"""U-159：repair 轮次与逐轮摘要必须能从 `CaseRun` 读出（零 LLM／零出图／零数据库）。

为什么单独立一条：`repair_round` / `repair_history` 在图侧一直有值
（`graph/state.py:355-356`、`graph/nodes/repair.py:122-134`），但评测记录此前
没取 ⇒ v2+v3 共 480 条结果件全 `null`。这条测试钉住三件事，缺一件就退回原状：
1. 有值时能原样读出（轮次是整数、摘要是逐轮映射）；
2. 缺键时回 `0` / 空元组（**不编中间值**，也不抛）；
3. 摘要里**不含 SQL**（组 9 只准脱敏摘要出站）。
"""

from __future__ import annotations

from typing import Any

from harness import CaseRun


def _run(state: dict[str, Any]) -> CaseRun:
    return CaseRun(
        case_id="n05",
        question="T_A 的客单价是多少？",
        tenant="T_A",
        identity=object(),  # 本测试只碰 state 派生属性，不用身份
        state=state,
    )


def test_repair_fields_are_read_from_state() -> None:
    run = _run(
        {
            "repair_round": 2,
            "repair_history": (
                {"round": 1, "error_class": "syntax_error", "attempts": 1},
                {"round": 2, "error_class": "syntax_error", "attempts": 1},
            ),
        }
    )
    assert run.repair_round == 2
    assert [item["round"] for item in run.repair_history] == [1, 2]
    assert all("sql" not in item for item in run.repair_history)


def test_absent_repair_fields_are_zero_and_empty() -> None:
    run = _run({})
    assert run.repair_round == 0
    assert run.repair_history == ()
