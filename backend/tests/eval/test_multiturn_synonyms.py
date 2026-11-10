"""U-175（T-16 裁定 A）：同义词表归一 + 括注剥离 + 上界表示差单列。

依据：用户 2026-11-10 书面签 A —— 其一，建显式同义词表只按表归一（不子串匹配）；
其二，维持 `U-165`「不 bump」，`time_end` 的上界表示差在报告层单列、仍计 bad。
"""

from __future__ import annotations

from typing import Any

import multiturn


def _cmp(expect: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return multiturn.compare_expectation(expect, summary)


def test_annotation_is_stripped_on_dimensions() -> None:
    """正控：`date（month 粒度，绑定 …）` 剥离括注后与 `date` 等价。"""
    got = _cmp({"dimensions": ["date"]},
               {"dimensions": ["date（month 粒度，绑定 order.order_purchase_timestamp）"]})
    assert got["fields"]["dimensions"]["ok"] is True


def test_grain_synonym_group_is_equivalent() -> None:
    """正控：`month` 与 `月（year-month）` 同组 ⇒ 等价。"""
    got = _cmp({"grain": "month"}, {"grain": "月（year-month）"})
    assert got["fields"]["grain"]["ok"] is True


def test_grain_outside_group_still_differs() -> None:
    """反控：`month` 与 `weekly` 不同组 ⇒ 必须仍判不等。"""
    got = _cmp({"grain": "month"}, {"grain": "weekly"})
    assert got["fields"]["grain"]["ok"] is False


def test_no_substring_matching() -> None:
    """反控：不做子串匹配 —— `date` 与 `datex` 不等、filters 的表名前缀仍不等。"""
    assert _cmp({"dimensions": ["date"]}, {"dimensions": ["datex"]})["fields"]["dimensions"]["ok"] is False
    assert _cmp({"filters": ["customer_state = 'sp'"]},
                {"filters": ["order.customer_state = 'sp'"]})["fields"]["filters"]["ok"] is False


def test_time_end_upper_representation_is_single_listed() -> None:
    """正控：`2019-01-01` 与 `2018-12-31` 仍判不等，但在 summarize 里单列计数。"""
    raw: dict[str, Any] = {
        "turn": 1,
        "question": "2018 年 GMV 是多少？",
        "expect": {"time_end": "2019-01-01"},
        "terminal_event": "complete",
        "plan_summary": {"metrics": [], "time_range": {"start": "2018-01-01", "end": "2018-12-31"}},
        "history_seeded": False,
        "tokens": {},
        "cost_cny": 0.0,
    }
    rec = multiturn.score_case_turns("mt01", "ellipsis_time", [raw])
    assert rec["turns"][0]["comparison"]["fields"]["time_end"]["ok"] is False
    summary = multiturn.summarize([rec])
    assert summary["time_end_representation_diff"] == 1
