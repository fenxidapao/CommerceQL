"""U-183 / P2：SQLite 时间绑定参数方言桥的穿点控制。

正控：T 分隔 → 空格分隔；`<=` 的纯日期上界 → 闭合当日 23:59:59。
负控：右开 `<` 的纯日期上界不动；下界不动；非日期字符串不动；数值不动；
      无 `<=` 的纯日期不动。

取证：`eval/olist/time_shape_probe.json`（gold 5,614,133.04 / T 分隔 5,631,554.30 /
纯日期闭区间 5,598,753.16 / 空格分隔与 gold 一致）。
"""

from __future__ import annotations

import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL_DIR))

import sqlite_dialect as sd  # noqa: E402
import sqlite_exec as sx  # noqa: E402

PG_SQL = (
    "SELECT 1 FROM v_o_orders AS o "
    "WHERE o.order_purchase_timestamp >= %(start_ts)s "
    "AND o.order_purchase_timestamp <= %(end_ts)s "
    "AND o.order_status NOT IN (%(status_canceled)s)"
)


def test_t_separator_is_rewritten() -> None:
    params = {"start_ts": "2018-01-01T00:00:00",
              "end_ts": "2018-12-31T23:59:59",
              "status_canceled": "canceled"}
    got = sd.normalize_time_params(params, PG_SQL)
    assert got["start_ts"] == "2018-01-01 00:00:00"
    assert got["end_ts"] == "2018-12-31 23:59:59"
    assert got["status_canceled"] == "canceled"


def test_pure_date_closed_upper_gets_end_of_day() -> None:
    params = {"start_ts": "2017-01-01", "end_ts": "2017-12-31"}
    got = sd.normalize_time_params(params, PG_SQL)
    assert got["end_ts"] == "2017-12-31 23:59:59"
    assert got["start_ts"] == "2017-01-01"


def test_right_open_upper_and_non_dates_are_untouched() -> None:
    right_open = "WHERE ts >= :start_ts AND ts < :end_ts"
    params = {"start_ts": "2017-01-01", "end_ts": "2018-01-01",
              "status_canceled": "canceled", "n": 5}
    got = sd.normalize_time_params(params, right_open)
    assert got == params


def test_sqlite_exec_placeholder_form_also_detected() -> None:
    got = sd.normalize_time_params({"end_ts": "2018-07-01"}, "WHERE ts <= :end_ts")
    assert got["end_ts"] == "2018-07-01 23:59:59"


def test_bridge_is_wired_into_both_execution_paths() -> None:
    """归一必须在 `run_in_sandbox` 与 `SqliteEvalExecutor.fetch` 两处共用同一函数。"""
    assert callable(sd.normalize_time_params)
    assert hasattr(sx, "to_sqlite_sql")
    import inspect

    import runner

    src = inspect.getsource(runner.run_in_sandbox)
    assert "normalize_time_params" in src
    fetch_src = inspect.getsource(sx.SqliteEvalExecutor.fetch)
    assert "normalize_time_params" in fetch_src
