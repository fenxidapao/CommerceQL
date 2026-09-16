"""Redis 内存替身 —— **只覆盖被测路径用到的命令**。

归属窗口：W1B（`tests/unit/**` 随被测模块）。

## ⚠️ 这个替身能证明什么、**不能**证明什么（必须说清，否则会产生假绿灯）

| 能力 | 由谁覆盖 |
|---|---|
| 控制流：轮询间隔、等待上限、超时抛错、持有者判定结果的处理 | **本替身**（离线，快，可精确控制时间） |
| **Lua 脚本的语义本身**（`GET`+`PEXPIRE` 的原子性、ZSET 滑窗的边界、参数位序） | **只有真实 Redis**（`tests/integration/`） |

替身里的 `eval` 是通过**匹配脚本文本**分发到 Python 实现的，因此
"脚本写错了参数位序"这类错误**替身测不出来** —— 它照着自己理解的位序执行。
这就是为什么必须同时有集成用例：`test_real_redis_*` 系列跑的是真脚本。

**不实现 redis-py 的全部接口**（`hset` / `lpush` / …）：只实现被测路径用到的。
需要新命令时**加在这里**，不要在用例里 `unittest.mock.AsyncMock(spec=...)` ——
后者会让"调用了不存在的方法"变成静默通过。
"""

from __future__ import annotations

import time
from typing import Any

__all__ = ["FakeRedis"]


class FakeRedis:
    """最小内存替身。

    时间由 `time_ms` **手动推进**（不依赖真实时钟）：滑窗与 TTL 的边界测试
    必须能精确控制"过了多久"，否则只能靠 `sleep`，那会让用例既慢又抖。
    """

    def __init__(self, *, now_ms: int | None = None) -> None:
        #: key → (value, 过期时刻 monotonic ms 或 None)
        self.store: dict[str, tuple[str, int | None]] = {}
        #: key → {member: score}
        self.zsets: dict[str, dict[str, float]] = {}
        self.time_ms: int = int(time.time() * 1000) if now_ms is None else now_ms
        #: 记录所有 `eval` 调用（脚本名 + keys + argv），供"参数位序"类断言使用
        self.eval_calls: list[tuple[str, int, tuple[Any, ...]]] = []
        self.closed: bool = False

    # ---------------- 时间 ----------------
    def advance_ms(self, delta_ms: int) -> None:
        self.time_ms += delta_ms

    def _expired(self, key: str) -> bool:
        entry = self.store.get(key)
        if entry is None:
            return True
        _, expires_at = entry
        if expires_at is not None and expires_at <= self.time_ms:
            del self.store[key]
            return True
        return False

    # ---------------- 字符串 ----------------
    async def set(
        self, key: str, value: str, *, nx: bool = False, px: int | None = None
    ) -> bool | None:
        if nx and not self._expired(key):
            return None
        self.store[key] = (value, None if px is None else self.time_ms + px)
        return True

    async def get(self, key: str) -> str | None:
        if self._expired(key):
            return None
        return self.store[key][0]

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    async def ping(self) -> bool:
        return True

    async def info(self, section: str | None = None) -> dict[str, Any]:
        return {"redis_version": "fake-0.0.0", "section": section}

    async def aclose(self) -> None:
        self.closed = True

    # ---------------- 脚本 ----------------
    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        keys = [str(k) for k in keys_and_args[:numkeys]]
        argv = [str(a) for a in keys_and_args[numkeys:]]
        self.eval_calls.append((script, numkeys, tuple(keys_and_args)))

        if "ZREMRANGEBYSCORE" in script:
            return self._sliding_window(keys, argv)
        # 续租与释放：两段脚本的结构相同（`GET` 比较 + 一个动作），只在动作上不同。
        if "PEXPIRE" in script:
            return self._compare_and(self.store, keys[0], argv[0], lambda: self._pexpire(keys[0], int(argv[1])))
        if "DEL" in script:
            return self._compare_and(self.store, keys[0], argv[0], lambda: self.delete_sync(keys[0]))
        raise AssertionError(f"替身不认识这段脚本（请同步 _redis_fake.py）：\n{script}")

    def delete_sync(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    def _pexpire(self, key: str, px: int) -> int:
        if key not in self.store:
            return 0
        value, _ = self.store[key]
        self.store[key] = (value, self.time_ms + px)
        return 1

    def _compare_and(self, _store: Any, key: str, expected: str, action: Any) -> int:
        """Lua 里的 `if redis.call('GET', KEYS[1]) == ARGV[1] then ... else return 0 end`。"""
        if self._expired(key):
            return 0
        if self.store[key][0] != expected:
            return 0
        return int(action())

    def _sliding_window(self, keys: list[str], argv: list[str]) -> list[int]:
        """`SLIDING_WINDOW_SCRIPT` 的等价 Python 实现。

        ⚠️ 参数**位序**必须与脚本一致（`ARGV[1]=user_limit, ARGV[2]=tenant_limit,
        ARGV[3]=window_ms, ARGV[4]=member`）—— 位序错了这里也会错，且**不会红**。
        这正是"替身替代不了集成用例"的具体含义。
        """
        now = float(self.time_ms)
        ulim, tlim = int(argv[0]), int(argv[1])
        win = float(argv[2])
        member = argv[3]

        def prune_and_count(key: str) -> int:
            bucket = self.zsets.setdefault(key, {})
            for m in [m for m, s in bucket.items() if s <= now - win]:
                del bucket[m]
            return len(bucket)

        ucount = prune_and_count(keys[0]) if ulim > 0 else 0
        tcount = prune_and_count(keys[1]) if tlim > 0 else 0

        if (ulim > 0 and ucount >= ulim) or (tlim > 0 and tcount >= tlim):
            ref = now
            if ulim > 0 and ucount >= ulim and self.zsets[keys[0]]:
                ref = min(self.zsets[keys[0]].values())
            elif tlim > 0 and tcount >= tlim and self.zsets[keys[1]]:
                ref = min(self.zsets[keys[1]].values())
            return [0, ucount, tcount, int(ref)]

        if ulim > 0:
            self.zsets[keys[0]][member] = now
        if tlim > 0:
            self.zsets[keys[1]][member] = now
        return [1, ucount + 1, tcount + 1, int(now)]
