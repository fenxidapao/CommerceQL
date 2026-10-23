"""W75-4：两项成本估算（**只出材料，零出站**；派单 §96.8）。

(a) τ 校准采样：现缺哪些 schema、n≥3 需要多少次调用、token/¥ 估算、建议硬上限；
(b) 维度 C1+A：要重录多少请求、token/¥ 估算、预期翻转。

所有费用都是**代理量**：取最近一次全量重放（`results_r75_full166_window.json`）
里记录的真实计费（`cost_cny` / `tokens`，来自录制批次的同模型同 prompt）。
重放本身零成本；真打按同一 token 结构计费，另留 30% 波动余量。

跑法（CommerceQL 根目录，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w75_cost_estimates.py
产物：`eval/results_r75_cost_estimates.json`
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

REPLAY = os.path.join(HERE, "results_r75_full166_window.json")
DIMENSIONS = os.path.join(HERE, "results_r74_dimension_dispositions.json")
CASSETTE = os.path.join(HERE, "cassettes", "w8_r63_full166.jsonl")
OUT = os.path.join(HERE, "results_r75_cost_estimates.json")

#: 估算余量：真打有重试/温度抖动，录制批次不含这些额外调用。
MARGIN = 1.3


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _tokens(record: dict[str, Any]) -> int:
    value = record.get("tokens") or {}
    return int(value.get("total") or 0) if isinstance(value, dict) else int(value)


def _cost(record: dict[str, Any]) -> float:
    return float(record.get("cost_cny") or 0.0)


def main() -> int:
    replay = _load(REPLAY)
    dims = _load(DIMENSIONS)
    records = list(replay["records"])
    n_calls = sum(1 for _ in open(CASSETTE, encoding="utf-8"))

    scorable = [
        r
        for r in records
        if (r.get("tau_raw") or {}).get("ok")
        and str((r.get("tau_raw") or {}).get("gold_status")) == "matched"
    ]
    scored_l4 = [r for r in records if (r.get("tau_raw") or {}).get("ok")]
    full = {
        "requests": len(records),
        "calls": n_calls,
        "tokens": sum(_tokens(r) for r in records),
        "cost_cny": round(sum(_cost(r) for r in records), 6),
    }
    subset = {
        "requests": len(scorable),
        "calls_est": round(n_calls * len(scorable) / len(records)),
        "tokens": sum(_tokens(r) for r in scorable),
        "cost_cny": round(sum(_cost(r) for r in scorable), 6),
    }
    city_ids = [c["case_id"] for c in dims["dimensions"]["city_cases"]]
    city = [r for r in records if r["case_id"] in city_ids]
    city_cost = {
        "requests": len(city),
        "calls_est": round(n_calls * len(city) / len(records)),
        "tokens": sum(_tokens(r) for r in city),
        "cost_cny": round(sum(_cost(r) for r in city), 6),
        "case_ids": city_ids,
    }

    payload = {
        **_bootstrap.build_stamp(),
        "task": "W75-4 两项成本估算（零出站材料；未执行任何真打）",
        "basis": {
            "replay": {
                "path": "eval/results_r75_full166_window.json",
                "git_rev": replay.get("git_rev"),
                "git_dirty": replay.get("git_dirty"),
            },
            "margin": MARGIN,
            "note": "费用 = 录制批次的同模型同 prompt 计费（代理量）；重放不产生新调用",
        },
        "tau": {
            "schema_in_place": {
                "version": "W8_TAU_RAW/v1",
                "fields": [
                    "candidate_ids（稳定键 `资产.列`）",
                    "rank（按分数降序的 id 序列，断平稳定）",
                    "scores（与 candidate_ids 等长）",
                    "scorer{model_id,prompt_version}",
                    "gold_status / gold_candidate_id / gold_unmatched_reason",
                ],
                "deriver": "eval/tau_samples.py（按 case_id 分组，n≥3 才成样本）",
            },
            "gaps": [
                "① **校准集/验收集分离**：`ScoreSample` 与 `calibrate(holdout_separated=…)` "
                "只接受一个**声明**布尔；采样数据里没有 case 级 `split` 字段 ⇒ 目前无法"
                "证明「分离」是真的（§C.4.6 约束 2）。需要新增 split 清单（先定种子/规则再采样）",
                "② **`binding_layer` 分布**：`CalibrationReport.is_finalizable` 的第 8 条要求"
                "运行时观测到的层分布；`tau_raw` 不含该字段（只有 `bind.py` 往 QueryPlanStore 落），"
                "runner 也未采集 ⇒ 必须先在 runner 侧补一条逐 case 的 `binding_layer`",
                "③ **批次身份**：`repeats` 要 3 次**独立**跑批；现有产物没有 `batch_id`，"
                "派生器只能按 case_id 跨文件分组 ⇒ 无法区分「3 次独立」与「同一份跑三遍」",
                "④ **候选覆盖**：L4 只覆盖 `v_order_paid`/`v_order_refund`/`v_product`；"
                "金标反解命中率实测低（见 sample_yield）",
            ],
            "sample_yield": {
                "n_records": len(records),
                "n_l4_scored": len(scored_l4),
                "n_gold_matched": len(scorable),
                "match_rate_of_scored": round(len(scorable) / max(len(scored_l4), 1), 4),
                "gold_status": _counter(
                    str((r.get("tau_raw") or {}).get("gold_status")) for r in records
                ),
            },
            "n_repeats_required": 3,
            "sampling_plan": {
                "scenario_subset": {
                    "requests_per_batch": subset["requests"],
                    "calls_per_batch_est": subset["calls_est"],
                    "batches": 3,
                    "calls_total_est": subset["calls_est"] * 3,
                    "tokens_total": subset["tokens"] * 3,
                    "cost_cny_measured": round(subset["cost_cny"] * 3, 6),
                    "cost_cny_with_margin": round(subset["cost_cny"] * 3 * MARGIN, 4),
                },
                "scenario_full": {
                    "requests_per_batch": full["requests"],
                    "calls_per_batch": full["calls"],
                    "batches": 3,
                    "calls_total": full["calls"] * 3,
                    "tokens_total": full["tokens"] * 3,
                    "cost_cny_measured": round(full["cost_cny"] * 3, 6),
                    "cost_cny_with_margin": round(full["cost_cny"] * 3 * MARGIN, 4),
                },
                "recommendation": (
                    "先跑 scenario_subset（29 条可校准题 × 3 批次 = 87 record / ≈267 次调用 / "
                    "2.44M tokens / 实测 ¥0.80）；它的样本量仍是当前候选面能产出的**全部**，"
                    "全批 3 次只会把同样的 29 条再跑一遍。硬上限建议 ¥2.50（≈3× 实测），"
                    "越过即停并把已花额度写进报告。"
                ),
            },
            "hard_cap": {
                "cost_cny": 2.5,
                "tokens": 3_500_000,
                "calls": 350,
                "rationale": "实测 ¥0.80 / 2.44M tokens / 267 calls × ≈1.4 → 取整；"
                "超限即停，不得「再试一次」——τ 采样不是结果导向的刷点数",
            },
        },
        "dimension_c1a": {
            "case_ids": city_cost["case_ids"],
            "cases": [
                {
                    "case_id": c["case_id"],
                    "question": c["question"],
                    "expected_behavior": c["expected_behavior"],
                    "gold_binding": c["gold_binding"],
                    "terminal_now": c["terminal"],
                }
                for c in dims["dimensions"]["city_cases"]
            ],
            "expected_flips": {
                "M-DIM-05": "refuse → complete（按 shop_city 落绑）",
                "M-MET-01": "refuse → complete（QA §96.5 的预期；它不是城市题，"
                "翻转取决于指标默认绑定，不取决于 shop_city —— 引用时必须分开说）",
                "unaffected": ["M-HIER-03", "M-MET-04（已是 complete）",
                               "C-CITY-01/02/04（expected=clarify）"],
            },
            "rerecord_cost": {
                "minimal_city_only": {
                    "requests": city_cost["requests"],
                    "calls_est": city_cost["calls_est"],
                    "tokens": city_cost["tokens"],
                    "cost_cny_measured": city_cost["cost_cny"],
                    "cost_cny_with_margin": round(city_cost["cost_cny"] * MARGIN, 4),
                    "valid_only_if": "其余 160 条匣带键**不变**",
                },
                "full_batch": {
                    "requests": full["requests"],
                    "calls": full["calls"],
                    "tokens": full["tokens"],
                    "cost_cny_measured": full["cost_cny"],
                    "cost_cny_with_margin": round(full["cost_cny"] * MARGIN, 4),
                    "why": "包内新增维度会改 planner 载荷（维度段逐条渲染进 prompt）⇒ "
                    "**每一条** plan 调用的匣带键都变 ⇒ 只重录 6 条时其余 160 条会在重放里"
                    "取不到对应调用。除非证明键未变，否则按全批计价",
                },
            },
            "hard_cap": {
                "cost_cny": 2.5,
                "tokens": 5_000_000,
                "calls": 700,
                "rationale": "实测全批 ¥1.09 / 3.65M tokens / 509 calls × ≈1.4 → 取整",
            },
            "not_executed": True,
        },
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {os.path.relpath(OUT, ROOT)}")
    print(
        "tau subset 3x:",
        payload["tau"]["sampling_plan"]["scenario_subset"]["calls_total_est"],
        "calls,",
        payload["tau"]["sampling_plan"]["scenario_subset"]["cost_cny_with_margin"],
        "CNY (with margin)",
    )
    print(
        "dimension full re-record:",
        payload["dimension_c1a"]["rerecord_cost"]["full_batch"]["calls"],
        "calls,",
        payload["dimension_c1a"]["rerecord_cost"]["full_batch"]["cost_cny_with_margin"],
        "CNY (with margin)",
    )
    return 0


def _counter(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    raise SystemExit(main())
