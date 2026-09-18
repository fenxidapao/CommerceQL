"""SSE 运行器 —— 把编译好的图跑起来，并把 state 增量转成 SSE 帧（07 §5.6 的接线层）。

层号：L5｜归属窗口：W4（`docs/08 §4.1` 的 `app/api/**`）。

--------------------------------------------------------------------------
一、本模块是"图"与"HTTP"之间**唯一**的桥：三件事，都在这里
--------------------------------------------------------------------------
1. **驱动图**：`graph.astream(..., stream_mode="updates")` → 每个节点跑完拿到一次增量。
   用 `updates` 而不是 `values`：`values` 会把**整份 state** 每次推一遍，
   而 07 §5.2.1 的体积字段（候选/结果行）让整份 state 的序列化代价与"节点数 × 结果集体积"
   成正比 —— 那是纯粹的浪费，且会让心跳被挤掉。
2. **产事件**：增量交给 `graph.events.EventRecorder.on_node()`（**唯一产出点**）。
   本模块**不拼任何事件载荷**：它只负责"什么时候调 on_node"和"帧往哪儿走"。
3. **管生命周期**：`ack` 首帧、15s 心跳、取消轮询、任务状态写回、取消时的审计补齐。

--------------------------------------------------------------------------
二、为什么心跳与取消轮询在**同一个**消费循环里（而不是两个 asyncio 任务）
--------------------------------------------------------------------------
心跳是**帧**（它必须按顺序排在该流的其他帧之间，且入队后由同一个消费者取走）；
取消轮询要做的动作是"取消图任务"。若各起一个任务，就会有两个 writer/两个 cancel 源，
而"谁先发现终态"变成竞态 —— 表现是偶发的"心跳出现在 terminal 之后"（被守卫丢弃并告警）
或"图已取消但流还挂着"。一个循环 = 一个时钟 = 一个取消决定点。

⚠️ 消费循环用 `asyncio.wait_for(queue.get(), timeout=…)`：`wait_for` 取消 `queue.get()`
**不会**丢帧（CPython 的 `Queue.get` 在 `await getter` 被取消时直接 re-raise，
不会调 `get_nowait()`，见其实现）。这一点值得记下来：把 `wait_for` 换成
"`asyncio.wait` + 手动 `get_nowait`"才是会丢帧的写法。

--------------------------------------------------------------------------
三、每请求的上下文与依赖（**不得跨请求复用**）
--------------------------------------------------------------------------
`RunContext`（依赖 + 降级累积 + 分项计时 + 体积数据中转）与 `EventRecorder`
（流级终态守卫）都**每请求一份**：

| 对象 | 复用的后果 |
|---|---|
| `EventRecorder` | `_terminal_emitted` 是**流级**状态 → 上一个请求发过终态后，本请求**一个事件都发不出去** |
| `PlannerEngine`（在 `GraphDeps` 里） | 内部 `_pending` 跨请求串事件（`RELAY §给 W4` 的接线硬约束） |
| `RunContext` | `degradations[]` / `latency_ms` 是累积器 → 上一轮的降级会出现在本轮的 `meta` 里 |

故 `new_deps` 是**工厂**（`deps.GraphRuntime.new_deps`），`state["options"]` 每请求新建。

--------------------------------------------------------------------------
四、P0 的诚实边界（**不得被读成"已完成"**）
--------------------------------------------------------------------------
| 项 | 现状 | 影响 |
|---|---|---|
| `GET /query/{task_id}` 的 `data`（结果行） | **恒 `null`** | 结果行的唯一允许位置是结果集缓存 `result:{tenant}:{task_id}`（07 §5.2.1），而 `CachePort` **全仓无实现**（`mask` 节点因此走"写失败只告警"的已登记路径）⇒ 写入通道不存在。`chart`/`insight`/`meta`/`sql` 不是体积数据，照常回填 |
| `audit_ref` | **恒 `null`** | `AuditSinkPort.write_pre/write_supp` 的返回类型是 `None`（不回 id），且 `GraphState` 无该字段（07 §5.2 穷举）⇒ 无来源。不编一个 id |
| `progress` | **恒 `null`** | 文档只在 §A.2 的示例里出现 `0.7`，**没有任何映射规则**（阶段→数值）。按 U-22 不发明数字 ⇒ 不下发。前端不消费该字段（06 §2301 只约束评测页"不显示虚假百分比"） |
| 转异步（`switched_to_async`） | **不可达** | `edges.route_after_gate3` 的 `_should_go_async` 缺"预估延迟"载体（`gate3_cost` 的 `GateResult` 无该字段），该分支恒 `False` 且已有专门测试钉住 —— 接线后那条测试会红 |
| 事件重放（`event_buffer`） | **未接线** | 断线重连不能重放（附录 A 未把重放列为必需端点）。键已备好 |
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from app.api import errors, sse
from app.api.state_store import RedisStateStore
from app.auth.context import bind_identity, reset_identity
from app.core.contracts import IdentityContext
from app.core.enums import ErrorCode, Outcome, SseEvent, Stage, TaskStatus
from app.graph.build import GRAPH_RECURSION_LIMIT, GRAPH_VERSION
from app.graph.context import (
    GraphDeps,
    RunContext,
    clear_run_context,
    set_run_context,
)
from app.graph.events import Emission, EventRecorder, meta_payload
from app.graph.nodes import AUDIT_PRE, ERROR_OUT, PRESENT
from app.graph.nodes._shared import write_audit_pre
from app.graph.state import GraphState, initial_state
from app.llm import LlmCallContext, set_call_context
from app.obs.logging import get_logger

__all__ = [
    "CANCEL_POLL_INTERVAL_S",
    "RunOutcome",
    "RunRequest",
    "SseRunner",
    "thread_id_of",
]

_log = get_logger(__name__)

#: 取消标志的轮询间隔。
#:
#: ⚠️ 不与心跳（15s）共用：心跳是**向前端证明连接还活着**，60s 才需要一次也无所谓；
#: 取消是**用户按了停止按钮**，15s 才响应等于"点了没反应"。1s 的成本是一条 `GET`
#: （且只在流还活着时才发生）—— 这个代价换的是"停止按钮真的有用"。
CANCEL_POLL_INTERVAL_S: Final[float] = 1.0

#: 消费循环单次等待的上限。取心跳与取消轮询的**较小者**，让两件事都能按时发生。
_TICK_MAX_S: Final[float] = min(sse.HEARTBEAT_INTERVAL_S, CANCEL_POLL_INTERVAL_S)

#: 消费循环单次等待的下限（防"tick 已经用掉大半"时算出 0 或负数 → 忙等）。
_TICK_MIN_S: Final[float] = 0.05

#: §16.2 占位帧的判定阈值（秒）。
#:
#: 🔴 **1.6 而不是表里的 1.2**（U-66 订正原文：照 `normalize_intent` 的**分配** 1.6s 判定，
#: "不是旧值 1.2s"）：表 1.2s 是 normalize+intent 的预算，加上建流/发射余量才是 1.5s 的
#: NFR 口径 —— 占位判定放余量之内才会把"还在预算内跑"的请求误判成需要占位。
#: 这是 **NFR-1.2 的唯一执行点**（网关根修后没有人替 W4 发这个帧）。
PLACEHOLDER_AFTER_S: Final[float] = 1.6


# ============================================================================
# 请求与结果
# ============================================================================


@dataclass(frozen=True, slots=True)
class RunRequest:
    """一次 run 的全部输入（**由端点构造**，本模块不碰 HTTP 对象）。

    ⚠️ `options` 是**已 `model_dump()` 的纯 dict**：`graph/edges.py` 的
    `_should_go_async` 用 `isinstance(options, dict)` 判定（它读 `async_if_slow` 等键）。
    传 pydantic 模型进去会让转异步判定**静默恒假** —— 用户勾了"慢就转异步"却永远不生效。
    """
    identity: IdentityContext
    question: str
    options: Mapping[str, Any] | None = None
    idempotency_key: str | None = None
    #: `false` → `stage=sql_ready` 省略 `sql` 字段（07 §5.6；事件照发）。
    explain: bool = True


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """一轮 run 的结论（**端点用它做会话记账**，不再回头翻 state）。

    ⚠️ 它是**快照**而不是"重新做一次判定"：`status` 的推导只发生在 `task_status_of()`
    一处，端点不得自己再按 `terminal.event` 判一遍 —— 两处判定的漂移表现是
    "轮询说 complete、审计说 failed"。
    """

    status: TaskStatus
    #: `terminal.event` 的原值（`complete` / `clarify` / `refuse` / `error`），未收口为 `None`。
    terminal_event: str | None
    reason: str | None
    error_code: str | None
    plan_summary: Mapping[str, Any] | None
    bundle_version: str
    cancelled: bool
    nodes: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()


# ============================================================================
# 纯函数：终态 → 任务状态
# ============================================================================


def task_status_of(state: Mapping[str, Any], *, cancelled: bool = False) -> TaskStatus:
    """`terminal` + `outcome` → `TaskStatus`（**唯一的投影点**）。

    对齐依据（补充契约 C-05 的原话："`complete` + 后 4 个与 `Outcome` 语义对齐"）：

    | `state.terminal.event` | `state.outcome` | `TaskStatus` |
    |---|---|---|
    | `complete` | `success` | `complete`（`"queued"/"processing"` 之外的第 3 个生命周期态） |
    | `complete` | `degraded` | `degraded`（§14.2 F5 的转异步路径） |
    | `clarify` | `clarify` | `clarify` |
    | `refuse` | `refuse` | **`refused`** |
    | `error` | `failed` | `failed` |
    | （无终态） | 任意 | `failed` + 告警（图未收口 = 缺陷，不是"成功"） |

    ⚠️ `refuse` → `refused` 这两个字面量**故意不同**（C-05 明文）：status 是任务终态表述，
    outcome 是审计结论，两套取值集各归各的 —— 用字面量相等去判"是不是拒答"是本条注释要防的事。
    ⚠️ `cancelled` **不进 `Outcome`**（用户侧取消不是审计结论），故它只能由入参表达。
    """
    if cancelled:
        return TaskStatus.CANCELLED
    terminal = state.get("terminal") or {}
    event = str(terminal.get("event") or "")
    outcome = str(state.get("outcome") or "")
    if event == "complete":
        return TaskStatus.DEGRADED if outcome == Outcome.DEGRADED.value else TaskStatus.SUCCEEDED
    if event == "clarify":
        return TaskStatus.CLARIFY
    if event == "refuse":
        return TaskStatus.REFUSE
    if event == "error":
        return TaskStatus.FAILED
    return TaskStatus.FAILED


def thread_id_of(identity: IdentityContext) -> str:
    """检查点线程 ID：`{tenant}:{user}:{session}`（07 §5.4 逐字，FR-10.4）。

    ⚠️ 三元组而**不是** `session_id`：`session_id` 由客户端传入（`POST /query` 的
    `session_id` 字段），只用它做 `thread_id` 就能让 A 租户拿 B 租户的 `session_id`
    读到 B 的检查点（跨租户续会话）。租户 + 用户进 `thread_id` 是**隔离**机制，不是命名偏好。
    """
    return f"{identity.tenant_id}:{identity.user_id}:{identity.session_id}"


# ============================================================================
# 运行器
# ============================================================================


@dataclass(slots=True)
class _RunTrace:
    """一次 run 的**观测累积器**（图外侧）：state 增量 + 已跑节点 + 取消标志。

    ⚠️ 它的存在理由与 `RunContext` 的累积器不同：后者累积"同一个键被多次写"的量
    （降级/计时），本类累积的是**增量合并后的全量 state** ——
    因为事件载荷（`meta`）与终态投影（`task_status_of`）需要的是
    "第 13 个节点跑完时，state 里 **10 组**字段分别是什么"，而那只有合并后才知道。

    ⚠️ **必须用 `initial_state()` 播种**（`Merge` 的第一次调用）：组 1 的身份字段由
    API 层直接写进初始 state，**不经任何节点的增量** —— 而 `trace_id` / `tenant_id`
    正是 `meta_payload` 与 `write_audit_pre` 要用的。不播种的表现是
    `meta.trace_id=None`（`missing_meta_keys` 会判它契约违规）与取消路径审计
    `KeyError: 'tenant_id'`。
    """

    state: dict[str, Any] = field(default_factory=dict)
    nodes: list[str] = field(default_factory=list)
    cancelled: bool = False
    #: 终态守卫记录的契约违规（`EventRecorder.violations`）—— 在 `finally` 里取一次快照。
    violations: tuple[str, ...] = ()

    def merge(self, update: Mapping[str, Any]) -> None:
        self.state.update(update)

    def mark(self, node: str) -> None:
        self.nodes.append(node)

    def seen(self, node: str) -> bool:
        return node in self.nodes


class SseRunner:
    """一次 run 的执行体（**每请求一份**，见模块 docstring §三）。

    用法（端点）：

        runner = SseRunner(graph=..., store=..., new_deps=...)
        async for frame in runner.stream(req):
            yield frame
        outcome = runner.outcome          # 流结束后（含断连）都可读

    ⚠️ `outcome` 在 `stream()` 的 `finally` 里赋值 ⇒ **即使客户端中途断连也一定有值**。
    端点依赖这条性质做会话记账（断连的那一轮也要进历史，否则用户会看到"问了没记录"）。
    """

    __slots__ = (
        "_cancel_poll_s",
        "_graph",
        "_graph_version",
        "_heartbeat_s",
        "_new_deps",
        "_placeholder_after_s",
        "_placeholder_sent",
        "_store",
        "outcome",
    )

    def __init__(
        self,
        *,
        graph: Any,
        store: RedisStateStore,
        new_deps: Callable[[], GraphDeps],
        graph_version: str = GRAPH_VERSION,
        heartbeat_s: float = sse.HEARTBEAT_INTERVAL_S,
        cancel_poll_s: float = CANCEL_POLL_INTERVAL_S,
        placeholder_after_s: float = PLACEHOLDER_AFTER_S,
    ) -> None:
        self._graph = graph
        self._store = store
        self._new_deps = new_deps
        self._graph_version = graph_version
        self._heartbeat_s = heartbeat_s
        self._cancel_poll_s = cancel_poll_s
        # §16.2 占位（U-66）：`placeholder_after_s` 可注入（测试压小验证"真的会发"），
        # 生产装配不传 —— 契约值只有 `PLACEHOLDER_AFTER_S` 一份来源。
        self._placeholder_after_s = placeholder_after_s
        self._placeholder_sent = False
        self.outcome: RunOutcome | None = None

    # -- 主流程 -------------------------------------------------------------

    async def stream(self, req: RunRequest) -> AsyncIterator[bytes]:
        """跑图并逐帧产出 SSE 字节（**首个 yield 是 `ack`**，W5 的硬要求）。"""
        recorder = EventRecorder(encoder=sse.encode, explain=req.explain)
        run_context = RunContext(self._new_deps(), recorder=recorder)
        state = initial_state(
            req.identity,
            raw_question=req.question,
            # ⚠️ `options` 必须是**纯 dict**（见 `RunRequest` 的注释）。
            options=dict(req.options) if req.options else None,
            idempotency_key=req.idempotency_key,
        )
        #: 用初始 state 播种累积器（组 1 的身份字段不经任何节点的增量，见 `_RunTrace`）。
        trace = _RunTrace(state=dict(state))
        #: 15s 心跳的时限按**构造参数**取（测试可以把它压到 0.05s 来验证"心跳真的会发"，
        #: 而不必等 15 秒 —— 真实间隔由 `sse.HEARTBEAT_INTERVAL_S` 保证，装配点不传参）。
        run_token = set_run_context(run_context)
        identity_token = bind_identity(req.identity)
        drive = asyncio.create_task(self._drive(state, req, recorder, run_context, trace))
        try:
            # 首帧：`ack`（`task_id` 是停止 / 看门狗 / 轮询三件事的共同前提）。
            recorder.ack(task_id=req.identity.task_id, session_id=req.identity.session_id)
            # 任务状态：进图前先落 `processing`（轮询端点在 SSE 建连后立刻可用）。
            await self._safe_put_task(req, status=TaskStatus.RUNNING)
            async for frame in self._pump(recorder, req, trace, drive):
                yield frame
        finally:
            # ⚠️ `finally` 里**先**定结论（同步、绝不失败），再做需要 await 的清理：
            # 客户端断连时本生成器会被 `GeneratorExit`/`CancelledError` 打断，
            # 那时任何 `await` 都可能再抛 —— 结论必须已经在手上。
            trace.violations = recorder.violations
            self.outcome = self._conclude(req, run_context, trace)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._shutdown(drive, recorder, run_context, req, trace)
            clear_run_context(run_token)
            reset_identity(identity_token)

    # -- 消费循环（心跳 + 取消轮询 + 出帧） ---------------------------------

    async def _pump(
        self,
        recorder: EventRecorder,
        req: RunRequest,
        trace: _RunTrace,
        drive: asyncio.Task[None],
    ) -> AsyncIterator[bytes]:
        last_beat = time.monotonic()
        # §16.2 占位的计时起点 = 消费循环进入时刻。它与 `ack`（在 `stream` 里、本函数
        # 之前发出）的间隔是同任务内的两次同步调用，<1ms —— 把"建流"定义在这里
        # 而不是再传一个时间戳进来，是省一个参数换不来偏差的交换。
        started = last_beat
        last_poll = last_beat
        while True:
            now = time.monotonic()
            wait_s = min(
                self._heartbeat_s - (now - last_beat),
                self._cancel_poll_s - (now - last_poll),
            )
            # 🔴 占位**必须**参与 tick 周期计算：`wait_for` 会一直等到最近的 tick，
            # 而占位阈值（1.6s）小于心跳（15s）—— 不把它算进等待，占位判定
            # 要等到下一次心跳 tick 才有机会跑，NFR-1.2 就在 produces 路径上失效。
            # （契约测试以 0.05s/10s 的极端比例抓住了这一点。）
            if not self._placeholder_sent and not drive.done():
                wait_s = min(wait_s, self._placeholder_after_s - (now - started))
            try:
                frame = await asyncio.wait_for(
                    recorder.queue.get(), timeout=max(wait_s, _TICK_MIN_S)
                )
            except TimeoutError:
                frame = None
            else:
                if frame is None:  # 哨兵：图已结束且队列已空
                    return
                last_beat = time.monotonic()
                yield frame
                continue

            now = time.monotonic()
            # §16.2 占位（U-66，NFR-1.2 的唯一执行点）——放在心跳之前判：
            # 1.6s < 15s，占位永远先到期；发完即止（`_placeholder_sent` 单次闸门）。
            # 四个条件缺一不可：图已结束（`drive.done()`）就不需要进度占位；
            # 已有任何 stage 帧（真值已到）就**不覆盖**——占位只补"一个字都没有"的空白。
            if (
                not self._placeholder_sent
                and not drive.done()
                and not recorder.has_stage_emission()
                and now - started >= self._placeholder_after_s
            ):
                self._placeholder_sent = True
                recorder.stage_placeholder()
            if now - last_beat >= self._heartbeat_s:
                # 心跳是**唯一**允许在终态之后发出的事件（07 §14.3 约束 3）：
                # 转异步场景下 `complete` 先到、用户还要等轮询，此时断流前端会误判连接异常。
                recorder.heartbeat()
                last_beat = now
            if now - last_poll >= self._cancel_poll_s:
                last_poll = now
                if await self._cancel_requested(req):
                    trace.cancelled = True
                    _log.info(
                        "run_cancelled",
                        task_id=req.identity.task_id,
                        extra_fact="取消标志命中 → 取消图任务（07 §8.3 步②）",
                    )
                    drive.cancel()
                    # ⚠️ **不发终态事件**（§14.2 E7 原文："无事件（流已断）"）。
                    # 取消是"客户端已经不要这一轮了"，补一个 error 帧反而是编造故障；
                    # 审计留痕由 `_shutdown` 补齐（§8.3 要求②：取消也必须留痕）。
                    return

    async def _cancel_requested(self, req: RunRequest) -> bool:
        """读取消标志。**读失败不取消**（Redis 抖动不该把用户的一轮查询掐掉）。"""
        try:
            return await self._store.is_cancel_requested(req.identity.task_id)
        except Exception as exc:
            _log.warning(
                "cancel_poll_failed",
                task_id=req.identity.task_id,
                error_type=type(exc).__name__,
                extra_fact="读取消标志失败 → 按「未取消」继续（不因基础设施抖动掐掉查询）",
            )
            return False

    # -- 生产者：跑图 -------------------------------------------------------

    async def _drive(
        self,
        state: GraphState,
        req: RunRequest,
        recorder: EventRecorder,
        run_context: RunContext,
        trace: _RunTrace,
    ) -> None:
        """驱动图；每个节点跑完 → `on_node(node, update, extras=…)`。

        ⚠️ **异常兜底在这里**：图内部（节点）抛出的未捕获异常若不处理，
        `recorder.close()` 一放哨兵，流就以"无终态"结束 —— 而前端按 §A.1.4 只能在 90s
        看门狗超时后才提示异常。故兜底发 `error(INTERNAL)`：
        它是**工程故障**（不是产品结论），符合 §7.6.1 的 refuse/error 边界。
        """
        config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id_of(req.identity)},
            "recursion_limit": GRAPH_RECURSION_LIMIT,
        }
        # 🔴 LLM 计量上下文（W3A §3 / W3B RELAY §3）：不设 ⇒ 计量归 `"(unset)"` ——
        # 那是**可见**的错误，但积攒一整天后"按租户对账"就废了。
        # 设置点选在**本任务**（`_drive` 由每请求一个的 `asyncio.create_task` 驱动）而不是
        # `stream()`：contextvar 写进哪个 task 的上下文，就只在那个 task 里可见 ——
        # 本任务随请求生灭 ⇒ 计量上下文的作用域被**钉死在一次 run 内**，
        # 端点任务与后续请求都读不到它（不需要"事后清除"，也就不依赖
        # `app.llm` 目前没有的 `clear_call_context`）。
        set_call_context(
            LlmCallContext(
                task_id=req.identity.task_id,
                tenant_id=req.identity.tenant_id,
                # ⚠️ `user_id` = JWT `sub`（`IdentityContext.user_id`）；三个字段都只进
                #    计量聚合，**永不出站**（N-12 的 PII 禁令对 payload 生效，不对此处）。
                user_id=req.identity.user_id,
            )
        )
        try:
            async for chunk in self._graph.astream(state, config, stream_mode="updates"):
                for node, update in dict(chunk).items():
                    if update is None:
                        # 🔴 **LangGraph 用 `None` 表示"该节点返回了空增量"**（不是 `{}`）。
                        # 这不是边角情况：`trusted_context` 恒返回 `{}`，而 `intent` 在
                        # **合并档**下也只返回 `{}`（它的事实由 `normalize` 一起产出）。
                        # 若把 `None` 当作"非法增量"跳过，`stage=intent` 这一帧就永远发不出去
                        # —— 那是前端进度条的第一段，且 §5.6 要求它的 `elapsed_ms` **含 normalize**。
                        update = {}
                    elif not isinstance(update, Mapping):
                        # 真·非法（列表/字符串/对象）：如实记一条并跳过，不当成空增量假装正常。
                        _log.error(
                            "node_update_not_mapping",
                            node=node,
                            task_id=req.identity.task_id,
                            update_type=type(update).__name__,
                            extra_fact="节点返回了非 Mapping 增量 → 本轮按空增量处理并告警",
                        )
                        update = {}
                    before = len(recorder.emissions)
                    trace.merge(update)
                    trace.mark(node)
                    recorder.on_node(
                        node, update, extras=self._extras(node, update, run_context, trace)
                    )
                    await self._after_node(recorder, before, req)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.error(
                "graph_run_failed",
                task_id=req.identity.task_id,
                error_type=type(exc).__name__,
                detail=str(exc)[:300],
                extra_fact="图未收口 → 补发 error(INTERNAL)，不留一条无终态的流（N-08）",
            )
            mapping = errors.map_code(ErrorCode.INTERNAL)
            recorder.push(
                Emission(
                    SseEvent.ERROR,
                    {
                        "code": mapping.code.value,
                        "message": mapping.message,
                        "retryable": mapping.retryable,
                    },
                )
            )
        finally:
            recorder.close()

    def _extras(
        self,
        node: str,
        update: Mapping[str, Any],
        run_context: RunContext,
        trace: _RunTrace,
    ) -> Mapping[str, Any] | None:
        """不属于 `GraphState` 的事件载荷（07 §5.2 字段是穷举的，不得为发事件新增键）。

        三处，逐条给出为什么只能走这条侧信道：

        | 节点 | 载荷 | 为什么不在 state 里 |
        |---|---|---|
        | `audit_pre` | `rows` | 结果行是**体积字段**（§5.2.1）：全量在结果集缓存/内存通道，state 里只有 `result_ref` |
        | `present` | `meta` | 它由 **10 组**字段拼成（`scope` 在组 7、`retrieval_mode` 在组 4、计量在组 11…），且 `bundle_version` **没有 state 载体**（见 `events.meta_payload` 的表） |
        | `error_out` | `message` / `detail` / `retryable` | 文案与可重试性由 **L5** 的 `api/errors.map_code` 产出，而 `app.graph`（L4）不得 import L5 |
        """
        if node == AUDIT_PRE:
            # `take_rows()` 是**取走即清**（单次赋值语义）：结果行只在这一刻出内存通道。
            return {"rows": run_context.take_rows()}
        if node == PRESENT:
            return {
                "meta": meta_payload(trace.state, bundle_version=run_context.bundle_version)
            }
        if node == ERROR_OUT:
            terminal = update.get("terminal") or {}
            code = str(terminal.get("code") or ErrorCode.INTERNAL.value)
            try:
                error_code = ErrorCode(code)
            except ValueError:
                error_code = ErrorCode.INTERNAL
            mapping = errors.map_code(error_code)
            payload: dict[str, Any] = {
                "code": mapping.code.value,
                "message": mapping.message,
                "retryable": mapping.retryable,
            }
            # `detail` 只给能处置它的角色（W5 RELAY §1.1 末列；判据在 `api/errors`）。
            if errors.detail_allowed_for(self._role_of(update)) and mapping.detail:
                payload["detail"] = mapping.detail
            return payload
        return None

    @staticmethod
    def _role_of(update: Mapping[str, Any]) -> Any:
        """`error_out` 增量里没有身份（身份在组 1，是**早期**节点的产出）。

        ⚠️ 这里读不到就是读不到：`error_out` 的增量只有 `terminal` / `outcome` / 计量。
        故 `detail` 的角色判据回退到**已绑定身份**（`app/auth/context.py` 的第 7 步）——
        那条路径在两处一致：`api/errors` 的全局处理器用的也是它。
        """
        from app.auth.context import identity_or_none

        context = identity_or_none()
        return context.role if context is not None else None

    async def _after_node(
        self, recorder: EventRecorder, before: int, req: RunRequest
    ) -> None:
        """节点产事件之后：把 `stage` 写进任务状态（供轮询端点显示进度段）。

        ⚠️ `stage` 从**已产出的事件**里读（不是本模块自己算一份映射）：
        "哪个节点对应哪个 stage"是 `graph/events.py` 的事实（07 §5.6 的"发出时机"列），
        在这里再写一张表就是同一个事实的第二份定义。
        """
        stage: Stage | None = None
        for emission in recorder.emissions[before:]:
            if emission.stage is not None:
                stage = emission.stage
        if stage is None:
            return
        await self._safe_put_task(req, status=TaskStatus.RUNNING, stage=stage.value)

    # -- 收尾 ---------------------------------------------------------------

    async def _shutdown(
        self,
        drive: asyncio.Task[None],
        recorder: EventRecorder,
        run_context: RunContext,
        req: RunRequest,
        trace: _RunTrace,
    ) -> None:
        """等图任务落地 → 取消留痕 → 最终任务状态写回。

        ⚠️ 顺序不能换：**先**等 `drive`（图要么跑完要么被取消），**再**写审计与状态 ——
        反过来会在图还在跑时写一个"最终状态"，随后被节点自己的写回覆盖（前端看到状态回退）。
        """
        if not drive.done():
            drive.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drive
        if trace.cancelled:
            await self._record_cancellation(req, run_context, trace)
        await self._persist_clarify(req, trace)
        await self._write_final_task(req, run_context, trace)

    async def _persist_clarify(self, req: RunRequest, trace: _RunTrace) -> None:
        """终态为 `clarify` 时把澄清上下文落 Redis（附录 A §A.4）。

        🔴 **不落它，`POST /clarify` 就恒返回 `CLARIFY_EXPIRED`(410)**：
        前端拿到 `clarify` 事件、用户选了选项、`POST /clarify {clarify_id}` 回来时，
        服务端没有任何记录可以校验这个 `clarify_id` 与 `selected_value`。
        图谱侧只**产出** `clarify_id`（`clarify_out._new_clarify_id`），
        它不知道 HTTP 层的存储键，也不该知道 —— 故这一跳只有接入层能接。

        ⚠️ 写失败**不阻断**（与 `_record_cancellation` 同理）：这一轮的终态已经发出去了，
        为"存不下澄清上下文"再抛异常，会把一个已定的 `clarify` 结果变成 500。
        但**必须打 ERROR 日志**——它的后果是"用户点选项后拿 410"，只有日志能指回来。
        """
        terminal = trace.state.get("terminal") or {}
        if not isinstance(terminal, Mapping) or terminal.get("event") != SseEvent.CLARIFY.value:
            return
        clarify = trace.state.get("clarify")
        clarify_id = str(clarify.get("clarify_id") or "") if isinstance(clarify, Mapping) else ""
        if not clarify_id:
            _log.error(
                "clarify_context_missing_id",
                task_id=req.identity.task_id,
                extra_fact="终态是 clarify 但 state 里没有 clarify_id ⇒ 端点无法存上下文（用户将拿 410）",
            )
            return
        raw_options = clarify.get("options") if isinstance(clarify, Mapping) else None
        reason = clarify.get("reason") if isinstance(clarify, Mapping) else None
        try:
            await self._store.put_clarify(
                req.identity,
                clarify_id=clarify_id,
                # ⚠️ 存**原始问题**（`req.question`）而不是已归一化的问句：
                #    重跑要从 `normalize` 完整走一遍（FR-9.2），拿归一化后的文本会丢失
                #    "用户原话"这个事实，且让 `raw_question` 这个字段名名不副实。
                raw_question=req.question,
                reason=None if reason is None else str(reason),
                options=raw_options if isinstance(raw_options, (list, tuple)) else (),
                # ⚠️ 原轮 `options` 一起存：附录 A §A.4 的请求体里没有 `options`，
                #    不继承就会用 DTO 默认值（max_rows / explain 静默改变）。见 `ClarifyContext` 注释。
                run_options=req.options,
            )
        except Exception as exc:
            _log.error(
                "clarify_context_write_failed",
                task_id=req.identity.task_id,
                clarify_id=clarify_id,
                error_type=type(exc).__name__,
                extra_fact="澄清上下文未落库 ⇒ 用户回答澄清时会拿到 CLARIFY_EXPIRED(410)",
            )

    async def _record_cancellation(
        self, req: RunRequest, run_context: RunContext, trace: _RunTrace
    ) -> None:
        """取消留痕（§8.3 要求②：**取消也必须写审计**）。

        ⚠️ 分两段判：段 1 已在 `audit_pre` 落库 ⇒ 补段 2；否则补段 1（结果从未下发）。
        反过来做会**重复写段 1**（同一次 run 两行 `audit_log`），而"审计行数"是
        §14.5 的统计口径之一。
        """
        state: GraphState = trace.state  # type: ignore[assignment]
        try:
            if trace.seen(AUDIT_PRE):
                await run_context.deps.audit.write_supp(
                    req.identity, _supp_payload(run_context, trace.state)
                )
            else:
                wrote = await write_audit_pre(state, outcome=Outcome.FAILED)
                if not wrote:
                    _log.error(
                        "cancel_audit_missing",
                        task_id=req.identity.task_id,
                        extra_fact="取消路径的段 1 审计未落库（§8.3 要求②：取消也要留痕）",
                    )
        except Exception as exc:
            # 审计补写失败**不阻断**（段 2 的语义，§14.2 G2）：这一轮已经结束了，
            # 为它抛异常只会把"用户取消"变成 500。
            _log.error(
                "cancel_audit_failed",
                task_id=req.identity.task_id,
                error_type=type(exc).__name__,
            )

    async def _write_final_task(
        self, req: RunRequest, run_context: RunContext, trace: _RunTrace
    ) -> None:
        """把最终状态投影进任务记录（`GET /query/{task_id}` 读它）。"""
        status = task_status_of(trace.state, cancelled=trace.cancelled)
        terminal = trace.state.get("terminal") or {}
        extra: dict[str, Any] = {
            "sql": trace.state.get("sql_text"),
            # 结果行恒 `None`：唯一允许位置是结果集缓存，而 `CachePort` 无实现（见模块 docstring §四）。
            "data": None,
            "chart": _chart_payload(trace.state),
            "insight": _insight_payload(trace.state),
            "meta": meta_payload(trace.state, bundle_version=run_context.bundle_version),
            # 无来源（`AuditSinkPort` 不回 id、state 无该字段）—— 不编一个。
            "audit_ref": None,
            # 文档无映射规则（§A.2 只有一个 0.7 的示例）—— 按 U-22 不下发。
            "progress": None,
            "terminal_event": terminal.get("event"),
        }
        await self._safe_put_task(req, status=status, extra=extra)

    async def _safe_put_task(
        self,
        req: RunRequest,
        *,
        status: TaskStatus,
        stage: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """写任务状态。**写失败只告警**：它是**投影**（权威仍是图的终态与审计），
        而"Redis 抖动导致整个查询 500"是把旁路设施当成了主链路。"""
        try:
            await self._store.put_task(req.identity, status=status, stage=stage, extra=extra)
        except Exception as exc:
            _log.warning(
                "task_state_write_failed",
                task_id=req.identity.task_id,
                status=status.value,
                error_type=type(exc).__name__,
                extra_fact="任务状态是投影（权威=图终态+审计）；写失败只影响轮询端点",
            )

    def _conclude(
        self, req: RunRequest, run_context: RunContext, trace: _RunTrace
    ) -> RunOutcome:
        """定结论（同步、无 I/O —— 必须在 `finally` 的第一时间可调用，见 `stream`）。"""
        status = task_status_of(trace.state, cancelled=trace.cancelled)
        terminal = trace.state.get("terminal") or {}
        return RunOutcome(
            status=status,
            terminal_event=None if terminal.get("event") is None else str(terminal["event"]),
            reason=None if terminal.get("reason") is None else str(terminal["reason"]),
            error_code=None if terminal.get("code") is None else str(terminal["code"]),
            plan_summary=_mapping_or_none(trace.state.get("plan_summary")),
            bundle_version=run_context.bundle_version,
            cancelled=trace.cancelled,
            nodes=tuple(trace.nodes),
            violations=trace.violations,
        )


# ============================================================================
# 载荷投影（**与 SSE 帧同构**：§A.2 原文"含 sql/data/chart/insight/meta（与 SSE 同构）"）
# ============================================================================


def _chart_payload(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """`chart` 事件的载荷形状（`chart_type` + `option`）—— 与 `events.emissions_for_node` 逐字一致。

    ⚠️ 这里**重写**那两个键名而不是复用 `events` 的内部函数：`events` 的组装发生在
    "该发哪个事件"的判定里（`if chart:` 之类），把它拆出来给别处用会把
    "发射决策"与"载荷形状"重新搅在一起。两处一致由 `tests/contract/` 钉
    （轮询响应的 `chart` 与 SSE 的 `chart` 帧同形）。
    """
    chart = state.get("chart_spec")
    if not isinstance(chart, Mapping) or not chart:
        return None
    return {"chart_type": chart.get("chart_type"), "option": chart.get("option")}


def _insight_payload(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """`insight` 事件的载荷形状（`text` + `caveats[]` + `citations[]`）。"""
    insight = state.get("insight")
    if not isinstance(insight, Mapping) or not insight:
        return None
    return {
        "text": insight.get("text"),
        "caveats": list(insight.get("caveats") or ()),
        "citations": list(insight.get("citations") or ()),
    }


def _supp_payload(run_context: RunContext, state: Mapping[str, Any]) -> dict[str, Any]:
    """段 2 审计的载荷（**取消路径专用**）。

    字段集与 `audit_supp` 节点逐字一致 —— 那个节点只在"成功收口"时才跑，
    而取消路径图被掐断、它不会执行。此处按同一形状补齐：
    "取消也要留痕"（§8.3 要求②）不等于"可以少几个列"。
    """
    from app.core.enums import LatencyKey

    tokens = run_context.tokens_payload()
    return {
        "input_tokens": int(tokens.get("input", 0)),
        "output_tokens": int(tokens.get("output", 0)),
        "cache_hit_tokens": int(tokens.get("cache_hit", 0)),
        "cost_cny": run_context.cost_cny(),
        "latency_ms_present": int(run_context.latency_ms().get(LatencyKey.PRESENT.value, 0)),
        "chart_type": None,
        "insight_hash": None,
        "degradations": [dict(item) for item in run_context.degradations()],
    }


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    """`plan_summary` → Mapping（`OpaquePayload` 的实际形态；非 Mapping 如实回 `None`）。"""
    return value if isinstance(value, Mapping) else None
