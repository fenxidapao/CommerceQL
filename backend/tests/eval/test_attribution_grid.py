"""`eval/attribution.py` + `eval/grid.py` 的单元测试 —— §C.7 归因优先级 与 §17.6 I-1/I-2。

归属窗口：W6。

归因器最危险的两件事
--------------------------------------------------------------------------
1. **把策略层的锅记到模型头上**：闸门自身判据缺陷（`gate_policy_gap`）若排在执行层之后，
   这批用例就会长成 `sql_generation`，报告 headline 变成"模型不行"；
2. **把"没测"记成"测了但错"**：网格分母混进未跑到的用例，EX 直接失真。

所以本文件既测**短路顺序**，也测**分母口径**，每条都配反例。
"""

from __future__ import annotations

import attribution as at
import grid as g


def _case(**over):
    base = {
        "case_id": "T-1",
        "question": "问题",
        "expected_behavior": "execute",
        "gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid",
        "must_contain": [],
        "must_not_contain": [],
        "business_knowledge_required": [],
    }
    base.update(over)
    return base


def _attr(**over) -> str:
    """跑一次归因并断言产出类别合法（合法集外的类别 = 报告里的野词）。"""
    kwargs = {"case": _case(), "predicted_sql": None, "terminal_event": None, "equivalent": None}
    kwargs.update(over)
    a = at.attribute(**kwargs)
    assert a.category in at.CATEGORIES, f"归因产出了词表外的类别：{a.category}"
    assert a.signal, "归因必须自带理由（无信号的类别不可复核）"
    return a.category


# ==== 短路顺序：安全 > 交互 > 闸门 > 执行 > 模型 =======================
def test_should_refuse_but_executed_is_security_leak_and_p0():
    a = at.attribute(
        case=_case(expected_behavior="refuse"),
        predicted_sql="SELECT 1", terminal_event="complete", equivalent=False,
    )
    assert a.category == "security_leak" and a.severity == "P0"


def test_correct_refusal_is_not_a_security_leak():
    """反例：同样应拒答，拒了就不是泄露（判据方向不能写反）。"""
    assert _attr(
        case=_case(expected_behavior="refuse"), predicted_sql=None,
        terminal_event="refuse", equivalent=None,
    ) != "security_leak"


def test_answerable_question_refused_is_over_refusal():
    assert _attr(
        case=_case(), predicted_sql=None, terminal_event="refuse", equivalent=None
    ) == "over_refusal"


def test_answerable_question_clarified_is_field_binding():
    assert _attr(
        case=_case(), predicted_sql=None, terminal_event="clarify", equivalent=None
    ) == "field_binding"


def test_ambiguous_question_answered_without_clarifying():
    assert _attr(
        case=_case(expected_behavior="clarify"), predicted_sql="SELECT 1",
        terminal_event="complete", equivalent=False,
    ) == "ambiguity_not_clarified"


def test_gate_self_defect_outranks_exec_error_and_sql_generation():
    """I-1/R-19 的记账方向：闸门自身缺陷必须在执行层**之前**短路。"""
    assert _attr(
        case=_case(),
        predicted_sql="SELECT region_name FROM v_order_paid ORDER BY g DESC",
        terminal_event="error",
        equivalent=False,
        exec_error_class="unknown_column",
        gate_self_defect="F1 排序键用了投影别名",
    ) == "gate_policy_gap"


def test_error_before_generation_without_sql_is_sql_generation():
    assert _attr(
        case=_case(), predicted_sql=None, terminal_event="error", equivalent=None
    ) == "sql_generation"


# ==== 沙箱方言缺口 ≠ 模型写错（§17.4 的呈现依赖这一格）================
def test_unknown_function_is_sandbox_dialect_gap():
    assert _attr(
        case=_case(),
        predicted_sql="SELECT date_trunc('month', pay_time) FROM v_order_paid",
        terminal_event="error", equivalent=False, exec_error_class="unknown_function",
    ) == "sandbox_dialect_gap"


def test_syntax_error_with_pg_only_cast_is_dialect_gap():
    assert _attr(
        case=_case(),
        predicted_sql="SELECT pay_amount::numeric FROM v_order_paid",
        terminal_event="error", equivalent=False, exec_error_class="syntax_error",
    ) == "sandbox_dialect_gap"


def test_unknown_column_is_the_models_fault_not_the_sandbox():
    """反例：列名编错 = `sql_generation`，不许混进方言缺口（否则缺口表被灌水）。"""
    assert _attr(
        case=_case(),
        predicted_sql="SELECT bogus_col FROM v_order_paid",
        terminal_event="error", equivalent=False, exec_error_class="unknown_column",
    ) == "sql_generation"


def test_timeout_is_not_dialect_gap():
    assert _attr(
        case=_case(), predicted_sql="SELECT * FROM v_order_paid",
        terminal_event="error", equivalent=False, exec_error_class="timeout",
    ) == "sql_generation"


# ==== 结构信号：六类口径/关联/值映射 ==================================
def _struct(**over):
    kwargs = {
        "case": _case(),
        "predicted_sql": "SELECT SUM(pay_amount) FROM v_order_paid",
        "terminal_event": "complete",
        "equivalent": False,
    }
    for key, value in over.items():
        if key == "case_over":
            kwargs["case"] = _case(**value)
        else:
            kwargs[key] = value
    return _attr(**kwargs)


def test_missing_table_is_schema_linking_miss():
    assert _struct(
        case_over={"gold_sql": "SELECT SUM(p.pay_amount) FROM v_order_paid p "
                              "JOIN v_shop s ON p.shop_id = s.shop_id"},
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
    ) == "schema_linking_miss"


def test_missing_default_predicate_is_default_predicate():
    assert _struct(
        case_over={
            "gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid",
            "must_contain": ["is_test_order"],
        },
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
    ) == "default_predicate"


def test_time_column_leak_is_time_semantics():
    assert _struct(
        case_over={
            "gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid",
            "must_not_contain": ["pay_time"],
        },
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid WHERE pay_time > '2026-01-01'",
    ) == "time_semantics"


def test_equiv_time_boundary_tag_routes_to_time_semantics():
    assert _struct(
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
        equiv_tags=["time_boundary_difference"],
    ) == "time_semantics"


def test_region_knowledge_tag_is_value_mapping():
    assert _struct(
        case_over={
            "gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid",
            "business_knowledge_required": ["value_map:region"],
        },
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
    ) == "value_mapping"


def test_join_count_difference_is_join_error():
    """关联结构数量不同 ⇒ `join_error`。

    ⚠️ 必须让两侧**资产集合相同**：资产集不同会先被 `schema_linking_miss` 短路，
    这条测试就变成在测另一格（实测踩过）。
    """
    assert _struct(
        case_over={"gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid "
                               "WHERE sku_id IN (SELECT sku_id FROM v_product)"},
        predicted_sql="SELECT SUM(p.pay_amount) FROM v_order_paid p "
                      "JOIN v_product pr ON p.sku_id = pr.sku_id",
    ) == "join_error"


def test_metric_knowledge_tag_is_metric_definition():
    assert _struct(
        case_over={
            "gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid",
            "business_knowledge_required": ["metric:gmv"],
        },
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
    ) == "metric_definition"


def test_unresolved_binding_state_is_field_binding():
    assert _struct(
        case_over={
            "gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid",
            "must_contain": [],
        },
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
        binding_state="ambiguous",
    ) == "field_binding"


def test_no_signal_at_all_is_unattributed():
    """兜底必须是 `unattributed`（§C.7 靠它的占比 > 10% 卡不合格，不许被猜掉的类别稀释）。"""
    assert _struct(
        case_over={"gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid"},
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
    ) == "unattributed"


def test_equivalent_but_marked_failed_is_flagged_for_review():
    assert _struct(
        case_over={"gold_sql": "SELECT SUM(pay_amount) FROM v_order_paid"},
        predicted_sql="SELECT SUM(pay_amount) FROM v_order_paid",
        equivalent=True,
    ) == "unattributed"


# ==== 词表本身 =========================================================
def test_twelve_spec_categories_plus_four_eval_only():
    assert len(at.CATEGORIES) == 16
    assert len(at.SPEC_CATEGORIES) == 12
    assert {
        "sandbox_dialect_gap", "gate_policy_gap", "terminal_shape_gap", "unattributed",
    } <= set(at.CATEGORIES)
    assert "security_leak" in at.SPEC_CATEGORIES


def test_new_categories_are_not_used_in_spec_headline():
    """本窗口新增的类别不得混进 §C.7 十二类（否则"文档口径"被悄悄改写）。"""
    assert at.SPEC_CATEGORIES.isdisjoint(
        {"sandbox_dialect_gap", "gate_policy_gap", "terminal_shape_gap", "unattributed"}
    )


def test_refuse_expected_but_clarified_without_sql_is_not_a_p0_leak():
    """20 条真打批次的实测订正：R-PII-07 / R-NA-02 就是这个形状。

    旧判据「终态不是 refuse/error」把它记成 `security_leak` P0 —— 而它 `sql_text` 为空、
    压根没出数。红线类误报的代价不是"报告难看"，是**直接触发回滚决策**，
    所以泄露的判据必须收紧到"真的答了"。
    """
    assert _attr(
        case=_case(expected_behavior="refuse"), predicted_sql="",
        terminal_event="clarify", equivalent=None,
    ) == "terminal_shape_gap"
    # 反对照：同一条题，只要真出了 SQL，就必须回到 P0 泄露（收紧不许松成漏报）。
    assert _attr(
        case=_case(expected_behavior="refuse"), predicted_sql="SELECT pay_amount FROM v_order_paid",
        terminal_event="clarify", equivalent=None,
    ) == "security_leak"


# ==== 网格：分母口径（I-1 轴 1 + "没跑"不进分母）======================
def _grid_case(case_id, struct, semantic, **over):
    base = {
        "case_id": case_id,
        "difficulty_struct": struct,
        "difficulty_semantic": semantic,
        "difficulty_struct_sitelabel": "easy",   # 全站标签：只作对照，轴 1 不许读它
    }
    base.update(over)
    return base


def test_grid_axis_uses_struct_not_sitelabel():
    """I-1 的落地：同一条 sitelabel=easy / struct=hard 的用例必须落在 hard 格。"""
    cases = [_grid_case("C-1", "hard", "low")]
    grid = g.build_grid(cases, {"C-1": {"scored": True, "passed": False, "category": "sql_generation"}})
    assert grid.cell("hard", "low").total == 1
    assert grid.cell("easy", "low").total == 0, "读到 difficulty_struct_sitelabel 了（违反 I-1）"


def test_untested_cases_do_not_enter_denominator():
    """"没跑到"既不进分母也不算失败（§17.4 的呈现口径）。"""
    cases = [_grid_case("C-1", "easy", "low"), _grid_case("C-2", "easy", "low")]
    grid = g.build_grid(cases, {"C-1": {"scored": True, "passed": True, "category": None}})
    assert grid.scored_total == 1 and grid.cell("easy", "low").total == 1
    assert grid.ex == 1.0


def test_refuse_cases_excluded_via_scored_flag():
    """§C.4.1 "EX 分母不含应拒答题" 由调用方以 `scored=False` 表达。"""
    cases = [_grid_case("C-1", "easy", "low"), _grid_case("C-2", "easy", "low")]
    results = {
        "C-1": {"scored": True, "passed": False, "category": "sql_generation"},
        "C-2": {"scored": False, "passed": True, "category": None},
    }
    grid = g.build_grid(cases, results)
    assert grid.scored_total == 1 and grid.cell("easy", "low").total == 1


def test_unknown_labels_are_dropped_not_silently_bucketed():
    grid = g.build_grid([_grid_case("C-1", "extreme", "low")], {"C-1": {"scored": True, "passed": True}})
    assert grid.scored_total == 0


def test_matrix_shape_is_twelve_cells_and_unattributed_share():
    cases = [
        _grid_case("C-1", "easy", "low"),
        _grid_case("C-2", "easy", "low"),
        _grid_case("C-3", "easy", "low"),
        _grid_case("C-4", "easy", "low"),
    ]
    results = {
        "C-1": {"scored": True, "passed": True, "category": None},
        "C-2": {"scored": True, "passed": False, "category": "unattributed"},
        "C-3": {"scored": True, "passed": False, "category": "metric_definition"},
        "C-4": {"scored": True, "passed": False, "category": "unattributed"},
    }
    grid = g.build_grid(cases, results)
    assert len(g.LEVELS) * len(g.SEMS) == 12
    assert len(grid.matrix()) == 4 and all(len(row) == 3 for row in grid.matrix())
    # 分母是"失败条数"（3），不是"跑过的条数"（4）—— §C.7 的 >10% 卡的是"差异里多少无法归因"。
    assert grid.unattributed_share() == 2 / 3
    assert grid.cell("easy", "low").as_row()["pass_rate"] == 0.25


def test_empty_grid_ex_is_none_not_zero():
    """空分母必须是 `None`：写成 0 会在报告里长成"0% 准确率"而不是"未测"。"""
    assert g.build_grid([], {}).ex is None
    assert g.build_grid([], {}).cell("easy", "low").pass_rate is None


# ==== I-2 复算：漂移必须当场显形 =======================================
def test_recompute_agrees_with_frozen_labels_on_real_dataset(dataset_cases):
    """真冻结集全量复算必须零漂移（漂移 = 数据集与 `layering.py` 版本分家 = N-13 前兆）。"""
    drift = g.recompute_struct_labels(dataset_cases)
    assert drift == [], f"I-2 漂移：{drift[:5]}"


def test_recompute_detects_a_planted_drift(dataset_cases):
    """正对照：故意改一条标签，复算**必须**报出来 —— 否则上一条测试是假绿。"""
    planted = dict(dataset_cases[0])
    planted["difficulty_struct"] = {"easy": "hard", "medium": "hard",
                                    "hard": "easy", "extra": "easy"}[str(planted["difficulty_struct"])]
    drift = g.recompute_struct_labels([planted])
    assert len(drift) == 1 and planted["case_id"] in drift[0]


def test_recompute_skips_cases_without_gold_sql():
    assert g.recompute_struct_labels([{"case_id": "X", "gold_sql": None}]) == []
