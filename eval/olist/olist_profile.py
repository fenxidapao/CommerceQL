"""Olist 轨的 N-13 验真 profile（W2，`docs/07 §4.8` 的 `U-144`）。

与 `eval/_bootstrap.py::verify_frozen_inputs()` **同形**：返回
`{"checks": {..., "all_ok": bool}, "content_hash": ..., "n_cases": ...}`。
区别只在对象：合成轨查 `dataset_v1_frozen.json` + `data/ecom_sandbox.db`；
Olist 轨查 `eval/olist/dataset_v1.yaml`（或冻结件）+ `data/olist/olist_sandbox.db`。

三条硬边界
----------
1. **不改** `_bootstrap.py` 的常量与判据；Olist 走自己的 profile。
2. **不 skip、不降级**：缺 DB / 缺 stamp / 哈希不符 = 失败（调用方 exit 3）。
3. **不新写第二套口径判据**：逐题 C1–C7 仍走 `run_olist.check_case`。

两个哈希并列（详见 `hashing.py`）：共享 `content_hash` + Olist `full_hash`。
源模式没有 `gold_result_hash` 时，金标哈希项记 `n/a (source mode)`，**不报 False**。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.olist import run_olist as R
from eval.olist.hashing import read_stamps

EXPECTED_N_CASES = 60
EXPECTED_N_EXECUTE = 55
EXPECTED_N_INTERACTION = 5

PINNED_PYTHON = "3.13.14"
SANDBOX_DRIFT_NOTE = (
    "3.13.x 之间 SQLite 构建的 sha256 会漂移（W1 实测 3.13.13=`a67c5f7d…`、"
    "3.13.14=`17c14cee…`），不是库损坏；请用 3.13.14 复跑。"
)


class OlistVerificationError(RuntimeError):
    """Olist 输入验真失败（缺文件/缺 stamp/哈希不符）。"""


def _python_version() -> str:
    import platform

    return platform.python_version()


def _dataset_expected(dataset_path: Path, spec: dict[str, Any]) -> tuple[str | None, str | None, str]:
    if dataset_path.suffix.lower() in {".yaml", ".yml"}:
        stamps = read_stamps(dataset_path)
        return stamps.get("content_hash"), stamps.get("full_hash"), "stamped"
    return spec.get("content_hash"), spec.get("full_hash"), "frozen"


def _db_expected(spec: dict[str, Any]) -> tuple[str | None, str]:
    frozen = spec.get("sandbox_db_sha256")
    if frozen:
        return str(frozen), "frozen"
    manifest_path = Path(__file__).resolve().parent / "sandbox_manifest.json"
    if not manifest_path.is_file():
        return None, "manifest_missing"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return (manifest.get("sandbox") or {}).get("sha256"), "manifest"


def _hash_check(expected: str | None, actual: str | None, *, mode: str) -> dict[str, Any]:
    return {
        "expected": expected,
        "actual": actual,
        "mode": mode,
        "ok": expected is not None and actual == expected,
        **({} if expected is not None else {"error": "missing_expected_hash"}),
    }


def _count_check(expected: int, actual: int | None) -> dict[str, Any]:
    return {"expected": expected, "actual": actual, "ok": actual == expected}


def _gold_hash_check(report: dict[str, Any], spec: dict[str, Any], *, frozen: bool) -> dict[str, Any]:
    if not frozen:
        return {"mode": "n/a (source mode)", "ok": True}
    actual = {
        str(record["case_id"]): record.get("result_hash")
        for record in report.get("cases", [])
        if str(record.get("expected_behavior") or "execute") == "execute"
    }
    mismatches = [
        str(case["case_id"])
        for case in spec.get("cases", [])
        if str(case.get("expected_behavior") or "execute") == "execute"
        and case.get("gold_result_hash") != actual.get(str(case["case_id"]))
    ]
    return {
        "mode": "frozen",
        "checked_cases": len(actual),
        "mismatches": mismatches,
        "ok": not mismatches,
    }


def verify_from_report(
    report: dict[str, Any], dataset_path: str | Path, spec: dict[str, Any]
) -> dict[str, Any]:
    """把一次 `run_olist.run()` 的读数折成与 `_bootstrap` 同形的证据块。"""
    path = Path(dataset_path)
    expected_content, expected_full, mode = _dataset_expected(path, spec)
    expected_db, db_mode = _db_expected(spec)
    frozen = mode == "frozen"

    n_cases = int(report.get("n_cases") or 0)
    n_execute = int(report.get("n_execute_cases") or 0)
    n_interaction = int(report.get("n_interaction_cases") or 0)
    shape_ok = (
        n_cases == EXPECTED_N_CASES
        and n_execute == EXPECTED_N_EXECUTE
        and n_interaction == EXPECTED_N_INTERACTION
    )

    checks: dict[str, Any] = {
        "dataset_content_hash": _hash_check(
            expected_content, report.get("content_hash"), mode=mode
        ),
        "dataset_full_hash": _hash_check(
            expected_full, report.get("full_hash"), mode=mode
        ),
        "sandbox_db_sha256": {
            "expected": expected_db,
            "actual": report.get("sandbox_db_sha256"),
            "mode": db_mode,
            "python": _python_version(),
            "pinned_python": PINNED_PYTHON,
            "ok": expected_db is not None
            and report.get("sandbox_db_sha256") == expected_db,
            **(
                {"note": SANDBOX_DRIFT_NOTE}
                if expected_db is not None
                and report.get("sandbox_db_sha256") != expected_db
                else {}
            ),
        },
        "dataset_shape": {
            "expected": {
                "n_cases": EXPECTED_N_CASES,
                "n_execute_cases": EXPECTED_N_EXECUTE,
                "n_interaction_cases": EXPECTED_N_INTERACTION,
            },
            "actual": {
                "n_cases": n_cases,
                "n_execute_cases": n_execute,
                "n_interaction_cases": n_interaction,
            },
            "ok": shape_ok,
        },
        "gold_executable": _count_check(
            EXPECTED_N_EXECUTE, report.get("gold_executable")
        ),
        "caliber_match": _count_check(
            EXPECTED_N_EXECUTE, report.get("caliber_match")
        ),
        "interaction_unlabeled": _count_check(
            EXPECTED_N_INTERACTION, report.get("interaction_valid")
        ),
        "cases_valid": _count_check(EXPECTED_N_CASES, report.get("cases_valid")),
        "gold_result_hash": _gold_hash_check(report, spec, frozen=frozen),
    }
    checks["all_ok"] = all(
        value if isinstance(value, bool) else bool(value.get("ok"))
        for value in checks.values()
    )
    return {
        "profile": "olist",
        "dataset": str(path),
        "db": str(report.get("db")),
        "python": _python_version(),
        "mode": mode,
        "frozen": frozen,
        "checks": checks,
        "dataset_version": spec.get("dataset_version") or spec.get("dataset"),
        "frozen_at": spec.get("frozen_at"),
        "n_cases": n_cases,
        "n_execute_cases": n_execute,
        "n_interaction_cases": n_interaction,
        "content_hash": report.get("content_hash"),
        "full_hash": report.get("full_hash"),
        "sandbox_db_sha256": report.get("sandbox_db_sha256"),
    }


def verify_olist_inputs(
    dataset_path: str | Path,
    db_path: str | Path,
    *,
    bundle_path: str | Path | None = None,
    tenant: str = "T_A",
) -> dict[str, Any]:
    """跑一遍 60 题 gold + C1–C7，返回 N-13 证据块；失败抛 `OlistVerificationError`。"""
    path = Path(dataset_path)
    db = Path(db_path)
    if not path.is_file():
        raise OlistVerificationError(f"Olist 数据集不存在：{path}")
    if not db.is_file():
        raise OlistVerificationError(
            f"Olist 沙箱不存在：{db}\n先跑 deploy/demo/build_olist_sandbox.py；不 skip、不降级。"
        )
    spec = R.load_cases(path)
    report = R.run(
        path, db, tenant=spec.get("tenant", tenant), bundle_path=bundle_path
    )
    return verify_from_report(report, path, spec)
