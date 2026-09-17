"""LLM 网关内部异常 —— `app.llm` 独占，不落 `app/core/errors.py`。

归属窗口：W3A｜依据：07 §10.2 / §14.2 的 **F1 / F2 / F3** 三行。

## 为什么异常落在这里而不是 `core/errors.py`（Q6 裁定）

`core/errors.py` 只有 7 个**跨层**类（基类 + ConfigError / SemanticBundleError /
SessionLockConflict / AuditWriteFailed / DependencyUnavailableError / ContractViolationError），
它们是"任何层都可能抛"的公共词汇。而本文件的 8 个类**全部只在 `client.py` 内部
产生、只在 `__init__.py` 的降级链里被消费** —— 把它们放进 L0 的 `core/` 等于让 L0
认识 L1 的运行细节。`CommerceQLError` 本身支持子类化（`default_code` 是类属性），
所以在自己的目录里建子类是**合法且更干净**的。

## ⚠️ `default_code` 只写"成员名字符串"

`CommerceQLError` 的约定（见其 docstring）：`default_code` 是**领域侧建议码**，
最终 HTTP 状态与 `retryable` **一律由** `app/api/errors.py` 查 `ERROR_HTTP_STATUS` /
`ERROR_RETRY_TIER` 决定。本文件**不碰** HTTP 语义 —— 那是 W4 的事。

## 🔴 契约缺口（必须让 W4 知道，已登记 `reports/w3a/RELAY.md`）

07 §10.2 要求"每一级降级必须发 `degraded` 事件"，且"模板无命中 = `refuse`（**不是 error**）"。
但端口被冻结成这样：

    async def call(task, payload, model) -> LLMResponse

`LLMResponse` 只有 `text / model / prompt_version / tokens / cost_cny` —— **既装不下
`degraded{reason, action_taken}`，也装不下 `refuse` 这个产品终态**。而 `app.llm` 在 **L1**，
`app.graph.events`（SSE 唯一产出点）在 **L4** → R-DEP-1 禁止 import。

因此本窗口的落地方式是**两条侧信道**，都必须在 W4 接线后才真正生效：

1. **降级通知** → `__init__.py` 的 `DegradationSink` 回调（默认只写结构化日志），
   由 W4 接成 `EventEmitterPort.emit(degraded, ...)`；
2. **拒答** → 抛本文件的 `LlmRefused`，由 W4 捕获后转 `refuse` 终态。

⚠️ **`LlmRefused` 被直接送到 `app/api/errors.py` 会被兜底成 `INTERNAL`（500）** ——
那是**错误**的终态（07 §14.2 F1 明确 refuse 不是 error）。W4 必须**先**捕获它。
本文件把它写成独立类而不是复用 `LlmTimeout`，就是为了让这条 `except` 能精确命中。
"""

from __future__ import annotations

from typing import Any

from app.core.errors import CommerceQLError

__all__ = [
    "LlmError",
    "LlmUnknownTask",
    "LlmUnknownModel",
    "LlmEgressViolation",
    "LlmPromptError",
    "LlmUpstreamError",
    "LlmConcurrencyExceeded",
    "LlmTimeout",
    "LlmCircuitOpen",
    "LlmSaturated",
    "LlmEmptyContent",
    "LlmBudgetExceeded",
    "LlmTemplateMiss",
    "LlmRefused",
    "DEGRADABLE_LLM_ERRORS",
]


class LlmError(CommerceQLError):
    """本文件全部异常的基类。**捕获范围用它，不要用 `Exception`。**"""

    default_code: str | None = "INTERNAL"


class LlmUnknownTask(LlmError):
    """`task` 不在 `router.LlmTask` 取值集内。

    🔴 **必须 fail-fast，不得回退默认模型** —— 猜一个模型 = 静默降级
    （N-21 的精神：降级必须可见）。契约违规，等同于上游窗口改了契约却没同步。
    """

    default_code = "INTERNAL"


class LlmUnknownModel(LlmError):
    """`call(..., model=...)` 传了既不是 `"auto"` 也不在配置模型名之列的取值。

    同样 fail-fast：`model` 参数是**覆盖路由表**的逃生门，不是一个自由字符串。
    """

    default_code = "INTERNAL"


class LlmEgressViolation(LlmError):
    """出站白名单被破坏（N-12）—— payload 含未登记字段，或值里夹带明细数据。

    🔴 这是**安全事件**，不是普通参数错误：它意味着调用方试图把结果集/明细/
    库内文本送出站。`detail` 只记**键名与字段名**，**绝不记值**（否则错误信息本身
    就成了泄露通道）。
    """

    default_code = "INTERNAL"


class LlmPromptError(LlmError):
    """prompt 资产加载/渲染失败（文件缺失、变量未提供、前缀被请求级变量污染）。

    07 §10.3 的前四条硬规则是**资产契约**，违反它 = prompt 缓存命中率归零，
    属于"静默变慢变贵"，因此在**构造期**就炸掉，而不是等命中率指标掉下来。
    """

    default_code = "INTERNAL"


class LlmUpstreamError(LlmError):
    """**F3**：上游 5xx（重试耗尽）。→ `error` + `LLM_UPSTREAM_ERROR`（✅ 可重试，`Retry-After`=30）。

    ⚠️ **`detail` 不得含上游自由文本**：只放 `status` 与上游的结构化
    `error.type`/`error.code`。上游 400 的 message 里可能回显我们的 prompt 片段，
    把它带进日志或响应等于自建一条出站回流通道（N-12 的反向）。
    """

    default_code = "LLM_UPSTREAM_ERROR"


class LlmConcurrencyExceeded(LlmError):
    """**F2**：上游 429（退避耗尽）。→ `error` + `LLM_CONCURRENCY_EXCEEDED`（✅，`Retry-After`=5）。

    ⚠️ 与 `LlmSaturated` **不是**一回事：本类=上游拒绝（我们并发超了它的限），
    `LlmSaturated`=我们自己的信号量没等到位（还没发出请求）。前者是 `error`，后者是 `degraded`。
    """

    default_code = "LLM_CONCURRENCY_EXCEEDED"


class LlmTimeout(LlmError):
    """**F1**：单次调用超时 → **可降级**（`degraded` + `switched_to_weak_model`）。

    ⚠️ 超时**不是** `EXEC_TIMEOUT` 那类"⭕ 需改请求"的码：本类在网关内部被降级链吃掉，
    正常流量里不该冒到 API 层。冒到 API 层 = 降级链也走完了，此时应抛 `LlmRefused`。
    """

    default_code = "INTERNAL"


class LlmCircuitOpen(LlmError):
    """**F1**：熔断已开路（连续 5 次失败 → 开路 30s）→ **不发请求直接降级**。

    ⚠️ 开路期间"根本不发请求"，这正是 `LLM_UPSTREAM_ERROR` 的 `Retry-After` 必须
    **不得小于开路时长**（30s）的机制来源（07 §14.4.1）。
    """

    default_code = "INTERNAL"


class LlmSaturated(LlmError):
    """自己的信号量等待超过 20s（07 §10.1 "排队"行）→ **降级**，不是 error。

    07 原文："信号量等待上限 20s；超时 → `degraded(llm_concurrency_exceeded, reduced_candidates)`
    或降级到单路"。本类即那条路径的触发点。

    ⚠️ **诚实的边界**：网关**无法**真的把候选路数减下来 —— payload 归调用方所有，
    `reduced_candidates` 只能作为**建议**通过 `DegradationSink` 传给编排层。
    网关能做的实物动作是**换到弱模型**（flash 的 8 个并发位远多于 pro 的 2 个，
    在 pro 饱和时几乎必然可用）。这条不对称必须写清，否则 `action_taken` 就是在撒谎。
    """

    default_code = "INTERNAL"


class LlmEmptyContent(LlmError):
    """响应 200 但 `content` 为空。

    🔴 **这是本项目实测踩到的真实故障模式**（2026-09-17，W3A）：
    思考模式下 `max_tokens` 会被 `reasoning_tokens` 吃掉 —— 实测 `max_tokens=32`
    时 **32 个 token 全进 reasoning，`content=''`，而上游状态码是 200、不报任何错**。
    若不显式拦截，调用方会拿到"空 SQL / 空结论"并当成合法结果继续往下走。

    处理：**走降级链**（reason=`llm_unavailable`），并按 `thinking` 位重新计预算。
    """

    default_code = "INTERNAL"


class LlmBudgetExceeded(LlmError):
    """预算 100% 硬熔断（NFR-4.2）→ 新请求走**模板 + 降级**，`reason=cost_too_high`。

    ⚠️ 07 §10.4 的原话是"熔断后新请求走模板 + 降级路径，并在 `meta` 标注" ——
    所以本类的归宿是**降级链**（把 `action_taken=template_only` 送进 sink），
    **不是** API 层的 5xx。
    """

    default_code = "INTERNAL"


class LlmTemplateMiss(LlmError):
    """降级链最后一跳（模板）无命中 —— 内部信号，**不会被抛出到调用方**。

    由 `__init__.py` 捕获后改抛 `LlmRefused`；单独存在是为了让"模板层没有库"
    这件事在日志里可归因（vs. "模板层有库但这次没命中"）。
    """

    default_code = "INTERNAL"


class LlmRefused(LlmError):
    """降级链走完仍无产出 → **产品终态 `refuse`，不是 error**（07 §10.2 表格最后一行）。

    🔴🔴 **W4 必读**：`refuse` / `error` / `clarify` 三者互斥（07 §14.3 约束 2），
    且 `refuse` **不给 `data`**（约束 5）。若本异常落到 `app/api/errors.py`，
    它会因 `default_code="INTERNAL"` 被兜底成 `500 INTERNAL` ——
    **那是错的终态**。W4 的编排层必须**先**捕获本类，转 `refuse`。
    接线位置与检出方式见 `reports/w3a/RELAY.md §给 W4`。
    """

    #: ⚠️ 故意留 `None`：它**不是**错误码，落 `INTERNAL` 只是"没接线时的显式症状"。
    default_code = None

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message, detail=detail)


#: 07 §10.2 的降级链**只吃这几类**。F2（429）/F3（5xx）**刻意不在其中** ——
#: 它们按 F2/F3 两行直接成为 `error`，不去"降级成模板答案"（那会把一次上游抖动
#: 变成一份看起来正常的模板结论，比报错更危险）。
DEGRADABLE_LLM_ERRORS: tuple[type[LlmError], ...] = (
    LlmTimeout,
    LlmCircuitOpen,
    LlmSaturated,
    LlmEmptyContent,
    LlmBudgetExceeded,
    LlmTemplateMiss,
)
