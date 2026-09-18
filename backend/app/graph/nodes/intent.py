"""节点 3 `intent` —— 四分类 + 拒答/开放分析识别（07 §5.3 行 3）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、合并档下本节点**是空操作**，而这不是"偷懒"
--------------------------------------------------------------------------
`normalize` 走 `understand()` 时已经把组 3（`intent` / `intent_detail`）写好了
（§16.1 手段 1 的代价与收益都在那一次调用里）。此时本节点**不能**再调一次
`classify_intent()` —— 那是同一判定的第二份结果（可能不同！），而且白烧一次调用与 ~1.5s。

判据只有一条、且无歧义：**`state.intent` 已被设置 ⟺ 合并档已经产出过意图**
（`initial_state()` 不写 `intent`，除 `normalize` 合并档外只有本节点会写它）。

⚠️ 为什么"空操作"仍然必须是一个**具名节点**（不能从图里删掉、也不能把边直接连到 `link`）：
1. §5.3 的 16 节点对账基线（`tests/graph_snapshot/` 与 08 §3.6"16 个节点"）按节点名核对；
2. 07 §5.6 的 `stage=intent` **挂在本节点之后**（"`intent` 完成后，耗时含 `normalize`"）——
   删掉它就少一个发射点，"17 个发射点"这条 DoD 立刻不成立；
3. 单跑路径（`GraphDeps.merged_understand=False`）下它就是真正的意图分类节点。

--------------------------------------------------------------------------
二、单跑路径的计时（C-04 的键集缺口）
--------------------------------------------------------------------------
`LatencyKey` 是恰好 8 个（C-04 要求与 `audit_log.latency_ms` 键集完全一致），
里面**没有** `intent` 键。07 §5.6 又说 `stage=intent` 的耗时"**含 `normalize`**"。
⇒ 单跑路径下，本节点的耗时也累加进 `LatencyKey.NORMALIZE`（与合并档同口径：
"理解阶段的合计耗时"）。这不是发明键，是给出唯一可行的归属。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import LatencyKey
from app.graph.nodes._shared import (
    deps_of,
    identity_of,
    llm_error_update,
    node_latency,
    rc,
)
from app.graph.state import GraphState
from app.llm.errors import LlmError
from app.planner.errors import PlannerError
from app.planner.schemas import IntentKind

__all__ = ["intent"]


async def intent(state: GraphState) -> dict[str, Any]:
    """意图分类（合并档下为空操作；单跑路径下真调 `classify_intent`）。"""
    if state.get("intent") is not None:
        # 合并档：`normalize` 已经产出组 3。不发事件、不写 state、不再调模型。
        return {}

    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    question = str(state.get("normalized_question") or state.get("raw_question") or "")

    try:
        with node_latency(LatencyKey.NORMALIZE):
            outcome = await deps.planner.classify_intent(identity, question)
    except LlmError as exc:
        return llm_error_update(state, exc, stage="intent")
    except PlannerError:
        # 单跑路径下的"意图不可用"：与合并档同款落法 —— 拒绝并如实写 reason_code。
        from app.core.enums import Outcome, RefuseReason
        from app.graph.nodes._shared import terminal_update

        update: dict[str, Any] = {
            "intent": IntentKind.REFUSE.value,
            "intent_detail": {
                "reason_code": "intent_unavailable",
                "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
            },
        }
        update.update(
            terminal_update(
                state,
                event="refuse",
                outcome=Outcome.REFUSE,
                reason=RefuseReason.NO_DATA_ASSET.value,
            )
        )
        return update

    context.record_usage(outcome.meta.tokens, outcome.meta.cost_cny)
    payload = dict(outcome.state_payload())
    # 单跑路径下 `understand()` 的占位语义不适用：只取组 3 两键，别把组 2 覆盖成空值
    # （`classify_intent` 的 `state_payload()` 里 `normalized_question` 是原样问题、
    #  `time_range=None`、`resolved_terms=()` —— 拿它覆盖会**静默丢掉**归一化结果）。
    return {"intent": payload["intent"], "intent_detail": payload["intent_detail"]}
