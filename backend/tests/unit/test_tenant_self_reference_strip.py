"""P0-A-1：租户自指的**确定性**剥离 —— 离线契约测试。

**为什么必须有它**（实测，不是推测）：第 45 轮匣带 `w8_r44_a3.jsonl` `#13`／`#14` 显示
同批 5 条里 **4 条**模型自己把 `T_A` 剥掉、**1 条**（`E-VER-04`「T_A 的SPU 数是多少？」）没剥 ⇒
`normalized_question` 留着 `T_A` ⇒ `plan` 判"实体无法解析" ⇒ `blocking_issues` ⇒ `metrics=[]`
⇒ `refuse_out`。**靠提示词约束 LLM 的顺从性来保证一条确定性要求 = 根因**，
故本函数是**纯文本后处理**（零 LLM），本文件钉住它的规则边界：

| 断言 | 防的是 |
|---|---|
| 自己租户代号（含「的」与空白）**必被剥** | 残留 ⇒ plan 误判（本文件存在的原因） |
| **别人**租户代号**不得**被剥 | 跨租户问题必须照常被 plan 拦住（不能把用户的话改掉） |
| 只跟代号紧邻的「的」被吃 | 误吃后文所属格（"T_A 2026-08 的日期…" 里的「的」属于 `2026-08`） |
| 通用自指短语（我们租户／本租户／我们公司）同规则 | 说明里列的另三种形态漏剥 |
| 幂等 | 二次清洗不得再变形（复算要求） |
| 无自指时**逐字不动** | 不能"顺手"改动普通问句 |
"""
from __future__ import annotations

import pytest

from app.planner.payloads import strip_tenant_self_reference

T = "T_A"


@pytest.mark.parametrize(
    ("raw", "expect"),
    [
        # ── 冻结集里真实出现过的形态（逐字取自 dataset_v1_frozen.json）──
        ("T_A 的SPU 数是多少？", "SPU 数是多少？"),
        ("T_A 的在架商品数是多少？", "在架商品数是多少？"),
        ("T_A 2026-08 的日期维表有多少天？", "2026-08 的日期维表有多少天？"),
        ("T_A「3C数码」自 2026-08-01 起各店铺的浏览量分别是多少？", "「3C数码」自 2026-08-01 起各店铺的浏览量分别是多少？"),
        ("T_A 在 杭州市 的店铺各 SKU 浏览量合计是多少？", "在 杭州市 的店铺各 SKU 浏览量合计是多少？"),
        # ── 通用自指短语（与 TENANT_SELF_REFERENCE_NOTE 的举例同源）──
        ("我们租户的在架商品数是多少？", "在架商品数是多少？"),
        ("本租户 的各渠道的浏览量分别是多少？", "各渠道的浏览量分别是多少？"),
        # ── 句中出现（⚠️ 规则会连两侧空白一并吃掉 ⇒ 相邻两词会**贴合**；
        #    这是刻意的确定性取舍：冻结集里的自指**都在句首**，句中情形只为钉住边界）──
        ("按 T_A 口径，各店铺的商品数分别是多少？", "按口径，各店铺的商品数分别是多少？"),
    ],
)
def test_own_tenant_self_reference_is_stripped(raw: str, expect: str) -> None:
    """★ 正例：指向**调用者自己**的租户自指必须被剥掉（含紧跟的「的」与空白）。"""
    assert strip_tenant_self_reference(raw, T) == expect


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("T_B 的在架商品数是多少？", "**别人**的租户代号：跨租户问题必须留着让 plan 拦"),
        ("T_C 2026-08 的日期维表有多少天？", "同上（换一个代号也要拦住）"),
        ("2026-08 的日期维表有多少天？", "本来就没有自指"),
        ("各店铺的商品数分别是多少？", "本来就没有自指"),
        ("在架商品数是多少？", "本来就没有自指（且不能凭空插词）"),
    ],
)
def test_other_or_absent_codes_are_left_untouched(raw: str, why: str) -> None:
    """★ 反例：**不剥别人**、**不动没有自指的句子** —— 逐字不变。"""
    assert strip_tenant_self_reference(raw, T) == raw, why


def test_only_the_adjacent_possessive_is_eaten() -> None:
    """★ 反例（最容易写错的一处）：只吃**紧跟代号**的那个「的」。

    "T_A 2026-08 的日期维表…" 里那个「的」属于 `2026-08`（不是代号的所属格）
    ⇒ 必须保留，否则会变成语法破碎的 `2026-08 日期维表…`。
    """
    out = strip_tenant_self_reference("T_A 2026-08 的日期维表有多少天？", T)
    assert out == "2026-08 的日期维表有多少天？"
    assert "的" in out, "把后文的所属格也吃掉了 —— 会改动用户原意"


def test_idempotent() -> None:
    """★ 幂等：剥两次 == 剥一次（复算入口会重复调用同一函数）。"""
    once = strip_tenant_self_reference("T_A 的SPU 数是多少？", T)
    assert strip_tenant_self_reference(once, T) == once == "SPU 数是多少？"


def test_empty_and_blank_inputs() -> None:
    """边界：空串 / 只有自指的句子 —— 不崩、给空串，不编内容。"""
    assert strip_tenant_self_reference("", T) == ""
    assert strip_tenant_self_reference("   ", T).strip() == ""
    assert strip_tenant_self_reference("T_A 的", T) == ""


def test_tenant_id_absent_means_only_phrases_are_stripped() -> None:
    """边界：`tenant_id` 为空时**只**剥通用短语（不猜代号）。"""
    assert strip_tenant_self_reference("T_A 的SPU 数是多少？", "") == "T_A 的SPU 数是多少？"
    assert strip_tenant_self_reference("我们租户的在架商品数是多少？", "") == "在架商品数是多少？"


def test_regex_metachars_in_tenant_id_are_escaped() -> None:
    """边界：`tenant_id` 含正则元字符时按**字面**处理（`T.A` 不得当通配符用）。"""
    assert strip_tenant_self_reference("T.A 的在架商品数", "T.A") == "在架商品数"
    # 反例：`T.A` 不得把 `TBA` 也吃掉
    assert strip_tenant_self_reference("TBA 的在架商品数", "T.A") == "TBA 的在架商品数"
