"""P0-A-3（U-142）：历史载体 —— 入口播种、顺序、只取问题、读失败不炸。

**为什么值得钉住**：`normalize` 的 `history=()` 是 U-142 的**根因**（多轮指代失效）。
本轮补上了载体（`GraphState.history_questions`）与两处接线，本文件钉住三件**容易错**的事：
1. **顺序**：`sess:plan` 是 `LPUSH`（**最新在前**），而提示词要**时间正序** —— 反了就变成"倒着讲历史"；
2. **只取问题**：`get_turns` 的条目里还有 `outcome` / `plan_summary` / `bundle_version`，
   它们**不得**进 prompt（§10.5 ⑥ 禁"历史 SQL 与结果"；`plan_summary` 是计划摘要）；
   其中 `plan_summary` 自 B6（U-154）起会经**白名单脱敏**进 `history_plan` 供条件继承，
   但**仍不出站**（不在 `PROMPT_ALLOWED_FIELDS`）。
3. **读失败不炸**：Redis 抖一下不得把一次正常查询变成 `INTERNAL`（与 `clarify.py:272-278` 的
   写失败同口径），且必须**告警**而不是静默吞掉。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.api.runner import SseRunner
from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.graph.state import initial_state

_IDENTITY = IdentityContext(
    trace_id="tr-p0a3", task_id="tk-p0a3", session_id="se-p0a3",
    tenant_id="T_A", user_id="u-owner", role=Role.ANALYST,
    scope_claims=(), shop_ids=(),
)


class _FakeStore:
    def __init__(self, turns: Any = (), *, boom: bool = False) -> None:
        self._turns = turns
        self._boom = boom
        self.calls = 0

    async def get_turns(self, identity: IdentityContext, session_id: str) -> Any:
        self.calls += 1
        if self._boom:
            raise RuntimeError("redis 抖了")
        return self._turns


class _FakeRunner:
    """只带 `_store` 的壳 —— 被测的是纯函数式的历史读取方法。"""

    #: 兼容入口 `_read_session_history` 内部会调 `_read_session_context`；
    #: 把真实实现绑到壳上，测的就是同一条代码路径。
    _read_session_context = SseRunner._read_session_context

    def __init__(self, store: _FakeStore) -> None:
        self._store = store


def _read(store: _FakeStore) -> tuple[str, ...]:
    return asyncio.run(SseRunner._read_session_history(_FakeRunner(store), _IDENTITY))  # type: ignore[arg-type]


def _read_context(store: _FakeStore) -> Any:
    return asyncio.run(SseRunner._read_session_context(_FakeRunner(store), _IDENTITY))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ① 入口播种
# ---------------------------------------------------------------------------


def test_initial_state_carries_history_unconditionally() -> None:
    """★ 载体必须在**每个** run 的初始状态里就位（键恒存在，空历史 = 空元组）。"""
    state = initial_state(_IDENTITY, raw_question="它有多少？", history_questions=("上一轮的问题",))
    assert state["history_questions"] == ("上一轮的问题",)
    # 不带历史时**也得有键**（值 `()`）—— 条件写会让"本轮没历史"继承上一轮的值。
    empty = initial_state(_IDENTITY, raw_question="它有多少？")
    assert empty["history_questions"] == ()


def test_history_is_a_request_level_field_not_run_scoped() -> None:
    """★ 载体属**组 1**（入口播种），**不得**被 `initial_state` 的复位逻辑清掉。"""
    from app.graph.state import RUN_SCOPED_STATE_FIELDS, STATE_GROUPS

    assert "history_questions" in STATE_GROUPS["1_request_identity"]
    assert "history_questions" not in RUN_SCOPED_STATE_FIELDS


# ---------------------------------------------------------------------------
# ② 顺序与只取问题
# ---------------------------------------------------------------------------


def test_turns_are_reversed_to_chronological_order() -> None:
    """★ `LPUSH` 最新在前 ⇒ 必须反成时间正序（否则提示词里历史是倒着的）。"""
    store = _FakeStore([
        {"question": "第二问", "outcome": "success", "plan_summary": {"m": 1}},
        {"question": "第一问", "outcome": "success", "plan_summary": {"m": 2}},
    ])
    assert _read(store) == ("第一问", "第二问")


def test_only_questions_are_taken() -> None:
    """★ **只**取 `question`：`outcome` / `plan_summary` **不得**进 prompt（§10.5 ⑥ / N-17）。"""
    got = _read(_FakeStore([{"question": "问一", "plan_summary": {"sql": "SELECT 1"},
                             "outcome": "success"}]))
    assert got == ("问一",)
    assert all("SELECT" not in q for q in got)


def test_turns_without_question_are_skipped() -> None:
    """边界：缺 `question` 的条目跳过（不编空串、不把 None 变成 "None"）。"""
    assert _read(_FakeStore([{"outcome": "success"}, {"question": "有问题的"}, "非映射"])) == ("有问题的",)


def test_empty_history_is_empty_tuple() -> None:
    """边界：首轮（无历史）返回 `()`，不是 `None`（`normalize` 按 `or ()` 读）。"""
    assert _read(_FakeStore([])) == ()


# ---------------------------------------------------------------------------
# ③ 读失败不炸
# ---------------------------------------------------------------------------


def test_read_failure_degrades_to_empty_history(capsys: pytest.CaptureFixture[str]) -> None:
    """★ 反例：读失败**不抛**、退化为空历史，且**必须告警**（不许静默吞）。

    ⚠️ 断言方式：本项目的结构化日志走 **structlog → stdout**（不经过 stdlib `logging`
    的 `caplog` 通道）⇒ 用 `capsys` 抓 stdout，别用 `caplog`（第一版就是这么误判的）。
    """
    store = _FakeStore(boom=True)
    got = _read(store)
    assert got == (), "读失败必须退化为空历史，而不是把本轮炸成 INTERNAL"
    assert store.calls == 1
    out = capsys.readouterr().out
    assert "session_history_read_failed" in out, (
        f"读失败必须留一条告警（静默吞掉 = 下一个人的坑）：stdout={out[:200]!r}"
    )


# ---------------------------------------------------------------------------
# ④ B6（U-154）：上一轮脱敏计划摘要
# ---------------------------------------------------------------------------


def test_initial_state_carries_history_plan_unconditionally() -> None:
    state = initial_state(
        _IDENTITY,
        raw_question="那华东区呢？",
        history_plan={"metrics": ["gmv"], "filters": ["region = '华东'"]},
    )
    assert state["history_plan"] == {"metrics": ["gmv"], "filters": ["region = '华东'"]}
    assert initial_state(_IDENTITY, raw_question="新问题")["history_plan"] is None


def test_history_plan_is_group_one_and_not_prompt_allowed() -> None:
    from app.graph.state import PROMPT_ALLOWED_FIELDS, RUN_SCOPED_STATE_FIELDS, STATE_GROUPS

    assert "history_plan" in STATE_GROUPS["1_request_identity"]
    assert "history_plan" not in RUN_SCOPED_STATE_FIELDS
    assert "history_plan" not in PROMPT_ALLOWED_FIELDS, (
        "计划摘要只供确定性继承，不得直接出站（出站面由本轮 plan 承担）"
    )


def test_context_takes_latest_plan_and_drops_non_c01_fields() -> None:
    store = _FakeStore([
        {
            "question": "那华东区呢？",
            "plan_summary": {
                "metrics": ["gmv"],
                "dimensions": ["region"],
                "time_range": {"start": "2026-08-01", "end": "2026-08-31"},
                "limit": 10,
                # 以下都不得进 history_plan：
                "task_id": "tk-old",
                "outcome": "success",
                "bundle_version": "v-old",
                "at": "2026-10-01T00:00:00+08:00",
                "sql": "SELECT 1",
            },
        },
        {
            "question": "上月 GMV 是多少",
            "plan_summary": {"metrics": ["gmv"], "dimensions": ["city"]},
        },
    ])
    ctx = _read_context(store)
    assert ctx.questions == ("上月 GMV 是多少", "那华东区呢？")
    assert ctx.plan == {
        "metrics": ["gmv"],
        "dimensions": ["region"],
        "time_range": {"start": "2026-08-01", "end": "2026-08-31"},
        "limit": 10,
    }


def test_latest_turn_without_plan_means_no_inheritance() -> None:
    """上一轮是澄清/拒答（无 `plan_summary`）⇒ 不拿更早的计划硬接。"""
    ctx = _read_context(_FakeStore([
        {"question": "那华东区呢？", "outcome": "clarify", "plan_summary": None},
        {"question": "上月 GMV 是多少", "plan_summary": {"metrics": ["gmv"]}},
    ]))
    assert ctx.plan is None
