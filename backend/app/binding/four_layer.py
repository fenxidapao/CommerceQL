"""四层顺序判定（07 §6.8 下半 / PRD §6.3.1）—— `binding` 的**核心**。

归属窗口：W3C｜依据：07 §6.8 表 + §6.8.2（含 5 条硬约束）、PRD §6.3.1 / §12.9、N-27。

| 层 | 判据（本模块的落地） | 输出态 |
|---|---|---|
| **L1 确定性映射** | 概念经**别名/维度**命中且过滤后**恰有一个**候选 | `resolved_unique` |
| **L2 粒度消歧** | 多候选**粒度不同**且**问句含粒度词**，恰有一个候选的层级等于问句层级 | `resolved_unique` |
| **L3 默认口径** | 语义包为该概念**声明了** `canonical_asset`（或指标的 `default_binding`）且**非 ambiguous** | `resolved_default`（**必须披露**） |
| **L4 打分兜底** | 以上均不成立 → 精排分差 `Δ ≥ τ + ε` | `resolved_unique` / `ambiguous` |
| — | 概念解析不到，或候选全被 ②/③/④ 过滤 | `unresolved` |

## 五个必须写明的读法（每一条都可能被挑战，故逐条给理由）

**读法 1：`field_binding` 来源的非歧义概念走 L3 而不是 L1 —— 因为它必须披露。**
   `customer_name` 唯一映射到 `shop.shop_name`，看起来"唯一"就是 L1。但语义包为它声明了
   `default_reason="主数据现值"`，而 PRD 要求"命中默认口径**必须标注已按 X 口径**"。
   ⇒ 判 `resolved_default` 才能把披露文案带出去。若判 `resolved_unique`，用户会在**不知情**下
   看到一个口径选择 —— 那正是 07 §6.8 说的"比报错更危险"。

**读法 2：`alias` / `dimension` 来源走 L1。**
   这两个来源在语义包里是**一对一**声明（别名表 loader 已断言无重复 term），
   没有"默认口径"的概念，故不产生披露义务。

**读法 3：`declared_ambiguous` 的概念**允许**被 L4 判成 `resolved_unique`。**
   `ambiguous: true` 在 SCHEMA §5.2 里的含义是"**没有规范字段**"（⇒ L3 不可能命中），
   而**不是**"禁止 L4 判唯一"。07 §6.8 的 L4 行是无条件的"以上均不成立 → 精排分差"。
   实测收敛性：`城市`（收货城市 vs 店铺所在城市）温度=0 下两分接近 → 落在 τ 邻域 → `ambiguous`，
   与 PRD §6.3.1 的期望（必须澄清）一致。**本读法已登记待架构确认**（见 RELAY）。

**读法 4：L4 需要 ≥2 个可比候选；只剩 1 个且无 L1/L3 声明依据 → 判 `ambiguous`。**
   依据是 PRD §6.3.1 的开篇原话："**'唯一'是结果描述，不是可执行判据**；若字面解读为
   '候选数必须 = 1'，则任何存在同义字段的域都会触发澄清"。既然"候选数 = 1"被明确否决为判据，
   那么"筛完只剩 1 个"就**不构成**唯一性证明 —— 没有声明、也没有分差，只能澄清（偏安全）。

**读法 5：τ 邻域的含义是"判不了"，不是"离阈值远所以更可信"。**
   按 07 §6.8.2 约束④：`Δ ≥ τ + ε` → `resolved_unique`；`Δ ≤ τ − ε` → `ambiguous`；
   `|Δ − τ| < ε` → **`ambiguous`（邻域内不得猜）**。三个区间互斥且穷尽。

**读法 6：L3 只认 `canonical_ref`，不认 `refs`；τ 未**声明打分器身份**时 `reason` 必须带 `tau_unverified`。**
   前者理由见 `_try_level3`（拿 `refs` 判会静默改绑未验证的 `alternatives`）。
   后者是 N-27 约束②的**观测面**：`check_binds_scorer` 的 `False` 表示
   "τ 没有声明打分器身份、本次分差未被校验"，这与"校验通过"是两件事 ——
   不落进 `reason` 就等于把未校验当成通过。
   ⚠️ **别把它与"τ 未校准"混为一谈**：判据不同（前者看 `model_id`/`prompt_version`，
   后者看三要素含 `calibrated_at`）、消费方也不同（前者进 `reason`，后者进启动 WARN + gauge）。

## 与 N-25 的张力（07 §6.8.2 已给答案，此处不重开）

读法 4/读法 5 都会**倾向于澄清**，而 NFR-7.1 给澄清率设了 ≤15% 上限。
二者不矛盾：**L4 频繁触发导致澄清率超限时的第一补救是回看语义层**
（补别名 → L1 / 定 `canonical_asset` → L3），**不是放宽 τ、更不是把 fail-safe 改成偏乐观**。
本模块**不提供**任何"降低澄清率"的开关 —— 那种开关的存在本身就是 R-19 的成因。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from app.binding.errors import BindingTauScorerMismatch
from app.binding.filters import ConceptResolution, FilterOutcome
from app.binding.grain import GrainIndex, GrainRef
from app.binding.scores import RerankScore, ScoreOutcome
from app.core.contracts import CandidateRef
from app.core.enums import BindingLayer, BindingState

__all__ = [
    "MAX_CLARIFY_OPTIONS",
    "GapBand",
    "GapVerdict",
    "LayerDecision",
    "TauConfig",
    "classify_gap",
    "decide",
    "tau_from_settings",
]

#: 澄清候选上限（FR-9.1 / 07 §6.8："只问一个问题、候选 ≤ 4"）。
MAX_CLARIFY_OPTIONS = 4


class TauSettings(Protocol):
    """τ 配置读面（实现者 = `app.core.config.Settings`）。

    ⚠️ `value` / `epsilon` **必须与 `model_id` + `prompt_version` 一起**才有意义：
    τ 是待校准参数，分数量纲随打分器（**含 prompt 版本**）漂移（PRD §6.3.1 / N-27 约束②）。
    """

    BINDING_TAU: float
    BINDING_TAU_EPSILON: float
    BINDING_TAU_MODEL_ID: str
    BINDING_TAU_PROMPT_VERSION: str
    BINDING_TAU_CALIBRATED_AT: str
    BINDING_TAU_REPORT_REF: str


@dataclass(frozen=True, slots=True)
class TauConfig:
    """τ / ε 及其**打分器绑定**（PRD §6.3.1 的 `{model_id, prompt_version, value, calibrated_at, report_ref}`）。"""

    value: float
    epsilon: float
    model_id: str = ""
    prompt_version: str = ""
    calibrated_at: str = ""
    report_ref: str = ""

    @classmethod
    def from_settings(cls, settings: TauSettings) -> TauConfig:
        return cls(
            value=float(settings.BINDING_TAU),
            epsilon=float(settings.BINDING_TAU_EPSILON),
            model_id=str(settings.BINDING_TAU_MODEL_ID),
            prompt_version=str(settings.BINDING_TAU_PROMPT_VERSION),
            calibrated_at=str(settings.BINDING_TAU_CALIBRATED_AT),
            report_ref=str(settings.BINDING_TAU_REPORT_REF),
        )

    @property
    def is_calibrated(self) -> bool:
        """是否已绑定打分器**且**附有校准时间（与 `Settings.binding_tau_is_calibrated` 同判据）。"""
        return bool(self.model_id and self.prompt_version and self.calibrated_at)

    def check_binds_scorer(self, score: RerankScore) -> bool:
        """校验**实际使用的打分器**与 τ 所绑定的是同一个（N-27 约束②）。

        返回 `True` = 校验通过；`False` = **τ 未声明打分器身份**（`model_id` / `prompt_version`
        为空），此时"未校验"这件事必须体现在观测里，不得静默；抛异常 = 声明了却不匹配（**真缺陷**）。

        ⚠️ **返回 `False` 与 `is_calibrated is False` 是两件事，不要混**（术语陷阱，已实测踩到）：

        | 判据 | 问的问题 | 消费方 |
        |---|---|---|
        | `is_calibrated` | τ 是否经冻结集校准（三要素含 `calibrated_at`） | U-19 的启动 WARN + gauge |
        | 本方法的返回 | 打分器**身份**是否已声明且与本次一致 | L4 的 `reason`（`\\|tau_unverified` 标记） |

        `calibrated_at` 为空**不影响**本方法 —— 身份声明了、也匹配了，校验就是真跑过了。
        把它标成"未校验"会把两个不同信号混成一个，U-19 的告警面随之失真。

        ⚠️ 抛的是**异常**而不是"判 ambiguous"：两者性质不同 ——
        "分数不好"是本次查询的结论（澄清）；"τ 绑的不是这个打分器"是**配置缺陷**，
        它会让**所有** L4 结论都失去意义，必须响亮地失败（`BindingTauScorerMismatch`）。
        """
        if not (self.model_id and self.prompt_version):
            return False
        if score.model_id != self.model_id or score.prompt_version != self.prompt_version:
            raise BindingTauScorerMismatch(
                f"τ 绑定打分器 ({self.model_id}, {self.prompt_version}) "
                f"≠ 本次实际打分器 ({score.model_id}, {score.prompt_version}) —— "
                "仅改 prompt 也会导致分数量纲漂移，必须**重新校准** τ（不是改 τ 的值）"
                "（PRD §6.3.1 / N-27 约束②）",
                detail={
                    "tau_model_id": self.model_id,
                    "tau_prompt_version": self.prompt_version,
                    "actual_model_id": score.model_id,
                    "actual_prompt_version": score.prompt_version,
                },
            )
        return True


@dataclass(frozen=True, slots=True)
class LayerDecision:
    """四层判定的结果 —— 可直接映射到 `BindingResult`，另带**不进 API** 的诊断信息。

    ⚠️ `reason` / `disclosure` / `clarify_prompt` 三个字段的去向**不同**，不得混：
    | 字段 | 去向 | 为什么 |
    |---|---|---|
    | `reason` | 观测 sink（日志/指标） | 机器可读的诊断标签（"哪一层、为什么"），**不进** `BindingResult`（端口装不下，见 RELAY D4） |
    | `disclosure` | `insight.caveats[]`（U-26 裁定的**唯一**载体） | `resolved_default` 的强制披露文案；**禁止**塞进 `scope.notice` |
    | `clarify_prompt` | 澄清节点（W4） | FR-9.1 只问一个问题；候选列表由 `bindings` 给出（≤4） |
    """

    state: BindingState
    layer: BindingLayer
    bindings: tuple[CandidateRef, ...] = ()
    reason: str | None = None
    disclosure: str | None = None
    clarify_prompt: str | None = None

    @property
    def is_decided(self) -> bool:
        """是否可直接生成 SQL（`resolved_unique` / `resolved_default` → 门禁 A 档）。"""
        return self.state in (BindingState.RESOLVED_UNIQUE, BindingState.RESOLVED_DEFAULT)


class GapBand(StrEnum):
    """分差落在 τ 的哪个区间（07 §6.8.2 约束④ 的三个互斥且穷尽的区间）。"""

    ABOVE = "above"  # Δ ≥ τ + ε → 判唯一
    NEIGHBORHOOD = "neighborhood"  # |Δ − τ| < ε → **判不了**
    BELOW = "below"  # Δ ≤ τ − ε → 判不唯一


@dataclass(frozen=True, slots=True)
class GapVerdict:
    """分差判定的结果（**纯函数产物**，无副作用、无依赖）。"""

    gap: float
    band: GapBand
    state: BindingState


def classify_gap(gap: float, tau: TauConfig) -> GapVerdict:
    """把 `Δ = 最高分 − 次高分` 归到 τ 的三个区间之一 —— **区间判据的唯一实现**。

    🔴 **为什么必须抽出来共用**：`calibration.py` 的 τ 扫描要吃**同一个判据**。
    若校准脚本自己再写一遍"Δ ≥ τ+ε 就判唯一"，那么校准报告描述的是一个**可能已漂移的**规则 ——
    而"校准结果与实际行为不一致"恰恰是最难发现的一类问题（报告是绿的，线上是另一个行为）。
    故扫描与运行时都走本函数。

    ⚠️ 三个区间互斥且穷尽（ε > 0 时）：
    `Δ ≥ τ+ε` → `ABOVE`；`|Δ−τ| < ε` → `NEIGHBORHOOD`；
    剩下即 `Δ < τ+ε 且 |Δ−τ| ≥ ε` ⟺ `Δ ≤ τ−ε` → `BELOW`。
    `ε = 0` 会让 `NEIGHBORHOOD` 永不可达（邻域退化成单点）—— 那是坏配置，
    `BindingService.assert_usable_tau` 在启动期就拒绝（见该方法的理由表）。
    """
    if gap >= tau.value + tau.epsilon:
        return GapVerdict(gap=gap, band=GapBand.ABOVE, state=BindingState.RESOLVED_UNIQUE)
    if abs(gap - tau.value) < tau.epsilon:
        return GapVerdict(gap=gap, band=GapBand.NEIGHBORHOOD, state=BindingState.AMBIGUOUS)
    return GapVerdict(gap=gap, band=GapBand.BELOW, state=BindingState.AMBIGUOUS)


def _candidate(ref: str, layer: BindingLayer, score: float = 0.0) -> CandidateRef:
    """构造绑定引用。

    ⚠️ **`score` 的语义只在 `layer is L4` 时有效**；L1–L3 填 `0.0` 是**占位**，
    因为那三层本来就没有分数（确定性映射没有"分"）。调用方读 `score` 前**必须先看 `layer`** ——
    这条不变量写进单测。登记：`CandidateRef` 缺"分数来源"字段，建议补 `score_kind`（RELAY §给 W0）。
    """
    return CandidateRef(asset_id=ref, score=score, layer=layer)


def decide(
    resolution: ConceptResolution | None,
    filtered: FilterOutcome,
    *,
    grain_index: GrainIndex,
    question_grain: GrainRef | None,
    tau: TauConfig,
    l4: ScoreOutcome,
) -> LayerDecision:
    """按 L1 → L2 → L3 → L4 **顺序**判定，前一层能定则不再进入下一层（07 §6.8 表）。"""
    # —— 前置：概念解析不到 / 候选全灭 ——
    if resolution is None:
        return LayerDecision(
            state=BindingState.UNRESOLVED, layer=BindingLayer.L1, reason="concept_unresolved"
        )
    if not filtered.ordered:
        return LayerDecision(
            state=BindingState.UNRESOLVED,
            layer=BindingLayer.L1,
            reason=f"filtered_out:{filtered.attribution or 'unknown'}",
        )

    # —— L1：别名 / 维度 一对一命中（走 readme 读法 2） ——
    if resolution.source in ("alias", "dimension") and len(filtered.ordered) == 1:
        return LayerDecision(
            state=BindingState.RESOLVED_UNIQUE,
            layer=BindingLayer.L1,
            bindings=(_candidate(filtered.ordered[0], BindingLayer.L1),),
            reason=f"{resolution.source}_unique",
        )

    # —— L2：多候选、粒度不同、问句说了粒度 ——
    l2 = _try_level2(filtered.ordered, grain_index, question_grain)
    if l2 is not None:
        return LayerDecision(
            state=BindingState.RESOLVED_UNIQUE,
            layer=BindingLayer.L2,
            bindings=(_candidate(l2, BindingLayer.L2),),
            reason="grain_disambiguated",
        )

    # —— L3：声明了规范字段且非歧义（**必须披露**） ——
    l3 = _try_level3(resolution, filtered.ordered)
    if l3 is not None:
        ref, disclosure = l3
        return LayerDecision(
            state=BindingState.RESOLVED_DEFAULT,
            layer=BindingLayer.L3,
            bindings=(_candidate(ref, BindingLayer.L3),),
            reason="resolved_default",
            disclosure=disclosure,
        )

    # —— L4：打分兜底（唯一可调 τ 的一层）；必要时 fail-safe 判 ambiguous ——
    return _level4(resolution, filtered.ordered, tau=tau, l4=l4)


# ============================================================================
# L2 / L3 / L4
# ============================================================================


def _try_level2(
    ordered: tuple[str, ...], grain_index: GrainIndex, question_grain: GrainRef | None
) -> str | None:
    """L2：**同族内**、多候选粒度不同、且恰有一个候选的层级 == 问句层级 → 选它。

    四道"不判"的闸门（任一不满足即返回 `None`，退回 L3/L4 —— 07 §6.8.1"抽取失败 → 不进入 L2"）：
    ① 问句粒度判不出来；② 候选数 < 2；③ 候选层级判不出来或跨族；④ 候选层级都相同（同粒度才是竞争）。
    """
    if question_grain is None or len(ordered) < 2:
        return None
    grains: list[GrainRef] = []
    for ref in ordered:
        grain = grain_index.level_of_ref(ref)
        if grain is None or grain.family != question_grain.family:
            return None  # 跨族 / 判不出 → 不判（禁止跨族比较）
        grains.append(grain)
    if len({grain.value for grain in grains}) < 2:
        return None  # 全部同粒度 → 不构成 L2 的"粒度差异"，退回 L3/L4
    matches = [ref for ref, grain in zip(ordered, grains, strict=True) if grain.level == question_grain.level]
    return matches[0] if len(matches) == 1 else None


def _try_level3(
    resolution: ConceptResolution, ordered: tuple[str, ...]
) -> tuple[str, str | None] | None:
    """L3：语义包**声明了**规范字段 / 指标默认绑定，且概念**非 `ambiguous`**。

    ⚠️ 返回值里的候选必须是**过滤后仍存活**的**那一个规范字段** —— 声明存在但被权限/粒度过滤掉时
    **不构成 L3 命中**（不能"因为包里有声明"就绑一个查不了的字段）。

    ⚠️ 判据是 `canonical_ref`，**不是** `refs`。`refs` 把 `canonical_asset` / `candidates` /
    `alternatives` 混在一个元组里（`_refs_of_field_binding`），用它做 L3 判据会在
    canonical 被 RBAC 淘汰时**静默改绑 alternatives** —— 而 alternatives 每条都带 `use_when`
    条件（"当 X 时用它"），我们并没有求值它。那等于**用一个没验证过的口径，披露另一条口径的文案**。
    查不了 → 交给澄清（N-25：补救方向是回看语义包，不是替用户猜）。
    """
    if resolution.declared_ambiguous or not resolution.default_reason:
        return None
    canonical = resolution.canonical_ref
    if not canonical or canonical not in ordered:
        return None
    return canonical, resolution.default_reason


def _level4(
    resolution: ConceptResolution,
    ordered: tuple[str, ...],
    *,
    tau: TauConfig,
    l4: ScoreOutcome,
) -> LayerDecision:
    """L4 打分兜底（PRD §12.9 约束④ 的 fail-safe 在此落地）。

    **失败侧一律偏 `ambiguous`**：解析失败 / 候选数不足 / 分数不全 / 分差落在 τ 邻域 ——
    四种情形**没有任何一种**可以判 `resolved_unique`。

    `reason` 尾部的 `|tau_unverified` 标记 = τ **未声明打分器身份**（`check_binds_scorer` 返回
    `False`，即 `model_id` / `prompt_version` 为空），本次分差**未经过校验**。它不是失败 ——
    判定照常 —— 但必须可观测，否则"校验通过"与"未校验"在日志里长得一模一样
    （N-27 约束②的存在意义就是消除这个歧义）。
    ⚠️ 该标记与 `is_calibrated`（是否经冻结集校准）**不是同一件事**，判据与消费方都不同 ——
    对照表见 `TauConfig.check_binds_scorer`。

    ⚠️ **区间边界是浮点的，且这不构成缺陷**：`Δ ≥ τ+ε` / `|Δ−τ| < ε` 的比较落在 IEEE-754 上，
    十进制"正好等于边界"的输入（如 `0.60 - 0.35`）实际是 `0.25000000000000006`，会落进任一邻侧。
    ε 的量级是 `5e-2`，远超浮点误差 `~1e-16`，**只有恰好压在边界上的输入受影响**，
    而那种输入在业务上无意义（分数本就是 LLM 产出的连续值）。故**不做** `math.isclose` 补偿：
    那会引入一个说不清宽度的第四区间。边界语义由单测用**二进制可精确表示**的 τ/ε 钉住。
    """
    options = tuple(_candidate(ref, BindingLayer.L4) for ref in ordered[:MAX_CLARIFY_OPTIONS])
    prompt = resolution.clarify_prompt

    if len(ordered) < 2:
        # 读法 4："候选数 = 1"不是唯一性判据（PRD §6.3.1 开篇）
        return LayerDecision(
            state=BindingState.AMBIGUOUS,
            layer=BindingLayer.L4,
            bindings=options,
            reason="single_candidate_without_declaration",
            clarify_prompt=prompt,
        )
    if not l4.ok:
        return LayerDecision(
            state=BindingState.AMBIGUOUS,
            layer=BindingLayer.L4,
            bindings=options,
            reason=f"l4_unavailable:{l4.reason or 'unknown'}",
            clarify_prompt=prompt,
        )

    by_id = {score.candidate_id: score for score in l4.scores}
    scorable = [ref for ref in ordered if ref in by_id]
    if len(scorable) != len(ordered):
        # 期望覆盖全部候选（parse_scores_json 已强制），这里只是纵深防御
        return LayerDecision(
            state=BindingState.AMBIGUOUS,
            layer=BindingLayer.L4,
            bindings=options,
            reason="l4_partial_coverage",
            clarify_prompt=prompt,
        )

    ranked = sorted(scorable, key=lambda ref: (-by_id[ref].value, ref))
    # 打分器绑定校验（N-27 约束②）：声明了却不匹配 → 抛（配置缺陷，不是本次查询的结论）。
    # 返回值**必须接住**：`False` = τ 未声明打分器身份，此时"未校验"必须落到 `reason` 上，
    # 否则观测里分不清"校验过通过"与"压根没校验"。
    scorer_verified = tau.check_binds_scorer(by_id[ranked[0]])
    unverified = "" if scorer_verified else "|tau_unverified"
    gap = by_id[ranked[0]].value - by_id[ranked[1]].value
    verdict = classify_gap(gap, tau)  # ← 三区间判据的**唯一**实现（校准脚本共用）

    if verdict.state is BindingState.RESOLVED_UNIQUE:
        return LayerDecision(
            state=BindingState.RESOLVED_UNIQUE,
            layer=BindingLayer.L4,
            bindings=(_candidate(ranked[0], BindingLayer.L4, by_id[ranked[0]].value),),
            reason=f"score_gap={gap:.4f}>=tau+eps{unverified}",
        )
    label = "tau_neighborhood" if verdict.band is GapBand.NEIGHBORHOOD else "score_gap_below_tau"
    return LayerDecision(
        state=BindingState.AMBIGUOUS,
        layer=BindingLayer.L4,
        bindings=options,
        reason=f"{label}:{gap:.4f}{unverified}",
        clarify_prompt=prompt,
    )


def tau_from_settings(settings: Any) -> TauConfig:  # pragma: no cover - 便捷别名
    """`TauConfig.from_settings` 的可读别名（供装配代码调用）。"""
    return TauConfig.from_settings(settings)
