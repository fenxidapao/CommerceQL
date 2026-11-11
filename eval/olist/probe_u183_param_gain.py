"""反事实：只归一 sql_params 的时间形态，重放 28 条真错题，量化确定性修复上限。

零网络、零 LLM、零 DB 写、零 prompt 改动：参数在**执行时**绑定，不进 LLM 请求体，
故 `eval/cassette.py` 的 key 不变 ⇒ 这类修复可用旧匣带 replay 验证。

归一规则（只改值，不改 SQL 文本）：
  ① 值里的 `T` 分隔符换成空格；
  ② 纯日期 `YYYY-MM-DD` 且用于闭区间上界的，补 ` 23:59:59`。

输出 ``param_gain_probe.json``。复算：``python eval/olist/probe_u183_param_gain.py``
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO / "eval"
DB = REPO / "data/olist/olist_sandbox.db"
OUT = Path(__file__).with_name("param_gain_probe.json")
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(REPO / "backend"))


def _load_translator() -> tuple[Any, str]:
    """复用 eval 侧现成翻译面；与 probe_repair_equal_gold.py:52-73 同一 fallback。"""
    try:
        import sqlite_exec as se
    except Exception:  # noqa: BLE001
        import sqlite_dialect as sd

        def fallback(sql: str) -> str:
            return re.sub(r"%\(([^)]+)\)s", r":\1", sd.translate_pg_functions(sql))

        return fallback, "eval/sqlite_dialect.py::translate_pg_functions (+ 同一参数改写法)"
    return se.to_sqlite_sql, "eval/sqlite_exec.py::to_sqlite_sql"


import equivalence as eq

TRANSLATE, TRANSLATE_ROUTE = _load_translator()

PURE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in params.items():
        if not isinstance(val, str):
            out[key] = val
            continue
        text = val.replace("T", " ")
        if PURE_DATE.match(text) and key not in ("start_ts",):
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


def main() -> None:
    ds = json.loads((REPO / "eval/olist/dataset_v3_frozen.json").read_text(encoding="utf-8"))
    gold_sql = {c["case_id"]: c["gold_sql"] for c in ds["cases"]}
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    records: list[dict[str, Any]] = []
    for i in (1, 2, 3):
        path = REPO / f"eval/olist/results_v3_r{i}.json"
        for r in json.loads(path.read_text(encoding="utf-8"))["records"]:
            if r.get("expected_behavior") != "execute":
                continue
            if (r.get("verdict") or {}).get("equivalent"):
                continue
            if r.get("terminal_event") != "complete":
                continue
            cid = r["case_id"]
            params = dict(r.get("sql_params") or {})
            norm = normalize(params)
            item: dict[str, Any] = {
                "batch": f"r{i}", "case_id": cid,
                "params_original": params, "params_normalized": norm,
                "changed": norm != params,
            }
            try:
                g = run(con, gold_sql[cid], {})
                p0 = run(con, r["sql_text"], params)
                v0 = eq.compare_tables(g, p0, gold_sql=gold_sql[cid], pred_sql=r["sql_text"])
                item["as_is_equivalent"] = v0.equivalent
                p1 = run(con, r["sql_text"], norm)
                v1 = eq.compare_tables(g, p1, gold_sql=gold_sql[cid], pred_sql=r["sql_text"])
                item["normalized_equivalent"] = v1.equivalent
                item["normalized_diffs"] = list(v1.diffs)[:4]
            except Exception as exc:  # noqa: BLE001
                item["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
                item["as_is_equivalent"] = False
                item["normalized_equivalent"] = False
            records.append(item)
    con.close()
    n = len(records)
    recovered = [r for r in records if r["normalized_equivalent"] and not r["as_is_equivalent"]]
    still = [r for r in records if not r["normalized_equivalent"]]
    payload = {
        "schema": "U183_PARAM_GAIN_PROBE/v1",
        "probe": "eval/olist/probe_u183_param_gain.py",
        "recompute": "python eval/olist/probe_u183_param_gain.py",
        "rule": "sql_params 值：T→空格；纯日期上界补 23:59:59。SQL 文本一字未改 ⇒ 匣带 key 不变，可 replay 验证",
        "translate_route": TRANSLATE_ROUTE,
        "db": "data/olist/olist_sandbox.db (mode=ro, 零改动)",
        "n_records": n,
        "n_as_is_equivalent": sum(1 for r in records if r["as_is_equivalent"]),
        "n_recovered_by_param_normalization": len(recovered),
        "n_still_wrong": len(still),
        "recovered": [{"batch": r["batch"], "case_id": r["case_id"]} for r in recovered],
        "still_wrong": [{"batch": r["batch"], "case_id": r["case_id"],
                         "diffs": r.get("normalized_diffs"), "error": r.get("error")}
                        for r in still],
        "records": records,
        "verdict": "参数归一属于确定性修复，不进请求体、不改冻结集、不重录匣带；剩余条目另需改 prompt 或投票",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", OUT.name)
    print("N", n, "AS_IS_EQ", payload["n_as_is_equivalent"],
          "RECOVERED", len(recovered), "STILL_WRONG", len(still))
    print("RECOVERED_IDS", sorted({r["case_id"] for r in recovered}))
    print("STILL_IDS", sorted({r["case_id"] for r in still}))


if __name__ == "__main__":
    main()
