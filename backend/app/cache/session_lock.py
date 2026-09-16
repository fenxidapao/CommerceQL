"""会话串行锁 —— FR-10.5 / ADR-13 的落地（07 §9.3）。

归属窗口：W1B（用户裁定 `3.a`）。

## 语义：这是**串行**，不是**限流**

| | 限流（`429`） | 本模块（`409 SESSION_CONFLICT`） |
|---|---|---|
| 语义 | 配额（你请求太多了） | **状态冲突**（这个会话已有查询在跑） |
| 响应头 | `X-RateLimit-*` + `Retry-After` | **仅** `Retry-After: 3`，**不得**带 `X-RateLimit-*` |
| 前端动作 | 进限流禁用态 | **自动重试一次**（附录 A §A.11） |

⚠️ 两者共用一套"重试"表现，但**绝不能复用 `429`**：前端的禁用态是粘性的，
会把一次"连点两次"的普通操作变成"用户被拉黑 30 秒"。

## 三个必须写进代码的细节（07 §9.3）

1. **`acquire` 的位置只在 api 层、进图之前**。在节点内获取是**自死锁**：
   检查点恢复会重放节点 → 重复获取同一把锁 → 等自己，直到 TTL 超时。
   → 本模块因此**不提供**"在节点里调用"的任何便利封装。
2. **续租与释放都必须校验持有者**（Lua：仅当 value 相同才 `PEXPIRE`/`DEL`）。
   不校验的后果是具体而常见的：A 的查询超时 → TTL 到期 → B 拿到锁 →
   A 的 `finally` 才执行 `DEL` → **删掉了 B 的锁** → 第三个请求与 B 并行进入同一会话。
   这个 bug 的时序很窄，压测未必复现，但用户连点两次就能触发。
3. **释放必须在 `finally`**（含客户端断连）。锁没释放 = 会话被永久锁死到 TTL，
   而用户看到的是"刚才那次明明断了，现在一直提示冲突"。

## ⚠️ 时钟口径（N-18 的边界）

`time.monotonic()` 用在这里是**允许**的，理由与 `auth/revocation.py` 相同：
它服务的是"**等待了多久**"这个**时长**判定，不参与任何业务口径计算（N-18 禁的是
口径读时间 —— 例如"上个月"的边界必须走语义包）。`ClockPort` 产出的是带语义的墙钟，
用它算超时反而会在 NTP 校时时得到负数。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Final

from app.cache import keys as cache_keys
from app.core.contracts import IdentityContext, SessionLockPort
from app.core.errors import SessionLockConflict

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from redis.asyncio import Redis

__all__ = [
    "DEFAULT_POLL_INTERVAL_MS",
    "RELEASE_SCRIPT",
    "RENEW_SCRIPT",
    "RedisSessionLock",
]

#: 轮询间隔（07 §9.3：等待 3s，间隔 200ms）。
#: ⚠️ 200ms × 15 次 = 3s —— 即最坏情况下 15 次 Redis 往返。
#: 用 `BLPOP` / 阻塞式等待会更省，但**语义不对**：锁被释放 ≠ 轮到我（可能是别人抢到），
#: 而且阻塞式等待会长期占住连接。轮询是这里唯一"行为可预测"的做法。
DEFAULT_POLL_INTERVAL_MS: Final[int] = 200

#: 续租：**仅当持有者一致**才续期。
#:
#: 返回 `1` = 续期成功；`0` = 锁已不在我手上（已过期或被别人持有）→ 调用方应停止续租循环。
#: ⚠️ 返回 `0` **不是异常**：它正是"长查询已经失去串行保证"这一事实的正常表达，
#: 调用方必须据此决定"继续跑（结果仍正确，只是串行性已破）还是中止"。
#: 本模块不替调用方做这个决定，因为两者的产品语义不同（W4 接线时裁定）。
RENEW_SCRIPT: Final[str] = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
else
  return 0
end
"""

#: 释放：**仅当持有者一致**才删除（防"释放了别人的锁"）。
RELEASE_SCRIPT: Final[str] = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
else
  return 0
end
"""


class RedisSessionLock(SessionLockPort):
    """`SessionLockPort` 的 Redis 实现。

    ⚠️ 锁的 value **必须是 `task_id`**（07 §9.3）：续租与释放的持有者校验全靠它。
    用 `1` / `"locked"` 这类常量做 value 会让校验退化成"键存在吗"，第 2 条细节立刻失效。
    """

    def __init__(self, client: Redis, *, poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS) -> None:
        if poll_interval_ms <= 0:
            raise ValueError(f"poll_interval_ms 必须为正：{poll_interval_ms}")
        self._client = client
        self._poll_interval_s = poll_interval_ms / 1000

    async def acquire(self, ctx: IdentityContext, *, ttl_s: int, wait_ms: int) -> str:
        """尝试拿锁；`wait_ms` 内没拿到 → 抛 `SessionLockConflict`。

        ⚠️ `wait_ms` 的**上限**（10s）由 `Settings` 的模型校验守（07 §9.5「禁止无限排队」），
        本方法不再判一次 —— 两处判同一个约束，早晚会有一处被改而另一处忘了。
        """
        if ttl_s <= 0:
            raise ValueError(f"ttl_s 必须为正：{ttl_s}")
        if wait_ms < 0:
            raise ValueError(f"wait_ms 不得为负：{wait_ms}")

        key = cache_keys.session_lock(ctx.tenant_id, ctx.user_id, ctx.session_id)
        holder = ctx.task_id
        # `PX` 而不是 `EX`：TTL 允许亚秒级调整时不必改单位换算（07 §9.3 的 60s 是秒，
        # 但续租间隔 20s 与轮询 200ms 都是毫秒量级，统一用毫秒少一处换算错误）。
        px = ttl_s * 1000
        deadline = time.monotonic() + wait_ms / 1000

        while True:
            acquired = await self._client.set(key, holder, nx=True, px=px)
            if acquired:
                return key
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SessionLockConflict(
                    "同一会话已有进行中的查询，请稍后重试",
                    detail={"session_id": ctx.session_id, "wait_ms": wait_ms, "ttl_s": ttl_s},
                )
            await asyncio.sleep(min(self._poll_interval_s, remaining))

    async def renew(self, key: str, holder: str, *, ttl_s: int) -> bool:
        """续租。返回 `False` = **锁已不在本持有者手上**（过期 / 被别人持有）。

        ⚠️ 不抛异常：见 `RENEW_SCRIPT` 的说明 —— 这是正常状态，不是故障。
        """
        result = await self._client.eval(RENEW_SCRIPT, 1, key, holder, str(ttl_s * 1000))
        return int(result) == 1

    async def release(self, key: str, holder: str) -> None:
        """释放。**必须放在 `finally`**。

        ⚠️ 幂等：锁已过期或已易主时静默返回。释放失败**不抛异常** ——
        抛出去会把"已经成功返回的结果"变成一次错误响应，而锁的残留有 TTL 兜底。
        用 Lua 保证"查 + 删"原子，避免 `GET` 与 `DEL` 之间锁易主（那是第 2 条细节的漏洞面）。
        """
        await self._client.eval(RELEASE_SCRIPT, 1, key, holder)

    async def holder_of(self, key: str) -> Any:
        """读回持有者（**仅供诊断/测试**：任何授权判定都**不得**基于它 ——
        "读的时候是我的"与"用的时候还是我的"是两件事，这正是 Lua 存在的理由）。"""
        return await self._client.get(key)
