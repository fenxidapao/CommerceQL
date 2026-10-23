"""W75-3：**当前门禁复算**（零出站材料；不是官方快照）。

派单 §96.8 W75-3：用冻结集网格与最新 replay 复算八格，逐格标输入来源与是否过期。
🔴 `backend/reports/w6/eval_metrics.json`（官方快照 `88f3500` / PASS 1/8）**不刷新** ——
本产物只回答"按今天的输入，八格读什么"，不代表官方通过。

输入（逐格注明）：
* **G-2**：冻结集 166 条 × `results_r75_full166_window.json`（W75-1 窗口强制后）的
  `scored/passed/attribution` → `grid.build_grid`；判定走 `gates.evaluate_gates`；
* **G-5**：同一 replay 的 `expected_behavior`/`terminal` → `reporter._refusal_counts`；
* **G-7**：`backend/reports/w6/probe_metric_values.json`（本轮按**同一 replay** 重跑，
  `--system-replay` 指向它）的 `system_consistent/system_total`；
* **G-8**：同一 replay 的澄清计数（`--second-round` 未开 ⇒ 后半句无可测分子）；
* **G-1/G-3/G-4/G-6**：无当期输入 ⇒ 引用官方快照的旧判定并标 `stale`（不重算、不刷新）。

跑法（CommerceQL 根目录，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w75_gate_recompute.py
产物：`eval/results_r75_gate_recompute.json`
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402
import gates as gates_mod  # noqa: E402
import grid as grid_mod  # noqa: E402
import reporter  # noqa: E402

REPLAY = os.path.join(HERE, "results_r75_full166_window.json")
PROBE = os.path.join(ROOT, "backend", "reports", "w6", "probe_metric_values.json")
OFFICIAL = os.path.join(ROOT, "backend", "reports", "w6", "eval_metrics.json")
OUT = os.path.join(HERE, "results_r75_gate_recompute.json")

#: 本轮本地 P0 证据（unit + eval + contract；集成层因本机无 PG 未跑）。
LOCAL_P0 = {
    "passed": 2680,
    "failed": 0,
    "errors": 0,
    "integration_ran": False,
    "source": "W75 本轮 pytest backend/tests/{unit,eval,contract} -q ⇒ 2680 passed / 0 failed",
}

#: 本轮**没有当期输入**的格：只引用官方快照（`88f3500`），必须标 `stale`。
#: G-1 例外：本轮有本地 pytest 读数（fresh），但它缺集成层 ⇒ 只判 PARTIAL。
_STALE_GATES = ("G-3", "G-4", "G-6")


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _results_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(r.get("case_id")): {
            "scored": bool(r.get("scored")),
            "passed": bool((r.get("verdict") or {}).get("equivalent")),
            "category": str((r.get("attribution") or {}).get("category") or ""),
        }
        for r in records
    }


def main() -> int:
    dataset = _load(_bootstrap.DATASET_PATH)
    replay = _load(REPLAY)
    probe = _load(PROBE)
    official = _load(OFFICIAL)

    records = list(replay["records"])
    cases = list(dataset["cases"])
    grid = grid_mod.build_grid(cases, _results_map(records))
    refusal = reporter._refusal_counts(records)
    clarification = reporter._clarify_counts(records)

    fresh = {
        g.gate_id: g
        for g in gates_mod.evaluate_gates(
            grid=grid,
            refusal=refusal,
            consistency=probe,
            clarification=clarification,
            tau_calibrated=False,
        )
    }
    local_g1 = {
        g.gate_id: g
        for g in gates_mod.evaluate_gates(p0_tests=LOCAL_P0, tau_calibrated=False)
    }["G-1"]
    fresh["G-1"] = local_g1

    official_by_id = {str(g["gate_id"]): g for g in official.get("gates") or []}
    official_meta = official.get("meta") or {}
    official_stamp = {
        "generated_at": official_meta.get("generated_at"),
        "git_rev": (official_meta.get("git") or {}).get("rev"),
        "git_dirty": (official_meta.get("git") or {}).get("dirty"),
    }

    rows: list[dict[str, Any]] = []
    for gate_id in ("G-1", "G-2", "G-3", "G-4", "G-5", "G-6", "G-7", "G-8"):
        computed = fresh[gate_id]
        stale = gate_id in _STALE_GATES
        row: dict[str, Any] = {
            "gate_id": gate_id,
            "condition": computed.condition,
            "fresh": not stale,
            "verdict": computed.verdict,
            "reading": computed.measured,
            "input": _input_source(gate_id, replay, probe, cases),
            "notes": list(computed.caveats or ()),
        }
        if gate_id in official_by_id:
            row["official_snapshot"] = {
                "verdict": official_by_id[gate_id].get("verdict"),
                "reading": official_by_id[gate_id].get("measured"),
                "stale": True,
                "stamp": official_stamp,
            }
        if stale and gate_id in official_by_id:
            #: 当期无输入 ⇒ 读数取官方快照（跨格对表用），并把「这是旧读数」钉在同一行。
            row["verdict"] = official_by_id[gate_id].get("verdict")
            row["reading"] = official_by_id[gate_id].get("measured")
            row["notes"] = [
                "本轮无当期输入 ⇒ 读数引用官方快照（"
                f"{official_stamp.get('git_rev')}），**已过期**；不得读成当期读数"
            ]
        rows.append(row)

    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in gates_mod.VERDICTS}

    payload = {
        **_bootstrap.build_stamp(),
        "task": "W75-3 当前门禁复算（零出站；**不是**官方快照）",
        "official_snapshot_untouched": _relative(OFFICIAL),
        "inputs": {
            "frozen_dataset": {
                "path": _relative(_bootstrap.DATASET_PATH),
                "content_hash": dataset.get("content_hash"),
                "n_cases": len(cases),
            },
            "replay": {
                "path": _relative(REPLAY),
                "git_rev": replay.get("git_rev"),
                "git_dirty": replay.get("git_dirty"),
                "generated_at": replay.get("generated_at"),
                "n_records": len(records),
            },
            "probe_g7": {
                "path": _relative(PROBE),
                "git_rev": probe.get("git_rev"),
                "git_dirty": probe.get("git_dirty"),
                "generated_at": probe.get("generated_at"),
                "system_consistent": probe.get("system_consistent"),
                "system_total": probe.get("system_total"),
                "system_consistent_rate": probe.get("system_consistent_rate"),
                "system_source": probe.get("system_source"),
                "dataset_caliber_consistency": probe.get("dataset_caliber_consistency"),
            },
            "local_p0": LOCAL_P0,
            "official_snapshot": {"path": _relative(OFFICIAL), **official_stamp},
        },
        "gate_summary": counts,
        "gates": rows,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {_relative(OUT)}")
    for row in rows:
        flag = "fresh" if row["fresh"] else "STALE"
        print(f"{row['gate_id']}  {row['verdict']:<14} [{flag}]  {row['reading']}")
    return 0


def _input_source(
    gate_id: str, replay: dict[str, Any], probe: dict[str, Any], cases: list[dict[str, Any]]
) -> str:
    stamp = f"{replay.get('git_rev')}/dirty={replay.get('git_dirty')}"
    return {
        "G-1": "本轮本地 pytest（unit+eval+contract）；集成层未跑 ⇒ 不构成 G-1 完整证据",
        "G-2": f"冻结集 {len(cases)} 条 × replay [{stamp}]",
        "G-3": "官方快照（88f3500）—— 红队矩阵本轮未重跑 ⇒ 过期",
        "G-4": "官方快照（88f3500）—— 双租户/RLS 本轮未重跑 ⇒ 过期",
        "G-5": f"冻结拒答集 × replay [{stamp}]",
        "G-6": "无机器可读压测回执 ⇒ NOT_AVAILABLE；官方快照的 UNVERIFIED 已过期",
        "G-7": f"probe_metric_values.json（system_source={probe.get('system_source')}）",
        "G-8": f"冻结澄清集 × replay [{stamp}]（--second-round 未开）",
    }[gate_id]


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
