"""07 §14.2 决策表 **A 组（意图与理解类）** 逐行 —— 图级转录断言。

T9 要求"A–H 八组决策表逐行有测试"。本文件先落 A 组 6 行（图可达性最好、
全部经真图 + 脚本 planner 触达）；B–G 组按批追加（各自需要更深的 deps 脚本，
进度登记在 `reports/w4/RELAY.md`，**不做没跑通的"全绿"假象**）。

行级断言 = 07 §14.2 表的列：事件 / `reason` / `terminal` / `outcome`（经 `task_status_of`
投影）/ 审计段 1 落行。`retryable` 列对 refuse/clarify 无意义（那是 error 帧的字段）。

实现事实与 07 字面的**登记差异**（不属本文件裁决）：
- A2 的 07 字面 `reason=ambiguity`，实现走 `clarify_out` 的时间澄清分支
  （`reason=time_ambiguous`，字面量来自附录 A §A.1.4 示例；`clarify_out.py` 已登记
  "reason 无枚举"）。断言按实现事实写。
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from app.api.runner import RunOutcome, RunRequest, SseRunner
from app.api.state_store import RedisStateStore
from app.core.contracts import IdentityContext, TokenUsage
from app.core.enums import RefuseReason, SseEvent, TaskStatus
from app.graph.build import build_graph
from app.planner.engine import LlmCallMeta, UnderstandOutcome
from app.planner.schemas import IntentKind
from tests.contract.test_api_runner_contract import _IDENTITY, _FakeSemantics, _parse
from tests.unit._redis_fake import FakeRedis

# ============================================================================
# 脚本 planner：A 组 6 行共用一个可参数化的 understand()
# ============================================================================

_META = LlmCallMeta(
    model="deepseek-chat",
    prompt_version="pv-dt",
    tokens=TokenUsage(input=10, output=5, cache_hit=0, total=15),
    cost_cny=Decimal("0.0001"),
)


def _outcome(
    *,
    intent: IntentKind,
    refuse_kind: RefuseReason | None = None,
    time_parse_ok: bool = True,
) -> UnderstandOutcome:
    return UnderstandOutcome(
        merged=True,
        normalized_question="上个月卖得怎么样",
        intent=intent,
        refuse_kind=refuse_kind,
        reason_code="decision_table",
        clarify_hint=None,
        confidence=0.9,
        time_range=None,
        time_parse_ok=time_parse_ok,
        time_reason=None if time_parse_ok else "无法唯一解析",
        resolved_terms=(),
        unresolved_terms=(),
        injection={},
        meta=_META,
        attempts=1,
        latency_ms=1,
    )


class _APlanner:
    """返回**预置** outcome 的最小 planner（A 组只需要 understand 一跳）。"""

    def __init__(self, outcome: UnderstandOutcome) -> None:
        self._outcome = outcome

    async def understand(
        self, identity: IdentityContext, question: str, history: tuple[Any, ...] = ()
    ) -> UnderstandOutcome:
        return self._outcome


class _RecordingAudit:
    def __init__(self) -> None:
        self.pre: list[dict[str, Any]] = []
        self.supp: list[dict[str, Any]] = []

    async def write_pre(self, identity: IdentityContext, payload: dict[str, Any]) -> None:
        self.pre.append(payload)

    async def write_supp(self, identity: IdentityContext, payload: dict[str, Any]) -> None:
        self.supp.append(payload)


def _run(outcome: UnderstandOutcome) -> tuple[list[tuple[str, dict[str, Any]]], RunOutcome, _RecordingAudit]:
    audit = _RecordingAudit()

    class _Holder:
        def __call__(self) -> Any:
            from app.graph.context import GraphDeps

            return GraphDeps(
                llm=object(),  # type: ignore[arg-type]
                planner=_APlanner(outcome),  # type: ignore[arg-type]
                binding=object(),  # type: ignore[arg-type]
                semantics=_FakeSemantics(),  # type: ignore[arg-type]
                retrieval=object(),  # type: ignore[arg-type]
                executor=object(),  # type: ignore[arg-type]
                mask=object(),  # type: ignore[arg-type]
                audit=audit,  # type: ignore[arg-type]
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

    frames = [_parse(frame) for frame in asyncio.run(_collect())]
    assert runner.outcome is not None
    return frames, runner.outcome, audit


def _terminal_frames(
    frames: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    return [(e, d) for e, d in frames if d.get("terminal") is True]


# ============================================================================
# A 组逐行
# ============================================================================


class TestAGroup:
    def test_a1_time_unparsable_clarifies(self) -> None:
        """A1 时间表达无法解析 → `clarify(reason=time_ambiguous)`、审计落行。"""
        frames, outcome, audit = _run(
            _outcome(intent=IntentKind.EXECUTABLE, time_parse_ok=False)
        )
        terminals = _terminal_frames(frames)
        assert len(terminals) == 1 and terminals[0][0] == SseEvent.CLARIFY.value
        assert terminals[0][1]["reason"] == "time_ambiguous"
        assert outcome.status is TaskStatus.CLARIFY
        assert len(audit.pre) == 1 and audit.pre[0]["outcome"] == "clarify"

    def test_a2_intent_clarify(self) -> None:
        """A2 意图 = 需澄清 → `clarify`。⚠️ 实现走时间澄清分支（登记差异见模块 docstring）。"""
        frames, outcome, audit = _run(_outcome(intent=IntentKind.CLARIFY))
        terminals = _terminal_frames(frames)
        assert len(terminals) == 1 and terminals[0][0] == SseEvent.CLARIFY.value
        assert terminals[0][1]["reason"] == "time_ambiguous"
        assert outcome.status is TaskStatus.CLARIFY
        assert len(audit.pre) == 1

    @pytest.mark.parametrize(
        ("refuse_kind", "expected_reason"),
        [
            (RefuseReason.OPEN_ANALYSIS, "open_analysis"),  # A3（NG4：经 intent=open_analysis）
            (RefuseReason.NO_DATA_ASSET, "no_data_asset"),  # A4
            (RefuseReason.OUT_OF_SCOPE, "out_of_scope"),  # A5（不透内容的中性文案）
            (RefuseReason.PII_BLOCKED, "pii_blocked"),  # A6
        ],
    )
    def test_a3_to_a6_refuse_rows(
        self, refuse_kind: RefuseReason, expected_reason: str
    ) -> None:
        """A3–A6 → `refuse(reason=…)`、审计落行、status=REFUSED、**无 data 帧**（约束 5）。"""
        intent = (
            IntentKind.REFUSE
            if refuse_kind is not RefuseReason.OPEN_ANALYSIS
            else IntentKind.OPEN_ANALYSIS
        )
        frames, outcome, audit = _run(
            _outcome(intent=intent, refuse_kind=refuse_kind)
        )
        terminals = _terminal_frames(frames)
        assert len(terminals) == 1 and terminals[0][0] == SseEvent.REFUSE.value
        assert terminals[0][1]["reason"] == expected_reason
        assert outcome.status is TaskStatus.REFUSE
        assert len(audit.pre) == 1 and audit.pre[0]["outcome"] == "refuse"
        # 07 §14.3 约束 5：**禁止 refuse + data**（拒答不给数据）。
        assert all(event != SseEvent.DATA.value for event, _ in frames)
