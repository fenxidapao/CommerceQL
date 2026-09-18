"""条件边契约测试 —— 07 §5.4 表格**逐行**、§14.2 A–H 的**去向**逐条。

对应 DoD ④："07 §14.2 的 A–H 八组决策表逐行有对应测试"。
条件边是纯函数，故本文件**不需要跑图**（跑图只能证明"某条分支可达"，
证明不了"另一条分支可达"—— 而那正是 §5.4 每行两/三个分支存在的意义）。

⚠️ 本文件同时钉住两处**如实登记的缺口**（见 `app/graph/edges.py` 模块 docstring §二）：
`route_after_plan` 的模板分支不可达、转异步判定恒 `False`。
它们的用例在缺口补齐时会**变红** —— 那时才是改动点，而不是"悄悄改了也没人知道"。
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import END

from app.core.contracts import GateResult
from app.core.enums import BindingState, GateDecision, GateNo
from app.graph import edges
from app.graph.edges import (
    MAX_REPAIR_ROUNDS,
    route_after_audit_pre,
    route_after_bind,
    route_after_execute,
    route_after_gate1,
    route_after_gate2,
    route_after_gate3,
    route_after_gen_sql,
    route_after_intent,
    route_after_link,
    route_after_mask,
    route_after_normalize,
    route_after_plan,
    route_after_present,
    route_after_repair,
    route_terminal,
    terminal_target,
)
from app.graph.nodes import (
    ALL_NODE_NAMES,
    AUDIT_PRE,
    AUDIT_SUPP,
    BIND,
    CLARIFY_OUT,
    ERROR_OUT,
    EXECUTE,
    GATE1_AST,
    GATE2_POLICY,
    GATE3_COST,
    GEN_SQL,
    INTENT,
    LINK,
    MASK,
    PLAN,
    PRESENT,
    REFUSE_OUT,
    REPAIR,
)

#: 出口节点名（`END` 之外唯一允许被条件边返回的"终点"）。
_EXITS = {CLARIFY_OUT, REFUSE_OUT, ERROR_OUT}

#: 所有条件边（用于"返回值必须已注册"的兜底断言）。
_ROUTERS = (
    route_after_normalize,
    route_after_intent,
    route_after_link,
    route_after_plan,
    route_after_bind,
    route_after_gen_sql,
    route_after_gate1,
    route_after_gate2,
    route_after_gate3,
    route_after_execute,
    route_after_repair,
    route_after_mask,
    route_after_audit_pre,
    route_after_present,
)


def _state(**kw: Any) -> Any:
    """构造一个最小 state（`GraphState` 是 `total=False`，缺字段即"该步没跑过"）。"""
    return dict(kw)


def _gates(*, ast: bool = True, policy: bool = True, cost: bool = True, cost_decision: GateDecision | None = None) -> dict[GateNo, GateResult]:
    def _gate(no: GateNo, passed: bool) -> GateResult:
        decision = GateDecision.PASS if passed else GateDecision.REJECT
        return GateResult(gate_no=no, passed=passed, decision=decision)

    cost_result = _gate(GateNo.COST, cost)
    if cost_decision is not None:
        cost_result = GateResult(
            gate_no=GateNo.COST, passed=cost, decision=cost_decision
        )
    return {GateNo.AST: _gate(GateNo.AST, ast), GateNo.POLICY: _gate(GateNo.POLICY, policy), GateNo.COST: cost_result}


# ---------------------------------------------------------------------------
# route_after_normalize —— §5.4 第 1 行
# ---------------------------------------------------------------------------


def test_route_after_normalize_clarifies_when_time_unparsable() -> None:
    assert route_after_normalize(_state(time_parse_ok=False)) == CLARIFY_OUT


def test_route_after_normalize_continues_when_time_ok() -> None:
    assert route_after_normalize(_state(time_parse_ok=True)) == INTENT


# ---------------------------------------------------------------------------
# route_after_intent —— §5.4 第 2 行（§14.2 A2/A3）
# ---------------------------------------------------------------------------


def test_route_after_intent_four_way() -> None:
    assert route_after_intent(_state(intent="refuse")) == REFUSE_OUT
    assert route_after_intent(_state(intent="clarify")) == CLARIFY_OUT
    assert route_after_intent(_state(intent="open_analysis")) == REFUSE_OUT  # NG4
    assert route_after_intent(_state(intent="executable")) == LINK


def test_route_after_intent_respects_terminal_set_by_node() -> None:
    """节点已设终态（例：kill switch，§14.2 G3）→ 按终态出口，不硬走 `link`。"""
    state = _state(intent="executable", terminal={"event": "refuse", "reason": "no_data_asset"})
    assert route_after_intent(state) == REFUSE_OUT


# ---------------------------------------------------------------------------
# route_after_link —— §5.4 第 3 行（§14.2 B1/B2/B3）
# ---------------------------------------------------------------------------


def test_route_after_link_refuses_on_empty_candidates() -> None:
    assert route_after_link(_state(candidates=())) == REFUSE_OUT


def test_route_after_link_clarifies_on_ambiguity() -> None:
    state = _state(candidates=({"asset_id": "a", "score": 1.0},), ambiguities=({"kind": "grain"},))
    assert route_after_link(state) == CLARIFY_OUT


def test_route_after_link_plans_when_clean() -> None:
    state = _state(candidates=({"asset_id": "a", "score": 1.0},), ambiguities=())
    assert route_after_link(state) == PLAN


# ---------------------------------------------------------------------------
# route_after_plan —— §5.4 第 4 行
# ---------------------------------------------------------------------------


def test_route_after_plan_goes_to_bind_when_plan_present() -> None:
    """成功去向 = `bind`（07 §5.4 表字面是"命中则 gen_sql"，但那会让 `bind` 悬空 ——
    修正依据见 `route_after_plan` 的 docstring，差异登记 RELAY §九）。"""
    assert route_after_plan(_state(plan={"metrics": []})) == BIND


def test_route_after_plan_refuses_when_plan_missing() -> None:
    """⚠️ 模板分支不可达（`NullTemplateProvider` 恒无命中 + 模板产出非 `Plan`）。

    缺口补齐（模板层落地产出真 `Plan`）后，本用例应改为断言走到 `BIND`。
    """
    assert route_after_plan(_state(plan=None)) == REFUSE_OUT


# ---------------------------------------------------------------------------
# route_after_bind —— §5.4 第 5 行（§14.2 B4/B6）
# ---------------------------------------------------------------------------


def test_route_after_bind_covers_all_four_binding_states() -> None:
    assert route_after_bind(_state(binding_status=BindingState.RESOLVED_UNIQUE.value)) == GEN_SQL
    assert route_after_bind(_state(binding_status=BindingState.RESOLVED_DEFAULT.value)) == GEN_SQL
    assert route_after_bind(_state(binding_status=BindingState.AMBIGUOUS.value)) == CLARIFY_OUT
    assert route_after_bind(_state(binding_status=BindingState.UNRESOLVED.value)) == REFUSE_OUT


def test_route_after_bind_is_fail_safe_on_unknown_status() -> None:
    """未登记的绑定态 → 拒答（N-27 fail-safe），**不猜**"大概绑上了"。"""
    assert route_after_bind(_state(binding_status="something_new")) == REFUSE_OUT


# ---------------------------------------------------------------------------
# 闸门三条 + gen_sql —— §5.4 第 6–9 行（§14.2 D1–D6）
# ---------------------------------------------------------------------------


def test_route_after_gen_sql_is_unconditional_gate1() -> None:
    """**无分支**（N-03：闸门是不可跳过的链）—— 包括"已设终态"也不放行。"""
    assert route_after_gen_sql(_state()) == GATE1_AST
    assert route_after_gen_sql(_state(terminal={"event": "error"})) == GATE1_AST


def test_route_after_gate1_reject_never_repairs() -> None:
    """D1：AST 结构性拒绝 → `error_out`，**不进 repair**（重试无意义）。"""
    assert route_after_gate1(_state(gate_results=_gates(ast=False))) == ERROR_OUT
    assert route_after_gate1(_state(gate_results=_gates())) == GATE2_POLICY


def test_route_after_gate2_uses_node_written_terminal() -> None:
    """D2（error）与 D3（refuse）去向不同，由节点写下的 `terminal` 决定。"""
    d2 = _state(gate_results=_gates(policy=False), terminal={"event": "error", "code": "GATE_POLICY_REJECTED"})
    assert route_after_gate2(d2) == ERROR_OUT
    d3 = _state(gate_results=_gates(policy=False), terminal={"event": "refuse", "reason": "pii_blocked"})
    assert route_after_gate2(d3) == REFUSE_OUT
    assert route_after_gate2(_state(gate_results=_gates())) == GATE3_COST


def test_route_after_gate3_reject_is_error_and_warn_still_executes() -> None:
    """D4 → `error_out`；D5（warn）/ D6（skipped）**仍执行**。"""
    rejected = _state(gate_results=_gates(cost=False, cost_decision=GateDecision.REJECT))
    assert route_after_gate3(rejected) == ERROR_OUT

    warned = _state(gate_results=_gates(cost_decision=GateDecision.WARN))
    assert route_after_gate3(warned) == EXECUTE

    skipped = _state(gate_results=_gates(cost_decision=GateDecision.SKIPPED))
    assert route_after_gate3(skipped) == EXECUTE


def test_async_switch_is_unreachable_until_carrier_lands() -> None:
    """⚠️ 登记项：`GateResult` 无预估延迟字段 ⇒ 转异步分支当前不可达（F5 未接线）。

    这条用例存在的意义是**把"未接线"变成可断言的事实**。载体落地后它会红，
    那时才应把断言改成"走到 `audit_supp`"。
    """
    state = _state(
        gate_results=_gates(),
        options={"async_if_slow": True, "async_threshold_ms": 1},
    )
    assert route_after_gate3(state) == EXECUTE


# ---------------------------------------------------------------------------
# execute / repair / mask / audit_pre / present —— §5.4 第 10–13 行
# ---------------------------------------------------------------------------


def test_route_after_execute_three_way() -> None:
    assert route_after_execute(_state()) == MASK
    # E1：可修 + 轮次未用尽 → repair
    repairable = _state(exec_error={"error_class": "unknown_column"}, repair_round=0)
    assert route_after_execute(repairable) == REPAIR
    # E2：轮次用尽 → error_out（不再 repair）
    exhausted = _state(exec_error={"error_class": "unknown_column"}, repair_round=MAX_REPAIR_ROUNDS)
    assert route_after_execute(exhausted) == ERROR_OUT
    # E4：不可修类别 → error_out
    fatal = _state(exec_error={"error_class": "db_unavailable"}, repair_round=0)
    assert route_after_execute(fatal) == ERROR_OUT


def test_route_after_repair_reenters_gate1() -> None:
    """§5.3 第 16 行：纠错后**必须重过全部闸门**（新 SQL 在安全面上与首次等价）。"""
    assert route_after_repair(_state()) == GATE1_AST


def test_route_after_mask_fail_closed() -> None:
    assert route_after_mask(_state()) == AUDIT_PRE
    fail_closed = _state(terminal={"event": "error", "code": "INTERNAL"})
    assert route_after_mask(fail_closed) == ERROR_OUT


def test_route_after_audit_pre_and_present() -> None:
    assert route_after_audit_pre(_state()) == PRESENT
    assert route_after_audit_pre(_state(terminal={"event": "error", "code": "INTERNAL"})) == ERROR_OUT
    assert route_after_present(_state()) == AUDIT_SUPP


# ---------------------------------------------------------------------------
# route_terminal —— §5.4 最后一行（幂等收口）
# ---------------------------------------------------------------------------


def test_route_terminal_ends_only_with_terminal_set() -> None:
    assert route_terminal(_state(terminal={"event": "complete"})) == END
    # 未设终态 = 图缺陷（会让这一轮没有 terminal:true 事件）→ 必须暴露而不是补默认终态。
    with pytest.raises(ValueError):
        route_terminal(_state())


def test_terminal_target_falls_back_to_error_out() -> None:
    assert terminal_target(_state()) == ERROR_OUT
    assert terminal_target(_state(terminal={"event": "clarify"})) == CLARIFY_OUT
    assert terminal_target(_state(terminal={"event": "complete"})) == AUDIT_SUPP


# ---------------------------------------------------------------------------
# 兜底：所有条件边返回的名字必须**已注册**（防"运行时才炸"）
# ---------------------------------------------------------------------------


def test_every_router_target_is_a_registered_node_or_end() -> None:
    """条件边返回未注册的名字，LangGraph 只在**走到那条分支时**才炸。

    这条断言把那种缺陷提前到测试期：构造一批覆盖各分支的 state，
    逐一调用所有 router，断言返回值 ∈ `ALL_NODE_NAMES ∪ {END}`。
    """
    probes = [
        _state(),
        _state(time_parse_ok=False),
        _state(intent="refuse"),
        _state(intent="clarify"),
        _state(intent="executable", candidates=({"asset_id": "a"},), ambiguities=({"k": 1},)),
        _state(candidates=({"asset_id": "a"},), ambiguities=()),
        _state(plan=None),
        _state(plan={"metrics": []}, binding_status=BindingState.AMBIGUOUS.value),
        _state(binding_status=BindingState.UNRESOLVED.value),
        _state(gate_results=_gates(ast=False)),
        _state(gate_results=_gates(policy=False), terminal={"event": "refuse"}),
        _state(gate_results=_gates(cost=False, cost_decision=GateDecision.REJECT)),
        _state(exec_error={"error_class": "unknown_column"}, repair_round=0),
        _state(exec_error={"error_class": "unknown_column"}, repair_round=2),
        _state(terminal={"event": "error"}),
    ]
    known = {*ALL_NODE_NAMES, END}
    for state in probes:
        for router in _ROUTERS:
            target = router(state)
            assert target in known, f"{router.__name__} 返回了未注册的节点名 {target!r}"


def test_edges_module_exports_match_all() -> None:
    """`__all__` 与实际导出一致（防止加了 router 却忘了登记）。"""
    for name in edges.__all__:
        assert hasattr(edges, name), f"`edges.__all__` 列了不存在的名字：{name}"
    assert MAX_REPAIR_ROUNDS == 2
