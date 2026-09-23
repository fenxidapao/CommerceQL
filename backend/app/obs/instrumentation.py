"""HTTP / SSE 观测中间件与在途流登记表 —— 07 §15.3 的采集点、§18.3 停机第 2~3 步的执行体。

归属窗口：W7（docs/08 §4.1：`app/obs/**` 的指标与采样器部分）

## 为什么采集点放在中间件（而不是散进各业务模块）
`app/obs` 在 **L1**，按 `.importlinter` R-DEP-1 的实测语义（高层可依赖低层，反过来即违规）
**不得 import L5 的 `app.api`**。而本模块想用的两件事实恰好住在 L5：SSE 编码器 `sse.encode`
与错误码映射 `api/errors.map_code`。解法不是破例 import，而是**由组装根 `app/main.py`
注入**（本文件只声明"需要什么"）。第二个好处：本模块可脱离 FastAPI 单测 ——
直接喂 ASGI 消息序列即可，不起服务。

## 三条不可让步的性质
1. **观测不得改变业务结果。** 任何计数/解析异常一律吞掉并记一条日志，绝不冒泡成 500。
   唯一例外是停机的"中止这条流"（`_DrainAbort`）—— 那是显式指令，不是观测故障。
2. **帧级契约判定是独立复算**，不复用 `EventRecorder` 的守卫。07 §14.3 的
   `ui_contract_violation` 断言的是"**到用户手上那一刻**"的帧序列，而 `EventRecorder`
   判的是"入队那一刻"。两处独立才可能抓到"入队后被别的路径补发/改写"的漂移；
   共用一份实现则永远一致，也就永远抓不到。
3. **停机不得伪造取消语义。** drain 的做法是"补一帧终止 `error` + 中止本次 ASGI 调用"，
   **刻意不写** §A.3 的取消标志：那条路径会把"服务端重启"记成"用户取消"
   （`cancel_task` 会把 `status` 落成 `cancelled`，审计 `outcome` 随之失真）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.enums import (
    SSE_TERMINAL_EVENTS,
    ActionTaken,
    ClarifyReason,
    DegradedReason,
    Outcome,
    RefuseReason,
    Stage,
)
from app.obs import metrics
from app.obs.logging import get_logger

__all__ = [
    "DRAIN_MESSAGE",
    "DRAIN_TIMEOUT_S",
    "ENDPOINT_LABEL_CAP",
    "InFlightRegistry",
    "InFlightStream",
    "ObservingMiddleware",
    "REGISTRY",
    "normalize_endpoint",
]

_log = get_logger(__name__)

#: 终止事件的 `event:` 名（取自 `core.enums`，不在这里重抄字面量）。
_TERMINAL_EVENTS: Final[frozenset[str]] = frozenset(e.value for e in SSE_TERMINAL_EVENTS)

#: 帧分隔符（`sse.encode` 产出 `event: …\ndata: …\n\n`，逐字对齐；一致性由契约测试钉住）。
_FRAME_SEP: Final[bytes] = b"\n\n"

#: 内容类型子串。`app.api.sse.SSE_MEDIA_TYPE` 的值 —— 此处不 import L5，
#: 故写常量，并在 `tests/contract/` 里断言两者相等（漂移会在 CI 炸，而不是在线上表现为"没观测"）。
_SSE_MEDIA: Final[str] = "text/event-stream"

#: 终止事件 → `query_outcome_total{outcome}`（§14.5 结果分布）。
#: ⚠️ `degraded` **不在**此表：它不是终止事件（§A.1.2），计数走 `degraded_total`。
_TERMINAL_OUTCOME: Final[Mapping[str, Outcome]] = {
    "complete": Outcome.SUCCESS,
    "clarify": Outcome.CLARIFY,
    "refuse": Outcome.REFUSE,
    "error": Outcome.FAILED,
}

#: 闸门拒绝码 → 闸门编号。这是 `app/graph/nodes/error_out.py::_GATE_CODE` 的**镜像**：
#: L1 不得 import L4（R-DEP-1），所以抄一份，并由
#: `tests/contract/test_obs_frame_format.py` 断言两边逐项相等（漂移在 CI 炸，不在线上沉默）。
#: ⚠️ 为什么必须有这张表：`refuse` 帧**不可能**承载闸门事实（C-12 + `RefuseReason` 四值里
#:    没有闸门项，06 §7.2 明令"闸门拒绝不得渲染成拒答卡"），闸门拒绝在帧面上**只有**
#:    `error` + 这三个码这一种形态。少了这张表，`gate_reject_total` 就是一个恒 0 的族，


#: 停机时下发给客户端的文案（07 §18.3 第 3 步原文给定的字符串）。
DRAIN_MESSAGE: Final[str] = "服务重启中，请重试"

#: drain 等待预算（§18.3 第 2 步"≤30s"）。
#: ⚠️ 必须**小于** Compose 的 `stop_grace_period`（40s）—— 预算先到期意味着我们还来得及
#: 发终止帧；`stop_grace_period` 先到期意味着 SIGKILL，那正是本步要避免的"静默断连"。
DRAIN_TIMEOUT_S: Final[float] = 30.0

_SELF_SCRAPE_PREFIXES: Final[tuple[str, ...]] = ("/api/v1/healthz", "/api/v1/metrics")


# ============================================================================
# endpoint 标签的有界化（§15.3：endpoint ≤20）
# ============================================================================

#: 与 `metrics.BOUNDED_ALLOWED_LABELS["endpoint"]` 同值（两处一致由测试钉）。
ENDPOINT_LABEL_CAP: Final[int] = 20

#: 超出上限的路径并入此桶。真实路径不可能叫这个名（端点全在 `/api/v1/` 下）。
UNMATCHED_ENDPOINT: Final[str] = "unmatched"

_ID_SEGMENT: Final[re.Pattern[str]] = re.compile(
    r"^(?:"
    r"\d+"  # 纯数字段
    r"|[0-9a-fA-F-]{16,}"  # hex / uuid 尾段
    r"|[a-z]{2,4}_[0-9A-Za-z_-]{10,})$"  # `app/obs/trace.py` 的 `前缀_id` 形态（tk_/ss_/tr_/fb_…）
)


def normalize_endpoint(path: str) -> str:
    """把请求路径压成**低基数**标签值：`/api/v1/query/tk_01ABC` → `/api/v1/query/{id}`。

    不做这件事，`endpoint` 的基数 = 任务数（无界），§15.3 的 ≤20 当场失效；
    Prometheus 侧的表现是时间序列数爆炸 —— "观测层自己把系统打挂"的经典形态。
    """
    stripped = path.split("?", 1)[0].rstrip("/") or "/"
    return "/".join("{id}" if _ID_SEGMENT.match(seg) else seg for seg in stripped.split("/"))


class _EndpointLabels:
    """endpoint 取值的**硬上限**：超出后并入 `unmatched`，不再新增序列。

    ⚠️ 这里与指标层（`metrics.BOUNDED_ALLOWED_LABELS["endpoint"]=20`）是**两道闸门**，
    而默认上限取 `cap - 1`：`unmatched` 自己也要占一个位置。否则中间件放满 20 个真实
    路径后，第 21 个换成 `unmatched` 时会被指标层再丢一次 —— 溢出从"看得见"变成"消失了"。
    """

    __slots__ = ("_cap", "_known")

    def __init__(self, cap: int = ENDPOINT_LABEL_CAP - 1) -> None:
        self._cap = cap
        self._known: dict[str, str] = {}

    def resolve(self, normalized: str) -> str:
        if normalized in self._known:
            return normalized
        if len(self._known) >= self._cap:
            return UNMATCHED_ENDPOINT
        self._known[normalized] = normalized
        return normalized


# ============================================================================
# 在途流登记表（§18.3 第 2~3 步的对象）
# ============================================================================


@dataclass(slots=True)
class InFlightStream:
    """一条**正在进行**的 SSE 流。生命周期由 `ObservingMiddleware` 管，注册表只做索引。"""

    stream_id: int
    endpoint: str
    started_monotonic: float
    task_id: str | None = None  # 由 `ack` 帧回填（不 import L5 时唯一可靠的来源）
    session_id: str | None = None
    frames: int = 0
    seen_terminal: bool = False
    terminal_event: str | None = None
    terminal_monotonic: float | None = None
    aborted_for_drain: bool = False
    done: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def age_s(self) -> float:
        return max(0.0, time.monotonic() - self.started_monotonic)


@dataclass(frozen=True, slots=True)
class DrainReport:
    """一次 drain 的事实（停机日志与 runbook 据此下结论，不靠"看起来没流量了"）。"""

    inflight_at_start: int
    finished_task_ids: tuple[str, ...]
    still_inflight_task_ids: tuple[str, ...]
    waited_s: float
    timed_out: bool

    @property
    def clean(self) -> bool:
        return not self.timed_out and not self.still_inflight_task_ids


class InFlightRegistry:
    """在途 SSE 流的索引 + drain 协调器。

    ⚠️ 为什么需要这张表：§18.3 第 2 步"drain 在途 SSE ≤30s"要求**枚举**在途流，
    而现有链路里没有任何一处持有"当前有哪些流"（`SseRunner` 每请求一份、请求结束即弃）。
    为什么不复用 `RedisStateStore` 的任务状态当索引：① 它是投影不是真相；
    ② 它没有"本进程正在服务这条流"的语义（多副本下会把别家进程的流也算进来）；
    ③ 遍历它需要 `SCAN`（07 §18 明令禁止在请求路径上用的用法）。
    """

    __slots__ = ("_draining", "_endpoints", "_lock", "_next_id", "_streams")

    def __init__(self, endpoint_cap: int | None = None) -> None:
        self._lock = threading.Lock()
        self._streams: dict[int, InFlightStream] = {}
        self._next_id = 0
        self._draining = False
        self._endpoints = _EndpointLabels() if endpoint_cap is None else _EndpointLabels(endpoint_cap)

    def endpoint_for(self, path: str) -> str:
        return self._endpoints.resolve(normalize_endpoint(path))

    # -- 登记 ---------------------------------------------------------------

    def register(self, endpoint: str) -> InFlightStream:
        with self._lock:
            self._next_id += 1
            stream = InFlightStream(
                stream_id=self._next_id, endpoint=endpoint, started_monotonic=time.monotonic()
            )
            self._streams[stream.stream_id] = stream
        return stream

    def complete(self, stream: InFlightStream) -> None:
        with self._lock:
            self._streams.pop(stream.stream_id, None)
        stream.done.set()

    def count(self) -> int:
        with self._lock:
            return len(self._streams)

    def active(self) -> tuple[InFlightStream, ...]:
        with self._lock:
            return tuple(self._streams.values())

    # -- drain --------------------------------------------------------------

    @property
    def draining(self) -> bool:
        return self._draining

    def begin_drain(self) -> int:
        """置位 drain 标志（幂等），返回置位瞬间的在途流数。

        ⚠️ 同步且不等待：真正"等在途流收尾"是 `drain()`。分开的理由是 §18.3 第 1 步 ——
        readiness 必须**立刻**翻成不可用，不能等 30s 才摘流量。
        """
        with self._lock:
            self._draining = True
            return len(self._streams)

    async def drain(self, *, timeout_s: float = DRAIN_TIMEOUT_S) -> DrainReport:
        """等待在途流收尾；**不**主动打帧（注入由中间件在下一次 `send` 时做）。

        时限 30s（§18.3 第 2 步），且必须 < Compose 的 `stop_grace_period`（40s）——
        否则容器被 SIGKILL，那正是本步骤要避免的"静默断连"。
        能兜住静止流的原因：`SseRunner` 的心跳间隔是 15s（§A.1.2），
        所以一条"什么都不发"的流最迟 15s 也会 tick 一次，`send` 一定会被再次调用。
        """
        started = time.monotonic()
        streams = self.active()
        if streams:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    _wait_all(s.done.wait() for s in streams), timeout=timeout_s
                )
        finished = tuple(s.task_id for s in streams if s.done.is_set() and s.task_id)
        missing = tuple(
            s.task_id or f"#{s.stream_id}" for s in streams if not s.done.is_set()
        )
        return DrainReport(
            inflight_at_start=len(streams),
            finished_task_ids=finished,
            still_inflight_task_ids=missing,
            waited_s=round(time.monotonic() - started, 3),
            timed_out=bool(missing),
        )


async def _wait_all(awaitables: Iterable[Awaitable[object]]) -> None:
    for aw in awaitables:
        await aw


#: 进程内唯一登记表（`/healthz/ready`、drain 端点、中间件三方共用）。
REGISTRY: Final[InFlightRegistry] = InFlightRegistry()


class _DrainAbort(BaseException):
    """中止本次 ASGI 调用。

    ⚠️ 继承 `BaseException` 是**刻意**的：Starlette / FastAPI 的异常链按 `except Exception`
    兜底，而此刻响应头早已发出、500 也写不出去，用普通异常只会让栈里再多一层
    "对已启动的响应写错误体"的报错。与 `asyncio.CancelledError` 同理 ——
    穿透中间件、直接展开到 ASGI 调用栈，从而触发 `SseRunner.stream()` 的 `finally`
    （取消图任务 → 释放依赖栈里的会话锁 → 写最终任务状态与审计）。
    """


# ============================================================================
# 帧解析与观测
# ============================================================================


@dataclass(frozen=True, slots=True)
class _Frame:
    event: str
    data: Mapping[str, Any]


def _parse_frame(raw: bytes) -> _Frame | None:
    """把一个 SSE 帧解析成 `(event, data)`；无法识别的帧返回 `None`（不猜、不补）。"""
    event = ""
    data_lines: list[str] = []
    for line in raw.decode("utf-8", "replace").split("\n"):
        if line.startswith(":"):
            continue  # SSE 注释行
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if not event and not data_lines:
        return None
    if not data_lines:
        return _Frame(event=event, data={})
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return _Frame(event=event, data={})  # 有事件名但 data 不可解 → 交给契约判定
    if not isinstance(payload, Mapping):
        return _Frame(event=event, data={})
    return _Frame(event=event, data=payload)


class _StreamObserver:
    """一条流的观测状态机（**每请求一个实例**，无跨请求共享可变状态）。"""

    __slots__ = ("_buf", "_last_stage_elapsed_ms", "_stream")

    def __init__(self, stream: InFlightStream) -> None:
        self._stream = stream
        self._buf = bytearray()
        self._last_stage_elapsed_ms = 0

    def feed(self, chunk: bytes) -> list[_Frame]:
        """喂入一段响应字节，返回其中**完整**的帧（不完整的留在缓冲区等下一段）。"""
        if chunk:
            self._buf.extend(chunk)
        frames: list[_Frame] = []
        while True:
            idx = self._buf.find(_FRAME_SEP)
            if idx < 0:
                break
            raw = bytes(self._buf[:idx])
            del self._buf[: idx + len(_FRAME_SEP)]
            frame = _parse_frame(raw)
            if frame is not None:
                frames.append(frame)
        return frames

    def observe(self, frames: Iterable[_Frame]) -> None:
        for frame in frames:
            self._observe_one(frame)

    def finalize(self) -> None:
        """响应结束（`more_body: false`）时的最后一道判定。"""
        if not self._stream.seen_terminal and not self._stream.aborted_for_drain:
            # 流关了一帧终止事件都没有：前端只能靠 90s 看门狗才发现异常（§A.1.4）。
            self._violate("stream_without_terminal")

    # -- 单帧 ---------------------------------------------------------------

    def _observe_one(self, frame: _Frame) -> None:
        stream = self._stream
        stream.frames += 1
        event, data = frame.event, frame.data

        if event == "ack":
            if isinstance(data.get("task_id"), str):
                stream.task_id = str(data["task_id"])
            if isinstance(data.get("session_id"), str):
                stream.session_id = str(data["session_id"])
            return

        is_terminal = event in _TERMINAL_EVENTS
        declared = data.get("terminal")

        if stream.seen_terminal and not is_terminal and event != "heartbeat":
            # 心跳是唯一允许出现在终态之后的事件（§14.3 约束 3），其余都算违规。
            self._violate("terminal_after_terminal")
        if is_terminal:
            if stream.seen_terminal:
                self._violate("duplicate_terminal")
            if declared is not True:
                self._violate("terminal_missing_flag")
            stream.seen_terminal = True
            stream.terminal_event = event
            stream.terminal_monotonic = time.monotonic()
        elif declared is True:
            # 非终止事件声称终止（`degraded` 最容易犯，§A.1.2 明令禁止）。
            self._violate("non_terminal_claims_terminal")

        with contextlib.suppress(Exception):
            self._count(event, data, is_terminal=is_terminal)

    def _count(self, event: str, data: Mapping[str, Any], *, is_terminal: bool) -> None:
        if event == "stage":
            self._count_stage(data)
        elif event == "degraded":
            reason, action = data.get("reason"), data.get("action_taken")
            if reason is not None and action is not None:
                metrics.observe_degraded(DegradedReason(str(reason)), ActionTaken(str(action)))
        elif is_terminal:
            self._count_terminal(event, data)

    def _count_stage(self, data: Mapping[str, Any]) -> None:
        stage, elapsed = data.get("stage"), data.get("elapsed_ms")
        if not isinstance(stage, str) or not isinstance(elapsed, int):
            return
        # `elapsed_ms` 是**从 run 起算**的累计值（`graph/events.py` 写死的时钟口径），
        # 所以本阶段耗时 = 与上一帧的差。非单调时如实丢弃（负数桶会把直方图打脏）。
        delta_ms = elapsed - self._last_stage_elapsed_ms
        self._last_stage_elapsed_ms = max(self._last_stage_elapsed_ms, elapsed)
        if delta_ms >= 0:
            metrics.observe_stage(Stage(stage), delta_ms / 1000.0)

    def _count_terminal(self, event: str, data: Mapping[str, Any]) -> None:
        outcome = _TERMINAL_OUTCOME.get(event)
        if outcome is not None:
            metrics.observe_outcome(outcome)
        if event == "clarify" and isinstance(data.get("reason"), str):
            metrics.observe_clarify(ClarifyReason(str(data["reason"])))
        if event == "refuse" and isinstance(data.get("reason"), str):
            reason = data["reason"]
            if reason:
                metrics.observe_refuse(RefuseReason(reason))
        # ⚠️ **`error` 这一格刻意什么都不记**（outcome 已在上面 `_TERMINAL_OUTCOME` 里记过了）。两族同源：
        # 1) `gate_reject_total` —— **U-125 ②**：唯一记录点是**闸门节点自己**（W4 ①：
        #    `app/graph/nodes/_shared.py::gate_update`）。从终止帧反推的两个毛病：① 与节点侧**双计**；
        #    ② error 帧载荷由 `api/errors.map_code` 产出，只有 `code`/`message`/`retryable`
        #    （`detail` 仅对能处置它的角色开放）⇒ `rule_id` **永远缺位**，全部拒绝会静默落在
        #    `gate_reject_total{rule_id=""}` 一条序列上 —— 那不是"规则号未知"，而是把
        #    §14.5"闸门拒绝率按 `rule_id` 分组"整条判据伪装成"载体没给"（09-22 活体实测即如此）。
        # 2) `exec_failure_total` —— 权威记录点是 `app/graph/nodes/execute.py::_on_failure`（按
        #    `error.error_class` 记全 9 类）。反推同样两个毛病：① 双计；
        #    ② `app/exec/errors.py` 把 `unknown_column` / `unknown_table` / `type_mismatch` /
        #    `unknown_function` / `syntax_error` **五类压成同一个** `SQL_SYNTAX_ERROR` ⇒ 反推出来
        #    只会得到一个 `syntax_error`，把四类结构错误伪装成语法错误（§8.9 要的正是要分清它们）。

    def _violate(self, kind: str) -> None:
        with contextlib.suppress(Exception):
            metrics.observe_ui_contract_violation(kind)
        _log.warning(
            "ui_contract_violation",
            kind=kind,
            endpoint=self._stream.endpoint,
            frames=self._stream.frames,
        )


# ============================================================================
# 中间件
# ============================================================================

TerminalFrameFactory = Callable[[], bytes]


class ObservingMiddleware:
    """纯 ASGI 中间件：HTTP 指标 + 在途流登记 + SSE 帧观测 + 优雅停机注入。

    装配点在 `app/main.py`（组装根，允许 import L5）。`terminal_error_frame` 用**工厂**
    而不是常量：drain 时才构造，才能拿到 `map_code` 的当前码表，也避免本模块 import 期触 L5。
    """

    __slots__ = ("_app", "_registry", "_terminal_error_frame")

    def __init__(
        self,
        app: ASGIApp,
        *,
        registry: InFlightRegistry = REGISTRY,
        terminal_error_frame: TerminalFrameFactory | None = None,
    ) -> None:
        self._app = app
        self._registry = registry
        self._terminal_error_frame = terminal_error_frame

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path: str = str(scope.get("path", ""))
        if path.startswith(_SELF_SCRAPE_PREFIXES):
            # 探针与 /metrics 自身不进 QPS：Prometheus 每 15s 抓一次、LB 每秒探一次，
            # 混进来的后果是"错误率"被探针抖动主导，看板曲线与用户体感脱钩。
            await self._app(scope, receive, send)
            return

        endpoint = self._registry.endpoint_for(path)
        started = time.perf_counter()
        metrics.inc_inflight(endpoint)
        state = _ResponseState(endpoint=endpoint)
        try:
            await self._app(scope, receive, self._make_send(send, state))
        except _DrainAbort:
            # drain 主动中止了这条流的生成器：终止帧**已经发出**、客户端已经按 `terminal` 收口。
            # 所以这里是"我们设计上的一次正常结束"，必须就地吞掉并补一个关流帧。
            # 让它逃到 uvicorn 的后果实测过（2026-09-19 一次真机停机）：
            # 每条被 drain 的流都留下一段 `ERROR: Exception in ASGI application` + 全栈 ⇒
            # runbook 里"按 error 级检索日志"的判据会被自家停机噪声整体污染。
            if state.sse:
                with contextlib.suppress(Exception):
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            self._finish(state, started, endpoint)

    def _finish(self, state: _ResponseState, started: float, endpoint: str) -> None:
        """收尾计数。`finally` 里的一切都必须**不可能抛**（否则一次观测失败会变成 500）。"""
        try:
            status = state.status if state.status is not None else 500
            metrics.record_http_request(endpoint, status, state.latency_s(time.perf_counter() - started))
            metrics.dec_inflight(endpoint)
        except Exception as exc:  # 观测器不许把用户的请求打挂：只记日志，不上抛
            _log.warning("http_metric_failed", endpoint=endpoint, error_type=type(exc).__name__)
        finally:
            if state.stream is not None:
                self._registry.complete(state.stream)

    def _make_send(self, send: Send, state: _ResponseState) -> Send:
        registry = self._registry
        frame_factory = self._terminal_error_frame

        async def wrapped(message: Message) -> None:
            kind = message["type"]

            if kind == "http.response.start":
                state.status = int(message["status"])
                if _is_sse_response(message):
                    state.sse = True
                    state.stream = registry.register(state.endpoint)
                    state.observer = _StreamObserver(state.stream)
                await send(message)
                return

            if kind != "http.response.body" or not state.sse or state.observer is None:
                await send(message)
                return

            body: bytes = message.get("body") or b""
            closing = not message.get("more_body", False)
            stream = state.stream
            assert stream is not None  # sse=True 与 observer 同处赋值

            if stream.aborted_for_drain:
                # drain 之后：数据帧一律吞掉（终止帧已经给过了，再发就是 `duplicate_terminal`），
                # 但关流帧照发 —— 否则连接挂在 uvicorn 的超时上，drain 反而拖长停机。
                if closing:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                return

            with contextlib.suppress(Exception):
                state.observer.observe(state.observer.feed(body))

            if registry.draining and not stream.seen_terminal:
                await _drain_stream(send, stream, frame_factory, state.observer)
                return

            if body:
                await send(message)
            if closing:
                with contextlib.suppress(Exception):
                    state.observer.finalize()
                await send({"type": "http.response.body", "body": b"", "more_body": False})

        return wrapped


async def _drain_stream(
    send: Send,
    stream: InFlightStream,
    frame_factory: TerminalFrameFactory | None,
    observer: _StreamObserver,
) -> None:
    """停机：先补一帧终止 `error`（让客户端**有终态可收**），再中止这条 ASGI 调用。

    ⚠️ 注入的那一帧**同样要喂给观测器**（走与真实帧完全相同的状态机）。
    不这么做会留下一个方向很坏的盲区：被停机打断的流在 `query_outcome_total` 里
    **一个数都不计** —— 于是"事故期间的失败率"被系统性低估，而 §15.4 的告警
    与 G-6 的口径都建立在"失败看得见"之上。计了才诚实：客户端确实收到 `terminal:true`
    的 `error`，这一轮对用户而言就是 `outcome=failed`。
    """
    stream.aborted_for_drain = True
    if frame_factory is not None:
        with contextlib.suppress(Exception):
            frame = frame_factory()
            await send({"type": "http.response.body", "body": frame, "more_body": True})
            # 顺序是刻意的：**发成功之后**才计。`send` 抛了说明对端已经断开，
            # 这一帧没人收到 ⇒ 不计 `failed`（宁可少计，也不凭"我们想发"造一个数）。
            observer.observe(observer.feed(frame))
    _log.info(
        "sse_stream_aborted_for_drain",
        task_id=stream.task_id,
        endpoint=stream.endpoint,
        age_s=round(stream.age_s, 1),
    )
    raise _DrainAbort(f"graceful shutdown: aborting stream {stream.stream_id}")


@dataclass(slots=True)
class _ResponseState:
    """单次调用的中间件状态（局部于一个请求，不做跨请求共享）。"""

    endpoint: str
    status: int | None = None
    sse: bool = False
    stream: InFlightStream | None = None
    observer: _StreamObserver | None = None
    started: float = field(default_factory=time.monotonic)

    def latency_s(self, fallback: float) -> float:
        """**SSE 的延迟口径 = 到终止帧为止**，不是到关流为止。

        为什么必须这样取：转异步路径下 `complete` 之后连接还会为轮询继续活着
        （心跳每 15s），拿"关流时刻"当延迟会把 G-6 的 P95 口径从"用户多久拿到结论"
        变成"这条连接活了多久"。没跑到终态的流（断连、异常）退回整条调用的耗时。
        """
        if self.stream is not None and self.stream.terminal_monotonic is not None:
            return max(0.0, self.stream.terminal_monotonic - self.stream.started_monotonic)
        return fallback


def _is_sse_response(message: Message) -> bool:
    for key, value in message.get("headers") or ():
        if key.lower() == b"content-type" and _SSE_MEDIA in value.decode("latin-1"):
            return True
    return False
