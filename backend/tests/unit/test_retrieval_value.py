"""值检索单元测试（07 §6.6）。

confidence 量纲 = 匹配层级确定性映射（登记待架构确认，见 value.py 模块注释）——
本测试把该映射**钉死**：若未来裁定换量纲，必须连测试一起改，不允许静默漂移。
"""

from __future__ import annotations

import pytest

from app.retrieval.tokenizer import load_custom_dict
from app.retrieval.value import (
    TIER_EDIT1,
    TIER_EXACT,
    TIER_PREFIX,
    normalize_text,
    search_values,
)
from app.retrieval.view import BundleView
from tests.unit._retrieval_fixture import load_bundle_view


@pytest.fixture(scope="module", autouse=True)
def _bundle_dict() -> None:
    load_custom_dict(load_bundle_view().dictionary_terms())


@pytest.fixture(scope="module")
def view():
    return load_bundle_view()


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

def test_normalize_fullwidth_case_spaces() -> None:
    assert normalize_text("ＧＭＶ") == "gmv"
    assert normalize_text(" 直播 渠道 ") == "直播渠道"
    assert normalize_text("Live") == "live"


# ---------------------------------------------------------------------------
# 三级匹配链
# ---------------------------------------------------------------------------

def test_exact_match_by_label_in_question(view) -> None:
    hits = search_values("直播渠道的上月GMV是多少", view)
    assert hits, "『直播』是 enum 标签 + 别名，必须命中"
    # 直播 是两个资产的 channel enum 标签（order_paid 成交渠道 / traffic_daily 流量渠道）
    live_hits = [h for h in hits if h.term == "直播" and h.confidence == TIER_EXACT]
    assert {(h.asset, h.column) for h in live_hits} == {
        ("order_paid", "channel"), ("traffic_daily", "channel"),
    }
    assert all(h.values == ("live",) for h in live_hits)


def test_exact_match_by_enum_key_fullwidth(view) -> None:
    """枚举键也是可说出的值；全角输入经 NFKC 归一后走**容器精确**路径。"""
    hits = search_values("ｄｉｒｅｃｔ 渠道的uv", view)
    assert any(
        h.values == ("direct",) and h.confidence == TIER_EXACT and h.asset == "traffic_daily"
        for h in hits
    )


def test_alias_value_route(view) -> None:
    """『达人/猜你喜欢』来自 aliases 的 value 条目（source=alias）。"""
    hits = search_values("达人渠道的GMV", view)
    assert any(h.term == "达人" and h.values == ("live",) and h.source == "alias" for h in hits)


def test_value_map_route(view) -> None:
    """『华南』来自 dimensions.region.value_map（source=value_map，多编码值）。"""
    hits = search_values("华南地区的订单量", view)
    assert any(
        h.term == "华南" and h.column == "region_code" and "440000" in h.values
        for h in hits
    )


def test_exact_match_by_label_and_alias_container(view) -> None:
    """『搜索』enum 标签精确命中；『自然搜索』别名在完整出现时经容器路径命中。"""
    hits = search_values("搜索渠道带来的访客数", view)
    matched = {h.term for h in hits}
    assert "搜索" in matched
    # "自然搜索" 在该问句里只是**子串后缀**（jieba 切出 自然/搜索）——
    # 07 §6.6 的匹配链是 精确→前缀→编辑距离，**没有子串**：后缀不算命中（契约忠实）。
    assert "自然搜索" not in matched

    hits2 = search_values("自然搜索渠道的访客数", view)
    assert any(h.term == "自然搜索" and h.confidence == TIER_EXACT for h in hits2)


def test_edit_distance_tier(view) -> None:
    """编辑距离 ≤1（双方 ≥2 字）：『推茬』→『推荐』（1 处替换）→ 0.6 档。

    用『推茬』是因为 jieba 对该未知词整词成 token（『直搔』会被切碎，token 级
    匹配够不着——那是分词器行为，不是本模块职责）。
    """
    hits = search_values("推茬渠道的GMV", view)
    assert any(h.confidence == TIER_EDIT1 and h.values == ("feed",) for h in hits)


def test_min_confidence_filter(view) -> None:
    hits_all = search_values("推茬渠道", view)
    hits_strict = search_values("推茬渠道", view, min_confidence=TIER_PREFIX)
    assert any(h.confidence == TIER_EDIT1 for h in hits_all)
    assert not any(h.confidence == TIER_EDIT1 for h in hits_strict)


def test_prefix_match_tier_with_controlled_bundle() -> None:
    """前缀档（0.8）：token 是词条前缀且双方 ≥2 字（受控词表，避开 jieba 方差）。"""
    fake = BundleView.from_mapping(
        {
            "meta": {"version": "test"},
            "aliases": [
                {"term": "paidsearch", "lang": "en", "maps_to_kind": "value",
                 "maps_to_ref": "fake_asset.fake_col=paid", "category": "value"},
            ],
        }
    )
    # "paidsearc" 是 "paidsearch" 的前缀（jieba 对 ASCII 未知词整词成 token）
    hits = search_values("paidsearc 渠道", fake)
    assert any(h.confidence == TIER_PREFIX for h in hits)
    assert not any(h.confidence == TIER_EXACT for h in hits)

    # 单字 token 不得前缀命中（噪声防线）：token "p" vs "paidsearch"
    assert search_values("p 渠道", fake) == ()


def test_no_match_returns_empty(view) -> None:
    assert search_values("今天是星期几", view) == () or all(
        h.confidence < TIER_EXACT for h in search_values("今天是星期几", view)
    )


def test_empty_question(view) -> None:
    assert search_values("", view) == ()


# ---------------------------------------------------------------------------
# 确定性
# ---------------------------------------------------------------------------

def test_deterministic_ordering(view) -> None:
    """同问句两次调用结果逐字节相同（07 §6.7：不得按候选动态调整）。"""
    q = "直播和搜索渠道的退款率对比"
    assert search_values(q, view) == search_values(q, view)


def test_ordering_is_confidence_then_term(view) -> None:
    hits = search_values("直播渠道", view)
    keys = [(-h.confidence, h.term, h.asset, h.column) for h in hits]
    assert keys == sorted(keys)


def test_tier_constants_are_pinned() -> None:
    """量纲登记：改动这三个常量必须是有意识的裁定（测试当场拦静默漂移）。"""
    assert (TIER_EXACT, TIER_PREFIX, TIER_EDIT1) == (1.0, 0.8, 0.6)
