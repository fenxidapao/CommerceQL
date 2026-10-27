#!/usr/bin/env python
"""W1 的 gold-only 执行器：跑 gold SQL + 7 条口径对账。

归属窗口：W1 实施窗（`docs/07 §4.8` 的 `U-143`）。

**不做什么**（三条边界，都是 W1 的硬约束）：
1. **不调用** `_bootstrap.verify_frozen_inputs()` —— 它拿 `dataset["sandbox_db_sha256"]`
   比 `data/ecom_sandbox.db`，Olist 永远过不了。Olist 的验真 profile 是 W2 的 `olist_profile.py`。
2. **不碰** `eval/runner.py` 的默认路径与 166 题判据。
3. **不算 EX** —— gold-only 没有模型输出，等价判定无从谈起。

租户隔离走 `open_sandbox_connection`（TEMP VIEW），与评测链路同一条路径；
`build_frozen_set.result_hash` 传 `tenant=None`，因为它的 `TENANT_SCOPED` 是写死的
合成 6 表，对 `v_o_*` 是空操作 —— **不得**扩展那份常量（会动冻结口径）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "eval"
for _p in (str(REPO_ROOT), str(EVAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402
import sqlglot  # noqa: E402
import yaml  # noqa: E402
from sqlglot import exp  # noqa: E402
from sqlite_exec import open_sandbox_connection  # noqa: E402

from eval.olist.build_dataset import write_json  # noqa: E402

SQL_DIALECT = "sqlite"
STATUS_COLUMN = "order_status"
TENANT_COLUMN = "tenant_id"


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------

def load_cases(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def open_connection(db: Path, loaded, tenant: str):
    """与 `eval/harness.py:742-746` 同一条推导：租户作用面取自 bundle，不硬编码第二份。"""
    physicals = {
        a.physical_asset: TENANT_COLUMN
        for a in loaded.bundle.assets
        if a.tenant_scoped and a.logical_name in loaded.active_assets
    }
    return open_sandbox_connection(str(db), tenant_id=tenant, tenant_scoped_physicals=physicals)


# ---------------------------------------------------------------------------
# 解析辅助
# ---------------------------------------------------------------------------

def parse_sql(sql: str) -> exp.Expression:
    return sqlglot.parse_one(sql, dialect=SQL_DIALECT)


def expression_as_sql(expression: str) -> exp.Expression:
    """指标 `expression` 是 `<agg> WHERE <pred>` 形态（本仓既有约定），补 FROM 后解析。"""
    head, sep, tail = expression.partition(" WHERE ")
    sql = f"SELECT {head} FROM t WHERE {tail}" if sep else f"SELECT {expression} FROM t"
    return parse_sql(sql)


def table_alias_map(tree: exp.Expression) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        mapping[table.alias_or_name] = table.name
        mapping[table.name] = table.name
    return mapping


def output_aliases(tree: exp.Expression) -> set[str]:
    return {node.alias for node in tree.find_all(exp.Alias) if node.alias}


def columns_in(tree: exp.Expression) -> list[exp.Column]:
    return list(tree.find_all(exp.Column))


def status_predicate(tree: exp.Expression) -> tuple[str, set[str]]:
    """从谓词里取 `(mode, values)`；mode ∈ {exclude, require, none}。"""
    mode, values = "none", set()
    for node in tree.walk():
        if isinstance(node, exp.In) and isinstance(node.this, exp.Column):
            if node.this.name != STATUS_COLUMN:
                continue
            mode = "exclude" if isinstance(node.parent, exp.Not) else "require"
            values |= {lit.this for lit in node.expressions if isinstance(lit, exp.Literal)}
        elif isinstance(node, (exp.EQ, exp.NEQ)) and isinstance(node.this, exp.Column):
            if node.this.name != STATUS_COLUMN or not isinstance(node.expression, exp.Literal):
                continue
            if isinstance(node, exp.EQ):
                if mode == "none":
                    mode = "require"
            else:
                mode = "exclude"
            values.add(node.expression.this)
    return mode, values


def aggregated_columns(tree: exp.Expression) -> set[str]:
    names: set[str] = set()
    for node in tree.walk():
        if isinstance(node, (exp.Sum, exp.Avg, exp.Min, exp.Max)):
            names |= {c.name for c in node.find_all(exp.Column)}
    return names


def _jsonable(value):
    return float(value) if isinstance(value, float) else value


# ---------------------------------------------------------------------------
# 7 条口径判据
# ---------------------------------------------------------------------------

def check_case(case: dict, tree: exp.Expression, bundle) -> dict[str, bool]:
    assets = {a.logical_name: a for a in bundle.assets}
    metrics = {m.name: m for m in bundle.metrics}
    expect = case.get("expect") or {}

    declared_assets = list(case["assets"])
    declared_physical = {assets[name].physical_asset for name in declared_assets if name in assets}
    declared_columns = {c for name in declared_assets if name in assets for c in assets[name].column_names}

    alias_map = table_alias_map(tree)
    out_aliases = output_aliases(tree)
    cols = columns_in(tree)

    # C1 资产白名单
    used_tables = {t.name for t in tree.find_all(exp.Table)}
    c1 = used_tables <= declared_physical and declared_physical <= {
        a.physical_asset for a in bundle.assets
    }

    # C2 列白名单（输出别名不是列）
    c2 = True
    for col in cols:
        if not col.table and col.name in out_aliases:
            continue
        if col.table:
            physical = alias_map.get(col.table)
            logical = next(
                (n for n in declared_assets if n in assets and assets[n].physical_asset == physical),
                None,
            )
            if logical is None or col.name not in assets[logical].column_names:
                c2 = False
                break
        elif col.name not in declared_columns:
            c2 = False
            break

    # C3 时间基准
    primary = metrics.get(case["metrics"][0]) if case.get("metrics") else None
    time_basis = primary.time_basis if primary else None
    c3 = time_basis is not None and expect.get("time_column") == time_basis
    if c3 and expect.get("time_filtered"):
        where = tree.find(exp.Where)
        where_cols = {c.name for c in where.find_all(exp.Column)} if where is not None else set()
        c3 = time_basis in where_cols

    # C4 金额列（必须真的被聚合，而不只是出现在 SQL 里）
    amount = expect.get("amount_column")
    if amount:
        c4 = (
            primary is not None
            and amount in aggregated_columns(tree)
            and amount in (primary.expression or "")
        )
    else:
        c4 = True

    # C5 状态谓词一致性（gold vs 指标表达式）
    gold_mode, gold_values = status_predicate(tree)
    metric_mode, metric_values = (
        status_predicate(expression_as_sql(primary.expression or "")) if primary else ("none", set())
    )
    c5 = (
        gold_mode == expect.get("status_mode") == metric_mode
        and gold_values == set(expect.get("status_values") or [])
        and metric_values == gold_values
    )

    # C6 租户列不得出现
    c6 = STATUS_COLUMN != TENANT_COLUMN and all(c.name != TENANT_COLUMN for c in cols)

    # C7 指标存在且 active
    c7 = bool(case.get("metrics")) and all(
        name in metrics and metrics[name].status == "active" for name in case["metrics"]
    )

    return {"C1_assets": c1, "C2_columns": c2, "C3_time_basis": c3,
            "C4_amount": c4, "C5_status": c5, "C6_tenant": c6, "C7_metric": c7}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run(dataset_path: Path, db_path: Path, tenant: str) -> dict:
    from app.semantics.loader import load_bundle

    spec = load_cases(dataset_path)
    bundle_path = REPO_ROOT / spec["bundle"]
    loaded = load_bundle(str(bundle_path))
    bundle = loaded.bundle

    con = open_connection(db_path, loaded, spec.get("tenant", tenant))
    cursor = con.cursor()
    records = []
    try:
        for case in spec["cases"]:
            record = {"case_id": case["case_id"], "question": case["question"],
                      "metrics": case.get("metrics", []), "executable": False,
                      "rows": None, "cols": None, "result_hash": None, "sample": [],
                      "checks": {}, "caliber_match": False, "error": None}
            try:
                tree = parse_sql(case["gold_sql"])
                record["checks"] = check_case(case, tree, bundle)
                digest, rows, cols = bfs.result_hash(cursor, case["gold_sql"], None)
                record.update(executable=True, result_hash=digest, rows=rows, cols=cols)
                cursor.execute(case["gold_sql"])
                header = [d[0] for d in (cursor.description or [])]
                record["sample"] = {"columns": header,
                                    "rows": [[_jsonable(v) for v in row]
                                             for row in cursor.fetchmany(3)]}
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            record["caliber_match"] = bool(record["checks"]) and all(record["checks"].values())
            records.append(record)
    finally:
        con.close()

    n = len(records)
    return {
        "mode": "gold-only",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": dataset_path.name,
        "bundle": {"path": spec["bundle"], "version": bundle.meta.version},
        "db": str(db_path),
        "tenant": spec.get("tenant", tenant),
        "n_cases": n,
        "gold_executable": sum(1 for r in records if r["executable"]),
        "caliber_match": sum(1 for r in records if r["caliber_match"]),
        "cases": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist gold-only 执行 + 口径对账")
    parser.add_argument("--gold-only", action="store_true", help="只跑 gold SQL（W1 唯一模式）")
    parser.add_argument("--dataset", default=str(EVAL_DIR / "olist" / "dataset_w1_gold10.yaml"))
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "olist" / "olist_sandbox.db"))
    parser.add_argument("--tenant", default="T_A")
    parser.add_argument("--out", default=str(EVAL_DIR / "olist" / "gold10_results.json"))
    args = parser.parse_args(argv)

    if not args.gold_only:
        raise SystemExit("W1 只有 --gold-only 一种模式（模型跑批属 W2，需预算批准）")

    db_path = Path(args.db)
    if not db_path.is_file():
        raise SystemExit(f"沙箱库不存在：{db_path}\n先跑 deploy/demo/build_olist_sandbox.py")

    report = run(Path(args.dataset), db_path, args.tenant)
    out = write_json(args.out, report, indent=2)

    print(f"{'case':<6}{'可执行':<8}{'caliber':<9}{'行':>6}{'列':>5}   失败判据")
    print("-" * 72)
    for record in report["cases"]:
        failed = [k for k, ok in record["checks"].items() if not ok]
        flag = "✓" if record["caliber_match"] else "✗"
        rows = "-" if record["rows"] is None else record["rows"]
        cols = "-" if record["cols"] is None else record["cols"]
        print(f"{record['case_id']:<6}{record['executable']!s:<8}{flag:<9}{rows:>6}{cols:>5}   "
              f"{','.join(failed) or ('EXEC_ERROR: ' + record['error'] if record['error'] else '')}")
    print("-" * 72)
    print(f"gold_executable = {report['gold_executable']}/{report['n_cases']}")
    print(f"caliber_match   = {report['caliber_match']}/{report['n_cases']}")
    print(f"[out] {out.relative_to(REPO_ROOT).as_posix()}")

    ok = report["gold_executable"] == report["n_cases"] == report["caliber_match"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
