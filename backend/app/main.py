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

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, build_runtime
from app.api.routers import clarify, feedback, health, query, session
from app.core.config import AppEnv, get_settings
from app.core.enums import Dependency
from app.core.errors import SemanticBundleError
from app.graph.build import (
    GRAPH_VERSION,
    CheckpointSetupOutcome,
    ensure_checkpoint_schema,
)
from app.obs import metrics
from app.obs.logging import configure_logging, get_logger
from app.repo.health import build_probe_table
from app.repo.pools import build_three_pools
from app.repo.redis import build_redis_client
from app.repo.startup_assertions import enforce_startup_assertions, live_probes
from app.semantics import (
    SemanticBundleRuntime,
    build_semantic_bundle_probe,
    load_bundle,
    validate_bundle_path,
)

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

    # --- 2.5 语义包运行时（W2-INT 接线，软依赖：失败 = degraded，不拒绝启动）---
    # 加载失败（缺失/非法，loader 统一抛 SemanticBundleError）→ runtime 保持 None：
    # 探针如实报 unhealthy（HARD 依赖 → readiness 503），启动断言如实报 PENDING。
    # **非预期异常不吞** —— 那是 bug，fail-fast 暴露比 degraded 诚实。
    semantic_runtime: SemanticBundleRuntime | None = None
    try:
        semantic_runtime = SemanticBundleRuntime(
            load_bundle(
                settings.SEMANTIC_BUNDLE_PATH,
                embedding_model=settings.EMBEDDING_MODEL,
                embedding_dim=settings.EMBEDDING_DIM,
            )
        )
        logger.info(
            "semantic_bundle_loaded",
            bundle_version=semantic_runtime.active_version(),
            why="W2-INT 接线：探针与启动断言共用同一运行时实例，不各自 load_bundle（防多实例漂移）",
        )
    except SemanticBundleError as exc:
        logger.warning(
            "semantic_bundle_load_failed",
            detail=str(exc),
            bundle_path=settings.SEMANTIC_BUNDLE_PATH,
            why="软依赖降级：semantic_bundle_loaded 探针将如实报 unhealthy（readiness 503）",
        )

    async def _semantic_validator() -> None:
        """启动断言注入物（W2A RELAY §1①）：五步校验，失败抛 SemanticBundleError。"""
        await validate_bundle_path(
            settings.SEMANTIC_BUNDLE_PATH,
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_dim=settings.EMBEDDING_DIM,
        )

    # --- 3. 启动断言（07 §18.4：失败即拒绝启动）---
    outcomes = await enforce_startup_assertions(
        settings,
        live_probes(settings, metadata_engine=pools.metadata),
        logger=logger,
        semantic_validator=_semantic_validator,
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

    # --- 4.5 图运行时装配（T6，W4 追加段）---
    # ⚠️ 为什么在 4 之后：`build_graph(checkpointer=...)` 需要一个**已开**的 checkpoint 池；
    #    为什么在 5 之前：探针注册后 LB 立刻开始判定 readiness，而图运行时是否就绪
    #    会直接影响 `/query` 系端点能否工作（500 ⇔ 未装配），观测要在判定前落定。
    #
    # ⚠️ **本段只追加，不另立组装根**（W1B 纪律）：lifespan 的六步顺序归 W1B，
    #    W4 在此插入的只有"构造 + 挂 app.state"，顺序调整权在组装根窗口。
    #
    # ⚠️ 装配策略（W4 的装配决定，T-A1 最终裁定权在架构）：`SINGLE_SAVER_SHARED_POOL`
    #    —— 复用第 4 步**已开**的 `pools.checkpoint`（零新增连接资源，关闭权仍在
    #    lifespan 手里）；`setup=False` 因为 `ensure_checkpoint_schema` 刚刚跑过，
    #    再跑一次 `setup()` 只会在 PG 上多排一次 `pg_advisory_xact_lock`（无收益）。
    #    其余策略（PER_RUN_*）属"每请求建检查点"形态，与本装配（进程级单图）不匹配。
    from app.api.deps import build_graph_runtime
    from app.graph.build import CheckpointStrategy, make_checkpointer

    graph_runtime = None
    try:
        saver = await make_checkpointer(
            CheckpointStrategy.SINGLE_SAVER_SHARED_POOL,
            settings,
            pool=pools.checkpoint,
            setup=False,
        )
        graph_runtime = build_graph_runtime(
            settings=settings,
            pools=pools,
            redis=redis_client,
            audit=runtime.audit,
            semantic_runtime=semantic_runtime,
            checkpointer=saver,
        )
    except Exception as exc:
        # ⚠️ 装配失败**必须**让启动失败（fail-fast），但要把"哪件东西没装好"说出来 ——
        #    吞掉异常会让 lifespan 看似成功、端点 500、日志里却没有任何装配痕迹。
        #    与"依赖连不上 ⇒ 非 prod 放行"不同：这里是**配置/接线**错误，不是依赖抖动。
        logger.exception("graph_runtime_assembly_failed", error_type=type(exc).__name__)
        raise
    if graph_runtime is not None:
        setattr(application.state, GRAPH_RUNTIME_STATE_KEY, graph_runtime)
        logger.info(
            "graph_runtime_assembled",
            graph_version=GRAPH_VERSION,
            gateway=type(graph_runtime.gateway).__name__,
            why="T6：GraphRuntime 进 app.state ⇒ /query 系端点不再以 500 拒答",
        )

    # --- 5. 健康探针（W1B 三件 + W2A 语义包探针，其余槽位保持"未接线"的如实上报）---
    probes = build_probe_table(
        metadata_engine=pools.metadata,
        checkpoint_pool=pools.checkpoint,
        redis_client=redis_client,
    )
    for dependency, probe in probes.items():
        health.register_probe(dependency, probe)
    # W2-INT 接线（W2A RELAY §1②）：runtime 未装配时探针返回 healthy=False ——
    # 这是"未接线/包未就绪"的诚实表达，接上即转真。
    health.register_probe(
        Dependency.SEMANTIC_BUNDLE_LOADED,
        build_semantic_bundle_probe(lambda: semantic_runtime),
    )
    # readiness/aggregate 的 bundle_version 从这里读（health.SEMANTIC_RUNTIME_STATE_KEY）
    setattr(application.state, health.SEMANTIC_RUNTIME_STATE_KEY, semantic_runtime)
    wired = [*probes.keys(), Dependency.SEMANTIC_BUNDLE_LOADED]
    logger.info(
        "health_probes_registered",
        wired=[d.value for d in wired],
        still_unwired=[
            d.value for d in Dependency if d not in wired
        ],
        why="未接线项由 health._unwired_probe 如实上报 healthy=false —— 不谎报健康（N-21）",
    )

    yield

    # --- 关闭 ---
    # W4/W7 还要在这里加：摘 readiness → drain 在途 SSE ≤30s →
    #   未完成的流发 error(INTERNAL) 且 terminal:true（**不得静默断连**）→
    #   释放会话锁（finally）+ 写审计 outcome=failed（07 §18.3）。
    # 本窗口只负责**释放自己创建的连接资源** —— 不替后续窗口假装做完停机六步。
    #
    # --- 4.5 的关闭（W4 追加段：两条**长连资源**，先于三池）---
    # ⚠️ `gateway.aclose()` 释放 httpx 连接（W3A §4："不关则 httpx 连接不释放"）；
    #    `cost_ledger.close()` 释放单条专用 psycopg 连接（W1B §9.2："不关 = 泄漏"）。
    #    两者都必须在池关闭**之前**完成（顺序无关紧要但"先长连后池"最直观），
    #    且**各自兜底**：一条失败不得阻断另一条与池的释放（停机路径要走到头）。
    if graph_runtime is not None:
        import contextlib as _contextlib

        if graph_runtime.gateway is not None:
            with _contextlib.suppress(Exception):
                await graph_runtime.gateway.aclose()
        if graph_runtime.cost_ledger is not None:
            with _contextlib.suppress(Exception):
                graph_runtime.cost_ledger.close()
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
    # --- W4 端点（T5）---
    # ⚠️ 异常处理器必须装：`CommerceQLError` → HTTP 码的映射只有 `api/errors.py` 一处
    #    （不装它，领域异常会落到 Starlette 的默认 500，前端拿不到 `code`/`retryable`）。
    errors.install_exception_handlers(app)
    app.include_router(query.router, prefix=API_PREFIX)
    app.include_router(session.router, prefix=API_PREFIX)
    app.include_router(clarify.router, prefix=API_PREFIX)
    app.include_router(feedback.router, prefix=API_PREFIX)
    # 🔴 未接线（T6）：`app.state[GRAPH_RUNTIME_STATE_KEY]` 还没装配 ⇒ 上面三个端点
    #    会以 `500 INTERNAL`（`deps.get_graph_runtime` 的显式拒答）结束，**不是**"能用"。
    #    这一步必须与 `build_gateway` / `BindingService` / 图编译一起做（T6），
    #    不能只把图编译完就宣告端点可用（那会让 `/query` 变成"接了一半"）。
    return app


#: uvicorn 入口：`uvicorn app.main:app`
#: 注意：保留进度已足够 —— SSE 流式响应**不应**因多进程/热重载被打断，
#: 生产用单进程 uvicorn（07 §18.1：多进程需先把 LLM 信号量改成 Redis 令牌桶）。
app = create_app()
