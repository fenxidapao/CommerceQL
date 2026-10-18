"""W58：LLM 理解之后、plan 之前的确定性请求策略出口。

这里只做语义包/契约已经能判定的事项，不新增指标，也不改变 plan 的判据：
- 语义包 `blacklist_terms.action=refuse`；
- 请求触达 deny/sensitive 列（地址、手机号、成本/毛利）；
- 其它店铺/租户等越界范围；
- 明确的“无对应指标/外部竞品” reason_code。

命中后由 `normalize` 直接写 refuse 终态，避免把“系统不回答”的问题误送进 clarify。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.core.contracts import SemanticBundlePort
from app.core.enums import RefuseReason

__all__ = ["PreflightRefusal", "preflight_refusal", "raw_preflight_refusal"]


@dataclass(frozen=True, slots=True)
class PreflightRefusal:
    reason: RefuseReason
    reason_code: str
    evidence: str


_SENSITIVE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "pii_address": ("地址", "收货地址", "收件人地址"),
    "pii_phone": ("手机号", "手机", "电话"),
    "internal_cost": ("成本", "成本价", "毛利"),
}
_EXTERNAL_DATA_PHRASES: Final[tuple[str, ...]] = (
    "竞品",
    "竞争对手",
    "竞店",
    "同行",
)
_OTHER_SCOPE_PHRASES: Final[tuple[str, ...]] = (
    "隔壁店铺",
    "其他店铺",
    "别家店铺",
    "别的店铺",
    "非本租户",
    "其他租户",
    "别的租户",
)


def _sensitive_hit(question: str, semantics: SemanticBundlePort) -> str | None:
    assets = getattr(semantics, "assets", None)
    if not callable(assets):
        return None
    for asset in assets():
        for column in getattr(asset, "columns", ()) or ():
            label = str(getattr(column, "sensitive", "") or "")
            for keyword in _SENSITIVE_KEYWORDS.get(label, ()):
                if keyword in question:
                    return label
    return None


def raw_preflight_refusal(question: str, semantics: SemanticBundlePort) -> PreflightRefusal | None:
    """在调用 LLM 前按原文做确定性安全判定。

    只覆盖原文即可判死的敏感列/外部数据/其它租户范围；语义包黑话和
    normalize 产出的 reason_code 仍由后置的同名守卫处理。
    """
    sensitive = _sensitive_hit(question, semantics)
    if sensitive is not None:
        return PreflightRefusal(
            RefuseReason.PII_BLOCKED,
            f"sensitive_column:{sensitive}",
            f"sensitive={sensitive}",
        )
    if "订单明细" in question or "买家手机号" in question:
        return PreflightRefusal(
            RefuseReason.PII_BLOCKED,
            "sensitive_export",
            "raw_sensitive_export_phrase",
        )
    if any(phrase in question for phrase in _EXTERNAL_DATA_PHRASES):
        return PreflightRefusal(
            RefuseReason.NO_DATA_ASSET,
            "no_data_asset",
            "external_data_phrase",
        )
    for phrase in _OTHER_SCOPE_PHRASES:
        if phrase in question:
            return PreflightRefusal(
                RefuseReason.OUT_OF_SCOPE,
                "unauthorized_scope",
                f"phrase={phrase}",
            )
    return None


def preflight_refusal(
    question: str,
    intent_detail: Mapping[str, Any],
    unresolved_terms: Sequence[str],
    semantics: SemanticBundlePort,
) -> PreflightRefusal | None:
    """返回确定性拒答；`None` 表示交回原有 intent/plan/clarify 流程。"""
    reason_code = str(intent_detail.get("reason_code") or "")
    lowered = reason_code.casefold()

    # 1) deny/sensitive：比“无指标”更具体，先判。
    sensitive = _sensitive_hit(question, semantics)
    if sensitive is not None:
        return PreflightRefusal(
            RefuseReason.PII_BLOCKED,
            f"sensitive_column:{sensitive}",
            f"sensitive={sensitive}",
        )

    # 2) 语义包黑话表明确要求 refuse。
    lookup = getattr(semantics, "lookup_blacklist", None)
    if callable(lookup):
        for term in unresolved_terms:
            item = lookup(str(term))
            if item is not None and getattr(item, "action", None) == "refuse":
                return PreflightRefusal(
                    RefuseReason.NO_DATA_ASSET,
                    "blacklist_refuse",
                    f"blacklist_term={item.term}",
                )

    # 3) 外部竞品/没有对应指标：产品边界是“不回答”，不是“再问一轮”。
    if (
        any(phrase in question for phrase in _EXTERNAL_DATA_PHRASES)
        or "competitor" in lowered
        or reason_code == "unmapped_metric"
    ):
        return PreflightRefusal(
            RefuseReason.NO_DATA_ASSET,
            "no_data_asset",
            f"reason_code={reason_code}",
        )

    # 4) 其它店铺/其它租户：当前身份范围之外的请求。
    for phrase in _OTHER_SCOPE_PHRASES:
        if phrase in question:
            return PreflightRefusal(
                RefuseReason.OUT_OF_SCOPE,
                "unauthorized_scope",
                f"phrase={phrase}",
            )

    return None
