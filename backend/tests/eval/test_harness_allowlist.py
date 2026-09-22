"""`eval/harness.py` 的单元测试 —— allowlist 形状适配、闸门自伤判据、夹具与超时。

归属窗口：W6。

这里测的都是"评测器凭什么有权替被测系统说话"的那几件事
--------------------------------------------------------------------------
* 闸门判据的**取用面**：评测侧不许再拼 wrapper，也不许再包一层双形状视图（U-121 全部
  落地后已删净）。本文件里那几条"到期哨兵"因此转成了**回归哨兵** —— 回退即红。
* `detect_gate_self_defect` 决定一条 R06 记在**闸门**头上还是**模型**头上；
  它自己判错，§C.7 的分布就整体失真。
* 超时派生：评测若在契约超时上跑，LLM 节点会整批超时，然后报告里全是"链路故障"。
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import harness as H
import pytest

from app.core.enums import RetrievalMode, Role
from app.guard.ast_gate import DEFAULT_MAX_ROWS, _effective_limit, run_gate1
from app.guard.policy_gate import run_gate2


# ==== 闸门判据的取用面（评测侧不再包视图）=================================
def test_harness_semantics_is_the_port_itself(harness):
    """评测路径与生产路径**同一个对象** —— 这是 U-121 的交付判据，不是风格偏好。

    记进测试的理由：适配层当初就是以'另一个实例'的形式混进来的，只要 `semantics` 又
    变成代理类，评测就会和生产读到不同的面，而所有读数仍然'看起来对'。
    """
    from app.semantics.runtime import SemanticBundleRuntime

    assert harness.semantics is harness.runtime
    assert type(harness.runtime) is SemanticBundleRuntime, "semantics 又变成代理类了"


def test_visible_columns_have_deny_columns_stripped(guard_allowlist):
    """CLS 的评测面：夹具/闸门看到的列集必须**已剔除** deny 列，而 deny 清单本身仍在。"""
    entry = guard_allowlist["assets"]["v_order_paid"]
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
    """`run_gate2(sql, ctx, bundle)` 的第三个参数是**端口**（自己调 `guard_allowlist`）。

    记进测试的理由：红队跑批第一版就是传了视图 ⇒ `AttributeError`，
    而它长得像被测系统坏了。
    """
    with pytest.raises(AttributeError):
        run_gate2("SELECT pay_amount FROM v_order_paid", analyst_ctx, guard_allowlist)


def test_gate2_on_the_production_port_no_longer_raises(analyst_ctx, harness):
    """🟢 生产链现状（U-121 第三步 `c76f701` 之后）：gate2 在**端口**上就能跑通，不再抛
    `ContractViolationError`。

    这条测试的前身是钉住一个**失效**（可见面已剔 `tenant_id`，而 ⑤ 用可见面判
    `tenant_scoped ⇔ tenant_id` ⇒ 必抛，07 §7.4 那条"N-07 失效"的雷）。W2C 把 ④⑤ 改读
    `all_columns` 后，结构面由闸门自己在 `policy_gate.py:187-201` 内顶起来 ⇒ 判据反转：

    * **不抛**并且 pass = 生产闸门真的生效了（G-3/G-4 的证据才成立）；
    * 一旦重新抛 `ContractViolationError` = 闸门又退回读可见面，本测试当场红。

    ⚠️ 红队侧同一条事实由 `gate2_on_port_raised` 落盘（`eval/redteam_eval.py`），
    两处都留读数，是为了防"只在一处修好"。
    """
    result = run_gate2("SELECT pay_amount FROM v_order_paid", analyst_ctx, harness.semantics)
    assert result.gate_result.decision.value == "pass", (
        f"生产端口上的 gate2 判成 {result.gate_result.decision.value}"
        f"（rule={result.gate_result.rule_id}）⇒ 07 §7.4 的双向断言在真实链上没走通"
    )


def test_structural_face_widening_only_touches_the_columns_key(analyst_ctx, harness):
    """结构面 = 只把 `assets[*].columns` 顶成 `all_columns`，其余判据一字不动。

    这条从"评测自己顶面"改成"核对闸门顶面后的效果"：租户列必须在结构面里**看得见**
    （④ 敏感列复核与 ⑤ 双向断言的前提），同时**仍不在**可见面里（gate1 R06 的跨租户
    拦截机制依赖的就是这一半）。两面都读，是为了让"顺手把 deny 列放回可见面"也红。
    """
    port = harness.runtime.guard_allowlist(analyst_ctx, max_rows=None)
    entry = port["assets"]["v_order_paid"]
    assert "tenant_id" in entry["all_columns"], "结构面缺 tenant_id ⇒ gate2 ⑤ 无法成立"
    assert "tenant_id" not in entry["columns"], "deny 列混进可见面 ⇒ gate1 R06 的拦截失效"


# ==== U-119 / U-121：形状只能取自端口，且适配层不得复活============
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


def _port_methods_called_by_gates(repo_root: str) -> dict[str, set[str]]:
    """生产闸门实际调了端口的哪个方法（AST 扫源码，不靠文档也不靠猜）—— **按文件分开**。

    ⚠️ 这里刻意不做并集：并集会让哨兵对"只接线了一半"完全失明。实测：W4 落 `357618f` 之后
    `gate1_ast.py` 已改调 `guard_allowlist`、`policy_gate.py` 仍读 `asset_allowlist`，
    并集版的哨兵既不响也不报，等于"到期"这件事只写在注释里（正是本测试要防的那件事）。
    """
    per_file: dict[str, set[str]] = {}
    for rel in _GATE_CONSUMERS:
        with open(os.path.join(repo_root, "backend", rel), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        per_file[rel.replace("\\", "/")] = {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("asset_allowlist", "guard_allowlist")
        }
    return per_file


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


def test_gate_input_equals_port_output(harness, analyst_ctx, guard_allowlist):
    """给闸门的那七键**逐键等于**端口输出 —— 中间没有任何加工。

    前身是"视图必须原样转发端口"。适配层删净之后这条仍然要留：它防的是"哪天有人
    在评测里给闸门补一个键 / 裁一个键"（那正是当初手拼七键造成的 `ast_gate.py:751`
    `AttributeError` 的形状）。
    """
    port = harness.runtime.guard_allowlist(analyst_ctx, max_rows=None)
    assert {k: guard_allowlist.get(k) for k in _GUARD_KEYS} == {k: port.get(k) for k in _GUARD_KEYS}


def test_the_adapter_symbols_stay_dead(repo_root):
    """🔴 回归哨兵（前身 = 两条"到期即 fail"哨兵）：适配层删了就不许回来，闸门也不许回退。

    W7 在 2026-09-22 明确要求"这条 AST 守卫别摘掉，改成转绿点名" ⇒ 判据从"到期就红"
    反转成"回退就红"，扫描面一字未改（**按文件**，不做并集 —— 并集版对"只接一半"失明，
    09-21 的 `357618f` 就是活证）。四件事一起钉：

    ① 两道闸门都调 `guard_allowlist`；
    ② 两道闸门都**不**再调 `asset_allowlist` 取判据；
    ③ 评测侧的适配符号全部不在（含 `redteam_eval` 那两个）；
    ④ `harness` docstring 里那行"存在理由（仍在读扁平面…）"清单不在 ——
       它是需要人工同步的第二处真相，2026-09-21 就是它先失真的。
    """
    import harness as _h
    import redteam_eval as _rt

    calls = _port_methods_called_by_gates(repo_root)
    readings = {k: sorted(v) for k, v in sorted(calls.items())}
    not_wired = {rel for rel, m in calls.items() if "guard_allowlist" not in m}
    back_to_flat = {rel for rel, m in calls.items() if "asset_allowlist" in m}
    assert not not_wired, f"闸门未接端口闸门面（逐文件读数 {readings}）：{sorted(not_wired)}"
    assert not back_to_flat, f"闸门回退到扁平面取判据（逐文件读数 {readings}）：{sorted(back_to_flat)}"

    revived = [f"{m.__name__}:{name}" for m, names in (
        (_h, ("AssetAllowlistView", "GuardAllowlistBundle", "build_guard_allowlist",
              "_GUARD_WRAPPER_KEYS")),
        (_rt, ("StructuralAllowlistBundle", "structural_wrapper")),
    ) for name in names if hasattr(m, name)]
    assert not revived, f"评测侧适配层符号复活：{revived}（U-121 已全量落地，留着就是第三份真相）"

    doc = _h.__doc__ or ""
    assert "存在理由（仍在读扁平面" not in doc, (
        "harness docstring 又出现了需要人工同步的『存在理由』清单 —— 适配层已不存在，"
        "这句话没有可维护的真值，删掉它（本测试的 ④）"
    )
    assert "class AssetAllowlistView" not in Path(_h.__file__).read_text(encoding="utf-8")


# ==== gate1 的真实形状（评测与生产同一条路径）=========================
def test_gate1_blocks_tenant_id_either_qualified_or_not(analyst_ctx, harness):
    """I-4/I-5 冲突的实测半边：手写租户谓词进不了闸门，所以评测只能走 DB 对象层。"""
    al = harness.semantics.guard_allowlist(analyst_ctx, max_rows=None)
    bare = run_gate1("SELECT pay_amount, tenant_id FROM v_order_paid", al)
    qualified = run_gate1("SELECT v_order_paid.tenant_id FROM v_order_paid", al)
    assert bare.passed is False and qualified.passed is False
    # ⚠️ 归因会随**表前缀**漂移（无表前缀时列归属先失败 → R06），文案两者共用一句。
    assert {bare.gate_result.rule_id, qualified.gate_result.rule_id} == {"R06", "R07"}
    assert bare.gate_result.reason == qualified.gate_result.reason == "查询包含受保护字段"


def test_gate1_rejects_assets_outside_the_bundle(analyst_ctx, harness):
    al = harness.semantics.guard_allowlist(analyst_ctx, max_rows=None)
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
