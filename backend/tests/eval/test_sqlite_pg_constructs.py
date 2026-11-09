"""U-174 穿点控制：**仍未注册**的 PG 专有构造必须被显式点名（纯函数，不判分）。

⚠️ 判定是**单位感知**的：扩白名单后 `DATE_TRUNC(year|month|day)`、`EXTRACT(...)`、`::timestamp`
已可翻，不得再点名；而 `DATE_TRUNC('quarter', …)`、`CAST(`、`NOW()`、`ILIKE`、`INTERVAL`、
白名单外 `TO_CHAR` 仍必须点名。
"""

from __future__ import annotations

from sqlite_pg_constructs import unregistered_constructs


def test_cast_still_named_but_registered_forms_are_not() -> None:
    """混合样本：`CAST(` 仍点名，已注册的 `EXTRACT` 与 `::timestamp` 不再点名。"""
    sql = (
        "SELECT EXTRACT(QUARTER FROM CAST(o.ts AS TIMESTAMP)) AS q, "
        "o.ts::timestamp AS t FROM v_o_orders AS o"
    )
    got = set(unregistered_constructs(sql))
    assert "CAST" in got
    assert "EXTRACT" not in got
    assert "::" not in got


def test_date_trunc_quarter_and_now_are_named() -> None:
    """负控：`quarter` 单位无等价原语（实测报 no such function）⇒ 仍点名；`NOW()` 亦不翻。"""
    sql = "SELECT DATE_TRUNC('quarter', NOW()) AS m FROM v_o_orders"
    assert {"DATE_TRUNC", "NOW"} <= set(unregistered_constructs(sql))


def test_date_trunc_month_is_clean_after_whitelist() -> None:
    """正控：`DATE_TRUNC('month', …)` 已注册可翻 ⇒ 返回空 tuple（不误报）。"""
    sql = "SELECT DATE_TRUNC('month', o.order_purchase_timestamp) AS m FROM v_o_orders AS o"
    assert unregistered_constructs(sql) == ()


def test_registered_to_char_format_is_clean() -> None:
    """正控：白名单内 `TO_CHAR` 格式不点名。"""
    sql = "SELECT TO_CHAR(o.order_purchase_timestamp, 'YYYY-MM') AS m FROM v_o_orders AS o"
    assert unregistered_constructs(sql) == ()


def test_unregistered_to_char_format_is_flagged() -> None:
    """负控：白名单外 `TO_CHAR` 格式必须点名。"""
    sql = "SELECT TO_CHAR(o.ts, 'YYYY-MM-DD HH24:MI') AS m FROM v_o_orders AS o"
    assert "TO_CHAR" in unregistered_constructs(sql)
