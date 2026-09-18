"""节点 16 `repair` —— 有界纠错（07 §5.3 行 16，≤2 轮 / NFR-2.4）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、纠错输入**只有**"计划 + 脱敏错误摘要"（N-17）
--------------------------------------------------------------------------
`repair_sql(ctx, *, normalized_question, plan, error_digest)` **拿不到**失败的那条 SQL ——
资产原文的理由是"乱改会产出一条看起来能跑但算错的 SQL，那比失败更危险"。
⇒ `error_digest` 取 `state.exec_error["llm_hint"]`（W2D 明文："已备好，**不要**自己再造提示语"）。
它缺失时（`llm_hint is None`：不可修类）**不该走到本节点** —— 条件边已按
`REPAIRABLE_CLASSES` 判过；真到了这里就 fail-fast（说明两条判据漂移了）。

--------------------------------------------------------------------------
二、纠错后**必须重过全部闸门**（§5.3 行 16 / N-17）
--------------------------------------------------------------------------
`route_after_repair` 恒 → `gate1_ast`。"它只是小改"是模型的声明，不是事实：
新 SQL 与首次生成在**安全面上等价**，跳过闸门等于给模型一条绕过审计的通道。

--------------------------------------------------------------------------
三、`repair_round` 的写法：**本节点自增**（并发安全）
--------------------------------------------------------------------------
`state.repair_round` 没有 reducer，节点返回的增量是**覆盖**。自增而不是"读旧+1"写在别处：
本节点是唯一写它的地方 ⇒ 不会有两个来源互相覆盖（`gate_update` 同款问题，此处天然不适用）。

--------------------------------------------------------------------------
四、§5.3 注的"相同 SQL 直接跳出 repair"**未落地**（如实登记）
--------------------------------------------------------------------------
原文："`repair` 后的重执行必须换新 SQL，否则视为无效重试（检测到相同 SQL 直接跳出 repair，
节省一轮）"。落地它需要一条 **repair → 失败出口**的新路径，而那条路径必须携带**执行类错误码**
（`timeout`/`syntax_error`…）—— 而 `error_out` 才是唯一做"exec_error → 错误码"映射的地方。
从本节点直接跳出去会制造**第二个映射点**。⇒ 本窗口不实现该优化，只靠 `repair_round ≤ 2` 兜底，
并在 RELAY 登记（另一选项：让 `error_out` 也接受"由一个标志触发的提前收口"）。
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

__all__ = ["repair"]


async def repair(state: GraphState) -> dict[str, Any]:
    """一轮纠错 → 组 6（新 SQL）+ 组 9（`repair_round` / `repair_history`）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    question = str(state.get("normalized_question") or "")
    plan_payload = state.get("plan")
    if not isinstance(plan_payload, Mapping):
        raise ContractViolationError(
            "`repair` 拿不到结构化计划 —— 图连线的顺序被改了",
            detail={"plan_type": type(plan_payload).__name__},
        )
    plan = Plan.model_validate(dict(plan_payload))

    exec_error = state.get("exec_error")
    digest = exec_error.get("llm_hint") if isinstance(exec_error, Mapping) else None
    if not digest:
        # 见 docstring §一：不可修类不该到这里。
        raise ContractViolationError(
            "`repair` 拿到了没有 `llm_hint` 的执行错误 —— 条件边与本节点对"
            "「可修类」的判据不一致（`app.exec.REPAIRABLE_CLASSES` 是唯一来源）",
            detail={"error_class": exec_error.get("error_class") if isinstance(exec_error, Mapping) else None},
        )

    try:
        with node_latency(LatencyKey.GEN_SQL):
            outcome = await deps.planner.repair_sql(
                identity,
                normalized_question=question,
                plan=plan,
                error_digest=str(digest),
            )
    except LlmError as exc:
        return llm_error_update(state, exc, stage="repair")
    except PlannerError as exc:
        context.report_degraded(
            DegradedReason.LLM_UNAVAILABLE,
            ActionTaken.TEMPLATE_ONLY,
            {"stage": "repair", "error": type(exc).__name__},
        )
        return terminal_update(
            state,
            event="refuse",
            outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )

    context.record_usage(outcome.meta.tokens, outcome.meta.cost_cny)

    if outcome.primary is None:
        update = terminal_update(
            state,
            event="refuse",
            outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )
        update["intent_detail"] = {
            "reason_code": "repair_blocked",
            "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
            "blocking_issues": list(outcome.blocking_issues),
        }
        return update

    round_no = int(state.get("repair_round", 0)) + 1
    payload = dict(outcome.state_payload())
    payload["sql_candidates"] = (outcome.primary.model_dump(),)  # §5.2.1：只留选中项
    payload["repair_round"] = round_no
    payload["repair_history"] = (
        *tuple(state.get("repair_history") or ()),
        {
            # ✅ 仅脱敏摘要可出站（07 §5.2 组 9 逐字）：类别与轮次，不含 SQL、不含原始库文本。
            "round": round_no,
            "error_class": exec_error.get("error_class") if isinstance(exec_error, Mapping) else None,
            "attempts": outcome.attempts,
        },
    )
    return payload
