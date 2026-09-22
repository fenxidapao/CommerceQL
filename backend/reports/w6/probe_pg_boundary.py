"""PG 共享前置的**运行边界签名**探针（回应 W7 2026-09-22"跑前 + 跑后各一次"的方法）。

为什么要有这个文件（不是"再看一眼行数"）
----------------------------------------------
W6 一天里两次全量跑（`pytest`，含 `tests/integration/**`）落在 W7 取证的"共享前置被清"窗口内。
我方上一版用 `count(*)` / `count(embed_doc)` 做前后对照，得出"我方这轮没有改变那张表"——
**那个判据不成立**：一次破坏性重载（TRUNCATE + INSERT，或无 embedder 的 materialize）之后
行数与非空数**可以是同一个数**（197|197 → 197|197）。计数不敏感于重载，这正是
"统计量把我看不到包装成它没变"的形状。

所以这里改取**对重载敏感的签名**（全部只读，来自 `pg_stat_user_tables` / `pg_class`）：
`relfilenode`（TRUNCATE / VACUUM FULL / CLUSTER 会换数）、`truncates`、`n_tup_ins`、
`n_tup_del`、`n_tup_hot_upd`、`n_live_tup`、`last_vacuum|analyze`，外加 `pg_stat_reset()`
以来的时钟。用法：

    export COMMERCEQL_PROBE_DSN='<共享库 DSN，必须显式给>'   # 不给就 exit 2、不出产物
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_pg_boundary.py --label before-run
    ...（跑你要归因的那条命令）...
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_pg_boundary.py --label after-run \
        --diff-with before-run

⚠️ 本探针的观察对象**就是共享实例** ⇒ 连它必须是一次显式动作（不给字面默认 DSN，
与 U-114 防线①同形：缺 env 就终止，**不 skip**、不猜默认库）。

产物 = `backend/reports/w6/pg_boundary.json`：每次运行追加一条快照，`--diff-with` 时额外写
`delta`（逐表逐字段 A→B 及差值）。⚠️ 这些计数器是**累积的**且跨窗口共享 ⇒ 差值只能说明
"这段时间里存储文件被换过 / 插入了 M 行"，**不能**指名是谁；归因要有时间线与代码路径。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "eval"))

from pg_guard import force_readonly, open_readonly, redact_dsn, target_stamp  # noqa: E402

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: 🔴 **刻意不留字面默认值**（对齐 U-114 防线①：W0 `36c782a` + W2A `5e47558`）。
#: 本探针的观察对象**就是共享实例**（归因写副作用正是它的用途）⇒ 连它必须是一次
#: 显式的操作者动作，而不是"某个 env 忘了设"就自动发生。仍一律过 `force_readonly()`。
DSN = force_readonly(os.environ.get("COMMERCEQL_PROBE_DSN", ""))

#: 观察对象 = 跨窗口共享前置里被怀疑过的表（新增疑点时往这里加一项，别改判据）。
TABLES = ("cost_ledger", "embed_doc", "audit_log", "query_plan")

#: 对"重载"敏感的签名 —— `n_live_tup` 单独看**不**敏感（197→197 也可能被整表重灌）。
#: ⚠️ 本机 PG 16.15 的 `pg_stat_user_tables` **没有** `truncates`、也没有 `stats_reset` 列
#: （第一版照抄了较新版本的列名，实测抛 `column s.truncates does not exist`）⇒
#: "发生过 TRUNCATE" 在这台库上只能由 **`relfilenode` 变了** + **`n_tup_ins` 涨而 `n_tup_del` 不涨**
#: 这一对形状推断（TRUNCATE 换存储文件、且不计入 del）。列名以 `pg_attribute` 实测为准。
COLUMNS = ("relfilenode", "n_tup_ins", "n_tup_upd", "n_tup_del", "n_tup_hot_upd",
           "n_live_tup", "n_dead_tup", "n_mod_since_analyze", "n_ins_since_vacuum",
           "last_vacuum", "last_autovacuum", "last_analyze", "last_autoanalyze",
           "vacuum_count", "autovacuum_count", "analyze_count", "autoanalyze_count")

SQL = """
select c.relname,
       c.relfilenode,
       coalesce(s.n_tup_ins, 0),
       coalesce(s.n_tup_upd, 0),
       coalesce(s.n_tup_del, 0),
       coalesce(s.n_tup_hot_upd, 0),
       coalesce(s.n_live_tup, 0),
       coalesce(s.n_dead_tup, 0),
       coalesce(s.n_mod_since_analyze, 0),
       coalesce(s.n_ins_since_vacuum, 0),
       s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze,
       coalesce(s.vacuum_count, 0),
       coalesce(s.autovacuum_count, 0),
       coalesce(s.analyze_count, 0),
       coalesce(s.autoanalyze_count, 0)
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
left join pg_stat_user_tables s on s.relid = c.oid
where n.nspname = 'app' and c.relname = any(%s)
order by c.relname
"""


def _ser(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


async def snapshot() -> dict:
    conn = await open_readonly(DSN, purpose="probe_pg_boundary")
    try:
        stamp = await target_stamp(conn)
        rows = await (await conn.execute(SQL, (list(TABLES),))).fetchall()
    finally:
        await conn.close()
    tables = {}
    for r in rows:
        tables[f"app.{r[0]}"] = {k: _ser(v) for k, v in zip(COLUMNS, r[1:], strict=True)}
    missing = sorted({f"app.{t}" for t in TABLES} - set(tables))
    return {
        "taken_at_utc": datetime.now(UTC).isoformat(),
        "target": stamp,
        "dsn_redacted": redact_dsn(DSN),
        "tables": tables,
        "missing_tables": missing,  # 表不存在也要如实点名，别让它变成"没变化"
    }


def diff(before: dict, after: dict) -> dict:
    """逐表逐字段 A→B；只列**变了**的格子（没变的格子留在那里反而会被读成"查过了")。"""
    out: dict[str, dict] = {}
    for key in sorted(set(before.get("tables", {})) | set(after.get("tables", {}))):
        a, b = before.get("tables", {}).get(key, {}), after.get("tables", {}).get(key, {})
        changed = {f: {"before": a.get(f), "after": b.get(f),
                       "delta": (b[f] - a[f]) if isinstance(a.get(f), int) and isinstance(b[f], int)
                       else None}
                   for f in set(a) | set(b) if a.get(f) != b.get(f)}
        if changed:
            out[key] = changed
    return {"changed_tables": sorted(out), "silent_equal_tables": sorted(
        set(before.get("tables", {})) & set(after.get("tables", {})) - set(out)),
        "fields": out,
        "note": "relfilenode 变了 = 存储文件被换过（TRUNCATE/VACUUM FULL/CLUSTER）；"
                "truncates/n_tup_ins 增量 = 发生过整表清空与重灌。行数相同不代表没被动过。"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="这次快照叫什么（如 before-run / after-full-pytest）")
    ap.add_argument("--diff-with", default=None, help="与产物里哪个 label 做差（一般传前一次的 label）")
    args = ap.parse_args()
    if psycopg is None:
        print("psycopg 不在位 ⇒ 不探测（不猜结论）")
        return 2
    if not os.environ.get("COMMERCEQL_PROBE_DSN"):
        print("🔴 未设 COMMERCEQL_PROBE_DSN ⇒ 不探测。本探针看的是**共享实例**，"
              "连它必须是显式动作（不给字面默认 DSN，理由见文件头）；"
              "只读闸门仍会自证，缺 env 不出产物。")
        return 2

    dest = HERE / "pg_boundary.json"
    book = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
    book.setdefault("snapshots", {})
    book.setdefault("diffs", {})
    snap = asyncio.run(snapshot())
    book["snapshots"][args.label] = snap
    if args.diff_with:
        prev = book["snapshots"].get(args.diff_with)
        if prev is None:
            print(f"🔴 产物里没有 label={args.diff_with!r} ⇒ 差值不做（不编）")
            return 3
        book["diffs"][f"{args.diff_with} -> {args.label}"] = diff(prev, snap)  # type: ignore[index]
    dest.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(snap["tables"], ensure_ascii=False, indent=1))
    print(f"闸门自证：{snap['target']}")
    if args.diff_with:
        d = book["diffs"][f"{args.diff_with} -> {args.label}"]
        print(f"差值（{args.diff_with} → {args.label}）：变化的表 = {d['changed_tables']}；"
              f"逐字段读数见 {dest.name}")
    print("written:", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
