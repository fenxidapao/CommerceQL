"""U-174：未注册 PG 专有构造必须穿过 turn 级记录（与 U-172 同族的采集面）。

为什么补：`eval/sqlite_pg_constructs.py::unregistered_constructs` 只把
「这条 SQL 里有未注册的 PG 专有构造」说出来，但若这条信息进不了记录，
读数上它仍与「模型写错」长得一样（`T-22` 与 `T-15` 都吃过这个亏）。

判据面不动：本文件只验投影与穿点，不改翻译、不改判定、不改闸门。
"""

from __future__ import annotations

from typing import Any

import multiturn


class _Run:
    def __init__(self, **kw: Any) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


def test_projection_names_unregistered_construct() -> None:
    """正控：`EXTRACT` 必须被点名，且顺序稳定（升序去重）。"""
    got = multiturn.turn_attribution(
        _Run(sql_text="SELECT EXTRACT(QUARTER FROM o.ts) AS q FROM v_o_orders AS o")
    )
    assert got["unregistered_pg_constructs"] == ("EXTRACT",)


def test_plain_sql_projects_empty_tuple() -> None:
    """负控：干净 SQL 回空元组，**不编值**。"""
    got = multiturn.turn_attribution(
        _Run(sql_text="SELECT COUNT(DISTINCT o.order_id) AS n FROM v_o_orders AS o")
    )
    assert got["unregistered_pg_constructs"] == ()


def test_missing_sql_text_is_empty_tuple() -> None:
    """负控：没有 `sql_text` 时同样回空元组（不抛、不猜）。"""
    assert multiturn.turn_attribution(_Run())["unregistered_pg_constructs"] == ()


def test_unregistered_survives_scoring() -> None:
    """正控：该键必须穿过 `score_case_turns` 的重建点（这才是本号的闸）。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "2018 年各季度 GMV 是多少？",
        "expect": {},
        "terminal_event": "complete",
        "plan_summary": None,
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
        "sql_text": "SELECT EXTRACT(QUARTER FROM o.ts) AS q FROM v_o_orders AS o",
        "unregistered_pg_constructs": ["EXTRACT"],
    }
    rec = multiturn.score_case_turns("mt01", "ellipsis_time", [raw])
    assert rec["turns"][0]["unregistered_pg_constructs"] == ("EXTRACT",)
