"""W6 冒烟：一条真用例走通「planner → binding → gate → SQLite 执行 → 终态」全链路。

用途：任务 #2 的收口验证 —— **只看链路通不通**，不出任何准确率结论
（真 LLM ⇒ 会花 token；本脚本一次 1 条，属于 D1 批准的"先冒烟"范围）。

两侧结果分别取到，是为了 §17.6 一致性测试① 的前半段能立刻看到实物：
- **gold 侧**：复用 W1A 的 `build_frozen_set.result_hash`（内含 `tenant_wrap` = 手写租户谓词），
  并与冻结集里已存的 `gold_result_hash` 比对 ⇒ 验"沙箱可复算"；
- **被测侧**：`Harness` 走**在线全链路**，租户边界 = `SqliteEvalExecutor` 的 TEMP VIEW
  （I-4/I-5 的定案：谓词在被测 SQL 之外，见 `eval/sqlite_exec.py` 文档头 §二）。

跑法（CommerceQL 根目录，密钥从环境读，本脚本不打印、不落盘）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/smoke_one_case.py [case_id]
产物：`backend/reports/w6/smoke_one_case.json` + `eval/cassettes/w6_smoke.jsonl`（录制匣带）
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402  # W1A 的唯一哈希实现（只读复用）
from harness import Harness  # noqa: E402

DEFAULT_CASE = "E-VER-02"
CASSETTE = os.path.join(ROOT, "eval", "cassettes", "w6_smoke.jsonl")


def gold_side(case: dict) -> dict:
    """冻结集 gold 侧：沙箱真实执行 + 复算 hash（W1A 口径，零复刻）。"""
    uri = Path(_bootstrap.SANDBOX_DB).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.cursor()
        h, nrows, ncols = bfs.result_hash(cur, str(case["gold_sql"]), case.get("eval_tenant"))
    finally:
        con.close()
    return {
        "tenant_wrapped_sql": bfs.tenant_wrap(str(case["gold_sql"]), case.get("eval_tenant")),
        "recomputed_hash": h,
        "frozen_hash": case.get("gold_result_hash"),
        "hash_matches_frozen": h == case.get("gold_result_hash"),
        "rows": nrows,
        "cols": ncols,
        "frozen_rows": case.get("gold_result_rows"),
        "frozen_cols": case.get("gold_result_cols"),
    }


def main(argv: list[str]) -> int:
    case_id = argv[1] if len(argv) > 1 else DEFAULT_CASE
    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    case = next((c for c in dataset["cases"] if c["case_id"] == case_id), None)
    if case is None:
        print(f"case_id 不在冻结集：{case_id}", file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(CASSETTE), exist_ok=True)
    harness = Harness(live=True, cassette_path=CASSETTE)
    try:
        run = harness.run_case(
            case_id=case_id,
            question=str(case["question"]),
            tenant=str(case["eval_tenant"]),
        )
    finally:
        written = harness.save_cassette()
        harness.close()

    out = {
        "case_id": case_id,
        "question": case["question"],
        "eval_tenant": case.get("eval_tenant"),
        "expected_behavior": case.get("expected_behavior"),
        "difficulty": {
            "struct": case.get("difficulty_struct"),
            "semantic": case.get("difficulty_semantic"),
        },
        "gold": gold_side(case),
        "run": {
            "nodes": list(run.nodes),
            "terminal_event": run.terminal_event,
            "outcome": run.outcome,
            "infra_error": run.infra_error,
            "refusal_reason": run.refusal_reason,
            "binding_status": run.binding_status,
            "sql_dialect": run.sql_dialect,
            "sql_text": run.sql_text,
            "sql_params": dict(run.sql_params or {}),
            "row_count": run.row_count,
            "result_columns": run.result_columns,
            "result_rows": run.result_rows,
            "truncated": run.truncated,
            "fingerprint": run.fingerprint,
            "exec_error_class": run.exec_error_class,
            "gate_decisions": run.gate_decisions,
            "gate_rules_hit": run.gate_rules_hit,
            "limit_injected": run.limit_injected,
            "applied_predicates": run.applied_predicates,
            "degradations": run.degradations,
            "latency_ms": run.latency_ms,
            "tokens": run.tokens,
            "cost_cny": run.cost_cny,
        },
        "cassette": {"path": CASSETTE, "entries_written": written},
    }
    path = os.path.join(HERE, "smoke_one_case.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(out["run"], ensure_ascii=False, indent=2, default=str)[:1800])
    print("--- gold ---")
    print(json.dumps(out["gold"], ensure_ascii=False, indent=2)[:700])
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
