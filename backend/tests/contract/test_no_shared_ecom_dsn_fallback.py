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
- ✅ **已收口（2026-10-01，W2B）**：本文件曾登记的例外 —— `tests/integration/test_retrieval_fts_pg.py`
  的 `_dsn_from_env_file()` 在**运行期**读 `deploy/.env` 并把 `@pg:` 改写成 `@127.0.0.1:` ——
  **已删除**（判据 `docs/07:1133`，v1.7.17；该文件的 DSN 现与另外 8 个 integration 模块同款走
  `env_dsn`）。接管这一类形态的**第二条守卫** = `tests/contract/test_no_env_file_dsn_derivation.py`
  （R-ENVFILE：集成模块不得读 `.env`，AST + 简单赋值的传递闭包）⇒ 本文件不再为它开例外；
- ✅ **已收口（2026-10-03，T-24）**：`AnnAssign`（`NAME: Final[str] = "…"`）不进常量表的盲区已补，
  并同步扫面到 `backend/reports/**`＋`deploy/**`＋`eval/**`；补尺当场抓到 1 处（w2d 的 `DEFAULT_DSN`），
  加上旧尺本来就能抓到的 5 处 = 6 处，全部改成"缺 env 即 exit 2、不出产物"；
- ⚠️ **仍不在面内、如实登记的例外**：`app/repo/migrations/versions/0001_roles_and_audit_append_only.py:77-78`
  有 2 处 `os.environ.get("DATABASE_URL"/"ANALYTICS_DB_URL", <指向共享 ecom 的字面量>)`。
  它是**已执行过的冻结制品**（W1B 归属，`tests/unit/test_migration_dsn_hygiene.py` 文件头同口径）：
  改它会让"从零重建的库"与"已建的库"走上不同分支，那比"留一个本机引导凭据"更坏。
  ⇒ 本守卫的扫描面**刻意不含 `backend/app/**`**，而不是"扫了没扫到"；
- `tests/eval/**` 不在扫描面：W6 的字面量是守卫函数自身的测试输入，归 W6 自治；
- f-string / 运行期拼接出来的 DSN 静态不可见 —— 本守卫只认「str 常量及其 `+` 拼接、
  可解析的模块级常量名（含带注解的）」。
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
#: T-24 新收的三面（2026-10-03）：报告侧探针、压测侧装载脚本、评测执行器。
#: 收它们的理由不是"顺手扫宽"，而是本轮实测到 `backend/reports/**` 上真有 6 处同形状兜底，
#: 其中两条（w6 的 `_probe_pg_real.py`／`_probe_parallel_states.py`）**以超管身份**连共享栈 ——
#: `force_readonly()` 保证写不进去，但保证不了"拨的是哪个库"。
_PROBE_DIRS = (_BACKEND_DIR / "reports", _REPO_ROOT / "deploy", _REPO_ROOT / "eval")

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
    """模块级 `NAME = <静态 str>` 与 `NAME: <ann> = <静态 str>` 表（解析 `_SCHEME + ...` 这类拼接兜底的前提）。

    🔴 `AnnAssign` 那一支是 T-24 补的：带类型注解的模块常量（`DEFAULT_DSN: Final[str] = "…"`）
    原先**不进这张表** ⇒ 下游 `_static_str(Name)` 查不到 ⇒ 兜底串静默漏网。
    实测存量：`backend/reports/w2d/probe_explain_timing_pg.py` 正是这一形（注解常量 + `os.environ.get(VAR, DEFAULT_DSN)`），
    旧尺在整仓上给它判了"零命中"。注解形态在报告脚本里很常见，不是罕见写法。
    """
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = _static_str(node.value, out)
                if value is not None:
                    out[target.id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _static_str(node.value, out) if node.value is not None else None
            if value is not None:
                out[node.target.id] = value
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
# ②′ T-24：同一把尺也压在**探针与装载脚本**上（原先只量 `tests/integration`，
#   而"漏带 env 静默打共享栈"这个失效形状与谁是受害者无关）
# ----------------------------------------------------------------------------
def test_report_probes_and_loadtest_scripts_have_no_shared_ecom_dsn_fallback() -> None:
    violations = [v for d in _PROBE_DIRS for v in _scan(d)]
    if not violations:
        return
    table = "\n".join(
        f"  {v['file']}:{v['line']}  env={v['var']}  →  {v['dsn']}" for v in violations
    )
    pytest.fail(
        f"探针/装载脚本面存在 {len(violations)} 处「指向共享 ecom 的字面默认 DSN」——"
        "`force_readonly()` 只保证写不进去，不保证拨的是哪个库；漏带 env 时静默回落 = "
        "把共享实例当探针靶子，而产物看起来是一次真探测：\n"
        f"{table}\n"
        "修法（与 `backend/reports/w6/probe_audit_invariant.py` 同形）："
        "`DSN = force_readonly(os.environ.get(VAR, '')) if os.environ.get(VAR) else ''`，"
        "并在 `main()` 开头按缺失变量名点名、`exit 2` 不出产物。"
    )


# ----------------------------------------------------------------------------
# 守卫自身的正对照（常驻 CI：护栏空转 = 假绿，必须当场证伪）
# ----------------------------------------------------------------------------
def _write(tmp_path: Path, source: str) -> Path:
    target = tmp_path / "fixture_sample.py"
    target.write_text(source, encoding="utf-8")
    return target


def test_guard_bites_on_the_real_shapes(tmp_path: Path) -> None:
    """三种现存肇事形态（内联字面量 / 经模块常量拼接的 scheme / **带注解的模块常量**）都必须咬中。"""
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

    # 🔴 第三形 = T-24 补的 `AnnAssign` 盲区：肇事串住在**带注解的模块常量**里，
    #    兜底位只写常量名。旧尺不解析注解赋值 ⇒ 这一形整仓静默漏网（w2d 实测中过）。
    annotated = (
        "import os\n"
        "from typing import Final\n"
        'DEFAULT_DSN: Final[str] = "postgresql://app_ro:app_ro_pwd@127.0.0.1:5432/ecom"\n'
        '_P = os.environ.get("PROBE_PG_DSN", DEFAULT_DSN)\n'
    )
    ann_dir = tmp_path / "annotated"
    ann_dir.mkdir()
    _write(ann_dir, annotated)
    assert len(_scan(ann_dir)) == 1, "带注解的模块常量兜底没被咬中 —— 尺子退回 AnnAssign 盲区"


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
