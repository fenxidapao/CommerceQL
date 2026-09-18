"""`POST /api/v1/clarify` —— 回答澄清（SSE 流式，附录 A §A.4）。

层号：L5｜归属窗口：W4。

--------------------------------------------------------------------------
一、为什么是"新开一条流"而不是"续原流"
--------------------------------------------------------------------------
附录 A §A.4 的响应是"与 `/query` 相同的 SSE 事件流"；W5 RELAY §1.1 说
"用户选择后前端**新开一条 `POST /clarify` 流**（不是续原流）"。
两处一致，且这正是 `SseRunner` 的唯一姿势 —— 它一次只驱动一次图。

⚠️ 文档 §A.4 有一句"（从 `stage=schema_linking` 之后继续）"。**本实现不遵守那句**，
理由是它与 FR-9.2（P0 安全）冲突：
> FR-9.2 —— 澄清后必须**重新完整走一遍**权限、字段绑定、SQL 校验、成本闸门与执行，
> **禁止拼接或复用澄清前的 SQL**。
"从 `schema_linking` 之后继续"意味着**复用澄清前的绑定结果**；一旦用户权限在会话期间
被变更，那就是一条越权后门。故本实现**从 `intent` 重新开始整图**。
对前端的影响仅是进度条从第一段重走（`stage` 是追加语义，不是替换）——
已登记为"与 §A.4 括注的偏离"，上呈架构裁决（不是静默取舍）。

--------------------------------------------------------------------------
二、问题重组格式：**文档没有规定**，故这里显式登记
--------------------------------------------------------------------------
`ClarifyContext` 存的是"重跑所需的最小输入"（原问题 + 会话 + 选项 + 原轮 options），
但**没有一处文档**说"用户答案"要以什么形式并回问题（`FR-9.2` 只说"以自由文本形式并入"）。
本实现取最保守的形式（见 `_compose_question`）并**登记为 UNVERIFIED**：
它是实现选择，不是契约事实；若架构裁定另一种格式，改动点只有那一个函数。

--------------------------------------------------------------------------
三、一次性消费 vs 幂等（§A.12 的偏离，如实登记）
--------------------------------------------------------------------------
附录 A §A.12 的分表把 `POST /clarify` 也列为 ✅ 幂等（`Idempotency-Key`）。
本实现**不接**`Idempotency-Key`，改用更强也更简单的机制：**澄清上下文一次性消费**。

为什么不接幂等键：幂等重放要"回同一个 `task_id`"，而重放请求**必须**知道
`session_id`（审计三元组 + 会话锁键），它只存在于澄清记录里；一旦首次应答消费掉了记录，
重放就只能拿到 `CLARIFY_EXPIRED`(410) —— 即"幂等靠记录复读，一次性靠记录消失"，
两者对同一条记录有**相反**的要求。要同时支持就得给记录加一个"已消费"状态
（多一个状态机、多一处过期语义），而 §A.12 的幂等目标（防重复执行）**一次性已达成**，
且更强（第二次连执行机会都没有）。

⇒ 偏离已登记；`Idempotency-Key` 头**不予接受**（不静默忽略：语义上与 `POST /session` 同类）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api import errors
from app.api.deps import (
    authenticate,
    check_rate_limit,
    get_graph_runtime,
    get_state_store,
    new_identity,
    remember_identity,
    session_lock_guard,
)
from app.api.dto.clarify import ClarifyRequest
from app.api.dto.query import MAX_QUESTION_LEN
from app.api.exceptions import ClarifyExpired, ClarifyInvalidOption, InvalidRequest
from app.api.runner import RunRequest, SseRunner
from app.api.sse import SSE_MEDIA_TYPE
from app.api.state_store import ClarifyContext, RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.enums import RateLimitBucket
from app.obs.logging import get_logger
from app.obs.trace import new_id

__all__ = ["compose_question", "router"]

_log = get_logger(__name__)

router = APIRouter(prefix="/clarify", tags=["clarify"])

#: 并入答案时的标记（见 `compose_question` 的登记说明）。
_ANSWER_MARKER = "（澄清补充：{answer}）"


@router.post(
    "",
    summary="回答澄清（SSE 流式）",
    response_class=StreamingResponse,
    responses={
        200: {"content": {SSE_MEDIA_TYPE: {}}, "description": "与 /query 相同的事件流"},
        410: {"description": "CLARIFY_EXPIRED（上下文不存在或已过期）"},
        422: {"description": "CLARIFY_INVALID_OPTION（选项不在上下文里）"},
        429: {"description": "配额超限（查询类桶）"},
    },
)
async def answer_clarify(
    request: Request,
    body: ClarifyRequest,
    token: Annotated[VerifiedToken, Depends(authenticate)],
) -> StreamingResponse:
    store = get_state_store(request)
    runtime = get_graph_runtime(request)

    # --- 1. 限流（查询类桶：澄清会触发一整轮 LLM 调用）---
    # ⚠️ 此刻还不知道 `session_id`（它就在下面要读的澄清记录里），故用占位身份 ——
    #    与 `routers/query.py` 第 2 步同理：限流只需 tenant/user/role。
    # ⚠️ 占位身份也要 `remember_identity`：否则这里的 `429` / `410` 响应里 `trace_id` 是 null
    #    （它们都发生在第 6 步的身份落地之前）。见 `deps.remember_identity`。
    provisional = new_identity(token, session_id=new_id("session"))
    remember_identity(request, provisional)
    quota = await check_rate_limit(request, RateLimitBucket.QUERY, provisional)

    # --- 2. 读澄清上下文（按**租户**读：此刻还没有 `session_id`，见 `state_store` 的说明）---
    context = await store.get_clarify_for_tenant(token.tenant_id, body.clarify_id)
    if context is None:
        # "不存在"与"过期"同形同码（§A.13：有效期 5 分钟）—— 对用户是同一件事：重问一遍。
        raise ClarifyExpired(
            "澄清已过期，请重新提问", detail={"clarify_id": body.clarify_id}
        )

    # --- 3. 校验选项（附录 A §A.4 的 422）---
    answer = _answer_of(body, context)

    # --- 4. 重组问题（FR-9.2：完整重跑，不复用任何澄清前的结论）---
    question = compose_question(context.raw_question, answer)
    if len(question) > MAX_QUESTION_LEN:
        # 跨字段约束（原问题 + 答案），DTO 看不见 ⇒ 在这里收敛。
        raise InvalidRequest(
            f"澄清补充并入原问题后超过 {MAX_QUESTION_LEN} 字，请缩短补充内容",
            detail={"length": len(question), "limit": MAX_QUESTION_LEN},
        )

    # --- 5. 一次性消费（**在跑图之前**：否则同一 clarify_id 可被反复回答，见模块 §三）---
    await store.drop_clarify(_tenant_scope(token, context), body.clarify_id)

    # --- 6. 身份落地：ADR-03 —— 澄清后的 run 是**新 `task_id`**；会话沿用原轮的 ---
    ctx = new_identity(token, session_id=context.session_id, task_id=new_id("task"))
    remember_identity(request, ctx)

    # --- 7. 抢锁（同 `routers/query.py` 模块 §二：此刻抛 409 还来得及）---
    stack = AsyncExitStack()
    await stack.enter_async_context(session_lock_guard(request, ctx))

    runner = SseRunner(graph=runtime.graph, store=store, new_deps=runtime.new_deps)
    run_request = RunRequest(
        identity=ctx,
        question=question,
        # ⚠️ **继承原轮的 options**（`ClarifyContext.run_options`）：§A.4 的请求体里没有它，
        #    不继承就会用 DTO 默认值 ⇒ `max_rows`/`explain`/`timezone` 静默变化。
        options=dict(context.run_options) if context.run_options else None,
        # ⚠️ 澄清不复用幂等键（模块 §三）：原 key 属于"原问题"那一轮，
        #    带着它会让这次重跑被误判成"同键不同体"而 409。
        idempotency_key=None,
        explain=_explain_of(context.run_options),
    )

    async def _frames() -> AsyncIterator[bytes]:
        try:
            async for frame in runner.stream(run_request):
                yield frame
        finally:
            await stack.aclose()
            await _record_turn(store, ctx, question, runner.outcome)

    return StreamingResponse(
        _frames(), media_type=SSE_MEDIA_TYPE, headers=errors.sse_response_headers(quota)
    )


# ===========================================================================
# 内部
# ===========================================================================


def _tenant_scope(token: VerifiedToken, context: ClarifyContext) -> Any:
    """构造一个**只用于删除澄清记录**的 `IdentityContext`（`drop_clarify` 只用 `tenant_id`）。

    ⚠️ 显式构造而不复用第 6 步的 `ctx`：删除发生在 `ctx` 落地**之前**
    （顺序不可换：先删再跑，否则并发第二次请求仍能读到记录并再跑一轮，见模块 §三）。
    """
    from app.core.contracts import IdentityContext

    return IdentityContext(
        # 占位标识：本对象只服务一次 `DEL`（键含租户），不参与任何授权判定。
        trace_id=new_id("trace"),
        task_id=context.task_id or new_id("task"),
        session_id=context.session_id or new_id("session"),
        tenant_id=token.tenant_id,
        user_id=token.subject,
        role=token.role,
    )


def _answer_of(body: ClarifyRequest, context: ClarifyContext) -> str:
    """取出用户的可读答案，并校验选项合法性（附录 A §A.4 的 422）。

    ⚠️ 选项的**取值字段**是 `value`（`clarify_out._option` 的产物：`{value,label,asset}`）。
    这里只认 `value` —— 认 `label` 会让"前端把展示文案传回来"也通过校验，
    而展示文案是可以被本地化/被用户改写的，不构成"上下文里存在的选项"。
    """
    if body.free_text is not None and body.free_text.strip():
        return body.free_text.strip()

    selected = (body.selected_value or "").strip()
    allowed = {
        str(option.get("value"))
        for option in context.options
        if isinstance(option, Mapping) and option.get("value") is not None
    }
    if selected not in allowed:
        # ⚠️ `detail` 里**不回显** `allowed`：澄清选项可能含资产名/口径名，
        #    而"把服务端的合法取值集合回给客户端"是一个不必要的枚举面（N-11 的精神）。
        raise ClarifyInvalidOption(
            "所选选项不在本次澄清的候选中",
            detail={"clarify_id": context.clarify_id},
        )
    return selected


def compose_question(raw_question: str, answer: str) -> str:
    """把答案并回原问题（FR-9.2："以自由文本形式并入"）。

    ⚠️ **文档没有规定格式**（模块 §二）：本函数是实现选择，已登记 UNVERIFIED。
    选当前形式的三条理由：
    1. `raw_question` **原样保留在最前**——不重写用户的句子。重写会让
       "用户原话"这一事实在 `normalize` 之前就丢失，而 `raw_question` 是审计与
       few-shot 检索（`semantic_few_shot` 按问题文本）的输入；
    2. 答案用**全角括号**标出，模型与人都能看出哪一段是补充，且不引入新句式；
    3. 不引 Prompt 指令（如"请按以下澄清回答"）——那是 L3 提示词的职责，
       在接入层拼指令会让"提示词版本化"（W3A 的资产管理面）出现第二处。

    ⚠️ 副作用（如实登记）：改写后的问题与 `semantic_retrieval` 的缓存键（按问题文本哈希）
    必定 miss。这是正确的 —— 澄清后的语义确实变了，复用旧检索结果才是错的。
    """
    return f"{raw_question}{_ANSWER_MARKER.format(answer=answer)}"


def _explain_of(run_options: Mapping[str, Any] | None) -> bool:
    """从原轮 `options` 取 `explain`（缺省 `True` = 附录 A §A.1.1 的默认值）。"""
    if not run_options:
        return True
    value = run_options.get("explain")
    return True if value is None else bool(value)


async def _record_turn(
    store: RedisStateStore, ctx: Any, question: str, outcome: Any
) -> None:
    """流结束后记会话历史（与 `routers/query.py::_record_turn` 同职责）。

    ⚠️ 这里**必须重复一遍**那段逻辑（而不是 import 过来）：两处的 `question` 不同
    （这里是**重组后**的问题），且 `query.py` 的版本读的是 `body.question`。
    抽公共函数会让"记哪个问题"变成一个参数 —— 而它恰恰是唯一会变的东西。
    两处都必须遵守的同一条：**写失败不抛**（流已结束）。
    """
    if outcome is None:  # pragma: no cover
        return
    from app.api.routers.query import _turn_outcome
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
            task_id=getattr(ctx, "task_id", None),
            error_type=type(exc).__name__,
            extra_fact="澄清轮已结束 → 历史写入失败只告警",
        )


def _iter_option_values(options: Sequence[Any]) -> Any:  # pragma: no cover - 保留给后续窗口
    return (option.get("value") for option in options if isinstance(option, Mapping))
