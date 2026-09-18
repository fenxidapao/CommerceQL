"""`feedback` 落库 —— 写出通道 + 幂等回读（07 §12.3:2354 表的访问层）。

归属窗口：W1B（`app/repo/**`）。表结构 = 迁移 `0005`（列集与本文档的写入面**必须逐字相等**，
由 `tests/unit/test_migration_0005_runtime_contract.py` 的静态比对 + 集成往返共同钉死）。

派单来源：W0 RELAY §9.1（"U-20 / 迁移 0005 归 W1B"）+ W4 决策点①（`queued_for_review` /
`corrected_sql` 无表可落）。契约 = `docs/02 §A.6`（请求字段与响应）+ `docs/07 §12.3`。

## 为什么复用**元数据池**（与 `QueryPlanStore` 同一裁定）

`feedback` 在 §12.3:2291 归 metadata 池（= `app_rw`），调用方（W4 端点）本身在 async 上下文里。
⇒ 收 `AsyncEngine`（`pools.metadata`），零新增连接资源、零 shutdown 责任（同
`audit_store.AuditStore` / `query_plan.QueryPlanStore`）。每次写入/读取都是独立
`engine.begin()` / `engine.connect()`，逐语句归还（07 §8.1 纪律 1）。

## 三层边界

| 层 | 文件 | 职责 |
|---|---|---|
| 语义 | W4（端点） | 何时写、`feedback_id` 从哪来、**幂等怎么组合**、`queued_for_review` 怎么定 |
| 事实 | **本文件** | 列名、类型转换、SQL 文本、枚举 → 字面值、NULL 比较语义 |

## 四条硬约束（静态断言，对齐 `query_plan.py`）

1. **只暴露 `insert_feedback` / `find_feedback_id`**：没有任何 `update` / `delete` / `truncate` / `upsert`；
2. SQL 文本里不出现针对本表的 `UPDATE` / `DELETE` / `TRUNCATE`，**也没有 `ON CONFLICT`**
   （理由：幂等由"回读 + 主键如实抛"表达，不用 upsert 把冲突静默成覆盖 —— 见下）；
3. **列名只在本文件出现一次**（`FEEDBACK_COLUMNS` 白名单），签名与 INSERT 都由它派生；
4. **不 catch 异常**：写失败向上抛（同 `audit_store`/`query_plan` 的裁定）。

## 幂等：**两个方法**，不在数据访问层替调用方做决定

§A.6 的幂等口径 =「同 `task_id` + 同 `reason_code` 视为同一条」，
物理实现 = `0005` 的 `uq_feedback_task_user_reason`（`NULLS NOT DISTINCT`）。
但"重复请求该返回哪条 id"是 **HTTP 语义**，属端点层：

```python
existing = await store.find_feedback_id(task_id=…, user_id=…, reason_code=…)
if existing is not None:
    return existing                      # 幂等命中：返回**同一条** feedback_id
feedback_id = new_id("feedback")          # 首次：id 的唯一来源仍是 obs.trace
await store.insert_feedback(feedback_id=feedback_id, …)
```

⚠️ 为什么不在本层做成 `upsert`：`ON CONFLICT DO UPDATE` 会把"用户改了归因后重发"
静默成覆盖（原始归因是 bad case 分析的证据）；`ON CONFLICT DO NOTHING` 会让
"到底写没写进去"不可知。两者都是把语义塞进数据层 —— 而 §A.6 要的恰恰是"同一条"，
它需要**读回那条已存在的记录**，不是"再写一次"。

## `feedback_id` 由调用方给（不在本层生成）

`feedback_id` 前缀 `fb` 由附录 A §A.6 明文给定（`"fb_01J8X7"`），生成器 = `app.obs.trace.new_id("feedback")`。
本层收 id 而不是自己造：**id 的唯一来源是 `obs.trace`**（同 W4 的 `state_store` 删掉
`new_task_id`/`new_session_id` 的裁定 —— 两处都能生成 id = 两份真相）。

## ⚠️ NULL 比较陷阱：同一个坑在**两处**，都要 `NULLS NOT DISTINCT` / `IS NOT DISTINCT FROM`

`reason_code` 可空（§A.6 标 ⭕），于是：

| 位置 | 天真写法 | 后果 |
|---|---|---|
| 唯一约束（已由 `0005` 处理） | `UNIQUE (task_id, user_id, reason_code)` | PG 里 `NULL != NULL` ⇒ 空归因可刷无限条，幂等失效 |
| 本文件的回读（本文件处理） | `reason_code = :reason_code` | `NULL = NULL` 为 NULL（非 true）⇒ **永远查不到已有的空归因记录**，幂等照样失效，且是"约束拦住了、回读没找到"的不一致形态 |

⇒ 唯一约束用 `UNIQUE NULLS NOT DISTINCT`，回读用 `IS NOT DISTINCT FROM`。**两处必须成对**。
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.enums import FeedbackReasonCode

__all__ = [
    "FEEDBACK_COLUMNS",
    "FEEDBACK_REQUIRED_COLUMNS",
    "FEEDBACK_TABLE",
    "FeedbackSchemaMismatch",
    "FeedbackStore",
]

FEEDBACK_TABLE: Final[str] = "app.feedback"

#: 列白名单 —— **唯一来源**（迁移 0005 的列集，顺序即列序）。
FEEDBACK_COLUMNS: Final[tuple[str, ...]] = (
    "feedback_id",
    "task_id",
    "user_id",
    "is_correct",
    "reason_code",
    "corrected_sql",
    "comment",
    "correct_result_hint",
)

#: NOT NULL 且无默认值的列（迁移 0005 的 DDL）。
#: `reason_code` / `corrected_sql` / `comment` / `correct_result_hint` 刻意不在内 ——
#: 它们的可空性是 §A.6 的 ⭕ 标记（0005 文件头登记了这条裁定）。
FEEDBACK_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"feedback_id", "task_id", "user_id", "is_correct"}
)


class FeedbackSchemaMismatch(ValueError):
    """写入面与表契约不符（缺必填列 / `reason_code` 不是 `FeedbackReasonCode`）。

    ⚠️ 是 `ValueError` 子类而**不是** `CommerceQLError`：这是**编程错误**
    （调用方与表定义不一致），不是运行时故障 —— 混进 `CommerceQLError` 会跟
    "库连不上"共用错误码，把排查方向带偏（同 `QueryPlanSchemaMismatch` 的裁定）。
    """


#: INSERT —— 本文件唯一拼 SQL 的地方。列名取自白名单常量（不是入参 dict 的键），
#: 因此不存在"把调用方的键拼进 SQL"的注入面。
_INSERT_SQL: Final[str] = (
    f"INSERT INTO {FEEDBACK_TABLE} ({', '.join(FEEDBACK_COLUMNS)}) "
    f"VALUES ({', '.join(f':{c}' for c in FEEDBACK_COLUMNS)})"
)

#: 幂等回读。⚠️ `IS NOT DISTINCT FROM` 而不是 `=` —— 见模块 docstring 的 NULL 比较陷阱。
#: 唯一约束保证"命中至多一条"，`LIMIT 1` 是形态上的自证（也让 planner 不必全扫）。
_FIND_SQL: Final[str] = (
    f"SELECT feedback_id FROM {FEEDBACK_TABLE} "
    f"WHERE task_id = :task_id AND user_id = :user_id "
    f"AND reason_code IS NOT DISTINCT FROM :reason_code "
    f"LIMIT 1"
)


class FeedbackStore:
    """`app.feedback` 的访问对象（**只写 + 只读**，无 UPDATE/DELETE）。

    ⚠️ 接收 **SQLAlchemy `AsyncEngine`（元数据池）**而不是连接：借用/归还
    必须**每语句一次**。传连接对象会让"谁负责归还"含糊，漏归还的表现是池被慢慢抽干
    （同 `AuditStore` / `QueryPlanStore` 的裁定）。
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def insert_feedback(
        self,
        *,
        feedback_id: str,
        task_id: str,
        user_id: str,
        is_correct: bool,
        reason_code: FeedbackReasonCode | None = None,
        corrected_sql: str | None = None,
        comment: str | None = None,
        correct_result_hint: str | None = None,
    ) -> None:
        """写一行反馈。**失败向上抛**（含唯一约束冲突）—— 本方法不 catch 任何异常。

        逐字覆盖迁移 `0005` 的列集：

        | 参数 | 列 | 约束 |
        |---|---|---|
        | `feedback_id` | `feedback_id` | PK；由**调用方**用 `new_id("feedback")` 生成 |
        | `task_id` / `user_id` | 同 | NOT NULL；`user_id` = **JWT 的 `sub`**（见下） |
        | `is_correct` | `is_correct` | NOT NULL；§A.6 必填 |
        | `reason_code` | `reason_code` | 可空；**枚举入参** → 写 `.value`；CHECK 是 0005 的冻结快照 |
        | `corrected_sql` | `corrected_sql` | 可空（§A.6 ⭕；进待审核池的那份 SQL） |
        | `comment` | `comment` | 可空 |
        | `correct_result_hint` | `correct_result_hint` | 可空。**§12.3 表行漏了该列、§A.6 请求字段有它** ⇒ 0005 补齐（否则端点收到就丢） |

        ⚠️ **`user_id` 的值 = JWT 的 `sub`，不是某个 `user_id` claim**：
        认证链的必需 claims 是 `sub`/`tenant_id`/`role`/`scope`/`exp`/`iat`/`jti`
        （`app/auth/tokens.py:59`），**没有** `user_id`。列名沿用 §12.3 的 `user_id`
        （改名会与契约文档不一致），映射发生在**调用方**：`user_id=identity.subject`。
        这条映射必须写死在调用点附近 —— 传成 `tenant_id` 会静默产生跨租户的"同一个人"。

        ⚠️ **`reason_code` 传枚举而不是裸字符串**：取值集在 `app/core/enums.py`，
        CHECK 是它的冻结快照（迁移 0005）。拼错在**调用点**就红，而不是等 CHECK 拒绝
        （那时错误信息只是一串约束名）。CHECK 仍是最后一道防线，两者不互替。

        ⚠️ **异常被 SQLAlchemy 包装过**：重复反馈（同 `task_id`+`user_id`+`reason_code`，
        含 `reason_code IS NULL` 的情形）得到 `sqlalchemy.exc.IntegrityError`，
        原始 psycopg 异常在 `.orig`（`psycopg.errors.UniqueViolation`）。
        幂等路径请**先**用 `find_feedback_id` 回读，而不是靠捕异常（见模块 docstring）。
        """
        if not isinstance(is_correct, bool):
            raise FeedbackSchemaMismatch(
                f"{FEEDBACK_TABLE}: is_correct 必须是 bool，收到 {type(is_correct).__name__}"
            )
        if reason_code is not None and not isinstance(reason_code, FeedbackReasonCode):
            raise FeedbackSchemaMismatch(
                f"{FEEDBACK_TABLE}: reason_code 必须是 FeedbackReasonCode 或 None，"
                f"收到 {type(reason_code).__name__} —— 取值集唯一来源是 app/core/enums.py"
            )

        values: dict[str, Any] = {
            "feedback_id": feedback_id,
            "task_id": task_id,
            "user_id": user_id,
            "is_correct": is_correct,
            # StrEnum ⇒ 取出字符串字面值（与 CHECK 的冻结快照同源）
            "reason_code": None if reason_code is None else str(reason_code.value),
            "corrected_sql": corrected_sql,
            "comment": comment,
            "correct_result_hint": correct_result_hint,
        }
        # 必填项在这里判（而不是靠 DB 报 NOT NULL）：错误信息能指出**缺的是哪个字段**
        missing = sorted(c for c in FEEDBACK_REQUIRED_COLUMNS if values.get(c) is None)
        if missing:
            raise FeedbackSchemaMismatch(f"{FEEDBACK_TABLE}: 缺少必填列 {missing}")

        async with self._engine.begin() as conn:
            await conn.execute(text(_INSERT_SQL), values)

    async def find_feedback_id(
        self,
        *,
        task_id: str,
        user_id: str,
        reason_code: FeedbackReasonCode | None = None,
    ) -> str | None:
        """幂等回读：返回已存在的 `feedback_id`（无则 `None`）。

        键 = §A.6 的幂等三元组 `(task_id, user_id, reason_code)`。
        ⚠️ `NULL` 的 `reason_code` 也参与比较（`IS NOT DISTINCT FROM`）——
        用 `=` 会让"不填归因的重复提交"永远查不到，形成
        "唯一约束拦住了、回读却找不到"的不一致形态（模块 docstring 的表）。
        """
        reason = None if reason_code is None else str(reason_code.value)
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(_FIND_SQL),
                {"task_id": task_id, "user_id": user_id, "reason_code": reason},
            )
            row = result.first()
        return None if row is None else str(row[0])
