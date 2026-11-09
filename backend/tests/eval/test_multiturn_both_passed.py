"""U-160：多轮 `both_passed` 必须是「轮次齐 + 全真」，未跑完不算通过。

为什么单立一条：`eval/olist/results_multiturn_r2_u158.json` 里 `mt15` 只跑完 turn1
（`turn_passes=[True]`，turn2 被预算掐掉），而旧判据 `bool(tp) and all(tp)` 把它算成
「两轮全过」⇒ `cases_both_passed=1` 与 `turn2_passed=0` 同真，读数自相矛盾。
"""

from __future__ import annotations

from typing import Any

import multiturn


def _turn(index: int, ok: bool) -> dict[str, Any]:
    return {
        "turn": index,
        "question": f"q{index}",
        "expect": {"metrics": ["gmv"]},
        "terminal_event": "complete",
        "plan_summary": {"metrics": ["gmv"] if ok else ["aov"]},
        "history_seeded": index > 1,
        "tokens": {},
        "cost_cny": 0.0,
    }


def test_single_turn_is_never_both_passed() -> None:
    """负控①：只跑完 turn1（`[True]`）不算两轮全过。"""
    rec = multiturn.score_case_turns("mt15", "reset", [_turn(1, True)])
    assert rec["turn_passes"] == [True]
    assert rec["both_passed"] is False


def test_two_turns_all_true_is_both_passed() -> None:
    """正控：两轮齐且全真才算。"""
    rec = multiturn.score_case_turns("mt01", "ellipsis_time", [_turn(1, True), _turn(2, True)])
    assert rec["both_passed"] is True


def test_two_turns_one_false_is_not_both_passed() -> None:
    """负控②：两轮齐但有一轮不过 ⇒ 不算。"""
    rec = multiturn.score_case_turns("mt02", "metric_switch", [_turn(1, True), _turn(2, False)])
    assert rec["both_passed"] is False


def test_summarize_ignores_legacy_both_flag() -> None:
    """负控③：旧件里单轮却带 `both_passed=true` 的记录，不许被 `summarize` 采信。"""
    legacy = {
        "case_id": "mt15",
        "follow_up_type": "reset",
        "turn_passes": [True],
        "both_passed": True,
        "turns": [],
    }
    summary = multiturn.summarize([legacy])
    assert summary["cases_both_passed"] == 0
    assert summary["cases_incomplete"] == 1
