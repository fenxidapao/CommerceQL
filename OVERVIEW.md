# CommerceQL —— 一份文本读懂这个项目

> **这是什么**：基于 Text2SQL 的电商数据分析 Agent。用户用中文问一句业务问题，系统生成一条**受控**的 SQL，
> 在只读业务库上执行，再自动出图并给出带口径说明的结论。
> **本文定位**：不依赖任何外部讲解，读完即可理解项目的目标、架构、当前实现进度与真实质量水平。
> 它**不属于** `docs/01–08` 契约文档集，不承载契约权威（权威顺序：附录A(02) > PRD(01) > UIUX(06) > TDD(07) > 实施计划(08)）。
>
> 【历史取证 · 2026-10-05，勿引为现状】取证时刻：**2026-10-05 15:4x +0800（= UTC 07:4x，第 13 轮落笔侧取证）**｜代码 HEAD：`c62f02d`（`main`，本行写下时远端 `git ls-remote origin main` = `c62f02d9711…` ⇒ 与 `git rev-parse HEAD` **同点、双向 0 偏差**；现读 438 次提交。🔻 **上一版取证（第 12 轮，10-05 13:0x +0800）= HEAD `3c37c79`／416 笔**，作历史读数保留、不当现状。⚠️ **本行自指、且必然过期**：任何一笔新提交都会让它失真 ⇒ **引用 HEAD / 提交数前必须实跑 `git ls-remote origin main` 与 `git rev-list --count HEAD`，别抄本行**）｜契约文档：**`07 = v1.7.21`**（**3,651** 个换行元素 = 正文 3,650 行 ＋ 尾空元素，两口径并报；`wc -l` 现读 3,650；行尾现读 **CRLF 3,650 ／ 裸 CR 0**）、**`08 = v1.4.1`**（`wc -l` 487 ／ 切分 488）｜`07 §4.8` 下一可用号 = **U-138**（现读出处 = `docs/07_技术设计文档_TDD.md:1081` 那句"下一个可用号 = U-138"；🔻 **v1.7.20 起本窗停止逐处抄行位**：该指针行位置每轮随插行漂移，本项目已三次踩到"行位抄本落后于内容"（QA 第 15 轮 12.8 c 是第三次），⇒ 坐标只认那句**行首**「下一个可用号 = `U-xxx`」，行号只作时点快照；v1.7.21 本窗取一号 `U-137`（闸门 R10 不认 CTE 侧 ⇒ 「先聚合再连维表」被报成越权；落号行本轮现测 `:1173`）；v1.7.20 本窗取一号 `U-136`（401 令牌过期时错误码没送到用户眼前 = `U-131` 的镜像；落号行现测 `:1172`）；v1.7.19 本窗取一号 `U-135` = `recursion_limit` 超限不写审计行（决策表 G4 行本轮现测 `:2885` 要求审计 ✅，落号行现测 `:1169`）。⚠️ **本行自曝一次尺误**：16:0x 那一版这里写成了 `U-136`，依据是"正则扫全文最大号 = 135 ⇒ 下一号 136"，而全文 `U-135` 只有 **2** 处命中、两处都是**指针／变更行**而不是已落号行 ⇒ "扫到最大号 +1" 不是取号尺，取号只认 §4.8 的落号行与那句显式指针。第 5、6 轮**零取号、`docs/**` 内容一字未改**；第 6 轮的四处判据侧／计量侧缺口（金标默认谓词、指标面覆盖、上游不可用的终态归类、`l4_score` 不入累加器）**已上呈但未落号**。🔻 **10-04 02:0x 就地补记一件"位置"变化（不是内容变化）**：`docs/01–08` 与本文 `OVERVIEW.md`、`_refs/` **已进 git**（提交 `3b695a9`）—— 此前 `git ls-files docs` = **0** 而盘上有 15 个文件，`README.md:15` 又把"唯一当前真相"指在仓库外 ⇒ clone／GitHub zip 的收件人拿不到契约文档。入库内容**逐字未改**（现算 `wc -l` 07 = 3,642、08 = 487 与本行上面的读数一致），只有两处字节级副作用：① `.gitattributes text=auto eol=lf` ⇒ 入库 blob 是 LF；② `docs/*.bak-*` **七份快照不进仓库**，移到工作区外归档 `E:\01_实训\项目\CommerceQL建议删除垃圾\docs-bak-20261004\`（移动非删除）。入库前对 12 个新跟踪文件按 `deploy/.env` 现读的四条真凭据做了字面量包含检查 = **命中 0**（唯一命中的是本文里我自己落下的两个口令字面量，已按 `U-134` 既有做法脱敏成形状；⚠️ 仓库内另有 **8 个此前已跟踪并已推送**的文件仍含同样字面量 —— 那属 `U-134` 的"轮换 vs 显式豁免"未裁项，本窗不擅动））
>
> **当期口径（2026-10-24 快照）**：HEAD `df65531`／711 笔；`07 v1.7.34`（3,683 行）／`08 v1.4.1`。
> **官方快照** = `backend/reports/w6/eval_metrics.json` 的 `88f3500`／**PASS 1/8**（PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2，生成 `2026-10-07T05:27:34Z`，最后改动该文件的提交 `24d4477`），**非当期读数**；
> **当期复算** = `eval/results_w80_gate_recompute.json` 的 **6 PASS／0 PARTIAL／2 UNVERIFIED／0 FAIL**（rev `26421ae`／`dirty=false`），**非官方快照**。两数必须同框，6/8 不等于门禁通过。
> 逐格说明见 §6／§7 顶部块；对外终版见 `backend/reports/w8/DELIVERY.md` 终版节；快照决策见 `backend/reports/w8/OFFICIAL_SNAPSHOT_DECISION.md`。
> ⚠️ 本块自指、必然过期：引用 HEAD／提交数前实跑 `git rev-parse --short HEAD; git rev-list --count HEAD`。
>
> 凡标注「实测」的句子都带文件指针；未跑过的一律写 `UNVERIFIED`。

---

## 1. 三十秒电梯版

- **做的事**：中文业务问题 → SQL → 电商库 → 图表 + 结论。服务方 = PRD §3.1 登记的 7 类角色
  （店铺老板/店长、运营、投放/市场、财务、客服、数据分析师、平台管理员），替代"提需求给数据团队排期"。
- **不做的事**：不是"调个 LLM 写 SQL 然后 execute"的 demo。整个设计围绕一个事实展开 —— **LLM 生成的 SQL 是不可信输入**。
- **怎么保证可信**：三道闸门（AST 白名单 → 策略/权限校验 → EXPLAIN 成本熔断）+ 数据库层行级隔离（RLS）+ 出站内容白名单 + 两段式审计（fail-closed）。
- **答不出来怎么办**：分三档出口 —— **澄清 / 拒答 / 报错**，三者视觉与语义严格可区分。拒答不是错误，是正确行为。
- **现在到哪**：端到端链路已在真实容器里跑通（19 节点图 ＋ 前端 SSE），并且 **10-03 第 5 轮第一次在浏览器里走查通过**
  —— 一次提问从输入到出表全链路真跑（DeepSeek ＋ PG RLS），四类终态都实测见过：正常出数、闸门拒、计划自拒、空结果。
  🔴 **但"出图"目前不成立**：`app/present/` 已不是空壳（现读 3 个文件 701 行：`artifacts.py` 只读产物装载 ＋ `eval_report.py` 是 A.9.2–A.9.4 的**投影**），但**图内侧仍未落** —— `chart_spec`／`insight` 不在这里生成，`GraphDeps.presenter` 恒 `None`、`graph/nodes/present.py` 的 fail-fast 照旧 ⇒ 每一轮都会带一条"本次未能生成图表，已用表格展示"的降级标注
  （这不是 bug 而是 §5.3 的如实降级，见 `graph/nodes/present.py` 的模块说明）。
  后端现读 **160 个模块文件 / 42,420 行**；**官方快照 PASS 1/8、当期复算 6 PASS＋2 UNVERIFIED**（详见 §7），"结果算对了"这件事**尚未成立**。
  【历史读数 · 10-03】🔻 **10-03 第 6 轮就地更新（原文不删）**：本轮跑了**第一批全量真打评测**（166 题、¥0.337171、14.6 分钟），
  门禁因此从 `0/8` 变成 **`1/8`**（G-1 转 PASS：离线 2,334 ＋ 集成 107，0 红）；"结果算对了"仍然**未成立**，
  但它的含义被订正了 —— 此前引用的 `EX=0` 里有**两处是评测自己的量具缺陷**（方言桥与体积字段，见 §7），
  修后同一批的真等价数是 **3/124**；另有 **19/41** 的差落在"冻结集金标没带指标默认谓词"这一判据侧缺口上。
  【历史读数 · 10-04】🔻 **10-04 00:5x 就地再更新（原文不删）**：同一天跑了**第二批全量真打**（166 题、¥0.391504，是被测代码面的第二次读数）——
  链路明显变深（终态 `complete` 12→48、`error` 32→1、澄清 54→30），真等价数 **3→6/124**，但**八格仍 PASS 1/8**，
  且 G-5 的误拒从 43/124 涨到 **63/124 = 50.8%**。逐条归因后结论是：这 63 条**不是新缺陷**，是同一批题被推过理解阶段后
  全部撞死在计划层（100% 出口理由 `no_data_asset`、最后节点全是 `plan`）；按金标形状拆开 = **34 条 `COUNT` 形态 ＋ 29 条未声明的列级聚合**，
  而语义包的 `metrics:` 现读只有 **9 个** ⇒ **当前主阻塞换形：语义层的指标面覆盖 ≠ 冻结集的期望**（第二处判据侧缺口，详见 §7、§9）。

---

## 2. 四条核心主张（项目的设计前提）

1. **参考对象要选对。** 同一批模型在学术基准 Spider 1.0 上 86.6%，在 Spider 2.0（真实企业工作流）上只有 10.1%。
   本项目**不以公开基准分数作为验收标准**，而是自建冻结评测集。
2. **没有指标口径字典，系统不是"不准"，而是"越准越危险"。** LLM 能生成语法完美、逻辑自洽、执行成功、
   且与财务口径差 30% 的 SQL，**并且不会报错**。所以语义层（版本化 YAML 语义包 + 口径字典）是 P0 地基，不是优化项。
3. **"生产级"与"demo"的分水岭在三处**：语义层（准确率上限）、校验层（安全边界）、评测体系（能否证明它是对的）。前端只是载体。
4. **诚实性优先于叙事。** 明确区分**设计目标 / 实测值 / 二手待复核**三类数字（§11），主动披露缺口（§9），
   并把"拒答 / 降级 / 错误"三态在 UI 上做成可区分 —— 否则用户会把正确拒答当故障反复重试，在体验层自我否定了安全设计的价值。

---

## 3. 系统怎么跑：一次提问的完整路径

**编排**：LangGraph 状态机，PostgreSQL 持久化 checkpointer。19 个节点（15 主链 + `repair` 回灌 + 3 终态出口），递归上限 25。

```
trusted_context → normalize → intent → link → plan → bind → gen_sql
   → gate1_ast → gate2_policy → gate3_cost → execute → mask
   → audit_pre → present → audit_supp → END
                                  ↑______ repair（失败回灌，repair_round < 2）
```

- 代码位置：`backend/app/graph/build.py`（装配）、`app/graph/nodes/`
  19 个节点实现文件 + `__init__.py`（节点名唯一来源）/`_shared.py`、`app/graph/edges.py`（14 个 `route_after_*` 条件路由）、
  `app/graph/events.py`（SSE 发射时机）。`GRAPH_VERSION = 0.1.0`、`build.py:86 GRAPH_RECURSION_LIMIT = 25`。
  （行数现读：`git ls-files backend/app/graph | xargs wc -l | tail -1`）

**三道闸门**（`app/guard/`：`ast_gate.py` + `rules.py` + `policy_gate.py` + `cost_gate.py`；
闸门决策枚举 `PASS/WARN/REJECT/SKIPPED` 在 `app/core/enums.py`）

| 闸门 | 实现 | 拦什么 |
|---|---|---|
| gate1 AST 审计 | `guard/ast_gate.py`（sqlglot 解析）+ `guard/rules.py`（**20 条规则注册表**） | R01 语句类型、R02 多语句、R03 `SELECT *`、R04 强制 LIMIT（**改写**，无错误出口）、R05 表白名单、R06 列白名单、R07 高危列→`PII_BLOCKED`、R08 系统 schema、R09 函数黑名单、R10 join 路径、R11 笛卡尔积、R12 递归 CTE、R13 union 作用域、R14 字面量策略（**文案只许进内部日志，下发用户即渲染层 bug**）、R15 注释剥离、R16 `search_path`；R17 隐式转换、R18 无界排序、R19 子查询深度 >5、R20 输出列 >50 为**仅告警**。<br>严重级别是 `core/enums.py:726-740` 的查找表而非散落 if：`R04`/`R15` = REWRITE（改写后继续，无错误出口）、`R16` = BLOCK、`R17`–`R20` = WARN。<br>⚠️ 此处的 `R19` 是**闸门规则号**，与下文引用的**风险登记册 `R-19`** 不是一回事（带连字符者为风险项）。 |
| gate2 策略校验 | `guard/policy_gate.py`（`G2-ASSET` + 语义包策略版本） | 资产授权、行/列级范围、口径版本一致性 |
| gate3 成本熔断 | `guard/cost_gate.py`（`G3-COST`，EXPLAIN 前探） | 阈值成对配置在 `core/config.py:118-121`：`total_cost` WARN 5e4 / **REJECT 5e5**，行数 WARN 50 万 / **REJECT 500 万**（启动即校验 WARN < REJECT）；EXPLAIN 连续失败 3 次转降级 |

**三档出口**：终态事件按出口节点映射（`clarify_out` / `refuse_out` / `error_out`），降级另有
`DegradedReason`（8 个取值）+ `report_degraded`，**降级不是终止事件**，链路仍产出结果。

**传输与呈现**：SSE 流式，帧编码唯一入口 `app/api/sse.py:48`（`event:`/`data:` 字节级唯一实现，6 个合法 stage，
15 秒心跳，`X-Accel-Buffering: no`）。前端 React 18 + AntD 5 + ECharts，SSE 客户端在
`frontend/src/api/queryStream.ts`（POST 流、终止帧唯一判据 `data.terminal === true`、90 秒无事件超时），
6 个页面 / 15 个业务组件（AskBox、StageBar、SqlCard、ClarifyCard、RefuseCard、ErrorCard、DegradeBar、CaveatBar…）。

**对外接口**（`/api/v1` 前缀）：`POST /query`（SSE）、`POST /query/{task_id}/cancel`、`GET /query/{task_id}`、
`POST /session`、`GET /session/{id}`、`POST /clarify`、`POST /feedback`、`GET /healthz{,/live,/ready}`、
`POST|GET /healthz/drain`、`GET /metrics`。错误码 28 个的唯一映射在 `app/api/errors.py`（契约见附录 A §A.11）。

---

## 4. 技术栈定案

| 层 | 选型 | 关键约束 |
|---|---|---|
| 语言 / Web | Python 3.12+、FastAPI（SSE） | — |
| 编排 | LangGraph + PostgreSQL checkpointer | 递归上限 25，节点级超时表 |
| 主数据库 | PostgreSQL 16（pgvector） | **双 DSN**：元数据 R/W + 业务只读；RLS + 列级权限。**P0 是同实例 `app_ro` 角色级只读，不是物理只读副本** |
| 检索（4 路 + 融合） | ① 稠密向量（**Ollama + `bge-m3`**，1024 维）② 稀疏词法（jieba → `tsvector('simple')` + `ts_rank_cd`）③ Join 图 BFS ≤2 ④ 值检索 → RRF 融合 | PG 原生 `tsvector` 对中文无效（整句一个 token）；这不是严格 BM25 |
| 精排（L4） | LLM 精排（非思考模式，同粒度候选联合打分） | **严禁双塔余弦**；阈值 τ 绑定 `(model_id, prompt_version)`；本地 cross-encoder 为 P1 升级路径 |
| SQL 校验 | sqlglot（AST 白名单审计） | 见 §3 gate1 |
| 缓存 / 会话 / 限流 | Redis 7 | 缓存键唯一构造入口 `app/cache/keys.py`；查询级结果缓存 P0 刻意关闭 |
| LLM | DeepSeek（`deepseek-flash` / `deepseek-v4-pro`） | **官方无 embedding API** ⇒ embedding 是必须独立引入的第二个模型依赖，数据不出本机；限流按并发连接数（2500/500）非 QPS |
| 评测沙箱 | SQLite（440 MB 合成库） | 冻结集 166 题 + 红队 66 例 |
| 前端 | React 18 + TS + Vite + AntD 5 + ECharts + zustand + react-query | 前后端**两个独立构建产物**；生产 Nginx 同源反代、CORS 关闭 |
| 部署 | Docker Compose：`pg`(pgvector) / `pgbouncer` / `redis` / `api` / `web`(nginx) / `worker` / `prometheus` / `grafana` | 见 §9 关于 `worker` 的实测缺口 |

---

## 5. 仓库与文档地图

**本目录就是仓库根**（GitHub `fenxidapao/CommerceQL`，`main` 分支）。**没有**嵌套的 `CommerceQL/` 子目录 —— 本文早期版本那种写法已失效。
历史窗口报告、旧评测结果与其余 cassette、`deliverables/`、`_refs/` 在**仓库外**同级目录 `../CommerceQL-archive/`（含 `restore-evidence.ps1` 可回滚）。

```
CommerceQL/                    ← 仓库根（= 本目录）
├── AGENTS.md                  ← ★ 新 Agent / 新接手先读（导航、阅读预算、禁区、陷阱）
├── README.md                  ← 工程约束版说明书（§2 快速开始、§4 五条约束）
├── OVERVIEW.md                ← 本文（项目导读；历轮快照已切至 archive）
├── docs/01–08                 ← 契约文档集（权威顺序 02 > 01 > 06 > 07 > 08）
├── backend/
│   ├── app/                   ← 16 个业务包，L0–L5 分层（读 backend/.importlinter）
│   ├── tests/                 ← unit · contract · eval · integration · redteam · graph_snapshot
│   ├── reports/               ← 当前证据（w6 评测输出 / w8 / qa）→ 读 reports/README.md
│   ├── scripts/               ← lint / secret-scan / drill 脚本
│   └── pyproject.toml         ← 依赖白名单 + pytest / ruff / mypy 配置
├── eval/                      ← 评测执行器 + 冻结集 + 当期 W80 结果 + 2 个 cassette
├── semantic/                  ← 语义包 bundle + 口径字典 + 校验器（读 semantic/README.md）
├── data/                      ← 合成数据生成器 + schema.sql（沙箱库不入库，读 data/README.md）
├── deploy/                    ← compose · Dockerfile · nginx · 压测驱动 · runbook · 观测面板
├── frontend/                  ← Vite + React + TS（SSE 流式对话与评测页）
└── .github/workflows/ci.yml   ← 7 job：contract-tests / w1a-artifact-checks / migration-gate /
                                 dependency-direction / lint / t23-shape-guard-gate / secret-scan
```

> ⚠️ 树里**刻意不写**文件数 / 行数 —— 那类数字每次提交都会漂，而且"写死的数"正是本文历史上最大的误导源。现读用：
>
> ```bash
> git ls-files backend/app | grep '\.py$' | wc -l
> git ls-files backend/app | grep '\.py$' | xargs wc -l | tail -1
> git ls-files frontend/src | grep -E '\.tsx?$' | wc -l
> ```

**文档地图（要什么去哪里）**

| 想要 | 去 |
|---|---|
| 进度与门禁现状 | 本文 §6 / §7 |
| 接口契约（最高权威） | `docs/02_附录A_接口契约详解.md` |
| 架构、判据、问题编号登记 | `docs/07_技术设计文档_TDD.md`（`§4.8` 是 `U-xx` 唯一权威，`§17.3` 是门禁定义） |
| 口径与指标定义 | `semantic/bundle_*.yaml` ＋ `semantic/metric_dictionary.md` |
| 评测与证据 | `eval/README.md`、`backend/reports/README.md` |
| 改代码前必读 | `README.md` §4 五条工程约束 ＋ `backend/.importlinter` |

`backend/app/` 依赖层级（低 → 高）：`core` / `repo`（L0）→ `semantics` / `llm` / `auth` / `obs`（L1）→ `binding` / `guard` / `exec` / `mask` / `cache`（L2）→ `planner` / `retrieval` / `present`（L3）→ `graph`（L4）→ `api`（L5）。
依赖方向由 `.importlinter` 机器保证：R-DEP-1 只能依赖严格更低层；R-DEP-2 确定性模块与 `binding` 禁 import `app.llm`；R-DEP-3 `obs/` 内除 `audit.py` 外禁依赖 `repo`。

---

## 6. 当前实现进度（实测）

🔻 **2026-10-24 第 80 轮（路径 A 零成本收口）当期读数 —— 现状以本段为准；历轮快照已切至 archive（见本节末指针）**（审计 rev `26421ae`／`dirty=false`；时刻 = 2026-10-24 14:24–14:26 +0800；零 LLM 出站；产物 = `eval/results_w80_final_audit.json`）：

- **当期复算 6 PASS／0 PARTIAL／2 UNVERIFIED／0 FAIL**；官方快照仍 **`88f3500`／PASS 1/8，未刷新**，与当期复算不是同一份读数。
- 六个 PASS 的单格读数：G-1 离线 **2736** ＋ 集成 **124**（W78 复用）；G-2 **8/8**；G-3 放行 **0**／覆盖 **50**；G-4 跨租户行 **0**（PG RLS 真库）；G-5 **24/24**＋误拒 **3/124 = 2.4%**；G-7 **13/13**。G-6／G-8 属外部阻塞，见 §9。
- 「**L4 决策份额 0/166；τ 未校准**」——G-2／G-5／G-7 的 PASS 是**条件性 τ 非适用**（`tau_applicability=not_exercised`），不是 τ 校准证据。
- 逐格「数＋面＋时刻＋HEAD＋复算命令」见 §7 顶部表；最终交付见 `backend/reports/w8/DELIVERY.md` 终版节；快照决策见 `backend/reports/w8/OFFICIAL_SNAPSHOT_DECISION.md`。

> **读法**：本节只保留当期块（2026-10-24 收口）；历轮历史快照已切至 `../CommerceQL-archive/reports/OVERVIEW_HISTORY_2026-10-25.md` §H1。当期只认顶部块与 §7 顶部对账。

阶段划分：`0` 脚手架+契约固化 → `1A` 地基（语义包/合成数据/冻结集/红队）→ `1B` 骨架（认证/审计/图/checkpointer）
→ `2` 确定性核心（W2A 语义层 / W2B 检索 / W2C 闸门 / W2D 执行脱敏）→ `3` LLM 链路（W3A 网关 / W3B 理解生成 / W3C 四层绑定）
→ `4` 编排收口（W4）→ `5` 前端（W5）→ `6` 评测与门禁（W6）→ `7` 观测部署（W7）。

> **历史（已切出）**：本节 2026-09-29 → 10-06 的逐轮快照（含"上一条已被我推翻"的就地订正、各时点规模表与质量读数表）已整体移到
> `../CommerceQL-archive/reports/OVERVIEW_HISTORY_2026-10-25.md` §H1。要查"某个数哪一轮测的、为什么改口"去那里 grep；**不要当现状引用**。

---

## 7. 质量现状：官方快照 PASS 1/8；当期复算 6 PASS＋2 UNVERIFIED（两者必须同框）

> **对账（2026-10-24）**：官方快照 `88f3500`／PASS 1/8 是**入库件、非当期读数**；当期复算 **6 PASS＋2 UNVERIFIED**（rev `26421ae`）是**复算、非官方快照**。两数必须同框；**6/8 不等于门禁通过**。
>
> 本节只保留当期收口与门禁定义；历轮复算流水已切至 `../CommerceQL-archive/reports/OVERVIEW_HISTORY_2026-10-25.md` §H2。

🔻 **W80 当期收口（2026-10-24；审计 rev `26421ae`／`dirty=false`；零 LLM）—— 八格当期读数只看本表；历轮表已切至 archive**

**汇总：6 PASS／0 PARTIAL／2 UNVERIFIED／0 FAIL**；官方快照 **`88f3500`／PASS 1/8**（未刷新，非当期读数）。τ 未校准；G-2／G-5／G-7 的 PASS 标 `tau_applicability=not_exercised`（条件性非适用，不是校准证据）。

| 格 | 判定 | 数（当期） | 面（产物） | 时刻（产物自报） | HEAD（产物自报） | 复算命令 |
|---|---|---|---|---|---|---|
| G-1 | PASS | 离线 **2736**／集成 **124**；红 **0** | `eval/results_w80_offline_pytest.junit.xml` ＋ `eval/results_w78_integration.json` | `2026-10-24T06:24:12Z`（离线）／`2026-10-24T04:49:46Z`（集成） | `26421ae`／`e7fc769` | `pytest … --junitxml=eval/results_w80_offline_pytest.junit.xml` ＋ `eval/w80_gate_recompute.py` |
| G-2 | PASS | easy×low **8/8**（单格分母） | `eval/results_w77_full166_applicability.json`（166 条 replay） | `2026-10-24T04:06:41Z` | `2cd6c92` | `eval/w80_gate_recompute.py` |
| G-3 | PASS | 放行 **0**／覆盖 **50/50** | `eval/results_w80_redteam.json`（66 条） | `2026-10-24T06:26:15Z` | `26421ae` | `eval/redteam_eval.py --out eval/results_w80_redteam.json` ＋ `eval/w80_gate_recompute.py` |
| G-4 | PASS | 跨租户行 **0**；RLS 行为 5/5＋对象 6/6 | `eval/results_w78_integration.json` | `2026-10-24T04:49:46Z` | `e7fc769` | `eval/w80_gate_recompute.py` |
| G-5 | PASS | 该拒 **24/24**；误拒 **3/124 = 2.4%** | `eval/results_w77_full166_applicability.json` | `2026-10-24T04:06:41Z` | `2cd6c92` | `eval/w80_gate_recompute.py` |
| G-6 | UNVERIFIED | P95 **7268ms**（分母未标注；STALE） | `backend/reports/w6/eval_metrics.json`（官方快照） | `2026-10-07T05:27:34Z` | `88f3500` | `eval/w80_gate_recompute.py`（引用旧快照，非当期） |
| G-7 | PASS | 一致 **13/13** | `backend/reports/w6/probe_metric_values.json`（system_source `5bdb663`／r75）＋ W77 replay | `2026-10-23T12:39:21Z`／`2026-10-24T04:06:41Z` | `5bdb663`／`2cd6c92` | `eval/w80_gate_recompute.py` |
| G-8 | UNVERIFIED | 澄清率 **16/166 = 9.6%**；`success/attempted = 0/0`（**不可测，不是 0%**） | `eval/results_w77_full166_applicability.json` | `2026-10-24T04:06:41Z` | `2cd6c92` | `eval/w80_gate_recompute.py` |

> 命令前缀均为 `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe`，cwd = 仓库根；完整命令串见 `eval/results_w80_final_audit.json` 的 `commands`。
> **G-3 PASS 只等于「危险 SQL 放行=0」**：`G-3 的成本闸门未测`（`cost_gate_tripped = NOT_CHECKED`；两条 COST 由 gate1 R10 拦下、未执行）；`21 条非 G-3 红队断言失败仍在`（终态形状 7 用例／截断 2／可执行前提 1；分类见 `eval/results_w80_redteam_tail.json`）。
> **G-6** 历史 p95 `11,381.8ms` 是 Ollama 未运行、检索 100% `sparse_only` 时的污染读数，只能参照；**G-8** `attempted=0` 不等于 0%，缺 17/18 补答来源。两格都保持 UNVERIFIED，见 §9。

**门禁定义**：`docs/07 §17.3`（**八格 = G-1…G-8** 的唯一定义处）＋ `eval/gates.py`（件在**仓库根**、不在 `backend/`）。
🔻 旧句写的「附录 C §C.8」那一份**只到 G-1…G-7 七格**（`04` 现读没有 G-8）⇒ 引条数前必须点名是哪一份。
判定词表 `PASS / FAIL / PARTIAL / UNVERIFIED / NOT_AVAILABLE`，`PASS` 之外一律不得进入"门禁通过"的汇总句；
八格输入的**唯一装配口** = `eval/reporter.py` 的 `gate_inputs()`，复算**只**走 `recompute_gate(格号, **产物路径)` ⇒ 在别处再装配一次就是第二份真相（QA `T-30` 判据原文）。

> **历史（已切出）**：八格逐轮的复算流水（历次 `reporter.py` 重跑、身份面取证、各轮 dirty 明细、表 B）已移到
> `../CommerceQL-archive/reports/OVERVIEW_HISTORY_2026-10-25.md` §H2。当期只认上面这张表。

---

## 8. 这个项目的另一条主线：多窗口协同的工程机制

代码之外，本仓库同时是一次"多个开发窗口（可由 AI agent 承担）在同一 `main` 上并行交付"的实践，机制本身是可复用的产出。

- **窗口划分**：W0 核心/CI、W1A 数据与冻结集、W1B 骨架、W2A–W2D 确定性核心四并发、W3A–W3C LLM 链路、
  W4 编排收口（强制单窗口）、W5 前端、W6 评测与门禁、W7 观测部署。每窗口一份 `backend/reports/wN/PROMPT.md` 开工提示词。
- **文件归属权表**（`docs/08:276-308`）：每个目录有**唯一可落笔者**。`app/core/**` 与 `cache/keys.py` 归 W0（最高冲突风险），
  `graph/**` 归 W4，`guard/**` 归 W2C，`eval/**` 执行器归 W6 而 `eval` 内容资产归 W1A……跨窗口只能"提需求"，不落别人代码。
- **取号协议**：`U-xx` 问题的唯一权威登记表在 `docs/07 §4.8`（建表起因是曾发生 7 处撞号）。规则：提新号先查表 →
  一个号只对应一件事（根因在别处须**拆号**）→ 撞车时引用面小的一方让号 → 改号必须留"原编号"行并通知引用方。
  下一可用号：只认 `docs/07 §4.8` 指针行现读（本句 2026-10-05 时为 **U-138**，**已过期、勿引**；当时现读 `:1081`；v1.7.8 / v1.7.9 / v1.7.10 / v1.7.11 / v1.7.12 / v1.7.13 / v1.7.14 / v1.7.15 / v1.7.16 / v1.7.17 **十轮均未取号**；**v1.7.18 一轮取两号 = `U-133` + `U-134` ⇒ 下一可用 `U-135`**；**v1.7.19 一轮取一号 = `U-135`（W8，X6 = `recursion_limit` 超限不写审计行）⇒ 下一可用 `U-136`**；**v1.7.20 一轮取一号 = `U-136`（W8，401 令牌过期时前端错误卡编号为空 ⇒ 立案，两条零额度判据）⇒ 下一可用 `U-137`**；**v1.7.21 一轮取一号 = `U-137`（W8，闸门 R10 不认 CTE 侧 ⇒ 产品主形态被报成越权；判据已裁、实现未落地）⇒ 下一可用 `U-138`**）。⚠️ **本行只是快照**：本项目已因"抄表取号"撞号 4 次，取号前必须读盘 + `git log --all --grep` 双向查（⚠️ 本机 `.git/refs/remotes/origin/` 目录缺失 ⇒ `git log origin/main..HEAD` **直接 fatal**，判推送状态只认 `git ls-remote origin main`）。
- **交付格式**：每轮两个 commit（`feat(wN)` + `docs(wN)`），配 `reports/wN/{DELIVERY,RELAY}.md` ——
  DELIVERY 登记交付物与实测读数，RELAY 记录跨窗转交与架构裁定。架构窗口的裁定落 `07`。
- **三条防自欺纪律**（`docs/08:398-436`，v1.3 新增）：
  ① 共享 git 索引 —— `add` 与 `commit` 同条命令、禁 `git add -A`、提交后 `git show --stat` 复核；
  ② 跑前 + 跑后双测，读数必须自带"时刻 + commit + 前置值"，缺一既不指认也不免责；
  ③ `skip` 明线 —— 判据要求"今天必红"者不得 skip；真缺前置须点名并列入 UNVERIFIED。
- **契约先行的三个单一真相文件**：`app/core/enums.py`（取值集）、`app/core/contracts.py`（跨模块 Protocol 端口）、
  `app/cache/keys.py`（缓存键）。改取值集不同步 `CONTRACT_COUNTS` 即构建失败；新增依赖须同时改
  `pyproject.toml` 白名单与契约测试，否则测试红。

---

## 9. 已知限制（不隐瞒清单）

> 本节只写**当期**仍然成立的限制。逐号的"已修／待验收／已缓解"长叙事、第 19–22 轮的靶子取证面、`U-131` 修复前后对比
> 已整体切出到 `../CommerceQL-archive/reports/OVERVIEW_HISTORY_2026-10-25.md` §H3（原字节保留、可 grep）。

### 9.1 外部阻塞：两格只能 UNVERIFIED

- **G-6（P95 ≤ 8s）**：缺三件外部输入 —— live LLM 预算（W7 估 **¥40+**）、容量决策（`U-126`：flash 槽位现 **8**，50 并发/8s 按推导需约 **38–48**）、满档 50 并发 × 10min 的**全请求分母**（429 单列）。现有 `p95 = 7268ms` **分母未标注（STALE）**，不得当作"用户端到端 P95"。
- **G-8（澄清率 ≤ 15% ＋ 澄清后一次成功率 ≥ 80%）**：缺 17/18 条 `expected=clarify` 的补答来源（业务给）＋ `U-141` 绑定型澄清路径（`bind → ambiguous → clarify_out`）＋二轮真跑。当前 16 条澄清全走 `intent → clarify_out`，`success/attempted = 0/0` —— **不可测，不是 0%**。
- **τ（L4 精排阈值）未校准**：L4 决策份额 0/166；G-2／G-5／G-7 的 PASS 标 `tau_applicability=not_exercised`（条件性非适用，**不是**校准证据）。非 `prod` 可启动但必须可见（启动 WARN ＋ 指标 `binding_tau_calibrated` 0/1）；`APP_ENV=prod` 时该检查 fail-closed。

### 9.2 设计取舍与已知短板（不是缺陷，但必须知道）

- **审计 fail-closed 换掉可用性**：审计写失败 → **不下发结果**（`INTERNAL` ＋ `trace_id`）。NFR-2.6 的有意取舍，不是 bug。
- **`/api/v1/healthz` 返回 503 ＋ `degraded_dependencies` 是设计**（`/healthz/live`、`/healthz/ready` 各自语义不同）。旧文档"阶段 0 恒 503"已过期 —— 现栈 `ready` 实测 200。
- **图表仍为降级形态**：`app/present/` 能装载产物，但 `chart_spec` / `insight` 不在该包内生成，`GraphDeps.presenter` 恒 `None` ⇒ 每轮带一条"本次未能生成图表，已用表格展示"的降级标注。
- **truncated 可观测性未达标**（N-06 / FR-8.9）：P0 的 `effective_limit` 恒 `None`（`app/graph/nodes/execute.py`），`truncated` 走退化口径。
- **embedding 不可用时检索降级**（NFR-2.7 / R-18）：Ollama 是必须独立维护的第二个模型依赖，实测单次 embedding 4.5–5.0 s。
- **P0 无物理只读副本**：同实例角色级只读 `app_ro`，不是独立只读库（PRD §8.5 / A-11）。
- **`worker` 服务无实现**：`deploy/docker-compose.yml` 的命令是 `python -m app.worker`，模块不存在；**令牌吊销只有内存版**（Redis 吊销表未落地）。
- **登录方式未裁（`D-H`）**：生产形态的页面没有登录入口。
- **`deploy/**` 游离在依赖白名单门禁之外**（P2）：`test_dependency_whitelist.py` 的 `_SCAN_ROOTS` 不含 `deploy/`，那 15 个 `.py` 的第三方依赖从没被核对过。⚠️ 不要顺手加进去 —— 会一次性点红若干条，属判据变更。
- **红队不是全绿**：G-3 的 PASS 只等于"危险 SQL 放行 = 0"（覆盖 50/50），成本闸门 `NOT_CHECKED`；另有 21 条非 G-3 红队断言失败已逐条归类（`eval/results_w80_redteam_tail.json`）。
- **所有 NFR 延迟 / 可用性 / 成本目标值都是设计目标**（PRD §17 Q-7 显式确认），首次实测后才可替换。

### 9.3 未闭问题（权威 = `docs/07 §4.8` 状态格末句）

**open 集 = 11 枚**：`U-126`（P0 槽位／几何配平）、`U-127`（P1 容量不足被伪装成"没有这个数据"）、`U-128`（P0 L4 精排静默降级）、`U-130`（P1 度量盲区）、`U-132`（P1 本机冷导入挂死）、`U-133`／`U-134`（P1 取证面默认值／本机栈凭据）、`U-135`（P1 豁免集合三态）、`U-140`（P1 压测量具形状）、`U-141`（绑定型澄清零触达）、`U-142`（多轮历史载体缺失）。

⚠️ **引用纪律**：逐号状态只认 `docs/07 §4.8` 状态格**末句原话**，本节不复制长句；判据含活体读数的号**当轮不得自写结案**；已裁的号（`U-129` / `U-136` / `U-137` / `U-138` / `U-139`）必须带限定语同框，🚫 不写光句。

**判据／口径侧三处缺口**（不占号、在案）：

1. **金标口径缺口**：GMV／订单量的语义包定义与金标不一致，`07 §16.1` 取 `complete` 最保守口径。
2. **冻结集期望 ≠ 语义包指标面**：124 条 execute 用例里 **63 条（50.8%）**要的指标在语义包里根本不存在 ⇒ 计划层按契约拒答是**正确行为**，是考卷把它标成了"该答"。未改考卷、未改判据。
3. **第二道 RLS 保证推后**：PG 面 6 条策略实测存在且有效，但评测主链路走 SQLite TEMP VIEW（替身）⇒ 保证层面未闭环（G-4 的判定词以 §7 当期表为准）。

---

## 10. 术语速查

| 术语 | 含义 |
|---|---|
| Text2SQL / NL2SQL | 自然语言转 SQL |
| EX | Execution Accuracy，执行结果与标准答案一致的题占比（本项目主口径 I-1） |
| 语义层 / 口径 | 指标的定义、公式、默认过滤条件、时间口径的版本化集合；本项目是版本化 YAML 语义包（`semantic/bundle_*.yaml`） |
| RLS / CLS | PostgreSQL 行级 / 列级安全策略；RLS 是最终强制边界，应用层过滤不得作为唯一手段 |
| 四路混合检索 | 稠密向量 + 稀疏词法(FTS) + Join 图扩展 + 值检索，RRF 融合 |
| L1–L4 绑定 | 四层绑定（表列→指标→过滤/粒度→精排），L4 为 LLM 精排，阈值 τ 决定是否降级澄清 |
| 三档门禁 | PRD §6.9：A 直接执行 / B 澄清 / C 拒答；与 UI 三态一一对应 |
| 冻结评测集 | 166 题带 `content_hash` 与沙箱库 SHA256，每次报告重新验真 |
| 红队用例集 | 66 例越权/注入/破坏性 SQL，用于 G-3 |
| 匣带 / replay | 录制-回放 LLM 后端，使评测零成本可复算；真打需 `--live --yes` |
| U-xx / C-xx | 问题回填编号 / 补充契约编号（权威表 `docs/07 §4.8`） |
| τ / ε | 绑定精排阈值 / 容差；τ 未校准 ⇒ 相关门禁只能判 UNVERIFIED |

---

## 11. 数字可信度分级（读这份文档时必须区分）

| 级别 | 内容 | 依据 |
|---|---|---|
| **A 实测** | §6 全部读数、§7 表格内所有分数、RLS 行数与策略数、pytest 计数、冷/热 p95 | 各自带文件指针与读数时刻 |
| **B 设计目标（未实测）** | G1 端到端 P95 ≤8s/≤4s、G2 自助率 ≥70%、G3 口径一致 ≥95%、G5 拒答 ≥95%、G4 越权执行成功 = **0**（硬红线）、NFR 全部延迟/可用性/成本值 | PRD `:73-77`（G1–G5）、`:570-650`（NFR 7 组）；"目标值非实测"由 **PRD §17.3 Q-7** 显式确认（`:1806-1814`） |
| **C 二手待复核** | "裸表准确率低 66%"、"澄清使 42.5%→92.5%" 等引用 | PRD §18.2 来源登记 S11–S14（`:1851-1852`），未包装为已验证事实 |
| **D 外部一手事实** | Spider 1.0 10,181 问 / 5,693 SQL / 200 库（榜单 2024-02 冻结，CC BY-SA 4.0）；Spider 2.0 632 任务、GPT-4o 仅 10.1%、要求输出 CSV、不提供预定义 schema；CSpider 榜首 test 62.1（比英文低 29 点）；CoSQL 官方把"执行/澄清/告知无法回答"并列建模；DeepSeek 当前仅 `deepseek-flash`/`deepseek-v4-pro`、`deepseek-chat` 已退役、限流按并发（2500/500）、缓存命中差 50 倍；PG 原生 `tsvector` 无中文分词 | 官方站点与 API 文档，抓取记录见仓库外 `archive/_refs/00_参考站点抓取记录.md` |

**免责**：本项目数据全部为**合成数据**，不代表任何真实企业经营数据。规模为设计目标 **3 租户 / 50 万订单 / 2,000 SKU**
（PRD §17.3 Q-8 确认按附录 C 实现），对应**实测**：沙箱已支付订单视图 494,249 行（逐租户 200,000 + 175,000 + 119,249）、
PG 侧业务事实 2,023,933 行。仓库内不放任何真实密钥（密钥只在 gitignore 的 `deploy/.env`，CI 以 gitleaks 扫全史）。

---

## 12. 想深入：按角色的阅读路径

| 你是 | 建议顺序 |
|---|---|
| 后端 / 算法 | `07` TDD（20 条 ADR → 包结构与依赖规则 → 状态机契约 → §17 门禁与不变量）→ `02` 附录 A 契约 → `README.md` §4 五条工程约束 → `backend/app/core/{enums,contracts}.py` |
| 前端 | `06` UIUX 全篇（尤其 §7 四大异常态、§8 组件×11 态矩阵、§10 SSE 客户端契约）→ `02` A.1/A.10/A.14 → `frontend/src/api/queryStream.ts` |
| 数据 / 业务方 | `03` 附录 B 口径字典 → `semantic/bundle_2026.09.14.1.yaml` → `data/generator/` |
| 评测 / 质量 | `04` 附录 C → `eval/{gates,runner,reporter}.py` → `backend/reports/w6/评测报告与门禁判定.md`（含 §10 复算指令） |
| 运维 / 部署 | `05` 附录 D 全篇 → `deploy/` → PRD §14 可观测性 |
| 评审 / 面试官 | 本文 §2 → §3 → §7（最诚实的一段）→ §8 → PRD §16 风险登记、§17 假设登记 → `07` §4 ADR |
| 新接手开发 | 本文 §5 → §6 → §9 → `docs/08` 文件归属表 + 取号协议 → 找到你要动的包属于哪个窗口，读它的 `reports/wN/{DELIVERY,RELAY}.md` |
