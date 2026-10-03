"""T-26：⑱ 形状守卫"三面尺"的接线断言（零 DB / 零 LLM / 零额度，纯文本）。

为什么这张单值得一个测试（不是给注释配个装饰）
--------------------------------------------------------------------------
`r23_thread_from_checkpoints.sql` 的 ⑱ 注记里，覆盖数在两轮之间从 **8** 变成 **11**，
两次都是**手工 `grep -c` 出来的整数写进散文**。整数不会跟着追加漂移，于是"引覆盖数"
在本仓库已经是第二次两跑矛盾。

T-26 的裁定是**把尺定义变成代码**（`deploy/loadtest/shape_guard_faces.py`），并规定
"引覆盖数必须点名是哪一面"。本文件钉住三件事，缺一件就退回原状：
1. 三面都**数得出**（非零）—— 尺子空转 = 没有尺；
2. 结构不变式无违反（写了排除式判据的文件必须同文件里有守卫定义位**和**消费位）——
   这正是 T-23 修掉的那一形，不能靠人记得；
3. **注释行不计入** —— 8 与 11 的差就在这根轴上。把它钉成断言，下一个数不一致的人
   会先看到"面不同"，而不是"有人数错了"。

⚠️ 本文件刻意**不断言具体数值**：数值会随追加漂（这正是本单的病因）。要数就现跑那件。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]  # .../CommerceQL
_COUNTER = _REPO / "deploy" / "loadtest" / "shape_guard_faces.py"


def _faces():
    """按**路径**加载计数件，而不是 `sys.path` + `import shape_guard_faces`。

    理由不是风格：`tests/contract/test_dependency_whitelist.py` 把 `import X` 一律当第三方依赖，
    而它的 `_SCAN_ROOTS` 不含 `deploy/` ⇒ 裸 import 会被判成"未声明的第三方包"。
    那条守卫本身是对的（`deploy/**` 确实游离在依赖纪律之外，已另记一笔），
    本测试不该靠给它开例外来通过 —— 按路径装载就不产生 import 语句。
    """
    assert _COUNTER.exists(), f"{_COUNTER} 缺失 —— 三面尺失去定义件"
    spec = importlib.util.spec_from_file_location("shape_guard_faces_under_test", _COUNTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_three_faces_are_countable() -> None:
    faces = _faces()
    counts = {k: 0 for k in ("F-pred", "F-guard", "F-consume")}
    for rel in faces.FILES:
        path = faces.REPO / rel
        assert path.exists(), f"{rel} 缺失 —— 三面尺失去承载件"
        one = faces._count(path)
        for key in counts:
            counts[key] += one[key]
    assert counts["F-pred"] > 0, "F-pred（判据谓词面）为 0 ⇒ 排除式谓词改名了，尺失效"
    assert counts["F-guard"] > 0, "F-guard（守卫面）为 0 ⇒ ⑱ 守卫定义位没了，覆盖面无从谈起"
    assert counts["F-consume"] > 0, "F-consume（消费位面）为 0 ⇒ 守卫退回旁注（T-23 复发）"


def test_no_file_uses_the_predicate_without_consuming_the_guard() -> None:
    """★ 三面齐全性 = 本单的可执行部分（`violations()` 为空）。"""
    assert _faces().violations() == [], "有判据无守卫/有守卫不消费 —— 守卫没接成否决位，见 violations()"


def test_comment_lines_are_not_counted(tmp_path: Path) -> None:
    """8 vs 11 的归因断言：同一条谓词写在 `--` 注释里**不得**计入 F-pred。

    没有这条，尺子的"面"就还是靠使用者自觉 —— 而本仓库已经两次在这里翻车。
    """
    faces = _faces()
    sample = tmp_path / "s.sql"
    sample.write_text(
        "-- 注记里复述一次 " + faces.PRED + " 不算判据\n"
        "#  python 注释里同样不算 " + faces.PRED + "\n"
        f"select count(*) filter (where {faces.PRED} and task_path ~ '__start__') = 0) {faces.GUARD}\n"
        "case when not s.shape_ok then '不可判'\n",
        encoding="utf-8",
    )
    got = faces._count(sample)
    assert got["F-pred"] == 1, f"注释行被计入了：{got}"
    assert got["F-guard"] == 1
    assert got["F-consume"] == 1
