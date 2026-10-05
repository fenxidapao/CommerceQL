# 验收窗口（QA）· QA_LEDGER（判据级台账：一行 = 一个判据或一个闸门）

> 填写规矩：读数一律带**作用域**；每个数带**五件**（数 ＋ 面 ＋ 谓词 ＋ 分母 ＋ 粒度）；`n/a` 必须写原因（空作用域 / 无样本 / 靶子形状不含 / 未采）；结论四态 = 达成 / 未达成 / `n/a` / `UNVERIFIED`。
> `DRAFT` 档 = 子件读数、本窗未复算 ⇒ **任何窗引用前必须等本窗换成实测值**。

## 一、上线门禁 G-1…G-8（判据出处 = `docs/07 §17.3`，行号 3267–3274，版本 v1.7.17）

| 对象 | 判据原文（`07` 行号） | 属主 | 本窗最近实测（读数 ＋ 面 ＋ 谓词 ＋ 分母 ＋ 粒度） | 复算命令 | 时刻 ＋ HEAD | 资格三查 | 结论 |
|---|---|---|---|---|---|---|---|
| G-1 全部 P0 用例通过 | `07:3267`（§17.1 单元＋集成）；判定实现 `eval/gates.py:183–196` | W6 | 面 = 整棵共享树；谓词 = `-q -rfEs --continue-on-collection-errors`；读数 = **2,284 passed ＋ 10 errors ＋ 6 skipped**，分母 = 收集到的用例数，粒度 = 用例；**断言失败 0 条** | 见 `GATE_LOG.md` 第一行命令原文 | 10-01 21:59 ＋ `fd5f5f2` | 作用域非空通过；无延迟类读数；**errors 非 pre-fix 恒 0**（7 条由夹具设计强制产生、3 条由权限拒绝） | **未达成（现行尺红 10）**；⚠️ 口径存疑 ⇒ 10 条全为环境/权限类、无一条断言失败 ⇒ 等 T-04 分档后重判 |
| G-2 结构 Easy × 语义低 ≥ 95% | `07:3268` | W6 | 本窗未复算；唯一在案读数 = `OVERVIEW.md:164` 转述 **FAIL** | 待引 `backend/reports/w6/评测报告与门禁判定.md` §10 复算命令 | — | 未查 | `UNVERIFIED` |
| G-3 危险 SQL 放行 = 0 | `07:3269` | W2C ＋ W6 | 转述 **PARTIAL**（`OVERVIEW.md:164`）；本窗未复算 | 同上 | — | 未查 | `UNVERIFIED` |
| G-4 跨租户泄露 = 0 | `07:3270` | W2A ＋ W6 | 转述 **PARTIAL**；`OVERVIEW` 述其只做到 SQL 层模拟、未做 PG 策略（与 `gates.py:13` 的 PARTIAL 定义同形） | 同上 ＋ 双租户夹具 | — | 未查 | `UNVERIFIED` |
| G-5 拒答准确率 ≥ 95% | `07:3271` | W6 | 转述 **FAIL** | 同上 | — | 未查 | `UNVERIFIED` |
| G-6 P95 延迟 ≤ 8s | `07:3272`（口径在 `07:3160`：准入样本 < `MIN_ADMITTED_FOR_P95 = 20` 不得出 P95） | W7 ＋ W6 | 转述 **UNVERIFIED**；本窗未采任何延迟读数（本轮零跑批） | 需当期回执格 ＋ `eval/reporter.py` | — | ⚠️ 分母与 `window_kind` 必须同引（`U-130` 判据面） | `UNVERIFIED` |
| G-7 口径一致性 ≥ 95% | `07:3273` | W6 | 转述 **FAIL** | 冻结集核心指标子集 | — | 未查 | `UNVERIFIED` |
| G-8 澄清率 ≤ 15% 且澄清后一次成功 ≥ 80% | `07:3274`；阈值在 `eval/gates.py:35–36` | W6 ＋ W4 | 转述 **UNVERIFIED** | `gates.py` 的 `G-8_clarify_rate` 与 `G-8_clarify_success` | — | ⚠️ **本窗提示词原本没把 G-8 列进落地定义**（RELAY F-1）⇒ 已按 §17.3 补齐 | `UNVERIFIED` |

> 🔻 具名失效：W7 交给本窗的提示词 §8 第 3 条「G-1…G-6 全绿」**不生效**，本窗一律以 `07 §17.3` 的 **8 条**为准。
> 🔻 同件 §5-C／§8 第 2 条「`04 附录C` 评测方案要求的四场景」**不生效**：`docs/04` 无压测字样，场景清单在 `07 §16.5:3156` 且为 **5 个**，同节 `:3159` 必测断言为 **6 条**。

## 二、`07 §4.8` 缺陷登记（本轮只登记本窗自验过的四号，其余 25 号见 DRAFT 段）

| 号 | 优先级 | 判据关键原文（逐字，`07` 行号） | 本窗实测 | 时刻 ＋ HEAD | 结论（状态） | 谁欠哪一步 |
|---|---|---|---|---|---|---|
| U-114 | P0 | `07:1133` 行末：「**判据 = 该夹具的运行期 DSN 也要过 `pg_guard` 的形状判定，或改为只认环境变量**」＋「残余面…`@pg:` 改写 ⇒ 静态守卫看不见…派 W2B ＋ W0 合批」 | **残余面今日仍开**：`test_retrieval_fts_pg.py:69` 缺 env 时回退 `PROD_DSN`，`:385` 夹具在共享 `ecom` 上试 `CREATE SCHEMA` / `DROP TABLE`，被 `InsufficientPrivilege` 挡住 ⇒ 3 error ＋ 6 skip；挡它的不是守卫而是角色权限 | 10-01 21:59 ＋ `fd5f5f2` | **未结案** | W2B ＋ W0（T-02） |
| U-121 | P0 | `07:1140` 行末：「对外表述请用「**形状通了、归因待补**」，不要用「付清/修完」」＋「结案还差两件事：① `U-119` 判据④ 的 gate2 对称断言；② 一次真栈读数 `gate_passed` / `executing` 非 0」 | 本窗只读行末原文一致，未做实现级验证 | 同上 | **未结案** | W2C ＋ W4（在途，非本窗新开单） |
| U-129 | P0 | `07:1154` 行末（v1.7.17）：三格并报、格2 第四件前置 = 非空真 `t2_routed_supp > 0`、pre-fix 基线改「作用域 × 家族」表、交齐三格用 **P-A′ = 3 对 = 6 条准入 ≈ ¥0.014–0.023（非峰）**；复算件 = `deploy/loadtest/r23_thread_from_checkpoints.sql` 的 ⑰ 四作用域 | W7 第三十一轮已交修复后首次读数（`0a236ec`：格1 两臂 0/0、格2 0 且前置=1、格3 3）⇒ **本窗尚未独立复算该读数** | 同上（引 W7 件，标待复算） | **未结案（待本窗复算 ＋ 待架构出结案句）** | W4 出结案句、架构裁；QA 复算（下一轮） |
| U-131 | P0 | `07:1158` 行末：「判据①②③④ 不变（单一强制点 ＋ fail-closed），但**结案必须同时交三面**：读 = 404、写 = 404、推理 = 明确不适用或补一轮打到 `gen_sql` 的对照；⚠️ **只交读侧不得转绿**」 | 本窗只读行末原文一致 | 同上 | **未结案** | W4（三面）＋ W1B 的未提交上呈（F-8） |

### DRAFT 段（`U-104`…`U-132` 其余 25 号）

子件只读取证给出的状态草稿（判据短语摘录方向可用，**状态一律未经验证**）：本窗判定为 `未结案` 的含 `U-104`、`U-105`、`U-108`、`U-109`、`U-111`、`U-113`、`U-115`、`U-116`、`U-119`、`U-120`、`U-122`、`U-123`、`U-126`、`U-127`、`U-128`、`U-130`；`已结案` = `U-106`、`U-107`、`U-110`、`U-112`、`U-118`、`U-124`、`U-125`；`观察中或降级` = `U-117`、`U-132`。
⇒ **这些状态在本台账里全部标 `DRAFT`，不得对外引用**；本窗第二/三轮逐号读 `07` 行末原文替换（每号一行、带行号与字符区间）。

## 三、`07 §16.5` 必测断言（6 条，`07:3159`）

| 条号 | 判据关键原文 | 本窗状态 |
|---|---|---|
| ① | 无 checkpoint 写入等待（R-10） | `DRAFT`（未采） |
| ② | `SET LOCAL` 身份在连接复用时正确复位（ADR-09 验证③） | `DRAFT` |
| ③ | pgbouncer 后端连接数不超过 30 | `DRAFT`（本窗现测：`commerceql-pgbouncer-1` 容器在跑，未取连接数） |
| ④ | P95 延迟 ≤ 8s，**只在准入（2xx）样本上算** | `DRAFT` |
| ⑤ | 429 必须 `Retry-After: 30` 且限流层 fail-fast | `DRAFT` |
| ⑥ | v1.7.5 追加（`U-130`）：入账完整性以 `admitted` 为分母 ＋ 豁免集合逐条具名；⚠️ `07:1156` 后续把 `U-130` 判据② 改为**直读式** ⇒ ⑥ 与本号措辞需对表（上呈件 O-3） | `DRAFT` ＋ 措辞待裁 |

---

# 第二轮（2026-10-02 16:56 +0800 ＠ HEAD `d440ed6` ＠ `07` v1.7.18）

> 🔻 具名失效：本文件第一轮所有 `docs/07` 行号引用（:1133／:1154／:1140／:1158／:1077／§16.5 的 :3156 与 :3159）**作废**，以本轮现读为准。§16.5 两行本轮**未重取** ⇒ 标 `待重取`。

## 一、闸门台账（刷新）

| 对象 | 判据原文位置（v1.7.18 现读） | 判定输入产物的时效面（我现读 `eval_metrics.json` 的 `gate_provenance`） | 本窗复算 | 结论 |
|---|---|---|---|---|
| G-1 | §17.3 行首形状现读 = **:3267**（G-1…G-8 = :3267–3274 本轮仍成立） | `backend/reports/w6/_full_pytest_1002_r20c.log`：`tracked_in_git = false`、`basis = mtime_only`（06:10:58Z）、不自报 HEAD | **我自己重跑**：全树 **2,312 passed / 0 skipped / 8 errors / rc=1 / 101.14 s @ `d440ed6`**；8 条 error 全部无 `::` ⇒ 收集期 8、夹具期 0；断言失败 **0** | **未达成（红 8 全为环境未备）**；⚠️ 判定驱动量已含 errors（`red_total = assertion_failures + environment_errors`），该口径**待架构裁** |
| G-2 | :3268 | `eval/results_v1.json` mtime **2026-09-21**（11 天前），不自报 HEAD | 未重跑（需额度） | **`n/a`（非当期构建）** |
| G-3 | :3269 | `redteam_results.json` mtime **2026-09-28** | 未重跑 | **`n/a`（非当期）** |
| G-4 | :3270 | 同上 ＋ `_probe_pg_real.json` mtime **2026-09-28** | 未重跑 | **`n/a`（非当期）** |
| G-5 | :3271 | `results_v1.json` **2026-09-21** | 未重跑 | **`n/a`（非当期）** |
| G-6 | :3272 | `deploy/loadtest/receipt.json` 自报 `started_at` **2026-09-19**（唯一有自报时刻的格；8/8 格 `self_reported_rev` 全为 `None`） | 未重跑（需额度 ＋ 时段） | **`n/a`（非当期）** |
| G-7 | :3273 | `probe_metric_values.json` mtime **2026-09-18**（14 天前） | 未重跑 | **`n/a`（非当期）** |
| G-8 | :3274 | `results_v1.json` **2026-09-21** | 未重跑 | **`n/a`（非当期）** |

🔴 **当期格数 = 1/8**（只有 G-1 本窗今日重跑，而那一格的日志不入库 = `.gitignore:47`）⇒ 落地定义第 2 条「逐条有当期可复算读数」目前**不成立**。`n/a` 的原因一律写「输入产物非当期构建」，不写 0、不写"未采"。

## 二、缺陷台账刷新

| 号 | 现行号 | 优先级（现读） | 本轮状态 | 一句话依据 |
|---|---|---|---|---|
| `U-114` | **:1134** | P0 | **待架构确认转结（本窗判：判据已兑现）** | 行末「运行期 DSN 只认环境变量」由 W2B `6b87da9` 落；我现测夹具期 error 3 → 0、skip 6 → 0；残余 = O-6（`:107-108` 权限型 skip 仍在） |
| `U-121` | **:1141** | P0 | **未结案** | 行末仍写「形状通了、归因待补」＋ 两件未交（`U-119`④ 对称断言、真栈读数非 0） |
| `U-129` | **:1155** | P0 | **未结案（待验收 ＋ 待结案句）** | 行末给 P-A′ 靶子与复算件；W4 已把它对 W7 P-A′ 的复算逐字交出（格2 = 0 且前置 = 1、格3 = 3、⑭c = f）⇒ 我下轮照此复算 |
| `U-131` | **:1159** | P0 | **未结案** | 「结案必须同时交三面」＋「只交读侧不得转绿」；W1B §16（改判"结构性无通道"）现已入库 = `c396266` :958 起 ⇒ 推理侧证据候选，待我读全文 |
| `U-133` | **:1163** | **P1** | **新开、未结案** | 架构登记为压测装载器的字面属主 DSN ＋ 缺 env 即破坏性 TRUNCATE；**本窗 R-2 加码**：该字面口令与 compose 的 `POSTGRES_PASSWORD` 等值 = **True**（长度 8，且不等于 `app_rw` 的已知占位串）⇒ 它是这台机器上可用的超管凭据 |
| `U-134` | **:1165** | **P1** | **新开、未结案** | 存量凭据治理；架构两把尺 = 形状 27／等值 17／交集 15／只形状 12。**本窗第三把尺**：面 = `git ls-files` 的 **629** 个已跟踪文件、谓词 = 与 `deploy/.env` 的 `app_rw` 口令段**逐字节等值**、命中 = **13** 个（2.1%），命中的是已登记 dev 占位串 `app_rw_pwd` ⇒ 属既有 allowlist 豁免面、**非新泄漏**（🔻 我初判撤回）；先例记的"9 个"随 HEAD 已涨到 13 ⇒ 计数必须带尺与 HEAD |
| `U-104`…`U-132` 其余 | 见 §4.8 | 混合 | **未结案合计 21 号（P0 = 7、P1 = 13、无级 = 1）** | 尺 = 「行末 230 字符内含明确未结／待补／不得转绿／待命／新开语句」的**肯定式**匹配；🔴 盲区 = 结案句写在行中部者会被这把尺误判成未结（`U-110`／`U-112`／`U-118`／`U-124`／`U-125` 已知属此类，本轮沿用第一轮全行读数记结案） |

> 效力声明：本表覆盖第一轮 DRAFT 段中 `U ≥ 104` 的部分（DRAFT 原文保留不改）；`U ≤ 103` 仍为**未复算**。

---

# 第 8 轮追加（2026-10-02 · W8 体制首轮 · @ `c7cf34a`）

| 对象 | 判据出处 | 属主 | 最近一次实测（数／面／谓词／分母／粒度） | 复算命令形状 | 时刻＋HEAD | 资格三查 | 结论 |
|---|---|---|---|---|---|---|---|
| `U-129` **格3** | `07 §4.8 :1155` | W8（接 W7） | 3 ／ `lg.checkpoint_writes`×`lg.checkpoints` ／ turn≥2 ∧ 本轮自写 terminal（排除 `__start__`）／ 全库宽窗 ／ **粒度 = run** | 只读跑 `r23` ⑰ 行（`-t -A -F'\|'`，值套一层引号） | 10-02 19:5x＋0800 ／ `c7cf34a` | 非空 ✓（3＞0）；静默期 ✓；pre-fix 本就为 0 ⇒ **该格 pre-fix 是 0、现在非 0 = 有效方向** | **达成（非空真）** |
| `U-129` **格2** | 同上 | W8 | 5 ／ 同面 ／ turn≥2 ∧ 被路由 `audit_supp` ∧ 未自写 terminal ／ 全库宽窗 ／ 粒度 = run | 同上 ＋ 我的按天分组尺 | 同上 | **分域后**：09-29 域 5 条（全 pre-fix 存量）；10-01 域 **0 条、n=1** | **全库窗 = `n/a`（作用域不含可判样本，不读成"未达成"也不读成回归）；post-fix 域 = 达成（n=1，须带样本量；分域依据目前是**日期代理**，严格化依赖 T-11②）** |
| `U-129` 第四件前置 | 同上 | W8 | `t2_routed_supp` = **6** ／ 全库 ／ turn≥2 ∧ supp ／ 粒度 = run | 同上 | 同上 | 非 0 ⇒ 不是空作用域 | **达成（非空真）** ✓ 与 W8 报的 6 一致 |
| **排除式等价性**（T-12 的代码半边） | `07:1155` ＋ `reports/w4/RELAY.md:1204-1211` | W8 | terminal 行 825／NULL 0／转义 like 排 6／`split_part` 排 6／**两向差各 0**；非转义 vs 转义 **全表差 0** | 单条只读 SQL（`-f -`，一条 UNION ALL） | 同上 | 当期零效应 ⇒ **预防性**修复，W8 未冒充当期缺陷 ✓ | **达成**（覆盖面 8 处 ＝ r23 3／w4 4／w6 1） |
| **形状不变式（无人守）** | 我本轮新量 | **待派 W8（T-21）** | terminal 行中 `task_path` 不含 `', '` = **0**；含字面 `__start__` 但不在第 2 段 = **0**；非 terminal 行含 `__start__` = **14,967** | 同上 | 同上 | 两个 0 是**约定成立**而非**被断言守住** ⇒ 破了就是假绿 | **未达成（缺断言）** |
| **粒度订正**（供上呈） | `reports/w4/RELAY.md:1206` | W4／架构（批次 3） | 该句写"写过终态的 **run 819**"；现测 **819 = 行数**，**thread 级 = 816** | `count(*)` 与 `count(distinct thread_id)` 同查询并报 | 同上 | — | **待订正**（与 `07 §4.8 U-131` 那条"同名量两数"同族，改引用规则文本时一并） |

## 第 9 轮追加（2026-10-02 @ `c040280`）

| 对象 | 判据出处 | 属主 | 最近一次实测 | 复算命令 | 时刻＋HEAD | 资格三查 | 结论 |
|---|---|---|---|---|---|---|---|

| `U-129` **格2／格3 分域并报**（T-22） | `07 §4.8 :1155` | W8 | `post_fix` **3\|1\|0\|3**／`pre_fix` **61\|5\|5\|0**（列序 = t2_runs／t2_routed_supp／ge2／ge3）；边界常量 `2026-09-30 14:25:35+00`，标签自写 `date_proxy` | 我从三件里**各抽出该 SQL 单跑**（r23 ⑰c／w4 ⑫ 第 339–359 行／w6 第 526–544 行）⇒ **三处同值** | 10-02 20:1x＋0800 ／ `c040280` ／ 只读、共享 `ecom`、零额度 | 非空 ✓；`post_fix` 域 `ge2 = 0` 且 pre-fix 本就为 5 ⇒ 可当验收位，**必须带 n=1** | **达成（post_fix 域，n=1）**；全库混合域 = **`n/a`（不作判）** ✓ 与 W8 一致 |
| **`shape_ok` 否决位**（T-23） | 承 `07:1155` 引用规则 | 待 W8 | `grep -rln shape_ok` 全仓 = **2 处定义、0 处引用** ⇒ 守卫红不出读数这件事**目前无人执行** | 同 grep ＋ 需注入反证 | 同上 | 定义存在但**不进判定链** | **未达成**（T-21 只完成一半） |
| **只读守卫覆盖面**（T-24） | `U-114` 防线邻接 | 待 W8 | 连库 py 件 **7**、带 `force_readonly`／`pg_guard` 的 **5** ⇒ 集合差 **4 个无守卫**（`w2-int/e2e_stage2_check`／`w2b/recall_report`／`w2d/probe_explain_timing_pg`／`w4/probe_feedback_endpoint_pg`） | 两个 `grep -rl` 结果做 `comm -23`（**集合差尺，不用 `is null` 尺**） | 同上 | — | **未达成（开 T-24）** |

## 第 10 轮追加（2026-10-03 @ `d6a6a2a`）

| 对象 | 判据出处 | 属主 | 最近一次实测 | 复算命令 | 时刻＋HEAD | 资格三查 | 结论 |
|---|---|---|---|---|---|---|---|

| **T-23 反证**（守卫是否真进判定量） | 承 `07:1155`／`§13.3` 细节 4 | W8 | 夹具自检 `g1 = 1`；⑰ 旧版 = `ge2 = 0 且 t2_routed_supp = 1 ⇒ 非空真达成`（**假绿**）；⑰ 新版 = `不可判__shape_guard_failed` ×2；⑰c 新版四行全不可判；共享库只读 = 63 非空行／**0 行 guard_failed**／读数未动 | 自起 `qa-t23-neg`（55442／`ecom_neg`）＋ 用件内 `grab()` 逐字抽 ⑰／⑰c，`2ae0b43` 与 HEAD 两版同库同参对跑 | 10-03 ／ `d6a6a2a` | 非空 ✓；两态并报（脏库红／干净库静默）✓；**"红了会翻"是被复现的不是被声明的** | ✅ **达成** |
| **覆盖面三面**（T-26） | 同上 | W8 | 判据谓词面 **8**／含守卫面 **11**／模式行数 **24**；守卫消费位面 **5**（r23 :608/:613/:697＋w4 :364＋w6 :549） | `git show 2ae0b43:… \| grep -c`、`grep -n shape_guard_failed`、`grep -c` 模式行数 | 同上 | — | **读数达成、尺名未固定** ⇒ 开 T-26 |
| **`force_readonly` 的 scheme 面**（T-24 前置事实） | 承 `U-114` 防线邻接 | W8 | `postgresql` **接受**／`postgresql+psycopg` **接受**／`postgresql+asyncpg` **拒**／`postgres` **拒**；四次拒绝的报错 `leak_user=False`、`leak_pass=False`；四个无守卫探针实用的 scheme 全在受支持面内 ⇒ **无迁移障碍** | `./.venv/Scripts/python.exe` 直调 `eval/pg_guard.force_readonly()`，输入为**发明的** `uu:pp@127.0.0.1:59999`（只报布尔） | 同上 | 报布尔不报值 ✓ | **订正 W8 一条事实**；T-24 可无条件开工 |


## 第 11 轮追加（2026-10-04 15:4x +0800 · @ `5307a94` · QA 接续：QA-b）

| 对象 | 判据出处 | 属主 | 最近一次实测（本窗自测） | 复算命令 | 时刻＋HEAD | 资格三查 | 结论 |
|---|---|---|---|---|---|---|---|
| `U-131`（四臂） | `docs/07:1159` | W8 | ① 载荷无 `user_id`；② `get_session` 无属主比对、键只到租户级；③ 两入口同调 `store.get_session`；④ 契约面只有"不存在"那一臂（`:191`／`:226`），跨属主臂**不存在** | `grep -n "class SessionMeta" -A 14 backend/app/api/state_store.py` ＋ `grep -n "def get_session" -A 18 同件` ＋ `grep -n "SESSION_NOT_FOUND" backend/tests/contract/test_api_endpoints_contract.py` | 2026-10-04 15:3x ＋0800／`5307a94` | 作用域非空（四臂都有行号可指）；静默期 n/a（静态面）；**pre-fix 就为 0 的坑已避开**：`:191`／`:226` 两条 404 断言修复前即绿 ⇒ 不得当验收位 | **未修 · P0** ⇒ `T-28` 开出；结案要三面齐（读／写／推理），只交读侧不转绿 |
| 门禁产物当期性 | `eval/gates.py` ＋ `04 C.8 §C.8` | W8（重算）／QA（引用限定） | `counts` = PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2；`meta.git.rev` = `079916d`、`dirty` = true；`self_reported_rev` = null 5 格；最老 `mtime_utc` 09-18 | `PYTHONUTF8=1 .venv/Scripts/python.exe -c "import json;d=json.load(open('backend/reports/w6/eval_metrics.json',encoding='utf-8'));print(d['gate_summary']['counts'],d['meta']['git'])"` | 同上 | 作用域非空；静默期 n/a；pre-fix n/a（不是修复类读数） | **PASS 1/8 ＋ 非当期构建** ⇒ 对外仍不得写"门禁通过"；`OVERVIEW §7` 那格欠"非当期"限定（QA 自己的活，见 RELAY §8.4） |
| 本窗花费 | `app.cost_ledger` | QA（只登记） | 全库 **1,656 行／¥2.725108**／`max(created_at)` = 2026-10-04 06:09:59＋00；本轮新增（`> 07:00:00+00`）= **0 行** | `MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'\|' -v ON_ERROR_STOP=1 -c "select count(*), round(sum(cost_cny),6), max(created_at) from app.cost_ledger;"` | 同上 | 三查 n/a（计数类读数，带谓词与时段即足） | 本窗**零花费**（双向自证：台账当场没涨）；¥2.725108 仍是**下界**（L4 档修复前的历史用量未入账） |

## 第 12 轮追加（2026-10-04 18:1x +0800 · @ `eb72ec9` · QA 接续：QA-b · 本轮 = W8 第 8 轮回执复算）

| 对象 | 判据出处 | 属主 | 最近一次实测（本窗自测） | 复算命令 | 时刻＋HEAD | 资格三查 | 结论 |
|---|---|---|---|---|---|---|---|
| `U-131` 五臂 | `docs/07:1159` | W8 | ① `state_store.py:157` `user_id: str`；② 强制点 `:399-408`、两端重复比对命中 **0**；③ 旧载荷 fail-closed ＋ 计数件 `:110`；④ 属主 GET **200**／非属主 GET **404**／非属主 POST **404** 首字节 `{`（未进图）／契约 **7 passed**；⑤⑥⑦ 无 403/401、管理员豁免命中 0、键族未动 | `cd backend && PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest tests/contract/test_api_endpoints_contract.py -q -k Ownership` ＋ `PYTHONUTF8=1 ../.venv/Scripts/python.exe reports/qa/prompts/probe_u131_readonly.py` | 17:5x–18:1x ＋0800／`eb72ec9`（＝远端同点） | 作用域非空（属主臂 200 在先，⇒ 两个 404 不是空真）；静默期 n/a（同步请求）；**判别力**：修复前无属主那一支（读码）＋ W7 史实 200（`07:1159` 行内）⇒ 404 有区分力，旧镜像本轮未重起 | **达成 · 可结案**（§4.8 状态行归 W8 落笔）；`E:/tmp_w7` 那份活体件未入库 ⇒ 记 `self_reported`，结案证据改指入库件 |
| 门禁当期性 | `eval/gates.py` ＋ `docs/07 §17.3` | W8 | 产物仍是 `079916d`／dirty，`self_reported_rev` = null 5 格，最老输入 mtime 09-18／09-20／09-28；全树 **2,362 passed／0 FAILED／9 errors（85.24s）**、集成面未跑 | `cd backend && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest -q -rfEs --continue-on-collection-errors` | 同上 | 三查 n/a（不是修复类读数） | 🔴 **未闭 ⇒ `T-30`**；对外仍不得写"门禁通过" |
| `lint-imports`（它交回 UNVERIFIED） | `08 §6.4` 门禁面 | QA（代跑） | **R-DEP-1／2／3／4 KEPT，4 kept／0 broken，rc=0** | `cd backend && PYTHONUTF8=1 ../.venv/Scripts/lint-imports.exe`（**不带 `check`**） | 同上 | 三查 n/a | ✅ 该格闭；新坑：`lint-imports check` 报 `unexpected extra argument` |
| 本轮花费口径 | `app.cost_ledger` | W8（事后报） | 新增 **18 行／¥0.028686／非峰（`bool_and(not is_peak)` = t）**；全库 **1,674／¥2.753794**；QA 自测后台账**未涨** | `MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'\|' -v ON_ERROR_STOP=1 -t -c "select count(*), round(sum(cost_cny),6), bool_and(not is_peak) from app.cost_ledger where created_at > '2026-10-04 07:00:00+00';"` | 同上 | 三查 n/a | ✅ 逐字复现；总额**仍是下界**（L4 修复前用量未入账）；写口径齐全（几何／档位／单价现读／`is_peak` 自证） |
| `U-129` 审计三格 | `docs/07:1155` v1.7.17 | W8 | 它自报只到客户端面（属主第 2 轮 200、`terminal_digest` 未复用），审计三格未查；格2 前置 `t2_routed_supp > 0` 本轮未现测 | 三格式见 `07:1155`；前置现测走 `reports/w4/probe_prod_checkpoint_terminal.sql` 的 ⑰ 作用域 | 同上 | **未采 ⇒ 不得记 0** | 🔴 **不得转绿 ⇒ `T-31`** |
| 写面归属（体制） | `reports/w8/PROMPT.md:46`／`:58` ↔ `reports/qa/QA_PROMPT.md` v2 §3 | 总控 | W8 把 `OVERVIEW.md`／`docs/**`／`ACCEPTANCE.md` 收回自写并已写 `OVERVIEW.md:319`；两份件一度正面相反，本窗已对齐并保留复算判红权 | `git diff --name-only 5307a94..eb72ec9` ＋ 两份件现读行号 | 同上 | 三查 n/a（体制裁定，不是读数） | 🟠 **单写者仍成立 ⇒ 可接受**；待总控点头，收回 QA 需两处对称改 |

## 第 13 轮追加（2026-10-04 19:3x +0800 · @ `ec69f8d`／403 笔 · QA 接续：QA-b · 本轮 = W8 第 9 轮回执复算）

| 对象 | 判据出处 | 属主 | 最近一次实测（本窗自测） | 复算命令 | 时刻＋HEAD | 资格三查 | 结论 |
|---|---|---|---|---|---|---|---|
| `T-30` 八格当期化 | `eval/gates.py` ＋ `docs/07 §17.3` | W8 | `meta.git` = {`cbff229`, dirty false}；`counts` = PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2；`gate_provenance.rows` = 8（每格 `basis`＋`recompute`）；`gaps` 自曝弱格 G-1／G-4／G-7 | `PYTHONUTF8=1 .venv/Scripts/python.exe -c "import json;d=json.load(open('backend/reports/w6/eval_metrics.json',encoding='utf-8'));print(d['meta']['git'],d['gate_summary']['counts'],len(d['gate_provenance']['rows']))"` | 19:0x＋0800／`ec69f8d` | 作用域非空；静默期 n/a；pre-fix n/a | **达成**；🔴 引用降级：G-1 输入是未入库 `.log` ⇒ 等级 `mtime_only`，只能"重跑取证" |
| `T-31` `U-129` 三格 | `docs/07:1155` v1.7.17 | W8 | S2 域：格1 两臂 0（`t2_runs = 10`）／格2 `ge2 = 0 ∧ t2_routed_supp = 5`／格3 `ge3 = 10`／`⑱ shape_ok = t`；混合域 `ge2 = 5` 标"不作判"；六空域标 `n/a__该域空真` | 读 `backend/reports/w8/t31_three_cells.json`（`git = {a84fc6f, dirty true, 399}`） | 同上 | 作用域非空（`n = 5` 同框）；静默期：只读 SQL 包 `begin;rollback;`；**pre-fix 基线已带**（格2 = 5、格3 = 0） | 🟠 **三格达成／本号不得转绿**：缺 `07:1155` 第二条耦合（`terminal − audit = 豁免集合`）⇒ `T-33` |
| `T-32` G-1 合并支 | `eval/reporter.py:794-802` ＋ `eval/gates.py:147-158` | W8（修法＋留笔） | **注入夹具实测**：离线 `1 failed, 2347 passed` ＋ 集成 `107 passed` ⇒ 判定量 `{failed: 0, errors: 0}`、**verdict = PASS**（假绿复现） | `PYTHONUTF8=1 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-1', pytest_log='E:/tmp_qoder/fake_offline.log', integration_log='E:/tmp_qoder/fake_integration.log')['verdict'])"` | 同上 | 脏态＝判据明令禁止的形状已注入 ⇒ 不是推测 | 🔴 **成立 = 判据口径变更**；退回"2,454 证合并没吞红"那句（加法只覆盖 `passed`） |
| `T-11②` 第二实例 | 引用规则（四件一起引） | W8 | `basis` 四态＋`gaps` 两组已长在产物里；`_*.log` 仍 `tracked_in_git = false` | `grep -o '"basis": "[a-z_]*"' backend/reports/w6/eval_metrics.json ｜ sort ｜ uniq -c` | 同上 | 三查 n/a（取证面，非读数） | ✅ **闭为"已知等级"**；升级 = 汇总落成入库件 ⇒ `T-33` 顺带 ③ |
| 我这面的红项 | `ruff` | QA | `probe_u131_readonly.py:18` 改 `[*MINT, …]`；`ruff check --config pyproject.toml reports/qa` = **All checks passed**；件重跑读数未变、台账 1,674 → 1,674 | `cd backend && PYTHONUTF8=1 ../.venv/Scripts/python.exe -m ruff check --config pyproject.toml reports/qa` | 同上 | n/a | ✅ 闭；同轮自曝两把尺（`NR` vs `FNR`＝横幅数 1→**10**；管道 grep 吃行 ⇒ 改落盘再读） |
| 构建身份 | `U-131` 面 | W8 | 容器内 `/srv/app/api/state_store.py` md5 = `e31e41c3…` = `git show HEAD:` blob ⇒ 本轮未重建镜像，被测构建仍含修法 | `MSYS_NO_PATHCONV=1 docker exec commerceql-api-1 md5sum /srv/app/api/state_store.py` | 同上 | n/a | ✅ 有效 |


## 第 14 轮追加（2026-10-04 22:1x–22:2x +0800 · @ `0d2570f`／409 笔 · QA 接续：QA-b · 本轮 = W8 第 10 轮回执复算）

| 项 | 判词 | 尺（可自跑，命令全文在 `RELAY §十一`） |
|---|---|---|
| T-32（G-1 合并支两侧相加） | ✅ **达成（判据口径变更，已坐实）** | 四对夹具：真日志 PASS／脏离线 FAIL／脏集成 FAIL／12 条夹具绿；判据措辞「全部 P0 用例通过」核 `docs/07:3272` = 未动 |
| T-33（`U-130` 的两面耦合量） | ✅ **达成（判定量零差）** | 重跑到 `E:/tmp_qoder/t33_recheck.json` ＋ 递归 diff ⇒ 13 差 = 6 meta ＋ 7 时钟派生句；判定量全等 |
| `U-129` 转绿 | ❌ **不转绿**（四条只差 ③） | ①三格我跑 ⑰c 达成（带 `n = 5`）；②落库面 0 达成、回执面 post_fix UNVERIFIED；③最新回执 09-29 23:29 本地，早于修法时刻；④`test_audit_terminal_pairing_contract.py:143` 14 passed |
| 裁② 口径变更要不要进 `§4.8` | ✅ **裁"不要"**，改为 `:3272` 行尾补历史指针 | `grep -c "merge_p0_logs" docs/07_技术设计文档_TDD.md` = 1（在 `:3272` 行内）；`§4.8` 只认落号行与那句显式指针 |
| 裁③ X5／X6 是否豁免 | ✅ **裁"都不算"**：X6 = 契约冲突缺陷（建议取号、零额度夹具钉）；X5 = `n/a__无样本`，不得记 0 | `docs/07:2879` G4 行审计列 = ✅；`grep -rn GraphRecursionError backend/app` = 0 命中 |
| 🔴 新发现（a）守卫支丢第二份日志的红 | ⏳ 进 `T-34` 顺带 A（**非**判据变更，缺的是自描述） | 注入实测 PASS（第二槽 1 failed ＋ 1 error 未进判定量），`eval/reporter.py:898` |
| 🔴 新发现（b）默认路径读上两轮日志 | ⏳ 进 `T-34` 顺带 A | `eval/reporter.py:75`／`:80` vs 盘上 mtime；不带参数读 2,340／带当期读 2,359，两个 PASS 形状同 |
| 🔴 新发现（c）落库面无构建身份 | ⏳ 进 `T-34` 顺带 C（上限写进契约面） | `bundle_version`／`graph_version` 非空行 = 0／0（`tk_` run 1,408）；post_fix 30 条里 21 条带 model／prompt_version，值域 2 与 4 |
| 抄本漂移（版本号 ＋ 对外 HEAD） | ⏳ 进 `T-34` 顺带 B（W8 写面） | `v1.7.19` 三处而版本历史表无行；`:11` 与 `OVERVIEW:8`／`:118` 仍 v1.7.18；`OVERVIEW:161` 主格 382／`b571b40` vs 现测 409／`0d2570f` |
| 评测报告页三端点 ＋ `present/` 空壳 | 🔴 **`T-34` 主单**（QA 自曝：挂三轮无单） | 五条契约路径在 `backend/app` 各 `grep -rn` 命中 0；`present/` 仅 `__init__.py` 292 B |
| 门禁对外口径 | ✅ 未变：**不可写"门禁通过"** | `eval_metrics.json` @ `d93db8f`／dirty false／20:57Z：G-1 PASS，G-2／G-5／G-7 FAIL，G-3／G-4 PARTIAL，G-6／G-8 UNVERIFIED ⇒ PASS 1/8 |
| 本窗花费 | **0**（账本 1,674／¥2.753794 跑前跑后同值；未建库，残渣尺同值） | 件内 `cost_ledger_before = after` ＋ 我 ⑰c 前后各读一次同值 |


## 第 15 轮追加（2026-10-05 11:5x–12:2x +0800 · @ `9e45281`／413 笔 · QA 接续：QA-b · 本轮 = W8 第 11 轮回执复算）

| 项 | 判词 | 尺（本窗自己跑，命令全文在 `RELAY §十二`） |
|---|---|---|
| T-34 主单（A.9.2／A.9.3／A.9.4 ＋ `present/` 投影） | ✅ **达成** | 我的新永久件 `prompts/probe_admin_eval_live.py` 活体 **21 臂 rc=0**：`total=2`／`items=5`／`grid.cells=12`／`gate.items=8`（五值未折叠）／`unavailable=6`／`rerun_in_endpoint=false`／`scope=cross_tenant`／analyst 三处 `403 FORBIDDEN_SCOPE`／带 `tenant_id`／`user_id` 参数 `data` sha256 全等／未知批次 `404 RUN_NOT_FOUND`；契约件 24 条我复跑绿 |
| 顺带 A（G-1 两处静默） | ✅ **达成（且强于我要的形状）** | `covers_integration()` 把"同源"从假设改成可核集合包含 ＋ `_input_stamp()` 进 `caveats`；`eval/gates.py` 判定谓词一字未动；三件测试 **42 passed**；我的五态件重取基准后 **rc=0**（态⑤ 钉"同源跳过 `red_total` 必为 1"） |
| 顺带 B（版本抄本） | 🟡 **达成但有残留** | `07:11`／`:80` 版本历史行／`OVERVIEW:8`／`:118` 已并平 v1.7.19 ✓；但 `OVERVIEW:161`「提交数／HEAD」主格仍 382／`b571b40`、最新 🔻 到 404，现测 413／`9e45281` ⇒ 进 `T-35` |
| 顺带 C（上限入契约 ＋ 取号） | ✅ **达成** | `U-135` 行在 `:1168`、指针行 `:1079` 已推进到 `U-136`；`U-129` 行内 🔻 补 date_proxy 上限；`U-130` 行一字未动；X5 记 `n/a__无样本` 并明写"暂不转正" |
| 裁②（§4.8 不另落一行） | ✅ **执行到位** | `docs/07:3275` G-1 行尾新增「📌 历史指针」并写明"属史料、不入契约、不得当判据引用" |
| 花费事后报 | ✅ **逐位对得上**（单笔最大那条 UNVERIFIED） | 增量 `12｜¥0.019418｜16:18:05→16:23:45Z`，两笔身份求和闭合，`is_peak` 全 false；台账全表 `1686｜2.773212` |
| 共享栈与构建身份 | ✅ **成立** | 残渣尺 `ecom%` = 2（一次性库真 DROP）；五件容器 md5 = 工作树 = HEAD blob 全 SAME（`/srv/app/…`） |
| 它的"重算自证" | ✅ **复现，且比我更严** | 我两遍跑 `reporter`：差集 1 条 = `meta.generated_at`（时钟派生），判定量零差 |
| 🔴 静态面读数 | ❌ **一句不复现** | `ruff check app tests` 在 `9e45281` 干净树给 **1 error（UP020 @ tests/contract/test_recursion_limit_audit_contract.py:73）**，而回执 §十一.2 写"全部 passed"；`mypy app` Success 150 件 ✓；`lint-imports` 4 kept ✓ 但**不设 `PYTHONUTF8` 会 gbk 崩** |
| `U-129` 转绿 | ❌ **仍不转绿** | ①④达成、② 落库面达成／回执面 post_fix UNVERIFIED（`deploy/loadtest/` 无新回执，最新仍 09-29 23:29）、③ 未交 ⇒ ②③ 同一次花费可并补（总控已批） |
| 裁：401 → 错误卡空编号 | ✅ **裁"立案"** | 用户可见错误语义缺失 ＋ `U-131` 那条"错误不可区分"的镜像；零额度可钉；建议号 `U-136`，且 `OVERVIEW §9` 现读没有这条 ⇒ 立案后补一行 |
| 裁：X5 转正 | ✅ **同意暂不转正** | 无样本；转正 = 决策表加行 = 契约变更 |
| 🔻 编制纠正 | ⏳ 进 `T-35` 顺带 | §十一.9 两处"这是架构裁决"⇒ 架构窗停用，判据落笔权在 W8；别把待办挂给不存在的窗 |
| 抄本与行位四处 | ⏳ 进 `T-35` 顺带 | `unavailable` 键名 `why`（契约）vs `reason`（实测）／`OVERVIEW:161` 主格／`U-135` 行引 `:1078` 而指针在 `:1079`／"四个终态"应为"四个回合（三种 outcome）" |
| 本窗花费 | **0** | 台账跑前跑后同值；本窗未建库 |
| 本窗自曝 | 🔻 已修 | 复算门禁报告时漏带 `--md-out` ⇒ 改写别窗入库件 3 行 ＋ 留两份 `.bak`；已 `git checkout` 恢复并删自造件，复核与 HEAD blob 等 |

## 第 16 轮追加（2026-10-05 13:4x–14:0x +0800 · @ `f05dbc2`／426 笔 · QA 接续：QA-b · 本轮 = W8 第 12 轮回执复算 · 零花费）

| # | 它的说法（第 12 轮回执／RELAY §十二） | 我这一侧的现测（命令或件：行号 ＋ 时刻） | 判定 |
|---|---|---|---|
| 1 | 三对 6 条准入、`admission.terminal = 6` | `deploy/loadtest/u129_paprime_r12_pair{1,2,3}.json` 的 `scenarios[0].admission.terminal` = **2/2/2**（顶层无 `admission` 键）；`outcomes` 各 `{ok:1, error_frame:1}` | **达成**（面 R 修法后域第一份分子） |
| 2 | 逐件 SAME 8/8、pair1 干净树重打 `3590eb5`／dirty=False | 三件 `layer1_2.files` 各 8 件全 `SAME`、全在 `backend/app/**`；pair1 `head_rev = 3590eb5…`／`worktree_dirty_at_attest = false`，pair2/3 = `3c37c79`／`true`（它如实）；pair1↔pair3 的 `build_identity` 差 **5** 格（比自报多一格 `head_rev_short`）；`git diff --name-only 3c37c79..HEAD -- backend/app` = 0 | **达成** |
| 3 | 「本轮重建出新镜像 `1005r12`（上一把 4 天前）」 | `docker image inspect 4adbcfc2e8f6` `Created` = **2026-10-04T16:06:22Z**（跑批前 13 小时），且与主栈 `commerceql-api` 同一时刻成像 | **措辞不复现** ⇒ 当期性靠逐件 md5，不靠 build 时刻；请改写为"重打 tag" |
| 4 | 花费 35 行／¥0.058383、全表 1,721／¥2.831595、残渣 2、首格 0 出站 | 四条尺全复现（分组：`u_r12_01/02/03` 各 8 行 = ¥0.045175；`u_walk_r12` 11 行 = ¥0.013208；预热窗 `cost_ledger` = **0 行**；`datname like 'ecom%'` = `ecom ecom_u123_probe`） | **达成**（逐位同） |
| 5 | §十二.0 ③「单笔最大…见 §十二.5 本手补这个数」 | §十二.5 是 U-136 节、**没有该数**；`max(cost_cny)` 自 10-04 09:16:55Z = **¥0.003663**（单行）；按 `task_id` 求和的最大 = **¥0.008740**（本轮 pair1 那条 AST 拒）；`tk_84b821…` 求和 = **¥0.006277**（10-04 那句当时为真） | **一句未兑现 ＋ 量纲不符** ⇒ 要具名订正 |
| 6 | 门禁重算两遍、判定量 0；`eval_metrics.json` `4c33109`／dirty False／PASS 1/8 | 我在 `f05dbc2` 干净树跑两遍（两遍都带 `--json-out`＋`--md-out` 重定向）：递归 diff **判定 0**、唯一差 `meta.generated_at`；我的重算与入库件八格 verdict 同词，差 = `generated_at` ＋ 2 个 rev 戳（`4c33109..f05dbc2` 的 `backend/app` = 0 行） | **复现** |
| 7 | U-136 立案 ＋ 26 臂夹具 ＋ 真机抓到第二处 401 硬编码 | `docs/07:1171` 行首 ✓／指针行 `:1080` = `U-137`（全文命中 1）✓／`OVERVIEW:459` ✓；`npx vitest run` = **26 passed / 3 files**、`tsc --noEmit` rc=0 | **达成**；判据② 测试面仍 **UNVERIFIED**（会话创建支无夹具）⇒ **不结案** |
| 8 | 静态三门当期原文各一行 | `ruff` `All checks passed!`／`mypy` `Success: … 150 source files`／`lint-imports` `Contracts: 4 kept, 0 broken.`（cwd=`backend`、带 UTF-8 env） | **复现** |
| 9 | 抄本四处收口（a–d） | `docs/02` 的 `why` 仅剩 1 处且在订正句自身 ✓；`OVERVIEW:8`／`:161` 换成现测 416/`3c37c79` ＋ 自指句（现 HEAD 已 426 ⇒ 那句**如期**过期）✓；`| G4 |`／`| **U-136** |` 行号尺 ✓；§十二.7 d 的 outcome 尺我今天复跑 = **16 行／3 种**（`failed,refuse,success`，窗口 `> 2026-10-04 16:00Z`）——它写的是 4 行／3 种，**窗口不同**（它取的是走查那四行）⇒ 引用要带窗口 | **达成（一处要带作用域）** |
| 10 | 两个卡点自裁并落笔 | A.9.5 `docs/02:1056–:1058`（`app_ro`／`app/repo/audit_read.py`）✓；A.7.1／A.7.2 `docs/02:701–:702`（平台级共享面）✓；均**判据、未实现**（它自己也这么写） | **达成（落笔面）**；实现面 = 未做 |
| 11 | 顺带：压测端口收回回环 | `compose.loadtest.yml:41` = `"127.0.0.1:18000:8000"` ✓；`w7load-api` 已 down ⇒ 运行面尺取不到 | 声明面 **达成**／运行面 **UNVERIFIED** |
| 12 | 🔴 新逮（不来自回执）：对外 §9 的 openapi 数与"两页必 404" | 现测 `openapi.json` = **15** 条 path（`OVERVIEW:477` 仍写 12）；前端在调而路由不存在三处：`/semantic/metrics`(`SemanticPage.tsx:124`)、`/semantic/assets`(`:156`)、`POST /admin/eval/run`(`EvalRunsPage.tsx:151`)；`/admin/eval/runs` 列表支对 admin 200／对 analyst **403** | **抄本过期 ＋ 形状要按角色拆**（浏览器面 UNVERIFIED） |
| 13 | 🔴 新逮：G-6 现有 6 样本已跨 8s | 反解样本 `mean×n−max`：pair1 {9807.6, **20042.4**}、pair2 {6591.3, 8936.7}、pair3 {7299.8, 9081.5} ms；`p95_scope=admitted_http_2xx`、n=2 ⇒ **p95 = max**；回执无逐样本＋outcome | **新欠**（形状要补，别只写"样本不足"） |
| 14 | 🔴 新逮：面 R 三条红的归因为空 | 三条 `GATE_AST_REJECTED`／`turn2plus`／同一题（psql：`outcome=failed`、`final_executed_sql` 776/887/962）；`§4.8` 无判据管"重问同题被 AST 拒" | **要归因**（已有号／取 `U-137`／进 t33 豁免集合，三选一） |
| 15 | 🔴 新逮：硬要求 (d)「报价先落一行再跑」在提交面不成立 | `git log` 现测报价笔 `b496d7b` = 10-05 12:56:36 +0800，而预热回执 `started_at` = 04:51:14Z = **12:51 +0800** ⇒ 提交晚于跑批起点 5 分钟 | **未达成（顺序）**，补法见 RELAY 13.1 (d) |
| 16 | 本窗自曝（docs/07 v1.7.20 双插、行数尺、拿业务端点探活） | `grep -c '^\| **v1.7.20** \|'` = **1**；`wc -l` **3,648**／CRLF 3,648／裸 CR 0（`read_bytes` 尺）⇒ 去重与尺**逐字复现** | **认账且已闭** |

**永久件复跑**：`probe_g1_merge_four_state.py` **漂移 0/5、rc=0**（附臂当期 `_1005_rT35` 两把 = PASS）；`probe_admin_eval_live.py` **不合格 0 臂、rc=0**（零花费自证：跑后仍 1,721／¥2.831595）。
**本窗写面纪律**：四件各只追加一节，段标题命中数落笔前后各数一次（防第 15 轮那次双插）；只 stage `backend/reports/qa/**` 四件；工作树复算全程 0 行。
