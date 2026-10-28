"""预算账本只有一份实现（W2 live 前置门，`U-144`）。

`runner.main` 与 `run_olist --batch` 必须共用 `runner.load_budget_ledger` /
`save_budget_ledger` / `ledger_run_entry`；两个入口各抄一份键名 = 钱账有两个真相。
本文件锁 schema、键集与调用点。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import runner  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402

RUN_KEYS = {
    "batch_id", "live", "mode", "cases", "calls", "calls_unique",
    "tokens", "cost_cny", "budget_stop",
}


def _batch() -> dict:
    return {
        "records": [{"case_id": "g01"}, {"case_id": "g02"}],
        "usage": {"calls": 3, "tokens": 120, "cost_cny": 0.42},
        "calls_unique": 2,
        "budget_stop": None,
    }


def test_roundtrip_preserves_schema_and_totals(tmp_path) -> None:
    ledger = tmp_path / "budget.json"
    payload, prior = runner.load_budget_ledger(ledger)
    assert payload is None
    assert prior == {}

    totals = {"calls": 3, "tokens": 120, "cost_cny": 0.42}
    run = runner.ledger_run_entry(_batch(), batch_id="w2_r1", live=True, mode="record")
    assert set(run) == RUN_KEYS
    runner.save_budget_ledger(
        ledger,
        payload=payload,
        totals=totals,
        run=run,
        stamp={"generated_at": "2026-10-27T00:00:00+00:00", "git_rev": "abc1234",
               "git_dirty": False},
    )

    payload2, prior2 = runner.load_budget_ledger(ledger)
    assert payload2["schema"] == runner.LEDGER_SCHEMA == "W77_CALLS_LEDGER/v1"
    assert prior2 == totals
    entry = payload2["runs"][0]
    assert set(entry) == set(runner.LEDGER_RUN_KEYS) == RUN_KEYS | {
        "generated_at", "git_rev", "git_dirty",
    }
    assert entry["batch_id"] == "w2_r1"
    assert entry["live"] is True
    assert entry["cases"] == 2


def test_second_save_accumulates_runs_and_totals(tmp_path) -> None:
    ledger = tmp_path / "budget.json"
    payload, prior = runner.load_budget_ledger(ledger)
    runner.save_budget_ledger(
        ledger, payload=payload, totals={"calls": 3, "tokens": 1, "cost_cny": 0.1},
        run=runner.ledger_run_entry(_batch(), batch_id="r1", live=True, mode="record"),
        stamp={"generated_at": "t1", "git_rev": "a", "git_dirty": False},
    )
    payload, prior = runner.load_budget_ledger(ledger)
    assert prior["calls"] == 3
    runner.save_budget_ledger(
        ledger, payload=payload, totals={"calls": 6, "tokens": 2, "cost_cny": 0.2},
        run=runner.ledger_run_entry(_batch(), batch_id="r2", live=True, mode="record"),
        stamp={"generated_at": "t2", "git_rev": "a", "git_dirty": False},
    )
    payload, prior = runner.load_budget_ledger(ledger)
    assert prior["calls"] == 6
    assert [entry["batch_id"] for entry in payload["runs"]] == ["r1", "r2"]


def test_both_entrypoints_use_the_shared_functions() -> None:
    main_src = inspect.getsource(runner.main)
    batch_src = inspect.getsource(R.batch_mode)
    for source, label in ((main_src, "runner.main"), (batch_src, "run_olist.batch_mode")):
        assert "load_budget_ledger(" in source, label
        assert "save_budget_ledger(" in source, label
        assert "ledger_run_entry(" in source, label
    # 第二份账本实现的特征：自己拼 runs / schema。
    assert '"runs", []' not in batch_src
    assert '"schema": runner.LEDGER_SCHEMA' not in batch_src
