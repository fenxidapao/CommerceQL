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

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from fastapi import Request

from app.api.errors import IDENTITY_STATE_KEY
from app.api.ratelimit import RateLimitQuota, RedisBucketRateLimiter
from app.api.state_store import RedisStateStore
from app.auth.context import bind_identity, build_identity, current_identity, reset_identity
from app.auth.jwks import JwksCache, PemFileJwksSource
from app.auth.revocation import InMemoryRevocationList
from app.auth.tokens import TokenVerifier, VerifiedToken
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
from app.obs.trace import TraceIds, bind_ids, new_id, reset_ids
from app.repo.audit_store import AuditStore
from app.repo.pools import ThreePools

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from redis.asyncio import Redis

    from app.graph.context import GraphDeps

__all__ = [
    "GRAPH_RUNTIME_STATE_KEY",
    "RUNTIME_STATE_KEY",
    "AppRuntime",
    "GraphRuntime",
    "RateLimited",
    "authenticate",
    "build_runtime",
    "build_token_verifier",
    "check_rate_limit",
    "get_audit_sink",
    "get_graph_runtime",
    "get_identity",
    "get_rate_limiter",
    "get_runtime",
    "get_session_lock",
    "get_state_store",
    "new_identity",
    "remember_identity",
    "session_lock_guard",
    "trace_scope",
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


#: `app.state` 上的第二个键：**图运行时**（与进程级 `AppRuntime` 分开）。
#:
#: ⚠️ 为什么不并进 `AppRuntime`：那个对象在 lifespan 第 2 步就装好了（纯构造、无 I/O），
#: 而图运行时需要**编译后的图 + 三包装配**（T6，在 checkpointer 之后）——
#: 合成一个对象会让"图还没装好"变成"运行时也没有"，而那会让健康探针与限流一起挂掉。
GRAPH_RUNTIME_STATE_KEY: Final[str] = "commerceql.graph_runtime"


@dataclass(frozen=True, slots=True)
class GraphRuntime:
    """图端点所需的三个东西 + 一个**每请求依赖工厂**。

    ⚠️ `new_deps` 是**工厂**而不是 `GraphDeps` 实例，这是接线的正确性前提：
    `GraphDeps.planner` 是 `PlannerEngine`，而它**必须每请求一实例**
    （内部 `_pending` 会跨请求串事件，见 `graph/context.py` 的模块 docstring 理由 3）。
    若这里放实例，端点就会在编译期共享一个引擎 —— 并发时 A 请求的降级事件发给 B 的流。
    把它写成 `Callable[[], GraphDeps]` 让"每请求一份"在类型层面无法被写错。

    ⚠️ `graph` 用 `Any` 而不是 `CompiledStateGraph[...]`：LangGraph 的泛型参数在
    mypy 下需要 `GraphState` + 四个位置参数（`None, GraphState, GraphState`），
    而这里只需要"有个能 `astream` 的东西" —— 真正的方法签名由 `runner.py` 的调用点约束。
    """

    graph: Any
    store: RedisStateStore
    verifier: TokenVerifier
    new_deps: Callable[[], GraphDeps]


def build_token_verifier(settings: Settings) -> TokenVerifier:
    """装配认证链路 1–5 步（`app/auth/**` 由 W1B 提供，本函数只做**组装**）。

    ⚠️ **纯构造、零 I/O**：`PemFileJwksSource` 只记住路径，真正的文件读发生在第一次
    `verify()` 里（`JwksCache._refresh`）。这条性质很重要 —— 组装根在 lifespan 里调用它，
    而 07 §18.2 要求"起不来"与"依赖没就绪"是两件事：公钥文件缺失时进程**照常启动**，
    请求按 `AUTH_FAILED` 拒绝，而不是让整个服务无法启动。

    ⚠️ 撤销名单用 `InMemoryRevocationList`（进程内）—— 这是 W1B 提供的实现，
    多实例部署下各自持有自己的名单（生产该换成 Redis 名单）。**此处不发明第二种实现**：
    登记为接线事实，见交付件的"未接线/已知限制"节。
    """
    return TokenVerifier(
        jwks=JwksCache(PemFileJwksSource(settings.JWT_PUBLIC_KEY_PATH)),
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        revocation=InMemoryRevocationList(),
    )


def get_graph_runtime(request: Request) -> GraphRuntime:
    """取图运行时。**未装配时明确报错**（同 `get_runtime` 的理由，不返回替身）。"""
    runtime = getattr(request.app.state, GRAPH_RUNTIME_STATE_KEY, None)
    if runtime is None:
        raise CommerceQLError(
            "图运行时未装配：app.state 上没有 GraphRuntime —— T6 的装配段未执行"
            "（不得用替身兜底：那会让「图没装好」表现为一次空转的成功响应）"
        )
    return runtime  # type: ignore[no-any-return]


def get_state_store(request: Request) -> RedisStateStore:
    """接入层状态读写器（`task_state` / 会话 / 幂等 / 澄清）。"""
    return get_graph_runtime(request).store


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
# 认证 → 身份（第 1–7 步的接线；**本文件只做组装，不做任何授权判定**）
# ---------------------------------------------------------------------------

async def authenticate(request: Request) -> VerifiedToken:
    """第 1–5 步：从 `Authorization` 头验签，取回**已确认的令牌事实**。

    作为 FastAPI 依赖使用（`Depends(authenticate)`）：失败即抛 `AuthError`
    （`app/auth/errors.py`，W1B 提供），由全局处理器映射成 `AUTH_FAILED` / `TOKEN_REVOKED`。

    ⚠️ 只做"验签"，**不做授权**：本函数不读路径参数、不读请求体、不判角色。
    授权判定的实参必须由端点**显式**传给下游（`guard` / `exec`），
    不得让它们回头取 contextvar（`auth/context.py` 已就此立规）。

    ⚠️ 为什么返回 `VerifiedToken` 而不是直接返回 `IdentityContext`：
    `IdentityContext` 还含 `trace_id`/`task_id`/`session_id` ——
    它们**由服务端生成**，而其中两个要等端点解析完请求才知道（见 `new_identity`）。
    在依赖里提前生成会让"同一个请求的 task_id"取决于依赖解析顺序（FastAPI 不保证顺序）。
    """
    runtime = get_graph_runtime(request)
    return await runtime.verifier.verify(request.headers.get("Authorization"))


def new_identity(
    token: VerifiedToken, *, session_id: str, task_id: str | None = None
) -> IdentityContext:
    """第 6 步：令牌事实 + **服务端生成**的运行标识 → `IdentityContext`。

    - `trace_id` 每次请求新生成（07 §15.2 的 trace 起点，服务端生成）；
    - `task_id` 默认新生成；**幂等重放时传入原 `task_id`**（§A.12："同 key 返回同一 `task_id`"）；
    - `session_id` 由调用方给：来自请求体（`/query`）、澄清上下文（`/clarify`）、
      路径参数（`/session/{id}`）或服务端新建。

    ⚠️ 三个 id 一律走 `app.obs.trace.new_id()`（**唯一的 id 生成器**）：
    前缀规则（`tr_`/`tk_`/`ss_`）与 `TraceIds` 的绑定在同一处，日志里贴出来的 id
    不必再查表就知道是 task 还是 session。
    """
    return build_identity(
        token,
        trace_id=new_id("trace"),
        task_id=task_id or new_id("task"),
        session_id=session_id,
    )


@asynccontextmanager
async def trace_scope(ctx: IdentityContext) -> AsyncIterator[None]:
    """绑定**两条**上下文通道：链路 id（`obs.trace`）+ 身份（`auth.context`）。

    ⚠️ 两条都要绑，缺一条就有可见后果：

    - 不绑 `TraceIds` ⇒ 日志缺 `trace_id`（07 §15.2 的链路断裂，"按 trace_id 查日志"失效）；
    - 不绑 `IdentityContext` ⇒ **错误响应里的 `trace_id` 恒 `null`** ——
      `errors._trace_id_of` 读的正是身份通道（它不从 `X-Trace-Id` 取，那是客户端可伪造的输入）。

    ⚠️ 生命周期与 `SseRunner` 的分工：本 CM 包住**整个端点**（含非 SSE 的普通响应），
    而 `SseRunner.stream()` 在**流内**自己再绑一次（用**自己的** token 还原）——
    那边的理由很具体：流可能在响应返回**之后**才被迭代，端点层的 `finally` 已经跑完了。
    两次绑定不冲突（各自 set/reset，LIFO 成对）。
    """
    ids_token = bind_ids(
        TraceIds(trace_id=ctx.trace_id, task_id=ctx.task_id, session_id=ctx.session_id)
    )
    identity_token = bind_identity(ctx)
    try:
        yield
    finally:
        reset_identity(identity_token)
        reset_ids(ids_token)


def remember_identity(request: Request, ctx: IdentityContext) -> None:
    """把身份记到 `request.state`（**ASGI scope 级**）。

    🔴 为什么不能只靠 contextvar：`trace_scope` 的 `finally` 在**异常处理器之前**执行
    （端点的 `async with` 先退出，异常才冒泡到 `ExceptionMiddleware`）⇒
    错误响应里的 `trace_id` 恒 `null`、`role` 恒取不到。实测踩过：
    `detail` 因此对所有角色都不下发（收口被静默全关），而"`detail: null` 看起来很正常"。
    详见 `errors._identity_of`。

    ⚠️ 每个端点**在身份落地后立刻**调用它（顺序上必须在任何可能抛错的步骤之前）。
    """
    setattr(request.state, IDENTITY_STATE_KEY, ctx)


# ---------------------------------------------------------------------------
# 两个语义必须写在一处的辅助器
# ---------------------------------------------------------------------------

async def check_rate_limit(
    request: Request, bucket: RateLimitBucket, ctx: IdentityContext
) -> RateLimitQuota:
    """限流拦截。超限 → 抛 `RateLimited`（映射为 `429`，**由端点层的统一出口**处理）。

    ⚠️ 这里**不构造 HTTP 响应**：`app/api/errors.py` 是"异常 → 错误码"的唯一映射点。
    在限流器里自己造 `JSONResponse(429)` 会让"响应头怎么给"出现第二处实现 ——
    而 `Retry-After` 与 `X-RateLimit-*` 恰恰是最容易两处不一致的地方。

    ⚠️ 返回值的来源是**实现类上的 `check_with_quota`**（若它存在）——
    端口 `RateLimiterPort` 只有 `check`，因为"配额三数"是接入层展示需要的东西，
    不属于 L0 端口契约（见 `app/api/ratelimit.RateLimitQuota` 的理由）。
    实现上没有那个方法时**降级为只回判定**：此时三头不下发、`Bucket` 头照发 ——
    这是"如实少三个头"，而不是编一个看起来合理的剩余额度。
    """
    limiter = get_rate_limiter(request)
    detailed = getattr(limiter, "check_with_quota", None)
    quota = (
        await detailed(bucket, ctx)
        if callable(detailed)
        else RateLimitQuota(decision=await limiter.check(bucket, ctx))
    )
    if not quota.decision.allowed:
        raise RateLimited(quota)
    return quota


class RateLimited(CommerceQLError):
    """限流拒绝（`429`）。

    ⚠️ 定义在本模块而**不**加进 `app/core/errors.py`（W0 持有）：那里放的是
    "可跨层抛出的领域异常"，而入口限流是**接入层**的概念
    （图内部的 L2 上游并发 / L4 数据库并发拒绝另有其表达，不走这里）。
    若架构窗口认为它该收进 `core/errors.py`，本类应整体迁走，**不得留两份**。

    ⚠️ 携带 `quota`（不是只带桶名与倒计时）：`429` 的四个 `X-RateLimit-*` 头
    **必须与本次判定同源** —— 若处理器自己再算一次剩余额度，就会出现
    "响应说还剩 3 次、状态码却是 429"的自相矛盾（§A.0.6 的补充规则要防的正是这个）。
    """

    default_code = "RATE_LIMITED"

    def __init__(self, quota: RateLimitQuota) -> None:
        bucket = quota.decision.bucket
        super().__init__(
            "请求过于频繁，请稍后重试",
            # ⚠️ `detail` 只放桶名与倒计时 —— 不含用户标识、不含键
            #    （键里虽已哈希，但它出现在**用户可见响应**里没有任何收益）。
            detail={"bucket": bucket.value, "retry_after_s": quota.decision.retry_after_s},
        )
        self.quota = quota
        self.bucket = bucket
        self.retry_after_s = quota.decision.retry_after_s


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
