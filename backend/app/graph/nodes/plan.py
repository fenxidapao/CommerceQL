"""节点 5 `plan` —— 生成结构化查询计划（07 §5.3 行 5）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、入参 `normalized_question` 是**必需的**，且必须原样下传
--------------------------------------------------------------------------
W3B 的接线硬约束（`RELAY §给 W4`）：`plan_for(ctx, *, normalized_question=...)` 的
`normalized_question` 是**归一化后**的问题（§10.5 ③"归一化后的用户问题"才是允许出站的形态）。
本节点**不**用 `raw_question` 兜底：拿原始问题去调 = 让未归一化文本出站，
且时间词/别名没被替换，计划的口径会与后续 `gen_sql` 不一致。
⇒ 缺失即 fail-fast（那是 `normalize` 没跑或没写组 2，属图缺陷）。

--------------------------------------------------------------------------
二、`blocking_issues` 的处置（07 未写明 —— 本窗口自定并登记）
--------------------------------------------------------------------------
`Plan` 有 `blocking_issues`（模型的"我做不到"声明，`_either_plan_or_blocked` 校验
"要么有计划、要么有阻塞项"），而 §5.3/§5.4 只写了"JSON 修复用尽 → 模板 → refuse"，
**没有**写 `blocking_issues` 的去向。本窗口的处置（登记待架构裁决）：

| 情形 | 判定 | 依据 |
|---|---|---|
| 模型的**输出不可用**（JSON 修复用尽） | `degraded(plan_generation_failed, template_only)` → `refuse` | §5.3 行 5 明文 |
| 模型**给出了** `blocking_issues` | 直接 `refuse(no_data_asset)`，**不发 degraded** | 它是产品结论（"这问题需要的数据不在语义层"），不是降级 —— 发 `degraded` 会把"库没有这张表"记成"系统变慢了"，归因方向完全错 |

C-12 的 `RefuseReason` 四值里没有"计划阻塞"槽位，取最接近的 `no_data_asset`（同
`normalize` 的已知近似，已登记）。

🔴 **U-163（2026-11-09）修订**：上表第二行的「直接 `refuse`」现在多一个前置条件 ——
**先跑 `inherit_plan`，再判阻塞是否致命**。原顺序把继承排在阻塞判定之后
（`:117-122`），模型一旦自陈阻塞，上一轮条件根本没机会参与判断；r5 全量 15 条里
**10 条 turn2** 就是这样死的（`intent_detail.reason_code=plan_blocked`，原文
「缺少分组维度与对比对象……无法确定 grain 与输出列」—— 而那些恰是 `inherit_plan`
能补的字段）。判定收在纯函数 `_blocking_is_fatal()`：**继承补齐任一字段 ⇒ 阻塞不再
致命**（并在日志里留一手证据）；**没有继承可补时仍按原样拒答**，不放松。
⚠️ 不按 `blocking_issues` 的文本做匹配：那是模型自由文本、非闭集，按文本猜口径就是
把"猜"写成"判据"。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.enums import ActionTaken, DegradedReason, LatencyKey, Outcome, RefuseReason
from app.core.errors import ContractViolationError
from app.graph.nodes._shared import (
    deps_of,
    identity_of,
    llm_error_update,
    node_latency,
    rc,
    terminal_update,
)
from app.graph.state import GraphState
from app.llm.errors import LlmError
from app.obs.logging import get_logger
from app.planner.errors import PlannerError
from app.planner.inherit import InheritanceResult, inherit_plan

__all__ = ["plan"]

_log = get_logger(__name__)


def _blocking_is_fatal(
    blocking: tuple[str, ...], inherited: InheritanceResult | None
) -> bool:
    """阻塞项是否仍然致命（U-163 的判据，纯函数、可单测）。

    改前是「只要有 `blocking_issues` 就拒答」，而 `inherit_plan` 排在判定之后 ⇒
    模型一自陈阻塞，上一轮条件就没机会参与。现在：**上一轮摘要已补齐任一字段**
    （`inherited.fields` 非空）时阻塞不再致命 —— 模型说缺的"分组维度 / 粒度 /
    时间窗"正是继承能补的那些；**没有继承可补时仍拒答**，不放松口径。

    ⚠️ 不判断 `blocking_issues` 的文本内容：那是模型自由文本、非闭集，按文本匹配
    等于靠字符串猜口径。
    """
    if not blocking:
        return False
    return not (inherited is not None and inherited.fields)


async def plan(state: GraphState) -> dict[str, Any]:
    """计划生成 → 组 5 的 `plan` / `plan_summary`（+ N-19 的版本字段）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    question = str(state.get("normalized_question") or "")
    if not question:
        raise ContractViolationError(
            "`plan` 拿不到 `normalized_question` —— `normalize` 没写组 2。"
            "用 `raw_question` 兜底会让未归一化文本出站（§10.5 ③），且时间口径与后续节点不一致",
            detail={"has_raw_question": bool(state.get("raw_question"))},
        )

    try:
        with node_latency(LatencyKey.PLAN):
            outcome = await deps.planner.plan_for(identity, normalized_question=question)
    except LlmError as exc:
        # `LlmRefused` 在 `llm_error_update` 内部最先分流（产品结论 ≠ 故障）。
        return llm_error_update(state, exc, stage="plan")
    except PlannerError as exc:
        context.report_degraded(
            DegradedReason.PLAN_GENERATION_FAILED,
            ActionTaken.TEMPLATE_ONLY,
            {
                "stage": "plan",
                "error": type(exc).__name__,
                "attempts": getattr(exc, "attempts", None),
            },
        )
        return terminal_update(
            state,
            event="refuse",
            outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )

    context.record_usage(outcome.meta.tokens, outcome.meta.cost_cny)

    blocking = tuple(outcome.plan.blocking_issues)
    #: 🔴 U-163：**继承要排在阻塞判定之前**（原顺序见模块 docstring §二 的修订段）。
    history_plan = state.get("history_plan")
    inherited = (
        inherit_plan(outcome.plan, history_plan, question)
        if isinstance(history_plan, Mapping)
        else None
    )

    if _blocking_is_fatal(blocking, inherited):
        # 见模块 docstring §二 的第二行：产品结论，不降级。
        update = terminal_update(
            state,
            event="refuse",
            outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )
        # ⚠️ **不**把 `plan` 写回 `None`：计划是有的（只是模型声明了阻塞项），
        # 抹掉它会让审计里"为什么拒答"少掉唯一的一手证据（`blocking_issues` 就在计划里）。
        # 去向由 `state.terminal` 决定（`route_after_plan` 先看终态），不靠 plan 是否为空。
        update["intent_detail"] = {
            "reason_code": "plan_blocked",
            "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
            "blocking_issues": list(blocking),
            "history_inherited_fields": list(inherited.fields)
            if inherited is not None
            else [],
        }
        return update

    if blocking:
        # 走到这里 = 有阻塞项，但上一轮摘要已补齐字段 ⇒ 不再致命；留一手证据供审计。
        _log.info(
            "plan_blocked_resolved_by_history",
            task_id=identity.task_id,
            fields=list(inherited.fields) if inherited is not None else [],
            extra_fact=(
                "模型自陈 blocking_issues，但上一轮摘要已补齐相关字段 ⇒ 继续 bind，不在此处拒答"
            ),
        )

    payload: dict[str, Any] = dict(outcome.state_payload())
    #: 🔴 B6（U-154）：上一轮脱敏计划摘要 → **只补本轮空位**（时间窗/维度/筛选/粒度/排序/上限）。
    #: 继承结果写回本轮的 `plan` / `plan_summary`，下游 `bind` 与 `gen_sql` 读到的就是合并后的计划；
    #: `history_plan` 本身**不出站**（不在 `PROMPT_ALLOWED_FIELDS`）。
    #: 🔴 U-163：继承结果在上方**已算过一次**（要赶在阻塞判定之前），此处复用，不重复调用。
    if inherited is not None and inherited.fields:
        payload["plan"] = inherited.plan.model_dump()
        payload["plan_summary"] = inherited.plan.to_summary().model_dump()
        _log.info(
            "history_plan_inherited",
            task_id=identity.task_id,
            fields=list(inherited.fields),
            extra_fact="多轮追问：本轮计划缺失的条件由上轮摘要补齐（只补空位，不覆盖本轮）",
        )
    return payload
