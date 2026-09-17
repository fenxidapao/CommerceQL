"""CommerceQL 后端包：脱敏引擎（deny 与 mask 两套语义）。

层号：L2｜归属窗口：W2D（docs/08 §4.1 文件归属权表）。
（阶段 0 的「只允许 docstring」约束已随 W2D 开工解除；实现落在子模块，本文件只做再导出。）

⚠️ deny 与 mask 是**两套语义**（07 §8.7）：
- `deny_columns` = 列根本不进 schema 上下文，SQL 仍引用 → W2C 的 AST-R07 直接拒绝，
  列**不出现**在结果里 —— 归 `app/guard`（W2C），本包不实现 deny 判定；
- `mask_rule` = 允许查询与返回，但结果值打码 —— 本包的职责。
  `tenant_key` / `internal_cost` 这类标签虽带 sensitive 标记，语义仍属 deny（不打码）。
"""

from app.mask.engine import MASK_POLICY_KEYS, MaskFailed, SemanticMaskEngine
from app.mask.rules import (
    KNOWN_RULE_FORMS,
    SENSITIVITY_TAGS,
    MaskRuleError,
    resolve_rule_for_column,
)

__all__ = [
    "KNOWN_RULE_FORMS",
    "MASK_POLICY_KEYS",
    "SENSITIVITY_TAGS",
    "MaskFailed",
    "MaskRuleError",
    "SemanticMaskEngine",
    "resolve_rule_for_column",
]
