"""PG 专有方言构造的显式暴露面（U-174；T-22 判据 ② 之㈡；纯函数、零副作用）。

背景（现读取证）：
  · `eval/sqlite_dialect.translate_pg_functions` 只改写**白名单内**的
    `TO_CHAR(<expr>, <fmt>)`（`TO_CHAR_FORMATS` 恰 5 条），其余构造一律**原样放过**；
  · 于是方言翻不动在执行期表现为 syntax error 或 no such function（SQLite 原话带引号，
    此处不复述）⇒ 读数上它与「模型写错」长得一样；
  · 取证件：`eval/olist/probe_repair_equal_gold_pool.json`
    （`pool_n = 4`、`pool_judged_n = 0`、四条全被方言阻塞）。

本模块只做一件事：把「这条 SQL 里有未注册的 PG 专有构造」**显式说出来**。
不翻译、不改写、不改判定，也不改变 `translate_pg_functions` 的任何行为。
已知保守处：字符串字面量里出现的 `::` 也会命中（宁可多报，不做词法分析）。
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["PG_ONLY_CONSTRUCTS", "unregistered_constructs"]

#: 构造名 → 识别正则。只收「SQLite 侧没有等价物」的 PG 专有写法。
PG_ONLY_CONSTRUCTS: Final[dict[str, re.Pattern[str]]] = {
    "EXTRACT": re.compile(r"\bEXTRACT\s*\(", re.IGNORECASE),
    "CAST": re.compile(r"\bCAST\s*\(", re.IGNORECASE),
    "::": re.compile(r"::"),
    "DATE_TRUNC": re.compile(r"\bDATE_TRUNC\s*\(", re.IGNORECASE),
    "INTERVAL": re.compile(r"\bINTERVAL\b", re.IGNORECASE),
    "ILIKE": re.compile(r"\bILIKE\b", re.IGNORECASE),
    "NOW": re.compile(r"\bNOW\s*\(", re.IGNORECASE),
}

_TO_CHAR = re.compile(r"\bTO_CHAR\s*\(", re.IGNORECASE)
_FORMAT_LITERAL = re.compile(r"'([^']*)'")


def _to_char_unregistered(sql: str) -> bool:
    """有没有「格式不在白名单内」的 `TO_CHAR`（无法解析时按未注册处理）。"""
    if not _TO_CHAR.search(sql):
        return False
    try:
        from sqlite_dialect import TO_CHAR_FORMATS, split_call_args
    except Exception:  # noqa: BLE001 - 缺依赖时按未注册处理，不静默放过
        return True
    for match in _TO_CHAR.finditer(sql):
        try:
            #: `split_call_args(text, start)` 的 `start` 是**左括号之后**的下标，
            #: 且返回 `(参数列表, 右括号下标)` 或 `None`（见 eval/sqlite_dialect.py:31-74）
            #: ⇒ 传 `match.end()`（紧跟左括号之后），并先拆元组再取参数列表。
            split = split_call_args(sql, match.end())
            if split is None:
                return True
            args = split[0]
        except Exception:  # noqa: BLE001 - 括号不配等
            return True
        #: `split_call_args` 在括号不配/解析不了时返回 `None` ⇒ 按未注册处理，不静默放过。
        if args is None or len(args) != 2:
            return True
        literal = _FORMAT_LITERAL.fullmatch(args[1].strip())
        if literal is None or literal.group(1) not in TO_CHAR_FORMATS:
            return True
    return False


def unregistered_constructs(sql: str) -> tuple[str, ...]:
    """返回该 SQL 里出现过的**未注册** PG 专有构造名（升序、去重、空 tuple 表示没有）。"""
    text = sql or ""
    if not text.strip():
        return ()
    found = {name for name, pattern in PG_ONLY_CONSTRUCTS.items() if pattern.search(text)}
    if _to_char_unregistered(text):
        found.add("TO_CHAR")
    return tuple(sorted(found))
