"""U-172：turn 级 `applied_predicates` 必须能读、且**穿过** `score_case_turns` 存活。

为什么补：单轮 record 已有该键（`eval/runner.py:614`），`eval/harness.py:594-595` 也暴露，
但 r12 的 turn 级 16 键里没有它 ⇒ 多轮批上「默认谓词注入了没、注了几条」不可复算
（与 `U-166` / `U-168` 同族的采集缺口）。

判据面不动：注入本身由 `backend/app/guard/ast_gate.py:649` 的 `_inject_predicates` 完成，
本条只补采集与穿点控制；旧件（r1 到 r12）保持原样、不重写。
"""

from __future__ import annotations

from typing import Any

import multiturn


class _Run:
    def __init__(self, **kw: Any) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


def test_projection_reads_applied_predicates() -> None:
    """正控：有值原样投影（顺序与条数都不动）。"""
    got = multiturn.turn_attribution(
        _Run(applied_predicates=("pay_status = 'paid'", "is_test_order = false"))
    )
    assert got["applied_predicates"] == ("pay_status = 'paid'", "is_test_order = false")


def test_missing_applied_predicates_is_empty_tuple() -> None:
    """负控：属性缺失回空元组，**不编值**。"""
    assert multiturn.turn_attribution(_Run())["applied_predicates"] == ()


def test_applied_predicates_survive_scoring() -> None:
    """正控：该键必须穿过 `score_case_turns` 的重建点（这才是本号的闸）。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "2018 年 GMV 是多少？",
        "expect": {"metrics": ["gmv"]},
        "terminal_event": "complete",
        "plan_summary": None,
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
        "terminal_code": None,
        "applied_predicates": ["pay_status = 'paid'"],
    }
    rec = multiturn.score_case_turns("mt02", "metric_switch", [raw])
    assert rec["turns"][0]["applied_predicates"] == ("pay_status = 'paid'",)


def test_absent_applied_predicates_after_scoring_is_empty() -> None:
    """负控：raw 里没有该键时，重建后回空元组。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "2018 年各州订单量是多少？",
        "expect": {},
        "terminal_event": "complete",
        "plan_summary": None,
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
    }
    rec = multiturn.score_case_turns("mt01", "ellipsis_time", [raw])
    assert rec["turns"][0]["applied_predicates"] == ()
