"""`eval/equivalence.py` 的单元测试 —— 附录 C §C.4.1 九条规则逐条落地校验。

归属窗口：W6（D4 裁定：评测器测试放 `backend/tests/eval/`）。

为什么这一层最值得测
--------------------------------------------------------------------------
`equivalence.compare_tables` 是 EX 的**唯一判据**。它写错的方向有两种，且都不报错：

* **假失败**（把等价判成不等）→ 门禁红，下一轮有人来放宽 `REL_TOL`；
* **假通过**（把不等判成等价）→ 门禁绿，而绿是"上线依据"。

第二条是红线。所以每条规则都配一个**反例断言**（同一条代码路径必须能判出不等），
只写正例的测试等于给判定器发通行证。

⚠️ `Table.rows` 用 tuple of tuple：`compare_tables` 按位置取列，list 也能跑，
但用 tuple 才能在"实现偷偷改了行容器类型"时立刻显形。
"""

from __future__ import annotations

from typing import ClassVar

import equivalence as eq


def _t(*columns, rows):
    return eq.Table(tuple(columns), tuple(tuple(r) for r in rows))


# ==== 规则 1：行序不同 = 等价（无显式 ORDER BY 时）====================
def test_row_order_difference_is_equivalent_without_order_by():
    gold = _t("region", "gmv", rows=[["华东", 100.0], ["华南", 90.0]])
    pred = _t("region", "gmv", rows=[["华南", 90.0], ["华东", 100.0]])
    v = eq.compare_tables(gold, pred)
    assert v.equivalent and v.unmatched == 0


def test_row_order_is_semantic_when_both_sides_order_by():
    """两侧都写了 `ORDER BY` ⇒ 行序进入判据（规则 1 的反面）。

    🔴 这条守的是修过的假通过：容差重匹配（`_tolerant_match`）是**无序贪心**，
    旧版在有序比对失败后仍跑它一遍 ⇒ "ORDER BY 答错序"被洗成等价。
    """
    gold = _t("region", "gmv", rows=[["华东", 100.0], ["华南", 90.0]])
    pred = _t("region", "gmv", rows=[["华南", 90.0], ["华东", 100.0]])
    sql = "SELECT region, gmv FROM t ORDER BY gmv DESC"
    v = eq.compare_tables(gold, pred, gold_sql=sql, pred_sql=sql)
    assert v.equivalent is False
    assert eq.Tag.ROW_ORDER in v.tags          # 报告要能把"只错顺序"与"值也错"分开


def test_ordered_comparison_still_tolerates_float_noise():
    """行序参与判据 ≠ 放弃 `REL_TOL`：同一格里的浮点尾差仍须判等。"""
    gold = _t("k", "gmv", rows=[["a", 100.0], ["b", 90.0]])
    pred = _t("k", "gmv", rows=[["a", 100.00000001], ["b", 90.0]])
    sql = "SELECT k, gmv FROM t ORDER BY gmv DESC"
    v = eq.compare_tables(gold, pred, gold_sql=sql, pred_sql=sql)
    assert v.equivalent is True and eq.Tag.FLOAT_WITHIN_TOL in v.tags


# ==== 规则 2/3：列序与列名（别名）不同 = 等价 ==========================
def test_column_reorder_and_alias_are_equivalent_and_tagged():
    gold = _t("region", "gmv", rows=[["华东", 100.0], ["华南", 90.0]])
    pred = _t("gmv", "site_label", rows=[[100.0, "华东"], [90.0, "华南"]])
    v = eq.compare_tables(gold, pred)
    assert v.equivalent
    assert {eq.Tag.ALIAS, eq.Tag.COL_ORDER} <= set(v.tags)


def test_unpairable_columns_are_not_equivalent():
    """列名不同**且**整列值也配不上 ⇒ 不许靠"列数相同"蒙过去。"""
    gold = _t("gmv", rows=[[100.0], [90.0]])
    pred = _t("gmv_wrong", rows=[["a"], ["b"]])
    v = eq.compare_tables(gold, pred)
    assert v.equivalent is False
    assert "列无法配对" in v.diffs[0]


def test_column_count_mismatch_short_circuits():
    v = eq.compare_tables(_t("a", "b", rows=[[1, 2]]), _t("a", rows=[[1]]))
    assert v.equivalent is False and v.diffs == ("列数不同：金标 2 / 预测 1",)


# ==== 规则 4：浮点相对误差 < 1e-6 相等 ================================
def test_float_within_relative_tolerance_is_equal():
    gold = _t("gmv", rows=[[3.0]])
    pred = _t("gmv", rows=[[3.0000000001]])
    v = eq.compare_tables(gold, pred)
    assert v.equivalent and eq.Tag.FLOAT_WITHIN_TOL in v.tags


def test_float_beyond_tolerance_is_not_equal():
    """`REL_TOL` 的正面对照：差 1% 必须判不等，否则"容差"就成了橡皮图章。"""
    v = eq.compare_tables(_t("gmv", rows=[[100.0]]), _t("gmv", rows=[[101.0]]))
    assert v.equivalent is False


def test_numeric_string_from_normalize_matches_float():
    """`app/exec/normalize.py` 给 `numeric` → **字符串**，沙箱给 float ⇒ 必须可比。

    ⚠️ 只断言"等价"不断言标签：无序路径经 `_row_key` 离散化后两侧同键，
    `REPRESENTATION` 只在逐格比对（`_cell_equal`）时才打 —— 拿标签当必要条件会逼着
    后人去放宽值比较，方向正好相反。
    """
    v = eq.compare_tables(_t("gmv", rows=[[1234.56]]), _t("gmv", rows=[["1234.56"]]))
    assert v.equivalent


# ==== 规则 5：NULL vs 0 **不等价**（最容易写成"都是空"的一格）==========
def test_null_versus_zero_is_not_equivalent():
    gold = _t("a", "b", rows=[[1, None], [2, 3.0]])
    pred = _t("a", "b", rows=[[1, 0], [2, 3.0]])
    assert eq.compare_tables(gold, pred).equivalent is False


def test_null_versus_empty_string_is_not_equivalent():
    assert eq.compare_tables(_t("a", rows=[[None]]), _t("a", rows=[[""]])).equivalent is False


def test_null_versus_null_is_equivalent():
    assert eq.compare_tables(_t("a", rows=[[None]]), _t("a", rows=[[None]])).equivalent is True


# ==== 规则 6：ORDER BY + LIMIT 的边界并列 ==============================
_TOP_SQL = "SELECT name, v FROM t ORDER BY v DESC LIMIT 2"


def test_limit_boundary_tie_is_tolerated():
    """长侧多出的那一行与边界值**并列** ⇒ 按集合等价（只比前 2 行）。"""
    gold = _t("name", "v", rows=[["x", 1], ["y", 2], ["z", 2]])
    pred = _t("name", "v", rows=[["x", 1], ["y", 2]])
    v = eq.compare_tables(gold, pred, gold_sql=_TOP_SQL, pred_sql=_TOP_SQL)
    assert v.equivalent and eq.Tag.LIMIT_TIE in v.tags


def test_limit_prefix_that_is_not_a_tie_is_not_equivalent():
    """反例（本模块修过的假通过）：多出的行 v=3 **高于**边界值 ⇒ 是真少答，不是并列。"""
    gold = _t("name", "v", rows=[["x", 3], ["y", 2], ["z", 1]])
    pred = _t("name", "v", rows=[["y", 2], ["z", 1]])
    v = eq.compare_tables(gold, pred, gold_sql=_TOP_SQL, pred_sql=_TOP_SQL)
    assert v.equivalent is False


def test_short_side_below_its_own_limit_is_under_answering():
    """反例：短侧只回 2 行但自己写的是 `LIMIT 5` ⇒ 没跑到上限，没有"并列"可言。"""
    gold = _t("name", "v", rows=[["x", 1], ["y", 2], ["z", 2]])
    pred = _t("name", "v", rows=[["x", 1], ["y", 2]])
    v = eq.compare_tables(
        gold, pred, gold_sql=_TOP_SQL,
        pred_sql="SELECT name, v FROM t ORDER BY v DESC LIMIT 5",
    )
    assert v.equivalent is False


def test_tie_tolerance_does_not_extend_to_ordering_key_that_is_not_a_result_column():
    """排序键定位不到（`ORDER BY SUM(x)`）⇒ fail closed，不猜哪一列是键。"""
    gold = _t("name", "v", rows=[["x", 1], ["y", 2], ["z", 2]])
    pred = _t("name", "v", rows=[["x", 1], ["y", 2]])
    sql = "SELECT name, SUM(v) FROM t GROUP BY name ORDER BY SUM(v) DESC LIMIT 2"
    assert eq.compare_tables(gold, pred, gold_sql=sql, pred_sql=sql).equivalent is False


def test_row_count_difference_without_limit_is_not_equivalent():
    """反例：没有 LIMIT 就没有"并列"可言，少一行就是少一行。"""
    gold = _t("k", rows=[["a"], ["b"], ["c"]])
    pred = _t("k", rows=[["a"], ["b"]])
    v = eq.compare_tables(gold, pred)
    assert v.equivalent is False and "行数不同" in v.diffs[0]


# ==== 规则 7/8/9：SQL 形态侧的表述差异（只打标签，不改结论）============
def test_join_vs_in_subquery_is_tagged_as_set_rewrite():
    tags = eq.sql_tags(
        "SELECT a FROM t JOIN u ON t.k=u.k",
        "SELECT a FROM t WHERE k IN (SELECT k FROM u)",
    )
    assert eq.Tag.SET_REWRITE in tags


def test_is_not_null_vs_gt_zero_is_tagged_as_expression_difference():
    tags = eq.sql_tags("SELECT a FROM t WHERE v > 0", "SELECT a FROM t WHERE v IS NOT NULL")
    assert eq.Tag.EXPRESSION_DIFFERENCE in tags


def test_same_shape_sql_gets_no_morphology_tags():
    assert eq.sql_tags("SELECT a FROM t WHERE v > 0", "SELECT a FROM t WHERE v > 0") == ()


def test_time_boundary_tags_but_does_not_rescue_inequality():
    """`BETWEEN` 含尾 vs 半开区间 ⇒ 日期单元格不等价，只留 `TIME_BOUNDARY` 标签。"""
    gold = _t("d", rows=[["2026-09-30"]])
    pred = _t("d", rows=[["2026-10-01"]])
    v = eq.compare_tables(
        gold, pred,
        gold_sql="SELECT d FROM t WHERE d BETWEEN '2026-09-01' AND '2026-09-30'",
        pred_sql="SELECT d FROM t WHERE d >= '2026-09-01' AND d < '2026-10-01'",
    )
    assert v.equivalent is False and eq.Tag.TIME_BOUNDARY in v.tags


# ==== 哈希通道与语义通道必须分开呈现 ==================================
def test_hash_mismatch_does_not_imply_wrong():
    """别名会改哈希（载荷含 `cols`），但结论是等价 —— 报告里这一格叫"等价但哈希不同"。"""
    gold = _t("gmv", rows=[[1.0]])
    pred = _t("pay_gmv", rows=[[1.0]])
    v = eq.compare_tables(gold, pred, hash_matches=False)
    assert v.equivalent and v.hash_matches is False and v.equivalent_despite_hash_mismatch


def test_hash_channel_defaults_to_none_meaning_not_computed():
    assert eq.compare_tables(_t("a", rows=[[1]]), _t("a", rows=[[1]])).hash_matches is None


def test_equivalent_despite_hash_mismatch_is_false_when_hashes_agree():
    v = eq.compare_tables(_t("a", rows=[[1]]), _t("a", rows=[[1]]), hash_matches=True)
    assert v.equivalent and not v.equivalent_despite_hash_mismatch


# ==== `Table.from_cursor`：驱动契约的两形状 ===========================
def test_from_cursor_reads_bare_tuple_description():
    """sqlite3 给裸 7 元组 ⇒ `equivalence` 走 `d[0]` 这一路。"""
    class _Cur:
        description: ClassVar[list[tuple]] = [
            ("a", None, None, None, None, None, None),
            ("b", None, None, None, None, None, None),
        ]

        def fetchall(self):
            return [(1, 2.0), (3, 4.0)]

    table = eq.Table.from_cursor(_Cur())
    assert table.columns == ("a", "b") and table.rows == ((1, 2.0), (3, 4.0))
    assert table.column(1) == (2.0, 4.0)


def test_column_desc_satisfies_both_driver_contracts():
    """`ColumnDesc` 存在的理由：在线 `_execute_and_collect` 取 `d.name`，本模块取 `d[0]`。

    任一侧失配都是一批用例空跑（实测红队 15 条执行用例因裸元组全炸），所以两个面都断言。
    """
    from sqlite_exec import ColumnDesc

    desc = ColumnDesc("gmv", 700, None, None, None, None, None)
    assert desc[0] == "gmv" and desc.name == "gmv"


def test_from_cursor_treats_empty_description_as_no_columns():
    class _Cur:
        description = None

        def fetchall(self):
            return []

    assert eq.Table.from_cursor(_Cur()).columns == ()


# ==== 辅助判据本身（判据错了上面全部失效）=============================
def test_has_explicit_order_and_limit_detect_case_and_spacing():
    assert eq.has_explicit_order("select * from t order\tby x")
    assert not eq.has_explicit_order("select * from t")
    assert eq.has_limit("SELECT * FROM t LIMIT 10")
    assert not eq.has_limit("select * from t")


def test_shape_of_caps_rows_so_reports_stay_bounded():
    table = _t("a", rows=[[i] for i in range(50)])
    assert len(eq.shape_of(table, limit=5)["head_rows"]) == 5
    assert eq.shape_of(table)["row_count"] == 50
