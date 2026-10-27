#!/usr/bin/env python
"""Olist 轨的落盘守卫 ＋ 数据集 stamp/check/freeze。

归属窗口：W1 实施窗（`U-143`）＋ W2 实施窗（`U-144`）。

为什么需要它
------------
`eval/build_frozen_set.py` 的 `OUT_DATASET` / `OUT_MANIFEST` 与
`eval/build_gold_seed.py` 的 `DATASET` / `OUT` 都是**写死常量**。
在 Olist 轨误调这两者的 `main()` / `build()` 会直接覆盖合成冻结集。
⇒ 本模块是 Olist 侧**唯一**的落盘入口：任何输出先过 `guard_output_path()`。

边界
----
· 只复用 `build_frozen_set` 的纯函数，不新写第二份哈希口径（AGENTS.md §5 第 1 条）。
· **禁止**调用 `build_frozen_set.main()` / `build_gold_seed.main()`。
· W1 的输出只落 `eval/olist/**`；冻结件由 W2 在同一个目录下生成。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
REPO_ROOT = EVAL_ROOT.parent

OLIST_ROOT = HERE

for _p in (str(REPO_ROOT), str(EVAL_ROOT), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval.olist.hashing import case_full_hash, read_stamps, stamp_lines  # noqa: E402

#: 合成轨的四个冻结件 —— 任何一条被 Olist 轨写到都是事故。
FROZEN_PATHS: tuple[Path, ...] = (
    EVAL_ROOT / "dataset_v1_frozen.json",
    EVAL_ROOT / "gold_query_seed_v1.json",
    EVAL_ROOT / "MANIFEST_v1.json",
    EVAL_ROOT / "red_team_cases_v1.json",
)

_RESOLVED_FROZEN = tuple(p.resolve() for p in FROZEN_PATHS)
_RESOLVED_OLIST_ROOT = OLIST_ROOT.resolve()


class FrozenWriteError(RuntimeError):
    """Olist 轨试图写合成冻结件，或写到 `eval/olist/` 之外的路径。"""


def guard_output_path(path: str | os.PathLike[str]) -> Path:
    """把输出路径解析成绝对路径；不合法就抛 `FrozenWriteError`。

    两条判据：① 不得等于四个冻结件之一；② 必须是 `eval/olist/` 的**严格后代**。
    用 `resolve()` 先归一化，符号链接与 `..` 都逃不掉。
    """
    target = Path(path).resolve()
    if target in _RESOLVED_FROZEN:
        raise FrozenWriteError(
            f"拒绝写入合成冻结件：{target}\n"
            f"Olist 轨只能写 {_RESOLVED_OLIST_ROOT} 之下；冻结件由 W2 在 eval/olist/ 下生成。"
        )
    if _RESOLVED_OLIST_ROOT not in target.parents:
        raise FrozenWriteError(
            f"拒绝写入 eval/olist 之外的路径：{target}\n"
            f"允许的根 = {_RESOLVED_OLIST_ROOT}"
        )
    return target


def write_json(path: str | os.PathLike[str], obj: Any, *, indent: int = 2) -> Path:
    """经守卫落一份 JSON（UTF-8、LF、末尾换行）。"""
    target = guard_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)
        fh.write("\n")
    return target


def load_frozen_pure():
    """取 `build_frozen_set` 的纯函数入口（需要 `eval/` 已在 `sys.path` 上）。

    只借 `tenant_wrap` / `result_hash` / `case_content_hash` —— 不碰它的 `main()`。
    """
    try:
        import build_frozen_set
    except ModuleNotFoundError as exc:  # pragma: no cover - 只在调用方漏 bootstrap 时触发
        raise ModuleNotFoundError(
            "build_frozen_set 不可导入：请先把 <repo>/eval 放进 sys.path"
            "（`eval/_bootstrap.py::bootstrap()` 会做这件事）"
        ) from exc
    return build_frozen_set


# ---------------------------------------------------------------------------
# W2：stamp / check / freeze
# ---------------------------------------------------------------------------

def _read_spec(path: Path) -> dict[str, Any]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _compute_hashes(spec: dict[str, Any]) -> tuple[str, str]:
    bfs = load_frozen_pure()
    return bfs.case_content_hash(spec["cases"]), case_full_hash(spec["cases"])


_STAMP_LINE = re.compile(r"^# (content_hash|full_hash): ")


def stamp_source(path: str | os.PathLike[str]) -> dict[str, str]:
    """重写源 YAML 头部的两个 stamp（幂等；不碰正文）。"""
    target = guard_output_path(path)
    spec = _read_spec(target)
    content_hash, full_hash = _compute_hashes(spec)
    content_line, full_line = stamp_lines(content_hash, full_hash)

    raw = target.read_text(encoding="utf-8").splitlines()
    header: list[str] = []
    body: list[str] = []
    in_header = True
    for line in raw:
        if in_header and line.strip() == "cases:":
            in_header = False
        if in_header and _STAMP_LINE.match(line):
            continue
        (header if in_header else body).append(line)

    insert_at = next(
        (i for i, line in enumerate(header) if line.strip().startswith("dataset:")),
        len(header),
    )
    header[insert_at:insert_at] = [content_line, full_line]
    target.write_text("\n".join(header + body).rstrip() + "\n", encoding="utf-8", newline="\n")
    return {"content_hash": content_hash, "full_hash": full_hash}


def _stamps_match(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    content_hash, full_hash = _compute_hashes(spec)
    stamps = read_stamps(path) if path.suffix.lower() in {".yaml", ".yml"} else {
        "content_hash": spec.get("content_hash"),
        "full_hash": spec.get("full_hash"),
    }
    return {
        "content_hash": {
            "expected": stamps.get("content_hash"),
            "actual": content_hash,
            "ok": stamps.get("content_hash") == content_hash,
        },
        "full_hash": {
            "expected": stamps.get("full_hash"),
            "actual": full_hash,
            "ok": stamps.get("full_hash") == full_hash,
        },
    }


def _check_report(report: dict[str, Any]) -> dict[str, Any]:
    execute = [
        r for r in report["cases"] if (r.get("expected_behavior") or "execute") == "execute"
    ]
    empty = [r["case_id"] for r in execute if not r.get("rows")]
    failed_checks = {
        r["case_id"]: [k for k, ok in (r.get("checks") or {}).items() if not ok]
        for r in execute
        if not all((r.get("checks") or {}).values())
    }
    shape_ok = (
        report["gold_executable"] == report["n_execute_cases"]
        and report["caliber_match"] == report["n_execute_cases"]
        and report["interaction_valid"] == report["n_interaction_cases"]
    )
    return {
        "gold_executable": report["gold_executable"],
        "caliber_match": report["caliber_match"],
        "interaction_valid": report["interaction_valid"],
        "cases_valid": report["cases_valid"],
        "n_cases": report["n_cases"],
        "n_execute_cases": report["n_execute_cases"],
        "n_interaction_cases": report["n_interaction_cases"],
        "empty_gold": empty,
        "failed_caliber_checks": failed_checks,
        "shape_ok": shape_ok,
        "ok": shape_ok and not empty and not failed_checks,
    }


def check_source(
    source: str | os.PathLike[str], db_path: str | os.PathLike[str]
) -> dict[str, Any]:
    """复算两个 stamp + 逐题 C1–C7 + 每例 ≥1 行；不写盘。"""
    from eval.olist import run_olist as R

    path = Path(source)
    spec = _read_spec(path)
    stamps = _stamps_match(path, spec)
    report = R.run(path, Path(db_path))
    checked = _check_report(report)
    return {
        "mode": "check",
        "source": str(path),
        "stamps": stamps,
        "report": checked,
        "all_ok": stamps["content_hash"]["ok"] and stamps["full_hash"]["ok"] and checked["ok"],
    }


def freeze_source(
    source: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    out: str | os.PathLike[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """生成冻结件：先验 source 两个 stamp，再执行 gold；只落 `eval/olist/**`。"""
    from eval.olist import run_olist as R
    from layering import annotate_case

    src = Path(source)
    target = guard_output_path(out)
    if target.exists() and not force:
        raise FrozenWriteError(
            f"冻结件已存在：{target}\n改集请走 v2（或显式 --force 覆盖）；不静默重写。"
        )

    spec = _read_spec(src)
    stamps = _stamps_match(src, spec)
    if not (stamps["content_hash"]["ok"] and stamps["full_hash"]["ok"]):
        raise ValueError(f"source stamp 不一致，拒绝冻结：{json.dumps(stamps, ensure_ascii=False)}")

    report = R.run(src, Path(db_path))
    checked = _check_report(report)
    if not checked["ok"]:
        raise ValueError(f"gold/口径未全绿，拒绝冻结：{json.dumps(checked, ensure_ascii=False)}")

    by_id = {r["case_id"]: r for r in report["cases"]}
    frozen_cases: list[dict[str, Any]] = []
    for case in spec["cases"]:
        record = by_id[str(case["case_id"])]
        annotated = annotate_case(case)
        merged = dict(case)
        merged.update(
            {
                "difficulty_struct": annotated["difficulty_struct"],
                "difficulty_semantic": annotated["difficulty_semantic"],
                "gold_result_hash": record.get("result_hash"),
                "gold_result_rows": record.get("rows"),
                "gold_result_cols": record.get("cols"),
                "caliber_checks": record.get("checks"),
            }
        )
        frozen_cases.append(merged)

    cells: dict[tuple[str, str], int] = {}
    for case in frozen_cases:
        key = (str(case["difficulty_struct"]), str(case["difficulty_semantic"]))
        cells[key] = cells.get(key, 0) + 1
    scored_total = sum(
        1
        for case in frozen_cases
        if case["difficulty_struct"] is not None and case["difficulty_semantic"] is not None
    )

    frozen = {
        "dataset_version": spec.get("dataset_version") or spec.get("dataset"),
        "dataset": spec.get("dataset"),
        "bundle": spec.get("bundle"),
        "bundle_version": report["bundle"]["version"],
        "tenant": spec.get("tenant"),
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "content_hash": report["content_hash"],
        "full_hash": report["full_hash"],
        "sandbox_db_sha256": report["sandbox_db_sha256"],
        "n_cases": report["n_cases"],
        "n_execute_cases": report["n_execute_cases"],
        "n_interaction_cases": report["n_interaction_cases"],
        "gold_executable": report["gold_executable"],
        "caliber_match": report["caliber_match"],
        "interaction_valid": report["interaction_valid"],
        "grid": {
            "scored_total": scored_total,
            "struct_null_skipped": report["n_cases"] - scored_total,
            "cells": [
                {"difficulty_struct": level, "difficulty_semantic": sem, "n": n}
                for (level, sem), n in sorted(cells.items())
            ],
        },
        "cases": frozen_cases,
    }
    write_json(target, frozen)
    return {
        "mode": "freeze",
        "source": str(src),
        "out": str(target),
        "content_hash": frozen["content_hash"],
        "full_hash": frozen["full_hash"],
        "sandbox_db_sha256": frozen["sandbox_db_sha256"],
        "n_cases": frozen["n_cases"],
        "scored_total": scored_total,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist 数据集 stamp / check / freeze")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stamp", action="store_true", help="重写源 YAML 的两个 stamp")
    mode.add_argument("--check", action="store_true", help="复算 stamp + C1–C7 + 行数（不写盘）")
    mode.add_argument("--freeze", action="store_true", help="生成冻结件（需 stamp 与 gold 全绿）")
    parser.add_argument("--source", default=str(HERE / "dataset_v1.yaml"))
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "olist" / "olist_sandbox.db"))
    parser.add_argument("--out", default=str(HERE / "dataset_v1_frozen.json"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.stamp:
            hashes = stamp_source(args.source)
            print(json.dumps(hashes, ensure_ascii=False, indent=2))
            return 0
        if args.check:
            result = check_source(args.source, args.db)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["all_ok"] else 1
        result = freeze_source(args.source, args.db, args.out, force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except FrozenWriteError as exc:
        print(f"拒绝写入：{exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
