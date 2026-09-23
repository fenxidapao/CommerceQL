"""四路检索编排 —— `RetrievalPort` 的实现（07 附-1 / contracts.RetrievalPort）。

归属窗口：**W2B**。

## 职责边界

- 编排 dense / sparse / value / graph 四路 → RRF 融合 → 截断；
- **mode 如实回填**（C-11）：稠密不可用时结果 `mode=sparse_only` 且携带
  `degraded_reason=embedding_unavailable` / `action_taken=sparse_only` 的载荷——
  **本模块不发 SSE 事件**（事件唯一产出点在 `graph/events.py`，W4），
  只把降级载荷如实交给接线层；
- 结果缓存走 `keys.semantic_retrieval()`（TTL 1h）；**降级轮不写缓存**
  （决策记录：缓存降级结果会把"稠密临时不可用"固化成 1 小时的确定性降级，
  这与降级的临时性语义冲突；缓存的是"本轮实际发生的检索"，两种取舍中
  选了"不放大降级"，如架构有裁定再改）；
- 租户过滤：dense/sparse 的 SQL 层强制（N-10）；value/graph 消费公共语义包，
  无租户维度数据（见 value.py 模块注释）。
- **检索模式埋点**（`retrieval_mode_total`，本模块是**唯一**调用点，RL-2 的缺口就在这一行）：
  只在**真的执行了检索**的那一轮计一次，标签取**实际**档 `effective_mode`；
  **空问题轮与缓存命中轮刻意不计**（前者没发生检索，后者没调 embedding 且降级轮不写缓存）
  —— 计进去会让降级率的分母失真（本项目的"假分母"已被点过两次名）。

## 契约缺口（Q2，已登记待架构裁定）

冻结端口 `RetrievalPort.search -> tuple[CandidateRef, ...]` 只能表达资产级候选；
07 §6.7 要求的**列 Top-30 / 指标 Top-5**与 §6.6 的 `value_hits` 无契约承载位。
本实现：端口面返回资产级 `CandidateRef`（契约不破），富结果通过
`RetrievalResult` 暴露（W3C/W4 消费），**不私改 contracts.py**。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import orjson

from app.cache.keys import DEFAULT_TTL_S, semantic_retrieval
from app.core.contracts import CandidateRef, IdentityContext
from app.core.enums import ActionTaken, DegradedReason, RetrievalMode
from app.obs.metrics import observe_retrieval_mode
from app.retrieval.dense import EmbeddingUnavailable, VectorStore
from app.retrieval.fuse import (
    ROUTE_DENSE,
    ROUTE_GRAPH,
    ROUTE_SPARSE,
    ROUTE_VALUE,
    rrf_fuse,
    top_n,
)
from app.retrieval.graph import GraphHit, expand_join_graph
from app.retrieval.sparse import SparseSearch
from app.retrieval.value import ValueHit, search_values
from app.retrieval.view import BundleView, JoinEdge

__all__ = ["RetrievalResult", "RetrievalService"]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """检索出参：契约面 candidates + 富结果 + 如实的降级信息。"""

    mode: RetrievalMode
    candidates: tuple[CandidateRef, ...]        # 资产级 Top-5（07 §6.7）
    columns: tuple[tuple[str, float], ...]      # 列级 Top-30（ref="资产.列", 融合分）
    metrics: tuple[tuple[str, float], ...]      # 指标级 Top-5
    value_hits: tuple[ValueHit, ...]
    graph_hits: tuple[GraphHit, ...]
    degraded_reason: DegradedReason | None      # 非空 = 本轮发生了降级（N-21）
    action_taken: ActionTaken | None

    @property
    def degraded(self) -> bool:
        return self.degraded_reason is not None


class RetrievalService:
    """`RetrievalPort` 实现。全部依赖注入（不建池、不读 YAML、不连网 unless dense）。"""

    def __init__(
        self,
        *,
        view: BundleView,
        embedder: Any,
        vector_store: VectorStore,
        sparse: SparseSearch,
        weights: Mapping[str, float],
        rrf_k: int,
        cache: Any | None = None,
        asset_top: int = 5,
        column_top: int = 30,
        metric_top: int = 5,
        store_fetch_limit: int = 50,
    ) -> None:
        self._view = view
        self._embedder = embedder
        self._vector_store = vector_store
        self._sparse = sparse
        self._weights = {name: float(v) for name, v in weights.items()}
        self._rrf_k = rrf_k
        self._cache = cache
        self._asset_top = asset_top
        self._column_top = column_top
        self._metric_top = metric_top
        self._store_fetch_limit = store_fetch_limit

    # ------------------------------------------------------------------
    # RetrievalPort
    # ------------------------------------------------------------------

    async def search(
        self, question: str, ctx: IdentityContext, mode: RetrievalMode
    ) -> tuple[CandidateRef, ...]:
        """契约面方法：返回资产级候选（富结果走 `search_full`）。"""
        return (await self.search_full(question, ctx, mode)).candidates

    async def search_full(
        self, question: str, ctx: IdentityContext, mode: RetrievalMode
    ) -> RetrievalResult:
        """完整检索（W4 接线 / 离线评测消费）。

        ⚠️ mode 语义：调用方的**请求**；结果里的 mode 是**实际**执行档
        （HYBRID 请求在稠密失败后实际执行 SPARSE_ONLY，C-11 要求如实回填）。
        """
        if not question.strip():
            # ⚠️ 此处**不计** `retrieval_mode_total`：空问题没有发生检索，
            #    计进分母会把"降级率"稀释成"含空问的比率"（假分母）。
            return RetrievalResult(
                mode=mode, candidates=(), columns=(), metrics=(),
                value_hits=(), graph_hits=(),
                degraded_reason=None, action_taken=None,
            )

        bundle_version = self._view.version
        tenant_id = ctx.tenant_id

        # 缓存命中（只对非降级轮生效——见模块 docstring 的决策记录）。
        cache_key = semantic_retrieval(tenant_id, bundle_version, question)
        if self._cache is not None:
            raw = await self._cache.get(cache_key)
            if raw is not None:
                # ⚠️ 此处**不计** `retrieval_mode_total`：缓存命中没有调用 embedding，
                #    而降级轮**从不写缓存**（见模块 docstring）⇒ 把缓存命中记成 `hybrid`
                #    会**系统性低估** embedding 降级率（RL-2 的分子分母都会失真）。
                return self._result_from_cache(orjson.loads(raw))

        # ① 稠密（失败 → 显式降级，N-21：不静默）
        degraded_reason: DegradedReason | None = None
        action_taken: ActionTaken | None = None
        dense_available = mode == RetrievalMode.HYBRID
        dense_hits: list[tuple[str, str, float]] = []  # (ref, kind, score)
        if dense_available:
            try:
                dense_hits = await self._dense_route(question, ctx, bundle_version)
            except EmbeddingUnavailable:
                dense_available = False
                degraded_reason = DegradedReason.EMBEDDING_UNAVAILABLE
                action_taken = ActionTaken.SPARSE_ONLY

        effective_mode = RetrievalMode.HYBRID if dense_available else RetrievalMode.SPARSE_ONLY

        # ② 稀疏
        sparse_rows = await self._sparse.search(
            question,
            tenant_id=tenant_id,
            bundle_version=bundle_version,
            limit=self._store_fetch_limit,
        )
        sparse_hits = [(h.ref, h.kind, h.score) for h in sparse_rows]

        # ③ 值检索（纯语义包；无租户维度，见 value.py）
        value_hits = search_values(question, self._view)

        # ④ 图扩展：种子 = dense/sparse 已命中的资产
        seed_assets = self._hit_assets(dense_hits) | self._hit_assets(sparse_hits)
        graph_hits = expand_join_graph(tuple(sorted(seed_assets)), self._view)

        # ⑤ 资产级融合（07 §6.7）
        asset_fused = rrf_fuse(
            {
                ROUTE_DENSE: self._dedupe(self._hit_assets_list(dense_hits)),
                ROUTE_SPARSE: self._dedupe(self._hit_assets_list(sparse_hits)),
                ROUTE_VALUE: self._dedupe([h.asset for h in value_hits]),
                ROUTE_GRAPH: [h.asset for h in graph_hits],
            },
            self._weights,
            k=self._rrf_k,
            dense_available=dense_available,
        )
        asset_top = top_n(asset_fused, self._asset_top)
        candidates = tuple(CandidateRef(asset_id=f.candidate_id, score=f.score) for f in asset_top)

        # ⑥ 列级融合（kind=column 的命中 + value_hits 的列）→ Top-30
        column_fused = rrf_fuse(
            {
                ROUTE_DENSE: self._dedupe([r for r, k, _ in dense_hits if k == "column"]),
                ROUTE_SPARSE: self._dedupe([r for r, k, _ in sparse_hits if k == "column"]),
                ROUTE_VALUE: self._dedupe([f"{h.asset}.{h.column}" for h in value_hits]),
            },
            self._weights,
            k=self._rrf_k,
            dense_available=dense_available,
        )
        columns = tuple((f.candidate_id, f.score) for f in top_n(column_fused, self._column_top))

        # ⑦ 指标级融合（kind=metric 的命中）→ Top-5
        metric_fused = rrf_fuse(
            {
                ROUTE_DENSE: self._dedupe([r for r, k, _ in dense_hits if k == "metric"]),
                ROUTE_SPARSE: self._dedupe([r for r, k, _ in sparse_hits if k == "metric"]),
            },
            self._weights,
            k=self._rrf_k,
            dense_available=dense_available,
        )
        metrics = tuple((f.candidate_id, f.score) for f in top_n(metric_fused, self._metric_top))

        result = RetrievalResult(
            mode=effective_mode,
            candidates=candidates,
            columns=columns,
            metrics=metrics,
            value_hits=value_hits,
            graph_hits=graph_hits,
            degraded_reason=degraded_reason,
            action_taken=action_taken,
        )

        # ⑧ 结果缓存（降级轮不写——决策见模块 docstring）
        if self._cache is not None and not result.degraded:
            await self._cache.set(
                cache_key,
                self._result_to_cache(result),
                ttl_s=DEFAULT_TTL_S["semantic_retrieval"],
            )
        # ⑨ 检索模式埋点（RL-2 的唯一缺口，W7 派单；本模块是**唯一**调用点）：
        #    只在本轮**真的执行了检索**时计一次，且用**实际**执行档 `effective_mode`
        #    （= C-11 的"如实回填"：HYBRID 请求在稠密失败后记 `sparse_only`）。
        #    ⇒ `retrieval_mode_total{sparse_only} / sum(...)` = embedding 降级率。
        #    ⚠️ 两条早退路径刻意不计（各自写在上面的注释里）—— 它们会让分母失真。
        observe_retrieval_mode(effective_mode)
        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _dense_route(
        self, question: str, ctx: IdentityContext, bundle_version: str
    ) -> list[tuple[str, str, float]]:
        vectors = await self._embedder.embed([question])
        hits = await self._vector_store.topk(
            vectors[0],
            tenant_id=ctx.tenant_id,
            bundle_version=bundle_version,
            limit=self._store_fetch_limit,
        )
        return [(h.ref, h.kind, h.score) for h in hits]

    def _hit_assets_list(self, hits: Sequence[tuple[str, str, float]]) -> list[str]:
        """命中 ref → 资产 logical_name（kind 归并；不可归并的 ref 忽略并保守丢弃）。"""
        metric_names = {m.name for m in self._view.metrics}
        assets = {a.logical_name for a in self._view.assets}
        out: list[str] = []
        for ref, _kind, _score in hits:
            asset = self._ref_to_asset(ref, metric_names, assets)
            if asset is not None:
                out.append(asset)
        return out

    def _hit_assets(self, hits: Sequence[tuple[str, str, float]]) -> set[str]:
        return set(self._hit_assets_list(hits))

    @staticmethod
    def _ref_to_asset(ref: str, metric_names: set[str], assets: set[str]) -> str | None:
        if "." in ref:
            return ref.partition(".")[0]
        if ref in assets:
            return ref
        if ref in metric_names:
            return ref
        return None

    @staticmethod
    def _dedupe(items: Sequence[str]) -> list[str]:
        """保序去重（名次 = 首次出现位置）。"""
        return list(dict.fromkeys(items))

    def _result_to_cache(self, result: RetrievalResult) -> str:
        return orjson.dumps(
            {
                "mode": str(result.mode),
                "candidates": [[c.asset_id, c.score] for c in result.candidates],
                "columns": [[ref, s] for ref, s in result.columns],
                "metrics": [[name, s] for name, s in result.metrics],
                "value_hits": [
                    [h.term, h.asset, h.column, list(h.values), h.confidence, h.source]
                    for h in result.value_hits
                ],
                "graph_hits": [
                    [h.asset, h.hop, self._path_to_refs(h.path)] for h in result.graph_hits
                ],
                "degraded_reason": (
                    str(result.degraded_reason) if result.degraded_reason else None
                ),
                "action_taken": str(result.action_taken) if result.action_taken else None,
            }
        ).decode()

    def _path_to_refs(self, path: Sequence[JoinEdge]) -> list[list[str]]:
        # path 实为 tuple[JoinEdge, ...]（graph.py 的 GraphHit.path）。
        return [
            [e.left_asset, e.left_column, e.right_asset, e.right_column] for e in path
        ]

    def _result_from_cache(self, raw: Mapping[str, Any]) -> RetrievalResult:
        edge_index = {
            (e.left_asset, e.left_column, e.right_asset, e.right_column): e
            for e in self._view.joins
        }
        graph_hits = tuple(
            GraphHit(
                asset=g[0],
                hop=g[1],
                path=tuple(
                    edge_index[(p[0], p[1], p[2], p[3])]
                    for p in g[2]
                    if (p[0], p[1], p[2], p[3]) in edge_index
                ),
            )
            for g in raw["graph_hits"]
        )
        value_hits = tuple(
            ValueHit(term=h[0], asset=h[1], column=h[2], values=tuple(h[3]),
                     confidence=h[4], source=h[5])
            for h in raw["value_hits"]
        )
        return RetrievalResult(
            mode=RetrievalMode(raw["mode"]),
            candidates=tuple(CandidateRef(asset_id=c[0], score=c[1]) for c in raw["candidates"]),
            columns=tuple((c[0], c[1]) for c in raw["columns"]),
            metrics=tuple((m[0], m[1]) for m in raw["metrics"]),
            value_hits=value_hits,
            graph_hits=graph_hits,
            degraded_reason=(
                DegradedReason(raw["degraded_reason"]) if raw["degraded_reason"] else None
            ),
            action_taken=ActionTaken(raw["action_taken"]) if raw["action_taken"] else None,
        )
