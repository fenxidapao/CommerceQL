"""W2B 集成测试（marker `integration`，离线默认不跑）。

覆盖两件事：
1. **N-24 动态 half（真 PG）**：写入侧用 `tsvector_source()` 算 `tsv`，
   查询侧 `SparseSearch`（同源分词）→ 同一文本必须召回（附录 D 检查项 18）；
   附带 ts_rank_cd 排序、租户隔离、`'*'` 公共哨兵行为。
2. **DoD③（真网络失败）**：`EMBEDDING_BASE_URL` 指向本机死端口 →
   重试耗尽 → `EmbeddingUnavailable` → 服务层显式降级（N-21 不静默）。

运行方式：
    ../.venv/Scripts/python.exe -m pytest tests/integration/test_retrieval_fts_pg.py -m integration

PG DSN（两路分离）：
- `PROD_DSN` = deploy/.env 的 DATABASE_URL（compose 服务名 `pg` → `127.0.0.1`）：
  仅用于生产表 schema 对齐检查（只读）。
- `TEST_DSN` = 环境变量 `RETRIEVAL_TEST_PG_DSN`，缺省回退 `PROD_DSN`：
  夹具 DDL 用；若该 DSN 的角色无建 schema 权限（如 app_rw），相关用例**如实 skip**。
  本机推荐：`docker run -d --name cql-it-pg -e POSTGRES_PASSWORD=it -p 5433:5432 postgres:16-alpine`
  并设 `RETRIEVAL_TEST_PG_DSN=postgresql://postgres:it@127.0.0.1:5433/postgres`。
夹具表落在**临时 schema**，测试后整体丢弃——不是第二份物化真相。
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from app.core.contracts import IdentityContext, Role
from app.core.enums import RetrievalMode
from app.retrieval.dense import EmbeddingUnavailable, OllamaEmbedder
from app.retrieval.search import RetrievalService
from app.retrieval.sparse import SparseSearch
from app.retrieval.tokenizer import tsvector_source
from app.retrieval.view import BundleView
from tests.unit._retrieval_fixture import FakeCache, load_bundle_view

pytestmark = pytest.mark.integration

BUNDLE_VERSION = "2026.09.14.1"

pytest.importorskip("psycopg", reason="psycopg 未安装（集成测试需要真 PG）")

import psycopg  # noqa: E402  # importorskip 之后


# ---------------------------------------------------------------------------
# DSN 定位（两路分离）：
# - PROD_DSN：deploy/.env 的 DATABASE_URL —— 仅用于生产表 schema 对齐检查（只读）；
# - TEST_DSN：RETRIEVAL_TEST_PG_DSN（优先）或回退 PROD_DSN —— 夹具 DDL 用。
#   回退 DSN 的角色（app_rw）无建 schema 权限时，夹具用例如实 skip，不伪装通过。
# ---------------------------------------------------------------------------

def _dsn_from_env_file() -> str | None:
    env_file = Path(__file__).resolve().parents[3] / "deploy" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.partition("=")[2].strip().replace(
                    "postgresql+psycopg://", "postgresql://"
                ).replace("@pg:", "@127.0.0.1:")
    return None


PROD_DSN: str | None = _dsn_from_env_file()
TEST_DSN: str | None = os.environ.get("RETRIEVAL_TEST_PG_DSN") or PROD_DSN

_needs_pg = pytest.mark.skipif(
    TEST_DSN is None, reason="无可用 PG DSN（RETRIEVAL_TEST_PG_DSN / deploy/.env）"
)
_needs_prod = pytest.mark.skipif(
    PROD_DSN is None, reason="无 deploy/.env 生产 DSN（schema 对齐检查需要）"
)


# ---------------------------------------------------------------------------
# 夹具：临时 schema 内的 embed_doc 同构表
# ---------------------------------------------------------------------------

SCHEMA = "retrieval_fts_it"

DDL = f"""
-- 生产 app.embed_doc 另有 embedding vector 列；本夹具只验 FTS 路径，
-- 故意省去（普通 postgres 镜像无 pgvector，sparse SQL 也不引用该列）。
CREATE SCHEMA IF NOT EXISTS {SCHEMA};
DROP TABLE IF EXISTS {SCHEMA}.embed_doc;
CREATE TABLE {SCHEMA}.embed_doc (
    doc_id         text PRIMARY KEY,
    bundle_version text NOT NULL,
    tenant_id      text NOT NULL,
    kind           text NOT NULL,
    ref            text NOT NULL,
    text           text NOT NULL,
    tsv            tsvector
);
CREATE INDEX {SCHEMA}_gin_tsv ON {SCHEMA}.embed_doc USING gin (tsv);
"""


def _conn(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, connect_timeout=5)


@pytest.fixture(scope="module")
def pg_table() -> str:
    """建临时 schema + 夹具表，模块结束整体丢弃。需要 DDL 权限。"""
    assert TEST_DSN is not None
    try:
        with _conn(TEST_DSN) as conn:
            conn.execute(DDL)
            conn.commit()
    except psycopg.errors.InsufficientPrivilege as exc:
        pytest.skip(
            f"夹具 DSN 无 DDL 权限（用 RETRIEVAL_TEST_PG_DSN 指向可建表实例）：{exc}"
        )
    yield f"{SCHEMA}.embed_doc"
    with _conn(TEST_DSN) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.commit()


def write_doc(
    table: str,
    *,
    doc_id: str,
    text: str,
    ref: str,
    kind: str = "asset",
    tenant_id: str = "T_A",
    bundle_version: str = BUNDLE_VERSION,
) -> None:
    """**写入侧**：tsv 由 `tsvector_source()` 计算 —— N-24 的写入 half。"""
    assert TEST_DSN is not None
    with _conn(TEST_DSN) as conn:
        conn.execute(
            f"INSERT INTO {table} (doc_id, bundle_version, tenant_id, kind, ref, text, tsv)"
            " VALUES (%s, %s, %s, %s, %s, %s,"
            " to_tsvector('simple', %s))",
            (doc_id, bundle_version, tenant_id, kind, ref, text, tsvector_source(text)),
        )
        conn.commit()


def make_fetcher(table: str):
    async def fetch(sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        # psycopg 命名参数 %(name)s 形态；我们的模板用 :name（SQLAlchemy 风格）
        for key, value in params.items():
            sql = sql.replace(f":{key}", f"%({key})s")
        assert TEST_DSN is not None
        with _conn(TEST_DSN) as conn:
            cur = conn.cursor()
            cur.execute(sql, dict(params))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    return fetch


def make_sparse(table: str) -> SparseSearch:
    return SparseSearch(
        make_fetcher(table), rank_normalization=32, score_min=0.05, table=table
    )


# ---------------------------------------------------------------------------
# N-24 动态 half（真 PG，真 ts_rank_cd，真 GIN）
# ---------------------------------------------------------------------------

def test_n24_write_and_query_same_tokenizer_recall(pg_table) -> None:
    """写入与查询两侧同源 → 同一文本必召回（N-24 的完整检查方式）。"""
    write_doc(pg_table, doc_id="d1", text="直播渠道的转化率口径说明",
              ref="traffic_daily", kind="asset")

    import asyncio

    sparse = make_sparse(pg_table)
    hits = asyncio.run(sparse.search(
        "直播渠道的转化率", tenant_id="T_A", bundle_version=BUNDLE_VERSION, limit=10
    ))
    assert [h.ref for h in hits] == ["traffic_daily"]


def test_sparse_no_lexical_overlap_no_hit(pg_table) -> None:
    """词法不通 → 不硬凑：FTS 的诚实空结果（召回靠 dense/value，不靠 sparse 撒谎）。"""
    write_doc(pg_table, doc_id="d2", text="直播渠道的转化率口径说明",
              ref="traffic_daily", kind="asset")
    import asyncio

    sparse = make_sparse(pg_table)
    hits = asyncio.run(sparse.search(
        "线下门店的库存周转", tenant_id="T_A", bundle_version=BUNDLE_VERSION, limit=10
    ))
    assert hits == []


def test_ts_rank_cd_orders_by_match_density(pg_table) -> None:
    """两 doc 都含全部查询词（AND 语义），token 覆盖密度高者排前（归一化标志 32）。

    ⚠️ 实测修正（2026-09-16）：原设计用「词少的 doc 对照」在 AND 语义下根本不命中，
    且极短 doc 的 rank(=0.048) 会落进 0.05 阈值以下——那是阈值的行为，不是排序行为。
    """
    write_doc(pg_table, doc_id="d3",
              text="直播渠道GMV口径：直播渠道GMV按渠道拆分，直播渠道GMV含直播带货GMV与渠道推广GMV",
              ref="doc_dense_match", kind="asset")
    write_doc(pg_table, doc_id="d4", text="直播渠道GMV口径说明",
              ref="doc_sparse_match", kind="asset")
    import asyncio

    sparse = make_sparse(pg_table)
    hits = asyncio.run(sparse.search(
        "直播渠道GMV", tenant_id="T_A", bundle_version=BUNDLE_VERSION, limit=10
    ))
    assert hits
    assert hits[0].ref == "doc_dense_match"


def test_tenant_isolation_in_sql(pg_table) -> None:
    """N-10：SQL 层租户过滤——T_B 的查询看不到 T_A 的私有 doc。"""
    write_doc(pg_table, doc_id="d5", text="私有店铺数据",
              ref="shop_private", tenant_id="T_A")
    import asyncio

    sparse = make_sparse(pg_table)
    hits_b = asyncio.run(sparse.search(
        "私有店铺数据", tenant_id="T_B", bundle_version=BUNDLE_VERSION, limit=10
    ))
    assert hits_b == []
    hits_a = asyncio.run(sparse.search(
        "私有店铺数据", tenant_id="T_A", bundle_version=BUNDLE_VERSION, limit=10
    ))
    assert [h.ref for h in hits_a] == ["shop_private"]


def test_public_sentinel_star_visible_to_all_tenants(pg_table) -> None:
    """`'*'` 哨兵行（W2A 物化实测形态）对任意租户可见；过滤仍在 SQL 内。"""
    write_doc(pg_table, doc_id="d6", text="公共语义包资产描述",
              ref="order_paid", tenant_id="*")
    import asyncio

    sparse = make_sparse(pg_table)
    for tenant in ("T_A", "T_B"):
        hits = asyncio.run(sparse.search(
            "公共语义包资产描述", tenant_id=tenant, bundle_version=BUNDLE_VERSION, limit=10
        ))
        assert [h.ref for h in hits] == ["order_paid"], tenant


def test_bundle_version_isolates(pg_table) -> None:
    """版本过滤：旧版本 doc 不进新版查询（缓存自然失效的 DB 侧对应物）。"""
    write_doc(pg_table, doc_id="d7", text="旧版本口径文档",
              ref="old_bundle_doc", bundle_version="2026.01.01.1")
    import asyncio

    sparse = make_sparse(pg_table)
    hits = asyncio.run(sparse.search(
        "旧版本口径文档", tenant_id="T_A", bundle_version=BUNDLE_VERSION, limit=10
    ))
    assert hits == []


# ---------------------------------------------------------------------------
# 生产表冒烟（schema 对齐检查；数据填充状态只报告不断言）
# ---------------------------------------------------------------------------

@_needs_prod
def test_production_embed_doc_schema_matches_query_template() -> None:
    """07 §12.2 embed_doc 的列必须与检索 SQL 模板对齐（W2A 物化的契约面）。"""
    assert PROD_DSN is not None
    with _conn(PROD_DSN) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema='app' AND table_name='embed_doc'"
        )
        cols = {r[0] for r in cur.fetchall()}
    required = {"doc_id", "bundle_version", "tenant_id", "kind", "ref", "text", "tsv", "embedding"}
    missing = required - cols
    assert not missing, f"app.embed_doc 缺列：{missing}（W2A 物化与 07 §12.2 不一致？）"


# ---------------------------------------------------------------------------
# DoD③：真网络失败 → 显式降级（不需要 PG）
# ---------------------------------------------------------------------------

def test_dead_ollama_port_yields_explicit_degradation() -> None:
    """停 Ollama 的等价注入：死端口 → 重试耗尽 → 服务层 sparse_only + 降级载荷。"""
    view: BundleView = load_bundle_view()
    import asyncio

    async def scenario() -> tuple[bool, str | None]:
        embedder = OllamaEmbedder(
            base_url="http://127.0.0.1:59999",  # 死端口（连接拒绝）
            model="bge-m3",
            dim=1024,
            timeout_s=2,
        )
        from app.retrieval.dense import InMemoryVectorStore

        service = RetrievalService(
            view=view,
            embedder=embedder,
            vector_store=InMemoryVectorStore(),
            sparse=SparseSearch(
                _empty_fetcher, rank_normalization=32, score_min=0.05
            ),
            weights={"dense": 0.40, "sparse": 0.35, "value": 0.15, "graph": 0.10},
            rrf_k=60,
            cache=FakeCache(),
        )
        ctx = IdentityContext(
            trace_id="t", task_id="t", session_id="s", tenant_id="T_A",
            user_id="u", role=Role.ANALYST,
        )
        result = await service.search_full("订单分析", ctx, RetrievalMode.HYBRID)
        return result.degraded, None if result.degraded_reason is None else str(
            result.degraded_reason
        )

    degraded, reason = asyncio.run(scenario())
    assert degraded, "稠密不可用必须显式降级（N-21），不得静默"
    assert reason == "embedding_unavailable"


async def _empty_fetcher(sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    return []
