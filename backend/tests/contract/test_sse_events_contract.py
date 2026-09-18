"""SSE 事件层契约测试 —— 07 §5.6（17 发射点）与 §14.3（八条序列约束）。

对应 DoD ①（"SSE 转录覆盖**全部出口路径** + 断言恰有 1 个 `terminal:true`"）
与 DoD ③（"`stage` 取值只有 6 个"）的后端机制侧。

⚠️ 本文件测的是**机制**（`EventRecorder`），不是字节格式 —— 帧格式的唯一校验点在
`app/api/sse.py::encode`（它自己会对 `terminal` 与 `stage` 做第二次校验）。
两道防线各管一件事：本层防"该不该发"，`encode` 防"发出去的帧自相矛盾"。
"""

from __future__ import annotations

import json

import pytest

from app.api.sse import encode
from app.core.contracts import GateResult
from app.core.enums import (
    SSE_STAGE_EMISSION_POINTS,
    SSE_TERMINAL_EVENTS,
    ActionTaken,
    DegradedReason,
    GateDecision,
    GateNo,
    SseEvent,
    Stage,
)
from app.core.errors import ContractViolationError
from app.graph.events import (
    EventRecorder,
    emissions_for_node,
    gate_detail,
    missing_meta_keys,
)
from app.graph.nodes import ALL_NODE_NAMES, MAIN_NODE_NAMES, TERMINAL_NODE_NAMES

#: 一条**完整成功链路**的（节点, state 增量）。顺序即图的执行序。
#: 它同时是"17 发射点全覆盖"的载体 —— 少了任何一个节点，覆盖断言就会红。
_CLEAN_GATES = {
    GateNo.AST: GateResult(gate_no=GateNo.AST, passed=True, decision=GateDecision.PASS),
    GateNo.POLICY: GateResult(gate_no=GateNo.POLICY, passed=True, decision=GateDecision.PASS),
    GateNo.COST: GateResult(gate_no=GateNo.COST, passed=True, decision=GateDecision.PASS),
}


def _meta_payload() -> dict[str, object]:
    # 07 §14.3 约束 7：`meta` 必须带 `scope` 与 `retrieval_mode`（缺一即为契约违规）。
    return {
        "bundle_version": "2026.09.1",
        "cost_cny": "0.0000",
        "tokens": {"input": 1, "output": 1, "cache_hit": 0, "total": 2},
        "latency_ms": {"total": 10},
        "trace_id": "trace-1",
        "scope": {"level": "unrestricted"},
        "retrieval_mode": "hybrid",
    }


def _full_flow() -> list[tuple[str, dict[str, object], dict[str, object] | None]]:
    return [
        ("trusted_context", {}, None),
        ("normalize", {}, None),
        ("intent", {"intent": "executable"}, None),
        ("link", {"candidates": [{"asset_id": "a", "score": 1.0}]}, None),
        ("plan", {"plan_summary": {"metrics": ["gmv"]}}, None),
        ("bind", {"binding_status": "resolved_unique"}, None),
        (
            "gen_sql",
            {"sql_text": "SELECT 1", "sql_dialect": "postgres", "confidence": 0.9},
            None,
        ),
        ("gate1_ast", {}, None),
        ("gate2_policy", {}, None),
        ("gate3_cost", {"gate_results": _CLEAN_GATES}, None),
        ("execute", {}, None),
        ("mask", {}, None),
        (
            "audit_pre",
            {"result_columns": [{"name": "gmv", "type_name": "numeric", "unit": "CNY"}],
             "row_count": 1, "truncated": False},
            {"rows": [["1.23"]]},
        ),
        (
            "present",
            {
                "chart_spec": {"chart_type": "kpi", "option": {"series": []}},
                "insight": {"text": "1 行", "caveats": [], "citations": []},
            },
            {"meta": _meta_payload()},
        ),
        ("audit_supp", {}, None),
    ]


def _recorder(**kwargs: object) -> EventRecorder:
    return EventRecorder(encoder=encode, **kwargs)  # type: ignore[arg-type]


def _frames(recorder: EventRecorder) -> list[tuple[str, dict[str, object]]]:
    """把队列里的帧解回 `(event, data)`，供顺序/终态断言使用。"""
    parsed: list[tuple[str, dict[str, object]]] = []
    while not recorder.queue.empty():
        raw = recorder.queue.get_nowait()
        assert raw is not None
        text = raw.decode()
        lines = text.strip().split("\n")
        event = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        parsed.append((event, data))
    return parsed


def _play_clean_flow(recorder: EventRecorder) -> None:
    recorder.ack(task_id="t-1", session_id="s-1")
    for node, update, extras in _full_flow():
        recorder.on_node(node, update, extras=extras)


# ---------------------------------------------------------------------------
# 发射点全覆盖（DoD ①/③ 的机制侧）
# ---------------------------------------------------------------------------


def test_contract_counts_anchor() -> None:
    """先钉住"17 发射点 = 12 事件类型 + 6 个 stage"这条口径（`SseEvent` 文档串的原文）。"""
    assert len(SseEvent) == 12
    assert len(Stage) == 6
    assert len(SSE_STAGE_EMISSION_POINTS) == 17
    assert len(SSE_TERMINAL_EVENTS) == 4


def test_all_17_emission_points_are_reachable() -> None:
    """**17 发射点全部可达** —— 这是"覆盖全部出口路径"里"路径"那一半的可执行证明。

    覆盖手法（**必须跨多条流**，因为终态唯一性会把同一条流上的第 2 个终态丢掉）：
    · 流 1：干净链路（`ack` + 6 个 `stage` + `data`/`chart`/`insight`/`meta` + `complete`）
      ＋ `degraded`（必须在终态之前）＋ `heartbeat`（唯一允许在终态之后的）→ 14 点；
    · 流 2~4：三个**非成功出口**各一发（`clarify` / `refuse` / `error`）→ 3 点。
    合计 17。
    """
    covered: set[tuple[SseEvent, Stage | None]] = set()

    main = _recorder()
    main.ack(task_id="t-1", session_id="s-1")
    for node, update, extras in _full_flow()[:-1]:  # 截至 `present`（不含 `audit_supp`）
        main.on_node(node, update, extras=extras)
    main.degraded(reason=DegradedReason.PRESENT_FAILED, action_taken=ActionTaken.TABLE_ONLY)
    main.on_node("audit_supp", {})
    main.heartbeat()
    covered |= {(e.event, e.stage) for e in main.emissions}

    for node, update in (
        (
            "clarify_out",
            {"clarify": {"clarify_id": "c-1", "question": "q", "options": [], "reason": "ambiguity"}},
        ),
        ("refuse_out", {"terminal": {"event": "refuse", "reason": "no_data_asset"}}),
        ("error_out", {"terminal": {"event": "error", "code": "INTERNAL"}}),
    ):
        branch = _recorder()
        branch.on_node(node, update)
        covered |= {(e.event, e.stage) for e in branch.emissions}

    assert covered == set(SSE_STAGE_EMISSION_POINTS)


def test_terminal_paths_are_all_reachable() -> None:
    """四条出口路径各自能产出自己的终止事件（`complete` / `clarify` / `refuse` / `error`）。

    ⚠️ 每条路径用**独立**的 recorder —— 终止事件唯一性是**流级**状态，
    复用同一个实例会让第 2~4 条路径的事件被守卫丢掉（那正是它该做的）。
    """
    cases: list[tuple[str, dict[str, object], SseEvent]] = [
        ("audit_supp", {}, SseEvent.COMPLETE),
        (
            "clarify_out",
            {"clarify": {"clarify_id": "c-1", "question": "哪个时间段？", "options": [], "reason": "time_ambiguous"}},
            SseEvent.CLARIFY,
        ),
        ("refuse_out", {"terminal": {"event": "refuse", "reason": "no_data_asset"}}, SseEvent.REFUSE),
        ("error_out", {"terminal": {"event": "error", "code": "INTERNAL"}}, SseEvent.ERROR),
    ]
    for node, update, expected in cases:
        recorder = _recorder()
        recorder.on_node(node, update)
        assert [emission.event for emission in recorder.emissions] == [expected]
        assert recorder.terminal_count == 1


# ---------------------------------------------------------------------------
# §14.3 约束 1/3：终态唯一性 + 终态后禁发
# ---------------------------------------------------------------------------


def test_exactly_one_terminal_true_over_full_flow() -> None:
    """§14.3 约束 1（N-08）：每条流**有且仅有 1 个** `terminal:true`。"""
    recorder = _recorder()
    _play_clean_flow(recorder)
    frames = _frames(recorder)
    terminals = [event for event, data in frames if data["terminal"] is True]
    assert terminals == [SseEvent.COMPLETE.value]
    assert recorder.terminal_count == 1


def test_second_terminal_is_dropped_and_recorded() -> None:
    recorder = _recorder()
    recorder.on_node("audit_supp", {})  # complete（终态）
    recorder.on_node("refuse_out", {"terminal": {"event": "refuse"}})  # 第二条终态
    assert [emission.event for emission in recorder.emissions] == [SseEvent.COMPLETE]
    assert recorder.dropped == (SseEvent.REFUSE.value,)
    assert recorder.violations  # `ui_contract_violation` 已记录


def test_no_event_after_terminal_except_heartbeat() -> None:
    """§14.3 约束 3：终态之后禁止任何事件（**心跳除外**）。"""
    recorder = _recorder()
    recorder.on_node("audit_supp", {})
    recorder.on_node("present", {"chart_spec": {"chart_type": "kpi", "option": {}}})
    recorder.heartbeat()
    events = [event for event, _ in _frames(recorder)]
    assert events == [SseEvent.COMPLETE.value, SseEvent.HEARTBEAT.value]


def test_refuse_excludes_data() -> None:
    """§14.3 约束 5：**禁止** `refuse` + `data`（拒答不给数据）。

    机制上由"终态之后一律丢弃"承担 —— 这条断言把那个一般机制钉到具体场景上，
    因为"拒答却带数据"是**合规**问题，不是渲染问题。
    """
    recorder = _recorder()
    recorder.on_node("refuse_out", {"terminal": {"event": "refuse", "reason": "pii_blocked"}})
    recorder.on_node("audit_pre", {"result_columns": [], "row_count": 0, "truncated": False})
    assert [event for event, _ in _frames(recorder)] == [SseEvent.REFUSE.value]


# ---------------------------------------------------------------------------
# §14.3 约束 4：degraded 在终态之前、且永不是终止事件
# ---------------------------------------------------------------------------


def test_degraded_is_never_terminal_and_precedes_complete() -> None:
    """§14.3 约束 4 + A.1.3：转异步 / 降级场景下 `degraded` 在前、`complete` 在后。"""
    recorder = _recorder()
    recorder.degraded(
        reason=DegradedReason.LATENCY_EXCEEDED, action_taken=ActionTaken.SWITCHED_TO_ASYNC
    )
    recorder.on_node("audit_supp", {})
    events = [event for event, _ in _frames(recorder)]
    assert events == [SseEvent.DEGRADED.value, SseEvent.COMPLETE.value]
    assert recorder.emissions[0].event not in SSE_TERMINAL_EVENTS


def test_degraded_after_terminal_is_dropped() -> None:
    recorder = _recorder()
    recorder.on_node("audit_supp", {})
    recorder.degraded(reason=DegradedReason.PRESENT_FAILED, action_taken=ActionTaken.TABLE_ONLY)
    assert recorder.dropped == (SseEvent.DEGRADED.value,)


# ---------------------------------------------------------------------------
# 约束 7/8：meta 必填键、stage 只有 6 值
# ---------------------------------------------------------------------------


def test_meta_missing_keys_are_reported_not_invented() -> None:
    """§14.3 约束 7：缺 `scope` / `retrieval_mode` 即为契约违规 —— **记违规，不补默认值**。"""
    recorder = _recorder()
    recorder.on_node("present", {"insight": {"text": "x"}}, extras={"meta": {"trace_id": "t"}})
    meta_emissions = [e for e in recorder.emissions if e.event is SseEvent.META]
    assert len(meta_emissions) == 1
    assert missing_meta_keys(meta_emissions[0].data) == (
        "bundle_version",
        "cost_cny",
        "tokens",
        "latency_ms",
        "scope",
        "retrieval_mode",
    )
    assert any("meta 事件缺必填键" in violation for violation in recorder.violations)


def test_stage_values_are_enum_backed() -> None:
    """DoD ③：`stage` 只有 6 个取值，且由枚举产出（历史病害 `data_ready`/`complete` 进不来）。"""
    recorder = _recorder()
    _play_clean_flow(recorder)
    stages = [data["stage"] for event, data in _frames(recorder) if event == SseEvent.STAGE.value]
    assert set(stages) <= {stage.value for stage in Stage}
    assert stages == [
        Stage.INTENT.value,
        Stage.SCHEMA_LINKING.value,
        Stage.PLAN_READY.value,
        Stage.SQL_READY.value,
        Stage.GATE_PASSED.value,
        Stage.EXECUTING.value,
    ]


def test_gate_passed_requires_clean_pass() -> None:
    """§14.2 D5/D6：`warn` / `skipped` **不得报告为通过**，但仍要发 `executing`。"""
    for decision in (GateDecision.WARN, GateDecision.SKIPPED):
        gates = dict(_CLEAN_GATES)
        gates[GateNo.COST] = GateResult(gate_no=GateNo.COST, passed=True, decision=decision)
        emissions = emissions_for_node("gate3_cost", {"gate_results": gates}, elapsed_ms=1)
        assert [e.stage for e in emissions] == [Stage.EXECUTING]


def test_sql_ready_event_is_emitted_without_sql_when_explain_false() -> None:
    """07 §5.6：`explain=false` 时**省略 `sql` 字段但事件照发**。"""
    emissions = emissions_for_node(
        "gen_sql",
        {"sql_text": "SELECT 1", "sql_dialect": "postgres", "confidence": 0.5},
        elapsed_ms=1,
        explain=False,
    )
    assert len(emissions) == 1
    assert emissions[0].stage is Stage.SQL_READY
    assert "sql" not in emissions[0].data
    assert emissions[0].data["dialect"] == "postgres"


# ---------------------------------------------------------------------------
# 机制自证：`terminal` 单点注入、节点名全覆盖、gate_detail 结构
# ---------------------------------------------------------------------------


def test_emission_may_not_carry_terminal() -> None:
    """`terminal` 由 `push()` 单点注入 —— 调用方自带它直接抛错（防"多处各自设置"）。"""
    from app.graph.events import Emission

    recorder = _recorder()
    with pytest.raises(ContractViolationError):
        recorder.push(Emission(SseEvent.DATA, {"terminal": False}))


def test_every_node_name_is_handled() -> None:
    """19 个节点名全部有明确处置（发事件或**有意静默**），且静默集合被显式登记。

    ⚠️ 静默集合写死是刻意的：给某个节点"顺手"加事件时，本条会红，
    逼作者回 07 §5.6 确认那个时机是否真的存在。
    """
    silent = {
        "trusted_context",
        "normalize",
        "bind",
        "gate1_ast",
        "gate2_policy",
        "execute",
        "mask",
        "repair",
    }
    assert silent <= set(MAIN_NODE_NAMES)
    for node in ALL_NODE_NAMES:
        emissions = emissions_for_node(node, {}, elapsed_ms=0)
        if node in silent:
            assert emissions == (), f"{node} 按 §5.6 不发事件"
        else:
            assert emissions, f"{node} 应当发至少一个事件"
    assert set(TERMINAL_NODE_NAMES) <= set(ALL_NODE_NAMES)


def test_gate_detail_follows_c02_shape() -> None:
    """补充契约 C-02：`gate_detail` 三个闸门各有 `passed`/`rule_id?`/`reason?`，
    `cost` 另有 `decision`/`estimated_rows`/`estimated_cost`。"""
    detail = gate_detail(_CLEAN_GATES)
    assert set(detail) == {"ast", "policy", "cost"}
    for key in ("ast", "policy"):
        assert {"passed", "rule_id", "reason"} <= set(detail[key])
    assert {"passed", "rule_id", "reason", "decision", "estimated_rows", "estimated_cost"} <= set(
        detail["cost"]
    )
    assert detail["cost"]["decision"] == GateDecision.PASS.value
