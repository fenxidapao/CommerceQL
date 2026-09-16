"""分桶限流的离线断言（附录 A §A.0.6 / 07 §9.2）。

归属窗口：W1B。

## ⚠️ 这个文件证明什么、不证明什么

| 断言 | 在这里（内存替身） | 在 `tests/integration/`（真 Redis） |
|---|---|---|
| 规则表**逐行**对齐 §9.2 的数字 | ✅ | — |
| 参数位序（`numkeys=2`、ARGV 顺序）与脚本的约定 | ✅（看 `eval_calls`） | — |
| 放行 N 次、第 N+1 次拒、窗口滑过后恢复 | ✅（时间可控） | ✅（真 Lua） |
| `GLOBAL_CONCURRENCY` 未实现这条**边界**被钉死 | ✅ | — |

"参数位序"这条离线断言特别值得留：脚本的 `ARGV[1..4]` 是按位置读的，
而 Python 侧传的是一个平铺的 `*args`。**位置写错不会有任何报错** ——
只会得到"限流数字不对"，看起来像阈值配错了。这条断言把它变成一次显式红。
"""

from __future__ import annotations

import pytest

from app.api import ratelimit as ratelimit_mod
from app.api.ratelimit import (
    ENFORCED_DIMENSIONS,
    RATE_LIMIT_RULES,
    SLIDING_WINDOW_SCRIPT,
    UNENFORCED_DIMENSIONS,
    UNIMPLEMENTED_BUCKETS,
    LimiterNotImplemented,
    RedisBucketRateLimiter,
)
from app.cache import keys as cache_keys
from app.core.contracts import IdentityContext
from app.core.enums import RATE_LIMIT_BUCKET_RETRY_AFTER_S, RateLimitBucket, Role

from ._redis_fake import FakeRedis


def _ctx(*, task_id: str = "t_001", user_id: str = "u_2002", tenant_id: str = "t_1001") -> IdentityContext:
    return IdentityContext(
        trace_id="tr_001",
        task_id=task_id,
        session_id="s_001",
        tenant_id=tenant_id,
        user_id=user_id,
        role=Role.OPERATOR,
    )


# ---------------------------------------------------------------------------
# 1. ★ 规则表逐行对齐 07 §9.2
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("bucket", "per_user", "per_tenant"),
    [
        (RateLimitBucket.QUERY, 10, 100),
        (RateLimitBucket.READ, 120, 1200),
        (RateLimitBucket.WRITE, 30, 300),
        (RateLimitBucket.ADMIN, 5, None),
    ],
)
def test_rules_match_the_design_table(
    bucket: RateLimitBucket, per_user: int, per_tenant: int | None
) -> None:
    """数字**逐行**取自 07 §9.2 —— 本窗口不调优、不发明。

    ⚠️ 写成参数化用例而不是"读一眼代码"：这四个数字是**契约**（附录 A §A.0.6），
    被改小是事故（用户被莫名限流）、被改大也是事故（配额保护失效），
    而两者都不会有任何报错。
    """
    rule = RATE_LIMIT_RULES[bucket]
    assert rule.per_user_per_min == per_user
    assert rule.per_tenant_per_min == per_tenant


def test_every_bucket_has_a_rule() -> None:
    """取值集里**每个**桶都必须有规则 —— 少一个就是"某个桶永远放行"（静默的保护缺失）。"""
    assert set(RATE_LIMIT_RULES) == set(RateLimitBucket)


def test_window_matches_the_fixed_retry_after_table() -> None:
    """四个已实现的桶在 `enums` 里**都必须**有 `Retry-After` 定值。

    实现侧不再写第二套数字（那会让响应头与文档分叉，而两边都"看起来对"）；
    因此"定值表缺项"必须在这里红，而不是等到联调时才发现 `429` 少了倒计时。
    """
    for bucket in RateLimitBucket:
        if bucket in UNIMPLEMENTED_BUCKETS:
            continue
        assert RATE_LIMIT_BUCKET_RETRY_AFTER_S[bucket] is not None, (
            f"{bucket.value} 已实现但没有 Retry-After 定值 → 429 响应会缺头"
        )


# ---------------------------------------------------------------------------
# 2. ★ 两条诚实边界（钉死机制）
# ---------------------------------------------------------------------------

async def test_global_concurrency_bucket_is_not_implemented_and_why() -> None:
    """`GLOBAL_CONCURRENCY` **未实现**，且刻意不提供近似值。

    它要防的是"100 个长连接挂着不结束"（§9.5 的并发租约），而 60s 滑窗
    对这件事**完全无感** —— 却会把"1 秒内打了 100 次"判成超限。
    用滑窗实现它 = 一个有明确错误方向的假实现。

    ⚠️ 这条测试就是钉死机制：想把它"补上"，必须**先改红这条测试**，
    于是改动者一定会读到"机制在 §9.5，归 W4"。
    """
    assert frozenset({RateLimitBucket.GLOBAL_CONCURRENCY}) == UNIMPLEMENTED_BUCKETS
    limiter = RedisBucketRateLimiter(FakeRedis())  # type: ignore[arg-type]
    with pytest.raises(LimiterNotImplemented, match="并发租约"):
        await limiter.check(RateLimitBucket.GLOBAL_CONCURRENCY, _ctx())


def test_both_dimensions_are_enforced_after_u38_wiring() -> None:
    """两个维度**都必须在 ENFORCED_DIMENSIONS**（U-38 已接线，2026-09-16）。

    ⚠️ 这条是双向钉死：拆掉任何一个维度（把集合改小）都会让本测试红，
    改动者会被注释引导到 07 §9.2 的逐行契约。`UNENFORCED_DIMENSIONS`
    保留为**空**集合 —— 它是"契约里有、实现里没有"这类缺席的登记处。
    """
    assert frozenset({"per_user", "per_tenant"}) == ENFORCED_DIMENSIONS
    assert frozenset() == UNENFORCED_DIMENSIONS


def test_tenant_key_uses_the_dedicated_constructor_and_differs_from_user_key() -> None:
    """★ 租户键必须走 `cache_keys.rate_limit_tenant`，且与用户键**恒不等**。

    复用用户键的后果是：脚本会在**同一个 ZSET** 上做两次判定（用户维度与租户维度），
    于是用户配额被当成租户配额 → 表现为"限流忽然变得极严"，且不会有任何报错。
    """
    limiter = RedisBucketRateLimiter(FakeRedis())  # type: ignore[arg-type]
    ctx = _ctx()
    user_key, tenant_key = limiter._window_keys(RateLimitBucket.QUERY, ctx)
    assert user_key == cache_keys.rate_limit("query", ctx.tenant_id, ctx.user_id)
    assert tenant_key == cache_keys.rate_limit_tenant("query", ctx.tenant_id)
    assert tenant_key != user_key
    assert "rl:t:" in tenant_key


# ---------------------------------------------------------------------------
# 3. 调用约定（参数位序）
# ---------------------------------------------------------------------------

async def test_eval_is_called_with_two_keys_and_the_documented_arg_order() -> None:
    """`numkeys=2` 且 ARGV 顺序 = `[user_limit, tenant_limit, window_ms, member]`。

    脚本按**位置**读这四个值。位置写错不会有任何报错，只会得到"限流数字不对"。
    """
    redis = FakeRedis()
    limiter = RedisBucketRateLimiter(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    await limiter.check(RateLimitBucket.QUERY, ctx)

    assert len(redis.eval_calls) == 1
    script, numkeys, args = redis.eval_calls[0]
    assert script is SLIDING_WINDOW_SCRIPT
    assert numkeys == 2
    user_key, tenant_key, user_limit, tenant_limit, window_ms, member = args
    assert user_key == cache_keys.rate_limit("query", ctx.tenant_id, ctx.user_id)
    assert tenant_key == cache_keys.rate_limit_tenant("query", ctx.tenant_id)
    assert user_limit == "10" and tenant_limit == "100"  # §9.2 QUERY 行的租户列
    assert window_ms == str(ratelimit_mod.WINDOW_S * 1000)
    assert member.startswith(ctx.task_id)


async def test_admin_bucket_passes_zero_tenant_limit_because_the_design_says_dash() -> None:
    """`ADMIN` 桶的租户列是 `—` → ARGV 里必须是 **"0"**（脚本不碰 KEYS[2]）。

    ⚠️ 断言的是设计（§9.2 的表），不是实现便利：给管理员桶叠租户配额
    会把"平台管理员排查故障"一起限住 —— 所以这里**必须**是 0 而不是"忘了传"。
    """
    redis = FakeRedis()
    limiter = RedisBucketRateLimiter(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    await limiter.check(RateLimitBucket.ADMIN, ctx)

    _, _, args = redis.eval_calls[0]
    _, _, user_limit, tenant_limit, _, _ = args
    assert user_limit == "5"
    assert tenant_limit == "0"


async def test_tenant_cap_denies_a_fresh_user_once_the_tenant_window_is_full() -> None:
    """★ 租户维度**真的生效**：同一租户打满租户上限后，**新用户**也被拒。

    这是 U-38 接线的存在性证明 —— 只断言 `ENFORCED_DIMENSIONS` 集合的话，
    "集合写了但 check() 没读"这种假接线不会被抓住。
    QUERY 桶：per_user=10 / per_tenant=100 → 100 次打满租户窗，
    第 101 次换一个**从没出现过的** user_id，必须被拒。
    """
    limiter = RedisBucketRateLimiter(FakeRedis())  # type: ignore[arg-type]
    for i in range(100):
        ctx = _ctx(task_id=f"t_{i:03d}", user_id=f"u_{i:03d}", tenant_id="t_tenantfull")
        assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed, f"第 {i + 1} 次就被拒 = 用户键/租户键撞了"
    fresh = _ctx(task_id="t_fresh", user_id="u_never_seen", tenant_id="t_tenantfull")
    decision = await limiter.check(RateLimitBucket.QUERY, fresh)
    assert not decision.allowed
    # 而隔壁租户的同名新用户不受牵连（租户隔离）。
    other = _ctx(task_id="t_other", user_id="u_never_seen", tenant_id="t_other_tenant")
    assert (await limiter.check(RateLimitBucket.QUERY, other)).allowed


async def test_key_contains_tenant_and_no_plaintext_user_id() -> None:
    """键必须含租户（N-10），且 `user_id` 必须哈希（§11.2 硬规则 4）。"""
    key = cache_keys.rate_limit("query", "t_1001", "u_2002")
    assert "t_1001" in key
    assert "u_2002" not in key


async def test_member_is_unique_per_call() -> None:
    """★ 成员必须**逐次唯一**（`task_id` + 随机后缀）。

    用裸 `task_id` 的话，幂等重放的两个请求会共用成员 → ZSET 里同成员是**覆盖**而不是累加
    → 计数偏小（限流少算）。而"同一 task 被重试"恰恰是最需要限流的时刻。
    """
    redis = FakeRedis()
    limiter = RedisBucketRateLimiter(redis)  # type: ignore[arg-type]
    ctx = _ctx(task_id="t_same")
    await limiter.check(RateLimitBucket.QUERY, ctx)
    await limiter.check(RateLimitBucket.QUERY, ctx)
    members = [call[2][-1] for call in redis.eval_calls]
    assert len(set(members)) == 2, "两次调用的成员相同 → 第二次会覆盖第一次，计数偏小"


# ---------------------------------------------------------------------------
# 4. 滑窗行为
# ---------------------------------------------------------------------------

async def test_allows_up_to_the_limit_then_denies() -> None:
    """放行 10 次（QUERY 的 per-user 上限），第 11 次拒 —— 且带 `Retry-After: 30`。"""
    redis = FakeRedis()
    limiter = RedisBucketRateLimiter(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    for _ in range(10):
        assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed is True
    denied = await limiter.check(RateLimitBucket.QUERY, ctx)
    assert denied.allowed is False
    assert denied.bucket is RateLimitBucket.QUERY
    assert denied.retry_after_s == RATE_LIMIT_BUCKET_RETRY_AFTER_S[RateLimitBucket.QUERY] == 30


async def test_allowed_decision_has_no_retry_after() -> None:
    """放行时**不得**带 `Retry-After`（给了倒计时就是在暗示需要退避）。"""
    limiter = RedisBucketRateLimiter(FakeRedis())  # type: ignore[arg-type]
    decision = await limiter.check(RateLimitBucket.READ, _ctx())
    assert decision.allowed is True
    assert decision.retry_after_s is None


async def test_window_slides() -> None:
    """★ 滑窗正身：窗口完全滑过之后**必须**重新放行。

    没有这一条，一个"一旦超限就永久拒绝"的实现也能通过上面所有用例 ——
    而那正是固定窗口最容易退化成的东西（或更糟：忘了 `PEXPIRE`，键永不过期）。
    """
    redis = FakeRedis()
    limiter = RedisBucketRateLimiter(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    for _ in range(10):
        await limiter.check(RateLimitBucket.QUERY, ctx)
    assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed is False

    redis.advance_ms(ratelimit_mod.WINDOW_S * 1000 + 1)
    assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed is True


async def test_partial_window_slide_keeps_the_count() -> None:
    """窗口**只滑一半**时计数不得清零（这是"精确滑窗"与"固定窗口"的分界）。

    固定窗口在窗口边界会把计数整体清零 → 放过 2 倍突发。
    """
    redis = FakeRedis()
    limiter = RedisBucketRateLimiter(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    for _ in range(10):
        await limiter.check(RateLimitBucket.QUERY, ctx)
    redis.advance_ms(ratelimit_mod.WINDOW_S * 1000 // 2)
    assert (await limiter.check(RateLimitBucket.QUERY, ctx)).allowed is False


async def test_limits_are_isolated_between_users_and_buckets() -> None:
    """限流必须**按用户**且**按桶**隔离 —— 键设计错了会串在一起。

    键写错（例如漏了 user 哈希段、或把 bucket 写死成常量）的表现是
    "A 打满后 B 也被限"，且不会有任何报错。
    """
    redis = FakeRedis()
    limiter = RedisBucketRateLimiter(redis)  # type: ignore[arg-type]
    for _ in range(10):
        await limiter.check(RateLimitBucket.QUERY, _ctx(user_id="u_A"))
    assert (await limiter.check(RateLimitBucket.QUERY, _ctx(user_id="u_A"))).allowed is False
    assert (await limiter.check(RateLimitBucket.QUERY, _ctx(user_id="u_B"))).allowed is True
    # 换桶：READ 的键不同 → 不受 QUERY 的计数影响
    assert (await limiter.check(RateLimitBucket.READ, _ctx(user_id="u_A"))).allowed is True
    # 换租户：键含租户 → 不受另一个租户的计数影响
    assert (await limiter.check(RateLimitBucket.QUERY, _ctx(user_id="u_A", tenant_id="t_2002"))).allowed


def test_constructor_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_s"):
        RedisBucketRateLimiter(FakeRedis(), window_s=0)  # type: ignore[arg-type]
