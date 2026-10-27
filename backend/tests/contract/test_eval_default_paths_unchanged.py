"""默认 166 合成轨的路径常量与 N-13 验真没被 Olist 改动。

W1 的整条 Olist 链路（`eval/olist/**`、`deploy/demo/**`、`semantic/bundle_olist_2018.yaml`）
**不许**动 `eval/_bootstrap.py` 的五个常量与它们的判据 —— 本文件是那条边界的机器断言。

第二条断言（`verify_frozen_inputs()`）依赖合成沙箱 `data/ecom_sandbox.db`：它不入库
（`*.db` 被 gitignore），库里没有时只能 `skip`（读数仅"常量未变"）；把它从
`CommerceQL-archive/local/ecom_sandbox.db` 放回 `data/` 后才会真跑"验真 all_ok"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO_ROOT / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()


def test_default_paths_are_still_the_synthetic_ones() -> None:
    expected = {
        "DATASET_PATH": EVAL_DIR / "dataset_v1_frozen.json",
        "GOLD_SEED_PATH": EVAL_DIR / "gold_query_seed_v1.json",
        "RED_TEAM_PATH": EVAL_DIR / "red_team_cases_v1.json",
        "SANDBOX_DB": REPO_ROOT / "data" / "ecom_sandbox.db",
        "BUNDLE_PATH": REPO_ROOT / "semantic" / "bundle_2026.09.14.1.yaml",
    }
    actual = {name: Path(getattr(_bootstrap, name)) for name in expected}
    assert actual == {name: path for name, path in expected.items()}


def test_olist_bundle_is_not_the_default_bundle() -> None:
    assert Path(_bootstrap.BUNDLE_PATH).name != "bundle_olist_2018.yaml"


def test_verify_frozen_inputs_all_ok_when_synthetic_sandbox_present() -> None:
    """N-13 验真：合成三件套 + 沙箱库都在时，`all_ok` 必须为真。"""
    if not Path(_bootstrap.SANDBOX_DB).is_file():
        pytest.skip(f"sandbox_db_absent: {_bootstrap.SANDBOX_DB}")

    evidence = _bootstrap.verify_frozen_inputs()
    assert evidence["checks"]["all_ok"] is True, evidence["checks"]
    assert evidence["checks"]["sandbox_db_sha256"]["ok"] is True


def test_olist_outputs_stay_inside_eval_olist() -> None:
    """Olist 轨的产物清单里不得出现 eval/ 根或 data/ecom_sandbox.db。"""
    olist_dir = EVAL_DIR / "olist"
    if not olist_dir.is_dir():
        pytest.skip(f"olist_track_absent: {olist_dir}")

    offenders = [
        p.as_posix()
        for p in olist_dir.rglob("*")
        if p.is_file()
        and p.name
        in {
            "dataset_v1_frozen.json",
            "gold_query_seed_v1.json",
            "MANIFEST_v1.json",
            "red_team_cases_v1.json",
            "ecom_sandbox.db",
        }
    ]
    assert not offenders, offenders
