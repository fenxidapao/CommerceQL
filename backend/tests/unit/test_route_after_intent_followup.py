"""U-158：多轮追问不再被意图层「假歧义」拦成 clarify（纯函数，零 LLM／零图／零 DB）。

钉四件事，缺一件这条改动就是错的：
1. 正控 —— 有 `history_plan` + 形似追问 ⇒ 走 `link`（让 `plan` 的 `inherit_plan` 补空位）；
2. 负控① —— 无历史 / 空历史 ⇒ 仍 `clarify_out`（单轮 166 条回放行为逐字不变）；
3. 负控② —— 有历史但本轮是一句完整新问题 ⇒ 仍 `clarify_out`（判据不是「有历史就放行」）；
4. 负控③ —— 已设 `terminal` 时判据不成立；其余三去向不受影响。
"""

from __future__ import annotations

from typing import Any

from app.graph.edges import route_after_intent
from app.graph.nodes import CLARIFY_OUT, LINK, REFUSE_OUT


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "intent": "clarify",
        "raw_question": "换成订单量呢？",
        "normalized_question": "订单量是多少？",
        "history_plan": None,
        "terminal": None,
    }
    base.update(over)
    return base


def test_follow_up_with_history_goes_to_link() -> None:
    """正控：有上一轮计划摘要 + 形似追问 ⇒ 不在意图层收口。"""
    state = _state(history_plan={"metrics": ["gmv"], "time_range": {"start": "2018-01-01"}})
    assert route_after_intent(state) == LINK


def test_no_history_still_clarifies() -> None:
    """负控①：无历史 / 空历史 ⇒ 与改动前逐字一致。"""
    assert route_after_intent(_state()) == CLARIFY_OUT
    assert route_after_intent(_state(history_plan={})) == CLARIFY_OUT


def test_history_but_not_follow_up_still_clarifies() -> None:
    """负控②：有历史但本轮是完整新问题 ⇒ 判据不成立，仍澄清。"""
    state = _state(
        raw_question="各城市的订单量分别是多少？",
        history_plan={"metrics": ["gmv"]},
    )
    assert route_after_intent(state) == CLARIFY_OUT


def test_terminal_set_wins_over_follow_up_guard() -> None:
    """负控③：节点已设终态时，判据必须让位（不绕掉 kill switch 那类收口）。"""
    state = _state(
        history_plan={"metrics": ["gmv"]},
        terminal={"event": "refuse", "reason": "out_of_scope"},
    )
    assert route_after_intent(state) == CLARIFY_OUT


def test_other_intents_unaffected() -> None:
    """其余三去向不受判据影响（判据只挂在 clarify 分支上）。"""
    hist = {"metrics": ["gmv"]}
    assert route_after_intent(_state(intent="refuse", history_plan=hist)) == REFUSE_OUT
    assert route_after_intent(_state(intent="open_analysis", history_plan=hist)) == REFUSE_OUT
    assert route_after_intent(_state(intent="executable", history_plan=hist)) == LINK
