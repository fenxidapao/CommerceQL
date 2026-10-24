"""W78-2 / D-W78-2：G-8 门禁层双分母（主 `success/attempted`，并列 `success/clarified`）。

**为什么必须在门禁层接**：W77-3 只把双分母落到报告层时，G-8 仍用
`clarify_then_correct / clarified` 判 PASS/FAIL。将来若 `attempted=1 < clarified=16`
且该条成功，门禁会按 `1/16=6.25%` 判 FAIL —— 正是 D-W77-3 要消除的误读。
本文件钉住：`attempted==0 ⇒ UNVERIFIED`；`attempted>0` 只按主读数判；
并列分母在 `attempted<clarified` 时标 UNVERIFIED 且**不得**驱动 verdict。
"""

from __future__ import annotations

from typing import Any

import gates as gt


def _gate(clarification: dict[str, Any]) -> gt.Gate:
    return next(
        g for g in gt.evaluate_gates(clarification=clarification, tau_calibrated=True)
        if g.gate_id == "G-8"
    )


def _base(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "requests": 200,
        "clarified": 16,
        "clarify_then_correct": 1,
        "second_round_attempted": 1,
        "second_round_success": 1,
        "success_rate_attempted": 1.0,
        "success_rate_clarified": 1 / 16,
        "second_round_loop_available": True,
    }
    data.update(over)
    return data


def test_attempted_one_of_sixteen_passes_by_primary() -> None:
    """attempted=1、success=1、clarified=16 ⇒ 主读数 100% PASS；并列 6.2% 标 UNVERIFIED。"""
    gate = _gate(_base())
    assert gate.verdict == "PASS"
    assert "主读数 success/attempted = 1/1 = 100.0%" in gate.measured
    assert "并列 success/clarified = 1/16 = 6.2%" in gate.measured
    assert "UNVERIFIED（attempted<clarified" in gate.measured
    assert any("不参与 verdict" in c for c in gate.caveats)


def test_zero_attempted_is_unverified_not_zero_percent() -> None:
    """attempted=0 ⇒ UNVERIFIED；不得把"没跑二轮"读成 0% 成功率。"""
    gate = _gate(_base(
        second_round_attempted=0, second_round_success=0,
        clarify_then_correct=0, success_rate_attempted=None,
        success_rate_clarified=0.0,
    ))
    assert gate.verdict == "UNVERIFIED"
    assert "attempted=0 ⇒ 不可测" in gate.measured


def test_attempted_sixteen_thirteen_passes() -> None:
    gate = _gate(_base(
        clarified=16, second_round_attempted=16, second_round_success=13,
        clarify_then_correct=13, success_rate_attempted=13 / 16,
        success_rate_clarified=13 / 16,
    ))
    assert gate.verdict == "PASS"


def test_attempted_sixteen_twelve_fails() -> None:
    gate = _gate(_base(
        clarified=16, second_round_attempted=16, second_round_success=12,
        clarify_then_correct=12, success_rate_attempted=12 / 16,
        success_rate_clarified=12 / 16,
    ))
    assert gate.verdict == "FAIL"


def test_secondary_denominator_never_drives_fail() -> None:
    """主读数 2/2=100%，并列 2/16=12.5% ⇒ 仍 PASS（并列不参与 verdict）。"""
    gate = _gate(_base(
        second_round_attempted=2, second_round_success=2,
        clarify_then_correct=2, success_rate_attempted=1.0,
        success_rate_clarified=2 / 16,
    ))
    assert gate.verdict == "PASS"
    assert "并列 success/clarified = 2/16 = 12.5%" in gate.measured
