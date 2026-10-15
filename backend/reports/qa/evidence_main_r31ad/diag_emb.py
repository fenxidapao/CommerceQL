#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QA R31ad-2 · 决定性：`embedding_unavailable` 到底是根因还是伴随现象？
**只读 / 零出站 / 零花费**

判法：
  若「误拒 63」与「成功 execute」两组**都有**该 degraded ⇒ 它是**全场伴随**（不是根因）
  若只有误拒组有 ⇒ 它可能是根因
"""
import io
import json
import collections

d = json.load(io.open("eval/results_v1.json", encoding="utf-8"))
recs = d["records"]


def has_emb(r):
    return any((x or {}).get("reason") == "embedding_unavailable" for x in (r.get("degradations") or []))


def by_outcome(out):
    g = [r for r in recs if r.get("outcome") == out]
    return len(g), sum(1 for r in g if has_emb(r))


print("=" * 78)
print("① 按 outcome 拆 embedding_unavailable 命中率")
print("=" * 78)
for out in ("success", "refuse", "clarify", "error"):
    n, k = by_outcome(out)
    if n:
        print(f"  {out:9s} = {n:3d} 条｜含 embedding_unavailable = {k:3d}（{100*k/n:5.1f}%）")

print()
print("=" * 78)
print("② 按「期望 execute」拆（G-5 的分母面）")
print("=" * 78)
ex = [r for r in recs if r.get("expected_behavior") == "execute"]
ok = [r for r in ex if r.get("outcome") == "success"]
bad = [r for r in ex if r.get("outcome") == "refuse"]
print(f"  期望 execute 总 = {len(ex)}")
print(f"    其中 success（做对了） = {len(ok):3d}｜含 emb = {sum(1 for r in ok if has_emb(r)):3d}"
      f"（{100*sum(1 for r in ok if has_emb(r))/len(ok) if ok else 0:.1f}%）")
print(f"    其中 refuse（误拒）    = {len(bad):3d}｜含 emb = {sum(1 for r in bad if has_emb(r)):3d}"
      f"（{100*sum(1 for r in bad if has_emb(r))/len(bad) if bad else 0:.1f}%）")
print()
if ok and bad:
    a = sum(1 for r in ok if has_emb(r)) / len(ok)
    b = sum(1 for r in bad if has_emb(r)) / len(bad)
    if abs(a - b) < 0.15:
        print(f"  ⇒ 两组命中率接近（{a:.1%} ⟷ {b:.1%}）⇒ **embedding_unavailable 是全场伴随，不是误拒的区分因素**")
    else:
        print(f"  ⇒ 两组差异显著（{a:.1%} ⟷ {b:.1%}）⇒ **需进一步归因**")

print()
print("=" * 78)
print("③ 对照：全 166 条里 embedding_unavailable")
print("=" * 78)
allk = sum(1 for r in recs if has_emb(r))
print(f"  含 = {allk}／{len(recs)} = {100*allk/len(recs):.1f}%")

print()
print("=" * 78)
print("④ 误拒 vs 成功的「题面可答性」对照（同分层）")
print("=" * 78)
for lay in (("easy", "low"), ("easy", "medium"), ("medium", "medium")):
    g = [r for r in recs if r.get("difficulty_struct") == lay[0] and r.get("difficulty_semantic") == lay[1]]
    c = collections.Counter([r.get("outcome") for r in g])
    print(f"  {lay[0]:8s}×{lay[1]:8s} = {len(g):3d}｜{dict(c)}")
# 对照：这些层里 success 的题面
print()
print("  同层 success 的题面（对照组）:")
for r in recs:
    if (r.get("difficulty_struct"), r.get("difficulty_semantic")) == ("easy", "low") and r.get("outcome") == "success":
        print("   ", r["case_id"], "|", r["question"][:46])
for r in recs:
    if (r.get("difficulty_struct"), r.get("difficulty_semantic")) == ("easy", "medium") and r.get("outcome") == "success":
        print("   ", r["case_id"], "|", r["question"][:46])
