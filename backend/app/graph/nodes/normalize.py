"""节点 2 `normalize` —— 时间绝对化 / 黑话别名 / 零代词补全 / 数值单位（07 §5.3 行 2）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、本节点走的是**合并档**（`understand()`），不是单跑 `normalize()`
--------------------------------------------------------------------------
07 §16.1 的手段 1 = "合并 `normalize` + `intent` 为一次调用"，状态栏已标 ✅ 已落地，
实测 2.84s → 1.56s（W3A §12.1）；而 §16.1 的诚实结论是"全串行 + 不合并时不满足 8s P95"。
⇒ P0 默认走 `PlannerEngine.understand()`（W3B 标注为"推荐入口"），本节点一次写满
**组 2 + 组 3**，随后的 `intent` 节点因此变成空操作（见该文件）。

⚠️ 合并**不改变任何判定标准**（§16.1 原文），只是省一次往返与一段重复上下文。
⇒ 单跑路径（`engine.normalize()` + `engine.classify_intent()`）必须仍然可跑 ——
否则 §16.1 DoD① 的"合并省了多少"无从测量。开关 = `GraphDeps.merged_understand`。

--------------------------------------------------------------------------
二、失败转移（§5.3 行 2 与行 3 的交集，逐条落到出口）
--------------------------------------------------------------------------
| 触发 | 本节点动作 | 去向 |
|---|---|---|
| `LlmRefused` | 直接转 `refuse` 终态（**必须先于 `PlannerError` 分流**） | `refuse` |
| 其余 `LlmError`（429/5xx/出站违规…） | `error(default_code)` | `error` |
| `UnderstandUnavailable`（JSON 修复用尽） | `degraded(llm_unavailable, template_only)` + `intent=refuse` | `refuse`（模板层 P0 恒无命中） |

⚠️ **时间不可解析 → 澄清**不在本节：`UnderstandOutcome.time_parse_ok=False` 只是写进 state，
由 `route_after_normalize` 判去向（§5.4 第 1 行）。本节点**不猜时间**（N-26）。

⚠️ **降级方向不对称，必须写清**：`UnderstandUnavailable` 是"模型给不出可用 JSON"，
在本项目里它的产品动作是**模板 → 无命中 → 拒答**（§10.2 最后两行），
故这里先把 `intent` 写成 `refuse` 再设终态 —— 让 state 与终态互相印证
（只设终态而不写 `intent` 的话，审计里"为什么拒答"就只剩一句 reason）。

--------------------------------------------------------------------------
三、两个"要了但给不了"的入参（如实登记，不编）
--------------------------------------------------------------------------
1. **多轮历史**：`understand(ctx, question, history=...)` 收 `history`，而 `GraphState`
   §5.2 的 11 组字段里**没有**历史消息字段 ⇒ 传 `()`。多轮指代消解因此在 P0 不生效
   （表现为"它/那个"类问题拿不到上一轮上下文）。缺口已登记。
2. **`resolved_terms` 的语义包批量命中**：`SemanticBundleRuntime.resolve_terms()` 提供
   O(1) 批量命中，但 `understand()` 内部已经做了时间词与别名解析（`resolve_time` 走
   `semantics`），故本节**不重复**调一次 —— 同一事实算两遍必然漂移。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import ActionTaken, DegradedReason, LatencyKey, Outcome, RefuseReason
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
from app.planner.schemas import IntentKind

__all__ = ["normalize"]


async def normalize(state: GraphState) -> dict[str, Any]:
    """归一化（合并档下同时产出意图）→ 07 §5.2 组 2（+ 组 3）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    question = str(state.get("raw_question") or "")

    try:
        with node_latency(LatencyKey.NORMALIZE):
            if deps.merged_understand:
                outcome = await deps.planner.understand(identity, question)
            else:
                outcome = await deps.planner.normalize(identity, question)
    except LlmError as exc:
        # 顺序刻意：`LlmRefused` 在 `llm_error_update` 内部最先分流（产品结论 ≠ 故障）。
        return llm_error_update(state, exc, stage="normalize")
    except PlannerError as exc:
        # 引擎已把 notes 送进它自己的 sink（→ `RunContext.report_degraded`），此处**不重发**，
        # 只补一条"下一步走模板"的业务降级（网关那一条是"出站跳"，语义不同）。
        context.report_degraded(
            DegradedReason.LLM_UNAVAILABLE,
            ActionTaken.TEMPLATE_ONLY,
            {
                "stage": "normalize",
                "error": type(exc).__name__,
                "attempts": getattr(exc, "attempts", None),
            },
        )
        update: dict[str, Any] = {
            "intent": IntentKind.REFUSE.value,
            "intent_detail": {
                "reason_code": "understand_unavailable",
                # ⚠️ 与终态 reason 同一取值（C-12 的 4 值里没有"理解失败"的槽位，已登记近似）
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
    return dict(outcome.state_payload())
