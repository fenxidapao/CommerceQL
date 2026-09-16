#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
few-shot Gold Query 种子生成器（供后续 L3 绑定层 / W3 使用）

归属窗口：W1A（eval/**）

为什么从冻结集**派生**而不是另写一份
------------------------------------
Gold Query 种子与冻结集是同一批 SQL 的两种视图。另写一份 = 第二份真相，
两边迟早漂移（U-18 形态）。→ 本脚本只做**选择 + 投影**，不新增任何 SQL 文本。

选择规则（确定性）
------------------
1. 只取 `expected_behavior == execute` 且有 `gold_result_hash` 的用例
2. 按 `gold_sql` 去重（同一 SQL 不问法只留一条）
3. 保证：**每个「指标」至少 2 条**、**每个 4×3 格子至少 1 条**（缺则不补齐、如实报告）
4. 排序键 = (指标, 结构级, 语义级, case_id)，输出顺序稳定

⚠️ 种子**不是答案库**：它只用于给 L3 绑定层提供少样本示例。
   注意 07 的纪律 —— few-shot 示例**不得**绕过闸门（示例里的 SQL 同样要过守卫）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATASET = os.path.join(HERE, "dataset_v1_frozen.json")
OUT = os.path.join(HERE, "gold_query_seed_v1.json")

METRIC_TAGS = ("gmv", "order_cnt", "aov", "arpu", "refund_rate", "repurchase_rate_90d",
               "uv", "pay_cvr")


def metric_of(case: dict) -> str:
    for t in case.get("business_knowledge_required") or []:
        if t.startswith("metric:") and t.split(":", 1)[1] in METRIC_TAGS:
            return t.split(":", 1)[1]
    return "(none)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="few-shot Gold Query 种子生成器")
    ap.add_argument("--check", action="store_true", help="只校验是否漂移")
    args = ap.parse_args(argv)

    ds = json.load(open(DATASET, encoding="utf-8"))
    cases = [c for c in ds["cases"]
             if c["expected_behavior"] == "execute" and c.get("gold_sql")]

    # 去重（同一 SQL 只留一条，保留 case_id 最小者）
    by_sql: dict[str, dict] = {}
    for c in sorted(cases, key=lambda x: x["case_id"]):
        by_sql.setdefault(c["gold_sql"], c)
    uniq = list(by_sql.values())

    # 覆盖面报告
    # ⚠️ 必须**分两套计数**：
    #   · per_metric_frozen —— 冻结集里该指标有几条用例（**去重前**）→ 覆盖度看这个
    #   · per_metric_seed   —— 去重后剩几条种子 → 种子库看这个
    #   若只看后者会误报：两条用例仅"租户不同"，而租户不在 gold_sql 里
    #   （由执行层注入），去重后必然并成 1 条 —— 那是**正确行为**，不是覆盖缺口。
    per_metric_frozen: dict[str, int] = {}
    for c in cases:
        per_metric_frozen[metric_of(c)] = per_metric_frozen.get(metric_of(c), 0) + 1
    per_metric: dict[str, int] = {}
    for c in uniq:
        per_metric[metric_of(c)] = per_metric.get(metric_of(c), 0) + 1
    per_cell: dict[str, int] = {}
    for c in uniq:
        k = f"{c['difficulty_struct']}×{c['difficulty_semantic']}"
        per_cell[k] = per_cell.get(k, 0) + 1

    thin_metrics = [m for m in METRIC_TAGS if per_metric_frozen.get(m, 0) < 2]
    missing_cells = [f"{a}×{b}" for a in ("easy", "medium", "hard", "extra")
                     for b in ("low", "medium", "high")
                     if per_cell.get(f"{a}×{b}", 0) < 1]

    seeds = [{
        "seed_id": f"GQ-{i + 1:03d}",
        "source_case_id": c["case_id"],
        "question": c["question"],
        "gold_sql": c["gold_sql"],
        "metric": metric_of(c),
        "domain": c["domain"],
        "difficulty_struct": c["difficulty_struct"],
        "difficulty_semantic": c["difficulty_semantic"],
        "business_knowledge_required": c["business_knowledge_required"],
        "must_contain": c["must_contain"],
        "must_not_contain": c["must_not_contain"],
        "notes": c["notes"],
    } for i, c in enumerate(sorted(
        uniq, key=lambda x: (metric_of(x) == "(none)", metric_of(x),
                             x["difficulty_struct"], x["difficulty_semantic"], x["case_id"])))]

    payload = {
        "seed_version": "1",
        "derived_from": "eval/dataset_v1_frozen.json",
        "derived_from_content_hash": ds["content_hash"],
        "policy": "从冻结集派生（不新增 SQL 文本）；同一 gold_sql 只保留一条",
        "coverage": {
            "unique_sql": len(uniq),
            "per_metric_frozen_set": per_metric_frozen,
            "per_metric_seed": per_metric,
            "per_cell": per_cell,
            "metrics_with_fewer_than_2_in_frozen_set": thin_metrics,
            "cells_with_no_seed": missing_cells,
        },
        "warning": "few-shot 示例**不得绕过闸门** —— 示例 SQL 同样要过 W4 守卫（07 纪律）",
    }
    chash = hashlib.sha256(json.dumps(
        [{k: s[k] for k in ("source_case_id", "question", "gold_sql", "metric")} for s in seeds],
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["content_hash"] = "sha256:" + chash

    print(f"Gold Query 种子 {len(seeds)} 条（唯一 SQL {len(uniq)} / 冻结集可复用 {len(cases)}）")
    print(f"冻结集每指标条数：{per_metric_frozen}")
    print(f"种子每指标条数：{per_metric}")
    print(f"每格种子条数：{per_cell}")
    if thin_metrics:
        print(f"  [WARN] **冻结集里**不足 2 条的指标：{thin_metrics}", file=sys.stderr)
    if missing_cells:
        print(f"  [WARN] 无种子的格子：{missing_cells}", file=sys.stderr)

    if args.check:
        old = json.load(open(OUT, encoding="utf-8"))
        if old.get("content_hash") != payload["content_hash"] \
                or old.get("derived_from_content_hash") != ds["content_hash"]:
            print("[FAIL] 种子与冻结集不同步", file=sys.stderr)
            return 1
        print("[OK] 种子与冻结集同步")
        return 0

    payload["seeds"] = seeds
    # 让 content_hash 排在前面：先写 seeds 再落盘（上面已算 hash）
    json.dump(payload, open(OUT, "w", encoding="utf-8", newline="\n"),
              ensure_ascii=False, indent=2)
    print(f"[OK] written {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
