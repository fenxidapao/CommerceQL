"""W6 探针：冻结集题面所需的"指标"有多少**根本不在语义包指标目录里**。

为什么测这个（不是"找茬"，是 EX 解释口径的地基）：
    本会话真打批次 5 条里有 3 条收口成 `refuse(no_data_asset)`，1 条 `clarify`，只有 1 条
    走到了 SQL。若直接把这些计入 EX 分母，报告会长成"模型准确率 20%"—— 而实际发生的是
    `app/planner/payloads.py::_METRIC_GAP_NOTE` 要求模型"指标找不到就别自己发明，写进
    `blocking_issues`"。模型**照做了**，出口节点把 `blocking_issues` 收口成拒答。
    ⇒ 这是"评测集要的东西目录里没有"，不是模型能力。

    ⚠️ 纪律：本探针只给**题面词形**层面的静态判据（可复算、进 CI），
    不声称这是模型内部实际读到的候选集 —— 那需要重放 prompt（成本 + 归属越界）。
    两条判据一起看：`blocking_issues` 出现在匣带里 = 模型自述的直接证据（抽样人工核对）。

为什么判据用 `metric.name ∪ synonyms ∪ alias_index(metric)`：
    前两者是 `app/semantics/runtime.py::_metrics` 的键（`Metric.name`），
    别名索引是 `_alias_index`（`resolve_alias` 的查法）—— 即**运行时真能查到的那些词**。
    业务别名（"销售额"→gmv 之类）只有挂在 alias_index 上才算可达，所以必须并进来。

跑法（CommerceQL 根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_metric_coverage.py
产物：同目录 `probe_metric_coverage.json`
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

#: "这道题在要一个聚合指标吗"的静态判据（gold_sql 里出现聚合 = 要数）。
_AGG_RE = re.compile(r"\b(SUM|COUNT|AVG|MAX|MIN|STDDEV|VARIANCE)\s*\(", re.I)


def metric_terms(loaded, runtime) -> dict[str, list[str]]:
    """指标名 → 该指标在运行时**可达**的全部词形（name + synonyms + 别名索引项）。"""
    terms: dict[str, set[str]] = {}
    for metric in loaded.bundle.metrics:
        name = str(metric.name)
        bag = terms.setdefault(name, set())
        bag.add(name)
        bag.update(str(s) for s in (metric.synonyms or ()))
        bag.add(str(getattr(metric, "display_name", "") or ""))
    # 别名索引：maps_to_ref 指到指标名的 surface 词（resolve_alias 的口径）
    alias_index = getattr(runtime, "_alias_index", {}) or {}
    for surface, alias in alias_index.items():
        if str(getattr(alias, "maps_to_kind", "")) == "metric":
            ref = str(getattr(alias, "maps_to_ref", ""))
            terms.setdefault(ref, set()).add(str(surface))
    return {k: sorted(x for x in v if x) for k, v in sorted(terms.items())}


def main() -> int:
    loaded = load_bundle(_bootstrap.BUNDLE_PATH)
    runtime = SemanticBundleRuntime(loaded)
    terms = metric_terms(loaded, runtime)
    active = {
        str(m.name) for m in loaded.bundle.metrics
        if runtime.is_metric_active(str(m.name))
    }
    flat = sorted({t for group in terms.values() for t in group})

    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    cases = list(dataset["cases"])
    hit: dict[str, list[str]] = {}
    miss: list[dict[str, object]] = []
    for case in cases:
        question = str(case.get("question") or "")
        gold = str(case.get("gold_sql") or "")
        wants_agg = bool(_AGG_RE.search(gold))
        found = [t for t in flat if t and t in question]
        if found:
            hit.setdefault(str(case["case_id"]), found)
        elif wants_agg:
            miss.append(
                {
                    "case_id": case["case_id"],
                    "question": question,
                    "expected_behavior": case.get("expected_behavior"),
                    "difficulty_struct": case.get("difficulty_struct"),
                    "difficulty_semantic": case.get("difficulty_semantic"),
                    "gold_agg": _AGG_RE.search(gold).group(1).upper(),
                }
            )
    execute_miss = [m for m in miss if m["expected_behavior"] == "execute"]

    out = {
        "metrics_in_bundle": sorted(terms),
        "active_metrics": sorted(active),
        "reachable_terms": flat,
        "n_cases": len(cases),
        "n_question_hits_metric_term": len(hit),
        "n_agg_gold_sql_without_metric_term": len(miss),
        "n_execute_agg_without_metric_term": len(execute_miss),
        "execute_miss_share": round(len(execute_miss) / max(1, len(cases)), 4),
        "execute_miss": execute_miss,
        "caveat": (
            "题面词形未命中 ≠ 模型一定拿不到该指标（normalize/intent 可能把黑话归一到 name）。"
            "本探针给的是**上界口径**：这些题面里没有任何一个运行时可达的指标词形，"
            "因此`_METRIC_GAP_NOTE` 指示模型写 blocking_issues 的概率极高 —— "
            "已用匣带里模型自述的 blocking_issues 抽样核对（见 reports/w6/live_batch2.log）。"
        ),
    }
    path = os.path.join(HERE, "probe_metric_coverage.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"指标目录 {len(out['metrics_in_bundle'])} 条 / active {len(out['active_metrics'])} "
          f"/ 可达词形 {len(flat)} 个")
    print(f"题面命中指标词形        : {out['n_question_hits_metric_term']}/{out['n_cases']}")
    print(f"gold 有聚合但题面无指标词: {out['n_agg_gold_sql_without_metric_term']}"
          f"（其中期望 execute {out['n_execute_agg_without_metric_term']} 条，"
          f"占全集 {out['execute_miss_share']:.2%}）")
    print("样例:", json.dumps(out["execute_miss"][:6], ensure_ascii=False))
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
