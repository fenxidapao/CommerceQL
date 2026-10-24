"""W78-4：**当前门禁复算**（零出站；不是官方快照）。

输入（逐格注明）：
* **G-1**：本轮离线 pytest（unit+eval+contract）＋ `results_w78_integration.json`
  （一次性 Docker 集成层；`integration_ran` 由 JUnit 推导）；
* **G-2/G-5**：`results_w77_full166_applicability.json`（W77-1 全量 replay）；
* **G-3**：`results_w78_redteam.json`（W78-3 刷新；仍 PARTIAL：2 条 COST 未覆盖）；
* **G-4**：集成层的 `test_rls_tenant_isolation.py` + `test_migration_0003_views.py`
  （`pg_rls_verified` 由两文件全绿推出，不手填）；
* **G-6**：无机器可读压测回执 ⇒ 引用官方快照旧判定并标 `stale`；
* **G-7**：`probe_metric_values.json`（system vs 语义包权威值）。其 `system_source` 仍是
  r75；本脚本逐条核对 **W77 replay 与 r75 的 SQL/params 166 条差异 = 0**，把等价性写进产物；
* **G-8**：W77 replay 的澄清计数；`attempted=0` ⇒ UNVERIFIED（门禁层已按 D-W78-2 双分母接线）；
* **τ 豁免**：复用 W77-1 证据；脚本自检 `2cd6c92..HEAD -- backend/app` 是否为空
  （D-W78-6：产品代码一变就必须重跑 166 replay）。

官方 `backend/reports/w6/eval_metrics.json` **不刷新**（D-W78-5）。
产物：`eval/results_w78_gate_recompute.json`
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402
import gates as gates_mod  # noqa: E402
import grid as grid_mod  # noqa: E402
import reporter  # noqa: E402

INTEGRATION = os.path.join(HERE, "results_w78_integration.json")
REDTEAM = os.path.join(HERE, "results_w78_redteam.json")
REPLAY = os.path.join(HERE, "results_w77_full166_applicability.json")
R75 = os.path.join(HERE, "results_r75_full166_window.json")
PROBE = os.path.join(ROOT, "backend", "reports", "w6", "probe_metric_values.json")
OFFICIAL = os.path.join(ROOT, "backend", "reports", "w6", "eval_metrics.json")
OUT = os.path.join(HERE, "results_w78_gate_recompute.json")

#: W78 本轮离线 P0 读数（unit+eval+contract + 其余 offline；集成层由 JUnit 另计）。
LOCAL_P0 = {
    "passed": 2731,
    "failed": 0,
    "errors": 0,
    "source": "W78 本轮 pytest backend/tests --ignore=backend/tests/integration -q",
}

#: W77-1 证据的生产 rev（D-W78-6 的比对基线）。
W77_REV = "2cd6c92"

#: 本轮无当期输入的格：引用官方快照并标 stale。
_STALE_GATES = ("G-6",)


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _results_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(r.get("case_id")): {
            "scored": bool(r.get("scored")),
            "passed": bool((r.get("verdict") or {}).get("equivalent")),
            "category": str((r.get("attribution") or {}).get("category") or ""),
        }
        for r in records
    }


def _sql_params_equivalence(
    records: list[dict[str, Any]], r75_records: list[dict[str, Any]]
) -> dict[str, Any]:
    old = {str(r.get("case_id")): r for r in r75_records}
    differences: list[str] = []
    for record in records:
        case_id = str(record.get("case_id"))
        prev = old.get(case_id)
        if prev is None:
            differences.append(case_id)
            continue
        if (
            str(record.get("sql_text") or "") != str(prev.get("sql_text") or "")
            or dict(record.get("sql_params") or {}) != dict(prev.get("sql_params") or {})
        ):
            differences.append(case_id)
    return {
        "n_compared": len(records),
        "differences": differences,
        "identical": not differences,
    }


def _product_code_changes() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{W77_REV}..HEAD", "--", "backend/app"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff 失败：{result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    dataset = _load(_bootstrap.DATASET_PATH)
    replay = _load(REPLAY)
    r75 = _load(R75)
    integration = _load(INTEGRATION)
    redteam = _load(REDTEAM)
    probe = _load(PROBE)
    official = _load(OFFICIAL)

    records = list(replay.get("records") or [])
    cases = list(dataset.get("cases") or [])
    applicability = replay.get("applicability") or {}
    evidence = {
        "n_records": applicability.get("n_records"),
        "l4_decisions": applicability.get("l4_decisions"),
        "ambiguous_bindings": applicability.get("ambiguous_bindings"),
    }
    app_changes = _product_code_changes()
    replay_required = bool(app_changes)
    applicability_holds = (
        gates_mod.tau_applicability_holds(evidence) and not replay_required
    )

    int_run = integration.get("g1_evidence") or {}
    g4 = integration.get("g4_evidence") or {}
    p0_tests = {
        "passed": int(LOCAL_P0["passed"]) + int(int_run.get("passed") or 0),
        "passed_offline": LOCAL_P0["passed"],
        "passed_integration": int_run.get("passed"),
        "failed": int(int_run.get("failed") or 0),
        "errors": int(int_run.get("errors") or 0),
        "failed_tests": [
            t for f in (integration.get("files") or {}).values() for t in f.get("failed_tests") or []
        ],
        "error_tests": [
            t for f in (integration.get("files") or {}).values() for t in f.get("error_tests") or []
        ],
        "integration_ran": bool(int_run.get("integration_ran")),
        "source": "离线 pytest + JUnit 集成层（一次性 Docker；端口/库名见 results_w78_integration.json）",
        "pg_surface": {
            "integration_named": "backend/tests/integration（JUnit 逐文件计数见产物）",
            "databases_denied": [],
            "ddl_targets": [],
            "conn_params": "127.0.0.1:55432/ecom_rls（一次性；口令不落盘）",
        },
    }
    cross_tenant = None
    if int_run.get("integration_ran"):
        cross_tenant = {
            "leaked": int(g4.get("leaked") or 0) if g4.get("pg_rls_verified") else None,
            "pg_rls_verified": bool(g4.get("pg_rls_verified")),
            "notes": [
                f"来源：{_relative(INTEGRATION)}（rev={integration.get('git_rev')}/"
                f"dirty={integration.get('git_dirty')}）",
                *[str(x) for x in (g4.get("basis") or [])],
            ],
        }
        if cross_tenant["leaked"] is None:
            cross_tenant = None  # 未取证 ⇒ NOT_AVAILABLE，不编 0

    grid = grid_mod.build_grid(cases, _results_map(records))
    refusal = reporter._refusal_counts(records)
    clarification = reporter._clarify_counts(records)
    fresh = {
        g.gate_id: g
        for g in gates_mod.evaluate_gates(
            grid=grid,
            p0_tests=p0_tests,
            red_team=redteam,
            cross_tenant=cross_tenant,
            refusal=refusal,
            consistency=probe,
            clarification=clarification,
            tau_calibrated=False,
            tau_applicability=evidence if applicability_holds else None,
        )
    }

    official_by_id = {str(g["gate_id"]): g for g in official.get("gates") or []}
    official_meta = official.get("meta") or {}
    official_stamp = {
        "generated_at": official_meta.get("generated_at"),
        "git_rev": (official_meta.get("git") or {}).get("rev"),
        "git_dirty": (official_meta.get("git") or {}).get("dirty"),
    }
    g7_equiv = _sql_params_equivalence(records, list(r75.get("records") or []))
    g8_dual = (
        {
            key: clarification.get(key)
            for key in (
                "requests", "clarified", "clarify_expected_n", "second_round_attempted",
                "second_round_success", "primary_denominator", "success_rate_attempted",
                "success_rate_clarified", "clarified_denominator_verdict",
            )
        }
        if clarification else None
    )

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
            "input": _input_source(gate_id, integration, redteam, replay, probe, cases),
            "notes": list(computed.caveats or ()),
            "tau_applicability": tau_applicability,
        }
        if gate_id == "G-7":
            row["g7_equivalence"] = g7_equiv
            row["notes"] = [
                *row["notes"],
                f"G-7 输入仍是 `{_relative(PROBE)}`（system_source="
                f"{(probe.get('system_source') or {}).get('git_rev')}）；"
                f"W77 replay 与 r75 的 SQL/params {g7_equiv['n_compared']} 条差异 "
                f"{len(g7_equiv['differences'])} ⇒ 读数可转移",
            ]
        if gate_id == "G-8":
            row["tau_applicability"] = None
            row["clarification_denominators"] = g8_dual
            attempted = int((g8_dual or {}).get("second_round_attempted") or 0)
            clarified_n = int((g8_dual or {}).get("clarified") or 0)
            succeeded = int((g8_dual or {}).get("second_round_success") or 0)
            primary = (
                "不存在（attempted=0，**不是 0%**）"
                if attempted == 0 else f"{succeeded}/{attempted}"
            )
            row["notes"] = [
                *row["notes"],
                f"D-W78-2 双分母：主读数 success/attempted = {primary}；"
                f"并列 success/clarified = {succeeded}/{clarified_n} ⇒ "
                f"{g8_dual.get('clarified_denominator_verdict') if g8_dual else None}"
                "（attempted<clarified 时分母未覆盖，不得读成低成功率）",
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
        "task": "W78-4 当前门禁复算（零出站；一次性 Docker 集成层；**不是**官方快照）",
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
            "product_code_changes_since_2cd6c92": app_changes,
            "replay_required": replay_required,
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
            "integration": {
                "path": _relative(INTEGRATION),
                "git_rev": integration.get("git_rev"),
                "git_dirty": integration.get("git_dirty"),
                "junit": integration.get("junit"),
                "containers": (integration.get("docker") or {}).get("containers"),
                "dsn_masked": (integration.get("dsn_masked") or {}),
                "g1_evidence": int_run,
                "g4_evidence": g4,
            },
            "redteam": {
                "path": _relative(REDTEAM),
                "git_rev": redteam.get("git_rev"),
                "git_dirty": redteam.get("git_dirty"),
                "total": redteam.get("total"),
                "leaked": redteam.get("leaked"),
                "checked": redteam.get("checked"),
                "expect_block": redteam.get("expect_block"),
                "not_covered_cases": redteam.get("not_covered_cases"),
            },
            "probe_g7": {
                "path": _relative(PROBE),
                "git_rev": probe.get("git_rev"),
                "git_dirty": probe.get("git_dirty"),
                "system_consistent": probe.get("system_consistent"),
                "system_total": probe.get("system_total"),
                "system_source": probe.get("system_source"),
                "equivalence_w77_vs_r75": g7_equiv,
            },
            "local_p0": LOCAL_P0,
            "official_snapshot": {"path": _relative(OFFICIAL), **official_stamp},
        },
        "clarification_denominators": g8_dual,
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
    print(f"summary={counts}")
    if replay_required:
        print("🔴 backend/app 有改动 ⇒ 必须重跑 166 replay 并重导 τ 证据；本次未给豁免。")
        return 3
    return 0


def _input_source(
    gate_id: str,
    integration: Mapping[str, Any],
    redteam: Mapping[str, Any],
    replay: Mapping[str, Any],
    probe: Mapping[str, Any],
    cases: list[dict[str, Any]],
) -> str:
    stamp = f"{replay.get('git_rev')}/dirty={replay.get('git_dirty')}"
    return {
        "G-1": "本轮离线 pytest + 一次性 Docker 集成层 JUnit（integration_ran 由证据推导）",
        "G-2": f"冻结集 {len(cases)} 条 × W77 replay [{stamp}]",
        "G-3": f"W78-3 红队刷新（{_relative(REDTEAM)}；rev={redteam.get('git_rev')}/"
               f"dirty={redteam.get('git_dirty')}）",
        "G-4": f"一次性 Docker 集成层（{_relative(INTEGRATION)}；RLS 行为 + 策略对象两文件全绿）",
        "G-5": f"冻结拒答集 × W77 replay [{stamp}]",
        "G-6": "无机器可读压测回执 ⇒ NOT_AVAILABLE；官方快照的判定已过期",
        "G-7": f"probe_metric_values.json（system_source={probe.get('system_source')}）"
               "；W77 vs r75 SQL/params 等价性逐条核对",
        "G-8": f"冻结澄清集 × W77 replay [{stamp}]（--second-round 未开）",
    }[gate_id]


if __name__ == "__main__":
    raise SystemExit(main())
