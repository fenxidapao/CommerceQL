#!/usr/bin/env python3
"""CommerceQL 压测驱动（07 §16.5 四场景）—— W7 自有，零新增依赖。

为什么不用 k6 / locust
----------------------
§16.5 说"二者皆可"，但本机两者都**没装**（2026-09-18 实测 `command -v k6/locust` 皆空），
装它们要动 dev 依赖 = 改 `pyproject` = 撞别的窗口。`httpx` 已是应用依赖，
而 §16.5 真正要的是**客户端能解析 SSE 的 `terminal` 判据**（附录 A §A.1.4）——
那是通用压测工具的弱项（它们按 HTTP 状态码计时，SSE 的 200 在"刚开始"就返回，
于是测出来的是 TTFB 而不是端到端延迟，**看着达标其实测错了对象**）。

测的是什么时间
--------------
每条请求记录两个数，缺一都会让 G-6 变成假的：

· ``ttfb_ms``   —— 请求发出到**第一帧**。快，但不含结果生成。
· ``total_ms``  —— 请求发出到**终止帧**（``data.terminal is true``）或异常收流。
  ⚠️ 默认 ``options.async_if_slow=true`` + ``async_threshold_ms=8000``：慢查询会**转异步**并
  正常终止这条流 ⇒ 只看 ``total_ms`` 的 P95 会因为"到点就转异步"而**天然 ≤8s**。
  那不等于达标。所以本驱动把 `转异步而终止` 单列成 ``async_degraded`` 一类，
  要求跑批时**同时**给 ``--no-async`` 跑一遍（拿真实端到端）或以轮询补完时间另计。

退出码：0 = 跑完并落了回执；2 = 参数/环境不满足（不猜测、不静默降级）；3 = 自检失败。

用法见同目录 ``README.md``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SCHEMA_VERSION = "w7.loadtest.receipt/1"
TERMINAL_EVENT_MAX_WAIT_S = 600.0  # 兜底：流开了但迟迟不给终止帧
QUESTION_POOL_DEFAULT = 5  # 轮转题库条数（见 --questions-file）


# ---------------------------------------------------------------------------
# 采样与单条请求
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Sample:
    """一条虚拟请求的观测。``outcome`` 的取值就是回执里的错误分类，别再新增同义项。"""

    outcome: str  # ok | clarify | refuse | error_frame | async_degraded | http_4xx | http_5xx | timeout | conn_error | truncated
    status: int | None
    ttfb_ms: float | None
    total_ms: float | None
    frames: int = 0
    code: str | None = None
    detail: str | None = None
    msg: str | None = None  # 终止 error 帧的 message ⇒ 区分"业务内部错误"与"drain 注入的停机帧"
    # ⚠️ 这两个字段是为了回答一个 `outcomes` 答不了的问题：一条 clarify/refuse **是哪个节点说的**。
    #    `reason="no_data_asset"` 这个字符串同时是 intent 层的产物和 §5.3 给 `link` 的"空召回"落点
    #    ⇒ 只看 reason 分不出来源，必须把"终止前最后一个 stage 帧"一起记下来。
    last_stage: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class ScenarioSpec:
    name: str
    concurrency: int
    duration_s: float | None  # None = 按 total_requests 收口
    total_requests: int | None
    single_session: bool  # 场景③：所有请求共用一个 session_id（验串行锁）
    one_tenant: bool  # 场景④：同租户（配额桶）


def scenario_specs(only: str | None) -> list[ScenarioSpec]:
    """07 §16.5 的四场景默认参数。``--scenario`` 给名字时只跑那一条。"""
    specs = [
        ScenarioSpec("steady", 50, 600.0, None, False, False),
        ScenarioSpec("burst", 100, 30.0, None, False, False),
        ScenarioSpec("session-lock", 8, None, 24, True, False),
        ScenarioSpec("tenant-quota", 30, None, 60, False, True),
    ]
    if only is None:
        return specs
    return [s for s in specs if s.name == only]


async def create_session(client: httpx.AsyncClient, base: str, token: str) -> str:
    """建一个**真实**会话并返回 id。

    ⚠️ 不能凭空编一个 `session_id` 塞给 `POST /query`：实测 24/24 全部
    `400 {"code":"SESSION_NOT_FOUND"}`（会话由 `POST /session` 铸造，§A.5.1）。
    那样跑出来的"串行锁测试"其实什么都没测 —— 一条都没进到锁上。
    """
    resp = await client.post(f"{base.rstrip('/')}/session", json={},
                             headers={"Authorization": f"Bearer {token}"})
    sid = _dig(resp.json(), "session_id") if resp.status_code == 200 else None
    if not sid:
        raise SystemExit(f"[中止] 建会话失败：HTTP {resp.status_code} {resp.text[:120]}\n"
                         "  ⇒ 场景③/复用会话都依赖它，先修这条再谈压测")
    return str(sid)


def _dig(obj: Any, key: str) -> Any:
    """在响应信封里递归找第一个 `key`（附录 A 的 `data` 层级不该由压测端硬编码假设）。"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _dig(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _dig(value, key)
            if found is not None:
                return found
    return None


async def fire_one(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    question: str,
    session_id: str | None,
    *,
    async_if_slow: bool,
) -> Sample:
    """发一条 ``POST /query`` 并按 SSE 语义计时。

    ⚠️ 不读 body 到终止帧就返回 = 测出来的是"服务器开始说话"，不是"用户拿到答案"。
    ⚠️ 也不看 ``status`` 就判 ok：`terminal: true` 才是唯一判据（附录 A §A.1.4），
       而 ``event: error`` 带终止帧的 HTTP 仍是 200 —— 用状态码判成功会把失败算成达标。
    """
    payload: dict[str, Any] = {
        "question": question,
        "session_id": session_id,
        "options": {"async_if_slow": async_if_slow},
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    start = time.perf_counter()
    ttfb: float | None = None
    event_name: str | None = None
    terminal: str | None = None
    last_stage: str | None = None
    frames = 0
    # 先绑一个空 dict：`terminal is None` 那条出口（流里一条 data 帧都没有）也要读 `data`，
    # 不初始化就是 UnboundLocalError —— 而那条出口恰恰是"什么都没收到"时最该走到的地方。
    data: dict[str, Any] = {}
    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            status = resp.status_code
            if status >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")[:200]
                kind = "http_4xx" if status < 500 else "http_5xx"
                return Sample(kind, status, None, _ms(start), 0, detail=_code_of(body) or body)
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                frames += 1
                if ttfb is None:
                    ttfb = _ms(start)
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    return Sample("truncated", status, ttfb, _ms(start), frames,
                                  detail="data 帧不是 JSON", last_stage=last_stage)
                if data.get("terminal") is not True:
                    if event_name == "stage" and isinstance(data.get("stage"), str) and data["stage"]:
                        last_stage = str(data["stage"])
                    continue
                terminal = event_name or str(data.get("type") or "")
                break
    except httpx.TimeoutException:
        return Sample("timeout", None, ttfb, _ms(start), frames,
                      detail=f">{TERMINAL_EVENT_MAX_WAIT_S}s 未收到终止帧", last_stage=last_stage)
    except (httpx.HTTPError, OSError) as exc:
        return Sample("conn_error", None, ttfb, _ms(start), frames,
                      detail=f"{type(exc).__name__}", last_stage=last_stage)

    total = _ms(start)
    reason = data.get("reason") if isinstance(data.get("reason"), str) else None
    if terminal is None:
        # 流正常结束却没有终止帧：这是 N-08 违约，不是"成功"。
        return Sample("truncated", status, ttfb, total, frames,
                      detail="流结束但无 terminal=true 帧", last_stage=last_stage)
    if terminal == "error":
        return Sample("error_frame", status, ttfb, total, frames,
                      code=str(data.get("code")), msg=str(data.get("message") or "")[:60],
                      last_stage=last_stage, reason=reason)
    if terminal == "complete":
        if data.get("async") or data.get("task_id"):
            return Sample("async_degraded", status, ttfb, total, frames,
                          detail="超阈值转异步，端到端未在此流内完成", last_stage=last_stage)
        return Sample("ok", status, ttfb, total, frames, last_stage=last_stage)
    if terminal == "clarify":
        return Sample("clarify", status, ttfb, total, frames, last_stage=last_stage, reason=reason)
    if terminal == "refuse":
        return Sample("refuse", status, ttfb, total, frames, last_stage=last_stage, reason=reason)
    return Sample("truncated", status, ttfb, total, frames,
                  detail=f"未知终止事件 {terminal}", last_stage=last_stage)


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _code_of(body: str) -> str | None:
    for marker in ("SESSION_CONFLICT", "IDEMPOTENCY_CONFLICT", "RATE_LIMITED", "UNAUTHENTICATED"):
        if marker in body:
            return marker
    return None


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------


async def run_spec(spec: ScenarioSpec, args: argparse.Namespace, questions: list[str]) -> dict[str, Any]:
    url = f"{args.target.rstrip('/')}/query"
    limits = httpx.Limits(max_connections=spec.concurrency, max_keepalive_connections=spec.concurrency)
    timeout = httpx.Timeout(args.request_timeout_s)
    samples: list[Sample] = []
    lock = asyncio.Lock()
    next_index = 0
    opened = time.perf_counter()
    # ⚠️ 成本安全阀：真实跑批每条请求都花额度，而"跑满 10min"的失控形态是
    #    服务越慢 ⇒ 每条越久 ⇒ 到时间前发出的并发数不减。`--max-requests` 给一个**硬上限**，
    #    到数就停 —— 宁可不跑满口径，也不能让一个脚本花光预算。
    hard_cap = spec.total_requests
    if args.max_requests:
        hard_cap = min(hard_cap, args.max_requests) if hard_cap else args.max_requests

    async def worker(client: httpx.AsyncClient, token: str) -> None:
        nonlocal next_index
        while True:
            if spec.duration_s is not None and time.perf_counter() - opened >= spec.duration_s:
                return
            async with lock:
                if hard_cap is not None and next_index >= hard_cap:
                    return
                i = next_index
                next_index += 1
            sid = session_pool[0] if spec.single_session else (
                session_pool[i % len(session_pool)] if session_pool else None
            )
            sample = await fire_one(
                client, url, token, questions[i % len(questions)], sid,
                async_if_slow=not args.no_async,
            )
            samples.append(sample)

    async with httpx.AsyncClient(limits=limits, timeout=timeout, http2=False) as client:
        tokens = await _tokens_for(args, spec)
        session_pool: list[str] = []
        if spec.single_session:
            # 场景③要的就是"同一个会话上并发" ⇒ 只建**一个**真会话，24 条全打上去
            session_pool = [await create_session(client, args.target, tokens[0])]
        elif args.reuse_sessions:
            session_pool = [await create_session(client, args.target, tokens[j % len(tokens)])
                            for j in range(max(1, args.session_pool))]
        workers = [asyncio.create_task(worker(client, tokens[i % len(tokens)])) for i in range(spec.concurrency)]
        await asyncio.gather(*workers)

    wall = time.perf_counter() - opened
    return _summarize(spec, samples, wall, args)


async def _tokens_for(args: argparse.Namespace, spec: ScenarioSpec) -> list[str]:
    """租户配额场景需要**多用户同租户**；其余场景一枚令牌就够。"""
    if args.tokens:
        return [t.strip() for t in Path(args.tokens).read_text(encoding="utf-8").split() if t.strip()]
    single = os.environ.get("COMMERCEQL_DEV_TOKEN", "")
    if not single:
        msg = (
            "没有令牌：设 COMMERCEQL_DEV_TOKEN 或 --tokens <file>。\n"
            "  签发：cd backend && python scripts/mint_dev_token.py --tenant-id tenant_a --role analyst"
        )
        raise SystemExit(f"{msg}\n[拒绝猜测默认凭据]")
    return [single]


def _summarize(spec: ScenarioSpec, samples: list[Sample], wall_s: float, args: argparse.Namespace) -> dict[str, Any]:
    totals = sorted(s.total_ms for s in samples if s.total_ms is not None)
    ttfbs = sorted(s.ttfb_ms for s in samples if s.ttfb_ms is not None)
    # 先算一次：`_pct` 返回 `float | None`，连调两次 mypy 收窄不了（而且同一分位数算两遍没意义）。
    p95_total = _pct(totals, 95)
    by_outcome: dict[str, int] = {}
    for s in samples:
        by_outcome[s.outcome] = by_outcome.get(s.outcome, 0) + 1
    return {
        "scenario": spec.name,
        "params": {
            "concurrency": spec.concurrency,
            "duration_s": spec.duration_s,
            "total_requests": spec.total_requests,
            "single_session": spec.single_session,
            "same_tenant": spec.one_tenant,
            "async_if_slow": not args.no_async,
            "questions": args.questions_file or f"合成题库 {QUESTION_POOL_DEFAULT} 条轮转",
            # 有上限的跑批必须在**场景级**可见，否则"300 条"看着像"跑满了 10min"。
            "request_cap": (min(spec.total_requests, args.max_requests)
                            if spec.total_requests and args.max_requests
                            else (spec.total_requests or args.max_requests)),
        },
        "requests": len(samples),
        "wall_s": round(wall_s, 3),
        "throughput_rps": round(len(samples) / wall_s, 3) if wall_s > 0 else None,
        "latency_ms": {"p50": _pct(totals, 50), "p95": p95_total, "p99": _pct(totals, 99),
                       "max": round(totals[-1], 1) if totals else None,
                       "mean": round(statistics.fmean(totals), 1) if totals else None},
        "ttfb_ms": {"p50": _pct(ttfbs, 50), "p95": _pct(ttfbs, 95)},
        "outcomes": by_outcome,
        "codes": _codes(samples),
        # 谁能回答"这条 refuse 是 intent 说的还是 link 说的"：`outcomes` 与 `reason` 单独都答不了。
        "terminal_provenance": _provenance(samples),
        # drain 证据只能靠 message 分家：光看 `error_frame` 数会把"停机注入"和"节点超时"混成一坨。
        "drain_frames": sum(1 for s in samples if s.msg and "重启" in s.msg),
        "error_messages": _messages(samples),
        # G-6 只看 total_ms 的 p95；⚠️ 这个布尔位**单独读没有意义**，必须与 `g6_caveat` 同读
        #    （0 条完成时 p95 也可以 ≤8s —— 那正是假绿灯的形状，见 `_g6_caveat` 的文档）。
        "g6_p95_le_8s": (p95_total is not None and p95_total <= 8000.0),
        "g6_caveat": _g6_caveat(by_outcome),
    }


def _g6_caveat(by_outcome: dict[str, int]) -> str | None:
    """这份 P95 **能不能**拿来判 G-6 达标 —— 必须是机器可读的，不能只在散文里警告。

    为什么这条要单独抽出来：下游 W6 的 `eval/reporter.loadtest_pressure()` 取的是
    "各场景 `latency_ms.p95` 的最大值"，并且**只通过 `g6_caveat` 是否非空**来降档 ——
    它不读 `outcomes`。于是 2026-09-19 那种"0 条完成、但 error 帧收得很快"的跑批
    （p95 = 7268ms ≤ 8000ms）会被**机械地判成 G-6 PASS**。分母里没有一次成功。
    ⇒ 凡是"这条 P95 不代表真实完成延迟"的情形，都必须在这里落一句非空文本。
    """
    notes: list[str] = []
    completed = by_outcome.get("ok", 0)
    if not completed:
        notes.append("本场景 0 条真正完成（outcome=ok）⇒ P95 的分母全是失败/降级样本，不可判达标")
    async_degraded = by_outcome.get("async_degraded", 0)
    if async_degraded:
        notes.append(f"含 {async_degraded} 条 async_degraded（超阈值转异步）⇒ 端到端未在此流内完成，P95 偏低")
    return "；".join(notes) if notes else None


def _messages(samples: list[Sample]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in samples:
        if s.msg:
            out[s.msg] = out.get(s.msg, 0) + 1
    return out


def _codes(samples: list[Sample]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in samples:
        if s.code:
            out[s.code] = out.get(s.code, 0) + 1
        elif s.outcome in {"http_4xx", "http_5xx"} and s.detail:
            out[s.detail[:48]] = out.get(s.detail[:48], 0) + 1
    return out


def _provenance(samples: list[Sample]) -> dict[str, dict[str, int]]:
    """终止事件的**来源指纹**：`outcome` → {"stage=<终止前最后一个 stage>|reason=<终止帧自带 reason>"} → 条数。

    存在的理由是一个 `outcomes` + `codes` 都答不了的问题：一条 `refuse(reason=no_data_asset)`
    既可能是 intent 层给的（07 §5.2 组 3），也可能是 `link` 的空召回（§5.3）—— 两个落点共用同一个
    4 值枚举。把"终止前最后一个 `stage` 帧"一起记下来才能分家。
    ⚠️ 读法：`stage=none` 表示**一条 stage 帧都没收到**（不是"数据丢了"），这本身就是信息 ——
    例如全部终止都停在 `stage=none` ⇒ 破在第一个发 stage 帧的节点之前。
    """
    out: dict[str, dict[str, int]] = {}
    for s in samples:
        key = f"stage={s.last_stage or 'none'}|reason={s.reason or 'none'}"
        bucket = out.setdefault(s.outcome, {})
        bucket[key] = bucket.get(key, 0) + 1
    return out


def _pct(sorted_values: list[float], p: int) -> float | None:
    """最近秩百分位（不用 ``quantile`` 的插值：压测要报的是**真实某一条**的耗时）。"""
    if not sorted_values:
        return None
    rank = max(1, -(-p * len(sorted_values) // 100))
    return round(sorted_values[min(rank, len(sorted_values)) - 1], 1)


# ---------------------------------------------------------------------------
# 自检：证明的是**量具**，不是被测系统
# ---------------------------------------------------------------------------


async def self_check() -> int:
    """对内置桩服务跑四场景的微缩版，断言量具本身读数正确。

    桩**不碰 Docker、不碰网络、不花额度**（``httpx.ASGITransport``），
    所以这条回执在任何机器上可复现。它证明的是：
    ① 已知延迟分布下 p50/p95/p99 落在预期区间；② ``terminal`` 判据被真的用到
    （桩故意在 200 流里发非终止帧再发终止帧）；③ 409/429 分类不错并成"成功"。
    它**不证明** CommerceQL 的 P95 —— 那需要真实栈（README §三）。
    """

    scripted: list[tuple[str, float]] = [
        ("ok", 120.0), ("ok", 400.0), ("clarify", 60.0), ("error", 30.0),
        ("http409", 0.0), ("http429", 0.0), ("async", 2600.0), ("ok", 3000.0),
        ("truncated", 50.0), ("ok", 800.0),
    ]
    cursor = {"i": 0}

    async def stub(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        path = scope["path"]
        if not path.endswith("/query"):
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})
            return
        i = cursor["i"] % len(scripted)
        cursor["i"] += 1
        kind, delay_ms = scripted[i]
        if kind == "http409":
            await _json_reply(send, 409, '{"detail":{"code":"SESSION_CONFLICT"}}')
            return
        if kind == "http429":
            await _json_reply(send, 429, '{"detail":{"code":"RATE_LIMITED"}}')
            return
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        # ⚠️ 首帧**必须单独一条 body 消息**发出去，延迟在首帧**之后**才睡：
        #    若把首帧和终止帧拼成一条，TTFB 就约等于 total，于是"计时停在第一帧"
        #    这类量具缺陷在这条自检里**测不出来**（变异实测漏判）。
        await send({"type": "http.response.body",
                    "body": b'event: stage\ndata: {"terminal": false, "stage": "schema_linking"}\n\n',
                    "more_body": True})
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
        if kind == "truncated":
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        body: dict[str, Any] = {"terminal": True}
        if kind == "error":
            body["code"] = "INTERNAL"
        if kind == "clarify":
            body["reason"] = "time_ambiguous"
        if kind == "async":
            body["task_id"] = "t_stub"
        name = {"ok": "complete", "clarify": "clarify", "error": "error", "async": "complete"}[kind]
        frame = f"event: {name}\ndata: {json.dumps(body)}\n\n".encode()
        await send({"type": "http.response.body", "body": frame, "more_body": False})

    # ⚠️ 走**真 TCP 环回**而不是 ASGITransport：后者把响应体先攒成 `body_parts` 再整体交回
    #    （httpx 0.28 `_transports/asgi.py:158-185`），于是任何"逐帧增量"的判据都被抹平 ——
    #    实测 TTFB == total，"计时停在第一帧"的变异**当场漏判**。量具要能分辨两帧，
    #    被测面就必须真的分帧发。uvicorn 是本应用自己的依赖 ⇒ 自检不新增依赖。
    server, serve_task, base_url = await _serve_on_loopback(stub)
    client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(30.0))
    questions = ["自检题库"]
    got: list[Sample] = []
    try:
        for _ in range(len(scripted)):
            got.append(await fire_one(client, "/api/v1/query", "tok", questions[0], None, async_if_slow=True))
    finally:
        await client.aclose()
        server.should_exit = True
        await serve_task
    outcomes = [s.outcome for s in got]
    want = ["ok", "ok", "clarify", "error_frame", "http_4xx", "http_4xx",
            "async_degraded", "ok", "truncated", "ok"]
    print("自检读数:", outcomes)
    if outcomes != want:
        print(f"[自检失败] 期望 {want}", file=sys.stderr)
        return 3
    # 两条"到得晚才拿到终止帧"的样本：2600ms 那条是转异步出口的 complete，
    # 3000ms 那条是普通完成 —— 两者都必须被 total_ms 计到，否则说明计时停在了第一帧。
    slow = [s.total_ms for s in got if s.outcome in {"ok", "async_degraded"} and s.total_ms and s.total_ms > 2000]
    if len(slow) != 2:
        print("[自检失败] 慢样本未被计入 ⇒ total_ms 没测到终止帧", file=sys.stderr)
        return 3
    # ⚠️ 这条才是"计时对象"的正证：2600ms 那条转异步样本必须 **TTFB ≪ total**。
    #    没有它，`total = ttfb` 那种退化赋值照样通过上面的计数断言（变异实测漏判）。
    late = next(s for s in got if s.outcome == "async_degraded")
    if late.ttfb_ms is None or late.total_ms is None or late.ttfb_ms > 500 or late.total_ms < 2000:
        print(f"[自检失败] 计时对象错位：ttfb={late.ttfb_ms} total={late.total_ms}"
              "（期望首帧 <500ms、终止帧 >2000ms）", file=sys.stderr)
        return 3
    totals = sorted(s.total_ms for s in got if s.total_ms is not None)
    p95 = _pct(totals, 95)
    # 双向卡：10 条样本的最近秩 p95 = 最大那条 = 桩里 3000ms 的"普通完成"。
    # 只卡上界会让"p95 恒 0"这种坏掉的量具蒙混过关。
    if p95 is None or not 2000.0 < p95 <= 3300.0:
        print(f"[自检失败] 百分位计算异常：p95={p95}（期望落在 (2000, 3300]）", file=sys.stderr)
        return 3
    # `g6_caveat` 是**下游唯一的降档开关**（W6 的 `eval/reporter.loadtest_pressure()` 只读它、
    # 不读 `outcomes`）⇒ 它"假空"就等于把一份没有一次成功的 P95 判成 G-6 PASS。
    # 三种情形都必须测到，否则会静默退回旧行为。
    gate_cases: list[tuple[dict[str, int], bool]] = [
        ({"error_frame": 87, "http_5xx": 41, "http_4xx": 9, "clarify": 7, "refuse": 6}, True),
        ({"async_degraded": 12, "ok": 3}, True),
        ({"ok": 40, "clarify": 5}, False),
    ]
    for case_outcomes, want_caveated in gate_cases:
        if bool(_g6_caveat(case_outcomes)) != want_caveated:
            print(f"[自检失败] g6_caveat 判错：{case_outcomes} → {_g6_caveat(case_outcomes)!r}"
                  f"（期望{'非空' if want_caveated else 'None'}）", file=sys.stderr)
            return 3
    # 终止来源指纹：整字典相等（不是"包含"）。三件事各钉一处 ——
    # ① 非终止 `stage` 帧真的被记下来了（不是永远 none）；② `clarify` 的 reason 被记下来；
    # ③ 4xx 没有流 ⇒ 落成 `stage=none|reason=none`，"分辨不了"要显式可见而不是留空。
    prov = _provenance(got)
    want_prov = {
        "ok": {"stage=schema_linking|reason=none": 4},
        "clarify": {"stage=schema_linking|reason=time_ambiguous": 1},
        "error_frame": {"stage=schema_linking|reason=none": 1},
        "async_degraded": {"stage=schema_linking|reason=none": 1},
        "truncated": {"stage=schema_linking|reason=none": 1},
        "http_4xx": {"stage=none|reason=none": 2},
    }
    if prov != want_prov:
        print(f"[自检失败] 终止来源指纹不对：{prov}", file=sys.stderr)
        return 3
    print(f"[自检通过] 10/10 分类正确；样本 p95={p95}ms（桩注入的最大延迟 3000ms）；"
          f"g6_caveat 三情形（零完成/转异步/真有完成）判向正确；"
          f"terminal_provenance {sum(sum(v.values()) for v in prov.values())} 条指纹可读")
    return 0


async def _serve_on_loopback(app: Any) -> tuple[Any, asyncio.Task[Any], str]:
    """把一个裸 ASGI app 起在 127.0.0.1 的**随机端口**上，返回 (server, 任务, base_url)。

    只绑环回、只在这条自检的生命周期内存在、不对外网开放 ⇒ 与真实栈无关。
    """
    import uvicorn  # 只有自检路径需要，跑真实压测时不引这个

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, f"http://127.0.0.1:{port}"


async def _json_reply(send: Any, status: int, body: str) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body.encode(), "more_body": False})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SYNTHETIC_QUESTIONS = [
    "近 7 天各品类的销售额趋势如何？",
    "上个月复购率最高的 10 个店铺是哪些？",
    "本周客单价的环比变化是多少？",
    "近 30 天退款率最高的品类及金额",
    "各渠道新客占比与转化率对比",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CommerceQL §16.5 四场景压测驱动（W7）")
    p.add_argument("--target", default="http://127.0.0.1:8000/api/v1",
                   help="API 基址（含 /api/v1）。⚠️ 先确认该栈有 query 路由：docker exec <api> ls /srv/app/api/routers")
    p.add_argument("--scenario", choices=["steady", "burst", "session-lock", "tenant-quota"],
                   help="只跑一条；缺省跑全四条")
    p.add_argument("--questions-file", help="题库文件（一行一条）。⚠️ §16.5 要求合成数据集全量口径")
    p.add_argument("--no-async", action="store_true", help="置 options.async_if_slow=false，拿真实端到端")
    p.add_argument("--reuse-sessions", action="store_true", help="轮转复用 session（撞串行锁的正面用例）")
    p.add_argument("--session-pool", type=int, default=10)
    p.add_argument("--tokens", help="令牌文件（空白分隔）；同租户多用户场景用")
    p.add_argument("--request-timeout-s", type=float, default=TERMINAL_EVENT_MAX_WAIT_S)
    p.add_argument("--concurrency", type=int, help="覆盖场景默认并发（**降并发**用于找失败边界；调高属于加负载，先报告）")
    p.add_argument("--duration-s", type=float, help="覆盖场景默认时长（秒）")
    p.add_argument("--max-requests", type=int,
                   help="**成本硬上限**（每个场景）。真实额度跑批必给：到数就停，不跑满时长")
    p.add_argument("--out", default="receipt.json", help="结构化回执输出路径")
    p.add_argument("--self-check", action="store_true", help="只验量具（零外呼、零额度）")
    p.add_argument("--roll-up", nargs="+", metavar="RECEIPT",
                   help="**零外呼、零额度**：把已落盘的回执合成一份 --out（默认 receipt.json），"
                        "并按各自 outcomes 重算 g6_caveat（旧文件的 null 会让 G-6 假绿）")
    p.add_argument("--dry-run", action="store_true", help="打印将执行的场景参数后退出")
    return p


def roll_up(paths: list[str], out: str) -> int:
    """**不发包、不花额度**：把已有回执合成一份 `receipt.json`，顺手把 caveat 补算对。

    两件事缺一不可：
    ① 下游 W6 的读端只认一个路径（`deploy/loadtest/receipt.json`），而本目录按场景分文件存；
    ② 2026-09-19 之前写出的回执里 `g6_caveat` 是 `null`（那时它只看 `async_degraded`），
       直接喂给 W6 的"取 max(p95) + 无 caveat 即达标"口径 ⇒ **G-6 会被判成 PASS**，
       而那几轮其实是 0 条完成。⇒ 这里用**各场景自己已落盘的 `outcomes`** 重算，不引入任何新测量。
    """
    merged: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "mode": "roll-up",
        "note": ("本文件由已落盘的回执**合成**，没有重新发包。"
                 "`g6_caveat` 按各场景自带的 `outcomes` 重算（旧文件里为 null 会产生 G-6 假绿灯）。"
                 "回执只含耗时与状态分类，不含查询文本与结果数据（N-11 同源关注）"),
        "derived_from": [],
        "started_at": None,
        "finished_at": None,
        "target": None,
        "scenarios": [],
    }
    started: list[str] = []
    finished: list[str] = []
    for p in paths:
        raw = json.loads(Path(p).read_text(encoding="utf-8"))
        if raw.get("schema") != SCHEMA_VERSION:
            print(f"[中止] {p} 的 schema 是 {raw.get('schema')!r}，不是 {SCHEMA_VERSION!r} ⇒ 别混进同一份",
                  file=sys.stderr)
            return 2
        merged["target"] = merged["target"] or raw.get("target")
        if raw.get("started_at"):
            started.append(raw["started_at"])
        if raw.get("finished_at"):
            finished.append(raw["finished_at"])
        for s in raw.get("scenarios") or []:
            outcomes = s.get("outcomes") or {}
            old = s.get("g6_caveat")
            s["g6_caveat"] = _g6_caveat(outcomes)
            s["g6_caveat_recomputed"] = True
            merged["derived_from"].append({
                "file": Path(p).name, "scenario": s.get("scenario"),
                "requests": s.get("requests"),
                "ok": outcomes.get("ok", 0),
                "p95_ms": (s.get("latency_ms") or {}).get("p95"),
                "caveat_before": old,
                "caveat_after": s["g6_caveat"],
            })
            merged["scenarios"].append(s)
    merged["started_at"] = min(started) if started else None
    merged["finished_at"] = max(finished) if finished else None
    Path(out).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    changed = sum(1 for d in merged["derived_from"] if d["caveat_before"] != d["caveat_after"])
    print(f"[合成] {len(paths)} 份 → {out}：{len(merged['scenarios'])} 条场景，"
          f"其中 {changed} 条的 g6_caveat 由 null 补算为非空")

    # ⚠️ 光修合成件不够：W6 的读端支持 `--loadtest-receipt <路径>`，把**任意一份分场景回执**
    #    单独指过去，同样会因为 `g6_caveat` 是 null 而判 PASS。⇒ 输入文件也就地重算写回。
    #    只改 `g6_caveat` 这一个派生字段，读数（outcomes / latency / codes）一律不动。
    repaired = 0
    for p in paths:
        raw = json.loads(Path(p).read_text(encoding="utf-8"))
        touched = False
        for s in raw.get("scenarios") or []:
            fresh = _g6_caveat(s.get("outcomes") or {})
            if s.get("g6_caveat") != fresh:
                s["g6_caveat"] = fresh
                s["g6_caveat_recomputed"] = True
                touched = True
        if touched:
            Path(p).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            repaired += 1
    if repaired:
        print(f"[就地补算] {repaired} 份输入回执的 g6_caveat 已按各自 outcomes 重算写回"
              "（读数未动，仅补派生字段）")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_check:
        return asyncio.run(self_check())
    if args.roll_up:
        return roll_up(args.roll_up, args.out)

    specs = scenario_specs(args.scenario)
    for s in specs:  # 覆盖参数只动**要跑的那条**，且只允许把量调小或等量（调高要先报告，见 §五）
        if args.concurrency:
            s.concurrency = args.concurrency
        if args.duration_s:
            s.duration_s = args.duration_s
    if args.dry_run:
        for s in specs:
            print(f"{s.name}: 并发={s.concurrency} 时长={s.duration_s or '—'} "
                  f"总请求={s.total_requests or '—'} 单会话={s.single_session} 同租户={s.one_tenant}")
        return 0

    questions = SYNTHETIC_QUESTIONS
    if args.questions_file:
        lines = [x.strip() for x in Path(args.questions_file).read_text(encoding="utf-8").splitlines() if x.strip()]
        if not lines:
            print(f"[题库为空] {args.questions_file}", file=sys.stderr)
            return 2
        questions = lines

    receipt: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": args.target,
        "note": "回执只含耗时与状态分类，不含查询文本与结果数据（N-11 同源关注）",
        "scenarios": [],
    }
    try:
        for spec in specs:
            print(f"[{spec.name}] 并发 {spec.concurrency} 开始 …", flush=True)
            one = asyncio.run(run_spec(spec, args, questions))
            receipt["scenarios"].append(one)
            print(f"  -> {one['requests']} 条，p95={one['latency_ms']['p95']}ms，{one['outcomes']}", flush=True)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        receipt["aborted"] = True
        print("[中断] 已采到的样本仍写回执", file=sys.stderr)

    receipt["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    Path(args.out).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[回执] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
