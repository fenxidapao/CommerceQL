# 【窗口提示词 · 阶段 4 · 编排收口（W4）】

> 骨架沿用 `reports/w3c/PROMPT.md`（定位 → 契约与纪律 → 现状 → 任务清单 → 必读 → 边界 → 决策点 → 交付 → 环境坑）。
> 产出：W3-INT 收口窗口（受用户指令）｜日期：2026-09-17 深夜｜基准 commit：**`9f6fd15`**（远端 = 本地）。
> **W4 是所有模块的汇合点，08 §3.6 明文"必须单窗口"**——多窗口改这一处必然撞车。其余窗口停手或只写测试。
> 交付目录：`backend/reports/w4/`（你的 DELIVERY.md / RELAY.md 落这里）。

---

你是 CommerceQL「阶段 4 · 编排收口」窗口（**W4**）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 `main`，远程 `fenxidapao/CommerceQL`。

【开工方式】**先输出执行计划，等确认后再动手**。需求不明确先提问，不要猜。
【红线】不伪造实现；不把"未接线/未联调"报告成"已实现"；跑不通就说卡在哪；决策点先"报告现状"再等指令；**Mock 不得冒充联调通过**（W5 同款红线）。

## 一、定位

- 独占范围（08 §4.1）：**`app/graph/**`（全部）· `app/api/errors.py` + `app/api/sse.py` · `app/api/routers/**`（除 health.py=W7）· `tests/{contract,graph_snapshot,redteam}/**`（redteam 与 W2C 共建）**。
- 扩展权（整体移交，**不得两边各留一份**，U-42）：`app/api/deps.py`、`app/api/ratelimit.py`（W1B 骨架 → 你在其上扩展运行时装配/限流拦截/会话锁守卫）。
- **追加权（不得另立第二个组装根）**：`app/main.py` 是组装根（lifespan 六步已由 W1B/W2-INT 落）——你的装配（网关/binding/planner/图编译/路由注册）**在该文件追加**。
- 交付 08 §3.6 全部产出：①`graph/nodes/` 接线（16 节点）②`graph/edges.py` 条件边（含 `route_terminal` 幂等收口）③**`graph/events.py`**（17 事件 + `terminal` 唯一性保证）④版本固定（会话级）⑤两段审计接线 ⑥每节点超时与失败转移。
- 你是三包（`app/llm`/`app/planner`/`app/binding`）**唯一的生产消费者**；也是 W5 前端联调的后端对端。

## 二、契约与纪律

- 契约优先级：**附录 A(02) > PRD(01) > 06 UIUX > 07 TDD(v1.0) > 08 实施计划(v1.2)**。
- 端口已冻结（W0 的 `app/core/contracts.py`，不得改；缺口提需求见 §七）：`LLMPort` / `PlannerPort` / `BindingPort` / `SemanticBundlePort` / `EventEmitterPort` / `RetrievalPort` 等。
- **确定性模块纪律**：你的节点编排层可以 import 三包与各层 Port，但 **`graph/events.py` 发射的事件取值必须来自 `core.enums`**（`Stage` 6 值、`sse_event` 12 值、`sse_emission_points` 17 点、`error_code` 28 值、`DegradedReason` 8 值），不得私造字面量。
- **前端零判断权 ⇄ 后端唯一判断权**：图表类型/口径/脱敏/`scope` 文案全部由你产出，前端逐字渲染（W5 有探测器记 `ui_contract_violation`）。
- 动手前先 `git status` + `git diff --stat` 判"是否别人的在制品"；**同一文件多处 Edit 串行改 + grep 复核**。
- 提交：`feat(w4)` / `docs(w4)`，只暂存本窗口文件。
- 编号纪律：**不得自行开号**。新问题列"待架构窗口分配"，下一可用号 = **`U-87`**（U-65~86 已被架构窗口用尽）。

## 三、现状盘点（2026-09-17 深夜实测；动手前复核）

| # | 事实 | 位置 |
|---|---|---|
| 1 | 三包已交付、**零调用方**；接线输入分散在 6 份 RELAY（见 §五必读），本提示词 §六已提炼硬约束 | `git log` |
| 2 | `graph/build.py`（341 行）= W1B **桩图** `stub_a→stub_b→stub_c` + **checkpoint 装配唯一决定点**（`CheckpointStrategy` 四种装配 + T-A1 结论落地处）+ `GRAPH_VERSION`——你接管真实装配，但这三个职责**不因接管而作废** | `app/graph/build.py` 模块头 |
| 3 | `graph/state.py`（483 行）= `GraphState`（含 `degradations[]`、`plan`/`plan_summary` 曾是 OpaquePayload 占位——W3B 后真类型以 `PlanOutcome.state_payload()`/`SqlOutcome.state_payload()` 为准，见 §六-5） | `app/graph/state.py` |
| 4 | `api/sse.py`(99)/`errors.py`(163) = W0 骨架；`deps.py`(221)/`ratelimit.py`(248) = W1B 骨架（文件头注明整体移交） | `app/api/` |
| 5 | `main.py`（246 行）lifespan 六步已落：τ gauge（U-19）→ 三池+Redis → 语义包 runtime（软依赖 degraded）→ 启动断言 → checkpointer 开池 → 探针注册。**你的装配追加在其后，资源释放挂同一 shutdown 段** | `app/main.py:50-204` |
| 6 | **W1B 0004 已落两表**：`app.cost_ledger`（列逐字对齐 `CostEntry`）+ `app.query_plan`（`binding_state`/`binding_layer` CHECK= enums 冻结快照）+ **`DbCostLedgerSink`**（`app/repo/cost_ledger.py`，同步三方法、单条专用连接、`connect_timeout=2`）→ W3C DoD① 只差你写入 | `reports/w1b/RELAY.md §9` |
| 7 | **W0 `1c24f14` 已修 7 条**：Retry-After 落码 **5s/30s**、空 API key `min_length=1`、`assert_importlinter` 并发安全根修、**`obs.metrics.observe_binding_state/layer` 计量端已落**、tenacity/respx 依赖清理 | `reports/w0/` |
| 8 | **架构裁决已执行（07 v1.0）**：U-65=`gen_sql_complex` 预算 3.0s（经验值）；U-66=**§16.2 占位符先推的执行点 = 你（SSE 层）**；U-67=**L3+ 生效档 = flash 非思考 + 15s 上限**（pro 白等 50–60s 场景已消失，但降级链 pro→flash 机制保留，P1 重启 pro 时回来——心跳仍按"可能慢"设计，别砍） | `reports/w3a/RELAY.md` 回执节 |
| 9 | **W5 前端已交付**（`e01c198`+`9f6fd15`）：MSW mock 层 + SSE 客户端 + 15 组件 + 五页；其 RELAY §一 = 对你的联调清单（事件字段/端点行为/CORS 头/限流逐桶/幂等约定），**§1.1 顺序约束 4 条是硬假设** | `reports/w5/RELAY.md` |
| 10 | W3B 勘误后口径：`plan`/`gen_sql` 真机 1.49s/1.60s（W3A §12.1 为准）；**U-68 合并档（plan+gen_sql）未开工**——接线时仍是两个 task，若中途落地须适配"flash 非思考 + `plan_ready` 先发" | `reports/w3b/DELIVERY.md §八` |
| 11 | 门禁基线（U-67 后）：pytest **1500/6/0**、mypy **104 files**、lint-imports 4 kept；6 skip = `test_retrieval_fts_pg.py` 夹具 DDL 权限（既有） | `reports/w3a/DELIVERY.md §14.4` |

## 四、任务清单（建议执行序，可按依赖调整）

1. **T0 环境自证**：起 Docker Desktop；venv = `CommerceQL/.venv`；`git status` 判在制品；复跑门禁钉基线（§三-11）。
2. **T1 读接线输入**：§五必读清单逐份读完（尤其 6 份 RELAY 的 §给 W4），把与本窗口冲突/含糊处列成问题清单先澄清，**不要边接边猜**。
3. **T2 `graph/nodes/`**：16 节点接线（07 §5.3 节点表）。每节点一个文件；节点内**只编排**，业务逻辑留在三包。
4. **T3 `graph/edges.py`**：条件边 + `route_terminal` **幂等收口**（重复进入不得二次发射终态）。
5. **T4 `graph/events.py`**：17 事件发射点 + **N-08（恰有 1 个 `terminal:true`）唯一性保证**。SSE 帧格式唯一入口 = `api/sse.py`；错误码映射唯一入口 = `api/errors.py`。
6. **T5 端点**：`POST /query`（SSE）· `POST /query/{task_id}/cancel`（**幂等**：重复 cancel 不得 5xx）· `GET /query/{task_id}`（轮询状态机）· `POST /session` · `GET /session/{id}` · `POST /clarify` · `POST /feedback`（对照 W5 RELAY §1.2 逐行核对，含前端期望的响应头）。
7. **T6 装配（`main.py` 追加）**：`build_gateway(settings, ledger=DbCostLedgerSink(...), degradation=<你的 sink>)` + shutdown `gateway.aclose()` + `sink.close()`（长连资源，W1B §9.2）→ `BindingService.from_settings(...)` + `assert_usable_tau()` + 观测适配器 → 图编译（复用 build.py 的 checkpoint 决定点）→ 路由注册。
8. **T7 每请求上下文与写入**：每请求 `PlannerEngine`（**不得跨请求复用**，`_pending` 串事件）+ `set_binding_scope(...)`/`finally clear` + `set_call_context(...)`（计量）→ **`query_plan` 写入**（`binding_state`/`binding_layer`，W3C DoD① 最后一步）→ binding 观测适配器调 `observe_binding_state/layer`（**别自行登记同名 Counter**）。
9. **T8 韧性**：每节点超时与失败转移、两段审计接线、版本固定（会话级 = `GRAPH_VERSION`）、§16.2 占位符先推（U-66：1.2s 未完成 → 先推 `stage=intent` 占位——**这是 NFR-1.2 唯一执行点，由你发**）。
10. **T9 测试**：`tests/contract/`（SSE 转录覆盖**全部出口路径** + 断言恰 1 终态）、`tests/graph_snapshot/`、`tests/redteam/`（与 W2C 共建）。**8 条事件序列约束（07 §14.3）逐条有测试；07 §14.2 A–H 八组决策表逐行有测试**。
11. **T10 DoD 自验 + 门禁 + 交付**：08 §3.6 四条 DoD 逐条对照（§八）；六道门禁原样进 DELIVERY；`reports/w4/{DELIVERY,RELAY}.md` + commit + push。

## 五、必读清单（精确到来源）

1. **07 v1.0**：§5 全章（图节点/边/状态）· **§14.2–14.3**（A–H 决策表 + 8 条事件序列 + refuse/降级语义）· **§16.1–16.2**（v1.0 已重算；U-66 执行点=你）· §10.2（超时口径：flash 15s/pro 45s；L3+ 生效档=flash 非思考）· §12.3（`query_plan`/`cost_ledger` 落库点）· §15.3（指标清单与标签基数）· §18（探针/停机）。
2. **08**：§3.6（DoD 原文）· §4.1（归属权表——你落笔前逐行核对）。
3. **附录 A**：A.1–A.14（请求/事件/分页/幂等/错误码/限流头/SSE 配置）——W5 按它实现，你的对端契约。
4. **六份 §给 W4**（接线输入，冲突时按下述优先级综合）：`reports/w3-int/RELAY.md` §给 W4（总纲）→ `w3a/RELAY.md` §给 W4 ×3（含 **U-67 回执：L3+ 行为已变**）→ `w3b/RELAY.md` §给 W4 + 勘误节 → `w3c/RELAY.md` §给 W4（含"读法 1"消费姿势）→ `w1b/RELAY.md` §9.2（DbCostLedgerSink 装配点）→ `w5/RELAY.md` §一（联调清单）。
5. `reports/w3c/PROMPT.md` §六（W3C 交付期给 W4 的四条接线须知——唯一权威在 `app/binding/__init__.py` "给 W4"节）。

## 六、接线硬约束（从六份 RELAY 提炼，接漏就是坏的；细节以原文为准）

**装配**：`build_gateway(settings, ledger=DbCostLedgerSink(DATABASE_URL 原值), degradation=...)`，收尾 `await gateway.aclose()` ＋ `sink.close()`；`PlannerEngine` **每请求一个**；binding lifespan 装配 + `assert_usable_tau()`；每请求 `set_binding_scope`（不设 ⇒ L2 与过滤步③**静默失效**）+ `set_call_context`（不设 ⇒ 计量归 `"(unset)"`）。

**事件/侧信道**：两条降级 sink（llm + planner）都要接，`on_degraded` 是**同步回调**——☠️ 禁止 `asyncio.run`；async emit 自桥接（`Queue.put_nowait`）；阻塞回调 = 吃延迟预算；planner 第二通道 `outcome.degradations[]` 也要进 `GraphState`。**`LlmRefused` 必须最先捕获**转 `refuse` 终态，否则落 `500 INTERNAL`（错终态）；`except PlannerError` 前先分流 `LlmRefused`。

**预算/心跳**：超预算不再失败（照跑完 + `over_budget=true`，**不发 degraded**）；§16.2 占位先推由你发（U-66）；heartbeat 按 **15s** 送达（前端 90s 看门狗靠它重置）；SSE 按"L3+ 可能慢"设计长连（P1 重启 pro 时 50s+ 回来）。

**入参契约**：`generate_sql` 的 `plan` **必须带 `normalized_question`**（`build_plan` 返回原样下传，别拆散重组）；`build_plan` 的 `candidates` 当前**不进 prompt**（别以为计划看到了候选）；state 载荷以 `state_payload()` 为准；binding 消费 `BindingResult` 用"读法 1"（`resolve_detailed`；`ambiguous` 态下 `bindings` 是澄清选项，拿去生成 SQL 是错的；`disclosure` 写进 `insight.caveats[]`）；L4 双入口**选在线 `score_l4`**（真校验）并登记。

**对前端（W5 RELAY §一，逐条核对）**：`task_id` 首帧尽快给（停止/看门狗/轮询都靠它）；`stage=sql_ready` → 前端不等 `data` 直接渲染 SqlCard；`data.truncated=true` 必带截断条；`chart.option` **不得含函数字符串**（直接喂 ECharts）；`insight.text` 过前端因果/预测措辞拦截——后端确保合规；`degraded` 恒 `terminal:false`；`clarify`/`refuse`/`error`/`complete` 四终态互斥且恰一 `terminal:true`；`error.detail` 仅 `role ∈ {analyst, platform_admin}` 下发；**CORS**：`Access-Control-Allow-Headers` 放行 `Authorization`/`Idempotency-Key`/`X-Trace-Id`，`Access-Control-Expose-Headers` 暴露 `X-RateLimit-*` 四头 + `Retry-After`；限流**逐桶**下发四头（前端只认 `query` 桶）；`409 SESSION_CONFLICT` **不带** `X-RateLimit-*` 且前端只对它自动重试；`meta.scope` 三级各给可复现夹具（含 `disclosable=true,notice!=null` 与 `notice=null` 两例；`tenant_isolated` 空结果与真无数据**同形**）。

## 七、动手前必须"报告现状 + 拿指令"的决策点

1. **🔴 `AsyncTaskStatus` 两源不一致**（W5 RELAY §三-2）：附录A A.2 = `queued/processing/complete/...`，`core/enums.py::TaskStatus` = `pending/running/succeeded/...`。前端按附录A实现；你若实发 `succeeded`，前端会空转轮询到 1h。**轮询端点返回哪个取值集，先上呈架构裁决**——你不得改 `enums.py`（W0 域），也不得假设 W5 会改。裁决前的临时方案（如适配层映射）须在 DELIVERY 登记并标 UNVERIFIED。
2. **D-H 登录端点未裁决**（W5 §三-1）：`/login` 是壳；你的身份注入（`IdentityContext` 来源）在 stub token 下如何联调，先报现状再动手。
3. **U-68 合并档未开工**：plan+gen_sql 仍两 task；若架构中途批 U-68，新 `LlmTask`/资产由 W3A 产，你接线适配 `plan_ready` 先发。
4. **07 §14.2 A–H 决策表与 §14.3 序列约束**如有 v1.0 未覆盖的路径（例如 `switched_to_async` 与占位符的组合时序），先列出来上呈，不要发明语义。
5. 其余任何"文档没写、实现要选"的点：列候选 + 你的倾向 + 代价，**等指令**（U-22 纪律：不许发明数字/语义）。

## 八、DoD（08 §3.6 原文，交付时逐条对照）

① **SSE 转录测试覆盖全部出口路径，并断言"恰有 1 个 `terminal:true`"**（N-08）② 07 §14.3 的 **8 条事件序列约束全绿** ③ `stage` 取值只有 6 个（枚举校验）④ 07 §14.2 的 **A–H 八组决策表逐行有对应测试**。

**收口结论必须如实写的三条**：① 端到端"可用"指**后端真实链路 + 前端 mock 之外的真实联调未做**——W5 的 17 条 BLOCKED QA（D 组 7 条等）要等你 + 联调环境，不得写成"全链路已通"；② U-68 未落 ⇒ W3B DoD① 仍只算部分达成，与你无关但别写反；③ 若 §七-1 的取值集裁决未回，轮询状态机的契约一致性标 UNVERIFIED。

## 九、边界（这些目录归他人，只能提需求）

`app/core/**`（W0）｜`app/{llm,planner,binding}`（W3A/B/C，接口问题走其 RELAY 回执）｜`app/repo/**`+migrations、`app/auth/**`、`app/main.py` **已有部分**、`app/cache/session_lock.py`（W1B）｜`app/semantics`（W2A）｜`app/retrieval`（W2B）｜`app/guard`（W2C）｜`app/{exec,mask}`（W2D）｜`app/api/routers/health.py`（W7）｜`app/obs/**` 指标本体（W0 已落，你只调用）｜`frontend/**`（W5）｜`eval/**` 执行器（W6）｜`deploy/**`（W7）。

## 十、交付物

| commit | 内容 |
|---|---|
| `feat(w4)` | `app/graph/**`（nodes/edges/events + build.py 接管）+ `app/api/{errors,sse,deps,ratelimit}.py` 扩展 + `app/api/routers/**`（除 health）+ `app/main.py` 追加段 + `tests/{contract,graph_snapshot,redteam}/**` |
| `docs(w4)` | `reports/w4/{DELIVERY.md, RELAY.md}`（RELAY 含给 W5 的联调回执 + 给架构的上呈 + 逐窗口回执） |

## 十一、本机环境坑（沿用 W3-INT §九，逐条都会浪费半小时）

1. Docker Desktop 不自启，先启动再跑全量（未启动 = 1F+6E+55S 集成假红，全在 `tests/integration/`）。
2. `assert_importlinter.py` 已由 W0 根修并发安全（`1c24f14`）；若仍见 `FATAL: 注入任何探针之前 lint 就已经失败`，先 `rm -f app/guard/_probe_violation.py`（不在 git，删掉即可，别当技术债）并与跑脚本同一条命令执行。
3. `lint-imports` 必须用**控制台脚本**（`.venv/Scripts/lint-imports.exe`）；`python -m importlinter.cli` 是无输出 exit 0 的假绿（U-41）。
4. `pytest` **无 timeout 插件**（传 `--timeout=` 会 exit 4）；全量约 70s，后台跑并落日志。
5. venv = `CommerceQL/.venv`（从 `backend/` 用 `../.venv/Scripts/...`）；Bash 工具每条命令加 PortableGit PATH 前缀；别用 PowerShell（零回显）。
6. 并行窗口同一条 `main`：提交前 `git log --oneline -5` 看父链，`git ls-remote origin main` 判分叉；`git add` 只暂存本窗口文件。
7. `w2-int/e2e_stage2_check.py` 的未暂存修改与 `reports/{arch,w0}/` 未跟踪件是**他人的**，不碰。
