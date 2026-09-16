"""会话串行锁的离线断言（FR-10.5 / ADR-13 / 07 §9.3）。

归属窗口：W1B。

## ⚠️ 这个文件证明什么、不证明什么

| 断言 | 在这里（内存替身） | 在 `tests/integration/`（真 Redis） |
|---|---|---|
| 轮询间隔、等待上限、超时抛 `SessionLockConflict` | ✅（时间可控） | — |
| 键的构造（含租户 + 哈希后的 user_id，无明文 PII） | ✅ | — |
| **续租/释放的持有者校验真的生效** | ⚠️ 逻辑等价实现 | ✅ **真 Lua**（`test_real_redis_*`） |

替身里的 Lua 是"文本匹配 + Python 等价实现"，所以它**测不出参数位序错误**。
而"释放了别人的锁"这个 bug 的全部风险都在那段 Lua 里 —— 所以集成用例不是补充，是必需。
"""

from __future__ import annotations

import pytest

from app.cache import keys as cache_keys
from app.cache.session_lock import RELEASE_SCRIPT, RENEW_SCRIPT, RedisSessionLock
from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.core.errors import SessionLockConflict

from ._redis_fake import FakeRedis


def _ctx(*, task_id: str = "t_001", session_id: str = "s_001") -> IdentityContext:
    return IdentityContext(
        trace_id="tr_001",
        task_id=task_id,
        session_id=session_id,
        tenant_id="t_1001",
        user_id="u_2002",
        role=Role.OPERATOR,
    )


# ---------------------------------------------------------------------------
# 1. 获取
# ---------------------------------------------------------------------------

async def test_acquire_sets_value_to_task_id() -> None:
    """锁的 value 必须是 `task_id` —— 续租/释放的持有者校验全靠它。

    用 `"1"` / `"locked"` 这类常量做 value，校验就退化成"键存在吗"，
    于是"A 超时释放、B 已持有 → A 删掉了 B 的锁"立刻发生。
    """
    redis = FakeRedis()
    lock = RedisSessionLock(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    key = await lock.acquire(ctx, ttl_s=60, wait_ms=0)
    assert await redis.get(key) == ctx.task_id


async def test_acquire_uses_the_single_key_builder() -> None:
    """键必须由 `cache/keys.py` 构造（§11.2 硬规则 3），且**含租户**（N-10）。

    同时断言键里**不含明文 `user_id`**：Redis 的 `KEYS` 输出与监控面板会把它暴露出去。
    """
    redis = FakeRedis()
    lock = RedisSessionLock(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    key = await lock.acquire(ctx, ttl_s=60, wait_ms=0)
    assert key == cache_keys.session_lock(ctx.tenant_id, ctx.user_id, ctx.session_id)
    assert ctx.tenant_id in key
    assert ctx.user_id not in key, "明文 user_id 不得进键（§11.2 硬规则 4）"


async def test_second_acquire_times_out_with_session_conflict() -> None:
    """同一会话第二次获取 → 等待超时 → `SessionLockConflict`（**409，不是 429**）。"""
    redis = FakeRedis()
    # 缩短轮询，让用例快
    lock = RedisSessionLock(redis, poll_interval_ms=1)  # type: ignore[arg-type]  # type: ignore[arg-type]
    ctx_a = _ctx(task_id="t_A")
    ctx_b = _ctx(task_id="t_B")
    await lock.acquire(ctx_a, ttl_s=60, wait_ms=0)
    with pytest.raises(SessionLockConflict) as excinfo:
        await lock.acquire(ctx_b, ttl_s=60, wait_ms=20)
    assert excinfo.value.default_code == "SESSION_CONFLICT"


async def test_conflict_detail_does_not_leak_the_key() -> None:
    """`detail` 里只放 `session_id`，**不放锁键**。

    ⚠️ 键里虽已哈希了 `user_id`，但它会进**用户可见响应**（`error.detail`），
    而它出现在那里没有任何收益 —— N-12 的精神是"出站内容不含明细"。
    """
    redis = FakeRedis()
    lock = RedisSessionLock(redis, poll_interval_ms=1)  # type: ignore[arg-type]
    await lock.acquire(_ctx(task_id="t_A"), ttl_s=60, wait_ms=0)
    with pytest.raises(SessionLockConflict) as excinfo:
        await lock.acquire(_ctx(task_id="t_B"), ttl_s=60, wait_ms=10)
    detail = excinfo.value.detail
    assert detail["session_id"] == "s_001"
    assert not any("lock:session" in str(v) for v in detail.values())


async def test_acquire_retries_until_the_holder_releases() -> None:
    """★ 正身：锁被释放后，等待中的请求**必须**拿到锁（而不是一直失败到超时）。

    没有这一条，"等待 3s 轮询"这个设计可能从未真正生效 —— 一条永远抛 409 的实现
    也能通过上面所有用例。
    """
    redis = FakeRedis()
    lock = RedisSessionLock(redis, poll_interval_ms=1)  # type: ignore[arg-type]
    ctx_a, ctx_b = _ctx(task_id="t_A"), _ctx(task_id="t_B")
    key = await lock.acquire(ctx_a, ttl_s=60, wait_ms=0)
    await lock.release(key, ctx_a.task_id)
    assert await lock.acquire(ctx_b, ttl_s=60, wait_ms=50) == key
    assert await redis.get(key) == ctx_b.task_id


async def test_acquire_rejects_invalid_arguments() -> None:
    lock = RedisSessionLock(FakeRedis())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ttl_s"):
        await lock.acquire(_ctx(), ttl_s=0, wait_ms=0)
    with pytest.raises(ValueError, match="wait_ms"):
        await lock.acquire(_ctx(), ttl_s=60, wait_ms=-1)


def test_constructor_rejects_non_positive_poll_interval() -> None:
    """轮询间隔为 0 会变成**忙等**（把 event loop 打满），必须在构造期拦下。"""
    with pytest.raises(ValueError, match="poll_interval_ms"):
        RedisSessionLock(FakeRedis(), poll_interval_ms=0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. 续租与释放（持有者校验）
# ---------------------------------------------------------------------------

async def test_renew_extends_only_for_the_holder() -> None:
    redis = FakeRedis()
    lock = RedisSessionLock(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    key = await lock.acquire(ctx, ttl_s=60, wait_ms=0)
    assert await lock.renew(key, ctx.task_id, ttl_s=60) is True
    assert await lock.renew(key, "t_OTHER", ttl_s=60) is False


async def test_renew_returns_false_when_lock_expired() -> None:
    """★ 锁已过期 → `renew` 返回 `False`（**不抛异常**）。

    这是"长查询已失去串行保证"的正常表达：调用方（W4）要据此决定"继续跑还是中止"，
    而这个决定的产品语义不同（结果仍正确，只是串行性已破），不该由锁的实现替它做。
    抛异常则会把每次 TTL 到期的长查询变成一次失败响应。
    """
    redis = FakeRedis()
    lock = RedisSessionLock(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    key = await lock.acquire(ctx, ttl_s=1, wait_ms=0)
    redis.advance_ms(1001)
    assert await lock.renew(key, ctx.task_id, ttl_s=60) is False


async def test_release_does_not_delete_someone_elses_lock() -> None:
    """★★ 本文件最关键的一条（07 §9.3 第 2 条细节）。

    时序：A 拿锁 → A 的 TTL 到期 → B 拿锁 → A 的 `finally` 才执行 release。
    不校验持有者的实现会把 **B 的锁删掉**，于是第三个请求与 B 并行进入同一会话 ——
    会话状态错乱。这个时序很窄（压测未必复现），但用户连点两次就能触发。
    """
    redis = FakeRedis()
    lock = RedisSessionLock(redis)  # type: ignore[arg-type]
    ctx_a, ctx_b = _ctx(task_id="t_A"), _ctx(task_id="t_B")

    key = await lock.acquire(ctx_a, ttl_s=1, wait_ms=0)
    redis.advance_ms(1001)  # A 的锁过期
    await lock.acquire(ctx_b, ttl_s=60, wait_ms=0)  # B 接手

    await lock.release(key, ctx_a.task_id)  # A 迟到的 finally
    assert await redis.get(key) == ctx_b.task_id, "A 释放掉了 B 的锁 —— 串行保证已破"


async def test_release_is_idempotent() -> None:
    """重复释放不得抛异常：它的调用点在 `finally`，抛出去会把**已成功的响应**变成错误。"""
    redis = FakeRedis()
    lock = RedisSessionLock(redis)  # type: ignore[arg-type]
    ctx = _ctx()
    key = await lock.acquire(ctx, ttl_s=60, wait_ms=0)
    await lock.release(key, ctx.task_id)
    await lock.release(key, ctx.task_id)  # 不得抛


# ---------------------------------------------------------------------------
# 3. 脚本本身
# ---------------------------------------------------------------------------

def test_scripts_compare_the_holder_before_mutating() -> None:
    """两段脚本都必须**先比后改**（`GET == ARGV[1]` 在动作之前）。

    ⚠️ 断言的是脚本的**形状**而不是行为：行为由集成用例在真 Redis 上验。
    这条离线断言的价值是"有人把校验删掉时立刻红" ——
    例如把 `if redis.call('GET', ...) == ARGV[1] then` 简化成直接 `PEXPIRE`，
    那是一次看起来无害的"简化"，而它正好抹掉了 §9.3 的第 2 条细节。
    """
    for script in (RENEW_SCRIPT, RELEASE_SCRIPT):
        assert "GET", script
        assert "ARGV[1]" in script, "缺少持有者比较"
        assert script.index("GET") < script.index("return redis.call", script.index("then"))


def test_release_script_uses_del_and_renew_uses_pexpire() -> None:
    assert "DEL" in RELEASE_SCRIPT
    assert "PEXPIRE" in RENEW_SCRIPT
    assert "DEL" not in RENEW_SCRIPT, "续租绝不能删键"
