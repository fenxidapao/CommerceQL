"""T3 出站客户端单测 —— 07 §10.1（并发/退避/熔断/排队）+ §10.2（模型级超时）。

## 本文件的断言分三层

1. **保护机制真的生效**：并发位真的限制在途数；429 真的退避重试；熔断真的停止发请求。
2. **保护机制不放大预算**：任务级 `timeout_s` 是**整次调用**的预算，重试不许把它乘 3。
3. **坏结果不许变成好结果**：空 `content`（HTTP 200）、上游 message 回显、
   `reasoning_content` —— 三者都必须被拦在出站客户端这一层。

## 🔴 为什么"空 content 检测"值得单独一条断言

实测（2026-09-17，真机）：思考模式下 `max_tokens=32` 时 32 个 completion token
**全部**进 `reasoning`，`content` 是空字符串，而 HTTP 状态是 **200**。
不拦它，`gen_sql` 会拿到空 SQL 并且调用方无从判断 —— 这不是"偶尔少个字段"，
是"每一次都稳定地返回一份看起来正常的空答案"。HTTP 200 是最有欺骗性的那种故障。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from dataclasses import dataclass, field

import httpx
import pytest

from app.llm.client import (
    BACKOFF_JITTER_RATIO,
    BACKOFF_SCHEDULE_S,
    SEMAPHORE_WAIT_TIMEOUT_S,
    ChatClient,
    Completion,
)
from app.llm.errors import (
    LlmConcurrencyExceeded,
    LlmEmptyContent,
    LlmSaturated,
    LlmTimeout,
    LlmUpstreamError,
)
from tests.unit._llm_fake_upstream import FakeUpstream, json_error, json_ok

_BASE_URL = "https://upstream.test"
_API_KEY = "sk-test-not-a-real-key"


@dataclass
class _Clock:
    """可注入的假时钟 —— 让"退避 0.5/1/2 秒"这类断言不真的等 3.5 秒。

    ⚠️ **已知局限**：`asyncio.timeout` 用的是**事件循环的真时钟**，不认这个假钟。
    所以"超时"必须用真 sleep 测（见 `test_slow_upstream_raises_timeout`），
    而"预算做减法"用它测（见 `test_retry_count_is_truncated_by_the_task_budget`）。
    """

    t: float = 1_000.0
    slept: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.t

    async def sleep(self, delay: float) -> None:
        self.slept.append(delay)
        self.t += delay


def _client(
    upstream: FakeUpstream,
    *,
    clock: _Clock | None = None,
    model_names: dict[str, str] | None = None,
    max_concurrency: int = 50,
    semaphore_flash: int = 8,
    semaphore_pro: int = 2,
    max_retries: int = 0,
    circuit_fails: int = 5,
    circuit_open_s: float = 30.0,
    seed: int = 0,
) -> ChatClient:
    c = clock or _Clock()
    return ChatClient(
        base_url=_BASE_URL,
        api_key=_API_KEY,
        model_names=model_names or {"fast": "m-flash", "strong": "m-pro"},
        max_concurrency=max_concurrency,
        semaphore_flash=semaphore_flash,
        semaphore_pro=semaphore_pro,
        max_retries=max_retries,
        circuit_fails=circuit_fails,
        circuit_open_s=circuit_open_s,
        transport=upstream.transport,
        sleep=c.sleep,
        monotonic=c.monotonic,
        rng=random.Random(seed),
    )


async def _call(
    client: ChatClient, model: str = "m-flash", deadline_s: float = 30.0
) -> Completion:
    return await client.invoke(model=model, wire_body={"model": model}, deadline_s=deadline_s)


# ============================================================================
# 一、成功路径与响应解析
# ============================================================================

class TestSuccessfulCall:
    async def test_happy_path_returns_the_content(self) -> None:
        up = FakeUpstream(lambda i, r: json_ok(content='{"sql":"SELECT 1"}'))
        client = _client(up)
        try:
            c = await _call(client)
        finally:
            await client.aclose()
        assert c.text == '{"sql":"SELECT 1"}'
        assert up.sent == 1

    async def test_token_usage_is_taken_from_upstream(self) -> None:
        up = FakeUpstream(lambda i, r: json_ok(prompt_tokens=321, completion_tokens=45))
        client = _client(up)
        try:
            c = await _call(client)
        finally:
            await client.aclose()
        assert c.tokens.input == 321
        assert c.tokens.output == 45
        assert c.tokens.total == 366

    async def test_api_key_travels_in_the_header_not_in_the_body(self) -> None:
        """🔴 密钥只在 `Authorization` 头里。它进了 body 就等于进了日志与录制文件。"""
        up = FakeUpstream()
        client = _client(up)
        try:
            await _call(client)
        finally:
            await client.aclose()
        assert up.raw_calls[0].headers["authorization"] == f"Bearer {_API_KEY}"
        assert _API_KEY not in up.all_sent_text()

    async def test_model_name_from_response_is_kept_for_attribution(self) -> None:
        """上游可能回一个带日期的模型名（如 `deepseek-v4-pro-0813`）—— 必须按**实际**记录。"""
        up = FakeUpstream(lambda i, r: json_ok(model="deepseek-v4-pro-0813"))
        client = _client(up)
        try:
            c = await _call(client, model="m-pro")
        finally:
            await client.aclose()
        assert c.model == "deepseek-v4-pro-0813"

    async def test_unparsable_body_is_an_upstream_error_not_a_crash(self) -> None:
        up = FakeUpstream(lambda i, r: httpx.Response(200, text="<html>oops</html>"))
        client = _client(up)
        try:
            with pytest.raises(LlmUpstreamError):
                await _call(client)
        finally:
            await client.aclose()


# ============================================================================
# 二、reasoning_content 与缓存命中（NFR-4.3 的数据源）
# ============================================================================

class TestReasoningAndCacheUsage:
    async def test_reasoning_content_is_discarded_only_its_length_is_kept(self) -> None:
        """🔴 三条理由必须扔：N-17（可能复述 prompt = 回流通道）、N-12（含 PII）、
        非确定性文本（存下来就会在下游被当成"可消费的内容"）。"""
        secret_echo = "用户在华东区想统计上月销售额，语义包摘要如下…" * 3
        up = FakeUpstream(
            lambda i, r: json_ok(content='{"sql":"SELECT 1"}', reasoning_content=secret_echo)
        )
        client = _client(up)
        try:
            c = await _call(client)
        finally:
            await client.aclose()
        assert c.reasoning_chars == len(secret_echo)  # 只留长度
        assert not hasattr(c, "reasoning_content")    # 结构上就没有这个字段
        assert secret_echo not in c.text
        assert secret_echo not in json.dumps(dict(c.raw_usage), ensure_ascii=False)

    async def test_cache_hit_prefers_the_deepseek_specific_field(self) -> None:
        """实测上游**同时**给两种写法；优先 DeepSeek 专有字段（它是权威口径）。"""
        up = FakeUpstream(
            lambda i, r: json_ok(prompt_tokens=1000, cache_hit_tokens=800, cached_tokens=999)
        )
        client = _client(up)
        try:
            c = await _call(client)
        finally:
            await client.aclose()
        assert c.tokens.cache_hit == 800

    async def test_cache_hit_falls_back_to_the_openai_compatible_shape(self) -> None:
        up = FakeUpstream(
            lambda i, r: json_ok(
                prompt_tokens=1000, include_prompt_cache_hit=False, cached_tokens=777
            )
        )
        client = _client(up)
        try:
            c = await _call(client)
        finally:
            await client.aclose()
        assert c.tokens.cache_hit == 777

    async def test_missing_cache_fields_report_zero_not_an_approximation(self) -> None:
        """🔴 `cache_hit` 是命中率指标的**唯一**数据源。取不到就必须**如实是 0**。

        用别的量近似（例如"输入既然没标命中就算全未命中"）会让命中率变成一个
        永远看起来合理、但和事实无关的数字 —— 那种指标比没有指标更坏。
        """
        up = FakeUpstream(
            lambda i, r: json_ok(prompt_tokens=1000, include_prompt_cache_hit=False)
        )
        client = _client(up)
        try:
            c = await _call(client)
        finally:
            await client.aclose()
        assert c.tokens.cache_hit == 0


# ============================================================================
# 三、坏结果不许变成好结果
# ============================================================================

class TestEmptyContentIsDetected:
    """🔴 实测故障模式：思考吃掉 `max_tokens` → HTTP **200** + `content=''`。"""

    async def test_empty_content_with_http_200_raises(self) -> None:
        up = FakeUpstream(
            lambda i, r: json_ok(
                content="", completion_tokens=32,
                reasoning_content="我先看看用户想问什么……" * 5,
            )
        )
        client = _client(up)
        try:
            with pytest.raises(LlmEmptyContent) as ei:
                await _call(client, model="m-pro")
        finally:
            await client.aclose()
        # 诊断信息必须足以定位"是思考吃光了预算"，而不是只有一句"空内容"
        assert ei.value.detail["completion_tokens"] == 32
        assert ei.value.detail["reasoning_chars"] > 0

    async def test_whitespace_only_content_is_also_empty(self) -> None:
        up = FakeUpstream(lambda i, r: json_ok(content="   \n\t  "))
        client = _client(up)
        try:
            with pytest.raises(LlmEmptyContent):
                await _call(client)
        finally:
            await client.aclose()

    async def test_empty_content_is_degradable_not_retryable_forever(self) -> None:
        """空内容不走"重试"（重发同样的请求只会同样地空）—— 直接在门面层降级。

        这里断言的是客户端把它当**可抛出的 LlmError** 抛出去，且 `max_retries>0`
        时也不会把它重试：一次请求就结束。
        """
        up = FakeUpstream(lambda i, r: json_ok(content=""))
        client = _client(up, max_retries=3)
        try:
            with pytest.raises(LlmEmptyContent):
                await _call(client)
        finally:
            await client.aclose()
        assert up.sent == 1


class TestUpstreamErrorHandling:
    async def test_429_maps_to_concurrency_exceeded(self) -> None:
        up = FakeUpstream(lambda i, r: json_error(429))
        client = _client(up)
        try:
            with pytest.raises(LlmConcurrencyExceeded) as ei:
                await _call(client)
        finally:
            await client.aclose()
        assert ei.value.detail["status"] == 429

    async def test_5xx_maps_to_upstream_error(self) -> None:
        up = FakeUpstream(lambda i, r: json_error(503))
        client = _client(up)
        try:
            with pytest.raises(LlmUpstreamError) as ei:
                await _call(client)
        finally:
            await client.aclose()
        assert ei.value.detail["status"] == 503

    async def test_upstream_message_text_never_leaves_the_client(self) -> None:
        """🔴 实测上游 400 的 message **会回显我们 prompt 里的原文片段**
        （例如 `Prompt must contain the word 'json'`）。

        把它写进日志或用户可见响应 = 自建一条出站回流通道（N-12 的反向）。
        故只保留**结构化标识**（`type` / `code` / `status`），不带 message。
        """
        secret = "Prompt must contain the word 'json' in some form"
        up = FakeUpstream(
            lambda i, r: json_error(
                400, message=secret, err_type="invalid_request_error", code="invalid_prompt"
            )
        )
        client = _client(up)
        try:
            with pytest.raises(LlmUpstreamError) as ei:
                await _call(client)
        finally:
            await client.aclose()
        assert ei.value.detail["status"] == 400
        assert ei.value.detail["upstream_type"] == "invalid_request_error"
        assert ei.value.detail["upstream_code"] == "invalid_prompt"
        haystack = f"{ei.value}\n{ei.value!r}\n{ei.value.detail!r}"
        assert "must contain" not in haystack
        assert "json' in some form" not in haystack

    async def test_client_side_protocol_error_is_not_retried(self) -> None:
        """400 说明**我们的请求体**有问题 —— 原样重发必然再次失败，重试只是浪费预算。"""
        up = FakeUpstream(lambda i, r: json_error(400))
        client = _client(up, max_retries=3)
        try:
            with pytest.raises(LlmUpstreamError):
                await _call(client)
        finally:
            await client.aclose()
        assert up.sent == 1

    async def test_connection_failure_is_an_upstream_error(self) -> None:
        def boom(i: int, r: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=r)

        up = FakeUpstream(boom)
        client = _client(up)
        try:
            with pytest.raises(LlmUpstreamError) as ei:
                await _call(client)
        finally:
            await client.aclose()
        # 异常文本可能含主机名/URL → 只留异常**类型**
        assert ei.value.detail["kind"] == "ConnectError"
        assert "refused" not in str(ei.value)


# ============================================================================
# 四、退避重试
# ============================================================================

class TestBackoff:
    async def test_429_is_retried_and_can_succeed(self) -> None:
        up = FakeUpstream(lambda i, r: json_error(429) if i < 2 else json_ok(content='"ok"'))
        clock = _Clock()
        client = _client(up, clock=clock, max_retries=3)
        try:
            c = await _call(client)
        finally:
            await client.aclose()
        assert c.text == '"ok"'
        assert up.sent == 3
        assert len(clock.slept) == 2

    async def test_backoff_follows_the_documented_schedule_with_jitter(self) -> None:
        """07 §10.1：0.5s / 1s / 2s + jitter（jitter 幅度 07 没给，本窗口取 ±25% 并登记）。"""
        up = FakeUpstream(lambda i, r: json_error(429))
        clock = _Clock()
        client = _client(up, clock=clock, max_retries=3)
        try:
            with pytest.raises(LlmConcurrencyExceeded):
                await _call(client, deadline_s=60.0)
        finally:
            await client.aclose()
        assert len(clock.slept) == 3
        for got, base in zip(clock.slept, BACKOFF_SCHEDULE_S, strict=True):
            jitter = base * BACKOFF_JITTER_RATIO
            assert base - jitter <= got <= base + jitter

    async def test_backoff_has_jitter_not_a_fixed_delay(self) -> None:
        """反向对照：没有 jitter 的话，同批请求会在同一毫秒齐刷刷重发、二次撞限流。"""
        delays = []
        for seed in range(4):
            up = FakeUpstream(lambda i, r: json_error(429))
            clock = _Clock()
            client = _client(up, clock=clock, max_retries=1, seed=seed)
            try:
                with pytest.raises(LlmConcurrencyExceeded):
                    await _call(client, deadline_s=60.0)
            finally:
                await client.aclose()
            delays.append(round(clock.slept[0], 6))
        assert len(set(delays)) > 1

    async def test_slow_upstream_raises_timeout(self) -> None:
        async def slow(i: int, r: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.4)
            return json_ok()

        up = FakeUpstream(slow)
        client = _client(up)
        try:
            with pytest.raises(LlmTimeout) as ei:
                await _call(client, deadline_s=0.05)
        finally:
            await client.aclose()
        assert ei.value.detail["model"] == "m-flash"

    async def test_timeout_is_not_retried(self) -> None:
        """超时重试只会把预算吃光，让降级来不及发生（预算是硬约束）。"""
        async def slow(i: int, r: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.4)
            return json_ok()

        up = FakeUpstream(slow)
        client = _client(up, max_retries=3)
        try:
            with pytest.raises(LlmTimeout):
                await _call(client, deadline_s=0.05)
        finally:
            await client.aclose()
        assert up.sent == 1

    async def test_retry_count_is_truncated_by_the_task_budget(self) -> None:
        """🔴 **预算做减法，不是每次尝试各给一份**。

        `timeout_s` 是**整次 task 调用**的预算（含重试与退避）。若写成"每次尝试各给
        timeout_s"，`gen_sql` 的 1.3s 在 3 次重试下变成 3.9s —— P95 契约被重试悄悄放大。

        做法：跑两次，唯一变量是预算。预算短 → 重试被截断；预算长 → 重试跑满。
        只有**两个方向都断言**，才能排除"重试次数恰好看上去对"的巧合。
        """
        def slow_fail(i: int, r: httpx.Request) -> httpx.Response:
            return json_error(429)

        # ① deadline 短：每次处理"耗掉"0.4s 假时钟时间 → 1.3s 只够 2 次尝试
        clock_short = _Clock()

        def tick(i: int, r: httpx.Request) -> httpx.Response:
            clock_short.t += 0.4
            return json_error(429)

        up_short = FakeUpstream(tick)
        client_short = _client(up_short, clock=clock_short, max_retries=3)
        try:
            with pytest.raises(LlmConcurrencyExceeded):
                await _call(client_short, deadline_s=1.3)
        finally:
            await client_short.aclose()

        # ② 对照：deadline 足够 → 4 次尝试（= max_retries 3 + 1）跑满
        up_long = FakeUpstream(slow_fail)
        client_long = _client(up_long, clock=_Clock(), max_retries=3)
        try:
            with pytest.raises(LlmConcurrencyExceeded):
                await _call(client_long, deadline_s=60.0)
        finally:
            await client_long.aclose()

        assert up_short.sent == 2, "短 deadline 下必须被截断（否则说明 deadline 没做减法）"
        assert up_long.sent == 4, "长 deadline 下必须跑满重试（否则说明重试根本没生效）"
        # 短 deadline 那一路真的把时间花掉了，而不是提前放弃
        assert clock_short.t - 1_000.0 >= 0.9 * 1.3


# ============================================================================
# 五、并发位
# ============================================================================

class TestConcurrency:
    async def test_global_cap_limits_in_flight_requests(self) -> None:
        """全局上限是**并发连接数**语义（07 §10.1 纠正过的易误读点），不是 QPS。"""
        state = {"in_flight": 0, "peak": 0}

        async def responder(i: int, r: httpx.Request) -> httpx.Response:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
            await asyncio.sleep(0.02)
            state["in_flight"] -= 1
            return json_ok()

        up = FakeUpstream(responder)
        client = _client(up, max_concurrency=2, semaphore_flash=8)
        try:
            await asyncio.gather(*(_call(client) for _ in range(6)))
        finally:
            await client.aclose()
        assert up.sent == 6
        assert state["peak"] == 2

    async def test_per_model_cap_is_applied_independently(self) -> None:
        """07 附-6：flash 8 位 / pro 2 位。**按模型分别限**，不是共享一个池。"""
        state = {"in_flight": 0, "peak": 0}

        async def responder(i: int, r: httpx.Request) -> httpx.Response:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
            await asyncio.sleep(0.02)
            state["in_flight"] -= 1
            return json_ok()

        up = FakeUpstream(responder)
        client = _client(up, max_concurrency=50, semaphore_flash=1, semaphore_pro=1)
        try:
            await asyncio.gather(
                *[_call(client, model="m-flash") for _ in range(4)],
                *[_call(client, model="m-pro") for _ in range(4)],
            )
        finally:
            await client.aclose()
        # 两个模型各自 1 位 → 同时在途 2（若共用一个池，peak 会是 1）
        assert state["peak"] == 2

    async def test_concurrency_limits_are_readable_for_ops(self) -> None:
        """运维要能从进程里读出"当前限到几路"，否则 429 只能靠猜。"""
        client = _client(FakeUpstream(), semaphore_flash=8, semaphore_pro=2)
        try:
            assert client.concurrency_limits() == {"m-flash": 8, "m-pro": 2}
        finally:
            await client.aclose()

    async def test_missing_model_in_map_does_not_crash_construction(self) -> None:
        """`model_names` 只有 fast 时也必须能构造（strong 位不注册即可）。"""
        client = _client(FakeUpstream(), model_names={"fast": "m-flash"})
        try:
            assert client.concurrency_limits() == {"m-flash": 8}
        finally:
            await client.aclose()

    async def test_waiting_too_long_for_a_slot_is_saturation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """排队超过 20s → `LlmSaturated` → 门面降级（07 §10.1"排队"行）。

        这里把等待上限压到 0 来避免真的等 20 秒 —— 被测的是"等不到就抛 LlmSaturated"
        这条分支，不是那个数字（数字由 `SEMAPHORE_WAIT_TIMEOUT_S` 常量断言钉住）。
        """
        monkeypatch.setattr("app.llm.client.SEMAPHORE_WAIT_TIMEOUT_S", 0.01)
        assert SEMAPHORE_WAIT_TIMEOUT_S == 20.0  # 常量本身必须是文档写的 20s

        async def responder(i: int, r: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.3)
            return json_ok()

        up = FakeUpstream(responder)
        client = _client(up, max_concurrency=1, semaphore_flash=1)
        try:
            first = asyncio.create_task(_call(client))
            await asyncio.sleep(0.02)  # 让第一个占住唯一的位
            with pytest.raises(LlmSaturated) as ei:
                await _call(client)
            await first
        finally:
            await client.aclose()
        assert ei.value.detail["model"] == "m-flash"
        assert up.sent == 1  # 没拿到位 → 请求根本没发


# ============================================================================
# 六、熔断
# ============================================================================

class TestCircuitBreaker:
    async def test_circuit_opens_after_the_configured_failures(self) -> None:
        """07 §10.2：连续 5 次失败 → 开路 30s。开路期间**不发请求**。"""
        up = FakeUpstream(lambda i, r: json_error(503))
        client = _client(up, max_retries=0, circuit_fails=5, circuit_open_s=30.0)
        try:
            for _ in range(5):
                with pytest.raises(LlmUpstreamError):
                    await _call(client)
            assert up.sent == 5
            assert client.circuit_is_open("m-flash") is True

            with pytest.raises(LlmTimeout) as ei:
                await _call(client)
            assert up.sent == 5, "开路期间不得发出任何请求"
            assert ei.value.detail["model"] == "m-flash"
        finally:
            await client.aclose()

    async def test_success_resets_the_failure_counter(self) -> None:
        """反向对照：4 次失败后 1 次成功 → 计数归零，熔断**不该**被打开。

        没有这条，"熔断会在 5 次后打开"可以用"计数器永远不清零"来作弊 ——
        那样一个偶发 5xx 的模型会在累计 5 次（可能横跨数小时）后被永久熔断。
        """
        up = FakeUpstream(lambda i, r: json_ok() if i == 4 else json_error(503))
        client = _client(up, max_retries=0, circuit_fails=5)
        try:
            for _ in range(6):
                with contextlib.suppress(LlmUpstreamError):
                    await _call(client)
            assert client.circuit_is_open("m-flash") is False
        finally:
            await client.aclose()
        assert up.sent == 6

    async def test_half_open_admits_exactly_one_probe(self) -> None:
        """半开：只放 1 个探测请求进去，其余继续按开路处理（不发请求）。"""
        release = asyncio.Event()

        async def responder(i: int, r: httpx.Request) -> httpx.Response:
            if i < 5:
                return json_error(503)
            await release.wait()  # 探测请求挂住，制造"在途"的中间态
            return json_ok()

        up = FakeUpstream(responder)
        clock = _Clock()
        client = _client(
            up, clock=clock, max_retries=0, circuit_fails=5, circuit_open_s=30.0
        )
        try:
            for _ in range(5):
                with pytest.raises(LlmUpstreamError):
                    await _call(client)

            clock.t += 31.0  # 越过开路窗口 → 进入半开

            probe = asyncio.create_task(_call(client))
            await asyncio.sleep(0.02)  # 让探测走到"在途"
            with pytest.raises(LlmTimeout) as ei:
                await _call(client)
            assert "半开" in ei.value.message
            assert up.sent == 6

            release.set()
            c = await probe
            assert c.text
            assert up.sent == 6
        finally:
            await client.aclose()

    async def test_half_open_flag_is_cleared_by_the_admitting_call_itself(self) -> None:
        """🔴 **白盒不变量**：放行探测的那次调用必须自己把标志复位，即使它**成功**了。

        实测记录（2026-09-17，探针脚本）：把复位条件写成 `opened_at is not None` 时，
        探测成功后标志会残留 `True`；它之所以没造成故障，只因为**下一次失败触顶时
        `opened_at` 恰好又非空**，那次的 `finally` 顺带清掉了它。

        也就是说，那种写法的正确性依赖"两处不相干分支的巧合交互" —— 把触顶逻辑挪一行、
        或让成功路径不清 `opened_at`，残留标志就会让半开分支永远认为"已有探测在途"，
        使该模型**在所有请求都不发出的情况下**静默降级（症状是"这个模型永远在降级，
        但上游监控里它一次请求都没有"）。

        这条断言刻意读私有字段：它是**因果关系**的断言（"谁设置、谁复位"），
        用黑盒行为断言不出来 —— 黑盒只能看到"恰好又正常了"。
        """
        mode = {"fail": True}

        def responder(i: int, r: httpx.Request) -> httpx.Response:
            return json_error(503) if mode["fail"] else json_ok()

        up = FakeUpstream(responder)
        clock = _Clock()
        client = _client(
            up, clock=clock, max_retries=0, circuit_fails=5, circuit_open_s=30.0
        )
        try:
            for _ in range(5):
                with pytest.raises(LlmUpstreamError):
                    await _call(client)
            clock.t += 31.0
            mode["fail"] = False
            await _call(client)  # 半开探测成功
            assert up.sent == 6

            # 读私有字段是刻意的：见本用例 docstring（要断的是因果关系，不是黑盒行为）
            breaker = client._breakers["m-flash"]
            assert breaker.half_open_probe_in_flight is False, (
                "探测已结束，标志却还在 —— 这一次是巧合被别的分支清掉，下一次不一定"
            )
        finally:
            await client.aclose()

    async def test_two_full_open_recover_cycles_both_admit_a_probe(self) -> None:
        """两轮完整的"开路 → 等过窗口 → 放探测 → 恢复"都必须能放行。

        单轮正常不足以说明问题：与半开标志相关的缺陷只在**第二次恢复**时才现形，
        而第一次恢复会一切正常。故这里显式跑满两个周期。
        """
        mode = {"fail": True}

        def responder(i: int, r: httpx.Request) -> httpx.Response:
            return json_error(503) if mode["fail"] else json_ok()

        up = FakeUpstream(responder)
        clock = _Clock()
        client = _client(
            up, clock=clock, max_retries=0, circuit_fails=5, circuit_open_s=30.0
        )
        try:
            # 周期 ①：打到开路 → 等过窗口 → 恢复
            for _ in range(5):
                with pytest.raises(LlmUpstreamError):
                    await _call(client)
            assert up.sent == 5
            clock.t += 31.0
            mode["fail"] = False
            await _call(client)  # 探测成功
            assert up.sent == 6

            # 周期 ②：**再次**打到开路 → 再等过窗口 → 必须仍然能放探测
            mode["fail"] = True
            for _ in range(5):
                with pytest.raises(LlmUpstreamError):
                    await _call(client)
            assert up.sent == 11
            clock.t += 31.0
            mode["fail"] = False
            await _call(client)
            assert up.sent == 12, "第二次恢复时探测被 stale 标志挡住了（模型被永久锁死）"
        finally:
            await client.aclose()
