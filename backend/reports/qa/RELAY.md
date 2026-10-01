# 验收窗口（QA）· RELAY

> 本窗唯一写者 = QA 窗（自本文件第一次提交起，W7 转只读）。只追加、不改历史文本；订正写在最新段并 🔻 具名失效。
> 纪律：不落题面、不落 SQL 文本、不落结果数据行；报告里不写完整 DSN 形态（`tests/unit/test_migration_dsn_hygiene.py` 扫整工作区）。

## §一 第一轮（2026-10-01 21:45–22:05 +0800 ｜ HEAD `fd5f5f2` ｜ 零写盘之外的实现改动、零额度、零跑批）

### 1. 开工五查（全部现测）

| # | 查项 | 实测读数 | 判定 |
|---|---|---|---|
| 1 | 本地与远端同点 | `git rev-parse --short HEAD` = `fd5f5f2`；`git ls-remote origin main` = `fd5f5f2d9142156f016975efaf135440c7a58f21` ⇒ **同点** | 通过 |
| 1b | 工作副本 | `git status --porcelain` = **4 行**：`M backend/reports/w1b/RELAY.md`、`?? reports/w6/_full_pytest_0929.rev`、`?? backend/生成：2026-09-16`、`?? eval/results_replay_probe.json` ⇒ **均非本窗件，本窗一律未动**（不 add、不 stash、不 checkout） | 登记 |
| 2 | `docs/07` 盘上态 | **v1.7.17** ／ `wc -l` **3,635** ／ 761,067 字节 ／ mtime 10-01 20:22；§4.8 起 **:1072**；登记表最后一行 **`U-132` @ :1160**；取号锚点行首形状 `^> \*\*下一个可用号 =` 命中 **1 行** = **:1077「下一个可用号 = `U-133`」**（裸串 `下一个可用号 =` 命中 **4 行** ⇒ 不可裸用） | 通过（未取号） |
| 3 | 门禁基线 | 见 `GATE_LOG.md` 第一轮六行：全树 **2,284 passed / 6 skipped / 10 errors / 89.97 s / 真 rc=1**；ruff backend **0 条 rc=0**；ruff `deploy/loadtest` **18 条 rc=1**；mypy **147 files Success rc=0**；lint-imports **4 kept 0 broken rc=0**（192 files / 1,069 deps）；`python -m app.core.enums` **rc=0**（33 项基数，`ast_rule` 20、`error_code` 28） | 复现（与 W7 `47bfdd2` 的 18 条同形） |
| 4 | 共享栈 | `commerceql-pg-1 / redis-1 / api-1 / pgbouncer-1` **Up 9 h**（api/redis/pg 带 healthy）；**被测构建镜像 = `w7load-api:0930r11`（imgID `8c1eb47fb118`，22 h 前，基准 `9998de1`）当前无常驻容器**；残留容器 `w7load-api_pre0930r11_bak` 的 `Config.Image` = **`w7load-api:0928r10`（pre-fix，容器 created 2026-09-28T13:39:34Z）** ⇒ 容器名与镜像内容**反着长**；`commerceql-api-1` 镜像 built **2026-09-18** ⇒ **不是被测构建** | 登记（见 F-9） |
| 5 | 花钱口径 | `app.cost_ledger`（面 = 全库、粒度 = 行）= **1,601 行 / ¥2.635700 / max `created_at` 2026-10-01 12:56:32Z（北京 20:56）**；与 W7 `47bfdd2` 落档值**逐字相同** ⇒ 本项目 20:56 后零新增花费；**本窗本轮零花费**（未跑任何打 LLM 的东西，双向自证 = 台账当场未涨） | 通过 |
| 6 | 本机 U-132 | `platform.machine()` 计时 = **0.09 s** ⇒ 本轮门禁数字**不需要**注明 shim 前提 | 通过 |

### 2. 本轮新发现的缺口（每条都是本窗现测，非转述）

- **F-1｜落地定义第 3 条少两条闸门。** `docs/07:3263–3275`（§17.3）= **G-1…G-8**；`04 C.8`（`docs/04:313–323`）只有 **G-1…G-7**；G-8 出自 PRD `docs/01:1622`。`OVERVIEW.md:159–164` 已按 **8 条**判：`PASS 0/8 = G-1 FAIL · G-2 FAIL · G-3 PARTIAL · G-4 PARTIAL · G-5 FAIL · G-6 UNVERIFIED · G-7 FAIL · G-8 UNVERIFIED`。**本窗默认决策**：一律按权威件（§17.3 的 8 条）执行；差异作为上呈件交架构与上游（`04` 属 PRD 窗，`08 §4.2:315`）。
- **F-2｜落地定义第 2 条的出处与个数都错。** `docs/04` 全文**无「压测」「四场景」字样**（"场景"仅 6 次命中）；压测场景在 `docs/07:3156`，**是 5 个**（稳态 50 并发／突发 100 并发／单会话并发验串行锁／同租户并发验配额／单租户饱和），同节 `docs/07:3159` **必测断言 = 6 条**（第 ⑥ 条 = v1.7.5 为 `U-130` 追加的入账完整性）。**本窗默认决策**：按 5 场景 + 6 断言建表。
- **F-3｜`U-114` 残余面今日仍在运行，且"保护"不是守卫（P0 面）。** `backend/tests/integration/test_retrieval_fts_pg.py:69` 的形状 = `TEST_DSN = os.environ.get("RETRIEVAL_TEST_PG_DSN") or PROD_DSN`，而 `PROD_DSN` 由 `:57 _dsn_from_env_file()` 从 `deploy/.env` 取（本窗只取派生段：用户段 = `app_rw`、主机段 = `pg` 被代码改写为 `127.0.0.1`；**未打印口令**）。⇒ 夹具 `dense_table`（module 级，`:385`）在**共享 `ecom`** 上执行 `CREATE SCHEMA` / `DROP TABLE`，被 `psycopg.errors.InsufficientPrivilege: permission denied for database ecom` 挡住 —— **挡住它的是角色权限，不是任何断言**。后果 = **3 条 setup error + 6 条 skip**。该残余面已由架构登记在 `docs/07:1133`（U-114）行末并派 W2B + W0 合批 ⇒ 本窗**不取号**，只开任务单 T-02。
- **F-4｜`G-1` 的判定把"环境未备"算成 FAIL。** `eval/gates.py:26` 词表**已有** `NOT_AVAILABLE`（`:12` 定义 = 输入根本没拿到），但 `G-1` 走 `:189` 的分支把 10 条 error 计入红。实测拆分：**7 条 = `U-114` 防线① 按设计 fail**（缺 `COMMERCEQL_TEST_RW_DSN` / `_SUPER_DSN`，代码明写"禁止 skip"），**3 条 = F-3 的权限不足**；两者都**不是用例真红**。CI 侧 `.github/workflows/ci.yml:123–128` 四个 DSN 全给 ⇒ **这是本机/离线口径缺口，不是 CI 缺口**。⇒ 单 T-04（归 W6，`eval/**` 属主见 `08:302`）。
- **F-5｜运行中的栈 ≠ 盘上 compose ⇒ 落地定义第 4 条不成立。** `deploy/docker-compose.yml` 定义 **8 个服务**（pg :53／pgbouncer :75／redis :114／api :128／web :183／worker :201／prometheus :222／grafana :246），worker 在 profile `async`（:209）、prometheus 与 grafana 在 profile `observability`（:224 / :248）；实际容器只有 **4 个**，且 **`web` 无 profile 却无容器** ⇒ 现行 compose 从未在这台机器完整起过。**本窗默认决策**：**不重启共享栈**（挤占所有窗 + 撞名单写者）；改要 W7 交「清单级可复现」证据（`compose config` 全 profile 展开，零额度、零容器），运行级复现列为待总控批的延后项。落地定义第 4 条本轮记 **部分（清单级未验、运行级未验）**。
- **F-6｜文档面与盘上面不一致（§8 第 5 条三处同源）。** `docs/05_附录D_环境依赖与部署清单.md` 全文 `grafana` 与 `prometheus` **0 命中**（本窗自查 `grep -ic`），而 compose 有这两个服务 ⇒ 观测栈**只活在代码里、不在部署清单里**。`docs/01–05` 归 **PRD 窗**（`08 §4.2:315`）⇒ 本窗只登记，转由总控走上游。
- **F-7｜记忆/交接件里的「7 条收集期中断」已过期。** 本窗实测 = **10 errors**（7 条收集期 + 3 条 setup）。⇒ 该句今后**必须带 HEAD 与尺**；本窗 🔻 具名失效：不再引用「7 条」作为当期读数。
- **F-8｜`w1b/RELAY.md` 的 §14／§15／§16（+157 行）未入库。** 子件读数（`git diff` 与 arch `RELAY.md:1714` 现测一致）：含一条「`session` 表从未建 ⇒ 同租户跨属主复用会话 fail-open」**明写未开号、请总控派单**，以及一条「推理侧改判为结构性无通道、我不同意花那 ¥0.03」。**本窗默认决策**：未入库 = 只有转述力、没有证据力 ⇒ 相关项在 `COMPLETENESS.md` 记 `UNVERIFIED`，并开 T-01 催 W1B 自己入库（本窗不代提交）。
- **F-9｜容器命名反直觉且会误导下一轮。** `w7load-api_pre0930r11_bak` 装的是 **`0928r10`（pre-fix）**，名字读起来像"0930r11 的备份"。⇒ 本窗在并发/串行表把它标为**禁借用的陈旧镜像位**，并请 W7 在 `deploy/loadtest/README.md` 里逐对象标面（这也是 arch 已欠 W7 的一格）。
- **F-10｜`08 §4.1` 至今没有 `tests/integration/**` 归属行。** 现读：表内只有 `tests/unit/**`（随被测模块）、`tests/contract / graph_snapshot / redteam`（W4）；`grep -n "tests/integration" docs/08` = **2 处均为正文提述、无归属行** ⇒ `U-114` 行末那条"上游回填请求"**未落**。归架构（`08` 属主，`08 §4.2:317`）。

### 3. 本窗自曝与撤回

- 🔻 我一开始准备按记忆写「收集期中断 7 条」，**现测为 10 errors** ⇒ 上一条 F-7 为准，旧句作废（记忆件是史料，不是当期读数）。
- 本轮的 U-xx 状态表初稿由只读取证子件产出，**其中 25 号未经本窗复核** ⇒ 在 `QA_LEDGER.md` 标 `DRAFT`，引用前必须换成实测值（本窗已自验 `U-114`／`U-121`／`U-129`／`U-131` 四号的行末原文）。
- 本轮**未写实现、未改配置、未动 `docs/**`、未起容器、未跑任何集成测试或 alembic 套件**。
