"""依赖注入接线位 —— 进程级运行时对象、限流、会话锁、审计出口。

归属窗口：**归属待明确**（见下）。实现由 W1B 提供（用户裁定 `3.a`）。

## ⚠️ 归属登记（必须先看这条）

`docs/07 §3.2` 的目录树里有 `app/api/deps.py` 与 `app/api/ratelimit.py`，
但 `docs/08 §4.1` 的**归属权表**只写了：

- `app/api/errors.py`、`app/api/sse.py` → **W4**；
- `app/api/routers/**`（其余） → **W4**。

→ `deps.py` / `ratelimit.py` / `dto/**` **未被登记归属**。W1B 按 §3.3 的产出清单
（⑥ 会话串行锁 ⑦ 限流分桶）在此落位，并**登记为待架构窗口裁定**（Q-15 同类：
"清单外必需文件"）。若裁定归 W4，本文件应整体移交，**不得两边各留一份**（U-18 教训）。

## 本文件做什么、不做什么

**做**：把进程级的、与业务无关的东西（池 / Redis / 锁 / 限流 / 审计）从 `app.state`
取出来给端点用；以及两个**语义必须写在一处**的辅助器（限流拦截、会话锁守卫）。

**不做**：任何端点逻辑、任何 DTO、任何授权判定。授权一律用**显式传入**的
`IdentityContext`（`app/auth/context.py` 已声明 contextvar 不是授权依据）——
本文件提供一个便利取用点，但**不把 contextvar 变成授权来源**：
需要授权的调用点必须**要求实参**，所以下面的 `check_rate_limit` /
`session_lock_guard` 都把 `ctx` 写成**必填位置参数**，而不是"取不到就用 contextvar"。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from fastapi import Request

from app.api.ratelimit import RedisBucketRateLimiter
from app.auth.context import current_identity
from app.cache.session_lock import RedisSessionLock
from app.core.config import Settings
from app.core.contracts import (
    AuditSinkPort,
    IdentityContext,
    RateLimiterPort,
    SessionLockPort,
)
from app.core.enums import RateLimitBucket
from app.core.errors import CommerceQLError
from app.obs.audit import AuditWriter
from app.repo.audit_store import AuditStore
from app.repo.pools import ThreePools

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from redis.asyncio import Redis

__all__ = [
    "RUNTIME_STATE_KEY",
    "AppRuntime",
    "RateLimited",
    "build_runtime",
    "check_rate_limit",
    "get_audit_sink",
    "get_identity",
    "get_rate_limiter",
    "get_runtime",
    "get_session_lock",
    "session_lock_guard",
]

#: `app.state` 上的键名。**用带前缀的字符串常量而不是属性名**：
#: `app.state.redis` 这种松散的属性写在多个模块里，改名时不会有任何静态检查发现。
RUNTIME_STATE_KEY: Final[str] = "commerceql.runtime"


@dataclass(frozen=True, slots=True)
class AppRuntime:
    """进程级运行时的**唯一持有对象**。

    为什么打包成一个不可变对象，而不是让端点各自 `request.app.state.xxx`：
    "这个进程到底有哪些运行时依赖"必须能**一次看全**。散着放的话，
    新增一个依赖（例如 pgbouncer 之后的第二个 Redis）不会有任何地方需要同步更新，
    而漏掉的地方表现为运行时 `AttributeError` —— 在生产上就是 500。
    """

    settings: Settings
    pools: ThreePools
    redis: Redis
    session_lock: SessionLockPort
    rate_limiter: RateLimiterPort
    audit: AuditSinkPort


def build_runtime(
    *,
    settings: Settings,
    pools: ThreePools,
    redis: Redis,
) -> AppRuntime:
    """组装运行时对象。**纯构造，不做 I/O**（连接是惰性的）。

    ⚠️ 三个具体实现（锁 / 限流 / 审计）在这里 `new` 出来而不是让调用方注入：
    它们都只依赖 `client` 或 `engine`，没有第二份配置；
    允许注入只会造出"测试里用 A、生产里用 B"的差异面 —— 而这类差异
    恰好会让契约测试（用假实现）全绿、生产（用真实现）出问题。
    需要测它们的**行为**时，测试直接构造实现类并配 fake client，不经过本函数。
    """
    return AppRuntime(
        settings=settings,
        pools=pools,
        redis=redis,
        session_lock=RedisSessionLock(redis),
        rate_limiter=RedisBucketRateLimiter(redis),
        # 审计的 fail-closed 语义在 `obs/audit.py`，SQL 在 `repo/audit_store.py`（§12.4.1 的分工）。
        audit=AuditWriter(AuditStore(pools.metadata)),
    )


def get_runtime(request: Request) -> AppRuntime:
    """取运行时对象。**未装配时明确报错**，不返回一个"半可用"的替身。"""
    runtime = getattr(request.app.state, RUNTIME_STATE_KEY, None)
    if runtime is None:
        raise CommerceQLError(
            "运行时未装配：app.state 上没有 AppRuntime —— "
            "startup 未执行或测试未走 lifespan（不得用替身兜底：那会掩盖真实的装配缺陷）"
        )
    return runtime  # type: ignore[no-any-return]


def get_identity() -> IdentityContext:
    """当前请求的 `IdentityContext`（第 7 步的 contextvar）。

    ⚠️ 仅供端点**读取**（日志 / 审计 / 传参）。授权判定的实参必须显式传下去，
    不得让 `guard` / `exec` 自己回头来这里取 —— contextvar 在后台任务里会继承**过期身份**。
    """
    return current_identity()


def get_session_lock(request: Request) -> SessionLockPort:
    return get_runtime(request).session_lock


def get_rate_limiter(request: Request) -> RateLimiterPort:
    return get_runtime(request).rate_limiter


def get_audit_sink(request: Request) -> AuditSinkPort:
    return get_runtime(request).audit


# ---------------------------------------------------------------------------
# 两个语义必须写在一处的辅助器
# ---------------------------------------------------------------------------

async def check_rate_limit(
    request: Request, bucket: RateLimitBucket, ctx: IdentityContext
) -> None:
    """限流拦截。超限 → 抛 `RateLimited`（映射为 `429`，**由端点层的统一出口**处理）。

    ⚠️ 这里**不构造 HTTP 响应**：`app/api/errors.py` 是"异常 → 错误码"的唯一映射点。
    在限流器里自己造 `JSONResponse(429)` 会让"响应头怎么给"出现第二处实现 ——
    而 `Retry-After` 与 `X-RateLimit-*` 恰恰是最容易两处不一致的地方。
    """
    decision = await get_rate_limiter(request).check(bucket, ctx)
    if not decision.allowed:
        raise RateLimited(bucket, decision.retry_after_s)


class RateLimited(CommerceQLError):
    """限流拒绝（`429`）。

    ⚠️ 定义在本模块而**不**加进 `app/core/errors.py`（W0 持有）：那里放的是
    "可跨层抛出的领域异常"，而入口限流是**接入层**的概念
    （图内部的 L2 上游并发 / L4 数据库并发拒绝另有其表达，不走这里）。
    若架构窗口认为它该收进 `core/errors.py`，本类应整体迁走，**不得留两份**。
    """

    default_code = "RATE_LIMITED"

    def __init__(self, bucket: RateLimitBucket, retry_after_s: int | None) -> None:
        super().__init__(
            "请求过于频繁，请稍后重试",
            # ⚠️ `detail` 只放桶名与倒计时 —— 不含用户标识、不含键
            #    （键里虽已哈希，但它出现在**用户可见响应**里没有任何收益）。
            detail={"bucket": bucket.value, "retry_after_s": retry_after_s},
        )
        self.bucket = bucket
        self.retry_after_s = retry_after_s


@asynccontextmanager
async def session_lock_guard(
    request: Request, ctx: IdentityContext
) -> AsyncIterator[str]:
    """会话锁守卫：**acquire 在进图之前，release 在 `finally`**（07 §9.3）。

    用法（W4 的端点）：

        async with session_lock_guard(request, ctx) as lock_key:
            result = await run_graph(...)

    ⚠️ 为什么用 `asynccontextmanager` 而不是 FastAPI 的 `yield` 依赖：
    `yield` 依赖的清理**在响应生成之后**执行，而本项目的 SSE 响应是**流式**的 ——
    "响应生成完"与"图跑完"不是同一时刻。锁必须在**图结束**时释放，
    否则会出现"流还在推事件、锁已经放掉、第二个请求已进入同一会话"。
    显式 `async with` 把释放点钉在代码结构上，不依赖框架的清理时机。

    ⚠️ 客户端断连也必须释放：`asynccontextmanager` 的 `finally` 在
    `CancelledError` / `GeneratorExit` 时同样执行 —— 这正是 07 §9.3
    "释放位置：api 层的 finally（客户端断连也必须释放）"要的效果。
    """
    runtime = get_runtime(request)
    key = await runtime.session_lock.acquire(
        ctx,
        ttl_s=runtime.settings.SESSION_LOCK_TTL_S,
        wait_ms=runtime.settings.SESSION_LOCK_WAIT_MS,
    )
    try:
        yield key
    finally:
        await runtime.session_lock.release(key, ctx.task_id)
