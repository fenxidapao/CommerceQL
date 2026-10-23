"""W73 材料件（零出站）：误拒定位 / 列族量化 / 复购金标方案。

派单 TASK_BOARD §94.9：
* W73-2 误拒 3/124 定位（只出材料）
* W73-3 列族量化（只出材料，不改 equivalence.py）
* W73-4 复购金标（只出方案）

W73-1（谓词矛盾守卫）是代码改动，不在本脚本内；本脚本只**读**：
r74 重放产物、r63 匣带（取模型原始响应）、语义包、沙箱（`mode=ro`）。
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections import Counter
from datetime import date, timedelta
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from _bootstrap import BUNDLE_PATH, bootstrap, build_stamp  # noqa: E402

bootstrap()

STAMP = build_stamp()

import yaml  # noqa: E402

from app.semantics import load_bundle  # noqa: E402
import equivalence as eq  # noqa: E402
import runner  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
SANDBOX = os.path.join(ROOT, "data", "ecom_sandbox.db")
BUNDLE = BUNDLE_PATH
SRC = os.path.join(HERE, "results_r74_full166_contradiction_guard.json")
CASSETTE = os.path.join(HERE, "cassettes", "w8_r63_full166.jsonl")

OUT_REFUSAL = os.path.join(HERE, "results_r73_refusal_localization.json")
OUT_COLUMNS = os.path.join(HERE, "results_r73_column_family.json")
OUT_REPURCHASE = os.path.join(HERE, "results_r73_repurchase_gold.json")

PROVENANCE = "W73 零出站材料（r74 重放 + r63 匣带 + 语义包 + 沙箱 sqlite；tokens = 0）"

#: W73-2 的三条误拒案（QA §94.5 第 2 条）
REFUSAL_CASES = ("M-DIM-05", "M-MET-01", "E-MET-08")


def _sandbox(sql: str, params: dict | None = None, tenant: str | None = None) -> dict[str, Any]:
    loaded = load_bundle(BUNDLE)
    tsf = {
        a.physical_asset: "tenant_id"
        for a in loaded.bundle.assets
        if a.tenant_scoped and a.logical_name in loaded.active_assets
    }
    return runner.run_in_sandbox(
        sql, params or {}, tenant=tenant, views=True,
        db_path=SANDBOX, tenant_scoped_physicals=tsf,
    )


# ============================================================================
# W73-2 误拒定位
# ============================================================================

def _planner_call(cassette: str, needle: str) -> dict[str, Any] | None:
    """从匣带里取「问题含 needle 且 system 是计划提示词」的那次调用。"""
    with open(cassette, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            req = rec["request"]
            if isinstance(req, str):
                req = ast.literal_eval(req)
            msgs = req.get("messages") or []
            blob = "\n".join(str(m.get("content", "")) for m in msgs)
            if needle not in blob or "查询计划" not in blob:
                continue
            resp = rec["response"]
            if isinstance(resp, str):
                resp = ast.literal_eval(resp)
            content = resp["choices"][0]["message"]["content"]
            try:
                plan = json.loads(content)
            except json.JSONDecodeError:
                plan = {"_raw": content}
            return {"plan": plan, "system_chars": len(str(msgs[0].get("content", "")))}
    return None


def _bundle_facts() -> dict[str, Any]:
    b = yaml.safe_load(open(BUNDLE, encoding="utf-8"))
    raw = open(BUNDLE, encoding="utf-8").read().splitlines()
    dims = {}
    for d in b.get("dimensions") or []:
        dims[d["name"]] = {
            "binding": d.get("binding") or d.get("bindings"),
            "grain_level": d.get("grain_level"),
        }
    assets = {
        a["logical_name"]: {
            "physical": a["physical_asset"],
            "columns": [c["name"] for c in a["columns"]],
        }
        for a in b["assets"]
    }
    concepts = {}
    for c in b.get("field_bindings") or []:
        key = c.get("concept")
        if key:
            concepts[key] = {
                "canonical_asset": c.get("canonical_asset"),
                "note": c.get("note"),
                "default_reason": c.get("default_reason"),
            }
    #: 行号：维度声明 / 列注释 / concept 声明
    def _line(pattern: str) -> int | None:
        for i, ln in enumerate(raw):
            if re.search(pattern, ln):
                return i + 1
        return None

    return {
        "dimensions": dims,
        "assets": assets,
        "concepts": concepts,
        "lines": {
            "shop_city_column": _line(r"^\s+- name: city$"),
            "city_dimension": _line(r"^\s+- name: city\s*$") ,
            "channel_dimension": _line(r"^\s+- name: channel\s*$"),
            "channel_concept_note": _line(r"order_paid\.channel 同样存在"),
        },
    }


def build_refusal(records: dict[str, dict[str, Any]], facts: dict[str, Any]) -> dict[str, Any]:
    plan_by_case = {}
    needle = {
        "M-DIM-05": "各城市的店铺数",
        "M-MET-01": "各渠道的 GMV",
        "E-MET-08": "含未支付",
    }
    for cid in REFUSAL_CASES:
        plan_by_case[cid] = _planner_call(CASSETTE, needle[cid])

    cases = []
    for cid in REFUSAL_CASES:
        r = records[cid]
        call = plan_by_case.get(cid) or {}
        plan = call.get("plan") or {}
        blockers = plan.get("blocking_issues") or []
        cases.append({
            "case_id": cid,
            "question": r.get("question"),
            "expected_behavior": r.get("expected_behavior"),
            "terminal_event": r.get("terminal_event"),
            "refusal_reason": r.get("refusal_reason"),
            "node_path": r.get("nodes"),
            "refused_at": (r.get("nodes") or [None])[-2] if r.get("nodes") else None,
            "terminal_error_detail": r.get("terminal_error_detail"),
            "gold_sql": (r.get("gold") or {}).get("gold_sql"),
            "planner_assets": plan.get("assets"),
            "planner_metrics": plan.get("metrics"),
            "planner_blocking_issues": blockers,
        })

    dims = facts["dimensions"]
    assets = facts["assets"]

    return {
        "provenance": PROVENANCE,
        "task": "W73-2 误拒 3/124 定位（只出材料；不改代码/判据）",
        **STAMP,
        "method": (
            "三条误拒案的终态/节点路径取自 r74 重放产物；模型原始计划响应取自 r63 匣带"
            "（按问句子串 + 计划提示词双重匹配，每次调用唯一命中）；"
            "「资产是否真缺」用语义包 `assets[].columns` / `dimensions` / `field_bindings` 核对"
        ),
        "scope_note": (
            "误拒分母 124 / 3 条由 QA §94.5 用 `reporter._refusal_counts` 测得；"
            "本件不重算分母，只做**逐条归因**"
        ),
        "bundle_reality": {
            "channel_dimension": dims.get("channel"),
            "city_dimension": dims.get("city"),
            "shop_has_city": "city" in (assets.get("shop", {}).get("columns") or []),
            "order_paid_has_channel": "channel" in (assets.get("order_paid", {}).get("columns") or []),
            "concept_渠道": facts["concepts"].get("渠道"),
            "lines": facts["lines"],
        },
        "cases": cases,
        "verdicts": {
            "M-DIM-05": {
                "assets_really_missing": False,
                "what_is_missing": "包内**没有** `shop.city` 这个维度条目：`dimensions[name=city]` "
                                   "绑的是 `order_paid.receiver_city`；`assets[shop].columns` 里"
                                   "确实有 `city`（注释写明「店铺所在城市，与收货城市同名不同义」）"
                                   "⇒ 数据在、**维度声明缺一半**",
                "node": "plan → refuse_out（`blocking_issues` 非空 ⇒ `refuse(no_data_asset)`）",
                "why_intent_did_not_clarify": (
                    "模型在 normalize 合并档给了 `clarify_needed`/"
                    "`ambiguous_dimension_city`，但 `normalize.py:104` "
                    "`_demote_unambiguous_shop_city_clarification` 在 "
                    "`normalize.py:130` 用「问句含『各城市』」这一条就把它降级为 executable "
                    "⇒ 走 link → plan；随后 plan 又以同一歧义为由阻塞"
                ),
                "classification": "① 归因码错位（歧义被记成 `no_data_asset`）；"
                                  "② 降级判据与 planner 判定打架（结构化证据没传给 planner）",
            },
            "M-MET-01": {
                "assets_really_missing": False,
                "what_is_missing": "`order_paid.channel` **存在**（资产列清单里就有），"
                                   "包内 concept「渠道」的 `note` 也写明「订单域问题应绑 "
                                   "order_paid.channel」；但 `dimensions[name=channel].binding` 是 "
                                   "`traffic_daily.channel` ⇒ 模型只看到后者，据此判定「订单侧无渠道」"
                                   "并要求澄清/阻塞",
                "node": "plan → refuse_out（`blocking_issues` 非空）",
                "classification": "planner 资产映射缺陷（维度声明与 concept note 方向相反 ⇒ 模型选错一面）",
            },
            "E-MET-08": {
                "assets_really_missing": False,
                "what_is_missing": "不是资产缺失：模型给的两条阻塞项是 "
                                   "①「语义包无『含未支付』指标，gmv 默认只算已支付」"
                                   "②「时间范围只有起点、无终点」",
                "node": "plan → refuse_out（`blocking_issues` 非空）",
                "classification": "「自造口径」保护按设计生效；但 ② 是**误加**的阻塞项"
                                  "（同批其它「从 2026-08-01 起」的题都执行了）",
                "disposition_recommendation": {
                    "expected_behavior": "clarify（建议）",
                    "why": "题面「付费金额合计（含未支付）」本身歧义："
                           "「含未支付」= 不过滤支付状态（全部），还是 = 仅未支付？"
                           "冻结集 gold 取 `pay_status = 'unpaid'`（仅未支付），与题面「含」不等价；"
                           "改成 clarify 既承认这层歧义，又不需要自造指标",
                    "alternatives": [
                        "refuse：承认「自造口径应拒答」是设计意图 ⇒ 需同步改冻结集 notes 与 G-5 分母",
                        "execute + 修 gold：gold 改 `SELECT SUM(pay_amount) ... WHERE pay_time >= …`"
                        "（不过滤 pay_status）⇒ 冻结集变更，需总控签",
                    ],
                    "g7_reverse_contrast": "只有**修 gold 并置 execute** 才能充当 G-7 的"
                                           "「反向口径」正例（系统须算出与权威值一致的数）；"
                                           "若定为 clarify/refuse，它就只能测「不静默套默认谓词」，"
                                           "测不到「反向口径算对」",
                    "warning": "任何改 expected_behavior 的动作都会让 G-5 误拒从 3/124 变成 2/124 —— "
                               "这是**刷绿**风险，必须总控签",
                },
            },
        },
        "root_cause_shared": (
            "三条里没有一条是「语义包真的没有这张表」；两条（M-DIM-05/M-MET-01）是"
            "**维度声明只写了一半**（shop.city 缺维度条目、order_paid.channel 与 canonical 绑定相反），"
            "一条（E-MET-08）是**问题本身歧义 + gold 取反向**。"
            "三者共同被 `plan.blocking_issues → refuse(no_data_asset)` 这层映射压成同一个码，"
            "于是「歧义 / 映射错 / 真缺数据」在报表上不可区分（`plan.py:91-105`）。"
        ),
    }


# ============================================================================
# W73-3 列族量化
# ============================================================================

def _col_multiset(table: eq.Table, j: int) -> Counter:
    return Counter(eq._row_key((v,)) for v in table.column(j))


def _project_compare(gold: eq.Table, pred: eq.Table, mode: str) -> dict[str, Any]:
    """把预测**投影到金标的列上**再比（忽略预测多出来的列）。

    `name` 模式：只认同名同值；`value` 模式：按整列多重集配对（覆盖改名），
    两种模式都**不考虑**行序（与 `compare_tables` 的多重集口径一致）。
    """
    gcols, pcols = list(gold.columns), list(pred.columns)
    if len(gold.rows) != len(pred.rows):
        return {"ok": False, "reason": f"行数不同：{len(gold.rows)} vs {len(pred.rows)}"}
    used: set[int] = set()
    matched: list[dict[str, Any]] = []
    for i, gname in enumerate(gcols):
        gkey = _col_multiset(gold, i)
        hit = None
        for j, pname in enumerate(pcols):
            if j in used:
                continue
            if mode == "name" and pname != gname:
                continue
            if _col_multiset(pred, j) == gkey:
                hit = j
                break
        if hit is None:
            return {
                "ok": False,
                "reason": f"金标列 {gname!r} 在预测里找不到同值列（{mode} 模式）",
                "matched": matched,
            }
        used.add(hit)
        matched.append({"gold": gname, "pred": pcols[hit]})
    return {
        "ok": True,
        "matched": matched,
        "extra_pred_columns": [pcols[j] for j in range(len(pcols)) if j not in used],
    }


def build_columns(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for cid, r in records.items():
        gold_sql = (r.get("gold") or {}).get("gold_sql") or ""
        if not gold_sql:
            continue
        pred_sql = r.get("sql_text") or ""
        if not pred_sql:
            #: 预测侧没有结果集（拒答 / 错误）—— QA 记的 36 条里有 12 条是这一类
            rows.append({
                "case_id": cid,
                "question": r.get("question"),
                "expected_behavior": r.get("expected_behavior"),
                "terminal_event": r.get("terminal_event"),
                "n_gold_cols": None,
                "n_pred_cols": 0,
                "family": "预测无结果集（拒答/错误）— 不属列族问题",
                "only_extra_column": False,
            })
            continue
        tenant = r.get("tenant") or "T_A"
        g = _sandbox(gold_sql, tenant=tenant)
        p = _sandbox(pred_sql, r.get("sql_params") or {}, tenant=tenant)
        if g.get("error") or p.get("error"):
            continue
        gcols, pcols = list(g["table"].columns), list(p["table"].columns)
        if len(gcols) == len(pcols):
            continue
        entry: dict[str, Any] = {
            "case_id": cid,
            "question": r.get("question"),
            "n_gold_cols": len(gcols),
            "n_pred_cols": len(pcols),
            "gold_cols": gcols,
            "pred_cols": pcols,
            "gold_rows": g.get("rows"),
            "pred_rows": p.get("rows"),
        }
        if not pcols:
            entry["family"] = "预测无结果集（拒答/错误）— 不属列族问题"
        else:
            for mode in ("name", "value"):
                entry[f"projection_{mode}"] = _project_compare(g["table"], p["table"], mode)
            entry["extra_columns"] = entry["projection_value"].get(
                "extra_pred_columns"
            ) or [c for c in pcols if c not in gcols]
            entry["only_extra_column"] = bool(entry["projection_value"].get("ok"))
            entry["family"] = (
                "仅多列（忽略预测多出的列后，金标每列都能按值配上）"
                if entry["only_extra_column"]
                else "值也不同（多列之外还有数值差）"
            )
        rows.append(entry)

    fam = Counter(x["family"] for x in rows)
    by_shape = Counter(f"{x['n_gold_cols']}→{x['n_pred_cols']}" for x in rows)
    flips = [x["case_id"] for x in rows if x.get("projection_name", {}).get("ok")]
    flips_value = [x["case_id"] for x in rows if x.get("projection_value", {}).get("ok")]
    extra_hist = Counter(
        tuple(x.get("extra_columns") or []) for x in rows if x.get("only_extra_column")
    )
    no_result = [x["case_id"] for x in rows if not x["n_pred_cols"]]
    return {
        "provenance": PROVENANCE,
        "task": "W73-3 列族量化（只出影响面；不改 equivalence.py、不改判据）",
        **STAMP,
        "method": (
            "r74 重放里 terminal=complete 且带预测 SQL 的每条，在同一沙箱/租户边界重跑金标与预测；"
            "取列数不等的那些，再做两种投影：`name` = 金标每列必须在预测里**同名同值**，"
            "`value` = 只要求**同值**（覆盖改名）；预测多出的列一律忽略、行序不参与"
        ),
        "headline": {
            "n_column_count_mismatch": len(rows),
            "n_sandbox_runnable": sum(1 for x in rows if x["n_pred_cols"]),
            "n_no_result_set": len(no_result),
            "no_result_set_cases": no_result,
            "by_shape": dict(by_shape),
            "by_family": dict(fam),
            "n_flip_if_ignore_extra_by_name": len(flips),
            "flip_cases_by_name": flips,
            "n_flip_if_ignore_extra_by_value": len(flips_value),
            "flip_cases_by_value": flips_value,
            "extra_column_histogram": {"+".join(k) or "(none)": v for k, v in extra_hist.items()},
            "name_mode_is_unusable": (
                "金标的聚合列**没有别名** ⇒ `Table.columns` 里是 `SUM(pay_amount)` 这种表达式串，"
                "而预测侧是 `gmv`；按列名投影会**结构性**匹配不上（0/24），"
                "所以「忽略多余列」只能按**值**判定，这也正是风险所在"
            ),
            "red_line": "只出影响面。是否「忽略多余列」= 等价判据口径变更 ⇒ 须总控裁；"
                        "本件未改 `equivalence.py` 一行",
        },
        "risk": [
            "① 「忽略多余列」会放过「预测多算了一列」这类真缺陷：多出来的列若本身是错的，"
            "判定层再也看不见；须配「多列只允许出现在 output_columns 声明的范围内」之类的限定。",
            "② 本件只证明「值对齐」，不证明「多出来的列是合理投影」：例如多 `shop_id` 与多 "
            "`shop_name` 在业务上不同（前者可配对、后者是改名）。",
            "③ 23 条 2→3 的多列里，若预测同时带 `shop_id` 与 `shop_name`，按 name 模式金标 "
            "`shop_id` 能配上、`shop_name` 属多余；按 value 模式两者都可能配得上 ⇒ 两种模式"
            "给出不同清单，不可混用。",
        ],
        "rows": rows,
    }


# ============================================================================
# W73-4 复购金标方案
# ============================================================================

_REPURCHASE_GOLD = (
    "SELECT COUNT(DISTINCT CASE WHEN cnt >= 2 THEN buyer_id END) / "
    "NULLIF(COUNT(DISTINCT buyer_id), 0) FROM ("
    "SELECT buyer_id, COUNT(DISTINCT sub_order_id) AS cnt FROM v_order_paid "
    "WHERE pay_time >= '{start}' GROUP BY buyer_id)"
)


def _variant_sql(start: str, *, rate_float: bool, predicates: bool, upper: bool) -> str:
    where = f"pay_time >= '{start}'"
    if upper:
        end = (date.fromisoformat(start) + timedelta(days=90)).isoformat()
        where += f" AND pay_time < '{end}'"
    if predicates:
        where += " AND pay_status = 'paid' AND is_test_order = false"
    num = "COUNT(DISTINCT CASE WHEN cnt >= 2 THEN buyer_id END)"
    if rate_float:
        num += " * 1.0"
    return (
        f"{'SELECT ' if False else ''}"
        f"SELECT {num} / NULLIF(COUNT(DISTINCT buyer_id), 0) FROM ("
        f"SELECT buyer_id, COUNT(DISTINCT sub_order_id) AS cnt FROM v_order_paid "
        f"WHERE {where} GROUP BY buyer_id)"
    )


def build_repurchase(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    b = yaml.safe_load(open(BUNDLE, encoding="utf-8"))
    metric = next(m for m in b["metrics"] if m["name"] == "repurchase_rate_90d")
    cases = []
    for cid, start in (("M-IDX-09", "2026-06-01"), ("M-IDX-10", "2026-03-01")):
        r = records[cid]
        tenant = r.get("tenant") or "T_A"
        variants = {}
        for name, kw in (
            ("v0_gold_as_is", dict(rate_float=False, predicates=False, upper=False)),
            ("v1_float_only", dict(rate_float=True, predicates=False, upper=False)),
            ("v2_float_predicates", dict(rate_float=True, predicates=True, upper=False)),
            ("v3_float_predicates_90d", dict(rate_float=True, predicates=True, upper=True)),
        ):
            sql = _variant_sql(start, **kw)
            res = _sandbox(sql, tenant=tenant)
            value = None
            if res.get("table") is not None and len(res["table"].rows) == 1:
                value = res["table"].rows[0][0]
            variants[name] = {"sql": sql, "value": value, "error": res.get("error")}
        system = None
        if r.get("sql_text"):
            res = _sandbox(r["sql_text"], r.get("sql_params") or {}, tenant=tenant)
            if res.get("table") is not None and len(res["table"].rows) == 1:
                system = res["table"].rows[0][0]
        cases.append({
            "case_id": cid,
            "question": r.get("question"),
            "start": start,
            "gold_sql": (r.get("gold") or {}).get("gold_sql"),
            "system_sql": r.get("sql_text"),
            "system_params": r.get("sql_params"),
            "system_value": system,
            "variants": variants,
        })

    return {
        "provenance": PROVENANCE,
        "task": "W73-4 复购率金标（只出方案；改 gold 属冻结集变更 ⇒ 须总控签）",
        **STAMP,
        "metric_definition": {
            "name": metric["name"],
            "expression": metric.get("expression"),
            "window": metric.get("window"),
            "definition_note": metric.get("definition_note"),
            "default_predicates": metric.get("default_predicates"),
            "time_basis": metric.get("time_basis"),
        },
        "findings": [
            "① **整数除法**：gold 的 `COUNT(...)/COUNT(...)` 两侧都是整数 ⇒ SQLite 与 Postgres "
            "**都**截断为 0（M-IDX-09/10 的 gold 原值实测 0.0）。`* 1.0` 后 M-IDX-09 = "
            "0.1671171171171171（与 QA §94.5 数字一致）。",
            "② **缺少 90 天上界**：`bundle:613` 写 `window: \"90 days\"`，"
            "`definition_note` 也写「周期固定 90 天，不接受运行时改窗口」；但 gold 只有 "
            "`pay_time >= start`，**没有上界** ⇒ M-IDX-10 gold 覆盖 2026-03-01 起的全部历史，"
            "比系统（截至 2026-05-30）大 2.2 倍，差异方向与「窗口缺上界」一致。",
            "③ **默认谓词缺失**：gold 无 `pay_status='paid'` / `is_test_order=false`（D 类一脉），"
            "补上后与系统的差距进一步收窄。",
            "④ **系统自身不一致**：M-IDX-09 的系统 SQL 只有下界、M-IDX-10 有上界 "
            "⇒ 90 天窗口由模型即兴决定，代码里没有任何一处读 `metrics[].window`"
            "（`grep '.window'` 只命中 `planner/engine.py` 的时间解析，与指标窗口无关）。",
        ],
        "proposed_fix": {
            "status": "PROPOSED（未改 gold；冻结集与语义包均未动）",
            "gold_v2": (
                "SELECT COUNT(DISTINCT CASE WHEN cnt >= 2 THEN buyer_id END) * 1.0 "
                "/ NULLIF(COUNT(DISTINCT buyer_id), 0) FROM (SELECT buyer_id, "
                "COUNT(DISTINCT sub_order_id) AS cnt FROM v_order_paid "
                "WHERE pay_time >= '{start}' AND pay_time < '{start+90d}' "
                "AND pay_status = 'paid' AND is_test_order = false GROUP BY buyer_id)"
            ),
            "expected_values": {
                c["case_id"]: {
                    "v3_float_predicates_90d": c["variants"]["v3_float_predicates_90d"]["value"],
                    "system_value": c["system_value"],
                }
                for c in cases
            },
            "code_follow_up": (
                "若要「窗口由指标定义强制」，需在 gen_sql 之后按 `metric.window` 覆写/校验时间窗"
                "（当前无任何代码读该字段）—— 属产品行为变更，另立议题"
            ),
            "sign_required": "改冻结集 gold（2 条）+ 可能改语义包 expected 值 ⇒ 需总控签",
        },
        "cases": cases,
    }


def main() -> None:
    records = {r["case_id"]: r for r in json.load(open(SRC, encoding="utf-8"))["records"]}
    facts = _bundle_facts()
    refusal = build_refusal(records, facts)
    columns = build_columns(records)
    repurchase = build_repurchase(records)

    for doc, path in ((refusal, OUT_REFUSAL), (columns, OUT_COLUMNS), (repurchase, OUT_REPURCHASE)):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)

    print("W73-2 refused_at:", {c["case_id"]: c["refused_at"] for c in refusal["cases"]})
    print("W73-2 blockers:", {c["case_id"]: len(c["planner_blocking_issues"]) for c in refusal["cases"]})
    print("W73-3 shapes:", columns["headline"]["by_shape"], "| families:", columns["headline"]["by_family"])
    print("W73-3 flips name/value:", columns["headline"]["n_flip_if_ignore_extra_by_name"],
          columns["headline"]["n_flip_if_ignore_extra_by_value"])
    print("W73-4:", [(c["case_id"], c["variants"]["v0_gold_as_is"]["value"],
                      c["variants"]["v1_float_only"]["value"],
                      c["variants"]["v3_float_predicates_90d"]["value"],
                      c["system_value"]) for c in repurchase["cases"]])
    print("written:", OUT_REFUSAL, OUT_COLUMNS, OUT_REPURCHASE)


if __name__ == "__main__":
    main()
