"""U-135（QA 第 8 轮的 X6）：`recursion_limit` 超限的**契约 vs 现实**冲突夹具（零额度、零活体）。

| 面 | 内容 |
|---|---|
| 契约 | `docs/07` §17.2 决策表 G4 行：`recursion_limit` 超限（25）⇒ `error` / `INTERNAL` / 终态 ✅ / **审计 ✅** / `outcome=failed` / retryable ⭕ |
| 现实 | `app/api/runner.py:482` 的兜底 `except Exception` 只补发 `error(INTERNAL)`；`audit_pre` 节点没跑到 ⇒ **零条审计行**。全仓 `app/**` 内 `GraphRecursionError` 命中 **0**（本窗 2026-10-04 复算同值）⇒ 该触发面与 X1（通用异常）**同一条支路** |

三条夹具的分工（缺任何一条，这个冲突都会静默地活下来）：

1. `test_recursion_blowup_current_shape` —— 钉**现状形状**：终态 `INTERNAL` ＋ 零条审计行。
   修好那天这一条必须翻红 ⇒ 与 `docs/07` 台账的 `U-135` 行同时改（不许只改代码留一份过期判据）。
2. `test_decision_table_g4_still_demands_audit_row` —— 钉**契约面**：G4 那行的「审计」列仍是 ✅。
   有人把契约改成 ❌（"设计豁免"）而没有走裁定 ⇒ 这条红。
3. `test_u135_registered_and_names_this_trigger` —— 钉**台账在位**：`U-135` 存在且指向 recursion 触发面。
   有人改了契约或代码却没登记 ⇒ 这条红。

零额度：桩件 `astream` 直接抛 `GraphRecursionError`，不进 LLM、不进 DB。
"""

from __future__ import annotations

import io
import os
from typing import Any

from langgraph.errors import GraphRecursionError

from app.api.runner import SseRunner
from app.api.state_store import RedisStateStore
from app.core.enums import SseEvent
from tests.contract.test_api_runner_contract import (
    _DepsHolder,
    _frames,
)
from tests.unit._redis_fake import FakeRedis

__all__ = [
    "test_recursion_blowup_current_shape",
    "test_decision_table_g4_still_demands_audit_row",
    "test_u135_registered_and_names_this_trigger",
]

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_TDD = os.path.join(_ROOT, "docs", "07_技术设计文档_TDD.md")


class _RecursionGraph:
    """LangGraph 撞到 `recursion_limit` 时从 `astream` 里抛 `GraphRecursionError`。"""

    def __init__(self, emissions: list[dict[str, Any]] | None = None) -> None:
        self._emissions = emissions or []

    async def astream(self, *_a: Any, **_kw: Any):  # pragma: no cover - 桩件
        for chunk in self._emissions:
            yield chunk
        raise GraphRecursionError("Node `gen_sql` reached the recursion limit of 25.")


def _drive(emissions: list[dict[str, Any]] | None = None) -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    holder = _DepsHolder("refuse_intent")
    runner = SseRunner(  # type: ignore[assignment]
        graph=_RecursionGraph(emissions),
        store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
        new_deps=holder,
        heartbeat_s=15,
        cancel_poll_s=1.0,
    )
    frames = _frames(runner)
    return frames, holder.last.audit


def _tdd_lines() -> list[str]:
    with io.open(_TDD, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_recursion_blowup_current_shape() -> None:
    """现状：终态 `error(INTERNAL)` 有、**审计行一条没有** ⇒ 与 G4 的「审计 ✅」冲突。"""
    frames, audit = _drive()
    terminals = [(ev, data) for ev, data in frames if ev == SseEvent.ERROR.value]
    assert len(terminals) == 1, frames
    assert terminals[0][1]["code"] == "INTERNAL", terminals[0]
    assert audit.pre == [] and audit.supp == []


def test_decision_table_g4_still_demands_audit_row() -> None:
    """契约面：G4 行「审计」列必须是 ✅（列位从**它自己那张表**的表头取，不硬数列号）。"""
    lines = _tdd_lines()
    g4 = [i for i, ln in enumerate(lines) if ln.startswith("| G4 |")]
    assert len(g4) == 1, g4
    head = [i for i in range(g4[0]) if lines[i].startswith("| # | 失败点 | 事件 |")]
    assert head, lines[max(0, g4[0] - 6) : g4[0]]
    head_cells = [c.strip() for c in lines[head[-1]].strip("|").split("|")]
    cells = [c.strip() for c in lines[g4[0]].strip("|").split("|")]
    assert len(cells) == len(head_cells), (head_cells, cells)
    assert "✅" in cells[head_cells.index("审计")], cells
    assert "recursion_limit" in cells[1], cells


def test_u135_registered_and_names_this_trigger() -> None:
    """台账：`U-135` 在位，且那一行点名 recursion 触发面与审计缺口。"""
    hits = [ln for ln in _tdd_lines() if "U-135" in ln]
    assert len(hits) >= 1, hits
    joined = " ".join(hits)
    assert "recursion" in joined.lower() and "审计" in joined, joined
    assert "G4" in joined, joined
