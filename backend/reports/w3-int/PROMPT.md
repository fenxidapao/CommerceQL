# 【窗口提示词 · 阶段 3 收口窗口（W3-INT）】

> 本文件沿用 `reports/w2-int/PROMPT.md` 的收口模板（定位 → 纪律 → 现状 → 任务 → 转述 → 交付）。
> 产出：W3B 窗口（受用户指令）｜日期：2026-09-17｜基准 commit：**`672fdf4`**（远端 = 本地）。
> 阶段 3 = 三个开发窗口：**W3A**（`app/llm/**`）· **W3B**（`app/planner/**`）· **W3C**（`app/binding/**`），均已交付并 push。
> 收口窗口的定位永远不变：**汇总 / 核验 / 接线 / 全量门禁 / 裁决上呈 / 交付 —— 不做功能开发。**
> 交付目录：`backend/reports/w3-int/`（你的 DELIVERY.md / RELAY.md 落这里）。

---

你是 CommerceQL「阶段 3 收口窗口」（**W3-INT**）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 `main`，远程 `fenxidapao/CommerceQL`。

## 一、你的定位

阶段 3 的三个开发窗口已完成交付并各自落库。你不写功能代码；你负责把三份交付**收成一个整体**：收集转述（§七已替你汇总，但**你必须逐条核验**）、核验"已落地"声称、判断接线面、跑全量门禁、把裁决请求**合并成单一文档**上呈架构。设立你的原因不变：点对点转述是 O(n²) 条边；单窗口各自绿 ≠ 聚合绿；装配根与全量回归需要一个 owner。

**阶段 3 的特殊性（与阶段 2 收口不同，先说清）**：三家的**下游接线方 W4（`graph/**`+`api/**`）尚未开工**——`app/llm`、`app/planner`、`app/binding` 目前**全部零调用方**。所以本阶段"接线"大部分**天然 BLOCKED**（等 W4），你的核心产出是**总表 + 裁决上呈 + 给 W4 的一份干净开工输入**，而不是把线接完。

## 二、契约与纪律

- 契约优先级：**附录 A(02) > PRD(01) > 06 UIUX > 07 TDD(v0.9) > 08 实施计划(v1.2)**。
- 红线：不伪造实现；未接线不得报已实现；skip 必须写明缺失前置（不静默假绿）；"已落地"必须给可核对位置（文件+键/行），否则标 UNVERIFIED。
- 动手前先 `git status` + `git diff --stat` 判断是否别人在制品；同文件多处编辑**串行改 + grep 复核**。
- **不修改** `app/{llm,planner,binding}/**` 的功能代码（三包各归属其窗口）。
- 归你独占的**接线文件**：`backend/main.py`、`app/repo/startup_assertions.py`、`app/api/routers/health.py` 的探针注册段（沿用阶段 2 起的约定）。
- 提交：`feat(w3-int)` / `docs(w3-int)`，只暂存本窗口文件。
- 编号纪律：**不得自行开号**。三窗口候选见 §七-6，全部"待架构分配"（下一可用号 = `U-65`）。

## 三、现状盘点（2026-09-17 实测；动手前**复核**，上游可能已变）

| # | 事实 | 位置/证据 |
|---|---|---|
| 1 | 三窗口均已交付并 push；HEAD = `672fdf4`；提交链 = `…2766f3c(w3a docs) → 8207fe7(w3c feat) → affbf32(w3c docs) → eef444c(w3b feat) → 94f25e0(w3b docs) → 91b8bd3(w3c RELAY 补登记) → d89dc07/e582fe0(w3a 修预算) → aac3091/672fdf4(w3a 标定思考档)` | `git log` + `git ls-remote` |
| 2 | **门禁基线（Docker 起来后，W3A 实测）**：`pytest -q` → **1471 passed / 6 skipped / 0 failed / 0 errors**（67s）；`ruff check .` → All passed；`mypy app` → **102 files** clean；`lint-imports.exe` → **4 kept, 0 broken**；`python scripts/assert_importlinter.py` → DoD② 通过；`python -m app.core.enums` → 契约自检通过 | `reports/w3a/DELIVERY.md §12.6` |
| 3 | ⚠️ **Docker 未启动时全量 = 1 failed + 6 errors + 55 skipped，全在 `tests/integration/`**（PG/Redis 不可达）——**假红，不是回归**；W3A/W3B/W3C 三家都踩过并当场验证"起 Docker 后复跑即全绿" | 三家 DELIVERY |
| 4 | **6 个 skip 是既有的**（`test_retrieval_fts_pg.py` 夹具 DSN 无 DDL 权限），如实 skip，非阶段 3 引入 | `reports/w3a/DELIVERY.md §3` |
| 5 | **`graph/**`、`api/routers/**`（除 health）仍是空/占位** —— 三包零调用方，W4 未开工 | 实测 |
| 6 | **DoD 达成度**（08 §3.5）：**W3A ①–⑤ 全 ✅**（其 §12/§13 修的两个缺陷是交付期发现，不在 DoD 列）｜**W3B ②③ ✅、① 部分达成**（合并档 2 未实现 + §16.1 执行点空缺）｜**W3C ②③④ ✅、① 部分达成**（缺 `query_plan` 表结构） | 三家 DELIVERY §2 |
| 7 | 🔴 **W3B 报告有两处已被 W3A 勘误**（`normalize_intent` 5/5 是悬崖边样本，实际 0/3；`gen_sql_complex` 2/3 实为 3/3 确定性失败 + pro 档从未生效）。W3B 已落**勘误节**（`reports/w3b/DELIVERY.md §八`、`RELAY.md 末节`）。**收口引用 W3B 数据时一律以勘误节为准** | `reports/w3b/DELIVERY.md §八` |
| 8 | 报告入库惯例已漂移：`w3a/PROMPT.md` **未入库**，`w3b/`+`w3c/PROMPT.md` **已入库**（W3C `91b8bd3` 具名登记并请收口裁决） | `reports/w3c/RELAY.md §给 W3-INT-7` |

## 四、任务清单（按序执行）

1. **T0 环境自证**：**先启动 Docker Desktop**（不自启）；venv = `CommerceQL/.venv`；`git status` 判在制品；复核 §三 每一条。
2. **T1 汇总**：读三家的 `DELIVERY.md` + `RELAY.md`（**含 W3B 勘误节、W3A §12/§13 追加、W3C `91b8bd3` 追加**），合并成《阶段 3 收口总表》，分三类（§七 已给出半成品，你补齐"核验结果"列）：
   - **接线类**：给 W4 的全部装配要求（§七-3）——本阶段**全部 BLOCKED（等 W4）**，你的责任是把它整理成 W4 拿来就能用的形态；
   - **裁决类**：三窗口候选 + 收口窗口自检发现的新问题（§七-6）；
   - **债务类**：等 W1B 的两张表、等 W0 的枚举/指标/脚本修复、等 W6 的 τ 校准、W3B 合并档 2 未实现（§七-7）。
3. **T2 核验**：对三家 DELIVERY 的关键"已落地"声称**抽查可核对位置**（文件+键/行）。最低抽查集（本窗口建议，可加）：
   - W3A：`router.py` 的 `budget_s`/`hard_timeout_s`（**确认 `effective_timeout_s` 已不存在**）；`THINKING_HEADROOM_TOKENS=8192`、`GEN_SQL_COMPLEX.output_tokens_hint=1536`；`CallRecord.budget_s/over_budget`；
   - W3B：`engine.py:773`（`_report_and_raise`）与 `:627`（`repair_schema=RepairResult`）；`schemas.py:102`（`INTENT_MAP`）；170 条用例可独立复跑；
   - W3C：`four_layer._level4` 四条 `ambiguous` 路径；`calibration.assess_stability` 的 `n≥3` 硬校验；`scores.require_rerank_scores` 拒裸 `float`；`app/core/enums` 自检两基数=4。
4. **T3 接线**：预期**没有**"不依赖未裁决项"的接线项（`main.py`/`startup_assertions`/health 探针在阶段 3 无新增探针需求——若你核验后确认，就**在 DELIVERY 里如实写"本阶段无接线动作"**，不要为了"做了事"硬接）。唯一例外：若架构在收口期间裁决了候选并需要单点落地，见 §六。
5. **T4 全量门禁**（Docker 起来后跑，输出**原样**进 DELIVERY）：`pytest -q`（期望 1471 passed / 6 skipped）、`ruff check .`、`mypy app`、`lint-imports.exe`、`python scripts/assert_importlinter.py`、`python -m app.core.enums`。任何红：先定位归属窗口；你能修的修（带注入对照），修不了的写进总表转达，**不许吞**。
6. **T5 端到端验证（如实标 BLOCKED，不得绕过）**：
   - **BLOCKED（等 W4）**：SSE 全链路、降级事件到前端、`refuse` 终态、L4 双入口选择、§16.2 占位符先推；
   - **BLOCKED（等架构）**：L3+ pro 档（候选 ⑬，A/B/C 未裁）；§16.1 预算重裁（⑪⑫）；
   - **BLOCKED（等 W1B/W6）**：`binding_state`/`binding_layer` 落库（缺表）；τ 校准（`is_finalizable` 真跑前必为 `False`，这是设计使然）；
   - **可做**：三包单测独立复跑；`lint-imports` 全仓基线；`cost_ledger`/`query_plan` 的"表不存在"现状复核（`grep -rn "query_plan\|cost_ledger" app/repo/migrations/` 应零命中）。
7. **T6 裁决上呈**：把 §七-6 的候选**合并去重**成**单一文档**（注意：W3B 候选 ①② 与 W3A ⑪⑫ 同源，必须合并成一条；W3C 候选 9 与 W3C 给 W1B 的建表需求同源）。附编号占用现状，**不得替架构选方案**（pro 档 A/B/C 三方向原样呈报）。
8. **T7 交付**：`backend/reports/w3-int/{DELIVERY.md, RELAY.md}`（RELAY 含逐窗口回执 + **给 W4 的阶段 4 开工输入**）+ commit。另对 §三-8 的惯例漂移给出你的裁决执行：若判"开发者窗口 PROMPT.md 不入库"，则 `git rm --cached backend/reports/w3b/PROMPT.md backend/reports/w3c/PROMPT.md` 并把 `w3a/PROMPT.md` 一并处理，**三窗一致**；若判"都入库"，则补 `git add backend/reports/w3a/PROMPT.md`。**别让同一阶段两种惯例并存**。

## 五、必读清单（精确到章节）

1. `reports/w3a/{DELIVERY,RELAY}.md`——**含 §12（预算≠超时）与 §13（思考档标定 + 45s 上限阻断）两个追加节**，及 RELAY 的两个【追加】节（跨窗口影响）。
2. `reports/w3b/{DELIVERY,RELAY}.md`——**含 DELIVERY §八勘误节与 RELAY 末节勘误**（本文件 §三-7）。
3. `reports/w3c/{DELIVERY,RELAY}.md`——含 `91b8bd3` 追加的两条登记（PROMPT.md 惯例冲突、obs 缺两个 Counter）。
4. `reports/w2-int/{DELIVERY,RELAY}.md`——收口模板先例 + 阶段 2 遗留（U-54/55/56 裁决状态）。
5. 07 §14.2–14.3（F2/F3/refuse/降级事件语义——核验 W3A 契约用）、§16.1/§16.2（预算语义与占位符兜底——候选 ⑪⑫ 的原文依据）、§4.8（编号登记表）。
6. PRD §12.2（模型路由表——候选 ⑬ 的原文依据）、NFR-1.2/1.4。
7. `docs/08` §3.5（阶段 3 DoD 原文）、§3.6（阶段 4 = W4 的 DoD，你给它的开工输入要对齐这张表）。

## 六、边界与例外

- 三包功能代码不得落笔；W4 的 `graph/**`/`api/**` 更不能碰（未开工）。
- **唯一授权修改**：若架构窗口在收口期间裁决了某候选且方案落在三包内，你获该**单点**修改授权——必须在 DELIVERY 留改动记录 + 注入对照（注入→必红→还原→必绿，且看清红的确实是目标断言）。
- 三窗口若在收口期间继续提交：**重跑门禁**，收口报告以最新 commit 为准。
- 接口问题优先走各家 RELAY 的回执，不直接改它们的代码。

## 七、阶段 3 对其他窗口的转述（汇总自三家 RELAY —— **你逐条核验后转达/上呈，不许吞**）

> 每条标注来源窗口。核验方式：抽查其"可核对位置"；与 §七-6 裁决类有重叠的条目在上呈文档里**合并**。

### 1. §给 W0（`app/core/**`、`app/obs/**`、`scripts/**`、`pyproject.toml`）

| # | 事项 | 来源 | 可核对位置 |
|---|---|---|---|
| 1 | 🔴 `Retry-After` 仍是 2/5，应落码为 5s/30s（07 §14.4.1） | W3A | `app/core/enums.py:349-350` |
| 2 | 🔴 空字符串 API key 能过"必填"校验（建议 `min_length=1` 或 validator） | W3A | `app/core/config.py` |
| 3 | 🔴 `scripts/assert_importlinter.py` **非并发安全**：残留 `_probe_violation.py` 会让**任何窗口**的 `lint-imports` 报 BROKEN + 脚本 FATAL（粘性：清理只在 `finally`，信号杀不死；拒绝覆盖；双窗口互踩）。建议：探针名带 PID/加锁、区分临时与陈旧残留、清理对 SIGPIPE/SIGTERM 生效 | W3A §12.7 | `backend/scripts/assert_importlinter.py` |
| 4 | `obs.metrics` 缺 LLM 指标本体（建议 `llm_calls_total{task,model,degraded}` 等 7 项） | W3A | `reports/w3a/RELAY.md §给 W0-3` |
| 5 | `obs.metrics` 缺 `binding_state`/`binding_layer` 两个 Counter 本体（标签已登记、指标未建；引 07 §15.3） | W3C（`91b8bd3`） | `reports/w3c/RELAY.md §给 W0-2` |
| 6 | `CallRecord` 新增 `budget_s`/`over_budget` 两字段 → 若已写 Prometheus 指标请一并纳入 | W3A §12 | `app/llm/__init__.py:259-262` |
| 7 | `DegradedReason` 缺 `understanding_failed`/`sql_generation_failed`（W3B 现用 `plan_generation_failed` + `detail.missing_reason_value` 显式标注凑值） | W3B | `app/planner/errors.py:80,142` |
| 8 | `PlannerPort.generate_sql` 缺"归一化问题"入参（W3B 现以 `plan["normalized_question"]` 约定绕开，缺失即抛契约错误） | W3B | `app/core/contracts.py:427-429`、`engine.py:729` |
| 9 | `PlanSummary.blocked` 是 C-01 之外的额外键，需正式登记（或换表达） | W3B | `app/planner/schemas.py:354,370` |
| 10 | `CandidateRef` 缺两个字段：①"分数来源"（L1–L3 `score=0.0` 是占位）②打分器标识（注入路径 τ 身份校验恒通过） | W3C | `reports/w3c/DELIVERY.md §7-1/2` |
| 11 | 依赖复核：`tenacity`/`respx` 是否移出白名单（W3A 未用 tenacity、Q5 用 `string.Template` 未用 jinja2）——归 ADR-20 | W3A | `reports/w3a/RELAY.md §给 W0-4` |
| 12 | `LLM_TIMEOUT_SECONDS=60` 已被 §10.2 取代且**未被使用**——补注释或裁决删除 | W3A | `app/core/config.py` |

### 2. §给 W1B（`app/repo/**` + migrations）

| # | 事项 | 来源 | 依据 |
|---|---|---|---|
| 1 | 🔴 建 **`cost_ledger`** 表（列逐列对齐 `app/llm/budget.py::CostEntry`；保留 13 个月）+ 实现 `CostLedgerSink`（`record`/`tenant_spent_cny`/`global_spent_cny`，`created_at` 带 时区，`cost_cny` 用 `Decimal`）。**表没建好前熔断在重启面前失效**（内存 sink） | W3A | `reports/w3a/RELAY.md §给 W1B` |
| 2 | 🔴 建 **`query_plan`** 表 + `binding_state`/`binding_layer` 列（迁移 0001–0003 均无；07 §12.3:2292、§:1540）。**W3C DoD① 的硬前置** | W3C | `reports/w3c/RELAY.md §给 W1B` |

### 3. §给 W4（`graph/**`、`api/**`）—— **阶段 4 开工输入，按 08 §3.6 的 DoD 对齐**

**装配（lifespan）**：
- `build_gateway(settings, ledger=…, degradation=SseDegradationSink(), …)`，收尾 `await gateway.aclose()`（W3A）；
- `PlannerEngine` **每请求构造一个**（不得跨请求复用——`_pending` 会串降级事件），`Clock(runtime.time_semantics())`（W3B）；
- binding 的 lifespan 装配 + **每请求设问句上下文**（不设 ⇒ L2 与五步过滤步③**静默失效**）（W3C）。

**事件/侧信道（不接线就是坏的）**：
- 降级 → SSE：`DegradationSink.on_degraded` 是**同步回调**（禁止 `asyncio.run`；async emit 自桥接）；`LlmRefused` 必须**先捕**并转 `refuse` 终态，否则落 `500 INTERNAL`（错终态）（W3A）；
- planner 两条降级通道都要接：同步 sink + outcome 的 `degradations[]`（W3B）；
- binding 观测出口必须有实现（N-27 约束⑤：`binding_layer` 分布可观测）（W3C）。

**🔴 预算与延迟（阶段 3 收口后新增的责任，原本不存在）**：
- **§16.1 阶段预算的执行责任现在归你（SSE 层）**：网关已不再按预算掐调用（超预算照跑完 + `over_budget=true`，**不发 degraded**）。07 §16.2"若 1.2s 未完成 → 先推 `stage=intent` 占位"**必须由你发**，否则 **NFR-1.2 没有任何执行点**（W3A §12）；
- **L3+ 实测 50–60s/请求且答案来自 flash**（pro 被 45s 掐断后降级）：你的 SSE **必须撑住 60s 不断流**（心跳/keepalive），且 `switched_to_weak_model` 事件照常发（W3A §13）。

**入参契约（照做，别自行发明）**：
- `generate_sql(plan, ctx, *, candidates)` 的 `plan` **必须带 `normalized_question`**（缺失即抛契约错误）——`build_plan` 的返回**原样下传**，别拆散重组（W3B）；
- `build_plan` 的 `candidates` 参数**当前不进 prompt**（`plan_v1` 无占位符）——传了没效果，别以为计划看到了候选（W3B）；
- state 载荷以 `PlanOutcome.state_payload()` / `SqlOutcome.state_payload()` 为准（W3B）；
- binding 消费 `BindingResult` 用"读法 1"；L4 双入口（D1(a)）**选一条**并登记（W3C）。

### 4. §给 W6（评测执行器）

τ/ε 校准脚手架的唯一消费方是你（W3C）：`calibration.calibrate()` 六步 + `assess_stability`（E-5：n≥3 硬校验 + Kendall τ-b 自实现 + 分差 std）。**注意：L4 从未接真实 LLM（MockTransport）⇒ τ 尚未在真实打分器上校准，真跑前 `is_finalizable` 必为 `False`**（设计使然，但阶段 3 收口时 E-5 稳定性**未在真实链路验证过**，收口结论要写）。

### 5. §给 W2B / W1A（小口径）

- W2B：检索集成用例在**库不可达时应 error 而非 skip**（当前 `test_retrieval_fts_pg.py` 的红/错形态让三个窗口都误判过基线）（W3C）；
- W1A：语义包字段缺口清单见 `reports/w3c/RELAY.md §给 W1A`（W3C）。

### 6. §给架构窗口（裁决上呈 —— 合并去重后成**单一文档**）

| 来源 | 数量 | 要点 |
|---|---|---|
| W3A | §8 的 8 条 + 追加 ⑪⑫⑬ | ⑪ 预算被当硬超时（**已修，但 §16.1 数字与执行点仍未裁**）；⑫ §16.1 分配值被证伪（1.39–1.60s vs 0.6–1.3s）；⑬ **PRD §12.2 × 07 §10.2（45s）× 8s P95 三者不可同时成立**（pro 实测 97–138s，端到端从未生效）——A/B/C 三方向原样呈报，**不预设立场** |
| W3B | 10 条（DELIVERY §五-6） | ①② 与 W3A ⑪⑫ **同源必须合并**；③ 手段 2 触发条件已成立（合并 `plan`+`gen_sql` 需新资产+新 `LlmTask`，若思考档会正撞 ⑬）；④–⑩ 见原文 |
| W3C | 9 条（DELIVERY §7） | 含 `CandidateRef` 两缺字段、`BindingPort.resolve` 无问句位、`platform_admin` 两判据相反、`query_plan` 缺列（与给 W1B 的需求同源） |

**另两项非编号裁决**：① `PROMPT.md` 入库惯例（§三-8，三窗一致）；② W3C 的 `l4_score` 真机延迟未量过（W3A 请它自测，收口时可代量）。

### 7. 债务类（不是裁决，是"等依赖"清单）

等 W1B：`cost_ledger`、`query_plan` 两表 ｜ 等 W0：Retry-After 落码、`DegradedReason` 补值、`CandidateRef` 扩字段、obs 指标、`assert_importlinter` 并发安全 ｜ 等 W6：τ 校准 ｜ 等 W4：全部接线（§七-3）｜ 等架构：⑪⑫⑬ + 合并档 2（W3B DoD① 的未达成半）。

## 八、收口结论必须如实写的四条（**不得记成"已达成"**）

1. **W3B DoD① 只记部分达成**：合并档 1 已实测（省 ~0.80s，数值口径以 W3A §12.1 为准）；`plan`/`gen_sql` 实测超 §16.1 分配；**合并档 2 未实现**；**§16.1 预算执行点现在空缺**（网关已修但无人执行 §16.2 兜底）。
2. **W3C DoD① 只记部分达成**：`(state, layer)` 二元组与观测出口已备，但 **`query_plan` 表不存在 ⇒ "双双落库"未达成**。
3. **L3+ 的 pro 档从未生效**（候选 ⑬ 未裁）：用户在 L3+ 上拿到的是 flash 的答案、代价 50–60s/请求。**别把"L3+ 慢"当回归**——那是 ⑬ 的既有事实。
4. **三包零调用方**：阶段 3 的"可用"是**模块级可用**，端到端要等 W4。收口报告不得使用"链路已通"类表述。

## 九、本机环境坑（实测，逐条都会浪费你半小时）

1. **Docker Desktop 不会自启**：先启动再跑全量；未启动时 1F+6E+55S 全是集成假红（§三-3）。
2. ☠️ `assert_importlinter.py` 报 `FATAL: 注入任何探针之前，lint 就已经失败` ⇒ 先查 `backend/app/guard/_probe_violation.py` 是否残留（`.gitignore:46` 已含 `**/_probe_violation.py`，**不在 git 里，删掉即可**，不要当技术债记）。绕法：`rm -f` 与跑脚本写在**同一条命令**里；**别用管道**接输出（SIGPIPE 杀掉清理）→ 用 `> file` 重定向。
3. `lint-imports` 必须用**控制台脚本**（`../.venv/Scripts/lint-imports.exe`）；`python -m importlinter.cli` 是**无输出 exit 0 的假绿**（U-41）。
4. `pytest` **无 `pytest-timeout` 插件** → 传 `--timeout=` 会 exit 4；全量约 67s，后台跑并落日志。
5. venv = `CommerceQL/.venv`（从 `backend/` 用 `../.venv/Scripts/python.exe`）；系统 Anaconda 3.11 的 pydantic 是 1.x，不合格。
6. Bash 工具每条命令前加 PATH 前缀（PortableGit）；stderr 的 `dirname: command not found` 无害。
7. **并行窗口会在同一工作副本同一条 `main` 上提交**：提交前先 `git log --oneline -5` 看父链；判断与远端是否分叉用 `git ls-remote origin main`（沙箱里 `git fetch` 写不进 `refs/remotes/origin/*`，`git branch -r` 可能为空）。
8. `git add` 只暂存本窗口文件（工作区常有 `_gs.txt`、`reports/arch/`、`reports/w0/` 等他人未跟踪件）。
