"""Redis 客户端的**唯一装配点** —— 与"三池唯一装配点"同一条纪律（N-14 / 07 §8.1）。

归属窗口：W1B。

## 为什么单独一个文件

Redis 在本系统里承载四样东西，**样样都是边界**，不是"一个缓存"：

| 用途 | 键（全部来自 `app/cache/keys.py`，禁止裸拼） | 失效后果 |
|---|---|---|
| 会话串行锁 | `lock:session:…` | 同一会话的两次查询并行 → 会话状态错乱（FR-10.5） |
| 分桶限流 | `rl:…` | 配额失效（滥用面） |
| 流重放事件缓冲 | `evt:…` | 断线无法续流（会静默停在"加载中"） |
| 语义缓存 / 版本指针 | `sem:…` / `semantic:active_version` | 口径漂移或全量回源 |

→ 因此它和连接池一样，**只能有一个构造函数**。散在各处 `from_url` 的后果不是报错，
而是"某个模块连的是 `db=1`，另一个连 `db=0`"——**限流计数与锁分散在两个逻辑库里**，
表现为"偶尔限不住"，且没有任何报错。

⚠️ 本模块**只造客户端，不做任何 I/O**：`redis.asyncio` 的连接是惰性的，
`from_url` 不建立任何 socket。这与 `app/main.py`「import 期零 I/O」的装配原则一致
（`build_checkpoint_pool` 的 `open=False` 是同一个理由）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from redis.asyncio import Redis

__all__ = ["build_redis_client"]


def build_redis_client(settings: Settings) -> Redis:
    """按 `REDIS_URL` 造客户端。

    ⚠️ `decode_responses=True` 是**刻意**的，不是顺手：
    本项目的 Redis 值分两类 —— 计数/锁（ASCII，如 `task_id`）与 JSON（幂等记录、事件帧）。
    用 `bytes` 的话每个调用点都要各自决定何时 `.decode()`，而漏掉一处就会得到
    `b'1' != '1'` 这类**静默为假**的比较（例如锁的持有者校验）。
    统一在客户端解码，判据只有一处。

    ⚠️ `socket_timeout` / `retry` **不在这里设**：它们必须按用途区分 ——
    会话锁的轮询间隔 200ms 与语义缓存的 1h TTL 对超时的容忍度完全不同，
    写死在客户端上会让一类调用被另一类的超时值绑住。
    """
    from redis.asyncio import Redis  # 见文件头：只造对象，不连

    return Redis.from_url(settings.REDIS_URL, decode_responses=True)
