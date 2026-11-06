#!/usr/bin/env python
"""归因误判回放探针（T-03，零 LLM／零出站／只读输入）。

对象：2026-11-05 B7 三批里被标成 `gate_policy_gap` 的 33 条记录。
问题：这些记录的**真实** `gate1_reject_rule` 是不是 R06？若不是，就是
`harness.detect_gate_self_defect` 旧判据的误判（日期格式字面量撞 R14，被写成 F1/R06）。

本探针**不改闸门、不重跑模型、不改任何证据件**：只读已落盘的
`eval/olist/results_v3_r*.json`，用**现行判据**（`reject_rule` 不含 R06 ⇒
F1/F2 不能解释这次拒绝）逐条复算是否仍成立。输出「仍成立 / 属误判」两组计数，
作为 T-03 的关闭证据（见 `docs/10_未决问题台账.md`）。

⚠️ 只读：不写结果件、不写账本；`--out` 只写本探针自己的 JSON。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OLIST_DIR = Path(__file__).resolve().parent
CATEGORY = "gate_policy_gap"
DEFAULT_BATCHES = (1, 2, 3)

if hasattr(__import__("sys").stdout, "reconfigure"):
    __import__("sys").stdout.reconfigure(encoding="utf-8", errors="replace")


def load_records(path: Path) -> list[dict[str, Any]]:
    """results 件有两种形状（list / dict 里挂 records 或 results），都认。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    records = (
        data if isinstance(data, list) else data.get("records") or data.get("results") or []
    )
    return [r for r in records if isinstance(r, dict)]


def still_holds(record: dict[str, Any]) -> bool:
    """现行判据：只有 `reject_rule` 含 R06 时，F1/F2 才可能解释这次拒绝。

    这不是本探针自创的口径，镜像的是 `eval/harness.py::detect_gate_self_defect`
    里那句 `if reject_rule is not None and "R06" not in reject_rule: return None`。
    """
    rule = record.get("gate1_reject_rule")
    return rule is not None and "R06" in str(rule)


def probe(batches: tuple[int, ...]) -> dict[str, Any]:
    per_batch: list[dict[str, Any]] = []
    total_gap = total_keep = 0
    for idx in batches:
        path = OLIST_DIR / f"results_v3_r{idx}.json"
        if not path.is_file():
            per_batch.append({"batch": f"r{idx}", "present": False, "path": str(path)})
            continue
        records = load_records(path)
        gap = [
            r for r in records
            if (r.get("attribution") or {}).get("category") == CATEGORY
        ]
        kept = [r for r in gap if still_holds(r)]
        gap_rules = Counter(str(r.get("gate1_reject_rule")) for r in gap)
        per_batch.append(
            {
                "batch": f"r{idx}",
                "present": True,
                "n_records": len(records),
                "n_gate_policy_gap": len(gap),
                "gap_rules": dict(gap_rules),
                "n_under_new_logic": len(kept),
                "kept_case_ids": [str(r.get("case_id")) for r in kept],
            }
        )
        total_gap += len(gap)
        total_keep += len(kept)
    return {
        "schema": "T03_ATTRIBUTION_MISJUDGE_PROBE/v1",
        "category": CATEGORY,
        "criterion": "reject_rule 不含 R06 ⇒ F1/F2 不成立（镜像 harness.detect_gate_self_defect）",
        "batches": per_batch,
        "totals": {
            "n_gate_policy_gap": total_gap,
            "n_under_new_logic": total_keep,
            "n_misjudged": total_gap - total_keep,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="归因误判回放探针（零 LLM）")
    parser.add_argument(
        "--batches",
        type=int,
        nargs="+",
        default=list(DEFAULT_BATCHES),
        help="要回放的批次号（默认 1 2 3）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OLIST_DIR / "probe_attribution_misjudge.json",
        help="本探针自己的输出件（不碰任何证据件）",
    )
    args = parser.parse_args(argv)

    result = probe(tuple(args.batches))
    for row in result["batches"]:
        if not row["present"]:
            print(f"{row['batch']}: MISSING {row['path']}")
            continue
        print(
            f"{row['batch']}: n={row['n_records']} "
            f"gate_policy_gap={row['n_gate_policy_gap']} "
            f"gap_rules={row['gap_rules']} "
            f"under_new_logic={row['n_under_new_logic']}"
        )
    totals = result["totals"]
    print(
        f"TOTAL gate_policy_gap={totals['n_gate_policy_gap']} "
        f"under_new_logic={totals['n_under_new_logic']} "
        f"misjudged={totals['n_misjudged']}"
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
