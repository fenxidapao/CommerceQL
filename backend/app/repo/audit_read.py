"""审计**读**路径 —— 只有 SELECT（§A.9.5 判据① 的落地形态）。

层号：L0｜归属窗口：W8（T-37，2026-10-05）｜上游：`docs/02 §A.9.5 判据块`（2026-10-05 第 12 轮落笔）

--------------------------------------------------------------------------
一、为什么新开一个文件，而不是给 `audit_store.py` 加一个 `select`
--------------------------------------------------------------------------
`app/repo/audit_store.py` 的**只写**不是风格，是 0001 那条 append-only 保证在代码面上的形状
（`tests/unit/test_audit_writer.py` 静态断言它"只暴露 `insert_*`"）。
把读口加进同一个类，"能写就能读"这条边界就没了 ⇒ 判据① 明写**新增本文件**，
且本文件**不 import `audit_store` 的类**，只复用它的两个表名常量（表名漂了就是查错对象）。

--------------------------------------------------------------------------
二、身份注入 = 沿用生产形态，一条语句三键同生同灭（判据②）
--------------------------------------------------------------------------
- 键名来自 `app/repo/dsn.py::IDENTITY_GUC_KEYS`（**唯一来源**，本文件不另列一份）；
- 三键在**同一条** `SELECT set_config(…), set_config(…), set_config(…)` 里注入，
  `is_local = true` ⇒ 随事务结束一起消失，不会顺着池化连接漂到下一个请求；
- 🚫 不写单键注入，也**不写 `RESET`** —— `U-110` 的"并行少算"就是非对称态：
  一半语句带身份、一半不带，比全都不带更难查。
- ⚠️ 为什么不复用 `dsn.IDENTITY_INJECTION_TEMPLATE` 那条 `$n` 文本：`$n` 是 pg 服务端绑定形态，
  转成 psycopg/SQLAlchemy 可绑定的占位符需要一个转换器，而那个转换器在 `app/exec/executor.py`（L2）。
  L0 向上 import L2 直接违反 `.importlinter` 的 R-DEP-1 —— 故这里用**命名绑定**从同一份键名常量
  生成语句（语义逐字相同：同一条语句、同三个键、同样 `is_local=true`）。
  形状由 `tests/contract/test_admin_audit_contract.py` 钉，不是由注释保证。

--------------------------------------------------------------------------
三、两道租户保证里，本文件只能给出一道半（判据③，如实登记）
--------------------------------------------------------------------------
| 保证 | 状态 |
|---|---|
| 服务端 `WHERE tenant_id = JWT.tenant_id` | ✅ 本文件实现（`tenant_scope` 参数为 `None` 时**只有** `platform_admin` 能走到，且响应必须带 `scope: cross_tenant`，见 `app/api/routers/admin_audit.py`） |
| 身份 GUC 注入（RLS 策略一旦在位即生效） | ✅ 本文件实现 |
| `app.audit_log` 上的 RLS 策略本身 | 🔴 **不在位，且本窗不擅自落 DDL** |

第三行为什么空着：`tests/unit/test_rls_policy_provenance.py` ① 禁止**任何**迁移产出
`CREATE POLICY` / `ENABLE|FORCE ROW LEVEL SECURITY`（ADR-10：策略只能由语义包派生），
而审计表**不是语义资产** ⇒ 派生器不会为它出策略。补策略还有 `app/obs/audit.py` 记过的两个陷阱
（只写 `FOR SELECT` ⇒ 默认拒绝会掐死 fail-closed 的 INSERT；而本表属主实测是**迁移执行角色**
（2026-10-05 现查共享库 = `postgres`，非 `app_rw`）⇒ `ENABLE` 不加 `FORCE` 就已经约束 `app_ro` 与 `app_rw`，
陷阱 ① 因此**必踩**而不是"可能踩"。两条形态都由 `tests/integration/test_audit_read_rls.py` 连库证过。）
⇒ 该 DDL 通道作为**需裁定项**上呈（推荐默认与代价见 `reports/w8/RELAY.md`）。
集成测试因此在**一次性库**里自造策略，用来证明"注入在位时跨租户不可读"这件事**不依赖** `WHERE`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.elements import TextClause

from app.core.contracts import IdentityContext
from app.core.enums import DependencyKind, Outcome
from app.core.errors import ContractViolationError, DependencyUnavailableError
from app.repo.audit_store import AUDIT_TABLE, SUPPLEMENT_TABLE
from app.repo.dsn import IDENTITY_GUC_KEYS

__all__ = ["AUDIT_LIST_COLUMNS", "AuditFilters", "AuditPage", "AuditReadDAO", "build_queries"]

#: 列表页要用的列，**逐列点名**（`SELECT *` 会让"表加了列"变成静默的形状变化）。
#: 不含 `final_executed_sql` 与 `raw_question` 全文 —— 前者是可执行模板、后者是用户原文，
#: 两者都只配详情视图（P1），列表页按 UIUX §11.4 只给截断预览。
AUDIT_LIST_COLUMNS: Final[tuple[str, ...]] = (
    "log_id",
    "task_id",
    "tenant_id",
    "user_id",
    "role",
    '"timestamp"',
    "raw_question",
    "row_count_returned",
    "pii_columns_hit",
    "truncated",
    "scope_level",
    "outcome",
    "refusal_reason",
    "latency_ms",
    "bundle_version",
    "prompt_version",
    "model_version",
    "tables_accessed",
    "columns_accessed",
)

#: 每列的**输出别名**（带引号的 `"timestamp"` 去掉引号，否则前端拿到一个带引号的键名）。
_COLUMN_KEYS: Final[tuple[str, ...]] = tuple(c.strip('"') for c in AUDIT_LIST_COLUMNS)

#: GUC 键 → 绑定参数名（`app.tenant_id` → `app_tenant_id`）。
_GUC_BIND: Final[dict[str, str]] = {key: key.replace(".", "_") for key in IDENTITY_GUC_KEYS}

_INJECT_SQL: Final[TextClause] = text(
    "SELECT "
    + ", ".join(f"set_config('{key}', :{_GUC_BIND[key]}, true)" for key in IDENTITY_GUC_KEYS)
)

_FROM_SQL: Final[str] = (
    f"FROM {AUDIT_TABLE} a LEFT JOIN {SUPPLEMENT_TABLE} s ON s.task_id = a.task_id"
)

#: `pii_hit` 的**派生谓词**：表里没有 `pii_hit` 这一列，只有 `pii_columns_hit text[]`（0001:139）。
_PII_TRUE: Final[str] = "a.pii_columns_hit <> '{}'::text[]"
_PII_FALSE: Final[str] = "a.pii_columns_hit = '{}'::text[]"

#: 排序**必须含 tiebreaker**：同一毫秒内的多条审计若只按 `"timestamp"` 排，
#: 分页会在页边界上重复/漏行（同 `present/artifacts.py` 的稳定排序理由）。
_ORDER_BY: Final[str] = 'ORDER BY a."timestamp" DESC, a.log_id DESC'

#: 第二道保证（RLS）**现在到底在不在位**——这是一个可现查的事实，不是文档里的承诺。
#: ⚠️ 不许在响应里凭代码注释写"RLS 已生效"：`app/obs/audit.py` 记的正是"实测 `relrowsecurity=f`、0 条策略"，
#: 而"没策略"与"策略在位"对读的人是完全不同的两件事（前者只有 WHERE 一道，后者才是双保证）。
_RLS_STATE_SQL: Final[TextClause] = text(
    """
    SELECT c.relrowsecurity                                  AS rls_enabled,
           c.relforcerowsecurity                             AS rls_forced,
           (SELECT count(*)
              FROM pg_policies p
             WHERE p.schemaname = 'app' AND p.tablename = 'audit_log') AS policies
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'app' AND c.relname = 'audit_log'
    """
)


@dataclass(frozen=True, slots=True)
class AuditFilters:
    """§A.9.5 的四个过滤条件。🔴 **没有** `tenant_id`／`user_id` —— 身份只从 JWT 取（判据③）。"""

    since: datetime | None = None
    until: datetime | None = None
    outcome: Outcome | None = None
    pii_hit: bool | None = None


@dataclass(frozen=True, slots=True)
class AuditPage:
    rows: list[dict[str, Any]]
    total: int
    #: 本表 RLS 的**现查**状态（同一次事务里读到的，不是代码注释里的承诺）。
    rls: dict[str, Any]


def _identity_params(ctx: IdentityContext) -> dict[str, str]:
    """三键的值全部来自服务端 `IdentityContext`（不接受任何请求方输入）。"""
    values: dict[str, str] = {
        "app.tenant_id": ctx.tenant_id,
        "app.role": ctx.role.value,
        "app.shop_ids": ",".join(ctx.shop_ids),
    }
    missing = sorted(set(IDENTITY_GUC_KEYS) - set(values))
    if missing:
        raise ContractViolationError(
            f"身份注入缺键：{missing}（契约破损，不是运行时故障）",
            detail={"missing": missing, "keys": list(IDENTITY_GUC_KEYS)},
        )
    return {_GUC_BIND[key]: values[key] for key in IDENTITY_GUC_KEYS}


def _where(filters: AuditFilters, tenant_scope: str | None) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if tenant_scope is not None:
        clauses.append("a.tenant_id = :scope_tenant")
        params["scope_tenant"] = tenant_scope
    if filters.since is not None:
        clauses.append('a."timestamp" >= :since')
        params["since"] = filters.since
    if filters.until is not None:
        clauses.append('a."timestamp" <= :until')
        params["until"] = filters.until
    if filters.outcome is not None:
        clauses.append("a.outcome = :outcome")
        params["outcome"] = filters.outcome.value
    if filters.pii_hit is not None:
        clauses.append(_PII_TRUE if filters.pii_hit else _PII_FALSE)
    return clauses, params


def build_queries(
    filters: AuditFilters, tenant_scope: str | None, *, limit: int, offset: int
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """纯函数：把过滤条件拼成 `(select_sql, count_sql, where_params, page_params)`。

    ⚠️ 为什么不留在方法体里：那半截 SQL 文本是**判据③ 的第一道保证**所在
    （租户谓词、tiebreaker、`count` 不受 `LIMIT` 影响）。留在 `async` 方法里就只能连库测；
    提成纯函数后离线契约件能直接钉它的形状，而"红了才知道要连库"这条路就留给了真行为。
    """
    clauses, params = _where(filters, tenant_scope)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    select_sql = (
        "SELECT "
        + ", ".join(f"a.{col} AS {key}" for col, key in zip(AUDIT_LIST_COLUMNS, _COLUMN_KEYS, strict=True))
        + ", s.cost_cny AS cost_cny "
        + _FROM_SQL
        + f" {where_sql} {_ORDER_BY} LIMIT :limit OFFSET :offset"
    )
    count_sql = f"SELECT count(*) AS total {_FROM_SQL} {where_sql}"
    return select_sql, count_sql, params, {**params, "limit": limit, "offset": offset}


class AuditReadDAO:
    """`app_ro` 上的审计分页读。

    ⚠️ 收 **engine**（分析只读池）而不是连接：借用/归还每语句一次，
    与 `audit_store`／`query_plan` 同一裁定（07 §8.1 纪律 1）。
    ⚠️ 本类**没有任何写方法**，也没有事务内的 DML —— 由契约测试静态断言（"只 SELECT"）。
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def fetch_page(
        self,
        ctx: IdentityContext,
        *,
        filters: AuditFilters,
        tenant_scope: str | None,
        limit: int,
        offset: int,
    ) -> AuditPage:
        """一次事务里取 `total` ＋ `items` ＋ `rls`（同一条读路径，页边界不会自相矛盾）。

        `tenant_scope = None` = **跨租户**视角 ⇒ 由调用方（L5）负责它只对
        `platform_admin` 开放，并在响应里显式标 `scope: cross_tenant`。
        """
        select_sql, count_sql, where_params, page_params = build_queries(
            filters, tenant_scope, limit=limit, offset=offset
        )
        try:
            async with self._engine.begin() as conn:
                await conn.execute(_INJECT_SQL, _identity_params(ctx))
                total_row = (await conn.execute(text(count_sql), where_params)).mappings().one()
                result = await conn.execute(text(select_sql), page_params)
                rows = [dict(row) for row in result.mappings().all()]
                rls_row = (await conn.execute(_RLS_STATE_SQL)).mappings().first()
        except DependencyUnavailableError:
            raise
        except SQLAlchemyError as exc:
            # 原始报错不回灌（N-11）：DB 文本里可能有 schema 名与参数值。
            raise DependencyUnavailableError(
                "审计读路径不可用",
                dependency="analytics_db",
                kind=DependencyKind.HARD.value,
                detail={"error_kind": type(exc).__name__},
            ) from exc
        if rls_row is None:
            raise ContractViolationError(
                "读不到 app.audit_log 的 relrowsecurity 状态（表不在位？）",
                detail={"table": AUDIT_TABLE},
            )
        return AuditPage(rows=rows, total=int(total_row["total"]), rls=dict(rls_row))
