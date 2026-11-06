#!/usr/bin/env python
"""多轮判定口径复算探针（U-154 相邻；零 LLM／零出站／只读输入）。

对象：`eval/olist/results_multiturn_r1.json`（2026-11-06 11:22–11:26 live 批，15 条 × 2 轮）。
问题：报告读数 turn1 **0/15**、turn2 **0/15**。要判这是「模型能力」还是「判定口径」。

已发现的矛盾（本探针把它量化，不改代码、不改冻结集）：
  · `eval/multiturn.py` 模块口径第 3 条写「时间窗：比 `time_range` 的 **ISO 日期字符串**
    （金标右开区间）」；
  · 实现 `compare_expectation()`（同文件 :235-240）对 `time_start` / `time_end` 做的是
    **原始字符串全等**。
  · 实测样本：expect `"2018-01-01"` vs actual `"2018-01-01 00:00:00"` ⇒ 必然不等。
  · 且金标是**右开区间**（`time_end: "2019-01-01"`），图给的是**闭区间**
    （`"2018-12-31 23:59:59"`）⇒ 即使只比日期也仍不等。

三种口径（只重算**时间面**，非时间键沿用记录里的判定）：
  A `exact`         —— 现行实现（原始字符串全等），应与报告 0/15 一致（自校验）
  B `date_only`     —— 只比日期部分 `YYYY-MM-DD`，忽略时分秒
  C `date_semantic` —— B 再叠加右开/闭区间归一：把 `T 23:59:59` 上界抬成次日 00:00:00

⚠️ 只读：不写结果件、不碰冻结集；`--out` 只写本探针自己的 JSON。
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

OLIST_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT = OLIST_DIR / "results_multiturn_r1.json"
TIME_KEYS = ("time_start", "time_end")
CALIBERS = ("exact", "date_only", "date_semantic")

if hasattr(__import__("sys").stdout, "reconfigure"):
    __import__("sys").stdout.reconfigure(encoding="utf-8", errors="replace")


def date_part(value: Any) -> date | None:
    """取 `YYYY-MM-DD` 头部（容忍 `T`/空格分隔与带时分秒）。取不到返回 None。

    用 `date.fromisoformat` 而不是 `datetime.strptime`：后者会造出 naive datetime，
    触发 ruff `DTZ007`；本函数只关心日期部分，不需要时区。
    """
    if not isinstance(value, str):
        return None
    text = value.strip().replace("T", " ")
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def exclusive_upper(value: Any) -> date | None:
    """闭区间上界抬成次日 00:00:00，与右开金标同口径。

    ⚠️ 两种写法都要认：`2018-12-31 23:59:59` 与 `2018-12-31T23:59:59`。
    初版只认空格分隔，T 分隔那 2 条被误判成不等 —— 属探针自身缺陷，已在读数里说明。

    🔻 **纯日期上界（`2018-12-31`）刻意不抬**：它既可能表示右开 `2019-01-01`，也可能就是
    闭区间当天；口径未定 ⇒ 本探针**不猜**，保持不抬，并在输出里单列条数交由人判。
    """
    day = date_part(value)
    if day is None:
        return None
    text = str(value).strip().replace("T", " ")
    return day + timedelta(days=1) if text.endswith("23:59:59") else day


def time_ok(key: str, expected: Any, actual: Any, caliber: str) -> bool:
    if caliber == "exact":
        return expected == actual
    if key == "time_start":
        left, right = date_part(expected), date_part(actual)
    else:
        left, right = exclusive_upper(expected), exclusive_upper(actual)
    return left is not None and left == right


def rescore(records: list[dict[str, Any]], caliber: str) -> dict[str, Any]:
    """按口径重算每轮是否通过；非时间键沿用记录里的 `ok`（不重判）。"""
    t1 = t2 = both = 0
    cases: list[dict[str, Any]] = []
    for record in records:
        passes: list[bool] = []
        bad_fields: list[list[str]] = []
        for turn in record.get("turns") or []:
            fields = (turn.get("comparison") or {}).get("fields") or {}
            ok = True
            bad: list[str] = []
            for key, item in fields.items():
                item = item or {}
                good = (
                    time_ok(key, item.get("expected"), item.get("actual"), caliber)
                    if key in TIME_KEYS
                    else bool(item.get("ok"))
                )
                if not good:
                    bad.append(key)
                ok = ok and good
            passes.append(ok)
            bad_fields.append(bad)
        cases.append(
            {
                "case_id": record.get("case_id"),
                "terminal_events": [t.get("terminal_event") for t in record.get("turns") or []],
                "passes": passes,
                "bad_fields": bad_fields,
            }
        )
        if passes and passes[0]:
            t1 += 1
        if len(passes) > 1 and passes[1]:
            t2 += 1
        if passes and all(passes):
            both += 1
    return {
        "caliber": caliber,
        "n_cases": len(records),
        "turn1_passed": t1,
        "turn2_passed": t2,
        "cases_both_passed": both,
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多轮判定口径复算探针（零 LLM）")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--out", type=Path, default=OLIST_DIR / "probe_multiturn_caliber.json")
    args = parser.parse_args(argv)

    payload = json.loads(args.report.read_text(encoding="utf-8"))
    records = [r for r in (payload.get("records") or []) if isinstance(r, dict)]
    reported = payload.get("summary") or {}

    result = {
        "schema": "U154_MULTITURN_CALIBER_PROBE/v1",
        "source_report": str(args.report),
        "reported_summary": reported,
        "docstring_claim": "时间窗比 ISO 日期字符串（金标右开区间）—— eval/multiturn.py:16",
        "implementation": "compare_expectation 对 time_start/time_end 做原始字符串全等 —— eval/multiturn.py:235-240",
        "calibers": [rescore(records, caliber) for caliber in CALIBERS],
    }

    print(f"reported: turn1={reported.get('turn1_passed')} turn2={reported.get('turn2_passed')} "
          f"both={reported.get('cases_both_passed')} n={reported.get('n_cases')}")
    for block in result["calibers"]:
        print(
            f"{block['caliber']:>14}: turn1={block['turn1_passed']}/{block['n_cases']} "
            f"turn2={block['turn2_passed']}/{block['n_cases']} "
            f"both={block['cases_both_passed']}/{block['n_cases']}"
        )
    semantic = result["calibers"][-1]
    still_fail = [c for c in semantic["cases"] if not all(c["passes"])]
    print(f"under date_semantic still failing: {len(still_fail)}")
    for case in still_fail:
        print(f"  {case['case_id']} passes={case['passes']} events={case['terminal_events']} bad={case['bad_fields']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
