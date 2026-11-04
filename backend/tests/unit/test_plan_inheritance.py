"""B6（U-154）多轮条件继承的纯函数契约。

只测确定性规则，不碰 LLM/Redis/图：
- 只在**追问线索**出现时启用；
- **只补空位**，本轮计划已有值不被历史覆盖；
- `metrics` / `assets` 不继承（摘要里没有 caliber / 关联键，拼半份计划比缺字段更危险）。
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.contracts import TokenUsage
from app.core.enums import Role
from app.graph.nodes import plan as plan_node
from app.planner.engine import LlmCallMeta, PlanOutcome
from app.planner.inherit import inherit_plan, looks_like_follow_up
from app.planner.schemas import Plan

_HISTORY = {
    "metrics": ["gmv"],
    "dimensions": ["region"],
    "filters": ["region = '华东'"],
    "grain": "day",
    "time_range": {"start": "2026-08-01", "end": "2026-08-31"},
    "order_by": ["gmv desc"],
    "limit": 10,
}


def _plan(**over: Any) -> Plan:
    body: dict[str, Any] = {
        "metrics": [{"name": "gmv", "caliber": "sum(amount)"}],
        "dimensions": [],
        "filters": [],
        "grain": None,
        "time_range": {"start": None, "end": None},
        "order_by": [],
        "limit": None,
        "assets": [{"asset": "v_order_paid", "join_key": None}],
        "output_columns": ["gmv"],
        "blocking_issues": [],
    }
    body.update(over)
    return Plan.model_validate(body)


def test_follow_up_cues_are_detected() -> None:
    assert looks_like_follow_up("那华东区呢？")
    assert looks_like_follow_up("再看一下同比")
    assert not looks_like_follow_up("2018 年 GMV 是多少")


def test_long_question_is_not_treated_as_follow_up() -> None:
    assert not looks_like_follow_up("那请把 2018 年每个季度华东区所有品类的 GMV 都按天拆开并排序")


def test_follow_up_fills_only_empty_fields() -> None:
    result = inherit_plan(_plan(), _HISTORY, "那华东区呢？")
    assert result.fields == ("time_range", "dimensions", "filters", "order_by", "grain", "limit")
    assert result.plan.time_range.start == "2026-08-01"
    assert result.plan.time_range.end == "2026-08-31"
    assert result.plan.dimensions == ["region"]
    assert result.plan.filters == ["region = '华东'"]
    assert result.plan.grain == "day"
    assert result.plan.order_by == ["gmv desc"]
    assert result.plan.limit == 10


def test_current_plan_wins_over_history() -> None:
    current = _plan(
        dimensions=["city"],
        filters=["pay_status = 'paid'"],
        grain="month",
        time_range={"start": "2026-09-01", "end": "2026-09-30"},
        order_by=["gmv asc"],
        limit=3,
    )
    result = inherit_plan(current, _HISTORY, "那华东区呢？")
    assert result.fields == ()
    assert result.plan is current


def test_metrics_and_assets_are_never_inherited() -> None:
    current = _plan(metrics=[], blocking_issues=["缺指标"])
    result = inherit_plan(current, _HISTORY, "它呢？")
    assert result.plan.metrics == []
    assert [asset.asset for asset in result.plan.assets] == ["v_order_paid"]


def test_independent_question_ignores_history() -> None:
    result = inherit_plan(_plan(), _HISTORY, "2018 年 GMV 是多少")
    assert result.fields == ()
    assert result.plan.dimensions == []


def test_missing_history_is_a_noop() -> None:
    plan = _plan()
    result = inherit_plan(plan, None, "那华东区呢？")
    assert result.fields == ()
    assert result.plan is plan


def test_multiturn_dataset_follow_ups_match_the_heuristic() -> None:
    """15 条多轮集里，除显式 `reset` 外，第二问都必须被识别为追问。"""
    path = Path(__file__).resolve().parents[3] / "eval" / "dataset_multiturn_v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["n_cases"] == len(data["cases"]) == 15
    for case in data["cases"]:
        second = case["turns"][1]["question"]
        expected = case["follow_up_type"] != "reset"
        assert looks_like_follow_up(second) is expected, (case["case_id"], second)


def test_plan_node_writes_the_merged_plan_back_to_state() -> None:
    """接线段：`plan` 节点必须把合并结果写进 `plan` / `plan_summary`，下游才看得到。"""

    class _Planner:
        async def plan_for(self, identity: Any, *, normalized_question: str) -> PlanOutcome:
            current = _plan()
            return PlanOutcome(
                plan=current,
                plan_summary=current.to_summary(),
                meta=LlmCallMeta(
                    model="fake",
                    prompt_version="plan_v1",
                    tokens=TokenUsage(),
                    cost_cny=Decimal(0),
                ),
                attempts=1,
                latency_ms=0,
            )

    state: dict[str, Any] = {
        "trace_id": "tr",
        "task_id": "tk",
        "session_id": "se",
        "tenant_id": "T_A",
        "user_id": "u",
        "role": Role.ANALYST,
        "scope_claims": (),
        "shop_ids": (),
        "normalized_question": "那华东区呢？",
        "history_plan": _HISTORY,
    }
    from app.graph.context import RunContext, clear_run_context, set_run_context

    token = set_run_context(RunContext(SimpleNamespace(planner=_Planner())))  # type: ignore[arg-type]
    try:
        update = asyncio.run(plan_node.plan(state))  # type: ignore[arg-type]
    finally:
        clear_run_context(token)

    assert update["plan"]["dimensions"] == ["region"]
    assert update["plan"]["time_range"] == {"start": "2026-08-01", "end": "2026-08-31"}
    assert update["plan_summary"]["dimensions"] == ["region"]
