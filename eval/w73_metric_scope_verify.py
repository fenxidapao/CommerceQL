"""W72-3 修复后的零出站验证：谓词收窄的**实际影响面** + G-7 口径重算。

输入（都是已落盘产物，不打任何 API）：
* `eval/results_r66_tau_raw_replay.json` —— 修复前的全量 166 重放（旧行为基线）
* `eval/results_r73_full166_metric_scope.json` —— 修复后的全量 166 重放
* `backend/reports/w6/probe_metric_values.json` —— G-7 的 13 条权威值
* `data/ecom_sandbox.db` —— 本地沙箱（只读）

输出：`eval/results_r73_metric_scope_delta.json`
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from _bootstrap import BUNDLE_PATH, bootstrap, build_stamp  # noqa: E402

bootstrap()

STAMP = build_stamp()

from app.semantics import load_bundle  # noqa: E402
import runner  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
SANDBOX = os.path.join(ROOT, "data", "ecom_sandbox.db")
BEFORE = os.path.join(HERE, "results_r66_tau_raw_replay.json")
AFTER = os.path.join(HERE, "results_r73_full166_metric_scope.json")
PROBE = os.path.join(ROOT, "backend", "reports", "w6", "probe_metric_values.json")
OUT = os.path.join(HERE, "results_r73_metric_scope_delta.json")


def _scalar(table) -> Any:
    if table is None or len(table.rows) != 1 or len(table.rows[0]) != 1:
        return None
    v = table.rows[0][0]
    return round(v, 10) if isinstance(v, float) else v


def main() -> None:
    before = {r["case_id"]: r for r in json.load(open(BEFORE, encoding="utf-8"))["records"]}
    after_doc = json.load(open(AFTER, encoding="utf-8"))
    after = {r["case_id"]: r for r in after_doc["records"]}

    pred_delta = []
    for cid, a in after.items():
        b = before.get(cid) or {}
        old = list(b.get("applied_predicates") or [])
        new = list(a.get("applied_predicates") or [])
        if set(old) != set(new):
            pred_delta.append({
                "case_id": cid,
                "question": a.get("question"),
                "removed": sorted(set(old) - set(new)),
                "added": sorted(set(new) - set(old)),
                "before": old,
                "after": new,
            })

    # 等价 / 终态总账（只比总数，逐条差异见两份产物）
    sb, sa = before and json.load(open(BEFORE, encoding="utf-8"))["summary"], after_doc["summary"]
    tally = {
        "n_equivalent_before": sb.get("n_equivalent"),
        "n_equivalent_after": sa.get("n_equivalent"),
        "n_scored_before": sb.get("n_scored"),
        "n_scored_after": sa.get("n_scored"),
        "terminal_distribution_before": sb.get("terminal_distribution"),
        "terminal_distribution_after": sa.get("terminal_distribution"),
    }

    # G-7 重算：system vs authority（用修复后的预测 SQL 在沙箱重跑，与判分同器同界）
    loaded = load_bundle(BUNDLE_PATH)
    tsf = {a.physical_asset: "tenant_id"
           for a in loaded.bundle.assets
           if a.tenant_scoped and a.logical_name in loaded.active_assets}
    probe = json.load(open(PROBE, encoding="utf-8"))
    thr = float(probe.get("threshold_rel_error") or 1e-3)
    rows = []
    ok = 0
    for row in probe["rows"]:
        cid = row["case_id"]
        rec = after.get(cid) or {}
        tenant = row.get("tenant") or rec.get("tenant") or "T_A"
        sql = rec.get("sql_text") or ""
        res = (runner.run_in_sandbox(sql, rec.get("sql_params") or {}, tenant=tenant, views=True,
                                     db_path=SANDBOX, tenant_scoped_physicals=tsf)
               if sql else {})
        val = _scalar(res.get("table"))
        auth = row.get("authority_value")
        rel = abs(val - auth) / abs(auth) if (val is not None and auth) else None
        consistent = rel is not None and rel <= thr
        ok += int(consistent)
        rows.append({"case_id": cid, "metric": row.get("metric"), "authority_value": auth,
                     "system_value": val, "rel_error": rel, "consistent": consistent,
                     "error": res.get("error")})

    doc = {
        "provenance": "W72-3 修复后零出站验证（r66 旧重放 vs r73 新重放 + 沙箱只读重算；tokens=0）",
        "task": "默认谓词按指标收窄：影响面 + G-7 system-vs-authority 重算（只出材料，不改判据）",
        **STAMP,
        "inputs": {
            "before": "eval/results_r66_tau_raw_replay.json",
            "after": "eval/results_r73_full166_metric_scope.json",
            "probe": "backend/reports/w6/probe_metric_values.json",
        },
        "headline": {
            "n_predicate_set_changed": len(pred_delta),
            "changed_cases": [d["case_id"] for d in pred_delta],
            "all_removed_only": all(not d["added"] and d["removed"] for d in pred_delta),
            "removed_predicates": sorted({p for d in pred_delta for p in d["removed"]}),
        },
        "tally": tally,
        "g7_system_vs_authority": {
            "threshold_rel_error": thr,
            "consistent": ok,
            "total": len(rows),
            "rate": round(ok / max(len(rows), 1), 4),
            "red_line": "84.6%→100% 只说明 D 类+W72-3 两个问题修好，"
                        "**不改变**「G-7 现行实现度量题库而非系统」这一判据问题（W72-2 A/B 案仍待裁）",
        },
        "g7_rows": rows,
        "predicate_delta": pred_delta,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    print("predicate-set changed:", len(pred_delta), [d["case_id"] for d in pred_delta])
    print("tally:", json.dumps(tally, ensure_ascii=False))
    print("G-7 system vs authority:", ok, "/", len(rows))
    print("written:", OUT)


if __name__ == "__main__":
    main()
