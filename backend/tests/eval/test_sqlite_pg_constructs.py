"""U-174 穿点控制：未注册 PG 专有构造必须被显式点名（纯函数，不判分）。"""

from __future__ import annotations

from sqlite_pg_constructs import unregistered_constructs


def test_extract_cast_and_cast_operator_are_named() -> None:
    sql = (
        "SELECT EXTRACT(QUARTER FROM CAST(o.ts AS TIMESTAMP)) AS q, "
        "o.ts::timestamp AS t FROM v_o_orders AS o"
    )
    assert {"EXTRACT", "CAST", "::"} <= set(unregistered_constructs(sql))


def test_date_trunc_and_now_are_named() -> None:
    sql = "SELECT DATE_TRUNC('month', NOW()) AS m FROM v_o_orders"
    assert {"DATE_TRUNC", "NOW"} <= set(unregistered_constructs(sql))


def test_registered_to_char_format_is_clean() -> None:
    sql = "SELECT TO_CHAR(o.order_purchase_timestamp, 'YYYY-MM') AS m FROM v_o_orders AS o"
    assert unregistered_constructs(sql) == ()


def test_unregistered_to_char_format_is_flagged() -> None:
    sql = "SELECT TO_CHAR(o.ts, 'YYYY-MM-DD HH24:MI') AS m FROM v_o_orders AS o"
    assert "TO_CHAR" in unregistered_constructs(sql)


def test_plain_sql_is_clean() -> None:
    sql = "SELECT COUNT(DISTINCT o.order_id) AS order_cnt FROM v_o_orders AS o"
    assert unregistered_constructs(sql) == ()
