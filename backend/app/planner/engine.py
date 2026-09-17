"""W3B 的引擎 —— 节点 2/3/5/7/16 的实现，也是 `PlannerPort` 的落地。

归属窗口：W3B（docs/08 §4.1）｜层号：L3

## 覆盖的节点（08 §3.5 的 DoD 指向 07 §5.3 的节点 2/3/5；7/16 是同一包的自然延伸）

| 节点 | 方法 | LLM task |
|---|---|---|
| 2 `normalize` | `normalize()` | `normalize` |
| 3 `intent` | `classify_intent()` | `intent` |
| **2+3 合并档** | `understand()` ← **推荐入口** | `normalize_intent` |
| 5 `plan` | `build_plan()`（端口）/ `plan_for()`（富） | `plan` |
| 7 `gen_sql` | `generate_sql()`（端口）/ `sql_for()`（富） | `gen_sql` / `gen_sql_complex` |
| 16 `repair` | `repair_sql()` | `repair` |

**为什么 `understand()` 是推荐入口**：07 §16.1 的压缩手段 1 就是"合并 `normalize` + `intent`
为一次调用"（省 ~0.6s；采用后串行合计 ≈7.5s，落回 8s 预算内）。
合并**不改变任何判定标准**（资产原文），只是省一次往返与一段重复上下文。

## 一、与网关的错误边界（**本文件最重要的不变量**）

```
LlmError 家族（LlmRefused / LlmConcurrencyExceeded / LlmUpstreamError / LlmEgressViolation …）
    → 一律原样上抛，本文件**不捕获**
本环节自己的校验失败（JSON 提取 / schema 校验）
    → 自己处理：修复 1 次 → 仍失败 → 抛 *Unavailable（由 W4 转 degraded / 模板 / 拒答）
```

🔴 **`LlmRefused` 必须原样上抛**：它 `default_code is None`，是**产品终态 `refuse`**，
不是错误（07 §10.2 最后一行）。把它包成 `PlanUnavailable` 会把"产品结论"变成
"一次业务降级" —— 语义就错了。⇒ 本文件里**没有** `except LlmError`，连"兜底 except"都不写，
因为兜底本身就是那个错误。

## 二、降级怎么上报（**两条通道，缺一不可**）

| 通道 | 谁发 | 谁接 |
|---|---|---|
| 网关的 `DegradationSink` | `app.llm`（出站跳：换模型 / 熔断 / 预算） | W4 |
| **本引擎的 `PlannerDegradationSink`** | 本文件（业务跳：理解失败 / 计划失败 / SQL 失败） | W4 |

本引擎**两条路都给**：① 同步回调 sink（默认只写结构化日志）；② 写进返回对象的
`degradations`（W4 可直接塞 `GraphState.degradations[]`）。
只留一条路的话，要么 SSE 看不到，要么 state 里没有 —— 两种都会让"降级可见性"出现缺口。

⚠️ 回调是**同步**的（与 `app.llm.DegradationSink` 同款理由，W3A 已论证）：它在 `call()` 的
同步段里被调用，阻塞它会直接吃掉任务的延迟预算。**禁止**在回调里 `asyncio.run(...)`。

## 三、并发安全（**已知限制，已具名登记**）

引擎实例是**无状态服务**，唯一的可变状态是 `_pending`（本次调用链产生的降级）。
它的生命周期严格限于一次公开方法调用：进入时清空、返回前取走。
⇒ **同一个 `PlannerEngine` 实例不得并发执行两次公开方法调用**。
W4 应当为**每个请求**构造一个引擎，或在装配层用工厂；
若将来要求单实例并发，`_pending` 必须换成 `contextvars`（与 `app.llm.set_call_context` 同款）。
这条写在 `DELIVERY.md` 的已知限制里，**不是**"应该没问题"。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, NoReturn, Protocol, TypeVar, cast

from pydantic import BaseModel, ValidationError

from app.cache.keys import user_scope_hash
from app.core.contracts import (
    ClockPort,
    IdentityContext,
    LLMPort,
    LLMResponse,
    SemanticBundlePort,
    TokenUsage,
)
from app.core.enums import RefuseReason
from app.llm.egress_guard import MAX_ERROR_DIGEST_CHARS
from app.llm.router import MODEL_AUTO, LlmTask
from app.planner.errors import (
    PlannerError,
    PlanUnavailable,
    SqlGenerationUnavailable,
    UnderstandUnavailable,
)
from app.planner.jsonish import JsonAttempt, extract_json_object, validation_digest
from app.planner.payloads import (
    PromptContext,
    detect_injection,
    gen_sql_payload,
    intent_payload,
    normalize_intent_payload,
    normalize_payload,
    plan_payload,
    repair_payload,
)
from app.planner.schemas import (
    INTENT_MAP,
    DegradedNote,
    GenSqlResult,
    IntentKind,
    IntentResult,
    LlmIntent,  # noqa: F401  —— 类型注解阅读用；运行时只经 INTENT_MAP
    NormalizeIntentResult,
    NormalizeResult,
    Plan,
    PlanSummary,
    RepairResult,
    ResolvedTerm,
    SqlCandidate,
    TimeRange,
)
from app.planner.timeexpr import resolve_time

__all__ = [
    "LoggingDegradationSink",
    "LlmCallMeta",
    "PlanOutcome",
    "PlannerDegradationSink",
    "PlannerEngine",
    "SqlOutcome",
    "UnderstandOutcome",
]

_log = logging.getLogger(__name__)

#: 修复重试次数 —— 07 §10.3 写死"修复重试 **1** 次"，**不可配置**：
#: 配置化会诱使有人调大它，而每多一次修复就多一分延迟与一分费用，
#: 且成功率并不会因此变好（校验错误摘要已经给出了定位信息）。
MAX_REPAIR_ATTEMPTS: Final[int] = 1

_ModelT = TypeVar("_ModelT", bound=BaseModel)


# ============================================================================
# 一、降级上报（同步回调，见模块 docstring §二）
# ============================================================================

class PlannerDegradationSink(Protocol):
    """本引擎的降级上报点。**同步**方法（理由见模块 docstring §二）。"""

    def on_degraded(self, note: DegradedNote) -> None: ...


class LoggingDegradationSink:
    """默认实现：只写结构化日志。

    ⚠️ **默认 = 前端看不到降级**（与 W3A 的默认 sink 同款取舍）。W4 必须换实现，
    否则"这次答案来自降级路径"这句话只存在于服务端日志里（N-21 要求用户有权知道）。
    """

    def on_degraded(self, note: DegradedNote) -> None:
        _log.warning(
            "planner_degraded",
            extra={
                "reason": str(note.reason),
                "action_taken": str(note.action_taken),
                "detail": dict(note.detail),
            },
        )


# ============================================================================
# 二、调用元数据（N-19 / C-03 的承载）
# ============================================================================

@dataclass(frozen=True, slots=True)
class LlmCallMeta:
    """一次（或修复后的两次）LLM 调用的合计元数据。

    ⚠️ `model` / `prompt_version` 取**最终产出被接受的那一次** —— 若走过修复轮次，
    首轮的版本号不能代表"这份结果是谁产出的"，把它记为版本等于审计撒谎。
    token 与成本则**两次都算**（钱确实花了）。
    """

    model: str
    prompt_version: str
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost_cny: Decimal = Decimal(0)
    calls: int = 1

    @classmethod
    def of(cls, resp: LLMResponse, *, calls: int = 1) -> LlmCallMeta:
        return cls(
            model=resp.model,
            prompt_version=resp.prompt_version,
            tokens=resp.tokens,
            cost_cny=resp.cost_cny,
            calls=calls,
        )

    def merged_with(self, other: LlmCallMeta) -> LlmCallMeta:
        """累加两次调用：token/成本相加，模型与版本取 `other`（后一次 = 产出者）。"""
        first, second = self.tokens, other.tokens
        return LlmCallMeta(
            model=other.model,
            prompt_version=other.prompt_version,
            tokens=TokenUsage(
                input=first.input + second.input,
                output=first.output + second.output,
                cache_hit=first.cache_hit + second.cache_hit,
                total=first.total + second.total,
            ),
            cost_cny=self.cost_cny + other.cost_cny,
            calls=self.calls + other.calls,
        )


# ============================================================================
# 三、产出对象（形状对齐 `GraphState`，W4 不必再翻译一遍）
# ============================================================================

@dataclass(frozen=True, slots=True)
class UnderstandOutcome:
    """节点 2（+3，走 `understand()` 合并档）的产出。

    | 字段 | `GraphState` 位置 |
    |---|---|
    | `normalized_question` / `time_range` / `resolved_terms` / `unresolved_terms` / `time_parse_ok` | 组 2 |
    | `intent` / `intent_detail` | 组 3 |
    | `degradations` | 组 10 |
    | `injection` | 审计（无对应 state 字段，见 `RELAY.md §给 W4`） |
    """

    merged: bool
    normalized_question: str
    intent: IntentKind
    refuse_kind: RefuseReason | None
    reason_code: str | None
    clarify_hint: str | None
    confidence: float
    time_range: TimeRange | None
    time_parse_ok: bool
    time_reason: str | None
    resolved_terms: tuple[ResolvedTerm, ...]
    unresolved_terms: tuple[str, ...]
    injection: Mapping[str, Any]
    meta: LlmCallMeta
    attempts: int
    latency_ms: int
    degradations: tuple[DegradedNote, ...] = ()

    @property
    def intent_detail(self) -> Mapping[str, Any]:
        """`GraphState.intent_detail` 的形状：`{refuse_kind?, reason_code}`。

        ⚠️ `refuse_kind` **只在 REFUSE 时出现** —— 非拒答时也给一个 `None` 会让下游
        "有值即拒答"的判定失效（那是最典型的一类静默错判）。
        """
        detail: dict[str, Any] = {"reason_code": self.reason_code}
        if self.refuse_kind is not None:
            detail["refuse_kind"] = str(self.refuse_kind)
        return detail

    def state_payload(self) -> dict[str, Any]:
        """可直接 `state.update(...)` 的形状（键名对齐 07 §5.2 组 2/组 3）。"""
        return {
            "normalized_question": self.normalized_question,
            "time_range": self.time_range.model_dump() if self.time_range else None,
            "resolved_terms": [t.model_dump() for t in self.resolved_terms],
            "unresolved_terms": list(self.unresolved_terms),
            "time_parse_ok": self.time_parse_ok,
            "intent": str(self.intent),
            "intent_detail": dict(self.intent_detail),
        }


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    """节点 5 的产出。`plan_summary` 是 `stage=plan_ready` 事件的载荷（C-01）。"""

    plan: Plan
    plan_summary: PlanSummary
    meta: LlmCallMeta
    attempts: int
    latency_ms: int
    degradations: tuple[DegradedNote, ...] = ()

    def state_payload(self) -> dict[str, Any]:
        return {
            "plan": self.plan.model_dump(),
            "plan_summary": self.plan_summary.model_dump(),
            "prompt_version": self.meta.prompt_version,
            "model_version": self.meta.model,
        }


@dataclass(frozen=True, slots=True)
class SqlOutcome:
    """节点 7 / 16 的产出。

    ⚠️ `requested` vs `len(candidates)`：调用方按 ADR-11 可能要求 N 路，
    模型可能只给回 M < N 路。本对象**如实记录两个数**，不把它伪装成一次降级事件
    （`DegradedReason` 里没有"路数不足"的取值，硬套一个就是撒谎）；W4 可据两者之差自作判断。
    """

    task: str
    candidates: tuple[SqlCandidate, ...]
    blocking_issues: tuple[str, ...]
    requested: int
    repair_used: bool
    meta: LlmCallMeta
    attempts: int
    latency_ms: int
    degradations: tuple[DegradedNote, ...] = ()

    @property
    def primary(self) -> SqlCandidate | None:
        """首选候选（`GraphState.sql_text` / `sql_params` 的来源）。"""
        return self.candidates[0] if self.candidates else None

    def state_payload(self) -> dict[str, Any]:
        top = self.primary
        return {
            "sql_text": top.sql_text if top else "",
            "sql_params": dict(top.params) if top else {},
            "sql_dialect": "postgres",
            "sql_candidates": [c.model_dump() for c in self.candidates],
            "prompt_version": self.meta.prompt_version,
            "model_version": self.meta.model,
            "confidence": top.confidence if top else 0.0,
        }


# ============================================================================
# 四、内部信号：校验用尽
# ============================================================================

class _ValidationExhausted(Exception):
    """**内部**信号：JSON 取不到 / schema 不过，且修复重试已用尽。

    为什么用一个内部异常而不是让 `_call_validated` 接收一个 `unavailable` 回调工厂：
    回调工厂捕获不到"用了几次"，只能让调用方去猜（本文件的初版就写成 `attempts_of(digest)`，
    那是个近似值）。异常携带**确切**的 `attempts`，且把"抛哪个领域异常"留给调用方 ——
    每个节点抛的异常类不同，只有它的调用方知道该抛哪个。
    """

    def __init__(self, digest: str, *, attempts: int) -> None:
        super().__init__(digest)
        self.digest = digest
        self.attempts = attempts


# ============================================================================
# 五、引擎
# ============================================================================

class PlannerEngine:
    """节点 2/3/5/7/16 的实现 + `PlannerPort`。

    依赖全部**注入**（不在模块里 new 任何东西）：

    | 依赖 | 来自 | 为什么必须是注入 |
    |---|---|---|
    | `llm: LLMPort` | W4 在 lifespan 装配 | 本类不 new 网关；测试可直接给假端口 |
    | `semantics: SemanticBundlePort` | W2A | 语义摘要与时间词表**只能**来自它（N-26） |
    | `clock: ClockPort` | W0 | 唯一时间来源（N-18）；本类**不调** `datetime.now()` |
    | `degradation` | W4（SSE 队列） | 见模块 docstring §二 |
    | `few_shots` | W1B/W6（Gold Query 库） | 没有就**不假装有**（默认不传 few-shot） |

    ⚠️ `user_scope` 由 `app.cache.keys.user_scope_hash` 现算（**键构造的唯一入口**，
    本类不自己哈希 —— 那会造出第二套隔离口径）。
    """

    __slots__ = ("_clock", "_degradation", "_few_shots", "_llm", "_monotonic", "_pending", "_semantics")

    def __init__(
        self,
        *,
        llm: LLMPort,
        semantics: SemanticBundlePort,
        clock: ClockPort,
        degradation: PlannerDegradationSink | None = None,
        few_shots: Callable[[str], Sequence[tuple[str, str]]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._llm = llm
        self._semantics = semantics
        self._clock = clock
        self._degradation: PlannerDegradationSink = degradation or LoggingDegradationSink()
        self._few_shots = few_shots
        self._monotonic = monotonic or time.perf_counter
        self._pending: list[DegradedNote] = []

    # ------------------------------------------------------------------
    # 公共入口：节点 2 + 3（合并档 = 推荐路径）
    # ------------------------------------------------------------------

    async def understand(
        self, ctx: IdentityContext, question: str, *, history: Sequence[str] = ()
    ) -> UnderstandOutcome:
        """节点 2 + 3：**一次调用**拿到归一化 + 意图（07 §16.1 压缩手段 1）。

        `LlmError` 一律上抛（含 `LlmRefused`）；本环节只在"JSON 取不到 / schema 不过"时降级。
        """
        self._reset()
        prompt_ctx = self._prompt_context(ctx)
        payload = normalize_intent_payload(prompt_ctx, question=question, history=history)
        started = self._monotonic()
        try:
            parsed, meta, attempts = await self._call_validated(
                task=str(LlmTask.NORMALIZE_INTENT),
                payload=payload,
                schema=NormalizeIntentResult,
                # 该资产**没有** `$error_digest` 槽 → 修复轮次只能同 task 重发（Q2 裁定的代价）
                repair_payload_factory=lambda _digest: normalize_intent_payload(
                    prompt_ctx, question=question, history=history
                ),
            )
        except _ValidationExhausted as exc:
            self._report_and_raise(UnderstandUnavailable(
                "归一化+意图的模型输出不可用（已用尽修复重试）",
                attempts=exc.attempts,
                detail={"last_validation_error": _first_line(exc.digest), "task": "normalize_intent"},
            ))
        latency = _elapsed_ms(started, self._monotonic())

        resolution = resolve_time(parsed.normalized_question, self._semantics, self._clock)
        intent, refuse_kind = INTENT_MAP[parsed.intent]
        return UnderstandOutcome(
            merged=True,
            normalized_question=parsed.normalized_question,
            intent=intent,
            refuse_kind=refuse_kind,
            reason_code=parsed.reason_code,
            clarify_hint=parsed.clarify_hint,
            confidence=parsed.confidence,
            time_range=resolution.window,
            time_parse_ok=resolution.ok,
            time_reason=resolution.reason,
            resolved_terms=resolution.terms,
            unresolved_terms=tuple(dict.fromkeys((*resolution.unresolved, *parsed.unmapped_terms))),
            injection=detect_injection(question).as_dict(),
            meta=meta,
            attempts=attempts,
            latency_ms=latency,
            degradations=self._take_notes(),
        )

    async def normalize(
        self, ctx: IdentityContext, question: str, *, history: Sequence[str] = ()
    ) -> UnderstandOutcome:
        """节点 2 单跑（`understand()` 的拆分版）。

        存在的理由：合并档是**优化**，不是**必需** —— DoD① 要实测"合并省了多少"，
        而没有不合并的那条路径，"省了多少"根本无从测量（两个口径必须都能跑）。
        单跑**不产出意图**：`intent` 置为 `EXECUTABLE` 的占位，由 `classify_intent` 覆盖
        （`merged=False` 就是给调用方看的标记）。
        """
        self._reset()
        prompt_ctx = self._prompt_context(ctx)
        payload = normalize_payload(prompt_ctx, question=question, history=history)
        started = self._monotonic()
        try:
            parsed, meta, attempts = await self._call_validated(
                task=str(LlmTask.NORMALIZE),
                payload=payload,
                schema=NormalizeResult,
                repair_payload_factory=lambda _digest: normalize_payload(
                    prompt_ctx, question=question, history=history
                ),
            )
        except _ValidationExhausted as exc:
            self._report_and_raise(UnderstandUnavailable(
                "归一化的模型输出不可用（已用尽修复重试）",
                attempts=exc.attempts,
                detail={"last_validation_error": _first_line(exc.digest), "task": "normalize"},
            ))
        latency = _elapsed_ms(started, self._monotonic())
        resolution = resolve_time(parsed.normalized_question, self._semantics, self._clock)
        return UnderstandOutcome(
            merged=False,
            normalized_question=parsed.normalized_question,
            intent=IntentKind.EXECUTABLE,
            refuse_kind=None,
            reason_code=None,
            clarify_hint=None,
            confidence=0.0,
            time_range=resolution.window,
            time_parse_ok=resolution.ok,
            time_reason=resolution.reason,
            resolved_terms=resolution.terms,
            unresolved_terms=tuple(dict.fromkeys((*resolution.unresolved, *parsed.unmapped_terms))),
            injection=detect_injection(question).as_dict(),
            meta=meta,
            attempts=attempts,
            latency_ms=latency,
            degradations=self._take_notes(),
        )

    async def classify_intent(self, ctx: IdentityContext, question: str) -> UnderstandOutcome:
        """节点 3 单跑（不归一化）。用于"归一化已固定/已缓存"的路径与分项埋点。"""
        self._reset()
        prompt_ctx = self._prompt_context(ctx)
        payload = intent_payload(prompt_ctx, question=question)
        started = self._monotonic()
        try:
            parsed, meta, attempts = await self._call_validated(
                task=str(LlmTask.INTENT),
                payload=payload,
                schema=IntentResult,
                repair_payload_factory=lambda _digest: intent_payload(prompt_ctx, question=question),
            )
        except _ValidationExhausted as exc:
            self._report_and_raise(UnderstandUnavailable(
                "意图分类的模型输出不可用（已用尽修复重试）",
                attempts=exc.attempts,
                detail={"last_validation_error": _first_line(exc.digest), "task": "intent"},
            ))
        latency = _elapsed_ms(started, self._monotonic())
        intent, refuse_kind = INTENT_MAP[parsed.intent]
        return UnderstandOutcome(
            merged=False,
            normalized_question=question,
            intent=intent,
            refuse_kind=refuse_kind,
            reason_code=parsed.reason_code,
            clarify_hint=parsed.clarify_hint,
            confidence=parsed.confidence,
            time_range=None,
            time_parse_ok=True,
            time_reason=None,
            resolved_terms=(),
            unresolved_terms=(),
            injection=detect_injection(question).as_dict(),
            meta=meta,
            attempts=attempts,
            latency_ms=latency,
            degradations=self._take_notes(),
        )

    # ------------------------------------------------------------------
    # 节点 5：查询计划
    # ------------------------------------------------------------------

    async def plan_for(
        self,
        ctx: IdentityContext,
        *,
        normalized_question: str,
        extra_constraints: str = "",
    ) -> PlanOutcome:
        """节点 5：结构化查询计划（**不含 SQL**）。

        ⚠️ `normalized_question` 是**归一化后**的问题 —— 出站的是它，不是原始问题
        （§10.5 ③"归一化后的用户问题"才是允许出站的形态）。
        """
        self._reset()
        prompt_ctx = self._prompt_context(ctx)
        payload = plan_payload(
            prompt_ctx, question=normalized_question, extra_constraints=extra_constraints
        )
        started = self._monotonic()
        try:
            parsed, meta, attempts = await self._call_validated(
                task=str(LlmTask.PLAN),
                payload=payload,
                schema=Plan,
                repair_payload_factory=lambda _digest: plan_payload(
                    prompt_ctx, question=normalized_question, extra_constraints=extra_constraints
                ),
            )
        except _ValidationExhausted as exc:
            self._report_and_raise(PlanUnavailable(
                "查询计划的模型输出不可用（已用尽修复重试）",
                attempts=exc.attempts,
                detail={"last_validation_error": _first_line(exc.digest), "task": "plan"},
            ))
        latency = _elapsed_ms(started, self._monotonic())
        return PlanOutcome(
            plan=parsed,
            plan_summary=parsed.to_summary(),
            meta=meta,
            attempts=attempts,
            latency_ms=latency,
            degradations=self._take_notes(),
        )

    # ------------------------------------------------------------------
    # 节点 7 / 16：SQL 生成与有界纠错
    # ------------------------------------------------------------------

    async def sql_for(
        self,
        ctx: IdentityContext,
        *,
        normalized_question: str,
        plan: Plan,
        candidates: int = 1,
        complex_query: bool = False,
    ) -> SqlOutcome:
        """节点 7：把计划翻成 SQL。

        `complex_query=True` → 走 `gen_sql_complex`（PRD §12.2：L3+ 复杂，**唯一走思考的档**）。
        `candidates`（ADR-11 的 N 路）写进约束块告诉模型要几条；**不硬校验条数**（见 `SqlOutcome`）。
        """
        self._reset()
        prompt_ctx = self._prompt_context(ctx)
        block = _plan_block(plan, requested=max(1, candidates))
        task = str(LlmTask.GEN_SQL_COMPLEX if complex_query else LlmTask.GEN_SQL)
        payload = gen_sql_payload(
            prompt_ctx,
            question=normalized_question,
            plan_block=block,
            few_shots=self._few_shots_for(normalized_question),
            complex_task=complex_query,
        )
        started = self._monotonic()
        try:
            parsed, meta, attempts = await self._call_validated(
                task=task,
                payload=payload,
                schema=GenSqlResult,
                # 🔴 Q2 裁定：`gen_sql*` 的修复轮次改走 `repair` 任务
                #    （它的资产有 `$error_digest` 槽）。代价见 jsonish 模块 docstring §二。
                repair_payload_factory=lambda digest: repair_payload(
                    prompt_ctx,
                    question=normalized_question,
                    plan_block=block,
                    error_digest=digest,
                ),
                repair_task=str(LlmTask.REPAIR),
                # 🔴 换 task 必须**同时**换输出模型：`repair_v1` 要求 `repairable` 键，
                #    拿 `GenSqlResult`（extra="forbid"）校验会把那个键当未登记字段拒收。
                repair_schema=RepairResult,
            )
        except _ValidationExhausted as exc:
            self._report_and_raise(SqlGenerationUnavailable(
                "SQL 生成的模型输出不可用（已用尽修复重试）",
                attempts=exc.attempts,
                detail={"last_validation_error": _first_line(exc.digest), "task": task},
            ))
        latency = _elapsed_ms(started, self._monotonic())
        return SqlOutcome(
            task=task,
            candidates=tuple(parsed.candidates),
            blocking_issues=tuple(parsed.blocking_issues),
            requested=max(1, candidates),
            repair_used=attempts > 1,
            meta=meta,
            attempts=attempts,
            latency_ms=latency,
            degradations=self._take_notes(),
        )

    async def repair_sql(
        self,
        ctx: IdentityContext,
        *,
        normalized_question: str,
        plan: Plan,
        error_digest: str,
    ) -> SqlOutcome:
        """节点 16：有界纠错（≤2 轮由 W4 的 `repair_round` 控制，本方法只管**一轮**）。

        🔴 **拿不到失败的那条 SQL**（N-17）：输入只有计划 + 脱敏错误摘要。
        资产原文说明了理由："乱改会产出一条看起来能跑但算错的 SQL，那比失败更危险。"
        """
        self._reset()
        prompt_ctx = self._prompt_context(ctx)
        block = _plan_block(plan, requested=1)
        payload = repair_payload(
            prompt_ctx, question=normalized_question, plan_block=block, error_digest=error_digest
        )
        started = self._monotonic()
        try:
            parsed, meta, attempts = await self._call_validated(
                task=str(LlmTask.REPAIR),
                payload=payload,
                schema=RepairResult,
                # 纠错本身**不再套一层修复**（有界纠错是 2 轮，不是 4 轮）
                repair_payload_factory=None,
            )
        except _ValidationExhausted as exc:
            self._report_and_raise(SqlGenerationUnavailable(
                "纠错的模型输出不可用（已用尽修复重试）",
                attempts=exc.attempts,
                detail={
                    "stage": "repair",
                    "last_validation_error": _first_line(exc.digest),
                    "task": str(LlmTask.REPAIR),
                },
            ))
        latency = _elapsed_ms(started, self._monotonic())
        return SqlOutcome(
            task=str(LlmTask.REPAIR),
            candidates=tuple(parsed.candidates),
            blocking_issues=tuple(parsed.blocking_issues),
            requested=1,
            repair_used=False,
            meta=meta,
            attempts=attempts,
            latency_ms=latency,
            degradations=self._take_notes(),
        )

    # ------------------------------------------------------------------
    # `PlannerPort`（端口方法 = 富方法的薄包装，返回 state 形状的 Mapping）
    # ------------------------------------------------------------------

    async def build_plan(
        self, question: str, candidates: Sequence[Any], ctx: IdentityContext
    ) -> Mapping[str, Any]:
        """`PlannerPort.build_plan`。

        🔴 **`candidates`（检索候选）当前不进 prompt**：`EgressPayload.candidates` 是
        W3A 为"精筛 / L4 打分器"登记的可选字段，而 `plan_v1.txt` 的 USER 段**没有**
        `$candidates_block` 占位符（实测）—— 传了也不会被渲染。
        ⇒ 计划的资产信息**只经 `semantic_summary`** 到达模型（那是资产级引用，不是候选级排序）。
        若将来要让计划看到"本轮候选 Top-N"，那是**资产侧改动**（W3A 的 `plan_v1`）；
        这里把口径写清，而不是偷偷把候选塞进 `constraints`（那会糊掉槽位语义）。
        """
        del candidates  # 见 docstring：当前不进 prompt，不假装用上了
        outcome = await self.plan_for(ctx, normalized_question=question)
        return outcome.state_payload()

    async def generate_sql(
        self, plan: Mapping[str, Any], ctx: IdentityContext, *, candidates: int
    ) -> Mapping[str, Any]:
        """`PlannerPort.generate_sql`。

        ⚠️ 端口签名里**没有**"归一化问题"这一位 —— 而 `gen_sql_v1.txt` 的 USER 段需要它。
        本实现的取舍：从 `plan` 里取 `normalized_question`（**这是本窗口与 W4 约定的入参形状**，
        见 `RELAY.md §给 W4`）；缺失时**抛契约错误而不是编一个** ——
        编一个 = 基于错误的问题生成 SQL。
        """
        question = _question_of(plan)
        if not question:
            raise PlannerError(
                "`generate_sql` 缺少归一化问题：端口签名没有这一位，需调用方在 `plan` 里带上 "
                "`normalized_question`。见 RELAY.md §给 W4 的入参约定与 §给架构的端口缺口登记。"
            )
        plan_model = _coerce_plan(plan)
        if plan_model.blocking_issues:
            # 计划自述有阻塞项 → 不生成 SQL（资产规则 7：宁可不输出，也不猜）
            self._report_and_raise(
                SqlGenerationUnavailable(
                    "计划带 `blocking_issues`，按资产规则不生成 SQL",
                    attempts=0,
                    detail={"blocking_issues": list(plan_model.blocking_issues)},
                )
            )
        outcome = await self.sql_for(
            ctx,
            normalized_question=question,
            plan=plan_model,
            candidates=candidates,
            complex_query=_looks_complex(plan_model),
        )
        return outcome.state_payload()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _reset(self) -> None:
        """进入一次公开调用前清空降级累积（见模块 docstring §三的并发限制）。"""
        self._pending.clear()

    def _take_notes(self) -> tuple[DegradedNote, ...]:
        """取走并清空本次调用累积的降级。"""
        notes = tuple(self._pending)
        self._pending.clear()
        return notes

    def _emit(self, note: DegradedNote) -> None:
        """上报一条降级：**同时**走 sink（W4 转 SSE）与返回对象的 `degradations`。"""
        self._pending.append(note)
        self._degradation.on_degraded(note)

    def _report_and_raise(self, exc: PlannerError) -> NoReturn:
        """把领域异常携带的 `notes` **送进 sink**，然后抛出。

        ## 为什么失败路径必须显式上报（这条是补上一个真实缺口）

        初版的四个失败分支只做了 `raise XxxUnavailable(...)` —— 而 `*Unavailable` 的
        `notes` 是在**异常对象内部**构造的，`_emit()` 从头到尾**没有任何调用点**。
        后果是：`PlannerEngine.__init__` 收下的那个 `degradation` sink
        （W4 装配时注入、文档写明"W4 依此发 `degraded`"）**永远收不到东西** ——
        也就是"降级双通道"里业务跳那一条**根本没接线**。而 `_emit` 又是本类唯一
        写 `_pending` 的地方，于是所有产出对象的 `degradations` 恒为空元组。

        这是最坏的一类缺陷：**编译通过、测试若不断言就全绿、线上表现为"前端从不提示降级"**。
        07 §5.3 的失败转移（`plan = None` → `degraded` → 模板 → `refuse`）要求这一跳真实存在。

        ## W4 只接一条（避免双发）

        sink 与 `exc.notes` 现在是**同一条事件的两个载体**：
        - 接了 sink（设计路径）→ **不要**再把 `exc.notes` 转发一次，否则前端收到两条；
        - 只捕获异常、没接 sink（例如日志/审计/测试）→ 从 `exc.notes` 取，内容一致。
        """
        for note in exc.notes:
            self._emit(note)  # 唯一上报路径：`_emit` 同时写 sink 与 `_pending`
        raise exc from None

    def _prompt_context(self, ctx: IdentityContext) -> PromptContext:
        return PromptContext.from_semantics(
            ctx, self._semantics, user_scope=user_scope_hash(ctx.user_id)
        )

    def _few_shots_for(self, question: str) -> tuple[tuple[str, str], ...]:
        """few-shot 取数（**可选能力**：没注入就等于没有 Gold Query 库，不假装有）。"""
        if self._few_shots is None:
            return ()
        return tuple(self._few_shots(question))

    async def _call_validated(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
        schema: type[_ModelT],
        repair_payload_factory: Callable[[str], Mapping[str, Any]] | None,
        repair_task: str | None = None,
        repair_schema: type[_ModelT] | None = None,
    ) -> tuple[_ModelT, LlmCallMeta, int]:
        """调用 → 严格校验 → **修复 1 次** → 仍失败即抛 `_ValidationExhausted`。

        返回 `(parsed, meta, attempts)`。

        ## 🔴 `repair_schema` 为什么必须存在（一个被测试抓出来的真缺陷）

        修复轮**换的不只是资产，可能还有输出形状**：`gen_sql` 的修复走 `repair_v1` 资产，
        而该资产要求模型输出 `repairable` 字段（它的 `output_schema` 是 `RepairResult`）。
        若仍拿首轮的 `GenSqlResult` 去校验 —— 那是 `extra="forbid"` 的模型 ——
        那个**被要求输出的** `repairable` 键会变成"未登记字段"，**整份拒收**。
        后果：`gen_sql` 的修复轮**永远不可能成功**，白烧一次调用与一段延迟，
        并且最终错误信息还指向"模型输出不可用"（把工程缺陷伪装成模型不听话）。

        ⇒ 调用方在换 task 时**必须同时声明**该轮的输出模型。默认 `None` = 不换
        （形状相同的重发，如 `normalize_intent` 的修复）。

        本函数**不捕获任何 `LlmError`**（见模块 docstring §一）。
        """
        first = await self._llm.call(task, payload, MODEL_AUTO)
        attempt = _validate(first.text, schema)
        if attempt.ok:
            return cast(_ModelT, attempt.parsed), LlmCallMeta.of(first), 1

        digest = _digest_or_placeholder(attempt)
        if repair_payload_factory is None or MAX_REPAIR_ATTEMPTS < 1:
            raise _ValidationExhausted(digest, attempts=1)

        second = await self._llm.call(repair_task or task, repair_payload_factory(digest), MODEL_AUTO)
        retry = _validate(second.text, repair_schema or schema)
        if retry.ok:
            return (
                cast(_ModelT, retry.parsed),
                LlmCallMeta.of(first).merged_with(LlmCallMeta.of(second)),
                2,
            )
        raise _ValidationExhausted(_digest_or_placeholder(retry), attempts=2)


# ============================================================================
# 六、模块级纯函数（可单独测）
# ============================================================================

def _elapsed_ms(started: float, now: float) -> int:
    """毫秒延迟（非负整数）。"""
    return max(0, round((now - started) * 1000))


def _validate(text: str, schema: type[BaseModel]) -> JsonAttempt:
    """提取 + 严格校验，**不抛异常**（失败信息转成摘要）。"""
    obj, reason = extract_json_object(text)
    if obj is None:
        return JsonAttempt(parsed=None, error_digest=reason)
    try:
        return JsonAttempt(parsed=schema.model_validate(dict(obj)), error_digest=None)
    except ValidationError as exc:
        return JsonAttempt(
            parsed=None, error_digest=validation_digest(exc, limit=MAX_ERROR_DIGEST_CHARS)
        )


def _digest_or_placeholder(attempt: JsonAttempt) -> str:
    """修复轮次用的错误摘要。

    ⚠️ "提取失败"（没找到 JSON）时没有 Pydantic 错误清单。此时给**一句可操作提示** ——
    比留空强（留空 = 第二次调用与第一次逐字相同，白花一次钱与一次延迟），
    但必须**如实**说明这是"没有结构可报"，不是"结构没错"。
    """
    if attempt.error_digest:
        return (
            "上一次输出未通过校验，原因如下（**请只修正这些问题，不要改动其余内容**）：\n"
            f"- {attempt.error_digest}"
        )
    return "上一次输出未通过校验（未取得可用于定位的校验信息）"


def _first_line(digest: str) -> str:
    """摘要的首行（进 `detail`，避免把整段错误清单塞进事件帧）。"""
    return digest.splitlines()[0][:200] if digest else ""


def _question_of(plan: object) -> str:
    """从端口入参里取归一化问题（约定形状见 `generate_sql` 的 docstring）。

    形参声明为 `object` 而非 `Mapping`：这是**边界解析**，入参来自图状态字典，
    运行期不保证真的是 Mapping（类型标注挡不住上游塞进来的意外值），
    故保留 `isinstance` 兜底，且让 mypy 不把该分支判为不可达。
    """
    if not isinstance(plan, Mapping):
        return ""
    inner = plan.get("plan")
    for key in ("normalized_question", "question"):
        value = plan.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(inner, Mapping):
        for key in ("normalized_question", "question"):
            value = inner.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _coerce_plan(plan: Mapping[str, Any]) -> Plan:
    """端口入参 → `Plan`。

    接受两种形状（都写进 `RELAY.md §给 W4`）：① 裸 `Plan` 形状的 mapping；
    ② 本引擎 `plan_for().state_payload()` 的形状（含 `plan` 子对象）。
    其余一律 `ValidationError` —— **不做"尽量读懂"的容错**：容错会把 W4 传错形状这件事
    变成"某些键静默缺失的计划"。
    """
    if isinstance(plan, Mapping):
        inner = plan.get("plan")
        if isinstance(inner, Mapping):
            return Plan.model_validate(dict(inner))
    return Plan.model_validate(dict(plan))


def _plan_block(plan: Plan, *, requested: int) -> str:
    """把计划渲染成 `constraints` 槽的文本（**确定性**：`sort_keys=True`）。

    ⚠️ 这里**只放计划内容**：不含 SQL（`Plan` 结构里本就没有）、不含候选/结果集（N-12）。
    `requested`（ADR-11 的路数）作为额外要求附在末尾 —— 那正是"附加约束"语义，
    而该槽在 `gen_sql` 资产里就是"计划 + 附加要求"。
    """
    body = json.dumps(plan.model_dump(), ensure_ascii=False, sort_keys=True, indent=2)
    return f"{body}\n\n期望候选 SQL 条数：{requested}"


#: 复杂查询的判定信号（决定走 `gen_sql` 还是 `gen_sql_complex`）。
#:
#: 🔴 **这是一个自设启发式，必须被登记**：PRD §12.2 说"SQL 生成（L3+ 复杂）"，
#: 但**没有给出 L3 的判定规则**（07 全文也没有）。⇒ 本窗口按"计划里出现
#: 窗口函数/排名/同环比/累计信号"来判，并在 `DELIVERY.md` 具名登记。
#: 宁可先有一个显式、可审计、可替换的规则，也不要"看情况决定" —— 后者无法被复核。
_COMPLEX_HINTS: Final[tuple[str, ...]] = (
    "排名",
    "占比",
    "同比",
    "环比",
    "累计",
    "增长率",
    "top",
    "rank",
    "window",
    "row_number",
    "partition",
)


def _looks_complex(plan: Plan) -> bool:
    """计划文本里是否有复杂查询信号（见 `_COMPLEX_HINTS` 的登记说明）。"""
    hay = json.dumps(plan.model_dump(), ensure_ascii=False, sort_keys=True).lower()
    return any(hint in hay for hint in _COMPLEX_HINTS)
