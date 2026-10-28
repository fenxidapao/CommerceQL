"""0007 —— Olist 演示资产：5 张基表 + 5 个认证视图（U-147 / W3）

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28

归属窗口：W3（`docs/07 v1.7.38` U-147；`docs/08 §4.1` 2026-10-28 补登记）。
**0007 由本计划占用**；B 的 `workflow_and_runs` 顺延 `0010`。

============================================================================
真相来源（**谁说了算**）
============================================================================

- **列名 + 列类型 = 语义包** `semantic/bundle_olist_2018.yaml` 的
  `assets[].columns[].{name,type}` —— 与 0003 同口径，逐字照抄（text/integer/numeric），
  不做"规范名"翻译。单测 `tests/unit/test_migration_0007_olist_assets.py` 双向比对。
- **可空性 = 数据实测 + SQLite 沙箱 DDL**：`tenant_id` 与主键列 NOT NULL，
  其余列可空（Olist 原始数据里存在空品类/空时间列）。
- **主键 = 实测唯一键**：`order_id` / `(order_id, order_item_id)` /
  `product_id` / `(order_id, payment_sequential)` / `(review_id, order_id)`。
  ⚠️ `review_id` 单独**不唯一**（99,224 行里有 789 组重复），所以 reviews 用复合主键
  —— 不能拿 `review_id` 当单列主键（会在迁移期直接失败，或诱导去重改变 gold 读数）。
- **索引名/列 = SQLite 沙箱** `deploy/demo/build_olist_sandbox.py::INDEXES` 的 13 条，
  保留 `ix_o_*` 原名，便于两侧对账。

============================================================================
所有权：为什么 OWNER 给 app_rw
============================================================================

`materialize(with_policy=True)` 用 **app_rw** 连接执行 `GRANT/ALTER/CREATE POLICY`，
这些都要求执行者是对象属主（同 0003 的 U-55(a) 结论）。属主留给迁移角色会让发布期
全部失败，且失败在权限上、最难排查。

⚠️ FORCE RLS（由 materialize 派生）会让属主 app_rw 也受策略约束：不设
`app.tenant_id` / `app.shop_ids` 时查询返回 0 行（失败关闭），"属主"不等于"绕过"。

============================================================================
刻意不做（与 0002/0003 同口径）
============================================================================

- **RLS / POLICY / GRANT 一条都不在这里**：由语义包派生
  （`app/semantics/materialize.py::derive_policy_statements`），发布事务内执行。
  在迁移里手写一份 = 第二份真相；`tests/unit/test_rls_policy_provenance.py`
  会扫描全部四位数字迁移并拒绝 `CREATE POLICY` / ENABLE|FORCE RLS。
- **不装载数据**：表在这里，行由 `deploy/demo/load_olist_to_pg.py` 用 app_rw 写入。
- **不写 down**（07 §12.6，同 0001–0006）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

#: `(列名, PG类型, 可空)`；类型逐字来自语义包。
_COLUMN = tuple[str, str, bool]

#: `(视图, 列, 主键, 索引[(索引名, (列...))])`
_ASSET = tuple[str, tuple[_COLUMN, ...], tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]

_ASSETS: Final[Mapping[str, _ASSET]] = {
    "o_orders": (
        "v_o_orders",
        (
            ("tenant_id", "text", False),
            ("order_id", "text", False),
            ("customer_id", "text", True),
            ("customer_unique_id", "text", True),
            ("customer_state", "text", True),
            ("customer_city", "text", True),
            ("order_status", "text", True),
            ("order_purchase_timestamp", "text", True),
            ("order_approved_at", "text", True),
            ("order_delivered_customer_date", "text", True),
            ("order_estimated_delivery_date", "text", True),
        ),
        ("order_id",),
        (
            ("ix_o_orders_order_id", ("order_id",)),
            ("ix_o_orders_purchase", ("order_purchase_timestamp",)),
            ("ix_o_orders_state", ("customer_state",)),
            ("ix_o_orders_tenant", ("tenant_id",)),
        ),
    ),
    "o_order_items": (
        "v_o_order_items",
        (
            ("tenant_id", "text", False),
            ("order_id", "text", False),
            ("order_item_id", "integer", False),
            ("product_id", "text", True),
            ("seller_id", "text", True),
            ("shipping_limit_date", "text", True),
            ("price", "numeric", True),
            ("freight_value", "numeric", True),
        ),
        ("order_id", "order_item_id"),
        (
            ("ix_o_items_order", ("order_id",)),
            ("ix_o_items_product", ("product_id",)),
            ("ix_o_items_tenant", ("tenant_id",)),
        ),
    ),
    "o_products": (
        "v_o_products",
        (
            ("tenant_id", "text", False),
            ("product_id", "text", False),
            ("product_category_name", "text", True),
            ("product_category", "text", True),
            ("product_weight_g", "numeric", True),
            ("product_photos_qty", "numeric", True),
        ),
        ("product_id",),
        (
            ("ix_o_products_product_id", ("product_id",)),
            ("ix_o_products_tenant", ("tenant_id",)),
        ),
    ),
    "o_payments": (
        "v_o_payments",
        (
            ("tenant_id", "text", False),
            ("order_id", "text", False),
            ("payment_sequential", "integer", False),
            ("payment_type", "text", True),
            ("payment_installments", "integer", True),
            ("payment_value", "numeric", True),
        ),
        ("order_id", "payment_sequential"),
        (
            ("ix_o_payments_order", ("order_id",)),
            ("ix_o_payments_tenant", ("tenant_id",)),
        ),
    ),
    "o_reviews": (
        "v_o_reviews",
        (
            ("tenant_id", "text", False),
            ("review_id", "text", False),
            ("order_id", "text", False),
            ("review_score", "integer", True),
            ("review_creation_date", "text", True),
            ("review_answer_timestamp", "text", True),
        ),
        ("review_id", "order_id"),
        (
            ("ix_o_reviews_order", ("order_id",)),
            ("ix_o_reviews_tenant", ("tenant_id",)),
        ),
    ),
}


def _column_defs(columns: tuple[_COLUMN, ...]) -> str:
    parts = []
    for name, pg_type, nullable in columns:
        null_sql = "" if nullable else " NOT NULL"
        parts.append(f"    {name} {pg_type}{null_sql}")
    return ",\n".join(parts)


def upgrade() -> None:
    # 顺序即正确性：索引必须在 OWNER 转移之前建（转移后迁移角色不再有建索引权）。
    for base, (view, columns, pk, indexes) in _ASSETS.items():
        pk_sql = ", ".join(pk)
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS app.{base} (
{_column_defs(columns)},
                PRIMARY KEY ({pk_sql})
            )
            """
        )
        for idx_name, idx_cols in indexes:
            cols_sql = ", ".join(idx_cols)
            op.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON app.{base} ({cols_sql})"
            )
        col_list = ", ".join(name for name, _, _ in columns)
        op.execute(
            f"CREATE OR REPLACE VIEW app.{view} AS "
            f"SELECT {col_list} FROM app.{base}"
        )
        op.execute(f"REVOKE ALL ON app.{base}, app.{view} FROM PUBLIC")
        op.execute(f"ALTER TABLE app.{base} OWNER TO app_rw")
        op.execute(f"ALTER VIEW app.{view} OWNER TO app_rw")

    for base, (view, _cols, _pk, _idx) in _ASSETS.items():
        op.execute(
            f"COMMENT ON VIEW app.{view} IS "
            f"'Olist demo auth view over app.{base} (U-147). app_ro entrypoint; "
            f"CLS grants derived by materialize (ADR-10)'"
        )
        op.execute(
            f"COMMENT ON TABLE app.{base} IS "
            f"'Olist demo base table of app.{view} (U-147). app_rw-owned; "
            f"RLS policy derived by materialize; NO grants to app_ro'"
        )


def downgrade() -> None:
    # 07 §12.6：只写 up，不写 down（同 0001–0006）。
    pass
