"""SSE 运行器契约（`app/api/runner.py`）—— 转录断言 + 任务状态投影 + 取消路径。

层号：tests（跨层）｜归属窗口：W4（`docs/08 §4.1`：`tests/contract/**`）。

--------------------------------------------------------------------------
一、本文件覆盖什么（以及 T9 还要补什么）
--------------------------------------------------------------------------
本文件是 T5 的**落地带测**（与 T2 的先例一致：缺陷修复当场带回归）。它覆盖：

| # | 覆盖项 | 依据 |
|---|---|---|
| 1 | 四条出口路径的 **SSE 转录**：首帧 `ack`、`terminal` 布尔恒在、**恰 1 个 `terminal:true`** | N-08 / DoD① |
| 2 | 终态事件与 `RunOutcome.status` 一致（同一份 state 两处投影不得分叉） | C-05 |
| 3 | 取消路径：**不发终态** + **审计留痕** + 状态落 `cancelled` | §14.2 E7 / §8.3 要求② |
| 4 | 心跳：慢图期间真的会发，且恒 `terminal:false` | §A.1.4 / §14.3 约束 3 |
| 5 | `stage` 取值只落 6 个合法值 | §14.3 约束 8 |
| 6 | 任务状态写回：所有权校验、取消幂等、幂等键三态、澄清上下文一次性 | §A.2 / §A.3 / §A.4 / §A.12 |

⚠️ **T9 仍需补的**（本文件做不到，原因写在这里而不是留在 TODO 里）：
· **成功路径**的转录（`data` 帧的 `rows` 走内存通道、`meta` 的 7 键齐全、`chart`/`insight`）
  —— 需要一条能跑到 `execute` 的假依赖链（retrieval/binding/executor/mask/present 五个假件），
  与 `tests/graph_snapshot/test_graph_wiring.py` 目前只有的"早退路径"假件不是同一规模，归 T9。
· 07 §14.3 的 **8 条事件序列约束**逐条断言与 §14.2 **A–H 决策表**逐行覆盖 —— 归 T9。

--------------------------------------------------------------------------
二、为什么用同步用例 + `asyncio.run`（而不是 `async def test_`）
--------------------------------------------------------------------------
同 `test_graph_wiring.py` §三：`pytest-asyncio 1.4` 自建的循环不认
`set_event_loop_policy`，Windows 上会让 `psycopg` 撞 `ProactorEventLoop`。
本文件不碰数据库，但保持同一惯例。

--------------------------------------------------------------------------
三、为什么用 `tests/unit/_redis_fake.py` 的 `FakeRedis`（跨目录引用）
--------------------------------------------------------------------------
`RedisStateStore`（本窗口新建）的读端义务（所有权、幂等、一次性澄清）**必须被验**，
而它需要一个 Redis 客户端。用 `AsyncMock(spec=Redis)` 会让"调了不存在的方法"变成静默通过
（`_redis_fake.py` 的文件头把这条理由写得很清楚），故**复用同一份替身**而不是另造一个。
本窗口对 `_redis_fake.py` 的改动是**纯追加**（`ex=` 秒级 TTL、`lpush`/`lrange`/`expire`），
不改变 W1B 既有用例的行为 —— 已在 `reports/w4/RELAY.md` 登记为跨窗口改动。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.api import sse
from app.api.runner import RunRequest, SseRunner, task_status_of, thread_id_of
from app.api.state_store import RedisStateStore
from app.cache import keys as cache_keys
from app.core.contracts import IdentityContext, TokenUsage
from app.core.enums import RefuseReason, Role, SseEvent, Stage, TaskStatus
from app.core.errors import ContractViolationError
from app.graph.build import build_graph
from app.graph.context import GraphDeps, current_run_context
from app.graph.events import Emission, EventRecorder
from app.llm.errors import LlmRefused, LlmTimeout
from app.planner.engine import LlmCallMeta, UnderstandOutcome
from app.planner.schemas import IntentKind
from tests.unit._redis_fake import FakeRedis

# ============================================================================
# 夹具
# ============================================================================

_IDENTITY = IdentityContext(
    trace_id="tr-run-1",
    task_id="tk-run-1",
    session_id="ss-run-1",
    tenant_id="tenant-run",
    user_id="user-run-1",
    role=Role.ANALYST,
    scope_claims=(),
    shop_ids=(),
)


def _other_identity() -> IdentityContext:
    """同 `user_id` 但**不同租户** —— 所有权校验的两个维度之一。"""
    return replace(_IDENTITY, tenant_id="tenant-other")


def _meta() -> LlmCallMeta:
    return LlmCallMeta(
        model="deepseek-chat",
        prompt_version="pv-runner",
        tokens=TokenUsage(input=10, output=5, cache_hit=0, total=15),
        cost_cny=Decimal("0.0001"),
    )


class _FakeSemantics:
    def active_version(self) -> str:
        return "v-runner-0001"


class _RecordingAudit:
    """两段审计分开记 —— 取消路径要断言"只写了一段、且是段 1"。"""

    def __init__(self) -> None:
        self.pre: list[dict[str, Any]] = []
        self.supp: list[dict[str, Any]] = []

    async def write_pre(self, identity: IdentityContext, payload: dict[str, Any]) -> None:
        self.pre.append(payload)

    async def write_supp(self, identity: IdentityContext, payload: dict[str, Any]) -> None:
        self.supp.append(payload)


class _ScriptedPlanner:
    """按 `mode` 返回/抛出 —— 四条出口路径各一条 + 一条"慢"用于心跳/取消。"""

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def understand(
        self, identity: IdentityContext, question: str, history: tuple[Any, ...] = ()
    ) -> UnderstandOutcome:
        if self.mode == "slow":
            # 把"图还在跑"的时间窗拉开，让心跳与取消轮询有机会发生。
            await asyncio.sleep(0.3)
        if self.mode == "llm_refused":
            raise LlmRefused("模板层无命中 → 拒答（不是故障）")
        if self.mode == "llm_timeout":
            raise LlmTimeout("网关 15s 上限")
        if self.mode == "refuse_intent":
            intent, refuse_kind, time_ok = IntentKind.REFUSE, RefuseReason.NO_DATA_ASSET, True
        else:
            intent, refuse_kind, time_ok = IntentKind.EXECUTABLE, None, False
        return UnderstandOutcome(
            merged=True,
            normalized_question=question,
            intent=intent,
            refuse_kind=refuse_kind,
            reason_code="runner",
            clarify_hint="是哪个自然月？",
            confidence=0.7,
            time_range=None,
            time_parse_ok=time_ok,
            time_reason=None if time_ok else "无法唯一解析",
            resolved_terms=(),
            unresolved_terms=(),
            injection={},
            meta=_meta(),
            attempts=1,
            latency_ms=12,
        )


class _DepsHolder:
    """`new_deps` 的载体：每调用一次造一份**新的**假依赖（模拟"每请求一份"）。

    ⚠️ 同时记住**最后一次**造出的 `GraphDeps` —— 断言审计行数要读那一份
    （`new_deps` 每请求一份，从持有者身上取"某一份"会取到上一次的）。
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls = 0
        self.last: GraphDeps | None = None

    def __call__(self) -> GraphDeps:
        self.calls += 1
        self.last = _make_deps(self.mode)
        return self.last


def _make_deps(mode: str) -> GraphDeps:
    """早退路径需要的最小依赖集（同 `test_graph_wiring.py` 的取舍：未预期调用当场炸）。"""
    return GraphDeps(
        llm=object(),  # type: ignore[arg-type]
        planner=_ScriptedPlanner(mode),  # type: ignore[arg-type]
        binding=object(),  # type: ignore[arg-type]
        semantics=_FakeSemantics(),  # type: ignore[arg-type]
        retrieval=object(),  # type: ignore[arg-type]
        executor=object(),  # type: ignore[arg-type]
        mask=object(),  # type: ignore[arg-type]
        audit=_RecordingAudit(),  # type: ignore[arg-type]
        clock=object(),  # type: ignore[arg-type]
    )


def _runner(
    holder: _DepsHolder,
    *,
    store: RedisStateStore,
    heartbeat_s: float = 15,
    cancel_poll_s: float = 1.0,
) -> SseRunner:
    return SseRunner(
        graph=build_graph(),
        store=store,
        new_deps=holder,
        heartbeat_s=heartbeat_s,
        cancel_poll_s=cancel_poll_s,
    )


# ============================================================================
# 转录解析（唯一的解析点：字节帧 → (event, data)）
# ============================================================================


def _parse(frame: bytes) -> tuple[str, dict[str, Any]]:
    text = frame.decode()
    assert text.endswith("\n\n"), f"SSE 帧必须以空行结束：{text!r}"
    lines = [line for line in text.split("\n") if line]
    assert len(lines) == 2, f"帧应为 `event:` + `data:` 两行：{lines}"
    assert lines[0].startswith("event: "), lines
    assert lines[1].startswith("data: "), lines
    return lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])


def _frames(
    runner: SseRunner, *, question: str = "上个月卖得怎么样"
) -> list[tuple[str, dict[str, Any]]]:
    """跑一轮并把字节帧解析成 `(event, data)`（顺序保留 —— 转录断言要看序）。"""
    req = RunRequest(identity=_IDENTITY, question=question)

    async def _collect() -> list[bytes]:
        return [frame async for frame in runner.stream(req)]

    return [_parse(frame) for frame in asyncio.run(_collect())]


def _read_task(store: RedisStateStore) -> dict[str, Any] | None:
    async def _run() -> dict[str, Any] | None:
        return await store.get_task(_IDENTITY, _IDENTITY.task_id)

    return asyncio.run(_run())


# ============================================================================
# 一、出口路径转录（N-08 / DoD①）
# ============================================================================

_EXIT_CASES = [
    ("refuse_intent", SseEvent.REFUSE.value, TaskStatus.REFUSE.value, "no_data_asset"),
    ("llm_refused", SseEvent.REFUSE.value, TaskStatus.REFUSE.value, "no_data_asset"),
    ("time_unparsable", SseEvent.CLARIFY.value, TaskStatus.CLARIFY.value, None),
    ("llm_timeout", SseEvent.ERROR.value, TaskStatus.FAILED.value, None),
]


class TestTranscript:
    """四条出口路径各一条转录，逐条断言 N-08 的两个方向。"""

    @pytest.mark.parametrize(("mode", "terminal_event", "status", "reason"), _EXIT_CASES)
    def test_exit_transcript(
        self, mode: str, terminal_event: str, status: str, reason: str | None
    ) -> None:
        store = RedisStateStore(FakeRedis())  # type: ignore[arg-type]
        holder = _DepsHolder(mode)
        runner = _runner(holder, store=store)
        frames = _frames(runner)

        # 1) 首帧必须是 `ack` 且带 `task_id`（停止 / 看门狗 / 轮询三件事都靠它）。
        assert frames[0][0] == SseEvent.ACK.value, f"首帧不是 ack：{frames[0]}"
        assert frames[0][1]["task_id"] == _IDENTITY.task_id
        assert frames[0][1]["session_id"] == _IDENTITY.session_id
        assert frames[0][1]["terminal"] is False

        # 2) 每个事件的 data 都必须带 `terminal` 布尔（§A.1.4 的**唯一判据**）。
        for event, data in frames:
            assert isinstance(data.get("terminal"), bool), f"{event} 缺 terminal：{data}"

        # 3) 恰有 1 个 `terminal:true`，且它就是该路径的终态事件。
        terminals = [(e, d) for e, d in frames if d["terminal"] is True]
        assert len(terminals) == 1, f"{mode} 的终态不唯一：{[e for e, _ in terminals]}"
        assert terminals[0][0] == terminal_event

        # 4) 终态之后除心跳外不得再有事件（§14.3 约束 3 的结构侧）。
        index = frames.index(terminals[0])
        assert all(e == SseEvent.HEARTBEAT.value for e, _ in frames[index + 1 :])

        # 5) `stage` 只允许 6 个合法值（§14.3 约束 8）。
        legal = {s.value for s in Stage}
        for event, data in frames:
            if event == SseEvent.STAGE.value:
                assert data["stage"] in legal, data

        # 6) 结论与事件**同源**：`RunOutcome` 必须与转录的终态一致。
        outcome = runner.outcome
        assert outcome is not None
        assert outcome.status.value == status
        assert outcome.terminal_event == terminal_event
        assert outcome.reason == reason
        assert outcome.bundle_version == "v-runner-0001"  # 会话级版本固定（trusted_context 写入）
        assert outcome.nodes[0] == "trusted_context"
        assert outcome.violations == ()

        # 7) 每请求一份依赖（`new_deps` 恰被调用一次）。
        assert holder.calls == 1

    @pytest.mark.parametrize(("mode", "terminal_event", "status", "reason"), _EXIT_CASES)
    def test_task_state_written(
        self, mode: str, terminal_event: str, status: str, reason: str | None
    ) -> None:
        """轮询端点读到的 `status` 必须与转录一致（C-05）。"""
        store = RedisStateStore(FakeRedis())  # type: ignore[arg-type]
        _frames(_runner(_DepsHolder(mode), store=store))
        payload = _read_task(store)
        assert payload is not None
        assert payload["status"] == status
        assert payload["task_id"] == _IDENTITY.task_id
        # 归属三元组每次写都带上（读端靠它做所有权校验，见 state_store §二）。
        assert payload["tenant_id"] == _IDENTITY.tenant_id
        assert payload["user_id"] == _IDENTITY.user_id
        # `queued_at` → `started_at` → `finished_at` 三个时间戳的先后（§A.2 的展示要求）。
        assert payload["queued_at"] <= payload["started_at"] <= payload["finished_at"]
        # P0 边界：无来源的三个字段如实为 `None`（见 runner 模块 docstring §四）。
        assert payload["data"] is None
        assert payload["audit_ref"] is None
        assert payload["progress"] is None

    def test_segment_one_audit_written_exactly_once(self) -> None:
        """出口路径：段 1 审计恰一次，且**不**写段 2（结果从未下发）。"""
        holder = _DepsHolder("refuse_intent")
        _frames(_runner(holder, store=RedisStateStore(FakeRedis())))  # type: ignore[arg-type]
        audit = holder.last.audit  # type: ignore[union-attr]
        assert len(audit.pre) == 1  # type: ignore[union-attr]
        assert audit.pre[0]["outcome"] == "refuse"  # type: ignore[union-attr]
        assert audit.pre[0]["bundle_version"] == "v-runner-0001"  # type: ignore[union-attr]
        assert audit.supp == []  # type: ignore[union-attr]

    def test_stage_intent_emitted_for_empty_update_nodes(self) -> None:
        """🔴 回归：LangGraph 的 `updates` 模式把**空增量**表示为 `None`（不是 `{}`）。

        `trusted_context` 恒返回 `{}`，而 `intent` 在**合并档**下也只返回 `{}`
        （它的事实由 `normalize` 一起产出）⇒ 若把 `None` 当成"非法增量"跳过，
        `stage=intent` 这一帧**永远不会发出**：前端进度条缺第一段，
        且 §5.6 要求的"`intent` 耗时含 `normalize`"无从体现。
        """
        frames = _frames(
            _runner(_DepsHolder("refuse_intent"), store=RedisStateStore(FakeRedis()))  # type: ignore[arg-type]
        )
        stages = [data["stage"] for event, data in frames if event == SseEvent.STAGE.value]
        assert stages and stages[0] == Stage.INTENT.value, f"首个 stage 不是 intent：{stages}"


# ============================================================================
# 二、心跳（§A.1.4：真实间隔 15s；测试把它压到 0.02s）
# ============================================================================


class TestHeartbeat:
    def test_heartbeat_before_terminal(self) -> None:
        runner = _runner(
            _DepsHolder("slow"),
            store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
            heartbeat_s=0.02,
            cancel_poll_s=5.0,
        )
        frames = _frames(runner)
        beats = [i for i, (event, _) in enumerate(frames) if event == SseEvent.HEARTBEAT.value]
        assert beats, "慢图期间必须有心跳（否则反代会切断静默连接）"
        terminals = [i for i, (_, data) in enumerate(frames) if data["terminal"] is True]
        assert terminals and min(beats) < min(terminals), "心跳必须发生在终态**之前**"
        for index in beats:
            assert frames[index][1]["terminal"] is False


# ============================================================================
# 三、取消路径（§14.2 E7 / §8.3 要求②）
# ============================================================================


class TestCancellation:
    def test_cancel_stops_run_without_terminal_and_writes_audit(self) -> None:
        """取消标志命中 ⇒ 取消图任务、**不发终态**、段 1 审计留痕、状态落 `cancelled`。"""
        store = RedisStateStore(FakeRedis())  # type: ignore[arg-type]
        # 预置取消标志（等价于"用户在流建立后、节点跑完前点了停止"）。
        asyncio.run(
            store.put_task(_IDENTITY, status=TaskStatus.RUNNING, extra={"cancel_requested": True})
        )
        holder = _DepsHolder("slow")
        runner = _runner(holder, store=store, heartbeat_s=15, cancel_poll_s=0.02)
        frames = _frames(runner)

        # E7：**无终态事件**（不补一个 error 帧去"假装有终态"）。
        assert all(data["terminal"] is False for _, data in frames), frames
        outcome = runner.outcome
        assert outcome is not None
        assert outcome.cancelled is True
        assert outcome.status is TaskStatus.CANCELLED

        # §8.3 要求②：取消也必须留痕 —— 结果从未下发 ⇒ 补**段 1**（不是段 2）。
        audit = holder.last.audit  # type: ignore[union-attr]
        assert len(audit.pre) == 1  # type: ignore[union-attr]
        assert audit.pre[0]["outcome"] == "failed"  # type: ignore[union-attr]
        assert audit.supp == []  # type: ignore[union-attr]

        payload = _read_task(store)
        assert payload is not None
        assert payload["status"] == TaskStatus.CANCELLED.value

    def test_cancel_poll_failure_does_not_cancel(self) -> None:
        """读取消标志失败 ⇒ 按"未取消"继续（基础设施抖动不得掐掉用户查询）。"""

        class _BrokenStore:
            async def is_cancel_requested(self, task_id: str) -> bool:
                raise RuntimeError("redis 抖动")

            async def put_task(self, *args: Any, **kwargs: Any) -> None:
                return None

        runner = SseRunner(
            graph=build_graph(),
            store=_BrokenStore(),  # type: ignore[arg-type]
            new_deps=_DepsHolder("refuse_intent"),
            heartbeat_s=15,
            cancel_poll_s=0.01,
        )
        frames = _frames(runner)
        assert any(data["terminal"] is True for _, data in frames), "抖动不得吞掉终态"
        assert runner.outcome is not None
        assert runner.outcome.cancelled is False


# ============================================================================
# 四、纯函数：终态 → TaskStatus（C-05）
# ============================================================================


class TestTaskStatusProjection:
    @pytest.mark.parametrize(
        ("event", "outcome", "expected"),
        [
            ("complete", "success", TaskStatus.SUCCEEDED),
            ("complete", "degraded", TaskStatus.DEGRADED),
            ("clarify", "clarify", TaskStatus.CLARIFY),
            # ⚠️ 字面量不同是**契约要求**（C-05）：status=`refused` ⇄ outcome=`refuse`。
            ("refuse", "refuse", TaskStatus.REFUSE),
            ("error", "failed", TaskStatus.FAILED),
        ],
    )
    def test_terminal_to_status(self, event: str, outcome: str, expected: TaskStatus) -> None:
        assert task_status_of({"terminal": {"event": event}, "outcome": outcome}) is expected

    def test_refused_and_outcome_literals_differ(self) -> None:
        """`refused`(status) ≠ `refuse`(outcome) —— 用字面量相等判"是不是拒答"是本条要防的事。"""
        assert TaskStatus.REFUSE.value == "refused"
        assert task_status_of({"terminal": {"event": "refuse"}, "outcome": "refuse"}).value == (
            "refused"
        )

    def test_missing_terminal_is_failed_not_success(self) -> None:
        """图未收口 ⇒ `failed`（**不得**悄悄当成功）。"""
        assert task_status_of({}) is TaskStatus.FAILED

    def test_cancelled_wins_over_terminal(self) -> None:
        state = {"terminal": {"event": "complete"}, "outcome": "success"}
        assert task_status_of(state, cancelled=True) is TaskStatus.CANCELLED


# ============================================================================
# 五、接线守卫（线程 ID / RunContext / 终态守卫）
# ============================================================================


class TestWiringGuards:
    def test_thread_id_is_tenant_scoped(self) -> None:
        """`thread_id` 必须含租户与用户（07 §5.4）——否则同 `session_id` 可跨租户读检查点。"""
        assert thread_id_of(_IDENTITY) == "tenant-run:user-run-1:ss-run-1"

    def test_run_context_missing_fails_fast(self) -> None:
        """节点在无 `RunContext` 时被调用必须抛错（fail-fast，见 `graph/context.py` §二）。"""
        with pytest.raises(RuntimeError, match="set_run_context"):
            current_run_context()

    def test_emission_may_not_carry_terminal(self) -> None:
        """`Emission` 自带 `terminal` 时 `push` 必须抛（守卫的 fail-closed 方向）。"""
        recorder = EventRecorder(encoder=sse.encode)
        with pytest.raises(ContractViolationError):
            recorder.push(Emission(SseEvent.COMPLETE, {"terminal": True}))


# ============================================================================
# 六、`RedisStateStore` 的读端义务（§A.2 / §A.3 / §A.4 / §A.12）
# ============================================================================


class TestStateStoreOwnership:
    """所有权校验是**读端义务**（`task_state` 是无租户键，见 `state_store` 模块 docstring §二）。"""

    def _store(self) -> RedisStateStore:
        return RedisStateStore(FakeRedis())  # type: ignore[arg-type]

    def test_foreign_tenant_cannot_read(self) -> None:
        store = self._store()

        async def _run() -> tuple[Any, Any]:
            await store.put_task(_IDENTITY, status=TaskStatus.RUNNING)
            return (
                await store.get_task(_IDENTITY, _IDENTITY.task_id),
                await store.get_task(_other_identity(), _IDENTITY.task_id),
            )

        mine, theirs = asyncio.run(_run())
        assert mine is not None
        # ⚠️ 不区分"不存在"与"不属于你"：区分会让 404/403 的差异变成存在性侧信道。
        assert theirs is None

    def test_cancel_is_idempotent_and_ownership_first(self) -> None:
        store = self._store()

        async def _run() -> tuple[Any, Any, Any]:
            await store.put_task(_IDENTITY, status=TaskStatus.RUNNING)
            return (
                await store.cancel_task(_IDENTITY, _IDENTITY.task_id),
                await store.cancel_task(_IDENTITY, _IDENTITY.task_id),
                await store.cancel_task(_other_identity(), _IDENTITY.task_id),
            )

        first, second, foreign = asyncio.run(_run())
        assert first.cancelled and first.ok
        # 幂等：重复 cancel 不得 5xx（W5 RELAY §1.2 的明确要求）。
        assert second.already_cancelled and second.ok
        # 别人的任务按"不存在"处理（先所有权、再终态 —— 反过来是存在性侧信道）。
        assert foreign.not_found

    def test_terminal_task_is_not_cancellable(self) -> None:
        store = self._store()

        async def _run() -> Any:
            await store.put_task(_IDENTITY, status=TaskStatus.RUNNING)
            await store.put_task(_IDENTITY, status=TaskStatus.SUCCEEDED)
            return await store.cancel_task(_IDENTITY, _IDENTITY.task_id)

        outcome = asyncio.run(_run())
        assert outcome.not_cancellable and not outcome.ok

    def test_task_state_merges_and_keeps_first_timestamps(self) -> None:
        """合并写：`queued_at` 不被后续更新覆盖（否则轮询里"排队时间"会一直变）。"""
        store = self._store()

        async def _run() -> tuple[Any, Any]:
            await store.put_task(_IDENTITY, status=TaskStatus.RUNNING)
            first = await store.get_task(_IDENTITY, _IDENTITY.task_id)
            await store.put_task(_IDENTITY, status=TaskStatus.SUCCEEDED, stage="executing")
            return first, await store.get_task(_IDENTITY, _IDENTITY.task_id)

        first, later = asyncio.run(_run())
        assert first is not None and later is not None
        assert later["queued_at"] == first["queued_at"]
        assert later["stage"] == "executing"
        assert later["status"] == TaskStatus.SUCCEEDED.value

    def test_idempotency_three_states(self) -> None:
        """幂等三态：首次 / 重放（同键同体）/ 冲突（同键不同体）。"""
        store = self._store()

        async def _run() -> tuple[Any, Any, Any]:
            first = await store.begin_idempotent(
                tenant_id=_IDENTITY.tenant_id,
                new_task_id=_IDENTITY.task_id,
                idempotency_key="k1",
                request_hash="h1",
            )
            await store.fill_idempotency(
                _IDENTITY, idempotency_key="k1", task_id=_IDENTITY.task_id, request_hash="h1"
            )
            return (
                first,
                await store.begin_idempotent(
                    tenant_id=_IDENTITY.tenant_id,
                    new_task_id="tk_unused",
                    idempotency_key="k1",
                    request_hash="h1",
                ),
                await store.begin_idempotent(
                    tenant_id=_IDENTITY.tenant_id,
                    new_task_id="tk_unused",
                    idempotency_key="k1",
                    request_hash="h2",
                ),
            )

        first, replay, conflict = asyncio.run(_run())
        assert first.replayed is False and first.task_id == _IDENTITY.task_id
        assert replay.replayed is True and replay.task_id == _IDENTITY.task_id
        assert conflict.conflict is True and conflict.task_id is None
        # §A.12 的 `detail.original_task_id` 来源：冲突时能给出**原任务**（同键不同体 ⇒ 原任务已知）
        assert conflict.existing_task_id == _IDENTITY.task_id

    def test_idempotency_absent_key_is_not_idempotent(self) -> None:
        """未传 `Idempotency-Key` ⇒ 不做幂等（§A.0.3 的 ⭕），且**不**落 Redis 键。"""
        fake = FakeRedis()
        store = RedisStateStore(fake)  # type: ignore[arg-type]

        async def _run() -> Any:
            return await store.begin_idempotent(
                tenant_id=_IDENTITY.tenant_id,
                new_task_id=_IDENTITY.task_id,
                idempotency_key=None,
                request_hash="h1",
            )

        decision = asyncio.run(_run())
        assert decision.replayed is False and decision.task_id == _IDENTITY.task_id
        assert fake.store == {}

    def test_clarify_context_is_one_shot(self) -> None:
        store = self._store()

        async def _run() -> tuple[Any, Any]:
            await store.put_clarify(
                _IDENTITY,
                clarify_id="cl_1",
                raw_question="上个月卖得怎么样",
                reason="time_unparsable",
                options=({"value": "2026-08", "label": "2026-08"},),
            )
            before = await store.get_clarify(_IDENTITY, "cl_1")
            await store.drop_clarify(_IDENTITY, "cl_1")
            return before, await store.get_clarify(_IDENTITY, "cl_1")

        before, after = asyncio.run(_run())
        assert before is not None and before.raw_question == "上个月卖得怎么样"
        assert before.options[0]["value"] == "2026-08"
        # 一次性：同一 `clarify_id` 不得被回答两次（见 `drop_clarify` 的理由）。
        assert after is None

    def test_turn_history_keeps_plan_summary_only(self) -> None:
        """轮次历史**只存计划摘要**、不含 SQL（FR-10.1 / N-17）。"""
        store = self._store()

        async def _run() -> tuple[dict[str, Any], ...]:
            await store.append_turn(
                _IDENTITY,
                question="上个月卖得怎么样",
                outcome="success",
                plan_summary={"metrics": ["gmv"]},
                bundle_version="v-runner-0001",
            )
            return await store.get_turns(_IDENTITY, _IDENTITY.session_id)

        turns = asyncio.run(_run())
        assert len(turns) == 1
        assert turns[0]["plan_summary"] == {"metrics": ["gmv"]}
        assert "sql" not in turns[0]

    def test_session_title_is_written_once(self) -> None:
        """标题只写一次（§A.5.4：标题取自**首轮**问题）。"""
        store = self._store()

        async def _run() -> Any:
            await store.create_session(_IDENTITY)
            await store.touch_session(
                _IDENTITY, title="上个月卖得怎么样", bundle_version="v-runner-0001"
            )
            await store.touch_session(
                _IDENTITY, title="第二个问题", bundle_version="v-runner-0002"
            )
            return await store.get_session(_IDENTITY, _IDENTITY.session_id)

        meta = asyncio.run(_run())
        assert meta is not None
        assert meta.title == "上个月卖得怎么样"
        # 语义包版本**要**更新（它是"这一轮用了哪版口径"的事实）。
        assert meta.bundle_version == "v-runner-0002"

    def test_task_ttl_comes_from_keys_single_source(self) -> None:
        """TTL 取自 `cache/keys.DEFAULT_TTL_S`（唯一来源），不在这里另写数字。"""
        fake = FakeRedis()
        store = RedisStateStore(fake)  # type: ignore[arg-type]
        asyncio.run(store.put_task(_IDENTITY, status=TaskStatus.RUNNING))
        key = cache_keys.task_state(_IDENTITY.task_id)
        _, expires_at = fake.store[key]
        assert expires_at is not None
        assert expires_at - fake.time_ms == cache_keys.DEFAULT_TTL_S["task_state"] * 1000
