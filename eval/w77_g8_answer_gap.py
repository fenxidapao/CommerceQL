"""W77-3：G-8 补答缺口清单（零出站；**只列不编**）。

W76 G-8 设计的结论是：18 条 `expected_behavior=clarify` 里只有 1 条带冻结候选，
其余 17 条没有补答来源；而实际收口成 clarify 的 16 条里，有 9 条是**题面本应 execute
的误澄清**——给它们补答会掩盖绑定缺陷，所以**不给补答**。

本脚本把这件事落成可核对的清单，**不生成任何答案文本**：
* 18 条 expected=clarify：`case_id/question/reason/是否带冻结候选/缺什么答案`；
* 9 条误澄清单列，标 `不给补答`；
* 双分母读数（W77-3）与结论：**G-8 仍 UNVERIFIED；需数据源**。

跑法（仓库根，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w77_g8_answer_gap.py
产物：`eval/results_w77_g8_answer_gap.json`
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
import reporter  # noqa: E402

REPLAY = os.path.join(HERE, "results_w77_full166_applicability.json")
OUT = os.path.join(HERE, "results_w77_g8_answer_gap.json")

MISCLARIFY_WHY = "题面本应 execute；补答会掩盖绑定缺陷"
NO_ANSWER = (
    "冻结集无 `clarify_expected.candidates` ⇒ 缺外部补答来源"
    "（需业务给出该维度的口径；本脚本不编答案）"
)
HAS_ANSWER = "已有冻结候选，可直接作为补答来源（`candidates[0]`）"


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def main() -> int:
    dataset = _load(_bootstrap.DATASET_PATH)
    replay = _load(REPLAY)
    records = list(replay.get("records") or [])
    by_id = {str(r.get("case_id")): r for r in records}

    clarify_rows: list[dict[str, Any]] = []
    for case in dataset.get("cases") or []:
        if str(case.get("expected_behavior")) != "clarify":
            continue
        case_id = str(case.get("case_id"))
        expected = case.get("clarify_expected") or {}
        candidates = [
            str(c) for c in (expected.get("candidates") or []) if str(c).strip()
        ]
        observe = by_id.get(case_id) or {}
        clarify_rows.append({
            "case_id": case_id,
            "question": case.get("question"),
            "reason": expected.get("reason") or "冻结集未写 reason",
            "has_frozen_candidate": bool(candidates),
            "frozen_candidates": candidates,
            "missing_answer": HAS_ANSWER if candidates else NO_ANSWER,
            "observed_terminal_event": observe.get("terminal_event"),
        })
    clarify_rows.sort(key=lambda row: row["case_id"])

    misclarified: list[dict[str, Any]] = []
    for record in records:
        if (
            str(record.get("expected_behavior")) == "execute"
            and record.get("terminal_event") == "clarify"
        ):
            misclarified.append({
                "case_id": str(record.get("case_id")),
                "question": record.get("question"),
                "expected_behavior": "execute",
                "observed_terminal_event": "clarify",
                "supplement_policy": "不给补答",
                "why": MISCLARIFY_WHY,
            })
    misclarified.sort(key=lambda row: row["case_id"])

    counts = reporter._clarify_counts(records)
    with_candidate = sum(1 for row in clarify_rows if row["has_frozen_candidate"])

    payload = {
        **_bootstrap.build_stamp(),
        "task": "W77-3 G-8 分母与补答缺口（零出站；只列不编；不实装二轮）",
        "source": {
            "replay": _relative(REPLAY),
            "git_rev": replay.get("git_rev"),
            "git_dirty": replay.get("git_dirty"),
            "generated_at": replay.get("generated_at"),
            "n_records": len(records),
        },
        "expected_clarify": {
            "n": len(clarify_rows),
            "n_with_frozen_candidate": with_candidate,
            "n_missing_answer_source": len(clarify_rows) - with_candidate,
            "rows": clarify_rows,
        },
        "misclarified": {
            "n": len(misclarified),
            "policy": "不给补答（见每行 why）；它们进误拒面，不进 G-8 的二轮回路",
            "rows": misclarified,
        },
        "clarification_denominators": counts,
        "conclusion": "G-8 仍 UNVERIFIED；需数据源",
        "reason": (
            "17/18 应澄清题没有补答来源；唯一有冻结候选的 C-CITY-01 只覆盖 1 条，"
            "attempted<clarified ⇒ success/clarified 判 UNVERIFIED。"
            "在数据源到位前不跑二轮、不编补答。"
        ),
        "no_live_run": True,
        "historical_billing_note": "回放读数来自历史匣带，零新增支出",
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {_relative(OUT)}")
    print(
        f"expected_clarify={len(clarify_rows)} with_candidate={with_candidate} "
        f"missing={len(clarify_rows) - with_candidate} misclarified={len(misclarified)}"
    )
    if counts:
        print(
            f"attempted={counts['second_round_attempted']} clarified={counts['clarified']} "
            f"rate_attempted={counts['success_rate_attempted']} "
            f"rate_clarified={counts['success_rate_clarified']} "
            f"clarified_verdict={counts['clarified_denominator_verdict']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
