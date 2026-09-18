"""图接线快照与回归（07 §5.3 节点表 / §5.4 条件边 / N-08 终态唯一性）。

层号：tests（跨层）｜归属窗口：W4（`docs/08 §4.1`：`tests/graph_snapshot/**`）。

--------------------------------------------------------------------------
一、本文件为什么在 T2 就存在（而不是等 T9）
--------------------------------------------------------------------------
T2 的接线在**第一次真正跑图**时暴露了两个"编译通过但一跑就坏"的缺陷
（见 `TestEntrySelfCheck` 与 `TestAuditSnapshot` 的注释）——两条都不是风格问题：
前者让**整张图从入口就起不来**（本产品自己的 `initial_state()` 造的状态过不了自检），
后者让 `audit_log.latency_ms` 在**成功路径上恒为空**。
⇒ 缺陷修复必须当场带回归用例，否则下一次"顺手把判定写回 `is None`"会静默复发。

--------------------------------------------------------------------------
二、本文件**不**做的事（避免与 T9 重复）
--------------------------------------------------------------------------
· 不覆盖 07 §14.2 A–H 的逐行判定 —— 那是 `tests/contract/test_edges_contract.py`
  （纯函数、构造 state → 断言去向）的职责，本文件只跑**真图**。
· 不做 SSE 转录断言 —— 归 T9 的 `tests/contract/`（`EventRecorder` 侧）。
  本文件只看 `GraphState.terminal` 这一个**终态字段**（N-08 的写入口）。

--------------------------------------------------------------------------
三、为什么用同步用例 + `asyncio.run`（而不是 `async def test_`）
--------------------------------------------------------------------------
`pytest-asyncio 1.4` 自建的循环**不认** `set_event_loop_policy`，在本机（Windows）
会让 `psycopg` 撞 `ProactorEventLoop`。仓库既有惯例是同步用例内 `asyncio.run(...)`
（见 `test_auth_chain.py` 的 30+ 处）。本文件不碰数据库，但**保持同一惯例**以免
日后有人往里加一条带 DSN 的用例时踩同一个坑。
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import pytest

from app.core.contracts import IdentityContext, TokenUsage
from app.core.enums import RefuseReason, Role
from app.core.errors import ContractViolationError
from app.graph.build import build_graph
from app.graph.context import GraphDeps, RunContext, clear_run_context, set_run_context
from app.graph.nodes import ALL_NODE_NAMES, TERMINAL_NODE_NAMES
from app.graph.nodes import trusted_context as trusted_context_node
from app.graph.state import REQUIRED_STATE_FIELDS, initial_state
from app.llm.errors import LlmRefused, LlmTimeout
from app.planner.engine import LlmCallMeta, UnderstandOutcome
from app.planner.schemas import IntentKind

# ============================================================================
# 夹具：最小假依赖 + 可编程的 planner
# ============================================================================
#
# ⚠️ 为什么"假依赖"在这里是**正当**的（而不是 PROMPT 红线里的"Mock 冒充联调"）：
# 本文件断言的是**图的接线与状态流转**（拓扑、终态唯一、审计载荷），这些与
# 数据库/网络无关；真实三包与真实 PG 的通路归 T9 的集成用例与 T7/T6 的装配。
# 每个假实现都**只**实现被断言路径真正途经的成员，且任何未预期的调用会
# `AttributeError`/`TypeError` 当场炸（而不是静默返回 None）—— 这是刻意的：
# "假依赖悄悄兜住了一个我没意识到的调用"是最坏的一类假绿。

_IDENTITY = IdentityContext(
    trace_id="trace-snap-1",
    task_id="task-snap-1",
    session_id="sess-snap-1",
    tenant_id="tenant-snap",
    user_id="user-snap-1",
    role=Role.ANALYST,
    scope_claims=(),
    shop_ids=(),
)


def _meta() -> LlmCallMeta:
    return LlmCallMeta(
        model="deepseek-chat",
        prompt_version="pv-snapshot",
        tokens=TokenUsage(input=10, output=5, cache_hit=0, total=15),
        cost_cny=Decimal("0.0001"),
    )


class _FakeSemantics:
    """只提供 `trusted_context` 需要的那一个成员（版本固定）。"""

    def active_version(self) -> str:
        return "v-snapshot-0001"


class _RecordingAudit:
    """记录段 1 审计载荷（`write_pre` 是**唯一**被出口节点调用的成员）。"""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def write_pre(self, identity: IdentityContext, payload: dict[str, Any]) -> None:
        self.rows.append(payload)


class _ScriptedPlanner:
    """按 `mode` 返回/抛出的 planner —— 三种出口各一条。

    ⚠️ `understand` 的签名必须与 `PlannerEngine.understand` 一致
    （`(identity, question, history=())`）：节点是按**位置**传参的，签名漂移会
    让"节点传错参数"这类缺陷被假依赖吞掉。
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def understand(
        self, identity: IdentityContext, question: str, history: tuple[Any, ...] = ()
    ) -> UnderstandOutcome:
        if self.mode == "llm_refused":
            # 产品结论：模板层无命中 → 拒答。**必须先于其它 LlmError 分流**（07 §10.2 末行）。
            raise LlmRefused("模板层无命中 → 拒答（不是故障）")
        if self.mode == "llm_timeout":
            # F1：超时。W3A 把它的 `default_code` 定成 `INTERNAL`
            # （`LlmTimeout` docstring："冒到 API 层 = 降级链也走完了"）。
            raise LlmTimeout("网关 15s 上限")
        if self.mode == "refuse_intent":
            intent, refuse_kind, time_ok = IntentKind.REFUSE, RefuseReason.NO_DATA_ASSET, True
        elif self.mode == "time_unparsable":
            intent, refuse_kind, time_ok = IntentKind.EXECUTABLE, None, False
        else:  # pragma: no cover - 未登记的 mode 直接炸，避免"悄悄走了别的分支"
            raise AssertionError(f"未登记的 planner mode：{self.mode}")
        return UnderstandOutcome(
            merged=True,
            normalized_question=question,
            intent=intent,
            refuse_kind=refuse_kind,
            reason_code="snapshot",
            clarify_hint="是哪个自然月？",
            confidence=0.7,
            time_range=None,
            time_parse_ok=time_ok,
            time_reason=None if time_ok else "无法唯一解析",
            resolved_terms=(),
            unresolved_terms=(),
            injection={},
            meta=_meta(),
            attempts=1,
            latency_ms=12,
        )


def _make_deps(mode: str) -> GraphDeps:
    return GraphDeps(
        llm=object(),
        planner=_ScriptedPlanner(mode),  # type: ignore[arg-type]
        binding=object(),  # type: ignore[arg-type]
        semantics=_FakeSemantics(),  # type: ignore[arg-type]
        retrieval=object(),  # type: ignore[arg-type]
        executor=object(),  # type: ignore[arg-type]
        mask=object(),  # type: ignore[arg-type]
        audit=_RecordingAudit(),  # type: ignore[arg-type]
        clock=object(),  # type: ignore[arg-type]
    )


def _run_graph(mode: str, question: str = "上个月卖得怎么样") -> tuple[dict[str, Any], GraphDeps]:
    """跑一次真图并返回 `(终态后的 state, deps)`。

    ⚠️ `checkpointer=None` 是**刻意**的：本文件验的是状态流转，不是检查点；
    带 saver 的用例归 T7（需要真实 PG）。
    """
    deps = _make_deps(mode)
    context = RunContext(deps)
    token = set_run_context(context)
    try:
        graph = build_graph()
        out = asyncio.run(
            graph.ainvoke(
                initial_state(_IDENTITY, raw_question=question),
                config={"configurable": {"thread_id": _IDENTITY.task_id}},
            )
        )
    finally:
        clear_run_context(token)
    return out, deps


# ============================================================================
# 一、入口自检（回归：判"键在场"，不判"值非 None"）
# ============================================================================


class TestEntrySelfCheck:
    """`trusted_context` 的就位自检。

    🔴 回归背景（T2 冒烟实测）：早期版本写作
    `missing = sorted(f for f in REQUIRED_STATE_FIELDS if state.get(f) is None)`，
    而 `REQUIRED_STATE_FIELDS` 是组 1 **全集**（11 个），其中 `options` /
    `idempotency_key` 在 `initial_state()` 里是**条件写入**（`None` 时不写键）。
    ⇒ 本产品自己的官方构造器造出的状态**过不了入口自检**，整张图起不来。
    """

    def test_expected_set_excludes_optional_request_fields(self) -> None:
        """`options` / `idempotency_key` 必须被排除在"必须在位"之外。"""
        expected = trusted_context_node._EXPECTED_AT_ENTRY
        assert {"options", "idempotency_key"}.isdisjoint(expected)
        # 排除项必须仍在组 1 里 —— 否则本集合会变成"第三份字段表"（U-18 的教训）。
        assert {"options", "idempotency_key"} <= REQUIRED_STATE_FIELDS
        # 8 个身份字段 + `raw_question` 必须在位。
        assert len(expected) == len(REQUIRED_STATE_FIELDS) - 2

    def test_official_initial_state_covers_expected_set(self) -> None:
        """**核心回归**：`initial_state()` 的产物必须覆盖"必须在位"的每一个键。"""
        state = initial_state(_IDENTITY, raw_question="上个月卖得怎么样")
        missing = sorted(f for f in trusted_context_node._EXPECTED_AT_ENTRY if f not in state)
        assert missing == [], f"官方构造器缺少入口自检要求的字段：{missing}"

    def test_self_check_passes_for_official_state(self) -> None:
        """端到端：官方构造的状态必须真的能过 `trusted_context`（含语义包版本固定）。"""
        deps = _make_deps("refuse_intent")
        context = RunContext(deps)
        token = set_run_context(context)
        try:
            update = asyncio.run(
                trusted_context_node.trusted_context(
                    initial_state(_IDENTITY, raw_question="上个月卖得怎么样")
                )
            )
        finally:
            clear_run_context(token)
        # 组 1 "之后只读"：入口节点不得回写身份（见该节点 docstring §二）。
        assert update == {}
        assert context.bundle_version == "v-snapshot-0001"

    def test_bare_dict_is_rejected(self) -> None:
        """裸 dict（API 层没走 `initial_state`）必须 fail-fast，且错误里点名缺了谁。"""
        bare: dict[str, Any] = {"task_id": "t", "raw_question": "q"}
        with pytest.raises(ContractViolationError) as excinfo:
            asyncio.run(trusted_context_node.trusted_context(bare))  # type: ignore[arg-type]
        detail = excinfo.value.detail or {}
        assert "trace_id" in detail.get("missing_identity_fields", [])


# ============================================================================
# 二、拓扑快照（07 §5.3 的 19 节点 / §5.4 的 14 条条件边）
# ============================================================================


class TestTopology:
    """图结构本身的可核对形态。"""

    def test_node_set(self) -> None:
        graph = build_graph()
        names = set(graph.get_graph().nodes)
        assert names == {"__start__", "__end__", *ALL_NODE_NAMES}
        assert len(ALL_NODE_NAMES) == 19  # 16 主节点 + 3 出口（§5.3）
        assert set(TERMINAL_NODE_NAMES) <= names

    def test_conditional_edge_sources_and_targets(self) -> None:
        """14 条条件边的**来源与目标**都必须可内省。

        🔴 为什么这条测试重要：LangGraph 在 `path_map=None` 时无法内省目标，
        `get_graph()` 会把该边渲染成指向 `__end__` 的**占位边** —— 于是"图快照"
        这个对账依据是假的（且编译期不校验拼错的节点名）。早期版本正是如此。
        """
        graph = build_graph()
        branches = graph.builder.branches
        # 14 条 §5.4 条件边（`trusted_context` 是入口**常量边**，不计入）。
        assert len(branches) == 14
        assert "trusted_context" not in branches

        exits = {"clarify_out", "refuse_out", "error_out"}
        for source, mapping in branches.items():
            (spec,) = mapping.values()
            targets = set(spec.ends or ())
            assert targets, f"{source} 的 `path_map` 为空 —— 目标不可内省"
            assert targets <= set(ALL_NODE_NAMES), f"{source} 指向了不存在的节点：{targets}"
            # 终态优先守卫（`build._guard`）让每条边都能直达三个出口。
            assert exits <= targets, f"{source} 缺少终态出口：{exits - targets}"

        # 逐条抽查四条的"主去向"，防止有人把两条边接反。
        assert "intent" in set(
            next(iter(branches["normalize"].values())).ends or ()
        )
        assert "gate2_policy" in set(
            next(iter(branches["gate1_ast"].values())).ends or ()
        )
        assert {"execute", "audit_supp"} <= set(
            next(iter(branches["gate3_cost"].values())).ends or ()
        )
        assert {"mask", "repair"} <= set(
            next(iter(branches["execute"].values())).ends or ()
        )

    def test_unconditional_edges(self) -> None:
        graph = build_graph()
        edges = {(e.source, e.target) for e in graph.get_graph().edges}
        assert ("__start__", "trusted_context") in edges
        assert ("trusted_context", "normalize") in edges
        assert ("audit_supp", "__end__") in edges
        for name in TERMINAL_NODE_NAMES:
            assert (name, "__end__") in edges


# ============================================================================
# 三、终态唯一性 + 段 1 审计（N-08 / C-04）
# ============================================================================


class TestExitPaths:
    """三条出口各走一遍真图。"""

    @pytest.mark.parametrize(
        ("mode", "event", "outcome"),
        [
            ("refuse_intent", "refuse", "refuse"),
            ("llm_refused", "refuse", "refuse"),
            ("time_unparsable", "clarify", "clarify"),
            ("llm_timeout", "error", "failed"),
        ],
    )
    def test_terminal_event_and_outcome(self, mode: str, event: str, outcome: str) -> None:
        state, _ = _run_graph(mode)
        terminal = state.get("terminal") or {}
        assert terminal.get("event") == event, f"{mode} 走到了 {terminal}"
        assert state.get("outcome") == outcome

    def test_segment_one_audit_written_once(self) -> None:
        _state, deps = _run_graph("refuse_intent")
        rows = deps.audit.rows  # type: ignore[attr-defined]
        assert len(rows) == 1, "出口路径必须恰写一次段 1 审计"
        row = rows[0]
        assert row["outcome"] == "refuse"
        assert row["refusal_reason"] == "no_data_asset"
        assert row["bundle_version"] == "v-snapshot-0001"
        assert row["pii_columns_hit"] == []

    def test_audit_latency_is_a_real_snapshot(self) -> None:
        """🔴 回归：`audit_log.latency_ms` 不得为空。

        早期版本从 `state["latency_ms"]` 取（组 11），而该键**只在出口节点**经
        `terminal_update` → `metering_update()` 写入 ⇒ 在成功路径上 `audit_pre`
        运行时它还没被写过，审计列恒为 `{}`；失败路径上读到的又是"某个失败节点
        当时写的半成品"。⇒ 改为从 `RunContext` 累加器取快照（唯一真相）。
        """
        for mode in ("refuse_intent", "time_unparsable", "llm_timeout"):
            _, deps = _run_graph(mode)
            row = deps.audit.rows[0]  # type: ignore[attr-defined]
            payload = json.loads(row["latency_ms"])
            assert payload, f"{mode}：段 1 审计的 latency_ms 为空（回归）"
            # C-04：分项 + `total`（`total` 由累加器在快照时补齐）。
            assert "total" in payload
