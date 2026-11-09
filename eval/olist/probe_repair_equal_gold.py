#!/usr/bin/env python
"""repair 两臂的 `equal_gold` 等价判据件（T-15；离线、零 LLM、零出站、只读沙箱）。

为什么单独一件：`eval/olist/probe_repair_ab.py:15-21` 明写「`equal_gold` **本件不算**：
那要 equivalence 全口径（列序/容差/舍入），留给单独一件」，且 `:11-13` 明写 B 臂
（`with_failed_sql`）违反 N-17、只在评测侧跑、不接生产。
⇒ 本件只补「那条已经生成好的 SQL 跑出来的结果，与金标是不是同一张表」。

输入：
  · 预测侧：`eval/olist/ab_n*.json` 的 `runs[].sql`（现成件，零成本，不再起 live）
  · 金标侧：`eval/olist/dataset_v3_frozen.json` 的 `gold_sql` / `gold_result_cols`
    （`n05` / `n10` / `n18` / `n39`；`dataset_v1_frozen.json` 与 `dataset_v2_frozen.json`
    是 `g01` 形态，不含 n 系列，别拿错件）

口径：
  · 等价判定**只用** `eval/equivalence.py::compare_tables`（`REL_TOL = 1e-6`，
    列序 / 别名 / 行序 / `LIMIT` 并列按 §C.4.1 九条）—— 不在本文件造第二份口径；
  · 方言翻译**只用** eval 侧现成实现（优先 `eval/sqlite_exec.py::to_sqlite_sql`，
    不可用时退回 `eval/sqlite_dialect.py::translate_pg_functions`），实际走哪条会打印；
  · **不做 `tenant_wrap`**：两侧 SQL 同侧执行，`hash_matches=None`。原因是
    `dataset_v3_frozen.json` 的 `gold_result_hash` 由 `eval/build_frozen_set.py:109`
    按 `tenant_wrap` 算过，本件不重放那条路径 ⇒ **不与哈希对撞**，避免被读成
    「哈希不一致 = 结果错」。这一点写在这里，也写进产物。

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
DEFAULT_OUT = OLIST_DIR / "probe_repair_equal_gold.json"
CASE_IDS = ("n05", "n10", "n18", "n39")


class Abort(Exception):
    """fail-closed：本件宁可不出件，也不出半份读数。"""


def _load_translator() -> tuple[Any, str]:
    """取 eval 侧现成的 PG→SQLite 翻译面（不造第二份）。"""
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
        # 与 `eval/sqlite_exec.py:148-154` 同一变换（`%(name)s` → `:name` + 方言函数改写）。
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


def _run(con: sqlite3.Connection, sql: str, translate: Any, eq: Any) -> Any:
    cur = con.cursor()
    try:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="repair 两臂 equal_gold 等价判据件（离线、零成本）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_D3)
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

    runs: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(OLIST_DIR.glob("ab_n*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for run in data.get("runs") or []:
            if isinstance(run, dict):
                runs.append((path.name, run))
    print(f"pred_runs: {len(runs)}")

    try:
        con = _open_ro(args.db)
    except Abort as exc:
        print(f"ABORT: {exc}")
        return 2

    records: list[dict[str, Any]] = []
    judged = 0
    equivalent_n = 0
    try:
        gold_tables: dict[str, Any] = {}
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

        for source, run in runs:
            cid = str(run.get("case_id"))
            arm = str(run.get("arm"))
            sql = str(run.get("sql") or "")
            item: dict[str, Any] = {
                "source": source,
                "case_id": cid,
                "arm": arm,
                "parse_ok": bool(run.get("parse_ok")),
                "exec_ok": bool(run.get("exec_ok")),
                "sql_len": len(sql),
                "judged": False,
                "reason": "",
            }
            if not sql:
                item["reason"] = "该臂没有产出 SQL（解析失败或空输出）"
                records.append(item)
                continue
            if cid not in gold_tables:
                item["reason"] = "金标侧不可执行"
                records.append(item)
                continue
            try:
                pred_table = _run(con, sql, translate, eq)
            except sqlite3.Error as exc:
                item["reason"] = f"预测侧执行失败：{type(exc).__name__}: {str(exc)[:120]}"
                records.append(item)
                continue

            gold_case = gold[cid]
            verdict = eq.compare_tables(
                gold_tables[cid],
                pred_table,
                gold_sql=str(gold_case.get("gold_sql") or ""),
                pred_sql=sql,
                hash_matches=None,  # 见模块 docstring：本件不做 tenant_wrap，不与哈希对撞
            )
            payload = _verdict_payload(verdict)
            item.update(
                {
                    "judged": True,
                    "gold_rows": len(gold_tables[cid].rows),
                    "pred_rows": len(pred_table.rows),
                    "verdict": payload,
                }
            )
            judged += 1
            ok = any(bool(payload.get(k)) for k in ("equivalent", "ok", "passed"))
            item["equivalent"] = ok
            if ok:
                equivalent_n += 1
            records.append(item)
            print(f"  {cid}/{arm}: judged=True equivalent={ok} gold_rows={item['gold_rows']} pred_rows={item['pred_rows']}")
    finally:
        con.close()

    if judged == 0:
        print("ABORT: 一条都没判成（不写件）")
        return 3

    result = {
        "schema": "T15_REPAIR_EQUAL_GOLD/v1",
        "note": (
            "本件只判 equal_gold（equivalence 全口径）；B 臂违反 N-17、仅评测侧实验；"
            "不做 tenant_wrap，故 hash_matches=None、不与 dataset_v3 的 gold_result_hash 对撞"
        ),
        "db": str(args.db.relative_to(REPO_ROOT)) if args.db.is_relative_to(REPO_ROOT) else str(args.db),
        "dataset": str(args.dataset.relative_to(REPO_ROOT)) if args.dataset.is_relative_to(REPO_ROOT) else str(args.dataset),
        "translate_route": route,
        "rel_tol": eq.REL_TOL,
        "judged_n": judged,
        "equivalent_n": equivalent_n,
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"judged={judged} equivalent={equivalent_n} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
