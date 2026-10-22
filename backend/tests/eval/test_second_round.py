"""W8 第 64 轮：G-8 二轮回路（`--second-round`）的判定逻辑，零出站。

覆盖：
* 补答来源只认冻结集的 `clarify_expected.candidates[0]`；
* 非 clarify 终态 / 无候选 ⇒ 不跑二轮（返回 None），且**不改写首轮判定**；
* 「澄清后一次成功」只认 `complete`，基建中断一律不算；
* 汇总计数把二轮的 tokens/cost **单列**，不与首轮混账。
"""

from __future__ import annotations

from typing import Any

import runner


def _clarify_case(case_id: str = "C-CITY-01", candidates: list[str] | None = None) -> dict[str, Any]:
    case: dict[str, Any] = {
        "case_id": case_id,
        "question": "城市维度的 GMV 是多少？",
        "expected_behavior": "clarify",
    }
    if candidates is not None:
        case["clarify_expected"] = {"reason": "两个同 grain 绑定", "candidates": candidates}
    return case


def test_second_round_question_uses_first_candidate() -> None:
    case = _clarify_case(candidates=["order_paid.receiver_city", "shop.city"])
    got = runner.second_round_question(case, "clarify")
    assert got == "城市维度的 GMV 是多少？（补充口径：order_paid.receiver_city）"


def test_second_round_question_skips_non_clarify() -> None:
    case = _clarify_case(candidates=["shop.city"])
    assert runner.second_round_question(case, "complete") is None
    assert runner.second_round_question(case, "refuse") is None
    assert runner.second_round_question(case, None) is None


def test_second_round_question_skips_without_candidates() -> None:
    # 无 `clarify_expected`
    assert runner.second_round_question(_clarify_case(), "clarify") is None
    # 有壳但候选为空 / 全空白
    assert runner.second_round_question(_clarify_case(candidates=[]), "clarify") is None
    assert runner.second_round_question(_clarify_case(candidates=["  "]), "clarify") is None


def test_second_round_success_only_counts_complete() -> None:
    assert runner.second_round_success("complete", None) is True
    assert runner.second_round_success("complete", "cassette_miss: x") is False
    assert runner.second_round_success("clarify", None) is False
    assert runner.second_round_success("refuse", None) is False
    assert runner.second_round_success("error", None) is False
    assert runner.second_round_success(None, None) is False


def test_summarize_counts_second_round_separately() -> None:
    records = [
        {"case_id": "A", "scored": True, "expected_behavior": "clarify", "terminal_event": "clarify",
         "tokens": {"total": 100}, "cost_cny": 0.01,
         "second_round": {"attempted": True, "success": True,
                          "tokens": {"total": 200}, "cost_cny": 0.02}},
        {"case_id": "B", "scored": True, "expected_behavior": "clarify", "terminal_event": "clarify",
         "tokens": {"total": 100}, "cost_cny": 0.01,
         "second_round": {"attempted": True, "success": False,
                          "tokens": {"total": 50}, "cost_cny": 0.005}},
        # 非 clarify：不 attempt
        {"case_id": "C", "scored": True, "expected_behavior": "execute", "terminal_event": "complete",
         "tokens": {"total": 100}, "cost_cny": 0.01, "second_round": None},
    ]
    s = runner.summarize(records)
    assert s["n_second_round_attempted"] == 2
    assert s["n_second_round_success"] == 1
    # 二轮单列：200 + 50
    assert s["second_round_tokens_total"] == 250
    assert abs(s["second_round_cost_cny_total"] - 0.025) < 1e-9
    # 首轮口径不变：只有首轮的 300 tokens
    assert s["tokens_total"] == 300


def test_summarize_without_second_round_flag_is_zero() -> None:
    records = [{"case_id": "A", "scored": True, "expected_behavior": "clarify",
                "terminal_event": "clarify", "tokens": {"total": 10}, "cost_cny": 0.001,
                "second_round": None}]
    s = runner.summarize(records)
    assert s["n_second_round_attempted"] == 0
    assert s["n_second_round_success"] == 0
    assert s["second_round_tokens_total"] == 0
