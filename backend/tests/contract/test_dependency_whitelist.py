"""契约断言：依赖白名单（07 ADR-20 + 附录 D §D.2.1）。

归属窗口：W0（docs/08 §3.1）。`backend/pyproject.toml` 的注释里点名了本文件，
故它是脚手架的一部分，不是后来补的。

为什么依赖需要"断言"而不是"约定"：
  ADR-20 的原文是"新增依赖必须先在 07 ADR-20 的表格登记并说明用途"。
  没有机器检查，"我顺手装个 xx 库"就会让契约失效 —— 而附录 D §D.2.4 明确
  排除了 torch / faiss / chromadb 等 2–3GB 级依赖（本机 8GB 显存 + 磁盘预算）。
  本文件把白名单变成**双录账**：加依赖必须同时改 pyproject 与本文件，
  这个"摩擦"是有意设计的，它强迫改动者去读 ADR-20。
"""

from __future__ import annotations

import ast
import sys
import tomllib
from functools import lru_cache
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _normalize(requirement: str) -> str:
    """`uvicorn[standard]>=0.32` → `uvicorn`（去 extras / 版本约束 / 环境标记）。"""
    name = requirement.split(";", 1)[0].strip()
    for sep in ("[", ">", "<", "=", "!", "~", " "):
        name = name.split(sep, 1)[0]
    return name.strip().lower().replace("_", "-")


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with _PYPROJECT.open("rb") as fp:
        return tomllib.load(fp)


@pytest.fixture(scope="module")
def dep_groups(pyproject: dict) -> dict[str, set[str]]:
    project = pyproject["project"]
    groups: dict[str, set[str]] = {
        "main": {_normalize(d) for d in project.get("dependencies", [])}
    }
    for group, reqs in (project.get("optional-dependencies") or {}).items():
        groups[group] = {_normalize(d) for d in reqs}
    return groups


# ---------------------------------------------------------------------------
# 1. ADR-20 / 附录 D §D.2.4：明确排除的重型依赖
# ---------------------------------------------------------------------------
# 这些**任何**依赖组都不得出现（包括 dev / eval）：
#   - 省 2–3GB+ 冗余下载；
#   - 本机 RTX 4060 Laptop 8GB 显存，torch 生态会把 CI 与本地都拖垮；
#   - 07 明确用 sqlglot 做解析、用 pgvector 做向量、用 httpx 直连 OpenAI 兼容端点，
#     因此 transformers / chromadb / faiss / openai SDK 都是**架构上不需要**的。

_FORBIDDEN = {
    # 深度学习栈
    "torch",
    "torchvision",
    "torchaudio",
    "sentence-transformers",
    "transformers",
    # 检索/向量库（生产用 pgvector，评测不需要额外向量库）
    "rank-bm25",
    "bm25s",
    "faiss-cpu",
    "faiss-gpu",
    "chromadb",
    "qdrant-client",
    "pymilvus",
    # 被 httpx 取代
    "openai",
    "anthropic",
    # 绘图/分析（评测期若确需 pandas，只许进 eval 组）
    "matplotlib",
    "seaborn",
    "plotly",
    "numpy",
    "scikit-learn",
}


@pytest.mark.parametrize("group", ["main", "dev", "eval"])
def test_forbidden_packages_absent(dep_groups: dict[str, set[str]], group: str) -> None:
    hit = sorted(dep_groups.get(group, set()) & _FORBIDDEN)
    assert not hit, (
        f"`{group}` 组出现 ADR-20 / 附录 D §D.2.4 明确排除的依赖：{hit} → "
        f"必须先改 07 ADR-20 表格并说明用途，再改 pyproject 与本断言"
    )


def test_no_group_escapes_the_check(dep_groups: dict[str, set[str]]) -> None:
    """防"新建一个没被参数化覆盖的依赖组偷偷塞重型包"。"""
    assert set(dep_groups) == {"main", "dev", "eval"}, (
        f"出现了未被禁止清单覆盖的依赖组：{sorted(set(dep_groups) - {'main', 'dev', 'eval'})}"
    )


# ---------------------------------------------------------------------------
# 2. 双录账：主依赖集合必须与附录 D §D.2.1 白名单逐项一致
# ---------------------------------------------------------------------------
# 这里**故意**写得死板：任何新增/删除都会让本测试红掉，从而强制走 ADR-20 登记流程。

_EXPECTED_MAIN = {
    "fastapi",
    "starlette",       # U-37：FastAPI 的 ASGI 底座；PRD §11 的 SSE 走 StreamingResponse（starlette 类）
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    # ── 以下 5 项是 U-37：**由"幽灵依赖"补登为显式依赖**（详见 pyproject 同名注释）──
    # 共同特征：项目代码**直接 import** 它们，但此前它们只作为别人的传递依赖存在。
    # 之所以必须补登：pip show 的 Required-by 指向的是**上游**，上游一改，我们的 import 静默消失。
    "python-dotenv",   # pydantic-settings 的 .env 读取全靠它；契约测试直接用它复现行尾注释陷阱
    "pyyaml",          # 语义包格式 = YAML（07 §6.1① / §3.2 loader.py）；3 处直接 import
    "psycopg-pool",    # 三池装配直接 import psycopg_pool（W1B 在 pools.py 头部主动提出）
    "cryptography",    # jwks.py 直接 import（虽 pyjwt[crypto] 已间接声明，直接 import 就应直接声明）
    "langgraph",
    "langgraph-checkpoint-postgres",
    "langchain-core",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "pgvector",
    "sqlglot",
    "redis",
    "httpx",
    "tenacity",
    "pyjwt",
    "structlog",
    "jieba",
    "tiktoken",
    "orjson",
}

_EXPECTED_DEV = {
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "import-linter",
    "ruff",
    "mypy",
    "respx",
}

_EXPECTED_EVAL = {"pandas"}


def test_main_dependencies_match_whitelist(dep_groups: dict[str, set[str]]) -> None:
    added = sorted(dep_groups["main"] - _EXPECTED_MAIN)
    removed = sorted(_EXPECTED_MAIN - dep_groups["main"])
    assert not added, f"主依赖新增了未登记项：{added} → 按 ADR-20 先登记再落白名单"
    assert not removed, f"主依赖缺少已登记项：{removed}"


def test_dev_dependencies_match_whitelist(dep_groups: dict[str, set[str]]) -> None:
    assert dep_groups.get("dev") == _EXPECTED_DEV


def test_eval_dependencies_are_isolated(dep_groups: dict[str, set[str]]) -> None:
    """ADR-20：评测期若确需 pandas，须**单独建组**，不得进主依赖。"""
    assert dep_groups.get("eval") == _EXPECTED_EVAL
    assert not (dep_groups.get("eval", set()) & dep_groups["main"])


# ---------------------------------------------------------------------------
# 3. 阶段 0 可运行性所必需的工具必须在 dev 组
# ---------------------------------------------------------------------------

def test_import_linter_present(dep_groups: dict[str, set[str]]) -> None:
    """R-DEP-1 / R-DEP-2 的强制手段。缺了它，`.importlinter` 只是一份文档。"""
    assert "import-linter" in dep_groups.get("dev", set())


def test_test_runner_present(dep_groups: dict[str, set[str]]) -> None:
    assert "pytest" in dep_groups.get("dev", set())


# ---------------------------------------------------------------------------
# 4. 解释器版本与 Python 版本下限
# ---------------------------------------------------------------------------

def test_requires_python_is_at_least_312(pyproject: dict) -> None:
    """附录 D §D.2.3 要求 >=3.12（3.12 起 `StrEnum` / `tomllib` / 类型参数语法齐备）。"""
    import re

    spec = pyproject["project"]["requires-python"]
    match = re.search(r">=\s*3\.(\d+)", spec)
    assert match, f"无法解析 requires-python：{spec}"
    assert int(match.group(1)) >= 12, f"requires-python={spec} 低于附录 D §D.2.3 的 3.12 下限"


def test_package_name_is_commerceql(pyproject: dict) -> None:
    assert pyproject["project"]["name"] == "commerceql"


# ---------------------------------------------------------------------------
# 5. 不声明不存在的 readme（否则 `pip install .` 直接失败）
# ---------------------------------------------------------------------------

def test_readme_not_declared_at_stage0(pyproject: dict) -> None:
    """仓库根 `README.md` 按 docs/08 §4.1 归属权归上游窗口，阶段 0 不创建它。

    若 pyproject 声明 `readme = "README.md"` 而文件不存在，`pip install .` 会立即失败 ——
    这是阶段 0 已经踩过并修掉的一次真实故障，故留断言防复发。
    """
    project = pyproject["project"]
    if "readme" not in project:
        return
    declared = project["readme"]
    target = declared if isinstance(declared, str) else declared.get("file", "")
    assert (_PYPROJECT.parent / target).exists(), (
        f"pyproject 声明了 readme={target}，但文件不存在 → `pip install .` 会失败"
    )


# ---------------------------------------------------------------------------
# 6. ★ 幽灵依赖检测：**直接 import 的第三方包必须在 pyproject 里声明**
# ---------------------------------------------------------------------------
# 本节补的是上面第 2 节的**结构性盲区**：
#   `_EXPECTED_MAIN` 是"pyproject 集合 vs 硬编码集合"的比对 —— 它只能发现
#   "pyproject 被人改了"，**发现不了"代码 import 了什么"**。
#   于是出现了一类静默缺陷：代码直接 import，pyproject 却没声明，靠"某个上游恰好也依赖它"活着。
#
# 真实来历（2026-09-16）：一次性扫出 **5 个**同形态缺陷 ——
#   pyyaml（3 处）/ psycopg-pool（3 处）/ cryptography（2 处）/ starlette（1 处）/ python-dotenv（1 处），
#   全部是"传递依赖冒充直接依赖"。其中 pyyaml 已被实测证明会**硬崩**：
#   用不含传递依赖的解释器跑 semantic/validate_bundle.py → `FATAL: PyYAML 不可用`。
#
# 为什么必须机器检查而不是写纪律：这类缺陷**本机永远复现不出来**（venv 里恰好都有），
#   只在"干净环境首次安装"或"上游换实现"时爆发 —— 而那时已经离现场很远了。
# （所需 import 已集中在文件头，遵守 E402。）


@lru_cache(maxsize=1)
def _module_to_distributions() -> dict[str, list[str]]:
    """顶层模块名 → 拥有它的发行版名。**必须缓存**。

    `packages_distributions()` 要遍历 site-packages 里每个 dist-info 的 RECORD，
    实测单次约 200ms。本文件要对它做数百次判定（每个 import × 每个文件），
    不缓存会让这个契约测试从 0.1s 涨到 **24s**（实测）—— 契约测试一旦慢下来，
    就会被人用 `-k "not ..."` 跳过，护栏随之失效。

    ⚠️ 这张表是**当前解释器实际装了什么**的快照，不是 pyproject 的声明。
    这正是本检测的价值：它判的是"代码能不能在**这个**环境里跑"，
    而 `_EXPECTED_MAIN` 判的是"有没有按 ADR-20 登记"。两者互补，缺一不可。
    """
    return packages_distributions()

#: 仓库内一方包（不按发行版解析）
_FIRST_PARTY = {"app", "tests", "scripts"}

#: 扫描范围：仓库里**我们自己写的** Python。注意用的是仓库根相对路径。
_SCAN_ROOTS = (
    "backend/app",
    "backend/tests",
    "backend/scripts",
    "semantic",
    "data",
    "eval",
)


def _top_level_imports(source: str) -> set[str]:
    """取一段源码里出现的**顶层**模块名（`a.b.c` → `a`）。

    - 相对 import（`from .x import y`）跳过：它不可能是第三方；
    - 函数内的延迟 import **照收** —— 延迟 import 同样构成依赖，
      只是把失败时机从"启动时"推到了"第一次调用时"，更难查，更该拦。
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".", 1)[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def _judge_import(module: str, declared: set[str], first_party: set[str]) -> str | None:
    """`None` = 合规；否则返回**违规原因**（字符串本身就是要给修改者的提示）。"""
    if module in sys.stdlib_module_names:
        return None
    if module in first_party:
        return None
    distributions = {_normalize(d) for d in _module_to_distributions().get(module, ())}
    if not distributions:
        return "无法解析到任何**已安装**的发行版（包名拼错？还是根本没装？）"
    if distributions & declared:
        return None
    return f"未声明（它属于发行版 {sorted(distributions)}，但 pyproject 里没有）"


def test_detector_is_not_vacuous() -> None:
    """**正向对照**：证明上面的检测器真的会红，而不是一个恒绿的摆设。

    没有这一条，"检测器写错了（比如 AST 没走对、判定恒返回 None）"与
    "代码真的干净"是**无法区分**的 —— 那正是本项目最贵的一类故障。
    """
    # ① 提取器：必须能抓 Import / ImportFrom / 函数内延迟 import / 带点模块名
    sample = (
        "import yaml\n"
        "from cryptography.hazmat.primitives import hashes\n"
        "import json, os.path\n"
        "from . import relative_should_be_skipped\n"
        "def f():\n"
        "    import psycopg_pool\n"
    )
    assert _top_level_imports(sample) == {"yaml", "cryptography", "json", "os", "psycopg_pool"}, (
        "提取器漏抓或误抓 → 检测结果不可信"
    )

    # ② 判定器：人造违规**必须**被拒；人造合规**必须**放行
    assert _judge_import("totally_not_a_real_module_xyz", set(), set()) is not None
    assert _judge_import("yaml", declared=set(), first_party=set()) is not None, (
        "模块能解析到发行版、但该发行版未声明 → 必须判违规"
    )
    assert _judge_import("yaml", declared={"pyyaml"}, first_party=set()) is None
    assert _judge_import("json", declared=set(), first_party=set()) is None, "stdlib 必须放行"
    assert _judge_import("app", declared=set(), first_party={"app"}) is None, "一方包必须放行"


def test_no_undeclared_third_party_imports(pyproject: dict, dep_groups: dict[str, set[str]]) -> None:
    """项目自身代码里**不允许**出现未声明的第三方 import。

    失败时怎么修（两条路，别选第三条）：
      1. 确实需要 → 按 ADR-20 登记，然后改 `pyproject.toml` 与本文件 `_EXPECTED_MAIN`；
      2. 不需要（比如只是为了图省事）→ 删掉那个 import，改用已声明的库或标准库。
      ❌ 第三条路"反正都装着，先放着"= 把缺陷留给"干净环境首次安装"那一刻。
    """
    declared: set[str] = set().union(*dep_groups.values())
    repo_root = _PYPROJECT.parent.parent

    scanned: list[Path] = []
    for rel in _SCAN_ROOTS:
        root = repo_root / rel
        if root.exists():
            scanned += sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    assert scanned, f"扫描范围为空的检查等于没检查（_SCAN_ROOTS={_SCAN_ROOTS}）"

    #: 一方模块名：包名 + 仓库内可直接 import 的裸模块（如 data/generator/layering.py）
    first_party = set(_FIRST_PARTY) | {p.stem for p in scanned}

    violations: dict[str, list[str]] = {}
    for path in scanned:
        source = path.read_text(encoding="utf-8")
        for module in sorted(_top_level_imports(source)):
            reason = _judge_import(module, declared, first_party)
            if reason:
                violations.setdefault(f"{module} —— {reason}", []).append(
                    str(path.relative_to(repo_root)).replace("\\", "/")
                )

    assert not violations, (
        "以下第三方模块被直接 import，却未在 pyproject 中声明（正在靠传递依赖苟活）：\n"
        + "\n".join(f"  · {k}\n      出现于 {sorted(v)}" for k, v in sorted(violations.items()))
    )
