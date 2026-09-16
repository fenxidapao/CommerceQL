"""`jti` 撤销名单（07 §13.1 第 4 步）。

归属窗口：W1B。

⚠️ **本模块当前只提供内存实现，Redis 版尚未落地 —— 这是如实登记的缺口，不是遗漏。**

原因是一个**真实的契约缺口**：07 §13.1 第 4 步指定键为 `jwt:revoked:{jti}`
（TTL = 令牌剩余有效期），但 `app/cache/keys.py`（**W0 持有，唯一键构造入口**）
里**没有**对应的构造函数。而 §11.2 硬规则 3 明文："**禁止裸字符串拼键** ——
全项目只能调用 `app/cache/keys.py` 的函数"。

两条路都不能走：
- 在 `auth/` 里自己拼 `f"jwt:revoked:{jti}"` → 制造**第二份键规范**（硬规则 3 的直接违反）；
- 直接改 `cache/keys.py` → 越界（`docs/08 §4.1` 明确归 W0），且按 §4.3 四步流程只能提需求。

→ 因此：**接口与语义在本阶段全部定型并测试**（`RevocationChecker` 协议、
TTL 语义、失败模式），**Redis 实现留待 W0 在 `cache/keys.py` 增加
`jwt_revoked(jti)` 之后补**（改动仅限本文件，约 30 行）。
交付说明里已列出该项与所需 diff。

⚠️ 内存版**不是**"降级方案"，而是：
1. 单元测试的夹具（真实实现要用 Redis，不能进离线测试 —— N-01）；
2. 单实例 dev 的可用形态（进程重启即清空，与"令牌本身还没有被吊销"的语义一致）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

__all__ = ["InMemoryRevocationList", "RevocationChecker"]


@runtime_checkable
class RevocationChecker(Protocol):
    """撤销名单查询（07 §13.1 第 4 步）。

    ⚠️ 签名是 `async` 而非同步：生产实现要走 Redis，同步签名会逼出
    "在 async 上下文里跑同步 I/O"这种写法（它会阻塞整个 event loop）。
    """

    async def is_revoked(self, jti: str) -> bool: ...


class InMemoryRevocationList:
    """进程内撤销名单（TTL = 令牌剩余有效期）。

    ⚠️ 惰性过期而不是定时清理：撤销条目数 = "登出但令牌未过期"的数量，
    量级极小；而起一个后台清理任务会引入"任务挂了怎么办"的新问题
    （且 N-01 要求确定性模块离线可测 —— 后台任务会破坏这一点）。
    """

    def __init__(self) -> None:
        self._entries: dict[str, datetime] = {}

    def revoke(self, jti: str, *, expires_at: datetime) -> None:
        """把 `jti` 加入名单，直到令牌自然过期。

        ⚠️ `expires_at` 必须是**带时区**的（naive datetime 与 UTC 比较会抛 `TypeError`，
        而那个错误发生在**查询**路径上，看起来像"撤销名单坏了"）。
        """
        if expires_at.tzinfo is None:
            raise ValueError("expires_at 必须是带时区的 datetime（07 §13.1 第 4 步）")
        self._entries[jti] = expires_at.astimezone(UTC)

    def _purge(self, now: datetime) -> None:
        for jti in [k for k, exp in self._entries.items() if exp <= now]:
            del self._entries[jti]

    async def is_revoked(self, jti: str) -> bool:
        # `datetime.now(UTC)` 在这里是**允许**的：它是"当前时刻"用于 TTL 判定，
        # 不参与任何业务口径计算（N-18 禁的是**口径**读时间，不是禁止一切时钟读取；
        # 且本模块不依赖语义包，无法构造 `ClockPort`）。
        # ⚠️ 若架构窗口认为 TTL 判定也必须走 `ClockPort`，改动仅限本方法签名。
        now = datetime.now(UTC)
        self._purge(now)
        return jti in self._entries

    def __len__(self) -> int:
        return len(self._entries)
