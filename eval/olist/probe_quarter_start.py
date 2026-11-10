"""DATE_TRUNC('quarter', x) 的可证性探针（离线、只读沙箱、不改翻译、不改白名单）。

为什么单独测这一条：`eval/olist/probe_repair_equal_gold_pool_r2.json` 现读
`pool_n = 4`、`pool_judged_n = 2`、`dialect_blocked_ids = [n10, n39]` ——
被挡住的正是 `DATE_TRUNC('quarter', ...)`（`eval/sqlite_dialect.py` 的
`DATE_TRUNC_UNITS` 只收 year/month/day）。

本件只回答一件事：能不能用一条 SQLite 表达式算出**与 PG 季度首日一致**的日期，
并给出逐条样本对照。**不**改 `translate_pg_functions`、**不**动白名单、
**不**改判据 —— 进白名单属落码，须先取号。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
COL = "o.order_purchase_timestamp"
LIMIT = 12


def quarter_start_sql(col: str) -> str:
    """季度首日的候选表达式：`strftime('%Y') || printf('-%02d-01', 季度首月)`。"""
    first_month = "((CAST(strftime('%m', " + col + ") AS INTEGER) - 1) / 3) * 3 + 1"
    return "strftime('%Y', " + col + ") || printf('-%02d-01', " + first_month + ")"


def expected_quarter_start(value: object) -> str | None:
    text = str(value or "").strip().replace("T", " ")
    if len(text) < 7:
        return None
    try:
        year = int(text[0:4])
        month = int(text[5:7])
    except ValueError:
        return None
    first = ((month - 1) // 3) * 3 + 1
    return "%04d-%02d-01" % (year, first)


def main() -> int:
    if not DB.is_file():
        print("ABORT: 沙箱库不存在 " + str(DB))
        return 2
    con = sqlite3.connect("file:" + DB.resolve().as_posix() + "?mode=ro", uri=True)
    con.row_factory = None
    cur = con.cursor()
    try:
        cur.execute("SELECT sqlite_version()")
        version = cur.fetchone()[0]
        print("sqlite_version =", version)
        sql = (
            "SELECT " + COL + ", " + quarter_start_sql(COL) + " AS q_start FROM v_o_orders AS o "
            "WHERE " + COL + " IS NOT NULL LIMIT " + str(LIMIT)
        )
        print("probe_sql =", sql)
        cur.execute(sql)
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        print("ABORT: 探针执行失败 " + type(exc).__name__ + ": " + str(exc)[:200])
        return 3
    finally:
        cur.close()
        con.close()

    matched = 0
    for ts, got in rows:
        want = expected_quarter_start(ts)
        ok = want is not None and str(got) == want
        matched += 1 if ok else 0
        print("  ts = %-21s | got = %-12s | want = %-12s | match = %s" % (str(ts)[:19], got, want, ok))
    print("matched = %d / %d" % (matched, len(rows)))
    return 0 if rows and matched == len(rows) else 4


if __name__ == "__main__":
    raise SystemExit(main())
