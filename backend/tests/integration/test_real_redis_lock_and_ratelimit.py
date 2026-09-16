"""**真 Redis** 上的 Lua 语义自证 —— 会话锁 + 限流滑窗（07 §9.2 / §9.3）。

归属窗口：W1B。

## 为什么必须有这个文件（替身覆盖不到的地方）

`tests/unit/_redis_fake.py` 的 `eval` 是**按脚本文本分发到 Python 实现**的。
于是它测不到两类最要命的错误：

1. **参数位序**：`numkeys` / `ARGV` 的顺序写错时，替身照着自己理解的位序执行 → 全绿；
2. **Lua 的原子性与语义**：`GET`+`PEXPIRE` 之间会不会被插进别的命令、ZSET 的
   `ZREMRANGEBYSCORE` 边界含不含端点、`TIME` 的精度 —— 这些**只有真 Redis 能答**。

替身自己的文档字符串也写明了这一点（"这就是为什么必须同时有集成用例"）。
本文件就是那句话的兑现 —— 在此之前，`test_real_redis_*` 系列**并不存在**
（又一个"文档写了、盘上没有"的影子承诺）。

## 与 `test_audit_append_only.py` 相同的两条纪律

- **无 Redis 自动 skip**，且 skip 理由写清楚 —— 不静默假绿；
- **负向对照**：先证明"正常路径真的能过"（拿得到锁 / 放行 10 次），
  再证明"拒绝路径真的会拒"。只测拒绝的话，一个把键名写错、连不上的实现也会"通过"。

⚠️ **不许 sleep 等窗口滑过**：本文件用**真 Redis 服务端时间**，等 60s 会让用例不可用。
需要"时间过去"的场合一律改用**缩短窗口**的实例（`window_s=1`）+ 真 sleep 1.1s，
或直接构造键状态。**限流窗口长度是构造参数**，这是它可以在测试里被缩小的原因。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

import pytest
import redis.asyncio as aioredis

from app.api.ratelimit import SLIDING_WINDOW_SCRIPT, RedisBucketRateLimiter
from app.cache import keys as cache_keys
from app.cache.session_lock import RedisSessionLock
from app.core.contracts import IdentityContext
from app.core.enums import RATE_LIMIT_BUCKET_RETRY_AFTER_S, RateLimitBucket, Role
from app.core.errors import SessionLockConflict

pytestmark = pytest.mark.integration

#: 真 Redis 的连接串。默认指向 compose 的宿主映射端口 —— 与 `docker-compose.yml` 一致，
#: 这样"测试能过"与"栈能起"用的是同一套地址。
_REDIS_URL = "redis://localhost:6379/0"


def _ctx(
    *,
    tag: str,
    session_id: str = "sess_1",
    task_id: str = "task_1",
    user_id: str | None = None,
) -> IdentityContext:
    """每次用**随机租户/用户**，避免用例之间（以及与本机残留键）互相污染。

    ⚠️ `user_id` 可显式覆盖 —— 测"同一租户下的两个不同用户"时必须能只换用户维度：
    用 `tag` 一次改两个维度（租户 + 用户）会让"到底靠哪个维度隔离"变得不可判定
    （本文件第一版就踩了：想验"不同用户互不影响"，却因为 `tag` 相同而构造出了**同一个用户**，
    于是断言在当时实际上是"同一把桶被打了 11 次"——测试失败才发现用例自身写错了）。

    ⚠️ 不用 `FLUSHDB` 清理：那会顺手删掉开发者本机其它进程的键，
    在"测试要让环境干净"与"测试不许破坏环境"之间，后者优先。
    """
    return IdentityContext(
        trace_id=f"tr_{tag}",
        task_id=task_id,
        session_id=session_id,
        tenant_id=f"t_it_{tag}",
        user_id=user_id if user_id is not None else f"u_it_{tag}",
        role=Role.OPERATOR,
    )


@pytest.fixture
async def client() -> AsyncIterator[aioredis.Redis]:
    """真 Redis 客户端。**连不上就 skip 整个模块**（不假绿）。"""
    conn: aioredis.Redis = aioredis.Redis.from_url(_REDIS_URL, decode_responses=True)
    try:
        await conn.ping()
    except Exception as exc:
        await conn.aclose()
        pytest.skip(f"集成环境不可用（{type(exc).__name__}）→ 跳过真脚本断言，不计为通过")
    try:
        yield conn
    finally:
        await conn.aclose()


@pytest.fixture
async def cleanup_keys(client: aioredis.Redis) -> AsyncIterator[list[str]]:
    """收集本用例创建的键，结束时删掉 —— **只删自己建的**。"""
    created: list[str] = []
    try:
        yield created
    finally:
        if created:
            await client.delete(*created)


# ===========================================================================
# 一、会话串行锁（§9.3）
# ===========================================================================

async def test_lock_roundtrip_against_real_redis(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """正身：拿得到锁、键名来自 `keys.session_lock`、value 是 `task_id`、TTL 真的是 `ttl_s`。

    ⚠️ 单独验 `PTTL` 不是装饰：第 2 条细节（续租/释放校验持有者）**只有在 TTL 真的生效时**
    才有意义 —— TTL 没设上的锁是"永不释放"的锁，而它在功能测试里表现完全正常
    （第一个请求能过），只有在第二个请求进来时才暴露。
    """
    lock = RedisSessionLock(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    key = await lock.acquire(ctx, ttl_s=60, wait_ms=0)
    cleanup_keys.append(key)

    assert key == cache_keys.session_lock(ctx.tenant_id, ctx.user_id, ctx.session_id)
    assert await lock.holder_of(key) == ctx.task_id
    pttl = await client.pttl(key)
    assert 0 < pttl <= 60_000, f"TTL 未按 ttl_s 设定：pttl={pttl}"
    # 明文 user_id 不得进键（§11.2 硬规则 4 / PII 面）
    assert ctx.user_id not in key
    assert cache_keys.user_scope_hash(ctx.user_id) in key


async def test_second_acquire_conflicts_and_does_not_return_the_rate_limit_shape(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★ 359 行文档里最容易被写成 `429` 的一条：冲突必须是 **`409` 语义**（`SessionLockConflict`），
    且 **detail 里不带键、不带 `X-RateLimit-*`**。

    ⚠️ 为什么把"等了一会儿"也断言进去：若实现把 `wait_ms` 忽略了直接抛，
    功能上"看起来对"（确实冲突了），但前端会从"连点两次"变成"一次都过不去"——
    而这个差异只在**并发真的存在**时才可见（单线程测试里两次串行调用不会撞）。
    """
    lock = RedisSessionLock(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    key = await lock.acquire(ctx, ttl_s=60, wait_ms=0)
    cleanup_keys.append(key)

    started = time.monotonic()
    with pytest.raises(SessionLockConflict) as ei:
        await lock.acquire(_ctx(tag=ctx.tenant_id.removeprefix("t_it_"), session_id="sess_1"),
                           ttl_s=60, wait_ms=300)
    elapsed = time.monotonic() - started

    assert elapsed >= 0.25, f"没有真的等待 wait_ms（{elapsed:.3f}s）—— 轮询/等待逻辑失效"
    assert ei.value.default_code == "SESSION_CONFLICT"
    assert "key" not in ei.value.detail, "冲突详情不得回显缓存键（既无收益又暴露内部结构）"


async def test_exactly_one_winner_under_real_concurrency(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★★ **本文件的核心证据**：10 个并发 `acquire(wait_ms=0)` 必须**恰好 1 个成功**。

    这是 `SET ... NX` 原子性的直接检验 —— 替身做不到（它的 `set` 是单线程 Python，
    "原子"是白送的，故永远测不出原子性缺失）。而串行锁的全部价值就在这个原子上：
    若两个请求同时拿到锁，本项目的"会话串行"承诺（FR-10.5 / ADR-13）当场失效。

    ⚠️ `wait_ms=0` 是刻意的：有等待的话，"多个成功"会被等待逻辑掩盖成"先后拿到"。
    """
    lock = RedisSessionLock(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])

    results = await asyncio.gather(
        *(lock.acquire(ctx, ttl_s=30, wait_ms=0) for _ in range(10)),
        return_exceptions=True,
    )
    winners = [r for r in results if isinstance(r, str)]
    conflicts = [r for r in results if isinstance(r, SessionLockConflict)]
    other = [r for r in results if not isinstance(r, (str, SessionLockConflict))]

    assert not other, f"出现了非预期异常：{[type(o).__name__ for o in other]}"
    assert len(winners) == 1, f"并发下拿到锁的个数 = {len(winners)}（必须恰好 1）"
    assert len(conflicts) == 9
    cleanup_keys.append(winners[0])


async def test_renew_only_succeeds_for_the_holder(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """续租的持有者校验：非持有者续租必须返回 `False` **且不改变 TTL**。

    ⚠️ 只断言"返回 False"是不够的：一个先 `PEXPIRE` 再判定的实现也会返回 False，
    却已经把别人的锁续上了 —— 表现为"某会话永远锁死"。故这里同时断言 TTL 未变。
    """
    lock = RedisSessionLock(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    key = await lock.acquire(ctx, ttl_s=5, wait_ms=0)
    cleanup_keys.append(key)
    before = await client.pttl(key)

    assert await lock.renew(key, "someone_else", ttl_s=60) is False
    after_wrong = await client.pttl(key)
    assert abs(after_wrong - before) < 1000, f"非持有者竟然改了 TTL：{before} → {after_wrong}"
    assert await lock.holder_of(key) == ctx.task_id

    assert await lock.renew(key, ctx.task_id, ttl_s=600) is True
    assert await client.pttl(key) > 500_000, "持有者续租未生效"


async def test_release_does_not_delete_a_lock_taken_by_someone_else(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★★ 07 §9.3 第 2 条细节的**完整复现**，也是"为什么必须用 Lua 而不是 GET+DEL"。

    时序（文档里写明的那个窄窗口）：
        A 拿到锁 → A 超时（TTL 到期）→ B 拿到锁 → A 的 `finally` 才执行 `release`
        → 若不校验持有者，A 会**删掉 B 的锁** → 第三个请求与 B 并行进同一会话。

    这里用**真 TTL 到期**（`ttl_s=1`）而不是手动 `DEL` 模拟：两者对应用而言等价，
    但真到期额外证明了"TTL 真的会到"—— 而 `GET+DEL` 的实现恰好会在**真到期**这条路径上翻车。
    """
    lock = RedisSessionLock(client)
    a = _ctx(tag=uuid.uuid4().hex[:8], task_id="task_A")
    key = await lock.acquire(a, ttl_s=1, wait_ms=0)
    cleanup_keys.append(key)

    await asyncio.sleep(1.2)  # 让 A 的锁真过期（窗口 1s，留 200ms 余量）
    assert await lock.holder_of(key) is None, "锁未按 TTL 过期 —— 后面的场景不成立"

    b = _ctx(tag=a.tenant_id.removeprefix("t_it_"), task_id="task_B")
    key_b = await lock.acquire(b, ttl_s=30, wait_ms=0)
    assert key_b == key  # 同一会话 → 同一把锁

    await lock.release(key, "task_A")  # A 的 finally 迟到（持有者已不是它）
    assert await lock.holder_of(key) == "task_B", (
        "★ A 的迟到 release 删掉了 B 的锁 —— 持有者校验没生效，会话串行承诺已破"
    )

    await lock.release(key, "task_B")
    assert await lock.holder_of(key) is None, "持有者 release 未删除锁"


async def test_release_is_idempotent(client: aioredis.Redis, cleanup_keys: list[str]) -> None:
    """`finally` 里调用 → 可能执行两次（正常返回 + 异常路径）→ 必须幂等且**不抛**。

    抛出去的后果很具体：把"已经成功返回的结果"变成一次错误响应，
    而锁的残留有 TTL 兜底 —— 收益为零、代价明确。
    """
    lock = RedisSessionLock(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    key = await lock.acquire(ctx, ttl_s=30, wait_ms=0)
    await lock.release(key, ctx.task_id)
    await lock.release(key, ctx.task_id)  # 第二次：键已不在，静默
    await lock.release(f"{key}:never_existed", ctx.task_id)  # 从未存在的键


# ===========================================================================
# 二、限流滑窗（§9.2）
# ===========================================================================

async def test_allow_then_deny_with_bucketed_retry_after(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★ `QUERY` 桶：前 10 次放行，第 11 次拒绝，`retry_after_s` **取自 `enums` 的定值表**。

    ⚠️ 断言定值而不是"非 None"：`Retry-After` 有两处可能各写一套数字
    （`enums` 的桶表 / `api/errors.map_rate_limited` 的取值），分叉时两边都"看起来对"，
    而用户看到的是"倒计时与文档不符"。这里把限流器这一侧钉到桶表上。

    ⚠️ 先证明放行 10 次**真的都放行**（负向对照）：
    否则一个"永远拒绝"的实现也会让"第 11 次被拒"这条绿。
    """
    limiter = RedisBucketRateLimiter(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    cleanup_keys.append(cache_keys.rate_limit(RateLimitBucket.QUERY.value, ctx.tenant_id, ctx.user_id))

    decisions = [await limiter.check(RateLimitBucket.QUERY, ctx) for _ in range(11)]
    allowed = [d.allowed for d in decisions]
    assert allowed[:10] == [True] * 10, f"前 10 次必须全放行，实际 {allowed[:10]}"
    assert allowed[10] is False, "第 11 次必须拒绝（10/min）"
    assert decisions[-1].retry_after_s == RATE_LIMIT_BUCKET_RETRY_AFTER_S[RateLimitBucket.QUERY]
    # 放行时**不得**给 Retry-After（那是"要等"的信号，会给前端造成误判）
    assert all(d.retry_after_s is None for d in decisions if d.allowed)


async def test_timestamps_come_from_redis_server_clock_not_the_app_clock(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★ 脚本声明"时间戳取自 Redis 服务端 `TIME`，不取应用侧时钟"，**这里验它**。

    这个选择有两个不可省的后果，且都**不可由应用侧假装**：
    ① 多实例部署时各实例墙钟有毫秒偏差 → 同一租户的计数会在实例间错位；
    ② 应用侧读时间要走 `ClockPort` → 而它的 `semantics()` 来自语义包
       → **限流器会凭空多出一条对语义包的启动依赖**（N-18 的边界）。

    做法：读回 ZSET 的 score，与**服务端 `TIME`** 比对（差值必须是百毫秒内的"刚刚"）。
    若实现改用应用侧时间，这条在**时区/时钟偏移**环境下才会红 —— 但它同时也是
    "score 单位是毫秒"的机器化证据（写成秒的话差值会大到离谱）。
    """
    limiter = RedisBucketRateLimiter(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    key = cache_keys.rate_limit(RateLimitBucket.READ.value, ctx.tenant_id, ctx.user_id)
    cleanup_keys.append(key)

    await limiter.check(RateLimitBucket.READ, ctx)
    scores = await client.zrange(key, 0, -1, withscores=True)
    assert len(scores) == 1

    sec, usec = await client.time()
    server_ms = sec * 1000 + usec // 1000
    assert abs(int(scores[0][1]) - server_ms) < 3000, (
        f"ZSET score={int(scores[0][1])} 与服务端 TIME={server_ms} 相差过大 —— "
        f"时间戳不是来自 Redis 服务端，或多实例下会错位"
    )


async def test_member_is_unique_per_call_so_retries_still_count(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★ 同一 `task_id` 的多次请求必须**各记一条**（member 带随机后缀）。

    若 member 用裸 `task_id`，幂等重放会让 ZSET **覆盖而不是累加** → 计数偏小、
    限流少算 —— 而"同一 task 被重发"恰恰是最需要限流保护的时刻。
    """
    limiter = RedisBucketRateLimiter(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8], task_id="task_same")
    key = cache_keys.rate_limit(RateLimitBucket.READ.value, ctx.tenant_id, ctx.user_id)
    cleanup_keys.append(key)

    for _ in range(3):
        assert (await limiter.check(RateLimitBucket.READ, ctx)).allowed
    assert await client.zcard(key) == 3, "同 task_id 的请求被覆盖计入 → 计数偏小（限流少算）"


async def test_bucket_and_user_dimensions_are_isolated(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """用户维度与桶维度**都要隔离**：打满一个桶不能影响另一个，一个用户不能影响另一个。

    ⚠️ 这条防的是"键少了维度"这类静默严重错误（§11.2 硬规则：键必须含租户；
    桶必须进键）。少一个维度的表现是"某人被限流后别人一起被限"，而日志里看不出异常。
    """
    limiter = RedisBucketRateLimiter(client)
    tag = uuid.uuid4().hex[:8]
    # ⚠️ `b` **同租户、不同用户**：这样才能把"靠用户维度隔离"单独验出来
    #    （租户也换掉的话，两条维度任一生效都会让用例通过 —— 等于没验到）。
    a = _ctx(tag=tag, task_id="task_a")
    b = _ctx(tag=tag, task_id="task_b", user_id="u_it_other_user")
    assert a.tenant_id == b.tenant_id and a.user_id != b.user_id
    cleanup_keys.extend(
        [
            cache_keys.rate_limit(RateLimitBucket.QUERY.value, a.tenant_id, a.user_id),
            cache_keys.rate_limit(RateLimitBucket.READ.value, a.tenant_id, a.user_id),
            cache_keys.rate_limit(RateLimitBucket.QUERY.value, b.tenant_id, b.user_id),
        ]
    )
    # 两个用户的键**必须不同** —— 键相同就不是"实现隔离失败"，而是**用例根本没在测隔离**
    assert cleanup_keys[0] != cleanup_keys[2]

    for _ in range(10):
        await limiter.check(RateLimitBucket.QUERY, a)
    assert (await limiter.check(RateLimitBucket.QUERY, a)).allowed is False
    # 同一用户的另一个桶不受影响
    assert (await limiter.check(RateLimitBucket.READ, a)).allowed is True
    # 另一个用户的同名桶不受影响
    assert (await limiter.check(RateLimitBucket.QUERY, b)).allowed is True


async def test_window_really_slides_with_a_short_window(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★ 窗口会滑走 —— 用 `window_s=1` 缩短窗口（**窗口长度是构造参数**，这是它能被测的原因）。

    若实现写成"固定窗口"（只在窗口起点清空），本用例同样会过（1s 后确实清了）。
    真正区分二者的是**边界突发**：滑窗下"0.9s 打满 + 1.1s 再打"仍受限，
    固定窗口会在边界放过 2 倍。这里先验证滑窗的基本行为（`ZREMRANGEBYSCORE` 的
    `<=` 边界含端点、以及过期成员被清），这是它能在边界上正确的**必要**条件。
    """
    limiter = RedisBucketRateLimiter(client, window_s=1)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    key = cache_keys.rate_limit(RateLimitBucket.QUERY.value, ctx.tenant_id, ctx.user_id)
    cleanup_keys.append(key)

    for _ in range(10):
        assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed
    assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed is False

    await asyncio.sleep(1.15)
    assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed is True, (
        "窗口未滑走（过期成员没被清）—— ZREMRANGEBYSCORE 的边界或窗口单位写错了"
    )
    assert await client.zcard(key) == 1, "过期成员未被清理，计数会越积越多"


async def test_partial_window_keeps_recent_count(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """补位断言：窗口**只**清掉过期的，没过期的一条都不能少。

    只测"会清"不够 —— 一个把窗口写成 0（每次全清）的实现也能过上面那条，
    但那等于**没有限流**（只留最后一条）。这里连打 3 次、等半个窗口，计数必须仍是 3。
    """
    limiter = RedisBucketRateLimiter(client, window_s=2)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    key = cache_keys.rate_limit(RateLimitBucket.QUERY.value, ctx.tenant_id, ctx.user_id)
    cleanup_keys.append(key)

    for _ in range(3):
        await limiter.check(RateLimitBucket.QUERY, ctx)
    await asyncio.sleep(0.6)  # < 2s 窗口
    await limiter.check(RateLimitBucket.QUERY, ctx)
    assert await client.zcard(key) == 4, "窗口内未过期的计数被误清 —— 限流会失效"


async def test_real_script_accepts_the_declared_numkeys_and_arg_order(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """★ 直接调**真脚本**，用**规格里的位序**，结果必须符合预期。

    这是对"替身测不出参数位序"的正面回应：若 `check()` 的实参顺序与脚本期望不一致，
    上面那些用例仍可能碰巧通过（例如两个键恰好相同、上限恰好都是 0），
    但**这一条按契约位序调用**，位序错了就红。

    契约位序（脚本头注释）：`numkeys=2`，`ARGV = [user_limit, tenant_limit, window_ms, member]`。
    """
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    user_key = cache_keys.rate_limit(RateLimitBucket.QUERY.value, ctx.tenant_id, ctx.user_id)
    tenant_key = f"rl:tenant:{ctx.tenant_id}"  # 仅本用例的临时键（U-38 未接线，不代表实现）
    cleanup_keys.extend([user_key, tenant_key])

    allowed = await client.eval(
        SLIDING_WINDOW_SCRIPT, 2, user_key, tenant_key, "2", "3", "60000", "m1"
    )
    assert int(allowed[0]) == 1, f"按契约位序调用应放行：{allowed}"
    assert int(allowed[1]) == 1 and int(allowed[2]) == 1, "两个维度的计数都该 +1"

    assert int((await client.eval(
        SLIDING_WINDOW_SCRIPT, 2, user_key, tenant_key, "2", "3", "60000", "m2"
    ))[0]) == 1
    denied = await client.eval(
        SLIDING_WINDOW_SCRIPT, 2, user_key, tenant_key, "2", "3", "60000", "m3"
    )
    assert int(denied[0]) == 0, "用户维度 2/min 打满后必须拒绝"
    assert int(denied[1]) == 2, f"被拒时不该消耗配额（计数应停在 2）：{denied}"
    # 被拒的一次**不得**写进 ZSET（否则一次拒绝会连带吃两次配额）
    assert await client.zcard(user_key) == 2

    # 第三个维度位序错误的对照：把 window_ms 与 limit 对调会立刻表现为异常或错误判定
    assert int((await client.eval(
        SLIDING_WINDOW_SCRIPT, 2, user_key, tenant_key, "0", "0", "60000", "m4"
    ))[0]) == 1, "两维都不设限（0）时必须放行 —— 脚本对 0 的语义是『不启用该维度』"


async def test_script_is_deterministic_across_repeated_runs(
    client: aioredis.Redis, cleanup_keys: list[str]
) -> None:
    """同一条脚本在真 Redis 上重复执行结果一致（无隐藏随机/时间依赖除 `TIME` 外）。

    与 `test_timestamps_come_from_redis_server_clock_not_the_app_clock` 配对：
    那条证明"用的是服务端时间"，这条证明"除了服务端时间没有别的非确定性来源"。
    """
    limiter = RedisBucketRateLimiter(client)
    ctx = _ctx(tag=uuid.uuid4().hex[:8])
    cleanup_keys.append(cache_keys.rate_limit(RateLimitBucket.WRITE.value, ctx.tenant_id, ctx.user_id))
    for _ in range(5):
        assert (await limiter.check(RateLimitBucket.WRITE, ctx)).allowed


# ---------------------------------------------------------------------------
# 收尾：确保本模块**没有**留下未清理的键（自检，不是业务断言）
# ---------------------------------------------------------------------------

def test_module_declares_itself_as_integration() -> None:
    """护栏：本文件的模块级 `pytestmark` 必须是 `integration`。

    没有它，`pytest -m "not integration"` 的离线跑法会**真的去连 Redis**，
    在没起栈的机器上表现为一堆失败（而不是干净跳过）—— 于是有人干脆把整个文件删掉。

    ⚠️ 不能写 `pytestmark is pytest.mark.integration`：每次访问 `pytest.mark.x`
    都会**新建**一个 `MarkDecorator`，身份比较必然为假（本文件第一版就这么写的，当场红）。
    要比的是**标记名**。
    """
    marks = pytestmark if isinstance(pytestmark, list) else [pytestmark]
    assert {m.mark.name for m in marks} == {"integration"}
