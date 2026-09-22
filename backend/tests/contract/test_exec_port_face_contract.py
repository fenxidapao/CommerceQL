"""U-122 判据②（防回退，写由 W4 / 审由 W0 —— 架构 v1.6.5 §22.3 裁定②）：
`SqlExecutorPort` 的**声明面**必须覆盖**图的真实调用面**。

钉的是端口成员集，三件事：

1. `fetch` 的参数名 == `app.exec.seam.FETCH_CALL_FACE`（含 `effective_limit`）；
2. `explain` **在端口上**，参数名 == `EXPLAIN_CALL_FACE`（U-63：gate3 的 EXPLAIN 只能走它）；
3. `effective_limit` **无默认值** —— 给默认值 = 允许调用方静默漏传 = §8.6 `truncated`
   口径静默失真，方向 fail-open（W0 `aa494f6` 的裁定，架构采纳）。

为什么必须是端口而不是替身：`nodes/_shared.deps_of() -> Any` ⇒ 类型层看不见这两个调用，
替身抄错签名也不会红（`rich_method` 只在**方法缺失**时 fail-fast）⇒ "回退成旧端口面"
以前是一次静默漂移。这条断言把它变成当场失败。
"""

from __future__ import annotations

import inspect

from app.core.contracts import SqlExecutorPort
from app.exec.seam import EXPLAIN_CALL_FACE, FETCH_CALL_FACE


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
