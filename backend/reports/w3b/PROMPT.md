# 【窗口提示词 · 阶段 3B：理解与生成（W3B）】

> **产出**：W3B 窗口（本文件为**开工轮任务定义的落档重建**）｜日期：2026-09-17
> ⚠️ **溯源诚实声明**：W3A 的 `PROMPT.md` 由 W2B 窗口产出并把全文作为开工上下文。
> 本窗口的开工指派是**会话内输入**，未随会话保留逐字原文；本文件据
> **① `docs/08` §3.5 的 DoD 原文 ② `docs/08` §4.1 的目录归属 ③ 实际交付与实测** 重建，
> 作为本窗口的**任务定义与 DoD 追溯锚点**。**不逐字复述开工问答**，避免转述漂移；
> 凡"已发生"的判断一律给**可核对位置**（文件 + 行/键），无位置的一律标 UNVERIFIED。
> 骨架沿用 `reports/w2-int/PROMPT.md` 的模板（定位 → 契约与纪律 → 现状 → 任务 → 必读 → 边界 → 交付 → 决策点 → 环境坑），
> 与 W3A 一致：W3B 是**开发窗口**，不是收口窗口（阶段 3 收口归 **W3-INT**）。
> 交付目录：`backend/reports/w3b/`｜实际交付与证据：同目录 `DELIVERY.md` / `RELAY.md`。

---

你是 CommerceQL「阶段 3B · 理解与生成」窗口（**W3B**）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 `main`，远程 `fenxidapao/CommerceQL`。

【开工方式】**先输出执行计划，等确认后再动手**。需求不明确先提问，不要猜。
【红线】不伪造实现；不把"未接线/未联调"报告成"已实现"；跑不通就说卡在哪；决策点先"报告现状"再等指令，不自行扩大范围。

## 一、你的定位

- 独占范围：**`backend/app/planner/**`**（08 §4.1 行 299）。开工时该目录**只有 `__init__.py`（仅 docstring）**——你是从零建包。
- 你负责 **07 §5.3 的节点 2/3/5/7/16**：`normalize` / `intent` / `plan` / `gen_sql` / `repair`，
  外加 **07 §16.1 压缩手段 1 的合并档**（`normalize`+`intent` → 一次调用）。层号 **L3**。
- 你落 **`PlannerPort`**（`app/core/contracts.py:416`，W0 冻结）：`build_plan` / `generate_sql`。
- 上游已就位：**W3A 的 `app/llm`（LLM 网关，已交付）**＋ W2A 的 `app/semantics`（语义包运行时）。
  ⇒ 你**不是**先拿桩写的那一包；你直接调真网关（可用假上游做离线测试）。
- 你**不是**收口窗口：阶段 3 的收口（汇总/接线/全量门禁/裁决上呈）由 **W3-INT** 承担。

## 二、契约与纪律

- 契约优先级：**附录 A(02) > PRD(01) > 06 UIUX > 07 TDD(v0.9) > 08 实施计划(v1.2)**。
- 端口已冻结（**W0 的 `app/core/contracts.py`，你不得改**）：
  - `PlannerPort.build_plan(question, candidates, ctx) -> Mapping`
  - `PlannerPort.generate_sql(plan, ctx, *, candidates) -> Mapping`
  - 🔴 **端口签名里没有"归一化问题"位**，而 `gen_sql_v1.txt` 需要它 ⇒ 走约定（`plan["normalized_question"]`），缺失**抛契约错误而不是编一个**；端口缺口提给架构。
- **W3A 已交接的调用面**（`reports/w3a/RELAY.md §给 W3B/W3C`，**照它写，不要自行发明**）：
  - `await port.call(task, payload, model="auto")`；`task` **10 个取值为契约**（改名即破坏你）；
  - `payload` **严格白名单**，多一个键就抛（**不静默丢弃**）；`user_id`/`tenant_id` 走 `set_call_context`，**永不出站**；
  - 🔴 **N-17：`sql_text` 永不回灌 prompt** ⇒ `repair` 只能吃 `error_digest`，**拿不到失败的那条 SQL**（设计如此）；
  - 🔴 **`LlmRefused` 是产品终态 `refuse`，不是 error** ⇒ **原样上抛，不要捕获**（连兜底 `except LlmError` 都不写）；
  - 网关**不解析 JSON**：`resp.text` 是字符串，提取 + schema 校验 + **修复 1 次**的归属**在你**。
- 机器化护栏（`.importlinter`，W0 落笔）：`planner` 可 import `app.core` / `app.llm` / `app.semantics` / `app.repo`；**不得** import `retrieval` / `present` / `graph` / `api`。
- 动手前先 `git status` + `git diff --stat` 判"是否别人的在制品"；**同一文件多处 `Edit` 必须串行改 + grep 复核**。
- 提交：`feat(w3b)` / `docs(w3b)`，只暂存本窗口文件。
- 编号纪律：**不得自行开号**。新问题列"待架构窗口分配"，下一可用号 = **`U-65`**。

## 三、开工时现状盘点（2026-09-17 实测）

| # | 事实 | 位置/证据 |
|---|---|---|
| 1 | `app/planner/` 只有 `__init__.py`（docstring），无任何模块 | 实测 |
| 2 | Doppler 侧已交付：`app/llm/**`（W3A，`94ae6ea`）、`app/semantics/**`（W2A）、`app/binding/**`（W3C 并行） | `git log` |
| 3 | **`app/planner/payloads.py` 与 `app/llm/egress_guard.py` 的接缝已由 W3A 定义**：`$output_schema` 由 **W3B** 产出（网关不产） | `payloads.py:16` 起 |
| 4 | `GraphState` 里 `plan` / `plan_summary` 此前是 `OpaquePayload` 占位，**真类型由 W3B 定义**（U-24） | `graph/state.py:49`、`schemas.py:20-22` |
| 5 | 10 个 prompt 资产已由 W3A 备好（`normalize_v1` / `intent_v1` / `normalize_intent_v1` / `plan_v1` / `gen_sql_v1` / `gen_sql_complex_v1` / `repair_v1` / `rerank_v1` / `present_v1` / `l4_score_v1`） | `app/llm/prompts/` |
| 6 | 任务级延迟预算 = 07 §16.1：`normalize` 0.6s／`intent` 0.6s／`plan` **1.0s**／`gen_sql` **1.3s**；合并档 = §16.2 **1.2s** | 07 §16.1/§16.2 |
| 7 | ⚠️ 上述预算是**阶段级 P95 分配**，§16.2 明写超预算应"**先推占位符**"（不是失败） | 07 §16.2 原文 |
| 8 | ⚠️ **`app/llm/router.py` 把 4/6 行的预算值当"单次调用硬超时"** → 真机上 `plan`/`gen_sql` **0/3 全失败** | 本窗口实测，见 `DELIVERY.md §五-1` |
| 9 | 真 key 已在 `deploy/.env` 的上游环境变量中可用 ⇒ **可做真机小样本实测**（成本约 ¥0.08/轮） | 实测 |
| 10 | `pytest` 全量基线可用；`lint-imports` 必须用**控制台脚本**（`python -m importlinter.cli` 是假绿，U-41） | `reports/w2-int/DELIVERY.md` |

## 四、任务清单（DoD 映射见括注 = 08 §3.5 行 231）

| 批 | 内容 | 产出 |
|---|---|---|
| **T0** | 环境与前置自证：venv 实测 import；`git status` 判在制品；复核 §三 每条（**上游可能已变**）；确认 `.importlinter` 4 条与本包关系 | 自证进 RELAY |
| **T1** | `schemas.py`：**LLM 输出契约唯一真相**（Pydantic v2，`extra="forbid"` + `frozen`）；意图取值**单表映射**；`plan_summary` 形状（**C-01：只放摘要、不含 SQL**） | + 单测 |
| **T2** | `payloads.py`：出站载荷构造（**只填 W3A 白名单里已登记的键**）；语义包摘要（按 `bundle_version` 渲染）；历史脱敏（**只留问题**）；**注入防护**：分隔符 + 声明（主）+ `detect_injection` 行为检测（辅，**打标不拒绝**）—— **DoD③** | + 单测 |
| **T3** | `timeexpr.py`：时间表达解析，**N-26 只从语义包取**，不喂模型常识；`campaign` 未结构化必退化 | + 单测 |
| **T4** | `jsonish.py`：JSON 提取（含围栏）+ `validation_digest`（**必须脱 SQL**，N-12/N-17） | + 单测 |
| **T5** | `engine.py`：节点 2/3/5/7/16 + 合并档；**修复 1 次后降级**（**DoD②**）+ **两条降级通道**（同步 sink + 返回对象）；`PlannerPort` 薄包装 | + 单测 |
| **T6** | 门禁（`pytest` 本包 + 全量／`ruff`／`mypy`／`lint-imports`）+ **DoD① 真机小样本延迟实测** | 实测数据 |
| **T7** | `reports/w3b/{PROMPT.md, DELIVERY.md, RELAY.md}` + commit | 交付件 |

**DoD（08 §3.5 原文）**：
① **合并调用后的延迟实测**（`normalize`+`intent`、`plan`+`gen_sql`，见 §16.1）
② JSON 修复 1 次后降级
③ 注入防护（分隔符 + 声明）

## 五、必读清单（精确到章节）

1. 07 §5.3（节点 2/3/5/7/16 的输入输出与判定标准）——你的主干规格。
2. 07 §16.1 + §16.2（**预算语义**：阶段级 P95 分配 + 超预算处置）＋ §16.1 的四条压缩手段。
3. PRD §12.2（模型路由表）+ §6.7（降级链）+ FR-1.6（意图四分类）+ FR-3.1（**必须先输出查询计划**）。
4. 07 §10.2（降级链 / `refuse` 不是 error）、§10.3（修复重试 1 次）、§10.5（出站白名单六项）。
5. 附录 A（契约优先级最高）；**C-01**（`plan_summary` 形状，07 §4.8 行 825）/ **C-03**（`meta.tokens`，07 §4.8 行 827）；
   硬规则 **N-12 / N-17 / N-19 / N-26**（07 §4 的 N 系列表）。
6. `app/core/contracts.py`（`PlannerPort` / `LLMPort` / `SemanticBundlePort`）、`app/core/enums.py`（`DegradedReason` / `ActionTaken` / `RefuseReason`）。
7. `reports/w3a/RELAY.md §给 W3B/W3C`（**调用面与异常语义，照它写**）+ `reports/w3a/DELIVERY.md §已知限制`。
8. `graph/state.py`（你的产物要落进哪些字段：`plan` / `plan_summary` / `degradations`）。

## 六、边界（这些目录归他人，你只能提需求，不得落笔）

| 路径 | 归属 | 你可能的需求 |
|---|---|---|
| `app/llm/**`（含 `prompts/`） | W3A | **任务级超时策略**（本窗口阻断项）、合并档 2 的新资产、`max_tokens` 标定 |
| `app/core/**`（contracts/enums/config） | W0 | `DegradedReason` 补两个值、`PlannerPort` 补入参、`PlanSummary.blocked` 登记 |
| `app/semantics/**` | W2A | 语义包字段/枚举器（`metrics()` / `aliases()` 若需枚举） |
| `graph/**`、`api/**` | W4 | 你不接线；`stage`/事件发射、每请求构造引擎 |
| `app/binding/**` | W3C | 并行走；`l4_score` 同受"预算当硬超时"影响 |

## 七、交付物

- `backend/app/planner/**` + `backend/tests/unit/test_planner_*.py`（**必须全离线**）。
- `backend/reports/w3b/DELIVERY.md`（**DoD 逐条对照 + 门禁实测原样输出 + 已知限制具名登记**）。
- `backend/reports/w3b/RELAY.md`：**逐窗口可粘贴**——§给 W3A／W0／W4／W3C／架构／W3-INT。
- commit：`feat(w3b)` / `docs(w3b)`，只暂存本窗口文件。

## 八、动手前必须"报告现状 + 拿指令"的决策点

| # | 决策点 | 要点 / 风险 |
|---|---|---|
| **Q1** | JSON 提取与 schema 校验的**归属**（W3A 明说"在调用方"） | 确认归你：网关只给字符串。风险：若两边各做一次，白烧一次调用 |
| **Q2** | 修复轮的 **task 归属**：`gen_sql*` 的修复改走 `repair` 任务？ | 走 `repair` 可复用网关的修复资产；**代价**：`repair` 只吃 `error_digest`（N-17），修不了"原文写错"。**已裁：走 `repair`**（`engine.py:616`） |
| **Q3** | 意图取值**不同名**（prompt 让模型出 `query/clarify_needed/out_of_scope/unsafe`，状态机要 `executable/clarify/refuse/open_analysis`） | **已裁：单表映射 `INTENT_MAP`**（`schemas.py:102`）；`open_analysis` **模型不产出** ⇒ 不可达，如实登记 |
| **Q4** | 合并档 1 是否作为**推荐入口** | **已裁：是**（`understand()`），但**必须同时提供不合并的路径**，否则"合并省了多少"无从测量（DoD①） |
| **Q5** | 时间语义从哪来 | **N-26**：只从语义包取（`timeexpr.py`），**禁止**用模型常识补 |
| **Q6** | 降级怎么上报 | **两条通道都给**：同步 sink（W4 转 SSE）+ 返回对象的 `degradations`（W4 塞 state） |

> 完整裁定与"可核对位置"见 `DELIVERY.md §四`（按代码重建，**不逐字复述问答**）。

## 九、本机环境坑（实测，逐条都会浪费你半小时）

1. 一律用 `CommerceQL/.venv/Scripts/python.exe`（系统 Anaconda 3.11 的 pydantic 是 1.x，不合格）。
2. **Bash 工具 PATH 漏 PortableGit/usr\bin** → 每条命令前加
   `export PATH="/c/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:/c/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.2.0/bin:$PATH"`
   （stderr 仍会报 `dirname: command not found`，**无害，exit 0 有效**）。
3. `python -m importlinter.cli` **假绿** → 用 `lint-imports.exe` 控制台脚本。
4. Docker Desktop **不会自启** → 跑 PG/Redis 集成测试前先手动启动；**不启动时用例会如实 skip/error，不计为通过**。
5. `git` 可用；工作区常有并行窗口的未提交在制品 → **提交前只 `git add` 自己的文件**。
6. 时间/事实以**实测**为准（`date`、真库查询），不要凭文档推断状态——上游可能已变，动手前复核。
