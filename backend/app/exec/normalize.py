"""结果集类型归一化 —— JSON 安全契约的**唯一**实现点（07 §8.4）。

归属窗口：W2D（docs/08 §4.1：`app/exec/**`）。

--------------------------------------------------------------------------------
为什么按「Python 类型」归一化，而不是按 PG 类型 OID
--------------------------------------------------------------------------------

psycopg3 返回的已经是 Python 对象（`Decimal` / `int` / `datetime` / `memoryview`…），
SQLAlchemy 流式游标再包一层后拿不到稳定的 `pg_type` OID。而 07 §8.4 的每条规则
都可以表述为 Python 类型的判据，且**判据本身就覆盖了类型差异**：

| 07 §8.4 的 PG 视角规则 | Python 判据（本实现） | 为什么等价 |
|---|---|---|
| `numeric` → 字符串保精度 | `Decimal` → `str()`（`NaN`→`None`） | psycopg 只把 numeric 返回成 `Decimal` |
| `bigint` 超 2^53 → 字符串 | `int` 且 `abs > 2^53-1` → `str()` | 小整数（int2/4/8）统一走"number"，越界才转字符串 —— 阈值判据天然覆盖 int8 |
| `float` NaN/±Inf → null | `float` 且 `isnan/isinf` → `None` | 同上 |
| `timestamptz` → ISO 带 +08:00 | aware → `astimezone(TZ)`；naive → 附 TZ | naive 只可能是 `timestamp`（无时区）|
| `bytea` 不返回 | `bytes`/`memoryview` → 占位符 | — |

唯一的代价：**列名层面**不知道原始 PG 类型（`ColumnMeta.type_name` 记的是归一化后的
类别名，不是 PG 类型名）——这已写进交付说明，若 W4/前端需要原始类型名，须由
语义包 `assets[].columns[].type` 在绑定层对齐，不在 exec 层造第二份类型映射。

**舍入纪律（07 §8.5）**：本模块**不做任何舍入** —— `exec` 层保真（对账用），
展示层（`present`，W3C）才允许格式化。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Final
from zoneinfo import ZoneInfo

__all__ = [
    "BYTEA_PLACEHOLDER",
    "JSON_MAX_DEPTH",
    "NORMALIZED_TYPE_NAMES",
    "JSON_DEPTH_PLACEHOLDER",
    "normalize_cell",
    "normalize_row",
]

#: `bytea` 的占位符（07 §8.4："不返回"，防二进制带出文件内容）。
BYTEA_PLACEHOLDER: Final[str] = "[binary omitted]"

#: json/jsonb 嵌套深度上限（07 §8.4："深度 > 5 时截断 + 标记"）。
#: 深度按容器层数计：顶层 dict/list = 1。
JSON_MAX_DEPTH: Final[int] = 5

#: 超深 json 的截断标记。
JSON_DEPTH_PLACEHOLDER: Final[str] = "[json depth truncated]"

#: 归一化后的类别名（进 `ColumnMeta.type_name`；07 §8.4 表的列别）。
#: ⚠️ 不含 str：字符串在 `normalized_type_name` 前置分支已处理（含占位符判定）。
NORMALIZED_TYPE_NAMES: Final[dict[type, str]] = {
    type(None): "null",
    bool: "boolean",
    int: "number",
    float: "number",
    Decimal: "decimal",
    datetime: "datetime",
    date: "date",
    time: "time",
    timedelta: "duration",
    dict: "json",
    list: "array",
    bytes: "binary_omitted",
    memoryview: "binary_omitted",
}


def _iso_duration(td: timedelta) -> str:
    """`timedelta` → ISO 8601 duration（07 §8.4：`interval` → ISO duration）。"""
    total = td.total_seconds()
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    out = f"{sign}P"
    if days:
        out += f"{int(days)}D"
    if hours or minutes or seconds or not days:
        out += "T"
        if hours or minutes or seconds or not days:
            if hours:
                out += f"{int(hours)}H"
            if minutes:
                out += f"{int(minutes)}M"
            if seconds or not (hours or minutes):
                # 秒带小数时保真（不做舍入，07 §8.5）
                sec_str = f"{seconds:.9f}".rstrip("0").rstrip(".")
                out += f"{sec_str}S" if sec_str else "0S"
    return out


def _normalize_json(value: Any, depth: int) -> Any:
    """json/jsonb 的递归归一化：元素同全局规则 + 深度 > 5 截断（07 §8.4）。"""
    if depth > JSON_MAX_DEPTH:
        return JSON_DEPTH_PLACEHOLDER
    if isinstance(value, dict):
        return {
            str(k): _normalize_json(v, depth + 1) if isinstance(v, (dict, list)) else normalize_cell(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _normalize_json(v, depth + 1) if isinstance(v, (dict, list)) else normalize_cell(v)
            for v in value
        ]
    return normalize_cell(value)


def normalize_cell(value: Any, *, tz: ZoneInfo | None = None) -> Any:
    """单格归一化（07 §8.4 表逐行）。**纯函数**：同一输入恒同一输出。

    `tz`：时间戳统一转换的目标时区（N-18 / 附录 A `TIMEZONE`，P0 = Asia/Shanghai）。
    缺省用 Asia/Shanghai —— 测试注入其他值仅为断言行为，不改变生产路径。
    """
    tz = tz or ZoneInfo("Asia/Shanghai")

    if value is None:
        return None
    if isinstance(value, bool):  # ⚠️ 必须在 int 之前：bool 是 int 的子类
        return value
    if isinstance(value, Decimal):
        # numeric → 字符串保精度（不得转 float，财务场景不可接受）。
        # Decimal('NaN') 是合法值，str 后成 "NaN" 会污染下游 —— 归入 null（JSON 安全优先）。
        if value.is_nan():
            return None
        return str(value)
    if isinstance(value, int):
        # bigint 超 2^53-1 转 JS 安全字符串；小整数保持 number
        if abs(value) > 2**53 - 1:
            return str(value)
        return value
    if isinstance(value, float):
        # JSON 不支持 NaN / ±Infinity：显式判，否则序列化报错或前端拿到 NaN
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        # naive = timestamp（无时区）→ 附目标时区；aware = timestamptz → astimezone。
        # 一律转 Asia/Shanghai（N-18），ISO 8601 带 +08:00 输出。
        aware = value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
        return aware.isoformat()
    if isinstance(value, date):
        return value.isoformat()  # YYYY-MM-DD
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return _iso_duration(value)
    if isinstance(value, (bytes, memoryview, bytearray)):
        # bytea 不返回 + 审计告警面（告警的接线归 W4：exec 不持 AuditSinkPort，
        # 命中信息通过 ColumnMeta.type_name = "binary_omitted" 可观测）
        return BYTEA_PLACEHOLDER
    if isinstance(value, (dict, list)):
        return _normalize_json(value, depth=1)
    # 未知类型：str() 兜底而不是 fail-closed —— exec 的契约是"JSON 安全"，
    # 任何 PG 类型都会被 psycopg 落进上面某一类；str 兜底是防御未知第三方的最后防线。
    return str(value)


def normalize_row(row: Sequence[Any], *, tz: ZoneInfo | None = None) -> tuple[Any, ...]:
    """整行归一化。"""
    return tuple(normalize_cell(v, tz=tz) for v in row)


def normalized_type_name(value: Any) -> str:
    """归一化后的类别名（进 `ColumnMeta.type_name`）。

    ⚠️ 输入应是**已归一化**的值（或原始值）；按"归一化后的 Python 类型"归类。
    """
    if value is None:
        return "null"
    if isinstance(value, str):
        if value in (BYTEA_PLACEHOLDER, JSON_DEPTH_PLACEHOLDER):
            # 占位符不可与正常字符串区分是已知取舍：宁可多标一列 binary_omitted，
            # 也不在值里塞结构（那会让前端按内容猜类型 —— 更不可测）
            return "binary_omitted" if value == BYTEA_PLACEHOLDER else "json"
        return "string"
    for py_type, name in NORMALIZED_TYPE_NAMES.items():
        if isinstance(value, py_type):
            return name
    return "string"


def raw_type_name(value: Any) -> str:
    """**原始**（psycopg 返回、未归一化）值的类别名。

    ⚠️ `ColumnMeta.type_name` 必须用本函数（在归一化**之前**判型）：
    归一化把 `Decimal` 变成了字符串，再判型就永远是 "string" —— 金额列会
    丢失"decimal"标注，前端按字符串渲染数字列（07 §8.4 的类别信息是给
    present/前端的契约，不是内部细节）。
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, int):
        return "string" if abs(value) > 2**53 - 1 else "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    if isinstance(value, timedelta):
        return "duration"
    if isinstance(value, dict):
        return "json"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (bytes, memoryview, bytearray)):
        return "binary_omitted"
    return "string"
