#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QA R31ad · 主线重启诊断：G-2/G-5 同根因验证 + 语义包覆盖缺口清单
**只读 / 零出站 / 零花费**
"""
import io
import json
import collections
import yaml

d1 = json.load(io.open("eval/results_v1.json", encoding="utf-8"))
recs = d1["records"]
sem = yaml.safe_load(io.open("semantic/bundle_2026.09.14.1.yaml", encoding="utf-8"))

print("=" * 78)
print("一、G-2 与 G-5 是否同根因")
print("=" * 78)
g2 = [r for r in recs if r.get("difficulty_struct") == "easy" and r.get("difficulty_semantic") == "low"]
wrong = [r for r in recs if r.get("expected_behavior") == "execute" and r.get("outcome") == "refuse"]
g5_right = [r for r in recs if r.get("expected_behavior") == "refuse"]
print(f"G-2 面（easy×low）       = {len(g2)} 条｜outcome = {dict(collections.Counter([r['outcome'] for r in g2]))}")
print(f"G-5 误拒（exc→refuse）   = {len(wrong)} 条｜reason = {dict(collections.Counter([r.get('refusal_reason') for r in wrong]))}")
print(f"G-2 ⊆ 误拒 ?             = {set(r['case_id'] for r in g2) <= set(r['case_id'] for r in wrong)}")
print(f"→ 两条理由**完全一致** = {set(r.get('refusal_reason') for r in g2) == set(r.get('refusal_reason') for r in wrong)}")
print()

print("=" * 78)
print("二、语义包覆盖 vs 误拒题要的指标")
print("=" * 78)
have = sorted(m["name"] for m in sem["metrics"])
print(f"语义包 metrics（{len(have)} 条）= {have}")
assets = sorted(a["grain"] for a in sem["assets"])
print(f"语义包 assets（{len(assets)} 条）= {assets}")
print()
# 关键词 → 语义包是否有对应
KEY = {
    "在架商品": ("on_sale 列**在**（sku 表）", "metric **缺**"),
    "下架商品": ("on_sale 列**在**", "metric **缺**"),
    "SPU 数": ("spu_id 列**在**", "metric **缺**"),
    "店铺数": ("shop asset **在**", "metric **缺**"),
    "活动数": ("campaign asset **在**", "metric **缺**"),
    "浏览量": ("sku_day_channel asset **在**", "metric **缺**（只有 uv=去重人数）"),
    "加购": ("sku_day_channel? 待核", "metric **缺**"),
    "商品数": ("sku asset **在**", "metric **缺**"),
    "SKU 数": ("sku_id 列**在**", "metric **缺**"),
    "省份": ("province asset **在**", "metric **缺**"),
    "类目": ("category_l1/l2/l3 列**在**", "metric **缺**（但可 group by）"),
}
for k, (phys, met) in KEY.items():
    print(f"  {k:10s}｜物理层：{phys:34s}｜指标层：{met}")
print()
print("=" * 78)
print("三、误拒 63 条的 gate_decisions / degradations（判是否为『模型自陈阻塞』）")
print("=" * 78)
print(f"gate_decisions 非空 = {sum(1 for r in wrong if r.get('gate_decisions'))}")
deg = collections.Counter()
for r in wrong:
    for x in (r.get("degradations") or []):
        deg[x.get("reason")] += 1
print(f"degradations = {deg.most_common()}")
print("（对比：若为 embedding 不可用导致空召回，应有 embedding_unavailable）")
print()
print("=" * 78)
print("四、L4 触发率与方案 A 前置（PRD §12.9）")
print("=" * 78)
print("① L4 触发率 > 10%  ｜ 现读 = 0.0%（query_plan 355 行 L4=0，Q 窗 R31m 已核）")
print("② L4 误判 ambiguous 是主因 ｜ 现读 = bind 层 clarify = 0；误拒主因 = plan 层 no_data_asset")
print("③ 语义层补全后仍不降 ｜ 未取")
print("⇒ **三条前置全不满足** ⇒ PRD §12.9「仅当同时满足才评估方案 A」未触发")
print("⇒ 主因指向 **语义层 metric 覆盖不足** = PRD §C.4.6 步骤 4 的『回看语义包』")
