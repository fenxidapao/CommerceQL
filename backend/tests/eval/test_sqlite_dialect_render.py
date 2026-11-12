"""U-167／U-174／U-184：方言渲染器必须把 PG 专有构造翻成 SQLite 等价写法（只翻白名单内已验形态）。

为什么单立一条：`backend/app/planner/payloads.py:109-121` 的 `DIALECT_NOTE` 写的是
「目标数据库：PostgreSQL 16」⇒ 模型产 `TO_CHAR(...)` 是照我方要求写的；而
`eval/sqlite_exec.py` 原来只改占位符、不翻函数 ⇒ `exec_error_class=unknown_function`
（r8 的 `mt06` turn1 与 turn2 均如此）。这条钉住三件事：翻得对、翻得保守、不影响占位符。

U-174 扩白名单后 `DATE_TRUNC('month', ...)` 自身也会被翻 ⇒ 嵌套断言的期望形态随之变化。
U-184：`CAST(<简单列> AS TIMESTAMP)` 在 SQLite 会把时间串截成四位年值，月度分组恒 1 行
（「跑得通但算错」）；恒等标注与 `::timestamp` 同形态，一并剥掉，但其它类型 CAST 不动。
"""

from __future__ import annotations

import sqlite3

import sqlite_dialect as sd
import sqlite_exec as sx


def test_to_char_month_is_translated() -> None:
    """正控：`TO_CHAR(<expr>, YYYY-MM)` → `strftime`，且 U-184 顺带剥掉恒等 TIMESTAMP CAST。"""
    out = sx.to_sqlite_sql("SELECT TO_CHAR(CAST(t AS TIMESTAMP), 'YYYY-MM') AS m FROM x")
    assert "strftime('%Y-%m', t)" in out
    assert "TO_CHAR" not in out.upper()
    assert "CAST(t AS TIMESTAMP)" not in out.upper()


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


def test_timestamp_cast_operator_is_stripped() -> None:
    """正控（U-167 原有）：`x::timestamp` 运算符形态剥成 `x`。"""
    assert sd.strip_timestamp_casts("SELECT o.ts::timestamp FROM t") == "SELECT o.ts FROM t"


def test_timestamp_cast_function_is_stripped() -> None:
    """正控（U-184）：`CAST(<简单列> AS TIMESTAMP)` 函数形态同样剥成该列。"""
    assert sd.strip_timestamp_casts(
        "SELECT CAST(o.order_purchase_timestamp AS TIMESTAMP) FROM t"
    ) == "SELECT o.order_purchase_timestamp FROM t"


def test_other_casts_are_preserved() -> None:
    """负控（U-184）：其它目标类型的 CAST 一律不动 —— 改舍入/截时分/比较语义。"""
    for sql in (
        "SELECT CAST(x AS INTEGER) FROM t",
        "SELECT CAST(x AS TEXT) FROM t",
        "SELECT CAST(x AS NUMERIC) FROM t",
        "SELECT CAST(x AS DATE) FROM t",
        "SELECT x::numeric FROM t",
    ):
        assert sd.strip_timestamp_casts(sql) == sql


def test_complex_timestamp_cast_is_preserved() -> None:
    """负控（U-184）：左值非简单列引用不做词法分析，原样保留。"""
    sql = "SELECT CAST(COALESCE(a, b) AS TIMESTAMP) FROM t"
    assert sd.strip_timestamp_casts(sql) == sql


def test_month_group_is_not_collapsed() -> None:
    """执行级正控（U-184）：12 个月的时间戳经翻译后必须分出 12 组，不是恒 1 组。

    负控同框：故意保留有害 CAST 时 `strftime` 拿到四位年值（按 Julian day 解释），
    所有行落到同一个固定标签 ⇒ 1 组。U-184 修的正是这个「跑得通但算错」。
    """
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE TABLE t (ts TEXT)")
        con.executemany(
            "INSERT INTO t VALUES (?)",
            [(f"2017-{m:02d}-15 10:00:00",) for m in range(1, 13)],
        )
        group = "TO_CHAR(CAST(ts AS TIMESTAMP), 'YYYY-MM')"
        fixed = sx.to_sqlite_sql(
            f"SELECT {group} AS m, COUNT(*) FROM t GROUP BY {group}"
        )
        assert len(con.execute(fixed).fetchall()) == 12
        broken = (
            "SELECT strftime('%Y-%m', CAST(ts AS TIMESTAMP)) AS m, COUNT(*) "
            "FROM t GROUP BY strftime('%Y-%m', CAST(ts AS TIMESTAMP))"
        )
        assert len(con.execute(broken).fetchall()) == 1
    finally:
        con.close()
