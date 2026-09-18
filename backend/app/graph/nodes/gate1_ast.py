"""节点 8 `gate1_ast` —— AST 静态审计 + LIMIT 注入 + 默认谓词注入（07 §5.3 行 8）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、被拒时**不覆盖 `sql_text`**（审计证据优先）
--------------------------------------------------------------------------
`run_gate1` 在拒绝时的 `rewritten_sql` 是空串（`_build_reject`）。若照抄回 `sql_text`，
被拒的那条 SQL 就**从 state 里消失了** —— 而它是审计里唯一能回答"模型当时生成了什么"
的一手证据（07 §5.2 组 6 的注释：`sql_text` 持久化供审计）。⇒ 只在**通过**时回写改写后的 SQL。

--------------------------------------------------------------------------
二、`allowlist` 的来源只有一处
--------------------------------------------------------------------------
`run_gate1(sql, allowlist)` 的 `allowlist` 是 gate1 的**全部判据**（白名单表、默认谓词、
`deny_columns`、常量表、生效 LIMIT）。它由 `SemanticBundlePort.asset_allowlist(ctx)` 产出
（唯一来源）。⚠️ 与 gate2 各自取一次：两次调用是**刻意**的 —— `asset_allowlist` 是
按身份现算的纯函数，共用一份变量会让"gate2 复核"变成"复核自己刚给的那份"（失去二次校验的意义）。

--------------------------------------------------------------------------
三、不触发 repair（§5.4 明文）
--------------------------------------------------------------------------
结构性拒绝（多语句 / 非 SELECT / 注释注入…）**重试无意义** ⇒ 直接 `error(GATE_AST_REJECTED)`。
`route_after_gate1` 会读 `gate_results[AST].passed` 决定去向；本节点的终态写在
"拒绝"分支上，两条路互斥且都由**本节点**给出结论（判定只有一处）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.enums import ErrorCode, GateNo, LatencyKey, Outcome
from app.graph.nodes._shared import (
    deps_of,
    gate_update,
    identity_of,
    node_latency,
    terminal_update,
)
from app.graph.state import GraphState
from app.guard import run_gate1

__all__ = ["gate1_ast"]


async def gate1_ast(state: GraphState) -> dict[str, Any]:
    """gate1：静态审计（纯函数，W2C）。"""
    deps = deps_of()
    identity = identity_of(state)
    sql = str(state.get("sql_text") or "")
    allowlist: Mapping[str, Any] = deps.semantics.asset_allowlist(identity)

    with node_latency(LatencyKey.GATE):
        report = run_gate1(sql, allowlist)

    update: dict[str, Any] = dict(gate_update(state, GateNo.AST, report.gate_result))
    if report.gate_result.passed:
        update["sql_text"] = report.rewritten_sql
        update["limit_injected"] = (
            dict(report.limit_injected) if report.limit_injected is not None else None
        )
        update["applied_predicates"] = tuple(report.applied_predicates)
        return update

    # 被拒：保留原始 SQL（见模块 docstring §一），只写终态。
    update.update(
        terminal_update(
            state,
            event="error",
            outcome=Outcome.FAILED,
            code=ErrorCode.GATE_AST_REJECTED.value,
        )
    )
    return update
