"""Trace 传播（07 §15.2）。

归属窗口：W0 立骨架 → W7 补全（docs/08 §4.1）。

`trace_id` 的存在意义很具体：SSE 场景下"一次用户提问"会横跨 api → graph → 多个节点 →
LLM 出站，而线上排查时手上通常只有用户截图里的一个 `trace_id`（错误响应会带它，07 §14.2 H15）。
**没有全链路贯通的 trace_id，`.log` 里那一堆记录就只是一堆记录。**

用 contextvar 而不是把 id 层层传参：SSE + 异步任务的调用链里，参数会穿过十几个未使用它的函数。
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final

__all__ = ["TraceIds", "bind_ids", "current_ids", "new_id", "reset_ids"]

_CTX: ContextVar[TraceIds | None] = ContextVar("commerceql_trace", default=None)

#: id 前缀。前缀不是装饰 —— 它让"日志里贴出来的那串 id 是 task 还是 session"无需再去查表。
_PREFIX: Final[dict[str, str]] = {"trace": "tr", "task": "tk", "session": "ss", "clarify": "cf"}


@dataclass(frozen=True, slots=True)
class TraceIds:
    """当前请求的链路标识。**不可变**，绑定后不再修改。"""

    trace_id: str
    task_id: str | None = None
    session_id: str | None = None


def new_id(kind: str) -> str:
    """生成 `{prefix}_{30 位十六进制}` 形态的 id。

    用 uuid4 而非自增：自增 id 会**泄露业务量**（一个外部用户能通过 id 大小推断日请求量），
    且在多实例部署下需要额外的集中式分配。
    """
    prefix = _PREFIX.get(kind, kind[:2] or "id")
    return f"{prefix}_{uuid.uuid4().hex}"


def bind_ids(ids: TraceIds) -> object:
    """绑定到当前上下文（返回 token，供 `reset_ids` 还原）。"""
    return _CTX.set(ids)


def reset_ids(token: object) -> None:
    """还原（在 `finally` 里调用 —— SSE 连接释放路径必须清干净，否则会串到下个请求）。"""
    _CTX.reset(token)  # type: ignore[arg-type]


def current_ids() -> TraceIds:
    """读取当前上下文；未绑定时返回空 id（不抛错）。

    为什么不抛错：日志处理器会调用它。日志绝不应该因为"契约没绑好"而把主流程打挂 ——
    那会把一个可观测性缺陷升级成一次可用性故障。
    """
    return _CTX.get() or TraceIds(trace_id="")
