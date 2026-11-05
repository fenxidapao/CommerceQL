"""B6 多轮（2 轮喂图）的判定纯函数 —— 零 LLM、零 SQL、零文件副作用。

判定的唯一期望源是 `eval/dataset_multiturn_v1.json` 的 `turns[].expect`，被测值是图里
真正交给下游的 C-01 摘要 `plan_summary`（不是原始 `plan` —— 条件继承的合并结果写在
`plan_summary` 里，见 `app/graph/nodes/plan.py`）。

## 为什么数据集里出现、但这里不认识的键不许静默丢弃

`expect` 里当前有一个 `comparison`（mt05「它比 2017 年高多少？」），而 `PlanSummary`
没有对应字段。**本文件不做"猜一个字段"式映射**：这类键进 `unmapped` 原样上报，
让读数的人看见"这条期望没有被判到"，而不是让分母悄悄少一条。

## 比较口径（都写在这里，测试逐条钉住）

- 集合类（`metrics` / `dimensions` / `filters` / `order_by`）：去重 + 大小写/空白归一后比集合；
- 时间窗：比 `time_range.start` / `time_range.end` 的 ISO 日期字符串（金标右开区间）；
- `grain` / `limit`：直接比；
- 计划缺失（图没走到 `plan`）：所有映射字段都记 `actual=None`、`ok=False`，不当作"空计划通过"。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

HERE: Final[Path] = Path(__file__).resolve().parent
DATASET_PATH: Final[Path] = HERE / "dataset_multiturn_v1.json"

#: 数据集形状的硬约束（B6 交接时写死 15 条 × 2 轮；超出必须显式改这里，不静默接受）。
EXPECTED_CASES: Final[int] = 15
EXPECTED_TURNS: Final[int] = 2
FOLLOW_UP_TYPES: Final[frozenset[str]] = frozenset(
    {
        "ellipsis_time",
        "metric_switch",
        "metric_add",
        "dimension_add",
        "filter_change",
        "filter_add",
        "pronoun",
        "grain_change",
        "limit",
        "reset",
    }
)

#: `expect` 里本文件能判的键。
MAPPED_KEYS: Final[tuple[str, ...]] = (
    "metrics",
    "dimensions",
    "filters",
    "grain",
    "time_start",
    "time_end",
    "order_by",
    "limit",
)


def load_dataset(path: str | Path = DATASET_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def content_hash(cases: Sequence[Mapping[str, Any]]) -> str:
    """与数据集 stamp 同口径（compact + sort_keys）—— 现算，不抄 stamp。"""
    body = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def verify_dataset(spec: Mapping[str, Any]) -> dict[str, Any]:
    """形状 + 内容哈希 + 追问启发式的数据集自检（不建图、不调 LLM）。"""
    from app.planner.inherit import looks_like_follow_up

    cases = list(spec.get("cases") or [])
    actual_hash = content_hash(cases)
    shape_errors: list[str] = []
    if len(cases) != EXPECTED_CASES:
        shape_errors.append(f"n_cases={len(cases)} != {EXPECTED_CASES}")
    if int(spec.get("n_cases") or 0) != len(cases):
        shape_errors.append(f"declared n_cases={spec.get('n_cases')} != 实际 {len(cases)}")
    heuristic_errors: list[str] = []
    for case in cases:
        case_id = str(case.get("case_id"))
        turns = list(case.get("turns") or [])
        if len(turns) != EXPECTED_TURNS:
            shape_errors.append(f"{case_id}: turns={len(turns)} != {EXPECTED_TURNS}")
            continue
        follow_up_type = str(case.get("follow_up_type"))
        if follow_up_type not in FOLLOW_UP_TYPES:
            shape_errors.append(f"{case_id}: 未知 follow_up_type={follow_up_type}")
        expected = follow_up_type != "reset"
        second = str(turns[1].get("question") or "")
        if looks_like_follow_up(second) is not expected:
            heuristic_errors.append(f"{case_id}: looks_like_follow_up({second!r}) != {expected}")
    return {
        "n_cases": len(cases),
        "content_hash": {"expected": spec.get("content_hash"), "actual": actual_hash,
                         "ok": actual_hash == spec.get("content_hash")},
        "shape_errors": shape_errors,
        "heuristic_errors": heuristic_errors,
        "ok": (
            not shape_errors
            and not heuristic_errors
            and actual_hash == spec.get("content_hash")
        ),
    }


def _norm(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _norm_set(value: Any) -> frozenset[str]:
    if not isinstance(value, (list, tuple)):
        return frozenset()
    return frozenset(_norm(item) for item in value if str(item).strip())


def plan_summary_from_state(state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """从图终态取 C-01 摘要；没有 `plan_summary` 时退回 `plan` 的等价投影。"""
    if not isinstance(state, Mapping):
        return None
    summary = state.get("plan_summary")
    if isinstance(summary, Mapping):
        return dict(summary)
    plan = state.get("plan")
    if not isinstance(plan, Mapping):
        return None
    metrics = plan.get("metrics") or []
    names = [
        str(item.get("name")) if isinstance(item, Mapping) else str(item)
        for item in metrics
        if (item.get("name") if isinstance(item, Mapping) else item)
    ]
    return {
        "metrics": names,
        "dimensions": list(plan.get("dimensions") or []),
        "filters": list(plan.get("filters") or []),
        "grain": plan.get("grain"),
        "time_range": dict(plan.get("time_range") or {}),
        "order_by": list(plan.get("order_by") or []),
        "limit": plan.get("limit"),
        "blocked": bool(plan.get("blocking_issues")),
    }


#: 与 `app/api/runner.py::_sanitize_history_plan` 的限长逐字一致。
#: ⚠️ 不能直接 import 生产函数：`tests/eval/test_eval_boundary.py` 明令 **eval 不许碰
#: `app.api`**（HTTP 层一旦进评测，数字就掺进路由/序列化行为）。此处是**镜像**，
#: 由 `tests/eval/test_multiturn_runner.py::test_history_sanitizer_matches_production`
#: 对同一批输入做等价断言；漂移会先红在测试上。
_HISTORY_LIST_LIMIT: Final[int] = 20
_HISTORY_STRING_LIMIT: Final[int] = 200
_HISTORY_TIME_LIMIT: Final[int] = 64
_HISTORY_LIMIT_MAX: Final[int] = 10_000


def _history_strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value[:_HISTORY_LIST_LIMIT]:
        text = item.strip() if isinstance(item, str) else ""
        if text:
            out.append(text[:_HISTORY_STRING_LIMIT])
    return out


def sanitize_history_plan(raw: Any) -> dict[str, Any] | None:
    """`plan_summary` → 可进图的脱敏摘要（生产 `_sanitize_history_plan` 的镜像）。"""
    if not isinstance(raw, Mapping):
        return None
    plan: dict[str, Any] = {}
    for key in ("metrics", "dimensions", "filters", "order_by"):
        values = _history_strings(raw.get(key))
        if values:
            plan[key] = values
    grain = raw.get("grain")
    if isinstance(grain, str) and grain.strip():
        plan["grain"] = grain.strip()[:_HISTORY_STRING_LIMIT]
    time_range = raw.get("time_range")
    if isinstance(time_range, Mapping):
        window = {
            side: str(time_range[side]).strip()[:_HISTORY_TIME_LIMIT]
            for side in ("start", "end")
            if isinstance(time_range.get(side), str) and str(time_range[side]).strip()
        }
        if window:
            plan["time_range"] = window
    limit = raw.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= _HISTORY_LIMIT_MAX:
        plan["limit"] = limit
    return plan or None


def history_plan_from_summary(summary: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """播种下一轮的 `history_plan` —— 形状与在线 `sess:plan` 播种一致（见上）。"""
    return sanitize_history_plan(summary)


def _summary_time(summary: Mapping[str, Any] | None, side: str) -> Any:
    if not isinstance(summary, Mapping):
        return None
    window = summary.get("time_range")
    if not isinstance(window, Mapping):
        return None
    return window.get(side)


def compare_expectation(
    expect: Mapping[str, Any],
    summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """按 `expect` 逐字段比 `plan_summary`；返回可 JSON 化的判定明细。"""
    fields: dict[str, dict[str, Any]] = {}
    for key in ("metrics", "dimensions", "filters", "order_by"):
        if key not in expect:
            continue
        expected = _norm_set(expect.get(key))
        actual = _norm_set((summary or {}).get(key))
        fields[key] = {"expected": sorted(expected), "actual": sorted(actual),
                       "ok": expected == actual}
    if "grain" in expect:
        expected = expect.get("grain")
        actual = (summary or {}).get("grain")
        fields["grain"] = {"expected": expected, "actual": actual, "ok": expected == actual}
    if "limit" in expect:
        expected = expect.get("limit")
        actual = (summary or {}).get("limit")
        fields["limit"] = {"expected": expected, "actual": actual, "ok": expected == actual}
    for key in ("time_start", "time_end"):
        if key not in expect:
            continue
        expected = expect.get(key)
        actual = _summary_time(summary, "start" if key == "time_start" else "end")
        fields[key] = {"expected": expected, "actual": actual, "ok": expected == actual}

    unmapped = {
        key: value for key, value in expect.items() if key not in MAPPED_KEYS
    }
    return {
        "passed": all(item["ok"] for item in fields.values()),
        "fields": fields,
        "unmapped": unmapped,
        "plan_present": summary is not None,
    }


def score_case_turns(case_id: str, follow_up_type: str, turns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """把一条用例的两轮原始记录变成判定记录（replay 与 live 共用这一个函数）。"""
    scored_turns: list[dict[str, Any]] = []
    for index, turn in enumerate(turns, start=1):
        expect = dict(turn.get("expect") or {})
        summary = turn.get("plan_summary")
        comparison = compare_expectation(expect, summary if isinstance(summary, Mapping) else None)
        scored_turns.append(
            {
                "turn": index,
                "question": turn.get("question"),
                "expect": expect,
                "terminal_event": turn.get("terminal_event"),
                "plan_summary": summary,
                "history_seeded": bool(turn.get("history_seeded")),
                "comparison": comparison,
                "tokens": turn.get("tokens"),
                "cost_cny": turn.get("cost_cny"),
            }
        )
    turn_passes = [bool(item["comparison"]["passed"]) for item in scored_turns]
    return {
        "case_id": case_id,
        "follow_up_type": follow_up_type,
        "turns": scored_turns,
        "turn_passes": turn_passes,
        "both_passed": bool(turn_passes) and all(turn_passes),
    }


def summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """两轮分开计数：turn2 才是"继承是否生效"的读数，不能和 turn1 混成一个准确率。"""
    n_cases = len(records)
    turn1 = sum(1 for record in records if (record.get("turn_passes") or [False])[0])
    turn2 = sum(
        1
        for record in records
        if len(record.get("turn_passes") or []) > 1 and record["turn_passes"][1]
    )
    both = sum(1 for record in records if record.get("both_passed"))
    unmapped = sorted(
        {
            key
            for record in records
            for turn in record.get("turns") or []
            if isinstance(turn, Mapping)
            for key in (turn.get("comparison") or {}).get("unmapped") or {}
        }
    )
    missing_plan = sum(
        1
        for record in records
        for turn in record.get("turns") or []
        if not (turn.get("comparison") or {}).get("plan_present")
    )
    return {
        "n_cases": n_cases,
        "turn1_passed": turn1,
        "turn2_passed": turn2,
        "cases_both_passed": both,
        "plans_missing": missing_plan,
        "unmapped_expect_keys": unmapped,
        "cost_cny_total": round(
            sum(float(turn.get("cost_cny") or 0) for record in records
                for turn in record.get("turns") or []),
            6,
        ),
    }


__all__ = [
    "DATASET_PATH",
    "EXPECTED_CASES",
    "EXPECTED_TURNS",
    "FOLLOW_UP_TYPES",
    "MAPPED_KEYS",
    "compare_expectation",
    "content_hash",
    "history_plan_from_summary",
    "load_dataset",
    "plan_summary_from_state",
    "sanitize_history_plan",
    "score_case_turns",
    "summarize",
    "verify_dataset",
]
