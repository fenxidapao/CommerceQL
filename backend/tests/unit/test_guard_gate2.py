"""gate2（策略校验 + scope 四分支）单元测试（W2C）。"""

from __future__ import annotations

import pytest

from app.core.enums import Role, ScopeLevel
from app.core.errors import ContractViolationError
from app.guard.policy_gate import SHOP_LIMITED_NOTICE, run_gate2
from tests.unit.guard_fixtures import FakeSemanticBundle, build_allowlist, make_ctx


@pytest.fixture(scope="module")
def allow() -> dict:
    return build_allowlist()


@pytest.fixture(scope="module")
def bundle(allow: dict) -> FakeSemanticBundle:
    return FakeSemanticBundle(allow)


class TestHappyPath:
    def test_pass_and_scope_tenant_isolated(self, bundle) -> None:
        rep = run_gate2("SELECT o.sub_order_id FROM v_order_paid o", make_ctx(), bundle)
        assert rep.gate_result.passed
        # 分支 3：order_paid 启用 RLS → tenant_isolated，不提示、不披露
        assert rep.scope.level is ScopeLevel.TENANT_ISOLATED
        assert rep.scope.applied is True
        assert rep.scope.notice is None
        assert rep.scope.disclosable is False

    def test_unrestricted_when_non_scoped_asset_only(self, allow: dict) -> None:
        # region 资产 tenant_scoped=False（公共维表）→ 不触发分支 3
        bundle = FakeSemanticBundle(allow)
        rep = run_gate2(
            "SELECT r.code FROM v_region r", make_ctx(), bundle
        )
        assert rep.gate_result.passed
        assert rep.scope.level is ScopeLevel.UNRESTRICTED
        assert rep.scope.applied is False


class TestGate1Gate2Redundancy:
    """gate1/gate2 故意冗余（07 §7.4）—— 二次复核必须真实存在。"""

    def test_asset_recheck_rejects(self, bundle) -> None:
        rep = run_gate2("SELECT x FROM raw_order_dump LIMIT 1", make_ctx(), bundle)
        assert not rep.gate_result.passed
        assert rep.gate_result.rule_id == "G2-ASSET"

    def test_deny_column_recheck_rejects(self, bundle) -> None:
        rep = run_gate2(
            "SELECT o.receiver_phone FROM v_order_paid o", make_ctx(), bundle
        )
        assert not rep.gate_result.passed
        assert rep.gate_result.rule_id == "G2-DENY"


class TestVersionPin:
    def test_stale_snapshot_rejected(self, allow: dict) -> None:
        stale = FakeSemanticBundle(allow, version="2099.01.01.1")
        rep = run_gate2(
            "SELECT sub_order_id FROM v_order_paid LIMIT 1", make_ctx(), stale
        )
        assert not rep.gate_result.passed
        assert rep.gate_result.rule_id == "G2-VERSION"


class TestDomainScope:
    def test_domain_out_of_scope_refuses(self, allow: dict) -> None:
        bundle = FakeSemanticBundle(allow)
        ctx = make_ctx(scope_claims=("products",))  # JWT scope 只允许 products 域
        rep = run_gate2("SELECT o.sub_order_id FROM v_order_paid o", ctx, bundle)
        assert not rep.gate_result.passed
        assert rep.refuse_reason is not None
        # refuse（产品结论）与 error（工程故障）的边界 —— C-12 / 07 §7.6.1
        assert rep.refuse_reason.value == "out_of_scope"

    def test_domain_in_scope_passes(self, allow: dict) -> None:
        bundle = FakeSemanticBundle(allow)
        ctx = make_ctx(scope_claims=("orders", "products", "traffic"))
        rep = run_gate2("SELECT o.sub_order_id FROM v_order_paid o", ctx, bundle)
        assert rep.gate_result.passed

    def test_empty_scope_claims_skip_domain_check(self, bundle) -> None:
        rep = run_gate2("SELECT o.sub_order_id FROM v_order_paid o", make_ctx(), bundle)
        assert rep.gate_result.passed


class TestScopeFourBranches:
    """07 §7.4 四分支算法 —— 顺序即优先级。"""

    def test_branch1_platform_admin_unrestricted(self, allow: dict) -> None:
        bundle = FakeSemanticBundle(allow)
        ctx = make_ctx(role=Role.PLATFORM_ADMIN, shop_ids=("S1",))  # admin 优先于 shop 限制
        rep = run_gate2("SELECT o.sub_order_id FROM v_order_paid o", ctx, bundle)
        assert rep.gate_result.passed
        assert rep.scope.level is ScopeLevel.UNRESTRICTED
        assert rep.scope.applied is False

    def test_branch2_shop_ids_role_limited(self, bundle) -> None:
        ctx = make_ctx(shop_ids=("S1", "S2"))
        rep = run_gate2("SELECT o.sub_order_id FROM v_order_paid o", ctx, bundle)
        assert rep.gate_result.passed
        assert rep.scope.level is ScopeLevel.ROLE_LIMITED
        assert rep.scope.applied is True
        assert rep.scope.notice == SHOP_LIMITED_NOTICE
        assert rep.scope.disclosable is True

    def test_branch3_tenant_scoped_asset(self, bundle) -> None:
        rep = run_gate2("SELECT o.sub_order_id FROM v_order_paid o", make_ctx(), bundle)
        assert rep.scope.level is ScopeLevel.TENANT_ISOLATED
        assert rep.scope.disclosable is False  # 防存在性泄露（A.1.5 红线 3）

    def test_branch4_fallback_unrestricted(self, allow: dict) -> None:
        bundle = FakeSemanticBundle(allow)
        rep = run_gate2("SELECT r.code FROM v_region r", make_ctx(), bundle)
        assert rep.scope.level is ScopeLevel.UNRESTRICTED


class TestTenantScopedBidirectionalAssertion:
    """07 §7.4 ⚠️：tenant_scoped ⇔ 含 tenant_id 列，写反 = N-07 失效。"""

    def test_mismatched_asset_raises(self, allow: dict) -> None:
        broken = {
            **allow,
            "assets": {
                "v_order_paid": {
                    **allow["assets"]["v_order_paid"],
                    "tenant_scoped": False,  # 资产声明无 RLS，但表里有 tenant_id 列
                }
            },
        }
        bundle = FakeSemanticBundle(broken)
        with pytest.raises(ContractViolationError):
            run_gate2("SELECT o.sub_order_id FROM v_order_paid o", make_ctx(), bundle)

    def test_public_asset_without_tenant_id_ok(self, allow: dict) -> None:
        # region：tenant_scoped=False 且无 tenant_id 列 → 断言通过
        bundle = FakeSemanticBundle(allow)
        rep = run_gate2("SELECT r.code FROM v_region r", make_ctx(), bundle)
        assert rep.gate_result.passed
