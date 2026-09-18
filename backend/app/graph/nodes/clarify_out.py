"""出口节点 `clarify_out` —— 构造澄清终态（07 §5.3 行 17）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、出口节点是终态的**构造者**，不只是"转发已定的结论"
--------------------------------------------------------------------------
两条澄清路径**都没有**在到达本节点前设终态（它们只写了状态）：
· `route_after_normalize`：`time_parse_ok is False`（时间表达解析不出唯一窗口）；
· `route_after_bind`：`binding_status = ambiguous`（四层判定判不唯一）。
⇒ 本节点必须把 `clarify` 载荷与终态一起造出来。若已设终态（例如某个节点提前收口），
本节点只补审计、**不覆盖**（N-08：`terminal_update` 内部会拒绝重复设置）。

--------------------------------------------------------------------------
二、文案来源与**缺口登记**
--------------------------------------------------------------------------
| 字段 | 来源 | 缺口 |
|---|---|---|
| `question`（绑定路径） | `binding_ambiguity.prompt` ← W3C 的 `decision.clarify_prompt` | 无 |
| `question`（时间路径） | **无来源** ⇒ 本模块的占位常量 | 🔴 `UnderstandOutcome.clarify_hint` 存在，但 `state_payload()` **没有把它写进 state**（组 3 只有 `intent_detail`）⇒ 模型给的澄清提示在这一版**丢失**。登记：或给组 3 加载体，或让 `clarify_hint` 进 `intent_detail` |
| `options[].label` | **无来源**：`CandidateRef` 只有 `asset_id`（无人类可读标签） ⇒ label 与 value 同值 | 登记：附录 A §A.1.4 示例里的 label 是中文短语（"收货城市"），其来源应是语义包的列注释，而绑定层出参里没有它 |
| `reason` | 字面量（`time_ambiguous` / `ambiguous_field_binding`） | 登记：`reason` 没有枚举（`core/enums.py` 无对应类型），后者的拼写取自附录 A §A.1.4 的示例 |

⚠️ 时间路径的 `question` 与全部 `suggestions`/`message` 均为**占位文案**，遵循
`policy_gate.SHOP_LIMITED_NOTICE` 的既有先例（"07 只规定固定文案，未给内容 —— 精确措辞归 06 UI/UX 复核"）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.enums import Outcome
from app.graph.nodes._shared import terminal_update, write_audit_pre
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["clarify_out"]

_log = get_logger(__name__)

#: 时间澄清的问句（占位，待 06 UI/UX 复核 —— 见 docstring §二）。
_TIME_CLARIFY_QUESTION = "你问的时间范围我不确定，请说得更具体一些（例如「最近 7 天」或「上个月」）。"

#: `reason` 的两个取值（见 docstring §二：无枚举，字面量来自附录 A §A.1.4 的示例）。
_REASON_BINDING = "ambiguous_field_binding"
_REASON_TIME = "time_ambiguous"


async def clarify_out(state: GraphState) -> dict[str, Any]:
    """澄清终态（`terminal.event = "clarify"`）+ 段 1 审计。"""
    update: dict[str, Any] = {}
    if state.get("terminal") is None:
        clarify = _clarify_payload(state)
        update = terminal_update(
            state,
            event="clarify",
            outcome=Outcome.CLARIFY,
            clarify=clarify,
        )

    # 段 1 审计（§5.4 `route_terminal` 的"直接 audit → END"）。⚠️ 此时终态已定（或本轮
    # 已由别处定），审计失败**改不了终态**（N-08）⇒ 只告警（`write_audit_pre` 内部已打 ERROR）。
    if not await write_audit_pre(state, outcome=Outcome.CLARIFY):
        _log.error(
            "clarify_audit_missing",
            outcome="terminal_still_sent",
            task_id=str(state.get("task_id")),
            extra_fact="出口路径的段 1 审计未落库；终态不可改（N-08），只能告警 + 登记",
        )
    return update


def _clarify_payload(state: GraphState) -> dict[str, Any]:
    """`{clarify_id, question, options[], reason}`（07 §5.2 组 11 + §5.6 `clarify` 行）。"""
    ambiguity = state.get("binding_ambiguity")
    if isinstance(ambiguity, dict) and ambiguity.get("options"):
        return {
            "clarify_id": _new_clarify_id(),
            "question": ambiguity.get("prompt") or _TIME_CLARIFY_QUESTION,
            "options": [_option(item) for item in ambiguity["options"]],
            "reason": _REASON_BINDING,
        }
    return {
        "clarify_id": _new_clarify_id(),
        "question": _TIME_CLARIFY_QUESTION,
        "options": [],
        "reason": _REASON_TIME,
    }


def _option(item: Any) -> dict[str, Any]:
    """候选 → 附录 A §A.1.4 的选项形状 `{value, label, asset}`（label 见 docstring §二）。"""
    asset = str(item.get("asset_id")) if isinstance(item, dict) else str(item)
    return {"value": asset, "label": asset, "asset": asset}


def _new_clarify_id() -> str:
    """澄清 ID（`cl_` + 随机段，形状取自附录 A §A.1.4 的示例）。

    ⚠️ 随机而不是派生自 `task_id`：`POST /clarify` 需要**不可猜**的 ID 才能防
    "拿别人的 clarify_id 续跑"（5 分钟过期的 `CLARIFY_EXPIRED` 只减少窗口，不提供授权）。
    ⚠️ **澄清上下文的存储（谁在等哪个澄清）未接线** —— 归 API 层（`POST /clarify` 需要它
    才能校验 `clarify_id` 与 `selected_value`）。已写进本窗口 RELAY。
    """
    return f"cl_{uuid.uuid4().hex[:12]}"
