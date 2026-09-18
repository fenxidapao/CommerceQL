"""节点 4 `link` —— 四路检索 + 融合 + 精筛 + 图扩展（07 §5.3 行 4）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、为什么调 `search_full` 而不是端口上的 `search`
--------------------------------------------------------------------------
`RetrievalPort.search` 只回 `candidates`，而本节点还要两样**端口装不下**的东西：

| 要什么 | 为什么 |
|---|---|
| `result.mode`（**实际**执行档） | C-11 要求 `meta.retrieval_mode` 如实回填**实际**执行档 —— HYBRID 请求在稠密失败后实际执行 SPARSE_ONLY，报请求档就是撒谎 |
| `result.degraded_reason` / `action_taken` | N-21"不静默降级"：稠密不可用必须发 `degraded` |

二者都在 `search_full` 的返回里（W2B 已在 `search.py` 注明"W4 接线用"）⇒ 经 `rich_method`
取它（缺即抛：静默跳过会让降级永久不可见，且没有任何报错）。

--------------------------------------------------------------------------
二、字段级候选为什么要经 `RunContext` 中转（**缺口登记**）
--------------------------------------------------------------------------
`bind` 的在线 L4 打分要打的是**字段级**候选（`result.columns`，ref 形状 `资产.列`），
而 `GraphState` 组 4 的 `candidates` 按 `RetrievalResult` 的注释是**资产级 Top-5**；
07 §5.2 的字段表里**没有**列级候选的键（§5.2 是穷举的，为传值新增字段 = 造第二份真相）。
⇒ 与结果行 / 披露文案同款：走 `RunContext` 的**内存单次赋值**通道
（不进检查点、不进 Redis、不进 SSE）。缺口已登记：列级候选在 §5.2 里没有位置。

--------------------------------------------------------------------------
三、两处"文档有、实现拿不到"的东西（如实登记，**不编**）
--------------------------------------------------------------------------
1. **§6.10 的 `candidates_summary` 有 5 个键，只拿得到 3 个**：`value_hits` / `graph_added` /
   `fused_top` 可从 `RetrievalResult` 直接数出；`dense` / `sparse` 的**分路条数**
   在融合之后不再存在（`RetrievalResult` 只暴露融合结果）⇒ 不填假数字。
2. **`ambiguities` 不写**：检索侧 P0 不产出歧义（`RetrievalResult` 里没有该字段），
   而 `state.py` 对它的类型是 `tuple[OpaquePayload, ...]`（U-24 占位）—— 写一个空元组
   会让 `route_after_link` 的"还剩没有"判定从"未产出"变成"产出且为空"，
   两件事在 `resume` 语义下不同（`initial_state` 的既定取向：不预先塞空值）。
   ⇒ 本节点只在**确有歧义**时写它；P0 恒不写。缺口已登记。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import ActionTaken, LatencyKey, RetrievalMode
from app.graph.nodes._shared import (
    candidate_payload,
    deps_of,
    identity_of,
    node_latency,
    rc,
    rich_method,
)
from app.graph.state import GraphState

__all__ = ["link"]

#: 请求的检索档位。**P0 恒 HYBRID**：`RunOptions`（附录 A §A.1.1）里没有"检索档位"这个
#: 字段，而 `state.py` 的 `options` 是 OpaquePayload 占位 —— 不发明一个键名去读它。
#: 稠密不可用时由检索层**自行**降级并在 `result.mode` 里如实回填（C-11），
#: 故"写 HYBRID"不等于"假装跑的是 hybrid"。
_REQUESTED_MODE: RetrievalMode = RetrievalMode.HYBRID


async def link(state: GraphState) -> dict[str, Any]:
    """检索 → 组 4（`candidates` / `candidates_summary` / `retrieval_mode`）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    question = str(state.get("normalized_question") or state.get("raw_question") or "")

    search_full = rich_method(
        deps.retrieval,
        "search_full",
        why="link 需要实际执行档与降级信息（C-11 / N-21）—— 端口 `search` 只回候选",
    )
    with node_latency(LatencyKey.LINKING):
        result = await search_full(question, identity, _REQUESTED_MODE)

    # 降级如实上报（N-21）。`action_taken` 缺失时取 `sparse_only`：
    # 检索层唯一会发的降级就是"稠密不可用 → 走稀疏"，这是它自己的取值（不是我们猜的）。
    if result.degraded_reason is not None:
        context.report_degraded(
            result.degraded_reason,
            result.action_taken or ActionTaken.SPARSE_ONLY,
        )

    # 列级候选交给 `bind` 的在线 L4（见模块 docstring §二）。
    context.hold_columns(result.columns)

    update: dict[str, Any] = {
        "candidates": tuple(candidate_payload(ref) for ref in result.candidates),
        "candidates_summary": {
            "fused_top": len(result.candidates),
            "value_hits": len(result.value_hits),
            "graph_added": len(result.graph_hits),
        },
        # ⚠️ 写**实际**执行档，不是请求档（C-11）。
        "retrieval_mode": str(result.mode),
    }
    return update
