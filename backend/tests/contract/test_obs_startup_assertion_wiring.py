"""U-105 的**接线面**契约：启动断言三态镜像成 `startup_assertion_state` 这件事真的接上了。

归属窗口：W7（`app/obs/**`、这条契约）。

## 为什么单独一个文件、而且用 AST 而不是跑 lifespan

本仓库对"测试里跑 lifespan"有一条**已登记的取舍**（`tests/contract/test_api_endpoints_contract.py:25`）：
`TestClient(app)` 刻意**不用 `with`** —— lifespan 里有真 I/O（连库、开池、跑启动断言）。
所以"起一次应用、再看 `/metrics` 有没有这 12 行"这条最直接的验法**在本仓库不成立**：
加了它，单测套件就从今天起依赖真 PG/Redis 在跑（并把每次 CI 都变成一次启动演练）。

⇒ 这里改验**接线的形状**，并且专门钉三件真会烂掉的事：
① 绑定动作真的发生，且**取值来自 `app/repo` 的源符号**（不是别处的字面量）；
② 逐条 `observe`（漏一条 = 那条断言的状态永远不上看板，而现象是"少一行"，不是报错）；
③ **`app/obs/metrics.py` 里没有任何手抄的断言名字面量** —— 这条是 U-105"禁手抄"的机器化：
   抄一份的后果是 W1B 改/加断言名时 CI 全绿而第 5 条状态永远隐形，只有这种检查能提前拦住。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.repo.startup_assertions import ASSERTION_NAMES

_MAIN_SOURCE = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
_METRICS_SOURCE = (Path(__file__).resolve().parents[2] / "app" / "obs" / "metrics.py").read_text(
    encoding="utf-8"
)


def _calls(tree: ast.AST, dotted: str) -> list[ast.Call]:
    """按"属性链尾部匹配"找调用点（`metrics.bind_x(...)` 与 `bind_x(...)` 都算）。"""
    suffix = dotted.split(".")[-1]
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name == suffix:
                found.append(node)
    return found


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _string_literals(tree: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_lifespan_binds_domains_from_the_repo_source_symbols() -> None:
    """① 绑定发生在 lifespan，且参数直指 `ASSERTION_NAMES` / `AssertionStatus`。"""
    tree = ast.parse(_MAIN_SOURCE)
    binds = _calls(tree, "bind_startup_assertion_domains")
    assert binds, "app/main.py 里没有 bind_startup_assertion_domains 调用 ⇒ 封闭集永远未绑定，" \
                   "而 `observe_startup_assertion` 会当场抛（这是 fail-fast 的设计，但接线漏了就永远红）"
    referenced = _names_in(binds[0])
    assert {"ASSERTION_NAMES", "AssertionStatus"} <= referenced, (
        f"绑定必须从源符号导出，实际引用了 {sorted(referenced)}"
    )


def test_lifespan_observes_every_returned_outcome() -> None:
    """② 逐条 observe：必须在 `for ... in outcomes` 里，而不是只记 passed。"""
    tree = ast.parse(_MAIN_SOURCE)
    observes = _calls(tree, "observe_startup_assertion")
    assert observes, "没有 observe_startup_assertion 调用 ⇒ 指标注册了但没人写（假仪表）"
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
    covering = [
        loop
        for loop in loops
        if any(obs in ast.walk(loop) for obs in observes)
        and "outcomes" in {part for part in _names_in(loop.iter)}
    ]
    assert covering, "observe_startup_assertion 必须遍历 enforce_startup_assertions 的**全部** outcomes"


def test_metrics_module_contains_no_hand_copied_assertion_names() -> None:
    """③ ★ U-105 的"禁手抄"：`app/obs/metrics.py` 里不得出现任何断言名字面量。

    这是本文件最要紧的一条。为什么值得用 AST 挡：把 4 个名字抄进 `domains=(...)` 是**能通过所有
    现有测试**的写法，而且看起来比"运行期注入"更简单。它坏在时间差上 —— 第 5 条断言加进来那天，
    抄的那份不会同步，新断言的状态既不进看板也不报错。
    """
    literals = _string_literals(ast.parse(_METRICS_SOURCE))
    leaked = sorted(set(ASSERTION_NAMES) & literals)
    assert not leaked, (
        f"app/obs/metrics.py 出现了手抄的断言名字面量 {leaked} ⇒ 改回由 lifespan 注入"
        "（`bind_startup_assertion_domains`），否则源枚举一改就静默漂移"
    )


def test_assertion_names_are_still_within_the_declared_cardinality_cap() -> None:
    """源枚举与上界的一致性：`BOUNDED_ALLOWED_LABELS["assertion"]` 必须容得下全部断言名。

    加第 5 条断言时这条会红 —— 那是**故意**的：逼着改动者显式承认"封闭集扩大了"，
    并按 U-105 走一次裁定（顺带把系列上界 12→15 的三处文案一起改）。

    ⚠️ 光改这里**不够**：上界的 fail-fast 落在 lifespan 里 ⇒ 只改测试不改 BOUNDED_ALLOWED_LABELS
    会让进程启动不了，而不是 CI 红一条。U-111 的第 5 条断言已提前入账（上界已给到 5）。
    """
    from app.obs import metrics

    assert len(ASSERTION_NAMES) <= metrics.BOUNDED_ALLOWED_LABELS["assertion"], (
        f"ASSERTION_NAMES 有 {len(ASSERTION_NAMES)} 条，超过上界 "
        f"{metrics.BOUNDED_ALLOWED_LABELS['assertion']} ⇒ 绑定会 fail-fast"
    )
