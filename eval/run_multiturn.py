"""B6 多轮 runner：15 条两轮用例 → 逐轮判定（turn1 / turn2 分开计数）。

三种模式，**默认不花钱**：

    1. `--check`（默认）：只验数据集 hash/形状/追问启发式，不建图、不调 LLM；
    2. `--replay <records.json>`：对已经跑过的记录重打分，零成本；
    3. `--live --yes`：真打 LLM 跑两轮（turn1 的 `plan_summary` 经生产同一守卫脱敏后
       作为 turn2 的 `history_plan`），受 `--max-cost-cny` 硬停约束。

⚠️ live 模式会真实计费，且本仓库纪律是"无预算批准不跑"：没有 `--yes` 只打印计划。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for _path in (str(REPO_ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import multiturn  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"


def _repo_path(value: str | Path | None, fallback: Path) -> Path:
    if value is None:
        return fallback
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _bundle_path(spec: Mapping[str, Any], override: str | Path | None) -> Path:
    return _repo_path(override or spec.get("bundle"), REPO_ROOT / "semantic")


def check_dataset(spec: Mapping[str, Any]) -> dict[str, Any]:
    """数据集自检（形状/hash/启发式）—— 与 live 读数无关，可随时跑。"""
    result = multiturn.verify_dataset(spec)
    result["dataset"] = spec.get("dataset")
    result["dataset_version"] = spec.get("dataset_version")
    return result


def replay_records(payload: Mapping[str, Any]) -> dict[str, Any]:
    """对已落盘记录重打分；不构造 Harness、不出站、不读数据库。"""
    cases = list(payload.get("records") or [])
    dataset_hash = payload.get("dataset_content_hash")
    if payload.get("dataset_cases") is not None:
        actual = multiturn.content_hash(payload["dataset_cases"])
        if dataset_hash != actual:
            raise ValueError(
                f"记录的数据集哈希不符：记录 {dataset_hash} / 现算 {actual}"
            )
    records = [
        multiturn.score_case_turns(
            str(case.get("case_id")),
            str(case.get("follow_up_type")),
            list(case.get("turns") or []),
        )
        for case in cases
    ]
    return {
        "mode": "replay",
        "dataset_content_hash": dataset_hash,
        "records": records,
        "summary": multiturn.summarize(records),
    }


async def run_live(
    spec: Mapping[str, Any],
    *,
    bundle_path: Path,
    db_path: Path,
    tenant: str,
    limit: int | None,
    max_cost_cny: float,
) -> dict[str, Any]:
    """真打两轮：turn1 → 生产同款脱敏 → turn2 的 `history_plan`。"""
    from harness import Harness, eval_node_timeouts

    cases = list(spec.get("cases") or [])
    if limit is not None:
        cases = cases[: max(0, limit)]
    harness = Harness(
        live=True,
        bundle_path=str(bundle_path),
        db_path=str(db_path),
        node_timeout_overrides=eval_node_timeouts(),
    )
    records: list[dict[str, Any]] = []
    spent = 0.0
    budget_stopped = False
    try:
        for case in cases:
            if spent >= max_cost_cny:
                budget_stopped = True
                break
            case_id = str(case["case_id"])
            history: dict[str, Any] | None = None
            raw_turns: list[dict[str, Any]] = []
            for index, turn in enumerate(case.get("turns") or [], start=1):
                question = str(turn.get("question") or "")
                extra = {"history_plan": history} if history else None
                run = await harness.run_case_async(
                    case_id=f"{case_id}-t{index}",
                    question=question,
                    tenant=tenant,
                    extra_state=extra,
                )
                summary = multiturn.plan_summary_from_state(run.state)
                raw_turns.append(
                    {
                        "turn": index,
                        "question": question,
                        "expect": turn.get("expect") or {},
                        "terminal_event": run.terminal_event,
                        "plan_summary": summary,
                        "history_seeded": history,
                        "tokens": run.tokens,
                        "cost_cny": run.cost_cny,
                    }
                )
                spent += float(run.cost_cny or 0)
                history = multiturn.history_plan_from_summary(summary)
                if spent >= max_cost_cny:
                    budget_stopped = True
                    break
            records.append(
                multiturn.score_case_turns(
                    case_id, str(case.get("follow_up_type")), raw_turns
                )
            )
    finally:
        await harness.aclose()
    return {
        "mode": "live",
        "dataset_cases": list(spec.get("cases") or []),
        "dataset_content_hash": spec.get("content_hash"),
        "budget": {
            "max_cost_cny": max_cost_cny,
            "spent_cny": round(spent, 6),
            "stopped": budget_stopped,
        },
        "records": records,
        "summary": multiturn.summarize(records),
    }


def _report(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    stamp = _bootstrap.build_stamp()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "stamp": stamp,
        "dataset": spec.get("dataset"),
        "dataset_version": spec.get("dataset_version"),
        **payload,
    }


def _print_summary(result: Mapping[str, Any]) -> None:
    if result.get("mode") == "check":
        check = result.get("check") or {}
        print(
            "数据集自检：{verdict}（{n} 条；hash {h}）".format(
                verdict="通过" if check.get("ok") else "失败",
                n=check.get("n_cases", 0),
                h="一致" if (check.get("content_hash") or {}).get("ok") else "不一致",
            )
        )
        return
    summary = result.get("summary") or {}
    print(
        "多轮读数：{t1}/{n} turn1 通过，{t2}/{n} turn2 通过，"
        "两轮全过 {both}/{n}；计划缺失 {miss}；未映射期望键 {unmapped}".format(
            t1=summary.get("turn1_passed", 0),
            t2=summary.get("turn2_passed", 0),
            both=summary.get("cases_both_passed", 0),
            n=summary.get("n_cases", 0),
            miss=summary.get("plans_missing", 0),
            unmapped=summary.get("unmapped_expect_keys") or "无",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(multiturn.DATASET_PATH))
    parser.add_argument("--bundle", default=None, help="默认取数据集里的 bundle 字段")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--tenant", default=None, help="默认取数据集里的 tenant")
    parser.add_argument("--check", action="store_true", help="只验数据集（默认行为）")
    parser.add_argument("--replay", default=None, help="对已落盘记录重打分（零成本）")
    parser.add_argument("--live", action="store_true", help="真打 LLM（计费，需 --yes）")
    parser.add_argument("--yes", action="store_true", help="确认 live 计费")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条用例")
    parser.add_argument("--max-cost-cny", type=float, default=2.0)
    parser.add_argument("--out", default=None, help="报告落盘路径；live 必填")
    args = parser.parse_args(argv)

    spec = multiturn.load_dataset(args.dataset)
    check = check_dataset(spec)
    if not check["ok"]:
        print(json.dumps(check, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3

    if args.replay:
        payload = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        result = _report(replay_records(payload), spec)
    elif args.live:
        if not args.yes:
            print(
                f"未带 --yes：只打印计划，不构造 Harness、不调 LLM。\n"
                f"  用例 {len(spec['cases'])} 条 × 2 轮；成本硬停 ¥{args.max_cost_cny}",
                file=sys.stderr,
            )
            return 0
        if not args.out:
            print("live 必须给 --out（每次读数都要是一件新证据，不覆盖旧件）", file=sys.stderr)
            return 2
        bundle_path = _bundle_path(spec, args.bundle)
        db_path = _repo_path(args.db, DEFAULT_DB)
        if not bundle_path.is_file() or not db_path.is_file():
            print(f"缺输入：bundle={bundle_path} db={db_path}", file=sys.stderr)
            return 4
        result = _report(
            asyncio.run(
                run_live(
                    spec,
                    bundle_path=bundle_path,
                    db_path=db_path,
                    tenant=str(args.tenant or spec.get("tenant") or "T_A"),
                    limit=args.limit,
                    max_cost_cny=args.max_cost_cny,
                )
            ),
            spec,
        )
    else:
        result = _report({"mode": "check", "check": check}, spec)

    _print_summary(result)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"报告：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
