"""U-163：`plan` 的阻塞判定必须先跑继承（纯函数，零 LLM／零图／零 DB）。

为什么单立一条：r5 全量 15 条里 10 条 turn2 收口 `refuse(no_data_asset)` 且
`intent_detail.reason_code=plan_blocked`，原文是「缺少分组维度与对比对象……无法确定
grain 与输出列」—— 而那些恰是 `inherit_plan` 能补的字段；原实现把继承排在阻塞判定
之后，模型一自陈阻塞，上一轮条件根本没机会参与判断。
"""

from __future__ import annotations

from app.graph.nodes.plan import _blocking_is_fatal
from app.planner.inherit import InheritanceResult
from app.planner.schemas import Plan


def _plan() -> Plan:
    return Plan(blocking_issues=["缺少分组维度与对比对象"])


def test_no_blocking_is_never_fatal() -> None:
    assert _blocking_is_fatal((), None) is False


def test_blocking_without_history_stays_fatal() -> None:
    assert _blocking_is_fatal(("缺少分组维度",), None) is True


def test_blocking_with_history_but_nothing_filled_stays_fatal() -> None:
    inherited = InheritanceResult(_plan())
    assert inherited.fields == ()
    assert _blocking_is_fatal(("缺少分组维度",), inherited) is True


def test_blocking_resolved_by_inheritance_is_not_fatal() -> None:
    inherited = InheritanceResult(_plan(), ("grain", "dimensions"))
    assert _blocking_is_fatal(("缺少分组维度",), inherited) is False
