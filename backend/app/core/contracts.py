"""跨模块端口（Protocol）与共享值对象 —— 单一真相文件 #2 / 3。

归属窗口：W0（docs/08 §4.1）。**所有窗口都 import 本文件，不得各自另立一套签名。**

它解决的是 07 §3.1 **R-DEP-1** 那条硬规则：
> 模块**只能**依赖严格更低层的模块；**同层调用必须走显式 `ports` 接口**。

没有这个文件，"同层调用"就只剩口头纪律 —— 而纪律在多人/多窗口协作里等于不存在。

契约纪律（本文件必须始终满足）：
1. **只放 `typing.Protocol` + `frozen dataclass` 值对象**，不含任何实现；
2. **只能 import `app.core` 之下、层级更低的模块**（当前仅 `app.core.enums` / `app.core.errors`）；
   **不得 import `app.llm` 等任何 L1+ 模块**，也不得 import pydantic
   （DTO 归 `app/api/dto/`；本文件是 L0，引入第三方序列化库会把 L0 变成有依赖的层）；
3. 只写**签名级**抽象（07 §0.3：本 TDD 的抽象层级止于签名与契约）；
4. 方法命名与 `07 附-1 模块职责清单` 对齐；若需偏离，须登记 `U-xx` 而不是就地改名。

未纳入本文件的端口（**故意不写，避免过早冻结**）：
- 评测执行器（`eval/`）：ADR-18 要求它**直接复用**在线 `guard` / `exec` 代码路径，**不走端口**；
- 具体端点的请求体/响应体：那是 `app/api/dto/`（OpenAPI 生成源），不是端口。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from app.core.enums import (
    BindingLayer,
    BindingState,
    Dependency,
    DependencyKind,
    GateDecision,
    GateNo,
    LatencyKey,
    RateLimitBucket,
    RetrievalMode,
    Role,
    ScopeLevel,
    SseEvent,
    Stage,
)
from app.core.errors import CommerceQLError

__all__ = [
    # 值对象
    "IdentityContext", "TimeSemantics", "ColumnMeta", "ResultSet", "GateResult",
    "ScopeInfo", "TokenUsage", "LatencyBreakdown", "LLMResponse",
    "RateLimitDecision", "MaskOutcome", "BindingResult", "CandidateRef", "HealthProbeResult",
    # 端口
    "ClockPort", "TokenizerPort", "LLMPort", "SemanticBundlePort", "RepositoryPort",
    "AuditSinkPort", "SessionLockPort", "RateLimiterPort", "CachePort",
    "SqlExecutorPort", "MaskPort", "RetrievalPort", "BindingPort", "PlannerPort",
    "GuardPort", "EventEmitterPort", "ErrorMapperPort", "DependencyProbePort",
]


# ============================================================================
# 一、共享值对象（frozen dataclass；**不可变**是契约的一部分）
# ============================================================================

@dataclass(frozen=True, slots=True)
class IdentityContext:
    """可信身份上下文 —— 由 JWT 构造，**进图之后只读**（07 §5.2 组 1 / §13.1）。

    ⚠️ 铁律：`role` / `shop_ids` / `tenant_id` **一律来自服务端**，
    **绝不接受客户端传入**（07 §13.1 第 2 条；违反 = 越权）。
    ⚠️ `tenant_id` / `user_id` 是 **PII**：**禁止出站到 LLM**（N-12），进日志受审计要求约束。
    """

    trace_id: str
    task_id: str
    session_id: str
    tenant_id: str
    user_id: str
    role: Role
    scope_claims: tuple[str, ...] = ()
    shop_ids: tuple[str, ...] = ()  # 空 = 不限制（07 §13.2 关键约束①：行级范围只有这一个维度）


@dataclass(frozen=True, slots=True)
class TimeSemantics:
    """时间口径 —— **只能来自语义包**，禁止代码硬编码（N-26 / FR-1.2 / FR-1.3）。

    由 `SemanticBundlePort.time_semantics()` 注入 `ClockPort` 的上下文。
    """

    timezone: str                     # IANA，P0 固定 Asia/Shanghai（PRD 假设 A-2）
    fiscal_year_start_month: int      # 附录 B `meta.fiscal_year_start_month`
    week_starts_on: str               # 附录 B `meta.week_starts_on`


@dataclass(frozen=True, slots=True)
class ColumnMeta:
    """结果集列元数据（07 §5.2 组 8 `result_columns`）。"""

    name: str
    type_name: str          # 类型归一化后的 name（07 §8.4）
    unit: str | None = None  # 金额类必须标注单位（附录 A §A.10 约束）


@dataclass(frozen=True, slots=True)
class ResultSet:
    """执行结果（**已完成脱敏** —— N-05：离开 `exec` 前必须脱敏）。

    ⚠️ `rows` **不进检查点**（体积规则，07 §5.2.1）→ 只存 Redis `result:{tenant}:{task_id}`。
    ⚠️ `truncated` **只允许由 LIMIT 触发**；RLS 过滤**不得**置 true（N-06 / FR-8.9）。
    """

    columns: tuple[ColumnMeta, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool
    fingerprint: str        # 结果集哈希（缓存/去重），07 §8.8


@dataclass(frozen=True, slots=True)
class GateResult:
    """单道闸门的判定对象（**纯函数出参**，N-03）。

    ⚠️ `rule_id` 必须进 `gate_detail`（C-02）—— 否则闸门拒绝无法归因、无法统计（PRD §14.2）。
    ⚠️ `decision` 为 `SKIPPED` 时**不得报告为通过**（07 §14.2 D6）。
    """

    gate_no: GateNo
    passed: bool
    decision: GateDecision
    rule_id: str | None = None
    reason: str | None = None
    estimated_rows: int | None = None
    estimated_cost: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    """`meta.scope` —— 三级披露（附录 A §A.1.5）。

    ⚠️ 缺省语义见 C-07：字段缺失视为 `unrestricted` / `applied=False` / `disclosable=True`，
    **不改变披露策略**（向后兼容）。
    """

    level: ScopeLevel
    applied: bool
    notice: str | None
    disclosable: bool


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """`meta.tokens`（C-03）。"""

    input: int = 0
    output: int = 0
    cache_hit: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class LatencyBreakdown:
    """`meta.latency_ms`（C-04）—— 键集必须与 PRD §9.2 `audit_log.latency_ms` 完全一致。"""

    values: Mapping[LatencyKey, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """LLM 网关出参。**必须携带版本字段**，否则无法满足 N-19。"""

    text: str
    model: str
    prompt_version: str
    tokens: TokenUsage
    cost_cny: Decimal


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """限流判定（附录 A §A.0.6 / 07 §9.2）。

    ⚠️ 本对象只服务 `429`；**会话串行冲突不是限流**（走 `409 SESSION_CONFLICT`）。
    """

    allowed: bool
    bucket: RateLimitBucket
    retry_after_s: int | None = None


@dataclass(frozen=True, slots=True)
class MaskOutcome:
    """脱敏结果。`hit_columns` 为命中的列名（**只记列名，不记值**）。"""

    rows: tuple[tuple[Any, ...], ...]
    hit_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateRef:
    """检索候选的**摘要引用** —— 进检查点的只有 id + score（07 §5.2.1 体积规则）。"""

    asset_id: str
    score: float
    layer: BindingLayer | None = None


@dataclass(frozen=True, slots=True)
class BindingResult:
    """字段绑定四层判定结果（07 §6.8 / 附-1）。

    ⚠️ `state` 与 `layer` **必须双双落库**（07 §12.3）：
    只落一个 → 澄清率异常时无法定位是哪一层失效。
    """

    state: BindingState
    layer: BindingLayer
    bindings: tuple[CandidateRef, ...] = ()


@dataclass(frozen=True, slots=True)
class HealthProbeResult:
    """单个依赖探针结果（附录 A §A.8.1）。

    ⚠️ `kind` 由 `app.core.enums.DEPENDENCY_KIND` 单一定义 —— 软依赖（LLM / embedding）
    **不计入 readiness**（N-21），这不是实现细节，是契约。
    """

    dependency: Dependency
    kind: DependencyKind
    healthy: bool
    detail: str | None = None


# ============================================================================
# 二、端口（Protocol）—— 同层调用必须经此，不得直接 import 同层模块（R-DEP-1）
# ============================================================================

@runtime_checkable
class ClockPort(Protocol):
    """唯一时间来源（N-18）。

    ⚠️ 实现方内**禁止**直接调 `datetime.now()` / `time.time()` —— 静态检查会拦。
    时间口径字段**不得**在实现里硬编码，只能来自 `TimeSemantics`（N-26）。
    """

    def now(self) -> datetime: ...
    def today(self) -> date: ...
    def tz(self) -> ZoneInfo: ...
    def semantics(self) -> TimeSemantics: ...


@runtime_checkable
class TokenizerPort(Protocol):
    """中文分词 —— **写入侧（物化 `tsvector`）与查询侧的唯一同源入口**（N-24 / ADR-07）。

    🔴 **端口落位理由（阶段 0 必须裁决的事，否则必然出现第四、第五个"真相"）**：
    - 规则要求两侧同源；
    - 但规则里写的唯一入口 `retrieval/tokenizer.py` 在 **L3**，而写入侧 `semantics` 在 **L1**；
    - L1 **不得** import L3（R-DEP-1）→ 若把实现留在 L3，`semantics` 只能自己再调一次 jieba。
    → **端口定义在 L0 本文件，实现在 L0/L1，`retrieval` 侧只 import 本端口。**
    检查方式：同一文本经两条路径产出的 `tsvector` **完全相等**（附录 D 检查项 18）。
    """

    def tokenize(self, text: str) -> list[str]: ...


@runtime_checkable
class LLMPort(Protocol):
    """LLM 网关（L1；`app.llm` 实现）。

    ⚠️ **L2 及以下与 `binding` 禁止 import 本端口的实现模块**（N-01 / R-DEP-2），
    本端口本身只用于 L3 及以上（`planner` / `retrieval.refine` / `present`）。
    实现必须：按模型 `asyncio.Semaphore`（**并发非 QPS**）、退避/熔断/预算熔断、
    出站白名单断言（N-12）、`prompt_version` 必录（N-19）。
    """

    async def call(self, task: str, payload: Mapping[str, Any], model: str) -> LLMResponse: ...
    def estimate_cost(self, payload: Mapping[str, Any]) -> Decimal: ...


@runtime_checkable
class SemanticBundlePort(Protocol):
    """语义层运行时（L1；`app.semantics` 实现）。签名对齐 07 附-1。"""

    def active_version(self) -> str: ...
    def asset_allowlist(self, ctx: IdentityContext) -> Mapping[str, Any]: ...
    def time_semantics(self) -> TimeSemantics: ...
    def policy(self) -> Mapping[str, Any]: ...


@runtime_checkable
class RepositoryPort(Protocol):
    """元数据持久化（L0；`app.repo` 实现）。

    ⚠️ `app.api` **禁止直连本实现**（07 附-1）—— 端点只能经端口访问。
    ⚠️ 分析连接（`app_ro`）**不经本端口**：它只由 `SqlExecutorPort` 获取（ADR-09）。
    """

    async def create_session(self, ctx: IdentityContext, title: str) -> str: ...
    async def get_session(self, ctx: IdentityContext, session_id: str) -> Mapping[str, Any] | None: ...
    async def save_task(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None: ...


@runtime_checkable
class AuditSinkPort(Protocol):
    """审计写入 —— **两段式**（07 §12.4 四重保证 / N-09）。

    语义是**不可协商**的：
    - `write_pre` 失败 ⇒ **不得下发 `data`**（fail-closed，`error(INTERNAL)` + P0 告警）；
    - `write_supp` 失败 ⇒ **不阻断**（已经下发过结果了），只告警（07 §14.2 G2）。
    ⚠️ 审计段 2 的 `write_supp` **必须**覆盖"客户端取消/断连"（07 §14.2 E7、§18.3 步 5）。
    """

    async def write_pre(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None: ...
    async def write_supp(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None: ...


@runtime_checkable
class SessionLockPort(Protocol):
    """会话串行锁（FR-10.5 / ADR-13）。

    ⚠️ 获取位置**只在 api 层、进图之前**（07 §9.3）—— 在节点内获取会因检查点恢复重复获取 → **自死锁**。
    ⚠️ 等待超时后**必须**返回 `409 SESSION_CONFLICT`（**不是 429**），且**不返回** `X-RateLimit-*`。
    实现失败时抛 `app.core.errors.SessionLockConflict`。
    """

    async def acquire(self, ctx: IdentityContext, *, ttl_s: int, wait_ms: int) -> str: ...
    async def renew(self, key: str, holder: str, *, ttl_s: int) -> bool: ...
    async def release(self, key: str, holder: str) -> None: ...


@runtime_checkable
class RateLimiterPort(Protocol):
    """分桶限流（附录 A §A.0.6 / 07 §9.2）。实现须用 Lua 保证原子性。"""

    async def check(self, bucket: RateLimitBucket, ctx: IdentityContext) -> RateLimitDecision: ...


@runtime_checkable
class CachePort(Protocol):
    """缓存存取（L2；`app.cache` 实现）。

    ⚠️ 键**只能**由 `app/cache/keys.py` 构造（§11.2 硬规则 3：禁止裸字符串拼键）。
    ⚠️ `single_flight` 是防击穿的**唯一**实现位置（§11.4），不要在调用方各写一把锁。
    """

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, ttl_s: int) -> None: ...
    async def delete(self, key: str) -> None: ...

    async def single_flight(
        self, key: str, loader: Callable[[], Awaitable[str]], *, ttl_s: int
    ) -> str: ...


@runtime_checkable
class SqlExecutorPort(Protocol):
    """受控执行（L2；`app.exec` 实现）。**分析连接的唯一出口**（N-02）。

    ⚠️ 实现在返回前**必须**完成类型归一化与脱敏交接（N-05 / 07 §8.4）。
    ⚠️ 资源上限（默认内存 512MB）被突破 → 抛 `EXEC_RESOURCE_EXCEEDED`，
    **不是** `COST_TOO_HIGH`（后者是预执行 gate3，层级不同，不得合并 —— 附录 A §A.11 补充约定）。
    """

    async def fetch(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        statement_timeout_ms: int,
    ) -> ResultSet: ...


@runtime_checkable
class MaskPort(Protocol):
    """脱敏引擎（L2；`app.mask` 实现）。

    ⚠️ `deny` 与 `mask` 是**两套语义**（07 §8.7）：`deny` = 列根本不出现；`mask` = 出现但值被替换。
    """

    def apply(self, rows: Sequence[Sequence[Any]], policy: Mapping[str, Any]) -> MaskOutcome: ...


@runtime_checkable
class RetrievalPort(Protocol):
    """四路检索（L3；`app.retrieval` 实现）。签名对齐 07 附-1。

    ⚠️ `mode` 必须如实回填进 `meta.retrieval_mode`（C-11）——
    稠密不可用时前端/审计需要**随时**能判定本轮检索质量，只有 `degraded` 事件不够。
    """

    async def search(
        self, question: str, ctx: IdentityContext, mode: RetrievalMode
    ) -> tuple[CandidateRef, ...]: ...


@runtime_checkable
class BindingPort(Protocol):
    """字段绑定解析器（L2；`app.binding` 实现）。

    🔴 **结构上禁 LLM**（FR-3.2）：不得 import `app.llm`（R-DEP-2 由 CI 强制）。
    ⚠️ fail-safe：解析失败 / 分差落在 τ 邻域 → **必判 `ambiguous`**，不得默认猜 `resolved_unique`（N-27）。
    ⚠️ 只接受 `RerankScore` 类型，**不接受裸 `float`**（N-27 检查方式①）。
    """

    def resolve(
        self, concept: str, ctx: IdentityContext, candidates: Sequence[CandidateRef]
    ) -> BindingResult: ...


@runtime_checkable
class PlannerPort(Protocol):
    """理解与生成（L3；`app.planner` 实现）。

    ⚠️ 计划摘要 `plan_summary` **只放摘要，不含 SQL**（C-01 呼应 FR-10.1）；
    ⚠️ 生成出的 `sql_text` **永不回灌 prompt**（N-17）。
    """

    async def build_plan(
        self, question: str, candidates: Sequence[CandidateRef], ctx: IdentityContext
    ) -> Mapping[str, Any]: ...

    async def generate_sql(
        self, plan: Mapping[str, Any], ctx: IdentityContext, *, candidates: int
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class GuardPort(Protocol):
    """三道闸门（L2；`app.guard` 实现）。

    🔴 **顺序不可变、不可跳过；三道都是纯函数**（N-03）。
    ⚠️ 拒绝文案**不得泄露表名**（07 §7.6）。
    """

    def gate1(self, sql: str, allowlist: Mapping[str, Any]) -> GateResult: ...
    def gate2(
        self, sql: str, ctx: IdentityContext, bundle: SemanticBundlePort
    ) -> tuple[GateResult, ScopeInfo]: ...
    def gate3(self, sql: str, thresholds: Mapping[str, Any]) -> GateResult: ...


@runtime_checkable
class EventEmitterPort(Protocol):
    """SSE 事件发射（L4；`app.graph.events` 实现 —— **唯一产出点**）。

    ⚠️ 节点**不得**自己拼事件帧（§5.6）：`stage` 取值漂移是历史病害。
    ⚠️ 实现必须维护 `terminal_emitted` 标志：终止事件之后再发任何事件（心跳除外）
    → **丢弃 + `ui_contract_violation` 告警**（N-08 的机制，不是纪律）。
    """

    def emit(self, event: SseEvent, data: Mapping[str, Any], *, stage: Stage | None = None) -> None: ...


@runtime_checkable
class ErrorMapperPort(Protocol):
    """异常 → 错误码的**唯一映射点**（L5；`app/api/errors` 实现）。

    ⚠️ 一张表答完四件事：`code` / HTTP 状态 / `retryable`（三级）/ 是否带 `Retry-After`（C-09）。
    """

    def to_http(self, exc: CommerceQLError) -> tuple[str, int, bool]: ...


@runtime_checkable
class DependencyProbePort(Protocol):
    """依赖健康探针（附录 A §A.8.1）。

    ⚠️ **软依赖（LLM / embedding）不得计入 readiness**（N-21）：
    把它们塞进 readiness 等于**让"降级"变成"不可用"**。
    """

    async def probe(self) -> HealthProbeResult: ...
