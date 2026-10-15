#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QA R31af · W8 第 40 轮复算（v2，修 metric 数取值）
**只读 / 零出站 / 零花费**
"""
import io
import json
import collections

W = json.load(io.open("backend/reports/w8/probe_semantic_metric_gap.json", encoding="utf-8"))
F = json.load(io.open("eval/dataset_v1_frozen.json", encoding="utf-8"))
R = json.load(io.open("eval/results_v1.json", encoding="utf-8"))
Y = None  # 语义包在别处已核

fr = {c["case_id"]: c for c in F["cases"]}
recs = R["records"]
cases = W["cases"]
cov = W["coverage"]
gaps = W["gaps"]

print("=" * 78)
print("① 三个数（主张 63｜16+46+1｜13）")
print("=" * 78)
print(f"  cases                = {len(cases):3d}  ⟷ 63  ⇒ {len(cases)==63}")
print(f"  pure_metric_only     = {cov['pure_metric_only']:3d}  ⟷ 16  ⇒ {cov['pure_metric_only']==16}")
print(f"  needs_non_metric     = {cov['needs_non_metric_face']:3d}  ⟷ 46  ⇒ {cov['needs_non_metric_face']==46}")
print(f"  not_gap              = {len(W['not_gap']):3d}  ⟷  1  ⇒ {len(W['not_gap'])==1}")
print(f"  proposed_new_metrics = {W['proposed_new_metrics']:3d}  ⟷ 13  ⇒ {W['proposed_new_metrics']==13}")
print(f"  gaps[] 列表长度       = {len(gaps):3d}  ⇒ 与 proposed_new_metrics 一致 = {len(gaps)==W['proposed_new_metrics']}")
print(f"  🔴 算术 16+46+1 = {16+46+1} ⟷ 63 ⇒ {16+46+1==63}")

print()
print("=" * 78)
print("② 三组互斥且并集 = 63")
print("=" * 78)
A = set(cov["pure_metric_only_cases"])
B = set(cov["needs_non_metric_face_cases"])
C = set(W["not_gap"].keys())
allc = set(c["case_id"] for c in cases)
print(f"  |A|={len(A)}｜|B|={len(B)}｜|C|={len(C)}")
print(f"  A∩B={len(A&B)}｜A∩C={len(A&C)}｜B∩C={len(B&C)} ⇒ 互斥 = {not (A&B or A&C or B&C)}")
print(f"  |A∪B∪C|={len(A|B|C)} ⟷ |cases|={len(allc)} ⇒ 相等 = {A|B|C == allc}")

print()
print("=" * 78)
print("③ 🔴 方法论：13 条 metric 是「概念级」还是「逐条特判」？")
print("=" * 78)
covers_stat = []
for m in gaps:
    n = len(m.get("covers") or [])
    covers_stat.append((m["metric"], m["display_name"], n))
covers_stat.sort(key=lambda x: -x[2])
for met, disp, n in covers_stat:
    bar = "█" * min(n, 30)
    print(f"  {met:24s}｜{disp:8s}｜{n:3d} {bar}")
one = [x for x in covers_stat if x[2] == 1]
many = [x for x in covers_stat if x[2] >= 2]
print()
print(f"  覆盖 = 1 的 = {len(one)} 条：{[x[0] for x in one]}")
print(f"  覆盖 ≥ 2 的 = {len(many)} 条（合计覆盖 {sum(x[2] for x in many)} case）")
tot_cov = sum(x[2] for x in covers_stat)
print(f"  总覆盖计数 = {tot_cov}（含重复：一个 case 可被多条 metric 覆盖）")
print()
print("  判据：「补 13 条 → 覆盖 16 条 case」⇒ 若**纯对 1**则 13 条只该覆盖 ≤13；")
print(f"        现 16 > 13 ⇒ **至少有一部分是多对多（概念级）**。")
print(f"        但**仍有 {len(one)} 条 metric 是 1 对 1** ⇒ 需逐条看是否属'为单题造指标'。")

print()
print("=" * 78)
print("④ X- 前缀 case 来源（15 条）")
print("=" * 78)
pref = collections.Counter([c["case_id"].split("-")[0] for c in cases])
print(f"  63 条前缀 = {dict(pref)}")
in_frozen = [cid for cid in allc if cid in fr]
print(f"  63 条里在冻结集的 = {len(in_frozen)}／63 ⇒ 全部在冻结集 = {len(in_frozen)==63}")
x_cases = [c for c in cases if c["case_id"].startswith("X-")]
print(f"  X- 开头 = {len(x_cases)} 条（均在上表内）")

print()
print("=" * 78)
print("⑤ 🔴 G-2 那 10 条：只补 metric 能救几条")
print("=" * 78)
g2 = [r["case_id"] for r in recs
      if r.get("difficulty_struct") == "easy" and r.get("difficulty_semantic") == "low"]
print(f"  G-2 面 = {len(g2)} 条")
tag_map = {}
for cid in g2:
    if cid in A:
        t = "✅ 纯 metric"
    elif cid in B:
        t = "⚠️ 需附面"
    elif cid in C:
        t = "🚫 不补"
    else:
        t = "❓ 未分类"
    tag_map[cid] = t
    print(f"     {cid:11s}｜{t}")
n_ok = sum(1 for cid in g2 if cid in A)
print()
print(f"  ⇒ 只补 metric 后，G-2 至多 0/10 → **{n_ok}/10 = {n_ok/10:.0%}**")
print(f"     目标 ≥95% ⇒ {'✅ 可达' if n_ok/10 >= 0.95 else '🔴 **达不到**（其余需附面）'}")
