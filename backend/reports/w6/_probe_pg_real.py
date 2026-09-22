"""W6 · 真 PostgreSQL 侧只读探测（D3 裁定：只读，绝不写业务数据）。

为什么要有这个文件
--------------------------------------------------------------------------
上一轮的报告写着「hostname `pg` 不可解析 ⇒ PG 侧全部 UNVERIFIED」。这个结论**来自
`ANALYTICS_DB_URL` 这一条路**，而集成测试用的是另一条路（`COMMERCEQL_TEST_*_DSN` 默认
`localhost:5432`）。两条路都验完才有资格说"PG 侧未验证"，否则就是把**自己没测**报告成
**环境测不了** —— 正是 §17.4 要防的那类叙述。

产出（全部只读）：
1. 沙箱 PG 库的对象面：schema / 表 / 视图 / alembic 版本
2. 每张业务表的真实行数（用来回答"PG 里到底有没有沙箱数据"）
3. RLS 策略表达式 + `relrowsecurity` / `relforcerowsecurity` 开关
4. 与 SQLite 沙箱的行数对照（§17.4「SQLite I/O 适配」缺口的量化证据）

运行：PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/_probe_pg_real.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # backend/reports/w6 -> reports -> backend -> CommerceQL
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "eval"))

# Windows：psycopg async 只支持 SelectorEventLoop（`tests/conftest.py:58` 同款处置）。
# 漏掉这一行时探测会报 `cannot use the 'ProactorEventLoop'` —— 那是**我的**循环问题，
# 不是环境不可达，绝不能记成"PG 测不了"。
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: 🔴 两条 DSN 一律过 `force_readonly()` —— 本探针**以 `postgres` 超管连接**（要看 `pg_policy` /
#: 建占位扩展），超管绕过 RLS 也绕过权限，"我只读"这句话在这个角色上等于没说。
#: 包完之后每条连接都会被服务端强制成只读事务，且 `main()` 里会**故意下发一次 CREATE TABLE**
#: 验证它真的被拒（`eval/pg_guard.py`）。W7 2026-09-22 要求"加一条会响的守卫"，落在这里。
from pg_guard import force_readonly  # noqa: E402

SUPER_DSN = force_readonly(os.environ.get(
    "COMMERCEQL_TEST_SUPER_DSN", "postgresql://postgres:postgres@localhost:5432/ecom"
))
RO_DSN = force_readonly(os.environ.get(
    "COMMERCEQL_TEST_RO_DSN", "postgresql://app_ro:app_ro_pwd@localhost:5432/ecom"
))
SQLITE_DB = REPO / "data" / "ecom_sandbox.db"

TABLES = (
    "campaign",
    "order_paid",
    "order_refund",
    "product",
    "region",
    "shop",
    "traffic_daily",
)
VIEWS = (
    "v_campaign",
    "v_order_paid",
    "v_order_refund",
    "v_product",
    "v_region",
    "v_shop",
    "v_traffic_daily",
    "v_user",
)


async def probe_pg() -> dict:
    import psycopg

    out: dict = {"dsn_host_user": SUPER_DSN.rsplit("@", 1)[-1].split("/")[0]}
    try:
        conn = await psycopg.AsyncConnection.connect(
            SUPER_DSN, row_factory=psycopg.rows.tuple_row, autocommit=True
        )
    except Exception as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}
    async with conn:
        cur = await conn.execute("select version()")
        out["version"] = (await cur.fetchone())[0]
        out["reachable"] = True

        # ---- schema / 迁移版本 ----
        # search_path 只有 public（app_ro 的授权范围），所以 app schema 的对象必须带限定名。
        # 这里刻意不加 app. 前缀的裸查询曾经直接报错并中止事务 —— 记在这里免得再踩。
        cur = await conn.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_schema in ('app','public') order by 1, 2"
        )
        out["tables"] = [f"{a}.{b}" for a, b in await cur.fetchall()]
        cur = await conn.execute(
            "select count(*) from information_schema.tables where table_schema='app'"
        )
        out["n_app_objects"] = (await cur.fetchone())[0]
        try:
            cur = await conn.execute("select version_num from public.alembic_version")
            out["alembic_version"] = [r[0] for r in await cur.fetchall()]
        except Exception as exc:
            out["alembic_version"] = f"ERR {type(exc).__name__}: {exc}"
            await conn.rollback()

        # ---- 真实行数：关系清单来自 information_schema，不靠猜名字 ----
        # （上一版硬写了 `v_user`，PG 里根本没有 ⇒ 报告出一条假的 ABSENT。
        #   探测器的产物一旦掺进推测，后面的缺口表就无从判起了。）
        cur = await conn.execute(
            "select table_name, table_type from information_schema.tables "
            "where table_schema='app' order by table_name"
        )
        rows = await cur.fetchall()
        pg_base = [r[0] for r in rows if r[1] == "BASE TABLE"]
        pg_views = [r[0] for r in rows if r[1] == "VIEW"]

        def count_of(rel: str) -> str:
            return (
                psycopg.sql.SQL('select count(*) from "app".{}')
                .format(psycopg.sql.Identifier(rel))
                .as_string(conn)
            )

        async def count_all(rels: list[str]) -> dict[str, int | str]:
            res: dict[str, int | str] = {}
            for rel in rels:
                try:
                    cur = await conn.execute(count_of(rel))
                    res[rel] = (await cur.fetchone())[0]
                except Exception as exc:
                    res[rel] = f"ERR {type(exc).__name__}"
                    await conn.rollback()
            return res

        out["pg_base_tables"] = pg_base
        out["pg_views"] = pg_views
        out["pg_row_counts"] = await count_all(pg_base)
        out["pg_view_counts"] = await count_all(pg_views)

        # ---- RLS：策略表达式 + 开关，两条都要（有策略但没 FORCE 等于对表属主无效）----
        cur = await conn.execute(
            "select tablename, policyname, permissive, cmd, roles, qual "
            "from pg_policies where schemaname='app' order by tablename"
        )
        out["rls_policies"] = [
            {
                "table": r[0],
                "policy": r[1],
                "permissive": r[2],
                "cmd": r[3],
                "roles": r[4],
                "qual": r[5],
            }
            for r in await cur.fetchall()
        ]
        cur = await conn.execute(
            "select c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname='app' and c.relkind in ('r','v') order by 1"
        )
        out["rls_flags"] = [
            {"rel": r[0], "row_security": r[1], "force": r[2]} for r in await cur.fetchall()
        ]

        # ---- app_ro 视角（生产只读角色到底看得见什么）----
        try:
            ro = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=True)
            async with ro:
                cur = await ro.execute(
                    "select count(*) from information_schema.tables "
                    "where table_schema in ('app','public')"
                )
                out["app_ro_visible_objects"] = (await cur.fetchone())[0]
                try:
                    cur = await ro.execute('select count(*) from "app"."v_order_paid"')
                    out["app_ro_can_read_view"] = (await cur.fetchone())[0]
                except Exception as exc:
                    out["app_ro_can_read_view"] = f"DENIED {type(exc).__name__}"
                try:
                    cur = await ro.execute(
                        "select current_setting('is_superuser'), "
                        "(select count(*) from pg_policies where schemaname='app')"
                    )
                    r = await cur.fetchone()
                    out["app_ro_non_superuser_with_policies"] = [r[0], r[1]]
                except Exception as exc:
                    out["app_ro_non_superuser_with_policies"] = f"ERR {type(exc).__name__}"
        except Exception as exc:
            out["app_ro"] = f"UNREACHABLE {type(exc).__name__}: {exc}"

        # ---- 带租户上下文的 RLS 有效性（评测真正关心的那一面）----
        # ⚠️ 这一段的由来：上一版只 count 了视图就报告"PG 业务事实表 0 行 ⇒ 不可测"。
        #    实测**那句结论的成因写错了**：基表里有 200 万行，视图返 0 行是因为
        #    `p_*_tenant` 策略里 `current_setting('app.shop_ids', true) = ''` 这一支在
        #    GUC **未设**时取到 NULL ⇒ 整条策略恒 false（视图按**视图属主**求策略，
        #    所以连绕开 RLS 的属主连接也一样返 0 行）。也就是"我没设上下文"被写成了
        #    "环境没数据" —— 正是 §17.4 要防的那类叙述。
        try:
            tenants = [
                r[0] for r in await (await conn.execute(
                    'select distinct tenant_id from "app"."order_paid" order by 1'
                )).fetchall()
            ]
            out["tenants_in_data"] = tenants
            TENANT_SCOPED = {
                "v_order_paid": "order_paid", "v_order_refund": "order_refund",
                "v_traffic_daily": "traffic_daily", "v_product": "product",
                "v_shop": "shop", "v_campaign": "campaign",
            }
            scoped_views = [v for v in pg_views if v.removeprefix("v_") in set(TENANT_SCOPED.values())]
            ro = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=True)
            per_tenant: dict[str, dict[str, int | str]] = {}
            async with ro:
                for ten in tenants:
                    await ro.execute("select set_config('app.tenant_id', %s, false)", (ten,))
                    await ro.execute("select set_config('app.shop_ids', '', false)")
                    res: dict[str, int | str] = {}
                    for v in scoped_views:
                        try:
                            cur = await ro.execute(f'select count(*) from "app"."{v}"')
                            res[v] = (await cur.fetchone())[0]
                        except Exception as exc:
                            res[v] = f"ERR {type(exc).__name__}"
                            await ro.rollback()
                    per_tenant[ten] = res
                # 负对照 A：另开一条**从未 set_config 过**的连接 ⇒ 复现上一版那个 0 行的成因。
                # （PG 没有 `reset_config(text, bool)` 这个函数，只有 `set_config` + SQL `RESET`，
                #   所以要用新会话，而不是在同一条连接上"撤销"。）
                if tenants:
                    fresh = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=True)
                    async with fresh:
                        try:
                            cur = await fresh.execute(
                                "select set_config('app.tenant_id', %s, false)", (tenants[0],))
                            await cur.fetchone()
                            cur = await fresh.execute('select count(*) from "app"."v_order_paid"')
                            out["rls_negative_no_context"] = (await cur.fetchone())[0]
                        except Exception as exc:
                            out["rls_negative_no_context"] = f"ERR {type(exc).__name__}"
                    # 负对照 B：设一个数据里不存在的租户 ⇒ 也应 0 行（不泄露也不凭空造数）。
                    await ro.execute("select set_config('app.tenant_id', 'T_NOT_A_TENANT', false)")
                    try:
                        cur = await ro.execute('select count(*) from "app"."v_order_paid"')
                        out["rls_negative_unknown_tenant"] = (await cur.fetchone())[0]
                    except Exception as exc:
                        out["rls_negative_unknown_tenant"] = f"ERR {type(exc).__name__}"
            out["rls_per_tenant_view_counts"] = per_tenant
            # 带上下文的可见数才是评测面 ⇒ 覆盖 pg_view_counts，零上下文那份另存反证。
            out["pg_view_counts_no_context"] = dict(out["pg_view_counts"])
            out["pg_view_counts"] = {
                **out["pg_view_counts_no_context"],
                **{
                    v: sum(
                        x for x in (per_tenant.get(t, {}).get(v) for t in per_tenant)
                        if isinstance(x, int)
                    )
                    for v in scoped_views
                },
            }
            out["pg_view_counts_scope"] = (
                "`pg_view_counts` = 角色 `app_ro` 在 set_config('app.tenant_id', 各租户) + "
                "set_config('app.shop_ids','') 下的可见行数**跨租户求和**；"
                "零上下文的读法（租户域视图一律 0 行）保留在 `pg_view_counts_no_context`"
            )
            # 跨租户不重不漏的机器判据：各租户可见数之和 == 属主看到的基表总数。
            out["rls_partition_check"] = {
                v: {
                    "sum_over_tenants": out["pg_view_counts"][v],
                    "owner_total": out["pg_row_counts"].get(TENANT_SCOPED.get(v, v), -1),
                }
                for v in scoped_views
            }
            out["rls_partition_ok"] = all(
                c["sum_over_tenants"] == c["owner_total"]
                for c in out["rls_partition_check"].values()
            )
            # ---- 并行 vs 串行：同一条 SQL 必须给同一个数 ----
            # 为什么常驻在探针里：租户策略里的 `current_setting('app.shop_ids', true)` 在
            # **并行 worker 眼里可以是 NULL**（当该键只是 RESET 留下的占位符时），于是 worker
            # 整片被过滤掉、`count(*)` 静默少算且不报错。N-07 抓不到这种错（策略照样生效，
            # 只是分量丢了），所以它是 PG 执行链的**前置判据**，不是可选检查。
            # ⚠️ 这一格第一轮探针只测了"显式设值"一种形态 ⇒ 恒绿，而恒绿正是它能藏错的原因。
            out["parallel_equality"] = await _parallel_equality(
                tenants[0] if tenants else "T_A", "v_order_paid", "v_traffic_daily"
            )
            out["parallel_equality_ok"] = all(
                v["state_ok"] for v in out["parallel_equality"].values()
            )
            # 按**形态**聚合的三态：
            # · False —— 有视图"串行有数、并行对不上"（真不符）
            # · None  —— 没有任何一个"可测且并行真跑起来"的格子（例如两把键都没设 ⇒ 恒 0 行，
            #   0 == 0 不能读成"等值通过"）
            # · True  —— 至少一个格子可测且真跑了并行，且没有一个格子不符
            out["parallel_state_ok"] = {}
            for state, _ in PARALLEL_GUC_STATES:
                cells = [
                    per_view["states"][state]
                    for per_view in out["parallel_equality"].values()
                    if state in per_view["states"]
                ]
                if any(c["measurable"] and not c["equal"] for c in cells):
                    out["parallel_state_ok"][state] = False
                elif any(c["measurable"] and c["parallel_ran"] for c in cells):
                    out["parallel_state_ok"][state] = True
                else:
                    out["parallel_state_ok"][state] = None
            out["parallel_undercount_states"] = sorted(
                f"{view}/{state}"
                for view, per_view in out["parallel_equality"].items()
                for state in per_view["undercount_in"]
            )
        except Exception as exc:
            out["rls_effectiveness"] = f"UNREACHABLE {type(exc).__name__}: {exc}"

    return out


#: `app.shop_ids` 的四种**都能到达 RLS 策略**的形态。少算只出在其中一格 ⇒ 只测一种必然恒绿。
PARALLEL_GUC_STATES: tuple[tuple[str, str], ...] = (
    ("explicit_empty", "显式 set_config('')，= 不限店铺（生产执行链的形状）"),
    ("reset_placeholder", "RESET app.shop_ids ⇒ 键本会话从未设过，留下值为 '' 的占位符"),
    ("never_touched", "全程不碰 app.shop_ids ⇒ current_setting 取 NULL"),
    ("sentinel_star", "set_config('*')（W7 的 P1 哨兵提议；策略文本里 `= ''` 不成立）"),
)


async def _set_guc_state(con, state: str) -> str:
    """把连接摆进目标形态，并如实记下这一句到底做了什么（RESET 失败不许静默跳过）。"""
    if state == "never_touched":
        return "untouched"
    if state == "explicit_empty":
        cur = await con.execute("select set_config('app.shop_ids', '', false)")
        return f"set_config '' -> {(await cur.fetchone())[0]!r}"
    if state == "reset_placeholder":
        try:
            await con.execute("reset app.shop_ids")
        except Exception as exc:
            await con.rollback()
            return f"RESET 失败 {type(exc).__name__}"
        cur = await con.execute("select current_setting('app.shop_ids', true)")
        return f"RESET ok -> {(await cur.fetchone())[0]!r}"
    if state == "sentinel_star":
        cur = await con.execute("select set_config('app.shop_ids', '*', false)")
        return f"set_config '*' -> {(await cur.fetchone())[0]!r}"
    raise ValueError(f"未知形态：{state}")


async def _count_under(con, q: str, *, parallel: bool, runs: int) -> dict:
    """在"真串行 / 真并行"下各数 `runs` 次，并带回**并行真的发生了**的证据。

    ⚠️ 轴换了：第一版拿 `debug_parallel_query` 的 off/on 当串行/并行 —— 本机 PG16 只接受
    `off/on/regress` 三个取值，且 **off 下计划里照样有 Gather** ⇒ 那个"off"根本不是串行。
    现在串行 = `max_parallel_workers_per_gather = 0`，并行 = 2 + `regress`（强制考虑并行路径），
    并以 `Workers Launched ≥ 1` 为"测到了"的判据 —— 只看计划里有没有 Gather 不够，
    "结果恰好正确"这一格已经骗过 W7 一次、也骗过本窗口一次。
    """
    mpw = "2" if parallel else "0"
    dpq = "regress" if parallel else "off"
    await con.execute(
        "select set_config('max_parallel_workers_per_gather', %s, false)", (mpw,)
    )
    await con.execute("select set_config('debug_parallel_query', %s, false)", (dpq,))
    counts = []
    for _ in range(runs):
        try:
            cur = await con.execute(q)
            counts.append((await cur.fetchone())[0])
        except Exception as exc:
            counts.append(f"ERR {type(exc).__name__}")
    plan = "\n".join(
        r[0] for r in await (await con.execute(f"explain (analyze, timing off) {q}")).fetchall()
    )
    launched = re.search(r"Workers Launched:\s*(\d+)", plan)
    removed = re.search(r"Rows Removed by Filter:\s*(\d+)", plan)
    return {
        "counts": counts,
        "gather_node": "Gather" in plan,
        "workers_launched": int(launched.group(1)) if launched else 0,
        "rows_removed_by_filter": int(removed.group(1)) if removed else 0,
    }


async def _parallel_equality(tenant: str, *views: str, runs: int = 3) -> dict:
    """视图 × GUC 形态 × 串行/并行 的等值矩阵。每格**新连接**（复用连接会让上一格的状态漏进来）。

    判定只认"串行有数"的格：串行都是 0 行的形态（NULL / `'*'`）里 `0 == 0` 也会"等值"，
    那种恒等不能算通过 —— 它测不到任何分量。
    """
    import psycopg  # 与 probe_pg() 同为延迟导入（模块顶层不依赖驱动在位）

    result: dict[str, dict] = {}
    for v in views:
        q = f'select count(*) from "app"."{v}"'
        per_state: dict[str, dict] = {}
        undercount: list[str] = []
        for state, note in PARALLEL_GUC_STATES:
            con = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=True)
            async with con:
                await con.execute("select set_config('app.tenant_id', %s, false)", (tenant,))
                applied = await _set_guc_state(con, state)
                ser = await _count_under(con, q, parallel=False, runs=runs)
                par = await _count_under(con, q, parallel=True, runs=runs)
            ser_nums = [x for x in ser["counts"] if isinstance(x, int)]
            par_nums = [x for x in par["counts"] if isinstance(x, int)]
            measurable = bool(ser_nums) and min(ser_nums) > 0
            # 没起 worker 的两格相等什么也证明不了 ⇒ 不算测到，更不算通过。
            parallel_ran = par["workers_launched"] >= 1
            equal = (
                measurable
                and parallel_ran
                and sorted(ser_nums) == sorted(par_nums)
                and len(par_nums) == runs
            )
            if measurable and parallel_ran and not equal:
                undercount.append(state)
            per_state[state] = {
                "note": note,
                "guc_applied": applied,
                "serial": ser,
                "parallel": par,
                "measurable": measurable,
                "parallel_ran": parallel_ran,
                "equal": equal,
            }
        result[v] = {
            "states": per_state,
            "undercount_in": undercount,
            "state_ok": not undercount,
        }
    return result


def probe_sqlite() -> dict:
    if not SQLITE_DB.exists():
        return {"error": f"missing {SQLITE_DB}"}
    con = sqlite3.connect(f"{SQLITE_DB.as_uri()}?mode=ro", uri=True)
    try:
        catalog = con.execute(
            "select name, type from sqlite_master "
            "where name not like 'sqlite_%' order by name"
        ).fetchall()
        sq_tables = [n for n, t in catalog if t == "table"]
        sq_views = [n for n, t in catalog if t == "view"]

        def count(rel: str) -> int:
            return con.execute(f'select count(*) from "{rel}"').fetchone()[0]

        return {
            "objects": [n for n, _ in catalog],
            "sqlite_base_tables": sq_tables,
            "sqlite_views": sq_views,
            "sqlite_row_counts": {t: count(t) for t in sq_tables},
            "sqlite_view_counts": {v: count(v) for v in sq_views},
            "tenants": (
                [r[0] for r in con.execute(
                    "select distinct tenant_id from app_user order by 1"
                )]
                if "app_user" in sq_tables
                else "NO app_user"
            ),
        }
    finally:
        con.close()


def parity(sq: dict, pg: dict) -> dict:
    """SQLite 沙箱 vs 真 PG 的行数对照（§17.4「只有 SQLite 面被度量」的量化证据）。

    这一栏存在的意义：`reachable=True` 不等于"能在 PG 上跑评测"。事实表全空时，
    RLS 有效性、跨租户隔离、结果集等价在 PG 侧都是**空对空**（0 行 vs 0 行必然相等），
    那种"通过"比不测更糟 —— 它会把未验证说成已验证。
    """
    s, p = sq.get("sqlite_row_counts", {}), pg.get("pg_row_counts", {})
    sv, pv = sq.get("sqlite_view_counts", {}), pg.get("pg_view_counts", {})
    rows = []
    for rel in sorted(set(s) | set(p) | set(sv) | set(pv)):
        rows.append(
            {
                "rel": rel,
                "sqlite": s.get(rel, sv.get(rel, "-")),
                "pg": p.get(rel, pv.get(rel, "-")),
                "sqlite_kind": "view" if rel in sv else ("table" if rel in s else "-"),
                "pg_kind": "view" if rel in pv else ("table" if rel in p else "-"),
            }
        )
    fact_rels = ("v_order_paid", "v_order_refund", "v_traffic_daily", "v_product", "v_shop")

    def fact_total(counts: dict[str, int | str], views: dict[str, int | str]) -> int:
        """按关系名取行数，表/视图两种落法都认。

        实测差异：SQLite 沙箱把 `v_*` 落成**物理表**（`sqlite_views` 为空），PG 侧是**视图**。
        只查一侧会得出"沙箱 0 行业务数据"这种反事实结论 —— 上面那条 200 万行的对照就是这么丢的。
        """
        return sum(
            v
            for r in fact_rels
            for v in [counts.get(r, views.get(r, 0))]
            if isinstance(v, int)
        )

    pg_fact_total = fact_total(p, pv)
    sq_fact_total = fact_total(s, sv)
    return {
        "relations": rows,
        "pg_reachable": bool(pg.get("reachable")),
        "pg_business_fact_rows": pg_fact_total,
        "sqlite_business_fact_rows": sq_fact_total,
        "pg_rls_measurable_with_real_data": pg_fact_total > 0,
        "pg_rls_policies_n": len(pg.get("rls_policies") or []),
        "pg_rls_forced_relations": [
            r["rel"] for r in pg.get("rls_flags", []) if r.get("force")
        ],
        "verdict": (
            "PG 可达且 RLS 策略在位，但业务事实表为空 ⇒ PG 侧只能验**结构/权限面**，"
            "结果集等价与 RLS 有效性仍不可测"
            if pg.get("reachable") and pg_fact_total == 0
            else ("PG 有事实数据 ⇒ 可评估把评测主链路切到 PG" if pg_fact_total else "PG 不可达")
        ),
    }


async def main() -> None:
    from pg_guard import open_readonly, redact_dsn, target_stamp

    # 🔴 闸门自证放在最前面：没过就不出产物（一份"我们以为只读"的读数比没有读数更贵）。
    guard: dict[str, object] = {}
    for label, dsn in (("super", SUPER_DSN), ("app_ro", RO_DSN)):
        conn = await open_readonly(dsn, purpose=f"_probe_pg_real/{label}")
        try:
            guard[label] = {**(await target_stamp(conn)), "dsn_redacted": redact_dsn(dsn)}
        finally:
            await conn.close()

    sq, pg = probe_sqlite(), await probe_pg()
    payload = {"sqlite_sandbox": sq, "pg": pg, "parity": parity(sq, pg), "pg_guard": guard}
    dest = HERE / "_probe_pg_real.json"
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["parity"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
