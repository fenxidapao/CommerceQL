"""`data` 载荷的唯一构造点 + 载荷读取工具（L4 叶子模块，零 `app.*` 依赖）。

层号：L4｜归属窗口：W4（`docs/08 §4.1`：`app/graph/**`）。

--------------------------------------------------------------------------
一、为什么单独一个文件（不是"把几个小函数挪个位置"）
--------------------------------------------------------------------------
`data` 载荷要在**两处**产出，且两处必须**逐字同构** —— 附录 A §A.2 的原话是轮询的
`data`"与 SSE 的 `data` 帧同构"：

| 产出点 | 用途 | 谁是权威 |
|---|---|---|
| `app/graph/events.py` 的 `audit_pre` 分支 | 本次下发的 SSE `data` 帧 | 线上唯一真相 |
| `app/graph/nodes/mask.py` | 结果集缓存 `result:{tenant}:{task_id}`（TTL 1h） | 异步 / 重放 / B2 导出读它 |

而 `nodes/mask.py` **不能** import `events.py`：后者 `from app.graph.nodes import …`
（发射点映射要节点名）⇒ `events → nodes → mask → events` 是**真 import 环**，
不是"看起来别扭"。跨模块 import 私有名（`_jsonable` / `_amount_unit`）也被既有纪律否掉
（`api/routers/query.py:124` 的注释：跨模块 import 私有名会让"改一处"变成"改两处"）。

⇒ 载荷装配与"能不能读出键"这两件事下沉到本模块。本模块是**叶子**：
只 import 标准库，故 `events.py` 与 `nodes/mask.py` 都能 import 它而不成环。

--------------------------------------------------------------------------
二、三条边界（违反任一条，本模块就失去存在理由）
--------------------------------------------------------------------------
1. **不解释载荷**（G-1）：只做"能不能读出键"的最小转换，不判断内容对不对 ——
   读不出就返回空 `Mapping`，让下游按"缺字段"处理，而不是在这里猜。
2. **不 import 任何 `app.*`**：这条是 §一 那个 import 环的唯一解法。
3. **`data_payload()` 是 `data` 载荷的唯一构造点**：SSE 帧与结果集缓存都调它，
   键集由 `DATA_PAYLOAD_KEYS` 一处决定。两处各写一份字典 = 一次改动只改到一处，
   而漂移**不会报错**（前端只是把某一列的单位标错）。
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any, Final

__all__ = [
    "DATA_PAYLOAD_KEYS",
    "amount_unit",
    "as_mapping",
    "as_sequence",
    "data_payload",
    "jsonable",
]

#: `data` 载荷的键集（**唯一声明处**）。改这里 = 同时改 SSE 帧与结果集缓存，
#: 以及轮询侧的裁剪白名单（`api/routers/query.py::poll_query` 按本常量裁缓存载荷，
#: 缓存里的内部读数如 `fingerprint` 因此不会漏到响应里）。
DATA_PAYLOAD_KEYS: Final[tuple[str, ...]] = (
    "columns",
    "rows",
    "row_count",
    "truncated",
    "amount_unit",
)


def as_mapping(value: Any) -> Mapping[str, Any]:
    """尽力把值读成 `Mapping`（`Mapping` / pydantic / dataclass / 裸 `__slots__` 四种形态）。

    读不出就返回空 `Mapping` —— 让下游按"缺字段"处理，而不是在这里编一个键。
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    if is_dataclass(value) and not isinstance(value, type):
        dumped_dataclass = asdict(value)
        if isinstance(dumped_dataclass, Mapping):
            return dumped_dataclass
    # `frozen=True, slots=True` 的 dataclass 走上面那条；其余带 `__slots__` 的值对象走这条。
    slots = getattr(value, "__slots__", None)
    if slots:
        return {name: getattr(value, name, None) for name in slots}
    return {}


def as_sequence(value: Any) -> Sequence[Any]:
    """把值读成序列。

    ⚠️ 字符串按**单元素序列**处理（`(value,)`），不是字符序列 —— 否则一个列名字符串
    会被展开成逐字符的"列"。
    """
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Sequence):
        return value
    return ()


def jsonable(value: Any) -> Any:
    """dataclass / 枚举 / 嵌套结构 → 可 JSON 序列化的形态。

    ⚠️ 两个消费者都靠它：`api/sse.encode()` 走 `json.dumps`（未转换的 dataclass 会在
    **编码时**抛 `TypeError`，错误发生在 SSE 生成器内部、表现为连接中断、归因极难）；
    `nodes/mask.py` 走 `orjson.dumps`（`ColumnMeta` 不是 orjson 的原生类型，
    退回 `default=str` 会把列元数据变成一个 repr 字符串 —— 前端拿到的 `columns` 就成了字符串）。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [jsonable(v) for v in value]
    dumped = as_mapping(value)
    if dumped:
        return {str(k): jsonable(v) for k, v in dumped.items()}
    return str(value)


def amount_unit(columns: Sequence[Any]) -> Any:
    """`data.amount_unit`：`columns` 中**唯一**的 `unit`。

    ⚠️ 多个不同单位 → `None`（**不猜**）：`amount_unit` 是"整张表的金额单位"，
    混合单位时给任意一个都会让前端把数字标错量级。
    """
    units = {as_mapping(c).get("unit") for c in columns}
    units.discard(None)
    return units.pop() if len(units) == 1 else None


def data_payload(
    *,
    columns: Sequence[Any],
    rows: Any,
    row_count: Any,
    truncated: Any,
) -> dict[str, Any]:
    """`data` 载荷（SSE 帧与结果集缓存的**同一份形状**）。

    ⚠️ `columns` 收**列元数据对象**（`core.contracts.ColumnMeta`），不收列名字符串：
    帧里的 `columns` 是 `{name, type_name, unit}`，且帧里还有 `amount_unit`。
    只存列名的话，读回方必须自己再拼一遍元数据 —— 那就是同一份下发内容两种形状。
    """
    return {
        "columns": [jsonable(c) for c in columns],
        "rows": jsonable(rows),
        "row_count": row_count,
        "truncated": truncated,
        "amount_unit": amount_unit(columns),
    }
