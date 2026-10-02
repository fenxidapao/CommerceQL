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

## §二 第二轮（2026-10-02 16:56 +0800 ｜ HEAD `d440ed6` ｜ 七份回执复算 ｜ 零开发、零额度、零容器起停）

### 1. 五查随动（环境已漂，全部重测）

| 查项 | 第一轮 → 本轮实测 |
|---|---|
| HEAD／远端 | `fd5f5f2` → **`d440ed6`**，`git ls-remote origin main` = `d440ed65364de…` ⇒ **同点**；本窗提交 `8375391` 在链上且**只有一笔**（无重复提交） |
| 工作副本 | 4 行 → **3 行**（`w1b/RELAY.md` 已由 W1B 自行入库）；剩余未跟踪 = `reports/w6/_full_pytest_0929.rev`、`backend/生成：2026-09-16`、`eval/results_replay_probe.json`（**均未跟踪、无 ignore 规则 ⇒ 会被 `git clean -fd` 删**，本窗不清、请属主窗自处） |
| `docs/07` | v1.7.17／3,635 行 → **v1.7.18／`wc -l` 3,642**／783,220 字节／mtime 10-02 16:29；§4.8 起 :1072 → **:1073**；取号行 :1077 → **:1078 = `U-135`**；登记最后一行 `U-132` → **`U-134`**（新号 `U-133` @ :1163、`U-134` @ :1165，两号架构现读均 **P1**）；§20.4 自我审计 **35 处**（现读「（35 处」） |
| 🔴 行号漂移表（我第一轮的引用坐标全部作废） | `U-114` 1133 → **1134**；`U-129` 1154 → **1155**；`U-121` 1140 → **1141**；`U-131` 1158 → **1159**；§16.5 场景/断言与 §17.3 闸门行需下轮重取（本轮只重取 §17.3 的 **G-1…G-8 = :3267–3274 仍成立**，取法 = `grep -n` 行首形状现读） |
| 门禁基线 | 全树 **2,312 passed / 0 skipped / 8 errors / rc=1 / 101.14 s @ `d440ed6`**（`E:/tmp_qoder/qa_r2/`）⇒ **与 W6 声称的 `8ffb53e` 基线逐字同数**，8 条 error **全部无 `::` ⇒ 收集期 8 / 夹具期 0**（我的红法拆分独立复现，见下）|
| 共享栈 | 4 个 commerceql 容器 **Up 4 h**（第一轮是 Up 9 h）⇒ **栈在约 10-02 12:5x 北京重启过**；新增残留 `cql-it-pg-t02`（状态 **`created`**，从未启动）、`cql-it-pg-w2b-t02`（exited 0）；`w7load-api_pre0930r11_bak` 仍 exited（`0928r10` pre-fix） |
| 花钱 | 台账 **1,601 行 / ¥2.635700 / max `created_at` 2026-10-01 12:56:32Z** ⇒ **与第一轮逐字相同 ⇒ 10-02 全天全项目零新增花费**；本窗零花费 |
| `app.embed_doc` | **197 行 / 197 非空向量** ⇒ U-114 相关跑批未损向量（我独立于 W0 的旁证再量一次） |

### 2. 七份回执的验收结论（四问裁完）

| 回执 | 结论 | 依据（我现测） |
|---|---|---|
| **W1B（T-01）** | **达成** | `git merge-base --is-ancestor c396266 origin/main` = 真；`wc -l backend/reports/w1b/RELAY.md` = **1,000**（我第一轮 843 ＋ 157 精确吻合）；节起始行现读 **§14 @ :844、§15 @ :927、§16 @ :958** ⇒ 与其回执逐字同。体制效果：F-8 的「未入库」前提消除 ⇒ 相关项可从 `UNVERIFIED` 改判，但**入库 ≠ 采纳**（§14 属读码可复核项，我在 T-08 里要求它给复算命令） |
| **W2B ＋ W0（T-02）** | **达成 ＋ 一条待补（O-6）** | 夹具现读：`test_retrieval_fts_pg.py:69` 区域已改为 `TEST_DSN = env_dsn("RETRIEVAL_TEST_PG_DSN")`，旧 `_dsn_from_env_file()`/`PROD_DSN` 仅存于注释（我 grep 命中 :22/:23/:62/:63/:280 全是说明文本）⇒ **判据 `07:1134` 行末「改为只认环境变量」兑现**；否定式守卫 `tests/contract/test_no_env_file_dsn_derivation.py` = **266 行**在库；我全树重跑：**夹具期 error 3 → 0、skip 6 → 0、收集期 7 → 8**（新增的第 8 条正是该文件 import 期具名 RuntimeError）⇒ 与 W2B ④ 的 2,289/0/8 同形，与我本轮 2,312/0/8 同形。**待补**：W0 点名 `:107-108` 的 `except InsufficientPrivilege: pytest.skip(...)` 仍在 ⇒ 给一个只读 DSN 就会重新静默 skip 6 条 ⇒ 我现测该行仍在（未收口面成立）⇒ 上呈 O-6 请架构裁是否属 U-133「禁 skip」范围 |
| **W7（T-03）** | **达成 ＋ 我退回自己一条** | 新件 `deploy/COMPOSE_SURFACE_DIFF_20261001.md` 在库、`deploy/loadtest/README.md:1561` = §三.0.1ac 在库；我复算其三条：`docs/05` 对 **grafana / prometheus / pgbouncer 命中数 = 0 / 0 / 0**（三条都是我自己 `grep -ic` 现读）；`deploy/init` = **No such file** ⇒ D.5 关键点 4 的落点消失成立；`deploy/observability/README.md` 第 11–13 行现读原文含「**仍未在真实运行时验证过：本窗口没起观测栈、没做过一次抓取、没在 Grafana 里渲染过面板**」⇒ 自曝逐字成立，已进 C 表。**🔻 我第一轮 F-5 那句「实际容器只有 4 个」缺面 ⇒ 作废**：`--filter status=running` 面 = 4、`docker ps -a` 全列面 = **7**（含 3 个退出/created 残留），W7 的纠正在其当时面上成立（他给 5），本轮因新增残留而为 7 ⇒ 一律按**面**报 |
| **W6（T-04a ＋ T-06）** | **T-06 达成；T-04a 部分 ＋ 一条退回** | 达成面：`eval/gates.py:147 red_split()` 出 `assertion_failures` / `environment_errors` / `environment_collect_phase` / `environment_fixture_phase`，:191 注释与 :250 均**单份分类**（不留两份真相）；`backend/reports/w6/eval_metrics.json` 的 `gate_provenance` 八格齐全、每格带 `recompute` 命令与 `tracked_in_git` 布尔 ⇒ 我要的"指路"兑现。**退回一项**：回执写「判据 `07:3267` 与**谓词**一字未动」，而 `git diff fd5f5f2..d440ed6 -- eval/gates.py` 现读 = `- "PASS" if failed == 0 …` → `+ "PASS" if red == 0 …`，且 `red = sp["red_total"]`、`red_total = assertion_failures + environment_errors` ⇒ **判定驱动量已把环境未备计入红**（判据原文确实没动，谓词实现动了）。⇒ 请 W6 具名订正那句话，或在产物里把「这一口径尚待架构裁」写成字段（他们说等架构下轮裁，却在代码里已如此判） |
| **W4（T-06）** | **达成 ＋ 一条我实测坐实** | 其给的三段偏移（12,452／17,193／18,302）我按 v1.7.18 的 `U-129` = :1155 重定位后方向一致（**行号已漂，偏移必须同轮重取**，这正是它自己要求的）；格2p「不是判据」= 它现读 0 命中，与我独立 grep 一致 ⇒ 采纳登记句「格2p 是 W4 提交的证据，生效的仍是格2 ＋ 第四件前置」。**我独立复算它的尺修正**：`lg.checkpoint_writes` 里 `channel='terminal'` = **825 行**，其中 `task_path` 含 `__start__` = **6 行**（涉及 3 个 thread）⇒ 825 ＝ 819 ＋ 6 逐字成立 ⇒ **架构 v1.7.15 ④「813 行／逐 thread 恒 1 次」已不成立**，且**任何用 terminal 写行当"本轮自己写了终态"证据的谓词必须排除 `__start__`**（否则只在入口被写的 run 会被算成达成）⇒ 上呈 O-7 |
| **架构（v27／v1.7.18）** | **裁定收讫 ＋ 我第一轮的两处措辞随之作废** | O-1／O-2／O-4 采纳 ⇒ 我的 F-1／F-2／F-10 结案（`08:309` 现读已有 `tests/integration/**` = 随被测模块 ＋ `_env_dsn.py` = W2A 建、W0 管形状守卫）；O-3 判"不是同一口径"且架构自曝 §16.5 断言⑥ 抄本没跟 `U-130` 的行内订正（§20.4 ㉜）⇒ 我台账里那句"三母不得并读"生效；O-5 拆两号 **`U-133`（探针面）／`U-134`（存量凭据）**，夹具面不另号 ⇒ 我 F-3 的"不取号、只上呈"路径正确。**⚠️ 我对 U-133 的严重性再加一条现测**（见下 R-2） |

### 3. 本轮新发现（R 系列，全部我现测）

- **R-1｜四个闸门的"当期"读数其实出自 9–14 天前的产物。** `eval_metrics.json` 的 `gate_provenance` 现读：G-2／G-5／G-8 的输入 = `eval/results_v1.json`（mtime **2026-09-21T14:33:55Z**）、G-7 = `probe_metric_values.json`（**2026-09-18T17:22:48Z**）、G-3／G-4 = `redteam_results.json`（**2026-09-28T10:09:55Z**）、G-6 = `deploy/loadtest/receipt.json`（自报 `started_at` **2026-09-19T05:27:26Z**）；`basis` 字段：**8/8 格 `self_reported_rev = None`**（无一自报 HEAD），仅 1 格有 `self_reported_at`。**被测构建早已换到 `0930r11`／代码到 `d440ed6`** ⇒ 按 §8 第 2 条"逐条有当期可复算读数"，**当期格数 = 0（唯一今日产物 = G-1 的 pytest 日志，而它 `tracked_in_git = false`）**。⇒ 这是落地进度的**真正长杆**，不是 G 判定的字面值。
- **R-2｜`U-133` 的靶子比架构登记的更硬：那个字面串就是这台机器上能用的超管口令。** 现读 `deploy/loadtest/load_synth_to_pg.py:42` = `DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/ecom"`，`:183` 的 `--dsn` 默认值即取它，help 文本自陈「必须是有 CREATE/TRUNCATE 权的属主串」。我用等值尺（不打印值）比 `deploy/docker-compose.yml` 的 `POSTGRES_PASSWORD` ⇒ **命中 1 处、等值 = True**（长度 8；且不等于 `app_rw` 那个已知 dev 占位串）⇒ **缺 env／不传 `--dsn` 就跑装载器 = 用仓库里的可用超管凭据对共享 `ecom` 做破坏性 TRUNCATE**。⇒ 建议 W7 把 U-133 判据① 的落地验收加一条"不传 `--dsn` 时必须具名 fail"的**负向用例**，并把该默认值删成 `None`。
- **R-3｜我一度把"13 个已跟踪文件含活口令"报成泄漏，撤回。** 现读等值 = 那 13 处命中的是**已知 dev 占位串 `app_rw_pwd`**（长度 10、与 `deploy/.env` 的 `DATABASE_URL` 口令段等值 = True；RO 侧不同串）；`.gitleaks.toml` 自最早提交 `15a23fc` 就点名它 ⇒ **属既有显式豁免，不是新泄漏**（面 = `git ls-files` 的 629 个已跟踪文件，谓词 = 与 `.env` 口令段逐字节等值，命中 13 ⇒ 2.1%，而第一轮登记先例记的是 9 个 ⇒ **该计数随 HEAD 涨**）。**但**它同时是共享栈 `app_rw` 的真口令，配上 R-4 ⇒ 组合面成立 ⇒ 这正是 `U-134` 判据① 要你裁的东西。
- **R-4｜LAN 暴露的形状我复核了：compose 全文无 `host_ip`。** 现读 `deploy/docker-compose.yml` 的 api 段 `ports:` 在 **:163**、`- "8000:8000"` 在 **:164**（**未限定 host_ip**）⇒ 与 `docs/05` D.5 关键点 2「api 用 `expose` 不用 `ports`」不符 ⇒ **契约第 2 条被破坏成立**（W7 报的 200-over-LAN 我未复现，未发任何请求 ⇒ 记 UNVERIFIED；端口绑定面已实锤）。修它要重建 4 个共享容器 ⇒ **只能你批**。
- **R-5｜W4 那条"15:33:18Z 起谁在跑检查点池"：我排除了"写入活动"。** 现读 `pg_stat_activity` = `commerceql-checkpoint` **1 条 idle**（backend_start **2026-10-02 08:05:24Z**）、`commerceql-metadata` 2 条 idle（05:12:41Z）、无 application_name 5 条（05:12:37Z）；而 `lg.checkpoints` 的 `max(checkpoint->>'ts')` = **2026-10-01T12:56:35Z**（与 cost_ledger max 同刻）⇒ **10-02 全天零检查点写入** ⇒ 它看到的旧连接已随 ~05:12Z 的栈重启消失、且"同一条语句两次读数不同"**不可归因于写入活动**。真因未定（候选 = 并行计划下的计数，即 `U-110` 已定稿机制）⇒ 我不指认，转 W4 自选对照复测。
- **R-6｜一次性容器残留要登记处置责任人。** `cql-it-pg-t02` 状态 = **`created`**（从未 `start` 过，谁建的不可从容器面判定）、`cql-it-pg-w2b-t02` = exited(0) 只停未删。**我一律未动**（不删、不改名）。

### 4. 本窗自曝与 🔻 具名失效

- 🔻 **F-5 那句「实际容器只有 4 个」缺面作废**（改按 running / `ps -a` 两个面报，本轮 = 4 / 7）。
- 🔻 **R-3 的初判作废**：把 dev 占位串当活口令泄漏 ⇒ 等值尺现测后撤回；教训 = **命中口令串不等于泄漏，必须先比"它是不是已登记的已知形态"**（本项目 `.gitleaks.toml` 与第一轮记忆都点过这条，我第一次没查就准备报警）。
- 🔻 **第一轮引用的 `07` 行号全部作废**（1133→1134、1154→1155、1140→1141、1158→1159），改用「行首形状 ＋ 号锚点 ＋ 落笔秒现测」；后续台账引用一律带版本 v1.7.18。
- 我第一轮把 T-04 说成"只加列不动谓词"的单 ⇒ 现测 W6 已把 `red_total = failed + errors` 写进判定 ⇒ **说明我当时没预判"加列会被顺带并进判定量"这一形态**；已退回订正。
