"""闸门三：EXPLAIN 成本闸门（07 §7.5）。

归属窗口：W2C（docs/08 §4.1）。**纯函数，禁依赖 LLM / 数据库**（N-01 / N-03 / R-DEP-2）。

**职责切分（U-55 提案，见 reports/w2c/RELAY.md）**：
EXPLAIN 的**执行**归 `gate3_cost` 节点（W4，经只读连接、同事务、同身份 GUC）；
本模块只做**计划解析 + 阈值判定** —— 计划 JSON 经 ``thresholds["explain_plan"]`` 传入。
这样 guard 保持纯函数（离线可测），EXPLAIN 的连接治理留在编排层。

**三态出口**（07 §7.5）：pass → execute；warn → 仍执行；reject → error(COST_TOO_HIGH)。
**跳过语义**（07 §14.2 D6 / §17.4）：SQLite 沙箱无 EXPLAIN JSON → ``SKIPPED``，
**不得报告为通过**（ADR-18 / 沙箱能力缺口表）。

⚠️ 阈值定位是"拦数量级异常"不是精确成本控制（07 §7.5 ⚠️1–3）；
真硬保护在执行层（statement_timeout / 行数 / 内存上限）。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Mapping

from app.core.contracts import GateResult
from app.core.enums import GateDecision, GateNo
from app.guard.rules import USER_MESSAGE_FOR_COST

__all__ = [
    "run_gate3",
    "CostThresholds",
    "EXPLAIN_ERROR_DEGRADE_THRESHOLD",
]

#: EXPLAIN 连续报错达到该值 → 节点应降级为"仅 AST + 策略"模式并显式标注（07 §7.5）。
#: 计数与降级动作在节点层（W4）维护；本模块只给常量。
EXPLAIN_ERROR_DEGRADE_THRESHOLD: Final[int] = 3


@dataclass(frozen=True, slots=True)
class CostThresholds:
    """gate3 阈值表（07 §7.5）—— **可配置**（DoD④），默认值 = 07 原表。

    ⚠️ 调整必须走变更记录（07 §7.5 ⚠️4：不得静默改）。
    """

    total_cost_pass: Decimal = Decimal("50000")
    total_cost_reject: Decimal = Decimal("500000")
    rows_pass: int = 500_000
    rows_reject: int = 5_000_000
    nested_loop_outer_rows: int = 10_000
    seq_scan_warn_rows: int = 200_000
    sort_warn_rows: int = 500_000
    max_plan_depth: int = 12  # 仅记录（告警），不拒绝

    @classmethod
    def from_mapping(cls, thresholds: Mapping[str, Any]) -> "CostThresholds":
        """从配置映射构造（未给的键用默认值；键名即字段名；值做类型归一）。"""

        kwargs: dict[str, Any] = {}
        for f in cls.__dataclass_fields__:
            if f not in thresholds:
                continue
            val = thresholds[f]
            kwargs[f] = Decimal(str(val)) if f.startswith("total_cost") else int(val)
        return cls(**kwargs)


def run_gate3(sql: str, thresholds: Mapping[str, Any]) -> GateResult:
    """执行 gate3。``thresholds`` 键：``CostThresholds`` 字段名 + 以下专用键：

    - ``explain_plan``：``EXPLAIN (FORMAT JSON)`` 的解析结果（list[dict] 或 {"Plan": ...}）；
      **缺失 = 沙箱跳过** → ``SKIPPED``（不报告为通过，D6）；
    - ``explain_error``：True 表示 EXPLAIN 本身报错 → ``warn``（不因闸门故障阻断正常查询）。
    """

    cfg = CostThresholds.from_mapping(thresholds)

    if thresholds.get("explain_error"):
        # EXPLAIN 本身报错 → warn + 告警（连续 3 次由节点层降级并标注）。
        return GateResult(
            gate_no=GateNo.COST,
            passed=True,
            decision=GateDecision.WARN,
            reason="explain_failed",
        )

    plan_payload = thresholds.get("explain_plan")
    if plan_payload is None:
        # SQLite 评测沙箱跳过 —— 必须显式标注，不得报告为"通过"（§7.5 表）。
        return GateResult(
            gate_no=GateNo.COST,
            passed=False,
            decision=GateDecision.SKIPPED,
            reason="dialect_no_explain_json",
        )

    plan = _top_plan(plan_payload)
    if plan is None:
        return GateResult(
            gate_no=GateNo.COST,
            passed=True,
            decision=GateDecision.WARN,
            reason="explain_plan_unparseable",
        )

    nodes = list(_walk_plan(plan))
    total_cost = Decimal(str(plan.get("Total Cost", 0)))
    total_rows = sum(int(n.get("Plan Rows", 0)) for n in nodes)
    depth = _plan_depth(plan)

    decision = GateDecision.PASS
    reasons: list[str] = []

    # --- Total Cost 三档 ---
    if total_cost > cfg.total_cost_reject:
        decision = GateDecision.REJECT
        reasons.append(f"total_cost>{cfg.total_cost_reject}")
    elif total_cost > cfg.total_cost_pass:
        decision = GateDecision.WARN
        reasons.append(f"total_cost>{cfg.total_cost_pass}")

    # --- 预估扫描行数三档 ---
    if total_rows > cfg.rows_reject:
        decision = GateDecision.REJECT
        reasons.append(f"rows>{cfg.rows_reject}")
    elif total_rows > cfg.rows_pass and decision is GateDecision.PASS:
        decision = GateDecision.WARN
        reasons.append(f"rows>{cfg.rows_pass}")

    # --- 形态判据（逐节点）---
    for node in nodes:
        node_type = str(node.get("Node Type", ""))
        rows = int(node.get("Plan Rows", 0))
        children = node.get("Plans") or []
        if node_type == "Nested Loop" and children:
            outer_rows = int(children[0].get("Plan Rows", 0))
            if outer_rows > cfg.nested_loop_outer_rows:
                # JOIN 爆炸，最危险的一类 → 直接拒绝（07 §7.5）。
                decision = GateDecision.REJECT
                reasons.append(f"nested_loop_outer={outer_rows}")
        if node_type == "Seq Scan" and rows > cfg.seq_scan_warn_rows:
            if decision is GateDecision.PASS:
                decision = GateDecision.WARN
            reasons.append(f"seq_scan={rows}")
        if node_type == "Sort" and children:
            child_rows = int(children[0].get("Plan Rows", 0))
            if child_rows > cfg.sort_warn_rows and decision is GateDecision.PASS:
                decision = GateDecision.WARN
            reasons.append(f"sort_input={child_rows}")

    if depth > cfg.max_plan_depth:
        # 计划深度：仅记录（07 §7.5 表"告警（仅记录）"）→ 不改 decision。
        reasons.append(f"plan_depth={depth}")

    if decision is GateDecision.REJECT:
        return GateResult(
            gate_no=GateNo.COST,
            passed=False,
            decision=GateDecision.REJECT,
            rule_id="G3-COST",
            reason=USER_MESSAGE_FOR_COST,
            estimated_rows=total_rows,
            estimated_cost=total_cost,
        )

    return GateResult(
        gate_no=GateNo.COST,
        passed=True,
        decision=decision,
        reason=";".join(reasons) if reasons else None,
        estimated_rows=total_rows,
        estimated_cost=total_cost,
    )


# ---------------------------------------------------------------------------
# EXPLAIN (FORMAT JSON) 计划树解析
# ---------------------------------------------------------------------------

def _top_plan(payload: Any) -> Mapping[str, Any] | None:
    """兼容三种形态：``[{"Plan": {...}}]`` / ``{"Plan": {...}}`` / 直接的 Plan dict。"""

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, Mapping):
            plan = first.get("Plan")
            return plan if isinstance(plan, Mapping) else None
        return None
    if isinstance(payload, Mapping):
        plan = payload.get("Plan")
        if isinstance(plan, Mapping):
            return plan
        if "Node Type" in payload:
            return payload
    return None


def _walk_plan(node: Mapping[str, Any]) -> Mapping[str, Any]:
    """深度优先遍历 Plans[]（07 §7.5 解析字段清单）。"""

    yield node
    for child in node.get("Plans") or []:
        if isinstance(child, Mapping):
            yield from _walk_plan(child)


def _plan_depth(node: Mapping[str, Any]) -> int:
    child_depths = [
        _plan_depth(c) for c in (node.get("Plans") or []) if isinstance(c, Mapping)
    ]
    return 1 + (max(child_depths) if child_depths else 0)
