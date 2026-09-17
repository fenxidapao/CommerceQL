"""粒度族索引单测（W3C，N-01：离线、不连网）。

两个层次（与 `test_semantics_loader.py` 同一套路）：
- **正向**：真实交付包 `semantic/bundle_2026.09.14.1.yaml` 必须派生出预期的族与层级定位；
- **负向**：刻度自相矛盾的包必须被**拒绝**（红线：不把"判据已失效"报告成"正常工作"）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.binding.errors import BindingBundleInconsistency
from app.binding.grain import GrainIndex, GrainRef
from app.semantics import SemanticBundleRuntime, load_bundle

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


@pytest.fixture(scope="module")
def index(runtime: SemanticBundleRuntime) -> GrainIndex:
    return GrainIndex.build(runtime)


# ============================================================================
# 负向夹具：一个最小的"假读面"，用于构造真实包无法构造的坏包
# ============================================================================


@dataclass(frozen=True)
class _FakeDimension:
    name: str
    grain_levels: dict[str, int]
    grain_level: int
    binding: str = "order_paid.id"


@dataclass
class _FakeReader:
    dims: tuple[_FakeDimension, ...] = ()
    fbs: tuple[Any, ...] = field(default_factory=tuple)
    alias_map: dict[str, Any] = field(default_factory=dict)

    def active_version(self) -> str:
        return "fake.0.0.0.0"

    def dimensions(self) -> tuple[Any, ...]:
        return self.dims

    def dimension(self, name: str) -> Any | None:
        return next((d for d in self.dims if d.name == name), None)

    def field_bindings(self) -> tuple[Any, ...]:
        return self.fbs

    def field_binding(self, concept: str) -> Any | None:
        return None

    def resolve_alias(self, term: str) -> Any | None:
        return self.alias_map.get(term)


class TestFamilyDerivation:
    def test_real_bundle_families(self, index: GrainIndex) -> None:
        """实测 5 族：地理族由 `region`+`city` 合并而成（共享 province/city 且值一致）。"""
        assert {fam.key for fam in index.families} == {
            "category",
            "channel",
            "city+region",
            "shop",
            "time",
        }
        geog = index.family("city+region")
        assert geog is not None
        assert geog.members == ("city", "region")
        assert dict(geog.level_values) == {"country": 1, "region": 2, "province": 3, "city": 4}

    def test_bundle_version_is_carried(self, index: GrainIndex, runtime: SemanticBundleRuntime) -> None:
        """索引是**某版本的派生视图**（bundle 换了必须重建，N-23）。"""
        assert index.bundle_version == runtime.active_version()

    def test_no_ambiguous_words_in_real_bundle(self, index: GrainIndex) -> None:
        assert index.ambiguous_words == ()

    def test_inconsistent_scale_is_rejected(self) -> None:
        """同名层级给了不同值 → 拒绝。此时"数值相等"判据已失效，继续会静默绑错字段。"""
        reader = _FakeReader(
            dims=(
                _FakeDimension(name="a", grain_levels={"city": 4}, grain_level=4),
                _FakeDimension(name="b", grain_levels={"city": 5}, grain_level=5),
            )
        )
        with pytest.raises(BindingBundleInconsistency) as exc:
            GrainIndex.build(reader)
        assert "city" in str(exc.value)

    def test_same_name_same_value_merges_families(self) -> None:
        reader = _FakeReader(
            dims=(
                _FakeDimension(name="a", grain_levels={"city": 4}, grain_level=4),
                _FakeDimension(name="b", grain_levels={"city": 4, "province": 3}, grain_level=4),
            )
        )
        built = GrainIndex.build(reader)
        assert [fam.key for fam in built.families] == ["a+b"]


class TestLevelOfRef:
    @pytest.mark.parametrize(
        ("ref", "expected"),
        [
            ("shop.city", GrainRef("city+region", "city", 4)),
            ("order_paid.receiver_city", GrainRef("city+region", "city", 4)),
            ("order_paid.receiver_province", GrainRef("city+region", "province", 3)),
            ("region.province_name", GrainRef("city+region", "province", 3)),
            ("region.region_name", GrainRef("city+region", "region", 2)),
            ("order_paid.category_l1", GrainRef("category", "category_l1", 1)),
            ("dim_date.month", GrainRef("time", "month", 3)),
            ("traffic_daily.channel", GrainRef("channel", "channel", 1)),
            ("shop.shop_name", GrainRef("shop", "shop", 1)),
            # 匹配不到层级 → None（问句粒度判据取不到时**不猜**）
            ("product.sku_name", None),
            ("order_paid.pay_time", None),
            # 非列级引用（指标名 / 纯表名）→ None
            ("gmv", None),
            ("order_paid", None),
        ],
    )
    def test_ref_to_level(self, index: GrainIndex, ref: str, expected: GrainRef | None) -> None:
        assert index.level_of_ref(ref) == expected


class TestQuestionLevel:
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            # `城市` 来自 field_bindings[].concept（歧义概念自身就是粒度词）
            ("哪个城市卖得好", GrainRef("city+region", "city", 4)),
            ("城市维度的订单量", GrainRef("city+region", "city", 4)),
            # `省份` / `省` 来自别名（maps_to_kind=column → region.province_name）
            ("各省份的GMV", GrainRef("city+region", "province", 3)),
            ("近7天各渠道的UV", GrainRef("channel", "channel", 1)),
            # 两个粒度词指向不同层级 → **不判**（不取最长、不取第一个）
            ("各省份下各城市的销量", None),
            # 抽不到粒度词 → None；07 §6.8.1："抽取失败 → 不进入 L2"
            ("上个月GMV是多少", None),
            ("按天看GMV", None),
            ("", None),
        ],
    )
    def test_question_to_level(self, index: GrainIndex, question: str, expected: GrainRef | None) -> None:
        assert index.question_level(question) == expected

    def test_extra_words_are_merged_not_trusted_blindly(self, index: GrainIndex) -> None:
        """调用方给的粒度词与问句扫出的词**冲突**时 → 不判（两处来源都要算）。"""
        assert index.question_level("各城市的GMV", extra_words=("省份",)) is None
        assert index.question_level("各省份的GMV", extra_words=("省份",)) == GrainRef(
            "city+region", "province", 3
        )

    def test_matches_are_reported_for_diagnostics(self, index: GrainIndex) -> None:
        """命中的词要能拿到 —— "为什么判成这个粒度"必须可解释。"""
        words = {m.word for m in index.matches_in("各省份下各城市的销量")}
        assert {"省份", "城市"} <= words
