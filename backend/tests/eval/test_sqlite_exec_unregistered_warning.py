"""U-174 告警出口穿点控制：未注册的 PG 专有构造必须在翻译前**显式告警**。

为什么补：`eval/sqlite_pg_constructs.py` 只是判定面（可被显式索取），若执行期一声不吭，
读数上「方言翻不动」仍与「模型写错」长得一样（`T-22` 与 `T-15` 都吃过这个亏）。

判据面不动：`to_sqlite_sql` 的输出**一字不变**、不阻断执行、不改 `sql_text`。
"""

from __future__ import annotations

import logging

from sqlite_exec import to_sqlite_sql


def test_extract_warns_and_output_is_unchanged(caplog) -> None:
    """正控：`EXTRACT` 必须告警，且翻译结果与输入逐字相同（不改写）。"""
    sql = "SELECT EXTRACT(QUARTER FROM o.ts) AS q FROM v_o_orders AS o"
    with caplog.at_level(logging.WARNING, logger="sqlite_exec"):
        out = to_sqlite_sql(sql)
    assert out == sql
    assert any("unregistered construct" in rec.getMessage() for rec in caplog.records)


def test_registered_to_char_translates_without_warning(caplog) -> None:
    """负控：白名单内的 `TO_CHAR` 照旧翻译，且**不**告警。"""
    sql = "SELECT TO_CHAR(o.ts, 'YYYY-MM') AS m FROM v_o_orders AS o"
    with caplog.at_level(logging.WARNING, logger="sqlite_exec"):
        out = to_sqlite_sql(sql)
    assert "strftime('%Y-%m'" in out
    assert not caplog.records


def test_plain_sql_is_silent(caplog) -> None:
    """负控：干净 SQL 既不告警也不改写（不制造噪音）。"""
    sql = "SELECT COUNT(DISTINCT o.order_id) AS n FROM v_o_orders AS o"
    with caplog.at_level(logging.WARNING, logger="sqlite_exec"):
        out = to_sqlite_sql(sql)
    assert out == sql
    assert not caplog.records
