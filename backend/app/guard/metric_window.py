"""指标窗口强制 —— 让 `metrics[].window` 真正生效（W75-1 / QA D2）。

--------------------------------------------------------------------------
一、为什么需要本模块
--------------------------------------------------------------------------
语义包给 `repurchase_rate_90d` 声明了 `window: "90 days"`（`bundle:613`）与
「周期固定 90 天，不接受运行时改窗口」（`bundle:614`），但 **W73-4 实证：没有任何
代码读该字段** ⇒ 同一指标两次问答的时间窗由模型即兴决定 —— M-IDX-09 只有下界
（统计到数据末尾），M-IDX-10 恰好带了上界，两条系统读数互相不可比。

--------------------------------------------------------------------------
二、判据（逐字对齐派单 §96.8 W75-1）
--------------------------------------------------------------------------
- 有 `window` 且 SQL 时间谓词里有 `time_basis` 的**起始时间** ⇒ 该 SELECT 必须含
  `time_basis < start + window`；
- **缺失则补**、**不一致则修**（只改写上界那一个比较，不动其它谓词）、
  **已有且一致则不动**；
- **无起始时间** ⇒ 不加（"无起始时间不误加"）；
- `window` 或起始时间**解析不出** ⇒ 抛 `MetricWindowError`（调用方 fail-closed，
  **不得静默忽略**）；
- 多指标对同一时间基准给出不同窗口 ⇒ 判冲突拒绝（同一条 WHERE 没有正确答案）。

--------------------------------------------------------------------------
三、为什么按 SELECT 逐个判
--------------------------------------------------------------------------
上界可能写在任意嵌套层（M-IDX-09 的 `pay_time >=` 在子查询里，外层只有聚合）。
起始时间在哪个 SELECT，上界就补在哪个 SELECT —— 挂到外层会引用不存在的列。

--------------------------------------------------------------------------
四、值一律走绑定参数（N-04）
--------------------------------------------------------------------------
补/修出来的上界值用新占位符 `%(window_end_<metric>)s` 承载，不写 SQL 字面量：
一是 N-04「一律走占位符」，二是 R14 的白名单不必为它开新常量。
旧参数（如被修掉的 `%(end_ts)s`）原样留在参数字典里 —— 未被引用即无副作用，
删除反而可能误伤同一参数在别处的引用。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

__all__ = [
    "MetricWindowError",
    "MetricWindowRule",
    "WindowEnforcement",
    "enforce_metric_windows",
]

#: 只认**固定天数**的单位。`month` / `quarter` / `year` 是日历歧义（28–31 天、闰年），
#: 换算成天数必须由语义包显式给出 ⇒ 不在本模块猜，交给 fail-closed。
_WINDOW_RE = re.compile(r"^\s*(\d+)\s*(day|days|week|weeks)\s*$", re.IGNORECASE)

#: 归一后的比较方向。`ge`/`gt` = 起始时间；`le`/`lt` = 上界；`eq` 不参与窗口判据
#: （`pay_time = '2026-06-01'` 是单日点查询，不是一段窗口的起点 —— 补上界会改题意）。
_DIRECTION = {
    exp.GTE: "ge",
    exp.GT: "gt",
    exp.LTE: "le",
    exp.LT: "lt",
    exp.EQ: "eq",
}
_FLIP = {"ge": "le", "gt": "lt", "le": "ge", "lt": "gt", "eq": "eq"}


class MetricWindowError(ValueError):
    """窗口无法强制（fail-closed 的唯一信号）。`code` 供节点写进 `intent_detail`。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MetricWindowRule:
    """一条指标窗口声明（`Metric.window` + `Metric.time_basis`）。"""

    metric: str
    time_basis: str
    window: str


@dataclass(frozen=True, slots=True)
class WindowEnforcement:
    """强制结果。`applied` 为空 ⇒ SQL/参数逐字未动（`changed` 为 False）。"""

    sql: str
    params: dict[str, Any]
    applied: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


class _Unresolved:
    __slots__ = ()


_UNRESOLVED = _Unresolved()


def enforce_metric_windows(
    sql: str,
    params: Mapping[str, Any] | None,
    rules: Sequence[MetricWindowRule],
) -> WindowEnforcement:
    """按 `rules` 强制 SQL 的时间上界。

    `rules` 只应包含**声明了 window** 的指标（调用方过滤）；空规则 ⇒ 原样返回。
    解析失败、窗口/起始时间解析不出、多规则冲突 ⇒ `MetricWindowError`。
    """

    base_params = dict(params or {})
    active = [rule for rule in rules if rule.window]
    if not active:
        return WindowEnforcement(sql, base_params, ())

    windows = [(rule, _window_days(rule)) for rule in active]
    try:
        root = sqlglot.parse_one(sql, dialect="postgres")
    except ParseError as exc:  # gate1 也会拒，但这里先给出**归因到窗口**的信号
        raise MetricWindowError("sql_unparsable", str(exc)) from exc
    if root is None:
        raise MetricWindowError("sql_unparsable", "空语句")

    out_params = dict(base_params)
    applied: list[str] = []
    for select in list(root.find_all(exp.Select)):
        where = select.args.get("where")
        if where is None:
            continue
        applied.extend(_enforce_select(where, windows, base_params, out_params))

    if not applied:
        return WindowEnforcement(sql, base_params, ())
    return WindowEnforcement(root.sql(dialect="postgres"), out_params, tuple(applied))


@dataclass(frozen=True, slots=True)
class _Bound:
    """一条已归一方向的比较：`op` ∈ `ge/gt/le/lt/eq`，`value` = 值侧节点。"""

    op: str
    col: exp.Column
    node: exp.Expression
    value: exp.Expression


def _enforce_select(
    where: exp.Where,
    windows: Sequence[tuple[MetricWindowRule, int]],
    base_params: Mapping[str, Any],
    out_params: dict[str, Any],
) -> list[str]:
    """对单个 SELECT 强制窗口。返回该 SELECT 的动作记录。"""

    bounds = _comparisons(where.this)
    applied: list[str] = []
    requirements: dict[str, tuple[date, str]] = {}

    for rule, days in windows:
        basis = rule.time_basis.strip().lower()
        if not basis:
            raise MetricWindowError(
                "time_basis_missing", f"指标 {rule.metric!r} 声明了 window 但没有 time_basis"
            )
        starts = [
            _date_value(bound.value, base_params, rule, "start")
            for bound in bounds
            if bound.op in ("ge", "gt") and bound.col.name.lower() == basis
        ]
        if not starts:
            continue  # 无起始时间 ⇒ 不误加（本 SELECT 也可能与窗口无关）
        expected = max(starts) + timedelta(days=days)

        previous = requirements.get(basis)
        if previous is not None and previous[0] != expected:
            raise MetricWindowError(
                "metric_window_conflict",
                f"指标 {previous[1]!r} 与 {rule.metric!r} 对 {basis} 给出不同窗口"
                f"（{previous[0].isoformat()} vs {expected.isoformat()}）",
            )
        if previous is not None:
            continue
        requirements[basis] = (expected, rule.metric)

        start_column = next(
            bound.col
            for bound in bounds
            if bound.op in ("ge", "gt") and bound.col.name.lower() == basis
        )
        upper = [
            bound for bound in bounds if bound.op in ("le", "lt") and bound.col.name.lower() == basis
        ]
        if not upper:
            _append_upper(where, start_column, rule, expected, out_params)
            applied.append(f"{rule.metric}|added|{basis}<{expected.isoformat()}")
            continue
        if (
            len(upper) == 1
            and upper[0].op == "lt"
            and _try_date(upper[0].value, base_params) == expected
        ):
            continue  # 已有正确上界 ⇒ 不动
        for bound in upper:
            _repair_upper(bound.node, start_column, rule, expected, out_params)
        applied.append(f"{rule.metric}|repaired|{basis}<{expected.isoformat()}")
    return applied


def _comparisons(where: exp.Expression) -> list[_Bound]:
    bounds: list[_Bound] = []
    for node in _flatten_and(where):
        for cls, op in _DIRECTION.items():
            if not isinstance(node, cls):
                continue
            left, right = node.this, node.expression
            if isinstance(left, exp.Column) and not isinstance(right, exp.Column):
                bounds.append(_Bound(op=op, col=left, node=node, value=right))
            elif isinstance(right, exp.Column) and not isinstance(left, exp.Column):
                bounds.append(_Bound(op=_FLIP[op], col=right, node=node, value=left))
            break
    return bounds


def _flatten_and(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.Paren):
        return _flatten_and(node.this)
    if isinstance(node, exp.And):
        return [*_flatten_and(node.this), *_flatten_and(node.expression)]
    return [node]


def _scalar(node: exp.Expression, params: Mapping[str, Any]) -> Any:
    """字面量 / 占位符 / 显式 CAST 的内层 → 值；其余 → `_UNRESOLVED`。"""
    if isinstance(node, exp.Cast):
        return _scalar(node.this, params)
    if isinstance(node, exp.Paren):
        return _scalar(node.this, params)
    if isinstance(node, exp.Literal):
        return node.this if node.is_string else _UNRESOLVED
    if isinstance(node, exp.Placeholder):
        name = getattr(node.this, "name", None)
        if name is not None and name in params:
            return params[name]
    return _UNRESOLVED


def _date_value(
    node: exp.Expression,
    params: Mapping[str, Any],
    rule: MetricWindowRule,
    which: str,
) -> date:
    """起始边界 → `date`。解析不出 ⇒ fail-closed（派单原文：「不得静默忽略」）。"""

    raw = _scalar(node, params)
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and len(raw.strip()) >= 10:
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            pass
    raise MetricWindowError(
        f"{which}_unparsable",
        f"指标 {rule.metric!r} 的 {which} 边界解析不出日期："
        f"{node.sql(dialect='postgres')!r}",
    )


def _try_date(node: exp.Expression, params: Mapping[str, Any]) -> date | None:
    """上界的**非抛**解析（只用于"是否已一致"；解析不出 ⇒ 按不一致处理并改写）。"""

    raw = _scalar(node, params)
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and len(raw.strip()) >= 10:
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def _window_days(rule: MetricWindowRule) -> int:
    match = _WINDOW_RE.match(rule.window)
    if match is None:
        raise MetricWindowError(
            "window_unparsable",
            f"指标 {rule.metric!r} 的 window {rule.window!r} 不是受支持的固定天数表达",
        )
    count = int(match.group(1))
    if count <= 0:
        raise MetricWindowError(
            "window_unparsable", f"指标 {rule.metric!r} 的 window {rule.window!r} 非正数"
        )
    unit = match.group(2).lower()
    return count if unit.startswith("day") else count * 7


def _append_upper(
    where: exp.Where,
    basis_column: exp.Column,
    rule: MetricWindowRule,
    expected: date,
    out_params: dict[str, Any],
) -> None:
    predicate = exp.LT(
        this=exp.column(basis_column.name, table=basis_column.table or None),
        expression=_window_placeholder(rule, expected, out_params),
    )
    where.set("this", exp.And(this=where.this, expression=predicate))


def _repair_upper(
    node: exp.Expression,
    basis_column: exp.Column,
    rule: MetricWindowRule,
    expected: date,
    out_params: dict[str, Any],
) -> None:
    """把一个已有上界改写成 `basis < %(window_end_…)s`（值 = start + window）。"""

    node.replace(
        exp.LT(
            this=exp.column(basis_column.name, table=basis_column.table or None),
            expression=_window_placeholder(rule, expected, out_params),
        )
    )


def _window_placeholder(
    rule: MetricWindowRule, expected: date, out_params: dict[str, Any]
) -> exp.Placeholder:
    value = expected.isoformat()
    base = "window_end_" + re.sub(r"[^0-9A-Za-z_]", "_", rule.metric)
    name = base
    suffix = 2
    while name in out_params and out_params[name] != value:
        name = f"{base}_{suffix}"
        suffix += 1
    out_params[name] = value
    return exp.Placeholder(this=exp.to_identifier(name))
