"""OpenAI 兼容出站客户端：并发信号量 / 有限退避 / 熔断 / 超时（07 §10.1 + §10.2）。

归属窗口：W3A｜落点由 07 §3.2 指定（`llm/client.py` = "OpenAI 兼容 + 并发信号量 + 退避"）。

## 1. 为什么是**并发信号量**而不是 QPS 计数器（07 §10.1 纠正过的易误读点）

DeepSeek 的限流语义是"**并发连接数**"：请求从发出到**响应读取完毕**算占用一个连接位，
超限返回 429。QPS 计数器实现与这个语义**不对应** —— 它允许"1 秒内连发 8 个长请求"，
而那正好就是撞限流的姿势。因此原语是 `asyncio.Semaphore`。

## 2. 超时：**做减法的 deadline**，不是"每次尝试各给一份"

`deadline_s` 是**整次 task 调用**的传输上限（含重试与退避）。若写成"每次尝试各给一份"，
则一次 15s 的调用在 3 次重试下会变成 45s —— 传输上限是保护，不能被重试悄悄放大。
实现方式：进来先算 `deadline`，每次尝试只拿 `deadline - now`；退避延时也从同一个 deadline 里扣。

⚠️ 本参数**不接受** 07 §16.1 的阶段延迟预算：那是端到端 P95 的分配份额，不是超时上限。
把 0.6–1.3s 的分配值接到这里，会让真机延迟 1.4–1.6s 的任务 100% 失败
（实测 0/15 → 15/15，见 `router.py` 模块 docstring）。调用方唯一的合法取值来源是
`router.hard_timeout_s()`（07 §10.2）。

## 3. 🔴 三条**实测**得到的上游行为（文档没写，写错不报错只出坏结果）

| # | 事实 | 实测（2026-09-17，真机） | 本模块的处置 |
|---|---|---|---|
| 1 | 两模型**默认开思考**；关闭的唯一有效写法是 `thinking={"type":"disabled"}` | `thinking:false` → **400**；`enable_thinking:false` / `chat_template_kwargs` → **被静默忽略**（仍产 reasoning token） | 由 `egress_guard.build_wire_request` 统一写入，**不允许调用方拼** |
| 2 | **`max_tokens` 会被 reasoning 吃掉 → `content` 为空且 HTTP 200** | `max_tokens=32` → 32 个 completion token 全在 reasoning，`content=''` | ① `router.max_tokens_for()` 给思考档留余量；② 本模块**仍然**检测空 content → `LlmEmptyContent`（双保险，因为余量值是经验值） |
| 3 | `response_format=json_object` 要求消息里出现 **"json" 字样** | 缺 → 400 `Prompt must contain the word 'json' ...` | `egress_guard` 在构造期断言 |

## 4. `reasoning_content` 必须**丢弃**（不是"存起来备用"）

两个模型都会返回 `message.reasoning_content`（实测 flash 126 / pro 116 字符）。
它有三个理由必须扔：

1. **N-17 同源**：思考过程可能复述 prompt 片段，回灌进下一轮 = 自建回流通道；
2. **N-12**：它可能包含被送出的语义包摘要与用户问题（= PII 面），不该进日志；
3. 它是**非确定性文本**：任何"存下来做诊断"的设计都会在下游变成"可被消费的内容"。

本模块只记录 `reasoning_chars`（**长度**），长度足以诊断"思考把预算吃光了"这件事。
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.core.contracts import TokenUsage
from app.llm.errors import (
    LlmConcurrencyExceeded,
    LlmEmptyContent,
    LlmError,
    LlmSaturated,
    LlmTimeout,
    LlmUpstreamError,
)

__all__ = [
    "Completion",
    "ChatClient",
    "SEMAPHORE_WAIT_TIMEOUT_S",
    "BACKOFF_SCHEDULE_S",
    "BACKOFF_JITTER_RATIO",
]

#: 信号量等待上限（07 §10.1 "排队"行）。超时 → `LlmSaturated` → 降级。
SEMAPHORE_WAIT_TIMEOUT_S: Final[float] = 20.0

#: 429 的退避档位（07 §10.1：0.5s / 1s / 2s，最多 3 次）。
BACKOFF_SCHEDULE_S: Final[tuple[float, ...]] = (0.5, 1.0, 2.0)

#: jitter 幅度。07 只写了"+ jitter"，**没给幅度** —— 取 ±25%（经验值，已登记）。
#: jitter 的作用是打散重试同步（否则同批请求会在同一毫秒齐刷刷重发，二次撞限流）。
BACKOFF_JITTER_RATIO: Final[float] = 0.25


@dataclass(frozen=True, slots=True)
class Completion:
    """一次成功的补全结果（**已是"可出站内容之外的干净物"**：不含 reasoning_content）。"""

    text: str
    model: str
    tokens: TokenUsage
    #: 上游原始 `usage`（**只含计数**，不含内容）—— 供审计与成本对账。
    raw_usage: Mapping[str, Any]
    latency_ms: int
    #: 思考内容的**长度**（不是内容）。诊断"思考把 max_tokens 吃光了"用。
    reasoning_chars: int


@dataclass(slots=True)
class _Breaker:
    """按模型的熔断状态（07 §10.2：连续 5 次失败 → 开路 30s；半开探测 1 次）。"""

    fails: int = 0
    opened_at: float | None = None
    half_open_probe_in_flight: bool = False

    def is_open(self, now: float, open_s: float) -> bool:
        return self.opened_at is not None and (now - self.opened_at) < open_s


class ChatClient:
    """出站客户端。

    ⚠️ **只做传输与保护，不做业务**：不选模型（router 的事）、不拼 prompt（loader 的事）、
    不构造请求体（egress_guard 的事）。这样"出站内容 = 已登记字段"这个性质才好验证 ——
    只要 `build_wire_request` 是唯一构造点，录制到的 payload 就必然可追溯。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_names: Mapping[str, Any],
        max_concurrency: int,
        semaphore_flash: int,
        semaphore_pro: int,
        max_retries: int,
        circuit_fails: int,
        circuit_open_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._max_retries = max_retries
        self._circuit_fails = circuit_fails
        self._circuit_open_s = circuit_open_s
        self._sleep = sleep or asyncio.sleep
        self._monotonic = monotonic or time.monotonic
        self._rng = rng or random.Random()

        # 并发位：**全局上限 AND 按模型上限**（Q2 裁定 —— 两个配置值都生效，不猜语义）
        self._global_sem = asyncio.Semaphore(max_concurrency)
        self._model_sem: dict[str, asyncio.Semaphore] = {}
        self._model_limits: dict[str, int] = {}
        for name, limit in (
            (model_names.get("fast"), semaphore_flash),
            (model_names.get("strong"), semaphore_pro),
        ):
            if isinstance(name, str) and name:
                self._model_limits[name] = limit
                self._model_sem[name] = asyncio.Semaphore(limit)

        self._breakers: dict[str, _Breaker] = {}
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0),
            transport=transport,
        )

    # -- 生命周期 -----------------------------------------------------------

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- 观测（供测试与门面用）----------------------------------------------

    def concurrency_limits(self) -> Mapping[str, int]:
        """返回 `{模型名: 并发位}` —— 测试用它断言"按模型 8/2"确实落在信号量上。"""
        return dict(self._model_limits)

    def circuit_is_open(self, model: str) -> bool:
        br = self._breakers.get(model)
        if br is None:
            return False
        return br.is_open(self._monotonic(), self._circuit_open_s)

    # -- 主路径 -------------------------------------------------------------

    async def invoke(
        self,
        *,
        model: str,
        wire_body: Mapping[str, Any],
        deadline_s: float,
    ) -> Completion:
        """发一次调用（含退避重试与熔断）。`deadline_s` 是**整次调用**的传输上限（07 §10.2）。"""
        start = self._monotonic()
        deadline = start + deadline_s
        last: LlmError | None = None

        breaker = self._breakers.setdefault(model, _Breaker())
        now = self._monotonic()
        if breaker.is_open(now, self._circuit_open_s):
            # 07 §10.2：开路期间**直接走降级链，不发请求**。
            raise LlmTimeout(
                "熔断已开路，本次不发请求",
                detail={"model": model, "circuit_open_s": self._circuit_open_s},
            )
        #: 本轮是否**由本协程**放行了一个半开探测。
        #:
        #: 复位条件必须挂在这个标志上，**不能**写成 `if breaker.opened_at is not None`。
        #: 实测（2026-09-17，探针脚本）旧写法的行为：探测**成功**会把 `opened_at` 清成
        #: `None`，于是那一轮 `finally` 不复位，标志残留 `True`；它之所以没造成故障，
        #: 只是因为**下一次失败触顶时 `opened_at` 恰好又非空**，那次的 `finally` 顺手把它
        #: 清掉了 —— 换句话说，正确性建立在"两处不相干代码的巧合交互"上。
        #:
        #: 那不是能靠阅读看出来的性质：把触顶逻辑挪一行、或让半开探测改成"成功也不清
        #: `opened_at`"，残留标志就会让半开分支永远认为"已有探测在途"，
        #: 使该模型**在所有请求都不发出的情况下**静默降级。
        #: 现在复位由放行者自己负责，这条不变量是**局部**的、不依赖别的分支做什么。
        probe_admitted = False
        if breaker.opened_at is not None:
            # 半开：只放 1 个探测请求进去。其余并发请求继续按开路处理（不发请求）。
            if breaker.half_open_probe_in_flight:
                raise LlmTimeout(
                    "熔断半开，已有 1 个探测请求在途", detail={"model": model}
                )
            breaker.half_open_probe_in_flight = True
            probe_admitted = True

        try:
            for attempt in range(self._max_retries + 1):
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    last = last or LlmTimeout(
                        "传输 deadline 耗尽（超时）",
                        detail={"model": model, "deadline_s": deadline_s},
                    )
                    break

                try:
                    completion = await self._attempt(
                        model=model, wire_body=wire_body, remaining=remaining
                    )
                except LlmError as exc:
                    last = exc
                    breaker.fails += 1
                    if breaker.fails >= self._circuit_fails:
                        breaker.opened_at = self._monotonic()
                    # 429/5xx 才值得重试；其余（超时/非重试 4xx）立刻上抛
                    if not self._retryable(exc) or attempt >= self._max_retries:
                        break
                    delay = self._backoff(attempt)
                    if self._monotonic() + delay >= deadline:
                        break  # 退避会跨过预算边界 → 不睡，直接失败（省掉无意义的等待）
                    await self._sleep(delay)
                    continue

                # 成功
                breaker.fails = 0
                breaker.opened_at = None
                return completion
        finally:
            # 复位判据是"**本协程放行过探测**"，不是"熔断还开着"（见上面 `probe_admitted` 的说明）。
            if probe_admitted:
                breaker.half_open_probe_in_flight = False

        assert last is not None  # 循环必然赋值：要么 break 前有 last，要么超时分支给了默认
        raise last

    # -- 内部 ---------------------------------------------------------------

    def _retryable(self, exc: LlmError) -> bool:
        """只有 429（上游并发超限）与 5xx（上游故障）值得重试。

        ⚠️ 超时**不重试**：deadline 是硬上限，重试只会把时间吃光并让降级来不及发生。
        非重试型 4xx（如 400）也不重试 —— 那说明**我们的请求体有问题**，
        原样重发必然再次失败（"原样重试必然失败"就不该重试，这与 §14.4 的 `⭕` 纪律同源）。
        """
        return isinstance(exc, (LlmConcurrencyExceeded, LlmUpstreamError)) and not (
            isinstance(exc, LlmUpstreamError) and exc.detail.get("status") in {400, 401, 403, 404, 422}
        )

    def _backoff(self, attempt: int) -> float:
        base = BACKOFF_SCHEDULE_S[min(attempt, len(BACKOFF_SCHEDULE_S) - 1)]
        jitter = base * BACKOFF_JITTER_RATIO
        return max(0.0, base + self._rng.uniform(-jitter, jitter))

    async def _acquire(self, model: str) -> None:
        """先拿全局位、再拿模型位，都用同一个 20s 上限（07 §10.1）。"""
        sem = self._model_sem.get(model)
        try:
            async with asyncio.timeout(SEMAPHORE_WAIT_TIMEOUT_S):
                await self._global_sem.acquire()
                try:
                    if sem is not None:
                        await sem.acquire()
                except BaseException:
                    self._global_sem.release()
                    raise
        except TimeoutError as exc:
            raise LlmSaturated(
                "等待并发位超过 20s（07 §10.1 排队上限）",
                detail={"model": model, "wait_timeout_s": SEMAPHORE_WAIT_TIMEOUT_S},
            ) from exc

    def _release(self, model: str) -> None:
        sem = self._model_sem.get(model)
        if sem is not None:
            sem.release()
        self._global_sem.release()

    async def _attempt(
        self, *, model: str, wire_body: Mapping[str, Any], remaining: float
    ) -> Completion:
        await self._acquire(model)
        t0 = self._monotonic()
        try:
            async with asyncio.timeout(remaining):
                resp = await self._client.post(
                    "/chat/completions",
                    json=dict(wire_body),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except TimeoutError as exc:
            raise LlmTimeout(
                "上游调用超时（传输 deadline 耗尽）",
                detail={"model": model, "remaining_s": round(remaining, 3)},
            ) from exc
        except httpx.HTTPError as exc:
            # 网络层故障归入上游错误（可重试）；**不把异常文本带出去**（可能含 URL/主机名）
            raise LlmUpstreamError(
                "上游连接失败", detail={"model": model, "kind": type(exc).__name__}
            ) from exc
        finally:
            self._release(model)

        latency_ms = int((self._monotonic() - t0) * 1000)
        return self._parse(resp, model=model, latency_ms=latency_ms)

    def _parse(self, resp: httpx.Response, *, model: str, latency_ms: int) -> Completion:
        if resp.status_code == 429:
            raise LlmConcurrencyExceeded(
                "上游返回 429（并发连接数超限）",
                detail={"model": model, "status": 429, "retry_after": resp.headers.get("retry-after")},
            )
        if resp.status_code >= 500:
            raise LlmUpstreamError(
                "上游返回 5xx", detail={"model": model, "status": resp.status_code}
            )
        if resp.status_code >= 400:
            # 🔴 只取上游的**结构化错误标识**，**绝不把 message 带出去** ——
            #    实测上游 400 的 message 会回显我们 prompt 里的原文片段
            #    （例如 "Prompt must contain the word 'json'"），把它写进日志或
            #    用户可见响应等于自建一条出站回流通道（N-12 的反向）。
            err_type = err_code = None
            try:
                body = resp.json()
                err = body.get("error") if isinstance(body, dict) else None
                if isinstance(err, dict):
                    err_type = err.get("type")
                    err_code = err.get("code")
            except Exception:
                pass  # 解析失败不影响"这仍然是个 4xx"这个结论
            raise LlmUpstreamError(
                "上游拒绝请求（4xx）",
                detail={
                    "model": model, "status": resp.status_code,
                    "upstream_type": err_type, "upstream_code": err_code,
                },
            )

        try:
            body = resp.json()
            choice = body["choices"][0]["message"]
            content = choice.get("content") or ""
            usage_raw = body.get("usage") or {}
        except Exception as exc:
            raise LlmUpstreamError(
                "上游响应结构不可解析", detail={"model": model, "kind": type(exc).__name__}
            ) from exc

        reasoning = choice.get("reasoning_content") or ""

        if not content.strip():
            # 🔴 实测故障模式：思考模式下 max_tokens 被 reasoning 吃光，HTTP 200 但 content 为空。
            #    不拦它会拿到"空 SQL / 空结论"，且调用方无从判断。
            raise LlmEmptyContent(
                "上游返回 200 但 content 为空（思考模式吃光了 max_tokens）",
                detail={
                    "model": model,
                    "reasoning_chars": len(reasoning),
                    "completion_tokens": usage_raw.get("completion_tokens"),
                },
            )

        cache_hit = self._cache_hit_tokens(usage_raw)
        prompt_tokens = int(usage_raw.get("prompt_tokens") or 0)
        completion_tokens = int(usage_raw.get("completion_tokens") or 0)
        total_tokens = int(usage_raw.get("total_tokens") or (prompt_tokens + completion_tokens))

        return Completion(
            text=content,  # ★ 只带 content；reasoning_content 到此为止（见模块 docstring §4）
            model=str(body.get("model") or model),
            tokens=TokenUsage(
                input=prompt_tokens,
                output=completion_tokens,
                cache_hit=cache_hit,
                total=total_tokens,
            ),
            raw_usage={k: v for k, v in usage_raw.items() if isinstance(v, (int, float, str))},
            latency_ms=latency_ms,
            reasoning_chars=len(reasoning),
        )

    @staticmethod
    def _cache_hit_tokens(usage_raw: Mapping[str, Any]) -> int:
        """取"前缀缓存命中"的输入 token 数。

        实测（2026-09-17）上游**同时**给了两种写法：
        `usage.prompt_cache_hit_tokens`（DeepSeek 专有）与
        `usage.prompt_tokens_details.cached_tokens`（OpenAI 兼容）。
        优先用前者，缺则退后者，都没有就 0 —— `cache_hit` 是 NFR-4.3 命中率的唯一数据源，
        取不到时必须**如实是 0**，不得用别的量近似（近似会让命中率指标变成假数）。
        """
        v = usage_raw.get("prompt_cache_hit_tokens")
        if isinstance(v, int):
            return v
        details = usage_raw.get("prompt_tokens_details")
        if isinstance(details, Mapping):
            cached = details.get("cached_tokens")
            if isinstance(cached, int):
                return cached
        return 0
