# eval/olist —— Olist 真实数据轨的评测侧

> 归属窗口：W1 实施窗｜问题号 `U-143`（`docs/07 §4.8`）
> 零 PG、零 LLM、零出站。本目录只跑 **SQLite 沙箱**上的 gold SQL。

## 1. 目录

| 文件 | 作用 |
|---|---|
| `build_dataset.py` | **P0 写保护**：`guard_output_path()` + `write_json()`。Olist 侧唯一落盘入口 |
| `run_olist.py` | gold-only 执行 + 7 条口径判据（`--gold-only`） |
| `dataset_w1_gold10.yaml` | 10 条 gold 题（不是冻结件） |
| `gold10_results.json` | 机器读数（每题的哈希 / 行数 / 判据 / 样本行） |
| `gold10_report.md` | 人读报告：口径声明、实测读数、数据质量发现、已知偏差 |
| `sandbox_manifest.json` | 沙箱行数 / 体积 / sha256（`deploy/demo/build_olist_sandbox.py` 生成） |

**本目录没有的东西**（有意）：`dataset_v1_frozen.json`（W2 首轮后才有）、`olist_profile.py`（W2 的 N-13 验真）、`results_v1.json`（W2 的 EX 批）。

## 2. 跑法（仓库根）

⚠️ **解释器用 archive 里那个 3.13 venv**（仓库根不放 `.venv`，2026-10-24 已移到仓库外）：

```bash
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"
"$V" --version   # 3.13.14
```

本机 Anaconda 的 Python 3.11 是 pydantic **1.10**，`app.semantics.load_bundle` 会直接
`ImportError: cannot import name 'model_validator'`。仓库 ADR-19 已明确要求 3.13 独立 venv。

```bash
# 解释器（每条命令都用它；不要用 .exe shim，移动过的 venv 里那三个 shim 已坏）
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"

# 0. 一次性：建沙箱（约 88 MiB，gitignore）
"$V" deploy/demo/build_olist_sandbox.py \
  --sqlite ../Text2SQL/real_data/olist/olist.sqlite \
  --out data/olist/olist_sandbox.db

# 1. 语义包结构校验（判据是 FAIL=0，不是"34/34 PASS"）
"$V" semantic/validate_bundle.py semantic/bundle_olist_2018.yaml

# 2. gold-only + 口径对账
"$V" eval/olist/run_olist.py --gold-only \
  --dataset eval/olist/dataset_w1_gold10.yaml \
  --db data/olist/olist_sandbox.db

# 3. 护栏（三条 Olist 测试 + 默认路径回归）
cd backend
"$V" -m pytest -q tests/unit/test_olist_write_guard.py \
                  tests/unit/test_olist_bundle_contract.py \
                  tests/unit/test_olist_caliber_checks.py \
                  tests/contract/test_eval_default_paths_unchanged.py

# 4. 导入方向（export 是唯一可靠形态：lint-imports.exe 已坏、importlinter 无 -m 入口）
PYTHONUTF8=1 "$V" -c "from importlinter.cli import lint_imports_command; lint_imports_command()"
```

## 3. 三条边界（写进代码，不只是文档）

1. **不调用 `verify_frozen_inputs()`**。它拿 `dataset["sandbox_db_sha256"]` 比
   `data/ecom_sandbox.db`，Olist 永远过不了；Olist 的验真是 W2 的 `olist_profile.py`。
2. **不改 `eval/runner.py` / `eval/_bootstrap.py`**。默认 166 路径的常量与判据由
   `backend/tests/contract/test_eval_default_paths_unchanged.py` 守着。
3. **不扩展 `build_frozen_set.TENANT_SCOPED`**。那份常量是写死的合成 6 表，
   对 `v_o_*` 是空操作 —— Olist 的租户隔离靠 `open_sandbox_connection` 建的 TEMP VIEW。

## 4. 租户隔离怎么生效

`open_sandbox_connection(db, tenant_id='T_A', tenant_scoped_physicals=...)` 会对每个
`tenant_scoped: true` 的资产执行：

```sql
CREATE TEMP VIEW v_o_orders AS SELECT * FROM main.v_o_orders WHERE tenant_id = 'T_A';
```

⇒ 沙箱主表里必须**真实存在**同名物理表且带 `tenant_id` 列。`tenant_scoped_physicals`
从 bundle 导出（与 `eval/harness.py:742-746` 同一条推导），不硬编码第二份清单。

## 5. 口径在哪

**只在 `semantic/bundle_olist_2018.yaml`**，本目录不另立一套。
最要紧的三条：

- GMV 时间基准 = `order_purchase_timestamp`（Olist 无支付时间戳，`order_approved_at` 有 160 条空值）
- GMV 金额 = `SUM(payment.payment_value)`，含运费；剔除 canceled/unavailable
- `default_predicates` **刻意留空** —— 域级谓词会被闸门一注入该域每条查询

## 6. 已知偏差

见 `gold10_report.md` §7。其中两条最容易被后来人踩：

- **`T_B = 0` 平凡成立**：沙箱只装 `T_A` 行，查空只证明视图过滤生效，不证明真实隔离。
- **`meta.dialect: "sqlite"` 只覆盖 W1/W2**：W3 进 PG 前必须显式裁定改 dialect 还是分叉第二份包。
