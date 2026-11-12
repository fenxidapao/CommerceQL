"""U-184：判分面重算读数 —— 剥 `CAST(<简单列> AS TIMESTAMP)` 前后的 EX。

零网络 / 零 LLM / 零 DB 写 / 只读已落盘结果件。判分函数复用 `equivalence.compare_tables`，
翻译与参数归一复用 `sqlite_exec.to_sqlite_sql` / `sqlite_dialect.normalize_time_params`。

口径边界（务必同框看）：
  · `base`     = 结果件里 live 判分的 `verdict.equivalent`（U-184 落码前）
  · `as_is`    = 用**现行** `to_sqlite_sql` 对已落盘 SQL 重判（U-184 落码后）
  · `stripped` = 额外再剥一次恒等 CAST 后重判 ⇒ 与 `as_is` 应恒等（幂等旁证）
  · 落码前 r4/r5 的重判与 `base` **逐条一致**（95/95、94/94）。本件落码后
    `rescore_vs_live_verdict_disagree` 恰等于 `newly_equivalent` 那 5 条 ⇒ 其余逐条仍一致，
    可反证落码前口径等价；但它**不是新一轮 live**，也没有新录匣带。
  · 匣带按 `eval/cassette.py` 的纪律不跨日历日复用，跨日 replay 必然 miss。

复算：``python eval/olist/probe_u184_cast_gain.py``
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DB = REPO / "data/olist/olist_sandbox.db"
OUT = ROOT / "cast_gain_probe_u184.json"
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "backend"))
logging.disable(logging.WARNING)

import equivalence as eq
from sqlite_dialect import normalize_time_params
from sqlite_exec import to_sqlite_sql

#: 只剥「简单列引用」形态；其它类型 CAST 与复杂左值一律不动（与生产码同边界）。
_TS_CAST = re.compile(
    r"CAST\s*\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s+AS\s+TIMESTAMP\s*\)",
    re.IGNORECASE,
)


def strip_ts_cast(sql: str) -> str:
    return _TS_CAST.sub(r"\1", sql)


def run(con: sqlite3.Connection, sql: str, params: dict[str, Any]) -> Any:
    cur = con.cursor()
    try:
        cur.execute(to_sqlite_sql(sql), params)
        return eq.Table.from_cursor(cur)
    finally:
        cur.close()


def judge(con: sqlite3.Connection, gold_sql: str, sql: str,
          params: dict[str, Any]) -> tuple[bool, str]:
    try:
        g = run(con, gold_sql, {})
        p = run(con, sql, params)
        v = eq.compare_tables(g, p, gold_sql=gold_sql, pred_sql=sql)
        return bool(v.equivalent), (str(list(v.diffs)[:1])[:120] if not v.equivalent else "")
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"


def main() -> None:
    ds = json.loads((ROOT / "dataset_v3_frozen.json").read_text(encoding="utf-8"))
    gold = {c["case_id"]: c["gold_sql"] for c in ds["cases"]}
    denom = int(ds["n_execute_cases"])
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    batches: list[dict[str, Any]] = []
    for f in ("r1", "r2", "r3", "r4", "r5"):
        d = json.loads((ROOT / f"results_v3_{f}.json").read_text(encoding="utf-8"))
        exe = [r for r in d["records"] if r.get("expected_behavior") == "execute"]
        base = sum(1 for r in exe if (r.get("verdict") or {}).get("equivalent"))
        as_is, stripped = base, base
        recovered: list[str] = []
        regressions: list[str] = []
        agree = 0
        disagree: list[str] = []
        n_with_cast = 0
        for r in exe:
            sql = r.get("sql_text") or ""
            cid = r["case_id"]
            b = bool((r.get("verdict") or {}).get("equivalent"))
            if not sql or not gold.get(cid):
                continue
            params = normalize_time_params(dict(r.get("sql_params") or {}), sql)
            a, _ = judge(con, gold[cid], sql, params)
            if a == b:
                agree += 1
            else:
                disagree.append(cid)
            as_is += int(a and not b)
            if _TS_CAST.search(sql):
                n_with_cast += 1
            s, _ = judge(con, gold[cid], strip_ts_cast(sql), params)
            stripped += int(s and not b)
            if s and not a:
                recovered.append(cid)
            if a and not s:
                regressions.append(cid)
        batches.append({
            "batch": f, "source": f"eval/olist/results_v3_{f}.json (只读)",
            "n_execute": len(exe), "denominator": denom,
            "base_live_verdict": base, "rescored_after_u184": as_is,
            "rescored_strip_again": stripped,
            "ex": {"base": round(base / denom, 4),
                   "after_u184": round(as_is / denom, 4)},
            "n_records_with_ts_cast": n_with_cast,
            "newly_equivalent": recovered, "regressions": regressions,
            "rescore_vs_live_verdict_agree": agree,
            "rescore_vs_live_verdict_disagree": disagree,
        })
    con.close()
    live = [b for b in batches if b["batch"] in ("r4", "r5")]
    payload = {
        "schema": "U184_CAST_GAIN_PROBE/v1",
        "probe": "eval/olist/probe_u184_cast_gain.py",
        "recompute": "python eval/olist/probe_u184_cast_gain.py",
        "denominator_source": "eval/olist/dataset_v3_frozen.json::n_execute_cases（U-177 已裁定）",
        "scope": "判分面重算（已落盘 SQL，零 LLM）；不是新一轮 live，r6 仍 UNVERIFIED",
        "batches": batches,
        "p3_live_batches": {
            "base": [b["base_live_verdict"] for b in live],
            "after_u184": [b["rescored_after_u184"] for b in live],
            "ex_base": [b["ex"]["base"] for b in live],
            "ex_after_u184": [b["ex"]["after_u184"] for b in live],
            "gap_to_81": [81 - b["rescored_after_u184"] for b in live],
        },
        "verdict": (
            "U-184 落码使 r4/r5 判分面重算读数由 " + str([b["base_live_verdict"] for b in live])
            + " 升至 " + str([b["rescored_after_u184"] for b in live])
            + "；85%（81 题）仍未达成，差距照实保留；"
            + "本件不是 live 实测，正式 EX 需新录匣带 + live 复测。"
        ),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for b in batches:
        print(b["batch"], "base", b["base_live_verdict"], "after", b["rescored_after_u184"],
              "again", b["rescored_strip_again"], "EX", b["ex"],
              "+", b["newly_equivalent"], "-", b["regressions"])
    print("LIVE", payload["p3_live_batches"])
    print("WROTE", OUT.name)


if __name__ == "__main__":
    main()
