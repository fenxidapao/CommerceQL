#!/usr/bin/env python
"""Olist 60 题报告（W2，`U-144`）：离线证据 ＋ 3 批 `EX_official`。

两件事必须分开，否则读数会互相冒充
--------------------------------
1. **`EX_official`** 只来自 `eval/grid.py::build_grid`：分母 = 有机器难度标签且 `scored`
   的 execute 题；交互题（`difficulty_struct is None`）不进分母。
2. **交互正确** 的判据是运行时终态，不是 `verdict.equivalent`：
   `terminal_event == expected_behavior and infra_error is None`（与 `runner.py` 同一条）。
   `verdict` 对交互题恒 `None` ⇒ 用 `passed` 推会永远得到 0/5。

源模式（`gold.frozen_hash is None`）下 `wrap_eq_frozen` / `hash_matches` 是构造性的
`False`（`"x" == None`），本报告一律渲染 `n/a (source mode)`，不得报成"金标不一致"。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OLIST_DIR = Path(__file__).resolve().parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from eval.grid import build_grid  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402
from eval.olist.build_dataset import FrozenWriteError, guard_output_path, write_json  # noqa: E402
from eval.olist.hashing import case_full_hash  # noqa: E402

FIXED_LINES = (
    "EX_official = {passed} / scored_total = {pct}%",
    "分母构成：scored={scored} | struct_null_skipped={skipped} | execute={execute} | "
    "with_sql={with_sql} | with_result={with_result} | equivalent={equivalent}",
    "交互正确（不计入 EX）：refuse {refuse_ok}/2 ｜ clarify {clarify_ok}/3",
    "沙箱方言缺口（单列，不是模型错）：{dialect_gap}",
    "若报 EX_exec（非官方，仅 coverage）：{ex_exec}/55",
)


def interaction_correct(record: Mapping[str, Any]) -> bool:
    """运行时交互正确：终态等于期望行为，且没有基础设施错误。**不读 `passed`。**"""
    return (
        record.get("terminal_event") == record.get("expected_behavior")
        and record.get("infra_error") is None
    )


def _results_map(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for record in records:
        verdict = record.get("verdict") or {}
        mapping[str(record["case_id"])] = {
            "scored": bool(record.get("scored")),
            "passed": bool(verdict.get("equivalent")) if isinstance(verdict, dict) else False,
            "category": (record.get("attribution") or {}).get("category") or "unattributed",
        }
    return mapping


def _count(records: Iterable[Mapping[str, Any]], field: str) -> int:
    return sum(1 for record in records if record.get(field))


def batch_stats(cases: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    grid = build_grid(cases, _results_map(records))
    execute = [r for r in records if r.get("expected_behavior") == "execute"]
    clarify = [r for r in records if r.get("expected_behavior") == "clarify"]
    refuse = [r for r in records if r.get("expected_behavior") == "refuse"]
    with_result = [
        r for r in execute
        if r.get("predicted") and (r.get("predicted") or {}).get("sandbox_error") is None
    ]
    return {
        "scored_total": grid.scored_total,
        "scored_passed": grid.scored_passed,
        "ex": grid.ex,
        "struct_null_skipped": len(cases) - grid.scored_total,
        "n_execute": len(execute),
        "with_sql": _count(execute, "sql_text"),
        "with_result": len(with_result),
        "equivalent": grid.scored_passed,
        "ex_exec": (grid.scored_passed / len(execute)) if execute else None,
        "n_unscored": sum(1 for r in records if not r.get("scored")),
        "n_false_clarify": sum(1 for r in execute if r.get("terminal_event") == "clarify"),
        "n_false_refuse": sum(1 for r in execute if r.get("terminal_event") == "refuse"),
        "sandbox_dialect_gap": sum(
            1 for r in records
            if (r.get("attribution") or {}).get("category") == "sandbox_dialect_gap"
        ),
        "clarify_correct": sum(1 for r in clarify if interaction_correct(r)),
        "clarify_total": len(clarify),
        "refuse_correct": sum(1 for r in refuse if interaction_correct(r)),
        "refuse_total": len(refuse),
        "matrix": grid.matrix(),
        "attribution": dict(grid.attribution),
    }


def _dataset_hashes(dataset_path: Path) -> tuple[str, str]:
    import build_frozen_set as bfs

    raw = R.load_cases(dataset_path)
    return bfs.case_content_hash(raw["cases"]), case_full_hash(raw["cases"])


def validate_batches(
    batches: list[dict[str, Any]], cases: list[dict[str, Any]],
    content_hash: str, full_hash: str,
) -> list[dict[str, Any]]:
    """校验批次身份与证据链；返回逐批 stats。任一不成立即拒绝出 EX。"""
    if not batches:
        return []
    ids = [str((b.get("config") or {}).get("batch_id") or "") for b in batches]
    if any(not batch_id for batch_id in ids):
        raise ValueError(f"批次缺 config.batch_id：{ids}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"批次 batch_id 重复：{ids}")

    all_ids = {str(c["case_id"]) for c in cases}
    stats: list[dict[str, Any]] = []
    for batch in batches:
        evidence = batch.get("frozen_evidence") or {}
        if evidence.get("content_hash") != content_hash:
            raise ValueError(
                f"批次 {batch.get('config', {}).get('batch_id')} 的 content_hash 与数据集不一致"
            )
        if evidence.get("full_hash") != full_hash:
            raise ValueError(
                f"批次 {batch.get('config', {}).get('batch_id')} 的 full_hash 与数据集不一致"
            )
        records = list(batch.get("records") or [])
        record_ids = {str(r.get("case_id")) for r in records}
        if record_ids != all_ids:
            missing = sorted(all_ids - record_ids)
            extra = sorted(record_ids - all_ids)
            raise ValueError(
                f"批次 {batch.get('config', {}).get('batch_id')} 用例不完整："
                f"missing={missing} extra={extra}（冒烟批不得当 EX 用）"
            )
        stats.append(batch_stats(cases, records))
    return stats


def _fmt_ex(ex: float | None) -> str:
    return "UNVERIFIED" if ex is None else f"{ex:.4f}"


def _fixed_lines(values: Mapping[str, Any]) -> list[str]:
    return [line.format(**values) for line in FIXED_LINES]


def render_markdown(
    *,
    dataset_path: Path,
    mode: str,
    cases: list[dict[str, Any]],
    gold: dict[str, Any] | None,
    control: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    stats: list[dict[str, Any]],
    batch_ids: list[str],
) -> str:
    lines = [
        "# Olist 60 题评测报告（W2）",
        "",
        f"> 数据集：`{dataset_path.as_posix()}` ｜ 模式：{mode} ｜ "
        + ("offline · 未跑 live" if not stats else "3 个独立批次（各自进程 + 各自 --batch-id）"),
        "",
        "## 1. 结论（固定五行）",
        "",
        "```",
    ]
    if not stats:
        lines += _fixed_lines({
            "passed": "UNVERIFIED",
            "pct": "UNVERIFIED",
            "scored": "UNVERIFIED",
            "skipped": sum(1 for c in cases if c.get("difficulty_struct") is None),
            "execute": sum(
                1 for c in cases
                if (c.get("expected_behavior") or "execute") == "execute"
            ),
            "with_sql": "UNVERIFIED",
            "with_result": "UNVERIFIED",
            "equivalent": "UNVERIFIED",
            "refuse_ok": "UNVERIFIED",
            "clarify_ok": "UNVERIFIED",
            "dialect_gap": "UNVERIFIED",
            "ex_exec": "UNVERIFIED",
        })
    else:
        mean_ex = statistics.fmean(s["ex"] for s in stats)
        std_ex = statistics.stdev(s["ex"] for s in stats) if len(stats) > 1 else None
        first = stats[0]
        lines += _fixed_lines({
            "passed": first["scored_passed"],
            "pct": f"{first['ex'] * 100:.2f}",
            "scored": first["scored_total"],
            "skipped": first["struct_null_skipped"],
            "execute": first["n_execute"],
            "with_sql": first["with_sql"],
            "with_result": first["with_result"],
            "equivalent": first["equivalent"],
            "refuse_ok": first["refuse_correct"],
            "clarify_ok": first["clarify_correct"],
            "dialect_gap": first["sandbox_dialect_gap"],
            "ex_exec": first["equivalent"],
        })
    lines += ["```"]
    if stats:
        mean_ex = statistics.fmean(s["ex"] for s in stats)
        std_ex = statistics.stdev(s["ex"] for s in stats) if len(stats) > 1 else None
        lines += [
            f"`EX_official` = {mean_ex:.4f} ± "
            + (f"{std_ex:.4f}" if std_ex is not None else "n/a")
            + f"（3 批均值 ± 样本标准差，n={len(stats)}；batch_id={batch_ids}）",
            "",
            "> 固定五行中的 `EX_official` / 分母构成 / 交互正确取**第一批**的逐例读数；"
            "跨批汇总以本行的均值±样本标准差为准（μ 与 σ 不可混批）。",
        ]

    lines += [
        "",
        "## 2. 分母构成",
        "",
        "| batch_id | scored | passed | EX | struct_null_skipped | execute | with_sql | "
        "with_result | equivalent | n_unscored | false_clarify | false_refuse | dialect_gap |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for batch_id, stat in zip(batch_ids, stats, strict=True):
        lines.append(
            f"| {batch_id} | {stat['scored_total']} | {stat['scored_passed']} | "
            f"{_fmt_ex(stat['ex'])} | {stat['struct_null_skipped']} | {stat['n_execute']} | "
            f"{stat['with_sql']} | {stat['with_result']} | {stat['equivalent']} | "
            f"{stat['n_unscored']} | {stat['n_false_clarify']} | {stat['n_false_refuse']} | "
            f"{stat['sandbox_dialect_gap']} |"
        )
    if not stats:
        lines.append(
            "| — | UNVERIFIED | UNVERIFIED | UNVERIFIED | 5 | 55 | UNVERIFIED | UNVERIFIED | "
            "UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |"
        )

    cell_counts: dict[tuple[str, str], int] = {}
    for case in cases:
        if (case.get("expected_behavior") or "execute") != "execute":
            continue
        key = (str(case.get("difficulty_struct")), str(case.get("difficulty_semantic")))
        cell_counts[key] = cell_counts.get(key, 0) + 1
    lines += [
        "",
        "### 4×3 网格（数据集现算，execute 题）",
        "",
        "| struct \\ semantic | low | medium | high |",
        "|---|---|---|---|",
    ]
    for level in ("easy", "medium", "hard", "extra"):
        lines.append(
            f"| {level} | "
            + " | ".join(str(cell_counts.get((level, sem), 0)) for sem in ("low", "medium", "high"))
            + " |"
        )
    lines.append(
        "| **合计** | "
        + " | ".join(
            str(sum(cell_counts.get((level, sem), 0) for level in ("easy", "medium", "hard", "extra")))
            for sem in ("low", "medium", "high")
        )
        + " |"
    )

    lines += [
        "",
        "## 3. 交互正确（运行时判据，不计入 EX）",
        "",
        "判据 = `terminal_event == expected_behavior and infra_error is None`；"
        "**不读 `verdict.equivalent`**（交互题 verdict 恒 None）。",
        "",
    ]
    if stats:
        lines.append(
            "| batch_id | refuse | clarify |\n|---|---|---|\n"
            + "\n".join(
                f"| {batch_id} | {s['refuse_correct']}/{s['refuse_total']} | "
                f"{s['clarify_correct']}/{s['clarify_total']} |"
                for batch_id, s in zip(batch_ids, stats, strict=True)
            )
        )
    else:
        lines.append("refuse `UNVERIFIED`/2 ｜ clarify `UNVERIFIED`/3（未跑 live）")

    lines += [
        "",
        "## 4. 金标与口径（离线证据）",
        "",
    ]
    if gold:
        lines += [
            f"- n_cases / n_execute / n_interaction = {gold.get('n_cases')} / "
            f"{gold.get('n_execute_cases')} / {gold.get('n_interaction_cases')}",
            f"- gold_executable = {gold.get('gold_executable')}/"
            f"{gold.get('n_execute_cases')}；caliber_match = {gold.get('caliber_match')}/"
            f"{gold.get('n_execute_cases')}；interaction_valid = "
            f"{gold.get('interaction_valid')}/{gold.get('n_interaction_cases')}",
            f"- content_hash = `{gold.get('content_hash')}`",
            f"- full_hash = `{gold.get('full_hash')}`",
            f"- sandbox_db_sha256 = `{gold.get('sandbox_db_sha256')}`",
            "- `wrap_eq_frozen` / `hash_matches`：`n/a (source mode)`"
            "（源 YAML 无 `gold_result_hash`；构造性 False 不是不一致）"
            if mode == "stamped" else
            "- `wrap_eq_frozen` / `hash_matches`：按冻结件逐例校验",
        ]
    else:
        lines.append("- 未提供 `--gold`：金标侧读数 `UNVERIFIED`。")

    if profile:
        checks = profile.get("checks") or {}
        lines += [
            "",
            "### N-13（Olist profile）",
            "",
            f"- mode = {profile.get('mode')}；all_ok = **{checks.get('all_ok')}**",
            "- dataset_content_hash = "
            f"`{(checks.get('dataset_content_hash') or {}).get('ok')}`；dataset_full_hash = "
            f"`{(checks.get('dataset_full_hash') or {}).get('ok')}`；sandbox_db_sha256 = "
            f"`{(checks.get('sandbox_db_sha256') or {}).get('ok')}`",
        ]

    if control:
        pos = control.get("positive") or {}
        neg = control.get("negative") or {}
        lines += [
            "",
            "### 仪器正/负控（不是模型 EX）",
            "",
            f"- positive = {pos.get('scored_passed')}/{pos.get('scored_total')}；"
            f"negative = {neg.get('scored_passed')}/{neg.get('scored_total')}；"
            f"not_ex_official = {control.get('not_ex_official')}",
            "- 负控用**同列名、同行数**的扰动值，确保走值比较分支（空表会走列数早退）。",
        ]

    lines += [
        "",
        "## 5. 已知偏差",
        "",
        "- 无 `ordered` / `percent_ok`：排序只在两侧 SQL 都含 ORDER BY 时按序比；"
        "容差固定 `REL_TOL=1e-6`。",
        "- `ast_gate` 是 postgres 方言、沙箱是 SQLite ⇒ 预期出现 `sandbox_dialect_gap`，"
        "单列、不归因模型。",
        "- Olist 数据实际止于 2018-08（9 月 1 单、10 月 0 单）。",
        "- `gold_executable` 的分母是 55 条 execute；交互题无 gold，不冒充可执行 SQL。",
        "",
    ]
    return "\n".join(lines)


def _load_json(path: Path | None) -> Any:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist 60 题报告（offline / 3 批 EX）")
    parser.add_argument("--dataset", default=str(OLIST_DIR / "dataset_v1.yaml"))
    parser.add_argument("--results", nargs="*", default=[])
    parser.add_argument("--profile", default=None)
    parser.add_argument("--gold", default=None)
    parser.add_argument("--control", default=None)
    parser.add_argument("--out", default=str(OLIST_DIR / "report.md"))
    parser.add_argument("--json-out", default=str(OLIST_DIR / "report.json"))
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        print(f"数据集不存在：{dataset_path}", file=sys.stderr)
        return 3

    try:
        out = guard_output_path(args.out)
        json_out = guard_output_path(args.json_out)
    except FrozenWriteError as exc:
        print(f"拒绝写入：{exc}", file=sys.stderr)
        return 2

    spec = R.load_annotated_cases(dataset_path)
    cases = spec["cases"]
    content_hash, full_hash = _dataset_hashes(dataset_path)
    mode = "frozen" if dataset_path.suffix.lower() == ".json" else "stamped"

    gold = _load_json(Path(args.gold)) if args.gold else None
    control = _load_json(Path(args.control)) if args.control else None
    profile = _load_json(Path(args.profile)) if args.profile else None

    batches = [_load_json(Path(p)) for p in args.results]
    try:
        stats = validate_batches(batches, cases, content_hash, full_hash)
    except ValueError as exc:
        print(f"批次校验失败：{exc}", file=sys.stderr)
        return 3
    batch_ids = [str((b.get("config") or {}).get("batch_id")) for b in batches]

    markdown = render_markdown(
        dataset_path=dataset_path, mode=mode, cases=cases, gold=gold,
        control=control, profile=profile, stats=stats, batch_ids=batch_ids,
    )
    out.write_text(markdown, encoding="utf-8", newline="\n")

    payload = {
        "mode": "offline" if not stats else "batches",
        "dataset": str(dataset_path),
        "content_hash": content_hash,
        "full_hash": full_hash,
        "batch_ids": batch_ids,
        "batches": stats,
        "ex_official": (
            None if not stats else {
                "mean": statistics.fmean(s["ex"] for s in stats),
                "std": (
                    statistics.stdev(s["ex"] for s in stats) if len(stats) > 1 else None
                ),
                "n": len(stats),
            }
        ),
        "interaction_judge": "terminal_event == expected_behavior and infra_error is None",
        "fixed_lines": _fixed_lines({
            "passed": (stats[0]["scored_passed"] if stats else "UNVERIFIED"),
            "pct": (f"{stats[0]['ex'] * 100:.2f}" if stats else "UNVERIFIED"),
            "scored": (stats[0]["scored_total"] if stats else "UNVERIFIED"),
            "skipped": (stats[0]["struct_null_skipped"] if stats else
                        sum(1 for c in cases if c.get("difficulty_struct") is None)),
            "execute": (stats[0]["n_execute"] if stats else
                        sum(1 for c in cases if (c.get("expected_behavior") or "execute") == "execute")),
            "with_sql": (stats[0]["with_sql"] if stats else "UNVERIFIED"),
            "with_result": (stats[0]["with_result"] if stats else "UNVERIFIED"),
            "equivalent": (stats[0]["equivalent"] if stats else "UNVERIFIED"),
            "refuse_ok": (stats[0]["refuse_correct"] if stats else "UNVERIFIED"),
            "clarify_ok": (stats[0]["clarify_correct"] if stats else "UNVERIFIED"),
            "dialect_gap": (stats[0]["sandbox_dialect_gap"] if stats else "UNVERIFIED"),
            "ex_exec": (stats[0]["equivalent"] if stats else "UNVERIFIED"),
        }),
        "gold": gold,
        "control": control,
        "profile": profile,
    }
    write_json(json_out, payload, indent=2)
    print(f"[out] {out.relative_to(REPO_ROOT).as_posix()}")
    print(f"[json] {json_out.relative_to(REPO_ROOT).as_posix()}")
    if stats:
        print(f"EX_official = {payload['ex_official']['mean']:.4f} ± "
              f"{payload['ex_official']['std']:.4f} (n={len(stats)})")
    else:
        print("EX_official = UNVERIFIED（offline，未跑 live）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
