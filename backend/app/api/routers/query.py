"""`POST /api/v1/query` · `POST /query/{task_id}/cancel` · `GET /query/{task_id}`。

层号：L5｜归属窗口：W4（docs/08 §4.1 的 `app/api/routers/**`）。

--------------------------------------------------------------------------
一、本文件只做四件事：解析 → 拦截 → 装配 → 翻译
--------------------------------------------------------------------------
| 步骤 | 动作 | 唯一实现处 |
|---|---|---|
| 解析 | 请求体 → DTO（`api/dto/query.py`，键名已由契约测试钉死） | 本文件 |
| 拦截 | 验签 · 限流 · 会话锁 · 幂等 | `app/api/deps.py` + `state_store` |
| 装配 | 组装 `RunRequest` 交给 `SseRunner` | 本文件 |
| 翻译 | 领域结果 → HTTP 响应 / 领域异常 | `app/api/errors.py` 查表 |

⚠️ 本文件**不得**：映射错误码（`errors.map_*` 唯一）、拼 SSE 帧（`sse.encode` 唯一）、
判定任务状态（`runner.task_status_of` 唯一）、自己构造错误响应（`errors.error_response` 唯一）。

--------------------------------------------------------------------------
二、为什么 SSE 的会话锁要在**返回响应之前**显式进入
--------------------------------------------------------------------------
`session_lock_guard` 若写在生成器里（`async with ...: yield`），acquire 会发生在
**响应头已发出之后**（Starlette 在 `http.response.start` 之后才迭代 body）。
那时"抢锁失败"已经**无法**变成 `409 SESSION_CONFLICT` —— 只能往流里塞一个 error 事件，
而前端拿到 `200` + 事件，与附录 A §A.11 的 409 契约不符（前端只对 409 自动重试）。

⇒ 用 `AsyncExitStack`：**先** `enter_async_context`（此刻抛 409 还来得及），
`aclose()` 留给生成器的 `finally`（释放点仍在图结束 / 客户端断连那一刻，07 §9.3）。
`aclose()` 幂等，重复调用安全。

⚠️ 已知边界（如实登记）：客户端若在响应被迭代**之前**就断开，生成器一次都没跑，
`finally` 不执行 ⇒ 锁留到 `SESSION_LOCK_TTL_S` 自然过期。不会死锁（有 TTL）。

--------------------------------------------------------------------------
三、幂等重放：沿用原 `task_id`（§A.12），但"同一流"是 P0 缺口
--------------------------------------------------------------------------
`begin_idempotent` 在**构造身份之前**调用 —— 它的结果决定这一轮用哪个 `task_id`
（故它收 `tenant_id` + `new_task_id` 而不是 `ctx`，理由见 `state_store` 方法 docstring）。

⚠️ §A.12 说"同 key 24h 返回同一 `task_id` 与**同一流**"。P0 只做到前半句：
事件重放需要 `event_buffer`（键已备好、**未接线**）⇒ 重放请求会**重新跑一遍图**。
如实登记，不写成"已完全实现"。

--------------------------------------------------------------------------
四、`cancel` / `poll` 的 `session_id` 缺口（如实说明，不掩盖）
--------------------------------------------------------------------------
附录 A §A.2 / §A.3 的路径里**只有 `task_id`**，没有 `session_id`。
而 `IdentityContext.session_id` 是审计三元组的一部分、非空才有意义（`build_identity` 硬拒空值）。
⇒ 这两个端点用一个**服务端生成的**会话占位 id；任务侧的**真实**会话归属仍在
`task_state` 记录里（`session_id` 字段，读端所有权校验也用它）。
为什么不去读它再重造身份：那属于"先拿真事实换身份、再拆身份" ——
而 `cancel_task` / `get_task` 的所有权校验只比对 `tenant_id` + `user_id`，
**不看** `session_id` ⇒ 重造身份对结果**零影响**，只是多一次绑/解绑。
（登记为接线事实，见交付件。）
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api import errors
from app.api.deps import (
    authenticate,
    check_rate_limit,
    get_graph_runtime,
    get_state_store,
    new_identity,
    remember_identity,
    session_lock_guard,
    trace_scope,
)
from app.api.dto.common import OkEnvelope
from app.api.dto.query import CancelData, QueryRequest, TaskStatusData
from app.api.exceptions import (
    IdempotencyConflict,
    SessionNotFound,
    TaskNotCancellable,
    task_not_found,
)
from app.api.ratelimit import RateLimitQuota
from app.api.runner import RunOutcome, RunRequest, SseRunner
from app.api.sse import SSE_MEDIA_TYPE
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.core.enums import Outcome, RateLimitBucket, SseEvent, TaskStatus
from app.obs.logging import get_logger
from app.obs.trace import new_id

__all__ = ["HEADER_IDEMPOTENCY_KEY", "router"]

_log = get_logger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

#: 幂等键请求头（附录 A §A.12；CORS 侧已在 `main.py` 放行）。
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"

#: 轮询响应里**允许透传**的字段（附录 A §A.2："与 SSE 的 data/chart/insight/meta 同构"）。
#:
#: ⚠️ 用白名单而**不是** `**payload`：`task_state` 的值里带 `tenant_id`/`user_id`/
#: `cancel_requested` 等**内部字段**（读端所有权校验靠它们）。直接透传会把租户与用户标识
#: 回给客户端 —— N-12 把它们列为 PII，且"响应里多出别的字段"会绕开契约测试的字段断言。
_POLL_FIELDS: tuple[str, ...] = (
    "stage",
    "queued_at",
    "started_at",
    "finished_at",
    "progress",
    "sql",
    "data",
    "chart",
    "insight",
    "meta",
    "audit_ref",
)

#: 终态集合（**由 `TaskStatus` 推导**）。
#: ⚠️ 不 import `state_store._TERMINAL_STATUSES`：那是该模块的实现细节，
#: 跨模块 import 私有名会让"改一处"变成"改两处"。枚举才是唯一事实。
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        TaskStatus.SUCCEEDED.value,
        TaskStatus.CLARIFY.value,
        TaskStatus.REFUSE.value,
        TaskStatus.DEGRADED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)


#: 终态事件 → 审计结论（`_turn_outcome` 的唯一数据源；见那里的表格与理由）。
_TERMINAL_TO_OUTCOME: Mapping[str, str] = {
    SseEvent.COMPLETE.value: Outcome.SUCCESS.value,
    SseEvent.CLARIFY.value: Outcome.CLARIFY.value,
    SseEvent.REFUSE.value: Outcome.REFUSE.value,
    SseEvent.ERROR.value: Outcome.FAILED.value,
}


# ===========================================================================
# POST /query —— SSE
# ===========================================================================


@router.post(
    "",
    summary="提交自然语言查询（SSE 流式）",
    response_class=StreamingResponse,
    responses={
        200: {"content": {SSE_MEDIA_TYPE: {}}, "description": "SSE 事件流（附录 A §A.1.2）"},
        409: {"description": "SESSION_CONFLICT / IDEMPOTENCY_CONFLICT"},
        429: {"description": "配额超限（查询类桶）"},
    },
)
async def submit_query(
    request: Request,
    body: QueryRequest,
    token: Annotated[VerifiedToken, Depends(authenticate)],
) -> StreamingResponse:
    store = get_state_store(request)
    runtime = get_graph_runtime(request)

    # --- 1. 会话标识（不传则服务端新建，附录 A §A.1.1）---
    session_id = body.session_id or new_id("session")

    # --- 2. 限流。⚠️ 此刻还没有最终 `task_id`（幂等可能改写它），故用一个**不绑定
    #        contextvar** 的临时身份：`check_rate_limit` 只用 tenant/user/role。---
    # ⚠️ 临时身份也要 `remember_identity`：否则**429 的响应里 `trace_id` 是 null**
    #    （限流是进入端点后第一个会抛错的步骤，见 `deps.remember_identity`）。
    provisional = new_identity(token, session_id=session_id)
    remember_identity(request, provisional)
    quota = await check_rate_limit(request, RateLimitBucket.QUERY, provisional)

    # --- 3. 会话存在性（仅当客户端显式给了 session_id）---
    session = await store.get_session(provisional, session_id)
    if session is None:
        if body.session_id is not None:
            # ⚠️ 必须与"新建"区分：客户端给了一个不存在的 id 时报错，
            #    否则"打错会话 id"会静默变成"开了一个新会话"，历史凭空断掉。
            raise SessionNotFound("会话不存在或已过期", detail={"session_id": session_id})
        await store.create_session(provisional)

    # --- 4. 幂等判定（结果决定 task_id ⇒ 必须在身份落地之前）---
    idem_key = request.headers.get(HEADER_IDEMPOTENCY_KEY)
    request_hash = _request_hash(body)
    decision = await store.begin_idempotent(
        tenant_id=token.tenant_id,
        new_task_id=new_id("task"),
        idempotency_key=idem_key,
        request_hash=request_hash,
    )
    if decision.conflict:
        detail = (
            {"original_task_id": decision.existing_task_id} if decision.existing_task_id else {}
        )
        raise IdempotencyConflict("同一幂等键的请求体不一致", detail=detail)

    # --- 5. 身份落地（此后 contextvar 里的 task_id 就是这一轮真正使用的那个）---
    ctx = new_identity(token, session_id=session_id, task_id=decision.task_id)
    remember_identity(request, ctx)
    if decision.replayed:
        _log.warning(
            "idempotent_replay",
            task_id=ctx.task_id,
            extra_fact="同键同体重放：沿用原 task_id 重跑（事件重放未接线，见模块 §三）",
        )
    elif idem_key is not None:
        # ⚠️ 必须在**执行之前**回填：否则并发重放者读到空 task_id 会被判成冲突（§A.12）。
        await store.fill_idempotency(
            ctx, idempotency_key=idem_key, task_id=ctx.task_id, request_hash=request_hash
        )

    # --- 6. 抢锁：此刻抛 409 还来得及改 HTTP 状态（模块 §二）---
    stack = AsyncExitStack()
    await stack.enter_async_context(session_lock_guard(request, ctx))

    runner = SseRunner(graph=runtime.graph, store=store, new_deps=runtime.new_deps)
    run_request = RunRequest(
        identity=ctx,
        question=body.question,
        # ⚠️ `model_dump()` 得到**纯 dict**：`graph/edges.py` 的转异步判定读字面量键
        #    （`async_if_slow` / `async_threshold_ms`），传 pydantic 对象会静默恒假。
        options=body.options.model_dump() if body.options is not None else None,
        idempotency_key=idem_key,
        explain=body.options.explain if body.options is not None else True,
    )

    async def _frames() -> AsyncIterator[bytes]:
        try:
            async for frame in runner.stream(run_request):
                yield frame
        finally:
            await stack.aclose()
            await _record_turn(store, ctx, body.question, runner.outcome)

    return StreamingResponse(
        _frames(),
        media_type=SSE_MEDIA_TYPE,
        headers=errors.sse_response_headers(quota),
    )


# ===========================================================================
# POST /query/{task_id}/cancel
# ===========================================================================


@router.post("/{task_id}/cancel", summary="取消进行中的查询（幂等）")
async def cancel_query(
    request: Request,
    task_id: str,
    token: Annotated[VerifiedToken, Depends(authenticate)],
) -> JSONResponse:
    """幂等取消（附录 A §A.3 / §A.12）。

    ⚠️ 四种结果的分派**只有一处**（`state_store.CancelOutcome`）：本函数不重新判断
    "已完成的任务能不能取消" —— 判据写两遍就会出现"某个终态在两个端点上行为不同"。
    ⚠️ `cancelled` 与 `already_cancelled` **都返回 200**（幂等正是这一条）。
    ⚠️ 未被取消的路径**不带** `X-RateLimit-*`？—— **要带**：它是 2xx 响应，
    与"409 SESSION_CONFLICT 不带"是两件事（后者不是配额事件，见 `errors.py`）。
    """
    store = get_state_store(request)
    # 模块 §四：路径里没有 session_id，用服务端占位（不影响任何判定）。
    ctx = new_identity(token, session_id=new_id("session"), task_id=task_id)
    remember_identity(request, ctx)

    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.QUERY, ctx)
        outcome = await store.cancel_task(ctx, task_id)
        if outcome.not_found:
            raise task_not_found(task_id)
        if outcome.not_cancellable:
            # 中性文案：用户点「停止」时这一轮常常刚好跑完（W5 RELAY §1.2）。
            raise TaskNotCancellable("该任务已结束，无需取消", detail={"task_id": task_id})
        return _ok(
            CancelData(task_id=task_id, status=TaskStatus.CANCELLED.value), ctx, quota
        )


# ===========================================================================
# GET /query/{task_id}
# ===========================================================================


@router.get("/{task_id}", summary="查询异步任务状态（轮询）")
async def poll_query(
    request: Request,
    task_id: str,
    token: Annotated[VerifiedToken, Depends(authenticate)],
) -> JSONResponse:
    """轮询状态机（附录 A §A.2）。

    ⚠️ `status` 取值集 = `TaskStatus` 的 8 值，**与附录 A §A.2 逐字一致**
    （W0 `d09020c` 已把枚举值对齐 ⇒ W4 PROMPT §七-1 关闭）。
    ⚠️ 不加 `Cache-Control`：前端 3s 轮询，缓存会让状态看起来卡住。
    """
    store = get_state_store(request)
    ctx = new_identity(token, session_id=new_id("session"), task_id=task_id)
    remember_identity(request, ctx)

    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)
        payload = await store.get_task(ctx, task_id)
        if payload is None:
            raise task_not_found(task_id)
        status = str(payload.get("status") or TaskStatus.FAILED.value)
        data = TaskStatusData(
            task_id=task_id,
            status=status,
            # 自描述轮询地址（**非**附录 A 明文）。仅在非终态给：终态再让前端轮询是误导。
            poll_url=None if status in _TERMINAL_STATUSES else str(request.url),
            **{field: payload[field] for field in _POLL_FIELDS if field in payload},
        )
        return _ok(data, ctx, quota)


# ===========================================================================
# 内部
# ===========================================================================


def _ok(data: Any, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    """成功封套 + 逐桶限流四头（W5 RELAY §1.4："逐桶都下发"）。

    ⚠️ 直接构造 `JSONResponse` 而**不用** `response_model`：后者无法在**同一个响应**上
    同时给业务体与限流头（FastAPI 的 `response_model` 走的是另一条序列化路径）。
    ⚠️ `code` 恒 `"OK"`（`OkEnvelope` 的默认值）：附录 A §A.0.4 + W5 RELAY §1.6 ——
    "`2xx` 但 `code !== 'OK'` 前端按错误处理"，故**不得**用 `code` 承载子状态。
    """
    envelope = OkEnvelope(
        trace_id=ctx.trace_id, data=data, server_time=errors.server_time()
    )
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )


async def _record_turn(
    store: Any, ctx: IdentityContext, question: str, outcome: RunOutcome | None
) -> None:
    """流结束后记会话历史 —— **断连的那一轮也要进历史**。

    ⚠️ 读 `runner.outcome`（由 `SseRunner.stream` 的 `finally` 赋值 ⇒ 断连也有值）：
    没有它就无法知道这一轮的结论，历史里会缺 turns 或写错 outcome。
    ⚠️ 写失败**不抛**：流已经结束，抛错只会在日志里多一条无主的栈（用户那一轮的结果已到手）。
    ⚠️ 存的是 `Outcome`（**5 值审计结论**），不是 `TaskStatus`（8 值状态机）——
    附录 A §A.5.2 的示例是 `"outcome": "success"`，且 `TurnData` 的 docstring 已就此立规。
    两个取值集**不得混用**，故映射只在本文件的 `_turn_outcome` 里做一次。
    """
    if outcome is None:  # pragma: no cover - 只有生成器未跑完才可能
        return
    from app.api.state_store import history_title

    try:
        await store.touch_session(
            ctx, title=history_title(question), bundle_version=outcome.bundle_version
        )
        await store.append_turn(
            ctx,
            question=question,
            outcome=_turn_outcome(outcome),
            plan_summary=outcome.plan_summary,
            bundle_version=outcome.bundle_version,
        )
    except Exception as exc:
        _log.warning(
            "session_history_write_failed",
            task_id=ctx.task_id,
            session_id=ctx.session_id,
            error_type=type(exc).__name__,
            extra_fact="本轮已结束 → 历史写入失败只告警（不得把结果变成错误）",
        )


def _turn_outcome(outcome: RunOutcome) -> str:
    """`RunOutcome` → 审计结论（`Outcome`，5 值）。**本映射的唯一实现处。**

    | 终态事件 | `Outcome` | 依据 |
    |---|---|---|
    | `complete` | `success` | 唯一成功出口 |
    | `clarify` | `clarify` | 07 §14.2 B 组 |
    | `refuse` | `refuse` | 07 §14.2 C 组 |
    | `error` | `failed` | 工程故障（§7.6.1 的 refuse/error 边界） |
    | **无终态**（被取消） | `failed` | ⚠️ 与 `runner._record_cancellation` 落的审计行**同一取值**（那里就是 `Outcome.FAILED`）—— 同一轮在两处必须同结论 |

    ⚠️ `Outcome` **没有** `cancelled`：取消在审计口径里是 `failed`（"这一轮没有得出结论"）。
    这里跟随审计（同一事实的权威处），**不**为了让历史好看而发明第六个取值。
    """
    if outcome.terminal_event is None:
        return Outcome.FAILED.value
    return _TERMINAL_TO_OUTCOME.get(outcome.terminal_event, Outcome.FAILED.value)


def _request_hash(body: QueryRequest) -> str:
    """请求体指纹（§A.12 的"同键同体"判据）。

    ⚠️ 用**规范化 JSON**（键排序 + 紧凑分隔符 + `mode="json"` + **默认值归一**）而不是 `str(body)`：
    `str()` 的顺序取决于字段定义顺序，且"`options` 缺省"与"`options` 显式给全部默认值"
    会被算成两个不同指纹 ⇒ 用户**原样重试**却被判成"同键不同体"而 409。
    排序 + 归一后它只依赖**语义**。
    """
    payload = body.model_dump(mode="json", exclude_none=False)
    # ⚠️ `options` 缺省 ≡ 全部取默认值（附录 A §A.1.1 的每项都是 ⭕）。
    #    不归一的话，前端"第一次省略 options、重试时补上默认值"就会被判成冲突 ——
    #    而这两个请求对服务端**完全等价**，判冲突是纯误伤。
    if payload.get("options") is None:
        from app.api.dto.query import AskOptions

        payload["options"] = AskOptions().model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
