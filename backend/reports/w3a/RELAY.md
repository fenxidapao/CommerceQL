# W3A 转述件（RELAY）—— 逐窗口可粘贴

> 窗口：W3A（阶段 3 · LLM 网关）｜日期：2026-09-17
> 细节与证据：`reports/w3a/DELIVERY.md`。本文只写**对方需要照做/照写的东西**。
> **本窗口未自行开号**：新问题列在 §给架构，下一可用号 = `U-65`。

---

## §给 W3B / W3C（调用面）—— 照此写，不要自行发明

### 1. 拿实例的方式（分层纪律，别绕）

| 你 | 可以怎么做 | **不可以** |
|---|---|---|
| **W3B**（`app.planner`，L3） | 可以 `import app.llm`，但**推荐**只依赖 `app.core.contracts.LLMPort` 并接收实例 | 不要在 `planner` 里自己 new 一个 `ChatClient`/`LlmGateway` |
| **W3C**（`app.binding`，L2） | **只能**拿注入的 `LLMPort` 实例 | 🔴 **禁止 `import app.llm`**（R-DEP-2 会红，`.importlinter` 机器拦）。`binding` 是确定性层，L4 打分器必须经端口 |

装配在 W4 的 lifespan（`build_gateway(...)`）；测试里可以自己构造。

### 2. 调用签名

```python
resp = await port.call(task, payload, model="auto")   # state/Mapping
cost = port.estimate_cost({"text": ..., "task": ..., "output_tokens": ...})  # 同步，返回 Decimal
```

- **`task` 取值（10 个，字面量即契约，改名会破坏你）**：
  `normalize` / `intent` / `normalize_intent`★合并档 / `rerank`（候选精筛）/ `plan` /
  `gen_sql`（L0–L2）/ `gen_sql_complex`（L3+，**唯一走思考**）/ `repair` / `present` / `l4_score`。
  未知 task → `LlmUnknownTask` **fail-fast，不会回退默认模型**。
- **`model` 参数语义**：`"auto"`（默认）= 按 PRD §12.2 路由表；显式模型名（`settings.LLM_MODEL_FAST/STRONG` 之一）= **覆盖**（逃生门，会记进降级事件 detail 的 `model_override`）；其他 → `LlmUnknownModel`。
- **`resp` 必带**：`text`（**JSON 字符串，未经解析**）／`model`／`prompt_version`／`tokens{input,output,cache_hit,total}`／`cost_cny`。

### 3. `payload` 只接受这些键（严格模式：多一个键就抛，**不静默丢弃**）

```
raw_question        必填、非空。唯一允许出站的用户输入（允许含 SQL —— 那是用户自己的话）
semantic_summary    §10.5 ① 语义包摘要（你经 SemanticBundlePort 取好再传）
dialect_note        §10.5 ② 方言说明（自产稳定文本）
output_schema       §10.5 ② 输出 JSON Schema（自产稳定文本）
few_shots           §10.5 ④ 已脱敏的 (问题, SQL) 二元组，≤8 条
constraints         自产稳定文本（约束提示）
error_digest        §10.5 ⑤ 脱敏错误摘要（**禁含 SQL 语句**，≤1000 字）
candidates          §10.5 ① 候选资产名（表/列/指标/别名），≤200 条、单条 ≤120 字
history_questions   §10.5 ⑥ 会话历史，**只有问题**（含 SQL 会抛）
bundle_version      语义包版本（前缀按它冻结）
user_scope          用户级隔离用的 **16 位 hex 哈希**；只进 HTTP `user` 参数，**不进 prompt 文本**
```

🔴 **三个必须知道的边界**（写错就是安全事件，不是普通参数错）：

1. **`user_id` / `tenant_id` / `task_id` 不得进 payload**。端口签名里没有身份位 —— 用 `app.llm.set_call_context(LlmCallContext(...))` 传，它走 `contextvars`、只服务计量与日志、**永不出站**。
2. **N-17：`generated_sql` / `sql_text` / `sql` 永不回灌 prompt**。连带后果：**`repair` 拿不到失败的那条 SQL**，它只能吃 `error_digest`。这是设计如此，不是我漏做了。
3. **结果集/明细/值样本禁止出站**。`rows`/`result_set`/`sample`/… 这类键名一律抛 `LlmEgressViolation`；用户问题里若出现"结果集形态"（多行分隔字段）也会抛。**这是 fail-closed，没有"警告后继续"档**。

### 4. 异常语义（07 §14.2）

| 你遇到的 | 是什么 | 你该怎么做 |
|---|---|---|
| `LlmConcurrencyExceeded`（**F2**，429 退避耗尽） | **error** | 上抛。**不要**降级成模板答案 |
| `LlmUpstreamError`（**F3**，5xx 重试耗尽） | **error** | 同上 |
| `LlmRefused` | **产品终态 `refuse`，不是 error**（07 §10.2 最后一行） | 🔴 **原样上抛，不要捕获**（W4 转 `refuse`）。它的 `default_code is None` |
| `LlmEgressViolation` / `LlmUnknownTask` / `LlmUnknownModel` / `LlmPromptError` | 契约错误 / 安全事件 | 上抛。**它们不降级** —— 降级会掩盖它们 |

⚠️ **若你写 `except LlmError:` 做自己的降级（如 `plan_generation_failed`），必须先 `except LlmRefused: raise`** —— 否则你会把"产品结论"变成"一次业务降级"，语义就错了。

### 5. 网关**不做**的三件事（免得两边各做一遍）

1. **不解析 JSON**：`resp.text` 是字符串。`json.loads` + schema 校验 + "修复重试 1 次"的**归属在调用方**（你）。理由：网关是 L1，不认识业务 schema。
2. **不发 `degraded` 到 SSE**：网关只调 `DegradationSink`（L4 那一跳归 W4）。
3. **不把候选从 N 路减到 1 路**：预算 80% / 并发饱和时网关只能**建议**（detail 里 `advisory: True`），实物动作是换到弱档。**减路的决定权在你**。

### 6. `estimate_cost(payload)` 的 payload 约定

```python
{"text": <将要出站的全部文本>,   # 必需；缺失按空串算（低估，不崩）
 "task": <LlmTask 取值>,         # 可选；给出则用它的 output_tokens_hint
 "output_tokens": <int>,         # 可选；显式覆盖输出预估
 "candidates": <int>}            # 可选；候选路数（默认 1，多路按 N 倍算）
```
语义 = **高峰价上界**（TCO 纪律）。它是 pre-flight 防失控用的，不是精确对账。

---

## §给 W4（接线）—— 不接线就有三处是坏的

### 1. 侧信道 A：降级通知 → SSE

```python
from app.llm import DegradationSink, DegradationEvent, build_gateway

class SseDegradationSink:                      # 你实现，接 EventEmitterPort
    def on_degraded(self, event: DegradationEvent) -> None:      # ⚠️ 同步方法
        # 推荐：非阻塞入队，由 SSE 侧消费；不要把 emitter 直接 await 在这
        queue.put_nowait(("degraded", {
            "reason": str(event.reason),                          # DegradedReason 8 值之一
            "action_taken": str(event.action_taken),               # ActionTaken 7 值之一
            **event.detail,
        }))
```
- 🔴 **`on_degraded` / `on_call` 都是同步回调**（Protocol 如此定义，本窗口刻意不加 `async` —— 它保证"发事件"这一跳**永远不会阻塞 LLM 调用路径**）。
  ⇒ 若你的 `EventEmitterPort.emit` 是 `async`，请自行做 **sync→async 桥接**：`asyncio.Queue.put_nowait` 或 `loop.call_soon_threadsafe`。
  ⇒ ☠️ **禁止在回调里 `asyncio.run(...)`**（会起第二个事件循环 → 在运行中的 loop 里必炸）；**禁止阻塞**（`on_degraded` 在 `call()` 的同步段内被调用，阻塞它会直接吃任务的延迟预算）。
- 默认实现**只写结构化日志**（`llm_degraded`）。**不接线 = 前端看不到降级**。
- `detail.advisory is True` ⇒ `reduced_candidates` 只是**建议**（网关做不到减路）。
- 一次 `call()` 可能发**多条**事件（例如预算告警 + 模型降级 + 模板命中）。

### 2. 侧信道 B：`refuse` 终态

```python
from app.llm.errors import LlmRefused

try:
    resp = await port.call(...)
except LlmRefused:
    return refuse(...)        # 🔴 必须**先**捕获
except LlmError: ...
```
🔴 **不接线它就落成 `500 INTERNAL`** —— 那是**错的终态**（07 §14.2 F1：refuse 不是 error）。
`refuse` **不给 `data`**（07 §14.3 约束 5），且 `refuse`/`error`/`clarify` 三者互斥。

### 3. 请求级身份上下文（计量要它）

```python
from app.llm import LlmCallContext, set_call_context
set_call_context(LlmCallContext(task_id=..., tenant_id=..., user_id=...))   # 进图前
```
`contextvars`，请求级、并发不串号、**从不出站**。不设 → 计量归集到 `"(unset)"`（**可见**的错误，不静默）。

### 4. lifespan 装配

```python
gateway = build_gateway(settings, ledger=<W1B 的落库 sink>, degradation=SseDegradationSink(), ...)
# 关闭：await gateway.aclose()   ← 别忘了，否则 httpx 连接不释放
```
不传 `ledger` 会用内存 sink（**重启后熔断被重置**）。

### 5. 你可能想知道的（前端相关）

- `degraded` **不是可重试信号**（07：前端只对 `SESSION_CONFLICT` 自动重试）。
- `resp.tokens` 可直接喂 C-03 `meta.tokens`；`cache_hit` 来自上游 `usage` 直供。

---

## §给 W0（配置 / 指标 / 依赖 / 枚举）

1. 🔴 **`Retry-After` 落码**（PROMPT §三-11，本窗口未复核）：07 §14.4.1 裁定 `LLM_CONCURRENCY_EXCEEDED`=**5s**、`LLM_UPSTREAM_ERROR`=**30s**；`app/core/enums.py` 现仍为 2/5。**30s 不得小于熔断开路时长 30s**（07 §14.4.1 的机制来源）。
2. 🔴 **空字符串 API key 能通过"必填"校验**（本窗口实测）：`DEEPSEEK_API_KEY=''` + 有效 DSN → settings **构造通过**。⇒ 当前"必填"只是"键必须存在"。建议加 `min_length=1` 或 validator（fail-fast 的强度取决于这个）。
3. **`app.obs.metrics.py` 没有 LLM 指标**（实测只有 `binding_tau` gauge）。本窗口**不改 W0 的文件**，改为暴露 `MetricsSink` 注入点 + 默认打结构化日志。建议落：`llm_calls_total{task,model,degraded}`、`llm_tokens_total{kind=input,output,cache_hit}`、`llm_cache_hit_ratio`（NFR-4.3）、`llm_cost_cny_total{model,is_peak}`、`llm_latency_seconds` 直方图、`llm_circuit_open{model}` gauge、`llm_budget_ratio{scope}` gauge。
4. **本窗口未新增依赖**：`httpx`/`tiktoken` 已在白名单；**未用 `tenacity`**（退避自己实现 —— `tenacity` 表达不了"总预算做减法"，见 `test_retry_count_is_truncated_by_the_task_budget`）；**未用 `jinja2`**（Q5 用标准库 `string.Template`）。请裁决 `tenacity` 与 `respx` 是否从白名单移出（归 ADR-20）。
5. **`LLM_TIMEOUT_SECONDS=60` 被 07 §10.2 的 15s/45s 取代**（Q3 以 07 为准）。该键目前**未被使用** —— 建议补注释或交架构裁决删除。
6. **`app/cache/keys.py` 现在不需要预算/成本键**（本窗口用 in-memory sink）；仅当将来把计量换 Redis 载体时才需要（07 §10.1 已提"并发改 Redis"那条）。

---

## §给 W1B（`cost_ledger` 表 + 写入 API）

**现状**：07 §12.3 有完整列定义，迁移 0001–0003 **均未建**；全仓 `cost_ledger` 只出现在 docstring 里（无模型、无迁移、无写入 API）。本窗口按 Q1 裁定 **(a)**：定义 sink 注入点 + 内存实现，**未建迁移、未报"已落库"**。

**需求（三件事）**：

1. **建表**（列**逐列对齐** `app/llm/budget.py::CostEntry`，§12.3 定义：`entry_id`(PK)/`task_id`/`tenant_id`/`user_id`/`model`/`input_tokens`/`output_tokens`/`cache_hit_tokens`/`cost_cny`/`is_peak`/`created_at`，**保留 13 个月**）。
   ⇒ 按 `CostEntry` 写 INSERT 即可，**不必两边各定义一遍列**。
2. **实现 `CostLedgerSink` Protocol**（`app/llm/budget.py`）：

   ```python
   def record(self, entry: CostEntry) -> None: ...
   def tenant_spent_cny(self, tenant_id: str, day: date) -> Decimal: ...
   def global_spent_cny(self, day: date) -> Decimal: ...
   ```
   - 后两个是**预算熔断的唯一读口**（日累计）。窗口口径 = **`Asia/Shanghai` 日切**（`budget.BILLING_TZ`），与业务时间口径（N-26）**解耦**。
   - ⚠️ `created_at` **必须带时区**（本窗口存的是 tz-aware `datetime`）。若落 `timestamptz` 更稳妥。
   - ☠️ **请不要给"查明细"接口** —— 网关不需要，给了会诱使别人绕开仓库层。
3. **`cost_cny` 用 `Decimal`**（本窗口精度 `0.000001`，`ROUND_HALF_UP`）。float 累加会让"恰好用满预算"这类判定飘。

**两个附加列（可选）**：`tokens_estimated` / `price_guess` 是 `CostEntry` 上的**非落库标记**（运维可观测用：token 数是否为估算、单价是否走了未知模型兜底价）。落不落列由你定，本窗口不擅自扩表。

**接线位置**：`build_gateway(settings, ledger=<你的 sink>)`（W4 在 lifespan 传）。表没建好之前，内存 sink 会让**熔断在重启面前失效** —— 这已在 `DELIVERY.md §6` 具名登记。

---

## §给架构窗口（待分配编号；下一可用 = `U-65`）

按 07 §4.8 的纪律，本窗口**未自行开号**。以下 8 项请分配编号并裁决：

| 候选 | 问题 | 现状 / 影响 |
|---|---|---|
| ① | **07 缺 `gen_sql_complex` / `repair` 的任务级延迟预算** | 其余 6 个阶段都有 0.6–1.5s；这两个没有 → 退化为模型级 45s/15s，**P95 契约在这两档无约束** |
| ② | **07 §16.1 `gen_sql`=1.3s 与 PRD §12.2 "L3+ 走 pro 思考" 物理冲突** | 真机实测 pro **最简**调用 1.42s > 1.3s。要么给 pro 档独立预算，要么承认 L3+ 必然超 P95 |
| ③ | `LLM_MAX_CONCURRENCY=50` 与 07 §10.1 "按模型 8/2" 的**语义关系未定义** | 本窗口按"全局 AND 按模型"实现（两值都生效）。若 50 另有含义，当前实现会低估吞吐 |
| ④ | **租户日预算无 config 键** | 07 §10.4 要求双层预算，config 只有全局 `DAILY_BUDGET_CNY`；本窗口用经验值 10 元 |
| ⑤ | **`USD_CNY_RATE` 全仓无配置项** | PRD §12.3 只有 1 个换算数据点（$0.0071→¥0.05 ⇒ ≈7.04），本窗口取 7.1 并标经验值 |
| ⑥ | **`EgressPayload.candidates` 需正式登记进 07 §10.5** | 本窗口**唯一**新增的出站字段（依据 §10.5 ① 的"同义词"子集） |
| ⑦ | **`LLMPort.estimate_cost(payload)` 的 payload 结构端口未定义**（签名只有 `Mapping`） | 本窗口自行定义并登记（见 `budget.estimate_for_payload` docstring 与本文 §给 W3B/W3C-6） |
| ⑧ | **`LLMResponse` 装不下 `degraded`/`refuse`** → 本窗口用两条侧信道（回调 + 异常）绕开 | 侧信道是妥协。需裁决是否扩端口字段（扩则 W4 不再依赖回调约定，也不必靠"记得先 except LlmRefused"） |

另请复核一条**交付期发现但已被我推翻的推断**（记录在案，避免后人重走）：`client._Breaker.half_open_probe_in_flight` 的复位耦合**不构成故障**（探针实验证实：失败触顶分支的 `finally` 恰好会清掉它）。本窗口已改为局部不变量并加了白盒断言，但**它不是"修了一个线上缺陷"**。

---

## §给 W3-INT（收口需知）

1. **门禁命令**（与 CI 对齐；⚠️ `lint-imports` 必须用**控制台脚本**）：

   ```bash
   cd CommerceQL/backend
   ../.venv/Scripts/python.exe -m pytest -q                      # 1020 passed / 6 skipped
   ../.venv/Scripts/python.exe -m ruff check .
   ../.venv/Scripts/python.exe -m mypy app
   ../.venv/Scripts/lint-imports.exe                             # 4 kept, 0 broken
   ../.venv/Scripts/python.exe scripts/assert_importlinter.py    # DoD② 注入实验
   ```
   ☠️ `python -m importlinter.cli lint-imports` = **无输出 + exit 0 的假绿**（U-41，该包 `cli.py` 无 `__main__` 守卫）。本窗口实测复现过。

2. **必须进阶段 3 收口结论的两条**（否则会误以为"已实现"）：
   - **模板层是空的**（`NullTemplateProvider`）→ 默认降级链实际是 `pro → flash → 拒答`。真正落地需 Gold Query 库（`gold_query`，W1B/W6）。
   - **计量是内存的**（`cost_ledger` 表不存在）→ **熔断在进程重启面前失效**。等 W1B 的表。
3. **两处未接线就是坏的**（W4 的活）：`degraded` 事件只到日志（前端看不到）；`LlmRefused` 不接线会落成 `500 INTERNAL`（错终态）。
4. **本窗口未做真机集成测试**（只做了行为探测）。`deploy/.env` 有可用 key（PROMPT §三-8 已过期）；集成测的门槛在**费用**与**限流**，请按需决定是否跑。
5. ⚠️ **探针残留通报**：交付期发现 `backend/app/guard/_probe_violation.py` 残留（中断的 `assert_importlinter.py` 留下的），**导致全仓 import 契约基线本地变红**。已备份内容后清理（详见 `DELIVERY.md §7.3`）。收口时如有窗口报告"lint-imports 红"，先查这个。
6. **测试夹具位置**：`tests/unit/_llm_fake_upstream.py`（假上游 + 出站请求录制）。DoD③ 的证据 = `test_llm_gateway.py::TestOutboundAttachment`。若你要写集成测试，可复用该夹具。

---

## 【追加·2026-09-17 下午】阶段预算 ≠ 超时 —— 本次修正的跨窗口影响

> 背景：W3B 转述的阻断项（`reports/w3b/RELAY.md` §给 W3A-1）已确认并修复。
> 证据与根因见 `DELIVERY.md §12`（真机双向对照 **0/15 → 15/15**）。

### §给 W3B（**你的阻断项已解除，但行为有变，请照此调整**）

1. **`plan` / `gen_sql` / `normalize` / `intent` / `normalize_intent` 现在可用。**
   真机实测修复后：`plan` 1.49s、`gen_sql` 1.60s、`normalize_intent` 1.56s、`normalize` 1.45s、`intent` 1.39s（均为中位）。你原来旁路 `effective_timeout_s` 的做法**不再需要**，且那个名字**已不存在**（删掉了）。
2. **不要再传、也不要再读 `TaskRoute.timeout_s`** —— 它改名为 **`budget_s`**，语义是"07 §16.1 的阶段延迟分配（P95）"，**只是元数据，不参与超时判定**。
3. 🔴 **行为变化（会影响你的阶段预算假设）**：单次调用现在受 **07 §10.2 的模型级上限**约束 —— **flash 15s / pro 45s**，**不再按 task 掐**。也就是说**超阶段预算不会再失败**，而是照跑完。
   ⇒ 07 §16.1 的 0.6/1.0/1.3s 在**网关层已无人强制执行**。**超预算的处置责任现在在上层**（见下面给 W4 与架构的两条），你那边若有"按预算做取舍"的逻辑，请注意它不再是网关能替你兜的。
4. 你的 **`gen_sql_complex` 空 content（2/3）** 与 **合并档资产** 两条已收下：前者我接下来做 `max_tokens` / `THINKING_HEADROOM_TOKENS` 标定；后者需要新资产 + 新 `LlmTask` 取值（改契约），**先报架构裁决**再动。

### §给 W4（**新增一份原本不存在的责任**）

1. 🔴 **§16.1 阶段预算的执行责任现在归你（SSE 层）**。原先它是被网关硬砍的（副作用是 `plan`/`gen_sql` 100% 失败）；现在网关**不再管**，07 §16.2 的兜底——"**若 1.2s 未完成 → 先推 `stage=intent` 占位**"——**必须由你发**，否则 NFR-1.2（首字节 ≤1.5s）失去唯一执行点。
2. 度量手段已备好：`CallRecord` 新增两字段 —— **`budget_s: float | None`**（该 task 的 §16.1 分配，`None` = 07 未给）与 **`over_budget: bool`**（本次是否超标）。日志已输出这两项（`llm_call` 事件）。
3. ⚠️ **`over_budget` 不会发 `degraded` 事件**（刻意的）：降级事件的含义是"答案来自降级路径"，延迟超标不改变答案。别指望靠降级事件感知它。

### §给架构窗口（**追加候选，编号仍待分配；请与 ① ② 合并裁**）

| 候选 | 问题 | 现状 / 影响 | 证据 |
|---|---|---|---|
| ⑪ | **07 §16.1 的阶段预算被实现成硬超时，导致 8 个有分配的 task 全部不可用** | 已按"解耦"修复（超时取 §10.2 模型级）；但 **07 §16.1 的数字本身仍未被重裁**，且**其执行责任现无归属** | `DELIVERY.md §12.1`（0/15 → 15/15） |
| ⑫ | **07 §16.1 的分配值被真机证伪**（实测 1.39–1.60s vs 分配 0.6–1.3s，**全部超**） | 与 W3B 候选 ① 同源，但本窗口给出了**直连网关**的口径（1.39–1.60s），与 W3B 经 `PlannerEngine` 的口径（1.9–2.8s）不同，请一并采纳 | `_w3a_budget_result.json` |

> 建议裁决要点：① §16.1 的 P95 分配按**新实测**重算（并明确"这是分配，不是超时"）；② 明确"超预算 → 推占位符"的执行点与验收口径（NFR-1.2 现在没有执行者）；③ 若认为确实需要"每任务硬上限"，请给**依据**而不是让实现者发明数字（U-22）。

### §给 W0（**两项**）

1. 🔴 **`scripts/assert_importlinter.py` 不是并发安全的，残留会污染全仓基线**（本窗口交付期实测，两次会话各出现同 sha256 `17d4eff1…7737e2` 的残留）：
   - 残留存在时，**任何窗口**的 `lint-imports` 报 `R-DEP-2 BROKEN`，脚本本身直接 `FATAL: 注入任何探针之前，lint 就已经失败`（退出码 2）。
   - 机制：清理只在 `finally`（**信号杀死不执行**）；且脚本**拒绝覆盖已存在的探针** ⇒ 残留是**粘性的**。另：两个窗口同时跑会互踩（一方的 step-0 看到另一方的探针）。
   - 本次取证：删除并验绿后**数秒内**该文件又被写下（mtime 15:56:44 → 15:57:44）；而"删完立刻跑"（最小竞态窗口）**DoD② 一次通过、无残留** ⇒ 竞态。
   - 建议：探针文件名带 PID（或加锁）；区分"并发中的临时文件"与"陈旧残留"；清理对 `SIGPIPE`/`SIGTERM` 也生效。
2. **`CallRecord` 新增 `budget_s` / `over_budget` 两字段**（用于 §16.1 一致性观测，见 `DELIVERY.md §12.4`）。若你已按旧字段集写 Prometheus 指标，请一并把这两项纳入（原"LLM 指标无落点"的需求不变）。

### §给 W3C（**一句话**）

`l4_score` 的 `budget_s=0.8s` **不再**是超时 —— 你那路若曾出现 0/3 失败，根因与 W3B 同源，**现在已修**（单次调用上限 = flash 15s）。**未实测**：`l4_score` 的真机延迟本窗口没量过，如果它的 prompt/候选规模比 `rerank` 大，请自行量一次。

### §给 W3-INT（**门禁数字更新 + 一条坑**）

1. 门禁数字（Docker **必须**先起来，否则集成测会假红）：

   ```bash
   cd CommerceQL/backend
   ../.venv/Scripts/python.exe -m pytest -q                      # 1471 passed / 6 skipped / 0 failed / 0 errors
   ../.venv/Scripts/ruff.exe check .                             # All checks passed!
   ../.venv/Scripts/mypy.exe app                                 # 102 files clean
   ../.venv/Scripts/lint-imports.exe                             # 4 kept, 0 broken
   ../.venv/Scripts/python.exe scripts/assert_importlinter.py    # DoD② 通过
   ```
   ⚠️ 首次未起 Docker 时全量会出 **1 failed + 6 errors + 55 skipped**，**全部**是"集成环境不可用"，不是回归（已当场验证：起 Docker 后复跑即 1471 passed）。
2. ☠️ **`assert_importlinter.py` 若报 `FATAL: 注入任何探针之前，lint 就已经失败`，先查 `backend/app/guard/_probe_violation.py` 是否存在**（并发/中断残留，见上面给 W0 那条）。它**不在 git 里**（`.gitignore:46` 有 `**/_probe_violation.py`），删掉即可，不要当技术债记。
3. **阶段 3 收口结论里必须写的一条**（替代原来的"`plan`/`gen_sql` 100% 失败"）：**网关已修，但 §16.1 的预算执行点现在空缺**，等架构裁决 + W4 落 SSE 占位符。

---

## 【追加·2026-09-17 傍晚】`gen_sql_complex` —— 空 content 已标定修好，**但 pro 档在真机仍不可用**

> 证据与根因见 `DELIVERY.md §13`。一句话：**`max_tokens` 不是主因，45s 上限才是。**

### §给 W3B（**你的第 2 条：结论与你相反，请注意**）

1. **不是 2/3，是 3/3 确定性失败。** 用带环比 + 品类排名的 L3+ 问句（真实资产、直发上游、n=3），
   `max_tokens=3248` 三次**全部** `finish_reason=length` + **空 content**，`reasoning_tokens` 恰好吃满 3248。
   你那次"成功过一次"应是更简问句下的偶然，**别把它当基线**。
2. **已按实测标定**（`router.py`）：`THINKING_HEADROOM_TOKENS` 2048 → **8192**；
   `GEN_SQL_COMPLEX.output_tokens_hint` 1200 → **1536**（旧值低于实测 content 需求 1223）。
   你**不用改任何调用代码**——这是路由表内部常量。但**可选**：若你的合并档新 `LlmTask` 也是思考档，请把 reasoning 上界按**你的**问句分布再量一次，别照抄我的 8192。
3. 🔴 **别对 pro 档质量做任何依赖，也别在文案/日志里承诺它。** 实测 pro 档在真实 L3+ 问句上
   **从未生效**：白等 45s 被传输层掐断（`error=LlmTimeout`）→ 降级 flash，**50–60s/请求**、`degraded=True`。
   即用户拿到的是 **flash 的答案**。这条是 PRD §12.2（L3+ 走 pro 思考）× 07 §10.2（pro 上限 45s）
   × 8s P95 **三者不可同时成立**，已上呈架构（候选 ⑬），**不由本窗口单方面改**。
4. **你的第 3 条（合并 `plan`+`gen_sql`）不变**：新资产 + 新 `LlmTask` 取值 = 改契约，先等架构裁决。
   附带一条给裁决的输入：合并后如果是**思考档**，会正撞上述 45s 矛盾；如果是**非思考档**，则回到 PRD §12.2 的偏离问题。

### §给 W4（**SSE 侧两条**）

1. **L3+ 请求实测 50–60s（且答案来自 flash）**：`switched_to_weak_model` / `llm_unavailable` 降级事件会照常发出
   （`from_model=deepseek-v4-pro`、`error=LlmTimeout`）⇒ 你的 SSE **必须能撑住 60s 不断流**（心跳/keepalive），
   否则前端会在 pro 被掐断之前就先断连。
2. ⚠️ **NFR-1.2（首字节 ≤1.5s）在 L3+ 上不可能靠"等模型"满足** —— 唯一出路是 §16.2 的**占位符先推**
   （与上一节给你的第 1 条是同一件事，此处是第二个动因：不只是 1.2s 预算，而是**总耗时 60s**）。
   本窗口**未**在网关层加任何"L3+ 先返回占位"的行为（那属于你的编排职责）。

### §给架构窗口（**追加候选 ⑬，请与 ⑪⑫ 合并裁**）

| 候选 | 问题 | 现状 / 影响 | 证据 |
|---|---|---|---|
| ⑬ | **PRD §12.2（L3+ → v4-pro 思考）× 07 §10.2（pro 单次 45s）× NFR-1.2（端到端 P95 8s）三者不可同时成立** | 实测 pro 档在真实 L3+ 问句 **97–138s**（思考 token 4900–6719），**超 45s 上限 2–3 倍** ⇒ pro **从未生效**，每次都降级 flash + 白等 45s | `DELIVERY.md §13.3`（n=2 端到端 + n=3 直发） |

**三个方向（本窗口不预设立场，也不替架构选）**：

| | 内容 | 代价 |
|---|---|---|
| A | 放宽 L3+ 的 pro 上限到 ~150s | 与 8s P95 彻底冲突 ⇒ 必须配异步/后台 + SSE 分段（产品形态变化） |
| B | L3+ 改走 **flash 非思考** | 放弃 pro 质量，与 PRD §12.2 直接冲突（需改需求或明确 deviation） |
| C | L3+ 走 pro 但**异步生成 + 先返回计划占位** | 工程量大（W4/W5 都动），但唯一同时满足质量与感知延迟的形态 |

> 裁决要素（与 ⑫ 一起）：**"单次调用超时"到底该按哪个口径定？** 07 §10.2 的 45s 已被真机证伪两次
> （⑫ 是"分配小于真实中位"，⑬ 是"上限小于真实需求 3 倍"）⇒ 建议架构**先给一版基于实测的口径**，再让实现者照做。
> 另：若选 B，`gen_sql_complex` 改回 FAST 非思考**本窗口可立即执行**，但需明确指令（不在本轮擅自改）。

### §给 W3-INT（**门禁数字不变，但有一条别误判**）

1. 门禁数字与上一节**完全一致**（本次改动只有 `router.py` 两个常量 + `test_llm_router.py` 一个测试类，
   全离线，不碰任何集成路径）：`pytest` → **1471 passed / 6 skipped**（比上一节 +4，来自本节新增的守卫测试类）；`ruff` All passed；`mypy app` 102 files clean；
   `lint-imports` 4 kept；`assert_importlinter.py` DoD② 通过。
2. ⚠️ **别把"L3+ 请求慢 50–60s"当回归**：那是 ⑬ 的既有事实（pro 被 45s 掐断后降级 flash），
   与本次标定无关。本次标定**不会**让 L3+ 变快，只会让极少数落在 45s 内的问句拿到真正的 pro 答案。

---

## 【回执·2026-09-17 晚】U-67 已执行 —— L3+ 生效档 = flash 非思考（07 v1.0 §10.2/§4.9）

> 架构裁方向 B（"W3A 拿本裁定即可执行路由改回"）→ 已改。执行细节见 `DELIVERY.md §14`。

### §给架构（**U-67 执行完毕 + deviation 确认**）

1. 路由表：`GEN_SQL_COMPLEX` = **FAST + thinking=False + budget_s=3.0**（U-65 经验值）。
   表内**不再有**任何 STRONG/思考条目。deviation（对 PRD §12.2 第 5 行）实现层已生效，**等上游认账**。
2. 45s 上限与 `THINKING_HEADROOM_TOKENS=8192` **按 ② 保留**（当前无消费方是有意的 —— P1 重启 pro 的前置）；
   测试组 `TestThinkingBudgetIsCalibratedFromMeasurement` 把"重启时标定仍盖住实测"钉成了守卫。
3. ⑫ `LLM_TIMEOUT_SECONDS`：本窗口确认**无消费方**，建议 W0 直接删（07 §10.2 是唯一超时口径）。

### §给 W4（**L3+ 行为变了，两条**）

1. **`gen_sql_complex` 现在是 flash 非思考、15s 上限、预算 3.0s（经验值）** —— 不再有 50–60s 的
   pro 白等 + 降级。`over_budget`（>3.0s）观测仍有效，占位符责任不变（U-66：§16.2 执行点 = 你）。
2. ⚠️ §10.2 ⑤ 仍要求你按"L3+ 可能慢"设计心跳——降级链（pro→flash）机制还在，
   P1 方向 C 重启 pro 时 50s+ 场景会回来。**别把这条当成"可以不做心跳"。**

### §给 W3B（**调用面零变化，行为变了 + 一处你的测试我改了**）

`call("gen_sql_complex", ...)` 的 task 名/签名/payload/schema **都不变**；变的只是模型档
（pro 思考 → flash 非思考）。你的合并档（U-68）若落地：**必须 flash 非思考 + `plan_ready` 先发**，
新 `LlmTask` 取值与 prompt 资产由本窗口产（见 `DELIVERY §14.6`，待开工指令）。

🔴 **`tests/unit/test_planner_egress_contract.py::test_complex_task_hits_the_thinking_route` 我改了**
（该文件属你）：它断言旧 PRD 行为（pro+思考），U-67 后全量假红。已改写为
`test_complex_task_hits_the_flash_non_thinking_route_u67`（断言 flash + `thinking: disabled`，
原断言见 git 历史，docstring 写明缘由）。**请复核**。

### §给 W1B（**sink 已核对**）

`DbCostLedgerSink` 与 `CostLedgerSink` Protocol 逐成员匹配（同步三方法 + `CostEntry` 列对齐），
R-DEP-2 处理方式（本地结构化 Protocol）正确。**接线归 W4**；接线后本窗口 InMemory sink 的
"重启丢账"自然消解。无需本窗口改码。

### §给 W3-INT（**门禁数字**）

改动面 = `router.py` 一个条目 + 两个测试文件；全离线。`ruff` All passed｜`mypy app` 104 files clean
（W1B/W0 新文件入扫）｜pytest 数字见 `DELIVERY §14.4`。
