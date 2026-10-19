"""W60：明确的城市口径不得被 normalize 误判为需澄清。"""
from __future__ import annotations

from app.graph.nodes.normalize import _demote_unambiguous_shop_city_clarification
from app.planner.schemas import IntentKind


def _outcome(question: str, reason_code: str = "ambiguous_dimension_city") -> dict:
    return {
        "normalized_question": question,
        "intent": IntentKind.CLARIFY.value,
        "intent_detail": {"reason_code": reason_code},
    }


def test_group_by_city_is_unambiguous_shop_city() -> None:
    for question in (
        "T_A 的各城市的店铺数分别是多少？",
        "T_A 各城市的在架商品数分别是多少？",
    ):
        got = _demote_unambiguous_shop_city_clarification(_outcome(question), question)
        assert got["intent"] == IntentKind.EXECUTABLE.value
        assert got["intent_detail"]["reason_code"] == "shop_city_unambiguous"


def test_store_city_filter_for_sku_traffic_is_unambiguous() -> None:
    for question in (
        "T_A 在 成都市 的店铺各 SKU 浏览量合计是多少？",
        "T_A 在 南京市的店铺各 SKU 浏览量合计是多少？",
        "T_A 在长沙市的店铺各 SKU 浏览量合计是多少？",
    ):
        got = _demote_unambiguous_shop_city_clarification(_outcome(question), question)
        assert got["intent"] == IntentKind.EXECUTABLE.value


def test_product_count_ambiguity_is_not_demoted() -> None:
    question = "T_A 位于长沙的店铺各有多少个商品？"
    got = _demote_unambiguous_shop_city_clarification(
        _outcome(question), question
    )
    assert got["intent"] == IntentKind.CLARIFY.value


def test_other_or_metric_clarifications_are_not_demoted() -> None:
    cases = (
        ("T_A 从 2026-08-01 起的付费金额合计（含未支付）是多少？", "ambiguous_metric_scope"),
        ("T_A 618 期间各大区各店铺的成交金额合计是多少？", "ambiguous_time"),
        ("城市维度的 GMV 是多少？", "ambiguous_dimension_city"),
    )
    for question, reason in cases:
        got = _demote_unambiguous_shop_city_clarification(_outcome(question, reason), question)
        assert got["intent"] == IntentKind.CLARIFY.value
