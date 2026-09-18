"""接线位（`app/api/deps.py`）的离线自证 —— 装配、限流拦截、会话锁守卫。

归属窗口：W1B（实现随 `3.a` 裁定提供；文件归属待架构窗口裁定，见 `deps.py` 文件头）。

## 本文件存在的理由

`deps.py` 里有两条**语义必须写在一处**的辅助器（`check_rate_limit` / `session_lock_guard`）。
它们的行为差异全在**边界时刻**上，而边界恰恰是最容易被下游窗口各写一遍的地方：

| 容易被写错的点 | 后果 | 本文件怎么钉 |
|---|---|---|
| `session_lock_guard` 的释放写在 `yield` 之后但**不在 `finally`** | 图抛异常/客户端断连时锁不释放 → 会话锁死到 TTL | `test_lock_released_when_body_raises` / `..._on_cancellation` |
| 用 FastAPI 的 `yield` 依赖代替 `async with` | 清理在**响应生成之后**，而 SSE 是流式的 → "流还在推、锁已放掉" | `test_guard_releases_before_returning_to_caller` 断言释放发生在 `async with` 退出时（而非进程后续） |
| 限流器自己造 `JSONResponse(429)` | `Retry-After` / `X-RateLimit-*` 出现第二处实现，与 `api/errors.py` 分叉 | `test_rate_limit_raises_domain_error_not_http_response` |
| 取不到 `ctx` 就回退到 contextvar | contextvar 在后台任务里会继承**过期身份** → 越权 | `test_helpers_require_identity_as_explicit_argument` |

## 刻意**不**测的东西

- 真 Redis 上的锁/限流语义：`tests/integration/test_real_redis_lock_and_ratelimit.py`（真脚本）；
- 端点级行为（HTTP 码、响应头）：W4 的端点与 `app/api/errors.py` 的映射，本文件只验
  "抛的是**领域异常**且带对的信息"，**不替 W4 决定 HTTP 码**。

⚠️ `build_runtime` 的"不做 I/O"是本文件能用真 `Settings`/`ThreePools` 的前提：
`build_three_pools` 是纯构造 + 装配期断言（`app/repo/pools.py`），Redis 客户端也是惰性的。
本文件**不连任何外部依赖** —— 离线可跑，不会被 skip 掉（"跳过"在 pytest 里显示为绿色，护栏会变摆设）。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from dataclasses import FrozenInstanceError
from typing import cast

import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from starlette.requests import Request

from app.api import deps
from app.api.deps import (
    AppRuntime,
    RateLimited,
    build_runtime,
    check_rate_limit,
    get_audit_sink,
    get_identity,
    get_rate_limiter,
    get_runtime,
    get_session_lock,
    session_lock_guard,
)
from app.api.errors import map_exception
from app.api.ratelimit import RateLimitQuota, RedisBucketRateLimiter
from app.cache.session_lock import RedisSessionLock
from app.core.config import get_settings
from app.core.contracts import IdentityContext, RateLimitDecision
from app.core.enums import RATE_LIMIT_BUCKET_RETRY_AFTER_S, RateLimitBucket, Role
from app.core.errors import CommerceQLError, SessionLockConflict
from app.obs.audit import AuditWriter
from app.repo.pools import build_three_pools
from tests.unit._redis_fake import FakeRedis


def _ctx(*, session_id: str = "sess_1", task_id: str = "task_1") -> IdentityContext:
    return IdentityContext(
        trace_id="tr_1",
        task_id=task_id,
        session_id=session_id,
        tenant_id="t_001",
        user_id="u_001",
        role=Role.OPERATOR,
    )


def _request(runtime: AppRuntime | None = None) -> Request:
    """造一个**最小可用**的 `Request`。

    ⚠️ 不启 `TestClient`、不跑 lifespan：本文件要验的是"运行时对象在不在"这件事本身，
    而 `TestClient` 会把 `lifespan` 里的**真** I/O（连库、开池、跑启动断言）全带上 ——
    那就不再是离线单测了（也正是"单测悄悄变成集成测试"的常见路径）。
    Request 只需要一个带 `state` 的 `app`。
    """
    app = FastAPI()
    if runtime is not None:
        setattr(app.state, deps.RUNTIME_STATE_KEY, runtime)
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.fixture
def redis_fake() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def runtime(redis_fake: FakeRedis) -> AppRuntime:
    settings = get_settings()
    return build_runtime(
        settings=settings,
        pools=build_three_pools(settings),
        redis=cast(Redis, redis_fake),
    )


# ===========================================================================
# 一、装配
# ===========================================================================

def test_build_runtime_wires_the_three_ports_with_real_implementations(
    runtime: AppRuntime,
) -> None:
    """★ 三个端口**必须是具体实现**，不能是替身。

    `build_runtime` 的文档字符串写明"不允许调用方注入"：允许注入只会造出
    "测试里用 A、生产里用 B"的差异面 —— 而那类差异恰好会让契约测试（用假实现）全绿、
    生产（用真实现）出问题。本用例把"装配点只有一处"钉住。
    """
    assert isinstance(runtime.session_lock, RedisSessionLock)
    assert isinstance(runtime.rate_limiter, RedisBucketRateLimiter)
    assert isinstance(runtime.audit, AuditWriter)
    assert runtime.redis is runtime.session_lock._client
    # ⚠️ 上面故意读了私有属性：要断言的是"**同一个** Redis 客户端被三处共用"。
    #    若哪天有人给限流器单独建了一个客户端，那会多出一条无人负责关闭的连接池
    #    （`main.py` 的关机路径只 `aclose()` 一个 client）。这条私有属性访问是**唯一**
    #    能表达该约束的地方，故保留并注明理由，而不是改成"看起来更规范"的弱断言。
    assert runtime.rate_limiter._client is runtime.session_lock._client


def test_app_runtime_is_frozen(runtime: AppRuntime) -> None:
    """不可变：装配完成后**任何模块**都不得偷换运行时对象。

    可变的话，"这个进程有哪些依赖"就有了第二个写入点，而它不会出现在任何 code review 里
    （一次 `app.state.runtime.redis = other` 就够）。

    ⚠️ 这里**只能**用属性赋值 + `# type: ignore[misc, assignment]`，两条路都试过：
    ① `setattr(runtime, "settings", None)` 会触发 ruff B010（"常量属性名用 setattr
       不比直接访问更安全"）—— 它说得对，而且它会把"这里在故意违规"这条信息藏进一个
       看起来无害的调用里；
    ② 属性赋值被 mypy 报两个码：`misc`（frozen dataclass 字段只读）与 `assignment`
       （`None` 不是 `Settings`）。两个都必须列出，否则 `--warn-unused-ignores` 会红。
    明确写出两个码 + 这句理由，比一个没有解释的 `setattr` 更容易在下一次评审里被理解。
    """
    with pytest.raises(FrozenInstanceError):
        runtime.settings = None  # type: ignore[misc, assignment]


def test_get_runtime_refuses_when_not_assembled() -> None:
    """★ 未装配时**明确报错**，不返回"半可用的替身"。

    兜底的替身会把"startup 没跑 / 测试没走 lifespan"这类**真实的装配缺陷**掩盖成
    "某些功能安静地不工作"，而那是最难定位的一类。
    """
    with pytest.raises(CommerceQLError, match="未装配"):
        get_runtime(_request())


def test_accessors_read_from_the_assembled_runtime(runtime: AppRuntime) -> None:
    """四个取用点在装配后都能取到**同一个**对象（不是每次新建）。"""
    req = _request(runtime)
    assert get_runtime(req) is runtime
    assert get_session_lock(req) is runtime.session_lock
    assert get_rate_limiter(req) is runtime.rate_limiter
    assert get_audit_sink(req) is runtime.audit


def test_get_identity_is_the_contextvar_reader_not_an_authorization_source() -> None:
    """`get_identity` 只读 contextvar（日志/审计/传参用）。

    ⚠️ 授权判定的实参**必须显式传下去** —— contextvar 在后台任务里会继承**过期身份**。
    本用例把"它是一个读取器"钉在签名上：无参、返回 `IdentityContext`。
    真值由中间件设置（W4 的第 7 步接线），本文件不造假上下文。
    """
    assert list(inspect.signature(get_identity).parameters) == []


@pytest.mark.parametrize("func", [check_rate_limit, session_lock_guard])
def test_helpers_require_identity_as_an_explicit_argument(func: object) -> None:
    """★ 两个辅助器的 `ctx` 都是**必填位置参数**（不是可选、不是从 contextvar 取）。

    这是"contextvar 不作为授权依据"的**结构化**保证：拿不到身份就写不出调用
    （而不是"忘传了就静默取到一个可能是过期的身份"）。
    """
    params = inspect.signature(func).parameters  # type: ignore[arg-type]
    assert "ctx" in params, f"{func} 少了 ctx 参数"
    assert params["ctx"].default is inspect.Parameter.empty, "ctx 不得有默认值"


# ===========================================================================
# 二、限流拦截：抛领域异常，**不造 HTTP 响应**
# ===========================================================================

async def test_rate_limit_passes_under_quota_then_raises(runtime: AppRuntime) -> None:
    """★ `QUERY` 桶 10/min：前 10 次放行，第 11 次抛 `RateLimited`。

    ⚠️ 先说清这一条**验的是接线**（`check_rate_limit` 有没有把 decision 翻成异常），
    Lua 滑窗的正确性归集成用例（真脚本）。
    """
    req = _request(runtime)
    ctx = _ctx()
    for _ in range(10):
        await check_rate_limit(req, RateLimitBucket.QUERY, ctx)

    with pytest.raises(RateLimited):
        await check_rate_limit(req, RateLimitBucket.QUERY, ctx)


async def test_rate_limited_carries_bucket_and_bucketed_retry_after(runtime: AppRuntime) -> None:
    """`RateLimited` 必须带上**桶与倒计时**：`Retry-After` 按桶取（附录 A §A.0.6）。

    ⚠️ 值来自 `enums.RATE_LIMIT_BUCKET_RETRY_AFTER_S`（单一来源）。
    在辅助器里另写一套数字会与 `api/errors.map_rate_limited` 分叉，
    表现为"响应头的倒计时与文档不符"，而两边都"看起来对"。
    """
    req = _request(runtime)
    ctx = _ctx()
    for _ in range(10):
        await check_rate_limit(req, RateLimitBucket.QUERY, ctx)
    with pytest.raises(RateLimited) as ei:
        await check_rate_limit(req, RateLimitBucket.QUERY, ctx)

    exc = ei.value
    assert exc.bucket is RateLimitBucket.QUERY
    assert exc.retry_after_s == RATE_LIMIT_BUCKET_RETRY_AFTER_S[RateLimitBucket.QUERY] == 30
    # `detail` 只放桶名与倒计时 —— 不含用户标识、不含键（用户可见响应里没有收益）
    assert set(exc.detail) == {"bucket", "retry_after_s"}
    assert "key" not in str(exc.detail)


def _referenced_names(source: str, names: set[str]) -> list[str]:
    """源码里**被真正引用**的标识符（`ast`），排除文档字符串与注释。

    ⚠️ 本文件第一版这两条静态检查用**子串匹配**写的，结果测试自己红了两次：
    正则命中的是"文档字符串里**在讨论**这条规则的那句话"，不是违规。
    这正是 `tests/contract/test_obs_audit_contract.py` 早已记录过的坑
    （"第一版用全文正则实现，结果本测试自己红了 …… 检查工具把『关于规则的文字』
    当成了『违反规则的行为』"）。→ 这里沿用同一套 `ast` 纪律，而不是再抄一遍正则。
    `ast` 天然不含注释，且能区分"字面量（数据）"与"标识符（行为）"。
    """
    tree = ast.parse(source)
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in names:
            hits.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            hits.add(node.attr)
    return sorted(hits)


def _calls(source: str, *, owner: str, attrs: set[str]) -> list[str]:
    """源码里**被调用**的 `owner.attr(...)`（`ast`）。

    用途：判"有没有真的调用 `pytest.skip`" —— 而不是"文件里出现过这几个字符"。
    """
    tree = ast.parse(source)
    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        if (
            func.attr in attrs
            and isinstance(func.value, ast.Name)
            and func.value.id == owner
        ):
            hits.add(f"{owner}.{func.attr}")
    return sorted(hits)


def test_rate_limit_raises_domain_error_not_http_response() -> None:
    """★ `check_rate_limit` 的返回类型必须是**领域异常**，不是 `Response`。

    `app/api/errors.py` 是"异常 → 错误码"的**唯一映射点**。在限流器里自己造
    `JSONResponse(429)` 会让"响应头怎么给"出现第二处实现 —— 而 `Retry-After` 与
    `X-RateLimit-*` 恰恰是最容易两处不一致的地方。

    ⚠️ 扫的是**代码里的标识符**（`ast`），不是字符串出现次数：
    `deps.py` 的文档字符串里正在讨论"不要造 `JSONResponse`"，
    用子串匹配会把这句话本身当成违规（第一版就是这么红的）。
    """
    source = inspect.getsource(deps)
    offenders = _referenced_names(
        source, {"JSONResponse", "HTTPException", "PlainTextResponse", "RedirectResponse"}
    )
    assert not offenders, (
        f"deps.py 引用了 Web 响应/异常类 {offenders} —— "
        f"响应构造必须只在 api/errors.py 与端点层（否则 Retry-After 会有两处实现）"
    )


def test_no_status_code_is_decided_inside_deps() -> None:
    """补位：连"决定 HTTP 码"这件事也不许在 `deps.py` 发生（同上理由的另一半）。

    只查"有没有引用 `JSONResponse`"是不够的 —— `raise ...AppError(status_code=429)` 也能绕过。
    """
    tree = ast.parse(inspect.getsource(deps))
    offenders = [
        kw.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg in {"status_code", "status"}
    ]
    assert not offenders, f"deps.py 里出现了状态码决策 {offenders}"


def test_rate_limited_maps_to_429_with_retry_after() -> None:
    """★ 跨模块的**端到端**一眼：`RateLimited` → `429` + `Retry-After: 30`。

    ⚠️ 映射本身归 `app/api/errors.py`（W0 立骨架 / W4 维护），本用例**不改它**，
    只做一次"两边接得上"的确认。少了这一条，两个模块各自全绿而接缝处是断的。

    ⚠️ `RateLimited` 携带的是**整个 `RateLimitQuota`**（判定 + 四头同源），
    不是"桶名 + 秒数"两个裸参数 —— 否则 `X-RateLimit-*` 会在处理器里被重算一遍。
    本用例因此按新签名构造，顺带把"配额对象真的能穿透到映射层"这条钉住。
    """
    quota = RateLimitQuota(
        decision=RateLimitDecision(
            allowed=False, bucket=RateLimitBucket.QUERY, retry_after_s=30
        )
    )
    mapping = map_exception(RateLimited(quota))
    assert mapping.status == 429, "`RateLimited` 必须映射到 429（配额语义）"
    assert mapping.retry_after_s == 30
    assert mapping.code.value == "RATE_LIMITED"


# ===========================================================================
# 三、会话锁守卫：**释放点必须在 async with 的出口**（含异常 / 取消）
# ===========================================================================

async def test_guard_acquires_then_releases(runtime: AppRuntime, redis_fake: FakeRedis) -> None:
    """正身：进去时拿到锁、出来时锁已释放。"""
    req = _request(runtime)
    ctx = _ctx()
    async with session_lock_guard(req, ctx) as key:
        assert await redis_fake.get(key) == ctx.task_id
        assert await runtime.session_lock.renew(key, ctx.task_id, ttl_s=60) is True
    assert await redis_fake.get(key) is None, "退出 async with 后锁必须已释放"


async def test_guard_releases_before_returning_control_to_the_caller(
    runtime: AppRuntime, redis_fake: FakeRedis
) -> None:
    """★★ 释放发生在**退出 `async with` 的那一刻**，不是"稍后"。

    ⚠️ 这正是"用 `async with` 而不是 FastAPI 的 `yield` 依赖"的理由：
    `yield` 依赖的清理在**响应生成之后**执行，而 SSE 响应是**流式**的 ——
    "响应生成完"与"图跑完"不是同一时刻。用 `yield` 会出现
    "流还在推事件、锁已经放掉、第二个请求已进入同一会话"。

    做法：在 `async with` 退出后**立即**（同一函数内、无 await 间隙以外的机会）读键，
    必须是 None。若实现把释放挂在某个后台任务/事件回调上，这里会读到旧值。
    """
    req = _request(runtime)
    ctx = _ctx()
    holder_after: list[str | None] = []
    async with session_lock_guard(req, ctx) as key:
        async with session_lock_guard(req, _ctx(session_id="sess_other")) as other:
            assert other != key, "不同会话必须是不同的锁键"
        holder_after.append(await redis_fake.get(key))
    assert holder_after == [ctx.task_id], "守卫内层退出时不得释放外层的锁（键不同，互不影响）"
    assert await redis_fake.get(key) is None


async def test_lock_released_when_body_raises(runtime: AppRuntime, redis_fake: FakeRedis) -> None:
    """★ 图执行抛异常时锁**必须**释放（`finally` 而非"正常路径之后"）。

    忘记这一条的后果不是"少了一次释放"：锁会活到 TTL（默认 60s），
    而用户看到的是"刚才那次明明报错了，现在一直提示冲突"。
    """
    req = _request(runtime)
    ctx = _ctx()
    key_seen: list[str] = []
    with pytest.raises(RuntimeError, match="图炸了"):
        async with session_lock_guard(req, ctx) as key:
            key_seen.append(key)
            raise RuntimeError("图炸了")
    assert await redis_fake.get(key_seen[0]) is None, "异常路径下锁未释放"


async def test_lock_released_on_cancellation(runtime: AppRuntime, redis_fake: FakeRedis) -> None:
    """★★ **客户端断连**（`CancelledError`）时也必须释放（07 §9.3 / §18.3 步 5）。

    ⚠️ `asynccontextmanager` 的 `finally` 在 `CancelledError` / `GeneratorExit` 时同样执行 ——
    本用例把这条依赖钉成**可执行的事实**：若哪天有人把它改成手写的 `__aenter__/__aexit__`
    并在 `__aexit__` 里先判 `exc_type is None`，这里会红。

    做法：不真的断连，而是在守卫体内 `await asyncio.sleep` 后被取消 ——
    取消点在 `sleep` 上，与真实断连在**协程层面等价**（都从 await 点抛出 `CancelledError`）。
    """
    req = _request(runtime)
    ctx = _ctx()
    entered = asyncio.Event()
    key_holder: dict[str, str] = {}

    async def _body() -> None:
        async with session_lock_guard(req, ctx) as key:
            key_holder["key"] = key
            entered.set()
            await asyncio.sleep(5)

    task = asyncio.create_task(_body())
    await entered.wait()
    key = key_holder["key"]
    assert await redis_fake.get(key) == ctx.task_id, "前置：取消前锁确实被持有"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await redis_fake.get(key) is None, (
        "★ 取消（客户端断连）路径下锁未释放 —— 会话会锁死到 TTL，"
        "用户看到『断开了但一直提示冲突』"
    )


async def test_guard_conflicts_do_not_leave_a_partial_hold(
    runtime: AppRuntime, redis_fake: FakeRedis
) -> None:
    """守卫拿不到锁时**抛异常且不留下任何持有**（`acquire` 失败不该进入 `try`）。

    ⚠️ 若实现把 `acquire` 写在 `try` 内部，`finally` 会对一个**没拿到的锁**执行 `release`
    —— 而 `release` 是持有者校验的，通常无害；但若 `acquire` 抛错前恰好拿到过
    （例如超时判定与拿到锁之间的竞态），就会**释放别人的锁**。
    本用例断言：冲突后键仍是**原持有者**的。
    """
    req = _request(runtime)
    first = _ctx(session_id="sess_1", task_id="task_A")
    async with session_lock_guard(req, first) as key:
        with pytest.raises(SessionLockConflict):
            # 第二个请求进来（同一个会话）：必须冲突
            async with session_lock_guard(req, _ctx(session_id="sess_1", task_id="task_B")):
                pytest.fail("同一会话的第二个请求不应进入守卫体")
        assert await redis_fake.get(key) == "task_A", "冲突路径不得动到原持有者的锁"


# ---------------------------------------------------------------------------
# 四、静默跳过防御：本文件不得因为"环境没起"而被整体 skip
# ---------------------------------------------------------------------------

def test_no_module_level_skip_in_this_file() -> None:
    """护栏：本文件**不得**出现 `pytest.skip` / `importorskip` **调用**。

    它全部依赖都是可替身的（FakeRedis / 纯构造），一旦出现 skip，
    说明有人在里面偷偷加了真外部依赖 —— 那会让护栏在 CI 上变成绿色装饰。

    ⚠️ 判的是 `ast.Call`（**真的调用了**），不是"文件里出现了这几个字符"：
    本用例自己的断言语句里就写着 `"pytest.skip"` 这个**字面量**（讨论规则），
    子串匹配会把自己抓出来 —— 与上一条同一个坑，第一版同样红在这里。
    """
    module = inspect.getmodule(test_no_module_level_skip_in_this_file)
    assert module is not None
    source = inspect.getsource(module)
    offenders = _calls(source, owner="pytest", attrs={"skip", "importorskip"})
    assert not offenders, (
        f"本文件出现了跳过调用 {offenders} —— 离线单测不得因环境不可用而跳过"
        f"（『跳过』在 pytest 里显示为绿色，护栏会变成装饰）"
    )
