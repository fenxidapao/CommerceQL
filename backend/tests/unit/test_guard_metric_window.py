"""W75-1：`metrics[].window` 强制（`app/guard/metric_window.py`）。

背景（QA §96.8 / W73-4 实证）：语义包 `bundle:613` 给 `repurchase_rate_90d`
声明 `window: "90 days"`，但此前**没有任何代码读它** ⇒ M-IDX-09 只有下界、
M-IDX-10 有上界，同一指标两次问答不可比。

判据：有 window 且有起始时间 ⇒ `time_basis < start + window` 必须存在；
缺则补、不一致则修、一致则不动、无起始时间不误加、解析不出 fail-closed。
"""

from __future__ import annotations

import pytest

from app.guard.metric_window import (
    MetricWindowError,
    MetricWindowRule,
    enforce_metric_windows,
)

_REPURCHASE = MetricWindowRule(
    metric="repurchase_rate_90d", time_basis="pay_time", window="90 days"
)

#: M-IDX-09 形状：内层只有下界（`%(start_ts)s`），上界缺失
_SQL_LOWER_ONLY = (
    "SELECT COUNT(DISTINCT CASE WHEN per_buyer.cnt >= 2 THEN per_buyer.buyer_id END)"
    " * 1.0 / NULLIF(COUNT(DISTINCT per_buyer.buyer_id), 0) AS repurchase_rate_90d "
    "FROM (SELECT o.buyer_id AS buyer_id, COUNT(DISTINCT o.sub_order_id) AS cnt "
    "FROM v_order_paid AS o WHERE o.pay_time >= %(start_ts)s GROUP BY o.buyer_id) AS per_buyer"
)

#: M-IDX-10 形状：上界恰好 = start + 90 天
_SQL_CORRECT_UPPER = (
    "SELECT COUNT(DISTINCT buyer_orders.buyer_id) FROM ("
    "SELECT o.buyer_id AS buyer_id, COUNT(DISTINCT o.sub_order_id) AS cnt "
    "FROM v_order_paid AS o WHERE o.pay_time >= %(start_ts)s "
    "AND o.pay_time < %(end_ts)s GROUP BY o.buyer_id) AS buyer_orders"
)

#: C-REP-01 形状：没有任何时间谓词
_SQL_NO_START = (
    "SELECT COUNT(DISTINCT o.buyer_id) FROM v_order_paid AS o WHERE o.pay_status = 'paid'"
)


def test_upper_bound_is_added_as_a_bound_parameter() -> None:
    """缺上界 ⇒ 补 `pay_time < start + 90d`，值走占位符（N-04），落进参数表。"""
    out = enforce_metric_windows(
        _SQL_LOWER_ONLY, {"start_ts": "2026-06-01"}, [_REPURCHASE]
    )
    assert out.changed
    assert "o.pay_time < %(window_end_repurchase_rate_90d)s" in out.sql
    assert out.params["window_end_repurchase_rate_90d"] == "2026-08-30"
    # 原有下界与参数不得被改
    assert "o.pay_time >= %(start_ts)s" in out.sql
    assert out.params["start_ts"] == "2026-06-01"


def test_a_correct_upper_bound_is_left_untouched() -> None:
    """已有正确上界（2026-03-01 + 90 天 = 2026-05-30）⇒ SQL 与参数逐字不动。"""
    params = {"start_ts": "2026-03-01", "end_ts": "2026-05-30"}
    out = enforce_metric_windows(_SQL_CORRECT_UPPER, params, [_REPURCHASE])
    assert not out.changed
    assert out.sql == _SQL_CORRECT_UPPER
    assert out.params == params


def test_no_start_time_means_no_upper_bound() -> None:
    """无起始时间不误加（C-REP-01 形状）—— 也不得因此报错。"""
    out = enforce_metric_windows(_SQL_NO_START, {}, [_REPURCHASE])
    assert not out.changed
    assert out.sql == _SQL_NO_START


def test_unparsable_window_fails_closed() -> None:
    """日历歧义单位（month/quarter）不在本模块猜 ⇒ 拒绝，不得静默忽略。"""
    with pytest.raises(MetricWindowError) as exc:
        enforce_metric_windows(
            _SQL_LOWER_ONLY,
            {"start_ts": "2026-06-01"},
            [MetricWindowRule("x", "pay_time", "1 quarter")],
        )
    assert exc.value.code == "window_unparsable"


def test_unparsable_start_fails_closed() -> None:
    with pytest.raises(MetricWindowError) as exc:
        enforce_metric_windows(
            "SELECT COUNT(*) FROM v_order_paid WHERE pay_time >= CURRENT_DATE - 30",
            {},
            [_REPURCHASE],
        )
    assert exc.value.code == "start_unparsable"


def test_inconsistent_upper_bound_is_repaired_in_place() -> None:
    """不一致则修：只改上界那一个比较，其它谓词原样保留。"""
    sql = (
        "SELECT COUNT(DISTINCT o.buyer_id) FROM v_order_paid AS o "
        "WHERE o.pay_status = 'paid' AND o.pay_time >= '2026-06-01' "
        "AND o.pay_time < '2026-07-01'"
    )
    out = enforce_metric_windows(sql, {}, [_REPURCHASE])
    assert out.changed
    assert "o.pay_time < %(window_end_repurchase_rate_90d)s" in out.sql
    assert "2026-07-01" not in out.sql
    assert "o.pay_status = 'paid'" in out.sql
    assert out.params["window_end_repurchase_rate_90d"] == "2026-08-30"


def test_predicate_goes_to_the_select_that_owns_the_start() -> None:
    """起始时间在子查询里 ⇒ 上界也落在子查询（外层引用 pay_time 会指向不存在的列）。"""
    out = enforce_metric_windows(
        _SQL_LOWER_ONLY, {"start_ts": "2026-06-01"}, [_REPURCHASE]
    )
    inner = out.sql.split("FROM (", 1)[1]
    assert "%(window_end_repurchase_rate_90d)s" in inner


def test_conflicting_windows_for_one_basis_are_rejected() -> None:
    """同一条 WHERE 上两个指标给出不同窗口 ⇒ 没有正确答案，拒绝。"""
    other = MetricWindowRule("another_metric", "pay_time", "30 days")
    with pytest.raises(MetricWindowError) as exc:
        enforce_metric_windows(
            _SQL_LOWER_ONLY, {"start_ts": "2026-06-01"}, [_REPURCHASE, other]
        )
    assert exc.value.code == "metric_window_conflict"
