"""认证链路 7 步中的第 6–7 步：不可变 `IdentityContext` + contextvar（07 §13.1）。

归属窗口：W1B。

**第 6 步：构造不可变上下文。**
`IdentityContext`（`app/core/contracts.py`，W0 冻结的 L0 值对象）是 `frozen=True, slots=True` ——
这意味着"进图之后不可修改"不是纪律，而是**类型事实**：任何 `ctx.role = ...` 都会抛
`FrozenInstanceError`。这正是 07 §5.2 组 1 那句"由 `trusted_context` 产出，之后只读"的落点。

**第 7 步：contextvar。**
目的只有一个：让 `obs`（日志 / 指标 / trace）能在**任何深度**取到身份，
而不必把 `ctx` 逐层透传（透传的必然结果是某个中间层为了省事用了可变的全局变量）。

⚠️ **contextvar 不是授权依据**。授权一律用**显式传入**的 `IdentityContext`
（`guard` / `exec` / `cache` 都从参数拿，不从 contextvar 拿）。理由：
contextvar 在 `asyncio.create_task` 里会被复制、在后台任务里会"继承"一个**过期的**身份 ——
把它当授权依据，等于让"谁在跑"取决于任务是怎么被创建的。

⚠️ **PII 约束**（N-12 / `obs/schema.py` 的"身份"组）：
`tenant_id` / `user_id` **禁止出站到 LLM**；进日志是允许的（审计要求留存），
但**进 `PROMPT` 是禁止的** —— 该约束在 `app/graph/state.py` 的字段权限标注里落实。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Final

from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext
from app.obs.schema import LogField

__all__ = [
    "IDENTITY_CONTEXTVAR_NAME",
    "bind_identity",
    "build_identity",
    "current_identity",
    "identity_or_none",
    "identity_obs_fields",
    "reset_identity",
]

#: contextvar 名（出现在 `contextvars` 的调试输出里，故起一个可搜索的名字）。
IDENTITY_CONTEXTVAR_NAME: Final[str] = "commerceql.identity"

_CURRENT: ContextVar[IdentityContext | None] = ContextVar(IDENTITY_CONTEXTVAR_NAME, default=None)


def build_identity(
    token: VerifiedToken,
    *,
    trace_id: str,
    task_id: str,
    session_id: str,
) -> IdentityContext:
    """第 6 步：`VerifiedToken` + **服务端生成**的运行标识 → `IdentityContext`。

    ⚠️ 三个运行标识是**入参而不是从令牌取**：
    `trace_id` 由接入层生成（07 §15.2 的 trace 起点）、`task_id` 由服务端分配
    （ADR-03：澄清后的 run 是**新 `task_id`**）、`session_id` 来自路径参数。
    从令牌取任何一个都会让"同一次请求的标识"变成"用户可控"。

    ⚠️ `role` / `shop_ids` / `tenant_id` **一律来自 `token`**（禁令 1、2）——
    本函数的签名里没有第二个可以传身份的地方，这是有意的：
    "多加一个可选参数"就是越权的入口。
    """
    for name, value in (("trace_id", trace_id), ("task_id", task_id), ("session_id", session_id)):
        if not value:
            raise ValueError(
                f"`{name}` 必须由服务端生成且非空（07 §13.1 第 6 步）—— "
                f"缺了它会让审计与 trace 无法关联"
            )
    return IdentityContext(
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        tenant_id=token.tenant_id,
        user_id=token.subject,
        role=token.role,
        scope_claims=token.scope_claims,
        shop_ids=token.shop_ids,
    )


def bind_identity(ctx: IdentityContext) -> Token[IdentityContext | None]:
    """第 7 步：把身份写进 contextvar。

    ⚠️ 返回 `Token` 并要求调用方在 `finally` 里 `reset_identity(token)` ——
    这是 `contextvars` 的**撤销机制**。不复位在"长驻单例 + 复用 context"的场景
    （如某些测试夹具、以及把请求塞进同一个 task 的批处理）会产生**身份串台**：
    下一个请求看到上一个租户的 `tenant_id`。那是最难查的一类跨租户泄露。
    """
    return _CURRENT.set(ctx)


def reset_identity(token: Token[IdentityContext | None]) -> None:
    """撤销 `bind_identity`（`finally` 里必调）。"""
    _CURRENT.reset(token)


def identity_or_none() -> IdentityContext | None:
    """取当前身份，**未绑定返回 `None`**。

    用于 `obs` 这类"有则记、无则跳过"的场景（例如启动期的日志）。
    """
    return _CURRENT.get()


def current_identity() -> IdentityContext:
    """取当前身份，**未绑定即抛错**。

    ⚠️ 刻意不返回一个"匿名上下文"兜底：那会让"忘了绑定身份"变成
    "以某个默认身份跑完全程"，而默认身份必然比真实身份**更宽**（否则它没法通用）。
    """
    ctx = _CURRENT.get()
    if ctx is None:
        raise RuntimeError(
            f"未绑定身份（contextvar `{IDENTITY_CONTEXTVAR_NAME}` 为空）—— "
            f"认证链路的第 7 步（`bind_identity`）没有执行。"
            f"⚠️ 不得用默认身份兜底：那会把'忘了绑定'变成'以更宽的身份跑完'。"
        )
    return ctx


def identity_obs_fields(ctx: IdentityContext) -> dict[str, str]:
    """第 7 步的"供 `obs` 记录"具体是哪几个字段（07 §13.1 第 7 步逐字：4 个）。

    ⚠️ 字段名取自 `app/obs/schema.py`（**唯一定义处**），不在这里写字符串字面量 ——
    否则日志与看板会因为一个 `tenantId` / `tenant_id` 的差异而对不上号，
    而那种错误既不报错也不影响功能，只是永远排不了障。
    """
    return {
        LogField.TRACE_ID.value: ctx.trace_id,
        LogField.TENANT_ID.value: ctx.tenant_id,
        LogField.USER_ID.value: ctx.user_id,
        LogField.ROLE.value: str(ctx.role),
    }
