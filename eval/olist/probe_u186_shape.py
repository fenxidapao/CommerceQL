#!/usr/bin/env python
"""U-186 形态探针：5 条稳定失败题（4 季度 + 1 CTE）的候选 SQL 写法过真闸 + 真沙箱判分。

零 LLM / 零出站 / 零花费：只用已落盘结果件里的 SQL 与参数，构造候选写法，
过**真实** `run_gate1`（含当前 allowlist 与 R14 口径），再走与 `runner` 相同的
`run_in_sandbox`（内含 `normalize_time_params` + `to_sqlite_sql` 方言桥）与
`equivalence.compare_tables` 判分。

目的：判定「是否存在既过闸又判等价的写法」，为 U-186 杠杆选型提供依据。
  · Q-A：去掉 `::timestamp`，季度用 `EXTRACT(quarter FROM ...)` 拼接
  · Q-B：Q-A 再把季度 CAST 成 text
  · Q-D：单列 `to_char(ts, 'YYYY"-Q"Q')`（检验桥接能否执行）
  · O-A：HAVING 标量子查询替代 CTE（gold 形态的 PG 版）
  · O-B：派生表 CROSS JOIN 替代 CTE
  · base：live 落盘写法（对照，预期 gate 拒）

复算：``python eval/olist/probe_u186_shape.py``
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
for _p in (str(REPO), str(REPO / "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()
logging.disable(logging.WARNING)

import equivalence as eq  # noqa: E402
from app.guard.ast_gate import run_gate1  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from eval.harness import Harness  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402
from eval.runner import identity_for_case, run_in_sandbox  # noqa: E402

DB = REPO / "data/olist/olist_sandbox.db"
DATASET = ROOT / "dataset_v3_frozen.json"
GOLD = ROOT / "gold100_frozen_results.json"
RESULTS = [ROOT / f"results_v3_u185_r{i}.json" for i in (4,)]
OUT = ROOT / "probe_u186_shape.json"
TARGETS = ("n05", "n10", "n18", "n39", "o20")


def quarter_spans(ts: str) -> str:
    return (
        f"to_char({ts}, 'YYYY') || '-Q' || "
        f"EXTRACT(quarter FROM {ts})"
    )


def build_candidates(case: dict[str, Any], model_sql: str) -> dict[str, str]:
    """按题面构造候选写法；只动季度表达式，其余结构保留模型 SQL。"""
    ts = "o.order_purchase_timestamp"
    out: dict[str, str] = {"base": model_sql}
    if case["case_id"] in ("n05", "n10", "n18", "n39"):
        natural = f"to_char({ts}::timestamp, 'YYYY') || '-Q' || to_char({ts}::timestamp, 'Q')"
        if natural not in model_sql:
            # 模型本批偶有轻微变体；退化到按 `::timestamp` 全局替换
            out["Q-A"] = (
                model_sql.replace(f"{ts}::timestamp", ts)
                .replace(f"to_char({ts}, 'Q')", f"EXTRACT(quarter FROM {ts})")
            )
        else:
            out["Q-A"] = model_sql.replace(natural, quarter_spans(ts))
        out["Q-B"] = out["Q-A"].replace(
            f"EXTRACT(quarter FROM {ts})",
            f"CAST(EXTRACT(quarter FROM {ts}) AS text)",
        )
        out["Q-D"] = model_sql.replace(natural, f"to_char({ts}, 'YYYY\"-Q\"Q')")
    return out


def judge(
    case_id: str,
    sql: str,
    params: dict[str, Any],
    *,
    allowlist: Any,
    tenant: str,
    tenant_scoped: dict[str, str],
    gold: dict[str, Any],
) -> dict[str, Any]:
    report: dict[str, Any] = {"gate": None, "rule": None, "exec": None, "equivalent": None}
    gate = run_gate1(sql, allowlist, params=params)
    report["gate"] = "pass" if gate.passed else "reject"
    if not gate.passed:
        report["rule"] = gate.gate_result.rule_id
        return report
    pred = run_in_sandbox(
        gate.rewritten_sql,
        params,
        tenant=tenant,
        views=True,
        db_path=str(DB),
        tenant_scoped_physicals=tenant_scoped,
        timeout_s=20.0,
    )
    if pred["error"]:
        report["exec"] = pred["error"]
        report["equivalent"] = False
        return report
    report["exec"] = "ok"
    verdict = eq.compare_tables(
        gold["table"],
        pred["table"],
        gold_sql=gold["sql"],
        pred_sql=gate.rewritten_sql,
        hash_matches=pred["hash"] == gold["hash"] if pred["hash"] else None,
    )
    report["equivalent"] = bool(verdict.equivalent)
    return report


def o20_candidates(model_sql: str, params: dict[str, Any]) -> dict[str, str]:
    """o20：CTE 形态的两种替代写法（HAVING 子查询 / 派生表）。全期间口径，无时间参数。"""
    aov = "SUM(p.payment_value) / NULLIF(COUNT(DISTINCT o.order_id), 0)"
    overall = "SUM(p2.payment_value) / NULLIF(COUNT(DISTINCT o2.order_id), 0)"
    shared_where = "o.order_status NOT IN ('canceled', 'unavailable')"
    sub_where = "o2.order_status NOT IN ('canceled', 'unavailable')"
    return {
        "base": model_sql,
        "O-A": (
            f"SELECT o.customer_state AS state, {aov} AS aov "
            "FROM v_o_payments AS p JOIN v_o_orders AS o ON o.order_id = p.order_id "
            f"WHERE {shared_where} GROUP BY o.customer_state "
            f"HAVING {aov} > (SELECT {overall} FROM v_o_payments AS p2 "
            "JOIN v_o_orders AS o2 ON o2.order_id = p2.order_id "
            f"WHERE {sub_where})"
        ),
        "O-B": (
            f"SELECT s.state, s.aov FROM (SELECT o.customer_state AS state, {aov} AS aov "
            "FROM v_o_payments AS p JOIN v_o_orders AS o ON o.order_id = p.order_id "
            f"WHERE {shared_where} GROUP BY o.customer_state) AS s "
            "CROSS JOIN (SELECT "
            f"{overall} AS overall_aov FROM v_o_payments AS p2 "
            "JOIN v_o_orders AS o2 ON o2.order_id = p2.order_id "
            f"WHERE {sub_where}) AS g "
            "WHERE s.aov > g.overall_aov"
        ),
    }


def main() -> None:
    spec = R.load_cases(DATASET)
    cases = {str(c["case_id"]): c for c in spec["cases"]}
    gold_evidence = {
        str(c["case_id"]): c
        for c in json.loads(GOLD.read_text(encoding="utf-8"))["cases"]
    }
    records: dict[str, dict[str, Any]] = {}
    for path in RESULTS:
        if not path.is_file():
            continue
        run = json.loads(path.read_text(encoding="utf-8"))
        for rec in run["records"]:
            records.setdefault(str(rec["case_id"]), rec)

    bundle = load_bundle(str(REPO / str(spec["bundle"])))
    tenant_scoped = {a.physical_asset: "tenant_id" for a in bundle.bundle.assets}
    harness = Harness(live=False, bundle_path=str(REPO / str(spec["bundle"])), db_path=str(DB))
    allowlist = harness.semantics.guard_allowlist(
        identity_for_case("PROBE-U186", "T_A"), max_rows=None
    )

    evidence: list[dict[str, Any]] = []
    for case_id in TARGETS:
        case = cases[case_id]
        rec = records[case_id]
        tenant = str(case.get("eval_tenant") or "T_A")
        params = dict(rec.get("sql_params") or {})
        gold = run_in_sandbox(
            str(case["gold_sql"]),
            None,
            tenant=tenant,
            views=True,
            db_path=str(DB),
            tenant_scoped_physicals=tenant_scoped,
            timeout_s=20.0,
        )
        gold_ref = {
            "table": gold["table"],
            "hash": gold["hash"],
            "sql": str(case["gold_sql"]),
        }
        if case_id == "o20":
            candidates = o20_candidates(str(rec.get("sql_text") or ""), params)
            if "base" in candidates and not candidates["base"]:
                candidates.pop("base")
        else:
            candidates = build_candidates(case, str(rec.get("sql_text") or ""))
        for shape, sql in candidates.items():
            outcome = judge(
                case_id,
                sql,
                params,
                allowlist=allowlist,
                tenant=tenant,
                tenant_scoped=tenant_scoped,
                gold=gold_ref,
            )
            evidence.append({
                "case_id": case_id,
                "shape": shape,
                "sql": sql,
                "params_used": sorted(params.keys()),
                **outcome,
            })
            print(
                f"{case_id} {shape:5s} gate={outcome['gate']}"
                f"{('/' + str(outcome['rule'])) if outcome['rule'] else ''}"
                f" exec={outcome['exec']} equivalent={outcome['equivalent']}"
            )

    OUT.write_text(
        json.dumps(
            {
                "schema": "U186_SHAPE_PROBE/v1",
                "note": "零 LLM 零出站；候选写法过真 gate1 + 真 run_in_sandbox + compare_tables；不是 live",
                "dataset": DATASET.name,
                "cases": evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("WROTE", OUT.name)


if __name__ == "__main__":
    main()