"""接缝契约测试：`run_gate1` 与 `SemanticBundleRuntime` 的**闸门判据形状**契约（U-119）。

判据已由架构 v1.6.5 §22.1 改写（`U-121` 定案"两个投影、两种形状"之后）：

- **Test A**：真运行时的 `guard_allowlist(ctx, max_rows=…)`（闸门唯一形状，7 键 wrapper）
  原样喂 `run_gate1` ⇒ 普通 SQL 必须 `passed=True`。这条**必须绿**，红 = 生产取用点/实现漂了。
- **Test B（反向对照）**：把**扁平面** `asset_allowlist(ctx)`（planner / binding 的可见面）
  喂闸门 ⇒ 必须被 `R05` 拒。改写前它是"缺陷的证据"，改写后它是"fail-closed 行为正确的证据"
  —— 扁平面按设计**不该**喂闸门（`app/core/contracts.py` 的 `SemanticBundlePort` docstring 明写）。

⚠️ **gate2 侧走的是它自己那次取数**：`run_gate2(sql, ctx, bundle)` 在 `guard/policy_gate.py` 内部
调 `bundle.guard_allowlist(ctx)`（`c76f701`，U-121 第三步），与 gate1 **各取一次是刻意的**
（见 `app/graph/nodes/gate1_ast.py` docstring §二）⇒ 本文件第三条断言测的就是那条独立缝。
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

#: 请求级行数上限：`api/dto/query.AskOptions.max_rows` 的默认值（生产由调用方给出）。
_MAX_ROWS = 5000

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
    """Test A：真运行时的闸门形状原样喂 `run_gate1`，普通 SQL 必须过（U-121 落地后应绿）。"""
    rt = _rt()
    allowlist = rt.guard_allowlist(_ctx(), max_rows=_MAX_ROWS)  # 原样，不包装、不加键

    r1 = run_gate1(SQL, allowlist)
    assert r1.gate_result.passed is True, r1.gate_result


def test_plain_sql_passes_through_gate2_seam() -> None:
    """Test C = `U-119` **判据④**：gate2 自己那次取数也必须拿到判据（与 Test A 对称）。

    `run_gate2` 收的是**端口对象**，判据在它内部取 ⇒ 这条测的是 `policy_gate.py` 那条独立缝，
    Test A 绿不代表它绿（两条分开喂）。
    ⚠️ **写法约束（`reports/w4/RELAY.md` §十四 的两种红法）**：只允许 `assert ... passed is True`
    直取，**不** `try/except`、**不**只断言拒绝码 —— 半落地态（换了取用点没换 `:154`/`:158`
    读取面）会以未捕获 `ContractViolationError` 暴露，那个 error 形态本身就是归因；
    把它折成"被拒"就等于把"只换一半"伪装成"没换"。
    """
    r2 = run_gate2(SQL, _ctx(), _rt())
    assert r2.gate_result.passed is True, r2.gate_result


def test_flat_projection_is_rejected_by_gate1() -> None:
    """Test B（反向对照）：扁平面喂闸门必被拒 —— 证明测的是这条缝，不是夹具。"""
    rt = _rt()
    flat = rt.asset_allowlist(_ctx())  # planner/binding 的可见面，不该进闸门

    r1 = run_gate1(SQL, flat)
    assert r1.gate_result.passed is False
