#!/usr/bin/env python
"""repair 面的 `equal_gold` 全量归因件（T-15；离线、零 LLM、零出站、只读沙箱）。

与 `probe_repair_equal_gold.py` 的分工（不合并、不互相覆盖）：
  · 那一件判 `eval/olist/ab_n*.json` 的 7 个臂（探针自己生成的两臂 SQL）；
  · 本件多判**候选池**里那 4 条**原始失败 SQL**（`results_v3_r{1,2,3}.json` 里
    `nodes` 含 `repair` 且 `terminal_event != complete` 的记录，与
    `probe_repair_ab.py:96-128` 的挑选口径同一套条件），回答「这些失败到底是
    方言翻不过去、还是 repair 改不对」。
  · 产物写到**新件** `probe_repair_equal_gold_pool.json`：旧件已经提交，证据不改手。

口径（与旧件一致，不造第二份）：
  · 等价判定只走 `eval/equivalence.py::compare_tables`（`REL_TOL = 1e-6`，
    列序 / 别名 / 行序 / `LIMIT` 并列按 §C.4.1 九条）；
  · 方言翻译只走 eval 侧现成实现（优先 `eval/sqlite_exec.py::to_sqlite_sql`，
    不可用时退回 `eval/sqlite_dialect.py::translate_pg_functions`），实际走哪条会打印；
  · **不做 `tenant_wrap`**：两侧 SQL 同侧执行，`hash_matches=None`。原因是
    `dataset_v3_frozen.json` 的 `gold_result_hash` 由 `eval/build_frozen_set.py:109`
    按 `tenant_wrap` 算过，本件不重放那条路径 => 不与哈希对撞，避免被读成
    「哈希不一致 = 结果错」。

⚠️ 只读输入、不写现有证据件：`--out` 只写本探针自己的 JSON（新件，不覆盖旧件）。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "eval"
OLIST_DIR = Path(__file__).resolve().parent
DEFAULT_D3 = OLIST_DIR / "dataset_v3_frozen.json"
DEFAULT_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
DEFAULT_OUT = OLIST_DIR / "probe_repair_equal_gold_pool.json"
DEFAULT_RESULTS = [OLIST_DIR / f"results_v3_r{i}.json" for i in (1, 2, 3)]
CASE_IDS = ("n05", "n10", "n18", "n39")
DIALECT_TOKENS = ("EXTRACT", "CAST(", "::", "DATE_TRUNC", "ILIKE", "INTERVAL", "NOW()", "TO_CHAR")


class Abort(Exception):
    """fail-closed：本件宁可不出件，也不出半份读数。"""


def _load_translator() -> tuple[Any, str]:
    """取 eval 侧现成的 PG->SQLite 翻译面（不造第二份）。"""
    sys.path.insert(0, str(EVAL_DIR))
    try:
        import sqlite_exec as se  # noqa: PLC0415 - 延迟导入，缺依赖时给可读的 ABORT
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] eval/sqlite_exec.py 不可用：{type(exc).__name__}: {str(exc)[:160]}")
    else:
        fn = getattr(se, "to_sqlite_sql", None)
        if callable(fn):
            return fn, "eval/sqlite_exec.py::to_sqlite_sql"

    try:
        import sqlite_dialect as sd  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise Abort(f"方言翻译不可用：{type(exc).__name__}: {str(exc)[:180]}") from exc

    def _fallback(sql: str) -> str:
        return re.sub(r"%\(([^)]+)\)s", r":\1", sd.translate_pg_functions(sql))

    return _fallback, "eval/sqlite_dialect.py::translate_pg_functions（+ 同一参数改写法）"


def _load_equivalence() -> Any:
    sys.path.insert(0, str(EVAL_DIR))
    try:
        import equivalence as eq  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise Abort(f"eval/equivalence.py 不可用：{type(exc).__name__}: {str(exc)[:180]}") from exc
    for name in ("Table", "compare_tables", "REL_TOL"):
        if not hasattr(eq, name):
            raise Abort(f"eval/equivalence.py 缺 {name}（契约变了，先读再改本件）")
    return eq


def _open_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise Abort(f"沙箱库不存在：{db_path}")
    con = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = None  # `Table.from_cursor` 按 tuple 消费
    return con


def _run(
    con: sqlite3.Connection, sql: str, translate: Any, eq: Any, params: Any = None
) -> Any:
    """`params` 非空时按 `%(name)s` → `:name` 绑定后执行。

    与 `eval/runner.py:188-202` 的 `_ParamCursor` 同口径：只转发，值加工仍由 sqlite3 完成。
    """
    bound = dict(params or {})
    cur = con.cursor()
    try:
        if bound:
            cur.execute(translate(sql), bound)
        else:
            cur.execute(translate(sql))
        return eq.Table.from_cursor(cur)
    finally:
        cur.close()


def _verdict_payload(v: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if is_dataclass(v) and not isinstance(v, type):
        for f in fields(v):
            out[f.name] = getattr(v, f.name)
    else:  # pragma: no cover - 契约变了才会走到
        out["repr"] = repr(v)
    return out


def _tokens(sql: str) -> dict[str, int]:
    up = (sql or "").upper()
    return {t: up.count(t) for t in DIALECT_TOKENS if up.count(t)}


def load_pool(paths: list[Path]) -> list[dict[str, Any]]:
    """挑「真走过 repair 且仍失败」的记录（与 `probe_repair_ab.py:96-128` 同条件）。"""
    picked: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.is_file():
            print(f"  [warn] 缺输入 {path.name}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else (data.get("records") or [])
        for record in records:
            if not isinstance(record, dict):
                continue
            nodes = [str(n) for n in (record.get("nodes") or [])]
            if "repair" not in nodes:
                continue
            if str(record.get("terminal_event")) == "complete":
                continue
            case_id = str(record.get("case_id"))
            if case_id in picked:
                continue
            picked[case_id] = {
                "case_id": case_id,
                "source": path.name,
                "terminal_code": str(record.get("terminal_code")),
                "exec_error_class": str(record.get("exec_error_class")),
                "terminal_event": str(record.get("terminal_event")),
                "sql_text": str(record.get("sql_text") or ""),
                #: U-174／T-15：池内 SQL 带 `%(start_ts)s` 一类占位符，必须带参数执行，
                #: 否则会误报 `Incorrect number of bindings supplied`（旧版就是这么误分类的）。
                "sql_params": dict(record.get("sql_params") or {}),
                "gold_sql_record": str((record.get("gold") or {}).get("gold_sql") or ""),
            }
    return [picked[k] for k in sorted(picked)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="repair 面 equal_gold 全量归因（离线、零成本）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_D3)
    parser.add_argument("--results", type=Path, nargs="+", default=DEFAULT_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    try:
        eq = _load_equivalence()
        translate, route = _load_translator()
    except Abort as exc:
        print(f"ABORT: {exc}")
        return 2

    print(f"equivalence: REL_TOL={eq.REL_TOL}")
    print(f"translate route: {route}")

    if not args.dataset.is_file():
        print(f"ABORT: 金标件不存在 {args.dataset}")
        return 2
    d3 = json.loads(args.dataset.read_text(encoding="utf-8"))
    gold: dict[str, dict[str, Any]] = {}
    for case in d3.get("cases") or []:
        if isinstance(case, dict) and str(case.get("case_id")) in CASE_IDS:
            gold[str(case["case_id"])] = case
    print(f"gold_cases: {sorted(gold)}")
    if not gold:
        print("ABORT: 金标件里没有 n 系列用例（取错件？）")
        return 2

    pool = load_pool(list(args.results))
    print(f"pool_n: {len(pool)} -> {[p['case_id'] for p in pool]}")
    if not pool:
        print("ABORT: 候选池为空（多轮批从未走到「repair 且仍失败」时属正常，但本件无输入）")
        return 2

    try:
        con = _open_ro(args.db)
    except Abort as exc:
        print(f"ABORT: {exc}")
        return 2

    gold_tables: dict[str, Any] = {}
    pool_records: list[dict[str, Any]] = []
    pool_judged = 0
    pool_equivalent = 0
    dialect_blocked: list[str] = []
    try:
        for cid, case in sorted(gold.items()):
            sql = str(case.get("gold_sql") or "")
            if not sql:
                print(f"  [skip] {cid}: 金标没有 gold_sql")
                continue
            try:
                gold_tables[cid] = _run(con, sql, translate, eq)
                print(f"  gold {cid}: rows={len(gold_tables[cid].rows)} cols={len(gold_tables[cid].columns)}")
            except sqlite3.Error as exc:
                print(f"  [gold-fail] {cid}: {type(exc).__name__}: {str(exc)[:120]}")

        for item in pool:
            cid = item["case_id"]
            sql = item["sql_text"]
            toks = _tokens(sql)
            rec: dict[str, Any] = {
                "case_id": cid,
                "source": item["source"],
                "terminal_code": item["terminal_code"],
                "exec_error_class": item["exec_error_class"],
                "sql_len": len(sql),
                "sql_params_keys": sorted((item.get("sql_params") or {})),
                "dialect_tokens": toks,
                "judged": False,
                "reason": "",
            }
            if not sql:
                rec["reason"] = "该记录没有 sql_text"
                pool_records.append(rec)
                continue
            if cid not in gold_tables:
                rec["reason"] = "金标侧不可执行或缺该 case"
                pool_records.append(rec)
                continue
            translated = translate(sql)
            rec["translated_differs"] = translated != sql
            try:
                pred_table = _run(con, sql, translate, eq, item.get("sql_params") or {})
            except sqlite3.Error as exc:
                msg = f"{type(exc).__name__}: {str(exc)}"
                rec["reason"] = f"执行失败：{msg[:140]}"
                rec["sqlite_error"] = msg
                low = msg.lower()
                if toks and ("syntax error" in low or "no such function" in low):
                    dialect_blocked.append(cid)
                    rec["dialect_failure_kind"] = (
                        "syntax_error" if "syntax error" in low else "no_such_function"
                    )
                pool_records.append(rec)
                continue
            gold_case = gold[cid]
            verdict = eq.compare_tables(
                gold_tables[cid],
                pred_table,
                gold_sql=str(gold_case.get("gold_sql") or item["gold_sql_record"]),
                pred_sql=sql,
                hash_matches=None,
            )
            payload = _verdict_payload(verdict)
            rec.update(
                {
                    "judged": True,
                    "gold_rows": len(gold_tables[cid].rows),
                    "pred_rows": len(pred_table.rows),
                    "verdict": payload,
                }
            )
            ok = any(bool(payload.get(k)) for k in ("equivalent", "ok", "passed"))
            rec["equivalent"] = ok
            pool_judged += 1
            if ok:
                pool_equivalent += 1
            pool_records.append(rec)
            print(f"  pool {cid}: judged=True equivalent={ok} gold_rows={rec['gold_rows']} pred_rows={rec['pred_rows']}")
    finally:
        con.close()

    arms_paths = sorted(OLIST_DIR.glob("ab_n*.json"))
    arm_runs: list[tuple[str, dict[str, Any]]] = []
    for path in arms_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for run in data.get("runs") or []:
            if isinstance(run, dict):
                arm_runs.append((path.name, run))
    print(f"arm_runs: {len(arm_runs)}")

    if pool_judged == 0 and not arm_runs:
        print("ABORT: 一条都没判成（不写件）")
        return 3

    result = {
        "schema": "T15_REPAIR_EQUAL_GOLD_POOL/v1",
        "note": (
            "本件判两件事：候选池里 repair 失败记录的原始 SQL、以及 ab_n* 七臂的输出；"
            "B 臂违反 N-17、仅评测侧实验；不做 tenant_wrap，故 hash_matches=None、"
            "不与 dataset_v3 的 gold_result_hash 对撞"
        ),
        "db": str(args.db.relative_to(REPO_ROOT)) if args.db.is_relative_to(REPO_ROOT) else str(args.db),
        "dataset": (
            str(args.dataset.relative_to(REPO_ROOT))
            if args.dataset.is_relative_to(REPO_ROOT)
            else str(args.dataset)
        ),
        "results": [p.name for p in args.results],
        "translate_route": route,
        "rel_tol": eq.REL_TOL,
        "pool_n": len(pool),
        "pool_judged_n": pool_judged,
        "pool_equivalent_n": pool_equivalent,
        "dialect_blocked_ids": dialect_blocked,
        "pool": pool_records,
        "arm_runs_n": len(arm_runs),
        "arm_run_meta": [
            {
                "source": src,
                "case_id": str(run.get("case_id")),
                "arm": str(run.get("arm")),
                "parse_ok": bool(run.get("parse_ok")),
                "exec_ok": bool(run.get("exec_ok")),
                "sql_len": len(str(run.get("sql") or "")),
            }
            for src, run in arm_runs
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"pool judged={pool_judged} equivalent={pool_equivalent} "
        f"dialect_blocked={dialect_blocked} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
