"""结果行生命周期：`audit_pre` 只读 → `present` 单次消费。

三段**不走 `make_chain`**（计划 §3.3 的裁定）：`data` 帧由 L5 的
`SseRunner._extras(AUDIT_PRE)` 侧信道发出，图内看不到 ⇒ 全链测试证明不了
"同一份行既进事件、又进 presenter，且只被消费一次"。

① `RunContext` 级 peek/take 语义；
② 直接调 `_extras(AUDIT_PRE, ...)`，断言与 `peek_rows()` 一致且**未清空**；
③ 直接调 `present` 节点：presenter 拿到的行 = ② 的那一份，调用后通道为空。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.api.runner import SseRunner
from app.core.contracts import ColumnMeta, Presentation
from app.core.enums import ChartType
from app.graph.context import (
    GraphDeps,
    RunContext,
    clear_run_context,
    set_run_context,
)
from app.graph.nodes import AUDIT_PRE
from app.graph.nodes.present import present
from app.graph.state import GraphState

_ROWS: tuple[tuple[Any, ...], ...] = (("SP", 10), ("RJ", 20))


def _context(presenter: Any) -> RunContext:
    deps = SimpleNamespace(presenter=presenter)
    return RunContext(cast(GraphDeps, deps))


def _state() -> dict[str, Any]:
    return {
        "task_id": "t-row-lifecycle",
        "raw_question": "各州订单量",
        "normalized_question": "各州订单量",
        "plan": {"limit": 10, "metrics": [{"name": "order_cnt"}]},
        "options": {"chart_preference": "auto"},
        "result_columns": (
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="order_cnt", type_name="number"),
        ),
        "row_count": len(_ROWS),
        "truncated": False,
        "time_range": None,
    }


class _RecordingPresenter:
    def __init__(self) -> None:
        self.payloads: list[Any] = []

    def build(self, payload: Any) -> Presentation:
        self.payloads.append(payload)
        return Presentation(
            chart_type=ChartType.BAR,
            option={"title": {"text": "订单量"}, "series": [{"name": "订单量", "type": "bar", "data": [10, 20]}]},
            insight_text="按 state 看，SP 的订单量最高（10单），共 2 项。",
            caveats=("语义包版本 v1。",),
            chart_skipped_reason=None,
        )


class _ExplodingPresenter:
    def build(self, payload: Any) -> Presentation:
        raise ValueError("boom")


# ---------------------------------------------------------------------------
# ① RunContext 级
# ---------------------------------------------------------------------------


def test_peek_is_read_only_and_take_consumes_once() -> None:
    ctx = _context(_RecordingPresenter())
    ctx.hold_rows(_ROWS)
    assert ctx.peek_rows() == _ROWS
    assert ctx.peek_rows() == _ROWS
    assert ctx.take_rows() == _ROWS
    assert ctx.peek_rows() == ()
    assert ctx.take_rows() == ()


# ---------------------------------------------------------------------------
# ② audit_pre 侧信道
# ---------------------------------------------------------------------------


def test_audit_pre_extras_reads_rows_without_consuming() -> None:
    ctx = _context(_RecordingPresenter())
    ctx.hold_rows(_ROWS)
    runner = object.__new__(SseRunner)
    extras = runner._extras(AUDIT_PRE, {}, ctx, cast(Any, None))
    assert extras == {"rows": _ROWS}
    assert ctx.peek_rows() == _ROWS, "audit_pre 侧信道不得消费结果行（present 才是消费点）"


# ---------------------------------------------------------------------------
# ③ present 节点：与 ② 同一份行、单次消费、state 形状逐字
# ---------------------------------------------------------------------------


def test_present_consumes_the_same_rows_that_audit_pre_published() -> None:
    recorder = _RecordingPresenter()
    ctx = _context(recorder)
    ctx.hold_rows(_ROWS)
    ctx.hold_disclosure("该指标默认取已支付订单。")
    ctx.bundle_version = "2026.10.27.1"

    runner = object.__new__(SseRunner)
    extras = runner._extras(AUDIT_PRE, {}, ctx, cast(Any, None))
    assert extras is not None

    token = set_run_context(ctx)
    try:
        update = asyncio.run(present(cast(GraphState, _state())))
    finally:
        clear_run_context(token)

    assert recorder.payloads, "presenter 未被调用"
    seen = recorder.payloads[0]
    assert seen.rows == extras["rows"], "presenter 拿到的行必须与 data 帧同一份"
    assert seen.disclosure == "该指标默认取已支付订单。"
    assert seen.bundle_version == "2026.10.27.1"
    assert seen.chart_preference == "auto"
    assert ctx.peek_rows() == (), "present 末尾必须消费结果行"

    assert set(update["chart_spec"]) == {"chart_type", "option"}
    assert update["chart_spec"]["chart_type"] == "bar"
    assert set(update["insight"]) == {"text", "caveats", "citations"}
    assert update["insight"]["citations"] == []
    assert "语义包版本 v1。" in update["insight"]["caveats"]


def test_present_without_presenter_degrades_and_still_consumes_rows() -> None:
    ctx = _context(None)
    ctx.hold_rows(_ROWS)
    token = set_run_context(ctx)
    try:
        update = asyncio.run(present(cast(GraphState, _state())))
    finally:
        clear_run_context(token)

    assert "chart_spec" not in update
    assert "insight" not in update
    assert [entry["reason"] for entry in ctx.degradations()] == ["present_failed"]
    assert [entry["action_taken"] for entry in ctx.degradations()] == ["table_only"]
    assert ctx.degradations()[0]["detail"]["reason"] == "presenter_absent"
    assert ctx.peek_rows() == ()


def test_presenter_exception_degrades_without_raising() -> None:
    ctx = _context(_ExplodingPresenter())
    ctx.hold_rows(_ROWS)
    token = set_run_context(ctx)
    try:
        update = asyncio.run(present(cast(GraphState, _state())))
    finally:
        clear_run_context(token)

    assert "chart_spec" not in update
    entry = ctx.degradations()[0]
    assert entry["reason"] == "present_failed"
    assert entry["detail"]["reason"] == "presenter_error"
    assert entry["detail"]["error_type"] == "ValueError"
    assert ctx.peek_rows() == (), "异常路径同样必须消费结果行（finally）"


@pytest.mark.parametrize("blocking_code", ["all_null"])
def test_blocking_check_downgrades_to_table_with_stable_reason(blocking_code: str) -> None:
    from app.present.checks import run_result_checks
    from app.present.presenter import ChartPresenter

    presenter = ChartPresenter(metric_catalog={})
    ctx = _context(presenter)
    ctx.hold_rows(((None, None),))
    state = _state()
    state["result_columns"] = (
        ColumnMeta(name="state", type_name="category"),
        ColumnMeta(name="gmv", type_name="decimal"),
    )
    token = set_run_context(ctx)
    try:
        update = asyncio.run(present(cast(GraphState, state)))
    finally:
        clear_run_context(token)

    assert update["chart_spec"]["chart_type"] == "table"
    entry = ctx.degradations()[0]
    assert entry["reason"] == "present_failed"
    assert entry["detail"]["reason"] == "result_checks"
    assert entry["detail"]["check"] == blocking_code
    # 判据本身也要能复现，防止上面只是"碰巧没触发"
    from app.core.contracts import PresentationInput

    violations = run_result_checks(
        PresentationInput(
            question="",
            plan=None,
            columns=state["result_columns"],
            rows=((None, None),),
            row_count=1,
            truncated=False,
            metric_meta=(),
            chart_preference="auto",
            time_range=None,
            disclosure=None,
            bundle_version="",
        )
    )
    assert blocking_code in [item.code for item in violations]
