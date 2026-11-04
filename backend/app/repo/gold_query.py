"""Gold Query 只读检索 —— B6 few-shot 的**唯一读取通道**。

归属窗口：B6。表结构 = 迁移 `0005`（`app.gold_query`）。

## 为什么单独一个 DAO，而不是塞进 `FeedbackStore`

`FeedbackStore` 的写面是 `feedback`（用户反馈），Gold Query 的写面是"审核通过后入库"，
两者唯一的交集是迁移文件。读取侧同样只服务一个消费者（`PlannerEngine` 的 few-shot），
故按单一职责拆开；表名/列名只在本文件出现一次。

## 检索规则：§11.7 原文必须写进 SQL

```sql
WHERE (tenant_id IS NULL OR tenant_id = :tenant_id)
  AND domain = ANY(:domains)
  AND bundle_version = :bundle_version
```

- `tenant_id IS NULL` = 全局认证库（对所有租户可见）；非 NULL = 租户私有库。
  **不能**把这条规则放到应用层：跨租户泄露是 N-12 面（prompt 内容白名单）的事故，
  应用层过滤一旦漏写就是静默越权。
- `bundle_version` 过滤是 §11.7 明文要求：召回别的语义包版本产的 Gold Query，
  等于用旧口径的 SQL 给新口径的问题做示例。
- `domain` 在 B6 用 `ANY(:domains)` 而不是单值 `= :domain`：一个计划可以跨域
  （`orders` + `products`），而检索规则只约束"可见性"，不约束"计划只能落一个域"。
  `domains` 由调用方从**计划自身的资产**派生（语义包 `domain` 字段），空集合直接返回空，
  **不**退化成"查全部域"。

## 排序：Top-3–5 在 Python 侧做

表上没有 embedding / 全文索引列（`gold_query` 只有 `ast_fingerprint`），
故先用 SQL 做完**可见性**过滤，再在候选上限（`_SCAN_LIMIT`）内按问题文本相似度排序。
排序是确定性的：分数相同按数据库返回顺序（`gold_id`）稳定打破平局。

⚠️ 读失败**不在这里兜**：本层如实上抛，由 `PlannerEngine` 决定"few-shot 是增强项，
读失败降级为空"（与 `runner._read_session_history` 同口径）。
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = ["GOLD_QUERY_TABLE", "GoldQueryStore", "rank_gold_queries"]

GOLD_QUERY_TABLE: Final[str] = "app.gold_query"

#: 单次扫描上限：先粗取再精排，避免把全库问题文本读进内存。
_SCAN_LIMIT: Final[int] = 50

#: §11.7 检索规则的唯一 SQL 文本（tenant 可见性 + bundle + domain）。
_SELECT_SQL: Final[str] = (
    f"SELECT question, sql FROM {GOLD_QUERY_TABLE} "
    "WHERE (tenant_id IS NULL OR tenant_id = :tenant_id) "
    "AND domain = ANY(:domains) "
    "AND bundle_version = :bundle_version "
    "ORDER BY gold_id "
    "LIMIT :scan_limit"
)

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


def _normalize(value: str) -> str:
    """比较用的规范化：去空白 + casefold（只影响排序，不改写回 prompt 的原文）。"""
    return _WHITESPACE.sub("", value).casefold()


def rank_gold_queries(
    question: str,
    candidates: Sequence[tuple[str, str]],
    *,
    limit: int,
) -> tuple[tuple[str, str], ...]:
    """按问题文本相似度取 Top-`limit`（确定性排序）。"""
    if limit <= 0:
        return ()
    target = _normalize(question)
    scored: list[tuple[float, int, tuple[str, str]]] = []
    for idx, (candidate_question, candidate_sql) in enumerate(candidates):
        if not candidate_question or not candidate_sql:
            continue
        score = difflib.SequenceMatcher(None, target, _normalize(candidate_question)).ratio()
        scored.append((score, idx, (candidate_question, candidate_sql)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(pair for _, _, pair in scored[:limit])


class GoldQueryStore:
    """`app.gold_query` 的只读数据访问对象（few-shot 专用）。"""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def few_shots(
        self,
        *,
        tenant_id: str,
        bundle_version: str,
        domains: Sequence[str],
        question: str,
        limit: int,
    ) -> tuple[tuple[str, str], ...]:
        """取 Top-`limit` 条可见的 `(问题, SQL)`。

        空 `domains` / 空身份 / 空版本一律返回空：缺任何一个过滤条件都不查。
        """
        visible_domains = tuple(
            dict.fromkeys(str(domain) for domain in domains if str(domain).strip())
        )
        if not visible_domains or not tenant_id or not bundle_version or limit <= 0:
            return ()
        params = {
            "tenant_id": tenant_id,
            "domains": list(visible_domains),
            "bundle_version": bundle_version,
            "scan_limit": _SCAN_LIMIT,
        }
        async with self._engine.connect() as conn:
            result = await conn.execute(text(_SELECT_SQL), params)
            rows = [
                (str(row["question"]), str(row["sql"]))
                for row in result.mappings().all()
            ]
        return rank_gold_queries(question, rows, limit=limit)
