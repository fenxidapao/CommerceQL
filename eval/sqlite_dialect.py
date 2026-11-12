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
* `<标识符>::timestamp` 与 `CAST(<简单列> AS TIMESTAMP)` —— **只剥这个恒等标注**
  （U-184 补函数写法）：`CAST(x AS TIMESTAMP)` 在 SQLite 走 NUMERIC 亲和性，会把时间串
  截成四位年值（实测 `['2016','2016','2016']`）；再喂给 `strftime` 会按 Julian day
  解出固定值（`2017` → `-4707-06`）⇒ 月度分组恒 1 行。那是「跑得通但算错」，比报错更危险。

不翻的（原样保留、继续由 `eval/sqlite_pg_constructs.py` 点名）：
* `DATE_TRUNC('quarter', ...)`（PG 语义是季度首日，SQLite 无等价原语，实测报 no such function）；
* `<expr>::numeric` / `::date` / `::text`（改舍入 / 截时分 / 改比较语义）；
* `CAST(... AS 其它类型)` / 左值非简单列引用的 TIMESTAMP CAST、`ILIKE`、`INTERVAL`、`NOW()`、以及任何单位不认识的时间函数。

翻译策略（保守优先）：任何一项对不上（单位未登记、参数个数不对、括号不配平）就**原样保留**；
宁可让它照旧失败并暴露（`unknown_function` 是**可判**的），也不猜一个不等价的翻译。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

__all__ = [
    "DATE_TRUNC_UNITS",
    "EXTRACT_UNITS",
    "TO_CHAR_FORMATS",
    "normalize_time_params",
    "split_call_args",
    "strip_timestamp_casts",
    "translate_pg_functions",
]

#: ISO 日期/日期时间字面量（PG 接受 `T` 分隔，SQLite 的 TEXT 列只认空格分隔）。
_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?$")
#: 命名参数在 SQL 里的两种写法（在线 `%(name)s` / 评测 `:name`）。
_CLOSED_UPPER = re.compile(r"<=\s*%\(([^)]+)\)s|<=\s*:([A-Za-z_]\w*)")


def normalize_time_params(
    params: Mapping[str, Any], sql: str
) -> dict[str, Any]:
    """把时间绑定参数归一到 SQLite TEXT 列可比较的形态（U-183 / P2）。

    根因（`eval/olist/time_shape_probe.json`）：沙箱 `v_o_orders` 的 99,441 条时间戳
    全是空格分隔（``2016-09-04 21:15:19``）；在线契约按 PG 产出 `T` 分隔 ISO 或纯日期
    闭区间上界。SQLite 按字符串比较 ⇒ ``<= '2018-06-30'`` 漏掉当日全部数据、
    ``< '2018-07-01T00:00:00'`` 多算次日。实测 gold 5,614,133.04 / T 分隔 5,631,554.30 /
    纯日期闭区间 5,598,753.16 / 空格分隔 5,614,133.04。

    只改**值**，不改 SQL 文本 ⇒ 不进 LLM 请求体、匣带 key 不变、可 replay 验证。
    规则：
      ① 匹配 ISO 日期形态的值把 `T` 换成空格；
      ② 纯日期值且该参数在 SQL 中是 `<=` 的上界时补 ` 23:59:59`（闭合当日）；
      ③ 其余值（状态字面量、数值、下界 `<`/`>=`）**一律原样**。

    ⚠️ 这是评测侧方言桥，不是放宽判据：gold 用右开字面量，预测用闭区间，
    归一只让两侧在同一字符串序下表达同一个区间。
    """
    closed_uppers = {a or b for a, b in _CLOSED_UPPER.findall(sql)}
    out: dict[str, Any] = {}
    for key, val in params.items():
        if not isinstance(val, str):
            out[key] = val
            continue
        m = _ISO_DATE.match(val)
        if m is None:
            out[key] = val
            continue
        if m.group(2):
            out[key] = m.group(1) + " " + m.group(2)
        elif key in closed_uppers:
            out[key] = m.group(1) + " 23:59:59"
        else:
            out[key] = val
    return out

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
#: U-184：PG 里对 timestamp 列恒等的 `CAST(<简单列引用> AS TIMESTAMP)`。
#: 同样的「只认简单列引用」边界：函数/表达式左值、`AS 其它类型` 一律不剥。
_TIMESTAMP_CAST_FUNC = re.compile(
    r"\bCAST\s*\(\s*"
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)"
    r"\s+AS\s+TIMESTAMP\s*\)",
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
    """剥掉 PG 的**恒等**时间戳标注：`x::timestamp` 与 `CAST(x AS TIMESTAMP)`。

    U-184：函数写法与运算符写法在 PG 里是同一个恒等操作，SQLite 下却会把时间串
    截成四位年值（见模块 docstring 的陷阱实测）⇒ 两种形态同样必须剥。
    ⚠️ 只剥简单列引用，其它类型 CAST 与复杂左值原样保留（保守优先不变）。
    """
    return _TIMESTAMP_CAST_FUNC.sub(r"\1", _TIMESTAMP_CAST.sub(r"\1", sql))


def translate_pg_functions(sql: str) -> str:
    """把 PG 专有构造翻成 SQLite 等价写法（只用白名单内已验等价的形态）。"""
    text = strip_timestamp_casts(sql)
    text = _rewrite_calls(text, _DATE_TRUNC_CALL, _build_date_trunc)
    text = _rewrite_calls(text, _EXTRACT_CALL, _build_extract)
    return _rewrite_calls(text, _TO_CHAR_CALL, _build_to_char)
