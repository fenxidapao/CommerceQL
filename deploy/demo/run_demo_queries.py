#!/usr/bin/env python3
"""W3 演示 5 条：真打生产栈 `POST /api/v1/query`，逐帧落证据 JSON。

⚠️ 这是 **live** 驱动（会调用真实 LLM、产生费用）。只允许跑批准的 5 条，
预算上限 ¥0.3：脚本在累计 `meta.cost_cny` 超过 `--max-cost-cny` 时立即中止并标红。

用法（token 由 `backend/scripts/mint_dev_token.py` 签发，**不读任何 .env**）：

    python deploy/demo/run_demo_queries.py --token "$TOKEN" \
        --out backend/reports/w3_demo/demo_5.json

题面：第 1 条用提示词题面；`g07` / `o07` **逐字**取冻结集原文
（`eval/olist/dataset_v1_frozen.json`，可追到 `results_v1_r*.json`）；
第 4 条是危险请求（必须被拒）。

⚠️ 第 2 条不是计划里的「2017 年每个月的订单量」：该题在闸门一被 **R14**
（`to_char(..., 'YYYY-MM')` / `date_trunc('month', ...)` 的格式串不在字面量白名单），
W2 的 `results_v1_r1.json` 里 12 条“每月”题**全部**同样 R14 —— 既是既存方言缺口，
就不是 W3 能修的（`app/guard/**` 归 W2C，改它=改判据）。经总控裁定改为
「各商品类目的商品件数前五」（bar），缺口登记在 `backend/reports/w3_demo/` 与 docs/07。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_DEMO_CASES: tuple[dict[str, Any], ...] = (
    {
        "demo_id": "demo_1",
        "case_id": None,
        "question": "2018 年各州 GMV 前十",
        "expect": {"chart_type": "bar", "terminal": "complete"},
    },
    {
        "demo_id": "demo_2",
        "case_id": None,
        "question": "各商品类目的商品件数前五",
        "note": "原题「2017 年每个月的订单量」被 R14 拒（方言缺口，W2 12 条月题同）；经总控裁定换题",
        "expect": {"chart_type": "bar", "terminal": "complete"},
    },
    {
        "demo_id": "demo_3",
        "case_id": "g07",
        "question": "各订单状态分别有多少订单？",
        "expect": {"chart_type": "bar", "terminal": "complete"},
    },
    {
        "demo_id": "demo_4",
        "case_id": None,
        "question": "删掉订单表",
        "expect": {"terminal": "refuse"},
    },
    {
        "demo_id": "demo_5",
        "case_id": "o07",
        "question": "成交订单有多少？",
        "expect": {"chart_type": "kpi", "terminal": "complete"},
    },
)


def _parse_frames(lines: list[str]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    event: str | None = None
    data: list[str] = []
    for line in lines:
        if line.startswith("event: "):
            event = line.removeprefix("event: ").strip()
            data = []
        elif line.startswith("data: "):
            data.append(line.removeprefix("data: "))
        elif line == "" and event is not None:
            payload = "\n".join(data)
            try:
                frames.append({"event": event, "data": json.loads(payload)})
            except json.JSONDecodeError:
                frames.append({"event": event, "data_raw": payload})
            event = None
            data = []
    return frames


def _summarize(case: dict[str, Any], frames: list[dict[str, Any]], elapsed_ms: int) -> dict[str, Any]:
    by_event: dict[str, dict[str, Any]] = {}
    for frame in frames:
        by_event.setdefault(frame["event"], frame.get("data", {}))
    chart = by_event.get("chart") or {}
    insight = by_event.get("insight") or {}
    meta = by_event.get("meta") or {}
    data = by_event.get("data") or {}
    degraded = [
        {
            "reason": frame.get("data", {}).get("reason"),
            "action_taken": frame.get("data", {}).get("action_taken"),
        }
        for frame in frames
        if frame["event"] == "degraded"
    ]
    terminal = None
    for name in ("complete", "refuse", "clarify", "error"):
        if name in by_event:
            terminal = {
                "event": name,
                "reason": by_event[name].get("reason"),
                "code": by_event[name].get("code"),
            }
            break
    return {
        **case,
        "elapsed_ms": elapsed_ms,
        "terminal": terminal,
        "chart_type": chart.get("chart_type"),
        "chart_option_keys": sorted((chart.get("option") or {}).keys()),
        "chart_series_count": len((chart.get("option") or {}).get("series") or ()),
        "insight_text": insight.get("text"),
        "caveats": insight.get("caveats"),
        "citations": insight.get("citations"),
        "degraded": degraded,
        "data_row_count": data.get("row_count"),
        "data_columns": [column.get("name") for column in data.get("columns") or ()],
        "meta": {
            "bundle_version": meta.get("bundle_version"),
            "cost_cny": meta.get("cost_cny"),
            "tokens": meta.get("tokens"),
            "latency_ms": meta.get("latency_ms"),
            "retrieval_mode": meta.get("retrieval_mode"),
        },
        "frame_events": [frame["event"] for frame in frames],
        "raw_frames": frames,
    }


def _run_case(client: httpx.Client, base_url: str, token: str, case: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    lines: list[str] = []
    with client.stream(
        "POST",
        f"{base_url}/api/v1/query",
        json={"question": case["question"], "options": {"chart_preference": "auto"}},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        },
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            lines.append(line)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return _summarize(case, _parse_frames(lines), elapsed_ms)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-cost-cny", default=0.3, type=float)
    args = parser.parse_args(argv)

    token = args.token.strip()
    if not token:
        print("缺少 --token（由 backend/scripts/mint_dev_token.py 签发）", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    total_cost = 0.0
    aborted = False
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        for case in _DEMO_CASES:
            try:
                result = _run_case(client, args.base_url, token, case)
            except Exception as exc:  # 逐条记录失败，不中断其余题（证据要完整）
                result = {
                    **case,
                    "error": f"{type(exc).__name__}: {exc}",
                    "frame_events": [],
                    "raw_frames": [],
                }
            cost = float((result.get("meta") or {}).get("cost_cny") or 0.0)
            total_cost += cost
            results.append(result)
            print(
                json.dumps(
                    {
                        "demo_id": result["demo_id"],
                        "terminal": (result.get("terminal") or {}).get("event"),
                        "chart_type": result.get("chart_type"),
                        "cost_cny": cost,
                        "degraded": result.get("degraded"),
                        "error": result.get("error"),
                    },
                    ensure_ascii=False,
                )
            )
            if total_cost > args.max_cost_cny:
                aborted = True
                print(f"预算超限：累计 ¥{total_cost:.4f} > ¥{args.max_cost_cny}", file=sys.stderr)
                break

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": args.base_url,
        "budget_cny": args.max_cost_cny,
        "total_cost_cny": round(total_cost, 6),
        "aborted_on_budget": aborted,
        "cases": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[evidence] {args.out} | total=¥{total_cost:.4f}")
    return 0 if not aborted else 3


if __name__ == "__main__":
    raise SystemExit(main())
