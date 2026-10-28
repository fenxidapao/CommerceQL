"""Olist SQLite 沙箱 → PG `app.o_*` 基表（app_rw 写）。

数据源 = `data/olist/olist_sandbox.db`（`build_olist_sandbox.py` 的产物，行/列与
`semantic/bundle_olist_2018.yaml` 逐列一致）。**不是**原始 `olist.sqlite`：用冻结沙箱
可以保证 PG 侧与 W2 的 gold 读数同源同列。

写入形态：生成 `COPY ... FROM STDIN (FORMAT text)`，经
`docker compose exec -T pg psql -U app_rw -d ecom` 灌入。全程不读 `.env`/密码，
也不在容器里挂宿主目录。

用法：
    python deploy/demo/load_olist_to_pg.py --exec
    python deploy/demo/load_olist_to_pg.py --out data/olist/olist_pg_load.sql
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final, TextIO

import yaml

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE: Final[Path] = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
DEFAULT_BUNDLE: Final[Path] = REPO_ROOT / "semantic" / "bundle_olist_2018.yaml"
DEFAULT_COMPOSE: Final[Path] = REPO_ROOT / "deploy" / "docker-compose.yml"
_TENANT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")


def _bundle_tables(bundle_path: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    """`[(SQLite 表/视图名, PG 基表名, 列名元组)]`，列序 = 语义包声明序。"""
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    tables: list[tuple[str, str, tuple[str, ...]]] = []
    for asset in data["assets"]:
        physical = str(asset["physical_asset"])
        if not physical.startswith("v_o_"):
            raise SystemExit(f"资产 {physical!r} 不是 Olist 的 v_o_* 命名 —— 拒绝混入合成包")
        tables.append(
            (
                physical,
                physical[2:],
                tuple(str(col["name"]) for col in asset["columns"]),
            )
        )
    return tables


def _verify_source_columns(
    cur: sqlite3.Cursor, tables: Sequence[tuple[str, str, tuple[str, ...]]]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for view, _base, columns in tables:
        actual = tuple(row[1] for row in cur.execute(f"PRAGMA table_info({view})"))
        if actual != columns:
            raise SystemExit(
                f"{view} 的列与语义包不一致：\n  sqlite = {actual}\n  bundle = {columns}"
            )
        counts[view] = int(cur.execute(f"SELECT count(*) FROM {view}").fetchone()[0])
    return counts


def _copy_value(value: Any) -> str:
    if value is None:
        return "\\N"
    if isinstance(value, str):
        return (
            value.replace("\\", "\\\\")
            .replace("\t", "\\t")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
    return str(value)


def _write_sql(
    out: TextIO,
    cur: sqlite3.Cursor,
    tables: Sequence[tuple[str, str, tuple[str, ...]]],
    *,
    tenant: str,
) -> None:
    out.write("\\set ON_ERROR_STOP on\n")
    out.write("BEGIN;\n")
    out.write(
        "SELECT set_config('app.tenant_id', "
        f"'{tenant}', true), set_config('app.shop_ids', '', true);\n"
    )
    bases = ", ".join(f"app.{base}" for _view, base, _cols in tables)
    out.write(f"TRUNCATE {bases};\n")
    for view, base, columns in tables:
        col_sql = ", ".join(columns)
        out.write(f"COPY app.{base} ({col_sql}) FROM STDIN WITH (FORMAT text);\n")
        select_sql = f"SELECT {col_sql} FROM {view}"
        for row in cur.execute(select_sql):
            out.write("\t".join(_copy_value(value) for value in row))
            out.write("\n")
        out.write("\\.\n")
    out.write("COMMIT;\n")
    for _view, base, _cols in tables:
        out.write(f"ANALYZE app.{base};\n")


def _psql_cmd(compose_path: Path, database: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(compose_path),
        "exec",
        "-T",
        "pg",
        "psql",
        "-X",
        "-U",
        "app_rw",
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "-",
    ]


def _run_exec(
    compose_path: Path,
    database: str,
    cur: sqlite3.Cursor,
    tables: Sequence[tuple[str, str, tuple[str, ...]]],
    *,
    tenant: str,
) -> None:
    env = dict(os.environ, PGCLIENTENCODING="UTF8")
    proc = subprocess.Popen(  # noqa: S603 - 固定参数，无用户拼接的命令
        _psql_cmd(compose_path, database),
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        env=env,
    )
    assert proc.stdin is not None
    writer = io.TextIOWrapper(proc.stdin, encoding="utf-8", newline="\n")
    try:
        _write_sql(writer, cur, tables, tenant=tenant)
        writer.flush()
    except BrokenPipeError:
        pass
    finally:
        writer.close()
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"psql 退出码 {rc} —— 装载失败（见上方 stderr）")


def _pg_counts(
    compose_path: Path,
    database: str,
    tables: Sequence[tuple[str, str, tuple[str, ...]]],
    *,
    tenant: str,
) -> dict[str, int]:
    query = f"SELECT set_config('app.tenant_id','{tenant}',true), set_config('app.shop_ids','',true); "
    query += " ".join(
        f"SELECT '{base}', count(*) FROM app.{base};" for _view, base, _cols in tables
    )
    proc = subprocess.run(  # noqa: S603 - 固定参数
        [
            "docker",
            "compose",
            "-f",
            str(compose_path),
            "exec",
            "-T",
            "pg",
            "psql",
            "-X",
            "-U",
            "app_rw",
            "-d",
            database,
            "-tA",
            "-c",
            query,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"复核查询失败：{proc.stderr.strip()}")
    bases = {base for _view, base, _cols in tables}
    counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 2 and parts[0] in bases:
            counts[parts[0]] = int(parts[1])
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist SQLite 沙箱 → PG app.o_* 基表")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--tenant", default="T_A")
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--database", default="ecom")
    parser.add_argument("--out", type=Path, default=None, help="只生成 SQL，不执行")
    parser.add_argument("--exec", action="store_true", help="经 docker compose exec psql 执行")
    args = parser.parse_args(argv)

    if not args.source.is_file():
        raise SystemExit(f"源沙箱不存在：{args.source}\n先跑 deploy/demo/build_olist_sandbox.py")
    if not args.bundle.is_file():
        raise SystemExit(f"语义包不存在：{args.bundle}")
    if not _TENANT_RE.match(args.tenant):
        raise SystemExit(f"tenant 只允许 [A-Za-z0-9_]：{args.tenant!r}")
    if not args.exec and args.out is None:
        raise SystemExit("必须给 --exec 或 --out（默认不往 stdout 灌 100MB）")

    tables = _bundle_tables(args.bundle)
    con = sqlite3.connect(f"file:{args.source}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        counts = _verify_source_columns(cur, tables)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("w", encoding="utf-8", newline="\n") as fh:
                _write_sql(fh, cur, tables, tenant=args.tenant)
            print(json.dumps({"out": str(args.out), "source_rows": counts}, ensure_ascii=False))
        if args.exec:
            _run_exec(args.compose, args.database, cur, tables, tenant=args.tenant)
            pg_counts = _pg_counts(args.compose, args.database, tables, tenant=args.tenant)
            expected = {base: counts[view] for view, base, _cols in tables}
            if pg_counts != expected:
                raise SystemExit(f"装载后行数不符：pg={pg_counts} expected={expected}")
            print(
                json.dumps(
                    {
                        "tenant": args.tenant,
                        "source_rows": counts,
                        "pg_rows": pg_counts,
                        "total": sum(pg_counts.values()),
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
