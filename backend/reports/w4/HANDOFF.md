# W4 交接件 · 新窗口继承说明（HANDOFF）

- 交接人：W4 窗口（阶段 4 · 编排收口）｜日期：2026-09-18
- 基准 commit：**`d09020c`**（W0 TaskStatus 四值裁正后）｜分支 `main`，远程 `fenxidapao/CommerceQL`
- 用途：本窗口因上下文容量交新窗口接续。**新窗口先读本文 → 再读 `PROMPT.md`（原窗口提示词）→ 从 §八 的 T2 开工**。

---

## 一、身份与边界（继承清单）

你（新窗口）是 **W4 负责人**。独占范围与纪律（08 §4.1 / PROMPT §一）：

**写白名单（只能改这些路径）**：
- `backend/app/graph/**`（全部）
- `backend/app/api/errors.py`、`backend/app/api/sse.py`
- `backend/app/api/routers/**`（**除 `health.py` = W7**）
- `backend/app/api/deps.py`、`backend/app/api/ratelimit.py`（W1B 骨架 → 在其上扩展运行时装配/限流拦截/会话锁守卫）
- `backend/app/main.py`（**只追加**，不得另立第二个组装根）
- `backend/tests/{contract,graph_snapshot,redteam}/**`
- `backend/reports/w4/**`（DELIVERY.md / RELAY.md / 本文）

**禁改（归他人，只能提需求）**：`app/core/**`(W0)、`app/{llm,planner,binding}`(W3A/B/C)、`app/repo/**`+migrations、`app/auth/**`、`app/cache/**`(W1B)、`app/semantics`(W2A)、`app/retrieval`(W2B)、`app/guard`(W2C)、`app/{exec,mask}`(W2D)、`app/api/routers/health.py`(W7)、`app/obs/**` 指标本体（只调用）、`frontend/**`(W5)、`eval/**`(W6)、`deploy/**`(W7)。

**红线**：不伪造实现；不把"未接线/未联调"报告成"已实现"；跑不通就如实说卡在哪；决策点先报告现状等指令；**Mock 不得冒充联调通过**；U-22 纪律：不许发明数字/语义。
**提交**：前缀 `feat(w4)` / `docs(w4)`，**只暂存本窗口文件**（`git add <具体文件>`，禁止 `add -A`）。
**编号纪律**：不得自行开号。**U-87 已被占用**（TaskStatus 裁定）；下一可用号待架构窗口分配。

---

## 二、仓库与环境事实（实测）

| 事项 | 事实 |
|---|---|
| 仓库根 | `E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`（后端在 `backend/`） |
| ⚠️ **设计文档不在仓库内** | `E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\docs\` —— 01 PRD / 02 附录A / 06 UIUX / 07 TDD / 08 实施计划 |
| venv | `CommerceQL/.venv` |
| Docker | 全路径 `C:\Users\林琪荣\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe` |
| PowerShell 坑 | 命令输出可能丢失 → 一律 `*> "$env:TEMP\xxx.txt"` 再 Read |
| Node | 必须用托管版，每次 Shell 开头先配 PATH（若 T 步骤只需 Python 可忽略） |
| git 现状 | HEAD `d09020c`；**未跟踪**：`backend/reports/w0/`、`backend/reports/arch/`、`backend/reports/w4/RELAY.md`；**他人在制品**：`M backend/reports/w2-int/e2e_stage2_check.py` —— **不要动、不要暂存** |
| 门禁基线（T0 实测，d09020c） | pytest **1500 passed / 6 skipped**、ruff 过、mypy **104 files**、lint-imports 4 kept；6 skip = `test_retrieval_fts_pg.py` 夹具 DDL 权限（既有） |

---

## 三、进度台账（截至交接）

| 任务 | 状态 | 说明 |
|---|---|---|
| T0 环境自证 + 门禁基线 | ✅ 完成 | 上表基线即 T0 产物 |
| T1 读接线输入 + 问题清单获批 | ✅ 完成 | 6 份 RELAY §给 W4、07/附录A/08 关键章已读；§七决策点已获裁 |
| 跨窗口需求统一转述件 | ✅ 落笔未提交 | `backend/reports/w4/RELAY.md`（四节：W0/W1B/架构/授权）。**建议新窗口以 `docs(w4)` 提交 RELAY.md + 本文件** |
| T2–T4 图接线 | ⬜ **未动笔** | 见 §八-1 |
| T5–T10 | ⬜ 未动笔 | 见 §八 |

**本窗（接续窗）核实的关键事实**：
1. `backend/app/graph/nodes/` **目录尚不存在** → T2 从零建（现有 `graph/` 仅 `build.py`(341行) / `state.py`(483行) / `__init__.py`）。
2. **`app/planner/__init__.py` 只有 docstring**（无导出）→ `PlannerEngine` 实体在 `app/planner/engine.py`；其余模块：`timeexpr.py` / `jsonish.py` / `payloads.py` / `errors.py` / `schemas.py`。**T2 前需通读 engine.py 的公开签名**（"每请求一实例"约束由此落实）。
3. `app/api/routers/` 现有 `health.py`(W7) + `__init__.py`；`app/api/dto/__init__.py` 为空壳（DTO 归 W4）。
4. 07 §5.3 节点契约表共 **17 行**：**行 1–16 = 16 个主节点**（`trusted_context`…`repair`，与 08 §3.6"16 个节点"对账一致）；**行 17 = 3 个终态出口节点**（`clarify_out` / `refuse_out` / `error_out`）→ `nodes/` 下实际文件数 = 16 + 3（出口可合并为一个文件但**必须三个具名节点**，见 §八-1）。
5. `app/api/{sse,errors,deps,ratelimit}.py` 与 `app/main.py` 骨架已在 T1 读过（上一窗），本窗未重读全文 → **T5/T6 前重读**。

---

## 四、待回执的跨窗口需求（全文见 `RELAY.md`，用户自行转述）

| 级 | 事项 | 挡什么 | 不挡什么 |
|---|---|---|---|
| 🔴 阻塞 | **W0 补 `app/cache/keys.py` 三组键**：`task_state`(`task:{id}` TTL3600)、`concurrency_lease`(`concur:{tenant}` ZSET TTL3600)、`session_meta`(`sess:meta:{t}:{s}` TTL86400) | T5 轮询状态机 / cancel 幂等 / session 两端点 + T8 转异步登记 | T2–T4、T6 |
| 🔴 阻塞 | **W1B 补 `app/repo/query_plan.py` 写入通道**（表已在迁移 0004；无写入函数） | T7 `query_plan` 落库 + W3C DoD① 最后一步 | T2–T6 |
| ⚪ 非阻塞 | 架构窗口落笔 07 v1.1：U-87 订正 / §14.2 增 cancel 行 / §16.2 占位×异步 / T-A1→§16.3；并确认 **§9.5 队列 P0 形态**（W4 拟：进程内 asyncio 等待 10s + Redis 租约计数；若坚持字面 Redis List(100) 则需 W0 再补 1 键） | 只影响收口文档一致性 | 全部编码 |
| ⚪ 非阻塞 | `backend/scripts/mint_dev_token.py` 落点授权（W4 白名单不含 `scripts/`；用途=D-H 未裁期间的本地令牌签发，RS256，配合 ADR-17 单文件 PEM） | 仅挡与 W5 真实联调 | 编码与测试 |

收到回执后先按其调整实现，再继续下一步。

---

## 五、已裁口径（**直接用，不要再问**）

1. **TaskStatus**：W0 `d09020c` 已对齐附录 A（`queued/processing/complete/clarify/refused/degraded/failed/cancelled`）。W5 无需改。
2. **cancel 语义**：cancel 成功**不发终态事件**（前端自行断流）；重复 cancel **幂等 200** `{task_id,status:"cancelled"}`；已终止且非 cancelled → **409 `TASK_NOT_CANCELLABLE`**；审计 `outcome=failed`。
3. **LlmRefused 最先捕获** → 转 `refuse(reason=no_data_asset)`（§14.2 C2 行）；`except PlannerError` 前先分流 `LlmRefused`。
4. **checkpoint 装配** = `SINGLE_SAVER_SHARED_POOL`（T-A1 结论）；W4 需同步登记进 `build.py` 头部注释。
5. **每节点超时** = `asyncio.timeout()` 包装（超时值取 07 §5.3 表；`execute` 交互 8s/上限 30s）。
6. **§16.2 占位符**：仅 `stage=intent` **单次**推出、**不回退**；1.2s（按 `normalize_intent` 分配 1.6s 判定，U-66 口语 1.2s 以 §16.2 表为准）未完成 → 先推 `stage=intent` 占位；转异步后**不收回**；执行体 P0 = 进程内 asyncio task（复用 `result_set`/`event_buffer` 键、**不跨重启**，launch 时登记）。
7. **X-RateLimit-\* 四头**：在 `ratelimit.py` 新增 `check_detailed()` 复用同次 Lua（不改 L0 契约）；`409 SESSION_CONFLICT`**不带** `X-RateLimit-*`。
8. **超预算 ≠ 失败**：照跑完 + `over_budget=true`（网关已根修），**不发 degraded**。

---

## 六、契约速查（读原文用行号；文档在仓库外的 `docs/`）

| 内容 | 文件:行 |
|---|---|
| 16 节点契约表（职责/调LLM/幂等/超时/失败转移/发 stage） | 07 L1282–1306 |
| 两段审计（段1 阻断 / 段2 非阻断） | 07 L1307–1319 |
| 条件边纯函数 + `route_terminal` 幂等收口 | 07 L1322–1337 |
| 检查点/线程模型（`thread_id`=tenant:user:session、recursion_limit=25、audit_pre/mask 同步） | 07 L1339–1351 |
| SSE 17 发射点 + 3 条实现约束（stage 6 值 / terminal 唯一 / degraded 顺序） | 07 L1354–1378 |
| 版本固定与灰度（会话级） | 07 L1380–1389 |
| §14.2 A–H 决策表（A1–A6 / B1–B6 / C1–C3 / D1–D7 / E1–E8 / F1–F6 / G1–G4 / H1–H15） | 07 L2625–2732 |
| §14.3 八条事件序列约束 | 07 L2734–2747 |
| §16.1 延迟预算（v1.0：plan/gen_sql 实测 1.49/1.60；gen_sql_complex 3.0 经验值）+ §16.2 首字节占位 | 07 L2884–2928 |
| 取值集唯一来源（Stage 6 / SseEvent 12 / 17 发射点 / terminal 恰 4 / ErrorCode 28 / TaskStatus 8） | `backend/app/core/enums.py` |
| GraphState 11 组 + `initial_state()` / `identity_fields()` / `assert_terminal_is_settable()`（N-08 写入口） | `backend/app/graph/state.py` |
| LLM：`build_gateway(...)` / `DegradationSink.on_degraded`（**同步回调，禁 asyncio.run**）/ `set_call_context` / `LlmRefused` / 模板层 P0 为空 | `backend/app/llm/__init__.py` |
| Binding：`BindingService.from_settings` / `assert_usable_tau` / `set_binding_scope`+`finally clear` / 读法 1=`resolve_detailed`（`bindings_are_options`、`disclosure`→insight.caveats）/ L4 选在线 `score_l4` | `backend/app/binding/__init__.py` |
| Planner：`PlannerEngine` 在 `backend/app/planner/engine.py`（**T2 前通读**） | — |
| 跨窗口转述件（含每条需求验收口径） | `backend/reports/w4/RELAY.md` |

**没写进上表的接线硬约束**：`generate_sql` 的 `plan` 必须带 `normalized_question`（`build_plan` 原样下传）；`build_plan` 的 `candidates` 不进 prompt；planner 第二通道 `outcome.degradations[]` 也要进 `GraphState.degradations`；两条降级 sink（llm+planner）都要接。

---

## 七、七组已读但尚未接线的事实（防重复踩坑）

1. `build.py` 的三个职责**不因 W4 接管而作废**：checkpoint 唯一决定点 / `GRAPH_VERSION` / 桩图。T6 复用其 checkpoint 决定点，不另造 saver。
2. `main.py` lifespan 六步已落（τ gauge → 三池+Redis → 语义包 runtime → 启动断言 → checkpointer 开池 → 探针注册，L50–204）；W4 装配**追加其后**，资源释放挂**同一 shutdown 段**（`await gateway.aclose()` + `sink.close()`）。
3. 预算/心跳：heartbeat **15s**（前端 90s 看门狗靠它重置）；SSE 按"L3+ 可能慢"设计长连。
4. CORS：放行 `Authorization`/`Idempotency-Key`/`X-Trace-Id`；暴露 `X-RateLimit-*` 四头 + `Retry-After`；限流逐桶下发（前端只认 `query` 桶）。
5. `error.detail` 仅 `role ∈ {analyst, platform_admin}` 下发；`chart.option` 不得含函数字符串；`degraded` 恒 `terminal:false`。
6. `stage=sql_ready` → 前端不等 `data` 直接渲染 SqlCard → 事件必须发（`explain=false` 时省略 `sql` 字段但**事件照发**）。
7. `first frame` 尽快给 `task_id`（停止/看门狗/轮询都靠它）。

---

## 八、剩余任务（按序，一步一汇报）

1. **T2–T4**：重读 07 §5.3/§5.4/§5.6 + `planner/engine.py` 公开签名 → 写 `app/graph/nodes/`（16 主节点 + 3 终态出口）、`app/graph/edges.py`（条件边 + `route_terminal` 幂等）、`app/graph/events.py`（17 发射点 + terminal 唯一性 + degraded 顺序）。消费三包姿势见 §六。
2. **T5 端点**：`POST /query`(SSE)、`cancel`（幂等）、`GET /query/{task_id}` 轮询状态机、`POST/GET /session`、`POST /clarify`、`POST /feedback`（对照附录 A A.1–A.14 + W5 RELAY §1.2 逐行）。**等 W0 三组键回执**。
3. **T6 `main.py` 追加装配**：`build_gateway(settings, ledger=DbCostLedgerSink(DATABASE_URL 原值), degradation=<sink>)` → `BindingService.from_settings` + `assert_usable_tau()` + 观测适配器（调 `obs.metrics.observe_binding_state/layer`，**不得自行登记同名 Counter**）→ 图编译 → 路由注册 → shutdown 释放。
4. **T7 每请求上下文与写入**：`PlannerEngine` **每请求一实例**（不得跨请求复用）；`set_binding_scope`+`finally clear`；`set_call_context`；**`query_plan` 落库**（等 W1B writer）。
5. **T8 韧性**：每节点超时与失败转移、两段审计、会话级版本固定（= `GRAPH_VERSION` 组合）、§16.2 占位先推（U-66）、heartbeat 15s。
6. **T9 测试**：`tests/contract/`（SSE 转录覆盖**全部出口路径** + 恰 1 终态）、`tests/graph_snapshot/`、`tests/redteam/`（与 W2C 共建）；**§14.3 八条逐条有测试；§14.2 A–H 逐行有测试**。
7. **T10 收口**：08 §3.6 四条 DoD + 六道门禁进 DELIVERY；`reports/w4/{DELIVERY,RELAY}.md` 补齐（含收口三条如实结论：真实联调未做 / U-68 未落 / 契约一致性不标 UNVERIFIED 除非裁决未回）；commit + push。

---

## 附录 A · 开新窗口提示词（整段复制到新窗口）

```text
你是 CommerceQL「阶段 4 · 编排收口」窗口（W4）的延续窗口负责人。仓库：
E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL，分支 main，远程 fenxidapao/CommerceQL。

【第一步·必读，按序】
1. backend/reports/w4/HANDOFF.md —— 交接件（身份/边界/进度/待回执/已裁口径/任务序），
   其中的事实表与行号就是你的即时上下文；
2. backend/reports/w4/PROMPT.md —— 原窗口提示词（§六 接线硬约束、§八 DoD 原文）；
3. backend/reports/w4/RELAY.md —— 跨窗口需求转述件（用户已自行转述，不必催）。

【身份与纪律】写白名单：backend/app/graph/**、backend/app/api/{errors,sse}.py、
backend/app/api/routers/**（除 health.py）、backend/app/api/{deps,ratelimit}.py、
backend/app/main.py（只追加）、backend/tests/{contract,graph_snapshot,redteam}/**、
backend/reports/w4/**。禁改 app/core、app/{llm,planner,binding}、app/repo、app/auth、
app/cache、app/semantics、app/retrieval、app/guard、app/{exec,mask}、frontend、eval、deploy。
红线：不伪造实现；不把"未接线"报告成"已实现"；Mock 不得冒充联调通过；决策点先报告
现状等指令；不许发明数字/语义（U-22）。提交前缀 feat(w4)/docs(w4)，只暂存本窗口文件；
不得自行开号（U-87 已占用）。动手前先 git status 判他人在制品
（注意 backend/reports/w2-int/e2e_stage2_check.py 是他人改动，不要动）。

【环境坑】设计文档不在仓库内，在 ..\docs\（07/08/附录A 等）；PowerShell 输出会丢 →
命令一律 *> "$env:TEMP\xxx.txt" 再 Read；venv=CommerceQL/.venv；Docker 用全路径
C:\Users\林琪荣\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe。

【已裁口径·直接用】见 HANDOFF §五（cancel 语义、LlmRefused 先捕、checkpoint=
SINGLE_SAVER_SHARED_POOL、每节点 asyncio.timeout、§16.2 占位先推、任务状态 8 值已对齐等）。

【当前进度】T0/T1 完成（门禁基线：pytest 1500 passed/6 skipped、mypy 104 files、
lint-imports 4 kept）；RELAY.md 已落笔未提交（可先 docs(w4) 提交 RELAY.md + HANDOFF.md）；
T2–T4 未动笔（graph/nodes/ 目录尚不存在，从零建）。

【现在开工】按 HANDOFF §八 顺序执行，**每步完成即汇报**：
T2–T4 先重读 07 §5.3（L1282）/§5.4（L1322）/§5.6（L1354）+ app/planner/engine.py 公开签名，
再写 app/graph/nodes/（16 主节点+3 终态出口）、graph/edges.py（route_terminal 幂等收口）、
graph/events.py（17 发射点+terminal 唯一性+degraded 顺序）；随后 T5 端点（等 W0 三组键）、
T6 main.py 追加装配、T7 每请求上下文（等 W1B writer）、T8 韧性、T9 测试（§14.3 八条+
§14.2 A–H 逐行）、T10 收口（DoD+六道门禁+DELIVERY/RELAY+commit+push）。
需求不明确先提问，不要猜；跨窗口阻塞项状态若用户已带回执，按其调整实现。
```