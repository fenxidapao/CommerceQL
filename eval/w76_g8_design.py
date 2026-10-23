"""W76-2：G-8 二轮回路的设计 + 成本估算（只出材料，不改代码、不真打）。

派单 §97.8 W76-2：现状 16/166 = 9.6%、second-round 未实现、澄清后一次成功 0.0%。
本脚本把三件事分开写清：

1. **状态机**：生产侧（`POST /clarify`）与评测侧（`runner --second-round`）各走到哪一步；
2. **数据缺口**：补答从哪来 —— 冻结集里只有 1/18 条带 `clarify_expected.candidates`；
3. **成本**：从最近一次全量重放（零成本）取逐 case 计费，估算重新录制二轮要多少钱。

🔴 本脚本**不改任何东西**：只读冻结集 + `results_r75_full166_window.json`。

跑法（CommerceQL 根目录，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w76_g8_design.py
产物：`eval/results_w76_g8_design.json`
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

REPLAY = os.path.join(HERE, "results_r75_full166_window.json")
OUT = os.path.join(HERE, "results_w76_g8_design.json")

MARGIN = 1.3


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _tokens(record: dict[str, Any]) -> int:
    value = record.get("tokens") or {}
    return int(value.get("total") or 0) if isinstance(value, dict) else int(value)


def _cost(record: dict[str, Any]) -> float:
    return float(record.get("cost_cny") or 0.0)


def main() -> int:
    replay = _load(REPLAY)
    dataset = _load(_bootstrap.DATASET_PATH)
    cases = {str(c["case_id"]): c for c in dataset["cases"]}
    records = list(replay["records"])

    clarify_records = [r for r in records if str(r.get("expected_behavior")) == "clarify"]
    clarified_all = [r for r in records if str(r.get("terminal_event")) == "clarify"]
    answered_endpoint = [
        r for r in clarified_all if str(r.get("expected_behavior")) == "clarify"
    ]
    mis_clarified = [
        r for r in clarified_all if str(r.get("expected_behavior")) != "clarify"
    ]
    with_candidates = [
        cid
        for cid in (str(r["case_id"]) for r in clarify_records)
        if isinstance(cases[cid].get("clarify_expected"), dict)
        and (cases[cid]["clarify_expected"].get("candidates") or ())
    ]

    def block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "requests": len(rows),
            "tokens": sum(_tokens(r) for r in rows),
            "cost_cny": round(sum(_cost(r) for r in rows), 6),
        }

    per_round = block(clarify_records)
    second_round_est = {
        "requests": len(clarified_all),
        "cost_cny": round(sum(_cost(r) for r in clarified_all), 6),
        "note": "二轮是完整重跑一次图（同 prompt/同工具）⇒ 以首轮同 case 的计费代理",
    }
    full = block(records)

    payload = {
        **_bootstrap.build_stamp(),
        "task": "W76-2 G-8 二轮回路设计＋成本估算（只出材料；未改代码、未真打）",
        "current_reading": {
            "requests": len(records),
            "clarified": len(clarified_all),
            "clarify_rate": round(len(clarified_all) / len(records), 4),
            "expected_clarify_n": len(clarify_records),
            "terminal_clarify_in_expected": len(answered_endpoint),
            "mis_clarified_outside_expected": len(mis_clarified),
            "clarify_then_correct": 0,
            "second_round_loop_available": False,
            "why_zero": "本批 `--second-round` 未开 ⇒ 无可测分子；"
            "门禁因此判 UNVERIFIED（不是 FAIL）—— 见 gates.py 的 G-8 分支",
        },
        "state_machine": {
            "production": [
                "首轮图：意图/绑定走到 clarify → `clarify_out` 写 `clarify` 终态 + "
                "`clarify_id` + 选项 `{value,label,asset}`",
                "`SseRunner._persist_clarify` 把上下文（raw_question / session / options / "
                "task_id）落 Redis，TTL 5 分钟（§A.13）",
                "前端 `POST /api/v1/clarify {clarify_id, option|value}` → 属主门（session 归属）"
                " → **一次性消费**（先删后跑）",
                "`compose_question(raw_question, answer)` → **完整重跑**（FR-9.2：不复用澄清前结论）",
                "新 `task_id`、同 `session_id`、继承原轮 `options`、幂等键不复用",
                "终态 complete / refuse / clarify（再澄清）/ error",
            ],
            "eval": [
                "`runner --second-round`：首轮终态 == clarify 时，用 "
                "`clarify_expected.candidates[0]`（或 `--second-round-answers` 文件）拼出"
                "「原问句（补充口径：X）」",
                "同一 `score_case` 再跑一遍图（**不经 /clarify 端点**）",
                "`record['second_round'] = {attempted, reason, question, terminal_event, "
                "success, tokens, cost_cny, tau_raw}`",
                "`success` 只认二轮 `complete` 且无 infra_error；二轮 gold = "
                "`not_defined_for_second_round`（二轮问句变了，冻结 gold 只对首轮成立）",
            ],
            "gap_between_two": "评测侧绕过 `/clarify` 端点 ⇒ 过期/一次性/属主门/推导式重组"
            "这些**生产语义**没有被评测覆盖；评测只覆盖「补答后再跑一次图能否 complete」",
        },
        "answer_source_gap": {
            "expected_clarify_cases": len(clarify_records),
            "with_frozen_candidates": len(with_candidates),
            "candidate_cases": with_candidates,
            "needs_external_answers": len(clarify_records) - len(with_candidates),
            "mis_clarified_without_answer_source": [str(r["case_id"]) for r in mis_clarified],
            "decision_needed": "外部补答文件（`--second-round-answers`）由谁给、按什么口径给 —— "
            "它是**数据**，不是第二次模型推断；不给就只覆盖 1 条，G-8 分子没有统计意义",
        },
        "denominator_issue": {
            "current_gate_formula": "clarify_then_correct / clarified（gates.py G-8）",
            "problem": "只跑 1 条二轮也能让分母保持 16 ⇒ 6.25%，读起来像系统只成功了 6%，"
            "实际是**没有覆盖**；分母应同时给 `attempted`",
            "proposal": "报告同时列 `success/attempted` 与 `success/clarified`；"
            "`attempted < clarified` 时后半句判 UNVERIFIED（判据变更，需总控/QA 签）",
        },
        "cost_estimates": {
            "per_round_18_clarify_cases": per_round,
            "second_round_est": second_round_est,
            "functional_single_case": {
                "cases": with_candidates,
                "cost_cny": round(
                    sum(_cost(r) for r in clarified_all if str(r["case_id"]) in with_candidates)
                    * 2,
                    4,
                ),
                "note": "只做功能验证（1 条），G-8 分子仍不具统计意义",
            },
            "full_batch_with_second_round": {
                "requests": len(records),
                "first_round_cost_cny": full["cost_cny"],
                "second_round_cost_cny_est": second_round_est["cost_cny"],
                "total_cny_measured": round(full["cost_cny"] + second_round_est["cost_cny"], 4),
                "total_cny_with_margin": round(
                    (full["cost_cny"] + second_round_est["cost_cny"]) * MARGIN, 4
                ),
                "why_full_batch": "匣带按 prompt 哈希键控，`record` 模式**整条重打**"
                "（不混用旧响应）⇒ 想得到可上报告的 G-8 读数，只能整批真打一次",
            },
            "hard_cap_suggestion": {
                "cost_cny": 1.8,
                "rationale": "实测全批 ¥1.09 + 二轮 ≈ ¥0.14，×1.3 余量取整；"
                "先补外部补答数据再花钱，否则分子最多 1 条",
            },
        },
        "recommendation": [
            "先定补答数据源（覆盖至少 7 条 expected=clarify 的实际 clarify 题；"
            "9 条误澄清题要不要给补答另议——它们本应 execute，补答会掩盖绑定缺陷）",
            "再决定是否改 G-8 分母口径（success/attempted）—— 判据变更需签",
            "最后才真打（整批 ¥1.2-1.5）；在此之前 G-8 保持 UNVERIFIED",
        ],
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {os.path.relpath(OUT, ROOT)}")
    print("clarify:", payload["current_reading"])
    print("with candidates:", with_candidates)
    print(
        "full-batch estimate:",
        payload["cost_estimates"]["full_batch_with_second_round"]["total_cny_with_margin"],
        "CNY (with margin)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
