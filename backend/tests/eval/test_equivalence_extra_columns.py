"""W74-2（总控签）：预测**多出列**时的窄口等价判定。

规则（`equivalence._extra_column_pairs`）：仅当 `pred` 列数 > `gold` 列数时启用；
金标每列必须在预测里找到**唯一**同值列、不同金标列不落同一预测列、且配对后的
预测列下标**严格递增**；命中记 `Tag.EXTRA_COLUMNS`，多余列名写进 notes（不得静默）。

⚠️ 只放宽「多列」，不放宽「值」：H-MET-01 那种值不同的必须仍然判不等价。
"""

from __future__ import annotations

import equivalence as eq


def _t(*columns, rows):
    return eq.Table(tuple(columns), tuple(tuple(r) for r in rows))


# ==== 正例：H-ENUM-02 形状（金标 2 列 / 预测 3 列，多 shop_name）=========
def test_h_enum_02_shape_is_equivalent_via_extra_columns():
    gold = _t("shop_id", "COUNT(DISTINCT sub_order_id)", rows=[
        ("S1", 1628), ("S2", 1648), ("S3", 1601),
    ])
    pred = _t("shop_id", "shop_name", "refunded_order_cnt", rows=[
        ("S1", "旗舰店1", 1628), ("S2", "旗舰店2", 1648), ("S3", "旗舰店3", 1601),
    ])
    v = eq.compare_tables(gold, pred)
    assert v.equivalent, v.diffs
    assert eq.Tag.EXTRA_COLUMNS in v.tags, v.tags
    assert any("shop_name" in n for n in v.diffs), v.diffs


# ==== 反例 1：值不同（H-MET-01 形状）⇒ 仍不等价 ======================
def test_h_met_01_shape_values_differ_still_not_equivalent():
    gold = _t("shop_id", "SUM(v_order_paid.pay_amount)", rows=[("S1", 100.0), ("S2", 200.0)])
    pred = _t("shop_id", "shop_name", "gmv", rows=[
        ("S1", "旗舰店1", 90.0), ("S2", "旗舰店2", 180.0),
    ])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent
    assert eq.Tag.EXTRA_COLUMNS not in v.tags


# ==== 反例 2：列序倒置 ⇒ 不放行 =====================================
def test_inverted_column_order_is_rejected():
    gold = _t("a", "b", rows=[(1, 10), (2, 20)])
    pred = _t("x", "y", "z", rows=[(10, 1, "n1"), (20, 2, "n2")])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent
    assert any("未严格递增" in n for n in v.diffs), v.diffs


# ==== 反例 3：配对不唯一（vacuous）⇒ 不放行 =========================
def test_duplicate_value_column_is_not_vacuous_pass():
    """两列预测值完全相同时，金标列会命中 2 个 ⇒ 判「不唯一」，不许凑一个算等价。"""
    gold = _t("only", rows=[(1,), (2,)])
    pred = _t("p1", "p2", rows=[(1, 1), (2, 2)])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent
    assert any("唯一" in n for n in v.diffs), v.diffs


# ==== 反例 4：金标「多列、预测更少」不放宽 ===========================
def test_pred_fewer_columns_is_unchanged():
    gold = _t("a", "b", "c", rows=[(1, 2, 3)])
    pred = _t("a", "b", rows=[(1, 2)])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent
    assert any("列数不同" in n for n in v.diffs)


# ==== 反例 5：行数不同 ⇒ 多余列窄口不适用 ===========================
def test_row_count_mismatch_blocks_extra_column_path():
    gold = _t("a", rows=[(1,), (2,)])
    pred = _t("a", "b", rows=[(1, "x")])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent
    assert any("行数不同" in n for n in v.diffs), v.diffs


# ==== 等列数路径不动（id↔name 仍不放开）=============================
def test_equal_column_count_path_untouched():
    gold = _t("shop_id", "cnt", rows=[("S1", 1)])
    pred = _t("shop_name", "cnt", rows=[("旗舰店1", 1)])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent, "等列数路径不得因 W74-2 而放开 id↔name"


# ==== W75-2：金标零列必须直接拒（此前循环 0 次 ⇒ 空配对 ⇒ 判等价）====
def test_zero_column_gold_is_rejected():
    """gold 0 列 / pred 1 列（两边都 0 行）：换任何预测都不该"等价"。"""
    gold = _t(rows=[])
    pred = _t("anything", rows=[])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent
    assert eq.Tag.EXTRA_COLUMNS not in v.tags
    assert any("金标零列" in n for n in v.diffs), v.diffs


def test_zero_column_gold_with_rows_is_rejected():
    gold = _t(rows=[(), ()])
    pred = _t("cnt", rows=[(1,), (2,)])
    v = eq.compare_tables(gold, pred)
    assert not v.equivalent
    assert any("金标零列" in n for n in v.diffs), v.diffs
