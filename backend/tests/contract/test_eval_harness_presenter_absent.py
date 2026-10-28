"""评测链路“不出图”上锁：`eval/harness.py` 的 `GraphDeps(...)` 必须传 `presenter=None`。

**为什么这是契约而不是风格**：评测的判定对象是"这一轮答得对不对"（SQL / 结果集 / 终态），
166 题的基线与 `presenter` 是否存在无关；一旦评测也出图，任何 presenter 侧的行为变化
都会悄悄改掉评测读数，而两套读数混在一张表里就无法归因。

🔒 本测试**只读源码**（AST），不 import `eval/harness.py` —— 它依赖沙箱与评测专用装配，
import 会拖进真实文件路径。`presenter` 关键字若被删掉或改成非 `None`，此测试立即红。
"""

from __future__ import annotations

import ast
from pathlib import Path


def _harness_path() -> Path:
    return Path(__file__).resolve().parents[3] / "eval" / "harness.py"


def _is_graphdeps(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "GraphDeps"
    if isinstance(func, ast.Attribute):
        return func.attr == "GraphDeps"
    return False


def test_eval_harness_constructs_graphdeps_with_presenter_none() -> None:
    path = _harness_path()
    assert path.is_file(), f"评测装配根不存在：{path}"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_graphdeps(node.func)
    ]
    assert len(calls) == 1, (
        "eval/harness.py 应恰好有一处 GraphDeps(...) 装配；出现第二处意味着"
        "评测可能绕过了 presenter=None 这条锁"
    )
    keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    assert "presenter" in keywords, "GraphDeps(...) 必须显式写 presenter=None"
    value = keywords["presenter"]
    assert isinstance(value, ast.Constant) and value.value is None, (
        "评测链路的 presenter 必须保持 None（生产出图、评测不出图是既定形态）"
    )


def test_eval_harness_does_not_import_chart_presenter() -> None:
    tree = ast.parse(_harness_path().read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module != "app.present.presenter", "评测链路不得引入 ChartPresenter"
        if isinstance(node, ast.Import):
            assert all(alias.name != "app.present.presenter" for alias in node.names)
