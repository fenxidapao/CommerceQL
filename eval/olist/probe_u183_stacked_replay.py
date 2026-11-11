"""分层叠加回放：只叠加「不改 LLM 请求体」的确定性增益，产出三批 EX_stacked。

零网络、零 LLM、零 DB 写。对三批已落盘的 `sql_text` / `sql_params` 逐条重判：
  · 原本 equivalent ⇒ 直接 PASS（保留原读数）；
  · GATE_AST_REJECTED（R14/R06）⇒ 评测侧越过闸门直接执行，看 SQL 是否本可等价；
  · SQL_SYNTAX_ERROR ⇒ 经现成 `to_sqlite_sql` 翻译后重试（quarter 未收录则如实单列）；
  · complete 但不等价 ⇒ 归一 `sql_params` 时间形态后重放。

⚠️ 这不是 `runner.py --mode replay` 的全链路重放，而是「记录级重判」：
它不验证闸门本身是否放行，只量化各杠杆的**上界**。落地仍需 P2 改判据/翻译器。

复算：``python eval/olist/probe_u183_stacked_replay.py``
"""

from __future__ import annotations

import collections
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
OUTS = [ROOT / f"results_v3_replay_stacked_r{i}.json" for i in (1, 2, 3)]
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(REPO / "backend"))


def _load_translator() -> tuple[Any, str]:
    try:
        import sqlite_exec as se
    except Exception:  # noqa: BLE001
        import sqlite_dialect as sd

        def fallback(sql: str) -> str:
            return re.sub(r"%\(([^)]+)\)s", r":\1", sd.translate_pg_functions(sql))

        return fallback, "eval/sqlite_dialect.py::translate_pg_functions (+ 参数改写法)"
    return se.to_sqlite_sql, "eval/sqlite_exec.py::to_sqlite_sql"


import equivalence as eq

TRANSLATE, ROUTE = _load_translator()
PURE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PLACEHOLDER = re.compile(r"%\(([^)]+)\)s")


def normalize(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in params.items():
        if not isinstance(val, str):
            out[key] = val
            continue
        text = val.replace("T", " ")
        if PURE_DATE.match(text) and key != "start_ts":
            text += " 23:59:59"
        out[key] = text
    return out


def run(con: sqlite3.Connection, sql: str, params: dict[str, Any]) -> Any:
    cur = con.cursor()
    try:
        cur.execute(TRANSLATE(sql), params)
        return eq.Table.from_cursor(cur)
    finally:
        cur.close()


def judge(con: sqlite3.Connection, gold_sql: str, sql: str,
          params: dict[str, Any]) -> dict[str, Any]:
    try:
        g = run(con, gold_sql, {})
        p = run(con, sql, params)
        v = eq.compare_tables(g, p, gold_sql=gold_sql, pred_sql=sql)
        return {"ok": True, "equivalent": v.equivalent, "diffs": list(v.diffs)[:3]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "equivalent": False,
                "error": f"{type(exc).__name__}: {str(exc)[:150]}"}


def main() -> None:
    ds = json.loads((ROOT / "dataset_v3_frozen.json").read_text(encoding="utf-8"))
    gold_sql = {c["case_id"]: c["gold_sql"] for c in ds["cases"]}
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    summary: list[dict[str, Any]] = []
    for i, out in zip((1, 2, 3), OUTS):
        path = ROOT / f"results_v3_r{i}.json"
        recs = json.loads(path.read_text(encoding="utf-8"))["records"]
        execute = [r for r in recs if r.get("expected_behavior") == "execute"]
        detail: list[dict[str, Any]] = []
        lever_counter: collections.Counter[str] = collections.Counter()
        for r in execute:
            cid, sql = r["case_id"], r.get("sql_text") or ""
            params = dict(r.get("sql_params") or {})
            base = bool((r.get("verdict") or {}).get("equivalent"))
            item: dict[str, Any] = {"case_id": cid, "base_equivalent": base,
                                    "terminal": r.get("terminal_event"),
                                    "terminal_code": r.get("terminal_code"),
                                    "gate1_rule": r.get("gate1_reject_rule"),
                                    "stacked_equivalent": base, "lever": "no_lever_applied"}
            if not base and sql and gold_sql.get(cid):
                needed = set(PLACEHOLDER.findall(sql))
                missing = needed - set(params)
                if missing:
                    item["lever"] = "skipped_missing_params"
                    item["missing_params"] = sorted(missing)
                else:
                    t, c = r.get("terminal_event"), r.get("terminal_code")
                    if t == "error" and c == "GATE_AST_REJECTED":
                        lever = "gate_bypass_r14" if r.get("gate1_reject_rule") == "R14" else "gate_bypass_r06"
                        res = judge(con, gold_sql[cid], sql, params)
                    elif t == "error" and c == "SQL_SYNTAX_ERROR":
                        lever = "dialect_retry"
                        res = judge(con, gold_sql[cid], sql, params)
                    elif t == "complete":
                        lever = "param_normalization"
                        res = judge(con, gold_sql[cid], sql, normalize(params))
                    else:
                        lever, res = "not_applicable", {"ok": False, "equivalent": False}
                    item["lever"] = lever
                    item["replay"] = res
                    item["stacked_equivalent"] = bool(res.get("equivalent"))
            detail.append(item)
            lever_counter[item["lever"]] += 1
        n_pass = sum(1 for d in detail if d["stacked_equivalent"])
        recovered = [d["case_id"] for d in detail
                     if d["stacked_equivalent"] and not d["base_equivalent"]]
        payload = {
            "schema": "U183_STACKED_REPLAY/v1",
            "probe": "eval/olist/probe_u183_stacked_replay.py",
            "recompute": "python eval/olist/probe_u183_stacked_replay.py",
            "source": f"eval/olist/results_v3_r{i}.json (只读)",
            "translate_route": ROUTE,
            "scope": "记录级重判；只叠加不改 LLM 请求体的确定性增益，是各杠杆上界而非闸门放行后的真实读数",
            "n_execute": len(execute),
            "base_pass": sum(1 for d in detail if d["base_equivalent"]),
            "stacked_pass": n_pass,
            "stacked_ex": round(n_pass / len(execute), 4),
            "n_recovered": len(recovered),
            "recovered_case_ids": recovered,
            "lever_distribution": dict(lever_counter),
            "details": detail,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary.append({"batch": f"r{i}", "base": payload["base_pass"],
                        "stacked": n_pass, "ex": payload["stacked_ex"],
                        "levers": dict(lever_counter)})
        print(out.name, "base", payload["base_pass"], "stacked", n_pass,
              "EX", payload["stacked_ex"], "levers", dict(lever_counter))
    con.close()
    (ROOT / "stacked_replay_summary.json").write_text(
        json.dumps({"schema": "U183_STACKED_REPLAY_SUMMARY/v1",
                    "translate_route": ROUTE, "batches": summary},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("ROUTE", ROUTE)


if __name__ == "__main__":
    main()
