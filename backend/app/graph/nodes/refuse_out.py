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
二、`message` / `suggestions` 是**占位文案**（登记，同 `SHOP_LIMITED_NOTICE` 先例）
--------------------------------------------------------------------------
07 §5.6 规定 `refuse` 的载荷含 `message` / `suggestions[]`，而**文案内容归 06 UI/UX**
（本项目已有先例：`policy_gate.SHOP_LIMITED_NOTICE` 是"固定文案"，内容由实现方暂拟、
登记待 UI/UX 复核）。本节点沿用该先例，按 `reason` 给一份**中性**文案：

* `message` 只陈述"没有可回答的数据"，**不**透露库里有什么、也不暗示"其实是权限问题"
  （后者会制造存在性泄露 —— 与 C-07 的三级披露同一条红线）；
* `suggestions[]` 在 `no_data_asset` 下给"换个问法/收窄范围"这类通用改法
  （`enums.DEFAULT_SUGGESTIONS` 的同类内容，但此处不 import 它：那是错误码侧的常量，
  语义是"原样重试必然失败时该怎么改"，与拒答的"没数据"不是同一件事）。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import Outcome, RefuseReason
from app.graph.nodes._shared import terminal_update, write_audit_pre
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["refuse_out"]

_log = get_logger(__name__)

#: `reason` → 中性文案（占位，待 06 UI/UX 复核 —— 见 docstring §二）。
_MESSAGES: dict[str, str] = {
    RefuseReason.NO_DATA_ASSET.value: "系统里没有能回答这个问题的数据，无法给出结果。",
    RefuseReason.OUT_OF_SCOPE.value: "这个问题涉及的数据范围超出你被授权的范围。",
    RefuseReason.PII_BLOCKED.value: "这个问题会返回受保护的字段，出于安全考虑不能作答。",
    RefuseReason.OPEN_ANALYSIS.value: "这类开放式分析不在本产品的回答范围内。",
}

_SUGGESTIONS: dict[str, tuple[str, ...]] = {
    RefuseReason.NO_DATA_ASSET.value: (
        "可以试着换一个更具体的问法（点明指标与时间范围）",
        "也可以先收窄维度，例如只看某个类目或某个渠道",
    ),
    RefuseReason.OPEN_ANALYSIS.value: (
        "可以把它拆成一个有明确口径的统计问题",
    ),
}
_DEFAULT_SUGGESTIONS: tuple[str, ...] = _SUGGESTIONS[RefuseReason.NO_DATA_ASSET.value]


async def refuse_out(state: GraphState) -> dict[str, Any]:
    """拒答终态（`terminal.event = "refuse"`）+ 段 1 审计。"""
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

    # `message` / `suggestions` 走**本节点的增量**（`events._terminal_payload` 会取它们）；
    # 理由：它们是产品文案，映射点是图内这**一处**（`api/errors` 只映射错误码，不映射拒答）。
    update["message"] = _MESSAGES.get(reason, _MESSAGES[RefuseReason.NO_DATA_ASSET.value])
    update["suggestions"] = list(_SUGGESTIONS.get(reason, _DEFAULT_SUGGESTIONS))

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
