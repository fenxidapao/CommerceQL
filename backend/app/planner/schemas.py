"""W3B 的 JSON 输出契约 —— **LLM 输出 schema 的唯一真相**（Pydantic v2）。

归属窗口：W3B（docs/08 §4.1）｜层号：L3

## 一、这个文件同时解决两件事（这是它存在的理由）

W3A 交付的 7 个 prompt 资产（`normalize_v1.txt` / `intent_v1.txt` / `normalize_intent_v1.txt` /
`plan_v1.txt` / `gen_sql_v1.txt` / `gen_sql_complex_v1.txt` / `repair_v1.txt`）里，
每个 SYSTEM 段都有一个 `$output_schema` 占位符，**但资产内不含 schema 本体**（实测 2026-09-17）。
资产只规定"只输出一个 JSON 对象"，不规定对象里有哪些键 —— 而那正是本环节的职责。

⇒ 本文件是**唯一的** schema 来源，并派生 `output_schema_for(task)` 的文本喂给出站载荷。
**不手写第二份 schema 文本**：手写的副本与模型定义必然漂移，而漂移的后果是
"prompt 里说的键"与"校验器认的键"不一致 → 修复重试次次失败 → 全链路降级。

## 二、`Plan` 与 `PlanSummary` 的归属（U-24 的回填）

`app/graph/state.py:49` 登记：

    | `few_shot` / `plan` / `plan_summary` / `bindings` | `GoldQuery` / `Plan` / `PlanSummary` / `Binding` | W2B / W3B | **U-24** |

即 **`Plan` / `PlanSummary` 的真类型由 W3B 定义**（该文件当前用 `OpaquePayload` 占位，
由 W4 接线时替换注解 —— 图不解释载荷，G-1）。

`PlanSummary` 的键集**逐字对齐补充契约 C-01**：
`{metrics[], dimensions[], filters[], grain, time_range{start,end}, order_by[], limit}`，
且"**只放摘要，不含 SQL**"（呼应 FR-10.1）。它**由 `Plan` 派生**（`Plan.to_summary()`），
两者不各写一遍 —— C-01 是"事件里发出去的那个形状"，`Plan` 是"模型输出的那个形状"。

## 三、三处**刻意不发明**的东西（缺什么就登记什么）

| # | 缺口 | 本文件的处理 |
|---|---|---|
| 1 | `intent` 四值枚举在 `core/enums.py` **不存在**（state.py:57 登记 U-25） | 在此**首次定义** `IntentKind` 并登记迁往 `core/enums.py` 的请求；**不**在 planner 内复制已有常量 |
| 2 | prompt 让模型输出 `query/clarify_needed/out_of_scope/unsafe`，与 07 §5.2 的 `executable/clarify/refuse/open_analysis` **不同名** | `INTENT_MAP` 单表映射（Q3 已裁）；`open_analysis` **模型不产出** → 见 §四 |
| 3 | `gen_sql_complex_v1.txt` 规则 7 让模型写 `plan_summary`（**一段话**），与 C-01 的结构化 `plan_summary` **同名不同义** | 本文件用 `rationale` 承载那段话，避免同名两义；资产措辞修订已提需求（RELAY §给 W3A） |

## 四、`open_analysis` 当前是**不可达**的（如实登记，不假装覆盖）

07 FR-1.6 的四分类含 `open_analysis`（NG4：开放分析 → 拒答并给替代问法），
但 prompt 资产的意图取值集是 `query/clarify_needed/out_of_scope/unsafe` —— **没有它**。
⇒ 在本窗口的实现里 `IntentKind.OPEN_ANALYSIS` **不会被产出**（模型没有这个选项，
本窗口也不发明启发式规则去猜）。后果与去向写在 `RELAY.md §给架构`（待分配编号）。
**这不是"实现了但没测到"，是"上游取值集缺一项"** —— 两者的区别必须能被看见。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ActionTaken, DegradedReason, RefuseReason

__all__ = [
    "DEGRADED_NOTE_DETAIL_WIRE_KEY",
    "GenSqlResult",
    "INTENT_MAP",
    "IntentKind",
    "IntentResult",
    "LlmIntent",
    "NormalizeIntentResult",
    "NormalizeResult",
    "Plan",
    "PlanAssetUse",
    "PlanMetric",
    "PlanSummary",
    "RepairResult",
    "ResolvedTerm",
    "SqlCandidate",
    "TimeRange",
    "TimeWindow",
    "DegradedNote",
    "output_schema_for",
    "schema_key_names",
    "task_output_models",
]


# ============================================================================
# 一、模型配置：严格 + 冻结
# ============================================================================

#: 所有 LLM 输出模型共用。
#:
#: - `extra="forbid"` —— 07 §10.3 "严格按 Pydantic schema 校验"。**多一个键即整份拒收**，
#:   不静默丢弃：未知键说明模型误解了 schema，而"猜它想要什么"会让口径漂移无声发生。
#: - `frozen=True` —— 输出是不可变事实，鉴权/降级路径上谁都不该改它。
_STRICT: Final[ConfigDict] = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
)


# ============================================================================
# 二、意图：LLM 取值 → 状态机取值（Q3 裁定的**单表映射**）
# ============================================================================

class LlmIntent(StrEnum):
    """**模型侧**的意图取值 —— 逐字对齐 `app/llm/prompts/intent_v1.txt` 的资产措辞。

    ⚠️ 这组值来自 prompt 资产（W3A 的文件），本类只是给它们**取了名字**，
    没有新增/改名任何一个字面量。
    """

    QUERY = "query"
    CLARIFY_NEEDED = "clarify_needed"
    OUT_OF_SCOPE = "out_of_scope"
    UNSAFE = "unsafe"


class IntentKind(StrEnum):
    """**状态机侧**的意图取值（07 §5.2 组 3）—— `GraphState.intent` 的取值集。

    🔴 **定义位置说明（U-25）**：`app/core/enums.py` 目前**没有**这个枚举
    （state.py:57 用 `str` 占位并登记 U-25）。本类是它**第一次被定义**的地方 ——
    这不是"复制一份常量"，是"先有了第一个定义"。**已向 W0 提需求迁往 `core/enums.py`**，
    迁移时本类应被删除并改为 re-export（避免真的变成两份）。
    """

    EXECUTABLE = "executable"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    OPEN_ANALYSIS = "open_analysis"


#: 模型侧 → (状态机侧, `refuse_kind`)。`refuse_kind` 只在 `REFUSE` 时有值。
#:
#: 逐条理由（Q3，用户 2026-09-17 已裁）：
#: - `query → executable`      —— 字面同义（"期望得到数据结果"）。
#: - `clarify_needed → clarify` —— 字面同义（"必须由用户回答才能继续"）。
#: - `out_of_scope → refuse(out_of_scope)` —— `RefuseReason.OUT_OF_SCOPE` 与资产措辞同字面。
#: - `unsafe → refuse(pii_blocked)` —— ⚠️ **语义拉伸**：资产说的是"试图越权/索取禁列/
#:   指示改变自身行为"，而 `RefuseReason` 只有 `pii_blocked` 与之最接近。
#:   这是一条**已知的近似**，不是巧合的吻合 —— 见 `RELAY.md §给架构`。
#: - `open_analysis` —— **无对应项**：模型侧没有这个取值（见模块 docstring §四）。
INTENT_MAP: Final[Mapping[LlmIntent, tuple[IntentKind, RefuseReason | None]]] = MappingProxyType(
    {
        LlmIntent.QUERY: (IntentKind.EXECUTABLE, None),
        LlmIntent.CLARIFY_NEEDED: (IntentKind.CLARIFY, None),
        LlmIntent.OUT_OF_SCOPE: (IntentKind.REFUSE, RefuseReason.OUT_OF_SCOPE),
        LlmIntent.UNSAFE: (IntentKind.REFUSE, RefuseReason.PII_BLOCKED),
    }
)


# ============================================================================
# 三、公共子结构
# ============================================================================

class TimeWindow(BaseModel):
    """**C-01 的形状**：`{start, end}`。`None` = 该侧无边界（如"至今"）。"""

    model_config = _STRICT

    start: str | None = None
    end: str | None = None


class TimeRange(TimeWindow):
    """`GraphState.time_range` 的形状：`{start, end, expr, tz}`（07 §5.2 组 2）。

    继承 `TimeWindow` 保证"C-01 的形状是本形状的子集" —— 两者不各写一遍。
    `expr` 保留用户原表达（**用于追溯**，不参与计算）；`tz` 来自语义包（N-26）。
    """

    expr: str | None = None
    tz: str | None = None


class ResolvedTerm(BaseModel):
    """`GraphState.resolved_terms[]` 的元素：`{surface, canonical, kind}`。

    形状由 **W2A** 定义（state.py 注明 U-24 回填物），本类只把它类型化 ——
    数据源是语义包的 `resolve_terms`，**不由 LLM 产出**（别名命中必须是确定性的，07 §6.8 L1）。
    """

    model_config = _STRICT

    surface: str
    canonical: str
    kind: str


@dataclass(frozen=True, slots=True)
class DegradedNote:
    """**一条要上报的降级**（reason + 已采取的动作 + 结构化 detail）。

    为什么是本模块的结构体而不是 `app.llm.DegradationEvent`：那个事件由网关在**出站那一跳**
    发出（它有自己的 `DegradationSink`）。而 `plan_generation_failed` 这类降级发生在
    **出站成功之后**，网关根本不知道 —— 只能由本模块上报。

    ⇒ 全项目有**两条降级通道**：网关的 sink（出站跳）+ 本模块的返回值（业务跳）。
    两者都必须由 W4 转到 SSE；只接一条，前端就会漏掉一类降级（见 `RELAY.md §给 W4`）。
    """

    reason: DegradedReason
    action_taken: ActionTaken
    detail: Mapping[str, Any]


#: 降级 detail 里承载"本模块自述细节"的键名。
#:
#: ⚠️ 叫这个名字是因为 detail 会被 W4 原样摊进 SSE `degraded.data`
#: （见 `reports/w3a/RELAY.md §给 W4` 的 sink 示例），故它必须是**扁平的、可序列化的**。
DEGRADED_NOTE_DETAIL_WIRE_KEY: Final[str] = "planner_detail"


# ============================================================================
# 四、节点 2 `normalize` 的输出
# ============================================================================

class NormalizeResult(BaseModel):
    """`normalize` 任务（节点 2）的**模型输出**。

    职责边界（07 §5.3 节点 2：时间绝对化 / 黑话别名 / 零代词补全 / 数值单位）里，
    **只有"改写与消歧"这一部分交给模型**：

    | 子职责 | 归属 | 理由 |
    |---|---|---|
    | 改写 / 消歧 / 零代词补全 | 模型 | 语言能力 |
    | **时间绝对化** | **本模块的确定性解析器**（`timeexpr.py`） | prompt 资产**明令**模型不得换算（规则 3），且 N-26 要求基准只能来自语义包 |
    | 黑话 / 别名的 `resolved_terms` | 语义包 `resolve_terms`（W2A） | L1 命中必须是确定性的（07 §6.8） |

    ⇒ `time_expression` 是模型**原样抄回**的时间表达，交给确定性解析器，而不是让模型算日期。
    """

    model_config = _STRICT

    #: 归一化后的问题（黑话已展开、零代词已补全）。prompt 规则 6：本身已规范就原样返回。
    normalized_question: str = Field(min_length=1)

    #: 问题里出现的时间表达（**原样**，如"上月"），无则 None。
    time_expression: str | None = None

    #: 语义摘要里找不到映射的词（FR-11.5 待补清单）。
    unmapped_terms: list[str] = Field(default_factory=list)


class IntentResult(BaseModel):
    """`intent` 任务（节点 3）的模型输出。"""

    model_config = _STRICT

    intent: LlmIntent
    #: 自由文本的理由码（进 `intent_detail.reason_code`；不设枚举，因为上游未定义取值集）。
    reason_code: str | None = None
    #: 资产的硬性规则 3："拿不准就低于 0.6"。
    confidence: float = Field(ge=0.0, le=1.0)
    #: `clarify_needed` 时缺什么（供 `clarify.question` 用；非澄清态应为空）。
    clarify_hint: str | None = None


class NormalizeIntentResult(BaseModel):
    """**合并档**（`normalize_intent`）的模型输出 —— 07 §16.1 压缩手段 1。

    字段 = `NormalizeResult` ∪ `IntentResult` 的最小并集。
    ⚠️ 合并**不改变任何判定标准**（资产原文），只是省掉一次往返与一段重复上下文。
    """

    model_config = _STRICT

    normalized_question: str = Field(min_length=1)
    time_expression: str | None = None
    unmapped_terms: list[str] = Field(default_factory=list)
    intent: LlmIntent
    reason_code: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    clarify_hint: str | None = None


# ============================================================================
# 五、节点 5 `plan` 的输出（+ C-01 的派生摘要）
# ============================================================================

class PlanMetric(BaseModel):
    """计划里的一项指标 —— `plan_v1.txt` 要求"逐一交代口径"。"""

    model_config = _STRICT

    #: 必须**显式引用**语义包中的指标名（资产硬性规则 2：不得自行定义新口径）。
    name: str = Field(min_length=1)
    #: 口径说明（分子/分母、是否含税、是否去重）。
    caliber: str | None = None


class PlanAssetUse(BaseModel):
    """计划涉及的资产与它的角色（资产硬性规则 3：必须写出关联键与方向）。"""

    model_config = _STRICT

    asset: str = Field(min_length=1)
    #: 关联键与方向（如 `order_paid.order_id → order_item.order_id`）。
    join_key: str | None = None


class Plan(BaseModel):
    """结构化查询计划 —— **不含 SQL**（`PlannerPort` docstring：`plan_summary` 不含 SQL；N-17）。

    `blocking_issues` 非空 = 模型拒绝出计划（资产硬性规则 3/4：找不到关联路径、
    时间范围缺失时**不要猜**）。此时 `metrics` 可以为空 —— 由本类的校验器保证
    "要么给出可用的计划主体，要么给出阻塞原因"，不允许两者皆空。
    """

    model_config = _STRICT

    metrics: list[PlanMetric] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    grain: str | None = None
    time_range: TimeWindow = Field(default_factory=TimeWindow)
    order_by: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, gt=0)
    assets: list[PlanAssetUse] = Field(default_factory=list)
    output_columns: list[str] = Field(default_factory=list)
    #: 阻塞原因（模型自述"我为什么出不了计划"）→ W4 据此转澄清 / 拒答。
    blocking_issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _either_plan_or_blocked(self) -> Plan:
        if not self.blocking_issues and not self.metrics:
            raise ValueError(
                "计划既没有 `metrics` 也没有 `blocking_issues` —— "
                "「什么都没说」不是一份合法计划（要么给出指标，要么说明为什么给不出）"
            )
        return self

    def to_summary(self) -> PlanSummary:
        """派生 C-01 的 `plan_summary`（**唯一来源 = 本模型**，不手写第二份）。"""
        return PlanSummary(
            metrics=[m.name for m in self.metrics],
            dimensions=list(self.dimensions),
            filters=list(self.filters),
            grain=self.grain,
            time_range=self.time_range,
            order_by=list(self.order_by),
            limit=self.limit,
            blocked=bool(self.blocking_issues),
        )


class PlanSummary(BaseModel):
    """`stage=plan_ready` 事件的 `plan_summary`（补充契约 **C-01**）。

    键集**逐字对齐 C-01**：`{metrics[], dimensions[], filters[], grain, time_range{start,end},
    order_by[], limit}`，并"只放摘要，不含 SQL"。

    ⚠️ **唯一的偏离**：多了一个 `blocked` 布尔。"计划没出来"与"计划出来了但为空"
    在下游是完全不同的两条路（前者 → 模板/拒答，后者 → 澄清），而 C-01 的键集里
    没有承载位。多一个键而不是复用 `metrics == []` 去暗示，是因为"用空数组暗示失败"
    正是"靠约定传递状态"的写法 —— 每个消费方都可能读出不同结论。
    已登记为回填请求（`RELAY.md §给架构`）。
    """

    model_config = _STRICT

    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    grain: str | None = None
    time_range: TimeWindow = Field(default_factory=TimeWindow)
    order_by: list[str] = Field(default_factory=list)
    limit: int | None = None
    blocked: bool = False


# ============================================================================
# 六、节点 7 `gen_sql` / 节点 16 `repair` 的输出
# ============================================================================

class SqlCandidate(BaseModel):
    """一条候选 SQL（含参数与自评）。

    ⚠️ **`sql_text` 永不回灌 prompt**（N-17）。本对象只在**出站方向之外**流动：
    进 `GraphState.sql_text` / `sql_candidates`（审计用），以及进闸门。
    """

    model_config = _STRICT

    sql_text: str = Field(min_length=1)
    #: 参数化绑定（N-04）：**一律走占位符**，`%(name)s` 风格。
    params: dict[str, Any] = Field(default_factory=dict)
    #: 思路说明（资产规则 7 要的那"一段话"）。⚠️ 见模块 docstring §三-3：
    #: 资产措辞写的是 `plan_summary`，那个名字已被 C-01 占用，故此处改名。
    rationale: str | None = None
    #: ⚠️ P0 **不下发前端**（06 §4.4：未校准概率对业务用户有害），只进 state。
    confidence: float = Field(ge=0.0, le=1.0)


class GenSqlResult(BaseModel):
    """`gen_sql` / `gen_sql_complex` 的模型输出。

    ADR-11（先 1 路，按需升 N）在**一次调用内**表达：`candidates` 是列表，
    调用方通过 `candidates=N` 要求路数，本模块只校验"要么给够路数，要么说明为什么给不出"。
    """

    model_config = _STRICT

    candidates: list[SqlCandidate] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _either_sql_or_blocked(self) -> GenSqlResult:
        if not self.blocking_issues and not self.candidates:
            raise ValueError(
                "既没有候选 SQL 也没有 `blocking_issues` —— "
                "「什么都没说」不是一次合法生成（要么给出 SQL，要么说明为什么给不出）"
            )
        return self


class RepairResult(GenSqlResult):
    """`repair` 任务（节点 16）的模型输出 —— 在 `GenSqlResult` 上多一个自评开关。

    `repairable=False` 是资产的规则 3/5 明确鼓励的**放弃路径**：
    "错误摘要不足以定位原因时不要瞎改 —— 放弃比乱改更有价值"。
    因此 `repairable=False` 时 `blocking_issues` 必须非空（否则放弃就变成了空手而归）。
    """

    model_config = _STRICT

    repairable: bool = True

    @model_validator(mode="after")
    def _give_up_must_explain(self) -> RepairResult:
        if not self.repairable and not self.blocking_issues:
            raise ValueError("`repairable=false` 必须在 `blocking_issues` 里说明还缺什么信息")
        return self


# ============================================================================
# 七、`output_schema` 文本派生（**唯一真相的机器化**）
# ============================================================================

#: task → 输出模型。**只登记本窗口负责的 7 个 task**（其余归 W3C / `retrieval.refine` / `present`）。
_TASK_OUTPUT_MODELS: Final[Mapping[str, type[BaseModel]]] = MappingProxyType(
    {
        "normalize": NormalizeResult,
        "intent": IntentResult,
        "normalize_intent": NormalizeIntentResult,
        "plan": Plan,
        "gen_sql": GenSqlResult,
        "gen_sql_complex": GenSqlResult,
        "repair": RepairResult,
    }
)

#: Schema 文本的引导句。
#:
#: ⚠️ 它同时承担一个**上游硬约束**：`response_format={"type":"json_object"}` 要求整个消息里
#: 出现 `"json"` 字样，否则上游直接 400（W3A 实测，`egress_guard.build_wire_request` 有构造期断言）。
#: 本句含 "JSON"（断言是小写比较），与资产 SYSTEM 段的"只输出一个 JSON 对象"共同满足它。
_SCHEMA_PREAMBLE: Final[str] = (
    "输出 JSON Schema（**键名、类型、必填项均以此为准**；多出任何键都会被整份拒收）："
)


def output_schema_for(task: str) -> str:
    """`task` → 出站载荷 `output_schema` 字段的文本。

    🔴 **确定性**：`json.dumps(..., sort_keys=True)` + Pydantic 的确定性 schema 生成 ⇒
    同一 `task` 的返回值逐字节稳定。这不是洁癖 —— 该文本落在 prompt 的**稳定前缀**里
    （07 §10.3 前缀缓存布局），一旦它随请求变化，前缀缓存命中率会归零。

    ⚠️ 它**随模型定义变化** ⇒ 模型一改就等于 prompt 内容改了。这正是 §5.7
    "版本固定"要管的事：`prompt_version` 与 schema 必须一起冻结（见 `RELAY.md §给 W3-INT`）。
    """
    model = _TASK_OUTPUT_MODELS.get(task)
    if model is None:
        raise KeyError(
            f"`{task}` 不是本窗口（W3B）负责的 task —— 本模块只为 "
            f"{sorted(_TASK_OUTPUT_MODELS)} 提供 output_schema"
        )
    payload = model.model_json_schema()
    return f"{_SCHEMA_PREAMBLE}\n{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"


def task_output_models() -> Mapping[str, type[BaseModel]]:
    """`task → 输出模型` 的只读视图（测试与 W4 用；不要在调用方硬编码这份映射）。"""
    return _TASK_OUTPUT_MODELS


def schema_key_names(task: str) -> tuple[str, ...]:
    """某 task 允许出现的**顶层键名**（升序）。

    用于"模型输出里不许出现未登记键"这类断言的**正面对照**：
    断言必须来自模型本身，否则又是一份手写副本。
    """
    model = _TASK_OUTPUT_MODELS[task]
    return tuple(sorted(model.model_fields))
