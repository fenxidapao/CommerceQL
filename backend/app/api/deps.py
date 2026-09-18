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

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType
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
from app.obs import metrics
from app.obs.audit import AuditWriter
from app.obs.logging import get_logger
from app.obs.trace import TraceIds, bind_ids, new_id, reset_ids
from app.repo.audit_store import AuditStore
from app.repo.feedback import FeedbackStore
from app.repo.pools import ThreePools

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from redis.asyncio import Redis

    from app.graph.context import GraphDeps

__all__ = [
    "GRAPH_RUNTIME_STATE_KEY",
    "RETRIEVAL_WEIGHTS",
    "RUNTIME_STATE_KEY",
    "AppRuntime",
    "GraphRuntime",
    "MetricsBindingObserver",
    "RateLimited",
    "SseDegradationSink",
    "SsePlannerDegradationSink",
    "authenticate",
    "build_graph_runtime",
    "build_runtime",
    "build_token_verifier",
    "check_rate_limit",
    "get_audit_sink",
    "get_feedback_store",
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
    #: 反馈落库（`POST /feedback` 的唯一写入通道，W1B 提供）。
    #: ⚠️ 收**引擎**（`pools.metadata`）而不是连接：借用/归还每语句一次，
    #: 零新增连接资源、零 shutdown 责任（同 `audit_store` / `query_plan` 的裁定）。
    feedback: FeedbackStore


def build_runtime(
    *,
    settings: Settings,
    pools: ThreePools,
    redis: Redis,
) -> AppRuntime:
    """组装运行时对象。**纯构造，不做 I/O**（连接是惰性的）。

    ⚠️ 四个具体实现（锁 / 限流 / 审计 / 反馈落库）在这里 `new` 出来而不是让调用方注入：
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
        # 反馈写入复用**元数据池**（W1B 开工指令 §1）：不新建连接资源。
        feedback=FeedbackStore(pools.metadata),
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
    #: 🔴 **长连资源**，由 `main.py` 的 lifespan 关闭区释放（W1B §9.2 / W3A §4）。
    #:
    #: ⚠️ 为什么它们必须挂在本对象上而不是局部变量：`build_graph_runtime` 是**函数**，
    #: 局部变量出了函数就没了 —— 而 `await gateway.aclose()`（否则 httpx 连接不释放）
    #: 与 `ledger.close()`（单条专用 psycopg 连接）都发生在**进程关闭时**。
    #: 不挂出来的直接后果是"开发期一切正常、压测/长跑后连接数只增不减"。
    gateway: Any | None = None
    cost_ledger: Any | None = None


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


def get_feedback_store(request: Request) -> FeedbackStore:
    """反馈落库通道（`POST /feedback` 用）。

    ⚠️ 与 `get_state_store` 的分工必须看清：那个返回 **Redis** 状态存储
    （task/session/幂等/澄清），本函数返回 **PostgreSQL** 的 `app.feedback` 访问对象。
    两者都不是"通用状态库"—— 把反馈写进 Redis 会绕开 §12.3 的表与
    `uq_feedback_task_user_reason` 的唯一约束，而幂等恰恰只由那个约束保证。
    """
    return get_runtime(request).feedback


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


# ===========================================================================
# T6：图运行时装配（由 `main.py` 的 lifespan 调用）
# ===========================================================================
#
# 为什么装配代码在这里而不是 `main.py`：`main.py` 的 lifespan 是**顺序**（六步的次序
# 有语义，见它的 docstring），把构造细节也塞进去会让"顺序"被二十行构造代码淹没。
# 本模块是"接线位"，构造放这里、顺序放那里（`build_runtime` 已经是同一分工）。
#
# ⚠️ 本节的函数**只在 lifespan 里调用一次**（进程级），绝不进请求路径 ——
# 唯一进请求路径的是 `GraphRuntime.new_deps`，它构造的是**每请求一份**的 `GraphDeps`。

#: 07 §6.7 的四路 RRF 权重（**逐字对齐该表，不是调优结果**）。
#:
#: ⚠️ 写成本模块的常量而不是 `Settings` 字段：07 §6.7 把这张表定为**契约**，
#: 而"降级时的权重重分配必须是确定性规则"（同节明文）。放进可配置项会让
#: "同一问题两次结果不同"从"不可能"变成"取决于谁改了 .env"。
#: `sparse_only` 的重分配（dense 的 0.40 按 0.35:0.10 分给 sparse/graph）在
#: `app/retrieval/fuse.effective_weights`，不在这里重复。
RETRIEVAL_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {"dense": 0.40, "sparse": 0.35, "value": 0.15, "graph": 0.10}
)

#: `SparseSearch` 的归一化标志与低分阈值（W2B 的装配示例用它自己的取值）。
_SPARSE_RANK_NORMALIZATION: Final[int] = 32
_SPARSE_SCORE_MIN: Final[float] = 0.05


def _report_degraded(reason: Any, action_taken: Any, detail: Any, *, source: str) -> None:
    """两条降级侧信道的**唯一**转出口（W3A 出站跳 + W3B 业务跳共用）。

    🔴 为什么收在一处：RELAY 说"两条通道缺一就有可见性缺口"，而两条通道的**转出语义
    完全相同**（reason + action_taken + detail → 当前请求的降级累积 + SSE 帧）。
    各写一份的结果是"其中一条忘了带 `detail`"，而那种缺陷在两条通道里表现不对称，
    最难发现的正是"只有某个特定降级路径丢字段"。

    ⚠️ **同步**（两个 sink 都是同步回调）：`RunContext.report_degraded` 也是同步的，
    所以这里**不需要** sync→async 桥接 —— 这正是 `report_degraded` 存在的意义
    （它在内部用 `EventRecorder.degraded`，后者直接 `Queue.put_nowait`）。
    ⇒ ☠️ 不得在此处 `await` / `asyncio.run`：`on_degraded` 在 `call()` 的同步段被调用，
    阻塞它会直接吃任务的延迟预算。

    ⚠️ `detail` 只进日志与 `GraphState.degradations`，**不进 SSE 帧**
    （C-08 的 `degraded.data` 只有 `{reason, action_taken, partial_result?}`）——
    这条口径由 `RunContext.report_degraded` 承担，本函数不重复处理。
    """
    from app.graph.context import current_run_context_or_none

    context = current_run_context_or_none()
    if context is None:
        # 无请求上下文 = 正常状态（离线评测 / 启动自检 / 直接构造引擎的单测），
        # 不是接线缺陷 ⇒ 如实记一条日志放行，**不抛**（见 `current_run_context_or_none`）。
        get_logger(__name__).info(
            "degradation_without_run_context",
            source=source,
            reason=str(reason),
            action_taken=str(action_taken),
            why="离线/启动期降级：没有请求可挂 ⇒ 只记日志（与 RunContext._recorder is None 同口径）",
        )
        return
    context.report_degraded(reason, action_taken, detail)


class SseDegradationSink:
    """W3A 的 `DegradationSink`（网关**出站跳**）→ 当前请求的 SSE 流。

    ⚠️ 默认实现（`_LoggingDegradationSink`）**不是空实现**，但它到不了 SSE：
    不接本类 = 前端看不到任何 LLM 降级（`switched_to_weak_model` / `llm_unavailable` …）。
    """

    __slots__ = ()

    def on_degraded(self, event: Any) -> None:
        _report_degraded(
            event.reason,
            event.action_taken,
            getattr(event, "detail", None),
            source="llm",
        )


class SsePlannerDegradationSink:
    """W3B 的 `PlannerDegradationSink`（planner **业务跳**）→ 当前请求的 SSE 流。

    ⚠️ 另一条通道（outcome 自带的 `degradations[]`）由节点写进 `GraphState.degradations`，
    与本类是**两条都要接**的关系，不是二选一。
    """

    __slots__ = ()

    def on_degraded(self, note: Any) -> None:
        _report_degraded(
            note.reason,
            note.action_taken,
            getattr(note, "detail", None),
            source="planner",
        )


class MetricsBindingObserver:
    """W3C 的 `BindingObserver` → W0 的 `obs.metrics` 计数器（N-27 约束⑤ 的计量端）。

    🔴 不接这一个的后果写在协议自己的 docstring 里：默认 `NullBindingObserver`
    什么都不做 ⇒ **指标面是缺的**（不是"已满足"）。`service.observer` 属性可查
    到底接的是本类还是空实现。

    ⚠️ **不自行登记同名 Counter**：指标本体由 W0 落（`binding_state_total` /
    `binding_layer_total`），本类只把 `BindingEvent` 的两个字段喂进去。
    自己登记一份 = 第二真相，两处会漂移且没有任何测试会红。

    ⚠️ `event.reason` 与概念名**只进日志**（无界基数，`obs.metrics` 明文禁止）
    ⇒ 本类把它们写进结构化日志而不是标签。
    """

    __slots__ = ()

    def on_binding(self, event: Any) -> None:
        from app.obs import metrics

        metrics.observe_binding_state(event.state)
        metrics.observe_binding_layer(event.layer)
        # ⚠️ 不 try/except：协议要求"实现不得抛"，而这两个函数是对**枚举**做的
        #    `dict[key] += 1`（`core.enums` 的冻结取值集），没有任何可抛的输入。
        #    包一层 `except Exception` 只会把"指标写坏了"变成静默的（调用侧还会兜一层）。
        get_logger(__name__).info(
            "binding_decision",
            binding_state=event.state.value,
            binding_layer=event.layer.value,
            reason=event.reason,
            scope_was_set=event.scope_was_set,
            tau_is_calibrated=event.tau_is_calibrated,
        )


def _metadata_fetch(engine: Any) -> Any:
    """元数据池上的**通用取数** —— `PgVectorStore` / `SparseSearch` 的注入物。

    🔴 这是**本窗口新增的接线件**，不是从哪个包抄来的：两个检索存储类都声明
    "取数经注入的 `fetch(sql, params)`（阶段 4 由 W4 注入元数据池的执行器）"，
    而 `app/repo/pools.py` 只提供 `ThreePools`，**没有**通用 `fetch`。
    本对象就是那句注释里的"执行器"，落在这里（W4 的接线位）而不是 `repo/`
    （W1B 域，要改请先提需求）。

    ⚠️ 三个刻意的性质：

    1. **每语句借还一次**（`async with engine.connect()`）—— 与 `AuditStore` /
       `QueryPlanStore` / `FeedbackStore` 同一纪律（07 §8.1 纪律 1）。持有连接会让
       "谁负责归还"含糊，漏归还的表现是池被慢慢抽干。
    2. **参数用 SQLAlchemy 的 `:name` 占位**（`text()` + `dict(params)`）——
       两个存储类的 SQL 模板就是 `:vector` / `:bundle_version` 这种形态，
       故**不做** `%(name)s` 改写（那是 psycopg 直连形态的写法，W2B 的评测脚本用）。
    3. **返回 `list[Mapping]`**（`mappings()`）而不是 tuple —— 调用方按列名取值。

    ⚠️ 之所以是**类**而不是闭包：`retrieval.Fetcher` 是"实例带异步 `__call__`"的
    Protocol，mypy 对"裸函数直接匹配 `__call__` Protocol"判定不稳定（实测报
    `arg-type`）；类实例在两侧都是精确形状，也让 docstring 有地方落。
    """
    from sqlalchemy import text

    class _MetadataFetcher:
        __slots__ = ("_engine",)

        def __init__(self, the_engine: Any) -> None:
            self._engine = the_engine

        async def __call__(self, sql: str, params: Mapping[str, Any]) -> list[Mapping[str, Any]]:
            async with self._engine.connect() as conn:
                result = await conn.execute(text(sql), dict(params))
                return [dict(row) for row in result.mappings().all()]

    return _MetadataFetcher(engine)



def _load_bundle_view(path: str) -> Any:
    """语义包 YAML → `BundleView`（检索面的只读视图）。

    ⚠️ 这里**再读一次 YAML**（`main.py` 已用 `load_bundle` 读过一次给
    `SemanticBundleRuntime`），这是**登记过的重复**，不是疏忽：

    - `BundleView.from_mapping` 要的是**原始 mapping**，而
      `SemanticBundleRuntime` 只把 `LoadedBundle` 藏在私有字段里（`_loaded`），
      没有暴露 mapping 的公开面 ⇒ 从运行时无法派生；
    - 拿 `LoadedBundle.bundle.model_dump()` 去凑不可取：那是**模型序列化**，
      与原始 YAML 在别名/默认值上的往返一致性没有任何测试保证 —— 用它等于
      在"检索看到的东西"与"语义层看到的东西"之间插一个未验证的转换。
    - W2B 自己的装配示例（`reports/w2b/recall_report.py`）也是这么做的。

    ⇒ 两次解析**同一个文件**（同一次启动内文件不变 ⇒ 无漂移）。
    已登记：建议 W2A 在 `SemanticBundleRuntime` 上暴露一个返回原始 mapping 的只读访问器，
    届时本函数改为从运行时取，重复即消除。
    """
    import yaml  # type: ignore[import-untyped]  # types-PyYAML 未进 dev 依赖（W0 白名单，同 semantics/loader.py）

    from app.retrieval.view import BundleView

    with open(path, encoding="utf-8") as fh:
        return BundleView.from_mapping(yaml.safe_load(fh))


def _gate3_thresholds(settings: Settings) -> dict[str, Any]:
    """`GraphDeps.gate3_thresholds` —— `CostThresholds` 的**字段名 → `Settings.GATE3_*`**。

    ⚠️ `graph/context.py` 原先注释说该映射"来源 = 语义包 `policy()`" —— **实测不成立**：
    `SemanticBundleRuntime.policy()` 只回 `deny_columns` / `applies_to_blacklist` 之类，
    **没有**成本阈值；语义包 YAML 里也 grep 不到 `gate3` / `total_cost` / `rows_pass`。
    唯一来源是 `Settings.GATE3_*`（`config.py:118-121`，且已有
    `total_cost_pass < total_cost_reject` 的交叉校验）。本函数按字段名映射
    （`CostThresholds.from_mapping` 的键名即字段名），**缺键由 dataclass 默认值兜底**
    （= 07 §7.5 原表）。该注释已同步订正。
    """
    return {
        "total_cost_pass": settings.GATE3_COST_WARN,
        "total_cost_reject": settings.GATE3_COST_REJECT,
        "rows_pass": settings.GATE3_ROWS_WARN,
        "rows_reject": settings.GATE3_ROWS_REJECT,
    }


def build_graph_runtime(
    *,
    settings: Settings,
    pools: ThreePools,
    redis: Redis,
    audit: AuditSinkPort,
    semantic_runtime: Any | None,
    checkpointer: Any | None = None,
) -> GraphRuntime | None:
    """装配图运行时（T6）。**返回 `None` 表示语义包不可用**（软依赖降级）。

    ⚠️ 为什么"语义包不可用 ⇒ 不装配"而不是"装一半"：
    `GraphDeps.semantics` / `binding` / `retrieval` 都**从语义包派生**（视图、τ、
    资产白名单）。语义包缺失时任何一个都造不出来，而造一个"能进图但一跑就炸"的运行时
    会让端点从"明确的 500 + 日志"退化成"看起来正常、跑到某个节点才炸"
    —— 后者在前端表现为**随机失败**。
    此时 `app.state` 上不设 `GRAPH_RUNTIME_STATE_KEY` ⇒ `get_graph_runtime` 的
    显式拒答生效（错误信息直接指出"装配段未执行"），而 readiness 已经因为
    `semantic_bundle_loaded` 探针报 503（摘流量）—— 两层都是**如实**的。

    ⚠️ 纯装配不做的两件事（都不在 T6 范围，见 §五的边界）：
    - 不 `await` 任何 I/O：`PemFileJwksSource` / `DbCostLedgerSink` / 三个池全是惰性连接
      （07 §18.2 要求"起不来"与"依赖没就绪"是两件事）；
    - 不注册任何健康探针（那是 `main.py` 的步骤 6）。
    """
    if semantic_runtime is None:
        get_logger(__name__).warning(
            "graph_runtime_not_assembled",
            reason="semantic_bundle_unavailable",
            extra_fact="图运行时**未**装配 ⇒ /query 等端点会以 500 明确拒答，不是『能用』",
            why="语义包是 GraphDeps 的派生源（视图/τ/白名单）；装一半会让失败随机化",
        )
        return None

    # --- 函数内 import：装配只在启动跑一次，模块 import 期保持廉价，也不会与 graph 成环 ---
    from app.binding.service import BindingService
    from app.core.clock import Clock
    from app.exec.executor import PgSqlExecutor
    from app.graph.build import build_graph
    from app.graph.context import GraphDeps
    from app.llm import build_gateway
    from app.mask.engine import SemanticMaskEngine
    from app.planner.engine import PlannerEngine
    from app.repo.cost_ledger import DbCostLedgerSink
    from app.repo.query_plan import QueryPlanStore
    from app.retrieval.dense import OllamaEmbedder, PgVectorStore
    from app.retrieval.search import RetrievalService
    from app.retrieval.sparse import SparseSearch

    logger = get_logger(__name__)

    # --- 1. 成本落库 sink + LLM 网关（W1B §9.2 / W3A §4）---
    # ⚠️ `settings.DATABASE_URL` 传**原值**（SQLAlchemy 形态），libpq 换算在 sink 内部。
    cost_ledger = DbCostLedgerSink(settings.DATABASE_URL)
    gateway = build_gateway(
        settings,
        ledger=cost_ledger,
        degradation=SseDegradationSink(),
    )

    # --- 2. 检索（W2B）---
    fetch = _metadata_fetch(pools.metadata)
    retrieval = RetrievalService(
        view=_load_bundle_view(settings.SEMANTIC_BUNDLE_PATH),
        embedder=OllamaEmbedder(
            base_url=settings.EMBEDDING_BASE_URL,
            model=settings.EMBEDDING_MODEL,
            dim=settings.EMBEDDING_DIM,
            timeout_s=float(settings.EMBEDDING_TIMEOUT_SECONDS),
            # ⚠️ `cache=None`：`CachePort` **全仓无实现**（`app/cache/` 只有键定义与
            #    会话锁；`runner.py` 的 P0 边界表已登记同一事实）。传 None = 每次真打
            #    Ollama，如实慢；不传会需要一个不存在的实现（编一个 = 第二真相）。
            cache=None,
        ),
        vector_store=PgVectorStore(fetch),
        sparse=SparseSearch(
            fetch,
            rank_normalization=_SPARSE_RANK_NORMALIZATION,
            score_min=_SPARSE_SCORE_MIN,
        ),
        weights=RETRIEVAL_WEIGHTS,
        rrf_k=settings.RRF_K,
        cache=None,
    )

    # --- 3. 掩码 / 执行（W2D）---
    mask = SemanticMaskEngine()
    executor = PgSqlExecutor(
        pools.analytics,
        mask,
        settings,
        bundle=semantic_runtime,
    )

    # --- 4. 绑定（W3C）：装配 + τ 断言 + gauge（U-19 §18.4.1 硬要求 ②）---
    binding_service = BindingService.from_settings(
        reader=semantic_runtime,
        settings=settings,
        observer=MetricsBindingObserver(),
    )
    # `assert_usable_tau()` 只做"坏配置 ⇒ ConfigError"（ε≤0 / τ≤0 / 已校准无 report_ref），
    # **不**重复 config 层的 prod 拒绝、**不**写指标、**不**校验"实际打分器 == τ 所绑"。
    calibrated = binding_service.assert_usable_tau()
    metrics.set_binding_tau_calibrated(calibrated)
    if not calibrated:
        logger.warning(
            "binding_tau_uncalibrated",
            extra_fact="τ 未校准 ⇒ L4 精排结果不可用于生产判定",
            env_gated=True,
            why="U-19：非 prod 放行但不得隐瞒（prod 会在 config 层直接拒绝启动）",
        )
    logger.info(
        "binding_service_assembled",
        observer=type(binding_service.observer).__name__,
        tau_is_calibrated=calibrated,
        why="observer 类型要能在这里一眼看到 —— 默认空实现时 N-27 约束⑤ 的指标面是缺的",
    )

    # --- 5. query_plan 写入通道（W1B §10，W3C DoD① 的最后一步）---
    query_plan_writer = QueryPlanStore(pools.metadata)

    # --- 6. 图（单例，可并发复用；依赖经 contextvars 每请求注入）---
    graph = build_graph(checkpointer=checkpointer)

    thresholds = _gate3_thresholds(settings)
    time_semantics = semantic_runtime.time_semantics()
    store = RedisStateStore(redis)

    def new_deps() -> GraphDeps:
        """**每请求一份** `GraphDeps`。

        🔴 `PlannerEngine` 在这里 `new`（而不是在装配期造一个共享实例）是硬约束：
        它唯一的可变状态 `_pending`（本次调用的降级累积）生命周期 = 一次公开方法调用，
        并发复用会**串降级事件**（A 请求的降级发给 B 的流）。把构造放进本工厂
        让"每请求一份"在**结构上**无法写错。
        ⚠️ `clock` 同理每请求一份：它持 `TimeSemantics` 与本请求无关，但共享实例
        没有任何收益，而"顺手共享"是下一次引入请求态的地方。
        ⚠️ **T7 待补**：本工厂尚未接 `set_binding_scope` / `set_call_context`
        （每请求上下文，缺则 L2 与过滤步③静默失效、计量归 `"(unset)"`）。
        """
        return GraphDeps(
            llm=gateway,
            planner=PlannerEngine(
                llm=gateway,
                semantics=semantic_runtime,
                clock=Clock(time_semantics),
                degradation=SsePlannerDegradationSink(),
            ),
            binding=binding_service,
            semantics=semantic_runtime,
            retrieval=retrieval,
            executor=executor,
            mask=mask,
            audit=audit,
            clock=Clock(time_semantics),
            # ⚠️ `None`：结果集缓存的唯一位置是 `result:{tenant}:{task_id}`，而
            #    `CachePort` 全仓无实现（与上面 embedder 的 cache 同一事实）。
            #    `mask` 节点因此走"写失败只告警"的已登记路径。
            result_cache=None,
            query_plan_writer=query_plan_writer,
            # ⚠️ `None`：`app/present/` 仍是空壳（W3B 归属）⇒ `present` 节点走
            #    §14.2 F4 降级（`present_failed` + `table_only`）。这意味着 **P0 下
            #    每个成功请求都会带一条 `degraded`** —— 这是既定 P0 形态（不是缺陷），
            #    已在 DELIVERY 显著登记。
            presenter=None,
            gate3_thresholds=thresholds,
            max_rows=settings.EXEC_MAX_ROWS,
            statement_timeout_ms=settings.EXEC_STATEMENT_TIMEOUT_MS,
        )

    return GraphRuntime(
        graph=graph,
        store=store,
        verifier=build_token_verifier(settings),
        new_deps=new_deps,
        gateway=gateway,
        cost_ledger=cost_ledger,
    )

