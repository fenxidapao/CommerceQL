"""稀疏词法检索（07 §6.4，**FTS，非 BM25**）。

归属窗口：**W2B**。N-22：UI/文档/答辩统一措辞「稀疏词法检索（FTS）」，**不得称 BM25**
（`ts_rank_cd` 无完整 IDF 与文档长度归一化——已知能力缺口，若评测显示召回不足，
P1 评估 `pg_bigm` 或真 BM25，走 ADR 变更，不悄悄换）。

规则逐条对齐 07 §6.4：
- 分词：**jieba 唯一入口** `retrieval/tokenizer.py`；写入与查询**必须调同一函数**（N-24）；
- 查询构造：**禁用 `plainto_tsquery`**（它会再走 PG 分词 → 两侧不同源）→
  `to_tsquery('simple', :terms)`，`:terms` 由 tokenizer 产出并经**参数绑定**传入（N-04）；
- 排序：`ts_rank_cd(tsv, query, 32)`，归一化标志 32（rank/(rank+1)，压缩长文档优势）
  ——32 来自 `app.core.config.FTS_RANK_NORMALIZATION`，本模块不持第二份默认值；
- 截断：分数 < `FTS_SCORE_MIN`(0.05) 丢弃；列级 Top-30 / 资产级 Top-10 由调用方截。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from app.retrieval.tokenizer import tsquery_source

__all__ = ["SparseHit", "SparseSearch", "build_tsquery_terms", "rank_and_filter"]


@dataclass(frozen=True, slots=True)
class SparseHit:
    """稀疏检索命中（与 dense.VectorHit 同构：ref/kind/score，便于融合对齐）。"""

    ref: str
    kind: str            # asset | column | metric | synonym | gold_query（07 §12.2）
    score: float


def build_tsquery_terms(question: str) -> str:
    """问句 → `to_tsquery('simple', :terms)` 的参数值（N-24 的查询侧落点）。

    ⚠️ 这里产出的 `'tok1' & 'tok2'` 串与写入侧 `tsvector_source()` **同源**
    （同一 `tokenize()`），但形态不同：to_tsquery 要求显式 `&` 连接
    （2026-09-16 集成测试实测：空格分隔直接 syntax error）。不要在调用点自己分词。
    """
    return tsquery_source(question)


class Fetcher(Protocol):
    """SQL 取数端口（注入；本模块不自建连接池，N-14）。"""

    async def __call__(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]: ...


class SparseSearch:
    """FTS 查询（表 = 07 §12.2 `app.embed_doc`，`tsv` 列 + GIN，由 W2A 物化）。

    `table` 参数仅供集成测试指到临时 schema 的夹具表；生产默认值不得改
    （改 = 私自变更物化契约，必须走 W2A/架构）。
    """

    #: 列名逐字对齐 07 §12.2。归一化标志与低分阈值经参数注入，不写死。
    #:
    #: ⚠️ `tenant_id IN (:tenant_id, '*')`：`'*'` 是 W2A 物化侧的**公共语义包哨兵**
    #: （2026-09-16 实测 `app.embed_doc.tenant_id` 为 `'*'`，非 NULL 非真租户）。
    #: 语义包 doc 不含任何租户数据，故公共哨兵行对任意租户可见**不构成跨租户泄露**；
    #: 真租户行仍只能命中自己的 `:tenant_id`。过滤发生在 SQL WHERE 内（N-10 不变）。
    #: ⚠️ 该哨兵尚未在 07 §12.2 契约化 —— 对齐项已登记 W2B RELAY，待架构/W2A 确认。
    _SQL_TEMPLATE: Final[str] = """
        SELECT doc_id, ref, kind,
               ts_rank_cd(tsv, query, :rank_norm) AS score
        FROM {table}, to_tsquery('simple', :terms) query
        WHERE tsv @@ query
          AND bundle_version = :bundle_version
          AND tenant_id IN (:tenant_id, '*')
        ORDER BY score DESC, doc_id
        LIMIT :limit
    """

    def __init__(
        self,
        fetch: Fetcher,
        *,
        rank_normalization: int,
        score_min: float,
        table: str = "app.embed_doc",
    ) -> None:
        self._fetch = fetch
        self._rank_normalization = rank_normalization
        self._score_min = score_min
        self._sql = self._SQL_TEMPLATE.format(table=table)

    async def search(
        self,
        question: str,
        *,
        tenant_id: str,
        bundle_version: str,
        limit: int,
    ) -> list[SparseHit]:
        """执行 FTS 查询并做路由内截断（低分丢弃）。

        ⚠️ `terms` 为空（问句分词后无有效 token）时**不发查询**，直接返回空——
        `to_tsquery('simple', '')` 会直接抛语法错误，而"没有词可查"不是错误，是空结果。
        """
        terms = build_tsquery_terms(question)
        if not terms:
            return []
        rows = await self._fetch(
            self._sql,
            {
                "terms": terms,  # 参数绑定（N-04）；:terms 里不含任何用户可控的 tsquery 运算符
                "rank_norm": self._rank_normalization,
                "bundle_version": bundle_version,
                "tenant_id": tenant_id,
                "limit": limit,
            },
        )
        return rank_and_filter(
            ({"ref": r["ref"], "kind": r["kind"], "score": r["score"]} for r in rows),
            score_min=self._score_min,
        )


def rank_and_filter(
    rows: Sequence[Mapping[str, Any]] | Any,
    *,
    score_min: float,
) -> list[SparseHit]:
    """行 → 命中列表：低分丢弃（07 §6.4）+ 确定性排序（score 降序，ref 兜底）。

    独立成纯函数：路由内截断规则可离线测试，不依赖 fetcher。
    """
    hits = [
        SparseHit(ref=str(r["ref"]), kind=str(r["kind"]), score=float(r["score"]))
        for r in rows
    ]
    kept = [h for h in hits if h.score >= score_min]
    kept.sort(key=lambda h: (-h.score, h.ref, h.kind))
    return kept
