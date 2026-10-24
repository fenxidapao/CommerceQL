"""W77-1：τ 非适用性证据（零出站；把全量回放的读数汇成 D-W77-1 可判定的块）。

输入是 `eval/runner.py` 刚跑出的 `results_w77_full166_applicability.json`（逐 case 已带
`binding_layer` / `binding_status` / `tau_raw`）与 r75 的全量回放。本脚本只做三件事：

1. 汇总分布：`binding_layer`／`binding_status`／`tau_raw.ok`／L4 候选数；
2. 与 r75 **逐条**比终态与等价（差异清单原样落盘，不四舍五入成"基本一致"）；
3. 把 D-W77-1 的三条件（`n_records==166`、`l4_decisions==0`、`ambiguous_bindings==0`）
   连同 `live=false` / `mode=replay` 的硬条件写成 `applicability.holds`。

🔴 任何一条不满足 ⇒ `holds=false` 并以非零码退出；W77-1 就此停手，**不改判据凑数**。
⚠️ 回放会复现历史计费（记录里的 `cost_cny` 是录制时的数），本轮**零新增支出**。

跑法（仓库根，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w77_applicability.py
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

REPLAY = os.path.join(HERE, "results_w77_full166_applicability.json")
R75 = os.path.join(HERE, "results_r75_full166_window.json")
EXPECTED_N = 166


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _equivalence(record: Mapping[str, Any]) -> bool | None:
    verdict = record.get("verdict")
    if not isinstance(verdict, Mapping):
        return None
    return verdict.get("equivalent")


def _distribution(values: Sequence[Any]) -> dict[str, int]:
    counts = Counter(str(v) for v in values)
    return {key: counts[key] for key in sorted(counts)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W77-1 τ 非适用性证据汇总")
    parser.add_argument("--replay", default=REPLAY)
    parser.add_argument("--r75", default=R75)
    parser.add_argument("--expected-n", type=int, default=EXPECTED_N)
    args = parser.parse_args(argv)

    replay = _load(args.replay)
    r75 = _load(args.r75)
    records = list(replay.get("records") or [])
    old_records = list(r75.get("records") or [])
    config = replay.get("config") or {}

    layers = _distribution([r.get("binding_layer") or "none" for r in records])
    statuses = _distribution([r.get("binding_status") or "none" for r in records])
    tau_ok = [r for r in records if (r.get("tau_raw") or {}).get("ok") is True]
    candidate_counts = Counter(
        len((r.get("tau_raw") or {}).get("candidate_ids") or []) for r in tau_ok
    )
    tau_reasons = _distribution(
        [
            (r.get("tau_raw") or {}).get("reason")
            or ("ok" if (r.get("tau_raw") or {}).get("ok") is True else "unknown")
            for r in records
        ]
    )
    l4_decisions = sum(1 for r in records if str(r.get("binding_layer") or "").upper() == "L4")
    ambiguous = statuses.get("ambiguous", 0)

    by_old = {str(r.get("case_id")): r for r in old_records}
    differences: list[dict[str, Any]] = []
    terminal_diffs = 0
    equivalence_diffs = 0
    for record in records:
        case_id = str(record.get("case_id"))
        old = by_old.get(case_id)
        if old is None:
            differences.append({"case_id": case_id, "kind": "missing_in_r75"})
            continue
        terminal_new, terminal_old = record.get("terminal_event"), old.get("terminal_event")
        equiv_new, equiv_old = _equivalence(record), _equivalence(old)
        if terminal_new != terminal_old:
            terminal_diffs += 1
        if equiv_new != equiv_old:
            equivalence_diffs += 1
        if terminal_new != terminal_old or equiv_new != equiv_old:
            differences.append({
                "case_id": case_id,
                "terminal_w77": terminal_new,
                "terminal_r75": terminal_old,
                "equivalent_w77": equiv_new,
                "equivalent_r75": equiv_old,
            })
    missing_in_r75 = sum(1 for d in differences if d.get("kind") == "missing_in_r75")

    conditions = {
        "n_records_166": len(records) == args.expected_n,
        "l4_decisions_zero": l4_decisions == 0,
        "ambiguous_bindings_zero": ambiguous == 0,
        "r75_terminal_identical": terminal_diffs == 0,
        "r75_equivalence_identical": equivalence_diffs == 0,
        "live_false": config.get("live") is False,
        "mode_replay": str(config.get("mode")) == "replay",
    }
    holds = all(conditions.values())

    applicability = {
        "task": "W77-1 τ 非适用性证据（零出站；不是 τ 校准证据）",
        "source": {
            "replay": os.path.relpath(args.replay, ROOT).replace("\\", "/"),
            "replay_git_rev": replay.get("git_rev"),
            "replay_git_dirty": replay.get("git_dirty"),
            "replay_generated_at": replay.get("generated_at"),
            "r75": os.path.relpath(args.r75, ROOT).replace("\\", "/"),
            "r75_git_rev": r75.get("git_rev"),
            "r75_git_dirty": r75.get("git_dirty"),
            "r75_generated_at": r75.get("generated_at"),
        },
        "n_records": len(records),
        "n_records_r75": len(old_records),
        "binding_layer_distribution": layers,
        "binding_status_distribution": statuses,
        "l4_decisions": l4_decisions,
        "ambiguous_bindings": ambiguous,
        "tau_raw_ok": len(tau_ok),
        "tau_raw_reason_distribution": tau_reasons,
        "l4_candidate_count_distribution": {
            str(k): candidate_counts[k] for k in sorted(candidate_counts)
        },
        "r75_comparison": {
            "terminal_differences": terminal_diffs,
            "equivalence_differences": equivalence_diffs,
            "missing_in_r75": missing_in_r75,
            "differences": differences,
        },
        "config": {
            "live": config.get("live"),
            "mode": config.get("mode"),
            "cassette": config.get("cassette"),
        },
        "historical_billing_note": (
            "历史计费仅随匣带回放，零新增；记录里的 cost_cny/tokens 是录制时的历史读数"
        ),
        "conditions": conditions,
        "holds": holds,
    }
    replay["applicability"] = applicability
    with open(args.replay, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(replay, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")

    print(f"written: {os.path.relpath(args.replay, ROOT)}")
    print(f"n_records={len(records)} l4_decisions={l4_decisions} ambiguous={ambiguous}")
    print(f"binding_layer={layers}")
    print(f"binding_status={statuses}")
    print(f"tau_raw.ok={len(tau_ok)} candidate_counts={dict(sorted(candidate_counts.items()))}")
    print(f"r75 terminal_diff={terminal_diffs} equivalence_diff={equivalence_diffs}")
    print(f"conditions={conditions}")
    print(f"holds={holds}")
    return 0 if holds else 1


if __name__ == "__main__":
    raise SystemExit(main())
