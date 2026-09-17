# W3B 交付说明（DELIVERY）—— 阶段 3B · 理解与生成

> 窗口：**W3B**（`app/planner/**`，L3）｜日期：2026-09-17
> 仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`｜分支 `main`
> 逐窗口转述件：同目录 `RELAY.md`（可粘贴）｜任务定义：同目录 `PROMPT.md`
>
> **一句话结论**：`app/planner/**` 6 个模块 + 170 条离线单测全绿、四项门禁全绿；
> **DoD① 部分达成**——合并档 1（`normalize`+`intent`）已实测（**省 ~0.80s**），
> 但 **`plan`/`gen_sql` 在真机上的延迟超 07 §16.1 预算**，且**当前被 W3A 的任务级硬超时掐成 100% 失败**；
> 合并档 2（`plan`+`gen_sql`）**未实现**（跨窗口缺 prompt 资产，需裁决）。

---

## 一、交付物清单（逐文件、可核对）

| 文件 | 行数 | 内容 |
|---|---|---|
| `backend/app/planner/__init__.py` | 5 | 仅包 docstring（阶段 0 纪律：不写业务逻辑） |
| `backend/app/planner/engine.py` | 971 | 引擎：节点 2/3/5/7/16 + `PlannerPort` 落地 + 修复轮 + 降级上报 |
| `backend/app/planner/schemas.py` | 496 | **LLM 输出契约唯一真相**（Pydantic v2，`extra="forbid"` + `frozen`） |
| `backend/app/planner/payloads.py` | 580 | 出站载荷构造 + 语义包摘要 + `detect_injection` + 历史脱敏 |
| `backend/app/planner/timeexpr.py` | 417 | 时间表达解析（N-26：只吃语义包，不吃模型记忆） |
| `backend/app/planner/jsonish.py` | 193 | JSON 提取 + 错误摘要（`validation_digest`，**必须脱 SQL**） |
| `backend/app/planner/errors.py` | 156 | 领域异常（不含 HTTP 语义） |
| **小计** | **2818** | |
| `backend/tests/unit/test_planner_engine.py` | 1087 | 53 用例 |
| `backend/tests/unit/test_planner_payloads.py` | 465 | 44 用例 |
| `backend/tests/unit/test_planner_egress_contract.py` | 446 | 11 用例（**用真网关 + 假上游**） |
| `backend/tests/unit/test_planner_timeexpr.py` | 374 | 43 用例 |
| `backend/tests/unit/test_planner_jsonish.py` | 197 | 19 用例 |
| **小计** | **2569** | **170 用例（全离线）** |

覆盖的 07 §5.3 节点：**2 `normalize`**／**3 `intent`**／**2+3 合并档**／**5 `plan`**／**7 `gen_sql`**（含 L3+ `gen_sql_complex`）／**16 `repair`**。

---

## 二、DoD 逐条对照（DoD 原文 = `docs/08` §3.5 行 231）

> 原文：**「3B 理解与生成」** | `planner/` | ① **合并调用后的延迟实测**（`normalize`+`intent`、`plan`+`gen_sql`，见 §16.1）② JSON 修复 1 次后降级 ③ 注入防护（分隔符 + 声明）

### DoD① 合并调用后的延迟实测 —— ⚠️ **部分达成**（3/4 项实测，1 项未实现）

真机实测，2026-09-17。探针与原始结果（**不属于交付物**，跑完即弃）：

| 探针 | 路径 | 说明 |
|---|---|---|
| v1 | `_w3b_latency_probe.py` → `_w3b_latency_result.json` | **原样**测（不改任何东西） |
| v2 | `_w3b_latency_probe2.py` | **旁路 W3A 任务级硬超时**后测 `plan`/`gen_sql` |
| v3 | `_w3b_latency_probe3.py` → `_w3b_latency_result3.json` | 合并档 vs 未合并档 |

| # | 目标 | 07 预算 | 实测（中位） | 判定 |
|---|---|---|---|---|
| ①-1 | **`normalize`+`intent` 合并档**（`understand()`） | §16.2 **1.2s** | **794ms**（n=3，另见 v1 的 939ms/n=5） | ✅ **达标** |
| ①-2 | 同上·**未合并**对照（`normalize()`+`classify_intent()`） | — | **928ms + 661ms = 1589ms** | — |
| ①-3 | **`plan`** | §16.1 **1.0s** | **2756ms**（n=3） | ❌ **超 1.76s** |
| ①-4 | **`gen_sql`** | §16.1 **1.3s** | **1939ms**（n=3） | ❌ **超 0.64s** |
| ①-5 | **`plan`+`gen_sql` 合并档**（§16.1 手段 2） | 合计分配 2.3s | **未实现** | ⛔ **DoD① 此项未完成** |
| 附 | `gen_sql_complex`（L3+ 思考） | 07 **无**预算 | **43480ms**（n=3） | 仅记录（无契约） |

**合并档 1 的收益实测 = 1589 − 794 = 795ms ≈ 0.80s**（07 §16.1 预期"~0.6s"，实测略优 —— 合并后共享同一段前缀缓存，`cache_hit_ratio≈0.92`）。

🔴 **两条必须说清的前提，否则上表会被读成"planner 慢"**：

1. **①-3/①-4 的数字是旁路 W3A 任务级硬超时之后测的**。**原样跑的结果是 `plan` 0/3、`gen_sql` 0/3 全失败**（`LlmRefused`，耗时恰为 1.0s / 1.3s）——根因在 W3A 的 `router.py`（见 §五-1），**不是** planner 的实现缺陷。旁路后 3/3 全成功 ⇒ 功能路径是通的，慢是慢，但不再失败。
2. **①-5 未实现，且实测证据表明 07 给的触发条件已经成立**。07 §16.1 把手段 2 列为"**备选**（若 1+4 后实测仍超）"——本次实测：采用手段 1+4 后，**`plan`+`gen_sql` 单独就 4.70s，而其分配只有 2.3s**；把 14 阶段串行合计重算，手段 1 只省下 0.60s，**远不足以填平**。⇒ "1+4 后仍超" **成立**，手段 2 该上。但实现它需要一个 `plan_v1`+`gen_sql_v1` 的合并资产（`app/llm/prompts/`，**W3A 独占**）+ 一个新 `LlmTask` 取值 + 一处架构裁决（与"计划先展示给用户看"的 UX 张力，07 §16.1 自己标了）。**本窗口不越界落笔**，列 §五-6 待裁。

**长尾观察（具名登记，不掩盖）**：每个探针进程的**首次**调用出现 12–14s 长尾（probe2-plan 首样本 14096ms、probe3-understand 首样本 11890ms），但 probe1 首次仅 1233ms、probe3-normalize 首次仅 772ms ⇒ **不是稳定的"冷启动代价"**，**成因未定**（上游排队 / 连接建立 / 服务端抖动皆可能）。记此一条是给 W3A/W7 留痕：**若它发生在生产首请求上，会一次性打爆 1.0s 预算 14 倍**。

### DoD② JSON 修复 1 次后降级 —— ✅ **达成**

| 要求 | 证据（用例名，可 `pytest -k` 复核） |
|---|---|
| 首次非法 → 修复 1 次 | `test_extra_key_is_rejected_then_repaired` |
| **有界**，最多 1 次额外调用 | `test_repair_is_bounded_at_one_extra_call`、`test_repair_sql_failure_is_bounded_to_one_call` |
| 修复轮换 task 并携带脱敏摘要 | `test_repair_round_switches_task_and_carries_a_digest` |
| 修复轮**不嵌套** | `test_repair_sql_takes_only_a_digest_and_does_not_nest_repairs` |
| 仍失败 → 降级上报（而非静默） | `TestDegradationPlumbing`：`SqlGenerationUnavailable` 带 `missing_reason_value`，sink 实收事件 |
| 修复**成功不算降级** | `test_a_successful_repair_is_not_a_degradation`（负向对照：成功路径不得发事件） |
| 修复轮 `prompt_version` 取第二次调用 | `test_repair_prompt_version_comes_from_the_second_call`（N-19） |

🔴 **本 DoD 抓出一个真缺陷**：`gen_sql` 的修复轮原本拿首轮的 `GenSqlResult` 去校验 `repair_v1` 的输出，而该资产**要求**输出 `repairable` 键 —— `extra="forbid"` 下它成了"未登记字段"，**整份拒收** ⇒ **`gen_sql` 的修复轮永远不可能成功**。修法 = `_call_validated` 增 `repair_schema` 参数（`engine.py:817`、调用点 `:627`），并把"为什么"写进 docstring（`engine.py:823-833`）。负向对照：删掉 `repair_schema=RepairResult` 那一行 → 3 条用例变红 → 还原 → 变绿。

### DoD③ 注入防护（分隔符 + 声明）—— ✅ **达成**

| 要求 | 证据 |
|---|---|
| **声明**：每个 task 的 `constraints` 都带注入声明 | `test_injection_declaration_is_in_every_task_constraints`（7 个 task 全覆盖） |
| **检测**（辅）：行为性指令 → 记录 + 打标，不直接拒绝 | `detect_injection`（`payloads.py:169`）；`test_injection_flags_instructional_overrides` |
| **不误伤**：正常业务措辞不得判为注入 | `test_normal_business_phrasing_is_not_flagged`（"帮我忽略未支付订单"） |
| **上报形态**：报"命中模式"**而非用户原文**（避免把用户话再抄一遍进日志） | `test_injection_report_carries_the_pattern_not_the_user_text` |
| **真网关下的端到端**：注入 SQL 进 payload 必被拦 | `test_injecting_sql_text_into_a_real_payload_is_rejected`（`LlmEgressViolation`，**0 字节出网**）+ `test_injecting_sql_into_the_error_digest_is_rejected` |

---

## 三、门禁实测输出（2026-09-17，原样粘贴）

```
########## 1) pytest · W3B 本包范围 ##########
170 passed in 1.05s

########## 2) ruff · app/planner + W3B 测试 ##########
All checks passed!

########## 3) mypy · app ##########
Success: no issues found in 102 source files

########## 4) lint-imports（控制台脚本，非 python -m） ##########
Analyzed 145 files, 600 dependencies.
R-DEP-1 分层依赖（只能依赖严格更低层） KEPT
R-DEP-2/N-01 确定性模块与 binding 禁止 import app.llm KEPT
R-DEP-3 obs 内除 audit 外禁止依赖 repo（U-18 代价约束） KEPT
R-DEP-4 retrieval 禁 LLM（refine 唯一豁免，P0 未实现） KEPT
Contracts: 4 kept, 0 broken.
```

**全量 `pytest -q`（同一时刻）**：

```
1 failed, 1395 passed, 55 skipped, 1 warning, 6 errors in 146.32s
```

⚠️ **7 个非通过项（1 failed + 6 errors）全部落在 `tests/integration/test_retrieval_fts_pg.py`**，原因 = 需要真 Postgres 而 **Docker Desktop 未启动**（`ConnectionTimeout`）；55 个 skip 同理（Redis/PG 集成）。**与 W3B 无关**，非本窗口范围，也**不计为通过**。

**全仓 `ruff check .`（同一时刻）**：

```
All checks passed!
```

（此前 W3C 窗口在 `tests/unit/test_binding_service.py` 的 3 条残留已由其自行清理，现全仓干净。）

---

## 四、开工轮决策点（Q 系列）—— 按**代码可核对位置**重建

⚠️ 诚实声明：开工轮的 Q 列表是会话内输入，**未随会话保留逐字原文**。下表按**实现**重建，每行给可核对位置；**不逐字复述问答**，避免转述漂移。

| # | 决策 | 落点（可核对） | 代价 / 风险（已登记） |
|---|---|---|---|
| Q2 | 修复轮的 task 归属：`gen_sql*` 的修复**改走 `repair` 任务** | `engine.py:616`、`jsonish.py:11-23`、`schemas.py` 的 `RepairResult` | 代价：`repair_v1` 只吃 `error_digest`（**N-17 禁回灌失败 SQL**），修不了"原文写错"这类错；故必须带 `repair_schema`（见 §二 DoD② 缺陷） |
| Q3 | 意图取值**单表映射**（模型侧 4 值 → 状态机 4 值） | `schemas.py:102`（`INTENT_MAP`）、`:135-142`（逐条理由） | `unsafe → refuse(pii_blocked)` 是**语义拉伸**（资产说的是"试图越权/改自身行为"，`RefuseReason` 只有 `pii_blocked` 最接近）→ 列 §五-6 待裁 |
| Q? | `$output_schema` 由谁产出 | `payloads.py:16` 起（"W3A ↔ W3B 的接缝，实测确认"） | — |
| Q? | `plan_summary` 形状（C-01：只放摘要、**不含 SQL**） | `schemas.py:326`（`_either_plan_or_blocked`）、`:344`（构造）、`:354`（"唯一的偏离"说明） | 多了一个 `blocked` 布尔 → 列 §五-6 待裁 |
| Q? | 时间语义**只从语义包取**（N-26），不喂模型常识 | `timeexpr.py` 全模块 + `schemas.py` 的 `TimeResolution` | — |
| Q? | 降级**两条通道都给**（同步回调 sink + 返回对象 `degradations`） | `engine.py` 模块 docstring §二 | 回调是**同步**的（阻塞它会吃延迟预算），与 `app.llm.DegradationSink` 同款理由 |

---

## 五、本窗口发现的问题（含跨窗口转述）

### 1. 🔴【**阻断 DoD①**，跨窗口 → W3A】07 的阶段级延迟预算被当成**单次调用硬超时**执行

- **位置**：`app/llm/router.py` `TASK_ROUTES`（`PLAN.timeout_s=1.0`、`GEN_SQL.timeout_s=1.3`）→ `app/llm/client.py:184` `deadline = start + timeout_s`（**硬 deadline**）。
- **语义冲突（实测钉死）**：07 §16.1 的 0.6/1.0/1.3s 是**阶段级 P95 预算分配**；07 §16.2 明写"**若 1.2s 未完成 → 先推 `stage=intent`（不发结论）**占位" ⇒ **超预算是走降级 UX，不是失败**。把它当硬超时，等于把"P95 目标"翻译成"第 1.000 秒必然失败"。
- **实测后果**：`plan` **0/3**、`gen_sql` **0/3** 全 `LlmRefused`（耗时恰为 1.0s/1.3s），**生产上这两条路不可用**；旁路后 **3/3 成功**。
- **W3B 无杠杆**：`LLMPort.call(task, payload, model)` **没有超时入参**（`app/core/contracts.py:279`），超时完全由路由表决定 ⇒ 只能转述，不能自修。
- ⚠️ W3A 已在 `router.py` 文件头（:39-42）登记了**同源的一半**（"07 §16.1 给 `gen_sql` 1.3s 与 PRD §12.2 要求 pro 思考物理冲突"）。**本窗口新增的证据是另一半**：不只是"pro 思考跑不进 1.3s"，而是"**任何** flash 调用都被这 1.0/1.3s 掐死"，即问题范围比 W3A 登记的更大。

### 2. ⚠️【跨窗口 → W3A / W7】`gen_sql_complex` 的 pro 档有 **2/3 概率返回空 content**

probe v1 三次样本：2 次 `LlmEmptyContent from_model=deepseek-v4-pro` → 自动 `switched_to_weak_model`（**降级到 flash，degraded=True**）；1 次 pro 正常返回（41130ms，`reasoning_chars=9341`，3248 输出 token）。⇒ 成功那次**思考了 9341 字符**；失败两次耗时同样 ~41s 却拿不到 content，**最可能是 `max_tokens` 在思考阶段被截断**（`output_tokens_hint=1200` + `THINKING_HEADROOM_TOKENS=2048`）。本窗口**不动** `app/llm`，只登记：**L3+ 路径的真实可用率 ≈ 1/3**。

### 3. ✅ 本窗口自修的两个真缺陷 + 一个测试夹具缺陷（不留白）

| # | 缺陷 | 性质 | 证据 |
|---|---|---|---|
| D1 | `PlannerEngine._emit()` **没有任何调用点**（死代码）⇒ 业务降级事件**从未到达 sink** | **产品缺陷** | 修 = 新增 `_report_and_raise()`（`engine.py:773`，7 个调用点 `:413/466/507/566/630/677/738`）；用例 `TestDegradationPlumbing` 断言 sink **实收**事件 |
| D2 | `gen_sql` 修复轮 schema 错配 ⇒ 修复**永不成功** | **产品缺陷**（最严重） | 见 §二 DoD②；`engine.py:817/627/823-833` |
| D3 | 测试夹具用 `iter([1.0,1.25])` 做 monotonic，组合调用时**迭代器耗尽** | 测试缺陷（非产品） | 改 `itertools.count(0)` |

### 4. 已知限制（**具名登记，不写成"应该没问题"**）

1. 🔴 **引擎实例不得并发**：唯一的可变状态 `_pending` 的生命周期 = 一次公开调用；**同一实例并发跑两次公开方法会串降级事件**。W4 必须**每请求构造一个引擎**（或装配层工厂）；若要单实例并发，`_pending` 得换 `contextvars`。已写进 `engine.py` 模块 docstring §三。
2. **`PlannerPort.generate_sql(plan, ctx, *, candidates)` 端口签名缺"归一化问题"位**，而 `gen_sql_v1.txt` 需要它 ⇒ 本实现从 `plan["normalized_question"]` 取，**缺失时抛契约错误而不是编一个**（`engine.py:729-734`）。这是**端口缺口**，列 §五-6。
3. **`build_plan` 的 `candidates` 参数当前不进 prompt**（`plan_v1.txt` 的 USER 段没有 `$candidates_block` 占位符，实测）⇒ 计划只经 `semantic_summary` 看到**资产级**信息，看不到"本轮候选 Top-N"。已 `del candidates` 显式标注，**不假装用上了**（`engine.py:708-715`）。
4. **`open_analysis` 意图当前不可达**：模型侧 prompt 不产出该值（`schemas.py:38-42`）⇒ FR-1.6 四分类**只落了 3 类**。
5. **`_looks_complex()` 是启发式**（`engine.py:968`），决定走 `gen_sql` 还是 `gen_sql_complex`；阈值未经评测标定。
6. **`DegradedReason` 缺 `understanding_failed` / `sql_generation_failed`**（`app/core/enums.py` 只有 `plan_generation_failed`）⇒ 本窗口复用 `plan_generation_failed` 并在 `detail` 里带 `missing_reason_value`（`errors.py:80`、`:142`）**显式标注"这个值是凑出来的"**。→ W0。
7. **`PlanSummary` 多了一个 `blocked` 布尔**（`schemas.py:354/370`）：C-01 未定义该键，但"计划没出来"与"计划出来但为空"必须可区分。
8. **注入检测是"辅"不是"主"**：主防线是分隔符 + 声明；`detect_injection` **只打标不拒绝**（设计如此）。**已知局限**：不含 `SELECT` 的裸 SQL 片段**检测不到**（`test_known_limit_a_sql_fragment_without_select_is_not_detected` 把它钉成已知限制，而不是假装覆盖）——真正的兜底是网关的白名单断言（W3A，已实测有效）。

### 6. 待架构窗口裁决（**本窗口未自行开号**；下一可用 = `U-65`）

| 候选 | 问题 | 现状 / 影响 |
|---|---|---|
| ① | **07 §16.1 的 `plan` 1.0s / `gen_sql` 1.3s 预算与真机实测差 2.8× / 1.5×** | 实测中位 2756ms / 1939ms（**旁路超时后**）。预算表若不改，P95 契约在这两档**永远不达标** |
| ② | **W3A 把阶段级 P95 预算当单次调用硬超时** | 见 §五-1。**当前 = `plan`/`gen_sql` 100% 失败**。需裁决"预算"的正确用法（软目标 + 超时另给，还是取消任务级超时） |
| ③ | **07 §16.1 压缩手段 2（合并 `plan`+`gen_sql`）的触发条件已成立**，但缺 prompt 资产 + 与"计划先展示"UX 有张力 | 实测：手段 1+4 后 `plan`+`gen_sql` 仍 4.70s vs 分配 2.3s。需裁决是否采纳，以及采纳后 `plan_ready` 事件怎么发 |
| ④ | **`PlannerPort.generate_sql` 缺"归一化问题"入参** | 本窗口用 `plan["normalized_question"]` 约定绕开（W4 需照此传）。扩端口要动 `app/core/contracts.py`（W0） |
| ⑤ | **`DegradedReason` 缺 `understanding_failed` / `sql_generation_failed`** | 本窗口用 `missing_reason_value` 显式标注凑值（不静默） |
| ⑥ | **`unsafe → refuse(pii_blocked)` 是语义拉伸** | 资产语义与 `RefuseReason` 取值集不匹配，见 `schemas.py:139-140` |
| ⑦ | **`PlanSummary.blocked` 是 C-01 之外的额外键** | 需正式登记或换成别的表达 |
| ⑧ | **`gen_sql_complex` 的 pro 档空 content 率 2/3** | 疑 `max_tokens` 在思考阶段截断（W3A 域）。**L3+ 真实可用率 ≈ 1/3** |
| ⑨ | **`open_analysis` 意图不可达** | FR-1.6 四分类实落 3 类 |
| ⑩ | **`_looks_complex` 阈值未标定** | 影响 L0–L2 / L3+ 路由质量，需评测 |

---

## 六、复现指引

```bash
cd CommerceQL/backend
# 1) W3B 本包（离线，1 秒级）
../.venv/Scripts/pytest.exe tests/unit/test_planner_egress_contract.py tests/unit/test_planner_engine.py \
  tests/unit/test_planner_jsonish.py tests/unit/test_planner_payloads.py tests/unit/test_planner_timeexpr.py -q
# 2) 门禁
../.venv/Scripts/ruff.exe check app/planner tests/unit/test_planner_*.py
../.venv/Scripts/mypy.exe app
../.venv/Scripts/lint-imports.exe          # ☠️ 必须控制台脚本；python -m importlinter.cli = 假绿(U-41)
# 3) 真机延迟（需真 key；成本约 ¥0.08/轮，见 §二各表）
../.venv/Scripts/python.exe ../../_w3b_latency_probe.py    # 原样（会看到 plan/gen_sql 0/3 失败）
../.venv/Scripts/python.exe ../../_w3b_latency_probe2.py   # 旁路超时
../.venv/Scripts/python.exe ../../_w3b_latency_probe3.py   # 合并档对比
```

⚠️ 三个探针脚本**留在工作区根目录且未提交**，是**一次性证据**，不是交付物；需要留档请自行移动。

---

## 七、本窗口**没有**做的事（免得被读成"已实现"）

1. **没有**接线（`graph/**`、`api/**` 是 W4 的）：`planner` 目前**没有任何调用方**，节点 2/3/5/7 在图上仍是空的。降级事件目前只到"调用方给的 sink"。
2. **没有**实现合并档 2（`plan`+`gen_sql`）——跨窗口缺 prompt 资产，见 §五-6-③。
3. **没有**动 `app/llm/**`、`app/core/**`、`app/semantics/**` 等任何非本窗口文件；**没有**新增依赖；**没有**自行开号。
4. **没有**做端到端联调（无 `graph` 装配）：DoD① 是**单模块真机实测**，不是链路实测。
