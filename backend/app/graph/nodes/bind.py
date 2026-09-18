"""节点 6 `bind` —— **确定性**字段绑定（07 §5.3 行 6；本节点禁 LLM 之外的一切发明）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、L4 走**在线**入口（`score_l4`），不走注入入口
--------------------------------------------------------------------------
D1(a) 给了两条路（`app/binding/__init__.py` 的"给 W4"§4），本窗口按 `PROMPT §六` 选**在线**：

| 路 | 身份校验 | 本窗口是否使用 |
|---|---|---|
| 在线：`await score_l4(port=...)` | ✅ **真校验**（`model_id`/`prompt_version` 来自 `LLMResponse`，不匹配即抛） | ✅ 用 |
| 注入：把 `CandidateRef(layer=L4)` 塞进 `resolve()` | ⚠️ **恒通过**（候选没有打分器标识） | ❌ 不用 |

🔴 **但必须如实写下这条在线路径的边界**：本节点拿 `score_l4` 的分数后，把它们转成
`CandidateRef(layer=L4)` 交给 `resolve_detailed` —— 而 `CandidateRef` **没有**打分器标识字段
（W3C RELAY §给 W0 第 2 条）。⇒ 判定层的 `check_binds_scorer` 在这一步上**仍然是构造性通过**，
真校验只发生在 `score_l4` **内部**那一次（它用 `LLMResponse` 的标识构造 `RerankScore`）。
要让校验真正生效，`decide()` 必须直接吃 `ScoreOutcome`（即绕过 `resolve_detailed`），
那需要把 resolve→filter→decide 三步在节点里重排 —— 本窗口**不做**（重排等于在编排层
复制一遍判定链路，与 G-1"节点只编排"冲突）。缺口已登记，等架构裁决。

--------------------------------------------------------------------------
二、`concept` 取什么（07 未写明 —— 本窗口自定并登记）
--------------------------------------------------------------------------
`resolve_detailed(concept, ctx, candidates)` 的 `concept` 是**单个概念字符串**，
而 07 §5.3 行 6 只写"确定性字段绑定（五步过滤）"，**没有**定义它的粒度
（一个概念一次？还是计划里每个指标/维度各一次？）。本窗口取：

```
concept = plan.metrics[0].name  （没有指标时退回 normalized_question）
```

理由：单次调用是 0.2s 预算内唯一稳妥的形态；多次调用会让"哪个概念失败"与
`binding_status` 的单值语义对不上（组 5 只有一个 `binding_status`）。
这是本窗口的**判断**，不是文档结论 —— 已登记待裁。

--------------------------------------------------------------------------
三、落库（T7 的 DoD① 最后一步）失败**不阻断**
--------------------------------------------------------------------------
`query_plan` 写入是 `07 §12.3` 的硬要求（诊断面），但它是**元数据写入**，
不是安全前提：写不进去时用户的查询仍然可以正确完成。
⇒ 处置 = 尝试写 + 失败打 ERROR 日志（`query_plan_write_failed`）+ 如实登记，
**不**把一次成功的查询变成 500。这条取舍登记待裁（另一选项是 fail-closed）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.binding import MAX_CLARIFY_OPTIONS
from app.binding.context import BindingRequestScope, clear_binding_scope, set_binding_scope
from app.core.contracts import CandidateRef
from app.core.enums import ActionTaken, BindingLayer, BindingState, DegradedReason
from app.core.errors import ContractViolationError
from app.graph.context import RunContext
from app.graph.nodes._shared import (
    candidate_payload,
    candidate_ref,
    deps_of,
    identity_of,
    llm_error_update,
    rc,
)
from app.graph.state import GraphState
from app.llm.errors import LlmError
from app.obs.logging import get_logger
from app.planner.schemas import Plan

__all__ = ["bind"]

_log = get_logger(__name__)


async def bind(state: GraphState) -> dict[str, Any]:
    """字段绑定 → 组 5（`bindings` / `binding_status` / `binding_ambiguity`）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)

    plan_payload = state.get("plan")
    if not isinstance(plan_payload, Mapping):
        raise ContractViolationError(
            "`bind` 拿不到结构化计划（`route_after_plan` 已保证非空）—— 图连线的顺序被改了",
            detail={"plan_type": type(plan_payload).__name__},
        )
    plan = Plan.model_validate(dict(plan_payload))
    question = str(state.get("normalized_question") or "")
    concept = _concept_of(plan, question)

    # 资产级候选（组 4）+ 在线 L4 打出的字段级候选（经 RunContext 中转，见 link 的 docstring §二）。
    asset_refs = tuple(candidate_ref(item) for item in (state.get("candidates") or ()))
    try:
        l4_refs = await _online_l4(context, [ref for ref, _ in context.take_columns()], question)
    except LlmError as exc:
        return llm_error_update(state, exc, stage="bind")

    # ⚠️ 本节点**不单独计时**：`LatencyKey` 是恰好 8 个（C-04 要求与审计键集逐字一致），
    # 里面没有 `bind` 键。硬塞一个语义不符的键会让两处数不再可比（见 `_shared` 文档头 §三），
    # 故 bind 的耗时只体现在 `latency_ms.total` 里。
    #
    # 🔴 问句上下文（W3C RELAY §2 / `binding/context.py` 的"接线动作归 W4"）：
    # 不设 ⇒ **L2 与五步过滤的步③ 静默失效**（fail-open，`scope_was_set=False` 如实标出）。
    # 设置点在这里（`resolve_detailed` 之前）而不是 runner：scope 要的是
    # `normalized_question`，它由 planner 在 `state` 里产出 —— runner 在进图前拿不到，
    # 只有本节点同时握着"归一化问句"与"判定调用"两样东西。
    # ⚠️ `time_semantics` 传 `None`（不校）：那是"**请求声明**的时间语义"
    # （§A.1.1 的 options 没有这一项 ⇒ 没有来源），而 `Clock` 的口径来自**语义包**，
    # 两者语义不同 —— 拿后者冒充前者等于发明一个请求没做过的声明（U-22）。
    # ⚠️ `bundle_version` 带上（N-23 的一致性告警输入）。
    set_binding_scope(
        BindingRequestScope(
            normalized_question=question,
            bundle_version=context.bundle_version or None,
        )
    )
    try:
        outcome = deps.binding.resolve_detailed(concept, identity, (*asset_refs, *l4_refs))
    finally:
        # 同一请求内可能多次进入（重试/重跑路径）⇒ 必须还原，不能残留到下一次判定。
        clear_binding_scope()

    if not outcome.scope_was_set:
        # L2 与五步过滤的步③ **不判**（fail-open，W3C RELAY §2）。不静默：打日志 + 登记。
        _log.warning(
            "binding_scope_not_set",
            outcome="l2_and_grain_step_skipped",
            task_id=identity.task_id,
            extra_fact="API 层每请求必须 `set_binding_scope(...)`，否则问句粒度永不生效",
        )

    result = outcome.result
    update: dict[str, Any] = {
        "bindings": tuple(candidate_payload(ref) for ref in result.bindings),
        # 4 值（`BindingState`），**不是** `state.py` 注释里的 3 值（该注释需订正，见 edges 文档头 §二-1）。
        "binding_status": str(result.state),
    }

    if result.state is BindingState.AMBIGUOUS:
        # `ambiguous` 下 `bindings` 是**澄清选项**，不是已绑定字段（读法 1）——
        # 交给 `clarify_out` 组装，本节点不写终态（出口节点是终态的唯一构造者）。
        update["binding_ambiguity"] = {
            "prompt": outcome.clarify_prompt,
            "options": [
                candidate_payload(ref) for ref in result.bindings[:MAX_CLARIFY_OPTIONS]
            ],
        }
    elif result.state is BindingState.RESOLVED_DEFAULT:
        # U-26：披露文案只能走 `insight.caveats[]`，而它与本节点隔了 11 个节点 ⇒ 内存中转。
        context.hold_disclosure(outcome.disclosure)

    await _write_query_plan(context, state, plan, result.state, result.layer)
    return update


def _concept_of(plan: Plan, question: str) -> str:
    """绑定的概念字符串（见模块 docstring §二；判据只有一处）。"""
    if plan.metrics:
        return str(plan.metrics[0].name)
    return question


async def _online_l4(
    context: RunContext, candidate_ids: Sequence[str], question: str
) -> tuple[CandidateRef, ...]:
    """在线 L4：真打分 → 还原成带 `L4` 标记的候选（唯一消费姿势见 `_split_candidates`）。

    `semantic_summary` 传空串并**登记**：`SemanticBundlePort`（W0 冻结的四方法）里
    **没有**"语义摘要"出口，而 `score_l4` 的摘要参数是给模型的上下文质量用的 ——
    传空不会让打分失败（含失败态由 `ScoreOutcome` 表达），但 L4 质量低于设计预期。
    缺口已登记（需语义包侧或 planner 侧提供一个摘要出口）。
    """
    if not candidate_ids:
        # 没有字段级候选 → 不调模型（省一次出站），直接交给判定层的 fail-safe。
        return ()
    from app.binding import score_l4  # 局部 import：仅 `bind` 需要（L4 是本包唯一异步入口）

    scores = await score_l4(
        port=context.deps.llm,
        question=question,
        candidates=list(candidate_ids),
        bundle_version=context.bundle_version,
    )
    if not scores.ok:
        # `failed=True` 是**正常返回值**（N-27 约束④ 的 fail-safe 输入），不是异常。
        context.report_degraded(
            DegradedReason.LLM_UNAVAILABLE,
            ActionTaken.REDUCED_CANDIDATES,
            {"stage": "bind.l4", "reason": scores.reason},
        )
        return ()
    return tuple(
        CandidateRef(asset_id=score.candidate_id, score=score.value, layer=BindingLayer.L4)
        for score in scores.scores
    )


async def _write_query_plan(
    context: RunContext,
    state: GraphState,
    plan: Plan,
    binding_state: BindingState,
    binding_layer: BindingLayer,
) -> None:
    """`query_plan` 落库（DoD① 的最后一格）。见模块 docstring §三 的失败语义。"""
    writer = context.deps.query_plan_writer
    if writer is None:
        _log.warning(
            "query_plan_writer_absent",
            outcome="not_written",
            task_id=str(state.get("task_id")),
            extra_fact="装配层未注入 `QueryPlanStore` → `binding_state`/`binding_layer` 不落库",
        )
        return

    plan_json = plan.model_dump()
    plan_json.setdefault("schema_version", 1)
    try:
        await writer.insert_query_plan(
            task_id=str(state["task_id"]),
            plan_json=plan_json,
            bundle_version=str(context.bundle_version),
            binding_state=binding_state,
            binding_layer=binding_layer,
            plan_summary=plan.to_summary().model_dump(),
        )
    except Exception as exc:
        _log.error(
            "query_plan_write_failed",
            outcome="non_blocking",
            task_id=str(state.get("task_id")),
            error_type=type(exc).__name__,
            extra_fact="DoD① 的落库未完成；用户查询不受影响（元数据写入非安全前提）",
        )
