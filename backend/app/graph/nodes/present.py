"""节点 14 `present` —— 图表 spec + 描述性结论（07 §5.3 行 14）。

层号：L4｜归属窗口：W4（呈现实现 `app/present/` 归 W3，U-148）。

--------------------------------------------------------------------------
一、两条路径
--------------------------------------------------------------------------
- `deps.presenter` 非 None（生产装配 = `ChartPresenter`）：组装 `PresentationInput`
  → `presenter.build(...)` → 写 `chart_spec` / `insight`。
- `deps.presenter` 为 None（评测链路 `eval/harness.py` 显式传 None）：按 §14.2 F4
  如实降级 `degraded(present_failed, table_only)`，不写图表/结论。
  ⚠️ **评测不出图是既定形态**，不得为了“评测也出图”改 `eval/harness.py`。

--------------------------------------------------------------------------
二、失败不 500、审计不阻断
--------------------------------------------------------------------------
presenter 抛异常 → 记 `present_failed/table_only`（detail 带异常类型），**不阻断主链路**；
审计已由 `audit_pre` 落库，fail-closed 语义不变。

--------------------------------------------------------------------------
三、结果行的唯一消费点在本节点末尾
--------------------------------------------------------------------------
`api/runner.py` 的 `audit_pre` 侧信道用 `peek_rows()`（只读）发 `data` 帧；
本节点 `finally` 里 `take_rows()` 消费一次。`chart_spec` 必须是**纯 dict**
（`GraphState` 类型就是 `Mapping[str, Any]`；`events._mapping()` 虽能 asdict dataclass，
但 `if chart:` 对任意对象恒真会发空帧）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.contracts import PresentationInput
from app.core.enums import ActionTaken, DegradedReason, LatencyKey
from app.graph.nodes._shared import metering_update, node_latency, rc
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["present"]

_log = get_logger(__name__)


def _presentation_input(
    state: GraphState,
    *,
    rows: tuple[tuple[Any, ...], ...],
    disclosure: str | None,
    bundle_version: str,
) -> PresentationInput:
    plan = state.get("plan")
    plan_payload = plan if isinstance(plan, Mapping) else None
    options = state.get("options")
    option_payload = options if isinstance(options, Mapping) else {}
    metric_meta = tuple(plan_payload.get("metrics") or ()) if plan_payload else ()
    return PresentationInput(
        question=str(state.get("normalized_question") or state.get("raw_question") or ""),
        plan=plan_payload,
        columns=tuple(state.get("result_columns") or ()),
        rows=rows,
        row_count=int(state.get("row_count") or 0),
        truncated=bool(state.get("truncated") or False),
        metric_meta=metric_meta,
        chart_preference=str(option_payload.get("chart_preference") or "auto"),
        time_range=(
            state.get("time_range") if isinstance(state.get("time_range"), Mapping) else None
        ),
        disclosure=disclosure,
        bundle_version=bundle_version,
    )


async def present(state: GraphState) -> dict[str, Any]:
    """呈现：生产出图/结论；评测无 presenter 时如实降级（见 docstring）。"""
    context = rc()
    deps = context.deps
    rows = context.peek_rows()
    try:
        with node_latency(LatencyKey.PRESENT):
            disclosure = context.take_disclosure()

            if deps.presenter is None:
                detail: dict[str, Any] = {"stage": "present", "reason": "presenter_absent"}
                if disclosure:
                    # U-26：评测/无 presenter 路径下披露只能落审计（生产由 caveats 出口）。
                    detail["binding_disclosure"] = disclosure
                    _log.warning(
                        "binding_disclosure_without_outlet",
                        outcome="audit_only",
                        task_id=str(state.get("task_id")),
                        extra_fact="resolved_default 披露本应进 insight.caveats[]，而本轮无 presenter",
                    )
                context.report_degraded(
                    DegradedReason.PRESENT_FAILED, ActionTaken.TABLE_ONLY, detail
                )
                return metering_update(context)

            try:
                payload = _presentation_input(
                    state,
                    rows=rows,
                    disclosure=disclosure,
                    bundle_version=context.bundle_version,
                )
                presentation = deps.presenter.build(payload)
            except Exception as exc:  # 呈现失败不得 500 / 不阻断审计
                _log.exception(
                    "present_engine_error",
                    task_id=str(state.get("task_id")),
                    error_type=type(exc).__name__,
                )
                detail = {
                    "stage": "present",
                    "reason": "presenter_error",
                    "error_type": type(exc).__name__,
                }
                if disclosure:
                    detail["binding_disclosure"] = disclosure
                context.report_degraded(
                    DegradedReason.PRESENT_FAILED, ActionTaken.TABLE_ONLY, detail
                )
                return metering_update(context)

        update: dict[str, Any] = {}
        if presentation.chart_type is not None:
            update["chart_spec"] = {
                "chart_type": str(presentation.chart_type),
                "option": dict(presentation.option or {}),
            }
        update["insight"] = {
            "text": presentation.insight_text,
            "caveats": list(presentation.caveats),
            "citations": [],
        }
        if presentation.chart_skipped_reason and presentation.chart_skipped_reason.startswith(
            "check:"
        ):
            context.report_degraded(
                DegradedReason.PRESENT_FAILED,
                ActionTaken.TABLE_ONLY,
                {
                    "stage": "present",
                    "reason": "result_checks",
                    "check": presentation.chart_skipped_reason.split(":", 1)[1],
                },
            )
        update.update(metering_update(context))
        return update
    finally:
        context.take_rows()
