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
from app.planner.errors import PlannerError

__all__ = ["plan"]


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
    if blocking:
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
        }
        return update

    payload: Mapping[str, Any] = outcome.state_payload()
    return dict(payload)
