"""架构自证探针（只读、零 LLM、零 DB、不落盘）：gate1 的 `rule_id` 会不会变成**列存在性 oracle**。

W7 @10:30（`reports/w7/scratch_gate2_face_probe.py` 档 4）与 W2C 独立到达同一结论：
`U-121` 落地后，若 gate1 的列解析面**退成"顶全列"（`columns <- all_columns`）**，
则「deny 列」与「根本不存在的列」会给出**不同** `rule_id` ⇒ 未授权方可据此判列在否（N-07 相邻面）。

本探针跑两个世界，只比 `rule_id`：
  A = 现状（`guard_allowlist()` 的 `columns` = 可见面，已裁 deny 列）
  B = 退步态（同一份 wrapper，把 `columns` 顶成 `all_columns`；仅进程内构造，不改任何源码）

跑法：cd CommerceQL/backend && ../.venv/Scripts/python.exe reports/arch/probe_gate1_column_oracle.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.guard import run_gate1
from app.semantics.loader import load_bundle
from app.semantics.runtime import SemanticBundleRuntime

BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
MAX_ROWS = 1000
DENY_SQL = "SELECT receiver_phone FROM v_order_paid"
GHOST_SQL = "SELECT zzz_not_a_real_column FROM v_order_paid"


def ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="t",
        task_id="t",
        session_id="t",
        tenant_id="T_A",
        user_id="u",
        role=Role.ANALYST,
    )


def rule_of(allowlist: object, sql: str) -> str:
    rep = run_gate1(sql, allowlist)  # type: ignore[arg-type]
    gr = rep.gate_result
    return f"{gr.rule_id}（passed={gr.passed}）"


def main() -> int:
    rt = SemanticBundleRuntime(load_bundle(str(BUNDLE)))
    c = ctx()
    vis = rt.guard_allowlist(c, max_rows=MAX_ROWS)

    top = dict(vis)
    top["assets"] = {
        k: {**v, "columns": v.get("all_columns") or v["columns"]} for k, v in vis["assets"].items()
    }

    print("=" * 76)
    print("列面自检：可见面 vs 结构面的差集（= deny 列）")
    for phys, ent in sorted(vis["assets"].items()):
        diff = sorted(set(ent.get("all_columns") or {}) - set(ent["columns"]))
        if diff:
            print(
                f"  {phys}: 可见 {len(ent['columns'])} 列 / 结构 {len(ent.get('all_columns') or {})} 列 ⇒ deny 面 = {diff}"
            )
    print(f"  deny_columns（逻辑名.列）= {sorted(vis['deny_columns'])[:6]} …")

    print("=" * 76)
    print("A｜现状：gate1 吃**可见面** `columns`")
    a1, a2 = rule_of(vis, DENY_SQL), rule_of(vis, GHOST_SQL)
    print(f"  deny 列   {DENY_SQL.split()[1]:<26} -> {a1}")
    print(f"  不存在的列 {GHOST_SQL.split()[1]:<25} -> {a2}")
    print("B｜退步态：把 `columns` 顶成 `all_columns`（进程内构造，未改源码）")
    b1, b2 = rule_of(top, DENY_SQL), rule_of(top, GHOST_SQL)
    print(f"  deny 列   {DENY_SQL.split()[1]:<26} -> {b1}")
    print(f"  不存在的列 {GHOST_SQL.split()[1]:<25} -> {b2}")

    print("=" * 76)
    same_a = a1.split("（")[0] == a2.split("（")[0]
    same_b = b1.split("（")[0] == b2.split("（")[0]
    print(f"  A 面 rule_id 相同（不可判存在性）= {same_a}")
    print(f"  B 面 rule_id 相同（不可判存在性）= {same_b}")
    if same_a and not same_b:
        print("  ⇒ W7 的结论成立：顶全列会把 gate1 变成列存在性 oracle（N-07 相邻面）。")
    else:
        print("  ⇒ 与 W7 的结论不一致，按盘上读数登记差异，不改判据方向。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
