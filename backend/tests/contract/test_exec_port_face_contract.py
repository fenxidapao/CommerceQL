"""U-122 的两条机械判据（写由 W4 / 审由 W0 —— 架构 v1.6.5 §22.3 裁定② + §22.5 判据④）。

**判据②**（端口成员集，防"回退成旧端口面"）钉 `SqlExecutorPort` 三件事：

1. `fetch` 的参数名 == `app.exec.seam.FETCH_CALL_FACE`（含 `effective_limit`）；
2. `explain` **在端口上**，参数名 == `EXPLAIN_CALL_FACE`（U-63：gate3 的 EXPLAIN 只能走它）；
3. `effective_limit` **无默认值** —— 给默认值 = 允许调用方静默漏传 = §8.6 `truncated`
   口径静默失真，方向 fail-open（W0 `aa494f6` 的裁定，架构采纳）。

**判据④**（替身忠实性）用 `declared_call_face_mismatches` 检全链脚本件 `ScriptExecutor`，
并配一条反向对照证明该 helper 不是空转。

为什么必须是端口而不是替身：`nodes/_shared.deps_of() -> Any` ⇒ 类型层看不见这两个调用，
替身抄错签名也不会红（`rich_method` 只在**方法缺失**时 fail-fast）⇒ "回退成旧端口面"
以前是一次静默漂移。这两条断言把它变成当场失败。
"""

from __future__ import annotations

import inspect
from typing import Any

from app.core.contracts import SqlExecutorPort
from app.exec.seam import EXPLAIN_CALL_FACE, FETCH_CALL_FACE, declared_call_face_mismatches
from tests.contract._fullchain_deps import ScriptExecutor


def _param_names(method_name: str) -> tuple[str, ...]:
    """端口上该方法的参数名（去掉协议自身的 `self`）。"""
    method = getattr(SqlExecutorPort, method_name)
    return tuple(p for p in inspect.signature(method).parameters if p != "self")


def test_fetch_declared_face_equals_graph_call_face() -> None:
    assert _param_names("fetch") == FETCH_CALL_FACE


def test_explain_is_declared_on_the_port() -> None:
    assert _param_names("explain") == EXPLAIN_CALL_FACE


def test_effective_limit_is_required_no_default() -> None:
    param = inspect.signature(SqlExecutorPort.fetch).parameters["effective_limit"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_fullchain_script_executor_is_faithful() -> None:
    """U-122 判据④（替身忠实性）：全链脚本件的声明面必须与 seam 一致。

    `deps_of() -> Any` ⇒ 替身抄错签名**不会红**，只在真调到那一行才炸；
    `declared_call_face_mismatches` 把"抄错"从运行时故障变成立判据时当场红。
    """
    assert declared_call_face_mismatches(ScriptExecutor()) == ()


def test_call_face_helper_is_load_bearing() -> None:
    """反向对照：缺 `explain` 的替身必须被抓到（证明上一条不是空断言）。"""

    class _NoExplain:
        async def fetch(
            self,
            sql: str,
            params: Any,
            ctx: Any,
            *,
            max_rows: int,
            statement_timeout_ms: int,
            effective_limit: int | None,
        ) -> Any: ...

    assert "缺方法 explain" in declared_call_face_mismatches(_NoExplain())
