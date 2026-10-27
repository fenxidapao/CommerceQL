"""`--batch` 的 dry-run 与三条路径/预算守卫（W2，`U-144` Step 6）。

本轮**没有 live 批准**：dry-run 只打印计划；`--live` 即使参数齐全也在账本前置门处拒绝。
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


def _require_db() -> None:
    if not SANDBOX_DB.is_file():
        pytest.skip(f"sandbox_db_absent: {SANDBOX_DB}")


def _base_args() -> list[str]:
    return [
        "--batch", "--limit", "5",
        "--dataset", str(DATASET), "--db", str(SANDBOX_DB),
    ]


def test_dry_run_prints_plan_and_writes_nothing(capsys) -> None:
    _require_db()
    probe = OLIST_DIR / "_probe_results_dryrun.json"
    probe.unlink(missing_ok=True)
    try:
        code = R.main([*_base_args(),
            "--batch-id", "w2_smoke",
            "--cassette", str(OLIST_DIR / "cassettes" / "olist_v1_smoke.jsonl"),
            "--out", str(probe),
        ])
        out = capsys.readouterr().out
    finally:
        exists = probe.exists()
        probe.unlink(missing_ok=True)

    assert code == 0
    assert exists is False
    assert "执行计划" in out
    assert "用例数        : 5" in out
    assert "未带 --yes" in out
    assert "执行器 DB" in out


def test_live_without_budget_is_rejected(capsys) -> None:
    _require_db()
    code = R.main([*_base_args(), "--live"])
    err = capsys.readouterr().err
    assert code == 2
    assert "--batch-id" in err and "--max-cost-cny" in err and "--max-calls" in err


def test_live_with_full_budget_hits_the_ledger_gate(capsys, monkeypatch) -> None:
    """参数齐全时也必须停在账本前置门（本轮不跑 live）。"""
    from eval.olist import olist_profile as P

    fake = {"content_hash": "sha256:" + "a" * 64, "full_hash": "sha256:" + "b" * 64}
    monkeypatch.setattr(P, "verify_olist_inputs", lambda *a, **k: fake)
    code = R.main([*_base_args(),
        "--live", "--yes", "--batch-id", "w2_probe",
        "--max-cost-cny", "5", "--max-calls", "10",
    ])
    err = capsys.readouterr().err
    assert code == 4
    assert "预算账本" in err
    assert "拒绝 --live" in err


def test_out_outside_olist_is_rejected(capsys) -> None:
    _require_db()
    code = R.main([*_base_args(), "--out", str(REPO_ROOT / "eval" / "results_v1.json")])
    err = capsys.readouterr().err
    assert code == 2
    assert "eval/olist 之外" in err


def test_cassette_outside_olist_is_rejected(capsys) -> None:
    _require_db()
    code = R.main([*_base_args(),
        "--cassette", str(REPO_ROOT / "eval" / "cassettes" / "x.jsonl"),
    ])
    err = capsys.readouterr().err
    assert code == 2
    assert "eval/olist 之外" in err
