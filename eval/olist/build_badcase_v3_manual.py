"""逐例定性 28 条真错题，产出 ``badcase_v3_manual.json``。

只读三批结果件、冻结集与两件反事实探针，所有 case 字段与判定读数都从盘上现取；
人工判定只以 ``CAUSES`` 常量给出「类别 + 错因 + 可修杠杆」，并 fail-closed 断言
其 case_id 集合恰好等于三批里 terminal=complete 且 verdict 不等价的集合。

复算：``python eval/olist/build_badcase_v3_manual.py``
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
OUT = ROOT / "badcase_v3_manual.json"

CAUSES: dict[str, dict[str, str]] = {
    "g01": {"category": "time_semantics", "cause": "2018 GMV：上界写成 <= 2018-12-31T23:59:59", "lever": "param_normalization"},
    "g05": {"category": "time_semantics", "cause": "2018 客单价：上界 <= 2018-12-31T23:59:59", "lever": "param_normalization"},
    "n23": {"category": "time_semantics", "cause": "2018H1 商品销售额：两界均带 T 分隔，字符串比较多算次日", "lever": "param_normalization"},
    "n25": {"category": "time_semantics", "cause": "2017 各州商品销售额：上界 <= 2017-12-31 纯日期，漏掉当日全部数据", "lever": "param_normalization"},
    "n26": {"category": "time_semantics", "cause": "2017H1 运费：两界 T 分隔", "lever": "param_normalization"},
    "n28": {"category": "time_semantics", "cause": "2018 运费 Top5 州：上界 <= 2018-12-31T23:59:59", "lever": "param_normalization"},
    "n29": {"category": "time_semantics", "cause": "2018 运费最低 5 品类：上界 <= 2018-12-31T23:59:59", "lever": "param_normalization"},
    "n30": {"category": "time_semantics", "cause": "2017H1 件数：两界 T 分隔", "lever": "param_normalization"},
    "n33": {"category": "time_semantics", "cause": "2017 件数最少 5 州：两界 T 分隔；另有次排序键但非致错主因", "lever": "param_normalization"},
    "o19": {"category": "time_semantics", "cause": "2017Q4 客单价：上界 <= 2017-12-31 纯日期", "lever": "param_normalization"},
    "o24": {"category": "time_semantics", "cause": "2018 各品类销售额：两界 T 分隔", "lever": "param_normalization"},
    "o30": {"category": "time_semantics", "cause": "2018 运费+销售额：上界 <= 2018-12-31T23:59:59", "lever": "param_normalization"},
    "o31": {"category": "time_semantics", "cause": "2017 件数：上界 <= 2017-12-31 纯日期", "lever": "param_normalization"},
    "o35": {"category": "time_semantics", "cause": "2018 订单量+件数：两界 T 分隔", "lever": "param_normalization"},
    "n03": {"category": "metric_definition", "cause": "2016H2 GMV 被写成 AOV 的 SUM/NULLIF(COUNT DISTINCT) 除法式，别名仍叫 gmv", "lever": "prompt_or_voting"},
    "o05": {"category": "metric_definition", "cause": "2017Q4 GMV 被写成 AOV 除法式、别名 aov，列无法配对", "lever": "prompt_or_voting"},
    "n35": {"category": "schema_linking_miss", "cause": "2017Q4 平均评分：gold 只用 review 表按 review_creation_date；预测多 JOIN orders 并改用 order_purchase_timestamp", "lever": "prompt_or_voting"},
    "n37": {"category": "schema_linking_miss", "cause": "2018 评分最高 5 州：时间基准列误用 order_purchase_timestamp，并多加订单状态过滤", "lever": "prompt_or_voting"},
    "o38": {"category": "schema_linking_miss", "cause": "2018 各州平均评分：时间基准列误用 order_purchase_timestamp，且别名/排序与 gold 不一致", "lever": "prompt_or_voting"},
}


def main() -> None:
    ds = json.loads((ROOT / "dataset_v3_frozen.json").read_text(encoding="utf-8"))
    gold = {c["case_id"]: c for c in ds["cases"]}
    gain = json.loads((ROOT / "param_gain_probe.json").read_text(encoding="utf-8"))
    gain_index: dict[tuple[str, str], dict[str, Any]] = {
        (r["batch"], r["case_id"]): r for r in gain["records"]
    }

    records: list[dict[str, Any]] = []
    old_attr = collections.Counter()
    for i in (1, 2, 3):
        batch = f"r{i}"
        for r in json.loads((ROOT / f"results_v3_r{i}.json").read_text(encoding="utf-8"))["records"]:
            if r.get("expected_behavior") != "execute":
                continue
            old = (r.get("attribution") or {}).get("category") or "NULL"
            old_attr[old] += 1
            if (r.get("verdict") or {}).get("equivalent") or r.get("terminal_event") != "complete":
                continue
            cid = r["case_id"]
            if cid not in CAUSES:
                raise SystemExit("MISSING MANUAL CAUSE: " + cid)
            c = CAUSES[cid]
            g = gain_index.get((batch, cid))
            records.append({
                "batch": batch,
                "case_id": cid,
                "question": r["question"],
                "difficulty_struct": r.get("difficulty_struct"),
                "difficulty_semantic": r.get("difficulty_semantic"),
                "category_manual": c["category"],
                "cause_manual": c["cause"],
                "fix_lever": c["lever"],
                "category_machine_old": old,
                "business_knowledge_required": gold[cid].get("business_knowledge_required"),
                "caliber_note": gold[cid].get("caliber_note"),
                "params_original": r.get("sql_params"),
                "verdict_diffs": (r.get("verdict") or {}).get("diffs"),
                "param_normalization_recovered": bool(g and g.get("normalized_equivalent")),
                "evidence": {
                    "gold_sql": "eval/olist/dataset_v3_frozen.json cases[" + cid + "].gold_sql",
                    "pred_sql": f"eval/olist/results_v3_r{i}.json records[{cid}].sql_text",
                    "counterfactual": "eval/olist/param_gain_probe.json",
                    "time_shape": "eval/olist/time_shape_probe.json",
                },
            })

    seen = {r["case_id"] for r in records}
    if seen != set(CAUSES):
        raise SystemExit("CAUSE SET MISMATCH: " + str(set(CAUSES) ^ seen))
    if len(records) != 28:
        raise SystemExit("EXPECTED 28 RECORDS, GOT " + str(len(records)))

    by_cat = collections.Counter(r["category_manual"] for r in records)
    by_lever = collections.Counter(r["fix_lever"] for r in records)
    n_old_unattributed = old_attr["unattributed"]
    n_recovered_unattributed = sum(
        1 for r in records if r["category_machine_old"] == "unattributed"
    )
    remaining = n_old_unattributed - n_recovered_unattributed
    denom = sum(old_attr.values())
    payload = {
        "schema": "U183_BADCASE_V3_MANUAL/v1",
        "builder": "eval/olist/build_badcase_v3_manual.py",
        "recompute": "python eval/olist/build_badcase_v3_manual.py",
        "n_records": len(records),
        "n_unique_cases": len(seen),
        "categories": dict(by_cat),
        "fix_levers": dict(by_lever),
        "unattributed_before": {"n": n_old_unattributed, "denom": denom,
                                "ratio": round(n_old_unattributed / denom, 4)},
        "unattributed_after": {"n": remaining, "denom": denom,
                               "ratio": round(remaining / denom, 4),
                               "gate": "eval/attribution.py:16 要求 <= 10%"},
        "counterfactual": {
            "probe": "eval/olist/probe_u183_param_gain.py",
            "n_recovered": gain["n_recovered_by_param_normalization"],
            "n_still_wrong": gain["n_still_wrong"],
            "rule": gain["rule"],
        },
        "records": records,
        "verdict": "28 条真错题全部落人工类别；20 条为时间参数形态（确定性、可 replay 验证），8 条需改 prompt 或候选投票",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", OUT.name, "n", len(records), "unique", len(seen))
    print("CATEGORIES", dict(by_cat), "LEVERS", dict(by_lever))
    print("UNATTRIBUTED", n_old_unattributed, "->", remaining,
          "ratio", round(n_old_unattributed / denom, 4), "->", round(remaining / denom, 4))


if __name__ == "__main__":
    main()
