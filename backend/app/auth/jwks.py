"""JWKS 获取与缓存（07 §13.1 第 2 步；ADR-17 本地 stub）。

归属窗口：W1B。

**这一步的失败模式与其他步完全不同，值得单独一个模块**：
它有一个**缓存**，而缓存 + 认证的组合有两类经典事故：

| 事故 | 触发方式 | 后果 |
|---|---|---|
| **缓存击穿** | 令牌带一个未知 `kid`，缓存 miss → 每个请求都去"刷新" | IdP 被打垮；同时把**每一次探测请求**变成一次对外请求 |
| **缓存全清** | 刷新时先 `clear()` 再填 | 刷新失败 = **认证全挂**；而刷新期间并发请求全部 miss → 风暴 |

07 §13.1 第 2 步的原文已经指定了防法：**"本地缓存 10 分钟；miss 时刷新一次，不清空缓存"**。
本模块就是这两句话的机器化实现：

1. `get(kid)`：命中且未过期 → 直接返回；
2. 过期或 miss → **刷新一次**（合并进缓存，**绝不 `clear()`**），然后再查一次；
3. 仍找不到 → `AuthError(step=2)`。

⚠️ **诚实边界**：ADR-17 的 stub 是"单文件 PEM"，`kid` 只有一个（`default`）。
真实 IdP 的 JWKS 是多 key + 轮转（`kid` 会变）。本模块的接口按**多 key** 设计
（`Mapping[str, KeyLike]`），因此换成真实 JWKS 端点时**只换 `JwksSource` 实现**
（ADR-17 的原话："只把 JWKS 来源做成配置"），缓存与刷新逻辑不动。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.auth.errors import AuthError

__all__ = ["JwksCache", "JwksSource", "PemFileJwksSource"]

#: PEM 文件里没有 `kid`，stub 用它当唯一键。令牌的 header 里 `kid` 缺省时也用它。
DEFAULT_KID: str = "default"

#: 07 §13.1 第 2 步：本地缓存 **10 分钟**。
JWKS_CACHE_TTL_S: int = 600


@runtime_checkable
class JwksSource(Protocol):
    """JWKS 来源。**唯一需要为换 IdP 而改的东西**（ADR-17）。"""

    async def fetch(self) -> Mapping[str, Any]: ...


class PemFileJwksSource:
    """单文件 PEM 公钥源（ADR-17 的本地 stub；也是单机部署的可用形态）。

    ⚠️ `load_pem_public_key` 不是装饰性的：**只读文件是不够的**。
    一个截断的 / 是私钥的 / 是证书而非公钥的文件，如果不在加载时炸，
    就会在每次校验时以 `InvalidSignatureError` 的形式表现出来 ——
    那会把"密钥配错了"误诊成"用户在伪造令牌"。
    """

    def __init__(self, path: str | Path, *, kid: str = DEFAULT_KID) -> None:
        self._path = Path(path)
        self._kid = kid

    async def fetch(self) -> Mapping[str, Any]:
        # `to_thread`：读文件是阻塞 I/O，在 event loop 里直接读会在冷启动（NFS/慢盘）时卡住所有请求
        pem = await asyncio.to_thread(self._path.read_bytes)
        return {self._kid: load_pem_public_key(pem)}


class JwksCache:
    """`kid` → 公钥 的带 TTL 缓存（07 §13.1 第 2 步的"miss 刷新一次，不清空缓存"）。

    ⚠️ `monotonic` 可注入是为了让 TTL 可测 —— 用 `time.time()`（墙钟）算 TTL
    会在 NTP 校时后得到负值或超长值，而这类 bug 只在特定时刻出现，几乎无法复现。
    """

    def __init__(
        self,
        source: JwksSource,
        *,
        ttl_s: int = JWKS_CACHE_TTL_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_s <= 0:
            raise ValueError(f"JWKS 缓存 TTL 必须为正数：{ttl_s}")
        self._source = source
        self._ttl_s = ttl_s
        self._monotonic = monotonic
        self._keys: dict[str, Any] = {}
        self._loaded_at: float | None = None
        #: 刷新串行化。**不是为了省请求**（省请求只是副产品），而是为了让
        #: "N 个并发请求同时 miss" 只产生 **1 次**对外/读盘动作 ——
        #: 否则一次 `kid` 扫描就能把 IdP 打满（缓存击穿的典型形态）。
        self._refresh_lock = asyncio.Lock()

    @property
    def cached_kids(self) -> tuple[str, ...]:
        """当前缓存里的 `kid`（供观测与测试；**不返回密钥本身**）。"""
        return tuple(sorted(self._keys))

    def _is_fresh(self) -> bool:
        return self._loaded_at is not None and (self._monotonic() - self._loaded_at) < self._ttl_s

    async def _refresh(self) -> None:
        async with self._refresh_lock:
            # 双检：等锁期间可能已经有别的协程刷好了
            if self._is_fresh():
                return
            try:
                fetched = await self._source.fetch()
            except Exception as exc:
                if self._keys:
                    # ⚠️ 这就是"不清空缓存"的价值：**刷新失败时旧 key 仍然可用**。
                    # 若这里先 clear() 再 fetch()，此刻缓存是空的 → 全部请求 401，
                    # 而真相只是"读文件/访问 IdP 抖了一下"。
                    return
                raise AuthError(
                    "无法获取签名公钥，认证不可用",
                    step=2,
                    reason=f"jwks_unavailable:{type(exc).__name__}",
                ) from exc
            # 合并而不是替换 —— 轮转期间新旧 `kid` 会同时存在，替换会让
            # "刚到手的旧令牌"（用上一个 kid 签的）瞬间失效。
            self._keys.update(fetched)
            self._loaded_at = self._monotonic()

    async def get(self, kid: str) -> Any:
        if self._is_fresh() and kid in self._keys:
            return self._keys[kid]
        await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise AuthError(
                "签名公钥与令牌 `kid` 不匹配",
                step=2,
                # 只报 `kid` 的**存在性**，不报它的值 —— 值可能被用来探测密钥轮转进度
                reason="unknown_kid",
            )
        return key
