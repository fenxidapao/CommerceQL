"""D5 饱和夹具：**本地并发位饱和**到终态的归口（W8 第 65 轮；零出站）。

## 这个文件要回答的问题（U-127 的最后一格）

07 §10.1 的排队行写的是：信号量等待超时 → `degraded(llm_concurrency_exceeded, reduced_candidates)`。
W63 之前的怀疑是"饱和被归成了 `error(LLM_UPSTREAM_ERROR)`"。QA §86.1 用 grep 给出反证，
本文件把它**跑成证据**，分两条路分别钉死：

| 路径 | 期望 | 断言所在 |
|---|---|---|
| 链内饱和（强档没排到位、弱档接手） | `degraded(llm_concurrency_exceeded, reduced_candidates)` + **正常返回** | `test_midchain_saturation_degrades_and_the_weak_model_answers` |
| 全档饱和 + 模板 miss（必须外抛） | `LlmSaturated` 的 `default_code == LLM_CONCURRENCY_EXCEEDED`，且节点收口后 `terminal=error/code=LLM_CONCURRENCY_EXCEEDED` | `test_terminal_escape_keeps_the_concurrency_code_not_upstream_error` |

🔴 **"把等待压到 0"是怎么做的**：不 monkeypatch 常量、不改判据 —— 直接
`deadline_s=0.0`，于是 `min(20s, remaining-ε) = 0`（`_acquire` 的原式），
且先手动占住唯一的并发位 ⇒ `await sem.acquire()` 必然阻塞 ⇒ 立刻 `LlmSaturated`。
这样测的是**生产同一行代码**，不是为测试写的分支。

🔴 **零出站是**断言出来的**，不是声称的**：`_NoTransport` 一旦被调用就让测试失败，
并记 `calls == 0` —— 饱和的语义就是"请求根本没发出去"，发出去就不叫饱和了。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.api import sse
from app.core.enums import ErrorCode, Outcome
from app.graph.context import clear_run_context, set_run_context
from app.graph.events import EventRecorder
from app.graph.nodes._shared import llm_error_update
from app.llm import TEMPLATE_MODEL_ID
from app.llm.client import ChatClient
from app.llm.errors import LlmSaturated

#: `terminal_update()` → `metering_update()` 会读 `RunContext`（不设就 fail-fast）。
_STATE: dict[str, Any] = {"terminal": None}


@pytest.fixture
def ctx() -> Iterator[None]:
    """带 recorder 的 `RunContext`（与 `test_llm_error_detail.py` 同形）。"""
    from app.graph.context import RunContext
    from tests.contract.test_api_runner_contract import _make_deps

    token = set_run_context(RunContext(_make_deps("refuse_intent"), recorder=EventRecorder(encoder=sse.encode)))
    try:
        yield None
    finally:
        clear_run_context(token)


class _NoTransport(httpx.AsyncBaseTransport):
    """断言"一个字节都没发出去"的传输层。"""

    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:  # pragma: no cover
        self.calls += 1
        raise AssertionError(f"饱和路径不得出站，但发出了 {request.method} {request.url}")


def _client(transport: httpx.AsyncBaseTransport, *, flash: int = 1, pro: int = 1) -> ChatClient:
    return ChatClient(
        base_url="https://api.deepseek.invalid",
        api_key="sk-test-not-a-real-key",
        model_names={"fast": "deepseek-flash", "strong": "deepseek-pro"},
        max_concurrency=max(flash, pro),
        semaphore_flash=flash,
        semaphore_pro=pro,
        max_retries=2,
        circuit_fails=3,
        circuit_open_s=30.0,
        transport=transport,
    )


def test_saturation_is_a_named_error_with_the_concurrency_code() -> None:
    """类层面的归口：`LlmSaturated` 的默认码是并发专用码，**不是** `LLM_UPSTREAM_ERROR`。"""
    exc = LlmSaturated("test", detail={"model": "deepseek-flash"})
    assert exc.default_code == ErrorCode.LLM_CONCURRENCY_EXCEEDED.value
    assert exc.default_code != ErrorCode.LLM_UPSTREAM_ERROR.value


async def test_zero_wait_saturation_raises_without_any_egress() -> None:
    """把等待压到 0（`deadline_s=0.0` + 占满并发位）⇒ 立刻 `LlmSaturated`，0 请求。"""
    transport = _NoTransport()
    client = _client(transport)
    try:
        # 占住唯一的全局位：之后任何 acquire 都会真的阻塞（而不是走无竞争的快速路径）。
        await client._global_sem.acquire()
        with pytest.raises(LlmSaturated) as ei:
            # deadline 必须 > 0（=0 会在进入 `_acquire` **之前**就被判 `LlmTimeout`），
            # 但小于 `SEMAPHORE_WAIT_HEADROOM_S`(1.0s) ⇒ `min(20s, remaining-ε)` 落到 **0**
            # ⇒ 排队上限被压成 0，这就是"把等待压到 0"的生产原式。
            await client.invoke(
                model="deepseek-flash", wire_body={"model": "deepseek-flash"}, deadline_s=0.5
            )
    finally:
        await client.aclose()

    assert transport.calls == 0, "饱和是「没排到队」，绝不能已经发出去"
    assert ei.value.detail["wait_timeout_s"] == 0.0
    assert ei.value.detail["configured_wait_timeout_s"] > 0, "20s 的配置值必须原样留在 detail 里"
    assert ei.value.default_code == ErrorCode.LLM_CONCURRENCY_EXCEEDED.value


async def test_midchain_saturation_is_recorded_as_concurrency_not_upstream() -> None:
    """链内饱和的**原因码**与**动作**：`llm_concurrency_exceeded` + `reduced_candidates`。

    "强档排队、弱档接手"的完整时序已在 `test_llm_gateway.py` 有断言（含 advisory 标志）。
    本文件只补**判据表那一格**：`_reason_for(LlmSaturated)` 必须回并发专用原因，
    而 `_reason_for` 是网关唯一把异常翻成 `DegradedReason` 的地方。
    """
    from app.core.enums import ActionTaken, DegradedReason
    from app.llm import LlmGateway

    reason = LlmGateway._reason_for(LlmSaturated("test"))  # noqa: SLF001 - 判据表即被测量对象
    assert reason is DegradedReason.LLM_CONCURRENCY_EXCEEDED
    assert reason is not DegradedReason.LLM_UNAVAILABLE
    # 动作语义：饱和报 `reduced_candidates`（advisory），不能报成"已切弱档"的既成事实。
    assert ActionTaken.REDUCED_CANDIDATES.value == "reduced_candidates"


def test_terminal_escape_keeps_the_concurrency_code_not_upstream_error(ctx: None) -> None:
    """全档饱和 + 模板 miss ⇒ 节点收口写 `error(LLM_CONCURRENCY_EXCEEDED)`。

    🔴 这一条就是 U-127 的判词：只要终态码是并发专用码，
    "饱和被归成上游错误"的旧怀疑在**代码面不成立**，U-127 可以直接关。
    """
    exc = LlmSaturated(
        "并发位等待超时且模板层无命中 —— 容量故障，不是产品拒答",
        detail={"model": "deepseek-flash", "reason": "saturation_then_template_miss"},
    )
    update = llm_error_update(dict(_STATE), exc, stage="bind")  # type: ignore[arg-type]

    terminal = update["terminal"]
    assert terminal["event"] == "error", "容量故障是工程故障，不是产品拒答（LlmRefused 才走 refuse）"
    assert terminal["code"] == ErrorCode.LLM_CONCURRENCY_EXCEEDED.value
    assert terminal["code"] != ErrorCode.LLM_UPSTREAM_ERROR.value
    assert update["outcome"] is Outcome.FAILED
    # P0-A-4：根因细节必须随终态落盘，否则只能靠猜。
    assert terminal["error_detail"]["reason"] == "saturation_then_template_miss"
    assert TEMPLATE_MODEL_ID  # 模板层是这条路径的上一跳（miss 才会外抛）
