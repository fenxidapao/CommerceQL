"""冻结工具（stamp/check/freeze）的可执行性与守卫（W2，`U-144`）。

本轮**不生成**正式冻结件：探针写到临时文件、断言完即删。
锁四件事：
· 冻结件含 content_hash + full_hash + sandbox_db_sha256 + 60 例 + 逐例 gold 哈希；
· `guard_output_path` 仍拒绝合成四件（尤其 `eval/dataset_v1_frozen.json`）；
· source stamp 不一致 ⇒ 拒绝冻结，且不落盘；
· `--check` 在 stamp 断裂时返回非绿。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OLIST_DIR = REPO_ROOT / "eval" / "olist"
SANDBOX_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
DATASET = OLIST_DIR / "dataset_v1.yaml"
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from eval.olist import build_dataset as B  # noqa: E402
from eval.olist.hashing import read_stamps  # noqa: E402


def _require_db() -> None:
    if not SANDBOX_DB.is_file():
        pytest.skip(f"sandbox_db_absent: {SANDBOX_DB}")


@pytest.fixture()
def probe_out():
    probe = OLIST_DIR / "_probe_dataset_v1_frozen.json"
    yield probe
    probe.unlink(missing_ok=True)


def test_freeze_probe_contains_every_required_field(probe_out) -> None:
    _require_db()
    result = B.freeze_source(DATASET, SANDBOX_DB, probe_out)
    frozen = yaml.safe_load(probe_out.read_text(encoding="utf-8"))
    stamps = read_stamps(DATASET)

    assert result["n_cases"] == 60
    assert frozen["content_hash"] == stamps["content_hash"]
    assert frozen["full_hash"] == stamps["full_hash"]
    assert frozen["sandbox_db_sha256"] == result["sandbox_db_sha256"]
    assert frozen["bundle"] == "semantic/bundle_olist_2018.yaml"
    assert frozen["bundle_version"]
    assert frozen["tenant"] == "T_A"
    assert frozen["frozen_at"]
    assert frozen["n_execute_cases"] == 55
    assert frozen["n_interaction_cases"] == 5
    assert frozen["gold_executable"] == frozen["caliber_match"] == 55
    assert frozen["interaction_valid"] == 5
    assert frozen["grid"]["scored_total"] == 55
    assert frozen["grid"]["struct_null_skipped"] == 5

    cases = frozen["cases"]
    assert len(cases) == 60
    for case in cases:
        if (case.get("expected_behavior") or "execute") == "execute":
            assert case["gold_result_hash"], case["case_id"]
            assert case["gold_result_rows"] >= 1, case["case_id"]
            assert all(case["caliber_checks"].values()), case["case_id"]
        else:
            assert case["gold_result_hash"] is None, case["case_id"]
            assert case["difficulty_struct"] is None, case["case_id"]


def test_freeze_refuses_existing_file_without_force(probe_out) -> None:
    _require_db()
    B.freeze_source(DATASET, SANDBOX_DB, probe_out)
    before = probe_out.read_bytes()
    with pytest.raises(B.FrozenWriteError):
        B.freeze_source(DATASET, SANDBOX_DB, probe_out)
    assert probe_out.read_bytes() == before


def test_guard_still_rejects_synthetic_frozen_paths() -> None:
    for name in (
        "dataset_v1_frozen.json",
        "gold_query_seed_v1.json",
        "MANIFEST_v1.json",
        "red_team_cases_v1.json",
    ):
        with pytest.raises(B.FrozenWriteError):
            B.guard_output_path(REPO_ROOT / "eval" / name)


def test_guard_rejects_paths_outside_olist() -> None:
    with pytest.raises(B.FrozenWriteError):
        B.guard_output_path(REPO_ROOT / "eval" / "olist_probe.json")


def test_freeze_refuses_when_source_stamp_is_stale(probe_out) -> None:
    _require_db()
    tampered = OLIST_DIR / "_probe_stale_stamp.yaml"
    spec = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    spec["cases"][0]["question"] = spec["cases"][0]["question"] + "（篡改）"
    try:
        tampered.write_text(
            yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )
        with pytest.raises(ValueError, match="stamp 不一致"):
            B.freeze_source(tampered, SANDBOX_DB, probe_out)
        assert not probe_out.exists()
    finally:
        tampered.unlink(missing_ok=True)


def test_check_green_on_real_source() -> None:
    _require_db()
    result = B.check_source(DATASET, SANDBOX_DB)
    assert result["all_ok"] is True, result
    assert result["report"]["empty_gold"] == []
    assert result["report"]["failed_caliber_checks"] == {}
