"""五步过滤单测（W3C，N-01：离线）。

分三块：
- **①概念解析**（真实包）：`field_binding` / `alias` / `metric` / `dimension` 四条来源 + 无解；
- **②–④过滤**：权限（角色相关！）、粒度可服务性、时间语义，各自的**归因**必须可区分；
- **⑤排序**：用假读面构造"质量分/时效不同"的候选，验证排序键是确定性的且方向正确。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.binding.context import BindingRequestScope
from app.binding.filters import (
    BindingAttribution,
    ConceptResolution,
    filter_candidates,
    resolve_concept,
)
from app.binding.grain import GrainIndex
from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.semantics import SemanticBundleRuntime, load_bundle

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


@pytest.fixture(scope="module")
def index(runtime: SemanticBundleRuntime) -> GrainIndex:
    return GrainIndex.build(runtime)


def _ctx(role: Role = Role.ANALYST) -> IdentityContext:
    return IdentityContext(
        trace_id="tr",
        task_id="tk",
        session_id="ss",
        tenant_id="t1",
        user_id="u1",
        role=role,
    )


# ============================================================================
# 第 ① 步：概念解析
# ============================================================================


class TestResolveConcept:
    def test_field_binding_wins_and_carries_disclosure_text(self, runtime: SemanticBundleRuntime) -> None:
        """`field_binding` 是唯一同时带 `canonical_asset`/`default_reason`/`ambiguous` 的来源 → 优先。"""
        res = resolve_concept("customer_name", runtime)
        assert res is not None
        assert res.source == "field_binding"
        assert res.refs[0] == "shop.shop_name"
        assert "order_paid.buyer_id" in res.refs  # alternatives 也要收
        assert res.declared_ambiguous is False
        assert res.default_reason == "主数据现值"

    def test_declared_ambiguous_keeps_candidates_and_prompt(self, runtime: SemanticBundleRuntime) -> None:
        """`城市`：**故意保留歧义** → 必须如实带出候选与澄清文案，且不得有默认口径文案。"""
        res = resolve_concept("城市", runtime)
        assert res is not None
        assert res.source == "field_binding"
        assert res.refs == ("order_paid.receiver_city", "shop.city")
        assert res.declared_ambiguous is True
        assert res.default_reason is None
        assert res.clarify_prompt is not None and "收货城市" in res.clarify_prompt

    def test_alias_column_source(self, runtime: SemanticBundleRuntime) -> None:
        res = resolve_concept("省份", runtime)
        assert res is not None
        assert (res.source, res.refs) == ("alias", ("region.province_name",))

    def test_alias_dimension_uses_dimension_binding(self, runtime: SemanticBundleRuntime) -> None:
        """`区域` 只出现在 `aliases`（`maps_to_kind=dimension`）→ 取该维度的 `binding`。"""
        res = resolve_concept("区域", runtime)
        assert res is not None
        assert (res.source, res.refs) == ("dimension", ("order_paid.region_code",))

    def test_field_binding_outranks_alias_for_same_word(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`大区` 同时是 `field_bindings[].concept` **和** dimension 类别名 → 取前者。

        这不是随意取的：`field_binding` 才带 `default_reason`（L3 的**强制披露文案**），
        取别名会丢掉"已按 X 口径"这句话（U-26 的披露链路）。
        """
        res = resolve_concept("大区", runtime)
        assert res is not None
        assert (res.source, res.refs) == ("field_binding", ("region.region_name",))
        assert res.default_reason is not None

    def test_alias_metric_source(self, runtime: SemanticBundleRuntime) -> None:
        """指标概念的绑定目标是**指标名**（物理资产与谓词由 `metric.default_binding` 给）。"""
        res = resolve_concept("gmv", runtime)
        assert res is not None
        assert (res.source, res.refs, res.metric_name) == ("metric", ("order_paid",), "gmv")
        assert res.default_reason is not None and "pay_time" in res.default_reason

    @pytest.mark.parametrize("concept", ["商品", "上个月", "淡季", "不存在的概念", "", "   "])
    def test_unresolvable_concepts_return_none(
        self, runtime: SemanticBundleRuntime, concept: str
    ) -> None:
        """表级（`asset`）/ 时间表达式 / 黑话 / 未定义 —— **一律 None，不猜**。"""
        assert resolve_concept(concept, runtime) is None


# ============================================================================
# 第 ②–⑤ 步：候选裁剪
# ============================================================================


class TestPermissionStep:
    def test_denied_column_is_dropped(self, runtime: SemanticBundleRuntime, index: GrainIndex) -> None:
        res = ConceptResolution(concept="x", source="alias", refs=("order_paid.receiver_phone",))
        outcome = filter_candidates(res, _ctx(Role.ANALYST), runtime, index, BindingRequestScope())
        assert outcome.ordered == ()
        assert outcome.attribution is BindingAttribution.DENIED

    def test_role_changes_the_verdict(self, runtime: SemanticBundleRuntime, index: GrainIndex) -> None:
        """`platform_admin` 不在 `policies[].applies_to_roles` 内 → deny 列被剔除 → 同一 ref 放行。

        🔴 **这是本窗口实测发现的一处判据分歧（已登记 RELAY §给架构）**：
        `is_denied_column(ref)`（W2C 的 AST-R07 判据，**角色无关**）对这个 ref 恒为 True，
        而 role-aware 的 `asset_allowlist(ctx)` 放行 → 于是
        **"binding 说可绑"与"gate1 R07 会拒"结论相反**。本窗口取白名单（它才是角色感知的那个），
        并把分歧如实上报，不在这里替架构裁决。
        """
        res = ConceptResolution(concept="x", source="alias", refs=("order_paid.receiver_phone",))
        outcome = filter_candidates(
            res, _ctx(Role.PLATFORM_ADMIN), runtime, index, BindingRequestScope()
        )
        assert outcome.ordered == ("order_paid.receiver_phone",)
        assert outcome.attribution is None

    @pytest.mark.parametrize("ref", ["ghost.col", "order_paid.tenant_id", "order_paid.no_such_column"])
    def test_unknown_asset_or_column_is_denied(
        self, runtime: SemanticBundleRuntime, index: GrainIndex, ref: str
    ) -> None:
        res = ConceptResolution(concept="x", source="alias", refs=(ref,))
        outcome = filter_candidates(res, _ctx(), runtime, index, BindingRequestScope())
        assert outcome.ordered == ()
        assert outcome.attribution is BindingAttribution.DENIED

    def test_metric_level_ref_is_not_blocked_here(self, runtime: SemanticBundleRuntime, index: GrainIndex) -> None:
        """指标名没有列维度 → 权限面归 gate 层（W2C）；本层不得误杀。"""
        res = ConceptResolution(concept="gmv", source="metric", refs=("order_paid",))
        outcome = filter_candidates(res, _ctx(), runtime, index, BindingRequestScope())
        assert outcome.ordered == ("order_paid",)


class TestGrainServabilityStep:
    """第 ③ 步：候选比请求**更粗** → 服务不了（更细的候选照常放行，交给 L2 选）。"""

    REFS = ("order_paid.receiver_city", "region.province_name")

    def _resolution(self) -> ConceptResolution:
        return ConceptResolution(concept="城市", source="field_binding", refs=self.REFS)

    def test_coarser_candidate_is_dropped_when_request_is_city(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        scope = BindingRequestScope(normalized_question="各城市的GMV")
        outcome = filter_candidates(self._resolution(), _ctx(), runtime, index, scope)
        assert outcome.ordered == ("order_paid.receiver_city",)
        assert outcome.dropped == (("region.province_name", BindingAttribution.GRAIN_MISMATCH),)

    def test_both_survive_when_request_is_province(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """请求粒度是 `province(3)` 时，`city(4)` **不比请求粗** → 保留（选择权在 L2，不在③）。"""
        scope = BindingRequestScope(normalized_question="各省份的GMV")
        outcome = filter_candidates(self._resolution(), _ctx(), runtime, index, scope)
        assert set(outcome.ordered) == set(self.REFS)

    def test_no_grain_word_means_no_filtering(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """抽不到粒度词 → 不判（07 §6.8.1）。**不是**"默认取最细"。"""
        outcome = filter_candidates(
            self._resolution(), _ctx(), runtime, index, BindingRequestScope(normalized_question="GMV")
        )
        assert set(outcome.ordered) == set(self.REFS)


class TestTimeSemanticsStep:
    def test_mismatch_drops_all_when_request_declares_other_semantics(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """`支付时间` 在包里声明 `transaction_time`；请求声明 `current` → 全灭并给对归因。"""
        res = ConceptResolution(concept="支付时间", source="field_binding", refs=("order_paid.pay_time",))
        outcome = filter_candidates(
            res, _ctx(), runtime, index, BindingRequestScope(time_semantics="current")
        )
        assert outcome.ordered == ()
        assert outcome.attribution is BindingAttribution.TIME_SEMANTICS_MISMATCH

    def test_matching_semantics_passes(self, runtime: SemanticBundleRuntime, index: GrainIndex) -> None:
        res = ConceptResolution(concept="支付时间", source="field_binding", refs=("order_paid.pay_time",))
        outcome = filter_candidates(
            res, _ctx(), runtime, index, BindingRequestScope(time_semantics="transaction_time")
        )
        assert outcome.ordered == ("order_paid.pay_time",)

    def test_undeclared_request_semantics_is_not_treated_as_mismatch(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """请求**没说** ≠ 不匹配 —— 把"没说"当"不匹配"会把可用候选杀光。"""
        res = ConceptResolution(concept="支付时间", source="field_binding", refs=("order_paid.pay_time",))
        outcome = filter_candidates(res, _ctx(), runtime, index, BindingRequestScope())
        assert outcome.ordered == ("order_paid.pay_time",)


class TestAttributionPrecedence:
    def test_denied_outranks_grain_mismatch(self, runtime: SemanticBundleRuntime, index: GrainIndex) -> None:
        res = ConceptResolution(
            concept="x",
            source="alias",
            refs=("order_paid.receiver_phone", "region.province_name"),
        )
        outcome = filter_candidates(
            res, _ctx(), runtime, index, BindingRequestScope(normalized_question="各城市的GMV")
        )
        assert outcome.ordered == ()
        assert outcome.attribution is BindingAttribution.DENIED

    def test_empty_refs_is_unresolved(self, runtime: SemanticBundleRuntime, index: GrainIndex) -> None:
        res = ConceptResolution(concept="x", source="alias", refs=())
        outcome = filter_candidates(res, _ctx(), runtime, index, BindingRequestScope())
        assert outcome.attribution is BindingAttribution.UNRESOLVED


# ============================================================================
# 第 ⑤ 步：排序（用假读面构造"质量分 / 时效不同"的候选）
# ============================================================================


@dataclass(frozen=True)
class _FakeAsset:
    """假资产：`physical_asset` 与 `columns` 由 `name` 派生，避免多个假资产撞进同一条白名单项。"""

    name: str
    certified: bool = True
    quality_score: float = 0.9
    freshness_sla: str = "PT24H"

    @property
    def physical_asset(self) -> str:
        return f"phys_{self.name}"

    @property
    def columns(self) -> tuple[str, ...]:
        return ("a",)


@dataclass
class _OrderingReader:
    assets_by_name: dict[str, _FakeAsset] = field(default_factory=dict)

    def active_version(self) -> str:
        return "fake.0.0.0.0"

    def dimensions(self) -> tuple[Any, ...]:
        return ()

    def dimension(self, name: str) -> Any | None:
        return None

    def field_bindings(self) -> tuple[Any, ...]:
        return ()

    def field_binding(self, concept: str) -> Any | None:
        return None

    def asset(self, logical_name: str) -> Any | None:
        return self.assets_by_name.get(logical_name)

    def asset_allowlist(self, ctx: Any) -> dict[str, Any]:
        return {
            asset.physical_asset: {"columns": asset.columns} for asset in self.assets_by_name.values()
        }

    def is_denied_column(self, ref: str) -> bool:
        return False

    def resolve_alias(self, term: str) -> Any | None:
        return None

    def metric(self, name: str) -> Any | None:
        return None

    def is_metric_active(self, name: str) -> bool:
        return False

    def assets(self) -> tuple[Any, ...]:
        return tuple(self.assets_by_name.values())


class TestOrderingStep:
    def _reader(self) -> _OrderingReader:
        return _OrderingReader(
            assets_by_name={
                "fresh": _FakeAsset(name="fresh", quality_score=0.95, freshness_sla="PT6H"),
                "stale": _FakeAsset(name="stale", quality_score=0.95, freshness_sla="P30D"),
                "lowq": _FakeAsset(name="lowq", quality_score=0.91, freshness_sla="PT6H"),
                "uncert": _FakeAsset(name="uncert", certified=False, quality_score=1.0),
            }
        )

    def test_order_is_certified_then_quality_then_freshness_then_ref(self) -> None:
        reader = self._reader()
        index = GrainIndex.build(reader)
        res = ConceptResolution(
            concept="x",
            source="alias",
            refs=("uncert.a", "lowq.a", "stale.a", "fresh.a"),
        )
        outcome = filter_candidates(res, _ctx(), reader, index, BindingRequestScope())
        assert outcome.ordered == ("fresh.a", "stale.a", "lowq.a", "uncert.a")

    def test_ordering_is_deterministic_for_equal_keys(self) -> None:
        """同分候选按 ref 字典序 —— 让结果可复现（评测要能重跑出同一条路径）。"""
        reader = _OrderingReader(assets_by_name={f"t{i}": _FakeAsset(name=f"t{i}") for i in range(3)})
        index = GrainIndex.build(reader)
        res = ConceptResolution(concept="x", source="alias", refs=("t2.a", "t0.a", "t1.a"))
        first = filter_candidates(res, _ctx(), reader, index, BindingRequestScope()).ordered
        second = filter_candidates(res, _ctx(), reader, index, BindingRequestScope()).ordered
        assert first == second == ("t0.a", "t1.a", "t2.a")

    def test_unparsable_freshness_sorts_last_not_first(self) -> None:
        """时效解析不出来 → 排最后。**当成 0 会让"解析失败"看起来最"新鲜"，与事实相反。**"""
        reader = _OrderingReader(
            assets_by_name={
                "ok": _FakeAsset(name="ok", freshness_sla="PT24H"),
                "weird": _FakeAsset(name="weird", freshness_sla="每周"),
            }
        )
        index = GrainIndex.build(reader)
        res = ConceptResolution(concept="x", source="alias", refs=("weird.a", "ok.a"))
        outcome = filter_candidates(res, _ctx(), reader, index, BindingRequestScope())
        assert outcome.ordered == ("ok.a", "weird.a")
