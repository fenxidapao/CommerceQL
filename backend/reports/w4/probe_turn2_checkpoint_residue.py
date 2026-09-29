"""W4 离线探针（**零额度、零外部依赖**）：同一 `thread_id` 的第 2 轮到底发生什么。

由来（2026-09-29）：W7 第二十轮在真实流量里抓到 `terminal(99) − 审计行(95) = 4`，
四条栈顶逐字相同 = `audit_supp.py:49 → _shared.py:165 terminal_update → state.py:480
assert_terminal_is_settable → ValueError`（`deploy/loadtest/r20_internal_attribution.txt`）。
它的触发面读法 = "**属主在自己会话上的第 2 轮**"。⇒ 本件把那条活体路径**离线固化**，
并回答三件它答不了的事：① 残留的到底是哪些通道 ② 是不是只有 `complete` 之后才坏
③ "入口复位"这条修法成不成立。

**第二十一轮追加**（回 W7 `r21_turn_index_attribution.txt` 表 2 的反例：4 条"上一轮 = `refuse`"
却落 **`failed` 行 + INTERNAL**，与"静默复用"不同形）⇒ 矩阵加两档（本轮也拒 / 上一轮的 refuse
由 `normalize` 而非 `plan` 写），并把 W7 那两个**客户端探测器同名同口径**在离线面一起算
（`terminal_without_any_stage` / `terminal_digest_same_as_turn1`，易变键集合与其
`_frame_digest` 一致）⇒ 两窗口读的是同一个信号，不是各造一套。

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

#: 与 W7 客户端探测器 `probe_session_owner_context._frame_digest` **同一组易变键**
#: —— 跨窗口比指纹必须同集合，否则两条读数不可比。
_VOLATILE_FRAME_KEYS = frozenset(
    {"task_id", "trace_id", "session_id", "elapsed_ms", "ts", "timestamp", "seq"}
)


class _DeltaSpy:
    """透明代理：只记录"每个节点返回的增量里有没有 `terminal`"，不改图也不改 runner。

    存在的理由 = 用读数区分两种坏法，而不是靠推路径：
    **无守卫节点写终态 → 抛 N-08（崩）** vs **出口节点跳过写终态 → 复用上一轮结论（不崩）**。
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.deltas: list[dict[str, Any]] = []

    async def astream(self, *args: Any, **kwargs: Any):
        async for chunk in self._inner.astream(*args, **kwargs):  # type: ignore[attr-defined]
            for node, update in dict(chunk).items():
                upd = update if isinstance(update, dict) else {}
                self.deltas.append(
                    {
                        "node": node,
                        "wrote_terminal": bool(upd.get("terminal")),
                        "keys": sorted(upd),
                    }
                )
            yield chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _frame_digest(payload: dict[str, Any]) -> str:
    """终止帧指纹（剥掉易变键后逐字比）—— 与 W7 的探测器同集合、同口径。"""
    stable = {k: v for k, v in payload.items() if k not in _VOLATILE_FRAME_KEYS}
    return json.dumps(stable, sort_keys=True, ensure_ascii=False)


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
    terminals = [(e, d) for e, d in frames if d.get("terminal") is True]
    payload = terminals[0][1] if terminals else {}
    return {
        "asked": question,
        "terminal": [[e, d.get("code")] for e, d in terminals],
        "terminal_payload_keys": sorted(payload),
        "terminal_digest": _frame_digest(payload) if payload else None,
        "stage_frames": sum(1 for e, _ in frames if e == "stage"),
        "events": [e for e, _ in frames],
        "audit_rows_this_turn": len(chain.audit.pre),
        "audit_outcomes": [r.get("outcome") for r in chain.audit.pre],
        #: 本轮进了几次"合并档理解"调用 ⇒ 与"崩在哪个节点"并排读，才能判
        #: "只烧 1 次调用"与"崩在 `audit_supp`"是否互斥（W7 第二十二轮 ③）。
        "understand_calls": chain.planner.understand_calls,
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


def _three_turn_chain() -> dict[str, Any]:
    """同一 thread 连跑三轮：`error` 残留 → 本轮自拒 → 绿灯。

    要判的事（回 W7 第二十二轮②）：**"上一条审计行的 outcome" 不是"残留终态事件"的代理**。
    出口节点带守卫（`refuse_out.py:58`/`error_out.py:80`）⇒ 守卫命中时**只补审计行、不写终态**
    ⇒ 落库的 `outcome` 跟着**残留事件**走，而残留事件本身**不变** ⇒ 两列可以脱钩。
    每轮跑完都从检查点把 `terminal.event` 读回来，让"落库结论"与"残留事件"并排可比。
    """
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id_of(_IDENTITY)}}

    def persisted_event() -> str:
        term: dict[str, Any] = dict(graph.get_state(config).values).get("terminal") or {}
        return str(term.get("event", "")) or "(空)"

    steps: list[dict[str, Any]] = []
    plan: list[tuple[str, Callable[[], Any]]] = [
        ("T1 gate1 拒（残留事件=error）", lambda: make_chain(sql="SELECT 1; SELECT 2")),
        ("T2 本轮自拒（plan blocked）", lambda: make_chain(plan_blocked_issues=("缺表",))),
        ("T3 绿灯", lambda: make_chain()),
    ]
    for i, (label, build) in enumerate(plan, start=1):
        chain = build()
        before = persisted_event()
        rec = _turn(graph, chain, tag=f"ch{i}", question=Q1)
        steps.append(
            {
                "label": label,
                "residual_event_before_turn": before,
                "terminal_frame": rec["terminal"],
                "audit_outcomes": rec["audit_outcomes"],
                "nodes_ran": rec["nodes_ran"],
                "residual_event_after_turn": persisted_event(),
            }
        )
    return {
        "steps": steps,
        "读法": "T2 的落库 outcome 与 T3 看到的残留事件若不同源 ⇒ `lag(outcome)` 不能当残留种类用",
    }


def _terminal_kind_matrix() -> dict[str, Any]:
    """五种"上一轮结论 × 本轮意图"的组合 —— 把 W7 的两个客户端探测器在离线面一起算出来。

    为什么要有第 4、5 档：W7 `r21` 表 2 抓到 4 条"上一轮 = refuse"却落 **`failed` 行 + INTERNAL**，
    与我的"上一轮 refuse ⇒ 静默复用"不同形 ⇒ 差异只可能来自**本轮自己是否也要写终态**、
    以及**上一轮的 refuse 是哪个节点写的**（守卫节点 vs 无守卫节点）。⇒ 各加一档。
    """
    from app.llm.errors import LlmRefused

    arms: dict[str, tuple[Callable[[], Any], Callable[[], Any]]] = {
        "after_complete__turn2_green": (lambda: make_chain(), lambda: make_chain()),
        "after_refuse_plan_blocked__turn2_green": (
            lambda: make_chain(plan_blocked_issues=("缺表",)),
            lambda: make_chain(),
        ),
        "after_refuse_plan_blocked__turn2_refuses_again": (
            lambda: make_chain(plan_blocked_issues=("缺表",)),
            lambda: make_chain(plan_blocked_issues=("缺表",)),
        ),
        "after_refuse_llm_no_template_hit__turn2_green": (
            lambda: make_chain(understand_error=LlmRefused("模板层无命中 → 拒答（不是故障）")),
            lambda: make_chain(),
        ),
        "after_gate1_reject__turn2_green": (
            lambda: make_chain(sql="SELECT 1; SELECT 2"),
            lambda: make_chain(),
        ),
    }
    out: dict[str, Any] = {}
    for name, (build_first, build_second) in arms.items():
        spy = _DeltaSpy(build_graph(checkpointer=MemorySaver()))
        spy.deltas.clear()
        t1 = _turn(spy, build_first(), tag=f"{name}-1", question=Q1)
        spy.deltas.clear()
        t2 = _turn(spy, build_second(), tag=f"{name}-2", question=Q2)
        same_digest = (
            t1["terminal_digest"] is not None
            and t1["terminal_digest"] == t2["terminal_digest"]
        )
        pending = [
            n for n in (spy.get_state({"configurable": {"thread_id": thread_id_of(_IDENTITY)}}).next or ())
        ]
        out[name] = {
            "turn1": t1,
            "turn2": t2,
            "turn2_pending_next_nodes": pending,
            "turn2_node_deltas": list(spy.deltas),
            # ↓ 与 W7 客户端探测器同名同口径（`probe_session_owner_context.py` 第 4 步）
            "detector_terminal_without_any_stage": bool(t2["terminal"]) and t2["stage_frames"] == 0,
            "detector_terminal_digest_same_as_turn1": same_digest,
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
        "three_turn_chain": _three_turn_chain(),
        "fix_shape_reset_at_entry": _fix_shape_reset_at_entry(),
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
