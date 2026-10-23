"""W72-3 / R31bq：默认谓词**按指标收窄**（`refund_rate` 不得被注入 `refund_status <> 'refunded'`）。

背景（实证，`eval/results_r72_refund_leak_localization.json`）：
* 包内 `bundle:591` 明文「本指标的谓词**不含** `refund_status <> 'refunded'`，分子正是靠退款
  行为算出来的」；metric 级 `default_predicates` 只有 `pay_status='paid'` / `is_test_order=false`。
* 但注入侧（`ast_gate._inject_predicates`）只按**资产所属域**取整份域级表
  （`dp_order_002` 的 `applies_to` 不含 `refund_rate`）⇒ 退款率的分子被自己的 WHERE 清零，
  M-IDX-05/06 实测恒 `0.0`（权威 0.05008 / 0.04998）。

修法：`run_gate1(..., metrics=[...])` + `GuardAllowlist["metric_predicates"]`；
指标无法确定时**回落域级**（不放松），多指标对同一谓词意见不一致时回落域级并记日志。
"""

from __future__ import annotations

import pytest

from app.guard import run_gate1

from .guard_fixtures import build_allowlist

#: 与 M-IDX-05 同构的退款率查询（分子靠退款行为算出来）
_REFUND_RATE_SQL = (
    "SELECT SUM(CASE WHEN refund_status = 'refunded' THEN pay_amount ELSE 0 END) "
    "/ NULLIF(SUM(pay_amount), 0) FROM v_order_paid WHERE pay_time >= '2026-08-01'"
)
_GMV_SQL = "SELECT SUM(pay_amount) FROM v_order_paid WHERE pay_time >= '2026-08-01'"


@pytest.fixture()
def allow() -> dict:
    return build_allowlist()


def _has(preds, col: str) -> bool:
    return any(col in p for p in preds)


def test_refund_rate_does_not_get_refund_status_filter(allow: dict) -> None:
    """refund_rate 注入后**不得**含 `refund_status <> 'refunded'`（分子靠它算出来）。"""
    r = run_gate1(_REFUND_RATE_SQL, allow, metrics=["refund_rate"])
    assert r.passed, r.gate_result.rule_id
    assert not _has(r.applied_predicates, "refund_status"), r.applied_predicates
    assert "refund_status <> 'refunded'" not in r.rewritten_sql
    # 其余两条仍须在（不许为了修一条把谓词整体关掉）
    assert _has(r.applied_predicates, "pay_status")
    assert _has(r.applied_predicates, "is_test_order")


def test_gmv_keeps_three_predicates(allow: dict) -> None:
    """gmv 必须同时拿到三条（pay_status / refund_status / is_test_order）。"""
    r = run_gate1(_GMV_SQL, allow, metrics=["gmv"])
    assert r.passed, r.gate_result.rule_id
    assert _has(r.applied_predicates, "pay_status")
    assert _has(r.applied_predicates, "refund_status")
    assert _has(r.applied_predicates, "is_test_order")
    assert len(r.applied_predicates) == 3


def test_metric_predicates_override_domain(allow: dict) -> None:
    """同一句 SQL：声明指标后按指标级集注入；不声明时沿用域级集（3 条）。"""
    scoped = run_gate1(_REFUND_RATE_SQL, allow, metrics=["refund_rate"])
    domain = run_gate1(_REFUND_RATE_SQL, allow)
    assert len(domain.applied_predicates) == 3, domain.applied_predicates
    assert len(scoped.applied_predicates) == 2, scoped.applied_predicates
    assert set(scoped.applied_predicates) < set(domain.applied_predicates)


def test_unknown_metric_falls_back_to_domain(allow: dict) -> None:
    """指标名不在包内 / 没有指标级声明 ⇒ **回落域级**（fail-closed，不放松）。"""
    unknown = run_gate1(_REFUND_RATE_SQL, allow, metrics=["no_such_metric"])
    assert len(unknown.applied_predicates) == 3, unknown.applied_predicates
    # 空指标列表 = 旧行为（向后兼容）
    assert len(run_gate1(_REFUND_RATE_SQL, allow, metrics=[]).applied_predicates) == 3


def test_conflicting_metrics_fall_back_to_domain(allow: dict) -> None:
    """gmv 要 `refund_status <> 'refunded'`、refund_rate 明确排除 ⇒ 判冲突，回落域级不选边。"""
    r = run_gate1(_REFUND_RATE_SQL, allow, metrics=["gmv", "refund_rate"])
    assert len(r.applied_predicates) == 3, r.applied_predicates


def test_metric_without_declaration_falls_back(allow: dict) -> None:
    """没有任何指标级声明的概念（如 avg_list_price）⇒ 回落域级。"""
    r = run_gate1(_GMV_SQL, allow, metrics=["avg_list_price"])
    assert len(r.applied_predicates) == 3, r.applied_predicates
