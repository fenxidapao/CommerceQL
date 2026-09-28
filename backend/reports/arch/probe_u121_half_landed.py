"""架构自证探针（只读、零 LLM、零 DB、不改任何他人文件）：`U-121` 半落地态的**第三种红法**。

问题（W7 2026-09-22 上呈 / W4 `6da16db` A-B 两档）：若 W2C 只换 `policy_gate.py:105`
（`asset_allowlist` → `guard_allowlist`）而不同轮换 `:141` / `:148` 的**读取面**，
gate2 观测到的是"**恒拒**"还是"**未捕获异常**"？

做法 = **进程内** monkeypatch 一个"只换 105"的世界（把 `asset_allowlist` 指到
`guard_allowlist`），真调用 `run_gate2` ⇒ **不落盘、不改源码**，跑完即还原。

跑法：cd CommerceQL/backend && ../.venv/Scripts/python.exe reports/arch/probe_u121_half_landed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.guard import run_gate1, run_gate2
from app.semantics.loader import load_bundle
from app.semantics.runtime import SemanticBundleRuntime

BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
SQL = "SELECT pay_amount FROM v_order_paid"
MAX_ROWS = 1000


def ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="t",
        task_id="t",
        session_id="t",
        tenant_id="T_A",
        user_id="u",
        role=Role.ANALYST,
    )


def show(tag: str, fn) -> None:
    try:
        rep = fn()
        gr = rep.gate_result
        print(
            f"  {tag}: 返回 {gr.gate_no.name} passed={gr.passed} decision={gr.decision.name} rule={gr.rule_id} reason={gr.reason}"
        )
    except Exception as exc:
        print(f"  {tag}: 抛 {type(exc).__module__}.{type(exc).__name__} :: {str(exc)[:110]}")


def main() -> int:
    rt = SemanticBundleRuntime(load_bundle(str(BUNDLE)))
    c = ctx()
    print("=" * 78)
    print("档 1｜现状（105 仍是扁平面，W2C 未换）")
    print("=" * 78)
    show(
        "gate1（W4 已换 guard_allowlist）",
        lambda: run_gate1(SQL, rt.guard_allowlist(c, max_rows=MAX_ROWS)),
    )
    show("gate2（105 仍 asset_allowlist）", lambda: run_gate2(SQL, c, rt))

    print("=" * 78)
    print("档 2｜模拟「只换 105」：asset_allowlist 就地指向 guard_allowlist（进程内，不落盘）")
    print("=" * 78)
    orig = SemanticBundleRuntime.asset_allowlist
    SemanticBundleRuntime.asset_allowlist = lambda self, _c: self.guard_allowlist(
        _c, max_rows=MAX_ROWS
    )
    try:
        show("gate2（105 已换、:141/:148 未换）", lambda: run_gate2(SQL, c, rt))
        show(
            "gate1（同世界，回归对照）",
            lambda: run_gate1(SQL, rt.guard_allowlist(c, max_rows=MAX_ROWS)),
        )
    finally:
        SemanticBundleRuntime.asset_allowlist = orig  # type: ignore[method-assign]
        assert SemanticBundleRuntime.asset_allowlist is orig, "monkeypatch 未还原"
    print("=" * 78)
    print("档 3｜还原自检（必须与档 1 的 gate2 同形）")
    print("=" * 78)
    show("gate2（已还原）", lambda: run_gate2(SQL, c, rt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
