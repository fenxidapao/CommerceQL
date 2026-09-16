"""认证链路的领域异常（07 §13.1 各步的失败码）。

归属窗口：W1B。

⚠️ 为什么单独一个文件、而不是塞进 `app/core/errors.py`：
`core/**` 归 W0（`docs/08 §4.1`），且那里面放的是**跨层通用**的领域异常。
认证的两个码（`AUTH_FAILED` / `TOKEN_REVOKED`）只被认证链路抛出，
放在 `auth/` 内可以让"谁能抛 401"这件事在目录结构上就可见。

⚠️ **铁律（PRD §11.5 有真实事故）**：本模块抛出的异常消息**绝不包含令牌原文**，
也不包含任何 claim 的**值**。只允许出现 claim 的**名字**与失败原因。
理由很直接：异常会被 `structlog` 序列化进日志，也会在 `error.detail` 里进响应体。
`tests/unit/test_auth_chain.py::test_failures_never_leak_the_token` 会守住这条。
"""

from __future__ import annotations

from app.core.errors import CommerceQLError

__all__ = ["AuthError", "TokenRevokedError"]


class AuthError(CommerceQLError):
    """07 §13.1 第 1/2/3/5 步的失败 —— 一律 `401 AUTH_FAILED`。

    ⚠️ 四步**刻意用同一个码**、同一段文案：区分"签名错"与"缺少 claim"会把
    令牌探测变成信息泄露（攻击者可以据此判断自己离成功有多近）。
    需要归因时看**日志**（那里有 `auth_failure_step`），不看响应。
    """

    default_code = "AUTH_FAILED"

    def __init__(self, message: str, *, step: int, reason: str) -> None:
        # `step` / `reason` 进 `detail`：它们是**服务端**可观测字段，
        # 不含用户数据；`app/api/errors.py` 决定是否透出（默认不透出）。
        super().__init__(message, detail={"auth_failure_step": step, "auth_failure_reason": reason})
        self.step = step
        self.reason = reason


class TokenRevokedError(CommerceQLError):
    """07 §13.1 第 4 步的失败 —— `401 TOKEN_REVOKED`。

    ⚠️ 与 `AUTH_FAILED` **必须分开**：`TOKEN_REVOKED` 表示"令牌本身是合法的，
    只是被主动吊销了"（登出 / 改密 / 风控）。前端对两者的处理不同：
    前者应引导重新登录并**清空本地令牌**，后者还需提示"该会话已被登出"。
    """

    default_code = "TOKEN_REVOKED"

    def __init__(self, message: str = "令牌已被吊销，请重新登录") -> None:
        super().__init__(message, detail={"auth_failure_step": 4})
        self.step = 4
