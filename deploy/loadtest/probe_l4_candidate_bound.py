
import asyncio, statistics as st, json
from app.core.config import Settings
from app.core.contracts import IdentityContext
from app.core.enums import Role, RetrievalMode
from app.repo.pools import build_three_pools
from app.api.deps import (_load_bundle_view, _metadata_fetch, RETRIEVAL_WEIGHTS,
                          _SPARSE_RANK_NORMALIZATION, _SPARSE_SCORE_MIN)
from app.retrieval.dense import OllamaEmbedder, PgVectorStore
from app.retrieval.sparse import SparseSearch
from app.retrieval.search import RetrievalService

QS = ['T_A 2026-08 的日期维表有多少天？', 'T_A 从 2026-08-01 起的 GMV 是多少？', 'T_A 从 2026-06-01 起的 GMV 是多少？', 'T_A 从 2025-11-01 起的 GMV 是多少？', 'T_A 从 2026-03-01 起的 GMV 是多少？', 'T_A 从 2026-08-01 起的订单量是多少？', 'T_A 从 2026-06-01 起的订单量是多少？', 'T_A 从 2026-01-01 起的订单量是多少？', 'T_A 从 2026-08-01 起的付费金额合计（含未支付）是多少？', 'T_A 从 2026-08-01 起各渠道的 GMV 分别是多少？', 'T_A 从 2026-08-01 起各店铺的 GMV 分别是多少？', 'T_A 从 2026-08-01 起各一级类目的 GMV 分别是多少？', 'T_A 从 2026-08-01 起各收货城市的 GMV 分别是多少？', 'T_A 从 2026-08-01 起各sku_id的 UV 分别是多少？', 'T_A 从 2026-08-01 起各channel的 UV 分别是多少？', 'T_A 从 2026-08-01 起各stat_date的 UV 分别是多少？', 'T_A「3C数码」自 2026-08-01 起各店铺的 GMV 分别是多少？', 'T_A「家用电器」自 2026-08-01 起各店铺的 GMV 分别是多少？', 'T_A「服饰鞋包」自 2026-06-01 起各店铺的 GMV 分别是多少？', 'T_A「食品生鲜」自 2026-06-01 起各店铺的 GMV 分别是多少？', 'T_A「美妆个护」自 2026-05-01 起各店铺的 GMV 分别是多少？', 'T_A 自 2026-08-01 起各大区的 GMV 分别是多少？', 'T_A 自 2026-06-01 起各大区的 GMV 分别是多少？', 'T_A 自 2026-05-01 起各大区的 GMV 分别是多少？', 'T_A 自 2026-03-01 起各大区的 GMV 分别是多少？', 'T_A 自 2026-08-01 起有流量但零转化的 SKU 有哪些？', 'T_A「3C数码」自 2026-08-01 起各店铺的浏览量分别是多少？', 'T_A「家用电器」自 2026-08-01 起各店铺的浏览量分别是多少？', 'T_A「服饰鞋包」自 2026-06-01 起各店铺的浏览量分别是多少？', 'T_A「食品生鲜」自 2026-06-01 起各店铺的浏览量分别是多少？', 'T_A「美妆个护」自 2026-05-01 起各店铺的浏览量分别是多少？', 'T_A 自 2026-08-01 起各大区各店铺的 GMV 分别是多少？', 'T_A 自 2026-06-01 起各大区各店铺的 GMV 分别是多少？', 'T_A 自 2026-05-01 起各大区各店铺的 GMV 分别是多少？', 'T_A 自 2026-03-01 起各大区各店铺的 GMV 分别是多少？', 'T_A 自 2026-08-01 起的客单价是多少？', 'T_A 自 2026-06-01 起的客单价是多少？', 'T_A 自 2026-08-01 起的人均消费是多少？', 'T_A 自 2026-08-01 起的退款率是多少？', 'T_A 自 2026-08-01 起的支付转化率是多少？', 'T_A 自 2026-06-01 起的 90 天复购率是多少？', 'T_A 自 2026-03-01 起的 90 天复购率是多少？']

async def main():
    s = Settings()
    pools = build_three_pools(s)
    fetch = _metadata_fetch(pools.metadata)
    svc = RetrievalService(
        view=_load_bundle_view(s.SEMANTIC_BUNDLE_PATH),
        embedder=OllamaEmbedder(base_url=s.EMBEDDING_BASE_URL, model=s.EMBEDDING_MODEL,
                                dim=s.EMBEDDING_DIM, timeout_s=float(s.EMBEDDING_TIMEOUT_SECONDS), cache=None),
        vector_store=PgVectorStore(fetch),
        sparse=SparseSearch(fetch,
                            rank_normalization=_SPARSE_RANK_NORMALIZATION, score_min=_SPARSE_SCORE_MIN),
        weights=RETRIEVAL_WEIGHTS, rrf_k=s.RRF_K, cache=None)
    ident = IdentityContext(trace_id="p", task_id="p", session_id="p", tenant_id="T_A",
                            user_id="u_probe", role=Role.ANALYST, shop_ids=())
    cols=[]; cands=[]; mets=[]; modes={}
    for q in QS:
        r = await svc.search_full(q, ident, RetrievalMode.HYBRID)
        cols.append(len(r.columns)); cands.append(len(r.candidates)); mets.append(len(r.metrics))
        modes[r.mode.value] = modes.get(r.mode.value, 0) + 1
    def rep(name, v):
        v=sorted(v); n=len(v)
        p=lambda x: v[min(n-1, int(x*n))]
        print(name, "n=%d min=%d p50=%.1f p95=%.1f max=%d mean=%.2f" % (n, v[0], st.mean(v), p(.95), v[-1], st.mean(v)))
    print("questions =", len(QS), "modes =", modes)
    rep("columns(->L4 candidate_ids)", cols)
    rep("candidates", cands)
    rep("metrics", mets)
    import collections; print("columns histogram:", dict(sorted(collections.Counter(cols).items())))
    pass

asyncio.run(main())
