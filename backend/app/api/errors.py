"""异常 → 错误码的**唯一映射点**（附录 A §A.11 / 07 §14.4）。

归属窗口：W0 定接口骨架 → W4 实现端点时使用（docs/08 §4.1）。

它是"唯一入口"文件里的一个（07 §3.2）：消灭的是**同一错误在不同端点映射成不同码**。
这类缺陷在联调期表现为"前端有的页面提示重试、有的页面静默失败"，而根因只是两处各写了一遍映射。

本文件**只做查表**，不做业务判定。四件事一张表答完：
`code` → HTTP 状态 → `retryable`(布尔) → 是否带 `Retry-After` / 是否必须给 `suggestions[]`。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api.ratelimit import RATE_LIMIT_HEADER_NAMES, RateLimitQuota
from app.core.contracts import IdentityContext, RateLimitDecision
from app.core.enums import (
    DEFAULT_SUGGESTIONS,
    ERROR_HTTP_STATUS,
    RATE_LIMIT_BUCKET_RETRY_AFTER_S,
    REQUIRES_SUGGESTIONS,
    RETRY_AFTER_DEFAULT_S,
    RETRY_AFTER_REQUIRED,
    RETRYABLE_BOOLEAN,
    ErrorCode,
    RateLimitBucket,
    RefuseReason,
    Role,
)
from app.core.errors import CommerceQLError

__all__ = [
    "DETAIL_ROLES",
    "EXPOSE_HEADERS",
    "HEADER_RETRY_AFTER",
    "IDENTITY_STATE_KEY",
    "HttpErrorMapping",
    "detail_allowed_for",
    "error_body",
    "error_response",
    "install_exception_handlers",
    "map_code",
    "map_exception",
    "map_rate_limited",
    "map_refuse",
    "rate_limit_headers",
    "server_time",
    "sse_response_headers",
]


HEADER_RETRY_AFTER = "Retry-After"

#: `request.state` 上存身份的键名（见 `_identity_of`：错误响应的 `trace_id` / `role` 从这来）。
IDENTITY_STATE_KEY: Final[str] = "commerceql.identity"


@dataclass(frozen=True, slots=True)
class HttpErrorMapping:
    """HTTP 响应所需的全部事实（**前端零判断权，后端必须给全** —— N-16）。"""

    code: ErrorCode
    status: int
    retryable: bool
    retry_after_s: int | None
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    suggestions: tuple[str, ...] = ()

    def headers(self) -> dict[str, str]:
        """响应头。

        ⚠️ 只产出 `Retry-After`。**绝不产出** `X-RateLimit-*`：
        那些头的语义是"配额剩余"，而 `SESSION_CONFLICT`(409) 与闸门拒绝都不是配额事件 ——
        用错的头会让前端的倒计时条显示错误信息（附录 A §A.0.6 末行、§A.11 补充约定）。
        """
        if self.retry_after_s is None:
            return {}
        return {HEADER_RETRY_AFTER: str(self.retry_after_s)}

    def validate(self) -> None:
        """自检，供契约测试调用（而不是靠评审看）。

        这里锁死的是 07 v0.6 §14.4 的**三级不对称**（**U-17 推翻了我原来的实现**）：
        1. `✅` 必须带 `Retry-After`（"等这么久再发一次会有不同结果"是承诺）；
        2. `⭕` **不得**带 `Retry-After`（它"原样重试必然失败"，给倒计时 = 假承诺），
           **但必须给 `suggestions[]`** —— 对 ⭕ 而言"怎么改"是用户唯一的出路；
        3. `❌` 两者皆无（只显示原因与出口）。
        """
        requires_after = RETRY_AFTER_REQUIRED[self.code]
        has_after = self.retry_after_s is not None
        if requires_after and not has_after:
            raise ValueError(f"{self.code} 必须带 Retry-After（07 §14.4 的 ✅ 档）")
        if not requires_after and has_after:
            raise ValueError(
                f"{self.code} 不得带 Retry-After —— "
                f"它不是 ✅（可原样重试），给了倒计时就是把用户骗进必然失败的重试（U-17）"
            )
        if REQUIRES_SUGGESTIONS[self.code] and not self.suggestions:
            raise ValueError(
                f"{self.code} 属于 ⭕（需改变请求后才可重试），必须同时给 suggestions[] "
                f"—— 只给倒计时不给改法 = 诱导无效操作（07 §14.4）"
            )
        if RETRYABLE_BOOLEAN[self.code] is False and self.retryable:
            raise ValueError(f"{self.code} 的 retryable 必须为 False")


def map_code(
    code: ErrorCode,
    *,
    message: str = "",
    detail: dict[str, Any] | None = None,
    suggestions: tuple[str, ...] = (),
) -> HttpErrorMapping:
    """错误码 → 完整响应事实。**唯一的码级映射实现**。

    ⚠️ `suggestions` 的缺省填充**只对 ⭕ 生效**：那是 `validate()` 的硬约束，
    若不填，构造出的对象**通不过自己的契约检查** —— 而 `map_exception()` 是异常的
    唯一出口，它绝不能产出一个非法对象。缺省值见 `enums.DEFAULT_SUGGESTIONS`（通用改法），
    端点层知道具体原因时**必须覆盖**（例如 gate3 可给"把时间范围收窄到 7 天"）。
    """
    # Retry-After：**只有 ✅ 有**（U-17）。值来自文档明确定义，缺省值登记在 U-22。
    # ⚠️ 这里刻意**不**再读 `ERROR_RETRY_TIER`：`RETRY_AFTER_REQUIRED` 已是它的投影，
    #    多经一道分支就多一处"两个判据可能不一致"的地方。
    retry_after: int | None = RETRY_AFTER_DEFAULT_S[code] if RETRY_AFTER_REQUIRED[code] else None

    resolved_suggestions = suggestions
    if not resolved_suggestions and REQUIRES_SUGGESTIONS[code]:
        resolved_suggestions = DEFAULT_SUGGESTIONS.get(code, ())

    return HttpErrorMapping(
        code=code,
        status=ERROR_HTTP_STATUS[code],
        retryable=RETRYABLE_BOOLEAN[code],
        retry_after_s=retry_after,
        message=message,
        detail=dict(detail or {}),
        suggestions=tuple(resolved_suggestions),
    )


#: 拒答 `reason` → 中性 `message`（占位文案，待 06 UI/UX 复核 —— 沿 `SHOP_LIMITED_NOTICE` 先例）。
#:
#: ⚠️ 表住在 L5 而不是 `graph/nodes/refuse_out.py` 的原因（T9 批次②实测）：
#: LangGraph `stream_mode="updates"` 只放行 `GraphState` schema 键 —— 出口节点往增量
#: 顶层写的 `message`/`suggestions` 在到达 `events.emissions_for_node` 之前就被丢弃
#: （实测 refuse_out 增量 = `{}`）。SSE 帧文案的唯一活通道是 `_extras` 侧信道（L5），
#: 故映射与 `map_code` 对称地住在 L5。文案约束不变：`message` 只陈述"没有可回答的数据"，
#: **不**透露库里有什么、不暗示"其实是权限问题"（存在性泄露，C-07 同一条红线）。
_REFUSAL_MESSAGES: Final[dict[str, str]] = {
    RefuseReason.NO_DATA_ASSET.value: "系统里没有能回答这个问题的数据，无法给出结果。",
    RefuseReason.OUT_OF_SCOPE.value: "这个问题涉及的数据范围超出你被授权的范围。",
    RefuseReason.PII_BLOCKED.value: "这个问题会返回受保护的字段，出于安全考虑不能作答。",
    RefuseReason.OPEN_ANALYSIS.value: "这类开放式分析不在本产品的回答范围内。",
}

#: `reason` → 改法建议（`no_data_asset` 的通用收窄建议；其余 reason 无更具体的改法）。
_REFUSAL_SUGGESTIONS: Final[dict[str, tuple[str, ...]]] = {
    RefuseReason.NO_DATA_ASSET.value: (
        "可以试着换一个更具体的问法（点明指标与时间范围）",
        "也可以先收窄维度，例如只看某个类目或某个渠道",
    ),
    RefuseReason.OPEN_ANALYSIS.value: (
        "可以把它拆成一个有明确口径的统计问题",
    ),
}

#: 兜底改法（`reason` 不在 `_REFUSAL_SUGGESTIONS` 时用，语义与 `no_data_asset` 档一致）。
_REFUSAL_DEFAULT_SUGGESTIONS: Final[tuple[str, ...]] = _REFUSAL_SUGGESTIONS[
    RefuseReason.NO_DATA_ASSET.value
]


def map_refuse(reason: str) -> dict[str, Any]:
    """拒答 `reason` → `refuse` 帧的 `message` / `suggestions[]`（与 `map_code` 对称的查表）。

    ⚠️ `suggestions` 的语义是"没数据时该怎么改问法"，与 `DEFAULT_SUGGESTIONS`
    （错误码侧的"原样重试必然失败时该怎么改"）**不是同一件事**，故不共用表。
    """
    return {
        "message": _REFUSAL_MESSAGES.get(
            reason, _REFUSAL_MESSAGES[RefuseReason.NO_DATA_ASSET.value]
        ),
        "suggestions": list(
            _REFUSAL_SUGGESTIONS.get(reason, _REFUSAL_DEFAULT_SUGGESTIONS)
        ),
    }


def map_rate_limited(bucket: RateLimitBucket, *, message: str = "") -> HttpErrorMapping:
    """限流专用：`Retry-After` 必须按**桶**取（附录 A §A.0.6）。

    ⚠️ 全局并发桶**没有** `Retry-After` 语义（07 §9.2 末行）→ 返回 `None`，符合 §14.4。
    """
    mapping = map_code(ErrorCode.RATE_LIMITED, message=message)
    return HttpErrorMapping(
        code=mapping.code,
        status=mapping.status,
        retryable=mapping.retryable,
        retry_after_s=RATE_LIMIT_BUCKET_RETRY_AFTER_S[bucket],
        message=mapping.message,
        detail={**mapping.detail, "bucket": bucket.value},
        suggestions=mapping.suggestions,
    )


def map_exception(exc: BaseException, *, message: str | None = None) -> HttpErrorMapping:
    """任意异常 → 响应事实。**这是异常离开进程的唯一出口。**

    ⚠️ 三条安全约束（都在这里一次性兜住，避免各端点各写一遍）：
    1. **数据库原始报错严禁回灌用户**（N-11）：未知异常一律降级为 `INTERNAL`，
       原文只进日志，不进 `message`/`detail`；
    2. `detail` 里**不得含明细数据**（N-12 精神：出站内容不含明细）；
    3. 未知异常必须带 `trace_id` 提示（07 §14.2 H15）。
    """
    if isinstance(exc, CommerceQLError):
        code_name = exc.default_code or ErrorCode.INTERNAL.value
        try:
            code = ErrorCode(code_name)
        except ValueError:
            # 领域异常声明了一个不在 A.11 表中的码 —— 这是契约违规（码表是唯一来源）
            code = ErrorCode.INTERNAL
        return map_code(
            code,
            message=message or exc.message,
            detail=exc.detail,
        )

    # 未捕获异常：不暴露内部信息（N-11）
    return map_code(
        ErrorCode.INTERNAL,
        message=message or "内部错误，请携带 trace_id 反馈",
    )


# ============================================================================
# 响应头（★ 全部头名的唯一来源）
# ============================================================================


#: ⚠️ `X-RateLimit-*` 四个头名在 `app/api/ratelimit.py` 定义（那里产出它们），
#: 本模块只 import —— 方向单向，避免"头名两处各写一份"。
#: `EXPOSE_HEADERS` 是 CORS 的 `Access-Control-Expose-Headers` 值（W5 RELAY §1.3）：
#: 跨源下不暴露它们，前端的 `headers.get()` 恒为 `null` → 限流指示器等于失效。
EXPOSE_HEADERS: tuple[str, ...] = (*RATE_LIMIT_HEADER_NAMES, HEADER_RETRY_AFTER)

#: 允许看到 `error.detail` 的角色（W5 RELAY §1.1 末列 + 07 §14.2 的收口）。
#:
#: ⚠️ **不在表内的角色一律不下发 `detail`**，且这是**服务端**的义务：
#: 前端 P0 无角色来源（无 `/me`，W5 RELAY §三 D-H），只能"一律不展示"；
#: 若后端照发，"不展示"只是渲染层的自觉 —— 而 `detail` 里可能有闸门规则号、
#: 解析器位置之类的诊断信息（N-11 的精神：诊断面只给能处置它的人）。
DETAIL_ROLES: frozenset[Role] = frozenset({Role.ANALYST, Role.PLATFORM_ADMIN})


def detail_allowed_for(role: Role | None) -> bool:
    """该角色是否允许收到 `detail`。`None`（未认证/无身份）一律 **False**。"""
    return role in DETAIL_ROLES


def rate_limit_headers(
    decision: RateLimitDecision | None = None,
    *,
    limit: int | None = None,
    remaining: int | None = None,
    reset_epoch_s: int | None = None,
) -> dict[str, str]:
    """`X-RateLimit-*` 四头。

    ⚠️ **`409 SESSION_CONFLICT` 不得带这四个头**（附录 A §A.0.6 末行的强制约定）：
    会话串行冲突不是配额事件，给了会让前端进入限流禁用态。故本函数**只在两处调用**：
    配额放行后的 `2xx` 响应、以及 `429` 本身。
    """
    if decision is None:
        return {}
    return RateLimitQuota(
        decision=decision, limit=limit, remaining=remaining, reset_epoch_s=reset_epoch_s
    ).headers()


def sse_response_headers(quota: RateLimitQuota | None = None) -> dict[str, str]:
    """SSE 响应头 = 反代必备头（`sse.SSE_HEADERS`）+ 逐桶限流四头。

    ⚠️ 是本模块而不是 `sse.py`：本模块的标题就是"**全部头名的唯一来源**"，
    而 `sse.py` 的职责是**编码帧**（它的 docstring 第一句）。两个 SSE 端点
    （`/query`、`/clarify`）都要这一组头，写在各自 router 里就是两处实现 ——
    漏一处表现是"某个端点的限流指示器不更新"，而前端只会静默忽略。
    ⚠️ `429` 的路径**不走这里**：那里由全局处理器用 `map_rate_limited` 取头（同一个来源链）。
    """
    from app.api.sse import SSE_HEADERS

    headers = dict(SSE_HEADERS)
    if quota is not None:
        headers.update(quota.headers())
    return headers


def server_time() -> str:
    """`server_time`（附录 A §A.0.1 的时间格式：ISO 8601 带时区偏移）。

    ⚠️ 与 `state_store._now_iso()` 是**同一个格式**、同一个语义（接入层墙钟）——
    这里再写一份是因为 `errors.py` 不能 import `state_store`（后者 import 了 Redis 客户端
    与 `cache.keys`，而错误响应在**任何**路径上都要能产出，包括还没装配运行时的启动期）。
    两者的一致性由 `tests/contract/test_api_error_contract.py` 的形状断言守住。
    """
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def error_body(
    mapping: HttpErrorMapping, *, trace_id: str | None, allow_detail: bool
) -> dict[str, Any]:
    """错误响应体（附录 A §A.0.4 的封套）。

    ⚠️ `detail` 的过滤**在这一处**完成（不是各端点各判一次）：
    本函数是"错误体长什么样"的唯一产出点，与 `ErrorEnvelope`（`api/dto/common.py`）同形。
    """
    return {
        "code": mapping.code.value,
        "message": mapping.message,
        "trace_id": trace_id,
        "detail": mapping.detail if (allow_detail and mapping.detail) else None,
        "suggestions": list(mapping.suggestions) if mapping.suggestions else None,
        "server_time": server_time(),
    }


def error_response(
    mapping: HttpErrorMapping,
    *,
    trace_id: str | None,
    allow_detail: bool,
    extra_headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """错误响应（**唯一的错误响应构造点**）。

    ⚠️ `mapping.validate()` 在构造时**必须**通过（`tests/contract/test_errors_contract.py` 已钉）：
    一条"码说可重试、头却没给"的响应会让前端倒计时与真实行为不符。
    """
    mapping.validate()
    headers = {**mapping.headers(), **(dict(extra_headers) if extra_headers else {})}
    return JSONResponse(
        status_code=mapping.status,
        content=error_body(mapping, trace_id=trace_id, allow_detail=allow_detail),
        headers=headers or None,
    )


# ============================================================================
# 全局异常处理器（★ 异常离开进程的唯一出口）
# ============================================================================


def install_exception_handlers(app: FastAPI) -> None:
    """把四类异常挂成全局处理器（`app/main.py` 的组装段调用一次）。

    覆盖范围与理由：

    | 异常 | 处理 | 理由 |
    |---|---|---|
    | `CommerceQLError` | `map_exception` | 领域异常的统一出口（`SESSION_CONFLICT` / `TASK_NOT_FOUND` / …） |
    | `RequestValidationError` | `INVALID_REQUEST` | FastAPI 默认产出的 `{"detail":[{"loc":…}]}` **不是**本项目封套 —— 前端按封套解析会拿到 `undefined.code` |
    | 其余 `Exception` | `INTERNAL` | N-11：原始报错不回灌；只留 `trace_id` 提示 |

    ⚠️ **限流头的两条非对称规则在这里落地**：
    · `429` 带 `X-RateLimit-*`（配额事件，四头齐全）；
    · `409 SESSION_CONFLICT` **不带**（`HttpErrorMapping.headers()` 只产 `Retry-After`，
      本函数不为它补配额头 —— 这正是"用错层的机制补救另一个层"要防的事）。

    ⚠️ **本函数不注册 `404` 兜底**：FastAPI 的 `HTTPException(404)` 由框架处理，
    而"路由不存在"不是本项目的领域错误码（附录 A §A.11 里的 404 全部是**资源**级）。
    """
    from app.api.ratelimit import RateLimitQuota
    from app.obs.logging import get_logger

    log = get_logger(__name__)

    def _role_of(request: Request) -> Role | None:
        """从**本次请求的身份**取角色（先 `request.state`，再 contextvar，见 `_identity_of`）。

        拿不到就返回 `None` → 不下发 `detail`（**安全缺省**：认证失败时本来也没有角色）。
        """
        context = _identity_of(request)
        return context.role if context is not None else None

    @app.exception_handler(CommerceQLError)
    async def _domain_error(request: Request, exc: CommerceQLError) -> JSONResponse:
        quota = getattr(exc, "quota", None)
        mapping = map_exception(exc)
        if isinstance(quota, RateLimitQuota):
            # 限流的 `Retry-After` **必须按桶取**（§A.0.6）：`map_rate_limited` 是唯一来源。
            mapping = map_rate_limited(quota.decision.bucket, message=mapping.message)
            extra = quota.headers()
        else:
            extra = {}
        log.warning(
            "api_error",
            code=mapping.code.value,
            status=mapping.status,
            path=request.url.path,
            error_type=type(exc).__name__,
        )
        return error_response(
            mapping,
            trace_id=_trace_id_of(request),
            allow_detail=detail_allowed_for(_role_of(request)),
            extra_headers=extra,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # ⚠️ `detail` 只放**字段路径**，不放用户输入回显（N-11 的精神）：
        # 把问题正文/参数值写回响应体既没有诊断价值（字段名就够了），
        # 又让"响应里出现用户输入"多一个面。截断到 10 条 —— 错误清单是给人看的，不是枚举面。
        paths = [".".join(str(part) for part in err.get("loc", ())) for err in exc.errors()]
        mapping = map_code(
            ErrorCode.INVALID_REQUEST,
            message="请求参数校验失败",
            detail={"fields": paths[:10]} if paths else {},
        )
        return error_response(
            mapping,
            trace_id=_trace_id_of(request),
            allow_detail=detail_allowed_for(_role_of(request)),
            extra_headers={},
        )

    @app.exception_handler(RedisError)
    async def _redis_unavailable(request: Request, exc: RedisError) -> JSONResponse:
        # Redis 超时/连不上 → `DB_UNAVAILABLE`(503 ✅) 而非裸 `INTERNAL`(500 ⭕)。
        # 覆盖四条边界（限流器 / 会话锁 / state_store / deps）——Redis 是 HARD 依赖
        # （`enums.Dependency.REDIS: HARD`），**fail-closed**：Redis 不可用即拒答、给 5s 重试，
        # 不让请求在失去限流/串行保护的状态下继续执行（w7 联调回执 #1）。
        # ⚠️ 只对**响应开始前**的边界生效：SSE 流已开始后（图内 state_store 写）不由本处理器接管，
        #    那条路径归 `runner` 的 in-stream error 帧（另一出口）。
        log.warning(
            "redis_unavailable",
            path=request.url.path,
            error_type=type(exc).__name__,
            extra_fact="fail-closed → 503 DB_UNAVAILABLE（Retry-After 5s，可原样重试）",
        )
        return error_response(
            map_code(ErrorCode.DB_UNAVAILABLE, message="服务暂时不可用，请稍后重试"),
            trace_id=_trace_id_of(request),
            allow_detail=detail_allowed_for(_role_of(request)),
            extra_headers={},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # ⚠️ 原始异常**只进日志**（N-11）：消息与 `detail` 都不带它。
        log.error(
            "unhandled_exception",
            path=request.url.path,
            error_type=type(exc).__name__,
            detail=str(exc)[:500],
        )
        return error_response(
            map_code(ErrorCode.INTERNAL, message="内部错误，请携带 trace_id 反馈"),
            trace_id=_trace_id_of(request),
            allow_detail=detail_allowed_for(_role_of(request)),
            extra_headers={},
        )


def _identity_of(request: Request) -> IdentityContext | None:
    """取本次请求的身份：**先 `request.state`，再 contextvar**。

    🔴 顺序不能反，理由是实测出来的：`trace_scope` 的 `finally` 在**异常处理器运行之前**
    就重置了 contextvar（端点的 `async with` 先退出，异常才冒泡到 `ExceptionMiddleware`）。
    只读 contextvar 的后果是**每一个领域错误的响应里 `trace_id` 都是 `null`**、
    且 `role` 一律取不到 ⇒ `detail` 对所有角色都不下发（07 §14.2 的收口被"静默全关"）。

    故身份必须同时落到 **ASGI scope 级**的 `request.state`（它随请求存活，
    异常处理器拿到的是同一个 `scope`）。contextvar 保留为兜底：它服务日志（`obs`），
    在**未**经端点（例如中间件层）产生的错误上仍有值。
    """
    remembered = getattr(request.state, IDENTITY_STATE_KEY, None)
    if isinstance(remembered, IdentityContext):
        return remembered
    from app.auth.context import identity_or_none

    return identity_or_none()


def _trace_id_of(request: Request) -> str | None:
    """从本次请求的身份取 `trace_id`（没有则 `None`）。

    ⚠️ 不从 `X-Trace-Id` 请求头取：那是**客户端可伪造**的输入，
    而 `trace_id` 是 07 §15.2 的 trace 起点（**服务端生成**）。
    回显一个客户端给的值会让"按 trace_id 查日志"查出攻击者构造的误导关联。
    """
    ctx = _identity_of(request)
    return ctx.trace_id if ctx is not None else None
