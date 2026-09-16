"""ASGI 入口 —— 组装根（composition root）。

⚠️ **清单外必需文件（Q-15）**：docs/08 §3.1 的落地清单里没有 `app/main.py`，
但 `deploy/docker-compose.yml` 必须有一个可被 uvicorn 加载的入口
（`uvicorn app.main:app`），否则阶段 0 的 DoD①「`up` 后 `/healthz/live` 返回 200」
**在字面上无法达成**。因此本文件是"缺它就交付不了 DoD"的必要补充，而不是顺手扩张：
内容只有装配，**零业务逻辑**。

装配原则：
- 这里是**唯一**允许把 L5（`api`）与 L0（`core`）拼在一起的地方 —— 组装根天然横跨各层；
- 不在 import 期做任何 I/O（连库、拉模型、读文件都不做）——
  否则"起不来"与"依赖没就绪"会混成一个错误，且 uvicorn `--reload` 会因为 import 期 I/O 反复卡住。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import RUNTIME_STATE_KEY, build_runtime
from app.api.routers import health
from app.core.config import AppEnv, get_settings
from app.core.enums import Dependency
from app.graph.build import CheckpointSetupOutcome, ensure_checkpoint_schema
from app.obs import metrics
from app.obs.logging import configure_logging, get_logger
from app.repo.health import build_probe_table
from app.repo.pools import build_three_pools
from app.repo.redis import build_redis_client
from app.repo.startup_assertions import enforce_startup_assertions, live_probes

__all__ = ["app", "create_app"]

#: API 版本前缀。⚠️ 破坏性变更**必须**升 `/api/v2/`（07 §4.5），
#: 且"语义变更"一律视为破坏性变更 —— 那是最隐蔽的一种：前端不报错，只会算错。
API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """启动/关闭钩子。

    ⚠️ **顺序是有约束的，不是随手排的**（07 §18.2 / §18.4）：

    1. 日志装配 → 2. τ 校准告警（U-19 硬要求①②，**不碰外部依赖**，必须最先可见）
    → 3. **三池 + Redis**（纯构造，连接惰性）
    → 4. **启动断言**（第一次真实 I/O）
    → 5. **checkpointer 开池 + 确保 `lg` 表族**（探针要靠它判定）
    → 6. **注册健康探针**

    ⚠️ 第 4 步有**两种失败**，处置相反（`repo/reachability.py` 是唯一分类点）：
    · **配置级不合格**（角色是超级用户 / 审计表可写 / 维度不匹配）→ **拒绝启动**，任何环境；
    · **依赖连不上 → 无法判定** → 非 prod **放行**（打 WARN，`/healthz/ready` 报 503），
      仅 prod 拒绝启动。把后者当致命会让「**服务起来了、但硬依赖未接**」这个状态
      **不可达** —— 而 07 §18.2 的探针语义（摘流量不重启）与 §18.4.1
      （`live=200` 且 `ready=503` **必须可达**）都要求它可达。

    ⚠️ 为什么 4 在 5 之前：启动断言里的 `analytics_dsn_is_read_only` 必须
    在**任何池取连接之前**判定 —— 否则"连不上"与"角色配错了"会混成一个池超时，
    排查方向被引到"数据库挂了"。断言用的是直连 psycopg（见 `_fetch_analytics_role`）。

    ⚠️ 为什么 6 在 5 之后：探针注册进去的是**已经开好的池**。
    先注册再开池，第一次 `/healthz/ready` 会打到未打开的池上（`PoolClosed`），
    于是"服务刚起来的那几秒"必然显示不健康 —— 而 LB 恰好在那一刻决定给不给流量。
    """
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    logger = get_logger(__name__)

    # --- 1. τ 校准可见性（U-19 硬要求 ①②）---
    metrics.set_binding_tau_calibrated(settings.binding_tau_is_calibrated)
    if not settings.binding_tau_is_calibrated:
        logger.warning(
            "binding_tau_is_calibrated=false",
            app_env=str(settings.APP_ENV),
            extra_fact="τ 未校准，L4 精排结果不可用于生产判定",
            env_gated=True,
            why="U-19（07 §18.4.1）：非 prod 放行但不隐瞒；prod 下会直接拒绝启动",
        )

    # --- 2. 三池 + Redis（**纯构造，不做 I/O**）---
    pools = build_three_pools(settings)
    redis_client = build_redis_client(settings)
    runtime = build_runtime(settings=settings, pools=pools, redis=redis_client)
    setattr(application.state, RUNTIME_STATE_KEY, runtime)

    # --- 3. 启动断言（07 §18.4：失败即拒绝启动）---
    outcomes = await enforce_startup_assertions(
        settings,
        live_probes(settings, metadata_engine=pools.metadata),
        logger=logger,
    )
    logger.info(
        "startup_assertions_done",
        passed=[o.name for o in outcomes if o.status.value == "pass"],
        pending=[o.name for o in outcomes if o.status.value == "pending"],
        pending_note="pending = 前置条件尚未具备（依赖上游窗口），不是通过",
        why="07 §18.4 / N-15：宁可起不来，也不要带着错配置跑起来",
    )

    # --- 4. checkpointer：开池 + 确保 lg 表族 ---
    # `wait=False`：不在启动路径上阻塞等连接。池连不上时**不应该**卡住启动 ——
    # 那是 readiness 该报告的事（摘流量），而不是"进程起不来"（07 §18.2 的失败动作不同）。
    await pools.checkpoint.open(wait=False)
    schema_outcome = await ensure_checkpoint_schema(pools.checkpoint)
    if schema_outcome is CheckpointSetupOutcome.CREATED:
        logger.warning(
            "checkpoint_schema_created",
            extra_fact="lg 表族不齐，本次启动了 AsyncPostgresSaver.setup() —— 通常意味着新库或表被删",
            why="07 §5.5：检查点表族由 setup() 建；本分支应只在首次部署出现",
        )
    elif schema_outcome is CheckpointSetupOutcome.UNREACHABLE:
        logger.warning(
            "checkpoint_schema_check_skipped",
            extra_fact="连不上元数据库 —— lg 表族是否就绪**未被检查**（不是「本来就齐」）",
            why=(
                "07 §18.2：readiness 会如实报 503（摘流量**不重启**）。"
                "本分支不得被读成「无需建表」：症状与日志方向相反，会把排查引偏"
            ),
        )

    # --- 5. 健康探针（本窗口只接三个，其余槽位保持"未接线"的如实上报）---
    probes = build_probe_table(
        metadata_engine=pools.metadata,
        checkpoint_pool=pools.checkpoint,
        redis_client=redis_client,
    )
    for dependency, probe in probes.items():
        health.register_probe(dependency, probe)
    logger.info(
        "health_probes_registered",
        wired=[d.value for d in probes],
        still_unwired=[
            d.value for d in Dependency if d not in probes
        ],
        why="未接线项由 health._unwired_probe 如实上报 healthy=false —— 不谎报健康（N-21）",
    )

    yield

    # --- 关闭 ---
    # W4/W7 还要在这里加：摘 readiness → drain 在途 SSE ≤30s →
    #   未完成的流发 error(INTERNAL) 且 terminal:true（**不得静默断连**）→
    #   释放会话锁（finally）+ 写审计 outcome=failed（07 §18.3）。
    # 本窗口只负责**释放自己创建的连接资源** —— 不替后续窗口假装做完停机六步。
    await redis_client.aclose()
    await pools.checkpoint.close()
    await pools.metadata.dispose()
    await pools.analytics.dispose()


def create_app() -> FastAPI:
    """构造 FastAPI 应用。

    ⚠️ 会调用 `get_settings()` → **环境变量缺项时这里就失败**（N-15：宁可起不来）。
    这符合 07 §18.4 的 fail-fast；CI 与单测通过 `tests/conftest.py` 提供非密钥占位值。
    """
    settings = get_settings()

    app = FastAPI(
        title="CommerceQL —— 基于 Text2SQL 的电商数据分析 Agent",
        version="0.1.0",
        # 契约面：OpenAPI 是「机读载体」（07 §4.1 双载体原则），
        # 由 DTO 生成后进 CI 快照比对（§4.2 六步断言）。
        docs_url=f"{API_PREFIX}/docs" if settings.APP_ENV is not AppEnv.PROD else None,
        openapi_url=f"{API_PREFIX}/openapi.json" if settings.APP_ENV is not AppEnv.PROD else None,
        lifespan=lifespan,
    )

    # CORS：生产**关闭**（同源反代，07 §8.6.5 列为常见误配）。
    # `Settings` 已强制 prod 下该项为空，这里再判一次是为了避免"配置改了但代码照旧生效"。
    origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
    if origins and settings.APP_ENV is not AppEnv.PROD:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            # SSE 需要这几项透出，否则前端拿不到 event/data 帧
            expose_headers=["X-RateLimit-Bucket", "X-RateLimit-Limit",
                            "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"],
        )

    app.include_router(health.router, prefix=API_PREFIX)
    return app


#: uvicorn 入口：`uvicorn app.main:app`
#: 注意：保留进度已足够 —— SSE 流式响应**不应**因多进程/热重载被打断，
#: 生产用单进程 uvicorn（07 §18.1：多进程需先把 LLM 信号量改成 Redis 令牌桶）。
app = create_app()
