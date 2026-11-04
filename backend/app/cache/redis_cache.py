"""`CachePort` 的 Redis 实现（L2｜`app.cache`）。

--------------------------------------------------------------------------
一、本类服务的是「结果集载体」，**不是** ADR-12 禁掉的「查询结果缓存」
--------------------------------------------------------------------------
两者共用"缓存"二字，混起来会得出错误结论（"ADR-12 禁了结果缓存 ⇒ 这个类不该存在"）：

| 东西 | 键 | 状态 | 依据 |
|---|---|---|---|
| **结果集载体**（异步 / 重放 / 导出读） | `result:{tenant}:{task_id}`，TTL 1h | ✅ 启用 | `docs/07 §11.1` 键表；`keys.py::result_set` |
| **查询结果缓存**（按问题 + 参数缓存答案） | 未定义 | ⛔ P0 关闭 | ADR-12；`docs/07 §11.5` 红线 1 |

⇒ 本类落地**不触碰** `Settings.ENABLE_RESULT_CACHE` / `..._CONFIRMED`（那两个开关守的是上表
第二行），也**不得**被拿去按问题缓存答案 —— 那要先满足 ADR-12 的三条前置条件（键规范评审冻结 /
跨租户与跨角色的负向测试齐备 / 键构造唯一入口被 N-10 单测覆盖）。

--------------------------------------------------------------------------
二、为什么实现落在这里，而不是 `app/api/state_store.py`
--------------------------------------------------------------------------
后者 docstring 明写「**不得**把本文件迁过去顶替」`CachePort` 实现：它是 L5 的端点状态读写器，
做成 Port 实现 = 邀请别层复用 = 下一处"有人拿 `task_state` 当通用缓存放别的东西"。

--------------------------------------------------------------------------
三、客户端从构造入参拿，不自己 `from_url`
--------------------------------------------------------------------------
`app/repo/redis.py` 是 Redis 客户端的**唯一装配点**（N-14 / `docs/07 §8.1`）；同包同层的
`session_lock.py:93` 同款：构造期只记住客户端，不建连接（`redis.asyncio` 本身惰性）。

--------------------------------------------------------------------------
四、诚实边界（不得被读成"防击穿已落地"）
--------------------------------------------------------------------------
| 项 | 现状 |
|---|---|
| `single_flight` 的**进程内**半格 | ✅ 本类实现：同键并发只回源一次 |
| `single_flight` 的**跨进程**半格（`§11.4` 要求的 Redis 短锁） | ⛔ **未做**：需要新增 `sf:` 键命名空间并在 `§11.1` 键表登记，属独立改动；今天全仓 `single_flight` **零调用者**（只有端口定义与 `state_store.py` 的注释提到它） |
| 单键 1MB 上限（`§11.4`） | ✅ **硬拒**（抛 `ValueError`），不截断 —— 截断把"设计错误"变成"静默的半份数据" |
| 负缓存（`§11.5` 红线 2） | ✅ 空串**不写**：空结果可能由 RLS 行级过滤造成，缓存它等于跨租户存在性泄露 |
| 失败响应（`§11.5` 红线 5） | ✅ loader 抛异常直接上抛，不写 |
| TTL 抖动（`§11.4` 防雪崩 ±10%） | ✅ 一律经 `keys.jittered_ttl`，本类不自算 —— 两处各写一份就会有两个抖动幅度 |
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from app.cache import keys as cache_keys
from app.core.contracts import CachePort

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis

__all__ = ["MAX_VALUE_BYTES", "RedisCache"]

#: 单键上限（`docs/07 §11.4`「单键 value ≤ 1MB」）。
#: 超限说明设计错误 —— 应分片或改存结构；**不得**靠调大本常量"绕过"。
MAX_VALUE_BYTES: Final[int] = 1_048_576


class RedisCache(CachePort):
    """`CachePort` 的 Redis 实现。**只做存取**：键由调用方从 `app/cache/keys.py` 取。

    本类不构造键、不判业务语义、不做装配（见模块 docstring §二/§三）。
    """

    def __init__(self, client: Redis, *, max_value_bytes: int = MAX_VALUE_BYTES) -> None:
        if max_value_bytes <= 0:
            raise ValueError(f"max_value_bytes 必须为正：{max_value_bytes}")
        self._client = client
        self._max_value_bytes = max_value_bytes
        #: 进程内单飞锁：key → `asyncio.Lock`。竞态与内存上界的取舍见 `single_flight`。
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str) -> str | None:
        """取原文。未命中返回 `None`。

        ⚠️ 不区分"不存在"与"已过期" —— Redis 层无从区分，在本层编一个区分就是假信息。
        `str(...)` 是显式收窄：装配点的客户端一律 `decode_responses=True`（`repo/redis.py` 已钉），
        但这条性质是**别人的**，本层不靠它做类型假设。
        """
        value = await self._client.get(key)
        return None if value is None else str(value)

    async def set(self, key: str, value: str, *, ttl_s: int) -> None:
        """写入并设 TTL。

        ⚠️ TTL **一律**经 `keys.jittered_ttl`（`§11.4` 防雪崩：基准 ×(0.9+rand×0.2)）。
        本类不自算抖动量 —— 否则"两处各写一份"迟早出现两个幅度。
        ⚠️ `max(1, ...)`：`jittered_ttl(1)` 可能算出 0，而 Redis 的 `SET ... EX 0` 直接报错。
        """
        if not key:
            raise ValueError("key 不得为空 —— 键必须由 app/cache/keys.py 构造（§11.2 硬规则 3）")
        if ttl_s <= 0:
            raise ValueError(f"ttl_s 必须为正：{ttl_s}")
        size = len(value.encode("utf-8"))
        if size > self._max_value_bytes:
            raise ValueError(
                f"value 超过单键上限：{size} > {self._max_value_bytes} 字节"
                "（§11.4 单键 ≤1MB；超限说明设计错误 —— 应分片或改存结构）"
            )
        await self._client.set(key, value, ex=max(1, cache_keys.jittered_ttl(ttl_s)))

    async def delete(self, key: str) -> None:
        """删除。键不存在时静默（Redis `DEL` 语义），不抛、不返回。"""
        await self._client.delete(key)

    async def single_flight(
        self, key: str, loader: Callable[[], Awaitable[str]], *, ttl_s: int
    ) -> str:
        """同键并发只回源一次（`§11.4` 的**进程内**半格）。

        ⚠️ **跨进程半格未做**（见模块 docstring §四）：多 worker 部署下每个进程各回源一次。
        ⚠️ **窄竞态（已知、刻意接受）**：锁在释放后从 `_locks` 摘除；若此刻另有协程已取到同一个
        `Lock` 对象但尚未 `acquire`，它可能带着"孤儿锁"进临界区，而新来的协程造了一把新锁 ⇒
        **同键可能多回源一次**。后果只是多余的 loader 调用，**不会**返回错值（写入幂等）。
        换成"无界 dict 不摘除"可消掉该竞态，但结果集键含 `task_id` ⇒ `_locks` 必然无界增长；
        这里选"有界内存 + 可能多一次回源"。
        ⚠️ 空结果不写缓存（`§11.5` 红线 2 负缓存），但仍原样返回给调用方。
        """
        cached = await self.get(key)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                # 双检：等锁期间别人可能已经回源并写入。
                cached = await self.get(key)
                if cached is not None:
                    return cached
                value = await loader()
                if value:
                    await self.set(key, value, ttl_s=ttl_s)
                return value
        finally:
            if not lock.locked() and self._locks.get(key) is lock:
                del self._locks[key]
