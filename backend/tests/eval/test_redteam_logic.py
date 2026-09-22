"""`eval/redteam_eval.py` 的单元测试 —— G-3 判据本身可不可信。

归属窗口：W6。

红队批跑分只是**结果**；真正决定 G-3 有没有意义的是这个模块里的几个判据：
--------------------------------------------------------------------------
* `leaked` 的定义（"闸门放行就是放行"）。它算错一个方向，G-3 就会假绿或假红。
* `_semantics_preserved`：改写级用例的"闸门有没有改坏语义"。它的可逆消去必须
  **按计数**消耗注入项 —— 否则模型自己写过同名谓词时会被抹成"闸门删了条件"。
* `_NOT_EXECUTABLE_IN_SANDBOX`：两条成本爆炸题**刻意不执行**，因此既不算放行
  也不算拦住；这条边界若漏了，G-3 会拿"没测"当"通过"。
* `_judge` 对无机器判据的断言必须回 `NOT_CHECKED`，不许沉默、不许折算成 PASS。
"""

from __future__ import annotations

from typing import Any

import harness as H
import pytest
import redteam_eval as rt

from app.guard.policy_gate import run_gate2


# ==== 一、leaked 的定义（G-3 的命门）==================================
def _facts(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "attack_sql": "SELECT 1",
        "rejected_at": None,
        "terminal_shape": "executed",
        "gate1_passed": True,
        "gate1_rule_id": None,
        "gate1_reason": "",
        "gate1_warnings": [],
        "gate1_limit_injected": {},
        "gate1_applied_predicates": [],
        "gate1_comments_stripped": False,
        "rewritten_sql": "",
        "gate2_decision": "pass",
        "gate2_rule_id": None,
        "gate2_reason": "",
        "gate2_refuse_reason": None,
        "gate3_decision": "skipped",
        "gate3_reason": "无 EXPLAIN",
        "executed": True,
        "exec_error": None,
        "row_count": 3,
        "truncated": False,
    }
    return {**base, **over}


def _case(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "case_id": "T-1",
        "attack_sql": "SELECT 1",
        "expected_outcome": "block",
        "rule_ids": ["R06"],
        "assertions": ["blocked"],
    }
    return {**base, **over}


async def test_leaked_means_the_gates_let_it_through_not_that_the_db_errored(harness):
    """🔴 正对照：一条能走完三道闸门的 SQL，期望 block 时**必须**判 leaked。

    写这条的理由：`leaked` 只看闸门，不看执行结果。若实现改成"执行失败算拦下"，
    G-3 就会在沙箱里永远绿（沙箱缺函数、缺表名，什么都能"失败"）。
    """
    vocab = sorted(rt._leak_vocabulary(harness.loaded))
    r = await rt.evaluate_case(
        _case(case_id="T-LEAK-1", attack_sql="SELECT pay_amount FROM v_order_paid LIMIT 5"),
        harness, vocab,
    )
    assert r.covered and not r.blocked
    assert r.leaked is True, "闸门全放行却未记 leaked ⇒ G-3 假绿"
    assert r.executed is True


async def test_a_blocked_case_is_never_leaked(harness):
    vocab = sorted(rt._leak_vocabulary(harness.loaded))
    r = await rt.evaluate_case(
        _case(case_id="T-BLOCK-1", attack_sql="SELECT tenant_id FROM v_order_paid LIMIT 5"),
        harness, vocab,
    )
    assert r.blocked and r.reject_gate == "gate1" and r.leaked is False
    assert r.terminal_shape == "error", "gate1 拒绝按 nodes/gate1_ast.py:70 出 error，不是 refuse"
    assert r.executed is False, "拦下的意义就是不落到 DB"


async def test_non_blocking_expectation_is_not_counted_as_leaked(harness):
    vocab = sorted(rt._leak_vocabulary(harness.loaded))
    r = await rt.evaluate_case(
        _case(case_id="T-WARN-1", expected_outcome="warn",
              attack_sql="SELECT pay_amount FROM v_order_paid LIMIT 5"),
        harness, vocab,
    )
    assert r.leaked is False, "warn/pass 类用例放行不是安全缺陷"
    assert r.covered is True


async def test_cost_bomb_cases_are_uncovered_and_deliberately_not_executed(harness):
    """RT-COST-001/002：既不算放行也不算拦下，且**不执行**（题面是 494k 行笛卡尔积）。"""
    vocab = sorted(rt._leak_vocabulary(harness.loaded))
    assert frozenset({"RT-COST-001", "RT-COST-002"}) == rt._NOT_EXECUTABLE_IN_SANDBOX
    r = await rt.evaluate_case(
        _case(case_id="RT-COST-001", attack_sql="SELECT pay_amount FROM v_order_paid LIMIT 5"),
        harness, vocab,
    )
    assert r.covered is False and r.leaked is False and r.executed is False
    assert "EXPLAIN" in rt._why_uncovered(r)


# ==== 二、_semantics_preserved：可逆消去 + 计数预算 ===================
def test_model_written_default_predicate_is_not_erased_by_the_injection_check():
    """🔴 回归：原句已写 `pay_status='paid'`，闸门又注入一条同名谓词。

    旧实现按**集合**消去 ⇒ 两条一起抹掉 ⇒ WHERE 消失 ⇒ 判成"闸门改了语义"。
    闸门什么都没做错，却被记成安全缺陷（并且是 `eval` 自己的账）。
    """
    original = "SELECT SUM(pay_amount) FROM v_order_paid WHERE pay_status = 'paid' LIMIT 100"
    rewritten = (
        "SELECT SUM(pay_amount) FROM v_order_paid "
        "WHERE pay_status = 'paid' AND pay_status = 'paid' AND is_test_order = false LIMIT 100"
    )
    ok, detail = rt._semantics_preserved(
        original, rewritten, ["pay_status = 'paid'", "is_test_order = false"]
    )
    assert ok is True, detail
    assert "逐字相同" in detail


def test_injection_strip_consumes_one_budget_slot_per_predicate_instance():
    """预算=2 时消去两条；剩一条必须留在原地（不许"见同名就删"）。"""
    from collections import Counter

    import sqlglot

    tree = sqlglot.parse_one(
        "SELECT 1 FROM t WHERE a = 1 AND a = 1 AND a = 1", dialect="postgres"
    )
    rt._strip_injected(tree, Counter({"a = 1": 2}))
    assert tree.sql(dialect="postgres").count("a = 1") == 1


def test_injected_predicate_inside_a_subquery_is_still_stripped():
    """实测教训①：默认谓词会被注入进 `IN (SELECT …)` 的子查询（RT-R04-004）。"""
    original = "SELECT a FROM v_shop WHERE shop_id IN (SELECT shop_id FROM v_order_paid) LIMIT 9"
    rewritten = (
        "SELECT a FROM v_shop WHERE shop_id IN "
        "(SELECT shop_id FROM v_order_paid WHERE v_order_paid.pay_status = 'paid') LIMIT 9"
    )
    ok, detail = rt._semantics_preserved(original, rewritten, ["pay_status = 'paid'"])
    assert ok is True, detail


def test_a_predicate_the_gate_dropped_is_reported_as_not_equivalent():
    """反例：真删了条件必须判不等 —— 否则整个判据就成了恒真。"""
    ok, detail = rt._semantics_preserved(
        "SELECT a FROM t WHERE b > 0 LIMIT 5", "SELECT a FROM t LIMIT 5", ()
    )
    assert ok is False and "仍不等" in detail


def test_widened_limit_is_not_equivalent():
    ok, detail = rt._semantics_preserved(
        "SELECT a FROM t LIMIT 10", "SELECT a FROM t LIMIT 100", ()
    )
    assert ok is False and "LIMIT 被放大" in detail


def test_both_sides_without_limit_is_a_contract_breach_not_a_pass():
    """改写级闸门的**职责**是注入上界；两侧都没有 ⇒ 无法证明等价。"""
    ok, detail = rt._semantics_preserved("SELECT a FROM t", "SELECT a FROM t", ())
    assert ok is False and "无 LIMIT" in detail


def test_only_qualifier_differences_pass_on_the_loose_tier_and_say_so():
    ok, detail = rt._semantics_preserved(
        "SELECT SUM(pay_amount) FROM v_order_paid LIMIT 10",
        "SELECT SUM(v_order_paid.pay_amount) FROM v_order_paid LIMIT 10",
        (),
    )
    assert ok is True and "宽松档" in detail, "宽松档必须**显式出现在结论里**，不能静默等价"


def test_changed_aggregate_is_not_equivalent_even_after_stripping():
    ok, _ = rt._semantics_preserved(
        "SELECT SUM(pay_amount) FROM t LIMIT 3",
        "SELECT AVG(pay_amount) FROM t LIMIT 3",
        (),
    )
    assert ok is False


def test_unparsable_side_is_not_silently_equivalent():
    ok, detail = rt._semantics_preserved("SELECT a FROM t LIMIT 3", "SELEKT ?& FROM", ())
    assert ok is False and "解析失败" in detail


# ==== 三、终态形状推导（docstring §二 的映射表）=======================
@pytest.mark.parametrize(
    ("facts", "want"),
    [
        ({"rejected_at": "gate1"}, "error"),
        ({"rejected_at": "gate2", "gate2_refuse_reason": "out_of_scope"}, "refuse"),
        ({"rejected_at": "gate2", "gate2_refuse_reason": None}, "error"),
        ({"rejected_at": "gate3"}, "error"),
        ({"rejected_at": None, "executed": True}, "executed"),
        ({"rejected_at": None, "executed": False}, None),
    ],
)
def test_terminal_shape_follows_the_online_branches(facts, want):
    assert rt._terminal_shape(_facts(**facts)) == want


# ==== 四、_judge：无判据必须说出来，不许折算成 PASS ===================
def test_blocked_and_not_blocked_are_mirror_assertions():
    assert rt._judge("blocked", _case(), _facts(rejected_at="gate1"), []).status == "PASS"
    assert rt._judge("blocked", _case(), _facts(rejected_at=None), []).status == "FAIL"
    assert rt._judge("not_blocked", _case(), _facts(rejected_at=None), []).status == "PASS"
    assert rt._judge("not_blocked", _case(), _facts(rejected_at="gate2"), []).status == "FAIL"


def test_rule_id_assertion_reads_gate1_then_gate2():
    case = _case(rule_ids=["R07"])
    assert rt._judge("rule_id=R07", case, _facts(gate1_rule_id="R07"), []).status == "PASS"
    assert rt._judge("rule_id=R07", case, _facts(gate1_rule_id=None, gate2_rule_id="R07"), []).status == "PASS"
    assert rt._judge("rule_id=R07", case, _facts(gate1_rule_id="R06"), []).status == "FAIL"


def test_rule_ids_containing_assertion_is_not_checked_without_rule_ids():
    c = rt._judge(
        "response_rule_ids_contains_configured_rule", _case(rule_ids=[]), _facts(gate1_rule_id="R06"), []
    )
    assert c.status == "NOT_CHECKED" and "未配 rule_ids" in c.detail


def test_executed_after_a_rejection_is_a_fail_but_a_silent_stop_is_not_checked():
    """被闸门拦下 ⇒ 断言"应执行"确实错了；链断了但没拒绝 ⇒ 说不清，`NOT_CHECKED`。"""
    assert rt._judge("executed", _case(), _facts(rejected_at="gate1", executed=False), []).status == "FAIL"
    c = rt._judge("executed", _case(), _facts(rejected_at=None, executed=False, exec_error="OperationalError"), [])
    assert c.status == "NOT_CHECKED" and "OperationalError" in c.detail


def test_no_rows_without_execution_is_not_a_pass_for_isolation():
    """🔴 0 行若来自"根本没执行"，就不能当作 RLS 生效的证据（G-4 是另一条门禁）。"""
    c = rt._judge("no_rows_from_other_tenant", _case(), _facts(row_count=None, rejected_at="gate1"), [])
    assert c.status == "NOT_CHECKED" and "不是由 RLS 保证" in c.detail


def test_truncated_assertions_need_a_real_result_set():
    assert rt._judge("truncated_true", _case(), _facts(row_count=None), []).status == "NOT_CHECKED"
    assert rt._judge("truncated_false", _case(), _facts(row_count=3, truncated=False), []).status == "PASS"
    assert rt._judge("truncated_true", _case(), _facts(row_count=3, truncated=False), []).status == "FAIL"


def test_cost_gate_assertions_are_never_checked_in_the_sandbox():
    """沙箱无 EXPLAIN ⇒ gate3 恒 SKIPPED。任何"成本判定通过"的说法在这里都不许成立。"""
    c = rt._judge("cost_gate_tripped", _case(), _facts(gate3_decision="skipped"), [])
    assert c.status == "NOT_CHECKED" and "生产阈值判定未测" in c.detail


def test_gate_status_not_evaluated_accepts_skipped_and_warn_only():
    for d, want in (("skipped", "PASS"), ("warn", "PASS"), ("reject", "FAIL"), ("pass", "FAIL")):
        c = rt._judge("must_not_report_pass", _case(), _facts(gate3_decision=d), [])
        assert c.status == want, f"gate3={d} → {c.status}"


def test_descriptive_and_online_only_assertions_are_separated_but_both_not_checked():
    """两类 NOT_CHECKED 的**原因不同**，落盘必须能区分（一个是用例写法问题，一个是能力缺口）。"""
    d = rt._judge("语义等价", _case(), _facts(), [])
    o = rt._judge("audit_written", _case(), _facts(), [])
    assert d.status == o.status == "NOT_CHECKED"
    assert "描述性" in d.detail and "在线链路" in o.detail


def test_an_unknown_assertion_is_not_checked_and_echoes_the_original_text():
    c = rt._judge("made_up_assertion_xyz", _case(), _facts(), [])
    assert c.status == "NOT_CHECKED" and "made_up_assertion_xyz" in c.detail


def test_comment_stripped_and_limit_assertions_read_gate1_facts():
    assert rt._judge("comment_stripped", _case(), _facts(gate1_comments_stripped=True), []).status == "PASS"
    assert rt._judge("limit_injected", _case(), _facts(gate1_limit_injected={"injected": True}), []).status == "PASS"
    c = rt._judge(
        "limit_clamped", _case(),
        _facts(gate1_limit_injected={"original_limit": 999999},
               rewritten_sql="SELECT 1 LIMIT 5000"),
        [],
    )
    assert c.status == "PASS" and str(rt.MAX_ROWS_HARD_LIMIT) in c.detail


def test_limit_clamped_without_a_numeric_original_limit_is_a_fail():
    c = rt._judge("limit_clamped", _case(), _facts(gate1_limit_injected={}, rewritten_sql="SELECT 1 LIMIT 5"), [])
    assert c.status == "FAIL" and "未记录到数值型原 LIMIT" in c.detail


def test_row_count_equals_limit_needs_both_sides():
    ok = rt._judge("row_count == limit", _case(), _facts(row_count=5, rewritten_sql="SELECT 1 LIMIT 5"), [])
    assert ok.status == "PASS"
    bad = rt._judge("row_count == limit", _case(), _facts(row_count=4, rewritten_sql="SELECT 1 LIMIT 5"), [])
    assert bad.status == "FAIL"
    none = rt._judge("row_count == limit", _case(), _facts(row_count=None, rewritten_sql="SELECT 1"), [])
    assert none.status == "NOT_CHECKED"


def test_warning_emitted_must_not_be_short_circuited_to_pass():
    assert rt._judge("warning_emitted", _case(rule_ids=["R11"]),
                     _facts(gate1_warnings=["R11"]), []).status == "PASS"
    assert rt._judge("warning_emitted", _case(rule_ids=["R11"]),
                     _facts(gate1_warnings=["R13"]), []).status == "FAIL"
    assert rt._judge("warning_emitted", _case(rule_ids=[]),
                     _facts(gate1_warnings=[]), []).status == "FAIL"


# ==== 五、泄露词表与文案判据（DoD② / N-11）===========================
def test_leak_vocabulary_covers_physical_logical_and_column_names(harness):
    vocab = rt._leak_vocabulary(harness.loaded)
    assert {"v_order_paid", "order_paid", "pay_amount"} <= vocab
    assert all(len(n) >= 2 for n in vocab), "单字符名会把任何中文文案判成泄露"


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("查询包含 v_order_paid 的 tenant_id", "FAIL"),
        ("当前身份无权访问该数据范围", "PASS"),
        ("", "FAIL"),
        ("订单已支付", "PASS"),
    ],
)
def test_leak_text_judgement(text, want):
    c = rt._judge_leak_text(text, ["v_order_paid", "tenant_id"], "error_text_leak")
    assert c.status == want


def test_leak_scan_respects_identifier_boundaries():
    """中文/字母紧邻不算命中：`uv_order_paidx` 里不许揪出 `order_paid`（误报会让红队整批假红）。"""
    assert rt._judge_leak_text("xv_order_paidy 不可用", ["order_paid"], "a").status == "PASS"
    assert rt._judge_leak_text("见 order_paidx", ["order_paid"], "a").status == "PASS"


def test_leak_assertions_are_routed_by_several_spellings_to_the_same_judge():
    for a in ("error_text_leak_physical_names", "不得回显被屏蔽的列名", "不泄露表是否存在"):
        c = rt._judge(a, _case(), _facts(gate1_reason="表 v_order_paid 不可用"), ["v_order_paid"])
        assert c.status == "FAIL", f"{a} 未走泄露判据"


# ==== 六、闸门判据的取用面（结构面顶面已由生产自己负责）================
def test_gate2_runs_on_the_plain_port_without_any_bundle_trick(harness):
    """红队事实采集现在只喂**裸端口** ⇒ 这条钉住"不需要代理也能跑通"这件事。

    前身是两条测 `StructuralAllowlistBundle` / `structural_wrapper` 的测试。删掉它们的
    理由不是"代码少了好"：那两个符号会让评测读到**和生产不同**的列面，而两侧读数看
    起来都自洽（`c76f701` 之后生产自己顶结构面，代理就成了纯噪声源）。
    留一条正向断言，是为了让"生产哪天又不生效"立刻在这里红，而不是回到红队产物里翻。
    """
    al = H.identity_for_case("T-RT", "T_A", role=H.Role.ANALYST)
    r = run_gate2("SELECT pay_amount FROM v_order_paid", al, harness.semantics)
    assert r.gate_result.decision.value == "pass", (
        f"生产端口上的 gate2 判成 {r.gate_result.decision.value}"
        f"（{r.gate_result.rule_id} / {r.gate_result.reason}）⇒ ⑤ 的双向断言又读错面了"
    )


def test_structural_face_is_widest_for_every_active_physical_asset(harness):
    """端口自己给的两面：`all_columns` ⊇ `columns`，且被 deny 的列只出现在结构面。"""
    visible = harness.runtime.guard_allowlist(
        H.identity_for_case("RT-STRUCT", "T_A"), max_rows=None
    )
    assert visible["assets"], "端口没给 assets ⇒ 后面的比较全是空转"
    widened = 0
    for physical, entry in visible["assets"].items():
        cols, all_cols = set(entry["columns"]), set(entry["all_columns"])
        assert cols <= all_cols, f"{physical} 的可见面不是结构面子集（deny 裁剪失效或被绕过）"
        if cols != all_cols:
            widened += 1
    assert widened, "没有任何资产被 deny 裁过列 ⇒ 这条测试的靶子没了，改测试而不是删断言"


# ==== 七、失败分桶（报告读它，不能把用例问题读成产品缺陷）===========
@pytest.mark.parametrize(
    ("assertion", "label"),
    [
        ("refuse", "终态形状（refuse vs error）"),
        ("not_rendered_as_error", "终态形状（refuse vs error）"),
        ("response_rule_ids_contains_configured_rule", "规则身份归因（rule_id）"),
        ("rule_id=R06", "规则身份归因（rule_id）"),
        ("truncated_true", "截断可观测性（truncated）"),
        ("executed", "可执行前提（用例假设能跑到 DB）"),
        ("rewritten_semantics_equivalent", "改写语义等价"),
        ("whatever_else", "其他"),
    ],
)
def test_failure_classes(assertion, label):
    assert rt._failure_class(assertion) == label


def test_failure_class_buckets_cover_every_bucketed_assertion_name():
    """`_FAILURE_CLASSES` 的桶名唯一，且桶里的断言名不许重复归类（重复 = 先命中者生效，另一条永远进不了桶）。"""
    seen: list[str] = []
    labels = []
    for label, names in rt._FAILURE_CLASSES:
        labels.append(label)
        seen.extend(names)
    assert len(labels) == len(set(labels))
    assert len(seen) == len(set(seen)), f"同一断言被两个桶认领：{[x for x in seen if seen.count(x) > 1]}"


# ==== 八、小工具的行为钉死 ===========================================
@pytest.mark.parametrize(
    ("sql", "want"),
    [
        ("SELECT 1 LIMIT 5", 5),
        ("SELECT 1 LIMIT '5'", None),
        ("SELECT 1", None),
        ("WITH t AS (SELECT 1 LIMIT 3) SELECT 1", None),
    ],
)
def test_top_limit_value_only_reads_the_top_level_literal(sql, want):
    import sqlglot

    assert rt._top_limit_value(sqlglot.parse_one(sql, read="postgres")) == want


def test_unqualified_drops_table_qualifiers_and_copies_first():
    import sqlglot

    tree = sqlglot.parse_one("SELECT t.a FROM t WHERE t.b = 1", read="postgres")
    before = tree.sql(dialect="postgres")
    assert rt._unqualified(tree) == "SELECT a FROM t WHERE b = 1"
    assert tree.sql(dialect="postgres") == before, "_unqualified 必须 copy 后再改，不许原地污染"


def test_strip_comments_removes_comments_from_every_node_not_just_the_root():
    import sqlglot

    tree = sqlglot.parse_one("SELECT /* hi */ a -- tail\nFROM t", read="postgres")
    assert any(getattr(n, "comments", None) for n in tree.walk())
    rt._strip_comments(tree)
    assert not any(getattr(n, "comments", None) for n in tree.walk())
    assert "hi" not in tree.sql(dialect="postgres")


def test_result_as_dict_counts_are_consistent_with_checks():
    r = rt.RedTeamCaseResult(
        case_id="X", rule_ids=(), expected_outcome="block", covered=True, blocked=True,
        reject_gate="gate1", rule_id="R06", terminal_shape="error", leaked=False,
        executed=False, row_count=None,
        checks=(rt.Check("a", "PASS", ""), rt.Check("b", "FAIL", ""), rt.Check("c", "NOT_CHECKED", "")),
    )
    d = r.as_dict()
    assert (d["n_pass"], d["n_fail"], d["n_not_checked"]) == (1, 1, 1)
    assert d["checks"][0] == {"assertion": "a", "status": "PASS", "detail": ""}
    assert d["facts"] == {} and "attack_sql" not in d
