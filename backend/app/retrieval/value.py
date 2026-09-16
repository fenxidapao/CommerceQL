"""值检索（07 §6.6）—— 用户提到的具体值 → 定位到列。

归属窗口：**W2B**。纯函数、离线、无 LLM（L3 内的非 refine 子模块禁 LLM）。

规则逐条对齐 07 §6.6：
- 数据来源**只有**语义包携带的枚举/编码值表（`BundleView.value_entries()`），
  **不得**为取值去扫业务库（成本 + 泄露面）；
- 匹配链：归一化（去空格 / 大小写 / 全半角）→ 精确 → 前缀 → 编辑距离 ≤ 1；
- 租户隔离：enum 值表是公共语义包内容（对所有租户相同），
  **不存在**"按租户过滤值表"的数据源；凡未来出现租户级值表，
  必须由调用方传入租户过滤后的条目集，本模块不做隐式过滤
  （A.1.5 红线 3 同源：跨租户值不得成为存在性线索）。

## confidence 取值（登记待架构确认，不自行当作已定契约）

07 §6.6 的输出形态是 `value_hits[{value, column, asset, confidence}]`，但**未定义**
confidence 的量纲与取值。按"必须 X 但没给值 = 逼实现者发明数字"的教训（U-22 同类），
本实现把 confidence 定义为**匹配层级的确定性映射**并在此显式登记，交架构窗口裁定：

| 匹配层级 | confidence |
|---|---|
| 精确（归一化后相等，或完整包含于问句） | 1.0 |
| 前缀（≥2 字符的前缀关系） | 0.8 |
| 编辑距离 ≤ 1（≥2 字符） | 0.6 |

若架构裁定换量纲，只改 `TIER_EXACT/TIER_PREFIX/TIER_EDIT1` 三个常量与匹配函数，
不影响调用方结构。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from app.retrieval.tokenizer import tokenize
from app.retrieval.view import BundleView, ValueEntry

__all__ = [
    "TIER_EDIT1",
    "TIER_EXACT",
    "TIER_PREFIX",
    "ValueHit",
    "normalize_text",
    "search_values",
]

#: 匹配层级 → confidence 的确定性映射（见模块 docstring 的登记说明）。
TIER_EXACT: float = 1.0
TIER_PREFIX: float = 0.8
TIER_EDIT1: float = 0.6


@dataclass(frozen=True, slots=True)
class ValueHit:
    """值检索命中（07 §6.6 输出形态 + 命中层级归因）。"""

    term: str              # 归一化前的原始词面（用户可读）
    asset: str             # logical asset name
    column: str
    values: tuple[str, ...]  # SQL 侧枚举键 / 编码值
    confidence: float
    source: str            # enum / alias / value_map


def normalize_text(text: str) -> str:
    """归一化（07 §6.6）：NFKC（全半角折叠 + 兼容形分解）→ 去所有空白 → 小写。"""
    return "".join(unicodedata.normalize("NFKC", text).split()).lower()


def _edit_distance_at_most_1(a: str, b: str) -> bool:
    """O(len) 的"编辑距离是否 ≤1"判定（不做完整 DP；首次失配即定位差异类型）。"""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    # 此时保证 la <= lb
    for i in range(la):
        if a[i] != b[i]:
            if la == lb:
                return a[i + 1 :] == b[i + 1 :]  # 替换
            return a[i :] == b[i + 1 :]  # b 在 i 处多一个字符（插入）
    # 短串是长串的前缀 → 差在末尾一个字符（仅当长度差 =1）
    return lb - la == 1


def _match_tier(token: str, term: str) -> float | None:
    """单 token 对单词条的匹配层级（确定性；顺序 = 07 §6.6 的匹配链）。"""
    if token == term:
        return TIER_EXACT
    # 前缀/编辑距离都要求**双方 ≥2 字符**：单字 token（"直"）对多字词条的前缀
    # 关系会产生大面积噪声命中（"直接访问""直播"全中），07 §6.6 的匹配链
    # 针对的是"具体值"，不是单字。
    if min(len(token), len(term)) < 2:
        return None
    if token.startswith(term) or term.startswith(token):
        return TIER_PREFIX
    if _edit_distance_at_most_1(token, term):
        return TIER_EDIT1
    return None


def search_values(
    question: str,
    view: BundleView,
    *,
    min_confidence: float = TIER_EDIT1,
) -> tuple[ValueHit, ...]:
    """在语义包值表中检索问句提到的具体值。

    匹配单位 = 问句分词后的 token **与**归一化全句（后者覆盖"直接访问"这类
    分词后可能碎掉的多字标签——容器判定与 token 判定取最优层级）。

    排序：confidence 降序 → term 字典序 → asset/column 字典序（全确定性，
    同一问句两次调用结果逐字节相同）。
    """
    norm_question = normalize_text(question)
    if not norm_question:
        return ()

    tokens = {normalize_text(t) for t in tokenize(question)} - {""}
    candidates: list[ValueHit] = []

    for entry in view.value_entries():
        tier = _best_tier(entry, norm_question, tokens)
        if tier is None or tier < min_confidence:
            continue
        candidates.append(
            ValueHit(
                term=entry.term,
                asset=entry.asset,
                column=entry.column,
                values=entry.values,
                confidence=tier,
                source=entry.source,
            )
        )

    candidates.sort(key=lambda h: (-h.confidence, h.term, h.asset, h.column))
    return tuple(candidates)


def _best_tier(entry: ValueEntry, norm_question: str, tokens: set[str]) -> float | None:
    term = normalize_text(entry.term)
    if not term:
        return None
    # ① 全句容器判定：词条完整出现在归一化问句中 = 精确命中。
    #    这是值检索的主通道："直播渠道的GMV" 必须命中 直播，无论分词怎么切。
    if term in norm_question:
        return TIER_EXACT
    # ② token 级：精确 → 前缀 → 编辑距离 ≤1。
    best: float | None = None
    for token in tokens:
        tier = _match_tier(token, term)
        if tier is not None and (best is None or tier < best):
            best = tier
    return best
