"""评测**评分器自身**的两条守卫（2026-10-03 补）。

为什么这一层必须有测试：真打批次 `n_equivalent=0`（124 条 execute 全灭）持续存在了若干轮，
而它同时被两处**测量器件**缺陷解释 —— 两处都不在任何测试的覆盖面里：

1. `run_in_sandbox` 不做 `%(name)s → :name` 方言桥 ⇒ 凡带绑定参数的被测 SQL 在沙箱里
   恒 `OperationalError: near "%"`，预测侧永远是空表（出站契约本身就要求绑定参数）；
2. 预测侧的表读的是 state 的 `result_rows`，而 07 §5.2.1 把 `result_rows` 定为**体积字段**
   （`execute` 只 `context.hold_rows`，行不进 state）⇒ 预测侧恒 0 行。

"评分器没有覆盖率" 这件事本身就是本轮最大的方法论收获：**判据装置坏的时候，
所有读数都会安静地变成 0，而离线门禁全绿。**
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import _bootstrap

REPO = pathlib.Path(_bootstrap.ROOT)


@pytest.fixture(scope="module")
def harness():
    import harness as eval_harness

    return eval_harness.Harness(cassette_path=None, live=False)


def test_sandbox_accepts_psycopg_named_params(harness) -> None:
    """带 `%(name)s` 的被测 SQL 必须能在沙箱跑出**非空**表（方言桥在位）。"""
    import runner as eval_runner

    out = eval_runner.run_in_sandbox(
        "SELECT SUM(pay_amount) AS gmv FROM v_order_paid WHERE pay_time >= %(start)s",
        {"start": "2026-06-01"},
        tenant="T_A",
        views=True,
        db_path=_bootstrap.SANDBOX_DB,
        tenant_scoped_physicals=harness.tenant_scoped_physicals,
    )
    assert out["error"] is None, out["error"]
    assert out["rows"] == 1
    assert out["table"].rows[0][0] is not None


def test_sandbox_tenant_boundary_is_enforced(harness) -> None:
    """方言桥不得顺手放开租户边界：TEMP VIEW 只给本租户的行。"""
    import runner as eval_runner

    def tenant_ids(tenant: str) -> set[str]:
        out = eval_runner.run_in_sandbox(
            "SELECT DISTINCT tenant_id FROM v_order_paid",
            None,
            tenant=tenant,
            views=True,
            db_path=_bootstrap.SANDBOX_DB,
            tenant_scoped_physicals=harness.tenant_scoped_physicals,
        )
        assert out["error"] is None
        return {str(row[0]) for row in out["table"].rows}

    assert tenant_ids("T_A") == {"T_A"}
    assert tenant_ids("T_B") == {"T_B"}


def test_predicted_table_is_not_read_from_volumetric_state_field() -> None:
    """AST 尺：`score_case` 的预测侧必须走沙箱复算，不得回到 `run.result_rows`。

    与 `tests/eval/test_harness_allowlist.py` 同族：形状尺比"我记得改过"可靠。
    体积字段 `result_rows` 在 state 里恒空 ⇒ 谁把它接回评分路径，EX 就会**静默**归 0。
    """
    tree = ast.parse((REPO / "eval" / "runner.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "score_case"
    )
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "result_rows" not in attrs, "预测侧又从 state 体积字段取行 ⇒ EX 会静默归 0"
    assert "result_columns" not in attrs
    calls = {
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "run_in_sandbox" in calls, "预测侧必须与金标同器同界（沙箱 + TEMP VIEW）复算"
