#!/usr/bin/env python
"""B7 方言对齐探针（U-155 第 1 步，零 LLM／零出站）。

问题：生产提示词要求 PostgreSQL，评测沙箱是 SQLite ⇒ 大量 PG 正确 SQL 被
R14／`SQL_SYNTAX_ERROR` 挡住，官方 EX 被低估。

本探针**不改闸门、不重跑模型**：拿已落盘的模型 SQL，按 PG→SQLite 转译后
在沙箱执行，再用与 `runner` 相同的 `equivalence.compare_tables` 判等。
输出「可救回 / 回归 / 仍失败」三组计数，作为是否动闸门的决策依据。

⚠️ 只读：不写结果件、不写账本；`--out` 只写本探针自己的 JSON。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OLIST_DIR = Path(__file__).resolve().parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import sqlglot  # noqa: E402
from sqlglot import exp  # noqa: E402

import equivalence as eq  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402
from eval.runner import run_in_sandbox  # noqa: E402


def _parse_expr(sql: str) -> exp.Expression:
    return sqlglot.parse_one(f"SELECT {sql}", read="sqlite").expressions[0]


def _extract_sqlite(unit: str, inner: str) -> str | None:
    unit = unit.upper()
    if unit == "QUARTER":
        return f"((CAST(STRFTIME('%m', {inner}) AS INTEGER) - 1) / 3 + 1)"
    if unit == "YEAR":
        return f"CAST(STRFTIME('%Y', {inner}) AS INTEGER)"
    if unit == "MONTH":
        return f"CAST(STRFTIME('%m', {inner}) AS INTEGER)"
    return None


def _trunc_sqlite(unit: str, inner: str) -> str | None:
    unit = unit.upper()
    if unit == "MONTH":
        return f"DATE({inner}, 'start of month')"
    if unit == "YEAR":
        return f"DATE({inner}, 'start of year')"
    if unit == "QUARTER":
        return (
            f"DATE({inner}, 'start of year', '+' || "
            f"(3 * ((CAST(STRFTIME('%m', {inner}) AS INTEGER) - 1) / 3)) || ' months')"
        )
    return None


def postgres_to_sqlite(sql: str) -> str:
    """PG SQL → SQLite SQL：to_char／占位符交给 sqlglot，EXTRACT／DATE_TRUNC 补改写。"""
    tree = sqlglot.parse_one(sql, read="postgres")
    # SQLite 的 `CAST(text AS TIMESTAMP)` 会按数值亲和性把日期变成年份整数
    # （实测 `STRFTIME('%Y-%m', CAST(ts AS TIMESTAMP))` → '-4707-06'）。
    # 沙箱的时间列本来就是 TEXT，去掉这类 cast 才与金标同义。
    for node in list(tree.find_all(exp.Cast)):
        target = node.to.this.name.upper() if isinstance(node.to, exp.DataType) else ""
        if target in {"TIMESTAMP", "TIMESTAMPTZ", "DATETIME"}:
            node.replace(node.this)
    for node in list(tree.find_all(exp.Extract)):
        unit = node.this.name if node.this is not None else ""
        rewritten = _extract_sqlite(unit, node.expression.sql(dialect="postgres"))
        if rewritten is not None:
            node.replace(_parse_expr(rewritten))
    for node in [*tree.find_all(exp.TimestampTrunc), *tree.find_all(exp.DateTrunc)]:
        unit_node = node.args.get("unit")
        unit = unit_node.name if unit_node is not None else ""
        rewritten = _trunc_sqlite(unit, node.this.sql(dialect="postgres"))
        if rewritten is not None:
            node.replace(_parse_expr(rewritten))
    return tree.sql(dialect="sqlite")


def _old_cause(record: dict[str, Any]) -> str:
    if (record.get("verdict") or {}).get("equivalent"):
        return "pass"
    code = str(record.get("terminal_code") or "")
    rule = str(record.get("gate1_reject_rule") or "")
    if code == "GATE_AST_REJECTED":
        return f"gate/{rule or '?'}"
    if code == "SQL_SYNTAX_ERROR":
        return "syntax"
    if code == "LLM_UPSTREAM_ERROR":
        return "upstream"
    if record.get("terminal_event") == "complete":
        return "wrong"
    return f"other/{code or record.get('terminal_event') or '?'}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="B7 方言对齐探针（零 LLM）")
    parser.add_argument(
        "--dataset", default=str(OLIST_DIR / "dataset_v3_frozen.json")
    )
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "olist" / "olist_sandbox.db"))
    parser.add_argument(
        "--results",
        nargs="+",
        default=[str(OLIST_DIR / f"results_v3_r{i}.json") for i in (1, 2, 3)],
    )
    parser.add_argument(
        "--gold", default=str(OLIST_DIR / "gold100_frozen_results.json")
    )
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument(
        "--out", default=str(OLIST_DIR / "probe_dialect_gain.json")
    )
    args = parser.parse_args(argv)

    spec = R.load_cases(Path(args.dataset))
    gold_cases = {str(c["case_id"]): c for c in spec["cases"]}
    gold_evidence = {
        str(c["case_id"]): c
        for c in json.loads(Path(args.gold).read_text(encoding="utf-8"))["cases"]
    }
    bundle = load_bundle(str(REPO_ROOT / str(spec["bundle"])))
    tenant_scoped = {
        asset.physical_asset: "tenant_id" for asset in bundle.bundle.assets
    }

    gold_tables: dict[tuple[str, str], eq.Table] = {}

    def gold_table(case_id: str, tenant: str) -> tuple[eq.Table, str]:
        key = (case_id, tenant)
        if key not in gold_tables:
            result = run_in_sandbox(
                str(gold_cases[case_id]["gold_sql"]),
                None,
                tenant=tenant,
                views=True,
                db_path=args.db,
                tenant_scoped_physicals=tenant_scoped,
                timeout_s=args.timeout_s,
            )
            gold_tables[key] = result["table"]
        return gold_tables[key], str(gold_evidence[case_id]["result_hash"])

    batches: list[dict[str, Any]] = []
    for result_path in args.results:
        run = json.loads(Path(result_path).read_text(encoding="utf-8"))
        batch_id = str(run.get("batch_id") or Path(result_path).stem)
        old_pass = new_pass = 0
        recovered: list[str] = []
        regressions: list[str] = []
        still: Counter[str] = Counter()
        errors: Counter[str] = Counter()
        for record in run["records"]:
            if str(record.get("expected_behavior") or "execute") != "execute":
                continue
            case_id = str(record["case_id"])
            tenant = str(record.get("tenant") or "T_A")
            old_ok = bool((record.get("verdict") or {}).get("equivalent"))
            old_pass += int(old_ok)
            sql = str(record.get("sql_text") or "")
            if not sql:
                still[_old_cause(record)] += 1
                continue
            try:
                translated = postgres_to_sqlite(sql)
            except Exception as exc:  # 转译失败单独计数，不并入「仍失败」
                errors[f"translate:{type(exc).__name__}"] += 1
                still[_old_cause(record)] += 1
                continue
            pred = run_in_sandbox(
                translated,
                record.get("sql_params") or {},
                tenant=tenant,
                views=True,
                db_path=args.db,
                tenant_scoped_physicals=tenant_scoped,
                timeout_s=args.timeout_s,
            )
            if pred["error"]:
                errors[f"exec:{pred['error'].split(':', 1)[0]}"] += 1
            gtable, ghash = gold_table(case_id, tenant)
            verdict = eq.compare_tables(
                gtable,
                pred["table"],
                gold_sql=str(gold_cases[case_id]["gold_sql"]),
                pred_sql=translated,
                hash_matches=pred["hash"] == ghash if pred["hash"] else None,
            )
            if verdict.equivalent:
                new_pass += 1
                if not old_ok:
                    recovered.append(case_id)
            else:
                still[_old_cause(record)] += 1
                if old_ok:
                    regressions.append(case_id)
        batches.append(
            {
                "batch_id": batch_id,
                "old_pass": old_pass,
                "new_pass": new_pass,
                "projected_ex": round(new_pass / 95, 4),
                "recovered": recovered,
                "regressions": regressions,
                "still_fail_by_old_cause": dict(still),
                "errors": dict(errors),
            }
        )
        print(
            f"{batch_id}: old={old_pass}/95 -> new={new_pass}/95 "
            f"({new_pass / 95:.2%}); recovered={len(recovered)} regressions={len(regressions)}"
        )
        print(f"  still: {dict(still)}")
        if errors:
            print(f"  errors: {dict(errors)}")

    mean = sum(b["new_pass"] for b in batches) / (95 * len(batches))
    print(f"\nprojected mean EX = {mean:.4f} ({mean * 100:.2f}%) over {len(batches)} batch(es)")
    payload = {
        "probe": "b7_dialect_gain",
        "dataset": str(args.dataset),
        "db": str(args.db),
        "projected_mean_ex": round(mean, 6),
        "batches": batches,
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[out] {Path(args.out).relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
