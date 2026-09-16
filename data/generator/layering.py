#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
4×3 分层判定器（确定性，可复现）

归属窗口：W1A（data/**）      对应 DoD③：4×3 网格每格 ≥ 8 条

两根轴
------
轴 1｜结构复杂度：**按 Spider 官方 `evaluation.py` 原样实现**（不是凭文档转述）
    来源：`github.com/taoyds/spider` → `evaluation.py`
    本实现**逐字对齐**三个计数器：
      · `count_component1`：WHERE / GROUP BY / ORDER BY / LIMIT 各 +1；
        **JOIN 贡献 `len(table_units) - 1`**（即"多余表数"，单表 +0）；
        WHERE/HAVING/ON 里的 **`OR` 出现次数**逐个 +1；**`LIKE` 条件个数**逐个 +1。
      · `count_component2`：`len(get_nestedSQL(sql))` —— 上游把**子查询、CTE、
        以及 UNION/EXCEPT/INTERSECT 的分支**都塞进 nested 列表，故三者都计入。
      · `count_others`：**不是原始长度求和**，而是"4 类中满足『多』的类数"（0–4）：
        聚合函数总数 >1 记 1；SELECT 列数 >1 记 1；WHERE 条件单元数 >1 记 1；
        GROUP BY 列数 >1 记 1。
    分级判据（`eval_hardness` 原样）：
        easy  : comp1 <= 1 and others == 0 and comp2 == 0
        medium: (others <= 2 and comp1 <= 1 and comp2 == 0) or (comp1 <= 2 and others < 2 and comp2 == 0)
        hard  : (others > 2 and comp1 <= 2 and comp2 == 0) or
                (2 < comp1 <= 3 and others <= 2 and comp2 == 0) or
                (comp1 <= 1 and others == 0 and comp2 <= 1)
        extra : 其余

    ⚠️ **两处上游实况（已 curl 原文核实，登记 U-29 / U-30）**

      U-29｜`component2` 的定义，附录 C 抄了一个**死常量**。
        附录 C §C.3.1 写「Component2：EXCEPT、UNION、INTERSECT」，来源标注"行号 53-56"。
        实测 `evaluation.py` 该处是：
            HARDNESS = {"component1": (...), "component2": ('except','union','intersect')}
        而 **`HARDNESS` 这个字典在全文件只出现这一次 —— 定义了，从未被使用**。
        真正生效的是 `count_component2(sql)` → `len(get_nestedSQL(sql))`，
        而 `get_nestedSQL` 收集的是
        **WHERE/HAVING/ON 里的子查询 + intersect/except/union 分支**。
        → 即：**子查询也计入 component2**，附录 C 只写了集合运算那一半。
        **07 §4.7.1 已采纳本诊断**（口径 = `len(get_nestedSQL())`，子查询计入）。
        本文件以上游生效代码为准；输出同时保留 `comp2_setops` 供核对。
        ⚠️ 引用一律按**函数名**，不按行号 —— 07 §4.1 禁令 4（U-29 的事故根因就是行号引用）。

      U-30｜按上游代码实算，**官方站点标注的 "Hard" 示例会得到 "extra"**。
        官方示例（`_refs/spider_examples.png` 实读）：
            SELECT T1.country_name FROM countries T1 JOIN continents T2 ON T1.continent=T2.cont_id
            JOIN car_makers T3 ON T1.country_id=T3.country
            WHERE T2.continent='Europe' GROUP BY T1.country_name HAVING COUNT(*)>=3
        按 `count += len(table_units) - 1`：3 张表 → +2，
        再加 WHERE(+1) 与 GROUP BY(+1) → **comp1 = 4**，others = 0，comp2 = 0
        → `eval_hardness` 落入 `else: return "extra"`。**与站点标注的 Hard 不符。**
        反之若 JOIN 只记 1 个组件（"站点标签口径"），comp1 = 3 → hard，四个官方示例全部吻合。

      **07 §4.7.2 的裁定（v0.8，已落）**：
        · `difficulty_struct` **= 上游代码口径，唯一主口径**（理由：可复现；且换站点口径会让
          `extra` 档从 28 条塌成 3 条 → **DoD③ 直接不达标**）。
        · `difficulty_struct_sitelabel` **降级为对照字段** ——
          **禁止**用于：分层统计 / 门禁判定 / 报告 headline / 任何"覆盖率"断言。
          唯一用途 = 让后来人一眼看到"我们与站点标签差在哪"（U-30 的物证）。
        · **官方 4 锚点降级为"差异记录"，不作为门禁**（其中 Hard 一条在采纳口径下必然不符）。
        · **另立本项目锚点**（`PROJECT_ANCHORS`，CI 断言 100% 命中）——
          锚点必须是"**采纳口径下的真实边界**"，不是"我们希望它是什么"。
          `--anchors` 一次打印两组锚点。

      ⚠️ **裁定锚点描述里的一处不一致（W1A 实测，与 U-30 同形态）**：
        07 §4.7.2 锚点③写「3 表 JOIN + WHERE + GROUP BY（`comp1=4`）→ `hard`」。
        按被它自己定为唯一主口径的代码实算：`comp1 = (3-1) + 1 + 1 = 4` →
        `spider_level(4, 0, others)` 三条 hard 子句**全不满足** → **`extra`**。
        `comp1=4` 落 `extra` 这一点，**正是 U-30 的结论本身**（官方 Hard 示例 comp1=4 → extra）。
        → 本文件不按那句话写锚点，而是**按真实边界**写，并把该 SQL 作为
          "**裁定描述 vs 采纳口径的分歧点**"锚点单独列出（`DIVERGENCE`）。

轴 2｜业务语义复杂度：附录 C §C.3.3 原样
     · 低：`business_knowledge_required` 为空
     · 中：恰好 1 项「类 A」知识 —— ① 同义词/黑话 ② 维度层级/大区映射 ③ 枚举值映射
     · 高：含任一「类 B」知识（指标口径 / 时间口径 / 默认谓词 / 模糊词澄清），
           或累计 ≥ 2 项知识（不论 A/B）

用法
----
    # 给用例集打标（就地写回，并校验既有标注是否与判定一致）
    python data/generator/layering.py --in eval/dataset_v1_frozen.json --out eval/dataset_v1_frozen.json
    # 只判定一条 SQL
    python data/generator/layering.py --sql "SELECT SUM(pay_amount) FROM v_order_paid WHERE pay_time >= '2026-01-01'"
    # 自检：打印 4×3 网格计数
    python data/generator/layering.py --in X --grid
    # 锚点回归（**本项目锚点 = 门禁**；官方锚点只作差异记录）→ 退出码即门禁结论
    python data/generator/layering.py --anchors
"""

from __future__ import annotations

import argparse
import json
import sys

import sqlglot
from sqlglot import exp

# ---- 读取方言：评测沙箱是 SQLite（07 §17.4 / 附录 C §C.14）----
DIALECT = "sqlite"

# ---- 轴 2 的知识标签分类（附录 C §C.3.3 的 ①②③ vs ④）----
SEM_A = ("synonym", "value_map", "enum", "hierarchy")      # 命中 1 项即"中"
SEM_B = ("metric", "time", "predicate", "fuzzy")           # 命中任一即"高"

AGG_TYPES = (exp.Sum, exp.Avg, exp.Count, exp.Min, exp.Max,
             exp.ArrayAgg, exp.GroupConcat, exp.Stddev, exp.Variance)


# ============================================================================
# 轴 1：Spider 结构复杂度
# ============================================================================
def _tables_in_from(node: exp.Expression) -> int:
    """FROM 里的表单元数（等价 `len(sql['from']['table_units'])`）。

    子查询也算一个 table unit（上游同样如此）。

    ⚠️ sqlglot 把 FROM 存在键 **`from_`**（带下划线）上 —— 取 `args["from"]`
    会静默拿到 None，导致 JOIN 计数**全部为 0**（本判定器初版的真实 bug，
    用"三表 JOIN 应为 hard"这条上游锚点测出来的）。故两个键都试。
    """
    frm = node.args.get("from_") or node.args.get("from")
    if frm is None:
        return 0
    n = 1 if frm.this is not None else 0
    for _ in (node.args.get("joins") or []):
        n += 1
    return n


def _all_from_nodes(root: exp.Expression) -> list[exp.Expression]:
    """跨所有分支收集顶层 select 节点（含 UNION 各分支）。"""
    if isinstance(root, exp.SetOperation):
        return _all_from_nodes(root.left) + _all_from_nodes(root.right)
    return [root]


def _select_nodes(root: exp.Expression) -> list[exp.Select]:
    return list(root.find_all(exp.Select))


def count_component1(root: exp.Expression) -> tuple[int, int, dict]:
    """返回 (comp1_按上游代码, comp1_按站点标签口径, 明细)。

    ⚠️ **两种口径的差别只在 JOIN 一项**（详见文件头 U-29/U-30 说明）：
      · 上游代码：`count += len(table_units) - 1`（"多余表数"）
      · 站点标签：JOIN 只算 1 个组件（否则官方 Hard 示例会算成 extra）
    两套都算出来，下游可按裁定切换；`difficulty_struct` 默认取**上游代码**口径。
    """
    base = 0
    tops = _all_from_nodes(root)
    any_where = any(t.args.get("where") is not None for t in tops)
    any_group = any(t.args.get("group") is not None for t in tops)
    any_order = any(t.args.get("order") is not None for t in tops)
    any_limit = any(t.args.get("limit") is not None for t in tops)

    if any_where:
        base += 1
    if any_group:
        base += 1
    if any_order:
        base += 1
    if any_limit:
        base += 1

    # JOIN 的两种口径
    join_extra = 0
    for t in tops:
        n = _tables_in_from(t)
        if n > 0:
            join_extra += n - 1
    join_bool = 1 if join_extra > 0 else 0

    # OR 计数：WHERE / HAVING / JOIN ON 中的 or 出现次数
    n_or = sum(1 for _ in root.find_all(exp.Or))
    # LIKE 条件个数
    n_like = sum(1 for _ in root.find_all(exp.Like)) + sum(1 for _ in root.find_all(exp.ILike))

    tail = n_or + n_like
    detail = {"base": base, "join_extra": join_extra, "or": n_or, "like": n_like}
    return base + join_extra + tail, base + join_bool + tail, detail


def count_component2(root: exp.Expression) -> int:
    """nested SQL 数 = 除最外层之外的所有 SELECT 数。

    覆盖：子查询 / 派生表 / CTE 主体 / UNION|EXCEPT|INTERSECT 的分支
    —— 与上游 `get_nestedSQL` 的收集范围一致。
    """
    total = len(_select_nodes(root))
    return max(0, total - 1)


def count_component2_setops(root: exp.Expression) -> int:
    """仅供对照：集合运算节点数（UNION / EXCEPT / INTERSECT 的**额外分支**）。

    上游把它们一并算进 nested；本函数单独数一遍，方便架构窗口核对 U-29。
    """
    return sum(1 for _ in root.find_all(exp.SetOperation))


def _count_agg(nodes) -> int:
    c = 0
    for n in nodes:
        if n is None:
            continue
        for sub in ([n] if isinstance(n, exp.Expression) else n):
            if isinstance(sub, AGG_TYPES):
                c += 1
            else:
                c += sum(1 for a in sub.find_all(*AGG_TYPES))
    return c


def count_others(root: exp.Expression) -> tuple[int, dict]:
    """返回 (others, 明细)。others = 4 类中满足"多"的类数（0–4）。"""
    top = _all_from_nodes(root)[0]
    detail = {}

    # ① 聚合函数总数（select / where / group by / order by / having）> 1 → +1
    #    ⚠️ 只取**本层子句**（不 find_all），否则子查询里的聚合会被重复计入 ——
    #       上游 sql dict 是逐层的，子查询的聚合在其自身层单独统计。
    agg = _count_agg([top.args.get("expressions")])
    agg += _count_agg([top.args.get("where")])
    agg += _count_agg([(top.args.get("group") or exp.Group()).args.get("expressions")])
    agg += _count_agg([(top.args.get("order") or exp.Order()).args.get("expressions")])
    agg += _count_agg([top.args.get("having")])
    detail["agg_count"] = agg
    count = 1 if agg > 1 else 0

    # ② SELECT 列数 > 1 → +1
    n_sel = len(top.args.get("expressions") or [])
    detail["select_cols"] = n_sel
    if n_sel > 1:
        count += 1

    # ③ WHERE 条件单元数 > 1 → +1（扁平化 AND/OR，与上游 where 列表语义一致）
    n_where = 0
    for w in top.find_all(exp.Where):
        n_where += _leaf_conditions(w.this)
    detail["where_conds"] = n_where
    if n_where > 1:
        count += 1

    # ④ GROUP BY 列数 > 1 → +1
    g = top.args.get("group")
    n_group = len(g.expressions) if g is not None else 0
    detail["group_cols"] = n_group
    if n_group > 1:
        count += 1

    return count, detail


def _leaf_conditions(node: exp.Expression) -> int:
    """把 AND/OR 树拍平成"条件单元"个数（叶子条件数）。"""
    if node is None:
        return 0
    if isinstance(node, (exp.And, exp.Or)):
        return _leaf_conditions(node.this) + _leaf_conditions(node.expression)
    if isinstance(node, exp.Paren):
        return _leaf_conditions(node.this)
    return 1


def spider_level(comp1: int, comp2: int, others: int) -> str:
    """上游 `Evaluator.eval_hardness` 原样。"""
    if comp1 <= 1 and others == 0 and comp2 == 0:
        return "easy"
    if (others <= 2 and comp1 <= 1 and comp2 == 0) or \
       (comp1 <= 2 and others < 2 and comp2 == 0):
        return "medium"
    if (others > 2 and comp1 <= 2 and comp2 == 0) or \
       (2 < comp1 <= 3 and others <= 2 and comp2 == 0) or \
       (comp1 <= 1 and others == 0 and comp2 <= 1):
        return "hard"
    return "extra"


def classify_struct(sql: str) -> dict:
    root = sqlglot.parse_one(sql, read=DIALECT)
    c1, c1_site, c1_detail = count_component1(root)
    c2 = count_component2(root)
    others, detail = count_others(root)
    return {
        "comp1": c1,                            # 上游代码口径（JOIN = 表数-1）
        "comp1_sitelabel": c1_site,             # 站点标签口径（JOIN = 1）
        "comp1_detail": c1_detail,
        "comp2_nested": c2,                     # 上游真实口径：nested SQL 数
        "comp2_setops": count_component2_setops(root),
        "others": others,
        "others_detail": detail,
        # ★ 主口径 = **上游代码**（07 §4.7.2 裁定为唯一主口径；可复现、可逐行核对）
        "difficulty_struct": spider_level(c1, c2, others),
        # ⚠️ **仅对照字段**（07 §4.7.2）：禁止进分层统计 / 门禁判定 / 报告 headline。
        #    唯一用途 = 记录"我们与站点标签差在哪"。见本文件头 U-30。
        "difficulty_struct_sitelabel": spider_level(c1_site, c2, others),
    }


# ============================================================================
# 轴 2：业务语义复杂度（附录 C §C.3.3）
# ============================================================================
def _tags(bk: list[str]) -> list[str]:
    return [t.split(":", 1)[0] for t in (bk or [])]


def classify_semantic(business_knowledge_required: list[str] | None) -> str:
    tags = _tags(business_knowledge_required)
    if not tags:
        return "low"
    if any(t in SEM_B for t in tags):
        return "high"
    if len(tags) >= 2:
        return "high"
    if tags[0] in SEM_A:
        return "medium"
    # 未知标签：不静默当"低"，抛错迫使登记
    raise ValueError(f"未知的知识标签 {tags}，please 登记后再用（不得静默降级）")


# ============================================================================
# 用例批处理
# ============================================================================
def annotate_case(case: dict) -> dict:
    out = dict(case)
    sql = case.get("gold_sql")
    if sql:
        out.update(classify_struct(sql))
    else:
        for k in ("comp1", "comp1_sitelabel", "comp1_detail", "comp2_nested", "comp2_setops",
                  "others", "others_detail", "difficulty_struct", "difficulty_struct_sitelabel"):
            out[k] = None
    out["difficulty_semantic"] = classify_semantic(case.get("business_knowledge_required"))
    return out


# ---- 官方四级锚点（SQL 逐字取自 _refs/spider_examples.png 实读）----
# ⚠️ 07 §4.7.2 裁定：**降级为"差异记录"，不作为门禁**（Hard 一条在采纳口径下必然不符）。
OFFICIAL_ANCHORS: list[tuple[str, str, str]] = [
    ("Easy",
     "SELECT COUNT(*) FROM cars_data WHERE cylinders > 4", "easy"),
    ("Medium",
     "SELECT T2.name, COUNT(*) FROM concert AS T1 JOIN stadium AS T2 "
     "ON T1.stadium_id = T2.stadium_id GROUP BY T1.stadium_id", "medium"),
    ("Hard",
     "SELECT T1.country_name FROM countries AS T1 JOIN continents AS T2 "
     "ON T1.continent = T2.cont_id JOIN car_makers AS T3 ON T1.country_id = T3.country "
     "WHERE T2.continent = 'Europe' GROUP BY T1.country_name HAVING COUNT(*) >= 3", "hard"),
    ("Extra Hard",
     "SELECT AVG(life_expectancy) FROM country WHERE name NOT IN "
     "(SELECT T1.name FROM country AS T1 JOIN country_language AS T2 "
     "ON T1.code = T2.country_code WHERE T2.language = 'English' AND T2.is_official = 'T')",
     "extra"),
]

# ---- 本项目锚点（07 §4.7.2 裁定"**新立**"，CI 必须 100% 命中）----
#   判据 = 「**采纳口径下的真实边界**」，不是"我们希望它是什么"。
#   每条都注明**它为什么落在该级**（comp1 / comp2 / others 各由什么构成）——
#   这样断言一旦失效，能一眼看出是**哪一根计数**变了，而不是只看到一个 FAIL。
#   SQL 全部只用本项目的资产名（v_order_paid / v_product / v_shop），
#   故它同时是"本项目口径"的锚点，而不是又一份 Spider 示例的转述。
PROJECT_ANCHORS: list[tuple[str, str, str, str]] = [
    ("P1-easy",
     "SELECT COUNT(*) FROM v_order_paid WHERE pay_status = 'paid'",
     "easy",
     "comp1=1(WHERE) comp2=0 others=0 → 命中第 1 条（三项全成立）"),
    ("P2-medium",
     "SELECT p.category_l1, SUM(o.pay_amount) FROM v_order_paid o "
     "JOIN v_product p ON o.sku_id = p.sku_id GROUP BY p.category_l1",
     "medium",
     "comp1=2(JOIN+1, GROUP BY+1) others=1(SELECT 列数>1) → 命中『comp1<=2 且 others<2』"),
    ("P3-hard-a",
     "SELECT p.category_l1, SUM(o.pay_amount) FROM v_order_paid o "
     "JOIN v_product p ON o.sku_id = p.sku_id GROUP BY p.category_l1 ORDER BY 2 DESC",
     "hard",
     "comp1=3(JOIN+1, GROUP BY+1, ORDER BY+1) others=1 → 命中『2<comp1<=3 且 others<=2』"),
    ("P3-hard-b",
     "SELECT category_l1, SUM(pay_amount), AVG(pay_amount) FROM v_order_paid "
     "WHERE pay_status = 'paid' AND is_test_order = false "
     "GROUP BY category_l1, region_code",
     "hard",
     "comp1=2(WHERE+1, GROUP BY+1) others=4(聚合>1, 列>1, 条件单元>1, 分组列>1) → 命中『others>2 且 comp1<=2』"),
    ("P4-extra-a",
     "SELECT AVG(pay_amount) FROM v_order_paid WHERE shop_id NOT IN "
     "(SELECT shop_id FROM v_shop WHERE city = '广州')",
     "extra",
     "comp2=1(子查询计入) 且 others=1 → 三条 hard 子句**全不满足**（含『others==0』那一支）"),
    ("P4-extra-b",
     "SELECT s.shop_name, COUNT(*) FROM v_order_paid o "
     "JOIN v_product p ON o.sku_id = p.sku_id JOIN v_shop s ON o.shop_id = s.shop_id "
     "WHERE o.pay_status = 'paid' GROUP BY s.shop_name",
     "extra",
     "comp1=4(JOIN 2 表→+2, WHERE+1, GROUP BY+1) → 三条 hard 子句全不满足。**这一条同时是 U-30 的核心证据**"),
]

# ---- 分歧点（**裁定描述** vs **采纳口径**），故意保留在锚点里 ----
#   07 §4.7.2 锚点③ 的括号注写「3 表 JOIN + WHERE + GROUP BY（comp1=4）→ hard」。
#   但按同一节定为**唯一主口径**的上游代码实算：comp1 = 4 → **extra**
#   （这正是 U-30 的结论本身：官方 Hard 示例 comp1=4 → extra）。
#   → 保留这条 SQL 的用途有两个：
#     ① 它是"描述与口径不一致"的**物证**（与 U-35 同族，需回填 07/附录 C）；
#     ② 若哪天它真的变成 hard，说明有人**偷偷改了 `spider_level`** ——
#        那必须先改 07 §4.7.2 与 §17.6 I-1，而不是改代码。
DIVERGENCE_SQL = PROJECT_ANCHORS[-1][1]
DIVERGENCE_CLAIMED = "hard"   # 07 §4.7.2 锚点③ 的描述
DIVERGENCE_ACTUAL = "extra"   # 采纳口径的实测结果


def run_anchors() -> bool:
    """打印两组锚点。**返回值 = 本项目锚点是否 100% 命中**（即 CI 门禁的口径）。

    官方锚点**只打印、不参与返回值** —— 07 §4.7.2 已把它降级为差异记录；
    若还用它当门禁，Hard 那条会永远红，门禁就会被人为放宽（护栏失效的经典路径）。
    """
    print("=" * 104)
    print("锚点回归 · 第 1 组：官方 4 条 —— **差异记录，不参与门禁**（07 §4.7.2）")
    hdr = (f"{'等级':12s}{'comp1':>7s}{'comp1_site':>12s}{'comp2':>7s}{'others':>8s}"
           f"{'主口径':>10s}{'对照口径':>12s}{'站点期望':>10s}")
    print(hdr)
    all_code, all_site = True, True
    for name, sql, exp in OFFICIAL_ANCHORS:
        r = classify_struct(sql)
        gc, gs = r["difficulty_struct"], r["difficulty_struct_sitelabel"]
        all_code &= (gc == exp)
        all_site &= (gs == exp)
        print(f"{name:12s}{r['comp1']:>7d}{r['comp1_sitelabel']:>12d}{r['comp2_nested']:>7d}"
              f"{r['others']:>8d}{gc:>10s}{gs:>12s}{exp:>10s}")
    print(f"  → 主口径（上游代码，唯一主口径）全对：{'是' if all_code else '否 ← U-30 的暴露点（已登记为差异，不再视为缺陷）'}")
    print(f"  → 对照口径（站点标签，**禁进报告/统计**）全对：{'是' if all_site else '否'}")

    print()
    print("=" * 104)
    print("锚点回归 · 第 2 组：**本项目锚点** —— CI 门禁，必须 100% 命中（07 §4.7.2 新立）")
    print(f"{'锚点':14s}{'comp1':>7s}{'comp2':>7s}{'others':>8s}{'判定':>8s}{'期望':>8s}{'':4s}判据")
    ok = True
    for name, sql, exp, why in PROJECT_ANCHORS:
        r = classify_struct(sql)
        got = r["difficulty_struct"]
        hit = got == exp
        ok &= hit
        print(f"{name:14s}{r['comp1']:>7d}{r['comp2_nested']:>7d}{r['others']:>8d}"
              f"{got:>8s}{exp:>8s}{'  OK  ' if hit else ' FAIL ':>6s}{why}")
    print()
    d = classify_struct(DIVERGENCE_SQL)
    print("分歧点（**裁定描述 vs 采纳口径**，故意保留）：")
    print(f"  07 §4.7.2 锚点③ 称该形状（3 表 JOIN + WHERE + GROUP BY，comp1={d['comp1']}）为 "
          f"**{DIVERGENCE_CLAIMED}**；采纳口径实算 = **{d['difficulty_struct']}**")
    print(f"  → 若此处突然变成 {DIVERGENCE_CLAIMED}，说明 `spider_level` 被改了 —— "
          f"那必须先改 07 §4.7.2 与 §17.6 I-1，**不是改这个函数**")
    print()
    print(f"本项目锚点 100% 命中：{'是' if ok else '否 —— 门禁不通过'}")
    return ok


def grid(cases: list[dict]) -> tuple[dict, list[str]]:
    """返回 (4×3 计数, 警告列表)。只统计有 gold_sql 的用例。"""
    levels = ["easy", "medium", "hard", "extra"]
    sems = ["low", "medium", "high"]
    g = {a: {b: 0 for b in sems} for a in levels}
    warns = []
    for c in cases:
        a, b = c.get("difficulty_struct"), c.get("difficulty_semantic")
        if a is None:
            continue
        if a not in g or b not in sems:
            warns.append(f"{c.get('case_id')}: 非法分层 struct={a} semantic={b}")
            continue
        g[a][b] += 1
    for a in levels:
        for b in sems:
            if g[a][b] < 8:
                warns.append(f"网格 [{a} × {b}] = {g[a][b]} 条，**低于 DoD③ 要求的 8 条**")
    return g, warns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="4×3 分层判定器")
    ap.add_argument("--in", dest="src", help="输入用例集 JSON")
    ap.add_argument("--out", dest="dst", help="输出 JSON（省略则只打印）")
    ap.add_argument("--sql", help="只判定一条 SQL 并打印")
    ap.add_argument("--grid", action="store_true", help="打印 4×3 网格计数")
    ap.add_argument("--anchors", action="store_true",
                    help="锚点回归：官方 4 条（差异记录）+ **本项目 4 条（CI 门禁）**；退出码 = 后者是否 100% 命中")
    args = ap.parse_args(argv)

    if args.anchors:
        # 退出码 = **本项目锚点**是否 100% 命中（官方锚点不参与，见 run_anchors 的 docstring）
        return 0 if run_anchors() else 1

    if args.sql:
        print(json.dumps(classify_struct(args.sql), ensure_ascii=False, indent=2))
        return 0

    if not args.src:
        ap.print_help()
        return 2

    data = json.load(open(args.src, encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    before = {(c.get("case_id")): (c.get("difficulty_struct"), c.get("difficulty_semantic"))
              for c in cases}
    cases = [annotate_case(c) for c in cases]

    # 断言：既有手写标注与机器判定一致（防止"看起来对"）
    drift = []
    for c in cases:
        b = before.get(c.get("case_id"))
        if b and b[0] is not None and (b[0] != c["difficulty_struct"] or b[1] != c["difficulty_semantic"]):
            drift.append(f"{c['case_id']}: 手写={b} 机器=({c['difficulty_struct']},{c['difficulty_semantic']})")

    if isinstance(data, dict):
        data["cases"] = cases
    else:
        data = cases

    if args.grid:
        g, warns = grid(cases)
        print("4×3 网格（结构 × 语义）：")
        print(f"{'':10s}" + "".join(f"{s:>10s}" for s in ("low", "medium", "high")) + f"{'行合计':>10s}")
        for lv in ("easy", "medium", "hard", "extra"):
            print(f"{lv:10s}" + "".join(f"{g[lv][s]:>10d}" for s in ("low", "medium", "high"))
                  + f"{sum(g[lv].values()):>10d}")
        print(f"{'列合计':10s}" + "".join(f"{sum(g[l][s] for l in g):>10d}" for s in ("low", "medium", "high")))
        for w in warns:
            print("  [WARN]", w, file=sys.stderr)

    if drift:
        for d in drift:
            print("  [DRIFT]", d, file=sys.stderr)

    if args.dst:
        json.dump(data, open(args.dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"written {args.dst}  cases={len(cases)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
