# RL-6 · 成本异常（日预算 80% / 100%）

> 归属窗口：**W7** ｜ 日期：**2026-09-18**
> 依据：07 §18.7 第 6 行 · §10.4（成本计量与预算熔断）· §15.3/§15.4 · 附录 A §A.11 · NFR-4.1 · N-19
> 共用命令与端口约定见同目录 `README.md` §五。

---

## 0. 一句话定性

§18.7 处置栏原文：**「80% 告警并收紧候选路数；100% 熔断 → 转模板」**。
关键事实：**100% 熔断后服务没有停**（转模板继续答，只是降级），所以**不要把它当宕机处置，更不要为"恢复服务"去抬预算**。

**熔断实装（`app/llm/budget.py` 的 `BudgetGuard`，§10.4 逐行有代码）**

| 07 要求 | 实现 |
|---|---|
| 预算层级 = 租户日预算 + 全局日预算 | `tenant_budget` / `global_budget`，**任一 100% 即熔断**（`preflight()` 两层都查） |
| 80% 告警 / 100% 硬熔断 | `BudgetDecision.warn` / `allowed=False`；阈值取 `BUDGET_ALERT_RATIO` |
| 熔断后走模板 + `degraded` 并在 `meta` 标注 | `allowed=False` → 门面走模板层并发 `degraded(cost_too_high, template_only)`（`app/llm/__init__.py:49`） |
| 接近预算时自动降为单路 | `force_single_path=True` → `action_taken=reduced_candidates`（这就是 §18.7 说的"收紧候选路数"，**已自动化**） |

两条边界纪律（判定时必须知道）：① **预估成本也计入判定**（`spent + estimated`），所以"没到 100% 就被熔断"是设计而非 bug；② 触顶用 `>=` 不用 `>`。

---

## 1. 触发信号（真实名字）

| 类型 | 信号 | 状态 |
|---|---|---|
| 配置阈值 | `DAILY_BUDGET_CNY=100`（全局日预算，元/日）、`BUDGET_ALERT_RATIO=0.8` | `deploy/.env:143-144` |
| 代码常量 | `DEFAULT_TENANT_DAILY_BUDGET_CNY = Decimal("10")`（**租户日预算没有任何配置项**，`app/llm/budget.py:89-94`） | 见 §5 不一致 |
| 帧 | `degraded{reason="cost_too_high", action_taken="template_only"}`（100%）；`degraded{..., action_taken="reduced_candidates"}`（80% 单路化） | 真实取值（`DegradedReason.COST_TOO_HIGH` / `ActionTaken`） |
| HTTP | 走到执行层时可能出 **`COST_TOO_HIGH` → 422**（`ERROR_HTTP_STATUS`）。它是 `⭕` 档：**不带** `Retry-After`，**必须给** `suggestions[]`（"收窄时间范围/增加过滤条件/减少分组维度"，`DEFAULT_SUGGESTIONS`） | 别和闸门三的成本拒绝混：同一个码，两个来源（§7.5 EXPLAIN 成本闸门 vs §10.4 预算） |
| 指标 | `daily_cost_cny`（Gauge，无标签 = **只有全局口径**）、`llm_tokens_total`（`token_key` 取 input/output/cache_hit/total）、`gen_sql_rounds_total`、`degraded_total{reason="cost_too_high"}` | 状态**分三种，别混着读**（端点口径见 README §四-4）：① `daily_cost_cny` **已接线但是条件性的** —— `samplers.make_cost_sampler` 只在 `graph_runtime.cost_ledger` 非 None 时注册，而本指标无标签 ⇒ 未注册时照样导出一条**恒 0** 序列；判据是启动日志 `obs_wiring_done` 的 `samplers=[...]` 是否含 `daily_cost`。② `llm_tokens_total` / `gen_sql_rounds_total` **无调用点**，但两族的标签要么有声明域要么无标签 ⇒ 属"**A 类恒 0 已导出**"：会看到 0 行，那**不是**"没花 token / 没纠错轮次"，是"采集点不存在"。③ `llm_json_parse_failure_total` 的 `prompt_version` 无声明域 ⇒ 属"**B 类整族不输出**"：`/metrics` 里根本没有这个前缀。真账仍以 `cost_ledger` 表为准 |
| 告警（§15.4） | 「日成本 80% → **P1**；100% → **P0**」；「token/请求 周环比上升 >40% → **P2**」（P2 的含义写在 §15.4：**提示 prompt 或输入分布变了**，不是账错） | 规则**已落地**：`deploy/observability/alert.rules.yml` 的 `CommerceQLDailyCostWarning`（`daily_cost_cny >= 80`）/ `CommerceQLDailyCostBreach`（`>= 100`）/ `CommerceQLTokensPerRequestWeekOverWeekRise`；已过 promtool 离线校验（`check rules` + `test rules`），**未做过一次线上触发验证**。⚠️ 两个坑：阈值是**写死的字面量**（80/100 对应 `DAILY_BUDGET_CNY=100`；附录 D 里 dev=20/staging=50 ⇒ 换环境不同步改数字就静默失效）；且**没有 Alertmanager** ⇒ 规则只在 observability profile 起来后才评估，且要有人去 `/alerts` 看才知道响了 |

> ⚠️ **成本异常 ≠ 429，也 ≠ 409**。预算熔断给的是 `degraded` + 模板，**不是** `429 RATE_LIMITED`；`429` 只表示**配额**（按桶 30/5/10/60）。看到 429 就跑本条是误诊（转 W4）。`409 SESSION_CONFLICT` 是会话串行，同样不相干。

---

## 2. 判定

判定的目的只有一个：**分辨「真的花超了」/「单价或聚合口径错了」/「输入分布或 prompt 变了」**。三者处置完全不同，而第一步是分辨**全局**还是**单租户**。

```bash
BASE=http://127.0.0.1:8000/api/v1
# 2.1 快照：探针与阈值（成本异常不会改探针状态——若 ready 也 503，那是别的故障）
curl -sS -o /dev/null -w 'ready=%{http_code} aggregate=' "$BASE/healthz/ready"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/healthz"
docker compose -f ../deploy/docker-compose.yml exec -T api python -c \
  "import os;print({k:os.getenv(k) for k in ('DAILY_BUDGET_CNY','BUDGET_ALERT_RATIO','LLM_MODEL_FAST','LLM_MODEL_STRONG','LLM_SEMAPHORE_FLASH','LLM_SEMAPHORE_PRO','GATE_MAX_REPAIR_ROUNDS')})"
```

```bash
cd deploy
# 2.2 降级分布（80% 与 100% 的区分就在 action_taken 上）
docker compose logs --since 60m api | grep -oE '"reason":"cost_too_high","action_taken":"[a-z_]+"' \
  | sort | uniq -c | sort -rn
docker compose logs --since 60m api | grep -oE '"blocked_by":"(tenant|global)"' | sort | uniq -c
```

```bash
# 2.3 真账：cost_ledger（表在 app schema，索引按 (tenant_id, created_at) / (created_at)，迁移 0004）
#     ✅ 2026-09-19 本机已实测可执行（真 PG + head=0005）。读数：小时分布 13:00→58 次/¥0.046680、
#        14:00→24 次/¥0.017578；租户分组只有 T_A（82 次 / ¥0.064258）⇒ 两条 SQL 的合计互相对得上。
#     ⚠️ token 口径：算总 token 用 sum(input_tokens + output_tokens)，**不要加 cache_hit_tokens** ——
#        它是 input_tokens 的**子集**（app/llm/budget.py:175 用 max(input - cache_hit, 0) 计未命中价），
#        相加等于把命中的前缀算两遍（本机实测：正确 217,675 vs 错误算法 473,270）。
#        命中率才用 cache_hit/input（NFR-4.3，`llm/__init__.py:279` 同式）。
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select date_trunc('hour', created_at at time zone 'Asia/Shanghai') as hr,
          sum(cost_cny) as cny, count(*) as calls
     from app.cost_ledger
     where created_at >= date_trunc('day', now() at time zone 'Asia/Shanghai')
    group by 1 order by 1 desc limit 24;"
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select tenant_id, sum(cost_cny) as cny, count(*)
     from app.cost_ledger
    where created_at >= date_trunc('day', now() at time zone 'Asia/Shanghai')
    group by 1 order by 2 desc limit 10;"
```

**分流表**

| 观察 | 结论 | 走 |
|---|---|---|
| 全局日累计逼近/达到 `DAILY_BUDGET_CNY`，`blocked_by="global"` | **全局预算触顶**（真超支） | §3-1 / §3-2 |
| 全局很低但某租户被熔，`blocked_by="tenant"` | **租户层熔**，且阈值是**硬编码的 10 元**，`.env` 改不动 | §3-2 + §5（配置缺口） |
| 单条请求 `cost_cny` 异常大、调用次数没涨 | **单价/档位错**：`classify_tier`（峰谷档，`BILLING_TZ=Asia/Shanghai`）或 `resolve_price` 的价表 | §3-3，**不要抬预算** |
| `llm_tokens_total{token_key="total"}` / 请求数 周环比 >40%（§15.4 P2），且 `llm_json_parse_failure_total` 同涨 | **prompt 或输入分布变了**（§15.4 对 P2 的原解释），不是账错 | 转 **W3A** |
| `gen_sql_rounds_total` / 请求数 上升（纠错轮次变多） | **有界纠错在反复重试** → 成本被 `repair` 放大（`GATE_MAX_REPAIR_ROUNDS` 上限 2，`config.py:115` 有 `le=2` 硬约束） | 转 **W4/W2C** 看拒绝原因（并看 RL-5） |
| prompt 前缀命中率塌陷：`llm_tokens_total{cache_hit}` / `{input}` 明显下降 | 缓存没吃到（ADR-12：**结果缓存 P0 关闭**，只有语义检索缓存与 prompt 前缀缓存开着；"缓存的主要收益是成本与 DB 压力，不是延迟"§16.4） | §3-4，**不得顺手开结果缓存** |
| 同时有 `embedding_unavailable` / `llm_unavailable` | 成本是**次生**现象（重试与降级链在花钱） | **先走 RL-2 / RL-4** |

---

## 3. 处置动作

1. **80%（P1）：收紧候选路数 —— 系统已经自动做了**（`force_single_path` → `reduced_candidates`）。运维侧可做的是压住**并发放大**，且**只调并发，不调预算**：
   ```
   LLM_SEMAPHORE_PRO=1      # 原 2；pro 是贵的一路
   LLM_MAX_CONCURRENCY=20   # 原 50
   ```
   生效需重启（`deploy/.env` 改前 `cp .env .env.bak-$(date +%Y%m%d%H%M)`）：
   ```bash
   cd deploy && docker compose stop --timeout 45 api && docker compose up -d api
   ```
   ⚠️ 前提：P0 单进程 uvicorn（§18.1）。**多 worker 会把按进程的 LLM 信号量悄悄放大成 N 倍并发** —— 想加 worker 必须先把信号量换成 Redis 令牌桶（§16.6），不是运维顺手改的参数。
   ⚠️ §18.3 的停机链**第 1~3 步已实装并已用桩实测**（SIGTERM trap → 摘 readiness → drain 在途 SSE ≤30s，超时流补发 `error(INTERNAL, terminal:true)`；实测覆盖"置位后才收尾/预算耗尽仍转发 TERM/无 token 不卡死"三场景，**没覆盖**真实 `app.main:app` 上真实 SSE 客户端能否收到终止帧；第 4~6 步属 `api/runner.py` 的 finally，归 W4。见 README §四-2）。所以结论不变、理由变了：**仍然挑空载时点重启**。另：停机后 `docker ps -a` 显示 `Exited (143)` 是**正常产物**（dash 取不到服务进程真实退出码），只有 `Exited (137)` 才表示 drain 撞上了 `stop_grace_period` 被硬杀。
2. **100%（P0）：熔断已生效，服务仍在跑（转模板）**。此步骤只做三件事：
   * **确认降级链在工作**：`degraded{reason="cost_too_high", action_taken="template_only"}` 在涨、用户拿到的是模板结果/拒答，**不是** 500 或静默断流（若 500 → 那是别的故障，转 RL-1/RL-4）。
   * **通知用户侧口径**：模板层 P0 **恒无命中**（`app/graph/nodes/normalize.py:24`），成本熔断期间**拒答率会明显上升** —— 这是预期的，**不得**为了压拒答率而放宽语义层。
   * **等自然复位**：预算按 `BILLING_TZ = Asia/Shanghai` 的**日切**判定（`budget.py:381` `now.astimezone(BILLING_TZ).date()`）。想立刻恢复只有两条路：**显式抬高预算（需决策）**，或**等到 00:00**。
3. **判定为"单价/档位错"时**：先取证（把 `cost_ledger` 里可疑行按 `model`/`tier` 分组留存），修**价表或聚合口径**（归 **W3A** 的 `app/llm/budget.py`），**不要**用"抬高 `DAILY_BUDGET_CNY`"掩盖口径错 —— 那等于同时改掉安全边界（NFR-4.1 是**硬约束**）。
4. **成本被重试/纠错放大时**：确认 `GATE_MAX_REPAIR_ROUNDS` 没被调大（默认 2 且已有 `le=2` 上限，改不动是**有意的**）、`LLM_MAX_RETRIES` 未调大（默认 3）。⚠️ **P0 结果缓存关闭**（ADR-12），**不得**为省成本去开 `ENABLE_RESULT_CACHE`：`config.py:201-203` 要求同时显式给 `ENABLE_RESULT_CACHE_CONFIRMED=true` 才允许启动 —— 这道"防误开"闸门是刻意的，键设计错 = 事故。**要开必须先走架构裁定。**
5. **⛔ 禁止清单**：
   * 不得手动删/改 `app.cost_ledger` 的行来"清账"。它是账本，且**账本与审计同源**（§10.4 的成本计量落 `audit_log_supplement` 聚合，§12.4 的 append-only 保证）；`app_rw` 无 UPDATE/DELETE 权限（§18.4 第 5 行），**你删不动**。真 PG 上确认这一点本身就是恢复判据之一。
   * 不得为了"恢复服务"抬 `DAILY_BUDGET_CNY`。抬预算 = 显式决策，必须记录决策人 + 理由 + 生效时段（NFR-4.1 + N-19 的成本口径纪律）。
   * 不得 `docker kill` / `kill -9`（§18.3）。重启不改变已花的钱，只会打断在途流并丢掉段 2 审计。
   * 不得把 `BUDGET_ALERT_RATIO` 调低（如 0.5）"提前告警"—— 它同时改变 `warn` 与单路化的触发点，是**策略**不是显示设置。

**回滚**：`.env` 从时间戳备份还原 + 按 §3-1 姿势重启。若为判定跑过任何 `UPDATE`/`DELETE` 尝试（应失败），把它们**当作安全事件**记进 §4 的事件单（说明权限边界被测试过，且**应当**失败）。

---

## 4. 验证恢复

| 判据 | 怎么看 | 位置 |
|---|---|---|
| 回到告警线以下 | 当日累计 < `DAILY_BUDGET_CNY × BUDGET_ALERT_RATIO`（默认 100 × 0.8 = **80 元**）。**以 `cost_ledger` 聚合为准**；`daily_cost_cny` 只有在启动日志 `obs_wiring_done` 的 `samplers=[...]` 含 `daily_cost` 时才是可信曲线（无标签 ⇒ 未接线时它也显示 0） | `app.cost_ledger`（真 PG）/ §15.5 成本屏 |
| 熔断解除 | `degraded_total{reason="cost_too_high"}` 增速归零；新查询不再出现 `blocked_by` 的日志 | 日志 / 指标 |
| 拒答回落 | `refuse_total{reason=...}` 与 `clarify_total` 回到基线（熔断期偏高的那些） | §15.3 语义指标 |
| 单路化解除 | `degraded_total{action_taken="reduced_candidates"}` 不再增长（80% 线以下应恢复多路） | 指标 |
| 效率没恶化 | `llm_tokens_total{token_key="cache_hit"}` / `{input}` 比例回到基线（prompt 前缀命中率，§15.3 缓存命中率行口径）。⚠️ 本族**当前无调用点**，导出的是 A 类恒 0 ⇒ 比值是 0/0 = **无数据**，本行判据**只能靠 `cost_ledger` 的 token 列或日志**，不得靠这条线 | 指标（`UNVERIFIED`）/ 账本 |
| 不是 prompt 退化 | `llm_json_parse_failure_total` 未同时上升（**最早预示 prompt 退化**的指标，§15.3）。⚠️ 该族 `prompt_version` 无声明域 ⇒ 属 **B 类整族不输出**：`/metrics` 里根本没有它。**"看不到线"不能读成"没有解析失败"**，本行判据当前不可用，改用日志计数 | 日志（指标 `UNVERIFIED`） |
| 边界仍然成立 | `has_table_privilege('app_rw','app.cost_ledger','delete')` = **f** | `psql`（真 PG） |
| 归档 | 事件单：全局 vs 租户、根因三分支结论、是否抬过预算（谁批的、时段）、以及**"80%/100% 两级各自命中时间"**写清 | `backend/reports/w7/`（W7 子目录） |

**不得报告的部分**：成本恢复 ≠ 准确率恢复。熔断窗口内的查询走了模板/单路，那批结果的质量与口径**和正常窗口不同**；若窗口内产出过评测/澄清率结论，必须标注，且**压测结果与评测结果分开归档**（PRD §13.5）。

---

## 5. 升级 / 联系（归属见 08 §4.1）

| 议题 | 找谁 |
|---|---|
| `app/llm/budget.py`：`BudgetGuard`、`CostLedger` sink、价表与峰谷档、成本计量口径 | **W3A** |
| `cost_ledger` 建表/索引/权限（迁移 `0004_cost_ledger_and_query_plan.py`）、`app/repo/cost_ledger.py` | **W1B** |
| `degraded(cost_too_high)` 帧与 `COST_TOO_HIGH` 的 422/`⭕` 档语义、`suggestions[]` | **W4** |
| `daily_cost_cny` / `llm_tokens_total` / `gen_sql_rounds_total` 的**采集端**、`/metrics`、§15.5 成本屏与 §15.4 成本告警规则、`deploy/.env` | **W7（本窗口）**（现状：`/metrics` 已注册；`daily_cost_cny` 已**条件**接线（`cost_ledger` 为 None 则不注册）；`llm_tokens_total` / `gen_sql_rounds_total` **仍无调用点**（属 A 类恒 0，需 W3A/W4 加一行调用），成本两条告警规则已落地但只做过离线 promtool 校验 |
| 结果缓存是否开启（ADR-12 的显式确认标志） | **架构窗口**裁定，W7 不得自开 |
| **不一致上呈**：① §18.7/§10.4 讲"日预算"，但**租户日预算无配置项**、写死 `DEFAULT_TENANT_DAILY_BUDGET_CNY = 10`（`budget.py:94`），而全局 `DAILY_BUDGET_CNY=100` → "某租户被熔断"在部署面**不可调**；② `daily_cost_cny` 无标签（只有全局口径），§15.5 成本屏要做**按租户**曲线就必须新增标签 → 涉及基数纪律，需架构确认；③ §15.4「日成本 100% = P0」与 §14.2 的 `COST_TOO_HIGH` 同码双源（预算 vs 闸门三）在指标层无法区分 | **架构窗口** → **待架构窗口分配编号** |
