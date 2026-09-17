"""四层判定单测（W3C，N-01：离线）。

分六块：

| 块 | 验什么 |
|---|---|
| **τ 配置** | 六字段读入；`is_calibrated` 三要素缺一即假；绑定校验**三态**（未声明 → `False` / 匹配 → `True` / 不匹配 → **抛**） |
| **前置** | 概念解析不到 / 候选全灭 → `unresolved`（且归因进 `reason`） |
| **L1** | `alias` / `dimension` 一对一定稿；带声明的 `field_binding` **不得**被判 L1（读法 1） |
| **L2** | 同族不同层级 + 问句粒度词 → 定稿；同层级 / 跨族 / 无粒度词 / ref 判不出 → 一律不进 L2 |
| **L3** | 规范字段存活 → `resolved_default` **必带披露文案**；规范字段被淘汰 → **不得**改绑 `alternatives` |
| **L4** | `Δ ≥ τ+ε` 定稿；邻域与下方一律 `ambiguous`；解析失败 / 候选不足 fail-safe；`tau_unverified` 标记 |

外加两条**跨层不变量**：L1–L3 的分数是占位 `0.0`（只有 L4 带真分）；澄清候选 ≤ 4。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.binding.errors import BindingTauScorerMismatch
from app.binding.filters import ConceptResolution, FilterOutcome, resolve_concept
from app.binding.four_layer import MAX_CLARIFY_OPTIONS, TauConfig, decide
from app.binding.grain import GrainIndex
from app.binding.scores import RerankScore, ScoreOutcome
from app.core.enums import BindingLayer, BindingState
from app.semantics import SemanticBundleRuntime, load_bundle

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"

MODEL_ID = "deepseek-flash"
PROMPT_VERSION = "l4-score-v1"


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


@pytest.fixture(scope="module")
def index(runtime: SemanticBundleRuntime) -> GrainIndex:
    return GrainIndex.build(runtime)


# ============================================================================
# 夹具与工具
# ============================================================================


def _filtered(*refs: str) -> FilterOutcome:
    """直接构造"过滤后存活"的候选（四层判定只吃 `ordered`，五步过滤已在别处专测）。"""
    return FilterOutcome(ordered=tuple(refs))


def _tau(
    value: float = 0.20,
    epsilon: float = 0.05,
    *,
    model_id: str = MODEL_ID,
    prompt_version: str = PROMPT_VERSION,
    calibrated_at: str = "2026-09-17T00:00:00Z",
) -> TauConfig:
    return TauConfig(
        value=value,
        epsilon=epsilon,
        model_id=model_id,
        prompt_version=prompt_version,
        calibrated_at=calibrated_at,
        report_ref="reports/w3c/calibration.md",
    )


def _score(
    candidate_id: str,
    value: float,
    *,
    model_id: str = MODEL_ID,
    prompt_version: str = PROMPT_VERSION,
) -> RerankScore:
    return RerankScore(
        candidate_id=candidate_id, value=value, model_id=model_id, prompt_version=prompt_version
    )


def _l4(*pairs: tuple[str, float], **kwargs: str) -> ScoreOutcome:
    return ScoreOutcome(scores=tuple(_score(cid, val, **kwargs) for cid, val in pairs))


#: L4 不可用（解析失败 / 超时 / 未接线）—— 下游必须 fail-safe。
L4_FAILED = ScoreOutcome(failed=True, reason="parse_failed")

#: 真实包里的歧义概念：`城市`（收货城市 vs 店铺所在城市），两个候选同族不同资产、**同层级**。
CITY_A = "order_paid.receiver_city"
CITY_B = "shop.city"


def _city(runtime: SemanticBundleRuntime) -> ConceptResolution:
    res = resolve_concept("城市", runtime)
    assert res is not None and res.declared_ambiguous
    return res


# ============================================================================
# τ 配置：τ 不是自由参数，是"与打分器绑定的校准产物"
# ============================================================================


@dataclass
class _FakeSettings:
    BINDING_TAU: float = 0.33
    BINDING_TAU_EPSILON: float = 0.04
    BINDING_TAU_MODEL_ID: str = MODEL_ID
    BINDING_TAU_PROMPT_VERSION: str = PROMPT_VERSION
    BINDING_TAU_CALIBRATED_AT: str = "2026-09-16T12:00:00Z"
    BINDING_TAU_REPORT_REF: str = "reports/w3c/calibration.md"


class TestTauConfig:
    def test_from_settings_reads_all_six_fields(self) -> None:
        tau = TauConfig.from_settings(_FakeSettings())
        assert (tau.value, tau.epsilon) == (0.33, 0.04)
        assert (tau.model_id, tau.prompt_version) == (MODEL_ID, PROMPT_VERSION)
        assert tau.calibrated_at == "2026-09-16T12:00:00Z"
        assert tau.report_ref == "reports/w3c/calibration.md"
        assert tau.is_calibrated is True

    @pytest.mark.parametrize("blank", ["model_id", "prompt_version", "calibrated_at"])
    def test_is_calibrated_requires_all_three(self, blank: str) -> None:
        """打分器标识与校准时间**缺一不可** —— 缺了就不是"已校准的 τ"，只是一个数字。"""
        fields: dict[str, Any] = {
            "model_id": MODEL_ID,
            "prompt_version": PROMPT_VERSION,
            "calibrated_at": "2026-09-16T12:00:00Z",
        }
        fields[blank] = ""
        assert TauConfig(value=0.2, epsilon=0.05, **fields).is_calibrated is False

    def test_binds_scorer_true_when_identical(self) -> None:
        assert _tau().check_binds_scorer(_score(CITY_A, 0.9)) is True

    def test_unbound_tau_returns_false_instead_of_raising(self) -> None:
        """`model_id` 为空 = **未声明绑定**（U-19 放宽态）→ `False`，不抛。

        这是"没配置"与"配错了"的区分：没配置是已知的放宽，配错是缺陷。
        """
        tau = _tau(model_id="", prompt_version="")
        assert tau.is_calibrated is False
        assert tau.check_binds_scorer(_score(CITY_A, 0.9)) is False

    def test_model_mismatch_raises(self) -> None:
        with pytest.raises(BindingTauScorerMismatch) as exc:
            _tau(model_id="deepseek-v4-pro").check_binds_scorer(_score(CITY_A, 0.9))
        assert exc.value.detail["tau_model_id"] == "deepseek-v4-pro"
        assert exc.value.detail["actual_model_id"] == MODEL_ID

    def test_prompt_version_mismatch_also_raises(self) -> None:
        """**仅改 prompt** 也必须触发 —— 分数量纲随 prompt 漂移，τ 不再是同一个阈值。

        这是 N-27 约束②里最容易被人当成"过度设计"删掉的一半，故单独立一条断言。
        """
        with pytest.raises(BindingTauScorerMismatch) as exc:
            _tau(prompt_version="l4-score-v2").check_binds_scorer(_score(CITY_A, 0.9))
        assert exc.value.detail["tau_prompt_version"] == "l4-score-v2"
        assert exc.value.detail["actual_prompt_version"] == PROMPT_VERSION


# ============================================================================
# 前置：解析不到 / 候选全灭
# ============================================================================


class TestPreconditions:
    def test_concept_unresolved(self, index: GrainIndex) -> None:
        d = decide(
            None,
            _filtered(),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert (d.state, d.layer, d.reason) == (
            BindingState.UNRESOLVED,
            BindingLayer.L1,
            "concept_unresolved",
        )
        assert d.bindings == ()

    def test_all_candidates_filtered_out(self, index: GrainIndex) -> None:
        from app.binding.filters import BindingAttribution

        res = ConceptResolution(concept="x", source="alias", refs=("region.province_name",))
        d = decide(
            res,
            FilterOutcome(attribution=BindingAttribution.DENIED),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.state is BindingState.UNRESOLVED
        assert d.reason == "filtered_out:denied"

    def test_all_candidates_filtered_without_attribution(self, index: GrainIndex) -> None:
        """归因为空也要给一个**可读**的 reason，不得出现 `None`。"""
        res = ConceptResolution(concept="x", source="alias", refs=("region.province_name",))
        d = decide(
            res, FilterOutcome(), grain_index=index, question_grain=None, tau=_tau(), l4=L4_FAILED
        )
        assert d.reason == "filtered_out:unknown"


# ============================================================================
# L1：确定性映射
# ============================================================================


class TestLevel1:
    def test_alias_single_candidate_is_l1(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        res = resolve_concept("省份", runtime)
        assert res is not None and res.source == "alias"
        d = decide(
            res,
            _filtered("region.province_name"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert (d.state, d.layer) == (BindingState.RESOLVED_UNIQUE, BindingLayer.L1)
        assert d.reason == "alias_unique"
        assert d.bindings[0].asset_id == "region.province_name"

    def test_dimension_single_candidate_is_l1(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        res = resolve_concept("区域", runtime)
        assert res is not None and res.source == "dimension"
        d = decide(
            res,
            _filtered("order_paid.region_code"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert (d.state, d.layer, d.reason) == (
            BindingState.RESOLVED_UNIQUE,
            BindingLayer.L1,
            "dimension_unique",
        )

    def test_l1_wins_over_l2_question_grain(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """L1 命中就不进 L2 —— 顺序判定的核心含义（07 §6.8"前层能定则不再进入下一层"）。"""
        res = resolve_concept("省份", runtime)
        assert res is not None
        d = decide(
            res,
            _filtered("region.province_name"),
            grain_index=index,
            question_grain=index.question_level("按省份看GMV"),
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L1

    def test_declared_field_binding_goes_to_l3_not_l1(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """**读法 1**：`customer_name` 唯一映射到 `shop.shop_name`，但语义包为它声明了默认口径
        （`default_reason="主数据现值"`）→ 必须判 `resolved_default` 才能把披露文案带出去。

        若判成 `resolved_unique`，用户会在**不知情**下看到一个口径选择。
        """
        res = resolve_concept("customer_name", runtime)
        assert res is not None
        d = decide(
            res,
            _filtered("shop.shop_name"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L3
        assert d.state is BindingState.RESOLVED_DEFAULT

    def test_alias_with_two_survivors_is_not_l1(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """别名来源也只在**恰有一个**候选时才算 L1。"""
        res = resolve_concept("省份", runtime)
        assert res is not None
        d = decide(
            res,
            _filtered("region.province_name", "region.region_name"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L4
        assert d.state is BindingState.AMBIGUOUS


# ============================================================================
# L2：粒度消歧（**同族内**才比较）
# ============================================================================


class TestLevel2:
    def test_picks_the_candidate_matching_question_grain(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """候选顺序**刻意反转**：证明确实是按粒度匹配选的，不是"取第一个"。"""
        question_grain = index.question_level("按城市看GMV")
        assert question_grain is not None and question_grain.level == "city"
        d = decide(
            _city(runtime),
            _filtered("region.region_name", CITY_A),
            grain_index=index,
            question_grain=question_grain,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert (d.state, d.layer, d.reason) == (
            BindingState.RESOLVED_UNIQUE,
            BindingLayer.L2,
            "grain_disambiguated",
        )
        assert d.bindings[0].asset_id == CITY_A

    def test_region_level_question_picks_region_candidate(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        question_grain = index.question_level("按大区看GMV")
        assert question_grain is not None and question_grain.level == "region"
        d = decide(
            _city(runtime),
            _filtered(CITY_A, "region.region_name"),
            grain_index=index,
            question_grain=question_grain,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L2
        assert d.bindings[0].asset_id == "region.region_name"

    def test_question_grain_absent_skips_l2(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """07 §6.8.1：抽取失败 → **不进入 L2**（不许"默认按城市"）。"""
        d = decide(
            _city(runtime),
            _filtered(CITY_A, "region.region_name"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L4

    def test_question_grain_conflicting_with_candidates_skips_l2(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """问了"按省份"，候选里**没有**省份层级 → L2 判不出 → 不猜。"""
        question_grain = index.question_level("按省份看GMV")
        assert question_grain is not None and question_grain.level == "province"
        d = decide(
            _city(runtime),
            _filtered(CITY_A, "region.region_name"),
            grain_index=index,
            question_grain=question_grain,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L4

    def test_same_level_candidates_are_not_an_l2_case(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """两个候选**同层级**（收货城市 vs 店铺城市）→ 粒度消歧帮不上忙 → 交给 L4。

        这正是 PRD §6.3.1 举的例：L2 无力，必须澄清。
        """
        question_grain = index.question_level("按城市看GMV")
        d = decide(
            _city(runtime),
            _filtered(CITY_A, CITY_B),
            grain_index=index,
            question_grain=question_grain,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L4
        assert d.state is BindingState.AMBIGUOUS

    def test_cross_family_comparison_is_refused(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """`shop` 与 `city+region` 是**两个族** → 07 §6.8.1 禁跨族比较 → 不进 L2。"""
        question_grain = index.question_level("按城市看GMV")
        d = decide(
            _city(runtime),
            _filtered(CITY_A, "order_paid.shop_id"),
            grain_index=index,
            question_grain=question_grain,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L4

    def test_unlocatable_candidate_ref_skips_l2(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """候选 ref 判不出粒度（`order_id` 不带任何层级词）→ 不判，不许"用另一个的粒度凑"。"""
        question_grain = index.question_level("按城市看GMV")
        assert index.level_of_ref("order_paid.order_id") is None
        d = decide(
            _city(runtime),
            _filtered("order_paid.order_id", CITY_B),
            grain_index=index,
            question_grain=question_grain,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L4


# ============================================================================
# L3：默认口径（**必须披露**）
# ============================================================================


class TestLevel3:
    def test_declared_canonical_yields_resolved_default_with_disclosure(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        res = resolve_concept("customer_name", runtime)
        assert res is not None and res.canonical_ref == "shop.shop_name"
        d = decide(
            res,
            _filtered("shop.shop_name"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert (d.state, d.layer, d.reason) == (
            BindingState.RESOLVED_DEFAULT,
            BindingLayer.L3,
            "resolved_default",
        )
        assert d.disclosure == "主数据现值"
        assert d.bindings[0].asset_id == "shop.shop_name"

    def test_metric_default_binding_counts_as_l3(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """指标的 `default_binding` 同样是"声明了默认口径" → L3 + 披露。"""
        res = resolve_concept("gmv", runtime)
        assert res is not None and res.canonical_ref == "order_paid"
        d = decide(
            res,
            _filtered("order_paid"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.state is BindingState.RESOLVED_DEFAULT
        assert d.layer is BindingLayer.L3
        assert d.disclosure is not None and "pay_time" in d.disclosure

    def test_filtered_canonical_must_not_fall_back_to_alternatives(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """🔴 **本窗口修正过的一处真实缺陷**：规范字段被淘汰 → **不得**改绑 `alternatives`。

        `customer_name` 的 `alternatives` 含 `order_paid.buyer_id`（带 `use_when` 条件）。
        旧实现拿扁平 `refs` 做 L3 判据 → canonical 被 RBAC 淘汰时会**静默绑到 buyer_id**，
        却仍披露 `主数据现值` 这条属于 canonical 的口径文案 —— 用户看到"已按 X 口径"，
        实际用的是 Y。改为只认 `canonical_ref` 后：查不了 → 澄清（偏安全，N-25 的补救方向）。
        """
        res = resolve_concept("customer_name", runtime)
        assert res is not None and "order_paid.buyer_id" in res.refs
        d = decide(
            res,
            _filtered("order_paid.buyer_id"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.state is BindingState.AMBIGUOUS
        assert d.layer is BindingLayer.L4
        assert d.reason == "single_candidate_without_declaration"

    def test_declared_ambiguous_concept_never_gets_l3(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """`ambiguous: true` = 语义包**明确声明没有规范字段** → L3 不可能命中。"""
        d = decide(
            _city(runtime),
            _filtered(CITY_A, CITY_B),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is not BindingLayer.L3
        assert d.disclosure is None

    def test_source_without_declaration_never_gets_l3(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """别名来源没有 `default_reason` → 不产生披露义务，也不构成 L3。"""
        d = decide(
            resolve_concept("省份", runtime),
            _filtered("region.province_name", "region.region_name"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.layer is BindingLayer.L4


# ============================================================================
# L4：打分兜底 + fail-safe（**失败侧一律偏 ambiguous**）
# ============================================================================


class TestLevel4FailSafe:
    def test_single_candidate_without_declaration_is_ambiguous(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """**读法 4**：PRD §6.3.1 明确否决"候选数 = 1"作为唯一性判据 → 筛完只剩 1 个要澄清。"""
        d = decide(
            _city(runtime),
            _filtered(CITY_A),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=_l4((CITY_A, 0.99)),
        )
        assert d.state is BindingState.AMBIGUOUS
        assert d.reason == "single_candidate_without_declaration"

    def test_parse_failure_fails_safe(self, runtime: SemanticBundleRuntime, index: GrainIndex) -> None:
        d = decide(
            _city(runtime),
            _filtered(CITY_A, CITY_B),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.state is BindingState.AMBIGUOUS
        assert d.reason == "l4_unavailable:parse_failed"

    def test_partial_coverage_fails_safe(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """只给了一个候选的分 → 分差不可算 → 不许拿"另一个当 0 分"凑。"""
        d = decide(
            _city(runtime),
            _filtered(CITY_A, CITY_B),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=_l4((CITY_A, 0.9)),
        )
        assert d.state is BindingState.AMBIGUOUS
        assert d.reason == "l4_partial_coverage"

    def test_fail_safe_keeps_clarify_options(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """fail-safe 不是"放弃" —— 必须给出可供选择的候选与澄清问句（FR-9.1）。"""
        d = decide(
            _city(runtime),
            _filtered(CITY_A, CITY_B),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert [b.asset_id for b in d.bindings] == [CITY_A, CITY_B]
        assert d.clarify_prompt is not None and "收货城市" in d.clarify_prompt


class TestLevel4Thresholds:
    """τ=0.20 / ε=0.05 → `Δ ≥ 0.25` 定稿、`0.15 < Δ < 0.25` 落邻域、`Δ ≤ 0.15` 判不唯一。

    区间边界用例改用二进制的 τ/ε（0.25 / 0.125），理由见各用例 docstring。
    """

    def _decide_gap(
        self,
        runtime: SemanticBundleRuntime,
        index: GrainIndex,
        high: float,
        low: float,
        *,
        tau: TauConfig | None = None,
    ) -> Any:
        return decide(
            _city(runtime),
            _filtered(CITY_A, CITY_B),
            grain_index=index,
            question_grain=None,
            tau=tau or _tau(),
            l4=_l4((CITY_A, high), (CITY_B, low)),
        )

    def test_gap_above_band_resolves_unique(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        d = self._decide_gap(runtime, index, 0.80, 0.40)
        assert (d.state, d.layer) == (BindingState.RESOLVED_UNIQUE, BindingLayer.L4)
        assert d.bindings[0].asset_id == CITY_A
        assert d.reason.startswith("score_gap=0.4000>=tau+eps")

    def test_gap_exactly_at_boundary_resolves_unique(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """`Δ = τ + ε` 判**闭区间**（07 §6.8.2 约束④原文是 `≥`）。

        ⚠️ 用**二进制可精确表示**的 τ/ε/分数（0.25 / 0.125 / 0.75 − 0.375）：
        若拿 0.20 / 0.05 做边界，`0.60 - 0.35` 实际是 `0.25000000000000006`，
        测到的是浮点舍入而不是边界语义。**区间边界是二进制的，不是十进制的。**
        """
        tau = _tau(0.25, 0.125)
        d = self._decide_gap(runtime, index, 0.75, 0.375, tau=tau)
        assert d.state is BindingState.RESOLVED_UNIQUE

    def test_gap_inside_neighborhood_is_ambiguous(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """**读法 5**：邻域内一律"判不了"，即使 Δ 已经接近 τ+ε（0.24 不判唯一）。"""
        d = self._decide_gap(runtime, index, 0.60, 0.36)
        assert d.state is BindingState.AMBIGUOUS
        assert d.reason.startswith("tau_neighborhood:0.2400")

    def test_gap_equal_to_tau_is_ambiguous(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        d = self._decide_gap(runtime, index, 0.50, 0.30)
        assert d.state is BindingState.AMBIGUOUS
        assert d.reason.startswith("tau_neighborhood:0.2000")

    def test_gap_exactly_at_lower_band_edge_is_below_tau(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """`Δ = τ − ε` 落在邻域**外**（邻域 `|Δ−τ| < ε` 是开区间）→ 归"判不唯一"。

        同上看齐：`0.625 - 0.5 = 0.125` 与 `0.25 - 0.125 = 0.125` 都是精确值，
        断言才是在验"开区间"，而不是在验 IEEE-754。
        """
        tau = _tau(0.25, 0.125)
        d = self._decide_gap(runtime, index, 0.625, 0.5, tau=tau)
        assert d.state is BindingState.AMBIGUOUS
        assert d.reason.startswith("score_gap_below_tau:0.1250")

    def test_gap_far_below_tau_is_ambiguous(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        d = self._decide_gap(runtime, index, 0.30, 0.25)
        assert d.reason.startswith("score_gap_below_tau:0.0500")

    def test_unique_pick_carries_the_real_score(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        d = self._decide_gap(runtime, index, 0.91, 0.10)
        assert d.bindings[0].score == pytest.approx(0.91)
        assert d.bindings[0].layer is BindingLayer.L4

    def test_scorer_binding_is_verified_silently_when_tau_is_calibrated(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        d = self._decide_gap(runtime, index, 0.80, 0.40)
        assert "tau_unverified" not in (d.reason or "")

    def test_unbound_tau_is_flagged_in_reason(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """τ 未绑定打分器（U-19 放宽态）→ **判定照常**，但 `reason` 必须标 `tau_unverified`。

        否则观测里"校验通过"与"压根没校验"长得一模一样 —— 那正是 N-27 约束②要消除的歧义。
        """
        tau = _tau(model_id="", prompt_version="")
        d = self._decide_gap(runtime, index, 0.80, 0.40, tau=tau)
        assert d.state is BindingState.RESOLVED_UNIQUE
        assert d.reason is not None and d.reason.endswith("|tau_unverified")

    def test_mismatched_scorer_raises_instead_of_deciding(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """打分器不匹配是**配置缺陷**（会让所有 L4 结论失效）→ 必须响亮失败，不降级成澄清。"""
        with pytest.raises(BindingTauScorerMismatch):
            self._decide_gap(runtime, index, 0.80, 0.40, tau=_tau(prompt_version="l4-score-v2"))

    def test_tau_is_not_tuned_by_the_decision_layer(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """同一组分数在不同 τ 下结论不同 —— 证明 τ 是**输入**而非被本层"自动修正"的量。

        N-25 禁止下调 τ 来降低澄清率；此断言把"τ 只读"钉住。
        """
        strict = self._decide_gap(runtime, index, 0.60, 0.40, tau=_tau(0.35, 0.05))
        loose = self._decide_gap(runtime, index, 0.60, 0.40, tau=_tau(0.10, 0.05))
        assert strict.state is BindingState.AMBIGUOUS
        assert loose.state is BindingState.RESOLVED_UNIQUE


# ============================================================================
# 跨层不变量
# ============================================================================


class TestCrossLayerInvariants:
    def test_deterministic_layers_carry_placeholder_score_only(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """**不变量**：`score` 的语义只在 `layer is L4` 时有效；L1–L3 填 `0.0` 是占位。

        确定性映射没有"分" —— 若 L1 结果里出现非零分，说明有人把打分器的输出漏进了确定层。
        """
        cases: list[tuple[ConceptResolution | None, FilterOutcome, BindingLayer]] = [
            (
                resolve_concept("省份", runtime),
                _filtered("region.province_name"),
                BindingLayer.L1,
            ),
            (
                _city(runtime),
                _filtered("region.region_name", CITY_A),
                BindingLayer.L2,
            ),
            (
                resolve_concept("customer_name", runtime),
                _filtered("shop.shop_name"),
                BindingLayer.L3,
            ),
        ]
        grain = index.question_level("按城市看GMV")
        for resolution, filtered, expected_layer in cases:
            d = decide(
                resolution,
                filtered,
                grain_index=index,
                question_grain=grain if expected_layer is BindingLayer.L2 else None,
                tau=_tau(),
                l4=L4_FAILED,
            )
            assert d.layer is expected_layer, f"{expected_layer} 未按预期命中"
            assert all(b.score == 0.0 for b in d.bindings)
            assert all(b.layer is expected_layer for b in d.bindings)

    def test_clarify_options_are_capped(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """FR-9.1 / 07 §6.8："只问一个问题、候选 ≤ 4" —— 溢出部分截断而不是全抛给用户。"""
        many = tuple(f"asset{i}.col" for i in range(7))
        d = decide(
            _city(runtime),
            FilterOutcome(ordered=many),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert d.state is BindingState.AMBIGUOUS
        assert len(d.bindings) == MAX_CLARIFY_OPTIONS == 4
        assert [b.asset_id for b in d.bindings] == list(many[:4])

    def test_is_decided_only_for_resolved_states(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        resolved = decide(
            resolve_concept("省份", runtime),
            _filtered("region.province_name"),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        pending = decide(
            _city(runtime),
            _filtered(CITY_A, CITY_B),
            grain_index=index,
            question_grain=None,
            tau=_tau(),
            l4=L4_FAILED,
        )
        assert resolved.is_decided is True
        assert pending.is_decided is False

    def test_layer_is_always_reported(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """N-27 约束⑤：`binding_layer` 必须**每一次**都有值（它是指标的唯一来源）。"""
        d = decide(None, _filtered(), grain_index=index, question_grain=None, tau=_tau(), l4=L4_FAILED)
        assert isinstance(d.layer, BindingLayer)
