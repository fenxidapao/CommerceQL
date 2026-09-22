"""W7 A/B：analytics 池到底解不解得开非限定资产名 —— 零 LLM / 零额度 / 只读 SELECT。

触发：2026-09-22 19:48 真栈 c=1 预检判据④ 未过。链上实测序列（`docker logs w7load-api`）：
gen_sql → gate3 `EXPLAIN 不可用 → warn` → **`exec_failed error_class=unknown_table`** →
repair → 终态 `GATE_AST_REJECTED`。离线闸门对照（`scratch_searchpath_asset_face_probe.py`）
同时钉住：非限定合法资产名 gate1/gate2 **全过**；带 `app.` 前缀一律 **R16**
（`ast_gate.py:531-534` 注释：带 schema 前缀 = 绕白名单形态）。

⇒ 两半合起来是一个死锁，本脚本证前半（解析面）：

| 臂 | 连接 | SQL | 读数（2026-09-22 19:5x 本机） |
|---|---|---|---|
| A | 生产 analytics 池（`build_analytics_engine`，原样） | `from v_order_paid` | 见输出 |
| B | 同一条连接先 `SET search_path = app, public` | `from v_order_paid` | 见输出 |
| C | 按 `lg` 的既有先例给池加 `-c search_path=app` | `from v_order_paid` | 见输出 |
| D = B 行 2 | B 臂同连接（对照） | `from app.v_order_paid` | 见输出 |
| E = A 行 2 | 生产池原样 | `EXPLAIN … from v_order_paid` | 见输出 |
| F = C 行 2 | 池级 `-c search_path=app` | `EXPLAIN … from v_order_paid` | 见输出 |

E/F 的动机：真栈日志里 gate3 报 `EXPLAIN 不可用 → warn`。若 E 与 execute 同为
`relation does not exist`、F 能出计划 ⇒ **两处同因**，修 `search_path` 一处即一起复原
（不是两个独立缺陷，也不该记成两笔账）。

⚠️ 口径：本脚本不经 `PgSqlExecutor`，直接借同一个池。理由 = 名字解析是**连接属性**，
而 `_controlled_session`（`app/exec/executor.py:257-300`）不含 `search_path`
（`git grep -n search_path backend/app/exec/` 为空，可复验）⇒ 身份注入/超时只影响**可见行**，
不影响 A 臂的报错。四臂都在只读角色 `app_ro` 的池上，语句只有 SELECT。

跑法（宿主机，CommerceQL 根）：
    docker cp backend/reports/w7/scratch_searchpath_ab.py w7load-api:/tmp/ab.py
    docker exec -w /srv w7load-api python /tmp/ab.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.repo.pools import build_analytics_engine

SQL_BARE = "SELECT count(*) FROM v_order_paid"
SQL_QUAL = "SELECT count(*) FROM app.v_order_paid"
SQL_EXPLAIN = "EXPLAIN SELECT count(*) FROM v_order_paid"

#: ADR-09 的身份注入（`repo/dsn.IDENTITY_INJECTION_TEMPLATE` 的三键，改成客户端绑定形态）。
#: 不注入则 RLS 把行滤光 ⇒ B/C 臂的"出数"会成假读数。
_IDENTITY_SQL = (
    "SELECT set_config('app.tenant_id', :t, false), "
    "set_config('app.role', :r, false), set_config('app.shop_ids', :s, false)"
)
_IDENTITY_PARAMS = {"t": "T_A", "r": "analyst", "s": ""}


async def _readout(conn: Any, sql: str) -> str:
    try:
        sp = (await conn.execute(text("SELECT current_setting('search_path')"))).scalar()
        row = (await conn.execute(text(sql))).first()
        cell = str(row[0])[:60] if row else "无行"
        return f"OK {cell}  search_path={sp}"
    except Exception as exc:
        return f"{type(exc).__name__}: {str(getattr(exc, 'orig', exc))[:90]}"


async def _one(engine: Any, sql: str, preset: str | None) -> str:
    """**每条语句各借一条新连接**：共用连接时 A 臂第一条失败会让同一事务里的第二条
    只返回 `current transaction is aborted` —— 那是量具假读数，E 臂首跑就中招过。"""
    async with engine.connect() as conn:
        if preset:
            await conn.execute(text(preset))
        await conn.execute(text(_IDENTITY_SQL), _IDENTITY_PARAMS)
        return await _readout(conn, sql)


async def _arm(label: str, engine: Any, preset: str | None,
               extra: tuple[tuple[str, str], ...] = ()) -> None:
    print(f"{label:14}非限定资产名 : {await _one(engine, SQL_BARE, preset)}")
    for name, sql in extra:
        print(f"{label:14}{name:12} : {await _one(engine, sql, preset)}")
    await engine.dispose()


async def main() -> int:
    settings = get_settings()
    await _arm("A 生产池原样", build_analytics_engine(settings), None,
               (("EXPLAIN", SQL_EXPLAIN),))
    await _arm("B 连接内 SET", build_analytics_engine(settings),
               "SET search_path = app, public", (("限定名", SQL_QUAL),))
    await _arm("C 池级 -c 固定",
               create_async_engine(settings.ANALYTICS_DB_URL,
                                   connect_args={"options": "-c search_path=app"}),
               None, (("EXPLAIN", SQL_EXPLAIN),))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
