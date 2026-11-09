"""U-161：`intent_detail` 必须能读出，缺键回空而不是抛（零 LLM／零出图／零数据库）。

为什么单立一条：`plan` 节点因模型给 `blocking_issues` 判 `refuse(no_data_asset)`
（`graph/nodes/plan.py:94-111`），planner 不可用也判 `refuse(no_data_asset)`
（`plan.py:85-90`）—— 终态相同，只能靠 `intent_detail.reason_code` 区分。
此前记录里没有这一格 ⇒ 「闸门误伤还是模型误报阻塞」不可判。
"""

from __future__ import annotations

from typing import Any

from harness import CaseRun


def _run(state: dict[str, Any]) -> CaseRun:
    return CaseRun(
        case_id="C-CITY-02",
        question="各城市的订单量分别是多少？",
        tenant="T_A",
        identity=object(),  # 本测试只碰 state 派生属性，不用身份
        state=state,
    )


def test_intent_detail_is_read_from_state() -> None:
    run = _run(
        {
            "intent_detail": {
                "reason_code": "plan_blocked",
                "refuse_kind": "no_data_asset",
                "blocking_issues": ["城市维度无法区分收货侧与店铺侧"],
            }
        }
    )
    detail = run.intent_detail
    assert detail["reason_code"] == "plan_blocked"
    assert detail["blocking_issues"] == ["城市维度无法区分收货侧与店铺侧"]


def test_absent_intent_detail_is_empty_dict() -> None:
    assert _run({}).intent_detail == {}


def test_non_mapping_intent_detail_is_empty_dict() -> None:
    assert _run({"intent_detail": ["not", "a", "mapping"]}).intent_detail == {}
