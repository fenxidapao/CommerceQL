"""U-53 复现探针：依赖不可达时，lifespan 关闭段的四步各花多久。

复现 arch/DELIVERY.md 的实测形态（"退出 lifespan 2.00s"）：
    await redis_client.aclose()
    await pools.checkpoint.close()
    await pools.metadata.dispose()
    await pools.analytics.dispose()

对照组：
  A. 不可达 —— PostgreSQL 指向 localhost:5433（无监听 → 立即 RST）
  B. 可达   —— 本机 5432（当前有 PG 16 在跑）

用法（一律 PowerShell，venv python）：
  .venv/Scripts/python.exe backend/scripts/probe_pool_close_u53.py unreachable
  .venv/Scripts/python.exe backend/scripts/probe_pool_close_u53.py reachable
"""

from __future__ import annotations

import asyncio
import sys
import time

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PG_UNREACHABLE = "postgresql://app_rw:app_rw_pwd@localhost:5433/ecom"
PG_REACHABLE = "postgresql://app_rw:app_rw_pwd@localhost:5432/ecom"

REDIS_URL = "redis://localhost:6379/0"


def _hr(label: str) -> None:
    print(f"\n=== {label} ===")


async def _time_redis() -> None:
    import redis.asyncio as aioredis

    _hr("① redis.aclose()（先构造，不 ping）")
    client = aioredis.from_url(REDIS_URL)
    t0 = time.monotonic()
    await client.aclose()
    print(f"  aclose: {time.monotonic() - t0:.3f}s")


async def _time_checkpoint(dsn: str, mode: str, connect_timeout: float | None) -> None:
    from psycopg_pool import AsyncConnectionPool

    label = f"② checkpoint.close()（open(wait=False) 后 {mode}，connect_timeout={connect_timeout}）"
    _hr(label)
    kwargs = {}
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    pool = AsyncConnectionPool(
        conninfo=dsn, min_size=1, max_size=20, open=False, kwargs=kwargs
    )
    await pool.open(wait=False)
    await asyncio.sleep(0.5)  # 给 worker 机会去撞连接失败（模拟真实 shutdown 前的状态）
    t0 = time.monotonic()
    await pool.close()
    dt = time.monotonic() - t0
    print(f"  close: {dt:.3f}s")


async def _time_sqla_dispose(dsn: str, mode: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    _hr(f"③④ engine.dispose()（{mode}，pool_pre_ping=True，从未借出过连接）")
    for name in ("metadata", "analytics"):
        engine = create_async_engine(
            dsn, pool_size=10, max_overflow=10, pool_pre_ping=True
        )
        t0 = time.monotonic()
        await engine.dispose()
        print(f"  {name}.dispose: {time.monotonic() - t0:.3f}s")


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "unreachable"
    dsn = PG_UNREACHABLE if mode == "unreachable" else PG_REACHABLE
    print(f"mode = {mode}")
    await _time_redis()
    # 先测不带 connect_timeout（现状基线），再测带 2s 的（修复后形态）
    await _time_checkpoint(dsn, mode, connect_timeout=None)
    await _time_checkpoint(dsn, mode, connect_timeout=2)
    await _time_sqla_dispose(dsn.replace("postgresql://", "postgresql+psycopg://"), mode)


if __name__ == "__main__":
    asyncio.run(main())
