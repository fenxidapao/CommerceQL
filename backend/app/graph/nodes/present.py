"""节点 14 `present` —— 图表 spec + 描述性结论（07 §5.3 行 14）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、P0 = **方案 ①：如实降级**（`app/present/` 仍是空壳，W3B 归属）
--------------------------------------------------------------------------
`GraphDeps.presenter` 在 P0 恒为 `None`（`present/` 包没有可调用的产物）。
本节点按 §14.2 F4 走降级：`degraded(present_failed, table_only)`，**只给表格**。
⇒ `chart_spec` / `insight` 都不写，`chart` / `insight` 两个事件因此不发（`events.py` 的条件）。
这不是"少发两个可选事件" —— 它是**产品可见**的差异，所以必须发 `degraded` 让前端能解释
"这一轮为什么只有表"（N-21）。

--------------------------------------------------------------------------
二、U-26 的披露文案在 P0 **没有落点**（缺口，必须写清）
--------------------------------------------------------------------------
`resolved_default` 的强制披露文案，07 裁定唯一载体 = `insight.caveats[]`（禁止塞 `scope.notice`）。
而 P0 无 `insight`（见上）⇒ 披露文案**没有用户可见的出口**。本节点的处置：

1. 把它写进本次 `degraded` 的 `detail`（审计与日志可见）—— 这是既有通道，不新增载体；
2. **不**把它塞进 `scope.notice`（U-26 明文禁止，两处文案的语义不同：一个是"口径默认"，
   一个是"范围过滤"）；**不**伪造一个只含 caveats 的空 `insight`（那会发明 `insight.text=""` 的语义）。
3. 缺口登记：**`present` 包落地前，`resolved_default` 的披露对用户不可见**。

--------------------------------------------------------------------------
三、`presenter` 若被装配进来 → **fail-fast**
--------------------------------------------------------------------------
P0 没有任何实现类，所以它的接口（方法名、入参、出参）**不存在**。此时猜一个接口去调
（`getattr(presenter, "build", None)` 之类）就是发明契约。⇒ 显式拒绝并指向 W3B。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import ActionTaken, DegradedReason, LatencyKey
from app.core.errors import ContractViolationError
from app.graph.nodes._shared import node_latency, rc
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["present"]

_log = get_logger(__name__)


async def present(state: GraphState) -> dict[str, Any]:
    """呈现（P0 = 诚实降级，见 docstring §一）。"""
    context = rc()
    deps = context.deps

    if deps.presenter is not None:
        raise ContractViolationError(
            "`GraphDeps.presenter` 被装配了，但 `app/present/` 的实现接口在 P0 **不存在**"
            "（无方法名/入参/出参约定）—— 猜一个接口去调就是发明契约。"
            "请先由 W3B 交付 `present/` 的公开入口，再在此接线。",
            detail={"presenter_type": type(deps.presenter).__name__},
        )

    with node_latency(LatencyKey.PRESENT):
        disclosure = context.take_disclosure()

    detail: dict[str, Any] = {"stage": "present", "reason": "presenter_absent"}
    if disclosure:
        # U-26 的披露文案 —— P0 只能落在这里（见 docstring §二）。
        detail["binding_disclosure"] = disclosure
        _log.warning(
            "binding_disclosure_without_outlet",
            outcome="audit_only",
            task_id=str(state.get("task_id")),
            extra_fact="resolved_default 的披露文案本应进 insight.caveats[]，而 P0 无 insight",
        )

    context.report_degraded(DegradedReason.PRESENT_FAILED, ActionTaken.TABLE_ONLY, detail)
    # ⚠️ 不写 `chart_spec` / `insight`：缺席 = 前端不发这两个事件（`events.py` 按非空判定）。
    return {}
