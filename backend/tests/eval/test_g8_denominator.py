"""W77-3 / D-W77-3：G-8 双分母（`success/attempted` 主、`success/clarified` 并列）。

**为什么不能只留 `success/clarified`**：W76 G-8 设计实测那条唯一带冻结候选的
C-CITY-01 只跑出 1 条 attempted ⇒ `success/clarified = 1/16 = 6.25%`，
读起来像"澄清后一次成功率极低"，实际是"分母根本没收全"（17/18 没有补答来源）。
`attempted < clarified` ⇒ 后者判 UNVERIFIED，而不是拿一个未覆盖的分母去打分。
"""

from __future__ import annotations

from typing import Any

import reporter as rp


def _rec(case_id: str, *, second: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "expected_behavior": "clarify",
        "terminal_event": "clarify",
        "verdict": None,
        "second_round": second,
    }


def _second(success: bool) -> dict[str, Any]:
    return {"attempted": True, "success": success, "terminal_event": "complete" if success else "clarify"}


def test_attempted_is_primary_denominator() -> None:
    """覆盖率不足时：主读数 1/1 = 100%，并列 1/3 = 33.3%，后者 UNVERIFIED。"""
    c = rp._clarify_counts([
        _rec("A", second=_second(True)),
        _rec("B"),
        _rec("C"),
    ])
    assert c is not None
    assert c["primary_denominator"] == "attempted"
    assert c["second_round_attempted"] == 1
    assert c["clarified"] == 3
    assert c["success_rate_attempted"] == 1.0
    assert c["success_rate_clarified"] == 1 / 3
    assert c["clarified_denominator_verdict"] == "UNVERIFIED"


def test_clarified_denominator_is_a_valid_reading_when_covered() -> None:
    """attempted == clarified ⇒ 两个分母都覆盖全，并列读数不再是 UNVERIFIED。"""
    c = rp._clarify_counts([
        _rec("A", second=_second(True)),
        _rec("B", second=_second(False)),
    ])
    assert c is not None
    assert c["success_rate_attempted"] == 0.5
    assert c["success_rate_clarified"] == 0.5
    assert c["clarified_denominator_verdict"] is None


def test_zero_attempted_is_none_not_zero_percent() -> None:
    """一条二轮都没跑 ⇒ 主分母不存在（`None`），不是"0% 成功率"。"""
    c = rp._clarify_counts([_rec("A")])
    assert c is not None
    assert c["success_rate_attempted"] is None
    assert c["success_rate_clarified"] == 0.0
    assert c["clarified_denominator_verdict"] == "UNVERIFIED"
    assert "attempted<clarified" in str(c["denominator_note"])
