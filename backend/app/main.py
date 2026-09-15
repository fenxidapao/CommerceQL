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

from app.api.routers import health
from app.core.config import AppEnv, get_settings
from app.obs import metrics
from app.obs.logging import configure_logging, get_logger

__all__ = ["app", "create_app"]

#: API 版本前缀。⚠️ 破坏性变更**必须**升 `/api/v2/`（07 §4.5），
#: 且"语义变更"一律视为破坏性变更 —— 那是最隐蔽的一种：前端不报错，只会算错。
API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动/关闭钩子。

    ⚠️ 阶段 0 故意**留空**，但必须把"W1B 要在这里做什么"写清楚，
    否则接线时会漏 —— 07 §18.4 有 4 条**只能在这里**做的断言
    （`app.core.config.STARTUP_ASSERTIONS_DELEGATED_TO_W1B`）。
    它们共同的特征是：**必须连上真实依赖才能判定**，纯配置层校验不出来。
    """
    # --- 启动 ---
    #
    # ★ U-19 硬要求 ①②：τ 未校准时**必须可见、不得隐瞒**。
    #   这是阶段 0 唯一实做的启动动作 —— 它不碰任何外部依赖（不连库、不拉模型），
    #   因此不会把"起不来"与"依赖没就绪"混成一件事（见本文件顶部装配原则）。
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    logger = get_logger(__name__)

    metrics.set_binding_tau_calibrated(settings.binding_tau_is_calibrated)
    if not settings.binding_tau_is_calibrated:
        logger.warning(
            "binding_tau_is_calibrated=false",
            app_env=str(settings.APP_ENV),
            extra_fact="τ 未校准，L4 精排结果不可用于生产判定",
            env_gated=True,
            why="U-19（07 §18.4.1）：非 prod 放行但不隐瞒；prod 下会直接拒绝启动",
        )

    # W1B: 执行 STARTUP_ASSERTIONS_DELEGATED_TO_W1B 的 4 条断言（失败即拒绝启动）
    # W2A: 语义包 §6.1 五步校验 + 版本指针读取
    # W7 : 接线 health.register_probe（元数据库/checkpointer/Redis/语义包/LLM/embedding）
    yield
    # --- 关闭 ---
    # W7 : 优雅停机六步（07 §18.3）—— 摘 readiness → drain 在途 SSE ≤30s →
    #      未完成的流发 error(INTERNAL) 且 terminal:true（**不得静默断连**）→
    #      释放会话锁（finally）+ 归还连接 → 写审计 outcome=failed → 退出


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
