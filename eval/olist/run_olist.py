#!/usr/bin/env python
"""Olist 轨的执行器：gold-only / N-13 验真 / 仪器正负控 / 模型跑批装配。

归属窗口：W1 实施窗（`U-143`）＋ W2 实施窗（`U-144`）。

四种模式（必须显式选一个）
--------------------------
· `--gold-only`：跑 gold SQL + 7 条口径对账（W1 的行为，输出默认 `gold10_results.json`）。
· `--verify-only`：N-13 源/冻结验真（`olist_profile.verify_olist_inputs`），失败 exit 3。
· `--instrument-control`：正控 gold-vs-gold（55/55）＋ 负控同列名同行数扰动值（0/55）。
· `--batch`：模型跑批装配（`runner.run_batch_sync`），判分仍走 `equivalence` + `harness`。

**不做什么**（W1 的三条边界仍然有效）：
1. **不调用** `_bootstrap.verify_frozen_inputs()`（它比的是合成冻结集与 `ecom_sandbox.db`）。
2. **不碰** `runner.main` 的默认路径与 166 题判据；只复用 `run_batch`。
3. **不改** `build_frozen_set.case_content_hash`，也**不扩展** `TENANT_SCOPED`。

租户隔离走 `open_sandbox_connection`（TEMP VIEW），与评测链路同一条路径；
`build_frozen_set.result_hash` 传 `tenant=None`，因为 `TENANT_SCOPED` 对 `v_o_*` 是空操作。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "eval"
OLIST_DIR = EVAL_DIR / "olist"
for _p in (str(REPO_ROOT), str(EVAL_DIR), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402
import equivalence as eq  # noqa: E402
import sqlglot  # noqa: E402
import yaml  # noqa: E402
from eval.grid import build_grid  # noqa: E402
from eval.olist.build_dataset import FrozenWriteError, guard_output_path, write_json  # noqa: E402
from eval.olist.hashing import case_full_hash, read_stamps  # noqa: E402
from layering import annotate_case  # noqa: E402
from sqlglot import exp  # noqa: E402
from sqlite_exec import open_sandbox_connection  # noqa: E402

SQL_DIALECT = "sqlite"
STATUS_COLUMN = "order_status"
TENANT_COLUMN = "tenant_id"


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------

def load_cases(path: str | Path) -> dict:
    """读 YAML 或 JSON。JSON 是 YAML 的子集，但分开读更快、错误更清楚。"""
    source = Path(path)
    with open(source, encoding="utf-8") as fh:
        if source.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(fh)
        return json.load(fh)


def load_annotated_cases(path: str | Path) -> dict:
    """读数据集并给每题补机器难度标签（`layering.annotate_case`，不手写级别）。"""
    spec = load_cases(path)
    for case in spec.get("cases", []):
        case.update(annotate_case(case))
    return spec


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
# gold-only / 逐题读数
# ---------------------------------------------------------------------------

def _bundle_path(spec: dict, override: str | Path | None) -> Path:
    if override is not None:
        return Path(override)
    return REPO_ROOT / str(spec["bundle"])


def _tenant_of(spec: dict, case: dict) -> str:
    return str(case.get("eval_tenant") or spec.get("tenant") or "T_A")


def run(
    dataset_path: Path,
    db_path: Path,
    tenant: str = "T_A",
    bundle_path: str | Path | None = None,
) -> dict:
    from app.semantics.loader import load_bundle

    spec = load_annotated_cases(dataset_path)
    loaded = load_bundle(str(_bundle_path(spec, bundle_path)))
    bundle = loaded.bundle
    dataset_tenant = str(spec.get("tenant") or tenant)
    tenants = {_tenant_of(spec, case) for case in spec["cases"]}
    if tenants != {dataset_tenant}:
        raise SystemExit(
            f"Olist 用例租户不一致：{sorted(tenants)} vs 数据集租户 {dataset_tenant}；"
            "本执行器只开一个租户连接，拒绝静默混用。"
        )

    con = open_connection(db_path, loaded, dataset_tenant)
    cursor = con.cursor()
    records = []
    try:
        for case in spec["cases"]:
            expected = str(case.get("expected_behavior") or "execute")
            record = {
                "case_id": case["case_id"],
                "question": case["question"],
                "expected_behavior": expected,
                "eval_tenant": _tenant_of(spec, case),
                "difficulty_struct": case.get("difficulty_struct"),
                "difficulty_semantic": case.get("difficulty_semantic"),
                "metrics": case.get("metrics", []),
                "executable": None,
                "rows": None,
                "cols": None,
                "result_hash": None,
                "sample": [],
                "checks": {},
                "caliber_match": None,
                "interaction_valid": None,
                "error": None,
            }
            if expected != "execute":
                record["interaction_valid"] = (
                    case.get("gold_sql") is None and case.get("difficulty_struct") is None
                )
                records.append(record)
                continue
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

    execute_records = [r for r in records if r["expected_behavior"] == "execute"]
    interaction_records = [r for r in records if r["expected_behavior"] != "execute"]
    n_execute = len(execute_records)
    n_interaction = len(interaction_records)
    gold_executable = sum(1 for r in execute_records if r["executable"])
    caliber_match = sum(1 for r in execute_records if r["executable"] and r["caliber_match"])
    interaction_valid = sum(1 for r in interaction_records if r["interaction_valid"])
    cases_valid = sum(
        1 for r in execute_records if r["executable"] and r["caliber_match"]
    ) + interaction_valid

    source = Path(dataset_path)
    if source.suffix.lower() in {".yaml", ".yml"}:
        stamps = read_stamps(source)
        content_stamp = stamps.get("content_hash")
        full_stamp = stamps.get("full_hash")
        mode = "stamped"
    else:
        content_stamp = spec.get("content_hash")
        full_stamp = spec.get("full_hash")
        mode = "frozen"

    return {
        "mode": "gold-only",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": source.name,
        "dataset_version": spec.get("dataset_version") or spec.get("dataset"),
        "dataset_hash_mode": mode,
        "bundle": {"path": str(spec.get("bundle") or _bundle_path(spec, bundle_path)),
                   "version": bundle.meta.version},
        "db": str(db_path),
        "tenant": dataset_tenant,
        "content_hash": bfs.case_content_hash(spec["cases"]),
        "content_hash_stamp": content_stamp,
        "full_hash": case_full_hash(spec["cases"]),
        "full_hash_stamp": full_stamp,
        "sandbox_db_sha256": bfs.file_sha256(str(db_path)),
        "n_cases": len(records),
        "n_execute_cases": n_execute,
        "n_interaction_cases": n_interaction,
        "gold_executable": gold_executable,
        "caliber_match": caliber_match,
        "interaction_valid": interaction_valid,
        "cases_valid": cases_valid,
        "cases": records,
    }


# ---------------------------------------------------------------------------
# 仪器正/负控
# ---------------------------------------------------------------------------

def _perturb_value(value):
    """负控扰动：数值按量级改 0.1%（下限 1），文本/空值改类型。

    ⚠️ **不能只 +1**：`equivalence.REL_TOL=1e-6` 是相对容差，8.59M 的 GMV +1
    只有 1.16e-7 相对差 ⇒ 会被判等，负控漏过。W1 10 条冒烟实测负控 1/10，
    就是 g01 这一例。按量级取 0.1% 才能保证相对差 ≫ 1e-6 且对 0 也有扰动。
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        delta = max(1.0, abs(float(value)) * 1e-3)
        perturbed = float(value) + delta
        return round(perturbed) if isinstance(value, int) else perturbed
    if isinstance(value, str):
        return "x" + value
    if isinstance(value, bytes):
        return b"x" + value
    if value is None:
        return "perturbed"
    return f"x{value}"


def perturb_table(table: eq.Table) -> eq.Table:
    """负控的 pred：**同列名、同行数**，只扰动值（证明走的是值比较，不是列数早退）。"""
    return eq.Table(
        columns=table.columns,
        rows=tuple(tuple(_perturb_value(v) for v in row) for row in table.rows),
    )


def instrument_control(
    dataset_path: Path,
    db_path: Path,
    tenant: str = "T_A",
    bundle_path: str | Path | None = None,
) -> dict:
    from app.semantics.loader import load_bundle

    spec = load_annotated_cases(dataset_path)
    loaded = load_bundle(str(_bundle_path(spec, bundle_path)))
    dataset_tenant = str(spec.get("tenant") or tenant)
    con = open_connection(db_path, loaded, dataset_tenant)
    cases = spec["cases"]
    execute_cases = [c for c in cases if str(c.get("expected_behavior") or "execute") == "execute"]
    rows: list[dict] = []
    cursor = con.cursor()
    try:
        for case in execute_cases:
            sql = case["gold_sql"]
            entry = {
                "case_id": case["case_id"],
                "gold_rows": None,
                "gold_cols": None,
                "pred_shape": None,
                "positive_equivalent": None,
                "negative_equivalent": None,
                "error": None,
            }
            try:
                cursor.execute(sql)
                gold = eq.Table.from_cursor(cursor)
                positive = eq.compare_tables(gold, gold, gold_sql=sql, pred_sql=sql)
                perturbed = perturb_table(gold)
                negative = eq.compare_tables(gold, perturbed, gold_sql=sql, pred_sql=sql)
                entry.update(
                    gold_rows=len(gold.rows),
                    gold_cols=len(gold.columns),
                    pred_shape={"columns": len(perturbed.columns), "rows": len(perturbed.rows)},
                    positive_equivalent=bool(positive.equivalent),
                    negative_equivalent=bool(negative.equivalent),
                )
                if not gold.rows:
                    entry["error"] = "gold_empty"
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(entry)
    finally:
        con.close()

    n_execute = len(execute_cases)
    by_id = {entry["case_id"]: entry for entry in rows}

    def _map(passed_key: str) -> dict[str, dict]:
        mapping: dict[str, dict] = {}
        for case in cases:
            case_id = str(case["case_id"])
            expected = str(case.get("expected_behavior") or "execute")
            if expected != "execute":
                mapping[case_id] = {"scored": True, "passed": False, "category": "unattributed"}
                continue
            entry = by_id.get(case_id) or {}
            mapping[case_id] = {
                "scored": entry.get("error") is None,
                "passed": bool(entry.get(passed_key)),
                "category": "unattributed",
            }
        return mapping

    grid_pos = build_grid(cases, _map("positive_equivalent"))
    grid_neg = build_grid(cases, _map("negative_equivalent"))
    pos_ok = grid_pos.scored_total == n_execute and grid_pos.scored_passed == n_execute
    neg_ok = grid_neg.scored_total == n_execute and grid_neg.scored_passed == 0
    all_ok = pos_ok and neg_ok and all(entry["error"] is None for entry in rows)

    def _grid_row(grid) -> dict:
        return {
            "scored_total": grid.scored_total,
            "scored_passed": grid.scored_passed,
            "ex": grid.ex,
            "matrix": grid.matrix(),
        }

    return {
        "mode": "instrument-control",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "not_ex_official": True,
        "dataset": Path(dataset_path).name,
        "db": str(db_path),
        "n_cases": len(cases),
        "n_execute_cases": n_execute,
        "positive": _grid_row(grid_pos),
        "negative": _grid_row(grid_neg),
        "all_ok": all_ok,
        "cases": rows,
    }


# ---------------------------------------------------------------------------
# 模型跑批装配（Step 6；本轮只做 dry-run 与 replay，不跑 live）
# ---------------------------------------------------------------------------

def _require_olist_path(raw: str | Path) -> Path:
    return guard_output_path(raw)


def batch_mode(args: argparse.Namespace, dataset_path: Path, db_path: Path, out: Path) -> int:
    """`--batch`：先 N-13 验真，再打印计划；无 `--yes` 不构造 Harness、不写盘。"""
    from eval import runner
    from eval.olist.olist_profile import OlistVerificationError, verify_olist_inputs

    if args.live:
        missing = [
            flag for flag, value in (
                ("--batch-id", args.batch_id),
                ("--max-cost-cny", args.max_cost_cny),
                ("--max-calls", args.max_calls),
            ) if value in (None, "")
        ]
        if missing:
            print(f"--live 必须同时给：{', '.join(missing)}", file=sys.stderr)
            return 2

    cassette = Path(args.cassette) if args.cassette else (
        OLIST_DIR / "cassettes" / f"olist_v1_{args.batch_id or args.mode}.jsonl"
    )
    try:
        cassette = _require_olist_path(cassette)
        ledger = _require_olist_path(args.budget_ledger) if args.budget_ledger else None
        out = _require_olist_path(out)
    except FrozenWriteError as exc:
        print(f"拒绝写入：{exc}", file=sys.stderr)
        return 2

    spec = load_annotated_cases(dataset_path)
    bundle_path = Path(args.bundle) if args.bundle else REPO_ROOT / str(spec["bundle"])
    if not bundle_path.is_file():
        print(f"语义包不存在：{bundle_path}", file=sys.stderr)
        return 2
    try:
        evidence = verify_olist_inputs(
            dataset_path, db_path, bundle_path=str(bundle_path), tenant=args.tenant
        )
    except OlistVerificationError as exc:
        print(f"Olist N-13 验真失败：{exc}", file=sys.stderr)
        return 3

    ids = [part.strip() for part in (args.cases or "").split(",") if part.strip()]
    cases = runner.load_cases(spec, ids=ids or None, limit=args.limit)
    node_timeouts = runner.eval_node_timeouts() if args.live else None
    mode = "record" if args.live else args.mode
    print(runner._plan(
        cases, live=args.live, cassette=str(cassette), mode=mode, node_timeouts=node_timeouts
    ))
    print(f"  执行器 DB     : {db_path}（与判分 DB 同一个）")
    print(f"  执行器 bundle : {bundle_path}")
    print(f"  数据集        : {dataset_path}  content_hash={evidence['content_hash']}")
    if args.live:
        print(
            f"  预算          : ≤¥{args.max_cost_cny} / ≤{args.max_calls} calls"
            + (f" / ≤{args.max_tokens} tokens" if args.max_tokens else "")
            + (f"；账本 {ledger}" if ledger else "；无账本（单批独立）")
        )

    if not args.yes:
        print("\n未带 --yes：只打印计划，不构造 Harness、不写盘。")
        return 0

    if not args.live and not cassette.is_file():
        print(f"回放匣带不存在：{cassette}（replay 无法开跑）", file=sys.stderr)
        return 4
    if args.live:
        cassette.parent.mkdir(parents=True, exist_ok=True)

    ledger_payload, prior_usage = runner.load_budget_ledger(
        str(ledger) if ledger else None
    )

    batch = runner.run_batch_sync(
        cases,
        live=args.live,
        cassette=str(cassette),
        mode=mode,
        db_path=str(db_path),
        bundle_path=str(bundle_path),
        column_top=args.column_top,
        node_timeout_overrides=node_timeouts,
        max_concurrency=args.max_concurrency,
        batch_id=args.batch_id,
        max_cost_cny=args.max_cost_cny,
        max_calls=args.max_calls,
        max_tokens=args.max_tokens,
        prior_usage=prior_usage,
    )
    if ledger:
        ledger_payload = runner.save_budget_ledger(
            str(ledger),
            payload=ledger_payload,
            totals=batch["usage"]["totals"],
            run=runner.ledger_run_entry(
                batch, batch_id=args.batch_id, live=args.live, mode=mode
            ),
            stamp=_bootstrap.build_stamp(),
        )
    payload = {
        "batch_id": args.batch_id,
        "frozen_evidence": evidence,
        "config": {
            "live": args.live,
            "mode": mode,
            "cassette": str(cassette),
            "dataset": str(dataset_path),
            "dataset_content_hash": evidence["content_hash"],
            "dataset_full_hash": evidence["full_hash"],
            "executor": batch["executor"],
            "scorer_db": str(db_path),
            "n_cases": len(cases),
            "filters": {"ids": ids, "limit": args.limit},
            "provenance": args.provenance,
            "budget": {
                "max_cost_cny": args.max_cost_cny,
                "max_calls": args.max_calls,
                "max_tokens": args.max_tokens,
                "ledger": str(ledger) if ledger else None,
            },
        },
        "summary": runner.summarize(batch["records"]),
        "usage": batch["usage"],
        "budget_stop": batch["budget_stop"],
        "records": batch["records"],
        "build": _bootstrap.build_stamp(),
    }
    out_path = write_json(out, payload)
    print(f"[out] {out_path.relative_to(REPO_ROOT).as_posix()}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_dataset(gold_only: bool) -> Path:
    return OLIST_DIR / ("dataset_w1_gold10.yaml" if gold_only else "dataset_v1.yaml")


def _default_out(mode: str) -> Path:
    return {
        "gold-only": OLIST_DIR / "gold10_results.json",
        "verify-only": OLIST_DIR / "olist_profile.json",
        "instrument-control": OLIST_DIR / "instrument_control.json",
        "batch": OLIST_DIR / "results_v1.json",
    }[mode]


def _print_gold_summary(report: dict, out_path: Path) -> None:
    print(f"{'case':<8}{'可执行':<8}{'caliber':<9}{'行':>6}{'列':>5}   失败判据")
    print("-" * 78)
    for record in report["cases"]:
        expected = record.get("expected_behavior") or "execute"
        if expected != "execute":
            flag = "n/a" if record.get("interaction_valid") else "✗"
            print(f"{record['case_id']:<8}{'N/A':<8}{flag:<9}{'-':>6}{'-':>5}   "
                  f"interaction={expected}")
            continue
        failed = [k for k, ok in record["checks"].items() if not ok]
        flag = "✓" if record["caliber_match"] else "✗"
        rows = "-" if record["rows"] is None else record["rows"]
        cols = "-" if record["cols"] is None else record["cols"]
        print(f"{record['case_id']:<8}{record['executable']!s:<8}{flag:<9}{rows:>6}{cols:>5}   "
              f"{','.join(failed) or ('EXEC_ERROR: ' + record['error'] if record['error'] else '')}")
    print("-" * 78)
    print(f"n_cases           = {report['n_cases']}")
    print(f"n_execute_cases   = {report['n_execute_cases']}")
    print(f"gold_executable   = {report['gold_executable']}/{report['n_execute_cases']}")
    print(f"caliber_match     = {report['caliber_match']}/{report['n_execute_cases']}")
    print(f"interaction_valid = {report['interaction_valid']}/{report['n_interaction_cases']}")
    print(f"cases_valid       = {report['cases_valid']}/{report['n_cases']}")
    print(f"content_hash      = {report['content_hash']}")
    print(f"full_hash         = {report['full_hash']}")
    print(f"sandbox_db_sha256 = {report['sandbox_db_sha256']}")
    if "verification" in report:
        print(f"N-13 all_ok       = {report['verification']['checks']['all_ok']}")
    print(f"[out] {out_path.relative_to(REPO_ROOT).as_posix()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist 60 题执行器（gold/验真/仪器控制/跑批）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gold-only", action="store_true", help="跑 gold SQL + 7 条口径判据")
    mode.add_argument("--verify-only", action="store_true", help="N-13 验真（失败 exit 3）")
    mode.add_argument("--instrument-control", action="store_true", help="正控 + 负控")
    mode.add_argument("--batch", action="store_true", help="模型跑批装配（dry-run/replay；live 需账本前置门）")
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "olist" / "olist_sandbox.db"))
    parser.add_argument("--tenant", default="T_A")
    parser.add_argument("--bundle", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cases", default=None, help="逗号分隔的 case_id（保持文件原序）")
    parser.add_argument("--live", action="store_true", help="真打上游（本窗未批准）")
    parser.add_argument("--yes", action="store_true", help="确认执行；不带只打印计划")
    parser.add_argument("--mode", default="replay", choices=["replay", "record"])
    parser.add_argument("--cassette", default=None)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--max-cost-cny", type=float, default=None)
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--budget-ledger", default=None)
    parser.add_argument("--column-top", type=int, default=None)
    parser.add_argument("--max-concurrency", type=int, default=None)
    parser.add_argument("--provenance", default=None)
    args = parser.parse_args(argv)

    selected = (
        "gold-only" if args.gold_only else
        "verify-only" if args.verify_only else
        "instrument-control" if args.instrument_control else
        "batch"
    )
    dataset_path = Path(args.dataset) if args.dataset else _default_dataset(args.gold_only)
    db_path = Path(args.db)
    out = Path(args.out) if args.out else _default_out(selected)

    if not dataset_path.is_file():
        raise SystemExit(f"数据集不存在：{dataset_path}")
    if not db_path.is_file():
        raise SystemExit(f"沙箱库不存在：{db_path}\n先跑 deploy/demo/build_olist_sandbox.py")

    try:
        if selected == "gold-only":
            report = run(dataset_path, db_path, tenant=args.tenant, bundle_path=args.bundle)
            ok = (
                report["n_execute_cases"] == report["gold_executable"] == report["caliber_match"]
                and report["n_interaction_cases"] == report["interaction_valid"]
            )
            if report["n_cases"] == 60:
                from eval.olist.olist_profile import verify_from_report

                report["verification"] = verify_from_report(report, dataset_path, load_cases(dataset_path))
                ok = ok and bool(report["verification"]["checks"]["all_ok"])
            out_path = write_json(out, report, indent=2)
            _print_gold_summary(report, out_path)
            return 0 if ok else 1

        if selected == "verify-only":
            from eval.olist.olist_profile import OlistVerificationError, verify_olist_inputs

            try:
                evidence = verify_olist_inputs(
                    dataset_path, db_path, bundle_path=args.bundle, tenant=args.tenant
                )
            except OlistVerificationError as exc:
                print(f"Olist N-13 验真失败：{exc}", file=sys.stderr)
                return 3
            out_path = write_json(out, evidence, indent=2)
            print(json.dumps(evidence["checks"], ensure_ascii=False, indent=2))
            print(f"N-13 all_ok = {evidence['checks']['all_ok']}")
            print(f"[out] {out_path.relative_to(REPO_ROOT).as_posix()}")
            return 0 if evidence["checks"]["all_ok"] else 3

        if selected == "instrument-control":
            control = instrument_control(
                dataset_path, db_path, tenant=args.tenant, bundle_path=args.bundle
            )
            out_path = write_json(out, control, indent=2)
            pos, neg = control["positive"], control["negative"]
            print(f"positive (gold vs gold) : {pos['scored_passed']}/{pos['scored_total']} "
                  f"ex={pos['ex']}")
            print(f"negative (perturbed)    : {neg['scored_passed']}/{neg['scored_total']} "
                  f"ex={neg['ex']}")
            print(f"all_ok                  : {control['all_ok']}  (not_ex_official=True)")
            print(f"[out] {out_path.relative_to(REPO_ROOT).as_posix()}")
            return 0 if control["all_ok"] else 1

        if selected == "batch":
            return batch_mode(args, dataset_path, db_path, out)

        raise SystemExit(f"未知模式：{selected}")
    except FrozenWriteError as exc:
        print(f"拒绝写入：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
