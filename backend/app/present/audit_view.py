"""审计读路径的响应投影（§A.9.5）—— L3，纯函数、零依赖。

层号：L3｜归属窗口：W8（T-37，2026-10-05）

--------------------------------------------------------------------------
为什么形状翻译在 L3 而不是 router
--------------------------------------------------------------------------
同 `present/eval_report.py` 的裁定（`docs/01:271` ＋ `docs/02:912-913`）：
"聚合与翻译由后端做、前端不得自算"是**判据**，而判据的落点必须可测。
写在 router 里，下一个"顺手加个前端兜底"的人就有借口说口径本来就在接入层。

--------------------------------------------------------------------------
本模块做的三件"不冒充"
--------------------------------------------------------------------------
1. **成本不许补零**：`cost_cny` 来自 `audit_log_supplement`（段 2，**非阻断**写入，
   07 §12.4）⇒ LEFT JOIN 拿不到就是 `null`。渲染成 `0` 会把"段 2 没落"说成"这次没花钱"，
   而 `U-130` 那一条量（terminal 事件数 − 审计行数）正是靠这种区别才有意义。
2. **`pii_hit` 是派生量**：表里没有 `pii_hit` 列，只有 `pii_columns_hit text[]`（0001:139）
   ⇒ 谓词是"数组非空"，并且响应里同时给出原数组，让人能复核。
3. **RLS 状态是现查的**：`rls.enabled`／`rls.policies` 来自同一次事务里对 `pg_class`／
   `pg_policies` 的读数，**不是**本文件注释里的承诺 —— 因为 `app/obs/audit.py` 记着
   "实测 `relrowsecurity=f`、0 条策略"，而"双保证"与"只有 WHERE 一道"是两件事。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from app.repo.dsn import IDENTITY_GUC_KEYS

__all__ = ["QUESTION_PREVIEW_MAX", "build_page"]

#: 列表页只给截断预览（UIUX §11.4「问题（截断，全文在详情）」）；全文属于 P1 详情视图。
QUESTION_PREVIEW_MAX: Final[int] = 120

_AUDIT_TABLE: Final[str] = "app.audit_log"


def _preview(text_value: Any) -> str:
    raw = "" if text_value is None else str(text_value)
    return raw if len(raw) <= QUESTION_PREVIEW_MAX else f"{raw[:QUESTION_PREVIEW_MAX]}…"


def _number(value: Any) -> float | None:
    """`numeric(12,4)` → JSON 可序列化的数（`Decimal` 直接进 `json.dumps` 会 500）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def _item(row: dict[str, Any]) -> dict[str, Any]:
    pii_columns = list(row.get("pii_columns_hit") or [])
    raw_latency = row.get("latency_ms")
    latency: dict[str, Any] = raw_latency if isinstance(raw_latency, dict) else {}
    total_ms = latency.get("total")
    return {
        "log_id": row.get("log_id"),
        "task_id": row.get("task_id"),
        "tenant_id": row.get("tenant_id"),
        "user_id": row.get("user_id"),
        "role": row.get("role"),
        "timestamp": _iso(row.get("timestamp")),
        "question_preview": _preview(row.get("raw_question")),
        "row_count_returned": row.get("row_count_returned"),
        "pii_hit": bool(pii_columns),
        "pii_columns_hit": pii_columns,
        "truncated": row.get("truncated"),
        "scope_level": row.get("scope_level"),
        "outcome": row.get("outcome"),
        "refusal_reason": row.get("refusal_reason"),
        "latency_ms": latency,
        "latency_total_ms": total_ms if isinstance(total_ms, int | float) else None,
        "cost_cny": _number(row.get("cost_cny")),
        "bundle_version": row.get("bundle_version"),
        "prompt_version": row.get("prompt_version"),
        "model_version": row.get("model_version"),
        "tables_accessed": list(row.get("tables_accessed") or []),
        "columns_accessed": list(row.get("columns_accessed") or []),
    }


def build_page(
    *,
    rows: list[dict[str, Any]],
    total: int,
    rls: dict[str, Any],
    limit: int,
    offset: int,
    cross_tenant: bool,
    tenant_id: str,
    filters: dict[str, Any],
) -> dict[str, Any]:
    """§A.9.5 的 `data`（形状与判据逐条对得上，缺一格就是没实现）。"""
    enabled = bool(rls.get("rls_enabled"))
    policies = int(rls.get("policies") or 0)
    enforced_by: list[str] = ["server_where_on_jwt_tenant", "identity_guc_injection"]
    if enabled and policies > 0:
        enforced_by.append("rls_policy")
    return {
        "scope": {
            "level": "cross_tenant" if cross_tenant else "tenant",
            "tenant_id": None if cross_tenant else tenant_id,
            "source": "jwt",
            "enforced_by": enforced_by,
        },
        "identity_guc": {
            "keys": list(IDENTITY_GUC_KEYS),
            "statement_count": 1,
            "is_local": True,
            "reset_issued": False,
        },
        "rls": {
            "table": _AUDIT_TABLE,
            "enabled": enabled,
            "forced": bool(rls.get("rls_forced")),
            "policies": policies,
            "second_guarantee_in_place": enabled and policies > 0,
        },
        "items": [_item(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "filters": filters,
        "notes": [
            "身份只从 JWT 取：`tenant_id`／`user_id` 不是查询参数，传了也不改变任何一行。",
            "`user_id` 原表（§A.9.5 参数表）列过一格，判据③（2026-10-05）明写不得做成查询参数"
            " ⇒ 以实现为准，见 §A.9.5 补记。",
            "`pii_hit` = `pii_columns_hit` 数组非空的派生量（表里没有 `pii_hit` 列）。",
            "`cost_cny` 来自段 2（非阻断）⇒ `null` 是『这一条没有段 2 记录』，不是零成本。",
        ],
    }
