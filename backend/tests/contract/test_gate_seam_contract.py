"""接缝契约测试：`run_gate1/run_gate2` 与 `SemanticBundleRuntime` 的 allowlist 形状契约。

背景（reports/w6/probe_gate_allowlist_shape.py）：生产唯一调用
`app/graph/nodes/gate1_ast.py` 把 `deps.semantics.asset_allowlist(identity)` —— 真运行时
返回**扁平** `{物理名: {...}}` —— 直接喂 `run_gate1`。但 `run_gate1/run_gate2` 期待的是
**wrapper** 形状（含 `assets` / `default_predicates` 等键）。这条「形状接缝」没有契约，
两边各自实现，今天这条缝是断的：普通 SQL 过闸仍是 `passed=False`。

本契约锁住：**真运行时输出原样喂进闸门，普通 SQL 必须能过**。Test A 红 = 缝没修；
Test B（不一致形状必须被拒）做反向对照，证明测的是这条缝、不是测夹具。
"""

from __future__ import annotations

from pathlib import Path

from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.guard import run_gate1, run_gate2
from app.semantics.loader import load_bundle
from app.semantics.runtime import SemanticBundleRuntime

#: W2C 规范普通 SQL（默认谓词归一后普通查询）。
SQL = "SELECT pay_amount FROM v_order_paid"

#: backend/tests/contract/... → parents[0]=contract, parents[1]=tests,
#: parents[2]=backend, parents[3]=CommerceQL（仓库根）。
_BUNDLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "semantic"
    / "bundle_2026.09.14.1.yaml"
)


def _rt() -> SemanticBundleRuntime:
    """构建真运行时（沿用 reports/w6/probe_gate_allowlist_shape.py 的做法）。"""
    return SemanticBundleRuntime(load_bundle(str(_BUNDLE_PATH)))


def _ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="t",
        task_id="t",
        session_id="t",
        tenant_id="T_A",
        user_id="u",
        role=Role.ANALYST,
    )


def test_plain_sql_passes_through_gate_seam() -> None:
    """真运行时 allowlist 原样喂进闸门，普通 SQL 必须能过（今天应红 = 缝没修）。"""
    rt = _rt()
    allowlist = rt.asset_allowlist(_ctx())  # 真运行时输出，原样，不包装、不加键

    r1 = run_gate1(SQL, allowlist)
    assert r1.gate_result.passed is True

    r2 = run_gate2(SQL, _ctx(), rt)
    assert r2.gate_result.passed is True


def test_broken_shape_rejected() -> None:
    """不一致形状必须被拒（反向对照：证明测的是缝不是夹具）。"""
    rt = _rt()
    allowlist = rt.asset_allowlist(_ctx())
    # 删掉 SQL 引用的 mandatory 资产 → 不可能通过。
    broken = {k: v for k, v in allowlist.items() if k != "v_order_paid"}

    r1 = run_gate1(SQL, broken)
    assert r1.gate_result.passed is False
