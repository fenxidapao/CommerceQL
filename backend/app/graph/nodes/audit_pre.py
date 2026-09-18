"""节点 13 `audit_pre` —— **阻断性**审计写入（07 §5.3 行 13 / §5.3.1 段 1）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、fail-closed 的边界就在这条边上
--------------------------------------------------------------------------
N-09："审计写入不得晚于结果下发"。落到实现上：段 1 写失败 ⇒ **不得**下发 `data`（`error(INTERNAL)`）。
`AuditWriter.write_pre` 自己**不**提供"关掉 fail-closed"的开关（NFR-3.4，其 docstring 明写理由），
所以这个判断只能在调用点做 —— 就是本节点。

⚠️ 与出口节点的差别（同一段审计，两种后果）：出口节点调 `write_audit_pre` 时终态**已经定了**，
失败只能告警（N-08 不允许改终态）—— 见 `_shared.write_audit_pre` 的 docstring。

--------------------------------------------------------------------------
二、为什么要把 `result_columns` / `row_count` / `truncated` 回写一遍
--------------------------------------------------------------------------
`events.emissions_for_node(AUDIT_PRE, update, extras=...)` 组 `data` 帧时读的是**本节点的
增量**（`update`），而这三个键在 `execute` 时就已写进 state。回写一遍是**刻意的**：
它让"`data` 帧的载荷"完全由本节点的增量决定，runner 不必为了拼一个帧去翻整个 state
（翻 state 会让"该发什么"与"state 里有什么"耦合，而 state 有 11 组字段）。
行数据仍走 extras（体积数据不进 state，见 `execute` 的 docstring §一）。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import ErrorCode, Outcome
from app.graph.nodes._shared import terminal_update, write_audit_pre
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["audit_pre"]

_log = get_logger(__name__)


async def audit_pre(state: GraphState) -> dict[str, Any]:
    """段 1 审计（阻断）。成功后 `data` 才允许下发。"""
    ok = await write_audit_pre(state)
    if not ok:
        _log.error(
            "audit_pre_blocked_data",
            outcome="fail_closed",
            task_id=str(state.get("task_id")),
            extra_fact="段 1 审计未落库 → 不下发结果（N-09）；P0 告警",
        )
        return terminal_update(
            state,
            event="error",
            outcome=Outcome.FAILED,
            code=ErrorCode.INTERNAL.value,
        )

    return {
        "result_columns": tuple(state.get("result_columns") or ()),
        "row_count": int(state.get("row_count", 0)),
        "truncated": bool(state.get("truncated", False)),
    }
