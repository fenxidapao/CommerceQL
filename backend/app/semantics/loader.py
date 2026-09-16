"""语义包加载与五步校验（07 §6.1）—— **任一步失败即拒绝启动**（fail fast，N-15）。

归属窗口：W2A（docs/08 §4.1）。装配根在拿到本模块的结果前不得宣告
`semantic_bundle_loaded` 探针健康 —— **"未接线"必须如实红灯**，沿用阶段 0 三探针原则。

五步（07 §6.1 原文顺序，不可换）：

| 步 | 内容 | 失败处理 |
|---|---|---|
| ① | 读取 YAML（`SEMANTIC_BUNDLE_PATH`） | 拒绝启动 |
| ② | Pydantic 校验 FR-12.2 的 15 类字段齐全性 | 拒绝启动 |
| ③ | 引用完整性（canonical_asset / join 两端 / synonym maps_to 等） | 拒绝启动 |
| ④ | 质量准入：未达阈值的资产**排除出检索**（不报错） | 降级排除 + 告警（WARN 收集） |
| ⑤ | 环境预检：`EMBEDDING_DIM`/`EMBEDDING_MODEL` 与 `meta.embedding` 一致 | 拒绝启动 |

**与 W1A `semantic/validate_bundle.py` 的分工**：那是作者侧独立校验器（34 项，
刻意不 import `app.*`）；本模块是运行时实现。二者不共享代码，防分叉手段 =
测试用真实 YAML 对拍其结论（`tests/unit/test_semantics_loader.py`）。

**步骤⑤ 的 jieba 子项（诚实边界）**：`retrieval/tokenizer.py`（N-24 唯一入口）归 W2B
且未交付；本模块**不 import jieba**（否则会制造第二个分词入口）。调用方可注入
`tokenizer_probe`（可调用，抛异常即失败）：注入 → 照常校验；未注入 → 步骤⑤记
**PENDING WARN（不是 PASS）**，随 `LoadedBundle.warnings` 上报。待 W2B 交付后由
装配根注入，PENDING 自动转实判。

版本状态机（§6.1）：`draft → candidate → published`，只有 `published` 可服务；
本包当前 `status: candidate` —— 运行时**如实携带**该状态，服务侧（W4 装配）据
07 §18.2 的启动顺序决定放行策略，本模块不替它放行。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml  # type: ignore[import-untyped]  # types-PyYAML 未进 dev 依赖（W0 白名单）；YAML 解析错误经 except 兜住
from pydantic import ValidationError

from app.core.errors import SemanticBundleError
from app.semantics.models import Asset, SemanticBundle

logger = logging.getLogger(__name__)

__all__ = [
    "LoadedBundle",
    "load_bundle",
    "validate_bundle_path",
]

#: 步骤⑤ jieba 子项的诚实占位文案（进 warnings，**不得**被读成 PASS）。
_TOKENIZER_PENDING: Final[str] = (
    "步骤⑤ jieba/tokenizer 子项 PENDING：tokenizer_probe 未注入"
    "（retrieval/tokenizer.py 归 W2B，未交付；本模块不 import jieba 以免制造第二入口）"
)

#: FR-12.2 的 15 类字段 → YAML 承载位的逐类核对在 `_check_fifteen_classes()`：
#: 「原子-可拆分-组合字段」由 `assets[].columns` + `metrics[].expression` 共同承载；
#: 「唯一字段绑定」= `field_bindings`（canonical_asset 的唯一性由一对一别名 + 双向互斥断言保障）。


@dataclass(frozen=True, slots=True)
class ExcludedAsset:
    """步骤④ 被排除的资产（`on_violation: exclude_from_context`）。"""

    logical_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class LoadedBundle:
    """加载完成、可被运行时消费的语义包（**不可变**）。

    `allowlist` 是 ADR-10 应用侧资产白名单的**派生产物**：
    physical_asset → 允许列（已剔除 deny_columns）。它与 DB 侧 GRANT 的
    一致性由 DoD③ 的一致性测试断言（`materialize.py` / 集成测试）。
    """

    bundle: SemanticBundle
    version: str
    #: 通过质量准入、可被检索的资产（logical_name → Asset）
    active_assets: dict[str, Asset] = field(default_factory=dict)
    #: 步骤④ 被排除的资产 + 原因（降级排除，不是错误）
    excluded_assets: tuple[ExcludedAsset, ...] = ()
    #: ADR-10 应用侧白名单：physical_asset → 允许列名（不含 deny_columns）
    allowlist: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: deny 列全集（`<logical_name>.<col>` 形态）—— AST-R07 / W2C gate1 的判据
    deny_columns: frozenset[str] = frozenset()
    #: 非阻断事项（grain_level 读法 WARN / tokenizer PENDING / 排除资产摘要）
    warnings: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return self.bundle.meta.status


# ============================================================================
# ① 读取 YAML（含重复 key 检测 —— YAML 规范允许重复 key 且后者静默覆盖前者）
# ============================================================================

class _DuplicateKeyLoader(yaml.SafeLoader):  # type: ignore[misc]  # 父类因 stubs 缺失为 Any
    """拒绝重复 key 的 SafeLoader（W1A 同款防线；两处实现、一份理由）。"""


def _no_dupes(loader: yaml.Loader, node: yaml.Node, deep: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise SemanticBundleError(f"语义包 YAML 存在重复键：{key!r}（后者会静默覆盖前者）")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes
)


def _read_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise SemanticBundleError(f"语义包文件不存在：{p}")
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SemanticBundleError(f"语义包文件不可读：{p}（{type(exc).__name__}）") from exc
    try:
        data = yaml.load(raw, Loader=_DuplicateKeyLoader)
    except yaml.YAMLError as exc:
        raise SemanticBundleError(f"语义包 YAML 解析失败：{type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise SemanticBundleError("语义包 YAML 顶层必须是映射（mapping）")
    return data


# ============================================================================
# ② 15 类字段齐全性（FR-12.2）—— pydantic 结构 + 逐类核对
# ============================================================================

def _check_fifteen_classes(bundle: SemanticBundle) -> None:
    """FR-12.2 的 15 类逐类核对（07 §6.1 步骤②）。

    结构合法性已由 pydantic 模型承担（extra=forbid / 各 model_validator）；
    这里核对的是**跨区块的类目级齐全性** —— 单个模型看不出"整包缺了一类"。
    """
    meta = bundle.meta
    problems: list[str] = []

    # 认证资产 / 数据域 / 粒度 / 时效 / Owner（5 类，承载于 assets + meta）
    if not bundle.assets:
        problems.append("认证资产（assets）为空")
    if not meta.domain:
        problems.append("数据域（meta.domain）为空")
    for a in bundle.assets:
        if not a.grain:
            problems.append(f"资产 {a.logical_name} 缺粒度（grain）")
        if not a.freshness_sla:
            problems.append(f"资产 {a.logical_name} 缺时效（freshness_sla）")
        if not a.owner:
            problems.append(f"资产 {a.logical_name} 缺 Owner")
        if a.domain not in meta.domain:
            problems.append(f"资产 {a.logical_name} 的域 {a.domain!r} ∉ meta.domain")
    # 指标公式（expression —— 非 draft 必有，模型层已拦；这里核对"至少存在一个非 draft"）
    if not any(m.status != "draft" for m in bundle.metrics):
        problems.append("全部指标均为 draft：无可用指标公式")
    # 维度层级（hierarchy + grain_levels）
    for d in bundle.dimensions:
        if not d.hierarchy or not d.grain_levels:
            problems.append(f"维度 {d.name} 缺层级或细度映射")
    # 同义词（aliases）/ 时间语义（time_semantics）/ 唯一字段绑定（field_bindings）
    if not bundle.aliases:
        problems.append("同义词表（aliases）为空")
    if not bundle.field_bindings:
        problems.append("字段绑定（field_bindings）为空")
    # 允许 Join 路径（joins）/ 方言能力（meta.dialect）/ 敏感列与脱敏规则（policies）
    if not bundle.joins:
        problems.append("允许 Join 路径（joins）为空")
    if not meta.dialect:
        problems.append("方言能力（meta.dialect）缺失")
    if not bundle.policies:
        problems.append("敏感列与脱敏规则（policies）为空")

    if problems:
        raise SemanticBundleError(
            "语义包 15 类字段齐全性校验失败（07 §6.1 步骤②）",
            detail={"missing": problems},
        )


# ============================================================================
# ③ 引用完整性
# ============================================================================

def _split_ref(ref: str) -> tuple[str, str] | None:
    """`asset.col` → (asset, col)；形态不合法返回 None。"""
    parts = ref.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _check_referential_integrity(bundle: SemanticBundle) -> list[str]:
    """步骤③。返回 warnings（非阻断）；阻断项直接抛 SemanticBundleError。"""
    warnings: list[str] = []
    assets = {a.logical_name: a for a in bundle.assets}
    metric_names = {m.name for m in bundle.metrics}
    dim_names = {d.name for d in bundle.dimensions}
    draft_metrics = {m.name for m in bundle.metrics if m.status == "draft"}

    def _col_exists(ref: str) -> bool:
        pair = _split_ref(ref)
        return pair is not None and pair[0] in assets and assets[pair[0]].has_column(pair[1])

    def _asset_exists(name: str) -> bool:
        return name in assets

    # --- field_bindings：canonical_asset / alternatives / candidates 可解析 ---
    for fb in bundle.field_bindings:
        if not fb.ambiguous:
            pair = _split_ref(fb.canonical_asset or "")
            if pair is None or not _col_exists(fb.canonical_asset or ""):
                raise SemanticBundleError(
                    f"field_binding {fb.concept!r} 的 canonical_asset "
                    f"{fb.canonical_asset!r} 不可解析（步骤③引用完整性）",
                    detail={"concept": fb.concept},
                )
        for cand in fb.candidates:
            if not _col_exists(cand.asset):
                raise SemanticBundleError(
                    f"field_binding {fb.concept!r} 的候选 {cand.asset!r} 不可解析",
                    detail={"concept": fb.concept},
                )
        for alt in fb.alternatives:
            if not _col_exists(alt.asset):
                raise SemanticBundleError(
                    f"field_binding {fb.concept!r} 的备选 {alt.asset!r} 不可解析"
                )

    # --- dimensions：绑定可解析（两种形态，SCHEMA §3.2）---
    #   单绑定 `binding`：完整 `asset.col` 引用；
    #   多绑定 `bindings`（时间维度专有）：**裸列名** —— 资产由各指标的
    #   `default_binding.asset` 决定（GMV→order_paid→pay_time；uv→traffic_daily→stat_date），
    #   这里只验证"该列在某资产上存在"，逐指标解析发生在绑定层（W3C）。
    all_column_names: set[str] = set()
    for a in bundle.assets:
        all_column_names.update(a.column_names)
    for dim in bundle.dimensions:
        if dim.binding is not None:
            if not _col_exists(dim.binding):
                raise SemanticBundleError(
                    f"维度 {dim.name!r} 的绑定 {dim.binding!r} 不可解析（步骤③）"
                )
        else:
            for grain, col in (dim.bindings or {}).items():
                if col not in all_column_names:
                    raise SemanticBundleError(
                        f"维度 {dim.name!r} 的多绑定 {grain!r}→{col!r}："
                        "列不存在于任何资产（步骤③；多绑定值为裸列名，SCHEMA §3.2）"
                    )

    # --- tenant_scoped ⇔ tenant_id 列（双向；写反 = 跨租户存在性泄露，N-07）---
    # ⚠️ 本检查是**结构断言**，必须先于 join 边的租户语义检查 —— 否则被写反的
    # 资产会让 join 检查先抛出另一条错误，真正的病灶（tenant_scoped 写反）被掩盖。
    for a in bundle.assets:
        has_tenant_col = a.has_column("tenant_id")
        if a.tenant_scoped and not has_tenant_col:
            raise SemanticBundleError(
                f"资产 {a.logical_name}: tenant_scoped=true 但不含 tenant_id 列（双向断言）"
            )
        if (not a.tenant_scoped) and has_tenant_col:
            raise SemanticBundleError(
                f"资产 {a.logical_name}: 含 tenant_id 列但 tenant_scoped=false（双向断言）"
            )

    # --- joins：两端可解析 + 危险边必须带 note ---
    for j in bundle.joins:
        for endpoint in (j.left, j.right):
            if not _col_exists(endpoint):
                raise SemanticBundleError(
                    f"join 边 {j.left} → {j.right} 的端点 {endpoint!r} 不可解析（步骤③）"
                )
        if j.on_columns and len(j.on_columns) == 2:
            left_pair, right_pair = _split_ref(j.left), _split_ref(j.right)
            if left_pair and right_pair:
                lt = next(c for c in assets[left_pair[0]].columns if c.name == left_pair[1])
                rt = next(c for c in assets[right_pair[0]].columns if c.name == right_pair[1])
                if lt.type != rt.type and not j.note:
                    raise SemanticBundleError(
                        f"join 边 {j.left} → {j.right} 两侧类型不同"
                        f"（{lt.type} vs {rt.type}）且无 note —— 会静默 0 行（SCHEMA §6.2）"
                    )
        lp, rp = _split_ref(j.left), _split_ref(j.right)
        if lp and rp:
            left_tenant_scoped = assets[lp[0]].tenant_scoped
            right_tenant_scoped = assets[rp[0]].tenant_scoped
            if (not left_tenant_scoped) and right_tenant_scoped and not j.note:
                raise SemanticBundleError(
                    f"join 边 {j.left} → {j.right} 跨租户边界（公共 → 租户资产）且无 note"
                    " —— 会跨租户扇出，聚合值静默变大（SCHEMA §6.2）"
                )

    # --- aliases：term 一对一 + maps_to 可解析 + 不指向 draft 指标 ---
    seen_terms: set[str] = set()
    for alias in bundle.aliases:
        if alias.term in seen_terms:
            raise SemanticBundleError(
                f"别名 {alias.term!r} 重复映射（L1 硬条件：term 必须一对一，SCHEMA §6.4）"
            )
        seen_terms.add(alias.term)
        kind, ref = alias.maps_to_kind, alias.maps_to_ref
        if kind == "metric":
            if ref not in metric_names:
                raise SemanticBundleError(f"别名 {alias.term!r} 指向不存在的指标 {ref!r}")
            if ref in draft_metrics:
                raise SemanticBundleError(
                    f"别名 {alias.term!r} 指向 draft 指标 {ref!r}"
                    "（L1 会把未确认口径确定性解析掉，FR-12.3）"
                )
        elif kind == "asset":
            if not _asset_exists(ref):
                raise SemanticBundleError(f"别名 {alias.term!r} 指向不存在的资产 {ref!r}")
        elif kind == "column":
            if not _col_exists(ref):
                raise SemanticBundleError(f"别名 {alias.term!r} 指向不存在的列 {ref!r}")
        elif kind == "dimension":
            if ref not in dim_names:
                raise SemanticBundleError(f"别名 {alias.term!r} 指向不存在的维度 {ref!r}")
        elif kind == "value":
            pair = _split_ref(ref)
            if pair is None:
                raise SemanticBundleError(f"别名 {alias.term!r} 的 value 引用形态非法：{ref!r}")
            v_asset, v_col = pair
            # `value` 引用形如 `traffic_daily.channel=live`，列名可能带 `=值` 后缀
            col_name = v_col.split("=", 1)[0]
            if not _col_exists(f"{v_asset}.{col_name}"):
                raise SemanticBundleError(
                    f"别名 {alias.term!r} 指向不存在的列 {v_asset}.{col_name}"
                )
        elif kind == "time":
            prefix = ref.split(":", 1)[0]
            if prefix not in {"relative", "rolling", "campaign", "compare"}:
                raise SemanticBundleError(f"别名 {alias.term!r} 的 time 引用前缀非法：{ref!r}")

    # --- column.synonyms / metric.synonyms ⊆ aliases（两处不一致 = 校验失败，SCHEMA §6.4）---
    alias_terms = seen_terms
    for a in bundle.assets:
        for coldef in a.columns:
            for syn in coldef.synonyms:
                if syn not in alias_terms:
                    raise SemanticBundleError(
                        f"资产 {a.logical_name}.{coldef.name} 的同义词 {syn!r} 不在 aliases 中"
                        "（column.synonyms ⊆ aliases，两处不一致视为校验失败）"
                    )
    for m in bundle.metrics:
        if m.status == "draft":
            # draft 指标的 synonyms **刻意不进 aliases**（进了 = L1 会把未确认口径
            # 确定性解析掉，FR-12.3）—— 故本检查对 draft 豁免（对齐 W1A 校验器结论）。
            continue
        for syn in m.synonyms:
            if syn not in alias_terms:
                raise SemanticBundleError(
                    f"指标 {m.name} 的同义词 {syn!r} 不在 aliases 中（synonyms ⊆ aliases）"
                )

    # --- policies：deny_columns 可解析；sensitive 列双向在位 ---
    deny: set[str] = set()
    for policy in bundle.policies:
        deny.update(policy.deny_columns)
    for ref in sorted(deny):
        if not _col_exists(ref):
            raise SemanticBundleError(f"policies.deny_columns 指向不存在的列：{ref!r}")
    for a in bundle.assets:
        for coldef in a.columns:
            col_ref = f"{a.logical_name}.{coldef.name}"
            if coldef.sensitive is not None and col_ref not in deny:
                raise SemanticBundleError(
                    f"敏感列 {col_ref}（sensitive={coldef.sensitive}）未进 policies.deny_columns"
                    "（敏感列双向断言，SCHEMA §2.1）"
                )

    # --- default_predicates：applies_to ⊆ 已定义指标；与 metrics[].default_predicates 双向一致 ---
    domain_predicates: dict[str, tuple[str, ...]] = {
        domain: tuple(dp.predicate for dp in dps)
        for domain, dps in bundle.default_predicates.items()
    }
    for domain, dps in bundle.default_predicates.items():
        if domain not in bundle.meta.domain:
            raise SemanticBundleError(
                f"default_predicates 的域 {domain!r} ∉ meta.domain"
            )
        for dp in dps:
            unknown = [name for name in dp.applies_to if name not in metric_names]
            if unknown:
                raise SemanticBundleError(
                    f"默认谓词 {dp.id} 的 applies_to 指向未定义指标：{unknown}"
                )
    for m in bundle.metrics:
        if m.status == "draft":
            continue
        domain_list = domain_predicates.get(m.domain, ())
        for pred in m.default_predicates:
            if pred not in domain_list:
                # 双向一致（SCHEMA §6.3）：metric 侧声明了谓词却不在域清单 → 静默漏谓词，口径算错
                raise SemanticBundleError(
                    f"指标 {m.name} 声明的谓词 {pred!r} 不在 default_predicates[{m.domain!r}] 中"
                    "（双向一致断言，SCHEMA §6.3）"
                )

    # --- blacklisting：refuse 条目给 alt_question 或至少 reason（模型层已拦 clarify）---
    return warnings


# ============================================================================
# ④ 质量准入 + ⑤ 环境预检 → LoadedBundle
# ============================================================================

def _apply_quality_gates(bundle: SemanticBundle) -> tuple[dict[str, Asset], tuple[ExcludedAsset, ...]]:
    """步骤④：未达标 → 排除出检索（不报错），原因进 excluded_assets。"""
    gates = bundle.quality_gates
    active: dict[str, Asset] = {}
    excluded: list[ExcludedAsset] = []
    for a in bundle.assets:
        reasons: list[str] = []
        if gates.min_certified and not a.certified:
            reasons.append("certified=false")
        if a.quality_score < gates.min_quality_score:
            reasons.append(f"quality_score={a.quality_score} < {gates.min_quality_score}")
        if gates.require_owner and not a.owner:
            reasons.append("缺 Owner")
        if reasons:
            excluded.append(ExcludedAsset(logical_name=a.logical_name, reason="；".join(reasons)))
        else:
            active[a.logical_name] = a
    return active, tuple(excluded)


def load_bundle(
    path: str | Path,
    *,
    embedding_model: str | None = None,
    embedding_dim: int | None = None,
    tokenizer_probe: Callable[[], None] | None = None,
) -> LoadedBundle:
    """五步校验并加载语义包。失败抛 `SemanticBundleError`（→ 启动期拒绝启动）。

    `tokenizer_probe`：步骤⑤ 的 jieba 子项注入点（W2B 交付后由装配根注入）；
    未注入 → 记 PENDING WARN，**不谎报通过**。
    """
    # —— 步骤①：读取 ——
    data = _read_yaml(path)

    # —— 步骤②：结构校验（15 类齐全性含其中；pydantic extra=forbid 兼任"已删字段未复活"负向断言）——
    try:
        bundle = SemanticBundle.model_validate(data)
    except ValidationError as exc:
        errors = [
            {"loc": ".".join(str(x) for x in e["loc"]), "msg": e["msg"]}
            for e in exc.errors()
        ]
        raise SemanticBundleError(
            "语义包结构校验失败（07 §6.1 步骤②；extra 键 = 已删字段复活或多余字段）",
            detail={"errors": errors[:20]},
        ) from exc
    _check_fifteen_classes(bundle)

    # —— 步骤③：引用完整性 ——
    warnings: list[str] = list(_check_referential_integrity(bundle))

    # —— 步骤④：质量准入（降级排除，不是错误）——
    active, excluded = _apply_quality_gates(bundle)
    for ex in excluded:
        warnings.append(f"步骤④ 排除资产 {ex.logical_name}：{ex.reason}（exclude_from_context）")

    # —— 步骤⑤：环境预检 ——
    emb = bundle.meta.embedding
    if embedding_dim is not None and embedding_dim != emb.dim:
        raise SemanticBundleError(
            f"EMBEDDING_DIM={embedding_dim} 与 meta.embedding.dim={emb.dim} 不一致"
            "（07 §6.1 步骤⑤：维度变更 = 版本递增 + 重建索引，不得改代码硬凑）"
        )
    if embedding_model is not None and embedding_model != emb.model:
        raise SemanticBundleError(
            f"EMBEDDING_MODEL={embedding_model!r} 与 meta.embedding.model={emb.model!r} 不一致"
        )
    if tokenizer_probe is not None:
        try:
            tokenizer_probe()
        except Exception as exc:
            raise SemanticBundleError(
                f"tokenizer_probe 校验失败（07 §6.1 步骤⑤）：{type(exc).__name__}"
            ) from exc
    else:
        warnings.append(_TOKENIZER_PENDING)

    # —— allowlist 派生（ADR-10 应用侧白名单）——
    deny_all: set[str] = set()
    for policy in bundle.policies:
        deny_all.update(policy.deny_columns)
    allowlist: dict[str, tuple[str, ...]] = {}
    for name, asset in active.items():
        cols = tuple(
            c.name for c in asset.columns if f"{asset.logical_name}.{c.name}" not in deny_all
        )
        if not cols:
            # 整资产被 deny 清空 = 白名单里留一个"空壳资产"只会误导下游（gate1 / 检索）
            warnings.append(
                f"资产 {name} 的全部列均在 deny_columns 中，已从 allowlist 剔除"
            )
            continue
        allowlist[asset.physical_asset] = cols

    logger.warning(
        "semantic bundle loaded: version=%s status=%s assets=%d excluded=%d warnings=%d",
        bundle.meta.version, bundle.meta.status, len(active), len(excluded), len(warnings),
    )
    return LoadedBundle(
        bundle=bundle,
        version=bundle.meta.version,
        active_assets=active,
        excluded_assets=excluded,
        allowlist=allowlist,
        deny_columns=frozenset(deny_all),
        warnings=tuple(warnings),
    )


async def validate_bundle_path(
    path: str | Path,
    *,
    embedding_model: str | None = None,
    embedding_dim: int | None = None,
    tokenizer_probe: Callable[[], None] | None = None,
) -> None:
    """启动断言注入物（`repo/startup_assertions.evaluate_semantic_bundle(validator=...)` 的形态）。

    成功 = 静默返回；失败 = 抛 `SemanticBundleError`（由 W1B 的断言链如实上报为 FAIL）。
    **接线动作在 `app/main.py`（W1B 组装根）** —— 本模块只提供注入物，不自行接线。
    """
    load_bundle(
        path,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        tokenizer_probe=tokenizer_probe,
    )
