#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
指标口径字典渲染器 —— 从 `semantic/bundle_*.yaml` **单向生成** `metric_dictionary.md`

归属窗口：W1A（semantic/**）

为什么不手写
------------
附录 C §C.14 把 `metric_dictionary.md` 列为交付物，但它的内容与语义包的
`metrics` 区块是**同一份事实**。手写 = 制造第二份真相，两边迟早漂移
（本项目已有实证：U-18 就是"同一事实在两个地方各写一遍，合起来矛盾"）。
→ 本文件把字典变成**派生视图**：改口径只能改 YAML，再重跑本脚本。
   生成的 md 顶部带 content_hash，可校验它确实对应某个 YAML 版本。

用法
----
    python semantic/render_metric_dictionary.py
    python semantic/render_metric_dictionary.py --check   # 只校验 md 是否与 YAML 同步
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BUNDLE = os.path.join(HERE, "bundle_2026.09.14.1.yaml")
DEFAULT_OUT = os.path.join(HERE, "metric_dictionary.md")
GENERATED = "<!-- GENERATED FILE - DO NOT EDIT BY HAND -->"


def bundle_digest(path: str) -> str:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    payload = json.dumps(data.get("metrics"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render(bundle_path: str) -> str:
    b = yaml.safe_load(open(bundle_path, encoding="utf-8"))
    meta = b.get("meta", {})
    dims = {d["name"]: d for d in b.get("dimensions", [])}
    out: list[str] = []

    out.append(GENERATED)
    out.append("")
    out.append("# 指标口径字典（metric_dictionary）")
    out.append("")
    out.append(f"> **本文件由 `semantic/render_metric_dictionary.py` 从 "
               f"`{os.path.basename(bundle_path)}` 自动生成，请勿手改。**")
    out.append(f">")
    out.append(f"> 语义包版本 `{meta.get('version')}`｜状态 `{meta.get('status')}`"
               f"｜指标口径 hash `{bundle_digest(bundle_path)}`")
    out.append(">")
    out.append("> 时区 `{}`；财年起始月 `{}`；周起点 `{}`。".format(
        meta.get("timezone"), meta.get("fiscal_year_start_month"), meta.get("week_starts_on")))
    out.append("")

    # ---- 概览表 ----
    out.append("## 1. 指标总览")
    out.append("")
    out.append("| 指标 | 显示名 | 域 | 单位 | 默认聚合 | 状态 | Owner | 默认时间基准 |")
    out.append("|---|---|---|---|---|---|---|---|")
    for m in b.get("metrics", []):
        tf = m.get("time_basis", "—")          # 时间基准的**唯一**承载位（§4.7.1 删掉了 time_field）
        out.append("| `{}` | {} | {} | {} | {} | {} | {} | {} |".format(
            m["name"], m.get("display_name", ""), m.get("domain", ""), m.get("unit", ""),
            m.get("default_aggregation", ""), m.get("status", ""), m.get("owner", ""), tf))
    out.append("")
    out.append("> **`status = draft` 的指标没有 `default_binding`、也没有别名** —— "
               "这是刻意的：未定口径的指标不得被检索命中（附录 C §C.5.2 / FR-12.3）。")
    out.append(">")
    out.append("> ⚠️ **时间基准读的是 `metrics[].time_basis`**。曾有一个 `default_binding.time_field` "
               "字段承载同一件事 —— 已由 07 §4.7.1 裁定**删除**（同一事实两处必然漂移）。")
    out.append("")

    # ---- 逐指标 ----
    out.append("## 2. 逐指标口径")
    out.append("")
    for m in b.get("metrics", []):
        out.append(f"### 2.{list(b['metrics']).index(m) + 1} `{m['name']}` — {m.get('display_name', '')}")
        out.append("")
        out.append(f"- **表达式**：`{m.get('expression', '')}`")
        out.append(f"- **默认聚合**：`{m.get('default_aggregation', '')}`｜**单位**：{m.get('unit', '')}"
                   f"｜**域**：{m.get('domain', '')}｜**Owner**：{m.get('owner', '')}"
                   f"｜**状态**：`{m.get('status', '')}`")
        db = m.get("default_binding")
        if db:
            out.append(f"- **默认绑定**：资产 `{db.get('asset')}`"
                       f"｜时间基准 `{m.get('time_basis', '—')}`（读 `time_basis`，非 time_field）")
            if db.get("reason"):
                out.append(f"  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，"
                           f"最终载体 = `insight.caveats[]`，≤ 40 字）：{db['reason']}")
        else:
            out.append("- **默认绑定**：无（draft 指标不参与 L3 绑定）")
        dp = m.get("default_predicates") or []
        if dp:
            out.append("- **默认谓词**：")
            for p in dp:
                owner = next((x for x in b.get("default_predicates", {}).get(m.get("domain"), [])
                              if x.get("predicate") == p), None)
                note = f" —— {owner['reason']}" if owner and owner.get("reason") else ""
                out.append(f"  - `{p}`{note}")
        note = (m.get("definition_note") or "").strip()
        if note:
            out.append("- **口径说明**：")
            for line in note.splitlines():
                if line.strip():
                    out.append(f"  - {line.strip()}")
        syn = m.get("synonyms") or []
        if syn:
            out.append(f"- **同义词（须与别名表一致）**：{'、'.join(syn)}")
        out.append("")

    # ---- 易混对 ----
    out.append("## 3. 易混指标对照（**口径差异必须显式**）")
    out.append("")
    notes = []
    for m in b.get("metrics", []):
        n = (m.get("definition_note") or "")
        if "差异" in n or "而非" in n:
            notes.append((m["name"], n.strip().replace("\n", " ")))
    if notes:
        out.append("| 指标 | 口径差异要点 |")
        out.append("|---|---|")
        for name, n in notes:
            out.append(f"| `{name}` | {n} |")
    else:
        out.append("_（本版无语义包内声明的差异项）_")
    out.append("")

    # ---- 维度口径 ----
    out.append("## 4. 维度口径（与指标联用时的时间/空间边界）")
    out.append("")
    ts = b.get("time_semantics", {})
    for k, v in ts.items():
        if k == "notes":
            out.append("- **时间口径明细**：")
            for n in v:
                out.append(f"  - {n}")
        else:
            out.append(f"- **{k}**：{v}")
    out.append("")
    for name, d in dims.items():
        if d.get("value_map"):
            out.append(f"- **`{name}` 的 value_map 是业务约定，不是数据库字段** —— "
                       f"共 {len(d['value_map'])} 组；未列入的取值归「其他」或不支持，"
                       f"**禁止让模型猜**。")
    out.append("")

    # ---- 变更纪律 ----
    out.append("## 5. 变更纪律")
    out.append("")
    out.append("| 动作 | 必须做的事 |")
    out.append("|---|---|")
    out.append("| 改任何口径 | 改 `bundle_*.yaml` 的 `meta.version` + 重跑本脚本 |")
    out.append("| 语义包升版 | 缓存键与 few-shot 索引必须失效（附录 B §B.4.1） |")
    out.append("| 冻结集是否需重生 | 由 **W6** 判定并出新版本号，**不得静默沿用** |")
    out.append("")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="渲染指标口径字典")
    ap.add_argument("--bundle", default=DEFAULT_BUNDLE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="只校验是否已同步（CI 用）")
    args = ap.parse_args(argv)

    text = render(args.bundle)
    if args.check:
        if not os.path.exists(args.out):
            print("MISSING", args.out, file=sys.stderr)
            return 1
        cur = open(args.out, encoding="utf-8").read()
        if cur != text:
            print("STALE: metric_dictionary.md 与语义包不一致，请重跑渲染", file=sys.stderr)
            return 1
        print("OK: metric_dictionary.md 与语义包同步")
        return 0

    open(args.out, "w", encoding="utf-8", newline="\n").write(text)
    print(f"written {args.out}  rate_hash={bundle_digest(args.bundle)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
