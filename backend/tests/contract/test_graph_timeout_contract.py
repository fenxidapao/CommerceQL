"""每节点超时（T8 / HANDOFF §五-5）：`asyncio.timeout` 包装的契约（U-107 / §5.3.0 附注①-③）。

被测契约：

| 约束 | 断言 |
|---|---|
| 非 LLM 节点超时值逐字取 07 §5.3 契约表"超时"列 | `NODE_TIMEOUT_S` 键集 = 9 个固定节点；`trusted_context` 与三个出口（"—"）不进表 |
| 6 个 LLM 节点硬超时 = 客户端超时（§10.2 flash 15s / pro 45s，执行期解析） | `_LLM_NODE_TASKS` 键集 = normalize/intent/plan/gen_sql/present/repair，且 `_effective_limit_for` 按 `resolve_route` 解析 |
| 合并档平移是「分配」而非「硬超时」（§5.3.0 附注③） | `_MERGED_NORMALIZE_EXTRA_S` 保留但**不叠加进** `_effective_limit_for` |
| 包装不改写「—」节点 | `_with_node_timeout` 对「—」节点返回**原函数对象** |
| LLM 节点超时 → 逐节点复用 §5.3 失败转移列（降级/拒答），**不再 re-raise**（附注②） | `gen_sql` 超时 → `degraded + refuse` |
| fail-closed 节点超时 → re-raise（runner 兜底 error(INTERNAL)） | `mask` 超时抛 `TimeoutError` |
| `present` 超时 → `degraded(present_failed, table_only)` + 空增量 | 返回 `{}` 且 `degradations()` 记 PRESENT_FAILED/TABLE_ONLY |
| 闸门超时 → 各自 GATE_* 码 | gate1 超时 → `error(GATE_AST_REJECTED)` |
| `execute` 超时 → 写 `exec_error(timeout)`、不定终态 | `exec_error.error_class == "timeout"` |
| `overrides` 仅测试注入生效 | 覆盖值优先生效 |
| 生产装配可编译 | `build_graph()` / `build_graph(overrides=...)` 均编译成功 |

同步用例 + `asyncio.run`（`tests/contract/` 惯例）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.api import sse
from app.core.enums import ActionTaken, DegradedReason, ErrorCode, Outcome, RefuseReason
from app.graph.build import (
    _LLM_NODE_TASKS,
    NODE_TIMEOUT_S,
    _with_node_timeout,
    build_graph,
)
from app.graph.context import RunContext, clear_run_context, set_run_context
from app.graph.events import EventRecorder
from tests.contract.test_api_runner_contract import _make_deps

# 07 §5.3 表里给了超时值的**非 LLM** 节点（"—" 的 trusted_context 与三个出口不在内；
# 7 个 LLM 节点已从本表移出，改走客户端超时，见 `_LLM_NODE_TASKS`）。
EXPECTED_TIMED_NODES = {
    "link": 30.0,
    "gate1_ast": 0.1,
    "gate2_policy": 0.1,
    "gate3_cost": 1.0,
    "execute": 30.0,
    "mask": 0.1,
    "audit_pre": 1.0,
    "audit_supp": 0.5,
}

#: 7 个 LLM 节点 —— 硬超时 = 客户端超时（§10.2 / U-107 附注① / U-118 ②），**不入 `NODE_TIMEOUT_S`**。
#: `bind` 走 `l4_score`（架构 ① 裁定 (B)：bind 是真发 LLM，摘出在线预算"0.2s 预算当硬超时"病害）。
EXPECTED_LLM_NODES = {
    "normalize", "intent", "plan", "gen_sql", "present", "repair", "bind",
}


def _make_ctx() -> tuple[RunContext, object]:
    """构造一个带 recorder 的 `RunContext` 并 set 进去，返回 `(ctx, token)`。"""
    recorder = EventRecorder(encoder=sse.encode)
    ctx = RunContext(_make_deps("refuse_intent"), recorder=recorder)
    token = set_run_context(ctx)
    return ctx, token


class TestTimeoutTable:
    def test_table_matches_the_spec_values_verbatim(self) -> None:
        """改这里 = 改 07 §5.3（或反过来）—— 两侧必须同步。"""
        assert NODE_TIMEOUT_S == EXPECTED_TIMED_NODES

    def test_llm_nodes_route_to_client_timeout(self) -> None:
        """6 个 LLM 节点的硬超时不再写死在 `NODE_TIMEOUT_S`，而是按 task 路由解析 §10.2 客户端超时。"""
        assert set(_LLM_NODE_TASKS) == EXPECTED_LLM_NODES
        for node in EXPECTED_LLM_NODES:
            assert node not in NODE_TIMEOUT_S

    @pytest.mark.parametrize(
        "name", ["trusted_context", "clarify_out", "refuse_out", "error_out"]
    )
    def test_dash_entries_have_no_timeout(self, name: str) -> None:
        """07 表里 "—" 的节点**不进任何表**：给它们配超时 = 发明文档里没有的数值。"""
        assert name not in NODE_TIMEOUT_S
        assert name not in _LLM_NODE_TASKS


class TestWrapper:
    def test_untimed_node_is_returned_as_is(self) -> None:
        async def _node(state: dict) -> dict:  # pragma: no cover - 仅验同一性
            return {}

        assert _with_node_timeout("trusted_context", _node) is _node

    def test_timeout_reraises_for_fail_closed_nodes(self) -> None:
        """fail-closed 节点（mask/audit_pre/audit_supp）超时 → `TimeoutError` 上抛（工程故障）。

        它们是「没跑完 = 安全前提未满足 / 终态未构造」的节点，吞掉才是谎报（§5.3.0 附注②）。
        """
        calls: list[int] = []

        async def _slow(state: dict) -> dict:
            calls.append(1)
            await asyncio.sleep(5.0)
            return {}

        wrapped = _with_node_timeout("mask", _slow, overrides={"mask": 0.05})
        with pytest.raises(TimeoutError):
            asyncio.run(wrapped({}))
        assert calls == [1]

    def test_llm_node_timeout_degrades_to_refuse(self) -> None:
        """LLM 节点超时 → 复用 §5.3 失败转移列（gen_sql → degraded + refuse），**不 re-raise**。"""
        ctx, token = _make_ctx()
        try:

            async def _slow(state: dict) -> dict:
                await asyncio.sleep(5.0)
                return {}

            wrapped = _with_node_timeout("gen_sql", _slow, overrides={"gen_sql": 0.05})
            result = asyncio.run(wrapped({}))
            assert result["terminal"]["event"] == "refuse"
            assert result["terminal"]["reason"] == RefuseReason.NO_DATA_ASSET.value
            assert result["outcome"] == Outcome.REFUSE
            degradations = ctx.degradations()
            assert len(degradations) == 1
            assert degradations[0]["reason"] == DegradedReason.LLM_UNAVAILABLE.value
            assert degradations[0]["action_taken"] == ActionTaken.TEMPLATE_ONLY.value
        finally:
            clear_run_context(token)

    def test_gate_timeout_sets_error_code(self) -> None:
        """闸门超时 → 各自 GATE_* 错误码（gate1 → `error(GATE_AST_REJECTED)`）。"""
        _ctx, token = _make_ctx()
        try:

            async def _slow(state: dict) -> dict:
                await asyncio.sleep(5.0)
                return {}

            wrapped = _with_node_timeout("gate1_ast", _slow, overrides={"gate1_ast": 0.05})
            result = asyncio.run(wrapped({}))
            assert result["terminal"]["event"] == "error"
            assert result["terminal"]["code"] == ErrorCode.GATE_AST_REJECTED.value
            assert result["outcome"] == Outcome.FAILED
        finally:
            clear_run_context(token)

    def test_execute_timeout_writes_exec_error(self) -> None:
        """execute 超时 → 写 `exec_error(timeout)`、**不定终态**（交 route_after_execute/error_out）。"""

        async def _slow(state: dict) -> dict:
            await asyncio.sleep(5.0)
            return {}

        wrapped = _with_node_timeout("execute", _slow, overrides={"execute": 0.05})
        result = asyncio.run(wrapped({}))
        assert result.get("terminal") is None
        assert result["exec_error"]["error_class"] == "timeout"
        assert result["exec_error"]["llm_hint"] is None
        assert result["exec_error"]["message"] == "查询超时，建议收窄时间范围或增加过滤条件"

    def test_present_timeout_degrades_to_table_only(self) -> None:
        """present 超时 → 与节点内部失败路径**同形**：report_degraded + 空增量。"""
        recorder = EventRecorder(encoder=sse.encode)
        run_context = RunContext(_make_deps("refuse_intent"), recorder=recorder)
        token = set_run_context(run_context)
        try:

            async def _slow(state: dict) -> dict:
                await asyncio.sleep(5.0)
                return {}

            wrapped = _with_node_timeout("present", _slow, overrides={"present": 0.05})
            result = asyncio.run(wrapped({}))
            assert result == {}, "F4：只给表格 = 不发 chart/insight（缺席 = 不发事件）"
            degradations = run_context.degradations()
            assert len(degradations) == 1
            assert degradations[0]["reason"] == DegradedReason.PRESENT_FAILED.value
            assert degradations[0]["action_taken"] == ActionTaken.TABLE_ONLY.value
        finally:
            clear_run_context(token)

    def test_overrides_take_precedence_over_table(self) -> None:
        """`overrides` 仅供测试放大/缩小超时值；覆盖必须真生效。

        用 re-raise 节点 `mask`（表值 0.1s 够跑 0.02s 的活），覆盖压到 0.001s ⇒ 必超时，
        且超时形态是 `TimeoutError`（无需 RunContext 即可观测），证明确实用了覆盖值。
        """

        async def _fast(state: dict) -> dict:
            await asyncio.sleep(0.02)
            return {"ok": True}

        wrapped = _with_node_timeout("mask", _fast, overrides={"mask": 0.001})
        with pytest.raises(TimeoutError):
            asyncio.run(wrapped({}))


class TestClientTimeoutResolution:
    """LLM 节点硬超时 = 客户端超时、合并档平移不加进 asyncio.timeout（§5.3.0 附注①/③）。"""

    def test_llm_node_effective_limit_is_client_timeout(self) -> None:
        from app.graph.build import _client_timeout_for, _effective_limit_for

        for node in ("normalize", "intent", "plan", "gen_sql", "present", "repair"):
            assert _effective_limit_for(node, None) == _client_timeout_for(_LLM_NODE_TASKS[node])

    def test_bind_uses_l4_score_client_timeout(self) -> None:
        """U-118 ①：`bind` 并入 LLM 执行期超时解析，走 `l4_score`（§6.8.2 上界 0.8s 是分配非超时）。"""
        from app.graph.build import _client_timeout_for, _effective_limit_for

        assert _LLM_NODE_TASKS["bind"] == "l4_score"
        assert "bind" not in NODE_TIMEOUT_S
        # bind 的生效硬超时 = `l4_score` 客户端的（FAST flash 15s），而非旧 0.2s 紧值。
        assert _effective_limit_for("bind", None) == _client_timeout_for("l4_score")
        assert _effective_limit_for("bind", None) > 0.2

    def test_merge_extra_is_allocation_not_timeout(self) -> None:
        """`_MERGED_NORMALIZE_EXTRA_S` 是「分配平移」，**不再叠加进 `asyncio.timeout`**。"""
        from app.graph.build import (
            _MERGED_NORMALIZE_EXTRA_S,
            _client_timeout_for,
            _effective_limit_for,
        )

        assert _MERGED_NORMALIZE_EXTRA_S > 0  # 分配仍保留（供 §16.1 预算 / SSE 占位判定）。
        # normalize 的生效硬超时 = 客户端超时（无 +1.5s 平移）。
        assert _effective_limit_for("normalize", None) == _client_timeout_for("normalize")


class TestAssembly:
    def test_build_graph_compiles_with_and_without_overrides(self) -> None:
        """包装不得破坏装配（T9 的拓扑快照跑在同一张被包装过的图上）。"""
        build_graph()
        build_graph(node_timeout_overrides={"gate1_ast": 5.0})
