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

⚠️ **两个投影、两种形状，各自显式声明（U-121）**：本模块对外给**两份**白名单视图 ——
`asset_allowlist(ctx)`（**扁平** `{物理名: 条目}`，给 `planner` / `binding`）与
`guard_allowlist(ctx, *, max_rows=None)`（**7 键 wrapper**，给 `guard/ast_gate` / `guard/policy_gate`）。
二者**同源于同一份 `LoadedBundle`**；消费方**不得**互相派生（"闸门自己从扁平拼判据"正是
U-121 那条缝的成因：同一条真 SQL 在生产里必 `R05`）。形状由 `app/core/contracts.py`
（W0 冻结）声明，本模块只负责**如实产出**，不自行发明键。

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

from app.core.contracts import (
    GuardAllowlist,
    GuardAllowlistAsset,
    GuardAllowlistJoin,
    IdentityContext,
    TimeSemantics,
)
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
    """实现 `SemanticBundlePort`（`active_version` / `asset_allowlist` / `guard_allowlist` /
    `time_semantics` / `policy`；五方法是 `ae59c5c` 后的端口全量）。

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
    # SemanticBundlePort 五方法（签名与 contracts.py 逐字对齐）
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

    def guard_allowlist(
        self, ctx: IdentityContext, *, max_rows: int | None = None
    ) -> GuardAllowlist:
        """闸门判据的**唯一形状**（U-121；`asset_allowlist` 的姊妹投影）。

        7 个键**全部必填**（缺键 = 违约，见 `contracts.GuardAllowlist`；**明令禁止**
        只补 `assets` 一键 —— 那会把一条 fail-closed 换成三条 fail-open）：
        `bundle_version` / `assets` / `joins` / `deny_columns` / `default_predicates` /
        `allowed_constants` / `max_rows`。

        🔴 **`assets[]` 带两个列面，不是一个**（U-121 子事实 2 / W0 `RELAY.md` §11.1）：

        | 面 | 键 | 内容 | 谁读 |
        |---|---|---|---|
        | 可见面 | `columns` | `{列名: PG 类型}`，**已裁 `deny_columns`** | gate1 的 R06 列解析 |
        | 结构面 | `all_columns` | `{列名: PG 类型}`，**全列含 deny** | gate2 ④ 敏感列复核 / ⑤ `tenant_id` 双向断言 / R17 类型 |

        ⚠️ **两面缺一不可**，各有一副失效形态（这就是"必须两个面"的实证理由）：
        - 只给结构面（`columns` 也填全列）⇒ `deny_columns` 一旦缺，`colname in columns`
          成立 ⇒ **敏感列被放行**（fail-open；07 v1.6.4 子事实 4 那句"缺 deny 仍 fail-closed"
          **只在可见面下成立**）；
        - 只给可见面（不另立 `all_columns`）⇒ gate2 ④ **认不出** `receiver_phone` 的归属
          ⇒ 列不出表就检不出 ⇒ **越权列漏检**；且 ⑤ 在 `tenant_scoped=true` 的资产上
          **当场 `ContractViolationError`**（`tenant_id` 恰是 deny 列）——
          这是 fail-open 的一半，比崩溃更值得记。

        ⚠️ `deny_columns` **角色无关**（07 §7.4 / U-84 裁定）：`platform_admin` 也**不**回填空列。
        它表达的是"绝对拒绝"，不是"本角色能不能看"——后者才是可见面裁的那件事。

        ⚠️ `max_rows` 是**请求级事实**，语义层无从得知 ⇒ 只能由调用方经关键字传入
        （`app/graph/nodes/gate1_ast.py` 侧的 `state["options"]["max_rows"]`）。
        键**必在**，"必在"≠"必非空"：调用方未声明时**照实填 `None`** —— `ast_gate._effective_limit`
        对 `None` 已走退化分支到硬上限，**不得**拿 `GraphDeps.max_rows`（那是 `EXEC_MAX_ROWS`）冒充。

        ⚠️ `allowed_constants`：本包**没有**该声明区块（grep 实证）⇒ 给**空序列**。
        不编造，也**不省略键**（省略 = R14 少一类来源，fail-closed）。

        ⚠️ 与扁平投影的关系（**派生不变式**）：`assets[p]` 与 `asset_allowlist(ctx)[p]`
        同源于同一份 `LoadedBundle.active_assets` —— 四个标量键（`logical_name` / `domain` /
        `grain` / `tenant_scoped`）**逐值相等**，列面也**是同一个可见列集**，只是：
        ①本投影带 PG 类型（`{列名: 类型}`，扁平面给的是列名元组）、②本投影**多**一个 `all_columns`。
        两面都从 `Asset.columns` 这一份声明派生 ⇒ 结构上不可能漂移；谁要是绕过它自己拼，
        就重新制造了 U-121。
        """
        deny_applies = ctx.role.value in self._applies_to_roles

        assets: dict[str, GuardAllowlistAsset] = {}
        for logical_name, asset in self._loaded.active_assets.items():
            if deny_applies:
                visible_names = self._allowlist.get(asset.physical_asset)
                if visible_names is None:
                    continue  # 整资产被 deny 清空（与 asset_allowlist 同一取舍，§6.1④）
            else:
                visible_names = asset.column_names
            visible = frozenset(visible_names)
            assets[asset.physical_asset] = GuardAllowlistAsset(
                logical_name=logical_name,
                domain=asset.domain,
                grain=asset.grain,
                tenant_scoped=asset.tenant_scoped,
                # 两面**同源**（同一份 Asset.columns），只差"裁不裁 deny"——不是两份真相
                columns={c.name: c.type for c in asset.columns if c.name in visible},
                all_columns={c.name: c.type for c in asset.columns},
            )

        return GuardAllowlist(
            # 与 active_version() 同一读数：gate2 ① 用它判"请求锚定的口径是否已下线"（§5.7）
            bundle_version=self.active_version(),
            assets=assets,
            joins=tuple(
                GuardAllowlistJoin(
                    # 包内 `left/right` 是 `<逻辑名>.<列>`（SCHEMA §6.2），而闸门拿它跟
                    # **逻辑名**比（`ast_gate._join_verdict` 的 `pair = {left, right}` vs `left_logical`）
                    # ⇒ 必须剥掉 `.列` 后缀，否则 join 恒落 R10。
                    left=str(j.left).split(".", 1)[0],
                    right=str(j.right).split(".", 1)[0],
                    on_columns=tuple(str(c) for c in (j.on_columns or ())),
                )
                for j in self._loaded.bundle.joins
            ),
            deny_columns=self._deny_columns(),
            default_predicates=self._default_predicates(),
            allowed_constants=(),
            max_rows=max_rows,
        )

    def time_semantics(self) -> TimeSemantics:
        """时间口径 —— **只能来自语义包**（N-26）；注入 `ClockPort` 的上下文。"""
        meta = self._loaded.bundle.meta
        return TimeSemantics(
            timezone=meta.timezone,
            fiscal_year_start_month=meta.fiscal_year_start_month,
            week_starts_on=meta.week_starts_on,
        )

    def _deny_columns(self) -> tuple[str, ...]:
        """deny 列全集（`<逻辑名>.<列>` 形态，**角色无关**）。

        `policy()` 与 `guard_allowlist()` **共用本方法** —— 两处各写一遍会让
        "闸门拿到的 deny 集"与"策略面读到的 deny 集"存在漂移空间。
        """
        return tuple(sorted(self._loaded.deny_columns))

    def _default_predicates(self) -> dict[str, tuple[str, ...]]:
        """数据域 → 默认谓词 SQL 片段（同一个共用理由，见 `_deny_columns`）。"""
        return {
            domain: tuple(dp.predicate for dp in dps)
            for domain, dps in self._loaded.bundle.default_predicates.items()
        }

    def policy(self) -> Mapping[str, Any]:
        """策略透出（W2C gate 的判据源）：deny_columns / mask_rules / 谓词 / 适用角色。"""
        bundle = self._loaded.bundle
        mask_rules = tuple(
            {"column_pattern": r.column_pattern, "rule": r.rule}
            for policy in bundle.policies
            for r in policy.mask_rules
        )
        return {
            "deny_columns": self._deny_columns(),
            "applies_to_roles": tuple(sorted(self._applies_to_roles)),
            "mask_rules": mask_rules,
            "default_predicates": self._default_predicates(),
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
    # 枚举面（W3B 语义摘要渲染 / W6 覆盖度核对 的取材源）
    # ------------------------------------------------------------------
    #
    # 🔴 为什么 `metrics()` **不做状态过滤**（这是个刻意的选择，不是漏了）：
    #
    # `metric(name)` 本来就**如实返回** draft 条目 —— 消费方靠 `is_metric_active()`
    # 区分"包里没有这个指标"与"有这个指标但它没转正"，这是两种不同的处置。
    # 枚举器一旦只吐 active，这个区分就**不可表达**了：调用方再也说不出
    # "`sell_through_rate` 存在但不得引用"，只剩"当它不存在"一种处理 ——
    # 而"当它不存在"恰恰是 G-6 那个坑的形态（模型看不到 ⇒ 自己发明一个）。
    #
    # ⇒ 枚举器 = **数据面**（吐全部），可用性判定 = **调用方**的事。
    #    与 `dimensions()`（不过滤）、`assets()`（过滤，因为质量准入在 loader 就落定）
    #    的分工一致：过滤发生在**数据加载期**，不在枚举期。

    def metrics(self) -> tuple[Metric, ...]:
        """全部指标定义（**含 draft / deprecated**，按包声明序）。

        ⚠️ 契约未变：`SemanticBundlePort`（W0 冻结）自 `ae59c5c` 起有 **5** 个方法
        （`active_version` / `asset_allowlist` / `guard_allowlist` / `time_semantics` / `policy`），
        本方法与 `assets()` / `dimensions()` / `joins()` 仍**不在端口上**，属**可选能力**，
        调用方必须用 `getattr` 探测（见 `app/planner/payloads.py::_sorted_metrics`）。
        """
        return self._loaded.bundle.metrics

    def aliases(self) -> tuple[Alias, ...]:
        """全部别名条目（L1 的同一份索引之源；`term` 一对一由 loader 强制）。

        ⚠️ 这是**唯一权威**的同义词来源 —— 不要改去渲染 `Metric.synonyms`：
        两张表一旦漂移，模型看到的词形会与 `resolve_alias()` 实际能解析的对不上
        （在 L1 该命中处静默落到 L4 近似匹配）——那正是函数头文件里说的"第二份真相"。
        """
        return self._loaded.bundle.aliases

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
