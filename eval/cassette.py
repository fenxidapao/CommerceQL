"""LLM 录制/回放匣带（§17.2 的"可复现评测"底座）。

归属窗口：W6（docs/08 §4.1：`eval/**` 的**执行器**部分）。

--------------------------------------------------------------------------
一、挂在哪：`ChatClient(transport=…)` 这一个缝
--------------------------------------------------------------------------
`app.llm.client.ChatClient` 的构造参数里有 `transport: httpx.AsyncBaseTransport | None`
（W3A 为 `respx` 测试留的口子）。本模块**只**实现一个 httpx 传输层，因此：

· prompt 组装、出站白名单（`egress_guard`）、路由、退避重试、熔断、计量、
  JSON schema 校验、repair 循环 —— **全部是在线代码**（ADR-18 的复用面）；
· 匣带看到的就是真正出网的 HTTP 报文，不存在"评测专用的第二套 LLM 调用逻辑"。

⚠️ 记录粒度 = **一次 HTTP 请求/响应**，不是"一次 LLM 语义调用"：
`ChatClient` 的重试会产生多条报文，每条各占一格（回放时按 key 命中同一条）。

--------------------------------------------------------------------------
二、key = 报文指纹，**故意做得很紧**
--------------------------------------------------------------------------
`sha256(url.path + canonical_json(body))`。紧的后果是**会 miss**，而 miss 是这里
唯一诚实的行为：

· prompt 版本变了 → 指纹变 → miss（而不是拿旧答案假装新 prompt 的结果）；
· 时间语义里的"今天"变了 → 指纹变 → miss。
  ⚠️ 这意味着**匣带不跨日历日复用**：跨日复跑必须重新录制。
  这是刻意的 —— 评测口径里"昨天的时间范围"是一个会漂移的量（附录 B 的
  `time_basis`），拿旧报文回放会把它伪装成常量。

miss 时抛 `CassetteMiss`（**不**降级、**不**回退到真网络、**不**编造响应）。
调用方（`eval/runner.py`）把它记成 `unscored(基础设施)`，绝不计入模型失败率。

--------------------------------------------------------------------------
三、密钥与 PII
--------------------------------------------------------------------------
只记录 **URL path + 请求体 + 响应体**；请求头（含 `Authorization`）
**永不入带**。响应体是模型输出（不含真实用户数据 —— 沙箱是合成数据）。
匣带因此可以进 Git，但 `reports/` 里不得复制其内容中的题目文本以外的东西。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

import httpx

__all__ = ["CassetteMiss", "CassetteTransport", "MODES"]

Mode = Literal["record", "replay"]
MODES: Final[tuple[str, ...]] = ("record", "replay")


class CassetteMiss(RuntimeError):
    """回放未命中（fail-fast）—— 详见模块 docstring §二。"""


def request_key(path: str, body: bytes) -> str:
    """报文指纹。body 非 JSON 时退回**原文**参与哈希（不猜、不丢信息）。"""
    try:
        parsed = json.loads(body.decode("utf-8"))
        canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        canonical = body.decode("utf-8", errors="replace")
    payload = f"{path}\n{canonical}".encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class CassetteTransport(httpx.AsyncBaseTransport):
    """`record`（真打上游并落盘）/ `replay`（只读匣带，miss 即抛）两种模式。

    ⚠️ `record` 模式下 `upstream` 必填（默认 `httpx.AsyncHTTPTransport()`）；
    `replay` 模式下**绝不**构造 upstream —— 这样"以为在回放、其实偷偷出网"
    在结构上不可能发生（而不是靠调用方自觉）。
    """

    def __init__(
        self,
        *,
        mode: Mode,
        path: str | Path,
        upstream: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"未知匣带模式：{mode!r}（合法：{MODES}）")
        self._mode: Mode = mode
        self._path = Path(path)
        self._records: dict[str, dict[str, Any]] = {}
        self._dirty = 0
        self.calls: list[str] = []  # 命中顺序（报告侧统计"这次跑用了几次 LLM 调用"）
        self.misses = 0
        if mode == "record":
            self._upstream = upstream or httpx.AsyncHTTPTransport()
        else:
            self._upstream = None
            self._load()

    # -- 磁盘格式：JSONL（一行一条，便于 diff 与流式写） ---------------------

    def _load(self) -> None:
        if not self._path.is_file():
            raise FileNotFoundError(
                f"回放匣带不存在：{self._path}（先用 mode='record' 跑一次录制）"
            )
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                self._records[rec["key"]] = rec

    def save(self) -> int:
        """把本次新增记录追加落盘（record 模式），返回文件内总条数。

        幂等：同 key 覆盖；**不**重写既有行以外的内容，避免整带哈希抖动。
        """
        if self._mode != "record":
            return len(self._records)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, dict[str, Any]] = {}
        if self._path.is_file():
            with self._path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        existing[rec["key"]] = rec
        existing.update(self._records)
        with self._path.open("w", encoding="utf-8") as fh:
            for rec in existing.values():
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        self._dirty = 0
        return len(existing)

    @property
    def recorded_count(self) -> int:
        return len(self._records)

    # -- httpx 传输层 ------------------------------------------------------

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = request.content  # ChatClient 发的是内存里的 JSON body，无需 await read
        key = request_key(request.url.path, body)
        self.calls.append(key)

        if self._mode == "replay":
            rec = self._records.get(key)
            if rec is None:
                self.misses += 1
                raise CassetteMiss(
                    f"匣带未命中（{self._path.name}）：key={key[:23]}… "
                    "miss 通常是 prompt/时间语义变了 —— 重新录制，不要在评测里回退到真网络"
                )
            return _to_response(request, rec)

        assert self._upstream is not None, "record 模式必须有 upstream"
        response = await self._upstream.handle_async_request(request)
        content = await response.aread()
        self._records[key] = {
            "key": key,
            "path": request.url.path,
            "request": _json_or_text(body),
            "status": response.status_code,
            "response": _json_or_text(content),
        }
        self._dirty += 1
        return httpx.Response(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=content,
            extensions={"request": request},
        )

    async def aclose(self) -> None:
        if self._upstream is not None:
            await self._upstream.aclose()


def _json_or_text(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"__text__": raw.decode("utf-8", errors="replace")}


def _to_response(request: httpx.Request, rec: Mapping[str, Any]) -> httpx.Response:
    payload = rec.get("response")
    content = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if not (isinstance(payload, Mapping) and "__text__" in payload)
        else str(payload["__text__"]).encode("utf-8")
    )
    return httpx.Response(
        status_code=int(rec.get("status", 200)),
        headers={"content-type": "application/json"},
        content=content,
        extensions={"request": request},
    )
