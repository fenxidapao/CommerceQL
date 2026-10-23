"""W76-3：指标窗口 fail-closed 的**节点级**拒答路径 + 路由（零出站）。

W75-1 只测了纯函数（`metric_window.enforce_metric_windows` 抛 `MetricWindowError`），
没有证明 `gate1_ast` 会把它落成 `refuse(no_data_asset)` 且**路由到 refuse_out**。
本文件补这一层，并钉住两条边界：

* 拒答路径**不写 `gate_results[AST]`** —— 它不是闸门拒绝（`error(GATE_AST_REJECTED)`），
  是产品结论；`route_after_gate1` 必须按终态选出口（W76-3 的边改动）。
* 上界已一致 / 无起点时**不进拒答路径**（否则一次正常的复购问句会被误杀）。

⚠️ `gate1_ast` 经 `terminal_update → metering_update` 读 `RunContext` ⇒ 必须先
`set_run_context(...)`（与 `test_llm_error_detail.py` 同款装配）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.core.enums import Outcome, RefuseReason
from app.graph.context import RunContext, clear_run_context, set_run_context
from app.graph.edges import REFUSE_OUT, route_after_gate1
from app.graph.nodes.gate1_ast import gate1_ast
from app.graph.state import initial_state
from tests.contract.test_api_runner_contract import _IDENTITY, _make_deps
from tests.unit.guard_fixtures import build_allowlist

_PLAN = {"metrics": [{"name": "repurchase_rate_90d"}], "dimensions": [], "filters": []}
_SQL = "SELECT COUNT(*) FROM v_order_paid WHERE pay_time >= %(start_ts)s"


class _Metrics:
    """只实现 `gate1_ast` 会用到的那两个能力（未预期调用当场炸）。"""

    def __init__(self, window: str) -> None:
        self._window = window
        self._allowlist = build_allowlist()

    def guard_allowlist(self, ctx, *, max_rows=None) -> dict:
        return self._allowlist

    def metric(self, name: str) -> object | None:
        if name != "repurchase_rate_90d":
            return None
        return SimpleNamespace(window=self._window, time_basis="pay_time")


@pytest.fixture()
def ctx() -> Iterator[None]:
    """默认可解析窗口（"90 days"）⇒ 走到 gate1；拒答用例自行换成非法窗口。"""
    token = set_run_context(RunContext(replace(_make_deps("refuse_intent"), semantics=_Metrics("90 days"))))
    try:
        yield None
    finally:
        clear_run_context(token)


def _run_with_window(window: str, state):
    token = set_run_context(
        RunContext(replace(_make_deps("refuse_intent"), semantics=_Metrics(window)))
    )
    try:
        return asyncio.run(gate1_ast(state))
    finally:
        clear_run_context(token)


def _state(**overrides):
    state = initial_state(_IDENTITY, raw_question="T_A 自 2026-06-01 起的 90 天复购率是多少？")
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def test_unenforceable_window_refuses_with_reason_code(ctx: None) -> None:
    state = _state(plan=_PLAN, sql_text=_SQL, sql_params={"start_ts": "2026-06-01"})
    update = _run_with_window("1 quarter", state)

    terminal = update["terminal"]
    assert terminal["event"] == "refuse"
    assert terminal["reason"] == RefuseReason.NO_DATA_ASSET.value
    assert update["outcome"] == Outcome.REFUSE
    assert update["intent_detail"]["reason_code"] == "metric_window_unenforceable"
    assert update["intent_detail"]["metric_window_error"] == "window_unparsable"
    # 不是闸门拒绝：不得伪造 gate_results[AST]
    assert "gate_results" not in update


def test_refusal_routes_to_refuse_out_not_error_out(ctx: None) -> None:
    state = _state(plan=_PLAN, sql_text=_SQL, sql_params={"start_ts": "2026-06-01"})
    update = _run_with_window("1 quarter", state)
    merged = {**state, **update}
    assert route_after_gate1(merged) == REFUSE_OUT


def test_gate_rejection_still_routes_to_error_out(ctx: None) -> None:
    """闸门拒绝的旧路径逐字不变：终态是 `error` ⇒ 仍走 error_out。"""
    state = _state(
        plan=_PLAN,
        sql_text="SELECT 1; SELECT 2",  # 多语句 ⇒ R02 拒绝
        sql_params={},
    )
    update = asyncio.run(gate1_ast(state))
    merged = {**state, **update}
    assert merged["terminal"]["event"] == "error"
    assert route_after_gate1(merged) != REFUSE_OUT


def test_empty_window_is_not_enforced(ctx: None) -> None:
    """无 window 声明的指标不触发任何改写（防止"没声明也被连带"）。"""
    state = _state(plan=_PLAN, sql_text=_SQL, sql_params={"start_ts": "2026-06-01"})
    update = _run_with_window("", state)
    assert update.get("terminal") is None
    assert "%(window_end_" not in str(update.get("sql_text") or "")
