"""`PresenterPort` 出参契约（纯离线）：`chart_type` / `option` / `caveats` 的硬边界。

四条断言对应 07 附录 A §A.10 与 06 §6.5 的前端零判断权前提：

1. `chart_type` ∈ `ChartType` 的 7 值（或 `None` = 不出图）；
2. `option` 键 ⊆ `{title, tooltip, legend, grid, xAxis, yAxis, series}`；
3. **任何层级都不出现 `formatter`**（前端不接受函数字符串）；
4. 数值位置只放 `int` / `float` / `None`（`Decimal` 会被 `_jsonable` 变成字符串）。

外加一条披露出口：`disclosure` / 截断 / Top-N / bundle_version 必须出现在 `caveats`。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.contracts import ColumnMeta, PresentationInput
from app.core.enums import ChartType
from app.present.presenter import ALLOWED_OPTION_KEYS, ChartPresenter

_CATALOG: dict[str, dict[str, Any]] = {
    "gmv": {"display_name": "GMV", "unit": "CNY", "aggregation": "sum"},
    "order_cnt": {"display_name": "订单量", "unit": "单", "aggregation": "sum"},
}


def _input(columns: list[ColumnMeta], rows: list[list[Any]], **overrides: Any) -> PresentationInput:
    values: dict[str, Any] = {
        "question": "",
        "plan": None,
        "columns": tuple(columns),
        "rows": tuple(tuple(row) for row in rows),
        "row_count": len(rows),
        "truncated": False,
        "metric_meta": (),
        "chart_preference": "auto",
        "time_range": None,
        "disclosure": None,
        "bundle_version": "2026.10.27.1",
    }
    values.update(overrides)
    return PresentationInput(**values)


@pytest.fixture()
def presenter() -> ChartPresenter:
    return ChartPresenter(metric_catalog=_CATALOG)


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


_SHAPES: dict[str, PresentationInput] = {
    "kpi": _input([ColumnMeta(name="gmv", type_name="decimal")], [[Decimal("1234.5")]]),
    "line": _input(
        [ColumnMeta(name="month", type_name="date"), ColumnMeta(name="order_cnt", type_name="number")],
        [["2017-01", 10], ["2017-02", 20], ["2017-03", 15]],
    ),
    "bar": _input(
        [ColumnMeta(name="state", type_name="category"), ColumnMeta(name="gmv", type_name="decimal")],
        [["SP", Decimal("100")], ["RJ", Decimal("80")]],
    ),
    "pie": _input(
        [ColumnMeta(name="state", type_name="category"), ColumnMeta(name="gmv", type_name="decimal")],
        [["SP", Decimal("100")], ["RJ", Decimal("80")]],
        question="各州 GMV 占比",
    ),
    "stacked_bar": _input(
        [
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="gmv", type_name="decimal"),
            ColumnMeta(name="order_cnt", type_name="number"),
        ],
        [["SP", Decimal("100"), 8], ["RJ", Decimal("80"), 6]],
        question="各州 GMV 与订单量构成",
    ),
    "grouped_bar": _input(
        [
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="gmv", type_name="decimal"),
            ColumnMeta(name="order_cnt", type_name="number"),
        ],
        [["SP", Decimal("100"), 8], ["RJ", Decimal("80"), 6]],
    ),
    "table": _input(
        [ColumnMeta(name="state", type_name="category"), ColumnMeta(name="order_cnt", type_name="number")],
        [[f"state_{index}", index] for index in range(21)],
    ),
}


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_chart_type_and_option_keys_stay_within_contract(
    presenter: ChartPresenter, shape: str
) -> None:
    presentation = presenter.build(_SHAPES[shape])
    if presentation.chart_type is not None:
        assert presentation.chart_type in set(ChartType)
    if presentation.option:
        assert set(presentation.option) <= ALLOWED_OPTION_KEYS
        for node in _walk(dict(presentation.option)):
            assert node != "formatter", "option 内出现 formatter（前端不接受函数字符串）"


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_series_points_are_json_numbers(presenter: ChartPresenter, shape: str) -> None:
    presentation = presenter.build(_SHAPES[shape])
    if presentation.chart_type is None:
        return
    series = list((presentation.option or {}).get("series") or ())
    for item in series:
        for point in item.get("data") or ():
            value = point.get("value") if isinstance(point, dict) else point
            assert value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def test_pie_points_carry_name_and_numeric_value(presenter: ChartPresenter) -> None:
    presentation = presenter.build(_SHAPES["pie"])
    assert presentation.chart_type is ChartType.PIE
    points = presentation.option["series"][0]["data"]
    assert [point["name"] for point in points] == ["SP", "RJ"]
    assert [point["value"] for point in points] == [100, 80]


def test_caveats_carry_disclosure_truncation_and_version(presenter: ChartPresenter) -> None:
    payload = _input(
        [ColumnMeta(name="state", type_name="category"), ColumnMeta(name="gmv", type_name="decimal")],
        [["SP", Decimal("100")]],
        disclosure="该指标默认取已支付订单。",
        truncated=True,
        plan={"limit": 10},
        bundle_version="2026.10.27.1",
        time_range={"start": "2017-01-01", "end": "2018-12-31"},
    )
    caveats = presenter.build(payload).caveats
    text = "\n".join(caveats)
    assert "该指标默认取已支付订单。" in text
    assert "LIMIT" in text
    assert "Top-10" in text
    assert "2026.10.27.1" in text
    assert "2017-01-01" in text and "2018-12-31" in text


def test_chart_type_is_none_when_preference_none(presenter: ChartPresenter) -> None:
    payload = _input(
        [ColumnMeta(name="state", type_name="category"), ColumnMeta(name="gmv", type_name="decimal")],
        [["SP", Decimal("100")]],
        chart_preference="none",
    )
    presentation = presenter.build(payload)
    assert presentation.chart_type is None
    assert presentation.option is None
    assert presentation.insight_text
