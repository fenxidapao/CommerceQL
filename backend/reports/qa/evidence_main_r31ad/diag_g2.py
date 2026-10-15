#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QA R31ad · 主线重启第一步：G-2 与误拒的根因分档（**只读 / 零出站 / 零花费**）

问题：G-2 = easy×low 0/10；G-5 误拒 63/124
要问：
  ① G-2 那 10 条的 refusal_reason 是什么？
  ② 误拒 63 条的 refusal_reason 构成？（看是否**同根因**）
  ③ 全 166 条的 `no_data_asset` 规模 = ?
  ④ 这些题缺的是「资产（表/列）」还是「指标口径」？
"""
import io
import json
import collections

P = "eval/results_v1.json"
d = json.load(io.open(P, encoding="utf-8"))
recs = d["records"]
print("=" * 78)
print(f"面 = {P}｜records = {len(recs)}")
print("=" * 78)

# ---------- ① G-2 那 10 条 ----------
el = [r for r in recs if r.get("difficulty_struct") == "easy" and r.get("difficulty_semantic") == "low"]
print(f"\n① G-2 面（easy×low）= {len(el)} 条")
print(f"   outcome 分布 = {dict(collections.Counter([r['outcome'] for r in el]))}")
print(f"   refusal_reason = {dict(collections.Counter([r.get('refusal_reason') for r in el]))}")
print(f"   expected = {dict(collections.Counter([r.get('expected_behavior') for r in el]))}")

# ---------- ② refuse 全量 ----------
ref = [r for r in recs if r.get("outcome") == "refuse"]
print(f"\n② 全量 refuse = {len(ref)} 条")
cc = collections.Counter([r.get("refusal_reason") for r in ref])
for k, v in cc.most_common():
    print(f"   {str(k):18s} = {v}")

# ---------- ③ no_data_asset x expected ----------
nd = [r for r in ref if r.get("refusal_reason") == "no_data_asset"]
print(f"\n③ no_data_asset = {len(nd)} 条")
print(f"   其中 expected=refuse（**正确拒**）= {sum(1 for r in nd if r.get('expected_behavior') == 'refuse')}")
print(f"   其中 expected=execute（**误拒**）= {sum(1 for r in nd if r.get('expected_behavior') == 'execute')}")

# ---------- ④ 误拒 63 条构成 ----------
wrong = [r for r in recs if r.get("expected_behavior") == "execute" and r.get("outcome") == "refuse"]
print(f"\n④ 误拒（expected=execute 且 out=refuse）= {len(wrong)} 条")
for k, v in collections.Counter([r.get("refusal_reason") for r in wrong]).most_common():
    print(f"   {str(k):18s} = {v}")

# ---------- ⑤ 误拒里有哪些层级 ----------
print(f"\n⑤ 误拒的分层分布")
for k, v in collections.Counter([(r.get("difficulty_struct") or "(空)", r.get("difficulty_semantic") or "(空)") for r in wrong]).most_common(12):
    print(f"   {str(k):22s} = {v}")

# ---------- ⑥ 误拒的停止节点 ----------
print(f"\n⑥ 误拒的停止节点（nodes 末位）")
for k, v in collections.Counter([(r.get("nodes") or ["?"])[-1] for r in wrong]).most_common():
    print(f"   {str(k):18s} = {v}")

# ---------- ⑦ 抽 6 条 no_data_asset 误拒题面 ----------
print(f"\n⑦ no_data_asset 误拒题面抽样（前 12）")
for r in nd:
    if r.get("expected_behavior") == "execute":
        print(f"   {r['case_id']:11s} | {r['question'][:52]}")
