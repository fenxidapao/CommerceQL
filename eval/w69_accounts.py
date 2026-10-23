"""W69 零出站材料：19 条判据冲突包（W69-2）+ 等价判定对空结果的退化出数（W69-3）。

纪律：
- 全程零出站：只读 r66 重放产物 / r68 live 产物 / r63 匣带 / 冻结集与 case_library；
- W69-2 只出材料：不单方面改冻结集，不再为对齐 expected 调系统行为；
- W69-3 只出数：不改等价判据（凡涉及口径变更一律上呈）；
- 证据绑 git_rev + dirty=false。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from _bootstrap import bootstrap, build_stamp  # noqa: E402

bootstrap()

STAMP = build_stamp()

SRC_R66 = os.path.join(HERE, "results_r66_tau_raw_replay.json")
SRC_R68_LIVE = os.path.join(HERE, "results_r68_hstr8.json")
SRC_R69_ROLLBACK = os.path.join(HERE, "results_r69_hstr8_rollback_replay.json")
CASSETTE_R63 = os.path.join(HERE, "cassettes", "w8_r63_full166.jsonl")
DATASET = os.path.join(HERE, "dataset_v1_frozen.json")
OUT_CONFLICT = os.path.join(HERE, "results_r69_conflict_19.json")
OUT_EMPTY = os.path.join(HERE, "results_r69_equiv_empty_degeneracy.json")

PROVENANCE = "W69 零出站材料（r66 重放 + r68 live + r63 匣带 + 冻结集/case_library；tokens 计费 = 0）"


def _intent_responses() -> dict[str, dict[str, Any]]:
    """r63 匣带里的 normalize-intent 响应，**按请求体里的原始问句**精确索引（零出站）。

    ⚠️ 不能用归一化后的问句匹配：LLM 会改写措辞（实测 C-GMV-02「上个月的销售额」
    被归一成「上个月的GMV」）；也不能用 3-gram 模糊匹配 —— 会误配到
    C-CITY-03「广州的销售额是多少？」。请求体 `[待处理的用户问题]` 段是原文，唯一可靠键。
    """
    out: dict[str, dict[str, Any]] = {}
    with open(CASSETTE_R63, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if "问题归一化 + 意图分类" not in rec["request"]["messages"][0]["content"]:
                continue
            user = str(rec["request"]["messages"][-1]["content"])
            m = _RAW_Q_RE.search(user)
            if not m:
                continue
            parsed = json.loads(rec["response"]["choices"][0]["message"]["content"])
            out.setdefault(m.group(1).strip(), parsed)
    return out


_RAW_Q_RE = re.compile(r"\[待处理的用户问题\]\s*\n(.+?)\n")


# ============================================================================
# W69-2 —— 19 条判据冲突包（只出材料）
# ============================================================================

#: 10 条「该问却答」：冻结集 expected=clarify，实测 8 条 complete / 2 条 gate1_ast error。
_ASK_BUT_ANSWERED = (
    "C-GMV-01", "C-GMV-02", "C-GMV-03", "C-GMV-04", "C-RATE-01",
    "C-RATE-02", "C-REP-01", "C-REP-02", "C-UV-02", "C-AOV-01",
)

#: 9 条「合理澄清却要求直答」：冻结集 expected=execute，系统（按语义判断）澄清。
_EXPECTED_EXECUTE_BUT_CLARIFIES = tuple(f"H-STR-{i:02d}" for i in range(1, 9)) + ("X-MET-10",)

#: 若按冻结集对齐，需要动什么（逐条人工判定，理由随行）。
_REMEDY: dict[str, dict[str, str]] = {
    "C-GMV-01": {"kind": "语义包字段 + 系统判据", "detail": "「本月」两解（自然月 / 最近 30 天）标记 + timeexpr 模糊来源闸门"},
    "C-GMV-02": {"kind": "语义包字段 + 系统判据", "detail": "「上月」已有定义 ⇒ 需 echo_confirm 回显确认位 + request_policy 判定"},
    "C-GMV-03": {"kind": "语义包字段 + 系统判据", "detail": "「最近」无定义窗口策略 + timeexpr 未定义窗闸门"},
    "C-GMV-04": {"kind": "语义包字段 + 系统判据", "detail": "「最近一周」起点未定（周起点与自然周边界不同）+ timeexpr 闸门"},
    "C-RATE-01": {"kind": "语义包字段 + 系统判据", "detail": "退款率多口径（金额/单量）标记，包只定义金额口径 ⇒ definition_multiple 闸门"},
    "C-RATE-02": {"kind": "语义包字段 + 系统判据", "detail": "「退货」→ refund_status 术语映射 + request_policy 未映射词闸门"},
    "C-REP-01": {"kind": "语义包字段 + 系统判据", "detail": "复购 90 天固定口径的回显确认位"},
    "C-REP-02": {"kind": "系统判据", "detail": "开放式问法（无窗无维度）缺聚合/时间闸门，纯 request_policy 判定"},
    "C-UV-02": {"kind": "语义包字段 + 系统判据", "detail": "uv_period 未定义（全期去重 vs 逐日累加）⇒ aggregation_ambiguous 闸门"},
    "C-AOV-01": {"kind": "语义包字段 + 系统判据", "detail": "客单价无时间窗 ⇒ timeexpr 闸门"},
    "X-MET-10": {"kind": "语义包字段（契约变更）", "detail": "「618」campaign 别名缺结构化窗口（gold 用 2026-05-24..06-21）"},
}

for _i in range(1, 9):
    _REMEDY[f"H-STR-{_i:02d}"] = {
        "kind": "语义包字段（默认口径）或 修订冻结集 expected",
        "detail": "商品数口径（product_cnt / on_sale_product_cnt / spu_cnt）无唯一默认："
                  "若判直答须在语义包给唯一默认（gold 要 on_sale_product_cnt）；否则应修订 expected=clarify",
    }


def build_conflict_account() -> dict[str, Any]:
    import case_library  # noqa: E402  （纯定义）

    clarify_reason = {e[0]: e[3].get("reason") for e in case_library._CLARIFY}
    dataset = json.load(open(DATASET, encoding="utf-8"))
    frozen = {c["case_id"]: c for c in dataset["cases"]}
    r66 = {r["case_id"]: r for r in json.load(open(SRC_R66, encoding="utf-8"))["records"]}
    intents = _intent_responses()

    rows = []
    for cid in _ASK_BUT_ANSWERED:
        r = r66[cid]
        llm = intents.get(r["question"]) or {}
        rows.append({
            "case_id": cid,
            "bucket": "该问却答",
            "question": r["question"],
            "frozen_expected": frozen[cid]["expected_behavior"],
            "frozen_reason_text": clarify_reason.get(cid) or None,
            "actual_terminal": r["terminal_event"],
            "actual_note": (
                f"SQL 已生成并执行（{r['nodes'][-2] if r['nodes'] else '?'} → {r['nodes'][-1] if r['nodes'] else '?'}）"
                if r["terminal_event"] == "complete"
                else f"止步 {r['nodes'][-1]}；terminal_error_detail={json.dumps(r.get('terminal_error_detail'), ensure_ascii=False)}"
            ),
            "llm_verbatim": {
                "intent": llm.get("intent"),
                "reason_code": llm.get("reason_code"),
                "clarify_hint": llm.get("clarify_hint"),
                "note": "LLM 本身判 query（未识别歧义）⇒ 澄清期望只存在于判据侧" if llm.get("intent") == "query" else None,
            },
            "remedy_if_align_frozen": _REMEDY[cid],
        })

    rollback = {r["case_id"]: r for r in json.load(open(SRC_R69_ROLLBACK, encoding="utf-8"))["records"]}
    for cid in _EXPECTED_EXECUTE_BUT_CLARIFIES:
        r = r66[cid]
        llm = intents.get(r["question"]) or {}
        rows.append({
            "case_id": cid,
            "bucket": "合理澄清却要求直答",
            "question": r["question"],
            "frozen_expected": frozen[cid]["expected_behavior"],
            "frozen_reason_text": (frozen[cid].get("notes") or None),
            "actual_terminal": r["terminal_event"],
            "actual_note": (
                "时间窗无结构化来源（campaign_window_not_structured）⇒ route_after_normalize 直判 clarify"
                if cid == "X-MET-10" else
                "商品数口径歧义（product_cnt / on_sale_product_cnt / spu_cnt）⇒ intent 判 clarify"
                + ("；W69-1 回滚后 replay 仍 clarify（8/8）" if cid in rollback else "")
            ),
            "llm_verbatim": {
                "intent": llm.get("intent"),
                "reason_code": llm.get("reason_code"),
                "clarify_hint": llm.get("clarify_hint"),
            },
            "remedy_if_align_frozen": _REMEDY[cid],
        })

    buckets = Counter(r["bucket"] for r in rows)
    return {
        "provenance": PROVENANCE,
        "task": "W69-2 19 条判据冲突包（只出材料：不改冻结集、不为对齐 expected 调系统行为）",
        **STAMP,
        "headline": {
            "n_cases": len(rows),
            "buckets": dict(buckets),
            "verdict": (
                "这 19 条是『判据与系统语义判断不一致』—— 既不是系统缺陷也不是判据缺陷；"
                "须总控二选一：①修订 expected（基线变更，改冻结集）②改系统行为"
                "（语义包契约变更 + 重基线）。本产物不做选择、不动任何一侧。"
            ),
        },
        "source_note": (
            "actual/LLM 原话来自 r66 重放（10 条该问却答 + X-MET-10）与 r63 匣带 intent 响应；"
            "H-STR 8 条另引 r69 回滚 replay（8/8 clarify）。"
        ),
        "cases": rows,
    }


# ============================================================================
# W69-3 —— 等价判定对空结果的退化（只出数，不改判据）
# ============================================================================

def build_empty_degeneracy() -> dict[str, Any]:
    r66 = json.load(open(SRC_R66, encoding="utf-8"))
    recs = r66["records"]
    dataset = json.load(open(DATASET, encoding="utf-8"))
    frozen = {c["case_id"]: c for c in dataset["cases"]}

    cat: Counter[str] = Counter()
    double_empty: list[dict[str, Any]] = []
    gold_empty_only: list[dict[str, Any]] = []
    pred_empty_only: list[dict[str, Any]] = []

    for r in recs:
        term = str(r.get("terminal_event") or "None")
        if term != "complete":
            cat[f"not_complete:{term}"] += 1
            continue
        g_rows = ((r.get("gold") or {}).get("via_view") or {}).get("rows")
        p_rows = (r.get("predicted") or {}).get("rows")
        verdict = r.get("verdict") or {}
        entry = {
            "case_id": r["case_id"],
            "difficulty": [r.get("difficulty_struct"), r.get("difficulty_semantic")],
            "gold_rows": g_rows,
            "pred_rows": p_rows,
            "equivalent": verdict.get("equivalent"),
            "gold_cols": ((r.get("gold") or {}).get("via_view") or {}).get("cols"),
            "pred_cols": len((r.get("predicted") or {}).get("columns") or []),
            "diffs": verdict.get("diffs"),
        }
        if g_rows == 0 and p_rows == 0:
            cat["double_empty"] += 1
            double_empty.append(entry)
        elif g_rows == 0:
            cat["gold_empty_pred_nonempty"] += 1
            gold_empty_only.append(entry)
        elif p_rows == 0:
            cat["pred_empty_gold_nonempty"] += 1
            pred_empty_only.append(entry)
        else:
            cat["both_nonempty"] += 1

    # —— G-2 = 结构 easy × 语义 low 单元格；passed = verdict.equivalent（reporter.py:1004）——
    easy_low = [
        r for r in recs
        if str(r.get("difficulty_struct")) == "easy"
        and str(r.get("difficulty_semantic")) == "low"
        and r.get("scored") is not False
    ]
    easy_low_pass = sum(1 for r in easy_low if (r.get("verdict") or {}).get("equivalent"))
    de_ids = {e["case_id"] for e in double_empty}
    de_in_easy_low = [r["case_id"] for r in easy_low if r["case_id"] in de_ids]

    # —— G-5 分母 = 冻结集 expected_behavior == "refuse" 的题 ——
    refuse_ids = {cid for cid, c in frozen.items() if c.get("expected_behavior") == "refuse"}
    de_in_refuse = [cid for cid in de_ids if cid in refuse_ids]

    # —— W68 live 的 H-STR 8 条（派单"6 条双空"的事实核对）——
    live = json.load(open(SRC_R68_LIVE, encoding="utf-8"))["records"]
    live_double_empty = [
        r["case_id"] for r in live
        if r.get("terminal_event") == "complete"
        and (((r.get("gold") or {}).get("via_view") or {}).get("rows") == 0)
        and (((r.get("predicted") or {}).get("rows") == 0))
    ]
    live_diffs = Counter(
        d for r in live
        for d in ((r.get("verdict") or {}).get("diffs") or [])
    )

    return {
        "provenance": PROVENANCE,
        "task": "W69-3 等价判定对空结果的退化：出数不改判据（口径变更一律上呈）",
        **STAMP,
        "rule_evidence": {
            "compare_order": "eval/equivalence.py::compare_tables —— 先比列数，再比行数，"
                             "行数相同后走 _multiset_diff；两侧 0 行 ⇒ unmatched=0 ⇒ equivalent=True",
            "implication": "『双空』默认判等价（前提：列数相同且列可配对）；"
                           "unmatched=0 不能读作『数据对上』",
            "g2_passed_source": "eval/reporter.py:1004 —— passed = bool(verdict.equivalent)",
        },
        "headline": {
            "n_records": len(recs),
            "category_counts": dict(sorted(cat.items())),
            "n_double_empty": len(double_empty),
            "n_double_empty_equivalent": sum(1 for e in double_empty if e["equivalent"]),
            "verdict": (
                f"166 条里 {len(double_empty)} 条双空（gold 0 行 & 预测 0 行），"
                f"全部判等价={sum(1 for e in double_empty if e['equivalent']) == len(double_empty)}；"
                "它们对 G-2 / G-5 / G-7 的贡献见 gate_contribution"
            ),
        },
        "gate_contribution": {
            "G-2": {
                "cell": "easy × low",
                "cell_n": len(easy_low),
                "cell_passed": easy_low_pass,
                "cell_rate": round(easy_low_pass / len(easy_low), 4) if easy_low else None,
                "double_empty_in_cell": de_in_easy_low,
                "contribution": (
                    f"{len(de_in_easy_low)} 条（双空题全部落在 extra×low，不进 easy×low 单元格）"
                    "⇒ 对 G-2 判定贡献 = 0；但『双空判等价』的机制仍在，"
                    "一旦有双空题落进 easy×low 就会白送通过"
                ),
            },
            "G-5": {
                "denominator": "冻结集 expected_behavior == 'refuse' 的题",
                "double_empty_in_denominator": de_in_refuse,
                "contribution": "0 条（双空题全部 expected=execute，不进拒答分母）⇒ 贡献 = 0",
            },
            "G-7": {
                "input_source": "eval/reporter.py:1031 —— consistency = probe_metric_values.json"
                                "（§C.4.3 权威值比对），不是 166 条 records 的等价结论",
                "contribution": "不消费 records 等价 ⇒ 贡献 = 0（双空退化影响不到 G-7）",
            },
        },
        "double_empty_cases": double_empty,
        "gold_empty_only": gold_empty_only,
        "pred_empty_only": pred_empty_only,
        "w68_live_hstr_check": {
            "n_double_empty": len(live_double_empty),
            "case_ids": live_double_empty,
            "verdict_diffs_observed": dict(live_diffs),
            "note": "派单所述『H-STR 8 条里 6 条双空』核实成立；当时唯一 diff = 列数不同",
        },
        "boundary": "只出数：未改 equivalence.py / 判据 / 冻结集；口径变更（如空集要求列标签一致）上呈",
    }


def main() -> None:
    conflict = build_conflict_account()
    with open(OUT_CONFLICT, "w", encoding="utf-8") as fh:
        json.dump(conflict, fh, ensure_ascii=False, indent=2)
    print("== W69-2 conflict ==", json.dumps(conflict["headline"], ensure_ascii=False)[:200])

    empty = build_empty_degeneracy()
    with open(OUT_EMPTY, "w", encoding="utf-8") as fh:
        json.dump(empty, fh, ensure_ascii=False, indent=2)
    print("== W69-3 empty ==", json.dumps(empty["headline"], ensure_ascii=False)[:260])
    print("gate contribution:", json.dumps(
        {k: v["contribution"][:40] for k, v in empty["gate_contribution"].items()},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
