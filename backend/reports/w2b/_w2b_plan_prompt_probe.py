"""W2B · 零 LLM 成本的静态取证：`plan` 的出站 prompt 里**到底有没有指标目录**。

背景（W7 第五/六轮预检）：全链停在 `plan_ready`，`plan_summary=null` ⇒ PLAN 自拒
（模型给了 `blocking_issues`）。但 W7 同时实测：`GMV` **是** 9 个已定义 metric 之一、
语义层覆盖没问题 ⇒ "题集/语义层不对齐"这条假设被证伪。

本脚本不猜，直接把 `build_semantic_summary()`（`app/planner/payloads.py`，即
`semantic_summary` 载荷的**唯一构造者**）**真跑一遍**并打印原文，然后回答一个问题：

    **那 9 个指标名，有没有一个真的进了出站文本？**

它只读语义包、只调纯函数，**不发任何 LLM 请求**。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(r"E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL")
sys.path.insert(0, str(REPO / "backend"))

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.planner.payloads import (  # noqa: E402
    _METRIC_GAP_NOTE,
    _SUMMARY_HEADER,
    build_semantic_summary,
    summary_gaps,
)
from app.semantics import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = REPO / "semantic" / "bundle_2026.09.14.1.yaml"

#: W7 实测到的 9 个已定义指标（`metrics` 表口径）
METRIC_NAMES = (
    "gmv", "aov", "arpu", "order_cnt", "pay_cvr",
    "refund_rate", "repurchase_rate_90d", "sell_through_rate", "uv",
)


def main() -> None:
    loaded = load_bundle(BUNDLE)
    runtime = SemanticBundleRuntime(loaded)
    print(f"语义包 = {BUNDLE.name} | version={loaded.version} | status={loaded.status}")
    print(f"已定义 metric 数 = {len(runtime._metrics)}（内部字典，仅供对照）")
    print(f"metric 名 = {sorted(runtime._metrics)}")
    print()

    print("=== 语义层运行时端口暴露了哪些枚举器（决定摘要能渲染什么）===")
    for name in ("active_version", "asset_allowlist", "policy", "resolve_alias",
                 "dimensions", "field_bindings", "metric", "metrics", "aliases",
                 "time_semantics"):
        has = callable(getattr(runtime, name, None))
        print(f"  {name:16} {'✅' if has else '❌ 不存在'}")
    print()

    print("=== 摘要缺口（生产代码自报，不许静默）===")
    for g in summary_gaps():
        print(f"  - {g}")
    print()

    roles = sorted(getattr(runtime, "_applies_to_roles", ())) or [str(r.value) for r in Role]
    role = Role(roles[0])
    ctx = IdentityContext(
        trace_id="probe-plan-ctx",
        task_id="probe-plan-ctx",
        session_id="probe-plan-ctx",
        tenant_id="t-probe",
        user_id="u-probe",
        role=role,
    )
    summary = build_semantic_summary(ctx, runtime)
    print(f"=== 出站 semantic_summary 原文（role={role.value}，共 {len(summary)} 字）===")
    print(summary)
    print("=== 原文结束 ===")
    print()

    print("=== 判据 ===")
    print(f"  gap 声明进入了摘要（'指标口径目录' 出现） : {'指标口径目录' in summary}")
    print(f"  摘要含 '（语义包摘要未提供）' 占位吗        : {'（语义包摘要未提供）' in summary}")
    hits = [n for n in METRIC_NAMES if n in summary]
    print(f"  9 个指标名出现在摘要里的                 : {hits or '**一个都没有**'}")
    print(f"  摘要里有 '## 指标' 段落吗                 : {'## 指标' in summary}")
    print()
    print(f"  头段原文 : {_SUMMARY_HEADER[:60]}…")
    print(f"  缺口原文 : {_METRIC_GAP_NOTE[:60]}…")


if __name__ == "__main__":
    main()
