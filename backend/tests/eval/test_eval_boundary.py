"""评测器与生产代码的**方向性边界**（ADR-18 + §17.4 的前提条件）。

归属窗口：W6。

为什么这条要写成测试而不是口头约定
--------------------------------------------------------------------------
评测的可信度建立在两件事同时成立上，而它们是**相反**的方向：

1. `eval/**` 必须复用**在线同一条** guard/exec 路径（否则"沙箱通过"根本不代表被测系统，
   ADR-18）；但它**不许**碰 `app.api`（HTTP 层一旦进评测，报告里的数字就掺进了 W4 的
   路由/序列化行为，而那不属于 §17 的任何一条门禁）。
2. `app/**` 反过来**一行都不许**引用 `eval/**`。生产依赖评测器一旦成立，
   "评测"立刻退化成了被测系统的一部分 —— 而且是最没人审的那部分。

外加两条同样只在"出事那天"才看得见的：冻结件不许被评测改写；
N-13 的验真函数不许是恒真桩（带正对照）。
"""

from __future__ import annotations

import ast
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import _bootstrap

EVAL_DIR = os.path.dirname(_bootstrap.__file__)
APP_DIR = os.path.join(_bootstrap.BACKEND, "app")

#: 实测（本文件跑之前用同一套 AST 扫描取到）：`eval → app` 的真实依赖面。
#: 新增一个子包必须**先在此登记**，登记的动作就是把"评测为什么需要它"写清楚的地方。
ALLOWED_APP_DEPS = frozenset({
    "app.core",        # 契约/枚举/错误码
    "app.auth",        # IdentityContext 的构造口径
    "app.semantics",   # 语义包加载（allowlist 的唯一来源）
    "app.retrieval",   # 检索夹具要同形
    "app.binding",     # 降级原因码 + tenant_wrap 之外的绑定面
    "app.planner",     # 语义摘要消费 allowlist 的形状
    "app.llm",         # 匣带（录制/回放）挂在 ChatClient 上
    "app.graph",       # 整链路装配（走 build_graph 的官方测试缝）
    "app.guard",       # ADR-18：闸门与在线同源
    "app.exec",        # ADR-18：执行器契约与错误分类与在线同源
    "app.mask",        # 掩码面（N-11）
})

#: 🔴 明确禁止：进了它，评测数字里就掺了 HTTP 行为。
FORBIDDEN_APP_DEPS = frozenset({"app.api"})

#: W1A 归属的评测器模块（本目录只读它们，不许反向依赖）。
EVAL_MODULES = frozenset({
    "_bootstrap", "attribution", "build_frozen_set", "build_gold_seed", "build_red_team",
    "case_library", "cassette", "consistency", "equivalence", "gap_table", "gates",
    "grid", "harness", "redteam_eval", "reporter", "runner", "sqlite_exec",
})

#: W1A 的内容资产（评测只读；写它们 = 篡改冻结集）。
FROZEN_ASSETS = ("dataset_v1_frozen", "red_team_cases", "gold_query_seed", "MANIFEST_v1")


def _eval_files() -> Iterator[str]:
    for name in sorted(os.listdir(EVAL_DIR)):
        if name.endswith(".py"):
            yield os.path.join(EVAL_DIR, name)


def _py_files(root: str) -> Iterator[str]:
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _imported_modules(path: str) -> list[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            out.append(node.module or "")
    return out


# ==== 一、eval → app：既不许越界，也不许悄悄扩面 ======================
def test_eval_never_imports_the_http_layer():
    offenders = {
        p: [m for m in _imported_modules(p) if m.split(".")[0] == "app.api"
            or m.startswith("app.api")]
        for p in _eval_files()
    }
    assert not {k: v for k, v in offenders.items() if v}, (
        "评测一旦依赖 `app.api`，报告里的数字就掺进了 W4 的路由/序列化行为"
    )


def test_eval_app_dependencies_are_all_declared():
    """实测依赖面 ⊆ 声明面：悄悄多依赖一个 `app.obs` 之类，必须在这里先撞一次。"""
    seen: set[str] = set()
    for p in _eval_files():
        for m in _imported_modules(p):
            if m.startswith("app."):
                seen.add(".".join(m.split(".")[:2]))
    assert seen, "扫描本身坏掉（一个 app 依赖都没抓到）比越界更危险"
    assert seen - ALLOWED_APP_DEPS == set(), f"未登记的评测→生产依赖：{sorted(seen - ALLOWED_APP_DEPS)}"
    assert not seen & FORBIDDEN_APP_DEPS


def test_eval_reuses_the_online_gate_and_executor_entries():
    """ADR-18 的正面半边：**复用**而不是**重抄**。

    判据取"import 了在线的闸门/执行入口"而不是"调用了它们"：调用点在 `harness`/`runner`
    里，本测试只保证没有任何一个 eval 文件另立了一套闸门实现。
    """
    src = {p: Path(p).read_text(encoding="utf-8") for p in _eval_files()}
    assert any("from app.guard import" in s or "from app.guard." in s for s in src.values())
    assert any("from app.core.contracts import" in s or "app.exec" in s for s in src.values())
    reimplemented = [
        os.path.basename(p)
        for p, s in src.items()
        if any(f"def run_gate{ i}(" in s for i in (1, 2, 3))
    ]
    assert not reimplemented, f"评测侧自己写了闸门 = 被测系统没被评测：{reimplemented}"


# ==== 二、app → eval：必须为零 ========================================
def test_production_code_never_imports_the_evaluator():
    """方向只允许一条。生产一旦引用评测器，"评测"就成了被测系统的一部分。"""
    hits: list[tuple[str, str]] = []
    for path in _py_files(APP_DIR):
        for mod in _imported_modules(path):
            top = mod.split(".")[0]
            if top in EVAL_MODULES:
                hits.append((os.path.relpath(path, _bootstrap.ROOT), mod))
    assert not hits, f"生产反向依赖评测器：{hits}"


def test_the_sandbox_adapter_is_not_visible_to_production():
    """`sqlite_exec`（D2 裁定的 I/O 适配）只属于评测侧。

    它若被 `app.exec` 引用，就等于把"沙箱方言"偷偷带进生产路径 —— 那正是 §17.4
    缺口表必须披露的东西，不该以依赖的形式出现。
    """
    for path in _py_files(APP_DIR):
        assert "sqlite_exec" not in " ".join(_imported_modules(path)), path


def test_sqlite_exec_is_the_only_eval_module_that_touches_sqlite_directly():
    """🔴 反证 D2 的取舍：绕过执行器契约直接开库=评测器各说各话。"""
    users = {
        os.path.basename(p)
        for p in _eval_files()
        if any(m == "sqlite3" for m in _imported_modules(p))
    }
    assert "sqlite_exec.py" in users, "适配层本身没直连 sqlite3？那上面的子集断言就是空转"
    assert users <= {"sqlite_exec.py", "consistency.py", "runner.py", "harness.py", "build_frozen_set.py"}, users
    assert "equivalence.py" not in users and "gates.py" not in users, "判定层应当只吃表，不吃连接"


# ==== 三、冻结件不许被评测改写 ========================================
def _path_fragments(value: ast.AST, consts: dict[str, list[str]]) -> list[str]:
    """把路径表达式折成"这里可能出现的文件名片段"（字面量 + 名字，名字再展开一跳）。

    不这么做的话 `open(DATASET_PATH, "w")` 会被读成"参数里没有 `dataset_v1_frozen`"，
    于是整条检查变成永远绿 —— 那比没有检查更糟。
    """
    frags: list[str] = []
    for sub in ast.walk(value):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            frags.append(sub.value)
        elif isinstance(sub, ast.Name):
            frags.append(sub.id)
            frags.extend(consts.get(sub.id, ()))
    return frags


def _module_constants(tree: ast.Module) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = _path_fragments(node.value, out)
    return out


def _write_targets(path: str) -> list[int]:
    """返回该文件里"以写模式打开冻结件"的行号列表。"""
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=path)
    consts = _module_constants(tree)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if fname not in {"open", "replace", "rename"} and not (
            isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"
        ):
            continue
        mode = ""
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value)
        for kw in node.keywords or []:
            if kw.arg in {"mode", "encoding"} and isinstance(kw.value, ast.Constant):
                mode += str(kw.value.value)
        if fname == "open" and not any(c in mode for c in "wa+"):
            continue  # 只读打开不算写
        frags = _path_fragments(node.args[0], consts)
        if any(any(stem in f for stem in FROZEN_ASSETS) for f in frags):
            hits.append(node.lineno)
    return hits


def test_only_the_w1a_build_scripts_can_write_frozen_assets():
    """W1A 只读边界。

    ⚠️ 断言的是**恰好等于**而不是"子集"：命中集非空本身才是这条扫描器没瞎的证据。
    若哪天有人把 `build_*` 改得不再直写冻结件，这条会以"命中集变小"的形式提醒
    —— 那时要改判据，而不是把断言放宽。
    """
    writers = {os.path.basename(p): _write_targets(p) for p in _eval_files()}
    hit = {k: v for k, v in writers.items() if v}
    assert set(hit) == {"build_frozen_set.py", "build_gold_seed.py", "build_red_team.py"}, (
        f"冻结件的写入口变了：{hit}"
    )
    assert all(len(v) >= 1 for v in hit.values())


def test_w6_owned_eval_modules_never_open_a_frozen_asset_for_writing():
    """本窗口写的模块（判定/装配/报告）一个写入口都不许有。"""
    w6 = [
        os.path.basename(p) for p in _eval_files()
        if not os.path.basename(p).startswith("build_")
    ]
    assert w6, "扫描面为空 ⇒ 这条测试什么都没说"
    for name in w6:
        assert not _write_targets(os.path.join(EVAL_DIR, name)), f"{name} 试图写冻结件"


def test_build_scripts_are_the_w1a_ones_and_w6_wrote_none_of_them():
    """`build_*.py` 归 W1A（本窗口只读）。列在这里是为了让"新增一个 build_*"必须过一次说明。"""
    builders = {
        os.path.basename(p) for p in _eval_files() if os.path.basename(p).startswith("build_")
    }
    assert builders == {"build_frozen_set.py", "build_gold_seed.py", "build_red_team.py"}


# ==== 四、N-13 验真不许是恒真桩（正对照）=============================
def test_frozen_inputs_verify_ok_on_the_real_tree():
    ev = _bootstrap.verify_frozen_inputs()
    assert ev["checks"]["all_ok"] is True, ev
    assert ev["checks"]["dataset_content_hash"]["expected"] == ev["checks"]["dataset_content_hash"]["actual"]


def test_frozen_input_verification_actually_catches_a_tamper(monkeypatch, tmp_path):
    """正对照：让 W1A 的哈希实现返回一个定值，验真**必须**报红。

    这条是本文件最重要的一条。静态扫描与哈希校验最容易的失效方式是"永远绿"，
    而"永远绿的护栏"比没有护栏更糟 —— 它会被写进报告的 PASS 那一栏。
    """
    import build_frozen_set as bfs

    real = _bootstrap.verify_frozen_inputs()
    assert real["checks"]["all_ok"] is True
    monkeypatch.setattr(bfs, "case_content_hash", lambda cases: "sha256:" + "0" * 64)
    tampered = _bootstrap.verify_frozen_inputs()
    assert tampered["checks"]["dataset_content_hash"]["ok"] is False
    assert tampered["checks"]["all_ok"] is False


def test_sandbox_db_hash_is_part_of_the_frozen_evidence():
    """沙箱库换过 ⇒ 所有 `gold_result_hash` 失去意义，因此它必须在验真面里。"""
    ev = _bootstrap.verify_frozen_inputs()["checks"]["sandbox_db_sha256"]
    assert ev["ok"] is True and len(ev["actual"]) == 64
    assert ev["expected"] == ev["actual"]


# ==== 五、评测目录的形状（测试发现不了"文件根本没被收集"）============
def test_every_eval_module_is_importable_by_name():
    """`conftest.py` 只挂了 `sys.path`；这里确认那些名字真的能 import。

    写这条的理由：跑批用 `python eval/x.py`，测试用 `import x`，两条路的可导入性
    不是一回事（后者要求 `eval/` 在 `sys.path` 上，而它并不在包里）。
    """
    assert EVAL_DIR in sys.path or os.path.abspath(EVAL_DIR) in {os.path.abspath(p) for p in sys.path}
    for name in sorted(EVAL_MODULES):
        __import__(name)


def test_test_dir_files_are_all_collected():
    """一条被文件名拼错（`test_` 前缀漏了）的测试等于没有测试。"""
    here = os.path.dirname(os.path.abspath(__file__))
    files = [f for f in sorted(os.listdir(here)) if f.endswith(".py")]
    assert "conftest.py" in files and "__init__.py" in files
    tests = [f for f in files if f.startswith("test_")]
    assert len(tests) >= 6, f"测试文件数倒退：{tests}"
    for f in tests:
        assert f.endswith(".py")
