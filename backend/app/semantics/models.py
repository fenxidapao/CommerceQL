"""语义包运行时模型（Pydantic v2）—— 07 §6.1 步骤②「15 类字段齐全性」的承载结构。

归属窗口：W2A（docs/08 §4.1：`app/semantics/**`）。
字段形状的唯一依据 = `semantic/SCHEMA_v1.md` **v1.1**（07 §4.7.1 裁定后的实现契约）；
本文件**只镜像形状，不发明字段**。发现 SCHEMA 与 YAML 冲突 → 以 YAML 为准并回报（SCHEMA §9.3）。

三条设计决定（每条都有事故背景）：

1. **`extra="forbid"`** —— 已删字段（`assets[].grain_level` / `field_bindings[].default_binding` /
   `meta.disclosure_text`，07 §4.7.1 裁定删除）只要在 YAML 里复活，pydantic 直接抛错。
   这把 W1A 校验器的 3 条"负向断言"变成了**结构约束**：不是靠记得，是靠形状。
2. **`frozen=True`** —— 语义包在进程内是**不可变**的版本化数据（07 §12.2：
   新版本只 INSERT，旧版本只读）。可变对象会让"版本切换"退化成"原地改数据"，
   单键指针的原子性设计（§6.2）就失去了意义。
3. **跨字段规则写成 `model_validator`** —— `ambiguous ⇔ 无 canonical_asset/default_reason`（双向）、
   `grain_level == grain_levels[hierarchy[-1]]`、draft 指标无 `default_binding`、
   维度 `binding`/`bindings` 二选一。这些是 SCHEMA §5.2/§3.3/§4/§3.2 的**硬约束**，
   放在模型层意味着**任何**构造路径（不只 loader）都绕不过。

⚠️ 与 W1A `semantic/validate_bundle.py` 的分工（07 §4.8 相关裁定精神的落位）：
那是**作者侧**校验器（刻意不 import `app.*`，独立可跑）；本文件是**运行时**模型。
二者不共享代码 —— 防分叉的手段是**测试用真实 YAML 对拍**（见 `tests/unit/test_semantics_loader.py`），
不是"抽一个公共库"（那会让作者侧被迫 import `app.*`，破坏它的独立可跑性）。
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Alias",
    "Asset",
    "BlacklistTerm",
    "ColumnDef",
    "DefaultPredicate",
    "Dimension",
    "EmbeddingDecl",
    "FieldBinding",
    "FieldBindingAlternative",
    "FieldBindingCandidate",
    "Join",
    "MaskRule",
    "Meta",
    "Metric",
    "MetricDefaultBinding",
    "Policy",
    "QualityGates",
    "SemanticBundle",
    "TimeSemanticsSection",
]


class _Frozen(BaseModel):
    """全包共用的模型配置：禁止多余键（已删字段复活即红）+ 实例不可变。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ============================================================================
# meta
# ============================================================================

class EmbeddingDecl(_Frozen):
    """`meta.embedding` —— U-25 裁定采纳（07 §6.1 步骤⑤ 的"YAML 声明"承载位）。"""

    model: str
    dim: int = Field(gt=0)


class Meta(_Frozen):
    """`meta` —— 附录 B §B.1.2。`domain` 是数据域的单一真相（SCHEMA §1）。"""

    version: str = Field(pattern=r"^\d{4}\.\d{2}\.\d{2}\.\d+$")  # 形态 YYYY.MM.DD.N（SCHEMA §9.1）
    domain: tuple[str, ...] = Field(min_length=1)
    dialect: str
    published_at: str
    published_by: str
    status: Literal["candidate", "active", "published", "deprecated"]
    timezone: str
    fiscal_year_start_month: int = Field(ge=1, le=12)
    week_starts_on: Literal["monday", "sunday"]
    embedding: EmbeddingDecl


# ============================================================================
# assets
# ============================================================================

class ColumnDef(_Frozen):
    """`assets[].columns[]`。`sensitive` 标记必须同时出现在 `policies.deny_columns`（loader 步骤③断言）。"""

    name: str
    type: str
    comment: str | None = None
    unit: str | None = None
    sensitive: str | None = None
    synonyms: tuple[str, ...] = ()
    enum: dict[str, str] = Field(default_factory=dict)  # 枚举值 → 中文展示名（不可变由 frozen 保证）
    time_semantics: str | None = None


class Asset(_Frozen):
    """认证资产 —— 唯一可被检索的集合（SCHEMA §2）。

    ⚠️ 已删字段 `grain_level`（资产细度档）**不得出现**（extra=forbid 拦截）。
    ⚠️ `tenant_scoped` 与"含 tenant_id 列"是**双向**断言（loader 步骤③）——
    写反 = 跨租户存在性泄露的直接路径（SCHEMA §2.1 / N-07）。
    """

    logical_name: str
    physical_asset: str
    grain: str
    domain: str
    owner: str
    certified: bool
    tenant_scoped: bool
    quality_score: float = Field(ge=0.0, le=1.0)
    freshness_sla: str
    level: Literal["hot", "warm", "cold"]
    row_estimate: int = Field(ge=0)
    description: str
    columns: tuple[ColumnDef, ...] = Field(min_length=1)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def has_column(self, name: str) -> bool:
        return any(c.name == name for c in self.columns)


# ============================================================================
# metrics
# ============================================================================

class MetricDefaultBinding(_Frozen):
    """`metrics[].default_binding` —— **形状必须恰好 `{asset, reason}`**（07 §4.7.1 收窄裁定）。

    `extra="forbid"` 保证 `time_field`（已删）或多任何一键都会直接红 ——
    "多出来的键不会有任何报错"正是 SCHEMA §4 点名的回归形态。
    """

    asset: str
    reason: str = Field(min_length=1, max_length=40)  # L3 披露文案 ≤ 40 字（U-26 渲染规则）


class Metric(_Frozen):
    """指标定义 —— 唯一权威口径（附录 B §B.2）。

    ⚠️ `draft` 指标**不得有** `default_binding`（draft 不参与 L3；
    给了默认口径 = 把未定口径伪装成已定，FR-12.3 要防的事）。
    """

    name: str
    display_name: str
    domain: str
    status: Literal["active", "draft", "deprecated"]
    definition_note: str | None = None
    expression: str | None = None
    default_aggregation: str | None = None
    unit: str | None = None
    owner: str | None = None
    default_binding: MetricDefaultBinding | None = None
    default_predicates: tuple[str, ...] = ()
    time_basis: str | None = None
    window: str | None = None
    synonyms: tuple[str, ...] = ()
    created_at: str | None = None
    version: int | None = None

    @model_validator(mode="after")
    def _draft_rules(self) -> Metric:
        if self.status == "draft":
            if self.default_binding is not None:
                raise ValueError(
                    f"指标 {self.name!r} 为 draft，不得携带 default_binding（draft 不参与 L3）"
                )
        else:
            missing = [
                key
                for key, val in (
                    ("expression", self.expression),
                    ("unit", self.unit),
                    ("time_basis", self.time_basis),
                )
                if val is None
            ]
            if missing:
                # FR-12.2「指标公式」是 15 类字段之一；缺了它该指标不可生成却仍可被检索。
                raise ValueError(f"非 draft 指标 {self.name!r} 缺少必填字段：{missing}")
        return self


# ============================================================================
# dimensions
# ============================================================================

class Dimension(_Frozen):
    """维度与层级（附录 B / 07 §6.8.1）。

    ⚠️ **刻度是族内的**（SCHEMA §3.3，"最反直觉的一处"）：
    - L2 判"是否同粒度"用 **`grain_level` 数值相等**，**不是** `hierarchy` 数组下标；
    - `grain_levels` 从 2 起（如 `city` 族）是**故意的**，运行时**不得"修正"**；
    - 禁止跨族比较（`year=1` 与 `country=1` 无任何关系）。
    """

    name: str
    hierarchy: tuple[str, ...] = Field(min_length=1)
    grain_levels: dict[str, int]
    grain_level: int
    binding: str | None = None            # 单绑定形态 `<asset>.<col>`
    bindings: dict[str, str] | None = None  # 多绑定形态（时间维度专有）{粒度: `<asset>.<col>`}
    value_map: dict[str, list[str]] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _grain_contract(self) -> Dimension:
        # ① 单绑定 / 多绑定二选一（SCHEMA §3.2）
        if (self.binding is None) == (self.bindings is None):
            raise ValueError(
                f"维度 {self.name!r} 必须且只能提供 binding（单绑定）或 bindings（多绑定）之一"
            )
        # ② grain_levels 必须与 hierarchy 逐项对应（可只覆盖子集，如 city 族从 region 起）
        for level_name in self.hierarchy:
            if level_name not in self.grain_levels:
                raise ValueError(
                    f"维度 {self.name!r}：hierarchy 层级 {level_name!r} 在 grain_levels 中无细度值"
                )
        # ③ 严格递增（SCHEMA §3.3：只断言递增，不断言"从 1 起 / 1..N 连续"）
        values = [self.grain_levels[name] for name in self.hierarchy]
        if any(b <= a for a, b in pairwise(values)):
            raise ValueError(
                f"维度 {self.name!r}：grain_levels 必须随 hierarchy 严格递增，当前 {values}"
            )
        # ④ 默认细度 ≡ hierarchy 末项（SCHEMA §3.3 的防漂移断言；读法残留 WARN 归 loader）
        expected = self.grain_levels[self.hierarchy[-1]]
        if self.grain_level != expected:
            raise ValueError(
                f"维度 {self.name!r}：grain_level={self.grain_level} != "
                f"grain_levels[hierarchy[-1]]={expected}（SCHEMA §3.3 防漂移断言）"
            )
        return self


# ============================================================================
# field_bindings
# ============================================================================

class FieldBindingAlternative(_Frozen):
    """`alternatives[]` —— 备选绑定（含启用条件与说明）。"""

    asset: str  # `<asset>.<col>` 形态
    use_when: str | None = None
    note: str | None = None


class FieldBindingCandidate(_Frozen):
    """`candidates[]` —— ambiguous 概念的候选（SCHEMA §5.3：候选必须**同 grain_level**）。"""

    asset: str
    label: str | None = None
    grain_level: int


class FieldBinding(_Frozen):
    """字段绑定 —— L3 的数据源（SCHEMA §5）。

    ⚠️ **双向互斥**（SCHEMA §5.2，"最易写错的一条"）：
    - `ambiguous: true` ⇒ `canonical_asset` 与 `default_reason` **都必须为空**，且 `candidates` 非空
      （留"占位非空"= 留一个假值 → 歧义被静默解决）；
    - 非 `ambiguous` ⇒ `canonical_asset` 与 `default_reason` **都不得缺**
      （缺了 → L3 在该直接执行的场景退回澄清 → 澄清率虚高）。
    """

    concept: str
    ambiguous: bool = False
    canonical_asset: str | None = None
    default_reason: str | None = None
    time_semantics: str | None = None
    grain_level: int | None = None
    alternatives: tuple[FieldBindingAlternative, ...] = ()
    candidates: tuple[FieldBindingCandidate, ...] = ()
    clarify_prompt: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _ambiguity_contract(self) -> FieldBinding:
        if self.ambiguous:
            if self.canonical_asset is not None or self.default_reason is not None:
                raise ValueError(
                    f"概念 {self.concept!r}：ambiguous=true 时不得有 canonical_asset/default_reason"
                    "（占位假值会把歧义静默解决，SCHEMA §5.2）"
                )
            if not self.candidates:
                raise ValueError(f"概念 {self.concept!r}：ambiguous=true 必须给出 candidates")
            # 候选必须同 grain_level：不同粒度该由 L2 按问句粒度直接选定，标 ambiguous 会虚高澄清率
            levels = {c.grain_level for c in self.candidates}
            if len(levels) > 1:
                raise ValueError(
                    f"概念 {self.concept!r}：ambiguous 候选必须同 grain_level，当前 {sorted(levels)}"
                    "（同粒度不同语义才需要澄清，SCHEMA §5.3）"
                )
        else:
            missing = [
                key for key, val in (("canonical_asset", self.canonical_asset),
                                     ("default_reason", self.default_reason))
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"概念 {self.concept!r}：非 ambiguous 条目缺少 {missing}"
                    "（L3 会退回澄清 → 澄清率虚高，SCHEMA §5.2）"
                )
        return self


# ============================================================================
# joins / default_predicates
# ============================================================================

class Join(_Frozen):
    """允许的 Join 路径 —— **未列出 = 禁止**（附录 B §B.1.3）。

    ⚠️ `on_columns` 只能是列对（左右各一，或同名只写一个）—— 这条不变量**不允许**
    靠新增 join 类型绕过（U-28 裁定：区间关联只能经 `v_dim_date` 两跳并显式登记）。
    ⚠️ 跨租户边界 / 跨类型的危险边必须带 `note`（loader 步骤③断言；
    这两类边是**会静默算错**的边，不是会报错的边）。
    """

    left: str   # `<asset>.<col>`
    right: str
    type: str
    on_columns: tuple[str, ...] = Field(min_length=1, max_length=2)
    certified_by: str
    note: str | None = None


class DefaultPredicate(_Frozen):
    """域级默认谓词（隐式业务规则）。`applies_to` 必须指向已定义指标。"""

    id: str
    predicate: str
    reason: str
    owner: str
    applies_to: tuple[str, ...] = Field(min_length=1)


# ============================================================================
# aliases / blacklist_terms / time_semantics / policies / quality_gates
# ============================================================================

class Alias(_Frozen):
    """别名表（L1 唯一入口；W1A 新增顶层区块，07 §12.2 `synonym` 物化表的源）。

    ⚠️ `term` 必须**一对一**（L1 硬条件；loader 步骤③断言全表无重复 term）。
    ⚠️ 不得指向 draft 指标（否则 L1 会把未确认口径"确定性解析"掉，FR-12.3）。
    """

    term: str
    lang: str
    maps_to_kind: Literal["asset", "metric", "column", "dimension", "value", "time"]
    maps_to_ref: str
    category: str


class BlacklistTerm(_Frozen):
    """黑话与不可映射词（附录 B §B.3.4 的承载位）。

    ⚠️ `refuse` 的语义是 **`refuse` 态 + 审计，不是 error**（SCHEMA §6.5）。
    """

    term: str
    action: Literal["refuse", "clarify"]
    reason: str
    alt_question: str | None = None
    clarify_prompt: str | None = None

    @model_validator(mode="after")
    def _copy_complete(self) -> BlacklistTerm:
        if self.action == "clarify" and not self.clarify_prompt:
            raise ValueError(f"黑话 {self.term!r}：action=clarify 必须给 clarify_prompt")
        return self


class TimeSemanticsSection(_Frozen):
    """时间语义（N-26：时间口径只能来自语义包，禁止代码硬编码）。

    ⚠️ 大促区间在本节 `notes`（**口径来源**）与 `v_campaign`（**取数来源**）两处，
    二者一致性由 W1A selfcheck 断言，运行时不重复校验（SCHEMA D-2）。
    """

    transaction_time: str
    current: str
    period_end_snapshot: str
    notes: tuple[str, ...] = ()


class MaskRule(_Frozen):
    """掩码规则。⚠️ `deny` 与 `mask` 是两套语义（07 §8.7）：deny = 列不出现；mask = 出现但打码。"""

    column_pattern: str
    rule: str


class Policy(_Frozen):
    """敏感列与脱敏策略（附录 B §B.3.3 / PRD FR-12.5）。

    YAML 中 `policies` 是列表且 deny / mask 分属两个条目 —— loader 负责聚合，
    本模型允许单条目只含其中一边。
    """

    deny_columns: tuple[str, ...] = ()
    applies_to_roles: tuple[str, ...] = ()
    mask_rules: tuple[MaskRule, ...] = ()
    note: str | None = None


class QualityGates(_Frozen):
    """质量与准入门槛（07 §6.1 步骤④）。

    ⚠️ 超阈值的行为是**排除**（`on_violation: exclude_from_context`），不是报错 ——
    "校验即准入门槛"针对的是**包结构**；质量不达标的资产只是**降级排除 + 告警**。
    """

    min_certified: bool
    min_quality_score: float = Field(ge=0.0, le=1.0)
    max_staleness_hours: int = Field(gt=0)
    require_owner: bool
    on_violation: Literal["exclude_from_context"]


# ============================================================================
# 根模型
# ============================================================================

class SemanticBundle(_Frozen):
    """语义包根模型。12 个顶层区块 = FR-12.2 的 15 类字段在 YAML 中的落位（loader 步骤②逐类核对）。

    ⚠️ `meta.disclosure_text` 已删（U-26）——披露文案的唯一载体是
    `metrics[].default_binding.reason` 与 `field_bindings[].default_reason`，
    渲染成 `insight.caveats[]` 由 API 层执行。本模型不提供任何渲染字段。
    """

    meta: Meta
    assets: tuple[Asset, ...] = Field(min_length=1)
    metrics: tuple[Metric, ...] = Field(min_length=1)
    dimensions: tuple[Dimension, ...] = Field(min_length=1)
    field_bindings: tuple[FieldBinding, ...] = Field(min_length=1)
    joins: tuple[Join, ...]
    default_predicates: dict[str, tuple[DefaultPredicate, ...]]
    aliases: tuple[Alias, ...] = Field(min_length=1)
    blacklist_terms: tuple[BlacklistTerm, ...]
    time_semantics: TimeSemanticsSection
    policies: tuple[Policy, ...] = Field(min_length=1)
    quality_gates: QualityGates
