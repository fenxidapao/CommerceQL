"""默认 166 合成轨的路径常量与 N-13 验真没被 Olist 改动。

W1 的整条 Olist 链路（`eval/olist/**`、`deploy/demo/**`、`semantic/bundle_olist_2018.yaml`）
**不许**动 `eval/_bootstrap.py` 的五个常量与它们的判据 —— 本文件是那条边界的机器断言。

第二条断言（`verify_frozen_inputs()`）依赖合成沙箱 `data/ecom_sandbox.db`：它不入库
（`*.db` 被 gitignore），库里没有时只能 `skip`（读数仅"常量未变"）；把它从
`CommerceQL-archive/local/ecom_sandbox.db` 放回 `data/` 后才会真跑"验真 all_ok"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO_ROOT / "eval"
for _p in (str(REPO_ROOT), str(EVAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402
from eval.olist.hashing import case_full_hash  # noqa: E402


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
    """Olist 轨的产物清单里不得出现 eval/ 根或 data/ecom_sandbox.db。

    U-146：`eval/olist/dataset_v1_frozen.json` 是**精确允许**的唯一例外 ——
    它由 W2 在冒烟通过后生成，路径由派单固定；其余四个合成冻结件与 `ecom_sandbox.db`
    仍一律禁止出现在 `eval/olist/` 下。
    """
    olist_dir = EVAL_DIR / "olist"
    if not olist_dir.is_dir():
        pytest.skip(f"olist_track_absent: {olist_dir}")

    allowed = {olist_dir / "dataset_v1_frozen.json"}
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
        and p.resolve() not in {path.resolve() for path in allowed}
    ]
    assert not offenders, offenders


def test_olist_frozen_file_is_valid_if_present() -> None:
    """冻结件存在时校验它自洽（本轮不生成 ⇒ 正常情况下 skip）。"""
    frozen_path = EVAL_DIR / "olist" / "dataset_v1_frozen.json"
    if not frozen_path.is_file():
        pytest.skip(f"olist_frozen_not_generated_yet: {frozen_path}")

    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    cases = frozen["cases"]
    assert frozen["content_hash"] == bfs.case_content_hash(cases)
    assert frozen["full_hash"] == case_full_hash(cases)
    assert len(frozen["sandbox_db_sha256"]) == 64
    assert len(cases) == 60
    assert sum(
        1 for case in cases
        if (case.get("expected_behavior") or "execute") == "execute"
    ) == 55
