"""`RedisCache` 的离线断言（B2 前置：`CachePort` 首次有实现）。

## ⚠️ 这个文件证明什么、不证明什么

| 断言 | 本文件（`FakeRedis`） | 需真 Redis |
|---|---|---|
| get / set / delete 走向、TTL 走单一入口、1MB 硬拒、单飞只回源一次 | ✅ | — |
| 与真 Redis 的协议细节（`SET ... EX` 语义、过期精度、多进程并发） | — | ⛔ 未覆盖：`tests/integration/` 尚无本类用例（登记为已知边界） |

替身的能力边界见 `_redis_fake.py` 文件头 —— 它只覆盖被测路径用到的命令。
"""

from __future__ import annotations

import asyncio

import pytest

from app.cache import keys as cache_keys
from app.cache.redis_cache import MAX_VALUE_BYTES, RedisCache
from app.core.contracts import CachePort

from ._redis_fake import FakeRedis

# ---------------------------------------------------------------------------
# 1. 端口面与基本存取
# ---------------------------------------------------------------------------


def test_implements_the_cache_port() -> None:
    """`CachePort` 是 `runtime_checkable` 协议 ⇒ 方法面缺一个就 isinstance 假。

    这条断言很便宜，但它是"`GraphDeps.result_cache: CachePort` 真能收这个对象"的唯一静态证据。
    """
    assert isinstance(RedisCache(FakeRedis()), CachePort)  # type: ignore[arg-type]


async def test_get_missing_key_returns_none() -> None:
    cache = RedisCache(FakeRedis())  # type: ignore[arg-type]
    assert await cache.get(cache_keys.result_set("t_1001", "task_x")) is None


async def test_set_then_get_roundtrip() -> None:
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]
    key = cache_keys.result_set("t_1001", "task_x")
    await cache.set(key, '{"rows": [[1]]}', ttl_s=3600)
    assert await cache.get(key) == '{"rows": [[1]]}'


async def test_delete_removes_the_key() -> None:
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]
    await cache.set("k", "v", ttl_s=60)
    await cache.delete("k")
    assert await cache.get("k") is None


# ---------------------------------------------------------------------------
# 2. TTL：必须只有一处抖动量（§11.4）
# ---------------------------------------------------------------------------


async def test_set_routes_ttl_through_the_single_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """TTL 必须经 `keys.jittered_ttl`，本类不得自算抖动量。

    ⚠️ 这条断言也在钉住调用形态：必须是 `cache_keys.jittered_ttl(...)`（模块属性查找），
    不能 `from app.cache.keys import jittered_ttl` —— 后者会让替身/补丁失效，且将来
    改抖动量时只改得到一处、另一处静默漂移。
    """
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]

    def _fake(ttl_s: int, *, rand: float | None = None) -> int:
        assert ttl_s == 60, "基准 TTL 必须原样传进去（抖动在 jittered_ttl 内部算）"
        assert rand is None, "调用方不得注入 rand —— 那是测试专用参数"
        return 7

    monkeypatch.setattr(cache_keys, "jittered_ttl", _fake)
    await cache.set("k", "v", ttl_s=60)
    expires_at = redis.store["k"][1]
    assert expires_at is not None
    assert expires_at - redis.time_ms == 7_000


async def test_set_clamps_jitter_to_at_least_one_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """抖动量算出 0 时不得写 `EX 0`（Redis 直接报错）⇒ 必须 clamp 到 1s。"""
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]

    monkeypatch.setattr(cache_keys, "jittered_ttl", lambda ttl_s, **kw: 0)
    await cache.set("k", "v", ttl_s=1)
    expires_at = redis.store["k"][1]
    assert expires_at is not None
    assert expires_at - redis.time_ms == 1_000


# ---------------------------------------------------------------------------
# 3. 红线段：大 key / 非法参数
# ---------------------------------------------------------------------------


async def test_set_rejects_value_over_one_megabyte() -> None:
    """§11.4「单键 value ≤ 1MB」：超限**硬拒**，不截断、不静默写半份。"""
    redis = FakeRedis()
    cache = RedisCache(redis, max_value_bytes=4)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="单键上限"):
        await cache.set("k", "12345", ttl_s=60)
    assert "k" not in redis.store, "被拒的值不得落库"


async def test_default_limit_is_one_megabyte() -> None:
    assert MAX_VALUE_BYTES == 1_048_576


async def test_set_rejects_non_positive_ttl() -> None:
    cache = RedisCache(FakeRedis())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ttl_s"):
        await cache.set("k", "v", ttl_s=0)


async def test_set_rejects_empty_key() -> None:
    """空键会退化成"全仓共享一个键" ⇒ 跨租户串数据，必须在写入前拦下（§11.2 硬规则 3）。"""
    cache = RedisCache(FakeRedis())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="key 不得为空"):
        await cache.set("", "v", ttl_s=60)


def test_constructor_rejects_non_positive_max_value_bytes() -> None:
    with pytest.raises(ValueError, match="max_value_bytes"):
        RedisCache(FakeRedis(), max_value_bytes=0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. 单飞（进程内半格）
# ---------------------------------------------------------------------------


async def test_single_flight_runs_loader_once_for_concurrent_callers() -> None:
    """★ 正身：同键并发只回源一次。

    没有这一条，一个"每次都回源"的实现也能通过上面所有用例（而单飞的全部价值就在这里）。
    """
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)  # 制造切换点，让后两个调用者真的等在锁上
        return "payload"

    results = await asyncio.gather(
        *(cache.single_flight("k", loader, ttl_s=60) for _ in range(3))
    )
    assert results == ["payload", "payload", "payload"]
    assert calls == 1
    assert await cache.get("k") == "payload"


async def test_single_flight_returns_cached_value_without_calling_loader() -> None:
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]
    await cache.set("k", "already", ttl_s=60)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return "should-not-be-used"

    assert await cache.single_flight("k", loader, ttl_s=60) == "already"
    assert calls == 0


async def test_single_flight_does_not_cache_empty_result() -> None:
    """§11.5 红线 2：空结果**不写缓存**（可能是 RLS 过滤造成的），但仍原样返回。"""
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]

    async def loader() -> str:
        return ""

    assert await cache.single_flight("k", loader, ttl_s=60) == ""
    assert await cache.get("k") is None


async def test_single_flight_propagates_loader_error_and_writes_nothing() -> None:
    """§11.5 红线 5：失败/异常不得被固化成缓存（会把瞬时故障变成稳定行为）。"""
    redis = FakeRedis()
    cache = RedisCache(redis)  # type: ignore[arg-type]

    async def loader() -> str:
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError, match="upstream down"):
        await cache.single_flight("k", loader, ttl_s=60)
    assert await cache.get("k") is None
    assert cache._locks == {}, "异常路径也必须摘掉进程内锁，否则该键永久串行"
