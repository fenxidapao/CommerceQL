"""异常 → 错误码的**唯一映射点**（附录 A §A.11 / 07 §14.4）。

归属窗口：W0 定接口骨架 → W4 实现端点时使用（docs/08 §4.1）。

它是"唯一入口"文件里的一个（07 §3.2）：消灭的是**同一错误在不同端点映射成不同码**。
这类缺陷在联调期表现为"前端有的页面提示重试、有的页面静默失败"，而根因只是两处各写了一遍映射。

本文件**只做查表**，不做业务判定。四件事一张表答完：
`code` → HTTP 状态 → `retryable`(布尔) → 是否带 `Retry-After` / 是否必须给 `suggestions[]`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
)
from app.core.errors import CommerceQLError

__all__ = ["HEADER_RETRY_AFTER", "HttpErrorMapping", "map_code", "map_exception"]


HEADER_RETRY_AFTER = "Retry-After"


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
