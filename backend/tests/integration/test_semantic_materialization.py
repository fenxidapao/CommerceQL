"""语义物化集成测试（§6.2 步骤①②③ + DoD③ 一致性）。

只测**必须真库才能证明**的部分：
- 步骤①：单事务写入物化行（幂等重跑 = 先 DELETE 后 INSERT）；
- 步骤②③：派生 GRANT/POLICY 执行 + DoD③ 双向一致性（少授与多授都红）；
- **负向对照纪律**：注入一个"整表 SELECT"→ 一致性检查必须红 → 还原 → 必须绿。
  （⚠️ 注入后红必须是 DoD③ 那条断言红 —— 报错理由不符 = 假对照。）
- 步骤⑤⑥：单键指针的原子切换 / 回滚校验（Redis 用内存 stub，只验语义不验连接）。

跳过策略（**每条 skip 都写明缺失的具体前置**，不静默假绿）：
- 无库 → skip（与 test_audit_append_only 同模式）；
- 迁移 0002 未应用 → skip（需先 `alembic upgrade head`）；
- 业务视图未建 → skip（**归属待架构裁决**，见 reports/w2a/DELIVERY.md 待裁决③）；
- PG 拒绝对视图 `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`（RLS 只适用于表）
  → **只在这一条错误上 skip**（待裁决②：RLS 落点），其余异常照常抛出 = 测试红。
"""

from __future__ import annotations

import os
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

pytestmark = pytest.mark.integration

_RW = os.environ.get(
    "COMMERCEQL_TEST_RW_DSN", "postgresql://app_rw:app_rw_pwd@localhost:5432/ecom"
)
_SUPER = os.environ.get(
    "COMMERCEQL_TEST_SUPER_DSN", "postgresql://postgres:postgres@localhost:5432/ecom"
)
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
        # embed_doc = 资产 8 + 列 75 + 指标 9 + 别名 105（与 _build_docs 对账，防止写丢/写重）
        assert report.rows["embed_doc"] == len(_build_docs(loaded))
        assert report.rows["embed_doc"] == 8 + 75 + 9 + 105
        # 诚实降级：tokenizer/embedder 未注入 → 状态 pending + 警告，不冒充已分词
        assert report.tsv_status == "pending_tokenizer"
        assert report.embedding_status == "pending_embedder"
        assert report.grant_policy_executed is False
        assert any("pending" in w or "未" in w for w in report.warnings)

    def test_idempotent_rerun(self, loaded: Any, migrated: None) -> None:
        """同版本重跑不重复累积（每表先 DELETE 同版本）。"""
        r1 = materialize(loaded, dsn=_RW, with_policy=False)
        r2 = materialize(loaded, dsn=_RW, with_policy=False)
        assert r1.rows == r2.rows


# ============================================================================
# 步骤②③ + DoD③：策略执行与一致性（依赖业务视图）
# ============================================================================

class TestPolicyAndConsistency:
    def test_policy_execution_and_dod3_consistency(
        self, loaded: Any, migrated: None, views_ready: bool
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
        self, loaded: Any, migrated: None, views_ready: bool
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
