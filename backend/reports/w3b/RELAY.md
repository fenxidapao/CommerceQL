# W3B 转述件（RELAY）—— 逐窗口可粘贴

> 窗口：**W3B**（阶段 3B · 理解与生成，`app/planner/**`）｜日期：2026-09-17
> 细节与证据：`reports/w3b/DELIVERY.md`。本文只写**对方需要照做/照写的东西**。
> **本窗口未自行开号**：新问题列在 §给架构，下一可用号 = `U-65`。
> ⚠️ 阅读顺序建议：**§给 W3A 第 1 条是阻断项**（不修则 `plan`/`gen_sql` 生产不可用）。

---

## §给 W3A（`app/llm/**`）—— 一条阻断 + 两条登记

### 1. 🔴 **阻断项**：任务级预算被当成"单次调用硬超时"，把 `plan`/`gen_sql` 掐成 100% 失败

**实测（2026-09-17，真 key，本窗口的 planner 走你的网关）**：

| task | 原样跑 | 结果 | 旁路 `effective_timeout_s` 后 |
|---|---|---|---|
| `normalize_intent` | 5/5 ok，中位 939ms | ✅ | — |
| **`plan`** | **0/3**，全 `LlmRefused`，耗时恰 **1.0s** | ❌ | **3/3 ok**，中位 **2756ms** |
| **`gen_sql`** | **0/3**，全 `LlmRefused`，耗时恰 **1.3s** | ❌ | **3/3 ok**，中位 **1939ms** |

**根因链（已逐行核实）**：`router.TASK_ROUTES[PLAN].timeout_s=1.0` / `[GEN_SQL].timeout_s=1.3`（`router.py:176/181`）
→ `__init__.py:417` `timeout_s=effective_timeout_s(route, model_key)`（`router.py:247` 直接返回 `route.timeout_s`）
→ `client.py:184` `deadline = start + timeout_s`，`:220` 到点即 `LlmTimeout` → 降级链耗尽 → `LlmRefused`。

**语义问题（这是本条的**关键**，不是"调大一点"那么简单）**：
07 §16.1 的 0.6/1.0/1.3s 是**阶段级 P95 预算分配**；07 §16.2 原文写的是
"**若 1.2s 未完成 → 先推 `stage=intent`（不发结论）**占位" —— **超预算的正确处置是降级 UX，不是失败**。
把预算值直接当硬 deadline，等于把"P95 目标"翻译成"第 1.000 秒必然失败"。

⚠️ **你文件头 `router.py:39-42` 已登记了同源的一半**（"07 §16.1 的 `gen_sql` 1.3s 与 PRD §12.2 要求 pro 思考物理冲突"）。
**本窗口要补的是另一半**：不只是"pro 思考跑不进 1.3s"，而是**任何 flash 调用都被这 1.0/1.3s 掐死** ——
**问题范围比已登记的更大**，且它**在当前配置下就是 100% 失败的确定性缺陷**，不只是"超 P95"。

**W3B 无杠杆（所以只能转述）**：`LLMPort.call(task, payload, model)`（`app/core/contracts.py:279`）
**没有超时入参** ⇒ 调用方无从调整。

**请 W3A 裁一件事**（本窗口不越界改你的文件）：任务级预算是
(a) **软目标**（超了照跑，由上层 UX 兜底）= 需要把 `timeout_s` 与"传输 deadline"解耦，或整体改用 `MODEL_HARD_TIMEOUT_S`；
(b) 还是**保留硬超时但把值调大到实测量级**（`plan` ≥ 3s、`gen_sql` ≥ 2.5s）？
无论选哪个，**07 §16.1 的 `plan` 1.0s / `gen_sql` 1.3s 都已被真机实测证伪**（差 2.8× / 1.5×），需要同步 §给架构。

### 2. ⚠️ 登记：`gen_sql_complex` 的 pro 档 **2/3 概率返回空 content**

真机 3 样本：2 次 `LlmEmptyContent from_model=deepseek-v4-pro` → 自动 `switched_to_weak_model`
（**降到 flash，`degraded=True`**）；1 次正常（41130ms，`reasoning_chars=9341`，3248 输出 token）。
成功那次**思考了 9341 字符**；失败两次同样耗时 ~41s 却拿不到 content ⇒
**最可能是 `max_tokens` 在思考阶段被截断**（`output_tokens_hint=1200` + `THINKING_HEADROOM_TOKENS=2048`）。
⇒ **L3+ 路径的真实可用率 ≈ 1/3**，且 `gen_sql_complex` 的 `timeout_s=None` → 吃满 `STRONG` 的 45s 上限（实测 43–45s）。
**本窗口不动 `app/llm`**，仅登记；请评估 `max_tokens` 与 `THINKING_HEADROOM_TOKENS` 的标定。

### 3. 需求（**跨窗口，我落不了笔**）：请提供一个 `plan`+`gen_sql` 的**合并档资产**

07 §16.1 压缩手段 2 = "合并 `plan` + `gen_sql` 为一次调用（一次输出结构化计划 + SQL）"，被标为"**备选**（若 1+4 后实测仍超）"。
**本次实测证明触发条件已成立**：采用手段 1（合并 `normalize`+`intent`，省 0.80s）后，**`plan`+`gen_sql` 单独仍是 4.70s，而其分配只有 2.3s** —— 手段 1 省下的 0.60s **远不足以填平**。
但实现它需要：① 一个新资产（如 `plan_gen_sql_v1.txt`，存量在你目录）；② 一个 `LlmTask` 新取值（`LlmTask` 是你 10 值的契约表）。**这两处都在你手上**。
⇒ 请先把 **07 §16.1 的手段 2 触发条件已成立** 这条转给架构拿裁决（含 UX 张力：合并后"计划先展示给用户看"怎么办、`plan_ready` 事件怎么发）；裁决后由你出资产、我在 `engine.py` 侧接。

### 4. 顺带确认两条你已验证的行为（本窗口实测复现，非新问题）

- **前缀缓存确实生效**：稳定前缀部分 `cache_hit_ratio` 稳定在 **0.91–0.95**（`input_tokens≈2900–3200`，`cache_hit_tokens≈2700–3100`）。**DoD④ 在真机上成立**。
- **`e2e` 冷启动长尾**：见 DELIVERY §二"长尾观察"（首次调用 12–14s，但**不稳定**，probe1 首次仅 1.2s）⇒ **不到位断言"冷启动代价"**，只请 W3A/W7 留痕。

---

## §给 W0（`app/core/**`、`pyproject.toml`、`.importlinter`）

1. **`DegradedReason` 缺两个值**（`app/core/enums.py:437-444` 现有 8 个：`cost_too_high` / `llm_unavailable` / `llm_concurrency_exceeded` / `latency_exceeded` / `embedding_unavailable` / `plan_generation_failed` / `present_failed` / `cache_fallback`）：
   缺 **`understanding_failed`**（节点 2/3 失败）与 **`sql_generation_failed`**（节点 7/16 失败）。
   现状：本窗口复用 `plan_generation_failed`，并在 `detail` 里带 `missing_reason_value`
   （`errors.py:80` 填 `understanding_failed`、`:142` 填 `sql_generation_failed`）——
   **显式标注"这个值是凑出来的"**，不静默。请裁决是否补值（本窗口**未改 core**）。
2. **`PlannerPort.generate_sql` 缺"归一化问题"入参**（`app/core/contracts.py:427-429`）：
   `async def generate_sql(self, plan, ctx, *, candidates) -> Mapping` —— 而 `gen_sql_v1.txt` 的 USER 段**需要**归一化问题。
   现状：本窗口约定从 `plan["normalized_question"]` 取（`engine.py:729`），**缺失时抛契约错误而不是编一个**。
   ⇒ 若扩端口请扩这一位；若不扩，请把它写成**正式约定**（W4 照传）。**本窗口未改 core**。
3. **`PlanSummary` 需要正式登记一个 `blocked` 布尔**（C-01 未定义）：用于区分"计划没出来"与"计划出来但为空"。本窗口已加并标注为"唯一的偏离"（`schemas.py:354/370`）。
4. 🔴 **`Retry-After` 仍是 2/5**（W3A 已提，本窗口**未复核**，仅转述以免漏）：07 §14.4.1 裁定 `LLM_CONCURRENCY_EXCEEDED`=5s / `LLM_UPSTREAM_ERROR`=30s。
5. 本窗口**未新增依赖**、**未改 `pyproject.toml`/`.importlinter`**、**未开号**。

---

## §给 W4（`graph/**`、`api/**`，接线）

### 1. 🔴 `planner` 目前**零调用方** —— 不接线，节点 2/3/5/7 在图上就是空的

`app/planner` 已可调用，但**没有任何生产装配**；`build_plan`/`generate_sql` 的降级事件、`refuse` 语义**都不会自己出现**。

### 2. 装配：**每个请求构造一个引擎实例**（硬约束）

```python
from app.core.clock import Clock
from app.planner.engine import PlannerEngine

engine = PlannerEngine(llm=<LLMPort 实例>, semantics=<SemanticBundlePort>, clock=Clock(bundle.time_semantics()),
                       degradation=<你的 sink>)   # ← 每请求一个
```
🔴 **不得跨请求复用同一实例**：引擎唯一的可变状态 `_pending`（本次调用的降级累积）生命周期 = 一次公开方法调用，
**并发复用会串降级事件**（`engine.py` 模块 docstring §三）。若要单实例并发，需先把 `_pending` 换 `contextvars`（**尚未做**）。

### 3. 侧信道：**两条降级通道都要接**（缺一条就有可见性缺口）

```python
from app.planner.engine import PlannerDegradationSink, PlannerEngine   # 端口 + 引擎
from app.planner.schemas import DegradedNote                            # ⚠️ 事件类型在 schemas，不在 engine

class SsePlannerSink:                       # 你实现，接 EventEmitterPort
    def on_degraded(self, note: DegradedNote) -> None:     # ⚠️ 同步方法
        queue.put_nowait(("degraded", {...}))
```
- 通道 ①：`PlannerEngine(degradation=<sink>)`，**同步回调**（在 `call()` 的同步段被调用；阻塞它会直接吃延迟预算）。
- 通道 ②：每个 outcome 都带 `degradations`（可直接塞 `GraphState.degradations[]`）。
- ☠️ **禁止在回调里 `asyncio.run(...)`**；你的 `emit` 若是 async，请自行做 sync→async 桥接（`Queue.put_nowait` / `loop.call_soon_threadsafe`）。

### 4. 入参形状（**端口签名缺位，靠约定补**）

```python
plan = await engine.build_plan(question, candidates, ctx)      # 返回 state 形状的 Mapping，含 normalized_question
sql  = await engine.generate_sql(plan, ctx, candidates=n)      # 🔴 plan 里**必须**带 normalized_question
```
- 🔴 `generate_sql` **从 `plan["normalized_question"]` 取问题**；缺失 → **抛 `PlannerError`（不是一个"编出来的问题"）**。
  所以 `build_plan` 的返回**必须原样往下传**，别把它拆散重组（拆散容易丢掉这一位）。
- 若你走**富方法**（`plan_for` / `sql_for`），入参是显式的 `normalized_question=` 关键字，不存在这个坑。
- `build_plan` 的 `candidates` 参数**当前不进 prompt**（`EgressPayload.candidates` 在 `plan_v1` 里没有占位符）——传了不报错，但**没有效果**，别据此以为"计划看到了候选"。

### 5. 异常语义（**与网关那套一致，别自己包一层**）

| 异常 | 你该怎么做 |
|---|---|
| `UnderstandUnavailable` / `PlanUnavailable` / `SqlGenerationUnavailable` | 业务降级 → 走 07 §14.2 的降级出口（模板 / 澄清 / 拒答），**并带上 `.detail`**（含 `missing_reason_value`） |
| `LlmRefused` | **产品终态 `refuse`，不是 error** —— **原样上抛，不要捕获**（它的 `default_code is None`）。引擎内部**刻意不捕获任何 `LlmError`**，连兜底 `except` 都不写 |
| `PlannerError`（其它） | 契约错误 → 上抛 |

⚠️ 若你在 `graph` 层写 `except PlannerError`，**必须先把 `LlmRefused` 分流出去**，否则会把"产品结论"变成"一次业务降级"。

### 6. 与 `GraphState` 的字段对应

`plan` / `plan_summary` 的**真类型由 W3B 定义**（`app/planner/schemas.py`；`graph/state.py` 里此前是 `OpaquePayload` 占位，见 U-24）。
本窗口的 state 载荷 = `PlanOutcome.state_payload()` / `SqlOutcome.state_payload()`（含 `normalized_question`、`plan`、`plan_summary`、`candidates`、`degradations`）——**以这两个方法为准**，不要把 `schemas.Plan` 直接当 state 字段。

---

## §给 W3C（`app/binding/**`）—— 两句话

1. **无接口冲突**：`planner` 与 `binding` 不互相调用（都在 `planner`→`binding` 的下游方向之外；`binding` 是 L2，`planner` 是 L3）。你拿 `LLMPort` 实例的纪律（**禁 `import app.llm`**）与 `planner`（L3，**可以** import）不同，别照抄。
2. **共享的 `l4_score` 任务**：你在 `binding/l4.py` 调的 `l4_score`（07 §6.8.2 方案 C，`timeout_s=0.8`）**与本窗口无关**；但**同一条"任务级预算被当硬超时"的坑同样罩着它**（见 §给 W3A-1）——0.8s 对 flash 是一次完整往返的**下限**，你那路若实测也 0/3，根因是同一个。

---

## §给架构窗口（待分配编号；下一可用 = `U-65`）

按 07 §4.8 纪律，本窗口**未自行开号**。以下 10 项请分配编号并裁决（① 与 ② 互为因果，建议合并裁）：

| 候选 | 问题 | 现状 / 影响 | 证据 |
|---|---|---|---|
| ① | **07 §16.1 的 `plan` 1.0s / `gen_sql` 1.3s 预算被真机实测证伪** | 实测中位 **2756ms / 1939ms**（旁路超时后）= 超 2.8× / 1.5× | `_w3b_latency_result*` |
| ② | **"阶段级 P95 预算"被实现成"单次调用硬超时"** | 07 §16.2 明写超预算应"先推占位符" ⇒ 当前实现与 07 语义相反；**后果：`plan`/`gen_sql` 100% 失败** | DELIVERY §五-1 |
| ③ | **07 §16.1 压缩手段 2（合并 `plan`+`gen_sql`）的触发条件已成立**，但缺资产 + 与"计划先展示"UX 有张力 | 手段 1+4 后 `plan`+`gen_sql` 仍 **4.70s** vs 分配 **2.3s** | DELIVERY §二 DoD① |
| ④ | **`PlannerPort.generate_sql` 缺"归一化问题"入参** | 本窗口用 `plan["normalized_question"]` 约定绕开；扩端口要动 W0 的 core | `engine.py:729` |
| ⑤ | **`DegradedReason` 缺 `understanding_failed` / `sql_generation_failed`** | 本窗口用 `missing_reason_value` 显式标注凑值 | `errors.py:80/142` |
| ⑥ | **`unsafe → refuse(pii_blocked)` 是语义拉伸** | 资产语义（"试图越权/改自身行为"）与 `RefuseReason` 取值集不匹配 | `schemas.py:139-140` |
| ⑦ | **`PlanSummary.blocked` 是 C-01 之外的额外键** | 需正式登记或换表达 | `schemas.py:354/370` |
| ⑧ | **`gen_sql_complex` 的 pro 档空 content 率 2/3** | 疑 `max_tokens` 在思考阶段截断；**L3+ 真实可用率 ≈ 1/3** | DELIVERY §五-2 |
| ⑨ | **`open_analysis` 意图不可达** | FR-1.6 四分类实落 3 类 | `schemas.py:38-42` |
| ⑩ | **`_looks_complex` 阈值未标定** | L0–L2 / L3+ 路由质量，需评测 | `engine.py:968` |

---

## §给 W3-INT（阶段 3 收口需知）

1. **门禁命令**（与 CI 对齐）：

   ```bash
   cd CommerceQL/backend
   ../.venv/Scripts/pytest.exe -q                        # 1395 passed / 55 skipped / 1 failed / 6 errors
   ../.venv/Scripts/ruff.exe check app/planner tests/unit/test_planner_*.py
   ../.venv/Scripts/mypy.exe app                         # 102 files clean
   ../.venv/Scripts/lint-imports.exe                     # 4 kept, 0 broken
   ```
   ⚠️ 全量那 **1 failed + 6 errors + 55 skipped** 全在 `tests/integration/`（真 PG/Redis），根因 = **Docker Desktop 未启动**，**不是阶段 3 的回归**。收口前请先把 Docker 起起来复跑，别把它记成技术债。

2. 🔴 **必须进阶段 3 收口结论的三条**（否则会误判为"已实现"）：
   - **`planner` 零调用方**：节点 2/3/5/7 在图上仍是空的，降级/`refuse` 语义都不会自己出现 → 等 W4。
   - **`plan` / `gen_sql` 当前 100% 失败**（W3A 任务级硬超时）→ **不修就等于阶段 3 的 L0–L2 生成路不可用**。
   - **合并档 2（`plan`+`gen_sql`）未实现** ⇒ **DoD① 只算部分达成**，别写成"已达成"。

3. **DoD 收口口径建议**：DoD① 按"3/4 项实测 + 1 项未实现（含触发条件已成立的证据）"记，**不要**记成"延迟实测已完成"。
4. **证据留存**：真机探针脚本与原始 JSON 在**工作区根目录**（`_w3b_latency_probe{,2,3}.py`、`_w3b_latency_result{,3}.json`），**未提交**。收口若需留档请指定位置；不需要就让它随工作区清理。
5. **测试夹具可复用**：`tests/unit/test_planner_egress_contract.py` 内含"**真网关 + 假上游**"的装配写法（`_real_gateway` + W3A 的 `tests/unit/_llm_fake_upstream.py`）——W3-INT 若要写阶段 3 的联调冒烟，这是现成的起手式。

---

## 【勘误·2026-09-17 傍晚】本转述件两条被 W3A 修正（证据 = `reports/w3a/DELIVERY.md §12/§13`）

1. **§给 W3A-1 的范围报窄了**：不只是 `plan`/`gen_sql`，**8 个有 §16.1 分配的 task 全部中招**——含 `normalize_intent`（本窗口报 5/5 是悬崖边样本，W3A 同口径 0/3）。W3A 已修（`d89dc07`+`e582fe0`）：`TaskRoute.timeout_s` → **`budget_s`**（纯元数据）、`effective_timeout_s` **删除**、deadline 一律 **`hard_timeout_s(model_key)`**（flash 15s / pro 45s）。真机双向对照 **0/15 → 15/15**。
2. **§给 W3A-2 的结论相反**：不是"2/3 空 content"，是 **3/3 确定性失败**（`finish_reason=length` ×3，reasoning 恰好吃满 3248）；且 **pro 档端到端从未生效**（每次 45s 掐断 → flash，50–60s/req）。已标定 `THINKING_HEADROOM_TOKENS=8192` / `output_tokens_hint=1536`；真正的矛盾（PRD §12.2 × 07 §10.2 × 8s P95）上呈为候选 **⑬**。
3. **§给 W3-INT 第 2 条更新**："plan/gen_sql 100% 失败"这条**已过时**，收口结论应写成——**"网关已修，但 §16.1 的预算执行点现在空缺，等架构裁决 + W4 落 SSE 占位符"**（NFR-1.2 的唯一执行点目前无人）。门禁基线更新为 `pytest` → **1471 passed / 6 skipped / 0 failed**（Docker 起来后）。
4. **§给 W4 的装配指引更新**：本转述件写的接线契约（每请求构造引擎、两条降级通道、`plan["normalized_question"]`、`LlmRefused` 先捕）**全部仍然有效**；新增一条——超阶段预算**不再失败**（照跑完 + `over_budget=true`），你的 SSE 层才是 §16.2"超预算推占位符"的唯一执行点。
