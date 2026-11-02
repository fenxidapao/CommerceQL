# Olist 60 题评测报告（EX v2：三类非模型修复后）

> 数据集：`eval/olist/dataset_v2_frozen.json` ｜ 模式：frozen ｜ 3 个独立批次（各自进程 + 各自 --batch-id）

## 1. 结论（固定五行）

```
EX_official = 41 / scored_total = 74.55%
分母构成：scored=55 | struct_null_skipped=5 | execute=55 | with_sql=55 | with_result=42 | equivalent=41
交互正确（不计入 EX）：refuse 2/2 ｜ clarify 1/3
沙箱方言缺口（单列，不是模型错）：12
若报 EX_exec（非官方，仅 coverage）：41/55
```

`EX_official` = 0.7273 ± 0.0182（3 批均值 ± 样本标准差，n=3；batch_id=['exv2_r1', 'exv2_r2', 'exv2_r3']）

> 固定五行中的 `EX_official` / 分母构成 / 交互正确取**第一批**的逐例读数；跨批汇总以本行的均值±样本标准差为准（μ 与 σ 不可混批）。

## 2. 分母构成

| batch_id | scored | passed | EX | struct_null_skipped | execute | with_sql | with_result | equivalent | n_unscored | false_clarify | false_refuse | dialect_gap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| exv2_r1 | 55 | 41 | 0.7455 | 5 | 55 | 55 | 42 | 41 | 0 | 0 | 0 | 12 |
| exv2_r2 | 55 | 39 | 0.7091 | 5 | 55 | 55 | 42 | 39 | 0 | 0 | 0 | 12 |
| exv2_r3 | 55 | 40 | 0.7273 | 5 | 55 | 55 | 42 | 40 | 0 | 0 | 0 | 12 |

### 4×3 网格（数据集现算，execute 题）

| struct \ semantic | low | medium | high |
|---|---|---|---|
| easy | 2 | 1 | 2 |
| medium | 2 | 2 | 8 |
| hard | 2 | 7 | 4 |
| extra | 6 | 11 | 8 |
| **合计** | 12 | 21 | 22 |

## 3. 交互正确（运行时判据，不计入 EX）

判据 = `terminal_event == expected_behavior and infra_error is None`；**不读 `verdict.equivalent`**（交互题 verdict 恒 None）。

| batch_id | refuse | clarify |
|---|---|---|
| exv2_r1 | 2/2 | 1/3 |
| exv2_r2 | 1/2 | 1/3 |
| exv2_r3 | 1/2 | 1/3 |

## 4. 金标与口径（离线证据）

- n_cases / n_execute / n_interaction = 60 / 55 / 5
- gold_executable = 55/55；caliber_match = 55/55；interaction_valid = 5/5
- content_hash = `sha256:beceddbc92f474aa2d1f22949839314b2181626ac04c29c90943c99382a4685f`
- full_hash = `sha256:1a0c58cc3464f1d3c1fbd5299c75d004d72542bbfadc1c800969e664a124f29a`
- sandbox_db_sha256 = `17c14cee7268e78225afa0406d705cf9a018c984d86697a038682d001fac31b0`
- `wrap_eq_frozen` / `hash_matches`：按冻结件逐例校验

### N-13（Olist profile）

- mode = stamped；all_ok = **True**
- dataset_content_hash = `True`；dataset_full_hash = `True`；sandbox_db_sha256 = `True`

### 仪器正/负控（不是模型 EX）

- positive = 55/55；negative = 0/55；not_ex_official = True
- 负控用**同列名、同行数**的扰动值，确保走值比较分支（空表会走列数早退）。

## 5. 已知偏差

- 无 `ordered` / `percent_ok`：排序只在两侧 SQL 都含 ORDER BY 时按序比；容差固定 `REL_TOL=1e-6`。
- `ast_gate` 是 postgres 方言、沙箱是 SQLite ⇒ 预期出现 `sandbox_dialect_gap`，单列、不归因模型。
- Olist 数据实际止于 2018-08（9 月 1 单、10 月 0 单）。
- `gold_executable` 的分母是 55 条 execute；交互题无 gold，不冒充可执行 SQL。
- **`AS order` 保留字（`U-150`）**：v1 的 `SQL_SYNTAX_ERROR` 已归零，逐批现算见 §6；规则写进 `gen_sql_v1` / `gen_sql_complex_v1` / `repair_v1` 三份 **SQL 侧**提示词，共用 `DIALECT_NOTE` 一字未动（它被 **10** 个模板注入，含 8 个非 SQL 模板）。
- **gold 去 `ROUND`（`U-151`）**：两侧都按原始精度比较；`REL_TOL=1e-6`、排序口径与判据措辞**均未改**。反向风险同框：模型若自己舍入，同样是 1e-5 级相对差而判不等。
- **`delivery_late_rate` ×100（`U-152`）**：语义包 `2026.10.31.1` 的表达式前置 `100.0 *`，一并消掉 SQLite 整数除法归零；v1 的 bundle 与冻结件**一字未改**。
- **R14 / 方言缺口 12 条**：三批一致（见 §6），本窗未修、单列、**不归因模型**。
- **端点与模型**：v2 = `deepseek-v4.1-flash` @ 阿里云百炼；v1 = `deepseek-flash` @ 官方 `api.deepseek.com`。按总控 2026-10-31 裁定**合并成一次读数**，端点差异在此留一句、不拆两套。
- **匣带**：提示词变更使 v1 匣带**预期 miss**（key = `sha256(path + canonical body)`），不重录、不补录、不花钱；属预期失效，不是回归退化。
- **预算上限是累计值**：`--max-cost-cny` / `--max-calls` 比的是 `prior + 本批`（`eval/runner.py::_breached`），**不是每批上限**。
- **三类桶的 0 ≠ 「三类都修干净了」**：`as_order`/`delivery` 的 0 是实测，`round` 的 0 **部分是桶定义使然**（v2 的 gold 已无 `ROUND`）；逐例转换数与仍未等价的 `o38`（时间基准差，不是舍入）见 §6.1。
- 端点=阿里云百炼 deepseek-v4.1-flash（v1 为官方 deepseek-flash），按总控 2026-10-31 裁定合并成一次读数。**交互正确不进 EX 但确有退化**：c01 三批由 clarify 变 complete、r02 在 r2/r3 由 refuse 变 clarify（§3/§6 可见），属模型行为差异，未修。

## 6. v1 → v2 对比（按总控 2026-10-31 裁定：合并成一次读数）

| 指标 | v1 | v2（本报告） |
|---|---|---|
| `EX_official` | 0.4147 ± 0.0133（n=3） | 0.7273 ± 0.0182（n=3） |
| 每批 EX | 0.4259 / 0.4182 / 0.4000 | 0.7455 / 0.7091 / 0.7273 |
| scored 分母 | 54 / 55 / 55 | 55 / 55 / 55 |
| 交互 refuse | 2/2 / 2/2 / 2/2 | 2/2 / 1/2 / 1/2 |
| 交互 clarify | 2/3 / 1/3 / 1/3 | 1/3 / 1/3 / 1/3 |
| 方言缺口（单列） | 12 / 12 / 12 | 12 / 12 / 12 |
| `SQL_SYNTAX_ERROR`（60 题口径，含 `c03` clarify；EX 分母内 6/5/5） | 7 / 6 / 6 | 0 / 0 / 0 |
| `round` 桶（gold 含 `ROUND` 且不等价） | 13 / 14 / 15 | 0 / 0 / 0 |
| `delivery_late_rate` 桶（含于 `round`） | 5 / 5 / 5 | 0 / 0 / 0 |
| R14 / 方言缺口桶（本窗不修） | 12 / 12 / 12 | 12 / 12 / 12 |

> 桶口径 = `eval/olist/report_olist.py::case_buckets`（唯一真相，`backend/reports/exv2/diagnosis.md` 的读数由同一函数现算）；`delivery` 含于 `round`，**两张表不可相加当非等价总数**。

### 6.1 逐例转换（同一 case、同一批次位；桶标签取 **v1** 侧）

| 批次位 | v1 桶内失败 | → 等价 | 仍失败 | 非桶失败→等价 | 回归（v1 等价、v2 失败） |
|---|---|---|---|---|---|
| r1 | 19 | 18 | 1（`o01`） | 0 | 1（`o31`） |
| r2 | 19 | 16 | 3（`g01`、`o05`、`o19`） | 1 | 1（`o24`） |
| r3 | 20 | 17 | 3（`g01`、`o05`、`o38`） | 1 | 0 |
| **合计** | **58** | **51** | **7** | **2** | **2** |

按桶拆（同一批内一个 case 可同时计入 `round` 与 `delivery`，**勿相加当总数**）：

| 桶 | v1 失败条次 | → 等价 | 仍失败 |
|---|---|---|---|
| `as_order` | 16 | 10 | 6 |
| `round` | 42 | 41 | 1 |
| `delivery` | 15 | 15 | 0 |

> ⚠️ **三类桶的 0 证据强度不同**：`as_order` 的 0 = 无 `SQL_SYNTAX_ERROR`（实测）；`delivery` 的 0 = ×100 后判等（实测）；`round` 的 0 **部分是定义使然**（v2 的 gold 已无 `ROUND`，桶自然为空），真正能说的是上表的「逐例转换」数，而仍未等价的那条是**时间基准差**（`o38`：金标按 `review_creation_date` 过滤，模型按 `order_purchase_timestamp`），不是舍入差。
> 因此 **`+31.26pp` 是净观测差，不能整笔记在 3 类修复账上**：端点/模型也换了（v2 百炼 `deepseek-v4.1-flash`、v1 官方 `deepseek-flash`），端点效应未拆分。
> 分母变化来源：`o19`（r1） 在 v1 记 `unscored`、v2 记 `scored` ⇒ 该批分子分母可能**同 +1**，别把它当成「多对了一道」。

> 批次：v2 = ['exv2_r1', 'exv2_r2', 'exv2_r3']；v1 = ['w2_r1', 'w2_r2', 'w2_r3']。
