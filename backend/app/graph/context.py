"""每请求运行上下文（`RunContext` / `GraphDeps`）—— 节点取依赖与累积降级/计时的**唯一载体**。

层号：L4｜归属窗口：W4（`docs/08 §4.1`：`app/graph/**`）。

--------------------------------------------------------------------------
一、为什么依赖不能放进 `GraphState`（四条理由，缺一条都不足以否决它）
--------------------------------------------------------------------------
1. **`GraphState` 的字段由 07 §5.2 穷举**（`GraphState.__annotations__` 与 `STATE_GROUPS`
   必须恰好互相覆盖，`tests/contract/test_graph_state_contract.py` 钉住）——
   往里加"LLM 网关"就等于与 §5.2 的第二份真相（U-18 的教训）。
2. **依赖不可随检查点序列化**：网关里有 `httpx` 连接池、`BindingService` 里有语义包 runtime、
   `PlannerEngine` 里有降级累积列表。它们既不是业务数据，也不该被 checkpoint 写进 PG。
3. **`PlannerEngine` 必须每请求一实例**（`RELAY §给 W4` 的接线硬约束）：它内部有 `_pending`
   降级累积与"每请求"语义 —— 一旦被编译期共享，并发请求会互相串事件。
4. **两个"累积量"在 LangGraph 的覆盖语义下无法由多个节点各自追加**：
   `degradations[]` 与 `latency_ms` 都是**同一个键被多次写**的场景，而后写覆盖前写 ——
   结果不是报错，而是**静默丢掉前面几个节点的数据**。故它们必须有一个非 state 的累积器
   （本文件的 `RunContext`），由**一个**节点在收口处一次性落盘。

--------------------------------------------------------------------------
二、为什么是 `contextvars` 而不是模块级变量
--------------------------------------------------------------------------
同 `app.llm.set_call_context` 的理由：并发请求不得串号（把身份/依赖挂在全局，
在异步服务里是经典事故 —— A 请求的依赖被 B 请求用掉）。每请求一份，请求结束后 `clear`。

⚠️ `current_run_context()` 在**未设置时抛错**（fail-fast）：与 `llm.current_call_context()`
返回哨兵 `(unset)` 的做法不同，理由是本文件的缺省不会"降级可用" ——
少了依赖的节点只能编造结果，而编造结果比崩溃危险得多。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.binding import BindingService
from app.core.contracts import (
    AuditSinkPort,
    CachePort,
    ClockPort,
    IdentityContext,
    LLMPort,
    MaskPort,
    RetrievalPort,
    SemanticBundlePort,
    SqlExecutorPort,
    TokenUsage,
)
from app.core.enums import ActionTaken, DegradedReason, LatencyKey, TokenKey
from app.planner.engine import PlannerEngine

__all__ = [
    "GraphDeps",
    "RunContext",
    "clear_run_context",
    "current_run_context",
    "identity_from_state",
    "set_run_context",
]


@dataclass(frozen=True, slots=True)
class GraphDeps:
    """一次 run 的全部服务依赖（**每请求一份**，由 `app/main.py` 装配、`api` 层注入）。

    ⚠️ 字段类型一律用 `core/contracts` 的 **Port**（而不是具体类）：节点只该认识端口，
    这样"节点层没有业务逻辑"这件事才在类型层面可见（G-1）。三处例外都写了理由：
    · `planner`：端口 `PlannerPort` 只暴露两个 `Mapping -> Mapping` 的薄包装，
      节点需要 `PlanOutcome/SqlOutcome` 的**富出参**（`attempts`/`degradations`/`latency`），
      故直接持有 `PlannerEngine`（W3B 的 `RELAY §给 W4` 明确推荐这条）；
    · `retrieval`：端口只回 `candidates`，而 `link` 节点还需要 `mode`/`degraded_reason`
      （C-11 要求如实回填）→ 走 `search_full`（W2B 在 `search.py` 里注明"W4 接线用"）；
    · `binding`：`resolve_detailed` 不在端口上（`BindingResult` 装不下 `disclosure`/
      `clarify_prompt`，D4 的既定分工）→ 用 `BindingService`。
    """

    llm: LLMPort
    planner: PlannerEngine
    binding: BindingService
    semantics: SemanticBundlePort
    retrieval: RetrievalPort
    executor: SqlExecutorPort
    mask: MaskPort
    audit: AuditSinkPort
    clock: ClockPort
    #: 结果集缓存（`result:{tenant}:{task_id}`）。**唯一**允许存放结果行的位置（07 §5.2.1）。
    result_cache: CachePort | None = None
    #: `query_plan` 写入通道（W1B `QueryPlanStore`）。`None` = 未接线 → 该写入跳过并登记。
    query_plan_writer: Any | None = None
    #: `present` 生成器（chart/insight）。**P0 = `None`**：`app/present/` 仍是空壳（W3B 归属），
    #: 此时 `present` 节点走 §14.2 F4 的降级路径（`degraded(present_failed)` + `table_only`）。
    presenter: Any | None = None
    #: gate3 阈值（`CostThresholds.from_mapping` 的输入）。来源 = 语义包 `policy()`。
    #: ⚠️ 用 `default_factory` 而不是 `None` 默认值：`Mapping` 的"缺省空表"与"显式 None"
    #: 在 `from_mapping` 里行为相同，但前者不需要调用方判空（少一条可写错的分支）。
    gate3_thresholds: Mapping[str, Any] = field(default_factory=dict)
    max_rows: int = 1000
    statement_timeout_ms: int = 8_000
    #: ADR-11 的 N 路 SQL 候选数（P0 = 1）。
    sql_candidates: int = 1
    #: 是否走"合并档"（07 §16.1 手段 1：`normalize` + `intent` 合并为一次 LLM 调用）。
    #: **默认 `True`** —— 该手段在 §16.1 的状态栏是 ✅ 已落地，且"不合并"的路径不满足
    #: 8s P95。留开关是因为 §16.1 DoD① 要**实测**"合并省了多少"，没有单跑路径就无从测量。
    merged_understand: bool = True


class RunContext:
    """一次 run 的可变状态：**服务依赖** + **降级累积** + **分项计时** + **体积数据中转**。

    ⚠️ 体积数据中转（`hold_rows`/`take_rows`）是刻意的：结果行**不进** `GraphState`
    （07 §5.2.1 的体积规则），但 `execute` 与 `mask` 是两个节点 —— 未脱敏的行不能进 Redis
    （N-05），也不能进检查点，只能经这条**内存**通道从前者交到后者。
    它是**单次赋值**语义（`take_rows` 取走即清空），不构成"第二个数据通道"。
    """

    __slots__ = (
        "_cost",
        "_degradations",
        "_disclosure",
        "_latency",
        "_mask_hits",
        "_monotonic",
        "_pending_columns",
        "_pending_rows",
        "_recorder",
        "_started",
        "_tokens",
        "bundle_version",
        "deps",
        "scope",
    )

    def __init__(
        self,
        deps: GraphDeps,
        *,
        recorder: Any | None = None,
        monotonic: Any | None = None,
    ) -> None:
        self.deps = deps
        #: 事件发射器（`graph.events.EventRecorder`）。**`None` = 无 SSE 出口**（离线/测试）：
        #: 此时降级只进 `degradations`（state/审计仍有到），这是"如实少一条通道"而非静默丢弃。
        self._recorder = recorder
        self._monotonic = monotonic or time.perf_counter
        self._started = self._monotonic()
        self._degradations: list[dict[str, Any]] = []
        self._latency: dict[str, int] = {}
        self._pending_rows: tuple[tuple[Any, ...], ...] | None = None
        self._pending_columns: tuple[tuple[str, float], ...] | None = None
        self._mask_hits: tuple[str, ...] | None = None
        self._tokens = TokenUsage()
        self._cost: Decimal = Decimal(0)
        self._disclosure: str | None = None
        #: 语义包版本 —— 由 `trusted_context` 写一次。`GraphState` **没有**该字段，
        #: 而 `meta.bundle_version` 是必填（07 §5.6）→ 它只能挂在这里（见 `events.meta_payload`）。
        self.bundle_version: str = ""
        #: gate2 算出的 `ScopeInfo` —— `gate2_policy` 写入，`present` 落进 `meta.scope`。
        #: state 组 7 也有 `scope`，两处并存不是重复：state 侧供审计（组 7），
        #: 本处供"出口节点在没走 gate2 的路径上也能给 meta 一个缺省语义"（C-07）。
        self.scope: Any | None = None

    # -- 计量（C-03 / C-04 的累积面） ----------------------------------------

    def record_usage(self, usage: TokenUsage, cost: Decimal) -> None:
        """累加一次 LLM 调用的 token 与成本（多次调用相加，与 `LlmCallMeta.merged_with` 同口径）。"""
        self._tokens = TokenUsage(
            input=self._tokens.input + usage.input,
            output=self._tokens.output + usage.output,
            cache_hit=self._tokens.cache_hit + usage.cache_hit,
            total=self._tokens.total + usage.total,
        )
        self._cost += cost

    def tokens_payload(self) -> dict[str, int]:
        """`meta.tokens` 的形状（C-03 的 4 键，逐字）。"""
        return {
            TokenKey.INPUT.value: self._tokens.input,
            TokenKey.OUTPUT.value: self._tokens.output,
            TokenKey.CACHE_HIT.value: self._tokens.cache_hit,
            TokenKey.TOTAL.value: self._tokens.total,
        }

    def cost_cny(self) -> Decimal:
        return self._cost

    # -- 降级（唯一上报入口） ------------------------------------------------

    def report_degraded(
        self,
        reason: DegradedReason,
        action_taken: ActionTaken,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """记一次降级并（若有出口则）发事件 —— **节点不得直接碰发射器**。

        `detail` 只进日志/审计（`RunContext.note` 的既有口径），**不进 SSE 帧**：
        C-08 的 `degraded.data` 是 `{reason, action_taken, partial_result?}`，
        往里塞无界的诊断字段等于把契约面变成日志面。
        """
        self.note(reason, action_taken, detail)
        if self._recorder is not None:
            self._recorder.degraded(reason=reason, action_taken=action_taken)

    def note(
        self,
        reason: DegradedReason,
        action_taken: ActionTaken,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """只记不发（给"侧信道已经发过事件"的场景用，避免同一跳双发）。"""
        entry: dict[str, Any] = {
            "reason": str(reason),
            "action_taken": str(action_taken),
        }
        if detail:
            entry["detail"] = dict(detail)
        self._degradations.append(entry)

    def degradations(self) -> tuple[dict[str, Any], ...]:
        """累积的降级项（落 `GraphState.degradations`，组 10）。"""
        return tuple(self._degradations)

    # -- 体积/无位数据中转（不进检查点、不进 state） --------------------------

    def hold_rows(self, rows: Sequence[Sequence[Any]]) -> None:
        self._pending_rows = tuple(tuple(row) for row in rows)

    def take_rows(self) -> tuple[tuple[Any, ...], ...]:
        rows = self._pending_rows or ()
        self._pending_rows = None
        return rows

    def hold_columns(self, columns: Sequence[tuple[str, float]]) -> None:
        """列级候选（ref 形状 `资产.列`）移交 `bind` 的在线 L4 打分。

        ⚠️ 为什么它也要中转：`GraphState` 组 4 的 `candidates` 是**资产级 Top-5**
        （`RetrievalResult` 的注释如此），而在线 L4 打的是字段级候选；07 §5.2 的
        字段表里没有列级候选的键（穷举，不得为传值新增）⇒ 与结果行同款的内存通道。
        """
        self._pending_columns = tuple((str(ref), float(score)) for ref, score in columns)

    def take_columns(self) -> tuple[tuple[str, float], ...]:
        columns = self._pending_columns or ()
        self._pending_columns = None
        return columns

    def hold_mask_hits(self, columns: Sequence[str]) -> None:
        """`mask` 命中的敏感列名 → `audit_pre`（段 1 的 `pii_columns_hit`）。

        ⚠️ 为什么不能从 `ResultSet` 拿：`ResultSet` 的五个字段里**没有** `hit_columns`
        （`MaskOutcome` 有，但 executor 在 `_execute_and_collect` 里就把 `outcome.rows`
        取走了，`hit_columns` 没有出口）⇒ `mask` 节点重新算一次并从这里交给 `audit_pre`。
        只记**列名**，不记值（`MaskOutcome` 的既定口径）。
        """
        self._mask_hits = tuple(str(name) for name in columns)

    def take_mask_hits(self) -> tuple[str, ...]:
        hits = self._mask_hits or ()
        self._mask_hits = None
        return hits

    def hold_disclosure(self, text: str | None) -> None:
        """U-26 的 `resolved_default` 披露文案 —— **端口与 state 都没有它的位置**。

        `BindingResult` 是三字段（D4 的既定分工），`GraphState` 组 5 也没有该键
        （07 §5.2 穷举，不得为传值新增）。它唯一的合法载体是 `insight.caveats[]`，
        而 `bind` 与 `present` 之间隔着 11 个节点 ⇒ 与结果行同款的内存中转。
        """
        self._disclosure = text

    def take_disclosure(self) -> str | None:
        text = self._disclosure
        self._disclosure = None
        return text

    # -- 计时 ---------------------------------------------------------------

    def elapsed_ms(self) -> int:
        return int((self._monotonic() - self._started) * 1000)

    def record_latency(self, key: LatencyKey, ms: int) -> None:
        """写一个分项耗时（键集 = `LatencyKey` 的 8 个，与审计同源）。

        ⚠️ **同键累加**而不是覆盖：`plan`/`gen_sql` 可能因 `repair` 跑两轮，
        只保留最后一轮会让"这一轮花了多久"偏小 —— 而它正是延迟预算的判据。
        """
        self._latency[key.value] = self._latency.get(key.value, 0) + int(ms)

    def latency_ms(self) -> dict[str, int]:
        """落 `GraphState.latency_ms` 的形状：8 个分项 + `total`。

        ⚠️ `total` 由本函数补齐（不是各节点之和的近似 —— 直接取 run 起点到收口的墙钟），
        两者不同是**正常的**：分项不含图调度与 I/O 等待（07 C-04 已注明这类差异）。
        """
        snapshot = dict(self._latency)
        snapshot[LatencyKey.TOTAL.value] = self.elapsed_ms()
        return snapshot


# ============================================================================
# 请求级绑定
# ============================================================================

_RUN_CONTEXT: ContextVar[RunContext | None] = ContextVar("graph_run_context", default=None)


def set_run_context(context: RunContext) -> Token[RunContext | None]:
    """由 API 层在**进图前**调用，`finally` 里用返回的 token 还原（见 `clear_run_context`）。"""
    return _RUN_CONTEXT.set(context)


def clear_run_context(token: Token[RunContext | None]) -> None:
    """还原到进入前的上下文（**必须**在 `finally` 里调，否则长生命周期 worker 会残留）。"""
    _RUN_CONTEXT.reset(token)


def current_run_context() -> RunContext:
    """取当前请求的上下文。**未设置即抛**（见模块 docstring §二 的 fail-fast 理由）。"""
    context = _RUN_CONTEXT.get()
    if context is None:
        raise RuntimeError(
            "节点在未设置 RunContext 的情况下被调用 —— 说明 API 层忘了 `set_run_context(...)`。"
            "此时节点拿不到任何依赖，只能编造结果；那比直接报错危险得多（fail-fast 是刻意的）。"
        )
    return context


def identity_from_state(state: Mapping[str, Any]) -> IdentityContext:
    """`GraphState` 组 1 的扁平字段 → `IdentityContext`（**唯一的逆向转换点**）。

    `graph/state.py::identity_fields()` 是正向（身份 → state）的唯一转换点；
    逆向没有对应函数，而**每个需要调用服务的节点**都要一个 `IdentityContext`
    —— 若各处手写 `IdentityContext(tenant_id=state["tenant_id"], ...)`，
    就等于把"身份有哪些字段"写了 N 遍，漏抄一个键的表现是"某个节点拿不到租户"
    （跨租户场景下这是**安全**问题）。故集中在此，与 `identity_fields()` 成对。

    ⚠️ `raw_question` / `options` / `idempotency_key` **不属于身份**（不在此转换）：
    它们是请求体，由 API 层写入 state（07 §13.1 禁令 1/2：身份不得由客户端影响）。
    """
    return IdentityContext(
        trace_id=str(state["trace_id"]),
        task_id=str(state["task_id"]),
        session_id=str(state["session_id"]),
        tenant_id=str(state["tenant_id"]),
        user_id=str(state["user_id"]),
        role=state["role"],
        scope_claims=tuple(state.get("scope_claims") or ()),
        shop_ids=tuple(state.get("shop_ids") or ()),
    )
