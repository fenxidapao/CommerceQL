"""3 路候选 + 执行验证 + 多数投票的零成本反事实（U-183 / P2 决策依据）。

三批 r1/r2/r3 是同一 prompt 的三次独立采样（temp=0.2），等价于「同一题跑 3 路候选」。
对每题在只读沙箱上重放三条预测 SQL（各自经参数归一），按**结果哈希多数**选出代表，
再与 gold 比较。这就是真实投票器（非 oracle）的收益读数。

对照两个上界：
  · oracle_union  = 任一臂等价即算对；
  · majority_vote = 按结果哈希多数选臂，选出的臂等价才算对。

零网络、零 LLM、零 DB 写。复算：``python eval/olist/probe_u183_voting_upper.py``
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
OUT = ROOT / "voting_upper_probe.json"
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(REPO / "backend"))

import equivalence as eq
from sqlite_dialect import normalize_time_params, translate_pg_functions
from voting import result_digest, vote_by_result


def to_sqlite(sql: str) -> str:
    return re.sub(r"%\(([^)]+)\)s", r":\1", translate_pg_functions(sql))


def run(con: sqlite3.Connection, sql: str, params: dict[str, Any]) -> tuple[str, Any]:
    cur = con.cursor()
    try:
        cur.execute(sql, params)
        table = eq.Table.from_cursor(cur)
        return result_digest(table.rows), table
    finally:
        cur.close()


def main() -> None:
    ds = json.loads((ROOT / "dataset_v3_frozen.json").read_text(encoding="utf-8"))
    gold = {c["case_id"]: c["gold_sql"] for c in ds["cases"]}
    batches = []
    for i in (1, 2, 3):
        d = json.loads((ROOT / f"results_v3_r{i}.json").read_text(encoding="utf-8"))
        batches.append({r["case_id"]: r for r in d["records"]
                        if r.get("expected_behavior") == "execute"})
    ids = sorted(set.intersection(*(set(b) for b in batches)))
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    detail: list[dict[str, Any]] = []
    for cid in ids:
        arms: list[dict[str, Any]] = []
        for i, b in enumerate(batches, start=1):
            r = b[cid]
            sql = r.get("sql_text") or ""
            if not sql:
                continue
            params = normalize_time_params(dict(r.get("sql_params") or {}), sql)
            try:
                g = run(con, gold[cid], {})
                digest, table = run(con, to_sqlite(sql), params)
                v = eq.compare_tables(g[1], table, gold_sql=gold[cid], pred_sql=sql)
                arms.append({"batch": f"r{i}", "digest": digest,
                             "equivalent": v.equivalent, "error": None})
            except Exception as exc:  # noqa: BLE001
                arms.append({"batch": f"r{i}", "digest": None,
                             "equivalent": False,
                             "error": f"{type(exc).__name__}: {str(exc)[:100]}"})
        # 多数投票复用 `eval/voting.py` 单一真相点（选臂不看 gold）
        vote = vote_by_result(arms)
        winner = vote["winner"]
        vote_equivalent = bool(
            winner is not None and arms[winner]["equivalent"]
        )
        detail.append({
            "case_id": cid,
            "n_arms": len(arms),
            "oracle_any_equivalent": any(a["equivalent"] for a in arms),
            "majority_vote_equivalent": vote_equivalent,
            "n_distinct_results": vote["n_distinct"],
            "vote_size": vote["vote_size"],
            "tied": vote["tied"],
            "arms": arms,
        })
    con.close()
    payload = {
        "schema": "U183_VOTING_UPPER_PROBE/v1",
        "probe": "eval/olist/probe_u183_voting_upper.py",
        "recompute": "python eval/olist/probe_u183_voting_upper.py",
        "scope": "三批独立采样当 3 路候选；经参数归一后在只读沙箱重放；多数投票按结果哈希",
        "n_cases": len(detail),
        "oracle_union": sum(1 for d in detail if d["oracle_any_equivalent"]),
        "majority_vote_pass": sum(1 for d in detail if d["majority_vote_equivalent"]),
        "verdict": "oracle 并集是上界；majority_vote 才是投票器真实可达读数",
        "details": detail,
    }
    payload["majority_vote_ex"] = round(payload["majority_vote_pass"] / len(detail), 4)
    payload["oracle_ex"] = round(payload["oracle_union"] / len(detail), 4)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", OUT.name)
    print("N", len(detail), "ORACLE", payload["oracle_union"], payload["oracle_ex"],
          "MAJORITY", payload["majority_vote_pass"], payload["majority_vote_ex"])


if __name__ == "__main__":
    main()
