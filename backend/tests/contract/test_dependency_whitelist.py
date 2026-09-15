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

import tomllib
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
    "uvicorn",
    "pydantic",
    "pydantic-settings",
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
