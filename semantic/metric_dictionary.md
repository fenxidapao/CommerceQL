<!-- GENERATED FILE - DO NOT EDIT BY HAND -->

# 指标口径字典（metric_dictionary）

> **本文件由 `semantic/render_metric_dictionary.py` 从 `bundle_2026.09.14.1.yaml` 自动生成，请勿手改。**
>
> 语义包版本 `2026.09.14.1`｜状态 `candidate`｜指标口径 hash `ecbcb01b08d9563e`
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

