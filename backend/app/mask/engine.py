"""脱敏引擎 —— `MaskPort` 的实现（07 §8.7 / N-05）。

归属窗口：W2D（docs/08 §4.1：`app/mask/**`）。

--------------------------------------------------------------------------------
`policy` 载荷形状（本模块与调用方的唯一约定）
--------------------------------------------------------------------------------

`MaskPort.apply(rows, policy)` 的 `rows` 是**裸行**（不含列名），所以列名与列身份
必须经 `policy` 进入。形状（缺一不可，缺了就 fail-closed）：

```python
policy = {
    "columns": [                      # 与 rows 每行的列序**严格对齐**
        {"name": "receiver_phone", "sensitivity": "pii_phone"},
        {"name": "amount",         "sensitivity": None},
        ...
    ],
    "mask_rules": [                   # 语义包 policies.mask_rules 原样透传（可空）
        {"column_pattern": ".*phone.*", "rule": "***-***-1234"},
    ],
}
```

`columns` 由 `app/exec`（调用方）从「语义包 assets[].columns[].sensitive」+
「游标 description 的输出列序」装配；本模块**不**读语义包（同层调用必须走端口，
R-DEP-1）。

--------------------------------------------------------------------------------
硬规则落位（07 §8.7 执行位置表）
--------------------------------------------------------------------------------

| # | 规则 | 落位 |
|---|---|---|
| 1 | mask 是唯一出口 | 由 `app/exec` 在返回 `ResultSet` 前调用本引擎保证 |
| 2 | 写缓存前必须已掩码 | 同上（`fetch` 返回值即已掩码，缓存写入方拿到的不可能有明文） |
| 3 | 列身份为主判据 | `rules.resolve_rule_for_column` |
| 4 | 命中列进 `pii_columns_hit` | `MaskOutcome.hit_columns` |
| 5 | 掩码失败 → fail-closed | `MaskFailed`（`default_code=INTERNAL`），**不下发任何数据** |
| 6 | 掩码值即前端展示值 | 前端不再脱敏（06 §1.4 R-2，W4/W5 的交接纪律） |
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from app.core.contracts import MaskOutcome
from app.core.errors import CommerceQLError
from app.mask.rules import (
    MaskRuleError,
    apply_rule,
    resolve_rule_for_column,
)

__all__ = ["MaskFailed", "SemanticMaskEngine", "MASK_POLICY_KEYS"]

#: policy 载荷的必需键（缺失 = 载荷形状错误 → fail-closed）。
MASK_POLICY_KEYS: Final[frozenset[str]] = frozenset({"columns", "mask_rules"})


class MaskFailed(CommerceQLError):
    """掩码失败 → fail-closed（07 §8.7 硬规则 5）。

    ⚠️ 消息**只描述失败原因类别**，绝不携带行数据或明文 PII。
    """

    default_code = "INTERNAL"


class SemanticMaskEngine:
    """按「列身份为主、语义包正则覆盖为辅」打码（N-05 / 07 §8.7）。"""

    def apply(
        self,
        rows: Sequence[Sequence[Any]],
        policy: Mapping[str, Any],
    ) -> MaskOutcome:
        missing = MASK_POLICY_KEYS - set(policy)
        if missing:
            raise MaskFailed(f"掩码 policy 缺少必需键（fail-closed）：{sorted(missing)}")

        columns = policy["columns"]
        if not isinstance(columns, (list, tuple)):
            raise MaskFailed("掩码 policy.columns 必须是列表（fail-closed）")
        n_cols = len(columns)

        # ---- 逐列解析规则（解析失败 = 整体 fail-closed，不输出部分结果）----
        # ⚠️ 先全量解析、再逐行打码：解析错误发生在打码前，保证"绝不半掩码出站"。
        try:
            per_column_rule = self._resolve_column_rules(columns, policy["mask_rules"])
        except MaskRuleError as exc:
            raise MaskFailed(f"掩码规则解析失败：{exc}") from exc
        except re.error as exc:
            raise MaskFailed(f"掩码 column_pattern 不是合法正则：{exc}") from exc

        rule_by_idx = {
            idx: rule for idx, rule in enumerate(per_column_rule) if rule != "none"
        }
        if not rule_by_idx:
            # 没有任何列需要打码：原样返回（hit_columns 为空）
            return MaskOutcome(
                rows=tuple(tuple(row) for row in rows), hit_columns=()
            )

        hit: set[str] = set()
        out_rows: list[tuple[Any, ...]] = []
        try:
            for row in rows:
                if len(row) != n_cols:
                    raise MaskFailed(
                        f"行宽度 {len(row)} 与 policy.columns {n_cols} 不一致（fail-closed）"
                    )
                cells: list[Any] = []
                for idx, value in enumerate(row):
                    rule = rule_by_idx.get(idx)
                    if rule is None or value is None:
                        cells.append(value)
                        continue
                    if not isinstance(value, str):
                        # 数值形态的敏感值（如手机号被存成 bigint）先转字符串再打码
                        value = str(value)
                    cells.append(apply_rule(rule, value))
                    hit.add(str(columns[idx]["name"]))
                out_rows.append(tuple(cells))
        except MaskRuleError as exc:
            raise MaskFailed(f"掩码执行失败：{exc}") from exc

        # hit_columns 列序稳定（按 policy.columns 顺序），便于审计比对
        ordered_hit = tuple(
            str(columns[idx]["name"]) for idx in sorted(rule_by_idx) if str(columns[idx]["name"]) in hit
        )
        return MaskOutcome(rows=tuple(out_rows), hit_columns=ordered_hit)

    @staticmethod
    def _resolve_column_rules(
        columns: Sequence[Mapping[str, Any]],
        mask_rules: Any,
    ) -> list[str]:
        """列清单 + 语义包覆盖 → 每列规则名（"none" = 不打码）。"""
        if mask_rules is None:
            mask_rules = ()
        if not isinstance(mask_rules, (list, tuple)):
            raise MaskRuleError("mask_rules 必须是列表")
        compiled: list[tuple[re.Pattern[str], str]] = []
        for entry in mask_rules:
            pattern = entry.get("column_pattern")
            rule = entry.get("rule")
            if not pattern or not rule:
                raise MaskRuleError(f"mask_rules 条目缺 column_pattern 或 rule：{entry!r}")
            compiled.append((re.compile(pattern), rule))

        resolved: list[str] = []
        for col in columns:
            name = col.get("name")
            if not name:
                raise MaskRuleError("policy.columns 条目缺 name")
            sensitivity = col.get("sensitivity")
            matched_form: str | None = None
            for pattern, rule in compiled:
                if pattern.search(str(name)):
                    matched_form = rule
                    break
            resolved.append(resolve_rule_for_column(sensitivity=sensitivity, matched_rule_form=matched_form))
        return resolved
