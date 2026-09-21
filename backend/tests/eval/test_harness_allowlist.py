"""`eval/harness.py` 的单元测试 —— allowlist 形状适配、闸门自伤判据、夹具与超时。

归属窗口：W6。

这里测的都是"评测器凭什么有权替被测系统说话"的那几件事
--------------------------------------------------------------------------
* `AssetAllowlistView` 是**双形状视图**，存在的理由是一条上游契约冲突（两个消费者要求
  互斥形状）。它一旦把 wrapper 键当资产枚举出去，planner 的提示词就会长出 8 张假表。
* `detect_gate_self_defect` 决定一条 R06 记在**闸门**头上还是**模型**头上；
  它自己判错，§C.7 的分布就整体失真。
* 超时派生：评测若在契约超时上跑，LLM 节点会整批超时，然后报告里全是"链路故障"。
"""

from __future__ import annotations

import ast
import os

import harness as H
import pytest

from app.core.enums import RetrievalMode, Role
from app.core.errors import ContractViolationError
from app.guard.ast_gate import DEFAULT_MAX_ROWS, _effective_limit, run_gate1
from app.guard.policy_gate import run_gate2


# ==== AssetAllowlistView：双形状不能互相污染 ==========================
def test_view_iterates_only_flat_assets_not_guard_wrapper_keys():
    """planner 走 `sorted(allowlist)` —— 枚举里混进 `assets`/`joins` 就是给它 8 张假表。"""
    from harness import AssetAllowlistView

    view = AssetAllowlistView(
        {"v_order_paid": {"logical_name": "order_paid"}, "v_shop": {"logical_name": "shop"}},
        {
            "assets": {"v_order_paid": {}}, "joins": [], "deny_columns": [],
            "default_predicates": {}, "bundle_version": "x",
        },
    )
    assert sorted(view) == ["v_order_paid", "v_shop"]
    assert len(view) == 2
    assert "assets" not in list(view)


def test_view_prefers_flat_entry_over_wrapper_key():
    from harness import AssetAllowlistView

    flat = {"v_shop": {"logical_name": "shop", "columns": {}}}
    wrapper = {"assets": {"FAKE": {}}, "joins": []}
    view = AssetAllowlistView(flat, wrapper)
    assert view["v_shop"]["logical_name"] == "shop"
    assert view.get("assets") == {"FAKE": {}}          # wrapper 键仍可取（闸门要）
    assert view.get("nope") is None and view.get("nope", 7) == 7


def test_view_refuses_to_build_when_a_physical_asset_shadows_a_guard_key():
    """正对照：物理资产真叫 `assets` 时必须**炸**，不能静默遮蔽（遮蔽方向 = 闸门拿不到判据）。"""
    from harness import AssetAllowlistView

    with pytest.raises(ValueError, match="遮蔽"):
        AssetAllowlistView({"assets": {"columns": {}}}, {"joins": []})


# ==== GuardAllowlistBundle：缓存 + 透传 ===============================
def test_bundle_caches_per_role_and_passes_through_other_methods(harness, analyst_ctx):
    assert harness.semantics.asset_allowlist(analyst_ctx) is harness.semantics.asset_allowlist(analyst_ctx)
    assert harness.semantics.active_version() == harness.runtime.active_version()
    assert harness.semantics.policy() == harness.runtime.policy()


def test_visible_columns_have_deny_columns_stripped(guard_allowlist):
    """CLS 的评测面：夹具/闸门看到的列集必须**已剔除** deny 列，而 deny 清单本身仍在。"""
    entry = guard_allowlist["v_order_paid"]
    visible = set(entry["columns"])
    denied_logical = {"tenant_id", "receiver_phone", "receiver_address"}
    assert not (visible & denied_logical), f"deny 列漏进了可见列面：{visible & denied_logical}"
    assert any(d.startswith("order_paid.") for d in guard_allowlist["deny_columns"])


def test_wrapper_shape_keys_are_all_present(guard_allowlist):
    for key in ("assets", "joins", "deny_columns", "default_predicates", "allowed_constants"):
        assert key in guard_allowlist, f"闸门判据缺键：{key}"


def test_allowed_constants_is_empty_because_bundle_has_none(harness, analyst_ctx):
    """语义包**没有** `allowed_constants` 区块（grep 实证）⇒ 端口给空集合，评测不许编一个。"""
    assert not harness.runtime.guard_allowlist(analyst_ctx, max_rows=None)["allowed_constants"]


def test_eval_does_not_invent_a_max_rows(harness, analyst_ctx, guard_allowlist):
    """评测不许私自注入 `max_rows`，否则 R04 在评测里比生产严/松。

    U-121 之前这条测试钉的是"wrapper 里**没有** `max_rows` 键"；端口现在**必给**这个键
    （生产也没给 ⇒ 填 `None`）。⇒ 钉法换成"键在但值为空，且 R04 的生效值与生产同值"。
    """
    port = harness.runtime.guard_allowlist(analyst_ctx, max_rows=None)
    assert port["max_rows"] is None, "评测不得自己决定行数上限"
    assert guard_allowlist.get("max_rows") is None
    assert _effective_limit(port) == _effective_limit({}) == DEFAULT_MAX_ROWS


# ==== run_gate2 的端口形状（一条真实的踩坑路径）=======================
def test_gate2_rejects_an_allowlist_view_because_it_wants_a_port(guard_allowlist, analyst_ctx):
    """`run_gate2(sql, ctx, bundle)` 的第三个参数是**端口**（自己调 `asset_allowlist`）。

    记进测试的理由：红队跑批第一版就是传了视图 ⇒ `AttributeError`，
    而它长得像被测系统坏了。
    """
    with pytest.raises(AttributeError):
        run_gate2("SELECT pay_amount FROM v_order_paid", analyst_ctx, guard_allowlist)


def test_gate2_bidirectional_tenant_assertion_raises_on_production_visible_shape(analyst_ctx, harness):
    """🔴 生产现状（不是评测的发明）：可见列已剔除 `tenant_id`，而资产仍 `tenant_scoped=true`
    ⇒ 07 §7.4 的双向断言 **必然**抛 `ContractViolationError`。

    这条测试钉住两件事：① 评测不能拿"闸门没报错"当 G-3/G-4 的证据（它压根没返回）；
    ② 红队必须显式改用结构档 bundle（见下一条），否则整批 45/66 的 FAIL 会被读成模型问题。
    """
    sql = "SELECT pay_amount FROM v_order_paid"
    with pytest.raises(ContractViolationError):
        run_gate2(sql, analyst_ctx, harness.semantics)


def test_gate2_passes_when_columns_are_the_full_bundle_shape(analyst_ctx, harness):
    import redteam_eval as rt

    structural = rt.StructuralAllowlistBundle(harness.semantics, rt.structural_wrapper(harness))
    result = run_gate2("SELECT pay_amount FROM v_order_paid", analyst_ctx, structural)
    assert result.gate_result.decision.value == "pass"


def test_structural_wrapper_only_changes_the_columns_face(harness, analyst_ctx):
    """结构档只把 `assets[*].columns` 换成端口的 `all_columns`，其余键一字不动。"""
    import redteam_eval as rt

    base = harness.runtime.guard_allowlist(analyst_ctx, max_rows=None)
    full = rt.structural_wrapper(harness)
    assert set(full) == set(base), "结构档不得新增/删除顶层键 —— 字段只能来自端口"
    assert "tenant_id" in full["assets"]["v_order_paid"]["columns"]
    assert "tenant_id" not in base["assets"]["v_order_paid"]["columns"]
    assert full["deny_columns"] == base["deny_columns"]
    assert full["default_predicates"] == base["default_predicates"]
    assert full["joins"] == base["joins"], "joins 由端口派生，评测不再截点分名"


# ==== U-119 / U-121：形状只能取自端口，且适配层必须"到期"==============
#: `contracts.GuardAllowlist` 的七个键（本测试只用作**反查**：评测侧不许自己拼出这些键）。
_GUARD_KEYS = ("bundle_version", "assets", "joins", "deny_columns",
               "default_predicates", "allowed_constants", "max_rows")
#: 两道闸门的取数点（W2C 的接线面）。
_GATE_CONSUMERS = (os.path.join("app", "guard", "policy_gate.py"),
                   os.path.join("app", "graph", "nodes", "gate1_ast.py"))


def _guard_keys_per_dict(path: str) -> list[set[str]]:
    """每个**字典字面量**各自命中的闸门键（不是全模块并集 —— 那样阈值就没意义了）。"""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    guard = set(_GUARD_KEYS)
    hits: list[set[str]] = []
    for node in (n for n in ast.walk(tree) if isinstance(n, ast.Dict)):
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if keys & guard:
            hits.append(keys & guard)
    return hits


def _port_methods_called_by_gates(repo_root: str) -> set[str]:
    """生产闸门实际调了端口的哪个方法（AST 扫源码，不靠文档也不靠猜）。"""
    found: set[str] = set()
    for rel in _GATE_CONSUMERS:
        with open(os.path.join(repo_root, "backend", rel), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found |= {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("asset_allowlist", "guard_allowlist")
        }
    return found


def test_the_evaluator_never_derives_guard_fields_itself():
    """🔴 U-119 的正面要求：形状只能**取自端口**，评测不得再拼一个 wrapper。

    判据是"字典字面量里出现 ≥5 个闸门键"⇒ 算的是**整份 wrapper**（被删掉的那版拼了 6 个）。
    阈值不是 7：漏 `max_rows` 的自拼件同样危险；也不是 3：`harness` 的自检证据字典与检索
    载荷本来就有同名列（键多到能拼出判据才是造面，只是取个长度不是）。
    漂移的真正兜底是 `test_view_forwards_the_port_output_verbatim`（行为对照：给闸门的七键
    必须逐键等于端口输出），本条只是不让旧符号悄悄回来。
    """
    import harness as _h
    import redteam_eval as _rt

    assert not hasattr(_h, "build_guard_allowlist"), "被删的派生函数不得回来"
    for mod in (_h, _rt):
        hits = _guard_keys_per_dict(os.path.abspath(mod.__file__))
        fabricated = next((sorted(h) for h in hits if len(h) >= 5), None)
        assert fabricated is None, (
            f"{os.path.basename(mod.__file__)} 里有字典字面量装了 {fabricated}（全部命中："
            f"{[sorted(h) for h in hits]}）—— 闸门判据必须由 "
            "`SemanticBundleRuntime.guard_allowlist()` 给出，不是评测拼"
        )


def test_view_forwards_the_port_output_verbatim(harness, analyst_ctx):
    """正对照：视图给闸门的 wrapper **逐键等于端口输出**，枚举面仍等于扁平面。"""
    port = harness.runtime.guard_allowlist(analyst_ctx, max_rows=None)
    view = harness.semantics.asset_allowlist(analyst_ctx)
    assert {k: view.get(k) for k in _GUARD_KEYS} == {k: port.get(k) for k in _GUARD_KEYS}
    assert sorted(view) == sorted(harness.runtime.asset_allowlist(analyst_ctx))


def test_the_dual_shape_view_dies_with_the_consumer_fix(repo_root):
    """哨兵：消费侧一旦改调 `guard_allowlist`，评测的双形状视图必须**整体删除**。

    为什么要它：适配层"是临时的"这句话靠注释传承不了两轮。今天生产仍从 `asset_allowlist`
    读闸门判据 ⇒ 视图合法存在；哪天 W2C 接线完成（`policy_gate` 的 ④⑤ 还要改读
    `all_columns`，见 `reports/w6/probe_gate_allowlist_shape.json`），本测试立刻红并点名删处。
    """
    if "asset_allowlist" not in _port_methods_called_by_gates(repo_root):
        pytest.fail(
            "U-121 消费侧已接线（两道闸门都改调 `guard_allowlist`）⇒ 现在必须删除评测侧适配层："
            "`eval/harness.py` 的 `AssetAllowlistView` / `GuardAllowlistBundle` 与 "
            "`eval/redteam_eval.py` 的 `StructuralAllowlistBundle` / `structural_wrapper`"
            "（U-119 判据③ 的副产品；留着它就是第三份真相）"
        )
    # 删除条件尚未成立 ⇒ 视图必须仍在（在 = 评测跑得动；不在 = 本测试的另一半失真）
    assert hasattr(H, "GuardAllowlistBundle") and hasattr(H, "AssetAllowlistView")


# ==== gate1 的真实形状（评测与生产同一条路径）=========================
def test_gate1_blocks_tenant_id_either_qualified_or_not(analyst_ctx, harness):
    """I-4/I-5 冲突的实测半边：手写租户谓词进不了闸门，所以评测只能走 DB 对象层。"""
    al = harness.semantics.asset_allowlist(analyst_ctx)
    bare = run_gate1("SELECT pay_amount, tenant_id FROM v_order_paid", al)
    qualified = run_gate1("SELECT v_order_paid.tenant_id FROM v_order_paid", al)
    assert bare.passed is False and qualified.passed is False
    # ⚠️ 归因会随**表前缀**漂移（无表前缀时列归属先失败 → R06），文案两者共用一句。
    assert {bare.gate_result.rule_id, qualified.gate_result.rule_id} == {"R06", "R07"}
    assert bare.gate_result.reason == qualified.gate_result.reason == "查询包含受保护字段"


def test_gate1_rejects_assets_outside_the_bundle(analyst_ctx, harness):
    al = harness.semantics.asset_allowlist(analyst_ctx)
    r = run_gate1("SELECT 1 FROM orders", al)
    assert r.passed is False and r.gate_result.rule_id == "R05"


# ==== detect_gate_self_defect：R06 的两种相反含义 =====================
def test_f1_order_by_projection_alias_is_the_gates_fault(guard_allowlist):
    defect = H.detect_gate_self_defect(
        "SELECT SUM(pay_amount) AS gmv FROM v_order_paid GROUP BY region_name ORDER BY gmv DESC",
        guard_allowlist,
    )
    assert defect and "F1" in defect and "gmv" in defect


def test_f1_must_not_fire_on_a_qualified_order_key(guard_allowlist):
    """反例：`ORDER BY o.region_name` 走表别名解析（`_scope_tables` 登记 alias），
    是合法形态，不许记成闸门缺陷。

    ⚠️ 这里必须用 `v_order_paid`：`v_region` 会先被 F2 命中（见下面那条），
    用它做 F1 的反例等于什么都测不到。
    """
    assert H.detect_gate_self_defect(
        "SELECT o.region_name AS rn FROM v_order_paid o ORDER BY o.region_name", guard_allowlist
    ) is None


def test_f2_v_region_is_poisoned_by_the_orders_domain_predicates(guard_allowlist):
    """实测：`v_region.domain == 'orders'` ⇒ orders 域的默认谓词被注入到一张没有那些列的表。"""
    defect = H.detect_gate_self_defect("SELECT region_name FROM v_region", guard_allowlist)
    assert defect and "F2" in defect and "v_region" in defect


def test_clean_sql_produces_no_self_defect(guard_allowlist):
    """正对照：判据不能恒真，否则所有 R06 都会被推给闸门。"""
    assert H.detect_gate_self_defect("SELECT pay_amount FROM v_order_paid", guard_allowlist) is None


def test_unparsable_and_unknown_asset_sql_are_not_gate_defects(guard_allowlist):
    """语法不成立是模型的账；未声明资产由 R05 管 —— 都不许记到 `gate_policy_gap`。"""
    assert H.detect_gate_self_defect("SELECT FROM WHERE", guard_allowlist) is None
    assert H.detect_gate_self_defect("SELECT x FROM not_in_bundle", guard_allowlist) is None
    assert H.detect_gate_self_defect("   ", guard_allowlist) is None


# ==== 身份与超时派生 ==================================================
def test_identity_is_deterministic_per_case_and_tenant():
    a1 = H.identity_for_case("C-1", "T_A")
    a2 = H.identity_for_case("C-1", "T_A")
    b1 = H.identity_for_case("C-2", "T_A")
    assert a1 == a2, "同一条用例两次跑出两个身份 → 权限回放不可复现"
    assert a1.user_id != b1.user_id
    assert a1.role is Role.ANALYST
    assert H.identity_for_case("C-1", "T_A", role=Role.OPERATOR).role is Role.OPERATOR


def test_eval_timeouts_keep_contract_values_but_floor_llm_nodes():
    """契约超时不许原样用在评测上：一次 LLM 调用就能超过契约值，
    于是整批被判"链路故障" —— 但执行/闸门这类**纯 CPU** 节点必须照契约。"""
    effective = H.eval_node_timeouts()
    described = H.describe_node_timeouts(effective)
    contract, floor = described["contract"], described["llm_node_floor_s"]
    assert described["scaled"] is True
    for node in described["llm_calling_nodes"]:
        assert effective[node] >= floor, "LLM 节点必须拿到评测下界"
        if node in contract:
            assert effective[node] >= contract[node]
    for node in described["kept_as_contract"]:
        assert effective[node] == contract[node]
    for node in set(contract) - set(described["llm_calling_nodes"]) - set(described["kept_as_contract"]):
        assert effective[node] == contract[node] * described["cpu_factor"]
    # U-104 之后 LLM 节点的硬超时不在契约表里（执行期由路由解析）⇒ 键集合是**并集**，
    # 且"哪些节点名已不在契约表"必须被显式报出来，不能静默隐身。
    assert set(effective) == set(contract) | set(described["llm_calling_nodes"])
    assert described["not_in_contract"] == sorted(
        set(described["llm_calling_nodes"]) - set(contract))


def test_outbound_budget_nodes_are_not_double_amplified() -> None:
    """U-107 把 `link` 的契约值抬到了**出站客户端超时同档**（30s = `EMBEDDING_TIMEOUT_SECONDS`）
    ⇒ 再乘 CPU 系数就是 240s：放大的是墙钟，不是被测事实（评测走本地夹具检索，逼近不了 30s）。
    所以"不放大"清单要逐节点钉住，且任何非 LLM 节点都不许被放大到越过 LLM 下界。
    """
    described = H.describe_node_timeouts(H.eval_node_timeouts())
    contract, effective = described["contract"], described["effective"]
    assert set(described["kept_as_contract"]) == {"execute", "link"}
    for node in described["kept_as_contract"]:
        assert effective[node] == contract[node]
    for node, value in effective.items():
        if node not in H.LLM_CALLING_NODES:
            assert value <= H.EVAL_LLM_NODE_TIMEOUT_S


def test_timeouts_survive_contract_slimming() -> None:
    """漂移守卫：契约表瘦身（U-104 把 LLM 节点移出去）不许让下界静默消失。

    本测试写的时候就是因为 `gen_sql` 已从 `NODE_TIMEOUT_S` 移除，旧实现只遍历契约表 ⇒
    这些节点连 override 都拿不到，真打批次又会把"上游慢"判成链路故障。
    """
    effective = H.eval_node_timeouts()
    moved = [n for n in ("gen_sql", "intent", "plan", "normalize", "repair")
             if n not in H.NODE_TIMEOUT_S]
    assert moved, "契约表若又把这些节点收回去，本测试的靶子就没了 —— 改测试而不是删断言"
    for node in moved:
        assert effective[node] == H.EVAL_LLM_NODE_TIMEOUT_S


def test_unknown_cassette_mode_is_rejected_at_construction():
    """真打时模式写错会静默退化成"不录"，第二批还以为在回放。"""
    with pytest.raises(ValueError, match="匣带模式"):
        H.Harness(cassette_path="x.json", cassette_mode="bogus", live=True)


def test_tenant_scoped_physicals_come_from_the_bundle(harness):
    """租户清单从语义包 `tenant_scoped=true` 导出，且只覆盖**激活**资产。"""
    assert set(harness.tenant_scoped_physicals) == {
        a.physical_asset for a in harness.loaded.bundle.assets
        if a.tenant_scoped and a.logical_name in harness.loaded.active_assets
    }
    assert set(harness.tenant_scoped_physicals.values()) == {"tenant_id"}
    assert len(harness.tenant_scoped_physicals) == 6, "语义包若新增租户资产，缺口表与一致性①都要跟着改"


# ==== 检索夹具：deny 面 + 降级面 =====================================
async def test_retrieval_fixture_excludes_deny_columns_and_keeps_all_metrics(harness, analyst_ctx):
    """夹具必须与生产可见面同形：deny 列不许出现在列候选里。

    ⚠️ `column_top` 只裁列候选、**不裁指标** —— 这是本夹具的既定行为（指标层只有 8 条，
    裁它会直接改变绑定结果）。写在这里是为了让"改这个行为"必须过一次测试。
    """
    full = await harness.retrieval.search_full("各大区 GMV", analyst_ctx, RetrievalMode.HYBRID)
    column_face = " | ".join(str(name) for name, _ in full.columns)
    for banned in ("tenant_id", "receiver_phone", "receiver_address", "cost_price"):
        assert banned not in column_face, f"deny 列 {banned} 出现在检索列候选里"

    trimmed = await H.BundleCatalogRetrieval(
        harness.loaded, column_top=3,
        denied_columns=tuple(harness.runtime.policy().get("deny_columns") or ()),
    ).search_full("各大区 GMV", analyst_ctx, RetrievalMode.HYBRID)
    assert len(trimmed.columns) == 3 < len(full.columns)
    assert len(trimmed.metrics) == len(full.metrics) == 8


async def test_offline_retrieval_degrades_loudly_instead_of_faking_hybrid(harness, analyst_ctx):
    """占位环境下嵌入服务不可用 ⇒ 必须回 `SPARSE_ONLY` 并带上降级原因。

    这条是"不许把降级读成正常"的护栏：若哪天它悄悄返回 `HYBRID`，
    说明要么环境真起了嵌入服务（那报告口径要改），要么夹具在说谎。
    """
    from app.core.enums import ActionTaken, DegradedReason
    from app.core.enums import RetrievalMode as RM

    res = await harness.retrieval.search_full("各大区 GMV", analyst_ctx, RM.HYBRID)
    assert res.mode is RM.SPARSE_ONLY
    assert res.action_taken is ActionTaken.SPARSE_ONLY
    assert res.degraded_reason is DegradedReason.EMBEDDING_UNAVAILABLE
    assert len(res.candidates) == len(harness.loaded.active_assets)


def test_gate3_thresholds_are_ordered_pass_below_reject(harness):
    t = harness.gate3_thresholds()
    assert t["total_cost_pass"] < t["total_cost_reject"]
    assert t["rows_pass"] < t["rows_reject"]
