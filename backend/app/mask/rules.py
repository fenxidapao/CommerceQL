"""掩码规则表 —— 默认规则 + 语义包覆盖形态的**唯一**实现点（07 §8.7）。

归属窗口：W2D（docs/08 §4.1：`app/mask/**`）。

--------------------------------------------------------------------------------
三条设计决定（实现前先读，防止被"优化"回去）
--------------------------------------------------------------------------------

1. **主判据 = 列身份（`sensitive` 标签），不是列名正则**（07 §8.7 硬规则 3）。
   语义包在 `assets[].columns[].sensitive` 上给列打身份标签（`pii_phone` / `pii_email` /
   `pii_idcard` / `pii_address` / `pii_name`），本模块按标签派发规则。
   语义包 `policies.mask_rules[].column_pattern`（列名正则）只作**覆盖通道**：
   命中的列按其 `rule` 字符串映射到规则函数。正则**从不**单独决定掩码——
   它只决定"该列按哪条已知规则打码"，这正是"正则只能兜底、不能做主判据"的落地形态。

2. **`rule` 字符串是"已知展示形态"，不是可执行表达式**。
   语义包 v1.1 里 `rule` 的值（如 `***-***-1234`）逐字来自 07 §8.7 默认规则表的示例列。
   因此本模块维护一张「展示形态 → 规则函数」的映射表；**未知形态 = 掩码失败 → fail-closed**
   （07 §8.7 硬规则 5：宁可不给，不给明文）。绝不做"猜一个最像的规则"。

3. **非字符串值先 `str()` 再掩码；`None` 原样通过**。
   `None` 不是敏感值（前端文案由 06 §6.4 定义），打码 `None` 反而制造"有值"的假象。
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "DEFAULT_RULE_BY_SENSITIVITY",
    "KNOWN_RULE_FORMS",
    "MaskRuleError",
    "SENSITIVITY_TAGS",
    "mask_email",
    "mask_id_card",
    "mask_name",
    "mask_phone",
    "mask_address",
    "resolve_rule_for_column",
]

#: 语义包当前使用的敏感标签全集（bundle_2026.09.14.1.yaml 实测：pii_phone /
#: pii_address / internal_cost / tenant_key）。**掩码只认 pii_* 标签**：
#: `tenant_key` / `internal_cost` 属 deny 语义（列根本不出现，W2C gate 的 AST-R07），
#: 不在本模块打码——把 deny 列也打码会制造"该列允许查询"的假象（07 §8.7 两套语义）。
SENSITIVITY_TAGS: Final[frozenset[str]] = frozenset(
    {"pii_phone", "pii_email", "pii_idcard", "pii_address", "pii_name"}
)


# ============================================================================
# 默认规则函数（07 §8.7 掩码规则表，逐行落位）
# ============================================================================

_LAST4_RE: Final[re.Pattern[str]] = re.compile(r"(\S{4})$")


def _last4(value: str) -> str:
    m = _LAST4_RE.search(value)
    return m.group(1) if m else "****"


def mask_phone(value: str) -> str:
    """手机号：保留后 4 位 → `***-***-1234`（07 §8.7 第 1 行）。"""
    return f"***-***-{_last4(value)}"


def mask_email(value: str) -> str:
    """邮箱：保留首字符 + 域名 → `u****@domain.com`（07 §8.7 第 2 行）。"""
    if "@" not in value:
        # 非法邮箱形态也是"掩码失败"的一种：按 fail-closed 处理（由调用方统一转 INTERNAL）
        # ⚠️ 消息里不得回显值本身（值可能是明文 PII，N-11 精神）
        raise MaskRuleError("email 规则收到不含 @ 的值，无法按已知形态打码（fail-closed）")
    local, _, domain = value.partition("@")
    return f"{local[:1]}****@{domain}"


def mask_id_card(value: str) -> str:
    """身份证：保留后 4 位 → `***-**-6789`（07 §8.7 第 3 行）。"""
    return f"***-**-{_last4(value)}"


def mask_address(value: str) -> str:
    """收货地址：保留省市区前缀 + 星号 → `广东省深圳市南山区***`（07 §8.7 第 4 行）。

    前缀识别 = **顺序边界扫描**（省→市→区/县，逐级向后找）：一次正则的非贪婪匹配
    会在第一个边界停（实测 "广东省深圳市南山区…" 只留到 "广东省"），贪婪匹配又会被
    街道里的"区"字过度暴露。顺序扫描对直辖市（无"省"）也成立（跳过缺失级）。
    一级边界都识别不出时保留首 6 字符再打码（保守：暴露得比"全打码"多、比"全暴露"少）。
    """
    pos = 0
    end = 0
    for suffix in ("省", "市", "区", "县"):
        j = value.find(suffix, pos)
        if j == -1:
            if suffix == "省":
                continue  # 直辖市/自治区形态：跳过"省"级继续找市/区
            break
        pos = j + len(suffix)
        end = pos
    prefix = value[:end] if end else value[:6]
    return f"{prefix}***"


def mask_name(value: str) -> str:
    """姓名：保留姓（首字符）→ `张*`（07 §8.7 第 5 行）。"""
    return f"{value[:1]}*"


#: 敏感标签 → 默认规则（07 §8.7 表的"列身份"落地形态）。
DEFAULT_RULE_BY_SENSITIVITY: Final[dict[str, str]] = {
    "pii_phone": "phone",
    "pii_email": "email",
    "pii_idcard": "id_card",
    "pii_address": "address",
    "pii_name": "name",
}

_RULE_FUNCS: Final[dict[str, object]] = {
    "phone": mask_phone,
    "email": mask_email,
    "id_card": mask_id_card,
    "address": mask_address,
    "name": mask_name,
}

#: 语义包 `mask_rules[].rule` 的**已知展示形态** → 规则名。
#: 这些字符串逐字来自 07 §8.7 / 语义包 v1.1 的示例值；新增形态必须先在本表登记，
#: 否则语义包更新一条新形态会把所有命中列 fail-closed（这是**故意的**：掩码规则变更
#: 应当是一次显式的代码动作，不是数据文件静默生效）。
KNOWN_RULE_FORMS: Final[dict[str, str]] = {
    "***-***-1234": "phone",
    "u****@domain.com": "email",
    "***-**-6789": "id_card",
    # 地址/姓名在语义包里没有唯一示例串（前缀依值而变），故无已知形态：
    # 语义包要覆盖它们，请在 column_pattern 里圈定列后，规则仍按 sensitivity 走。
}


class MaskRuleError(ValueError):
    """掩码规则不可解析 / 值不可按规则打码。

    ⚠️ 由 `engine.py` 统一转成 fail-closed（07 §8.7 硬规则 5：`error(INTERNAL)`，
    不下发任何数据）。本异常**刻意不带原始值**进消息（值本身可能是 PII）。
    """


def resolve_rule_for_column(
    *,
    sensitivity: str | None,
    matched_rule_form: str | None,
) -> str:
    """列 → 规则名的**唯一**判定点（07 §8.7 硬规则 3 的机器化）。

    | 输入组合 | 判定 | 依据 |
    |---|---|---|
    | sensitivity 是 pii_* | 该标签的默认规则 | 列身份是主判据 |
    | sensitivity 非 pii_*（tenant_key / internal_cost / None）且无覆盖 | **不打码** | deny 语义归 gate；无身份不打码 |
    | sensitivity 非 pii_* 但列名命中 mask_rules 且形态已知 | 该形态的规则 | 语义包覆盖通道（07："规则表可由语义包覆盖"） |
    | 命中 mask_rules 但形态未知 | **raise** | fail-closed，绝不猜 |
    """
    if sensitivity in SENSITIVITY_TAGS:
        return DEFAULT_RULE_BY_SENSITIVITY[sensitivity]
    if matched_rule_form is None:
        return "none"
    rule = KNOWN_RULE_FORMS.get(matched_rule_form)
    if rule is None:
        raise MaskRuleError(
            f"语义包 mask_rules 使用了未知 rule 形态（fail-closed，不猜规则）："
            f"{matched_rule_form!r} —— 新形态必须先在 mask/rules.py 的 KNOWN_RULE_FORMS 登记"
        )
    return rule


def apply_rule(rule: str, value: str) -> str:
    """规则名 → 掩码值。规则名必须是 `resolve_rule_for_column` 的产出。"""
    func = _RULE_FUNCS.get(rule)
    if func is None:
        raise MaskRuleError(f"未知掩码规则名：{rule!r}")
    result = func(value)  # type: ignore[operator]
    if not isinstance(result, str):  # pragma: no cover - 规则函数均为 str 返回
        raise MaskRuleError(f"掩码规则 {rule!r} 返回了非字符串")
    return result
