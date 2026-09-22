"""exec 入口形态（`app/exec/seam.py`）的钉子 —— **这条声明有没有分离力**。

归属窗口：W2D（`tests/unit/test_exec_offline.py` 同域）。

--------------------------------------------------------------------------
为什么这几条必须存在（它们是"声明层"的**正向对照**）
--------------------------------------------------------------------------
历史前提（U-122 立号时）：`SqlExecutorPort` 只声明 `fetch` 两关键字，图却在
`effective_limit` 与 `explain` 两处越过端口。W0 `aa494f6` 已把端口面补齐
（`effective_limit` 必填 + `explain` 上端口），`seam.py` 随之收敛为
**再导出 + 检查器**（`ExplainPlan` 再导出、`ExecutorSeam` = 端口别名）。
本文件钉的是收敛后的不变式：

| 用例 | 断言的是 |
|---|---|
| `test_single_truth_identity` | **单一真相**：`app.exec.ExplainPlan` 就是 contracts 那个对象、`ExecutorSeam` 就是端口别名（杀第二真相） |
| `test_pg_executor_satisfies_seam` | 真实现对齐（正向） |
| `test_faces_match_port_and_pin_content` | 两个 face 常量与端口签名逐字相等 + 内容钉死（W4 判据② 的独立见证面） |
| `test_port_face_double_is_rejected` | **分离力**：旧端口面替身（无 `effective_limit`/`explain`）⇒ `isinstance` 必须为假，且 `mismatches` 点名两处 |
| `test_extra_required_param_is_flagged` | 反方向的分离力：多出无默认值的参数也要被抓 |
| `test_fullchain_script_executor_satisfies_port` | 全链夹具 `ScriptExecutor` 与端口/检查器全对齐（U-122 判据④ 的单元侧） |
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from typing import Any

from app.core.config import Settings
from app.core.contracts import IdentityContext, MaskOutcome, ResultSet, SqlExecutorPort
from app.core.enums import Role
from app.exec import (
    EXPLAIN_CALL_FACE,
    FETCH_CALL_FACE,
    ExecutorSeam,
    ExplainPlan,
    PgSqlExecutor,
    declared_call_face_mismatches,
)
from app.exec.seam import ExplainPlan as SeamExplainPlan

# ============================================================================
# 单一真相
# ============================================================================


def test_single_truth_identity() -> None:
    """`seam.py` 不得另立第二份定义（contracts.py:515-517 明文）。

    `ExplainPlan` 必须是 `app.core.contracts` 的**同一个对象**（再导出，不是
    重新赋值）；`ExecutorSeam` 必须就是 `SqlExecutorPort` 的别名。哪天有人把
    本地定义加回来，这条立刻红。
    """
    import app.core.contracts as contracts

    assert SeamExplainPlan is contracts.ExplainPlan
    assert ExplainPlan is contracts.ExplainPlan
    assert ExecutorSeam is SqlExecutorPort
    assert ExplainPlan == list[dict[str, Any]] | None


# ============================================================================
# 夹具
# ============================================================================


class _StubMask:
    def apply(self, rows, policy) -> MaskOutcome:
        return MaskOutcome(rows=tuple(tuple(r) for r in rows), hit_columns=())


def _settings() -> Settings:
    return Settings(
        DATABASE_URL=os.environ["DATABASE_URL"],
        ANALYTICS_DB_URL=os.environ["ANALYTICS_DB_URL"],
        DEEPSEEK_API_KEY="sk-placeholder",
    )


def _ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="tr",
        task_id="tk",
        session_id="s",
        tenant_id="t_001",
        user_id="u",
        role=Role.ANALYST,
    )


class _PortFaceDouble:
    """**旧**端口面的替身：`fetch` 两关键字、无 `effective_limit`、无 `explain`。

    这就是"照 U-122 之前的端口抄替身"会写出来的东西。端口面补齐后，
    `runtime_checkable` 的 `isinstance(x, SqlExecutorPort)` 会因缺 `explain`
    属性而**为假**；`declared_call_face_mismatches` 再把两处缺口**点名**。
    """

    async def fetch(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        statement_timeout_ms: int,
    ) -> ResultSet:  # pragma: no cover - 不会被调到
        raise AssertionError("端口面替身不该被真正调用")


class _SloppyDouble:
    """对齐了 `fetch`/`explain`，但 `fetch` 多出一个**无默认值**的参数。"""

    async def fetch(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        statement_timeout_ms: int,
        effective_limit: int | None = None,
        probe_budget_ms: int,
    ) -> ResultSet:  # pragma: no cover
        raise AssertionError("不该被真正调用")

    async def explain(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        statement_timeout_ms: int,
    ) -> Any:  # pragma: no cover
        raise AssertionError("不该被真正调用")


# ============================================================================
# 正向：真实现对齐
# ============================================================================


def test_pg_executor_satisfies_seam() -> None:
    """`PgSqlExecutor` 是生产注入的那个实现（`app/api/deps.py`）⇒ 必须对齐。"""
    ex = PgSqlExecutor(analytics_engine=None, mask=_StubMask(), settings=_settings())
    assert isinstance(ex, ExecutorSeam)
    assert declared_call_face_mismatches(ex) == ()


def test_faces_match_port_and_pin_content() -> None:
    """face 常量与端口签名**逐字相等**（W4 判据② 的等式两边），且内容钉死。

    ⚠️ 常量刻意手写、不从端口推导（见 `seam.py` 模块 docstring 第二节）——
    推导会让 W4 的等式断言变恒真、防回退失效；本条的**内容钉死**部分
    （精确元组）就是手写面自己的锚。
    """
    for method_name, face in (("fetch", FETCH_CALL_FACE), ("explain", EXPLAIN_CALL_FACE)):
        method = getattr(SqlExecutorPort, method_name)
        port_params = tuple(p for p in inspect.signature(method).parameters if p != "self")
        assert face == port_params

    assert "effective_limit" in FETCH_CALL_FACE
    assert "explain" not in FETCH_CALL_FACE
    assert EXPLAIN_CALL_FACE == ("sql", "params", "ctx", "statement_timeout_ms")


# ============================================================================
# 分离力：旧端口面替身必须被拒
# ============================================================================


def test_port_face_double_is_rejected() -> None:
    """⚠️ 这条就是分离力所在 —— 它今天必须是**假**。

    `runtime_checkable` 的 `isinstance` 只查属性存在：替身缺 `explain` 属性 ⇒
    对端口（= `ExecutorSeam` 别名）必为假；签名级缺口由 `mismatches` 点名。
    若哪天端口面被砍回旧形状且替身照抄，本条的 isinstance 断言会变绿 ⇒
    说明这一刀又钝了（届时 W4 判据② 也会红 —— 双保险）。
    """
    fake = _PortFaceDouble()
    assert not isinstance(fake, ExecutorSeam)

    problems = declared_call_face_mismatches(fake)
    assert any("effective_limit" in p for p in problems), problems
    assert any("explain" in p for p in problems), problems


def test_extra_required_param_is_flagged() -> None:
    """反方向：多出一个**无默认值**的参数 ⇒ 调用方不传就 `TypeError`，必须点名。"""
    problems = declared_call_face_mismatches(_SloppyDouble())
    assert any("probe_budget_ms" in p for p in problems), problems
    # 其余两面是对齐的 ⇒ 不得误报
    assert not any("effective_limit" in p for p in problems), problems


# ============================================================================
# 全链夹具忠实性（U-122 判据④ 的单元侧）
# ============================================================================


def test_fullchain_script_executor_satisfies_port() -> None:
    """`tests/contract/_fullchain_deps.py::ScriptExecutor` 与端口/检查器全对齐。

    历史注：端口面补齐前，这个夹具"本来就越过端口"（当年必须手抄实现类才有
    `explain`/`effective_limit`）；`aa494f6` 之后端口**追认**了图的真实调用面，
    夹具从"越过端口"变成"恰好忠实"。契约侧的正式判据在
    `tests/contract/test_exec_port_face_contract.py::test_fullchain_script_executor_is_faithful`。
    """
    from tests.contract._fullchain_deps import ScriptExecutor

    ex = ScriptExecutor()
    assert isinstance(ex, ExecutorSeam)
    assert declared_call_face_mismatches(ex) == ()
