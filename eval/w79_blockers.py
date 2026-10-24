"""W79-4：G-6 / G-8 阻塞备忘（零出站；只出成本与数据需求，不跑）。

D-W79-4：G-6 满档需要 live LLM（W7 估 ¥40+）；G-8 需要 17/18 条的补答源。
本脚本不调模型、不跑压测、不实装二轮，只把"要花多少钱 / 能测到什么 / 缺哪些数据"落盘。

产物：`eval/results_w79_blockers.json`
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

GAP = os.path.join(HERE, "results_w77_g8_answer_gap.json")
OUT = os.path.join(HERE, "results_w79_blockers.json")


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def main() -> int:
    gap = _load(GAP)
    missing_rows = [
        row for row in (gap.get("expected_clarify") or {}).get("rows") or []
        if not row.get("has_frozen_candidate")
    ]
    misclarified = list((gap.get("misclarified") or {}).get("rows") or [])

    payload = {
        **_bootstrap.build_stamp(),
        "task": "W79-4 G-6/G-8 阻塞备忘（零出站；不跑）",
        "g6": {
            "status": "UNVERIFIED",
            "not_run": True,
            "why": "满档压测需要 live LLM；无新预算授权（D-W79-4）",
            "scenario": "50 并发 × 10min（§16.5 满档）",
            "cost_estimate_cny": "¥40+（W7 估；派单 §100.6 D-W79-4 引用）",
            "cost_source": "TASK_BOARD §100.6 D-W79-4；W7 历史压测记录",
            "historical_quota_reading": {
                "scenario": "steady c=50/n=120",
                "p50_ms": 5474.4,
                "p95_ms": 11381.8,
                "max_ms": 14289.8,
                "threshold_ms": 8000,
                "exceeds_threshold": True,
                "source": "backend/reports/w7/DELIVERY.md:149",
                "caveat": (
                    "该轮本机 Ollama 未运行 ⇒ 检索 100% sparse_only、ok 率 2/79；"
                    "容量读数被污染，只能当参照，不能当 G-6 判定"
                ),
            },
            "what_it_would_measure": "满档并发下的端到端 P95（含被 429 挡在分母外的请求需单列）",
            "possible_conclusions": [
                "P95 ≤ 8s 且回执带全请求分母 ⇒ 可判 PASS",
                "P95 > 8s ⇒ FAIL（不得因环境噪声改判）",
                "回执缺全请求分母/带 g6_caveat ⇒ UNVERIFIED，不得宣布通过",
            ],
            "prerequisites": [
                "live LLM 预算（¥40+）",
                "Ollama 可用（否则检索退化污染读数）",
                "10 个同租户令牌 + 50 并发压测环境",
            ],
        },
        "g8": {
            "status": "UNVERIFIED",
            "not_run": True,
            "why": "17/18 条 expected=clarify 没有补答来源；编答案 = 造数据（D-W79-4）",
            "source": _relative(GAP),
            "source_git_rev": gap.get("git_rev"),
            "source_git_dirty": gap.get("git_dirty"),
            "n_expected_clarify": (gap.get("expected_clarify") or {}).get("n"),
            "n_with_frozen_candidate": (gap.get("expected_clarify") or {}).get("n_with_frozen_candidate"),
            "n_missing_answer_source": len(missing_rows),
            "missing_answer_sources": [
                {
                    "case_id": row.get("case_id"),
                    "question": row.get("question"),
                    "reason": row.get("reason"),
                    "missing": row.get("missing_answer"),
                }
                for row in missing_rows
            ],
            "misclarified_policy": {
                "n": len(misclarified),
                "policy": "不给补答（题面本应 execute；补答会掩盖绑定缺陷）",
                "case_ids": [row.get("case_id") for row in misclarified],
            },
            "needs_business_input": True,
            "what_it_would_measure": (
                "二轮回到可执行终态（complete）的比例；主分母 = attempted，"
                "attempted<clarified 时并列 success/clarified 判 UNVERIFIED"
            ),
            "do_not_run_until": "业务为 17 条补齐口径（外部补答源），且不把 9 条误澄清算进去",
        },
        "no_llm_calls": True,
        "no_second_round_run": True,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {_relative(OUT)}")
    print(
        f"g6=UNVERIFIED not_run=true; g8=UNVERIFIED missing={len(missing_rows)} "
        f"misclarified={len(misclarified)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
