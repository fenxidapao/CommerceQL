"""结果行内存通道：`peek_rows` 只读、`take_rows` 取走即清。"""

from __future__ import annotations

from typing import Any, cast

from app.graph.context import GraphDeps, RunContext


def _context() -> RunContext:
    return RunContext(cast(GraphDeps, cast(Any, object())))


def test_peek_does_not_consume_and_take_clears() -> None:
    ctx = _context()
    assert ctx.peek_rows() == ()
    assert ctx.take_rows() == ()

    ctx.hold_rows([[1, "a"], [2, "b"]])
    expected = ((1, "a"), (2, "b"))
    assert ctx.peek_rows() == expected
    assert ctx.peek_rows() == expected, "peek 第二次仍应拿到同一份行"
    assert ctx.take_rows() == expected
    assert ctx.peek_rows() == (), "take 后通道必须为空"
    assert ctx.take_rows() == (), "take 是幂等的空读，不得复活旧行"


def test_hold_rows_copies_sequences_to_tuples() -> None:
    ctx = _context()
    source = [[1, None]]
    ctx.hold_rows(source)
    source[0][0] = 99
    assert ctx.peek_rows() == ((1, None),)
