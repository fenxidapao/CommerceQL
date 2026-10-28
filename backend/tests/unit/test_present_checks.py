"""结果级校验：4 条判据 + 守恒式的 4 条跳过路径。

⚠️ 守恒式在"没有合计行 / 有 `plan.limit` / `truncated`"时**必须跳过**：
presenter 无 IO，拿不到库级总量（第二条 SQL 超出契约）；无基准时猜一个
"不守恒"会把正常的分页结果误报成错误。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.contracts import ColumnMeta, PresentationInput
from app.present.checks import CheckViolation, run_result_checks
from app.present.presenter import ChartPresenter


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


def _codes(violations: tuple[CheckViolation, ...]) -> list[str]:
    return [item.code for item in violations]


# ---------------------------------------------------------------------------
# 判据 1：空结果
# ---------------------------------------------------------------------------


def test_empty_result_is_info_not_block() -> None:
    violations = run_result_checks(_input([ColumnMeta(name="gmv", type_name="decimal")], []))
    assert _codes(violations) == ["empty_result"]
    assert violations[0].severity == "info"


# ---------------------------------------------------------------------------
# 判据 2：全 NULL
# ---------------------------------------------------------------------------


def test_all_cells_null_blocks() -> None:
    payload = _input(
        [
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="gmv", type_name="decimal"),
        ],
        [[None, None], [None, None]],
    )
    violations = run_result_checks(payload)
    assert _codes(violations) == ["all_null"]
    assert violations[0].severity == "block"


# ---------------------------------------------------------------------------
# 判据 3：单行 KPI 异常
# ---------------------------------------------------------------------------


def test_non_numeric_single_value_blocks() -> None:
    payload = _input([ColumnMeta(name="gmv", type_name="decimal")], [["not-a-number"]])
    violations = run_result_checks(payload)
    assert _codes(violations) == ["kpi_anomaly"]
    assert violations[0].severity == "block"


def test_non_finite_single_value_blocks() -> None:
    payload = _input([ColumnMeta(name="gmv", type_name="decimal")], [[float("inf")]])
    violations = run_result_checks(payload)
    assert _codes(violations) == ["kpi_anomaly"]
    assert violations[0].severity == "block"


def test_negative_count_is_warn_only() -> None:
    payload = _input(
        [ColumnMeta(name="order_cnt", type_name="number")],
        [[-5]],
        metric_meta=({"name": "order_cnt"},),
    )
    violations = run_result_checks(payload)
    assert _codes(violations) == ["kpi_anomaly"]
    assert violations[0].severity == "warn"


# ---------------------------------------------------------------------------
# 判据 4：守恒式（合计行存在时）
# ---------------------------------------------------------------------------


def _conservation_payload(total: Decimal, **overrides: Any) -> PresentationInput:
    return _input(
        [
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="gmv", type_name="decimal"),
        ],
        [["SP", Decimal("10")], ["RJ", Decimal("20")], ["合计", total]],
        **overrides,
    )


def test_conservation_passes_when_parts_equal_total() -> None:
    assert run_result_checks(_conservation_payload(Decimal("30"))) == ()


def test_conservation_warns_when_parts_do_not_match() -> None:
    violations = run_result_checks(_conservation_payload(Decimal("31")))
    assert _codes(violations) == ["conservation"]
    assert violations[0].severity == "warn"
    assert violations[0].detail["total"] == "31"


def test_conservation_skipped_without_total_row() -> None:
    payload = _input(
        [
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="gmv", type_name="decimal"),
        ],
        [["SP", Decimal("10")], ["RJ", Decimal("20")]],
    )
    assert run_result_checks(payload) == ()


def test_conservation_skipped_when_plan_has_limit() -> None:
    payload = _conservation_payload(Decimal("31"), plan={"limit": 10})
    assert run_result_checks(payload) == ()


def test_conservation_skipped_when_truncated() -> None:
    payload = _conservation_payload(Decimal("31"), truncated=True)
    assert run_result_checks(payload) == ()


# ---------------------------------------------------------------------------
# 与 presenter 的接缝：block 级 → 只出表 + 稳定原因码
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([[None, None]], "check:all_null"),
        ([["not-a-number"]], "check:kpi_anomaly"),
    ],
)
def test_presenter_downgrades_blocking_violation_to_table(rows: list[list[Any]], reason: str) -> None:
    if len(rows[0]) == 1:
        columns = [ColumnMeta(name="gmv", type_name="decimal")]
    else:
        columns = [
            ColumnMeta(name="state", type_name="category"),
            ColumnMeta(name="gmv", type_name="decimal"),
        ]
    presentation = ChartPresenter(metric_catalog={}).build(_input(columns, rows))
    assert presentation.chart_type is not None
    assert str(presentation.chart_type) == "table"
    assert presentation.chart_skipped_reason == reason
