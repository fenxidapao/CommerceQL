"""语义层运行时 —— `SemanticBundlePort` 的实现（07 附-1 / §6.8 的数据面）。

归属窗口：W2A（docs/08 §4.1）。签名**原样实现** `app/core/contracts.py` 的端口，
不改名、不增删方法 —— 端口是 W0 冻结的单一真相。

职责边界（防"顺手多做"）：

| 本模块做 | 本模块**不做**（归谁） |
|---|---|
| 别名/概念/维度/谓词的 **O(1) 确定性查找**（L1/L2/L3 的数据面） | 从问句抽词（分词 → W2B `tokenizer.py`，N-24 唯一入口） |
| 按角色裁剪资产白名单（ADR-10 应用侧） | 判定绑定四态（→ W3C `binding/four_layer.py`） |
| `TimeSemantics` 注出（N-26：时间口径只来自语义包） | 时间区间解析（→ W3/W4 按本口径执行） |
| deny / mask / 谓词的策略透出（§7.4 / §8.7 的判据） | SQL 判定（→ W2C guard） |

⚠️ **确定性纪律（N-01 / R-DEP-2）**：本模块禁 import `app.llm`，且**没有任何方法**
调外部服务 —— 同一输入恒同一输出，离线可测。

⚠️ **版本与切换（§6.2）**：实例持有**一个**已加载版本（索引随实例构建，实例视为
不可变 —— 不要原地改索引）。版本切换 = Redis 单键 `semantic:active_version` 原子
SET + 进程内换绑新 `LoadedBundle`（失效清单 §6.2 的"订阅版本变更事件重载"）——
换绑编排归 W4 装配；本模块提供 `with_bundle()` 派生新实例，不提供原地改。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.contracts import IdentityContext, TimeSemantics
from app.semantics.loader import LoadedBundle
from app.semantics.models import (
    Alias,
    Asset,
    BlacklistTerm,
    Dimension,
    FieldBinding,
    Metric,
    MetricDefaultBinding,
)

__all__ = ["SemanticBundleRuntime"]


class SemanticBundleRuntime:
    """实现 `SemanticBundlePort`（`active_version` / `asset_allowlist` / `time_semantics` / `policy`）。

    另暴露 L1/L2/L3 与黑话的确定性查找面 —— W2B（检索）、W2C（gate1 白名单/谓词）、
    W3C（绑定四层的 L1–L3 数据）、W4（`resolved_terms` 填充）都从这里取数，
    **不得**各自再解析 YAML（那会制造第二份真相）。
    """

    __slots__ = (
        "_alias_index",
        "_allowlist",
        "_applies_to_roles",
        "_blacklist",
        "_dimensions",
        "_field_bindings",
        "_loaded",
        "_metrics",
    )

    # 类级注解（仅声明，不赋值 —— 与 __slots__ 兼容；mypy 由此获得类型）
    _loaded: LoadedBundle
    _alias_index: dict[str, Alias]
    _field_bindings: dict[str, FieldBinding]
    _metrics: dict[str, Metric]
    _dimensions: dict[str, Dimension]
    _blacklist: dict[str, BlacklistTerm]
    _allowlist: dict[str, tuple[str, ...]]
    _applies_to_roles: frozenset[str]

    def __init__(self, loaded: LoadedBundle) -> None:
        self._loaded = loaded
        self._alias_index = {a.term: a for a in loaded.bundle.aliases}
        self._field_bindings = {fb.concept: fb for fb in loaded.bundle.field_bindings}
        self._metrics = {m.name: m for m in loaded.bundle.metrics}
        self._dimensions = {d.name: d for d in loaded.bundle.dimensions}
        self._blacklist = {b.term: b for b in loaded.bundle.blacklist_terms}
        self._allowlist = dict(loaded.allowlist)
        roles: set[str] = set()
        for policy in loaded.bundle.policies:
            roles.update(policy.applies_to_roles)
        self._applies_to_roles = frozenset(roles)

    # ------------------------------------------------------------------
    # SemanticBundlePort 四方法（签名与 contracts.py 逐字对齐）
    # ------------------------------------------------------------------

    def active_version(self) -> str:
        """当前服务版本（§6.2 单键指针的进程内读数）。

        ⚠️ 包的**真实 status** 由 `bundle_status()` 提供 —— 本包当前 candidate，
        `published` 转正走人工发布（FR-12.3），运行时**不替发布流程放行**。
        """
        return self._loaded.version

    def bundle_status(self) -> str:
        """版本状态机读数（draft→candidate→published；只有 published 可服务，§6.1）。"""
        return self._loaded.status

    def asset_allowlist(self, ctx: IdentityContext) -> Mapping[str, Any]:
        """ADR-10 应用侧资产白名单，按 `ctx.role` 裁剪 deny_columns。

        裁剪规则**逐字执行语义包声明**（`policies[].applies_to_roles`）：
        角色在清单内 → deny 列被剔除；不在（当前即 `platform_admin`）→ 全列。
        返回形状：`{physical_asset: {logical_name, columns, grain, domain, tenant_scoped}}`。
        ⚠️ 被步骤④排除的资产**不在本表**（exclude_from_context，§6.1④）。
        """
        deny_applies = ctx.role.value in self._applies_to_roles
        result: dict[str, Any] = {}
        for logical_name, asset in self._loaded.active_assets.items():
            cols = self._allowlist.get(asset.physical_asset)
            if cols is None:
                continue  # 整资产被 deny 清空（loader 已记 WARN）
            if not deny_applies:
                cols = asset.column_names
            result[asset.physical_asset] = {
                "logical_name": logical_name,
                "columns": cols,
                "grain": asset.grain,
                "domain": asset.domain,
                "tenant_scoped": asset.tenant_scoped,
            }
        return result

    def time_semantics(self) -> TimeSemantics:
        """时间口径 —— **只能来自语义包**（N-26）；注入 `ClockPort` 的上下文。"""
        meta = self._loaded.bundle.meta
        return TimeSemantics(
            timezone=meta.timezone,
            fiscal_year_start_month=meta.fiscal_year_start_month,
            week_starts_on=meta.week_starts_on,
        )

    def policy(self) -> Mapping[str, Any]:
        """策略透出（W2C gate 的判据源）：deny_columns / mask_rules / 谓词 / 适用角色。"""
        bundle = self._loaded.bundle
        mask_rules = tuple(
            {"column_pattern": r.column_pattern, "rule": r.rule}
            for policy in bundle.policies
            for r in policy.mask_rules
        )
        return {
            "deny_columns": tuple(sorted(self._loaded.deny_columns)),
            "applies_to_roles": tuple(sorted(self._applies_to_roles)),
            "mask_rules": mask_rules,
            "default_predicates": {
                domain: tuple(dp.predicate for dp in dps)
                for domain, dps in bundle.default_predicates.items()
            },
        }

    # ------------------------------------------------------------------
    # L1 —— 别名确定性命中（07 §6.8 表 L1 行：命中且唯一映射 → resolved_unique）
    # ------------------------------------------------------------------

    def resolve_alias(self, term: str) -> Alias | None:
        """term → 别名条目（O(1)）。未命中返回 None（**不得**在此层做模糊匹配 —— 那是 L4 的事）。"""
        return self._alias_index.get(term)

    def resolve_terms(self, terms: tuple[str, ...] | list[str]) -> tuple[dict[str, str], ...]:
        """批量命中，产出 `graph/state.py` 组 2 `resolved_terms` 的形状
        `[{surface, canonical, kind}]`（state.py 注明该形状由 W2A 定义，U-24 回填物）。

        `canonical` = `<maps_to_kind>:<maps_to_ref>`；黑话命中**不进** resolved_terms
        （拒答/澄清走 `unresolved_terms` + intent，黑话查 `lookup_blacklist`）。
        """
        resolved: list[dict[str, str]] = []
        for term in terms:
            alias = self._alias_index.get(term)
            if alias is not None:
                resolved.append(
                    {"surface": term, "canonical": f"{alias.maps_to_kind}:{alias.maps_to_ref}",
                     "kind": alias.category}
                )
        return tuple(resolved)

    # ------------------------------------------------------------------
    # L2 —— 维度与族内粒度（07 §6.8.1）
    # ------------------------------------------------------------------

    def dimension(self, name: str) -> Dimension | None:
        return self._dimensions.get(name)

    def dimensions(self) -> tuple[Dimension, ...]:
        return self._loaded.bundle.dimensions

    @staticmethod
    def same_grain(level_a: int, level_b: int) -> bool:
        """L2 判"是否同粒度"：**数值相等**（同族内比较）。

        ⚠️ 只能在**同族**维度间调用 —— 跨族的数值相等毫无意义（`year=1` vs `country=1`）。
        族归属由调用方保证（候选来自同一族字段时才比较）；本方法**刻意**不做族检查，
        因为"族"在包里没有显式字段（U-34 范围），发明一个就是制造第二真相。
        ⚠️ 用 **grain_level 数值**，不用 `hierarchy` 数组下标 —— 用下标会把
        `city(4)` 与 `shop(1)` 误判成不同粒度，真歧义被漏判（SCHEMA §3.3 硬约束①）。
        """
        return level_a == level_b

    # ------------------------------------------------------------------
    # L3 —— 默认口径（canonical_asset / default_binding），**必须披露**（U-26）
    # ------------------------------------------------------------------

    def field_binding(self, concept: str) -> FieldBinding | None:
        """概念 → 字段绑定条目。`ambiguous=true` 条目**如实返回**（歧义判定归 W3C 四层）。"""
        return self._field_bindings.get(concept)

    def field_bindings(self) -> tuple[FieldBinding, ...]:
        return self._loaded.bundle.field_bindings

    def metric(self, name: str) -> Metric | None:
        """指标定义。draft 指标**可查但不可用** —— 消费方必须先过 `is_metric_active`。"""
        return self._metrics.get(name)

    def is_metric_active(self, name: str) -> bool:
        """draft 指标**不可被检索使用**（§6.1 版本状态机；未定义的指标不得被生成）。"""
        m = self._metrics.get(name)
        return m is not None and m.status == "active"

    def metric_default_binding(self, name: str) -> MetricDefaultBinding | None:
        """L3 指标层：`{asset, reason}`。draft 指标恒 None（draft 不参与 L3）。"""
        m = self._metrics.get(name)
        if m is None or m.status != "active":
            return None
        return m.default_binding

    def predicates_for_metric(self, name: str) -> tuple[str, ...]:
        """指标的默认谓词（默认口径的一部分，生成 SQL 时必须拼入）。"""
        m = self._metrics.get(name)
        return m.default_predicates if m is not None else ()

    # ------------------------------------------------------------------
    # 黑话（附录 B §B.3.4：拒答/澄清的确定性判据）
    # ------------------------------------------------------------------

    def lookup_blacklist(self, term: str) -> BlacklistTerm | None:
        """命中黑话 → `refuse`（渲染为 refuse 态 + 审计，**不是 error**）或 `clarify`。"""
        return self._blacklist.get(term)

    # ------------------------------------------------------------------
    # 资产面（gate1 / 检索 / W2D 的判据源）
    # ------------------------------------------------------------------

    def asset(self, logical_name: str) -> Asset | None:
        """仅返回**通过质量准入**的资产；被排除资产等同不存在（exclude_from_context）。"""
        return self._loaded.active_assets.get(logical_name)

    def assets(self) -> tuple[Asset, ...]:
        return tuple(self._loaded.active_assets.values())

    def is_denied_column(self, ref: str) -> bool:
        """`<logical>.<col>` 是否在 deny_columns（AST-R07 判据，W2C 用）。"""
        return ref in self._loaded.deny_columns

    def joins(self) -> tuple[Any, ...]:
        """允许 Join 路径全集（W2C gate1 R10/R11 / W2B 图扩展的唯一合法来源）。"""
        return self._loaded.bundle.joins

    def warnings(self) -> tuple[str, ...]:
        """加载期非阻断事项（tokenizer PENDING / 排除资产等）—— **调用方必须透出，不得吞**。"""
        return self._loaded.warnings

    # ------------------------------------------------------------------
    # 版本切换（§6.2 的进程内侧；Redis 指针写入在 materialize.py）
    # ------------------------------------------------------------------

    def with_bundle(self, loaded: LoadedBundle) -> SemanticBundleRuntime:
        """换绑新版本（派生新实例）。由装配根在指针变更事件后调用。"""
        return SemanticBundleRuntime(loaded)
