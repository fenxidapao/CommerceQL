"""SSE 编码器 —— **唯一产出 `event:` / `data:` 帧的地方**（07 §3.2、§5.6）。

归属窗口：W0 定骨架 → W4 接线（docs/08 §4.1）。

它消灭的漂移是：**帧格式（尤其是 `terminal`）在多处拼接**。
历史病害的形态很具体 —— 有的出口路径记得带 `terminal: true`，有的忘了，
于是前端在"澄清"路径上永远转圈。**前端只认 `data.terminal` 这一个判据**（附录 A §A.1.4），
所以这个字段的单点产出比帧格式本身更重要。

⚠️ 本文件只负责**编码**。事件何时发、是否已发过终止事件，属 `app/graph/events.py`（W4）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from app.core.enums import SSE_TERMINAL_EVENTS, SseEvent, Stage
from app.core.errors import ContractViolationError

__all__ = ["HEARTBEAT_INTERVAL_S", "SSE_HEADERS", "SSE_MEDIA_TYPE", "encode", "encode_heartbeat"]


#: 附录 A §A.1.1：`200 OK` + `text/event-stream`
SSE_MEDIA_TYPE: Final[str] = "text/event-stream"

#: 反代/浏览器侧的必备头。
#: ⚠️ `X-Accel-Buffering: no` 是**必须的**：Nginx 默认缓冲会让 SSE 攒够一整块才吐，
#: 表现是"进度条不动、最后一次性全出来" —— 这类问题在本地不缓冲、上 Nginx 才复现。
SSE_HEADERS: Final[Mapping[str, str]] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

#: 心跳间隔（附录 A §A.1.2：每 15 秒一次）。
#: 存在的理由：反向代理/负载均衡各有空闲超时，静默连接会被单方面切断，
#: 而"连接被切断"与"这轮结束了"在前端看起来是同一件事（都只是流停了）——
#: 所以必须有心跳把两者区分开。A.1.4 也据此规定：90s 内收不到**任何**事件（含心跳），
#: 客户端才应判定连接异常。
HEARTBEAT_INTERVAL_S: Final[int] = 15

#: 合法 stage 值（**只允许 6 个**，07 §14.3 约束 8）。历史病害 `data_ready` / `complete` 即在此被拦。
_LEGAL_STAGES: Final[frozenset[str]] = frozenset(s.value for s in Stage)


def encode(event: SseEvent, data: Mapping[str, Any]) -> bytes:
    """把一个事件编码成 SSE 帧。

    **三条契约（违反时抛错，而不是静默兼容）**：

    1. 每个 `data` **必须带 `terminal` 布尔**（N-08）。本函数对普通事件补齐缺省 `False`；
       但对**终止事件**（`complete` / `clarify` / `refuse` / `error`）缺 `terminal: true` 直接抛错 ——
       忘了它就是"前端永远在加载中"，静默兼容等于把 bug 藏起来。
    2. **非终止事件不得声称 `terminal: true`**。`degraded` 尤其典型：
       它的语义是"发生了降级"，不是"这一轮结束了"（附录 A §A.1.2）。
       若把它标成终止，转异步路径会在 `complete` 之前被前端关流。
    3. `stage` 事件的 `stage` 值必须是 `Stage` 的 6 个之一（非法值直接抛错）。

    ⚠️ `data` 里**不得**出现 `node` 之类的内部名（06 D2 红线：`node` 只进日志）。
    """
    payload: dict[str, Any] = dict(data)
    terminal_declared = payload.get("terminal")

    if event in SSE_TERMINAL_EVENTS:
        if terminal_declared is not True:
            raise ContractViolationError(
                f"终止事件 {event.value} 必须携带 terminal=true（N-08）—— "
                f"缺失或为 {terminal_declared!r} 都会让前端停在加载态"
            )
    else:
        if terminal_declared is True:
            raise ContractViolationError(
                f"非终止事件 {event.value} 不得声明 terminal=true —— "
                f"唯一判据是 data.terminal（附录 A §A.1.4）；"
                f"degraded 更明确：它只表示发生了降级，不代表流结束"
            )
        payload["terminal"] = False

    if event is SseEvent.STAGE:
        stage = payload.get("stage")
        if not isinstance(stage, str) or stage not in _LEGAL_STAGES:
            raise ContractViolationError(
                f"stage 事件携带非法 stage 值 {stage!r} —— 合法值只有 6 个"
                f"（07 §14.3 约束 8）：{sorted(_LEGAL_STAGES)}"
            )

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.value}\ndata: {body}\n\n".encode()


def encode_heartbeat() -> bytes:
    """心跳帧（`terminal: false`）。

    用 `encode()` 走同一条路径，而不是另拼一个字符串 ——
    "唯一产出点"的价值就在于**没有第二条路径**可以漂移。
    """
    return encode(SseEvent.HEARTBEAT, {})
