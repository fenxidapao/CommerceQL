#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""W8 第 41 轮 · 零成本前置：语义摘要**长度/截断**体检（只读 / 零出站）

动机：`build_semantic_summary` 的截断是**按段从后往前整块丢弃**
（`payloads._truncate_sections`），上限 `MAX_SEMANTIC_SUMMARY_CHARS = 40_000`。
本轮要往包里**加 13 个指标 ＋ 5 个维度面** ⇒ 摘要会变长 ⇒ **必须先量**它有没有顶到上限，
否则"加了指标"可能反而**挤掉**后半段（资产列清单 / 唯一字段绑定 / 同义词表），
表现为"加了更多口径、模型反而更不会做"。

本脚本只做一件事：按 T_A × analyst 身份把摘要渲染出来，报长度与分段长度。
"""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.path.insert(0, os.path.join(ROOT, "data"))
sys.path.insert(0, os.path.join(ROOT, "data", "generator"))

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.planner.payloads import (  # noqa: E402
    MAX_SEMANTIC_SUMMARY_CHARS,
    build_semantic_summary,
)
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402


def identity(tenant: str) -> IdentityContext:
    return IdentityContext(
        trace_id="tr-w8-r41", task_id="tk-w8-r41", session_id="se-w8-r41",
        tenant_id=tenant, user_id="u-w8-r41", role=Role.ANALYST,
        scope_claims=(), shop_ids=(),
    )


def main() -> int:
    loaded = load_bundle(_bootstrap.BUNDLE_PATH)
    rt = SemanticBundleRuntime(loaded)
    out = {"bundle_version": rt.active_version(), "limit": MAX_SEMANTIC_SUMMARY_CHARS,
           "tenants": {}}
    for tenant in ("T_A", "T_B", "T_C"):
        text = build_semantic_summary(identity(tenant), rt)
        secs = text.split("\n\n")
        heads = []
        for s in secs:
            first = s.split("\n", 1)[0]
            heads.append({"head": first[:60], "chars": len(s)})
        truncated = "【摘要已截断" in text
        out["tenants"][tenant] = {
            "chars": len(text),
            "headroom": MAX_SEMANTIC_SUMMARY_CHARS - len(text),
            "truncated": truncated,
            "n_sections": len(secs),
            "n_lines": text.count("\n") + 1,
            "sections": heads,
            "n_metric_lines": sum(1 for x in text.splitlines() if x.startswith("    ") and "：" in x),
        }
    with io.open(os.path.join(HERE, "probe_semantic_summary.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print("语义包版本 = %s ｜ 上限 = %d" % (out["bundle_version"], out["limit"]))
    for t, v in out["tenants"].items():
        print("%s：chars=%d ｜ 余量=%d ｜ 截断=%s ｜ 段数=%d ｜ 行数=%d" % (
            t, v["chars"], v["headroom"], v["truncated"], v["n_sections"], v["n_lines"]))
        for s in v["sections"]:
            print("     %6d  %s" % (s["chars"], s["head"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
