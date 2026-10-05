"""`GET /api/v1/semantic/metrics` · `/api/v1/semantic/assets`（附录 A §A.7.1／§A.7.2）。

层号：L5｜归属窗口：W8（T-37，2026-10-05）

--------------------------------------------------------------------------
一、这个文件只做四件事
--------------------------------------------------------------------------
**验签 → 限流 → 取运行时 → 装信封**。投影（字段翻译、`deny` 分组、分页壳）全在
`app/present/semantic_dict.py`（L3），理由与 `admin_eval.py` 文件头那条相同：
口径与形状不许在接入层重算一遍（那会造出第二份真相）。

--------------------------------------------------------------------------
二、这里**没有**角色门禁（是裁定，不是漏了）
--------------------------------------------------------------------------
`docs/02:700-706`（10-05 裁定）：口径字典 = **平台级共享面**，`app/semantics/` 里没有按
身份分叉的读法 ⇒ 七个角色都能读同一份定义。因此：
- 本文件**不**调 `_require_platform_admin`（那会把共享面误标成管理员面）；
- 响应里**没有** `scope` 键 —— `cross_tenant` 属于"读了别人的私有数据"那一类面（§A.9.4／§A.9.5），
  挂在共享字典上等于把"同一份定义"说成"跨租户读取"；
- **没有** `tenant_id`／`user_id` 参数（§A.0.2 禁令）。FastAPI 对未声明的查询参数是忽略，
  所以契约测试断的是**"传了也不改变任何东西"**（与 `test_admin_eval_report_contract.py` 同一口径）。

限流档 = **读取类 120 次/分钟**（`docs/02:117` 把 `GET /semantic/*` 明确列在读取桶，
不是查询桶）—— 这正是 §A.0.6 那条修订要防的：渲染一个字典页不该吃掉问答额度。

--------------------------------------------------------------------------
三、语义包没装载时**不给 `INTERNAL`**
--------------------------------------------------------------------------
`main.py` 第 4 步是**软降级**（装载失败 ⇒ `app.state` 上没有运行时、`healthz` 给
`semantic_bundle_loaded=false`，但进程照常起）。此时本端点如实抛
`NoDataAsset`（422 `NO_DATA_ASSET`，`detail.reason = "semantic_bundle_not_loaded"`），
**不**压成 500 —— 压成 500 就是 `U-131`／`U-136` 那一族病灶（设计性失败被报成内部错误）。
文案也与问答链路那句"拒答"分开写，避免两个触发面共用一句话（`U-137` 刚为 R10 文案立过同样的规矩）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api import errors
from app.api.deps import (
    authenticate,
    check_rate_limit,
    new_identity,
    remember_identity,
    trace_scope,
)
from app.api.dto.common import OkEnvelope
from app.api.exceptions import NoDataAsset
from app.api.ratelimit import RateLimitQuota
from app.api.routers.health import SEMANTIC_RUNTIME_STATE_KEY
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.core.enums import RateLimitBucket
from app.present import semantic_dict
from app.semantics.runtime import SemanticBundleRuntime

__all__ = ["router"]

router = APIRouter(prefix="/semantic", tags=["semantic"])

#: 口径字典页**不属于任何用户会话**（同 `admin_eval.py:63` 的理由：`build_identity`
#: 要求 `session_id` 非空，而这两个 GET 不读写 `sess:meta:*`、不写审计）。
_SEMANTIC_SCOPE_SESSION = "semantic_dict"


def _runtime(request: Request) -> SemanticBundleRuntime:
    """取装配期那份运行时（`main.py:281` 存的同一个实例），不在位就具名失败。

    ⚠️ 这里用 `isinstance` 而不是"取到就用"：`main.py` 存的是 `SemanticBundleRuntime | None`
    （软降级 = 装载失败时**显式存 None**，进程照起）。`None` 走具名 422，
    而"有值但不是运行时"只可能是装配写错了 ⇒ 那种情况**不该**被静默当成"字典为空"。
    """
    mounted = getattr(request.app.state, SEMANTIC_RUNTIME_STATE_KEY, None)
    if not isinstance(mounted, SemanticBundleRuntime):
        raise NoDataAsset(
            "口径字典当前不可用：语义包未装载（可核对 /healthz 的 semantic_bundle_loaded）",
            detail={"reason": "semantic_bundle_not_loaded"},
        )
    return mounted


@router.get(
    "/metrics",
    summary="指标口径字典（§A.7.1）",
    responses={401: {"description": "AUTH_FAILED"}, 422: {"description": "NO_DATA_ASSET"}},
)
async def list_metrics(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    domain: Annotated[str | None, Query(description="按数据域精确过滤")] = None,
    q: Annotated[str | None, Query(description="模糊搜索（name / display_name / 同义词）")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """指标定义清单（§A.7.1）。

    ⚠️ 引用本读数时要知道的两件事：① `total` = **过滤后**条数，不是包内指标总数；
    ② `status="draft"` 的条目**刻意保留**（`runtime.py:349-359`），其 `expression`／`unit`
    等为 `null` = **口径未定**，不是"公式是空的"。
    """
    ctx = new_identity(token, session_id=_SEMANTIC_SCOPE_SESSION)
    remember_identity(request, ctx)
    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        data = semantic_dict.metrics(_runtime(request), domain=domain, q=q, limit=limit, offset=offset)
        return _ok(data, ctx, quota)


@router.get(
    "/assets",
    summary="认证资产清单（§A.7.2）",
    responses={401: {"description": "AUTH_FAILED"}, 422: {"description": "NO_DATA_ASSET"}},
)
async def list_assets(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    domain: Annotated[str | None, Query(description="按数据域精确过滤")] = None,
    q: Annotated[str | None, Query(description="模糊搜索（logical / physical / description）")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """认证资产清单（§A.7.2）。

    ⚠️ 只列**通过质量准入**的资产（`runtime.assets()` 在 loader 期就过滤了排除项），
    且 `column_count`／`denied_columns` 是**派生量**（包内没有这两个字段），来源见
    `app/present/semantic_dict.py` 文件头第二节。
    """
    ctx = new_identity(token, session_id=_SEMANTIC_SCOPE_SESSION)
    remember_identity(request, ctx)
    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        data = semantic_dict.assets(_runtime(request), domain=domain, q=q, limit=limit, offset=offset)
        return _ok(data, ctx, quota)


def _ok(data: object, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    """成功封套 ＋ 逐桶限流四头（与 `routers/admin_eval.py::_ok` 同形）。"""
    envelope = OkEnvelope(trace_id=ctx.trace_id, data=data, server_time=errors.server_time())
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )
