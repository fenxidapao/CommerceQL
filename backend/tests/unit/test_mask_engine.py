"""mask 引擎单测（W2D / 07 §8.7）。

纪律（沿用 W1B 固化的两条）：
1. 凡断言"某条规则被走了"，必须做一次**注入 → 必红 → 还原 → 必绿**的负向对照，
   并看清红的确实是目标断言（不是邻居红）；
2. 替身/夹具不得为被断言的参数提供值。
"""

from __future__ import annotations

import pytest

from app.core.errors import CommerceQLError
from app.mask import (
    KNOWN_RULE_FORMS,
    SENSITIVITY_TAGS,
    MaskFailed,
    SemanticMaskEngine,
    resolve_rule_for_column,
)
from app.mask.rules import mask_address, mask_email, mask_id_card, mask_name, mask_phone

ENGINE = SemanticMaskEngine()


def _policy(*columns: tuple[str, str | None]) -> dict:
    return {
        "columns": [{"name": n, "sensitivity": s} for n, s in columns],
        "mask_rules": [{"column_pattern": ".*phone.*", "rule": "***-***-1234"}],
    }


# ============================================================================
# 默认规则函数（07 §8.7 表逐行）
# ============================================================================


def test_mask_phone_keeps_last4():
    assert mask_phone("13812345678") == "***-***-5678"


def test_mask_email_keeps_first_char_and_domain():
    assert mask_email("user01@example.com") == "u****@example.com"


def test_mask_email_without_at_fails_closed():
    with pytest.raises(Exception) as ei:
        mask_email("not-an-email")
    assert not isinstance(ei.value, MaskFailed)  # 引擎层统一转 MaskFailed


def test_mask_id_card_keeps_last4():
    assert mask_id_card("440101199001011234") == "***-**-1234"


def test_mask_address_keeps_admin_prefix():
    assert mask_address("广东省深圳市南山区科技园路1号") == "广东省深圳市南山区***"
    # 直辖市（无"省"级）同样成立
    assert mask_address("北京市朝阳区建国路88号") == "北京市朝阳区***"
    # 无行政区划边界 → 保守前缀
    assert mask_address("somewhere road 123") == "somewh***"


def test_mask_name_keeps_surname():
    assert mask_name("张三丰") == "张*"


# ============================================================================
# 规则判定：列身份为主、正则覆盖为辅（07 §8.7 硬规则 3）
# ============================================================================


def test_sensitivity_is_primary_judge():
    # 列名不匹配任何 mask_rules 正则，仅凭敏感标签也要打码
    assert resolve_rule_for_column(sensitivity="pii_phone", matched_rule_form=None) == "phone"


def test_regex_overlay_applies_to_non_tagged_column():
    # 列无敏感标签，但列名命中语义包覆盖正则 → 按已知形态打码
    assert resolve_rule_for_column(sensitivity=None, matched_rule_form="***-***-1234") == "phone"


def test_unknown_rule_form_raises_not_guesses():
    with pytest.raises(Exception, match="未知 rule 形态"):
        resolve_rule_for_column(sensitivity=None, matched_rule_form="keep-first-3")


def test_deny_semantics_tags_are_not_masked():
    # tenant_key / internal_cost 属 deny 语义（W2C/guard），mask 不打码也不报错
    assert resolve_rule_for_column(sensitivity="tenant_key", matched_rule_form=None) == "none"
    assert resolve_rule_for_column(sensitivity="internal_cost", matched_rule_form=None) == "none"
    assert resolve_rule_for_column(sensitivity=None, matched_rule_form=None) == "none"


def test_bundle_rule_forms_are_all_known():
    # 语义包 v1.1 实际使用的两个形态必须在 KNOWN_RULE_FORMS 里（否则真包一上来就 fail-closed）
    assert KNOWN_RULE_FORMS["***-***-1234"] == "phone"
    assert KNOWN_RULE_FORMS["u****@domain.com"] == "email"
    assert KNOWN_RULE_FORMS["***-**-6789"] == "id_card"


def test_sensitivity_tags_cover_bundle_pii_tags():
    assert {"pii_phone", "pii_address"} <= SENSITIVITY_TAGS


# ============================================================================
# apply：整体行为
# ============================================================================


def test_apply_masks_by_sensitivity_and_records_hit_columns():
    policy = _policy(("receiver_phone", "pii_phone"), ("amount", None), ("name", "pii_name"))
    rows = [("13812345678", 100, "张三"), (None, 200, "李四")]
    out = ENGINE.apply(rows, policy)
    assert out.rows == (("***-***-5678", 100, "张*"), (None, 200, "李*"))
    assert out.hit_columns == ("receiver_phone", "name")


def test_apply_numeric_phone_value_is_coerced():
    policy = _policy(("receiver_phone", "pii_phone"),)
    out = ENGINE.apply([(13812345678,)], policy)  # 手机号被存成 bigint
    assert out.rows == (("***-***-5678",),)
    assert out.hit_columns == ("receiver_phone",)


def test_apply_none_passes_through_untouched():
    policy = _policy(("name", "pii_name"),)
    out = ENGINE.apply([(None,)], policy)
    assert out.rows == ((None,),)  # None 不是敏感值，打码会制造"有值"假象
    assert out.hit_columns == ()  # 没有实际打码 → 不记命中


def test_apply_no_masked_columns_returns_rows_verbatim():
    policy = _policy(("amount", None), ("city", None))
    rows = [(1, "广州")]
    out = ENGINE.apply(rows, policy)
    assert out.rows == ((1, "广州"),)
    assert out.hit_columns == ()


def test_apply_row_width_mismatch_is_fail_closed():
    policy = _policy(("a", "pii_name"), ("b", None))
    with pytest.raises(MaskFailed, match="行宽度"):
        ENGINE.apply([("张三",)], policy)


def test_apply_missing_policy_key_is_fail_closed():
    with pytest.raises(MaskFailed, match="缺少必需键"):
        ENGINE.apply([("x",)], {"columns": []})  # 缺 mask_rules


def test_apply_bad_regex_is_fail_closed():
    policy = {
        "columns": [{"name": "phone", "sensitivity": None}],
        "mask_rules": [{"column_pattern": "((", "rule": "***-***-1234"}],
    }
    with pytest.raises(MaskFailed, match="正则"):
        ENGINE.apply([("x",)], policy)


def test_mask_failed_is_internal_and_carries_no_value():
    """fail-closed：掩码失败必须抛 INTERNAL，且消息不含明文值（07 §8.7 硬规则 5）。"""
    policy = _policy(("email", "pii_email"),)
    secret = "not-an-email"  # 不含 @ → email 规则 fail-closed
    with pytest.raises(CommerceQLError) as ei:
        ENGINE.apply([(secret,)], policy)
    assert ei.value.default_code == "INTERNAL"
    assert secret not in str(ei.value)


# ============================================================================
# 负向对照：注入 → 必红 → 还原 → 必绿（看清红的是目标断言）
# ============================================================================


def test_negative_control_column_identity_rules_actually_fire():
    """把「列身份 → 规则」判定注入为"永远 none"必须让打码断言变红；
    还原后同断言必须回绿 —— 证明打码不是"碰巧没值"造成的假绿。"""
    policy = _policy(("receiver_phone", "pii_phone"),)
    rows = [("13812345678",)]

    # 正常：打码生效
    assert ENGINE.apply(rows, policy).rows == (("***-***-5678",),)

    # 注入：sensitivity 改为非 pii 标签 **且**去掉语义包覆盖正则
    # （覆盖正则本来就允许对无标签列打码 —— 注入必须同时去掉两条判定路径，
    #   否则注入不成立，断言红不了才是对的）
    broken_policy = {
        "columns": [{"name": "receiver_phone", "sensitivity": "tenant_key"}],
        "mask_rules": [],
    }
    assert ENGINE.apply(rows, broken_policy).rows == (("13812345678",),)  # 明文漏出 = 注入成功

    # 还原：回绿
    assert ENGINE.apply(rows, policy).rows == (("***-***-5678",),)
