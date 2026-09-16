"""rules.py 注册表契约测试（W2C）。"""

from __future__ import annotations

import pytest

from app.core.enums import AST_RULE_SEVERITY, AstRule, AstRuleSeverity, ErrorCode
from app.guard.rules import RULES, RULE_BY_ID


class TestRegistryCompleteness:
    def test_covers_all_20_rules(self) -> None:
        assert len(AstRule) == 20
        assert set(RULES) == set(AstRule)

    def test_by_id_index_consistent(self) -> None:
        for rule, rd in RULES.items():
            assert RULE_BY_ID[rd.rule.value] is rd

    def test_severity_matches_enums_source(self) -> None:
        # enums.AST_RULE_SEVERITY 是处置级别的唯一真相；rules.py 不得复制出第二份
        for rule, rd in RULES.items():
            assert rd.severity == AST_RULE_SEVERITY[rule]

    def test_blocking_rules_have_error_code(self) -> None:
        from app.core.enums import AST_BLOCKING_RULES

        for rule in AST_BLOCKING_RULES:
            assert RULES[rule].error_code is not None

    def test_rewrite_and_warn_rules_have_no_error_code(self) -> None:
        from app.core.enums import AST_REWRITE_RULES, AST_WARNING_RULES

        for rule in (*AST_REWRITE_RULES, *AST_WARNING_RULES):
            assert RULES[rule].error_code is None

    def test_error_codes_are_gate_family(self) -> None:
        allowed = {ErrorCode.GATE_AST_REJECTED, ErrorCode.FORBIDDEN_SCOPE, ErrorCode.PII_BLOCKED}
        for rd in RULES.values():
            if rd.error_code is not None:
                assert rd.error_code in allowed


class TestNoSchemaLeakageInUserMessages:
    """DoD②：每条规则的用户文案不得泄露 schema 细节（表名/列名/schema 前缀）。"""

    @pytest.mark.parametrize("rule", list(AstRule))
    def test_message_has_no_identifiers(self, rule: AstRule) -> None:
        msg = RULES[rule].user_message
        forbidden_markers = (
            "v_order", "v_product", "v_shop", "v_traffic", "v_region",
            "v_campaign", "v_dim_date", "order_paid", "traffic_daily",
            "information_schema", "pg_catalog", "pg_temp", "pg_toast",
            "receiver_phone", "cost_price", "tenant_id", "sku", "shop_id",
            "SELECT", "FROM", "WHERE",
        )
        for marker in forbidden_markers:
            assert marker.lower() not in msg.lower(), (
                f"{rule.value} 文案疑似泄露 schema 细节：{msg!r}"
            )

    def test_r14_is_marked_internal_only(self) -> None:
        # 07 §7.6：R14 到达用户 = 渲染层 bug → 文案必须标 internal_only
        assert RULES[AstRule.R14_LITERAL_POLICY].internal_only is True

    def test_non_r14_messages_not_internal(self) -> None:
        for rule, rd in RULES.items():
            if rule is not AstRule.R14_LITERAL_POLICY:
                assert rd.internal_only is False
