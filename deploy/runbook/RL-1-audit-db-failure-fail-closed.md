# RL-1 · 审计库故障（fail-closed 生效）

> 归属窗口：**W7** ｜ 日期：**2026-09-18**
> 依据：07 §18.7 第 1 行 · §18.2 · §18.3 · §12.4 · §14.2 G1/G2 · ADR-14 · N-09 / NFR-2.6 / NFR-3.4 · 附录 A §A.8.1/§A.8.3
> 共用命令与端口约定见同目录 `README.md` §五。**开工前先读 `README.md` §四「诚实边界」。**

---

## 1. 触发信号（真实名字）

| 类型 | 信号 |
|---|---|
| 探针 | `GET /api/v1/healthz/ready` → **`503`**，`checks.metadata_db=false` 和/或 `checks.checkpointer=false` 和/或 `checks.redis=false`（§18.7 原文："硬依赖含元数据库"） |
| 探针 | `GET /api/v1/healthz` → **`503`** + `"status": "unhealthy"`（硬依赖失败才允许 503，附录 A §A.8.4） |
| 日志事件 | **`audit_pre_failed`**（`app/obs/audit.py:92`，带 `outcome="fail_closed"`）+ 紧随的 **`audit_pre_blocked_data`**（`app/graph/nodes/audit_pre.py:44`，带 `outcome="fail_closed"`） |
| 日志事件 | 段 2 单独失败：`audit_supp_failed`（`app/obs/audit.py:125`，`outcome="non_blocking"`）—— **不阻断**，只告警（§14.2 G2） |
| 对客户端 | SSE `error` 帧 `code=INTERNAL`（HTTP 500 / `⭕` 档：**不带** `Retry-After`，必须给 `suggestions[]`）—— 见 §14.2 G1 |
| 指标 | `http_requests_total{endpoint="/api/v1/query",status="5xx"}` 上升；`query_outcome_total{outcome="failed"}` 上升 |
| 告警（§15.4） | §18.7 标为 **P0**。⚠️ 规则文件**已落地**（`deploy/observability/alert.rules.yml`，9 条），但 §15.4 十条里**没有**"审计库故障"这一行 ⇒ 本故障**至今无 Prometheus 出口**，自动侧只有 compose 的 readiness healthcheck 会把容器标 `unhealthy`（且**不重启**，见 §四-1）→ 待架构窗口分配编号 |

> ⚠️ **文档与实现的第一处不一致（不得照抄文档执行）**：§18.7 写的日志判据是 `audit_insert_failed`，**仓库里不存在这个名字**。真实事件是 `audit_pre_failed`（段 1，抛 `AuditWriteFailed`）与 `audit_supp_failed`（段 2，吞异常只告警）。本条以代码为准。

> ⚠️ **不要与 RL-4 混**：`/healthz` 里 `llm_reachable` / `embedding_reachable` 为 `false` 时**必须**是 `200 + degraded`，那是降级不是本故障（二者探针已于 2026-09-18 接线，键名即 §A.8.4 那两个）。为什么挂只看一条 WARN 日志 `healthz_failed_probes`（`probe_detail` 已从响应体移除）。**只有硬依赖**（`metadata_db` / `checkpointer_reachable` / `redis_reachable` / `semantic_bundle_loaded`）失败才是 `503` = 本条。

---

## 2. 判定

按顺序做，**在第一步分出"DB 真挂了 / 池被打满 / 权限或迁移被改坏"三个分支**，三者处置相反。

```bash
BASE=http://127.0.0.1:8000/api/v1
# 2.1 三个探针各看一次（live 必须仍是 200 —— 若不是，见 README §四-1）
curl -sS -o /dev/null -w 'live=%{http_code}\n'  "$BASE/healthz/live"
curl -sS "$BASE/healthz/ready"; echo
curl -sS "$BASE/healthz"; echo
```

```bash
cd deploy
# 2.2 栈与容器状态（看 pg / pgbouncer / redis 是否 Up / healthy，api 是否正在被摘）
docker compose ps
docker compose logs --since 10m api | grep -E "audit_pre_failed|audit_pre_blocked_data|startup_assertion|checkpoint_schema" | tail -30
```

```bash
# 2.3 分支 A：PG 实例本身
docker compose exec -T pg pg_isready -U postgres -d ecom
docker compose exec -T pg psql -U postgres -d ecom -x -c \
  "select datname, numbackends from pg_stat_database where datname='ecom';"
# 2.3.b 连接被打满时按池归因（application_name 由 app/repo/pools.py 写入，checkpoint 池 = commerceql-checkpoint）
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select application_name, state, count(*) from pg_stat_activity
    where datname='ecom' group by 1,2 order by 3 desc;"
```

```bash
# 2.4 分支 B：审计表还在不在 / 迁移跑没跑（缺表 = 启动断言 AUDIT_LOG_APPEND_ONLY_ENFORCED 会 pending/fail）
#     ⚠️ schema 归属：业务表与账本表在 **`app`** schema（迁移 0001 `CREATE TABLE IF NOT EXISTS app.audit_log`），
#        LangGraph 检查点表在 **`lg`** schema（0001 只给 `GRANT USAGE, CREATE ON SCHEMA lg TO app_rw`）。
#        按 `public` 去找会"表不存在"，那是查错 schema，不是缺表。
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select table_schema, table_name from information_schema.tables
    where table_schema='app'
      and table_name in ('audit_log','audit_log_supplement','cost_ledger','query_task','query_plan','session');"
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select version_num from alembic_version;"   # env.py 未自定义 version_table → 默认 alembic_version
```

```bash
# 2.5 分支 C：append-only 边界有没有被人改坏（N-09 的前提，§18.4 第 5 行）
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select has_table_privilege('app_rw','app.audit_log','insert')  as can_insert,
          has_table_privilege('app_rw','app.audit_log','update')  as can_update,
          has_table_privilege('app_rw','app.audit_log','delete')  as can_delete;"
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select tgname from pg_trigger where tgrelid='app.audit_log'::regclass and not tgisinternal;"
# 角色级只读/可读的显式设定也在迁移里（0001）：app_rw 被 ALTER ROLE ... SET default_transaction_read_only = off
#   → 元数据写入必须可写；ANALYTICS 侧的 app_ro 才必须为 on（§18.4 第 2 行，别把两条判据混了）
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select rolname, pg_roles.rolconfig from pg_roles where rolname in ('app_rw','app_ro');"
```

**判定结论的三种走向**

| 结论 | 走 |
|---|---|
| PG 连不上 / 盘满 / 容器 Down | §3 步骤 2–3 |
| PG 活着但**连接数打满**（常见是 checkpoint 池把 metadata 池一起拖死，见 `app/repo/pools.py:11` 的同 DSN 分池理由） | **转 RL-3**，本条只做止血 |
| 表/权限/触发器不对（有人改了 GRANT 或迁移没跑） | §3 步骤 4，并**必须**上呈（fail-closed 被改坏 = 安全边界破了，不是运维小事） |

✅ **2026-09-19 真机读数**（本机 PG 在跑，`alembic_version = 0005`；上面 2.4–2.5 四条 SQL **逐条可执行**，无 SQLite 沙箱形态的豁免需要）：

| 检查 | 读数 | 判定 |
|---|---|---|
| 2.5 权限三元组 | `can_insert=t` / `can_update=f` / `can_delete=f` | ✅ N-09 的 append-only 边界**没被改坏** |
| 2.5 触发器 | `trg_audit_log_immutable`（`not tgisinternal` 过滤后只有这一条） | ✅ 在位 |
| 2.5 角色 `rolconfig` | `app_rw = {default_transaction_read_only=off}` · `app_ro = {default_transaction_read_only=on}` | ✅ 与上面第 78–79 行的两条判据一一对上，**没有混** |
| 2.4 表清单 | 6 个被查的名字里只存在 4 个：`audit_log` / `audit_log_supplement` / `cost_ledger` / `query_plan` | ⚠️ **`query_task` 与 `session` 在任何 schema 下都不存在**（按 `table_name` 全库搜 = 0 行）。本条判据**不依赖**这两张表（运行期会话确实可用，24 条请求打同一 session id 成功 ⇒ 会话面在 Redis/检查点侧），所以这里**只记录读数，不下"这是缺陷"的结论**。要定性归 W1B |

⇒ 与启动校验互证：`audit_log_append_only_enforced` 的 PASS detail 就是"INSERT ✅ / UPDATE ❌ / DELETE ❌ / TRUNCATE ❌ 且触发器在位"，与本表同一事实的两次独立读法。

---

## 3. 处置动作（按序；**这一步之后才谈重启**）

1. **确认这是设计行为，不是"服务坏了"**。§18.7 原文："该期间服务**按设计拒绝下发结果**（NFR-2.6）"。readiness `503` 已经在摘流量 —— **不要抢着重启 api 去"恢复服务"**，重启会把在途 SSE 全打断，而硬依赖仍然连不上，起来还是 503。
2. **恢复 DB 本体**（只动 DB，不动 api）：

   ```bash
   cd deploy
   docker compose up -d pg          # 容器不在跑时
   docker compose restart pgbouncer # 仅当确认走 6432 且它异常（现网 .env 未指向 pgbouncer，见 §5）
   ```
3. **连接数打满**：先列后杀，**不要盲杀**（`idle in transaction` 才是泄漏形态）：

   ```bash
   docker compose exec -T pg psql -U postgres -d ecom -c \
     "select pid, application_name, state, now()-xact_start as xact_age
        from pg_stat_activity where datname='ecom' and state='idle in transaction'
        order by xact_age desc;"
   # 确认清单无误后，逐个（不要 for-all）：
   docker compose exec -T pg psql -U postgres -d ecom -c "select pg_terminate_backend(<pid>);"
   ```
4. **迁移没跑 / 表缺**：

   ```bash
   # 迁移在**宿主**跑（走宿主映射 127.0.0.1:5432，不是服务名 pg），DSN 只在当前 shell 里导出
   export MIGRATION_DATABASE_URL='postgresql+psycopg://<属主>@127.0.0.1:5432/<库>'
   cd ../backend && ../.venv/Scripts/python.exe -m alembic upgrade head
   ```

   ⚠️ `MIGRATION_DATABASE_URL` 是迁移的**唯一** DSN 来源且**无默认值**（`app/repo/migrations/env.py:45-63`）。它**刻意不落进仓库树里的任何文件**（包括 gitignore 掉的 `deploy/.env`）—— `tests/unit/test_migration_dsn_hygiene.py` 扫的是整个工作区，属主级字面 DSN 一落地 DoD④ 就红；`.env.example` 也不能收，因为 `tests/contract/test_config_failfast.py` 要求它的键集与 `Settings.model_fields` 完全相等，而迁移 DSN 不是应用配置项。运行时角色 `app_rw` 刻意没有建表权限，所以这一步只能用属主/超级用户串。
5. **权限被改坏（分支 C 命中）**：只能沿迁移方向修回，**不许手工 GRANT 后了事**：

   ```bash
   # 读回迁移里的原始 GRANT 口径（唯一真相），据此判断是"少授了"还是"多授了"
   ../.venv/Scripts/python.exe -c "print(open('app/repo/migrations/versions/0001_roles_and_audit_append_only.py',encoding='utf-8').read())" | grep -n -i "grant\|revoke\|trigger"
   ```

   若必须临时收紧：`REVOKE UPDATE, DELETE ON audit_log FROM app_rw;` → **立刻补进迁移**，否则下一次全新部署又会漂回来。
6. **只有 DB 侧确认恢复后**，才让实例重新接流量。当前**不需要**重启就能恢复：readiness 探针是每次请求实时打 `SELECT 1`（`app/repo/health.py:107-111`），DB 一通它就转真，LB 自己会把流量放回来。**先验证 §4，验证不过再考虑重启。**
7. **确需重启时的唯一正确姿势**（§18.3；`api` 已有 `stop_grace_period: 40s`）：

   ```bash
   cd deploy
   docker compose ps                 # 确认无在途流；或看 http_requests_inflight（README §四-4）
   docker compose stop --timeout 45 api
   docker compose up -d api
   curl -sS http://127.0.0.1:8000/api/v1/healthz/ready; echo
   ```

   `api` 起来后 lifespan 会重跑 §18.4 的启动断言（`app/main.py:137`），DB 还没好就会 `startup_assertions_failed` 并**拒绝启动**（prod）或 503（非 prod）—— 这是预期，不要误当新故障。
8. **⛔ 禁止清单（这一条的红线）**：
   * **不得临时关闭 fail-closed**：`AuditWriter` 刻意**不提供** `strict=False` 之类的开关，其类 docstring 写明了理由（打开它等于制造"结果下发了、审计没记"的窗口，NFR-3.4 → N-09 失效）。
   * 不得给 `app_rw` 加 `UPDATE`/`DELETE` 来"让插入失败别再报"。
   * 不得 `docker kill` / `kill -9`（打断在途 SSE、丢段 2 审计）。
   * 不得把 `metadata_db` 从 `READINESS_DEPENDENCIES` 里摘掉（定义在 `app/core/enums.py`，W0 域，且是结构约束）。

**回滚**：本条的处置**全部是 DB 侧**，正常不需要回滚。若动过 `deploy/.env`：先备份再改（`cp .env .env.bak-$(date +%Y%m%d%H%M)`），回滚 = 还原该文件后 `docker compose stop --timeout 45 api && docker compose up -d api`。若跑过迁移且需要退：`../.venv/Scripts/python.exe -m alembic downgrade -1` —— **仅在已确认这一步就是根因时执行**，`0001` 涉及角色与触发器，来回倒腾比修错更危险。

---

## 4. 验证恢复

| 判据 | 怎么看 |
|---|---|
| 硬依赖全绿 | `curl -sS $BASE/healthz/ready` → **200**，`checks` 四项全 `true` |
| 聚合不再 unhealthy | `curl -sS $BASE/healthz` → 200，`status` 为 `ok`；若仍 `degraded` 且 `degraded_dependencies` 只含 `llm`/`embedding` → **那是正常的，转 RL-2/RL-4** |
| 段 1 真的落库了 | `docker compose exec -T pg psql -U postgres -d ecom -c "select count(*), max(created_at) from app.audit_log;"`（`UNVERIFIED`：列名以迁移 0001 为准） |
| 主链路通了 | 发一次真实 `/query`，能看到 `data` + `complete`（`data` 出现本身就是段 1 成功的证明，§12.4/§5.3.1 的时序） |
| 不再新增失败 | 近 5min 日志里 `audit_pre_failed` 的**条数为 0**（完整命令见表格下方；带管道的那行不要从表格里抄） |
| 5xx 回落 | `http_requests_total{status="5xx"}` 速率归零；`query_outcome_total{outcome="failed"}` 不再增长 |

```bash
cd deploy
# 「不再新增失败」的完整命令：期望输出 0
docker compose logs --since 5m api | grep -c audit_pre_failed
```

**观测位置**：探针 = `$BASE/healthz*`；日志 = `docker compose logs api`（JSON Lines，§15.1 字段契约）；指标 = `curl -sS $BASE/metrics`（**已注册**，走宿主映射 8000 直读；⚠️ 经 80 端口会被 nginx `location = /api/v1/metrics` **故意 404**，无宿主映射时改用容器内 `python -c urllib`，见 README §四-4）。
**⛔ 不得声称"自愈已闭环"**：liveness 无自动消费者（附录 A §A.8.2），DB 恢复后 readiness 会自己转真，但**进程级卡死只能人工处理**。

---

## 5. 升级 / 联系（归属见 08 §4.1）

| 议题 | 找谁 |
|---|---|
| 审计写入策略、fail-closed 语义、`obs/audit.py` | **W1B**（U-18 裁定落 `obs/audit.py`；`app/obs/audit.py` 实现归 W1B） |
| `app/repo/**`（`audit_store.py` / `pools.py` / `health.py`）、migrations、角色与 GRANT | **W1B** |
| 三探针语义、`/healthz` payload、`deploy/**`（compose 的 healthcheck / `stop_grace_period`） | **W7（本窗口）** |
| `error(INTERNAL)` 帧与 HTTP 映射、`/query` 端点行为 | **W4**（`app/api/errors.py`、`app/api/routers/**`） |
| §18.7 判据里的日志名 `audit_insert_failed` 与代码里的 `audit_pre_failed` 不一致 | **架构窗口**（改 §18.7 或改代码由它裁定）→ **待架构窗口分配编号** |
| `MIGRATION_DATABASE_URL` 未进 `.env.example` / 07 附-6 / 附录 D §D.4 | **W1B 提给架构窗口** → 待架构窗口分配编号 |
| 备份与恢复（每日全量 + WAL 归档、保留 30 天，§18.6） | **W7**（但**当前未落地**，属 §18.6 的待办） |
