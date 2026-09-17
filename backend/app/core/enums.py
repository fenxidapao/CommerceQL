"""取值集唯一来源（单一真相文件 #1 / 3）。

归属窗口：W0（docs/08 §4.1）。任何窗口需要新增/修改取值，走 docs/08 §4.3 的
四步共享文件变更流程；**禁止在本文件之外另定义第二份取值集**
（07 §4.1 禁令三：取值集只能有一处定义 —— `stage` 曾出现非法值 `data_ready` / `complete`）。

契约纪律（本文件必须始终满足）：
1. 只放「取值集 + 纯查找表 + 自检函数」，**零业务逻辑**；
2. **不得 import 任何 `app.*` 模块**（本文件在 L0 最底层，import 谁都是依赖倒挂）；
3. 一律用 `enum.StrEnum`（Python 3.13）→ JSON / SQL / SSE 帧直接序列化，无需自定义 encoder；
4. 每项标注**权威来源章节号**；权威优先级：附录 A > PRD > 06 > 07 TDD。

回填请求的销账状态（07 v0.6 已**全部裁定并落笔**，本文件据此修正过一轮）：

| 请求 | 裁定 | 对本文件的影响 |
|---|---|---|
| **U-14** | 缓存键租户归属。**根因不在键**：`gold_query` 表缺 `tenant_id` 列（新增 §11.7） | `cache/keys.py`：`sem:fs` **加**租户、`emb:` **去掉**租户（唯一豁免）、`evt:` 保持无租户（规则 1 不适用）；本文件新增 `GoldQueryTier` |
| **U-15** | ✅ 采纳 7 值，**并指出请求侧是另一个枚举**（`chart_preference` 8 值，含 `auto`/`none`）→ 二者不得合并 | `ChartType`(7) 与 `ChartPreference`(8) 并列存在，且自检断言两者的差集非空 |
| **U-16** | ✅ 采纳 20 条，**并补一层我未提的区分**：**R17–R20 是告警级不是阻断级**，断言方式相反 | 新增 `AstRule`(20) + `AstRuleSeverity`(3)；`AST_WARNING_RULES` 显式落位，"命中即拒绝"会被自检拦下 |
| **U-17** | ✅ **推翻我原来的实现**：`⭕` **不得**带 `Retry-After`（那是假承诺），必须给 `suggestions[]` | `RETRY_AFTER_REQUIRED` 改为**只对 ✅**；新增 `RETRY_AFTER_DEFAULT_S` / `DEFAULT_SUGGESTIONS` |
| **U-18** | ✅ 审计写入落 `obs/audit.py`（我按 §3.2 建文件是对的）；**新增约束**：`obs/` 下除 `audit.py` 外禁止依赖 DB | `.importlinter` 新增 `r-dep-3-obs-except-audit-no-repo`；`tests/contract` 新增"audit.py 无 UPDATE/DELETE"静态断言 |
| **U-19** | ✅ τ 校验改 env-gate（`prod` fail-closed / 非 prod 放行但**不得隐瞒**） | `config.py` 保留 env-gate，并补**启动 WARN + 指标 gauge**；钉死机制 = `test_tau_gate_is_prod_only_by_design` 双断言 |

本文件仍**独立于 07**保留了一处冲突（**新登记 U-21**）：`INTERNAL` 的档位在附录 A §A.11（`⭕`）
与 07 §14.4（`✅`）之间不一致 → 按契约优先级取附录 A，理由与代价写在 `ERROR_RETRY_TIER` 上方。
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    # ---- 编排与事件 ----
    "Stage", "SseEvent", "SseTerminal", "SSE_STAGE_EMISSION_POINTS", "SSE_TERMINAL_EVENTS",
    # ---- 错误 ----
    "ErrorCode", "RetryableTier", "ERROR_HTTP_STATUS", "ERROR_RETRY_TIER",
    "RETRY_AFTER_REQUIRED", "RETRYABLE_BOOLEAN", "REQUIRES_SUGGESTIONS",
    "RETRY_AFTER_DEFAULT_S", "DEFAULT_SUGGESTIONS",
    "SESSION_CONFLICT_RETRY_AFTER_S",
    # ---- 结果与终态 ----
    "Outcome", "TaskStatus", "RefuseReason", "ClarifyReason",
    "DegradedReason", "ActionTaken", "RetrievalMode",
    # ---- 语义与绑定 ----
    "BindingState", "BindingLayer", "GoldQueryTier",
    # ---- 呈现 ----
    "ChartType", "ChartPreference", "CitationType",
    # ---- 权限与闸门 ----
    "Role", "ScopeLevel", "GateNo", "GateDecision", "LimitType",
    "AstRule", "AstRuleSeverity", "AST_RULE_SEVERITY",
    "AST_WARNING_RULES", "AST_BLOCKING_RULES", "AST_REWRITE_RULES",
    # ---- 限流与计量 ----
    "RateLimitBucket", "RATE_LIMIT_BUCKET_RETRY_AFTER_S",
    "LatencyKey", "TokenKey",
    # ---- 健康检查（附录 A §A.8）----
    "HealthStatus", "DependencyKind", "Dependency",
    "DEPENDENCY_KIND", "READINESS_DEPENDENCIES", "DEGRADABLE_DEPENDENCIES",
    # ---- 契约自检 ----
    "CONTRACT_COUNTS", "validate_contract_counts",
]


# ============================================================================
# 一、编排与 SSE 事件
# ============================================================================

class Stage(StrEnum):
    """SSE `stage` 事件的取值集。

    **恰好 6 个**（07 §14.3 约束 8 / §5.6 实现约束 1）。
    注意：`data_ready` / `complete` 曾作为非法 stage 出现 —— 它们是**事件名**，不是 stage。
    来源：07 §5.6 / §14.3。
    """

    INTENT = "intent"
    SCHEMA_LINKING = "schema_linking"
    PLAN_READY = "plan_ready"
    SQL_READY = "sql_ready"
    GATE_PASSED = "gate_passed"
    EXECUTING = "executing"


class SseEvent(StrEnum):
    """SSE 事件**类型**取值集 —— 12 个。

    ⚠️ 与「17」的关系必须分清（否则 W4 的契约测试口径会打架）：
    - 事件**类型** = 12 个（本枚举）；
    - 事件**发射点** = 17 个（见 `SSE_STAGE_EMISSION_POINTS`，因 `stage` 要发 6 次）；
    - docs/08 §3.6 所写的「17 个事件」= 17 个**发射点**。
    来源：附录 A §A.1.2 / §A.1.3；07 §5.6。
    """

    ACK = "ack"
    STAGE = "stage"
    DATA = "data"
    CHART = "chart"
    INSIGHT = "insight"
    META = "meta"
    DEGRADED = "degraded"
    COMPLETE = "complete"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class SseTerminal(StrEnum):
    """`data.terminal` 的两种取值。

    前端**唯一判据**是 `data.terminal === true`，不得按事件类型维护白名单（附录 A §A.1.4）。
    本枚举用于后端自检，不要求出现在 payload 中（payload 用布尔）。
    """

    TRUE = "true"
    FALSE = "false"


#: SSE 事件发射点（**顺序即契约**）。来源：07 §5.6。
#: 元素 = (事件类型, stage 值 | None)。共 17 项 —— 与 08 §3.6「17 个事件」对齐。
SSE_STAGE_EMISSION_POINTS: Final[tuple[tuple[SseEvent, Stage | None], ...]] = (
    (SseEvent.ACK, None),
    (SseEvent.STAGE, Stage.INTENT),
    (SseEvent.STAGE, Stage.SCHEMA_LINKING),
    (SseEvent.STAGE, Stage.PLAN_READY),
    (SseEvent.STAGE, Stage.SQL_READY),
    (SseEvent.STAGE, Stage.GATE_PASSED),
    (SseEvent.STAGE, Stage.EXECUTING),
    (SseEvent.DATA, None),
    (SseEvent.CHART, None),
    (SseEvent.INSIGHT, None),
    (SseEvent.META, None),
    (SseEvent.DEGRADED, None),
    (SseEvent.COMPLETE, None),
    (SseEvent.CLARIFY, None),
    (SseEvent.REFUSE, None),
    (SseEvent.ERROR, None),
    (SseEvent.HEARTBEAT, None),
)

#: 终止事件（`terminal: true`）—— **恰好 4 个，且两两互斥**。
#: 每条流有且仅有 1 个终止事件（N-08 / 07 §14.3 约束 1–2）。
#: `degraded` **不在其中**（它是"发生了降级"的通知，不是"这一轮结束了"）。
SSE_TERMINAL_EVENTS: Final[frozenset[SseEvent]] = frozenset(
    {SseEvent.COMPLETE, SseEvent.CLARIFY, SseEvent.REFUSE, SseEvent.ERROR}
)


# ============================================================================
# 二、错误码（**28 个，唯一来源 = 附录 A §A.11**）
# ============================================================================

class ErrorCode(StrEnum):
    """错误码全集 —— **28 个**（附录 A v1.5 §A.11）。

    ⚠️ PRD §10.3 的表格是**节选**，以附录 A §A.11 为准（07 §14.1）。
    新增错误码必须同步登记 §A.11 + 07 §4.2 断言集，**未登记即构建失败**。
    """

    # --- 成功 ---
    OK = "OK"

    # --- 400 / 401 / 403 ---
    INVALID_REQUEST = "INVALID_REQUEST"
    AUTH_FAILED = "AUTH_FAILED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    FORBIDDEN_SCOPE = "FORBIDDEN_SCOPE"
    PII_BLOCKED = "PII_BLOCKED"

    # --- 404 ---
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"

    # --- 409（**会话串行冲突走这里，不是 429**）---
    AMBIGUOUS_QUERY = "AMBIGUOUS_QUERY"
    TASK_NOT_CANCELLABLE = "TASK_NOT_CANCELLABLE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    SESSION_CONFLICT = "SESSION_CONFLICT"

    # --- 410 / 422 ---
    CLARIFY_EXPIRED = "CLARIFY_EXPIRED"
    CLARIFY_INVALID_OPTION = "CLARIFY_INVALID_OPTION"
    GATE_AST_REJECTED = "GATE_AST_REJECTED"
    GATE_POLICY_REJECTED = "GATE_POLICY_REJECTED"
    COST_TOO_HIGH = "COST_TOO_HIGH"
    EXEC_RESOURCE_EXCEEDED = "EXEC_RESOURCE_EXCEEDED"
    NO_DATA_ASSET = "NO_DATA_ASSET"
    SQL_SYNTAX_ERROR = "SQL_SYNTAX_ERROR"

    # --- 429 / 5xx ---
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"
    LLM_UPSTREAM_ERROR = "LLM_UPSTREAM_ERROR"
    LLM_CONCURRENCY_EXCEEDED = "LLM_CONCURRENCY_EXCEEDED"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    EXEC_TIMEOUT = "EXEC_TIMEOUT"


class RetryableTier(StrEnum):
    """可重试性的三级记法（附录 A §A.11 的 `❌ / ⭕ / ✅`，07 v0.6 §14.4）。

    **与 `Retry-After` / `suggestions[]` 的绑定是硬约定（C-09）—— v0.6 起是"三级不对称"：**

    | 级别 | `Retry-After` | `suggestions[]` | 含义 |
    |---|---|---|---|
    | `YES`(✅) | **必须带** | — | 环境瞬时问题，**原样重发**会有不同结果 |
    | `REPHRASE`(⭕) | **不得带** | **必须给** | 原样重试**必然再次失败**，必须先改请求 |
    | `NONE`(❌) | **不得带** | — | 不可重试（重新登录 / 换个问法 / 复制 trace_id） |

    ⚠️ **本类最初把 `REPHRASE` 写成"必须带 `Retry-After`" —— 那是个假承诺，已被 U-17 推翻。**
    `Retry-After` 的字面含义是"**等这么久，把同一个请求再发一次**会有不同结果"；
    而 `⭕` 的定义恰恰是"原样重试必然失败"。两者并列 = **用一个倒计时把用户骗进必然失败的重试**，
    且前端会把它渲染成"稍后自动重试"（06 §4.12 现有映射）—— 行为完全错。
    `⭕` 真正该给的是"**怎么改**"（收窄时间 / 加过滤 / 换问法），即 `suggestions[]`。
    """

    NONE = "none"          # ❌
    REPHRASE = "rephrase"  # ⭕ 需改变请求后才可重试
    YES = "yes"            # ✅


#: 错误码 → HTTP 状态码（附录 A §A.11）。`OK` 为 200。
ERROR_HTTP_STATUS: Final[Mapping[ErrorCode, int]] = MappingProxyType(
    {
        ErrorCode.OK: 200,
        ErrorCode.INVALID_REQUEST: 400,
        ErrorCode.AUTH_FAILED: 401,
        ErrorCode.TOKEN_REVOKED: 401,
        ErrorCode.FORBIDDEN_SCOPE: 403,
        ErrorCode.PII_BLOCKED: 403,
        ErrorCode.TASK_NOT_FOUND: 404,
        ErrorCode.SESSION_NOT_FOUND: 404,
        ErrorCode.RUN_NOT_FOUND: 404,
        ErrorCode.DATASET_NOT_FOUND: 404,
        ErrorCode.AMBIGUOUS_QUERY: 409,
        ErrorCode.TASK_NOT_CANCELLABLE: 409,
        ErrorCode.IDEMPOTENCY_CONFLICT: 409,
        ErrorCode.SESSION_CONFLICT: 409,
        ErrorCode.CLARIFY_EXPIRED: 410,
        ErrorCode.CLARIFY_INVALID_OPTION: 422,
        ErrorCode.GATE_AST_REJECTED: 422,
        ErrorCode.GATE_POLICY_REJECTED: 422,
        ErrorCode.COST_TOO_HIGH: 422,
        ErrorCode.EXEC_RESOURCE_EXCEEDED: 422,
        ErrorCode.NO_DATA_ASSET: 422,
        ErrorCode.SQL_SYNTAX_ERROR: 422,
        ErrorCode.RATE_LIMITED: 429,
        ErrorCode.INTERNAL: 500,
        ErrorCode.LLM_UPSTREAM_ERROR: 502,
        ErrorCode.LLM_CONCURRENCY_EXCEEDED: 502,
        ErrorCode.DB_UNAVAILABLE: 503,
        ErrorCode.EXEC_TIMEOUT: 504,
    }
)

#: 错误码 → 可重试级别（07 v0.6 §14.4 的三级表）。**必须与 HTTP 状态码表等长（= 28）**。
ERROR_RETRY_TIER: Final[Mapping[ErrorCode, RetryableTier]] = MappingProxyType(
    {
        # ✅ 环境瞬时问题，原样重试有意义
        ErrorCode.RATE_LIMITED: RetryableTier.YES,
        ErrorCode.SESSION_CONFLICT: RetryableTier.YES,
        ErrorCode.LLM_CONCURRENCY_EXCEEDED: RetryableTier.YES,
        ErrorCode.LLM_UPSTREAM_ERROR: RetryableTier.YES,
        ErrorCode.DB_UNAVAILABLE: RetryableTier.YES,
        # ⭕ 原样重试必然再失败 —— 必须同时告诉用户"怎么改"
        ErrorCode.COST_TOO_HIGH: RetryableTier.REPHRASE,
        ErrorCode.EXEC_RESOURCE_EXCEEDED: RetryableTier.REPHRASE,
        ErrorCode.EXEC_TIMEOUT: RetryableTier.REPHRASE,
        ErrorCode.SQL_SYNTAX_ERROR: RetryableTier.REPHRASE,
        # ⚠️ INTERNAL 按**附录 A §A.11**（⭕），而非 07 §14.4 的 ✅ —— 见 U-21 说明
        ErrorCode.INTERNAL: RetryableTier.REPHRASE,
        # ❌ 不得带 Retry-After，也不给 suggestions
        ErrorCode.INVALID_REQUEST: RetryableTier.NONE,
        ErrorCode.AUTH_FAILED: RetryableTier.NONE,
        ErrorCode.TOKEN_REVOKED: RetryableTier.NONE,
        ErrorCode.FORBIDDEN_SCOPE: RetryableTier.NONE,
        ErrorCode.PII_BLOCKED: RetryableTier.NONE,
        ErrorCode.TASK_NOT_FOUND: RetryableTier.NONE,
        ErrorCode.SESSION_NOT_FOUND: RetryableTier.NONE,
        ErrorCode.RUN_NOT_FOUND: RetryableTier.NONE,
        ErrorCode.DATASET_NOT_FOUND: RetryableTier.NONE,
        ErrorCode.AMBIGUOUS_QUERY: RetryableTier.NONE,
        ErrorCode.TASK_NOT_CANCELLABLE: RetryableTier.NONE,
        ErrorCode.IDEMPOTENCY_CONFLICT: RetryableTier.NONE,
        ErrorCode.CLARIFY_EXPIRED: RetryableTier.NONE,
        ErrorCode.CLARIFY_INVALID_OPTION: RetryableTier.NONE,
        ErrorCode.GATE_AST_REJECTED: RetryableTier.NONE,
        ErrorCode.GATE_POLICY_REJECTED: RetryableTier.NONE,
        ErrorCode.NO_DATA_ASSET: RetryableTier.NONE,
        # 成功不参与可重试语义
        ErrorCode.OK: RetryableTier.NONE,
    }
)

#: ⚠️ **`INTERNAL` 的档位在 07 与附录 A 之间冲突，本文件按契约优先级取附录 A**（登记 **U-21**）：
#:   · 附录 A §A.11 表：`INTERNAL` = **`⭕`**
#:   · 07 v0.6 §14.4 表：`INTERNAL` 被列进 **`✅`** 那行
#: 优先级规则是「附录 A > PRD > 06 > 07」（08 §0.1），故取 `⭕` → **不带 `Retry-After`、
#: 必须给 `suggestions[]`**（这里给的是"复制 trace_id 并反馈"，即 §A.11 的"用户文案要点"）。
#: 理由不只是"服从优先级"：`✅` 要求"承诺一个等待时长"，而**两张文档都没有给 `INTERNAL` 定义过
#: 任何 `Retry-After` 数值** —— 那会逼实现者发明一个数字，正是 U-17 刚推翻的"假承诺"。
#: → 若架构窗口判定按 07（✅），则**必须同时给出 `INTERNAL` 的 `Retry-After` 值**，否则不可实现。
ERROR_RETRY_TIER_U21_NOTE = "见 U-21：INTERNAL 档位以附录 A §A.11 为准（⭕）"

#: `Retry-After` 是否**必须**出现。True ⇒ 必须带；False ⇒ **不得带**。
#:
#: ⚠️ **只对 `✅` 为 True** —— 这是 U-17 裁定的**核心修正**（07 v0.6 §14.4）。
#: 本文件最初的写法是 `tier is not RetryableTier.NONE`（即 `⭕` 也要带），
#: 并附了一段"承认 retryable 布尔与 Retry-After 是两个判据"的论证 —— **那段论证是错的**：
#: 它只注意到"⭕ 带 Retry-After 不违反可重试性"，**没注意到 `Retry-After` 是一句承诺**
#: （"等这么久再发一次会有不同结果"），而 ⭕ 的定义就是"原样重发必然失败"。
#: 两者并列会**把用户骗进必然失败的重试**。→ 已改为只对 `✅` 为 True。
RETRY_AFTER_REQUIRED: Final[Mapping[ErrorCode, bool]] = MappingProxyType(
    {code: tier is RetryableTier.YES for code, tier in ERROR_RETRY_TIER.items()}
)

#: 响应里的 `retryable` 布尔（附录 A §A.1.2 `error` 事件的 `retryable` 字段）。
#: **只对 `✅` 为 True** —— `⭕` 的语义是"原样重试必然失败"，故 `retryable=false` 是正确的。
RETRYABLE_BOOLEAN: Final[Mapping[ErrorCode, bool]] = MappingProxyType(
    {code: tier is RetryableTier.YES for code, tier in ERROR_RETRY_TIER.items()}
)

#: 是否**必须**同时给出 `suggestions[]`。
#: **只对 `⭕` 为 True**，且这是**硬要求**（07 §14.4：`⭕` 必须给"可执行的改法"，
#: 且**不得显示倒计时**）—— 因为对 `⭕` 而言，"怎么改"是用户唯一的出路。
REQUIRES_SUGGESTIONS: Final[Mapping[ErrorCode, bool]] = MappingProxyType(
    {code: tier is RetryableTier.REPHRASE for code, tier in ERROR_RETRY_TIER.items()}
)

#: ✅ 档缺省 `Retry-After`（秒）。**只对附录 A 没给值的 ✅ 码生效**。
#:
#: ⚠️ 登记 **U-22**：§14.4 说这 6 个 ✅ 码"**必须带** `Retry-After`"，但**只给了两个值**：
#: `RATE_LIMITED` 按桶（§A.0.6：查询 30 / 读取 5 / 写入 10 / 管理员 60）、
#: `SESSION_CONFLICT` = 3（§A.11 补充约定）。剩下三个 W0 曾给保守缺省，
#: **07 v0.8 §14.4.1 已裁定替代**（含推导纪律 4：每个值必须能从内部退避窗口 /
#: 熔断开路时长 / 锁等待上限 / 池超时推导）：
#:   · `LLM_CONCURRENCY_EXCEEDED` = 5s（内部已退避 3.5s 才外抛，2s 落在同一失败窗口内；
#:     W0 原值 2s 被裁正）
#:   · `LLM_UPSTREAM_ERROR` = 30s（熔断开路 30s 内重试**必然失败**，给 5s 等于保证失败；
#:     W0 原值 5s 被裁正）
#:   · `DB_UNAVAILABLE` = 5s（07 §14.4 表内明文给定；⚠️ U-52：与池等待的推导自洽性
#:     归 07 §8 / W1B，勿在此处自行改动）
RETRY_AFTER_DEFAULT_S: Final[Mapping[ErrorCode, int]] = MappingProxyType(
    {
        ErrorCode.RATE_LIMITED: 30,               # 查询类桶；真实值必须走 map_rate_limited(bucket)
        ErrorCode.SESSION_CONFLICT: 3,            # 附录 A §A.11 补充约定（明文给定）
        ErrorCode.LLM_CONCURRENCY_EXCEEDED: 5,    # 07 v0.8 §14.4.1（U-22 裁正，原 2s）
        ErrorCode.LLM_UPSTREAM_ERROR: 30,         # 07 v0.8 §14.4.1（U-22 裁正，原 5s）
        ErrorCode.DB_UNAVAILABLE: 5,              # 07 §14.4 明文；推导自洽性归 U-52（07 §8）
    }
)

#: ⭕ 档的缺省 `suggestions[]`。**存在的理由**：`REQUIRES_SUGGESTIONS` 是硬约束，
#: 若构造器不给，`HttpErrorMapping.validate()` 会拒 —— 那会让"忘了传 suggestions"
#: 变成运行时异常。给缺省值，是让**契约在默认路径上就可满足**（fail-safe 而非 fail-open）。
#: ⚠️ 缺省值只能是**通用改法**；端点层知道具体原因时**必须覆盖它**
#: （例如 gate3 拒绝可给出"把时间范围收窄到 7 天"这种带数字的建议）。
DEFAULT_SUGGESTIONS: Final[Mapping[ErrorCode, tuple[str, ...]]] = MappingProxyType(
    {
        ErrorCode.COST_TOO_HIGH: ("收窄时间范围", "增加过滤条件", "减少分组维度"),
        ErrorCode.EXEC_RESOURCE_EXCEEDED: ("收窄查询范围", "增加过滤条件"),
        ErrorCode.EXEC_TIMEOUT: ("收窄时间范围", "增加过滤条件"),
        ErrorCode.SQL_SYNTAX_ERROR: ("换一种问法", "把问题拆成两步"),
        # U-21：附录 A §A.11 的用户文案要点就是"带 trace_id，请反馈"
        ErrorCode.INTERNAL: ("复制 trace_id 并反馈", "稍后换一种问法重试"),
    }
)

#: `SESSION_CONFLICT`(409) 的建议 `Retry-After`（附录 A §A.11 补充约定）。
#: ⚠️ 该码**不返回** `X-RateLimit-*` —— 它不是配额事件。
#: ✅ 它是 `RETRY_AFTER_DEFAULT_S` 的**别名**（同一个事实只准有一处字面量，
#: 由 `validate_contract_counts()` 钉住）。
SESSION_CONFLICT_RETRY_AFTER_S: Final[int] = RETRY_AFTER_DEFAULT_S[ErrorCode.SESSION_CONFLICT]


# ============================================================================
# 三、结果、终态与降级
# ============================================================================

class Outcome(StrEnum):
    """审计 `audit_log.outcome` —— 5 值。**语义权威 = PRD §9.2**（07 §14.1）。"""

    SUCCESS = "success"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    DEGRADED = "degraded"
    FAILED = "failed"


class TaskStatus(StrEnum):
    """`GET /query/{task_id}` 的 `status` —— **8 值**（补充契约 C-05）。

    后 5 个与 `Outcome` 对齐；前 3 个是任务生命周期态。
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RefuseReason(StrEnum):
    """`refuse.reason` —— **4 值**（补充契约 C-12）。

    ⚠️ `refuse` = **产品结论**（系统不回答这类问题）；`error` = **工程故障**。
    二者边界见 07 §7.6.1 —— 闸门拒绝走 `error`，**不得渲染成拒答卡**（06 §7.2）。
    ⚠️ 「查询成功但结果为空」**不用本枚举**：走正常 `data` + `complete`，由 `meta.scope` 表达（附录 A §A.11）。
    本枚举**同时**是 `GraphState.intent_detail.refuse_kind` 的取值集（07 §5.2 组 3）—— 一处定义，两处引用。
    """

    NO_DATA_ASSET = "no_data_asset"
    OUT_OF_SCOPE = "out_of_scope"
    PII_BLOCKED = "pii_blocked"
    OPEN_ANALYSIS = "open_analysis"


class ClarifyReason(StrEnum):
    """`clarify.reason` —— 2 值（07 §14.2 A1/A2、B2/B3；事件契约见附录 A §A.1.2）。"""

    TIME_AMBIGUOUS = "time_ambiguous"
    AMBIGUITY = "ambiguity"


class DegradedReason(StrEnum):
    """`degraded.reason` —— **8 值**（补充契约 C-08，v0.3 修正后）。

    ⚠️ 与 `ActionTaken` **不对称**：reason = "为什么"，action_taken = "做了什么"，
    同一个词不得两边都放（`template_only` 曾被误放进 reason，已移除）。
    """

    COST_TOO_HIGH = "cost_too_high"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_CONCURRENCY_EXCEEDED = "llm_concurrency_exceeded"
    LATENCY_EXCEEDED = "latency_exceeded"
    EMBEDDING_UNAVAILABLE = "embedding_unavailable"
    PLAN_GENERATION_FAILED = "plan_generation_failed"
    PRESENT_FAILED = "present_failed"
    CACHE_FALLBACK = "cache_fallback"


class ActionTaken(StrEnum):
    """`degraded.action_taken` —— **7 值**（补充契约 C-08）。

    不加 `switched_to_weak_model` / `template_only` / `table_only` 这三项，实现者只能被迫
    复用语义不符的枚举值（C-08 原文说明了这一点）。
    """

    REDUCED_CANDIDATES = "reduced_candidates"
    SWITCHED_TO_WEAK_MODEL = "switched_to_weak_model"
    USED_CACHE = "used_cache"
    SWITCHED_TO_ASYNC = "switched_to_async"
    SPARSE_ONLY = "sparse_only"
    TEMPLATE_ONLY = "template_only"
    TABLE_ONLY = "table_only"


class RetrievalMode(StrEnum):
    """`meta.retrieval_mode` —— 2 值（补充契约 C-11）。

    `sparse_only` = 稠密检索不可用时的降级，**必须在 `meta` 中显式标注**，
    只有 `degraded` 事件不足以让前端/审计**随时**判定本轮检索质量。
    """

    HYBRID = "hybrid"
    SPARSE_ONLY = "sparse_only"


# ============================================================================
# 四、语义绑定
# ============================================================================

class BindingState(StrEnum):
    """字段绑定四态 —— **必须落库**（`query_plan.binding_state`）。

    它是澄清率异常时的**唯一诊断入口**（07 §12.3 / §6.8.3）：
    不落库 → 澄清率超标时无法定位是哪一层失效。
    """

    RESOLVED_UNIQUE = "resolved_unique"
    RESOLVED_DEFAULT = "resolved_default"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class BindingLayer(StrEnum):
    """四层判定的层号（07 §6.8.2 硬约束 5）。

    `L4` 占比本身就是**语义层质量的仪表盘** —— 频繁触发 L4 说明 L1 别名表 / L3 默认口径没建够，
    补救方向是**回看语义包**，不是放宽 τ（N-25）。
    """

    L1 = "L1"  # 确定性映射（别名表）
    L2 = "L2"  # 粒度消歧
    L3 = "L3"  # 默认口径（default_binding）
    L4 = "L4"  # 打分兜底（唯一可调 τ 的一层）


class GoldQueryTier(StrEnum):
    """Gold Query 的**归属层**（07 v0.6 §11.7，**由 U-14 牵出的新决策**）。

    ⚠️ **物理判据是 `gold_query.tenant_id` 是否为 `NULL`，不是新增一个 `tier` 列。**
    本枚举只提供"逻辑层名"，供检索 SQL、审批流程与观测标签使用；
    **不得**在表上再加一个 `tier` 列 —— 那就是同一事实的第二份真相（§4.1 要根治的病）。

    ⚠️ 为什么它值得一个枚举：这两层的**进库门槛不同**，而不是同一门槛加个过滤。
    全局层的内容**会跨租户传播**，故审核除正确性外还必须确认"**不含任何业务信息**"——
    这是 N-12（出站内容白名单）在 prompt 层的落地。
    把它们混成一个值，等于把"额外审批"这道闸门从枚举层面删掉。

    ⚠️ 相关回填：**U-20**（PRD FR-11.2 与 07 §12.3 的 `gold_query` 表定义需补
    `tenant_id`（nullable）+ "进全局库需额外审批"的规则）—— 归**上游/架构**处理，不属 W0。
    """

    GLOBAL_CERTIFIED = "global_certified"  # tenant_id IS NULL：所有租户可见（**需额外审批**）
    TENANT_PRIVATE = "tenant_private"      # tenant_id = 租户 ID：仅该租户可见


# ============================================================================
# 五、呈现
# ============================================================================

class ChartType(StrEnum):
    """`chart_type` —— **7 值**（响应侧）。选择规则见附录 A §A.10。

    ✅ **U-15 已裁定（07 v0.6 §4.2 断言⑤）**：本枚举原与 07 §4.2 断言⑤ 的"6 值"冲突，
    架构窗口采纳 7 值，并**额外指出请求侧是另一个枚举** —— `ChartPreference`(8 值，含
    `auto`/`none`)，二者**不同字段、不同取值集，不得合并**
    （合并会让 `auto` 漏进响应侧校验，前端零判断权被打破，N-16）。
    """

    LINE = "line"                 # 时间序列（x 轴为时间且 ≥3 点）
    BAR = "bar"                   # 分类对比（单指标）
    STACKED_BAR = "stacked_bar"   # 多指标分类对比（堆叠）
    GROUPED_BAR = "grouped_bar"   # 多指标分类对比（分组）
    PIE = "pie"                   # 占比（≤8 个分类）
    KPI = "kpi"                   # 单值（1 行 1 列）
    TABLE = "table"               # 明细（行 >20 或列 >6）


class ChartPreference(StrEnum):
    """`options.chart_preference` —— 8 值（附录 A §A.1.1）。

    ⚠️ 注意它**不含** `grouped_bar`，但含 `auto` 与 `none` —— 与 `ChartType` 不是同一个集合，
    不得互相赋值（典型事故：把用户偏好直接当成最终 `chart_type` 下发，前端零判断权即被破坏，N-16）。
    ✅ U-15 后 07 §4.2 断言⑤ 已把它写成独立一项，并明确指出"**不得合并为一个枚举**"。
    """

    AUTO = "auto"
    LINE = "line"
    BAR = "bar"
    STACKED_BAR = "stacked_bar"
    PIE = "pie"
    TABLE = "table"
    KPI = "kpi"
    NONE = "none"


class CitationType(StrEnum):
    """`insight.citations[].type` —— 3 值（补充契约 C-06）。"""

    METRIC = "metric"
    ASSET = "asset"
    SYNONYM = "synonym"


# ============================================================================
# 六、权限与闸门
# ============================================================================

class Role(StrEnum):
    """角色 —— **7 值**（07 §13.2）。

    ⚠️ `platform_admin` 对业务表**仍受 RLS 约束**（其租户 = 管理租户）：
    跨租户业务明细查询必须**显式拒绝**，不能靠"他是管理员所以放行"。
    """

    SHOP_OWNER = "shop_owner"
    OPERATOR = "operator"
    MARKETER = "marketer"
    FINANCE = "finance"
    SUPPORT = "support"
    ANALYST = "analyst"
    PLATFORM_ADMIN = "platform_admin"


class ScopeLevel(StrEnum):
    """`meta.scope.level` —— 3 值（附录 A §A.1.5 三级披露策略）。

    ⚠️ 这是**防存在性泄露**的机制：直接告知"有数据但你看不到"会让用户二分试探出数据存在性。
    `scope` 字段**缺失**时的缺省语义见补充契约 C-07（视为 `unrestricted`，且不改披露策略）。
    """

    TENANT_ISOLATED = "tenant_isolated"
    ROLE_LIMITED = "role_limited"
    UNRESTRICTED = "unrestricted"


class GateNo(IntEnum):
    """闸门编号（07 §7.1）。**顺序不可变、不可跳过**（N-03）。"""

    AST = 1      # 闸门一：AST 静态审计
    POLICY = 2   # 闸门二：策略校验（含 scope 计算）
    COST = 3     # 闸门三：EXPLAIN 成本闸门


class GateDecision(StrEnum):
    """闸门判定（07 §14.2 D4/D5/D6）。

    ⚠️ `SKIPPED`（SQLite 沙箱跳过 gate3）**不得报告为通过**（D6 原文）。
    """

    PASS = "pass"
    REJECT = "reject"
    WARN = "warn"
    SKIPPED = "skipped"


class AstRuleSeverity(StrEnum):
    """AST 规则的**处置级别**（07 v0.6 §7.2）。

    ⚠️ **这一层划分是 U-16 的产物，而它比"规则加到 20 条"本身更重要。**
    我（W0）当初只报了"规则条数不足、红队集无法逐条覆盖"；架构窗口扩到 20 条的同时
    指出：**R17–R20 是"告警级"不是"阻断级"**，并特别标注 ——
    **必须断言"产生告警且查询继续"，写成拒绝即为实现缺陷**（会误杀正常查询）。

    把 `WARN` 与 `BLOCK` 放进同一个枚举，是为了让"两者断言方式相反"这件事
    在类型层面就可见：任何按 `severity` 分支的代码都会被迫处理三种情况，
    而不是默认"不通过的都拒绝"。
    """

    BLOCK = "block"      # 阻断：拒绝执行，返回错误码
    REWRITE = "rewrite"  # 改写：不拒绝，改写后继续（注入 LIMIT / 剥离注释后重解析）
    WARN = "warn"        # 告警：**记录后继续**，不改变查询语义，不拒绝


class AstRule(StrEnum):
    """AST 静态审计规则编号 —— **R01–R20（20 条）**，权威来源 07 v0.6 §7.2。

    ⚠️ **本枚举的存在意义是"编号不能被随便改"**：规则编号会进入
    `gate_detail.ast.rule_id`（补充契约 C-02）与观测指标分组（§14.5 要求按 `rule_id` 分组），
    改一个编号 = 让历史指标与红队用例失效。所以它是取值集，不是常量表。

    ⚠️ 与 07 §14.2 D1 的关系：D1 曾写成 `R01…R16`（见**已销账的 U-16**）。
    **规则实体（判据、正则、文案）归 W2C 的 `guard/rules.py`** —— 本枚举只锁编号与级别。
    """

    # --- 阻断级（14 条）---
    R01_STATEMENT_TYPE = "R01"      # 只允许 SELECT / WITH...SELECT
    R02_MULTI_STATEMENT = "R02"     # 表达式数 ≠ 1 → 拒绝
    R03_SELECT_STAR = "R03"         # SELECT * / t.* / 隐式全列
    R05_TABLE_ALLOWLIST = "R05"     # 表必须在 allowed_assets 内
    R06_COLUMN_ALLOWLIST = "R06"    # 列引用（含 GROUP/ORDER/HAVING/窗口）必须在允许列内
    R07_DENY_COLUMNS = "R07"        # policy.deny_columns（列级屏蔽优先于一切）
    R08_SYSTEM_SCHEMA = "R08"       # information_schema / pg_catalog / pg_temp* / pg_toast*
    R09_FUNCTION_DENYLIST = "R09"   # pg_read_file / pg_sleep / dblink / set_config …
    R10_JOIN_PATH = "R10"           # JOIN 必须落在 join_path 内
    R11_CARTESIAN = "R11"           # 无 ON/USING 的 JOIN / CROSS JOIN
    R12_RECURSIVE_CTE = "R12"       # WITH RECURSIVE → P0 直接拒绝
    R13_UNION_SCOPE = "R13"         # UNION/INTERSECT/EXCEPT 每分支独立过 R05/R06/R07
    R14_LITERAL_POLICY = "R14"      # 除三类白名单外不得出现字面量
    R16_SEARCH_PATH = "R16"         # 不得修改 search_path
    # --- 改写级（2 条）---
    R04_FORCE_LIMIT = "R04"         # 顶层无 LIMIT → 注入/改写（§7.3）
    R15_COMMENT_STRIP = "R15"       # 剥离注释后**重新解析**
    # --- 告警级（4 条，★ 断言方式与上面相反）---
    R17_IMPLICIT_CAST = "R17"       # 高风险比较（字符串列 vs 数字常量）→ 记录
    R18_UNBOUNDED_SORT = "R18"      # ORDER BY 作用于超大结果集 → 交 gate3 成本判定
    R19_SUBQUERY_DEPTH = "R19"      # 嵌套深度 > 5 → 记录
    R20_OUTPUT_COLUMNS = "R20"      # 顶层输出列 > 50 → 记录


#: 规则 → 处置级别（07 v0.6 §7.2 的表逐行落位）。**必须覆盖 `AstRule` 全集**。
AST_RULE_SEVERITY: Final[Mapping[AstRule, AstRuleSeverity]] = MappingProxyType(
    {
        AstRule.R01_STATEMENT_TYPE: AstRuleSeverity.BLOCK,
        AstRule.R02_MULTI_STATEMENT: AstRuleSeverity.BLOCK,
        AstRule.R03_SELECT_STAR: AstRuleSeverity.BLOCK,
        AstRule.R04_FORCE_LIMIT: AstRuleSeverity.REWRITE,
        AstRule.R05_TABLE_ALLOWLIST: AstRuleSeverity.BLOCK,
        AstRule.R06_COLUMN_ALLOWLIST: AstRuleSeverity.BLOCK,
        AstRule.R07_DENY_COLUMNS: AstRuleSeverity.BLOCK,
        AstRule.R08_SYSTEM_SCHEMA: AstRuleSeverity.BLOCK,
        AstRule.R09_FUNCTION_DENYLIST: AstRuleSeverity.BLOCK,
        AstRule.R10_JOIN_PATH: AstRuleSeverity.BLOCK,
        AstRule.R11_CARTESIAN: AstRuleSeverity.BLOCK,
        AstRule.R12_RECURSIVE_CTE: AstRuleSeverity.BLOCK,
        AstRule.R13_UNION_SCOPE: AstRuleSeverity.BLOCK,
        AstRule.R14_LITERAL_POLICY: AstRuleSeverity.BLOCK,
        AstRule.R15_COMMENT_STRIP: AstRuleSeverity.REWRITE,
        AstRule.R16_SEARCH_PATH: AstRuleSeverity.BLOCK,
        AstRule.R17_IMPLICIT_CAST: AstRuleSeverity.WARN,
        AstRule.R18_UNBOUNDED_SORT: AstRuleSeverity.WARN,
        AstRule.R19_SUBQUERY_DEPTH: AstRuleSeverity.WARN,
        AstRule.R20_OUTPUT_COLUMNS: AstRuleSeverity.WARN,
    }
)

#: 告警级规则（**命中不得拒绝**）。W2C 的代码与红队用例都应以本集合为判据，
#: 而不是各自写一遍 `rule_id in {...}` —— 那是第二份真相。
AST_WARNING_RULES: Final[frozenset[AstRule]] = frozenset(
    rule for rule, sev in AST_RULE_SEVERITY.items() if sev is AstRuleSeverity.WARN
)

#: 阻断级规则（命中必须拒绝，且必须带 `rule_id` 进 `gate_detail`）。
AST_BLOCKING_RULES: Final[frozenset[AstRule]] = frozenset(
    rule for rule, sev in AST_RULE_SEVERITY.items() if sev is AstRuleSeverity.BLOCK
)

#: 改写级规则（命中不拒绝，改写后继续）。
AST_REWRITE_RULES: Final[frozenset[AstRule]] = frozenset(
    rule for rule, sev in AST_RULE_SEVERITY.items() if sev is AstRuleSeverity.REWRITE
)


class LimitType(StrEnum):
    """`error.detail.limit_type` —— 3 值（附录 A §A.11 `EXEC_RESOURCE_EXCEEDED` 补充约定）。

    ⚠️ **只用于区分"维度"**；**不得**用它去区分"是否成本闸门" —— 那是**码本身**的职责
    （把层级差异塞进 detail = 把两个码偷偷合并成一个）。
    """

    MEMORY = "memory"      # P0
    ROWS = "rows"          # 预留
    TEMP_DISK = "temp_disk"  # 预留


# ============================================================================
# 七、限流与计量
# ============================================================================

class RateLimitBucket(StrEnum):
    """限流分桶（附录 A §A.0.6 / 07 §9.2）。

    ⚠️ `429` **只用于配额超限**；会话串行冲突走 `409 SESSION_CONFLICT`（不同层，不得复用）。
    """

    QUERY = "query"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    GLOBAL_CONCURRENCY = "global_concurrency"


#: 各桶超限时的 `Retry-After`（秒）。`GLOBAL_CONCURRENCY` 无该头语义。
RATE_LIMIT_BUCKET_RETRY_AFTER_S: Final[Mapping[RateLimitBucket, int | None]] = MappingProxyType(
    {
        RateLimitBucket.QUERY: 30,
        RateLimitBucket.READ: 5,
        RateLimitBucket.WRITE: 10,
        RateLimitBucket.ADMIN: 60,
        RateLimitBucket.GLOBAL_CONCURRENCY: None,
    }
)


class LatencyKey(StrEnum):
    """`meta.latency_ms` 的键 —— **8 个**（补充契约 C-04）。

    ⚠️ 必须与 PRD §9.2 `audit_log.latency_ms` 的键**完全一致**（C-04 明确要求，避免两套键名）。
    """

    NORMALIZE = "normalize"
    LINKING = "linking"
    PLAN = "plan"
    GEN_SQL = "gen_sql"
    GATE = "gate"
    EXEC = "exec"
    PRESENT = "present"
    TOTAL = "total"


class TokenKey(StrEnum):
    """`meta.tokens` 的键 —— 4 个（补充契约 C-03）。"""

    INPUT = "input"
    OUTPUT = "output"
    CACHE_HIT = "cache_hit"
    TOTAL = "total"


# ============================================================================
# 八、健康检查（附录 A §A.8 —— 三探针 + 硬/软依赖分级）
# ============================================================================

class HealthStatus(StrEnum):
    """`/healthz` 聚合详情的 `status` —— 3 值（附录 A §A.8.4）。

    ⚠️ 与 HTTP 状态的对应是**硬约定**，也是最容易做错的一条：
    - `OK` → 200
    - `DEGRADED`（**仅软依赖失败**）→ **200**（服务可用，只是能力降级）
    - `UNHEALTHY`（任一硬依赖失败）→ 503

    原设计在"LLM 不可达"时返回 `503 + degraded` —— **那是错的**：任何按 HTTP 码判断的
    编排层/监控都会误判为服务不可用，**等于把已设计好的降级路径作废**。
    """

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DependencyKind(StrEnum):
    """依赖分级（附录 A §A.8.1）。

    ⚠️ `SOFT` 的失败动作是**降级继续服务**，因此**不得计入 readiness**（N-21）：
    把软依赖塞进 readiness，等于让"降级"变成"不可用"。
    """

    HARD = "hard"  # 失败 → 摘流量（**不重启**）
    SOFT = "soft"  # 失败 → 降级 + `degraded` 事件，继续服务


class Dependency(StrEnum):
    """被探依赖名 —— 6 值（附录 A §A.8.1）。

    ⚠️ `LLM` 与 `EMBEDDING` **必须分列上报**：二者是两个互相独立的外部依赖
    （Ollama 在宿主、DeepSeek 在公网），合成一个字段会让"到底谁挂了"无法定位。
    """

    METADATA_DB = "metadata_db"
    CHECKPOINTER = "checkpointer"
    REDIS = "redis"
    SEMANTIC_BUNDLE_LOADED = "semantic_bundle_loaded"
    LLM = "llm"
    EMBEDDING = "embedding"


#: 依赖 → 硬/软分级（附录 A §A.8.1 的机器可读形式）。
#: 元数据库 / checkpointer / Redis / 语义包 = 硬；LLM / embedding = 软。
DEPENDENCY_KIND: Final[Mapping[Dependency, DependencyKind]] = MappingProxyType(
    {
        Dependency.METADATA_DB: DependencyKind.HARD,
        Dependency.CHECKPOINTER: DependencyKind.HARD,
        Dependency.REDIS: DependencyKind.HARD,
        Dependency.SEMANTIC_BUNDLE_LOADED: DependencyKind.HARD,
        Dependency.LLM: DependencyKind.SOFT,
        Dependency.EMBEDDING: DependencyKind.SOFT,
    }
)

#: `/healthz/ready` **只允许**检查这些（N-21）。阶段 0 的 503 就是这条规则的正确体现。
READINESS_DEPENDENCIES: Final[frozenset[Dependency]] = frozenset(
    d for d, k in DEPENDENCY_KIND.items() if k is DependencyKind.HARD
)

#: 失败时**必须** `200 + degraded` + 发 `degraded` 事件，且**不得静默降级**（N-21 / NFR-2.7）。
DEGRADABLE_DEPENDENCIES: Final[frozenset[Dependency]] = frozenset(
    d for d, k in DEPENDENCY_KIND.items() if k is DependencyKind.SOFT
)


# ============================================================================
# 九、契约自检（供 CI / 单测调用；属"护栏"，不属业务逻辑）
# ============================================================================

#: 取值集基数表 —— 07 §4.2 断言⑤ 与 `tests/contract/` 直接读这张表。
CONTRACT_COUNTS: Final[Mapping[str, int]] = MappingProxyType(
    {
        # 以下 3 项是 07 §4.2 断言⑤ 明文要求的
        "stage": 6,
        "error_code": 28,
        "chart_type": 7,
        # 以下为守卫项：写错一位就能立刻发现
        "sse_event": 12,
        "sse_emission_points": 17,
        "sse_terminal_events": 4,
        "outcome": 5,
        "task_status": 8,
        "refuse_reason": 4,
        "clarify_reason": 2,
        "degraded_reason": 8,
        "action_taken": 7,
        "retrieval_mode": 2,
        "binding_state": 4,
        "binding_layer": 4,
        "role": 7,
        "scope_level": 3,
        "gate_no": 3,
        "gate_decision": 4,
        "chart_preference": 8,
        "citation_type": 3,
        "limit_type": 3,
        "rate_limit_bucket": 5,
        "latency_key": 8,
        "token_key": 4,
        # 健康检查（附录 A §A.8）
        "health_status": 3,
        "dependency": 6,
        "readiness_dependencies": 4,
        "degradable_dependencies": 2,
        # 闸门规则表基数（07 §7.2）。✅ U-16 已裁定 = **20 条**（R01–R20）。
        # 本项**已纳入校验**：`AstRule` 现在是本文件的实体，不再是"只登记数字"。
        # （规则实体的判据与文案仍归 W2C 的 `guard/rules.py`，本枚举只锁编号与级别。）
        "ast_rule": 20,
        "ast_rule_severity": 3,
        # 语义与绑定（U-14 §11.7 新增）
        "gold_query_tier": 2,
    }
)


def validate_contract_counts() -> None:
    """自检：枚举实际基数 == `CONTRACT_COUNTS` 声明值。

    在 CI 与单测中调用（07 §4.2 断言⑤）。**失败即说明有人改了取值集却没同步契约**。
    """
    actual = {
        "stage": len(Stage),
        "error_code": len(ErrorCode),
        "chart_type": len(ChartType),
        "sse_event": len(SseEvent),
        "sse_emission_points": len(SSE_STAGE_EMISSION_POINTS),
        "sse_terminal_events": len(SSE_TERMINAL_EVENTS),
        "outcome": len(Outcome),
        "task_status": len(TaskStatus),
        "refuse_reason": len(RefuseReason),
        "clarify_reason": len(ClarifyReason),
        "degraded_reason": len(DegradedReason),
        "action_taken": len(ActionTaken),
        "retrieval_mode": len(RetrievalMode),
        "binding_state": len(BindingState),
        "binding_layer": len(BindingLayer),
        "role": len(Role),
        "scope_level": len(ScopeLevel),
        "gate_no": len(GateNo),
        "gate_decision": len(GateDecision),
        "chart_preference": len(ChartPreference),
        "citation_type": len(CitationType),
        "limit_type": len(LimitType),
        "rate_limit_bucket": len(RateLimitBucket),
        "latency_key": len(LatencyKey),
        "token_key": len(TokenKey),
        "health_status": len(HealthStatus),
        "dependency": len(Dependency),
        "readiness_dependencies": len(READINESS_DEPENDENCIES),
        "degradable_dependencies": len(DEGRADABLE_DEPENDENCIES),
        "ast_rule": len(AstRule),
        "ast_rule_severity": len(AstRuleSeverity),
        "gold_query_tier": len(GoldQueryTier),
    }
    mismatches = {
        key: (declared, actual.get(key))
        for key, declared in CONTRACT_COUNTS.items()
        if actual.get(key) != declared
    }
    if mismatches:
        detail = "; ".join(f"{k}: 声明={d} 实际={a}" for k, (d, a) in mismatches.items())
        raise ValueError(f"取值集基数与 CONTRACT_COUNTS 不一致 → {detail}")

    # ---- U-15：chart_type 与 chart_preference 是**两个**枚举，不得合并 ----
    # 若有人图省事把它们合成一个，`auto`/`none` 就会漏进响应侧校验（N-16 被破坏）。
    # ⚠️ 用 `.value` 字符串集合比较而不是 `set(ChartType) == set(ChartPreference)`：
    #    后者会被 mypy 判为"类型上不可能相等"（两个 StrEnum 类型不重叠）而报
    #    `comparison-overlap` —— 那正是我们要检查的东西，但静态类型视角看不到
    #    "有人改了定义"这件事。改用字符串值比较，检查意图保留且类型检查通过。
    if not (ChartType.__members__.keys() & ChartPreference.__members__.keys()):
        raise ValueError("ChartType 与 ChartPreference 不得合并：二者必须有交集但非同一集合")
    _chart_type_values: set[str] = {c.value for c in ChartType}
    _chart_pref_values: set[str] = {c.value for c in ChartPreference}
    if _chart_type_values == _chart_pref_values:
        raise ValueError(
            "ChartType(响应侧 7 值) 与 ChartPreference(请求侧 8 值) 被改成了同一集合 "
            "—— U-15 明确二者不同字段、不同取值集（07 §4.2 断言⑤）"
        )
    if ChartPreference.AUTO.value in _chart_type_values:
        raise ValueError("`auto` 只存在于请求侧 chart_preference，不得出现在响应侧 chart_type")

    # ---- U-16：告警级规则命中的处理方式是"记录后继续"，写成拒绝 = 实现缺陷 ----
    if set(AST_RULE_SEVERITY) != set(AstRule):
        missing = sorted(set(AstRule) - set(AST_RULE_SEVERITY))
        raise ValueError(f"AST_RULE_SEVERITY 未覆盖全部规则：缺 {missing}")
    warn_rules = {r.value for r in AST_WARNING_RULES}
    if warn_rules != {"R17", "R18", "R19", "R20"}:
        raise ValueError(
            f"告警级规则必须是 R17–R20（07 v0.6 §7.2），实际 = {sorted(warn_rules)} "
            f"—— 把 R17–R20 改成阻断级会**误杀正常查询**（U-16 明文警告）"
        )

    # ---- U-17：Retry-After 的**三级不对称**（⭕ 不得带，必须给 suggestions）----
    for code, tier in ERROR_RETRY_TIER.items():
        if tier is RetryableTier.REPHRASE:
            if RETRY_AFTER_REQUIRED[code]:
                raise ValueError(
                    f"{code} 属 ⭕ 却要求带 Retry-After —— 那是假承诺（U-17）："
                    f"⭕ 的定义就是'原样重试必然失败'，而 Retry-After 的含义是"
                    f"'等这么久再发一次会有不同结果'"
                )
            if not REQUIRES_SUGGESTIONS[code]:
                raise ValueError(f"{code} 属 ⭕ 却未要求 suggestions[]（U-17）")
        if tier is RetryableTier.NONE and RETRY_AFTER_REQUIRED[code]:
            raise ValueError(f"{code} 属 ❌ 却要求带 Retry-After —— 会诱导无意义重试")
    for code, required in RETRY_AFTER_REQUIRED.items():
        if required and code not in RETRY_AFTER_DEFAULT_S:
            raise ValueError(
                f"{code} 要求必须带 Retry-After，但 RETRY_AFTER_DEFAULT_S 未给值 "
                f"—— '必须带' + '没有值' = 逼实现者发明数字（U-22）"
            )

    # `RATE_LIMITED` 与 `SESSION_CONFLICT` 的值在附录 A 有明文，别处不得再写第二遍字面量
    if RETRY_AFTER_DEFAULT_S[ErrorCode.RATE_LIMITED] != RATE_LIMIT_BUCKET_RETRY_AFTER_S[
        RateLimitBucket.QUERY
    ]:
        raise ValueError(
            "RATE_LIMITED 的缺省 Retry-After 与 §A.0.6 的查询类桶值不一致 "
            "—— 同一个数值出现了两处字面量"
        )
    if (
        RETRY_AFTER_DEFAULT_S[ErrorCode.SESSION_CONFLICT]
        != SESSION_CONFLICT_RETRY_AFTER_S
    ):
        raise ValueError("SESSION_CONFLICT_RETRY_AFTER_S 必须是 RETRY_AFTER_DEFAULT_S 的别名")

    # 错误码两张查找表必须覆盖全集（漏一项 → 某条出口路径没有 HTTP 码）
    missing_http = set(ErrorCode) - set(ERROR_HTTP_STATUS)
    missing_tier = set(ErrorCode) - set(ERROR_RETRY_TIER)
    if missing_http or missing_tier:
        raise ValueError(
            f"错误码查找表不完整：缺 HTTP 映射={sorted(missing_http)} 缺可重试级别={sorted(missing_tier)}"
        )

    # `SSE_TERMINAL_EVENTS` 必须是 `SseEvent` 的子集，且与发行点集合自洽
    unknown = SSE_TERMINAL_EVENTS - set(SseEvent)
    if unknown:
        raise ValueError(f"终止事件含未知类型：{sorted(unknown)}")

    # 发射点里的 stage 必须是合法 Stage（防"非法 stage 值"病害复发）
    illegal = [s for _, s in SSE_STAGE_EMISSION_POINTS if s is not None and s not in Stage]
    if illegal:
        raise ValueError(f"发射点含非法 stage：{illegal}")


if __name__ == "__main__":  # pragma: no cover - 手工自检入口
    validate_contract_counts()
    print(f"enums.py 契约自检通过；取值集基数 = {dict(CONTRACT_COUNTS)}")
