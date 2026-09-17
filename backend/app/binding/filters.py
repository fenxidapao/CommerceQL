"""五步过滤（FR-3.3 / 07 §6.8 上半）—— 概念解析与候选裁剪。

归属窗口：W3C｜依据：07 §6.8 表 + §6.8.1、PRD §6.3.1。

| 步 | 07 原文 | 本模块的落地 | 淘汰归因 |
|---|---|---|---|
| ① | 术语表/语义模型解析业务概念（`synonym` + `metric_def` + `field_binding.concept`） | `resolve_concept()`：三个来源按序尝试，产出**绑定目标标识**集合 | `unresolved` |
| ② | 过滤未认证 / 无权限 / 质量异常 / 已废弃 | `_step_permitted()`：RBAC 面（allowlist + deny 列）。<br>⚠️ **质量面已在 loader 完成**（`quality_gates.on_violation=exclude_from_context`）→ 被排除的资产在 `runtime.asset()` 里**等同不存在**，故此步只需查 RBAC | `denied` |
| ③ | 校验查询粒度（请求粒度声明 vs `asset.grain`） | `_step_grain_servable()`：**问句粒度** vs **候选层级**，**同族内**才比较。候选比请求更粗（`value < 请求`）→ 该字段**服务不了**这个粒度 → 淘汰 | `grain_mismatch` |
| ④ | 校验时间语义（当前主数据 / 交易时快照 / 统计期末值） | `_step_time_semantics()`：请求声明 vs `field_binding.time_semantics`；**请求未声明时不判**（不猜） | `time_semantics_mismatch` |
| ⑤ | 排序：权威来源 > 血缘完整 > 时效 > 成本 | `_order_key()`：确定性排序键 | 取 Top-1（**排序不等于判定**，见下） |

## 两处必须写明的读法（否则实现会走偏，已登记待架构确认）

**读法 1：⑤ 的"取 Top-1"与四层判定并存，不是二选一。**
   若 ⑤ 直接"取 Top-1 即定稿"，L2/L4 就永远不可能被触达，而 07 §6.8.2 硬约束 5 又要求
   `binding_layer` 分布可观测（L1–L4 四层都要有触发场景）—— 那会自相矛盾。
   ⇒ 本模块把 ⑤ 实现为**产出确定性的有序候选列表**（给 L4 送候选、给澄清选项定序、让结果可复现），
   **是否唯一由四层判定负责**（`four_layer.py`）。"排序靠前"不等于"已确定"。

**读法 2：③ 与 L2 的分工。**
   ③ 淘汰的是**服务不了**请求粒度的候选（更粗）；L2 是**在能服务的候选里按问句粒度选一个**
   （更细或相等的多个候选之间有竞争）。二者不重复：③ 是"能不能"，L2 是"选哪个"。

## 已知缺口（如实登记，不猜不补）

| 缺口 | 后果 | 去向 |
|---|---|---|
| ⑤ 的"**血缘完整**"与"**成本**"在语义包里**没有对应字段** | 排序键实际只用 `certified / quality_score / freshness_sla / ref` 四项 | RELAY §给 W1A（补字段） |
| `quality_gates.max_staleness_hours` 需要**实际新鲜度**（不在语义包内） | loader 未实施该条，本步也不实施；语义包只有 `freshness_sla`（SLA 声明，不是实测新鲜度） | RELAY §给 W1A/W0 |
| 表级概念（`aliases` 的 `maps_to_kind=asset`，如 `商品`→`product`）**解析不出列级绑定** | 归 `unresolved`（表级不是字段绑定；意图分类应拦在前面） | RELAY §给架构 |
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from app.binding.context import BindingRequestScope
from app.binding.grain import GrainIndex, GrainRef, SemanticReader

__all__ = [
    "BindingAttribution",
    "ConceptResolution",
    "FilterOutcome",
    "filter_candidates",
    "resolve_concept",
]


class BindingAttribution(StrEnum):
    """淘汰归因（07 §6.8 的"淘汰归因"列，**逐字对齐**）。

    ⚠️ 它不是 `DegradedReason` / `ClarifyReason` 的一部分，也不进 SSE ——
    它的消费者是**评测报告与运行指标**：「澄清率高的时候到底是哪一层/哪一步失效」。
    07 §6.8.3 的诊断表就是按这四个值横向定位的。
    """

    UNRESOLVED = "unresolved"
    DENIED = "denied"
    GRAIN_MISMATCH = "grain_mismatch"
    TIME_SEMANTICS_MISMATCH = "time_semantics_mismatch"


#: 多因并存时的**主归因优先级**（越靠前越"根因"）：越权最重，其次语义不符，最后是粒度。
_ATTRIBUTION_PRECEDENCE: tuple[BindingAttribution, ...] = (
    BindingAttribution.DENIED,
    BindingAttribution.TIME_SEMANTICS_MISMATCH,
    BindingAttribution.GRAIN_MISMATCH,
)


@dataclass(frozen=True, slots=True)
class ConceptResolution:
    """第 ① 步的结果：概念解析出的**绑定目标标识**及其来源。

    ⚠️ **`refs` 的元素形态由 `source` 决定**（这是端口装不下的约定，已登记 RELAY §给 W4）：
    | source | ref 形态 | 例 |
    |---|---|---|
    | `alias` / `field_binding`（列级） | `<asset>.<col>` | `order_paid.receiver_city` |
    | `alias`（维度）/ `dimension` | 该维度的 `binding` / 默认粒度绑定 | `order_paid.region_code` |
    | `metric` | **指标名**（物理资产与默认谓词由 `metric.default_binding` / `default_predicates` 给出） | `gmv` |
    """

    concept: str
    source: Literal["field_binding", "alias", "metric", "dimension"]
    refs: tuple[str, ...]
    #: 语义包**声明**的规范字段（`field_binding.canonical_asset` / `metric.default_binding.asset`）。
    #:
    #: ⚠️ 必须与 `refs` **分开**：`refs` 是"这个概念的候选全集"（canonical + candidates + alternatives），
    #: L3 只认**声明的那个**。若拿 `refs` 做 L3 判据，canonical 被 RBAC 过滤掉时会**静默改绑
    #: `alternatives`**（其 `use_when` 条件根本没被求值），却照旧披露 canonical 的口径文案 ——
    #: 用户看到的是"已按 X 口径"，实际用的是 Y。宁可澄清（N-25 的补救方向是回看语义包）。
    canonical_ref: str | None = None
    declared_ambiguous: bool = False
    #: `field_binding.grain_level` —— 语义包声明的**族内刻度值**。
    #:
    #: ⚠️ 目前**没有任何层消费它**，这是刻意的：`field_binding` 不声明它属于哪个**粒度族**，
    #: 而刻度值只在族内可比（07 §6.8.1 禁跨族比较）。拿单个数字去比 = 拿 `time.day=5`
    #: 与 `city=4` 大小论粗细。故只如实携带，供观测 / 后续 W1A 补族名后再启用。
    declared_grain_level: int | None = None
    default_reason: str | None = None
    clarify_prompt: str | None = None
    metric_name: str | None = None


@dataclass(frozen=True, slots=True)
class FilterOutcome:
    """五步过滤的结果。`ordered` 非空 = 有候选可用；`attribution` = 全灭时的主归因。"""

    ordered: tuple[str, ...] = ()
    dropped: tuple[tuple[str, BindingAttribution], ...] = ()
    attribution: BindingAttribution | None = None
    notes: tuple[str, ...] = field(default=())
    #: 本步算出的**请求粒度**（判不出为 `None`）。**带出来而不是让调用方重算**：
    #: `four_layer.decide` 的 L2 需要同一个值，而重算会把 n-gram 扫描跑两遍 ——
    #: 更糟的是"两份代码算同一件事"，将来一处改了另一处没改，两边就会用不同的粒度判定。
    #: `None` 的语义是确定的：步③ 不判（不猜）、L2 不参与（07 §6.8.1）。
    question_grain: GrainRef | None = None


# ============================================================================
# 第 ① 步：概念解析
# ============================================================================


def resolve_concept(concept: str, reader: SemanticReader) -> ConceptResolution | None:
    """概念 → 绑定目标（07 §6.8 步① 的三个依据：`synonym` / `metric_def` / `field_binding.concept`）。

    顺序**刻意固定**（写进单测）：`field_binding` → `alias` → `metric` → `dimension`。
    理由：`field_binding` 是**唯一**携带 `canonical_asset` / `default_reason` / `ambiguous`
    三个 L3/L4 判据的来源，优先命中它能让"默认口径必须披露"这条纪律在最外层就拿到文案。
    """
    if not concept or not concept.strip():
        return None
    term = concept.strip()

    raw = reader.field_binding(term)
    if raw is not None:
        refs = _refs_of_field_binding(raw)
        return ConceptResolution(
            concept=term,
            source="field_binding",
            refs=refs,
            canonical_ref=_as_optional_str(getattr(raw, "canonical_asset", None)),
            declared_ambiguous=bool(getattr(raw, "ambiguous", False)),
            declared_grain_level=_as_int(getattr(raw, "grain_level", None)),
            default_reason=_as_optional_str(getattr(raw, "default_reason", None)),
            clarify_prompt=_as_optional_str(getattr(raw, "clarify_prompt", None)),
        )

    alias = reader.resolve_alias(term)
    if alias is not None:
        kind = str(getattr(alias, "maps_to_kind", ""))
        ref = str(getattr(alias, "maps_to_ref", ""))
        if kind == "column":
            return ConceptResolution(concept=term, source="alias", refs=(ref,) if ref else ())
        if kind == "dimension":
            dimension = reader.dimension(ref)
            if dimension is None:
                return None
            refs = _refs_of_dimension(dimension)
            return ConceptResolution(concept=term, source="dimension", refs=refs)
        if kind == "metric":
            return _metric_resolution(term, ref, reader)
        if kind == "value":
            # `traffic_daily.channel=live` → 绑定目标是**列**（值本身由 value_map/谓词承载）
            column = ref.split("=", 1)[0].strip()
            return ConceptResolution(concept=term, source="alias", refs=(column,) if column else ())
        # asset / time：都不是字段绑定（表级 / 时间表达式）→ 归 unresolved
        return None

    metric = reader.metric(term)
    if metric is not None:
        return _metric_resolution(term, term, reader)

    dimension = reader.dimension(term)
    if dimension is not None:
        return ConceptResolution(
            concept=term, source="dimension", refs=_refs_of_dimension(dimension)
        )
    return None


def _metric_resolution(term: str, metric_ref: str, reader: SemanticReader) -> ConceptResolution | None:
    """指标类概念的解析。**draft 指标不参与**（FR-12.3 / `is_metric_active`）。"""
    if not reader.is_metric_active(metric_ref):
        return None
    metric = reader.metric(metric_ref)
    if metric is None:
        return None
    default = getattr(metric, "default_binding", None)
    if default is None:
        # 无默认口径 → 该指标**没有可用绑定**（口径不唯一），交给上层走澄清
        return ConceptResolution(
            concept=term, source="metric", refs=(), declared_ambiguous=True, metric_name=metric_ref
        )
    asset = str(getattr(default, "asset", "") or "")
    return ConceptResolution(
        concept=term,
        source="metric",
        refs=(asset,) if asset else (),
        canonical_ref=asset or None,
        default_reason=_as_optional_str(getattr(default, "reason", None)),
        metric_name=metric_ref,
    )


def _refs_of_field_binding(raw: Any) -> tuple[str, ...]:
    """`canonical_asset` + `candidates[].asset` + `alternatives[].asset`（保序去重）。

    ⚠️ 三者都要收：`ambiguous: true` 的条目**只有 `candidates`**（`canonical_asset` 必须为空），
    而非歧义条目可能带 `alternatives`（换了 `use_when` 条件就是另一个合法绑定）。
    漏收 `candidates` 会让"必须澄清"的形态退化成"空候选 → unresolved"，方向刚好相反。
    """
    refs: list[str] = []
    canonical = str(getattr(raw, "canonical_asset", "") or "")
    if canonical:
        refs.append(canonical)
    refs += [str(getattr(c, "asset", "")) for c in getattr(raw, "candidates", ())]
    refs += [str(getattr(a, "asset", "")) for a in getattr(raw, "alternatives", ())]
    return tuple(dict.fromkeys(ref for ref in refs if ref))


def _refs_of_dimension(dimension: Any) -> tuple[str, ...]:
    """维度的绑定目标：多绑定形态（`bindings`）取**默认粒度**那一项，单绑定取 `binding`。

    ⚠️ 多绑定实测只有时间维度（`{day/week/month/quarter/year: pay_time}`）。取"默认粒度条目"
    的依据是 `grain_level`（= `grain_levels[hierarchy[-1]]`，SCHEMA §3.3 的防漂移断言保证它存在）；
    万一取不到 → 退化为**字典序最小**的键（确定性，不猜语义）。
    """
    bindings = getattr(dimension, "bindings", None)
    if isinstance(bindings, Mapping) and bindings:
        default_value = _as_int(getattr(dimension, "grain_level", None))
        levels = getattr(dimension, "grain_levels", None)
        level_values: Mapping[str, Any] = levels if isinstance(levels, Mapping) else {}
        for level in sorted(bindings):
            if default_value is not None and _as_int(level_values.get(level)) == default_value:
                return (str(bindings[level]),)
        return (str(bindings[sorted(bindings)[0]]),)
    single = str(getattr(dimension, "binding", "") or "")
    return (single,) if single else ()


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


# ============================================================================
# 第 ②–⑤ 步：候选裁剪与排序
# ============================================================================


def filter_candidates(
    resolution: ConceptResolution,
    ctx: Any,
    reader: SemanticReader,
    grain_index: GrainIndex,
    scope: BindingRequestScope,
) -> FilterOutcome:
    """对 `resolution.refs` 施加 ②③④ 过滤并按 ⑤ 排序。

    ⚠️ `attribution` 只在**全灭**（`ordered` 为空）时才有值 —— 部分淘汰不改变结论，
    但 `dropped` 始终如实记录，便于诊断（"为什么只剩一个候选"是可解释性的一部分）。
    """
    if not resolution.refs:
        return FilterOutcome(attribution=BindingAttribution.UNRESOLVED)

    dropped: list[tuple[str, BindingAttribution]] = []
    survived: list[str] = []

    # 请求粒度（L2 与步③ 共用；判不出则为 None → 步③ 不判、L2 不参与）
    question_grain: GrainRef | None = None
    if scope.is_set:
        question_grain = grain_index.question_level(
            scope.normalized_question, extra_words=scope.grain_words
        )

    for ref in resolution.refs:
        if not _step_permitted(ref, ctx, reader):
            dropped.append((ref, BindingAttribution.DENIED))
            continue
        if not _step_grain_servable(ref, question_grain, grain_index):
            dropped.append((ref, BindingAttribution.GRAIN_MISMATCH))
            continue
        if not _step_time_semantics(resolution, scope, reader):
            dropped.append((ref, BindingAttribution.TIME_SEMANTICS_MISMATCH))
            continue
        survived.append(ref)

    ordered = tuple(sorted(survived, key=lambda ref: _order_key(ref, reader)))
    if ordered:
        return FilterOutcome(ordered=ordered, dropped=tuple(dropped), question_grain=question_grain)
    attribution = next(
        (kind for kind in _ATTRIBUTION_PRECEDENCE if any(d[1] is kind for d in dropped)),
        BindingAttribution.UNRESOLVED,
    )
    return FilterOutcome(
        dropped=tuple(dropped), attribution=attribution, question_grain=question_grain
    )


def _step_permitted(ref: str, ctx: Any, reader: SemanticReader) -> bool:
    """第 ② 步：RBAC 面（ADR-10 应用侧白名单）。

    ⚠️ **质量面**（`certified` / `quality_score` / `owner`）**不在此重复实施**：
    loader 已按 `quality_gates.on_violation=exclude_from_context` 把它们排除出 `active_assets`，
    于是 `runtime.asset()` 对不合格资产**返回 None** —— 在此再审一遍 = 同一事实两处实现。

    ⚠️ **权限面只认 `asset_allowlist(ctx)`**，刻意**不用** `is_denied_column(ref)`。理由与代价如下：

    | 判据 | 是否角色感知 | 归谁 |
    |---|---|---|
    | `asset_allowlist(ctx)` | ✅ 逐字执行语义包 `policies[].applies_to_roles` | 本步（07 §6.8 步②"无权限"） |
    | `is_denied_column(ref)` | ❌ 静态集合（docstring 自述为 **AST-R07 判据，W2C 用**） | gate1（SQL 层） |

    🔴 **实测发现的真实分歧（已登记，见 RELAY §给架构）**：`platform_admin` **不在**
    `applies_to_roles` 内 → 白名单**放行** `order_paid.receiver_phone`；
    而 `is_denied_column` 对它恒为 `True`（角色无关）→ **gate1 R07 会拒绝**。
    即同一 ref 上，"能不能绑"与"能不能查"两个判据结论相反。本窗口**只报告不裁决**，
    取白名单的理由是它才是角色感知的那一个（07 §6.8 步②列的是"无权限"，不是"黑名单列"）。
    """
    parts = ref.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        # 指标名 / 表级标识没有列维度 → 权限面在 gate 层（W2C）判，本层不拦
        return True
    logical, column = parts
    asset = reader.asset(logical)
    if asset is None:
        return False
    allowlist = reader.asset_allowlist(ctx)
    entry = allowlist.get(str(getattr(asset, "physical_asset", "")))
    if not isinstance(entry, Mapping):
        return False
    columns = entry.get("columns")
    # 白名单项缺 `columns` 时**不拦**（形状异常属 loader 契约，不在本层发明拒绝规则）
    return not (isinstance(columns, (list, tuple)) and column not in columns)


def _step_grain_servable(ref: str, question_grain: GrainRef | None, grain_index: GrainIndex) -> bool:
    """第 ③ 步：候选能否服务请求粒度（**同族内**才比较，跨族直接放行 —— 07 §6.8.1 禁跨族）。"""
    if question_grain is None:
        return True
    candidate_grain = grain_index.level_of_ref(ref)
    if candidate_grain is None or candidate_grain.family != question_grain.family:
        return True
    # 候选比请求**更粗**（值更小）→ 它无法承载请求的细度 → 服务不了
    return candidate_grain.value >= question_grain.value


def _step_time_semantics(
    resolution: ConceptResolution, scope: BindingRequestScope, reader: SemanticReader
) -> bool:
    """第 ④ 步：时间语义校验（`field_binding.time_semantics` vs 请求声明）。

    ⚠️ **判据是概念级的**，因为语义包里 `time_semantics` 声明在 `field_bindings[]` 上
    （实测：`支付时间` 声明 `transaction_time`，`customer_name` 声明 `current`），
    并没有"按 `<asset>.<col>` 反查 time_semantics"的读口。按 ref 判会需要一张新映射表 = 第二真相。

    ⚠️ 两个"不判"是刻意的（与 07 §6.8.1"抽取失败不进入"同族纪律）：
    ① 请求**未声明**时间语义（`scope.time_semantics is None`）；
    ② 该概念在语义包里**没有**声明 `time_semantics`（如纯指标概念）。
    这两种情形**放行**而不是淘汰 —— 淘汰会让"没说"变成"不匹配"，把可用候选杀光。
    """
    if scope.time_semantics is None:
        return True
    raw = reader.field_binding(resolution.concept)
    declared = _as_optional_str(getattr(raw, "time_semantics", None)) if raw is not None else None
    if declared is None:
        return True
    return declared == scope.time_semantics


def _order_key(ref: str, reader: SemanticReader) -> tuple[int, float, float, str]:
    """第 ⑤ 步的排序键：**权威来源 > 时效 > 成本**，全部确定性、无随机。

    | 键 | 判据 | 来源 |
    |---|---|---|
    | ① 权威来源 | `asset.certified`（True 在前） | 语义包 `asset.certified` |
    | ② 质量分 | `-quality_score`（高在前） | 语义包 `asset.quality_score` |
    | ③ 时效 | `freshness_sla` 解析成秒（短在前；不可解析排最后） | 语义包 `asset.freshness_sla` |
    | ④ 稳定序 | ref 字典序（保证同分候选顺序可复现） | — |

    ⚠️ 07 原表里的"**血缘完整**"与"**成本**"在语义包中**没有字段** → 本键不含它们（已登记缺口，
    见模块 docstring）。**不发明默认值**：给一个猜测的权重等于把"缺字段"伪装成"已实现"。
    """
    parts = ref.split(".", 1)
    if len(parts) != 2:
        return (1, 0.0, float("inf"), ref)
    asset = reader.asset(parts[0])
    if asset is None:
        return (1, 0.0, float("inf"), ref)
    certified = 0 if bool(getattr(asset, "certified", False)) else 1
    quality = float(getattr(asset, "quality_score", 0.0) or 0.0)
    freshness = _duration_seconds(getattr(asset, "freshness_sla", None))
    return (certified, -quality, freshness, ref)


def _duration_seconds(value: Any) -> float:
    """ISO 8601 duration（`PT6H` / `PT12H` / `PT24H` / `P7D` / `P30D`）→ 秒。

    语义包实测只用到 `P{n}D` 与 `PT{n}H` 两种形态；其余形态 → `inf`（排最后），
    **不当作 0**（当作 0 会让"解析不出来"看起来最"新鲜"，与事实相反）。
    """
    if not isinstance(value, str) or not value.startswith("P"):
        return float("inf")
    body = value[1:]
    total = 0.0
    number = ""
    matched = False
    for char in body:
        if char.isdigit():
            number += char
            continue
        if char == "T" or not number:
            continue
        amount = float(number)
        number = ""
        if char == "D":
            total += amount * 86400.0
        elif char == "H":
            total += amount * 3600.0
        elif char == "M":
            total += amount * 60.0
        elif char == "S":
            total += amount
        else:
            return float("inf")
        matched = True
    if number:  # 结尾还有数字 = 单位缺失 → 形态不认识
        return float("inf")
    return total if matched else float("inf")
