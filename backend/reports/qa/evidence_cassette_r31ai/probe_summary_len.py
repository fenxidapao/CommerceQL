# -*- coding: utf-8 -*-
"""离线复算：语义摘要长度（旧 9 指标包 ⟷ 新 22 指标包）。

目的：验证 W8 的成本归因「语义摘要 8,235→13,364 字符，四个 LLM 节点各吃一遍」。
方法：**自己构造**（照 W8 探针的构造法），不运行 W8 的脚本（那个会写它自己的产物）。
零出站 / 零花费。**不解析 YAML 之外的语义**，只调 `build_semantic_summary`。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

HERE = r"E:/tmp_qoder/qa_r31ai"
ROOT = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
for p in (os.path.join(ROOT, "backend"), os.path.join(ROOT, "eval"),
          os.path.join(ROOT, "data"), os.path.join(ROOT, "data", "generator")):
    sys.path.insert(0, p)

import _bootstrap  # noqa: E402
_bootstrap.bootstrap()

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.planner.payloads import MAX_SEMANTIC_SUMMARY_CHARS, build_semantic_summary  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

REL = "semantic/bundle_2026.09.14.1.yaml"
NEW = os.path.join(ROOT, REL)


def old_bundle_tmp(ref="a943575"):
    raw = subprocess.run(["git", "show", ref + ":" + REL],
                         capture_output=True, cwd=ROOT).stdout
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.write(fd, raw)
    os.close(fd)
    return path, len(raw)


def identity(tenant):
    return IdentityContext(trace_id="tr-qa", task_id="tk-qa", session_id="se-qa",
                           tenant_id=tenant, user_id="u-qa", role=Role.ANALYST,
                           scope_claims=(), shop_ids=())


print("MAX_SEMANTIC_SUMMARY_CHARS =", MAX_SEMANTIC_SUMMARY_CHARS)
rows = []
for label, path in (("写前(9 指标, a943575)", None), ("现读(22 指标)", NEW)):
    if path is None:
        path, ylen = old_bundle_tmp()
    else:
        ylen = os.path.getsize(path)
    rt = SemanticBundleRuntime(load_bundle(path))
    lens = []
    for t in ("T_A", "T_B", "T_C"):
        txt = build_semantic_summary(identity(t), rt)
        lens.append(len(txt))
    trunc = "【摘要已截断" in txt
    print(f"  {label:22s} yaml={ylen:6d}B  version={rt.active_version():16s} "
          f"摘要 chars={lens} 截断={trunc}")
    rows.append((label, lens[0], ylen))

if len(rows) == 2:
    a, b = rows[0][1], rows[1][1]
    print(f"\n  摘要增长 = {b-a:+d} chars（{b/max(a,1):.2f}×，+{100*(b-a)/max(a,1):.1f}%）")
    print(f"  W8 报值 = 8,235 → 13,364（+5,129，1.62×）")
