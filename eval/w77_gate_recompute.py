"""W77-2：**当前门禁复算**（零出站材料；不是官方快照）。

与 `w75_gate_recompute.py` 的唯一区别是：把 W77-1 的 `applicability` 证据传给
`gates.evaluate_gates(tau_applicability=...)`，让 G-2/G-5/G-7 在
`n_records==166 ∧ l4_decisions==0 ∧ ambiguous_bindings==0` 成立时按实质读数输出 PASS，
并在 notes 强制标注 `tau_applicability=not_exercised`。

🔴 `backend/reports/w6/eval_metrics.json`（官方快照）**不刷新**（D-W77-5）。
本产物只回答"按今天的输入、加上 D-W77-1 的豁免，八格读什么"。

输入：
* **G-2/G-5/G-8**：`results_w77_full166_applicability.json`（W77-1 全量 replay）；
* **G-7**：`backend/reports/w6/probe_metric_values.json`（system vs 语义包权威值）；
* **G-1**：本轮本地 pytest（unit+eval+contract；集成层未跑）；
* **G-3/G-4/G-6**：官方快照旧判定，标 `stale`（不重算、不刷新）。

跑法（CommerceQL 根目录，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w77_gate_recompute.py
产物：`eval/results_w77_gate_recompute.json`
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

REPLAY = os.path.join(HERE, "results_w77_full166_applicability.json")
PROBE = os.path.join(ROOT, "backend", "reports", "w6", "probe_metric_values.json")
OFFICIAL = os.path.join(ROOT, "backend", "reports", "w6", "eval_metrics.json")
OUT = os.path.join(HERE, "results_w77_gate_recompute.json")

#: W77 本轮本地 P0 证据（unit + eval + contract；集成层因本机无 PG 未跑）。
LOCAL_P0 = {
    "passed": 2726,
    "failed": 0,
    "errors": 0,
    "integration_ran": False,
    "source": "W77 本轮 pytest backend/tests --ignore=backend/tests/integration -q ⇒ 2726 passed / 0 failed",
}

#: 本轮**没有当期输入**的格：只引用官方快照（`88f3500`），必须标 `stale`。
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


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def main() -> int:
    dataset = _load(_bootstrap.DATASET_PATH)
    replay = _load(REPLAY)
    probe = _load(PROBE)
    official = _load(OFFICIAL)
    applicability = replay.get("applicability") or {}
    evidence = {
        "n_records": applicability.get("n_records"),
        "l4_decisions": applicability.get("l4_decisions"),
        "ambiguous_bindings": applicability.get("ambiguous_bindings"),
    }
    applicability_holds = gates_mod.tau_applicability_holds(evidence)

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
            tau_applicability=evidence if applicability_holds else None,
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

    exempt = {"G-2", "G-5", "G-7"}
    rows: list[dict[str, Any]] = []
    for gate_id in ("G-1", "G-2", "G-3", "G-4", "G-5", "G-6", "G-7", "G-8"):
        computed = fresh[gate_id]
        stale = gate_id in _STALE_GATES
        tau_applicability = (
            "not_exercised"
            if applicability_holds and gate_id in exempt and computed.verdict == "PASS"
            else None
        )
        row: dict[str, Any] = {
            "gate_id": gate_id,
            "condition": computed.condition,
            "fresh": not stale,
            "verdict": computed.verdict,
            "reading": computed.measured,
            "input": _input_source(gate_id, replay, probe, cases),
            "notes": list(computed.caveats or ()),
            "tau_applicability": tau_applicability,
        }
        if gate_id == "G-8":
            row["tau_applicability"] = None
            row["notes"] = [
                *row["notes"],
                "G-8 **不适用** D-W77-1 的 τ 非适用豁免（澄清率/二轮成功率的判据点不在 L4 决策上）",
            ]
        if gate_id in official_by_id:
            row["official_snapshot"] = {
                "verdict": official_by_id[gate_id].get("verdict"),
                "reading": official_by_id[gate_id].get("measured"),
                "stale": True,
                "stamp": official_stamp,
            }
        if stale and gate_id in official_by_id:
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
        "task": "W77-2 当前门禁复算（零出站；D-W77-1 条件性 τ 非适用；**不是**官方快照）",
        "official_snapshot_untouched": _relative(OFFICIAL),
        "tau_applicability_evidence": {
            "source": _relative(REPLAY),
            "replay_git_rev": replay.get("git_rev"),
            "replay_git_dirty": replay.get("git_dirty"),
            "n_records": evidence["n_records"],
            "l4_decisions": evidence["l4_decisions"],
            "ambiguous_bindings": evidence["ambiguous_bindings"],
            "conditions": applicability.get("conditions"),
            "holds": applicability_holds,
            "wording": "tau_applicability=not_exercised（τ 未校准；本数据集不触发 L4 决策；"
                       "此标注不是 τ 校准证据）",
            "scope": "仅 G-2/G-5/G-7；G-8 不豁免",
        },
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
        "clarification_denominators": (
            {
                key: clarification.get(key)
                for key in (
                    "requests", "clarified", "clarify_expected_n", "second_round_attempted",
                    "second_round_success", "primary_denominator", "success_rate_attempted",
                    "success_rate_clarified", "clarified_denominator_verdict",
                )
            }
            if clarification else None
        ),
        "gate_summary": counts,
        "gates": rows,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {_relative(OUT)}")
    for row in rows:
        flag = "fresh" if row["fresh"] else "STALE"
        tau = f" tau={row['tau_applicability']}" if row.get("tau_applicability") else ""
        print(f"{row['gate_id']}  {row['verdict']:<14} [{flag}]  {row['reading']}{tau}")
    return 0


def _input_source(
    gate_id: str, replay: dict[str, Any], probe: dict[str, Any], cases: list[dict[str, Any]]
) -> str:
    stamp = f"{replay.get('git_rev')}/dirty={replay.get('git_dirty')}"
    return {
        "G-1": "本轮本地 pytest（unit+eval+contract）；集成层未跑 ⇒ 不构成 G-1 完整证据",
        "G-2": f"冻结集 {len(cases)} 条 × W77 replay [{stamp}]",
        "G-3": "官方快照 —— 红队矩阵本轮未重跑 ⇒ 过期",
        "G-4": "官方快照 —— 双租户/RLS 本轮未重跑 ⇒ 过期",
        "G-5": f"冻结拒答集 × W77 replay [{stamp}]",
        "G-6": "无机器可读压测回执 ⇒ NOT_AVAILABLE；官方快照的判定已过期",
        "G-7": f"probe_metric_values.json（system_source={probe.get('system_source')}）",
        "G-8": f"冻结澄清集 × W77 replay [{stamp}]（--second-round 未开）",
    }[gate_id]


if __name__ == "__main__":
    raise SystemExit(main())
