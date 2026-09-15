"""结构化日志（JSON Lines，**字段即契约**）—— 07 §15.1。

归属窗口：W0 立骨架 → W7 补全指标与告警（docs/08 §4.1：`app/obs/**` = W0 → W7）。

为什么日志字段算"契约"而不是"实现细节"：
告警规则、看板、故障复盘的 grep 语句全都建立在字段名上。字段名一漂移，
**告警不会报错，只会不再触发** —— 这是最坏的一类失败：系统看起来一切正常。

⚠️ 本文件当前只提供"装配 + 脱敏"两件事；完整字段组与标签基数上限待 W7 回填
（清单见 `app/obs/schema.py` 的 `PENDING_FIELD_GROUPS_OWNER_W7`）。
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any, Final

import structlog

from app.obs.schema import LogField

__all__ = ["REDACTED_KEYS", "configure_logging", "get_logger"]

#: 必须脱敏/剔除的字段名（07 §13.1 第 3 条：**禁止把令牌原文写日志**，PRD §11.5 有真实事故）。
#: 除认证头外还包含口令与密钥类字段 —— 它们更常见的泄漏路径是"配置对象被整体 dump 进日志"。
REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "password",
        "passwd",
        "secret",
        "api_key",
        "deepseek_api_key",
        "jwt",
        "private_key",
        "db_password",
    }
)


def _redact(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """脱敏处理器：键名命中即替换为 `***`（**大小写不敏感**）。

    只看键名、不看值 —— 因为"值像不像密钥"是不可靠的判断，而键名是可控的。
    """
    for key in list(event_dict.keys()):
        if key.lower() in REDACTED_KEYS:
            event_dict[key] = "***"
    return event_dict


def _add_service_identity(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """补齐链路字段的位置（阶段 0 只保证 `trace_id` 来源唯一）。

    ⚠️ 阶段 0 的 `task_id` / `session_id` 来自 `app.obs.trace` 的 contextvar；
    这里**不生成**任何 id，避免出现"日志里的 task_id 与响应里的 task_id 不是同一个"。
    """
    from app.obs.trace import current_ids  # 延迟 import：避免 obs 内部循环

    ids = current_ids()
    if ids.trace_id and LogField.TRACE_ID not in event_dict:
        event_dict[LogField.TRACE_ID] = ids.trace_id
    if ids.task_id and LogField.TASK_ID not in event_dict:
        event_dict[LogField.TASK_ID] = ids.task_id
    if ids.session_id and LogField.SESSION_ID not in event_dict:
        event_dict[LogField.SESSION_ID] = ids.session_id
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """进程级装配（在 `create_app()` 之前调用一次）。

    ⚠️ 输出必须是 **JSON Lines**：非结构化日志无法做"按 `rule_id` 统计闸门拒绝率"这类统计，
    而 07 §14.5 的归因指标全都依赖它。
    """
    logging.basicConfig(format="%(message)s", level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),  # 本地时区，便于对账
            _add_service_identity,
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """取 logger。**所有模块都用它，不直接用 `logging.getLogger`** ——

    否则那条日志会绕过脱敏与链路字段，成为唯一一条"看不出来是谁打的"日志。
    """
    return structlog.get_logger(name)
