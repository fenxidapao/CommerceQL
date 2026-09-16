# 语义包字段契约 SCHEMA_v1（bundle_2026.09.14.1）

> **归属窗口**：W1A（`docs/08 §4.1`：`semantic/**`）
> **状态**：v1 **candidate** —— 结构已落盘并通过 `validate_bundle.py`（24 PASS / 0 FAIL / 1 SKIP / 1 WARN）
> **本文用途**：把「YAML 里每个字段什么形状、谁依赖它、依据是哪条」写成一张可裁定的表。
> 凡标 ★ 的字段，**附录 B v1.1 结构示例里没有定义**，属 W1A 提出的扩展，登记 **U-23** 交架构窗口裁定。
> 裁定前 W2A 可按本表实现；**裁定若与本文冲突，以裁定为准**，W1A 改 YAML。

---

## 0. 权威链（谁说了算）

```
附录 A(02)  >  PRD(01)  >  06 UIUX  >  07 TDD(0.6)  >  08 实施计划
```

本文件**不是**权威来源，是**实现输入**（对 W2A/W2B/W3 而言）。字段来源逐条标注如下。

| 区块 | 结构来源 | 消费者 |
|---|---|---|
| `meta` | 附录 B §B.1.2 + 07 §6.1⑤ | W2A loader |
| `assets` | 附录 B §B.1.2 + 07 §12.2 `asset` 物化表 | W2B 检索 / W3 绑定 / W4 守卫 |
| `metrics` | 附录 B §B.2 + 07 §12.2 `metric_def` | W3 绑定 / W6 评测 |
| `dimensions` | 附录 B + 07 §12.2 `dimension` | **W2A L2 层判据** |
| `field_bindings` | 附录 B §B.3.2 + 07 §6.8.1 | **W2A L3 层判据** |
| `joins` | 附录 B §B.1.3 + 07 §12.2 `join_path` | W4 守卫 R10/R11 |
| `default_predicates` | 附录 B + 07 §5.4 | W4 谓词注入 |
| `aliases` ★ | 07 §12.2 `synonym` 物化表（附录 B 无此区块） | W2A L1 层 |
| `blacklist_terms` ★ | 附录 B §B.3.4（无此区块名，是 B.3.4 的落地） | W2A L1 拒答/澄清 |
| `time_semantics` | 附录 B + N-26 | W3 / W4 |
| `policies` | 附录 B §B.3.3 + PRD FR-12.5 | W4 守卫 R07 |
| `quality_gates` | 07 §6.1④ | W2A loader 准入 |

---

## 1. `meta`

`meta.domain` 是**域的单一真相**：所有 `assets[].domain` 必须是它的子集（校验器已断言）。

```yaml
meta:
  version: "2026.09.14.1"        # 形态 YYYY.MM.DD.N（07 §6.1 版本状态机）
  domain: [orders, products, traffic]
  dialect: postgresql             # ⚠️ 语义包声明 postgresql；评测沙箱是 sqlite —— 见 §7 差异说明
  published_at: "..."
  published_by: "data-team"
  status: candidate               # candidate | active | published | deprecated
  timezone: "Asia/Shanghai"
  fiscal_year_start_month: 1      # 附录 B v1.1 已确认（PRD §17.1 / FR-1.3）
  week_starts_on: "monday"        # 决定"本周/上周"边界
  embedding:                      # ★ U-25
    model: "bge-m3"
    dim: 1024
  disclosure_text: "已按系统默认口径回答"   # ★ U-26
```

### ★ U-25 `meta.embedding`

- **问题**：07 §6.1 步骤⑤ 要求「`EMBEDDING_DIM` 与 YAML 声明一致」，但附录 B 结构示例**没有任何位置**声明维度。
- **当前实现**：`meta.embedding.{model,dim}`，值与 `app/core/config.py` 默认（`bge-m3` / 1024）一致；校验器已断言一致。
- **风险**：若架构窗口裁定该声明属**配置项**而非语义包字段，则本字段应删、校验器改为比 config 内两处。

### ★ U-26 `meta.disclosure_text`

- **问题**：07 §6.8 要求「`resolved_default` 态必须披露默认口径」，但**披露文案的唯一来源**未指定。
- **当前实现**：放 `meta.disclosure_text`，单一字符串。
- **替代方案**：放 `metrics[].default_binding.reason`（更细粒度，但同一应答里多个指标会给出多段文案，需拼接规则）。

---

## 2. `assets`（认证资产 —— 检索准入白名单）

**唯一可被检索的资产集合**。未进本包 = 不可检索、不可引用、不可生成。

```yaml
assets:
  - logical_name: order_paid        # 逻辑名（模型可见）
    physical_asset: v_order_paid    # 物理视图名（认证视图，非裸表）
    grain: sub_order
    grain_level: 4                  # ★ U-23
    domain: orders                  # 必须 ∈ meta.domain
    owner: data-team
    certified: true
    tenant_scoped: true             # ★ U-23
    quality_score: 0.98             # ★ U-23
    freshness_sla: "PT6H"           # ISO 8601 duration
    level: hot                      # hot | warm | cold
    row_estimate: 500000
    description: "..."
    columns:
      - name: tenant_id
        type: text
        comment: "..."
        sensitive: tenant_key       # 敏感标记 → 必须在 policies.deny_columns
```

### ★ U-23 · `assets[].grain_level`

- **依赖**：07 §12.2 `asset` 物化表的 `grain_level` 列；L2 层判「粒度是否同族可比」。
- **形状**：**整数，1 = 最粗**。本包刻度见 §3.3。
- **写反的后果**：L2 会把「日粒度」判得比「月粒度」粗 → 度量口径与维度粒度错配被静默放行。

### ★ U-23 · `assets[].tenant_scoped`

- **依赖**：07 §7.4 分支 3 判据（是否注入租户谓词）。
- **形状**：`bool`。`true` = RLS 生效，执行层必须 `SET app.tenant_id`。
- **写反的后果**：**跨租户存在性泄露**（把 `false` 写在有租户数据的资产上 → 不注入谓词 → T_A 能看到 T_B 的行数）。这是 N-07 的直接失效路径，故校验器把 `tenant_scoped: true` 与资产含 `tenant_id` 列做了双向断言。

### ★ U-23 · `assets[].quality_score`

- **依赖**：07 §12.2 `asset.quality_score`；与 `quality_gates.min_quality_score`（=0.90）联判 `certified`。
- **形状**：`0–1` 浮点。
- **当前值**：8 个资产全部 ≥ 0.90（校验器已断言）。

---

## 3. `dimensions`

### 3.1 形状

```yaml
dimensions:
  - name: region
    binding: order_paid.region_code          # 单绑定形态
    hierarchy: [country, region, province, city]
    grain_levels: { country: 1, region: 2, province: 3, city: 4 }
    grain_level: 4                            # ★ U-23：本维度默认细度
    value_map: {...}                          # 业务约定映射（非 DB 字段）
  - name: time
    bindings:                                 # 多绑定形态（时间维度专有）
      day: pay_time
      week: pay_time
      ...
```

### 3.2 单绑定 vs 多绑定

| 形态 | 适用 | 说明 |
|---|---|---|
| `binding: <asset>.<col>` | 一般维度 | 一个默认物理列 |
| `bindings: {<粒度>: <col>}` | **时间维度** | 各粒度可绑不同列（GMV 走 `pay_time`，流量走 `stat_date`） |

### 3.3 ★ U-23 · `grain_levels` / `grain_level`（**刻度族制，不是 1..N**）

**这是本次唯一一处与直觉相反的设计，必须写清楚，否则 W2A 会"修正"它。**

- `grain_level` = **整数，1 = 最粗**，**同一语义族内统一刻度**。
- **地理族**：`country=1 / region=2 / province=3 / city=4`
- **时间族**：`year=1 / quarter=2 / month=3 / week=4 / day=5`
- **类目族**：`category_l1=1 / category_l2=2 / category_l3=3`

**后果**：`dimensions.city` 的 `grain_levels` 是 `{region:2, province:3, city:4}` —— **从 2 起，不是从 1 起**。这是**故意的**，不是笔误。

| 理由 | 说明 |
|---|---|
| L2 的比较发生在**同族内** | `shop.city` 与 `order_paid.receiver_city` 必须可比 → 必须共用族刻度 |
| 若重排为 1..N | `city` 变成 2 起 vs `shop` 的 1 起 → 同粒度被判成不同粒度 → **真歧义被漏判** |
| 校验器规则 | 不断言"1..N 连续"，只断言「层级名与细度值一一对应且**随 `hierarchy` 顺序严格递增**」 |

> ⚠️ **给 W2A 的硬约束**：L2 判"是否同粒度"用的是 **`grain_level` 数值相等**，**不是** `hierarchy` 数组下标。用下标会把 `city`(4) 与 `shop`(1) 误判为不同粒度。

### 3.4 `assets[].grain_level` —— **资产细度档**（与 §3.3 是两套刻度）

**上游事实**：07 §12.2 的 `asset` 物化表列了 `grain_level` 列，但**全文从未定义其语义，也无任何消费者**（实测：`grain_level` 在 07 只出现于 §12.2 表结构清单与 §6.8.1 的 dimension 语境）。本章刻度表为 **W1A 提议**，登记 U-23 待裁定。

| 档 | 含义 | 本包资产 |
|---|---|---|
| 1 | 汇总/活动维 | `campaign` |
| 2 | 地理维（省） | `region` |
| 3 | 店铺维 | `shop` |
| 4 | 明细主数据档 | `product`（SKU）/ `dim_date`（日） |
| 5 | 单据行档 | `order_paid` / `order_refund` |
| 6 | 最细事实档 | `traffic_daily`（SKU × 日 × 渠道） |

#### ⚠️ 为什么不能与 `dimensions[].grain_level` 混用

| | `dimensions[].grain_level` | `assets[].grain_level` |
|---|---|---|
| 刻度 | **族内刻度**（地理族 1–4 / 时间族 1–5 / 类目族 1–3） | **跨资产细度档**（1–6） |
| 比较范围 | 同一维度的**候选之间**（L2） | 不同**资产**之间（若将来有消费者） |
| 混用的后果 | `shop(3)` 与 `city(4)` 会产出**虚假的"粒度关系"**，把两个无关的东西判成可比较 | 同上 |

**给 W2A 的硬约束**：这两个字段**永不出现在同一个比较表达式里**。

### 3.5 `value_map` 的定位

`region.value_map`（大区 → 省编码列表）**是业务约定，不是数据库字段**。
→ 禁止让模型猜大区归属；未列入 `value_map` 的省 → 归"其他"或不支持。

### 3.6 ★ `dimensions[].binding` 指向 `order_paid.receiver_city` 的来源说明

**与附录 C §C.11.2 的差异**：附录 C 的 `v_order_paid` 字段表**只列了 `region_code`（收货省编码）**，没有城市列。但 `dimensions.city.binding` 需要一个城市字段，L2 的"城市 vs 店铺城市"竞争要靠它。
→ W1A 在 `v_order_paid` 补 `receiver_city` 列，理由：`region_code` 只到省，`receiver_address` 是敏感列不可用，城市维度必须有非敏感的独立列承载。**登记 U-27**，并把该列写进 `data/schema.sql`，`selfcheck.py` 断言两处一致。

---

## 4. `metrics`

```yaml
metrics:
  - name: gmv
    display_name: GMV
    domain: orders
    expression: "SUM(order_paid.pay_amount)"
    default_aggregation: sum
    unit: CNY
    owner: finance
    status: active                 # active | draft | deprecated
    definition_note: >
      口径：按支付完成时间（pay_time）统计；含运费；剔除全额退款订单；剔除测试单。
      与财务口径的差异仅在"部分退款"处理上 —— 本口径暂不扣减部分退款。
    default_binding:               # ★ U-23
      asset: order_paid
      time_field: pay_time
      reason: "GMV 的时间基准固定为 pay_time，而非 create_time"
    default_predicates:
      - "pay_status = 'paid'"
```

### ★ U-23 · `metrics[].default_binding`

- **依赖**：07 §12.2 `metric_def.default_binding`；**L3 层依据**。
- **形状**：`{asset, time_field, reason}`。`reason` = 07 §6.8 强制披露的文案来源。
- **纪律**：**`draft` 指标不得有 `default_binding`** —— draft 不参与 L3，若给了默认口径，等于把一个未定口径的指标伪装成已定。校验器已断言（当前 `sell_through_rate` 为 draft 且无绑定、无别名）。

---

## 5. `field_bindings`（唯一性保障 —— 核心机制）

```yaml
field_bindings:
  - concept: 城市
    candidates: [order_paid.receiver_city, shop.city]
    canonical_asset: shop.city          # 存在默认时的规范字段
    default_binding: shop.city          # ★ U-23
    ambiguous: true                     # ⚠️ 与 default_binding 互斥
  - concept: customer_name
    canonical_asset: shop.shop_name
    default_binding: shop.shop_name
    ambiguous: false
```

### 5.1 ⚠️ `default_binding` 与 `ambiguous` 互斥（**最易写错的一条**）

**`ambiguous: true` 的概念不得有 `default_binding`。**
否则 L3 会**抢在澄清之前**把歧义"解决"掉 → 歧义被静默吞掉 → 用户得到看似合理但可能错误的字段。

- 校验器已断言：`ambiguous` 概念数为 1（`城市`），且它 **0 条同时有别名**（保证不发生 L1 短路）。
- 当前 `field_bindings` 7 条中 6 条有 `default_binding`，1 条（`城市`）标 `ambiguous`。

### 5.2 `canonical_asset` 的语义

- **非 ambiguous** 概念：`canonical_asset` 即 `default_binding` 指向的资产。
- **ambiguous** 概念：`canonical_asset` 是**占位**（L3 不消费它，但表结构要求非空）→ 由澄清流程回填。

---

## 6. `joins` / `default_predicates` / `aliases` / `blacklist_terms`

### 6.1 `joins`

```yaml
joins:
  - left: order_paid.sku_id
    right: product.sku_id
    type: many_to_one
    on_columns: [sku_id]
    certified_by: data-team
```

**未列出的路径一律禁止**（附录 B §B.1.3）。防笛卡尔积与错误关联。

**刻意不列出**：`order_paid × traffic_daily` 直连。二者只能经 `product` 桥接（2 跳）。
直连 = 语义错误的关联（订单与流量无共同粒度键）→ 对应红队 `RT-JOIN-003`。

### 6.2 `default_predicates`

按域分组，`applies_to` 必须指向已定义指标（校验器已断言）。
两族：`is_test_order = false`（排测试单）、`refund_status <> 'refunded'`（GMV 剔全额退款）。

### 6.3 ★ `aliases`（**新增顶层区块**）

**为什么必须新增**：附录 B 把同义词散落在 `metric.synonyms` / `column.synonyms` 两处，但 07 §12.2 要求一张**扁平 `synonym` 物化表**供 L1 层做 O(1) 命中。v1 把两处**归一化**到 `aliases`，并加校验：「`column/metric` 的 `synonyms` ⊆ `aliases` 的 term 集」。

```yaml
aliases:
  - { term: "GMV", lang: en, maps_to_kind: metric, maps_to_ref: gmv, category: metric }
  - { term: "成交额", lang: zh, maps_to_kind: metric, maps_to_ref: gmv, category: metric }
```

- `maps_to_kind` ∈ `{asset, metric, column, dimension}`
- **L1 判据**：`term` 必须**一对一**（校验器已断言 105/105）。

### 6.4 ★ `blacklist_terms`（**新增顶层区块**）

附录 B §B.3.4 要求「无对应字段 → 拒答」与「需澄清阈值」，但**没给承载位**。v1 落在 `blacklist_terms`。

```yaml
blacklist_terms:
  - term: "淡季"
    action: refuse            # refuse | clarify
    reason: "无定义的时间概念"
    alt_question: "你可以问「2026 年 3 月的 GMV 是多少」"
```

- 当前：**9 拒答 + 6 澄清 = 15 条**，`clarify_prompt` / `alt_question` 齐全（校验器已断言）。
- **`refuse` 的语义**：**不是 error**。07 要求拒答渲染为 `refuse` 态 + 审计，不得落成 `error`。

---

## 7. 已知口径差异（**必须转达，不得静默**）

| # | 差异 | 处置 |
|---|---|---|
| D-1 | `meta.dialect = postgresql`，但评测沙箱是 **SQLite**（07 §17.4 / 附录 C §C.14） | 语义包声明 PG 方言；沙箱用 SQLite 跑**评测**。SQL 生成时 `sqlglot` 负责转译。**风险**：PG 专有语法（`FILTER`、`DISTINCT ON`）在沙箱不可用 → 已在红队集 `RT-EXEC-*` 标出，W6 执行器需回退策略 |
| D-2 | 大促区间（618/双11）在 `time_semantics` 与 `v_campaign` 两处 | **本包 notes 是口径来源，`v_campaign` 是取数来源**；生成器以本包为准写入，`selfcheck` 断言二者一致 |
| D-3 | `dimensions.city` 的 `grain_levels` 从 2 起 | **故意**，理由见 §3.3。W2A 不得"修正" |

---

## 8. 校验器覆盖矩阵（`validate_bundle.py`）

| 步骤 | 断言数 | 说明 |
|---|---|---|
| ① 读取 YAML | 1 | 无重复 key（自定义 loader 检测） |
| ② 字段齐全性 | 4 | FR-12.2 **15 类** / U-23 扩展字段 5 项 / 域子集 / draft 无 default_binding |
| ③ 引用完整性 | 10 | joins、field_bindings、别名一对一、deny_columns、敏感列双向、default_predicates、grain_levels↔hierarchy、synonyms⊆aliases |
| ④ 质量准入 | 2 | 全部资产 ≥ 0.90 / `on_violation` 语义 |
| ⑤ 环境一致 | 3 | EMBEDDING_DIM / meta 时间语义(N-26) / 版本号形态 |
| （跳） | 1 | `jieba` 词典加载与分词函数 —— 归 W2B（`retrieval/tokenizer.py` 是唯一入口，N-24），本脚本**不 import `app.*`** |
| DoD 自证 | 3 | `default_binding` 覆盖 / 别名覆盖 / 黑话表形态 |

> 校验器**不 import `app.*`** —— 因为 W1A 禁改 `app/**`，且 import 会引入包路径依赖使脚本无法独立运行。这是**刻意的边界**，不是缺失。

---

## 9. 变更纪律

1. 改本包 → 必须递增 `meta.version`（形态 `YYYY.MM.DD.N`）→ 缓存与 few-shot 索引必须失效（附录 B §B.4.1）。
2. 冻结评测集**不随语义包一起改**；语义包升版后，冻结集是否需重生成，由 **W6** 判定并出新版本号。
3. 本文件与 YAML 不一致时，**以 YAML 为准**，并立刻改本文件。
