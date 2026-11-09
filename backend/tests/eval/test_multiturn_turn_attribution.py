"""U-162：多轮 turn 级归因四键必须能读出（纯函数，零 LLM／零图／零 DB）。

为什么单立一条：r2 的 15 条里 8 条 turn2 收口 `refuse`，而 turn 记录只有
`terminal_event` / `plan_summary` / `history_seeded` —— 没有 `refusal_reason` /
`terminal_code` / `intent_detail` / `nodes` ⇒ 「意图层判拒 / 链接层无候选 /
plan 阻塞 / 闸门拒」四者不可判。这条钉住：有值原样投影、缺属性回默认不编值。
"""

from __future__ import annotations

from typing import Any

import multiturn


class _Run:
    def __init__(self, **kw: Any) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


def test_full_attribution_is_projected() -> None:
    run = _Run(
        terminal_code="GATE_AST_REJECTED",
        refusal_reason=None,
        intent_detail={"reason_code": "plan_blocked", "blocking_issues": ["x"]},
        nodes=("trusted_context", "normalize", "plan", "refuse_out"),
    )
    got = multiturn.turn_attribution(run)
    assert got["terminal_code"] == "GATE_AST_REJECTED"
    assert got["refusal_reason"] is None
    assert got["intent_detail"]["reason_code"] == "plan_blocked"
    assert got["nodes"] == ("trusted_context", "normalize", "plan", "refuse_out")


def test_missing_attributes_fall_back_without_inventing() -> None:
    got = multiturn.turn_attribution(_Run())
    assert got["terminal_code"] is None
    assert got["refusal_reason"] is None
    assert got["intent_detail"] == {}
    assert got["nodes"] == ()
