# Olist 100 题评测报告（B7 · live 3 批）

> 数据集：`eval/olist/dataset_v3_frozen.json` ｜ 模式：frozen ｜ 3 个独立批次（各自进程 + 各自 --batch-id）

## 1. 结论（固定五行）

```
EX_official = 69 / scored_total = 72.63%
分母构成：scored=95 | struct_null_skipped=5 | execute=95 | with_sql=94 | with_result=79 | equivalent=69
交互正确（不计入 EX）：refuse 2/2 ｜ clarify 1/3
沙箱方言缺口（单列，不是模型错）：15
若报 EX_exec（非官方，仅 coverage）：69/95
```

`EX_official` = 0.7088 ± 0.0161（3 批均值 ± 样本标准差，n=3；batch_id=['b7_r1', 'b7_r2', 'b7_r3']）

> 固定五行中的 `EX_official` / 分母构成 / 交互正确取**第一批**的逐例读数；跨批汇总以本行的均值±样本标准差为准（μ 与 σ 不可混批）。

## 2. 分母构成

| batch_id | scored | passed | EX | struct_null_skipped | execute | with_sql | with_result | equivalent | n_unscored | false_clarify | false_refuse | dialect_gap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b7_r1 | 95 | 69 | 0.7263 | 5 | 95 | 94 | 79 | 69 | 0 | 0 | 0 | 15 |
| b7_r2 | 95 | 67 | 0.7053 | 5 | 95 | 95 | 77 | 67 | 0 | 0 | 0 | 16 |
| b7_r3 | 95 | 66 | 0.6947 | 5 | 95 | 94 | 76 | 66 | 0 | 0 | 0 | 16 |

### 4×3 网格（数据集现算，execute 题）

| struct \ semantic | low | medium | high |
|---|---|---|---|
| easy | 2 | 1 | 2 |
| medium | 20 | 2 | 8 |
| hard | 6 | 7 | 4 |
| extra | 24 | 11 | 8 |
| **合计** | 52 | 21 | 22 |

## 3. 交互正确（运行时判据，不计入 EX）

判据 = `terminal_event == expected_behavior and infra_error is None`；**不读 `verdict.equivalent`**（交互题 verdict 恒 None）。

| batch_id | refuse | clarify |
|---|---|---|
| b7_r1 | 2/2 | 1/3 |
| b7_r2 | 2/2 | 1/3 |
| b7_r3 | 1/2 | 1/3 |

## 4. 金标与口径（离线证据）

- n_cases / n_execute / n_interaction = 100 / 95 / 5
- gold_executable = 95/95；caliber_match = 95/95；interaction_valid = 5/5
- content_hash = `sha256:ec6b13f27cb9eaa0c4dc3f70031638370dc8b961a1676df50b3da33ca7b24f7e`
- full_hash = `sha256:8777d896d1308e9a3ba5a447d519408aa06fc69e4a625ba5f8bab4eb0d907595`
- sandbox_db_sha256 = `17c14cee7268e78225afa0406d705cf9a018c984d86697a038682d001fac31b0`
- `wrap_eq_frozen` / `hash_matches`：按冻结件逐例校验

### N-13（Olist profile）

- mode = frozen；all_ok = **True**
- dataset_content_hash = `True`；dataset_full_hash = `True`；sandbox_db_sha256 = `True`

### 仪器正/负控（不是模型 EX）

- positive = 95/95；negative = 0/95；not_ex_official = True
- 负控用**同列名、同行数**的扰动值，确保走值比较分支（空表会走列数早退）。

## 5. 已知偏差

- 无 `ordered` / `percent_ok`：排序只在两侧 SQL 都含 ORDER BY 时按序比；容差固定 `REL_TOL=1e-6`。
- `ast_gate` 是 postgres 方言、沙箱是 SQLite ⇒ 预期出现 `sandbox_dialect_gap`，单列、不归因模型。
- Olist 数据实际止于 2018-08（9 月 1 单、10 月 0 单）。
- `gold_executable` 的分母是 95 条 execute；交互题无 gold，不冒充可执行 SQL。