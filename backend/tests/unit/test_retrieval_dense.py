"""稠密检索单元测试（07 §6.3）—— 批量分片、重试退避、L2 归一化、向量缓存。

全部离线：HTTP 用 `httpx.MockTransport`，退避注入计数函数（不真 sleep，N-01）。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.retrieval.dense import (
    EMBED_BATCH_SIZE,
    EmbeddingUnavailable,
    InMemoryVectorStore,
    OllamaEmbedder,
    PgVectorStore,
    l2_normalize,
)
from tests.unit._retrieval_fixture import FakeCache

DIM = 4


def make_vector(seed: float) -> list[float]:
    return [seed, 1.0, 0.0, 0.0]


def make_embedder(
    handler,
    *,
    cache=None,
    backoff=None,
) -> OllamaEmbedder:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaEmbedder(
        base_url="http://ollama.test",
        model="bge-m3",
        dim=DIM,
        timeout_s=1,
        cache=cache,
        client=client,
        backoff=backoff or (lambda _s: asyncio.sleep(0)),
    )


def ok_handler(calls: list[int], vectors_for_first_text: dict[str, list[float]]):
    """200 应答器：记录每批文本，按文本首词回固定向量。"""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        texts = json.loads(request.content)["input"]
        return httpx.Response(
            200, json={"embeddings": [vectors_for_first_text.get(t, make_vector(0.5)) for t in texts]}
        )

    return handler


# ---------------------------------------------------------------------------
# l2_normalize
# ---------------------------------------------------------------------------

def test_l2_normalize_unit_vector() -> None:
    v = l2_normalize([3.0, 4.0])
    assert sum(x * x for x in v) == pytest.approx(1.0)
    assert v[0] == pytest.approx(0.6)
    assert v[1] == pytest.approx(0.8)


def test_l2_normalize_zero_vector_safe() -> None:
    assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]


# ---------------------------------------------------------------------------
# embed：分片 / 归一化 / 维度校验
# ---------------------------------------------------------------------------

async def test_embed_batches_at_32() -> None:
    calls: list[int] = []
    seen_batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        seen_batch_sizes.append(len(json.loads(request.content)["input"]))
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"embeddings": [make_vector(0.1) for _ in texts]})

    embedder = make_embedder(handler)
    vectors = await embedder.embed([f"t{i}" for i in range(EMBED_BATCH_SIZE + 8)])

    assert len(calls) == 2
    assert seen_batch_sizes == [EMBED_BATCH_SIZE, 8]
    assert len(vectors) == EMBED_BATCH_SIZE + 8


async def test_embed_normalizes_and_validates_dim() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        texts = json.loads(request.content)["input"]
        # 返回未归一化的 [1,1,0,0]
        return httpx.Response(200, json={"embeddings": [[1.0, 1.0, 0.0, 0.0] for _ in texts]})

    embedder = make_embedder(handler)
    vectors = await embedder.embed(["问句"])
    assert sum(x * x for x in vectors[0]) == pytest.approx(1.0)


async def test_embed_dim_mismatch_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"embeddings": [[0.0] * 7 for _ in texts]})

    with pytest.raises(EmbeddingUnavailable, match="维度不符"):
        await make_embedder(handler).embed(["问句"])


# ---------------------------------------------------------------------------
# embed：重试与降级
# ---------------------------------------------------------------------------

async def test_retry_once_then_succeed() -> None:
    calls: list[int] = []
    backoffs: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("first attempt fails")
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"embeddings": [make_vector(0.3) for _ in texts]})

    embedder = make_embedder(handler, backoff=lambda s: _record(s, backoffs))
    vectors = await embedder.embed(["问句"])
    assert len(calls) == 2
    assert backoffs == [1.0]  # 07 §6.3：重试 1 次，退避 1s
    assert len(vectors) == 1


async def _record(seconds: float, sink: list[float]) -> None:
    sink.append(seconds)


async def test_retry_exhausted_raises_unavailable() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("always down")

    with pytest.raises(EmbeddingUnavailable, match="重试 1 次后仍失败"):
        await make_embedder(handler).embed(["问句"])
    assert len(calls) == 2  # 恰好 1 次重试（不是无限重试）


async def test_http_500_also_retries_then_fails() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500)

    with pytest.raises(EmbeddingUnavailable):
        await make_embedder(handler).embed(["问句"])
    assert len(calls) == 2


async def test_malformed_response_shape_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": "not-a-list"})

    with pytest.raises(EmbeddingUnavailable, match="形状异常"):
        await make_embedder(handler).embed(["问句"])


# ---------------------------------------------------------------------------
# 向量缓存
# ---------------------------------------------------------------------------

async def test_cache_hit_skips_network() -> None:
    calls: list[int] = []
    cached_text = "已缓存的问句"
    raw_vector = make_vector(0.7)
    cache = FakeCache()

    embedder = make_embedder(ok_handler(calls, {cached_text: raw_vector}), cache=cache)
    first = await embedder.embed([cached_text])
    assert calls == [1]
    assert cache.set_calls == 1

    # 第二次：命中缓存，不再发请求；回填的是**归一化后**的向量（缓存写的就是它）
    again = await embedder.embed([cached_text])
    assert calls == [1]
    assert again == first == [l2_normalize(raw_vector)]


async def test_cache_partial_hit_only_requests_missing() -> None:
    calls: list[int] = []
    vector = make_vector(0.9)
    cache = FakeCache()
    embedder = make_embedder(ok_handler(calls, {}), cache=cache)

    # 手动预热一条
    from app.cache.keys import embedding as embedding_key

    await cache.set(
        embedding_key("bge-m3", DIM, "命中文本"),
        json.dumps(vector),
        ttl_s=60,
    )
    result = await embedder.embed(["命中文本", "未命中文本"])
    assert len(calls) == 1
    assert result[0] == vector  # 命中的按原样回填
    assert sum(x * x for x in result[1]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# InMemoryVectorStore（替身）与 PgVectorStore
# ---------------------------------------------------------------------------

async def test_inmemory_store_filters_tenant_and_version() -> None:
    store = InMemoryVectorStore()
    query = l2_normalize([1.0, 0.0, 0.0, 0.0])
    store.add(ref="a", kind="asset", tenant_id="T_A", bundle_version="v1", vector=query)
    store.add(ref="b", kind="asset", tenant_id="T_B", bundle_version="v1", vector=query)
    store.add(ref="c", kind="asset", tenant_id="T_A", bundle_version="v2", vector=query)
    hits = await store.topk(query, tenant_id="T_A", bundle_version="v1", limit=10)
    assert [h.ref for h in hits] == ["a"]  # N-10：过滤在"查询内"完成


async def test_inmemory_store_ordering() -> None:
    store = InMemoryVectorStore()
    strong = l2_normalize([1.0, 0.1, 0.0, 0.0])
    weak = l2_normalize([0.1, 1.0, 0.0, 0.0])
    query = l2_normalize([1.0, 0.0, 0.0, 0.0])
    store.add(ref="weak", kind="asset", tenant_id="T", bundle_version="v", vector=weak)
    store.add(ref="strong", kind="asset", tenant_id="T", bundle_version="v", vector=strong)
    hits = await store.topk(query, tenant_id="T", bundle_version="v", limit=2)
    assert [h.ref for h in hits] == ["strong", "weak"]


async def test_pg_store_passes_params_and_parses_rows() -> None:
    captured: dict[str, object] = {}

    async def fetch(sql: str, params: dict[str, object]):
        captured["sql"] = sql
        captured["params"] = params
        return [
            {"ref": "order_paid", "kind": "asset", "score": 0.93},
            {"ref": "traffic_daily.channel", "kind": "column", "score": 0.71},
        ]

    store = PgVectorStore(fetch)
    hits = await store.topk(
        [1.0, 0.0, 0.0, 0.0], tenant_id="T_A", bundle_version="2026.09.14.1", limit=5
    )
    assert "app.embed_doc" in captured["sql"]
    assert "tenant_id IN (:tenant_id, '*')" in captured["sql"]
    assert "bundle_version = :bundle_version" in captured["sql"]
    params = captured["params"]
    assert params["tenant_id"] == "T_A"
    assert params["bundle_version"] == "2026.09.14.1"
    assert params["limit"] == 5
    assert [(h.ref, h.kind, h.score) for h in hits] == [
        ("order_paid", "asset", 0.93),
        ("traffic_daily.channel", "column", 0.71),
    ]


# ---------------------------------------------------------------------------
# U-112 形态 (ii)：向量列未物化（NULL 分数）
#
# `1 - (embedding <=> vec)` 在 `embedding IS NULL` 时是 **NULL**（不是 0）。
# 旧实现 `score=float(row["score"])` 无条件转换 ⇒ `TypeError` ⇒ 逃出图 ⇒
# runner 兜底 `error(INTERNAL)`（W7 2026-09-21 活体栈实测）。
# 现须转成与形态 (i) 同款的 `EmbeddingUnavailable`（07 §5.3 行 4 的降级出口）。
# ---------------------------------------------------------------------------

def store_with_rows(rows: list[dict]) -> PgVectorStore:
    """分数形态由用例给定（含 None），专门用来钉 NULL 分支。"""

    async def fetch(sql: str, params: dict) -> list[dict]:
        return rows

    return PgVectorStore(fetch)


async def test_pg_store_all_null_scores_raises_unavailable() -> None:
    """作用域内有行但零条可用向量 ⇒ 抛 `EmbeddingUnavailable`（空向量列）。"""
    store = store_with_rows([
        {"ref": "order_paid", "kind": "asset", "score": None},
        {"ref": "product", "kind": "asset", "score": None},
    ])
    with pytest.raises(EmbeddingUnavailable, match="全为 NULL"):
        await store.topk([1.0, 0.0, 0.0, 0.0], tenant_id="T_A", bundle_version="v1", limit=5)


async def test_pg_store_keeps_valid_rows_and_drops_null_ones() -> None:
    """部分 NULL：有效向量照常返回、**不降级**。

    "向量列到底有没有数"由 `U-111` 的**启动断言**播报 —— 读路径不重复判
    （一条判据两个落点 = 本项目已 4 次实锤的病害）。
    """
    store = store_with_rows([
        {"ref": "order_paid", "kind": "asset", "score": 0.93},
        {"ref": "dim_date", "kind": "asset", "score": None},
        {"ref": "product", "kind": "asset", "score": 0.4},
    ])
    hits = await store.topk([1.0, 0.0, 0.0, 0.0], tenant_id="T_A", bundle_version="v1", limit=5)
    assert [(h.ref, h.score) for h in hits] == [("order_paid", 0.93), ("product", 0.4)]


async def test_pg_store_empty_scope_is_not_degradation() -> None:
    """作用域内一行都没有（空 KB / 该版本无文档）⇒ 如实返空，**不得**冒充降级。

    否则 `retrieval_mode=sparse_only` 的降级率会掺进"没数据"的假信号，而
    07 把它当 Ollama 软依赖的真实健康度指标用。
    """
    hits = await store_with_rows([]).topk(
        [1.0, 0.0, 0.0, 0.0], tenant_id="T_A", bundle_version="v1", limit=5
    )
    assert hits == []


async def test_pg_store_zero_score_is_not_treated_as_null() -> None:
    """**0.0 是合法分数**（正交向量 ⇒ 余弦相似度 0）—— 别把 falsy 当 NULL 丢。

    钉这个是因为"顺手写 `if not score`"是这类修复最常见的回归形态。
    """
    hits = await store_with_rows([{"ref": "unrelated", "kind": "asset", "score": 0.0}]).topk(
        [1.0, 0.0, 0.0, 0.0], tenant_id="T_A", bundle_version="v1", limit=5
    )
    assert [(h.ref, h.score) for h in hits] == [("unrelated", 0.0)]
