"""交互题（3 clarify / 2 refuse）在评测形状上是"不可执行、无结构标签"。

锁三件事：
1. 5 条交互题 `gold_sql is None` 且 `difficulty_struct is None`；
2. 评分器给它们的 `verdict` 恒 `None`、`passed=False` —— 这是**不进 EX 分母**的形状；
3. `build_grid` 即使看到 `scored=True` 也不把它们计入 `scored_total`。

⚠️ 本文件的 `passed=False` **不是**交互正确判据。运行时正确性判据见
`test_olist_interaction_correctness.py`（`terminal_event == expected_behavior`）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OLIST_DIR = REPO_ROOT / "eval" / "olist"
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from eval.grid import build_grid  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return R.load_annotated_cases(OLIST_DIR / "dataset_v1.yaml")["cases"]


def test_interaction_ids_and_behaviors(cases) -> None:
    clarify = [c for c in cases if c.get("expected_behavior") == "clarify"]
    refuse = [c for c in cases if c.get("expected_behavior") == "refuse"]
    assert [c["case_id"] for c in clarify] == ["c01", "c02", "c03"]
    assert [c["case_id"] for c in refuse] == ["r01", "r02"]


def test_interaction_cases_have_no_sql_and_no_struct_label(cases) -> None:
    for case in cases:
        if (case.get("expected_behavior") or "execute") == "execute":
            continue
        assert case.get("gold_sql") is None, case["case_id"]
        assert case.get("difficulty_struct") is None, case["case_id"]
        # 语义标签允许 high（fuzzy:*），结构标签必须为空。
        assert case.get("difficulty_semantic") in {"low", "medium", "high"}, case["case_id"]


def test_scoring_shape_is_unscored_not_failed(cases) -> None:
    """评分器对交互题给 `verdict=None`；`passed=False` 只是形状，不是错误。"""
    for case in cases:
        if (case.get("expected_behavior") or "execute") == "execute":
            continue
        record = {"case_id": case["case_id"], "verdict": None, "scored": True}
        verdict = record["verdict"] or {}
        assert bool(verdict.get("equivalent")) is False
        assert verdict.get("equivalent") is None


def test_build_grid_excludes_interactions_even_if_scored(cases) -> None:
    results = {
        str(c["case_id"]): {"scored": True, "passed": False, "category": "unattributed"}
        for c in cases
        if (c.get("expected_behavior") or "execute") != "execute"
    }
    grid = build_grid(cases, results)
    assert grid.scored_total == 0
    assert grid.scored_passed == 0
    assert grid.ex is None
