"""W60/W69：明确的城市口径不得被 normalize 误判为需澄清（QA R31bl / R31bm）。

W69-1（R31bm 回滚）：
- 可撤销的澄清理由族**只剩 city**；商品数口径（product_cnt / on_sale_product_cnt /
  spu_cnt）是**真歧义**，必须仍澄清 —— 降级后默认绑 product_cnt、金标要
  on_sale_product_cnt ⇒ 口径错（W68 live 8/8 预测 SQL 缺 `AND v_product.on_sale = 1`）。
- 定语位结构判据保留，但被测主体收窄为「各 SKU …」；商品数尾缀不再构成降级证据
  （r63 实测：杭州 reason=ambiguous_city_dimension、武汉 reason=ambiguous_metric_and_city，
  其 hint 仍含商品数口径问题 —— 若按"理由含 city 就降级"会被误降级）。
"""
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


def test_w60_hangzhou_shop_sku_still_demoted() -> None:
    """W69-③：W60 原用例「在杭州的店铺各 SKU」⇒ 仍 demote。"""
    question = "T_A 在杭州的店铺各 SKU 浏览量合计是多少？"
    got = _demote_unambiguous_shop_city_clarification(
        _outcome(question, "ambiguous_dimension_city"), question
    )
    assert got["intent"] == IntentKind.EXECUTABLE.value
    assert (
        got["intent_detail"]["normalize_original_reason_code"]
        == "ambiguous_dimension_city"
    )


def test_locative_plus_city_family_still_demotes() -> None:
    """W69-④：定语位 + 城市族理由 ⇒ 仍 demote（结构判据对城市族成立）。"""
    question = "T_A 位于广州的店铺各 SKU 浏览量合计是多少？"
    got = _demote_unambiguous_shop_city_clarification(
        _outcome(question, "ambiguous_city_dimension"), question
    )
    assert got["intent"] == IntentKind.EXECUTABLE.value
    assert got["intent_detail"]["reason_code"] == "shop_city_unambiguous"


def test_hstr01_product_count_ambiguity_stays_clarify() -> None:
    """W69-①：H-STR-01 题面（reason=ambiguous_metric_product_cnt）⇒ 恢复 CLARIFY。

    覆盖 4 种实测表面形式：若按"理由含 city 就降级"，city 族两条会被误降级。
    """
    question = "T_A 位于广州的店铺各有多少个商品？"
    for reason in (
        "ambiguous_metric_product_cnt",
        "ambiguous_metric_product_count",
        "ambiguous_city_dimension",
        "ambiguous_metric_and_city",
    ):
        got = _demote_unambiguous_shop_city_clarification(_outcome(question, reason), question)
        assert got["intent"] == IntentKind.CLARIFY.value, reason


def test_hstr_family_product_count_stays_clarify() -> None:
    """H-STR-02…08 同构题面全部保持澄清（商品数口径真歧义）。"""
    for city in ("杭州", "成都", "武汉", "南京", "西安", "长沙", "郑州"):
        question = f"T_A 位于{city}的店铺各有多少个商品？"
        got = _demote_unambiguous_shop_city_clarification(
            _outcome(question, "ambiguous_metric_product_cnt"), question
        )
        assert got["intent"] == IntentKind.CLARIFY.value, question


def test_guangzhou_sales_subject_still_clarifies() -> None:
    """W69-②：C-CITY-03「广州的销售额是多少？」⇒ 仍 CLARIFY。"""
    question = "广州的销售额是多少？"
    got = _demote_unambiguous_shop_city_clarification(
        _outcome(question, "ambiguous_dimension_city"), question
    )
    assert got["intent"] == IntentKind.CLARIFY.value
    assert got["intent_detail"]["reason_code"] == "ambiguous_dimension_city"


def test_city_dimension_and_perspective_still_clarify() -> None:
    """W69-②：C-CITY-01 / C-CITY-04 ⇒ 仍 CLARIFY。"""
    cases = (
        ("城市维度的 GMV 是多少？", "ambiguous_dimension_city"),
        ("城市口径下哪个卖得最好？", "ambiguous_dimension_city"),
    )
    for question, reason in cases:
        got = _demote_unambiguous_shop_city_clarification(_outcome(question, reason), question)
        assert got["intent"] == IntentKind.CLARIFY.value, question


def test_time_and_metric_scope_clarifications_are_never_demoted() -> None:
    """W69-⑤：时间 / 口径范围类理由永不 demote（即使题面命中定语位）。"""
    cases = (
        ("T_A 从 2026-08-01 起的付费金额合计（含未支付）是多少？", "ambiguous_metric_scope"),
        ("T_A 618 期间各大区各店铺的成交金额合计是多少？", "ambiguous_time"),
        ("T_A 位于广州的店铺各 SKU 浏览量合计是多少？", "ambiguous_time"),
    )
    for question, reason in cases:
        got = _demote_unambiguous_shop_city_clarification(_outcome(question, reason), question)
        assert got["intent"] == IntentKind.CLARIFY.value, (question, reason)
