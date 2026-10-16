<!-- GENERATED FILE - DO NOT EDIT BY HAND -->

# 指标口径字典（metric_dictionary）

> **本文件由 `semantic/render_metric_dictionary.py` 从 `bundle_2026.09.14.1.yaml` 自动生成，请勿手改。**
>
> 语义包版本 `2026.10.16.2`｜状态 `candidate`｜指标口径 hash `76a8e74d8c3b87c4`
>
> 时区 `Asia/Shanghai`；财年起始月 `1`；周起点 `monday`。

## 1. 指标总览

| 指标 | 显示名 | 域 | 单位 | 默认聚合 | 状态 | Owner | 默认时间基准 |
|---|---|---|---|---|---|---|---|
| `gmv` | GMV | orders | CNY | sum | active | finance | pay_time |
| `order_cnt` | 订单量 | orders | 单 | count_distinct | active | operations | pay_time |
| `aov` | 客单价 | orders | CNY | ratio_of_sums | active | operations | pay_time |
| `arpu` | 人均消费 | orders | CNY | ratio_of_sums | active | operations | pay_time |
| `refund_rate` | 退款率 | orders | ratio | ratio_of_sums | active | finance | pay_time |
| `repurchase_rate_90d` | 90天复购率 | orders | ratio | ratio_of_sums | active | operations | pay_time |
| `uv` | UV | traffic | 人 | sum | active | operations | stat_date |
| `pay_cvr` | 支付转化率 | traffic | ratio | ratio_of_sums | active | operations | stat_date |
| `sell_through_rate` | 动销率 | products |  |  | draft |  | — |
| `pv` | 浏览量 | traffic | 次 | sum | active | operations | stat_date |
| `cart_add_cnt` | 加购次数 | traffic | 次 | sum | active | operations | stat_date |
| `product_cnt` | 商品数 | products | 个 | count | active | operations | current |
| `on_sale_product_cnt` | 在架商品数 | products | 个 | count | active | operations | current |
| `off_sale_product_cnt` | 下架商品数 | products | 个 | count | active | operations | current |
| `spu_cnt` | SPU 数 | products | 个 | count_distinct | active | operations | current |
| `avg_list_price` | 商品平均标价 | products | CNY | avg | active | operations | current |
| `shop_cnt` | 店铺数 | products | 个 | count | active | operations | current |
| `campaign_cnt` | 活动数 | orders | 个 | count | active | operations | current |
| `province_cnt` | 覆盖省份数 | orders | 个 | count | active | operations | current |
| `province_covered_cnt` | 收货省份覆盖数 | orders | 个 | count_distinct | active | operations | pay_time |
| `day_cnt` | 天数 | orders | 天 | count | active | operations | current |
| `refunded_order_cnt` | 全额退款订单数 | orders | 笔 | count_distinct | active | finance | pay_time |

> **`status = draft` 的指标没有 `default_binding`、也没有别名** —— 这是刻意的：未定口径的指标不得被检索命中（附录 C §C.5.2 / FR-12.3）。
>
> ⚠️ **时间基准读的是 `metrics[].time_basis`**。曾有一个 `default_binding.time_field` 字段承载同一件事 —— 已由 07 §4.7.1 裁定**删除**（同一事实两处必然漂移）。

## 2. 逐指标口径

### 2.1 `gmv` — GMV

- **表达式**：`SUM(order_paid.pay_amount)`
- **默认聚合**：`sum`｜**单位**：CNY｜**域**：orders｜**Owner**：finance｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：GMV 的时间基准固定为 pay_time，而非 create_time
- **默认谓词**：
  - `pay_status = 'paid'` —— 仅统计已支付
  - `refund_status <> 'refunded'` —— GMV 口径剔除全额退款
  - `is_test_order = false` —— 排除测试单
- **口径说明**：
  - 口径：按支付完成时间（pay_time）统计；含运费；剔除全额退款订单；剔除测试单。 与财务口径的差异仅在"部分退款"处理上 —— 本口径暂不扣减部分退款。
- **同义词（须与别名表一致）**：GMV、gmv、成交额、销售额、交易额、成交金额、流水

### 2.2 `order_cnt` — 订单量

- **表达式**：`COUNT(DISTINCT order_paid.sub_order_id)`
- **默认聚合**：`count_distinct`｜**单位**：单｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：订单量同为交易口径，与 GMV 共用时间基准
- **默认谓词**：
  - `pay_status = 'paid'` —— 仅统计已支付
  - `refund_status <> 'refunded'` —— GMV 口径剔除全额退款
  - `is_test_order = false` —— 排除测试单
- **口径说明**：
  - 按子订单计数（非父订单）；仅已支付、未取消、未全额退款。
- **同义词（须与别名表一致）**：订单量、单量、订单数、成交单量、出单量

### 2.3 `aov` — 客单价

- **表达式**：`SUM(order_paid.pay_amount) / NULLIF(COUNT(DISTINCT order_paid.sub_order_id), 0)`
- **默认聚合**：`ratio_of_sums`｜**单位**：CNY｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：客单价属交易口径
- **默认谓词**：
  - `pay_status = 'paid'` —— 仅统计已支付
  - `refund_status <> 'refunded'` —— GMV 口径剔除全额退款
  - `is_test_order = false` —— 排除测试单
- **口径说明**：
  - ⚠️ 高危口径。分母 = **支付子订单数**（非买家数、非父订单数）。 若业务需要"人均消费"，应使用独立指标 arpu，**不要复用 aov**。 ⚠️ "件单价"（pay_amount / quantity）**不是** aov → 见 blacklist_terms。
- **同义词（须与别名表一致）**：客单价、平均订单金额、AOV

### 2.4 `arpu` — 人均消费

- **表达式**：`SUM(order_paid.pay_amount) / NULLIF(COUNT(DISTINCT order_paid.buyer_id), 0)`
- **默认聚合**：`ratio_of_sums`｜**单位**：CNY｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：人均消费属交易口径
- **默认谓词**：
  - `pay_status = 'paid'` —— 仅统计已支付
  - `refund_status <> 'refunded'` —— GMV 口径剔除全额退款
  - `is_test_order = false` —— 排除测试单
- **口径说明**：
  - 分母 = 去重买家数。与 aov **不可混用**。
- **同义词（须与别名表一致）**：人均消费、人均产出、ARPU

### 2.5 `refund_rate` — 退款率

- **表达式**：`SUM(CASE WHEN order_paid.refund_status = 'refunded' THEN order_paid.pay_amount ELSE 0 END) / NULLIF(SUM(order_paid.pay_amount), 0)
`
- **默认聚合**：`ratio_of_sums`｜**单位**：ratio｜**域**：orders｜**Owner**：finance｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：退款率以支付订单为分母，时间随分母
- **默认谓词**：
  - `pay_status = 'paid'` —— 仅统计已支付
  - `is_test_order = false` —— 排除测试单
- **口径说明**：
  - **按金额、按退款完成**。若要按单量口径，须另立 refund_rate_qty（P1）。
- **同义词（须与别名表一致）**：退款率、退货率、退款占比

### 2.6 `repurchase_rate_90d` — 90天复购率

- **表达式**：`COUNT(DISTINCT CASE WHEN cnt >= 2 THEN buyer_id END) / NULLIF(COUNT(DISTINCT buyer_id), 0)
`
- **默认聚合**：`ratio_of_sums`｜**单位**：ratio｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：复购窗口以支付时间为基准
- **默认谓词**：
  - `pay_status = 'paid'` —— 仅统计已支付
  - `is_test_order = false` —— 排除测试单
- **口径说明**：
  - 90 天内购买 ≥ 2 次；**不含首单口径**。周期固定 90 天，不接受运行时改窗口。
- **同义词（须与别名表一致）**：复购率、回购率、复购

### 2.7 `uv` — UV

- **表达式**：`SUM(traffic_daily.uv)`
- **默认聚合**：`sum`｜**单位**：人｜**域**：traffic｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `traffic_daily`｜时间基准 `stat_date`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：流量表的时间基准是 stat_date（date 型），不是 pay_time
- **默认谓词**：
  - `uv >= 0` —— 防御性谓词：排除脏数据负数访客（生成器会注入 0 值，但不会注入负数）
- **口径说明**：
  - 按用户去重、**自然日窗口**。跨日直接累加会重复计数 —— 跨日区间应使用独立口径 uv_period（P1，本包未定义 → 未定义的指标**不得被生成**）。
- **同义词（须与别名表一致）**：UV、uv、访客数、独立访客

### 2.8 `pay_cvr` — 支付转化率

- **表达式**：`SUM(traffic_daily.order_cnt) * 1.0 / NULLIF(SUM(traffic_daily.uv), 0)`
- **默认聚合**：`ratio_of_sums`｜**单位**：ratio｜**域**：traffic｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `traffic_daily`｜时间基准 `stat_date`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：转化率的分母是流量，时间随 UV
- **默认谓词**：
  - `uv >= 0` —— 防御性谓词：排除脏数据负数访客（生成器会注入 0 值，但不会注入负数）
- **口径说明**：
  - **支付**转化（非下单转化），分母为 UV。转化率不落成列，只在此定义。
- **同义词（须与别名表一致）**：转化率、支付转化率、CVR、成交转化、转化

### 2.9 `sell_through_rate` — 动销率

- **表达式**：``
- **默认聚合**：``｜**单位**：｜**域**：products｜**Owner**：｜**状态**：`draft`
- **默认绑定**：无（draft 指标不参与 L3 绑定）
- **口径说明**：
  - 口径待业务确认（观察周期、分母是否含下架商品）。**确认前不对外开放**。
- **同义词（须与别名表一致）**：动销率、动销

### 2.10 `pv` — 浏览量

- **表达式**：`SUM(traffic_daily.pv)`
- **默认聚合**：`sum`｜**单位**：次｜**域**：traffic｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `traffic_daily`｜时间基准 `stat_date`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：浏览量只存在于流量表，时间随统计日
- **口径说明**：
  - 页面浏览量：**不去重**、按次累计。与 `uv`（按用户去重、自然日窗口）**不是同一件事** —— 把 pv 当 uv 报，等于把跨日重复计数说成访客数。跨日区间可直接累加（uv 不可以）。
- **同义词（须与别名表一致）**：浏览量、PV、pv、页面浏览量、浏览次数、访问量、曝光量

### 2.11 `cart_add_cnt` — 加购次数

- **表达式**：`SUM(traffic_daily.cart_add_cnt)`
- **默认聚合**：`sum`｜**单位**：次｜**域**：traffic｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `traffic_daily`｜时间基准 `stat_date`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：加购行为记在流量日粒度表上
- **口径说明**：
  - 加购次数：**不去重**、按次计数。是转化漏斗的中间一步（uv → 加购 → 支付），与 `pay_cvr` 串联使用。
- **同义词（须与别名表一致）**：加购次数、加购数、加购量、加购、加购人次

### 2.12 `product_cnt` — 商品数

- **表达式**：`COUNT(*)`
- **默认聚合**：`count`｜**单位**：个｜**域**：products｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `product`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：商品数是维表存量口径，时间语义为当前值
- **口径说明**：
  - **存量**计数（维表快照，非交易口径）：不区分上/下架。 `time_basis = current` ⇒ 与任何时间区间**无关**；"某月的商品数"在语义上不存在 （若要"某月新上架数"须另立指标，本包未定义 ⇒ 不得被生成）。
- **同义词（须与别名表一致）**：商品数、商品数量、商品个数、SKU数、SKU数量、sku数、款式数、货品数

### 2.13 `on_sale_product_cnt` — 在架商品数

- **表达式**：`COUNT(*) WHERE on_sale = true`
- **默认聚合**：`count`｜**单位**：个｜**域**：products｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `product`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：在架商品数是维表存量口径，时间语义为当前值
- **口径说明**：
  - **在售状态的存量**商品数。过滤条件 `on_sale = true` **写在 `expression` 里** （不是 `default_predicates`）：本包的 `default_predicates` 是**域级**业务规则， gate1 R06 会把它注入到**本域每一个能表达它的资产**上 ⇒ 写在域里会让 "任意商品查询"都被强制只看在架（静默算错）。谓词一律写 `on_sale = true`， 不写 `on_sale <> false`（后者会漏掉 `on_sale IS NULL` 的行）。
- **同义词（须与别名表一致）**：在架商品数、在架商品、在售商品数、在售商品、上架商品数、在架SKU数、在售SKU数、在架商品个数

### 2.14 `off_sale_product_cnt` — 下架商品数

- **表达式**：`COUNT(*) WHERE on_sale = false`
- **默认聚合**：`count`｜**单位**：个｜**域**：products｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `product`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：下架商品数是维表存量口径，时间语义为当前值
- **口径说明**：
  - **已下架的存量**商品数（过滤条件同样写在 `expression` 里，理由见上条）。 与 `on_sale_product_cnt` **互补**，但**两者相加 ≠ product_cnt** （`on_sale IS NULL` 的行两边都不计）。
- **同义词（须与别名表一致）**：下架商品数、下架商品、停售商品数、已下架商品数

### 2.15 `spu_cnt` — SPU 数

- **表达式**：`COUNT(DISTINCT product.spu_id) WHERE on_sale = true`
- **默认聚合**：`count_distinct`｜**单位**：个｜**域**：products｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `product`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：SPU 由 SKU 表唯一承载，默认按在售口径计数
- **口径说明**：
  - **按 `spu_id` 去重**的存量计数（"款数"），默认按**在售**口径（过滤条件写在 `expression` 里）。 若要"全部款数（含已下架）"，须显式去掉该过滤 —— 默认口径**不是**全量， 这是刻意选定的业务默认，已在披露文案里说明。
- **同义词（须与别名表一致）**：SPU数、SPU数量、SPU个数、款数、款式数量

### 2.16 `avg_list_price` — 商品平均标价

- **表达式**：`AVG(product.list_price) WHERE on_sale = true`
- **默认聚合**：`avg`｜**单位**：CNY｜**域**：products｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `product`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：标价是商品维表列，默认按在售口径取均值
- **口径说明**：
  - **标价（吊牌价），非成交价**，默认按在售口径（过滤条件写在 `expression` 里）。 成交侧的"件单价 / 客单价"分别由 `aov` 与 `blacklist_terms` 里的"件单价"承接 —— **不要**把本条当成交价用。
- **同义词（须与别名表一致）**：商品平均标价、平均标价、平均吊牌价、标价均值、商品平均吊牌价

### 2.17 `shop_cnt` — 店铺数

- **表达式**：`COUNT(*)`
- **默认聚合**：`count`｜**单位**：个｜**域**：products｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `shop`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：店铺数是维表存量口径，时间语义为当前值
- **口径说明**：
  - **存量**店铺数（维表快照）。⚠️ 与「各店铺的…」（按 `shop_id` 分组）不同：后者是分组面，不是本指标。
- **同义词（须与别名表一致）**：店铺数、店铺数量、店铺个数、门店数、店铺家数

### 2.18 `campaign_cnt` — 活动数

- **表达式**：`COUNT(*)`
- **默认聚合**：`count`｜**单位**：个｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `campaign`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：活动数是维表存量口径，时间语义为当前值
- **口径说明**：
  - **存量**活动数（维表快照）。⚠️ **刻意不挂 `campaign_type = 'normal_sale'` 默认谓词**： "活动数"到底含不含大促（`prom_618` / `prom_double11` 共 12 条）**尚未经业务确认** ⇒ 默认口径取**全量**（`v_campaign` 84 条），要只看日常促销请在问句里显式限定类型。
- **同义词（须与别名表一致）**：活动数、活动数量、活动个数、活动场次、促销活动数

### 2.19 `province_cnt` — 覆盖省份数

- **表达式**：`COUNT(*)`
- **默认聚合**：`count`｜**单位**：个｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `region`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：省份清单是公共参考维表，时间语义为当前值
- **口径说明**：
  - **`v_region` 维表上的存量省份数**（现读 31），默认资产 `region`，按 `region_name` 筛选或分组即得。本指标是**存量清单口径**（`time_basis: current`）⇒ **不需要澄清**、 也不需要任何时间范围。判别规则（**可直接执行，不得判 blocking**）：问句里出现 "大区 / 区域"以及"覆盖省份 / 省份数"等**清单类**说法 → **本条**；只有问句明确要 "实际卖出去的 / 成交覆盖到的省份数"（订单事实口径）时才用 `province_covered_cnt`。
- **同义词（须与别名表一致）**：省份数、省份数量、省份个数、覆盖省份数、省份覆盖数

### 2.20 `province_covered_cnt` — 收货省份覆盖数

- **表达式**：`COUNT(DISTINCT order_paid.region_code) WHERE region_code IS NOT NULL`
- **默认聚合**：`count_distinct`｜**单位**：个｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：收货省份覆盖数依赖订单事实，时间随支付时间
- **口径说明**：
  - **订单实际覆盖到的收货省份数**（跨列去重，落在事实表）。与 `province_cnt` （维表清单）是**两个不同指标、不同资产**，各有各的别名，不必也无法"择一"： 本指标只应答"实际卖出去的 / 成交覆盖到的省份数"；问"大区 / 区域有多少个省" 一律用 `province_cnt`。 `region_code IS NOT NULL` 写在 `expression` 里（理由同 `on_sale_product_cnt`： 域级谓词会被 gate1 R06 注入到本域**所有**资产）。
- **同义词（须与别名表一致）**：收货省份覆盖数、收货省份数、收货覆盖省份数

### 2.21 `day_cnt` — 天数

- **表达式**：`COUNT(*)`
- **默认聚合**：`count`｜**单位**：天｜**域**：orders｜**Owner**：operations｜**状态**：`active`
- **默认绑定**：资产 `dim_date`｜时间基准 `current`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：天数是公共日历维表口径，时间语义为当前值
- **口径说明**：
  - **日历维表的存量天数**（`v_dim_date` 现读 730，区间 2024-10-01 … 2026-09-30）。 问"某月有多少天"须**显式**加月份筛选谓词 —— 本指标默认**不带**任何时间谓词。
- **同义词（须与别名表一致）**：天数、日期数、日历天数、日期维表天数、统计天数、日期个数

### 2.22 `refunded_order_cnt` — 全额退款订单数

- **表达式**：`COUNT(DISTINCT order_paid.sub_order_id) WHERE refund_status = 'refunded' AND pay_status = 'paid'`
- **默认聚合**：`count_distinct`｜**单位**：笔｜**域**：orders｜**Owner**：finance｜**状态**：`active`
- **默认绑定**：资产 `order_paid`｜时间基准 `pay_time`（读 `time_basis`，非 time_field）
  - 默认理由是**必须披露**的（07 §6.8 / §4.7.1 的 U-26 披露链路，最终载体 = `insight.caveats[]`，≤ 40 字）：退款笔数以支付子订单为分母，时间随支付时间
- **口径说明**：
  - **按退款状态计数**（不是比率）。两条过滤**写在 `expression` 里**（理由同 `on_sale_product_cnt`：域级谓词会被 R06 注入到本域所有资产，`refund_status = 'refunded'` 若进域会让**任何订单查询**都被过滤成"只看全额退款单"）。 口径镜像 `refund_rate` 的例外模式：分子正是退款行为本身。 若要"部分退款"或"无退款"笔数，请显式限定 `refund_status`，本指标默认只给"全额退款"。
- **同义词（须与别名表一致）**：全额退款订单数、退款订单数、全额退款笔数、退款笔数、退款单量

## 3. 易混指标对照（**口径差异必须显式**）

| 指标 | 口径差异要点 |
|---|---|
| `gmv` | 口径：按支付完成时间（pay_time）统计；含运费；剔除全额退款订单；剔除测试单。 与财务口径的差异仅在"部分退款"处理上 —— 本口径暂不扣减部分退款。 |

## 4. 维度口径（与指标联用时的时间/空间边界）

- **transaction_time**：交易发生时的时间戳（pay_time / create_time / refund_time / stat_date）
- **current**：主数据当前值
- **period_end_snapshot**：统计期末快照
- **时间口径明细**：
  - '上个月' = 日历上月首日 00:00:00 至末日 23:59:59（Asia/Shanghai）
  - '近7天' = 含今天往前 7 个自然日
  - '本周' 起点 = **周一**（对齐 meta.week_starts_on）
  - '618' = 2026-05-24 至 2026-06-20（**含预售期**）
  - '双11' = 2026-10-20 至 2026-11-11（**含预售期**）
  - '同比' = 去年同期；'环比' = 上一相邻周期

- **`region` 的 value_map 是业务约定，不是数据库字段** —— 共 7 组；未列入的取值归「其他」或不支持，**禁止让模型猜**。

## 5. 变更纪律

| 动作 | 必须做的事 |
|---|---|
| 改任何口径 | 改 `bundle_*.yaml` 的 `meta.version` + 重跑本脚本 |
| 语义包升版 | 缓存键与 few-shot 索引必须失效（附录 B §B.4.1） |
| 冻结集是否需重生 | 由 **W6** 判定并出新版本号，**不得静默沿用** |

