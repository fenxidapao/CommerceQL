"""节点 7 `gen_sql` —— 计划 → SQL（07 §5.3 行 7）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、`complex_query` 在 P0 **恒 False** ⇒ `gen_sql_complex` 档在请求路径上不可达（登记）
--------------------------------------------------------------------------
U-67 把 L3+ 生效档定为 `GEN_SQL_COMPLEX = flash 非思考 + 3.0s`，但**谁判"这是 L3+ 复杂查询"**
在 07 / PRD 里都没有规则。W3B 落了一个**自设启发式** `planner.engine._looks_complex(plan)`
（`_COMPLEX_HINTS`：排名/占比/同比/环比/累计/增长率/top/rank/window/row_number/partition），
并明确登记"这是一个自设启发式，必须被登记"。

🔴 但它是**模块私有函数**（`_` 前缀、不在 `planner.__all__` 里），`sql_for(...)` 也**不调用它**
而是把判定留给调用方 ⇒ 「难度判定」这件事目前**没有合法的调用面**。本窗口不：
· 不 import 私有名（跨窗口依赖私有 API = 下次它改名就是静默失效）；
· 不在节点里重抄一份关键词表（第二份真相，两份必然漂移 —— 正是 U-18 的教训）。
⇒ P0 的处置：`complex_query=False`，并把「请 W3B 导出 `looks_complex`（或给 `GraphDeps`
一个档次开关）」写进本窗口 RELAY。**后果如实说明**：U-67 标定的 `gen_sql_complex` 档
在 P0 请求路径上没有触发点（它只在直接调 `PlannerEngine.sql_for(complex_query=True)` 时生效）。

--------------------------------------------------------------------------
二、`sql_candidates` 只写**选中项**（§5.2.1 的体积规则）
--------------------------------------------------------------------------
`SqlOutcome.state_payload()` 会把**全部** N 路候选写进 `sql_candidates`，而 07 §5.2.1 明写
"体积字段：**只保留选中项** → `sql_text`"。本节点因此覆盖该键，只写首选候选；
其余候选仍可在 `SqlOutcome` 里拿到（离线评测用），但**不进 state**。
后面没有任何节点需要它们（`repair` 走的是"计划 + 脱敏错误摘要"，N-17 明令**不给**失败 SQL）。
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
from app.planner.schemas import Plan

__all__ = ["gen_sql"]


async def gen_sql(state: GraphState) -> dict[str, Any]:
    """SQL 生成 → 组 6。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    question = str(state.get("normalized_question") or "")
    plan_payload = state.get("plan")
    if not isinstance(plan_payload, Mapping):
        raise ContractViolationError(
            "`gen_sql` 拿不到结构化计划 —— 图连线的顺序被改了",
            detail={"plan_type": type(plan_payload).__name__},
        )
    plan = Plan.model_validate(dict(plan_payload))

    try:
        with node_latency(LatencyKey.GEN_SQL):
            outcome = await deps.planner.sql_for(
                identity,
                normalized_question=question,
                plan=plan,
                candidates=deps.sql_candidates,
                # 见模块 docstring §一：难度判定没有合法调用面 ⇒ P0 恒走 `gen_sql`。
                complex_query=False,
            )
    except LlmError as exc:
        return llm_error_update(state, exc, stage="gen_sql")
    except PlannerError as exc:
        context.report_degraded(
            DegradedReason.LLM_UNAVAILABLE,
            ActionTaken.TEMPLATE_ONLY,
            {
                "stage": "gen_sql",
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

    if outcome.primary is None:
        # 模型给了 `blocking_issues` 而没给 SQL —— 与 `plan` 节点同款处置（产品结论，不降级）。
        update = terminal_update(
            state,
            event="refuse",
            outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )
        update["intent_detail"] = {
            "reason_code": "sql_blocked",
            "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
            "blocking_issues": list(outcome.blocking_issues),
        }
        return update

    primary = outcome.primary
    update = dict(outcome.state_payload())
    # §5.2.1：体积字段只留选中项（见模块 docstring §二）。
    update["sql_candidates"] = (primary.model_dump(),)
    if len(outcome.candidates) < outcome.requested:
        # `SqlOutcome` 明文说"不把它伪装成降级事件"（`DegradedReason` 里没有"路数不足"）——
        # 故这里只落一个审计可见的事实，不发 `degraded`。
        update["linking_stats"] = {
            "sql_candidates_requested": outcome.requested,
            "sql_candidates_returned": len(outcome.candidates),
        }
    return update
