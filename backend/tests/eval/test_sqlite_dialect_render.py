"""U-167／U-174：方言渲染器必须把 PG 专有构造翻成 SQLite 等价写法（只翻白名单内已验形态）。

为什么单立一条：`backend/app/planner/payloads.py:109-121` 的 `DIALECT_NOTE` 写的是
「目标数据库：PostgreSQL 16」⇒ 模型产 `TO_CHAR(...)` 是照我方要求写的；而
`eval/sqlite_exec.py` 原来只改占位符、不翻函数 ⇒ `exec_error_class=unknown_function`
（r8 的 `mt06` turn1 与 turn2 均如此）。这条钉住三件事：翻得对、翻得保守、不影响占位符。

U-174 扩白名单后 `DATE_TRUNC('month', ...)` 自身也会被翻 ⇒ 嵌套断言的期望形态随之变化。
"""

from __future__ import annotations

import sqlite_exec as sx


def test_to_char_month_is_translated() -> None:
    """正控：`TO_CHAR(<expr>, YYYY-MM)` → `strftime`，且不再残留 `TO_CHAR`。"""
    out = sx.to_sqlite_sql("SELECT TO_CHAR(CAST(t AS TIMESTAMP), 'YYYY-MM') AS m FROM x")
    assert "strftime('%Y-%m', CAST(t AS TIMESTAMP))" in out
    assert "TO_CHAR" not in out.upper()


def test_nested_parentheses_are_handled() -> None:
    """正控：第一个参数里带括号（`DATE_TRUNC(...)`）时仍能正确切参数并各自翻译。"""
    out = sx.to_sqlite_sql("SELECT TO_CHAR(DATE_TRUNC('month', t), 'YYYY-MM') FROM x")
    # U-174 扩白名单后 `DATE_TRUNC('month', ...)` 自身也翻 ⇒ 期望是嵌套 `strftime`。
    assert "strftime('%Y-%m', strftime('%Y-%m-01', t))" in out


def test_unregistered_format_is_left_untouched() -> None:
    """负控：格式未登记 ⇒ 原样保留（宁可照旧失败，也不猜等价翻译）。"""
    sql = "SELECT TO_CHAR(t, 'Q') FROM x"
    assert sx.to_sqlite_sql(sql) == sql


def test_placeholders_are_still_rewritten() -> None:
    """旁证：翻译与占位符改写互不影响。"""
    out = sx.to_sqlite_sql("SELECT TO_CHAR(t, 'YYYY-MM') FROM x WHERE a = %(a)s")
    assert "strftime('%Y-%m', t)" in out
    assert ":a" in out


def test_native_sqlite_sql_is_untouched() -> None:
    """负控：本来就是 SQLite 写法的 SQL 一字不改。"""
    sql = "SELECT strftime('%Y-%m', t) FROM x"
    assert sx.to_sqlite_sql(sql) == sql
