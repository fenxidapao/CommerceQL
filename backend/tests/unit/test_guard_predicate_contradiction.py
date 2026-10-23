"""W73-1 / R31bq：默认谓词与**题目显式谓词矛盾**时必须跳过（否则结果被清零）。

背景（实证，QA §94.3）：
* `H-ENUM-02`「全额退款状态的订单数」——模型 SQL 带 `refund_status = %(refund_status)s`
  （`params['refund_status'] = 'refunded'`），闸门又注入 `refund_status <> 'refunded'`
  ⇒ **0 行**；只去掉注入那一条后 5 行，计数与金标逐值相同。
* 根因同 `refund_rate`（W72-3），但那条路径是「指标声明为空」⇒ 回落域级，
  指标级收窄治不了它 ⇒ 需要**逐条**的显式矛盾守卫。
* `E-MET-08`（`pay_status='unpaid'` 的反向探针）同理。

守卫规则见 `ast_gate._contradiction`：同列 `=` / `<>` 四种组合里三种判矛盾；
值解析不出（占位符无绑定）时按矛盾处理（模型已表态，闸门不替它翻案）。
"""

from __future__ import annotations

import pytest

from app.guard import run_gate1

from .guard_fixtures import build_allowlist


@pytest.fixture()
def allow() -> dict:
    return build_allowlist()


def _has(preds, col: str) -> bool:
    return any(col in p for p in preds)


#: H-ENUM-02 形状：模型用占位符写「全额退款」，闸门的域级谓词里有 `<> 'refunded'`
_HENUM02_SQL = (
    "SELECT v_shop.shop_id AS shop_id, v_shop.shop_name AS shop_name, "
    "COUNT(DISTINCT v_order_paid.sub_order_id) AS refunded_order_cnt "
    "FROM v_order_paid JOIN v_shop ON v_order_paid.shop_id = v_shop.shop_id "
    "WHERE v_order_paid.refund_status = %(refund_status)s"
)
_HENUM02_PARAMS = {"refund_status": "refunded"}


def test_refunded_order_cnt_drops_opposite_predicate(allow: dict) -> None:
    """占位符版（真实形态）：`= %(refund_status)s`='refunded' ⇒ 不得注入 `<> 'refunded'`。"""
    r = run_gate1(
        _HENUM02_SQL, allow, metrics=["refunded_order_cnt"], params=_HENUM02_PARAMS
    )
    assert r.passed, r.gate_result.rule_id
    assert not _has(r.applied_predicates, "refund_status"), r.applied_predicates
    assert "refund_status <> 'refunded'" not in r.rewritten_sql
    # 派单红线：不得为了修这一条把默认谓词整体关掉
    assert _has(r.applied_predicates, "pay_status")
    assert _has(r.applied_predicates, "is_test_order")


def test_literal_form_is_guarded_too(allow: dict) -> None:
    """字面量版（同义形态）：`refund_status = 'refunded'` 同样判矛盾。"""
    sql = (
        "SELECT COUNT(DISTINCT sub_order_id) FROM v_order_paid "
        "WHERE refund_status = 'refunded'"
    )
    r = run_gate1(sql, allow, params={})
    assert r.passed, r.gate_result.rule_id
    assert not _has(r.applied_predicates, "refund_status"), r.applied_predicates


def test_partial_refund_is_not_a_contradiction(allow: dict) -> None:
    """H-ENUM-01 形状：`= 'partial'` 与 `<> 'refunded'` 可同时成立 ⇒ 照旧注入。"""
    sql = (
        "SELECT COUNT(DISTINCT sub_order_id) FROM v_order_paid "
        "WHERE refund_status = %(refund_status)s"
    )
    r = run_gate1(sql, allow, metrics=["order_cnt"], params={"refund_status": "partial"})
    assert r.passed, r.gate_result.rule_id
    assert _has(r.applied_predicates, "refund_status"), r.applied_predicates


def test_reverse_caliber_pay_status_unpaid(allow: dict) -> None:
    """E-MET-08 形状：`pay_status='unpaid'` ⇒ 不得注入 `pay_status='paid'`，其余两条仍在。"""
    sql = (
        "SELECT SUM(pay_amount) FROM v_order_paid "
        "WHERE pay_status = %(pay_status)s AND pay_time >= %(start)s"
    )
    r = run_gate1(sql, allow, metrics=["gmv"], params={"pay_status": "unpaid", "start": "2026-08-01"})
    assert r.passed, r.gate_result.rule_id
    assert "pay_status = 'paid'" not in r.rewritten_sql
    assert _has(r.applied_predicates, "refund_status")
    assert _has(r.applied_predicates, "is_test_order")


def test_gmv_untouched_when_no_contradiction(allow: dict) -> None:
    """无矛盾时 gmv 仍拿满三条（守卫不许有连带效应）。"""
    r = run_gate1(
        "SELECT SUM(pay_amount) FROM v_order_paid WHERE pay_time >= '2026-08-01'",
        allow,
        metrics=["gmv"],
    )
    assert r.passed, r.gate_result.rule_id
    assert len(r.applied_predicates) == 3, r.applied_predicates


def test_unresolved_placeholder_is_treated_as_conflict(allow: dict) -> None:
    """没给 params ⇒ 占位符解析不出 ⇒ 同列候选保守跳过（宁可少注入，不注入清零谓词）。"""
    r = run_gate1(_HENUM02_SQL, allow, metrics=["refunded_order_cnt"])
    assert r.passed, r.gate_result.rule_id
    assert not _has(r.applied_predicates, "refund_status"), r.applied_predicates


def test_same_value_equality_is_not_a_contradiction(allow: dict) -> None:
    """模型已写 `pay_status='paid'` 且默认谓词也是它 ⇒ 不算矛盾（重复但不冲突）。"""
    sql = (
        "SELECT SUM(pay_amount) FROM v_order_paid "
        "WHERE pay_status = %(pay_status)s AND is_test_order = %(is_test)s "
        "AND refund_status <> %(rs)s"
    )
    r = run_gate1(
        sql, allow, metrics=["gmv"],
        params={"pay_status": "paid", "is_test": False, "rs": "refunded"},
    )
    assert r.passed, r.gate_result.rule_id
    assert len(r.applied_predicates) == 3, r.applied_predicates


def test_two_different_equalities_conflict(allow: dict) -> None:
    """`= 'partial'` 对注入 `= 'paid'`（不同值）同样判矛盾。"""
    sql = (
        "SELECT SUM(pay_amount) FROM v_order_paid "
        "WHERE pay_status = %(pay_status)s"
    )
    r = run_gate1(sql, allow, metrics=["gmv"], params={"pay_status": "partial"})
    assert r.passed, r.gate_result.rule_id
    assert "pay_status = 'paid'" not in r.rewritten_sql
