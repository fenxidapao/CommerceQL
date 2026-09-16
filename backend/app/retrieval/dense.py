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
  但该表**由 W2A 物化**、schema 未冻结——除表名外的列形态以 W2A 冻结为准，
  本实现按 07 §6.3/§12.2 的字段需求写，**在 W2A 冻结 schema 前标 UNVERIFIED**，
  不跑集成测试（本机 pgvector 也未安装）。
- `InMemoryVectorStore` 是**测试/离线评测用的替身**（余弦同生产数学），
  **不是**第二套生产实现，禁止在任何在线路径使用。
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any, Final, Protocol, Sequence

import httpx
import orjson

from app.cache.keys import DEFAULT_TTL_S, embedding as embedding_key

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
    def _row_to_hit(row: Mapping[str, Any]) -> VectorHit:
        return VectorHit(
            ref=str(row["ref"]),
            kind=str(row["kind"]),
            score=float(row["score"]),
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
        return [self._row_to_hit(row) for row in rows]
