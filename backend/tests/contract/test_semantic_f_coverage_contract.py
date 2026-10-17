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


def test_region_province_metrics_carry_a_decidable_rule(
    runtime: SemanticBundleRuntime,
) -> None:
    """F-4 真死因：plan 读口径说明里的"同名根不同资产"就判 blocking ⇒ refuse。

    E-VER-07 的 gold 落在 `v_region`，而 plan 的原文 blocking 是
    「`province_cnt` 与 `province_covered_cnt` 同名根不同资产…二者不可自行择一」。
    ⇒ 口径说明必须给出**可直接执行**的判别规则，且不得留下会把模型推向
    「无法自行择一」的措辞。本测试是那条修复的防漂回钉。
    """
    for name in ("province_cnt", "province_covered_cnt"):
        m = runtime.metric(name)
        assert m is not None
        note = str(m.definition_note or "")
        assert "同名根不同资产" not in note, f"{name} 的口径说明仍含触发 blocking 的措辞"
        assert "不可自行择一" not in note, f"{name} 的口径说明仍含触发 blocking 的措辞"

    pc = str(runtime.metric("province_cnt").definition_note or "")
    assert "不需要澄清" in pc, "province_cnt 必须明说：清单口径不需要澄清"
    assert "region_name" in pc, "province_cnt 必须点明按 region_name 取"
    # E-VER-07 的原问法是「华东覆盖省份数」，判别规则必须**逐字点名**这个说法归本条，
    # 否则 plan 会把它读成 province_covered_cnt 并因缺时间范围判 blocking（实测复现）。
    assert "覆盖省份数" in pc, "province_cnt 的判别规则必须点名「覆盖省份数」归本条"


def test_province_cnt_and_covered_cnt_have_disjoint_synonyms(
    runtime: SemanticBundleRuntime,
) -> None:
    """F-4 配套：`覆盖省份数` 必须**唯一**指向 `province_cnt`。

    E-VER-07 问「华东覆盖省份数」，gold 落在 `v_region`。若这个说法同时被
    `province_covered_cnt` 的同义词覆盖，plan 会判「同名根不同资产」的口径歧义而
    `refuse(no_data_asset)` —— 这正是终版 G-2 产物里 E-VER-07 的真实死因。
    """
    def syn(name: str) -> set[str]:
        m = runtime.metric(name)
        assert m is not None, f"缺少指标 {name}"
        return {str(x) for x in m.synonyms}

    overlap = syn("province_cnt") & syn("province_covered_cnt")
    assert overlap == set(), f"两个指标的同义词不得重叠，实得 {sorted(overlap)}"
    assert "覆盖省份数" in syn("province_cnt")
    aliases = runtime.resolve_alias("覆盖省份数")
    assert aliases is not None
    assert str(getattr(aliases, "maps_to_ref", "")) == "province_cnt"


def test_region_gold_sql_faces_are_covered(
    cases: dict[str, dict[str, object]],
) -> None:
    """F-4 的**两条** gold 形态都要被覆盖（派单点名）。

    E-VER-07 = 标量（`WHERE region_name='华东'`）；M-DIM-08 = 分组（`GROUP BY region_name`）。
    只覆盖其中一条 ⇒ 另一条仍会退化成 region_code（M-DIM-08 的原始死因）。
    """
    scalar = str(cases["E-VER-07"]["gold_sql"])
    grouped = str(cases["M-DIM-08"]["gold_sql"])
    assert "v_region" in scalar and "region_name" in scalar and "group by" not in scalar.lower()
    assert "v_region" in grouped and "region_name" in grouped and "group by" in grouped.lower()


def test_dimension_region_binding_stays_order_side(
    runtime: SemanticBundleRuntime,
) -> None:
    """F-4 不许把 `dimensions.region.binding` 直接改成 region_name。

    理由：`dimensions.region` 承载 `value_map`（华东→省编码集）—— 其物化路径由
    `BundleView.value_entries()` 按 `(binding 资产, binding 列)` 展开，改列会让
    「华南」等**值检索**整条失效（见 `test_retrieval_value.py::test_value_map_route`）。
    大区名走的是别名/family 通路，不是改这个 binding。
    """
    region = runtime.dimension("region")
    assert region is not None
    assert region.binding == "order_paid.region_code"
    assert region.value_map, "value_map 必须仍在 region 维度上"
    assert "华东" in region.value_map


def test_region_name_resolves_from_alias_without_new_family(
    runtime: SemanticBundleRuntime,
) -> None:
    """F-4：`大区` 必须解析到 **region.region_name**（而不是 dimension region 的 region_code）。

    否则 M-DIM-08（GROUP BY region_name）会退化成 GROUP BY region_code，
    而 E-VER-07（WHERE region_name='华东'）连列都对不上。
    同时钉住：不得靠新增共享 `region` 层级的维度来做（那会把 family key 从
    `city+region` 改成 `city+region+region_name`）。
    """
    from app.binding.filters import resolve_concept

    res = resolve_concept("大区", runtime)
    assert res is not None, "大区 必须能解析"
    assert "region.region_name" in res.refs, f"大区 应解析到 region.region_name，实得 {res.refs}"

    index = GrainIndex.build(runtime)
    fam_keys = {fam.key for fam in index.families}
    assert "city+region" in fam_keys, f"地理族 key 被改了：{sorted(fam_keys)}"
    assert "city+region+region_name" not in fam_keys, "不得用新增共享层级的维度来解 F-4"
    assert index.level_of_ref("region.region_name") == GrainRef("city+region", "region", 2)


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


def test_g2_contract_gold_no_longer_has_frozen_conflicts(
    cases: dict[str, dict[str, object]],
) -> None:
    """第 56 轮冻结基线 v2 的防漂回钉。

    三条冲突必须同时保持：
    - E-VER-01：题面 2026-08 必须落到月份谓词；
    - E-VER-06：活动数按包内全量口径，不得重新加 normal_sale；
    - E-VER-08：事实表收货省份覆盖数必须显式带 pay_time 月份范围。
    同时保证 F-4 的 E-VER-07/M-DIM-08 仍走 v_region 且不带时间谓词。
    """
    e1 = str(cases["E-VER-01"]["gold_sql"]).lower()
    e6 = str(cases["E-VER-06"]["gold_sql"]).lower()
    e8 = str(cases["E-VER-08"]["gold_sql"]).lower()
    e7 = str(cases["E-VER-07"]["gold_sql"]).lower()
    m8 = str(cases["M-DIM-08"]["gold_sql"]).lower()

    assert "year = 2026" in e1 and "month = 8" in e1
    assert "campaign_type" not in e6
    assert "pay_time" in e8 and "2026-08-01" in e8 and "2026-09-01" in e8

    assert "v_region" in e7 and "region_name" in e7 and "pay_time" not in e7
    assert "v_region" in m8 and "group by" in m8 and "pay_time" not in m8


def test_g2_v2_frozen_baseline_is_versioned_and_locked() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    seed = json.loads((REPO / "eval" / "gold_query_seed_v1.json").read_text(encoding="utf-8"))
    assert dataset["dataset_version"] == "2"
    assert dataset["content_hash"] == (
        "sha256:31f3385f3a5da8e126cac209d1d812d09dd7c62998f60b0fdde61ac19235d7c5"
    )
    assert seed["seed_version"] == "2"
    assert seed["derived_from_content_hash"] == dataset["content_hash"]
    assert seed["content_hash"] == (
        "sha256:2f91ed51e0c97fcbb45b7a59eabc13067167747df52d5cae6d1b37cfe339a592"
    )
