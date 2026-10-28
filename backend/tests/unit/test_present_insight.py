"""结论文案：数字必须来自结果行、单位来自 `metric_catalog`、禁因果/预测词。

`insight.text` 是**描述性**结论 —— 它只复述结果里的数，不解释原因、不预测未来。
本文件对三类模板（单值 / 排名 / 时序）各钉一遍，并做一次禁用词全扫。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.contracts import ColumnMeta, PresentationInput
from app.present.presenter import ChartPresenter

_FORBIDDEN = ("因为", "导致", "预计", "由于", "将会")

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


def test_kpi_insight_uses_value_and_display_name(presenter: ChartPresenter) -> None:
    payload = _input([ColumnMeta(name="gmv", type_name="decimal")], [[Decimal("1234.5")]])
    text = presenter.build(payload).insight_text
    assert "GMV" in text
    assert "1,234.50" in text
    assert "¥" in text


def test_ranking_insight_names_the_max_category(presenter: ChartPresenter) -> None:
    rows = [["SP", Decimal("100")], ["RJ", Decimal("80")], ["MG", Decimal("60")]]
    payload = _input(
        [ColumnMeta(name="state", type_name="category"), ColumnMeta(name="gmv", type_name="decimal")],
        rows,
        question="各州 GMV",
    )
    text = presenter.build(payload).insight_text
    assert "SP" in text
    assert "最高" in text
    assert "100.00" in text
    assert "3 项" in text


def test_line_insight_reports_first_last_and_peak(presenter: ChartPresenter) -> None:
    rows = [["2017-01", 10], ["2017-02", 20], ["2017-03", 15]]
    payload = _input(
        [ColumnMeta(name="month", type_name="date"), ColumnMeta(name="order_cnt", type_name="number")],
        rows,
    )
    text = presenter.build(payload).insight_text
    assert "2017-01" in text
    assert "2017-03" in text
    assert "峰值出现在 2017-02" in text
    assert "20单" in text


def test_table_insight_reports_row_count(presenter: ChartPresenter) -> None:
    rows = [[f"state_{index}", index] for index in range(25)]
    payload = _input(
        [ColumnMeta(name="state", type_name="category"), ColumnMeta(name="order_cnt", type_name="number")],
        rows,
    )
    text = presenter.build(payload).insight_text
    assert "25 行" in text


def test_insight_never_uses_causal_or_predictive_words(presenter: ChartPresenter) -> None:
    samples = [
        _input([ColumnMeta(name="gmv", type_name="decimal")], [[Decimal("1")]]),
        _input(
            [
                ColumnMeta(name="state", type_name="category"),
                ColumnMeta(name="gmv", type_name="decimal"),
            ],
            [["SP", Decimal("10")], ["RJ", Decimal("20")]],
        ),
        _input(
            [
                ColumnMeta(name="month", type_name="date"),
                ColumnMeta(name="order_cnt", type_name="number"),
            ],
            [["2017-01", 1], ["2017-02", 2], ["2017-03", 3]],
        ),
    ]
    for payload in samples:
        text = presenter.build(payload).insight_text
        for word in _FORBIDDEN:
            assert word not in text, f"结论出现禁用词 {word!r}: {text}"
