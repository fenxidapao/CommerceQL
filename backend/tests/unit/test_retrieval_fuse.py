"""融合与截断单元测试（07 §6.7）—— RRF 数学、降级重分配确定性、截断。"""

from __future__ import annotations

import pytest

from app.retrieval.fuse import (
    ROUTE_DENSE,
    ROUTE_GRAPH,
    ROUTE_SPARSE,
    ROUTE_VALUE,
    effective_weights,
    rrf_fuse,
    top_n,
)

#: 07 §6.7 的默认四路权重（config 默认值同源；此处独立钉死做数学断言）。
DEFAULT_WEIGHTS: dict[str, float] = {
    ROUTE_DENSE: 0.40,
    ROUTE_SPARSE: 0.35,
    ROUTE_VALUE: 0.15,
    ROUTE_GRAPH: 0.10,
}

K = 60


# ---------------------------------------------------------------------------
# effective_weights
# ---------------------------------------------------------------------------

def test_full_mode_keeps_weights() -> None:
    w = effective_weights(DEFAULT_WEIGHTS, dense_available=True)
    assert w == DEFAULT_WEIGHTS
    assert sum(w.values()) == pytest.approx(1.0)


def test_sparse_only_redistribution_exact_values() -> None:
    """07 §6.7 定案：dense 的 0.40 按 0.35:0.10 比例分给 sparse/graph。"""
    w = effective_weights(DEFAULT_WEIGHTS, dense_available=False)
    assert w[ROUTE_DENSE] == 0.0
    expected_sparse = 0.35 + 0.40 * (0.35 / 0.45)
    expected_graph = 0.10 + 0.40 * (0.10 / 0.45)
    assert w[ROUTE_SPARSE] == pytest.approx(expected_sparse)
    assert w[ROUTE_GRAPH] == pytest.approx(expected_graph)
    assert sum(w.values()) == pytest.approx(1.0)


def test_sparse_only_value_weight_untouched() -> None:
    w = effective_weights(DEFAULT_WEIGHTS, dense_available=False)
    assert w[ROUTE_VALUE] == 0.15


def test_redistribution_is_deterministic() -> None:
    """同一输入两次调用结果完全一致（无随机、无候选依赖）。"""
    a = effective_weights(DEFAULT_WEIGHTS, dense_available=False)
    b = effective_weights(DEFAULT_WEIGHTS, dense_available=False)
    assert a == b


def test_zero_sparse_and_graph_defensive_branch() -> None:
    """sparse/graph 权重同为 0：无处可分 → dense 归零，不抛错。"""
    w = effective_weights({ROUTE_DENSE: 0.4, ROUTE_SPARSE: 0.0, ROUTE_VALUE: 0.6, ROUTE_GRAPH: 0.0},
                          dense_available=False)
    assert w[ROUTE_DENSE] == 0.0
    assert w[ROUTE_VALUE] == 0.6


# ---------------------------------------------------------------------------
# rrf_fuse
# ---------------------------------------------------------------------------

def test_rrf_score_math_exact() -> None:
    """单候选单路由：score = w / (k + rank)。手算值断言。"""
    fused = rrf_fuse(
        {ROUTE_SPARSE: ["order_paid"]}, DEFAULT_WEIGHTS, k=K, dense_available=False
    )
    expected = (0.35 + 0.40 * (0.35 / 0.45)) / (K + 1)
    assert fused[0].score == pytest.approx(expected)


def test_rrf_multi_route_summation() -> None:
    """多路由命中：score = Σ wᵢ/(k+rankᵢ)（07 §6.7 公式原文）。"""
    fused = rrf_fuse(
        {ROUTE_DENSE: ["a", "b"], ROUTE_SPARSE: ["a"]},
        DEFAULT_WEIGHTS,
        k=K,
        dense_available=True,
    )
    a = next(f for f in fused if f.candidate_id == "a")
    b = next(f for f in fused if f.candidate_id == "b")
    assert a.score == pytest.approx(0.40 / (K + 1) + 0.35 / (K + 1))
    assert b.score == pytest.approx(0.40 / (K + 2))
    assert a.score > b.score
    assert a.ranks == {ROUTE_DENSE: 1, ROUTE_SPARSE: 1}
    assert b.ranks == {ROUTE_DENSE: 2}


def test_rrf_rank_starts_at_one() -> None:
    fused = rrf_fuse({ROUTE_GRAPH: ["x", "y"]}, DEFAULT_WEIGHTS, k=K)
    assert fused[0].ranks[ROUTE_GRAPH] == 1
    assert fused[1].ranks[ROUTE_GRAPH] == 2
    assert fused[0].score == pytest.approx(0.10 / (K + 1))


def test_rrf_tie_broken_by_id() -> None:
    """真同分候选按 candidate_id 字典序（不抖动）。

    四路默认权重互不相同，跨候选真同分需要**对称权重**构造：
    m = value rank1 + graph rank2；n = value rank2 + graph rank1，
    value/graph 权重同为 0.5 → 二者得分逐位相同。
    """
    equal_weights = {ROUTE_DENSE: 0.0, ROUTE_SPARSE: 0.0, ROUTE_VALUE: 0.5, ROUTE_GRAPH: 0.5}
    cross = rrf_fuse(
        {ROUTE_VALUE: ["m", "n"], ROUTE_GRAPH: ["n", "m"]}, equal_weights, k=K
    )
    m = next(f for f in cross if f.candidate_id == "m")
    n = next(f for f in cross if f.candidate_id == "n")
    assert m.score == pytest.approx(n.score)  # 对称构造 → 真同分
    ids = [f.candidate_id for f in cross]
    assert ids == sorted(ids)  # 同分 → 字典序，且只有一种可能顺序


def test_rrf_deterministic_across_calls() -> None:
    routes = {ROUTE_DENSE: ["a", "b", "c"], ROUTE_SPARSE: ["c", "a"], ROUTE_VALUE: ["a"]}
    r1 = rrf_fuse(routes, DEFAULT_WEIGHTS, k=K, dense_available=True)
    r2 = rrf_fuse(routes, DEFAULT_WEIGHTS, k=K, dense_available=True)
    assert [(f.candidate_id, f.score, dict(f.ranks)) for f in r1] == [
        (f.candidate_id, f.score, dict(f.ranks)) for f in r2
    ]


def test_rrf_degraded_uses_redistributed_weights() -> None:
    """降级下 dense 路即使缺席，sparse/graph 的名次贡献按重分配权重计。"""
    fused = rrf_fuse(
        {ROUTE_SPARSE: ["a"], ROUTE_GRAPH: ["b"]},
        DEFAULT_WEIGHTS,
        k=K,
        dense_available=False,
    )
    a = next(f for f in fused if f.candidate_id == "a")
    b = next(f for f in fused if f.candidate_id == "b")
    w = effective_weights(DEFAULT_WEIGHTS, dense_available=False)
    assert a.score == pytest.approx(w[ROUTE_SPARSE] / (K + 1))
    assert b.score == pytest.approx(w[ROUTE_GRAPH] / (K + 1))


def test_rrf_invalid_k() -> None:
    with pytest.raises(ValueError, match="k"):
        rrf_fuse({ROUTE_SPARSE: ["a"]}, DEFAULT_WEIGHTS, k=0)


def test_top_n_truncation() -> None:
    fused = rrf_fuse(
        {ROUTE_SPARSE: ["a", "b", "c", "d", "e", "f"]}, DEFAULT_WEIGHTS, k=K,
        dense_available=False,
    )
    assert len(top_n(fused, 5)) == 5
    assert len(top_n(fused, 0)) == 0
    with pytest.raises(ValueError):
        top_n(fused, -1)
