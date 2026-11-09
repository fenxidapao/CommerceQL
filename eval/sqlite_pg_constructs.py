"""PG 专有方言构造的显式暴露面（U-174；T-22 判据 ② 之㈡；纯函数、零副作用）。

背景（现读取证）：
  · `eval/sqlite_dialect.translate_pg_functions` 只改写**白名单内**的形态，其余一律**原样放过**；
    翻不动时执行期报 syntax error 或 no such function ⇒ 读数上它与「模型写错」长得一样；
  · 取证件：`eval/olist/probe_repair_equal_gold_pool.json`
    （`pool_n = 4`、`pool_judged_n = 0`、四条全被方言阻塞）、
    `eval/olist/probe_dialect_forms.json`（单位级可证性）。

本模块只做一件事：把「这条 SQL 里还有未注册的 PG 专有构造」**显式说出来**。
不翻译、不改写、不改判定。

⚠️ 判定必须**单位感知**：`DATE_TRUNC('month', ...)` 与 `EXTRACT(YEAR FROM ...)` 扩白名单后已可翻，
继续点名会与行为自相矛盾（已翻译的构造还被告警）。已知保守处：字符串字面量里出现的 `::`
也会命中（宁可多报，不做词法分析）。
"""

from __future__ import annotations

import re
from typing import Final

from sqlite_dialect import DATE_TRUNC_UNITS, EXTRACT_UNITS, TO_CHAR_FORMATS, split_call_args

__all__ = ["PG_ONLY_CONSTRUCTS", "unregistered_constructs"]

#: 一律不翻译、必须点名的构造 → 识别正则。
PG_ONLY_CONSTRUCTS: Final[dict[str, re.Pattern[str]]] = {
    #: `CAST(x AS TIMESTAMP)` 会静默算错（NUMERIC 亲和性），故 CAST 整体不翻。
    "CAST": re.compile(r"\bCAST\s*\(", re.IGNORECASE),
    "INTERVAL": re.compile(r"\bINTERVAL\b", re.IGNORECASE),
    "ILIKE": re.compile(r"\bILIKE\b", re.IGNORECASE),
    "NOW": re.compile(r"\bNOW\s*\(", re.IGNORECASE),
}

_DATE_TRUNC_CALL = re.compile(r"\bDATE_TRUNC\s*\(", re.IGNORECASE)
_EXTRACT_CALL = re.compile(r"\bEXTRACT\s*\(", re.IGNORECASE)
_CAST_OPERATOR = re.compile(r"::\s*([A-Za-z_][A-Za-z0-9_]*)")
_EXTRACT_FROM = re.compile(r"^\s*([A-Za-z]+)\s+FROM\s+(.+)$", re.IGNORECASE | re.DOTALL)
_LITERAL = re.compile(r"'([^']*)'")
_TO_CHAR = re.compile(r"\bTO_CHAR\s*\(", re.IGNORECASE)
#: 扩白名单里唯一被剥掉的转型运算符（只剥、不转 CAST）。
_REGISTERED_CAST_TYPES = frozenset({"timestamp"})


def _registered_date_trunc(args: list[str]) -> bool:
    if len(args) != 2:
        return False
    literal = _LITERAL.fullmatch(args[0].strip())
    return literal is not None and literal.group(1).lower() in DATE_TRUNC_UNITS


def _registered_extract(args: list[str]) -> bool:
    if len(args) != 1:
        return False
    match = _EXTRACT_FROM.match(args[0])
    return match is not None and match.group(1).lower() in EXTRACT_UNITS


def _to_char_unregistered(sql: str) -> bool:
    """有没有「格式不在白名单内」的 `TO_CHAR`（无法解析时按未注册处理）。"""
    if not _TO_CHAR.search(sql):
        return False
    for match in _TO_CHAR.finditer(sql):
        split = split_call_args(sql, match.end())
        if split is None:
            return True
        args = split[0]
        if len(args) != 2:
            return True
        literal = _LITERAL.fullmatch(args[1].strip())
        if literal is None or literal.group(1) not in TO_CHAR_FORMATS:
            return True
    return False


def unregistered_constructs(sql: str) -> tuple[str, ...]:
    """返回该 SQL 里**仍未注册**的 PG 专有构造名（升序、去重、空 tuple 表示没有）。"""
    text = sql or ""
    if not text.strip():
        return ()
    found: set[str] = set()
    for name, pattern, check in (
        ("DATE_TRUNC", _DATE_TRUNC_CALL, _registered_date_trunc),
        ("EXTRACT", _EXTRACT_CALL, _registered_extract),
    ):
        for match in pattern.finditer(text):
            split = split_call_args(text, match.end())
            if split is None or not check(split[0]):
                found.add(name)
                break
    for match in _CAST_OPERATOR.finditer(text):
        if match.group(1).lower() not in _REGISTERED_CAST_TYPES:
            found.add("::")
            break
    for name, pattern in PG_ONLY_CONSTRUCTS.items():
        if pattern.search(text):
            found.add(name)
    if _to_char_unregistered(text):
        found.add("TO_CHAR")
    return tuple(sorted(found))
