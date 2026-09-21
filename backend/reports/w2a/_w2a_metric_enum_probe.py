"""W2A · 零 LLM 成本的取证：`## 指标口径` 段进没进 plan 的出站 prompt。

背景：W2B 的 G-6 根因回执（`reports/w2b/RELAY.md §12`）证明——plan 资产信息的**唯一通道**
是 `semantic_summary`，而该通道里**没有指标段**，还明说"未提供指标口径目录…找不到就写进
`blocking_issues`"。模型照做 ⇒ PLAN 结构性自拒 ⇒ `executing` 恒 0。

本脚本把 `build_semantic_summary()`（唯一构造者）真跑一遍，回答四个问题：

1. 运行时现在有没有 `metrics()` / `aliases()` 枚举器；
2. 摘要里有没有 `## 指标口径` 段；
3. W7 题的 9 个指标名，有几个出现在出站文本里（**逐字**）；
4. 有没有 deny 列 / 非 active 资产从新段落漏出（N-12 复核）。

只读语义包、只调纯函数，**零 LLM 调用、不碰服务、不碰 DB**。

复现：`CommerceQL\\.venv\\Scripts\\python.exe backend\\reports\\w2a\\_w2a_metric_enum_probe.py`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(r"E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL")
sys.path.insert(0, str(REPO / "backend"))

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.planner.payloads import (  # noqa: E402
    _SUMMARY_HEADER,
    build_semantic_summary,
    summary_gaps,
)
from app.semantics import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = REPO / "semantic" / "bundle_2026.09.14.1.yaml"
OUT = Path(__file__).resolve().parent / "_w2a_summary_after.txt"

#: W7 批次里被模型写进 `blocking_issues` 的那个指标 + 包内全部 9 个指标名
METRIC_NAMES = (
    "gmv", "aov", "arpu", "order_cnt", "pay_cvr",
    "refund_rate", "repurchase_rate_90d", "sell_through_rate", "uv",
)


def _ctx(role: Role = Role.ANALYST) -> IdentityContext:
    return IdentityContext(
        trace_id="trace-probe",
        task_id="task-probe",
        session_id="session-probe",
        tenant_id="T_PROBE",
        user_id="user-probe",
        role=role,
        scope_claims=(),
        shop_ids=(),
    )


def main() -> None:
    loaded = load_bundle(BUNDLE)
    runtime = SemanticBundleRuntime(loaded)
    print(f"语义包 = {BUNDLE.name} | version={loaded.version} | status={loaded.status}")
    print(f"metrics 数 = {len(loaded.bundle.metrics)} | aliases 数 = {len(loaded.bundle.aliases)}")
    print()

    print("=== ① 运行时枚举器（决定摘要能渲染什么）===")
    for name in ("active_version", "asset_allowlist", "policy", "resolve_alias",
                 "dimensions", "field_bindings", "metric", "metrics", "aliases",
                 "time_semantics", "joins", "assets"):
        ok = callable(getattr(runtime, name, None))
        print(f"  {name:16} {'✅' if ok else '❌ 不存在'}")
    print()

    summary = build_semantic_summary(_ctx(), runtime)
    OUT.write_text(summary, encoding="utf-8")
    sections = re.findall(r"^## .+$", summary, flags=re.M)
    print("=== ② 摘要段落清单 ===")
    for s in sections:
        print(f"  {s}")
    print(f"  （共 {len(sections)} 段，{len(summary)} 字，上限 40000）")
    print()

    print("=== ③ 判据 ===")
    print(f"  摘要里有 '## 指标口径' 段吗            : {'## 指标口径' in summary}")
    hits = [n for n in METRIC_NAMES if re.search(rf"\b{re.escape(n)}\b", summary)]
    print(f"  9 个指标名出现在摘要里的（词边界）      : {len(hits)}/9 {hits}")
    print(f"  'GMV' 词形出现在摘要里吗（W7 那条题）  : {'GMV' in summary}")
    print(f"  draft 指标被标为不可用吗               : {'sell_through_rate' in summary}")
    print()

    print("=== ④ N-12 复核：新段落有没有漏 deny 列 / 非 active 资产 ===")
    deny_base = sorted({d.rsplit(".", 1)[-1] for d in loaded.deny_columns})
    leaked = [b for b in deny_base if b in summary]
    print(f"  deny 列名出现在整份摘要里的            : {leaked or '无'}")
    inactive = [
        a for a in ("v_does_not_exist",)
        if a in summary
    ]
    print(f"  非 active 资产名漏出                   : {inactive or '无'}")
    print()

    print("=== ⑤ 摘要缺口登记（生产代码自报）===")
    for g in summary_gaps():
        print(f"  - {g}")
    print()

    print(f"原文已留存 : {OUT}")
    print(f"头段原文   : {_SUMMARY_HEADER[:48]}…")


if __name__ == "__main__":
    main()
