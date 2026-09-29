"""W4 离线探针（**零额度、零外部依赖**）：同一 `thread_id` 的第 2 轮到底发生什么。

由来（2026-09-29）：W7 第二十轮在真实流量里抓到 `terminal(99) − 审计行(95) = 4`，
四条栈顶逐字相同 = `audit_supp.py:49 → _shared.py:165 terminal_update → state.py:480
assert_terminal_is_settable → ValueError`（`deploy/loadtest/r20_internal_attribution.txt`）。
它的触发面读法 = "**属主在自己会话上的第 2 轮**"。⇒ 本件把那条活体路径**离线固化**，
并回答三件它答不了的事：① 残留的到底是哪些通道 ② 是不是只有 `complete` 之后才坏
③ "入口复位"这条修法成不成立。

为什么 `tests/contract/**` 全都没看见它：**整套契约面用 `build_graph()`（`checkpointer=None`）**
⇒ 线程态从不跨 run 累积 ⇒ 这条缝在离线面物理不存在（`_fullchain_deps.py:659` 等 8 处）。

跑法（`cd backend`；本机须先按 `07 §4.8` 的 `U-132` 处理环境，见 RELAY §二十三.1）：
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 PYTHONPATH=<U-132 shim> \
    ../.venv/Scripts/python.exe reports/w4/probe_turn2_checkpoint_residue.py \
        --out reports/w4/probe_turn2_checkpoint_residue.json
退出码：0 = 本件跑完（**不代表"没缺陷"，本件的产出就是缺陷读数**）；非 0 = 探针自己坏了。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))

import app.api.runner as runner_mod  # noqa: E402
from app.api.runner import RunRequest, SseRunner, thread_id_of  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.graph.state import initial_state as real_initial_state  # noqa: E402
from tests.contract._fullchain_deps import (  # noqa: E402
    _IDENTITY,
    FakeRedis,
    RedisStateStore,
    _DepsHolder,
    _parse,
    make_chain,
)

Q1 = "上个月卖得怎么样"
Q2 = "上面那个指标按店铺拆开分别是多少"

#: 组 1 身份通道：每轮由 `initial_state()` 依请求重写 ⇒ 不算"残留"。
IDENTITY_KEYS = frozenset(
    {"trace_id", "task_id", "session_id", "tenant_id", "user_id", "role", "scope"}
)


def _turn(graph: Any, chain: Any, *, tag: str, question: str) -> dict[str, Any]:
    """走**生产同一个** `SseRunner`（不改代码），返回这一轮的终态/审计/节点读数。"""
    runner = SseRunner(
        graph=graph,
        store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
        new_deps=_DepsHolder(chain),
    )
    req = RunRequest(identity=replace(_IDENTITY, task_id=f"tk-{tag}", trace_id=f"tr-{tag}"), question=question)

    async def _collect() -> list[bytes]:
        return [f async for f in runner.stream(req)]

    frames = [_parse(f) for f in asyncio.run(_collect())]
    out = runner.outcome
    return {
        "asked": question,
        "terminal": [[e, d.get("code")] for e, d in frames if d.get("terminal") is True],
        "events": [e for e, _ in frames],
        "audit_rows_this_turn": len(chain.audit.pre),
        "audit_outcomes": [r.get("outcome") for r in chain.audit.pre],
        "nodes_ran": [] if out is None else list(out.nodes),
    }


def _non_empty_channels(graph: Any, config: dict[str, Any]) -> dict[str, str]:
    values: dict[str, Any] = dict(graph.get_state(config).values)
    return {
        k: f"{type(v).__name__}:{str(v)[:48]}"
        for k, v in sorted(values.items())
        if v not in (None, (), {}, [])
    }


def _node_terminal_guard_census() -> dict[str, list[str]]:
    """扫源码判"哪些终态节点在写之前看过 `terminal` 是否已在场"（读盘，不抄结论）。"""
    import re

    out: dict[str, list[str]] = {"guarded": [], "unguarded": []}
    for p in sorted((_BACKEND / "app" / "graph" / "nodes").glob("*.py")):
        text = p.read_text(encoding="utf-8")
        writes = len(re.findall(r"terminal_update\(", text))
        if not writes:
            continue
        guards = len(re.findall(r'get\("terminal"\)\s*(?:is None|or \{\})', text))
        key = f"{p.name}(写 {writes} 处)"
        (out["guarded"] if guards else out["unguarded"]).append(key)
    return out


def _residue_across_turns() -> dict[str, Any]:
    saver = MemorySaver()
    graph = build_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": thread_id_of(_IDENTITY)}}
    t1 = _turn(graph, make_chain(), tag="r1", question=Q1)
    residue = _non_empty_channels(graph, config)
    t2 = _turn(graph, make_chain(), tag="r2", question=Q2)
    return {
        "thread_id_shape": "tenant:user:session（`runner.py:196 thread_id_of`，07 §5.4 逐字）",
        "turn1": t1,
        "residue_at_turn2_entry": residue,
        "residue_key_count": len(residue),
        "run_scoped_residue_keys": sorted(set(residue) - IDENTITY_KEYS),
        "turn2": t2,
        "thread_next_after_turn2": [
            n for n in (graph.get_state(config).next or ())
        ],
    }


def _terminal_kind_matrix() -> dict[str, Any]:
    """第 1 轮的三种终态 × 第 2 轮换一句问题 —— 看坏法是否只有一种。"""
    arms: dict[str, Callable[[], Any]] = {
        "after_complete": lambda: make_chain(),
        "after_refuse_planblocked": lambda: make_chain(plan_blocked_issues=("缺表",)),
        "after_gate1_reject": lambda: make_chain(sql="SELECT 1; SELECT 2"),
    }
    out: dict[str, Any] = {}
    for name, build_first in arms.items():
        graph = build_graph(checkpointer=MemorySaver())
        out[name] = {
            "turn1": _turn(graph, build_first(), tag=f"{name}-1", question=Q1),
            "turn2": _turn(graph, make_chain(), tag=f"{name}-2", question=Q2),
        }
    return out


def _fix_shape_reset_at_entry() -> dict[str, Any]:
    """修法形状实验（**不落地**）：入口把 run 级通道显式写 `None` ⇒ 跨轮残留被切断。

    只回答"方向成不成立"。⚠️ 代价本件不判：`initial_state()` 的 docstring 明写
    "不预先塞空值"（`None` 与"键不存在"在 resume 语义下不同），且 `trusted_context.py:79`
    用 `f not in state` 判在场 —— 那条自检只覆盖组 1，但形状差异本身要架构裁。
    """
    run_keys = [
        k for k in _residue_keys_for_reset() if k not in IDENTITY_KEYS
    ]

    def patched(identity: Any, **kw: Any) -> Any:
        st = real_initial_state(identity, **kw)
        for k in run_keys:
            st[k] = None  # type: ignore[literal-required]
        return st

    original = runner_mod.initial_state
    runner_mod.initial_state = patched  # type: ignore[assignment]
    try:
        graph = build_graph(checkpointer=MemorySaver())
        return {
            "reset_keys": sorted(run_keys),
            "turns": {
                f"turn{i}": _turn(graph, make_chain(), tag=f"fx{i}", question=Q1)
                for i in (1, 2, 3)
            },
        }
    finally:
        runner_mod.initial_state = original  # type: ignore[assignment]


def _residue_keys_for_reset() -> list[str]:
    saver = MemorySaver()
    graph = build_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": thread_id_of(_IDENTITY)}}
    _turn(graph, make_chain(), tag="rk1", question=Q1)
    return list(_non_empty_channels(graph, config))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).with_suffix(".json")))
    args = ap.parse_args()

    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_BACKEND.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ).stdout.strip()
    except Exception:  # pragma: no cover - 探针环境差异不影响读数
        head = ""

    payload = {
        "meta": {
            "produced_by": "reports/w4/probe_turn2_checkpoint_residue.py",
            "read_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "head": head,
            "quota_cost_cny": 0.0,
            "checkpointer_under_test": "langgraph MemorySaver（生产 = AsyncPostgresSaver；"
            "本件只需要「同一 thread 跑过多轮」这一事实）",
            "why_contract_suite_misses_it": "tests/contract/** 全部 build_graph() ⇒ checkpointer=None",
        },
        "node_terminal_guard_census": _node_terminal_guard_census(),
        "residue": _residue_across_turns(),
        "terminal_kind_matrix": _terminal_kind_matrix(),
        "fix_shape_reset_at_entry": _fix_shape_reset_at_entry(),
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
