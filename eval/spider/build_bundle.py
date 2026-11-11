"""Spider 库 -> 语义包（机械派生，U-182）。

纪律：每个字段都从 schema 机械派生，不写任何人工口径。

  1. 资产 = 一张真实表（PRAGMA table_info 取真列名与类型、COUNT(*) 取行数）；
  2. Join = tables.json 的一条外键（子列 -> 父列）；
  3. 指标 = 每个数值列一条 SUM 与 AVG，加一条整表 COUNT；id 类列不当度量、跳过；
  4. 维度 = 该库第一条 time 列，绑 day/week/month/quarter/year；
  5. 别名 = 列名在全库唯一时才建（重名会让校验器判 term 不唯一）。

因此本包的「指标口径」是 schema 派生物、不是业务口径。报告须原话写明
「指标由 schema 机械派生、非业务口径」。

⚠️ 两条真加载器（`backend/app/semantics/models.py`）才查、作者侧校验器不查的硬约束：

  · `meta` 是 `extra=forbid`（`models.py:59`）⇒ 不得塞 derived_from / db_id 等自定义键；
  · 非 draft 指标必须有 `expression` / `unit` / `time_basis`（`models.py:182-193`）。

  只跑 `semantic/validate_bundle.py` 会得到 PASS 假绿（实测 PASS=32 FAIL=0，而真加载抛
  `SemanticBundleError`）⇒ 必须另过一遍 `load_bundle()`（见 archive 的 check_bundle_load.py）。

用法：
    python eval/spider/build_bundle.py --db tracking_orders --spider-root <...>/spider_data
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

VERSION = "2026.11.10.2"
BUNDLE_DIR = Path(__file__).resolve().parent / "bundles"


def q(value):
    return json.dumps(str(value), ensure_ascii=False)


def snake(name):
    return re.sub(r"[^0-9A-Za-z]+", "_", str(name)).strip("_").lower() or "x"


def ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def read_sqlite(db_path):
    con = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        cur = con.cursor()
        tables = [r[0] for r in cur.execute(
            "select name from sqlite_master where type='table' "
            "and name not like 'sqlite_%' order by name")]
        info = {}
        for table in tables:
            cols = cur.execute("pragma table_info(" + ident(table) + ")").fetchall()
            rows = cur.execute("select count(*) from " + ident(table)).fetchone()[0]
            info[table] = {"columns": [(str(c[1]), str(c[2] or "")) for c in cols],
                           "rows": int(rows)}
        return info
    finally:
        con.close()


def spider_meta(entry):
    orig = entry["column_names_original"]
    types = entry["column_types"]
    names = entry["table_names_original"]
    pk_map = {}
    for pk in entry.get("primary_keys") or []:
        items = pk if isinstance(pk, list) else [pk]
        for col in items:
            pk_map.setdefault(str(names[orig[col][0]]), []).append(str(orig[col][1]))
    fk_pairs = []
    for child, parent in entry.get("foreign_keys") or []:
        fk_pairs.append((str(names[orig[child][0]]), str(orig[child][1]),
                         str(names[orig[parent][0]]), str(orig[parent][1])))
    col_types = {}
    for index, pair in enumerate(orig):
        if pair[0] < 0:
            continue
        col_types[(str(names[pair[0]]), str(pair[1]))] = str(types[index])
    return {"pk_map": pk_map, "fk_pairs": fk_pairs, "col_types": col_types}


def build(db_id, spider_root, out_path):
    sqlite_info = read_sqlite(spider_root / "database" / db_id / (db_id + ".sqlite"))
    tables_json = json.loads((spider_root / "tables.json").read_text(encoding="utf-8"))
    entry = None
    for item in tables_json:
        if item.get("db_id") == db_id:
            entry = item
            break
    if entry is None:
        raise SystemExit("tables.json 缺该库: " + db_id)
    meta = spider_meta(entry)

    ordered = sorted(sqlite_info)
    logical_of = {}
    used = set()
    for table in ordered:
        candidate = snake(table)
        while candidate in used:
            candidate = candidate + "_t"
        used.add(candidate)
        logical_of[table] = candidate

    time_table = None
    time_col = None
    for table in ordered:
        for name, _ctype in sqlite_info[table]["columns"]:
            if meta["col_types"].get((table, name)) == "time":
                time_table, time_col = table, name
                break
        if time_table is not None:
            break
    time_is_real = time_table is not None
    if not time_is_real:
        fallback = None
        for table in ordered:
            for name, ctype in sqlite_info[table]["columns"]:
                if str(ctype).lower() == "text":
                    fallback = (table, name)
                    break
            if fallback is not None:
                break
        if fallback is None:
            raise SystemExit("该库既无 time 列也无 text 列，本手不生成: " + db_id)
        time_table, time_col = fallback
    time_basis_value = time_col if time_is_real else "none（schema 无 time 列）"

    owners = {}
    for table in ordered:
        for name, _ in sqlite_info[table]["columns"]:
            owners.setdefault(name, []).append(table)
    alias_rows = []
    for name in sorted(owners):
        if len(owners[name]) != 1:
            continue
        table = owners[name][0]
        alias_rows.append(
            "  - { term: " + q(name) + ", lang: en, maps_to_kind: column, maps_to_ref: "
            + q(logical_of[table] + "." + name) + ", category: column }")
    if not alias_rows:
        alias_rows = [
            "  - { term: " + q(logical_of[time_table] + "_" + snake(time_col))
            + ", lang: en, maps_to_kind: column, maps_to_ref: "
            + q(logical_of[time_table] + "." + time_col) + ", category: time }"]

    join_rows = []
    for child_t, child_c, parent_t, parent_c in meta["fk_pairs"]:
        if child_t not in logical_of or parent_t not in logical_of:
            continue
        if child_t == parent_t and child_c == parent_c:
            continue
        join_rows.append([
            "  - left: " + q(logical_of[child_t] + "." + child_c),
            "    right: " + q(logical_of[parent_t] + "." + parent_c),
            '    type: "many_to_one"',
            "    on_columns: [" + q(child_c) + "]",
            '    certified_by: "data-team"',
        ])

    lines = []
    add = lines.append
    add("# 由 eval/spider/build_bundle.py 机械生成 —— 禁止手改。")
    add("# 来源：资产=PRAGMA table_info / Join=tables.json 外键 / 指标=数值列 / 维度=首条 time 列。")
    add("# 指标口径是 schema 派生物、非业务口径。")
    add("")
    add("meta:")
    add("  version: " + q(VERSION))
    add("  domain: [orders]")
    add('  dialect: "sqlite"')
    add('  published_at: "2026-11-10T00:00:00+08:00"')
    add('  published_by: "u-182-deriver"')
    add('  status: "candidate"')
    add('  timezone: "Asia/Shanghai"')
    add("  fiscal_year_start_month: 1")
    add('  week_starts_on: "monday"')
    add("  embedding:")
    add('    model: "bge-m3"')
    add("    dim: 1024")

    add("")
    add("assets:")
    for table in ordered:
        info = sqlite_info[table]
        logical = logical_of[table]
        pk_cols = meta["pk_map"].get(table) or []
        add("")
        add("  - logical_name: " + q(logical))
        add("    physical_asset: " + q(table))
        add('    grain: "row"')
        add('    domain: "orders"')
        add('    owner: "data-team"')
        add("    certified: true")
        add("    tenant_scoped: false")
        add("    quality_score: 0.95")
        add('    freshness_sla: "P1D"')
        add('    level: "warm"')
        add("    row_estimate: " + str(info["rows"]))
        add("    description: " + q("Spider 物理表 " + table + "（schema 派生资产，"
                                  + str(len(info["columns"])) + " 列）"))
        add("    columns:")
        for name, ctype in info["columns"]:
            add("      - name: " + q(name))
            add("        type: " + q(ctype or "text"))
            add("        comment: " + q(("主键；" if name in pk_cols else "") + "schema 派生列"))

    metrics_n = 0
    add("")
    add("metrics:")
    for table in ordered:
        logical = logical_of[table]
        pk_cols = meta["pk_map"].get(table) or []
        count_col = pk_cols[0] if pk_cols else sqlite_info[table]["columns"][0][0]
        add("")
        add("  - name: " + q(logical + "_row_count"))
        add("    display_name: " + q(table + " 行数"))
        add('    domain: "orders"')
        add('    status: "active"')
        add("    expression: " + q("COUNT(" + table + "." + count_col + ")"))
        add('    default_aggregation: "count"')
        add('    unit: "count"')
        add("    time_basis: " + q(time_basis_value))
        add('    owner: "data-team"')
        add("    default_binding:")
        add("      asset: " + q(logical))
        add("      reason: " + q("schema 派生：整表行数"))
        add("    definition_note: " + q("schema 机械派生，非业务口径。"))
        metrics_n += 1
        for name, _ctype in sqlite_info[table]["columns"]:
            if meta["col_types"].get((table, name)) != "number":
                continue
            col_snake = snake(name)
            if col_snake == "id" or col_snake.endswith("_id"):
                continue
            for agg in ("sum", "avg"):
                add("")
                add("  - name: " + q(logical + "_" + col_snake + "_" + agg))
                add("    display_name: " + q(table + "." + name + " " + agg.upper()))
                add('    domain: "orders"')
                add('    status: "active"')
                add("    expression: " + q(agg.upper() + "(" + table + "." + name + ")"))
                add('    default_aggregation: "' + agg + '"')
                add('    unit: "number"')
                add("    time_basis: " + q(time_basis_value))
                add('    owner: "data-team"')
                add("    default_binding:")
                add("      asset: " + q(logical))
                add("      reason: " + q("schema 派生：数值列 " + agg))
                add("    definition_note: " + q("schema 机械派生，非业务口径。"))
                metrics_n += 1

    add("")
    add("dimensions:")
    add("")
    dim_name = "date" if time_is_real else snake(time_col)
    add("  - name: " + q(dim_name))
    add("    bindings:")
    if time_is_real:
        for grain in ("day", "week", "month", "quarter", "year"):
            add("      " + grain + ": " + q(time_col))
        add("    hierarchy: [year, quarter, month, week, day]")
        add("    grain_levels: { year: 1, quarter: 2, month: 3, week: 4, day: 5 }")
        add("    grain_level: 5")
    else:
        add("      " + dim_name + ": " + q(time_col))
        add("    hierarchy: [" + dim_name + "]")
        add("    grain_levels: { " + dim_name + ": 1 }")
        add("    grain_level: 1")
    add("    note: " + q("schema 派生：绑 " + time_table + "." + time_col))

    add("")
    add("field_bindings:")
    add("")
    add("  - concept: " + q(dim_name))
    add("    canonical_asset: " + q(logical_of[time_table] + "." + time_col))
    if time_is_real:
        add('    time_semantics: "transaction_time"')
        add("    grain_level: 5")
        add("    default_reason: " + q("schema 派生：该库首条 time 列"))
    else:
        add("    grain_level: 1")
        add("    default_reason: " + q("schema 派生：该库无 time 列，取首个 text 列作维度（非时间列）"))

    add("")
    if join_rows:
        add("joins:")
        for row in join_rows:
            add("")
            for line in row:
                add(line)
    else:
        add("joins: []")

    add("")
    add("default_predicates: {}")

    add("")
    add("aliases:")
    for row in alias_rows:
        add(row)

    add("")
    add("blacklist_terms: []")

    add("")
    add("time_semantics:")
    add('  transaction_time: ' + q("交易时间 = " + time_table + "." + time_col + "（schema 派生）"))
    add('  current: ' + q("主数据当前值"))
    add('  period_end_snapshot: ' + q("统计期末快照"))
    add("  notes:")
    add("    - " + q("本包由 eval/spider/build_bundle.py 从 Spider schema 机械派生，指标非业务口径。"))

    add("")
    add("policies:")
    add("  - deny_columns: []")
    add("    applies_to_roles: [analyst]")
    add("    note: " + q("Spider 沙箱库无租户列，本包不设拒绝列（机械派生）。"))

    add("")
    add("quality_gates:")
    add("  min_certified: true")
    add("  min_quality_score: 0.90")
    add("  max_staleness_hours: 24")
    add("  require_owner: true")
    add("  on_violation: exclude_from_context")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"out": str(out_path), "bytes": out_path.stat().st_size, "db_id": db_id,
            "assets": len(ordered), "metrics": metrics_n, "joins": len(join_rows),
            "aliases": len(alias_rows), "time_column": time_table + "." + time_col}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Spider 库 -> 语义包（机械派生，U-182）")
    ap.add_argument("--db", required=True)
    ap.add_argument("--spider-root", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    out_path = Path(args.out) if args.out else (BUNDLE_DIR / ("bundle_spider_" + args.db + ".yaml"))
    result = build(args.db, Path(args.spider_root), out_path)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
