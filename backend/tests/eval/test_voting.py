"""U-183 / P2：结果多数投票的穿点控制（正控 + 负控）。"""

from __future__ import annotations

import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL_DIR))

from voting import result_digest, vote_by_result  # noqa: E402


def test_majority_wins() -> None:
    a, b = result_digest([(1,)]), result_digest([(2,)])
    got = vote_by_result([
        {"digest": a, "equivalent": False},
        {"digest": b, "equivalent": True},
        {"digest": b, "equivalent": True},
    ])
    assert got["winner"] == 1
    assert got["vote_size"] == 2
    assert got["n_distinct"] == 2
    assert got["arms_equivalent"] == [True, True]


def test_failed_arms_do_not_vote() -> None:
    a = result_digest([(1,)])
    got = vote_by_result([
        {"digest": None, "equivalent": False},
        {"digest": a, "equivalent": True},
        {"digest": None, "equivalent": False},
    ])
    assert got["winner"] == 1
    assert got["n_valid"] == 1
    assert got["vote_size"] == 1


def test_all_failed_returns_no_winner() -> None:
    got = vote_by_result([{"digest": None}, {"digest": None}])
    assert got["winner"] is None
    assert got["vote_size"] == 0
    assert got["n_valid"] == 0


def test_tie_is_deterministic_first_index() -> None:
    a, b = result_digest([(1,)]), result_digest([(2,)])
    for _ in range(3):
        got = vote_by_result([{"digest": a}, {"digest": b}])
        assert got["winner"] == 0
        assert got["tied"] is True
        assert got["tie_size"] == 2


def test_digest_is_stable_and_order_sensitive() -> None:
    assert result_digest([(1, "a")]) == result_digest([(1, "a")])
    assert result_digest([(1, "a"), (2, "b")]) != result_digest([(2, "b"), (1, "a")])


def test_vote_does_not_peek_at_gold() -> None:
    """打乱 equivalent 标记不得改变选臂结果。"""
    a, b = result_digest([(1,)]), result_digest([(2,)])
    one = vote_by_result([{"digest": a, "equivalent": True},
                          {"digest": b, "equivalent": False},
                          {"digest": a, "equivalent": False}])
    two = vote_by_result([{"digest": a, "equivalent": False},
                          {"digest": b, "equivalent": True},
                          {"digest": a, "equivalent": True}])
    assert (one["winner"], one["vote_size"]) == (two["winner"], two["vote_size"]) == (0, 2)
