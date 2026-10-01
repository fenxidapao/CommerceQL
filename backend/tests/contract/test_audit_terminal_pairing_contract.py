"""结构锁（`U-129` 的门禁化，W7 09-28 上呈"admitted − 审计行差 = 0"）：
**每一个终态都必须有一条段 1 审计行**，且四种终态**逐一**被覆盖。

为什么是结构断言而不是又一处逐例断言：A–G 组各例已断"审计段 1 落行"（实证
`test_decision_table_contract.py:151`、`test_decision_table_d_e.py:72`），但那些是**散在**各组的单点断言 ——
`U-129` 那次事故（8 条 `error(INTERNAL)`、审计 0 行）走的正是"终态设了、审计没落"的缝，
而缝的出现方式=**新增一条终态路径而没人给它加断言**。本文件钉的是集合本身：

- `TERMINAL_AUDIT_OUTCOME` 的键集必须等于 `SSE_TERMINAL_EVENTS`（`core/enums.py:146`）
  ⇒ 以后多一种终态事件而没登记审计 `outcome` ⇒ **当场红**（而不是等某次压测差 8 行）。
- 反向也钉：取值必须落在真 `Outcome` 词表内，且 5 值里**唯一**没有终态的必须是 `DEGRADED`
  （它不发终止帧）⇒ 新增/改名 `Outcome` 而没人说明它对应哪个终态 ⇒ 同样当场红。
- 每个键都要有一档**真跑图**的场景，断言"恰 1 个终态 + 恰 1 条 `audit.pre` 行 + `outcome` 逐字相等"。
- 具名例外 = `audit_pre` 写库失败（决策表 G1）：此时审计 0 行是**设计**（fail-closed，
  且终态已被 `error_out` 定成 `INTERNAL`，N-08 不许改）。该例外必须**点名**，
  不得泛化成"0 行也可以" —— 否则这条锁退化成恒真。
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.contracts import IdentityContext
from app.core.enums import SSE_TERMINAL_EVENTS, Outcome, Role, SseEvent
from app.graph.build import build_graph
from app.graph.state import (
    RUN_SCOPED_STATE_FIELDS,
    identity_fields,
    initial_state,
)
from app.planner.schemas import IntentKind
from tests.contract._fullchain_deps import make_chain, run_chain, terminal_frames
from tests.contract.test_decision_table_contract import _outcome, _run

#: 终态事件 → 段 1 审计行的 `outcome`（逐字实测值，非推测）。
TERMINAL_AUDIT_OUTCOME: dict[str, str] = {
    SseEvent.COMPLETE.value: "success",
    SseEvent.REFUSE.value: "refuse",
    SseEvent.ERROR.value: "failed",
    SseEvent.CLARIFY.value: "clarify",
}


def _identity() -> IdentityContext:
    """入口断言用的身份（值固定 ⇒ 断言只关心"复位了什么"，不关心身份本身）。"""
    return IdentityContext(
        trace_id="t",
        task_id="t",
        session_id="t",
        tenant_id="T_A",
        user_id="u",
        role=Role.ANALYST,
    )


def _make_scenario(event: str) -> tuple[list[tuple[str, dict[str, Any]]], Any, list[dict[str, Any]]]:
    """跑出给定终态的一档真图，返回 `(帧序列, RunOutcome, audit.pre)`。"""
    if event == SseEvent.COMPLETE.value:
        chain = make_chain()
        frames, out = run_chain(chain)
        return frames, out, chain.audit.pre
    if event == SseEvent.REFUSE.value:
        chain = make_chain(plan_blocked_issues=("缺表",))
        frames, out = run_chain(chain)
        return frames, out, chain.audit.pre
    if event == SseEvent.ERROR.value:
        # 多语句 → gate1 R02 → error(GATE_AST_REJECTED)
        chain = make_chain(sql="SELECT 1; SELECT 2")
        frames, out = run_chain(chain)
        return frames, out, chain.audit.pre
    if event == SseEvent.CLARIFY.value:
        # A 组件（同为 W4 面）的最小 planner 档位：意图=需澄清 → clarify
        frames, out, audit = _run(_outcome(intent=IntentKind.CLARIFY))
        return frames, out, audit.pre
    raise AssertionError(f"未登记场景的终态事件：{event}（请在上方补一档）")


def test_terminal_kind_set_is_the_whole_enum() -> None:
    """新增/删除一种终态 ⇒ 必须同时在这里登记，否则红。"""
    assert set(TERMINAL_AUDIT_OUTCOME) == {event.value for event in SSE_TERMINAL_EVENTS}


def test_audit_vocabulary_closes_on_both_ends() -> None:
    """审计侧取值必须是真 `Outcome`，且**具名**说明谁没有终态 —— 防另一向漂移。

    `Outcome` 有 5 值（`core/enums.py:384`）而终态事件只有 4 个：`DEGRADED` 不发终止帧
    （`core/enums.py:145` 注释：degraded 是"发生了降级"的通知，不是"这一轮结束了"）。
    ⇒ 差集必须**恰好**是 `{DEGRADED}`：多一个 ⇒ 有终态没登记；少一个 ⇒ 有人在造新的终态口径。
    """
    assert set(TERMINAL_AUDIT_OUTCOME.values()) <= {o.value for o in Outcome}
    assert {o.value for o in Outcome} - set(TERMINAL_AUDIT_OUTCOME.values()) == {
        Outcome.DEGRADED.value
    }


@pytest.mark.parametrize("event", sorted(TERMINAL_AUDIT_OUTCOME))
def test_every_terminal_has_exactly_one_audit_row(event: str) -> None:
    """逐终态 1:1：恰一个终态帧、恰一条段 1 审计行、`outcome` 逐字对得上。"""
    frames, _out, audit_pre = _make_scenario(event)

    terminals = terminal_frames(frames)
    assert len(terminals) == 1, f"{event} 路径冒出多个终态：{terminals}"
    assert terminals[0][0] == event

    assert len(audit_pre) == 1, (
        f"{event} 终态但段 1 审计行数 = {len(audit_pre)} ⇒ 压测侧会出现 admitted − 审计行差 ≠ 0"
        f"（U-129 的形状：终态设了、审计没落）"
    )
    assert audit_pre[0]["outcome"] == TERMINAL_AUDIT_OUTCOME[event]


def test_audit_write_failure_is_the_only_named_zero_row_case() -> None:
    """具名例外（决策表 G1）：`audit_pre` 写库失败 ⇒ 0 行 + `error(INTERNAL)`，fail-closed 不下发结果。

    这条同时是本文件第 2 组断言的**反向对照**：如果"0 行"是泛化允许的，就不会有红 ——
    这里它只在被点名时成立。
    """
    chain = make_chain(audit_pre_fail=True)
    frames, _out = run_chain(chain)

    assert len(chain.audit.pre) == 0
    terminals = terminal_frames(frames)
    assert len(terminals) == 1
    assert terminals[0][0] == SseEvent.ERROR.value
    assert terminals[0][1]["code"] == "INTERNAL"
    # N-09：段 1 没落库就不该有 data 帧（结果不下发）。
    assert all(e != "data" for e, _ in frames)


# ===========================================================================
# `U-129` 判据⑦（入口不变量）：每个新 run 起点必须 `state.terminal is None`
# ---------------------------------------------------------------------------
# 为什么这一组要钉"集合"而不只是钉 `terminal` 一个键：入口只复位 `terminal` 能让
# `route_terminal` 不再误跳，但 `outcome`/`sql_text`/`gate_results` 仍会被下一轮读到，
# 而 `nodes/_shared.py:353` 把 `sql_text` 当 `final_executed_sql` 写进**段 1 审计载荷**
# ⇒ 审计正确性也在这条不变量里。机制与两侧症状见 `reports/w4/RELAY.md §二十四/§二十六`。
# ===========================================================================


class TestU129EntryInvariant:
    """入口不变量 = 组 2–11 每轮复位；含"同 thread 连跑多轮"的真图臂。

    🔴 「本轮自己写了终态」在**生产落库面**的等价读点（W4 2026-10-01 直读 `lg` 复算）：
    `lg.checkpoint_writes.channel = 'terminal'` 按写行的 `checkpoint_id` 连回带 `tk_` 的检查点
    ⇒ run 归属。该面对四种终态都有实例（refuse 423 / failed 206 / clarify 114 / success 70 = 813 条 run），
    且 turn≥2 的 run **确实有写行**（39/39 有 `branch:to:%` 行）只是 `terminal` = 0 ⇒ 修复前那个 0 是
    **真读数**，不是"写面黏在第一轮"的量具假象。
    ⚠️ `branch:to:%` 只证"被路由到"、不证"写了终态"：修复前 `branch:to:audit_supp` = 75 条 run
    （turn1 的 70 条**全部**带 `terminal` 写；turn≥2 的 5 条**一条都没有**、且全部零审计行）
    ⇒ 「被路由到出口节点 ⇒ 本轮写了 terminal」这一蕴含式在修复前**恰好只崩在这 5 条崩臂上**。
    """

    def test_run_scoped_set_is_derived_and_contains_terminal(self) -> None:
        """派生集合本身要先钉住：漏一个键 = 那一轮的该键跨轮带回来。"""
        assert "terminal" in RUN_SCOPED_STATE_FIELDS
        # 身份键由请求每轮重写 ⇒ 既不该被复位，也不该混进复位集（混进来的话 `role`/`scope` 会变 None）
        assert set(identity_fields(_identity())) & RUN_SCOPED_STATE_FIELDS == set()

    def test_entry_state_has_terminal_present_and_none_and_nothing_else_carried(self) -> None:
        st = dict(initial_state(_identity(), raw_question="这一轮的问题"))
        assert "terminal" in st and st["terminal"] is None
        carried = [
            k for k in RUN_SCOPED_STATE_FIELDS if k not in st or st[k] is not None
        ]
        assert carried == [], f"入口未复位的 run 级通道：{sorted(carried)}"

    def test_request_body_fields_are_written_even_when_absent(self) -> None:
        """这一轮没带 `options` ⇒ 必须写 `None`，不能"不写键"（不写键 = 继承上一轮的值）。"""
        st = dict(initial_state(_identity(), raw_question="q"))
        assert st["options"] is None
        assert st["idempotency_key"] is None

    def test_second_run_on_one_thread_writes_its_own_terminal_and_full_chain(self) -> None:
        graph = build_graph(checkpointer=MemorySaver())
        first = make_chain()
        f1, o1 = run_chain(first, graph=graph)
        second = make_chain()
        f2, o2 = run_chain(second, graph=graph)

        assert terminal_frames(f1)[0][0] == SseEvent.COMPLETE.value
        assert [e for e, _ in terminal_frames(f2)] == [SseEvent.COMPLETE.value]
        assert len(second.audit.pre) == 1 and second.audit.pre[0]["outcome"] == "success"
        # 全链重跑 = 第 2 轮没有被上一轮的终态接去出口（那条路只跑 2–3 个节点）
        assert len(o1.nodes) == len(o2.nodes) == 15

    def test_refuse_residue_does_not_become_the_next_turns_conclusion(self) -> None:
        """§26.2 那格的回归位：残留 `refuse` 曾让第 2 轮"复用上一轮拒答 + 多落一条审计行"。"""
        graph = build_graph(checkpointer=MemorySaver())
        blocked = make_chain(plan_blocked_issues=("缺表",))
        fb, _ob = run_chain(blocked, graph=graph)
        assert [e for e, _ in terminal_frames(fb)] == [SseEvent.REFUSE.value]

        green = make_chain()
        fg, _og = run_chain(green, graph=graph)
        assert [e for e, _ in terminal_frames(fg)] == [SseEvent.COMPLETE.value]
        assert len(green.audit.pre) == 1 and green.audit.pre[0]["outcome"] == "success"

    def test_previous_turns_sql_never_lands_in_this_turns_audit_row(self) -> None:
        """审计正确性那一半：本轮在 `plan` 就拒答 ⇒ 它的段 1 行**不得**带上一轮跑出来的 SQL。"""
        graph = build_graph(checkpointer=MemorySaver())
        ran = make_chain()
        run_chain(ran, graph=graph)
        assert "final_executed_sql" in ran.audit.pre[0]

        blocked = make_chain(plan_blocked_issues=("缺表",))
        run_chain(blocked, graph=graph)
        assert blocked.audit.pre[0]["outcome"] == "refuse"
        assert "final_executed_sql" not in blocked.audit.pre[0], (
            "第 2 轮自己没生成 SQL，却把上一轮的 SQL 写进了本轮审计行 ⇒ 入口复位漏了这个通道"
        )

    def test_three_turns_on_one_thread_keep_pairing_each_turn(self) -> None:
        """毒化是累计的：跑三轮，每轮都要"恰 1 终态 + 恰 1 段 1 行"。"""
        graph = build_graph(checkpointer=MemorySaver())
        for turn in range(3):
            chain = make_chain()
            frames, out = run_chain(chain, graph=graph)
            assert len(terminal_frames(frames)) == 1, f"第 {turn + 1} 轮终态数 ≠ 1"
            assert len(chain.audit.pre) == 1, f"第 {turn + 1} 轮段 1 审计行数 ≠ 1"
            assert len(out.nodes) == 15, f"第 {turn + 1} 轮没有重跑全链"
