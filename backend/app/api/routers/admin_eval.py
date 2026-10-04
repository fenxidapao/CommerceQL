"""`GET /api/v1/admin/eval/datasets` · `/runs` · `/runs/{run_id}`（附录 A §A.9.2–§A.9.4）。

层号：L5｜归属窗口：W8（T-34，2026-10-04）。

--------------------------------------------------------------------------
一、这个文件为什么"薄"，以及薄的边界在哪
--------------------------------------------------------------------------
形状翻译、4×3 网格、归因分布、门禁判定全部在 `app/present/eval_report.py`（L3）。
本文件只做四件事：**验签 → 角色门禁 → 限流 → 装信封**。

⚠️ 之所以必须在 L3 而不是这里：`docs/01_需求规格说明书_PRD.md:271` 与
`docs/02_附录A_接口契约详解.md:912-913` 把"网格由后端聚合、前端不得自算"写成**判据**，
而 `backend/.importlinter` 的层序里 `app.api` 是 L5、`app.present` 是 L3 ——
聚合写在 router 里会让下一位"顺手加个前端兜底计算"的人有借口说口径本来就在接入层。

--------------------------------------------------------------------------
二、三条硬约束（都不是形式主义的）
--------------------------------------------------------------------------
1. **角色门禁是 fail-closed**：`role != platform_admin` ⇒ 403 `FORBIDDEN_SCOPE`，
   且**只复用既有 JWT 验签链**（`deps.authenticate`）。
   这里没有新令牌通道、没有第二个 header、也没有"管理员可读他人会话"的豁免
   （`U-131` 判据⑥ 同源：本端点根本不碰会话面）。
2. **没有 `tenant_id`／`user_id` 查询参数**（`docs/02:600` 的禁令）。
   本端点的数据源是**已入库的评测产物**、不是业务表：冻结集天然跨 `T_A/T_B/T_C`，
   所以 §A.9.4 的 `scope: "cross_tenant"` 标注恒存在（由 L3 写进响应，不在这里二次判定），
   读的是"这次评测覆盖了哪些租户"，不是"某个租户的业务数据"。
3. **只读产物，端点内不重跑评测、不出站、不连库**（派单硬要求）。
   产物不在位 ⇒ 404 `RUN_NOT_FOUND`；不会因为"目录不存在"而 500，
   也**不会**因为想要一个好看的页面而造一行假数据。
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

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
from app.api.exceptions import DatasetNotFound, ForbiddenScope, RunNotFound
from app.api.ratelimit import RateLimitQuota
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.core.enums import RateLimitBucket, Role
from app.present import eval_report
from app.present.artifacts import ArtifactNotFound

__all__ = ["router"]

router = APIRouter(prefix="/admin/eval", tags=["admin"])

#: 管理端视图**不属于任何用户会话**，而 `build_identity` 要求 `session_id` 非空
#: （`app/auth/context.py:68-73`）。这里给的是命名占位，不是存储键：
#: 本文件不读写 `sess:meta:*`、不写审计，限流按 user/tenant 分桶 ⇒ 它只进 trace。
_ADMIN_SCOPE_SESSION: Final = "admin_eval"


def _require_platform_admin(token: VerifiedToken) -> None:
    if token.role is not Role.PLATFORM_ADMIN:
        raise ForbiddenScope("该视图仅平台管理员可见")


@router.get(
    "/datasets",
    summary="评测集列表（§A.9.2）",
    responses={401: {"description": "AUTH_FAILED"}, 403: {"description": "FORBIDDEN_SCOPE"}},
)
async def list_datasets(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
) -> JSONResponse:
    """评测集清单（§A.9.2）。

    ⚠️ 这一格的存在理由写在契约里：触发评测（A.9.1）必须传 `dataset_id`，
    而原契约没给可选值来源 ⇒ 前端无法构造那个请求。本端点只列**已冻结**的集，
    `status` 恒为 `frozen`（`draft` 需要能改评测集，而评测集一经冻结不得再动，
    见 `eval/dataset_v1_frozen.json` 的 `frozen_rule`）。
    """
    ctx = new_identity(token, session_id=_ADMIN_SCOPE_SESSION)
    remember_identity(request, ctx)
    async with trace_scope(ctx):
        _require_platform_admin(token)
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        return _ok(eval_report.datasets(), ctx, quota)


@router.get(
    "/runs",
    summary="评测运行列表（§A.9.3）",
    responses={
        403: {"description": "FORBIDDEN_SCOPE"},
        404: {"description": "DATASET_NOT_FOUND"},
        429: {"description": "配额超限（读取类桶）"},
    },
)
async def list_runs(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    dataset_id: Annotated[str | None, Query(description="按评测集过滤")] = None,
    status: Annotated[
        Literal["queued", "running", "complete", "failed"] | None, Query(description="按状态过滤")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """批次清单（§A.9.3）。

    🔴 `gate_passed` 与 `headline` 里的数**只在有对应门禁报告的批次上才有值**，
    其余批次如实给 `null`（L3 的 `_linked_gate`）。列表页因此会出现「未算门禁」——
    那是设计，不是缺陷：把"没算"显示成"没过"就是撒谎。
    """
    ctx = new_identity(token, session_id=_ADMIN_SCOPE_SESSION)
    remember_identity(request, ctx)
    async with trace_scope(ctx):
        _require_platform_admin(token)
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        if dataset_id is not None and dataset_id not in eval_report.dataset_ids():
            raise DatasetNotFound("评测集不存在", detail={"dataset_id": dataset_id})
        data = eval_report.runs(dataset_id=dataset_id, status=status, limit=limit, offset=offset)
        return _ok(data, ctx, quota)


@router.get(
    "/runs/{run_id}",
    summary="单次评测结果（§A.9.4，网格与归因由后端聚合）",
    responses={
        403: {"description": "FORBIDDEN_SCOPE"},
        404: {"description": "RUN_NOT_FOUND"},
        429: {"description": "配额超限（读取类桶）"},
    },
)
async def get_run(
    request: Request,
    run_id: str,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    include_cases: Annotated[bool, Query(description="是否附带逐条用例明细")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    case_filter: Annotated[Literal["failed", "all"] | None, Query(description="用例过滤")] = None,
) -> JSONResponse:
    """单批次结果（§A.9.4）。

    ⚠️ 三件事在同一次响应里必须同时成立，缺一件就退回本窗：
    ① `grid`／`attribution`／`gate` 是**服务端算好的**（前端一行聚合都不写）；
    ② 产物算不出的口径是 `null` 且**在 `unavailable` 里有对应解释**（不许 0 顶替未测）；
    ③ `include_cases=true` 时**不下发** `gold_sql` 与完整预测 SQL（`docs/02:1012`）。
    """
    ctx = new_identity(token, session_id=_ADMIN_SCOPE_SESSION)
    remember_identity(request, ctx)
    async with trace_scope(ctx):
        _require_platform_admin(token)
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        try:
            data = eval_report.run_detail(
                run_id=run_id,
                include_cases=include_cases,
                limit=limit,
                offset=offset,
                case_filter=case_filter,
            )
        except ArtifactNotFound as exc:
            raise RunNotFound("评测批次不存在", detail={"run_id": run_id}) from exc
        return _ok(data, ctx, quota)


def _ok(data: Any, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    """成功封套 + 逐桶限流四头（与 `routers/session.py::_ok` 同形）。"""
    envelope = OkEnvelope(trace_id=ctx.trace_id, data=data, server_time=errors.server_time())
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )
