"""图内呈现：图表选择 + ECharts option 子集 + 描述性结论 + caveats。

**纯函数、无 LLM、无 IO**（`PresenterPort` 的实现）。输入只读 `PresentationInput`
（rows 已脱敏），输出 `Presentation`；不写 state、不查库、不编造 citations。

选择规则（计划 §3.3.2 第 3 条，7 种形态，不自创第 8 种）：
空结果 → 无图；`chart_preference=none` → 无图；分类数 >50 → 只表 + caveat；
行 >20 或列 >6 → table；单行单数值 → kpi；首列时间型且 ≥3 点 → line；
分类 + 单数值（占比/构成/份额或偏好 pie，≤8 类且指标可加）→ pie；
分类 + 单数值 → bar；分类 + ≥2 数值（构成/偏好 stacked_bar）→ stacked_bar，否则 grouped_bar。

option 只用 `title/tooltip/legend/grid/xAxis/yAxis/series`（A.10 + 06 §6.5 白名单），
禁止 formatter 字符串；数值一律转 int/float（`events._jsonable` 会把 Decimal 变成字符串）。
金额轴写 `yAxis.name`（单位来自装配点注入的 `metric_catalog`）。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.core.contracts import ColumnMeta, Presentation, PresentationInput
from app.core.enums import ChartType
from app.present.checks import run_result_checks

_NUMERIC_TYPES: Final[frozenset[str]] = frozenset({"number", "decimal"})
_TIME_TYPES: Final[frozenset[str]] = frozenset({"date", "datetime", "time"})
_TIME_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}(-\d{2}(-\d{2})?)?([ T].*)?$"
)
_PIE_WORDS: Final[tuple[str, ...]] = ("占比", "构成", "份额")
_ADDITIVE_AGG: Final[frozenset[str]] = frozenset({"sum", "count", "count_distinct"})
_ALLOWED_OPTION_KEYS: Final[frozenset[str]] = frozenset(
    {"title", "tooltip", "legend", "grid", "xAxis", "yAxis", "series"}
)
ALLOWED_OPTION_KEYS = _ALLOWED_OPTION_KEYS
_SKIP_TEXT: Final[dict[str, str]] = {
    "empty_result": "结果为空，未出图。",
    "preference_none": "按请求未生成图表。",
    "too_many_categories": "分类数超过 50，未聚合、未出图，仅展示明细表。",
    "too_many_rows": "结果行数超过 20，仅展示明细表。",
    "too_many_columns": "结果列数超过 6，仅展示明细表。",
    "no_numeric": "结果没有数值列，未出图。",
    "preference_incompatible": "请求的图表类型与数据形状不兼容，已回退到自动选择。",
}


class ChartPresenter:
    """`PresenterPort` 的确定性实现。`metric_catalog` 由装配点注入（name → 元数据）。"""

    def __init__(self, *, metric_catalog: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._catalog: dict[str, Mapping[str, Any]] = {
            str(name).lower(): value
            for name, value in (metric_catalog or {}).items()
            if isinstance(value, Mapping)
        }

    # -- 入口 ---------------------------------------------------------------

    def build(self, payload: PresentationInput) -> Presentation:
        checks = run_result_checks(payload)
        caveats = _base_caveats(payload)
        caveats.extend(v.message for v in checks if v.code != "empty_result")
        blocking = next((v for v in checks if v.severity == "block"), None)

        if not payload.rows:
            caveats.append(_SKIP_TEXT["empty_result"])
            return Presentation(
                chart_type=None,
                option=None,
                insight_text="当前条件下没有数据。",
                caveats=tuple(caveats),
                chart_skipped_reason="empty_result",
            )

        if (payload.chart_preference or "auto").strip().lower() == "none":
            caveats.append(_SKIP_TEXT["preference_none"])
            return Presentation(
                chart_type=None,
                option=None,
                insight_text=self._insight(payload, ChartType.TABLE),
                caveats=tuple(caveats),
                chart_skipped_reason="preference_none",
            )

        if blocking is not None:
            caveats.append("结果校验未通过，已降级为只出表。")
            return Presentation(
                chart_type=ChartType.TABLE,
                option={},
                insight_text=blocking.message,
                caveats=tuple(caveats),
                chart_skipped_reason=f"check:{blocking.code}",
            )

        chart_type, reason = self._select(payload, caveats)
        if reason is not None:
            caveats.append(_SKIP_TEXT.get(reason, reason))
        if chart_type is ChartType.BAR and any(word in payload.question for word in _PIE_WORDS):
            caveats.append("指标不可加或分类数超过 8，未按占比出饼图。")
        option, option_caveats = self._option(payload, chart_type)
        caveats.extend(option_caveats)
        return Presentation(
            chart_type=chart_type,
            option=option,
            insight_text=self._insight(payload, chart_type),
            caveats=tuple(caveats),
            chart_skipped_reason=reason,
        )

    # -- 选择 ---------------------------------------------------------------

    def _select(
        self, payload: PresentationInput, caveats: list[str]
    ) -> tuple[ChartType, str | None]:
        rows = payload.rows
        columns = payload.columns
        n_rows = len(rows)
        n_cols = len(columns)
        numeric = _numeric_indexes(columns)
        first = columns[0] if columns else None
        first_is_numeric = first is not None and first.type_name in _NUMERIC_TYPES
        preference = (payload.chart_preference or "auto").strip().lower()

        if not numeric:
            return ChartType.TABLE, "no_numeric"

        if not first_is_numeric and first is not None:
            distinct = len({row[0] for row in rows if row and row[0] is not None})
            if distinct > 50:
                return ChartType.TABLE, "too_many_categories"

        if preference == "table":
            return ChartType.TABLE, "too_many_rows" if n_rows > 20 else None
        if preference == "kpi":
            if n_rows == 1 and n_cols == 1:
                return ChartType.KPI, None
            caveats.append(_SKIP_TEXT["preference_incompatible"] + "（kpi 要求单行单列）")
            return self._auto_select(payload, numeric, first)

        if n_rows > 20:
            return ChartType.TABLE, "too_many_rows"
        if n_cols > 6:
            return ChartType.TABLE, "too_many_columns"

        if n_rows == 1 and n_cols == 1:
            return ChartType.KPI, None

        is_time = first is not None and _is_time_column(first, rows)
        if preference == "line":
            if is_time and n_rows >= 3:
                return ChartType.LINE, None
            caveats.append(_SKIP_TEXT["preference_incompatible"] + "（line 要求时间列 ≥3 点）")
            return self._auto_select(payload, numeric, first)
        if preference == "bar":
            if not first_is_numeric and len(numeric) == 1:
                return ChartType.BAR, None
            caveats.append(_SKIP_TEXT["preference_incompatible"] + "（bar 要求分类 + 单数值）")
            return self._auto_select(payload, numeric, first)
        if preference == "stacked_bar":
            if not first_is_numeric and len(numeric) >= 2:
                return ChartType.STACKED_BAR, None
            caveats.append(
                _SKIP_TEXT["preference_incompatible"] + "（stacked_bar 要求分类 + ≥2 数值）"
            )
            return self._auto_select(payload, numeric, first)
        if preference == "pie":
            if self._pie_ok(payload, first, numeric):
                return ChartType.PIE, None
            caveats.append(
                _SKIP_TEXT["preference_incompatible"]
                + "（pie 要求分类 + 单数值、≤8 类且指标可加）"
            )
            return self._auto_select(payload, numeric, first)
        return self._auto_select(payload, numeric, first)

    def _auto_select(
        self,
        payload: PresentationInput,
        numeric: tuple[int, ...],
        first: ColumnMeta | None,
    ) -> tuple[ChartType, str | None]:
        rows = payload.rows
        first_is_numeric = first is not None and first.type_name in _NUMERIC_TYPES
        is_time = first is not None and _is_time_column(first, rows)
        if is_time and len(rows) >= 3:
            return ChartType.LINE, None
        if first_is_numeric or first is None:
            return ChartType.TABLE, "no_numeric"

        if len(numeric) == 1:
            if self._pie_ok(payload, first, numeric):
                return ChartType.PIE, None
            return ChartType.BAR, None

        if "构成" in payload.question or (
            payload.chart_preference or ""
        ).strip().lower() == "stacked_bar":
            return ChartType.STACKED_BAR, None
        return ChartType.GROUPED_BAR, None

    def _pie_ok(
        self,
        payload: PresentationInput,
        first: ColumnMeta | None,
        numeric: tuple[int, ...],
    ) -> bool:
        if first is None or first.type_name in _NUMERIC_TYPES or len(numeric) != 1:
            return False
        distinct = len({row[0] for row in payload.rows if row and row[0] is not None})
        entry = self._entry(payload, payload.columns[numeric[0]])
        aggregation = str(entry.get("aggregation") or "").lower()
        additive = aggregation in _ADDITIVE_AGG
        wants = any(word in payload.question for word in _PIE_WORDS)
        preference = (payload.chart_preference or "").strip().lower()
        return distinct <= 8 and additive and (wants or preference == "pie")

    # -- option -------------------------------------------------------------

    def _option(
        self, payload: PresentationInput, chart_type: ChartType
    ) -> tuple[Mapping[str, Any], tuple[str, ...]]:
        numeric = _numeric_indexes(payload.columns)
        if chart_type is ChartType.TABLE:
            return {}, ()
        if chart_type is ChartType.KPI:
            label = self._label(payload, numeric[0]) if numeric else "结果"
            return {"title": {"text": label}}, ()

        labels = [str(row[0]) if row and row[0] is not None else "—" for row in payload.rows]
        names = [self._series_name(payload, index) for index in numeric]
        axis_name, axis_caveats = self._axis_name(payload, numeric, names)

        if chart_type is ChartType.PIE:
            index = numeric[0]
            data = [
                {"name": label, "value": _chart_number(row[index])}
                for label, row in zip(labels, payload.rows, strict=True)
            ]
            return (
                {
                    "title": {"text": names[0]},
                    "tooltip": {"trigger": "item"},
                    "legend": {"data": labels},
                    "series": [
                        {
                            "name": names[0],
                            "type": "pie",
                            "radius": ["40%", "70%"],
                            "data": data,
                        }
                    ],
                },
                axis_caveats,
            )

        series: list[Mapping[str, Any]] = []
        for offset, index in enumerate(numeric):
            item: dict[str, Any] = {
                "name": names[offset],
                "type": "line" if chart_type is ChartType.LINE else "bar",
                "data": [_chart_number(row[index]) for row in payload.rows],
            }
            if chart_type is ChartType.LINE:
                item["smooth"] = False
            if chart_type is ChartType.STACKED_BAR:
                item["stack"] = "total"
            series.append(item)

        option: dict[str, Any] = {
            "title": {"text": names[0] if len(names) == 1 else "分指标对比"},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 16, "right": 16, "bottom": 24, "containLabel": True},
            "xAxis": {
                "type": "category",
                "data": labels,
                "name": payload.columns[0].name if payload.columns else "",
            },
            "yAxis": {"type": "value", "name": axis_name},
            "series": series,
        }
        if len(series) > 1:
            option["legend"] = {"data": names}
        return option, axis_caveats

    def _axis_name(
        self, payload: PresentationInput, numeric: tuple[int, ...], names: list[str]
    ) -> tuple[str, tuple[str, ...]]:
        units = {
            str(self._entry(payload, payload.columns[index]).get("unit") or "")
            for index in numeric
        }
        units.discard("")
        if len(units) == 1:
            unit = next(iter(units))
            label = names[0] if len(names) == 1 else "值"
            return f"{label}（{unit}）", ()
        if len(units) > 1:
            return "值", ("多指标单位不同，坐标轴未标单一单位。",)
        return (names[0] if len(names) == 1 else "值"), ()

    # -- 结论 ---------------------------------------------------------------

    def _insight(self, payload: PresentationInput, chart_type: ChartType) -> str:
        rows = payload.rows
        if not rows:
            return "当前条件下没有数据。"
        numeric = _numeric_indexes(payload.columns)
        if chart_type is ChartType.KPI or (len(rows) == 1 and len(numeric) == 1):
            kpi_index = numeric[0] if numeric else 0
            label = self._label(payload, kpi_index)
            unit = self._unit(payload, kpi_index)
            return f"{label}为 {_format_value(rows[0][kpi_index], unit)}。"
        if chart_type is ChartType.TABLE:
            return f"共 {len(rows)} 行，按明细表展示。"

        index = numeric[0] if numeric else None
        if index is None:
            return f"共 {len(rows)} 行，按明细表展示。"
        label = self._label(payload, index)
        unit = self._unit(payload, index)
        if chart_type is ChartType.LINE:
            first = rows[0][index]
            last = rows[-1][index]
            peak_index = max(range(len(rows)), key=lambda i: _sort_key(rows[i][index]))
            first_label = _cell_label(rows[0][0])
            last_label = _cell_label(rows[-1][0])
            peak_label = _cell_label(rows[peak_index][0])
            return (
                f"{first_label} 至 {last_label}，{label} 从 {_format_value(first, unit)} "
                f"变为 {_format_value(last, unit)}，峰值出现在 {peak_label}"
                f"（{_format_value(rows[peak_index][index], unit)}）。"
            )
        peak_index = max(range(len(rows)), key=lambda i: _sort_key(rows[i][index]))
        dimension = payload.columns[0].name if payload.columns else "分类"
        return (
            f"按 {dimension} 看，{_cell_label(rows[peak_index][0])} 的 {label} 最高"
            f"（{_format_value(rows[peak_index][index], unit)}），共 {len(rows)} 项。"
        )

    # -- 指标元数据 ---------------------------------------------------------

    def _entry(self, payload: PresentationInput, column: ColumnMeta) -> Mapping[str, Any]:
        direct = self._catalog.get(column.name.lower())
        if direct is not None:
            return direct
        plan_names = [
            str(item.get("name")) for item in payload.metric_meta if item.get("name")
        ]
        if len(plan_names) == 1:
            return self._catalog.get(plan_names[0].lower(), {})
        return {}

    def _label(self, payload: PresentationInput, index: int) -> str:
        column = payload.columns[index]
        entry = self._entry(payload, column)
        return str(entry.get("display_name") or column.name)

    def _unit(self, payload: PresentationInput, index: int) -> str:
        entry = self._entry(payload, payload.columns[index])
        return str(entry.get("unit") or "")

    def _series_name(self, payload: PresentationInput, index: int) -> str:
        return self._label(payload, index)


# -- 纯工具 -----------------------------------------------------------------


def _numeric_indexes(columns: tuple[ColumnMeta, ...]) -> tuple[int, ...]:
    return tuple(
        index for index, column in enumerate(columns) if column.type_name in _NUMERIC_TYPES
    )


def _is_time_column(column: ColumnMeta, rows: tuple[tuple[Any, ...], ...]) -> bool:
    if column.type_name in _TIME_TYPES:
        return True
    values = [row[0] for row in rows if row and row[0] is not None]
    if not values or column.type_name in _NUMERIC_TYPES:
        return False
    return all(
        isinstance(value, str) and _TIME_RE.match(value.strip()) for value in values
    )


def _cell_label(value: Any) -> str:
    return "—" if value is None else str(value)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else Decimal(str(value))
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None
    return None


def _chart_number(value: Any) -> int | float | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    if parsed == parsed.to_integral_value() and abs(parsed) <= Decimal(2**53 - 1):
        return int(parsed)
    number = float(parsed)
    return number if math.isfinite(number) else None


def _sort_key(value: Any) -> Decimal:
    parsed = _decimal(value)
    return parsed if parsed is not None else Decimal("-Infinity")


def _format_value(value: Any, unit: str) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "—"
    if unit == "CNY":
        return f"¥{parsed:,.2f}"
    if unit in {"分", "%"}:
        return f"{parsed:,.2f}{unit}"
    if unit in {"单", "件", "g"}:
        return f"{parsed:,.0f}{unit}"
    if parsed == parsed.to_integral_value():
        return f"{parsed:,.0f}"
    return f"{parsed:,.2f}"


def _base_caveats(payload: PresentationInput) -> list[str]:
    caveats: list[str] = []
    if payload.disclosure:
        caveats.append(payload.disclosure)
    if payload.truncated:
        caveats.append("结果按 LIMIT 截断，以下结论仅基于当前返回行。")
    limit = payload.plan.get("limit") if payload.plan is not None else None
    if limit is not None:
        caveats.append(f"按计划 Top-{limit} 展示。")
    if payload.bundle_version:
        caveats.append(f"语义包版本 {payload.bundle_version}。")
    if payload.time_range:
        start = payload.time_range.get("start")
        end = payload.time_range.get("end")
        if start or end:
            caveats.append(f"时间范围 {start or '…'} 至 {end or '…'}。")
    return caveats


__all__ = ["ALLOWED_OPTION_KEYS", "ChartPresenter"]
