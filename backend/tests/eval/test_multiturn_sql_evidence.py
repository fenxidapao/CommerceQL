"""U-166：`sql_text` 与 `exec_error_class` 必须能读、且**穿过** `score_case_turns` 存活。

为什么必须补：多轮 turn 记录此前只有四键（`terminal_code` / `refusal_reason` /
`intent_detail` / `nodes`），缺 SQL 原文与错误类别 ⇒ `SQL_SYNTAX_ERROR` 到底是
「模型写错语法」还是「方言错配（postgres 风味跑在 SQLite 沙箱，T-15 已记过 `near "FROM"`）」
不可判。r5/r6/r7 三批分别 2/2/3 条该码，`mt06` 的 turn1 与 turn2 在 r7 均为该码。

⚠️ 这两条同时钉两层：投影函数（`turn_attribution`）与重建点（`score_case_turns`）。
只测前者会被固定键集重建丢掉 —— `U-162` 就是这么翻车的。
"""

from __future__ import annotations

from typing import Any

import multiturn


class _Run:
    def __init__(self, **kw: Any) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


def test_turn_attribution_projects_sql_evidence() -> None:
    """正控：有值原样投影。"""
    run = _Run(sql_text="SELECT 1 FROM t", exec_error_class="syntax_error")
    got = multiturn.turn_attribution(run)
    assert got["sql_text"] == "SELECT 1 FROM t"
    assert got["exec_error_class"] == "syntax_error"


def test_missing_sql_evidence_falls_back_without_inventing() -> None:
    """负控：属性缺失回 `""` / `None`，**不编默认值**。"""
    got = multiturn.turn_attribution(_Run())
    assert got["sql_text"] == ""
    assert got["exec_error_class"] is None


def test_sql_evidence_survives_scoring() -> None:
    """正控：两键必须穿过 `score_case_turns` 的重建点（这才是 U-166 的闸）。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "订单量也一起看",
        "expect": {"metrics": ["gmv", "order_cnt"]},
        "terminal_event": "error",
        "plan_summary": None,
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
        "terminal_code": "SQL_SYNTAX_ERROR",
        "refusal_reason": None,
        "intent_detail": {},
        "nodes": ("gen_sql", "execute", "error_out"),
        "sql_text": "SELECT * FROM",
        "exec_error_class": "syntax_error",
    }
    rec = multiturn.score_case_turns("mt06", "metric_add", [raw])
    turn = rec["turns"][0]
    assert turn["sql_text"] == "SELECT * FROM"
    assert turn["exec_error_class"] == "syntax_error"


def test_absent_sql_evidence_falls_back_after_scoring() -> None:
    """负控：raw 里没有两键时，重建后回 `""` / `None`，不编值。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "2018 年各月 GMV 是多少？",
        "expect": {},
        "terminal_event": "complete",
        "plan_summary": None,
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
    }
    rec = multiturn.score_case_turns("mt01", "ellipsis_time", [raw])
    turn = rec["turns"][0]
    assert turn["sql_text"] == ""
    assert turn["exec_error_class"] is None
