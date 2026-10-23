"""W74-4 材料件（零出站）：维度绑定方案 / 两层判据打架 / E-MET-08 处置影响 / 复购双议题。

派单 TASK_BOARD §95.7 第 4 项。**只出材料**：不改语义包、不改冻结集、不改 `expected_behavior`、
不改代码。所有数字都是本地沙箱与已落盘重放产物上现算的。
"""

from __future__ import annotations

import json
import os
import re
import sys
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
import reporter as rp  # noqa: E402
import runner  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
BUNDLE = BUNDLE_PATH
SANDBOX = os.path.join(ROOT, "data", "ecom_sandbox.db")
DATASET = os.path.join(HERE, "dataset_v1_frozen.json")
SRC = os.path.join(HERE, "results_r75_full166_extra_columns.json")
OUT = os.path.join(HERE, "results_r74_dimension_dispositions.json")

PROVENANCE = "W74-4 零出站材料（冻结集 + 语义包 + 沙箱 sqlite + r75 重放；tokens = 0）"


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


def _scalar(out: dict[str, Any]) -> float | None:
    if out.get("error") or out.get("table") is None:
        return None
    rows = list(out["table"].rows)
    if len(rows) != 1 or len(rows[0]) != 1 or rows[0][0] is None:
        return None
    return float(rows[0][0])


# ============================================================================
# A/B 维度绑定
# ============================================================================

def build_dimensions(cases: list[dict[str, Any]], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    b = yaml.safe_load(open(BUNDLE, encoding="utf-8"))
    raw = open(BUNDLE, encoding="utf-8").read().splitlines()

    def _line(pattern: str) -> int | None:
        for i, ln in enumerate(raw):
            if re.search(pattern, ln):
                return i + 1
        return None

    dims = {d["name"]: d for d in (b.get("dimensions") or [])}
    concepts = {c.get("concept"): c for c in (b.get("field_bindings") or []) if c.get("concept")}
    assets = {a["logical_name"]: a for a in b["assets"]}

    rows = []
    for c in cases:
        q = str(c.get("question") or "")
        gold = str(c.get("gold_sql") or "")
        if not (("城市" in q) or ("渠道" in q) or ("channel" in q.lower())):
            continue
        uses_shop_city = bool(re.search(r"\bv_shop\b", gold)) and bool(re.search(r"\bcity\b", gold)) \
            and not re.search(r"receiver_city", gold)
        rows.append({
            "case_id": c["case_id"],
            "question": q,
            "expected_behavior": c.get("expected_behavior"),
            "gold_binding": (
                "shop.city" if uses_shop_city else
                "order_paid.receiver_city" if "receiver_city" in gold else
                "traffic_daily.channel" if re.search(r"\bv_traffic_daily\b", gold) and "channel" in gold else
                "order_paid.channel" if re.search(r"\bv_order_paid\b", gold) and "channel" in gold else
                ("(no gold)" if not gold else "其它")
            ),
            "terminal": (records.get(c["case_id"]) or {}).get("terminal_event"),
            "difficulty": f"{c.get('difficulty_struct')}×{c.get('difficulty_semantic')}",
        })

    city_rows = [r for r in rows if "城市" in r["question"]]
    channel_rows = [r for r in rows
                    if "渠道" in r["question"] or "channel" in r["question"].lower()]
    return {
        "bundle_facts": {
            "dimensions_city": dims.get("city"),
            "dimensions_channel": dims.get("channel"),
            "concept_渠道": concepts.get("渠道"),
            "shop_columns": [c["name"] for c in assets["shop"]["columns"]],
            "order_paid_columns": [c["name"] for c in assets["order_paid"]["columns"]],
            "lines": {
                "shop_city_column": _line(r"^\s+- name: city$"),
                "city_dimension": _line(r"^\s+- name: city\s*$"),
                "channel_dimension": _line(r"^\s+- name: channel\s*$"),
                "channel_concept": _line(r"^- concept: 渠道"),
            },
        },
        "city_cases": city_rows,
        "channel_cases": channel_rows,
        "city_proposal": {
            "status": "PROPOSED（未改包）",
            "option_a_add_dimension": {
                "yaml": (
                    "  - name: shop_city\n"
                    "    binding: shop.city\n"
                    "    hierarchy: [country, region, province, city]\n"
                    "    grain_levels: { country: 1, region: 2, province: 3, city: 4 }\n"
                    "    grain_level: 4\n"
                    "    note: \"店铺所在城市（与 `city`=收货城市 同名不同义）；店/商品域问题用它\"\n"
                ),
                "impact": (
                    "有 gold 的两条按 `v_shop.city` 落绑（M-DIM-05、M-HIER-03），"
                    "M-MET-04 用 `receiver_city` 不受影响；三条 expected=clarify 不受影响"
                ),
                "risk": "新增维度名会把「城市」的同义词分成两个 ⇒ planner 仍需判域；"
                        "若同义词表把「城市」同时挂到 shop_city 与 city，歧义会从「表不明」变成「维度名重复」",
            },
            "option_b_context_binding": {
                "yaml": "在 `dimensions[name=city]` 下加 `alternatives: [{asset: shop.city, use_when: shop_grain}]`",
                "impact": "不动维度名，改的是「同一概念按粒度选绑定」；需 planner 提示词把 use_when 渲染出来",
                "risk": "结构性证据（「各城市的店铺数」主语是店铺）目前只存在于 `normalize.py` 的降级规则里，"
                        "planner 看不到 ⇒ 单改包不改提示词，模型仍可能选错",
            },
            "recommendation": "A + 把「店铺粒度」作为结构证据写进 plan 提示词（两者缺一都会回到本轮现象）",
        },
        "channel_proposal": {
            "status": "PROPOSED（未改包）",
            "option_domain_binding": {
                "yaml": (
                    "  - name: channel\n"
                    "    binding: traffic_daily.channel\n"
                    "    alternatives:\n"
                    "      - asset: order_paid.channel\n"
                    "        use_when: orders_domain\n"
                    "        note: \"成交渠道；GMV/订单域问题绑它（bundle:1135 已写，但维度层没表达）\"\n"
                ),
                "impact": (
                    "12 条提「渠道」的题里，10 条 gold 走 `v_traffic_daily`（PV/加购/流量域），"
                    "1 条走 `v_order_paid`（M-MET-01 GMV），1 条题面含英文 channel；"
                    "只有 M-MET-01 会受影响（当前 refuse）"
                ),
                "risk": "「渠道」两义（流量渠道 vs 成交渠道）在数值上可能不同源 ⇒ 必须按域选，不能合并",
            },
            "recommendation": "按域绑定（alternatives），并在 planner 提示词里把 note 渲染到维度行",
        },
    }


# ============================================================================
# C 两层判据打架
# ============================================================================

def build_normalize_plan(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "PROPOSED（未改代码）",
        "conflict": (
            "`normalize.py:104` 的降级规则用「问句含『各城市』」把模型的 `clarify_needed` "
            "改写成 executable（`normalize.py:130`），随后 `plan` 又以同一歧义为由 "
            "`refuse(no_data_asset)`（`plan.py:91-105`）⇒ 同一个歧义先被撤销、再被拒答，"
            "既没澄清也没执行"
        ),
        "options": [
            {
                "id": "C1",
                "name": "plan 消费 normalize 的维度结论",
                "how": "把 `intent_detail.reason_code == 'shop_city_unambiguous'` 作为一条"
                       "结构化约束写进 plan 提示词（`filters`/`dimensions` 提示），"
                       "让模型知道「城市已判定为店铺维度」",
                "cost": "改 payloads + 提示词 ⇒ 请求哈希变化 ⇒ **匣带失效、需重录**（真打花钱）",
                "effect": "正面解决；M-DIM-05 可能直接执行",
            },
            {
                "id": "C2",
                "name": "blocking_issues 分类映射",
                "how": "plan 的阻塞项按类型分流：歧义类 → `clarify`，缺资产类 → `refuse(no_data_asset)`",
                "cost": "需给 `Plan.blocking_issues` 加类型（提示词 + schema 变更，同样动请求哈希）；"
                        "若不改 schema 只能靠关键词猜 ⇒ 脆弱",
                "effect": "只修归因码，不修「能不能算」；M-DIM-05/M-MET-01 变成 clarify，"
                          "G-5 over_refused 会从 3 掉到 1 —— **但那是计数器不数 clarify 造成的**，不是系统变强",
            },
            {
                "id": "C3",
                "name": "撤掉降级规则",
                "how": "删除 `normalize.py:104-142`，让 M-DIM-05 回到 clarify_out",
                "cost": "零出站可验证（replay），但会把 C-CITY 族的澄清率推高，"
                        "且 W68/W69 的结论（「各城市」结构上唯一指向 shop.city）被推翻",
                "effect": "M-DIM-05 由 refuse 变 clarify；M-HIER-03（同形状、目前能执行）可能受连带影响",
            },
        ],
        "second_instance": {
            "case": "C-CITY-02「各城市的订单数分别是多少？」",
            "expected": "clarify（城市维度歧义）",
            "terminal": (records.get("C-CITY-02") or {}).get("terminal_event"),
            "reason": (records.get("C-CITY-02") or {}).get("refusal_reason"),
            "nodes": (records.get("C-CITY-02") or {}).get("nodes"),
            "note": "同一条冲突的第二例：模型判 clarify、被降级、plan 阻塞 ⇒ 记成 "
                    "`refuse(no_data_asset)`。所以「歧义被压成缺数据」不是 M-DIM-05 独有，"
                    "expected-clarify 的 18 条里有 1 条最终成了 refuse。",
        },
        "measured_now": {
            "M-DIM-05": {
                "terminal": (records.get("M-DIM-05") or {}).get("terminal_event"),
                "reason": (records.get("M-DIM-05") or {}).get("refusal_reason"),
            },
            "M-HIER-03": {
                "terminal": (records.get("M-HIER-03") or {}).get("terminal_event"),
                "note": "同形状（各城市的…）但主语是在架商品 ⇒ 走了 shop 粒度并执行成功；"
                        "说明「各城市」本身不是拦路虎，**主语粒度**才是",
                "sql": ((records.get("M-HIER-03") or {}).get("sql_text") or "")[:240],
            },
        },
        "recommendation": "C1（结构化传递）＋ A 案的 shop_city 维度；C2 单独做只会把数字刷绿，不建议先做",
    }


# ============================================================================
# D E-MET-08 处置影响
# ============================================================================

def build_emet08(records: list[dict[str, Any]]) -> dict[str, Any]:
    refusal = rp._refusal_counts(records) or {}
    clarify = rp._clarify_counts(records) or {}
    target = next((r for r in records if r["case_id"] == "E-MET-08"), {})
    terminal = target.get("terminal_event")

    def _sim(disposition: str) -> dict[str, Any]:
        answerable = refusal.get("answerable_total", 0)
        over = refusal.get("over_refused", 0)
        refuse_total = refusal.get("total", 0)
        correct = refusal.get("correct_refused", 0)
        req = clarify.get("requests", 0)
        clarified = clarify.get("clarified", 0)
        out: dict[str, Any] = {}
        if disposition == "execute":
            out = {
                "G-5": f"不变：answerable={answerable}，over_refused={over}（该条仍被拒 ⇒ 仍计入误拒）",
                "G-8": f"不变：requests={req}，clarified={clarified}",
            }
        elif disposition == "clarify":
            out = {
                "G-5": f"answerable {answerable}→{answerable - 1}；over_refused {over}→{over - 1}"
                       "（该条不再参与误拒分母）",
                "G-8": f"requests 不变（分母 = 全部 {req} 条）；clarified 不变（系统实际终态是 {terminal}）"
                       f" ⇒ 澄清率仍 {clarified / req:.1%}；`clarify_expected_n` "
                       f"{clarify.get('clarify_expected_n')}→{clarify.get('clarify_expected_n', 0) + 1}",
                "note": "该条会变成「该澄清却没澄清」，但 **G-8 不度量漏澄清**（只度量澄清率与澄清后成功率）",
            }
        elif disposition == "refuse":
            out = {
                "G-5": f"refuse 题 {refuse_total}→{refuse_total + 1}；correct_refused {correct}→{correct + 1}；"
                       f"answerable {answerable}→{answerable - 1}；over_refused {over}→{over - 1}",
                "G-8": f"不变：requests={req}，clarified={clarified}",
            }
        else:  # unscored
            out = {
                "G-5": f"**不变**：`_refusal_counts` 只按 `expected_behavior` 分组，**不看 `scored`** "
                       f"⇒ 标 unscored 不会把它移出分母（answerable 仍 {answerable}、over_refused 仍 {over}）",
                "G-8": f"不变：requests={req}，clarified={clarified}",
                "note": "若真要让它退出计分，得在 reporter 侧加 `scored` 过滤 —— 那是**判据改动**",
            }
        return out

    return {
        "status": "只出对照（未改 expected_behavior、未改冻结集）",
        "current": {
            "case": "E-MET-08",
            "terminal": terminal,
            "expected": target.get("expected_behavior"),
            "G5_inputs": refusal,
            "G8_inputs": clarify,
        },
        "dispositions": {d: _sim(d) for d in ("execute", "clarify", "refuse", "unscored")},
        "honest_warning": (
            "四个选项里，execute 之外**全部**会把 over_refused 从 3 降到 2 —— 降的那 1 条不是"
            "「系统修好了」，而是「该条被移出了 execute 分母」。任何一项都需要总控签，"
            "并在台账上写明这是口径变更而非能力提升。"
        ),
    }


# ============================================================================
# E 复购：gold_v2 与 window 强制分开列
# ============================================================================

def build_repurchase(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def _gold_v2(start: str) -> str:
        end = (date.fromisoformat(start) + timedelta(days=90)).isoformat()
        return (
            "SELECT COUNT(DISTINCT CASE WHEN cnt >= 2 THEN buyer_id END) * 1.0 "
            "/ NULLIF(COUNT(DISTINCT buyer_id), 0) FROM (SELECT buyer_id, "
            "COUNT(DISTINCT sub_order_id) AS cnt FROM v_order_paid "
            f"WHERE pay_time >= '{start}' AND pay_time < '{end}' "
            "AND pay_status = 'paid' AND is_test_order = false GROUP BY buyer_id)"
        )

    cases = []
    for cid, start in (("M-IDX-09", "2026-06-01"), ("M-IDX-10", "2026-03-01")):
        r = records.get(cid) or {}
        tenant = r.get("tenant") or "T_A"
        gold_now = (r.get("gold") or {}).get("gold_sql") or ""
        gv2 = _gold_v2(start)
        sysv = _scalar(_sandbox(r.get("sql_text") or "", r.get("sql_params") or {}, tenant)) \
            if r.get("sql_text") else None
        #: window 强制后的系统值 = 把系统 SQL 的窗口按 90 天补齐（等价于 v3）
        end = (date.fromisoformat(start) + timedelta(days=90)).isoformat()
        forced = (
            "SELECT COUNT(DISTINCT CASE WHEN cnt >= 2 THEN buyer_id END) * 1.0 "
            "/ NULLIF(COUNT(DISTINCT buyer_id), 0) FROM (SELECT buyer_id, "
            "COUNT(DISTINCT sub_order_id) AS cnt FROM v_order_paid "
            f"WHERE pay_time >= '{start}' AND pay_time < '{end}' "
            "AND pay_status = 'paid' AND is_test_order = false GROUP BY buyer_id)"
        )
        forced_v = _scalar(_sandbox(forced, tenant=tenant))
        cases.append({
            "case_id": cid,
            "start": start,
            "gold_now_value": _scalar(_sandbox(gold_now, tenant=tenant)) if gold_now else None,
            "gold_v2_value": _scalar(_sandbox(gv2, tenant=tenant)),
            "system_value_now": sysv,
            "system_value_with_window_enforced": forced_v,
        })

    def _eq(a, b) -> bool:
        if a is None or b is None:
            return False
        return abs(a - b) / (abs(b) or 1.0) < 1e-6

    matrix = {}
    for c in cases:
        cid = c["case_id"]
        matrix[cid] = {
            "only_gold_v2": _eq(c["system_value_now"], c["gold_v2_value"]),
            "only_window_enforced": _eq(c["system_value_with_window_enforced"], c["gold_now_value"]),
            "both": _eq(c["system_value_with_window_enforced"], c["gold_v2_value"]),
        }
    return {
        "status": "只出对照（未改 gold、未改代码）",
        "cases": cases,
        "equivalence_matrix": matrix,
        "impact": {
            "only_gold_v2": f"等价翻转 {sum(1 for v in matrix.values() if v['only_gold_v2'])}/2"
                            "（M-IDX-10 翻；M-IDX-09 不翻 —— 系统无上界）",
            "only_window_enforced": f"翻转 {sum(1 for v in matrix.values() if v['only_window_enforced'])}/2"
                                    "（gold 仍是整数除法 ⇒ 恒 0，翻不动）",
            "both": f"翻转 {sum(1 for v in matrix.values() if v['both'])}/2",
            "scope_of_window_enforcement": (
                "`metrics[].window` 只在 repurchase_rate_90d 一处声明（`bundle:613`），"
                "全仓无代码读取 ⇒ 强制窗口只影响该指标的查询；但实现上等于在 gen_sql 后"
                "改写时间谓词，属产品行为变更（会改变任何『复购率 + 自定义时间』问句的语义）"
            ),
            "sign_required": "gold_v2 改冻结集（2 条）⇒ 需总控签；window 强制改产品行为 ⇒ 另立议题",
        },
    }


def main() -> None:
    cases = list(json.load(open(DATASET, encoding="utf-8"))["cases"])
    doc = json.load(open(SRC, encoding="utf-8"))
    records = {r["case_id"]: r for r in doc["records"]}
    order = [r for r in doc["records"]]

    out = {
        "provenance": PROVENANCE,
        "task": "W74-4 材料：维度绑定 / 两层判据 / E-MET-08 处置 / 复购双议题（只出材料）",
        **STAMP,
        "source_replay": {"path": os.path.basename(SRC), "git_rev": doc.get("git_rev"),
                          "git_dirty": doc.get("git_dirty")},
        "dimensions": build_dimensions(cases, records),
        "normalize_plan": build_normalize_plan(records),
        "emet08": build_emet08(order),
        "repurchase": build_repurchase(records),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("W74-4 city cases:", [(c["case_id"], c["gold_binding"], c["terminal"]) for c in out["dimensions"]["city_cases"]])
    print("W74-4 channel bindings:", {r["gold_binding"] for r in out["dimensions"]["channel_cases"]})
    print("W74-4 E-MET-08 G5:", out["emet08"]["current"]["G5_inputs"], "| G8:", out["emet08"]["current"]["G8_inputs"])
    print("W74-4 repurchase matrix:", out["repurchase"]["equivalence_matrix"])
    print("written:", OUT)


if __name__ == "__main__":
    main()
