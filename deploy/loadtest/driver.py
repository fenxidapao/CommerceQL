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
import tempfile
import time
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx

SCHEMA_VERSION = "w7.loadtest.receipt/1"
TERMINAL_EVENT_MAX_WAIT_S = 600.0  # 兜底：流开了但迟迟不给终止帧
QUESTION_POOL_DEFAULT = 5  # 轮转题库条数（见 --questions-file）


def _build_stamp() -> dict[str, Any]:
    """让回执自报构建身份（T-11②）——键名必须是 `reporter._AT_KEYS`／`_REV_KEYS` 认得的。

    ⚠️ 回执原本只写 `finished_at`，而**那个键不在识别之列** ⇒ G-6 的输入取证一直退化成 mtime。
    ⚠️ 不在这里复写一份 git 逻辑：stamp 的唯一实现是 `eval/_bootstrap.build_stamp()`
    （它已有 `ROOT` 定位与"取不到不猜"的处置），本件只把它的输出面接到运行面上。
    """
    eval_dir = Path(__file__).resolve().parents[2] / "eval"
    if str(eval_dir) not in sys.path:
        sys.path.insert(0, str(eval_dir))
    import _bootstrap

    return _bootstrap.build_stamp()


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
    #: 关联键（`ack` 帧的 `task_id`）：只有它能把一条错误码 join 到 `app.audit_log` /
    #: `app.cost_ledger` / 服务端日志行。④′A 档那 17 条 INTERNAL 归因时，回执里没有任何
    #: 键可交 ⇒ 只能靠时间窗反查，把一格读数拆成两族花了一整轮。
    #: ⚠️ 它是**标识符不是内容**（N-11 禁的是查询文本与结果数据），且每码只留 12 条。
    task_id: str | None = None
    #: 拒答侧的"什么时候再来"（429 → §9.2 给 30s；W4 的 DB_UNAVAILABLE → 5s）。
    #: U-106 新增场景⑤"单租户饱和"要验的就是这个头**在不在**——没有它，客户端只会重试打爆。
    retry_after: str | None = None
    #: `X-RateLimit-*` 四头里**实际出现**的名字（剥掉前缀）。④′ **锁维修正判据**要求
    #: "`409 SESSION_CONFLICT` 不得带这四头"（`app/api/errors.py:278` 引 附录 A §A.0.6 末行；
    #: 四头名唯一出处 = `app/api/ratelimit.py:147-150`）。旧量具只读 `retry-after` ⇒ 这条判据
    #: **从未被本窗口的任何回执证过**（"没读到"与"没有"同形）。只在 `status >= 400` 一侧记。
    quota_headers: tuple[str, ...] = ()
    #: (worker, session) 组身份的两半（都是**标识符不是内容**，与 `task_id` 同一卫生类）。
    #: 🔴 U-138：这两个字段**拼不出**服务端 thread —— `thread_id = {tenant}:{user}:{session}`
    #:    （`app/api/runner.py:196`）里 `tenant` 与 `user` 要从令牌解，压测件不碰 DB 也不解 JWT ⇒
    #:    本尺只数"组"，thread 一律走库面那把（`r23_thread_from_checkpoints.sql`）。
    #: 服务端 `thread_id = {tenant}:{user}:{session}`（`app/api/runner.py:196`）里：
    #: ① `user` 由 **worker 序号**定（`worker_token(i)` 的 `i` 是 worker 序号，`:320`）；
    #: ② `session` 由**请求序号**定（`session_pool[i % len]` 的 `i` 是全局游标，`:298`）。
    #: ⇒ **同一 worker 的连续两条请求大概率落在两个不同 thread 上。**
    #:    第二十一轮我把"该 user 的第几轮"当成"该 thread 的第几轮"用了 ⇒ 这两个字段就是那笔账。
    worker: int = -1
    session_id: str | None = None


@dataclass(slots=True)
class ScenarioSpec:
    name: str
    concurrency: int
    duration_s: float | None  # None = 按 total_requests 收口
    total_requests: int | None
    single_session: bool  # 场景③：所有请求共用一个 session_id（验串行锁）
    one_tenant: bool  # 场景④：同租户（配额桶）


def scenario_specs(only: str | None) -> list[ScenarioSpec]:
    """07 §16.5 的四场景默认参数 + U-106 追加的场景⑤。``--scenario`` 给名字时只跑那一条。

    ★ 场景⑤ `tenant-saturation`（U-106，2026-09-20 架构裁定"另加"）验的**不是容量**，是
    "配额保护对不对"：429 是否带 `Retry-After: 30`、被拒的请求是否**根本没进流水线**
    （不产生 LLM 调用、不产生 `cost_ledger` 行）。⚠️ 成本要说清：租户桶是 100 请求/分钟
    （`ratelimit.py:203`），所以前 ~100 条是**真准入、真花额度**的，只有超出那部分才是免费的拒绝
    —— 别把这一场景当成"不花钱的冒烟测试"。
    """
    specs = [
        ScenarioSpec("steady", 50, 600.0, None, False, False),
        ScenarioSpec("burst", 100, 30.0, None, False, False),
        ScenarioSpec("session-lock", 8, None, 24, True, False),
        ScenarioSpec("tenant-quota", 30, None, 60, False, True),
        ScenarioSpec("tenant-saturation", 30, 30.0, 130, False, True),
    ]
    if only is None:
        # ⚠️ 缺省**不含**场景⑤：§16.5 的口径是"四场景"，而 W6 读的 `receipt.json` 就按那四条合成。
        #    把一条追加诊断场景混进默认集，会让"§16.5 全跑完"这句话悄悄变成五件事 ——
        #    要跑它必须显式 `--scenario tenant-saturation`。
        return [s for s in specs if s.name != "tenant-saturation"]
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
    task_id: str | None = None
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
                quota = tuple(sorted(h[len("x-ratelimit-"):].lower() for h in resp.headers
                                     if h.lower().startswith("x-ratelimit-")))
                return Sample(kind, status, None, _ms(start), 0, detail=_code_of(body) or body,
                              retry_after=resp.headers.get("retry-after"), quota_headers=quota)
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
                                  detail="data 帧不是 JSON", last_stage=last_stage, task_id=task_id)
                if data.get("terminal") is not True:
                    if isinstance(data.get("task_id"), str) and data["task_id"]:
                        task_id = str(data["task_id"])
                    if event_name == "stage" and isinstance(data.get("stage"), str) and data["stage"]:
                        last_stage = str(data["stage"])
                    continue
                if isinstance(data.get("task_id"), str) and data["task_id"]:
                    task_id = str(data["task_id"])
                terminal = event_name or str(data.get("type") or "")
                break
    except httpx.TimeoutException:
        return Sample("timeout", None, ttfb, _ms(start), frames,
                      detail=f">{TERMINAL_EVENT_MAX_WAIT_S}s 未收到终止帧",
                      last_stage=last_stage, task_id=task_id)
    except (httpx.HTTPError, OSError) as exc:
        return Sample("conn_error", None, ttfb, _ms(start), frames,
                      detail=f"{type(exc).__name__}", last_stage=last_stage, task_id=task_id)

    total = _ms(start)
    reason = data.get("reason") if isinstance(data.get("reason"), str) else None
    if terminal is None:
        # 流正常结束却没有终止帧：这是 N-08 违约，不是"成功"。
        return Sample("truncated", status, ttfb, total, frames,
                      detail="流结束但无 terminal=true 帧", last_stage=last_stage, task_id=task_id)
    if terminal == "error":
        return Sample("error_frame", status, ttfb, total, frames,
                      code=str(data.get("code")), msg=str(data.get("message") or "")[:60],
                      last_stage=last_stage, reason=reason, task_id=task_id)
    if terminal == "complete":
        if data.get("async") or data.get("task_id"):
            return Sample("async_degraded", status, ttfb, total, frames,
                          detail="超阈值转异步，端到端未在此流内完成",
                          last_stage=last_stage, task_id=task_id)
        return Sample("ok", status, ttfb, total, frames, last_stage=last_stage, task_id=task_id)
    if terminal == "clarify":
        return Sample("clarify", status, ttfb, total, frames, last_stage=last_stage,
                      reason=reason, task_id=task_id)
    if terminal == "refuse":
        return Sample("refuse", status, ttfb, total, frames, last_stage=last_stage,
                      reason=reason, task_id=task_id)
    return Sample("truncated", status, ttfb, total, frames,
                  detail=f"未知终止事件 {terminal}", last_stage=last_stage, task_id=task_id)


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

    async def worker(client: httpx.AsyncClient, token: str, widx: int) -> None:
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
            #: thread = (worker ⇒ user, sid ⇒ session)；两个都是标识符，不落内容。
            sample.worker = widx
            sample.session_id = sid
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
        # ⚠️ `single_session` 必须**全线固定创建者令牌**（W1B/W0 09-28 裁定）：会话由 `tokens[0]` 铸造，
        #    而 §9.3 的锁键与 FR-10.4 的 thread_id 都含 user ⇒ 换令牌 = 换锁键/换 thread，
        #    「同一会话并发」这一维根本没被压到（实测：10 令牌轮转时 `rejected_429=0`、409 只有 4）。
        #    非属主令牌的负向断言不在这里做，见 `probe_session_owner.py`。
        worker_token = (lambda i: tokens[0]) if spec.single_session else (lambda i: tokens[i % len(tokens)])
        workers = [asyncio.create_task(worker(client, worker_token(i), i)) for i in range(spec.concurrency)]
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


#: U-106 的"准入"定义：HTTP 2xx（= 真进了 SSE 流）。429 是限流器**正确工作**，
#: 不该进延迟分位数；4xx/5xx/未收口同理要单列，不能混进分母。
MIN_ADMITTED_FOR_P95: Final[int] = 20

#: 收到 `terminal: true` 终止帧的那些 outcome（U-130 的严格分母）。
#: ⚠️ `truncated`（200 但流断在半途）与 `http_4xx` / `http_5xx` / `timeout` / `conn_error`
#: **都不在此列** —— 它们没有终止帧，因而不构成"服务端落了一条终态"。
_TERMINAL_OUTCOMES: Final[frozenset[str]] = frozenset(
    {"ok", "clarify", "refuse", "error_frame", "async_degraded"}
)


def _admitted(sample: Sample) -> bool:
    return sample.status is not None and 200 <= sample.status < 300


def _admission(samples: list[Sample]) -> dict[str, int]:
    """把请求按"有没有被准入"分桶 —— U-106 要求 429 比例**单列**，不是塞进 outcomes。

    🔴 **`terminal` 桶为什么必须与 `admitted` 并存（U-130）**：`admitted` 的判据只是 HTTP 2xx，
    而 `truncated`（200 但流里没读到 `terminal:true`）**也在 2xx 里** —— 那条请求没有资格断言
    服务端落了终态行。⇒ 「`admitted − app.audit_log` 行差 = 0」这条不变量的**严格分母是 `terminal`**，
    `admitted` 只是"本性格子里没有断流"时的代理（两者不等 ⇒ 差值是假红，别拿去指认缺陷）。
    """
    buckets = {
        "admitted": 0,
        "rejected_429": 0,
        "other_http_4xx": 0,
        "http_5xx": 0,
        "unresolved": 0,
        "terminal": 0,
    }
    for s in samples:
        if _admitted(s):
            buckets["admitted"] += 1
        elif s.status == 429:
            buckets["rejected_429"] += 1
        elif s.status is not None and 400 <= s.status < 500:
            buckets["other_http_4xx"] += 1
        elif s.status is not None and s.status >= 500:
            buckets["http_5xx"] += 1
        else:
            buckets["unresolved"] += 1  # 超时/连不上：连接层事实，没资格进任何 HTTP 桶
        if s.outcome in _TERMINAL_OUTCOMES:
            buckets["terminal"] += 1
    return buckets


def _rejections(samples: list[Sample]) -> dict[str, dict[str, int]]:
    """被拒样本的**退避可用性**指纹：`状态码 → {"retry_after=<值 或 missing>"} → 条数`。

    为什么单独记：429/503 只对客户端"可恢复"的前提是带了 `Retry-After`（§9.2 给 429 是 30s，
    W4 的 `DB_UNAVAILABLE` 给 5s）。少了这个头，压测端和真实前端都只会立刻重试 ⇒ 配额保护
    被自己的重试流量打穿，而看板上看到的只是"429 很多"。
    """
    out: dict[str, dict[str, int]] = {}
    for s in samples:
        if s.status is None or s.status < 400:
            continue
        bucket = out.setdefault(str(s.status), {})
        key = f"retry_after={s.retry_after if s.retry_after is not None else 'missing'}"
        bucket[key] = bucket.get(key, 0) + 1
    return out


def _worker_session_depth(samples: list[Sample]) -> dict[str, Any]:
    """按 **(worker, session_id)** 这一组给样本排第几轮，再按深度切读数。

    🔴 **U-138（2026-10-06 立案并落地）**：这把尺的键**不是**服务端 thread。服务端
    `thread_id = {tenant}:{user}:{session}`（`app/api/runner.py:196`），而这里的键是
    `(worker 序号, session_id)` ⇒ 同一把批实测 **回执 7 组 vs 库面 3 条 thread**，不等价。
    三条落地要求逐条对上：
    ① 键名与文案**不再自称 thread**（旧 `thread_depth` / `threads` 已废，见返回体的 `grouping_key`）；
    ② 两把不等价 ⇒ **必须同框并报**，库面尺 = `deploy/loadtest/r23_thread_from_checkpoints.sql` 的 ⑮/⑰
       （本尺只给 `server_thread_ruler` 指针，不在此处查库 —— 压测件不开 DB 连接）；
    ③ 凡"同一 thread 的第 N 轮"这类结论**只从库面那把取**，本尺只支撑"同一 `(worker, session)` 组的第 N 条"。

    存在的理由仍是第二十一轮那笔账（`r21_turn_index_attribution.txt` 表 1/表 2）：那次按
    **user** 排轮次、又被当成 **thread** 尺读，而 `sid` 随请求序号轮转 ⇒ 聚合读数撑不起序列断言。
    ⚠️ 深度顺序 = 样本**完成顺序**（`samples.append` 的到达序），不是发出序；并发下两者可差几秒。
    """
    seen: dict[tuple[int, str], int] = {}
    depth_hist: dict[str, int] = {}
    by_outcome: dict[str, dict[str, int]] = {}
    by_code: dict[str, dict[str, int]] = {}
    unsessioned = 0
    for s in samples:
        if s.session_id is None:
            unsessioned += 1
            depth = None
        else:
            k = (s.worker, s.session_id)
            seen[k] = seen.get(k, 0) + 1
            depth = seen[k]
            bucket = "1" if depth == 1 else ("2" if depth == 2 else "3+")
            depth_hist[bucket] = depth_hist.get(bucket, 0) + 1
        arm = "unsessioned" if depth is None else ("turn1" if depth == 1 else "turn2plus")
        o = by_outcome.setdefault(s.outcome, {"turn1": 0, "turn2plus": 0, "unsessioned": 0})
        o[arm] += 1
        if s.code:
            c = by_code.setdefault(s.code, {"turn1": 0, "turn2plus": 0, "unsessioned": 0})
            c[arm] += 1
    return {"grouping_key": "(worker, session_id)",
            "is_server_thread": False,
            "server_thread_key": "{tenant}:{user}:{session}（app/api/runner.py 的 thread_id 形状）",
            "server_thread_ruler": "deploy/loadtest/r23_thread_from_checkpoints.sql ⑮/⑰（库面，须剔作废那跑）",
            "groups": len(seen),
            "depth_hist": depth_hist, "unsessioned": unsessioned,
            "by_outcome": by_outcome, "by_code": by_code}


def _quota_headers_by_status(samples: list[Sample]) -> dict[str, dict[str, int]]:
    """`状态码 → {出现的 X-RateLimit 头名组合} → 条数`（④′ **锁维修正判据**的可读面）。

    ⚠️ 这条判据是**否证形**（409 不许带四头）⇒ 单看 409 一侧永远绿。正向对照 = **429 必须带**
    （`app/api/errors.py:279`：四头只在配额放行后的 2xx 与 429 两处下发）⇒ 两臂同表才作数。
    """
    out: dict[str, dict[str, int]] = {}
    for s in samples:
        if s.status is None or s.status < 400:
            continue
        bucket = out.setdefault(str(s.status), {})
        key = "+".join(s.quota_headers) if s.quota_headers else "none"
        bucket[key] = bucket.get(key, 0) + 1
    return out


def _summarize(spec: ScenarioSpec, samples: list[Sample], wall_s: float, args: argparse.Namespace) -> dict[str, Any]:
    # ★ U-106（架构裁定 2026-09-20）：**P95 只在准入样本上算，429 比例单列**。
    #   旧口径把所有样本混进分位数 ⇒ "5 用户打 150 条"那种跑法 p50=7.3ms（那是 429 的速度），
    #   而 429 是限流器**正确工作**，不是"请求很快"。混算会把配额问题伪装成容量结论。
    admitted = [s for s in samples if _admitted(s)]
    totals = sorted(s.total_ms for s in admitted if s.total_ms is not None)
    ttfbs = sorted(s.ttfb_ms for s in admitted if s.ttfb_ms is not None)
    all_totals = sorted(s.total_ms for s in samples if s.total_ms is not None)
    # 先算一次：`_pct` 返回 `float | None`，连调两次 mypy 收窄不了（而且同一分位数算两遍没意义）。
    p95_total = _pct(totals, 95)
    by_outcome: dict[str, int] = {}
    for s in samples:
        by_outcome[s.outcome] = by_outcome.get(s.outcome, 0) + 1
    admission = _admission(samples)
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
        # ⚠️ `latency_ms` 的分母是**准入样本**（`p95_scope` 自证口径）。schema 串刻意仍是
        #    `w7.loadtest.receipt/1`：W6 的 `eval/reporter.py:139` 按这个串**精确匹配**，
        #    改串会让 G-6 静默退回 `NOT_AVAILABLE` —— 那是把口径修对了、把接口弄断了。
        "p95_scope": "admitted_http_2xx",
        "admission": admission,
        "rejection_headers": _rejections(samples),
        "quota_headers_by_status": _quota_headers_by_status(samples),
        "worker_session_depth": _worker_session_depth(samples),
        "latency_ms": {"p50": _pct(totals, 50), "p95": p95_total, "p99": _pct(totals, 99),
                       "max": round(totals[-1], 1) if totals else None,
                       "mean": round(statistics.fmean(totals), 1) if totals else None,
                       "samples": len(totals)},
        "latency_ms_all_ms": {"p50": _pct(all_totals, 50), "p95": _pct(all_totals, 95),
                              "samples": len(all_totals)},
        "ttfb_ms": {"p50": _pct(ttfbs, 50), "p95": _pct(ttfbs, 95)},
        # 🔻 T-36 E（QA 13.7 B）：聚合量在 n=2 时 `p95` **恒等于 `max`** ⇒ 只报五个数会把"两个样本"
        #    读成"一个分布"。逐样本毫秒 ＋ outcome 标签一并落进回执，下一窗要按样本重算就不必重跑（花钱）。
        #    口径见 07 §16.5：`admitted < MIN_ADMITTED_FOR_P95` ⇒ 聚合量**不得**引用为达标／不达标，
        #    但逐样本是实测读数（可以引"哪一条多少毫秒、什么终态"，不可以引"这批 P95 是多少"）。
        "latency_samples_ms": _latency_samples(samples),
        "outcomes": by_outcome,
        "codes": _codes(samples),
        # 关联键：让 `codes` 里每一格都能被 `app.audit_log` / `app.cost_ledger` 复算（见 helper 注释）。
        "codes_task_ids": _codes_task_ids(samples),
        # 谁能回答"这条 refuse 是 intent 说的还是 link 说的"：`outcomes` 与 `reason` 单独都答不了。
        "terminal_provenance": _provenance(samples),
        # drain 证据只能靠 message 分家：光看 `error_frame` 数会把"停机注入"和"节点超时"混成一坨。
        "drain_frames": sum(1 for s in samples if s.msg and "重启" in s.msg),
        "error_messages": _messages(samples),
        # G-6 只看 total_ms 的 p95。**三态**（U-120 / 07 §16.5）：`None` = 这份样本不可判，
        # `true`/`false` 才是量到了结论 —— 旧写法把"没有数"输出成 `false`（= 不达标），
        # 与"准入只有 5 条也给布尔"是同一病灶的两种形态。⚠️ 必须与 `g6_caveat` 同读。
        "g6_p95_le_8s": _g6_boolean(p95_total, admission),
        "g6_caveat": _g6_caveat(by_outcome, admission),
    }


def _g6_boolean(p95_ms: float | None, admission: Mapping[str, int] | None) -> bool | None:
    """`g6_p95_le_8s` 的唯一判定点 —— 三态，不是布尔。

    `None` 的三种来路（每种都比 `false` 诚实）：
      · 没有 p95（准入样本里一条延迟都没收到）⇒ "不达标"是**假话**，那是"没有数"；
      · `admission` 缺失（产自 U-106 口径之前的旧回执）⇒ 分母口径无法确认；
      · `admitted < MIN_ADMITTED_FOR_P95` ⇒ 分位数落点由个别样本决定，不构成容量结论。
    scope 就这一格：`ttfb_ms.p95` 与 `latency_ms_all_ms` 没有配对布尔，不入本判据（架构 v1.6.5 ②）。
    """
    if p95_ms is None or not admission:
        return None
    if admission.get("admitted", 0) < MIN_ADMITTED_FOR_P95:
        return None
    return bool(p95_ms <= 8000.0)


def _g6_caveat(
    by_outcome: dict[str, int],
    admission: Mapping[str, int] | None = None,
) -> str | None:
    """这份 P95 **能不能**拿来判 G-6 达标 —— 必须是机器可读的，不能只在散文里警告。

    为什么这条要单独抽出来：下游 W6 的 `eval/reporter.loadtest_pressure()` 取的是
    "各场景 `latency_ms.p95` 的最大值"，并且**只通过 `g6_caveat` 是否非空**来降档 ——
    它不读 `outcomes`。于是 2026-09-19 那种"0 条完成、但 error 帧收得很快"的跑批
    （p95 = 7268ms ≤ 8000ms）会被**机械地判成 G-6 PASS**。分母里没有一次成功。
    ⇒ 凡是"这条 P95 不代表真实完成延迟"的情形，都必须在这里落一句非空文本。

    `admission=None` = 这份回执产自 U-106 之前（没有准入分桶字段）⇒ 不能假装按新口径判过。
    """
    notes: list[str] = []
    completed = by_outcome.get("ok", 0)
    if not completed:
        notes.append("本场景 0 条真正完成（outcome=ok）⇒ P95 的分母全是失败/降级样本，不可判达标")
    async_degraded = by_outcome.get("async_degraded", 0)
    if async_degraded:
        notes.append(f"含 {async_degraded} 条 async_degraded（超阈值转异步）⇒ 端到端未在此流内完成，P95 偏低")
    if admission is None:
        notes.append("本回执无 `admission` 字段（产自 U-106 口径之前）⇒ 无法确认 P95 的分母是否只含准入样本")
    else:
        admitted = admission.get("admitted", 0)
        if not admitted:
            notes.append("准入样本为 0（全部被 4xx/5xx/连接层拒掉）⇒ 本场景没有任何端到端延迟可判")
        elif admitted < MIN_ADMITTED_FOR_P95:
            notes.append(
                f"准入样本仅 {admitted} 条（< 本窗口下限 {MIN_ADMITTED_FOR_P95}）⇒ P95 落点由个别样本决定，"
                "统计意义不足"
            )
        rejected_429 = admission.get("rejected_429", 0)
        if rejected_429:
            notes.append(
                f"另有 {rejected_429} 条被限流 429 拒掉（按 U-106 已**排除**出 P95 分母；"
                "它是配额画像而非容量读数）"
            )
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


#: 每个错误码最多留几条关联键。12 = "够对方抽样定位"又不把回执撑大；截断是**有意的**，
#: 全量键在 `app.audit_log` 里按时间窗本来就能反查出来。
CODES_TASK_IDS_CAP: Final[int] = 12


def _latency_samples(samples: list[Sample]) -> list[dict[str, object]]:
    """逐样本延迟 ＋ 终态标签（T-36 E）。

    只装**观测值与标识符**：`total_ms` / `ttfb_ms` / `outcome` / `code` / `task_id` ——
    不含查询文本与结果数据（N-11 同一条关注，与 `_codes_task_ids` 一个口径）。
    排序 = `total_ms` 升序 ⇒ 同一批样本两次 roll-up 输出一致（可复算）。
    """
    out: list[dict[str, object]] = []
    for s in samples:
        if not _admitted(s) or s.total_ms is None:
            continue
        out.append({
            "total_ms": round(s.total_ms, 1),
            "ttfb_ms": round(s.ttfb_ms, 1) if s.ttfb_ms is not None else None,
            "outcome": s.outcome,
            "code": s.code,
            "task_id": s.task_id,
        })
    out.sort(key=lambda d: (d["total_ms"] is None, d["total_ms"]))
    return out


def _codes_task_ids(samples: list[Sample]) -> dict[str, list[str]]:
    """`错误码 → 命中该码的 task_id 样本`（U-130 取证用）。

    存在的理由：`codes` 只说"有 17 条 INTERNAL"，答不了"这 17 条是不是同一种 INTERNAL"。
    ④′A 档实测把 17 条拆成了两族（13 条有段 1 审计行、4 条没有），靠的是**时间窗反查**
    `app.audit_log` 的 `latency_ms` 键集 + `app.cost_ledger` 的调用数 —— 一轮才拆得开。
    带上关联键，对方一条 `where task_id = any(...)` 就能复算。

    ⚠️ 只装**标识符**，不装查询文本与结果数据（N-11 同一条关注）；排序后截断，保证同一份
    样本两次 roll-up 输出一致。
    """
    out: dict[str, list[str]] = {}
    for s in samples:
        if s.code and s.task_id:
            out.setdefault(s.code, []).append(s.task_id)
    return {code: sorted(ids)[:CODES_TASK_IDS_CAP] for code, ids in sorted(out.items())}


def _provenance(samples: list[Sample]) -> dict[str, dict[str, int]]:
    """终止事件的**来源指纹**：`outcome` → {"stage=<终止前最后一个 stage>|reason=<终止帧自带 reason>"} → 条数。

    存在的理由是一个 `outcomes` + `codes` 都答不了的问题：一条 `refuse(reason=no_data_asset)`
    既可能是 intent 层给的（07 §5.2 组 3），也可能是 `link` 的空召回（§5.3）—— 两个落点共用同一个
    4 值枚举。把"终止前最后一个 `stage` 帧"一起记下来才能分家。

    🔴 **读法（W4 纠正，别再按字面读）**：stage 帧是节点**跑完之后**才发射的 ——
    `app/api/runner.py:454` 用 `stream_mode="updates"`，其头注第 8 行明写"每个节点跑完拿到一次增量"。
    ⇒ `stage=X` 的**唯一**可靠含义是"**X 已完成**"，破点在 §5.3 顺序里 X 的**后继节点**，
    而不是 X 本身。把它读成"X 这一格有问题"是反向的。
    例：本轮 `{"error_frame": {"stage=intent|reason=none": 2}}` 曾被本窗口读成
    "intent 收不了口"，按此语义正确读法是 **intent 完成、崩在 link**（W4 据此定位到
    `app/retrieval/search.py` 缓存重建路径的 `float(None)`）。
    ⚠️ `stage=none` = **一条 stage 帧都没收到** ⇒ 没有任何节点**完成**（不是"数据丢了"）。
    🔴 但它**不等价于**"没进图"或"没落审计行"（W6 第 ⑦ 条，本窗自有读数佐证）：同一格
    `terminal_provenance` 里 `stage=none` 共 **22** 条（error 11 + 4xx 9 + refuse 2），
    而审计侧缺行只有 **4** 条 ⇒ **≥18 条 `stage=none` 的 run 是落了审计行的**。
    ⇒ 判"是否落审计"请读 `app.audit_log` 或 U-130 的批级差，**不要用 `stage=none` 当代用**。
    （为"为什么一条 stage 都没有却落了行"给出**机制解释 = UNVERIFIED**：本轮只有形状读数，没有对照臂。）
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


#: 桩自发的 `X-RateLimit-*` 四头（头名 = `app/api/ratelimit.py:147-150` 的小写形）。
_STUB_QUOTA_HDRS: Final[list[tuple[bytes, bytes]]] = [
    (b"x-ratelimit-bucket", b"query"), (b"x-ratelimit-limit", b"10"),
    (b"x-ratelimit-remaining", b"9"), (b"x-ratelimit-reset", b"1700000000"),
]


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
        seq = cursor["i"]
        cursor["i"] += 1
        kind, delay_ms = scripted[i]
        if kind == "http409":
            await _json_reply(send, 409, '{"detail":{"code":"SESSION_CONFLICT"}}')
            return
        if kind == "http429":
            # 带 `Retry-After: 30` 是 §9.2 的要求 ⇒ 桩必须也带上，否则 `rejection_headers`
            # 这条读数在任何自检里都只能是 missing，等于没测。
            # 四头同理发 = `quota_headers_by_status` 的正向对照臂（409 那一支故意不发）。
            await _json_reply(send, 429, '{"detail":{"code":"RATE_LIMITED"}}',
                              headers=[(b"retry-after", b"30"), *_STUB_QUOTA_HDRS])
            return
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        # 首帧对齐真服务端的 `ack`（`app/graph/events.py` 发 `{"task_id","session_id"}`）：
        # `codes_task_ids` 读的就是它。桩不发 ack，那条接线就只是"自检里没报错"，从不被验证。
        await send({"type": "http.response.body",
                    "body": f'event: ack\ndata: {{"terminal": false, "task_id": "tk_stub_{seq}"}}\n\n'
                            .encode(),
                    "more_body": True})
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
    # 五种情形都必须测到（后三条是 U-106 加的），否则会静默退回旧行为。
    gate_cases: list[tuple[dict[str, int], dict[str, int] | None, bool]] = [
        ({"error_frame": 87, "http_5xx": 41, "http_4xx": 9, "clarify": 7, "refuse": 6},
         {"admitted": 0, "rejected_429": 9}, True),
        ({"async_degraded": 12, "ok": 3}, {"admitted": 15}, True),
        ({"ok": 40, "clarify": 5}, {"admitted": 45}, False),
        ({"ok": 5}, {"admitted": 5}, True),                                  # 准入太少 ⇒ 判不了
        ({"ok": 40}, None, True),                                            # 旧回执无准入分桶
        ({"ok": 30, "refuse": 5}, {"admitted": 30, "rejected_429": 20}, True),  # 429 单列但必须可见
    ]
    for case_outcomes, case_admission, want_caveated in gate_cases:
        if bool(_g6_caveat(case_outcomes, case_admission)) != want_caveated:
            print(f"[自检失败] g6_caveat 判错：{case_outcomes} + admission={case_admission} "
                  f"→ {_g6_caveat(case_outcomes, case_admission)!r}"
                  f"（期望{'非空' if want_caveated else 'None'}）", file=sys.stderr)
            return 3
    # ★ U-120：三态要**单独**钉。上一轮的形状正是"caveat 判对了、布尔照出"——
    #   而 `false` 与 `null` 的差别是"不达标"与"没量到"的差别，只读布尔的下游分不出来。
    bool_cases: list[tuple[float | None, dict[str, int] | None, bool | None]] = [
        (7000.0, {"admitted": 20}, True),                       # 样本够 + 达标
        (9000.0, {"admitted": 20}, False),                      # 样本够 + 超预算 ⇒ 唯一许出 False 的形态
        (7000.0, {"admitted": 19}, None),                       # 差一条也不许出结论
        (7000.0, {"admitted": 5}, None),                        # 今天 c=1 预检就是这个形状
        (7000.0, {"admitted": 0, "rejected_429": 9}, None),     # 全部被限流拒掉
        (7000.0, None, None),                                   # 旧回执无准入分桶
        (None, {"admitted": 40}, None),                         # ★ 没有 p95 ⇒ 不得谎报"不达标"
    ]
    for p95_in, adm_in, want_bool in bool_cases:
        got_bool = _g6_boolean(p95_in, adm_in)
        if got_bool is not want_bool:
            print(f"[自检失败] g6_p95_le_8s 三态判错：p95={p95_in} admission={adm_in} "
                  f"→ {got_bool!r}（期望 {want_bool!r}）", file=sys.stderr)
            return 3
    # ★ 上面那组只钉住了**助手函数**。变异检查实测：把 `_summarize` 里的接线退回旧表达式，
    #   助手用例照样全绿 —— 病灶在调用点，就得在调用点上取证。两格双向：低样本给 None，
    #   样本够要真给布尔（防有人把三态写成"永远 None"来通过这条守卫）。
    stub_spec = ScenarioSpec(name="self-check", concurrency=1, duration_s=None,
                             total_requests=len(got), single_session=False, one_tenant=False)
    stub_args = argparse.Namespace(no_async=True, questions_file=None, max_requests=None)
    sum_low = _summarize(stub_spec, got, 1.0, stub_args)
    if sum_low["g6_p95_le_8s"] is not None:
        print(f"[自检失败] 调用点没走三态：admitted={sum_low['admission']['admitted']} "
              f"⇒ g6_p95_le_8s={sum_low['g6_p95_le_8s']!r}（期望 None）", file=sys.stderr)
        return 3
    enough = [s for s in got if _admitted(s)] * MIN_ADMITTED_FOR_P95
    sum_ok = _summarize(stub_spec, enough, 1.0, stub_args)
    if sum_ok["g6_p95_le_8s"] is not True:
        print(f"[自检失败] 样本够时调用点仍没给出达标布尔：admitted="
              f"{sum_ok['admission']['admitted']} p95={sum_ok['latency_ms']['p95']} "
              f"⇒ {sum_ok['g6_p95_le_8s']!r}（期望 True）", file=sys.stderr)
        return 3
    # ★ 关联键接线也要在**调用点**钉（同 U-120 三态那条的教训）：桩里唯一带码的终止帧是
    #   脚本第 4 条（索引 3）的 `error` ⇒ 整字典相等，不留"字段存在但恒空"的空间。
    # ★ T-36 E（QA 13.7 B）：逐样本延迟必须在**调用点**钉住 —— n=2 时 `p95` 恒 = `max`，
    #   只报聚合量会把"两个样本"读成"一个分布"。三条断言：同分母、升序、字段集合固定（不含查询文本）。
    lat_samples = sum_low.get("latency_samples_ms")
    if not isinstance(lat_samples, list):
        print("[自检失败] latency_samples_ms 缺失或不是列表 ⇒ 回执形状没接上", file=sys.stderr)
        return 3
    want_keys = {"total_ms", "ttfb_ms", "outcome", "code", "task_id"}
    if any(set(d.keys()) != want_keys for d in lat_samples):
        print(f"[自检失败] 逐样本字段集合不对：{[sorted(d) for d in lat_samples][:2]}"
              f"（期望 {sorted(want_keys)}）⇒ 要么漏字段，要么把内容写进了回执（N-11）", file=sys.stderr)
        return 3
    if len(lat_samples) != sum_low["latency_ms"]["samples"]:
        print(f"[自检失败] 逐样本条数 {len(lat_samples)} ≠ latency_ms.samples "
              f"{sum_low['latency_ms']['samples']} ⇒ 两栏分母不同源，聚合量与样本不可对账", file=sys.stderr)
        return 3
    if [d["total_ms"] for d in lat_samples] != sorted(d["total_ms"] for d in lat_samples):
        print("[自检失败] 逐样本未按 total_ms 升序 ⇒ 同一批样本两次 roll-up 输出不一致（不可复算）", file=sys.stderr)
        return 3
    want_codes_tasks = {"INTERNAL": ["tk_stub_3"]}
    if sum_low.get("codes_task_ids") != want_codes_tasks:
        print(f"[自检失败] codes_task_ids 接线不对：{sum_low.get('codes_task_ids')!r}"
              f"（期望 {want_codes_tasks}）⇒ ack 帧的 task_id 没被记进错误码", file=sys.stderr)
        return 3
    # ★ A-1（架构 v1.6.6）：`--roll-up` 必须把两个派生量**一起**重算，而且只动派生量。
    #   两格是双向的 —— 低样本的 stale `true` 要降成 None（否则旧件继续被引用），
    #   而"样本够、确实达标"的格必须能从 None 回到 true（否则守卫会被写成"永远不可判"来自证清白）。
    rollup_cases = {
        "low_sample.json": {"bool_before": True, "bool_after": None,
                            "admitted": 5, "p95": 3000.0},
        "enough_sample.json": {"bool_before": None, "bool_after": True,
                               "admitted": 25, "p95": 4000.0},
    }
    with tempfile.TemporaryDirectory() as td:
        ru_paths = []
        for ru_name, ru_case in rollup_cases.items():
            receipt = {"schema": SCHEMA_VERSION, "scenarios": [{
                "scenario": ru_name, "requests": ru_case["admitted"],
                "outcomes": {"ok": ru_case["admitted"]},
                "admission": {"admitted": ru_case["admitted"], "rejected_429": 0},
                "latency_ms": {"p50": ru_case["p95"], "p95": ru_case["p95"]},
                "latency_ms_all_ms": {"p95": ru_case["p95"]},
                "g6_p95_le_8s": ru_case["bool_before"], "g6_caveat": None}]}
            ru_path = os.path.join(td, ru_name)
            Path(ru_path).write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            ru_paths.append(ru_path)
        if roll_up(ru_paths, os.path.join(td, "merged.json")) != 0:
            print("[自检失败] A-1：roll_up 在临时夹具上返回非零", file=sys.stderr)
            return 3
        for ru_path in ru_paths:
            ru_name = os.path.basename(ru_path)
            ru_case = rollup_cases[ru_name]
            ru_got = json.loads(Path(ru_path).read_text(encoding="utf-8"))["scenarios"][0]
            ru_audit = ru_got.get("g6_derived_audit") or {}
            if ru_audit.get("bool_before") != ru_case["bool_before"] \
                    or ru_got.get("g6_p95_le_8s") != ru_case["bool_after"]:
                print(f"[自检失败] A-1 派生量重算不对：{ru_name} "
                      f"bool {ru_audit.get('bool_before')!r}→{ru_got.get('g6_p95_le_8s')!r}"
                      f"（期望 {ru_case['bool_before']!r}→{ru_case['bool_after']!r}）", file=sys.stderr)
                return 3
            if ru_got.get("admission") != {"admitted": ru_case["admitted"], "rejected_429": 0} \
                    or ru_got.get("latency_ms", {}).get("p95") != ru_case["p95"]:
                print(f"[自检失败] A-1 越界：读数被改写了（{ru_name}）", file=sys.stderr)
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
    # U-106 的准入分桶：桩里刻意放一条 409（配额之外的 4xx）和一条 429，
    # 断言"429 单独成桶、其他 4xx 不混进去、2xx 全算准入"——分母口径错了，P95 就全错了。
    # ★ `terminal` 比 `admitted` 少 1 是**故意的**：桩里那条 `truncated` 是 HTTP 200（进 admitted）
    #   却没读到终止帧（不进 terminal）⇒ 这格就是"别把不变量的分母退回 admitted"的活样本（U-130）。
    admission = _admission(got)
    want_admission = {"admitted": 8, "rejected_429": 1, "other_http_4xx": 1,
                      "http_5xx": 0, "unresolved": 0, "terminal": 7}
    if admission != want_admission:
        print(f"[自检失败] 准入分桶不对：{admission}（期望 {want_admission}）", file=sys.stderr)
        return 3
    # 被拒样本的退避指纹：429 必须读到 `retry_after=30`（桩就是照 §9.2 发的），
    # 409 没这个头 ⇒ 落成 missing。**如果这条恒 missing，说明驱动压根没读响应头**，
    # 那场景⑤要验的东西就没人验 —— 所以它是"指纹能不能出数"的正向对照，不是装饰。
    rejections = _rejections(got)
    want_rejections = {"409": {"retry_after=missing": 1}, "429": {"retry_after=30": 1}}
    if rejections != want_rejections:
        print(f"[自检失败] Retry-After 指纹不对：{rejections}（期望 {want_rejections}）", file=sys.stderr)
        return 3
    # ④′ 锁维修正判据的量具自证：**409 一个四头都不许有 / 429 四个都有**（双向，防恒 none 也防恒有）。
    quota_fp = _quota_headers_by_status(got)
    want_quota = {"409": {"none": 1}, "429": {"bucket+limit+remaining+reset": 1}}
    if quota_fp != want_quota:
        print(f"[自检失败] X-RateLimit 四头指纹不对：{quota_fp}（期望 {want_quota}）", file=sys.stderr)
        return 3

    # (worker, session) 组深度尺的离线双向自证（第二十一轮那笔账的量具面：user 尺 ≠ thread 尺 ≠ 本尺）。
    # 为什么不能只靠真跑批：`--reuse-sessions` 关着的时候这把尺整根悬空（全落 `unsessioned`），
    # 那格回执里没有任何东西能暴露"键根本没接上"。
    # 🔴 U-138：夹具同时钉住"不再自称 thread"那两面 —— 键名不许出现 `thread_depth`/`threads`，
    #    且必须显式声明 `is_server_thread = False` 并给出库面尺指针（缺一条 = 抄本又漂回"thread"）。
    td_samples = [
        Sample("ok", 200, 1.0, 1.0, 1, worker=0, session_id="sA"),
        Sample("error_frame", 200, 1.0, 1.0, 1, code="INTERNAL", worker=0, session_id="sA"),
        Sample("refuse", 200, 1.0, 1.0, 1, worker=1, session_id="sB"),
        Sample("ok", 200, 1.0, 1.0, 1, worker=2, session_id=None),
    ]
    want_td = {"grouping_key": "(worker, session_id)", "is_server_thread": False,
               "server_thread_key": "{tenant}:{user}:{session}（app/api/runner.py 的 thread_id 形状）",
               "server_thread_ruler": "deploy/loadtest/r23_thread_from_checkpoints.sql ⑮/⑰（库面，须剔作废那跑）",
               "groups": 2, "depth_hist": {"1": 2, "2": 1}, "unsessioned": 1,
               "by_outcome": {"ok": {"turn1": 1, "turn2plus": 0, "unsessioned": 1},
                              "error_frame": {"turn1": 0, "turn2plus": 1, "unsessioned": 0},
                              "refuse": {"turn1": 1, "turn2plus": 0, "unsessioned": 0}},
               "by_code": {"INTERNAL": {"turn1": 0, "turn2plus": 1, "unsessioned": 0}}}
    td_got = _worker_session_depth(td_samples)
    if td_got != want_td:
        print(f"[自检失败] (worker, session) 组深度尺不对：{td_got}（期望 {want_td}）", file=sys.stderr)
        return 3
    print(f"[自检通过] 10/10 分类正确；样本 p95={p95}ms（桩注入的最大延迟 3000ms）；"
          f"g6_caveat {len(gate_cases)} 情形判向正确；g6_p95_le_8s {len(bool_cases)} 情形三态正确"
          f"（含 _summarize 调用点双向）；"
          f"A-1 roll-up 降档/回判双向 {len(rollup_cases)} 夹具正确且未越界改读数；"
          f"准入分桶正确；"
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


async def _json_reply(send: Any, status: int, body: str,
                      headers: list[tuple[bytes, bytes]] | None = None) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), *(headers or [])]})
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
    p.add_argument("--scenario",
                   choices=["steady", "burst", "session-lock", "tenant-quota", "tenant-saturation"],
                   help="只跑一条；缺省跑 §16.5 那四条（`tenant-saturation` 是 U-106 的追加场景，**只能点名跑**）")
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
                        "并按各场景自带读数重算两个派生判定量 —— g6_caveat（旧文件的 null 会让 G-6 假绿）"
                        "与三态的 g6_p95_le_8s（U-120/A-1：低样本的 stale true 要降档，留 before/after 审计位）")
    p.add_argument("--dry-run", action="store_true", help="打印将执行的场景参数后退出")
    return p


def roll_up(paths: list[str], out: str) -> int:
    """**不发包、不花额度**：把已有回执合成一份 `receipt.json`，顺手把两个派生判定量算对。

    三件事缺一不可：
    ① 下游 W6 的读端只认一个路径（`deploy/loadtest/receipt.json`），而本目录按场景分文件存；
    ② 2026-09-19 之前写出的回执里 `g6_caveat` 是 `null`（那时它只看 `async_degraded`），
       直接喂给 W6 的"取 max(p95) + 无 caveat 即达标"口径 ⇒ **G-6 会被判成 PASS**，
       而那几轮其实是 0 条完成。⇒ 这里用**各场景自己已落盘的 `outcomes`** 重算，不引入任何新测量。
    ③ **A-1（架构 v1.6.6）**：`g6_p95_le_8s` 自 U-120 起是三态，而历史回执里躺着 14 个 stale `true`
       （`admission` 缺失 / `admitted<20` 的格照样给了布尔）⇒ 同一处派生量重算必须把它一起降档，
       否则改了新写端、旧文件还在被引用。**边界**：只动派生判定量（`g6_caveat` / `g6_p95_le_8s`），
       读数（`outcomes` / `latency_ms` / `codes` / `admission`）一律不碰；每次降档留 before/after 审计位。
    """
    merged: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "mode": "roll-up",
        "note": ("本文件由已落盘的回执**合成**，没有重新发包。"
                 "`g6_caveat` 与 `g6_p95_le_8s` 按各场景自带的 outcomes/p95/admission 重算"
                 "（旧文件的 null caveat 会让 G-6 假绿、stale true 会让低样本量具产出可引用布尔）。"
                 "读数未动，只动这两个派生量。"
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
            audit = _recompute_g6_derived(s)
            merged["derived_from"].append({
                "file": Path(p).name, "scenario": s.get("scenario"),
                "requests": s.get("requests"),
                "ok": outcomes.get("ok", 0),
                "p95_ms": (s.get("latency_ms") or {}).get("p95"),
                **audit,
            })
            merged["scenarios"].append(s)
    merged["started_at"] = min(started) if started else None
    merged["finished_at"] = max(finished) if finished else None
    #: T-11②：合成回执也要带 rev ⇒ 否则 G-6 的输入面只有一句 `started_at`、没有代码版本。
    #: ⚠️ `generated_at` 记的是**本次合成**的时刻，不是被合成的那些样本的时刻。
    merged.update(_build_stamp())
    Path(out).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    changed = sum(1 for d in merged["derived_from"] if d["changed"])
    print(f"[合成] {len(paths)} 份 → {out}：{len(merged['scenarios'])} 条场景，"
          f"其中 {changed} 条的派生判定量被重算（caveat 补算 / g6 布尔降档）")

    # ⚠️ 光修合成件不够：W6 的读端支持 `--loadtest-receipt <路径>`，把**任意一份分场景回执**
    #    单独指过去，同样会因为 `g6_caveat` 是 null、或因为 stale 布尔而判 PASS。⇒ 输入文件也就地重算。
    #    只动这两个派生字段，读数（outcomes / latency_ms / codes / admission）一律不碰。
    repaired = 0
    for p in paths:
        raw = json.loads(Path(p).read_text(encoding="utf-8"))
        touched = False
        for s in raw.get("scenarios") or []:
            audit = _recompute_g6_derived(s)
            if audit["changed"]:
                s["g6_derived_audit"] = audit
                touched = True
        if touched:
            Path(p).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            repaired += 1
    if repaired:
        print(f"[就地补算] {repaired} 份输入回执的派生判定量已按其自带读数重算写回"
              "（读数未动；每格留 g6_derived_audit 记 before/after）")
    return 0


def _recompute_g6_derived(s: dict[str, Any]) -> dict[str, Any]:
    """按这一格**自己已落盘的读数**重算两个派生判定量，返回 before/after 审计位。

    刻意不引入任何新测量：`g6_caveat` 只看 `outcomes` + `admission`，`g6_p95_le_8s` 只看
    `latency_ms.p95` + `admission` —— 都是格内既有字段。**关键：两处都必须把 `admission` 传进去**，
    漏传会让带 admission 的新格式回执被盖上"无 admission 字段"这句假话（就地补算曾这么错过一次）。
    """
    admission = s.get("admission")
    old_caveat, old_bool = s.get("g6_caveat"), s.get("g6_p95_le_8s")
    new_caveat = _g6_caveat(s.get("outcomes") or {}, admission)
    new_bool = _g6_boolean((s.get("latency_ms") or {}).get("p95"), admission)
    s["g6_caveat"], s["g6_p95_le_8s"] = new_caveat, new_bool
    return {
        "caveat_before": old_caveat, "caveat_after": new_caveat,
        "bool_before": old_bool, "bool_after": new_bool,
        "changed": (old_caveat, old_bool) != (new_caveat, new_bool),
    }


def verify_openapi_has_query(base: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """取 `<target>/openapi.json` 自证这棵树挂着 `/api/v1/query`（`07 §16.5` 的跑批前义务）。"""
    with urllib.request.urlopen(base.rstrip("/") + "/openapi.json", timeout=timeout_s) as resp:
        doc = json.loads(resp.read().decode("utf-8"))
    paths = sorted((doc.get("paths") or {}).keys())
    return {
        "url": base.rstrip("/") + "/openapi.json",
        "paths_total": len(paths),
        "has_query": "/api/v1/query" in paths,
        "query_paths": [p for p in paths if "/query" in p][:6],
    }


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

    # 🔴 `07 §16.5` 的新义务（架构 09-29 裁定，起因 = W7 把一条预热请求打到了共享 `:8000`）：
    #    发批之前先自证"这个 target 真的挂着 `/api/v1/query`"。共享 api 那台是**阶段 0 骨架**
    #    （`openapi.json` 只有三条 healthz 路由，而 `/healthz` 返 200）⇒ 对它发 `/query` 得 404
    #    是"那棵树的正确行为"，却长得像"被测代码坏了"。裁定原文是"不匹配 ⇒ 该轮全部读数作废"，
    #    所以这里**当场拦**，而不是跑完再宣布作废 —— 跑完已经花钱了。
    try:
        check = verify_openapi_has_query(args.target)
    except Exception as exc:  # 拿不到 openapi 就等于拿不到"打的是谁"的证据
        print(f"[中止] 取不到 {args.target}/openapi.json：{type(exc).__name__}: {exc}"
              "  ⇒ 无法自证被测栈挂着 /api/v1/query（07 §16.5），不发这一批", file=sys.stderr)
        return 2
    receipt["target_check"] = check
    if not check["has_query"]:
        print(f"[中止] target={args.target} 的 openapi 里没有 /api/v1/query"
              f"（paths_total={check['paths_total']}，含 query 的路径={check['query_paths']}）"
              " ⇒ 按 07 §16.5 这一轮读数全部作废，所以根本不该发；请显式 --target 指到被测栈", file=sys.stderr)
        return 2
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
    #: T-11②：G-6 的输入产物自报构建身份（`generated_at` + `git_rev`）。
    receipt.update(_build_stamp())
    Path(args.out).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[回执] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
