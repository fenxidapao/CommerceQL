#!/usr/bin/env python
"""从原始 Olist SQLite 生成评测沙箱库。

归属窗口：W1 实施窗（`docs/07 §4.8` 的 `U-143`）。

产物 `data/olist/olist_sandbox.db`（gitignore，`*.db`）必须满足三件事，
否则 `eval/sqlite_exec.py::open_sandbox_connection` 用不了它：

1. 物理表名**恰好等于**语义包的 `physical_asset`（`v_o_*`）—— 它按资产名建 TEMP VIEW；
2. 每张表带 `tenant_id` 列 —— TEMP VIEW 的过滤条件就是 `tenant_id = '<t>'`；
3. `tenant_id` 值来自 `--tenant`（默认 `T_A`），**本脚本只装一个租户的行** ——
   因此 `T_B` 查空是**平凡成立**的，只能证明 TEMP VIEW 的过滤谓词生效，
   **不能**证明真实跨租户隔离（见 `eval/olist/README.md` 的已知偏差第 4 条）。

本脚本只写 `data/olist/**` 与 `eval/olist/sandbox_manifest.json`（后者经
`olist.build_dataset.write_json` 的落盘守卫）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "eval"
for _p in (str(REPO_ROOT), str(EVAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _bootstrap  # noqa: E402

from eval.olist.build_dataset import write_json  # noqa: E402

# `open_sandbox_connection` 走的是在线 exec 的真实代码路径（ADR-18），
# 需要 backend/ 在 sys.path 上、环境默认值已补齐 —— 与 eval 侧同一套引导。
_bootstrap.bootstrap()

DEFAULT_TENANT = "T_A"
BOUNDARY_TENANT = "T_B"

#: `(表名, 列定义, 取数 SQL)`。表名 = 语义包 `physical_asset`，改名会同时废掉两边。
TABLES: tuple[tuple[str, str, str], ...] = (
    (
        "v_o_orders",
        """
        tenant_id                  TEXT    NOT NULL,
        order_id                   TEXT    NOT NULL,
        customer_id                TEXT,
        customer_unique_id         TEXT,
        customer_state             TEXT,
        customer_city              TEXT,
        order_status               TEXT,
        order_purchase_timestamp   TEXT,
        order_approved_at          TEXT,
        order_delivered_customer_date TEXT,
        order_estimated_delivery_date TEXT
        """,
        """
        SELECT ?, o.order_id, o.customer_id, c.customer_unique_id,
               c.customer_state, c.customer_city, o.order_status,
               o.order_purchase_timestamp, o.order_approved_at,
               o.order_delivered_customer_date, o.order_estimated_delivery_date
        FROM src.orders o
        LEFT JOIN src.customers c ON c.customer_id = o.customer_id
        """,
    ),
    (
        "v_o_order_items",
        """
        tenant_id          TEXT    NOT NULL,
        order_id           TEXT    NOT NULL,
        order_item_id      INTEGER NOT NULL,
        product_id         TEXT,
        seller_id          TEXT,
        shipping_limit_date TEXT,
        price              REAL,
        freight_value      REAL
        """,
        """
        SELECT ?, i.order_id, i.order_item_id, i.product_id, i.seller_id,
               i.shipping_limit_date, i.price, i.freight_value
        FROM src.order_items i
        """,
    ),
    (
        "v_o_products",
        """
        tenant_id             TEXT NOT NULL,
        product_id            TEXT NOT NULL,
        product_category_name TEXT,
        product_category      TEXT,
        product_weight_g      REAL,
        product_photos_qty    REAL
        """,
        """
        SELECT ?, p.product_id, p.product_category_name,
               t.product_category_name_english AS product_category,
               p.product_weight_g, p.product_photos_qty
        FROM src.products p
        LEFT JOIN src.product_category_name_translation t
               ON t.product_category_name = p.product_category_name
        """,
    ),
    (
        "v_o_payments",
        """
        tenant_id            TEXT    NOT NULL,
        order_id             TEXT    NOT NULL,
        payment_sequential   INTEGER NOT NULL,
        payment_type         TEXT,
        payment_installments INTEGER,
        payment_value        REAL
        """,
        """
        SELECT ?, p.order_id, p.payment_sequential, p.payment_type,
               p.payment_installments, p.payment_value
        FROM src.order_payments p
        """,
    ),
    (
        "v_o_reviews",
        """
        tenant_id              TEXT NOT NULL,
        review_id              TEXT,
        order_id               TEXT,
        review_score           INTEGER,
        review_creation_date   TEXT,
        review_answer_timestamp TEXT
        """,
        """
        SELECT ?, r.review_id, r.order_id, r.review_score,
               r.review_creation_date, r.review_answer_timestamp
        FROM src.order_reviews r
        """,
    ),
)

#: `(索引名, 表, 列列表)` —— 只加会被评测用到的 join / 时间 / 维度列。
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_o_orders_order_id", "v_o_orders", "order_id"),
    ("ix_o_orders_purchase", "v_o_orders", "order_purchase_timestamp"),
    ("ix_o_orders_state", "v_o_orders", "customer_state"),
    ("ix_o_orders_tenant", "v_o_orders", "tenant_id"),
    ("ix_o_items_order", "v_o_order_items", "order_id"),
    ("ix_o_items_product", "v_o_order_items", "product_id"),
    ("ix_o_items_tenant", "v_o_order_items", "tenant_id"),
    ("ix_o_products_product_id", "v_o_products", "product_id"),
    ("ix_o_products_tenant", "v_o_products", "tenant_id"),
    ("ix_o_payments_order", "v_o_payments", "order_id"),
    ("ix_o_payments_tenant", "v_o_payments", "tenant_id"),
    ("ix_o_reviews_order", "v_o_reviews", "order_id"),
    ("ix_o_reviews_tenant", "v_o_reviews", "tenant_id"),
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    """仓库相对路径（POSIX 分隔符）；跨盘时退回绝对路径。"""
    try:
        return Path(os.path.relpath(path.resolve(), REPO_ROOT)).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_sandbox(src: Path, out: Path, tenant: str) -> dict:
    if not src.is_file():
        raise SystemExit(f"源库不存在：{src}\n先确认 --sqlite 指向 Text2SQL/real_data/olist/olist.sqlite")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        print(f"[build] 覆盖既有产物：{_rel(out)} ({out.stat().st_size} bytes)")
        out.unlink()

    con = sqlite3.connect(f"{out.resolve().as_uri()}?mode=rwc", uri=True)
    try:
        con.execute("ATTACH DATABASE ? AS src", (f"{src.resolve().as_uri()}?mode=ro",))
        for name, columns, select_sql in TABLES:
            con.execute(f"CREATE TABLE {name} ({columns})")
            cur = con.execute(f"INSERT INTO {name} {select_sql}", (tenant,))
            print(f"[build] {name:<16} += {cur.rowcount} 行")
        for index, table, columns in INDEXES:
            con.execute(f"CREATE INDEX {index} ON {table}({columns})")
        con.commit()
        con.execute("DETACH DATABASE src")
    finally:
        con.close()

    return {"tables": {name: _count(str(out), name) for name, _, _ in TABLES}}


def _count(db: str, table: str) -> int:
    con = sqlite3.connect(f"{Path(db).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    finally:
        con.close()


def self_check(db: Path, tenant: str, tables: dict[str, int]) -> dict:
    """经 `open_sandbox_connection` 验证租户边界 —— 与评测侧走同一条路径。"""
    from sqlite_exec import open_sandbox_connection

    physicals = {name: "tenant_id" for name, _, _ in TABLES}
    tenant_rows: dict[str, int] = {}
    boundary_rows: dict[str, int] = {}

    con = open_sandbox_connection(str(db), tenant_id=tenant, tenant_scoped_physicals=physicals)
    try:
        for name in physicals:
            tenant_rows[name] = int(con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
    finally:
        con.close()

    con = open_sandbox_connection(
        str(db), tenant_id=BOUNDARY_TENANT, tenant_scoped_physicals=physicals
    )
    try:
        for name in physicals:
            boundary_rows[name] = int(con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
    finally:
        con.close()

    for name, expected in tables.items():
        if tenant_rows[name] != expected:
            raise SystemExit(
                f"[self-check] {tenant} 侧 {name} 行数 {tenant_rows[name]} != 主表 {expected}"
            )

    return {tenant: tenant_rows, BOUNDARY_TENANT: boundary_rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 Olist 评测沙箱（SQLite，只读源库）")
    parser.add_argument(
        "--sqlite",
        default=str(REPO_ROOT.parent / "Text2SQL" / "real_data" / "olist" / "olist.sqlite"),
        help="原始 Olist SQLite（只读 ATTACH）",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "data" / "olist" / "olist_sandbox.db"),
        help="沙箱库输出路径",
    )
    parser.add_argument("--tenant", default=DEFAULT_TENANT, help="写入行的租户码")
    parser.add_argument(
        "--manifest",
        default=str(EVAL_DIR / "olist" / "sandbox_manifest.json"),
        help="行数/哈希清单（必须落在 eval/olist/ 下）",
    )
    args = parser.parse_args(argv)

    src = Path(args.sqlite)
    out = Path(args.out)
    if not out.resolve().is_relative_to((REPO_ROOT / "data").resolve()):
        raise SystemExit(f"--out 必须落在 {REPO_ROOT / 'data'} 之下：{out}")

    result = build_sandbox(src, out, args.tenant)
    checks = self_check(out, args.tenant, result["tables"])

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tenant": args.tenant,
        "boundary_tenant": BOUNDARY_TENANT,
        "source": {"path": _rel(src), "bytes": src.stat().st_size, "sha256": sha256_of(src)},
        "sandbox": {"path": _rel(out), "bytes": out.stat().st_size, "sha256": sha256_of(out)},
        "tables": result["tables"],
        "row_total": sum(result["tables"].values()),
        "indexes": [{"name": n, "table": t, "columns": c} for n, t, c in INDEXES],
        "self_check": {
            "tenant_rows": checks[args.tenant],
            "boundary_rows": checks[BOUNDARY_TENANT],
            "boundary_all_zero": all(v == 0 for v in checks[BOUNDARY_TENANT].values()),
        },
    }
    path = write_json(args.manifest, manifest)

    print("\n[build] 行数")
    for name, rows in result["tables"].items():
        print(f"  {name:<16} {rows:>8}")
    print(f"  {'合计':<15} {manifest['row_total']:>8}")
    print(f"[build] 沙箱 sha256 = {manifest['sandbox']['sha256']}")
    print(f"[build] 沙箱体积   = {manifest['sandbox']['bytes']} bytes")
    print(f"[self-check] {args.tenant} 各表 > 0：" + str(all(v > 0 for v in checks[args.tenant].values())))
    print(
        f"[self-check] {BOUNDARY_TENANT} 各表 = 0："
        + str(manifest["self_check"]["boundary_all_zero"])
    )
    print(f"[manifest] {_rel(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
