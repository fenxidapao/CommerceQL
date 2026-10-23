"""W70 零出站材料：C 类 gold-vs-包物证（W70-1）+ A 类三分法（W70-2）+ 空金标盘点（W70-3）。

纪律：
- 全程零出站：只读 r66 重放产物 / r63 匣带 / 语义包 / 冻结集 / 沙箱 sqlite；
- 只出材料：不改包、不改 gold、不改代码、不标 unscored、不改等价判据；
- 证据绑 git_rev + dirty=false。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from _bootstrap import bootstrap, build_stamp  # noqa: E402

bootstrap()

STAMP = build_stamp()

SRC_R66 = os.path.join(HERE, "results_r66_tau_raw_replay.json")
SRC_R68 = os.path.join(HERE, "results_r68_clarify_completeness.json")
DATASET = os.path.join(HERE, "dataset_v1_frozen.json")
SANDBOX = os.path.join(HERE, "..", "data", "ecom_sandbox.db")
OUT_C = os.path.join(HERE, "results_r70_c_gold_vs_bundle.json")
OUT_A = os.path.join(HERE, "results_r70_a_three_way.json")
OUT_ZERO = os.path.join(HERE, "results_r70_zero_gold_inventory.json")

PROVENANCE = "W70 零出站材料（r66 重放 + r63 匣带 + 语义包 + 冻结集 + 沙箱 sqlite；tokens 计费 = 0）"

#: 语义包内三处产品数指标的行号（bundle_2026.09.14.1.yaml）。
BUNDLE_REFS = {
    "file": "semantic/bundle_2026.09.14.1.yaml（版本身份 2026.10.16.2）",
    "product_cnt": {
        "name_line": 728,
        "expression_line": 730,
        "expression": "COUNT(*)",
        "definition_note_lines": "733-737（不区分上/下架；time_basis=current）",
        "synonyms_line": 744,
        "synonyms": ["商品数", "商品数量", "商品个数", "SKU数", "SKU数量", "sku数", "款式数", "货品数"],
    },
    "on_sale_product_cnt": {
        "name_line": 748,
        "expression_line": 750,
        "expression": "COUNT(*) WHERE on_sale = true",
        "definition_note_lines": "757-761（谓词写进 expression 的理由）",
        "synonyms_line": 766,
        "synonyms": ["在架商品数", "在架商品", "在售商品数", "在售商品", "上架商品数",
                     "在架SKU数", "在售SKU数", "在架商品个数"],
    },
    "off_sale_product_cnt": {"name_line": 768, "synonyms_line": 786},
    "spu_cnt": {"name_line": 790, "expression_line": 792,
                "expression": "COUNT(DISTINCT product.spu_id) WHERE on_sale = true"},
}


# ============================================================================
# W70-1 —— C 类 8 条「gold vs 包」物证包
# ============================================================================

_HSTR_CITY = {
    "H-STR-01": "广州市", "H-STR-02": "杭州市", "H-STR-03": "成都市", "H-STR-04": "武汉市",
    "H-STR-05": "南京市", "H-STR-06": "西安市", "H-STR-07": "长沙市", "H-STR-08": "郑州市",
}


def _run(sql: str) -> tuple[int, list[tuple]]:
    con = sqlite3.connect(SANDBOX)
    try:
        rows = con.execute(sql).fetchall()
        return len(rows), rows[:3]
    finally:
        con.close()


def build_c_account() -> dict[str, Any]:
    r66 = {r["case_id"]: r for r in json.load(open(SRC_R66, encoding="utf-8"))["records"]}
    con = sqlite3.connect(SANDBOX)
    city_owner = {
        row[0]: row[1] for row in con.execute("SELECT city, tenant_id FROM v_shop").fetchall()
    }
    con.close()

    per_case = []
    for cid, city in _HSTR_CITY.items():
        gold_sql = r66[cid]["gold"]["gold_sql"]
        no_onsale_sql = gold_sql.replace(" AND v_product.on_sale = 1", "")
        tenant_cond = f" AND v_shop.tenant_id = 'T_A'"
        # ① 原样（沙箱无租户过滤 = 泄漏视角，仅作对照）
        raw_gold, _ = _run(gold_sql)
        raw_no_onsale, _ = _run(no_onsale_sql)
        # ② 加 T_A 租户过滤（= gold 执行层的等价口径）
        #: ⚠️ gold SQL 用的是 `v_shop.city`（不是别名 s.）：替换必须与原文一致，否则静默不生效
        t_gold = gold_sql.replace(f"v_shop.city = '{city}'", f"v_shop.city = '{city}'{tenant_cond}")
        t_no_onsale = no_onsale_sql.replace(
            f"v_shop.city = '{city}'", f"v_shop.city = '{city}'{tenant_cond}"
        )
        assert tenant_cond in t_gold, "租户条件未成功注入（gold SQL 别名变了？）"
        t_gold_rows, _ = _run(t_gold)
        t_no_rows, _ = _run(t_no_onsale)

        per_case.append({
            "case_id": cid,
            "city": city,
            "city_tenant_in_sandbox": city_owner.get(city),  # None = 该城市在沙箱不存在
            "gold_sql": gold_sql,
            "sandbox": {
                "gold_rows_T_A": t_gold_rows,
                "no_on_sale_rows_T_A": t_no_rows,
                "empty_becomes_nonempty_after_dropping_on_sale": t_gold_rows == 0 and t_no_rows > 0,
                "gold_rows_no_tenant_filter": raw_gold,
                "no_on_sale_rows_no_tenant_filter": raw_no_onsale,
            },
            "conflict_points": [
                f"包 product_cnt（L{BUNDLE_REFS['product_cnt']['name_line']}）"
                f"expression=COUNT(*)、L{BUNDLE_REFS['product_cnt']['definition_note_lines']}"
                " 明文「不区分上/下架」，与 gold 的 "
                "`AND v_product.on_sale = 1` 直接冲突",
                "同一措辞「商品数」在 gold 内部就分裂：M-DIM-07/09、M-HIER-04/05/06 的 gold "
                "用 COUNT(*) 无过滤，H-CAT-01…05 与本案族用 COUNT(*) + on_sale=1",
            ],
            "sandbox_verdict": (
                "该城市在沙箱**不存在**（或属他租户）⇒ 去掉 on_sale 仍 0 行，"
                "空金标与 on_sale 无关"
                if t_gold_rows == 0 and t_no_rows == 0 else
                f"两版均非空：带 on_sale {t_gold_rows} 行 / 不带 {t_no_rows} 行"
                "（口径差可由 COUNT 值体现，但不会改变空/非空）"
            ),
        })

    # —— 改 synonyms 指向 on_sale_product_cnt 的波及面（不改，只列）——
    dataset = json.load(open(DATASET, encoding="utf-8"))
    bare_syn = ("商品数", "商品数量", "商品个数")
    prefixed = ("在架商品数", "在售商品数", "上架商品数", "下架商品数", "停售商品数")
    affected = []
    for c in dataset["cases"]:
        q = c["question"]
        if not any(s in q for s in bare_syn):
            continue
        if any(p in q for p in prefixed):
            continue  # 已被在架/下架等前缀锁定，不受影响
        gold_sql = (r66.get(c["case_id"], {}).get("gold") or {}).get("gold_sql", "")
        affected.append({
            "case_id": c["case_id"],
            "question": q,
            "gold_uses_on_sale": "on_sale" in gold_sql,
            "consistent_with_move": "on_sale" in gold_sql,
        })

    return {
        "provenance": PROVENANCE,
        "task": "W70-1 C 类 8 条「gold vs 包」物证包（只出材料：不改包/gold/代码）",
        **STAMP,
        "bundle_refs": BUNDLE_REFS,
        "sandbox_note": (
            "沙箱 = data/ecom_sandbox.db（12 店：T_A 太原/长春/南京/福州/郑州，"
            "T_B 呼和浩特/哈尔滨/杭州/南昌，T_C 沈阳/上海/合肥）。"
            "gold 执行层带租户隔离 ⇒ 本表 `_T_A` 列在 SQL 里显式加 `v_shop.tenant_id='T_A'` 复刻。"
        ),
        "honest_correction": (
            "派单前提『8/8 预测 SQL 缺 AND v_product.on_sale = 1 ⇒ 0/8 等价是口径错』"
            "在沙箱上**不成立**：8 条里 6 条的城市在 T_A 根本不存在（去掉 on_sale 仍 0 行），"
            "第 7 条杭州属 T_B（租户隔离），只有南京/郑州两条有数据；"
            "而这两条的等价失败 diff 实测是**列数**（预测多 shop_name），不是 on_sale。"
            "on_sale 口径差真实存在（南京 369 vs 400、郑州 377 vs 400），但它不是 0/8 的主因。"
        ),
        "per_case": per_case,
        "synonym_move_impact": {
            "what_changes": "把「商品数/商品数量/商品个数」从 product_cnt（L744）迁到 "
                            "on_sale_product_cnt（L766）⇒ 裸「商品数」将按在架口径计数",
            "affected_metrics": {
                "product_cnt": "失去全部裸同义词（只剩 SKU数/SKU数量/sku数/款式数/货品数）"
                               "⇒ 「全量商品数」将无任何同义词可命中",
                "on_sale_product_cnt": "新增裸同义词，与已有「在架商品数」共存（不冲突）",
                "spu_cnt": "不受影响（款数/SPU 系独立）",
            },
            "affected_frozen_cases": affected,
            "n_affected": len(affected),
            "consistency_split": {
                "gold_already_on_sale": [a["case_id"] for a in affected if a["gold_uses_on_sale"]],
                "gold_without_on_sale": [a["case_id"] for a in affected if not a["gold_uses_on_sale"]],
            },
            "verdict": (
                f"波及 {len(affected)} 条裸「商品数」题：其中 "
                f"{sum(1 for a in affected if a['gold_uses_on_sale'])} 条 gold 已是 on_sale 口径"
                "（迁移后自洽）、其余 gold 是 COUNT(*) 全量口径（迁移后会与 gold 冲突）"
                "⇒ 迁移必须与 gold 口径统一同步做，否则只是把冲突从 8 条扩散到更多条"
            ),
        },
    }


# ============================================================================
# W70-2 —— A 类 10 条三分法
# ============================================================================

#: 逐条判定（依据：包内声明 / 明文窗口 / 系统是否静默填默认）。
_A_JUDGMENT: dict[str, dict[str, Any]] = {
    "C-GMV-01": {
        "judgment": "改 expected",
        "basis": "包 L1510 明文 alias 本月→relative:this_month（唯一口径）；系统按包执行未自造窗口",
        "bundle_declared": True, "explicit_window": True, "system_silent_default": False,
        "counter_consideration": "若产品坚持「本月=最近 30 天」，那是另一个指标，须改包新增 alias（与字面冲突）",
    },
    "C-GMV-02": {
        "judgment": "改 expected（首选）/ 改包加回显（次选）",
        "basis": "包 L1512 alias 上个月→relative:last_month + L1605 明文窗口定义；回显确认是体验项而非口径必需",
        "bundle_declared": True, "explicit_window": True, "system_silent_default": False,
        "counter_consideration": "若要求「先回显再答」，属新增闸门（改包 + 改系统），成本高于改 expected",
    },
    "C-GMV-03": {
        "judgment": "改系统",
        "basis": "包内无「最近」alias；plan LLM 自填 time_range=rolling:7d_incl_today 且 "
                 "blocking_issues=[]（r63 匣带 plan 响应原文）⇒ 静默默认必须改成澄清",
        "bundle_declared": False, "explicit_window": False, "system_silent_default": True,
        "counter_consideration": "也可改包定义「最近=近 7 天」（产品决策），但那需要重基线",
    },
    "C-GMV-04": {
        "judgment": "改系统",
        "basis": "包内无「最近一周」；系统自选 date_trunc('week', CURRENT_DATE) 周起点 ⇒ 起点未定却出数",
        "bundle_declared": False, "explicit_window": False, "system_silent_default": True,
        "counter_consideration": "周起点包内虽有 week_starts_on，但「最近一周」不等于「本周」",
    },
    "C-RATE-01": {
        "judgment": "改 expected",
        "basis": "包 refund_rate（L580）表达式=金额口径，definition_note 明文「若要单量口径须另立 "
                 "refund_rate_qty（P1）」⇒ 包内唯一口径，直答正确",
        "bundle_declared": True, "explicit_window": False, "system_silent_default": False,
        "counter_consideration": "若产品要在答案里披露口径，属展示层改进，不必走澄清",
    },
    "C-RATE-02": {
        "judgment": "改 expected",
        "basis": "包 refund_rate synonyms 含「退货率」（L580 块）⇒ 术语映射**已存在**；"
                 "W68-3 记的 term_mapping_unknown 判定需更正",
        "bundle_declared": True, "explicit_window": False, "system_silent_default": False,
        "counter_consideration": "若业务认为「退货」与「退款」应分开（单据类型不同），须改包拆指标",
    },
    "C-REP-01": {
        "judgment": "改 expected",
        "basis": "包 repurchase_rate_90d（L603）周期固定 90 天、明文「不接受运行时改窗口」⇒ 唯一口径",
        "bundle_declared": True, "explicit_window": True, "system_silent_default": False,
        "counter_consideration": "「不含首单」是包内刻意默认，已在 definition_note 写明",
    },
    "C-REP-02": {
        "judgment": "改系统",
        "basis": "开放式「怎么样」既无维度也无窗口；包内 repurchase 固定 90d 但无法回答「情况」⇒ "
                 "系统应澄清要哪个指标/维度，而非自选",
        "bundle_declared": False, "explicit_window": False, "system_silent_default": True,
        "counter_consideration": "也可在 request_policy 里把开放式问法判 open_analysis（拒答+替代问法）",
    },
    "C-UV-02": {
        "judgment": "改系统（必须澄清）",
        "basis": "包 uv（L626）明文「跨日直接累加会重复计数；uv_period（P1，本包未定义 → "
                 "**未定义的指标不得被生成**）」；实测 SQL 正是 SUM(uv) 全期累加 ⇒ 违反包内明文",
        "bundle_declared": True, "explicit_window": False, "system_silent_default": True,
        "counter_consideration": "P1 落地 uv_period 后本条可改 expected=execute（改包）",
    },
    "C-AOV-01": {
        "judgment": "改 expected",
        "basis": "包 aov（L535）分母=支付子订单数、definition_note 覆盖高危口径说明；包未要求时间窗",
        "bundle_declared": True, "explicit_window": False, "system_silent_default": False,
        "counter_consideration": "全期客单价业务上少见；若要强制窗口须改系统闸门（会波及其它指标）",
    },
}


def build_a_three_way() -> dict[str, Any]:
    w68 = json.load(open(SRC_R68, encoding="utf-8"))
    w68_cases = {c["case_id"]: c for c in w68["cases"]}

    rows = []
    for cid, j in _A_JUDGMENT.items():
        base = w68_cases[cid]
        rows.append({
            "case_id": cid,
            "question": base["question"],
            "judgment": j["judgment"],
            "basis": j["basis"],
            "evidence": {
                "bundle_declared": j["bundle_declared"],
                "explicit_window": j["explicit_window"],
                "system_silent_default": j["system_silent_default"],
            },
            "counter_consideration": j["counter_consideration"],
            "cost": {
                "changes_frozen_set": j["judgment"].startswith("改 expected"),
                "changes_bundle": "改包" in j["judgment"],
                "changes_code": "改系统" in j["judgment"],
                "breaks_cassette": "改包" in j["judgment"],  # 包变 ⇒ prompt 变 ⇒ 哈希变
                "needs_rebaseline": True,  # 三种都改变判定结论
            },
            "reuse": "实际 SQL / 缺哪类闸门来自 W68-3 results_r68_clarify_completeness.json（未重做）",
        })

    counts = Counter(r["judgment"].split("（")[0] for r in rows)
    return {
        "provenance": PROVENANCE,
        "task": "W70-2 A 类 10 条逐条三分法（只出材料：不改 expected / 不改包 / 不改系统）",
        **STAMP,
        "headline": {
            "n_cases": len(rows),
            "judgment_counts": dict(counts),
            "verdict": (
                "10 条里 6 条判「改 expected」（包内已有唯一口径或明文映射：本月/上个月/退款率/"
                "退货率/复购率/客单价）、4 条判「改系统」（最近/最近一周/开放式复购/总访客数 —— "
                "包内无定义或包内明文禁止生成未定义指标）。三分法不替总控做选择，"
                "只标出每条的最短改动路径与成本。"
            ),
            "cost_summary": {
                "改 expected（6 条）": "改冻结集 ⇒ 重封印 + 重基线；不动代码 ⇒ 不破匣带",
                "改系统（4 条）": "只改 timeexpr/request_policy 判定 ⇒ 不破匣带，但行为变 ⇒ 重基线",
                "改包（0 条主判，仅 C-GMV-03/04、C-UV-02 的可选路径）": "包变 ⇒ prompt 变 ⇒ 匣带全 miss + 重基线",
            },
        },
        "corrections_to_w68_3": [
            "C-RATE-02：包 refund_rate synonyms 含「退货率」⇒ 术语映射已存在，"
            "W68-3 的 term_mapping_unknown 判定不准确",
            "C-UV-02：包内 uv 明文「跨日累加会重复计数 + uv_period 未定义不得生成」⇒ 缺闸门性质更硬",
            "C-GMV-03：缺窗口不是「无定义」这么简单 —— plan LLM 会自填 rolling:7d 且不报 blocking，"
            "属静默默认缺陷",
        ],
        "cases": rows,
    }


# ============================================================================
# W70-3 —— 空金标盘点
# ============================================================================

def build_zero_gold() -> dict[str, Any]:
    r66 = json.load(open(SRC_R66, encoding="utf-8"))
    recs = r66["records"]
    LEVELS = {"easy", "medium", "hard", "extra"}

    zero = []
    for r in recs:
        if ((r.get("gold") or {}).get("via_view") or {}).get("rows") != 0:
            continue
        sql = (r.get("gold") or {}).get("gold_sql") or ""
        zero.append({
            "case_id": r["case_id"],
            "question": r["question"],
            "difficulty": [r.get("difficulty_struct"), r.get("difficulty_semantic")],
            "expected": r["expected_behavior"],
            "terminal": r["terminal_event"],
            "gold_sql": sql,
            "gold_predicates": [p for p in ("tenant_id", "city", "category_l1", "on_sale")
                                if p in sql],
        })

    # 成因分类（逐类给依据，不猜）
    def _reason(item: dict[str, Any]) -> tuple[str, str]:
        sql = item["gold_sql"]
        if "category_l1 = '" in sql:
            lit = sql.split("category_l1 = '")[1].split("'")[0]
            return ("gold_字面与数据不匹配",
                    f"gold 过滤 category_l1='{lit}'，沙箱该列实际值为 '{lit.split('-')[0]}'"
                    "（「-」后是 case_library 里自造的后缀）⇒ 该品类有数据但字面错")
        if "city" in sql:
            return ("数据覆盖缺口（城市）",
                    "该城市在 T_A 无店铺（或属他租户）⇒ 与 on_sale / 过滤松严无关")
        return ("其它", "需人工判读")

    for item in zero:
        item["reason_class"], item["reason_detail"] = _reason(item)

    # 影响面：按格计数（只算不改）
    cells = defaultdict(lambda: [0, 0, 0, 0])  # n, passed, removed_n, removed_passed
    for r in recs:
        if r.get("scored") is False:
            continue
        s = str(r.get("difficulty_struct"))
        if s not in LEVELS:
            continue
        key = (s, str(r.get("difficulty_semantic")))
        eq = bool((r.get("verdict") or {}).get("equivalent"))
        cells[key][0] += 1
        cells[key][1] += eq
        if ((r.get("gold") or {}).get("via_view") or {}).get("rows") == 0:
            cells[key][2] += 1
            cells[key][3] += eq

    impact = []
    for key in sorted(cells):
        n, ps, rn, rp = cells[key]
        impact.append({
            "cell": list(key),
            "n": n, "passed": ps, "rate": round(ps / n, 4) if n else None,
            "zero_gold_n": rn, "zero_gold_passed": rp,
            "after_unscored": {
                "n": n - rn, "passed": ps - rp,
                "rate": round((ps - rp) / (n - rn), 4) if n - rn else None,
            },
        })

    cls = Counter(item["reason_class"] for item in zero)
    return {
        "provenance": PROVENANCE,
        "task": "W70-3 空金标盘点（只出事实 + 影响面；不改判据、不标 unscored、不剔分母）",
        **STAMP,
        "headline": {
            "n_zero_gold": len(zero),
            "reason_classes": dict(cls),
            "terminal_split": dict(Counter(item["terminal"] for item in zero)),
            "verdict": (
                f"15 条空金标全部可归因于**数据/字面**："
                f"{cls.get('数据覆盖缺口（城市）', 0)} 条城市不在 T_A、"
                f"{cls.get('gold_字面与数据不匹配', 0)} 条 gold 品类字面错误"
                "（'3C数码-子类1' 数据里不存在）。没有一条是「视图空」或「过滤过严」；"
                "与 on_sale 口径无关（详见 W70-1 沙箱双版本跑）。"
            ),
        },
        "cases": zero,
        "impact_if_unscored": impact,
        "g2_note": (
            "G-2 只看 easy×low 格：该格 8/8 PASS，且 15 条空金标**无一落在此格** ⇒ "
            "标 unscored 不影响 G-2 判定"
        ),
    }


def main() -> None:
    for path, data in (
        (OUT_C, build_c_account()),
        (OUT_A, build_a_three_way()),
        (OUT_ZERO, build_zero_gold()),
    ):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print("written:", os.path.basename(path))

    zero = json.load(open(OUT_ZERO, encoding="utf-8"))
    print("zero-gold:", zero["headline"]["reason_classes"])
    a = json.load(open(OUT_A, encoding="utf-8"))
    print("A three-way:", a["headline"]["judgment_counts"])


if __name__ == "__main__":
    main()
