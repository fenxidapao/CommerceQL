"""U-164：`plan` 判「像不像追问」必须用**原始问题**，不能用归一化后的（纯函数，零 LLM／零图）。

为什么单立一条：`looks_like_follow_up` 的线索是「呢 / 换成 / 那 / 按 …」，而
`normalized_question` 正是把这些线索规整掉之后的产物 ⇒ 拿归一化文本去判，追问永远判不出。
实测 r6 的 `mt01` / `mt02` / `mt13` 三例：turn1 历史里有时窗（如 `mt13` 的
`2018-07-01` 至 `2018-10-01`），turn2 的 `time_range` 却是 `null` —— 继承在
`inherit_plan` 第一行就早退了。
"""

from __future__ import annotations

from app.planner.inherit import inherit_plan, looks_like_follow_up
from app.planner.schemas import Plan

#: 上一轮脱敏摘要里的时间窗（`mt13` turn1 的真实取值）。
_HISTORY = {"time_range": {"start": "2018-07-01", "end": "2018-10-01"}}


def _plan() -> Plan:
    """本轮计划：有指标、**没有**时窗（正是该被继承补上的形态）。"""
    return Plan(metrics=[{"name": "aov"}])


def test_raw_question_carries_the_cue() -> None:
    """正控：原始问句带线索 ⇒ 继承补上 `time_range`。"""
    result = inherit_plan(_plan(), _HISTORY, "客单价呢？")
    assert "time_range" in result.fields
    assert result.plan.time_range.start == "2018-07-01"
    assert result.plan.time_range.end == "2018-10-01"


def test_normalized_text_loses_the_cue() -> None:
    """负控：归一化后的问句无线索 ⇒ 判不成追问 ⇒ 继承为空（这就是 U-164 的 bug 形态）。"""
    assert looks_like_follow_up("客单价呢？") is True
    assert looks_like_follow_up("客单价是多少？") is False
    result = inherit_plan(_plan(), _HISTORY, "客单价是多少？")
    assert result.fields == ()


def test_metric_switch_wording_same_shape() -> None:
    """同类旁证：`换成订单量呢？` 与它的归一化形态，结论必须一个真一个假。"""
    assert looks_like_follow_up("换成订单量呢？") is True
    assert looks_like_follow_up("订单量是多少？") is False
    assert "time_range" in inherit_plan(_plan(), _HISTORY, "换成订单量呢？").fields
    assert inherit_plan(_plan(), _HISTORY, "订单量是多少？").fields == ()
