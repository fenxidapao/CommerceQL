"""迁移 0007（Olist 演示资产）的离线契约测试 —— 防迁移与语义包两份真相。

钉死：
- `semantic/bundle_olist_2018.yaml` 的 `physical_asset` 集合 = 0007 的视图集合（5 个）；
- 每个资产的列名 + 列类型逐字一致（顺序也一致）；
- 基表名 = 视图名去掉 `v_` 前缀；主键/索引列都真实存在。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml


def _load_migration_module() -> Any:
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "repo"
        / "migrations"
        / "versions"
        / "0007_olist_demo_assets.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0007", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mig() -> Any:
    return _load_migration_module()


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _bundle_assets(repo_root: Path) -> dict[str, list[tuple[str, str]]]:
    text = (repo_root / "semantic" / "bundle_olist_2018.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return {
        asset["physical_asset"]: [(col["name"], col["type"]) for col in asset["columns"]]
        for asset in data["assets"]
    }


def test_revision_chain(mig: Any) -> None:
    assert mig.revision == "0007"
    assert mig.down_revision == "0006"
    assert mig.branch_labels is None
    assert mig.depends_on is None


def test_view_set_matches_bundle_exactly(mig: Any, repo_root: Path) -> None:
    bundle = _bundle_assets(repo_root)
    mig_views = {view for view, _cols, _pk, _idx in mig._ASSETS.values()}
    assert mig_views == set(bundle), (
        "0007 的视图集合与语义包 physical_asset 不一致 —— "
        f"仅在迁移: {sorted(mig_views - set(bundle))}, "
        f"仅在 bundle: {sorted(set(bundle) - mig_views)}"
    )


def test_columns_and_types_are_verbatim(mig: Any, repo_root: Path) -> None:
    bundle = _bundle_assets(repo_root)
    for base, (_view, columns, _pk, _idx) in mig._ASSETS.items():
        physical = f"v_{base}"
        assert physical in bundle, f"{physical} 不在语义包里"
        got = [(name, pg_type) for name, pg_type, _nullable in columns]
        assert got == bundle[physical], (
            f"{physical} 的列/类型与语义包不一致：\n迁移 = {got}\n包 = {bundle[physical]}"
        )


def test_primary_keys_are_real_columns(mig: Any) -> None:
    for base, (_view, columns, pk, _idx) in mig._ASSETS.items():
        names = {name for name, _type, _nullable in columns}
        assert pk, f"{base} 没有主键"
        assert set(pk) <= names, f"{base} 的主键列不在列清单里：{sorted(set(pk) - names)}"


def test_indexes_only_reference_real_columns(mig: Any) -> None:
    for base, (_view, columns, _pk, indexes) in mig._ASSETS.items():
        names = {name for name, _type, _nullable in columns}
        for idx_name, idx_cols in indexes:
            assert idx_name.startswith("ix_o_"), f"{base} 索引命名不符 ix_o_*：{idx_name}"
            missing = set(idx_cols) - names
            assert not missing, f"{base}.{idx_name} 引用了不存在的列：{sorted(missing)}"


def test_all_assets_are_tenant_scoped(mig: Any, repo_root: Path) -> None:
    text = (repo_root / "semantic" / "bundle_olist_2018.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert all(asset["tenant_scoped"] is True for asset in data["assets"])
    for base, (_view, columns, _pk, _idx) in mig._ASSETS.items():
        names = [name for name, _type, _nullable in columns]
        assert "tenant_id" in names, f"{base} 缺 tenant_id（RLS 依据）"
