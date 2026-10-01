"""`U-114` 残余面 —— 集成夹具禁止从 `.env` 取 DSN（2026-10-01，W2B）。

为什么要有这条断言（判据出处 `docs/07:1133`，v1.7.17）
--------------------------------------------------------------------------
判定原句：「该夹具的运行期 DSN 也要过 `pg_guard` 的形状判定，**或改为只认环境变量**」。
`test_retrieval_fts_pg.py` 走的是第二支（与另外 8 个 integration 模块同款）。

为什么静态守卫是必须的那一半
--------------------------------------------------------------------------
第二支的"只认环境变量"**本身看不出来**是否真的做到 —— 旧实现长这样：

    PROD_DSN = _dsn_from_env_file()          # 读 deploy/.env、把 @pg: 改写成 @127.0.0.1:
    TEST_DSN = os.environ.get("RETRIEVAL_TEST_PG_DSN") or PROD_DSN

它**有**环境变量、**也**有 `or`，肉眼与 `os.environ.get(VAR)` 几乎一样；区别在于
"缺 env 时发生什么"是**运行期**行为、静态看不见。所以 `test_no_shared_ecom_dsn_fallback.py`
（防线②，扫字面量默认值）**结构性地咬不到它** —— 该文件 §「诚实边界」第 1 条已登记此事，
并把收口判给"该夹具归属窗口"（= W2B，即本文件这一轮）。

本守则（**R-ENVFILE**）
--------------------------------------------------------------------------
`tests/integration/**` 的模块**不得读任何 `.env` 文件内容**（`read_text` / `read_bytes` /
`readlines` / `.open()` / `open()`，路径里静态含 `.env`；以及 `load_dotenv` / `dotenv_values`）。
理由不是洁癖：集成夹具拿到 DSN 后的**第一条语句**就是 DDL（`CREATE SCHEMA` / `DROP TABLE`），
所以"从 `.env` 取 DSN"这条链路的终点是**在开发机共享库上试写**；要什么值请**显式**走环境变量
（`tests/integration/_env_dsn.py` 的 `env_dsn`：缺 = 具名 fail，禁 skip）。
`.env` 读法本身就不是"取配置"的手段 —— 它是**隐式兜底**的入口。

⚠️ 走的是**传递闭包**而不是只认字面量：`env_file = … / ".env"` 再 `env_file.read_text()`
这种**经变量中转**的写法才是实际形态（字面量直写在 `read_text()` 里的写法本案没出现过）。
闭包对"简单赋值（`NAME = expr`）"迭代到不动点，`NAME = 别名` 的链路也追得到。

刻意**不咬**的形态
--------------------------------------------------------------------------
- docstring / 注释里提到 `.env`（使用说明，不是取值动作）—— 本守卫走 AST，天然不看注释，
  而 docstring 是 `Expr(Constant)`、不在任何读调用子树里；
- 报错文案里写 `deploy/.env`（如 `pytest.skip("…不要指向 .env…")`）；
- `os.environ.get(VAR)`（合法取值方式，含缺省即 fail 的形态）；
- 读**别的**文件（`read_text()` 的路径里没有 `.env`）。

诚实边界
--------------------------------------------------------------------------
- 只扫 `tests/integration/**`（与防线② 同面）。`tests/conftest.py`、`eval/**` 不在面内 ——
  若它们也要收口，另开判据，本文件不冒充覆盖；
- 静态追的是**同名简单赋值**；跨函数传参把路径带进来（`f(path)` 里读）看不见 ——
  但无论怎么传，**总得有一次 `.env` 读调用落地**，本守则就在那一次拦；
- 与防线② 的分工：防线② 管"字面量默认值指向共享 ecom"，本守则管"从 `.env` 取值"。
  两者是**同一 hazard 的两条入口**，都不许靠"反正权限会挡住"。
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend
_INTEGRATION_DIR = _BACKEND_DIR / "tests" / "integration"

#: 会**读文件内容**的方法名（receiver 链或参数里出现 `.env` 即违规）。
_READ_METHODS = {"read_text", "read_bytes", "readlines", "open"}
#: dotenv 家族：默认行为就是读 `.env`（无参调用一律违规）。
_DOTENV_FUNCS = {"load_dotenv", "dotenv_values"}
_ENV_FILE_TOKEN = ".env"


def _call_name(func: ast.AST) -> str | None:
    """`open(...)` / `p.read_text(...)` / `dotenv.load_dotenv(...)` → 末段名。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _strings(node: ast.AST | Sequence[ast.AST]) -> list[str]:
    """子树（或子树列表）里的全部 str 常量值。"""
    nodes = [node] if isinstance(node, ast.AST) else list(node)
    return [
        sub.value
        for one in nodes
        for sub in ast.walk(one)
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
    ]


def _mentions_env_file(node: ast.AST | Sequence[ast.AST]) -> bool:
    return any(_ENV_FILE_TOKEN in s for s in _strings(node))


def _env_file_names(tree: ast.Module) -> set[str]:
    """静态绑定到 `.env` 路径的名字集合（简单赋值的**传递闭包**）。

    `env_file = … / ".env"` ⇒ tainted；再 `alias = env_file` ⇒ 也 tainted。
    只认 `NAME = expr` 形态；带下标/属性目标、元组解包一律不猜。
    """
    binds: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            binds[node.targets[0].id] = node.value

    tainted = {name for name, value in binds.items() if _mentions_env_file(value)}
    changed = True
    while changed:
        changed = False
        for name, value in binds.items():
            if name in tainted:
                continue
            if any(
                isinstance(sub, ast.Name) and sub.id in tainted for sub in ast.walk(value)
            ):
                tainted.add(name)
                changed = True
    return tainted


def _scan_source(source: str) -> list[dict[str, Any]]:
    """返回违规清单（每项：line / call / reason）。纯函数，便于正对照自测。"""
    tree = ast.parse(source)
    tainted = _env_file_names(tree)
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name is None:
            continue
        if name in _DOTENV_FUNCS:
            # 无参 = 默认搜 `.env`；带参 = 参数里点到 `.env` 才算。两种都违规。
            if not node.args or _mentions_env_file(node):
                found.append({"line": node.lineno, "call": name, "reason": "dotenv 家族读 .env"})
            continue
        if name not in _READ_METHODS:
            continue

        tosearch: list[ast.expr] = list(node.args) + [kw.value for kw in node.keywords]
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        if receiver is not None:
            tosearch.append(receiver)
        if _mentions_env_file(tosearch):
            found.append({"line": node.lineno, "call": name, "reason": "读路径静态含 .env"})
        elif any(
            isinstance(sub, ast.Name) and sub.id in tainted
            for one in tosearch
            for sub in ast.walk(one)
        ):
            found.append(
                {"line": node.lineno, "call": name, "reason": "读路径经变量静态指向 .env"}
            )
    return found


def _scan(directory: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*.py")):
        try:
            where = path.relative_to(_BACKEND_DIR).as_posix()
        except ValueError:  # tmp_path 等扫描目录外的文件（守卫自测用）
            where = str(path)
        for hit in _scan_source(path.read_text(encoding="utf-8")):
            out.append({"file": where, **hit})
    return out


# ----------------------------------------------------------------------------
# 真树断言（负向：这条现在应当是绿的；它的价值由下面的正对照保证不空转）
# ----------------------------------------------------------------------------
def test_integration_modules_do_not_read_dotenv_files() -> None:
    violations = _scan(_INTEGRATION_DIR)
    if not violations:
        return
    table = "\n".join(
        f"  {v['file']}:{v['line']}  {v['call']}()  ← {v['reason']}" for v in violations
    )
    pytest.fail(
        f"集成模块存在 {len(violations)} 处「读 `.env` 取 DSN」——"
        "夹具拿到 DSN 后的第一条语句就是 DDL（CREATE SCHEMA / DROP TABLE），"
        "所以这条链路的终点是在开发机**共享库上试写**（2026-09-22 的历史形态）。\n"
        f"{table}\n"
        "修法：删掉 `.env` 读取，DSN 显式走环境变量 —— "
        '`from tests.integration._env_dsn import env_dsn` 后 `DSN = env_dsn("VAR")`'
        "（缺 env = import 期具名 fail，禁 skip、禁默认值）。"
    )


# ----------------------------------------------------------------------------
# 守卫自身的正/负对照（护栏空转 = 假绿，必须当场证伪）
#
# ⚠️ 正对照用的就是**本案的历史形态**（`git show fd5f5f2:backend/tests/integration/
#    test_retrieval_fts_pg.py` 里逐字存在过的那段），所以"它会红"不是假设、是复现。
# ----------------------------------------------------------------------------
def test_guard_bites_on_the_historical_shape() -> None:
    """旧实现（读 deploy/.env 后赋给夹具变量）必须被咬中 —— 逐字取自修复前的源码。"""
    pre_fix = (
        "from pathlib import Path\n"
        "\n"
        "def _dsn_from_env_file() -> str | None:\n"
        "    env_file = Path(__file__).resolve().parents[3] / 'deploy' / '.env'\n"
        "    if env_file.exists():\n"
        "        for line in env_file.read_text(encoding='utf-8').splitlines():\n"
        "            if line.startswith('DATABASE_URL='):\n"
        "                return line.partition('=')[2].strip()\n"
        "    return None\n"
        "\n"
        "PROD_DSN = _dsn_from_env_file()\n"
    )
    hits = _scan_source(pre_fix)
    # `read_text` 命中；`exists` 不在读方法表内，故恰 1 处。
    assert len(hits) == 1, hits
    assert hits[0]["call"] == "read_text"
    assert "变量" in hits[0]["reason"]


def test_guard_bites_on_one_extra_hop_of_indirection() -> None:
    """赋值链再转一手也必须追到（防"改个名就绕过"）。"""
    source = (
        "from pathlib import Path\n"
        "base = Path('deploy')\n"
        "target = base / '.env'\n"
        "alias = target\n"
        "text = alias.read_text()\n"
    )
    hits = _scan_source(source)
    assert len(hits) == 1, hits


def test_guard_bites_on_dotenv_helpers() -> None:
    """`load_dotenv()` / `dotenv_values()` 是同一入口的另一种写法，必须同样咬中。"""
    assert _scan_source("from dotenv import load_dotenv\nload_dotenv()\n")
    assert _scan_source("import dotenv\ndotenv.load_dotenv('/srv/app/.env')\n")
    assert _scan_source("from dotenv import dotenv_values\nv = dotenv_values('.env')\n")


def test_guard_bites_on_plain_open() -> None:
    assert _scan_source("open('deploy/.env')")
    assert _scan_source("f = (Path('deploy') / '.env').open()")


def test_guard_spares_legitimate_shapes() -> None:
    """四类正当形态都不许咬（假阳性 = 护栏失去信用，下一批人会把它关掉）。"""
    spared = (
        '"""模块说明：本文件不读 deploy/.env（只认环境变量）。"""\n'
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "# 注释里提到 .env 不算取值动作\n"
        "_A = os.environ.get('RETRIEVAL_TEST_PG_DSN', '')\n"
        "MSG = '请把 DSN 指向一次性容器，不要指向 deploy/.env'\n"
        "_B = Path(__file__).read_text(encoding='utf-8')\n"  # 读的是别的文件
        "_C = Path(__file__).resolve().parents[3]\n"
    )
    assert _scan_source(spared) == []


def test_guard_spares_the_current_integration_tree_and_is_not_vacuous() -> None:
    """两道保险合一条：真树零命中 **且** 扫描面确实非空（防"扫了个空目录也是绿"）。"""
    scanned = sorted(_INTEGRATION_DIR.rglob("*.py"))
    assert len(scanned) >= 8, f"扫描面异常（{len(scanned)} 个文件）—— 守卫可能指错了目录"
    assert _scan(_INTEGRATION_DIR) == []
