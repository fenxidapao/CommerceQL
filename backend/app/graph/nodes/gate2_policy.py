"""节点 9 `gate2_policy` —— 策略校验 + **算 `scope`**（07 §5.3 行 9 / §7.4）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、两条去向，**都由本节点定**（同一个 `not passed` 有两种终态）
--------------------------------------------------------------------------
`Gate2Report` 多带一个 `refuse_reason`，这不是冗余 —— 它是"产品结论 vs 工程故障"的分界线
（`run_gate2` 的 docstring：越界域是产品结论，其余拒绝是故障）：

| 情形 | 终态 | 依据 |
|---|---|---|
| `refuse_reason` 非空（数据域越界） | **`refuse(out_of_scope)`** | §14.2 D3：它不是"系统出错"，是"你不能看" |
| 其余 `not passed`（版本漂移 / 白名单外资产 / 敏感列） | `error(GATE_POLICY_REJECTED)` | §5.3 行 9 明文 |

⚠️ **条件边无法从 `GateResult` 反推这两条**（`GateResult` 里没有 `refuse_reason`）——
所以结论必须在这里落进 `state.terminal`，`route_after_gate2` 只负责按结论选出口
（这条分工写在 `edges.py` 文档头 §三）。

--------------------------------------------------------------------------
二、`scope` 写两处，不是重复
--------------------------------------------------------------------------
`Gate2Report.scope` 同时写进：
1. `GraphState.scope`（组 7）—— 审计面（§5.3.1 段 1 的 `scope` 列）；
2. `RunContext.scope` —— 出口面：`meta.scope` 由 `events.meta_payload` 组装，而
   它必须能在"没走到 gate2 的路径"（澄清/拒答/错误）上给出 C-07 的缺省语义。
   两处并存是**刻意的**（`context.py` 已注明），删掉任一处都会让一个面失去依据。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import ErrorCode, GateNo, LatencyKey, Outcome
from app.graph.nodes._shared import (
    deps_of,
    gate_update,
    identity_of,
    node_latency,
    rc,
    terminal_update,
)
from app.graph.state import GraphState
from app.guard import run_gate2

__all__ = ["gate2_policy"]


async def gate2_policy(state: GraphState) -> dict[str, Any]:
    """gate2：策略校验 + scope 计算（纯函数，W2C）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    sql = str(state.get("sql_text") or "")

    with node_latency(LatencyKey.GATE):
        report = run_gate2(sql, identity, deps.semantics)

    # scope 的两个面（见模块 docstring §二）。
    context.scope = report.scope
    update: dict[str, Any] = {"scope": report.scope}
    update.update(gate_update(state, GateNo.POLICY, report.gate_result))
    if report.gate_result.passed:
        return update

    if report.refuse_reason is not None:
        update.update(
            terminal_update(
                state,
                event="refuse",
                outcome=Outcome.REFUSE,
                reason=report.refuse_reason.value,
            )
        )
        return update

    update.update(
        terminal_update(
            state,
            event="error",
            outcome=Outcome.FAILED,
            code=ErrorCode.GATE_POLICY_REJECTED.value,
        )
    )
    return update
