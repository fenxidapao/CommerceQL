"""gate1（AST 审计 + LIMIT 注入 + 默认谓词注入）单元测试（W2C）。

告警级规则（R17–R20）的断言方式与阻断级**相反**（U-16）：
必须断言"产生告警且查询继续"—— 写成拒绝即实现缺陷。
"""

from __future__ import annotations

import pytest

from app.core.enums import AstRule, GateDecision
from app.guard.ast_gate import MAX_ROWS_HARD_LIMIT, run_gate1, strip_comments
from tests.unit.guard_fixtures import build_allowlist


@pytest.fixture(scope="module")
def allow() -> dict:
    return build_allowlist()


# ---------------------------------------------------------------------------
# 剥注释（R15）
# ---------------------------------------------------------------------------

class TestStripComments:
    def test_block_comment_removed(self) -> None:
        assert strip_comments("SELECT/*x*/ 1") == "SELECT  1"

    def test_line_comment_removed_to_eol(self) -> None:
        # 行注释终止于换行符；换行后的内容是活语句（不是注释的一部分）
        assert strip_comments("SELECT 1;--\n DROP") == "SELECT 1;\n DROP"

    def test_comment_with_quote_does_not_break_strings(self) -> None:
        # 07 §7.8 R15：注释内的引号不得破坏字符串边界
        stripped = strip_comments("SELECT 'a' /*'*/ FROM t")
        assert "'a'" in stripped
        assert "/*" not in stripped

    def test_string_content_preserved(self) -> None:
        assert "a--b" in strip_comments("SELECT 'a--b'")

    def test_dollar_quoted_preserved(self) -> None:
        assert "$$a/*b*/c$$" in strip_comments("SELECT $$a/*b*/c$$")


# ---------------------------------------------------------------------------
# 阻断级规则（逐条：红队 RT-xx 对应用例）
# ---------------------------------------------------------------------------

class TestBlockingRules:
    def test_r01_dml_rejected(self, allow: dict) -> None:
        r = run_gate1("UPDATE v_order_paid SET pay_amount = 0 WHERE shop_id = 'S1'", allow)
        assert not r.passed and r.gate_result.rule_id == "R01"

    def test_r01_ddl_rejected(self, allow: dict) -> None:
        r = run_gate1("CREATE TABLE t AS SELECT 1", allow)
        assert not r.passed and r.gate_result.rule_id == "R01"

    def test_r02_multi_statement(self, allow: dict) -> None:
        r = run_gate1("SELECT 1; DROP TABLE v_order_paid", allow)
        assert not r.passed and r.gate_result.rule_id == "R02"

    def test_r02_hidden_after_line_comment(self, allow: dict) -> None:
        r = run_gate1("SELECT COUNT(*) FROM v_shop;-- DELETE FROM v_order_paid", allow)
        # 注释吞掉行尾 → 只剩一条语句 → 不因 R02 拒（R15 改写级语义）
        assert r.passed

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM v_order_paid",
            "SELECT v_order_paid.* FROM v_order_paid",
            "SELECT o.* FROM v_order_paid o",
        ],
    )
    def test_r03_select_star(self, allow: dict, sql: str) -> None:
        r = run_gate1(sql, allow)
        assert not r.passed and r.gate_result.rule_id == "R03"

    def test_r03_count_star_allowed(self, allow: dict) -> None:
        # COUNT(*) 的 Star 不是投影项 → 不得拒绝（§7.8 断言纪律的反例保护）
        r = run_gate1("SELECT COUNT(*) FROM v_order_paid", allow)
        assert r.passed

    @pytest.mark.parametrize(
        "sql",
        ["SELECT COUNT(*) FROM raw_order_dump", "SELECT COUNT(*) FROM v_order_paid_raw"],
    )
    def test_r05_table_allowlist(self, allow: dict, sql: str) -> None:
        r = run_gate1(sql, allow)
        assert not r.passed and r.gate_result.rule_id == "R05"

    def test_r06_unlisted_column(self, allow: dict) -> None:
        r = run_gate1("SELECT secret_margin FROM v_product", allow)
        assert not r.passed and r.gate_result.rule_id == "R06"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT receiver_phone FROM v_order_paid LIMIT 10",
            "SELECT md5(receiver_phone) FROM v_order_paid LIMIT 10",
            "SELECT COUNT(*) FROM v_order_paid WHERE receiver_phone LIKE '138%'",
            "SELECT cost_price FROM v_product LIMIT 10",
        ],
    )
    def test_r07_deny_columns(self, allow: dict, sql: str) -> None:
        r = run_gate1(sql, allow)
        # U-121 判据⑤（07 v1.6.8）：可见面已裁 deny 列 ⇒ 无表别名形态归 R06
        # （归属失败）、限定/别名形态归 R07 —— 两者都必须拒，且**禁止分裂出
        # 第三种码**；单值断言 R07 只在可见面裁剪前的旧夹具下成立。
        assert not r.passed and r.gate_result.rule_id in {"R06", "R07"}

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT table_name FROM information_schema.tables",
            "SELECT * FROM pg_catalog.pg_tables",
            "SELECT COUNT(*) FROM pg_temp_3.t",
            "SELECT COUNT(*) FROM pg_toast.pg_toast_12345",
        ],
    )
    def test_r08_system_schema(self, allow: dict, sql: str) -> None:
        r = run_gate1(sql, allow)
        assert not r.passed and r.gate_result.rule_id == "R08"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT pg_sleep(60)",
            "SELECT lo_import('/etc/shadow')",
            "SELECT set_config('app.tenant_id', 'T_B', false)",
            "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(x int)",
        ],
    )
    def test_r09_function_denylist(self, allow: dict, sql: str) -> None:
        r = run_gate1(sql, allow)
        assert not r.passed and r.gate_result.rule_id == "R09"

    def test_r09_nested_in_cte(self, allow: dict) -> None:
        # 07 §7.8：嵌套在 CTE 中的 current_setting 也必须被抓到（全树遍历）
        r = run_gate1(
            "WITH x AS (SELECT current_setting('data_directory') AS d) SELECT d FROM x",
            allow,
        )
        assert not r.passed and r.gate_result.rule_id == "R09"

    def test_r10_unregistered_join_path(self, allow: dict) -> None:
        # order_paid × traffic_daily 被语义包刻意不登记（07 §6.8）
        r = run_gate1(
            "SELECT COUNT(*) FROM v_order_paid o JOIN v_traffic_daily t ON o.sku_id = t.sku_id",
            allow,
        )
        assert not r.passed and r.gate_result.rule_id == "R10"

    def test_r10_cross_join(self, allow: dict) -> None:
        r = run_gate1("SELECT COUNT(*) FROM v_order_paid o CROSS JOIN v_shop s", allow)
        assert not r.passed and r.gate_result.rule_id == "R10"

    def test_r10_join_with_literal_condition(self, allow: dict) -> None:
        r = run_gate1(
            "SELECT COUNT(*) FROM v_order_paid o JOIN v_product p ON 1 = 1", allow
        )
        assert not r.passed and r.gate_result.rule_id == "R10"

    def test_r11_condition_columns_mismatch(self, allow: dict) -> None:
        # product × shop 是认证边（shop_id），用 sku_id = shop_id 连接 = 笛卡尔风险
        r = run_gate1(
            "SELECT COUNT(*) FROM v_product p JOIN v_shop s ON p.sku_id = s.shop_id",
            allow,
        )
        assert not r.passed and r.gate_result.rule_id == "R11"

    def test_r12_recursive_cte(self, allow: dict) -> None:
        r = run_gate1(
            "WITH RECURSIVE t AS (SELECT 1 UNION ALL SELECT 1 FROM t) SELECT 1 FROM t",
            allow,
        )
        assert not r.passed and r.gate_result.rule_id == "R12"

    def test_r13_union_branch_column_violation_is_r13(self, allow: dict) -> None:
        # 红队 RT-R13-001 冻结口径：UNION 分支内 deny 列 → 归因 R13（分支独立过 R07）
        r = run_gate1(
            "SELECT sub_order_id FROM v_order_paid UNION SELECT receiver_phone FROM v_order_paid",
            allow,
        )
        assert not r.passed and r.gate_result.rule_id == "R13"

    def test_r13_union_branch_table_violation_is_r13(self, allow: dict) -> None:
        # 07 §7.2 R13 原文：分支独立过 R05/R06/R07 —— 分支违规统一归因 R13
        r = run_gate1(
            "SELECT sku_id FROM v_product UNION SELECT k FROM raw_order_dump", allow
        )
        assert not r.passed and r.gate_result.rule_id == "R13"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT COUNT(*) FROM v_order_paid WHERE sub_order_id = 'x' OR 1 = 1",
            "SELECT shop_id FROM v_order_paid GROUP BY shop_id HAVING 1 = 1",
            "SELECT COUNT(*) FROM v_product WHERE sku_name LIKE 'A%' OR 'x' = 'x'",
        ],
    )
    def test_r14_tautology_and_free_literals(self, allow: dict, sql: str) -> None:
        r = run_gate1(sql, allow)
        assert not r.passed and r.gate_result.rule_id == "R14"

    def test_r14_column_constant_comparison_allowed(self, allow: dict) -> None:
        # 列-常量比较不是 R14 拒绝位（类型失配交 R17 告警；口径见 ast_gate.py R14 docstring）
        r = run_gate1("SELECT COUNT(*) FROM v_order_paid WHERE shop_id = 'S1'", allow)
        assert r.passed

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT COUNT(*) FROM analytics.public.v_order_paid",
            "SELECT COUNT(*) FROM main.v_order_paid",
        ],
    )
    def test_r16_schema_prefix(self, allow: dict, sql: str) -> None:
        r = run_gate1(sql, allow)
        assert not r.passed and r.gate_result.rule_id == "R16"

    def test_r16_set_local_search_path(self, allow: dict) -> None:
        r = run_gate1("SET LOCAL search_path = evil", allow)
        assert not r.passed and r.gate_result.rule_id == "R16"

    def test_r01_session_set_search_path(self, allow: dict) -> None:
        # 会话级 SET：红队冻结口径 tag = R01（语句形态）；归因消歧见 run_gate1
        r = run_gate1("SET search_path = analytics", allow)
        assert not r.passed and r.gate_result.rule_id == "R01"

    def test_parse_failure_rejected(self, allow: dict) -> None:
        r = run_gate1("SELECT FROM WHERE", allow)
        assert not r.passed


# ---------------------------------------------------------------------------
# 改写级（R04 / R15）：**拒绝即实现缺陷**
# ---------------------------------------------------------------------------

class TestRewriteRules:
    def test_r04_no_limit_injected(self, allow: dict) -> None:
        r = run_gate1("SELECT sub_order_id FROM v_order_paid", allow)
        assert r.passed
        assert r.limit_injected == {"injected": True}
        assert f"LIMIT {MAX_ROWS_HARD_LIMIT}" in r.rewritten_sql

    def test_r04_oversized_limit_capped(self, allow: dict) -> None:
        r = run_gate1("SELECT sub_order_id FROM v_order_paid LIMIT 999999", allow)
        assert r.passed
        assert r.limit_injected == {"injected": True, "original_limit": 999999}
        assert f"LIMIT {MAX_ROWS_HARD_LIMIT}" in r.rewritten_sql

    def test_r04_reasonable_limit_kept(self, allow: dict) -> None:
        r = run_gate1("SELECT sub_order_id FROM v_order_paid LIMIT 10", allow)
        assert r.passed and r.limit_injected is None
        assert "LIMIT 10" in r.rewritten_sql

    def test_r04_limit_all_rewritten(self, allow: dict) -> None:
        # 红队 RT-R04-003 冻结口径 = rewrite（07 §7.3 "拒绝"行的分歧已登记 RELAY）
        r = run_gate1("SELECT sub_order_id FROM v_order_paid LIMIT ALL", allow)
        assert r.passed and r.limit_injected is not None

    def test_r04_limit_zero_rejected(self, allow: dict) -> None:
        # §7.3：LIMIT 0 亦可拒绝（无效查询）—— 红队集无反例
        r = run_gate1("SELECT sub_order_id FROM v_order_paid LIMIT 0", allow)
        assert not r.passed and r.gate_result.rule_id == "R04"

    def test_r04_offset_without_limit(self, allow: dict) -> None:
        r = run_gate1("SELECT sub_order_id FROM v_order_paid OFFSET 10", allow)
        assert r.passed
        assert "OFFSET 10" in r.rewritten_sql
        assert "LIMIT" in r.rewritten_sql

    def test_r04_subquery_limit_still_injects_top(self, allow: dict) -> None:
        # §7.3：子查询 LIMIT 不限制最终行数 —— 顶层仍注入
        r = run_gate1(
            "SELECT sku_id FROM v_product WHERE sku_id IN "
            "(SELECT sku_id FROM v_traffic_daily LIMIT 10)",
            allow,
        )
        assert r.passed and r.limit_injected == {"injected": True}

    def test_r04_max_rows_configurable(self, allow: dict) -> None:
        allow2 = {**allow, "max_rows": 100}
        r = run_gate1("SELECT sub_order_id FROM v_order_paid", allow2)
        assert r.passed and "LIMIT 100" in r.rewritten_sql

    def test_r15_comments_stripped_flag(self, allow: dict) -> None:
        r = run_gate1("SELECT /* 恶意注释 */ COUNT(*) FROM v_order_paid", allow)
        assert r.passed and r.comments_stripped is True

    def test_r15_trailing_comment_rewrites(self, allow: dict) -> None:
        r = run_gate1("SELECT COUNT(*) FROM v_order_paid -- ; DROP TABLE v_order_paid", allow)
        assert r.passed and r.comments_stripped is True


# ---------------------------------------------------------------------------
# 默认谓词注入（先于审计；注入的谓词必须被审计覆盖）
# ---------------------------------------------------------------------------

class TestPredicateInjection:
    def test_predicates_injected_for_orders_domain(self, allow: dict) -> None:
        r = run_gate1("SELECT sub_order_id FROM v_order_paid", allow)
        assert r.passed
        assert "is_test_order = FALSE" in r.rewritten_sql
        assert any("is_test_order" in p for p in r.applied_predicates)

    def test_predicates_qualified_with_alias(self, allow: dict) -> None:
        r = run_gate1("SELECT o.sub_order_id FROM v_order_paid o LIMIT 5", allow)
        assert r.passed
        assert "o.is_test_order = FALSE" in r.rewritten_sql

    def test_no_injection_for_predicate_free_domain(self, allow: dict) -> None:
        # products 域无默认谓词
        r = run_gate1("SELECT sku_name FROM v_product LIMIT 5", allow)
        assert r.passed and r.applied_predicates == ()

    def test_injected_constants_do_not_trip_r14(self, allow: dict) -> None:
        # 注入引入的谓词常量在 R14 白名单（三类来源之②）
        r = run_gate1("SELECT COUNT(*) FROM v_order_paid", allow)
        assert r.passed


# ---------------------------------------------------------------------------
# 告警级（R17–R20）：**必须放行 + 告警**（U-16）
# ---------------------------------------------------------------------------

class TestWarningRules:
    def test_r17_text_column_vs_numeric_literal(self, allow: dict) -> None:
        r = run_gate1("SELECT COUNT(*) FROM v_order_paid WHERE region_code = 440000", allow)
        assert r.passed
        assert AstRule.R17_IMPLICIT_CAST in [w.rule for w in r.warnings]

    def test_r18_unbounded_order_by(self, allow: dict) -> None:
        r = run_gate1("SELECT sku_id FROM v_traffic_daily ORDER BY pv DESC", allow)
        assert r.passed
        assert AstRule.R18_UNBOUNDED_SORT in [w.rule for w in r.warnings]

    def test_r18_bounded_order_by_no_warning(self, allow: dict) -> None:
        r = run_gate1("SELECT sku_id FROM v_traffic_daily ORDER BY pv DESC LIMIT 10", allow)
        assert r.passed
        assert AstRule.R18_UNBOUNDED_SORT not in [w.rule for w in r.warnings]

    def test_r19_deep_nesting(self, allow: dict) -> None:
        sql = (
            "SELECT COUNT(*) FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM "
            "(SELECT * FROM (SELECT * FROM v_order_paid) a) b) c) d) e"
        )
        r = run_gate1(sql, allow)
        assert r.passed
        assert AstRule.R19_SUBQUERY_DEPTH in [w.rule for w in r.warnings]

    def test_r19_shallow_no_warning(self, allow: dict) -> None:
        r = run_gate1(
            "SELECT COUNT(*) FROM (SELECT sub_order_id FROM v_order_paid) e", allow
        )
        assert r.passed
        assert AstRule.R19_SUBQUERY_DEPTH not in [w.rule for w in r.warnings]

    def test_r20_too_many_output_columns(self, allow: dict) -> None:
        cols = ", ".join(f"channel AS c{i}" for i in range(51))
        r = run_gate1(f"SELECT {cols} FROM v_traffic_daily LIMIT 1", allow)
        assert r.passed
        assert AstRule.R20_OUTPUT_COLUMNS in [w.rule for w in r.warnings]

    def test_warn_rules_never_reject(self, allow: dict) -> None:
        # U-16 反向断言：告警级规则的决策不得是 REJECT
        r = run_gate1("SELECT COUNT(*) FROM v_order_paid WHERE region_code = 440000", allow)
        assert r.gate_result.decision is not GateDecision.REJECT
