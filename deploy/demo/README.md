# deploy/demo —— Olist 真实数据的装载与演示资产

> 归属窗口：W1 实施窗（`build_olist_sandbox.py`）｜问题号 `U-143`
> 本目录只放**脚本**，产物一律落 `data/`（gitignore）。

## 1. 已有

### `build_olist_sandbox.py`

从原始 Olist SQLite（只读 ATTACH）生成评测沙箱 `data/olist/olist_sandbox.db`。

⚠️ 用 archive 里的 3.13 venv 跑（`CommerceQL-archive/local/.venv/Scripts/python.exe`）：
自检段会 import `eval/sqlite_exec.py`，它依赖 `app.exec`（pydantic v2）。
Anaconda 的 3.11 + pydantic 1.10 会直接红。仓库根**不放** `.venv`。

```bash
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"
"$V" deploy/demo/build_olist_sandbox.py \
  --sqlite ../Text2SQL/real_data/olist/olist.sqlite \
  --out data/olist/olist_sandbox.db
```

产物契约（三条，缺一 `eval/sqlite_exec.py::open_sandbox_connection` 就用不了）：

1. 物理表名**恰好等于**语义包的 `physical_asset`：`v_o_orders` / `v_o_order_items` /
   `v_o_products` / `v_o_payments` / `v_o_reviews`；
2. 每张表带 `tenant_id` 列 —— TEMP VIEW 的过滤条件就是它；
3. 行数 / 体积 / sha256 写进 `eval/olist/sandbox_manifest.json`（经 `eval/olist/build_dataset.py`
   的落盘守卫，所以清单只会出现在 `eval/olist/` 下）。

自检走 `open_sandbox_connection`（不是裸 `sqlite3`）：`T_A` 每表 > 0、`T_B` 每表 = 0。

**当前读数**（2026-10-27，CPython 3.13.14 / sqlite3 3.53.1）：448,152 行 /
92,684,288 bytes / sha256 `17c14cee…`。**同一解释器内**两次构建哈希一致；
**跨解释器会变**（3.13.13 下是 `a67c5f7d…`，字节数相同）—— 判定身份要么钉解释器，
要么以内容为准。

**沙箱里没有的东西**：`geolocation`（1,000,163 行，本薄包不用）、
`order_reviews` 的评论正文两列（自由文本，未做 PII 审阅）、`sellers` 表。

## 2. W3 已创建（2026-10-28，U-147）

| 文件 | 用途 |
|---|---|
| `load_olist_to_pg.py` | SQLite 沙箱 → PG `app.o_*` 基表（app_rw 写；COPY text 流） |
| `materialize_olist.py` | Olist 包物化（`with_policy=True`）+ 一致性断言 + T_B 金丝雀读数 |
| `docker-compose.olist.yml` | 只把 api 的 `SEMANTIC_BUNDLE_PATH` 切到 Olist 包 |
| `run_demo_queries.py` | 5 条 live 演示（真打 `POST /api/v1/query`，逐帧落证据 JSON，带 ¥0.3 预算闸） |

### 2.1 迁移

`backend/app/repo/migrations/versions/0007_olist_demo_assets.py` 建
`o_orders / o_order_items / o_products / o_payments / o_reviews` 五张基表 +
`v_o_*` 五个认证视图（owner `app_rw`）。**迁移里没有 GRANT/POLICY/RLS** ——
它们由 `materialize` 从语义包派生。0007 由 W3 占用；B 的 `workflow_and_runs`
顺延 `0010`（`docs/08 §4.1` 补登记）。

```bash
cd backend
export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/ecom"
"$V" -m alembic current     # 0006 (head) —— 先验 DSN
"$V" -m alembic upgrade head
"$V" -m alembic heads       # 0007 (head)
```

### 2.2 装载（数据源 = 已冻结的 SQLite 沙箱）

```bash
"$V" deploy/demo/load_olist_to_pg.py --exec
```

2026-10-28 实测：`99441 / 112650 / 32951 / 103886 / 99224`（合计 **448,152**），
PG 侧复核行数逐表相等。

### 2.3 物化 + RLS 读数（必须在 api 容器内跑）

```bash
docker compose -f deploy/docker-compose.yml exec -T api \
  python - < deploy/demo/materialize_olist.py
```

2026-10-28 实测（`ok=true`）：

| 项 | 读数 |
|---|---|
| bundle | `/semantic/bundle_olist_2018.yaml`，版本 `2026.10.27.1` |
| materialize | `grant_policy_executed=true`，`embedding_status=embedded`，`tsv_status=tokenized` |
| 一致性 | `consistent=true`，`checked_assets=5`，`mismatches=[]` |
| app_ro 无 GUC | 五表全 `0`（失败关闭） |
| app_ro GUC=`T_A` | `99441 / 112650 / 32951 / 103886 / 99224`（金丝雀在库时也不变） |
| app_ro GUC=`T_B` | 五表各 `1`（金丝雀：`canary_order_1` / `canary_product_1` / `canary_review_1`） |
| 删金丝雀后 | `T_A` 回原值；`T_B` 全 `0` |

⚠️ **T_B=0 本身是平凡成立的**（沙箱只装 T_A）。上面的“T_B=每表 1”才是真隔离证据；
脚本把金丝雀 id、全部读数与清理后复核值都打进同一个 JSON，`finally` 兜底删除。
探针 GUC 与执行器同形：`app.tenant_id` **且** `app.shop_ids=''`（Olist 资产无
`shop_id`，但少设 `shop_ids` 在带 shop 子句的合成视图上会被滤成 0 —— 2026-10-28 实测）。

### 2.4 切到 Olist 包演示

```bash
docker compose -f deploy/docker-compose.yml -f deploy/demo/docker-compose.olist.yml \
  up -d --no-deps api
# 验收后切回合成包
docker compose -f deploy/docker-compose.yml up -d --no-deps api
```

### 2.5 5 条 live 演示（2026-10-29，U-147/U-148）

```bash
# 1) api 切到 Olist 包并重建（代码在镜像里，改 app 后必须 build）
docker compose -f deploy/docker-compose.yml build api
docker compose -f deploy/docker-compose.yml -f deploy/demo/docker-compose.olist.yml \
  up -d --no-deps api
# 2) 签 T_A 令牌（不读 .env）
TOKEN=$(cd backend && "$V" scripts/mint_dev_token.py --tenant-id T_A --user-id u_dev --role analyst | tail -1)
# 3) 5 条（live，预算闸 ¥0.3）
"$V" deploy/demo/run_demo_queries.py --token "$TOKEN" \
  --out backend/reports/w3_demo/demo_5.json
```

实测（`backend/reports/w3_demo/demo_5.json`，一次跑完 `total_cost_cny=0.02384`）：

| # | 题面 | terminal | chart_type | 结果 |
|---|---|---|---|---|
| 1 | 2018 年各州 GMV 前十 | complete | bar | SP ¥3,374,237.33（10 项） |
| 2 | 各商品类目的商品件数前五 | complete | bar | bed_bath_table 11,097 件（5 项） |
| 3 | `g07` 原文「各订单状态分别有多少订单？」 | complete | bar | delivered 96,478 单（8 类） |
| 4 | 删掉订单表 | **refuse** | — | `pii_blocked`（危险请求被拒） |
| 5 | `o07` 原文「成交订单有多少？」 | complete | kpi | 98,207 单 |

⚠️ **第 2 条换过题**：原题「2017 年每个月的订单量」在闸门一被 **R14** 拒 ——
`to_char(..., 'YYYY-MM')` / `date_trunc('month', ...)` 的字符串格式串不在字面量白名单。
W2 的 `results_v1_r1.json` 里 **12 条**“每月”题（`g02/g06/g10/o02/o09/o13/o17/o22/o29/o34/o39/o44`）
全部同样 R14，是既存方言缺口，不是 W3 回归。修它要改 `app/guard/**`（W2C 归属，
等于改判据）⇒ 总控告裁定换题并在
`backend/reports/w3_demo/r14_line_gap.json` 与 `docs/07 v1.7.38` 登记。

浏览器验收（截图 + 任务号在 `backend/reports/w3_demo/browser_acceptance.json`）：
5/5 交互完成，其中 4 条图形 / 拒答卡真渲染；第 5 条命中一个**前端既有缺陷** ——
`CHART_TYPES_ALL` 缺 `'kpi'`，后端正确的 kpi 被当成未知类型降级为表格。
经总控授权 W3 代改一行（`frontend/src/components/ResultBlock.tsx`，W5 归属），
重建 `dist` 后 kpi 卡正常渲染（控制台不再出现 `ui_unknown_chart_type: kpi`）。

累计 live 花费：`app.cost_ledger` 2026-10-28 + 10-29 合计 **¥0.107807**
（含首轮旧题、line 尝试与浏览器重跑），低于批准上限 ¥0.3。

### 2.6 两个刻意保留的已知项

1. **`semantic/bundle_olist_2018.yaml` 一个字不改**：`meta.dialect: sqlite` 与
   `meta.version: 2026.10.27.1` 保持原样。冻结集钉了 `bundle_version`，改包会让
   W2 证据失配；PG 链路的方言本来就硬编码 `postgres`（planner 的 `DIALECT_NOTE`
   与三闸门的 `sqlglot.parse(..., dialect="postgres")`），`meta.dialect` 不参与执行分支。
   这是“声明与链路的既存不一致”，修正走 v2，不在 W3 偷改。
2. **`delivery_late_rate` 不进 live demo**：除了 bundle expression 未 ×100，
   PG 的 `SUM(bigint)/COUNT(bigint)` 是**整数除法**（结果截断成 0/1），
   比 SQLite 的“偏小 100 倍”更糟。W3 只在文档登记，不在演示里展示该指标。

## 3. 文件归属

`deploy/**` 归 W7 实施窗；`build_olist_sandbox.py` 由 W1 建。W3 按
`docs/07 v1.7.38` / U-147 写入本目录的四个新文件（`load_olist_to_pg.py` /
`materialize_olist.py` / `docker-compose.olist.yml` / `run_demo_queries.py`），
不改 `deploy/**` 的归属列。新增脚本前先确认不覆盖 `deploy/.env`（含密钥，不入库）。
