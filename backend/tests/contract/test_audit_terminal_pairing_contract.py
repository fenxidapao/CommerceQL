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

from app.core.enums import SSE_TERMINAL_EVENTS, Outcome, SseEvent
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
