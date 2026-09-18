"""出口节点 `refuse_out` —— 构造拒答终态（07 §5.3 行 17）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、`reason` 的来源有优先级，且**不猜**
--------------------------------------------------------------------------
拒答的四条来路里，有三条**不设终态**（只写状态），本节点负责收口：

| 来路 | `reason` 从哪来 |
|---|---|
| `route_after_intent`（`intent=refuse` / `open_analysis`） | `state.intent_detail.refuse_kind` ← `PlannerEngine` 的 `UnderstandOutcome`（**模型/规则给出的**，不是我们编的） |
| `route_after_link`（空召回） | 无来源 ⇒ 按 C-12 语义取 `no_data_asset`（召回为空 = 没有可用的数据资产） |
| `route_after_bind`（`unresolved`） | 同上 |
| （已设终态的路径，如 gate2 的 `out_of_scope`） | 不动 `terminal`，只补审计 |

⚠️ 取不到时**兜底为 `no_data_asset`** 而不是"最像的那个"：C-12 的四个取值里，
只有 `no_data_asset` 是"我们确实没有能回答它的东西" —— 其余三个（越权/敏感/开放分析）
各自都有**明确而不重叠**的判据（JWT scope / deny_columns / `open_analysis` 意图），
在没有那些判据时选它们等于把一次"没数据"记成"你没权限"。

--------------------------------------------------------------------------
二、`message` / `suggestions` **不在本节点产出**（映射点在 L5，登记）
--------------------------------------------------------------------------
07 §5.6 规定 `refuse` 的载荷含 `message` / `suggestions[]`，文案内容归 06 UI/UX
（本项目先例：`policy_gate.SHOP_LIMITED_NOTICE`）。映射表住在 `app/api/errors.py`
的 `map_refuse`（与 `map_code` 对称），由 runner 的 `_extras` 侧信道送进帧 ——
**不是**本节点不想给：LangGraph `stream_mode="updates"` 只放行 `GraphState`
schema 键，本节点往增量顶层写的任何文案键都会在到达 `events` 之前被丢弃
（T9 批次②实测）。`reason` 同理走侧信道（从 `_RunTrace` 的累积终态读）。
本节点保留的是**判据**（`_reason_of` 的优先级链）与**终态收口**（if 分支）。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import Outcome, RefuseReason
from app.graph.nodes._shared import terminal_update, write_audit_pre
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["refuse_out"]

_log = get_logger(__name__)


async def refuse_out(state: GraphState) -> dict[str, Any]:
    """拒答终态（`terminal.event = "refuse"`）+ 段 1 审计。

    ⚠️ 上游已设终态时（plan 拒答 / gate2 `out_of_scope` / execute `permission` 等）
    本节点返回**空增量**（只补审计）：终态已在 state，帧上的 `reason` /
    `message` / `suggestions` 由 runner `_extras` 侧信道产出（见模块 docstring §二）。
    """
    terminal = state.get("terminal") or {}
    reason = _reason_of(state, terminal)
    update: dict[str, Any] = {}
    if state.get("terminal") is None:
        update = terminal_update(
            state,
            event="refuse",
            outcome=Outcome.REFUSE,
            reason=reason,
        )

    if not await write_audit_pre(state, outcome=Outcome.REFUSE, refusal_reason=reason):
        _log.error(
            "refuse_audit_missing",
            outcome="terminal_still_sent",
            task_id=str(state.get("task_id")),
            extra_fact="出口路径的段 1 审计未落库；终态不可改（N-08），只能告警 + 登记",
        )
    return update


def _reason_of(state: GraphState, terminal: Any) -> str:
    """拒答原因（优先级见 docstring §一）。"""
    if isinstance(terminal, dict) and terminal.get("reason"):
        return str(terminal["reason"])
    detail = state.get("intent_detail")
    if isinstance(detail, dict) and detail.get("refuse_kind"):
        return str(detail["refuse_kind"])
    return RefuseReason.NO_DATA_ASSET.value
