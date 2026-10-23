"""W76-1：τ 校准（3 批独立重放 → 样本 → 选点 → 验收集复核）。零出站。

输入：3 份 `results_w76_tau_b*.json`（`--live` 真打、各自 `batch_id`）。
输出：`eval/results_w76_tau_calibration.json` —— 含曲线、选点、验收集读数、
`is_finalizable` 与**缺哪一条**（缺就不定稿，不硬选 τ）。

两条纪律（派单 §97.8）：
* split 规则在采样**前**写死（`tau_samples.split_of`，盐带版本号）；
* `is_finalizable=false` 时如实列出 `blocking_actions` —— 不得为了"有个 τ"而跳过条款。

跑法（CommerceQL 根目录，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w76_tau_calibrate.py \
        eval/results_w76_tau_b1.json eval/results_w76_tau_b2.json eval/results_w76_tau_b3.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

from eval.tau_samples import (  # noqa: E402
    SPLIT_CALIBRATION,
    build_score_samples,
    coverage_summary,
    split_of,
    split_summary,
    summarize,
)

#: §C.4.6 步骤 3 的绑定准确率目标。原文未给数值（"由调用方按业务口径给定"），
#: 这里取 `app/binding/__init__.py` 文档示例里的 0.8 —— 写进产物，便于复核。
ACCURACY_TARGET = 0.8

OUT = os.path.join(HERE, "results_w76_tau_calibration.json")


def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="τ 校准（离线派生 + 验收集复核）")
    parser.add_argument("results", nargs="+", help="≥3 份 results_*.json（各自 batch_id）")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args(argv)

    from app.binding.calibration import TAU_SWEEP_STEP, assess_stability, calibrate, sweep
    from app.core.config import get_settings

    payloads = [_load(p) for p in args.results]
    records: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    for path, payload in zip(args.results, payloads, strict=True):
        records.extend(payload.get("records") or [])
        summary = payload.get("summary") or {}
        batches.append({
            "path": os.path.relpath(path, ROOT).replace("\\", "/"),
            "batch_id": (payload.get("config") or {}).get("batch_id"),
            "git_rev": payload.get("git_rev"),
            "git_dirty": payload.get("git_dirty"),
            "n_records": summary.get("n_records"),
            "tokens_total": summary.get("tokens_total"),
            "cost_cny_total": summary.get("cost_cny_total"),
            "cassette_entries_written": summary.get("cassette_entries_written"),
            "budget_stop": (payload.get("config") or {}).get("budget_stop"),
        })

    settings = get_settings()
    epsilon = float(settings.BINDING_TAU_EPSILON)
    samples, skips = build_score_samples(records, min_repeats=3)
    calibration = [s for s in samples if split_of(s.sample_id) == SPLIT_CALIBRATION]
    holdout = [s for s in samples if split_of(s.sample_id) != SPLIT_CALIBRATION]

    layers: dict[str, int] = {}
    for record in records:
        key = str(record.get("binding_layer") or "none")
        layers[key] = layers.get(key, 0) + 1

    scorer = next(
        (
            (r.get("tau_raw") or {}).get("scorer") or {}
            for r in records
            if (r.get("tau_raw") or {}).get("ok")
        ),
        {},
    )

    report = None
    if calibration:
        report = calibrate(
            calibration,
            epsilon=epsilon,
            accuracy_target=ACCURACY_TARGET,
            model_id=str(scorer.get("model_id") or ""),
            prompt_version=str(scorer.get("prompt_version") or ""),
            calibrated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            holdout_separated=bool(holdout),
            layer_distribution=layers,
        )

    holdout_reading = None
    selected_tau = None if report is None else report.selected_tau
    if selected_tau is not None and holdout:
        points = sweep(holdout, epsilon=epsilon)
        point = next((p for p in points if abs(p.tau - selected_tau) < TAU_SWEEP_STEP / 2), None)
        if point is not None:
            holdout_reading = {
                "tau": point.tau,
                "n_samples": len(holdout),
                "binding_accuracy": point.binding_accuracy,
                "should_clarify_but_did_not": point.should_clarify_but_did_not,
                "clarify_rate": point.clarify_rate,
                "decided": point.decided,
                "meets_accuracy_target": (
                    point.binding_accuracy is not None
                    and point.binding_accuracy >= ACCURACY_TARGET
                ),
                "meets_nfr71": point.clarify_rate <= 0.15,
            }

    stability_calib = assess_stability(calibration) if calibration else None
    output: dict[str, Any] = {
        **_bootstrap.build_stamp(),
        "task": "W76-1 τ 校准（3 批独立真打 → 校准集选点 → 验收集复核）",
        "inputs": batches,
        "split": split_summary(str(s.sample_id) for s in samples),
        "coverage": coverage_summary(records),
        "samples": summarize(samples, skips),
        "epsilon": epsilon,
        "accuracy_target": ACCURACY_TARGET,
        "sweep_step": TAU_SWEEP_STEP,
        "layer_distribution": layers,
        "scorer": scorer,
        "stability_calibration": None
        if stability_calib is None
        else {
            "verdict": str(getattr(stability_calib, "verdict", "")),
            "is_calibratable": bool(getattr(stability_calib, "is_calibratable", False)),
            "max_gap_std": getattr(stability_calib, "max_gap_std", None),
        },
        "calibration": None
        if report is None
        else {
            "n_calibration_samples": len(calibration),
            "selected_tau": report.selected_tau,
            "selected_point": None
            if report.selected_point is None
            else {
                "tau": report.selected_point.tau,
                "binding_accuracy": report.selected_point.binding_accuracy,
                "clarify_rate": report.selected_point.clarify_rate,
                "decided": report.selected_point.decided,
            },
            "nfr71_satisfied": report.nfr71_satisfied,
            "escalation_required": report.escalation_required,
            "is_finalizable": report.is_finalizable,
            "blocking_actions": list(report.blocking_actions),
            "curve": [
                {
                    "tau": p.tau,
                    "binding_accuracy": p.binding_accuracy,
                    "clarify_rate": p.clarify_rate,
                    "decided": p.decided,
                    "should_clarify_but_did_not": p.should_clarify_but_did_not,
                }
                for p in report.points
            ],
        },
        "holdout": holdout_reading,
        "finalizable_answer": (
            "是：可据此写入 .env（本脚本不改 .env，写不写由总控定）"
            if report is not None and report.is_finalizable
            else "否：见 calibration.blocking_actions，缺一条就不能定稿"
        ),
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {os.path.relpath(args.out, ROOT)}")
    print(
        "samples:", len(samples),
        "| calibration:", len(calibration), "| holdout:", len(holdout),
        "| skipped:", len(skips),
    )
    if report is None:
        print("no calibration samples -> no tau")
    else:
        print(
            "selected tau:", report.selected_tau,
            "| finalizable:", report.is_finalizable,
            "| blockers:", list(report.blocking_actions),
        )
    if holdout_reading is not None:
        print("holdout:", holdout_reading)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
