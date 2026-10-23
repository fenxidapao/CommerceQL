"""W60/W68：明确的城市口径不得被 normalize 误判为需澄清（QA R31bl 结构判据）。

W68 变更：H-STR 族「位于<城市>的店铺各有多少个商品」由"保持澄清"改为"撤销澄清"
——结构判据 = 「位于/在 … 的店铺」定语位 + 被测主体是逐店聚合的商品数/SKU。
C-CITY 族（城市维度 / 城市名做主语 / 城市口径视角）无定语位，必须仍澄清。
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


def test_hstr01_shop_locative_product_count_is_demoted() -> None:
    """W68：H-STR-01 题面（含商品数口径歧义 reason）⇒ 不再 CLARIFY。"""
    question = "T_A 位于广州的店铺各有多少个商品？"
    got = _demote_unambiguous_shop_city_clarification(
        _outcome(question, "ambiguous_metric_product_cnt"), question
    )
    assert got["intent"] == IntentKind.EXECUTABLE.value
    assert got["intent_detail"]["reason_code"] == "shop_city_unambiguous"
    #: W68-③：新增 demotion 也要保留原始 reason_code 记账。
    assert (
        got["intent_detail"]["normalize_original_reason_code"]
        == "ambiguous_metric_product_cnt"
    )


def test_hstr_family_city_variants_are_demoted() -> None:
    """H-STR-02…08 同构题面全部撤销澄清（不同城市字面）。"""
    for city in ("杭州", "成都", "武汉", "南京", "西安", "长沙", "郑州"):
        question = f"T_A 位于{city}的店铺各有多少个商品？"
        got = _demote_unambiguous_shop_city_clarification(
            _outcome(question, "ambiguous_metric_product_cnt"), question
        )
        assert got["intent"] == IntentKind.EXECUTABLE.value, question


def test_guangzhou_sales_subject_still_clarifies() -> None:
    """C-CITY-03「广州的销售额是多少？」——城市做主语、无店铺定语位 ⇒ 仍 CLARIFY。"""
    question = "广州的销售额是多少？"
    got = _demote_unambiguous_shop_city_clarification(
        _outcome(question, "ambiguous_dimension_city"), question
    )
    assert got["intent"] == IntentKind.CLARIFY.value
    assert got["intent_detail"]["reason_code"] == "ambiguous_dimension_city"


def test_city_dimension_and_perspective_still_clarify() -> None:
    """C-CITY-01 / C-CITY-04 —— 城市维度 / 城市口径视角 ⇒ 仍 CLARIFY。"""
    cases = (
        ("城市维度的 GMV 是多少？", "ambiguous_dimension_city"),
        ("城市口径下哪个卖得最好？", "ambiguous_dimension_city"),
    )
    for question, reason in cases:
        got = _demote_unambiguous_shop_city_clarification(_outcome(question, reason), question)
        assert got["intent"] == IntentKind.CLARIFY.value, question


def test_w60_hangzhou_shop_sku_still_demoted() -> None:
    """W60 原用例「在杭州的店铺各 SKU」⇒ 仍 demote（W68 重构不得回退）。"""
    question = "T_A 在杭州的店铺各 SKU 浏览量合计是多少？"
    got = _demote_unambiguous_shop_city_clarification(
        _outcome(question, "ambiguous_dimension_city"), question
    )
    assert got["intent"] == IntentKind.EXECUTABLE.value
    assert (
        got["intent_detail"]["normalize_original_reason_code"]
        == "ambiguous_dimension_city"
    )


def test_time_and_metric_scope_clarifications_are_not_demoted() -> None:
    """时间/口径范围类澄清理由不在撤销族内（结构性防线，与题面无关也不得覆盖）。"""
    cases = (
        ("T_A 从 2026-08-01 起的付费金额合计（含未支付）是多少？", "ambiguous_metric_scope"),
        ("T_A 618 期间各大区各店铺的成交金额合计是多少？", "ambiguous_time"),
        ("T_A 位于广州的店铺各有多少个商品？", "ambiguous_time"),
    )
    for question, reason in cases:
        got = _demote_unambiguous_shop_city_clarification(_outcome(question, reason), question)
        assert got["intent"] == IntentKind.CLARIFY.value, (question, reason)
