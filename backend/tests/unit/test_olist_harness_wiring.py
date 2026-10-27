"""Harness 的 Olist 装配与 `run_batch` 透传（W2，`U-145`）。

W1 的缺陷：`run_batch` 构造 `Harness` 时不传 bundle/db ⇒ 图执行器恒用默认合成沙箱，
`--db` 只影响判分沙箱。本文件锁住修复后的接线：
· `Harness(bundle_path=olist, db_path=olist.db)` 真的加载 Olist 包与库；
· `run_batch(..., bundle_path=...)` 把它传进 Harness，并在返回值里记 `executor`。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OLIST_DIR = REPO_ROOT / "eval" / "olist"
BUNDLE_PATH = REPO_ROOT / "semantic" / "bundle_olist_2018.yaml"
SANDBOX_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import runner  # noqa: E402
from eval.harness import Harness  # noqa: E402


def _require_db() -> None:
    if not SANDBOX_DB.is_file():
        pytest.skip(f"sandbox_db_absent: {SANDBOX_DB}")


@pytest.fixture(scope="module")
def harness():
    _require_db()
    h = Harness(bundle_path=str(BUNDLE_PATH), db_path=str(SANDBOX_DB))
    yield h
    h.close()


def test_harness_loads_olist_bundle(harness) -> None:
    assert harness.loaded.bundle.meta.version == "2026.10.27.1"
    assert len(harness.loaded.bundle.assets) == 5
    assert len(harness.loaded.bundle.metrics) == 9
    assert harness.loaded.bundle.default_predicates == {}


def test_harness_executor_uses_olist_db(harness) -> None:
    assert Path(harness.executor._db_path) == SANDBOX_DB


def test_harness_allowlist_is_the_olist_views(harness) -> None:
    allow = harness.semantics.guard_allowlist(
        runner.identity_for_case("ALLOWLIST", "T_A"), max_rows=None
    )
    tables = set((allow.get("assets") or {}).keys())
    assert tables == {
        "v_o_orders", "v_o_order_items", "v_o_products", "v_o_payments", "v_o_reviews",
    }
    assert "v_order_paid" not in tables
    assert "orders" not in tables


def test_tenant_views_exist_and_row_count(harness) -> None:
    from sqlite_exec import open_sandbox_connection

    con = open_sandbox_connection(
        str(SANDBOX_DB),
        tenant_id="T_A",
        tenant_scoped_physicals=harness.tenant_scoped_physicals,
    )
    try:
        views = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_temp_master WHERE type = 'view' ORDER BY name"
            )
        }
        assert views == {
            "v_o_orders", "v_o_order_items", "v_o_products", "v_o_payments", "v_o_reviews",
        }
        assert con.execute("SELECT COUNT(*) FROM v_o_orders").fetchone()[0] == 99441
    finally:
        con.close()


def test_run_batch_passes_bundle_and_db_to_harness() -> None:
    _require_db()
    batch = asyncio.run(runner.run_batch(
        [],
        live=False,
        cassette="",
        mode="replay",
        db_path=str(SANDBOX_DB),
        bundle_path=str(BUNDLE_PATH),
        column_top=None,
        node_timeout_overrides=None,
    ))
    assert batch["records"] == []
    assert batch["executor"]["db_path"] == str(SANDBOX_DB)
    assert batch["executor"]["bundle_path"] == str(BUNDLE_PATH)


def test_run_batch_default_bundle_is_unchanged() -> None:
    """不传 `bundle_path` 时默认仍是合成包（默认路径不因 W2 改变）。"""
    import inspect

    params = inspect.signature(runner.run_batch).parameters
    assert "bundle_path" in params
    assert params["bundle_path"].default is None
