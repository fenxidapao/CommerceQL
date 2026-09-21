"""并行少算的复现脚本（回应 W7 对 RELAY P7 的答复）。

W7 说：你们 8 组全绿的形状**只差一句** `reset app.shop_ids;`。这句话把状态从
"显式 set_config 设过值"换成"本会话从未设过 ⇒ RESET 留下值为 `''` 的占位符"。
两种状态在 SQL 里读出来是同一个 `''`，差别在 GUC 的内部形态（占位符是否随并行 worker 传过去），
而这正好能被 `count(*)` 抓到：**worker 扫不到 ⇒ leader 自己那一份就是读数**。

所以这个脚本不比"谁的说法对"，它一次跑完五态 × 并行开关，并把
`EXPLAIN (ANALYZE)` 里的 `Workers ... actual rows=` 原样带回来 —— 只看计划里有没有
Gather 不足以证明 worker 真扫了块（W7 与我在同一件事上各被骗过一次）。

只读：全程 `SELECT` / `RESET` / `SET ROLE`，不改任何数据。跑法：
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w6/_probe_parallel_states.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

try:  # 与 `_probe_pg_real.py` 同样：驱动不在位时不炸栈，只让探测如实报"未测"
    import psycopg
except ImportError:  # pragma: no cover - 取决于本机环境
    psycopg = None  # type: ignore[assignment]

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "backend"))

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

RO_DSN = os.environ.get(
    "COMMERCEQL_TEST_RO_DSN", "postgresql://app_ro:app_ro_pwd@localhost:5432/ecom"
)
SUPER_DSN = os.environ.get(
    "COMMERCEQL_TEST_SUPER_DSN", "postgresql://postgres:postgres@localhost:5432/ecom"
)
TENANT = "T_A"
VIEW = "v_order_paid"
RUNS = 3
COUNT_SQL = f'select count(*) from "app"."{VIEW}"'

#: 五态：① 两把 GUC 都显式设值（我方常驻探针原来只测这一态）② `RESET` 留下的 `''` 占位符
#: （W7 说少算就出在这一态）③ 从头到尾没碰过 `app.shop_ids`（= NULL，恒 0 行那一格）
#: ④ 真店铺清单 ⑤ W7 P1 提议的 `'*'` 哨兵（在当前策略文本下到底等不等于"不限"，测了才知道）。
STATES = ("never_touched", "explicit_empty", "reset_placeholder", "explicit_list", "sentinel_star")

#: `explicit_list` 用的真实店铺号，由 main 先从库里取（空 ⇒ 该状态判"未测"而不是 0==0）。
SHOP_SAMPLE: list[str] = []


async def _prep(con, state: str) -> dict:
    """把连接摆进目标状态，并如实记下每一步的结果（RESET 失败也要留痕，不许静默跳过）。"""
    steps: dict[str, str] = {}
    await con.execute("select set_config('app.tenant_id', %s, false)", (TENANT,))
    if state == "never_touched":
        steps["shop_ids"] = " untouched"
    elif state == "explicit_empty":
        cur = await con.execute("select set_config('app.shop_ids', '', false)")
        steps["shop_ids"] = f" set_config '' -> {(await cur.fetchone())[0]!r}"
    elif state == "reset_placeholder":
        try:
            await con.execute("reset app.shop_ids")
            cur = await con.execute("select current_setting('app.shop_ids', true)")
            steps["shop_ids"] = f" RESET ok -> {(await cur.fetchone())[0]!r}"
        except Exception as exc:
            await con.rollback()
            steps["shop_ids"] = f" RESET 失败 {type(exc).__name__}"
    elif state == "explicit_list":
        if not SHOP_SAMPLE:
            steps["shop_ids"] = " 未取到真实 shop_id ⇒ 本状态未测（不许退化成 0==0 的假绿）"
        else:
            joined = ",".join(SHOP_SAMPLE)
            cur = await con.execute("select set_config('app.shop_ids', %s, false)", (joined,))
            steps["shop_ids"] = f" set_config {joined!r} -> {(await cur.fetchone())[0]!r}"
    elif state == "sentinel_star":
        cur = await con.execute("select set_config('app.shop_ids', '*', false)")
        steps["shop_ids"] = f" set_config '*' -> {(await cur.fetchone())[0]!r}"
    return steps


async def _guc_form(con) -> dict:
    """GUC 的**内部形态**：占位符与显式设值在 `pg_settings.source` 上是两回事。"""
    rows = await (await con.execute(
        "select name, setting, coalesce(source,'—'), coalesce(sourcefile,'—') "
        "from pg_settings where name in ('app.shop_ids','app.tenant_id') order by name"
    )).fetchall()
    return {r[0]: {"setting": r[1], "source": r[2]} for r in rows}


async def _measure(con, mode: str) -> dict:
    """`mode` ∈ {"serial", "parallel"} —— 两态各数 RUNS 次，并带回"并行真发生了"的证据。

    ⚠️ 轴换过一次：第一版用 `debug_parallel_query` 的 off/on 当串行/并行。本机 PG16 这个参数
    只接受 `off / on / regress`，而且 **off 下计划里照样出现 Gather** ⇒ 那个"off"根本不是串行。
    现在：串行 = `max_parallel_workers_per_gather = 0`；并行 = 2 + `regress`（强制考虑并行路径）。
    并且必须看到 `Workers Launched ≥ 1` 才算这一格测到了并行 —— 只看"计划里有 Gather"不够：
    W7 的 canary 与本窗口第一版各被"结果恰好正确"骗过一次。
    """
    parallel = mode == "parallel"
    mpw = "2" if parallel else "0"
    dpq = "regress" if parallel else "off"
    await con.execute(
        "select set_config('max_parallel_workers_per_gather', %s, false)", (mpw,)
    )
    await con.execute("select set_config('debug_parallel_query', %s, false)", (dpq,))
    counts = []
    for _ in range(RUNS):
        try:
            cur = await con.execute(COUNT_SQL)
            counts.append((await cur.fetchone())[0])
        except Exception as exc:
            counts.append(f"ERR {type(exc).__name__}")
    plan = "\n".join(
        r[0] for r in await (await con.execute(
            f"explain (analyze, timing off, summary off) {COUNT_SQL}")).fetchall()
    )
    launch = re.search(r"Workers Launched:\s*(\d+)", plan)
    removed = re.search(r"Rows Removed by Filter:\s*(\d+)", plan)
    scan = re.search(r"Parallel [A-Za-z ]*Scan[^\n]*?rows=(\d+)", plan)
    return {
        "counts": counts,
        "parallel_node": "Gather" in plan,
        "workers_launched": int(launch.group(1)) if launch else 0,
        "rows_removed_by_filter": int(removed.group(1)) if removed else 0,
        "scan_rows_per_loop": int(scan.group(1)) if scan else None,
        "plan_head": plan.splitlines()[:6],
    }


#: 角色只走这张白名单（值不进 SQL 拼接的任意位置）：`app_ro` 是只读登录身份，
#: `app_rw` 用来复现 W7 的 `SET ROLE` 路径。**不写 superuser** —— 超级用户绕过 RLS，
#: 用它探出来的"读数正确"是假的。
ROLES = ("app_ro", "app_rw")


async def _probe(dsn: str, label: str, states: tuple[str, ...], *, as_role: str) -> dict:
    if as_role not in ROLES:
        raise ValueError(f"角色不在白名单：{as_role!r}")
    out: dict[str, dict] = {}
    for state in states:
        try:
            con = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        except Exception as exc:
            out[state] = {"connect": f"ERR {type(exc).__name__}: {exc}"}
            continue
        async with con:
            # ⚠️ 必须在**每条**连接上重设：SET ROLE 不跨连接继承，在外层连接上设一次
            # 等于后面所有状态都以登录身份跑（本脚本第一版就这么错过了一次）。
            await con.execute(f"set role {as_role}")
            entry = await _prep(con, state)
            entry["role"] = (await (await con.execute("select current_user, session_user")).fetchone())
            entry["guc_form"] = await _guc_form(con)
            entry["serial"] = await _measure(con, "serial")
            entry["parallel"] = await _measure(con, "parallel")
            s_nums = [x for x in entry["serial"]["counts"] if isinstance(x, int)]
            p_nums = [x for x in entry["parallel"]["counts"] if isinstance(x, int)]
            entry["measurable"] = bool(s_nums) and min(s_nums) > 0
            entry["parallel_ran"] = entry["parallel"]["workers_launched"] >= 1
            entry["equal"] = (
                entry["measurable"]
                and sorted(s_nums) == sorted(p_nums)
                and len(p_nums) == RUNS
            )
            out[state] = entry
    return {"role_path": label, "states": out}


async def _reset_parallel_con(runs: int = 3, *, extra_sql: str = ""):
    """摆出"少算那一格"的最小形状：显式设租户 + `RESET app.shop_ids` + 真并行。"""
    con = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=True)
    await con.execute("select set_config('app.tenant_id', %s, false)", (TENANT,))
    await con.execute("reset app.shop_ids")
    await con.execute("select set_config('max_parallel_workers_per_gather', '2', false)")
    await con.execute("select set_config('debug_parallel_query', 'regress', false)")
    if extra_sql:
        await con.execute(extra_sql)
    counts = [(await (await con.execute(COUNT_SQL)).fetchone())[0] for _ in range(runs)]
    return con, counts


async def _controls() -> dict:
    """三条直观解释为什么**不是**成因 —— 排除法也要有入库产物，不能只在对话里说。"""
    out: dict[str, object] = {}

    plan_cache: dict[str, list] = {}
    for threshold in (None, 1):
        for pcm in ("auto", "force_custom_plan", "force_generic_plan"):
            kw = {} if threshold is None else {"prepare_threshold": threshold}
            con = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=True, **kw)
            async with con:
                await con.execute("select set_config('app.tenant_id', %s, false)", (TENANT,))
                await con.execute("reset app.shop_ids")
                await con.execute("select set_config('plan_cache_mode', %s, false)", (pcm,))
                await con.execute(
                    "select set_config('max_parallel_workers_per_gather', '2', false)")
                await con.execute("select set_config('debug_parallel_query', 'regress', false)")
                n = [(await (await con.execute(COUNT_SQL)).fetchone())[0] for _ in range(4)]
            key = f"prepare_threshold={'default' if threshold is None else threshold}" \
                  f" × plan_cache_mode={pcm}"
            plan_cache[key] = n
        out["plan_cache"] = plan_cache

    nodes: dict[str, list] = {}
    for opt in ("enable_indexonlyscan", "enable_indexscan", "enable_parallel_append"):
        con, n = await _reset_parallel_con(extra_sql=f"set {opt} = off")
        async with con:
            nodes[opt] = n
    out["plan_node_options"] = nodes

    # ⚠️ 这一组**换过形状**：旧版是 `select coalesce(current_setting(...)) as v from 视图 group by v`，
    # 表达式里**没有列引用** ⇒ planner 把它提到 Gather 之上、只由 leader 算一次 ⇒ 根本测不到 worker，
    # 于是产出"worker 也看到 ''"这种**提升性伪影**（W7 指出，我方复算证实：同一条查询里
    # `Workers Launched = 2`，leader 格 `''` 与 worker 格 `<NULL-in-this-process>` 同时出现）。
    # 现在必须带列引用（`case when t.tenant_id is not null then …`）逐行求值，走基表
    # `traffic_daily`，身份用 `app_rw`（`app_ro` 读不到基表、也无权 `SET ROLE`），并在
    # **同一条计划**里核对 `Workers Launched ≥ 1`；不满足就整组作废（`void`），不许留假读数。
    q = ("select case when t.tenant_id is not null then "
         "coalesce(current_setting('app.shop_ids', true), '<NULL-in-this-process>') "
         "else '<unreachable>' end v, count(*) n "
         "from app.traffic_daily t group by 1 order by 1")
    con = await psycopg.AsyncConnection.connect(SUPER_DSN, autocommit=True)
    async with con:
        await con.execute("set role app_rw")
        await con.execute("select set_config('app.tenant_id', %s, false)", (TENANT,))
        await con.execute("reset app.shop_ids")
        await con.execute("select set_config('max_parallel_workers_per_gather', '2', false)")
        await con.execute("select set_config('debug_parallel_query', 'regress', false)")
        plan = "\n".join(r[0] for r in await (await con.execute(
            f"explain (analyze, timing off, summary off) {q}")).fetchall())
        launched = re.search(r"Workers Launched:\s*(\d+)", plan)
        workers = int(launched.group(1)) if launched else 0
        out["worker_side_guc_value"] = {
            "workers_launched": workers,
            "void": workers < 1,
            "rows": [list(r) for r in await (await con.execute(q)).fetchall()] if workers >= 1 else [],
            "shape": "带列引用的 CASE（`t.tenant_id is not null` 逼出逐行求值）× 基表 traffic_daily × app_rw",
            "note": "两格相加恒等于该租户总行数 ⇒ 占位符 GUC 没传到 worker；"
                    "leader 读 '' 而 worker 读 NULL ⇒ 这就是少算那一格的成因",
        }
    # 生产形状对照：`app/exec/executor.py` 走的是①（`IDENTITY_INJECTION_TEMPLATE` 用
    # `set_config(..., true)`，且与连接借用原子）。③ 是连接池复用最容易踩的一格。
    shapes: dict[str, dict] = {}
    tc = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=False)
    async with tc:
        async with tc.transaction():
            await tc.execute("select set_config('app.tenant_id', %s, true)", (TENANT,))
            await tc.execute("select set_config('app.shop_ids', '', true)")
            await tc.execute("select set_config('max_parallel_workers_per_gather', '2', true)")
            await tc.execute("select set_config('debug_parallel_query', 'regress', true)")
            shapes["①事务内 set_config(...,true)（生产形状）"] = {
                "counts": [(await (await tc.execute(COUNT_SQL)).fetchone())[0] for _ in range(4)]}
        # 提交后：两把键的**事务级**值都消失 ⇒ 这一格问的是"连接被池复用时会读到什么"
        await tc.commit()
        cur = await tc.execute(
            "select coalesce(current_setting('app.tenant_id', true), '<NULL>'), "
            "coalesce(current_setting('app.shop_ids', true), '<NULL>')")
        left_tenant, left_shops = (await cur.fetchone())
        shapes["③提交后复用同一把连接"] = {
            "guc_left": {"app.tenant_id": left_tenant, "app.shop_ids": left_shops},
            "counts": [(await (await tc.execute(COUNT_SQL)).fetchone())[0] for _ in range(4)]}
        await tc.rollback()
    sc = await psycopg.AsyncConnection.connect(RO_DSN, autocommit=True)
    async with sc:
        await sc.execute("select set_config('app.tenant_id', %s, false)", (TENANT,))
        await sc.execute("select set_config('app.shop_ids', '', false)")
        await sc.execute("select set_config('max_parallel_workers_per_gather', '2', false)")
        await sc.execute("select set_config('debug_parallel_query', 'regress', false)")
        shapes["②会话级 set_config(...,false)"] = {
            "counts": [(await (await sc.execute(COUNT_SQL)).fetchone())[0] for _ in range(4)]}
    out["production_shapes"] = shapes
    return out


async def main() -> int:
    if psycopg is None:
        print("psycopg 不在位 ⇒ 无法探测（不猜结论）")
        return 2
    result = {
        "view": f"app.{VIEW}",
        "tenant": TENANT,
        "runs_per_mode": RUNS,
        "policy_qual": None,
        "probes": [],
    }
    con = await psycopg.AsyncConnection.connect(SUPER_DSN, autocommit=True)
    async with con:
        result["policy_qual"] = (await (await con.execute(
            "select pg_get_expr(p.polqual, p.polrelid) from pg_policy p "
            "join pg_class c on c.oid = p.polrelid join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'app' and c.relname = 'order_paid' and p.polname = 'p_order_paid_tenant'"
        )).fetchone())[0]
        result["pg_version"] = (await (await con.execute("select version()")).fetchone())[0]
        result["max_parallel_workers_per_gather"] = (await (await con.execute(
            "select setting from pg_settings where name = 'max_parallel_workers_per_gather'"
        )).fetchone())[0]
        SHOP_SAMPLE.extend(str(r[0]) for r in await (await con.execute(
            "select shop_id from \"app\".\"order_paid\" where tenant_id = %s limit 2", (TENANT,)
        )).fetchall())
        result["shop_sample"] = list(SHOP_SAMPLE)
        # W7 只测了 `SET ROLE app_rw`；直接以 app_ro 登录那条路径他们没口令 ⇒ 我方补测。
        result["probes"].append(await _probe(RO_DSN, "app_ro 直接登录", STATES, as_role="app_ro"))
        result["probes"].append(await _probe(SUPER_DSN, "postgres 登录 + 每连接 SET ROLE app_rw",
                                             STATES, as_role="app_rw"))

    result["controls"] = await _controls()
    for p in result["probes"]:
        for s, e in p["states"].items():
            if "connect" in e:
                continue
            print(f"{p['role_path']:34s} {s:18s} equal={e['equal']!s:5} "
                  f"并行启动={e['parallel']['workers_launched']} "
                  f"串行={e['serial']['counts']} 并行={e['parallel']['counts']} "
                  f"Filter移除={e['parallel']['rows_removed_by_filter']} | {e.get('shop_ids')}")
    ctl = result["controls"]
    print("--- 排除法对照（都在 reset 占位符 + 真并行下）")
    for k, v in ctl["plan_cache"].items():
        print(f"    {k:66s} counts={v}")
    for k, v in ctl["plan_node_options"].items():
        print(f"    {k:66s} counts={v}")
    print(f"    worker 眼里的 app.shop_ids = {ctl['worker_side_guc_value']['rows']} "
          f"(Workers Launched={ctl['worker_side_guc_value']['workers_launched']})")
    for k, v in ctl["production_shapes"].items():
        print(f"    生产形状 {k:34s} counts={v['counts']}"
              + (f" 余值={v['guc_left']}" if "guc_left" in v else ""))
    out = HERE / "_probe_parallel_states.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
