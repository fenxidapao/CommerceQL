"""融合与截断（07 §6.7）—— 四路候选的 RRF 融合、降级权重重分配、Top-N 截断。

归属窗口：**W2B**。纯函数、离线、无 LLM、**无随机**。

规则逐条对齐 07 §6.7：
- 四路权重 dense 0.40 / sparse 0.35 / value 0.15 / graph 0.10（配置源 =
  `app.core.config` 的 `DENSE/SPARSE/VALUE/GRAPH_WEIGHT`，本模块不持有第二份默认值——
  调用方从 Settings 读入传入）；
- 融合算法 RRF，`score = Σ wᵢ / (k + rankᵢ)`，k=60（`RRF_K`）；
- **降级时的权重重分配必须是确定性规则**：`sparse_only` 时 dense 的 0.40 按
  0.35:0.10 比例分给 sparse/graph → sparse += 0.40×(0.35/0.45)、graph += 0.40×(0.10/0.45)，
  权重和恒为 1.0；**不得随机、不得按当前候选动态调整**（否则同一问题两次结果不同）；
- 截断：资产 Top-5 / 列 Top-30 / 指标 Top-5（few-shot Top-3–5 归 §6.9，本包不产）；
- 租户过滤在 SQL 层，不在融合后——本模块收到的候选**必须已经过租户过滤**
  （由调用方对 dense/sparse 的 SQL 参数保证；本模块无从复核，这是调用方契约）。

## 输入形态

路由榜 = `route -> [(candidate_id, route_rank)...]`（rank 从 1 起，按各路自己的分数排序）。
candidate_id 约定为**资产 logical_name**（P0 融合在资产级）；
列/指标榜由各自路由单独成榜传入，融合逻辑同构。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "ROUTE_DENSE",
    "ROUTE_GRAPH",
    "ROUTE_SPARSE",
    "ROUTE_VALUE",
    "ROUTE_ORDER",
    "FuseTie",
    "effective_weights",
    "rrf_fuse",
    "top_n",
]

ROUTE_DENSE: Final[str] = "dense"
ROUTE_SPARSE: Final[str] = "sparse"
ROUTE_VALUE: Final[str] = "value"
ROUTE_GRAPH: Final[str] = "graph"

#: 固定路由遍历顺序——确定性的一部分（dict 迭代序不可依赖）。
ROUTE_ORDER: Final[tuple[str, ...]] = (ROUTE_DENSE, ROUTE_SPARSE, ROUTE_VALUE, ROUTE_GRAPH)


@dataclass(frozen=True, slots=True)
class FuseTie:
    """融合后候选：分数 + 各路由名次（归因用，进 stats 不进契约面）。"""

    candidate_id: str
    score: float
    ranks: Mapping[str, int]   # 路由名 → 名次（缺席 = 该路未命中）


def effective_weights(
    weights: Mapping[str, float],
    *,
    dense_available: bool,
) -> dict[str, float]:
    """按降级状态计算**有效权重**（确定性；07 §6.7 降级重分配的唯一实现）。

    - 四路全可用 → 原权重原样返回；
    - dense 不可用（sparse_only）→ dense 权重按 sparse:graph 的原权重比例分给二者，
      和恒等于 1.0。value/graph 自身缺席**不触发**重分配（07 只定义了这一种降级）。
    """
    w = {name: float(weights.get(name, 0.0)) for name in ROUTE_ORDER}
    if dense_available:
        return w
    dense_w = w[ROUTE_DENSE]
    denominator = w[ROUTE_SPARSE] + w[ROUTE_GRAPH]
    if denominator <= 0:
        # sparse 与 graph 权重同为 0：无处可分 → 原样返回（和不为 1 的配置
        # 应被 config 的和=1.0 校验拦下，这里是防御分支，不是第二套规则）。
        w[ROUTE_DENSE] = 0.0
        return w
    w[ROUTE_SPARSE] += dense_w * (w[ROUTE_SPARSE] / denominator)
    w[ROUTE_GRAPH] += dense_w * (w[ROUTE_GRAPH] / denominator)
    w[ROUTE_DENSE] = 0.0
    return w


def rrf_fuse(
    route_ranks: Mapping[str, Sequence[str]],
    weights: Mapping[str, float],
    *,
    k: int,
    dense_available: bool = True,
) -> tuple[FuseTie, ...]:
    """RRF 融合：`score = Σ wᵢ / (k + rankᵢ)`（rank 从 1 起）。

    确定性保证：路由按 `ROUTE_ORDER` 固定顺序累加（浮点加法顺序固定）；
    结果按 (score 降序, candidate_id 字典序) 排序——同分不抖动。
    """
    if k <= 0:
        raise ValueError(f"RRF k 必须为正：{k}")
    eff = effective_weights(weights, dense_available=dense_available)

    ranks: dict[str, dict[str, int]] = {}
    for route in ROUTE_ORDER:
        for rank, candidate_id in enumerate(route_ranks.get(route, ()), start=1):
            ranks.setdefault(candidate_id, {})[route] = rank

    fused = [
        FuseTie(
            candidate_id=candidate_id,
            score=sum(
                eff[route] / (k + rank)
                for route, rank in sorted(per_route.items(), key=lambda kv: ROUTE_ORDER.index(kv[0]))
            ),
            ranks=dict(sorted(per_route.items(), key=lambda kv: ROUTE_ORDER.index(kv[0]))),
        )
        for candidate_id, per_route in ranks.items()
    ]
    fused.sort(key=lambda f: (-f.score, f.candidate_id))
    return tuple(fused)


def top_n(fused: Sequence[FuseTie], n: int) -> tuple[FuseTie, ...]:
    """取前 N（07 §6.7 截断；n 必须 ≥0）。"""
    if n < 0:
        raise ValueError(f"截断数必须 ≥0：{n}")
    return tuple(fused[:n])
