"""R-DEP-4（retrieval 禁 LLM，refine 唯一豁免）的防漏网断言。

背景（2026-09-16，W2B RELAY §2 Q4 提案 → W0 落笔）：
  检索链路唯一允许 LLM 的是 refine（查询改写，P0 未实现占位）。
  四路检索（dense/sparse/graph/value）+ 融合 + 分词必须确定性 ——
  它们每次请求都执行，混入 LLM = 延迟/成本不可控 + 评测不可复现。

⚠️ forbidden 契约的 source_modules 是**逐个列出的具体模块**（import-linter 不支持通配），
  新建的 retrieval 子模块若没人把它加进列表，就**自动获得 LLM 豁免**且 lint 不报错
  （r-dep-3 的第一版探针就是这么失效的）。本文件兜住这个漏网面：

  · 目录里的每个 .py（除 refine 与包 __init__）都必须出现在 R-DEP-4 的 source_modules 里；
  · refine.py 必须仍以 docstring 声明它的豁免地位（豁免是**显式决策**，不能靠沉默存在）。
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
IMPORTLINTER = BACKEND_ROOT / ".importlinter"
RETRIEVAL_DIR = BACKEND_ROOT / "app" / "retrieval"

#: 契约 id（.importlinter 里的节名，唯一标识这一条契约）。
_CONTRACT_ID = "r-dep-4-retrieval-no-llm-except-refine"
#: 刻意豁免的模块（07 §4.8：唯一允许 LLM 的检索子模块，P0 占位）。
_EXEMPT = {"refine"}


def _contract_source_modules() -> set[str]:
    """从 .importlinter 解析 R-DEP-4 的 source_modules（简单节解析，够用且无新依赖）。"""
    text = IMPORTLINTER.read_text(encoding="utf-8")
    section = re.search(
        rf"^\[importlinter:contract:{re.escape(_CONTRACT_ID)}\](.*?)(?=^\[|\Z)",
        text,
        re.M | re.S,
    )
    assert section, f".importlinter 里找不到契约 {_CONTRACT_ID} —— 它被删了？"
    body = section.group(1)
    sources = re.search(r"^source_modules\s*=\s*(.*?)(?=^\w+\s*=|\Z)", body, re.M | re.S)
    assert sources, "R-DEP-4 缺 source_modules 段"
    names = {
        line.strip()
        for line in sources.group(1).splitlines()
        if line.strip() and not line.strip().startswith((";", "#"))
    }
    return names


def test_every_retrieval_module_is_covered_by_r_dep_4() -> None:
    """目录实际文件 == 契约 source 列表 + 显式豁免 —— 新文件漏加即红。"""
    on_disk = {
        f.stem
        for f in RETRIEVAL_DIR.glob("*.py")
        if f.name != "__init__.py"
    }
    listed = {name.rsplit(".", 1)[-1] for name in _contract_source_modules()}
    listed = {n for n in listed if n.startswith("app.") is False} | {
        n.split(".")[-1] for n in _contract_source_modules() if n.startswith("app.")
    }
    missing = on_disk - listed - _EXEMPT
    extra = listed - on_disk
    assert not missing, (
        f"retrieval 下新增了模块但未加进 R-DEP-4 的 source_modules：{sorted(missing)} —— "
        f"漏加 = 该模块自动获得 LLM 豁免（forbidden 契约只检查已列出的具体模块）"
    )
    assert not extra, f"R-DEP-4 列了不存在的模块：{sorted(extra)} —— lint 会直接报错或静默失效"


def test_refine_exemption_is_declared_not_silent() -> None:
    """豁免必须是显式决策：refine.py 的 docstring 必须声明它是唯一 LLM 豁免。"""
    refine = RETRIEVAL_DIR / "refine.py"
    assert refine.exists(), "refine.py 不存在了 —— R-DEP-4 的豁免语义需要重新裁定"
    doc = refine.read_text(encoding="utf-8")[:2000]
    assert "app.llm" in doc and ("唯一" in doc or "only" in doc.lower()), (
        "refine.py 的 docstring 未声明其 '检索内唯一 LLM 豁免' 地位 —— "
        "豁免必须显式写明，否则下一个读者无法区分'有意豁免'与'漏管'"
    )


def test_r_dep_4_forbids_llm_third_party_packages() -> None:
    """forbidden 面必须覆盖第三方 LLM 栈（app.llm + langgraph/langchain/openai）。"""
    text = IMPORTLINTER.read_text(encoding="utf-8")
    section = re.search(
        rf"^\[importlinter:contract:{re.escape(_CONTRACT_ID)}\](.*?)(?=^\[|\Z)",
        text,
        re.M | re.S,
    )
    body = section.group(1)  # type: ignore[union-attr]
    for forbidden in ("app.llm", "langgraph", "langchain_core", "openai"):
        assert re.search(rf"^\s+{re.escape(forbidden)}\s*$", body, re.M), (
            f"R-DEP-4 的 forbidden_modules 缺 {forbidden} —— 第三方 LLM 栈必须显式禁入检索链路"
        )
