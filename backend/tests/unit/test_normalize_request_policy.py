"""W58：normalize 后的确定性请求策略出口（零 LLM）。"""
from __future__ import annotations

from pathlib import Path

from app.core.enums import RefuseReason
from app.planner.request_policy import preflight_refusal
from app.semantics import SemanticBundleRuntime, load_bundle

_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"


def _semantics() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(_BUNDLE))


def test_refuse_blacklist_term_is_no_data_asset() -> None:
    got = preflight_refusal(
        "淡季的销量是多少？",
        {"reason_code": "ambiguous_time_and_metric"},
        ("淡季", "销量"),
        _semantics(),
    )
    assert got is not None
    assert got.reason == RefuseReason.NO_DATA_ASSET


def test_denied_sensitive_terms_are_refused() -> None:
    semantics = _semantics()
    address = preflight_refusal(
        "给我收货地址明细",
        {"reason_code": "ambiguous_metric_and_grain"},
        ("收货地址明细",),
        semantics,
    )
    assert address is not None and address.reason == RefuseReason.PII_BLOCKED

    margin = preflight_refusal("毛利是多少？", {"reason_code": "unmapped_metric"}, ("毛利",), semantics)
    assert margin is not None and margin.reason == RefuseReason.PII_BLOCKED


def test_external_and_other_scope_terms_are_refused() -> None:
    semantics = _semantics()
    other_shop = preflight_refusal(
        "看看隔壁店铺的销量", {"reason_code": "AMBIGUOUS_SHOP_REFERENCE"}, ("隔壁店铺", "销量"), semantics
    )
    assert other_shop is not None and other_shop.reason == RefuseReason.OUT_OF_SCOPE

    competitor = preflight_refusal(
        "竞品的销量是多少？",
        {"reason_code": "unmapped_metric_and_scope"},
        ("竞品", "销量"),
        semantics,
    )
    assert competitor is not None and competitor.reason == RefuseReason.NO_DATA_ASSET


def test_genuine_clarifications_are_not_refused() -> None:
    semantics = _semantics()
    assert preflight_refusal(
        "城市维度的 GMV 是多少？", {"reason_code": "ambiguous_dimension_city"}, (), semantics
    ) is None
    assert preflight_refusal(
        "华东的销量是多少？",
        {"reason_code": "ambiguous_metric_and_dimension"},
        ("销量",),
        semantics,
    ) is None
