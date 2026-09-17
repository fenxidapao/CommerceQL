"""物化派生逻辑单测（离线部分 —— N-01；PG/Redis 侧在 integration）。

覆盖：ADR-10 派生语句的**确定性**与形状（DoD②③ 的纯函数侧）、embed_doc 组装、
诚实降级标记（tokenizer/embedder 未注入 ≠ 通过）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.semantics import load_bundle
from app.semantics.materialize import (
    PolicyStatementSet,
    _base_table,
    _build_docs,
    _q_ident,
    _qualify,
    content_sha256,
    derive_policy_statements,
)

REAL_BUNDLE = (
    Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
)


@pytest.fixture(scope="module")
def loaded() -> object:  # LoadedBundle，避免跨类型导入噪声
    return load_bundle(REAL_BUNDLE)


@pytest.fixture(scope="module")
def stmts(loaded: object) -> PolicyStatementSet:
    return derive_policy_statements(loaded)  # type: ignore[arg-type]


# ============================================================================
# 派生：CLS（GRANT SELECT(col)）
# ============================================================================

class TestDerivedGrants:
    def test_deterministic(self, loaded: object) -> None:
        """纯函数：同一包两次派生逐字节相同（DoD③ 的前提）。"""
        s1 = derive_policy_statements(loaded)  # type: ignore[arg-type]
        s2 = derive_policy_statements(loaded)  # type: ignore[arg-type]
        assert s1.all_statements() == s2.all_statements()

    def test_all_statements_schema_qualified(self, stmts: PolicyStatementSet) -> None:
        """**2026-09-17 根修锁定**：所有派生语句必须 schema 限定。

        根因（W1B 转述 §8.2 实测）：非限定名 `REVOKE ALL ON "v_order_paid"` 依赖连接的
        `search_path` 才能解析到 `app`；调用侧不带 → `UndefinedTable`（此前被 skip 盖住）。
        锁定形态：① 任何语句不得出现 ` ON "`（裸对象名）；② 每条语句都必须含 `app.` 限定。
        """
        for s in stmts.all_statements():
            assert ' ON "' not in s, f"出现非 schema 限定的对象名：{s}"
            assert "app." in s, f"语句未使用 schema 限定名：{s}"

    def test_qualify_and_base_table_mapping(self) -> None:
        """`_qualify` 与 `_base_table` 的形态锁定（供策略/检查器/迁移三方对齐）。"""
        assert _base_table("v_order_paid") == "order_paid"
        assert _base_table("no_underscore_asset") == "no_underscore_asset"  # 非 v_ 原样
        assert _qualify("v_order_paid") == 'app."v_order_paid"'
        assert _qualify("order_paid") == 'app."order_paid"'

    def test_grant_only_allowlist_columns(self, stmts: PolicyStatementSet) -> None:
        g = next(s for s in stmts.grant_sql if "v_order_paid" in s)
        assert "receiver_phone" not in g
        assert "receiver_address" not in g
        assert "tenant_id" not in g
        assert '"pay_amount"' in g

    def test_revoke_public_first(self, stmts: PolicyStatementSet) -> None:
        """§13.3：先 REVOKE ALL FROM PUBLIC 再只授允许列（顺序在 all_statements 中保证）。"""
        all_stmts = stmts.all_statements()
        revoke_idx = next(i for i, s in enumerate(all_stmts) if "v_order_paid" in s and "REVOKE" in s)
        grant_idx = next(i for i, s in enumerate(all_stmts) if "v_order_paid" in s and "GRANT" in s)
        assert revoke_idx < grant_idx

    def test_tenant_id_never_granted(self, stmts: PolicyStatementSet) -> None:
        """租户键绝不进 GRANT —— 写反 = 跨租户存在性泄露的直接路径（N-07）。"""
        assert not any("tenant_id" in s and s.startswith("GRANT") for s in stmts.grant_sql)


# ============================================================================
# 派生：RLS（CREATE POLICY）
# ============================================================================

class TestDerivedPolicies:
    def test_policy_only_for_tenant_scoped(self, stmts: PolicyStatementSet) -> None:
        """8 资产中 6 个 tenant_scoped（region/dim_date 公共）→ 6 条策略。"""
        assert len(stmts.policy_sql) == 6
        # 公共资产不得有租户策略
        assert not any("v_region" in s for s in stmts.policy_sql)
        assert not any("v_dim_date" in s for s in stmts.policy_sql)

    def test_fail_closed_guc_semantics(self, stmts: PolicyStatementSet) -> None:
        """缺省 GUC = 失败关闭：current_setting 第二参 true → NULL → 行全滤（§13.3 细节①）。

        ⚠️ v0.9（U-55 (a)）：策略建在**基表**上（`v_order_paid` → `order_paid`），
        视图上建 RLS 实测 42809 —— 本条同时锁定"目标 = 基表、非视图"的新契约。
        """
        p = next(s for s in stmts.policy_sql if '"order_paid"' in s)
        assert "current_setting('app.tenant_id', true)" in p
        assert 'ON app."order_paid"' in p and "v_order_paid" not in p

    def test_shop_ids_empty_string_semantics(self, stmts: PolicyStatementSet) -> None:
        """空串 = 不限店铺（不能用 NULL —— 经典 bug，§13.3 细节②）。"""
        p = next(s for s in stmts.policy_sql if '"order_paid"' in s)
        assert "current_setting('app.shop_ids', true) = ''" in p
        assert "string_to_array" in p

    def test_assets_without_shop_id_get_tenant_only(self, stmts: PolicyStatementSet) -> None:
        """campaign 无 shop_id 列（yaml 实测）→ 策略只含租户谓词，不发明店铺子句；
        product 有 shop_id → 含店铺子句。两者都派生自包，不写死。"""
        p_campaign = next(s for s in stmts.policy_sql if '"campaign"' in s)
        assert "shop_ids" not in p_campaign
        assert "tenant_id = current_setting('app.tenant_id', true)" in p_campaign
        p_product = next(s for s in stmts.policy_sql if '"product"' in s)
        assert "current_setting('app.shop_ids', true)" in p_product

    def test_force_rls(self, stmts: PolicyStatementSet) -> None:
        """FORCE = 表 owner 也受限 —— 缺了它 owner 直连即绕过（§13.3 模板）。

        v0.9（U-55 (a)）：ALTER TABLE 目标 = **基表** order_paid，不是视图。
        """
        rls = [s for s in stmts.rls_sql if '"order_paid"' in s]
        assert any("ENABLE ROW LEVEL SECURITY" in s for s in rls)
        assert any("FORCE ROW LEVEL SECURITY" in s for s in rls)
        assert not any("v_order_paid" in s for s in rls)


# ============================================================================
# embed_doc 组装 + 指纹
# ============================================================================

class TestDocsAndHash:
    def test_docs_deterministic_and_complete(self, loaded: object) -> None:
        docs1 = _build_docs(loaded)  # type: ignore[arg-type]
        docs2 = _build_docs(loaded)  # type: ignore[arg-type]
        assert docs1 == docs2
        # 8 资产 + 全部列 + 9 指标 + 105 别名（gold_query 归 W2B/W6 追加）
        kinds = [d["kind"] for d in docs1]
        assert kinds.count("asset") == 8
        assert kinds.count("metric") == 9
        assert kinds.count("synonym") == 105
        assert kinds.count("column") > 0
        assert not any(d["kind"] == "gold_query" for d in docs1)
        # doc_id 版本化（随指针自然失效）
        assert all(d["doc_id"].startswith("2026.09.14.1:") for d in docs1)

    def test_content_sha256_stable(self) -> None:
        h1 = content_sha256(REAL_BUNDLE)
        h2 = content_sha256(REAL_BUNDLE)
        assert h1 == h2 and len(h1) == 64


# ============================================================================
# 标识符引注
# ============================================================================

def test_q_ident_escapes() -> None:
    assert _q_ident("pay_amount") == '"pay_amount"'
    assert _q_ident('we"ird') == '"we""ird"'
