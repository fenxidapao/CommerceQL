# W1 gold-only 对账报告（Olist 真实轨）

> 归属：W1 实施窗｜问题号 `U-143`（`docs/07 §4.8`）
> 起点 rev：`af35fbd`｜生成时点：2026-10-27T06:20:14Z（沙箱侧 06:20:37Z）
> 模式：**gold-only**。零 PG、零 LLM、零出站、不写 EX、不产冻结件。

---

## 1. Gate 读数

| 项 | 读数 | 判读 |
|---|---|---|
| `gold_executable` | **10 / 10** | 10 条 gold SQL 全部在沙箱上执行成功 |
| `caliber_match` | **10 / 10** | 7 条机器判据逐题全过（见 §5） |
| `T_A` 各表行数 | 5 表均 > 0（见 §2） | 经 `open_sandbox_connection` 验证 |
| `T_B` 各表行数 | 5 表均 = 0 | ⚠️ **平凡成立**，见 §7-4 |
| `validate_bundle.py` | **PASS=33 FAIL=0 SKIP=1 WARN=0** | SKIP = jieba 分词（归 W2B） |
| `load_bundle` | 通过，`warnings=1` | 同一条 jieba/tokenizer PENDING |
| 默认 166 路径 | 常量未变；N-13 验真 **skip** | 本机无 `data/ecom_sandbox.db`，见 §7-3 |

> ⚠️ 本报告**不写** "34/34 PASS"。校验器只保证 FAIL=0，SKIP/WARN 不参与退出码。
> 参照基线：现有默认包实测 `PASS=31 FAIL=0 SKIP=1 WARN=2`。

复算命令（仓库根）：

```bash
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"
"$V" deploy/demo/build_olist_sandbox.py \
  --sqlite ../Text2SQL/real_data/olist/olist.sqlite \
  --out data/olist/olist_sandbox.db
"$V" semantic/validate_bundle.py semantic/bundle_olist_2018.yaml
"$V" eval/olist/run_olist.py --gold-only \
  --dataset eval/olist/dataset_w1_gold10.yaml \
  --db data/olist/olist_sandbox.db
```

---

## 2. 沙箱读数

| 项 | 值 |
|---|---|
| 产物 | `data/olist/olist_sandbox.db`（gitignore） |
| 体积 | 92,684,288 bytes（88.4 MiB） |
| sha256 | `17c14cee7268e78225afa0406d705cf9a018c984d86697a038682d001fac31b0` |
| 源库 | `../Text2SQL/real_data/olist/olist.sqlite`，150,478,848 bytes |
| 源库 sha256 | `bc5ca78bb28743f332b663fc0b50e30ec8dd89e2deffa35cf460cc272039d1d4` |

| 表 | 行数 |
|---|---|
| `v_o_orders` | 99,441 |
| `v_o_order_items` | 112,650 |
| `v_o_products` | 32,951 |
| `v_o_payments` | 103,886 |
| `v_o_reviews` | 99,224 |
| **合计** | **448,152** |

**可复现的边界（实测，别读过头）**：同一解释器内连续两次构建 sha256 **完全一致**
（`17c14cee…`，sqlite3 库 **3.53.1**）。**跨解释器不一致**：同一条命令在 CPython 3.13.13
（另一套 sqlite3 库）下产出 `a67c5f7d…`，字节数同为 92,684,288 但文件字节不同。
⇒ 判定沙箱身份时，要么钉解释器版本，要么以**内容**为准 —— 10 条 gold 的 `result_hash`
在两个解释器下**逐条相同**（见 §4），数据本身没有分叉。

---

## 3. 口径声明（写死在 bundle，不在报告里另立一套）

**GMV**
- 时间基准 = `order_purchase_timestamp`（Olist 无支付时间戳；`order_approved_at` **实测 160 条空值**，不采用）
- 金额 = `SUM(order_payments.payment_value)`，**含运费**
- 剔除 `order_status IN ('canceled','unavailable')`
- **Olist 无退款金额字段** ⇒ 不建退款率指标；`blacklist_terms` 把「退款率」登记为 `refuse`

**订单量三者的边界**（不许合并）

| 指标 | 是否排除 canceled/unavailable | 用途 |
|---|---|---|
| `order_cnt` | 是 | 有效单量，与 GMV 同口径 |
| `order_cnt_all` | **否** | 状态分布类问题（g07）专用 |
| `aov` | 是（分子分母同过滤） | 两端表达式写全，不引用指标名 |

**配送延迟率**
- 分子分母：`order_status='delivered'` 且 `order_delivered_customer_date`、`order_estimated_delivery_date` **均非空**
- **7,826 / 96,470 = 8.112%**

---

## 4. 10 条 gold 的逐条读数

| id | 问题 | 行 × 列 | 前 3 行 | result_hash（前 16） |
|---|---|---|---|---|
| g01 | 2018 年 GMV | 1 × 1 | `8,594,831.98` | `48dbc2303ab1512d` |
| g02 | 2017 年每月订单量 | 12 × 2 | 2017-01=787；2017-02=1,718；2017-03=2,617 | `e924a981438e5588` |
| g03 | 各州 GMV 前十 | 10 × 2 | SP=5,878,935.99；RJ=2,115,994.28；MG=1,843,460.37 | `df2d5b5e77815dee` |
| g04 | 各品类商品销售额（不含运费）前十 | 10 × 2 | health_beauty=1,255,695.13；watches_gifts=1,198,185.21；bed_bath_table=1,035,964.06 | `89c836b51a7eb37d` |
| g05 | 2018 年客单价 | 1 × 1 | `160.56` | `59d585f571e9c397` |
| g06 | 每月运费总额 | 24 × 2 | 2016-09=71.83；2016-10=6,847.22；2016-12=8.72 | `0c7d119a43f4c692` |
| g07 | 各订单状态订单数 | 8 × 2 | delivered=96,478；shipped=1,107；canceled=625 | `5b19d12ce3c3ec9d` |
| g08 | 各州平均评分 | 27 × 2 | AP=4.1940；AM=4.1837；PR=4.1800 | `72cdc4ea3859b7ae` |
| g09 | 各州配送延迟率 | 27 × 2 | AL=23.9295%；MA=19.6653%；PI=15.9664% | `05ea8db9a7e98aad` |
| g10 | 2018 年每月商品件数 | 9 × 2 | 2018-01=8,173；2018-02=7,597；2018-03=8,195 | `16f1604138b5e2ae` |

完整哈希、SQL、样本行见 `eval/olist/gold10_results.json`。

**g07 是设计探针**：它按 `order_status` 分组且**不加任何状态过滤**。如果哪天有人把
「排除取消单」写进 `default_predicates`，闸门一 R06 会把谓词注入这条查询，g07 的
`canceled` / `unavailable` 两行会同时消失 —— 届时读数会变成 6 行而不是 8 行。

---

## 5. 机器判据（7 条）与正控

判据实现见 `eval/olist/run_olist.py::check_case`：

| 代号 | 判据 |
|---|---|
| C1 | 资产白名单：SQL 中的表 ⊆ 本题声明资产 ⊆ bundle `physical_asset` |
| C2 | 列白名单：所有列（经别名解析）⊆ 对应资产的 columns；输出别名不算列 |
| C3 | 时间基准：`expect.time_column == metrics[].time_basis`；若 `time_filtered` 则该列必须出现在 WHERE |
| C4 | 金额列：`expect.amount_column` 必须真的被聚合（SUM/AVG/MIN/MAX 的参数里），且出现在指标表达式里 |
| C5 | 状态谓词一致性：gold 的 `order_status` 谓词（exclude/require/none + 取值集）必须与指标表达式**逐值相等** |
| C6 | 租户列：gold SQL 不得出现 `tenant_id` |
| C7 | 指标存在且 `status: active` |

**正控（本窗自订）**：`backend/tests/unit/test_olist_caliber_checks.py` 对每条判据注入一次
反例，必须变红。首轮实测抓出一处真 bug —— C7 的注入让 `check_case` 抛
`AttributeError`（`primary is None` 时 C4 解引用了它）而不是判红，已修。

| 注入 | 期望变红 | 实测 |
|---|---|---|
| g07 加 `NOT IN ('canceled','unavailable')` | C5 | ✅ 红 |
| g01 时间列换 `order_approved_at` | C3 | ✅ 红 |
| g01 金额换 `payment_installments` | C4 | ✅ 红 |
| g01 显式引用 `tenant_id` | C6 | ✅ 红 |
| g01 换未声明表 | C1 | ✅ 红（同时带红 C2） |
| g01 换未声明列 | C2 | ✅ 红（同时带红 C4） |
| g01 声明不存在的指标 | C7 | ✅ 红（修复后） |

---

## 6. 数据质量发现（W2 出题前必须知道）

**① 数据止于 2018-08，不是 2018-10-17。**

源库 `MAX(order_purchase_timestamp) = 2018-10-17`，但那是**假尾巴**：

| 月份 | 有效单 |
|---|---|
| 2018-08 | 6,421 |
| 2018-09 | **1**（当月另有 15 条 canceled） |
| 2018-10 | **0**（当月 4 条全是 canceled） |

⇒ 任何"2018 年全年 12 个月"的题都会落空（g10 只有 9 个月，其中 9 月是 1 行）。
W2 出题时要么把范围截到 2018-08，要么明确接受空月。

**② 两条独立金额路径吻合到 0.023%。**

| 路径 | 有效单合计 |
|---|---|
| `SUM(order_payments.payment_value)` | 15,739,137.01 |
| `SUM(order_items.price + freight_value)` | 15,735,527.03 |
| 差 | 3,609.98（**0.023%**） |

这是"GMV 取支付表"的旁证：支付表与明细表互相独立，差额仅来自两者覆盖的订单集合不同。
**注意**：价差不是零，因此两个指标不可互相替代。

**③ 多支付行订单 2,961 单** ⇒ 任何按订单聚合的地方都必须 `COUNT(DISTINCT order_id)`。

**④ 品类空值**：`product_category` 有未翻译商品，g04 的 Top-10 里没有落进空值组，但全量里存在。

---

## 7. 已知偏差（与本报告的读数同框）

1. **计划 §3.2 的题型字段 `ordered` / `percent_ok` 在代码中不存在** —— `compare_tables` 无此参数
   （排序靠 SQL 文本推断、容差是常量 `REL_TOL=1e-6`）。W1 不受影响（gold-only 不跑等价判定），
   **W2 写 60 题前必须先对齐**。
2. **`ast_gate` 硬编码 `dialect="postgres"`**（`backend/app/guard/ast_gate.py:305`）—— 沙箱是 SQLite。
   W1 不过闸门，但 W2 的 `sandbox_dialect_gap` 会从这里产生。
3. **默认 166 路径本次只有"常量未变"，没有"验真 all_ok"** —— `data/ecom_sandbox.db` 本机不存在，
   该断言 `skip(reason="sandbox_db_absent")`。不得写成"已回归通过"。
4. **`T_B = 0` 属平凡成立** —— 沙箱只装 `T_A` 行。查空只证明 TEMP VIEW 的过滤谓词生效，
   **不**证明真实跨租户隔离。
5. **指标 9 个而非 §3.1 的 8 个** —— 多出 `order_cnt_all`，理由见 §3；相对预算是显式偏离。
6. **`meta.dialect: "sqlite"`** 只声明 W1/W2 的评测基底。W3 开工第一件事必须裁定：
   改成 `postgresql` 并递增 `meta.version`（会作废绑在该版本上的读数），还是分叉第二份包。
7. **计划里写的 `v_o_sellers` 实际不存在** —— 沙箱第 5 张表是 `v_o_products`
   （32,951 行），不是卖家表。W1 的包按实际数据建了 product 资产；理由成立
   （品类维度需要它），`eval/olist/README.md` 已声明。**本报告既有读数不改。**

---

## 8. 环境与全量检查读数（如实，含未转绿的部分）

**环境**：本机 Anaconda 是 Python 3.11.5 + pydantic **1.10.19**，`app.semantics` 直接
`ImportError: cannot import name 'model_validator'`；`backend/pyproject.toml` 的 ADR-19 也明写
"用托管 Python 3.13 独立 venv，**不用** Anaconda 3.11.5"。

用哪个 3.13 venv：**`CommerceQL-archive/local/.venv`**（CPython **3.13.14**，
pydantic 2.13.5 / sqlglot 30.18.0 / ruff 0.16.7 / mypy 2.3.1 / pytest 9.1.1）。
它原本就建在 `CommerceQL/.venv`（`pyvenv.cfg` 的 `command` 可证），2026-10-24 仓库精简时
被整体移入 archive ⇒ **沿用原位，不再往仓库里放第二份**。调用一律 `"<archive>/local/.venv/Scripts/python.exe" -m <tool>`。**不要用 `.exe` shim**：
venv 被移动后，实测 `pytest.exe` / `mypy.exe` / `lint-imports.exe` 三个都变成"静默 exit 1、
零输出"，只有 `ruff.exe`（原生二进制，无 shebang）仍可用。`lint-imports` 没有 `-m` 入口，
用 `python -c "from importlinter.cli import lint_imports_command; lint_imports_command()"`。

| 检查 | 读数 | 是否 W1 引入 |
|---|---|---|
| W1 的 8 个 Python 文件 `ruff` | **All checks passed** | — |
| W1 的 4 个测试文件 + 依赖白名单 | **50 passed, 1 skipped** | — |
| `pytest -q --ignore=tests/integration` | **2751 passed / 21 failed / 1 skipped** | ❌ **21 条全部既有** |
| `ruff check .` | **215 errors**（仓库既有） | ❌ 既有（新版 ruff 新增 UP031/UP009/UP020 等规则；`app/` 10 条、`tests/` 26 条在我未改的文件里） |
| `mypy app` | **8 errors / 5 files**（`ast_gate.py`、`planner/engine.py`、`normalize.py`、`gate1_ast.py`、`bind.py`） | ❌ 既有，均为我未触碰的文件 |
| `lint-imports` | **4 kept, 0 broken**，输出含 `Contracts:` 行 | ✅ 绿 |

**21 条既有失败的根因（逐类实测）**

| 类 | 条数 | 根因 |
|---|---|---|
| 合成沙箱 / 产物缺失 | 18 | `sqlite3.OperationalError: unable to open database file` —— `data/ecom_sandbox.db` 本机不存在（`*.db` 被 gitignore；该库现存于 `CommerceQL-archive/local/ecom_sandbox.db`，440,729,600 B） |
| W4 探针文件缺失 | 2 | `backend/reports/w4/probe_prod_checkpoint_terminal.sql` 不存在 |
| eval 批次产物缺失 | 1 | `GET /admin/eval/runs/results_v1` 返回 404 `RUN_NOT_FOUND` |

**对照组（同一份代码，只换 venv）**：在我临时建的 venv 里（sqlglot **30.25.0**）是
**2749 passed / 23 failed**，多出的 2 条是 `test_guard_gate1::test_r04_limit_all_rewritten`
与 `test_redteam_guard::RT-R04-003`（`R04 LIMIT ALL` 由 rewrite 变成 reject）；
换到 archive venv（sqlglot **30.18.0**）后这两条转绿。
⇒ **`backend/pyproject.toml` 的 `sqlglot>=25.0` 未钉上限，装到最新会打破闸门一 R04 的改写行为。**
本窗未改该依赖声明（属 W0 的依赖账），但这是一个应当登记的**实现面风险**，不是 W1 引入的缺陷。

**调用方式注意（本机实测，非判据改动）**：`backend/tests/eval/{test_tau_samples,test_tau_split_and_layers}.py`
在 `cd backend && pytest` 下会因 `ModuleNotFoundError: No module named 'eval'` 收集失败；
把仓库根放进 `PYTHONPATH` 后 30 项全过。该问题与 W1 无关（`backend/tests/conftest.py` 不做 sys.path 处理），
本报告的全量读数即在该调用方式下取得。

