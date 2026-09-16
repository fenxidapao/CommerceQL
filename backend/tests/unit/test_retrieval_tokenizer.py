"""tokenizer 唯一入口的单元测试（N-24 / 07 §6.4）。"""

from __future__ import annotations

import pytest

from app.retrieval.tokenizer import (
    loaded_custom_terms,
    load_custom_dict,
    tokenize,
    tsvector_source,
)
from tests.unit._retrieval_fixture import load_bundle_view


@pytest.fixture(scope="module", autouse=True)
def _bundle_dict() -> None:
    """把真实语义包词表加载进 jieba（幂等；模块级一次）。"""
    load_custom_dict(load_bundle_view().dictionary_terms())


def test_custom_dict_loaded_from_bundle() -> None:
    """W1A RELAY §5 点名的自证项：jieba 词典可加载（此前校验器标 SKIP）。"""
    terms = loaded_custom_terms()
    # 电商词表的关键词必须在词典里（07 §6.4 点名的形态）
    assert "双11" in terms
    assert "坑位费" in terms
    assert "SKU" in terms
    assert "动销率" in terms
    # 数量级 sanity：105 别名 + 列级 synonyms + 15 黑话 + enum 标签
    assert len(terms) >= 120


def test_load_custom_dict_is_idempotent() -> None:
    assert load_custom_dict(["双11", "坑位费", "SKU"]) == 0
    assert load_custom_dict(["全新测试词xyz"]) == 1
    assert load_custom_dict(["全新测试词xyz"]) == 0


def test_load_custom_dict_rejects_whitespace() -> None:
    with pytest.raises(ValueError, match="空白"):
        load_custom_dict(["含 空格"])


def test_tokenize_e_commerce_terms_stay_whole() -> None:
    """自定义词必须整体成词（默认词典会把 双11 切成 双/11）。"""
    tokens = tokenize("双11的GMV是多少")
    assert "双11" in tokens
    assert "GMV" in tokens


def test_tokenize_drops_punctuation_and_whitespace() -> None:
    tokens = tokenize("GMV，。！ 2026年？")
    assert all(tok.strip() and tok.isalnum() or "_" in tok for tok in tokens)
    assert "，" not in tokens
    assert "！" not in tokens


def test_tokenize_empty_and_blank() -> None:
    assert tokenize("") == []
    assert tokenize("   ") == []
    assert tsvector_source("!!!") == ""


def test_n24_same_text_same_source_string() -> None:
    """N-24 的静态 half：同一文本经入口函数产出**完全相同**的 tsvector 源串。"""
    text = "上个月华东大区的直播渠道GMV"
    assert tsvector_source(text) == tsvector_source(text)
    # 查询侧与写入侧用的是同一个函数的同一个返回值形态
    assert " ".join(tokenize(text)) == tsvector_source(text)


def test_tsvector_source_is_space_joined_tokens() -> None:
    text = "直播渠道GMV"
    assert tsvector_source(text) == " ".join(tokenize(text))
    assert " " in tsvector_source(text)
