# 【窗口提示词 · 阶段 3A：LLM 网关（W3A）】

> 产出：W2B 窗口（受用户指令）｜日期：2026-09-17｜用途：阶段 3 启动时，把本文件**全文**作为 W3A 窗口的开工上下文。
> 骨架沿用 `reports/w2-int/PROMPT.md` 的收口模板（定位 → 契约与纪律 → 现状 → 任务清单 → 边界 → 决策点 → 交付），
> 但 W3A 是**开发窗口**，不是收口窗口：你**要做功能开发**，且**先行交付**——你不出，W3B/W3C 只能拿桩写。
> 交付目录：`backend/reports/w3a/`（你的 DELIVERY.md / RELAY.md 落这里）。

---

你是 CommerceQL「阶段 3 · LLM 网关」窗口（**W3A**）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 `main`，远程 `fenxidapao/CommerceQL`。

【开工方式】**先输出执行计划，等我确认后再动手**。需求不明确先提问，不要猜。
【红线】不伪造实现；不把"未接线/未联调"报告成"已实现"；跑不通就说卡在哪；决策点先"报告现状"再等指令，不自行扩大范围。

## 一、你的定位

- 独占范围：**`backend/app/llm/**`**（含 `prompts/` 子目录，见 08 §4.1）。当前该目录**只有 `__init__.py`（仅 docstring）**——你是从零建包。
- 你是**全项目唯一的 LLM 出站通道**：W3B（`planner/`，normalize/intent/plan/gen_sql）、W3C（`binding/` 的 L4 精排）、`retrieval/refine.py`（P0 未实现）、`present`（图表 spec + 结论）**全部经你的端口调用**。
- **先行理由**（08 §3.5 原文）："3A 不做完，3B/3C 只能拿桩写——最后还要返工"。因此你的**第一阶段目标**是尽快给出**可调用的端口实现**（哪怕降级路径先行），但**桩必须诚实**：不得返回伪造 SQL / 伪造结论。
- 你**不是**收口窗口：阶段 3 的收口（汇总/接线/全量门禁/裁决上呈）由后续 W3-INT 承担，你只负责本包交付 + 转述件。

## 二、契约与纪律

- 契约优先级：**附录 A(02) > PRD(01) > 06 UIUX > 07 TDD(v0.9) > 08 实施计划(v1.2)**。
- 端口已冻结（**W0 的 `app/core/contracts.py`，你不得改**）：
  - `LLMPort`：`async def call(task: str, payload: Mapping[str, Any], model: str) -> LLMResponse`｜`def estimate_cost(payload: Mapping[str, Any]) -> Decimal`
  - `LLMResponse`：`text / model / prompt_version / tokens / cost_cny`（**必须携带版本字段**，否则不满足 N-19）
  - `TokenUsage`：`input / output / cache_hit / total`
  - 缺口即提需求（见 §八 Q 系列），**不得私改 core**。
- 机器化护栏（`.importlinter`，W0 落笔）：
  - `R-DEP-2/N-01`：`app.core/binding/guard/exec/mask/cache/semantics/auth/obs/repo` **禁** `import app.llm`；
  - `R-DEP-1`：你把 `app.llm` 视作 **L1**——可 import `app.core`、`app.repo`；**不得** import 任何 L2/L3/L4/L5（`binding/guard/exec/mask/cache/planner/retrieval/present/graph/api`）。
- 动手前先 `git status` + `git diff --stat` 判"是否别人的在制品"；**同一文件多处 `Edit` 必须串行改 + grep 复核**（并行发会静默丢编辑，本仓库已多次踩到）。
- 提交：`feat(w3a)` / `docs(w3a)`，只暂存本窗口文件；**未获明确指令不 push**（仓库默认 no-push 习惯）。
- 编号纪律：**不得自行开号**。新问题列"待架构窗口分配"，下一可用号 = **`U-65`**（07 §4.8 登记表是唯一权威，当前快照：W2B `U-57~61`／W2C `U-62~64` 已占）。

## 三、现状盘点（**2026-09-17 实测，非转述**）

| # | 事实 | 位置/证据 |
|---|---|---|
| 1 | `app/llm/` 只有 `__init__.py`（docstring："L1｜归属窗口：W3A"）；`prompts/` 目录**不存在** | `backend/app/llm/` 实测 |
| 2 | 目录布局**已由 07 指定**：`client.py`（OpenAI 兼容 + 并发信号量 + 退避）/ `router.py`（模型路由决策）/ `budget.py`（成本计量 + 预算熔断）/ `prompts/`（版本化 prompt，N-19）/ `egress_guard.py`（出站脱敏，N-12） | 07 L688–693 |
| 3 | config **已有**键：`DEEPSEEK_API_KEY`（**必填** `SecretStr`）/ `DEEPSEEK_BASE_URL=https://api.deepseek.com` / `LLM_MODEL_FAST=deepseek-flash` / `LLM_MODEL_STRONG=deepseek-v4-pro` / `LLM_TIMEOUT_SECONDS=60` / `LLM_MAX_CONCURRENCY=50` / `LLM_MAX_RETRIES=3` / `LLM_SEMAPHORE_FLASH=8` / `LLM_SEMAPHORE_PRO=2` / `LLM_CIRCUIT_FAILS=5` / `LLM_CIRCUIT_OPEN_S=30` / `DAILY_BUDGET_CNY=100` / `BUDGET_ALERT_RATIO=0.8` | `app/core/config.py` |
| 4 | ⚠️ **两处 config 与 07 不一致，需报告现状后再定**：`LLM_TIMEOUT_SECONDS=60` vs 07 §10.2 的**单次 15s(flash)/45s(pro)**；`LLM_MAX_CONCURRENCY=50` vs 07 §10.1 的**按模型 8/2** | 同上 + 07 L2025–2047 |
| 5 | 依赖白名单**已备好你的工具**：`httpx>=0.27`（出站）、**`tenacity>=9.0`**（退避）、**`tiktoken>=0.7`**（token 计量/成本估算）、**`respx>=0.21`**（测试拦截 + 录制 outbound payload）。**没有 `openai` SDK** | `backend/pyproject.toml` |
| 6 | 🔴 **`app.cost_ledger` 表不存在**：07 §12.3 有列定义（`entry_id`(PK)/`task_id`/`tenant_id`/`user_id`/`model`/`input_tokens`/`output_tokens`/`cache_hit_tokens`/`cost_cny`…，保留 13 个月），但**迁移 0001/0002/0003 均未建**，真库 `app` schema 表清单里没有它 | 07 L2299/L2383；`app/repo/migrations/versions/*`；真库实测 |
| 7 | 🔴 `app/cache/keys.py` **没有预算/成本相关的键构造**（现有 16 个：`active_version`/`semantic_retrieval`/`semantic_few_shot`/`embedding`/`session_plan`/`clarify_context`/`idempotency`/`event_buffer`/`result_set`/`rate_limit`/`rate_limit_tenant`/`session_lock`/`jittered_ttl`…） | 实测 `grep '^def '` |
| 8 | 🔴 `deploy/.env` **没有 `DEEPSEEK_API_KEY`** → 真实调用跑不了；而 `config` 该字段**必填** → 任何 import settings 的路径无 key 即 fail-fast。⇒ **测试必须全离线**（`respx` 拦截 + 固定响应）；真机联调为**可选**步骤并标 UNVERIFIED | `deploy/.env` 实测 |
| 9 | 模型 ID 是真实的：`deepseek-flash`(=DeepSeek-V4.1-Flash) / `deepseek-v4-pro`(=DeepSeek-V4-Pro-0813)，OpenAI 兼容；`deepseek-chat`/`deepseek-reasoner` **已退役**；**两模型默认开思考模式（`thinking`）**，PRD §12.2 路由表指定"任务→模型→思考位" | PRD §12.1/§12.2 |
| 10 | 任务级延迟预算**已由 07 §16.1 给出**（你的调用必须活在这些预算里）：`normalize` 0.6s／`intent` 0.6s／**精筛 0.8s**／`plan` 1.0s／`gen_sql` 1.3s／`present` 1.5s；首字节预算 §16.2 = `normalize+intent` 合并后 **1.2s** | 07 §16.1/§16.2 |
| 11 | 429/5xx 的 `Retry-After` **已由架构裁定**（07 §14.4.1）：`LLM_CONCURRENCY_EXCEEDED`=**5s**、`LLM_UPSTREAM_ERROR`=**30s**；但 **W0 尚未落码**——`app/core/enums.py:349-350` 现仍为 `2`/`5` | 07 L2724–2725 vs enums 实测 |
| 12 | 上游余量：`pytest` 全量基线已可用（阶段 2 收口后本机全绿），`lint-imports` 用**控制台脚本**（`python -m importlinter.cli` 是假绿） | `reports/w2-int/DELIVERY.md` |

## 四、任务清单（按序；DoD 映射见括注 = 08 §3.5）

| 批 | 内容 | 产出 |
|---|---|---|
| **T0** | 环境与前置自证：venv 内 `import httpx/tenacity/tiktoken/respx` 实测；`git status` 判在制品；实测"无 `DEEPSEEK_API_KEY` 时 settings 的行为"（**只记录，不改 config**）；确认 `.importlinter` 现有 4 条契约与本包关系 | 自证记录进 RELAY |
| **T1** | `egress_guard.py`：**字段白名单**（N-12，白名单而非黑名单）——payload 由**受控 dataclass** 构造，序列化只接受已登记字段；新增字段必须显式登记。测试：`respx` 捕获**录制的 outbound payload**，断言不含任何结果集/明细键名与值（**DoD③**） | + 单测（离线） |
| **T2** | `prompts/`：`{name}_v{n}.jinja` 或 `{name}_v{n}.txt`（模板引擎见 §八 Q5）；加载器返回 `(text, prompt_version, content_hash)`；**前缀缓存布局**：稳定前缀（系统角色 → 语义包摘要（按 `bundle_version` 冻结）→ 方言说明 → 输出 JSON Schema）→ 变化后缀（few-shot → 归一化问题 → 约束提示）；四条硬规则（**DoD④**：稳定前置、前缀禁请求级变量、前缀禁会话历史、命中率埋点）+ `prompt_version` 必录（**DoD⑤**/N-19） | + 单测 |
| **T3** | `client.py` + `router.py`：按模型 `asyncio.Semaphore`（**并发非 QPS**，取 07 的 8/2——见 Q2）；单次超时（15s/45s，**并按 07 §16.1 的任务预算派生**，见 Q3）；429 → 指数退避 **0.5/1/2s + jitter，最多 3 次**；连续 **5** 次失败 → **开路 30s** + 半开探测 1 次；信号量等待上限 **20s**（超时 → `degraded(llm_concurrency_exceeded, reduced_candidates)`）；**降级链** `pro → flash → 模板 → 拒答`，**每一级必发 `degraded`**（N-21），`action_taken` = `switched_to_weak_model`/`template_only`，模板无命中走 **`refuse`（不是 error）**（**DoD①②**） | + 单测（离线，用 fake transport + 假时钟） |
| **T4** | `budget.py`：`tiktoken` 估算 + 计价（按 **PRD §12.3** 官方价；**高峰定义 = 北京时间工作日 09:00–12:00 与 14:00–18:00**；**TCO 一律按高峰价**）；预算层级 = 租户日预算 + 全局日预算（`DAILY_BUDGET_CNY`）；**80% 告警 / 100% 硬熔断**；熔断后新请求走**模板 + 降级**并在 `meta` 标注；**前置估算**：接近预算时自动降为单路（`action_taken=reduced_candidates`）；**计量 sink**：见 Q1（`cost_ledger` 表缺，**不得**自己写 migration） | + 单测 |
| **T5** | 门面（`__init__.py` 导出 + `LLMPort` 实现）：`task` → (模型, 思考位) 路由表**来源 = PRD §12.2**，集中一处（见 Q4）；`call()` 汇总 T1–T4 全链；错误码映射对齐 07 §14.2 的 **F2（429→`LLM_CONCURRENCY_EXCEEDED`）/F3（5xx→`LLM_UPSTREAM_ERROR`）**；`estimate_cost()` 为 pre-flight 估算 | 端口实现 |
| **T6** | 测试与交付：单测全离线 + DoD 逐条证据（含负向对照：注入→必红→还原→必绿，并看清红的确实是目标断言）+ 门禁（`pytest` 本包范围／`ruff check .`／`mypy app`／`lint-imports`）+ `reports/w3a/{DELIVERY.md, RELAY.md}` + commit | 交付件 |

**DoD（08 §3.5，逐条落地）**：① 按模型 `asyncio.Semaphore`（并发非 QPS）② 退避 / 熔断 / 预算熔断 ③ **出站白名单断言：录制 payload 不含任何明细键与值（N-12）** ④ 前缀缓存布局（稳定内容前置）⑤ `prompt_version` 必录（N-19）。

## 五、必读清单（**精确到章节**）

1. 07 §10 全章（§10.1 并发模型 / §10.2 超时熔断降级链 / §10.3 Prompt 资产工程 / §10.4 成本计量与预算熔断 / §10.5 出站脱敏）——你的主干规格。
2. 07 §16.1 + §16.2（任务级延迟预算与首字节预算——决定你的超时策略）＋ §14.2 的 F2/F3 行（429/5xx 出口）＋ §14.4.1（`Retry-After` 推导）。
3. 07 L688–693（`llm/` 目录布局）+ §12.3（`cost_ledger` 列定义与保留期）。
4. PRD **§12.1–§12.3**（模型 ID 与能力、**§12.2 模型路由表**、官方价与高峰定义、成本模型）——路由与计价的权威。
5. 附录 D §D.2.1（依赖清单）/ §D.3（环境变量）——与 `config.py` 的键对齐。
6. `app/core/contracts.py`（`LLMPort`/`LLMResponse`/`TokenUsage`）、`app/core/enums.py`（`ErrorCode`/`RetryableTier`/`DegradedReason`/`ActionTaken`/`RETRY_AFTER_DEFAULT_S`）、`.importlinter`（R-DEP-1/2/4）。
7. `reports/w2-int/{DELIVERY.md,RELAY.md}`（阶段 2 收口的实测基线与你可能踩到的共用文件状态）。

## 六、边界（**这些目录归他人，你只能提需求，不得落笔**）

| 路径 | 归属 | 你可能的需求 |
|---|---|---|
| `app/core/**`（contracts/enums/config/errors） | W0 | 端口字段扩充、`Retry-After` 落码、model/thinking 枚举 |
| `app/cache/keys.py` | W0 | 预算计数/成本键（若选 Redis 载体） |
| `app/repo/**` + `migrations/**` | W1B | `cost_ledger` 表 + 写入 API |
| `pyproject.toml` / `.importlinter` / `.github/**` | W0 | 新增依赖须走 ADR-20（**别自己加**） |
| `app/obs/**`（audit.py 归 W1B） | W0/W1B | 若你要写成本相关审计/指标 |
| `graph/**`、`api/**` | W4 | 你不接线；`stage`/事件的发射归 W4 |

## 七、交付物

- `backend/app/llm/**`（含 `prompts/`）+ 对应测试（`backend/tests/unit/test_llm_*.py`，可选 `tests/integration/`）。
- `backend/reports/w3a/DELIVERY.md`（DoD 逐条对照 + 门禁**实测**输出 + 已知限制具名登记）。
- `backend/reports/w3a/RELAY.md`：**逐窗口可粘贴**的转述件——§给 W0（`Retry-After` 落码 / keys 需求 / 依赖需求）、§给 W1B（`cost_ledger`）、§给 W3B/W3C（调用面，见 §九）、§给架构（待分配编号）、§给 W3-INT（收口需知）。
- commit：`feat(w3a)` / `docs(w3a)`，只暂存本窗口文件，**不 push**（除非明确指令）。

## 八、动手前必须"报告现状 + 拿指令"的 5 个决策点（**我不替你选**，下列为建议）

| # | 决策点 | 我的建议与风险 |
|---|---|---|
| **Q1** | 🔴 `cost_ledger` 表缺失（迁移 0001–0003 均无）——计量怎么落地？ | 建议 **(a) 先在 `llm/` 内定义 sink 注入点（Protocol），配内存/假实现跑通计量与预算逻辑**，同时向 W1B 出需求（表 + 写入 API），**不得**自建迁移、**不得**报"已落库"。风险：如果不做 (a) 而等表，W3B/W3C 会被一张表卡住 |
| **Q2** | `LLM_MAX_CONCURRENCY=50` 与 07 的按模型 8/2 是什么关系？ | 建议解读为"全局上限"、按模型信号量仍取 **8/2**（07 §10.1 是权威），并在 DELIVERY 写明该解读；风险：若 50 是别的语义（如上游真实并发上限），你的解读会掩盖一个配置缺陷 —— 所以**先报告再动** |
| **Q3** | 单次超时用 `LLM_TIMEOUT_SECONDS=60` 还是 07 的 15s/45s？ | 建议**以 07 为准（15s/45s）**，并**按 §16.1 任务预算派生更短的 task 级超时**（否则 15s 兜底会直接把 P95 预算打爆：`gen_sql` 预算只有 1.3s）；风险：任务级超时过紧会推高"超时→降级"比例，需在 RELAY 如实登记实测超时率 |
| **Q4** | 任务→(模型, 思考位) 路由表落点？ | 建议集中在 `llm/router.py` 常量表（来源写明 PRD §12.2），config 只提供模型名；风险：若后续要热改路由，常量需重发版——P0 可接受，但**要写明代价** |
| **Q5** | prompt 模板引擎：07 §10.3 写 `{jinja|txt}`，但依赖白名单**没有 jinja2** | 建议用**标准库**（`string.Template` / `str.format`）或纯文本占位；若要 jinja2，须请 W0 走 ADR-20 加依赖——**别自己加** |

## 九、交接给 W3B / W3C 的调用面（你交付后，他们照此写）

- 调用：`port.call(task, payload, model) -> LLMResponse`；`task` 取值 = PRD §12.2 的 7 类（意图分类 / 问题归一化改写 / 候选筛选精筛 / SQL 生成 L0–L2 / SQL 生成 L3+ / 有界纠错 / 图表 spec + 结论）+ **L4 打分器**（PRD §6.3.1：`deepseek-flash` 非思考）。
- 出参必带：`text`（JSON 字符串）／`model`／`prompt_version`／`tokens{input,output,cache_hit,total}`／`cost_cny` —— 这四个是你对 N-19 与 `meta.tokens`（C-03）的承诺。
- 降级语义**必须原样透传**给调用方与编排层：`degraded + action_taken`（`switched_to_weak_model` / `template_only` / `reduced_candidates`）；模板无命中 = **`refuse`**（产品结论），**不是 error**。
- 你**不负责**：JSON schema 校验与"修复重试 1 次"的**归属**（07 §10.3 写在 prompt 工程节，但校验 schema 在调用方）→ 开工后**与 W3B/W3C 对齐并在 RELAY 登记归属**，不要两边各做一次。
- 你**不负责**：SSE 事件发射、`stage` 推进、审计写入编排（W4/W1B）。

## 十、本机环境坑（实测，逐条都会浪费你半小时）

1. 一律用 `CommerceQL/.venv/Scripts/python.exe`（系统 Anaconda 3.11 的 pydantic 是 1.x，不合格）。
2. **PowerShell 工具会吞 stdout** → 命令输出 `Out-File -Encoding utf8` 落临时文件再 `Read`。
3. **Bash 工具残缺**：`grep`/`head`/`tail`/`ls`/`dirname` 时好时坏（PortableGit shim 问题）→ 扫描用 Grep/Read 工具，别赌内置命令。
4. `python -m importlinter.cli` **假绿**（无输出 exit 0）→ 用 `lint-imports` 控制台脚本。
5. Docker Desktop **不会自启**：跑 PG/Redis 相关测试前先手动启动（`AppData\Local\Programs\DockerDesktop\Docker Desktop.exe`），compose 栈会自恢复，`127.0.0.1:5432` 约 30s 后可用。
6. 集成测试需要真 PG 时的 DSN 注入惯例：环境变量（如 `RETRIEVAL_TEST_PG_DSN`）优先；dev compose 的库是 `ecom`，**`app_rw` 无 DDL 权限**（建表/建 schema 需超管 DSN），缺权时用例**如实 skip**，不伪装绿。
7. `git` 可用；工作区常有并行窗口的未提交在制品 → **提交前只 `git add` 自己的文件**。
8. 时间/事实以实测为准（`date`、真库查询），不要凭文档推断状态（本文件 §三 的每一条都是实测的，但**上游可能已变**——动手前复核）。
