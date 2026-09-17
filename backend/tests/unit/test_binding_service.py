"""绑定门面单测（W3C，N-01：**全离线**）。

六块：

| 块 | 验什么 |
|---|---|
| **端口契约** | `BindingService` 结构上满足 `core.contracts.BindingPort`；返回的 `bindings` 在 `ambiguous` 下是**选项**（读法 1） |
| **上下文取用** | 问句来自 `contextvars`；未设置时 `question_grain=None` 且 `scope_was_set=False`（读法 2） |
| **候选拆分** | 只有 `layer is L4` 的条目被消费；其余**计数上报**不静默丢弃（读法 3 / D7） |
| **L4 两条路** | 在线路径身份来自响应（真校验）；注入路径身份取自 τ（**恒通过**，如实断言） |
| **τ 启动校验** | ε≤0 / τ≤0 / 已校准但无报告引用 → `ConfigError`；未校准 → 返回 `False` 不抛 |
| **观测与缓存** | 观测事件字段正确；观测抛异常**不影响判定**且留下 note；粒度索引按包版本缓存 |
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.binding.context import (
    BindingRequestScope,
    clear_binding_scope,
    set_binding_scope,
)
from app.binding.filters import BindingAttribution
from app.binding.four_layer import TauConfig
from app.binding.service import (
    NULL_BINDING_OBSERVER,
    BindingEvent,
    BindingService,
    NullBindingObserver,
)
from app.core.contracts import BindingPort, CandidateRef, IdentityContext
from app.core.enums import BindingLayer, BindingState, Role
from app.core.errors import ConfigError
from app.semantics import SemanticBundleRuntime, load_bundle

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"

MODEL_ID = "deepseek-flash"
PROMPT_VERSION = "l4_score_v1"
CALIBRATED_AT = "2026-09-17T00:00:00Z"


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


@pytest.fixture(autouse=True)
def _clean_scope() -> Any:
    """每个用例前后清上下文 —— `contextvars` 会跨用例残留（同一个测试线程）。"""
    clear_binding_scope()
    yield
    clear_binding_scope()


def _tau(
    *,
    value: float = 0.20,
    epsilon: float = 0.05,
    model_id: str = MODEL_ID,
    prompt_version: str = PROMPT_VERSION,
    calibrated_at: str = CALIBRATED_AT,
    report_ref: str = "reports/w3c/calibration.md",
) -> TauConfig:
    return TauConfig(
        value=value,
        epsilon=epsilon,
        model_id=model_id,
        prompt_version=prompt_version,
        calibrated_at=calibrated_at,
        report_ref=report_ref,
    )


def _ctx(role: Role = Role.ANALYST) -> IdentityContext:
    return IdentityContext(
        trace_id="tr", task_id="tk", session_id="ss", tenant_id="t1", user_id="u1", role=role
    )


def _service(runtime: SemanticBundleRuntime, **kwargs: Any) -> BindingService:
    kwargs.setdefault("tau", _tau())
    return BindingService(reader=runtime, **kwargs)


@dataclass
class _RecordingObserver:
    events: list[BindingEvent] = field(default_factory=list)
    raises: Exception | None = None

    def on_binding(self, event: BindingEvent) -> None:
        if self.raises is not None:
            raise self.raises
        self.events.append(event)


@dataclass
class _VersionedReader:
    """`active_version` 可变的假读面 —— 只用来测索引缓存，其余方法转发真 reader。"""

    inner: SemanticBundleRuntime
    version: str = "v1"

    def active_version(self) -> str:
        return self.version

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


# ============================================================================
# 一、端口契约
# ============================================================================


class TestPortContract:
    def test_service_structurally_satisfies_binding_port(self, runtime: SemanticBundleRuntime) -> None:
        """`BindingPort` 是 `runtime_checkable` Protocol → 结构符合即可（无需继承）。"""
        assert isinstance(_service(runtime), BindingPort)

    def test_resolve_returns_port_triple(self, runtime: SemanticBundleRuntime) -> None:
        result = _service(runtime).resolve("省份", _ctx(), ())
        assert (result.state, result.layer) == (BindingState.RESOLVED_UNIQUE, BindingLayer.L1)
        assert result.bindings[0].asset_id == "region.province_name"

    def test_ambiguous_bindings_are_options_not_fields(self, runtime: SemanticBundleRuntime) -> None:
        """**读法 1**：`ambiguous` 态下 `bindings` 是澄清选项 —— 直接用它们生成 SQL 是错的。"""
        outcome = _service(runtime).resolve_detailed("城市", _ctx())
        assert outcome.result.state is BindingState.AMBIGUOUS
        assert outcome.bindings_are_options is True
        assert [b.asset_id for b in outcome.result.bindings] == [
            "order_paid.receiver_city",
            "shop.city",
        ]
        assert outcome.clarify_prompt is not None

    def test_resolved_default_exposes_disclosure(self, runtime: SemanticBundleRuntime) -> None:
        """`resolved_default` 必须能拿到披露文案（U-26 的 `insight.caveats[]` 来源）。"""
        outcome = _service(runtime).resolve_detailed("customer_name", _ctx())
        assert outcome.result.state is BindingState.RESOLVED_DEFAULT
        assert outcome.disclosure == "主数据现值"
        assert outcome.bindings_are_options is False

    def test_unresolvable_concept_yields_unresolved(self, runtime: SemanticBundleRuntime) -> None:
        outcome = _service(runtime).resolve_detailed("不存在的概念", _ctx())
        assert outcome.result.state is BindingState.UNRESOLVED
        assert outcome.resolution is None
        assert outcome.filtered.attribution is BindingAttribution.UNRESOLVED

    def test_resolved_result_never_carries_disclosure(self, runtime: SemanticBundleRuntime) -> None:
        """`resolved_unique` 没有披露义务 —— 有文案就说明 L3 判据被误用了。"""
        outcome = _service(runtime).resolve_detailed("省份", _ctx())
        assert outcome.disclosure is None


# ============================================================================
# 二、上下文取用（读法 2）
# ============================================================================


class TestRequestScope:
    def test_scope_unset_means_no_question_grain(self, runtime: SemanticBundleRuntime) -> None:
        """未接线 → `question_grain=None`（步③ 不判、L2 不参与），且**如实标出**。"""
        outcome = _service(runtime).resolve_detailed("城市", _ctx())
        assert outcome.scope_was_set is False
        assert outcome.filtered.question_grain is None

    def test_scope_set_drives_question_grain(self, runtime: SemanticBundleRuntime) -> None:
        set_binding_scope(BindingRequestScope(normalized_question="按城市看 GMV"))
        outcome = _service(runtime).resolve_detailed("城市", _ctx())
        assert outcome.scope_was_set is True
        assert outcome.filtered.question_grain is not None
        assert outcome.filtered.question_grain.level == "city"

    def test_explicit_scope_argument_overrides_contextvar(self, runtime: SemanticBundleRuntime) -> None:
        """显式传入的 scope 优先 —— 离线回放/测试必须能钉住输入，不受环境残留影响。"""
        set_binding_scope(BindingRequestScope(normalized_question="按大区看 GMV"))
        outcome = _service(runtime).resolve_detailed(
            "城市", _ctx(), scope=BindingRequestScope(normalized_question="按城市看 GMV")
        )
        assert outcome.filtered.question_grain is not None
        assert outcome.filtered.question_grain.level == "city"

    def test_blank_question_counts_as_unset(self, runtime: SemanticBundleRuntime) -> None:
        """`BindingRequestScope(normalized_question="  ")` 与"没设置"等价（`is_set` 的判据）。"""
        set_binding_scope(BindingRequestScope(normalized_question="   "))
        outcome = _service(runtime).resolve_detailed("城市", _ctx())
        assert outcome.scope_was_set is False

    def test_question_grain_flows_into_filtering(self, runtime: SemanticBundleRuntime) -> None:
        """粒度词真的参与了步③：问"按省份"而候选是 region 层级（更粗）→ 该候选被淘汰。

        `城市` 的两个候选都是 `city`(4)，比 `province`(3) **更细** → 服务得了，不被淘汰；
        这条断言确认的是"筛完之后仍有两个候选"，即步③ 没有误杀。
        """
        set_binding_scope(BindingRequestScope(normalized_question="按省份看 GMV"))
        outcome = _service(runtime).resolve_detailed("城市", _ctx())
        assert len(outcome.filtered.ordered) == 2


# ============================================================================
# 三、候选拆分（读法 3 / D7）
# ============================================================================


class TestCandidateSplitting:
    def test_non_l4_candidates_are_counted_not_silently_dropped(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """端口 `candidates` 里非 L4 的条目会被忽略 —— 但必须**可见**（计数）。"""
        candidates = (
            CandidateRef(asset_id="order_paid.receiver_city", score=0.9, layer=None),
            CandidateRef(asset_id="shop.city", score=0.8, layer=BindingLayer.L1),
        )
        outcome = _service(runtime).resolve_detailed("城市", _ctx(), candidates)
        assert outcome.ignored_candidates == 2
        assert outcome.result.state is BindingState.AMBIGUOUS

    def test_l4_candidates_are_consumed_and_can_resolve(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """注入式 L4：候选顺序**刻意反转**（低分在前）→ 仍应选中高分那个。"""
        candidates = (
            CandidateRef(asset_id="shop.city", score=0.30, layer=BindingLayer.L4),
            CandidateRef(asset_id="order_paid.receiver_city", score=0.90, layer=BindingLayer.L4),
        )
        outcome = _service(runtime).resolve_detailed("城市", _ctx(), candidates)
        assert outcome.result.state is BindingState.RESOLVED_UNIQUE
        assert outcome.result.layer is BindingLayer.L4
        assert outcome.result.bindings[0].asset_id == "order_paid.receiver_city"
        assert outcome.ignored_candidates == 0

    def test_mixed_candidates_consume_only_l4(self, runtime: SemanticBundleRuntime) -> None:
        candidates = (
            CandidateRef(asset_id="shop.city", score=0.80, layer=None),
            CandidateRef(asset_id="order_paid.receiver_city", score=0.90, layer=BindingLayer.L4),
            CandidateRef(asset_id="shop.city", score=0.30, layer=BindingLayer.L4),
        )
        outcome = _service(runtime).resolve_detailed("城市", _ctx(), candidates)
        assert outcome.ignored_candidates == 1
        assert outcome.result.state is BindingState.RESOLVED_UNIQUE
        assert outcome.result.bindings[0].asset_id == "order_paid.receiver_city"

    def test_l4_scores_must_cover_every_surviving_candidate(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """只给一个候选的分（另一个缺失）→ **不做部分采纳** → fail-safe 澄清。

        分差吃的是"最高 − 次高"：缺一个候选的分，就可能把"两个几乎并列"误读成"一个明显占优"，
        而后者直接产出 `resolved_unique`。宁澄清不猜（N-27 约束④）。
        """
        candidates = (
            CandidateRef(asset_id="order_paid.receiver_city", score=0.90, layer=BindingLayer.L4),
            CandidateRef(asset_id="order_paid.receiver_city", score=0.10, layer=BindingLayer.L4),
        )
        outcome = _service(runtime).resolve_detailed("城市", _ctx(), candidates)
        assert outcome.result.state is BindingState.AMBIGUOUS
        assert outcome.decision.reason is not None
        assert outcome.decision.reason.startswith("l4_partial_coverage")

    def test_empty_candidates_falls_back_to_clarify(self, runtime: SemanticBundleRuntime) -> None:
        outcome = _service(runtime).resolve_detailed("城市", _ctx(), ())
        assert outcome.result.state is BindingState.AMBIGUOUS
        assert outcome.ignored_candidates == 0

    def test_out_of_range_injected_score_is_rejected(self, runtime: SemanticBundleRuntime) -> None:
        """越界分在**唯一适配缝**就被拦下 → 不静默截断，直接落 fail-safe。"""
        candidates = (
            CandidateRef(asset_id="shop.city", score=1.4, layer=BindingLayer.L4),
            CandidateRef(asset_id="order_paid.receiver_city", score=0.9, layer=BindingLayer.L4),
        )
        outcome = _service(runtime).resolve_detailed("城市", _ctx(), candidates)
        assert outcome.result.state is BindingState.AMBIGUOUS


# ============================================================================
# 四、L4 两条路的校验强度不同（如实断言，不粉饰）
# ============================================================================


class TestTwoL4Paths:
    def test_injected_path_identity_is_tau_itself_so_check_is_vacuous(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """🔴 **注入路径的 τ 绑定校验恒通过** —— 它不是验证，是构造。

        `CandidateRef` 没有打分器标识字段，`adopt_l4_candidates` 只能填 τ 自己那一组。
        本条用例把这件事**钉成断言**，免得后来者以为 N-27 约束② 在所有路径都生效了。
        根治手段 = 给候选补打分器标识（已登记 RELAY §给 W0）。
        """
        tau = _tau(model_id="某个未必是真实来源的模型", prompt_version="某个未必是真实的版本")
        candidates = (
            CandidateRef(asset_id="shop.city", score=0.30, layer=BindingLayer.L4),
            CandidateRef(asset_id="order_paid.receiver_city", score=0.90, layer=BindingLayer.L4),
        )
        outcome = BindingService(reader=runtime, tau=tau).resolve_detailed("城市", _ctx(), candidates)
        # 校验"通过"了，尽管分数可能来自完全另一个打分器 —— 这正是要暴露的事实
        assert outcome.result.state is BindingState.RESOLVED_UNIQUE
        assert outcome.result.layer is BindingLayer.L4

    def test_uncalibrated_but_identified_tau_still_resolves_and_is_not_marked(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """**两个布尔量不是一回事** —— 本条把它们区分开：

        | 判据 | 问的问题 | 本用例的取值 |
        |---|---|---|
        | `TauConfig.is_calibrated` | τ 是否经冻结集校准（三要素含 `calibrated_at`） | **False**（无校准时间） |
        | `TauConfig.check_binds_scorer` 的返回 | 打分器**身份**是否已声明且匹配 | **True**（身份声明了） |

        于是：`calibrated_at` 为空时**不该**出现 `tau_unverified` —— 身份校验确实跑了、也确实通过了。
        把"未校准"标成"未校验"会让观测里两个不同的信号混成一个（U-19 的告警面就失真了）。
        """
        tau = _tau(calibrated_at="")
        assert tau.is_calibrated is False
        candidates = (
            CandidateRef(asset_id="shop.city", score=0.30, layer=BindingLayer.L4),
            CandidateRef(asset_id="order_paid.receiver_city", score=0.90, layer=BindingLayer.L4),
        )
        outcome = BindingService(reader=runtime, tau=tau).resolve_detailed("城市", _ctx(), candidates)
        assert outcome.result.state is BindingState.RESOLVED_UNIQUE
        assert outcome.decision.reason == "score_gap=0.6000>=tau+eps"

    def test_fully_unbound_tau_makes_the_injected_path_unavailable(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """🔴 τ 连"打分器是谁"都没声明时，**注入路径必然不可用** —— 这是 fail-safe，不是缺陷。

        根因是 `RerankScore` **要求**携带 `(model_id, prompt_version)`（N-27 约束②：
        没有身份的分不可比）。注入路径没有别的地方能拿到身份，只能取 τ 的；
        τ 空 → 构造失败 → `ScoreOutcome(failed=True)` → 澄清。

        ⇒ 连带结论：`|tau_unverified` 标记**在这条路上不可能出现**（空 τ 更早就失败了）。
        它只在**在线路径**可达 —— 那里分数带着 `LLMResponse` 的真实身份，
        于是"τ 未声明身份"与"声明了且匹配"才成为两个可分辨的状态。

        ⚠️ 实际影响：**非 prod 下用注入路径做评测时，必须至少声明 `BINDING_TAU_MODEL_ID` 与
        `BINDING_TAU_PROMPT_VERSION`**（`CALIBRATED_AT` 可留空 = 上面那条"未校准但可用"形态）。
        否则 L4 恒不可用 → 所有歧义都成澄清 → 澄清率爆表、评测无意义。
        """
        tau = _tau(model_id="", prompt_version="", calibrated_at="")
        candidates = (
            CandidateRef(asset_id="shop.city", score=0.30, layer=BindingLayer.L4),
            CandidateRef(asset_id="order_paid.receiver_city", score=0.90, layer=BindingLayer.L4),
        )
        outcome = BindingService(reader=runtime, tau=tau).resolve_detailed("城市", _ctx(), candidates)
        assert outcome.result.state is BindingState.AMBIGUOUS
        assert outcome.decision.reason is not None
        assert outcome.decision.reason.startswith("l4_unavailable:score_invalid")


# ============================================================================
# 五、τ 启动校验（可同步校验的那部分）
# ============================================================================


class TestAssertUsableTau:
    def test_calibrated_tau_returns_true(self, runtime: SemanticBundleRuntime) -> None:
        assert _service(runtime).assert_usable_tau() is True

    def test_uncalibrated_tau_returns_false_without_raising(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """U-19 §18.4.1：非 prod 放行、**但不得隐瞒** —— 由调用方据此写 WARN + gauge 0。

        （`APP_ENV=prod` 下的拒绝启动已在 `config.py` 强制，本方法不重复实现。）
        """
        service = _service(runtime, tau=_tau(model_id="", prompt_version="", calibrated_at=""))
        assert service.assert_usable_tau() is False

    def test_zero_epsilon_is_refused(self, runtime: SemanticBundleRuntime) -> None:
        """ε=0 → 邻域退化成单点，fail-safe 缓冲消失，且**不报任何错**。"""
        with pytest.raises(ConfigError) as exc:
            _service(runtime, tau=_tau(epsilon=0.0)).assert_usable_tau()
        assert "BINDING_TAU_EPSILON" in exc.value.message

    def test_zero_tau_is_refused(self, runtime: SemanticBundleRuntime) -> None:
        """τ=0 → 任何正分差都判唯一 = 把 L4 的判定能力关掉。"""
        with pytest.raises(ConfigError) as exc:
            _service(runtime, tau=_tau(value=0.0)).assert_usable_tau()
        assert "BINDING_TAU" in exc.value.message

    def test_calibrated_without_report_ref_is_refused(self, runtime: SemanticBundleRuntime) -> None:
        """N-25：τ 的每次变更必须附冻结集校准报告 —— 无引用则无法复核。"""
        with pytest.raises(ConfigError) as exc:
            _service(runtime, tau=_tau(report_ref="")).assert_usable_tau()
        assert "REPORT_REF" in exc.value.message

    def test_from_settings_matches_direct_construction(self, runtime: SemanticBundleRuntime) -> None:
        @dataclass
        class _S:
            BINDING_TAU: float = 0.2
            BINDING_TAU_EPSILON: float = 0.05
            BINDING_TAU_MODEL_ID: str = MODEL_ID
            BINDING_TAU_PROMPT_VERSION: str = PROMPT_VERSION
            BINDING_TAU_CALIBRATED_AT: str = CALIBRATED_AT
            BINDING_TAU_REPORT_REF: str = "reports/w3c/calibration.md"

        service = BindingService.from_settings(reader=runtime, settings=_S())
        assert (service.tau.value, service.tau.epsilon) == (0.2, 0.05)
        assert service.assert_usable_tau() is True


# ============================================================================
# 六、观测出口与粒度索引缓存
# ============================================================================


class TestObserver:
    def test_event_is_emitted_with_metric_labels(self, runtime: SemanticBundleRuntime) -> None:
        recorder = _RecordingObserver()
        _service(runtime, observer=recorder).resolve("省份", _ctx(), ())
        assert len(recorder.events) == 1
        event = recorder.events[0]
        assert (event.state, event.layer) == (BindingState.RESOLVED_UNIQUE, BindingLayer.L1)
        assert event.reason == "alias_unique"
        assert event.scope_was_set is False
        assert event.tau_is_calibrated is True
        assert event.bundle_version == "2026.09.14.1"

    def test_event_carries_no_unbounded_label_content(self, runtime: SemanticBundleRuntime) -> None:
        """`BindingEvent` **不得**含概念名/问句/租户 —— 标签只允许有界基数。"""
        recorder = _RecordingObserver()
        set_binding_scope(BindingRequestScope(normalized_question="按城市看 GMV"))
        _service(runtime, observer=recorder).resolve_detailed("城市", _ctx(), ())
        event = recorder.events[0]
        field_names = set(vars(event)) if not hasattr(event, "__slots__") else set(event.__slots__)
        assert "concept" not in field_names
        assert "normalized_question" not in field_names
        assert "tenant_id" not in field_names
        assert not any("按城市" in str(getattr(event, name)) for name in field_names)

    def test_observer_failure_does_not_break_the_decision(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """观测坏掉不该让一次已经算完的判定失败 —— 但也不静默吞（留下 note）。"""
        recorder = _RecordingObserver(raises=RuntimeError("metrics backend down"))
        outcome = _service(runtime, observer=recorder).resolve_detailed("省份", _ctx())
        assert outcome.result.state is BindingState.RESOLVED_UNIQUE
        assert "observer_failed:RuntimeError" in outcome.filtered.notes

    def test_successful_observation_leaves_no_note(self, runtime: SemanticBundleRuntime) -> None:
        outcome = _service(runtime, observer=_RecordingObserver()).resolve_detailed("省份", _ctx())
        assert outcome.filtered.notes == ()

    def test_null_observer_is_the_default_and_is_stateless(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """默认接的是**空实现** —— 这件事必须可查，否则无法判断 N-27 约束⑤ 是否已接线。"""
        service = _service(runtime)
        assert isinstance(service.observer, NullBindingObserver)
        assert NullBindingObserver.__slots__ == ()
        # 共享实例而非每次新建：无状态，且"是不是同一个"能证明没人在构造期塞状态
        assert service.observer is NULL_BINDING_OBSERVER


class TestGrainIndexCache:
    def test_index_is_reused_for_the_same_bundle_version(self, runtime: SemanticBundleRuntime) -> None:
        service = _service(runtime)
        assert service.grain_index is service.grain_index

    def test_index_is_rebuilt_when_bundle_version_changes(self, runtime: SemanticBundleRuntime) -> None:
        """N-23：索引是**从包派生**的 —— 版本变了还复用旧索引，粒度判定会按旧包做且不报错。"""
        reader = _VersionedReader(inner=runtime, version="v1")
        service = BindingService(reader=reader, tau=_tau())
        first = service.grain_index
        reader.version = "v2"
        assert service.grain_index is not first

    def test_index_reports_the_derived_bundle_version(self, runtime: SemanticBundleRuntime) -> None:
        assert _service(runtime).grain_index.bundle_version == "2026.09.14.1"


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class TestPackageFacade:
    """包门面自证。

    🔴 存在的理由：**在此之前没有任何测试 import 过 `app.binding`**（全部走 `app.binding.xxx`
    子模块）。于是 `__init__.py` 里一个拼错的名字、一条漏掉的 import、一个循环依赖，
    都能一路静默到 W4 接线时才炸 —— 而那时排查成本最高。
    """

    def test_every_exported_name_resolves(self) -> None:
        import app.binding as pkg

        missing = [name for name in pkg.__all__ if not hasattr(pkg, name)]
        assert missing == [], f"`__all__` 列了但模块上没有（拼错或漏 import）：{missing}"

    def test_dunder_all_follows_the_three_group_convention(self) -> None:
        """`__all__` 分三组、每组内按 ASCII 序，且组序固定为 **常量 → 类 → 函数**。

        ⚠️ 别用 `sorted(pkg.__all__)` 一把梭：ASCII 下 `'L'(76) < 'a'(97)`，一把梭会把三组
        混成一组，与本仓库其它包的既有风格不符。分组有序才有意义 —— 新加名字时漏登记一眼可见。
        """
        import app.binding as pkg

        names = list(pkg.__all__)
        groups: dict[str, list[str]] = {"常量": [], "类": [], "函数": []}
        for name in names:
            obj = getattr(pkg, name)
            if isinstance(obj, type):
                groups["类"].append(name)
            elif name[:1].isupper():
                groups["常量"].append(name)
            else:
                groups["函数"].append(name)

        assert all(groups.values()), f"三组都该非空：{ {k: len(v) for k, v in groups.items()} }"
        for label, group in groups.items():
            assert group == sorted(group), f"{label}组未按 ASCII 序：{group}"
        assert names == groups["常量"] + groups["类"] + groups["函数"]

    def test_calibration_offline_api_is_reachable_from_the_facade(self) -> None:
        """W6 的离线执行器从这里一个入口拿全 —— 也顺带保证 `calibration` 不会腐坏。"""
        # 刻意在用例内 import：拿不到时 pytest 直接指到这一行，比模块级 import 失败更直白
        from app.binding import (
            CalibrationReport,
            ScoreSample,
            assess_stability,
            calibrate,
            kendall_tau_b,
            sweep,
        )

        assert all(callable(f) for f in (calibrate, sweep, assess_stability, kendall_tau_b))
        assert (ScoreSample.__name__, CalibrationReport.__name__) == ("ScoreSample", "CalibrationReport")

    def test_importing_the_package_does_not_pull_in_the_llm_gateway(self) -> None:
        """R-DEP-2 / FR-3.2 的**运行时**镜像（`lint-imports` 查的是静态 import 图）。

        用**干净解释器**跑：同进程的 `sys.modules` 会被其它测试文件污染（它们会 import
        `app.llm`），那样断言恒假红。故必须 `subprocess`。
        """
        code = (
            "import sys, app.binding;"
            "print(sorted(m for m in sys.modules if m == 'app.llm' or m.startswith('app.llm.')))"
        )
        # 固定 argv、无 shell、无外部输入 —— 不需要 S603 豁免（该规则本仓库未启用，写 noqa 反被 RUF100 抓）
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"干净解释器 import app.binding 失败：{proc.stderr}"
        assert proc.stdout.strip() == "[]", f"绑定包把 LLM 网关拖进来了：{proc.stdout.strip()}"
