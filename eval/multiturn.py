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
from datetime import date, timedelta
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


def _date_part(value: Any) -> date | None:
    """取 `YYYY-MM-DD` 头部（容忍 `T`/空格分隔与带时分秒）。取不到返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip().replace("T", " ")
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _exclusive_upper(value: Any) -> date | None:
    """`time_end` 侧归一：闭区间上界（`… 23:59:59`，含 `T` 分隔）抬成次日 00:00:00。

    ⚠️ **纯日期上界（`2018-12-31`）刻意不抬**（U-157；U-165 尝试改成「抬」、同日撤回）：
    它既可能就是闭区间当天，也可能是右开的另一种写法；契约未定义 ⇒ 按字面比，不猜。
    撤回理由：抬次日会与既有反向控制 `test_compare_detects_mismatch[time_end-mutate2]`
    直接互斥，且 `timeexpr.py:227-234` 只定义 `resolve_time` 的产出格式、不构成
    「计划里的裸日期 = 闭区间」的契约；评测口径变更属红线，须书面裁定。
    """
    day = _date_part(value)
    if day is None:
        return None
    text = str(value).strip().replace("T", " ")
    return day + timedelta(days=1) if text.endswith("23:59:59") else day


def time_field_ok(key: str, expected: Any, actual: Any) -> bool:
    """时间面判定（U-157）：两侧按**日粒度**比，右开/闭区间归一后再比。

    修的是「模块口径说 ISO 日期字符串、实现做原始字符串全等」这处分歧
    （见本模块 docstring 比较口径第 2 条）。`actual is None`（无完整计划）照旧判不等，
    但统计层由 `plans_missing` 单列，不与「时间答错」混计。
    """
    if expected is None or actual is None:
        return expected == actual
    if key == "time_start":
        left, right = _date_part(expected), _date_part(actual)
    else:
        left, right = _exclusive_upper(expected), _exclusive_upper(actual)
    return left is not None and left == right


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
        # U-157：原先在这里做 `expected == actual`（原始字符串全等），与本模块
        # docstring 第 2 条「比 ISO 日期字符串、金标右开」不一致 ⇒ 改走 time_field_ok。
        fields[key] = {
            "expected": expected,
            "actual": actual,
            "ok": time_field_ok(key, expected, actual),
        }

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
                # 🔴 U-162 补（2026-11-09）：四键由 run_multiturn 用
                # `**multiturn.turn_attribution(run)` 展开进 raw turn，**必须在这里透传**——
                # 否则本函数用固定键集重建 turn 时会把它们丢掉（r3 冒烟实测 four_keys=0/4
                # 就是这条：产出侧改了、重装侧没改）。缺则回 None / {} / ()，**不编值**。
                "terminal_code": turn.get("terminal_code"),
                "refusal_reason": turn.get("refusal_reason"),
                "intent_detail": dict(turn.get("intent_detail"))
                if isinstance(turn.get("intent_detail"), Mapping)
                else {},
                "nodes": tuple(turn.get("nodes") or ()),
                # 🔴 U-166：同一道穿点守卫 —— 产出侧加了键、这里不透传就等于没加
                # （U-162 已在 r3 冒烟上踩过一次：four_keys=0/4）。缺则回 "" / None，不编值。
                "sql_text": str(turn.get("sql_text") or ""),
                "exec_error_class": turn.get("exec_error_class"),
                "gate1_reject_rule": turn.get("gate1_reject_rule"),  # U-168 穿点
            }
        )
    turn_passes = [bool(item["comparison"]["passed"]) for item in scored_turns]
    return {
        "case_id": case_id,
        "follow_up_type": follow_up_type,
        "turns": scored_turns,
        "turn_passes": turn_passes,
        # U-160：**未跑完 != 通过**。原先的 `bool(turn_passes) and all(turn_passes)`
        # 让单元素 `[True]`（只跑完 turn1、turn2 被预算掐掉）也算「两轮全过」——
        # 实测 r2 的 mt15 正因如此，造成 `cases_both_passed=1` 与 `turn2_passed=0` 同真。
        "both_passed": len(turn_passes) == EXPECTED_TURNS and all(turn_passes),
    }


def turn_attribution(run: Any) -> dict[str, Any]:
    """turn 级归因四键的**纯投影**（U-162；不读图、不编值）。

    为什么必须有：r2 的 15 条里 8 条 turn2 收口 `refuse`，而 turn 记录此前只有
    `terminal_event` 与 `plan_summary` —— 「意图层判拒 / 链接层无候选 / plan 阻塞 /
    闸门拒」四者盘上不可判（单轮 record 的 `intent_detail` 也到不了 turn 级）。
    缺属性一律回 `None` 或空，**不编默认值**：空 == 本次没这项信息。
    """
    detail = getattr(run, "intent_detail", None)
    return {
        "terminal_code": getattr(run, "terminal_code", None),
        "refusal_reason": getattr(run, "refusal_reason", None),
        "intent_detail": dict(detail) if isinstance(detail, Mapping) else {},
        "nodes": tuple(getattr(run, "nodes", ()) or ()),
        # 🔴 U-166：执行侧证据两键（SQL 原文与脱敏错误类别）。没有它们，
        # `SQL_SYNTAX_ERROR` 到底是「模型写错语法」还是「方言错配（postgres 风味跑在
        # SQLite 沙箱）」不可判 —— r5/r6/r7 三批分别 2/2/3 条，`mt06` 的 turn1 与 turn2
        # 在 r7 均为该码、repair 三轮后 error_out。
        "sql_text": str(getattr(run, "sql_text", "") or ""),
        "exec_error_class": getattr(run, "exec_error_class", None),
        "gate1_reject_rule": getattr(run, "gate1_reject_rule", None),  # U-168
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
    # U-160：不直接信记录里的 `both_passed`（旧件按错口径写的）—— 统一按 `turn_passes`
    # 重算，保证 turn1 / turn2 / both 由同一份明细派生；未跑完的单列，不算通过。
    both = sum(
        1
        for record in records
        if len(record.get("turn_passes") or []) == EXPECTED_TURNS
        and all(record.get("turn_passes") or [])
    )
    incomplete = sum(
        1 for record in records if len(record.get("turn_passes") or []) != EXPECTED_TURNS
    )
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
        "cases_incomplete": incomplete,
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
