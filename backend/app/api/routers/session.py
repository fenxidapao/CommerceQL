"""`POST /api/v1/session` · `GET /api/v1/session/{session_id}`（附录 A §A.5.1 / §A.5.2）。

层号：L5｜归属窗口：W4。

⚠️ **本文件是"薄"的，这是刻意的**：会话的两个端点没有任何业务判定 ——
创建就是把服务端生成的 `session_id` 落地，读取就是把记录翻译成 DTO。
判定（存在性、所有权、TTL）全在 `app/api/state_store.py`，映射全在 `app/api/errors.py`。

⚠️ 两个安全约束在这里的落点（都不是形式主义）：

1. **`POST /session` 不收 `title`**（§A.5.1 的 B-19 修订）。
   由 `dto/session.py` 的 `extra="forbid"` 保证"客户端还在传 `title`"变成
   **400（`INVALID_REQUEST`）显式拒绝**，
   而不是静默忽略 —— 静默忽略会让联调期变成"我传了 title 但列表里没有"这种要翻代码的问题。
   本文件**不**读请求体，所以也不可能"顺手"把 `title` 用上。

2. **`GET /session/{id}` 只回计划摘要，不回原始 SQL**（PRD FR-10.1）。
   由 DTO 保证：`TurnData` 里**没有** `sql` 字段。本文件**不得**把 `turn` 字典整体透传
   （`append_turn` 落的记录里有 `bundle_version` 等内部字段），必须逐字段投影。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
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
from app.api.dto.session import (
    CreateSessionRequest,
    SessionCreatedData,
    SessionDetailData,
    TurnData,
)
from app.api.exceptions import SessionNotFound
from app.api.ratelimit import RateLimitQuota
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.core.enums import RateLimitBucket
from app.obs.trace import new_id

__all__ = ["router"]

router = APIRouter(prefix="/session", tags=["session"])


@router.post(
    "",
    summary="创建会话",
    responses={429: {"description": "配额超限（写入类桶）"}},
)
async def create_session(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    body: CreateSessionRequest | None = None,
) -> JSONResponse:
    """创建会话（附录 A §A.5.1）。

    ⚠️ **每次调用都新建**（§A.12：`POST /session` 明确**不**幂等）——
    故**不**接受 `Idempotency-Key`：接受却不生效比不接受更糟（客户端会以为它起作用了）。

    ⚠️ `body` **声明了却不使用**，这是刻意的：唯一的用处是让 FastAPI **解析并校验**
    请求体，从而把"客户端还在传 `title`"变成 400（`extra="forbid"`）而不是静默忽略。
    省略这个参数会让端点接受任意 body（见 `CreateSessionRequest` 的 docstring）。

    ⚠️ `title` 此刻**故意为空**：§A.5.4 说标题取**首轮问题**前 20 字，
    而首轮问题要等 `POST /query` 才知道 ⇒ 标题由 `routers/query.py::_record_turn` 补写。
    """
    del body  # 只用于触发请求体校验，见 docstring（`extra="forbid"` 的落点）
    store = get_state_store(request)
    ctx = new_identity(token, session_id=new_id("session"))
    remember_identity(request, ctx)

    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.WRITE, ctx)
        meta = await store.create_session(ctx)
        return _ok(
            SessionCreatedData(session_id=meta.session_id, created_at=meta.created_at),
            ctx,
            quota,
        )


@router.get(
    "/{session_id}",
    summary="读取会话历史（**只回计划摘要**）",
    responses={
        404: {"description": "SESSION_NOT_FOUND"},
        429: {"description": "配额超限（读取类桶）"},
    },
)
async def get_session(
    request: Request,
    session_id: str,
    token: Annotated[VerifiedToken, Depends(authenticate)],
) -> JSONResponse:
    """会话详情（附录 A §A.5.2）。

    ⚠️ **404 与"空历史"是两件事**：会话不存在 → `SESSION_NOT_FOUND`（前端渲染
    "该会话不存在或已删除" + "开始新会话"）；会话存在但还没有轮次 → `200` + `turns: []`
    （前端渲染空列表）。把前者做成 200+空列表会让"会话被删了"看起来像"我还没问过问题"。
    """
    store = get_state_store(request)
    ctx = new_identity(token, session_id=session_id)
    remember_identity(request, ctx)

    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        meta = await store.get_session(ctx, session_id)
        if meta is None:
            raise SessionNotFound("会话不存在或已删除", detail={"session_id": session_id})
        turns = await store.get_turns(ctx, session_id)
        return _ok(
            SessionDetailData(
                session_id=meta.session_id,
                turns=[_turn(turn) for turn in turns],
                # ⚠️ P0 恒 `None`：多轮指代消解需要"历史消息"载体，而 `GraphState` 的
                #    11 组字段里没有它（`normalize` 已按 `history=()` 调用并登记该缺口）。
                #    没有游标可给 ⇒ 如实返回 `None`，不编一个 `"tu_1"`（U-22）。
                context_cursor=None,
            ),
            ctx,
            quota,
        )


def _ok(data: Any, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    """成功封套 + 逐桶限流四头（与 `routers/query.py::_ok` 同形）。"""
    from app.api import errors

    envelope = OkEnvelope(trace_id=ctx.trace_id, data=data, server_time=errors.server_time())
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )


def _turn(raw: Any) -> TurnData:
    """`session_plan` 的一条记录 → `TurnData`（**逐字段投影**，见模块 docstring 约束 2）。

    ⚠️ 记录里没有的字段一律**不编**：`plan_summary` 缺失就是 `None`，
    而 `outcome` 缺失时取 `failed` —— 它表示"这一轮的结论没有落下来"，
    比默认成 `success` 诚实得多（后者会让"失败的一轮"在历史里显示为成功）。
    """
    from app.core.enums import Outcome

    if not isinstance(raw, dict):  # pragma: no cover - 记录由本进程写入，形状受控
        raw = {}
    return TurnData(
        task_id=str(raw.get("task_id") or ""),
        question=str(raw.get("question") or ""),
        outcome=str(raw.get("outcome") or Outcome.FAILED.value),
        plan_summary=raw.get("plan_summary") if isinstance(raw.get("plan_summary"), dict) else None,
        at=str(raw.get("at") or ""),
    )
