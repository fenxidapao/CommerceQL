"""粒度族索引 —— L2 粒度消歧与五步过滤第 ③ 步的**共同依据**（07 §6.8.1）。

归属窗口：W3C｜依据：07 §6.8.1、SCHEMA §3.3、PRD §6.3.1（L2 行）。

🔴 **本模块解决的是"族"这件事没有显式字段的问题。**
   语义包里每个维度都有自己的 `grain_levels`，而 `grain_level` 的**数值只在同一族内有意义**
   （`year=1` 与 `country=1` 毫无关系）。W2A 的 `SemanticBundleRuntime.same_grain` 是**纯数值比较**，
   并明确把"族归属"留给调用方保证（其 docstring 原话），因为包里没有"族"字段。
   ⇒ "族"必须由**消费方**从既有数据里**推导**，而不是新造一个字段（新造 = 第二真相）。

**推导规则（只用语义包里已有的数据，不发明任何映射表）：**

1. **族 = 一组共享层级名的维度**。两个维度共享某层级名**且细度值相等** → 同族；
   同名却给了**不同的值** → **拒绝**（`BindingBundleInconsistency`）：此时"数值相等"这个判据
   本身已失去意义，继续绑定只会产出**看起来正常的错绑定**。
   实测：`region{country=1…city=4}` 与 `city{region=2,province=3,city=4}` 共享三级且值一致 → 同族；
   `time` / `category` / `channel` / `shop` 各自成族。
2. **列 → 层级**：`<asset>.<col>` 按**四条由严到宽的规则**匹配层级名
   （`col == level` → `endswith("_"+level)` → `startswith(level+"_")` → `"_"+level+"_" in col`）。
   实测：`shop.city`(=)、`order_paid.receiver_city`(后缀)、`region.province_name`(前缀)、
   `order_paid.category_l1`(=)、`dim_date.month`(=)。**匹配到多个族 → `None`（不猜）**。
3. **问句 → 粒度词**：三个来源，全部经**公开接口**取得，不碰私有属性 ——
   ① 层级名本身（英文）；
   ② `field_bindings[].concept`（用其声明的 `grain_level` 定层级、用规范/候选资产定族；
      实测 `城市` → geog 族 `city` 层）；
   ③ 问句的 **n-gram 经 `resolve_alias` 命中**（`maps_to_kind=column` 用 `maps_to_ref` 定位，
      `maps_to_kind=dimension` 用该维度默认 `grain_level`）。实测 `省份` → `region.province_name`
      → `province` 层。
   ⚠️ 为什么用 n-gram 而不是"遍历别名全集"：`SemanticBundleRuntime` **没有暴露别名全集**
   （只有 O(1) 的 `resolve_alias(term)`），而遍历 `_loaded` 私有属性会破坏窄接口。
   n-gram 扫描（长度 ≤ 8）只用公开查口，代价是每个请求约数百次字典查询，
   换来的是"不依赖未暴露的接口"。
4. **一个词指向两个不同（族, 层级）→ 剔除并登记**（`ambiguous_words`），不取第一个。

⚠️ **07 原话"抽取失败 → 不进入 L2"是本模块的核心失效语义**：任何判不出来的情形
（列名匹配不到层级 / 词不在词汇表 / 词落在多个族 / 问句里两个粒度词指向不同层级）
**一律 `None`**，绝不默认取一个 —— 那会把"该问的问题"压成"猜错也不报错"。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.binding.errors import BindingBundleInconsistency

__all__ = [
    "GrainFamily",
    "GrainIndex",
    "GrainMatch",
    "GrainRef",
    "SemanticReader",
]

#: 问句里做 n-gram 扫描的最大词长（中文粒度词实测 ≤ 4 字；留到 8 是为了将来英文短语）。
_MAX_WORD_LEN = 8


class SemanticReader(Protocol):
    """`binding` 需要的最小语义包读面（**结构类型**，实现者 = `SemanticBundleRuntime`）。

    ⚠️ 用 Protocol 而不是直接 `import app.semantics`：`.importlinter` 其实允许 `binding`
    import `semantics`（它更低层），但本仓库既有惯例是**注入 + 窄接口**
    （`app/llm/egress_guard.py`、`app/repo/startup_assertions.py` 都注明了这一点）。
    窄接口的额外好处：单测可喂一个三行假读面，不必每次构造完整语义包。
    """

    def active_version(self) -> str: ...
    def dimensions(self) -> tuple[Any, ...]: ...
    def dimension(self, name: str) -> Any | None: ...
    def field_bindings(self) -> tuple[Any, ...]: ...
    def field_binding(self, concept: str) -> Any | None: ...
    def metric(self, name: str) -> Any | None: ...
    def is_metric_active(self, name: str) -> bool: ...
    def asset(self, logical_name: str) -> Any | None: ...
    def assets(self) -> tuple[Any, ...]: ...
    def asset_allowlist(self, ctx: Any) -> Mapping[str, Any]: ...
    def is_denied_column(self, ref: str) -> bool: ...
    def resolve_alias(self, term: str) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class GrainRef:
    """一次粒度定位：**哪个族**、**哪一级**、**细度值**。三者缺一不可。

    ⚠️ 之所以要把 `family` 一起带上：07 §6.8.1 明令"**禁止跨族比较**"。
    只带数值的接口无法阻止把 `year=1` 与 `country=1` 比出"同粒度"来。
    """

    family: str
    level: str
    value: int


@dataclass(frozen=True, slots=True)
class GrainMatch:
    """一次词级命中（词 → 粒度定位）。保留词是为了让归因可读、可回归。"""

    word: str
    grain: GrainRef


@dataclass(frozen=True, slots=True)
class GrainFamily:
    """一个粒度族：成员维度 + 层级名→细度值。"""

    key: str
    members: tuple[str, ...]
    level_values: Mapping[str, int]

    def name_of(self, value: int) -> str | None:
        """细度值 → 层级名。**族内唯一**（`grain_levels` 随 `hierarchy` 严格递增，值互不相同）。"""
        for level, level_value in self.level_values.items():
            if level_value == value:
                return level
        return None


#: 列名 → 层级名的四条匹配规则，**按列表顺序由严到宽**（顺序即优先级，不得重排）。
_MATCHERS: tuple[tuple[str, Any], ...] = (
    ("exact", lambda col, level: col == level),
    ("suffix", lambda col, level: col.endswith("_" + level)),
    ("prefix", lambda col, level: col.startswith(level + "_")),
    ("infix", lambda col, level: "_" + level + "_" in col),
)

_WHITESPACE = re.compile(r"\s+")


def _split_ref(ref: str) -> tuple[str, str] | None:
    """`<asset>.<col>` → `(asset, col)`；非列级引用（指标名 / 纯表名）返回 `None`。"""
    if ref.count(".") != 1:
        return None
    asset, col = ref.split(".", 1)
    return (asset, col) if asset and col else None


class GrainIndex:
    """从语义包**派生**的粒度索引。构建一次即可复用。

    ⚠️ 索引是**某个 bundle 版本的派生视图**：本对象持有读面引用（n-gram 解析需要现场查别名），
    因此 `bundle_version` 变更后**必须重建**（`BundleBindingService` 按 `active_version` 缓存）。
    """

    __slots__ = (
        "_ambiguous_words",
        "_families",
        "_level_by_family",
        "_reader",
        "_ref_cache",
        "_version",
        "_vocab",
    )

    def __init__(
        self,
        *,
        reader: SemanticReader,
        version: str,
        families: tuple[GrainFamily, ...],
        vocabulary: Mapping[str, GrainRef],
        ambiguous_words: tuple[str, ...],
    ) -> None:
        self._reader = reader
        self._version = version
        self._families = families
        self._vocab = dict(vocabulary)
        self._ambiguous_words = ambiguous_words
        self._level_by_family: dict[str, dict[str, GrainRef]] = {
            family.key: {
                level: GrainRef(family=family.key, level=level, value=value)
                for level, value in family.level_values.items()
            }
            for family in families
        }
        self._ref_cache: dict[str, GrainRef | None] = {}

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, reader: SemanticReader) -> GrainIndex:
        """从语义包构建索引（唯一入口）。"""
        dimensions: Sequence[Any] = reader.dimensions()
        keys = [str(d.name) for d in dimensions]
        level_values = [{str(k): int(v) for k, v in d.grain_levels.items()} for d in dimensions]

        # —— 并查集：共享同名层级且值相等 → 同族；同名却不同值 → 拒绝 ——
        parent = list(range(len(dimensions)))
        seen_value: dict[str, tuple[int, int]] = {}

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(left: int, right: int) -> None:
            root_l, root_r = find(left), find(right)
            if root_l != root_r:
                parent[max(root_l, root_r)] = min(root_l, root_r)

        for idx, levels in enumerate(level_values):
            for level, value in levels.items():
                prev = seen_value.get(level)
                if prev is None:
                    seen_value[level] = (value, idx)
                    continue
                prev_value, prev_idx = prev
                if prev_value != value:
                    raise BindingBundleInconsistency(
                        f"语义包层级刻度自相矛盾：层级 {level!r} 在维度 {keys[prev_idx]!r}"
                        f"(={prev_value}) 与 {keys[idx]!r}(={value}) 中给了不同的细度值。"
                        "grain_level 是族内刻度，判'同粒度'靠数值相等 —— 值不一致时该判据失去意义，"
                        "继续绑定会产出**看起来正常的错绑定**（07 §6.8.1）"
                    )
                union(prev_idx, idx)

        grouped: dict[int, list[int]] = {}
        for idx in range(len(dimensions)):
            grouped.setdefault(find(idx), []).append(idx)

        families: list[GrainFamily] = []
        for members in grouped.values():
            merged: dict[str, int] = {}
            for i in members:
                merged.update(level_values[i])
            families.append(
                GrainFamily(
                    key="+".join(sorted(keys[i] for i in members)),
                    members=tuple(sorted(keys[i] for i in members)),
                    level_values=dict(sorted(merged.items())),
                )
            )
        families.sort(key=lambda fam: fam.key)

        index = cls(
            reader=reader,
            version=str(reader.active_version()),
            families=tuple(families),
            vocabulary={},
            ambiguous_words=(),
        )
        vocabulary, ambiguous = index._derive_vocabulary()
        return cls(
            reader=reader,
            version=index._version,
            families=index._families,
            vocabulary=vocabulary,
            ambiguous_words=ambiguous,
        )

    # ------------------------------------------------------------------
    # 查询面
    # ------------------------------------------------------------------

    @property
    def bundle_version(self) -> str:
        """本索引派生自哪个 bundle 版本（供缓存失效判断，N-23）。"""
        return self._version

    @property
    def families(self) -> tuple[GrainFamily, ...]:
        return self._families

    @property
    def ambiguous_words(self) -> tuple[str, ...]:
        """指向多个（族, 层级）而被**剔除**的词 —— 暴露出来，不静默丢弃。"""
        return self._ambiguous_words

    def family(self, key: str) -> GrainFamily | None:
        return next((fam for fam in self._families if fam.key == key), None)

    def level_of_ref(self, ref: str) -> GrainRef | None:
        """`<asset>.<col>` → 粒度定位。**匹配不到或跨族歧义一律 `None`**（不猜）。"""
        if ref not in self._ref_cache:
            self._ref_cache[ref] = self._compute_level_of_ref(ref)
        return self._ref_cache[ref]

    def _compute_level_of_ref(self, ref: str) -> GrainRef | None:
        parts = _split_ref(ref)
        if parts is None:
            return None
        _, col = parts
        for _, matches in _MATCHERS:
            hits = [
                grain
                for levels in self._level_by_family.values()
                for level, grain in levels.items()
                if matches(col, level)
            ]
            if not hits:
                continue
            # 命中多个族 → 跨族歧义 → 不判（07 §6.8.1 禁止跨族比较）
            if len({grain.family for grain in hits}) != 1:
                return None
            # 同一优先级内仍不唯一 → 真歧义 → 不判
            return hits[0] if len(hits) == 1 else None
        return None

    # ------------------------------------------------------------------
    # 问句 → 粒度
    # ------------------------------------------------------------------

    def matches_in(self, question: str) -> tuple[GrainMatch, ...]:
        """扫出问句里全部可定位的粒度词（**全部**命中，不做取舍 —— 冲突由调用方判）。

        顺序：按词长降序（最长匹配优先），同长度按出现位置，保证结果可复现。
        """
        if not question:
            return ()
        text = _WHITESPACE.sub("", question)
        seen: set[str] = set()
        matches: list[GrainMatch] = []
        words = sorted(self._vocab, key=len, reverse=True)
        for word in words:
            if word in text and word not in seen:
                seen.add(word)
                matches.append(GrainMatch(word=word, grain=self._vocab[word]))
        # ② 词汇表未命中 → 逐 n-gram 走公开的 `resolve_alias`（最长优先）
        for length in range(_MAX_WORD_LEN, 0, -1):
            for start in range(0, max(0, len(text) - length + 1)):
                word = text[start : start + length]
                if word in seen or not word.strip():
                    continue
                grain = self._locate_word(word)
                if grain is not None:
                    seen.add(word)
                    matches.append(GrainMatch(word=word, grain=grain))
        return tuple(matches)

    def question_level(self, question: str, *, extra_words: Sequence[str] = ()) -> GrainRef | None:
        """问句 → **唯一**粒度定位。判不出或自相矛盾 → `None`（07 §6.8.1："抽取失败 → 不进入 L2"）。

        ⚠️ 两条以上命中指向**不同**（族, 层级）时返回 `None`，而不是"取最长/取第一个"：
        那种取法会把"用户其实说了两个粒度"这件事静默变成一个猜测。
        """
        matches = list(self.matches_in(question))
        for word in extra_words:
            grain = self._locate_word(word)
            if grain is not None:
                matches.append(GrainMatch(word=word, grain=grain))
        if not matches:
            return None
        first = matches[0].grain
        if any(m.grain.family != first.family or m.grain.level != first.level for m in matches):
            return None
        return first

    # ------------------------------------------------------------------
    # 词 → 粒度（词汇表 + 现场别名解析）
    # ------------------------------------------------------------------

    def _locate_word(self, word: str) -> GrainRef | None:
        """词 → 粒度定位：先查派生词汇表，再走 `resolve_alias` 现场定位。"""
        cached = self._vocab.get(word)
        if cached is not None:
            return cached
        alias = self._reader.resolve_alias(word)
        if alias is None:
            return None
        kind = str(getattr(alias, "maps_to_kind", ""))
        ref = str(getattr(alias, "maps_to_ref", ""))
        if kind == "column":
            return self.level_of_ref(ref)
        if kind == "dimension":
            dimension = self._reader.dimension(ref)
            return None if dimension is None else self._level_of_dimension(dimension)
        # asset / value / time 类**不是**粒度词来源：
        #   asset=整表、value=枚举值、time=时间表达式（粒度归时间解析），纳入会制造假命中
        return None

    def _derive_vocabulary(self) -> tuple[dict[str, GrainRef], tuple[str, ...]]:
        """派生**固定词汇表**（① 层级名 + ② `field_bindings[].concept`）。

        别名类词**不进**词汇表，改由 `_locate_word` 现场解析 —— 因为拿不到别名全集
        （见模块 docstring 规则 3 的说明）。
        """
        candidates: dict[str, list[GrainRef]] = {}

        def offer(word: str, grain: GrainRef | None) -> None:
            if not word or grain is None:
                return
            bucket = candidates.setdefault(word, [])
            if not any(g.family == grain.family and g.level == grain.level for g in bucket):
                bucket.append(grain)

        for family in self._families:
            for level, grain in self._level_by_family[family.key].items():
                offer(level, grain)

        for raw in self._reader.field_bindings():
            refs = [str(getattr(raw, "canonical_asset", "") or "")]
            refs += [str(getattr(c, "asset", "")) for c in getattr(raw, "candidates", ())]
            refs += [str(getattr(a, "asset", "")) for a in getattr(raw, "alternatives", ())]
            located = next(
                (found for ref in refs if (found := self.level_of_ref(ref)) is not None), None
            )
            offer(str(getattr(raw, "concept", "")), located)

        vocabulary: dict[str, GrainRef] = {}
        ambiguous: list[str] = []
        for word, grains in candidates.items():
            if len(grains) == 1:
                vocabulary[word] = grains[0]
            else:
                # ⚠️ 歧义词**剔除**而不是取第一个：取第一个会把"两个族都可能是它"变成一次静默误判
                ambiguous.append(word)
        return vocabulary, tuple(sorted(ambiguous))

    def _level_of_dimension(self, dimension: Any) -> GrainRef | None:
        """维度的**默认细度**（`grain_level`）→ 定位。族内值→名唯一，故可反查。"""
        default_value = getattr(dimension, "grain_level", None)
        if not isinstance(default_value, int):
            return None
        name = str(dimension.name)
        for family in self._families:
            if name not in family.members:
                continue
            level = family.name_of(default_value)
            if level is not None:
                return GrainRef(family=family.key, level=level, value=default_value)
        return None
