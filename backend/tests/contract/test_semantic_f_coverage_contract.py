"""F-1…F-5 的语义覆盖契约（W8 第 48 轮）。

本文件只做离线对撞：
- 五项 F 面对应的维度/绑定必须在真实交付包里显式存在；
- 每项影响的 case_id 的 gold_sql 必须真落在该面所声明的资产/列上；
- 既有 family/level/grain_index 坐标不得被新增维度挤掉。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.binding.grain import GrainIndex, GrainRef
from app.semantics import SemanticBundleRuntime, load_bundle

REPO = Path(__file__).resolve().parents[3]
BUNDLE = REPO / "semantic" / "bundle_2026.09.14.1.yaml"
DATASET = REPO / "eval" / "dataset_v1_frozen.json"

_F_EXPECTATIONS = {
    "F-1": {
        "dimension": "sku",
        "binding": "product.sku_id",
        "case_pattern": r"\bsku_id\b",
        "cases": (
            "M-DIM-01",
            "M-ENUM-01",
            "M-ENUM-02",
            "M-ENUM-03",
            "M-ENUM-04",
            "X-STR-02",
            "X-STR-04",
        ),
    },
    "F-2": {
        "dimension": "spu",
        "binding": "product.spu_id",
        "case_pattern": r"\bspu_id\b",
        "cases": ("M-DIM-06",),
    },
    "F-3": {
        "dimension": "category",
        "binding": "product.category_l1",
        "case_pattern": r"\bv_product\b.*\bcategory_l[12]\b",
        "cases": (
            "E-ENUM-06",
            "E-ENUM-07",
            "E-ENUM-08",
            "E-ENUM-09",
            "E-ENUM-10",
            "H-CAT-01",
            "H-CAT-02",
            "H-CAT-03",
            "H-CAT-04",
            "H-CAT-05",
            "M-DIM-07",
            "M-DIM-09",
            "M-HIER-01",
            "M-HIER-02",
            "M-HIER-04",
            "M-HIER-05",
            "M-HIER-06",
            "X-ENUM-01",
            "X-ENUM-02",
            "X-ENUM-03",
            "X-ENUM-04",
            "X-ENUM-05",
            "X-ENUM-06",
            "X-ENUM-07",
            "X-ENUM-08",
            "X-MET-01",
            "X-MET-02",
            "X-MET-03",
            "X-MET-04",
            "X-MET-05",
        ),
    },
    "F-4": {
        "concept": "大区",
        "binding": "region.region_name",
        "case_pattern": r"\bv_region\b.*\bregion_name\b",
        "cases": ("E-VER-07", "M-DIM-08"),
    },
    "F-5": {
        "dimension": "campaign_type",
        "binding": "campaign.campaign_type",
        "case_pattern": r"\bcampaign_type\b",
        "cases": ("M-DIM-04",),
    },
}


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(BUNDLE))


@pytest.fixture(scope="module")
def cases() -> dict[str, dict[str, object]]:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    return {str(row["case_id"]): row for row in data["cases"]}


@pytest.mark.parametrize("face", sorted(_F_EXPECTATIONS))
def test_f_face_declares_its_dimension_binding(
    runtime: SemanticBundleRuntime, face: str
) -> None:
    expected = _F_EXPECTATIONS[face]
    if "concept" in expected:
        fb = runtime.field_binding(str(expected["concept"]))
        assert fb is not None, f"{face} 缺少字段绑定 {expected['concept']}"
        assert fb.canonical_asset == expected["binding"]
        return
    dim = runtime.dimension(str(expected["dimension"]))
    assert dim is not None, f"{face} 缺少维度 {expected['dimension']}"
    assert dim.binding == expected["binding"]


@pytest.mark.parametrize("face", sorted(_F_EXPECTATIONS))
def test_f_face_cases_have_matching_gold_sql(
    cases: dict[str, dict[str, object]], face: str
) -> None:
    expected = _F_EXPECTATIONS[face]
    pattern = re.compile(str(expected["case_pattern"]), re.IGNORECASE | re.DOTALL)
    missing = [cid for cid in expected["cases"] if not pattern.search(str(cases[cid]["gold_sql"]))]
    assert missing == [], f"{face} 的 gold_sql 未落在声明面：{missing}"


def test_category_binding_is_product_side_but_preserves_category_family(
    runtime: SemanticBundleRuntime,
) -> None:
    fb = runtime.field_binding("类目")
    assert fb is not None
    assert fb.canonical_asset == "product.category_l1"
    index = GrainIndex.build(runtime)
    assert index.level_of_ref("product.category_l1") == GrainRef(
        "category", "category_l1", 1
    )
    assert index.level_of_ref("order_paid.category_l1") == GrainRef(
        "category", "category_l1", 1
    )


def test_existing_region_level_is_not_displaced(runtime: SemanticBundleRuntime) -> None:
    region = runtime.dimension("region")
    assert region is not None
    assert region.binding == "order_paid.region_code"
    index = GrainIndex.build(runtime)
    assert index.level_of_ref("region.region_name") == GrainRef(
        "city+region", "region", 2
    )


def test_new_f_families_are_present_without_renaming_existing_ones(
    runtime: SemanticBundleRuntime,
) -> None:
    index = GrainIndex.build(runtime)
    assert index.level_of_ref("product.sku_id") == GrainRef("sku", "sku", 1)
    assert index.level_of_ref("product.spu_id") == GrainRef("spu", "spu", 1)
    assert index.level_of_ref("campaign.campaign_type") == GrainRef(
        "campaign_type", "campaign_type", 1
    )
    assert index.level_of_ref("order_paid.category_l1") == GrainRef(
        "category", "category_l1", 1
    )
    assert index.level_of_ref("region.region_name") == GrainRef(
        "city+region", "region", 2
    )
