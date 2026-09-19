#!/usr/bin/env python3
"""把 W1A 的 SQLite 沙箱灌进 PG 的 `app.*` 业务底表 —— §16.5 压测的数据前置。

归属：W7（`deploy/loadtest/**`）。**不生成数据、不改 DDL**：
数据来自 W1A 的 `data/generator/seed_generator.py`（确定性、附录 C §C.12 规模），
表结构来自 W1B 的迁移 `0003_business_views`（`app.<base>` 底表 + `app.v_*` 视图）。

## 这个脚本为什么存在（不是"多此一举"）

07 U-56 裁定：`v_*` 视图与基表的 DDL 归 W1B 迁移，**"数据装载另行裁定"**。
2026-09-18 实测：迁移已到 head `0005`，8 张底表**全在但 0 行**，
容器内 `/data/sandbox/` 也是空的 ⇒ §16.5 要求的"合成数据集全量"在本机**任何引擎里都不存在**。
没有装载步骤，压测就只能对着空库跑（快，但完全不成立）。

## 为什么用 COPY 而不是逐条 INSERT

`traffic_daily` 目标 150 万行。逐条 INSERT 在这台 Docker Desktop 上是小时级
（05 附录 D §E-2 明写："大批量灌数用容器内脚本而非宿主→容器逐条写"）；
COPY 走文本协议，百万行是分钟级。

## 列不对齐时**炸掉**而不是猜

装载错列的失败形态是"压测跑得通、数出来很像样"，那是最坏的一种错。
所以：表名映射靠 `v_X → app.X` 的机械规则，列集**必须完全相等**（缺列/多列都 abort），
文本值里出现制表符或换行也 abort（COPY 的分隔符会被静默污染）。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections.abc import Iterable
from typing import Any

import psycopg

#: SQLite 沙箱表 → PG 底表。**dim_tenant 刻意不在表里**：PG 侧没有对应底表
#: （租户维度由 `app.policy` + RLS 承担），跳过它必须被打印出来，不能静默。
SKIP_SQLITE_TABLES = {"dim_tenant"}
DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/ecom"
BATCH = 50_000


def _sqlite_columns(con: sqlite3.Connection, table: str) -> list[str]:
    # 表名来自沙箱自身的 sqlite_master 列表，不是外部输入
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _pg_columns(con: psycopg.Connection, table: str) -> dict[str, str]:
    rows = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema='app' and table_name=%s order by ordinal_position",
        (table,),
    ).fetchall()
    return dict(rows)


def _cast(value: Any, pg_type: str) -> Any:
    """SQLite 没有 boolean 类型（存 0/1），PG 有 ⇒ 只转这一类，其余交给驱动适配。"""
    if pg_type == "boolean" and value is not None and not isinstance(value, bool):
        return value in (1, "1", "t", "true", True)
    return value


def _rows(con: sqlite3.Connection, table: str, cols: list[str], types: list[str]) -> Iterable[tuple]:
    """产出**元组**行（不是拼好的字符串）。

    ⚠️ 两个坑都是实测出来的：
    ① 曾按 psycopg2 的写法调 `cur.copy(sql, iterable)` —— psycopg **3.3.5** 的第二个位置参数
       是 `params`，且返回的是一个**没有进入的 context manager**：于是一行都不写、也不报错，
       八张表全部静默灌进 0 行。所以这里产出元组，由调用方 `with cur.copy(...) as cp: cp.write_row(row)`。
    ② `write_row` 让驱动负责 NULL 与转义 ⇒ 不再手拼制表符文本，
       "值里含 tab/换行会改变列数"这一类问题从根上消失。
    """
    # 列名来自两侧元数据比对（不是用户输入），所以这里的 f-string 拼接是安全的
    sql = f"select {', '.join(cols)} from {table}"
    cur = con.execute(sql)
    while chunk := cur.fetchmany(BATCH):
        for row in chunk:
            yield tuple(_cast(v, t) for v, t in zip(row, types, strict=True))


def _scalar(con: psycopg.Connection, sql: str) -> int:
    """取一个标量计数。`fetchone()` 的类型是 `tuple | None` ⇒ 不判空就是在赌它有行。"""
    row = con.execute(sql).fetchone()
    assert row is not None, f"聚合查询没有返回行：{sql}"
    return int(row[0])


def plan(sandbox: sqlite3.Connection) -> list[tuple[str, str]]:
    """[(沙箱表, PG 底表)]，按机械规则 `v_X → X`；跳过项打印出来。"""
    out = []
    for (table,) in sandbox.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
    ).fetchall():
        if table in SKIP_SQLITE_TABLES:
            print(f"[跳过] 沙箱表 {table} 在 PG 侧无对应底表（租户维度由 app.policy + RLS 承担）")
            continue
        base = table.removeprefix("v_")
        out.append((table, base))
    return out


def load(args: argparse.Namespace) -> int:
    sandbox = sqlite3.connect(args.sqlite)
    with psycopg.connect(args.dsn, autocommit=False) as pg:
        pairs = plan(sandbox)
        rows_report: list[tuple[str, int, int]] = []
        for s_table, base in pairs:
            s_cols = _sqlite_columns(sandbox, s_table)
            p_cols = _pg_columns(pg, base)
            if not p_cols:
                print(f"[中止] PG 里没有 app.{base} ⇒ W1B 的 0003 迁移没跑到这一版，别硬灌")
                return 2
            if set(s_cols) != set(p_cols):
                print(f"[中止] {s_table} 与 app.{base} 列集不等\n"
                      f"  只在沙箱: {sorted(set(s_cols) - set(p_cols))}\n"
                      f"  只在 PG : {sorted(set(p_cols) - set(s_cols))}")
                return 2
            types = [p_cols[c] for c in s_cols]
            existing = _scalar(pg, f"select count(*) from app.{base}")
            if existing and not args.force:
                print(f"[中止] app.{base} 已有 {existing} 行 ⇒ 可能不是空库（别人的装载？）。"
                      "确认要覆盖再加 --force")
                return 2
            s_count = sandbox.execute(f"select count(*) from {s_table}").fetchone()[0]
            if args.dry_run:
                print(f"[dry-run] {s_table} → app.{base}: 沙箱 {s_count} 行，列 {len(s_cols)} 个 齐")
                continue
            started = time.perf_counter()
            # 不 CASCADE：`v_*` 视图依赖这些底表，CASCADE 会把 8 个视图一起删掉（那是 W1B 的迁移产物）
            pg.execute(f"truncate app.{base}")
            with pg.cursor() as cur, cur.copy(
                f"COPY app.{base} ({', '.join(s_cols)}) FROM STDIN"
            ) as cp:
                for row in _rows(sandbox, s_table, s_cols, types):
                    cp.write_row(row)
            pg.execute(f"analyze app.{base}")
            pg.commit()
            got = _scalar(pg, f"select count(*) from app.{base}")
            took = time.perf_counter() - started
            rows_report.append((base, s_count, got))
            print(f"[灌入] app.{base}: 沙箱 {s_count} → PG {got}  ({took:.1f}s)"
                  + ("" if got == s_count else "  ⚠️ 行数不等"))
        if args.dry_run:
            return 0
        bad = [r for r in rows_report if r[1] != r[2]]
        print("\n| 表 | 沙箱 | PG | 一致 |")
        print("|---|---|---|---|")
        for base, want, got in rows_report:
            print(f"| app.{base} | {want} | {got} | {'✅' if want == got else '❌'} |")
        if bad:
            print(f"\n[失败] {len(bad)} 张表行数不等 ⇒ 回执不可信，别拿这组数据压测", file=sys.stderr)
            return 3
        # 视图可读性：底表灌完不等于 `v_*` 能用（列/权限任一处缺都会让 exec 节点报"表不存在"）。
        # ⚠️ 必须带身份 GUC 才测得出东西：`app.order_paid` 上是 **FORCE ROW LEVEL SECURITY**，
        #    策略为 `tenant_id = current_setting('app.tenant_id', true)`
        #    **AND** (`current_setting('app.shop_ids', true)` = '' **OR** shop_id = ANY(...))。
        #    两个 GUC 都不设时第二个谓词整体求值为 **NULL**（不是 true）⇒ 任何一行都不满足，
        #    连超级用户走视图都是 0 行（2026-09-19 实测）。所以"视图 0 行"**不是**装载失败，
        #    而是没给身份 —— 这里显式设成 T_A/'' 来区分这两种情况。
        for (view,) in pg.execute(
            "select viewname from pg_views where schemaname='app' and viewname like 'v_%' order by 1"
        ).fetchall():
            pg.execute("select set_config('app.tenant_id', %s, false)", (args.tenant_id,))
            pg.execute("select set_config('app.shop_ids', '', false)")
            n = _scalar(pg, f"select count(*) from app.{view}")
            print(f"[视图] app.{view} 以 tenant={args.tenant_id} 可读 {n} 行")
        print("\n[完成] 底表与视图均通过；下一步用 app_ro 角色复核只读路径（GRANT 由 0001/0003 迁移负责）")
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SQLite 沙箱 → PG app.* 底表装载（W7 压测前置）")
    p.add_argument("--sqlite", required=True, help="seed_generator.py 的产物路径")
    p.add_argument("--dsn", default=DEFAULT_DSN, help="必须是有 CREATE/TRUNCATE 权的属主串；默认本机开发实例")
    p.add_argument("--dry-run", action="store_true", help="只比对列集与行数，不写")
    p.add_argument("--force", action="store_true", help="允许覆盖已有行的底表")
    p.add_argument("--tenant-id", default="T_A",
                   help="视图可读性核对用的租户（必须与沙箱数据里的 tenant_id 一致，否则 0 行是策略生效不是装载失败）")
    args = p.parse_args(argv)
    return load(args)


if __name__ == "__main__":
    raise SystemExit(main())
