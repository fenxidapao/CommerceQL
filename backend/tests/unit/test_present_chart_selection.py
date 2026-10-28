"""`ChartPresenter` 的形态选择：7 种 `chart_type` + 偏好兼容性 + 分类数闸门。

选择规则原文见 `app/present/presenter.py` 模块 docstring；本文件逐条钉住
"什么形状选什么图"，并钉住两条**回退**行为：偏好与形状不兼容不回退到空图，
而是落回自动选择并追加 caveat。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.contracts import ColumnMeta, PresentationInput
from app.core.enums import ChartType
from app.present.presenter import ChartPresenter

_CATALOG: dict[str, dict[str, Any]] = {
    "gmv": {"display_name": "GMV", "unit": "CNY", "aggregation": "sum"},
    "order_cnt": {"display_name": "订单量", "unit": "单", "aggregation": "sum"},
    "avg_price": {"display_name": "客单价", "unit": "CNY", "aggregation": "avg"},
}


def _col(name: str, type_name: str) -> ColumnMeta:
    return ColumnMeta(name=name, type_name=type_name)


def _input(
    columns: list[ColumnMeta],
    rows: list[list[Any]],
    **overrides: Any,
) -> PresentationInput:
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


def test_empty_rows_emit_no_chart(presenter: ChartPresenter) -> None:
    result = presenter.build(_input([_col("state", "category"), _col("gmv", "decimal")], []))
    assert result.chart_type is None
    assert result.chart_skipped_reason == "empty_result"


def test_preference_none_emits_no_chart(presenter: ChartPresenter) -> None:
    payload = _input(
        [_col("state", "category"), _col("gmv", "decimal")],
        [["SP", Decimal("100")]],
        chart_preference="none",
    )
    result = presenter.build(payload)
    assert result.chart_type is None
    assert result.chart_skipped_reason == "preference_none"
    assert result.insight_text


def test_single_numeric_cell_is_kpi(presenter: ChartPresenter) -> None:
    result = presenter.build(_input([_col("gmv", "decimal")], [[Decimal("1234.5")]]))
    assert result.chart_type is ChartType.KPI
    assert result.option == {"title": {"text": "GMV"}}
    assert result.chart_skipped_reason is None


def test_time_series_is_line(presenter: ChartPresenter) -> None:
    rows = [[f"2017-{month:02d}", 100 + month] for month in range(1, 13)]
    result = presenter.build(_input([_col("month", "date"), _col("order_cnt", "number")], rows))
    assert result.chart_type is ChartType.LINE
    series = result.option["series"]
    assert len(series) == 1
    assert series[0]["type"] == "line"
    assert len(series[0]["data"]) == 12


def test_string_time_like_first_column_is_line(presenter: ChartPresenter) -> None:
    rows = [["2017-01", 10], ["2017-02", 20], ["2017-03", 15]]
    result = presenter.build(_input([_col("month", "text"), _col("order_cnt", "number")], rows))
    assert result.chart_type is ChartType.LINE


def test_category_single_numeric_is_bar(presenter: ChartPresenter) -> None:
    rows = [["SP", Decimal("100")], ["RJ", Decimal("80")], ["MG", Decimal("60")]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("gmv", "decimal")],
            rows,
            question="2018 年各州 GMV 前十",
        )
    )
    assert result.chart_type is ChartType.BAR
    assert result.option["series"][0]["type"] == "bar"


def test_share_question_with_additive_metric_is_pie(presenter: ChartPresenter) -> None:
    rows = [["SP", Decimal("100")], ["RJ", Decimal("80")], ["MG", Decimal("60")]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("gmv", "decimal")],
            rows,
            question="各州 GMV 占比",
        )
    )
    assert result.chart_type is ChartType.PIE
    assert result.option["series"][0]["type"] == "pie"


def test_pie_falls_back_to_bar_when_metric_not_additive(presenter: ChartPresenter) -> None:
    rows = [["SP", Decimal("100")], ["RJ", Decimal("80")]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("avg_price", "decimal")],
            rows,
            question="各州客单价占比",
        )
    )
    assert result.chart_type is ChartType.BAR
    assert any("未按占比出饼图" in caveat for caveat in result.caveats)


def test_two_numeric_with_composition_question_is_stacked(presenter: ChartPresenter) -> None:
    rows = [["SP", Decimal("100"), 8], ["RJ", Decimal("80"), 6]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("gmv", "decimal"), _col("order_cnt", "number")],
            rows,
            question="各州 GMV 与订单量构成",
        )
    )
    assert result.chart_type is ChartType.STACKED_BAR
    assert all(series.get("stack") == "total" for series in result.option["series"])


def test_two_numeric_without_composition_is_grouped(presenter: ChartPresenter) -> None:
    rows = [["SP", Decimal("100"), 8], ["RJ", Decimal("80"), 6]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("gmv", "decimal"), _col("order_cnt", "number")],
            rows,
            question="各州 GMV 和订单量对比",
        )
    )
    assert result.chart_type is ChartType.GROUPED_BAR
    assert len(result.option["series"]) == 2
    assert "legend" in result.option


def test_more_than_50_categories_is_table_with_reason(presenter: ChartPresenter) -> None:
    rows = [[f"state_{index:02d}", index] for index in range(51)]
    result = presenter.build(_input([_col("state", "category"), _col("order_cnt", "number")], rows))
    assert result.chart_type is ChartType.TABLE
    assert result.chart_skipped_reason == "too_many_categories"
    assert any("50" in caveat for caveat in result.caveats)


def test_more_than_20_rows_is_table(presenter: ChartPresenter) -> None:
    rows = [[f"state_{index:02d}", index] for index in range(21)]
    result = presenter.build(_input([_col("state", "category"), _col("order_cnt", "number")], rows))
    assert result.chart_type is ChartType.TABLE
    assert result.chart_skipped_reason == "too_many_rows"


def test_more_than_6_columns_is_table(presenter: ChartPresenter) -> None:
    columns = [_col("state", "category")] + [
        _col(f"m{index}", "number") for index in range(6)
    ]
    rows = [["SP", 1, 2, 3, 4, 5, 6]]
    result = presenter.build(_input(columns, rows))
    assert result.chart_type is ChartType.TABLE
    assert result.chart_skipped_reason == "too_many_columns"


def test_no_numeric_column_is_table(presenter: ChartPresenter) -> None:
    rows = [["SP", "a"], ["RJ", "b"]]
    result = presenter.build(_input([_col("state", "category"), _col("note", "text")], rows))
    assert result.chart_type is ChartType.TABLE
    assert result.chart_skipped_reason == "no_numeric"


def test_explicit_pie_preference_is_honoured_when_shape_fits(presenter: ChartPresenter) -> None:
    rows = [["SP", 100], ["RJ", 80]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("gmv", "decimal")],
            rows,
            chart_preference="pie",
        )
    )
    assert result.chart_type is ChartType.PIE


def test_incompatible_pie_preference_falls_back_with_caveat(presenter: ChartPresenter) -> None:
    rows = [["SP", Decimal("100")], ["RJ", Decimal("80")]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("avg_price", "decimal")],
            rows,
            chart_preference="pie",
        )
    )
    assert result.chart_type is ChartType.BAR
    assert any("不兼容" in caveat for caveat in result.caveats)


def test_incompatible_line_preference_falls_back_with_caveat(presenter: ChartPresenter) -> None:
    rows = [["SP", 10], ["RJ", 20], ["MG", 15]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("order_cnt", "number")],
            rows,
            chart_preference="line",
        )
    )
    assert result.chart_type is ChartType.BAR
    assert any("不兼容" in caveat for caveat in result.caveats)


def test_bar_preference_on_time_series_is_honoured(presenter: ChartPresenter) -> None:
    rows = [["2017-01", 10], ["2017-02", 20], ["2017-03", 15]]
    result = presenter.build(
        _input(
            [_col("month", "date"), _col("order_cnt", "number")],
            rows,
            chart_preference="bar",
        )
    )
    assert result.chart_type is ChartType.BAR


def test_kpi_preference_with_wrong_shape_falls_back(presenter: ChartPresenter) -> None:
    rows = [["SP", 10], ["RJ", 20]]
    result = presenter.build(
        _input(
            [_col("state", "category"), _col("order_cnt", "number")],
            rows,
            chart_preference="kpi",
        )
    )
    assert result.chart_type is ChartType.BAR
    assert any("kpi" in caveat for caveat in result.caveats)
