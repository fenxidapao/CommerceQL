"""`U-114` 残余面 + `U-133` 判据③ —— 夹具与**探针**都禁止从 `.env` 取 DSN（2026-10-01 W2B；2026-10-02 扩面 W0）。

为什么要有这条断言（判据出处 `docs/07:1133` v1.7.17 + `docs/07:1163` v1.7.18）
--------------------------------------------------------------------------
`U-114` 判定原句：「该夹具的运行期 DSN 也要过 `pg_guard` 的形状判定，**或改为只认环境变量**」。
`test_retrieval_fts_pg.py` 走的是第二支（与另外 **7** 个 integration 模块同款）。
`U-133` 判据③ 原句：「`U-114` 防线② 的 AST 守卫扫描面从 `tests/integration/**` 扩到
**`deploy/loadtest/**` 与 `eval/**`**」——**面二**即由此而来；归属见 `docs/08 §4.1`「扩面归 W0」。

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
**面一（严）：`tests/integration/**`** —— 模块**不得读任何 `.env` 文件内容**（`read_text` /
`read_bytes` / `readlines` / `.open()` / `open()`，路径里静态含 `.env`；以及
`load_dotenv` / `dotenv_values`）。
理由不是洁癖：集成夹具拿到 DSN 后的**第一条语句**就是 DDL（`CREATE SCHEMA` / `DROP TABLE`），
所以"从 `.env` 取 DSN"这条链路的终点是**在开发机共享库上试写**；要什么值请**显式**走环境变量
（`tests/integration/_env_dsn.py` 的 `env_dsn`：缺 = 具名 fail，禁 skip）。
`.env` 读法本身就不是"取配置"的手段 —— 它是**隐式兜底**的入口。

**面二（DSN 限定）：`deploy/loadtest/**` 与 `eval/**`**（`U-133` ③，2026-10-02 W0 扩面）
—— 这两棵树下 `.env` 读取**只在"取 DSN"时**才算违规：判定式 = 该读取**所在作用域**里出现
**DSN 键名**（`_DSN_KEY_RE`：`DATABASE_URL` / `DSN` / `*_DB_URL` / `PG*URL` / `POSTGRES*URL` /
`SQLALCHEMY_DATABASE_URI`）。
⚠️ **为什么面二不能沿用面一的严规则**：`docs/07:1163` 自带一条**对照件** ——
`eval/reporter.py:595` 也读 `deploy/.env`，但它只取 `BINDING_TAU*` 开头的键、且把值归一成**布尔**
（只落"有没有值"，不落值本身）。
实测（2026-10-02，HEAD `ce85db0`）：同文件在**严规则**下 1 命中（`:597`）、在**面二规则**下
0 命中 ⇒ 面二不是"给某个文件开后门"，是把判据从**动作**收到**意图**（禁的是"从 `.env` 拿连接串"）。

⚠️ 走的是**传递闭包**而不是只认字面量：`env_file = … / ".env"` 再 `env_file.read_text()`
这种**经变量中转**的写法才是实际形态（字面量直写在 `read_text()` 里的写法本案没出现过）。
闭包对"简单赋值（`NAME = expr`）"迭代到不动点，`NAME = 别名` 的链路也追得到。

刻意**不咬**的形态
--------------------------------------------------------------------------
- docstring / 注释里提到 `.env`（使用说明，不是取值动作）—— 本守卫走 AST，天然不看注释，
  而 docstring 是 `Expr(Constant)`、不在任何读调用子树里；
- 报错文案里写 `deploy/.env`（如 `pytest.skip("…不要指向 .env…")`）；
- `os.environ.get(VAR)`（合法取值方式，含缺省即 fail 的形态）；
- 读**别的**文件（`read_text()` 的路径里没有 `.env`）；
- **面二**上、作用域里**没有 DSN 键名**的 `.env` 读取（对照件 = `eval/reporter.py` 的 τ 校准块）。

诚实边界
--------------------------------------------------------------------------
- 面一 = `tests/integration/**`（与防线② 同面）；面二 = `deploy/loadtest/**` + `eval/**`。
  `tests/conftest.py`、`tests/eval/**`、`backend/app/**` 均**不在面内** —— 要收口另开判据，本文件不冒充覆盖。
- 🔴 **面二首跑（2026-10-02，HEAD `ce85db0`）实测咬到 1 处真违规**，已在下面 `_KNOWN_LEGACY_HITS`
  具名登记（**只许销账、不许新增**）：`deploy/loadtest/w2b_materialize/_w2b_u112_materialize.py:56`
  —— `rw_dsn()` 读 `deploy/.env` 的 `DATABASE_URL`、换成宿主 DSN，`:68` 直接 `psycopg.connect`。
  属主 = **W2B（件）**，所在树 = **W7**（`deploy/**`，`08 §4.1`）⇒ W0 只登记，不代改。
- 🔴 **但 `U-133` ① 的「主体」两条守卫都咬不到**（别把面二当它的达标凭证）：
  ① 的形态是 `deploy/loadtest/load_synth_to_pg.py` **完全没有 `os.environ`/`.env` 读取**、
  却有一个**模块级字面 `DEFAULT_DSN`**（含属主段+口令段，指向共享 `ecom`）被 `--dsn` 当默认值，
  下游 `:134` 是 `truncate app.{base}`。实测三数：本件 **0 命中**（它不读 `.env`）、
  防线② **0 命中**（防线② 的入口谓词是 `os.environ.get/getenv` 的**兜底操作数**，裸的模块级常量
  不在它的形状里）、而它确实是 ①。⇒ ① 的探测器需要**第三条谓词**（"运行期 DSN 的字面默认值"），
  不在本件能力面内 —— 见 W0 回执 `RELAY.md §15`；本件在面二上只覆盖**读 `.env` 取 DSN** 这一支。
- 静态追的是**同名简单赋值**；跨函数传参把路径带进来（`f(path)` 里读）看不见 ——
  但无论怎么传，**总得有一次 `.env` 读调用落地**，本守则就在那一次拦。
- 面二的 DSN 键名判定是**作用域级**近似：键名写在别的函数里、读取写在这个函数里 ⇒ 漏判。
  它只用来挡"顺手从 `.env` 拿连接串"，不是完备的污点分析。
- 与防线② 的分工：防线② 管"**env 兜底**到共享 ecom 字面量"，本守则管"从 `.env` 取值"。
  两者是**同一 hazard 的两条入口**，都不许靠"反正权限会挡住"。
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend
_REPO_ROOT = _BACKEND_DIR.parent  # .../CommerceQL
_INTEGRATION_DIR = _BACKEND_DIR / "tests" / "integration"
_LOADTEST_DIR = _REPO_ROOT / "deploy" / "loadtest"
_EVAL_DIR = _REPO_ROOT / "eval"

#: 面二（DSN 限定）的两棵树 —— `U-133` 判据③（2026-10-02 扩面）。
_PROBE_FACES: tuple[Path, ...] = (_LOADTEST_DIR, _EVAL_DIR)

#: 会**读文件内容**的方法名（receiver 链或参数里出现 `.env` 即违规）。
_READ_METHODS = {"read_text", "read_bytes", "readlines", "open"}
#: dotenv 家族：默认行为就是读 `.env`（无参调用一律违规）。
_DOTENV_FUNCS = {"load_dotenv", "dotenv_values"}
_ENV_FILE_TOKEN = ".env"

#: **DSN 键族**（只对面二生效）：`.env` 里用来取**连接串**的键名。
#: 两侧用"非标识符字符"边界，而不是裸子串 —— 免得把散文/报告文案里的 `DSN` 字样也算成键名。
_DSN_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:DATABASE_URL|DB_URL|DSN|SQLALCHEMY_DATABASE_URI|"
    r"PG[A-Z0-9_]*URL|POSTGRES(?:QL)?[A-Z0-9_]*URL)"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

#: **面二存量登记**（`U-133` ③ 扩面首跑实测，2026-10-02 W0）。
#: 纪律两条：**新增命中一律红**；**存量被修掉后必须销账**（下面两条断言一起逼）。
#: 登记形状 = `"<repo 相对 posix 路径>:<行号>"`。W0 只登记不代改（属主见文件头「诚实边界」）。
_KNOWN_LEGACY_HITS: frozenset[str] = frozenset(
    {
        "deploy/loadtest/w2b_materialize/_w2b_u112_materialize.py:56",  # W2B 件 / W7 树
    }
)


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


def _enclosing_scope(tree: ast.Module, lineno: int) -> ast.AST:
    """读调用所在的最内层作用域（函数体优先，模块兜底）。面二的 DSN 键名判定用它。"""
    best: ast.AST | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        if not (node.lineno <= lineno <= end):
            continue
        if best is None or node.lineno >= best.lineno:
            best = node
    return best if best is not None else tree


def _names_dsn_key(scope: ast.AST) -> bool:
    """作用域内的字面量里是否出现 **DSN 键名**（面二判定式）。"""
    return any(_DSN_KEY_RE.search(text) for text in _strings(scope))


def _scan_source(source: str, *, dsn_scoped: bool = False) -> list[dict[str, Any]]:
    """返回违规清单（每项：line / call / reason）。纯函数，便于正对照自测。

    `dsn_scoped=False` = **面一**：任何 `.env` 读取都违规。
    `dsn_scoped=True`  = **面二**：仅当该读取**所在作用域内出现 DSN 键名**时才算违规
    —— 对照件 `eval/reporter.py` 只取 `BINDING_TAU*` 的「有没有值」⇒ 不咬。
    """
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
    if dsn_scoped:
        found = [hit for hit in found if _names_dsn_key(_enclosing_scope(tree, hit["line"]))]
        for hit in found:
            hit["reason"] += "，且作用域内出现 DSN 键名"
    return found


def _scan(directory: Path, *, dsn_scoped: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*.py")):
        where = str(path)
        for base in (_BACKEND_DIR, _REPO_ROOT):  # backend 先试，保持集成面的历史展示形状
            try:
                where = path.relative_to(base).as_posix()
                break
            except ValueError:  # tmp_path 等两棵根之外的文件（守卫自测用）
                continue
        for hit in _scan_source(path.read_text(encoding="utf-8"), dsn_scoped=dsn_scoped):
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


# ----------------------------------------------------------------------------
# 面二：探针面（`U-133` 判据③，2026-10-02 W0 扩面；归属 `docs/08 §4.1`「扩面归 W0」）
#
# ⚠️ 面二对 `U-133` ①（装载器缺 env 即 `TRUNCATE` 共享库）**不构成检测** —— 见文件头
#    「诚实边界」第 2 条（`load_synth_to_pg.py` 不读 `.env`，实测 0 命中）。
#    下面这组断言保的是**回归栅栏**与**规则本身不空转**，不是 ① 的达标凭证。
# ----------------------------------------------------------------------------
def test_probe_faces_have_no_new_dotenv_dsn_reads() -> None:
    """面二零**新增**命中，且扫描面确实非空（防"指错目录也是绿"）。

    存量（`_KNOWN_LEGACY_HITS`）单列 —— 它**不是豁免**：新增一处即红；
    存量被修掉而不销账也红（否则登记表会烂在原地，变成永久后门）。
    """
    loadtest = sorted(_LOADTEST_DIR.rglob("*.py"))
    eval_tree = sorted(_EVAL_DIR.rglob("*.py"))
    assert len(loadtest) >= 5, f"deploy/loadtest 扫描面异常（{len(loadtest)} 个文件）"
    assert len(eval_tree) >= 10, f"eval 扫描面异常（{len(eval_tree)} 个文件）"

    seen = {
        f"{hit['file']}:{hit['line']}"
        for face in _PROBE_FACES
        for hit in _scan(face, dsn_scoped=True)
    }
    new = sorted(seen - _KNOWN_LEGACY_HITS)
    assert not new, (
        f"面二出现 {len(new)} 处**新增**「从 `.env` 取 DSN」：{new}\n"
        "修法：DSN 只许来自环境变量或显式参数（缺 = 具名 fail，禁字面默认值、禁 skip）。\n"
        "（存量登记只覆盖已具名的那一条，新命中的必须是修，不是加进登记表。）"
    )
    stale = sorted(_KNOWN_LEGACY_HITS - seen)
    assert not stale, (
        f"存量登记已失效：{stale} —— 说明它已被修掉（或行号漂了）。\n"
        "修掉 ⇒ 请从 `_KNOWN_LEGACY_HITS` 销账；只是行号漂 ⇒ 更新锚点。"
        "留着不销 = 把一次性存量变成永久后门。"
    )


def test_guard_bites_on_dsn_key_extraction_in_probe_face() -> None:
    """面二的正对照：读 `.env` **且**作用域内出现 DSN 键名 ⇒ 必须咬中。"""
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "def resolve() -> str:\n"
        "    env_file = Path('deploy') / '.env'\n"
        "    for line in env_file.read_text().splitlines():\n"
        "        if line.startswith('DATABASE_URL='):\n"
        "            return line.partition('=')[2]\n"
        "    return os.environ['DSN']\n"
    )
    hits = _scan_source(source, dsn_scoped=True)
    assert len(hits) == 1, hits
    assert "DSN 键名" in hits[0]["reason"]


def test_guard_spares_the_reporter_shape_by_rule_not_by_exemption() -> None:
    """面二不许咬 τ 校准块（只取 `BINDING_TAU*` 的「有没有值」）—— 靠**规则**，不靠文件白名单。

    同时证这条收窄是**承重的**：同一份源码在面一（严）规则下必须命中 1 处，
    否则 `dsn_scoped` 等于没生效（护栏空转 = 假绿）。
    """
    synthetic = (
        "import os\n"
        "import re\n"
        "\n"
        "def tau() -> dict[str, bool]:\n"
        "    env_path = os.path.join('deploy', '.env')\n"
        "    out: dict[str, bool] = {}\n"
        "    for line in open(env_path, encoding='utf-8'):\n"
        "        m = re.match(r'\\s*(BINDING_TAU[A-Z_]*)\\s*=\\s*(.*)$', line)\n"
        "        if m:\n"
        "            out[m.group(1)] = bool(m.group(2).strip())\n"
        "    return out\n"
    )
    assert _scan_source(synthetic, dsn_scoped=True) == []
    assert len(_scan_source(synthetic, dsn_scoped=False)) == 1, "收窄必须是承重的"

    real = _EVAL_DIR / "reporter.py"
    assert real.exists(), "对照件 `eval/reporter.py` 不见了 —— `docs/07:1163` 引的就是它"
    real_source = real.read_text(encoding="utf-8")
    assert _scan_source(real_source, dsn_scoped=True) == [], (
        "面二咬到了 τ 校准块的 `.env` 读取 —— 它只取 `BINDING_TAU*` 的「有没有值」，"
        "`docs/07:1163` 明写「不是本案」"
    )
    assert _scan_source(real_source, dsn_scoped=False), "严规则下它应当命中 —— 面二的收窄才有意义"
