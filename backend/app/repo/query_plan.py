"""`query_plan` 落库 —— **只写**（07 §12.3:2349 表的唯一写入通道）。

归属窗口：W1B（`app/repo/**`）。表结构 = 迁移 `0004`（列集与本文档的写入面**必须逐字相等**，
由 `tests/unit/test_query_plan_store.py` 的静态断言 + 集成往返共同钉死）。

派单来源：W4 统一转述件 `reports/w4/RELAY.md §二`（阻塞 T7 = W3C DoD① 的最后一步）。
W4 原文给的形态选项之一即"走既有池并注明池名"——本实现取这条：

## 为什么复用**元数据池**而不是再开一条连接

| 方案 | 结论 |
|---|---|
| 单条专用同步连接（比照 `DbCostLedgerSink`） | ❌ 那是**同步 Protocol** 逼出来的形态；本通道的调用方（W4 图节点）本身在 async 上下文里，同步连接只会多一个长连资源 + 一个 `close()` 装配责任 |
| **本实现：`QueryPlanStore(engine)` 收元数据池 `AsyncEngine`** | ✅ 与 `app/repo/audit_store.py::AuditStore` **同一形态**（既有先例，W4 装配时传 `pools.metadata`）；零新增连接资源、零 shutdown 责任、无 search_path 依赖（表名 schema 限定） |

⚠️ 复用池**不等于**可以持有连接：每次写入都是独立 `engine.begin()`，
借用/归还逐语句完成（07 §8.1 纪律 1：LLM 期间不持有连接）。表名里没有参数，
SQL 文本里也没有 —— 参数全部走绑定。

## 三层边界（与 audit_store 同款分层，理由一致）

| 层 | 文件 | 职责 |
|---|---|---|
| 语义 | W4（图节点） | 何时写、写什么（`plan_summary` 结构按 C-01、`plan_json` 含 `schema_version`） |
| 事实 | **本文件** | 列名、类型转换、SQL 文本、枚举 → 字面值 |

## 四条硬约束（`tests/unit/test_query_plan_store.py` 静态断言）

1. **只暴露 `insert_query_plan`**：没有任何 `update` / `delete` / `truncate` / `upsert` 方法；
2. SQL 文本里不出现针对本表的 `UPDATE` / `DELETE` / `TRUNCATE`；**也没有 `ON CONFLICT`**
   （见下"主键撞重"）；
3. **列名只在本文件出现一次**（`_COLUMNS` 白名单）——签名与 INSERT 语句都由它派生，
   不存两份（两份必然漂移，且漂移只在运行时暴露）；
4. **不 catch 异常**：写失败向上抛。阻断性归调用方定（同 `audit_store` 的裁定：
   在数据访问层吞异常 = 那个策略永远收不到信号）。

## 主键撞重 = **如实抛**，不做 upsert

`task_id` 是本表主键 ⇒ 一个任务一行。重复写入说明**图结构有问题**（同一 task 走了两次 plan 节点，
或重试逻辑没有按 task 隔离）。用 `ON CONFLICT DO UPDATE` 会把这种缺陷静默成"最后一次覆盖"，
而 `query_plan` 存在的意义恰恰是**事后诊断**——被覆盖的那次才是要查的那次。
`ON CONFLICT DO NOTHING` 同样不行：它让"写没写进去"变成不可知。

## `plan_summary` 存的是 **JSON 文本**（列类型 = `text`，见迁移 0004）

C-01 把 `plan_summary` 定义成结构化对象（`{metrics, dimensions, filters, grain, time_range, order_by, limit}`）。
列类型是 `text` ⇒ 传 `Mapping` 时本层序列化为 JSON 字符串入库（保证写入后能原样还原，
且不引入"存了一半的 dict 的 str() 形态"这种不可解析的脏数据）。传 `str` 则按原样存。

## `plan_json` 的 `schema_version`（07 §12.3 明文要求）

传 `Mapping` 时本层**校验 `schema_version` 在场**（缺 → 显式报错，而不是写一行没法版本化的计划）；
传 `str` 时由调用方自证（W4 保证，已在其 RELAY 声明）。两种形态都走 `CAST(... AS jsonb)`——
psycopg3 把 Python `str` 按 `text` 绑定，而 `text → jsonb` **无隐式转换**
（同 `audit_store._JSONB_COLUMNS` 踩过的坑：PG 直接报 `column is of type jsonb but expression is of type text`）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.enums import BindingLayer, BindingState

__all__ = ["QUERY_PLAN_COLUMNS", "QUERY_PLAN_REQUIRED_COLUMNS", "QUERY_PLAN_TABLE", "QueryPlanStore"]

QUERY_PLAN_TABLE: Final[str] = "app.query_plan"

#: 列白名单 —— **唯一来源**（迁移 0004 的列集，顺序即列序）。
#: 签名校验与 INSERT 语句都从这里派生；新增列时改这一处即可，
#: 「允许哪些列」与「SQL 用哪些列」分成两份表的写法必然漂移。
QUERY_PLAN_COLUMNS: Final[tuple[str, ...]] = (
    "task_id",
    "plan_json",
    "plan_summary",
    "bundle_version",
    "binding_state",
    "binding_layer",
    "confidence",
)

#: NOT NULL 且无默认值的列（迁移 0004 的 DDL）。
#: `binding_layer` / `plan_summary` / `confidence` 刻意不在内 —— 它们的可空性是 0004 明写的裁定
#: （unresolved 等态没有判定层/置信度可言）。
QUERY_PLAN_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"task_id", "plan_json", "bundle_version", "binding_state"}
)

#: 需要 `jsonb` 转换的列（`text → jsonb` 无隐式转换，必须显式 CAST）。
_JSONB_COLUMNS: Final[frozenset[str]] = frozenset({"plan_json"})

#: `schema_version` 的键名（07 §12.3 明文要求 `plan_json` 含它）。
_SCHEMA_VERSION_KEY: Final[str] = "schema_version"


class QueryPlanSchemaMismatch(ValueError):
    """写入面与表契约不符（缺必填列 / `plan_json` 缺 `schema_version`）。

    ⚠️ 是 `ValueError` 的子类而**不是** `CommerceQLError`：这是**编程错误**
    （调用方与表定义不一致），不是运行时故障。混进 `CommerceQLError` 会跟
    "库连不上"共用错误码，把排查方向带偏（同 `audit_store.AuditSchemaMismatch` 的裁定）。
    """


def _json_dumps(value: Any) -> str:
    """`ensure_ascii=False` + 紧凑分隔符：库里存的是给人看的诊断 JSON，中文不该变成转义序列。

    ⚠️ 与 `audit_store` 的 `json.dumps(value, ensure_ascii=False)` 保持一致（同一仓库一种写法）。
    """
    return json.dumps(value, ensure_ascii=False)


def _prepare_plan_json(plan_json: Mapping[str, Any] | str) -> str:
    """`plan_json` → 可绑定的字符串（`Mapping` 形态顺带校验 `schema_version`）。"""
    if isinstance(plan_json, str):
        return plan_json
    if not isinstance(plan_json, Mapping):
        raise QueryPlanSchemaMismatch(
            f"{QUERY_PLAN_TABLE}: plan_json 必须是 Mapping 或已序列化的 str，"
            f"收到 {type(plan_json).__name__}"
        )
    if _SCHEMA_VERSION_KEY not in plan_json:
        raise QueryPlanSchemaMismatch(
            f"{QUERY_PLAN_TABLE}: plan_json 缺 `{_SCHEMA_VERSION_KEY}` —— "
            f"07 §12.3 明文要求计划体自带版本号（没有版本号的计划行无法在 schema 演进后解读）"
        )
    return _json_dumps(dict(plan_json))


def _prepare_plan_summary(plan_summary: Mapping[str, Any] | str | None) -> str | None:
    """`plan_summary` → `text` 列的值（C-01 的结构化摘要序列化成 JSON 文本）。"""
    if plan_summary is None or isinstance(plan_summary, str):
        return plan_summary
    if not isinstance(plan_summary, Mapping):
        raise QueryPlanSchemaMismatch(
            f"{QUERY_PLAN_TABLE}: plan_summary 必须是 Mapping / str / None，"
            f"收到 {type(plan_summary).__name__}"
        )
    return _json_dumps(dict(plan_summary))


def _binding(name: str) -> str:
    """列 → 绑定表达式（**单一实现**，与 `_JSONB_COLUMNS` 同源）。"""
    return f"CAST(:{name} AS jsonb)" if name in _JSONB_COLUMNS else f":{name}"


#: INSERT 语句 —— 本文件里唯一拼 SQL 的地方。列名取自白名单常量（不是入参 dict 的键），
#: 因此不存在"把调用方的键拼进 SQL"的注入面。
_INSERT_SQL: Final[str] = (
    f"INSERT INTO {QUERY_PLAN_TABLE} ({', '.join(QUERY_PLAN_COLUMNS)}) "
    f"VALUES ({', '.join(_binding(c) for c in QUERY_PLAN_COLUMNS)})"
)


class QueryPlanStore:
    """`app.query_plan` 的**只写**数据访问对象。

    ⚠️ 它接收 **SQLAlchemy `AsyncEngine`（元数据池）**而不是连接：
    借用/归还必须**每语句一次**（07 §8.1 纪律 1）。传连接对象会让"谁负责归还"
    变得含糊，漏归还的表现是池被慢慢抽干（同 `AuditStore` 的裁定，见其 docstring）。
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def insert_query_plan(
        self,
        *,
        task_id: str,
        plan_json: Mapping[str, Any] | str,
        bundle_version: str,
        binding_state: BindingState,
        binding_layer: BindingLayer | None = None,
        plan_summary: Mapping[str, Any] | str | None = None,
        confidence: Decimal | None = None,
    ) -> None:
        """写一行计划（`task_id` 为键）。**失败向上抛** —— 本方法不 catch 任何异常。

        逐字覆盖迁移 `0004` 的列集：

        | 参数 | 列 | 约束 |
        |---|---|---|
        | `task_id` | `task_id` | PK；重复 = `UniqueViolation` 如实抛（不做 upsert） |
        | `plan_json` | `plan_json` | `Mapping` 必含 `schema_version`；`Mapping`/`str` 均可 |
        | `bundle_version` | `bundle_version` | NOT NULL（版本固定是审计前提） |
        | `binding_state` | `binding_state` | **枚举入参**（`BindingState`）→ 写 `.value` |
        | `binding_layer` | `binding_layer` | 可空；枚举入参（`BindingLayer`）→ `.value` |
        | `plan_summary` | `plan_summary` | 可空；`Mapping` → JSON 文本 |
        | `confidence` | `confidence` | 可空；`Decimal`（不要传 `float`，见下） |

        ⚠️ **枚举入参而不是裸字符串**：`binding_state`/`binding_layer` 的取值集在
        `app/core/enums.py`，CHECK 约束是它的冻结快照（迁移 0004）。让调用方传枚举
        ⇒ 拼错取值在**调用点**就红（`AttributeError`/类型检查），而不是等到运行时
        被 CHECK 拒绝（那时错误信息只是一串约束名，还得回头看是哪个字段）。
        CHECK 仍然是最后一道防线 —— 枚举由 Python 保证，CHECK 由数据库保证，两者不互替。

        ⚠️ **`confidence` 传 `Decimal` 而不是 `float`**：列是 `numeric`，
        `float` 会引入二进制表示误差（`0.1` → `0.1000000000000000055511151231257827`），
        诊断时看到的分数与打分器产出的分数不再相等。打分侧（W3C）产出的就是小数/Decimal，
        转换点应留在调用方。

        ⚠️ **异常是被 SQLAlchemy 包装过的**：经 `AsyncEngine` 执行时，DBAPI 异常成为
        `sqlalchemy.exc.IntegrityError` / `OperationalError` 等，原始 psycopg 异常在 `.orig`。
        调用方（W4）的捕获点用 SQLAlchemy 的类型；要区分"撞主键"与"别的完整性错误"，
        看 `exc.orig` 是不是 `psycopg.errors.UniqueViolation`（集成测试有该断言）。
        """
        values: dict[str, Any] = {
            "task_id": task_id,
            "plan_json": _prepare_plan_json(plan_json),
            "plan_summary": _prepare_plan_summary(plan_summary),
            "bundle_version": bundle_version,
            # StrEnum ⇒ 直接取出字符串字面值（与 CHECK 的冻结快照同源）
            "binding_state": str(binding_state.value),
            "binding_layer": None if binding_layer is None else str(binding_layer.value),
            "confidence": confidence,
        }
        # 必填项在这里判（而不是靠 DB 报 NOT NULL）：错误信息能指出**缺的是哪个字段**
        missing = sorted(c for c in QUERY_PLAN_REQUIRED_COLUMNS if values.get(c) is None)
        if missing:
            raise QueryPlanSchemaMismatch(f"{QUERY_PLAN_TABLE}: 缺少必填列 {missing}")

        async with self._engine.begin() as conn:
            await conn.execute(text(_INSERT_SQL), values)
