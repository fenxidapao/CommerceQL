"""出口节点 `error_out` —— 构造失败终态（07 §5.3 行 17）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、本节点是 **`exec_error` → 错误码的唯一映射点**
--------------------------------------------------------------------------
`route_after_execute` 只回答"可修 / 不可修"，**不回答**该落哪个码（§5.4 原文：
"否则 → `error_out(EXEC_TIMEOUT / SQL_SYNTAX_ERROR / DB_UNAVAILABLE)`" —— 括号里的三个码
是**本节点**的职责）。把映射放在这里而不是 `execute`，是因为：

* `execute` 若也判一次"该不该进 repair"，就有**两个**判据来源（`execute` 一个、边一个），
  漂移的表现是"节点认为该修、边认为该报错" —— 两边都不报错，只是行为不一致；
* 于是 `execute` 只写脱敏摘要（N-11），码的**唯一**决定点在出口（可单测）。

映射表（`app/exec/errors.py` 的类别 → 附录 A §A.11 的码）：

| `error_class` | 码 |
|---|---|
| `timeout` | `EXEC_TIMEOUT` |
| `db_unavailable` | `DB_UNAVAILABLE` |
| `resource_exceeded` | `EXEC_RESOURCE_EXCEEDED` |
| `syntax_error` / `unknown_column` / `unknown_table` / `type_mismatch` / `unknown_function` | `SQL_SYNTAX_ERROR` |
| `permission` | **不在本表** —— 它的终态是 `refuse(out_of_scope)`，已由 `execute` 直接落 `refuse`（W2D 明文） |

--------------------------------------------------------------------------
二、`message` / `detail` / `retryable` **不由本节点产出**
--------------------------------------------------------------------------
它们由 `app/api/errors.map_code(...)`（`ErrorMapperPort`，**L5**）产出，而
`app.graph`（L4）**不得 import L5**（importlinter 分层契约）⇒ 由 runner/端点层在发帧时映射。
`events.emissions_for_node` 的 `extras` 就是给这件事留的口子（其 docstring 已注明）。
⚠️ 因此 `error` 帧在"端点未接映射"时会缺这三个字段 —— `events.py` 会如实发"少字段"的帧
并告警，**不编造**文案（U-22）。这条接线属 T5。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.enums import ErrorCode, GateDecision, GateNo, Outcome
from app.graph.nodes._shared import terminal_update, write_audit_pre
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["error_out"]

_log = get_logger(__name__)

#: `exec_error.error_class` → 终态错误码（见 docstring §一）。
_EXEC_CODE: dict[str, ErrorCode] = {
    "timeout": ErrorCode.EXEC_TIMEOUT,
    "db_unavailable": ErrorCode.DB_UNAVAILABLE,
    "resource_exceeded": ErrorCode.EXEC_RESOURCE_EXCEEDED,
    "syntax_error": ErrorCode.SQL_SYNTAX_ERROR,
    "unknown_column": ErrorCode.SQL_SYNTAX_ERROR,
    "unknown_table": ErrorCode.SQL_SYNTAX_ERROR,
    "type_mismatch": ErrorCode.SQL_SYNTAX_ERROR,
    "unknown_function": ErrorCode.SQL_SYNTAX_ERROR,
}

#: 闸门 → 它的拒绝码（兜底用：正常路径上闸门节点自己已落终态）。
_GATE_CODE: dict[GateNo, ErrorCode] = {
    GateNo.AST: ErrorCode.GATE_AST_REJECTED,
    GateNo.POLICY: ErrorCode.GATE_POLICY_REJECTED,
    GateNo.COST: ErrorCode.COST_TOO_HIGH,
}


async def error_out(state: GraphState) -> dict[str, Any]:
    """失败终态（`terminal.event = "error"`）+ 段 1 审计。"""
    update: dict[str, Any] = {}
    if state.get("terminal") is None:
        update = terminal_update(
            state,
            event="error",
            outcome=Outcome.FAILED,
            code=_code_of(state).value,
        )

    if not await write_audit_pre(state, outcome=Outcome.FAILED):
        _log.error(
            "error_audit_missing",
            outcome="terminal_still_sent",
            task_id=str(state.get("task_id")),
            extra_fact="出口路径的段 1 审计未落库；终态不可改（N-08），只能告警 + 登记",
        )
    return update


def _code_of(state: GraphState) -> ErrorCode:
    """错误码（判据顺序即优先级：执行错误 > 闸门拒绝 > 兜底 `INTERNAL`）。"""
    exec_error = state.get("exec_error")
    if isinstance(exec_error, Mapping):
        error_class = str(exec_error.get("error_class") or "")
        mapped = _EXEC_CODE.get(error_class)
        if mapped is not None:
            return mapped
        if error_class:
            _log.error(
                "error_out_unmapped_class",
                outcome="fell_back_to_internal",
                task_id=str(state.get("task_id")),
                error_class=error_class,
                extra_fact="`exec_error.error_class` 不在映射表里 → 落 INTERNAL（不编一个更精确的码）",
            )
        return ErrorCode.INTERNAL

    for gate_no, code in _GATE_CODE.items():
        result = (state.get("gate_results") or {}).get(gate_no)
        decision = getattr(result, "decision", None)
        if decision is not None and decision is GateDecision.REJECT:
            return code
    return ErrorCode.INTERNAL
