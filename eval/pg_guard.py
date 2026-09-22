"""W6 的 PG 接触面守卫 —— 只读不是"我保证"，而是要**被服务端拒绝过一次**才算。

为什么要有这个文件（2026-09-22，W7 提出"报全量读数时点名是否含集成层 / 能否加一条会响的守卫"）
----------------------------------------------------------------------------------------------
评测窗口的 PG 证据（G-4 的 RLS 有效性、并行少算的复现）必须连**共享实例**才拿得到，
所以"拒连共享 `ecom`"这条我方做不到、也不该假装做到 —— 做到就等于把 G-4 变回 UNVERIFIED。
能做且该做的是：**我方每一条 PG 会话都不许有写能力**，并且这件事要被机器验一次。

`open_readonly()` 做三件事，缺一就抛：
1. 连上后 `SET default_transaction_read_only = on`（服务端级，不靠我们自觉）；
2. `SHOW` 回来确认真的是 `on`（superuser 也拦得住，比"选只读角色"强：`app_ro` 是权限约束，
   而 GUC 约束连 `postgres` 角色也生效）；
3. **故意写一次**（`CREATE TABLE`）并期望被拒成 `ReadOnlySqlTransaction` —— 没被拒就说明
   这道闸是假的，当场抛，宁可让探针不出产物也不让它出一份"我们其实没锁住"的产物。

同时 `target_stamp()` 会把 `current_database()` / `current_user` / `server_version` 落成读数
⇒ 报告里能点名"这一轮连的是哪个库、以谁的身份"，但**永不含口令**（`redact_dsn` 只留 host:port/db）。
"""

from __future__ import annotations

import re
from typing import Any

import psycopg

__all__ = ["PgReadOnlyGuardError", "force_readonly", "open_readonly", "redact_dsn", "target_stamp"]


#: 编进连接串的会话级 GUC ⇒ 同一个 DSN 常量的**每一条**连接都自动受约束（不用逐处改 `connect`）。
_RO_OPTIONS = "-c default_transaction_read_only=on"


def force_readonly(dsn: str) -> str:
    """给 DSN 加上 `options=-c default_transaction_read_only=on`（幂等）。

    ⚠️ 这不是"我自己小心点"，而是**服务端**在每条事务上把关；`open_readonly()` 会故意下发一次
    `CREATE TABLE` 来证明它真的生效。两者都过，才允许探针继续出产物。
    """
    if "default_transaction_read_only" in dsn:
        return dsn
    sep = "&" if "?" in dsn else "?"
    # ⚠️ 空格**和**等号都要编码：libpq 解析 URI 查询串时会把值里的 `=` 当成键值分隔符，
    # 实测 `?options=-c%20default_transaction_read_only=on` 直接抛
    # `ProgrammingError: extra key/value separator "=" in URI query parameter: "options"`。
    return f"{dsn}{sep}options={_RO_OPTIONS.replace(' ', '%20').replace('=', '%3D')}"


class PgReadOnlyGuardError(RuntimeError):
    """只读闸门没锁住（或被服务端拒绝生效）—— 宁可不出产物。"""


_DSN_SHAPE = re.compile(r"(?P<scheme>[a-z+]+)://(?P<user>[^:@/]*)(?::[^@]*)?@(?P<host>[^/?]+)(?P<path>/[^?#]*)?")


def redact_dsn(dsn: str) -> str:
    """把 DSN 缩成 `user@host:port/db` —— 口令段一律丢掉（本模块的任何产物都不落凭据）。"""
    m = _DSN_SHAPE.search(dsn or "")
    if not m:
        return "<无法解析的 DSN 形状：不落盘>"
    return f"{m.group('user')}@{m.group('host')}{m.group('path') or ''}"


async def open_readonly(dsn: str, *, purpose: str) -> Any:
    """连一把**已被证明只读**的 async 连接。`purpose` 只进异常文案，方便点名是谁在用。"""
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    await conn.execute("SET default_transaction_read_only = on")
    shown = await conn.execute("SHOW default_transaction_read_only")
    value = (await shown.fetchone())[0]
    if str(value).lower() not in {"on", "true", "1"}:
        await conn.close()
        raise PgReadOnlyGuardError(f"{purpose}：SET 之后 SHOW 回来是 {value!r}，只读闸门没生效")
    try:
        await conn.execute("CREATE TABLE IF NOT EXISTS _w6_readonly_guard_probe (x integer)")
    except psycopg.errors.ReadOnlySqlTransaction:
        pass  # ← 这就是我们要的读数：写请求被服务端拒了
    else:
        await conn.close()
        raise PgReadOnlyGuardError(
            f"{purpose}：故意下发 CREATE TABLE **没有被拒** ⇒ 该会话不是只读，"
            f"目标 = {redact_dsn(dsn)}；宁可不出产物，也不出一份「没锁住」的产物"
        )
    return conn


async def target_stamp(conn: Any) -> dict[str, Any]:
    """这条会话到底连到了哪、以谁的身份、闸门在不在 —— 进产物，供跨窗口点名。"""
    row = await (await conn.execute(
        "select current_database(), current_user, "
        "current_setting('default_transaction_read_only'), version()"
    )).fetchone()
    return {
        "database": row[0],
        "role": row[1],
        "read_only_enforced": str(row[2]).lower() in {"on", "true", "1"},
        "write_attempt_rejected": True,  # open_readonly() 已经故意写过一次并被拒
        "server": str(row[3]).split(",")[0],
    }
