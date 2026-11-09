"""U-162 补：turn 级归因四键必须**穿过** `score_case_turns` 存活（纯函数，零 LLM／零图）。

为什么单立一条：r3 冒烟 live 的六条 turn 记录 `four_keys = 0/4`。成因不是
`turn_attribution(run)` 写错，而是 `score_case_turns` 用固定键集**重建**每条 turn，
把 `run_multiturn` 展开进来的四键丢掉了。上一批的 2 条契约只测投影函数本身，
盖不住真正的丢弃点 —— 这条补的正是那道闸。
"""

from __future__ import annotations

from typing import Any

import multiturn

_KEYS = ("terminal_code", "refusal_reason", "intent_detail", "nodes")


def _turn(index: int) -> dict[str, Any]:
    return {
        "turn": index,
        "question": f"q{index}",
        "expect": {"metrics": ["gmv"]},
        "terminal_event": "refuse",
        "plan_summary": None,
        "history_seeded": index > 1,
        "tokens": {},
        "cost_cny": 0.0,
        "terminal_code": None,
        "refusal_reason": "no_data_asset",
        "intent_detail": {"reason_code": "plan_blocked", "blocking_issues": ["x"]},
        "nodes": ("trusted_context", "normalize", "plan", "refuse_out"),
    }


def test_attribution_survives_scoring() -> None:
    """正控：四键必须原样出现在评分后的 turn 记录里。"""
    rec = multiturn.score_case_turns("mt02", "metric_switch", [_turn(1), _turn(2)])
    for turn in rec["turns"]:
        assert set(_KEYS) <= set(turn), f"四键被丢弃: {sorted(set(_KEYS) - set(turn))}"
        assert turn["refusal_reason"] == "no_data_asset"
        assert turn["intent_detail"]["reason_code"] == "plan_blocked"
        assert turn["nodes"] == ("trusted_context", "normalize", "plan", "refuse_out")


def test_absent_attribution_falls_back_without_inventing() -> None:
    """负控：raw turn 里没有四键时回 None／空，**不编默认值**。"""
    raw = {k: v for k, v in _turn(1).items() if k not in _KEYS}
    rec = multiturn.score_case_turns("mt02", "metric_switch", [raw])
    turn = rec["turns"][0]
    assert turn["terminal_code"] is None
    assert turn["refusal_reason"] is None
    assert turn["intent_detail"] == {}
    assert turn["nodes"] == ()
