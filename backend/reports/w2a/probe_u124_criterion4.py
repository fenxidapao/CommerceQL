"""W2A U-124 判据④：真栈上 `SELECT pay_amount FROM v_order_paid` 经生产 analytics 池出数。

零 LLM / 零额度 / 只读。跑法（宿主机，CommerceQL 根；容器已热补丁新版 pools/config）：
    docker cp backend/app/repo/pools.py w7load-api:/srv/app/repo/pools.py
    docker cp backend/app/core/config.py w7load-api:/srv/app/core/config.py
    docker cp backend/reports/w2a/probe_u124_criterion4.py w7load-api:/tmp/c4.py
    MSYS_NO_PATHCONV=1 docker exec -e PYTHONPATH=/srv -w /srv w7load-api python /tmp/c4.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.repo.pools import build_analytics_engine

SQL = "SELECT pay_amount FROM v_order_paid LIMIT 3"
SQL_EXPLAIN = "EXPLAIN SELECT pay_amount FROM v_order_paid LIMIT 3"

_IDENTITY_SQL = (
    "SELECT set_config('app.tenant_id', :t, false), "
    "set_config('app.role', :r, false), set_config('app.shop_ids', :s, false)"
)
_IDENTITY_PARAMS = {"t": "T_A", "r": "analyst", "s": ""}


async def _one(engine: Any, sql: str) -> str:
    async with engine.connect() as conn:
        await conn.execute(text(_IDENTITY_SQL), _IDENTITY_PARAMS)
        sp = (await conn.execute(text("SELECT current_setting('search_path')"))).scalar()
        rows = (await conn.execute(text(sql))).fetchall()
        return f"OK rows={len(rows)} sample={[str(r[0]) for r in rows]}  search_path={sp}"


async def main() -> int:
    settings = get_settings()
    engine = build_analytics_engine(settings)
    try:
        print("判据④ SELECT pay_amount :", await _one(engine, SQL))
        print("判据④ EXPLAIN           :", await _one(engine, SQL_EXPLAIN))
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
