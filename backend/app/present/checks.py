"""结果级校验（最小版，U-149）—— **纯函数、无 IO**。

四条判据：空结果 / 全 NULL / 单行 KPI 异常 / 守恒式。
⚠️ 守恒式只在结果**自带合计行**且 `plan.limit` 为空、`truncated=False` 时校验；
presenter 无 IO，拿不到库级总量（第二条 SQL 超出本契约），无基准就**跳过**而不是猜。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.core.contracts import PresentationInput

_NUMERIC_TYPES: Final[frozenset[str]] = frozenset({"number", "decimal"})
_TOTAL_LABELS: Final[frozenset[str]] = frozenset({"合计", "总计", "全部", "all", "total"})
_COUNT_HINTS: Final[tuple[str, ...]] = ("cnt", "count", "量", "件")


@dataclass(frozen=True, slots=True)
class CheckViolation:
    """一条校验结论。`severity`: info（正常提示）/ warn（可疑）/ block（不出图）。"""

    code: str
    severity: str
    message: str
    detail: Mapping[str, Any] = field(default_factory=dict)


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


def numeric_indexes(columns: tuple[Any, ...]) -> tuple[int, ...]:
    return tuple(
        index
        for index, column in enumerate(columns)
        if str(getattr(column, "type_name", "")) in _NUMERIC_TYPES
    )


def _is_count_metric(payload: PresentationInput) -> bool:
    for item in payload.metric_meta:
        name = str(item.get("name") or "").lower()
        if any(hint in name for hint in _COUNT_HINTS):
            return True
    return False


def _find_total_row(payload: PresentationInput) -> int | None:
    if not payload.rows or not payload.columns:
        return None
    for index, row in enumerate(payload.rows):
        first = row[0] if row else None
        if isinstance(first, str) and first.strip().lower() in _TOTAL_LABELS:
            return index
    return None


def run_result_checks(payload: PresentationInput) -> tuple[CheckViolation, ...]:
    violations: list[CheckViolation] = []

    if not payload.rows:
        return (
            CheckViolation(
                code="empty_result",
                severity="info",
                message="当前条件下没有数据。",
                detail={"row_count": payload.row_count},
            ),
        )

    all_null = all(cell is None for row in payload.rows for cell in row)
    if all_null:
        violations.append(
            CheckViolation(
                code="all_null",
                severity="block",
                message="结果全部为空值，无法生成图表或结论。",
                detail={"rows": len(payload.rows)},
            )
        )

    numeric = numeric_indexes(payload.columns)
    if (
        not all_null
        and len(payload.rows) == 1
        and len(payload.columns) == 1
        and numeric
    ):
        value = _decimal(payload.rows[0][0])
        if value is None:
            violations.append(
                CheckViolation(
                    code="kpi_anomaly",
                    severity="block",
                    message="单值结果不是有效数值，无法作为 KPI 展示。",
                )
            )
        elif value < 0 and _is_count_metric(payload):
            violations.append(
                CheckViolation(
                    code="kpi_anomaly",
                    severity="warn",
                    message="计数类指标出现负值，请核对口径或数据。",
                    detail={"value": str(value)},
                )
            )

    limit = None
    if payload.plan is not None:
        limit = payload.plan.get("limit")
    conservation_skipped = payload.truncated or limit is not None
    total_index = _find_total_row(payload)
    if not conservation_skipped and total_index is not None and numeric:
        total_row = payload.rows[total_index]
        parts = [row for index, row in enumerate(payload.rows) if index != total_index]
        for column_index in numeric:
            total = _decimal(total_row[column_index])
            if total is None:
                continue
            part_values: list[Decimal] = []
            for row in parts:
                value = _decimal(row[column_index])
                if value is not None:
                    part_values.append(value)
            part_sum = sum(part_values, Decimal(0))
            tolerance = max(abs(total) * Decimal("1e-6"), Decimal("1e-9"))
            if abs(part_sum - total) > tolerance:
                violations.append(
                    CheckViolation(
                        code="conservation",
                        severity="warn",
                        message=(
                            f"守恒式不成立：{payload.columns[column_index].name} "
                            f"分项之和 {part_sum} ≠ 合计 {total}。"
                        ),
                        detail={
                            "column": payload.columns[column_index].name,
                            "parts_sum": str(part_sum),
                            "total": str(total),
                        },
                    )
                )

    return tuple(violations)
