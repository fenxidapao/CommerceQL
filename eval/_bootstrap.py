"""W6 评测执行器的公共底座：路径、环境默认值、冻结集完整性校验。

归属窗口：W6（docs/08 §4.1：`eval/**` 的**执行器**部分）。
⚠️ 本文件**不产生任何数据**，只做"加载 + 验真"——内容资产归 W1A。

为什么必须先验真：`dataset_v1_frozen.json` 的 `content_hash` 与 `sandbox_db_sha256`
是 N-13 的物证。哈希不符时继续跑批，产出的是一份**没有对应数据集版本**的评测报告，
而报告本身看起来完全合法 —— 这类错误只会在使用时暴露，不会在生产时暴露。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # CommerceQL/
BACKEND = os.path.join(ROOT, "backend")
DATA_DIR = os.path.join(ROOT, "data")

DATASET_PATH = os.path.join(HERE, "dataset_v1_frozen.json")
RED_TEAM_PATH = os.path.join(HERE, "red_team_cases_v1.json")
GOLD_SEED_PATH = os.path.join(HERE, "gold_query_seed_v1.json")
SANDBOX_DB = os.path.join(DATA_DIR, "ecom_sandbox.db")
BUNDLE_PATH = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")

__all__ = [
    "BUNDLE_PATH",
    "DATASET_PATH",
    "GOLD_SEED_PATH",
    "RED_TEAM_PATH",
    "SANDBOX_DB",
    "bootstrap",
    "file_sha256",
    "load_json",
    "verify_frozen_inputs",
]

_ENV_DEFAULTS = {
    # 与 tests/conftest.py 的 `_placeholder_env` 同款：让 `get_settings()` 在零真实密钥下可构造。
    # ⚠️ 两条 DSN **必须不同**：`Settings` 有交叉校验（DATABASE_URL ≠ ANALYTICS_DB_URL，
    #    否则"分析库只读"的保证失效，N-02）—— 写成同值会让构造直接抛。
    "DEEPSEEK_API_KEY": "sk-placeholder-not-a-real-key",
    "DATABASE_URL": "postgresql+psycopg://app_rw:placeholder@pg:5432/ecom",
    "ANALYTICS_DB_URL": "postgresql+psycopg://app_ro:placeholder@pg:5432/ecom",
    "APP_ENV": "dev",
    "ENABLE_RESULT_CACHE_CONFIRMED": "false",
    "SEMANTIC_BUNDLE_PATH": BUNDLE_PATH,
}


def bootstrap() -> None:
    """把 `backend/` 与 `data/generator/` 挂上 `sys.path`，并补默认环境变量。

    `data/generator/` 必须在路径上：难度分层（I-1 的"上游代码口径"）的唯一实现是
    `layering.py`，评测**复算**它而不是抄它的结论。
    """
    for path in (BACKEND, HERE, DATA_DIR, os.path.join(DATA_DIR, "generator")):
        if path not in sys.path:
            sys.path.insert(0, path)
    for key, value in _ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_frozen_inputs() -> dict[str, Any]:
    """校验冻结集三件套与沙箱库未被改动（N-13），返回可写进报告的证据块。

    只验**内容哈希**：`content_hash` 的算法归 W1A（`build_frozen_set.case_content_hash`），
    这里直接 import 它复算 —— 自己再写一遍 = 制造第二份哈希口径。
    """
    import build_frozen_set as bfs  # W1A 的唯一哈希实现（只读复用，不修改）

    dataset = load_json(DATASET_PATH)
    red_team = load_json(RED_TEAM_PATH)
    gold_seed = load_json(GOLD_SEED_PATH)

    recomputed = bfs.case_content_hash(dataset["cases"])
    db_sha = file_sha256(SANDBOX_DB)
    checks = {
        "dataset_content_hash": {
            "expected": dataset["content_hash"],
            "actual": recomputed,
            "ok": recomputed == dataset["content_hash"],
        },
        "sandbox_db_sha256": {
            "expected": dataset["sandbox_db_sha256"],
            "actual": db_sha,
            "ok": db_sha == dataset["sandbox_db_sha256"],
        },
        "red_team_content_hash_present": str(red_team.get("content_hash", "")).startswith("sha256:"),
        "gold_seed_derived_from_dataset_hash": gold_seed.get("derived_from_content_hash")
        == dataset.get("content_hash"),
    }
    checks["all_ok"] = all(
        v if isinstance(v, bool) else v["ok"] for v in checks.values()
    )
    return {
        "checks": checks,
        "dataset_version": dataset.get("dataset_version"),
        "frozen_at": dataset.get("frozen_at"),
        "n_cases": len(dataset.get("cases", [])),
        "content_hash": dataset.get("content_hash"),
        "red_team": {"content_hash": red_team.get("content_hash"), "n_cases": len(red_team.get("cases", []))},
        "gold_seed": {"content_hash": gold_seed.get("content_hash"), "n_seeds": len(gold_seed.get("seeds", []))},
    }
