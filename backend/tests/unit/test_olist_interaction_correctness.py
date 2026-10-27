"""交互正确性的**运行时**判据（W2；总控修正 #1）。

`reporter.py` 的 `passed=bool(verdict.equivalent)` 对交互题恒 False（verdict 恒 None），
拿它统计会永远得到 0/5。正确判据与 `runner.score_case` 同一条：
`terminal_event == expected_behavior and infra_error is None`。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from eval.olist import report_olist as P  # noqa: E402


def _record(**overrides):
    base = {
        "expected_behavior": "clarify",
        "terminal_event": "clarify",
        "infra_error": None,
        "verdict": None,
    }
    base.update(overrides)
    return base


def test_correct_terminal_counts() -> None:
    assert P.interaction_correct(_record()) is True


def test_wrong_terminal_does_not_count() -> None:
    assert P.interaction_correct(_record(terminal_event="execute")) is False


def test_infra_error_does_not_count_even_with_right_terminal() -> None:
    assert P.interaction_correct(_record(infra_error="TimeoutError: boom")) is False


def test_refuse_uses_the_same_judge() -> None:
    assert P.interaction_correct(
        _record(expected_behavior="refuse", terminal_event="refuse")
    ) is True
    assert P.interaction_correct(
        _record(expected_behavior="refuse", terminal_event="execute")
    ) is False


def test_judge_does_not_use_verdict_equivalent() -> None:
    """三态样本已证明判据独立；这里再从源码层防回退。"""
    source = inspect.getsource(P.interaction_correct)
    assert "equivalent" not in source
    assert "verdict" not in source


def test_false_clarify_and_execute_with_verdict_are_not_interaction_success() -> None:
    execute_record = _record(
        expected_behavior="execute",
        terminal_event="clarify",
        verdict={"equivalent": True},
    )
    assert P.interaction_correct(execute_record) is False
