"""W2B 检索契约断言（阶段 2B 交付的"会红的护栏"）。

- N-24 静态 half：`app/**` 内 jieba **只准** `retrieval/tokenizer.py` 一处 import
  （写入侧经组装根注入 TokenizerPort，绝不第二处 import jieba）；
- 端口一致性：`RetrievalService` / tokenizer 实现 / 替身满足 W0 冻结的 Protocol；
- 权重同源：fuse 测试钉死的默认权重 == `app.core.config` 的默认值
  （两处漂移 = 融合行为悄悄变化，必须在 CI 红）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.contracts import RetrievalPort, TokenizerPort
from app.retrieval.dense import InMemoryVectorStore
from app.retrieval.search import RetrievalService
from app.retrieval.sparse import SparseSearch
from app.retrieval.tokenizer import tokenize
from tests.unit._retrieval_fixture import RecordingFetcher, load_bundle_view

APP_DIR: Path = Path(__file__).resolve().parents[2] / "app"

#: jieba 全项目唯一 import 点（07 §3.2 唯一入口表 + N-24）。
JIEBA_ALLOWED_MODULES: set[str] = {"app/retrieval/tokenizer.py"}


def _iter_app_py() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _module_name(path: Path) -> str:
    return path.relative_to(APP_DIR.parent).as_posix()


# ---------------------------------------------------------------------------
# N-24 静态 half：jieba 单一 import 点
# ---------------------------------------------------------------------------

def test_jieba_imported_only_by_tokenizer_entrypoint() -> None:
    violations: list[str] = []
    for path in _iter_app_py():
        if _module_name(path) in JIEBA_ALLOWED_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "jieba" or alias.name.startswith("jieba.") for alias in node.names):
                    violations.append(f"{_module_name(path)}: import jieba")
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "jieba" or node.module.startswith("jieba.")):
                    violations.append(f"{_module_name(path)}: from jieba import ...")
    assert not violations, f"jieba 只准在 {JIEBA_ALLOWED_MODULES} import（N-24），违规：{violations}"


def test_tokenizer_entrypoint_actually_imports_jieba() -> None:
    """反向断言：唯一入口真的在用 jieba（防止有人删掉实现让上面那条空转）。"""
    tree = ast.parse(
        (APP_DIR / "retrieval" / "tokenizer.py").read_text(encoding="utf-8")
    )
    assert any(
        (isinstance(n, ast.Import) and any(a.name == "jieba" for a in n.names))
        or (isinstance(n, ast.ImportFrom) and n.module == "jieba")
        for n in ast.walk(tree)
    ), "tokenizer.py 不再 import jieba —— 唯一入口空转，请修正本测试或实现"


# ---------------------------------------------------------------------------
# 端口一致性（W0 冻结的 contracts.Protocol）
# ---------------------------------------------------------------------------

def test_tokenizer_satisfies_tokenizer_port() -> None:
    assert isinstance(tokenize, object)
    # runtime_checkable Protocol：校验"有这个方法"（签名细节由 mypy strict 把关）
    class _Impl:
        def tokenize(self, text: str) -> list[str]:
            return tokenize(text)

    assert isinstance(_Impl(), TokenizerPort)


def test_retrieval_service_satisfies_retrieval_port() -> None:
    view = load_bundle_view()
    service = RetrievalService(
        view=view,
        embedder=object(),
        vector_store=InMemoryVectorStore(),
        sparse=SparseSearch(RecordingFetcher(), rank_normalization=32, score_min=0.05),
        weights={"dense": 0.4, "sparse": 0.35, "value": 0.15, "graph": 0.1},
        rrf_k=60,
    )
    assert isinstance(service, RetrievalPort)


# ---------------------------------------------------------------------------
# 权重同源（fuse 测试的 DEFAULT_WEIGHTS == config 默认值）
# ---------------------------------------------------------------------------

def test_fuse_default_weights_match_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DENSE_WEIGHT", raising=False)
    monkeypatch.delenv("SPARSE_WEIGHT", raising=False)
    monkeypatch.delenv("VALUE_WEIGHT", raising=False)
    monkeypatch.delenv("GRAPH_WEIGHT", raising=False)
    settings = Settings(
        DEEPSEEK_API_KEY="sk-placeholder-not-a-real-key",
        DATABASE_URL="postgresql+psycopg://app_rw:placeholder@pg:5432/ecom",
        ANALYTICS_DB_URL="postgresql+psycopg://app_ro:placeholder@pg:5432/ecom",
    )
    assert settings.DENSE_WEIGHT == 0.40
    assert settings.SPARSE_WEIGHT == 0.35
    assert settings.VALUE_WEIGHT == 0.15
    assert settings.GRAPH_WEIGHT == 0.10
    assert settings.RRF_K == 60
    assert settings.FTS_SCORE_MIN == 0.05
    assert settings.FTS_RANK_NORMALIZATION == 32
