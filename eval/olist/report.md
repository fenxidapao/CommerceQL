# Olist 60 题评测报告（W2）

> 数据集：`eval/olist/dataset_v1_frozen.json` ｜ 模式：frozen ｜ 3 个独立批次（各自进程 + 各自 --batch-id）

## 1. 结论（固定五行）

```
EX_official = 23 / scored_total = 42.59%
分母构成：scored=54 | struct_null_skipped=5 | execute=55 | with_sql=55 | with_result=36 | equivalent=23
交互正确（不计入 EX）：refuse 2/2 ｜ clarify 2/3
沙箱方言缺口（单列，不是模型错）：12
若报 EX_exec（非官方，仅 coverage）：23/55
```

`EX_official` = 0.4147 ± 0.0133（3 批均值 ± 样本标准差，n=3；batch_id=['w2_r1', 'w2_r2', 'w2_r3']）

> 固定五行中的 `EX_official` / 分母构成 / 交互正确取**第一批**的逐例读数；跨批汇总以本行的均值±样本标准差为准（μ 与 σ 不可混批）。

## 2. 分母构成

| batch_id | scored | passed | EX | struct_null_skipped | execute | with_sql | with_result | equivalent | n_unscored | false_clarify | false_refuse | dialect_gap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| w2_r1 | 54 | 23 | 0.4259 | 5 | 55 | 55 | 36 | 23 | 1 | 0 | 0 | 12 |
| w2_r2 | 55 | 23 | 0.4182 | 5 | 55 | 55 | 38 | 23 | 0 | 0 | 0 | 12 |
| w2_r3 | 55 | 22 | 0.4000 | 5 | 55 | 55 | 38 | 22 | 0 | 0 | 0 | 12 |

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
| w2_r1 | 2/2 | 2/3 |
| w2_r2 | 2/2 | 1/3 |
| w2_r3 | 2/2 | 1/3 |

## 4. 金标与口径（离线证据）

- n_cases / n_execute / n_interaction = 60 / 55 / 5
- gold_executable = 55/55；caliber_match = 55/55；interaction_valid = 5/5
- content_hash = `sha256:f5e78268bf4b20a32d566b7b82a0b2c89fc0bed4f2ba68802846ab0ff978f894`
- full_hash = `sha256:b4491abbf5ccf100bc752b950c6a257f8fc93ac2c8bfc4d2c175330b54bb8928`
- sandbox_db_sha256 = `17c14cee7268e78225afa0406d705cf9a018c984d86697a038682d001fac31b0`
- `wrap_eq_frozen` / `hash_matches`：按冻结件逐例校验

### N-13（Olist profile）

- mode = frozen；all_ok = **True**
- dataset_content_hash = `True`；dataset_full_hash = `True`；sandbox_db_sha256 = `True`

### 仪器正/负控（不是模型 EX）

- positive = 55/55；negative = 0/55；not_ex_official = True
- 负控用**同列名、同行数**的扰动值，确保走值比较分支（空表会走列数早退）。

## 5. 已知偏差

- 无 `ordered` / `percent_ok`：排序只在两侧 SQL 都含 ORDER BY 时按序比；容差固定 `REL_TOL=1e-6`。
- `ast_gate` 是 postgres 方言、沙箱是 SQLite ⇒ 预期出现 `sandbox_dialect_gap`，单列、不归因模型。
- Olist 数据实际止于 2018-08（9 月 1 单、10 月 0 单）。
- `gold_executable` 的分母是 55 条 execute；交互题无 gold，不冒充可执行 SQL。
- 模型把表别名写成 `AS order`（SQL 保留字）⇒ 本轮 7/55 条 `SQL_SYNTAX_ERROR`；这是生成缺陷，不是方言缺口。
- gold 做了 `ROUND`、模型常未做 ⇒ `REL_TOL=1e-6` 判不等（AOV/评分/延迟率多例）；本轮不改判据，W3 裁定是去 gold 的 ROUND 还是把舍入写进 bundle/prompt。
- `delivery_late_rate` 的 bundle expression 未乘 100，模型照 expression 生成 ⇒ SQLite 整数除法归零；这是 bundle 与 gold 口径不一致，不归因模型。
- 批次 r1 有 1 条 `GraphRecursionError`（o19）记 `unscored`，故该批分母 54；其余两批分母 55。
- 零出站回放复核（r1 匣带）：59/60 逐例一致；o19 的 `GraphRecursionError` **不复现**（回放记 `scored` 但仍不等值）⇒ 回放批 23/55、首发 23/54。官方 EX 仍取首发三批，回放件 `results_v1_r1_replay.json` 只作复核证据。
