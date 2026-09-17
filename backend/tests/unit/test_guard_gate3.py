"""gate3（EXPLAIN 成本闸门）单元测试（W2C）。

阈值表 = 07 §7.5 原值；调整必须可配置（DoD④）且走变更记录（不得静默改）。
"""

from __future__ import annotations

from decimal import Decimal

from app.core.enums import GateDecision
from app.guard.cost_gate import EXPLAIN_ERROR_DEGRADE_THRESHOLD, run_gate3


def _plan(node_type: str, rows: int, cost: int | float, children: list | None = None) -> dict:
    return {
        "Node Type": node_type,
        "Plan Rows": rows,
        "Total Cost": cost,
        "Plans": children or [],
    }


def _plan_payload(root: dict) -> list[dict]:
    return [{"Plan": root}]


class TestThresholdTable:
    def test_total_cost_pass(self) -> None:
        r = run_gate3("SELECT 1", {"explain_plan": _plan_payload(_plan("Seq Scan", 100, 10))})
        assert r.passed and r.decision is GateDecision.PASS
        assert r.estimated_cost == Decimal("10")

    def test_total_cost_warn_band(self) -> None:
        r = run_gate3(
            "SELECT 1",
            {"explain_plan": _plan_payload(_plan("Seq Scan", 100, Decimal("60000")))},
        )
        assert r.passed and r.decision is GateDecision.WARN

    def test_total_cost_reject(self) -> None:
        r = run_gate3(
            "SELECT 1",
            {"explain_plan": _plan_payload(_plan("Seq Scan", 100, 600_000))},
        )
        assert not r.passed
        assert r.decision is GateDecision.REJECT
        assert r.rule_id == "G3-COST"
        assert r.reason  # 用户文案（07 §7.6：收窄建议）

    def test_rows_warn_band(self) -> None:
        r = run_gate3(
            "SELECT 1",
            {"explain_plan": _plan_payload(_plan("Seq Scan", 600_000, 10))},
        )
        assert r.passed and r.decision is GateDecision.WARN

    def test_rows_reject(self) -> None:
        r = run_gate3(
            "SELECT 1",
            {"explain_plan": _plan_payload(_plan("Seq Scan", 6_000_000, 10))},
        )
        assert not r.passed and r.decision is GateDecision.REJECT

    def test_plan_rows_recursive_sum(self) -> None:
        # 预估扫描行数 = Plans[] 递归累加（07 §7.5）
        root = _plan(
            "Hash Join", 0, 10,
            [_plan("Seq Scan", 300_000, 5), _plan("Seq Scan", 300_000, 5)],
        )
        r = run_gate3("SELECT 1", {"explain_plan": _plan_payload(root)})
        assert r.estimated_rows == 600_000
        assert r.decision is GateDecision.WARN  # 600k ∈ (500k, 5M] warn 档


class TestPlanShapeRules:
    def test_nested_loop_outer_rows_reject(self) -> None:
        # JOIN 爆炸：外层 > 10,000 → 直接拒绝（最危险的一类）
        root = _plan(
            "Nested Loop", 50_000, 100,
            [_plan("Seq Scan", 20_000, 50), _plan("Index Scan", 10, 50)],
        )
        r = run_gate3("SELECT 1", {"explain_plan": _plan_payload(root)})
        assert not r.passed and r.decision is GateDecision.REJECT

    def test_nested_loop_small_outer_warn_only(self) -> None:
        root = _plan(
            "Nested Loop", 5_000, 100,
            [_plan("Seq Scan", 5_000, 50), _plan("Index Scan", 10, 50)],
        )
        r = run_gate3("SELECT 1", {"explain_plan": _plan_payload(root)})
        assert r.passed

    def test_seq_scan_large_rows_warn_not_reject(self) -> None:
        # 小表 Seq Scan 合理；> 200k warn 不阻断
        r = run_gate3(
            "SELECT 1",
            {"explain_plan": _plan_payload(_plan("Seq Scan", 300_000, 10))},
        )
        assert r.passed and r.decision is GateDecision.WARN

    def test_sort_large_input_warn(self) -> None:
        root = _plan(
            "Sort", 100, 10,
            [_plan("Seq Scan", 600_000, 5)],
        )
        r = run_gate3("SELECT 1", {"explain_plan": _plan_payload(root)})
        assert r.passed and r.decision is GateDecision.WARN


class TestSkipAndErrorSemantics:
    def test_sqlite_skip_not_reported_as_pass(self) -> None:
        # 07 §14.2 D6 / §7.5：SKIPPED 不得报告为通过（ADR-18 沙箱缺口）
        r = run_gate3("SELECT 1", {})
        assert r.decision is GateDecision.SKIPPED
        assert r.reason == "dialect_no_explain_json"
        assert r.passed is False  # ⚠️ skipped 不是 passed

    def test_explain_error_is_warn(self) -> None:
        # EXPLAIN 自身报错 → 不因闸门故障阻断正常查询（07 §7.5）
        r = run_gate3("SELECT 1", {"explain_error": True})
        assert r.passed and r.decision is GateDecision.WARN
        assert r.reason == "explain_failed"

    def test_degrade_threshold_constant(self) -> None:
        # 连续 3 次报错 → 节点层降级为"仅 AST+策略"并显式标注（计数归 W4）
        assert EXPLAIN_ERROR_DEGRADE_THRESHOLD == 3

    def test_unparseable_plan_warns(self) -> None:
        r = run_gate3("SELECT 1", {"explain_plan": {"unexpected": "shape"}})
        assert r.passed and r.decision is GateDecision.WARN
        assert r.reason == "explain_plan_unparseable"


class TestConfigurableThresholds:
    """DoD④：阈值表可配置。"""

    def test_override_reject_threshold(self) -> None:
        cfg = {"explain_plan": _plan_payload(_plan("Seq Scan", 100, 100)), "total_cost_reject": "50"}
        r = run_gate3("SELECT 1", cfg)
        assert not r.passed and r.decision is GateDecision.REJECT

    def test_override_rows_threshold(self) -> None:
        cfg = {"explain_plan": _plan_payload(_plan("Seq Scan", 600, 10)), "rows_reject": 500}
        r = run_gate3("SELECT 1", cfg)
        assert not r.passed

    def test_unknown_keys_ignored(self) -> None:
        cfg = {"explain_plan": _plan_payload(_plan("Seq Scan", 100, 10)), "future_key": 1}
        r = run_gate3("SELECT 1", cfg)
        assert r.passed
