"""`POST /api/v1/feedback`（附录 A §A.6）—— 结果反馈与修正。

层号：L5｜归属窗口：W4。

⚠️ **本文件的"薄"是刻意的**（同 `routers/session.py`）：列名/类型/枚举→字面值/
NULL 比较语义**全在** `app/repo/feedback.py`（W1B）；本文件只决定
**何时写、`feedback_id` 从哪来、幂等怎么组合、`queued_for_review` 怎么定**
（`feedback.py` 的三层边界表把这条分工写成了契约）。

## 幂等：**先回读，再写**（不是靠捕异常）

§A.6 的口径 =「同 `task_id` + 同 `reason_code` 视为同一条」，物理实现 =
迁移 `0005` 的 `uq_feedback_task_user_reason`（`NULLS NOT DISTINCT`）。正确形态：

```
find_feedback_id(...)  →  命中 ⇒ 返回**那条的 id**（不写）
                       ↘  未命中 ⇒ new_id("feedback") + insert_feedback
```

🔴 **为什么不能靠捕异常实现幂等**：撞唯一约束抛的是
`sqlalchemy.exc.IntegrityError`（`.orig` 才是 `psycopg.errors.UniqueViolation`），
而**捕到它也拿不到已有记录的 `feedback_id`** —— 那个值不在异常里、
也不在请求里（是上一次调用生成的）。所以"先回读"不是优化，是**唯一**能返回同一条 id 的路径。

⚠️ 并发下仍可能撞（两个请求同时回读到 `None`）⇒ 那时捕 `IntegrityError` **再回读一次**
（唯一约束保证了"回读必有"）。这段竞态恢复**只**在 `Insert` 分支里，不在读路径上。

## `queued_for_review` 的口径（归本窗口定，W1B 不替你选）

§A.6 关于"待审核池"的**唯一**一句话是：

> 修正后的 SQL **不直接生效**，进入待审核池，审核通过后进入 Gold Query 库（PRD FR-11.2）。

⇒ 本窗口取**窄口径**：`queued_for_review = (not is_correct) and (corrected_sql is not None)`。

考虑过并**弃用**的宽口径 `not is_correct`：它的落点是"任何结果有误都进池等归因"。
弃用理由不是"更严格更好"，而是**语义落点不同**：§A.6 那句话里的池是
**Gold Query 候选池**（有可审之物才谈得上"审核通过后入 Gold Query"）；
只有归因（`reason_code`）而**没有修正 SQL** 的反馈，池里没有可审对象 ——
此时回 `true` 才是**谎报**。无论真值如何，**行都已落库**（`feedback_id` 就是证据），
所以 `false` 表示的是"没有待审的修正"，不是"没收到反馈"。

⚠️ 幂等命中时 `queued_for_review` 由**本次请求体**算出（与首次提交同一公式）。
若客户端拿同一个 `(task_id, user_id, reason_code)` 但改了 `is_correct`/`corrected_sql`
重发，库里留的是**首次**的值而响应描述的是**本次**的意图 —— 这是
`FeedbackStore.find_feedback_id` 只回 `feedback_id` 的直接后果，**已登记为已知边界**
（要收紧需 W1B 让回读同时返回 `is_correct`/`corrected_sql`；本窗口不越权改 `app/repo/**`）。
§A.6 的幂等三元组本来就把这种重发定义为"同一条"，属边界外的异常用法。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    authenticate,
    check_rate_limit,
    get_feedback_store,
    get_identity,
    new_identity,
    remember_identity,
    trace_scope,
)
from app.api.dto.common import OkEnvelope
from app.api.dto.feedback import FeedbackData, FeedbackRequest
from app.api.ratelimit import RateLimitQuota
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.core.enums import RateLimitBucket
from app.obs.trace import new_id
from app.repo.feedback import FeedbackStore

__all__ = ["router"]

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post(
    "",
    summary="提交结果反馈与修正（**幂等**：同 task_id + 同 reason_code 返回同一条）",
    responses={
        400: {"description": "请求体不合法（含非 `FeedbackReasonCode` 的 `reason_code`）"},
        429: {"description": "配额超限（写入类桶）"},
    },
)
async def submit_feedback(
    request: Request,
    token: Annotated[VerifiedToken, Depends(authenticate)],
    body: FeedbackRequest,
) -> JSONResponse:
    """结果反馈与修正（附录 A §A.6）。

    ⚠️ **不走 `Idempotency-Key` 头**：§A.12 的幂等分表把 `POST /feedback` 的幂等键
    定成**业务三元组** `task_id + user_id + reason_code`（不是客户端提供的 request key）。
    本端点**不读** `Idempotency-Key` —— 读了却不生效比不读更糟
    （客户端会以为换个 key 就能写第二条，而唯一约束会拒）。

    ⚠️ `user_id` 取 **`IdentityContext.user_id`**，它才是 JWT 的 `sub`
    （链路：`JWT.sub` → `VerifiedToken.subject`（`auth/tokens.py`）→
    `IdentityContext.user_id`（`auth/context.py::build_identity`））。
    **不要**传 `tenant_id`：那会静默造出"跨租户的同一个人"，而幂等三元组里
    恰恰有这个字段 —— 错的值 = 幂等键错 = 同一租户下不同用户的反馈互相顶掉。
    （`app/repo/feedback.py` 的 docstring 行 173 仍写着 `identity.subject`，
    那是 W1B 首版笔误，其开工指令已订正；该文件属 W1B，本窗口只提不落笔。）

    ⚠️ 身份的三个运行标识（`trace_id`/`task_id`/`session_id`）**必须非空**
    （`auth/context.py::build_identity` 的硬校验），而 §A.6 给本端点的请求/响应里
    **没有** session、也没有"本次 run 的 task"—— 反馈不是一个图 run。
    ⇒ 三者一律由服务端新生成（`obs.trace.new_id`），它们只作 trace/审计的挂键；
    **被反馈的那个 `task_id` 只进数据库那一行**，不被伪装成本次请求的 task
    （冒充会让审计与并发键把"一次反馈写入"读成"那个 task 又跑了一次"）。
    """
    store = get_feedback_store(request)
    ctx = new_identity(token, session_id=new_id("session"))
    remember_identity(request, ctx)

    async with trace_scope(ctx):
        # §A.0.6 的分桶表：`POST /feedback` ∈ **写入类**（单用户 30 次/分钟）。
        quota = await check_rate_limit(request, RateLimitBucket.WRITE, ctx)
        feedback_id = await _resolve_feedback_id(
            store,
            task_id=body.task_id,
            # 🔴 唯一正确来源。别写 `token.subject`（那是 `VerifiedToken` 的字段，
            #    在这里恰好同名，一旦上游改了映射就会静默错位）—— 取已是
            #    `IdentityContext` 的那一份，让类型检查参与把关。
            user_id=get_identity().user_id,
            body=body,
        )
        return _ok(
            FeedbackData(feedback_id=feedback_id, queued_for_review=_queued_for_review(body)),
            ctx,
            quota,
        )


def _queued_for_review(body: FeedbackRequest) -> bool:
    """是否入待审核池（**窄口径**，理由见模块 docstring 同名小节）。

    ⚠️ 恒不谎报 `true`：本函数只在"有可审之物（修正 SQL）**且**结果被标为有误"时为真，
    而那一行**必定已经落库** —— 真值不承担任何"可能会写失败"的语义
    （写失败会在 `_resolve_feedback_id` 里向上抛，端点根本到不了这里）。
    """
    return (not body.is_correct) and body.corrected_sql is not None


async def _resolve_feedback_id(
    store: FeedbackStore,
    *,
    task_id: str,
    user_id: str,
    body: FeedbackRequest,
) -> str:
    """幂等的唯一组合点：先回读；未命中才写；竞态撞唯一约束则再回读一次。

    返回**已存在或本次新建**的 `feedback_id` —— 两种情形对 §A.6 是同一个答案
    （"同一条"），这也正是本函数把它们收在一处的原因：调用方拿不到"是新建还是命中"，
    因此不可能写出"命中时走了另一条响应路径"这种分叉。
    """
    existing = await store.find_feedback_id(
        task_id=task_id, user_id=user_id, reason_code=body.reason_code
    )
    if existing is not None:
        return existing

    feedback_id = new_id("feedback")  # → `fb_<32 hex>`（§A.6 明文形态；W0 已登记前缀）
    try:
        await store.insert_feedback(
            feedback_id=feedback_id,
            task_id=task_id,
            user_id=user_id,
            is_correct=body.is_correct,
            reason_code=body.reason_code,
            corrected_sql=body.corrected_sql,
            comment=body.comment,
            correct_result_hint=body.correct_result_hint,
        )
    except IntegrityError:
        # 竞态：另一并发请求在"我们回读之后、写入之前"插进了同一条。
        # 唯一约束是权威 ⇒ 回读拿回它。**回读不到就重抛**：那说明冲突不是
        # "同一条"造成的（例如主键撞了），把它吞掉会变成一次静默的数据丢失。
        raced = await store.find_feedback_id(
            task_id=task_id, user_id=user_id, reason_code=body.reason_code
        )
        if raced is None:  # pragma: no cover - 需要"唯一约束外的冲突"才能触发
            raise
        return raced
    return feedback_id


def _ok(data: Any, ctx: IdentityContext, quota: RateLimitQuota) -> JSONResponse:
    """成功封套 + 逐桶限流四头（与 `routers/session.py::_ok` 同形）。"""
    from app.api import errors

    envelope = OkEnvelope(trace_id=ctx.trace_id, data=data, server_time=errors.server_time())
    return JSONResponse(
        status_code=200,
        content=envelope.model_dump(mode="json"),
        headers=dict(quota.headers()),
    )
