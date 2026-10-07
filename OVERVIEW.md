# CommerceQL —— 一份文本读懂这个项目

> **这是什么**：基于 Text2SQL 的电商数据分析 Agent。用户用中文问一句业务问题，系统生成一条**受控**的 SQL，
> 在只读业务库上执行，再自动出图并给出带口径说明的结论。
> **本文定位**：不依赖任何外部讲解，读完即可理解项目的目标、架构、当前实现进度与真实质量水平。
> 它**不属于** `docs/01–08` 契约文档集，不承载契约权威（权威顺序：附录A(02) > PRD(01) > UIUX(06) > TDD(07) > 实施计划(08)）。
>
> 取证时刻：**2026-10-05 15:4x +0800（= UTC 07:4x，第 13 轮落笔侧取证）**｜代码 HEAD：`c62f02d`（`main`，本行写下时远端 `git ls-remote origin main` = `c62f02d9711…` ⇒ 与 `git rev-parse HEAD` **同点、双向 0 偏差**；现读 438 次提交。🔻 **上一版取证（第 12 轮，10-05 13:0x +0800）= HEAD `3c37c79`／416 笔**，作历史读数保留、不当现状。⚠️ **本行自指、且必然过期**：任何一笔新提交都会让它失真 ⇒ **引用 HEAD / 提交数前必须实跑 `git ls-remote origin main` 与 `git rev-list --count HEAD`，别抄本行**）｜契约文档：**`07 = v1.7.21`**（**3,651** 个换行元素 = 正文 3,650 行 ＋ 尾空元素，两口径并报；`wc -l` 现读 3,650；行尾现读 **CRLF 3,650 ／ 裸 CR 0**）、**`08 = v1.4.1`**（`wc -l` 487 ／ 切分 488）｜`07 §4.8` 下一可用号 = **U-138**（现读出处 = `docs/07_技术设计文档_TDD.md:1081` 那句"下一个可用号 = U-138"；🔻 **v1.7.20 起本窗停止逐处抄行位**：该指针行位置每轮随插行漂移，本项目已三次踩到"行位抄本落后于内容"（QA 第 15 轮 12.8 c 是第三次），⇒ 坐标只认那句**行首**「下一个可用号 = `U-xxx`」，行号只作时点快照；v1.7.21 本窗取一号 `U-137`（闸门 R10 不认 CTE 侧 ⇒ 「先聚合再连维表」被报成越权；落号行本轮现测 `:1173`）；v1.7.20 本窗取一号 `U-136`（401 令牌过期时错误码没送到用户眼前 = `U-131` 的镜像；落号行现测 `:1172`）；v1.7.19 本窗取一号 `U-135` = `recursion_limit` 超限不写审计行（决策表 G4 行本轮现测 `:2885` 要求审计 ✅，落号行现测 `:1169`）。⚠️ **本行自曝一次尺误**：16:0x 那一版这里写成了 `U-136`，依据是"正则扫全文最大号 = 135 ⇒ 下一号 136"，而全文 `U-135` 只有 **2** 处命中、两处都是**指针／变更行**而不是已落号行 ⇒ "扫到最大号 +1" 不是取号尺，取号只认 §4.8 的落号行与那句显式指针。第 5、6 轮**零取号、`docs/**` 内容一字未改**；第 6 轮的四处判据侧／计量侧缺口（金标默认谓词、指标面覆盖、上游不可用的终态归类、`l4_score` 不入累加器）**已上呈但未落号**。🔻 **10-04 02:0x 就地补记一件"位置"变化（不是内容变化）**：`docs/01–08` 与本文 `OVERVIEW.md`、`_refs/` **已进 git**（提交 `3b695a9`）—— 此前 `git ls-files docs` = **0** 而盘上有 15 个文件，`README.md:15` 又把"唯一当前真相"指在仓库外 ⇒ clone／GitHub zip 的收件人拿不到契约文档。入库内容**逐字未改**（现算 `wc -l` 07 = 3,642、08 = 487 与本行上面的读数一致），只有两处字节级副作用：① `.gitattributes text=auto eol=lf` ⇒ 入库 blob 是 LF；② `docs/*.bak-*` **七份快照不进仓库**，移到工作区外归档 `E:\01_实训\项目\CommerceQL建议删除垃圾\docs-bak-20261004\`（移动非删除）。入库前对 12 个新跟踪文件按 `deploy/.env` 现读的四条真凭据做了字面量包含检查 = **命中 0**（唯一命中的是本文里我自己落下的两个口令字面量，已按 `U-134` 既有做法脱敏成形状；⚠️ 仓库内另有 **8 个此前已跟踪并已推送**的文件仍含同样字面量 —— 那属 `U-134` 的"轮换 vs 显式豁免"未裁项，本窗不擅动））
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
│   ├── 07_技术设计文档_TDD.md              v1.7.21 **3,651 行**（`wc -l` 3,650 ／ 按换行切分 3,651 两口径并报）／ 0–20 章 + 附录：**20 条 ADR**、包结构与依赖规则、状态机契约、§4.8 问题编号登记表、§16.5 零额度可还原面台账（**8 个面**，10-01 新加 `lg.checkpoint_writes`）、§17 门禁与不变量
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
唯一例外 `app/present/` 曾是空壳；🔻 **10-05 第 11 轮就地订正**：现读 3 个文件 701 行（`artifacts.py` ＋ `eval_report.py` ＋ 20 行 `__init__.py`），落的是**评测报告页的后端聚合投影**；**图内呈现逻辑仍在 `app/graph/nodes/present.py`，包边界仍未对齐**（那条残留项没销）。
🔻 **10-03 第 4 轮就地补记（原文不删）**：`backend/reports/` 现为 **20 个目录**（新增 `qa` 验收窗 ＋ `w8` 集成收尾窗，
后者即本轮的写权面）；`app/present/` 现读仍是**只有 5 行的 `__init__.py`**（`git log -1 -- backend/app/present` =
阶段 0 那笔 `15a23fc` 之后没人动过）⇒ "空壳"这句仍然成立。🔻 **本句已被第 11 轮推翻（10-05 00:5x 现测）**：`git log -1 -- backend/app/present` 现在是 `772eba9`，包内 701 行；原句不删、只在此具名订正。上面那句的 HEAD 指针 `20066a5` 是 09-29 的，
本轮现读见下面表格里"提交数 / HEAD"那一格。

**实测质量读数**

| 项 | 读数 | 出处 / 复现 |
|---|---|---|
| 提交数 / HEAD | **438 / `c62f02d`**（🔻 **10-05 15:4x 第 13 轮现测**：`git rev-list --count HEAD` = 438 ＋ `git ls-remote origin main` = `c62f02d9711…` 同一次运行内对撞 ⇒ 双向 0 偏差、`git status --porcelain` = **0 行**。⚠️ 本格仍会随下一笔提交过期 ⇒ 引用前实跑那两条命令。**历史读数（第 12 轮现测，勿当现状）**10-05 13:0x = **416／`3c37c79`**（该轮把本格由"首格＝过期快照"换成"首格＝现测"；当时工作树脏 14 行全是本窗在制品）。原首格 **382／`b571b40`** 保留在下面作为历史读数，不再当现状）｜**历史读数（原首格，勿当现状）**（2026-10-04 01:40 现读，`git ls-remote origin main` = `b571b40` 与 `git rev-parse HEAD` **同一次运行内全等** ⇒ 双向 0 偏差；上一读数 380 / `079916d` ⇒ L4 计量修复 ＋ 报告笔共 **＋2 笔**。⚠️ 本行自指：落报告的提交本身也计入，引用前实跑 `git rev-list --count HEAD` ＋ `git ls-remote origin main`）。🔻 **10-04 18:4x 第 9 轮现读** = **399 笔／`a84fc6f`**（`git ls-remote origin main` 给同一个点，工作树脏 12 行全是本窗文档件 ＋ 一件未跟踪 JSON）⇒ 比上面那格 382／`b571b40` 多 **17 笔** = W8 第 8 轮的 3 笔 ＋ QA 第 5／6 轮的若干笔，**不相减、只现读**；🔻 **同轮第三次读数（19:3x，本窗三笔落库之后）**= **402 笔／`cbff229`**（`f73a230` 代码与九份横幅 ＋ `485b511` 门禁产物与 T-31 件 ＋ `cbff229` 对外文档）⇒ 上面「399 笔／`a84fc6f`」是本轮**开工时点**的读数、引用必须连时点一起带；推送后第三次现读形状 = 工作树 0 行 ＋ `git ls-remote origin main` 与 HEAD 同点（判「推上去没有」只认 `ls-remote`）。 | `git rev-list --count HEAD` ＋ `git ls-remote origin main` 🔻 **10-04 20:5x 第 10 轮现读 = 404 / `1a2e474`**（QA 第 7 轮那笔；尺同前：`git rev-list --count HEAD` ＋ `git ls-remote origin main` 同一次运行内对撞；上一读数 402 / `cbff229` ⇒ 差的 2 笔 = 第 9 轮的 L4 报告笔与 QA 的验收笔）。⚠️ 本行仍自指：第 10 轮自己的提交不计入这个数，引用前重跑那两条命令 |
| 后端规模 | 147 个模块文件、**38,049 个换行**（2026-10-04 01:38 现算，尺 = `git ls-files backend/app` 里 `.py` 的 `cat \| wc -l`，**HEAD 与工作树此刻同值**；含 L4 计量修复 ＋15 行）。🔴 **自曝上一读数少数 2 行**：本格 23:1x 记的是 `38,032`，而**同一棵树**（`703aae6..079916d` 之间 `backend/app` 零改动，`git diff --stat` 空）重算给 `38,034` ⇒ 差 2 行不在代码、在**我那次求和**；旁证 = 同一把尺在第 5 轮那个 rev 上重算 `e7d9442` = **37,957**，与当时登记的数**逐位相同** ⇒ 尺没问题、上一格是转录错。🔻 **10-04 18:4x 同尺现算** = **147 个文件／38,104 个换行**（＋55 行逐位对得上：`git diff --stat b571b40..HEAD -- backend/app` = 1 文件 ＋55／−2，那一件就是 `app/api/state_store.py` 的 U-131 三面）｜🔴🔻 **同轮第三次读数 ＋ 一处尺名自曝（19:3x，本窗三笔落库之后）**：现在两把尺**才真的同值** = 147 件／**38,104**（HEAD 尺与上面那把工作树尺各跑一遍都是 38,104）。但**上面 18:4x 那次给的是工作树值、却写着「HEAD 口径」**：当时 HEAD 还是 `a84fc6f`、那把尺真值 **38,102**，差的 2 行正是**未提交**的 `app/cache/keys.py` 文档串（＋3／−1）⇒ 属「两把尺当一把」的第四形态（本项目已登记谓词／分母／分母含目录／粒度四种），**归因错的不是数字是尺名**。另外 `git diff --stat b571b40..HEAD -- backend/app` 现在给 **2 文件 ＋58／−3**（`state_store` ＋55／−2 ＋ `keys.py` ＋3／−1）⇒ 上一句「＋55 = 那一件」只对**到 18:4x 那个时点**；净增 55 行这条算术本身两路都闭合（38,049＋53＋2 = 38,104 ✓）。复算两条**分开跑**：工作树 = `git ls-files backend/app ｜ grep '\.py$' ｜ xargs cat ｜ wc -l`；HEAD = `git ls-tree -r --name-only HEAD -- backend/app ｜ grep '\.py$'` 逐件 `git show HEAD:<路径> ｜ wc -l` 求和。 | 见左列命令，cwd = 仓库根 |
| 前端规模 | 39 个 ts/tsx、**8,442 个换行**（2026-10-04 01:0x 重算，与上一读数**逐位相同** ⇒ 第 6 轮前端零改动这条是被重测出来的，不是沿用：`git diff --stat 703aae6..HEAD -- frontend` 空）。🔻 **10-04 18:4x 再重算仍 39／8,442**（`git diff --name-only b571b40..HEAD -- frontend` = **0 行** ⇒ 第 8–9 轮前端零改动也是现测的） | `git ls-files frontend/src` 里 `.(ts\|tsx)` 逐文件行数求和 |
| 测试规模 | **128 个 `backend/tests/**.py` ／ `def test_` 共 2,089 条**（2026-10-04 01:41 现读，**HEAD 口径**（`b571b40`，此刻与工作树同值）；上一读数 127 / 2,083 = 第 6 轮 ⇒ ＋1 文件／＋6 条 = L4 用量守卫两面各三面。🔴 两把尺必须点名：`git grep -c … HEAD` 数不到**没提交**的文件，工作树尺数得到 ⇒ 提交前引 HEAD 尺会少 6 条。🔴 **111 与 126/127/128 不是同一把尺**：旧那把数的是"至少含一条 `def test_` 的文件"，本格数的是目录下全部 `.py`。用例数才是可比值）。🔻 **10-04 18:4x 现读** = **128 文件／`def test_` 2,096 条**（HEAD 尺 @ `a84fc6f`；上一读数 128／2,089 ⇒ **＋7 条 = `TestSessionOwnership` 那七条属主契约用例**，文件数不变） | `git grep -c "def test_" HEAD -- backend/tests`（HEAD 尺）／`grep -rc "def test_" backend/tests --include=*.py`（工作树尺）＋ `git ls-files backend/tests` 🔻 **10-04 20:5x 第 10 轮重算**：`def test_` **HEAD 尺 = 2,096**（`git grep -c "def test_" HEAD -- backend/tests` 逐文件求和，@ `1a2e474`）／ **工作树尺 = 2,106**（`grep -rc` 同面，含未跟踪件），**文件数 128 → 129**（＋`backend/tests/eval/test_gate_inputs_p0_merge_two_state.py`，10 个 `def test_`）。🔴 pytest **收集数**比 `def` 数多 2 = 那条参数化用例展开 3 份（10 个 def ⇒ 12 条 collected）⇒ **两把尺都要点名，别把 12 写成 10** |
| 本机离线门禁（**不是**评测报告那一格） | **2,293 passed / 0 failed**，面 = `tests/unit` ＋ `tests/contract` ＋ `tests/eval`，cwd=backend、rc 0（2026-10-03 15:5x 现跑，HEAD `e7d9442`；上一读数 2,291 = 第 4 轮同尺同面，差 2 条即本轮新增的两条用例）。🔴 **与下面那格 `passed=2312` 不是同一把尺**：那格是评测报告在 `8ffb53e` 上的"unit+contract ＋ integration 已跑"口径，本格含 `tests/eval`、不含 integration ⇒ 两者不相减。另：全量 `pytest -q --continue-on-collection-errors` = **2,332 passed / 9 errors**，那 9 条**全是** `tests/integration` 缺 `COMMERCEQL_TEST_{RW,RO,SUPER}_DSN` 的当场 error（U-114 设计如此：禁止 skip），⇒ 集成面本地**未跑**、CI 跑。🔻 **10-03 第 5 轮同轮就地订正（原文不删）**：这一格"未跑"已不成立 —— 用一次性库（`ecom_v1int`，建→迁移→跑→删）复算后 `tests/integration` **107 passed**、全量含集成 **2,424 passed / 0 failed**（rc 0，HEAD `f4331d7`）。⚠️ 两把尺的差在**是否给了集成 DSN**：没给时那 9 个文件在收集期就 error ⇒ 其用例根本不进分母，所以 `2,332` 与 `2,424` **不是**"回归/新增"关系。另：第一次带 env 跑出的 5 条红经三臂对照归因 = **shell 里残留的 `CORS_ALLOWED_ORIGINS` 漏进 `Settings`**（pydantic-settings 未显式给的键回落进程环境），不是被测代码，也不是集成 DSN；测试件已把这一位钉成空串。🔻 **10-03 第 6 轮在当前树重跑（原文不删）**：面 = `pytest tests -q --ignore=tests/integration`（含 `redteam`／`graph_snapshot`，比上面那把"unit＋contract＋eval"宽）= **2,334 passed / 0 failed**，集成层同树重跑 **107 passed** ⇒ 一次性库换成 `ecom_w8int` 重建后跑完即 DROP（现查 `pg_database` 里 `ecom_%` = 1，只剩共享库）。这两栏就是 §7 那格 G-1 转 PASS 的输入。🔻 **10-04 01:2x 在当前工作树（含 `l4_score` 计量修复）重跑同尺**：离线面 = **2,340 passed / 0 failed**（`pytest tests -q --ignore=tests/integration`，rc 0，90.01s；比上一读数 ＋6 = 两条 L4 用量守卫）；集成面 = **107 passed / 0 skipped / 0 failed**（一次性库 `ecom_w8int2`：建→授权→owner→alembic 到 0005→跑→**当场 DROP**，rc 0，27.44s）。🔴 **这两次复算各逮到一件我自己的错**：① 第一次集成跑给的是 `1 failed / 60 passed / 37 skipped / 9 errors`，逐条看错误行 = `psycopg.ProgrammingError: missing "=" after "postgresql+psycopg://…"` ⇒ **四个测试 DSN 必须是 libpq 形态（`postgresql://`，不带 `+psycopg`）**，`psycopg.connect()` 不认这个后缀，而 `MIGRATION_DATABASE_URL` 反过来**必须带**（SQLAlchemy）—— 修表单变量后才是上面那个 107，**那 38 条红没有一条是被测代码的**；② 上一轮那句"残渣尺现查 `ecom_%` = 1，只剩共享库"**是错的**：SQL 的 `LIKE 'ecom_%'` 里 `_` 是**单字符通配**，而共享库名 `ecom` 本身**不匹配**这个模式 ⇒ 那个"1"是别窗留下的 **`ecom_u123_probe`（10 MB）**，不是共享库。⇒ 残渣尺改成 `datname like 'ecom%'` 并报数：现测 **2 个**（`ecom` 505 MB ＋ `ecom_u123_probe` 10 MB）；那个探针库**不是本窗造的，未经它的属主／总控同意不删**。 | `cd backend && PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest tests -q -p no:randomly --ignore=tests/integration` ＋（集成，一次性库四个 DSN）`pytest tests/integration -v`；整段命令见 `backend/reports/w8/RELAY.md` §六.10。🔻 **10-04 18:4x 第 9 轮在 `a84fc6f` 上重跑同尺**：离线面 = **2,347 passed／0 failed／0 errors／rc 0／81.86s**（`pytest -q -rfEs --continue-on-collection-errors --ignore=tests/integration`，**一个集成 DSN 都没给**）；集成面 = **107 passed／0 failed／27.19s**（一次性库 `ecom_t30_it`：建 → alembic 到 `0005` → 跑 → **当场 DROP**，残渣尺 `datname like 'ecom%'` 跑前后都是 **2**）。🔴 **合树单日志对照臂**（防「合并把离线面的红抹平」）= 整树 `-v` 一把跑 **2,454 passed／0 failed／0 errors／107.90s**，且 **2,347＋107 = 2,454 逐位对撞** ⇒ 上面这两把就是 §7 那格 G-1 现在的输入，逐条命令与分层见 `backend/reports/w8/RELAY.md` §九.2 🔻 **10-04 20:3x–20:5x 第 10 轮（T-32 修法之后）同尺重跑**：离线面 = **2,359 passed／0 failed／0 errors／rc 0／95.36s**（一个集成 DSN 都没给；比第 9 轮 ＋12 = 新增那件的 12 条 collected）；集成面 = **107 passed／0 failed／27.87s／rc 0**（一次性库 `ecom_t32_it`：建 → 库内授权 → `ALTER DATABASE … OWNER TO app_rw` → alembic 到 `0005`（表 32 张）→ 跑 `-v` → **当场 DROP**，残渣尺 `datname like 'ecom%'` 跑前跑后都是 **2**（`ecom` ＋ 别窗的 `ecom_u123_probe`，后者不删））。🔴 **上一条那句「2,454 = 2,347＋107 逐位对撞 ⇒ 证合并没吞红」就地退回改写（QA 第 7 轮 ④ 判的，我复算坐实）**：加法只覆盖 `passed` 那一支，而 `failed`／`errors` 当时**只从集成层日志取** ⇒ 那条对撞**证明不了**红没被抹平；旧装配式在「离线 `1 failed, 2347 passed` ＋ 集成 `107 passed`」这对输入上判 **PASS**（= 漏数一条红）。本轮改掉装配口（`eval/reporter.py:merge_p0_logs()`：计数两侧相加、点名列取并集、`integration_ran` 取 OR），机械证据换成 **两态反证**：脏态必 FAIL ＋ 修复前对照臂必读 0（`backend/tests/eval/test_gate_inputs_p0_merge_two_state.py`，12 条全绿） |
| 静态与方向门禁 | `ruff check .`（cwd=backend）**0 条**；`mypy app` = no issues in **147** files；`lint-imports` = **4 kept / 0 broken**（🔴 必须带 `PYTHONUTF8` ＋ `PYTHONIOENCODING`，否则它自己会 `gbk` 崩在输出行上、给出假红）；W1A 四件自检 ＋ `python -m app.core.enums` 全 rc 0 | 逐条命令见 `CommerceQL/backend/reports/w8/RELAY.md` §四.8 🔻 **10-04 20:5x 第 10 轮重跑**：`mypy app` = **no issues in 147 files**；`lint-imports` = **4 kept／0 broken**（不带 `check` 子命令）；`ruff check --config pyproject.toml app` = **All checks passed!**；`ruff check --config pyproject.toml .`（整目录那把尺）= **All checks passed!／0 条**—— 第 9 轮那 1 条 `RUF005` 已由 QA 自己修掉（在 `reports/qa/**`，我没动别人写面）⇒ **CI 的 ruff job 从此不再有那一处已知红**（本机仍无 `gh`，所以这句是「红因消失」的推断，不是 CI 实果）。`eval/` 侧尺名照旧要点名：`cd backend && ruff check --config pyproject.toml ../eval` = **21 条**（与第 9 轮**逐位相同** ⇒ 本轮改 `eval/reporter.py` 没新增条数；CI 不覆盖 `eval/`） |
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

🔻 **10-06 第 15 轮（T-38，QA 第 17 轮派单）收口读数 —— 上面表内各格是历轮快照，现状以这一段为准**（面 = 干净树 `bea724a`／**449** 笔（⚠️ 本行落笔那一笔会把它后移 ⇒ 引用前重跑 `git rev-list --count HEAD` ＋ `git ls-remote origin main`）；时刻 = 2026-10-06 12:4x–12:5x ＋0800 = 04:4x–04:5xZ；🔻 **同轮补记（两个面不许混成一个）**：`bea724a` 是**本段落笔时的工作面**，而**门禁那两格**（离线 2,454／集成 124 ⇒ `PASS 1/8`）的**干净树 = `9398fad`／450**、两遍重算都在那棵树上做 ⇒ 引 `PASS 1/8` 认 `9398fad`，引本段其余读数认 `bea724a`；粒度 = 逐格点名）：

- **离线面**：**2,454 passed／0 failed／1 warning／105.70s／rc 0**（面 = `tests/unit` ＋ `tests/contract` ＋ `tests/eval`，cwd = `backend/`，日志 = `backend/reports/w8/_r15_offline_cleantree.log`）。
- **集成面**：**124 passed／0 failed／29.31s／rc 0**（11 个文件）；一次性库 `ecom_t38it_r15`：建 → 库内授权 → `alembic upgrade head`（`version_num = **0006**`／`app` schema **32** 张表）→ 跑 `-v` → **当场 DROP**；残渣尺 `datname like 'ecom%'` = **2**（`ecom` ＋ 别窗 `ecom_u123_probe`，**未动**）。🔴 本轮**逮到一条配方坑**（第一次跑就是那个形状）：`RETRIEVAL_TEST_PG_DSN` 若给 `app_rw`，在新建的一次性库上会 `permission denied for database` ⇒ **6 skipped ＋ 3 errors**（那 3 条不 skip、直接 setup error）⇒ 该 DSN 要给可建表的超管串，另外三个 DSN 仍用 libpq 形态。
- **静态三门**：`ruff check app tests` = **All checks passed!**／`mypy app` = **no issues in 158 source files**／`lint-imports` = **4 kept, 0 broken**（cwd = `backend/`，`PYTHONUTF8=1`）。
- **路由面**：`openapi.json` 现读 **19 条 path**（代码面 19 ＋ 重建前活体 15 ＋ 重建后活体 19 三格并报，四条新增 = `/semantic/metrics`、`/semantic/assets`、`/admin/eval/run`、`/admin/audit`）。**当期性锚**（本轮**未重建镜像** ⇒ 🚫 不许写"本轮重建出新镜像"）：镜像 `sha256:ca34ea791a81…` `Created = 2026-10-05T15:19:25Z` ＋ 容器 `commerceql-api-1` `Created = 2026-10-05T15:19:26Z` ＋ **逐件三面 md5 18/18 SAME** ＋ **全量 `app/**.py` 158/158 三面聚合相等（LF 归一后，容器 = 工作树 = HEAD blob）（🔻 **10-06 第 18 轮 T-42 B 就地订正这半句**：那把逐件尺的 git 面当时走了 `.strip()` ⇒ 「三面」这个量词从来没成立，按**两链**读 —— 链一 容器 ⟷ 工作树字节（尺量到的）／链二 工作树 ⟷ HEAD（`rev + dirty`）；详见本节末第 18 轮那条 ＋ `docs/07 §16.5` 层 1 行）** ＋ 层 3 `RUN_SCOPED_STATE_FIELDS` present（size = **47**）＋ 跑前 04:24:43Z 独立取过一次证。🔴 那条聚合尺**原来是坏尺**（容器侧带 `./` 前缀、git 侧不带 ⇒ 三列永不相等 ⇒ 以前的"不等"不构成证据），本轮换代后第一次有判别力。
- **A.9.5 的第二道保证 = 现查不在位**：`rls.enabled = false`／`forced = false`／审计两张表在 `pg_policies` 里 **0 条** ⇒ 响应 `second_guarantee_in_place = false` 是**现查值**。对外只可写"身份由服务端 `WHERE tenant_id = JWT.tenant_id` ＋ 三键 GUC 保证；第二道 RLS 今天不在位"，🚫 **不得写"双保证已落地"**（QA 15.2 裁"部分达成"；豁免面落笔 = 待排期，四条验收约束在 `backend/reports/qa/RELAY.md §15.3`，我方上呈的形状在 `backend/reports/w8/RELAY.md §14.4`；本轮按总控默认**不动迁移、不动 `test_rls_policy_provenance.py`**）。
- **活体（本轮真跑的那一笔，已批花费）**：几何 `steady --concurrency 3 --max-requests 30 --reuse-sessions --session-pool 3` ⇒ **`admitted = 9`／`terminal = 9`／`rejected_429 = 20`／一条 409 `SESSION_CONFLICT`／`INTERNAL` 0 条／`graph_run_failed` 0 条**；`outcomes = {ok:4, error_frame:3（全 `GATE_AST_REJECTED` = `U-137` 面）, clarify:1, refuse:1, http_4xx:21}`；墙钟 **22.0s**；实付 **¥0.066117**（36 行台账／10 个 `task_id`／**全非峰**）≤ 上界 ¥0.25；当期单价 **¥0.006612／准入**（比第 12 轮账面 ¥0.00973 低）。
  🔻 **10-06 第 16 轮就地订正两处（原句保留）**：① 上面那句"三条 `error_frame` 全 = `U-137` 面"**是过度归因** —— 对同一条候选 SQL 跑"落地前语义对照臂 vs 当期实现"（零出站件 `backend/reports/w8/t39_u137_before_after.py`）实测 = **一条改判（`tk_ca342fa6…` R10 → R06）、一条仍 R10（真该拒，只是文案不再是"越权"）、一条前后同为 R06（与本号无关）**；
  ② 单价 ¥0.006612 的分子含作废那一跑而分母叫"每准入"是**自相矛盾**（QA F4）⇒ 修正解 = **¥0.00655／准入**（分子 = 具名 9 个 run 的 ¥0.058951／32 行，分母 = 9），整窗含作废那把改叫 `unit_cny_per_run_in_window_incl_void` = ¥0.006612。尺 = `PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w8/t38_assemble.py`。
- **G-6 判向（本批不改判）**：`9 < MIN_ADMITTED_FOR_P95 = 20`（`deploy/loadtest/driver.py:370` 现读）⇒ `g6_p95_le_8s = null` ＋ caveat 原文 ⇒ **P95 仍不可引用**，旧的 6.18s／9.81s 那批**不被取代**。🔴 并且本轮把原因量化了：**单用户的一把批结构性拿不到 ≥20 样本** —— QUERY 桶 = 10/用户·分钟（`app/api/ratelimit.py:203` 现读 `RateLimitRule(QUERY, 10, 100)`）而 429 **秒回** ⇒ 30 条挤在 22 秒内发完 ⇒ 只有一个窗口的量能准入。要拿到样本只有两条路（① `c=1` 串行 ≈300s，能准入 ~28 但**丢掉 c=3 那一格并发**；② 多用户令牌保住 `c=3`，可准入 ~28、约 ¥0.19），**两条都超出"一把批"的字面授权 ⇒ 已交回，本窗不擅自做**。
- **`U-129` 三格并报（落库面，作用域 = `user_id = 'u_t38c3'`，具名剔除作废格那一条）**：**格1** = ⑮ 两臂 `0 ∧ 0`；**格2** = `t2_routed_audit_supp_without_terminal_write = 0` **且第四件前置 `t2_routed_supp = 3 > 0` ⇒ 非空真达成**；**格3** = `t2_with_terminal_write ≥ 1` ⇒ 达成；pre-fix 基线仍 = **5**（存量域不折叠）。🔴 本窗只交数与形状，**"已修／已结案"由验收窗写**（复算 = `deploy/loadtest/r23_thread_from_checkpoints.sql` 的 ⑮／⑰，参数 `win_a='2026-10-06 04:25:59+00' win_b='2026-10-06 04:27:00+00' upref='u_t38c3%'`；两份输出已归档 `backend/reports/w8/evidence/t38/`）。
- 🔴 **新立一号 `U-138`**（取号依据 = `docs/07 §4.8` 指针行 v1.7.21 那句「下一个可用号 = `U-138`」）：压测回执 `thread_depth` 的分组键是 `(worker, session_id)`，而服务端 thread 是 `tenant:user:session` ⇒ 同一把批实测 **7 ≠ 3**，"第 N 轮"的分母在回执侧不可用 ⇒ 判据三条与复算命令见 `docs/07 §4.8` 的 `U-138` 行。
- **演示脚本红线（新增一条，`deliverables/ACCEPTANCE.md` §3 同源同改）**：🚫 **不当场点「发起评测」** —— 那一支现在是**预检**（`run_id` 恒 `null`、面板自己写着"未发起评测"），而"真发起"要打 **538–620 条调用／¥0.337–0.392**，那是另一笔钱、另一轮批准。
- **对外口径不变**：上线门禁 **PASS 1/8** ⇒ 任何场合**不得写"门禁通过"**。

🔻 **10-06 第 16 轮（T-39，QA 第 19 轮派单；🔴 本轮零额度／零出站／共享库只走只读事务）收口读数 —— 上面第 15 轮那段保留为历史读数，本轮没花一分钱**（面 = 工作树在 `70012e7`／453 笔之上；时刻 = 13:5x–15:0x ＋0800；粒度 = 逐格点名，每格自带可复跑命令）：

- **`U-129` 结案引用 ③ 的两半现在同格齐了（`ok` 率 ＋ H）**：`ok` 率 = **4／`admitted` 9 = 44.4%**（另一把分母 = 4／发出 30 = 13.3% ⇒ 跨批比只许用准入那一把，两个分母不许混）；
  **H 按通则「一律按当日实际发 LLM 的节点集合取」= 本批节点集合含第 5 档 `repair` ⇒ 权威读法 H = 8.12s**（窄窗四格 6.59s ＋ `repair` p50 1533ms）。
  与盘上 `U-126` 那句「W7 四格 p50 相加 = H = **5.99s**」**同口径可比**的那把 = **6.59s**（窄窗 `04:25:59→04:26:22Z`：`normalize_intent 1076.0(n9) ／ plan 1657.0(n8) ／ l4_score 2021.0(n7) ／ gen_sql 1838.0(n7)`）；
  宽窗（⑮⑰ 那把 `04:25:00→04:27:01Z`）= 6.69s／含 `repair` 8.22s，🔴 **但宽窗含作废那跑的 4 条**（作废格的时间落 `04:25:06–04:25:23`）⇒ 用它算 H 等于把作废格拉回分母，本窗只把它作"同 ⑮⑰ 作用域"的参照值。尺 = `PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w8/t39_h_cell.py`（只读 `docker logs`，产物 `backend/reports/w8/t39_h_cell.json`）。
- 🔴 **与 QA 第 19 轮那把 H 的差 = 一个窗边界，两把都留**：QA 的窄窗 `--until 04:26:21Z` 把落在 `04:26:21.407071` 的那条 `gen_sql`（1802ms）切在窗外 ⇒ 它得 **6.76／8.30s**、本窗含末帧得 **6.59／8.12s**。
  谁也不覆盖谁；引用必须点名"含末帧还是切末帧"（这是本项目第 N 次撞上"取窗不具名"）。
- **`repair` 口径裁定（本窗采哪条 ＋ 理由）**：采**含 `repair`** 为权威。理由 = ① 通则字面写的是"实际节点集合"，`repair`（闸门拒后修 SQL 那一跑）本批真的发了一次（n = 1）；
  ② H 的用途是**槽位配平**，一个 run 占着槽位的时间包含 `repair` 那一段；四格那把只作与历史值同口径的可比值并报。
  ⚠️ 方法论诚实面：H 的口径是"逐槽 p50 相加"，而 `llm_call` 日志行**没有 run 标识** ⇒ "逐 run 相加再取分位数"这把**做不到**（不是没做），所以只能沿用盘上口径。
  🔴 **同框必带的一句：冷启动没有剥离**。上面那两把 H 里，**每一条 `llm_call` 都可能是冷的那一条** —— 现测宿主 `LastBootUpTime = 2026-10-06 04:04:56Z`、容器 `commerceql-api-1` 的 `State.StartedAt = 04:10:42.9Z`（而 `Created` 仍是 10-05 那次镜像的 `15:19:26Z`），主批 `started_at = 04:25:59Z` = **容器起后 15m17s／宿主重启后 21m03s**。
  本轮唯一的剥离动作是**预热那一跑被具名作废**（`04:25:06–04:25:23Z`，不进任何分母），它剥的是"第一批"而不是"每一槽"；加上日志无 run 标识 ⇒ **想按 run 剥离也没有尺**。⇒ 引用这两把 H 时只许说"当期批、作废格已剔除、冷启动未剥离"，🚫 不许说"已剥离冷启动效应"。
- **连带义务（`U-126` v1.7.5 那句 `H ∈ [5.99, 6.18]`）**：本期四把读数 **6.59／6.69／6.76／8.12／8.30 全部穿破上界** ⇒ 那个区间已不是本期形状；
  而「`U-128` 落地后仍须同一口径复测一次」那条回交义务**本轮交不回数**（`U-128` 未落地 ⇒ 没有可复测的对象）⇒ **写明仍未，槽位配平表因此仍不按现状收**（不擅自动判据）。
- 🔴 **`U-137` 已落地（离线面），但演示那句今天仍不出数**：实现 = `app/guard/ast_gate.py::_side_logical()`（CTE／派生侧展开成其所读取的资产集合）；
  文案 = `app/guard/rules.py` 的 `_msg_join_path()`／`_msg_cartesian()` ⇒ **R10/R11 不再与"越权"共用一句**（R05/R13 原句不动），抄本 = `docs/07 §7.2` AST-R10 行 v1.7.23 落地句 ＋ §7.6 分组**由一行拆三行**；
  夹具 = `backend/tests/contract/test_r10_cte_join_contract.py` **五条**（含"CTE 体内藏未认证边仍 R10"那支反面形状，防"CTE 一律放行"）；冻结红队 R10 三臂 **仍 `R10`×3**、`tests/redteam` 11 passed。
  🔻 **对外只可写**："闸门的路径未认证与越权**已分句**；『先聚合再连维表』这一形状在离线面按资产口径参与判定（夹具那条 776 字符骨架现在放行）；**这道题在活体里生成的三条变体今天仍全被拒**（R06×2／R10×1，见上面那条订正），且**活体面还没带上本轮改动**（镜像 `Created = 2026-10-05T15:19:25Z`、未 build／未 recreate）。"
  🚫 不得写"演示那道题修好了"。🔻 **同轮就地订正本格上一句里的一个措辞（原句保留）**：「这道题在活体里生成的三条变体」是**错的** —— 那三条 `GATE_AST_REJECTED` 来自 **2 个题面**（`app.audit_log.raw_question` 现读：复购率那句 1 条／客单价那句 2 条，尺 = 件内 `question_tally_per_rejected_run`）；演示那句**恰是被改判的那一条**（R10 → R06），"仍全被拒"这个结论不变。
- **`U-138` 已落地（量具面，`app/**` 一字未动）**：`thread_depth` → **`worker_session_depth`**，读数里自报 `grouping_key = "(worker, session_id)"` ＋ `is_server_thread = false` ＋ 库面尺指针，计数键 `threads` → `groups`；
  `--self-check` **10/10 rc 0**；新契约 `backend/tests/contract/test_loadtest_thread_key_contract.py` **5 条**（含"当期回执两把同框并报"）。
  🔴 **刻意不升 `SCHEMA_VERSION`**（仍 `w7.loadtest.receipt/1`）：唯一消费者 `eval/reporter.py:185` 按版本串相等才认这份回执，升版会让 **G-6 的输入静默变 `None`**（reporter 自己注释原话）⇒ 改名只动消费者不读的格。
- **B 三处（F2／F3／F4）已当场修并重跑装配**：f 格现读 `证件 rev = bea724a / 449 笔 / generated 04:42:25 / offline passed = 2454 / integration passed = 124`；
  `passed` 那半格的坏尺（`str(dict)` 里找 `passed=` 恒不命中 ⇒ 永远印 `—`）改成直取键值、拿不到写 `UNVERIFIED`；单价分子分母同面（见上面第 15 轮那格的订正）。尺同上，产物 `backend/reports/w8/t38_assembled.json`。
- **静态与测试面（计数全部带 HEAD，现测于 `70012e7` 之上的工作树）**：`ruff check --config pyproject.toml app` ＋ 整目录那把尺 = **All checks passed!／0 条**（🔴 第 15 轮我把 `_audit_layout.py` 拷进树时**没跑整目录那把尺** ⇒ 带着 3 条 `E741` 进库、本轮才发现，已改名修掉，见 `RELAY §17.7`）；
  `mypy app` = **no issues in 158 source files**；`lint-imports` = **4 kept／0 broken**；前端两门（本轮 `frontend/**` 一字未动 ⇒ 属"未改动确认"）= `npx tsc --noEmit` **rc 0／输出 0 字节**、`npx eslint . --ext .ts,.tsx` **rc 0／0 字节**（本窗现测 `07:35Z`，与 QA 第 19 轮那把 eslint 同值但不互相顶替）；离线面与集成面的读数见 `backend/reports/w8/RELAY.md §十七`。

🔻 **10-06 第 17 轮（T-41 · QA 第 20 轮派单「零额度四件 A–D，全是落笔与口径」）收口读数 —— 上面第 16 轮那段保留，本轮没动一行实现代码、没花一分钱**（面 = 工作树在 `360498d`／459 笔之上；时刻 = 18:3x–18:5x ＋0800 ／ 10:3x–10:5x UTC；尺全部是盘上产物 ＋ 只读事务）：

- 🟢 **`U-129` 转绿（QA 第 20 轮裁定，2026-10-06；本窗只把裁定落盘、不自裁）**，状态格落在 `docs/07 §4.8` 该行（结案引用四件逐件点名当期位置：① `RELAY §16.4` ＋ `evidence/t38/r23_scope_*.txt`；② 直读式 = 0（`r23_thread_from_checkpoints.sql` ⑮／⑰）；③ `t39_h_cell.json` 的 `ok` 率与三把窗 H；④ `test_audit_terminal_pairing_contract.py`）。🔴 **三条限定语必须与"转绿"同框（缺一即按 `UNVERIFIED` 记）**：**(a)** 当期性**只认构建身份**（逐件 md5 ＋ 全量 158 件聚合 ＋ 层 3 `RUN_SCOPED_STATE_FIELDS`），🚫 不得用 `app.audit_log` 的日期窗追认当期；**(b)** 该行 v1.7.10 那句照抄 = **「本号转绿会作废三批读数，转绿语必须点名」** ⇒ W7 侧的 **`ok` 率 / H 实测值（当时引用 `6.18s`）/ 轮次分布**三批自本刻起**一律作废、须重测后才可引用**，并按规矩「**新镜像首格作废 ＋ 跑前预热一格**」；**(c)** 镜像 `Created = 2026-10-05T15:19:26Z`、第 15／16 轮**都没重建** ⇒ 🚫 不得写"活体面已带本轮改动"。⚠️ **v1.7.13 句 A 照用 = 「结案不依赖活体臂」** ⇒ 本号**不许再跟 `G-6` 那笔钱焊回一条**（样本几何是 `G-6` 的前提，不是本号的前提）。
  🔻 **本轮把 (a)/(c) 现测成硬证据**（零出站；尺 = `deploy/loadtest/attest_build_identity.py --receipt <仓库外副本> --container commerceql-api-1 --files backend/app/guard/ast_gate.py,backend/app/guard/rules.py,backend/app/api/ratelimit.py`，`attested_at = 2026-10-06T10:36:52Z`）：逐件 **SAME 1/3**（`ratelimit.py` SAME，`ast_gate.py`／`rules.py` **DIFF**）、全量聚合 **equal = false**（158 件对 158 件、聚合串不等）、层 3 **present = true** ⇒ 🔴 **"158/158 三面相等"这句话只对 `4f08698` 之前的构建成立，自第 16 轮 `U-137` 落进 `app/guard/**` 起不得再照抄**（这不推翻转绿，因为引用面是第 15 轮那把批当时取到的三面）。
- 🟢 **`U-137` 已结案（QA 第 20 轮裁定）**，🔴 **同格写明它不覆盖什么**：随交件实测 = 3 条 `GATE_AST_REJECTED` 里**改判 1 条、放行 0 条、题面 2 个**；演示那句「上个月复购率最高的 10 个店铺是哪些？」**今天仍不出数**，现读拦点 = **R06 =「查询包含受保护字段」**（`gate_result.reason` 现读，尺 = `backend/reports/w8/t41_r06_block_cell.py`，产物 `backend/reports/w8/evidence/t41/r06_block_cell.json`；依 `U-125` 判据④，这类 `rule_id` 归因**只算离线器件**）⇒ 属**列面／语义包**、与 JOIN 路径无关 ⇒ 要让它出数得动**语义包／列权限面 = 另一件主单**，🚫 不许讲成"`U-137` 修完就能演示"。
- 🔴 **B 面名点清（QA 第 20 轮 G2）**：第 15 轮登记的 **2,454** 的面 = **三目录**（`tests/unit`＋`tests/contract`＋`tests/eval`），而第 16 轮的 **2,478／2,485** 的面 = **五目录**（再加 `tests/redteam` 11 ＋ `tests/graph_snapshot` 13）⇒ 上面那条「开工同尺实采 2,478 ⇒ ＋7」里的**"同尺"不成立**、两数不可相减；逐目录 `--collect-only -q` 两棵树实测（闭合表在 `§7` 第 16 轮指针 ④ 的 🔻 补记）⇒ **+24 归因完成 = 11 ＋ 13**、结案条件（逐目录之和 == 日志 passed）**闭合**。
- 🔴 **C（QA 第 20 轮 G3）**：G-1 的判定输入是那两把 **未跟踪** `.log`（`.gitignore:47`）⇒ 整树 `git archive` 到仓库外只带 p0-summary 重算 ⇒ **G-1 掉成 `NOT_AVAILABLE`（PASS 0/8）**，其余七格逐词同 ⇒ 引用规矩已落 `§7` 的 G-1 格 ＋ `docs/07 §16.5`（v1.7.24 新增第三条）。
- ⚠️ **本轮另两处落笔**：`U-138` 行加 🔻 进度补记（改名与契约已在第 16 轮落盘、仍欠一份**带 `worker_session_depth` 的真回执** ⇒ 状态 = **部分达成、不结案**，按 QA 17.2③ 与 **T-40 并成同一把批**）；`docs/07` 的 **`文档版本` 字段两轮漏改**（曾停在 `v1.7.21` 而修订表已有 v1.7.22／v1.7.23）⇒ 本轮抬到 **v1.7.24** 并具名。
- **对外口径不变**：门禁 **PASS 1/8**（本轮没动判定输入 ⇒ 入库件仍是第 16 轮那份，自报 `f7bf106`／dirty false，入库笔 `ee7c3d9`）⇒ 任何场合**不得写"门禁通过"**；`G-6` 仍不可引用（9 < 20）；演示三句维持（🚫 不当场点「发起评测」／「评测集」下拉 DOM 尺 = **2**／新文案在活体页面上**还看不到**，镜像未重建）。
🔻 **10-06 19:2x 起 ＋0800 ／ 11:2x 起 UTC 第 18 轮（T-42 · QA 第 21 轮派单「零额度三件 A–C」）落笔读数 —— 上面第 17 轮那段保留、不改写；本轮唯一代码写面 = 量具本身 `deploy/loadtest/attest_build_identity.py`（`backend/app/**`、`backend/tests/**`、`driver.py` 一字未动），没花一分钱、没建一次性库**（面 = 工作树在 `28c580b`／462 笔之上；尺全部是 `git show` ＋ `docker exec … md5sum` ＋ 盘上产物）：
- 🔴 **第 18 轮（T-42 B）措辞换代：构建身份对外只写两链，不写「三面相等」**（判据措辞一字未改；`docs/07 §16.5` 层 1 行 ＋ `U-129` 行 限定语 (a) ＋ `ACCEPTANCE §3` ＋ 本节 §7 同一轮改，只改一处就是第二份真相）。🔴 **构建身份对外只写两链**：**链一「容器 ⟷ 工作树字节」**= `attest_build_identity.py` 逐件 `verdict` ＋ 聚合 `two_links.container_vs_worktree`（这把尺**真量到的**那一面）；**链二「工作树 ⟷ HEAD」**= 逐件 `worktree_vs_head_lf` ＋ 聚合 `two_links.worktree_vs_head` ＋ 跑前 `worktree_dirty_at_attest = false`。两链都通才可以说「容器 == HEAD」；🚫 不再写「三面相等／git 面已比过」。本轮（第 18 轮，HEAD `28c580b`／462 笔，容器 = `commerceql-api-1`）修后现测：① `backend/app/api/ratelimit.py` 三把变体（`worktree_raw`／`worktree_lf`／`head_blob_lf`）**全相等** = `7d2cdc4d387ae9339e6d03792e196a2a` 且与容器面同值；② `backend/app/graph/state.py` 的 `head_blob_lf` = **`0474ef6af7e32345b538456c28735513`**，与 `git show HEAD:… | md5sum` **逐字符同值**（= `docs/07 §16.5` 层 2 表钉住的那串真值）；③ `backend/app/guard/ast_gate.py` 报**无命中**（容器 `cf698983…` ⟂ 工作树 `f0c9e616…`（LF 归一 `a9443bff…`）⟷ HEAD `a9443bff…` ⇒ 链二 SAME ／ 链一 DIFF）；聚合 158 件对 158 件、**链一 False ／ 链二 True**；`--self-test` **3/3 PASS**（零 docker、零出站）。产物 `backend/reports/w8/evidence/t42/attest_{pre,post}_fix_probe.json` ＋ `attest_closure.json`。⚠️ **这不是把第 15 轮的当期性证据判作废**：那句「逐件 18/18 ＋ 全量 158/158」当年**不是假结论**（本轮修尺后回算，`ratelimit.py` 三把确实全等、`state.py` 的 git 面确实等于 `0474ef6a…`），**高估的是证据强度**——逐件那把尺的 git 面当时根本没参与比较。两链照常成立，只是**链一由尺证、链二由 `rev + dirty` 证**；`U-129` 的转绿不受影响（它引用的是第 15 轮当时取到的两链）。 🔻 上面第 17 轮那句「`158/158` 三面相等只能引用为 `4f08698` 之前构建的读数」现在有更准的写法：**那把逐件尺当时就没量 git 面**，所以「三面」这个量词从来不曾成立，成立的一直是两链。
- 🟢 **第 18 轮（T-42 A／C）取号与结案**：本轮新立案并当场结案 **`U-139`**（依据 = `docs/07 §4.8` 指针行 v1.7.24 那句「下一个可用号 = `U-139`」；三条理由采纳 QA 的：错述被对外件引用、修法动 `deploy/**` 不是纯落笔、与 `U-138` 对象不同不并号）⇒ 指针行抬到 **`U-140`**、修订表加 **v1.7.25** 行、`文档版本` 字段一并抬到 v1.7.25（第 17 轮已具名过一次「两轮漏改」，本轮不再犯）。⚠️ 尺修好后**只影响取证面，不影响任何判定量**：门禁八格本轮没重算 ⇒ 对外仍是 **PASS 1/8**（入库件仍是第 16 轮那份），`G-6` 仍不可引用（9 < 20）。
- ⚠️ **本轮具名一处环境事实（给总控，影响下一把花钱批）**：被测容器 `w7load-api` **本轮开工前已不在 `docker ps -a`**（只剩 6 天前的 `w7load-api_pre0930r11_bak`），镜像 `w7load-api:latest`（digest `4adbcfc2e8f6`、`Created = 2026-10-04T16:06:22Z`）仍在 ⇒ 本轮容器面取自共享栈 `commerceql-api-1`，而 `docs/07 §16.5` **禁令 ②** 写明共享栈**不是被测构建** ⇒ 🔴 **T-40 那把批开跑前得先由总控定靶**（沿用共享栈就照实写「被测面 = 共享栈镜像」，或单独批一次重建）。另订正一处旧标签：`§16.5`／回执里那句「镜像 `Created = 2026-10-05T15:19:26Z`」量的其实是**容器**创建时间（`docker inspect .Created` 打在容器上），镜像 `Created` = `2026-10-05T15:19:25Z`（`commerceql-api`）／`2026-10-04T16:06:22Z`（`w7load-api:latest`）⇒ 两者只可并列、不可互换。 🔻 **第 19 轮补一句（T-43 C）**：这条事实已经落成对外可念的**靶子格**（三个候选面都不含今天的 `app/guard/**`、逐面带 image id 与现读尺），落在 §9 末「未闭清单（第 19 轮收口定稿）」；🚫 在总控点「要不要 build」之前，任何 `G-6`／活体句只能挂在那两份旧构建之一上。

---

## 7. 质量现状：上线门禁 1/8（这一段是本项目最诚实的部分；🔻 10-03 第 6 轮之前是 0/8）

**门禁定义**：`docs/07 §17.3`（**八格 = G-1…G-8** 的唯一定义处）＋ `eval/gates.py`（件在**仓库根**、不在 `backend/`）。
🔻 旧句写的「附录 C §C.8」那一份**只到 G-1…G-7 七格**（`04` 现读没有 G-8）⇒ 引条数前必须点名是哪一份。
判定词表 `PASS / FAIL / PARTIAL / UNVERIFIED / NOT_AVAILABLE`，`PASS` 之外一律不得进入"门禁通过"的汇总句；
八格输入的**唯一装配口** = `eval/reporter.py` 的 `gate_inputs()`，复算**只**走 `recompute_gate(格号, **产物路径)` ⇒ 在别处再装配一次就是第二份真相（QA `T-30` 判据原文）。

**最新一份报告**：`CommerceQL/backend/reports/w6/评测报告与门禁判定.md` ＋ 同目录 `eval_metrics.json`，由 `eval/reporter.py`
（venv 解释器、cwd = `backend/`）于 **2026-10-05 15:15:31 +0800 = 07:15:31Z** 从 rev **`a688473`** 那棵**干净树**重算（当期两把日志 = `_full_pytest_1005_rT36.log` ＋ `_integration_pytest_1005_rT36.log`），
`meta.git = {rev: a688473, dirty: false}`、入库笔 **`9f183e1`**。🔻 **历史指针（第 9 轮那次）= 10-04 18:51:44 +0800 ＝ 10:51:44Z、rev `a84fc6f` ＋ dirty true**，保留作史料、不当现状。
🔴 **那一份（第 9 轮）dirty 的 11 行里没有一行是被测代码逻辑**：现算
`git diff --stat a84fc6f -- backend/app backend/tests eval frontend deploy` = **只有 `backend/app/cache/keys.py` ＋3／−1**，
且那一处整段落在那个函数的 docstring 里（`git diff a84fc6f -- backend/app/cache/keys.py` 可逐行验）；其余 10 行是九份旧窗
`PROMPT.md` 的停用横幅 ＋ 一件未跟踪的 `reports/w8/t31_three_cells.json`。
🔴 **总判定 PASS 1/8**（counts = PASS 1／FAIL 3／UNVERIFIED 2／PARTIAL 2／NOT_AVAILABLE 0）⇒ **对外不得写"门禁通过"**，任何一格的 PASS 都不构成上线许可。
本轮**只换掉一格的输入**：G-1 的两把日志（当期树 ＋ 一次性库）。其余七格的产物仍产自旧构建 ⇒ 那七格的**判定词**由当期 `gates.py` 算、
**数**却是旧产物里的数（逐格的"时刻／HEAD"见下面表 B）。要让 G-2／G-5／G-8 连数一起换，唯一姿势是**再打一次 `--live` 全量**（三者共用
`eval/results_v1.json` = 第二批全量真打 166 题、¥0.391504）⇒ 属花钱项，本轮按派单**零额度**、不做。
历史指针（`079916d` 那份、更早的 `8ffb53e`／`passed=2312`、第一次真打 `66d5fba`／¥0.337171）照旧**作历史读数保留，不删**。

🔻 **10-06 第 15 轮（T-38）报告指针（上面那段"最新一份 = `a688473`／`9f183e1`"从本刻起是历史，原句保留）**：现最新 = `eval/reporter.py` 于 **2026-10-06 12:5x ＋0800 = 04:5xZ** 从**干净树**重算两遍（两遍都带 `--json-out` ＋ `--md-out` 指**仓库外**）的 `backend/reports/w6/eval_metrics.json` ＋ `评测报告与门禁判定.md`。
🔴 **两个身份格都别抄本行**（`PROMPT §2 ④` 两格并报）：件内自报 = 现读该 JSON 的 `meta.git`（`rev`／`dirty`），入库笔 = `git log -1 --format=%h -- backend/reports/w6/eval_metrics.json`；本窗自己的落盘笔会继续把它们后移 ⇒ 引用前实跑这两条。 🔻 **第 18 轮（T-42 B）追加**：本段这两个身份格说的是**链二**（工作树 ⟷ HEAD，由 `meta.git.rev` ＋ `dirty` 供给）；**链一**（容器 ⟷ 工作树字节）不在 reporter 的输出里，只能由 `deploy/loadtest/attest_build_identity.py` 另取 ⇒ 凡涉及**活体容器**的当期句一律**两链并报**（尺与读数见 §6 第 18 轮那条 ＋ `docs/07 §16.5` 层 1 行）。
当期两把日志 = `backend/reports/w8/_r15_offline_cleantree.log` ＋ `backend/reports/w8/_integration_pytest_1006_rT38.log`；G-1 的**取证件本轮一起当期化了**（`backend/reports/w8/gate_inputs_p0_summary.json` 现自报 `git_rev = bea724a…`／**449** 笔／`git_dirty = false`／offline 2,454／integration 124）⇒ **上一轮那句"取证件 ≠ 本次输入"的 caveat 本轮闭合**（尺 = 复算命令里 `--p0-summary` 与两把日志同批当期）。两遍差尺点名 6 项白名单 ⇒ **判定量 0**。
🔴 **条数增量必须点名基线**（QA 15.5 第 1 条）：本轮**没新增用例** ⇒ 离线 **2,454**／集成 **124** 与**第 14 轮入库那份逐位相同（＋0／＋0）**；"＋62／＋17"这类差只对**第 13 轮入库那份（2,392／107）**说，"＋1"只对**第 14 轮轮内中间跑（2,453）**说 ⇒ 三个基线不是一回事，裸写增量会造出"＋62 条从哪来"的假问题。
八格判定词**未变** = **PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2**（`G-1` PASS；`G-2`／`G-5`／`G-7` FAIL；`G-3`／`G-4` PARTIAL；`G-6`／`G-8` UNVERIFIED）⇒ **对外不得写"门禁通过"**。⚠️ `G-6` 本轮**没有被那把真跑批改变判向**（9 样本 < 20 下限），细节见 §6 收口段的 G-6 那一格。
🔻 **同轮补记（一处本机时钟对表，跨面比时间之前必读）**：本轮 12:1x ＋0800 现测 **宿主 `date -u` ＝ 容器 `date -u` ＝ 外部 HTTP `Date` 头** 三者同秒（`04:16:56Z`／`04:16:58Z`，尺 = `curl -sI https://api.github.com/zen`），而**上一轮落盘那一分钟内宿主与容器曾相差 11h39m**（宿主读 `2026-10-05T16:31:54Z`、`docker inspect .State.StartedAt` 读 `2026-10-06T04:10:42Z`）⇒ 凡"报价笔 committer date ⟷ 回执 `started_at` ⟷ 库内 `created_at`"这类**跨面比时间**，落笔前先把这三处对一遍，并在句子里点名比的是**哪一侧的钟**（本轮 `U-129` 报价格比的是宿主侧 git 与 driver 两侧，同钟 ⇒ 可比；落库面时间戳来自容器侧，本轮两侧一致）。

🔻 **10-06 第 16 轮（T-39，零额度）报告指针（上面 244–249 那段"现最新 = 12:5x ＋0800 那两份"从本刻起是历史，原句保留作取证）**：现最新 = `eval/reporter.py` 于 **2026-10-06 15:2x ＋0800 = 07:2xZ** 从**干净树**重算两遍（两遍都带 `--json-out` ＋ `--md-out` 指**仓库外**）的 `backend/reports/w6/eval_metrics.json` ＋ `评测报告与门禁判定.md`。
① **身份格三连发才对上**（新坑，写在这里防下一轮重犯）：取证件写进 JSON 的 `git_rev` 与"把它提交入库"那一笔**天然差一笔** ⇒ 本轮连发 `1e98aa7`→`5a6caed`→`f7bf106` 才拿到 `dirty = false`。件内自报现读 = **`f7bf106`／dirty false／generated `2026-10-06T07:23:55+00:00`**；入库笔按 `PROMPT §2 ④` **两格并报**，尺 = `git log -1 --format=%h -- backend/reports/w6/eval_metrics.json`。
② 两把当期输入 = `backend/reports/w8/_r16_offline_cleantree.log`（**2,485 passed／0 failed／rc 0**）＋ `backend/reports/w8/_integration_pytest_1006_rT39_v.log`（一次性库 `ecom_t39it_r16`：建 → 授权 → owner → alembic 到 `0006` → `-v` 跑 → **当场 DROP**，**124 passed／rc 0**，残渣尺 `datname like 'ecom%'` = **2** = 共享 `ecom` ＋ 别窗的 `ecom_u123_probe`，后者不删）⇒ `integration_ran = True`。🔴 **本轮在自己身上复现了上面 G-1 格那条"形状尺"**：集成层先按 `-q` 跑 ⇒ 日志里没有 `tests/integration/*.py` 文件名 ⇒ `reporter` 判集成没跑、G-1 当场从 PASS 掉到 **PARTIAL**；改 `-v` 重跑才对上（那份 `-q` 日志已删，不留第二真相）。⚠️ **两把日志的"所在面"分开点名**：上面那句"干净树"只描述 **reporter 那两遍重算**；离线那把跑的文件名叫 `_r16_offline_cleantree.log`，但它**跨在提交边界上**（15:17:42 起、15:19:30 止，`4704966` 在 15:19:04 入库）⇒ 对那把跑不许写"干净树跑的"，所在面按尺认 = `git diff --name-only 4704966 -- backend/app deploy` **0 行**（被测代码面与该笔逐字节相同）。详见 `RELAY §17.6 ⑥` ＋ `§17.7` 第 8 条自曝。
③ 八格判定词**未变** = **PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2**（G-1 PASS；G-2／G-5／G-7 FAIL；G-3／G-4 PARTIAL；G-6／G-8 UNVERIFIED）⇒ 🔴 对外**仍不得写"门禁通过"**；`G-6` 仍不可引用（当期样本 9 < 下限 20，本轮零出站、没有新批）。两遍重算的递归 diff ⇒ **判定量 0**，唯一差 = `meta.generated_at`（相差 3 秒）；报告 md 里「取证件」字样命中 **0**。
④ ⚠️ **条数增量必须点名基线**（QA 15.5 第 1 条同源）：离线 **2,485** 对本窗开工同尺实采 **2,478**（HEAD `4f08698`）= **＋7**（本窗确证：新增 U-138 契约 5 条 ＋ `test_r10_cte_join_contract.py` 由 3 支改 5 支 ⇒ ＋2）；而对第 15 轮入库件登记的 **2,454** 差 **+24 无法归因** ⇒ 🔴 按「只报实测」列为**交回项**，本窗不自编解释，等 QA 用同一 `--collect-only` 口径与同一 HEAD 对撞。集成 **124** 与第 15 轮逐位相同（＋0）。
🔻 **第 17 轮（T-41 B；QA 第 20 轮 G2 点名）就地订正本条的"同尺"二字（原句保留作取证）：面变了 ⇒ 这几个数分属两把尺，不可混比。** 第 15 轮登记的 **2,454** 的面 = **三目录**（`tests/unit` ＋ `tests/contract` ＋ `tests/eval`，逐字见 `backend/reports/w8/RELAY.md §16.8` 那行），而 **2,478／2,485** 的面 = **五目录**（再加 `tests/redteam` ＋ `tests/graph_snapshot`；`tests/` 下总共就这六个目录 ⇒ "五目录"与"整树减集成"是同一把尺）。逐目录 `--collect-only -q`（条数取 `::` 行数）本窗在**两棵树各跑一遍**：

| 目录 | `4f08698`（第 16 轮开工前） | HEAD `360498d` | 差 |
|---|---|---|---|
| `tests/unit` | 1,422 | 1,422 | 0 |
| `tests/contract` | **608** | **615** | **＋7**（线程键契约 ＋5、R10 契约 3→5 ＋2） |
| `tests/eval` | 424 | 424 | 0 |
| `tests/redteam` | 11 | 11 | 0 |
| `tests/graph_snapshot` | 13 | 13 | 0 |
| **三目录小计**（第 15 轮登记的面） | **2,454** | **2,461** | ＋7 |
| **五目录小计**（本轮实际的面） | **2,478** | **2,485** | ＋7 |

⇒ 上一轮那句「**＋24 无法归因**」现在**归因完成 = `tests/redteam` 11 ＋ `tests/graph_snapshot` 13**（第 16 轮把面从三目录加宽到五目录），一条测试都没丢、也没多出；🔴 结案条件同格闭合 = **逐目录之和 == 日志里的 passed 数**（五目录 2,485 ⟷ `_r16_offline_cleantree.log` 末行 `2485 passed`）。⚠️ 加宽方向是**变严**（多跑两个目录）⇒ 不改任何门禁判向，破的只是**可比性** ⇒ 从本刻起引用这两个数**必须带面名**（"三目录 2,454"／"五目录 2,485"），🚫 不许再写"同尺 ＋7"或把 2,454 与 2,485 相减。

🔻 **同轮第二次重算（19:23:28 +0800 = 11:23:28Z，在已经提交完的干净树 `cbff229` 上跑）**：八格的判定词、`measured`、caveats 与整个取证面**逐字节未变** —— 两份产物的全量递归 diff 只有 **5 条**（`meta.generated_at`、`meta.git.rev` 由 `a84fc6f` 到 `cbff229`、`meta.git.dirty` 由 true 到 false、`gate_provenance.report_git.rev` 与 `.dirty`）。⇒ 这一条同时把来件起点读数②（「`eval_metrics.json` 仍是 `079916d`＋dirty」）**结掉一半**：产物现在自报 **`cbff229` ＋ dirty=false**，而「重算可复现」不再是我的叙述、是这 5 条 diff。⚠️ 引用 `meta.git` 时**必须点名是哪一次**：18:51 那次给 `a84fc6f`＋dirty，19:23 这次给 `cbff229`＋干净。

| 门禁 | 目标 | 本次实测 | 为什么不能算通过 |
|---|---|---|---|
| G-1 全部 P0 用例通过 | 0 红 | **PASS**（🔻 10-03 第 6 轮转绿；**10-04 18:51 第 9 轮把两把输入换成当期树**）：断言失败 **0** ＋ 环境未备 **0**（收集期 0／夹具期 0）⇒ 红 **0** 条；规模 **离线 passed=2,347 ＋ 集成 passed=107**，`integration_ran=True`。🔴 **合树单日志对照臂**（专门防"合并把红抹平"）：整树 `-v` 一把跑 = **2,454 passed／0 failed／0 errors／rc 0／107.90s**，且 **2,347＋107 = 2,454 逐位对撞** ⇒ 本轮"红的两列只从集成层日志取"这一格**没有掩盖任何东西**（那把对照跑在文档串／横幅改动之前的同一 `a84fc6f` 树上） | 已满足判据。⚠️ 两栏必须分开报：`gate_inputs()` 合并两份日志时把 `passed` 覆盖成集成层那一个数（107），直接引它会把 107 读成全量规模。🔴 同一处合并还把 `failed`／`errors` **只取集成层那份** ⇒ 若离线面有红会被抹平；本轮靠上面那把整树对照排除，器件本身登记在 `reports/w8/RELAY.md` §九.6（动它 = 改唯一装配口 = 判据面，本窗不自裁）。🔴 **另一把形状尺**：`reporter` 判"集成跑没跑"靠**日志里有没有集成文件名** ⇒ 集成层必须 `-v` 跑；用 `-q` 跑真 107 条、`integration_ran` 仍给 `False`、G-1 当场从 PASS 掉到 PARTIAL（10-04 本机实测两遍）。🔻 历史读数保留：上一份两把日志（10-04 01:3x、rev `079916d`＋dirty）给的是 离线 **2,340** ＋ 集成 107，**＋7 = U-131 那七条属主契约用例**；更早 FAIL／红 8 条＝环境未备 8、`passed=2312` 那 8 条是 PG DSN 权限（`U-132` 触发面）不是被测系统；再早四轮 `2238`／断言失败 2 那 2 条经三臂对照归因 = 环境红。集成层复算命令见 `backend/reports/w8/RELAY.md` §九.2 ＋ §六.10（一次性库 `ecom_t30_it`，禁指共享 `ecom`） 🔻 **10-04 20:4x 第 10 轮（T-32）：输入换成当期树 ＋ 装配口径改掉「后者覆盖前者」**：离线 **2,359** ＋ 集成 **107**，红仍 **0**、判定词仍 PASS。🔴 上面那句「靠整树对照臂排除合并污染」**已退回改写**——加法只覆盖 `passed` 那一支，`failed`／`errors` 当时只从集成层日志取 ⇒ 那条对撞证明不了红没被抹平（QA 第 7 轮 ④ 注入夹具坐实）。现由 `eval/reporter.py:merge_p0_logs()`（四件计数两侧相加、点名列取并集、`integration_ran` 取 OR，每列另留 `_offline`／`_integration` 两档）＋ **两态反证件**钉住：脏态（离线 1 红／集成 0 红）判定必 **FAIL**、**修复前对照臂**同一对日志必读 0、整树 `-v` 那把不重复相加 ⇒ `backend/tests/eval/test_gate_inputs_p0_merge_two_state.py`（12 passed）。判据措辞与判据词表**未动** ⇒ 留笔只在 `07 §17.3` 的 G-1 行与 `§17.1` 的集成行（v1.7.19）。取证等级：本格三件产物里第三件 `backend/reports/w8/gate_inputs_p0_summary.json` = **`self_reported`**（自报 rev ＋ 时刻 ＋ 两份日志的 sha256），两份 `.log` 仍是 `mtime_only`（`.gitignore:47` 全局忽略 `*.log` ⇒ 日志永不入库，等级只能靠取证件升）⇒ 对外可写「当期重算 ＋ 入库取证件在位」，**仍不可写「门禁通过」**。🔻 **10-05 第 11 轮（T-34）当期重算**：两把输入换成 `772eba9` 干净树跑的
`_full_pytest_1004_rT34b.log`（sha256 `7cdc916b…`，离线 **2,389 passed / 0 skipped**）＋ `_integration_pytest_1004_rT34b.log`
（一次性库 `ecom_t34it_r11`，**107 passed**，跑完 DROP、残渣尺 `datname like 'ecom%'` = 2 = 共享 `ecom` ＋ 非本窗的 `ecom_u123_probe`）
⇒ 合并 **2,496**、红 **0**、判定仍 **PASS**；全表 **PASS 1/8**（G-2／G-5／G-7 FAIL、G-3／G-4 PARTIAL、G-6／G-8 UNVERIFIED）。
取证件重发为 rev `772eba9`／dirty **False**／411 笔，门禁报告 `eval_metrics.json` 自报 rev `005d691`／dirty **False**；
**两遍重算的递归 diff = 3 条**（只差 `meta.git.dirty`／`meta.generated_at`／`gate_provenance.report_git.dirty`）⇒ 数字可复现。
器件侧新增三条**自描述**（QA ④a／④b，判据谓词一字未动）：`input_stamps`（两槽路径＋sha256＋有没有走默认路径）／
`merge_skipped`／`overlap_suspected` ＋ `_p0_notes()` 的对应 caveat；
QA 的四态探针现读 **态①②④ 复现、态③ = FAIL ＝ want**（该件 rc=1 只因其 `now` 仍是修前基准 —— 探针自己留了「届时重取基准并具名订正」）。🔻 **10-05 第 13 轮（T-36，零额度）当期重算**：两把输入换成干净树 `a688473` 跑的
`_full_pytest_1005_rT36.log`（sha256 `364d8ab5…`，**2,392 passed／0 failed／1 warning／rc 0**）＋ `_integration_pytest_1005_rT36.log`（sha256 `176eb1bc…`，一次性库 `ecom_t36_it` 迁移到 `0005`／**107 passed**／跑完 DROP、残渣尺 `datname like 'ecom%'` = **2**）
⇒ 合并 **2,499**、红 **0**、判定仍 **PASS**、**全表仍 PASS 1/8**（同词：G-2／G-5／G-7 FAIL、G-3／G-4 PARTIAL、G-6／G-8 UNVERIFIED）；离线比第 11／12 轮的 2,389 **＋3** = 本轮新落号 `U-137` 的三条契约臂。两遍重算（仓库外 `--json-out`＋`--md-out`）递归 diff **判定量 = 0**、唯一差 `meta.generated_at` ⇒ 入库件 `9f183e1` 自报 `rev a688473`／`dirty false`。**仍不得写"门禁通过"** 🔻 **第 17 轮（T-41 C；QA 第 20 轮 G3 ＋ 本窗独立复算坐实）新增一条引用规矩（判据措辞一字未动）**：本格的**判定输入是那两把 `.log`，而 `.log` 全被 `.gitignore:47` 忽略 ⇒ 未跟踪**（现测 = `git ls-files backend/reports/w8/_r16_offline_cleantree.log` 给 **0 行** ＋ `git check-ignore -v` 指到 **`.gitignore:47:*.log`**）⇒ 把整树 `git archive` 到仓库外、只带 `gate_inputs_p0_summary.json` 去重算 ⇒ **G-1 从 `PASS` 掉成 `NOT_AVAILABLE`**（counts = **PASS 0／FAIL 3／PARTIAL 2／UNVERIFIED 2／NOT_AVAILABLE 1**，其余七格**逐词相同**；本窗现测 `2026-10-06T10:3xZ`，副本在 `E:/tmp_qoder/r17/head_tree`）。⇒ **复算 G-1 必须连那两把日志一起在场**；手上只有 p0-summary 时，本格只可引到 **`self_reported`** 那一格，🚫 **不得声称"异地可复算／拿仓库就能重跑 G-1"**。判定面（日志）与取证面（入库件）是两件事 ⇒ 同一规矩已落 `docs/07 §16.5`（v1.7.24 第三条）。**仍不得写"门禁通过"** |
| G-2 结构 Easy × 语义低 ≥95% | ≥95% | easy×low **0/10 = 0.0%**（🔻 10-04 00:47 第二批真打重算；数值未变、**成因已换**） | 十条现在整整齐齐走到 `intent>link>plan>refuse_out`（10/10 出口理由 `no_data_asset`）⇒ 红点**从"理解阶段"移到了"计划层的指标面"**（§9 那条 P1 判据侧缺口）。🔻 第一次真打那版（9 条澄清 ＋ 1 条拒答、匣带原文 `reason_code=unmapped_entity`、提示语"「T_A」无法映射到任何已登记实体"）保留：那是租户码自指被当未映射实体的形状，载荷说明落地后不再出现；τ 未校准污染 L4 判据（R-19） |
| G-3 危险 SQL 放行 = 0 | 0 | 放行 0 / 覆盖 48（应拦 50） | 2 条成本闸门用例沙箱无 EXPLAIN ⇒ gate3 恒 SKIPPED |
| G-4 跨租户泄露 = 0 | 0 | 跨租户行 0 | **评测主链路走 SQLite TEMP VIEW**，"应用运行时经 PG 执行并设好 `app.tenant_id`" 那一跳未测；且 PG 并行/串行不等值（占位符 GUC 不随 worker 传值） |
| G-5 拒答 ≥95%、误拒 ≤5% | ≥95% / ≤5% | 该拒则拒 **19/24 = 79.2%**（未变）；误拒 **63/124 = 50.8%**（🔻 10-04 00:47 第二批真打；第一次 43/124 = 34.7%，更早已往 3/5=60% 与 4/12=33.3% 是小样本） | 🔴 **涨了 20 点，但这不是新缺陷**：63 条 `execute→refuse` 逐条看，出口理由 **100% 是 `no_data_asset`**、最后节点 **100% 是 `plan`**（不是 intent、不是闸门）⇒ 是同一批题被从"澄清"推进了"拒答"（G-5 罚后者、不罚前者）。按金标投影拆：**34 条 `COUNT` 形态 ＋ 29 条未声明的列级聚合**，而语义包只有 9 个 `metrics` ⇒ 天花板在**考卷与考纲不同源**那条判据缺口上（§9）；闸门自伤修完后 43 条里已无 `GATE_AST_REJECTED`。τ 未校准 |
| G-6 P95 ≤8s | ≤8s | P95 7,268 ms | 准入样本 5 < `MIN_ADMITTED_FOR_P95=20`；回执该场景 0 条真正完成 ⇒ **不可判达标**。⚠️ 另加一条不可引用的理由：10-04 00:5x–01:2x 本机同时在跑 pytest／`docker build`／回放 ⇒ **该时段的活体延迟被本地负载污染**，那一小时内浏览器单问的 8.5s／15s 超时都不许当 G-6 证据 |
| G-7 口径一致 ≥95% | ≥95% | 一致 1/13=7.7%，不可归因差异 0 | 本项目**无外部 BI 权威值**可引，比对基准只能降级为"内部口径一致性" |
| G-8 澄清率 ≤15% 且澄清后一次成功 ≥80% | 两条同时 | 澄清率 **30/166 = 18.1%**（🔻 10-04 00:47 第二批真打；第一次 54/166 = 32.5%，更早期 9/20=45%），一次成功 0% | 后半句**结构上不可测**：跑批器**没有** "澄清→补答→再走一次" 的第二轮回路 ⇒ 整条判 UNVERIFIED（既非 FAIL 也非 PASS）。⚠️ 左半虽然从 32.5% 降到 18.1%、距 ≤15% 只差 3.1 点，**也不得读成"接近达标"**：降下来的那 24 条是搬去 `refuse` 了（见上一格），不是搬去"答对" |

**表 A：八格逐格的 数／面／谓词／分母／粒度**（对外引用**必须整行带走**；谓词与阈值的当期实现 = `eval/gates.py`）

| 格 | 判定 | 数 | 谓词（判据摘要） | 面（这份数从哪件产物来） | 分母 | 粒度 |
|---|---|---|---|---|---|---|
| G-1 | PASS | 红 **0** 条（断言失败 0／环境未备 0，两列各自现算）；规模 离线 **2,347** ＋ 集成 **107**（合树对照 **2,454**） | `red_total = failed + errors == 0` 且 `integration_ran` | 当期树的两把日志：`_full_pytest_1004_rT30.log`（离线面，**未给任何集成 DSN**）＋ `_integration_pytest_1004_rT30.log`（集成面 `-v`） | 被收集并执行的用例 **2,454** 条（skipped 0；分层 unit 1,422／contract 493／eval 408／integration 107／graph_snapshot 13／redteam 11） | 用例条 🔻 **第 10 轮整行换新（引用请连这半句一起带走）**：数 = 红 **0** 条（断言失败 0／环境未备 0，两列各自现算）＋ 规模 离线 **2,359** ＋ 集成 **107**；面 = `_full_pytest_1004_rT32.log`（离线面，**未给任何集成 DSN**）＋ `_integration_pytest_1004_rT32.log`（集成面 `-v`，一次性库 `ecom_t32_it` 跑完即 DROP）＋ 入库取证件 `backend/reports/w8/gate_inputs_p0_summary.json`；谓词不变 = `red_total = failed + errors == 0` 且 `integration_ran`；分母 = 被收集并执行 **2,466** 条用例（skipped 0）；粒度 = 用例条 |
| G-2 | FAIL | easy×low **0／10 = 0.0%** | 该格 `pass_rate ≥ 0.95` | `eval/results_v1.json`（冻结集第二批全量真打，166 条 records）的分层网格 easy×low 格 | 该格用例 **10** 条 | 用例（case） |
| G-3 | PARTIAL | 放行 **0**／覆盖 **48** | `leaked == 0` 且 `checked ≥ expect_block` | `backend/reports/w6/redteam_results.json`（红队矩阵产物，total 66 条） | 应拦 **50** 条（差的 2 条 = 沙箱无 EXPLAIN ⇒ gate3 恒 SKIPPED 的成本闸门用例） | 用例 |
| G-4 | PARTIAL | 跨租户行 **0**；PG RLS 在**评测链路**上未验证（策略本身在 PG 上实测在位：6 条策略／2,023,933 行事实数据） | `leaked == 0` 且 `pg_rls_verified`（评测侧恒 False ⇒ 只能 PARTIAL） | 红队产物里的 RT-XT 子集 ＋ `backend/reports/w6/_probe_pg_real.json` | RT-XT **3** 条用例 | 用例 |
| G-5 | FAIL | 该拒则拒 **19／24 = 79.2%**；误拒 **63／124 = 50.8%** | `拒答准确率 ≥ 0.95` 且 `误拒 ≤ 0.05`（两类错误分开统计，§C.4.4） | 同 `eval/results_v1.json` 的拒答面 | 该拒集 **24**／可答集 **124** | 用例 |
| G-6 | UNVERIFIED | P95 **7,268 ms**（回执里 4 个场景各带 p95、判定取最大） | 全请求 P95 ≤ **8,000 ms**；分母口径未标注 ⇒ **不判 PASS** | `deploy/loadtest/receipt.json`（schema `w7.loadtest.receipt/1`） | 准入样本 **5** 条 < `MIN_ADMITTED_FOR_P95 = 20`；⚠️ 覆盖面 **4／5 场景**（场景数定义在 `docs/07 §16.5:3161` = 5 条） | 请求 |
| G-7 | FAIL | 一致 **1／13 = 7.7%**；不可归因差异 **0** | `一致率 ≥ 0.95` 且 `unattributed == 0` | `backend/reports/w6/probe_metric_values.json`（§C.4.3 比对；基准 = 语义包直接实现、**不是外部 BI 权威值**） | 可比对指标 **13** 项 | 指标比对项 |
| G-8 | UNVERIFIED | 澄清率 **30／166 = 18.1%**；澄清后一次成功 **0.0%** | `澄清率 ≤ 0.15` 且 `澄清后一次成功率 ≥ 0.80`；本批次**无第二轮回路** ⇒ 后半句不可测、整条不判 FAIL | 同 `eval/results_v1.json` 全量 166 条 | 分母 **166** requests；后半句的分子分母 = clarified **30** 条 | 会话轮（run） |

**表 B：八格逐格的 时刻／HEAD／取证等级／复算命令**（复算**全部零额度**，cwd = 仓库根，逐格一行）

| 格 | 时刻（输入产物自报，UTC） | HEAD（输入产物自报 rev） | 取证等级 | 复算命令 |
|---|---|---|---|---|
| G-1 | 日志不自报 ⇒ `mtime_utc = 2026-10-04T10:47:49Z`（= 18:47:49 +0800） | **无自报**（`self_reported_rev = null`）⇒ 当期性靠旁证：`meta.git.rev = a84fc6f` ＋ 上面那句"未提交的代码面只有 `keys.py` 一处 docstring" | `mtime_only`。🔴 `*.log` 被 `.gitignore:47` 全局忽略 ⇒ **别的树看不到这两把日志**，只能本机按下面命令重跑（尺：`git check-ignore -v backend/reports/w6/_full_pytest_1004_rT30.log`） | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-1', pytest_log='backend/reports/w6/_full_pytest_1004_rT30.log', integration_log='backend/reports/w6/_integration_pytest_1004_rT30.log'))"` 🔻 **第 10 轮换输入后的四件**：时刻 = 取证件自报 `2026-10-04T12:44:25+00:00`（两份 `.log` 仍只有 mtime：`12:36:33Z`／`12:38:52Z`）；HEAD = 取证件自报 `git_rev = e900105` ＋ `commit_count = 405` ＋ `git_dirty = true`（脏面 = 报告件与取证件本身，被测代码面 0 改动）；等级 = 三件里第三件 **`self_reported`**、前两件 `mtime_only`；复算 = 取证行那条 `recompute_gate('G-1', pytest_log=…, integration_log=…, p0_summary_path=…)`（零额度）；日志身份另给 sha256 前 12 位：离线 `7e81f22a6145`／集成 `b54aa36a9f88`（日志不入库 ⇒ sha256 是唯一能跨机核验的身份） |
| G-2 | 产物自报 `2026-10-03T16:29:35Z` | 产物自报 **`b97920d`**（`dirty = true`） | `self_reported`（八格里最强的一档）；🔴 但它**不属于当期构建 `a84fc6f`** ⇒ 引这行必须同框带 `b97920d` | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-2', results_path='eval/results_v1.json'))"` |
| G-3 | 产物自报 `2026-10-03T05:11:35Z` | 产物自报 **`22e69d3`** | `self_reported`；同上，非当期构建 | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-3', redteam_path='backend/reports/w6/redteam_results.json'))"` |
| G-4 | 红队件自报 `2026-10-03T05:11:35Z`；PG 探针件 **只有 mtime** `2026-09-28T10:28:24Z` | `22e69d3`／探针件 **无自报** | `self_reported` ＋ `mtime_only` 两件同格 ⇒ 这一格的等级取**较低**那件 | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-4', redteam_path='backend/reports/w6/redteam_results.json', pg_probe_path='backend/reports/w6/_probe_pg_real.json'))"` |
| G-5 | 同 G-2：`2026-10-03T16:29:35Z` | `b97920d` | `self_reported`；非当期构建 | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-5', results_path='eval/results_v1.json'))"` |
| G-6 | 回执自报时刻 `2026-09-19T05:27:26Z`（**只有时刻、没有 rev**） | **无自报** | `self_reported_at_only` ⇒ 能定位"哪一次"，不能定位"哪棵树" | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-6', loadtest_receipt='deploy/loadtest/receipt.json'))"` |
| G-7 | **只有 mtime** `2026-09-18T17:22:48Z`（八格里最老的一件） | **无自报** | `mtime_only` ⇒ 这一格今天仍然**不能**读成"当期口径已验证" | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-7', metric_values_path='backend/reports/w6/probe_metric_values.json'))"` |
| G-8 | 同 G-2／G-5：`2026-10-03T16:29:35Z` | `b97920d` | `self_reported`；非当期构建 | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys;sys.path[:0]=['eval','.'];import reporter as r;print(r.recompute_gate('G-8', results_path='eval/results_v1.json'))"` |

🔴 **取证等级这一维本轮没能动，也不该由本窗动**：八格里 **5 格的输入产物 `self_reported_rev = null`**（G-1 的两把日志、G-4 的 PG 探针件、G-6 的回执、G-7 的比对件）⇒ 等级停在 `mtime_only`／`self_reported_at_only`。
修它 = 给 `reporter.parse_pytest_summary()` 与各探针件加自报 `git_rev`＋`git_dirty` 字段 ⇒ 动的是**唯一装配口**（判据面）且要重录七件产物 ⇒ 本窗把它登记成 **`T-11②` 的第二实例**、不自裁。
🔻 与 QA 起点读数的对表：来件说"8 格输入里 `self_reported_rev` 为 null 共 5 格、最老 `mtime_utc` 落在 09-18"——本轮重算后**这一维一格未动**（仍是 5 格 null、最老仍是 09-18 的 G-7 件），变的只有 G-1 那两把日志的**内容**（旧 `079916d`＋dirty ⇒ 新 `a84fc6f`）。

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

🔴 **10-04 18:3x–19:0x 第 9 轮（QA 第 6 轮派单：主单 T-30 当期门禁重算 ＋ 顺带 T-31 审计三格；零额度、零跑批、未动共享栈、未连共享库写面）**：
① **八格在当期树上重算并落盘**（`eval_metrics.json` ＋ 报告 md，`meta.git = {rev: a84fc6f, dirty: true}`）⇒ 判定集合与上一份**逐格同词**（`PASS 1／FAIL 3／UNVERIFIED 2／PARTIAL 2／NOT_AVAILABLE 0`）。
这一句不只是结论，也是**报警器**：本轮我确实换了 G-1 的输入而词集没变 ⇒ 说明上一份的 G-1 本来就是 PASS（红 0），本轮动作是把它的**输入当期性**从 `079916d`＋dirty 抬到 `a84fc6f`。
② **G-1 缺的那一格"集成已跑"是本轮补上的**：一次性库 `ecom_t30_it`（建 → alembic 到 `0005` → 跑 107 条 → **当场 DROP**），
残渣尺 `datname like 'ecom%'` 跑前 = **2**（`ecom` ＋ 别窗的 `ecom_u123_probe`，后者**不是本窗造的、不擅删**）；两把日志的分层与 rc 逐条见 `backend/reports/w8/RELAY.md` §九.2。
③ **T-31：`U-129` 的审计三格已交**（件 = `backend/reports/w8/t31_three_cells.json`，只读事务 `begin`→`rollback`、零额度）。
post-fix 域（**日期代理** = run 首见晚于修法落地时刻，不是构建身份）：**格1 臂1 = 0 且臂2 = 0**（`t2_runs = 10` ⇒ 非空真）、
**格2 `ge2 = 0` 且第四件前置 `t2_routed_supp = 5`** ⇒ 记"非空真达成"（引它必带 n=5）、**格3 `ge3 = 10 ≥ 1`** 达成；⑱ 形状守卫 `shape_ok = t`（两条 g 列均 0）。
⚠️ 三条边界不许越过：全库宽窗的臂1 = **13**、⑰ 混合域行的 `ge2 = 5` 都是 **pre-fix 存量**（不是回归）；`10-04` 那一域 `t2_routed_supp = 0` ⇒ 格2 记 **`n/a__该域空真`、不记 0**；
`docs/07:1155` 的判据措辞**一字未动**。**本号是否转绿由 QA 复算裁**，本窗只交数与谓词。
④ **不占号两件已做**：`app/cache/keys.py:178` 的 `session_meta` 值清单补上 `user_id` ＋ "缺失即按会话不存在处理"那句（＋3／−1 行，整段在 docstring 里）；
九份旧窗 `reports/*/PROMPT.md`（`w2-int w3-int w3a w3b w3c w4 w5 w6 w7`）各加"本席位已停用"横幅（尺 = `awk 'NR==3 && /停用/' <件> | wc -l` ⇒ 十份现读各 1，含上一轮的 `arch`）。
⑤ 🔴 **对外仍然受限的三句**：`PASS 1/8` ⇒ 不写"门禁通过"；`U-131` ⇒ 只写"已结案"、不写"跨用户隔离已达成"；
G-6 那一格除原有"分母口径未标注 ＋ 0 条真正完成"外，**再加一条覆盖面**（回执 4 场景 vs `§16.5:3161` 定义 5 场景）。
本轮**零 LLM 出站**：G-2／G-5／G-8 的数要换必须再打一次全量（≈¥0.39），按派单不做 ⇒ 这三格是"当期判定词 ＋ 旧构建的数"，引用时两者都要带。
🔻 **同轮补记（19:0x，落笔自曝）**：我第一次重算用的是**系统 `python`**（Anaconda 那份 `pydantic` v1）⇒ `reporter.py` 在 `tau_facts()` 里 `ImportError: cannot import name 'field_validator'`、
`eval_metrics.json` **一个字没被写**（我拿旧内容的 rev `079916d` 当"重算结果"看了 30 秒才发现），而那次调用的 rc 因为接了 `| tail` 打成 **0** ⇒ 本项目老坑"管道吞退出码"第三次在我自己身上复现。
正解 = `cd backend && ../.venv/Scripts/python.exe ../eval/reporter.py …`（rc 单独取，不接管道）。

🔴 **10-04 20:2x–20:5x 第 10 轮（QA 第 7 轮派单：主单 T-33 ＝ `U-129` 结案缺的那条 `U-130` 对账量；顺带 T-32 修法 ＋ gate_inputs 入库件；零额度、零 LLM 出站、未重建镜像）**：
① **T-33 的数已交、判词不写**（件 = `backend/reports/w8/t33_u130_coupling.py` ＋ 同名 JSON）。两面分列、不得并读（`07 §16.5:3164` v1.7.18 的原话）：**面 R（回执／request 粒度）** = 带 `admission.terminal` 的入库回执 7 份逐格对表，差合计 **4**，全部落在 A 档那一格（`terminal 99 − 段1 行 95`），且这 4 条在落库面上**独立复算**也是零行、并与 `deploy/loadtest/r20_internal_attribution.txt:23-26` 那 4 条 `graph_run_failed` **集合全等** ⇒ 归 `U-129` 的崩臂（缺陷类 X1），**不算豁免**；其余 6 格差 0。**面 W（落库面／run 粒度）** = 全库 `gap_down`（写了终态却无段1 行）= **0**，修法后作用域**非空**（`runs = 30`、`turn≥2 = 10`）⇒ 那个 0 有读点、不是空真；反向 `gap_up`（有段1 行却没写终态）= **48**，逐条 `turn≥2` 且全部早于修法时刻 ⇒ 与 `U-129` 修法前形状同形。
② 🔴 **面 W 的失明必须一起引**：崩臂连终态通道都没写 ⇒ 它在面 W 的分子与减数里**都不在场**，所以「`gap_down = 0`」在这一面**不等于账平了**；能数出崩臂的只有面 R 或签名 `n_audit = 0 ∧ turn≥2`（全库 13 条 = 09-28 的 8 ＋ 09-29 的 5，其中 5 条被路由进 `audit_supp` ⇒ 与 ⑰ 登记的 pre-fix 基线 5 对上）。
③ **豁免集合按类别逐条具名**（X1 崩臂／X2 段1 写库失败 fail-closed＝决策表 G1／X3 未进图的 429·409＝分母纪律而非豁免／X4 断流取消＝反方向、进 `gap_up`／X5 优雅停服由 ASGI 注入终止帧＝契约未具名的豁免候选／X6 `recursion_limit` 超限：`07:2879` 的 G4 行要求审计 ✅ 而代码走 X1 那条 `except Exception` ⇒ 口径冲突、上呈待裁）。当期成员数：X2／X5／X6 均**面上无样本**（要夹具才能出现，本窗零额度未造）；设计豁免在差里的占比 = **0**（差 4 全是缺陷类）。`U-129` 是否转绿**由 QA 按这条量裁**，本窗不写「已修／已结案」。
④ **T-32 见上表 G-1 那三格**（修法 ＋ 两态反证 ＋ 等级升到 `self_reported`），顺带把第 9 轮那句「2,454 = 2,347＋107 ⇒ 证合并没吞红」就地退回改写（🔻 原文不删）。
⑤ **可复现自证**：同一套命令在带改动的工作树跑一遍（rev `1a2e474`／dirty）、在已提交的干净树上再跑一遍（rev `e900105`／dirty）⇒ 两份产物的递归 diff 只允许差在 `meta.*` 与取证件自报面那几格（本轮输入日志与第 9 轮不同，所以 G-1 的规模数会变，这条变化本身在 ②③ 里有解释）。零额度自证：`app.cost_ledger` 全程 **1,674 行／¥2.753794／max 09:16:55Z** 与开工值逐位相同；所有只读探针外层包 `begin; … rollback;`；一次性库 `ecom_t32_it` 跑完当场 DROP，残渣尺 `datname like 'ecom%'` 跑前跑后都是 2（`ecom` ＋ 别窗的 `ecom_u123_probe`，不删）。🔻 **20:5x 实测收口（上面那句从叙述变成实测）**：同一套命令共跑**三遍**——第一遍在带改动的工作树（T-33 件自报 rev `1a2e474`／dirty、G-1 取证件自报 `e900105`／dirty），第二、三遍在**已提交的干净树**上（自报 rev `4566e84`→`ce1dec4`、dirty=False；报告 `eval_metrics.json` 自报 `d93db8f`／dirty=False）⇒ 递归叶子 diff：T-33 件 **16 条**（第二遍对第一遍）＋ **12 条**（第三遍对第二遍）、G-1 取证件 **4 条**、`eval_metrics.json` **10 条**，**全部落在取数时刻／rev 三面／由时刻派生的那一句「静默前置」倍数**上；判定量（八格 verdict 与 `PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2` 的计数、`gap_down`／`gap_up`／各 cohort 行、shape guard、台账、残渣尺）**逐位相同**。唯一一处与时间无关的差异 = 取证件的 `tracked_in_git` 由**否转是**（连带 `gate_provenance.gaps.artifacts_not_tracked_in_git` 从 3 项缩到 2 项、报告 md 的 G-1 取证行与那列清单共 5 行随之变）⇒ 那正是 ③ 里「本轮提交后为是」那句的实测。pytest 未在这几遍重跑（两份 `.log` 的 sha256 未变 ⇒ 输入没动）。
⑥ **本轮没做的事**：没重跑评测（G-2／G-5／G-8 的数要换必须再打全量 ≈¥0.39，未申请）、没造 X2／X5／X6 的夹具臂（那三类当期读数因此都是「面上无样本」而不是 0）、没补修法后的压测回执（面 R 的 7 份全在修法前 ⇒ **修法后的回执面 = `UNVERIFIED`**，补它属花费动作）、没动 `U-129`／`U-130` 的判据措辞、没取新号。

---

## 8. 这个项目的另一条主线：多窗口协同的工程机制

代码之外，本仓库同时是一次"多个开发窗口（可由 AI agent 承担）在同一 `main` 上并行交付"的实践，机制本身是可复用的产出。

- **窗口划分**：W0 核心/CI、W1A 数据与冻结集、W1B 骨架、W2A–W2D 确定性核心四并发、W3A–W3C LLM 链路、
  W4 编排收口（强制单窗口）、W5 前端、W6 评测与门禁、W7 观测部署。每窗口一份 `backend/reports/wN/PROMPT.md` 开工提示词。
- **文件归属权表**（`docs/08:276-308`）：每个目录有**唯一可落笔者**。`app/core/**` 与 `cache/keys.py` 归 W0（最高冲突风险），
  `graph/**` 归 W4，`guard/**` 归 W2C，`eval/**` 执行器归 W6 而 `eval` 内容资产归 W1A……跨窗口只能"提需求"，不落别人代码。
- **取号协议**：`U-xx` 问题的唯一权威登记表在 `docs/07 §4.8`（建表起因是曾发生 7 处撞号）。规则：提新号先查表 →
  一个号只对应一件事（根因在别处须**拆号**）→ 撞车时引用面小的一方让号 → 改号必须留"原编号"行并通知引用方。
  下一可用号 = **U-138**（`docs/07 §4.8` 末段**行首**，2026-10-05 14:5x 现读 `:1081`；v1.7.8 / v1.7.9 / v1.7.10 / v1.7.11 / v1.7.12 / v1.7.13 / v1.7.14 / v1.7.15 / v1.7.16 / v1.7.17 **十轮均未取号**；**v1.7.18 一轮取两号 = `U-133` + `U-134` ⇒ 下一可用 `U-135`**；**v1.7.19 一轮取一号 = `U-135`（W8，X6 = `recursion_limit` 超限不写审计行）⇒ 下一可用 `U-136`**；**v1.7.20 一轮取一号 = `U-136`（W8，401 令牌过期时前端错误卡编号为空 ⇒ 立案，两条零额度判据）⇒ 下一可用 `U-137`**；**v1.7.21 一轮取一号 = `U-137`（W8，闸门 R10 不认 CTE 侧 ⇒ 产品主形态被报成越权；判据已裁、实现未落地）⇒ 下一可用 `U-138`**）。⚠️ **本行只是快照**：本项目已因"抄表取号"撞号 4 次，取号前必须读盘 + `git log --all --grep` 双向查（⚠️ 本机 `.git/refs/remotes/origin/` 目录缺失 ⇒ `git log origin/main..HEAD` **直接 fatal**，判推送状态只认 `git ls-remote origin main`）。
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
- 🔴 **401 令牌过期时用户拿不到错误码（P1，编号 `U-136`；🔻 2026-10-05 13:0x +0800 本窗立案 @ HEAD `3c37c79`，状态 = 修法已落地、待验收窗复算）**：
  后端信封本来就把 `code = AUTH_FAILED` 给了出去（10-05 04:32:05Z 活体现测 `POST /api/v1/query` 回 401，`{code, message, detail, suggestions, trace_id, server_time}`，其中 `trace_id = null`），
  但前端 `frontend/src/api/queryStream.ts` 在非 2xx 支路上把它压成 `new Error('HTTP 401')` ⇒ 错误卡渲染成「错误编号：（空）」。
  形状上是 `U-131`「错误不可区分」的**镜像**：该给的码没给；401 的唯一出路是"重新登录"，编号为空 ⇒ 用户与答辩都读不出该做什么。
  🚫 **不得**为此把 401 改成 403／500（状态码语义 = `附录A` A.0.4 ＋ §14.2 H 组），**不得**把令牌写进任何文案或日志。
  结案判据两条（已钉零额度夹具 `queryStream.test.ts` 4 臂 ＋ `ErrorCard.test.tsx` 3 臂）：① 流侧 `code`／`status`／`traceId` 原样透传；② 渲染侧编号非空（缺 `trace_id` 时退回 `code`）且 401 走「请重新登录」文案。
  ⚠️ 本格只登记立案与夹具形状，**不写"已修"**：401 的浏览器真机臂在验收窗复算前不算数。
  🔻 **10-05 第 14 轮 23:5x +0800 结案落笔（依 QA 第 17 轮 `backend/reports/qa/RELAY.md:983` 的裁定句「`U-136` ⇒ 结案（转绿）」；本窗只落状态，**判据措辞一字未动**）**：判据①／② 两面现由零额度夹具钉住 = `queryStream.test.ts` 19 臂 ＋ `ErrorCard.test.tsx` 3 臂 ＋ `ChatPage.test.tsx` 3 臂（QA 于 `RELAY:976` 复跑 = 29 passed／4 files、`tsc --noEmit` rc=0；本窗 10-05 23:3x 当期复跑 = **33 passed／5 files**，增量是本轮新增的 `EvalRunsPage.test.tsx` 4 臂、与本号无关 ⇒ 不许把 33 读成 29 的订正）。真机臂本轮另有一次独立走查证据：未登录直接打开 `/semantic/metrics` ⇒ 错误卡渲染「登录已过期或令牌无效，请重新登录」＋「错误编号：`AUTH_FAILED`」，读数登记在 `backend/reports/w8/t37_a5_browser_walk.json` 的 `browser_walk.readings` 末条。 ⇒ **本格状态改为「已结案（转绿）」**，上面那句立案原话保留作历史取证。
- **`app/present/` 已落投影、仍未落图内侧**（🔻 10-05 第 11 轮）：A.9.2–A.9.4 的网格聚合在 `present/eval_report.py`，而每轮回答的 `chart_spec` 仍在 `graph/nodes/present.py`，包边界与文档表述**仍待对齐**。
- **`deploy/docker-compose.yml` 的 `worker` 服务无实现**：命令是 `python -m app.worker`，但 `backend/app/worker.py` 不存在（已核对）。
- **令牌吊销只有内存版**：`app/auth/` 自述 Redis 吊销表未落地。
- 🔴 **登录方式未裁（`D-H`）⇒ 生产形态的页面没有任何登录入口（P1，10-03 第 5 轮真机走查实测）**：
  `/login` 的主按钮只是提示"待裁决"，唯一能进去的路是"粘贴测试 token"的调试入口，而它被
  `VITE_ENABLE_DEBUG_PANEL === 'true'` 门控 ⇒ **默认生产构建打不开问答**。演示必须用带调试门的构建
  （`VITE_ENABLE_DEBUG_PANEL=true npm run build`）＋ `scripts/mint_dev_token.py` 签的令牌，三步已写进
  `deploy/runbook/README.md` §5.1。⚠️ 两个坑实测过：令牌只在内存 ⇒ **刷新页面就要重贴**；
  `--tenant-id` 必须是数据里真实存在的（`T_A`/`T_B`/`T_C`），签成 `tenant_a` 的表现是
  "五步走完、该条件下没有数据"而**不是报错**（RLS 匹配不到行），最容易误诊成闸门或模型坏了。
- 🔴 **「先聚合再连维表」这类问题被闸门当成越权拒掉（P1，编号 `U-137`；🔻 2026-10-05 14:5x +0800 @ `f05dbc2` 本窗立案，零额度）**：
  语义包的 `join_path` 认证面只认**资产对**，而 `app/guard/ast_gate.py:638-648` 把 JOIN 的左侧候选取成
  `from_.find_all(exp.Table)` 的表名 —— sqlglot 把 **CTE 引用也解析成表** ⇒ 左侧是 CTE 名 ⇒ 永不匹配认证边 ⇒ 落 `R10`，
  而 `R10` 的用户文案是「查询涉及的数据范围超出你的权限」（§7.6 把 R05/R10/R11/R13 并成一句）⇒ **不是越权，是路径未认证**。
  实测：面 R 三对六条准入里那 3 条 `GATE_AST_REJECTED` 全是这一形状（同一道题「上个月复购率最高的 10 个店铺是哪些？」），
  复算件 = `backend/reports/w8/probe_r13_gate_rejections.py`（按 `U-125` 判据④：这类 `rule_id` 归因属**离线器件**）。
  📌 裁定已落 `docs/07`（§7.2 AST-R10 行 v1.7.21 定义补句）：**「左表 / 右表」指资产，CTE 侧按其所含资产参与判定**；
  落地那天 §7.6 分组与 `rules.py` 文案必须同轮同改。⚠️ **本轮只裁方向、未改实现** ⇒ 该形状今天仍拒；
  零额度夹具 = `backend/tests/contract/test_r10_cte_join_contract.py`（3 条，含「资产直连对照必须放行」）。
- 🟠 **顶栏两个入口点了必出错误卡（P1，10-04 14:0x 真机截图取证，未修）**：`/semantic/metrics`（口径字典）与 `/eval/runs`（评测）两条前端路由**已建页面**，但它们要调的后端端点**没接线** ——
  现读（**10-04 那次取证**）`openapi.json` 的 12 条 path 里没有 `semantic`/`eval` 任何一条 ⇒ 两页都渲染出**HTTP 404 错误卡**（页面本身在、数据拿不到）。🔻 **10-05 现测 = 15 条 path**（`GET /api/v1/openapi.json` ⇒ `len(paths) = 15`；新增的三条是本轮 A.9.2／A.9.3／A.9.4 的 `admin/eval/datasets`／`admin/eval/runs`／`admin/eval/runs/{run_id}`）**且「两页必出 404」这句要拆开读，见下面的订正块**。
  证据：`deliverables/screenshots/07_page_semantic_metrics_HTTP404.png`、`08_page_eval_runs_HTTP404.png`。
  ⇒ 影响两件事：① 第 5 轮那次浏览器走查的覆盖面**只包含问答链路**，"页面打得开"当时是按问答页判的，顶栏另两个入口没人点过 ⇒ 面向人的判据要**逐入口点一遍**，不是"主链路通"；
  ② 演示与交付包里已明写"别点这两个链接"（`deliverables/ACCEPTANCE.md` §3）。⚠️ 补端点属新功能面（口径字典只读接口 ＋ 评测报告读取接口），本窗**未做**，登记待排。
  🔻 **订正（10-05 14:5x +0800 @ `f05dbc2`，QA 第 16 轮 13.7 A 点名「数与形状都漂了」；上面的原句保留作历史取证）**：
  ① **数量**：`openapi.json` 现读 **15 条 path**（尺：`python -c "import json,urllib.request;print(len(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/openapi.json'))['paths']))"`）。
  ② **形状**：`/eval/runs` 那一页现在有**两条支路**，结局不同 —— ②a **列表支**打 `GET /api/v1/admin/eval/runs`（已接线，
  `admin_eval.py` 三条 `@router.get` 之一）：对 `platform_admin` 是 **200**（验收窗 21 臂实测 `grid.cells=12`／`gate.items=8`），
  对 **analyst 是 403 `FORBIDDEN_SCOPE`**（角色门禁 fail-closed）；②b **发起评测支**打 `POST /api/v1/admin/eval/run`
  —— **路由不存在**（`ls backend/app/api/routers/` = `admin_eval / clarify / feedback / health / query / session`，无 `semantic`、
  `admin_eval.py` 内 **0** 条 `@router.post`）⇒ 这一支必 404。
  ③ `/semantic/metrics` 与 `/semantic/assets` 两页**仍是 404**（前端调用点 `SemanticPage.tsx:124`／`:156`）。
  ⇒ 所以这句要写成：**"评测页列表支按角色给 200／403、发起支必 404；口径字典两页必 404"**，不得再写"两页都必出 404 卡"。
  ④ ⚠️ 演示默认令牌的角色决定观众看到 200 还是 403 ⇒ 交付包的措辞已同步（`deliverables/ACCEPTANCE.md` §3）。
  ⑤ 页面**渲染**层面的读数本轮未重跑（只取 HTTP 面与代码面）⇒ "错误卡长什么样"记 **UNVERIFIED**，归真机那一臂。
  🔻 **订正二（10-05 第 14 轮 23:3x +0800 @ HEAD `0c69d56`，T-37 A1／A2／A3 落地 ＋ A5 真机走查；上面两条原句保留作历史取证）**：
  ① **数量**：`openapi.json` 现读 **19 条 path**（活体尺 = `curl -s http://127.0.0.1:8000/api/v1/openapi.json` 后数 `paths`；
  代码面同尺 = 离线 `create_app().openapi()` 也 = 19 ⇒ 这一格两个面**第一次对上**，靠的是本轮 `docker build` ＋
  `--force-recreate api`：重建**前**活体是 **15**（镜像落后一笔），重建后才是 19 ⇒ 引"19"必须连重建时刻一起引）。
  新增四条逐个点名：`GET /api/v1/semantic/metrics`、`GET /api/v1/semantic/assets`、`POST /api/v1/admin/eval/run`、
  `GET /api/v1/admin/audit`。容器身份三件照旧在位：`/srv/app` 的 `.py` = **158**（上一读数 147）、path 集含上述四条、
  import 实证 = `app.repo.audit_read.AuditReadDAO` 可导入。
  ② **形状**：上面那句"发起支必 404；口径字典两页必 404"**作废**，改成三句 ——
  · **口径字典两页 200 且拿到真数据**：`/semantic/metrics` 活体 `total = 9`、`/semantic/assets` `total = 8`，
  前端调用点 `SemanticPage.tsx:124`／`:156` 不再落空；红线复核 = 响应 `data` 的键集只有
  `items／total／limit／offset／has_more`，**没有** `scope` 键 ⇒ 页面不可能声称"本租户口径"。
  · **评测页发起支 200，但语义是"预检"不是"发起"**：`run_id = null`、`status = "dry_run"`、`launched = false`，
  报价逐格带出处（活体：166 题、538～620 次调用、非峰 ¥0.337171～¥0.391504、保守口径 ¥0.901214、
  峰档上界 ¥0.783008、乘数 ×2.00、3 份产物 = **2 批**独立观测）；`launch_blockers` 三条在响应里点名缺什么。
  🔴 所以这一支**不得**写成"评测已发起"，也不得把报价当"本次花费"——它是从既有真打批次外推的。
  · **审计读 `GET /api/v1/admin/audit` 新增**（无 UI，`App.tsx:3` 那条"分期未落地"仍然成立）：
  `platform_admin` ⇒ 200（活体 `total = 905`，`scope.level = tenant`、`scope.tenant_id = T_A`、`source = jwt`）；
  其余角色 ⇒ 403 `FORBIDDEN_SCOPE`；无令牌 ⇒ 401；`scope=bogus`／`pii_hit=maybe` ⇒ 400 `INVALID_REQUEST`；
  未知 `dataset_id` ⇒ 404 `DATASET_NOT_FOUND`（detail 点名是哪一格）；请求体多一个键 ⇒ 400（`extra = forbid`）。
  `tenant_id`／`user_id` **不是查询参数**的活体反证 = 带 `?tenant_id=T_C` 仍回 `scope.tenant_id = T_A` 且 `items` 里只有 `T_A`。
  身份 GUC 三键**同一条语句**注入（响应自报 `identity_guc.statement_count = 1`／`is_local = true`／`reset_issued = false`）。
  🔴 **第二道保证今天不在位，而且是页面可见的事实**：响应里 `rls = {enabled: false, forced: false, policies: 0,
  second_guarantee_in_place: false}` 是**现查** `pg_class`／`pg_policies` 出来的（策略 DDL 被迁移守卫禁产，需裁定，见 `backend/reports/w8/RELAY.md` §十四 那条"需上呈"）；
  跨租户视角另给一次读数：`scope=cross_tenant` ⇒ `total = 907`（比租户视角多 2 行 ⇒ "切得开"是被数出来的，不是被说出来的）。
  ③ **迁移数 5 → 6**：尺 = `ls backend/app/repo/migrations/versions/*.py`（除 `__init__`）⇒ **6**，新增的是
  `0006_audit_read_grant.py`（只落 `GRANT SELECT … TO app_ro` ＋ 显式 `REVOKE` 写权限，**不落 RLS DDL**）；
  活体 `select version_num from public.alembic_version` ⇒ **0006**（本轮已对共享 `ecom` 跑过 `alembic upgrade head`；
  跑之前 `app_ro` 对两张审计表**零授权**，是现读的）。
  ④ **A5 真机走查（浏览器，不是 mock）**：登录 → 顶栏两入口逐一点开 →「指标」9 条／「数据资产」8 行、
  搜「客单价」**两遍**都是 1 条（`1 / 共 1`）→ 评测页弹窗选集、填三格、点「生成预检」面板出现，
  **同一填法再点一遍 ⇒ 面板文本逐字符相同**（两遍均 819 字符、`identical = true`）。
  截图四张入库 = `backend/reports/w8/screens/a5_*.png`；⚠️ 视口 = `531 × 559`（dpr 1.5）⇒ 窄屏下宽表横向滚动的**排版**复核仍记 **UNVERIFIED**，
  本轮取的是"数据到没到／文案对不对"这一层。
  ⑤ 🔴 **走查当场抓到一个 P1 前端缺陷并修掉**：评测弹窗里「评测集」下拉恒为"暂无数据"，而 `GET /admin/eval/datasets`
  是 **200 且两条**（DOM 尺 = `document.querySelectorAll('.ant-select-item-option').length` ⇒ 0）。
  成因 = `EvalRunsPage.tsx` 那个 effect 把**自己正在改的** `datasetsLoading` 放进了依赖数组 ⇒ 依赖一变 React 先跑上一轮 cleanup
  （`cancelled = true`）⇒ `.then`／`.catch`／`.finally` 里三个 `if (!cancelled)` **全部跳过** ⇒ 候选恒空、**连 403 的报错都被吞掉**、
  loading 永远停在 true。这形状自 `e01c198`（W5）就在树里，是 A.9.2 端点接上之后才**第一次能被看见**——
  ⇒ 印证本项目那条老教训：**"路由没接"会掩护一整类前端缺陷**。修法 = loading 不进依赖数组、两个分支各自复位；
  夹具 = `frontend/src/pages/EvalRunsPage.test.tsx`（4 臂，含"空列表也照样渲染"的对照臂与"403 不许静默"臂），
  同一件源码两态对撞：**pre-fix 3 红 1 绿 ／ post-fix 4 绿**（还原后 md5 `938469e4…` 与修后件逐字相同）。
  前端三门现测：`tsc --noEmit` rc = 0 ／ `vitest run` = **33 passed / 5 files**（上一轮 29／4）／ `eslint` rc = 0。
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

🔻 **10-06 第 19 轮（T-43 C）收口定稿：未闭清单（按现状列全；逐号现读 `docs/07 §4.8` 状态格**末句**，判据措辞一字未改）**

- **open 集 = 九枚**（🔻 **10-07 第 20 轮：QA 第 23 轮裁定 `U-127`／`U-135` 进集 ⇒ 七枚改九枚**；本段原写「七枚」= 第 19 轮按当时现状，两处现读均逐号指 `docs/07 §4.8` 状态格**原话**）：
  `U-126`（P0，槽位／几何配平 ⇒ 状态格现读「三面归属，**缺一即未结案**」＋ `redis_unavailable` 差额仍 `UNVERIFIED`）；
  `U-127`（P1，**容量不足被伪装成「没有这个数据」** ⇒ 🔻 第 20 轮进集（QA 第 23 轮裁定）；状态格**末句原话**「**升 P0 与否留待健康态复算，本轮不据污染读数改级别**」＋同格「**三侧同批、缺一即不可结案**」；🔴 措辞约束 = 它的「升 P0 触发条件」本身**不可判**（那一轮 66 条 `refuse` 里 8 条走 `node_timeout_degraded{normalize}`，但该轮被 Ollama 中断污染）⇒ 🚫 对外不许写「未触发」，只许写「不可判 ⇒ 留待健康态复算」）；
  `U-128`（P0，功能静默降级 ⇒「本号落地后**必须用同一口径实测复算一次 H**，否则判据④ 保持未结」）；
  `U-130`（P1，度量盲区 ⇒「**不得写「臂1 已归零」**」＋ 分母必须带面名）；
  `U-132`（P1，环境阻塞 ⇒ 登记为环境红、🚫 不得 skip/xfail/调大超时）；
  `U-133`／`U-134`（P1，取证面破坏性默认值／本机栈凭据 ⇒ `U-134` = 一次性治理项、暴露面 `UNVERIFIED`）；
  `U-135`（P1，豁免集合三态与停服排水 ⇒ 🔻 第 20 轮进集（QA 第 23 轮裁定）；状态格**末句原话**「…**本窗裁定：暂不转正**，转正前若出现任何 X5 样本必须先具名上呈，不得直接进豁免集合」；⚠️ 那句「暂不转正」**只管 X5 那半格**、不是本号结案 ⇒ 来件给的结案路径 = 零额度夹具可证，但闭口要动 `app/**` 那条通用 `except`（属实现面，本窗不自裁））；
  `U-138`（P1，回执分组键 ⇒ 改名 ＋ 契约已在第 16 轮落盘，**后半 = 一份带 `worker_session_depth` 的真回执**，必须出站 ⇒ 与 **T-40** 并成同一把 ⇒ 本格现状 **部分达成、不结案**）。
- **判据／口径侧三处缺口（不占号、在案）**：① **金标口径缺口**（GMV／订单量的语义包定义与金标不一致，`07 §16.1` 取 `complete` 最保守口径）；② **冻结集期望 ≠ 语义包指标面** = 124 条 execute 用例里 **63 条（50.8%）**要的指标在语义包里根本不存在 ⇒ 计划层按契约拒答是**正确行为**、是考卷把它标成了「该答」（已作为判据侧缺口上呈，未改考卷、未改判据）；③ **第二道 RLS 保证推后**（四条验收约束在案；PG 面 6 条策略实测存在且有效，但评测主链路走 SQLite TEMP VIEW ⇒ `G-4` 仍 PARTIAL）。
- ⚠️ **本窗现读补两枚「带未闭词」的号（不擅自并进 open 集，交回 QA 裁定）**：`U-127` 状态格现读「**三侧同批、缺一即不可结案**」＋「升 P0 与否留待健康态复算」；`U-135` 状态格现读「**本窗裁定：暂不转正**」（转正 = 在决策表加行 = 契约变更）。⇒ 按盘上措辞这两格**不是已闭**，欠的是**裁定／复算**、不是本窗的活儿。 🔻 **第 20 轮按 QA 第 23 轮裁定收口这两枚**：二者**已进 open 集**（上面那段「七枚」已改「九枚」），本行保留作取证。措辞约束两条 = ① `U-127` 的「升 P0 触发条件」= **不可判**（污染读数），🚫 对外不许写「未触发」——不可判本身就是该号的症状；② `U-135` 盘上那句「暂不转正」**只管 X5 那半格**、不是本号结案 ⇒ 本号要闭得动 `app/**` 那条通用 `except`（实现面，本窗不自裁、不占号）。
- **已裁四格（只写裁定 ＋ 限定语，🚫 不写光句）**：`U-129` = 🟢 **转绿**（QA 第 20 轮裁定）＋ 三条限定语必须同框：**(a)** 当期性按**两链**报（链一 容器 ⟷ 工作树字节 ＝ 尺量到的；链二 工作树 ⟷ HEAD ＝ `rev + dirty`；🚫 不写「三面相等」、🚫 不用 `audit_log` 日期窗追认当期）、**(b)** 该行 v1.7.10 那句照抄 = 转绿**作废三批历史读数**（W7 侧 `ok` 率／H／轮次分布须重测后才可引用）、**(c)** 镜像未重建 ⇒ 不得写「活体面已带本轮改动」（本轮靶子格就是它的实测）；`U-136` = 🟢 **已结案（转绿）**；`U-137` = 🟢 **已结案** ＋ 同格写明**不覆盖**什么（随交件实测：改判 1 条、放行 0 条、题面 2 个；演示那句仍卡 **R06 列面**）；`U-139` = 🟢 **已修并结案**（W8 第 18 轮，量具自证）⇒「当轮取号当轮结案」的适用范围已落 `07 §4.8` 规则 **④**。
- **门禁句（不变）**：八格 = **PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2** ⇒ 对外 **PASS 1/8**，🚫 不得写「门禁通过」；`G-6` 仍不可引用（9 < 样本下限 20）。
- 🔴 **靶子那格（第 19 轮必须写实）**：三个候选面**都不含今天的 `app/guard/**`**——
| 候选面 | 现读 id 与时刻（本轮 `docker image inspect` ／ `docker exec … md5sum`，零额度） | 含 `U-137` 落地（笔 `4704966`／2026-10-06T15:19:04 ＋0800 = 07:19Z）吗 |
|---|---|---|
| `commerceql-api:latest` ＝ 共享栈容器 `commerceql-api-1`（本轮唯一在场的容器面） | image `sha256:ca34ea791a81…`、镜像 `Created = 2026-10-05T15:19:25Z`；**容器** `Created = 2026-10-05T15:19:26Z`（两格只差一秒、不可互换） | 🔴 **实测不含**：容器内 `ast_gate.py` md5 = `cf698983db685b21d46e9accbe9da7c5` ⟂ 工作树／HEAD 的 `a9443bff14973301c27d16ef386d3c3f` ⇒ 链一 DIFF、链二 SAME |
| `w7load-api:latest` ＝ 原被测构建的镜像 | image `sha256:4adbcfc2e8f6…`、镜像 `Created = 2026-10-04T16:06:22Z` | ⚠️ **按时刻推断不含**（镜像早于落地笔约 15 小时），但本轮**没起容器**（派单禁容器动作）⇒ 这一格只能记 `UNVERIFIED-面`，🚫 不许对它下 md5 断言 |
| `w7load-api` 容器 | **不在 `docker ps -a`**（只剩 6 天前的 `w7load-api_pre0930r11_bak`，`Exited (255)`） | ❌ 无面可取（第 18 轮已具名上呈） |

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
