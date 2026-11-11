"""剩余失败反事实：quarter 表达式放行 / 月度题翻译 到底有没有收益。

零网络、零 LLM、零 DB 写。对三批里「归一后仍失败」的题，分两臂重判：
  · quarter 臂：`DATE_TRUNC('quarter', x)` → 季度首日表达式、
    `EXTRACT(QUARTER FROM x)` → 季度号，其余走现成 `to_sqlite_sql`；
  · 月度臂：直接走现成 `to_sqlite_sql`（R14 已在生产码收窄，本臂绕过闸门执行）。

⚠️ 这是评测侧反事实，用于判断「值不值得落码」，不是最终读数。
复算：``python eval/olist/probe_u183_remaining_gain.py``
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
EVAL_DIR = REPO / "eval"
DB = REPO / "data/olist/olist_sandbox.db"
OUT = ROOT / "remaining_gain_probe.json"
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(REPO / "backend"))

import equivalence as eq
from sqlite_dialect import normalize_time_params, translate_pg_functions
from sqlite_pg_constructs import unregistered_constructs

_QUARTER_DT = re.compile(
    r"DATE_TRUNC\(\s*'quarter'\s*,\s*([^,()]+?)\s*\)", re.IGNORECASE
)
_QUARTER_EX = re.compile(
    r"EXTRACT\(\s*QUARTER\s+FROM\s+([^)]+?)\s*\)", re.IGNORECASE
)


def quarter_rewrite(sql: str) -> str:
    """仅在反事实臂里放行季度：首日/季度号两个等价表达式（probe_quarter_start.py 已证）。"""
    text = _QUARTER_DT.sub(
        lambda m: (
            "strftime('%Y', " + m.group(1) + ") || '-' || "
            "printf('%02d-01', ((CAST(strftime('%m', " + m.group(1)
            + ") AS INTEGER) - 1) / 3) * 3 + 1)"
        ),
        sql,
    )
    return _QUARTER_EX.sub(
        lambda m: "((CAST(strftime('%m', " + m.group(1) + ") AS INTEGER) - 1) / 3 + 1)",
        text,
    )


def to_sqlite(sql: str) -> str:
    return re.sub(r"%\(([^)]+)\)s", r":\1", translate_pg_functions(sql))


def run(con: sqlite3.Connection, sql: str, params: dict[str, Any]) -> Any:
    cur = con.cursor()
    try:
        cur.execute(sql, params)
        return eq.Table.from_cursor(cur)
    finally:
        cur.close()


def main() -> None:
    ds = json.loads((ROOT / "dataset_v3_frozen.json").read_text(encoding="utf-8"))
    gold = {c["case_id"]: c["gold_sql"] for c in ds["cases"]}
    after = json.loads((ROOT / "probe_dialect_gain_after_u183.json").read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    records: list[dict[str, Any]] = []
    for i, batch in enumerate(after["batches"], start=1):
        got = set(batch["recovered"])
        src = json.loads((ROOT / f"results_v3_r{i}.json").read_text(encoding="utf-8"))
        for r in src["records"]:
            if r.get("expected_behavior") != "execute":
                continue
            if (r.get("verdict") or {}).get("equivalent") or r["case_id"] in got:
                continue
            cid, sql = r["case_id"], r.get("sql_text") or ""
            if not sql:
                continue
            params = normalize_time_params(dict(r.get("sql_params") or {}), sql)
            constructs = unregistered_constructs(sql)
            is_quarter = any("QUARTER" in t.upper() for t in constructs) or "QUARTER" in sql.upper()
            item: dict[str, Any] = {"batch": f"r{i}", "case_id": cid,
                                    "constructs": list(constructs),
                                    "arm": "quarter_rewrite" if is_quarter else "plain_translate"}
            try:
                translated = quarter_rewrite(sql) if is_quarter else sql
                g = run(con, gold[cid], {})
                p = run(con, to_sqlite(translated), params)
                v = eq.compare_tables(g, p, gold_sql=gold[cid], pred_sql=translated)
                item["equivalent"] = v.equivalent
                item["diffs"] = list(v.diffs)[:3]
            except Exception as exc:  # noqa: BLE001
                item["equivalent"] = False
                item["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
            records.append(item)
    con.close()
    payload = {
        "schema": "U183_REMAINING_GAIN_PROBE/v1",
        "probe": "eval/olist/probe_u183_remaining_gain.py",
        "recompute": "python eval/olist/probe_u183_remaining_gain.py",
        "scope": "评测侧反事实，用于判断 quarter/月度翻译是否值得落码；不是最终 EX 读数",
        "n_records": len(records),
        "n_recovered": sum(1 for r in records if r.get("equivalent")),
        "by_arm": {
            a: {"n": sum(1 for r in records if r["arm"] == a),
                "recovered": sum(1 for r in records if r["arm"] == a and r.get("equivalent"))}
            for a in ("quarter_rewrite", "plain_translate")
        },
        "records": records,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", OUT.name, "N", len(records), "RECOVERED", payload["n_recovered"])
    print("BY_ARM", payload["by_arm"])
    print("RECOVERED_IDS", sorted({r["case_id"] for r in records if r.get("equivalent")}))


if __name__ == "__main__":
    main()
