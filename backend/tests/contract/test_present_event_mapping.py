"""`present` 增量 → SSE 帧的键名契约（逐字）。

`chart_spec` / `insight` 一旦改名，前端零判断权就破了 —— 这里不测字节格式
（那是 `test_sse_events_contract.py` 的事），只测**键集**与数值类型穿过滤镜后不变。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.contracts import ColumnMeta, PresentationInput
from app.core.enums import ChartType, SseEvent
from app.graph.events import emissions_for_node
from app.present.presenter import ChartPresenter

_CATALOG: dict[str, dict[str, Any]] = {
    "gmv": {"display_name": "GMV", "unit": "CNY", "aggregation": "sum"},
}


def _payload() -> PresentationInput:
    return PresentationInput(
        question="各州 GMV",
        plan={"limit": 10},
        columns=(
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="gmv", type_name="decimal"),
        ),
        rows=(("SP", Decimal("100.50")), ("RJ", Decimal("80"))),
        row_count=2,
        truncated=False,
        metric_meta=({"name": "gmv"},),
        chart_preference="auto",
        time_range=None,
        disclosure="该指标默认取已支付订单。",
        bundle_version="2026.10.27.1",
    )


def _present_update() -> dict[str, Any]:
    presentation = ChartPresenter(metric_catalog=_CATALOG).build(_payload())
    assert presentation.chart_type is ChartType.BAR
    return {
        "chart_spec": {
            "chart_type": str(presentation.chart_type),
            "option": dict(presentation.option or {}),
        },
        "insight": {
            "text": presentation.insight_text,
            "caveats": list(presentation.caveats),
            "citations": [],
        },
    }


def _by_event(update: dict[str, Any]) -> dict[SseEvent, dict[str, Any]]:
    emissions = emissions_for_node(
        "present", update, elapsed_ms=1, extras={"meta": {"bundle_version": "2026.10.27.1"}}
    )
    return {emission.event: dict(emission.data) for emission in emissions}


def test_present_emits_chart_insight_and_meta() -> None:
    frames = _by_event(_present_update())
    assert set(frames) == {SseEvent.CHART, SseEvent.INSIGHT, SseEvent.META}


def test_chart_frame_keys_are_exactly_chart_type_and_option() -> None:
    frames = _by_event(_present_update())
    assert set(frames[SseEvent.CHART]) == {"chart_type", "option"}
    assert frames[SseEvent.CHART]["chart_type"] == "bar"


def test_insight_frame_keys_are_exactly_text_caveats_citations() -> None:
    frames = _by_event(_present_update())
    assert set(frames[SseEvent.INSIGHT]) == {"text", "caveats", "citations"}
    assert frames[SseEvent.INSIGHT]["citations"] == []
    assert isinstance(frames[SseEvent.INSIGHT]["caveats"], list)


def test_chart_option_numbers_survive_jsonable_as_numbers() -> None:
    frames = _by_event(_present_update())
    option = frames[SseEvent.CHART]["option"]
    values = [
        point
        for series in option["series"]
        for point in series["data"]
    ]
    assert values == [100.5, 80]
    assert all(isinstance(value, (int, float)) for value in values)


def test_absent_chart_spec_emits_no_chart_frame() -> None:
    update = _present_update()
    del update["chart_spec"]
    frames = _by_event(update)
    assert SseEvent.CHART not in frames
    assert SseEvent.INSIGHT in frames
