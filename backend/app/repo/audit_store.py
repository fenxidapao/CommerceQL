"""审计落库 —— **只有 INSERT**（07 §12.4 第 ③ 层的数据访问面）。

归属窗口：W1B（`app/repo/**`）。

## 与 `app/obs/audit.py` 的分工（§12.4.1 裁定的落地形态）

| 文件 | 层 | 职责 |
|---|---|---|
| `app/obs/audit.py` | L1 | **语义**：两段式的阻断性（fail-closed vs 非阻断）、把 `IdentityContext` 拆成身份列 |
| 本文件 | L0 | **事实**：列名、类型转换、SQL 文本 |

拆开是为了让两边各自唯一：**列名与类型只在 L0 出现一次**（避免"代码以为列叫 A、库里的列叫 B"），
**阻断性只在 L1 出现一次**（避免两个地方各自决定"失败了要不要抛"）。

## ⚠️ 本文件的三条硬约束（由 `tests/unit/test_audit_writer.py` 静态断言）

1. **只暴露 `insert_*`**：没有任何 `update` / `delete` / `truncate` 方法；
2. **SQL 文本里不出现针对审计表的 `UPDATE` / `DELETE` / `TRUNCATE` 语句**；
3. **列名一律来自本文件的常量白名单**，payload 里出现未登记的名字 → **直接报错**
   （而不是静默丢弃 —— 静默丢弃会让"审计少记了一个字段"在几个月后才被发现）。

第 3 条容易被当成"不必要地严格"。它的理由具体：W4 写审计时会传一个 dict，
而 dict 的键来自 `GraphState` 的字段名。**字段名漂移**（例如 `sql_text` 改名 `final_sql`）
在动态列名实现下表现为"多了一列 / 少了一列"，没有任何报错；在严格实现下**当次就红**。
审计是"事后唯一能还原现场的东西"，它的字段集漂移必须是显式事件。

## ⚠️ 身份列**不接受** payload 提供

`insert_audit_log(identity, payload)` 刻意拆成**两个参数**而不是"一个合并好的 row"。
理由：合并成 dict 时，`payload` 里的 `role` 会**静默覆盖** `identity` 里的 `role`
（`{**identity, **payload}` 的语义），于是"谁干的"变成请求方可控 —— 而审计的全部价值
就在于它**不可被请求方影响**。拆开之后这个覆盖在结构上不可能发生，并且会被显式拒绝。

## ⚠️ 已知缺口：`audit_log` 暂时是**普通表**而非分区表

07 §12.4 要求按月分区、过期 `DROP PARTITION`。迁移 `0001` 出于"P0 数据量远达不到归档量级 +
分区会引入『下月分区谁建』的运维依赖"而**刻意未做**，并在该文件里写明了触发条件与连带改动
（PK 必须含分区键 → 段 2 的 FK 要改）。本文件因此**不假设分区存在**：
插入语句不指定目标分区，也不依赖分区裁剪。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = [
    "AUDIT_IDENTITY_COLUMNS",
    "AUDIT_PAYLOAD_COLUMNS",
    "AUDIT_REQUIRED_COLUMNS",
    "AUDIT_TABLE",
    "SUPPLEMENT_PAYLOAD_COLUMNS",
    "SUPPLEMENT_REQUIRED_COLUMNS",
    "SUPPLEMENT_TABLE",
    "AuditSchemaMismatch",
    "AuditStore",
]

AUDIT_TABLE: Final[str] = "app.audit_log"
SUPPLEMENT_TABLE: Final[str] = "app.audit_log_supplement"

#: 身份列 —— **只能来自 `IdentityContext`**（见文件头第 2 条）。
#:
#: `log_id` / `timestamp` 由数据库生成（`GENERATED ALWAYS AS IDENTITY` / `DEFAULT now()`），
#: 应用侧**故意不留接口**（多一个可写字段 = 多一个让审计时间失真的入口）。
AUDIT_IDENTITY_COLUMNS: Final[tuple[str, ...]] = ("task_id", "tenant_id", "user_id", "role")

#: 段 1 的 payload 列（= 迁移 `0001` 的 `app.audit_log` 列集减去身份四项与数据库生成项）。
AUDIT_PAYLOAD_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "raw_question",
        "final_executed_sql",
        "tables_accessed",
        "columns_accessed",
        "row_count_returned",
        "pii_columns_hit",
        "truncated",
        "scope_level",
        "bundle_version",
        "prompt_version",
        "model_version",
        "latency_ms",
        "outcome",
        "refusal_reason",
    }
)

#: 段 1 里 `NOT NULL` 且**无默认值**的列 —— 缺了它们只能靠数据库报错，
#: 而数据库报错会被 `obs/audit.py` 包成 `AuditWriteFailed`（一个"写失败了"的模糊结论）。
#: 提前判出来，错误信息才能指出**缺的是哪个字段**（N-11 不禁止我们指出自己的字段名）。
AUDIT_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset({"raw_question", "outcome"})

#: 段 2 的 payload 列（`task_id` 单独传入，另有主键 + 外键约束）。
SUPPLEMENT_PAYLOAD_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "cache_hit_tokens",
        "cost_cny",
        "latency_ms_present",
        "chart_type",
        "insight_hash",
        "degradations",
    }
)

#: 段 2 全部列都有默认值 → **没有**必填项。这不是"宽松"：
#: 段 2 的语义是"补充信息，失败也不阻断"，强加必填项只会制造一个
#: "因为少了一个可选指标所以审计不完整"的假故障。
SUPPLEMENT_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset()

#: 需要 `jsonb` 转换的列。
#: ⚠️ 必须显式 `CAST`：psycopg3 把 Python `str` 按 `text` 绑定，
#: 而 `text → jsonb` **没有隐式转换**（PG 直接报 `column is of type jsonb but expression is of type text`）。\n
_JSONB_COLUMNS: Final[frozenset[str]] = frozenset({"latency_ms"})

#: 需要 `text[]` 转换的列。同理：不给目标类型提示时，psycopg 在**参数化**语句里
#: 没有足够信息决定元素类型（`list[str]` 与 `list[int]` 都可以是数组）。
_ARRAY_COLUMNS: Final[frozenset[str]] = frozenset(
    {"tables_accessed", "columns_accessed", "pii_columns_hit", "degradations"}
)


def _binding(name: str) -> str:
    """列 → 绑定表达式（**单一实现**，两张表的绑定都从这里来）。

    ⚠️ 与白名单**同一个来源**：若"允许哪些列"与"这些列怎么绑"分成两份表，
    新增列时漏改一处就会得到一条**用错了转换**的 SQL（`jsonb` 列按 `text` 绑），
    而它只在运行时、只在有值时才报错。
    """
    if name in _JSONB_COLUMNS:
        return f"CAST(:{name} AS jsonb)"
    if name in _ARRAY_COLUMNS:
        return f"CAST(:{name} AS text[])"
    return f":{name}"


AUDIT_IDENTITY_BINDINGS: Final[Mapping[str, str]] = MappingProxyType(
    {name: _binding(name) for name in AUDIT_IDENTITY_COLUMNS}
)
AUDIT_PAYLOAD_BINDINGS: Final[Mapping[str, str]] = MappingProxyType(
    {name: _binding(name) for name in sorted(AUDIT_PAYLOAD_COLUMNS)}
)
SUPPLEMENT_BINDINGS: Final[Mapping[str, str]] = MappingProxyType(
    {name: _binding(name) for name in ("task_id", *sorted(SUPPLEMENT_PAYLOAD_COLUMNS))}
)


class AuditSchemaMismatch(ValueError):
    """payload 与审计表契约不符（未登记的列名 / 缺必填列 / 试图覆盖身份列）。

    ⚠️ `ValueError` 的子类而**不是** `CommerceQLError`：这是**编程错误**（代码与表不一致），
    不是运行时故障。它不该被 `obs/audit.py` 包装成 `AuditWriteFailed` ——
    那会把"字段名写错了"和"数据库连不上"混成同一个错误码，排查方向直接跑偏。
    """


def _build_insert(
    table: str, row: Mapping[str, Any], bindings: Mapping[str, str], required: frozenset[str]
) -> tuple[str, dict[str, Any]]:
    """装配 `INSERT`。**本文件里唯一拼 SQL 的地方**。

    ⚠️ 列名是**拼进** SQL 的（绑定参数只能绑值）。这是安全的，但前提是列名**先过了白名单** ——
    即下面那个循环里的 `bindings` 键。任何"直接把 dict 的键拼进 SQL"的写法都是注入面，
    而这里恰好是最容易被写成注入面的地方（`", ".join(row.keys())` 太顺手了）。
    """
    unknown = sorted(set(row) - set(bindings))
    if unknown:
        raise AuditSchemaMismatch(
            f"{table}: payload 含未登记的列名 {unknown}；"
            f"已登记的白名单见 `app/repo/audit_store.py`。"
            f"（**不静默丢弃**：审计字段集漂移必须是显式事件）"
        )
    missing = sorted(required - set(row))
    if missing:
        raise AuditSchemaMismatch(f"{table}: 缺少必填列 {missing}")

    columns = list(row)
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(bindings[c] for c in columns)})"
    return sql, dict(row)


def _normalize_value(name: str, value: Any) -> Any:
    """`jsonb` 列接受 dict/list/str；其余原样。

    ⚠️ 只对 `jsonb` 做转换 —— 给 `text[]` 列做 `json.dumps` 会把它变成**一个元素的数组**，
    而这种错误在库里"看起来有数据"，只在消费端按元素遍历时才暴露。
    """
    if name in _JSONB_COLUMNS and not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return value


def _prepare(row: Mapping[str, Any]) -> dict[str, Any]:
    return {name: _normalize_value(name, value) for name, value in row.items()}


class AuditStore:
    """`app.audit_log` / `app.audit_log_supplement` 的**只写**数据访问对象。

    ⚠️ 它接收的是 **SQLAlchemy `AsyncEngine`（元数据池）**，不是连接：
    借用/归还必须**每语句一次**（07 §8.1 纪律 1：LLM 期间不持有连接）。
    传入连接对象会让"谁负责归还"变得含糊，而漏归还的表现是池被慢慢抽干。
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def insert_audit_log(
        self, identity: Mapping[str, Any], payload: Mapping[str, Any]
    ) -> None:
        """段 1：写 `audit_log`。**失败必须向上抛**（由 `obs/audit.py` 决定 fail-closed）。

        ⚠️ 本方法**不 catch 异常**：catch 在这里会让"审计写失败"变成
        "审计写失败的日志"，而 N-09 要的是**阻断**。
        """
        overlap = sorted(set(payload) & set(AUDIT_IDENTITY_COLUMNS))
        if overlap:
            raise AuditSchemaMismatch(
                f"{AUDIT_TABLE}: payload 试图提供身份列 {overlap} —— "
                f"身份一律来自服务端 `IdentityContext`（07 §13.1 第 2 条；"
                f"让请求方决定『谁干的』等于审计失效）"
            )
        missing_identity = sorted(set(AUDIT_IDENTITY_COLUMNS) - set(identity))
        if missing_identity:
            raise AuditSchemaMismatch(f"{AUDIT_TABLE}: 缺少身份列 {missing_identity}")

        row = _prepare({**dict(identity), **dict(payload)})
        sql, params = _build_insert(
            AUDIT_TABLE,
            row,
            MappingProxyType({**AUDIT_IDENTITY_BINDINGS, **AUDIT_PAYLOAD_BINDINGS}),
            AUDIT_REQUIRED_COLUMNS,
        )
        async with self._engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def insert_supplement(self, task_id: str, payload: Mapping[str, Any]) -> None:
        """段 2：写 `audit_log_supplement`。**失败同样向上抛** ——

        "非阻断"是 `obs/audit.py` 的**策略**（由它决定要不要吞掉异常），不是本层的事实。
        在数据访问层吞掉异常，会让那个策略永远收不到信号 ——
        于是"段 2 一直静默失败、成本与 token 永远为 0"这件事将无法被任何人发现。
        """
        row = _prepare({"task_id": task_id, **dict(payload)})
        sql, params = _build_insert(
            SUPPLEMENT_TABLE, row, SUPPLEMENT_BINDINGS, SUPPLEMENT_REQUIRED_COLUMNS
        )
        async with self._engine.begin() as conn:
            await conn.execute(text(sql), params)
