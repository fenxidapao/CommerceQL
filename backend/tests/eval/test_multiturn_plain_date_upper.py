"""U-165：纯日期上界必须按「含当日」抬成次日（纯函数，零 LLM／零图／零 DB）。

为什么改：平台自己的时间解析产出是闭区间 —— `backend/app/planner/timeexpr.py:227-234`
的 `_boundary(..., end=True)` 给 `time(23, 59, 59)`，并注明口径逐字取自语义包 §9 notes 的
「首日 00:00:00 至末日 23:59:59」；语义包里 `右开` / `闭区间` 各 0 处。
⇒ 模型写纯日期 `2018-12-31` 是同一口径的另一种写法，抬次日即与右开金标 `2019-01-01` 等值。
原实现（U-157）「纯日期刻意不抬」与契约冲突，是其时口径未定下的保守写法。
"""

from __future__ import annotations

import multiturn


def test_plain_date_upper_is_treated_as_inclusive() -> None:
    """正控：纯日期上界抬成次日，与右开金标同值 ⇒ 判等。"""
    assert multiturn.time_field_ok("time_end", "2019-01-01", "2018-12-31") is True
    assert multiturn.time_field_ok("time_end", "2019-02-01", "2019-01-31") is True


def test_timestamp_upper_still_bumps() -> None:
    """旁证：`23:59:59`（含 `T` 分隔）形态不受影响。"""
    assert multiturn.time_field_ok("time_end", "2019-01-01", "2018-12-31 23:59:59") is True
    assert multiturn.time_field_ok("time_end", "2019-01-01", "2018-12-31T23:59:59") is True


def test_partial_day_upper_is_not_bumped() -> None:
    """负控：带时刻但不是 `23:59:59`（如 `12:00:00`）⇒ 不抬，仍按当日比。"""
    assert multiturn.time_field_ok("time_end", "2019-01-01", "2018-12-31 12:00:00") is False


def test_start_side_is_unchanged_by_this_rule() -> None:
    """负控：`time_start` 只取日期部分，本改动不影响它。"""
    assert multiturn.time_field_ok("time_start", "2018-01-01", "2018-01-01 00:00:00") is True
    assert multiturn.time_field_ok("time_start", "2018-01-02", "2018-01-01") is False


def test_none_still_false() -> None:
    """负控：`actual=None`（无完整计划）仍判不等，且由 `plans_missing` 单列。"""
    assert multiturn.time_field_ok("time_end", "2019-01-01", None) is False
