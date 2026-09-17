"""jieba 中文分词 —— **写入侧与查询侧的唯一同源入口**（07 §3.2 ★ / ADR-07 / N-24）。

归属窗口：**W2B**（docs/08 §4.1：`app/retrieval/**`，含本文件唯一入口）。

## 为什么必须是唯一入口（N-24）

`tsvector` 列由**写入侧**（语义包物化，W2A）计算，`tsquery` 由**查询侧**（本模块 sparse.py）构造。
两侧只要有一侧换了分词方式，查询就会**静默召回失败**——不报错、只是查不到。
所以规则不是"两侧都要小心"，而是**两侧只能调同一个函数**：

- 写入侧：`to_tsvector('simple', tsvector_source(text))`
- 查询侧：`to_tsquery('simple', tsvector_source(question))`（**禁用 plainto_tsquery**，
  它会再走一遍 PG 自己的分词 → 两侧不同源，正是 N-24 要消灭的形态）

**⚠️ 层级落位的裁定记录（Q1，2026-09-16 用户采纳建议，待架构窗口分配编号）**：
`contracts.TokenizerPort` 的 docstring 写"实现在 L0/L1"（因 semantics L1 不得 import L3），
而 07 §3.2 与 W1A RELAY §5 均指明 `retrieval/tokenizer.py` 是唯一入口。两处权威文件矛盾。
**本实现按 07 §3.2 落在 retrieval/（L3）**，写入侧（semantics 物化）经**组装根注入
`TokenizerPort`** 使用本模块，不做 import——层级矛盾由此消解，最终落位以架构裁定为准。

## 自定义词典

07 §6.4：从语义包 `synonym` 生成电商词表（双11 / 618 / 坑位费 / 动销率 / UV / SPU / SKU）。
词表来源 = `BundleView.dictionary_terms()`（本包 view.py），加载动作**只能**经
`load_custom_dict()`——它是幂等的（重复加载同一词不重复计数），且记录已加载词集供测试断言。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

import jieba

__all__ = [
    "loaded_custom_terms",
    "load_custom_dict",
    "tokenize",
    "tsquery_source",
    "tsvector_source",
]

#: 合法 token 形态：Unicode 字母/数字/下划线（`\w` 在 Python re 下天然含 CJK）。
#: 分词产出的纯标点/空白碎片对 tsvector 无意义，必须剥掉——否则写入侧与查询侧
#: 只要一侧忘了剥，token 集就不同源。
_TOKEN_OK: Final[re.Pattern[str]] = re.compile(r"^\w+$", re.UNICODE)

#: 已加载的自定义词（幂等加载的记账本；仅由 `load_custom_dict` 写入）。
_LOADED_TERMS: set[str] = set()

#: 自定义词的 add_word 频率。取一个显著高于 jieba 默认词频的值，
#: 使"双11"这类默认会被切成"双/11"的词整体成词。值本身不进任何契约——
#: 它只影响"能否成词"，不影响 N-24 的同源性（两侧用的是同一份词典状态）。
_CUSTOM_WORD_FREQ: Final[int] = 10_000_000


def load_custom_dict(terms: Iterable[str]) -> int:
    """把电商词表加载进 jieba（幂等）。

    返回本次**新加载**的词数（重复调用返回 0）。词必须非空、不含空白——
    含空白的"词"会让 tsvector_source 产出的空格串歧义化（写入/查询两侧的
    token 边界就是空格），直接拒绝而不是悄悄截断。
    """
    added = 0
    for term in terms:
        word = term.strip()
        if not word:
            continue
        if re.search(r"\s", word):
            raise ValueError(f"自定义词典词不得含空白：{word!r}")
        if word in _LOADED_TERMS:
            continue
        jieba.add_word(word, freq=_CUSTOM_WORD_FREQ)
        _LOADED_TERMS.add(word)
        added += 1
    return added


def loaded_custom_terms() -> frozenset[str]:
    """已加载的自定义词集（只读视图，供测试与诊断）。"""
    return frozenset(_LOADED_TERMS)


def tokenize(text: str) -> list[str]:
    """分词——**两侧同源的唯一入口**（N-24）。

    产出：jieba 切分 → 去首尾空白 → 剥纯标点碎片。**不**在此处做大小写归一：
    英文词（GMV/UV）大小写形态属于"值匹配"（value.py 的归一化）的职责，
    分词层保持原文；tsvector 的 'simple' 配置本身会做小写归一，两侧同样经过它，
    同源性不受影响。
    """
    if not text:
        return []
    return [tok for tok in (t.strip() for t in jieba.lcut(text)) if tok and _TOKEN_OK.match(tok)]


def tsvector_source(text: str) -> str:
    """文本 → **写入侧** `to_tsvector('simple', :source)` 的参数值（N-24 写入 half）。

    产出 = `tokenize()` 的空格串形态；'simple' 配置把空格分隔串逐 token 索引。
    ⚠️ 写入侧**必须**用本函数——任何一侧自己分词都构成第二个真相（N-24）。
    """
    return " ".join(tokenize(text))


def tsquery_source(text: str) -> str:
    """文本 → **查询侧** `to_tsquery('simple', :terms)` 的参数值（N-24 查询 half）。

    ⚠️ 实测裁定（2026-09-16，集成测试抓出）：`to_tsquery` **不接受**空格分隔的
    多个 lexeme（`syntax error in tsquery: "直播 渠道"`）——token 之间必须显式
    `&` 连接。旧假设「'simple' 下空格 = AND」是错的，以此函数为准。
    token 仍来自**同一** `tokenize()`（同源性不变）；token 形态已被 `_TOKEN_OK`
    限制为 `\\w+`（不含引号/运算符），此处再按 tsquery 语法加引号兜底。
    """
    tokens = tokenize(text)
    if not tokens:
        return ""
    return " & ".join("'" + t.replace("'", "''") + "'" for t in tokens)
