"""PG → SQLite 的**方言渲染器**（ADR-18 的「仅替换：方言渲染器 → SQLite」那一半，U-167）。

为什么需要它：`backend/app/planner/payloads.py:109-121` 的 `DIALECT_NOTE` 逐字写着
「目标数据库：PostgreSQL 16（扩展：pgvector）」，它是 `PromptContext.dialect_note` 的默认值
（`:815`）并直接进载荷（`:840`）⇒ 模型产 `TO_CHAR(...)` 是**照我方要求**写的，不是乱写。
而 `eval/sqlite_exec.py` 原来只把 `%(name)s` 改成 `:name`，PG 函数原样落到 SQLite ⇒
`exec_error_class=unknown_function`、终态 `SQL_SYNTAX_ERROR`（r8 实测 `mt06` 的 turn1 与
turn2 均如此，repair 三轮仍是同码同类 ⇒ 不是 repair 能救的）。

翻译策略（保守优先）：
* 只翻**白名单内且格式已验等价**的 `TO_CHAR(<expr>, <fmt>)`；
* 任何一项对不上（格式未登记、参数个数不对、括号不配平）就**原样保留**；
* 宁可让它照旧失败并暴露（`unknown_function` 是**可判**的），也不猜一个不等价的翻译 ——
  那会把「方言不支持」静默变成「算错了一个数」。
"""

from __future__ import annotations

__all__ = ["TO_CHAR_FORMATS", "split_call_args", "translate_pg_functions"]

#: `TO_CHAR` 的 PG 格式 → SQLite `strftime` 格式（只收已验证等价的几种）。
TO_CHAR_FORMATS: dict[str, str] = {
    "YYYY-MM": "%Y-%m",
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYYMM": "%Y%m",
    "YYYY": "%Y",
    "MM": "%m",
}


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


def translate_pg_functions(sql: str) -> str:
    """把 PG 专有函数翻成 SQLite 等价写法（当前只处理 `TO_CHAR`）。"""
    lowered = sql.lower()
    parts: list[str] = []
    cursor = 0
    while True:
        at = lowered.find("to_char(", cursor)
        if at < 0:
            parts.append(sql[cursor:])
            break
        head = sql[cursor:at]
        open_at = at + len("to_char")
        split = split_call_args(sql, open_at + 1)
        if split is None:
            parts.append(sql[cursor:open_at + 1])
            cursor = open_at + 1
            continue
        args, close_at = split
        translated: str | None = None
        if len(args) == 2:
            fmt_raw = args[1].strip()
            if len(fmt_raw) >= 2 and fmt_raw[0] == "'" and fmt_raw[-1] == "'":
                mapped = TO_CHAR_FORMATS.get(fmt_raw[1:-1])
                if mapped is not None:
                    translated = f"strftime('{mapped}', {args[0]})"
        if translated is None:
            parts.append(sql[cursor:close_at + 1])
        else:
            parts.append(head)
            parts.append(translated)
        cursor = close_at + 1
    return "".join(parts)
