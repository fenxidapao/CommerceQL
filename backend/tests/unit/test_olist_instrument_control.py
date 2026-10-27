"""仪器正/负控：证明 `scored_total` 与值比较分支都真的在工作（W2，`U-144` Step 4）。

正控 = 金标 vs 金标（55/55）；负控 = **同列名、同行数**的扰动值（0/55）。
负控绝不能用空表：空 pred 只有 0 列，`compare_tables` 会走列数早退分支，
根本没比较值 ⇒ 那样的 −0/55 什么也证明不了。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OLIST_DIR = REPO_ROOT / "eval" / "olist"
DATASET = OLIST_DIR / "dataset_v1.yaml"
SANDBOX_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from eval.olist import run_olist as R  # noqa: E402


@pytest.fixture(scope="module")
def control() -> dict:
    if not SANDBOX_DB.is_file():
        pytest.skip(f"sandbox_db_absent: {SANDBOX_DB}")
    return R.instrument_control(DATASET, SANDBOX_DB)


def test_positive_control_is_full_pass(control) -> None:
    assert control["positive"]["scored_passed"] == 55
    assert control["positive"]["scored_total"] == 55
    assert control["positive"]["ex"] == 1.0


def test_negative_control_is_zero_pass(control) -> None:
    assert control["negative"]["scored_passed"] == 0
    assert control["negative"]["scored_total"] == 55
    assert control["negative"]["ex"] == 0.0


def test_negative_control_uses_same_shape(control) -> None:
    """同列名同行数 ⇒ 走的是值比较，不是列数/行数早退。"""
    for entry in control["cases"]:
        assert entry["error"] is None, entry
        assert entry["gold_rows"] >= 1, entry
        assert entry["pred_shape"] == {
            "columns": entry["gold_cols"], "rows": entry["gold_rows"],
        }, entry


def test_interactions_do_not_enter_scored_total(control) -> None:
    assert control["n_cases"] == 60
    assert control["n_execute_cases"] == 55
    assert control["positive"]["scored_total"] == control["negative"]["scored_total"] == 55


def test_control_is_not_ex_official(control) -> None:
    assert control["not_ex_official"] is True
    assert control["all_ok"] is True
