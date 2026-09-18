"""节点 15 `audit_supp` —— **非阻断**补充审计（07 §5.3 行 15 / §5.3.1 段 2）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、失败**不阻断**，且**不抛**（§14.2 G2）
--------------------------------------------------------------------------
段 2 的语义是"结果已经下发过了，此时抛异常只会把一次成功的查询变成 500"。
`AuditWriter.write_supp` 已经做到"自身不抛"（连 `AuditSchemaMismatch` 都不抛，只打日志），
本节点因此**不**再加一层 try —— 但必须覆盖**取消路径**（§14.2 E7 / §18.3 步 5）：
那个覆盖发生在调用方（SSE 端点），见 `AuditWriter.write_supp` 的 docstring。本节点能做的
只是"不因自身原因抛异常"，从而让端点敢于在 `finally` 里调它。

--------------------------------------------------------------------------
二、`complete` 的终态**由本节点写**（成功路径的收口）
--------------------------------------------------------------------------
07 §5.6："`complete` | **`audit_supp` 之后**"。`complete` **不是**出口节点发的
（出口三节点走 clarify/refuse/error）。本节点写 `terminal(event="complete")` 的目的不是发事件
（事件由 `events.emissions_for_node(AUDIT_SUPP)` 产出），而是让成功路径也经过
`route_terminal` 这一个收口点 —— **两处收口就是两套幂等语义**。

⚠️ 转异步路径（§5.4 `route_after_gate3` 的 async 分支，P0 不可达）也会走到本节点，
此时它写的就是那一轮的终态（见 `edges.py` §二-4）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import orjson

from app.core.enums import LatencyKey, Outcome
from app.graph.nodes._shared import rc, terminal_update
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["audit_supp"]

_log = get_logger(__name__)


async def audit_supp(state: GraphState) -> dict[str, Any]:
    """段 2 审计（非阻断）+ 写 `complete` 终态。"""
    context = rc()
    identity = _identity(state)
    terminal = terminal_update(state, event="complete", outcome=Outcome.SUCCESS)

    payload: dict[str, Any] = {
        "input_tokens": int((state.get("tokens") or {}).get("input", 0)),
        "output_tokens": int((state.get("tokens") or {}).get("output", 0)),
        "cache_hit_tokens": int((state.get("tokens") or {}).get("cache_hit", 0)),
        "cost_cny": _decimal(state.get("cost_cny")),
        # 段 2 的 `latency_ms_present` = **present 阶段**耗时（段 1 的 `latency_ms` 是下发前快照）。
        "latency_ms_present": int(context.latency_ms().get(LatencyKey.PRESENT.value, 0)),
        "chart_type": _chart_type(state),
        "insight_hash": _insight_hash(state),
        "degradations": [
            orjson.dumps(item, default=str).decode() for item in (state.get("degradations") or ())
        ],
    }
    try:
        await context.deps.audit.write_supp(identity, payload)
    except Exception as exc:
        _log.error(
            "audit_supp_failed",
            outcome="non_blocking",
            task_id=str(state.get("task_id")),
            error_type=type(exc).__name__,
        )

    return terminal


def _identity(state: GraphState) -> Any:
    from app.graph.context import identity_from_state

    return identity_from_state(state)


def _decimal(value: Any) -> Decimal:
    """`cost_cny` 列是 `numeric`：传 `Decimal`，**不传 `float`**（二进制误差会让分数不可比）。"""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def _chart_type(state: GraphState) -> str | None:
    chart = state.get("chart_spec")
    if isinstance(chart, Mapping):
        value = chart.get("chart_type")
        return None if value is None else str(value)
    return None


def _insight_hash(state: GraphState) -> str | None:
    """`insight` 摘要哈希（**存哈希不存原文**：审计表不该成为第二份用户可见文案的副本）。"""
    insight = state.get("insight")
    if not isinstance(insight, Mapping):
        return None
    text = insight.get("text")
    if not text:
        return None
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()
