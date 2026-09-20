# RL-3 · checkpoint 写入变慢

> 归属窗口：**W7** ｜ 日期：**2026-09-18**
> 依据：07 §18.7 第 3 行 · §16.3（连接池算数）· §5.5 · §15.3 · ADR-02 / ADR-15 · R-10 · N-14 · 附录 A §A.8.3
> 共用命令与端口约定见同目录 `README.md` §五。

---

## 0. 一句话定性

§18.7 判据原文：**「节点间耗时上升 + 池等待」→「检查 pgbouncer 与连接池；必要时降并发（kill switch）」**。
本条要在动手前先把两件事钉清楚：**(a) 现在的"等待"大概率不在池上而在锁上**；**(b) 现网 DSN 根本没走 pgbouncer**（见 §2.5）。

---

## 1. 触发信号（真实名字）

| 类型 | 信号 |
|---|---|
| 指标 | `stage_duration_seconds{stage=...}` 分位上升。**stage 只有 6 个契约值**：`intent` / `schema_linking` / `plan_ready` / `sql_ready` / `gate_passed` / `executing`（`app/core/enums.py:Stage`） |
| 指标 | `http_request_duration_seconds{endpoint="/api/v1/query"}` P95 上升；§15.4 的 **P95 > 15s（P1）** 告警，与 G-6/§16.5 的 **≤8s** 验收口径是**同一指标的两种线**，不要混 |
| 指标 | `http_requests_inflight{endpoint}` 不降（流被拖长）；`query_outcome_total{outcome="failed"}` 微升 |
| 探针 | `GET /api/v1/healthz/ready` 端到端变慢 → 503。⚠️ `ready` 的 `checks` 只是**布尔映射**（`app/api/routers/health.py:243`），**不含原因**；原因在 WARN 日志 `healthz_failed_probes` 的 `failed.checkpointer`（`probe_detail` 已从响应体移除），形如 `app=<application_name> lg 表族 <present>/<expected>`（`app/repo/health.py:166`） |
| 日志 | `checkpoint_schema_created`（`app/main.py:158`：**lg 表族不齐、跑了 `setup()`**，通常意味着新库或表被删）、`checkpoint_schema_check_skipped`（`app/main.py:164`：连不上，**没查**≠**本来就齐**） |
| 连带信号 | 同窗口出现 `audit_pre_failed` → **元数据池被 checkpoint 池拖死**（两条池**同 DSN** `DATABASE_URL`，靠分池隔离，`app/repo/pools.py:11` 明写这条风险）。此时**主故障是本条，但先按 RL-1 止血** |
| 告警（§15.4） | P95 延迟 > 15s / P1 |

> ⚠️ **记法约定（先看这条再抄指标名）**：下表里 `stage_duration_seconds{stage=...}` / `http_request_duration_seconds{endpoint=...}` 这种写法指代的是**指标族**，
> 而它们是**直方图** —— `/metrics` 实际导出的是 `_bucket` / `_count` / `_sum` 三条，**裸名选择器返回 0 条序列**（2026-09-19 经真 Prometheus 实测）。
> ⇒ 排查时**不要**直接 curl/查询裸名；分位数的可抄表达式见 §4「验证恢复」。

> ⚠️ **「图节点耗时」这个指标在本仓库不存在**。§15.3 给了一行「图节点耗时 Histogram `node`(≤20)」，而 `app/obs/metrics.py` 注册的是 `STAGE_DURATION_SECONDS`（`stage_duration_seconds{stage}`），其 help 明文写着「⚠️ **不是** §15.3 的『图节点耗时』：节点名不进 SSE（06 D2 红线），节点级直方图待 `app/graph` 的观测钩子（见 RELAY 上呈）」。→ 本条**只能用 stage 口径判定**，"节点间耗时"在指标层面**判不了**（不一致已登记，待架构窗口分配编号）。
> ⚠️ **「池等待」同样没有指标**：`metrics.py` 里没有池等待/池占用的任何 Counter。只有 `llm_upstream_concurrency`（那是 LLM 信号量，不是 DB 池）。→ 池与锁的等待只能从 **PG 侧 + 日志时间差** 反推（§2.2、§2.3）。

---

## 2. 判定

### 2.1 先分辨「慢」还是「假」（探针 + 一次端到端）

```bash
BASE=http://127.0.0.1:8000/api/v1
time curl -sS "$BASE/healthz/ready"; echo            # 慢/503 都记下来；probe 本身要打一次连接
curl -sS "$BASE/healthz" -o /tmp/hz.json -w '%{time_total}\n'   # 第二条：aggregate，别拿它做编排探针
cd deploy && docker compose logs --since 10m api | grep healthz_failed_probes | tail -3   # 原因在整行的 `failed` 字段里；checks 只有 true/false
```

⚠️ 读法：`app/repo/pools.py:181-182` 记的是**修复前的实测基线** ——「`probe_checkpointer()` → `pool.connection()` = **30s**，`/healthz/ready` 端到端实测 **35.8s**」（`psycopg_pool` 默认 `timeout=30s` 是为业务借用设计的，用在探针上会反向）。现在两处都收口了：探针取连接的预算 `POOL_ACQUIRE_TIMEOUT_S = 2.0`（`app/repo/pools.py:201`，推导 = 5s ÷ 3 硬依赖），且 `_collect` **已改为并发**（`app/api/routers/health.py` 的 `asyncio.gather`，上界从"各依赖之**和**"变成"最慢的**一个**"）⇒ 附录 D 的 5s 预算在**结构上**成立。⚠️ **未在起栈下复测**（本窗口没跑过真实 `/healthz/ready` 计时）⇒ 若仍观察到 >5s，先怀疑探针之外的东西（DNS `getaddrinfo` 在 Windows 上的失败代价就有 5.8s，见 W1B 转交记录），而不是直接归给 checkpoint。
结论：**ready 慢 / ready 超时 ≠ 图慢**，它可能只是在等一条池里的连接（`pools.py` 自己的注释就写着"每次探针要占住一个 worker 达 30s —— 健康端点自己成了可用性风险"）。**这一步不做完就把"慢"归给 checkpoint，是这条 runbook 最容易犯的错。**

> 口径差（登记，**已缩小**）：`app/repo/pools.py:173,191` 按"3 个硬依赖"推导 `2.0s = 5s ÷ 3`，而 `/healthz/ready` 实际取的是 `READINESS_DEPENDENCIES` = 全部 **4 个** HARD（含 `semantic_bundle_loaded`）。该推导之所以原来会破预算，是因为 `_collect` 串行（和 = 4×2s=8s > 5s）；**并行化现已落地** ⇒ 上界变成"最慢的一个"（≈2s），**结构上不再依赖那个 3/4 之差**。剩下的只有两点：① `pools.py` 注释里的"÷3"字样与实际 4 个硬依赖不一致（属注释文案，归 W1B）；② `UNVERIFIED`：**并行化之后本窗口没有实测收敛的 `/healthz/ready` 端到端耗时**。

### 2.2 PG 侧看连接与归因（`application_name` 是唯一归因把手）

```bash
cd deploy
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select application_name, state, wait_event_type, wait_event, count(*)
     from pg_stat_activity where datname='ecom'
    group by 1,2,3,4 order by count(*) desc;"
# 三条池的 application_name 由 app/repo/pools.py 写死，checkpoint 池 = commerceql-checkpoint
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select name, setting from pg_settings where name in ('max_connections','idle_session_timeout');"
```

判读：`commerceql-checkpoint` 的行数**长期等于 1 且 state='idle in transaction'** → 单 saver 串行（§2.3 的锁）；行数**逼近池上限** → 池不够（§2.5）。

### 2.3 分辨「锁等待」还是「池等待」——**这一步决定要不要动配置**

`app/repo/pools.py` 与 `scripts/probe_checkpoint_pool.py` 头部（W1B 实测，读 `langgraph-checkpoint-postgres 3.1.2` 源码得到）钉了三条事实：

| # | 事实 | 对本故障的意义 |
|---|---|---|
| 1 | `AsyncPostgresSaver` 的 `_cursor()` 短持/长持**由构造入参决定**：给 `AsyncConnectionPool` → 每次操作借还；给单条 `AsyncConnection` → 整个 saver 生命周期长持 | 当前装配是 `CheckpointStrategy.SINGLE_SAVER_SHARED_POOL`（`app/main.py:180-195`）→ **短持 + 共享池** |
| 2 | `self.lock = asyncio.Lock()`：**每个 saver 实例一把锁，串行化它自己的全部检查点 I/O** | ⚠️ 单 saver 的检查点吞吐上限 = **同时刻 1 个操作**。**池再大，等待也发生在锁上，不发生在池上** |
| 3 | saver 绑定创建它的 loop | 任何"顺手把 saver 提全局"的改法都会炸 |

→ **判据**：若 `stage_duration_seconds` 各段都在涨、但 §2.2 里 `commerceql-checkpoint` 的**并发连接数一直是 1**，那就是**锁串行**，**扩池、改 pgbouncer 都无效**（这是 §18.7 那行"检查 pgbouncer 与连接池"在本实现下**不成立**的情形）。

### 2.4 `lg` 表族与膨胀

⚠️ **表名不是 `lg_*` 前缀，而是 schema `lg` 下的四张表**：`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations`。唯一清单 = `app/repo/health.py:65-70` 的 `CHECKPOINT_TABLE_FAMILY`（注释自述是"本机跑完 `setup()` 后读 `pg_class` 实测得来"）；schema 名 = `app/repo/pools.py:107` 的 `CHECKPOINT_SCHEMA = "lg"`，与迁移 `0001` 里的 `CREATE SCHEMA lg` 是同一事实的两处。readiness 探针 `detail` 里的 `lg 表族 <present>/<expected>` 数的就是这四张（`expected` 恒为 4）。

```bash
cd deploy
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select schemaname, relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
     from pg_stat_user_tables where schemaname='lg' order by n_dead_tup desc;"
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select c.relname, pg_size_pretty(pg_total_relation_size(c.oid)) as total
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname='lg' and c.relkind='r'
    order by pg_total_relation_size(c.oid) desc;"
```

✅ **2026-09-19 本机已核过**（`setup()` 由 `langgraph-checkpoint-postgres` 内部建，实测结果如下）。四张表：

| 表 | 行数 | 含索引总大小 |
|---|---|---|
| `lg.checkpoints` | 5,086 | 9,216 kB |
| `lg.checkpoint_writes` | 16,305 | 6,648 kB |
| `lg.checkpoint_blobs` | 4,619 | 2,032 kB |
| `lg.checkpoint_migrations` | 0 | 24 kB |

索引共 **7 条**：三张业务表各一个 `*_pkey`、一个 `*_thread_id_idx`（`checkpoints_thread_id_idx` / `checkpoint_writes_thread_id_idx` / `checkpoint_blobs_thread_id_idx`），加 `checkpoint_migrations_pkey`。**没有**额外的手工二级索引 ⇒ 按 `thread_id` 查是走索引的，不必怀疑"缺索引"。

⚠️ 这组读数是**基线快照**，不是"膨胀已发生"的证据。判膨胀要比**同一实例的前后两次**读数；`pg_stat_user_tables` 的计数在容器重建/`truncate` 后会归零，所以"看起来很小"不能读成"没有写放大"。清理口径仍未实现：`CHECKPOINT_TTL_DAYS=7`（`deploy/.env:142`）**没有任何清理任务读它**（上呈见 §5）。

### 2.5 pgbouncer —— 已确认：**不在链路上，而且当前根本进不来**

```bash
cd deploy && grep -n "DATABASE_URL\|ANALYTICS_DB_URL\|6432" .env
```

现网 `deploy/.env` 两条 DSN 都指向 **`pg:5432`**。→ §18.7 的"检查 pgbouncer 与连接池"在**当前配置下不是本故障的第一现场**（文档与配置不一致，待架构窗口分配编号）。

**2026-09-19 实测（把这一节从"推断"升级成"实证"）**：

| 项 | 实测 |
|---|---|
| 镜像有没有 `psql` | ✅ **有**（`/usr/bin/psql`）⇒ 旧版这里写的 `UNVERIFIED` 不再成立 |
| 旧命令能否直接跑 | ❌ **不能**：不带口令 → `fe_sendauth: no password supplied`。可执行版见下 |
| 管理口 | ✅ `SHOW POOLS` 可查（`admin_users = postgres`） |
| 监听端口 | 镜像自动生成的 `pgbouncer.ini` 里 `listen_port = 6432` —— 这要等 `LISTEN_PORT: "6432"` 显式设进 compose 之后才成立。⚠️ **该镜像默认监听 5432**，compose 原先 `6432:6432` 映射的是一个**没人监听**的端口 ⇒ 这个服务从建好起就从未可用过（"已定义"≠"能用"） |
| 认证方式 | ✅ **已解，且零安全代价**（订正本目录先前那版"三选一出路"）：pgbouncer 的合法取值是 **`scram-sha-256`**（1.14+ 原生支持），先前记的"`scram` 非法 ⇒ 只能退回 md5 / userlist / trust"是**我把字面值写错了**，不是架构冲突。改 `deploy/docker-compose.yml` 一行 `AUTH_TYPE: "scram-sha-256"` 后，本轮用 `app_rw`（0001 迁移按 PG 默认 `password_encryption=scram-sha-256` 建的角色）实测：**`conn ok, current_user=app_rw`** |
| **断言③ 现在可判** | `SHOW POOLS` 不再只有管理池 —— 实测出现 `db=ecom user=app_rw`（`sv_idle=1`）⇒ **§16.5 断言③ 从"不可测"变成"可判"**。⚠️ 两个读数前提：① 管理台要**用 `autocommit=True` 连 `pgbouncer` 库**，否则 `BEGIN` 被拒（`SHOW POOLS` 会失败）；② 现在这一池是**探针连出来的**，应用 DSN 仍指 `pg:5432` ⇒ 要拿"生产并发下 ≤30"的数，仍要先裁"应用到底该不该过 pgbouncer"（见下一行的 transaction/`SET LOCAL` 冲突） |
| **流量证据** | 两个时点要分开读：**认证修好之前** `SHOW POOLS` 只有 pgbouncer 自用管理池那一行（探针也连不上，所以没有 `ecom` 的池）；**之后**才有 `db=ecom user=app_rw`，而那一条是本轮**探针**连出来的。⇒ "生产应用流量不经 pgbouncer"仍然成立，依据换成：`.env` 两条 DSN 都指 `pg:5432` + 四场景压测期间池表里除管理池外没有任何 `ecom` 池 |

```bash
# 可执行版（口令是 compose 里明文写的开发默认值，不是秘密）
cd deploy
docker compose exec -e PGPASSWORD=postgres pgbouncer \
  psql -h 127.0.0.1 -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;"
docker compose exec pgbouncer cat /etc/pgbouncer/pgbouncer.ini   # 核对 auth_type / listen_port / pool_mode
```

⚠️ **不要顺手把 DSN 改成 6432**。认证这一关**已经不是障碍**（`scram-sha-256` 已解），剩下的是真正的那笔账：
`transaction` 池模式与 `SET LOCAL` 身份传递（ADR-09）、以及 checkpoint 若变长持连接（R-10）三者互不兼容 ——
07 §16.3 风险 1 与 `probe_checkpoint_pool.py` 头部都点过。改它属配置决策，需 W7 + 架构确认。

⇒ **§16.5 断言 ③（pgbouncer 后端连接 ≤30）现在可判**（先前记的"链路不通、分母为空"已随 `AUTH_TYPE` 订正失效）。
⚠️ 但**"可判"≠"已有生产读数"**：要拿这个数，前提是应用 DSN 真的走 6432，而那件事卡在
`transaction` 池模式与 `SET LOCAL` 身份传递（ADR-09）的冲突上，**尚未裁决**（见上一行与 `RELAY.md`）。
本轮四场景期间的读数是 `sv_active=0`（没有生产连接走它）—— 那是"没接"，不是"接了但没超"。

---

## 3. 处置动作（按"先不砍纪律、再不动配置、最后才重启"排序）

1. **降并发（首选，且不重启）**。§18.7 原文给的手段是「必要时降并发（kill switch）」—— **当前仓库没有 kill switch**：`app/core/config.py` 字段全表里**没有**任何降级/禁用开关，§14.2 G3 的"全局禁用开关 → `refuse(reason=no_data_asset)`"路径未接线。现实可执行的等效手段只有：

   ```bash
   cd deploy
   docker compose stop web        # 只停前端：挡住新会话，api 与在途 SSE 都不动，探针继续可查
   ```

   * ⛔ **不得** `docker compose stop api`（那是摘流量的对立面：会打断在途流、并让探针消失）。
   * ⛔ **不得** `docker kill` / `kill -9`（§18.3；见 README §三-2）。
   * `recursion_limit=25` 是**图侧**的 NFR-2.4 kill switch（`app/graph/build.py:80`），它不是运维降并发旋钮，**不要为了降并发去调它** —— 调小会把正常多轮查询变成 `error(INTERNAL)`（§14.2 G4）。
   * "kill switch / 全局降级开关缺实现"→ **待架构窗口分配编号**。
2. **确认是锁串行而不是池不足**（§2.3 结论）→ **不要扩池、不要改 pgbouncer**；把它当成容量结论上报，走 §16.6 的扩展路径（加 api 实例的前提是"LLM 信号量先改 Redis 令牌桶"，§18.1，单机 Compose 下无横向扩展需求）。
3. **确认是 `lg` 表膨胀**（§2.4，`n_dead_tup` 高）：业务低峰做**不锁表**的整理，`CONCURRENTLY` 必须单独一条执行：

   ```bash
   cd deploy
   # 四张表逐条来，不要一把 VACUUM FULL（FULL 持 ACCESS EXCLUSIVE，等于停写）
   for t in checkpoints checkpoint_blobs checkpoint_writes checkpoint_migrations; do
     docker compose exec -T pg psql -U postgres -d ecom -c "VACUUM (ANALYZE) lg.$t;"
   done
   # 索引重建只在确认索引膨胀时做；索引名先查再动：
   #   select indexname from pg_indexes where schemaname='lg';
   #   REINDEX INDEX CONCURRENTLY lg.<索引名>;   -- 逐条
   ```

   ⚠️ 不要对 `lg` 表族做 `CLUSTER` / `TRUNCATE` / `VACUUM FULL`；历史检查点靠 `CHECKPOINT_TTL_DAYS=7` 的口径清理，**清理任务的实现归属尚未在代码中找到** → 待架构窗口分配编号。
4. **确认是池不足**（§2.2：某 `application_name` 行数长期顶到上限）→ 先查**是谁没还**：`idle in transaction` 的会话按 RL-1 §3-3 逐个 `pg_terminate_backend`。**改池大小本身属 `app/repo/pools.py`（W1B 域），运维不得自改。**
5. **若同时出现 `audit_pre_failed`**：说明审计写不进去，主链路已经在 fail-closed 拒发结果。按 **RL-1** 处置（并记住两条池同 DSN，`pools.py:11`）。
6. **重启是最后一步，且只在完成 1–5 且确认无在途流后**：

   ```bash
   cd deploy
   curl -sS http://127.0.0.1:8000/api/v1/healthz/live; echo   # 先确认进程活着、看 uptime_s 是否刚被重启过
   docker compose stop --timeout 45 api && docker compose up -d api
   ```

   `--timeout 45` > `stop_grace_period: 40s` > §18.3 的 drain 30s，三者要对齐。
   ⚠️ **drain 的 shell 侧已实装并实测（桩），但真实链路未测**（README §四-2）：`deploy/entrypoint.sh` 收到 TERM 会先 `POST /healthz/drain` ⇒ `begin_drain()` 让 `/healthz/ready` **立刻** 503（摘流量）→ `drain()` 等在途 SSE ≤30s（`DRAIN_TIMEOUT_S`）→ 仍未终态的流由 `ObservingMiddleware` 在下一次 `send` 注入 `error(INTERNAL, message="服务重启中，请重试", terminal:true)`；lifespan 关闭段还有第二道同样的锁作兜底。**三个前提要记住**：① `DRAIN_TOKEN` 未设时 drain 端点 **403 fail-closed**（启动日志会吵 `drain_trigger_unavailable`），此时只剩 uvicorn `--timeout-graceful-shutdown 5` 的 5s（桩实测：这条路径**不会卡死**，仍会转发 TERM 并在 2s 内退出）；② 桩实测覆盖的是"顺序对不对、预算耗尽还退不退"，**没有覆盖**真实 `app.main:app` 上真实 SSE 客户端能否收到终止帧 ⇒ **仍挑空载时点**；③ 停机后 `docker ps -a` 会显示 **`Exited (143)`，这是正常产物**（dash 在 trap 之后取不到服务进程的真实退出码，见 README §四-2），**只有 `Exited (137)` 才是"被 SIGKILL、有流被硬断"**。

**回滚**：本条的正常处置不写配置，因此回滚面只在 ① `docker compose stop web` → `docker compose start web`；② 若为诊断改过 `.env`（DSN/池相关），改前 `cp .env .env.bak-<时间戳>`，回滚 = 覆盖还原 + 按 §3-6 的姿势重启 api 生效。任何"为了让 P95 好看而调 `EXEC_STATEMENT_TIMEOUT_MS` / `LLM_TIMEOUT_SECONDS`"的改动**一律视为未授权**：它改变的是查询语义与超时契约，不是运维参数。

---

## 4. 验证恢复

| 判据 | 怎么看 |
|---|---|
| 阶段耗时回到基线 | ⚠️ 同样是直方图，**裸名查不到**：用 `histogram_quantile(0.95, sum by (le, stage) (rate(stage_duration_seconds_bucket[$__rate_interval])))`（宿主 curl 场景把 `$__rate_interval` 换成 `5m`）按 `stage` 分组看分位回落；重点看 `executing`（含检查点写入的那段）与 `plan_ready`。`stage_duration_seconds_count{stage="executing"}` 为 **0** 的意思不是"快"，是**根本没有查询走到执行**（本轮 09-19 就是这个形态，见 `压测报告.md` §四 R4） |
| P95 达标 | ⚠️ **别照抄裸名**：`http_request_duration_seconds` 这个族在 `/metrics` 里**不存在**（直方图只导出 `_bucket` / `_count` / `_sum` 三条；2026-09-19 实测裸选择器返回 **0 条序列** ⇒ 照着查会看成"没有慢请求"）。正确写法：`histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{endpoint="/api/v1/query"}[5m])))` ⇒ **P95 ≤ 8s**（§16.5 断言④ / G-6），告警线 >15s（§15.4）。两条读法坑：① 该族带 `endpoint` 且无声明域 ⇒ **冷启动整族不输出**，要出现过请求才有数；② 窗口内样本太少时 `histogram_quantile` 返回 **NaN**（实测：刚起 3 个请求即 NaN），**NaN 不是 0、也不是"达标"** |
| 探针快且绿 | `time curl $BASE/healthz/ready` 明显低于 §2.1 记下的基线，且 200、`checks` 四项全 true |
| 连接归位 | `pg_stat_activity` 里 `commerceql-checkpoint` 的行数回到预期区间，无长期 `idle in transaction` |
| 断言未破 | 近 5min 日志里 `checkpoint_schema_created` 与 `audit_pre_failed` **都不出现**（完整命令见表格下方） |
| 在途流清空 | `http_requests_inflight` 归零。**`/metrics` 已注册**（README §五命令约定）：宿主 `curl -sS "$BASE/metrics"`（8000 直读；经 80 会被 nginx 故意 404），拿不到宿主映射时在 api 容器内用 `python -c "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8000/api/v1/metrics').read().decode())"`（镜像无 curl），再在返回全文里筛 `http_requests_inflight{` 开头的行。⚠️ 该族标签 `endpoint` **无取值域** ⇒ 属"整族不输出"型：冷启动**没有这条线 = 还没有过请求**，不等于"已排空"；排空的判据是**出现过、且当前值为 0**。辅证用 `docker compose logs` 与 nginx 活动连接数。**2026-09-19 两端都实测过**：新起容器查 `http_requests_inflight` 返回 0 条序列（= 还没有过请求），发 3 个请求后该族出现且值回到 0 ⇒ 这条判据是**可执行**的，不是纸面推断 |

```bash
cd deploy
# 「断言未破」的完整命令（管道放这里，别在表格里抄）：期望输出 0
docker compose logs --since 5m api | grep -Ec 'checkpoint_schema_created|audit_pre_failed'
#     非 0 时再分辨是哪一种：checkpoint_schema_created = lg 表族不齐（本条）；
#     audit_pre_failed = 段 1 审计写不进去 → 转 RL-1
```

**压测复现口径（§16.5）**：确认修复要按**四场景**跑 —— ① 稳态 50 并发 10min ② 突发 100 并发 30s ③ 单会话并发（验串行锁）④ 同租户并发（验配额），数据用**合成数据集全量**（**不得用缩小数据集压测**，否则连接池与慢查询都不暴露）。必测断言：① **无 checkpoint 写入等待**（R-10）② `SET LOCAL` 在连接复用时正确复位 ③ pgbouncer 后端连接 ≤30 ④ P95 ≤ 8s。
✅ **已跑（2026-09-19，W7）**：四场景按 §16.5 口径执行完毕 —— 被测面是当前源码树构建的**独立容器** `w7load-api`（宿主 18000），数据是**合成数据集全量 1,940,300 行**（`deploy/loadtest/load_synth_to_pg.py` 灌入），题库是冻结集里 `eval_tenant=T_A` 的 **155 条**问句。
落点：**`deploy/loadtest/README.md`**（方案、断言口径、复现命令）与 **`backend/reports/w7/压测报告.md`**（读数与判读），回执 JSON 在 `deploy/loadtest/receipt_*.json`。

四条必测断言的当前状态（**别把"跑过了"读成"判据成立了"**）：

| 断言 | 状态 | 为什么 |
|---|---|---|
| ① 无 checkpoint 写入等待（R-10） | ⚪ **不可观察** | 本轮 0 次执行（`stage_duration_seconds_count{executing}=0`）⇒ 没有写入可等。`lg.checkpoints` 确有 4,200 行（图状态在写），但那不是分析查询的等待面 |
| ② `SET LOCAL` 连接复用时正确复位 | ⚪ **不可观察** | 同因：需要真查询流量穿过 `app_rw` 身份传递路径。离线契约测试通过 ≠ 负载下成立 |
| ③ pgbouncer 后端连接 ≤30 | ⚪ **不可判** | 链路本身不通（§2.5：镜像 `auth_type=md5` vs W1B 角色的 SCRAM 口令），分母为空 |
| ④ P95 ≤ 8s | ⚠️ **跑出来了但不可判达标** | 50 / 100 并发下 `complete` 帧 **0 条** ⇒ P95（6.19s / 7.27s）的分母全是失败样本。**必须与 `outcomes` 同读** |

运维口径两条：① 要演练停机或压测，**用 `w7load-api`，不要动 `commerceql-api-1`**（W6 在用；重启会打断它的在途 SSE 流）。② 压测结果与评测结果**分开归档**（PRD §13.5）—— 上面的报告全文没有任何准确率结论。

---

## 5. 升级 / 联系（归属见 08 §4.1）

| 议题 | 找谁 |
|---|---|
| 三池构造与大小、`application_name`、checkpoint 池超时、`app/repo/**` + migrations | **W1B** |
| `T-A1` 的结论（短持/长持、四装配臂）、`scripts/probe_checkpoint_pool.py` | **W1B** |
| 图装配策略 `CheckpointStrategy.*`、`ensure_checkpoint_schema`、`recursion_limit` | **W4**（`app/graph/**`） |
| `stage_duration_seconds` 本体、节点级直方图缺口、`/metrics` 导出、`deploy/**` | **W7（本窗口）** |
| §18.7 判据"节点间耗时 + 池等待"缺对应指标；"检查 pgbouncer"与 `.env` 不走 6432 冲突；kill switch 无字段；`CHECKPOINT_TTL_DAYS` 无清理实现 | **架构窗口** → **待架构窗口分配编号** |
| 压测方案与结果归档（G-6 判定输入） | **W7 产出 → 交 W6 引用** |
