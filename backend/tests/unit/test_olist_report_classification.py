"""报告层的方言缺口分类（W2 live 收尾）。

`ast_gate` 按 postgres 解析、沙箱是 SQLite：`to_char` / `date_trunc` / `::timestamp`
这类 SQL 在闸门 R14 就被拒，**走不到执行层** ⇒ `attribution` 给不出
`sandbox_dialect_gap`。报告不能因此把它算成模型错，需在同一处单列。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from eval.olist import report_olist as P  # noqa: E402


def test_attribution_category_is_honored() -> None:
    record = {"attribution": {"category": "sandbox_dialect_gap"}, "gate1_reject_rule": None}
    assert P.is_sandbox_dialect_gap(record) is True


def test_r14_with_postgres_function_is_dialect_gap() -> None:
    record = {
        "gate1_reject_rule": "R14",
        "sql_text": "SELECT to_char(date_trunc('month', o.ts::timestamp), 'YYYY-MM') FROM t",
        "attribution": {"category": "unattributed"},
    }
    assert P.is_sandbox_dialect_gap(record) is True


def test_r14_with_plain_sql_is_not_dialect_gap() -> None:
    record = {
        "gate1_reject_rule": "R14",
        "sql_text": "SELECT COUNT(*) FROM v_o_orders AS order",
        "attribution": {"category": "unattributed"},
    }
    assert P.is_sandbox_dialect_gap(record) is False


def test_other_reject_rules_are_not_dialect_gap() -> None:
    record = {
        "gate1_reject_rule": "R04",
        "sql_text": "SELECT to_char(ts) FROM t",
        "attribution": {"category": "sql_generation"},
    }
    assert P.is_sandbox_dialect_gap(record) is False


def test_struct_null_skipped_is_not_unscored() -> None:
    cases = [
        {"case_id": "c", "difficulty_struct": None, "difficulty_semantic": "high",
         "expected_behavior": "clarify"},
        {"case_id": "x", "difficulty_struct": "easy", "difficulty_semantic": "low",
         "expected_behavior": "execute"},
    ]
    records = [
        {"case_id": "c", "expected_behavior": "clarify", "scored": True,
         "terminal_event": "clarify", "infra_error": None},
        {"case_id": "x", "expected_behavior": "execute", "scored": False,
         "unscored_reason": "infra: GraphRecursionError", "infra_error": "GraphRecursionError"},
    ]
    stats = P.batch_stats(cases, records)
    assert stats["scored_total"] == 0
    assert stats["struct_null_skipped"] == 1
    assert stats["n_unscored"] == 1
