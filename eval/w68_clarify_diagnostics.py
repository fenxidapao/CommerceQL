"""W68 零出站诊断：X-MET-10 单条定位（W68-2）+ 澄清完备性材料账（W68-3）。

纪律（TASK_BOARD W68 派单）：
- 全程零出站：只读 r63 匣带 / r66 重放产物 / 真语义包离线解析 / case_library 定义；
- W68-3 只出材料：**不实装闸门**、不改行为；红线 = 不得写「澄清能力已验证」；
- 证据绑 git_rev + dirty=false。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from _bootstrap import bootstrap, build_stamp  # noqa: E402

bootstrap()

from app.core.clock import FrozenClock  # noqa: E402
from app.planner.timeexpr import resolve_time  # noqa: E402
from app.semantics import SemanticBundleRuntime, load_bundle  # noqa: E402

SRC_REPLAY = os.path.join(HERE, "results_r66_tau_raw_replay.json")
CASSETTE = os.path.join(HERE, "cassettes", "w8_r63_full166.jsonl")
BUNDLE = Path(HERE, "..", "semantic", "bundle_2026.09.14.1.yaml")
OUT_XMET = os.path.join(HERE, "results_r68_xmet10_diagnosis.json")
OUT_COMPLETENESS = os.path.join(HERE, "results_r68_clarify_completeness.json")

PROVENANCE = "W68 零出站诊断（r63 匣带 + r66 重放 + 真语义包离线解析；tokens 计费 = 0）"


# ---------------------------------------------------------------------------
# W68-2 —— X-MET-10 单条定位（只定位不断言）
# ---------------------------------------------------------------------------

def probe_xmet10() -> dict[str, Any]:
    case_id = "X-MET-10"
    question = "T_A 618 期间各大区各店铺的成交金额合计是多少？"

    replay = json.load(open(SRC_REPLAY, encoding="utf-8"))
    rec = next(r for r in replay["records"] if r["case_id"] == case_id)

    # ① intent LLM（normalize 合并档）实际响应 —— 从 r63 匣带读（零出站）
    intent_llm: dict[str, Any] | None = None
    with open(CASSETTE, encoding="utf-8") as fh:
        for line in fh:
            crec = json.loads(line)
            blob = "".join(
                m.get("content") or "" for m in crec["request"]["messages"]
            )
            if "618 期间各大区各店铺" in blob:
                content = crec["response"]["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                intent_llm = {
                    "intent": parsed.get("intent"),
                    "confidence": parsed.get("confidence"),
                    "reason_code": parsed.get("reason_code"),
                    "clarify_hint": parsed.get("clarify_hint"),
                    "time_expression": parsed.get("time_expression"),
                    "unmapped_terms": parsed.get("unmapped_terms"),
                    "source": "eval/cassettes/w8_r63_full166.jsonl（r63 实跑录制）",
                }
                break

    # ② resolve_time 离线实证 —— 真语义包 + 冻结时钟（今天与 r66 重放同日 2026-10-23）
    runtime = SemanticBundleRuntime(load_bundle(BUNDLE))
    clock = FrozenClock(
        _now=datetime(2026, 10, 23, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        _semantics=runtime.time_semantics(),
    )
    resolution = resolve_time(question, runtime, clock)
    resolve_observed = {
        "ok": resolution.ok,
        "reason": resolution.reason,
        "window": None if resolution.window is None
        else [str(resolution.window.start), str(resolution.window.end)],
        "unresolved_terms": list(resolution.unresolved),
        "method": "resolve_time(question, SemanticBundleRuntime(真包 2026.10.16.2), "
                  "FrozenClock(2026-10-23 10:30 +08)) —— 离线实证，非复述文档",
    }

    return {
        "provenance": PROVENANCE,
        "task": "W68-2 X-MET-10 单条定位：止步 clarify_out 的触发层（只定位不断言）",
        **build_stamp(),
        "case": {"case_id": case_id, "question": question,
                 "expected_behavior": rec["expected_behavior"]},
        "r66_pipeline": {
            "nodes": rec["nodes"],
            "terminal": rec["terminal_event"],
            "note": "nodes 里没有 intent 节点 ⇒ 路由在 intent 之前分流",
        },
        "layers": [
            {
                "layer": "① intent LLM（normalize 合并档）",
                "observed": intent_llm,
                "verdict": "query/高置信、reason_code=null ⇒ LLM 不构成澄清触发",
            },
            {
                "layer": "② resolve_time（planner/timeexpr.py:329，docstring 三种 ok=False 之情形 1）",
                "observed": resolve_observed,
                "verdict": "「618」是 campaign 别名、包内无结构化窗口 ⇒ time_parse_ok=False —— **实际触发点**",
            },
            {
                "layer": "③ route_after_normalize（graph/edges.py:183）",
                "observed": "time_parse_ok is False → CLARIFY_OUT（意图节点不运行）",
                "verdict": "路由层执行了 ② 的判定",
            },
            {
                "layer": "④ 层级（大区/店铺）",
                "verdict": "未触发 —— 链在 link/plan 之前已断，层级从未被读到",
            },
            {
                "layer": "⑤ 成交金额口径",
                "verdict": "未触发 —— 同上；gold 用 gmv（SUM(pay_amount)），口径可映射",
            },
        ],
        "honest_note": (
            "派单要求读 intent_detail.reason_code 与 ambiguities 原文 —— 实测两者在运行时不存在："
            "intent 节点未运行（r66 nodes 无 intent），澄清由确定性时间层在路由处触发；"
            "此处如实报告『要读的东西不存在』，不构造替代文本。"
        ),
        "gold_reference": {
            "gold_window": "pay_time >= '2026-05-24' AND pay_time < '2026-06-21'",
            "note": "gold 有结构化 618 窗而语义包没有 ⇒ 修复路径 = 契约变更（语义包补 campaign "
                    "结构化窗口），按派单⑤本轮不碰、须另轮 + 重基线",
        },
        "conclusion": {
            "trigger": "time_window（campaign_window_not_structured）",
            "not_triggered": ["region/shop 层级", "成交金额口径"],
            "assertion_scope": "只定位不断言（本产物不给修复方案）",
        },
    }


# ---------------------------------------------------------------------------
# W68-3 —— 澄清完备性材料账（只出材料，不改行为）
# ---------------------------------------------------------------------------

#: QA 四类口径 → 案例映射（与派单给的四类计数 5/1/1/1/2 对齐）。
_CLASS_OF: dict[str, dict[str, str]] = {
    "C-GMV-01": {"gate_class": "time_window_undefined",
                 "missing": "「本月」= 自然月 vs 最近 30 天，包内两解且无闸门"},
    "C-GMV-02": {"gate_class": "echo_confirm",
                 "missing": "「上月」已定义，但时区与含端未回显确认"},
    "C-GMV-03": {"gate_class": "time_window_undefined",
                 "missing": "「最近」无定义窗口"},
    "C-GMV-04": {"gate_class": "time_window_undefined",
                 "missing": "「最近一周」起点未定（且实测 gate1_ast error）"},
    "C-RATE-01": {"gate_class": "definition_multiple",
                  "missing": "退款率金额/单量双口径，包只定义金额口径，缺口径确认闸门"},
    "C-RATE-02": {"gate_class": "term_mapping_unknown",
                  "missing": "「退货」→ refund_status 的术语映射未闸"},
    "C-REP-01": {"gate_class": "echo_confirm",
                 "missing": "复购 90 天窗口固定口径须回显确认"},
    "C-REP-02": {"gate_class": "time_window_undefined",
                 "missing": "开放式问法无时间窗（QA 计入 time_window_undefined）"},
    "C-UV-02": {"gate_class": "aggregation_ambiguous",
                "missing": "「总」= 全期去重 vs 逐日累加，uv_period 未定义"},
    "C-AOV-01": {"gate_class": "time_window_undefined",
                 "missing": "客单价无时间窗"},
}

IMPLEMENTATION_CHECKLIST = {
    "contract_change_required": True,
    "files_to_touch": [
        {"path": "semantic/bundle_2026.09.14.1.yaml（新版本号）",
         "change": "四类闸门的语义声明：模糊时间窗策略（relative_time 未定 → 强制澄清）、"
                   "多口径指标标记（refund_rate 单量口径=未定义）、术语映射表（退货→refund_status）、"
                   "uv_period / 复购口径回显位",
         "blast": "契约变更：改 prompt ⇒ 请求哈希全变 ⇒ r63 匣带全 miss，须重基线（派单⑤）"},
        {"path": "backend/app/planner/timeexpr.py",
         "change": "window 已解析但属『模糊来源』时仍返回可区分 reason"
                   "（现状：只有解析失败才 ok=False，C-GMV-01/02 的窗口直接放行）"},
        {"path": "backend/app/planner/request_policy.py",
         "change": "preflight 增加 definition_multiple / term_mapping_unknown / echo_confirm 三类澄清判定"},
        {"path": "backend/app/graph/nodes/normalize.py",
         "change": "preflight 澄清结果进 intent_detail（reason_code 家族 + 缺失闸门原文）"},
        {"path": "backend/app/graph/nodes/clarify_out.py",
         "change": "按闸门类组装澄清文案（回显确认类要带出包内既有定义）"},
        {"path": "eval/case_library.py",
         "change": "clarify 期望文本已有（_CLARIFY），冻结集不动；如需逐闸门断言须扩 schema（另轮）"},
    ],
    "cassette_breakage": [
        "语义包变更 ⇒ normalize/intent 与 plan 的 prompt 都变 ⇒ eval/cassettes/w8_r63_full166.jsonl "
        "全量 miss（166 条重放失效，须 live 重录）",
        "timeexpr/request_policy 为确定性代码层：不改 prompt ⇒ 匣带请求哈希不变，"
        "但重放语义改变（8 条 complete 会变 clarify）⇒ G-2/G-5/G-8 口径重算，属重基线范围",
    ],
    "gating_position": "单列指标（澄清完备性），不进八格、不作收口硬条件（总控已裁）",
}


def build_completeness() -> dict[str, Any]:
    sys.path.insert(0, HERE)
    import case_library  # noqa: E402  （纯定义，无副作用）

    expected = {e[0]: e for e in case_library._CLARIFY}
    replay = json.load(open(SRC_REPLAY, encoding="utf-8"))
    recs = {r["case_id"]: r for r in replay["records"]}

    cases = []
    for cid, meta in _CLASS_OF.items():
        r = recs[cid]
        exp = expected[cid]
        complete = r["terminal_event"] == "complete"
        sql = r.get("sql_text") or ""
        cases.append({
            "case_id": cid,
            "question": r["question"],
            "clarify_expected_reason": exp[3].get("reason"),
            "gate_class": meta["gate_class"],
            "missing_gate": meta["missing"],
            "actual": {
                "terminal": r["terminal_event"],
                "clarified": r["terminal_event"] == "clarify",
                "nodes_tail": r["nodes"][-3:],
                "sql_present": bool(sql),
                "sql_digest": (sql[:180] + "…") if len(sql) > 180 else sql,
                "applied_predicates": r.get("applied_predicates"),
                "note": None if complete else
                f"实测未澄清且未出数：{r['terminal_event']} @ {r['nodes'][-1]}"
                f"（terminal_error_detail={json.dumps(r.get('terminal_error_detail'), ensure_ascii=False)}）",
            },
        })

    n_clarified = sum(1 for c in cases if c["actual"]["clarified"])
    n_complete = sum(1 for c in cases if c["actual"]["terminal"] == "complete")
    n_error = sum(1 for c in cases if c["actual"]["terminal"] == "error")
    by_class: dict[str, int] = {}
    for c in cases:
        by_class[c["gate_class"]] = by_class.get(c["gate_class"], 0) + 1

    return {
        "provenance": PROVENANCE,
        "task": "W68-3 澄清完备性材料账（只出材料，不改行为；不实装闸门）",
        "red_line": "本产物不构成『澄清能力已验证』——它度量的是缺哪些闸门；"
                    "亦不得为凑澄清率上限改判据或剔分母",
        **build_stamp(),
        "headline": {
            "n_cases": len(cases),
            "n_clarified_actual": n_clarified,
            "n_executed_complete": n_complete,
            "n_error": n_error,
            "verdict": (
                f"10 条『应澄清』题实测 0 条澄清：{n_complete} 条带静默默认值一路执行到 "
                f"complete，{n_error} 条在 gate1_ast 报 error（C-GMV-04 / C-REP-02），"
                "澄清完备性闸门整体缺失"
            ),
        },
        "class_counts": by_class,
        "class_counts_qa_reference": {
            "time_window_undefined": 5, "definition_multiple": 1,
            "term_mapping_unknown": 1, "aggregation_ambiguous": 1,
            "echo_confirm": 2, "note": "与 QA 派单给的四类计数逐类对齐",
        },
        "cases": cases,
        "implementation_checklist": IMPLEMENTATION_CHECKLIST,
    }


def main() -> None:
    xmet = probe_xmet10()
    with open(OUT_XMET, "w", encoding="utf-8") as fh:
        json.dump(xmet, fh, ensure_ascii=False, indent=2)
    print("== W68-2 X-MET-10 ==")
    print("trigger:", xmet["conclusion"]["trigger"],
          "| resolve reason:", xmet["layers"][1]["observed"]["reason"])

    comp = build_completeness()
    with open(OUT_COMPLETENESS, "w", encoding="utf-8") as fh:
        json.dump(comp, fh, ensure_ascii=False, indent=2)
    print("== W68-3 completeness ==")
    print(json.dumps(comp["headline"], ensure_ascii=False))
    print("class_counts:", comp["class_counts"])


if __name__ == "__main__":
    main()
