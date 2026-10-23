"""W71 全量金标口径审计（166 条，全程零出站）。

做法：逐条机械抽取三样 —— ① 问句口径线索 ② gold 谓词/表达式 ③ 语义包声明（带行号），
按包内 expression 判定 gold 是否偏离包；再对三类缺陷做**沙箱双版本实跑**算影响面。

红线：只出审计表 —— 不改任何 gold / 冻结集 / 语义包 / 判据 / 代码；不标 unscored。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from _bootstrap import bootstrap, build_stamp  # noqa: E402

bootstrap()

import yaml  # noqa: E402

from app.semantics import load_bundle  # noqa: E402
import equivalence as eq  # noqa: E402
import runner  # noqa: E402

STAMP = build_stamp()

ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC_R66 = os.path.join(HERE, "results_r66_tau_raw_replay.json")
DATASET = os.path.join(HERE, "dataset_v1_frozen.json")
BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")
SANDBOX = os.path.join(ROOT, "data", "ecom_sandbox.db")
REDTEAM = os.path.join(HERE, "red_team_cases_v1.json")
METRIC_PROBE = os.path.join(ROOT, "backend", "reports", "w6", "probe_metric_values.json")

OUT_AUDIT = os.path.join(HERE, "results_r71_gold_caliber_audit.json")
OUT_IMPACT = os.path.join(HERE, "results_r71_defect_impact.json")
OUT_CITY = os.path.join(HERE, "results_r71_city_coverage.json")

PROVENANCE = "W71 零出站审计（r66 重放 + 冻结集 + 语义包 + 沙箱 sqlite；tokens 计费 = 0）"

ONSALE_WORDS = ("在架", "在售", "上架")
OFFSALE_WORDS = ("下架", "停售")
BARE_PRODUCT_WORDS = ("商品数", "商品数量", "商品个数", "SKU数", "sku数", "款式数", "货品数")
TIME_WORDS = ("本月", "上月", "上个月", "这个月", "最近", "本周", "上周", "同比", "环比",
              "618", "双11", "双十一", "起", "期间")


def _bundle_metric_index() -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """metric name → {expression, note, synonyms, lines}；并返回 yaml 行号。"""
    raw = open(BUNDLE, encoding="utf-8").read().splitlines()
    metrics = yaml.safe_load(open(BUNDLE, encoding="utf-8"))["metrics"]

    # 逐块定位行号：`  - name: X` 起，到下一条 `  - name:` 止
    starts = [(i + 1, ln.split("name:", 1)[1].strip())
              for i, ln in enumerate(raw) if ln.startswith("  - name:")]
    spans: dict[str, tuple[int, int]] = {}
    for idx, (line_no, name) in enumerate(starts):
        end = starts[idx + 1][0] - 1 if idx + 1 < len(starts) else len(raw)
        spans[name] = (line_no, end)

    out: dict[str, dict[str, Any]] = {}
    for m in metrics:
        name = m["name"]
        lo, hi = spans.get(name, (0, 0))
        detail = {"expression": m.get("expression"),
                  "note": (m.get("definition_note") or "").strip(),
                  "synonyms": m.get("synonyms") or [],
                  "lines": [lo, hi]}
        for i in range(lo - 1, min(hi, len(raw))):
            ln = raw[i]
            if ln.strip().startswith("expression:") and detail["expression"] is None:
                detail["expression"] = ln.split("expression:", 1)[1].strip()
            if ln.strip().startswith("synonyms:"):
                detail["synonyms_line"] = i + 1
        out[name] = detail
    return out, {name: span[0] for name, span in spans.items()}


def _matched_metrics(q: str, index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """问句里命中的指标（按同义词最长匹配去重）。"""
    hits: list[tuple[int, str, str]] = []
    for name, meta in index.items():
        for syn in meta["synonyms"]:
            if syn and syn in q:
                hits.append((len(syn), name, syn))
    hits.sort(reverse=True)
    seen: dict[str, str] = {}
    for _, name, syn in hits:
        seen.setdefault(name, syn)
    return [{"metric": n, "synonym": s, **index[n]} for n, s in seen.items()]


def _gold_facts(sql: str) -> dict[str, Any]:
    low = sql.lower()
    tables = sorted(set(re.findall(r"\b(v_[a-z_]+)\b", sql)))
    lits: list[tuple[str, str]] = []
    #: ⚠️ 列名含数字（category_l1/l2/l3）：`[a-z_]+` 会在 "1" 前截断 ⇒ 必须允许数字
    for col, lit in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^']*)'", sql):
        lits.append((col, lit))
    return {
        "tables": tables,
        "has_on_sale_true": bool(re.search(r"\bon_sale\s*=\s*(1|true)\b", low)),
        "has_on_sale_false": bool(re.search(r"\bon_sale\s*=\s*(0|false)\b", low)),
        "literals": lits,
        "has_time_filter": bool(re.search(r"pay_time|stat_date|launch_date|open_date", low)),
        "aggregations": sorted(set(re.findall(r"\b(sum|count|avg|min|max)\s*\(", low))),
    }


_COL_CACHE: dict[str, set[str]] = {}


def _connect():
    """只读沙箱连接 —— 走 `eval/sqlite_exec.py` 的唯一适配层（不直连 sqlite3）。"""
    from sqlite_exec import open_sandbox_connection

    return open_sandbox_connection(SANDBOX, tenant_id=None, tenant_scoped_physicals={})


def _column_values(col: str) -> set[str] | None:
    if col in _COL_CACHE:
        return _COL_CACHE[col]
    con = _connect()
    try:
        vals: set[str] = set()
        for (tbl,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall():
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({tbl})").fetchall()]
            if col not in cols:
                continue
            for (v,) in con.execute(f"SELECT DISTINCT {col} FROM {tbl}").fetchall():
                if isinstance(v, str):
                    vals.add(v)
        _COL_CACHE[col] = vals
        return vals
    finally:
        con.close()


def build_audit() -> dict[str, Any]:
    index, _ = _bundle_metric_index()
    dataset = {c["case_id"]: c for c in json.load(open(DATASET, encoding="utf-8"))["cases"]}
    records = json.load(open(SRC_R66, encoding="utf-8"))["records"]

    rows = []
    for r in records:
        cid = r["case_id"]
        q = r["question"]
        sql = (r.get("gold") or {}).get("gold_sql") or ""
        facts = _gold_facts(sql)
        metrics = _matched_metrics(q, index)

        # ① 问句线索
        q_clues = {
            "onsale_words": [w for w in ONSALE_WORDS if w in q],
            "offsale_words": [w for w in OFFSALE_WORDS if w in q],
            "bare_product_words": [
                w for w in BARE_PRODUCT_WORDS
                if w in q and not any(f"{p}{w}" in q for p in ONSALE_WORDS + OFFSALE_WORDS)
            ] + (["有多少个商品"] if re.search(r"(?:有多少个?商品|多少个商品)", q) else []),
            "time_words": [w for w in TIME_WORDS if w in q],
        }

        #: 兜底：H-STR 族问「各有多少个商品」不含任何包内同义词（同义词表里是「商品数」）
        #: ⇒ 若问句有裸商品数短语但没命中任何指标，按 product_cnt 的包内声明比对。
        if not metrics and q_clues["bare_product_words"]:
            metrics = [{"metric": "product_cnt", "synonym": q_clues["bare_product_words"][0],
                        **index["product_cnt"]}]

        # ② / ③ → 逐条判缺陷
        defects: list[dict[str, str]] = []
        for m in metrics:
            expr = str(m["expression"] or "")
            expr_has_on = "on_sale = true" in expr or "on_sale=1" in expr.lower()
            expr_has_off = "on_sale = false" in expr or "on_sale=0" in expr.lower()
            if q_clues["onsale_words"] and expr_has_on and not facts["has_on_sale_true"]:
                defects.append({
                    "type": "A",
                    "detail": f"问句问「{'/'.join(q_clues['onsale_words'])}」，"
                              f"gold 未过滤 on_sale；包 {m['metric']}（L{m['lines'][0]}）"
                              f"expression 含 on_sale = true",
                    "direction": "假阴性（系统按包加过滤则被判错）",
                })
            if q_clues["offsale_words"] and expr_has_off and not facts["has_on_sale_false"]:
                defects.append({
                    "type": "A",
                    "detail": f"问句问「{'/'.join(q_clues['offsale_words'])}」，"
                              f"gold 未过滤 on_sale = false；包 {m['metric']}（L{m['lines'][0]}）"
                              "expression 含 on_sale = false",
                    "direction": "假阴性",
                })
            if (sql and "商品" in q and not facts["tables"].count("v_product")
                    and not any("product" in t for t in facts["tables"])):
                defects.append({
                    "type": "A2",
                    "detail": "问句问商品，但 gold 的 FROM 里没有商品表"
                              f"（仅 {facts['tables']}）⇒ 错表",
                    "direction": "假阴性（gold 数的不是商品）",
                })
            if (q_clues["bare_product_words"] and "on_sale" in sql.lower()
                    and not expr_has_on):
                defects.append({
                    "type": "B",
                    "detail": f"问句裸「{q_clues['bare_product_words'][0]}」，gold 却带 "
                              f"on_sale 过滤；包 {m['metric']}（L{m['lines'][0]}）"
                              f"expression={expr}（无 on_sale）",
                    "direction": "假阴性（系统按包不加过滤则被判错）",
                })
        # C：字面不在库内 —— 必须拆两级（否则会把「数据缺口」误记成「gold 字面错」）
        for col, lit in facts["literals"]:
            vals = _column_values(col)
            if vals is None or lit in vals:
                continue
            head = re.split(r"[-_－—]", lit)[0]
            fabricated = bool(head) and head != lit and head in vals
            defects.append({
                "type": "C" if fabricated else "C2",
                "detail": (
                    f"gold 字面 {col}='{lit}' 库内无此值；其前缀 '{head}' 在库内存在"
                    f"（实测：{sorted(v for v in vals if head in str(v))[:3]}）⇒ 自造后缀"
                    if fabricated else
                    f"gold 字面 {col}='{lit}' 库内无此值，且无可用前缀 ⇒ 数据覆盖缺口"
                    f"（该列实测值：{sorted(v for v in vals if v)[:4]}）"
                ),
                "direction": "假阴性（gold 恒空，系统无法命中）",
            })

        uniq: list[dict[str, str]] = []
        seen_detail: set[str] = set()
        for d in defects:
            key = f"{d['type']}|{d['detail']}"
            if key not in seen_detail:
                seen_detail.add(key)
                uniq.append(d)
        defects = uniq

        rows.append({
            "case_id": cid,
            "question": q,
            "expected": r["expected_behavior"],
            "terminal": r["terminal_event"],
            "difficulty": [r.get("difficulty_struct"), r.get("difficulty_semantic")],
            "q_clues": q_clues,
            "gold_facts": facts,
            "gold_sql": sql,
            "bundle_metrics": [
                {"metric": m["metric"], "synonym": m["synonym"], "lines": m["lines"],
                 "expression": m["expression"], "note": m["note"][:160]}
                for m in metrics
            ],
            "defects": defects,
            "verdict_equivalent": (r.get("verdict") or {}).get("equivalent"),
        })

    by_type: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for d in row["defects"]:
            by_type[d["type"]].append(row["case_id"])

    return {
        "provenance": PROVENANCE,
        "task": "W71-1 全量 166 条「问句口径 vs gold 口径」一致性审计（只出表：不改任何 gold）",
        **STAMP,
        "method": {
            "clues": "问句正则抽取：在架/在售/上架；下架/停售；裸商品数类词；时间词",
            "gold": "从 gold_sql 抽表集合、on_sale 谓词、字面、时间过滤、聚合函数",
            "bundle": "按 metrics[].synonyms 最长匹配命中概念，再比对 metrics[].expression",
            "defect_rules": {
                "A": "问句问在架/在售/上架（或下架），gold 缺对应 on_sale 谓词，而包 expression 有该谓词",
                "A2": "问句问商品，但 gold 的 FROM 不含商品表（错表）",
                "B": "问句是裸「商品数」类词，gold 却带 on_sale，而包 product_cnt 的 expression=COUNT(*) 无过滤",
                "C": "gold 字面 `col='lit'` 在沙箱该列不存在（逐列实测 DISTINCT 值）",
            },
        },
        "headline": {
            "n_records": len(rows),
            "defect_counts": {k: len(v) for k, v in sorted(by_type.items())},
            "n_clean": sum(1 for r in rows if not r["defects"]),
            "verdict": "只出审计表，不改任何 gold；本产物不构成『已修复』",
        },
        "defect_lists": {k: sorted(set(v)) for k, v in sorted(by_type.items())},
        "rows": rows,
    }


# ============================================================================
# W71-2 三类缺陷「若修正」的影响面（沙箱双版本实跑）
# ============================================================================

_CORRECTIONS = {
    # A 类：补 on_sale
    "E-ENUM-06": lambda s: s.replace("WHERE category_l1", "WHERE on_sale = 1 AND category_l1"),
    "E-ENUM-07": lambda s: s.replace("WHERE category_l1", "WHERE on_sale = 1 AND category_l1"),
    "E-ENUM-08": lambda s: s.replace("WHERE category_l1", "WHERE on_sale = 1 AND category_l1"),
    "E-ENUM-09": lambda s: s.replace("WHERE category_l1", "WHERE on_sale = 1 AND category_l1"),
    "E-ENUM-10": lambda s: s.replace("WHERE category_l1", "WHERE on_sale = 1 AND category_l1"),
    # A2 类（错表）：改成按店铺城市统计在架商品数
    "M-HIER-03": lambda _s: (
        "SELECT s.city, COUNT(*) FROM v_product p JOIN v_shop s ON p.shop_id = s.shop_id "
        "WHERE p.on_sale = 1 GROUP BY s.city"
    ),
    # B 类：去掉 on_sale 限定
    **{f"H-STR-0{i}": (lambda s: s.replace(" AND v_product.on_sale = 1", ""))
       for i in range(1, 9)},
    **{f"H-CAT-0{i}": (lambda s: s.replace(" AND v_product.on_sale = 1", ""))
       for i in range(1, 6)},
    # C 类：修正自造后缀字面
    "M-HIER-04": lambda s: s.replace("3C数码-子类1", "3C数码"),
    "M-HIER-05": lambda s: s.replace("家用电器-子类1", "家用电器"),
    "M-HIER-06": lambda s: s.replace("服饰鞋包-子类1", "服饰鞋包"),
}


def build_impact() -> dict[str, Any]:
    loaded = load_bundle(BUNDLE)
    tsf = {a.physical_asset: "tenant_id"
           for a in loaded.bundle.assets
           if a.tenant_scoped and a.logical_name in loaded.active_assets}
    records = {r["case_id"]: r for r in json.load(open(SRC_R66, encoding="utf-8"))["records"]}

    def _sandbox(sql: str, params: dict | None = None, tenant: str | None = None) -> dict:
        return runner.run_in_sandbox(
            sql, params or {}, tenant=tenant, views=True,
            db_path=SANDBOX, tenant_scoped_physicals=tsf,
        )

    per_case = []
    for cid, fix in _CORRECTIONS.items():
        r = records[cid]
        tenant = r.get("tenant") or "T_A"
        gold = (r.get("gold") or {}).get("gold_sql") or ""
        corrected = fix(gold)
        g0 = _sandbox(gold, tenant=tenant)
        g1 = _sandbox(corrected, tenant=tenant)
        pred_sql = r.get("sql_text") or ""
        p = _sandbox(pred_sql, r.get("sql_params") or {}, tenant=tenant) if pred_sql else {}

        before = None
        after = None
        before_v = after_v = None
        if g0.get("table") is not None and p.get("table") is not None:
            before_v = eq.compare_tables(
                g0["table"], p["table"], gold_sql=gold, pred_sql=pred_sql
            )
            before = before_v.equivalent
        if g1.get("table") is not None and p.get("table") is not None:
            after_v = eq.compare_tables(
                g1["table"], p["table"], gold_sql=corrected, pred_sql=pred_sql
            )
            after = after_v.equivalent

        per_case.append({
            "case_id": cid,
            "fix_class": ("A" if cid.startswith("E-ENUM") else
                          "A2" if cid == "M-HIER-03" else
                          "B" if cid.startswith(("H-STR", "H-CAT")) else "C"),
            "gold_rows_before": g0.get("rows"),
            "gold_rows_after": g1.get("rows"),
            "gold_error_before": g0.get("error"),
            "gold_error_after": g1.get("error"),
            "equivalent_before": before,
            "equivalent_after": after,
            "diffs_before": list(before_v.diffs) if before_v is not None else None,
            "diffs_after": list(after_v.diffs) if after_v is not None else None,
            "flips_to_equivalent": bool(after) and not before,
            "pred_rows": (p or {}).get("rows"),
        })

    cls_summary = {}
    for cls in ("A", "A2", "B", "C"):
        items = [x for x in per_case if x["fix_class"] == cls]
        cls_summary[cls] = {
            "n": len(items),
            "equiv_before": sum(1 for x in items if x["equivalent_before"]),
            "equiv_after": sum(1 for x in items if x["equivalent_after"]),
            "flips": [x["case_id"] for x in items if x["flips_to_equivalent"]],
        }

    return {
        "provenance": PROVENANCE,
        "task": "W71-2 三类缺陷「若修正」的影响面（沙箱双版本实跑；只算不改）",
        **STAMP,
        "method": (
            "修正版 gold 与 r66 记录的预测 SQL 都在同一沙箱、同一租户边界（TEMP VIEW）重跑，"
            "再用 eval/equivalence.py::compare_tables 判定 —— 与判分同器同界，非推演"
        ),
        "class_summary": cls_summary,
        "per_case": per_case,
        "gate_impact": _gate_impact(records),
        "b_consistency_check": {
            "question": "B 类若改成 COUNT(*)，H-CAT 与 M-DIM 是否就一致？还剩几处分歧？",
            "answer": "见 b_pair_values：H-CAT 改 COUNT(*) 后其口径与 M-DIM-07/09 同为全量；"
                      "但 H-STR 仍带 on_sale（同属 B 类），且 M-HIER-04/05/06 是 C 类字面问题 —— "
                      "「一致」只在 B 类内部成立，跨类分歧（C 类 + A 类）仍在",
            "pairs": _b_pairs(records, _sandbox),
        },
    }


def _gate_impact(records: dict[str, dict]) -> list[dict[str, Any]]:
    """八闸逐格核实「修正 A/B/C 是否会影响该闸」——按各闸**实际输入**算交集，不一句话带过。"""
    defect_ids = {
        "A": ["E-ENUM-06", "E-ENUM-07", "E-ENUM-08", "E-ENUM-09", "E-ENUM-10", "M-HIER-03"],
        "A2": ["M-HIER-03"],
        "B": [f"H-STR-0{i}" for i in range(1, 9)] + [f"H-CAT-0{i}" for i in range(1, 6)],
        "C": ["M-HIER-04", "M-HIER-05", "M-HIER-06"],
        "C2": ["H-STR-01", "H-STR-03", "H-STR-04", "H-STR-06", "H-STR-07",
               "X-STR-01", "X-STR-03", "X-STR-04", "X-STR-06", "X-STR-07"],
    }
    all_ids = {i for v in defect_ids.values() for i in v}

    easy_low = [cid for cid, r in records.items()
                if str(r.get("difficulty_struct")) == "easy"
                and str(r.get("difficulty_semantic")) == "low"]
    refuse = [cid for cid, r in records.items() if r.get("expected_behavior") == "refuse"]
    clarify = [cid for cid, r in records.items() if r.get("terminal_event") == "clarify"]
    probe = ["E-MET-01", "E-MET-02", "E-MET-03", "E-MET-04", "E-MET-05", "E-MET-06",
             "E-MET-07", "E-MET-09", "M-IDX-01", "M-IDX-02", "M-IDX-05", "M-IDX-06"]

    def _inter(xs: list[str]) -> list[str]:
        return sorted(set(xs) & all_ids)

    rt_ids = {c["case_id"] for c in
              json.load(open(REDTEAM, encoding="utf-8"))["cases"]} if os.path.isfile(REDTEAM) else set()

    return [
        {"gate": "G-1", "input": "p0_tests（pytest 单元 + 集成结果）",
         "defect_cases_in_input": [], "affected": False,
         "evidence": "输入是测试结果文件，不消费 166 条 records 的等价结论"},
        {"gate": "G-2", "input": "grid easy×low 单元格（passed = verdict.equivalent）",
         "input_cases": sorted(easy_low), "defect_cases_in_input": _inter(easy_low),
         "affected": bool(_inter(easy_low)),
         "evidence": f"easy×low 共 {len(easy_low)} 条，与 A/B/C 缺陷集交集 "
                     f"{len(_inter(easy_low))} 条 ⇒ 缺陷修正不会改变该格分子分母"},
        {"gate": "G-3", "input": "红队矩阵 RT-*（66 条攻击 SQL）",
         "defect_cases_in_input": _inter(sorted(rt_ids)), "affected": bool(_inter(sorted(rt_ids))),
         "evidence": "红队 case id 为 RT-*，与 166 条业务 case 无交集"},
        {"gate": "G-4", "input": "跨租户夹具（redteam 里的 RT-XT 子集）",
         "defect_cases_in_input": [], "affected": False,
         "evidence": "输入是 RT-XT 结果，不消费业务 166 条"},
        {"gate": "G-5", "input": "refusal（expected=refuse 的记录）",
         "input_cases_n": len(refuse), "defect_cases_in_input": _inter(refuse),
         "affected": bool(_inter(refuse)),
         "evidence": f"拒答分母 {len(refuse)} 条，与缺陷集交集 {len(_inter(refuse))} 条"},
        {"gate": "G-6", "input": "压测回执（W7 loadtest）",
         "defect_cases_in_input": [], "affected": False,
         "evidence": "输入是压测报告，与业务 case 无关"},
        {"gate": "G-7", "input": "probe_metric_values.json（13 条核心指标权威值比对）",
         "input_cases": probe, "defect_cases_in_input": _inter(probe),
         "affected": bool(_inter(probe)),
         "evidence": f"G-7 输入是 {len(probe)} 条 E-MET/M-IDX，与缺陷集交集 "
                     f"{len(_inter(probe))} 条"},
        {"gate": "G-8", "input": "records 的 clarify 计数（分子=clarify，分母=已评分）",
         "clarify_cases_n": len(clarify), "defect_cases_that_are_clarify":
             sorted(set(clarify) & all_ids),
         "affected": False,
         "evidence": "修正只改 gold 侧，不改系统行为 ⇒ clarify 分子分母都不变"
                     "（H-STR 6 条目前确为 clarify，但修正 gold 不会让它们变 execute）"},
    ]


def _b_pairs(records: dict[str, dict], sandbox) -> list[dict[str, Any]]:
    """H-CAT（改 COUNT(*)）与 M-DIM 的口径对齐对照（实测值）。"""
    out = []
    for cid in ("H-CAT-01", "M-DIM-07", "M-DIM-09"):
        r = records.get(cid) or {}
        sql = (r.get("gold") or {}).get("gold_sql") or ""
        if not sql:
            continue
        base = sandbox(sql, tenant=r.get("tenant") or "T_A")
        no_on = sandbox(sql.replace(" AND v_product.on_sale = 1", ""),
                        tenant=r.get("tenant") or "T_A")
        out.append({
            "case_id": cid,
            "gold_rows": base.get("rows"),
            "dropping_on_sale_rows": no_on.get("rows"),
            "gold_sql": sql[:160],
        })
    return out


# ============================================================================
# W71-3 城市覆盖缺口登记
# ============================================================================

def build_city() -> dict[str, Any]:
    con = _connect()
    tenant_cities: dict[str, list[str]] = defaultdict(list)
    for city, tid, shop in con.execute(
        "SELECT city, tenant_id, shop_id FROM v_shop ORDER BY tenant_id, shop_id"
    ).fetchall():
        tenant_cities[tid].append(f"{city}（{shop}）")
    con.close()

    records = {r["case_id"]: r for r in json.load(open(SRC_R66, encoding="utf-8"))["records"]}
    city_of = {}
    for cid, r in records.items():
        #: ⚠️ H-STR 题面写「广州」（无「市」）、X-STR 写「广州市」 ⇒ 必须允许可选「市」再归一
        m = re.search(r"(?:位于|在)\s*([\u4e00-\u9fa5]{2,4}?)\s*(?:市)?\s*的\s*店铺",
                      r["question"])
        if m:
            city = m.group(1)
            city_of[cid] = city if city.endswith("市") else f"{city}市"

    rows = []
    for cid, city in city_of.items():
        if ((records[cid].get("gold") or {}).get("via_view") or {}).get("rows") != 0:
            continue
        owner = next((t for t, cities in tenant_cities.items()
                      if any(city in c for c in cities)), None)
        rows.append({
            "case_id": cid,
            "city": city,
            "city_exists_in_tenant": owner,
            "expected": records[cid]["expected_behavior"],
            "terminal": records[cid]["terminal_event"],
        })

    return {
        "provenance": PROVENANCE,
        "task": "W71-3 城市覆盖缺口登记（只出材料）",
        **STAMP,
        "sandbox_tenant_cities": {k: v for k, v in tenant_cities.items()},
        "n_t_a_cities": len(tenant_cities.get("T_A", [])),
        "zero_gold_city_cases": rows,
        "two_fix_paths": {
            "补沙箱数据": {
                "what": "给 T_A 增补广州/成都/武汉/西安/长沙的店铺与商品（或把杭州划到 T_A）",
                "impact": "不动冻结集/gold/判据；沙箱指纹变化 ⇒ 需重跑基线（results 全刷新），不需"
                          "重封印冻结集（gold_result_hash 由 gold SQL 与数据共同决定 ⇒ 空→非空会变）",
                "risk": "🔴 沙箱 DB sha256 写在冻结集 `sandbox_db_sha256` ⇒ 补数据会触发 N-13 验真不一致，"
                        "必须同时更新该指纹（属于冻结集变更，须总控批准）",
            },
            "把 case 改到存在城市": {
                "what": "把 12 条的 6 个城市换成 T_A 已存在的城市",
                "impact": "冻结集变更 + 重封印 + 重基线；沙箱不动",
                "risk": "题面语义随之改变（Q 与 gold 都改），且 H-STR/X-STR 各 8 条会重复城市",
            },
        },
        "recommendation": "不建议直接改 case；若要修，优先补数据 + 更新 sandbox 指纹（一次变更解决 12 条），"
                          "但须先确认冻结集指纹更新的授权路径",
    }


def main() -> None:
    audit = build_audit()
    with open(OUT_AUDIT, "w", encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=2)

    impact = build_impact()
    with open(OUT_IMPACT, "w", encoding="utf-8") as fh:
        json.dump(impact, fh, ensure_ascii=False, indent=2)

    city = build_city()
    with open(OUT_CITY, "w", encoding="utf-8") as fh:
        json.dump(city, fh, ensure_ascii=False, indent=2)

    print("audit defects:", audit["headline"]["defect_counts"],
          "| clean:", audit["headline"]["n_clean"])
    print("impact:", {k: (v["n"], v["equiv_before"], v["equiv_after"])
                      for k, v in impact["class_summary"].items()})
    print("city zero-gold cases:", len(city["zero_gold_city_cases"]),
          "| T_A cities:", city["n_t_a_cities"])


if __name__ == "__main__":
    main()
