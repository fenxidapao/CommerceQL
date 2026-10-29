# CommerceQL —— 受控 Text2SQL 电商数据分析 Agent

> 作品集主件。目标：**面试官 30 秒能看懂、3 分钟能看完、10 个追问能答**。
> 每个数字都能用一条命令追到源件；未跑过的写 `UNVERIFIED`，不包装成通过。

---

## 1. 一句话价值

**中文**：把一句中文业务问题变成一条**受控** SQL —— 三道安全闸门（AST / 政策 / 成本）、
按租户的行级隔离（RLS）、出站内容白名单、两段式审计（fail-closed）；在 Olist 真实数据
60 题冻结集上，3 个独立批次实测 `EX_official = 41.47% ± 1.33%`（n=3，样本标准差）。

**English**：A controlled Text2SQL agent for e-commerce analytics. LLM-generated SQL is
treated as **untrusted input**: three gates (AST / policy / cost), tenant-level RLS,
outbound content whitelist, and fail-closed two-phase audit. On a 60-case frozen Olist
set, `EX_official = 41.47% ± 1.33%` over 3 independent batches (n=3, sample std).

> 口径先说清：41.47% **未达**任务书的 85% 目标；`6/8 ≠ 门禁通过`（G-6 延迟、G-8 澄清率
> 仍 `UNVERIFIED`）。本项目只报实测，不报目标。

---

## 2. 架构图

```mermaid
flowchart TD
  START([用户问题]) --> TC[trusted_context]
  TC --> NO[normalize] --> IN[intent] --> LI[link] --> PL[plan] --> BI[bind] --> GS[gen_sql]
  GS --> G1{gate1_ast}
  G1 -- pass --> G2{gate2_policy}
  G2 -- pass --> G3{gate3_cost}
  G3 -- pass --> EX[execute] --> MK[mask] --> AP[audit_pre] --> PR[present] --> AS[audit_supp] --> END([complete])
  G1 -- reject --> RF[refuse_out]
  G2 -- reject --> RF
  G3 -- reject --> RF
  G1 -- repair --> RP[repair] --> G1
  IN -- need clarify --> CL[clarify_out]
  TC -- error --> ER[error_out]
```

**19 个图节点 = 16 个主节点 + 3 个终态出口**（节点名唯一真相：
`backend/app/graph/nodes/__init__.py`；`END` 是图终点，不计入 19）。RLS 不在图节点里，
它是数据层的最后一道：`v_o_*` 认证视图 + `FORCE ROW LEVEL SECURITY` + 租户 GUC。

**为什么这样分层（三行）**

1. **依赖方向由机器保证**：`backend/.importlinter` 的 R-DEP-1..4 要求只能依赖严格更低层；
   L2 确定性层（`binding/guard/exec/mask/cache`）**结构上禁止** import `app.llm`——
   "SQL 不可信"不是靠纪律，而是靠 import 图。
2. **三闸门在 `gen_sql` 之后、`execute` 之前**：`repair` 只能回到 `gate1_ast`，不能绕过
   政策/成本；三个终态出口（clarify / refuse / error）是**独立节点**，不是一个节点的三种行为。
3. **审计两段式**：`audit_pre` 在 `present` 之前、`audit_supp` 在 `present` 之后；
   **审计写失败 = 不下发数据**（fail-closed），不是"记不下来就算了"。

---

## 3. 安全设计

| 机制 | 做什么 | 源件 / 证据 |
|---|---|---|
| **AST 闸门** | `gen_sql` 产物先过 AST 规则（R01–R20；postgres 方言），拒 SELECT */DDL/危险函数/未授权表等 | `backend/app/guard/ast_gate.py`、`backend/app/guard/rules.py` |
| **政策闸门** | 逐字执行语义包 `policies[].applies_to_roles` + 列级 allowlist；角色感知，不认黑名单 | `backend/app/guard/policy_gate.py`、`backend/app/binding/filters.py:310` |
| **成本闸门** | `EXPLAIN` 预估行数 / 成本超阈即拒；超时与行数上限另有执行层兜底 | `backend/app/guard/cost_gate.py`、`backend/app/exec/executor.py` |
| **租户 RLS** | 业务 SQL 只经 `v_o_*` 认证视图；`FORCE RLS` 对属主也生效；策略由 `materialize` 从语义包派生 | `backend/app/repo/migrations/versions/0003_business_views.py`、`deploy/demo/materialize_olist.py`、`backend/reports/w3_demo/materialize_olist_2026-10-28.json` |
| **出站内容白名单（N-12）** | 身份字段（`tenant_id` / `user_id`）与 PII **禁止出站到 LLM**；只有归一化问题允许进 LLM；错误 `detail` 不含明细 | `backend/app/auth/context.py:19-20`、`backend/app/binding/context.py:45-51`、`backend/app/api/errors.py:221` |
| **两段式审计（fail-closed）** | `audit_log` append-only；代码层只暴露 `insert`；写失败即不下发数据 | `backend/app/obs/audit.py`（`AuditWriter`）、`backend/app/graph/nodes/audit_pre.py`、`audit_supp.py`、`backend/tests/integration/test_audit_append_only.py`（本窗未跑 integration，不报绿） |
| **PII 脱敏** | 按语义包列标签（`pii_phone` / `pii_email` / `pii_idcard` / `pii_address` / `pii_name`）派发掩码；错误消息不回显明文 | `backend/app/mask/engine.py`、`backend/app/mask/rules.py` |
| **结果级校验（U-149）** | 空结果 / 全 NULL / 单行 KPI 异常 / 守恒式；守恒式只在结果自带合计行且未截断时校验，**无基准就跳过**而不是猜 | `backend/app/present/checks.py` |
| **官方门禁快照（仅引用，非当期）** | 官方 `88f3500`：**PASS 1/8**；其中 G-3 = PASS（危险 SQL 放行=0，覆盖 50/50），成本闸门 `NOT_CHECKED` | `backend/reports/w6/eval_metrics.json`、`README.md §6` |

**RLS 金丝雀读数（W3，2026-10-28 实测）**

| 项 | 读数 |
|---|---|
| 五表总行数 | `99,441 / 112,650 / 32,951 / 103,886 / 99,224 = 448,152` |
| `materialize` | `ok=true`、`consistent=true`、`checked_assets=5`、`mismatches=[]` |
| `app_ro` 无 GUC | 五表全 `0`（失败关闭） |
| `app_ro` GUC=`T_A` | 五表原值（金丝雀在库时也不变） |
| `app_ro` GUC=`T_B` | 五表各 `1`（金丝雀 `canary_order_1` / `canary_product_1` / `canary_review_1`） |
| 删金丝雀后 | `T_A` 回原值；`T_B` 全 `0` |

> ⚠️ `T_B=0` 本身**平凡成立**（沙箱只装 `T_A` 行）；上面的"`T_B` 每表 1"才是真隔离证据。

---

## 4. 评测表（Olist 真实数据，60 题冻结集）

| 项 | 读数 | 源件 |
|---|---|---|
| **EX_official** | **0.4147 ± 0.0133**（3 批均值 ± 样本标准差，n=3） | `eval/olist/report.md:15`、`eval/olist/report.json` |
| 三批 | r1 `23/54`（0.4259）、r2 `23/55`（0.4182）、r3 `22/55`（0.4000） | `eval/olist/report.md:21-25` |
| 分母构成（r1） | `scored=54 \| struct_null_skipped=5 \| execute=55 \| with_sql=55 \| with_result=36 \| equivalent=23` | `eval/olist/report.md:9` |
| 为什么 r1 分母是 54 | 1 条 `GraphRecursionError`（o19）记 `unscored`；r2/r3 分母 55 | `eval/olist/report.md:75` |
| 交互正确（不计入 EX） | refuse `2/2`；clarify `2/3`、`1/3`、`1/3`（三批） | `eval/olist/report.md:41-45` |
| 沙箱方言缺口 | `12/55`（三批同，单列、不归因模型） | `eval/olist/report.md:69` |
| `EX_exec`（非官方，仅 coverage） | `23/55` | `eval/olist/report.md:12` |
| 题集构成 | `60 = 55 execute + 5 interaction（3 clarify + 2 refuse）`；`gold_executable 55/55`、`caliber_match 55/55`、`interaction_valid 5/5`、`cases_valid 60/60` | `eval/olist/README.md:135-137`、`eval/olist/report.md:49-50` |
| 仪器正/负控（不是模型 EX） | 正控 `55/55`、负控 `0/55` | `eval/olist/report.md:61-64` |
| 冻结件 | `content_hash=sha256:f5e78268…`、`full_hash=sha256:b4491abb…`、`sandbox_db_sha256=17c14cee…` | `eval/olist/report.md:51-53` |

**实验协议（写进 `THESIS_MAPPING.md` 的同一份口径）**

- 60 题冻结集；**3 个独立批次**（各自进程 + 各自 `--batch-id`：`w2_r1..r3`）；批次日期 2026-10-28。
- 温度：所有 LLM 路由 `temperature=0.0`（`backend/app/llm/router.py:202-260`）。
- DSN：`postgresql+psycopg://postgres:postgres@127.0.0.1:5432/ecom`（`deploy/demo/README.md:60`；评测沙箱走 SQLite，见 §7）。
- **读数身份**：三批运行时刻 `build.git_rev=aeb53eb`、`build.git_dirty=true`（三批同，W2 窗未提交的中间态）；
  最终入库代码 `b780125`。**可复算的是命令、冻结件与三批结果件，不是一棵干净的 git 树**——
  不得写成"同一 rev 的干净复现"。
- 改题 / 改 bundle 必须升 v2；不因调试改冻结集。
- 评测花费（历史，非本窗）：冒烟 ¥0.090114 + 三批 ¥1.449328 = **¥1.539442**；
  另两次预热探针 ¥0.048696 ⇒ 本轨累计 **¥1.588138**（`eval/olist/README.md:169-174`、`budget_*.json`）。

> **口径**：`EX_official` 只统计有有效难度标签的 scored 题；`scored_total` 现算，不抄常量。
> `EX_exec` 只作 coverage 附注，不进主数字。`sandbox_dialect_gap` 单列，不归因模型。

---

## 5. 演示（生产栈真跑，截图版）

5 张截图来自 W3 的浏览器验收（`backend/reports/w3_demo/browser_acceptance.json`，
2026-10-29 09:19–09:26 +0800），经 nginx → api 的生产栈；**不是静态稿，也不是动图**。

| # | 问题 | 输出 | 读数 | 截图 |
|---|---|---|---|---|
| 1 | 2018 年各州 GMV 前十 | `bar` | SP `¥3,374,237.33`，10 项；9.47s；¥0.005732 | `demo_1_bar.png` |
| 2 | 各商品类目的商品件数前五 | `bar` | `bed_bath_table` `11,097` 件，5 项；7.61s；¥0.006674 | `demo_2_bar.png` |
| 3 | 各订单状态分别有多少订单？ | `bar` | `delivered` `96,478` 单，8 类；6.67s；¥0.005366 | `demo_3_bar.png` |
| 4 | 删掉订单表 | `refuse` | 原因码 `pii_blocked`；0.85s；不产生 LLM 花费 | `demo_4_refuse.png` |
| 5 | 成交订单有多少？ | `kpi` | `98,207` 单；7.09s；¥0.006068 | `demo_5_kpi.png` |

- 单次跑完 `total_cost_cny=0.02384`（`backend/reports/w3_demo/demo_5.json`）；
  浏览器重跑另计；`app.cost_ledger` 10-28+10-29 合计 **¥0.107807**（上限 ¥0.3）。
- 截图路径：`backend/reports/w3_demo/demo_1_bar.png` … `demo_5_kpi.png`。
- **W4 复跑**：见 `backend/reports/w4_acceptance/demo_5.json`（工作树 @ `b780125`；
  若与截图读数有差异，以该文件为准并在此标注）。
- demo 4 的原因码 `pii_blocked` 是"删除类请求"落到 PII 文案面的既存映射（W4 文案面），
  **只登记、不改**；它证明危险请求被拒，不证明脱敏链路。

---

## 6. 快速开始（分两栈，别混）

### 6.1 合成栈（数据在仓库外，必须先生成 + 装载）

```bash
# 0) 解释器（本机；仓库不放 .venv）
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"

# 1) 环境变量（仓库内不放真实密钥）
cp deploy/.env.example deploy/.env
#    按需填 DEEPSEEK_API_KEY；DSN / 端口已按 compose 服务名预置

# 2) 起基础设施 + API
docker compose -f deploy/docker-compose.yml up -d --build pg redis api

# 3) 迁移（容器不会自动迁移）
cd backend
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/ecom \
  "$V" -m alembic upgrade head
cd ..

# 4) 合成业务数据（约 440MB；仓库只带生成器）
"$V" data/generator/seed_generator.py --out data/ecom_sandbox.db
"$V" deploy/loadtest/load_synth_to_pg.py \
  --sqlite data/ecom_sandbox.db \
  --dsn postgresql://postgres:postgres@127.0.0.1:5432/ecom --force

# 5) 三探针
curl -i http://127.0.0.1:8000/api/v1/healthz/live    # 200
curl -i http://127.0.0.1:8000/api/v1/healthz/ready   # 200；bundle_version=2026.10.16.2
curl -i http://127.0.0.1:8000/api/v1/healthz         # 503 + degraded_dependencies（设计）
```

> ⚠️ "干净 checkout"**不等于**能直接出数：业务表要经第 3/4 步迁移+装载；否则分析库为空。
> 本窗的验收在工作树 @ `b780125`（不是 clone）执行，外部前置 = 合成数据 + `DEEPSEEK_API_KEY`。

### 6.2 Olist 真实数据栈（依赖仓库外原始数据）

```bash
# 1) 重建 SQLite 沙箱（源在仓库外：Text2SQL/real_data/olist/olist.sqlite）
"$V" deploy/demo/build_olist_sandbox.py \
  --sqlite ../Text2SQL/real_data/olist/olist.sqlite \
  --out data/olist/olist_sandbox.db

# 2) 迁移到 0007（同上，MIGRATION_DATABASE_URL 指向本机 pg）
cd backend && MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/ecom \
  "$V" -m alembic upgrade head && cd ..

# 3) 装载五表（448,152 行）+ 物化/RLS 一致性
"$V" deploy/demo/load_olist_to_pg.py --exec
docker compose -f deploy/docker-compose.yml exec -T api \
  python - < deploy/demo/materialize_olist.py

# 4) 切 Olist 包 → 签 T_A 令牌 → 5 条 demo（预算闸 ¥0.3）
docker compose -f deploy/docker-compose.yml -f deploy/demo/docker-compose.olist.yml \
  up -d --no-deps api
TOKEN=$(cd backend && "$V" scripts/mint_dev_token.py --tenant-id T_A --user-id u_dev --role analyst | tail -1)
"$V" deploy/demo/run_demo_queries.py --token "$TOKEN" \
  --out backend/reports/w3_demo/demo_5.json

# 5) 验收后切回合成包
docker compose -f deploy/docker-compose.yml up -d --no-deps api
```

> ⚠️ **干净 checkout 不能直接跑 Olist 栈**：原始数据在 `Text2SQL/real_data/olist/olist.sqlite`，
> `*.db` 被 `.gitignore:54` 忽略；必须先有外部数据并执行上面的重建/装载。
> ⚠️ Olist 包的 `meta.dialect: sqlite` 与 PG 链路硬编码 `postgres` 的既存不一致，见 §7 第 1 条。

---

## 7. 已知限制（诚实清单，逐条给证据）

1. **`meta.dialect: sqlite` 与 PG 链路方言硬编码不一致**：`semantic/bundle_olist_2018.yaml`
   声明 `sqlite`，而 planner 的 `DIALECT_NOTE` 与三闸门 `sqlglot.parse(..., dialect="postgres")`
   是硬编码；`meta.dialect` 不参与执行分支。修正走 v2，不在 W3 偷改。
   源：`deploy/demo/README.md §2.6`、`docs/07 v1.7.38`。
2. **R14 月度时序题被闸门一拒**：`to_char(..., 'YYYY-MM')` / `date_trunc('month', ...)` 的格式串
   不在字面量白名单；W2 的 `results_v1_r1.json` 里 12 条"每月"题同族拒（`g02/g06/g10/o02/...`）。
   demo 因此无 `line` 形态，`line` 仅单测覆盖。
   源：`backend/reports/w3_demo/r14_line_gap.json`、`deploy/demo/README.md §2.5`。
3. **`AS order` 保留字致 7/55 `SQL_SYNTAX_ERROR`**：生成缺陷，不是方言缺口；本窗不改 prompt。
   源：`eval/olist/report.md:72`。
4. **`delivery_late_rate` bundle expression 未 ×100**：gold 按百分比、bundle 是裸比率；
   PG 的 `SUM(bigint)/COUNT(bigint)` 还是整数除法（截断成 0/1）。该指标不进 demo。
   源：`eval/olist/README.md §6.12`、`deploy/demo/README.md §2.6`。
5. **gold 带 `ROUND`、模型常不带** ⇒ `REL_TOL=1e-6` 判不等（AOV/评分/延迟率多例）；
   不改判据。源：`eval/olist/report.md:73`。
6. **B0 消融 `UNVERIFIED`（未做）**：按计划 §3.1 "时间紧可砍"；不临时跑。
7. **5 条既有 pytest 失败（证据移出仓库）**：`test_admin_eval_report_contract` ×1、
   `test_shape_guard_faces` ×2、`test_consistency_reporter` ×1、
   `test_gate_inputs_p0_merge_two_state` ×1；本窗复跑清单见
   `backend/reports/w4_acceptance/pytest_summary.txt`。**不写成"已回归通过"**。
8. **读数身份**：三批 live 的 `build.git_rev=aeb53eb`、`build.git_dirty=true`（三批同，
   W2 窗未提交的中间态）；最终入库代码 `b780125`。可复算的是命令、冻结件与三批结果件，
   **不是一棵干净的 git 树**；不得写"同一 rev 的干净复现"。
9. **披露文案 Top-N 噪音（未修）**：`backend/app/present/presenter.py:446-450` 只要 `plan.limit`
   存在就追加"按计划 Top-{limit} 展示"，不看是否真截断 ⇒ demo_3（8 行）挂"Top-100"、
   demo_5（KPI）挂"Top-1"。§3.8 微修需取 `U-150` 并重拍受影响截图；本窗**不做**，只登记。

**口径红线**：41.47% **未达 85%**；G-6（P95 ≤ 8s）与 G-8（澄清率）仍 `UNVERIFIED`；
官方 `PASS 1/8` 与当期复算 `6 PASS / 2 UNVERIFIED` 必须同框，**`6/8 ≠ 门禁通过`**。

---

## 8. 可复算命令（每个数字一条）

先设解释器与工作目录（仓库根）：

```bash
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"
```

| 数字 / 结论 | 命令 | 期望 |
|---|---|---|
| `EX_official=0.4147±0.0133`、三批分母 | `"$V" eval/olist/report_olist.py --dataset eval/olist/dataset_v1_frozen.json --results eval/olist/results_v1_r1.json eval/olist/results_v1_r2.json eval/olist/results_v1_r3.json --profile eval/olist/olist_profile_frozen.json --gold eval/olist/gold60_frozen_results.json --control eval/olist/instrument_control.json --out /tmp/w4_report.md --json-out /tmp/w4_report.json` | 生成报告；与 `eval/olist/report.md` 对撞；`report.json` 的 `ex_official.mean/std/n` = 0.41470258…/0.01330853…/3 |
| 三批 `23/54`、`23/55`、`22/55` | `"$V" -c "import json;r=json.load(open('eval/olist/report.json'));print([(b['scored_passed'],b['scored_total'],b['ex']) for b in r['batches']])"` | `[(23,54,0.4259…),(23,55,0.4182…),(22,55,0.4)]` |
| 交互 `refuse 2/2`、`clarify 2/3·1/3·1/3` | `"$V" -c "import json;r=json.load(open('eval/olist/report.json'));print([(b['refuse_correct'],b['refuse_total'],b['clarify_correct'],b['clarify_total']) for b in r['batches']])"` | `[(2,2,2,3),(2,2,1,3),(2,2,1,3)]` |
| `sandbox_dialect_gap=12` | `"$V" -c "import json;r=json.load(open('eval/olist/report.json'));print([b['sandbox_dialect_gap'] for b in r['batches']])"` | `[12,12,12]` |
| RLS `448,152` 行 / T_B 金丝雀 | `"$V" -c "import json;d=json.load(open('backend/reports/w3_demo/materialize_olist_2026-10-28.json'));print(d.get('consistent'),d.get('checked_assets'))"`；完整读数用 `jq` 或编辑器读同件 | `True 5`；五表 `99441/112650/32951/103886/99224`，T_B 每表 1→0 |
| demo 5 条 / 花费 ¥0.02384 | `"$V" -c "import json;d=json.load(open('backend/reports/w3_demo/demo_5.json'));print(d['total_cost_cny'],[(c['demo_id'],c['terminal']['event'],c['chart_type']) for c in d['cases']])"` | `0.02384` + 4 complete + 1 refuse |
| 花费账本 ¥0.107807 | `docker compose -f deploy/docker-compose.yml exec -T pg psql -U postgres -d ecom -Atc "select to_char(sum(cost_cny),'FM999990.000000') from app.cost_ledger where created_at::date in ('2026-10-28','2026-10-29');"` | `0.107807`（按 DB 时区分日见 §4 注） |
| 离线回归 | `cd backend && PYTHONPATH=.. "$V" -m pytest -q --ignore=tests/integration` | `2908 passed / 5 failed`（或同清单；见 `pytest_summary.txt`） |
| `ruff` / `mypy` | `cd backend && "$V" -m ruff check .`；`"$V" -m mypy app` | `214 errors`；`8 errors in 5 files`（基线，不增） |
| 依赖方向 | `cd backend && PYTHONUTF8=1 "$V" -c "from importlinter.cli import lint_imports_command; lint_imports_command()"` | `4 kept, 0 broken` |
| 两个语义包 | `"$V" semantic/validate_bundle.py semantic/bundle_olist_2018.yaml`；`"$V" semantic/validate_bundle.py semantic/bundle_2026.09.14.1.yaml` | Olist `33/0/1/0`；合成 `31/0/1/2` |
| 官方 1/8 与复算 6/8 | `"$V" -c "import json;o=json.load(open('backend/reports/w6/eval_metrics.json'));print(o.get('summary'))"`；`"$V" -c "import json;r=json.load(open('eval/results_w80_gate_recompute.json'));print(r.get('counts') or r.get('summary'))"` | 官方 `PASS 1/8`；复算 `6 PASS / 2 UNVERIFIED`；两数同框，6/8≠通过 |
| 许可证 | `curl -s https://www.kaggle.com/api/v1/datasets/view/olistbr/brazilian-ecommerce -o /tmp/olist.json && "$V" -c "import json;d=json.load(open('/tmp/olist.json'));print(d['licenseName'],d['ownerName'],d['creatorName'])"` | `CC BY-NC-SA 4.0 Olist Francisco Magioli` |
| 公开仓库 | `git check-ignore -v data/olist/olist_sandbox.db`；`git ls-files \| grep -Ei '\.(db\|sqlite\|sqlite3)$'`；`git ls-files \| grep -Ei '(^\|/)\.env$\|secrets/'`；`"$V" backend/scripts/scan_secrets.py --working-tree` | 忽略行命中；后三条应空 / 0 命中 |
| 图节点数 | `cd backend && PYTHONPATH=.. "$V" -c "from app.graph.nodes import ALL_NODE_NAMES;print(len(ALL_NODE_NAMES))"` | `19` |

> 说明：`report_olist.py` 的输出写到 `/tmp`，**不覆盖** `eval/olist/report.md`；
> 若脚本的落盘守卫限制输出位置，改到 `eval/olist/` 下的临时文件名、对撞后删除。
> 所有原始读数与命令回执见 `backend/reports/w4_acceptance/`。

---

## 9. 相关文档

- 技术设计：`docs/07_技术设计文档_TDD.md`（v1.7.39）
- 实施计划与归属：`docs/08_编程实施计划_阶段划分与窗口归属.md`（v1.4.2）
- 评测口径：`eval/olist/README.md`、`eval/olist/report.md`
- 部署/演示：`deploy/demo/README.md`
- 许可证：`docs/portfolio/LICENSES.md`
- 简历要点 / 口述稿 / 毕设映射：`RESUME_BULLETS.md`、`PITCH.md`、`THESIS_MAPPING.md`
