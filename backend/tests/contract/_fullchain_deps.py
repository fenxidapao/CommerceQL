"""07 §14.2 决策表 **B–G 组**的全链脚本依赖 —— `tests/contract` 内部夹具（非测试文件）。

为什么 A 组不需要它而 B–G 需要：A 组 6 行全部在 `understand` 一跳内出结论
（`test_decision_table_contract.py` 的 `_APlanner` 只有一个方法）；B–G 要触达
`link → bind → plan → gen_sql → 三闸门 → execute → repair → mask → audit_pre →
present → audit_supp` 的深层链路 ⇒ 九个依赖全部脚本化。

三条设计纪律（沿 `test_graph_wiring.py` / `test_api_runner_contract.py` 的先例）：

1. **未预期的调用当场炸**：假件只实现节点实际会调的方法，多调一个 = 接线漂移；
2. **脚本按序消费、用尽重复末位**（末位 = 稳定态；精确次数由 `*_calls` 计数器断言）；
3. **SQL 一律字面量**：psycopg 风格 `%(name)s` 占位符 sqlglot 解析不了（gate1 直接拒），
   `params` 恒 `{}`；WHERE 里的数据值（`region_code = 440000`）属 R14 的
   "列-常量比较值位"，放行（红队集 RT-R17-* 的既定口径）。

**allowlist 两跳（D3 的机制）**：`gate1_ast` 节点与 `run_gate2` **各自**调
`asset_allowlist`（刻意的二次校验，见 `gate1_ast.py` docstring §二）⇒
`FullChainSemantics` 按调用序消费 `allowlists` 列表：第 1 份给 gate1、第 2 份给 gate2。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.api.runner import RunOutcome, RunRequest, SseRunner
from app.api.state_store import RedisStateStore
from app.binding.filters import FilterOutcome
from app.binding.four_layer import LayerDecision
from app.binding.service import BindingOutcome
from app.core.contracts import (
    BindingResult,
    CandidateRef,
    ColumnMeta,
    IdentityContext,
    MaskOutcome,
    ResultSet,
    TokenUsage,
)
from app.core.enums import (
    ActionTaken,
    BindingLayer,
    BindingState,
    DegradedReason,
    RetrievalMode,
)
from app.exec.errors import ExecError, ExecFailure
from app.graph.build import build_graph
from app.graph.context import GraphDeps
from app.mask import MaskFailed
from app.planner.engine import LlmCallMeta, PlanOutcome, SqlOutcome, UnderstandOutcome
from app.planner.schemas import IntentKind, Plan, PlanMetric, SqlCandidate
from app.retrieval.search import RetrievalResult
from tests.contract.test_api_runner_contract import _IDENTITY, _parse
from tests.unit._redis_fake import FakeRedis

__all__ = [
    "BUNDLE_VERSION",
    "Chain",
    "GREEN_EXPLAIN",
    "GREEN_RESULT",
    "GREEN_SQL",
    "QUESTION",
    "RecordingAudit",
    "FullChainPlanner",
    "FullChainSemantics",
    "ScriptBinding",
    "ScriptExecutor",
    "ScriptMask",
    "ScriptRetrieval",
    "base_allowlist",
    "make_chain",
    "run_chain",
    "terminal_frames",
]


# ============================================================================
# 常量与绿灯产物
# ============================================================================

#: 语义包版本（`FullChainSemantics.active_version` 与 allowlist 的 `bundle_version` 同值）。
BUNDLE_VERSION = "v-dt-0001"

#: 默认问句（与 A 组一致，保证跨文件可比）。
QUESTION = "上个月卖得怎么样"

#: 绿灯 SQL：单表、白名单列、列-常量比较（R14 值位）、LIMIT 100 ≤ L(=min(1000,10000))。
GREEN_SQL = "SELECT order_id, amount FROM fact_orders WHERE region_code = 440000 LIMIT 100"

#: 绿灯 EXPLAIN 计划（Total Cost 100 ≪ pass 阈值 50000 → gate3 PASS）。
GREEN_EXPLAIN: dict[str, Any] = {
    "Plan": {"Total Cost": 100, "Plan Rows": 10, "Node Type": "Seq Scan"}
}

#: 绿灯结果集（executor 首跳返回；`amount` 带单位，附录 A §A.10）。
GREEN_RESULT = ResultSet(
    columns=(
        ColumnMeta(name="order_id", type_name="bigint"),
        ColumnMeta(name="amount", type_name="numeric", unit="CNY"),
    ),
    rows=((1, Decimal("99.00")),),
    row_count=1,
    truncated=False,
    fingerprint="fp-dt-1",
)

_META = LlmCallMeta(
    model="deepseek-chat",
    prompt_version="pv-dt",
    tokens=TokenUsage(input=10, output=5, cache_hit=0, total=15),
    cost_cny=Decimal("0.0001"),
)

#: 绿灯计划（校验器"metrics 或 blocking_issues 至少其一"—— 有 metrics 即过）。
_PLAN = Plan(metrics=[PlanMetric(name="amount")])


def _green_understand(question: str) -> UnderstandOutcome:
    """`intent=executable` 的合并档产出（B–G 全链的默认第一跳）。"""
    return UnderstandOutcome(
        merged=True,
        normalized_question=question,
        intent=IntentKind.EXECUTABLE,
        refuse_kind=None,
        reason_code="decision_table",
        clarify_hint=None,
        confidence=0.9,
        time_range=None,
        time_parse_ok=True,
        time_reason=None,
        resolved_terms=(),
        unresolved_terms=(),
        injection={},
        meta=_META,
        attempts=1,
        latency_ms=1,
    )


# ============================================================================
# allowlist（gate1 / gate2 的全部判据；形状逐字对齐 ast_gate 模块 docstring）
# ============================================================================


def base_allowlist() -> dict[str, Any]:
    """干净基线：两张白名单表、无 deny、无谓词、无白名单常量。

    `fact_orders` 带 `buyer_phone`（敏感列）但**不在 deny_columns** —— 单一 allowlist
    下它可被查出（D3 需要 gate2 的第二份 allowlist 才会拦它）。

    U-121 双面：`columns` = 可见面、`all_columns` = 结构面（全列）。本基线无
    deny ⇒ 两面同内容，但**键必须都在**（gate2 ⑤ 读 `all_columns`，缺键 =
    `tenant_scoped` 双向断言误抛，`policy_gate.py` 落地后的实测红）。
    """

    assets = {
        "fact_orders": {
            "logical_name": "order_paid",
            "domain": "sales",
            "tenant_scoped": True,
            "columns": {
                "order_id": "bigint",
                "tenant_id": "text",
                "amount": "numeric",
                "region_code": "bigint",
                "buyer_phone": "text",
            },
        },
        "dim_region": {
            "logical_name": "region",
            "domain": "geography",
            "tenant_scoped": False,
            "columns": {"region_code": "bigint", "region_name": "text"},
        },
    }
    for asset in assets.values():
        asset["all_columns"] = dict(asset["columns"])
    return {
        "bundle_version": BUNDLE_VERSION,
        "assets": assets,
        "joins": [],
        "deny_columns": [],
        "default_predicates": {},
        "allowed_constants": [],
        "max_rows": 1000,
    }


# ============================================================================
# 假件（每个只实现节点实际会调的方法面）
# ============================================================================


class FullChainSemantics:
    """三方法语义包：`active_version` / `asset_allowlist`（按调用序消费）/ `policy`。

    `asset_allowlist` 的调用序（默认单份 allowlist 时无感知）：
    gate1 第 1 次 → gate2 第 2 次。D3 传两份：干净版给 gate1、带 deny 版给 gate2。
    """

    def __init__(self, allowlists: Sequence[Mapping[str, Any]] | None = None) -> None:
        self._allowlists: list[Mapping[str, Any]] = (
            list(allowlists) if allowlists else [base_allowlist()]
        )
        self.allowlist_calls = 0

    def active_version(self) -> str:
        return BUNDLE_VERSION

    def asset_allowlist(self, ctx: IdentityContext) -> Mapping[str, Any]:
        idx = min(self.allowlist_calls, len(self._allowlists) - 1)
        self.allowlist_calls += 1
        return self._allowlists[idx]

    def guard_allowlist(
        self, ctx: IdentityContext, *, max_rows: int | None = None
    ) -> Mapping[str, Any]:
        """闸门形状（U-121）：与 `asset_allowlist` **共用调用序** —— gate1 第 1 次、gate2 第 2 次。"""
        allowlist = dict(self.asset_allowlist(ctx))
        allowlist["max_rows"] = max_rows
        return allowlist

    def policy(self) -> Mapping[str, Any]:
        """mask 的 policy 来源 —— 空表 = 无 mask_rules（脱敏恒直通）。"""
        return {}


class ScriptRetrieval:
    """`link.search_full` 的脚本件。默认给 1 个资产候选、无列级候选（绕过在线 L4）。"""

    def __init__(
        self,
        *,
        candidates: Sequence[CandidateRef] = (CandidateRef(asset_id="fact_orders", score=0.9),),
        mode: RetrievalMode = RetrievalMode.HYBRID,
        degraded_reason: DegradedReason | None = None,
        action_taken: ActionTaken | None = None,
    ) -> None:
        self._candidates = tuple(candidates)
        self._mode = mode
        self._degraded_reason = degraded_reason
        self._action_taken = action_taken
        self.calls = 0

    async def search_full(
        self, question: str, identity: IdentityContext, mode: RetrievalMode
    ) -> RetrievalResult:
        self.calls += 1
        return RetrievalResult(
            mode=self._mode,
            candidates=self._candidates,
            # 列级候选留空 ⇒ bind 的在线 L4 不调模型（`bind._online_l4` 的空短路）。
            columns=(),
            metrics=(),
            value_hits=(),
            graph_hits=(),
            degraded_reason=self._degraded_reason,
            action_taken=self._action_taken,
        )


class ScriptBinding:
    """`bind.resolve_detailed` 的**同步**脚本件（BindingService 是同步端口）。"""

    def __init__(
        self,
        state: BindingState = BindingState.RESOLVED_UNIQUE,
        *,
        options: Sequence[CandidateRef] = (),
        disclosure: str | None = None,
        clarify_prompt: str | None = None,
    ) -> None:
        self._state = state
        self._options = tuple(options)
        self._disclosure = disclosure
        self._clarify_prompt = clarify_prompt
        self.calls = 0

    def resolve_detailed(
        self,
        concept: str,
        identity: IdentityContext,
        candidates: Sequence[CandidateRef],
    ) -> BindingOutcome:
        self.calls += 1
        decision = LayerDecision(
            state=self._state,
            layer=BindingLayer.L3,
            bindings=self._options,
            reason=None,
            disclosure=self._disclosure,
            clarify_prompt=self._clarify_prompt,
        )
        return BindingOutcome(
            result=BindingResult(
                state=self._state, layer=BindingLayer.L3, bindings=self._options
            ),
            decision=decision,
            resolution=None,
            filtered=FilterOutcome(),
            scope_was_set=True,
            ignored_candidates=0,
            bundle_version=BUNDLE_VERSION,
        )


class FullChainPlanner:
    """planner 四方法（understand / plan_for / sql_for / repair_sql）的脚本件。

    错误注入：`understand_error`（F1/F2/F3）、`plan_error`（C1/C2）、`sql_error`
    （gen_sql 阶段拒绝）。`repair_sqls` 按序消费（E2 需要"两轮都给坏 SQL"）。
    """

    def __init__(
        self,
        *,
        question: str = QUESTION,
        sql: str = GREEN_SQL,
        understand_error: Exception | None = None,
        plan_error: Exception | None = None,
        plan_blocked_issues: Sequence[str] = (),
        sql_error: Exception | None = None,
        repair_sqls: Sequence[str] = (),
    ) -> None:
        self._question = question
        self._sql = sql
        self._understand_error = understand_error
        self._plan_error = plan_error
        self._plan_blocked_issues = tuple(plan_blocked_issues)
        self._sql_error = sql_error
        self._repair_sqls = list(repair_sqls)
        self.understand_calls = 0
        self.plan_calls = 0
        self.sql_calls = 0
        self.repair_calls = 0

    async def understand(
        self, identity: IdentityContext, question: str, history: tuple[Any, ...] = ()
    ) -> UnderstandOutcome:
        self.understand_calls += 1
        if self._understand_error is not None:
            raise self._understand_error
        return _green_understand(self._question)

    async def plan_for(
        self, identity: IdentityContext, *, normalized_question: str
    ) -> PlanOutcome:
        self.plan_calls += 1
        if self._plan_error is not None:
            raise self._plan_error
        if self._plan_blocked_issues:
            # U-115 测试用：模型自拒（有阻塞项、空 metrics）→ `plan_blocked` 路径。
            blocked = Plan(metrics=[], blocking_issues=list(self._plan_blocked_issues))
            return PlanOutcome(
                plan=blocked,
                plan_summary=blocked.to_summary(),
                meta=_META,
                attempts=1,
                latency_ms=1,
            )
        return PlanOutcome(
            plan=_PLAN,
            plan_summary=_PLAN.to_summary(),
            meta=_META,
            attempts=1,
            latency_ms=1,
        )

    async def sql_for(
        self,
        identity: IdentityContext,
        *,
        normalized_question: str,
        plan: Plan,
        candidates: int = 1,
        complex_query: bool = False,
    ) -> SqlOutcome:
        self.sql_calls += 1
        if self._sql_error is not None:
            raise self._sql_error
        return self._sql_outcome("gen_sql", self._sql)

    async def repair_sql(
        self,
        identity: IdentityContext,
        *,
        normalized_question: str,
        plan: Plan,
        error_digest: str,
    ) -> SqlOutcome:
        self.repair_calls += 1
        if not self._repair_sqls:
            raise RuntimeError("repair_sql 被调用但夹具未预置 repair_sqls —— 用例脚本漂移")
        sql = self._repair_sqls[min(self.repair_calls - 1, len(self._repair_sqls) - 1)]
        return self._sql_outcome("repair", sql)

    @staticmethod
    def _sql_outcome(task: str, sql: str) -> SqlOutcome:
        return SqlOutcome(
            task=task,
            candidates=(SqlCandidate(sql_text=sql, params={}, rationale="dt", confidence=0.9),),
            blocking_issues=(),
            requested=1,
            repair_used=task == "repair",
            meta=_META,
            attempts=1,
            latency_ms=1,
        )


def syntax_failure(*, pgcode: str | None = "42601") -> ExecFailure:
    """可修类执行失败（`syntax_error`，07 §8.9 表：SQLSTATE 42601）。"""
    return ExecFailure(
        ExecError(
            error_class="syntax_error",
            pgcode=pgcode,
            message="SQL 语法有误",
            llm_hint="SQL 语法有误",
        )
    )


def exec_failure(error_class: str, *, pgcode: str | None = None) -> ExecFailure:
    """按类别构造执行失败（`timeout` / `db_unavailable` / `resource_exceeded` / `permission`）。"""
    hints = {
        "timeout": None,
        "permission": None,
        "db_unavailable": None,
        "resource_exceeded": None,
    }
    messages = {
        "timeout": "查询超时，建议收窄时间范围或增加过滤条件",
        "permission": "当前身份无权访问该数据范围",
        "db_unavailable": "数据库暂不可用，请稍后重试",
        "resource_exceeded": "执行超出资源上限",
    }
    return ExecFailure(
        ExecError(
            error_class=error_class,
            pgcode=pgcode,
            message=messages[error_class],
            llm_hint=hints.get(error_class),
        )
    )


class ScriptExecutor:
    """`execute.fetch` / `gate3.explain` 的脚本件。

    `fetches` 按序消费（`ResultSet` 返回 / `ExecFailure` 抛出），用尽重复末位。
    `explain_payload=None` 模拟"沙箱无 EXPLAIN JSON"（D6 的 SKIPPED）；
    `explain_error` 非 None 时 explain 抛出（D5 的 warn）。
    """

    def __init__(
        self,
        *,
        fetches: Sequence[ResultSet | ExecFailure] = (),
        explain_payload: Any = GREEN_EXPLAIN,
        explain_error: Exception | None = None,
    ) -> None:
        self._fetches: list[ResultSet | ExecFailure] = list(fetches) or [GREEN_RESULT]
        self._explain_payload = explain_payload
        self._explain_error = explain_error
        self.fetch_calls = 0
        self.explain_calls = 0

    async def fetch(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        statement_timeout_ms: int,
        effective_limit: int | None = None,
    ) -> ResultSet:
        self.fetch_calls += 1
        item = self._fetches[min(self.fetch_calls - 1, len(self._fetches) - 1)]
        if isinstance(item, ExecFailure):
            raise item
        return item

    async def explain(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        statement_timeout_ms: int,
    ) -> Any:
        self.explain_calls += 1
        if self._explain_error is not None:
            raise self._explain_error
        return self._explain_payload


class ScriptMask:
    """`mask.apply` 的**同步**脚本件（成功直通 / `fail=True` 时 fail-closed）。"""

    def __init__(
        self, *, fail: bool = False, hit_columns: Sequence[str] = ()
    ) -> None:
        self._fail = fail
        self._hit_columns = tuple(hit_columns)
        self.calls = 0

    def apply(
        self, rows: Sequence[Sequence[Any]], policy: Mapping[str, Any]
    ) -> MaskOutcome:
        self.calls += 1
        if self._fail:
            raise MaskFailed("脱敏引擎故障（决策表 G 组脚本）")
        return MaskOutcome(
            rows=tuple(tuple(row) for row in rows), hit_columns=self._hit_columns
        )


class RecordingAudit:
    """两段审计分开记；`pre_fail` / `supp_fail` 模拟写入故障（G1 / G2）。"""

    def __init__(self, *, pre_fail: bool = False, supp_fail: bool = False) -> None:
        self.pre: list[dict[str, Any]] = []
        self.supp: list[dict[str, Any]] = []
        self._pre_fail = pre_fail
        self._supp_fail = supp_fail

    async def write_pre(
        self, identity: IdentityContext, payload: Mapping[str, Any]
    ) -> None:
        if self._pre_fail:
            raise RuntimeError("audit pre down（决策表 G1 脚本）")
        self.pre.append(dict(payload))

    async def write_supp(
        self, identity: IdentityContext, payload: Mapping[str, Any]
    ) -> None:
        if self._supp_fail:
            raise RuntimeError("audit supp down（决策表 G2 脚本）")
        self.supp.append(dict(payload))


# ============================================================================
# 装配与驱动
# ============================================================================


@dataclass
class Chain:
    """一次全链 run 的全部假件引用（断言侧读计数与落行）。"""

    deps: GraphDeps
    planner: FullChainPlanner
    retrieval: ScriptRetrieval
    binding: ScriptBinding
    semantics: FullChainSemantics
    executor: ScriptExecutor
    mask: ScriptMask
    audit: RecordingAudit


def make_chain(
    *,
    question: str = QUESTION,
    sql: str = GREEN_SQL,
    understand_error: Exception | None = None,
    plan_error: Exception | None = None,
    plan_blocked_issues: Sequence[str] = (),
    sql_error: Exception | None = None,
    repair_sqls: Sequence[str] = (),
    fetches: Sequence[ResultSet | ExecFailure] = (),
    explain_payload: Any = GREEN_EXPLAIN,
    explain_error: Exception | None = None,
    allowlists: Sequence[Mapping[str, Any]] | None = None,
    retrieval_candidates: Sequence[CandidateRef]
    | None = None,
    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID,
    retrieval_degraded_reason: DegradedReason | None = None,
    retrieval_action_taken: ActionTaken | None = None,
    binding_state: BindingState = BindingState.RESOLVED_UNIQUE,
    binding_options: Sequence[CandidateRef] = (),
    binding_disclosure: str | None = None,
    binding_clarify_prompt: str | None = None,
    mask_fail: bool = False,
    mask_hit_columns: Sequence[str] = (),
    audit_pre_fail: bool = False,
    audit_supp_fail: bool = False,
) -> Chain:
    """全链假件装配（B–G 逐行差异全部收敛为这组参数 —— 测试文件不再碰 GraphDeps）。"""
    planner = FullChainPlanner(
        question=question,
        sql=sql,
        understand_error=understand_error,
        plan_error=plan_error,
        plan_blocked_issues=plan_blocked_issues,
        sql_error=sql_error,
        repair_sqls=repair_sqls,
    )
    retrieval = ScriptRetrieval(
        candidates=retrieval_candidates
        if retrieval_candidates is not None
        else (CandidateRef(asset_id="fact_orders", score=0.9),),
        mode=retrieval_mode,
        degraded_reason=retrieval_degraded_reason,
        action_taken=retrieval_action_taken,
    )
    binding = ScriptBinding(
        binding_state,
        options=binding_options,
        disclosure=binding_disclosure,
        clarify_prompt=binding_clarify_prompt,
    )
    semantics = FullChainSemantics(allowlists)
    executor = ScriptExecutor(
        fetches=fetches,
        explain_payload=explain_payload,
        explain_error=explain_error,
    )
    mask = ScriptMask(fail=mask_fail, hit_columns=mask_hit_columns)
    audit = RecordingAudit(pre_fail=audit_pre_fail, supp_fail=audit_supp_fail)

    deps = GraphDeps(
        llm=object(),  # type: ignore[arg-type]
        planner=planner,  # type: ignore[arg-type]
        binding=binding,  # type: ignore[arg-type]
        semantics=semantics,  # type: ignore[arg-type]
        retrieval=retrieval,  # type: ignore[arg-type]
        executor=executor,
        mask=mask,
        audit=audit,
        clock=object(),  # type: ignore[arg-type]
    )
    return Chain(
        deps=deps,
        planner=planner,
        retrieval=retrieval,
        binding=binding,
        semantics=semantics,
        executor=executor,
        mask=mask,
        audit=audit,
    )


def run_chain(
    chain: Chain, *, question: str = QUESTION
) -> tuple[list[tuple[str, dict[str, Any]]], RunOutcome]:
    """驱动真图一轮，返回解析后的 `(event, data)` 帧序列与 `RunOutcome`。

    同步用例 + `asyncio.run`（沿 A 组与 `test_api_runner_contract.py` §二 的惯例：
    pytest-asyncio 自建循环在 Windows 上会撞 ProactorEventLoop）。
    """
    holder = _DepsHolder(chain)
    runner = SseRunner(
        graph=build_graph(),
        store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
        new_deps=holder,
    )
    req = RunRequest(identity=_IDENTITY, question=question)

    async def _collect() -> list[bytes]:
        return [frame async for frame in runner.stream(req)]

    frames = [_parse(frame) for frame in asyncio.run(_collect())]
    assert runner.outcome is not None
    return frames, runner.outcome


class _DepsHolder:
    """`new_deps` 载体：每请求一份（同一 Chain 复用同一份假件 —— 断言计数才完整）。"""

    def __init__(self, chain: Chain) -> None:
        self._chain = chain
        self.calls = 0

    def __call__(self) -> GraphDeps:
        self.calls += 1
        return self._chain.deps


def terminal_frames(
    frames: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """`terminal is True` 的帧（N-08：恰 1 个）。"""
    return [(e, d) for e, d in frames if d.get("terminal") is True]
