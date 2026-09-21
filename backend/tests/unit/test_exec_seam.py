"""exec 入口形态（`app/exec/seam.py`）的钉子 —— **这条声明有没有分离力**。

归属窗口：W2D（`tests/unit/test_exec_offline.py` 同域）。

--------------------------------------------------------------------------
为什么这几条必须存在（它们是"声明层"的**正向对照**）
--------------------------------------------------------------------------
`SqlExecutorPort` 只声明 `fetch`（两个关键字、无 `explain`），而图真的在传
`effective_limit` 与 `explain`（见 `seam.py` 模块 docstring）。若只加一个 Protocol 而**不**
证明它会拒绝"端口面替身"，那这条声明与不写没有区别 —— 所以每条都配一个**必须为假/必须点名**
的反向断言：

| 用例 | 断言的是 |
|---|---|
| `test_pg_executor_satisfies_seam` | 真实现对齐（正向） |
| `test_port_face_double_is_rejected` | **分离力**：只实现端口那两下 ⇒ `isinstance` 必须为假，且 `mismatches` 点名 `effective_limit` 与 `explain` |
| `test_extra_required_param_is_flagged` | 反方向的分离力：多出无默认值的参数也要被抓 |
| `test_contract_harness_double_already_exceeds_port` | **为什么需要这条声明**：合同夹具里的替身**本来就已经越过端口**（它当年必须抄实现类） |
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from app.core.config import Settings
from app.core.contracts import IdentityContext, MaskOutcome, ResultSet
from app.core.enums import Role
from app.exec import (
    EXPLAIN_CALL_FACE,
    FETCH_CALL_FACE,
    ExecutorSeam,
    PgSqlExecutor,
    declared_call_face_mismatches,
)

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
    """**只**实现 `SqlExecutorPort` 声明的那一面：`fetch` 两关键字、无 `explain`。

    这正是"照端口抄替身"会写出来的东西 —— 也是 `seam.py` 存在的理由：
    它在**运行期**（`execute` 传 `effective_limit` / `gate3_cost` 取 `explain`）才会炸，
    而 `isinstance(x, SqlExecutorPort)` 对它**为真**。
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


def test_declared_faces_cover_port_superset() -> None:
    """声明面是端口面的**超集**，且多出来的正是那两处（不是随手写宽）。"""
    assert "effective_limit" in FETCH_CALL_FACE
    assert "explain" not in FETCH_CALL_FACE
    assert EXPLAIN_CALL_FACE == ("sql", "params", "ctx", "statement_timeout_ms")


# ============================================================================
# 分离力：端口面替身必须被拒
# ============================================================================


def test_port_face_double_is_rejected() -> None:
    """⚠️ 这条就是 `seam.py` 的价值所在 —— 它今天必须是**假**。

    若哪天有人把 `ExecutorSeam` 改回 `SqlExecutorPort` 的形状（去掉 `explain`
    或 `effective_limit`），本条会变绿 ⇒ 说明这一刀又钝了。
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
# 为什么需要这条声明：合同夹具里的替身**本来就已经越过端口**
# ============================================================================


def test_contract_harness_double_already_exceeds_port() -> None:
    """`tests/contract/_fullchain_deps.py::ScriptExecutor` 满足 `ExecutorSeam`。

    意义：契约测试要跑到 gate3/execute，**当年就必须**实现 `explain` 与
    `effective_limit` —— 也就是说"图需要的面 > 端口声明的面"这件事，
    早就在夹具里以**手抄**的形式存在了，只是没有任何一层把它写下来。
    """
    from tests.contract._fullchain_deps import ScriptExecutor

    ex = ScriptExecutor()
    assert isinstance(ex, ExecutorSeam)
    assert declared_call_face_mismatches(ex) == ()
