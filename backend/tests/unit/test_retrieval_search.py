"""四路编排门面（search.py）单元测试 —— 降级如实、mode 回填、缓存边界、租户传递。

核心红线：
- N-21：稠密不可用 → 显式降级载荷，绝不静默；
- C-11：结果 mode = 实际执行档；
- N-10：tenant/bundle_version 必须传到 SQL 层（夹具内断言，不代填）。
"""

from __future__ import annotations

from app.core.enums import RetrievalMode
from app.retrieval.dense import EmbeddingUnavailable, InMemoryVectorStore, l2_normalize
from app.retrieval.search import RetrievalService
from app.retrieval.sparse import SparseSearch
from tests.unit._retrieval_fixture import (
    FakeCache,
    RecordingFetcher,
    load_bundle_view,
    make_identity,
)

BUNDLE_VERSION = "2026.09.14.1"


class FakeEmbedder:
    """固定向量替身（embed() 合同与 OllamaEmbedder 一致）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    async def embed(self, texts):
        self.calls += 1
        if self._fail:
            raise EmbeddingUnavailable("fake: ollama down")
        # 每个文本给一个由文本哈希决定方向的稳定向量（dim=8 无所谓，替身自洽即可）
        return [l2_normalize([1.0, float(len(t) % 7) + 1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]) for t in texts]


def sparse_rows_for(refs: list[str]) -> list[dict]:
    return [{"doc_id": str(i), "ref": r, "kind": "asset", "score": 0.5} for i, r in enumerate(refs)]


def make_service(*, embedder, sparse_rows=(), cache=None, vector_store=None):
    """构造服务，返回 (service, fetcher)。fetcher 供测试断言收到的参数。"""
    view = load_bundle_view()
    fetcher = RecordingFetcher(sparse_rows)
    weights = {"dense": 0.40, "sparse": 0.35, "value": 0.15, "graph": 0.10}
    service = RetrievalService(
        view=view,
        embedder=embedder,
        vector_store=vector_store or InMemoryVectorStore(),
        sparse=SparseSearch(fetcher, rank_normalization=32, score_min=0.05),
        weights=weights,
        rrf_k=60,
        cache=cache,
    )
    return service, fetcher


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------

async def test_value_hits_flow_through() -> None:
    service, _ = make_service(embedder=FakeEmbedder(), sparse_rows=sparse_rows_for([]))
    result = await service.search_full("直播渠道的上月GMV", make_identity(), RetrievalMode.HYBRID)
    assert result.mode == RetrievalMode.HYBRID
    assert not result.degraded
    assert any(h.values == ("live",) for h in result.value_hits)
    # GMV 相关资产应进资产级候选
    asset_ids = {c.asset_id for c in result.candidates}
    assert "order_paid" in asset_ids or "traffic_daily" in asset_ids


async def test_sparse_hits_reach_fusion_and_tenant_is_passed() -> None:
    service, fetcher = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"])
    )
    result = await service.search_full("订单分析", make_identity("T_B"), RetrievalMode.HYBRID)
    assert any(c.asset_id == "order_paid" for c in result.candidates)
    # 夹具内断言：tenant/version 逐字到达取数层（N-10）
    _sql, params = fetcher.calls[0]
    assert params["tenant_id"] == "T_B"
    assert params["bundle_version"] == BUNDLE_VERSION


async def test_graph_extension_adds_bridge_assets() -> None:
    """sparse 只命中 order_paid → graph 补桥接资产（如 dim_date/product）。"""
    service, _ = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"])
    )
    result = await service.search_full("订单分析", make_identity(), RetrievalMode.SPARSE_ONLY)
    assert result.graph_hits, "种子 order_paid 必产生图扩展"
    graph_assets = {h.asset for h in result.graph_hits}
    assert "campaign" in graph_assets  # U-28 两跳
    assert any(c.asset_id == "order_paid" for c in result.candidates)


async def test_contract_port_returns_candidate_refs() -> None:
    service, _ = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid", "product"])
    )
    refs = await service.search("订单分析", make_identity(), RetrievalMode.SPARSE_ONLY)
    assert refs
    for ref in refs:
        assert ref.asset_id
        assert ref.score > 0
    scores = [r.score for r in refs]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 降级（DoD③ 的单测 half；集成 half 见 tests/integration）
# ---------------------------------------------------------------------------

async def test_embedding_down_yields_explicit_degradation() -> None:
    """N-21 / C-11：稠密不可用 → sparse_only + 降级载荷，绝不静默。"""
    service, _ = make_service(
        embedder=FakeEmbedder(fail=True), sparse_rows=sparse_rows_for(["order_paid"])
    )
    result = await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    assert result.mode == RetrievalMode.SPARSE_ONLY
    assert result.degraded
    assert str(result.degraded_reason) == "embedding_unavailable"
    assert str(result.action_taken) == "sparse_only"
    assert result.candidates  # 降级不是空结果


async def test_requested_sparse_only_never_calls_embedder() -> None:
    embedder = FakeEmbedder()
    service, _ = make_service(embedder=embedder, sparse_rows=sparse_rows_for(["order_paid"]))
    result = await service.search_full("订单分析", make_identity(), RetrievalMode.SPARSE_ONLY)
    assert embedder.calls == 0
    assert result.mode == RetrievalMode.SPARSE_ONLY
    assert not result.degraded  # 请求就是 sparse_only，没有发生"降级"


async def test_empty_question_short_circuits() -> None:
    service, _ = make_service(embedder=FakeEmbedder(), sparse_rows=[])
    result = await service.search_full("   ", make_identity(), RetrievalMode.HYBRID)
    assert result.candidates == ()
    assert not result.degraded


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

async def test_cache_hit_skips_routes_and_roundtrips_graph_hits() -> None:
    embedder = FakeEmbedder()
    service, _ = make_service(
        embedder=embedder,
        sparse_rows=sparse_rows_for(["order_paid"]),
        cache=FakeCache(),
    )
    first = await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    calls_after_first = embedder.calls
    assert first.graph_hits

    second = await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    assert embedder.calls == calls_after_first  # 第二轮零 embed 调用
    assert second == first  # 逐字段相等（含图命中重建）


async def test_degraded_round_is_not_cached() -> None:
    """决策记录：降级轮不写缓存（不把临时降级固化 1 小时）。"""
    cache = FakeCache()
    service, _ = make_service(
        embedder=FakeEmbedder(fail=True),
        sparse_rows=sparse_rows_for(["order_paid"]),
        cache=cache,
    )
    await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    assert cache.set_calls == 0

    # 恢复后同一问句正常写入缓存
    service_ok, _ = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"]), cache=cache
    )
    await service_ok.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    assert cache.set_calls == 1
