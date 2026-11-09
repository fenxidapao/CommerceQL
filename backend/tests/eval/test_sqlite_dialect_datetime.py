"""U-174 扩白名单：`DATE_TRUNC` / `EXTRACT` / `::timestamp` 的等价翻译。

取证：`eval/olist/probe_dialect_forms.json`（`mode=ro` 打开沙箱，源库零改动）——
`DATE_TRUNC` 的 `year`/`month`/`day` 三种单位样本已出、`quarter` 报 `no such function`；
`EXTRACT` 的 `year`/`month`/`day`/`quarter` 四种样本已出；`x::timestamp` 只能剥运算符
（`CAST(x AS TIMESTAMP)` 返回四位年值，属跑得通但算错）。
"""

from __future__ import annotations

import sqlite_exec as sx


def test_date_trunc_month_year_day_are_translated() -> None:
    """正控：三种已证单位翻成 `strftime` 首日格式。"""
    month = sx.to_sqlite_sql("SELECT DATE_TRUNC('month', o.ts) AS m FROM x AS o")
    year = sx.to_sqlite_sql("SELECT DATE_TRUNC('year', o.ts) AS y FROM x AS o")
    day = sx.to_sqlite_sql("SELECT DATE_TRUNC('day', o.ts) AS d FROM x AS o")
    assert "strftime('%Y-%m-01', o.ts)" in month
    assert "strftime('%Y-01-01', o.ts)" in year
    assert "strftime('%Y-%m-%d', o.ts)" in day
    assert "DATE_TRUNC" not in (month + year + day).upper()


def test_date_trunc_quarter_is_left_untouched() -> None:
    """负控：`quarter` 单位无等价原语 ⇒ 一字不改。"""
    sql = "SELECT DATE_TRUNC('quarter', o.ts) AS q FROM x AS o"
    assert sx.to_sqlite_sql(sql) == sql


def test_extract_year_and_quarter_are_translated() -> None:
    """正控：`EXTRACT` 的 year / quarter 翻成整数取值（quarter 用整数除法）。"""
    year = sx.to_sqlite_sql("SELECT EXTRACT(YEAR FROM o.ts) AS y FROM x AS o")
    quarter = sx.to_sqlite_sql("SELECT EXTRACT(QUARTER FROM o.ts) AS q FROM x AS o")
    assert "CAST(strftime('%Y', o.ts) AS INTEGER)" in year
    assert "((CAST(strftime('%m', o.ts) AS INTEGER) + 2) / 3)" in quarter
    assert "EXTRACT" not in (year + quarter).upper()


def test_extract_unknown_unit_is_left_untouched() -> None:
    """负控：单位未登记 ⇒ 一字不改（宁可照旧失败并暴露）。"""
    sql = "SELECT EXTRACT(WEEK FROM o.ts) AS w FROM x AS o"
    assert sx.to_sqlite_sql(sql) == sql


def test_timestamp_cast_operator_is_stripped() -> None:
    """正控：`x::timestamp` 只剥运算符，**不**变成 CAST（那个会静默算错）。"""
    out = sx.to_sqlite_sql("SELECT o.ts::timestamp AS t FROM x AS o")
    assert "::" not in out
    assert "CAST(" not in out.upper()
    assert "o.ts AS t" in out


def test_other_cast_operators_are_left_untouched() -> None:
    """负控：`::numeric` 改舍入、`::date` 截时分 ⇒ 一律不翻。"""
    for sql in (
        "SELECT o.amount::numeric AS a FROM x AS o",
        "SELECT o.ts::date AS d FROM x AS o",
    ):
        assert sx.to_sqlite_sql(sql) == sql
