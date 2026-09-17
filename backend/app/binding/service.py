"""绑定门面：把五步过滤（`filters`）+ 四层判定（`four_layer`）装配成 `BindingPort`。

归属窗口：W3C｜依据：07 附-1（端口签名）、§6.8、§18.4.1（τ 校验）、N-25 / N-27、PRD §6.3.1。

## 谁调它

W4 的 `bind` 节点。它只需要 `resolve()`；另外三个方法服务**装配期**与**观测**：

| 方法 | 谁调 | 为什么 |
|---|---|---|
| `resolve(concept, ctx, candidates)` | W4 的 bind 节点（经 `BindingPort`） | 端口契约，返回 `BindingResult` |
| `resolve_detailed(...)` | W4（需要披露文案/澄清文案/诊断时） | `BindingResult` **装不下** `disclosure` / `clarify_prompt` / `reason`（见下 D4） |
| `assert_usable_tau()` | W4 的 lifespan（启动期） | τ 配置的可校验部分 fail-fast，并回传"是否已校准"供写 gauge（U-19 §18.4.1） |
| `grain_index` | 本模块内部（懒建） | 粒度索引构建有成本，按 `active_version` 缓存（N-23） |

## 三个必须写明的读法（否则接口会被用错）

**读法 1：`resolve()` 返回的 `bindings` 在 `ambiguous` 态下是"候选选项"，不是"已绑定字段"。**
   `BindingResult` 只有 `{state, layer, bindings}` 三个字段（端口面，不可改）。于是四态里的
   `ambiguous` 只能借 `bindings` 承载澄清选项 —— 消费方**必须先看 `state`**。
   这条不变量写进单测与 `BindingOutcome.bindings_are_options`。

**读法 2：端口签名里没有问句，问句只能从请求级上下文取（D2）。**
   `resolve(concept, ctx, candidates)` 三个参数都不含问句，而**粒度判定（L2）与步③ 都需要它**。
   本实现的取法 = 读 `app.binding.context.current_binding_scope()`（`contextvars`，同 W3A 的
   `set_call_context` 形状），由 W4 在进图前设置。
   🔴 **取不到时不做任何猜测**：`question_grain=None` → 步③ 不判、L2 不参与，
   并在观测里把 `scope_was_set=False` 标出来。绝不"默认按天/按城市"。

**读法 3：`candidates` 参数只被消费其中**显式声明 `layer is L4`** 的那部分（D7）。**
   07 附-1 给了 `resolve(concept, ctx, candidates)` 这个签名，但**没有定义 `candidates` 的语义**。
   绑定层的候选**另有来源且更权威**：语义包为该概念声明的 `canonical_asset` / `candidates[]` /
   `alternatives[]`（07 §6.8 步① 明写"术语表 + 语义模型解析业务概念"）。
   两者不是一回事（前者是检索给出的字段候选，后者是语义模型的声明），因此本实现：
   - **只**从 `candidates` 里取 L4 标记项当精排分（`scores.adopt_l4_candidates`，D1(a) 双入口之一）；
   - 其余条目**计数上报**（`BindingOutcome.ignored_candidates`）而不是静默丢弃 ——
     "传进来了却被忽略"必须是**可见**的，否则 W4 会以为自己传的候选生效了。
   → 该语义待架构/ W4 确认，已登记 RELAY §D7。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final, Protocol

from app.binding.context import BindingRequestScope, current_binding_scope
from app.binding.filters import (
    BindingAttribution,
    ConceptResolution,
    FilterOutcome,
    filter_candidates,
    resolve_concept,
)
from app.binding.four_layer import LayerDecision, TauConfig, TauSettings, decide
from app.binding.grain import GrainIndex, GrainRef, SemanticReader
from app.binding.scores import ScoreOutcome, adopt_l4_candidates
from app.core.contracts import BindingResult, CandidateRef, IdentityContext
from app.core.enums import BindingLayer, BindingState
from app.core.errors import ConfigError

__all__ = [
    "BindingEvent",
    "BindingObserver",
    "BindingOutcome",
    "BindingService",
    "NullBindingObserver",
]


# ============================================================================
# 观测面（N-27 约束⑤：`binding_layer` 分布必须可观测）
# ============================================================================


@dataclass(frozen=True, slots=True)
class BindingEvent:
    """一次绑定判定的**观测快照**。

    ⚠️ 字段刻意少：指标标签只允许有界基数（`obs.metrics.BOUNDED_ALLOWED_LABELS` 里
    `binding_state`=4 / `binding_layer`=4）。**概念名与理由不进标签**（概念名是语义包级的、
    数量可增长；理由里可能带 ref）—— 它们进**日志**，不进标签。
    """

    state: BindingState
    layer: BindingLayer
    reason: str | None
    attribution: BindingAttribution | None
    #: 请求级上下文是否就绪。`False` = 本次判定的 L2 与步③ 均**未参与**（读法 2）。
    scope_was_set: bool
    #: τ 是否**已校准**（三要素齐全，含 `calibrated_at`）—— U-19：非 prod 放行但**不得隐瞒**。
    #: ⚠️ 它**不是**"打分器身份校验是否通过"：后者是 `reason` 里的 `|tau_unverified` 标记
    #: （判据 = `model_id` / `prompt_version` 是否声明）。两个布尔量用途不同，别合并。
    tau_is_calibrated: bool
    #: 端口 `candidates` 里**未被消费**的条数（读法 3）。
    ignored_candidates: int
    bundle_version: str


class BindingObserver(Protocol):
    """绑定判定的观测出口（实现者 = W4/W7 的指标+日志适配器）。

    ⚠️ **同步方法**：与 W3A 的 `DegradationSink.on_degraded` 同一取向 —— 保证
    "发观测"这一跳**永不阻塞判定路径**。`resolve()` 本身是同步的，若这里开 `async`
    就得把它变成协程，端口签名不允许（附-1 是同步签名）。
    ⚠️ 实现**不得抛异常**：观测失败不该让一次绑定判定失败。调用侧会兜住（见 `_emit`）。
    """

    def on_binding(self, event: BindingEvent) -> None: ...


class NullBindingObserver:
    """默认观测实现：**什么都不做**（`__slots__ = ()`，零状态）。

    ⚠️ 刻意不做"默认写日志"：`binding` 是 L2，直接 import `app.obs.logging` 虽然层级允许，
    但会让本模块的**每条判定路径**都依赖日志配置的可用性。默认静默 + 显式注入，
    与 W3A"默认只写日志"的差别在此登记：不接线时 N-27 约束⑤**是缺的**，
    这一点写进 DELIVERY 的"已知限制"，不假装它已被满足。
    """

    __slots__ = ()

    def on_binding(self, event: BindingEvent) -> None:  # pragma: no cover - 空实现
        return None


#: 共享实例（无状态，可安全复用）。
NULL_BINDING_OBSERVER: Final[NullBindingObserver] = NullBindingObserver()


# ============================================================================
# 判定产物：端口面 + 诊断面
# ============================================================================


@dataclass(frozen=True, slots=True)
class BindingOutcome:
    """`resolve_detailed` 的完整产物 —— `BindingResult` **装不下**的那些信息在这里。

    | 字段 | 去向 | 为什么不在端口里 |
    |---|---|---|
    | `result` | 端口返回值（进检查点、进 `query_plan`） | — |
    | `decision.disclosure` | `insight.caveats[]`（U-26 裁定的**唯一**载体） | 端口三字段无位置；且 `caveats` 不是绑定层的产物结构 |
    | `decision.clarify_prompt` | 澄清节点（W4） | 同上（FR-9.1 只问一个问题） |
    | `decision.reason` | 观测 sink | 机器可读诊断，不该进用户可见响应 |
    | `resolution` / `filtered` | 评测报告、诊断 | 体积与生命周期都不适合进检查点 |
    """

    result: BindingResult
    decision: LayerDecision
    resolution: ConceptResolution | None
    filtered: FilterOutcome
    scope_was_set: bool
    ignored_candidates: int
    bundle_version: str

    @property
    def disclosure(self) -> str | None:
        """`resolved_default` 的强制披露文案（U-26）。其余态恒为 `None`。"""
        return self.decision.disclosure

    @property
    def clarify_prompt(self) -> str | None:
        return self.decision.clarify_prompt

    @property
    def bindings_are_options(self) -> bool:
        """**读法 1 的机器化表达**：`ambiguous` 态下 `result.bindings` 是选项而非已绑定字段。

        消费方（W4）若要在 `ambiguous` 时直接用 `bindings` 生成 SQL，那是**错的** ——
        它必须走澄清。把这件事做成一问即可回答的属性，比写在文档里可靠。
        """
        return self.result.state is BindingState.AMBIGUOUS


# ============================================================================
# 门面
# ============================================================================


class BindingService:
    """`BindingPort` 的实现（07 附-1）。**同步**：端口签名如此，且确定性层不该是协程。

    构造参数全部显式注入（无全局单例、无隐式默认 reader）—— 便于 W4 用真实件、
    测试用假件，且避免"模块级单例被两个租户共享"这类问题。
    """

    __slots__ = ("_index", "_index_version", "_observer", "_reader", "_tau")

    def __init__(
        self,
        *,
        reader: SemanticReader,
        tau: TauConfig,
        observer: BindingObserver | None = None,
    ) -> None:
        self._reader = reader
        self._tau = tau
        self._observer: BindingObserver = observer or NULL_BINDING_OBSERVER
        self._index: GrainIndex | None = None
        self._index_version: str | None = None

    # ------------------------------------------------------------------
    # 装配期
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        *,
        reader: SemanticReader,
        settings: TauSettings,
        observer: BindingObserver | None = None,
    ) -> BindingService:
        return cls(reader=reader, tau=TauConfig.from_settings(settings), observer=observer)

    @property
    def tau(self) -> TauConfig:
        """τ 配置（只读）。暴露出来是因为**它是待校准参数**：观测与评测需要读它。"""
        return self._tau

    @property
    def observer(self) -> BindingObserver:
        """当前观测出口（只读）。

        暴露它有两个真实用途：① 启动期自检"到底接的是真适配器还是空实现"——
        不接线时 N-27 约束⑤ 的指标面是缺的，这个判断必须是**可查的**；
        ② 测试断言默认接线，而不必去戳私有属性。
        """
        return self._observer

    @property
    def grain_index(self) -> GrainIndex:
        """粒度索引（懒建，按 `active_version` 缓存）。

        ⚠️ 缓存键是 **bundle 版本**而不是"建过一次就够"：N-23 要求 `active_version` 切换后
        同会话内版本不漂移，而索引是**从包派生**的 —— 版本变了却复用旧索引，
        会让粒度判定按旧包做，且**不报错**（最难查的一类）。
        """
        version = self._reader.active_version()
        if self._index is None or self._index_version != version:
            self._index = GrainIndex.build(self._reader)
            self._index_version = version
        return self._index

    def assert_usable_tau(self) -> bool:
        """启动期校验 τ 中**可同步校验**的那部分；返回"是否已完整校准"。

        返回 `True` = τ 已绑 `(model_id, prompt_version)` 且有 `calibrated_at` ——
        调用方（W4 的 lifespan）据此写 `obs.metrics.set_binding_tau_calibrated(True)` 并**不打** WARN。
        返回 `False` = 未校准（U-19 §18.4.1：**非 prod 放行但不得隐瞒** →
        调用方必须打 WARN 且写 gauge 0；`APP_ENV=prod` 的拒绝在 `config.py` 已强制，不在此重复）。

        抛 `ConfigError`（**拒绝启动**）的三种情形 —— 它们都不是"放宽"，是**配置坏了**：

        | 情形 | 为什么必须拦 |
        |---|---|
        | `ε ≤ 0` | 邻域退化成单点 → N-27 约束④ 的 fail-safe 缓冲**消失**，且看不出异常（只是更容易判唯一） |
        | `τ ≤ 0` | 任何正分差都判 `resolved_unique` → L4 的判定能力被**关掉**，同样无声 |
        | 已校准但无 `report_ref` | N-25："`τ` 的每次变更必须附冻结集校准报告" → 无法复核的 τ 等于没校准 |

        ⚠️ **不在本方法里做的事**（避免第二真相）：
        ① `APP_ENV=prod` 下"未校准即拒绝启动"——已在 `config.py` 的 validator 里，不重复；
        ② 写指标 / 打 WARN —— 那是 W4 的 lifespan 动作（`obs.metrics` 的 docstring 已言明）；
        ③ 校验"实际打分器 == τ 所绑"——**启动期不可能知道**（要等第一次 LLM 响应回来），
           故它在 `TauConfig.check_binds_scorer` 里按次校验，不在启动期假装校验过。
        """
        if self._tau.epsilon <= 0:
            raise ConfigError(
                "BINDING_TAU_EPSILON 必须 > 0：ε=0 会让 τ 邻域退化成单点，"
                "N-27 约束④ 的 fail-safe 缓冲随之消失 —— 而症状只是'L4 更容易判唯一'，"
                "不会报任何错（07 §6.8.2：邻域宽度同样需校准并进 τ 配置）"
            )
        if self._tau.value <= 0:
            raise ConfigError(
                "BINDING_TAU 必须 > 0：τ=0 会让任何正分差都判 resolved_unique，"
                "等于把 L4 的判定能力关掉，且无任何报错（PRD §12.9 约束④要求失败侧偏安全）"
            )
        if self._tau.is_calibrated and not self._tau.report_ref:
            raise ConfigError(
                "BINDING_TAU 已声明校准但缺 BINDING_TAU_REPORT_REF："
                "N-25 要求 τ 的每次变更附冻结集校准报告 —— 无报告引用则无法复核，"
                "等同于未校准（且它看起来是'已校准'，更危险）"
            )
        return self._tau.is_calibrated

    # ------------------------------------------------------------------
    # 端口面（07 附-1）
    # ------------------------------------------------------------------

    def resolve(
        self, concept: str, ctx: IdentityContext, candidates: Sequence[CandidateRef]
    ) -> BindingResult:
        """`BindingPort` 实现 —— 只回端口三字段。

        ⚠️ 需要披露文案或澄清文案的调用方用 `resolve_detailed`：本方法**刻意**不把它们
        塞进 `bindings`（那会让"已绑定字段"与"说明文案"混在一个元组里，消费方分不开）。
        """
        return self.resolve_detailed(concept, ctx, candidates).result

    # ------------------------------------------------------------------
    # 诊断面
    # ------------------------------------------------------------------

    def resolve_detailed(
        self,
        concept: str,
        ctx: IdentityContext,
        candidates: Sequence[CandidateRef] = (),
        *,
        scope: BindingRequestScope | None = None,
    ) -> BindingOutcome:
        """完整链路：概念解析 → 五步过滤 → 四层判定 → 上报观测。

        `scope=None` 时取请求级上下文（读法 2）；显式传入主要用于测试与离线回放。
        """
        bundle_version = self._reader.active_version()
        active_scope = scope if scope is not None else current_binding_scope()
        index = self.grain_index

        l4, ignored = self._split_candidates(candidates)

        resolution = resolve_concept(concept, self._reader)
        if resolution is None:
            filtered = FilterOutcome(attribution=BindingAttribution.UNRESOLVED)
        else:
            filtered = filter_candidates(resolution, ctx, self._reader, index, active_scope)

        question_grain: GrainRef | None = filtered.question_grain
        decision = decide(
            resolution,
            filtered,
            grain_index=index,
            question_grain=question_grain,
            tau=self._tau,
            l4=l4,
        )
        outcome = BindingOutcome(
            result=BindingResult(
                state=decision.state, layer=decision.layer, bindings=decision.bindings
            ),
            decision=decision,
            resolution=resolution,
            filtered=filtered,
            scope_was_set=active_scope.is_set,
            ignored_candidates=ignored,
            bundle_version=bundle_version,
        )
        note = self._emit(outcome)
        if note is not None:
            # `BindingOutcome` 是 frozen：观测失败的标记必须**返回新对象**给调用方，
            # 就地改写调用方手上那个引用是徒劳的（这也是为什么把 replace 放在这里而不是 _emit 里）。
            outcome = replace(
                outcome,
                filtered=replace(outcome.filtered, notes=(*outcome.filtered.notes, note)),
            )
        return outcome

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _split_candidates(self, candidates: Sequence[CandidateRef]) -> tuple[ScoreOutcome, int]:
        """把端口 `candidates` 拆成「L4 精排分」与「本层不消费的条目」（读法 3）。

        L4 分数的适配**不在这里造轮子**：交给 `scores.adopt_l4_candidates`（D1(a) 的唯一适配缝），
        由它强制"候选必须显式声明 `layer is L4`"并校验 `[0,1]`。

        🔴 **本条路径上的打分器身份校验是"构造性"的，不是"验证性"的 —— 必须说清，否则会误以为
        N-27 约束② 已在所有路径生效。** `CandidateRef` 只有 `{asset_id, score, layer}` 三个字段，
        **没有打分器标识**；所以 `model_id` / `prompt_version` 只能取 τ 自己那一组，
        于是 `TauConfig.check_binds_scorer` 在这条路上**必然通过** —— 它在这里拦不住
        "分数其实是另一个模型/prompt 版本产出的"这件事。

        | 路径 | 身份来源 | `check_binds_scorer` 的实际效力 |
        |---|---|---|
        | 在线（`l4.score_l4`） | `LLMResponse.model` / `.prompt_version`（**实际**用的） | ✅ 真校验：不匹配即抛 |
        | 注入（本方法） | τ 自身（**无从知道**真实来源） | ⚠️ **恒通过** —— 身份正确性由**调用方**负责 |

        → 走注入路径的调用方（评测夹具、离线回溯、W2B 预计算）**必须自己保证**
        分数的来源与 τ 所绑定的 `(model_id, prompt_version)` 一致。
        根治手段是给 `CandidateRef` 补打分器标识（建议 `RerankScore` 直接进候选，或加
        `scorer_id` 字段）—— 已登记 RELAY §给 W0，**本窗口不擅自改 `core/contracts.py`**。
        """
        if not candidates:
            return ScoreOutcome(failed=True, reason="no_l4_scores_injected"), 0
        injected = [ref for ref in candidates if ref.layer is BindingLayer.L4]
        ignored = len(candidates) - len(injected)
        if not injected:
            return ScoreOutcome(failed=True, reason="no_l4_scores_injected"), ignored
        return (
            adopt_l4_candidates(
                injected,
                model_id=self._tau.model_id,
                prompt_version=self._tau.prompt_version,
            ),
            ignored,
        )

    def _emit(self, outcome: BindingOutcome) -> str | None:
        """上报观测。返回 `None` = 正常；返回字符串 = **观测失败的标记**（由调用方记进 `notes`）。

        ⚠️ 观测失败**不得让判定失败**（一次绑定判定已经算完了，观测坏掉不该回滚它）——
        但也不静默吞掉：标记会出现在 `FilterOutcome.notes` 里，在诊断面上可见。

        ⚠️ 默认 `NullBindingObserver` 什么都不做，于是"标记没人消费"。这是**已知情形**
        （见 `NullBindingObserver`）：不接线时 N-27 约束⑤ 的指标面是**缺的**，
        如实写进 DELIVERY 的已知限制，不假装已满足。
        """
        event = BindingEvent(
            state=outcome.result.state,
            layer=outcome.result.layer,
            reason=outcome.decision.reason,
            attribution=outcome.filtered.attribution,
            scope_was_set=outcome.scope_was_set,
            tau_is_calibrated=self._tau.is_calibrated,
            ignored_candidates=outcome.ignored_candidates,
            bundle_version=outcome.bundle_version,
        )
        try:
            self._observer.on_binding(event)
        except Exception as exc:  # 刻意的宽捕获：见 docstring，观测不得打断判定
            return f"observer_failed:{type(exc).__name__}"
        return None
