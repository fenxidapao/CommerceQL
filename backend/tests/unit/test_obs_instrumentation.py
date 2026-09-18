"""`app/obs/instrumentation.py` 的离线单测（07 §15.3 采集点 / §14.3 契约复算 / §18.3 停机）。

归属窗口：W7。

## 这个文件证明什么、不证明什么
| 断言 | 在这里（离线喂 ASGI 消息） | 在真实链路上 |
|---|---|---|
| HTTP 计数/耗时/在途 gauge 的取值与**归零** | ✅ | — |
| `endpoint` 标签基数上限（第 21 个路径并入 `unmatched`） | ✅ | — |
| 帧 → 语义指标的映射（stage/degraded/终态/refuse/clarify/闸门） | ✅ | — |
| §14.3 四条契约违规的**独立复算** | ✅ | — |
| drain 会补一帧终止 `error` 并中止本次调用 | ✅ | — |
| "线上真的采到了这些数" | ❌ | 需要 `tests/integration/` + 真 uvicorn |

⚠️ 测试直接构造 ASGI `send` 消息而**不 import `app.api.sse`**：中间件在 L1，
按 R-DEP-1 不许触 L5，测试若 import 它就会把这条边的缺失**掩盖**成"覆盖了"。
帧格式与 `sse.encode` 的一致性另有 `tests/contract/test_obs_frame_format.py` 钉。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from app.obs import metrics
from app.obs.instrumentation import (
    DRAIN_MESSAGE,
    UNMATCHED_ENDPOINT,
    InFlightRegistry,
    ObservingMiddleware,
    normalize_endpoint,
)

# ---------------------------------------------------------------------------
# 夹具：一个最小 ASGI 应用，按给定"消息脚本"回放响应
# ---------------------------------------------------------------------------

_START: dict[str, Any] = {
    "type": "http.response.start",
    "status": 200,
    "headers": [(b"content-type", b"text/event-stream")],
}


def _frame(event: str, data: str) -> dict[str, Any]:
    return {
        "type": "http.response.body",
        "body": f"event: {event}\ndata: {data}\n\n".encode(),
        "more_body": True,  # 漏了它 = 每条帧都被当作关流帧，`stream_without_terminal` 会重复计数
    }


def _final(body: bytes = b"") -> dict[str, Any]:
    return {"type": "http.response.body", "body": body, "more_body": False}


def _make_app(messages: list[dict[str, Any]]) -> Callable[[Any, Any, Any], Any]:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        for message in messages:
            await send(message)

    return app


async def _run(
    messages: list[dict[str, Any]],
    *,
    path: str = "/api/v1/query",
    registry: InFlightRegistry | None = None,
    terminal_frame: Callable[[], bytes] | None = None,
) -> tuple[list[dict[str, Any]], BaseException | None]:
    """跑一次中间件，返回**实际下发**的消息序列与冒泡的异常。"""
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    mw = ObservingMiddleware(
        _make_app(messages),
        registry=registry or InFlightRegistry(),
        terminal_error_frame=terminal_frame,
    )
    error: BaseException | None = None
    try:
        await mw({"type": "http", "path": path, "method": "POST"}, _noop_receive, send)
    except BaseException as exc:  # 本用例就是要观察冒泡的异常
        error = exc
    return sent, error


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.fixture(autouse=True)
def _clean_metrics() -> AsyncIterator[None]:
    metrics.reset_for_tests()
    yield
    metrics.reset_for_tests()


def _sample(name: str, **labels: str) -> float:
    """取一个已声明指标的当前值（无样本时 0）。"""
    text = metrics.render_prometheus_text()
    rendered = ",".join(f'{k}="{v}"' for k, v in labels.items())
    needle = f"{name}{{{rendered}}}" if rendered else f"{name}{{"
    for line in text.splitlines():
        if line.startswith(needle):
            return float(line.rsplit(" ", 1)[1])
        if line.startswith(f"{name} ") and not rendered:
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"指标序列未出现：{needle}\n----\n{text}")


# ===========================================================================
# 一、HTTP 指标
# ===========================================================================


async def test_plain_json_request_records_counter_and_clears_inflight() -> None:
    await _run(
        [
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            },
            _final(b'{"ok":true}'),
        ]
    )
    assert _sample("http_requests_total", endpoint="/api/v1/query", status="2xx") == 1
    # gauge 必须回零：漏 dec 会让"在途请求数"只涨不跌，那是一条会把容量告警永久点亮的 bug。
    assert metrics.inflight_total() == 0


async def test_upstream_5xx_counts_as_error_class() -> None:
    await _run(
        [
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [(b"content-type", b"application/json")],
            },
            _final(b"{}"),
        ]
    )
    assert _sample("http_requests_total", endpoint="/api/v1/query", status="5xx") == 1


async def test_exception_before_response_start_is_recorded_as_5xx() -> None:
    """应用在任何响应头之前抛错：观测侧必须记 5xx，**不能**因为拿不到状态码就记成功。"""

    async def boom(scope: Any, receive: Any, send: Any) -> None:
        raise RuntimeError("boom")

    mw = ObservingMiddleware(boom, registry=InFlightRegistry())
    with pytest.raises(RuntimeError):
        await mw({"type": "http", "path": "/api/v1/feedback", "method": "POST"}, _noop_receive, _send_discard)
    assert _sample("http_requests_total", endpoint="/api/v1/feedback", status="5xx") == 1
    assert metrics.inflight_total() == 0


async def _send_discard(message: dict[str, Any]) -> None:
    return None


async def test_endpoint_label_is_bounded_and_overflow_collapses() -> None:
    registry = InFlightRegistry()
    seen: set[str] = set()
    for i in range(30):
        await _run([_START, _final(b"")], path=f"/api/v1/sessions/ss_{i:032d}", registry=registry)
        seen.add(normalize_endpoint(f"/api/v1/sessions/ss_{i:032d}"))
    # 30 个不同任务 id 的路径必须先归并成同一个模板，再受 ≤20 上限保护。
    assert seen == {"/api/v1/sessions/{id}"}
    # 上限生效：20 条路径之外一律并入 unmatched（Prometheus 序列数有界）。
    for i in range(25):
        await _run([_START, _final(b"")], path=f"/api/v1/extra-{i}", registry=registry)
    assert _sample("http_requests_total", endpoint=UNMATCHED_ENDPOINT, status="2xx") > 0


async def test_self_scrape_endpoints_are_not_counted() -> None:
    """/healthz 与 /metrics 自身不进 QPS：否则看板被探针抖动主导（LB 每秒探一次）。"""
    await _run([_START, _final(b"")], path="/api/v1/healthz/ready")
    await _run([_START, _final(b"")], path="/api/v1/metrics")
    assert metrics.HTTP_REQUESTS_TOTAL.total() == 0


# ===========================================================================
# 二、SSE 帧 → 语义指标
# ===========================================================================


async def test_stage_frames_yield_per_stage_durations_from_cumulative_elapsed() -> None:
    """`elapsed_ms` 是**从 run 起算**的累计口径，直方图要的是**本阶段**耗时 → 取差分。"""
    await _run(
        [
            _START,
            _frame("ack", '{"task_id":"tk_a","session_id":"ss_a","terminal":false}'),
            _frame("stage", '{"stage":"intent","elapsed_ms":400,"terminal":false}'),
            _frame("stage", '{"stage":"schema_linking","elapsed_ms":900,"terminal":false}'),
            _frame("complete", '{"terminal":true}'),
            _final(),
        ]
    )
    assert _sample("stage_duration_seconds_count", stage="intent") == 1
    assert _sample("stage_duration_seconds_count", stage="schema_linking") == 1
    # 900-400=500ms：差分若写成"直接 observe 累计值"，schema_linking 的 sum 会是 0.9。
    assert _sample("stage_duration_seconds_sum", stage="schema_linking") == pytest.approx(0.5)


async def test_non_monotonic_elapsed_is_dropped_not_counted_negative() -> None:
    before = metrics.STAGE_DURATION_SECONDS.observed()
    await _run(
        [
            _START,
            _frame("stage", '{"stage":"intent","elapsed_ms":900,"terminal":false}'),
            _frame("stage", '{"stage":"plan_ready","elapsed_ms":100,"terminal":false}'),
            _frame("complete", '{"terminal":true}'),
            _final(),
        ]
    )
    assert metrics.STAGE_DURATION_SECONDS.observed() == before + 1


async def test_terminal_event_counts_outcome_and_refuse_reason() -> None:
    await _run(
        [
            _START,
            _frame("refuse", '{"reason":"out_of_scope","terminal":true}'),
            _final(),
        ]
    )
    assert _sample("query_outcome_total", outcome="refuse") == 1
    assert _sample("refuse_total", reason="out_of_scope") == 1


async def test_gate_reject_is_counted_from_the_rejection_code() -> None:
    """闸门拒绝在**帧面上**只有 `error` + 拒绝码这一种形态（C-12），所以码就是来源。

    ⚠️ 这条断言钉的是一个真实缺陷的第一版：观测器原本只查载荷里的 `gate_no`/`rule_id`，
    而 `api/errors.map_code` 产出的 error 载荷只有 `code`/`message`/`retryable`
    （`detail` 仅对特定角色开放）⇒ `gate_reject_total` 会成为一个**恒 0 的族**，
    而"系统从没拦过危险 SQL"恰恰是 §15.4 最想发现的问题。
    """
    await _run(
        [
            _START,
            _frame(
                "error",
                '{"code":"GATE_AST_REJECTED","message":"x","retryable":false,"terminal":true}',
            ),
            _final(),
        ]
    )
    # rule_id 落空值 = "载体本轮没给规则号"（EMPTY_LABEL_VALUE 的既定语义，不是"未知规则"）
    assert _sample("gate_reject_total", gate_no="1", rule_id="") == 1
    assert _sample("query_outcome_total", outcome="failed") == 1


async def test_cost_gate_rejection_maps_to_gate_three() -> None:
    await _run(
        [
            _START,
            _frame("error", '{"code":"COST_TOO_HIGH","message":"x","retryable":true,"terminal":true}'),
            _final(),
        ]
    )
    assert _sample("gate_reject_total", gate_no="3", rule_id="") == 1
    assert _sample("gate_reject_total", gate_no="1", rule_id="") == 0


async def test_refuse_frame_does_not_feed_the_gate_counter() -> None:
    """拒答**不是**闸门拒绝（06 §7.2：闸门拒绝不得渲染成拒答卡）⇒ 不得串台。"""
    await _run(
        [
            _START,
            _frame("refuse", '{"reason":"pii_blocked","terminal":true}'),
            _final(),
        ]
    )
    assert _sample("refuse_total", reason="pii_blocked") == 1
    assert metrics.GATE_REJECT_TOTAL.total() == 0


async def test_degraded_frame_counts_reason_and_action_without_ending_the_stream() -> None:
    await _run(
        [
            _START,
            _frame("degraded", '{"reason":"llm_unavailable","action_taken":"template_only","terminal":false}'),
            _frame("complete", '{"terminal":true}'),
            _final(),
        ]
    )
    assert _sample("degraded_total", reason="llm_unavailable", action_taken="template_only") == 1
    assert _sample("query_outcome_total", outcome="success") == 1


async def test_clarify_counts_reason() -> None:
    await _run(
        [
            _START,
            _frame("clarify", '{"reason":"time_ambiguous","clarify_id":"cl_x","terminal":true}'),
            _final(),
        ]
    )
    assert _sample("clarify_total", reason="time_ambiguous") == 1
    assert _sample("query_outcome_total", outcome="clarify") == 1


# ===========================================================================
# 三、§14.3 契约违规的独立复算
# ===========================================================================


@pytest.mark.parametrize(
    ("frames", "kind"),
    [
        (
            [_frame("complete", '{"terminal":true}'), _frame("stage", '{"stage":"intent","elapsed_ms":1,"terminal":false}')],
            "terminal_after_terminal",
        ),
        (
            [_frame("complete", '{"terminal":true}'), _frame("complete", '{"terminal":true}')],
            "duplicate_terminal",
        ),
        ([_frame("error", '{"code":"INTERNAL"}')], "terminal_missing_flag"),
        ([_frame("degraded", '{"reason":"used_cache","action_taken":"used_cache","terminal":true}')], "non_terminal_claims_terminal"),
        ([_frame("ack", '{"task_id":"tk_a","terminal":false}')], "stream_without_terminal"),
    ],
)
async def test_contract_violations_are_counted(frames: list[dict[str, Any]], kind: str) -> None:
    await _run([_START, *frames, _final()])
    assert _sample("ui_contract_violation_total", kind=kind) == 1, kind


async def test_heartbeat_after_terminal_is_legal_and_not_counted() -> None:
    """§14.3 约束 3：心跳是唯一允许出现在终态之后的事件（转异步轮询要继续活着）。"""
    await _run(
        [
            _START,
            _frame("complete", '{"terminal":true}'),
            _frame("heartbeat", '{"terminal":false}'),
            _final(),
        ]
    )
    assert metrics.UI_CONTRACT_VIOLATION_TOTAL.total() == 0


async def test_split_frames_are_reassembled_across_body_messages() -> None:
    """一帧被 TCP 切成两条 body 消息是 SSE 的常态：跨消息的半帧必须能拼回来。"""
    await _run(
        [
            _START,
            {"type": "http.response.body", "body": b'event: complete\ndata: {"ter', "more_body": True},
            {"type": "http.response.body", "body": b'minal":true}\n\n', "more_body": True},
            _final(),
        ]
    )
    assert _sample("query_outcome_total", outcome="success") == 1
    assert metrics.UI_CONTRACT_VIOLATION_TOTAL.total() == 0


# ===========================================================================
# 四、优雅停机（§18.3 第 2~3 步）
# ===========================================================================


def _drain_frame() -> bytes:
    return f'event: error\ndata: {{"code":"INTERNAL","message":"{DRAIN_MESSAGE}","retryable":true,"terminal":true}}\n\n'.encode()


async def test_drain_injects_terminal_error_frame_and_aborts() -> None:
    registry = InFlightRegistry()

    async def slow_app(scope: Any, receive: Any, send: Any) -> None:
        await send(_START)
        await send(_frame("ack", '{"task_id":"tk_slow","session_id":"ss_s","terminal":false}'))
        registry.begin_drain()  # 模拟 pre-stop 钩子在这一刻置位
        await send(_frame("heartbeat", '{"terminal":false}'))

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    mw = ObservingMiddleware(slow_app, registry=registry, terminal_error_frame=_drain_frame)
    with pytest.raises(BaseException) as caught:  # _DrainAbort
        await mw({"type": "http", "path": "/api/v1/query", "method": "POST"}, _noop_receive, send)
    assert type(caught.value).__name__ == "_DrainAbort"

    bodies = [m.get("body", b"") for m in sent if m["type"] == "http.response.body"]
    assert any(b"event: error" in b and DRAIN_MESSAGE.encode() in b and b'"terminal":true' in b for b in bodies)
    # 中止后注册表必须为空：否则 `drain()` 会白等到超时。
    assert registry.count() == 0


async def test_drain_does_not_touch_streams_that_already_reached_terminal() -> None:
    """终态已下发的流不需要被补帧（补了就是 `duplicate_terminal`）——原样转发即可。"""
    registry = InFlightRegistry()
    registry.begin_drain()
    sent, error = await _run(
        [_START, _frame("complete", '{"terminal":true}'), _final()],
        registry=registry,
        terminal_frame=_drain_frame,
    )
    assert error is None
    bodies = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"event: complete" in bodies and b"event: error" not in bodies


async def test_registry_drain_reports_completion_and_timeout() -> None:
    registry = InFlightRegistry()
    stream = registry.register("/api/v1/query")
    stream.task_id = "tk_1"
    registry.begin_drain()

    async def finish_later() -> None:
        await asyncio.sleep(0.01)
        registry.complete(stream)

    task: asyncio.Task[None] = asyncio.create_task(finish_later())
    report = await registry.drain(timeout_s=1.0)
    await task
    assert report.clean and report.inflight_at_start == 1 and report.finished_task_ids == ("tk_1",)

    stuck = registry.register("/api/v1/query")
    stuck.task_id = "tk_stuck"
    timed = await registry.drain(timeout_s=0.05)
    assert timed.timed_out and timed.still_inflight_task_ids == ("tk_stuck",)
    registry.complete(stuck)


def test_sse_latency_is_measured_to_the_terminal_frame_not_to_close() -> None:
    """转异步路径下 `complete` 之后连接还活着（心跳 15s）：延迟口径必须是"到终态为止"，
    否则 G-6 的 P95 会从"用户多久拿到结论"变成"这条连接活了多久"。"""
    from app.obs.instrumentation import _ResponseState

    registry = InFlightRegistry()
    stream = registry.register("/api/v1/query")
    state = _ResponseState(endpoint="/api/v1/query", stream=stream, started=stream.started_monotonic)
    stream.terminal_monotonic = stream.started_monotonic + 3.0
    assert state.latency_s(fallback=99.0) == pytest.approx(3.0)
    stream.terminal_monotonic = None
    assert state.latency_s(fallback=99.0) == 99.0  # 没跑到终态 → 退回整条调用耗时
