"""反事实执行：28 条真错题里「时间参数形态」是否为主因。

零网络、零 LLM、零 DB 写：以 mode=ro 打开 Olist 沙箱，对同一条 SQL 换不同时间参数
形态跑结果，与 gold_sql 字面量结果对照。输出 ``time_shape_probe.json``。

复算：``python eval/olist/probe_u183_time_shape.py``
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "data/olist/olist_sandbox.db"
OUT = Path(__file__).with_name("time_shape_probe.json")

BASE = (
    "SELECT SUM(i.price) AS item_gmv FROM v_o_order_items AS i "
    "JOIN v_o_orders AS o ON o.order_id = i.order_id "
    "WHERE o.order_status NOT IN ('canceled', 'unavailable') "
    "AND o.order_purchase_timestamp >= {lo} AND o.order_purchase_timestamp {op} {hi}"
)

ARMS: dict[str, tuple[str, str, str]] = {
    "gold_literal_right_open": ("'2018-01-01'", "<", "'2018-07-01'"),
    "param_T_right_open": ("'2018-01-01T00:00:00'", "<", "'2018-07-01T00:00:00'"),
    "param_space_right_open": ("'2018-01-01 00:00:00'", "<", "'2018-07-01 00:00:00'"),
    "param_T_closed_end": ("'2018-01-01T00:00:00'", "<=", "'2018-06-30T23:59:59'"),
    "param_space_closed_end": ("'2018-01-01 00:00:00'", "<=", "'2018-06-30 23:59:59'"),
    "param_date_only_closed_end": ("'2018-01-01'", "<=", "'2018-06-30'"),
}


def main() -> None:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    sample = con.execute(
        "SELECT order_purchase_timestamp FROM v_o_orders "
        "WHERE order_purchase_timestamp IS NOT NULL LIMIT 3"
    ).fetchall()
    rows: list[dict[str, Any]] = []
    for name, (lo, op, hi) in ARMS.items():
        sql = BASE.format(lo=lo, op=op, hi=hi)
        try:
            got = con.execute(sql).fetchall()
            err = None
        except sqlite3.Error as exc:
            got, err = [], str(exc)
        rows.append({"arm": name, "lo": lo, "op": op, "hi": hi,
                     "result": got, "error": err})
    t_sample = con.execute(
        "SELECT COUNT(*) FROM v_o_orders WHERE order_purchase_timestamp LIKE '%T%'"
    ).fetchone()[0]
    total = con.execute(
        "SELECT COUNT(*) FROM v_o_orders WHERE order_purchase_timestamp IS NOT NULL"
    ).fetchone()[0]
    con.close()
    baseline = rows[0]["result"]
    for r in rows:
        r["same_as_gold"] = r["result"] == baseline
    payload = {
        "schema": "U183_TIME_SHAPE_PROBE/v1",
        "probe": "eval/olist/probe_u183_time_shape.py",
        "recompute": "python eval/olist/probe_u183_time_shape.py",
        "db": "data/olist/olist_sandbox.db (mode=ro, 源库零改动)",
        "timestamp_samples": [s[0] for s in sample],
        "n_timestamps_with_T": t_sample,
        "n_timestamps_total": total,
        "arms": rows,
        "verdict": "各臂结果与 gold 字面量对照；same_as_gold=False 即为该形态致错",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", OUT.name)
    for r in rows:
        print(r["arm"], r["result"], "same_as_gold", r["same_as_gold"], r["error"])
    print("TS_SAMPLE", [s[0] for s in sample], "T_COUNT", t_sample, "/", total)


if __name__ == "__main__":
    main()
