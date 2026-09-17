"""CommerceQL 三道闸门 —— **纯函数**；``rules.py`` 为规则唯一入口。

层号：L2｜归属窗口：W2C（docs/08 §4.1 文件归属权表）｜禁依赖：``llm``（R-DEP-2，CI 强制）

模块布局（07 §7 / 附-1）：

- ``rules.py``     —— 20 条 AST 规则注册表 + 用户文案（07 §7.2/§7.6）**唯一来源**；
- ``ast_gate.py``  —— gate1：AST 审计 + LIMIT 注入 + 默认谓词注入（§7.2/§7.3）；
- ``policy_gate.py`` —— gate2：策略校验 + scope 四分支计算（§7.4）；
- ``cost_gate.py`` —— gate3：EXPLAIN 计划解析 + 阈值判定（§7.5）；
- 本文件           —— ``SqlGuard``（实现 ``core.contracts.GuardPort``）+ 完整出参导出。

**接线注意（W4）**：端口签名只回传 ``GateResult``（gate2 另带 ``ScopeInfo``）；
但节点还需要 ``rewritten_sql`` / ``limit_injected`` / ``applied_predicates`` / warnings
等完整出参 —— 请调 ``run_gate1`` / ``run_gate2`` 模块函数（U-62 提案已登记 RELAY）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.core.contracts import GateResult, ScopeInfo
from app.guard.ast_gate import Gate1Report, Gate1Warning, run_gate1
from app.guard.cost_gate import CostThresholds, run_gate3
from app.guard.policy_gate import Gate2Report, run_gate2

if TYPE_CHECKING:
    from app.core.contracts import IdentityContext, SemanticBundlePort

__all__ = [
    "SqlGuard",
    "Gate1Report",
    "Gate1Warning",
    "Gate2Report",
    "CostThresholds",
    "run_gate1",
    "run_gate2",
    "run_gate3",
]


class SqlGuard:
    """``GuardPort`` 实现（顺序不可变、不可跳过；三道都是纯函数 —— N-03）。

    ⚠️ 节点侧推荐直接调 ``run_gate1`` / ``run_gate2`` / ``run_gate3`` 获取完整出参；
    本类是端口契约的**形状实现**（供 runtime_checkable 断言与依赖注入框架使用）。
    """

    def gate1(self, sql: str, allowlist: Mapping[str, Any]) -> GateResult:
        return run_gate1(sql, allowlist).gate_result

    def gate2(
        self, sql: str, ctx: IdentityContext, bundle: SemanticBundlePort
    ) -> tuple[GateResult, ScopeInfo]:
        report = run_gate2(sql, ctx, bundle)
        return report.gate_result, report.scope

    def gate3(self, sql: str, thresholds: Mapping[str, Any]) -> GateResult:
        return run_gate3(sql, thresholds)
