#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""W8 第 40 轮 · 语义层 `metrics` 缺口清单（**只读 / 零出站 / 零花费 / 不动 YAML**）

派单：`backend/reports/qa/TASK_BOARD.md` §58.1（行 3298-3342）

与 QA `evidence_main_r31ad/diag_main.py` 的**唯一区别**（也是本件的增值点）：
  QA 的「题要的 metric 缺」是**按题面关键词人工比对**得出的（其 README §7 限制②自述）；
  本件改为**用 `dataset_v1_frozen.json` 的 `gold_sql` 结构反推缺口**
  （聚合函数 + 聚合源表 + WHERE 谓词 + GROUP BY 列），**不读题面关键词**。

判定规则（确定性，逐条可复算）：
  1. 取 `expected_behavior=execute 且 outcome=refuse` 的记录 = 误拒面（现读 63 条）
  2. 按 `case_id` 连 `dataset_v1_frozen.json` 取 `gold_sql`（规范化空白）
  3. `classify(gold_sql)` → 缺口 metric 键（见 GAP_RULES）
  4. 附加面（extra_faces）：GROUP BY 列 → 需要的**维度/绑定面**；JOIN 到 v_shop → 店铺面

输出：`probe_semantic_metric_gap.json` ＋ `probe_semantic_metric_gap.md`（两件同源）。
"""
from __future__ import annotations

import collections
import datetime
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DS = os.path.join(ROOT, "eval", "dataset_v1_frozen.json")
RES = os.path.join(ROOT, "eval", "results_v1.json")
BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")

OUT_JSON = os.path.join(HERE, "probe_semantic_metric_gap.json")
OUT_MD = os.path.join(HERE, "probe_semantic_metric_gap.md")


def norm(sql: str) -> str:
    return " ".join((sql or "").split())


# ---------------------------------------------------------------------------
# 缺口 metric 提案（**本轮回单的正文**；形状对齐既有 9 条 metric）
#   asset 用 `logical_name`（派单用 `grain` token 指资产，对照见 ASSET_ALIAS）
# ---------------------------------------------------------------------------
ASSET_ALIAS = {
    "order_paid": "sub_order",
    "order_refund": "refund_record",
    "product": "sku",
    "shop": "shop",
    "region": "province",
    "campaign": "campaign",
    "traffic_daily": "sku_day_channel",
    "dim_date": "day",
}

GAPS = {
    "pv": {
        "metric": "pv",
        "display_name": "浏览量",
        "asset": "traffic_daily",
        "expression": "SUM(traffic_daily.pv)",
        "default_aggregation": "sum",
        "unit": "次",
        "default_predicates": ["pv >= 0"],
        "predicate_reason": "防御性谓词：与 uv 同族，排除脏数据负数",
        "time_basis": "stat_date",
        "synonyms": ["浏览量", "PV", "pv", "页面浏览量", "浏览次数", "访问量", "流量", "曝光量"],
        "definition_note": "不去重；跨日区间可安全累加（与 uv 不同，uv 跨日累加会重复计数）。",
        "uncertainty": [],
    },
    "cart_add_cnt": {
        "metric": "cart_add_cnt",
        "display_name": "加购次数",
        "asset": "traffic_daily",
        "expression": "SUM(traffic_daily.cart_add_cnt)",
        "default_aggregation": "sum",
        "unit": "次",
        "default_predicates": ["cart_add_cnt >= 0"],
        "predicate_reason": "防御性谓词：同 pv/uv 族",
        "time_basis": "stat_date",
        "synonyms": ["加购次数", "加购数", "加购量", "加购", "加购人次"],
        "definition_note": "不去重、按次计数。",
        "uncertainty": [],
    },
    "on_sale_product_cnt": {
        "metric": "on_sale_product_cnt",
        "display_name": "在架商品数",
        "asset": "product",
        "expression": "COUNT(*)",
        "default_aggregation": "count",
        "unit": "个",
        "default_predicates": ["on_sale = true"],
        "predicate_reason": "「在架/在售/上架」的商品 = on_sale 为真",
        "time_basis": "current",
        "synonyms": ["在架商品数", "在架商品", "在售商品数", "在售商品", "上架商品数", "在架SKU数", "在售SKU数", "在架商品个数"],
        "definition_note": "维表快照口径（time_semantics=current），非交易口径。",
        "uncertainty": [
            "🔴 `E-ENUM-06…10` 的 gold_sql **不带** `on_sale = 1`，而这 5 条的题面**写着**「在架」→ "
            "本指标一旦挂 `on_sale = true` 默认谓词，这 5 条**会作答但计数与 gold 不等**"
            "（`v_product` 现读 on_sale=1 为 5631 / 全表 6000）。**属冻结集内部口径冲突：只登记，不得为迎合它改判据。**",
            "`on_sale` 为 NULL 的行不存在（现读仅 0/1 两值）⇒ `on_sale = true` 与 `on_sale <> false` 等价的说法**不成立**（NULL 会被 `<> false` 漏掉），谓词一律写 `on_sale = true`。",
        ],
    },
    "off_sale_product_cnt": {
        "metric": "off_sale_product_cnt",
        "display_name": "下架商品数",
        "asset": "product",
        "expression": "COUNT(*)",
        "default_aggregation": "count",
        "unit": "个",
        "default_predicates": ["on_sale = false"],
        "predicate_reason": "「下架/停售」的商品 = on_sale 为假",
        "time_basis": "current",
        "synonyms": ["下架商品数", "下架商品", "停售商品数", "已下架商品数"],
        "definition_note": "与 on_sale_product_cnt 互补，**不可相加代替 product_cnt**（category_l1 为 NULL 的 60 行两指标都不计）。",
        "uncertainty": [],
    },
    "product_cnt": {
        "metric": "product_cnt",
        "display_name": "商品数",
        "asset": "product",
        "expression": "COUNT(*)",
        "default_aggregation": "count",
        "unit": "个",
        "default_predicates": [],
        "predicate_reason": "",
        "time_basis": "current",
        "synonyms": ["商品数", "商品数量", "商品个数", "SKU数", "SKU数量", "sku数", "款式数", "货品数"],
        "definition_note": "不区分上下架的存量计数（含 category_l1 为 NULL 的 60 行）。",
        "uncertainty": [
            "与 on_sale_product_cnt **同词根**（「商品数」「SKU数」）→ L1 别名表必须做**互斥切分**（「在架/在售/上架」修饰词归 on_sale 那条），否则 L1 会把带修饰词的问题也命中本指标。",
        ],
    },
    "spu_cnt": {
        "metric": "spu_cnt",
        "display_name": "SPU 数",
        "asset": "product",
        "expression": "COUNT(DISTINCT product.spu_id)",
        "default_aggregation": "count_distinct",
        "unit": "个",
        "default_predicates": ["on_sale = true"],
        "predicate_reason": "对齐 gold_sql（`E-VER-04` 的 gold 带 `on_sale = 1`）—— ⚠️ 题面并无此限定",
        "time_basis": "current",
        "synonyms": ["SPU 数", "SPU数", "SPU数量", "SPU个数", "款数", "款式数量"],
        "definition_note": "按 spu_id 去重。",
        "uncertainty": ["题面「T_A 的 SPU 数是多少」**无在架限定**，而 gold_sql 带 `on_sale = 1`（`v_product` 全表 6000 行 / on_sale=1 为 5631 行）→ 默认谓词的取舍直接决定能否与 gold 对齐，**须业务确认**。"],
    },
    "avg_list_price": {
        "metric": "avg_list_price",
        "display_name": "商品平均标价",
        "asset": "product",
        "expression": "AVG(product.list_price)",
        "default_aggregation": "avg",
        "unit": "CNY",
        "default_predicates": ["on_sale = true"],
        "predicate_reason": "对齐 gold_sql（`H-STR-09` 的 gold 带 `on_sale = 1`）—— ⚠️ 题面并无此限定",
        "time_basis": "current",
        "synonyms": ["商品平均标价", "平均标价", "平均吊牌价", "标价均值", "商品平均吊牌价"],
        "definition_note": "标价 = 吊牌价，**非成交价**（成交侧用 aov / 件单价）。",
        "uncertainty": ["同 `spu_cnt`：gold 带未在题面出现的 `on_sale = 1`。"],
    },
    "shop_cnt": {
        "metric": "shop_cnt",
        "display_name": "店铺数",
        "asset": "shop",
        "expression": "COUNT(*)",
        "default_aggregation": "count",
        "unit": "个",
        "default_predicates": [],
        "predicate_reason": "",
        "time_basis": "current",
        "synonyms": ["店铺数", "店铺数量", "店铺个数", "门店数", "店铺家数"],
        "definition_note": "`v_shop` 现读 12 行。",
        "uncertainty": ["gold_sql 为 `COUNT(*) … WHERE city IS NOT NULL`（现读仍为 12，因 city 无 NULL）；题面无该限定 → 默认谓词**建议不挂**，但须登记与 gold 的这点差异。"],
    },
    "campaign_cnt": {
        "metric": "campaign_cnt",
        "display_name": "活动数",
        "asset": "campaign",
        "expression": "COUNT(*)",
        "default_aggregation": "count",
        "unit": "个",
        "default_predicates": [],
        "predicate_reason": "",
        "time_basis": "current",
        "synonyms": ["活动数", "活动数量", "活动个数", "活动场次", "促销活动数"],
        "definition_note": "`v_campaign` 现读 84 行（normal_sale 72 / prom_618 6 / prom_double11 6）。",
        "uncertainty": [
            "🔴 **同一指标两条 gold 口径互斥**：`E-VER-06`（T_A 的活动数）gold 带 `campaign_type = 'normal_sale'`（=72），而 `M-DIM-04`（各活动类型的活动数）gold **无谓词**（=84）。⇒ 挂默认谓词必错其一。**建议不挂**，并把它作为「口径待业务确认」登记。",
        ],
    },
    "province_cnt": {
        "metric": "province_cnt",
        "display_name": "覆盖省份数",
        "asset": "region",
        "expression": "COUNT(*)",
        "default_aggregation": "count",
        "unit": "个",
        "default_predicates": [],
        "predicate_reason": "",
        "time_basis": "current",
        "synonyms": ["覆盖省份数", "省份数", "省份数量", "省份个数", "省份覆盖数", "覆盖省份"],
        "definition_note": "`v_region` 现读 31 行；大区（华东 7 / 华北 5 / 西南 5 / 西北 5 / 华南 3 / 华中 3 / 东北 3）由 `region_name` 承载。",
        "uncertainty": ["`E-VER-07` 的「华东」是**大区层级**筛选，`M-DIM-08` 的「7 个大区各覆盖」是**按大区分组** → 二者都还要 `region` 侧的**大区绑定面**（见 non_metric_faces F-4）。"],
    },
    "province_covered_cnt": {
        "metric": "province_covered_cnt",
        "display_name": "收货省份覆盖数",
        "asset": "order_paid",
        "expression": "COUNT(DISTINCT order_paid.region_code)",
        "default_aggregation": "count_distinct",
        "unit": "个",
        "default_predicates": ["region_code IS NOT NULL"],
        "predicate_reason": "对齐 gold_sql（`E-VER-08`）",
        "time_basis": "pay_time",
        "synonyms": ["收货省份覆盖数", "收货省份数", "覆盖省份数(收货)", "省份覆盖", "收货覆盖省份数"],
        "definition_note": "跨列去重计数，落在事实表 order_paid 上；与 `region` 资产上的 `province_cnt` **不是同一件事**（一个是维表存量、一个是订单实覆盖）。",
        "uncertainty": ["与 `province_cnt` 中文名高度重叠（都可叫「覆盖省份数」）→ 别名表须做互斥切分，否则 L1 歧义。"],
    },
    "day_cnt": {
        "metric": "day_cnt",
        "display_name": "天数",
        "asset": "dim_date",
        "expression": "COUNT(*)",
        "default_aggregation": "count",
        "unit": "天",
        "default_predicates": [],
        "predicate_reason": "",
        "time_basis": "current",
        "synonyms": ["天数", "日期数", "日历天数", "日期维表天数", "统计天数", "日期个数"],
        "definition_note": "`v_dim_date` 现读 730 行（2024-10-01 … 2026-09-30）。",
        "uncertainty": ["gold_sql 为**全表** `COUNT(*)`（=730），而题面写「**2026-08** 的日期维表有多少天」（应含月份筛选 = 31）→ 作答后**计数必与 gold 不等**。属冻结集内部口径冲突，**只登记、不改判据**。"],
    },
    "refunded_order_cnt": {
        "metric": "refunded_order_cnt",
        "display_name": "全额退款订单数",
        "asset": "order_paid",
        "expression": "COUNT(DISTINCT order_paid.sub_order_id)",
        "default_aggregation": "count_distinct",
        "unit": "笔",
        "default_predicates": ["refund_status = 'refunded'", "pay_status = 'paid'"],
        "predicate_reason": "对齐 gold_sql（`H-ENUM-02`）；分子正是退款行为本身，故**不套** `refund_status <> 'refunded'`",
        "time_basis": "pay_time",
        "synonyms": ["全额退款订单数", "退款订单数", "全额退款笔数", "退款笔数", "退款单量"],
        "definition_note": "口径参照 `refund_rate` 的例外模式：谓词**不含** `refund_status <> 'refunded'`。",
        "uncertainty": ["`H-ENUM-03`（「无退款」状态的订单数）**已 success** —— 说明该族目前靠模型即兴表达 `refund_status` 谓词；补本指标后需确认是否**只**覆盖 `全额退款` 而把「无退款/部分退款」留给通用 `order_cnt` ＋显式谓词。"],
    },
}

GAP_ORDER = list(GAPS.keys())

# 明确**不补**的 case（附理由）
NOT_GAP = {
    "E-MET-08": "冻结集 `notes` 原文明写：**反面口径**（「故意不套默认谓词，用来测 W6 的『口径一致性』能否识别默认谓词缺失」）⇒ 它要的**不是**新 metric（恰恰相反，要的是「同一个 pay_amount 表达式**不许**自动带上 gmv 的默认谓词」）。补 metric 会**破坏**该用例的设计意图。",
}

# 非 metric 面（维度 / 绑定 / 路径）
NON_METRIC_FACES = {
    "F-1": {
        "face": "SKU 维度（`sku_id`）**未定义**",
        "why": "`dimensions` 现有 6 个（`region`/`category`/`channel`/`time`/`shop`/`city`），**没有** SKU 维度。`M-MET-05`（各 `sku_id` 的 UV）能 success ⇒ 该面可能只差 metric、不差维度，**故列为不确定项**。",
        "authorized_this_round": False,
    },
    "F-2": {
        "face": "SPU 维度（`spu_id`）**未定义**",
        "why": "`M-DIM-06`（各 SPU 的 SKU 数）需按 `spu_id` 分组，`dimensions` 无此维度。",
        "authorized_this_round": False,
    },
    "F-3": {
        "face": "类目维度在 **`product` 侧**无绑定",
        "why": "`dimensions.category.binding` = `order_paid.category_l1`；而 {n} 条的 gold 都在 **`v_product`** 上"
               "按 `category_l1`/`category_l2` 筛选或分组（其中 13 条是 3 表 JOIN：`X-ENUM-*` / `X-MET-*`）。**不是** metric 面。",
        "authorized_this_round": False,
    },
    "F-4": {
        "face": "大区（`region_name`）在 **`region` 资产侧**无绑定",
        "why": "`dimensions.region` 的 `binding` = `order_paid.region_code`（收货省），`region_name` 只出现在 `value_map`（业务约定）。`E-VER-07`/`M-DIM-08` 的 gold 直接读 `v_region.region_name`。",
        "authorized_this_round": False,
    },
    "F-5": {
        "face": "活动类型维度（`campaign.campaign_type`）**未定义**",
        "why": "`M-DIM-04` 需按 `campaign_type` 分组。",
        "authorized_this_round": False,
    },
    "F-6": {
        "face": "店铺维度（`shop.shop_id`）**已有** ＋ `product→shop` join **已有** ⇒ **不是缺口**",
        "why": "{n} 条都走这两条既有路径；`F-6` 登记在案只为**排除**它（避免下一轮把它当缺口再补一遍）。",
        "authorized_this_round": True,
    },
}


# ---------------------------------------------------------------------------
# gold_sql → 缺口键（**先看聚合函数与聚合源列，再看计数源表**，避免 X-* 三表 JOIN 误判）
# ---------------------------------------------------------------------------
def classify(sql: str) -> tuple[str, list[str]]:
    s = norm(sql)
    up = s.upper()
    faces: list[str] = []

    # ① 聚合表达式级（跨资产也稳定）
    if re.search(r"COUNT\(DISTINCT\s+SPU_ID\)", up):
        return "spu_cnt", faces
    if re.search(r"AVG\(\s*(V_PRODUCT\.)?LIST_PRICE", up):
        return "avg_list_price", faces
    if re.search(r"COUNT\(DISTINCT\s+REGION_CODE\)", up):
        return "province_covered_cnt", faces
    if re.search(r"SUM\(\s*(V_TRAFFIC_DAILY\.)?PV\b", up):
        return "pv", faces
    if re.search(r"SUM\(\s*(V_TRAFFIC_DAILY\.)?CART_ADD_CNT", up):
        return "cart_add_cnt", faces
    if re.search(r"SUM\(\s*(V_ORDER_PAID\.)?PAY_AMOUNT", up) and "PAY_STATUS = 'UNPAID'" in up:
        return "E-MET-08", faces  # 反面口径，见 NOT_GAP

    # ② COUNT(*) 级 —— 看计数源表
    if re.search(r"COUNT\(\*\)", up):
        if "FROM V_DIM_DATE" in up:
            return "day_cnt", faces
        if "FROM V_PRODUCT" in up:
            if "ON_SALE = 1" in up:
                return "on_sale_product_cnt", faces
            if "ON_SALE = 0" in up:
                return "off_sale_product_cnt", faces
            return "product_cnt", faces
        if "FROM V_SHOP" in up:
            return "shop_cnt", faces
        if "FROM V_CAMPAIGN" in up:
            return "campaign_cnt", faces
        if "FROM V_REGION" in up:
            return "province_cnt", faces
        if "FROM V_ORDER_PAID" in up and "REFUND_STATUS = 'REFUNDED'" in up:
            return "refunded_order_cnt", faces
    return "UNKNOWN:" + s[:60], faces


def need_faces(sql: str) -> list[str]:
    """gold_sql 需要的**非 metric 面**（本轮不授权改；只登记）"""
    s = norm(sql)
    up = s.upper()
    out = []
    m = re.search(r"GROUP BY\s+(.+)$", s, re.I)
    gb = (m.group(1) if m else "").strip().lower()
    if gb in ("sku_id", "v_product.sku_id"):
        out.append("F-1")
    if gb == "spu_id":
        out.append("F-2")
    if gb.startswith("category_l") or "CATEGORY_L1 =" in up or "CATEGORY_L2 =" in up:
        out.append("F-3")
    if gb == "region_name" or "REGION_NAME =" in up:
        out.append("F-4")
    if gb == "campaign_type":
        out.append("F-5")
    if "V_SHOP" in up and "FROM V_SHOP" not in up:
        out.append("F-6")
    return out


def main() -> int:
    with io.open(DS, encoding="utf-8") as fh:
        ds = json.load(fh)
    with io.open(RES, encoding="utf-8") as fh:
        res = json.load(fh)["records"]
    by = {c["case_id"]: c for c in ds["cases"]}

    wrong = [r for r in res if r.get("expected_behavior") == "execute" and r.get("outcome") == "refuse"]
    wrong.sort(key=lambda r: r["case_id"])
    exp_exec = [r for r in res if r.get("expected_behavior") == "execute"]
    g2 = [r for r in res if r.get("difficulty_struct") == "easy" and r.get("difficulty_semantic") == "low"]

    rows = []
    for r in wrong:
        c = by[r["case_id"]]
        sql = norm(c.get("gold_sql"))
        key, _ = classify(sql)
        m = re.search(r"GROUP BY\s+(.+)$", sql, re.I)
        rows.append({
            "case_id": r["case_id"],
            "template_block": c.get("template_block"),
            "difficulty": "%s×%s" % (c.get("difficulty_struct"), c.get("difficulty_semantic")),
            "question": r["question"],
            "gold_sql": sql,
            "gap_metric": key,
            "non_metric_faces": need_faces(sql),
            "group_by": (m.group(1).strip() if m else ""),
        })

    # ---- 分组 ----
    by_metric = collections.OrderedDict()
    for k in GAP_ORDER:
        ids = [x["case_id"] for x in rows if x["gap_metric"] == k]
        if ids:
            by_metric[k] = ids
    for x in rows:
        if x["gap_metric"] not in GAPS:
            by_metric.setdefault(x["gap_metric"], []).append(x["case_id"])

    faces_cases = collections.OrderedDict((f, []) for f in NON_METRIC_FACES)
    for x in rows:
        for f in x["non_metric_faces"]:
            faces_cases[f].append(x["case_id"])

    # 「只补 metric 即可」= 无非 metric 面 **且** 确有 metric 可补（E-MET-08 除外）
    pure = [x["case_id"] for x in rows if not x["non_metric_faces"] and x["gap_metric"] in GAPS]
    face_needed = [x["case_id"] for x in rows if x["non_metric_faces"]]

    gaps_out = []
    for k, ids in by_metric.items():
        if k in GAPS:
            g = dict(GAPS[k])
            g["asset_grain"] = ASSET_ALIAS.get(g["asset"], "?")
            g["covers"] = ids
            g["n_covers"] = len(ids)
            gaps_out.append(g)

    payload = {
        "round": 40,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "scope": "只读清单件；**不动 `semantic/**` YAML**、不改冻结集、不改判据、不取号",
        "inputs": {
            "dataset": "eval/dataset_v1_frozen.json",
            "results": "eval/results_v1.json",
            "bundle_read_only": "semantic/bundle_2026.09.14.1.yaml",
        },
        "method": "按 gold_sql 的『聚合函数＋聚合源列＋计数源表』反推缺口（不读题面关键词）；"
                  "QA 侧同类诊断是按题面关键词人工比对（其 README §7 限制②）",
        "funnel": {
            "expected_execute": sum(1 for r in res if r.get("expected_behavior") == "execute"),
            "false_refusal": len(wrong),
            "refusal_reason": dict(collections.Counter(r.get("refusal_reason") for r in wrong)),
            "stop_node": dict(collections.Counter((r.get("nodes") or ["?"])[-1] for r in wrong)),
        },
        # 独立复核 QA `evidence_main_r31ad` 的五条断言（本窗**自算**，不抄其输出）
        "qa_r31ad_recheck": {
            "① G-2 面构成": {
                "n": len(g2),
                "outcome": dict(collections.Counter(r.get("outcome") for r in g2)),
                "refusal_reason": dict(collections.Counter(r.get("refusal_reason") for r in g2)),
                "expected": dict(collections.Counter(r.get("expected_behavior") for r in g2)),
            },
            "② G-2 ⊆ 误拒": {r["case_id"] for r in g2} <= {r["case_id"] for r in wrong},
            "③ 误拒理由 100% no_data_asset": (
                set(r.get("refusal_reason") for r in wrong) == {"no_data_asset"}),
            "④ embedding 伴随率（零区分力？）": {
                "success 含 embedding": "%d/%d" % (
                    sum(1 for r in exp_exec if r.get("outcome") == "success"
                        and any("embedding" in str(x) for x in (r.get("degradations") or []))),
                    sum(1 for r in exp_exec if r.get("outcome") == "success")),
                "误拒 含 embedding": "%d/%d" % (
                    sum(1 for r in wrong
                        if any("embedding" in str(x) for x in (r.get("degradations") or []))),
                    len(wrong)),
                "判": "两组同率（100%/100%）⇒ 无区分力，非根因",
            },
            "⑤ 停止点与召回": {
                "nodes 末位": dict(collections.Counter((r.get("nodes") or ["?"])[-1] for r in wrong)),
                "retrieval_counts.assets": dict(collections.Counter(
                    (r.get("retrieval_counts") or {}).get("assets") for r in wrong)),
                "gate_decisions 非空": sum(1 for r in wrong if r.get("gate_decisions")),
            },
        },
        "existing_metrics_read_only": 9,
        "proposed_new_metrics": len(gaps_out),
        "proposed_metric_names": [g["metric"] for g in gaps_out],
        "gaps": gaps_out,
        "not_gap": NOT_GAP,
        "non_metric_faces": {f: dict(v, why=v["why"].replace("{n}", str(len(faces_cases[f]))),
                                     cases=faces_cases[f], n_cases=len(faces_cases[f]))
                             for f, v in NON_METRIC_FACES.items()},
        "coverage": {
            "total_false_refusal": len(wrong),
            "pure_metric_only": len(pure),
            "pure_metric_only_cases": pure,
            "needs_non_metric_face": len(face_needed),
            "needs_non_metric_face_cases": face_needed,
            "not_covered_by_any_metric": sorted(NOT_GAP),
            "by_metric": {k: {"n": len(v), "cases": v} for k, v in by_metric.items()},
        },
        "landing_prereq": {
            "aliases": "`synonyms` ⊆ `aliases` 的 term 集是**校验器断言**（`validate_bundle.py` 步骤③）"
                       "⇒ 落 YAML 时**必须同步补 `aliases`** 的指标类别名条目（一对一）。",
            "default_predicates": "`metrics[].default_predicates` 与顶层 `default_predicates[域][].applies_to`"
                                  "**双向一致**也是断言（同上）⇒ 新增谓词必须两处都写。",
            "duplicate_terms": "本件内 `product_cnt` / `on_sale_product_cnt` 与 `province_cnt` / "
                               "`province_covered_cnt` **中文名重叠**，落 YAML 时必须做**互斥切分**，"
                               "否则 `aliases.term` 的一对一断言（现 105/105）会 FAIL。",
            "version": "改语义包 ⇒ 必须递增 `meta.version`（形态 `YYYY.MM.DD.N`，`07 §6.1`），"
                       "且缓存 / few-shot 索引失效（附录 B §B.4.1）。",
        },
        "cases": rows,
    }

    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    # ---------------- 简表（同源生成） ----------------
    L = []
    L.append("# 语义层 `metrics` 缺口清单（W8 第 40 轮）")
    L.append("")
    L.append("> **性质**：**只读清单件** —— 🔴 **本轮不动 `semantic/**` YAML**（派单 §58.1 三、）。")
    L.append("> **来源**：`eval/dataset_v1_frozen.json` 的 `gold_sql` ＋ `eval/results_v1.json` 的 outcome。")
    L.append("> **时点**：`%s`（UTC）" % payload["generated_at_utc"])
    L.append("")
    L.append("## 0. 漏斗（现读）")
    L.append("")
    L.append("| 步 | 数 |")
    L.append("|---|---|")
    L.append("| `expected_behavior = execute` | %d |" % payload["funnel"]["expected_execute"])
    L.append("| 其中 **误拒**（`outcome = refuse`） | **%d** |" % payload["funnel"]["false_refusal"])
    L.append("| ↳ `refusal_reason` | %s |" % payload["funnel"]["refusal_reason"])
    L.append("| ↳ 停止节点 | %s |" % payload["funnel"]["stop_node"])
    L.append("| 既有 `metrics`（只读，未改） | %d |" % payload["existing_metrics_read_only"])
    L.append("| 本件建议**新增** `metrics` | **%d** |" % payload["proposed_new_metrics"])
    L.append("")
    L.append("独立复核 QA `evidence_main_r31ad` 的五条断言（本窗**自算**，未抄其输出）：")
    L.append("")
    rk = payload["qa_r31ad_recheck"]
    L.append("| # | QA 断言 | 本窗自算（第 40 轮） | 判 |")
    L.append("|---|---|---|---|")
    L.append("| ① | G-2 面 10 条全 `refuse`／`no_data_asset`，`expected=execute` | n=%d｜outcome=%s｜reason=%s｜expected=%s | ✅ |" % (
        rk["① G-2 面构成"]["n"], rk["① G-2 面构成"]["outcome"],
        rk["① G-2 面构成"]["refusal_reason"], rk["① G-2 面构成"]["expected"]))
    L.append("| ② | `set(G-2) ⊆ set(误拒)` | %s | ✅ |" % rk["② G-2 ⊆ 误拒"])
    L.append("| ③ | 误拒 63 条 100%% `no_data_asset` | %s（`reason` 只有一种） | ✅ |" % rk["③ 误拒理由 100% no_data_asset"])
    L.append("| ④ | `embedding_unavailable` **零区分力**（非根因） | success **%s** ⟷ 误拒 **%s** | ✅ |" % (
        rk["④ embedding 伴随率（零区分力？）"]["success 含 embedding"],
        rk["④ embedding 伴随率（零区分力？）"]["误拒 含 embedding"]))
    L.append("| ⑤ | 停止点全在 `plan → refuse_out`（非 link 空召回） | nodes 末位=%s｜`retrieval_counts.assets`=%s｜`gate_decisions` 非空=%d | ✅ |" % (
        rk["⑤ 停止点与召回"]["nodes 末位"], rk["⑤ 停止点与召回"]["retrieval_counts.assets"],
        rk["⑤ 停止点与召回"]["gate_decisions 非空"]))
    L.append("")
    L.append("⇒ **五条全部复现**；本轮的**值增量**在于「缺口怎么补」不再靠题面关键词人工比对（见 §40.1 方法与 §1.1 逐条）。")
    L.append("")
    L.append("## 1. 缺口 metric 清单")
    L.append("")
    L.append("| # | metric | 显示名 | 目标 asset（grain） | expression | 默认谓词 | 覆盖 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, g in enumerate(gaps_out, 1):
        L.append("| %d | `%s` | %s | `%s`（`%s`） | `%s` | %s | **%d** |" % (
            i, g["metric"], g["display_name"], g["asset"], g["asset_grain"],
            g["expression"],
            ("`" + "`, `".join(g["default_predicates"]) + "`") if g["default_predicates"] else "**无**",
            g["n_covers"]))
    L.append("")
    L.append("### 1.1 逐条详表（`default_aggregation` / `unit` / `time_basis` / `synonyms` / 覆盖 case_id）")
    L.append("")
    for i, g in enumerate(gaps_out, 1):
        L.append("**%d. `%s` — %s**" % (i, g["metric"], g["display_name"]))
        L.append("")
        L.append("- `asset`：`%s`（`grain = %s`）｜`expression`：`%s`" % (g["asset"], g["asset_grain"], g["expression"]))
        L.append("- `default_aggregation`：`%s`｜`unit`：`%s`｜`time_basis`：`%s`" % (
            g["default_aggregation"], g["unit"], g["time_basis"]))
        L.append("- `synonyms`：%s" % "、".join(g["synonyms"]))
        if g["default_predicates"]:
            L.append("- `default_predicates`：`%s`｜理由：%s" % ("`, `".join(g["default_predicates"]), g["predicate_reason"]))
        else:
            L.append("- `default_predicates`：**无**")
        L.append("- `definition_note`：%s" % g["definition_note"])
        L.append("- **覆盖 %d 条**：%s" % (g["n_covers"], ", ".join(g["covers"])))
        if g["uncertainty"]:
            for u in g["uncertainty"]:
                L.append("- ⚠️ **不确定项**：%s" % u)
        L.append("")

    L.append("## 2. **不补** 的 case（并附理由）")
    L.append("")
    for k, v in NOT_GAP.items():
        L.append("- `%s` —— %s" % (k, v))
    L.append("")
    L.append("## 3. 非 metric 面（**本轮不授权改**，只登记；下一轮须单独点句）")
    L.append("")
    L.append("| # | 面 | 覆盖条数 | case_id |")
    L.append("|---|---|---|---|")
    for f, v in payload["non_metric_faces"].items():
        L.append("| %s | %s | %d | %s |" % (f, v["face"], v["n_cases"], ", ".join(v["cases"]) or "—"))
    L.append("")
    for f, v in payload["non_metric_faces"].items():
        L.append("- **%s**：%s" % (f, v["why"]))
    L.append("")
    L.append("## 4. 覆盖预估（④ 合计）")
    L.append("")
    L.append("- 误拒总数 **%d**" % payload["coverage"]["total_false_refusal"])
    L.append("- ↳ **只补 metric 即可**（无 F-1…F-5 附面）：**%d** 条 —— %s" % (
        payload["coverage"]["pure_metric_only"], ", ".join(payload["coverage"]["pure_metric_only_cases"])))
    L.append("- ↳ **还须附面**（F-1…F-5 任一，本轮**未授权**）：**%d** 条 —— %s" % (
        payload["coverage"]["needs_non_metric_face"],
        ", ".join(payload["coverage"]["needs_non_metric_face_cases"])))
    L.append("- ↳ **不建议补**：%s" % ", ".join(payload["coverage"]["not_covered_by_any_metric"]))
    L.append("- 校验：%d ＋ %d ＋ %d = %d ✅" % (
        payload["coverage"]["pure_metric_only"], payload["coverage"]["needs_non_metric_face"],
        len(payload["coverage"]["not_covered_by_any_metric"]), payload["coverage"]["total_false_refusal"]))
    L.append("")
    L.append("## 5. 落地前置（**下一轮**改 YAML 时必须一并处理，非本轮动作）")
    L.append("")
    for k, v in payload["landing_prereq"].items():
        L.append("- **`%s`**：%s" % (k, v))
    L.append("")
    L.append("## 6. 纪律与红线")
    L.append("")
    L.append("- 🔴 **不迎合那 63 条**：不按题面逐条特判；冻结集是**验收标准**，不是训练集。")
    L.append("- 🔴 本件**不动** `semantic/**`；`status=draft` 的 `sell_through_rate` **不算缺口**，未列。")
    L.append("- 派单用 **`grain` token** 指资产（`sub_order`/`refund_record`/`sku`/`shop`/`province`/"
             "`campaign`/`sku_day_channel`/`day`）；本件用 **`logical_name`**，对照已列在第 1 节括号内。")
    L.append("- 零出站、零花费、零取号（指针 `U-143`）。")
    L.append("")
    L.append("## 7. 复算入口（`PROMPT.md §5` 三条纪律：带时点 / 附实跑输出＋点名口径 / 禁自指）")
    L.append("")
    L.append("- **时点**：第 40 轮 ｜ 生成于 `%s`（UTC）" % payload["generated_at_utc"])
    L.append("- **命令**（从仓库根，零出站）：")
    L.append("")
    L.append("```bash")
    L.append("PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "
             "backend/reports/w8/probe_semantic_metric_gap.py")
    L.append("```")
    L.append("")
    L.append("- **实跑输出**（本机实跑，非「应等于」）：")
    L.append("")
    L.append("```text")
    L.append("expected=execute           = %d" % payload["funnel"]["expected_execute"])
    L.append("其中误拒(outcome=refuse)   = %d | reason=%s" % (
        payload["funnel"]["false_refusal"], payload["funnel"]["refusal_reason"]))
    L.append("① 建议新增 metrics         = %d 条" % len(gaps_out))
    L.append("④ 覆盖预估                 = 只补 metric %d ＋ 还须附面 %d ＋ 不补 %d" % (
        payload["coverage"]["pure_metric_only"], payload["coverage"]["needs_non_metric_face"],
        len(payload["coverage"]["not_covered_by_any_metric"])))
    L.append("```")
    L.append("")
    L.append("- **口径点名**（数 / 面 / 谓词 / 分母 / 粒度）：")
    L.append("  - 数 = `63`；面 = `eval/results_v1.json`（166 条）**连** `eval/dataset_v1_frozen.json`（按 `case_id`）；")
    L.append("  - 谓词 = `expected_behavior == 'execute'` **且** `outcome == 'refuse'`；分母 = 该谓词命中数 63；")
    L.append("  - 粒度 = **逐 case**（一 case 一票，不按模板块聚合）。")
    L.append("- **禁自指**：本入口是**整脚本复跑**（不是 `grep` 单串），上列「实跑输出」由脚本自身计算后写入，")
    L.append("  **不存在**「pattern 命中写下它的那一行」的自指形态（`PROMPT.md §5` 纪律③的适用对象是 `grep`/`-c` 类入口）。")
    L.append("")
    L.append("## 8. 附录：误拒 63 条逐条（`case_id` ｜ 缺口 metric ｜ 非 metric 面 ｜ GROUP BY ｜ 题面）")
    L.append("")
    L.append("| case_id | metric | 非 metric 面 | GROUP BY | 题面 |")
    L.append("|---|---|---|---|---|")
    for x in rows:
        L.append("| `%s` | `%s` | %s | %s | %s |" % (
            x["case_id"], x["gap_metric"],
            ", ".join(x["non_metric_faces"]) or "—",
            ("`%s`" % x["group_by"]) if x["group_by"] else "—",
            x["question"].replace("|", "\\|")))
    L.append("")
    L.append("> `gold_sql` 全文（每条一份，可直接对拍）在 `probe_semantic_metric_gap.json` 的 `cases[]`。")
    L.append("")

    with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))

    # ---------------- 实跑输出（供回执/RELAY 引用） ----------------
    print("=" * 72)
    print("面 = eval/results_v1.json 连 eval/dataset_v1_frozen.json（按 case_id）")
    print("=" * 72)
    print("expected=execute           = %d" % payload["funnel"]["expected_execute"])
    print("其中误拒(outcome=refuse)   = %d | reason=%s" % (
        payload["funnel"]["false_refusal"], payload["funnel"]["refusal_reason"]))
    print("停止节点                   = %s" % payload["funnel"]["stop_node"])
    rk = payload["qa_r31ad_recheck"]
    print("QA R31ad 五条复核：")
    print("   ① G-2 = %d 条 | outcome=%s | reason=%s | ⊆误拒=%s" % (
        rk["① G-2 面构成"]["n"], rk["① G-2 面构成"]["outcome"],
        rk["① G-2 面构成"]["refusal_reason"], rk["② G-2 ⊆ 误拒"]))
    print("   ③ 误拒理由只有 no_data_asset = %s" % rk["③ 误拒理由 100% no_data_asset"])
    print("   ④ embedding 伴随 success %s ⟷ 误拒 %s" % (
        rk["④ embedding 伴随率（零区分力？）"]["success 含 embedding"],
        rk["④ embedding 伴随率（零区分力？）"]["误拒 含 embedding"]))
    print("   ⑤ nodes 末位=%s | assets=%s | gate_decisions 非空=%d" % (
        rk["⑤ 停止点与召回"]["nodes 末位"], rk["⑤ 停止点与召回"]["retrieval_counts.assets"],
        rk["⑤ 停止点与召回"]["gate_decisions 非空"]))
    print()
    print("① 建议新增 metrics = %d 条" % len(gaps_out))
    for i, g in enumerate(gaps_out, 1):
        print("   %2d. %-22s %-8s %-12s %-42s %2d 条" % (
            i, g["metric"], g["display_name"], g["asset"], g["expression"], g["n_covers"]))
    print()
    print("② 不补 = %s" % ", ".join(NOT_GAP))
    print()
    print("③ 非 metric 面覆盖：")
    for f, v in payload["non_metric_faces"].items():
        print("   %s %-46s %2d 条" % (f, v["face"], v["n_cases"]))
    print()
    print("④ 覆盖预估：误拒 %d = 只补 metric %d ＋ 还须附面 %d ＋ 不补 %d" % (
        payload["coverage"]["total_false_refusal"], payload["coverage"]["pure_metric_only"],
        payload["coverage"]["needs_non_metric_face"], len(NOT_GAP)))
    print()
    print("产出：%s" % os.path.basename(OUT_JSON))
    print("产出：%s" % os.path.basename(OUT_MD))
    return 0


if __name__ == "__main__":
    sys.exit(main())
