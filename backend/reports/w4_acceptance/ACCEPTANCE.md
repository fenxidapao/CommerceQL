# W4 包装窗 · Phase A 最终验收证据索引

- **工作树**：`CommerceQL-archive/w4_worktree`（`git worktree add ... b780125`，**不是 clone**）
- **HEAD**：`b780125462574391f29f5bdd3567f2876c672863`（`b780125`，739 笔）
- **验收日期**：2026-10-29（+0800）
- **隔离栈**：compose 项目 `cqlw4`（宿主端口 pg `55432` / api `58000`；redis/pgbouncer/web 端口未发布）
- **花费口径**：主栈 `¥0.107807` + `cqlw4` 实际账本值（见 §8），对照本窗上限 `¥0.3`

> 本文件只做**索引**：数字全部指向同目录原始件，不手抄推算。原始件由工具自产（tee 日志 / 工具 JSON）。

## 0. 环境与隔离

| 项 | 读数 | 源 |
|---|---|---|
| 覆盖文件 | `pg: 55432`、`redis: []`、`api: 58000`、`pgbouncer: []`、`web: []` | `docker-compose.w4accept.yml`（本目录副本） |
| `config` 发布端口 | 仅 `55432`、`58000` | `docker compose -p cqlw4 -f deploy/docker-compose.yml -f deploy/docker-compose.w4accept.yml config` |
| 容器名 | `cqlw4-pg-1` / `cqlw4-redis-1` / `cqlw4-api-1` | `docker compose -p cqlw4 ps` |
| 工作树身份 | `b780125` / 739 笔 / 工作树内改动 = eval 产物 + 覆盖文件 | `worktree_identity.txt` |
| LLM 端点 | 第三方中转 `https://wanwanzhou.top/v1`（模型 `deepseek-v4.1-flash`） | 见 §9 偏差登记 |
| 嵌入端点 | 宿主 Ollama `bge-m3`（容器经 `host.docker.internal:11434`） | api 启动日志 `embedding_dim_matches_vector_column` |

## 1. 迁移（全新库）

`alembic upgrade head`：`0001 → 0007` 全部执行，`alembic current = 0007 (head)`。

## 2. 合成栈数据装载

`deploy/loadtest/load_synth_to_pg.py --sqlite data/ecom_sandbox.db --dsn postgresql://postgres:***@127.0.0.1:55432/ecom --force`

| 表 | 行数 |
|---|---|
| `app.dim_date` | 730 |
| `app.order_paid` | 494,249 |
| `app.order_refund` | 23,116 |
| `app.product` | 6,000 |
| `app.region` | 31 |
| `app.shop` | 12 |
| `app.traffic_daily` | 1,500,556 |

视图以 `T_A` 可读（`v_order_paid 494,249`、`v_traffic_daily 1,500,556` …）。源：`load_synth.log`。

## 3. Olist 沙箱重建（与主仓件对撞）

| 项 | 读数 | 期望 | 判据 |
|---|---|---|---|
| 体积 | `92,684,288 bytes` | `92,684,288` | 一致 |
| sha256 | `17c14cee7268e78225afa0406d705cf9a018c984d86697a038682d001fac31b0` | `17c14cee…` | 一致 |
| 五视图行数 | 99441 / 112650 / 32951 / 103886 / 99224 = **448,152** | 448,152 | 一致 |

源：`build_olist_sandbox.log`。

## 4. 零成本 60 题 dry-run（补充项，零 LLM）

| 探针 | 读数 | 源 |
|---|---|---|
| `build_dataset.py --check` | `all_ok=true`；`cases_valid=60`、`execute=55`、`interaction=5`、`gold_executable=55`、`caliber_match=55` | `olist_dataset_check.log` |
| `run_olist.py --verify-only` | N-13 `all_ok=True`（内容/全量哈希与冻结件一致） | `olist_verify_only.log` |
| `run_olist.py --gold-only` | gold `10/10`、caliber `10/10`；`sandbox_db_sha256=17c14cee…` | `olist_gold_only.log` |
| `run_olist.py --instrument-control` | 正控 `55/55 ex=1.0`；负控 `0/55 ex=0.0`；`all_ok=True (not_ex_official=True)` | `olist_instrument_control.log` |

## 5. Olist 装 PG（隔离栈）

`COMPOSE_PROJECT_NAME=cqlw4 deploy/demo/load_olist_to_pg.py --exec --compose <worktree>/deploy/docker-compose.yml --source <worktree>/data/olist/olist_sandbox.db`

`pg_rows = {o_orders 99441, o_order_items 112650, o_products 32951, o_payments 103886, o_reviews 99224}`，合计 `448,152`。源：`load_olist_pg.log`。

## 6. 物化与 RLS 隔离读数

### 6.1 合成包 `2026.10.16.2`（一次性容器，启动期断言前置）

`asset=8`、`metric_def=22`、`dimension=9`、`field_binding=7`、`join_path=10`、`synonym=179`、`policy=2`、`default_predicate=2`、`embed_doc=284`；`embedding_status=embedded`、`tsv_status=tokenized`、`grant_policy_executed=true`。源：`materialize_synth.log`。

> 说明：全新库上 api 启动期断言 `active_bundle_version_materialized` 会**拒绝启动**（这是设计）。故先用一次性容器（`compose run --entrypoint python`）物化，再起 api。

### 6.2 Olist 包 `2026.10.27.1`

`embedding_status=embedded`、`tsv_status=tokenized`、`grant_policy_executed=true`、`consistent=true`、`checked_assets=5`、`mismatches=[]`；`ok=true`。源：`materialize_olist.log`。

| 租户 | v_o_orders | v_o_order_items | v_o_products | v_o_payments | v_o_reviews |
|---|---|---|---|---|---|
| 无 GUC（app_ro） | 0 | 0 | 0 | 0 | 0 |
| `T_A` | 99,441 | 112,650 | 32,951 | 103,886 | 99,224 |
| `T_B`（金丝雀 1 行/表） | 1 | 1 | 1 | 1 | 1 |
| 金丝雀清理后 `T_B` | 0 | 0 | 0 | 0 | 0 |

## 7. Olist 栈 5 条 demo（**未达判据**）

判据：4 条 `complete`（bar/bar/bar/kpi）+ 1 条 `refuse`。**实际未达成**，四轮尝试全部留证：

| 轮 | 时间 | 模型 | 结果 | 账本 ¥ | 源 |
|---|---|---|---|---|---|
| 1 | 12:01 | `deepseek-v4.1-flash` | 5 条全 `error`（中转 502 `upstream_error`） | 0.000000 | `demo_5_attempt1_relay502.json` |
| 2 | 13:05 | `deepseek-v4-pro` | 2 complete（demo_2 bar、demo_5 kpi）+ 1 refuse（demo_4）+ 2 error（demo_1 `llm_unavailable`、demo_3 `plan_generation_failed`） | 0.1414 | `demo_5_attempt2_v4pro.json` |
| 3 | 13:06 | `deepseek-v4-pro` | **3 complete（demo_1 bar、demo_2 bar、demo_5 kpi）+ 2 refuse（demo_3、demo_4）** ← 最接近判据 | 0.242185 | `demo_5_attempt3_v4pro.json` |
| 4 | 13:08 | `deepseek-v4-pro` | 2 complete（demo_2 bar、demo_5 kpi）+ 2 refuse（demo_3、demo_4）+ 1 error（demo_1） | 0.1579 | `demo_5.json`（末轮原样） |

- **稳定失败点**：`demo_3`（`g07`「各订单状态分别有多少订单？」）在轮 2/3/4 均止于 plan 阶段（`plan_generation_failed` 两次 → `template_only` → `refuse no_data_asset`）；轮 3 的 `demo_3` 延迟仅 6.3s，属模型返回不可用计划，**非 15s 节点超时**。W3 用 `deepseek-flash` 时该题正常出 bar 图（`backend/reports/w3_demo/demo_5.json`）。
- **未改任何产品代码/判据**；按总控「再不行就停下」停跑。
- 展示口径：截图为 W3 生产栈真跑（`backend/reports/w3_demo/demo_*.png`），本窗**没有**可替换的新截图；本目录的尝试件只作过程证据，**不得**当作 5/5 通过。

## 8. 花费账

| 账本 | 读数 | 源 |
|---|---|---|
| 主栈（验收前/后） | `2026-10-28 0.083210 + 2026-10-29 0.024597 = ¥0.107807`（DB 时区分日；前后同值） | `main_stack_before.txt`、`main_stack_after.txt` |
| `cqlw4` 合成问题 1 条 | `¥0.877296`（4 次调用；97,242 入 / 4,456 出；`deepseek-v4.1-flash` 按兜底价 + `price_guess`） | `synth_query_M-DIM-02.sse` |
| `cqlw4` demo 四轮 | `0 + 0.1414 + 0.242185 + 0.1579 = ¥0.541485` | §7 各件、`cqlw4_cost_ledger.txt` |
| **`cqlw4` 合计** | `¥1.739752`（`v4.1-flash 4 调用 ¥0.877296` + `v4-pro 47 调用 ¥0.862456`） | `cqlw4_cost_ledger.txt` |
| **两栈合计（账本口径）** | `¥0.107807 + ¥1.739752 = ¥1.847559` | 同上 |

> ⚠️ 对照本窗批准上限 **¥0.3：账本口径已超 6.2 倍**。三个原因必须同框：① 中转模型 ID 不在 `app/llm/budget.py:PRICES`，按 `deepseek-v4-pro` 最贵档兜底（`price_guess`）；② 中转回报 token 偏大（8-token ping 报 874 入 / 516 出）；③ 轮 2–4 的重试与多轮 demo。**这不是中转真实扣费**——该站无账单接口（`/v1/dashboard/billing/*`、`/v1/credits`、`/v1/balance` 全 404），真实花费 **UNVERIFIED**。总控 12:00 后批准 demo 上限 ¥6（账本口径），demo 实际 ¥0.541485，未超该批准。

## 9. 与 W3 参考读数的偏差登记（必须同框）

1. **LLM 端点不同**：W3 的 5 条 demo 走官方 `https://api.deepseek.com` + `deepseek-flash`（`backend/reports/w3_demo/demo_5.json`：`total_cost_cny=¥0.02384`）。本窗为第三方中转 `https://wanwanzhou.top/v1` + `deepseek-v4.1-flash`（总控提供）。
2. **模型 ID 不在价目表**：`app/llm/budget.py:PRICES` 只有 `deepseek-flash` 与 `deepseek-v4-pro`；`deepseek-v4.1-flash` 按最贵档兜底计价并打 `price_guess`。因此账本 ¥ 值**不是中转真实扣费**（该站无余额接口，`/v1/dashboard/billing/*`、`/v1/credits`、`/v1/balance` 全 404）。
3. **中转 token 回报偏大**：8 token 的 ping 回报 `prompt_tokens=874`、`completion_tokens=516`。
4. **中转可用性**：2026-10-29 12:01–13:07 期间 `deepseek-v4.1-flash` 持续 `502 upstream_error`（四个模型同时 502 出现在 12:01–12:24；13:04 起 `v4-pro`/`v3.2` 恢复 200，`v4.1-flash` 仍 502）。因此 demo 轮 2–4 改用 `deepseek-v4-pro`，与总控口径「`deepseek-flash` = `v4.1-flash`」**不一致**；此偏差只影响 demo，不影响 EX 读数（EX 三批未重跑）。
5. **读数身份**：三批 live EX 的 `build.git_rev=aeb53eb`、`git_dirty=true`（W2 未提交中间态）；最终入库代码 `b780125`。本验收是**工作树 @ b780125**，不写「同一 rev 干净复现」。

## 10. 回归读数（零成本，主仓）

| 项 | 读数 | 源 |
|---|---|---|
| pytest | `2908 passed / 5 failed`（430.72s；5 条为既有失败，清单见下） | `pytest_summary.txt` |
| ruff | `214`（基线，允许红） | `ruff.log` |
| mypy | `8 errors / 5 files` | `mypy.log` |
| lint-imports | `4 kept / 0 broken` | `lint_imports.log` |
| Olist 包校验 | `PASS=33 FAIL=0 SKIP=1 WARN=0` | `validate_bundle_olist.log` |
| 合成包校验 | `31 PASS / 0 FAIL / 1 SKIP / 2 WARN` | `validate_bundle_synth.log` |

5 条既有失败测试 id 见 `pytest_summary.txt`；**不写成「已回归通过」**。

## 11. 证据清单

`manifest.sha256`（本目录）给出全部证据文件的哈希。原始 SSE / 日志 / 工具 JSON 均未手改。
