"""U-168：`gate1_reject_rule` 必须能读、且**穿过** `score_case_turns` 存活。

为什么补：r9 那 3 条 `GATE_AST_REJECTED`（`mt01` / `mt03` / `mt04` 的 turn1）在 turn 记录里
没有 `gate1_reject_rule` —— 该键只落在单轮 record 顶层（`eval/runner.py:616`），多轮 turn 级
从未透传；`intent_detail` 也只有 `reason_code: null`。于是「是哪条规则拒的」不可判，
与 `T-20` ② 类同族。

⚠️ 与 `U-162` / `U-166` 同一教训：产出侧与重建侧必须同改，只测投影函数盖不住真正的丢弃点。
"""

from __future__ import annotations

from typing import Any

import multiturn


class _Run:
    def __init__(self, **kw: Any) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


def test_projection_reads_gate1_rule() -> None:
    """正控：有值原样投影。"""
    got = multiturn.turn_attribution(_Run(gate1_reject_rule="R10"))
    assert got["gate1_reject_rule"] == "R10"


def test_missing_gate1_rule_is_none_not_invented() -> None:
    """负控：属性缺失回 `None`，**不编默认值**。"""
    assert multiturn.turn_attribution(_Run())["gate1_reject_rule"] is None


def test_gate1_rule_survives_scoring() -> None:
    """正控：该键必须穿过 `score_case_turns` 的重建点（这才是本号的闸）。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "按州拆开看看",
        "expect": {"metrics": ["gmv"]},
        "terminal_event": "error",
        "plan_summary": None,
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
        "terminal_code": "GATE_AST_REJECTED",
        "gate1_reject_rule": "R14",
    }
    rec = multiturn.score_case_turns("mt03", "dimension_add", [raw])
    assert rec["turns"][0]["gate1_reject_rule"] == "R14"


def test_absent_gate1_rule_after_scoring_is_none() -> None:
    """负控：raw 里没有该键时，重建后回 `None`。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "q",
        "expect": {},
        "terminal_event": "complete",
        "plan_summary": None,
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
    }
    rec = multiturn.score_case_turns("mt01", "ellipsis_time", [raw])
    assert rec["turns"][0]["gate1_reject_rule"] is None
