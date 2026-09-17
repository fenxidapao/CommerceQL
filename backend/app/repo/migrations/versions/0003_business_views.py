"""0003 —— 业务资产：8 张基表 + 8 个认证视图（07 §13.3 v0.9 / U-56 裁定）

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17

归属窗口：W1B（架构裁决 **U-56**：「`v_*` 视图与基表的 DDL **一律由 W1B 的 alembic
迁移产出**（版本化、可回滚；GRANT/POLICY/一致性检查都依赖对象先存在 → **迁移先于
物化**）；数据装载另行裁定」—— 07 §4.8 / §6.2 v0.9）。

这是 DoD③ 端到端的**唯一硬阻塞**的解除件：收口窗口（w2-int）实测
`materialize(with_policy=True)` 因 `relation "v_order_paid" does not exist` 整体回滚。
本迁移落地后，语义包即可从 candidate 走完整发布（§6.2 步骤②）。

============================================================================
真相来源与类型映射（**谁说了算**）
============================================================================

- **列名 + 列类型 = 语义包**（`semantic/bundle_2026.09.14.1.yaml` 的
  `assets[].columns[].{name,type}`，75 列）。bundle 声明的就是 **PG 类型**
  （text/numeric/int/date/bigint/timestamptz/boolean）—— 本迁移逐列照抄。
- **可空性 + 主键 + 索引 = `data/schema.sql`**（W1A 的数据层契约声明件；
  其文件头明写"生产 PG 侧由 W1B 的 alembic 迁移唯一产出"）。
- 单测 `tests/unit/test_migration_views_contract.py` 把本文件的 `_ASSETS`
  与 bundle（类型）和 schema.sql（列序/可空性）**双向比对** —— 防两份真相。

⚠️ **与 schema.sql 的三处刻意类型分歧**（bundle 赢，schema.sql 是 SQLite 方言）：
| 列 | schema.sql（SQLite） | 本迁移（= bundle） | 为什么 |
|---|---|---|---|
| `pay_time` / `create_time` / `refund_time` | TEXT（ISO8601） | **timestamptz** | bundle 声明；SQLite 用 TEXT 是方言妥协 |
| `is_test_order` / `on_sale` / `is_weekend` | INTEGER 0/1 | **boolean** | 同上 |
| `stat_date` 等日期列 | TEXT | **date** | 同上 |
⚠️ 连带登记（转 W1A/W6，不阻塞本迁移）：评测 gold SQL 若写 `is_test_order = 0`
（SQLite 整数比较），在 PG 上会因 boolean 报错 —— gold SQL 的方言适配属评测侧。

============================================================================
所有权：为什么把对象 OWNER 给 app_rw（U-55(a) 的直接后果）
============================================================================

`materialize(with_policy=True)` 用 **app_rw** 连接执行（见其 docstring）：
`ALTER TABLE ... ENABLE/FORCE ROW LEVEL SECURITY`、`CREATE POLICY`、
`REVOKE/GRANT ... TO app_ro` —— 这三类语句都要求**执行者是对象属主**。
属主若留在迁移角色名下，发布期全部失败（而且失败在"权限"上，最难排查）。

⚠️ 两条诚实的连带后果（登记，转 W7/架构）：
1. **app_rw 因此持有这些对象的 DDL 权**（DROP/ALTER）。这是 U-55(a) 形态的固有代价；
   缓解 = 基表对 app_ro 仍然零 GRANT，且 FORCE RLS 连属主一起管（见下）。
2. **后续迁移**若要改这些表，迁移角色已不是属主 —— 需先 `SET ROLE app_rw`
   （或将属主临时转回）。运行维护方必须知道这一点。

⚠️ **FORCE ROW LEVEL SECURITY**（materialize 落的策略段）会让 RLS 连**属主 app_rw**
一起生效：执行器没 `SET app.tenant_id` → 查询返回 0 行（失败关闭）。
所以"app_rw 是属主"**不会**变成"app_rw 绕过 RLS"——这正是选 FORCE 而非 ENABLE 的价值。

============================================================================
刻意不做（与 0002 同口径）
============================================================================

- **RLS / POLICY / GRANT 一条都不在这里**：ADR-10 要求它们由语义包**派生**
  （`app/semantics/materialize.py::derive_policy_statements`），发布事务内执行。
  本迁移只建**容器**（表 + 视图 + 索引）。在迁移里手写一份策略 = 第二份真相，
  且绕过了"派生即白名单"的双保险。
- **不装载数据**：U-56 裁定"数据装载另行裁定"。表在这里，行从哪来（W7 部署面）不归本迁移。
- **不建 `dim_tenant`**：它不在语义包 assets 里（backend 全仓零引用），沙箱里仅供
  生成器使用；若执行层将来需要，按"清单外对象"另行过裁决。
- **不写 down**（07 §12.6，同 0001/0002）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

#: 列声明的形状：`(列名, PG类型, 可空)`。类型**逐字**来自语义包
#: `assets[].columns[].type`；可空性来自 `data/schema.sql`。
#: 用数据结构而不是内联 SQL 字符串：单测要拿它与 bundle/schema.sql 逐列比对，
#: 字符串里藏 DDL 会让"两份真相"的比对无法进行。
_COLUMN = tuple[str, str, bool]  # (name, pg_type, nullable)

_ASSETS: Final[Mapping[str, tuple[str, tuple[_COLUMN, ...], tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]]] = {
    # ------------------------------------------------------------------
    # 键 = 基表名；每项 = (视图, 列, 主键列, 索引[(索引名, (列...))])
    # 列序 = schema.sql 逐列一致（单测锁定）；类型 = bundle 逐字一致（单测锁定）
    # ------------------------------------------------------------------
    "order_paid": (
        "v_order_paid",
        (
            ("tenant_id", "text", False),
            ("sub_order_id", "text", False),
            ("order_id", "text", False),
            ("shop_id", "text", False),
            ("buyer_id", "text", False),
            ("sku_id", "text", False),
            ("spu_id", "text", False),
            ("category_l1", "text", True),
            ("category_l2", "text", True),
            ("category_l3", "text", True),
            ("pay_amount", "numeric", False),
            ("freight_amount", "numeric", False),
            ("discount_amount", "numeric", False),
            ("quantity", "int", False),
            ("pay_time", "timestamptz", True),  # ★ GMV 基准；未支付订单为 NULL（schema.sql 语义）
            ("create_time", "timestamptz", False),  # ★ 下单时间；非 GMV 基准
            ("pay_status", "text", False),
            ("refund_status", "text", False),
            ("region_code", "text", True),
            ("receiver_city", "text", True),  # ★ U-27：城市维度绑定所需
            ("channel", "text", False),
            ("is_test_order", "boolean", False),
            ("receiver_phone", "text", True),  # 敏感（CLS 拒授，见 materialize 派生）
            ("receiver_address", "text", True),  # 敏感
        ),
        ("tenant_id", "sub_order_id"),
        (
            ("idx_op_tenant_paytime", ("tenant_id", "pay_time")),
            ("idx_op_tenant_shop", ("tenant_id", "shop_id")),
            ("idx_op_tenant_sku", ("tenant_id", "sku_id")),
            ("idx_op_tenant_region", ("tenant_id", "region_code")),
            ("idx_op_tenant_cat", ("tenant_id", "category_l1")),
            ("idx_op_tenant_channel", ("tenant_id", "channel")),
        ),
    ),
    "order_refund": (
        "v_order_refund",
        (
            ("tenant_id", "text", False),
            ("refund_id", "text", False),
            ("sub_order_id", "text", False),
            ("refund_amount", "numeric", False),
            ("refund_type", "text", False),
            ("refund_time", "timestamptz", False),
            ("refund_status", "text", False),
        ),
        ("tenant_id", "refund_id"),
        (
            ("idx_rf_tenant_sub", ("tenant_id", "sub_order_id")),
            ("idx_rf_tenant_time", ("tenant_id", "refund_time")),
        ),
    ),
    "product": (
        "v_product",
        (
            ("tenant_id", "text", False),
            ("sku_id", "text", False),
            ("sku_name", "text", False),
            ("spu_id", "text", False),
            ("shop_id", "text", False),
            ("category_l1", "text", True),
            ("category_l2", "text", True),
            ("category_l3", "text", True),
            ("list_price", "numeric", False),
            ("cost_price", "numeric", False),  # 敏感（deny_columns → CLS 只在 allowlist 有它时授）
            ("on_sale", "boolean", False),
            ("launch_date", "date", False),
        ),
        ("tenant_id", "sku_id"),
        (
            ("idx_pd_tenant_spu", ("tenant_id", "spu_id")),
            ("idx_pd_tenant_shop", ("tenant_id", "shop_id")),
        ),
    ),
    "shop": (
        "v_shop",
        (
            ("tenant_id", "text", False),
            ("shop_id", "text", False),
            ("shop_name", "text", False),
            ("city", "text", False),
            ("category_l1", "text", True),
            ("open_date", "date", False),
        ),
        ("tenant_id", "shop_id"),
        (),
    ),
    # 以下两张 tenant_scoped=false（bundle 声明）→ 无 tenant_id 列，materialize 不落策略。
    # 主键不带 tenant_id（与 schema.sql 一致）。
    "region": (
        "v_region",
        (
            ("code", "text", False),
            ("province_name", "text", False),
            ("region_name", "text", False),
        ),
        ("code",),
        (("idx_rg_region", ("region_name",)),),
    ),
    "campaign": (
        "v_campaign",
        (
            ("tenant_id", "text", False),
            ("campaign_id", "text", False),
            ("campaign_name", "text", False),
            ("campaign_type", "text", False),
            ("start_date", "date", False),
            ("end_date", "date", False),
        ),
        ("tenant_id", "campaign_id"),
        (),
    ),
    "traffic_daily": (
        "v_traffic_daily",
        (
            ("tenant_id", "text", False),
            ("stat_date", "date", False),
            ("sku_id", "text", False),
            ("channel", "text", False),
            ("uv", "bigint", False),
            ("pv", "bigint", False),
            ("cart_add_cnt", "bigint", False),
            ("order_cnt", "bigint", False),
            ("ad_cost", "numeric", False),
        ),
        ("tenant_id", "stat_date", "sku_id", "channel"),
        (
            ("idx_td_tenant_date", ("tenant_id", "stat_date")),
            ("idx_td_tenant_sku", ("tenant_id", "sku_id")),
            ("idx_td_tenant_channel", ("tenant_id", "channel")),
        ),
    ),
    "dim_date": (
        "v_dim_date",
        (
            ("date_key", "date", False),
            ("year", "int", False),
            ("quarter", "int", False),
            ("month", "int", False),
            ("iso_week", "int", False),
            ("day_of_week", "int", False),
            ("is_weekend", "boolean", False),
            ("campaign_id", "text", True),
        ),
        ("date_key",),
        (),
    ),
}

#: ⚠️ 类型**逐字**用 bundle 的写法（含 `int` —— PG 的合法别名），不做"规范名"翻译：
#: 否则"迁移 ↔ bundle 逐字一致"的比对就多出一层翻译，而翻译层自己也会漂移。


def _column_defs(columns: tuple[_COLUMN, ...]) -> str:
    parts = []
    for name, pg_type, nullable in columns:
        null_sql = "" if nullable else " NOT NULL"
        parts.append(f"    {name} {pg_type}{null_sql}")
    return ",\n".join(parts)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. 前置：角色必须已存在（0001 建）。缺了就让它在这里报错，而不是半途失败。
    # ------------------------------------------------------------------
    # 每张表/视图：
    #   ① 建基表（migrator 身份）→ ② 建索引 → ③ 建视图（显式列清单，不用 SELECT *）→
    #   ④ REVOKE PUBLIC（卫生，同 0001）→ ⑤ **OWNER TO app_rw**（materialize 需要属主身份，
    #      见文件头"所有权"节）。
    # ⚠️ 顺序即正确性：索引必须在 OWNER 转移**之前**建（转移后 migrator 不再有权限）。
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

    # ------------------------------------------------------------------
    # 1. 权限边界（显式写清"谁没有"，与 0001 的 REVOKE 卫生同构）
    # ------------------------------------------------------------------
    # ⚠️ **app_ro 对基表零 GRANT**（U-55(a) 前提 2）：视图是 app_ro 的唯一入口。
    # 这里"不给"就够了（表上 PUBLIC 默认无权限，上面又 REVOKE 过一遍）——
    # 刻意**不写** `REVOKE ... FROM app_ro`：app_ro 从未被授过，写它反而暗示"曾经授过"。
    # app_rw 的列级 GRANT（授在**视图**上）由 materialize 派生执行，同样不在这里。
    # ------------------------------------------------------------------
    # 2. 对象元数据注释：把"视图=唯一入口 / 基表对 app_ro 零授权"钉进 COMMENT，
    #    让 psql 的 `\d+` 直接可见，不用翻迁移源码。
    # ------------------------------------------------------------------
    for base, (view, _cols, _pk, _idx) in _ASSETS.items():
        op.execute(
            f"COMMENT ON VIEW app.{view} IS "
            f"'auth view over app.{base} (U-56). app_ro entrypoint; "
            f"CLS grants derived by materialize (ADR-10)'"
        )
        op.execute(
            f"COMMENT ON TABLE app.{base} IS "
            f"'base table of app.{view} (U-56/U-55a). app_rw-owned; "
            f"RLS policy derived by materialize; NO grants to app_ro'"
        )


def downgrade() -> None:
    # 07 §12.6：只写 up，不写 down（同 0001/0002）。
    # 若真要回滚：先切走 active_version 指针 → materialize 的 REVOKE 已随对象消失。
    pass
