"""内部异常基类 —— **不含 HTTP 语义**。

归属窗口：W0（docs/08 §4.1）。与 `app/api/errors.py` 的分工是**硬边界**：

| 本文件 | `app/api/errors.py` |
|---|---|
| 领域语义（"审计写不进去"、"语义包没通过校验"） | HTTP 状态码 / `retryable` / `Retry-After` / 用户文案 |
| 可跨层抛出、可被任意模块 import | **唯一的异常 → 错误码映射点**（附录 A §A.11 的 28 码） |

为什么必须拆开：把 HTTP 语义混进领域异常，会让 L0–L2 的确定性模块被迫知道 HTTP 协议细节，
而 N-01 要求这些模块**离线可测**（不连网、不起服务）。异常里带 `HTTPException` 就等于把
Web 框架拖进确定层。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AuditWriteFailed",
    "CommerceQLError",
    "ConfigError",
    "ContractViolationError",
    "DependencyUnavailableError",
    "SemanticBundleError",
    "SessionLockConflict",
]


class CommerceQLError(Exception):
    """本系统全部业务异常的基类。

    ⚠️ 约定：`code` 只是**领域侧的默认建议码**，最终 HTTP 状态与 `retryable`
    **一律**由 `app/api/errors.py` 依据 `app.core.enums.ERROR_HTTP_STATUS` /
    `ERROR_RETRY_TIER` 查表决定（C-09：`retryable=false` **不得**带 `Retry-After`）。

    ⚠️ `message` 会进用户可见响应：**严禁**把数据库原始报错塞进来（N-11）。
    """

    #: 领域默认码（`app.core.enums.ErrorCode` 的成员名字符串）；`None` = 由映射层兜底为 `INTERNAL`。
    default_code: str | None = None

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        #: 结构化补充信息（进 `error.detail`）。**不得含明细数据/库内文本**（N-11 / N-12）。
        self.detail: dict[str, Any] = dict(detail or {})

    def __str__(self) -> str:  # pragma: no cover - 平凡实现
        return self.message if not self.detail else f"{self.message} | detail={self.detail}"


class ConfigError(CommerceQLError):
    """启动期配置缺失/非法 → **拒绝启动**（fail fast，N-15 / 07 §18.4）。

    ⚠️ 宁可起不来，也不要带着错配置跑起来 —— 错配置的表现是"部分功能静默失效"，
    排查成本远高于启动失败。
    """

    default_code = "INTERNAL"


class SemanticBundleError(CommerceQLError):
    """语义包未通过 07 §6.1 五步校验 → **拒绝启动**。

    语义包是硬依赖里最硬的一个：**无口径 = 不可用，不是降级**（07 §5.1「越准越危险」）。
    """

    default_code = "INTERNAL"


class SessionLockConflict(CommerceQLError):
    """同一 `session_id` 已有进行中的查询，等待超时（FR-10.5 / ADR-13）。

    ⚠️ 落地约定（附录 A §A.11 补充约定）：
    - 映射为 **`409 SESSION_CONFLICT`** + `Retry-After: 3`；
    - **绝不复用 `429`**（`429` 是配额语义，本码是**状态冲突**语义）；
    - **不返回** `X-RateLimit-*`；
    - 前端按"稍后自动重试"处理，**不得**进入限流禁用态。
    """

    default_code = "SESSION_CONFLICT"


class AuditWriteFailed(CommerceQLError):
    """审计写入失败 → **fail-closed**（N-09 / ADR-14）。

    ⚠️ 两段式的处置**不同**，实现时不得一刀切：
    - **段 1（`audit_pre`）失败** ⇒ 不得下发 `data`；映射 `error(INTERNAL)` + **P0 告警**；
      **不得**临时关闭 fail-closed（那会破坏 NFR-3.4）；
    - **段 2（`audit_supp`）失败** ⇒ **不阻断**（结果已下发），只告警（07 §14.2 G2）。
    """

    default_code = "INTERNAL"


class DependencyUnavailableError(CommerceQLError):
    """外部依赖不可用。

    ⚠️ `kind` 决定行为，**不可互换**（N-21）：
    - `hard` → 摘流量（`/healthz/ready` 503）；
    - `soft` → **降级**（`200 + degraded` + 发 `degraded` 事件），**不得静默降级**。
    """

    default_code = "DB_UNAVAILABLE"

    def __init__(
        self,
        message: str,
        *,
        dependency: str,
        kind: str,  # "hard" | "soft"（值域见 app.core.enums.DependencyKind）
        detail: dict[str, Any] | None = None,
    ) -> None:
        merged = {"dependency": dependency, "kind": kind, **(detail or {})}
        super().__init__(message, detail=merged)
        self.dependency = dependency
        self.kind = kind


class ContractViolationError(CommerceQLError):
    """契约被违反（如事件序列矛盾、枚举非法值、快照漂移）。

    ⚠️ 这条**不应在正常流量里出现**：出现即说明上游窗口改了契约却没同步。
    比照 `ui_contract_violation` 的处理 —— **任何非零值都是 P0**（07 §14.5）。
    """

    default_code = "INTERNAL"
