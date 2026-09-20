"""每节点超时（T8 / HANDOFF §五-5）：`asyncio.timeout` 包装的契约。

被测契约：

| 约束 | 断言 |
|---|---|
| 超时值逐字取 07 §5.3 契约表"超时"列 | `NODE_TIMEOUT_S` 键集 = 16 主节点里 07 给了超时值的 15 个；`trusted_context` 与三个出口（"—"）不在表 |
| 包装不改写无超时节点 | `_with_node_timeout` 对"—"节点返回**原函数对象** |
| 超时 → re-raise（runner 兜底 error(INTERNAL)，N-08 不留无终态的流） | 非 present 节点超时抛 `TimeoutError` |
| `present` 超时 → `degraded(present_failed, table_only)` + 空增量（§14.2 F4 同形） | 返回 `{}` 且 `RunContext.degradations()` 记录 PRESENT_FAILED/TABLE_ONLY |
| `overrides` 仅测试注入生效 | 覆盖值优先生效（0.1s 闸门节点在慢 CI 上防假阳性的通道） |
| 合并档 `normalize` 吸收 `intent` 预算（2.0+1.5=3.5s，执行期按 `deps.merged_understand` 判；w7 🔴-0） | 合并档下超基线的工作不再被掐；split 档 / 无上下文仍逐字表值 |
| 生产装配可编译 | `build_graph()` / `build_graph(overrides=...)` 均编译成功 |

同步用例 + `asyncio.run`（`tests/contract/` 惯例）。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.api import sse
from app.core.enums import ActionTaken, DegradedReason
from app.graph.build import NODE_TIMEOUT_S, _with_node_timeout, build_graph
from app.graph.context import RunContext, clear_run_context, set_run_context
from app.graph.events import EventRecorder
from tests.contract.test_api_runner_contract import _make_deps

# 07 §5.3 表里给了超时值的节点（"—" 的 trusted_context 与三个出口不在内）。
EXPECTED_TIMED_NODES = {
    "normalize": 2.0,
    "intent": 1.5,
    "link": 4.0,
    "plan": 3.0,
    "bind": 0.2,
    "gen_sql": 2.5,
    "gate1_ast": 0.1,
    "gate2_policy": 0.1,
    "gate3_cost": 1.0,
    "execute": 30.0,
    "mask": 0.1,
    "audit_pre": 1.0,
    "present": 2.0,
    "audit_supp": 0.5,
    "repair": 3.0,
}


class TestTimeoutTable:
    def test_table_matches_the_spec_values_verbatim(self) -> None:
        """改这里 = 改 07 §5.3（或反过来）—— 两侧必须同步。"""
        assert NODE_TIMEOUT_S == EXPECTED_TIMED_NODES

    @pytest.mark.parametrize("name", ["trusted_context", "clarify_out", "refuse_out", "error_out"])
    def test_dash_entries_have_no_timeout(self, name: str) -> None:
        """07 表里 "—" 的节点**不进表**：给它们配超时 = 发明文档里没有的数值。"""
        assert name not in NODE_TIMEOUT_S


class TestWrapper:
    def test_untimed_node_is_returned_as_is(self) -> None:
        async def _node(state: dict) -> dict:  # pragma: no cover - 仅验同一性
            return {}

        assert _with_node_timeout("trusted_context", _node) is _node

    def test_timeout_reraises_for_fail_closed_nodes(self) -> None:
        """非 present 节点超时 → `TimeoutError` 上抛（工程故障 → runner 兜底 error）。"""
        calls: list[int] = []

        async def _slow(state: dict) -> dict:
            calls.append(1)
            await asyncio.sleep(5.0)
            return {}

        wrapped = _with_node_timeout("gen_sql", _slow, overrides={"gen_sql": 0.05})
        with pytest.raises(TimeoutError):
            asyncio.run(wrapped({}))

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
        """`overrides` 仅供测试放大 0.1s 闸门值（慢 CI 防假阳性）；覆盖必须真生效。"""

        async def _fast(state: dict) -> dict:
            await asyncio.sleep(0.02)
            return {"ok": True}

        # 表值 gate1_ast=0.1s 够跑，但 overrides 压到 0.001s ⇒ 必超时 —— 证明确实用了覆盖值。
        wrapped = _with_node_timeout("gate1_ast", _fast, overrides={"gate1_ast": 0.001})
        with pytest.raises(TimeoutError):
            asyncio.run(wrapped({}))


class TestMergedUnderstandSlack:
    """合并档预算平移（w7 🔴-0）：`normalize` 吸收 `intent` 的 1.5s，仅本请求合并档生效。"""

    def test_merged_mode_absorbs_intent_budget(self) -> None:
        """合并档（默认 `merged_understand=True`）：0.05s 基线 + 1.5s 平移 ⇒ 0.2s 的活不被掐。"""
        recorder = EventRecorder(encoder=sse.encode)
        # `_make_deps` 不传 `merged_understand` ⇒ 走默认 True（P0 合并档，同生产）。
        run_context = RunContext(_make_deps("refuse_intent"), recorder=recorder)
        token = set_run_context(run_context)
        try:

            async def _work(state: dict) -> dict:
                await asyncio.sleep(0.2)  # > 0.05 基线；< 1.55 生效值
                return {"ok": True}

            wrapped = _with_node_timeout("normalize", _work, overrides={"normalize": 0.05})
            assert asyncio.run(wrapped({})) == {"ok": True}
        finally:
            clear_run_context(token)

    def test_split_mode_keeps_verbatim_budget(self) -> None:
        """split 档（`merged_understand=False`）：仍按表值/覆盖值逐字执行（07 §5.3 不动）。"""
        recorder = EventRecorder(encoder=sse.encode)
        deps = replace(_make_deps("refuse_intent"), merged_understand=False)
        run_context = RunContext(deps, recorder=recorder)
        token = set_run_context(run_context)
        try:

            async def _work(state: dict) -> dict:
                await asyncio.sleep(0.2)  # > 0.05 ⇒ 必超时（证明没吃到平移）
                return {"ok": True}

            wrapped = _with_node_timeout("normalize", _work, overrides={"normalize": 0.05})
            with pytest.raises(TimeoutError):
                asyncio.run(wrapped({}))
        finally:
            clear_run_context(token)

    def test_without_run_context_no_slack(self) -> None:
        """无运行上下文（装配自检 / 未设 context 的单测）：不加平移，按基线走。"""

        async def _work(state: dict) -> dict:
            await asyncio.sleep(0.2)
            return {"ok": True}

        wrapped = _with_node_timeout("normalize", _work, overrides={"normalize": 0.05})
        with pytest.raises(TimeoutError):
            asyncio.run(wrapped({}))

    def test_slack_does_not_leak_to_other_nodes(self) -> None:
        """平移只给 `normalize`：合并档下别的节点仍按自身表值/覆盖值执行。"""
        recorder = EventRecorder(encoder=sse.encode)
        run_context = RunContext(_make_deps("refuse_intent"), recorder=recorder)
        token = set_run_context(run_context)
        try:

            async def _work(state: dict) -> dict:
                await asyncio.sleep(0.2)
                return {"ok": True}

            wrapped = _with_node_timeout("gen_sql", _work, overrides={"gen_sql": 0.05})
            with pytest.raises(TimeoutError):
                asyncio.run(wrapped({}))
        finally:
            clear_run_context(token)


class TestAssembly:
    def test_build_graph_compiles_with_and_without_overrides(self) -> None:
        """包装不得破坏装配（T9 的拓扑快照跑在同一张被包装过的图上）。"""
        build_graph()
        build_graph(node_timeout_overrides={"gate1_ast": 5.0})
