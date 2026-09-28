"""只读定位：A 臂 count=0 是名称解析问题，还是 RLS 身份未给？（零 DeepSeek）"""

import asyncio

from app.core.config import Settings
from app.repo.pools import build_analytics_engine
from sqlalchemy import text


async def one(conn, sql):
    try:
        return (await conn.execute(text(sql))).fetchall()
    except Exception as exc:  # noqa: BLE001
        return f"ERR {type(exc).__name__}: {str(exc)[:120]}"


async def main() -> None:
    engine = build_analytics_engine(Settings())
    async with engine.connect() as conn:
        print("current_user      =", await one(conn, "select current_user, current_schema()"))
        print("rolbypassrls      =", await one(
            conn, "select rolname, rolbypassrls from pg_roles where rolname=current_user"))
        print("search_path       =", await one(conn, "show search_path"))
        print("count no tenant   =", await one(conn, "select count(*) from v_order_paid"))
        await conn.execute(text("select set_config('app.tenant_id','T_A', false)"))
        print("count T_A         =", await one(conn, "select count(*) from v_order_paid"))
        print("tenant seen       =", await one(
            conn, "select current_setting('app.tenant_id', true)"))
        print("view relkind      =", await one(
            conn, "select relname, relrowsecurity from pg_class where relname='v_order_paid'"))
        print("view def head     =", str(await one(
            conn, "select pg_get_viewdef('app.v_order_paid'::regclass, true)"))[:400])
    await engine.dispose()


asyncio.run(main())
