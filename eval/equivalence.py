"""结果集等价判定 —— 附录 C §C.4.1 九条规则的落地（08 §3.8 产出②）。

归属窗口：W6。

为什么要单独一层，而不是直接比 `gold_result_hash`
--------------------------------------------------------------------------
哈希把**列名**也算进了载荷（`build_frozen_set.result_hash` 的 `{"cols":…, "rows":…}`），
而 §C.4.1 明确"列名/别名不同 = 等价"。所以 **哈希不一致 ≠ 必错**：
别名改写、列序调整、浮点末位、`NULL` 表示都会让哈希漂移而结果正确。
若只报哈希，评测会把大量正确结果记成失败（假失败），并污染 §C.7 的归因分布。

因此本模块产出的是**两件事**：`hash_matches`（与冻结哈希的一致性，用于快速通道）
与 `equivalent`（按 §C.4.1 的语义等价），二者不等价时由 `attribution.py` 归因。

§C.4.1 规则 → 实现对照（逐条）
--------------------------------------------------------------------------
| 情形 | 判定 | 本模块的位置 |
|---|---|---|
| 行序不同 | 等价（除显式 `ORDER BY`） | 两侧都有 `ORDER BY` 才走 `_ordered_diff`（按序逐行），否则 `_multiset_diff`（行序不参与） |
| 列序不同 | 等价（按列名/语义配对） | `_pair_columns` 先按列名、再按"整列值相同"配对 |
| 列名/别名不同 | 等价 | 同上，命中记 `ALIAS` |
| 浮点误差 | 相对误差 < 1e-6 相等 | `_cell_equal`（`REL_TOL`） |
| `NULL` vs `0` | **不等价** | `_cell_equal` 的 `None` 前置分支（不参与数值归一） |
| `ORDER BY` + `LIMIT` 边界并列 | 并列值相同则集合等价 | `LIMIT_TIE`（五条判据齐备才宽容，且**只比前 keep 行**；见 `_limit_tie`） |
| `JOIN` vs `IN (SELECT)` | 等价 | `SET_REWRITE`（SQL 形态标注，不改判定结论） |
| `IS NOT NULL` vs `> 0` | 数据无负值则等价，但**单独统计表述差异** | `EXPRESSION_DIFFERENCE` |
| 时间边界 | 日粒度下 `BETWEEN` 含尾，**不等价** → 按口径判定 | `TIME_BOUNDARY`（判不等价，交归因层） |
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

__all__ = [
    "REL_TOL",
    "Tag",
    "Table",
    "Verdict",
    "compare_tables",
    "has_explicit_order",
    "has_limit",
    "sql_tags",
]

#: §C.4.1："相对误差 < 1e-6 视为相等"。
REL_TOL: Final[float] = 1e-6

_DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}")


class Tag:
    """等价判定过程中命中的**表述差异**标签（进报告的"等价但哈希不同"细分）。

    ⚠️ 与 §C.7 的失败归因类别是两套词表：标签解释"为什么哈希不同却等价"，
    归因解释"为什么结果不同"。混用会让报告读者把两者当成同一件事。
    """

    ROW_ORDER = "row_order_difference"
    COL_ORDER = "col_order_difference"
    ALIAS = "column_alias_difference"
    FLOAT_WITHIN_TOL = "float_within_tolerance"
    SET_REWRITE = "set_semantics_rewrite"          # JOIN vs IN (SELECT)
    EXPRESSION_DIFFERENCE = "expression_difference"  # IS NOT NULL vs > 0
    TIME_BOUNDARY = "time_boundary_difference"
    LIMIT_TIE = "limit_boundary_tie"
    REPRESENTATION = "value_representation_difference"
    NULL_PRESENTATION = "null_presentation_difference"


@dataclass(frozen=True, slots=True)
class Table:
    """一张结果表（列名 + 行）。行内单元格保持**驱动原生类型**。"""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    @classmethod
    def from_cursor(cls, cursor: Any) -> Table:
        cols = tuple(d[0] for d in (cursor.description or []))
        return cls(columns=cols, rows=tuple(tuple(r) for r in cursor.fetchall()))

    def column(self, index: int) -> tuple[Any, ...]:
        return tuple(row[index] for row in self.rows)


@dataclass(frozen=True, slots=True)
class Verdict:
    equivalent: bool
    hash_matches: bool | None = None      # None = 本次没做哈希比对
    tags: tuple[str, ...] = ()
    diffs: tuple[str, ...] = ()           # 人类可读差异摘要（bad case 附录用）
    #: 行多重集比对后剩余的差异对数（0 = 完全一致）。
    unmatched: int = 0

    @property
    def equivalent_despite_hash_mismatch(self) -> bool:
        """"等价但哈希不同"——报告里必须与"真错"分开的就是这一格。"""
        return self.equivalent and self.hash_matches is False


def _to_float(value: Any) -> float | None:
    """数值化（含"数字字符串"）。字符串数值化是为 `Decimal→str` 的归一化口径让路：

    `app/exec/normalize.py` 把 `numeric` 转成**字符串**保精度，而 SQLite 驱动直接给
    `float`/`int`。两侧要能比，必须有一个共同的数值域；但**只有**在值本身可无损
    数值化时才跨（`"abc"` 仍是字符串）。
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, Decimal)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, str) and _NUMERIC_STR.match(value.strip()):
        try:
            return float(value)
        except (ValueError, InvalidOperation):
            return None
    return None


_NUMERIC_STR = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _cell_equal(gold: Any, pred: Any) -> tuple[bool, str | None]:
    """单元格相等判定。返回 `(是否相等, 命中的标签)`。"""
    if gold is None or pred is None:
        # §C.4.1：NULL vs 0 不等价 —— None 必须先短路，不能被数值化吃掉。
        return (gold is pred if gold is None and pred is None else False), Tag.NULL_PRESENTATION
    if isinstance(gold, (str, bytes, bool)) or isinstance(pred, (str, bytes, bool)):
        pass  # 走下方数值/字符串双路，不做日期特判
    gf, pf = _to_float(gold), _to_float(pred)
    if gf is not None and pf is not None:
        if gf == pf:
            return True, Tag.REPRESENTATION if type(gold) is not type(pred) else None
        denom = max(abs(gf), abs(pf))
        if denom > 0 and abs(gf - pf) / denom < REL_TOL:
            return True, Tag.FLOAT_WITHIN_TOL
        return False, None
    if _norm_scalar(gold) == _norm_scalar(pred):
        return True, Tag.REPRESENTATION if type(gold) is not type(pred) else None
    if _is_timeish(gold) or _is_timeish(pred):
        return False, Tag.TIME_BOUNDARY
    return False, None


def _norm_scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        # 时间戳按 ISO 比：带时区的先归一到同一时刻（07 §8.4 的 +08:00 口径）。
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, Decimal):
        return str(value)
    return value


def _is_timeish(value: Any) -> bool:
    return isinstance(value, (datetime, date)) or (isinstance(value, str) and bool(_DATEISH.match(value)))


def _row_key(row: Sequence[Any]) -> tuple[Any, ...]:
    """精确比对的键（浮点按 `REL_TOL` 量级离散化，避免 1e-7 抖动把多重集打散）。"""
    out: list[Any] = []
    for cell in row:
        f = _to_float(cell)
        if f is None:
            out.append(_norm_scalar(cell))
        else:
            out.append(round(f, 9) if abs(f) < 1 else float(f"{f:.12g}"))
    return tuple(out)


def _pair_columns(gold: Table, pred: Table) -> tuple[tuple[int, int], tuple[str, ...]]:
    """列配对：先按列名，剩余按"整列值多重集相同"。返回 `(配对下标, 标签)`。"""
    tags: list[str] = []
    pairs: list[tuple[int, int]] = []
    used_pred: set[int] = set()
    gold_names = {name: i for i, name in enumerate(gold.columns)}
    for j, pname in enumerate(pred.columns):
        i = gold_names.get(pname)
        if i is not None and i not in {p for p, _ in pairs}:
            pairs.append((i, j))
            used_pred.add(j)
    if len(pairs) == len(gold.columns) == len(pred.columns):
        if tuple(sorted(pairs)) != tuple(enumerate(range(len(pairs)))):
            tags.append(Tag.COL_ORDER)
        return tuple(sorted(pairs)), tuple(tags)

    # 列名没配全：按"整列值多重集"配对未命中的列（覆盖纯改名情形）。
    unmatched_gold = [i for i in range(len(gold.columns)) if i not in {p for p, _ in pairs}]
    unmatched_pred = [j for j in range(len(pred.columns)) if j not in used_pred]
    for i in list(unmatched_gold):
        gkey = Counter(_row_key((v,)) for v in gold.column(i))
        for j in list(unmatched_pred):
            if Counter(_row_key((v,)) for v in pred.column(j)) == gkey:
                pairs.append((i, j))
                unmatched_gold.remove(i)
                unmatched_pred.remove(j)
                break
        if i not in unmatched_gold:
            continue
    if len(pairs) != len(gold.columns) or len(gold.columns) != len(pred.columns):
        return tuple(sorted(pairs)), tuple(tags)
    renamed = any(gold.columns[i] != pred.columns[j] for i, j in pairs)
    if renamed:
        tags.append(Tag.ALIAS)
    if tuple(sorted(pairs)) != tuple(enumerate(range(len(pairs)))):
        tags.append(Tag.COL_ORDER)
    return tuple(sorted(pairs)), tuple(tags)


def _multiset_diff(
    gold: Table, pred: Table, pairs: Sequence[tuple[int, int]]
) -> tuple[int, list[str], tuple[str, ...]]:
    """按配对后的列做**多重集**比对（行序不参与 —— §C.4.1 第 1 条）。"""
    g_rows = Counter(_row_key(tuple(row[i] for i, _ in pairs)) for row in gold.rows)
    p_rows = Counter(_row_key(tuple(row[j] for _, j in pairs)) for row in pred.rows)
    only_gold = g_rows - p_rows
    only_pred = p_rows - g_rows
    n = sum(only_gold.values())
    notes: list[str] = []
    if only_gold or only_pred:
        notes.append(
            f"行多重集差异：仅金标 {sum(only_gold.values())} 行 / 仅预测 {sum(only_pred.values())} 行"
        )
    return n, notes, ()


def compare_tables(
    gold: Table,
    pred: Table,
    *,
    gold_sql: str = "",
    pred_sql: str = "",
    hash_matches: bool | None = None,
) -> Verdict:
    """§C.4.1 等价判定主入口。"""
    tags: list[str] = []
    notes: list[str] = []
    if len(gold.columns) != len(pred.columns):
        return Verdict(
            False, hash_matches, (),
            (f"列数不同：金标 {len(gold.columns)} / 预测 {len(pred.columns)}",),
        )
    if len(gold.rows) != len(pred.rows):
        tie = _limit_tie(gold, pred, gold_sql, pred_sql)
        if tie is None:
            notes.append(f"行数不同：金标 {len(gold.rows)} / 预测 {len(pred.rows)}")
            return Verdict(False, hash_matches, tuple(tags), tuple(notes))
        note, keep = tie
        tags.append(Tag.LIMIT_TIE)
        notes.append(note)
        # 宽容档的作用域**恰好**是并列那一段：两侧一起截到前 keep 行再比，不多给一行。
        gold = Table(gold.columns, gold.rows[:keep])
        pred = Table(pred.columns, pred.rows[:keep])

    pairs, col_tags = _pair_columns(gold, pred)
    tags.extend(col_tags)
    if len(pairs) != len(gold.columns):
        return Verdict(False, hash_matches, tuple(tags), ("列无法配对（列数相同但内容不匹配）",))

    gold_ordered = has_explicit_order(gold_sql) and has_explicit_order(pred_sql)
    if gold_ordered:
        unmatched, row_notes, row_tags = _ordered_diff(gold, pred, pairs)
    else:
        unmatched, row_notes, row_tags = _multiset_diff(gold, pred, pairs)
    tags.extend(row_tags)
    notes.extend(row_notes)

    if unmatched:
        if gold_ordered:
            # ⚠️ 这里**不能**再走一遍容差匹配：`_tolerant_match` 是贪心无序的，
            # 会把"两侧都要求 ORDER BY 却答错行序"洗成等价 —— 而 §C.4.1 第 1 条
            # 的括号（"除显式 ORDER BY"）正是本模块唯一让行序参与结论的地方。
            notes.append("已跳过容差重匹配（两侧均要求 ORDER BY ⇒ 行序参与判据）")
        else:
            tolerant, t_notes = _tolerant_match(gold, pred, pairs)
            if tolerant:
                unmatched = 0
                tags.append(Tag.FLOAT_WITHIN_TOL)
                notes.extend(t_notes)
            else:
                notes.extend(t_notes)

    tags.extend(t for t in sql_tags(gold_sql, pred_sql) if t not in tags)
    return Verdict(unmatched == 0, hash_matches, tuple(dict.fromkeys(tags)), tuple(notes), unmatched)


def _ordered_diff(
    gold: Table, pred: Table, pairs: Sequence[tuple[int, int]]
) -> tuple[int, list[str], tuple[str, ...]]:
    """两侧都有显式 `ORDER BY`：按序逐行比（行序是语义的一部分）。"""
    n = 0
    notes: list[str] = []
    tags: set[str] = set()
    for r, (grow, prow) in enumerate(zip(gold.rows, pred.rows, strict=False)):
        for i, j in pairs:
            ok, tag = _cell_equal(grow[i], prow[j])
            if not ok:
                n += 1
                if len(notes) < 5:
                    notes.append(f"第 {r} 行 列 {gold.columns[i]!r}：金标 {grow[i]!r} vs 预测 {prow[j]!r}")
            elif tag:
                tags.add(tag)
    if gold.rows != pred.rows:
        if _multiset_diff(gold, pred, pairs)[0] == 0:
            tags.add(Tag.ROW_ORDER)  # 值都在、位置不对 ⇒ 纯粹的排序错（报告里与"值也错"分开）
        elif n == 0:
            tags.add(Tag.REPRESENTATION)
    return n, notes, tuple(sorted(tags))


def _tolerant_match(
    gold: Table, pred: Table, pairs: Sequence[tuple[int, int]]
) -> tuple[bool, list[str]]:
    """多重集精确比对失败后，用带容差的单元格比较做一对一贪心匹配。

    为什么要第二段：`_row_key` 的离散化只保证"同一量级不误伤"，跨量级的
    `1e-7` 相对差、以及 `Decimal→str` 与 `float` 的表示差仍会打散多重集。
    """
    used: set[int] = set()
    notes: list[str] = []
    for grow in gold.rows:
        gtuple = tuple(grow[i] for i, _ in pairs)
        hit = None
        for k, prow in enumerate(pred.rows):
            if k in used:
                continue
            if all(_cell_equal(gv, prow[j])[0] for gv, (_, j) in zip(gtuple, pairs, strict=True)):
                hit = k
                break
        if hit is None:
            notes.append(f"金标行无法在预测结果中找到：{gtuple!r}")
            return False, notes[:5]
        used.add(hit)
    return len(used) == len(pred.rows), notes[:5]


def _limit_tie(gold: Table, pred: Table, gold_sql: str, pred_sql: str) -> tuple[str, int] | None:
    """`ORDER BY` + `LIMIT` 的边界并列：并列值相同则视集合等价（§C.4.1 第 6 条）。

    返回 `(说明, 参与比对的行数)`；任一判据不成立一律 `None` ⇒ **宁可判不等**。

    🔴 为什么把条件收紧到五条（旧版实测会把"少答"判成"等价"）：旧实现只要求
    "两侧截断点那一格取值相同"，而那一格本来就是同一行 —— 于是**金标 10 行 / 预测 3 行**
    只要预测是金标的前缀就通过。`LIMIT` 题少答 Top-N 是最常见的真错，
    被这条宽容档吃掉等于给 EX 开后门。现在必须同时成立：
    ① 两侧都有 `ORDER BY` + `LIMIT`；② 排序键是**可识别的裸列名**且两侧同名
    （表达式/序号排序定位不了键 ⇒ 不宽容）；③ **短的一侧行数 = 它自己的 `LIMIT`**
    （没跑到上限就是少答，不是并列）；④ 前 `keep` 行多重集相同；
    ⑤ 长的一侧多出来的行**逐行**与边界键值并列。
    """
    for sql in (gold_sql, pred_sql):
        if not (has_explicit_order(sql) and has_limit(sql)):
            return None
    key = _order_key_name(gold_sql)
    if key is None or key != _order_key_name(pred_sql):
        return None

    n_gold, n_pred = len(gold.rows), len(pred.rows)
    keep = min(n_gold, n_pred)
    if keep == 0:
        return None

    short_sql, short_n = (gold_sql, n_gold) if n_gold <= n_pred else (pred_sql, n_pred)
    if _limit_value(short_sql) != short_n:
        return None  # 短侧没跑到自己的 LIMIT ⇒ 少答，不是边界并列

    long_table, short_table = (pred, gold) if n_gold <= n_pred else (gold, pred)
    key_idx = next((i for i, c in enumerate(short_table.columns) if c.lower() == key), None)
    long_key_idx = next((i for i, c in enumerate(long_table.columns) if c.lower() == key), None)
    if key_idx is None or long_key_idx is None:
        return None  # 排序键不在结果列里 ⇒ 无法验证并列，fail closed

    boundary = _row_key((short_table.column(key_idx)[keep - 1],))
    if any(_row_key((row[long_key_idx],)) != boundary for row in long_table.rows[keep:]):
        return None
    if Counter(_row_key(tuple(r)) for r in short_table.rows[:keep]) != \
            Counter(_row_key(tuple(r)) for r in long_table.rows[:keep]):
        return None
    return (
        f"边界并列：短侧 {short_n} 行已到 `LIMIT`，长侧多出的 {abs(n_gold - n_pred)} 行排序键 "
        f"{short_table.columns[key_idx]!r} 与边界值并列 ⇒ 按集合等价（只比前 {keep} 行）"
    ), keep


# ---------------------------------------------------------------------------
# SQL 形态侧的辅助判据（只用于打标签，不参与"是否等价"的结论）
# ---------------------------------------------------------------------------

_ORDER_BY = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_LIMIT = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_IN_SUBQUERY = re.compile(r"\bIN\s*\(\s*SELECT\b", re.IGNORECASE)
_JOIN = re.compile(r"\b(INNER|LEFT|RIGHT|FULL|CROSS)?\s*JOIN\b", re.IGNORECASE)
_IS_NOT_NULL = re.compile(r"\bIS\s+NOT\s+NULL\b", re.IGNORECASE)
_GT_ZERO = re.compile(r">\s*0\b")
_BETWEEN = re.compile(r"\bBETWEEN\b", re.IGNORECASE)
#: 半开区间的**书写形态**是 `>= '…' AND 列 < '…'`。
#: ⚠️ 这里曾写成 `>\s*'`（漏了 `=`）⇒ `>=` 永远不匹配 ⇒ 第 9 条的标签**从来没打过**。
#: 一条永不命中的判据比没有判据更糟：它让"时间边界差异"在归因分布里永远是 0。
_HALF_OPEN = re.compile(r">=\s*'[^']+'\s+AND\s+[A-Za-z_][\w.]*\s*(?:<=|<)\s*'", re.IGNORECASE)
_ORDER_KEY = re.compile(r"\bORDER\s+BY\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
_LIMIT_VALUE = re.compile(r"\bLIMIT\s+(\d+)", re.IGNORECASE)


def has_explicit_order(sql: str) -> bool:
    """是否含 `ORDER BY`（顶层或子查询都算 —— 只要有序输出被要求过）。"""
    return bool(_ORDER_BY.search(sql or ""))


def _order_key_name(sql: str) -> str | None:
    """第一条 `ORDER BY` 的**裸列名**（去掉表前缀、小写）。

    只认"列名"形态：`ORDER BY SUM(x) DESC` / `ORDER BY 1` 定位不到结果列，
    返回 `None` 让调用方**放弃宽容**（§C.4.1 第 6 条的前提是"能验证并列值"）。
    """
    m = _ORDER_KEY.search(sql or "")
    if not m:
        return None
    return m.group(1).rsplit(".", 1)[-1].lower()


def _limit_value(sql: str) -> int | None:
    m = _LIMIT_VALUE.search(sql or "")
    return None if m is None else int(m.group(1))


def has_limit(sql: str) -> bool:
    return bool(_LIMIT.search(sql or ""))


def sql_tags(gold_sql: str, pred_sql: str) -> tuple[str, ...]:
    """两侧 SQL 的**表述差异**标签（§C.4.1 要求"单独统计"的两类）。"""
    tags: list[str] = []
    if (_IN_SUBQUERY.search(pred_sql) and _JOIN.search(gold_sql)) or (
        _IN_SUBQUERY.search(gold_sql) and _JOIN.search(pred_sql)
    ):
        tags.append(Tag.SET_REWRITE)
    if (_IS_NOT_NULL.search(pred_sql) and _GT_ZERO.search(gold_sql)) or (
        _IS_NOT_NULL.search(gold_sql) and _GT_ZERO.search(pred_sql)
    ):
        tags.append(Tag.EXPRESSION_DIFFERENCE)
    if (_BETWEEN.search(pred_sql) and _HALF_OPEN.search(gold_sql)) or (
        _BETWEEN.search(gold_sql) and _HALF_OPEN.search(pred_sql)
    ):
        # ⚠️ 必须**双向**：第 9 条讲的是"两种写法不同"，与哪一侧用 BETWEEN 无关。
        # 只判单向会让归因分布里的 `time_semantics` 少掉一半（本模块曾就是这么写的）。
        tags.append(Tag.TIME_BOUNDARY)
    return tuple(tags)


def shape_of(table: Table, *, limit: int = 5) -> dict[str, Any]:
    """bad case 附录用的紧凑摘要（默认截断 5 行 —— 报告不进无界载荷）。"""
    return {
        "columns": list(table.columns),
        "row_count": len(table.rows),
        "head_rows": [[_norm_scalar(v) for v in row] for row in table.rows[:limit]],
    }


@dataclass(slots=True)
class DiffLedger:
    """一次 run 内累计的标签计数（报告 §4 归因分布的旁证）。"""

    counter: Counter[str] = field(default_factory=Counter)

    def add(self, tags: Sequence[str]) -> None:
        self.counter.update(tags)
