"""节点 10 `gate3_cost` —— EXPLAIN 成本闸门（07 §5.3 行 10 / §7.5 / U-63）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、EXPLAIN 只能走 `executor.explain()`，**不能**走 `fetch`（U-63，已实测钉死）
--------------------------------------------------------------------------
`fetch` 走 `DECLARE ... CURSOR`，而 PG 对 EXPLAIN **不接受**命名游标（实测 `42601`），
误接的后果不是报错而是**误导**：错误被归成 `syntax_error`（可修类）→ 回灌 repair
→ 模型被要求"修语法"，而语法本来是对的（W2D RELAY §0 原话）。
⇒ 经 `rich_method` 取 `explain`（端口上没有它，缺即抛）。

--------------------------------------------------------------------------
二、EXPLAIN 报错 → `warn`，**不阻断**（§7.5 / §14.2 D5）
--------------------------------------------------------------------------
`run_gate3` 支持 `thresholds["explain_error"]=True` → 返回 `passed=True, decision=WARN`。
本节点在 EXPLAIN 抛异常时置该键。⚠️ `warn` **不是通过** —— 它由 `events._all_gates_clean_pass`
按 `decision is PASS` 判定，故这一轮**不会**出现 `stage=gate_passed`（§14.2 D6 的要求）。

⚠️ **"连续 3 次报错 → 降级为仅 AST+策略并标注"（07 §7.5 / `EXPLAIN_ERROR_DEGRADE_THRESHOLD`）
在 P0 未落地**：它是**跨请求**计数，而 `RunContext` 是每请求的、`obs.metrics` 里也没有
对应的计数器（W0 只落了 binding 两个 Counter）。本节点只按单次 `warn` 处理并登记该缺口
（载体缺，不是"忘了实现"）。

--------------------------------------------------------------------------
三、`params` 必须一起交给 EXPLAIN
--------------------------------------------------------------------------
参数化 SQL（N-04）里 `%(name)s` 的值影响计划（选择率估算）。只传 SQL 文本不传参数
会让 EXPLAIN 在缺参情况下失败或给出错误计划。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import ErrorCode, GateDecision, GateNo, LatencyKey, Outcome
from app.graph.nodes._shared import (
    deps_of,
    gate_update,
    identity_of,
    node_latency,
    rich_method,
    terminal_update,
)
from app.graph.state import GraphState
from app.guard import run_gate3
from app.obs.logging import get_logger

__all__ = ["gate3_cost"]

_log = get_logger(__name__)


async def gate3_cost(state: GraphState) -> dict[str, Any]:
    """gate3：EXPLAIN → 阈值判定（判定是纯函数，EXPLAIN 经受控入口）。"""
    deps = deps_of()
    identity = identity_of(state)
    sql = str(state.get("sql_text") or "")
    params = dict(state.get("sql_params") or {})

    explain = rich_method(
        deps.executor,
        "explain",
        why="gate3 的 EXPLAIN 必须走受控入口（U-63）；走 `fetch` 会撞 PG 42601 并被误归为可修语法错",
    )

    thresholds: dict[str, Any] = dict(deps.gate3_thresholds)
    with node_latency(LatencyKey.GATE):
        try:
            plan_payload = await explain(
                f"EXPLAIN (FORMAT JSON) {sql}",
                params,
                identity,
                statement_timeout_ms=deps.statement_timeout_ms,
            )
            thresholds["explain_plan"] = plan_payload
        except Exception as exc:
            # ⚠️ `asyncio.CancelledError` 继承 `BaseException`，**不会**被这里吃掉：
            # 客户端取消必须能一路冒泡（07 §18.3 步 5）。
            thresholds["explain_error"] = True
            # ⚠️ 计数载体缺失（见 docstring §二）：只打日志，不假装"已经降级"。
            _log.warning(
                "gate3_explain_failed",
                outcome="warn_not_blocking",
                task_id=identity.task_id,
                error_type=type(exc).__name__,
                extra_fact="EXPLAIN 不可用 → gate3 判 warn（不报告为通过，D5/D6）",
            )

        result = run_gate3(sql, thresholds)

    update: dict[str, Any] = dict(gate_update(state, GateNo.COST, result))
    if result.decision is not GateDecision.REJECT:
        # `pass` 继续执行；`warn` 也继续（§14.2 D5）；`skipped` 继续但**不得报告为通过**（D6）。
        # 三者都不设终态 —— 是否发 `stage=gate_passed` 由 `events._all_gates_clean_pass`
        # 按 `decision is PASS` 判定（判据只有一处）。
        return update

    update.update(
        terminal_update(
            state,
            event="error",
            outcome=Outcome.FAILED,
            code=ErrorCode.COST_TOO_HIGH.value,
        )
    )
    return update
