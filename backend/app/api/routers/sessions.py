"""`GET /api/v1/sessions`（附录 A §A.5.4）—— 会话列表。

层号：L5｜归属窗口：Phase B B4。

⚠️ `tenant_id` / `user_id` **不是查询参数**：服务端从 JWT 取，索引键已含两者。
⚠️ 只返回元数据，不返回轮次明细；`title` 由服务端在首轮写定。
⚠️ 索引存在**不等于**有权读：每条仍走 `state_store.get_session` 的属主门。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import (
    authenticate,
    check_rate_limit,
    get_state_store,
    new_identity,
    remember_identity,
    trace_scope,
)
from app.api.dto.common import OkEnvelope
from app.api.dto.sessions import SessionListData, SessionSummary
from app.api.ratelimit import RateLimitQuota
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.core.enums import RateLimitBucket
from app.obs.trace import new_id

__all__ = ["router"]

router = APIRouter(prefix="/sessions", tags=["session"])


@router.get(
    "",
    summary="会话列表（只回元数据）",
    responses={429: {"description": "配额超限（读取类桶）"}},
)
async def list_sessions(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    store: Annotated[RedisStateStore, Depends(get_state_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: Annotated[Literal["last_turn_at", "created_at"], Query()] = "last_turn_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> JSONResponse:
    ctx = new_identity(token, session_id=new_id("session"))
    remember_identity(request, ctx)

    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        metas = list(await store.list_sessions(ctx))
        if q:
            needle = q.lower()
            metas = [m for m in metas if m.title and needle in m.title.lower()]
        if sort == "created_at":
            metas.sort(key=lambda m: m.created_at, reverse=(order == "desc"))
        elif order == "asc":
            metas.reverse()  # 索引本身是 last_turn_at 倒序
        total = len(metas)
        window = metas[offset : offset + limit]
        items = []
        for meta in window:
            items.append(
                SessionSummary(
                    session_id=meta.session_id,
                    title=meta.title or "",
                    turn_count=len(await store.get_turns(ctx, meta.session_id)),
                    last_turn_at=meta.last_turn_at or meta.created_at,
                    created_at=meta.created_at,
                    last_bundle_version=meta.bundle_version or "",
                )
            )
        data = SessionListData(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(items) < total,
        )
        return _ok(data, ctx, quota)


def _ok(data: Any, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    from app.api import errors

    envelope = OkEnvelope(trace_id=ctx.trace_id, data=data, server_time=errors.server_time())
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )
