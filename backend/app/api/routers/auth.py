"""`POST /api/v1/auth/register` · `POST /api/v1/auth/login`（Phase B B3）。

层号：L5｜归属窗口：Phase B B3。

安全口径（与 `plan §4 B3` 逐条对应）：
1. **统一错误文案**：未知用户与错密码同为 `AUTH_FAILED` + 同一句话，防用户名枚举；
2. **禁用账号** 403（`FORBIDDEN_SCOPE`）—— 这是文档要求的显式分支，
   它确实暴露"该用户名存在且被禁用"，与"防枚举"存在张力；按计划优先满足前者；
3. **登录限流**：走 ADMIN 桶（5 次/分钟/IP）——登录前没有可信身份，
   只能以客户端 IP 作为限流主体（租户固定为 `auth` 占位，不落任何业务租户）；
4. **注册默认关闭**（`AUTH_ALLOW_REGISTRATION`），租户来自服务端配置；
5. **不记录明文密码**：本文件不写日志；异常文本只含"用户名或密码错误"。

⚠️ 重复用户名 → 409：`ErrorCode` 是封闭 28 值且没有 `USER_EXISTS`，
复用 `IDEMPOTENCY_CONFLICT`（409）而不是新增错误码；新增码需先改 §A.11 与断言集。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    check_rate_limit,
    get_runtime,
    get_token_issuer,
    get_user_store,
    remember_identity,
)
from app.api.dto.auth import LoginRequest, RegisterData, RegisterRequest, TokenData
from app.api.dto.common import OkEnvelope
from app.api.exceptions import ForbiddenScope, IdempotencyConflict
from app.api.ratelimit import RateLimitQuota
from app.auth.errors import AuthError
from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import TokenIssuer
from app.core.config import Settings
from app.core.contracts import IdentityContext
from app.core.enums import RateLimitBucket, Role
from app.obs.trace import new_id
from app.repo.users import UserStore

__all__ = ["router"]

router = APIRouter(prefix="/auth", tags=["auth"])

#: 未知用户的计时对照串（模块加载时算一次）。目的是让"用户不存在"与"密码错"
#: 在 scrypt 上耗时接近，而不是每次登录都现场造盐再散列。
_DUMMY_HASH = hash_password("dummy-password-for-timing-only")


def _preauth_context(request: Request) -> IdentityContext:
    """登录前没有令牌：用客户端 IP 作为限流主体（不伪造业务身份）。"""
    host = request.client.host if request.client and request.client.host else "unknown"
    return IdentityContext(
        trace_id=new_id("trace"),
        task_id="",
        session_id="",
        tenant_id="auth",
        user_id=f"ip:{host}",
        role=Role.ANALYST,
    )


def _ok(data: Any, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    from app.api import errors

    envelope = OkEnvelope(trace_id=ctx.trace_id, data=data, server_time=errors.server_time())
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )


@router.post(
    "/register",
    summary="注册本地账号",
    responses={
        403: {"description": "注册未开放（FORBIDDEN_SCOPE）"},
        409: {"description": "用户名已存在（IDEMPOTENCY_CONFLICT）"},
        429: {"description": "配额超限（管理员类桶）"},
    },
)
async def register(
    request: Request,
    body: RegisterRequest,
    users: Annotated[UserStore, Depends(get_user_store)],
) -> JSONResponse:
    ctx = _preauth_context(request)
    remember_identity(request, ctx)
    quota = await check_rate_limit(request, RateLimitBucket.ADMIN, ctx)

    settings: Settings = get_runtime(request).settings
    if not settings.AUTH_ALLOW_REGISTRATION:
        raise ForbiddenScope("注册未开放")

    user_id = new_id("user")
    try:
        await users.insert_user(
            user_id=user_id,
            tenant_id=settings.AUTH_REGISTRATION_TENANT_ID,
            username=body.username,
            password_hash=hash_password(body.password),
            role=Role.ANALYST.value,
        )
    except IntegrityError as exc:
        raise IdempotencyConflict("用户名已存在") from exc

    from app.api import errors

    return _ok(
        RegisterData(
            user_id=user_id,
            username=body.username,
            created_at=errors.server_time() or "",
        ),
        ctx,
        quota,
    )


@router.post(
    "/login",
    summary="登录并签发令牌",
    responses={
        401: {"description": "AUTH_FAILED"},
        403: {"description": "账号已禁用（FORBIDDEN_SCOPE）"},
        429: {"description": "配额超限（管理员类桶）"},
    },
)
async def login(
    request: Request,
    body: LoginRequest,
    users: Annotated[UserStore, Depends(get_user_store)],
    issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> JSONResponse:
    ctx = _preauth_context(request)
    remember_identity(request, ctx)
    quota = await check_rate_limit(request, RateLimitBucket.ADMIN, ctx)

    row = await users.find_by_username(body.username)
    # ⚠️ 未知用户也走一次散列校验，保持两条失败路径的耗时接近（降低计时侧信道）。
    password_ok = verify_password(body.password, row.password_hash if row else _DUMMY_HASH)
    if row is None or not password_ok:
        raise AuthError("用户名或密码错误", step=1, reason="bad_credentials")
    if row.disabled:
        raise ForbiddenScope("账号已禁用")

    try:
        role = Role(row.role)
    except ValueError as exc:
        raise AuthError("账号角色配置无效", step=5, reason="unknown_role") from exc

    issued = issuer.issue(
        subject=row.user_id,
        tenant_id=row.tenant_id,
        role=role,
        shop_ids=row.shop_ids,
    )
    return _ok(
        TokenData(
            access_token=issued.access_token,
            expires_in=issued.expires_in,
        ),
        ctx,
        quota,
    )
