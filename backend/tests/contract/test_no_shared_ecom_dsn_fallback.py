"""U-114 防线② —— 集成夹具禁止「指向共享 ecom 的字面默认 DSN」（2026-09-22，W7 点名）。

为什么要有这条断言
--------------------------------------------------------------------------
W7 的证据（2026-09-22）：四小时内 `app.embed_doc` 被全表重载 21 次（ins/del 1970→6107，
每次 ≈197 行 = 一次 materialize），`cost_ledger` 出现 TRUNCATE 签名 —— 来源是集成夹具里的
`os.environ.get("COMMERCEQL_TEST_*_DSN", "<localhost:5432/ecom 字面量>")`：CI 本来会注入
这些 env，**只有本地裸跑才会落到字面量兜底**，于是在跑着 compose 共享栈的开发机上，
一次无意的 `pytest tests/integration` 就把共享库当测试沙箱用了（G-6 与所有窗口的复现
前置都被它挡住）。

判定形状（唯一真相 = `eval/pg_guard.py`，W6 `3ff31c4`）
--------------------------------------------------------------------------
DSN 的解析与脱敏**只**用 `pg_guard.redact_dsn`（同一份形状 regex），本文件不复制第二份。
命中条件 = 字面量能被解析成 DSN，且 **db == ecom** 且 **host ∈ {localhost, 127.0.0.1}**
—— 即"从宿主机拨得通共享栈"的形态。

刻意**不咬**的形态（都有正当用途，咬了就是假阳性）：
- `host = pg`（容器网内名，宿主机/CI runner 都解析不了）：`conftest.py` / Settings 构造用的占位 DSN；
- `db != ecom`（fail-fast 测试的假 DSN，如 `.../commerceql`）；
- 出现在 **docstring** 里的 DSN（使用说明，不是可拨号默认值）—— 本守卫走 AST，天然不看注释；
- **没有兜底**的 `os.environ.get(VAR)`（缺 env 时得到 None → 夹具自行 skip，这正是想要的形态）。

诚实边界（静态分析的能力上限）：
- `tests/integration/test_retrieval_fts_pg.py` 的 `_dsn_from_env_file()` 在**运行时**读
  `deploy/.env` 并把 `@pg:` 改写成 `@127.0.0.1:` —— 静态看不见，本守卫不覆盖（既存机制，
  是否也要收口归该夹具归属窗口 + 架构裁，本文件只登记）；
- `tests/eval/**` 不在扫描面：W6 的字面量是守卫函数自身的测试输入，归 W6 自治；
- f-string / 运行期拼接出来的 DSN 静态不可见 —— 本守卫只认「str 常量及其 `+` 拼接、
  可解析的模块级常量名」。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend
_REPO_ROOT = _BACKEND_DIR.parent  # .../CommerceQL
_INTEGRATION_DIR = _BACKEND_DIR / "tests" / "integration"

# DSN 形状/脱敏的唯一真相在 eval/pg_guard.py（W6）；这里只借用，不复制。
_EVAL_DIR = _REPO_ROOT / "eval"
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))
import pg_guard  # noqa: E402  ← 路径注入后才能 import（同 tests/eval/conftest.py 的做法）

_UNPARSABLE = "<无法解析的 DSN 形状：不落盘>"
_SHARED_DB = "ecom"
_SHARED_HOSTS = {"localhost", "127.0.0.1"}


# ----------------------------------------------------------------------------
# 极小静态求值：str 常量、它们的 `+` 拼接、以及可解析的模块级常量名。
# 除此之外（f-string / 函数调用 / 下标）一律返回 None —— 不猜。
# ----------------------------------------------------------------------------
def _static_str(node: ast.AST, consts: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _static_str(node.left, consts), _static_str(node.right, consts)
        if left is not None and right is not None:
            return left + right
        return None
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def _module_str_constants(tree: ast.Module) -> dict[str, str]:
    """模块级 `NAME = <静态 str>` 表（解析 `_SCHEME + ...` 这类拼接兜底的前提）。"""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = _static_str(node.value, out)
                if value is not None:
                    out[target.id] = value
    return out


def _is_env_get_call(node: ast.AST) -> bool:
    """`os.environ.get(...)` / `os.getenv(...)` / 裸 `getenv(...)`（from os import getenv）。"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "getenv"
    if isinstance(func, ast.Attribute):
        if func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
            return True
        if func.attr == "get" and isinstance(func.value, ast.Attribute):
            inner = func.value
            return (
                inner.attr == "environ"
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "os"
            )
    return False


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    return {
        id(child): node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }


def _points_at_shared_ecom(text: str) -> bool:
    redacted = pg_guard.redact_dsn(text)
    if redacted == _UNPARSABLE or "@" not in redacted or "/" not in redacted:
        return False
    host_part, db = redacted.rsplit("/", 1)
    host = host_part.split("@", 1)[1].split(":", 1)[0]
    return db == _SHARED_DB and host in _SHARED_HOSTS


def _scan(directory: Path) -> list[dict[str, Any]]:
    """返回「指向共享 ecom 的字面默认 DSN」清单（每项：file/line/var/dsn 已脱敏）。"""
    found: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = _module_str_constants(tree)
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not _is_env_get_call(node):
                continue
            call: ast.Call = node
            var = _static_str(call.args[0], consts) if call.args else "?"
            # 兜底候选 = 第 2 个位置参数 + default= 关键字；都没有时，
            # 若调用外层是 `get(VAR) or X` 的 BoolOp，则兄弟操作数也是兜底。
            candidates: list[ast.AST] = list(call.args[1:]) + [
                kw.value for kw in call.keywords if kw.arg == "default"
            ]
            if not candidates:
                parent = parents.get(id(call))
                if isinstance(parent, ast.BoolOp):
                    candidates = [v for v in parent.values if v is not call]
            for cand in candidates:
                text = _static_str(cand, consts)
                if text is not None and _points_at_shared_ecom(text):
                    try:
                        where = path.relative_to(_BACKEND_DIR).as_posix()
                    except ValueError:  # tmp_path 等扫描目录外的文件（守卫自测用）
                        where = str(path)
                    found.append(
                        {
                            "file": where,
                            "line": cand.lineno,
                            "var": var or "?",
                            "dsn": pg_guard.redact_dsn(text),
                        }
                    )
    return found


# ----------------------------------------------------------------------------
# 真树断言（当前刻意红 —— 命中的就是现存肇事夹具；修法见失败输出）
# ----------------------------------------------------------------------------
def test_integration_fixtures_have_no_shared_ecom_dsn_fallback() -> None:
    violations = _scan(_INTEGRATION_DIR)
    if not violations:
        return
    table = "\n".join(
        f"  {v['file']}:{v['line']}  env={v['var']}  →  {v['dsn']}" for v in violations
    )
    pytest.fail(
        f"集成夹具存在 {len(violations)} 处「指向共享 ecom 的字面默认 DSN」——"
        "本地裸跑会静默连上 compose 共享栈并重载 embed_doc / TRUNCATE cost_ledger"
        f"（W7 证据：4 小时 21 次全表重载）：\n{table}\n"
        "修法（归属各夹具窗口）：把 os.environ.get(VAR, 字面量) 改成「必填 env，缺省即 skip」——"
        "CI 本就注入 COMMERCEQL_TEST_*_DSN，改后 CI 不受影响，只有本地裸跑从『毁库』变『跳过』。"
    )


# ----------------------------------------------------------------------------
# 守卫自身的正对照（常驻 CI：护栏空转 = 假绿，必须当场证伪）
# ----------------------------------------------------------------------------
def _write(tmp_path: Path, source: str) -> Path:
    target = tmp_path / "fixture_sample.py"
    target.write_text(source, encoding="utf-8")
    return target


def test_guard_bites_on_the_real_shapes(tmp_path: Path) -> None:
    """两种现存肇事形态（内联字面量 / 经模块常量拼接的 scheme）都必须咬中。"""
    inline = (
        "import os\n"
        '_RW = os.environ.get(\n'
        '    "COMMERCEQL_TEST_RW_DSN", "postgresql://app_rw:app_rw_pwd@localhost:5432/ecom"\n'
        ")\n"
    )
    _write(tmp_path, inline)
    assert len(_scan(tmp_path)) == 1

    concat = (
        "import os\n"
        '_SCHEME = "postgresql+psycopg" + "://"\n'
        '_S = os.environ.get(\n'
        '    "COMMERCEQL_TEST_SUPER_DSN",\n'
        '    _SCHEME + "postgres" + ":" + "postgres" + "@localhost:5432/ecom",\n'
        ")\n"
    )
    concat_dir = tmp_path / "concat"
    concat_dir.mkdir()
    _write(concat_dir, concat)
    assert len(_scan(concat_dir)) == 1


def test_guard_bites_on_boolop_fallback(tmp_path: Path) -> None:
    """`get(VAR) or 字面量` 与 `get(VAR, 字面量)` 是同一个兜底，必须同样咬中。"""
    source = (
        "import os\n"
        '_D = os.environ.get("X") or "postgresql://app_ro:app_ro_pwd@127.0.0.1:5432/ecom"\n'
    )
    _write(tmp_path, source)
    assert len(_scan(tmp_path)) == 1


def test_guard_spares_legitimate_shapes(tmp_path: Path) -> None:
    """docstring / 无兜底 / host=pg / db!=ecom 四类正当形态都不许咬（假阳性 = 护栏失去信用）。"""
    source = (
        "import os\n"
        "USAGE = \"\"\"\n"
        "COMMERCEQL_TEST_RW_DSN=postgresql://app_rw:app_rw_pwd@localhost:5432/ecom \\\n"
        " pytest tests/integration/...\"\"\"\n"  # docstring 里的使用说明：不咬
        '_A = os.environ.get("COMMERCEQL_TEST_RW_DSN")\n'  # 无兜底 → 夹具自己 skip：不咬
        '_B = "postgresql+psycopg://app_rw:placeholder@pg:5432/ecom"\n'  # host=pg 拨不通：不咬
        '_C = "postgresql://app_rw:pw@localhost:5432/commerceql"\n'  # db≠ecom：不咬
    )
    _write(tmp_path, source)
    assert _scan(tmp_path) == []
