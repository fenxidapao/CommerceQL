"""Olist 薄语义包的结构契约（W1，`docs/07 §4.8` 的 `U-143`）。

这里锁的是**W1 自己做过的三个决定**，不是重复 runner 的校验：

1. 包能被 `app.semantics.load_bundle`（`extra="forbid"`）读完；
2. 资产 ↔ 沙箱表**同名且同列** —— `open_sandbox_connection` 建的是 `SELECT *` 的 TEMP VIEW，
   沙箱里多出的列会绕过 `policies.deny_columns` 直达结果集；
3. `order_cnt`（有效单）与 `order_cnt_all`（全状态）**不许合并**：
   前者带状态过滤、后者不带。域级 `default_predicates` 留空的前提就是这个区分。

沙箱库不在本机时（`.gitignore` 排除 `*.db`）第 2 组断言走 skip，不掩盖。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE_PATH = REPO_ROOT / "semantic" / "bundle_olist_2018.yaml"
SANDBOX_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"

EXPECTED_ASSET_COUNT = 5
EXPECTED_METRIC_COUNT = 9
EXPECTED_DIMENSION_COUNT = 4


@pytest.fixture(scope="module")
def loaded():
    from app.semantics.loader import load_bundle

    return load_bundle(str(BUNDLE_PATH))


@pytest.fixture(scope="module")
def bundle(loaded):
    return loaded.bundle


@pytest.fixture(scope="module")
def sandbox_tables() -> dict[str, tuple[str, ...]]:
    if not SANDBOX_DB.is_file():
        pytest.skip(f"sandbox_db_absent: {SANDBOX_DB}")
    con = sqlite3.connect(f"{SANDBOX_DB.resolve().as_uri()}?mode=ro", uri=True)
    try:
        names = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            name: tuple(r[1] for r in con.execute(f'PRAGMA table_info("{name}")'))
            for name in names
        }
    finally:
        con.close()


def test_counts_are_the_w1_budget(bundle) -> None:
    assert len(bundle.assets) == EXPECTED_ASSET_COUNT
    assert len(bundle.metrics) == EXPECTED_METRIC_COUNT
    assert len(bundle.dimensions) == EXPECTED_DIMENSION_COUNT


def test_default_predicates_stay_empty(bundle) -> None:
    """域级谓词会被闸门一注入该域每条查询 —— 留空是有意的（见包文件头）。"""
    assert bundle.default_predicates == {}


def test_asset_physical_names_match_sandbox_tables(bundle, sandbox_tables) -> None:
    assert {a.physical_asset for a in bundle.assets} == set(sandbox_tables)


def test_asset_columns_match_sandbox_columns_exactly(bundle, sandbox_tables) -> None:
    mismatched = {
        a.logical_name: {
            "bundle_only": sorted(set(a.column_names) - set(sandbox_tables[a.physical_asset])),
            "sandbox_only": sorted(set(sandbox_tables[a.physical_asset]) - set(a.column_names)),
        }
        for a in bundle.assets
        if set(a.column_names) != set(sandbox_tables[a.physical_asset])
    }
    assert not mismatched, mismatched


def test_tenant_scoped_iff_tenant_id_column(bundle) -> None:
    for asset in bundle.assets:
        assert asset.tenant_scoped is True, asset.logical_name
        assert asset.has_column("tenant_id"), asset.logical_name


def test_tenant_id_is_denied_everywhere(bundle) -> None:
    denied = {ref for policy in bundle.policies for ref in policy.deny_columns}
    for asset in bundle.assets:
        assert f"{asset.logical_name}.tenant_id" in denied


def test_every_metric_time_basis_is_a_real_column(bundle) -> None:
    columns = {c for a in bundle.assets for c in a.column_names}
    missing = {m.name: m.time_basis for m in bundle.metrics if m.time_basis not in columns}
    assert not missing, missing


def test_order_cnt_and_order_cnt_all_are_not_merged(bundle) -> None:
    """`order_cnt` 带状态过滤、`order_cnt_all` 不带 —— 合并会毁掉 g07。"""
    metrics = {m.name: m for m in bundle.metrics}
    filtered = metrics["order_cnt"].expression or ""
    unfiltered = metrics["order_cnt_all"].expression or ""

    assert "canceled" in filtered and "unavailable" in filtered
    assert "canceled" not in unfiltered and "unavailable" not in unfiltered
    assert "WHERE" not in unfiltered.upper()


def test_aov_expression_does_not_reference_metric_names(bundle) -> None:
    """`aov` 自含两端表达式；引用指标名会在对方改口径时静默漂移。"""
    expression = next(m for m in bundle.metrics if m.name == "aov").expression or ""
    assert "payment_value" in expression
    assert "order_id" in expression
    for other in ("gmv", "order_cnt"):
        assert other not in expression.lower()
