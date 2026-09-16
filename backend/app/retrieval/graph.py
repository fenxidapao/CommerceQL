"""Join 图扩展（07 §6.5）—— 从已命中资产沿认证 join 边补桥接资产。

归属窗口：**W2B**。纯函数、离线、无 LLM。

规则逐条对齐 07 §6.5：
- 图来源**只有**语义包 `joins`（未列出的路径一律禁止——附录 B §B.1.3，
  对应红队 RT-JOIN-003"未认证 JOIN 路径"）；
- 从已命中资产 BFS，**最大跳数 2**；**只沿已认证路径**（边有 `certified_by`，
  且两端资产在包内且 certified）；
- 输出标注 `added_by="join_graph"`，用于 §6.10 的线上代理①
  （图扩展占比过高 = 缺认证宽表）；
- **禁止**模型建议的 JOIN 路径直接使用（FR-5.5）——本模块根本不接收模型输入，
  结构上杜绝。

## U-28 两跳陷阱（必须原样保留的边）

`order_paid → dim_date → campaign` 的区间关联只能经两跳登记边抵达
（07 §4.7.1 裁定：不新增 join 类型）。本模块把"两跳可达"如实返回为
hop=2 的图扩展命中——**物理 SQL 的非裸等值写法**（`date(pay_time) = date_key`）
与**租户谓词落位**（campaign 侧）是生成/执行层的职责，不属于本模块。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.view import BundleView, JoinEdge

__all__ = ["GRAPH_ADDED_BY", "MAX_HOPS", "GraphHit", "expand_join_graph"]

#: 07 §6.5 定案：最大跳数 2。
MAX_HOPS: int = 2

#: 归因标注（§6.10 线上代理①的统计依据）。
GRAPH_ADDED_BY: str = "join_graph"


@dataclass(frozen=True, slots=True)
class GraphHit:
    """图扩展命中：一个经认证路径补进来的资产。"""

    asset: str                      # 新补入的 logical asset name
    hop: int                        # 1 或 2（07 §6.5 上限）
    path: tuple[JoinEdge, ...]      # 从起点资产到本资产的边序列
    added_by: str = GRAPH_ADDED_BY


def expand_join_graph(
    start_assets: tuple[str, ...] | list[str],
    view: BundleView,
    *,
    max_hops: int = MAX_HOPS,
) -> tuple[GraphHit, ...]:
    """从已命中资产出发做 BFS 扩展（≤ max_hops 跳，只走认证边）。

    确定性：邻接边按 (对端资产, 边全字段) 排序后遍历，同一输入的
    BFS 访问顺序与输出顺序恒定；已访问资产不重复入队（环安全）。
    起点资产本身**不**出现在结果里（图扩展只补新资产）。
    """
    asset_index = view.asset_index()

    def edge_usable(edge: JoinEdge) -> bool:
        """只沿已认证路径：边有 certified_by，两端资产存在且 certified。"""
        if not edge.certified_by:
            return False
        for name in (edge.left_asset, edge.right_asset):
            other = asset_index.get(name)
            if other is None or not other.certified:
                return False
        return True

    adjacency: dict[str, list[tuple[str, JoinEdge]]] = {}
    for edge in view.joins:
        if not edge_usable(edge):
            continue
        adjacency.setdefault(edge.left_asset, []).append((edge.right_asset, edge))
        adjacency.setdefault(edge.right_asset, []).append((edge.left_asset, edge))
    for neighbors in adjacency.values():
        neighbors.sort(key=lambda pair: (pair[0], pair[1].left_asset, pair[1].right_asset,
                                         pair[1].left_column, pair[1].right_column))

    visited: set[str] = set(start_assets)
    queue: list[tuple[str, int, tuple[JoinEdge, ...]]] = [
        (name, 0, ()) for name in dict.fromkeys(start_assets) if name in asset_index
    ]
    hits: list[GraphHit] = []

    while queue:
        current, hop, path = queue.pop(0)
        if hop >= max_hops:
            continue
        for neighbor, edge in adjacency.get(current, ()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            new_path = (*path, edge)
            hits.append(GraphHit(asset=neighbor, hop=hop + 1, path=new_path))
            queue.append((neighbor, hop + 1, new_path))

    # BFS 出队顺序本身确定；再按 (hop, asset) 稳定排序，与遍历顺序解耦。
    hits.sort(key=lambda h: (h.hop, h.asset))
    return tuple(hits)
