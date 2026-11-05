# eval/olist —— Olist 真实数据轨的评测侧

> 归属窗口：W1 实施窗（`U-143`）＋ W2 实施窗（`U-144`/`U-145`/`U-146`，`docs/07 §4.8`）
> 零 PG。本目录只跑 **SQLite 沙箱**上的 gold SQL；离线默认零 LLM 零出站，
> live 只在本窗一次性授权下跑过（账本前置门 + 路径围栏，见 §6.11）。

## 1. 目录

| 文件 | 作用 |
|---|---|
| `build_dataset.py` | **P0 写保护** + `--stamp` / `--check` / `--freeze`；Olist 侧唯一落盘入口 |
| `run_olist.py` | `--gold-only` / `--verify-only` / `--instrument-control` / `--batch` |
| `olist_profile.py` | N-13 Olist 验真（与 `_bootstrap.verify_frozen_inputs()` 同形） |
| `hashing.py` | 两个并列哈希：共享 `content_hash` + Olist 自定 `full_hash` |
| `report_olist.py` | 报告生成：固定五行、分母构成、3 批 EX 均值±样本标准差 |
| `dataset_v1.yaml` | **60 题**源集（55 execute / 3 clarify / 2 refuse），g01..g10 原样承接 |
| `dataset_v1_frozen.json` | 冻结件（冒烟通过后 `--freeze` 生成）；3 批 live 只认它 |
| `dataset_v3.yaml` | **100 题**源集（95 execute / 3 clarify / 2 refuse）；v2 的 60 题原样承接 + `n01..n40` |
| `dataset_v3_frozen.json` | v3 冻结件（`scored_total=95`）；B7 live 只认它 |
| `gold100_frozen_results.json` | v3 逐题 gold 读数（95/95 可执行、95/95 口径） |
| `olist_profile_v3.json` | v3 的 N-13 证据块（`all_ok=true`） |
| `instrument_control_v3.json` | v3 仪器正/负控（+95/95、−0/95；**不是模型 EX**） |
| `report_v3.md` / `report_v3.json` | v3 报告（当前 offline：EX 段 `UNVERIFIED`，未跑 live） |
| `dataset_w1_gold10.yaml` | W1 的 10 条 gold（对账基准，不改） |
| `gold60_results.json` / `gold60_frozen_results.json` | 60 题的逐题 gold 读数（源集 / 冻结件各一份） |
| `olist_profile.json` / `olist_profile_frozen.json` | N-13 证据块（源模式 / 冻结件模式，均 `all_ok=true`） |
| `instrument_control.json` | 仪器正/负控（+55/55、−0/55；**不是模型 EX**） |
| `results_v1_smoke.json` / `results_v1_r1..r3.json` | 冒烟批 / 3 个独立 live 批的逐题读数（EX 源件） |
| `results_v1_r1_replay.json` | r1 的零出站回放复核（59/60 与首发逐例一致） |
| `budget_smoke.json` / `budget_full.json` | 共享预算账本（`W77_CALLS_LEDGER/v1`，每次尝试一行） |
| `report.md` / `report.json` | 最终报告（EX = 3 批均值 ± 样本标准差） |
| `cassettes/` | live 回放匣带（**不入库**，见 §1.1） |
| `gold10_results.json` / `gold10_report.md` | W1 证据（历史读数，不改） |
| `sandbox_manifest.json` | 沙箱行数 / 体积 / sha256（`deploy/demo/build_olist_sandbox.py` 生成） |

### 1.1 cassettes 不入库

3 个整批回放匣带共约 11 MiB（每批 ~3.7 MiB），且逐题 SQL/行数/判据已在
`results_v1_r*.json` 里，同一份信息不落两遍。因此 `.gitignore` 掉
`eval/olist/cassettes/`。**报告复算不依赖匣带**：`report_olist.py --results …` 即可
（2026-10-28 实测：同一组输入重跑 `report.md` 逐字节相同）。

本机回放（零出站；匣带缺省路径是 `olist_v1_{batch_id}.jsonl`，与记录的
`olist_v1_r1.jsonl` 不同名，**必须显式给 `--cassette`**）：

```bash
"$V" eval/olist/run_olist.py --batch --yes \
  --dataset eval/olist/dataset_v1_frozen.json --db data/olist/olist_sandbox.db \
  --cassette eval/olist/cassettes/olist_v1_r1.jsonl --batch-id w2_r1 \
  --out eval/olist/results_v1_r1_replay.json
```

读数：59/60 逐例一致；o19 的 `GraphRecursionError` 不复现（回放 23/55，首发 23/54）。
official EX 取首发三批，不取回放件。换机器要重放就得重录（= 花钱）。

## 2. 跑法（仓库根）

⚠️ **解释器用 archive 里那个 3.13 venv**（仓库根不放 `.venv`）：

```bash
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"
"$V" --version   # 3.13.14（沙箱 sha256 与解释器绑定，见 §6）
```

```bash
# 1. 维护源集两个 stamp（改题后必跑；只改文件头，不碰正文）
"$V" eval/olist/build_dataset.py --stamp --source eval/olist/dataset_v1.yaml

# 2. 复算 stamp + 逐题 C1–C7 + 每例 ≥1 行（不写盘）
"$V" eval/olist/build_dataset.py --check \
  --source eval/olist/dataset_v1.yaml --db data/olist/olist_sandbox.db

# 3. N-13 源模式验真（失败 exit 3）
"$V" eval/olist/run_olist.py --verify-only \
  --dataset eval/olist/dataset_v1.yaml --db data/olist/olist_sandbox.db \
  --out eval/olist/olist_profile.json

# 4. 60 题 gold + 口径
"$V" eval/olist/run_olist.py --gold-only \
  --dataset eval/olist/dataset_v1.yaml --db data/olist/olist_sandbox.db \
  --out eval/olist/gold60_results.json

# 5. 仪器正/负控（零 LLM）
"$V" eval/olist/run_olist.py --instrument-control \
  --dataset eval/olist/dataset_v1.yaml --db data/olist/olist_sandbox.db \
  --out eval/olist/instrument_control.json

# 6. 跑批计划（无 --yes 不构造 Harness、不写盘）
"$V" eval/olist/run_olist.py --batch --limit 10 \
  --dataset eval/olist/dataset_v1.yaml --db data/olist/olist_sandbox.db \
  --batch-id w2_smoke --cassette eval/olist/cassettes/olist_v1_smoke.jsonl \
  --out eval/olist/results_v1_smoke.json

# 7. 报告（offline：EX 段全部 UNVERIFIED）
"$V" eval/olist/report_olist.py \
  --dataset eval/olist/dataset_v1.yaml --profile eval/olist/olist_profile.json \
  --gold eval/olist/gold60_results.json --control eval/olist/instrument_control.json \
  --out eval/olist/report.md --json-out eval/olist/report.json
```

### 2.1 B7：v3（100 题）复算命令与现跑读数

2026-11-05 现跑（零 LLM、零出站）：

```bash
"$V" eval/olist/build_dataset.py --check \
  --source eval/olist/dataset_v3.yaml --db data/olist/olist_sandbox.db
"$V" eval/olist/build_dataset.py --freeze \
  --source eval/olist/dataset_v3.yaml --db data/olist/olist_sandbox.db \
  --out eval/olist/dataset_v3_frozen.json
"$V" eval/olist/run_olist.py --gold-only \
  --dataset eval/olist/dataset_v3_frozen.json --db data/olist/olist_sandbox.db \
  --out eval/olist/gold100_frozen_results.json
"$V" eval/olist/run_olist.py --instrument-control \
  --dataset eval/olist/dataset_v3_frozen.json --db data/olist/olist_sandbox.db \
  --out eval/olist/instrument_control_v3.json
"$V" eval/olist/run_olist.py --verify-only \
  --dataset eval/olist/dataset_v3_frozen.json --db data/olist/olist_sandbox.db \
  --out eval/olist/olist_profile_v3.json
"$V" eval/olist/report_olist.py --dataset eval/olist/dataset_v3_frozen.json \
  --profile eval/olist/olist_profile_v3.json \
  --gold eval/olist/gold100_frozen_results.json \
  --control eval/olist/instrument_control_v3.json \
  --title "Olist 100 题评测报告（B7 · 离线）" --no-v1-deviations \
  --out eval/olist/report_v3.md --json-out eval/olist/report_v3.json
```

读数：`n_cases=100`、`n_execute=95`、`n_interaction=5`；`gold_executable=95/95`、
`caliber_match=95/95`、`interaction_valid=5/5`、`cases_valid=100/100`；
N-13 `all_ok=true`；正控 95/95、负控 0/95。冻结哈希见
`dataset_v3_frozen.json` 头部。**EX 未跑 live，固定五行全部 `UNVERIFIED`**；
live 3 批估算约 ¥2.75 + 冒烟，未批准不跑。

live（需进程环境已注入 `DEEPSEEK_API_KEY`；冒烟通过后才冻结）：

```bash
# 冒烟 ≤¥5，独立账本
"$V" eval/olist/run_olist.py --batch --live --yes --limit 10   --dataset eval/olist/dataset_v1.yaml --db data/olist/olist_sandbox.db   --cassette eval/olist/cassettes/olist_v1_smoke.jsonl --batch-id w2_smoke   --max-cost-cny 5 --max-calls 200 --budget-ledger eval/olist/budget_smoke.json   --out eval/olist/results_v1_smoke.json

# 只此一次冻结；改集走 v2
"$V" eval/olist/build_dataset.py --freeze --source eval/olist/dataset_v1.yaml   --db data/olist/olist_sandbox.db --out eval/olist/dataset_v1_frozen.json

# 3 个独立批次（各自进程 + 各自 batch-id；共享账本）
for r in 1 2 3; do
  "$V" eval/olist/run_olist.py --batch --live --yes     --dataset eval/olist/dataset_v1_frozen.json --db data/olist/olist_sandbox.db     --cassette eval/olist/cassettes/olist_v1_r$r.jsonl --batch-id w2_r$r     --max-cost-cny 50 --max-calls 1500 --budget-ledger eval/olist/budget_full.json     --out eval/olist/results_v1_r$r.json
done

# 报告（3 批 → EX 均值 ± 样本标准差）
"$V" eval/olist/report_olist.py --dataset eval/olist/dataset_v1_frozen.json   --results eval/olist/results_v1_r1.json eval/olist/results_v1_r2.json             eval/olist/results_v1_r3.json   --profile eval/olist/olist_profile_frozen.json   --gold eval/olist/gold60_frozen_results.json --control eval/olist/instrument_control.json   --out eval/olist/report.md --json-out eval/olist/report.json
```

## 3. 三条边界（写进代码，不只是文档）

1. **不调用 `_bootstrap.verify_frozen_inputs()`**。它拿合成冻结集的
   `sandbox_db_sha256` 比 `data/ecom_sandbox.db`；Olist 走 `olist_profile.py`。
2. **`eval/runner.py` 只加透传**（U-145）：`run_batch(..., bundle_path=None)` 把
   bundle/db 传给 `Harness`，并在返回值记 `executor`。`runner.main`、默认常量、
   166 题判据都不改 —— `run_olist.py --batch` 是 Olist 的独立入口。
3. **不扩展 `build_frozen_set.TENANT_SCOPED`**。那份常量是合成 6 表；Olist 的租户
   隔离靠 `open_sandbox_connection` 建的 TEMP VIEW。

## 4. 两个哈希（并列，不互相替代）

| 哈希 | 覆盖 | 维护 |
|---|---|---|
| `content_hash` | `build_frozen_set.case_content_hash` 的 10 个共享字段 | 源 YAML 头 `# content_hash:` / 冻结件顶层 |
| `full_hash` | 上述 10 字段 + `expect` / `metrics` / `assets` / `eval_tenant` | 同上 |

`content_hash` **盖不住口径期望**：改 `expect` 或 `metrics` 时它不变，`full_hash` 必变。
`olist_profile` 两个都查；源模式下 `gold_result_hash` 记 `n/a (source mode)`。

## 5. 判据与计数（不要把三种绿混成一种）

- `gold_executable` / `caliber_match`：分母 **55**（execute 题）；交互题无 gold。
- `interaction_valid`：5/5，形状判据（`gold_sql is None` 且 `difficulty_struct is None`）。
- `cases_valid`：60/60（55 + 5）。
- `scored_total`：`build_grid` 现算 = **55**；交互题因 `difficulty_struct=None` 不进分母。
- **交互正确**（运行时）：`terminal_event == expected_behavior and infra_error is None`；
  **不读 `passed`**（交互题 `verdict` 恒 None，用 `passed` 会永远 0/5）。
- 仪器正/负控不是模型 EX：正控 gold-vs-gold = 55/55；负控同列名同行数扰动 = 0/55。

## 6. 已知偏差（与本目录读数同框）

1. **无 `ordered` / `percent_ok`** —— `equivalence.compare_tables` 没有这两个参数；
   排序只在两侧 SQL 都含 ORDER BY 时按序比，容差固定 `REL_TOL=1e-6`。
2. **方言缺口** —— `ast_gate` 硬编码 postgres、沙箱是 SQLite ⇒ 预期出现
   `sandbox_dialect_gap`；单列，不归因模型，不改闸门/prompt。
3. **数据止点 2018-08** —— 2018-09 只有 1 单、2018-10 为 0；月度题截到 8 月底，不制造空月。
4. **`T_B = 0` 平凡成立** —— 沙箱只装 `T_A` 行；查空只证明 TEMP VIEW 过滤生效。
5. **`full_hash` 是 Olist 自定** —— 共享 `case_content_hash` 的 keep-list 未改；
   两者并列落盘、并列校验，不混用。
6. **55/55 vs 60/60** —— 派单的 `gold_executable=60/60` 在 5 条交互题无 gold 时不可达；
   本目录按 `55/55（execute）+ 5/5（interaction）+ 60/60（cases_valid）` 拆分报告。
7. **冻结时机** —— 2026-10-28 冒烟通过后生成 `dataset_v1_frozen.json`（`content_hash`
   `f5e78268…`、`full_hash` `b4491abb…`）；3 批 live 都读冻结件，改集走 v2。
8. **Harness 透传** —— W1 的 `run_batch` 不传 bundle/db（`--db` 只影响判分沙箱）；
   W2 加了 `bundle_path` 并同时传 `db_path`，默认路径行为不变。
9. **9 个指标而非 8 个** —— 多出 `order_cnt_all`（全状态口径），与 `order_cnt` 不许合并。
10. **`meta.dialect: "sqlite"`** —— 只声明 W1/W2 评测基底；W3 进 PG 前必须显式裁定。
11. **`--live` 的账本门已闭合** —— 账本读/写已提成 `runner.load_budget_ledger` /
    `save_budget_ledger` / `ledger_run_entry`，两个入口共用同一份 schema；
    `test_olist_budget_ledger.py` 守键集与调用点。live 必须带 `--batch-id`、
    `--max-cost-cny`、`--max-calls`，且 cassette/out/ledger 只能落在 `eval/olist/`。
12. **`delivery_late_rate` 的 bundle expression 未乘 100** —— gold 与数据集按百分比
    （`* 100.0`、`ROUND 4`）判分，而 bundle 的 `expression` 是裸比率；模型照 expression
    生成会被判错（SQLite 整数除法还会归零）。这是 **bundle 与 gold 的口径不一致**，
    不归因模型；W2 不动 bundle，W3 修 expression 并递增 `meta.version`。
13. **live 三批读数（2026-10-28，冻结件）** —— EX = 23/54、23/55、22/55（r1 有 1 条
    `GraphRecursionError` 记 `unscored`）⇒ `41.47% ± 1.33%`（n=3，样本标准差）；
    方言缺口 12/55（3 批同）；交互 refuse 2/2、clarify 2/3、1/3、1/3。
    花费：冒烟 ¥0.090114 + 三批 ¥1.449328 = **¥1.539442**；另两次预热探针（bundle 配错，
    不入 EX）¥0.048696 ⇒ 本窗累计 **¥1.588138**，逐笔在 `budget_*.json`。
    预热探针的 `results_v1_warmup*.json` 与匣带已删（配置错误，不构成证据）。

## 7. 沙箱 sha256 与解释器

`sandbox_db_sha256` 是**解释器相关**的：3.13.13 与 3.13.14 构建出的 SQLite 文件
sha256 不同（W1 实测 `a67c5f7d…` vs `17c14cee…`），**不是库损坏**。
profile 失败信息会带解释器版本与两份哈希；请用 **3.13.14** 复跑。
