"""W80-1：最终门禁证据链审计（零出站；**不是**官方快照）。

把八格判定压成**一条可复核的链**：同一 HEAD 上重跑离线 pytest、红队、门禁复算，
逐格写 verdict／evidence path／git_rev／dirty／fresh／复算命令／"什么会改变这个判定"。

关键边界：
* 集成层**不重跑**（本轮不启动容器）⇒ 复用 W78 `results_w78_integration.json` 的
  124/0/0；复用依据由本脚本现算 `e7fc769..HEAD -- backend/app backend/tests/integration`
  的 diff 是否为空，不手填。
* G-2/G-5/G-7/G-8 用 W77 全量 replay 复算（零 LLM）⇒ `fresh=true` 指"本轮重新计算"，
  不是"重新调用模型"；产物里把 replay 的 rev/dirty 一并列出。
* G-6 无当期输入 ⇒ `fresh=false`，读数仍引用官方快照 `88f3500`（已过期）。
* 六格 PASS 与 W79 逐格比对（verdict ＋ reading 全等）；不一致照实写并**非零退出**，
  不改判据/阈值去凑。

产物：`eval/results_w80_final_audit.json`
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

JUNIT = os.path.join(HERE, "results_w80_offline_pytest.junit.xml")
RECOMPUTE = os.path.join(HERE, "results_w80_gate_recompute.json")
REDTEAM = os.path.join(HERE, "results_w80_redteam.json")
TAIL = os.path.join(HERE, "results_w80_redteam_tail.json")
INTEGRATION = os.path.join(HERE, "results_w78_integration.json")
W79 = os.path.join(HERE, "results_w79_gate_recompute.json")
REPLAY = os.path.join(HERE, "results_w77_full166_applicability.json")
PROBE = os.path.join(ROOT, "backend", "reports", "w6", "probe_metric_values.json")
OFFICIAL = os.path.join(ROOT, "backend", "reports", "w6", "eval_metrics.json")
OUT = os.path.join(HERE, "results_w80_final_audit.json")

OFFLINE_CMD = (
    "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -X utf8 -m pytest backend/tests "
    "--ignore=backend/tests/integration -q "
    "--junitxml=eval/results_w80_offline_pytest.junit.xml"
)
REDTEAM_CMD = (
    "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/redteam_eval.py "
    "--out eval/results_w80_redteam.json"
)
RECOMPUTE_CMD = "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w80_gate_recompute.py"
AUDIT_CMD = "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w80_final_audit.py"
TAIL_CMD = "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w80_redteam_tail.py"

SIX_PASS = ("G-1", "G-2", "G-3", "G-4", "G-5", "G-7")
TWO_UNVERIFIED = ("G-6", "G-8")

FRESH = {
    "G-1": True, "G-2": True, "G-3": True, "G-4": True,
    "G-5": True, "G-6": False, "G-7": True, "G-8": True,
}

FRESHNESS = {
    "G-1": "本轮离线 pytest 重跑（计数从 JUnit 读）；集成层复用 W78 e7fc769（本轮不启动容器）",
    "G-2": "本轮用 W77 全量 replay 复算（未重新调用 LLM；backend/app 自 2cd6c92 空 diff）",
    "G-3": "本轮红队 66 条重跑（零 LLM）",
    "G-4": "本轮复算；RLS 证据复用 W78 集成层（e7fc769；本轮不启动容器）",
    "G-5": "本轮用 W77 全量 replay 复算（未重新调用 LLM；backend/app 自 2cd6c92 空 diff）",
    "G-6": "无当期输入；读数引用官方快照 88f3500，已过期",
    "G-7": "本轮用 probe(5bdb663) + W77 replay 复算；SQL/params 166 条差异 0 ⇒ 读数可转移",
    "G-8": "本轮用 W77 replay 复算（--second-round 未开；attempted=0）",
}

WHAT_WOULD_CHANGE = {
    "G-1": "任一 P0 用例失败/报错（离线或集成）⇒ 红>0；或集成证据被判无效（integration_ran=false）⇒ NOT_AVAILABLE。集成层若在 e7fc769 之后改了 backend/app 或 integration 测试，必须重跑 124 条，不能复用。",
    "G-2": "easy×low 格 <95%；或 τ 校准后 L4 在该格真的做决策（不再是条件性非适用）；或 backend/app 自 2cd6c92 有改动 ⇒ 必须重跑 166 条 replay。",
    "G-3": "任一应拦用例 leaked（三道闸门无一拒绝）；或红队集/闸门代码变更。成本闸门另行需要 gate3 可执行（沙箱 EXPLAIN 恒 None）才能测，当前 `cost_gate_tripped` 仍是 NOT_CHECKED。",
    "G-4": "跨租户行 >0；或 RLS 证据失效（PG 集成两文件非全绿 / 产品代码改了 RLS 派生）；沙箱 SQLite TEMP VIEW 不能替代真实 PG RLS。",
    "G-5": "该拒 <24/24 或误拒 >5%（当前 3/124 = 2.4%，距阈值只剩 4 条）；或 backend/app 自 2cd6c92 有改动 ⇒ 必须重跑 replay。",
    "G-6": "拿到满档 50 并发×10min、全请求分母（429 单列）、≥20 准入样本的 live 压测回执，且同 rev/dirty=false；否则永远 UNVERIFIED——不得拿历史 p95 判 PASS 或 FAIL。",
    "G-7": "一致 <13/13；或 probe 的 system_source 与当期代码不再等价（W77 vs r75 SQL/params 出现差异）；外部 BI 权威值缺失仍是判据限制。",
    "G-8": "18 条澄清集有补答来源并真跑二轮（attempted>0），且澄清率 ≤15%、二轮回到可执行终态 ≥80%；否则永远 UNVERIFIED，attempted=0 不等于 0%。",
}

EVIDENCE = {
    "G-1": [JUNIT, INTEGRATION, RECOMPUTE],
    "G-2": [REPLAY, RECOMPUTE],
    "G-3": [REDTEAM, RECOMPUTE, TAIL],
    "G-4": [INTEGRATION, RECOMPUTE],
    "G-5": [REPLAY, RECOMPUTE],
    "G-6": [OFFICIAL, RECOMPUTE],
    "G-7": [PROBE, REPLAY, RECOMPUTE],
    "G-8": [REPLAY, RECOMPUTE],
}

COMMANDS = {
    "G-1": f"{OFFLINE_CMD} && {RECOMPUTE_CMD}",
    "G-2": RECOMPUTE_CMD,
    "G-3": f"{REDTEAM_CMD} && {RECOMPUTE_CMD}",
    "G-4": RECOMPUTE_CMD,
    "G-5": RECOMPUTE_CMD,
    "G-6": RECOMPUTE_CMD,
    "G-7": RECOMPUTE_CMD,
    "G-8": RECOMPUTE_CMD,
}


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout.strip()


def _junit_counts(path: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    failed_tests: list[str] = []
    error_tests: list[str] = []
    for suite in suites:
        for key in total:
            total[key] += int(suite.get(key) or 0)
        for case in suite.findall("testcase"):
            node_id = f"{case.get('classname')}::{case.get('name')}"
            if case.find("failure") is not None:
                failed_tests.append(node_id)
            if case.find("error") is not None:
                error_tests.append(node_id)
    failed = total["failures"] + total["errors"]
    return {
        **_relative_path_and_sha(path),
        **total,
        "passed": total["tests"] - failed - total["skipped"],
        "failed_tests": failed_tests,
        "error_tests": error_tests,
    }


def _relative_path_and_sha(path: str) -> dict[str, Any]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _stamp(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "git_rev": artifact.get("git_rev"),
        "git_dirty": artifact.get("git_dirty"),
        "generated_at": artifact.get("generated_at"),
    }


def main() -> int:
    stamp = _bootstrap.build_stamp()
    recompute = _load(RECOMPUTE)
    redteam = _load(REDTEAM)
    integration = _load(INTEGRATION)
    w79 = _load(W79)
    replay = _load(REPLAY)
    probe = _load(PROBE)
    official = _load(OFFICIAL)
    tail = _load(TAIL) if os.path.isfile(TAIL) else {}
    offline = _junit_counts(JUNIT)

    int_g1 = integration.get("g1_evidence") or {}
    int_g4 = integration.get("g4_evidence") or {}
    official_meta = official.get("meta") or {}
    official_git = official_meta.get("git") or {}
    official_counts = (official.get("gate_summary") or {}).get("counts") or {}
    replay_stamp = _stamp(replay)
    redteam_stamp = _stamp(redteam)
    integration_stamp = _stamp(integration)
    probe_stamp = _stamp(probe)
    recompute_stamp = _stamp(recompute)

    reuse_diff = _git(
        "diff", "--name-only", f"{integration.get('git_rev')}..HEAD",
        "--", "backend/app", "backend/tests/integration",
    )
    official_diff = _git(
        "diff", "--name-only", f"{integration.get('git_rev')}..HEAD",
        "--", _relative(OFFICIAL),
    )

    rows: list[dict[str, Any]] = []
    w79_by = {str(g["gate_id"]): g for g in w79.get("gates") or []}
    for gate in recompute.get("gates") or []:
        gate_id = str(gate["gate_id"])
        previous = w79_by.get(gate_id) or {}
        row: dict[str, Any] = {
            "gate_id": gate_id,
            "condition": gate.get("condition"),
            "verdict": gate.get("verdict"),
            "reading": gate.get("reading"),
            "evidence_paths": [_relative(p) for p in EVIDENCE[gate_id]],
            "git_rev": {
                "G-1": stamp.get("git_rev"),
                "G-2": replay_stamp.get("git_rev"),
                "G-3": redteam_stamp.get("git_rev"),
                "G-4": integration_stamp.get("git_rev"),
                "G-5": replay_stamp.get("git_rev"),
                "G-6": official_git.get("rev"),
                "G-7": probe_stamp.get("git_rev"),
                "G-8": replay_stamp.get("git_rev"),
            }[gate_id],
            "git_dirty": {
                "G-1": stamp.get("git_dirty"),
                "G-2": replay_stamp.get("git_dirty"),
                "G-3": redteam_stamp.get("git_dirty"),
                "G-4": integration_stamp.get("git_dirty"),
                "G-5": replay_stamp.get("git_dirty"),
                "G-6": official_git.get("dirty"),
                "G-7": probe_stamp.get("git_dirty"),
                "G-8": replay_stamp.get("git_dirty"),
            }[gate_id],
            "recompute_git_rev": recompute_stamp.get("git_rev"),
            "recompute_git_dirty": recompute_stamp.get("git_dirty"),
            "fresh": FRESH[gate_id],
            "freshness": FRESHNESS[gate_id],
            "recompute_command": COMMANDS[gate_id],
            "what_would_change": WHAT_WOULD_CHANGE[gate_id],
            "w79_verdict": previous.get("verdict"),
            "w79_reading": previous.get("reading"),
            "matches_w79": (
                gate.get("verdict") == previous.get("verdict")
                and gate.get("reading") == previous.get("reading")
            ),
            "tau_applicability": gate.get("tau_applicability"),
        }
        if gate_id == "G-3":
            row["g3_scope"] = gate.get("g3_scope")
        if gate_id == "G-7":
            row["g7_equivalence"] = gate.get("g7_equivalence")
        if gate_id == "G-8":
            row["clarification_denominators"] = gate.get("clarification_denominators")
        rows.append(row)

    checks = {
        "tree_clean_at_audit": stamp.get("git_dirty") is False,
        "offline_2736_0_0": (
            offline["tests"] == 2736 and offline["failed"] == 0 and offline["errors"] == 0
        ),
        "offline_matches_recompute": all(
            (recompute.get("inputs") or {}).get("local_p0", {}).get(key) == offline[key]
            for key in ("passed", "failed", "errors", "skipped")
        ),
        "integration_124_0_0": (
            int_g1.get("passed") == 124
            and int_g1.get("failed") == 0
            and int_g1.get("errors") == 0
            and int_g1.get("skipped") == 0
            and bool(int_g1.get("integration_ran"))
        ),
        "integration_reuse_basis_empty": not reuse_diff,
        "redteam_checked_50_leaked_0": (
            redteam.get("checked") == 50
            and redteam.get("expect_block") == 50
            and redteam.get("leaked") == 0
            and not redteam.get("not_covered_cases")
        ),
        "redteam_failures_21": int((redteam.get("assertion_counts") or {}).get("FAIL") or 0) == 21,
        "redteam_tail_21_10": (
            tail.get("n_failures") == 21 and tail.get("n_cases") == 10
        ),
        "six_pass_match_w79": all(
            next(r for r in rows if r["gate_id"] == gate_id)["matches_w79"]
            and next(r for r in rows if r["gate_id"] == gate_id)["verdict"] == "PASS"
            for gate_id in SIX_PASS
        ),
        "two_unverified_match_w79": all(
            next(r for r in rows if r["gate_id"] == gate_id)["matches_w79"]
            and next(r for r in rows if r["gate_id"] == gate_id)["verdict"] == "UNVERIFIED"
            for gate_id in TWO_UNVERIFIED
        ),
        "official_snapshot_still_88f3500_pass1of8": (
            official_git.get("rev") == "88f3500"
            and official_git.get("dirty") is False
            and official_counts.get("PASS") == 1
            and official_counts.get("FAIL") == 3
            and official_counts.get("PARTIAL") == 2
            and official_counts.get("UNVERIFIED") == 2
        ),
        "official_snapshot_not_rewritten": not official_diff,
        "g4_pg_rls_verified": bool(int_g4.get("pg_rls_verified")),
        "no_llm_calls": True,
        "no_containers_started": True,
    }
    all_checks_pass = all(checks.values())

    payload: dict[str, Any] = {
        **stamp,
        "task": "W80-1 最终门禁证据链审计（零出站；同一 HEAD 重跑；**不是**官方快照）",
        "tokens": 0,
        "no_llm_calls": True,
        "no_containers_started": True,
        "commands": {
            "offline_pytest": OFFLINE_CMD,
            "redteam": REDTEAM_CMD,
            "gate_recompute": RECOMPUTE_CMD,
            "redteam_tail": TAIL_CMD,
            "final_audit": AUDIT_CMD,
        },
        "offline_pytest": {
            **offline,
            "command": OFFLINE_CMD,
            "scope": "backend/tests --ignore=backend/tests/integration（五目录：unit/contract/eval/redteam/graph_snapshot）",
        },
        "integration_reuse": {
            **_relative_path_and_sha(INTEGRATION),
            **integration_stamp,
            "passed": int_g1.get("passed"),
            "failed": int_g1.get("failed"),
            "errors": int_g1.get("errors"),
            "skipped": int_g1.get("skipped"),
            "integration_ran": int_g1.get("integration_ran"),
            "reuse_basis": {
                "command": (
                    f"git diff --name-only {integration.get('git_rev')}..HEAD -- "
                    "backend/app backend/tests/integration"
                ),
                "diff_empty": not reuse_diff,
                "product_code_changes_since_2cd6c92": _git(
                    "diff", "--name-only", "2cd6c92..HEAD", "--", "backend/app"
                ).splitlines(),
                "rerun": False,
                "why": "W80 不启动容器；产品代码与集成测试自 e7fc769 空 diff ⇒ 124/0/0 可作为同一 HEAD 的集成输入",
            },
            "g4_evidence": {
                "pg_rls_verified": int_g4.get("pg_rls_verified"),
                "leaked": int_g4.get("leaked"),
                "basis": int_g4.get("basis"),
            },
        },
        "redteam": {
            **_relative_path_and_sha(REDTEAM),
            **redteam_stamp,
            "total": redteam.get("total"),
            "expect_block": redteam.get("expect_block"),
            "checked": redteam.get("checked"),
            "leaked": redteam.get("leaked"),
            "not_covered_cases": redteam.get("not_covered_cases"),
            "assertion_counts": redteam.get("assertion_counts"),
            "g3_scope": redteam.get("g3_scope"),
        },
        "redteam_tail": {
            **(
                _relative_path_and_sha(TAIL)
                if os.path.isfile(TAIL)
                else {"path": _relative(TAIL)}
            ),
            **(_stamp(tail) if tail else {}),
            "n_failures": tail.get("n_failures"),
            "n_cases": tail.get("n_cases"),
            "buckets": tail.get("buckets"),
        },
        "comparison_w79": {
            **_relative_path_and_sha(W79),
            **_stamp(w79),
            "six_pass_match": checks["six_pass_match_w79"],
            "two_unverified_match": checks["two_unverified_match_w79"],
            "cells": [
                {
                    "gate_id": row["gate_id"],
                    "w79_verdict": row["w79_verdict"],
                    "w80_verdict": row["verdict"],
                    "reading_identical": row["matches_w79"],
                }
                for row in rows
            ],
        },
        "gate_summary": recompute.get("gate_summary"),
        "gates": rows,
        "official_snapshot": {
            **_relative_path_and_sha(OFFICIAL),
            "git_rev": official_git.get("rev"),
            "git_dirty": official_git.get("dirty"),
            "generated_at": official_meta.get("generated_at"),
            "counts": official_counts,
            "last_commit_touching_file": _git(
                "log", "-1", "--format=%h", "--", _relative(OFFICIAL)
            ),
            "refreshed_this_round": False,
            "diff_since_integration_rev": official_diff.splitlines(),
        },
        "tau_line": "L4 决策份额 0/166；τ 未校准（条件性非适用，不是校准证据）",
        "g3_line": "G-3 的成本闸门未测；21 条非 G-3 红队断言失败仍在",
        "disclosures": [
            "当期复算 6 PASS／2 UNVERIFIED（需预算/业务输入的阻塞项）",
            "L4 决策份额 0/166；τ 未校准（条件性非适用，不是校准证据）",
            "G-3 的成本闸门未测；21 条非 G-3 红队断言失败仍在",
            "官方快照仍 88f3500／PASS 1/8，未刷新",
        ],
        "checks": checks,
        "all_checks_pass": all_checks_pass,
    }

    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"written: {_relative(OUT)}")
    for row in rows:
        flag = "fresh" if row["fresh"] else "STALE"
        match = "=" if row["matches_w79"] else "≠"
        print(f"{row['gate_id']}  {row['verdict']:<12} [{flag}] {match} W79  {row['reading']}")
    print(f"checks={checks}")
    print(f"all_checks_pass={all_checks_pass}")
    return 0 if all_checks_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
