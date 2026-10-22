"""W8 第 66 轮 C1-2：reporter 接线（G-8 二轮回路）的单测，零出站。

覆盖：
* 带二轮的批次 ⇒ `second_round_loop_available=True`，分子＝`second_round.success`；
* 单轮批次 ⇒ `second_round_loop_available=False`（**仍须为 False**）；
* 开了二轮但没有可补答来源 ⇒ 仍为 False（回路在、这批无可测分子）；
* 分子口径：**二轮回到可执行终态**，不是答案正确率。
"""

from __future__ import annotations

from typing import Any

import reporter as rp


def _rec(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "case_id": "X",
        "expected_behavior": "execute",
        "terminal_event": "complete",
        "verdict": {"equivalent": False},
        "second_round": None,
    }
    base.update(kw)
    return base


def _second(attempted: bool, success: bool) -> dict[str, Any]:
    return {
        "attempted": attempted,
        "success": success,
        "terminal_event": "complete" if success else "clarify",
    }


def test_single_turn_batch_stays_unavailable_for_second_round() -> None:
    """单轮批次（`second_round=None`）⇒ `second_round_loop_available` **仍须为 False**。"""
    c = rp._clarify_counts([
        _rec(case_id="A", expected_behavior="clarify", terminal_event="clarify"),
        _rec(case_id="B", expected_behavior="clarify", terminal_event="complete"),
    ])
    assert c is not None
    assert c["second_round_loop_available"] is False
    assert c["second_round_attempted"] == 0
    assert c["second_round_success"] == 0


def test_second_round_batch_sets_loop_available_and_counts_from_records() -> None:
    """带二轮的批次 ⇒ 标志为 True，计数**从 records 数出来**（不是写死的）。"""
    c = rp._clarify_counts([
        _rec(case_id="A", expected_behavior="clarify", terminal_event="clarify",
             second_round=_second(True, True)),
        _rec(case_id="B", expected_behavior="clarify", terminal_event="clarify",
             second_round=_second(True, False)),
        _rec(case_id="C", expected_behavior="clarify", terminal_event="clarify",
             second_round=_second(True, True)),
    ])
    assert c is not None
    assert c["second_round_loop_available"] is True
    assert c["second_round_attempted"] == 3
    assert c["second_round_success"] == 2
    # 🔴 分子口径 = `second_round.success`（「二轮回到可执行终态」）
    assert c["clarify_then_correct"] == 2


def test_second_round_without_supplement_source_stays_false() -> None:
    """开了二轮但**没有可补答来源** ⇒ 仍是 False（回路在，但这批无可测分子）。"""
    c = rp._clarify_counts([
        _rec(case_id="A", expected_behavior="clarify", terminal_event="clarify",
             second_round={"attempted": False, "reason": "no_supplement_source"}),
    ])
    assert c is not None
    assert c["second_round_loop_available"] is False
    assert c["second_round_attempted"] == 0
    assert c["clarify_then_correct"] == 0


def test_molecule_is_not_answer_correctness() -> None:
    """分子**不**来自首轮 `verdict.equivalent`（那是"没澄清就答对"，与本口径无关）。

    首轮 equivalent=True 的记录**不**进分子；二轮 success=True 的**进**。
    """
    c = rp._clarify_counts([
        # 首轮就等价（但它收口成 clarify，说明这条的 equivalent 无意义）⇒ 不进分子
        _rec(case_id="A", expected_behavior="clarify", terminal_event="clarify",
             verdict={"equivalent": True}, second_round=_second(True, False)),
        # 二轮回到 complete ⇒ 进分子
        _rec(case_id="B", expected_behavior="clarify", terminal_event="clarify",
             verdict={"equivalent": False}, second_round=_second(True, True)),
    ])
    assert c is not None
    assert c["clarify_then_correct"] == 1
