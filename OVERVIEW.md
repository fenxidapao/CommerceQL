# CommerceQL —— 一份文本读懂这个项目

> **这是什么**：基于 Text2SQL 的电商数据分析 Agent。用户用中文问一句业务问题，系统生成一条**受控**的 SQL，
> 在只读业务库上执行，再自动出图并给出带口径说明的结论。
> **本文定位**：不依赖任何外部讲解，读完即可理解项目的目标、架构、当前实现进度与真实质量水平。
> 它**不属于** `docs/01–08` 契约文档集，不承载契约权威（权威顺序：附录A(02) > PRD(01) > UIUX(06) > TDD(07) > 实施计划(08)）。
>
> 取证时刻：**2026-10-04 01:40 +0800**｜代码 HEAD：`b571b40`（`main`，与 `origin/main` **双向 0 偏差** = `git ls-remote origin main` 与 `git rev-parse HEAD` **同一次运行内**全等，382 次提交。⚠️ **本行自指、且必然过期**：任何一笔新提交都会让它失真 ⇒ **引用 HEAD / 提交数前必须实跑 `git ls-remote origin main` 与 `git rev-list --count HEAD`，别抄本行**）｜契约文档：**`07 = v1.7.18`**（**3,643** 个换行元素 = 正文 3,642 行 ＋ 尾空元素，两口径并报；`wc -l` 现读 3,642）、**`08 = v1.4.1`**（`wc -l` 487 ／ 切分 488）｜`07 §4.8` 下一可用号 = **U-135**（现读出处 = `docs/07_技术设计文档_TDD.md:1078` 那句"下一个可用号 = U-135"。⚠️ **本行自曝一次尺误**：16:0x 那一版这里写成了 `U-136`，依据是"正则扫全文最大号 = 135 ⇒ 下一号 136"，而全文 `U-135` 只有 **2** 处命中、两处都是**指针／变更行**而不是已落号行 ⇒ "扫到最大号 +1" 不是取号尺，取号只认 §4.8 的落号行与那句显式指针。第 5、6 轮**零取号、`docs/**` 内容一字未改**；第 6 轮的四处判据侧／计量侧缺口（金标默认谓词、指标面覆盖、上游不可用的终态归类、`l4_score` 不入累加器）**已上呈但未落号**。🔻 **10-04 02:0x 就地补记一件"位置"变化（不是内容变化）**：`docs/01–08` 与本文 `OVERVIEW.md`、`_refs/` **已进 git**（提交 `3b695a9`）—— 此前 `git ls-files docs` = **0** 而盘上有 15 个文件，`README.md:15` 又把"唯一当前真相"指在仓库外 ⇒ clone／GitHub zip 的收件人拿不到契约文档。入库内容**逐字未改**（现算 `wc -l` 07 = 3,642、08 = 487 与本行上面的读数一致），只有两处字节级副作用：① `.gitattributes text=auto eol=lf` ⇒ 入库 blob 是 LF；② `docs/*.bak-*` **七份快照不进仓库**，移到工作区外归档 `E:\01_实训\项目\CommerceQL建议删除垃圾\docs-bak-20261004\`（移动非删除）。入库前对 12 个新跟踪文件按 `deploy/.env` 现读的四条真凭据做了字面量包含检查 = **命中 0**（唯一命中的是本文里我自己落下的两个口令字面量，已按 `U-134` 既有做法脱敏成形状；⚠️ 仓库内另有 **8 个此前已跟踪并已推送**的文件仍含同样字面量 —— 那属 `U-134` 的"轮换 vs 显式豁免"未裁项，本窗不擅动））
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
  🔴 **但"出图"目前不成立**：P0 的 `app/present/` 是空壳 ⇒ 每一轮都会带一条"本次未能生成图表，已用表格展示"的降级标注
  （这不是 bug 而是 §5.3 的如实降级，见 `graph/nodes/present.py` 的模块说明）。
  后端 147 个模块文件 / 约 3.80 万行；**8 条上线门禁当前 0/8 通过**，"结果算对了"这件事**尚未成立**（详见 §7）。
  🔻 **10-03 第 6 轮就地更新（原文不删）**：本轮跑了**第一批全量真打评测**（166 题、¥0.337171、14.6 分钟），
  门禁因此从 `0/8` 变成 **`1/8`**（G-1 转 PASS：离线 2,334 ＋ 集成 107，0 红）；"结果算对了"仍然**未成立**，
  但它的含义被订正了 —— 此前引用的 `EX=0` 里有**两处是评测自己的量具缺陷**（方言桥与体积字段，见 §7），
  修后同一批的真等价数是 **3/124**；另有 **19/41** 的差落在"冻结集金标没带指标默认谓词"这一判据侧缺口上。
  🔻 **10-04 00:5x 就地再更新（原文不删）**：同一天跑了**第二批全量真打**（166 题、¥0.391504，是被测代码面的第二次读数）——
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

- 代码位置（实测行数）：`CommerceQL/backend/app/graph/build.py` 847 行（装配）、`app/graph/nodes/`
  19 个节点实现文件 + `__init__.py`/`_shared.py`、`app/graph/edges.py` 419 行（14 个 `route_after_*` 条件路由）、
  `app/graph/events.py` 735 行（SSE 发射时机）。`GRAPH_VERSION = 0.1.0`、`build.py:86 GRAPH_RECURSION_LIMIT = 25`。

**三道闸门**（`app/guard/` 共 1,732 行：`ast_gate.py` 943 + `rules.py` 261 + `policy_gate.py` 256 + `cost_gate.py` 212；
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

```
基于Text2SQL的电商数据分析Agent/
├── README.md            ← 文档集索引 + 核心主张 + 技术栈定案
├── OVERVIEW.md          ← 本文
├── docs/                ← 设计文档（只读，不进代码仓库；对开发窗口只读）
│   ├── 01_需求规格说明书_PRD.md            v1.6   18 章 1,890 行（G1–G5 目标、NFR 7 组、FR、§6.9 三档门禁、§17 假设登记）
│   ├── 02_附录A_接口契约详解.md            v1.5   A.0–A.14：全端点契约 + SSE + 图表 spec + 28 错误码
│   ├── 03_附录B_语义层与指标口径字典.md    v1.1   语义包 YAML 设计 + 10 项高危口径 + 同义词黑话表 + 生命周期
│   ├── 04_附录C_评测方案与合成数据集设计.md v1.4   C.1–C.16：双维度难度 4×3、四类指标、§C.8 上线门禁、红队
│   ├── 05_附录D_环境依赖与部署清单.md      v1.3   版本矩阵 / 依赖清单 / .env 模板 / Ollama 专项 / 部署检查清单
│   ├── 06_UIUX设计文档.md                  v1.2.2 2,691 行：Design Token、§7 四大异常态、§8 组件×11 态矩阵、§10 SSE 客户端契约
│   ├── 07_技术设计文档_TDD.md              v1.7.18 **3,643 行**（`wc -l` 3,642 ／ 按换行切分 3,643 两口径并报）／ 0–20 章 + 附录：**20 条 ADR**、包结构与依赖规则、状态机契约、§4.8 问题编号登记表、§16.5 零额度可还原面台账（**8 个面**，10-01 新加 `lg.checkpoint_writes`）、§17 门禁与不变量
│   └── 08_编程实施计划_阶段划分与窗口归属.md v1.4.1（10-02 补 `tests/integration/**` 归属行，回 QA O-4）   8 阶段 / 14 工作包 / 文件归属权表 / 取号协议 / 交接纪律
├── _refs/               ← 参考材料（Spider 官方抓取记录 + 2 张原图）与踩坑记录
└── CommerceQL/          ← 代码仓库（GitHub: fenxidapao/CommerceQL, main）
    ├── README.md         ← 工程约束版说明书（⚠️ 进度章节已过期，见 §6）
    ├── backend/app/      ← 16 个业务包，147 个模块文件 / 38,006 行（09-29 17:0x 复算**与 09-28 同值**：本轮只增文档与压测驱动，未动 `app/`）
    ├── backend/tests/    ← **107 个测试文件 / 2,041 个 test 函数**（2026-10-02 15:5x 按 **HEAD 口径**实测：unit 54 · contract 30 · eval 12 · integration 9 · redteam 1 · graph_snapshot 1；口径 = `git grep -c "def test_" HEAD -- backend/tests` 与 `git ls-tree -r --name-only HEAD backend/tests` 逐文件计数**两条独立算法互验** ⇒ 两个读数必须相等才允许落笔；`backend/tests` 下另有 `122 - 107 = 15` 个 .py 不含 `def test_`（conftest / 夹具 / 工具），不得混进"测试文件数"。⚠️ 前值 **113** 是"逐目录分项相加"得来的、分项没重测 ⇒ 已具名订正，规矩见 `reports/arch/HANDOVER.md §7.1` 第 **18** 条）
    ├── backend/reports/  ← 18 个窗口目录的 DELIVERY / RELAY / PROMPT / HANDOFF 与探针脚本、取证产物
    ├── semantic/         ← 语义包 bundle_2026.09.14.1.yaml（1,225 行）+ 口径字典 + 校验器
    ├── data/             ← 合成数据生成器 + SQLite 沙箱库（440 MB）+ schema.sql
    ├── eval/             ← 18 个执行器脚本 + 冻结集(166) + 红队集(66) + 匣带 + MANIFEST
    ├── frontend/         ← 37 个 ts/tsx / 8,412 行（09-29 复算**与 09-28 同值**）
    ├── deploy/           ← compose / Dockerfile / nginx.conf / .env.example / 压测驱动与回执 / 观测面板
    └── .github/workflows/ci.yml  ← 6 job：契约断言、W1A 产物验真、迁移闸门、依赖方向(含注入实验)、ruff+mypy、gitleaks 全史扫描
```

`backend/app/` 按依赖层级从低到高：`core`(2,326 行) → `cache`(551) → `obs`(2,675) → `repo`(4,006) →
`api`(5,231) → `auth`(639) → `semantics`(2,182) → `retrieval`(1,783) → `binding`(3,160) →
`planner`(3,039) → `guard`(1,732) → `exec`(1,085) → `mask`(379) → `llm`(2,868) → `graph`(5,604)。
**依赖方向由机器而非纪律保证**：`.importlinter` 定义 R-DEP-1（只能依赖严格更低层）、R-DEP-2（确定性模块禁 import `app.llm`）、
R-DEP-3（`obs/` 内除 `audit.py` 外禁依赖 `repo`）。

---

## 6. 当前实现进度（实测）

阶段划分：`0` 脚手架+契约固化 → `1A` 地基（语义包/合成数据/冻结集/红队）→ `1B` 骨架（认证/审计/图/checkpointer）
→ `2` 确定性核心（W2A 语义层 / W2B 检索 / W2C 闸门 / W2D 执行脱敏）→ `3` LLM 链路（W3A 网关 / W3B 理解生成 / W3C 四层绑定）
→ `4` 编排收口（W4）→ `5` 前端（W5）→ `6` 评测与门禁（W6）→ `7` 观测部署（W7）。

**已落地并可在树中核对**（HEAD `20066a5`，09-29 实测）：阶段 0–5 的交付物全部在树中；阶段 6（评测）与阶段 7（观测部署）同样已有代码与产物，
**它们缺的不是实现而是判定通过**（见 §7）。`backend/reports/` 下 18 个目录（`arch t-a1 w0 w1a w1b w2a w2b w2c w2d w2-int
w3a w3b w3c w3-int w4 w5 w6 w7`）各自留有 `PROMPT/DELIVERY/RELAY`。`app/` 的 16 个包里 **15 个有实现**，
唯一例外 `app/present/` 是空壳（呈现逻辑实际在 `app/graph/nodes/present.py`）。
🔻 **10-03 第 4 轮就地补记（原文不删）**：`backend/reports/` 现为 **20 个目录**（新增 `qa` 验收窗 ＋ `w8` 集成收尾窗，
后者即本轮的写权面）；`app/present/` 现读仍是**只有 5 行的 `__init__.py`**（`git log -1 -- backend/app/present` =
阶段 0 那笔 `15a23fc` 之后没人动过）⇒ "空壳"这句仍然成立。上面那句的 HEAD 指针 `20066a5` 是 09-29 的，
本轮现读见下面表格里"提交数 / HEAD"那一格。

**实测质量读数**

| 项 | 读数 | 出处 / 复现 |
|---|---|---|
| 提交数 / HEAD | **382 / `b571b40`**（2026-10-04 01:40 现读，`git ls-remote origin main` = `b571b40` 与 `git rev-parse HEAD` **同一次运行内全等** ⇒ 双向 0 偏差；上一读数 380 / `079916d` ⇒ L4 计量修复 ＋ 报告笔共 **＋2 笔**。⚠️ 本行自指：落报告的提交本身也计入，引用前实跑 `git rev-list --count HEAD` ＋ `git ls-remote origin main`） | `git rev-list --count HEAD` ＋ `git ls-remote origin main` |
| 后端规模 | 147 个模块文件、**38,049 个换行**（2026-10-04 01:38 现算，尺 = `git ls-files backend/app` 里 `.py` 的 `cat \| wc -l`，**HEAD 与工作树此刻同值**；含 L4 计量修复 ＋15 行）。🔴 **自曝上一读数少数 2 行**：本格 23:1x 记的是 `38,032`，而**同一棵树**（`703aae6..079916d` 之间 `backend/app` 零改动，`git diff --stat` 空）重算给 `38,034` ⇒ 差 2 行不在代码、在**我那次求和**；旁证 = 同一把尺在第 5 轮那个 rev 上重算 `e7d9442` = **37,957**，与当时登记的数**逐位相同** ⇒ 尺没问题、上一格是转录错 | 见左列命令，cwd = 仓库根 |
| 前端规模 | 39 个 ts/tsx、**8,442 个换行**（2026-10-04 01:0x 重算，与上一读数**逐位相同** ⇒ 第 6 轮前端零改动这条是被重测出来的，不是沿用：`git diff --stat 703aae6..HEAD -- frontend` 空） | `git ls-files frontend/src` 里 `.(ts\|tsx)` 逐文件行数求和 |
| 测试规模 | **128 个 `backend/tests/**.py` ／ `def test_` 共 2,089 条**（2026-10-04 01:41 现读，**HEAD 口径**（`b571b40`，此刻与工作树同值）；上一读数 127 / 2,083 = 第 6 轮 ⇒ ＋1 文件／＋6 条 = L4 用量守卫两面各三面。🔴 两把尺必须点名：`git grep -c … HEAD` 数不到**没提交**的文件，工作树尺数得到 ⇒ 提交前引 HEAD 尺会少 6 条。🔴 **111 与 126/127/128 不是同一把尺**：旧那把数的是"至少含一条 `def test_` 的文件"，本格数的是目录下全部 `.py`。用例数才是可比值） | `git grep -c "def test_" HEAD -- backend/tests`（HEAD 尺）／`grep -rc "def test_" backend/tests --include=*.py`（工作树尺）＋ `git ls-files backend/tests` |
| 本机离线门禁（**不是**评测报告那一格） | **2,293 passed / 0 failed**，面 = `tests/unit` ＋ `tests/contract` ＋ `tests/eval`，cwd=backend、rc 0（2026-10-03 15:5x 现跑，HEAD `e7d9442`；上一读数 2,291 = 第 4 轮同尺同面，差 2 条即本轮新增的两条用例）。🔴 **与下面那格 `passed=2312` 不是同一把尺**：那格是评测报告在 `8ffb53e` 上的"unit+contract ＋ integration 已跑"口径，本格含 `tests/eval`、不含 integration ⇒ 两者不相减。另：全量 `pytest -q --continue-on-collection-errors` = **2,332 passed / 9 errors**，那 9 条**全是** `tests/integration` 缺 `COMMERCEQL_TEST_{RW,RO,SUPER}_DSN` 的当场 error（U-114 设计如此：禁止 skip），⇒ 集成面本地**未跑**、CI 跑。🔻 **10-03 第 5 轮同轮就地订正（原文不删）**：这一格"未跑"已不成立 —— 用一次性库（`ecom_v1int`，建→迁移→跑→删）复算后 `tests/integration` **107 passed**、全量含集成 **2,424 passed / 0 failed**（rc 0，HEAD `f4331d7`）。⚠️ 两把尺的差在**是否给了集成 DSN**：没给时那 9 个文件在收集期就 error ⇒ 其用例根本不进分母，所以 `2,332` 与 `2,424` **不是**"回归/新增"关系。另：第一次带 env 跑出的 5 条红经三臂对照归因 = **shell 里残留的 `CORS_ALLOWED_ORIGINS` 漏进 `Settings`**（pydantic-settings 未显式给的键回落进程环境），不是被测代码，也不是集成 DSN；测试件已把这一位钉成空串。🔻 **10-03 第 6 轮在当前树重跑（原文不删）**：面 = `pytest tests -q --ignore=tests/integration`（含 `redteam`／`graph_snapshot`，比上面那把"unit＋contract＋eval"宽）= **2,334 passed / 0 failed**，集成层同树重跑 **107 passed** ⇒ 一次性库换成 `ecom_w8int` 重建后跑完即 DROP（现查 `pg_database` 里 `ecom_%` = 1，只剩共享库）。这两栏就是 §7 那格 G-1 转 PASS 的输入。🔻 **10-04 01:2x 在当前工作树（含 `l4_score` 计量修复）重跑同尺**：离线面 = **2,340 passed / 0 failed**（`pytest tests -q --ignore=tests/integration`，rc 0，90.01s；比上一读数 ＋6 = 两条 L4 用量守卫）；集成面 = **107 passed / 0 skipped / 0 failed**（一次性库 `ecom_w8int2`：建→授权→owner→alembic 到 0005→跑→**当场 DROP**，rc 0，27.44s）。🔴 **这两次复算各逮到一件我自己的错**：① 第一次集成跑给的是 `1 failed / 60 passed / 37 skipped / 9 errors`，逐条看错误行 = `psycopg.ProgrammingError: missing "=" after "postgresql+psycopg://…"` ⇒ **四个测试 DSN 必须是 libpq 形态（`postgresql://`，不带 `+psycopg`）**，`psycopg.connect()` 不认这个后缀，而 `MIGRATION_DATABASE_URL` 反过来**必须带**（SQLAlchemy）—— 修表单变量后才是上面那个 107，**那 38 条红没有一条是被测代码的**；② 上一轮那句"残渣尺现查 `ecom_%` = 1，只剩共享库"**是错的**：SQL 的 `LIKE 'ecom_%'` 里 `_` 是**单字符通配**，而共享库名 `ecom` 本身**不匹配**这个模式 ⇒ 那个"1"是别窗留下的 **`ecom_u123_probe`（10 MB）**，不是共享库。⇒ 残渣尺改成 `datname like 'ecom%'` 并报数：现测 **2 个**（`ecom` 505 MB ＋ `ecom_u123_probe` 10 MB）；那个探针库**不是本窗造的，未经它的属主／总控同意不删**。 | `cd backend && PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest tests -q -p no:randomly --ignore=tests/integration` ＋（集成，一次性库四个 DSN）`pytest tests/integration -v`；整段命令见 `backend/reports/w8/RELAY.md` §六.10 |
| 静态与方向门禁 | `ruff check .`（cwd=backend）**0 条**；`mypy app` = no issues in **147** files；`lint-imports` = **4 kept / 0 broken**（🔴 必须带 `PYTHONUTF8` ＋ `PYTHONIOENCODING`，否则它自己会 `gbk` 崩在输出行上、给出假红）；W1A 四件自检 ＋ `python -m app.core.enums` 全 rc 0 | 逐条命令见 `CommerceQL/backend/reports/w8/RELAY.md` §四.8 |
| DoD④ 本机替身 | 全仓重放 `.gitleaks.toml` 的 DSN 规则 ⇒ **零未放行命中**（治理前 43 处；`tests/unit/test_migration_dsn_hygiene.py` 8 passed）。⚠️ 本机未装 `gitleaks` ⇒ 这一格是**替身**，真门仍在 CI | `cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_migration_dsn_hygiene.py -q` |
| 反证类门禁 | ⑱ 形状守卫：`t23_negative_gate.py` 在一次性库上 **8 项全过**（pre-fix 对照件复现假绿、新版逐行降为不可判、⑰c 有行 = 4）；三面尺 `shape_guard_faces.py` 现算 **F-pred=8／F-guard=6／F-consume=5**；两者已挂进 CI 新 job `t23-shape-guard-gate` | `CommerceQL/backend/reports/w8/t23_negative_gate_receipt.json`（含 `git_rev`／`git_dirty` 自报） |
| 部署面暴露（A5） | compose 五个发布端口只绑宿主回环，**声明面**（`docker compose config` → 5 条 `host_ip: 127.0.0.1`）与**运行面**（`docker ps` 五条 `127.0.0.1:P->P`；`netstat` 的 LISTENING 里这四个端口无 `0.0.0.0` 行）两面都量过；recreate 后 `healthz/live`／`healthz/ready`／`web` = 200／200／200，`app.embed_doc` 仍 **197 行** | `docker compose -f deploy/docker-compose.yml config` ＋ `docker ps --format "{{.Names}} {{.Ports}}"` ＋ `netstat -ano -p tcp` |
| 活体构建面（10-03 换构建 ＋ 第 5 轮三次重建后） | 共享 `:8000` 现＝HEAD 级构建（`e7d9442` 那批代码）：容器内 `/srv/app` 的 `.py` = **147**（旧镜像 79）、`openapi.json` path = **12** 且含 `/api/v1/query`、启动断言 **4 passed / 0 pending**、`ready` = **200**。构建身份的实证方式**不看时间戳**而在容器内 import 后读函数体：`meta_payload(Decimal, 分项字典)` 返回 `cost 0.003821(float) / latency 7219(int)` ＋ `gen_sql_v1.txt` 内含"不带 schema 前缀" ⇒ 两条都在构建面上。🔴 **端到端已跑过**（第 5 轮，浏览器 → nginx 同源 `/api/v1` → api → DeepSeek → PG（RLS）→ SSE → 表格）：5 次 run 打出四种终态各至少一次 —— 正常出数（5 行真实聚合值）、R05 拒（`GATE_AST_REJECTED`）、PLAN 自拒（`no_data_asset`）、空结果（`该条件下没有数据`），且降级条／错误卡／拒答卡的形状都核过。⇒ 现在**可以**写"链路能跑通、四类出口会如实呈现"，**仍然不可以**写"数字算对了"（🔻 10-03 第 6 轮：§7 的 EX 已由"0/11"订正为 **3/124**，其中两处 0 的成因原本在量具上）。🔻 **10-03 第 6 轮重建 `api`（镜像含闸门四处修复）后再走一次浏览器**：同一题（"T_A 从 2026-06-01 起的 GMV 是多少？"）问了两遍 —— 第一遍 `normalize` 撞 15s **生产契约**超时 ⇒ `template_only` ⇒ 终态 `refuse`，UI 文案"系统里没有这类数据"（**真实原因是上游，不是没有数据**，见 §9 那条 P1）；第二遍正常出表 `gmv = 30768819.37`，与评测沙箱对同一题的复算值**逐位相同** ⇒ 生产链路与评测链路同口径，且这道题在修复前是被 `GATE_AST_REJECTED` 打死的；耗时 15.6s／成本 ¥0.003221／语义包 2026.09.14.1／任务号都在口径条里，两帧降级都喊了出来，同题连问不再 `INTERNAL`。⇒ **单条真实问句 15.6s 已经高于 §7 G-6 的 8s 预算**，这一格不许只引回执里那个 7,268ms。🔴 **10-04 01:0x 现算发现上面那次走查的构建面落后一件**：容器内 `import app.planner.payloads` → `hasattr(…, 'TENANT_SELF_REFERENCE_NOTE')` = **`False`**（而闸门那四处 `_clause_key_of`／列面守卫在位）⇒ **"镜像＝HEAD 级"这句对载荷改动不成立**，那一轮的活体读数不能算它的面。⇒ 本轮**两次 `docker compose build api` ＋ `--force-recreate`**（镜像 `a3b14d1d597c` → `c97ef6d353f8`），三层构建指纹重取：容器内 `/srv/app` `.py` = **147**、`openapi.json` path = **12** 且含 `/api/v1/query`、import 实证 = `ScoreOutcome` 字段集含 `tokens`/`cost_cny` ∧ `TENANT_SELF_REFERENCE_NOTE` 在位 ∧ `bind` 源里含 `record_usage`，`/api/v1/healthz/{live,ready}` = **200/200**（🔴 裸 `/healthz/ready` 在 Round-5 加了 API 前缀之后是 **404**，引探针 URL 必须带 `/api/v1`）。**新构建上的走查（01:2x–01:4x）**：同一题连问 4 遍 —— 3 遍撞 `normalize` 的 **15.0s 生产契约超时**（`node_timeout_degraded`，`limit_s=15.0`）⇒ `template_only` ⇒ `refuse` ＋ 文案"系统里没有这类数据"（§9 那条 P1 又复现一次；⚠️ 同容器内现量 `api.deepseek.com` 的 DNS **0.07–0.18s**、TCP **0.12–0.18s**，3/3 ⇒ 这次**不是解析抖动**，且这半小时本机同时在跑 pytest／build／回放 ⇒ **该时段活体延迟被本地负载污染，不许引成 G-6 证据**）；1 遍正常出表 `gmv = 30768819.37`（与评测沙箱、与前两轮**逐位相同**），**耗时 7.3s ／ 成本 ¥0.004312**，且 `app.cost_ledger` 里该 run（`tk_b6ad2288…`）4 档调用 sum = **¥0.004312** ⇒ **口径条与落库面首次闭合**（修复前同题是 `¥0.003288` vs `¥0.004670`，见 §9 的 L4 那条）。顶栏另现"本分钟剩余 9 次"（限流桶可见）。 | `docker exec commerceql-api-1 find /srv/app -name "*.py" \| wc -l` ＋ `curl -s http://127.0.0.1:8000/api/v1/openapi.json` ＋ `docker exec commerceql-api-1 python -c "from decimal import Decimal as D; from app.graph.events import meta_payload as m; print(m({'cost_cny': D('0.003821'), 'latency_ms': {'total': 7219}}, bundle_version='b'))"` ＋（同口径复现走查）`deploy/runbook/README.md` §5.1 |
| 测试通过数（**unit+contract 口径，非全量**） | 2026-10-02 15:5x 复核**已入库**那份报告（生成于 `2026-10-02T06:11:47+00:00`、报告自述代码版本 `8ffb53e`、入库提交 `e775464`）：**`passed=2312`、断言失败 0、环境未备 8（收集期 8 / 夹具期 0）、PASS 0/8** | 出处 = `backend/reports/w6/评测报告与门禁判定.md` §1，架构取数用 `git show HEAD:…`（**不读工作区**；本轮实测 HEAD 版与工作区版**逐字相同**）。🔻 **10-03 第 6 轮该格已重算**：`G-1` 转 **PASS**（红 0 条；离线 2,334 ＋ 集成 107），环境未备那 8 条随一次性库配方消解 ⇒ 本格左上那串旧数只作历史读数保留。🔴 **`PASS 1/8` ⇒ 对外仍不得写"门禁通过"**；⚠️ 历史读数保留：更早四轮曾报 `passed=2238` / 断言失败 2、`passed=2248` / 断言失败 0、`passed=2255` / 断言失败 0、`passed=2258` / 断言失败 0，那 2 条断言失败经归因 = **环境红**（`U-132` 触发面：冷导入 SQLAlchemy 挂死、间歇），不得把"这次 0"读成"上次不存在" |
| PG 侧 RLS | 6 条 `p_<table>_tenant` 策略在位、6 表 `FORCE ROW LEVEL SECURITY`、2,023,933 行业务事实数据；逐租户可见数求和恰等于属主总数，零上下文与未知租户两条负对照均返 0 行 | W6 报告 §5/§9；RLS 与列级 GRANT 由 `semantics/materialize.py:133 derive_policy_statements` **派生**，非手写 |
| 活体三态 | 第 10 轮预检 `outcomes={ok:3, clarify:1, refuse:1}`、六个 stage 全亮；第 11 轮 `ok:2/clarify:2/refuse:1`、`retrieval_mode_total{hybrid}=2` | `backend/reports/w7/DELIVERY.md`（镜像 `0923r7` / `0923r8`） |
| 冷/热延迟 | p95 72,768.7 ms → 1,345.7 ms | 同上（**该 p95 的分母口径未标注，不得当作"用户端到端 P95"**） |

⚠️ `CommerceQL/README.md` 的"当前进度"表停留在 2026-09-16（写的是"阶段 0 完成、1A/1B/2–7 未开始"），**已过期**，读进度看本节。
🔻 **10-04 01:5x 重读 `README.md` —— 这一句已经不适用了，就地订正**：那张表**已被删除**，`README.md:12-15` 现在写的就是"进度与上线门禁的唯一当前真相 = 根 `OVERVIEW.md` §6/§7"
⇒ 入口不再互相打脸。⚠️ 但同一节 `README.md:28` 那句 `# 阶段 0 期望 503（硬依赖未接）` **仍是旧的**（当前栈 `/api/v1/healthz/ready` 实测 **200**）⇒ 本轮已改成"就绪即 200，503 属阶段 0 旧形状"。

---

## 7. 质量现状：上线门禁 1/8（这一段是本项目最诚实的部分；🔻 10-03 第 6 轮之前是 0/8）

**门禁定义**：附录 C §C.8 + `eval/gates.py` 的 G-1…G-8，判定词表 `PASS / FAIL / PARTIAL / UNVERIFIED / NOT_AVAILABLE`，
`PASS` 之外一律不得进入"门禁通过"的汇总句。

**最新一份报告**：`CommerceQL/backend/reports/w6/评测报告与门禁判定.md`，由 `eval/reporter.py` 于
**2026-10-04 00:47 +0800** 从 rev `0ff8f73` 那棵树重算（输入件 = `eval/results_v1.json` = **第二批全量真打**，
它**自己声明** `git_rev=b97920d` ＋ `git_dirty=True`（脏的那一份是在写的 `reports/w8/RELAY.md`，不是被测代码）
⇒ G-2／G-5／G-8 的取证等级仍是 **`self_reported`**；⚠️ 因此下面八格那三个质量数**只属于 `b97920d` 那棵树** ——
现算尺 `git diff --name-only b97920d 079916d` 给出 7 个文件、`backend/app` ＋ `eval/gates.py` ＋ `eval/reporter.py` 侧 **0 个**
⇒ 它与第一次真打**同一被测代码面**、可比。LLM 后端 = **真打**（`--live`，166 题 ¥0.391504）。
🔴 **但 10-04 的 `l4_score` 计量修复落在这份读数之后**（见 §9 那条 P1）⇒ 成本／token 两栏是**修复前口径**（下限），
其余七格不受影响（成本与 token 不进任何一格的判据）。
旧指针（`8ffb53e` / `2026-10-02T06:11:47+00:00` / replay 匣带 / `passed=2312`）与第一次真打那份（rev `66d5fba`／¥0.337171）
都作为**历史读数**保留，不删。
**总判定 PASS 1/8**：`G-1 PASS · G-2 FAIL · G-3 PARTIAL · G-4 PARTIAL · G-5 FAIL · G-6 UNVERIFIED · G-7 FAIL · G-8 UNVERIFIED`。

| 门禁 | 目标 | 本次实测 | 为什么不能算通过 |
|---|---|---|---|
| G-1 全部 P0 用例通过 | 0 红 | **PASS**（🔻 10-03 第 6 轮转绿，10-04 01:4x 在**含 L4 计量修复的当前树**上重跑同尺仍绿）：断言失败 **0** ＋ 环境未备 **0** ⇒ 红 **0** 条；规模 **离线 passed=2,340 ＋ 集成 passed=107**，`integration_ran=True` | 已满足判据。⚠️ 两栏必须分开报：`gate_inputs()` 合并两份日志时曾把 `passed` 覆盖成集成层那一个数（107），直接引它会把 107 读成全量规模。🔴 **另一把形状尺**：`reporter` 判"集成跑没跑"是靠**日志里有没有集成文件名** ⇒ 集成层必须 `-v` 跑；用 `-q` 跑真 107 条、`integration_ran` 仍给 `False`、G-1 当场从 PASS 掉到 PARTIAL（10-04 本机实测两遍）。🔻 旧读数（FAIL／红 8 条＝环境未备 8、unit+contract `passed=2312`）保留：那 8 条是 PG DSN 权限（`U-132` 触发面），不是被测系统；更早的 2 条断言失败经三臂对照归因 = 环境红，连续多轮重跑均为 0。集成层复算命令见 `backend/reports/w8/RELAY.md` §六.10 ＋ §六.16（一次性库，禁指共享 `ecom`） |
| G-2 结构 Easy × 语义低 ≥95% | ≥95% | easy×low **0/10 = 0.0%**（🔻 10-04 00:47 第二批真打重算；数值未变、**成因已换**） | 十条现在整整齐齐走到 `intent>link>plan>refuse_out`（10/10 出口理由 `no_data_asset`）⇒ 红点**从"理解阶段"移到了"计划层的指标面"**（§9 那条 P1 判据侧缺口）。🔻 第一次真打那版（9 条澄清 ＋ 1 条拒答、匣带原文 `reason_code=unmapped_entity`、提示语"「T_A」无法映射到任何已登记实体"）保留：那是租户码自指被当未映射实体的形状，载荷说明落地后不再出现；τ 未校准污染 L4 判据（R-19） |
| G-3 危险 SQL 放行 = 0 | 0 | 放行 0 / 覆盖 48（应拦 50） | 2 条成本闸门用例沙箱无 EXPLAIN ⇒ gate3 恒 SKIPPED |
| G-4 跨租户泄露 = 0 | 0 | 跨租户行 0 | **评测主链路走 SQLite TEMP VIEW**，"应用运行时经 PG 执行并设好 `app.tenant_id`" 那一跳未测；且 PG 并行/串行不等值（占位符 GUC 不随 worker 传值） |
| G-5 拒答 ≥95%、误拒 ≤5% | ≥95% / ≤5% | 该拒则拒 **19/24 = 79.2%**（未变）；误拒 **63/124 = 50.8%**（🔻 10-04 00:47 第二批真打；第一次 43/124 = 34.7%，更早已往 3/5=60% 与 4/12=33.3% 是小样本） | 🔴 **涨了 20 点，但这不是新缺陷**：63 条 `execute→refuse` 逐条看，出口理由 **100% 是 `no_data_asset`**、最后节点 **100% 是 `plan`**（不是 intent、不是闸门）⇒ 是同一批题被从"澄清"推进了"拒答"（G-5 罚后者、不罚前者）。按金标投影拆：**34 条 `COUNT` 形态 ＋ 29 条未声明的列级聚合**，而语义包只有 9 个 `metrics` ⇒ 天花板在**考卷与考纲不同源**那条判据缺口上（§9）；闸门自伤修完后 43 条里已无 `GATE_AST_REJECTED`。τ 未校准 |
| G-6 P95 ≤8s | ≤8s | P95 7,268 ms | 准入样本 5 < `MIN_ADMITTED_FOR_P95=20`；回执该场景 0 条真正完成 ⇒ **不可判达标**。⚠️ 另加一条不可引用的理由：10-04 00:5x–01:2x 本机同时在跑 pytest／`docker build`／回放 ⇒ **该时段的活体延迟被本地负载污染**，那一小时内浏览器单问的 8.5s／15s 超时都不许当 G-6 证据 |
| G-7 口径一致 ≥95% | ≥95% | 一致 1/13=7.7%，不可归因差异 0 | 本项目**无外部 BI 权威值**可引，比对基准只能降级为"内部口径一致性" |
| G-8 澄清率 ≤15% 且澄清后一次成功 ≥80% | 两条同时 | 澄清率 **30/166 = 18.1%**（🔻 10-04 00:47 第二批真打；第一次 54/166 = 32.5%，更早期 9/20=45%），一次成功 0% | 后半句**结构上不可测**：跑批器**没有** "澄清→补答→再走一次" 的第二轮回路 ⇒ 整条判 UNVERIFIED（既非 FAIL 也非 PASS）。⚠️ 左半虽然从 32.5% 降到 18.1%、距 ≤15% 只差 3.1 点，**也不得读成"接近达标"**：降下来的那 24 条是搬去 `refuse` 了（见上一格），不是搬去"答对" |

**必须先说清的一件事**：EX（执行结果正确率）在 124 条 execute 用例上为 **6/124 = 4.8%**
（等价件：`E-MET-10`／`M-DIM-03`／`M-IDX-07`／`M-IDX-08`／`M-MET-06`／`M-MET-07`；🔻 10-04 00:47 第二批真打，
第一批同树同尺是 **3/124 = 2.4%**（`E-MET-10`／`M-MET-06`／`M-MET-07`），更早的 `0/11` 见下面那段量具订正）。
也就是说：**"链路能跑通、能出表、三态出口都会用"已经成立；"算出来的数字是对的"尚未成立。**
这是本项目当前与目标之间真实存在的距离，不是措辞问题。
⚠️ 分母也换了口径：`n_execute_with_sql` 41→**45**（更多题走到了 SQL）⇒ 下面"四十一分之几"那组数属于**第一批**，
第二批的同名尺要重算才能引（探针零额度，见 §9 那条判据缺口的复算命令）。
🔻 **但"0"这个数要单独订正**（10-03 第 6 轮）：本轮之前各处引用的 `EX=0`（含本报告早先那句 `0/11`）里有**两处成因在评测自己的量具上** ——
① `run_in_sandbox` 不做 `%(name)s → :name` 方言桥 ⇒ 凡带绑定参数的被测 SQL 在沙箱恒 `OperationalError: near "%"`（金标不带参数，所以只有预测侧被打死）；
② 预测侧的表读 `state["result_rows"]`，而 07 §5.2.1 把 `result_rows` 定为**体积字段**（行只进 `context.hold_rows`，不进 state）⇒ 恒 0 行。
两处修好后同一批真打件复算得 **3** 条等价（`tests/eval/test_scorer_sandbox_path.py` 三条守卫守住这一层，含一条 AST 形状尺）。
方法论教训入册：**判据装置坏的时候所有读数会安静地变成 0，而离线门禁全绿** ⇒ 任何"整列为 0"的读数，先证明量具能产出非 0。
另有 **19/41** 条"差一个默认谓词"（金标没带语义包声明的 已支付·非退款·非测试单 过滤，而链路会注入）⇒ 那是**判据侧待裁**，不是能力缺口；
剩下 **19/41** 条加上默认谓词仍不等价 ⇒ 那才是真能力缺口。详见 `backend/reports/w8/RELAY.md` §六.4／§六.5。

09-22 之后（09-23）只有上表的 W7 活体预检读数，**未重算门禁报告**。复算指令清单见该报告 §10（零 LLM 优先，真打需额度）。

🔴 **10-03 第 4 轮的状态声明**（不改上表任何一个格，只补一句"这一轮动了什么、没动什么"）：
本轮**没有**重跑评测（`--live` 要额度，四件套未报未批）⇒ 上表八格读数**全部沿用** `8ffb53e` 那份，
`PASS 0/8` 未变 ⇒ 对外仍不得写"门禁通过"。本轮真正改变门禁的是**门的形状而不是判定词**，四件事：
① DoD④ 的规则面与承诺面对齐（旧规则只认 `postgresql+psycopg://`，且 `keywords` 预筛是**第二个独立
失明面** ⇒ 承诺"属主口令必红"却扫不到纯 scheme；现已对齐并把豁免钉在"引导值 × 回环主机"上）；
② 装载器与四条探针不留"指向共享 `ecom`"的字面默认 DSN，且**尺子本身补了一处盲区**
（带注解的模块常量 `NAME: Final[str] = "…"` 原先不进静态求值表 ⇒ 整仓静默漏网）；
③ 两条以前"只能靠人记得"的纪律变成会红的门：⑱ 形状守卫的反证夹具接成 CI job（两侧断言：
旧版必复现假绿、新版必降不可判），compose 端口"只绑回环 ＋ 宿主端口不重号"进契约测试；
④ 闸门输入件自报构建身份（`git_rev`／`git_dirty`）—— 但 🔴 **`eval/results_v1.json` 在 ¥0 下重建不出来**
（回放 rc=0 而 `n_scored=0`、166 条 `cassette_miss` ⇒ 匣带键对着更早的 20 用例集），
所以 G-2／G-5／G-8 的输入件取证等级**仍停在** `mtime_only`，这一格是本轮唯一"改了代码但没改到取证等级"的欠账。
§6 那格 `本机离线门禁 = 2,291 passed` 与 §7 引用的 `passed=2312` **不是同一把尺**（面与时点都不同），
两者都保留、不相减。

🔴 **10-03 第 5 轮的状态声明**（同样不改上表任何一个格）：本轮**仍未**重跑评测 ⇒ 八格读数与
`PASS 0/8` **全部沿用** `8ffb53e` 那份，对外仍不得写"门禁通过"。本轮动的是**验收面本身**：
第一次把页面在浏览器里打开（前四轮的"可用"全部建立在离线门禁 ＋ curl 上），一次走查打出
**8 处 v1 阻断面**（前端 4 ＋ 后端/部署 4），全部修掉并各自带回归。其中三处值得写进质量现状：
① 契约测试的夹具**照抄了实现**（`meta.latency_ms` 字典、`cost_cny` 字符串），所以它对"形状偏离
契约"全程失明 —— 契约测试的夹具值必须来自契约文档；② 一次"更清楚"的措辞改动打在**共用摘要**上，
等于改了 PLAN 的判据（改前 2 次出计划／改后 2 次自拒），而 1,888 条离线用例全绿 ⇒ 已回退并补反证；
③ 面向人的判据（页面打得开 ≠ 链路可用）此前**不在任何一轮的收尾清单里**。
本轮花了 **¥0.058674**（5 run / 28 调用，`cost_ledger` 现算），是本项目第一次为验收花钱。
细节与复算命令：`CommerceQL/backend/reports/w8/RELAY.md` §五。

🔴 **10-03 第 6 轮的状态声明**（第一次全量真打 ＋ 三处"我们自己的器件"缺陷）：本轮**跑了** `--live` 全量 166 题
（¥0.337171／1,637,722 tokens／14.6 分钟，跑前计划打印 ¥0.332 ⇒ 估子偏差 +1.6%），八格全部重算，
`PASS 0/8` → **`1/8`**（G-1 转 PASS）。对外仍**不得**写"门禁通过"。本轮真正值得记的是三条归因方向：
① **32 条 `GATE_AST_REJECTED` 里 30 条是闸门自伤**（逐条复算：模型编造的列 = **0 条**；F1 排序键写投影别名 15 条、
F2 按域注入出不存在的列 8 条、R14 打死算术位数值字面量 8 条 —— 而**冻结集金标自己就有 10 条 `NULLIF(x, 0)`**、
R04 打死参数化 `LIMIT` 2 条），四处已修并各带反证；同匣带零成本回放显示 **error 32→2、complete 12→42，
30 次翻转全是 `failed→success`、0 反向**。
② **`EX=0` 有两处是量具**（上一条 §7 已订正）。
③ **两处缺口属判据侧，本窗未擅自改**：金标的默认谓词口径（19/41）与"上游不可用被收口成 `no_data_asset`"
（凭据失效／超时会打成"系统里没有这类数据"这句用户可见文案）⇒ 都上呈待裁，`docs/**` 一字未改、零取号。
另外本轮把 §五.10 欠的**集成面复算命令**补全（一次性库建→迁移→107 passed→DROP＋残渣尺），
并自曝三条方法论错误（前缀外推报价、量具零覆盖、读数写了命令没写）。
细节与复算命令：`CommerceQL/backend/reports/w8/RELAY.md` §六。
🔴 **仍欠的一件事**：理解阶段那条"租户码自指不算未映射实体"的改动**没有评测读数**（`UNVERIFIED`）——
23:03 之后两次子集试跑全部降级、实花 ¥0。🔻 **原因我第一版写错了，现按两把 key 的实测对照订正**：
`deploy/.env:35` 那把（尾号 `23e8`）直连 `/chat/completions` = **HTTP 200**；挡住它的是 **Windows 用户级环境变量**里
另一把同名 `DEEPSEEK_API_KEY`（尾号 `d46d`，**HTTP 401 `api key is invalid`**），因为 `eval/_bootstrap.py` 用
`os.environ.setdefault` ⇒ **进程环境赢**。⇒ 要做的动作不是换 key，而是 `env -u DEEPSEEK_API_KEY` 后重跑 `--live`
（演示栈不受影响：`api` 容器读到的是 `23e8`，所以浏览器那一问真跑成功）。
🔻🔻 **同轮第二次订正（那句 `env -u` 的处方也不成立）**：`eval/_bootstrap.py` 压根不读 `deploy/.env`，它只把
`DEEPSEEK_API_KEY` **占位值** `sk-placeholder-not-a-real-key` `setdefault` 进去 ⇒ 清掉进程环境后拿到的是占位串，照样 401。
真正可行的姿势 = **显式覆盖**再跑：`DEEPSEEK_API_KEY=$(sed -n 's/^DEEPSEEK_API_KEY=//p' deploy/.env) .venv/Scripts/python.exe eval/runner.py --live …`
（值只在子 shell 里解析，不落任何文件、不进终端历史）。⇒ 这一错连累出的方法论：**"拿机制推理代替实测"我犯了两次**（第一次断言"密钥失效要换"、第二次断言"`env -u` 就好"），
两版都是在**没有对照臂**的情况下写下的；两次都由"各发一发 curl / 各跑一次批"当场推翻。

🔴 **10-04 00:5x–01:2x 第 6 轮的第二批真打（同一棵被测树，唯一变量=理解阶段的载荷改动 ＋ 闸门修复都在里面）**：
又跑了一次 `--live` 全量 166 题（**¥0.391504**／1,836,623 tokens／墙钟中位 3.134s、最长 26.48s），八格全部重算、报告重生成，
`PASS` **仍是 1/8**（唯一变绿的还是 G-1）。变化与归因：
① 链路**明显变深** —— 终态 `complete` 12→**48**、`error` 32→**1**、`clarify` 54→**30**、`n_execute_with_sql` 41→**45**、EX **3→6/124**；
② G-5 误拒 43→**63**（50.8%）、G-8 澄清率 32.5%→**18.1%**、G-2 仍 0/10 但成因从"理解阶段"换成"计划层"
—— 三条是**同一件事**：22 条题被推过理解阶段后全部撞死在 `plan`（63/63 出口理由 `no_data_asset`、63/63 最后节点 `plan`）；
③ 🔴 **主阻塞因此换形**：这 63 条按金标投影拆 = 34 条 `COUNT` 形态 ＋ 29 条未声明的列级聚合，而语义包 `metrics:` 现读 **9 个**
⇒ **"考卷 ≠ 考纲"的第二处判据侧缺口**（§9）；本窗**不擅自扩包、不改冻结集、不改判据**，两条杠杆（改内容 ⇒ 重录 ≈¥0.4；改判据 ⇒ 不动代码）都上呈待裁；
④ 🔴 **本轮最后一件实测收获是又一个自家器件缺陷**：走查那条 run 的口径条写 `¥0.003288`、同一条 run 落库面 sum `¥0.004670`，
差值恰为 `l4_score` 那一档 ⇒ `record_usage` 少一个调用点（`bind`）⇒ 成本与 token **长期少算一整档**，
本轮此前报的所有花费数因此是**下限**；已修（`ScoreOutcome` 带出用量、失败态也带 ＋ `bind` 入累加器 ＋ 两条三面守卫），
`docs/**` 仍一字未改、**零取号**（建议归入 `U-130` 的第二触发面，待裁）。
细节与复算命令：`CommerceQL/backend/reports/w8/RELAY.md` §六.15 起。

---

## 8. 这个项目的另一条主线：多窗口协同的工程机制

代码之外，本仓库同时是一次"多个开发窗口（可由 AI agent 承担）在同一 `main` 上并行交付"的实践，机制本身是可复用的产出。

- **窗口划分**：W0 核心/CI、W1A 数据与冻结集、W1B 骨架、W2A–W2D 确定性核心四并发、W3A–W3C LLM 链路、
  W4 编排收口（强制单窗口）、W5 前端、W6 评测与门禁、W7 观测部署。每窗口一份 `backend/reports/wN/PROMPT.md` 开工提示词。
- **文件归属权表**（`docs/08:276-308`）：每个目录有**唯一可落笔者**。`app/core/**` 与 `cache/keys.py` 归 W0（最高冲突风险），
  `graph/**` 归 W4，`guard/**` 归 W2C，`eval/**` 执行器归 W6 而 `eval` 内容资产归 W1A……跨窗口只能"提需求"，不落别人代码。
- **取号协议**：`U-xx` 问题的唯一权威登记表在 `docs/07 §4.8`（建表起因是曾发生 7 处撞号）。规则：提新号先查表 →
  一个号只对应一件事（根因在别处须**拆号**）→ 撞车时引用面小的一方让号 → 改号必须留"原编号"行并通知引用方。
  下一可用号 = **U-135**（`docs/07 §4.8` 末段**行首**，2026-10-02 15:5x 实测；v1.7.8 / v1.7.9 / v1.7.10 / v1.7.11 / v1.7.12 / v1.7.13 / v1.7.14 / v1.7.15 / v1.7.16 / v1.7.17 **十轮均未取号**；**v1.7.18 一轮取两号 = `U-133` + `U-134` ⇒ 下一可用 `U-135`**）。⚠️ **本行只是快照**：本项目已因"抄表取号"撞号 4 次，取号前必须读盘 + `git log --all --grep` 双向查（⚠️ 本机 `.git/refs/remotes/origin/` 目录缺失 ⇒ `git log origin/main..HEAD` **直接 fatal**，判推送状态只认 `git ls-remote origin main`）。
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

- 🔴 **同租户内跨属主会话可读（P0，编号 `U-131`；🔻 2026-10-04 17:2x +0800 @ HEAD `4a070ae`：本格原写"未修"，现状态 = 修复已落地、待验收）**：
  修法落在 `backend/app/api/state_store.py` 的**单一强制点**（`get_session` 比对载荷属主，不符或缺失一律返回 `None` ⇒ 两个端点现有 404 分支自动生效），
  键与键族**一字未动**；`backend/tests/contract/test_api_endpoints_contract.py` 新增 7 条同型断言（跨属主 → 404、属主 → 200、修复前旧载荷 fail-closed）。
  ⚠️ **不得据此写"跨用户隔离已达成"**：门禁 8 格里 `PASS 1/8` 未变，且本号的三面活体取证仍待验收窗独立复算（读侧／写侧已 404，推理侧＝非属主请求根本没进图）。
  下面那段是**修复前的历史读数**（保留原文，不得当现状）：会话元数据键 `sess:meta:{tenant}:{session_id}` **只到租户级**、载荷里**没有属主** ⇒ 同一租户内任何合法令牌都能读他人会话。活体（09-28，只读探针）：非属主 `POST /query` = **200 + 完整 SSE 流**、`GET /session/{id}` = **200 且他人轮次可读**，而契约（附录 A §A.11）期望 **404 `SESSION_NOT_FOUND`**。⚠️ **09-29 W7 补第三面：写侧同样失守** —— 非属主带着自己的令牌**把追问写进了属主会话**（该会话回合数 1 → 2），⇒ 结案判据改为**三面同交**（读 404 / 写 404 / 推理侧不适用或补一轮打到 `gen_sql`），**只交读侧不得转绿**。⇒ 修复判据见 `07 §4.8` 的 U-131 行；**在修复落地前，任何"跨用户隔离"的正面结论都不得引用**。⚠️ 这是本项目**第一条同租户内跨用户**的越权 —— 既有隔离证据全是**跨租户**的，所以它不在原门禁覆盖面里。

- 🟡 **`deploy/**` 游离在依赖白名单门禁之外（P2，10-03 现测登记，未修）**：
  `backend/tests/contract/test_dependency_whitelist.py` 的 `_SCAN_ROOTS` =
  `backend/app`／`backend/tests`／`backend/scripts`／`semantic`／`data`／`eval` ⇒ `deploy/` 那 **15 个 `.py`**
  （顶层 import 含 `httpx`／`uvicorn`／`psycopg`，还有一个 `deploy/loadtest/_w2b_u112_materialize` 这类
  裸模块名）从来没有人核对过"直接 import 的第三方包是否在 `pyproject` 里声明"。
  ⚠️ **不要顺手把它加进 `_SCAN_ROOTS`**：加了会一次性点红若干条（同 `T-19` 扩规则那次 43 处的形状），
  那属"判据变更"、要逐条归因后再落；本轮只是**登记**，不改门禁。
- 🔴 **属主在自己会话上的第 2 轮追问会崩（P0，编号 `U-129` 的第二触发面：**修法已落地 ⇒ 状态 = 待验收，既不得写「已修好」、也不得写「必崩」** —— W4 `33675b9` 把入口复位做成 `app/graph/state.py:247-252` 的 `RUN_SCOPED_STATE_FIELDS`（从 `STATE_GROUPS` 派生，实测 47 = `GraphState` 58 个字段 − 组 1 的 11 个身份字段），`d73a201` 用 `TestU129EntryInvariant` 把它钉成 CI（契约 7→14 条）；被测构建身份本轮改由 **import 级实证**判定：`w7load-api:0930r11` 可导入该符号且 n=47、`0928r10` 与共享栈 `commerceql-api-1` 均 ImportError）**：崩点是 `audit_supp` 撞 N-08 断言（`state.py:480 assert_terminal_is_settable` 抛 `ValueError`）⇒ 客户端拿到 `error(INTERNAL)`、**且该 run 一行审计都不留**。活体（09-29 第二十轮，W7 两臂 A/B + 架构独立复算）：**同一句追问、同一会话，只把提问者从非属主换成属主 ⇒ `clarify` ↔ `INTERNAL`**；④′ 压测格内 **4/99**、`--control` 臂 **1/1** ⇒ 有竞态成分，别把"有时不崩"读成缓解。⚠️ 两条连带：**(a)** 多轮追问这条主路径在修复前不可用；**(b)** `U-131`（跨属主越权）的**推理侧那一臂被它挡住** —— 唯一能把上下文带进 `gen_sql` 的路径就是属主自己的第 2 轮 ⇒ 两个号都不转绿。⚠️ **09-29 晚间两条新事实**：**(i)** 该崩点在被测构建里**没有被上一版修法覆盖** —— `7035db3` 只把 `app/graph/build.py` 的"节点超时出路表"改成终态感知（`:484-492`），而崩的那一处是 `app/graph/nodes/audit_supp.py:49` 的**无条件**写终态；容器内 `build.py` 的 md5 与 `7035db3` / `HEAD` / 工作区三向同值 ⇒ **"换了镜像就自动好了"不成立**。(ii) 架构已裁修法 = **(a) 入口复位**（否 (b) 改 `thread_id`、(c) 列为备用），并要求修复与"同一 thread 第 2 轮 ⇒ 恰 1 终态 + 恰 1 审计行 + 终态不得等于上一轮结论"那档场景**同一 PR 落地**。修复判据见 `07 §4.8` 的 U-129 行。⚠️ **09-30 架构 v21 轮再补两条（读 `reports/arch/RELAY.md §35`）**：**(iii) 判据的支点换面** —— W4 §二十七（`399b786`，架构独立复算通过）直接读生产落库面：`terminal` **不在** `lg.checkpoints` 的 `channel_values`（现测 **0 / 12,004 行可读**），它落在 **`lg.checkpoint_blobs`**（`channel='terminal'`，现测 **813 行 / 813 个 thread**，全库 thread 1,322）；W7 那 4 条崩臂的**前一条 run 4/4 = `success`、4/4 在 `turn=2`**（架构换 `checkpoint_id` 排序复算，与 W4 的 `ts` 排序逐条同值）⇒ **"跨轮残留"是生产事实，不是 `MemorySaver` 夹具的形状** ⇒ 修复后的验收改为**两条零额度断言**：`turn≥2` 的 run 里"0 审计行"= 0，且 `turn≥2` 的 run **本轮必须自己写终态**（不等压测采样、不花钱）。**(iv) 记账口径**：全库 **517 条 run 没有审计行，其中 turn 1 占 504** ⇒ 凡用"0 审计行"认崩**必须限定 `turn≥2`**，否则高估约 **40 倍**（`U-130` 的 gap 同理）。⇒ 对外句子（架构 07 **v1.7.15** 更新）：**多轮追问主路径 = 待验收，不得写「可用」也不得写「必崩」**（修法后**零进图 run**：`lg.checkpoints` 与 `app.cost_ledger` 两条独立算法都给最后一条 = 2026-09-29T15:29:43Z，而修法时刻是 09-30 14:25:35Z ⇒ `U-129` 判据① 落在空作用域上、按契约记 `UNVERIFIED`；`U-131` 推理侧仍被这一号挡着）。⚠️ **09-30 架构 v22 轮把这一号的结案判据改成三句（读 `reports/arch/RELAY.md §36`）**：**句 A** = 结案**不依赖活体臂**（原"两臂活体复现 ≈¥0.02"从结案必要条件里**删除**，依据是零额度的落库面 + thread 链：4/4 `turn=2` ∧ prev 全 `success`、`terminal` 持久化 813 行 / 813 thread）；**句 B1** = 条件式必然**成立**（残留 `complete` ∧ 本轮把出口选到 `audit_supp` ⇒ 抛 N-08 且 0 审计行；代码 = `edges.py:121-126` + `audit_supp.py:49` 无守卫 + `state.py:471`）；**句 B2** = "每一次第 2 轮追问都会崩"这种全称频率**仍 `UNVERIFIED`**（⑬ 的 `success` 桶 5/5 但 `users_clean` = 0 ⇒ 桶内无对照）。⇒ **对外句子只许用 B1 的条件式表述**，不得写"必崩 / 崩率 100%"。另：`U-130` 的"审计行缺口"今后必须带口径 —— **子窗 99/95 = gap 4**、**整窗 104/99 = gap 5**，两个数都对、不得互换。 ⚠️ **10-01 架构 v1.7.15 轮再补三件（读 `reports/arch/RELAY.md §38`）**：**(v) 判"这版代码在不在被测构建里"改用三层证据** —— 层 1 单文件 md5 最弱（没被改过的文件无判别力）、层 2 必须**逐对象标面**（实测新镜像 `state.py` 原始字节 = `33675b9` 的 **CRLF 面** `58dc5462abb5…`，旧镜像 = `33675b9^` 的 **LF 面** `c3d2656dee60…`，同镜像内跨文件行尾还是混的：CRLF 38 / LF 109）、层 3 import／行为级实证最强（细则入 `07 §16.5`）。**(vi) 两条禁令**：`git status` 干净 **≠** 工作副本字节等于 git blob（`.gitattributes = * text=auto eol=lf`）⇒ 不得拿它当构建身份证据；**共享 `:8000` 栈不是被测构建**（镜像 `commerceql-api` 建在 09-18、`/srv/app` 只有 79 个 `.py` 而 HEAD 侧 147）⇒ 任何"现在服务如何／某缺陷已修"的活体句都不得取自它。**(vii) `U-129` 判据② 生产面读点已实测存在**：`lg.checkpoint_writes` 里 `channel='terminal'` = **813 行 / 813 个 thread、逐 thread 恒 1 次**（这同时是"一个 thread 至多一次终态写"的落库面形状），但**它的 `task_id` 是 LangGraph 内部 UUID 不是应用 `tk_` run 号、`task_path` 末段不可当写入节点名、且不得与 `channel_versions.terminal` 混用同一 `checkpoint_id`（对撞 0 / 1,571）** ⇒ 升成 run 级判据还缺"run 边界怎么切"这件器件（归 W4 设计）。 ⚠️ **10-01 架构 v1.7.16（含同版第二次、第三次落笔）再补三件（读 `reports/arch/RELAY.md §39`）**：**(viii) `turn≥2` 那个 0 被判定为「真读数」** —— `lg.checkpoint_writes` 上按轮分桶现测 = `turn1` 1,317 条 run / 1,316 条有写行 / `terminal` 写 813，`turn2` 39 / 39 / **0**，`turn3` 15、`turn4` 6、`turn5` 1 同形 ⇒ 第 2 轮在同一面**有写行、只是没有终态行** ⇒ 「写面对 terminal 黏在第一轮」这种量具怀疑被现测排除（⚠️ 只排除本表的 `terminal` 通道，`lg.checkpoint_blobs` 仍是 thread 级、切不出 run 边界）。**(ix) 验收形状改成三格并报**：`⑮ 臂1 = 0 ∧ 臂2 = 0` ／ `t2_routed_audit_supp_without_terminal_write = 0`（修复前基线 = **5**，即那 5 条被路由进 `audit_supp` 却没写终态的崩臂）／ `t2_with_terminal_write ≥ 1`（修复前基线 = **0**；那批里若没有 `turn≥2` run 走到终态，记 `n/a` + 原因，**不许记 0**）。**(x) 一个名词、三个面、三个数**：`lg.checkpoints` 1,322 ／ `lg.checkpoint_blobs` 1,319 ／ `lg.checkpoint_writes` 1,318 ⇒ 对外引用「全库 thread 数」必须带面名，三者不可互认、不可相加（本号 §9 与 §16.5 历轮那句「1,322」指 checkpoints 侧）。 ⚠️ **10-01 架构 v1.7.17 再补三件（读 `reports/arch/RELAY.md §40`）**：**(xi) 报数固定五件 = 数 + 面 + 谓词 + 分母 + 粒度** —— 现测谓词 `channel='branch:to:audit_supp'` 的写面上：写行 **75** ＝ distinct checkpoint **75** ＝ 可归属 run **75**，但 distinct **thread = 70**（65 个各 1 条、5 个各 2 条被路由 run）⇒ 而这个 70 **恰等于** `turn1` 被路由的 run 数 70 **（同值不同义）**：光对数值永远抓不到，必须带粒度名。**(xii) `U-129` 格2 新增非空真前置 `t2_routed_supp > 0`（判据变更）** —— 修复前基线**不是裸常数**，而是随作用域变：全库宽窗 **5** ／ A 档子窗 **4** ／ `session-lock` 家族 **0**；该家族 `turn≥2` 的 8 条 run 里被路由 **0** 条 ⇒ 它的「格2 = 0 即达成」是**空真** ⇒ 验收靶子必须选 A 档形状，不满足前置的那一格按契约记 `n/a` + 原因、**不许记 0**。**(xiii) 报价形状 P-A → P-A′**：同人同会话同题串行 **3 对 = 6 条准入 ≈ ¥0.014–0.023（非峰）**；只批 1 对（≈ ¥0.0045–0.0075）现在**只保证拿到格1**，格2/格3 大概率记 `n/a` —— 乘数口径照旧（峰时 per-run ≈ ×3.2 ／ per-call ≈ ×2.3 ⇒ 引用报价必须点口径）。
- 🔴 **L4 精排在默认配置下静默失效（P0，编号 `U-128`；🔻 10-04 现读：状态 = 大幅缓解、未清零，且**没修的部分不是同一件事**）**：`l4_score` 走非思考档且 `max_tokens=512` ⇒ 响应被截断、绑定静默退回下层。活体读数（W7 第十七轮，`c=100/n=100`）：`l4_score` 完成数 **65 → 3**，约 **64% 的请求 L4 未生效**，**既不报错也不带降级标注** ⇒ 依赖 L4 的准确率口径（G-2 的 `easy×low` 网格）在修复前不可引用。
  🔻 **10-04 01:4x 两把尺现算**：① **代码面** `app/llm/router.py:261/288` 已是 `512 → **2304**`（注释自述 2026-09-28 标定）⇒ 那条"恒被 512 截断"的形状**已经不在当前树里**；
  ② **匣带面**（`eval/cassettes/w6_batch.jsonl`，115 条 `l4_score` 录制响应，两批真打的混合体）按 `max_tokens` 分组的 `finish_reason` 分布 =
  `512 档 8/8 全为 length（100% 截断）`、`2304 档 7/107 为 length（6.5%）` ⇒ 从 64% 降到 6.5%，但**没有归零**；
  ③ ⚠️ 顺带量到一件比截断更值钱的事：L4 的 `completion_tokens` 中位 **2,193**（上限 2,304）而它的产物只是一份 `{candidate_id, score, reason}` 列表
  ⇒ **"贴顶输出"几乎全花在 `reason` 这个自由文本字段上**，这也是上一条（成本少算的一档 = 单批 ¥0.74 = 65.5%）为什么这么贵。
  压 `reason`（截断／改结构化短字段／换档）属**共用文本面上的措辞改动** ⇒ 是 G-2 的判据变更，本窗不自签，只登记为**下一笔最该裁的成本**。
  ⚠️ 面必须点名：匣带是**录制件**（`thinking={'type':'disabled'}`、模型恒 `deepseek-flash`），**不等于** W7 那轮压测活体的 64% 已重测；
  ⇒ "恢复／未恢复"的断言按 `U-132` 那条纪律必须带复测时刻与面，本行的两个数（100% / 6.5%）只属于匣带这一份。
- 🔴 **取证面两条凭据／破坏性默认值缺口（P1，10-02 新号 `U-133` / `U-134`，回验收窗 QA 第一轮 O-5 及其连带面）**：**(a) `U-133`** = 压测装载器 `deploy/loadtest/load_synth_to_pg.py:42` 的运行期 DSN 是**仓库里的字面属主串（含口令）**、`:134` 对 `app.*` 执行 `truncate`、全文 env 读取 **0 处** ⇒ **不给 `--dsn` 就直接连共享库清表**；判据三件见 `07 §4.8`（夹具面 `tests/integration/test_retrieval_fts_pg.py` 已由 W2B `6b87da9` 收口，现测可执行回退行 0 处 ⇒ 本号只管探针面）。**(b) `U-134`** = 可用凭据以 DSN 字面量存在于 **18 个跟踪文件**（等值尺，**本窗落笔前基线**；形状尺 27 个、两尺交集 16 个 ⇒ 架构同轮自清自己那两处并提交后 **现测：等值 17 个／交集 15 个／形状仍 27 个**—— 掩码串本身落进形状尺 ⇒ 只有等值尺看得见少了一处），含 `deploy/.env.example` 与 `reports/arch/RELAY.md` ⇒ **「密钥仅来自环境变量」（`N-15`）在仓库侧是被 gitleaks allowlist 放行、不是成立**；架构本轮把自己写的两处**脱敏为形状**（`07 §4.8` 的 `U-114` 行 + `reports/arch/RELAY.md:494` ⇒ 文档侧尺现测 0 / 0）。⚠️ **git 历史里仍在**、远端可见性**本机无 `gh` ⇒ `UNVERIFIED`** ⇒ 「轮换口令 vs 写成显式豁免」是**总控决策**，架构不代裁。⚠️ 连带：本条与 **W7 §五十④**（`api` 经局域网 IP 返 `200`、`5432/6379/6432` 可建连、四端口 `0.0.0.0` LISTENING、redis 无 `requirepass`）是同一条暴露面的两条腿 ⇒ 她那轮**不在本窗上呈队列，已点名未裁**。
🔻 **10-03 第 4 轮就地补记（原文不删；本窗＝开发窗，A5 已由总控授权直接做）**：
**(a) `U-133` 的装载器那半已闭合** —— `deploy/loadtest/load_synth_to_pg.py` 的字面属主 DSN **删除**，
改成 `--dsn` ＋ `COMMERCEQL_LOADTEST_PG_DSN`、两者都缺即退出（实测 rc 1、点名两个来源），
并加了两条同形状守卫（先解 DSN 再碰文件：`sqlite3.connect` 对不存在的路径是**创建**不是报错；
空 `plan()` 即退：否则一次不进还打印"完成"）。
现算尺 = `git grep -c -E "postgres(ql)?(\+[a-z]+)?://[^[:space:]/]+:[^[:space:]@/]+@" HEAD --
装载器＋四条探针五个文件` ⇒ **零命中**（rc 1）。
同形状治理面从 1 个文件扩到 **6 个**（w2d 1／w4 1／w6 4 处探针兜底全删；w2d 的变量名顺带
`PROBE_PG_DSN` → `COMMERCEQL_PROBE_DSN`，与 w6 两条已入门禁的探针同名）。
**(b) 连带那条腿（四端口对外）已收到宿主回环** —— 声明面 `docker compose config` 5 条 `host_ip: 127.0.0.1`，
运行面 `docker ps` 5 条 `127.0.0.1:P->P` ＋ `netstat` 的 LISTENING 里四个端口**无** `0.0.0.0` 行；
`redis` 仍无 `requirepass`（本机面），但已拨不到局域网 ⇒ 与"只绑回环"这一条合起来才构成 U-134
"不轮换 ＋ 显式豁免登记"的完整前提。
**(c) 这句仍然成立、且本轮把它说得更准**：「密钥仅来自环境变量」在仓库侧**是被 allowlist 放行、不是不存在**。
本轮现算（固定串尺，HEAD 口径，`git grep -l -e <串>`；**⚠️ 本文件不落那两个口令字面量本身** —— 10-04 把 `OVERVIEW.md` 搬进 git 时按 `U-134` 的既有做法**脱敏为形状**，串见 `deploy/.env` 现读）：
含**元数据读写角色口令字面量**的跟踪文件 **18** 个、含**分析库只读角色口令字面量** **15** 个、含 `postgres:postgres@` **9** 个。
⚠️ 这三个数与上面架构那把尺（等值 17／交集 15／形状 27）**不是同一把尺**（那把按"能否解析成 DSN ＋ 口令等值"，
这把按"文件里有没有这串固定字节"）⇒ **不得互认、不得相减**；两把尺的本轮共同读数只有一个方向：
DoD④ 全仓重放 = **零未放行命中**（= 每个命中都落在豁免面内，正是"被放行"这句话的可执行形态）。
**(d) `gitleaks` 本机仍未装** ⇒ 上面所有"门绿"都是**替身**（`tests/unit/test_migration_dsn_hygiene.py`
的 8 条断言，含"用项目自己那条真规则全仓重放"），真门在 CI。
**(e) 顺带把规则本身的两处失明改了**：旧正则只认 `postgresql+psycopg://`（⇒ 纯 `postgresql://` 扫不到，
实测全仓该形状 61 处、旧门命中 24），且 `keywords` 预筛是**第二个独立失明面**（不命中就不跑正则）。


- 🟡 **本机冷导入 SQLAlchemy 会挂死（P1 环境阻塞，未修，编号 `U-132`；09-29 午后状态 = 间歇性、当前不复现）**：成因**不是** alembic、也不是迁移残留 —— 架构复算抓栈为 `platform.machine() → uname() → win32_ver() → _wmi_query()` 卡在 WMI `Win32_OperatingSystem` 查询，而 SQLAlchemy 在导入期就调它（`util/compat.py:50`）⇒ **凡起新进程的器件都可能中招**。⚠️ **间歇性由同日三条读数钉死**：架构 12:2x 单次 `platform.machine()` **挂死 >120s（零输出）**，而 15:0x 复测 **6/6 ≤0.05s** 且 `tests/unit/test_migration_dsn_hygiene.py` = **8 passed / 5.96s** ⇒ **任何"恢复 / 未恢复"的断言都必须带复测时刻**，无限定词的现状句一律视为过期。⇒ 跑任何冷导入 SQLAlchemy 的套件**前**先计时 `platform.machine()`；挂了就当场具名登记为**环境红**（不并进判据红），且该轮需要新进程的读数标 `UNVERIFIED`。🚫 不得 skip/xfail/调大超时；主机侧恢复 WMI 是 A 半、测试期 shim 是 B 半（**此刻不必落地，落了必须标 workaround**）。与 W0 的 `tests/eval × 421MB 沙箱库` 那条长期红**是两回事，不得混号**。
- 🟠 **共享 `:8000` 是阶段 0 骨架，不能当"活的后端"用**：其 `/api/v1/openapi.json` **只注册 3 条路由**（`/api/v1/healthz`、`/healthz/live`、`/healthz/ready`），`/healthz` 返 **200 但 `status=degraded`、`graph_compiled=false`** ⇒ 对它发 `POST /api/v1/query` 得 404 是**该树的正确行为**，不是路由丢了。⚠️ 危险点：`/healthz` 的 200 会让人误判"栈是活的"，而压测驱动的**默认 `--target` 正指着它**（`deploy/loadtest/driver.py:832`）。已入契约的新义务：**跑批/联调前必须核对 openapi 的 path 集合含 `/api/v1/query`，不匹配则该轮全部读数作废并登记为不可引用来源**。
🔻 **10-03 第 4 轮就地补记（原文不删；这一格的前提已经变了）**：`docker compose build api` ＋
`up -d --force-recreate api` 之后，共享 `:8000` **不再**是阶段 0 骨架 —— 现读三层证据同向：
容器内 `/srv/app` 的 `.py` 数 = **147**（旧镜像 79）、`openapi.json` 的 path 数 = **12** 且
**含 `/api/v1/query`**、**import 级实证** = `app.graph.state.RUN_SCOPED_STATE_FIELDS` 可导入且
**n = 47**、`app.semantics.materialize._guard_tenant_private_kinds` 在位（`_TENANT_PRIVATE_KINDS = ['gold_query']`
⇒ 这轮刚提交的代码正在跑）。启动断言 4 条 passed／0 pending，`healthz/ready` = **200**。
⚠️ **但禁令的形式要留着**，因为它管的是"镜像会不会再次落后"：任何活体句**必须自带构建指纹三件**
（`.py` 数 ＋ openapi path 集 ＋ 一条 import 实证），否则该轮读数不可引用。
⚠️ 而且**没有**端到端跑过 `POST /api/v1/query`（那要打 LLM = 要额度，本轮零额度）⇒
当前可说的只是"路由在位、启动断言过、ready=200"，**不得升格成"链路可用"**；
`health_probes_registered` 那句 `still_unwired: ["llm","embedding"]` 也照原样在日志里。


- **P0 无物理只读副本**：同实例角色级只读 `app_ro`，不是独立只读库（PRD §8.5 / A-11）。
- **审计 fail-closed 换掉的可用性**：NFR-2.6 审计写失败 → **不下发结果**，返回 `INTERNAL` + `trace_id`；
  显式取舍是 **NFR-3.4（审计 100% 完整性）优先于 NFR-2.1（可用性 ≥99.5%）**，理由"无法追溯的查询结果在电商财务场景里比没有结果更危险"，
  由此产生的可用性缺口编号 **R-17**，PRD 要求"不得靠 SLA 措辞掩盖"。`audit_log` append-only，代码层只暴露 `insert()` 并有静态断言禁止 `UPDATE/DELETE`。
- **embedding 不可用时检索降级**（NFR-2.7 / R-18）：Ollama 是必须独立维护的第二个模型依赖，实测单次 embedding 4.5–5.0 s。
- **决策点 τ 未校准**：非 `prod` 可启动但**必须可见**（启动 WARN + 指标 `binding_tau_calibrated` 0/1）；
  `APP_ENV=prod` fail-closed 拒启动。**此窗口产出的任何准确率/澄清率结论不得作为评测证据。**
- **`app/present/` 是空壳**：呈现逻辑在 `graph/nodes/present.py`，包边界与文档表述需对齐。
- **`deploy/docker-compose.yml` 的 `worker` 服务无实现**：命令是 `python -m app.worker`，但 `backend/app/worker.py` 不存在（已核对）。
- **令牌吊销只有内存版**：`app/auth/` 自述 Redis 吊销表未落地。
- 🔴 **登录方式未裁（`D-H`）⇒ 生产形态的页面没有任何登录入口（P1，10-03 第 5 轮真机走查实测）**：
  `/login` 的主按钮只是提示"待裁决"，唯一能进去的路是"粘贴测试 token"的调试入口，而它被
  `VITE_ENABLE_DEBUG_PANEL === 'true'` 门控 ⇒ **默认生产构建打不开问答**。演示必须用带调试门的构建
  （`VITE_ENABLE_DEBUG_PANEL=true npm run build`）＋ `scripts/mint_dev_token.py` 签的令牌，三步已写进
  `deploy/runbook/README.md` §5.1。⚠️ 两个坑实测过：令牌只在内存 ⇒ **刷新页面就要重贴**；
  `--tenant-id` 必须是数据里真实存在的（`T_A`/`T_B`/`T_C`），签成 `tenant_a` 的表现是
  "五步走完、该条件下没有数据"而**不是报错**（RLS 匹配不到行），最容易误诊成闸门或模型坏了。
- 🟠 **顶栏两个入口点了必出错误卡（P1，10-04 14:0x 真机截图取证，未修）**：`/semantic/metrics`（口径字典）与 `/eval/runs`（评测）两条前端路由**已建页面**，但它们要调的后端端点**没接线** ——
  现读 `openapi.json` 的 12 条 path 里没有 `semantic`/`eval` 任何一条 ⇒ 两页都渲染出**HTTP 404 错误卡**（页面本身在、数据拿不到）。
  证据：`deliverables/screenshots/07_page_semantic_metrics_HTTP404.png`、`08_page_eval_runs_HTTP404.png`。
  ⇒ 影响两件事：① 第 5 轮那次浏览器走查的覆盖面**只包含问答链路**，"页面打得开"当时是按问答页判的，顶栏另两个入口没人点过 ⇒ 面向人的判据要**逐入口点一遍**，不是"主链路通"；
  ② 演示与交付包里已明写"别点这两个链接"（`deliverables/ACCEPTANCE.md` §3）。⚠️ 补端点属新功能面（口径字典只读接口 ＋ 评测报告读取接口），本窗**未做**，登记待排。
- 🟡 **`api` 容器现在依赖公网 DNS 解析器（P2，10-03 本机 A/B 实测后写进 compose）**：
  Docker Desktop 内嵌 DNS 解析 `api.deepseek.com` 8 次里 1 次 `gaierror`（8.02s）＋1 次 3.07s，
  足以吃光 `normalize` 节点的 15s 预算 ⇒ 前端表现为降级＋拒答。`deploy/docker-compose.yml` 已给
  `api` 加 `dns: [223.5.5.5, 119.29.29.29]`，**内网部署必须删掉那三行**（不是改值），
  且删除前要确认 `host.docker.internal` 仍解析得到 —— 单加 `dns:` 会打断它（实测 `gaierror`），
  现在靠 compose 里已有的 `extra_hosts` 补住。
- **`/healthz/ready` 在阶段 0 恒 503** 是设计行为（硬依赖探针归后续阶段），不是缺陷；读文档时要区分这两类。
- 🔴 **金标口径缺口（P1，10-03 第 6 轮实测，判据侧待裁）**：语义包把 GMV／订单量定义成
  **已支付 · 非退款 · 非测试单**（`default_predicates`，附录 A §A.7.1 挂在指标上），而冻结集的 `gold_sql`
  是裸 `SUM(pay_amount) FROM v_order_paid WHERE pay_time >= '…'`。同器同界复算 41 条有 SQL 的用例：
  预测 = 金标 **3 条**／预测 = 金标＋默认谓词 **22 条** ⇒ **19 条的差是金标缺默认谓词**、19 条是真能力缺口。
  ⇒ 它直接决定 G-2／G-7 的天花板。**本轮没有动冻结集**（改 `gold_sql` 会破 `content_hash`，N-13 验真当场失败；
  而且"改考卷让分好看"不是可接受的做法）。探针：`backend/reports/w8/probe_gold_predicate_gap.py`。
- 🔴 **上游不可用被链路收口成"系统里没有这类数据"（P1，W3A 错误分类面）**：演示第一问撞 `normalize` 的 15s 生产契约超时
  ⇒ `template_only` ⇒ 终态 `refuse` ＋ `no_data_asset`，用户看到的是"没有这类数据"而不是"智能服务暂不可用"；
  23:03 之后的两次试跑也走同一条码路（当时我把它写成"密钥失效"，🔻 已按实测订正：坏的是 **Windows 用户级环境变量**里那把同名旧 key，尾号 `d46d`，实测 HTTP 401；`deploy/.env` 里尾号 `23e8` 那把实测 HTTP 200 好使，被 `eval/_bootstrap.py` 的 `os.environ.setdefault` 挡在后面）。
  ⇒ 两个后果：误诊方向（人会去改语义包而不是换密钥），以及**降级件会被录进评测匣带**（本轮 4 条认证错误响应已 `git restore` 撤掉）。
  C-12 的四个 `RefuseReason` 里没有"上游不可用"这一格 ⇒ 补码位属判据变更，本窗不自签。
  🔻 **10-04 01:1x 在真浏览器里又打到一次，并且当场做了对照**：同一题（"T_A 从 2026-06-01 起的 GMV 是多少？"）连问两遍 ——
  第一遍 `normalize` 撞 **15.0s 生产契约超时**（日志事件 `node_timeout_degraded`，`limit_s=15.0`）⇒ `template_only` ⇒ `refuse` ＋ 页面文案"系统里没有这类数据"；
  第二遍正常出表 `gmv = 30768819.37`、8.5s、¥0.003288。**同容器内**当场量 `api.deepseek.com`：DNS **0.07–0.18s**、TCP 建连 **0.12–0.18s**（3/3）
  ⇒ **这次不是解析抖动**（那是上一条 `dns:` 那个 P2 的形状），是**上游往返本身**慢过 15s。
  ⚠️ 这条落库面还顺手证了另一件事：超时那一次在 `app.cost_ledger` **零行**（4 档调用只落了后一次的 4 行）⇒ "被超时吃掉的调用有没有入账"是个未测面。
- 🔴 **冻结集的期望 ≠ 语义包的指标面（P1，10-04 第二批真打实测，判据侧第二处缺口）**：124 条 `execute` 用例里 **63 条（50.8%）**
  需要的指标在语义包里**根本不存在** —— 按金标投影拆：**34 条 `COUNT(*)`／`COUNT(DISTINCT x)` 形态**（在架商品数、SPU 数、店铺数、活动数、各维度分组计数）
  ＋ **29 条未声明的列级聚合**（浏览量 `SUM(pv)`、加购数、投放成本等），而 `semantic/bundle_2026.09.14.1.yaml` 的 `metrics:` 现读只有 **9 个**
  （`gmv order_cnt aov arpu refund_rate repurchase_rate_90d uv pay_cvr sell_through_rate`）。
  ⇒ 计划层按契约拒答（`no_data_asset`）是**正确行为**，是**考卷**把这些题标成了 `execute`。
  它直接决定 G-5 右半与 G-2 的天花板：杠杆只有两条 —— 扩指标面（改内容 ⇒ 全批重录 ≈¥0.4，且内容归 W1A）或裁"这 63 条该不该由 9 指标面回答"（改判据 ⇒ 不动代码）；
  **两条都不在本窗自签**。尺 = `eval/results_v1.json` 的 `expected_behavior`×`outcome`×`refusal_reason`×`gold.gold_sql` 投影，复算命令见 `backend/reports/w8/RELAY.md` §六.15。
- 🔴 **`l4_score` 的用量此前不进 run 累加器 ⇒ 本轮所有花费/token 数是下限（P1，10-04 实测并当场修）**：`record_usage` 只有
  `normalize`／`intent`／`plan`／`gen_sql`／`repair` 五个调用点，而 `bind` 是唯一"自己出过站却不往累加器记"的节点 ⇒
  同一条 run 的**口径条 ¥0.003288** 对 **落库面 sum ¥0.004670**，差值**恰等于**四档调用里的 `l4_score` 那一档（`¥0.001382`，占该 run 的 29.6%）。
  ⇒ 后果要说准：① 用户可见的成本与 `audit_log` 的成本列**少算一整档**；② §7 引用的 ¥0.337171 ／ ¥0.391504 与两个 token 数都是**下限**（评测产物读的是同一个累加器），
  真实上游花费更高，比例上界 = 每条走通 `bind` 的题 ×(1+l4 档占比)；③ **这正是 `U-130`（全项目没有对"请求级入账完整性"敏感的机器判据）的第二个触发面** —— 已上呈建议并号登记，本窗不取号。
  修复 = `ScoreOutcome` 带出 `tokens`/`cost_cny`（失败态也带：解析失败不等于没花钱）＋ `bind` 记入累加器；守卫两条各三面（入账／失败仍入账／没出站不许凭空入账）。
  ⚠️ **少算的规模已经量出来了（零额度，同匣带回放，唯一变量就是这条修复）**：同一份 166 题的回放，成本从 `¥0.391504` 变成 **`¥1.131531`**、tokens 从 1,836,623 变成 **2,090,419**；
  逐档拆开 = **`l4_score` 73 次调用、¥0.741315（占整批 65.5%）**、`plan` ¥0.161837、`normalize_intent` ¥0.138684、`gen_sql` ¥0.088006、`repair` ¥0.001689；
  恰好 **73 条用例的成本变大**（= 走过 `bind` 的那批），其余 93 条逐位不变 ⇒ 增量与这条修复一一对应，没有第二种解释。
  🔻 **活体面当场闭合**：修复前那条 run 口径条 `¥0.003288` vs 落库面 `¥0.004670`；修复后同一题（`tk_b6ad2288…`）口径条 **`¥0.004312` = 落库面 sum `¥0.004312`**（4 档调用全数入账）。
  ⇒ **结论要说狠**：本项目此前上报的**所有**花费与 token 数都少算一整档，而少算的这一档恰恰是**最贵的一档**（单批 ¥0.74）——
  报价模型、成本熔断阈值、日预算 80%/100% 两级告警、G-6 之外任何"这轮花了多少"的句子都必须带这条订正重看；
  回放继承的是匣带里录制的用量 ⇒ `¥1.131531` 是**复算口径**，不是 DeepSeek 账单数，两批相加会把同一批匣带条目重复计价 ⇒ 真实累计花费留 `UNVERIFIED`，等控制台对账或下一次 `--live`。
  ⚠️ **重跑一次 `--live` 才能把花费口径转成实测**（≈¥0.4，未批 ⇒ 本窗没跑）。
- 🟠 **评测题面带夹具痕迹，会被读成产品行为（P2）**：冻结集为钉死租户把 `T_A`/`T_B` 写进中文问句 ⇒
  理解阶段把租户码当"未映射实体"，easy×low 十条里 **9 条澄清**、澄清率 32.5% 的相当一部分是这个形状造成的。
  产品侧已加"租户码自指不算实体"的说明（只给三个理解任务，`plan`/`gen_sql`/`repair` 不给，两面守卫进测试），
  🔻 **10-04 00:5x 第二批真打给了读数（原文那句"收益 UNVERIFIED"作废）**：澄清 **54→30**、easy×low 十条**不再停在澄清**
  ⇒ 设计目标**达成**；但 🔴 这十条现在整整齐齐走到 `intent>link>plan>refuse_out`（10/10 出口理由 `no_data_asset`），
  也就是**被推过了理解阶段、全部撞死在计划层**，于是 G-5 误拒 43→63、G-2 仍是 0/10。
  ⇒ 本窗的裁定（写清楚理由，不做 cosmetic 回退）：**不回退这条改动** —— 拒答与澄清在 P0 是两个不同产品出口，
  把题留在"永远走不下去的那一步"不是修复；G-5 变难看是**上一段那条判据侧缺口**的可见化，不是这条改动引入的缺陷。
  ⚠️ **活体面不能当这条的证据**：重建后的构建里 `hasattr(payloads,'TENANT_SELF_REFERENCE_NOTE')=True`、
  而"闸门修复后、载荷改动前"那个旧镜像对同一道带 `T_A` 的题**也没澄清**（§六.9 那次走查就是它）⇒ 这一题面上**没有 A/B 对照**，
  收益只由评测批次那一份读数支撑。
- 🟠 **同匣带回放件的两栏不许串**：回放（¥0）里 LLM 段 `latency_ms` 恒 0、`cost_cny_total` 是从录制用量**继承**的同一个数
  ⇒ 引用延迟/耗时只用真打那份（`eval/results_v1_live_20261003T1410Z.json`，已入库固定不覆盖），
  也不许把 ¥0.337171 说成"花了两次"。
  🔻 **10-04 补第二份固定件**：第二批真打的读数已另存为 `eval/results_v2_live_20261003T1632Z.json`（与当前 `eval/results_v1.json` 同字节，md5 已对）
  ⇒ 两份真打件并存可比，**第一次与第二次的花费是两个独立数**（¥0.337171 ＋ ¥0.391504 ＋ 演示 1 问 ¥0.003221 ＋ 本轮走查 ¥0.003288 ⇒ 本项目累计 ¥0.735484）；
  ⚠️ 这四个数按上一条都属**下限**口径（`l4_score` 那档此前没进累加器）。
- **文档间版本漂移**：`07` 的上游版本表仍写 `05=v1.2`、`06=v1.2.1`，而两者实际已是 v1.3 / v1.2.2。
- ~~仓库里有一个空垃圾目录 `CommerceQL/semantic;C/`，以及 `docs/` 与 `eval/` 下大量 `*.bak-*` 快照~~ **已于 2026-09-28 清理**：空目录删除，59 个 `*.bak-*` + 48 个跑批日志 + 40 个未被点名的根一次性稿 + 39 MB 根缓存移到工作区外的 `E:\01_实训\项目\CommerceQL建议删除垃圾\`（清单见其 `MANIFEST.md`，**移动非删除**）。清理后 `git status` 只剩 2 条未跟踪项（`backend/reports/arch/`、`eval/results_replay_probe.json`）。
- **所有 NFR 延迟/可用性/成本目标值都是设计目标**（PRD §17 Q-7 已确认按目标实现并埋点，首次实测后替换）。

---

## 10. 术语速查

| 术语 | 含义 |
|---|---|
| Text2SQL / NL2SQL | 自然语言转 SQL |
| EX | Execution Accuracy，执行结果与标准答案一致的题占比（本项目主口径 I-1） |
| 语义层 / 口径 | 指标的定义、公式、默认过滤条件、时间口径的版本化集合；本项目是 1,225 行 YAML 语义包 |
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
| **D 外部一手事实** | Spider 1.0 10,181 问 / 5,693 SQL / 200 库（榜单 2024-02 冻结，CC BY-SA 4.0）；Spider 2.0 632 任务、GPT-4o 仅 10.1%、要求输出 CSV、不提供预定义 schema；CSpider 榜首 test 62.1（比英文低 29 点）；CoSQL 官方把"执行/澄清/告知无法回答"并列建模；DeepSeek 当前仅 `deepseek-flash`/`deepseek-v4-pro`、`deepseek-chat` 已退役、限流按并发（2500/500）、缓存命中差 50 倍；PG 原生 `tsvector` 无中文分词 | 官方站点与 API 文档，抓取记录见 `_refs/00_参考站点抓取记录.md` |

**免责**：本项目数据全部为**合成数据**，不代表任何真实企业经营数据。规模为设计目标 **3 租户 / 50 万订单 / 2,000 SKU**
（PRD §17.3 Q-8 确认按附录 C 实现），对应**实测**：沙箱已支付订单视图 494,249 行（逐租户 200,000 + 175,000 + 119,249）、
PG 侧业务事实 2,023,933 行。仓库内不放任何真实密钥（密钥只在 gitignore 的 `deploy/.env`，CI 以 gitleaks 扫全史）。

---

## 12. 想深入：按角色的阅读路径

| 你是 | 建议顺序 |
|---|---|
| 后端 / 算法 | `07` TDD（20 条 ADR → 包结构与依赖规则 → 状态机契约 → §17 门禁与不变量）→ `02` 附录 A 契约 → `CommerceQL/README.md` §4 五条工程约束 → `backend/app/core/{enums,contracts}.py` |
| 前端 | `06` UIUX 全篇（尤其 §7 四大异常态、§8 组件×11 态矩阵、§10 SSE 客户端契约）→ `02` A.1/A.10/A.14 → `frontend/src/api/queryStream.ts` |
| 数据 / 业务方 | `03` 附录 B 口径字典 → `semantic/bundle_2026.09.14.1.yaml` → `data/generator/` |
| 评测 / 质量 | `04` 附录 C → `eval/{gates,runner,reporter}.py` → `backend/reports/w6/评测报告与门禁判定.md`（含 §10 复算指令） |
| 运维 / 部署 | `05` 附录 D 全篇 → `deploy/` → PRD §14 可观测性 |
| 评审 / 面试官 | 本文 §2 → §3 → §7（最诚实的一段）→ §8 → PRD §16 风险登记、§17 假设登记 → `07` §4 ADR |
| 新接手开发 | 本文 §5 → §6 → §9 → `docs/08` 文件归属表 + 取号协议 → 找到你要动的包属于哪个窗口，读它的 `reports/wN/{DELIVERY,RELAY}.md` |
