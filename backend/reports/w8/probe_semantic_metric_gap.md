# 语义层 `metrics` 缺口清单（W8 第 40 轮）

> **性质**：**只读清单件** —— 🔴 **本轮不动 `semantic/**` YAML**（派单 §58.1 三、）。
> **来源**：`eval/dataset_v1_frozen.json` 的 `gold_sql` ＋ `eval/results_v1.json` 的 outcome。
> **时点**：`2026-10-15T02:36:00+00:00`（UTC）

## 0. 漏斗（现读）

| 步 | 数 |
|---|---|
| `expected_behavior = execute` | 124 |
| 其中 **误拒**（`outcome = refuse`） | **63** |
| ↳ `refusal_reason` | {'no_data_asset': 63} |
| ↳ 停止节点 | {'refuse_out': 63} |
| 既有 `metrics`（只读，未改） | 9 |
| 本件建议**新增** `metrics` | **13** |

独立复核 QA `evidence_main_r31ad` 的五条断言（本窗**自算**，未抄其输出）：

| # | QA 断言 | 本窗自算（第 40 轮） | 判 |
|---|---|---|---|
| ① | G-2 面 10 条全 `refuse`／`no_data_asset`，`expected=execute` | n=10｜outcome={'refuse': 10}｜reason={'no_data_asset': 10}｜expected={'execute': 10} | ✅ |
| ② | `set(G-2) ⊆ set(误拒)` | True | ✅ |
| ③ | 误拒 63 条 100% `no_data_asset` | True（`reason` 只有一种） | ✅ |
| ④ | `embedding_unavailable` **零区分力**（非根因） | success **45/45** ⟷ 误拒 **63/63** | ✅ |
| ⑤ | 停止点全在 `plan → refuse_out`（非 link 空召回） | nodes 末位={'refuse_out': 63}｜`retrieval_counts.assets`={8: 63}｜`gate_decisions` 非空=0 | ✅ |

⇒ **五条全部复现**；本轮的**值增量**在于「缺口怎么补」不再靠题面关键词人工比对（见 §40.1 方法与 §1.1 逐条）。

## 1. 缺口 metric 清单

| # | metric | 显示名 | 目标 asset（grain） | expression | 默认谓词 | 覆盖 |
|---|---|---|---|---|---|---|
| 1 | `pv` | 浏览量 | `traffic_daily`（`sku_day_channel`） | `SUM(traffic_daily.pv)` | `pv >= 0` | **26** |
| 2 | `cart_add_cnt` | 加购次数 | `traffic_daily`（`sku_day_channel`） | `SUM(traffic_daily.cart_add_cnt)` | `cart_add_cnt >= 0` | **1** |
| 3 | `on_sale_product_cnt` | 在架商品数 | `product`（`sku`） | `COUNT(*)` | `on_sale = true` | **13** |
| 4 | `off_sale_product_cnt` | 下架商品数 | `product`（`sku`） | `COUNT(*)` | `on_sale = false` | **1** |
| 5 | `product_cnt` | 商品数 | `product`（`sku`） | `COUNT(*)` | **无** | **11** |
| 6 | `spu_cnt` | SPU 数 | `product`（`sku`） | `COUNT(DISTINCT product.spu_id)` | `on_sale = true` | **1** |
| 7 | `avg_list_price` | 商品平均标价 | `product`（`sku`） | `AVG(product.list_price)` | `on_sale = true` | **1** |
| 8 | `shop_cnt` | 店铺数 | `shop`（`shop`） | `COUNT(*)` | **无** | **1** |
| 9 | `campaign_cnt` | 活动数 | `campaign`（`campaign`） | `COUNT(*)` | **无** | **2** |
| 10 | `province_cnt` | 覆盖省份数 | `region`（`province`） | `COUNT(*)` | **无** | **2** |
| 11 | `province_covered_cnt` | 收货省份覆盖数 | `order_paid`（`sub_order`） | `COUNT(DISTINCT order_paid.region_code)` | `region_code IS NOT NULL` | **1** |
| 12 | `day_cnt` | 天数 | `dim_date`（`day`） | `COUNT(*)` | **无** | **1** |
| 13 | `refunded_order_cnt` | 全额退款订单数 | `order_paid`（`sub_order`） | `COUNT(DISTINCT order_paid.sub_order_id)` | `refund_status = 'refunded'`, `pay_status = 'paid'` | **1** |

### 1.1 逐条详表（`default_aggregation` / `unit` / `time_basis` / `synonyms` / 覆盖 case_id）

**1. `pv` — 浏览量**

- `asset`：`traffic_daily`（`grain = sku_day_channel`）｜`expression`：`SUM(traffic_daily.pv)`
- `default_aggregation`：`sum`｜`unit`：`次`｜`time_basis`：`stat_date`
- `synonyms`：浏览量、PV、pv、页面浏览量、浏览次数、访问量、流量、曝光量
- `default_predicates`：`pv >= 0`｜理由：防御性谓词：与 uv 同族，排除脏数据负数
- `definition_note`：不去重；跨日区间可安全累加（与 uv 不同，uv 跨日累加会重复计数）。
- **覆盖 26 条**：E-ENUM-01, E-ENUM-02, E-ENUM-03, E-ENUM-04, E-ENUM-05, M-DIM-01, M-DIM-02, M-ENUM-01, M-ENUM-02, M-ENUM-03, M-ENUM-04, X-ENUM-01, X-ENUM-02, X-ENUM-03, X-ENUM-04, X-ENUM-05, X-ENUM-06, X-ENUM-07, X-ENUM-08, X-MET-01, X-MET-02, X-MET-03, X-MET-04, X-MET-05, X-STR-02, X-STR-04

**2. `cart_add_cnt` — 加购次数**

- `asset`：`traffic_daily`（`grain = sku_day_channel`）｜`expression`：`SUM(traffic_daily.cart_add_cnt)`
- `default_aggregation`：`sum`｜`unit`：`次`｜`time_basis`：`stat_date`
- `synonyms`：加购次数、加购数、加购量、加购、加购人次
- `default_predicates`：`cart_add_cnt >= 0`｜理由：防御性谓词：同 pv/uv 族
- `definition_note`：不去重、按次计数。
- **覆盖 1 条**：M-DIM-10

**3. `on_sale_product_cnt` — 在架商品数**

- `asset`：`product`（`grain = sku`）｜`expression`：`COUNT(*)`
- `default_aggregation`：`count`｜`unit`：`个`｜`time_basis`：`current`
- `synonyms`：在架商品数、在架商品、在售商品数、在售商品、上架商品数、在架SKU数、在售SKU数、在架商品个数
- `default_predicates`：`on_sale = true`｜理由：「在架/在售/上架」的商品 = on_sale 为真
- `definition_note`：维表快照口径（time_semantics=current），非交易口径。
- **覆盖 13 条**：E-VER-02, E-VER-10, E-VER-11, H-CAT-01, H-CAT-02, H-CAT-03, H-CAT-04, H-CAT-05, H-STR-05, H-STR-06, H-STR-08, M-HIER-01, M-HIER-02
- ⚠️ **不确定项**：🔴 `E-ENUM-06…10` 的 gold_sql **不带** `on_sale = 1`，而这 5 条的题面**写着**「在架」→ 本指标一旦挂 `on_sale = true` 默认谓词，这 5 条**会作答但计数与 gold 不等**（`v_product` 现读 on_sale=1 为 5631 / 全表 6000）。**属冻结集内部口径冲突：只登记，不得为迎合它改判据。**
- ⚠️ **不确定项**：`on_sale` 为 NULL 的行不存在（现读仅 0/1 两值）⇒ `on_sale = true` 与 `on_sale <> false` 等价的说法**不成立**（NULL 会被 `<> false` 漏掉），谓词一律写 `on_sale = true`。

**4. `off_sale_product_cnt` — 下架商品数**

- `asset`：`product`（`grain = sku`）｜`expression`：`COUNT(*)`
- `default_aggregation`：`count`｜`unit`：`个`｜`time_basis`：`current`
- `synonyms`：下架商品数、下架商品、停售商品数、已下架商品数
- `default_predicates`：`on_sale = false`｜理由：「下架/停售」的商品 = on_sale 为假
- `definition_note`：与 on_sale_product_cnt 互补，**不可相加代替 product_cnt**（category_l1 为 NULL 的 60 行两指标都不计）。
- **覆盖 1 条**：E-VER-03

**5. `product_cnt` — 商品数**

- `asset`：`product`（`grain = sku`）｜`expression`：`COUNT(*)`
- `default_aggregation`：`count`｜`unit`：`个`｜`time_basis`：`current`
- `synonyms`：商品数、商品数量、商品个数、SKU数、SKU数量、sku数、款式数、货品数
- `default_predicates`：**无**
- `definition_note`：不区分上下架的存量计数（含 category_l1 为 NULL 的 60 行）。
- **覆盖 11 条**：E-ENUM-06, E-ENUM-07, E-ENUM-08, E-ENUM-09, E-ENUM-10, M-DIM-06, M-DIM-07, M-DIM-09, M-HIER-04, M-HIER-05, M-HIER-06
- ⚠️ **不确定项**：与 on_sale_product_cnt **同词根**（「商品数」「SKU数」）→ L1 别名表必须做**互斥切分**（「在架/在售/上架」修饰词归 on_sale 那条），否则 L1 会把带修饰词的问题也命中本指标。

**6. `spu_cnt` — SPU 数**

- `asset`：`product`（`grain = sku`）｜`expression`：`COUNT(DISTINCT product.spu_id)`
- `default_aggregation`：`count_distinct`｜`unit`：`个`｜`time_basis`：`current`
- `synonyms`：SPU 数、SPU数、SPU数量、SPU个数、款数、款式数量
- `default_predicates`：`on_sale = true`｜理由：对齐 gold_sql（`E-VER-04` 的 gold 带 `on_sale = 1`）—— ⚠️ 题面并无此限定
- `definition_note`：按 spu_id 去重。
- **覆盖 1 条**：E-VER-04
- ⚠️ **不确定项**：题面「T_A 的 SPU 数是多少」**无在架限定**，而 gold_sql 带 `on_sale = 1`（`v_product` 全表 6000 行 / on_sale=1 为 5631 行）→ 默认谓词的取舍直接决定能否与 gold 对齐，**须业务确认**。

**7. `avg_list_price` — 商品平均标价**

- `asset`：`product`（`grain = sku`）｜`expression`：`AVG(product.list_price)`
- `default_aggregation`：`avg`｜`unit`：`CNY`｜`time_basis`：`current`
- `synonyms`：商品平均标价、平均标价、平均吊牌价、标价均值、商品平均吊牌价
- `default_predicates`：`on_sale = true`｜理由：对齐 gold_sql（`H-STR-09` 的 gold 带 `on_sale = 1`）—— ⚠️ 题面并无此限定
- `definition_note`：标价 = 吊牌价，**非成交价**（成交侧用 aov / 件单价）。
- **覆盖 1 条**：H-STR-09
- ⚠️ **不确定项**：同 `spu_cnt`：gold 带未在题面出现的 `on_sale = 1`。

**8. `shop_cnt` — 店铺数**

- `asset`：`shop`（`grain = shop`）｜`expression`：`COUNT(*)`
- `default_aggregation`：`count`｜`unit`：`个`｜`time_basis`：`current`
- `synonyms`：店铺数、店铺数量、店铺个数、门店数、店铺家数
- `default_predicates`：**无**
- `definition_note`：`v_shop` 现读 12 行。
- **覆盖 1 条**：E-VER-05
- ⚠️ **不确定项**：gold_sql 为 `COUNT(*) … WHERE city IS NOT NULL`（现读仍为 12，因 city 无 NULL）；题面无该限定 → 默认谓词**建议不挂**，但须登记与 gold 的这点差异。

**9. `campaign_cnt` — 活动数**

- `asset`：`campaign`（`grain = campaign`）｜`expression`：`COUNT(*)`
- `default_aggregation`：`count`｜`unit`：`个`｜`time_basis`：`current`
- `synonyms`：活动数、活动数量、活动个数、活动场次、促销活动数
- `default_predicates`：**无**
- `definition_note`：`v_campaign` 现读 84 行（normal_sale 72 / prom_618 6 / prom_double11 6）。
- **覆盖 2 条**：E-VER-06, M-DIM-04
- ⚠️ **不确定项**：🔴 **同一指标两条 gold 口径互斥**：`E-VER-06`（T_A 的活动数）gold 带 `campaign_type = 'normal_sale'`（=72），而 `M-DIM-04`（各活动类型的活动数）gold **无谓词**（=84）。⇒ 挂默认谓词必错其一。**建议不挂**，并把它作为「口径待业务确认」登记。

**10. `province_cnt` — 覆盖省份数**

- `asset`：`region`（`grain = province`）｜`expression`：`COUNT(*)`
- `default_aggregation`：`count`｜`unit`：`个`｜`time_basis`：`current`
- `synonyms`：覆盖省份数、省份数、省份数量、省份个数、省份覆盖数、覆盖省份
- `default_predicates`：**无**
- `definition_note`：`v_region` 现读 31 行；大区（华东 7 / 华北 5 / 西南 5 / 西北 5 / 华南 3 / 华中 3 / 东北 3）由 `region_name` 承载。
- **覆盖 2 条**：E-VER-07, M-DIM-08
- ⚠️ **不确定项**：`E-VER-07` 的「华东」是**大区层级**筛选，`M-DIM-08` 的「7 个大区各覆盖」是**按大区分组** → 二者都还要 `region` 侧的**大区绑定面**（见 non_metric_faces F-4）。

**11. `province_covered_cnt` — 收货省份覆盖数**

- `asset`：`order_paid`（`grain = sub_order`）｜`expression`：`COUNT(DISTINCT order_paid.region_code)`
- `default_aggregation`：`count_distinct`｜`unit`：`个`｜`time_basis`：`pay_time`
- `synonyms`：收货省份覆盖数、收货省份数、覆盖省份数(收货)、省份覆盖、收货覆盖省份数
- `default_predicates`：`region_code IS NOT NULL`｜理由：对齐 gold_sql（`E-VER-08`）
- `definition_note`：跨列去重计数，落在事实表 order_paid 上；与 `region` 资产上的 `province_cnt` **不是同一件事**（一个是维表存量、一个是订单实覆盖）。
- **覆盖 1 条**：E-VER-08
- ⚠️ **不确定项**：与 `province_cnt` 中文名高度重叠（都可叫「覆盖省份数」）→ 别名表须做互斥切分，否则 L1 歧义。

**12. `day_cnt` — 天数**

- `asset`：`dim_date`（`grain = day`）｜`expression`：`COUNT(*)`
- `default_aggregation`：`count`｜`unit`：`天`｜`time_basis`：`current`
- `synonyms`：天数、日期数、日历天数、日期维表天数、统计天数、日期个数
- `default_predicates`：**无**
- `definition_note`：`v_dim_date` 现读 730 行（2024-10-01 … 2026-09-30）。
- **覆盖 1 条**：E-VER-01
- ⚠️ **不确定项**：gold_sql 为**全表** `COUNT(*)`（=730），而题面写「**2026-08** 的日期维表有多少天」（应含月份筛选 = 31）→ 作答后**计数必与 gold 不等**。属冻结集内部口径冲突，**只登记、不改判据**。

**13. `refunded_order_cnt` — 全额退款订单数**

- `asset`：`order_paid`（`grain = sub_order`）｜`expression`：`COUNT(DISTINCT order_paid.sub_order_id)`
- `default_aggregation`：`count_distinct`｜`unit`：`笔`｜`time_basis`：`pay_time`
- `synonyms`：全额退款订单数、退款订单数、全额退款笔数、退款笔数、退款单量
- `default_predicates`：`refund_status = 'refunded'`, `pay_status = 'paid'`｜理由：对齐 gold_sql（`H-ENUM-02`）；分子正是退款行为本身，故**不套** `refund_status <> 'refunded'`
- `definition_note`：口径参照 `refund_rate` 的例外模式：谓词**不含** `refund_status <> 'refunded'`。
- **覆盖 1 条**：H-ENUM-02
- ⚠️ **不确定项**：`H-ENUM-03`（「无退款」状态的订单数）**已 success** —— 说明该族目前靠模型即兴表达 `refund_status` 谓词；补本指标后需确认是否**只**覆盖 `全额退款` 而把「无退款/部分退款」留给通用 `order_cnt` ＋显式谓词。

## 2. **不补** 的 case（并附理由）

- `E-MET-08` —— 冻结集 `notes` 原文明写：**反面口径**（「故意不套默认谓词，用来测 W6 的『口径一致性』能否识别默认谓词缺失」）⇒ 它要的**不是**新 metric（恰恰相反，要的是「同一个 pay_amount 表达式**不许**自动带上 gmv 的默认谓词」）。补 metric 会**破坏**该用例的设计意图。

## 3. 非 metric 面（**本轮不授权改**，只登记；下一轮须单独点句）

| # | 面 | 覆盖条数 | case_id |
|---|---|---|---|
| F-1 | SKU 维度（`sku_id`）**未定义** | 7 | M-DIM-01, M-ENUM-01, M-ENUM-02, M-ENUM-03, M-ENUM-04, X-STR-02, X-STR-04 |
| F-2 | SPU 维度（`spu_id`）**未定义** | 1 | M-DIM-06 |
| F-3 | 类目维度在 **`product` 侧**无绑定 | 30 | E-ENUM-06, E-ENUM-07, E-ENUM-08, E-ENUM-09, E-ENUM-10, H-CAT-01, H-CAT-02, H-CAT-03, H-CAT-04, H-CAT-05, M-DIM-07, M-DIM-09, M-HIER-01, M-HIER-02, M-HIER-04, M-HIER-05, M-HIER-06, X-ENUM-01, X-ENUM-02, X-ENUM-03, X-ENUM-04, X-ENUM-05, X-ENUM-06, X-ENUM-07, X-ENUM-08, X-MET-01, X-MET-02, X-MET-03, X-MET-04, X-MET-05 |
| F-4 | 大区（`region_name`）在 **`region` 资产侧**无绑定 | 2 | E-VER-07, M-DIM-08 |
| F-5 | 活动类型维度（`campaign.campaign_type`）**未定义** | 1 | M-DIM-04 |
| F-6 | 店铺维度（`shop.shop_id`）**已有** ＋ `product→shop` join **已有** ⇒ **不是缺口** | 25 | H-CAT-01, H-CAT-02, H-CAT-03, H-CAT-04, H-CAT-05, H-ENUM-02, H-STR-05, H-STR-06, H-STR-08, H-STR-09, X-ENUM-01, X-ENUM-02, X-ENUM-03, X-ENUM-04, X-ENUM-05, X-ENUM-06, X-ENUM-07, X-ENUM-08, X-MET-01, X-MET-02, X-MET-03, X-MET-04, X-MET-05, X-STR-02, X-STR-04 |

- **F-1**：`dimensions` 现有 6 个（`region`/`category`/`channel`/`time`/`shop`/`city`），**没有** SKU 维度。`M-MET-05`（各 `sku_id` 的 UV）能 success ⇒ 该面可能只差 metric、不差维度，**故列为不确定项**。
- **F-2**：`M-DIM-06`（各 SPU 的 SKU 数）需按 `spu_id` 分组，`dimensions` 无此维度。
- **F-3**：`dimensions.category.binding` = `order_paid.category_l1`；而 30 条的 gold 都在 **`v_product`** 上按 `category_l1`/`category_l2` 筛选或分组（其中 13 条是 3 表 JOIN：`X-ENUM-*` / `X-MET-*`）。**不是** metric 面。
- **F-4**：`dimensions.region` 的 `binding` = `order_paid.region_code`（收货省），`region_name` 只出现在 `value_map`（业务约定）。`E-VER-07`/`M-DIM-08` 的 gold 直接读 `v_region.region_name`。
- **F-5**：`M-DIM-04` 需按 `campaign_type` 分组。
- **F-6**：25 条都走这两条既有路径；`F-6` 登记在案只为**排除**它（避免下一轮把它当缺口再补一遍）。

## 4. 覆盖预估（④ 合计）

- 误拒总数 **63**
- ↳ **只补 metric 即可**（无 F-1…F-5 附面）：**16** 条 —— E-ENUM-01, E-ENUM-02, E-ENUM-03, E-ENUM-04, E-ENUM-05, E-VER-01, E-VER-02, E-VER-03, E-VER-04, E-VER-05, E-VER-06, E-VER-08, E-VER-10, E-VER-11, M-DIM-02, M-DIM-10
- ↳ **还须附面**（F-1…F-5 任一，本轮**未授权**）：**46** 条 —— E-ENUM-06, E-ENUM-07, E-ENUM-08, E-ENUM-09, E-ENUM-10, E-VER-07, H-CAT-01, H-CAT-02, H-CAT-03, H-CAT-04, H-CAT-05, H-ENUM-02, H-STR-05, H-STR-06, H-STR-08, H-STR-09, M-DIM-01, M-DIM-04, M-DIM-06, M-DIM-07, M-DIM-08, M-DIM-09, M-ENUM-01, M-ENUM-02, M-ENUM-03, M-ENUM-04, M-HIER-01, M-HIER-02, M-HIER-04, M-HIER-05, M-HIER-06, X-ENUM-01, X-ENUM-02, X-ENUM-03, X-ENUM-04, X-ENUM-05, X-ENUM-06, X-ENUM-07, X-ENUM-08, X-MET-01, X-MET-02, X-MET-03, X-MET-04, X-MET-05, X-STR-02, X-STR-04
- ↳ **不建议补**：E-MET-08
- 校验：16 ＋ 46 ＋ 1 = 63 ✅

## 5. 落地前置（**下一轮**改 YAML 时必须一并处理，非本轮动作）

- **`aliases`**：`synonyms` ⊆ `aliases` 的 term 集是**校验器断言**（`validate_bundle.py` 步骤③）⇒ 落 YAML 时**必须同步补 `aliases`** 的指标类别名条目（一对一）。
- **`default_predicates`**：`metrics[].default_predicates` 与顶层 `default_predicates[域][].applies_to`**双向一致**也是断言（同上）⇒ 新增谓词必须两处都写。
- **`duplicate_terms`**：本件内 `product_cnt` / `on_sale_product_cnt` 与 `province_cnt` / `province_covered_cnt` **中文名重叠**，落 YAML 时必须做**互斥切分**，否则 `aliases.term` 的一对一断言（现 105/105）会 FAIL。
- **`version`**：改语义包 ⇒ 必须递增 `meta.version`（形态 `YYYY.MM.DD.N`，`07 §6.1`），且缓存 / few-shot 索引失效（附录 B §B.4.1）。

## 6. 纪律与红线

- 🔴 **不迎合那 63 条**：不按题面逐条特判；冻结集是**验收标准**，不是训练集。
- 🔴 本件**不动** `semantic/**`；`status=draft` 的 `sell_through_rate` **不算缺口**，未列。
- 派单用 **`grain` token** 指资产（`sub_order`/`refund_record`/`sku`/`shop`/`province`/`campaign`/`sku_day_channel`/`day`）；本件用 **`logical_name`**，对照已列在第 1 节括号内。
- 零出站、零花费、零取号（指针 `U-143`）。

## 7. 复算入口（`PROMPT.md §5` 三条纪律：带时点 / 附实跑输出＋点名口径 / 禁自指）

- **时点**：第 40 轮 ｜ 生成于 `2026-10-15T02:36:00+00:00`（UTC）
- **命令**（从仓库根，零出站）：

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/probe_semantic_metric_gap.py
```

- **实跑输出**（本机实跑，非「应等于」）：

```text
expected=execute           = 124
其中误拒(outcome=refuse)   = 63 | reason={'no_data_asset': 63}
① 建议新增 metrics         = 13 条
④ 覆盖预估                 = 只补 metric 16 ＋ 还须附面 46 ＋ 不补 1
```

- **口径点名**（数 / 面 / 谓词 / 分母 / 粒度）：
  - 数 = `63`；面 = `eval/results_v1.json`（166 条）**连** `eval/dataset_v1_frozen.json`（按 `case_id`）；
  - 谓词 = `expected_behavior == 'execute'` **且** `outcome == 'refuse'`；分母 = 该谓词命中数 63；
  - 粒度 = **逐 case**（一 case 一票，不按模板块聚合）。
- **禁自指**：本入口是**整脚本复跑**（不是 `grep` 单串），上列「实跑输出」由脚本自身计算后写入，
  **不存在**「pattern 命中写下它的那一行」的自指形态（`PROMPT.md §5` 纪律③的适用对象是 `grep`/`-c` 类入口）。

## 8. 附录：误拒 63 条逐条（`case_id` ｜ 缺口 metric ｜ 非 metric 面 ｜ GROUP BY ｜ 题面）

| case_id | metric | 非 metric 面 | GROUP BY | 题面 |
|---|---|---|---|---|
| `E-ENUM-01` | `pv` | — | — | T_A 直播渠道一共带来多少浏览量？ |
| `E-ENUM-02` | `pv` | — | — | T_A 搜索渠道一共带来多少浏览量？ |
| `E-ENUM-03` | `pv` | — | — | T_A 推荐渠道一共带来多少浏览量？ |
| `E-ENUM-04` | `pv` | — | — | T_A 付费广告渠道一共带来多少浏览量？ |
| `E-ENUM-05` | `pv` | — | — | T_A 直接访问渠道一共带来多少浏览量？ |
| `E-ENUM-06` | `product_cnt` | F-3 | — | T_A 的「3C数码」在架商品有多少个？ |
| `E-ENUM-07` | `product_cnt` | F-3 | — | T_A 的「家用电器」在架商品有多少个？ |
| `E-ENUM-08` | `product_cnt` | F-3 | — | T_A 的「美妆个护」在架商品有多少个？ |
| `E-ENUM-09` | `product_cnt` | F-3 | — | T_B 的「服饰鞋包」在架商品有多少个？ |
| `E-ENUM-10` | `product_cnt` | F-3 | — | T_C 的「食品生鲜」在架商品有多少个？ |
| `E-MET-08` | `E-MET-08` | — | — | T_A 从 2026-08-01 起的付费金额合计（含未支付）是多少？ |
| `E-VER-01` | `day_cnt` | — | — | T_A 2026-08 的日期维表有多少天？ |
| `E-VER-02` | `on_sale_product_cnt` | — | — | T_A 的在架商品数是多少？ |
| `E-VER-03` | `off_sale_product_cnt` | — | — | T_A 的下架商品数是多少？ |
| `E-VER-04` | `spu_cnt` | — | — | T_A 的SPU 数是多少？ |
| `E-VER-05` | `shop_cnt` | — | — | T_A 的店铺数是多少？ |
| `E-VER-06` | `campaign_cnt` | — | — | T_A 的活动数是多少？ |
| `E-VER-07` | `province_cnt` | F-4 | — | T_A 的华东覆盖省份数是多少？ |
| `E-VER-08` | `province_covered_cnt` | — | — | T_A 的收货省份覆盖数是多少？ |
| `E-VER-10` | `on_sale_product_cnt` | — | — | T_B 的在架商品数是多少？ |
| `E-VER-11` | `on_sale_product_cnt` | — | — | T_C 的在架商品数是多少？ |
| `H-CAT-01` | `on_sale_product_cnt` | F-3, F-6 | `v_shop.shop_id` | T_A 的「3C数码」各店铺的商品数分别是多少？ |
| `H-CAT-02` | `on_sale_product_cnt` | F-3, F-6 | `v_shop.shop_id` | T_A 的「家用电器」各店铺的商品数分别是多少？ |
| `H-CAT-03` | `on_sale_product_cnt` | F-3, F-6 | `v_shop.shop_id` | T_A 的「服饰鞋包」各店铺的商品数分别是多少？ |
| `H-CAT-04` | `on_sale_product_cnt` | F-3, F-6 | `v_shop.shop_id` | T_A 的「食品生鲜」各店铺的商品数分别是多少？ |
| `H-CAT-05` | `on_sale_product_cnt` | F-3, F-6 | `v_shop.shop_id` | T_A 的「美妆个护」各店铺的商品数分别是多少？ |
| `H-ENUM-02` | `refunded_order_cnt` | F-6 | `v_shop.shop_id` | T_A 处于「全额退款」状态的订单在各店铺分别是多少笔？ |
| `H-STR-05` | `on_sale_product_cnt` | F-6 | `v_shop.shop_id` | T_A 位于南京的店铺各有多少个商品？ |
| `H-STR-06` | `on_sale_product_cnt` | F-6 | `v_shop.shop_id` | T_A 位于西安的店铺各有多少个商品？ |
| `H-STR-08` | `on_sale_product_cnt` | F-6 | `v_shop.shop_id` | T_A 位于郑州的店铺各有多少个商品？ |
| `H-STR-09` | `avg_list_price` | F-6 | `v_shop.shop_id` | T_A 各店铺的商品平均标价是多少？ |
| `M-DIM-01` | `pv` | F-1 | `sku_id` | T_A 的各 SKU 的浏览量分别是多少？ |
| `M-DIM-02` | `pv` | — | `channel` | T_A 的各渠道的浏览量分别是多少？ |
| `M-DIM-04` | `campaign_cnt` | F-5 | `campaign_type` | T_A 的各活动类型的活动数分别是多少？ |
| `M-DIM-06` | `product_cnt` | F-2 | `spu_id` | T_A 的各 SPU 的 SKU 数分别是多少？ |
| `M-DIM-07` | `product_cnt` | F-3 | `category_l2` | T_A 的各二级类目的商品数分别是多少？ |
| `M-DIM-08` | `province_cnt` | F-4 | `region_name` | 7 个大区各覆盖的省份数分别是多少？ |
| `M-DIM-09` | `product_cnt` | F-3 | `category_l1` | 各一级类目的商品数分别是多少？ |
| `M-DIM-10` | `cart_add_cnt` | — | `channel` | 各渠道的加购次数合计分别是多少？ |
| `M-ENUM-01` | `pv` | F-1 | `sku_id` | T_A 直播渠道各 SKU 的浏览量分别是多少？ |
| `M-ENUM-02` | `pv` | F-1 | `sku_id` | T_A 搜索渠道各 SKU 的浏览量分别是多少？ |
| `M-ENUM-03` | `pv` | F-1 | `sku_id` | T_A 推荐渠道各 SKU 的浏览量分别是多少？ |
| `M-ENUM-04` | `pv` | F-1 | `sku_id` | T_A 付费广告渠道各 SKU 的浏览量分别是多少？ |
| `M-HIER-01` | `on_sale_product_cnt` | F-3 | `category_l1` | T_A 各一级类目的在架商品数分别是多少？ |
| `M-HIER-02` | `on_sale_product_cnt` | F-3 | `category_l2` | T_A 各二级类目的在架商品数分别是多少？ |
| `M-HIER-04` | `product_cnt` | F-3 | `category_l2` | 3C数码下一级各子类的商品数分别是多少？ |
| `M-HIER-05` | `product_cnt` | F-3 | `category_l2` | 家用电器下一级各子类的商品数分别是多少？ |
| `M-HIER-06` | `product_cnt` | F-3 | `category_l2` | 服饰鞋包下一级各子类的商品数分别是多少？ |
| `X-ENUM-01` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「3C数码」商品在各店铺的浏览量合计是多少？ |
| `X-ENUM-02` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「家用电器」商品在各店铺的浏览量合计是多少？ |
| `X-ENUM-03` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「服饰鞋包」商品在各店铺的浏览量合计是多少？ |
| `X-ENUM-04` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「食品生鲜」商品在各店铺的浏览量合计是多少？ |
| `X-ENUM-05` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「美妆个护」商品在各店铺的浏览量合计是多少？ |
| `X-ENUM-06` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「家居家装」商品在各店铺的浏览量合计是多少？ |
| `X-ENUM-07` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「母婴玩具」商品在各店铺的浏览量合计是多少？ |
| `X-ENUM-08` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A 的「运动户外」商品在各店铺的浏览量合计是多少？ |
| `X-MET-01` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A「3C数码」自 2026-08-01 起各店铺的浏览量分别是多少？ |
| `X-MET-02` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A「家用电器」自 2026-08-01 起各店铺的浏览量分别是多少？ |
| `X-MET-03` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A「服饰鞋包」自 2026-06-01 起各店铺的浏览量分别是多少？ |
| `X-MET-04` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A「食品生鲜」自 2026-06-01 起各店铺的浏览量分别是多少？ |
| `X-MET-05` | `pv` | F-3, F-6 | `v_shop.shop_id` | T_A「美妆个护」自 2026-05-01 起各店铺的浏览量分别是多少？ |
| `X-STR-02` | `pv` | F-1, F-6 | `v_product.sku_id` | T_A 在 杭州市 的店铺各 SKU 浏览量合计是多少？ |
| `X-STR-04` | `pv` | F-1, F-6 | `v_product.sku_id` | T_A 在 武汉市 的店铺各 SKU 浏览量合计是多少？ |

> `gold_sql` 全文（每条一份，可直接对拍）在 `probe_semantic_metric_gap.json` 的 `cases[]`。
