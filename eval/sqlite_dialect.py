"""PG → SQLite 的**方言渲染器**（ADR-18 的「仅替换：方言渲染器 → SQLite」那一半，U-167／U-174）。

为什么需要它：`backend/app/planner/payloads.py:109-121` 的 `DIALECT_NOTE` 逐字写着
「目标数据库：PostgreSQL 16（扩展：pgvector）」，它是 `PromptContext.dialect_note` 的默认值
（`:815`）并直接进载荷（`:840`）⇒ 模型产 PG 专有构造是**照我方要求**写的，不是乱写。
而 `eval/sqlite_exec.py` 原来只把 `%(name)s` 改成 `:name`，PG 函数原样落到 SQLite ⇒
`exec_error_class=unknown_function`、终态 `SQL_SYNTAX_ERROR`。

翻译范围（U-174 扩白名单，取证 = `eval/olist/probe_dialect_forms.json`）：
* `TO_CHAR(<expr>, <fmt>)` —— 5 种已验格式（U-167）；
* `DATE_TRUNC('year'|'month'|'day', <expr>)` —— 三种单位的年初／月初／当日样本已出；
* `EXTRACT(YEAR|MONTH|DAY|QUARTER FROM <expr>)` —— 四种单位样本已出；
* `<标识符>::timestamp` —— **只剥运算符、不转 CAST**：`CAST(x AS TIMESTAMP)` 在 SQLite
  走 NUMERIC 亲和性，会把时间串截成四位年值（实测 `['2016','2016','2016']`）——
  那是「跑得通但算错」，比报错更危险。

不翻的（原样保留、继续由 `eval/sqlite_pg_constructs.py` 点名）：
* `DATE_TRUNC('quarter', ...)`（PG 语义是季度首日，SQLite 无等价原语，实测报 no such function）；
* `<expr>::numeric` / `::date` / `::text`（改舍入 / 截时分 / 改比较语义）；
* `CAST(...)`、`ILIKE`、`INTERVAL`、`NOW()`、以及任何单位不认识的时间函数。

翻译策略（保守优先）：任何一项对不上（单位未登记、参数个数不对、括号不配平）就**原样保留**；
宁可让它照旧失败并暴露（`unknown_function` 是**可判**的），也不猜一个不等价的翻译。
"""

from __future__ import annotations

import re
from collections.abc import Callable

__all__ = [
    "DATE_TRUNC_UNITS",
    "EXTRACT_UNITS",
    "TO_CHAR_FORMATS",
    "split_call_args",
    "strip_timestamp_casts",
    "translate_pg_functions",
]

#: `TO_CHAR` 的 PG 格式 → SQLite `strftime` 格式（只收已验证等价的几种）。
TO_CHAR_FORMATS: dict[str, str] = {
    "YYYY-MM": "%Y-%m",
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYYMM": "%Y%m",
    "YYYY": "%Y",
    "MM": "%m",
}

#: `DATE_TRUNC` 可证等价的单位 → `strftime` 首日格式（U-174 取证件的三种样本）。
DATE_TRUNC_UNITS: dict[str, str] = {
    "year": "%Y-01-01",
    "month": "%Y-%m-01",
    "day": "%Y-%m-%d",
}

#: `EXTRACT` 可证等价的单位 → 取值表达式模板（`quarter` 用整数除法）。
EXTRACT_UNITS: dict[str, str] = {
    "year": "CAST(strftime('%Y', {expr}) AS INTEGER)",
    "month": "CAST(strftime('%m', {expr}) AS INTEGER)",
    "day": "CAST(strftime('%d', {expr}) AS INTEGER)",
    "quarter": "((CAST(strftime('%m', {expr}) AS INTEGER) + 2) / 3)",
}

_TO_CHAR_CALL = re.compile(r"\bTO_CHAR\s*\(", re.IGNORECASE)
_DATE_TRUNC_CALL = re.compile(r"\bDATE_TRUNC\s*\(", re.IGNORECASE)
_EXTRACT_CALL = re.compile(r"\bEXTRACT\s*\(", re.IGNORECASE)
_EXTRACT_FROM = re.compile(r"^\s*([A-Za-z]+)\s+FROM\s+(.+)$", re.IGNORECASE | re.DOTALL)
_LITERAL = re.compile(r"'([^']*)'")
#: 只认「标识符（可带一处表前缀）::timestamp」——更复杂的左值不做词法分析，留给原样保留。
_TIMESTAMP_CAST = re.compile(
    r"(\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)::timestamp\b",
    re.IGNORECASE,
)


def split_call_args(text: str, start: int) -> tuple[list[str], int] | None:
    """从 `text[start]`（左括号之后）切出顶层参数，返回 `(参数列表, 右括号下标)`。

    只做括号与引号的深度扫描，不解释 SQL；解析不出返回 `None`，由调用方原样保留。
    """
    depth = 0
    args: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == '"' or ch == "'":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            if depth == 0:
                args.append("".join(buf).strip())
                return args, i
            depth -= 1
            buf.append(ch)
            i += 1
            continue
        if ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    return None


def _rewrite_calls(sql: str, pattern: re.Pattern[str], build: Callable[[list[str]], str | None]) -> str:
    """按 `pattern` 逐个调用点改写；`build` 返回 `None` 表示「翻不动」⇒ 该调用原样保留。"""
    end = 0
    while True:
        match = pattern.search(sql, end)
        if match is None:
            return sql
        split = split_call_args(sql, match.end())
        if split is None:
            end = match.end()
            continue
        args, close_at = split
        replacement = build(args)
        if replacement is not None:
            sql = sql[: match.start()] + replacement + sql[close_at + 1 :]
            end = match.start() + len(replacement)
        else:
            end = close_at + 1


def _build_date_trunc(args: list[str]) -> str | None:
    if len(args) != 2:
        return None
    literal = _LITERAL.fullmatch(args[0].strip())
    if literal is None:
        return None
    fmt = DATE_TRUNC_UNITS.get(literal.group(1).lower())
    if fmt is None:
        return None
    return f"strftime('{fmt}', {args[1].strip()})"


def _build_extract(args: list[str]) -> str | None:
    if len(args) != 1:
        return None
    match = _EXTRACT_FROM.match(args[0])
    if match is None:
        return None
    template = EXTRACT_UNITS.get(match.group(1).lower())
    if template is None:
        return None
    return template.format(expr=match.group(2).strip())


def _build_to_char(args: list[str]) -> str | None:
    if len(args) != 2:
        return None
    literal = _LITERAL.fullmatch(args[1].strip())
    if literal is None:
        return None
    mapped = TO_CHAR_FORMATS.get(literal.group(1))
    if mapped is None:
        return None
    return f"strftime('{mapped}', {args[0].strip()})"


def strip_timestamp_casts(sql: str) -> str:
    """剥掉 `<标识符>::timestamp` 的运算符（不转 CAST —— 见模块 docstring 的陷阱实测）。"""
    return _TIMESTAMP_CAST.sub(r"\1", sql)


def translate_pg_functions(sql: str) -> str:
    """把 PG 专有构造翻成 SQLite 等价写法（只用白名单内已验等价的形态）。"""
    text = strip_timestamp_casts(sql)
    text = _rewrite_calls(text, _DATE_TRUNC_CALL, _build_date_trunc)
    text = _rewrite_calls(text, _EXTRACT_CALL, _build_extract)
    return _rewrite_calls(text, _TO_CHAR_CALL, _build_to_char)
