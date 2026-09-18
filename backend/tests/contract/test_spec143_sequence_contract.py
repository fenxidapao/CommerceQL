"""07 §14.3 事件序列约束 —— **八条逐条**各有测试（T9 要求"逐条有测试"）。

| # | 约束 | 本文件的测试 |
|---|---|---|
| 1 | 终态唯一 | `test_c1_exactly_one_terminal`（转录级） |
| 2 | refuse/error/clarify 互斥 | `test_c2_terminal_kinds_are_mutually_exclusive`（两类转录对照） |
| 3 | 终态后禁事件（心跳除外） | `test_c3_terminal_is_the_last_frame`（转录级）+ `test_c4_...`（recorder 级） |
| 4 | degraded 在终态前 | `test_c4_degraded_precedes_terminal` |
| 5 | data 可在 error 前；禁止 refuse+data | `test_c5a_*` / `test_c5b_*` |
| 6 | data 在 audit_log 提交之后 | `test_c6_data_only_from_audit_pre_and_fail_closed` |
| 7 | meta 必含 scope + retrieval_mode | `test_c7_meta_required_keys` |
| 8 | stage 恰 6 值 | `test_c8_stage_enum_is_six_values` |

图级转录复用 `test_decision_table_contract` 的脚本夹具形态（自包含副本，
与 `test_api_runner_contract` / `test_graph_wiring` 各持 `_FakeSemantics` 的先例一致）。
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from app.api import sse
from app.api.runner import RunRequest, SseRunner
from app.api.state_store import RedisStateStore
from app.core.contracts import IdentityContext, TokenUsage
from app.core.enums import SseEvent, Stage
from app.graph.build import build_graph
from app.graph.events import (
    _META_REQUIRED_KEYS,  # 约束 7 的键集是契约本体
    Emission,
    EventRecorder,
    emissions_for_node,
)
from app.graph.nodes import AUDIT_PRE, ERROR_OUT
from app.llm.errors import LlmTimeout
from app.planner.engine import LlmCallMeta, UnderstandOutcome
from app.planner.schemas import IntentKind
from tests.contract.test_api_runner_contract import _FakeSemantics, _parse
from tests.unit._redis_fake import FakeRedis

_IDENTITY = IdentityContext(
    trace_id="tr-143",
    task_id="tk-143",
    session_id="ss-143",
    tenant_id="tenant-143",
    user_id="user-143",
    role=None,
    scope_claims=(),
    shop_ids=(),
)

_META = LlmCallMeta(
    model="deepseek-chat",
    prompt_version="pv-143",
    tokens=TokenUsage(input=10, output=5, cache_hit=0, total=15),
    cost_cny=Decimal("0.0001"),
)


def _outcome(intent: IntentKind, *, refuse_kind: Any = None) -> UnderstandOutcome:
    return UnderstandOutcome(
        merged=True,
        normalized_question="上个月卖得怎么样",
        intent=intent,
        refuse_kind=refuse_kind,
        reason_code="spec143",
        clarify_hint=None,
        confidence=0.9,
        time_range=None,
        time_parse_ok=True,
        time_reason=None,
        resolved_terms=(),
        unresolved_terms=(),
        injection={},
        meta=_META,
        attempts=1,
        latency_ms=1,
    )


class _OutcomePlanner:
    def __init__(self, outcome: UnderstandOutcome) -> None:
        self._outcome = outcome

    async def understand(
        self, identity: IdentityContext, question: str, history: tuple[Any, ...] = ()
    ) -> UnderstandOutcome:
        return self._outcome


class _TimeoutPlanner:
    async def understand(
        self, identity: IdentityContext, question: str, history: tuple[Any, ...] = ()
    ) -> UnderstandOutcome:
        raise LlmTimeout("网关 15s 上限（§14.2 F 系）")


def _frames_with(planner: Any) -> list[tuple[str, dict[str, Any]]]:
    class _Holder:
        def __call__(self) -> Any:
            from app.graph.context import GraphDeps

            return GraphDeps(
                llm=object(),  # type: ignore[arg-type]
                planner=planner,  # type: ignore[arg-type]
                binding=object(),  # type: ignore[arg-type]
                semantics=_FakeSemantics(),  # type: ignore[arg-type]
                retrieval=object(),  # type: ignore[arg-type]
                executor=object(),  # type: ignore[arg-type]
                mask=object(),  # type: ignore[arg-type]
                audit=object(),  # type: ignore[arg-type]
                clock=object(),  # type: ignore[arg-type]
            )

    runner = SseRunner(
        graph=build_graph(),
        store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
        new_deps=_Holder(),  # type: ignore[arg-type]
    )
    req = RunRequest(identity=_IDENTITY, question="上个月卖得怎么样")

    async def _collect() -> list[bytes]:
        return [frame async for frame in runner.stream(req)]

    return [_parse(frame) for frame in asyncio.run(_collect())]


def _refuse_frames() -> list[tuple[str, dict[str, Any]]]:
    return _frames_with(_OutcomePlanner(_outcome(IntentKind.REFUSE, refuse_kind="no_data_asset")))


def _error_frames() -> list[tuple[str, dict[str, Any]]]:
    return _frames_with(_TimeoutPlanner())


# ============================================================================
# 约束 1–3：终态唯一 / 三者互斥 / 终态最后
# ============================================================================


class TestSpec143:
    def test_c1_exactly_one_terminal(self) -> None:
        for frames in (_refuse_frames(), _error_frames()):
            terminals = [d for _, d in frames if d.get("terminal") is True]
            assert len(terminals) == 1, f"约束 1（N-08）：恰 1 个终态，实得 {len(terminals)}"

    def test_c2_terminal_kinds_are_mutually_exclusive(self) -> None:
        """refuse / error / clarify 互斥：refuse 流无 error/clarify；error 流无 refuse/clarify。"""
        refuse_events = {e for e, _ in _refuse_frames()}
        assert refuse_events.isdisjoint({SseEvent.ERROR.value, SseEvent.CLARIFY.value})
        error_events = {e for e, _ in _error_frames()}
        assert error_events.isdisjoint({SseEvent.REFUSE.value, SseEvent.CLARIFY.value})

    def test_c3_terminal_is_the_last_frame(self) -> None:
        """终态之后没有任何事件帧（心跳例外发生在**挂起**的流上，正常收口流不出现）。"""
        for frames in (_refuse_frames(), _error_frames()):
            # 逐帧找终态：终态帧之后不允许再有帧。
            for index, (_, data) in enumerate(frames):
                if data.get("terminal") is True:
                    assert index == len(frames) - 1, f"终态后有帧：{frames[index + 1:]}"

    def test_c4_degraded_precedes_terminal(self) -> None:
        """约束 4：`degraded` 可多次、必须在终态**之前**；终态后到达的降级被守卫丢弃。"""
        recorder = EventRecorder(encoder=sse.encode)
        recorder.degraded(reason="llm_unavailable", action_taken="template_only")
        recorder.degraded(reason="embed_unavailable", action_taken="sparse_only")
        recorder.push(Emission(SseEvent.COMPLETE, {}))
        recorder.degraded(reason="late", action_taken="noop")  # 终态后 → 必须被丢弃
        events = [e.event for e in recorder.emissions]
        assert events.count(SseEvent.DEGRADED) == 2
        assert events.index(SseEvent.DEGRADED) < events.index(SseEvent.COMPLETE)
        assert SseEvent.DEGRADED.value in recorder.dropped, "终态后的 degraded 必须被丢弃"

    def test_c5a_refuse_carries_no_data(self) -> None:
        assert all(e != SseEvent.DATA.value for e, _ in _refuse_frames())

    def test_c5b_data_may_precede_error(self) -> None:
        """约束 5 前半：06 §7.5 允许 `error` + `data` 共存（部分数据）。"""
        recorder = EventRecorder(encoder=sse.encode)
        recorder.on_node(
            AUDIT_PRE,
            {"result_columns": ["city"], "row_count": 1, "truncated": False},
            extras={"rows": [["广州"]]},
        )
        recorder.on_node(
            ERROR_OUT,
            {"terminal": {"event": "error", "code": "INTERNAL", "outcome": "failed"}},
            extras={"code": "INTERNAL", "message": "x", "retryable": False},
        )
        events = [e.event for e in recorder.emissions]
        assert SseEvent.DATA in events and SseEvent.ERROR in events
        assert events.index(SseEvent.DATA) < events.index(SseEvent.ERROR)

    def test_c6_data_only_from_audit_pre_and_fail_closed(self) -> None:
        """约束 6（N-09）：`data` 帧挂在 `audit_pre` 之后；段 1 写失败 → fail-closed 无 data。"""
        # ① audit_pre 的成功增量（rows 经 extras）→ 产 DATA；
        emissions = emissions_for_node(
            AUDIT_PRE,
            {"result_columns": ["city"], "row_count": 1, "truncated": False},
            elapsed_ms=1,
            explain=True,
            extras={"rows": [["广州"]]},
        )
        assert any(e.event is SseEvent.DATA for e in emissions)
        # ② 同样的行数据若出现在 `execute` 增量里**不**产 DATA（发射点唯一）；
        from app.graph.nodes import EXECUTE

        emissions_exec = emissions_for_node(
            EXECUTE,
            {"result_columns": ["city"], "row_count": 1, "truncated": False},
            elapsed_ms=1,
            explain=True,
            extras={"rows": [["广州"]]},
        )
        assert all(e.event is not SseEvent.DATA for e in emissions_exec)
        # ③ 段 1 写失败（audit_pre 返回 terminal=error）→ 无 DATA（fail-closed）。
        emissions_failed = emissions_for_node(
            AUDIT_PRE,
            {
                "terminal": {"event": "error", "code": "INTERNAL", "outcome": "failed"},
                "outcome": "failed",
            },
            elapsed_ms=1,
            explain=True,
            extras=None,
        )
        assert all(e.event is not SseEvent.DATA for e in emissions_failed)

    def test_c7_meta_required_keys(self) -> None:
        """约束 7：meta 必含 `scope` 与 `retrieval_mode`（C-07/C-11），缺失即契约违规。"""
        assert {"scope", "retrieval_mode"} <= set(_META_REQUIRED_KEYS)

    def test_c8_stage_enum_is_six_values(self) -> None:
        assert {s.value for s in Stage} == {
            "intent",
            "schema_linking",
            "plan_ready",
            "sql_ready",
            "gate_passed",
            "executing",
        }


@pytest.mark.parametrize(
    ("left", "right"),
    [(SseEvent.REFUSE, SseEvent.ERROR), (SseEvent.REFUSE, SseEvent.CLARIFY), (SseEvent.ERROR, SseEvent.CLARIFY)],
)
def test_c2_matrix_pairs_are_disjoint_by_guard(left: SseEvent, right: SseEvent) -> None:
    """互斥的**机制**面：终态守卫对第二次终态丢弃 + 违规记录（双保险的第二处）。"""
    recorder = EventRecorder(encoder=sse.encode)
    first = SseEvent.COMPLETE if {left, right} == {SseEvent.REFUSE, SseEvent.ERROR} else left
    second = right if first is left else left
    recorder.push(Emission(first, {}))
    recorder.push(Emission(second, {}))
    assert recorder.terminal_count == 1
    assert any("终态" in v or "terminal" in v for v in recorder.violations), recorder.violations
