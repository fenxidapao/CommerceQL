-- ============================================================================
-- CommerceQL 分析沙箱 DDL —— SQLite 评测版
-- 归属窗口：W1A（data/**）      版本：schema_v1      生成：2026-09-15
--
-- ⚠️ 本文件是「数据层契约声明件」，不是生产 DDL 的真相来源。
--    生产侧（PostgreSQL）的表 / 视图 / **RLS / GRANT / 触发器** 由 **W1B 的 alembic
--    迁移**唯一产出（docs/08 §4.3 四步流程）。本文件只保证：
--      ① 列名与 `semantic/bundle_2026.09.14.1.yaml` 的 `assets[].columns` **逐列一致**
--         （由 `data/generator/selfcheck.py` 断言，防「两份真相」）
--      ② 评测沙箱（SQLite）能跑通附录 C §C.5 的全部用例与 §C.5.3 的 V0–V7 变体
--
-- ⚠️ SQLite 没有 RLS / 列级权限。附录 C §C.13 的 `CREATE POLICY tenant_isolation`、
--    `REVOKE SELECT (cost_price)`、`GRANT ... TO app_ro` **在本文件中一律不出现** ——
--    它们的落地属 W1B。沙箱里的租户隔离由**执行器注入 WHERE tenant_id = ?** 模拟，
--    目的是让「漏注入谓词」这件事在评测里**可以被测出来**（V7 变体），
--    而不是用数据库强制掩盖它。
-- ============================================================================

PRAGMA journal_mode = OFF;      -- 生成期提速；只读评测库无需 WAL
PRAGMA synchronous = OFF;
PRAGMA foreign_keys = OFF;      -- 生成器按依赖序写入，不依赖 FK 强制

-- ----------------------------------------------------------------------------
-- 0. 租户维（附录 C §C.11.1 的 dim_tenant）
--    非认证资产（不在语义包 assets 里）→ 模型不可检索，仅供执行层解析租户
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS dim_tenant;
CREATE TABLE dim_tenant (
    tenant_id    TEXT PRIMARY KEY,
    tenant_name  TEXT NOT NULL,
    plan         TEXT NOT NULL,          -- basic | pro | enterprise
    created_at   TEXT NOT NULL
);

-- ----------------------------------------------------------------------------
-- 1. v_order_paid —— 已支付子订单事实表（主事实表，24 列）
--    对应 YAML assets[order_paid].columns
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_order_paid;
CREATE TABLE v_order_paid (
    tenant_id         TEXT    NOT NULL,   -- RLS 依据；模型不得引用
    sub_order_id      TEXT    NOT NULL,   -- PK 子订单号
    order_id          TEXT    NOT NULL,   -- 父订单号
    shop_id           TEXT    NOT NULL,
    buyer_id          TEXT    NOT NULL,   -- 脱敏哈希
    sku_id            TEXT    NOT NULL,
    spu_id            TEXT    NOT NULL,
    category_l1       TEXT,               -- 可空：场景 13 类目缺失
    category_l2       TEXT,
    category_l3       TEXT,
    pay_amount        NUMERIC NOT NULL,   -- 实付（含运费）
    freight_amount    NUMERIC NOT NULL,
    discount_amount   NUMERIC NOT NULL,
    quantity          INTEGER NOT NULL,
    pay_time          TEXT,               -- ISO8601；**GMV 基准**。⚠️ 可空：未支付订单为 NULL
    create_time       TEXT    NOT NULL,   -- 下单时间；**非 GMV 基准**
    pay_status        TEXT    NOT NULL,   -- paid | unpaid
    refund_status     TEXT    NOT NULL,   -- none | partial | refunded
    region_code       TEXT,               -- 可空：场景 11 NULL
    receiver_city     TEXT,               -- ★ U-27：附录 C §C.11.2 未列，城市维度绑定所需
    channel           TEXT    NOT NULL,
    is_test_order     INTEGER NOT NULL,   -- 0/1
    receiver_phone    TEXT,               -- 敏感
    receiver_address  TEXT,               -- 敏感
    PRIMARY KEY (tenant_id, sub_order_id)
);
-- 评测常用访问路径（L2/L3 的时间过滤 + 租户隔离）
CREATE INDEX idx_op_tenant_paytime ON v_order_paid (tenant_id, pay_time);
CREATE INDEX idx_op_tenant_shop    ON v_order_paid (tenant_id, shop_id);
CREATE INDEX idx_op_tenant_sku     ON v_order_paid (tenant_id, sku_id);
CREATE INDEX idx_op_tenant_region  ON v_order_paid (tenant_id, region_code);
CREATE INDEX idx_op_tenant_cat     ON v_order_paid (tenant_id, category_l1);
CREATE INDEX idx_op_tenant_channel ON v_order_paid (tenant_id, channel);

-- ----------------------------------------------------------------------------
-- 2. v_order_refund —— 退款事实表（7 列）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_order_refund;
CREATE TABLE v_order_refund (
    tenant_id      TEXT NOT NULL,
    refund_id      TEXT NOT NULL,
    sub_order_id   TEXT NOT NULL,
    refund_amount  NUMERIC NOT NULL,
    refund_type    TEXT NOT NULL,        -- partial | full
    refund_time    TEXT NOT NULL,
    refund_status  TEXT NOT NULL,        -- applied | approved | refunded | rejected
    PRIMARY KEY (tenant_id, refund_id)
);
CREATE INDEX idx_rf_tenant_sub ON v_order_refund (tenant_id, sub_order_id);
CREATE INDEX idx_rf_tenant_time ON v_order_refund (tenant_id, refund_time);

-- ----------------------------------------------------------------------------
-- 3. v_product —— 商品维表（12 列）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_product;
CREATE TABLE v_product (
    tenant_id    TEXT NOT NULL,
    sku_id       TEXT NOT NULL,
    sku_name     TEXT NOT NULL,
    spu_id       TEXT NOT NULL,
    shop_id      TEXT NOT NULL,
    category_l1  TEXT,                   -- 可空：场景 13
    category_l2  TEXT,
    category_l3  TEXT,
    list_price   NUMERIC NOT NULL,       -- 标价
    cost_price   NUMERIC NOT NULL,       -- 敏感（deny_columns）
    on_sale      INTEGER NOT NULL,       -- 0/1
    launch_date  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, sku_id)
);
CREATE INDEX idx_pd_tenant_spu ON v_product (tenant_id, spu_id);
CREATE INDEX idx_pd_tenant_shop ON v_product (tenant_id, shop_id);

-- ----------------------------------------------------------------------------
-- 4. v_shop —— 店铺维表（6 列）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_shop;
CREATE TABLE v_shop (
    tenant_id   TEXT NOT NULL,
    shop_id     TEXT NOT NULL,
    shop_name   TEXT NOT NULL,
    city        TEXT NOT NULL,           -- 店铺侧「城市」→ 与收货城市同粒度竞争
    category_l1 TEXT,                    -- 店铺主营一级类目
    open_date   TEXT NOT NULL,
    PRIMARY KEY (tenant_id, shop_id)
);

-- ----------------------------------------------------------------------------
-- 5. v_region —— 地区维表（3 列，**无 tenant_id** → tenant_scoped: false）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_region;
CREATE TABLE v_region (
    code          TEXT PRIMARY KEY,      -- 省编码（6 位）
    province_name TEXT NOT NULL,
    region_name   TEXT NOT NULL          -- 大区名，**由语义包 value_map 派生**
);
CREATE INDEX idx_rg_region ON v_region (region_name);

-- ----------------------------------------------------------------------------
-- 6. v_campaign —— 活动/大促维表（6 列）
--    618 / 双11 区间以语义包 time_semantics.notes 为准（D-2）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_campaign;
CREATE TABLE v_campaign (
    tenant_id     TEXT NOT NULL,
    campaign_id   TEXT NOT NULL,
    campaign_name TEXT NOT NULL,
    campaign_type TEXT NOT NULL,         -- promo | daily | newuser
    start_date    TEXT NOT NULL,         -- 含
    end_date      TEXT NOT NULL,         -- 含
    PRIMARY KEY (tenant_id, campaign_id)
);

-- ----------------------------------------------------------------------------
-- 7. v_traffic_daily —— 流量日粒度事实表（9 列）
--    主键 = tenant_id × stat_date × sku_id × channel
--    ⚠️ 转化率不存成列（附录 C §C.11.2）：必须由 metric_def 定义
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_traffic_daily;
CREATE TABLE v_traffic_daily (
    tenant_id     TEXT    NOT NULL,
    stat_date     TEXT    NOT NULL,      -- YYYY-MM-DD
    sku_id        TEXT    NOT NULL,
    channel       TEXT    NOT NULL,
    uv            INTEGER NOT NULL,
    pv            INTEGER NOT NULL,
    cart_add_cnt  INTEGER NOT NULL,
    order_cnt     INTEGER NOT NULL,
    ad_cost       NUMERIC NOT NULL,
    PRIMARY KEY (tenant_id, stat_date, sku_id, channel)
);
CREATE INDEX idx_td_tenant_date    ON v_traffic_daily (tenant_id, stat_date);
CREATE INDEX idx_td_tenant_sku     ON v_traffic_daily (tenant_id, sku_id);
CREATE INDEX idx_td_tenant_channel ON v_traffic_daily (tenant_id, channel);

-- ----------------------------------------------------------------------------
-- 8. v_dim_date —— 日期维表（8 列，**无 tenant_id** → tenant_scoped: false）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v_dim_date;
CREATE TABLE v_dim_date (
    date_key     TEXT PRIMARY KEY,       -- YYYY-MM-DD
    year         INTEGER NOT NULL,
    quarter      INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    iso_week     INTEGER NOT NULL,
    day_of_week  INTEGER NOT NULL,       -- 1=周一
    is_weekend   INTEGER NOT NULL,       -- 0/1
    campaign_id  TEXT                    -- 可空：非活动日
);

-- ============================================================================
-- 附：数据变体 V0–V7 的落地方式（附录 C §C.5.3）
--   **不是一个变体一份库**。V0 是全量基线库；V1–V7 由
--   `data/generator/variants.py` 以**确定性 patch** 作用在评测所需的时间窗 /
--   租户子集上（已裁定：V0 全量 + 变体打 patch）。理由：8 份快照会使仓库体积
--   翻 8 倍，且每次改集都要全量重生成；patch 方式可复现、可审计、可单测。
-- ============================================================================
