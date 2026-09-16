"""Join 图扩展单元测试（07 §6.5）。"""

from __future__ import annotations

import pytest

from app.retrieval.graph import GRAPH_ADDED_BY, MAX_HOPS, expand_join_graph
from tests.unit._retrieval_fixture import load_bundle_view


@pytest.fixture(scope="module")
def view():
    return load_bundle_view()


def test_max_hops_constant_pinned() -> None:
    assert MAX_HOPS == 2


def test_one_hop_expansion(view) -> None:
    """order_paid 已命中 → 1 跳补 product/shop/region/order_refund/dim_date。"""
    hits = expand_join_graph(("order_paid",), view)
    one_hop = {h.asset for h in hits if h.hop == 1}
    assert {"product", "shop", "region", "order_refund", "dim_date"} <= one_hop


def test_two_hop_reaches_campaign_via_u28_path(view) -> None:
    """U-28 两跳路径：order_paid → dim_date → campaign 必须可达且 hop=2。"""
    hits = expand_join_graph(("order_paid",), view)
    campaign_hits = [h for h in hits if h.asset == "campaign"]
    assert campaign_hits, "campaign 必须经 dim_date 两跳可达（07 §4.7.1 裁定）"
    h = campaign_hits[0]
    assert h.hop == 2
    assert [edge.left_asset for edge in h.path] == ["order_paid", "dim_date"]
    assert [edge.right_asset for edge in h.path] == ["dim_date", "campaign"]
    assert h.added_by == GRAPH_ADDED_BY


def test_u28_edges_carry_danger_notes(view) -> None:
    """两跳的两条边都带危险 note（校验器断言的对应物：检索侧不得丢弃归因）。"""
    notes = {
        (e.left_asset, e.right_asset): e.note
        for e in view.joins
        if e.left_asset == "dim_date" or e.right_asset == "dim_date"
    }
    assert notes[("order_paid", "dim_date")] and "date(order_paid.pay_time)" in notes[
        ("order_paid", "dim_date")
    ]
    assert notes[("dim_date", "campaign")] and "租户谓词" in notes[("dim_date", "campaign")]


def test_start_assets_not_in_results(view) -> None:
    hits = expand_join_graph(("order_paid",), view)
    assert all(h.asset != "order_paid" for h in hits)


def test_no_start_asset_no_hits(view) -> None:
    assert expand_join_graph((), view) == ()


def test_unknown_start_asset_ignored(view) -> None:
    """不在包内的起点忽略（未认证资产不可作为扩展源——§6.5 的结构性落实）。"""
    assert expand_join_graph(("no_such_asset",), view) == ()


def test_unconnected_asset_yields_nothing(view) -> None:
    """dim_date 与 traffic 无直连（流量侧有 stat_date 边除外）——用孤立起点验证。

    真实包内所有资产都至少一条边相连，故这里验证的是"搜索不到就空"的行为面。
    """
    hits = expand_join_graph(("campaign",), view, max_hops=0)
    assert hits == ()


def test_deterministic_ordering(view) -> None:
    a = expand_join_graph(("order_paid", "traffic_daily"), view)
    b = expand_join_graph(("traffic_daily", "order_paid"), view)
    # 起点集合相同 → 结果相同（起点顺序不影响：visited 集合 + 稳定排序）
    assert [h.asset for h in a] == [h.asset for h in b]
    keys = [(h.hop, h.asset) for h in a]
    assert keys == sorted(keys)


def test_max_hops_param_is_respected(view) -> None:
    one_hop_only = expand_join_graph(("order_paid",), view, max_hops=1)
    assert all(h.hop == 1 for h in one_hop_only)
    assert not any(h.asset == "campaign" for h in one_hop_only)
