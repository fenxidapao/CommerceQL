# Olist 100 题评测报告（B7 · 离线）

> 数据集：`eval/olist/dataset_v3_frozen.json` ｜ 模式：frozen ｜ offline · 未跑 live

## 1. 结论（固定五行）

```
EX_official = UNVERIFIED / scored_total = UNVERIFIED%
分母构成：scored=UNVERIFIED | struct_null_skipped=5 | execute=95 | with_sql=UNVERIFIED | with_result=UNVERIFIED | equivalent=UNVERIFIED
交互正确（不计入 EX）：refuse UNVERIFIED/2 ｜ clarify UNVERIFIED/3
沙箱方言缺口（单列，不是模型错）：UNVERIFIED
若报 EX_exec（非官方，仅 coverage）：UNVERIFIED/95
```


## 2. 分母构成

| batch_id | scored | passed | EX | struct_null_skipped | execute | with_sql | with_result | equivalent | n_unscored | false_clarify | false_refuse | dialect_gap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| — | UNVERIFIED | UNVERIFIED | UNVERIFIED | 5 | 95 | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |

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

refuse `UNVERIFIED`/2 ｜ clarify `UNVERIFIED`/3（未跑 live）

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