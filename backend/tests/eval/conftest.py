"""`tests/eval/` 的公共装置（D4 裁定：评测器测试放 `backend/tests/eval/`）。

为什么需要单独一个 conftest
--------------------------------------------------------------------------
`eval/**` 不在 `pythonpath` 里（`pyproject.toml` 只给了 `.`，即 `backend/`）。
这些模块本来就是**仓库根的独立批跑器**（`python eval/xxx.py` 直接跑），
让它们为了测试而改成可安装包 = 越界动 W0 的打包配置。所以这里只做一件事：
把 `CommerceQL/eval/` 与 `data/generator/` 挂上 `sys.path`。

⚠️ 顺序敏感：`_bootstrap.bootstrap()` 会顺手 `setdefault` 一套**占位环境变量**
（与 `tests/conftest.py` 同款）。这里刻意复用它而不是重抄一份 —— 两份环境默认值
迟早漂移，而漂移的表现是"某些评测测试只在某台机器上过"。
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)  # backend/tests/eval -> tests -> backend -> CommerceQL
EVAL_DIR = os.path.join(REPO_ROOT, "eval")
GENERATOR_DIR = os.path.join(REPO_ROOT, "data", "generator")

for _p in (EVAL_DIR, GENERATOR_DIR, os.path.join(REPO_ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()


@pytest.fixture(scope="session")
def repo_root() -> str:
    return REPO_ROOT


@pytest.fixture(scope="session")
def dataset() -> dict:
    """冻结集本体（只读）。任何测试想改它 —— 改不了，`content_hash` 会先在评测里炸。"""
    return _bootstrap.load_json(_bootstrap.DATASET_PATH)


@pytest.fixture(scope="session")
def dataset_cases(dataset: dict) -> list[dict]:
    return list(dataset.get("cases") or [])


@pytest.fixture(scope="session")
def sandbox_db() -> str:
    return _bootstrap.SANDBOX_DB


@pytest.fixture(scope="session")
def harness():
    """一份语义包 + 一张图 + 一个只读执行器（装配本身要花钱，且必须与评测同形）。

    ⚠️ 收口走 `await aclose()`：`ChatClient` 的 `httpx.AsyncClient` 绑在创建它的循环上，
    用同步 `close()` 了事会让后续批次的某一条报 `Event loop is closed`
    （`eval/harness.py` 的 `aclose` docstring 记的就是这个实测）。本目录不发 LLM 请求，
    但**不因此跳过**收口 —— 否则测试成了"只有评测器知道的那个坑"的豁免区。
    """
    import harness as harness_mod

    h = harness_mod.Harness()
    yield h
    asyncio.run(h.aclose())


@pytest.fixture(scope="session")
def analyst_ctx():
    """一个分析师身份（题库回放/夹具断言都用它，避免每条测试各造一份）。"""
    from harness import identity_for_case

    return identity_for_case("TEST-CONF-001", "T_A")


@pytest.fixture(scope="session")
def guard_allowlist(harness, analyst_ctx):
    """闸门实际读到的那份 allowlist = 端口的七键 `guard_allowlist`（与生产同一条路径）。"""
    return harness.semantics.guard_allowlist(analyst_ctx, max_rows=None)
