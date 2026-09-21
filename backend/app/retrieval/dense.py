"""稠密检索（07 §6.3）—— Ollama embedding 客户端 + 向量存储查询。

归属窗口：**W2B**。`dense.py` 是 `refine.py` 之外检索内唯一碰网络的模块。

规则逐条对齐 07 §6.3：
- 调用 Ollama `POST /api/embed`，**批量 ≤ 32**，超过分片；
- 超时 `EMBEDDING_TIMEOUT_SECONDS`（覆盖冷启动模型加载）；
- 失败：重试 1 次（退避 1s）→ 仍失败 → `EmbeddingUnavailable` →
  上层转 `retrieval_mode=sparse_only` + `degraded(embedding_unavailable, sparse_only)`
  （**N-21：不得静默降级**——降级信息必须如实上抛，由编排层发事件）；
- 距离度量 cosine；写入前 L2 归一化，查询向量同（本模块负责查询侧归一化）；
- 检索范围 **SQL 层强制** `bundle_version = :active AND tenant_id = :tenant`
  （N-10：绝不"先跨租户召回再过滤"）；
- 向量缓存键 `emb:{model}:{dim}:{sha256(text)}`（`app/cache/keys.embedding`，
  唯一无租户豁免键），TTL 30 天。

## 落位与诚实边界

- `PgVectorStore` 的物理 SQL 面向 `app.embed_doc`（W1B 启动断言引用的表名）；
  该表由 W2A 物化。**列形态已核对**（2026-09-21 实测 `information_schema`：
  `doc_id/bundle_version/tenant_id/kind/ref/text/tsv/embedding`，其中 `embedding`
  = `vector`、`tsv` = `tsvector`，与 07 §12.2 逐字一致；本机 pgvector **已装**
  = `0.8.6`，旧注"本机 pgvector 也未安装"作废）。
- **`U-112`：稠密不可用的两种形态，本模块都归到同一个出口**（07 §5.3 行 4 的
  `degraded(embedding_unavailable, sparse_only)`，不新发明出口）：
  - **(i) 请求侧失败**：`OllamaEmbedder.embed` 重试耗尽 → 抛 `EmbeddingUnavailable`；
  - **(ii) 数据侧缺失**：向量列未物化（`embedding IS NULL`）。此时
    `1 - (embedding <=> vec)` **返回 NULL**（不是 0），`float(None)` 会抛 `TypeError`
    并一路逃出图 ⇒ runner 兜底 `error(INTERNAL)`（W7 2026-09-21 活体栈实测）。
    `PgVectorStore.topk` 现按下列规则**转为 (i) 同款异常**：
    作用域内有行但**一条可用向量都没有** ⇒ 抛 `EmbeddingUnavailable`（= 空向量列）；
    作用域内**一行都没有** ⇒ 返回空、**不降级**（空 KB / 无该版本文档是合法状态，
    不能让"没数据"冒充"软依赖坏了"，否则 `retrieval_mode=sparse_only` 的降级率
    会掺进假信号 —— 07 §6.x 把它当 Ollama 健康度信号用）。
    ⚠️ 部分为 NULL 时**不降级**：有效向量照常返回。"列里有没有数"由
    `U-111` 的**启动断言**负责播报，不在读路径上重复判（一条判据两个落点 = 第 5 例）。
- **有效向量不会被 NULL 行挤掉**（判据不是不等式，是可证事实）：SQL 的
  `ORDER BY embedding <=> (:vector)::vector, doc_id` 是 **ASC**，PG 的 ASC 默认
  **`NULLS LAST`** ⇒ 非 NULL 行必排在 NULL 行之前 ⇒ 被 `LIMIT` 截掉的只可能是
  NULL 行。**这条不变量由集成测试锁住**
  （`tests/integration/test_retrieval_fts_pg.py::test_dense_null_rows_never_crowd_out_valid_vectors`）
  —— 改 `ORDER BY` 的排序方向会让它变红。
- `InMemoryVectorStore` 是**测试/离线评测用的替身**（余弦同生产数学），
  **不是**第二套生产实现，禁止在任何在线路径使用。
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

import httpx
import orjson

from app.cache.keys import DEFAULT_TTL_S
from app.cache.keys import embedding as embedding_key

__all__ = [
    "EMBED_BATCH_SIZE",
    "EmbeddingUnavailable",
    "InMemoryVectorStore",
    "OllamaEmbedder",
    "PgVectorStore",
    "VectorHit",
    "VectorStore",
    "l2_normalize",
]

#: 单批上限（07 §6.3：减少往返；单批过大会触发 Ollama 侧超时）。
EMBED_BATCH_SIZE: Final[int] = 32

#: 重试退避（07 §6.3：重试 1 次，退避 1s）。
RETRY_BACKOFF_S: Final[float] = 1.0

#: Ollama embed 端点路径（相对 base_url）。
_EMBED_PATH: Final[str] = "/api/embed"


class EmbeddingUnavailable(RuntimeError):
    """稠密向量不可用（重试后仍失败）。**必须**被上层转为显式降级，禁止吞掉。"""


def l2_normalize(vector: Sequence[float]) -> list[float]:
    """L2 归一化（07 §6.3：查询向量与写入向量同规则）。零向量原样返回（不除零）。"""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return list(vector)
    return [v / norm for v in vector]


@dataclass(frozen=True, slots=True)
class VectorHit:
    """向量检索命中（分数 = 1 - cosine distance；归一化向量下 ∈ [0,1]）。

    `ref` = 07 §12.2 `embed_doc.ref`：doc 的引用键（kind=asset → 资产名；
    kind=column → "资产.列"；kind=metric → 指标名）。
    """

    ref: str
    kind: str            # asset | column | metric | synonym | gold_query（07 §12.2）
    score: float


class VectorStore(Protocol):
    """向量存储查询端口（dense 路的取数面；实现方负责 SQL 层租户过滤）。

    ⚠️ N-10：租户与版本过滤必须在**查询内部**完成（生产 = SQL WHERE），
    绝不允许"先全量召回再在 Python 里过滤"——实现方违约时本协议无法阻止，
    由集成测试与评审把关（这是 Protocol 的边界，如实写明）。
    """

    async def topk(
        self,
        vector: Sequence[float],
        *,
        tenant_id: str,
        bundle_version: str,
        limit: int,
    ) -> list[VectorHit]: ...


class OllamaEmbedder:
    """Ollama `/api/embed` 客户端（批量、重试、L2 归一化、向量缓存）。"""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dim: int,
        timeout_s: float,
        cache: Any | None = None,
        client: httpx.AsyncClient | None = None,
        backoff: Any = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dim = dim
        self._timeout_s = timeout_s
        self._cache = cache          # CachePort 或 None（None = 不缓存，测试用）
        self._client = client
        self._backoff = backoff      # 可注入的 sleep（测试瞬时化）

    async def _post_embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self._model, "input": texts}
        client = self._client or httpx.AsyncClient(timeout=self._timeout_s)
        try:
            last_error: Exception | None = None
            for attempt in (1, 2):  # 首次 + 重试 1 次（07 §6.3）
                try:
                    resp = await client.post(
                        f"{self._base_url}{_EMBED_PATH}", json=payload
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    embeddings = body.get("embeddings")
                    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                        raise EmbeddingUnavailable(
                            f"Ollama /api/embed 返回形状异常：期望 {len(texts)} 条向量"
                        )
                    return embeddings
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    if attempt == 1:
                        await self._backoff(RETRY_BACKOFF_S)
            raise EmbeddingUnavailable(
                f"embedding 重试 1 次后仍失败：{type(last_error).__name__}: {last_error}"
            ) from last_error
        finally:
            if self._client is None:
                await client.aclose()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """批量 embed（自动分片 ≤32 + L2 归一化 + 可选向量缓存）。

        ⚠️ 缓存命中/未命中混合时：只对 miss 的文本发起请求，顺序按输入回填。
        降级语义：任何分片失败 → 整体抛 `EmbeddingUnavailable`（不返回部分结果——
        上层要么全量稠密要么整体降级，"半稠密"是没人能解释的状态）。
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        miss_idx: list[int] = []
        miss_texts: list[str] = []

        if self._cache is not None:
            for i, text in enumerate(texts):
                raw = await self._cache.get(embedding_key(self._model, self._dim, text))
                if raw is not None:
                    results[i] = orjson.loads(raw)
                else:
                    miss_idx.append(i)
                    miss_texts.append(text)
        else:
            miss_idx = list(range(len(texts)))
            miss_texts = list(texts)

        for start in range(0, len(miss_texts), EMBED_BATCH_SIZE):
            batch = miss_texts[start : start + EMBED_BATCH_SIZE]
            embedded = await self._post_embed(batch)
            for offset, vector in enumerate(embedded):
                idx = miss_idx[start + offset]
                normalized = l2_normalize(vector)
                if len(normalized) != self._dim:
                    raise EmbeddingUnavailable(
                        f"embedding 维度不符：期望 {self._dim}，实际 {len(normalized)}"
                        "（EMBEDDING_DIM / 模型 / 物化向量列三者必须一致，07 §6.1⑤）"
                    )
                results[idx] = normalized
                if self._cache is not None:
                    await self._cache.set(
                        embedding_key(self._model, self._dim, batch[offset]),
                        orjson.dumps(normalized).decode(),
                        ttl_s=DEFAULT_TTL_S["embedding"],
                    )

        # typing 收窄：上面保证每个位置都被赋值（命中或回填）。
        return [v for v in results if v is not None]


class InMemoryVectorStore:
    """测试 / 离线评测替身：全量余弦 + 线性扫。**禁止**在线路径使用。"""

    def __init__(self) -> None:
        # (ref, kind, tenant_id, bundle_version, vector)
        self._docs: list[tuple[str, str, str, str, list[float]]] = []

    def add(
        self,
        *,
        ref: str,
        kind: str,
        tenant_id: str,
        bundle_version: str,
        vector: Sequence[float],
    ) -> None:
        self._docs.append((ref, kind, tenant_id, bundle_version, list(vector)))

    async def topk(
        self,
        vector: Sequence[float],
        *,
        tenant_id: str,
        bundle_version: str,
        limit: int,
    ) -> list[VectorHit]:
        query = l2_normalize(vector)
        scored: list[VectorHit] = []
        for ref, kind, doc_tenant, doc_version, doc_vec in self._docs:
            # 过滤在查询内完成（对齐生产 SQL 层语义；N-10 的替身对应物）。
            if doc_tenant != tenant_id or doc_version != bundle_version:
                continue
            similarity = sum(a * b for a, b in zip(query, doc_vec, strict=True))
            scored.append(VectorHit(ref=ref, kind=kind, score=similarity))
        scored.sort(key=lambda h: (-h.score, h.ref))
        return scored[:limit]


class PgVectorStore:
    """pgvector 生产实现（表结构 = **07 §12.2 `embed_doc`**，由 W2A 物化）。

    - 取数经注入的 `fetch(sql, params)`（阶段 4 由 W4 注入 metadata 池的执行器；
      本模块**不自建连接池**——三池唯一装配点在 `app/repo/pools.py`，N-14）；
    - 租户与版本过滤在 SQL WHERE 内（N-10 / 07 §6.3）；
    - 分数 = `1 - (embedding <=> :vector)`（cosine 距离转相似度）。
    """

    #: 列名逐字对齐 07 §12.2 的 embed_doc 定义（doc_id/bundle_version/tenant_id/
    #: kind/ref/text/tsv/embedding）。schema 变更只动这个模板，不散落。
    #:
    #: ⚠️ `tenant_id IN (:tenant_id, '*')`：`'*'` = W2A 物化侧的公共语义包哨兵
    #: （实测 2026-09-16；语义包 doc 无租户数据，公共行全租户可见不构成泄露，
    #: 真租户行仍只能命中自己。过滤仍在 SQL 内，N-10 不变。对齐项已登记 RELAY）。
    #:
    #: ⚠️ **两处刻意"什么都不加"**（U-112，改动前先读模块头的"落位与诚实边界"）：
    #: 1. **不加 `AND embedding IS NOT NULL`** —— 加了就再也分不清"作用域内无文档"
    #:    与"文档在但向量没物化"；这两者的正确处理相反（前者如实返空，后者降级）。
    #: 2. **不写显式 `NULLS LAST`** —— ASC 下它与默认同义（多一处与 pgvector HNSW
    #:    有序扫描计划交互的语法，收益为零）；改成断言式锁：集成测试
    #:    `test_dense_null_rows_never_crowd_out_valid_vectors` 让"改排序方向"变红。
    _SQL_TEMPLATE: Final[str] = """
        SELECT ref, kind,
               1 - (embedding <=> (:vector)::vector) AS score
        FROM {table}
        WHERE bundle_version = :bundle_version
          AND tenant_id IN (:tenant_id, '*')
        ORDER BY embedding <=> (:vector)::vector, doc_id
        LIMIT :limit
    """

    def __init__(self, fetch: Any, *, table: str = "app.embed_doc") -> None:
        # fetch(sql: str, params: Mapping[str, Any]) -> Awaitable[Sequence[Mapping]]
        # `table` 仅供集成测试指到临时 schema 的夹具表；生产默认值不得改。
        self._fetch = fetch
        self._sql = self._SQL_TEMPLATE.format(table=table)

    @staticmethod
    def _row_to_hit(row: Mapping[str, Any]) -> VectorHit | None:
        """行 → 命中。**分数为 NULL 时返回 `None`**（= 该行没有可用向量）。

        `1 - (embedding <=> vec)` 在 `embedding IS NULL` 时求值为 **NULL**（不是 0）
        —— 旧实现无条件 `float(row["score"])` 会在这一步抛 `TypeError`、逃出图，
        被 runner 兜底成 `error(INTERNAL)`（`U-112` 形态 (ii)，W7 活体栈实测）。
        这里**不就地把 NULL 当成 0 分**（那会让空向量列伪造出"全 0 分候选"，
        比报错更坏）；返回 `None` 交 `topk` 汇总判断。
        """
        score = row["score"]
        if score is None:
            return None
        return VectorHit(
            ref=str(row["ref"]),
            kind=str(row["kind"]),
            score=float(score),
        )

    async def topk(
        self,
        vector: Sequence[float],
        *,
        tenant_id: str,
        bundle_version: str,
        limit: int,
    ) -> list[VectorHit]:
        rows = await self._fetch(
            self._sql,
            {
                # pgvector 文本入参形态；经参数绑定传入（N-04），不拼 SQL 字符串。
                "vector": f"[{','.join(repr(float(v)) for v in vector)}]",
                "bundle_version": bundle_version,
                "tenant_id": tenant_id,
                "limit": limit,
            },
        )
        hits = [h for h in (self._row_to_hit(row) for row in rows) if h is not None]

        # U-112 形态 (ii)：作用域内**有行**却**零条可用向量** ⇒ 向量列未物化。
        # 抛 `EmbeddingUnavailable`（与形态 (i) 同款异常）⇒ search.py 既有出口
        # 把它转成 `degraded(embedding_unavailable, sparse_only)`（07 §5.3 行 4）。
        # ⚠️ 判据是"有行且全 NULL"，不是"命中 0 行"：作用域内一行都没有（空 KB /
        #    该版本无文档）是**合法状态**，返回空即为如实结果，不得冒充降级。
        if rows and not hits:
            raise EmbeddingUnavailable(
                f"app.embed_doc 在 tenant_id={tenant_id!r} / "
                f"bundle_version={bundle_version!r} 作用域内返回 {len(rows)} 行，"
                "但 embedding 全为 NULL ⇒ 向量列未物化，稠密检索不可用"
                "（物化侧未注入 embedder，见 semantics/materialize.py 的 "
                "`pending_embedder`；U-112 形态 (ii)）。"
            )
        return hits
