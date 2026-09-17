"""LLM 网关门面 —— `LLMPort` 的实现与唯一对外出口。

层号：L1｜归属窗口：W3A（docs/08 §4.1）｜落点：07 §3.2 `llm/`（含 `prompts/`）

调用方（**只认识本模块**）：`app.planner`（W3B：normalize / intent / plan / gen_sql /
repair）、`app.binding` 的 L4 打分器（W3C，**经 `LLMPort` 端口**）、
`app.retrieval.refine`（P0 未实现）、`present`。

## 一、本模块做的是**编排**，不是把逻辑再写一遍

    白名单载荷（egress_guard） → 路由与超时（router） → prompt 渲染（prompts）
    → 预算 pre-flight（budget） → 出站（client） → 结算（budget） → 降级链（本模块）

每一环都有独立单测；本模块只负责**顺序**与**失败时往下走哪一级**。

## 二、🔴 契约缺口：`LLMResponse` 装不下 `degraded` 与 `refuse`

端口被冻结为 `call(task, payload, model) -> LLMResponse`，而
`LLMResponse = (text, model, prompt_version, tokens, cost_cny)`。
07 §10.2 却要求"每一级降级必须发 `degraded` + `action_taken`"、以及
"模板无命中 = `refuse`（**不是 error**）" —— 这两样**都不在** `LLMResponse` 里。
而 `app.llm` 在 L1、`app.graph.events`（SSE 唯一产出点）在 L4 → R-DEP-1 禁止我们 import 它。

因此用**两条侧信道**（都必须由 W4 接线后才真正生效，已登记 `RELAY.md §给 W4`）：

1. **降级** → `DegradationSink.on_degraded(...)` 回调；默认实现写结构化日志
   （事件**确实产生了**，只是暂时没有 SSE 出口）；
2. **拒答** → 抛 `LlmRefused`，由 W4 捕获后转 `refuse` 终态。
   ⚠️ 不接线时它会落成 `500 INTERNAL` —— **那是错的终态**，本窗口无法单方面解决。

## 三、计量需要的 `task_id` / `tenant_id` / `user_id` 从哪来（**不能放进 payload**）

`cost_ledger` 要写 `task_id`/租户/用户（07 §10.4），但它们是 **PII 或内部标识**，
**绝不能进 `EgressPayload`** —— 那会把"已登记字段"与"可以出站"混为一谈。
端口签名又无处多传一个身份，故用 **`contextvars` 的请求级上下文**
（`set_call_context`，由 API 层在进图前设置）：

- 它**从不出站**，只流向 `budget.settle()` 与日志；
- 它是**请求级**的，并发请求不会串号（模块级变量在这里是事故写法）；
- 未接线时默认 `tenant_id="(unset)"` —— 计量仍写入 sink，但租户级预算退化为
  按 `"(unset)"` 归集。这个降级**可见**（日志会写），不是静默的。

## 四、降级链与 `action_taken`（07 §10.2 逐行落地）

| 触发 | 动作 | `reason` | `action_taken` |
|---|---|---|---|
| pro 超时 / 熔断开路 / 空 content | 换 flash（**并关思考**） | `llm_unavailable` | `switched_to_weak_model` |
| 信号量等待超 20s | 换 flash（"减路"作为**建议**上报） | `llm_concurrency_exceeded` | `reduced_candidates` |
| 预算 100% | **跳过全部模型调用**，直接模板 | `cost_too_high` | `template_only` |
| flash 也不可用 | 模板匹配 | `llm_unavailable` | `template_only` |
| 模板无命中 | **拒答**（`refuse`，非 error） | — | — |

### ⚠️ 三处**不肯撒谎**的地方

1. **"减路"网关做不到**：payload 归调用方所有，网关无法把候选从 N 路减到 1 路。
   `reduced_candidates` 只能作为**建议**经 sink 上报（`detail.advisory=True`），
   真实动作是"换到并发位更多的 flash"。这条不对称写在事件里，而不是用
   `action_taken` 冒充一个已经完成的动作。
2. **模板层当前是空的**：它需要 Gold Query 库（`gold_query` 表，归 W1B/W6），P0 未接线
   → 默认 `NullTemplateProvider` 恒返回 `None`，于是默认路径是 `pro → flash → 拒答`。
   这不是"实现了模板降级"，是"给模板层留了口子并如实说明它空着"。
3. **F2 / F3 不降级**：429 与 5xx 按 07 §14.2 直接成为 `error`，**不去"降级成一份模板答案"** ——
   把一次上游抖动变成一份看起来正常的结论，比报错危险得多。

### `model` 参数的语义（端口签名与路由表张力的收口）

`call(task, payload, model)` 的 `model` 是必填位置参数，但 PRD §12.2 又规定"任务决定模型"。
本实现：`"auto"`（默认）→ 按路由表；显式模型名 → 覆盖（逃生门）；其他 → `LlmUnknownModel`。
**不做"猜最近的模型名"** —— 那正是 N-21 禁止的静默降级。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol

from app.core.contracts import LLMResponse, TokenUsage
from app.core.enums import ActionTaken, DegradedReason
from app.llm.budget import (
    BudgetGuard,
    CostLedgerSink,
    InMemoryCostLedgerSink,
    estimate_for_payload,
)
from app.llm.client import ChatClient
from app.llm.egress_guard import EgressPayload, build_wire_request
from app.llm.errors import (
    DEGRADABLE_LLM_ERRORS,
    LlmError,
    LlmRefused,
    LlmSaturated,
    LlmTemplateMiss,
)
from app.llm.prompts import load_prompt, render_messages
from app.llm.router import (
    MODEL_AUTO,
    ModelKey,
    degrade_target,
    hard_timeout_s,
    max_tokens_for,
    resolve_model_name,
    resolve_route,
)
from app.obs.logging import get_logger

__all__ = [
    "LlmGateway",
    "LlmCallContext",
    "set_call_context",
    "current_call_context",
    "DegradationEvent",
    "DegradationSink",
    "TemplateProvider",
    "NullTemplateProvider",
    "CallRecord",
    "MetricsSink",
    "build_gateway",
    "TEMPLATE_MODEL_ID",
    "TEMPLATE_PROMPT_VERSION",
]

_log = get_logger(__name__)

#: 模板层产出时 `LLMResponse.model` 的取值 —— 必须与真实模型 ID **可区分**，
#: 否则"这份答案来自降级路径"在审计里就看不出来（N-21 的精神）。
TEMPLATE_MODEL_ID: Final[str] = "template"

#: 模板层不走 LLM prompt，但 `prompt_version` 仍然**必须给值**（N-19）：留空会被下游
#: 当成"忘记填"，而给一个显式的 `"template"` 则让"这不是某版 prompt 的产物"可被查询。
TEMPLATE_PROMPT_VERSION: Final[str] = "template"


# ============================================================================
# 请求级上下文（只服务计量与日志，**永不出站**）
# ============================================================================

@dataclass(frozen=True, slots=True)
class LlmCallContext:
    """一次调用的身份上下文。三个字段**全部是内部标识**，任何一个都不得进 payload。"""

    task_id: str = "(unset)"
    tenant_id: str = "(unset)"
    user_id: str = "(unset)"


_UNSET_CONTEXT: Final[LlmCallContext] = LlmCallContext()

#: ⚠️ `default` 用 `None` 而不是 `LlmCallContext()`：ruff 的 B039 会拦"可变默认值"，
#: 而这里真正要表达的是"未设置"（一个哨兵），用 `None` + `or` 兜底语义更准确 ——
#: 顺带避免了"每个请求都构造一个新对象"。
_CALL_CONTEXT: ContextVar[LlmCallContext | None] = ContextVar("llm_call_context", default=None)


def set_call_context(ctx: LlmCallContext) -> None:
    """由 API 层在进图前调用（**接线动作归 W4**）。

    ⚠️ 用 `contextvars` 而不是模块级变量：并发请求必须互不串号，
    而"把身份挂在全局"在异步服务里是经典事故（A 请求的租户记到 B 的账上）。
    """
    _CALL_CONTEXT.set(ctx)


def current_call_context() -> LlmCallContext:
    """取当前请求的身份上下文；未接线时返回哨兵 `(unset)`（**可见**，不静默）。"""
    return _CALL_CONTEXT.get() or _UNSET_CONTEXT


# ============================================================================
# 侧信道 1：降级通知
# ============================================================================

@dataclass(frozen=True, slots=True)
class DegradationEvent:
    """一次降级。字段与 SSE 的 `degraded` 事件（补充契约 C-08）一一对应。"""

    task: str
    reason: DegradedReason
    action_taken: ActionTaken
    detail: Mapping[str, Any]


class DegradationSink(Protocol):
    """降级通知出口。**W4 实现成 `EventEmitterPort.emit(degraded, ...)`。**"""

    def on_degraded(self, event: DegradationEvent) -> None: ...


class _LoggingDegradationSink:
    """默认实现：写结构化日志。**不是空实现** —— 事件真的产生了、真的可被采集，
    缺的只是到 SSE 的那一跳，而那一跳在 L4，本层不能让。"""

    def on_degraded(self, event: DegradationEvent) -> None:
        _log.warning(
            "llm_degraded",
            task=event.task,
            reason=str(event.reason),
            action_taken=str(event.action_taken),
            **{k: v for k, v in event.detail.items() if isinstance(v, (str, int, float, bool))},
        )


# ============================================================================
# 侧信道 2：模板层（P0 空着，口子留好）
# ============================================================================

class TemplateProvider(Protocol):
    """降级链最后一跳的模板来源（实现者将是 Gold Query 库 `gold_query`）。

    返回 `None` = 无命中 → 门面抛 `LlmRefused`
    （07 §10.2：`refuse` 是**产品结论**，不是 error）。
    """

    def lookup(self, task: str, payload: Mapping[str, Any]) -> str | None: ...


class NullTemplateProvider:
    """P0 默认：**恒无命中**。

    🔴 诚实声明：这不是"实现了模板降级"，而是"模板库未接线"。
    它的价值是让降级链的**形状**保持完整（四级），并让"现在只能走到拒答"
    在代码与测试里可读（`test_llm_gateway.py` 有一条断言专门钉住这个默认行为）。
    """

    def lookup(self, task: str, payload: Mapping[str, Any]) -> str | None:
        # 参数刻意保留：它定义的是**接口形状**，实现丢弃参数是"未接线"的正确表现。
        _ = (task, payload)
        return None


# ============================================================================
# 观测：调用记录
# ============================================================================

@dataclass(frozen=True, slots=True)
class CallRecord:
    """一次成功调用的观测记录（含"降级后成功"）。

    它同时是**缓存命中率的埋点载体**：`cache_hit_tokens / input_tokens` 就是 NFR-4.3
    要的命中率（实测上游 `usage.prompt_cache_hit_tokens` 直供，无需自算）。
    """

    task: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cost_cny: Decimal
    latency_ms: int
    reasoning_chars: int
    is_peak: bool
    degraded: bool
    #: 该 task 在 07 §16.1 里的阶段延迟分配（`None` = 07 未给该阶段分配）。
    #: **仅供比对** —— 它不是超时，不参与任何成败判定（见 `router` 模块 docstring）。
    budget_s: float | None
    #: 本次调用是否超过了 `budget_s`。它**替代**了被移除的"预算=硬超时"：
    #: §16.1 的一致性从"强制"改为"可观测"，判定留在上层（推占位符是 W4 的 SSE 责任）。
    over_budget: bool


class MetricsSink(Protocol):
    """指标出口。

    ⚠️ **`app/obs/metrics.py` 目前只有一个 `binding_tau` gauge**（实测），
    没有任何 LLM 计数器/直方图 → 本窗口**不擅自改 W0 的文件**，改为暴露这个注入点
    + 默认打日志。真正的 Prometheus 指标需要 W0 落，需求已写进 `RELAY.md §给 W0`。
    """

    def on_call(self, record: CallRecord) -> None: ...


class _LoggingMetricsSink:
    def on_call(self, record: CallRecord) -> None:
        hit_ratio = (
            round(record.cache_hit_tokens / record.input_tokens, 4) if record.input_tokens else 0.0
        )
        _log.info(
            "llm_call",
            task=record.task,
            model=record.model,
            prompt_version=record.prompt_version,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            cache_hit_tokens=record.cache_hit_tokens,
            cache_hit_ratio=hit_ratio,
            cost_cny=str(record.cost_cny),
            latency_ms=record.latency_ms,
            reasoning_chars=record.reasoning_chars,
            is_peak=record.is_peak,
            degraded=record.degraded,
            budget_s=record.budget_s,
            over_budget=record.over_budget,
        )


# ============================================================================
# 门面
# ============================================================================

class LlmGateway:
    """`LLMPort` 的实现。**全项目唯一的 LLM 出站通道。**

    结构性满足 `LLMPort`（`call` 为 async、`estimate_cost` 同步返回 `Decimal`）——
    由 `tests/unit/test_llm_gateway.py::test_gateway_satisfies_llm_port` 用
    `isinstance(..., LLMPort)` 钉住（`LLMPort` 是 `runtime_checkable`）。
    """

    def __init__(
        self,
        *,
        client: ChatClient,
        model_names: Mapping[ModelKey, str],
        budget: BudgetGuard,
        now_fn: Callable[[], datetime],
        degradation: DegradationSink | None = None,
        templates: TemplateProvider | None = None,
        metrics: MetricsSink | None = None,
    ) -> None:
        self._client = client
        self._model_names = dict(model_names)
        self._budget = budget
        self._degradation = degradation or _LoggingDegradationSink()
        self._templates = templates or NullTemplateProvider()
        self._metrics = metrics or _LoggingMetricsSink()
        self._now = now_fn

    # -- 端口 ---------------------------------------------------------------

    async def call(
        self, task: str, payload: Mapping[str, Any], model: str = MODEL_AUTO
    ) -> LLMResponse:
        """执行一次 LLM 调用（含降级链）。`model="auto"` 表示按路由表决定。

        异常语义（对齐 07 §14.2 的 F1/F2/F3）：

        - **F2** 429 退避耗尽 → `LlmConcurrencyExceeded`（**error**，不降级）
        - **F3** 5xx 重试耗尽 → `LlmUpstreamError`（**error**，不降级）
        - **F1** 超时 / 熔断 / 空 content → **降级**；链走完仍无产出 → `LlmRefused`
        - 未知 `task` / 非法 `model` / 出站白名单违规 → 直接抛，**不降级**
          （前两者是契约错误，后者是安全事件 —— 都不是"上游不行"，降级会掩盖它们）
        """
        route = resolve_route(task)
        model_name = resolve_model_name(route, model, self._model_names)
        #: `model` 的语义（见 `router` 模块 docstring）：`"auto"` → 按路由表；
        #: 显式模型名 → **覆盖**（逃生门）。覆盖必须**真的生效在出站请求上**，
        #: 否则调用方以为换了模型、账单和延迟却按另一个模型走 —— 那就是 N-21 禁止的静默行为
        #: （只把覆盖用于成本估算、出站却按路由表走，是同一类缺陷的隐蔽版本）。
        override = model != MODEL_AUTO
        entry_key = (
            next((k for k, name in self._model_names.items() if name == model_name), route.model_key)
            if override
            else route.model_key
        )
        ctx = current_call_context()
        now = self._now()

        # ① 出站白名单（fail-closed；安全事件不降级）
        egress = EgressPayload.from_mapping(payload)

        # ② prompt 渲染（资产缺失/版本不匹配同样不降级：那是代码问题）
        asset = load_prompt(task)
        messages, prompt_version = render_messages(asset, egress)
        system_text, user_text = messages[0]["content"], messages[1]["content"]

        # ③ 预算 pre-flight（含 80% 减路 / 100% 熔断）
        estimated = estimate_for_payload(
            self._budget, {"text": f"{system_text}\n{user_text}", "task": task}, model=model_name
        )
        decision = self._budget.preflight(tenant_id=ctx.tenant_id, now=now, estimated_cny=estimated)
        if not decision.allowed:
            self._emit(
                task,
                DegradedReason.COST_TOO_HIGH,
                ActionTaken.TEMPLATE_ONLY,
                {
                    "blocked_by": decision.blocked_by,
                    "ratio": round(decision.ratio, 4),
                    "estimated_cny": str(estimated),
                },
            )
            return self._template_or_refuse(task, payload)
        if decision.force_single_path:
            self._emit(
                task,
                DegradedReason.COST_TOO_HIGH,
                ActionTaken.REDUCED_CANDIDATES,
                {
                    "ratio": round(decision.ratio, 4),
                    # 🔴 不撒谎：网关无法替调用方把候选从 N 路减到 1 路。
                    "advisory": True,
                    "hint": "调用方应把候选路数降为 1（07 §10.4 前置估算）",
                },
            )

        # ④ 降级链的模型段：入口档 → （强档时）弱档。
        #    ⚠️ 入口档取自 `entry_key`（**含 model 覆盖**），不是 `route.model_key` ——
        #    见上面 `override` 的说明。降级链本身仍按 07 §10.2 从该档继续往下。
        attempts: list[ModelKey] = [entry_key]
        weaker = degrade_target(route, entry_key)
        if weaker is not None:
            attempts.append(weaker)

        degraded_so_far = False
        for idx, model_key in enumerate(attempts):
            wire = build_wire_request(
                egress,
                model=self._model_names[model_key],
                system_text=system_text,
                user_text=user_text,
                max_tokens=max_tokens_for(route),
                temperature=route.temperature,
                # 07 §10.2 的链写明 "v4-pro（思考） → flash（**非思考**）"：
                # 降到弱档时必须一并关思考，否则既拿不到质量也拿不到速度。
                thinking=route.thinking and model_key is ModelKey.STRONG,
                json_output=route.json_output,
            )
            try:
                completion = await self._client.invoke(
                    model=self._model_names[model_key],
                    wire_body=wire,
                    # 🔴 传输 deadline **只按模型档取**（07 §10.2）。绝不能传 `route.budget_s` ——
                    #    那是 §16.1 的端到端 P95 分配，不是超时上限；传它会 100% 掐死
                    #    所有"真机延迟 > 分配值"的任务（实测 0/15，见 router 模块 docstring）。
                    deadline_s=hard_timeout_s(model_key),
                )
            except LlmError as exc:
                if not isinstance(exc, DEGRADABLE_LLM_ERRORS):
                    raise  # F2/F3 与契约错误：不降级
                degraded_so_far = True
                is_last_model_attempt = idx == len(attempts) - 1
                reason = self._reason_for(exc)
                if is_last_model_attempt:
                    action = ActionTaken.TEMPLATE_ONLY
                elif reason is DegradedReason.LLM_CONCURRENCY_EXCEEDED:
                    action = ActionTaken.REDUCED_CANDIDATES
                else:
                    action = ActionTaken.SWITCHED_TO_WEAK_MODEL
                self._emit(
                    task,
                    reason,
                    action,
                    {
                        "from_model": self._model_names[model_key],
                        "error": type(exc).__name__,
                        "advisory": action is ActionTaken.REDUCED_CANDIDATES,
                        # 覆盖是逃生门，但必须**可审计**：不记它就无法回答
                        # "这次为什么走了这个档"。False 时也写，便于按字段聚合。
                        "model_override": override,
                    },
                )
                continue

            # ⑤ 成功：结算 + 埋点
            entry = self._budget.settle(
                task_id=ctx.task_id,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                model=completion.model,
                usage=completion.tokens,
                now=now,
            )
            self._metrics.on_call(
                CallRecord(
                    task=task,
                    model=completion.model,
                    prompt_version=prompt_version,
                    input_tokens=completion.tokens.input,
                    output_tokens=completion.tokens.output,
                    cache_hit_tokens=completion.tokens.cache_hit,
                    cost_cny=entry.cost_cny,
                    latency_ms=completion.latency_ms,
                    reasoning_chars=completion.reasoning_chars,
                    is_peak=entry.is_peak,
                    degraded=degraded_so_far,
                    budget_s=route.budget_s,
                    # 单位换算：budget_s 是秒，latency_ms 是毫秒 —— 比错过就会静默失真。
                    over_budget=(
                        route.budget_s is not None
                        and completion.latency_ms > route.budget_s * 1000
                    ),
                )
            )
            return LLMResponse(
                text=completion.text,
                model=completion.model,
                prompt_version=prompt_version,
                tokens=completion.tokens,
                cost_cny=entry.cost_cny,
            )

        # ⑥ 模板层 → 拒答
        _log.info("llm_falling_back_to_template", task=task, prompt_version=prompt_version)
        try:
            return self._template_or_refuse(task, payload)
        except LlmTemplateMiss as exc:  # pragma: no cover - 当前 provider 不改抛
            raise LlmRefused(str(exc)) from exc

    def estimate_cost(self, payload: Mapping[str, Any]) -> Decimal:
        """pre-flight 成本估算（**高峰价上界**，TCO 纪律）。

        payload 约定见 `budget.estimate_for_payload` 的 docstring
        （端口签名只有 `Mapping`、没给结构 —— 本窗口在此定义并登记到 RELAY）。
        """
        task = payload.get("task")
        model_name = self._model_names[ModelKey.FAST]
        if isinstance(task, str):
            try:
                route = resolve_route(task)
            except LlmError:
                route = None
            if route is not None:
                model_name = self._model_names[route.model_key]
        return estimate_for_payload(self._budget, payload, model=model_name)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- 内部 ---------------------------------------------------------------

    def _emit(
        self,
        task: str,
        reason: DegradedReason,
        action: ActionTaken,
        detail: Mapping[str, Any],
    ) -> None:
        self._degradation.on_degraded(
            DegradationEvent(task=task, reason=reason, action_taken=action, detail=detail)
        )

    def _template_or_refuse(self, task: str, payload: Mapping[str, Any]) -> LLMResponse:
        """模板层：有命中 → 返回（`model="template"`）；无命中 → `LlmRefused`。"""
        text = self._templates.lookup(task, payload)
        if text is None:
            raise LlmRefused(
                "所有模型档与模板层均不可用 —— 无法给出答案",
                detail={"task": task},
            )
        # 模板命中也要发 degraded（N-21：不得静默降级）
        self._emit(
            task,
            DegradedReason.LLM_UNAVAILABLE,
            ActionTaken.TEMPLATE_ONLY,
            {"template_hit": True},
        )
        return LLMResponse(
            text=text,
            model=TEMPLATE_MODEL_ID,
            prompt_version=TEMPLATE_PROMPT_VERSION,
            tokens=TokenUsage(),  # 模板层没烧 token，**如实为 0**
            cost_cny=Decimal(0),
        )

    @staticmethod
    def _reason_for(exc: LlmError) -> DegradedReason:
        """异常 → `DegradedReason`（C-08 的 8 值之一）。

        ⚠️ `DegradedReason` 里**没有** `template_only` —— 那是 `ActionTaken` 的取值。
        两者在本项目里是**不对称**的两组词（reason = "为什么"，action = "做了什么"），
        混用会让前端与审计双方都读错。
        """
        if isinstance(exc, LlmSaturated):
            return DegradedReason.LLM_CONCURRENCY_EXCEEDED
        return DegradedReason.LLM_UNAVAILABLE


# ============================================================================
# 便捷构造（W4 在 lifespan 里接线的入口）
# ============================================================================

def build_gateway(
    settings: Any,
    *,
    ledger: CostLedgerSink | None = None,
    degradation: DegradationSink | None = None,
    templates: TemplateProvider | None = None,
    metrics: MetricsSink | None = None,
    now_fn: Callable[[], datetime] | None = None,
    client: ChatClient | None = None,
) -> LlmGateway:
    """用 `Settings` 装配一个网关（`client` 可注入 → 测试传 `respx` 拦截）。

    ⚠️ **本函数不读 `.env`、不注册到 `app.main`** —— 接线（lifespan 装配与优雅关闭）
    归 W4，本窗口不越界改别人的文件。
    """
    the_client = client or ChatClient(
        base_url=settings.DEEPSEEK_BASE_URL,
        api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
        model_names={"fast": settings.LLM_MODEL_FAST, "strong": settings.LLM_MODEL_STRONG},
        max_concurrency=settings.LLM_MAX_CONCURRENCY,
        semaphore_flash=settings.LLM_SEMAPHORE_FLASH,
        semaphore_pro=settings.LLM_SEMAPHORE_PRO,
        max_retries=settings.LLM_MAX_RETRIES,
        circuit_fails=settings.LLM_CIRCUIT_FAILS,
        circuit_open_s=settings.LLM_CIRCUIT_OPEN_S,
    )
    budget = BudgetGuard(
        global_daily_budget_cny=settings.DAILY_BUDGET_CNY,
        alert_ratio=settings.BUDGET_ALERT_RATIO,
        sink=ledger if ledger is not None else InMemoryCostLedgerSink(),
    )
    return LlmGateway(
        client=the_client,
        model_names={
            ModelKey.FAST: settings.LLM_MODEL_FAST,
            ModelKey.STRONG: settings.LLM_MODEL_STRONG,
        },
        budget=budget,
        now_fn=now_fn or (lambda: datetime.now(UTC)),
        degradation=degradation,
        templates=templates,
        metrics=metrics,
    )
