"""语义包加载器与运行时单测（W2A，N-01：离线、不连网）。

两个层次：
- **正向**：真实交付包 `semantic/bundle_2026.09.14.1.yaml` 必须全绿加载，
  且关键派生物（allowlist / deny / 别名一对一）与 W1A 校验器结论对拍；
- **负向**：坏包必须拒绝启动（红线：不把"未校验"报告成"已加载"）。
  用真实包**定向变异**构造坏包 —— 每条负向用例对应 SCHEMA v1.1 的一条硬约束。
"""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.core.errors import SemanticBundleError
from app.semantics import (
    SemanticBundleRuntime,
    load_bundle,
    validate_bundle_path,
)

REAL_BUNDLE = (
    Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
)


@pytest.fixture(scope="module")
def real_yaml() -> dict[str, Any]:
    with REAL_BUNDLE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture()
def bundle_writer(tmp_path: Path, real_yaml: dict[str, Any]) -> Iterator[Any]:
    """写一个（可变异的）YAML 到临时文件，返回路径。"""
    counter = {"n": 0}

    def _write(mutate: Any = None) -> Path:
        data = deepcopy(real_yaml)
        if mutate is not None:
            mutate(data)
        counter["n"] += 1
        p = tmp_path / f"bundle_mut_{counter['n']}.yaml"
        p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return p

    yield _write


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


def _identity(role: Role = Role.ANALYST) -> IdentityContext:
    return IdentityContext(
        trace_id="t", task_id="k", session_id="s",
        tenant_id="T_A", user_id="u1", role=role,
    )


# ============================================================================
# 正向：真实包必须全绿
# ============================================================================

class TestRealBundle:
    def test_loads_green(self) -> None:
        loaded = load_bundle(REAL_BUNDLE)
        assert loaded.version == "2026.09.14.1"
        assert loaded.status == "candidate"
        # 8 资产全部过质量门槛（W1A：quality_score 全部 ≥ 0.90）
        assert len(loaded.active_assets) == 8
        assert loaded.excluded_assets == ()

    def test_step5_tokenizer_pending_is_not_pass(self) -> None:
        """诚实边界：tokenizer 未注入 → PENDING WARN，**不得**被读成通过。"""
        loaded = load_bundle(REAL_BUNDLE)
        assert any("PENDING" in w and "tokenizer" in w for w in loaded.warnings)

    def test_step5_tokenizer_probe_injected(self) -> None:
        loaded = load_bundle(REAL_BUNDLE, tokenizer_probe=lambda: None)
        assert not any("PENDING" in w for w in loaded.warnings)

    def test_step5_tokenizer_probe_failure_rejects(self) -> None:
        def _broken() -> None:
            raise RuntimeError("jieba 词典加载失败（模拟）")

        with pytest.raises(SemanticBundleError, match="tokenizer_probe"):
            load_bundle(REAL_BUNDLE, tokenizer_probe=_broken)

    def test_allowlist_derived(self) -> None:
        loaded = load_bundle(REAL_BUNDLE)
        # 8 资产 → 8 个物理视图都在 allowlist
        assert set(loaded.allowlist) == {
            "v_order_paid", "v_order_refund", "v_product", "v_shop",
            "v_region", "v_campaign", "v_traffic_daily", "v_dim_date",
        }
        # deny 列被剔除
        assert "receiver_phone" not in loaded.allowlist["v_order_paid"]
        assert "tenant_id" not in loaded.allowlist["v_order_paid"]
        assert "cost_price" not in loaded.allowlist["v_product"]
        # 非敏感列仍在
        assert "pay_amount" in loaded.allowlist["v_order_paid"]

    def test_deny_columns_complete(self) -> None:
        loaded = load_bundle(REAL_BUNDLE)
        # YAML policies：5 个租户 tenant_id + receiver_phone + receiver_address + cost_price
        assert loaded.deny_columns == frozenset({
            "order_paid.receiver_phone", "order_paid.receiver_address",
            "product.cost_price",
            "order_paid.tenant_id", "order_refund.tenant_id", "product.tenant_id",
            "shop.tenant_id", "traffic_daily.tenant_id", "campaign.tenant_id",
        })

    async def test_validate_bundle_path_passes(self) -> None:
        """启动断言注入物（W1B 插槽形态）：通过 = 静默返回。"""
        await validate_bundle_path(REAL_BUNDLE)


# ============================================================================
# 负向：坏包必须拒绝启动（每条 = SCHEMA v1.1 的一条硬约束）
# ============================================================================

class TestNegativeBundles:
    def test_missing_required_section(self, bundle_writer: Any) -> None:
        def mutate(d: dict[str, Any]) -> None:
            del d["aliases"]

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_revived_asset_grain_level(self, bundle_writer: Any) -> None:
        """已删字段复活（07 §4.7.1 负向断言）→ 结构校验直接红。"""
        def mutate(d: dict[str, Any]) -> None:
            d["assets"][0]["grain_level"] = 3

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_meta_disclosure_text_revived(self, bundle_writer: Any) -> None:
        def mutate(d: dict[str, Any]) -> None:
            d["meta"]["disclosure_text"] = "不该回来的字段"

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_metric_default_binding_time_field_revived(self, bundle_writer: Any) -> None:
        """`default_binding` 必须恰好 {asset, reason}（time_field 已删，07 §4.7.1）。"""
        def mutate(d: dict[str, Any]) -> None:
            d["metrics"][0]["default_binding"]["time_field"] = "pay_time"

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_ambiguous_with_canonical_asset(self, bundle_writer: Any) -> None:
        """双向互斥：ambiguous=true ⇒ 无 canonical_asset / default_reason。"""
        def mutate(d: dict[str, Any]) -> None:
            for fb in d["field_bindings"]:
                if fb.get("ambiguous"):
                    fb["canonical_asset"] = "shop.city"
                    fb["default_reason"] = "占位假值"

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_non_ambiguous_missing_default_reason(self, bundle_writer: Any) -> None:
        def mutate(d: dict[str, Any]) -> None:
            for fb in d["field_bindings"]:
                if not fb.get("ambiguous"):
                    del fb["default_reason"]
                    break

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_ambiguous_candidates_different_grain(self, bundle_writer: Any) -> None:
        """同粒度不同语义才需要澄清；候选粒度不同 → 澄清率虚高（SCHEMA §5.3）。"""
        def mutate(d: dict[str, Any]) -> None:
            for fb in d["field_bindings"]:
                if fb.get("ambiguous"):
                    fb["candidates"][0]["grain_level"] = 2

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_grain_level_drift(self, bundle_writer: Any) -> None:
        """grain_level != grain_levels[hierarchy[-1]] → 防漂移断言红。"""
        def mutate(d: dict[str, Any]) -> None:
            d["dimensions"][0]["grain_level"] = 2

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_draft_metric_with_default_binding(self, bundle_writer: Any) -> None:
        """draft 指标不得有 default_binding（draft 不参与 L3）。"""
        def mutate(d: dict[str, Any]) -> None:
            for m in d["metrics"]:
                if m["status"] == "draft":
                    m["default_binding"] = {"asset": "order_paid", "reason": "不该存在"}

        with pytest.raises(SemanticBundleError, match="结构校验失败"):
            load_bundle(bundle_writer(mutate))

    def test_alias_to_draft_metric(self, bundle_writer: Any) -> None:
        """别名指向 draft 指标 → L1 会把未确认口径确定性解析掉（FR-12.3）。"""
        def mutate(d: dict[str, Any]) -> None:
            d["aliases"].append(
                {"term": "动销", "lang": "zh", "maps_to_kind": "metric",
                 "maps_to_ref": "sell_through_rate", "category": "metric"}
            )

        with pytest.raises(SemanticBundleError, match="draft"):
            load_bundle(bundle_writer(mutate))

    def test_duplicate_alias_term(self, bundle_writer: Any) -> None:
        """L1 硬条件：term 必须一对一。"""
        def mutate(d: dict[str, Any]) -> None:
            d["aliases"].append(dict(d["aliases"][0]))

        with pytest.raises(SemanticBundleError, match="一对一"):
            load_bundle(bundle_writer(mutate))

    def test_column_synonym_not_in_aliases(self, bundle_writer: Any) -> None:
        """column.synonyms ⊆ aliases（两处不一致视为校验失败，SCHEMA §6.4）。"""
        def mutate(d: dict[str, Any]) -> None:
            d["assets"][0]["columns"][1]["synonyms"] = ["子订单号", "凭空同义词"]

        with pytest.raises(SemanticBundleError, match="不在 aliases"):
            load_bundle(bundle_writer(mutate))

    def test_sensitive_column_not_denied(self, bundle_writer: Any) -> None:
        """敏感列双向断言：sensitive 标记必须同时出现在 deny_columns。"""
        def mutate(d: dict[str, Any]) -> None:
            for p in d["policies"]:
                if "deny_columns" in p:
                    p["deny_columns"] = [
                        c for c in p["deny_columns"] if c != "order_paid.receiver_phone"
                    ]

        with pytest.raises(SemanticBundleError, match="敏感列"):
            load_bundle(bundle_writer(mutate))

    def test_tenant_scoped_without_tenant_column(self, bundle_writer: Any) -> None:
        """tenant_scoped=true ⇔ 含 tenant_id 列（双向；写反 = 跨租户存在性泄露）。"""
        def mutate(d: dict[str, Any]) -> None:
            d["assets"][0]["tenant_scoped"] = False  # 仍含 tenant_id 列 → 反向红

        with pytest.raises(SemanticBundleError, match="双向断言"):
            load_bundle(bundle_writer(mutate))

    def test_join_cross_tenant_edge_without_note(self, bundle_writer: Any) -> None:
        """跨租户边界 / 跨类型的危险边必须带 note（缺 note = 会静默算错）。"""
        def mutate(d: dict[str, Any]) -> None:
            for j in d["joins"]:
                if "dim_date.campaign_id" in j["left"]:
                    del j["note"]

        with pytest.raises(SemanticBundleError, match="跨租户边界"):
            load_bundle(bundle_writer(mutate))

    def test_join_type_mismatch_without_note(self, bundle_writer: Any) -> None:
        def mutate(d: dict[str, Any]) -> None:
            for j in d["joins"]:
                if j["left"] == "order_paid.pay_time":
                    del j["note"]

        with pytest.raises(SemanticBundleError, match="类型不同"):
            load_bundle(bundle_writer(mutate))

    def test_metric_predicate_not_in_domain(self, bundle_writer: Any) -> None:
        """谓词↔metric 双向一致（SCHEMA §6.3：只查一个方向会静默漏谓词）。"""
        def mutate(d: dict[str, Any]) -> None:
            for m in d["metrics"]:
                if m["name"] == "gmv":
                    m["default_predicates"].append("is_test_order = true")

        with pytest.raises(SemanticBundleError, match="双向一致"):
            load_bundle(bundle_writer(mutate))

    def test_dangling_canonical_asset(self, bundle_writer: Any) -> None:
        def mutate(d: dict[str, Any]) -> None:
            for fb in d["field_bindings"]:
                if fb["concept"] == "渠道":
                    fb["canonical_asset"] = "traffic_daily.not_a_column"

        with pytest.raises(SemanticBundleError, match="不可解析"):
            load_bundle(bundle_writer(mutate))

    def test_embedding_dim_mismatch(self) -> None:
        with pytest.raises(SemanticBundleError, match="EMBEDDING_DIM"):
            load_bundle(REAL_BUNDLE, embedding_dim=768)

    def test_embedding_model_mismatch(self) -> None:
        with pytest.raises(SemanticBundleError, match="EMBEDDING_MODEL"):
            load_bundle(REAL_BUNDLE, embedding_model="nomic-embed-text")

    def test_missing_file(self) -> None:
        with pytest.raises(SemanticBundleError, match="不存在"):
            load_bundle("/nonexistent/bundle.yaml")

    def test_duplicate_yaml_key(self, real_yaml: dict[str, Any], tmp_path: Path) -> None:
        """YAML 重复 key 后者静默覆盖前者 —— 必须在读取层拦下。"""
        p = tmp_path / "dupe.yaml"
        p.write_text("meta:\n  version: '1'\nmeta:\n  version: '2'\n", encoding="utf-8")
        with pytest.raises(SemanticBundleError, match="重复键"):
            load_bundle(p)

    def test_quality_gate_excludes_not_errors(self, bundle_writer: Any) -> None:
        """步骤④：质量不达标 = **排除**（不报错）—— 降级排除 + 告警，非拒绝启动。"""
        def mutate(d: dict[str, Any]) -> None:
            d["assets"][6]["quality_score"] = 0.5  # traffic_daily

        loaded = load_bundle(bundle_writer(mutate))
        assert "traffic_daily" not in loaded.active_assets
        assert any(ex.logical_name == "traffic_daily" for ex in loaded.excluded_assets)
        # 被排除资产不进 allowlist（exclude_from_context）
        assert "v_traffic_daily" not in loaded.allowlist


# ============================================================================
# 运行时：L1 / L2 / L3 / 黑话 / 白名单 / 策略
# ============================================================================

class TestRuntime:
    def test_resolve_alias_metric(self, runtime: SemanticBundleRuntime) -> None:
        a = runtime.resolve_alias("GMV")
        assert a is not None
        assert a.maps_to_kind == "metric"
        assert a.maps_to_ref == "gmv"

    def test_resolve_alias_case_distinct(self, runtime: SemanticBundleRuntime) -> None:
        """别名表区分大小写（GMV / gmv 各自成条）—— 运行时**不擅自归一化**。"""
        assert runtime.resolve_alias("GMV") is not None
        assert runtime.resolve_alias("gmv") is not None
        assert runtime.resolve_alias("GmV") is None

    def test_resolve_terms_shape(self, runtime: SemanticBundleRuntime) -> None:
        out = runtime.resolve_terms(["GMV", "不存在的词", "大促"])
        # 大促在 blacklist（clarify），不进 resolved_terms
        assert out == (
            {"surface": "GMV", "canonical": "metric:gmv", "kind": "metric"},
        )

    def test_alias_unique_105(self) -> None:
        """W1A 交付口径：105 条别名（一对一由 loader 的重复 term 断言强制）。"""
        loaded = load_bundle(REAL_BUNDLE)
        assert len(loaded.bundle.aliases) == 105

    def test_blacklist_refuse_and_clarify(self, runtime: SemanticBundleRuntime) -> None:
        refuse = runtime.lookup_blacklist("坑位费")
        assert refuse is not None and refuse.action == "refuse"
        clarify = runtime.lookup_blacklist("大促")
        assert clarify is not None and clarify.action == "clarify"
        assert clarify.clarify_prompt is not None

    def test_l3_metric_default_binding(self, runtime: SemanticBundleRuntime) -> None:
        b = runtime.metric_default_binding("gmv")
        assert b is not None
        assert b.asset == "order_paid"
        assert "pay_time" in b.reason  # L3 披露文案

    def test_draft_metric_excluded_from_l3(self, runtime: SemanticBundleRuntime) -> None:
        assert runtime.metric("sell_through_rate") is not None
        assert not runtime.is_metric_active("sell_through_rate")
        assert runtime.metric_default_binding("sell_through_rate") is None
        assert runtime.is_metric_active("gmv")

    def test_l2_same_grain_numeric_not_index(self, runtime: SemanticBundleRuntime) -> None:
        """硬约束①：判同粒度用 grain_level 数值，不用 hierarchy 下标。"""
        city = runtime.dimension("city")
        assert city is not None
        # city 族从 2 起是故意的（SCHEMA D-3）：city(4) 与 shop 维度 shop(1) 下标都是"第 1 项"，
        # 但数值 4≠1 → 不同粒度。而 shop.city 与 receiver_city 同为 4 → 同粒度（真竞争）。
        assert city.grain_levels == {"region": 2, "province": 3, "city": 4}
        assert SemanticBundleRuntime.same_grain(4, 4)
        assert not SemanticBundleRuntime.same_grain(4, 1)

    def test_field_binding_ambiguous_returned_as_is(self, runtime: SemanticBundleRuntime) -> None:
        fb = runtime.field_binding("城市")
        assert fb is not None
        assert fb.ambiguous
        assert fb.canonical_asset is None  # 双向互斥：不给占位假值
        assert {c.asset for c in fb.candidates} == {"order_paid.receiver_city", "shop.city"}

    def test_allowlist_role_trimming(self, runtime: SemanticBundleRuntime) -> None:
        """deny 对 applies_to_roles 内角色生效；platform_admin 得全列（按包声明逐字执行）。"""
        analyst = runtime.asset_allowlist(_identity(Role.ANALYST))
        admin = runtime.asset_allowlist(_identity(Role.PLATFORM_ADMIN))
        assert "tenant_id" not in analyst["v_order_paid"]["columns"]
        assert "tenant_id" in admin["v_order_paid"]["columns"]
        # 被排除资产不出现
        assert "v_dim_date" in analyst  # tenant_scoped=false 的公共表也在白名单

    def test_time_semantics_from_bundle(self, runtime: SemanticBundleRuntime) -> None:
        ts = runtime.time_semantics()
        assert ts.timezone == "Asia/Shanghai"
        assert ts.fiscal_year_start_month == 1
        assert ts.week_starts_on == "monday"

    def test_policy_surface(self, runtime: SemanticBundleRuntime) -> None:
        pol = runtime.policy()
        assert len(pol["deny_columns"]) == 9
        assert any(r["column_pattern"] == ".*phone.*" for r in pol["mask_rules"])
        assert "is_test_order = false" in pol["default_predicates"]["orders"]

    def test_predicates_for_metric(self, runtime: SemanticBundleRuntime) -> None:
        # refund_rate 刻意不含 `refund_status <> 'refunded'`（分子正是退款行为）
        preds = runtime.predicates_for_metric("refund_rate")
        assert "pay_status = 'paid'" in preds
        assert "refund_status <> 'refunded'" not in preds
        assert "is_test_order = false" in preds

    def test_metrics_enumerator_returns_all_including_draft(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`metrics()` 是**枚举器**，刻意不过滤状态（理由见 `runtime.metrics()` 的注释）。

        它存在的原因很具体：plan 的资产信息只经 `semantic_summary` 到达模型，
        而摘要此前渲染不出指标段 ⇒ 模型看不见指标名 ⇒ 把指标写进 `blocking_issues`
        ⇒ PLAN 自拒 ⇒ `executing` 恒 0（W2B 的 G-6 根因回执）。
        """
        enumerated = runtime.metrics()
        assert enumerated, "夹具失效：语义包一个指标都没有"
        names = {m.name for m in enumerated}
        assert names == {m.name for m in load_bundle(REAL_BUNDLE).bundle.metrics}
        assert "gmv" in names
        assert "sell_through_rate" in names, "draft 指标被枚举器静默滤掉了（应当如实吐出）"
        # 与按名单查的 `metric()` 是**同一份对象** —— 不许有第二份真相
        assert runtime.metric("gmv") is next(m for m in enumerated if m.name == "gmv")
        # 可用性判定仍归调用方：draft 在枚举里，但 `is_metric_active` 说不可用
        assert not runtime.is_metric_active("sell_through_rate")

    def test_aliases_enumerator_is_the_same_index_as_resolve_alias(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`aliases()` 必须与 L1 的 `resolve_alias()` **同源**（不是另抄一份表）。

        判据用**对象同一性**逐条回代：任何"另建一张表"的实现都会在这里红 —
        而两张表漂移的后果是模型按摘要里的词形问、L1 却查不到，静默落到 L4 近似匹配。
        """
        aliases = runtime.aliases()
        assert len(aliases) == 105
        for alias in aliases:
            assert runtime.resolve_alias(alias.term) is alias
