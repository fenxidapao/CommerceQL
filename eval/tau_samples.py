"""τ 采样**派生器**：`record["tau_raw"]` → `ScoreSample`（W8 第 65 轮 C2）。

归属契约（QA §86.2-2 的三条点句，逐条落在这里）：

| 点句 | 落地方式 |
|---|---|
| 候选 ID 用**稳定键**（禁下标）、顺序另存 `rank` | 上游 `bind` 就按 `资产.列` 写 `candidate_ids`；本模块**只按下标对齐到 id 序列**，从不把下标当身份 |
| gold 由 `gold_sql` **反解**，匹配不上写 `null` + `reason`，不许猜 | 反解在 `runner._gold_for_tau`；本模块只**消费** `gold_status`，遇 `unmatched` **跳过** |
| raw 与 `ScoreSample` **双落**：record 存 raw，ScoreSample 由 record 派生 | 本模块是**唯一**派生点（纯函数、零出站），`calibrate()` 只吃它的输出 |

🔴 **为什么 `unmatched` 必须跳过、不能落成 `gold_candidate_id=None`**：
`ScoreSample` 里 `None` 的语义是"**本该澄清**"（§C.4.6 步骤 2 的安全侧样本）。
把"没反解出来"写进同一个 `None`，等于凭空造一批"该澄清未澄清"样本，
校准出来的 τ 会朝"更容易澄清"漂 —— 那正是 NFR-7.1 最不希望的方向。

🔴 **重复从哪来**：`ScoreSample.repeats` 要求 `n ≥ MIN_REPEATS`（§C.4.6 约束 5）。
单次跑批只有一次打分 ⇒ **必须同一 case 有 ≥3 次独立跑批**（同 prompt/同打分器）才能成样本。
本模块按 `case_id` 分组，不跨 case 拼凑、不对分数取平均（取平均是约束 5 明令禁止的"藏方差"）。

用法（零出站）：

    python eval/tau_samples.py eval/results_a.json eval/results_b.json eval/results_c.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

SCHEMA = "W8_TAU_RAW/v1"

#: 与 `runner.TAU_RAW_SCHEMA` 必须同值（两处都改，或都别改）。
ACCEPTED_SCHEMA = SCHEMA


def _tau_raw(record: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = record.get("tau_raw")
    return raw if isinstance(raw, Mapping) else {}


def candidate_ids_of(record: Mapping[str, Any]) -> list[str]:
    """该记录的候选**稳定键**序列（未打分 / 未走到 L4 ⇒ 空）。"""
    return [str(cid) for cid in (_tau_raw(record).get("candidate_ids") or [])]


def scores_of(record: Mapping[str, Any]) -> list[float]:
    return [float(x) for x in (_tau_raw(record).get("scores") or [])]


def gold_of(record: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
    """`(gold_status, gold_candidate_id, gold_unmatched_reason)`。"""
    raw = _tau_raw(record)
    status = str(raw.get("gold_status") or "missing")
    cid = raw.get("gold_candidate_id")
    reason = raw.get("gold_unmatched_reason")
    return status, (None if cid is None else str(cid)), (None if reason is None else str(reason))


def coverage_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """金标反解的**覆盖情况**（这不是校准结果，只是"能校准多少"的分母）。"""
    by_status: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    scored = 0
    for record in records:
        raw = _tau_raw(record)
        status, _, reason = gold_of(record)
        by_status[status] = by_status.get(status, 0) + 1
        if status == "unmatched" and reason:
            by_reason[reason] = by_reason.get(reason, 0) + 1
        if raw.get("ok"):
            scored += 1
    return {
        "n_records": sum(by_status.values()),
        "n_l4_scored": scored,
        "gold_status": dict(sorted(by_status.items())),
        "gold_unmatched_reason": dict(sorted(by_reason.items())),
    }


def build_score_samples(
    records: Sequence[Mapping[str, Any]],
    *,
    min_repeats: int,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """按 `case_id` 分组派生 `ScoreSample`。返回 `(samples, skips)`。

    `skips` 里每条都带**可读原因**：一份"0 样本"的校准报告必须能回答"为什么是 0"，
    否则它看起来像"模型没有歧义"，而实际可能是"我们没采到"。
    """
    from app.binding.calibration import MIN_REPEATS, ScoreSample  # 局部 import：本模块只被离线/评测调用

    # ⚠️ `ScoreSample.__post_init__` **自己**就要求 `n ≥ MIN_REPEATS`（§C.4.6 约束 5）。
    # 把 `min_repeats` 调低不会"放宽校验"，只会让每条样本在构造时被拒 —— 所以这里夹紧，
    # 让"要求低于常量"表现为**多要重复**而不是**静默 0 样本**。
    effective_repeats = max(int(min_repeats), int(MIN_REPEATS))

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        groups.setdefault(str(record.get("case_id")), []).append(record)

    samples: list[Any] = []
    skips: list[dict[str, Any]] = []
    for case_id in sorted(groups):
        rows = groups[case_id]

        def _skip(reason: str, **extra: Any) -> None:
            skips.append({"sample_id": case_id, "reason": reason, **extra})

        usable = [r for r in rows if _tau_raw(r).get("ok") and scores_of(r)]
        if len(usable) < effective_repeats:
            _skip(
                "insufficient_repeats",
                usable=len(usable),
                required=effective_repeats,
                total_records=len(rows),
            )
            continue

        # 候选集必须**逐次一致**（用 set 比较，顺序按首条的 id 序列对齐）。
        first_ids = candidate_ids_of(usable[0])
        first_set = frozenset(first_ids)
        if any(frozenset(candidate_ids_of(r)) != first_set for r in usable):
            _skip("candidate_set_unstable", candidate_ids=first_ids)
            continue
        if len(first_ids) < 2:
            _skip("single_candidate", candidate_ids=first_ids)
            continue

        repeats: list[tuple[float, ...]] = []
        broken = False
        for record in usable[:effective_repeats]:
            by_id = dict(zip(candidate_ids_of(record), scores_of(record)))
            if any(cid not in by_id for cid in first_ids):
                broken = True
                break
            repeats.append(tuple(by_id[cid] for cid in first_ids))
        if broken:
            _skip("candidate_set_unstable", candidate_ids=first_ids)
            continue

        statuses = {gold_of(r)[0] for r in usable}
        if len(statuses) > 1:
            _skip("gold_status_inconsistent", statuses=sorted(statuses))
            continue
        status, gold_cid, gold_reason = gold_of(usable[0])
        if status == "unmatched":
            # 🔴 跳过，**不**当作"该澄清"（见模块 docstring）。
            _skip("gold_unmatched", gold_unmatched_reason=gold_reason)
            continue
        if status not in {"matched", "expected_clarify"}:
            _skip("gold_missing", gold_status=status)
            continue

        try:
            samples.append(
                ScoreSample(
                    sample_id=case_id,
                    candidate_ids=tuple(first_ids),
                    repeats=tuple(repeats),
                    gold_candidate_id=gold_cid,
                )
            )
        except ValueError as exc:  # 契约不合（越界分数 / id 重复…）→ 如实跳过，不修数据
            _skip("score_sample_rejected", detail=str(exc)[:200])
    return samples, skips


def summarize(samples: Sequence[Any], skips: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "n_samples": len(samples),
        "n_skipped_cases": len(skips),
        "skip_reasons": _count(str(s.get("reason")) for s in skips),
        "samples": [
            {
                "sample_id": s.sample_id,
                "candidate_ids": list(s.candidate_ids),
                "repeats": [list(row) for row in s.repeats],
                "gold_candidate_id": s.gold_candidate_id,
            }
            for s in samples
        ],
        "skips": list(skips),
    }


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tau_raw → ScoreSample 派生器（零出站）")
    parser.add_argument("results", nargs="+", help="一份或多份 results_*.json（同一冻结集）")
    parser.add_argument("--out", default=None, help="把派生结果写到该 JSON 路径")
    parser.add_argument(
        "--min-repeats",
        type=int,
        default=None,
        help="覆盖 §C.4.6 约束 5 的最小重复次数（默认取 calibration.MIN_REPEATS）",
    )
    args = parser.parse_args(argv)

    sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    try:  # 与 runner 同款：让 `app.*` 可导入
        import _bootstrap  # noqa: F401

        _bootstrap.bootstrap()
    except Exception:  # pragma: no cover - 离线兜底
        pass

    from app.binding.calibration import MIN_REPEATS

    records: list[dict[str, Any]] = []
    files: list[str] = []
    for path in args.results:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        files.append(os.path.basename(path))
        records.extend(payload.get("records") or [])

    samples, skips = build_score_samples(
        records, min_repeats=args.min_repeats or MIN_REPEATS
    )
    report = {
        "schema": SCHEMA,
        "inputs": files,
        "coverage": coverage_summary(records),
        **summarize(samples, skips),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}  samples={len(samples)}  skipped={len(skips)}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
