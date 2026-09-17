"""LLM 测试共用的**假上游**：记录出站请求 + 返回脚本化响应。

为什么不用 `respx` 而是 `httpx.MockTransport`：本项目的关键断言是
**"发出去的那个字节流是什么"**（DoD③：录制出站 payload 并逐键核对白名单）。
`MockTransport` 把 `httpx.Request` 原样交给回调，`request.content` 就是**线缆上的字节**——
没有中间层可以做手脚，也不需要理解 patch 的生效范围。
（`respx` 也在候选里，但它解决的是"路由到不同 URL"，本项目只有一个 URL。）

⚠️ 这个文件**刻意不放在 `conftest.py`**：它只在 LLM 相关测试里用，
放全局会让不关心 LLM 的测试也背上这份导入。
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

__all__ = [
    "FakeUpstream",
    "Responder",
    "ok_body",
    "error_body",
    "json_ok",
    "json_error",
]


def ok_body(
    *,
    content: str = '{"sql": "SELECT 1"}',
    model: str = "deepseek-flash",
    prompt_tokens: int = 120,
    completion_tokens: int = 30,
    cache_hit_tokens: int | None = 0,
    cached_tokens: int | None = None,
    reasoning_content: str = "",
    total_tokens: int | None = None,
    include_prompt_cache_hit: bool = True,
) -> dict[str, Any]:
    """构造一个 OpenAI 兼容的成功响应体（字段名照**实测**的上游回包写）。"""
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": (
            total_tokens if total_tokens is not None else prompt_tokens + completion_tokens
        ),
    }
    if include_prompt_cache_hit and cache_hit_tokens is not None:
        usage["prompt_cache_hit_tokens"] = cache_hit_tokens
    if cached_tokens is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning_content,
                },
            }
        ],
        "usage": usage,
    }


def error_body(
    *, message: str = "bad request", err_type: str | None = None, code: str | None = None
) -> dict[str, Any]:
    err: dict[str, Any] = {"message": message}
    if err_type is not None:
        err["type"] = err_type
    if code is not None:
        err["code"] = code
    return {"error": err}


def json_ok(**kwargs: Any) -> httpx.Response:
    return httpx.Response(200, json=ok_body(**kwargs))


def json_error(status: int, **kwargs: Any) -> httpx.Response:
    headers = {}
    if status == 429:
        headers["retry-after"] = "1"
    return httpx.Response(status, json=error_body(**kwargs), headers=headers)


#: 回调签名：`(第几次调用从 0 起, 原始 request) -> response`（也可以返回协程）
Responder = Callable[[int, httpx.Request], "httpx.Response | Awaitable[httpx.Response]"]


def _default_responder(index: int, request: httpx.Request) -> httpx.Response:
    _ = (index, request)
    return json_ok()


class FakeUpstream:
    """可记录、可脚本化的假上游。

    用法：

        upstream = FakeUpstream(lambda i, req: json_ok() if i == 0 else json_error(429))
        client = ChatClient(..., transport=upstream.transport)
        ...
        assert upstream.sent == 2
        assert upstream.calls[0]["thinking"] == {"type": "disabled"}
    """

    def __init__(self, responder: Responder | None = None) -> None:
        self._responder: Responder = responder or _default_responder
        #: 每次出站的**请求体**（已 `json.loads`）—— DoD③ 的核对对象
        self.calls: list[dict[str, Any]] = []
        #: 每次出站的原始 `httpx.Request`（拷 headers 用）
        self.raw_calls: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(json.loads(request.content))
        self.raw_calls.append(request)
        result = self._responder(len(self.calls) - 1, request)
        # 允许回调是协程：并发观测与超时测试需要"响应**还没**返回"这个中间态。
        if inspect.isawaitable(result):
            result = await result
        return result

    @property
    def sent(self) -> int:
        """已发出的请求数（**"没发请求"也要能被断言**，故不能只看成功次数）。"""
        return len(self.calls)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def all_sent_text(self) -> str:
        """所有出站请求体的拼串 —— 用于"某个串**从未**出站"这类否定断言。"""
        return json.dumps(self.calls, ensure_ascii=False, default=str)

    def assert_close(self) -> None:
        """无连接资源可关（`MockTransport` 是纯内存的）—— 保留只为调用侧对称。"""
