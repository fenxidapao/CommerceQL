# W3-INT 转述件（RELAY）—— 阶段 3 统一上游转述（逐窗口可粘贴）

> 窗口：W3-INT（收口）｜日期：2026-09-17｜基准 commit：`affad0b`
> 本文 = 阶段 3 三窗口（W3A `app/llm` · W3B `app/planner` · W3C `app/binding`）对上游/平行窗口转述的**统一合并版**。
> 每条已经收口窗口逐条核验（核验记录见 `DELIVERY.md §4`）；与三家原始 RELAY 冲突时**以本文为准**（已吸收 W3B 勘误节与 W3A §12/§13 追加）。
> 用户可将各节整段转发对应窗口。

---

## §给架构窗口（裁决上呈 —— 单一文档，合并去重后 24 组候选）

> 编号纪律：本窗口与三家窗口均**未自行开号**，下一可用号 = `U-65`。以下临时标记 [A1]–[A24] 仅供引用，正式编号由你分配。
> 合并说明：W3B 候选 ①② 与 W3A ⑪⑫ 同源（已并入 A2）；W3B ⑧ 已被 W3A §13 标定解决（撤下，见 A2 尾注）；W3C 9 与给 W1B 的建表需求同源（A22）。

### A 组一：预算与延迟（🔴 优先，互相咬合，建议一并裁）

| # | 问题 | 实测证据 | 需要你裁什么 |
|---|---|---|---|
| **A1**（原 W3A①） | 07 缺 `gen_sql_complex` / `repair` 的任务级延迟预算 | 其余 6 阶段有 0.6–1.5s 分配，这两档没有 → 退化为模型级 45s/15s，P95 契约在这两档无约束 | 补两档分配（依据实测，U-22：不许实现者发明数字） |
| **A2**（原 W3A⑪⑫ + W3B①② 合并） | **07 §16.1 分配值被真机证伪 + 其执行点现空缺**。预算曾被实现成硬超时（8 个有分配 task 全不可用），已按"预算≠超时"根修（`d89dc07`）；但 §16.1 数字本身未重裁，且 §16.2"超预算先推占位符"目前**无人执行** ⇒ NFR-1.2 没有执行者 | 直连网关口径：normalize 1.45s / intent 1.39s / normalize_intent 1.56s / plan 1.49s / gen_sql 1.60s（vs 分配 0.6–1.3s，**全部超**）；经 PlannerEngine 口径：plan 2756ms / gen_sql 1939ms（结论一致，数值以 W3A §12.1 为准）。双向对照 0/15 → 15/15 | ① 按新实测重算 §16.1（并写明"这是分配不是超时"）；② 指定"超预算 → 推占位符"的执行点（W4 SSE）与验收口径 |
| **A3**（原 W3A⑬） | **PRD §12.2（L3+ → v4-pro 思考）× 07 §10.2（pro 45s）× NFR-1.2（8s P95）三者不可同时成立** | pro 在真实 L3+ 问句实测 **97–138s**（reasoning 4900–6719 token），超 45s 上限 2–3 倍 ⇒ **pro 档端到端从未生效**：每次白等 45s → 降级 flash，用户拿 flash 答案、付 50–60s/请求（`w3a/DELIVERY.md §13.3`） | 三方向原样呈报、**不预设立场**：**A** 放宽 pro 上限 ~150s（与 8s P95 彻底冲突，须配异步/后台+SSE 分段）；**B** L3+ 改走 flash 非思考（与 PRD §12.2 冲突，需改需求或记 deviation；若选 B，W3A 可立即改回 FAST 非思考，待明确指令）；**C** pro 异步生成 + 先返回计划占位（工程量大 W4/W5 都动，唯一兼顾质量与感知延迟）。另：07 §10.2 的"单次调用超时"口径已被实测证伪两次（A2 + A3），建议先给一版基于实测的口径 |
| **A4**（原 W3B③） | 07 §16.1 压缩手段 2（合并 `plan`+`gen_sql`）**触发条件已成立**，但缺资产 + UX 张力 | 手段 1+4 后 `plan`+`gen_sql` 仍 4.70s vs 分配 2.3s（`w3b/DELIVERY.md §二`） | 是否采纳；采纳后需新 prompt 资产 + 新 `LlmTask` 取值（W3A 域），且"计划先展示给用户"的 UX、`plan_ready` 事件语义要定。⚠️ 若合并档是思考档会正撞 A3 |

### A 组二：端口 / 契约缺口（W0 的 core 文件，动前需你定方案）

| # | 问题 | 现状 |
|---|---|---|
| **A5**（W3A③） | `LLM_MAX_CONCURRENCY=50` 与 07 §10.1"按模型 8/2"语义关系未定义 | W3A 按"全局 AND 按模型"实现；若 50 是上游契约上限则当前低估吞吐 |
| **A6**（W3A④⑤） | 租户日预算无 config 键（现用经验值 10 元）；`USD_CNY_RATE` 全仓无配置项（现用 7.1） | config 需补两键或给口径 |
| **A7**（W3A⑥） | `EgressPayload.candidates` 需正式登记进 07 §10.5 | W3A 唯一新增出站字段 |
| **A8**（W3A⑦） | `LLMPort.estimate_cost(payload)` 的 payload 结构端口未定义 | W3A 自定义并登记（`budget.estimate_for_payload` docstring） |
| **A9**（W3A⑧） | `LLMResponse` 装不下 `degraded`/`refuse` → 用两条侧信道（回调+异常）绕开 | 是否扩端口字段（扩则 W4 不再依赖"记得先 except LlmRefused"的约定） |
| **A10**（W3B④） | `PlannerPort.generate_sql` 缺"归一化问题"入参 | 现以 `plan["normalized_question"]` 约定绕开（缺失即抛契约错误）；扩端口动 W0 的 `contracts.py` |
| **A11**（W3B⑤） | `DegradedReason` 缺 `understanding_failed` / `sql_generation_failed` | 现复用 `plan_generation_failed` + `detail.missing_reason_value` 显式标注凑值 |
| **A12**（W3B⑥） | `unsafe → refuse(pii_blocked)` 是语义拉伸 | 资产语义（越权/改自身行为）与 `RefuseReason` 取值集不匹配（`w3b/schemas.py:139-140`） |
| **A13**（W3B⑦） | `PlanSummary.blocked` 是 C-01 之外的额外键 | 需正式登记或换表达（区分"计划没出来"与"计划出来但为空"） |
| **A14**（W3B⑨） | `open_analysis` 意图不可达（模型侧 prompt 不产出） | FR-1.6 四分类实落 3 类 |
| **A15**（W3B⑩） | `_looks_complex` 启发式阈值未标定 | 影响 L0–L2 / L3+ 路由质量，需评测口径 |
| **A16**（W3C1+2 合并） | `CandidateRef` 缺两字段：①分数来源（L1–L3 `score=0.0` 是占位）②打分器标识（注入路径 τ 身份校验恒通过，N-27 约束②失效） | 建议 `score_kind` + `scorer_id`（或 `RerankScore` 直进候选） |
| **A17**（W3C3） | `BindingPort.resolve` 无问句位 + 07 附-1 未定义 `candidates` 语义 | 现以 contextvars + "只消费 L4 标记"绕过（D2/D7 已登记） |
| **A18**（W3C7） | `BindingResult` 三字段装不下 `disclosure`/`clarify_prompt`/`reason` | 现走 `resolve_detailed` 旁路；`disclosure` 唯一载体 = `insight.caveats[]`（U-26） |
| **A19**（W3C8） | 校准选点 tie-break 原文只说"最小澄清率" | W3C 落 `(澄清率, −准确率, −τ)`，均在保守侧，请确认 |

### A 组三：语义 / 判据冲突

| # | 问题 | 现状 |
|---|---|---|
| **A20**（W3C4）🔴 | **`platform_admin` 两判据结论相反**：`asset_allowlist` 放行 `order_paid.receiver_phone`，`is_denied_column` 恒拒 → gate1 R07 必拒其一 | 与 W2C 的**真冲突**，建议优先裁 |
| **A21**（W3C5+6） | ①表级概念（`maps_to_kind=asset`）解析不出列级绑定 → 归 `unresolved`（意图分类应拦在前面？）②`declared_ambiguous` 允许被 L4 判唯一（SCHEMA §5.2 的 `ambiguous:true`="没有规范字段"，与"禁止 L4 判唯一"不同义；实测与 PRD §6.3.1 期望一致） | 两条读法已写进 docstring，请确认 |

### A 组四：数据结构（与 W1B 同源）

| # | 问题 | 现状 |
|---|---|---|
| **A22**（W3C9） | `query_plan` 表缺 `binding_state`/`binding_layer` 列——更准确说**整表不存在**（迁移 0001–0003 零命中） | = W3C DoD① 硬前置 = 给 W1B 的建表需求（见 §给 W1B-2），是否开号由你定 |

### 非编号两项

1. **`l4_score` 真机延迟未量过**（W3A 请 W3C 自测；收口窗口未代量——真机 key 费用/限流不在授权内）：它的 `budget_s=0.8s` 已不再是超时（根因同 A2，已修），但真实延迟未知，若 prompt/候选规模比 `rerank` 大请安排量一次（归 W3C/W6）。
2. **`PROMPT.md` 入库惯例**：收口已裁决"**所有窗口一律入库**"并执行（补 `w3a/PROMPT.md`，见 `w3-int/DELIVERY.md §8`）。请知悉；若否决，反向操作交下一窗口。

---

## §给 W0（`app/core/**` · `app/obs/**` · `scripts/**` · `pyproject.toml`）—— 合并 12 条

| # | 事项 | 优先级 | 可核对位置 |
|---|---|---|---|
| 1 | 🔴 **`Retry-After` 仍是 2/5，应落码 5s/30s**（07 §14.4.1；30s 不得小于熔断开路 30s） | 高 | `app/core/enums.py` |
| 2 | 🔴 **空字符串 `DEEPSEEK_API_KEY` 能过"必填"校验**（实测 `''` + 有效 DSN → settings 构造通过；建议 `min_length=1` 或 validator） | 高 | `app/core/config.py` |
| 3 | 🔴 **`scripts/assert_importlinter.py` 非并发安全**：残留 `_probe_violation.py` 使任何窗口 `lint-imports` 报 BROKEN + 脚本 FATAL（粘性：清理只在 finally、拒绝覆盖；双窗口互踩，W3A 两轮实测同 sha256 残留）。建议：探针名带 PID/加锁、区分临时与陈旧残留、清理对 SIGPIPE/SIGTERM 生效 | 高 | `backend/scripts/assert_importlinter.py` |
| 4 | `obs.metrics` 缺 LLM 指标本体：建议 `llm_calls_total{task,model,degraded}` / `llm_tokens_total` / `llm_cache_hit_ratio` / `llm_cost_cny_total` / `llm_latency_seconds` 直方图 / `llm_circuit_open` / `llm_budget_ratio` 七项 | 中 | `app/obs/metrics.py`（实测只有 `binding_tau_calibrated` 一个 gauge） |
| 5 | `obs.metrics` 缺 **`binding_state`/`binding_layer` 两个 Counter 本体**（标签已登记≠指标已建；07 §15.3 明确要求；无它则 N-27 约束⑤ 只是"产生了事件没人计量"） | 中 | 同上 |
| 6 | `CallRecord` 新增 `budget_s`/`over_budget` 两字段——若已写 Prometheus 指标请一并纳入 | 低 | `app/llm/__init__.py:259-262` |
| 7 | `DegradedReason` 缺 `understanding_failed`/`sql_generation_failed`（= A11） | 中 | `app/planner/errors.py:80,142` |
| 8 | `PlannerPort.generate_sql` 缺"归一化问题"入参（= A10） | 中 | `app/core/contracts.py:427-429`、`engine.py:729` |
| 9 | `PlanSummary.blocked` 需正式登记（= A13） | 低 | `app/planner/schemas.py:354,370` |
| 10 | `CandidateRef` 缺分数来源 + 打分器标识两字段（= A16） | 中 | `reports/w3c/DELIVERY.md §7-1/2` |
| 11 | 依赖复核：`tenacity`（W3A 自实现退避未用）/ `respx`（未用，用 `httpx.MockTransport`）是否移出白名单——归 ADR-20；W3C 零新增依赖（Kendall τ-b 自实现未引 scipy） | 低 | `reports/w3a/RELAY.md §给 W0-4` |
| 12 | `LLM_TIMEOUT_SECONDS=60` 已被 07 §10.2（15/45s）取代且**未被使用**——补注释或裁决删除 | 低 | `app/core/config.py` |

---

## §给 W1B（`app/repo/**` + migrations）—— 两张表（已复核：迁移 0001–0003 零命中）

1. 🔴 **建 `cost_ledger` 表**：列**逐列对齐** `app/llm/budget.py::CostEntry`（`entry_id` PK / `task_id` / `tenant_id` / `user_id` / `model` / `input_tokens` / `output_tokens` / `cache_hit_tokens` / `cost_cny` / `is_peak` / `created_at`，保留 13 个月）+ 实现 `CostLedgerSink` Protocol（`record` / `tenant_spent_cny` / `global_spent_cny`；`created_at` 带时区、`cost_cny` 用 `Decimal` 0.000001 ROUND_HALF_UP）。**表没建好前熔断在重启面前失效**（现内存 sink）；不要给"查明细"接口。
2. 🔴 **建 `query_plan` 表**（`task_id` PK / `plan_json` / `plan_summary` / `bundle_version` / **`binding_state`** / **`binding_layer`** / `confidence`，保留 90 天；07 §12.3:2292、§6.8.3:1540）——**W3C DoD① 的硬前置**，也是 W4 写入的前提。若判定"阶段 3 不落库"，请回一句，W3C 会把 DoD① 改记"整条不做"。

---

## §给 W6（评测执行器）—— τ/ε 校准的唯一消费方

- 脚手架：`from app.binding import ScoreSample, calibrate`（离线，不进请求路径）。`calibrate()` 六步 + `assess_stability`（E-5：n≥3 构造期硬校验 + Kendall τ-b 自实现 + 分差 std；门槛 `max(gap_std) ≥ 0.05` 即 UNSTABLE → 禁止定稿）。
- 四条硬提醒：①`layer_distribution` 只能由运行时观测带入（缺了报告不可定稿）；②稳定性门槛未过不给 τ 候选（不得"多跑取平均"绕过）；③`should_clarify_but_did_not` 只报告不设闸；④`config_lines()` 无定稿点时抛 `ValueError`（旧版输出空 `BINDING_TAU=` 已修）。
- ⚠️ **收口结论（必须带进你的评测计划）**：L4 从未接真实 LLM（MockTransport）⇒ **τ 尚未在真实打分器上校准，真跑前 `is_finalizable` 必为 `False`**（设计使然）；E-5 稳定性**未在真实链路验证过**。另 `accuracy_target` 数值上游未给（§C.4.6 只说"满足目标"），是必填参数——需业务/架构给口径（= A19 邻域）。

---

## §给 W2B / W1A（小口径）

- **W2B**：检索集成用例在**库不可达时应 error→skip 而非外逸**：`test_retrieval_fts_pg.py` 的 `pg_table` 夹具（:110-117）只捕 `InsufficientPrivilege`，Docker 未起时整文件 1 failed + 6 errors，**三个窗口都被它误判过基线**。建议补 `except (psycopg.OperationalError, ConnectionTimeout) → pytest.skip`（你的文件你定）。
- **W1A**：语义包两字段缺口：①排序键要的"血缘完整"与"成本"无对应字段（步⑤ 实际只用 4 项）；②`quality_gates.max_staleness_hours` 需要实际新鲜度，包内只有 SLA 声明（`reports/w3c/RELAY.md §给 W1A`）。

---

## §给 W4（阶段 4 开工输入 —— 按 08 §3.6 DoD 对齐）

> 三包零调用方；以下全部 BLOCKED 待你。**接线约定以本文为准**（已合并三家 RELAY 含 W3A 两轮追加）。

### 1. 装配（lifespan）

```python
# LLM 网关（W3A）
gateway = build_gateway(settings, ledger=<W1B 的落库 sink>, degradation=SseDegradationSink(), ...)
# 收尾：await gateway.aclose()（不关则 httpx 连接不释放）；不传 ledger = 内存 sink（重启熔断失效）

# Planner（W3B）—— 每请求一个实例，不得跨请求复用（_pending 会串降级事件）
engine = PlannerEngine(llm=<LLMPort>, semantics=<SemanticBundlePort>,
                       clock=Clock(bundle.time_semantics()), degradation=<你的 sink>)

# Binding（W3C）—— 装配 + τ 断言 + gauge
service = BindingService.from_settings(reader=semantic_runtime, settings=settings, observer=<你的 BindingObserver>)
calibrated = service.assert_usable_tau()      # ε≤0/τ≤0/已校准无 report_ref → ConfigError 拒启
metrics.set_binding_tau_calibrated(calibrated)
```

### 2. 每请求上下文（不设 = 静默失效）

- **binding**：`set_binding_scope(BindingRequestScope(normalized_question=q, time_semantics=ts))` + `finally: clear_binding_scope()`——不设则 L2 与五步过滤步③**不判**（fail-open 但 `scope_was_set=False` 如实标出）。
- **LLM 计量**：`set_call_context(LlmCallContext(task_id=..., tenant_id=..., user_id=...))`（contextvars，永不出站；不设 → 计量归 `"(unset)"`）。

### 3. 事件 / 侧信道（不接线就是坏的）

- **降级 → SSE**（W3A + W3B 两条 sink 都要接）：`DegradationSink.on_degraded` / `PlannerDegradationSink.on_degraded` 均为**同步回调**——☠️ 禁止在回调里 `asyncio.run`；你的 emit 若是 async，自行桥接（`asyncio.Queue.put_nowait` / `loop.call_soon_threadsafe`）；阻塞回调会直接吃延迟预算。planner 另有通道②：outcome 自带 `degradations[]`（塞 `GraphState.degradations`）。**两条通道缺一就有可见性缺口。**
- **`LlmRefused` → `refuse` 终态**：🔴 **必须最先捕获**（`except LlmRefused: raise/return refuse(...)` 在 `except LlmError` 之前），否则落 `500 INTERNAL`——**错的终态**（07 §14.2 F1：refuse 不是 error）。planner 的 `UnderstandUnavailable/PlanUnavailable/SqlGenerationUnavailable` 才走业务降级出口（带 `.detail`，含 `missing_reason_value`）。
- **binding 观测出口必须有实现**：默认 `NullBindingObserver` 什么都不做 → N-27 约束⑤（`binding_layer` 分布可观测）的指标面是缺的。`service.observer` 属性可查接的是真适配器还是空实现。
- **L4 双入口（D1(a)）选一条并登记**：在线 `score_l4`（真校验，推荐）vs 注入 `CandidateRef`（τ 身份校验恒通过，来源一致性由你保证）。

### 4. 🔴 预算与延迟（阶段 3 收口后**新增**的责任）

- **§16.2 占位符先推现在归你**：网关已不再按预算掐调用（超预算照跑完 + `over_budget=true`，**不发 degraded**）。07 §16.2"若 1.2s 未完成 → 先推 `stage=intent` 占位"**必须由你发**，否则 NFR-1.2（首字节 ≤1.5s）没有任何执行点（等架构 A2 裁决后照新口径落）。
- **SSE 必须撑住 60s 不断流**（心跳/keepalive）：L3+ 实测 50–60s/请求（pro 被 45s 掐断 → flash），`switched_to_weak_model`/`llm_unavailable` 事件照常发。**别把"L3+ 慢"当回归**——那是候选 A3 的既有事实。
- 度量已备好：`CallRecord.budget_s`/`over_budget`（日志 `llm_call` 事件已输出）。

### 5. 入参契约（照做，别自行发明）

- `generate_sql(plan, ctx, *, candidates)` 的 `plan` **必须带 `normalized_question`**（缺失即抛契约错误）——`build_plan` 返回**原样下传**，别拆散重组；走富方法 `plan_for`/`sql_for` 则无此坑。
- `build_plan` 的 `candidates` 参数**当前不进 prompt**（`plan_v1` 无占位符）——传了没效果。
- state 载荷以 `PlanOutcome.state_payload()` / `SqlOutcome.state_payload()` 为准（别把 `schemas.Plan` 直接当 state 字段）。
- binding 消费 `BindingResult` 用"读法 1"（`resolve_detailed`；`ambiguous` 态下 `result.bindings` 是**澄清选项**，拿去生成 SQL 是错的；`disclosure` 必须写进 `insight.caveats[]`）。
- LLM `payload` 只接受白名单键（严格模式，多一个键就抛）；`user_id/tenant_id` 走 `set_call_context` 不进 payload；`generated_sql` 永不回灌 prompt（N-17，`repair` 只吃 `error_digest`）。
- 联调冒烟现成起手式：`tests/unit/test_planner_egress_contract.py`（真网关 + 假上游 `_llm_fake_upstream.py`）。

---

## 逐窗口回执（收口核验结论 → 各开发窗口）

### → W3A（`app/llm/**`）
- 核验：`budget_s`/`hard_timeout_s`/标定常量/`CallRecord` 四项全部实锤；`effective_timeout_s` 零残留。228 条单测随全量绿。DoD①–⑤ 维持"全达成"。
- 需你知：①你转给 W3C 的"量 `l4_score` 真机延迟"收口未代量（授权外），已转 W3C/W6；②`PROMPT.md` 已按收口裁决补入库。

### → W3B（`app/planner/**`）
- 核验：`_report_and_raise`(:773)/`repair_schema`(:627) 实锤；`INTENT_MAP` 实际在 `schemas.py:143`（你的报告写 `:102`，指向同处，**行号请下次修正**）。170 条单测随全量绿。
- DoD① 收口口径 = **部分达成**（合并档 1 达成、合并档 2 未实现、§16.1 执行点空缺）——与你的勘误节一致，无进一步动作。探针脚本（工作区根 `_w3b_latency_*`）已因 `effective_timeout_s` 删除而全部失效，随工作区清理即可，不需留档。

### → W3C（`app/binding/**`）
- 核验：四条 fail-safe 路径 / n≥3 硬校验（`calibration.py:100-102`）/ `require_rerank_scores`(:129,138) / enums 两基数=4 全部实锤。265 条单测随全量绿。
- DoD① 收口口径 = **部分达成**（落库被缺表阻塞）。你请收口裁决的 PROMPT.md 惯例已裁（一律入库，见 `DELIVERY.md §8`）；你给 W1B 的建表需求已并入统一转述（§给 W1B-2）。
