"""语义包只读视图 —— 检索四路共用的**已解析数据结构**（07 §6.3–6.7 的输入面）。

归属窗口：**W2B**。

## 落位理由（不是第二份 loader）

- 语义包的**加载与五步校验**归 W2A（`app/semantics/loader.py`，在制品）；
- 本模块**不读文件、不做校验**，只把"已经过校验的 bundle Mapping"解析成
  检索四路要用的只读 dataclass。谁持有 bundle 谁传入（阶段 4 由 W4 接线；
  在那之前离线脚本/测试直接 `yaml.safe_load` 后传入）。
- 只读（frozen）：检索过程不得改动语义包数据——四路都是纯读。

## 检索可用的过滤（07 §6.1 步骤④）

- 资产：`certified=True` **且** `quality_score >= quality_gates.min_quality_score`，
  不达标者**排除出检索**（不报错，降级排除）。
- 指标：`status == "active"` 才可检索（07 §6.1 版本状态机：只有可服务状态对外开放；
  本包 draft 指标 sell_through_rate 由此被排除）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "AliasInfo",
    "AssetInfo",
    "BlacklistTerm",
    "BundleView",
    "ColumnInfo",
    "JoinEdge",
    "MetricInfo",
    "ValueEntry",
    "DimensionInfo",
]


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """资产列（含同义词 / enum 值表 / 敏感标记——07 §6.4 与 §6.6 的输入）。"""

    name: str
    type: str
    comment: str
    synonyms: tuple[str, ...] = ()
    enum: Mapping[str, str] | None = None   # {枚举键: 中文标签}
    sensitive: str | None = None


@dataclass(frozen=True, slots=True)
class AssetInfo:
    """认证资产（07 §6.1 步骤④过滤后的候选池成员）。"""

    logical_name: str
    physical_asset: str
    grain: str
    domain: str
    certified: bool
    tenant_scoped: bool
    quality_score: float
    description: str
    columns: tuple[ColumnInfo, ...]

    @property
    def column_map(self) -> dict[str, ColumnInfo]:
        return {c.name: c for c in self.columns}


@dataclass(frozen=True, slots=True)
class MetricInfo:
    """指标定义（status=active 才可检索）。"""

    name: str
    display_name: str
    domain: str
    status: str
    expression: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AliasInfo:
    """扁平别名（L1 层唯一入口的源数据；本模块只搬运不做判定——判定归 W3C binding）。"""

    term: str
    lang: str
    maps_to_kind: str      # metric / asset / column / dimension / value / time
    maps_to_ref: str
    category: str


@dataclass(frozen=True, slots=True)
class BlacklistTerm:
    """黑话（§B.3.4）：action ∈ {refuse, clarify}；检索侧用它建词典 + 短路判定。"""

    term: str
    action: str
    reason: str
    alt_question: str | None = None
    clarify_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class JoinEdge:
    """认证 join 边（07 §6.5 图扩展的唯一图源；未列出的路径一律禁止）。"""

    left_asset: str
    left_column: str
    right_asset: str
    right_column: str
    join_type: str
    certified_by: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DimensionInfo:
    """维度（检索侧只消费 value_map 与 binding；grain_levels/hierarchy 归 W3C L2）。"""

    name: str
    binding: str                    # "资产.列" 形态；可为空（如 time 维度用 bindings）
    value_map: Mapping[str, tuple[str, ...]]  # {业务约定标签: 编码值集}


@dataclass(frozen=True, slots=True)
class ValueEntry:
    """值检索单条（07 §6.6 的"语义包携带的枚举/编码值表"）。

    `source` 三种来源：`enum`（列级 enum 值表）/ `alias`（aliases 中
    maps_to_kind=value 的条目）/ `value_map`（dimensions[].value_map 业务约定）。
    """

    term: str              # 用户会说出的词（中文标签 / 别名）
    asset: str             # logical asset name
    column: str            # 列名
    values: tuple[str, ...]  # 落到 SQL 侧的枚举键 / 编码值（≥1 个）
    source: str


def _split_ref(ref: str) -> tuple[str, str]:
    """`asset.column` → (asset, column)。join 边与 value_map binding 共用。"""
    asset, sep, column = ref.partition(".")
    if not sep or not asset or not column:
        raise ValueError(f"引用必须是 '资产.列' 形态：{ref!r}")
    return asset, column


def _opt_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    return str(value) if value is not None else ""


@dataclass(frozen=True, slots=True)
class BundleView:
    """语义包检索面只读视图。由 `from_mapping()` 构造，构造后不可变。"""

    version: str
    embedding_model: str
    embedding_dim: int
    assets: tuple[AssetInfo, ...]
    metrics: tuple[MetricInfo, ...]
    aliases: tuple[AliasInfo, ...]
    blacklist: tuple[BlacklistTerm, ...]
    joins: tuple[JoinEdge, ...]
    dimensions: tuple[DimensionInfo, ...]
    min_quality_score: float

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------

    @classmethod
    def from_mapping(cls, bundle: Mapping[str, Any]) -> "BundleView":
        """从（已经 W2A 校验的）bundle Mapping 构造。**本方法不做五步校验**。"""
        meta = bundle.get("meta") or {}
        embedding = meta.get("embedding") or {}
        gates = bundle.get("quality_gates") or {}

        assets = tuple(cls._parse_assets(bundle.get("assets") or []))
        metrics = tuple(cls._parse_metrics(bundle.get("metrics") or []))
        aliases = tuple(
            AliasInfo(
                term=_opt_str(a, "term"),
                lang=_opt_str(a, "lang"),
                maps_to_kind=_opt_str(a, "maps_to_kind"),
                maps_to_ref=_opt_str(a, "maps_to_ref"),
                category=_opt_str(a, "category"),
            )
            for a in (bundle.get("aliases") or [])
        )
        blacklist = tuple(
            BlacklistTerm(
                term=_opt_str(b, "term"),
                action=_opt_str(b, "action"),
                reason=_opt_str(b, "reason"),
                alt_question=(str(b["alt_question"]) if b.get("alt_question") is not None else None),
                clarify_prompt=(
                    str(b["clarify_prompt"]) if b.get("clarify_prompt") is not None else None
                ),
            )
            for b in (bundle.get("blacklist_terms") or [])
        )
        joins = tuple(cls._parse_joins(bundle.get("joins") or []))
        dimensions = tuple(cls._parse_dimensions(bundle.get("dimensions") or []))

        return cls(
            version=str(meta.get("version", "")),
            embedding_model=str(embedding.get("model", "")),
            embedding_dim=int(embedding.get("dim", 0)),
            assets=assets,
            metrics=metrics,
            aliases=aliases,
            blacklist=blacklist,
            joins=joins,
            dimensions=dimensions,
            min_quality_score=float(gates.get("min_quality_score", 0.0)),
        )

    @staticmethod
    def _parse_assets(raw: Iterable[Mapping[str, Any]]) -> list[AssetInfo]:
        out: list[AssetInfo] = []
        for a in raw:
            columns = tuple(
                ColumnInfo(
                    name=str(c.get("name", "")),
                    type=str(c.get("type", "")),
                    comment=str(c.get("comment", "")),
                    synonyms=tuple(str(s) for s in (c.get("synonyms") or [])),
                    enum=({str(k): str(v) for k, v in c["enum"].items()} if c.get("enum") else None),
                    sensitive=(str(c["sensitive"]) if c.get("sensitive") is not None else None),
                )
                for c in (a.get("columns") or [])
            )
            out.append(
                AssetInfo(
                    logical_name=str(a.get("logical_name", "")),
                    physical_asset=str(a.get("physical_asset", "")),
                    grain=str(a.get("grain", "")),
                    domain=str(a.get("domain", "")),
                    certified=bool(a.get("certified", False)),
                    tenant_scoped=bool(a.get("tenant_scoped", False)),
                    quality_score=float(a.get("quality_score", 0.0)),
                    description=str(a.get("description", "")),
                    columns=columns,
                )
            )
        return out

    @staticmethod
    def _parse_metrics(raw: Iterable[Mapping[str, Any]]) -> list[MetricInfo]:
        return [
            MetricInfo(
                name=str(m.get("name", "")),
                display_name=str(m.get("display_name", "")),
                domain=str(m.get("domain", "")),
                status=str(m.get("status", "")),
                expression=str(m.get("expression", "")),
                synonyms=tuple(str(s) for s in (m.get("synonyms") or [])),
            )
            for m in raw
        ]

    @staticmethod
    def _parse_joins(raw: Iterable[Mapping[str, Any]]) -> list[JoinEdge]:
        edges: list[JoinEdge] = []
        for j in raw:
            left_asset, left_column = _split_ref(str(j.get("left", "")))
            right_asset, right_column = _split_ref(str(j.get("right", "")))
            edges.append(
                JoinEdge(
                    left_asset=left_asset,
                    left_column=left_column,
                    right_asset=right_asset,
                    right_column=right_column,
                    join_type=str(j.get("type", "")),
                    certified_by=str(j.get("certified_by", "")),
                    note=(str(j["note"]) if j.get("note") is not None else None),
                )
            )
        return edges

    @staticmethod
    def _parse_dimensions(raw: Iterable[Mapping[str, Any]]) -> list[DimensionInfo]:
        dims: list[DimensionInfo] = []
        for d in raw:
            value_map_raw = d.get("value_map") or {}
            dims.append(
                DimensionInfo(
                    name=str(d.get("name", "")),
                    binding=str(d.get("binding", "")),
                    value_map={
                        str(label): tuple(str(v) for v in codes)
                        for label, codes in value_map_raw.items()
                    },
                )
            )
        return dims

    # ------------------------------------------------------------------
    # 查询辅助（纯读）
    # ------------------------------------------------------------------

    def asset(self, logical_name: str) -> AssetInfo | None:
        return self.asset_index().get(logical_name)

    def asset_index(self) -> dict[str, AssetInfo]:
        """logical_name → AssetInfo 索引（每次现建；8 资产规模下构建成本可忽略）。"""
        return {a.logical_name: a for a in self.assets}

    def retrievable_assets(self) -> tuple[AssetInfo, ...]:
        """通过 §6.1 步骤④质量准入的资产（未达标者降级排除，不报错）。"""
        return tuple(
            a for a in self.assets if a.certified and a.quality_score >= self.min_quality_score
        )

    def retrievable_metrics(self) -> tuple[MetricInfo, ...]:
        """status=active 的指标（draft / deprecated 不对外）。"""
        return tuple(m for m in self.metrics if m.status == _METRIC_STATUS_ACTIVE)

    def value_entries(self) -> tuple[ValueEntry, ...]:
        """值检索的全量条目（§6.6：只来自语义包，**不得**扫业务库）。"""
        entries: list[ValueEntry] = []
        for a in self.assets:
            for c in a.columns:
                if c.enum:
                    for key, label in c.enum.items():
                        entries.append(
                            ValueEntry(
                                term=label, asset=a.logical_name, column=c.name,
                                values=(key,), source="enum",
                            )
                        )
                        # 枚举键本身也是用户可能说出的值（"direct 渠道"）——
                        # 与中文标签同列登记，标签仍是主词条（排序在前由 term 字典序保证）。
                        if key != label:
                            entries.append(
                                ValueEntry(
                                    term=key, asset=a.logical_name, column=c.name,
                                    values=(key,), source="enum_key",
                                )
                            )
        for alias in self.aliases:
            if alias.maps_to_kind == "value" and "=" in alias.maps_to_ref:
                ref, _, key = alias.maps_to_ref.partition("=")
                if not key:
                    continue  # "资产.列=" 形态（空值）不构成值词条
                asset, column = _split_ref(ref)
                entries.append(
                    ValueEntry(
                        term=alias.term, asset=asset, column=column,
                        values=(key,), source="alias",
                    )
                )
        # dimensions[].value_map（业务约定映射，如 大区名 → 省编码集）：
        # binding 列取 dimensions[].binding（"资产.列" 形态）。维度原始结构
        # （grain_levels / hierarchy）由 W3C 的 L2 消费，检索侧不复制。
        for dim in self.dimensions:
            if not (dim.binding and dim.value_map):
                continue
            asset, column = _split_ref(dim.binding)
            for label, codes in dim.value_map.items():
                entries.append(
                    ValueEntry(
                        term=label, asset=asset, column=column,
                        values=codes, source="value_map",
                    )
                )
        return tuple(entries)

    def dictionary_terms(self) -> tuple[str, ...]:
        """jieba 自定义词典词源（07 §6.4）：别名 + 列级同义词 + 黑话 + enum 标签。

        去重保序（首个出现位置优先），保证词典加载顺序确定性。
        """
        seen: dict[str, None] = {}

        def add(terms: Iterable[str]) -> None:
            for t in terms:
                if t and t not in seen:
                    seen[t] = None

        add(a.term for a in self.aliases)
        for m in self.metrics:
            add(m.synonyms)  # 指标同义词（含 draft 指标——词典成词与可服务性是两回事）
        for a in self.assets:
            for c in a.columns:
                add(c.synonyms)
        add(b.term for b in self.blacklist)
        for a in self.assets:
            for c in a.columns:
                if c.enum:
                    add(c.enum.values())
        return tuple(seen)


_METRIC_STATUS_ACTIVE: Final[str] = "active"
