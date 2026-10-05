"""`GET /api/v1/admin/audit`（附录 A §A.9.5）—— 审计日志的服务端强制租户读。

层号：L5｜归属窗口：W8（T-37，2026-10-05）

--------------------------------------------------------------------------
四条硬约束（逐条对应 §A.9.5 判据块，缺一格就是没实现）
--------------------------------------------------------------------------
1. **角色 fail-closed**：`role != platform_admin` ⇒ 403 `FORBIDDEN_SCOPE`（不是 401、不是 500）。
   §A.9.4 的强制约束覆盖所有 `/admin/*`：`role == "platform_admin"`。
2. **身份只从 JWT 取**：本端点**没有** `tenant_id`／`user_id` 查询参数
   （`docs/02:65` ＋ §A.9.5 判据③）。传了也不改变任何一行 —— 这条由契约测试钉，
   而**不是**断言"传了会 422"（FastAPI 对未声明的查询参数是忽略，那才是可测的面）。
3. **连接角色 = `app_ro`**（判据①）：DAO 收 `runtime.pools.analytics`，
   **不是** `pools.metadata`。写反了不会有任何报错，只是读路径变成可写连接上的 SELECT
   —— 而"只读"正是 §A.9.5 唯一能拦"审计被改过"的那道权限面。
4. **限流 = 管理员类 5 次/分钟**（`docs/02:119`），与 `GET /admin/eval/*` 的读取类 120 次**不同桶**。

--------------------------------------------------------------------------
`scope` 参数不是身份，是**视角开关**
--------------------------------------------------------------------------
判据③ 要求 `WHERE tenant_id = JWT.tenant_id`，而 §A.9.5 的强制约束又要求平台管理员的跨租户视角
**显式带** `scope: "cross_tenant"`。两者的交集只有一种写法：

| 请求 | `tenant_scope` 传给 DAO | 响应 `scope.level` |
|---|---|---|
| 默认（不传 `scope`） | **JWT 的 `tenant_id`**（服务端拼，参数不可覆盖） | `tenant` |
| `?scope=cross_tenant` | `None`（不加租户谓词） | `cross_tenant` |

⇒ 默认那一行让③的 WHERE 子句**真的在链路上**（而不是"代码里有但没人走"）；
跨租户那一行让标签**必须出现**。两个分支都由集成测试连库验，且响应里的 `rls` 块
现查 `pg_policies` —— 第二道保证在不在位，读的人可以自己看见。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api import errors
from app.api.deps import (
    authenticate,
    check_rate_limit,
    get_runtime,
    new_identity,
    remember_identity,
    trace_scope,
)
from app.api.dto.common import OkEnvelope
from app.api.exceptions import ForbiddenScope
from app.api.ratelimit import RateLimitQuota
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.core.enums import Outcome, RateLimitBucket, Role
from app.present import audit_view
from app.repo.audit_read import AuditFilters

__all__ = ["router"]

router = APIRouter(prefix="/admin", tags=["admin"])

#: 与 `admin_eval` 同一做法：管理端视图不属于任何用户会话，而 `build_identity` 要求
#: `session_id` 非空 ⇒ 命名占位，只进 trace，不读写 `sess:meta:*`。
_AUDIT_SCOPE_SESSION: Final = "admin_audit"

#: UIUX §11.4 的分页规格（默认 50、上限 500）。
_DEFAULT_LIMIT: Final = 50
_MAX_LIMIT: Final = 500


@router.get(
    "/audit",
    summary="审计日志（§A.9.5，服务端按 JWT 租户强制过滤）",
    responses={
        401: {"description": "AUTH_FAILED"},
        403: {"description": "FORBIDDEN_SCOPE"},
        429: {"description": "配额超限（管理员类桶 5/min）"},
    },
)
async def list_audit(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    scope: Annotated[Literal["tenant", "cross_tenant"], Query(description="视角：默认仅本租户")] = "tenant",
    from_time: Annotated[datetime | None, Query(alias="from", description="起始时间（含）")] = None,
    to_time: Annotated[datetime | None, Query(alias="to", description="结束时间（含）")] = None,
    outcome: Annotated[Outcome | None, Query(description="5 值：success/clarify/refuse/degraded/failed")] = None,
    pii_hit: Annotated[bool | None, Query(description="PII 命中（派生自 pii_columns_hit 非空）")] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """审计读（§A.9.5）。

    ⚠️ 响应里的 `rls.policies` 是**现查** `pg_policies` 的结果。今天 `app.audit_log` 上
    0 条策略（DDL 通道待裁定，见 `reports/w8/RELAY.md`），所以
    `rls.second_guarantee_in_place = false`、`scope.enforced_by` 只有两条 ——
    页面据此显示"当前只有一道服务端过滤"，而不是把"已启 RLS"当成既成事实。
    """
    ctx = new_identity(token, session_id=_AUDIT_SCOPE_SESSION)
    remember_identity(request, ctx)
    async with trace_scope(ctx):
        if token.role is not Role.PLATFORM_ADMIN:
            raise ForbiddenScope("该视图仅平台管理员可见")
        quota = await check_rate_limit(request, RateLimitBucket.ADMIN, ctx)
        runtime = get_runtime(request)
        cross_tenant = scope == "cross_tenant"
        filters = AuditFilters(since=from_time, until=to_time, outcome=outcome, pii_hit=pii_hit)
        page = await runtime.audit_read.fetch_page(
            ctx,
            filters=filters,
            tenant_scope=None if cross_tenant else ctx.tenant_id,
            limit=limit,
            offset=offset,
        )
        data = audit_view.build_page(
            rows=page.rows,
            total=page.total,
            rls=page.rls,
            limit=limit,
            offset=offset,
            cross_tenant=cross_tenant,
            tenant_id=ctx.tenant_id,
            filters={
                "from": from_time.isoformat() if from_time else None,
                "to": to_time.isoformat() if to_time else None,
                "outcome": outcome.value if outcome else None,
                "pii_hit": pii_hit,
                "scope": scope,
            },
        )
        return _ok(data, ctx, quota)


def _ok(data: Any, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    """成功封套 + 逐桶限流四头（与 `routers/admin_eval.py::_ok` 同形）。"""
    envelope = OkEnvelope(trace_id=ctx.trace_id, data=data, server_time=errors.server_time())
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )


#: 本端点的失败面全是既有码：`AUTH_FAILED`(401) / `FORBIDDEN_SCOPE`(403) /
#: `RATE_LIMITED`(429) / `INVALID_REQUEST`(400) / `DB_UNAVAILABLE`(503)。
#: ⚠️ 若将来要为"审计表不在位"之类新增错误码，那是改判据（`docs/02:1119`：本表是错误码唯一来源），
#: 必须先上呈而不是就地发明。
