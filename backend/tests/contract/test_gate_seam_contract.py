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

**判据④b（Test D + Test E，07 v1.7.2 拆 ④a/④b 的欠下那半）**：④a = Test C（正向对称）已由 W4
`e0ce440` 落；④b = 「deny 列经**真端口**喂 `run_gate2` ⇒ 必 `G2-DENY`」入 CI，且**读取面**这条缝
本身要有反向对照（原本只在 W2C 的报告件探针 `reports/w2c/_probe_u121_faces.py` 里跑过，
**报告件不是门禁**）。

- **Test D**：`receiver_phone`（deny 列）三形态（裸 / 表限定 / 别名）经真 `SemanticBundleRuntime`
  喂 `run_gate2` ⇒ 必须 `passed=False` 且 `rule_id == "G2-DENY"`。
- **Test E（反向对照）**：把 ④ 的读取面从结构面（`_struct_view`）退回**可见面**，
  **裸写**形态必须不再被 `G2-DENY` 拦 ⇒ 证明 Test D 钉的是读取面这条缝，而不是「反正都会被拒」。
  ⚠️ **只有裸写会翻转**（实测）：限定/别名形态靠 `_resolve_column` 的表别名映射仍能归属到资产，
  即使列不在可见 `columns` 里也照拒 ⇒ 反向对照**只对裸写**成立。
  而裸名恰好是**唯一能过闸门 R16 的形态** ⇒ 可见面下漏检的那一格，正是生产最常走的那一格。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.guard import policy_gate, run_gate1, run_gate2
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


#: deny 列（`receiver_phone`）的三种写法 —— 裸 / 表限定 / 别名。
_DENY_SQL_FORMS = {
    "裸写": "SELECT receiver_phone FROM v_order_paid",
    "表限定": "SELECT v_order_paid.receiver_phone FROM v_order_paid",
    "别名": "SELECT o.receiver_phone FROM v_order_paid AS o",
}


@pytest.mark.parametrize("form", sorted(_DENY_SQL_FORMS))
def test_deny_column_rejected_through_gate2_seam(form: str) -> None:
    """Test D = `U-119` **判据④b**：deny 列经真端口喂 `run_gate2` ⇒ 必 `G2-DENY`。

    与 Test C 的区别：Test C 只证明**干净 SQL 不被误拒**；这条证明 ④ 的**冗余复核仍然活着**
    —— 两者缺一，gate2 侧那道缝就只在"不错杀"这一半上有护栏（漏检 = fail-open，不会有任何红）。
    """
    r2 = run_gate2(_DENY_SQL_FORMS[form], _ctx(), _rt())
    assert r2.gate_result.passed is False, r2.gate_result
    assert r2.gate_result.rule_id == "G2-DENY", r2.gate_result


def test_gate2_deny_check_depends_on_structure_face(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test E（反向对照）：把 ④ 的读取面退回可见面 ⇒ **裸写**形态必须不再被 `G2-DENY` 拦。

    只有裸写会翻转（限定/别名靠 `_resolve_column` 的表别名映射仍能归属 ⇒ 仍拒）——
    所以反向对照只对裸写成立，这**不是**测试写漏。裸名是唯一能过闸门 R16 的形态，
    可见面下漏检的那一格正是生产最常走的那一格（07 §7.4 的"静默漏检"形态）。
    """

    def _visible_face(allowlist: dict[str, Any]) -> dict[str, Any]:
        return allowlist  # 等价于"④ 直接吃可见 columns"

    monkeypatch.setattr(policy_gate, "_struct_view", _visible_face)
    r2 = run_gate2(_DENY_SQL_FORMS["裸写"], _ctx(), _rt())
    assert not (r2.gate_result.passed is False and r2.gate_result.rule_id == "G2-DENY"), (
        "可见面下裸写 deny 列竟然仍被 G2-DENY 拦 ⇒ 该断言不再能证明 ④ 读的是结构面"
    )
