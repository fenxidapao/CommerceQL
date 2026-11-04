"""`app.audit_export_log` 的**只写**数据访问对象（Phase B B2）。

层号：L0｜归属窗口：Phase B B2（`计划_合并版 §4 B2`）。

--------------------------------------------------------------------------
一、为什么导出审计单独一张表、单独一个 DAO
--------------------------------------------------------------------------
`app/repo/audit_store.py` 管的是**查询级两段式**（段 1 `audit_log` 有 `UNIQUE(task_id)`，
段 2 `audit_log_supplement` 以外键挂它）。导出是**另一个动作**，发生在查询结束之后：
它没有"前段"可写，而 `audit_log` 那些 NOT NULL 列（`raw_question` / `outcome` /
`tables_accessed` / `columns_accessed` …）对导出行没有意义，只能填占位值 ——
那正是本项目已实锤四次的"一个字段两个语义"病害。

表的形状与 append-only 三重保险在迁移 `0009_audit_export_log.py`。

--------------------------------------------------------------------------
二、append-only 第三重（代码层）的落点：**本文件只能有 INSERT**
--------------------------------------------------------------------------
`backend/tests/unit/test_audit_export_store.py` 用与 `test_audit_writer.py` **同一个正则**
扫本文件（`test_audit_writer.py:61` 的 `_MUTATION`）：出现针对审计导出表的改、删语句即红。
所以：

- 本文件**只**提供 `insert_export_log()`；不提供改、不提供删、不提供清空；
- `ON CONFLICT` 也不得出现：`DO UPDATE` 会让"同一个 task 的导出行被覆盖"成为可能，
  而导出行是"**发生过一次导出**"的凭证；
- 身份列（`task_id` / `tenant_id` / `user_id` / `role`）**只能来自服务端 `IdentityContext`**，
  payload 试图自带身份列即抛 `ExportSchemaMismatch`（与 `audit_store.insert_audit_log`
  同一条纪律：让请求方决定"谁干的"等于审计失效）。

--------------------------------------------------------------------------
三、为什么收 `AsyncEngine` 而不是连接
--------------------------------------------------------------------------
同 `audit_store.AuditStore`：借用/归还必须**每语句一次**（07 §8.1 纪律 1：LLM 期间不持连接）。
传连接对象会让"谁负责归还"变得含糊，而漏归还的表现是池被慢慢抽干。
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = [
    "EXPORT_BINDINGS",
    "EXPORT_FORMAT_CSV",
    "EXPORT_IDENTITY_COLUMNS",
    "EXPORT_PAYLOAD_COLUMNS",
    "EXPORT_REQUIRED_COLUMNS",
    "EXPORT_TABLE",
    "AuditExportStore",
    "ExportSchemaMismatch",
]

EXPORT_TABLE: Final[str] = "app.audit_export_log"

#: 身份列 —— **只能来自 `IdentityContext`**（见模块 docstring §二）。
#: `export_id` / `timestamp` 由数据库生成（`GENERATED ALWAYS AS IDENTITY` / `DEFAULT now()`），
#: 应用侧**故意不留接口**：多一个可写字段 = 多一个让"导出发生在何时"失真的入口。
EXPORT_IDENTITY_COLUMNS: Final[tuple[str, ...]] = ("task_id", "tenant_id", "user_id", "role")

#: 业务列（= 迁移 `0009` 的列集减去身份四项与数据库生成项）。
EXPORT_PAYLOAD_COLUMNS: Final[frozenset[str]] = frozenset(
    {"export_format", "row_count", "truncated"}
)

#: `NOT NULL` 且**无默认值**的列 —— 缺了只能靠数据库报错，而数据库报错会被包成
#: "写失败了"的模糊结论。提前判出来，错误信息才能指出**缺的是哪个字段**
#: （N-11 不禁止我们指出自己的字段名）。
EXPORT_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset({"row_count"})

#: P0 唯一的导出格式。**不在迁移里写 CHECK**：取值集归 `core/enums`，
#: 迁移里再写一份 = 枚举变更时被迫重写迁移（`0008` 对 `role` 的同款裁定）。
EXPORT_FORMAT_CSV: Final[str] = "csv"

#: 列 → 绑定表达式（**单一实现**）。
#: 本表没有 `jsonb` / `text[]` 列，故不需要 `CAST`；保留这层间接是为了与
#: `audit_store._binding` 同形 —— 将来加数组列时只改一处，不必在两份 DAO 里各写一遍。
EXPORT_BINDINGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        name: f":{name}"
        for name in (*EXPORT_IDENTITY_COLUMNS, *sorted(EXPORT_PAYLOAD_COLUMNS))
    }
)


class ExportSchemaMismatch(ValueError):
    """payload 与导出审计表契约不符（未登记的列 / 缺必填列 / 试图覆盖身份列）。

    ⚠️ `ValueError` 的子类而**不是** `CommerceQLError`：这是**编程错误**（代码与表不一致），
    不是运行时故障。它不该被包装成"审计写失败"—— 那会把"字段名写错了"和
    "数据库连不上"混成同一个错误码，排查方向直接跑偏（同 `AuditSchemaMismatch` 的理由）。
    """


def _build_insert(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """装配 `INSERT`。**本文件里唯一拼 SQL 的地方**。

    ⚠️ 列名是**拼进** SQL 的（绑定参数只能绑值）。安全前提 = 列名先过 `EXPORT_BINDINGS`
    白名单（下面第一个循环）。任何"直接把 dict 的键拼进 SQL"的写法都是注入面，
    而这里恰好是最容易被写成注入面的地方。
    """
    unknown = sorted(set(row) - set(EXPORT_BINDINGS))
    if unknown:
        raise ExportSchemaMismatch(
            f"{EXPORT_TABLE}: payload 含未登记的列名 {unknown}；"
            f"已登记的白名单见 `app/repo/audit_export_store.py`。"
            f"（**不静默丢弃**：审计字段集漂移必须是显式事件）"
        )
    missing = sorted(EXPORT_REQUIRED_COLUMNS - set(row))
    if missing:
        raise ExportSchemaMismatch(f"{EXPORT_TABLE}: 缺少必填列 {missing}")

    columns = list(row)
    sql = (
        f"INSERT INTO {EXPORT_TABLE} ({', '.join(columns)}) "
        f"VALUES ({', '.join(EXPORT_BINDINGS[c] for c in columns)})"
    )
    return sql, dict(row)


class AuditExportStore:
    """`app.audit_export_log` 的**只写**数据访问对象（见模块 docstring §二）。"""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def insert_export_log(
        self, identity: Mapping[str, Any], payload: Mapping[str, Any]
    ) -> None:
        """写一条导出审计。**失败必须向上抛**（由调用方决定 fail-closed）。

        ⚠️ 本方法**不 catch 异常**：catch 在这里会把"审计写失败"变成
        "审计写失败的日志"，而调用方要的是**阻断**（审计失败 ⇒ 不下发文件）。
        """
        overlap = sorted(set(payload) & set(EXPORT_IDENTITY_COLUMNS))
        if overlap:
            raise ExportSchemaMismatch(
                f"{EXPORT_TABLE}: payload 试图提供身份列 {overlap} —— "
                f"身份一律来自服务端 `IdentityContext`（07 §13.1 第 2 条；"
                f"让请求方决定『谁干的』等于审计失效）"
            )
        missing_identity = sorted(set(EXPORT_IDENTITY_COLUMNS) - set(identity))
        if missing_identity:
            raise ExportSchemaMismatch(f"{EXPORT_TABLE}: 缺少身份列 {missing_identity}")

        sql, params = _build_insert({**dict(identity), **dict(payload)})
        async with self._engine.begin() as conn:
            await conn.execute(text(sql), params)
