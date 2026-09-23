"""四路编排门面（search.py）单元测试 —— 降级如实、mode 回填、缓存边界、租户传递。

核心红线：
- N-21：稠密不可用 → 显式降级载荷，绝不静默；
- C-11：结果 mode = 实际执行档；
- N-10：tenant/bundle_version 必须传到 SQL 层（夹具内断言，不代填）；
- RL-2：`retrieval_mode_total` 的分母 = **真的尝试过 embedding 的轮次**，
  标签 = **实际**执行档（记请求档会让降级率永远为 0）。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.enums import RetrievalMode
from app.obs import metrics
from app.obs.metrics import RETRIEVAL_MODE_TOTAL
from app.retrieval.dense import (
    EmbeddingUnavailable,
    InMemoryVectorStore,
    PgVectorStore,
    l2_normalize,
)
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


@pytest.fixture(autouse=True)
def _clean_metrics() -> Iterator[None]:
    """RL-2 计数断言必须与执行顺序无关。

    指标是**模块级全局状态**（这正是 counter 的语义），跨用例残留会让
    `... == 1` 这类断言依赖执行顺序 —— 与 `tests/conftest.py` 复位 τ gauge 同因。
    用仓内公共助手（`reset_for_tests` 清样本、**保留声明**），不碰私有 `_reset`。
    """
    metrics.reset_for_tests()
    yield
    metrics.reset_for_tests()


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


async def test_vector_column_not_materialized_degrades_not_internal() -> None:
    """`U-112` 形态 (ii)：向量列未物化（分数全 NULL）—— 必须降级，不得抛出去。

    与上面的 `test_embedding_down_yields_explicit_degradation`（形态 (i)：
    Ollama 不通）**成对**：07 §5.3 行 4 的 v1.6 判据要求"两形态同一出口"。
    只修 (i) 会留下静默/500 形态 —— 那正是 W7 那 2 条 `INTERNAL` 的形状。
    """

    async def fetch_rows(sql: str, params: dict) -> list[dict]:
        return [{"ref": "order_paid", "kind": "asset", "score": None}]

    service, _ = make_service(
        embedder=FakeEmbedder(),
        sparse_rows=sparse_rows_for(["order_paid"]),
        vector_store=PgVectorStore(fetch_rows),
    )
    result = await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    assert result.mode == RetrievalMode.SPARSE_ONLY
    assert result.degraded
    assert str(result.degraded_reason) == "embedding_unavailable"
    assert str(result.action_taken) == "sparse_only"
    assert result.candidates  # 稀疏路仍有结果 ⇒ 不是"空降级"


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


# ---------------------------------------------------------------------------
# RL-2 接线：检索模式分布（`retrieval_mode_total`，本模块 = 唯一调用点）
#
# 判据形态（指标自身 help_text 写的）：`{retrieval_mode="sparse_only"} / 全体`
# = embedding 降级率。接线前它是 **0/0**（本体在、无调用点）⇒ 不可当证据引用。
# ---------------------------------------------------------------------------

async def test_hybrid_round_counts_hybrid() -> None:
    """健康轮：记 `hybrid`，且只记一次。"""
    service, _ = make_service(embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"]))
    result = await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    assert result.mode == RetrievalMode.HYBRID
    assert RETRIEVAL_MODE_TOTAL.value(retrieval_mode="hybrid") == 1
    assert RETRIEVAL_MODE_TOTAL.total() == 1


async def test_dense_failure_counts_effective_mode_not_requested() -> None:
    """★ 正向对照（arch RELAY 要求"注入一次必红、还原必绿"）：降级轮记**实际**档。

    请求 HYBRID、稠密失败 ⇒ 实际执行 `sparse_only` ⇒ 序列必须落在 `sparse_only`。
    把请求档记进去就是 C-11 说的撒谎（`link.py` 同一理由要求 `meta.retrieval_mode`
    如实回填）—— 那样降级率永远是 0，正好是 RL-2 要发现的病被抹掉。
    反向对照：把 `observe_retrieval_mode` 那一行删掉 ⇒ `observed()` 为 False、本用例必红。
    """
    service, _ = make_service(
        embedder=FakeEmbedder(fail=True), sparse_rows=sparse_rows_for(["order_paid"])
    )
    result = await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    assert result.mode == RetrievalMode.SPARSE_ONLY  # 请求 hybrid、实际 sparse_only
    assert RETRIEVAL_MODE_TOTAL.value(retrieval_mode="sparse_only") == 1
    assert RETRIEVAL_MODE_TOTAL.value(retrieval_mode="hybrid") == 0
    assert RETRIEVAL_MODE_TOTAL.observed() is True


async def test_degradation_ratio_is_computable() -> None:
    """判据本身：健康 1 轮 + 降级 1 轮 ⇒ `sparse_only / 全体 = 1/2`（可算、非 0/0）。"""
    healthy, _ = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"])
    )
    await healthy.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)

    down, _ = make_service(
        embedder=FakeEmbedder(fail=True), sparse_rows=sparse_rows_for(["order_paid"])
    )
    await down.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)

    assert RETRIEVAL_MODE_TOTAL.total() == 2
    ratio = RETRIEVAL_MODE_TOTAL.value(retrieval_mode="sparse_only") / RETRIEVAL_MODE_TOTAL.total()
    assert ratio == 0.5


async def test_void_round_and_cache_hit_are_not_counted() -> None:
    """两条早退**刻意不计** —— 分母口径 = **真的尝试过 embedding 的轮次**。

    空问题轮：没有发生检索，计进去会把降级率**稀释**成"含空问的比率"。
    缓存命中轮：复用健康期写入的结果，**不可能降级**，计进去同样稀释分母；
    而"embedding 挂了但被缓存兜住"的轮次在用户侧**无影响** ⇒ 不该污染依赖健康度读数。
    ⚠️ 已知副作用（有意，已在 `search.py` docstring 登记）：本指标**看不见**被缓存
    兜住的降级轮。若将来要度量"用户侧感受不到的降级"，那是另一个指标的事。
    """
    cache = FakeCache()
    service, _ = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"]), cache=cache
    )

    await service.search_full("   ", make_identity(), RetrievalMode.HYBRID)  # 空问题轮
    assert RETRIEVAL_MODE_TOTAL.observed() is False, "空问题轮不得产生任何序列"

    await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)  # 真检索轮
    assert RETRIEVAL_MODE_TOTAL.total() == 1

    await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)  # 缓存命中轮
    assert cache.set_calls == 1  # 确认第二轮真的走了缓存命中（而不是又跑了一遍）
    assert RETRIEVAL_MODE_TOTAL.total() == 1, "缓存命中轮不得再计一次"


async def test_contract_face_search_counts_exactly_once() -> None:
    """`search()` = `search_full()` 的薄封装 ⇒ **恰好一次**（防"两边都埋点"造成 2×）。"""
    service, _ = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"])
    )
    await service.search("订单分析", make_identity(), RetrievalMode.SPARSE_ONLY)
    assert RETRIEVAL_MODE_TOTAL.total() == 1
    assert RETRIEVAL_MODE_TOTAL.value(retrieval_mode="sparse_only") == 1


async def test_metric_is_actually_exported_after_a_round() -> None:
    """导出面自证：跑完一轮后 `/metrics` 文本里**真的出现**这条序列。

    与上面几条"计数"断言**分开**的理由：本项目被"计数 ≠ 可读"咬过一次
    （物化 197 行、向量却全 NULL）⇒ 内部计数为 1 **不自动等于**导出面可读。
    这一条顺手把标签取值格式钉死（必须等于 `RetrievalMode` 的 `.value`）。
    """
    service, _ = make_service(embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"]))
    await service.search_full("订单分析", make_identity(), RetrievalMode.HYBRID)
    text = metrics.render_prometheus_text()
    assert 'retrieval_mode_total{retrieval_mode="hybrid"} 1' in text


async def test_requested_sparse_only_is_indistinguishable_in_the_metric() -> None:
    """⚠️ 口径边界（我主动登记，不靠"没人会这么调"糊过去）。

    **请求档** SPARSE_ONLY 与**降级**出来的 SPARSE_ONLY 在指标里同标签、不可区分。
    现在可接受的理由（已核，非假设）：生产唯一调用点是
    `app/graph/nodes/link.py:61` 的 `_REQUESTED_MODE = RetrievalMode.HYBRID`（写死）
    ⇒ 线上 `sparse_only` 序列**只可能**来自降级。
    风险：若将来 eval / A-B / fast-mode 拿**真** `RetrievalService` 请求 SPARSE_ONLY，
    该序列立刻变成"请求 + 降级"混合 = **假分子**（本项目已两次栽在假分子/假分母上）。
    ⇒ 届时二选一：加区分标签（需架构裁定）或把这类调用导到不注册指标的替身。
    """
    service, _ = make_service(
        embedder=FakeEmbedder(), sparse_rows=sparse_rows_for(["order_paid"])
    )
    result = await service.search_full("订单分析", make_identity(), RetrievalMode.SPARSE_ONLY)
    assert result.mode == RetrievalMode.SPARSE_ONLY
    assert not result.degraded  # 没有发生降级……
    assert RETRIEVAL_MODE_TOTAL.value(retrieval_mode="sparse_only") == 1  # ……但计数相同
