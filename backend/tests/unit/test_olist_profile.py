"""N-13 Olist profile 的形状与失败模式（W2，`U-144`）。

两类断言：
· **绿**：源模式下 `checks.all_ok is True`，且 `gold_result_hash` 记 `n/a (source mode)`
  （不是构造性的 False）；
· **会红**：改记录 / 改期望 / 缺 DB 时 `all_ok` 必为 False 或直接抛错，不 skip。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OLIST_DIR = REPO_ROOT / "eval" / "olist"
SANDBOX_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402
from eval.olist import olist_profile as P  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402
from eval.olist.hashing import case_full_hash, read_stamps  # noqa: E402

DATASET = OLIST_DIR / "dataset_v1.yaml"

EXPECTED_CHECKS = {
    "dataset_content_hash",
    "dataset_full_hash",
    "sandbox_db_sha256",
    "dataset_shape",
    "gold_executable",
    "caliber_match",
    "interaction_unlabeled",
    "cases_valid",
    "gold_result_hash",
}


def _require_db() -> None:
    if not SANDBOX_DB.is_file():
        pytest.skip(f"sandbox_db_absent: {SANDBOX_DB}")


@pytest.fixture(scope="module")
def report() -> dict:
    _require_db()
    return R.run(DATASET, SANDBOX_DB)


def _verify(report: dict) -> dict:
    return P.verify_from_report(report, DATASET, R.load_cases(DATASET))


def test_evidence_shape_matches_bootstrap(report) -> None:
    evidence = _verify(report)
    assert set(evidence["checks"]) == EXPECTED_CHECKS | {"all_ok"}
    assert evidence["mode"] == "stamped"
    assert evidence["frozen"] is False
    assert evidence["n_cases"] == 60
    assert evidence["n_execute_cases"] == 55
    assert evidence["n_interaction_cases"] == 5


def test_source_mode_all_ok_and_gold_hash_is_na(report) -> None:
    checks = _verify(report)["checks"]
    assert checks["all_ok"] is True, checks
    assert checks["gold_result_hash"] == {"mode": "n/a (source mode)", "ok": True}


def test_source_mode_never_reports_constructive_false(report) -> None:
    """`wrap_eq_frozen=False` 是源模式的构造性事实，profile 不得把它当失败。"""
    assert all(
        record.get("gold", {}).get("frozen_hash") is None
        for record in report["cases"]
        if (record.get("expected_behavior") or "execute") == "execute"
    )
    assert _verify(report)["checks"]["gold_result_hash"]["ok"] is True


def test_tampered_expect_breaks_full_hash_only() -> None:
    stamps = read_stamps(DATASET)
    spec = R.load_cases(DATASET)
    tampered = copy.deepcopy(spec)
    tampered["cases"][20]["expect"]["time_filtered"] = not (
        tampered["cases"][20]["expect"]["time_filtered"]
    )
    assert bfs.case_content_hash(tampered["cases"]) == stamps["content_hash"]
    assert case_full_hash(tampered["cases"]) != stamps["full_hash"]


def test_tampered_metrics_or_assets_break_full_hash_only() -> None:
    stamps = read_stamps(DATASET)
    spec = R.load_cases(DATASET)
    for field in ("metrics", "assets"):
        tampered = copy.deepcopy(spec)
        case = tampered["cases"][20]
        case[field] = ["review"] if field == "assets" else ["order_cnt"]
        assert bfs.case_content_hash(tampered["cases"]) == stamps["content_hash"], field
        assert case_full_hash(tampered["cases"]) != stamps["full_hash"], field


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report.update(gold_executable=54),
        lambda report: report.update(caliber_match=54),
        lambda report: report.update(interaction_valid=4),
        lambda report: report.update(full_hash="sha256:" + "0" * 64),
        lambda report: report.update(content_hash="sha256:" + "1" * 64),
    ],
    ids=["gold_executable", "caliber_match", "interaction_valid", "full_hash", "content_hash"],
)
def test_broken_readings_turn_all_ok_false(report, mutate) -> None:
    tampered = copy.deepcopy(report)
    mutate(tampered)
    checks = _verify(tampered)["checks"]
    assert checks["all_ok"] is False


def test_missing_db_raises_instead_of_skipping(tmp_path) -> None:
    with pytest.raises(P.OlistVerificationError):
        P.verify_olist_inputs(DATASET, tmp_path / "missing.db")


def test_missing_stamp_is_a_failure(tmp_path) -> None:
    """源 YAML 去掉两个 stamp ⇒ 两个哈希项都红（不是 skip）。"""
    _require_db()
    stripped = tmp_path / "dataset_unstamped.yaml"
    lines = [
        line for line in DATASET.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("# content_hash:", "# full_hash:"))
    ]
    stripped.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    report = R.run(stripped, SANDBOX_DB)
    checks = P.verify_from_report(report, stripped, R.load_cases(stripped))["checks"]
    assert checks["dataset_content_hash"]["ok"] is False
    assert checks["dataset_full_hash"]["ok"] is False
    assert checks["all_ok"] is False
