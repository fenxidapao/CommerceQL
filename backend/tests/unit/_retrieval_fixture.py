"""W2B 检索测试夹具助手（下划线前缀 = 非 pytest 收集，与 `_redis_fake.py` 同例）。

⚠️ 夹具纪律（本项目实测教训：夹具污染）：
- 断言"某参数被传下去了"时，夹具**不得**为同一参数提供默认值——
  本文件的 `RecordingFetcher` 会在缺 tenant/bundle_version 时**直接失败**，
  而不是替调用方补上。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from app.core.contracts import IdentityContext, Role
from app.retrieval.view import BundleView

#: 仓库根 = tests/unit/_retrieval_fixture.py 向上三级（backend/ 的上一级）。
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

BUNDLE_PATH: Path = REPO_ROOT / "semantic" / "bundle_2026.09.14.1.yaml"


def load_bundle_view() -> BundleView:
    """真实语义包 → BundleView（W1A 冻结资产，content_hash 未漂移）。"""
    with BUNDLE_PATH.open(encoding="utf-8") as fh:
        return BundleView.from_mapping(yaml.safe_load(fh))


def make_identity(tenant_id: str = "T_A") -> IdentityContext:
    return IdentityContext(
        trace_id="trace-test",
        task_id="task-test",
        session_id="session-test",
        tenant_id=tenant_id,
        user_id="user-test",
        role=Role.ANALYST,
    )


class RecordingFetcher:
    """sparse/dense 取数替身：逐字记录 (sql, params)，按预设行应答。

    ⚠️ 若 params 里缺 `tenant_id` / `bundle_version`，**断言在夹具内当场失败**——
    这是"租户过滤在 SQL 层"（N-10）的夹具侧守卫：绝不允许替调用方默认补值。
    """

    def __init__(self, rows: Sequence[Mapping[str, Any]] = ()) -> None:
        self.rows = [dict(r) for r in rows]
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def __call__(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        assert params.get("tenant_id"), "tenant_id 必须由调用方显式传入（N-10）"
        assert params.get("bundle_version"), "bundle_version 必须由调用方显式传入"
        self.calls.append((sql, dict(params)))
        return self.rows


class FakeCache:
    """CachePort 最小替身（get/set 计数；用于缓存命中与降级不缓存的断言）。"""

    def __init__(self, seed: Mapping[str, str] | None = None) -> None:
        self.store: dict[str, str] = dict(seed or {})
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ttl_s: int) -> None:
        self.set_calls += 1
        self.store[key] = value
