#!/usr/bin/env python
"""方言候选形态的**可执行性取证**（T-22 判据 ② 之㈠ 的设计依赖；离线、只读沙箱、零成本）。

为什么需要（现读取证）：
  · `eval/sqlite_dialect.py` 的既有白名单只收 5 种 `TO_CHAR` 格式；
  · 预测侧 SQL 里 `::timestamp` 78 次、`DATE_TRUNC` 28 次、`EXTRACT` 20 次；
  · 金标侧 `eval/olist/dataset_v3_frozen.json` 的 100 条 `gold_sql` 里这三类**各 0 次**
    ⇒ 扩白名单只影响预测侧。

本件把「候选翻译形态」逐条**在沙箱上真跑**，给「能不能跑、跑出什么」，
而不是在文档里猜等价。另单列一条**陷阱**：`CAST('2018-03-05 10:11:12' AS TIMESTAMP)`
在 SQLite 按 NUMERIC 亲和性处理 ⇒ `x::timestamp` 只能**剥掉**、不能转成 CAST。

本件**不改**翻译器行为、不改白名单、不改判据；只产出新件 `probe_dialect_forms.json`。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OLIST_DIR = Path(__file__).resolve().parent
DEFAULT_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
DEFAULT_OUT = OLIST_DIR / "probe_dialect_forms.json"
TRAP_SQL = "SELECT CAST('2018-03-05 10:11:12' AS TIMESTAMP) AS v"
COL = "o.order_purchase_timestamp"

#: 每条：`name` / `verdict`（adopt = 拟进白名单、reject = 拒收）/ `expr`（None 表示不跑）/ `note`
FORMS: tuple[dict[str, Any], ...] = (
    {
        "name": "date_trunc_month",
        "verdict": "adopt",
        "expr": f"strftime('%Y-%m-01', {COL})",
        "note": "DATE_TRUNC('month', x) 的候选等价形态（PG 返回月初零点）",
    },
    {
        "name": "date_trunc_year",
        "verdict": "adopt",
        "expr": f"strftime('%Y-01-01', {COL})",
        "note": "DATE_TRUNC('year', x) 的候选等价形态",
    },
    {
        "name": "date_trunc_day",
        "verdict": "adopt",
        "expr": f"strftime('%Y-%m-%d', {COL})",
        "note": "DATE_TRUNC('day', x) 的候选等价形态",
    },
    {
        "name": "date_trunc_quarter_untouched",
        "verdict": "reject",
        "expr": f"DATE_TRUNC('quarter', {COL})",
        "note": "PG 季度截断要落到季度首日，SQLite 无等价原语 ⇒ 不翻、原样保留并继续告警",
    },
    {
        "name": "extract_year",
        "verdict": "adopt",
        "expr": f"CAST(strftime('%Y', {COL}) AS INTEGER)",
        "note": "EXTRACT(YEAR FROM x) 的候选等价形态",
    },
    {
        "name": "extract_month",
        "verdict": "adopt",
        "expr": f"CAST(strftime('%m', {COL}) AS INTEGER)",
        "note": "EXTRACT(MONTH FROM x) 的候选等价形态",
    },
    {
        "name": "extract_day",
        "verdict": "adopt",
        "expr": f"CAST(strftime('%d', {COL}) AS INTEGER)",
        "note": "EXTRACT(DAY FROM x) 的候选等价形态",
    },
    {
        "name": "extract_quarter",
        "verdict": "adopt",
        "expr": f"((CAST(strftime('%m', {COL}) AS INTEGER) + 2) / 3)",
        "note": "EXTRACT(QUARTER FROM x) 的候选等价形态（整数除法）",
    },
    {
        "name": "cast_timestamp_via_cast",
        "verdict": "reject",
        "expr": f"CAST({COL} AS TIMESTAMP)",
        "note": "⚠️ 陷阱：SQLite 的 TIMESTAMP 走 NUMERIC 亲和性，会把时间串截成数字",
    },
    {
        "name": "strip_timestamp_cast",
        "verdict": "adopt",
        "expr": COL,
        "note": "x::timestamp 的候选等价形态（PG 侧是恒等 ⇒ 只剥掉运算符，不转 CAST）",
    },
)

#: 明确拒收、但不需要在沙箱上跑的形态（理由写在这里，避免后人再试一遍）。
REJECT_NOTES: tuple[dict[str, str], ...] = (
    {
        "name": "cast_numeric_kept",
        "note": "x::numeric 改舍入语义（PG numeric 精确十进制 / SQLite REAL）⇒ 拒收，原样保留",
    },
    {
        "name": "cast_date_kept",
        "note": "x::date 会截掉时分 ⇒ 改结果粒度 ⇒ 拒收，原样保留",
    },
    {
        "name": "cast_text_kept",
        "note": "x::text 会改比较语义（数值列被当字符串比）⇒ 拒收，原样保留",
    },
)


def _run_expr(con: sqlite3.Connection, expr: str) -> dict[str, Any]:
    sql = f"SELECT {expr} AS v FROM v_o_orders AS o WHERE {COL} IS NOT NULL LIMIT 3"
    cur = con.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        return {
            "sql": sql,
            "error": None,
            "samples": [str(r[0]) for r in rows],
        }
    except sqlite3.Error as exc:
        return {"sql": sql, "error": f"{type(exc).__name__}: {str(exc)[:180]}", "samples": []}
    finally:
        cur.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="方言候选形态可执行性取证（离线、只读沙箱）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if not args.db.is_file():
        print(f"ABORT: 沙箱库不存在 {args.db}")
        return 2

    con = sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = None
    records: list[dict[str, Any]] = []
    try:
        for form in FORMS:
            expr = form.get("expr")
            item: dict[str, Any] = {
                "name": form["name"],
                "verdict": form["verdict"],
                "note": form["note"],
                "expr": expr,
                "ran": expr is not None,
            }
            if expr is not None:
                item.update(_run_expr(con, str(expr)))
            records.append(item)
            status = "error" if item.get("error") else "ok"
            print(f"  {form['name']:<28} verdict={form['verdict']:<7} {status:<5} samples={item.get('samples')}")

        trap = _run_expr(con, "CAST('2018-03-05 10:11:12' AS TIMESTAMP)")
        trap["sql"] = TRAP_SQL
        print(f"  {'cast_timestamp_trap':<28} samples={trap.get('samples')}")
    finally:
        con.close()

    payload = {
        "schema": "T22_DIALECT_FORMS_PROBE/v1",
        "note": (
            "只跑候选形态、不改翻译器行为、不改白名单、不改判据；"
            "沙箱以 mode=ro 打开，源库零改动"
        ),
        "db": str(args.db.relative_to(REPO_ROOT)) if args.db.is_relative_to(REPO_ROOT) else str(args.db),
        "column": COL,
        "forms": records,
        "cast_timestamp_trap": trap,
        "rejected_without_running": list(REJECT_NOTES),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
