"""`GoldQueryStore`（B6 few-shot 读取）的离线契约。

只测**不依赖真库**的部分：§11.7 规则是否真的写进 SQL、Top-K 排序是否确定性、
缺任一过滤条件是否不查。库侧语义（全局 ∪ 本租户、跨租户不可见）由迁移 0005 的
集成用例 `test_feedback_store_pg.py::test_gold_query_tenant_visibility_follows_section_11_7`
钉住；本文件的 SQL 断言与它同源（同一条 `WHERE` 形状）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.repo.gold_query import (
    _SELECT_SQL,
    GOLD_QUERY_TABLE,
    GoldQueryStore,
    rank_gold_queries,
)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, Any]], captured: dict[str, Any]) -> None:
        self._rows = rows
        self._captured = captured

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        self._captured["sql"] = str(statement)
        self._captured["params"] = dict(params)
        return _Result(self._rows)

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Engine:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.captured: dict[str, Any] = {}
        self.connected = 0

    def connect(self) -> _Connection:
        self.connected += 1
        return _Connection(self.rows, self.captured)


class _ExplodingEngine:
    def connect(self) -> Any:
        raise AssertionError("缺过滤条件时不得触碰数据库")


def test_select_sql_encodes_the_section_11_7_visibility_rule() -> None:
    """租户可见性、bundle 版本、domain 过滤都必须在 SQL 文本里（不靠应用层补）。"""
    assert GOLD_QUERY_TABLE in _SELECT_SQL
    assert "(tenant_id IS NULL OR tenant_id = :tenant_id)" in _SELECT_SQL
    assert "domain = ANY(:domains)" in _SELECT_SQL
    assert "bundle_version = :bundle_version" in _SELECT_SQL


def test_ranking_prefers_the_closer_question_and_respects_limit() -> None:
    candidates = [
        ("完全无关的退款率问题", "SELECT 1"),
        ("上月华东区 GMV 是多少", "SELECT 2"),
        ("上月华东区 GMV 环比", "SELECT 3"),
    ]
    ranked = rank_gold_queries("上月华东区 GMV 是多少", candidates, limit=2)
    assert [sql for _, sql in ranked] == ["SELECT 2", "SELECT 3"]


def test_ranking_ties_keep_database_order() -> None:
    """同分按 SQL 返回顺序打破平局（确定性；不依赖 dict/set 迭代顺序）。"""
    question = "同一句"
    candidates = [(question, "SELECT a"), (question, "SELECT b"), (question, "SELECT c")]
    ranked = rank_gold_queries(question, candidates, limit=3)
    assert [sql for _, sql in ranked] == ["SELECT a", "SELECT b", "SELECT c"]


@pytest.mark.asyncio
async def test_store_passes_filters_and_returns_top_k() -> None:
    engine = _Engine(
        rows=[
            {"question": "无关问题", "sql": "SELECT 0"},
            {"question": "上月销售额", "sql": "SELECT 1"},
        ]
    )
    store = GoldQueryStore(engine)  # type: ignore[arg-type]
    shots = await store.few_shots(
        tenant_id="T_A",
        bundle_version="2026.10.16.2",
        domains=("orders", "orders", "products"),
        question="上月销售额",
        limit=1,
    )
    assert shots == (("上月销售额", "SELECT 1"),)
    assert engine.captured["params"] == {
        "tenant_id": "T_A",
        "domains": ["orders", "products"],
        "bundle_version": "2026.10.16.2",
        "scan_limit": 50,
    }


@pytest.mark.asyncio
async def test_store_never_queries_without_a_domain() -> None:
    """空 domains 不许退化成"查全部域"（那是跨域召回，不是少一个过滤条件）。"""
    store = GoldQueryStore(_ExplodingEngine())  # type: ignore[arg-type]
    assert (
        await store.few_shots(
            tenant_id="T_A", bundle_version="v1", domains=(), question="x", limit=5
        )
        == ()
    )


@pytest.mark.asyncio
async def test_store_never_queries_without_identity_or_version() -> None:
    store = GoldQueryStore(_ExplodingEngine())  # type: ignore[arg-type]
    assert (
        await store.few_shots(
            tenant_id="", bundle_version="v1", domains=("orders",), question="x", limit=5
        )
        == ()
    )
    assert (
        await store.few_shots(
            tenant_id="T_A", bundle_version="", domains=("orders",), question="x", limit=5
        )
        == ()
    )
