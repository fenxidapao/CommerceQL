"""语义物化集成测试（§6.2 步骤①②③ + DoD③ 一致性 + U-123 防破坏性幂等）。

只测**必须真库才能证明**的部分：
- 步骤①：单事务写入物化行（幂等重跑 = 先 DELETE 后 INSERT；
  ⚠️ `embed_doc` 例外 —— U-123：缺派生器时**整体跳过**，见 TestU123NoDestructiveIdempotence）；
- 步骤②③：派生 GRANT/POLICY 执行 + DoD③ 双向一致性（少授与多授都红）；
- **负向对照纪律**：注入一个"整表 SELECT"→ 一致性检查必须红 → 还原 → 必须绿。
  （⚠️ 注入后红必须是 DoD③ 那条断言红 —— 报错理由不符 = 假对照。）
- 步骤⑤⑥：单键指针的原子切换 / 回滚校验（Redis 用内存 stub，只验语义不验连接）。

跳过策略（**每条 skip 都写明缺失的具体前置**，不静默假绿）：
- 无库 → skip（与 test_audit_append_only 同模式）；
- ⚠️ **DSN 只认环境变量**（U-114 防线①）：缺 `COMMERCEQL_TEST_*_DSN` =
  **import 期当场 fail**（共享守卫 `tests/integration/_env_dsn.py`），
  禁止 skip、禁止共享库字面默认值。请指向**一次性测试库**。
- 迁移 0002 未应用 → skip（需先 `alembic upgrade head`）；
- 业务视图未建 → skip（**归属待架构裁决**，见 reports/w2a/DELIVERY.md 待裁决③）；
- PG 拒绝对视图 `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`（RLS 只适用于表）
  → **只在这一条错误上 skip**（待裁决②：RLS 落点），其余异常照常抛出 = 测试红。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.semantics import load_bundle
from app.semantics.materialize import (
    SemanticMaterializeError,
    _build_docs,
    assert_grant_policy_consistency,
    get_active_version,
    materialize,
    rollback_to,
    switch_version,
)
from tests.integration._env_dsn import env_dsn

pytestmark = pytest.mark.integration

_RW = env_dsn("COMMERCEQL_TEST_RW_DSN")
_SUPER = env_dsn("COMMERCEQL_TEST_SUPER_DSN")
_POINTER_KEY = "semantic:active_version"  # 测试内固定字面量；生产由 cache.keys.active_version() 注入

REAL_BUNDLE = (
    Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
)


class _StubRedis:
    """内存 stub：只验证 switch/get/rollback 的**语义**（键值读写），不验证连接。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def get(self, key: str) -> str | None:
        return self._data.get(key)


@pytest.fixture(scope="module")
def rw_conn() -> Any:  # psycopg.Connection
    try:
        conn = psycopg.connect(_RW, connect_timeout=3)
    except Exception as exc:
        pytest.skip(f"集成环境不可用（{type(exc).__name__}）→ 不计为通过")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def loaded() -> Any:  # LoadedBundle
    return load_bundle(REAL_BUNDLE)


@pytest.fixture(scope="module")
def migrated(rw_conn: Any) -> None:
    """前置：迁移 0002 已应用（semantic_bundle 表存在）。"""
    row = rw_conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'app' AND table_name = 'semantic_bundle'
        """
    ).fetchone()
    if not row or not row[0]:
        pytest.skip("迁移 0002 未应用（app.semantic_bundle 不存在）→ 先 alembic upgrade head")


@pytest.fixture(scope="module")
def views_ready(rw_conn: Any) -> bool:
    """业务视图是否已建（**归属待架构裁决**，建了才能执行 GRANT 语句）。"""
    row = rw_conn.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'app' AND table_name = 'v_order_paid'
        """
    ).fetchone()
    return bool(row and row[0])


# ============================================================================
# 步骤①：物化行写入（不依赖业务视图）
# ============================================================================

class TestMaterializeRows:
    def test_insert_rows_and_honest_degradation(
        self, loaded: Any, migrated: None
    ) -> None:
        report = materialize(loaded, dsn=_RW, with_policy=False)
        assert report.version == "2026.09.14.1"
        assert report.rows["asset"] == 8
        assert report.rows["metric_def"] == 9
        assert report.rows["dimension"] == 6
        assert report.rows["synonym"] == 105
        # U-123：缺派生器 ⇒ embed_doc **整体跳过删插**（连 DELETE 都不做），不是插 NULL 行
        assert report.rows["embed_doc"] == 0
        assert report.doc_count == 0
        # 诚实降级：tokenizer/embedder 未注入 → 状态具名 PENDING + 警告（U-123 判据①④）
        assert report.tsv_status == "pending_tokenizer"
        assert report.embedding_status == "pending_embedder"
        assert report.grant_policy_executed is False
        assert any("跳过" in w and "embed_doc" in w for w in report.warnings)

    def test_idempotent_rerun(self, loaded: Any, migrated: None) -> None:
        """同版本重跑不重复累积（每表先 DELETE 同版本）。"""
        r1 = materialize(loaded, dsn=_RW, with_policy=False)
        r2 = materialize(loaded, dsn=_RW, with_policy=False)
        assert r1.rows == r2.rows


# ============================================================================
# U-123：缺派生器的 materialize 不得破坏性清空 embed_doc（2026-09-22，P0）
# ============================================================================

_EMBEDDING_DIM = 1024  # 迁移 0002 `EMBEDDING_DIM`（ADR-06 bge-m3）；假 embedder 必须对齐维度


class TestU123NoDestructiveIdempotence:
    @staticmethod
    def _tokenizer(text: str) -> list[str]:
        return text.split()

    @staticmethod
    def _embedder(texts: list[str]) -> list[list[float]]:
        return [[0.125] * _EMBEDDING_DIM for _ in texts]

    def test_rematerialize_without_derivers_preserves_derived_data(
        self, loaded: Any, migrated: None
    ) -> None:
        """判据②（正向断言，修复前必红）：带派生器物化 → 缺派生器重物化 → 派生列仍在。

        修复前的形态：第二次 materialize 对同版本 embed_doc 先 DELETE 再插 NULL 行
        ⇒ count(embedding) 归零 —— 即 2026-09-22 共享库 embed_doc 一天被清两轮的
        生产件自毁路径（arch RELAY §24.1）。
        """
        docs = _build_docs(loaded)
        r1 = materialize(
            loaded, dsn=_RW, with_policy=False,
            tokenizer=self._tokenizer, embedder=self._embedder,
        )
        assert r1.embedding_status == "embedded"
        assert r1.tsv_status == "tokenized"
        assert r1.rows["embed_doc"] == len(docs)

        r2 = materialize(loaded, dsn=_RW, with_policy=False)  # 缺派生器
        assert r2.tsv_status == "pending_tokenizer"
        assert r2.embedding_status == "pending_embedder"
        assert r2.rows["embed_doc"] == 0  # 跳过（PENDING），不是静默插 NULL（判据①/④）

        try:
            with psycopg.connect(_RW, connect_timeout=3) as conn:
                n_rows, n_emb, n_tsv = conn.execute(
                    """
                    SELECT count(*), count(embedding), count(tsv)
                    FROM app.embed_doc WHERE bundle_version = %s
                    """,
                    (loaded.version,),
                ).fetchone()
            assert n_rows == len(docs), "embed_doc 行数被改 = 破坏性幂等（U-123）"
            assert n_emb == len(docs), "embedding 被清 NULL = 破坏性幂等（U-123 判据②）"
            assert n_tsv == len(docs), "tsv 被清 NULL = 破坏性幂等（U-123 判据②）"
        finally:
            # 收尾卫生：本测试写入的是假向量，不留在库里
            with psycopg.connect(_RW, connect_timeout=3) as conn:
                conn.execute(
                    "DELETE FROM app.embed_doc WHERE bundle_version = %s", (loaded.version,)
                )
                conn.commit()

    def test_idempotent_rerun_with_derivers(self, loaded: Any, migrated: None) -> None:
        """带派生器的幂等重跑：行数一致且派生列不丢（全量写路径的幂等性）。"""
        r1 = materialize(
            loaded, dsn=_RW, with_policy=False,
            tokenizer=self._tokenizer, embedder=self._embedder,
        )
        r2 = materialize(
            loaded, dsn=_RW, with_policy=False,
            tokenizer=self._tokenizer, embedder=self._embedder,
        )
        assert r1.rows == r2.rows
        assert r2.rows["embed_doc"] == len(_build_docs(loaded))
        with psycopg.connect(_RW, connect_timeout=3) as conn:
            n_emb = conn.execute(
                "SELECT count(embedding) FROM app.embed_doc WHERE bundle_version = %s",
                (loaded.version,),
            ).fetchone()
        assert n_emb[0] == r2.rows["embed_doc"]
        # 收尾卫生：清掉假向量
        with psycopg.connect(_RW, connect_timeout=3) as conn:
            conn.execute(
                "DELETE FROM app.embed_doc WHERE bundle_version = %s", (loaded.version,)
            )
            conn.commit()


# ============================================================================
# 步骤②③ + DoD③：策略执行与一致性（依赖业务视图）
# ============================================================================

class TestPolicyAndConsistency:
    def test_policy_execution_and_dod3_consistency(
        self, loaded: Any, migrated: None, views_ready: bool, rw_conn: Any
    ) -> None:
        if not views_ready:
            pytest.skip(
                "业务视图未建（PG 侧 DDL 归属待架构裁决，见 reports/w2a/DELIVERY.md 待裁决③）"
            )
        try:
            materialize(loaded, dsn=_RW, with_policy=True)
        except psycopg.errors.WrongObjectType as exc:
            # 只在这一条已知未决错误上跳过：PG 的 RLS 不适用于视图（待裁决②：RLS 落点）
            pytest.skip(f"RLS 落点缺口（视图不支持 RLS，待架构裁决②）：{exc}")
        report = assert_grant_policy_consistency(rw_conn, loaded)
        assert report.checked_assets == 8
        assert report.consistent, f"DoD③ 不一致：{report.mismatches}"

    def test_negative_injection_revoke_must_red(
        self, loaded: Any, migrated: None, views_ready: bool, rw_conn: Any
    ) -> None:
        """注入：把 v_product 的授权降成整表以外的错（直接 REVOKE 全部列授权）→ DoD③ 必红。

        ⚠️ 看清红的**确实是** assert_grant_policy_consistency 的 mismatch 断言，
        不是别的异常 —— 否则就是假对照。
        """
        if not views_ready:
            pytest.skip("业务视图未建（待裁决③），无法注入授权扰动")
        try:
            materialize(loaded, dsn=_RW, with_policy=True)
        except psycopg.errors.WrongObjectType as exc:
            pytest.skip(f"RLS 落点缺口（待裁决②）：{exc}")

        with psycopg.connect(_SUPER, connect_timeout=3) as super_conn:
            super_conn.execute('REVOKE ALL ON app."v_product" FROM app_ro')
            super_conn.commit()

        report = assert_grant_policy_consistency(rw_conn, loaded)
        assert not report.consistent, "注入后仍一致 = 检查器失效（假绿灯）"
        assert any("v_product" in m for m in report.mismatches)

        # 还原：重新物化（REVOKE ALL + 重派生 GRANT，ADR-10 同源）→ 必绿
        materialize(loaded, dsn=_RW, with_policy=True)
        report2 = assert_grant_policy_consistency(rw_conn, loaded)
        assert report2.consistent, f"还原后仍红：{report2.mismatches}"

    def test_negative_injection_base_table_grant_must_red(
        self, loaded: Any, migrated: None, views_ready: bool, rw_conn: Any
    ) -> None:
        """注入 2（U-55(a) 前提 2）：app_ro 对**基表**被授权 → 检查器必须红。

        RLS 仍挡行，但 CLS 列白名单可经基表绕过 —— 这是 (a) 方案唯一的静默越权形态。
        基表未建（U-56 迁移未落）时 skip，就绪后自动转为真检查。
        """
        if not views_ready:
            pytest.skip("业务视图未建（待裁决③），无法注入授权扰动")
        try:
            materialize(loaded, dsn=_RW, with_policy=True)
        except psycopg.errors.WrongObjectType as exc:
            pytest.skip(f"RLS 落点缺口（待裁决②）：{exc}")

        has_base = rw_conn.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'app' AND table_name = 'order_paid'
            """
        ).fetchone()[0]
        if not has_base:
            pytest.skip("基表 order_paid 未建（U-56 迁移未落）→ 前提 2 检查空洞放行，非已验证")

        with psycopg.connect(_SUPER, connect_timeout=3) as super_conn:
            super_conn.execute('GRANT SELECT ON app."order_paid" TO app_ro')
            super_conn.commit()

        report = assert_grant_policy_consistency(rw_conn, loaded)
        assert not report.consistent, "基表授权注入后仍一致 = 前提 2 检查器失效（假绿灯）"
        assert any("基表" in m for m in report.mismatches)

        # 还原 → 必绿
        with psycopg.connect(_SUPER, connect_timeout=3) as super_conn:
            super_conn.execute('REVOKE ALL ON app."order_paid" FROM app_ro')
            super_conn.commit()
        report2 = assert_grant_policy_consistency(rw_conn, loaded)
        assert report2.consistent, f"还原后仍红：{report2.mismatches}"


# ============================================================================
# 步骤⑤⑥：单键指针（stub Redis 验语义）
# ============================================================================

class TestVersionPointer:
    def test_switch_get_roundtrip(self, loaded: Any, migrated: None) -> None:
        r = _StubRedis()
        assert get_active_version(r, key=_POINTER_KEY) is None  # 未发布 = 如实 None
        switch_version(r, loaded.version, key=_POINTER_KEY)
        assert get_active_version(r, key=_POINTER_KEY) == "2026.09.14.1"

    def test_rollback_requires_existing_version(
        self, loaded: Any, migrated: None
    ) -> None:
        r = _StubRedis()
        rollback_to(r, _RW, loaded.version, key=_POINTER_KEY)  # 已物化版本 → 可回滚
        with pytest.raises(SemanticMaterializeError, match="不存在"):
            rollback_to(r, _RW, "9999.99.99.9", key=_POINTER_KEY)
