# W3C 转述件（RELAY）—— 逐窗口可粘贴

> 窗口：W3C（`app/binding/**`）｜日期：2026-09-17｜交付提交：`feat(w3c)` + `docs(w3c)`
> 交付细节 = `reports/w3c/DELIVERY.md`。本文件只放**别人要动手的事**，每节可整段粘贴到对应窗口。

---

## §给 W4（接线）—— 不接线就有四处是坏的

> **唯一权威 = `backend/app/binding/__init__.py` 的"给 W4"节**（含可复制的代码片段）。这里只列要点与后果。

### 1. 装配（lifespan）

```python
service = BindingService.from_settings(reader=semantic_runtime, settings=settings,
                                        observer=MyBindingObserver())   # ← 必须给，见第 3 条
calibrated = service.assert_usable_tau()          # ε≤0 / τ≤0 / 已校准但无 report_ref → ConfigError，拒绝启动
metrics.set_binding_tau_calibrated(calibrated)     # U-19 §18.4.1 硬要求 ②
if not calibrated:
    logger.warning("binding_tau_uncalibrated", ...)   # 非 prod 放行但**不得隐瞒**
```

`assert_usable_tau()` **不**重复 `config.py` 的 prod 拒绝、**不**写指标、**不**校验"实际打分器 == τ 所绑"
（后者要等第一次 LLM 响应才有），别在启动期假装校验过。

### 2. 每次请求必须设问句上下文 —— 否则 **L2 与五步过滤的步③ 静默失效**

```python
set_binding_scope(BindingRequestScope(normalized_question=q, time_semantics=ts))
try:
    result = service.resolve(concept, ctx, candidates)      # 端口面（同步）
finally:
    clear_binding_scope()                                   # 长生命周期 worker 必须清
```

不设也能跑（fail-open），但 `question_grain=None` → 步③ 与 L2 **都不判**，且 `BindingOutcome.scope_was_set=False`
会如实标出来。**本层绝不默认某个粒度。** 端口签名里没有问句（`resolve(concept, ctx, candidates)`），
这是 N-27 之外唯一能拿到问句的通道。

### 3. 观测出口**必须有实现** —— N-27 约束⑤（`binding_layer` 分布可观测）要求它

默认 `NullBindingObserver` **什么都不做**：不接线时这条指标面是**缺的**，不是"已满足"。
`service.observer` 属性就是为"查到底接的是真适配器还是空实现"而暴露的。

- 指标标签：`binding_state`(4) / `binding_layer`(4) 已在 `obs.metrics.BOUNDED_ALLOWED_LABELS` 登记；
  `BindingEvent.reason` / 概念名**只进日志，不进标签**（无界基数）。
- `on_binding` 是**同步**方法，实现**不得抛异常**（观测失败不该让一次已算完的判定失败；
  调用侧会兜住并把 `observer_failed:<ExcType>` 写进 `FilterOutcome.notes`）。

### 4. L4 的两条路，选一条（D1(a) 双入口）

| 路 | 怎么用 | 校验强度 |
|---|---|---|
| **在线**（推荐） | `await score_l4(port=llm_port, question=…, candidates=…, …)` 拿 `ScoreOutcome`，再把**同一批**候选与分数交给 `decide(...)` | ✅ **真校验**：身份取自 `LLMResponse.model` / `.prompt_version`，不匹配即抛 |
| **注入**（离线/评测/回溯） | 把分数做成 `CandidateRef(asset_id=…, score=…, layer=BindingLayer.L4)` 传进 `resolve(...)` | ⚠️ **恒通过**：`CandidateRef` 没有打分器标识，只能取 τ 自己那组 → **来源一致性由你保证** |

`score_l4` 需要**归一化问句**与**语义包摘要**（出站白名单键见 W3A RELAY §3）。
非 `L4` 标记的候选**不会被消费**，但会计数进 `BindingOutcome.ignored_candidates`（**不静默丢弃**，D7）。

### 5. 消费 `BindingResult` 的正确姿势（**读法 1**）

```python
outcome = service.resolve_detailed(concept, ctx, candidates)
if outcome.bindings_are_options:                 # ⟺ state is ambiguous
    ...  # 走澄清：把 outcome.clarify_prompt 与 outcome.result.bindings 交给澄清节点（FR-9.1 只问一个问题）
elif outcome.result.state is BindingState.RESOLVED_DEFAULT:
    ...  # 必须把 outcome.disclosure 写进 insight.caveats[]（U-26 的唯一载体；**禁止**塞 scope.notice）
elif outcome.result.state is BindingState.UNRESOLVED:
    ...  # 概念解析不到 or 候选全被过滤 → 不是"澄清"
```

🔴 `ambiguous` 态下 `result.bindings` 是**澄清选项**，不是已绑定字段。拿它直接生成 SQL 是**错的**。
`disclosure` / `clarify_prompt` / `reason` **装不进** `BindingResult`（端口三字段），只能从 `resolve_detailed` 拿。

### 6. 你还需要知道的两件事

- **L4 上游故障会以异常形式到达你**（`LlmRefused` / `LlmUpstreamError` / 并发超限）——本层**刻意不转 `ambiguous`**（D6）：
  用产品结论（"需要澄清"）掩盖系统故障是本项目红线。你要在 `bind` 节点捕获并走降级/错误出口。
- **DoD① 的"落库"目前是断的**：`query_plan` 表还没有 `binding_state`/`binding_layer` 列（见 §给 W1B）。
  在你接线前，四态只是"产生了、上报了"，**没有落库**。

---

## §给 W0（`core/**` / `obs` / `cache` / 依赖）

### 1. `CandidateRef` 缺两个字段（两个不同的问题，别合并成一个）

| 缺什么 | 现象 | 建议 |
|---|---|---|
| **分数来源**（如 `score_kind`） | `CandidateRef.score` 在 L1–L3 上是**占位 `0.0`**（那三层本无分数），语义**只在 `layer is L4` 时有效** → 消费方读 `score` 前必须先看 `layer`，很容易踩 | 加 `score_kind`（`placeholder` / `rerank` / `injected`），或在 docstring 里把"只有 L4 有意义"写成硬契约 |
| **打分器标识**（如 `scorer_id` / 或让 `RerankScore` 直接进候选） | `model_id` / `prompt_version` 只能取 τ 自己那组 → **N-27 约束② 在注入路径上恒通过**（无法拦住"分数其实是另一个模型/prompt 产的"） | 二者选一即可根治。**本窗口不擅自改 `core/contracts.py`** |

### 2. `obs.metrics` 侧：**两个 Counter 本体不存在**（标签已登记，指标未建）

实测：`grep -n "Counter" backend/app/obs/metrics.py` → **零命中**（该文件只有 `binding_tau_calibrated`
一个 gauge 与 `BOUNDED_ALLOWED_LABELS` 允许表，**没有任何 Counter 构造**）。
而 07 **§15.3 指标清单**（第 2784–2785 行）要求两个 Counter：

| 指标 | 类型 | 标签（基数上限） | 出处原文 |
|---|---|---|---|
| **`binding_state` 四态分布** | Counter | `state`(4) | "定位澄清率来自哪一层" |
| **`binding_layer` 分布** | Counter | `layer`(4) | "**L4 占比 = 语义层质量的仪表盘**（§12.9 约束 5）" |

`binding_state`(4) / `binding_layer`(4) 已在 `BOUNDED_ALLOWED_LABELS` 登记 —— 那只是"**允许用**"，
不等于指标已存在。**请补这两个 Counter**（本窗口未越界落笔 `app/obs/**`）；
W4 的观测适配器要写它们，否则 N-27 约束⑤ 只是"产生了事件、没人计量"。

### 3. 依赖

本窗口**零新增依赖**：Kendall τ-b 自实现（`calibration.kendall_tau_b`，闭式公式含并列修正），
**没有引入 `scipy`**（ADR-20 依赖纪律）。

---

## §给 W1B（`query_plan` 表 —— DoD① 的硬前置）

🔴 **08 阶段 3C 的 DoD① 要求 `binding_state` + `binding_layer` "双双落库"，而落点表不存在。**

实测（2026-09-17）：

```
$ grep -rn "query_plan" backend/app/repo/migrations/versions/*.py      # 零命中
$ grep -rn "binding_state\|binding_layer" backend/app/repo/migrations/ # 零命中
$ ls backend/app/repo/migrations/versions/
0001_roles_and_audit_append_only.py  0002_semantic_materialization.py  0003_business_views.py
```

07 规定的落点（**不是我推的，是文档原文**）：

| 出处 | 原文 |
|---|---|
| 07 §12.3 第 2292 行 | `query_plan`：`task_id`(PK) / `plan_json`(含 `schema_version`) / `plan_summary` / `bundle_version` / **`binding_state`（四态！）** / `confidence`，保留 90 天 |
| 07 §12.3 第 2301 行 | "**`binding_state` 必须落库**：不落库 → 澄清率异常时**无法定位是哪一层失效**（§6.8.3 的诊断表失效）" |
| 07 §6.8.3 第 1540 行 | "`query_plan.binding_layer` 落库（与 `binding_state` 同源）" |

**请求**：建 `query_plan` 表（含上述列）→ 本层交付后即可由 W4 写入。
**本窗口没有越界建迁移**（`app/repo/**` 归你）。用户/架构若判定"阶段 3 不落库"，
请回一句，我会把 DoD① 在 `DELIVERY.md` 里改成"整条不做"而不是"部分达成"。

---

## §给 W6（评测执行器 —— 校准脚手架的唯一消费方）

```python
from app.binding import ScoreSample, calibrate           # 离线，不进请求路径

samples = [
    ScoreSample(sample_id="q01",
                candidate_ids=("order_paid.receiver_city", "shop.city"),
                repeats=((0.81, 0.42), (0.79, 0.40), (0.83, 0.44)),   # n ≥ 3，构造期硬校验
                gold_candidate_id="order_paid.receiver_city"),        # None = 本条本该澄清
]
report = calibrate(samples, epsilon=0.05,
                   accuracy_target=0.8,            # ← 必填：§C.4.6 未给数值，本模块不代猜
                   model_id="deepseek-flash", prompt_version="l4_score_v1",   # 打分器标识
                   calibrated_at="2026-09-17T00:00:00Z",
                   holdout_separated=True,         # 约束 2
                   layer_distribution=counts)      # 步骤 6：**只能由运行时观测带进来**
if report.is_finalizable:
    print("\n".join(report.config_lines()))        # 可直接贴 .env 的 6 行
else:
    print(report.blocking_actions)                 # 缺什么，逐条给（含"回看语义包"而非"换 τ"）
```

四条硬提醒：

1. **`layer_distribution` 本模块造不出来**（不连库、不读文件）→ 没带就是 `None`，报告因此**不可定稿**。
   从 W4 的观测/审计侧取。
2. **稳定性门槛未过就不给 τ 候选**（§C.4.6 约束 5"禁止定稿"），并附升级方案 A 的动作项。
   曲线仍会返回 —— 它正是"该升级打分器"的证据。**不得**用"多打几次取平均"绕过。
3. `should_clarify_but_did_not`（安全侧错误率）**只报告、不设闸**：§C.4.6 步骤 4 只把澄清率与定稿联立。
   本窗口**刻意没给它加门槛** —— 加一条文档没有的规则与漏掉一条同样不可接受。但请**在报告里显著呈现**。
4. `config_lines()` 在**无定稿点**时**抛 `ValueError`**（旧实现会输出空值 `BINDING_TAU=`，看着像"待填"，
   实际是坏配置）。要写报告就 catch 它、改读 `blocking_actions`。

---

## §给 W2B（检索集成用例：库不可达时 **error**，不是 skip）

本窗口跑全量 pytest 时发现（**只报告，不落笔改你的文件**）：

```
FAILED tests/integration/test_retrieval_fts_pg.py::test_production_embed_doc_schema_matches_query_template
ERROR  tests/integration/test_retrieval_fts_pg.py::{6 个用例}  ← ERROR at setup of pg_table
```

根因（实测）：`docker ps` → `npipe:////./pipe/dockerDesktopLinuxEngine` 不存在（**daemon 未运行**）；
`/dev/tcp/127.0.0.1/5432` → `Connection refused`。即：`psycopg.errors.ConnectionTimeout`。

**为什么是 ERROR/FAILED 而不是 SKIP**：

- `pg_table` 夹具（第 110–117 行）**只捕获 `psycopg.errors.InsufficientPrivilege`** →
  库不可达时异常外逸，整个 module 的用例变 **ERROR**。
- `@_needs_prod` 用例只判 `PROD_DSN is not None` → 库不可达时 **FAILED**。

W3A 交付时该文件是 "6 skip"（当时 PG 在跑、只是 `app_rw` 无 DDL 权限），**同一文件现在变成 "6 error + 1 failed"**
—— 缺的正是"不可达 → skip"这一档。建议加 `except (psycopg.OperationalError, psycopg.errors.ConnectionTimeout)` → `pytest.skip`
（**你的文件，怎么改你定**）。这样 CI/本机在 Docker 未启时是"如实跳过"，而不是把环境问题伪装成测试缺陷。

**本窗口绑定域 265 用例 0 skip**（全离线，N-01），与上述无关。

---

## §给 W1A（语义包字段缺口）

| 缺口 | 后果 | 位置 |
|---|---|---|
| 排序键要的"**血缘完整**"与"**成本**"在语义包中**没有字段** | 步⑤ 排序键实际只用 `certified / quality_score / freshness_sla / ref` 四项 | `filters._order_key` |
| `quality_gates.max_staleness_hours` 需要**实际新鲜度** | 包内只有 `freshness_sla`（**SLA 声明**，不是实测值）→ 该条 loader 与本层都未实施 | `filters` 步② |

两者都**如实登记为缺口**，本窗口没造替身字段。

---

## §给架构窗口（待分配编号；下一可用 = `U-65`）

**本窗口未自行开号。** 9 条候选（明细见 `DELIVERY.md §7`），按"是否阻塞别人"排序：

| 候选 | 问题 | 阻塞谁 |
|---|---|---|
| 1 | `CandidateRef` 缺**分数来源**字段（L1–L3 的 `score=0.0` 是占位） | 所有消费方（易踩） |
| 2 | `CandidateRef` 缺**打分器标识** → 注入路径 τ 身份校验**恒通过** | N-27 约束② 的完整生效 |
| 3 | `BindingPort.resolve` **无问句位** + 07 附-1 **未定义 `candidates` 语义** | 端口语义（本窗口已用 D2/D7 绕过并登记） |
| 4 | `platform_admin`：`asset_allowlist` **放行** `order_paid.receiver_phone`，而 `is_denied_column` **恒拒** → 同一 ref 上"能不能绑"与"能不能查"结论相反 | 与 W2C gate1 R07 的**真冲突**，建议优先 |
| 5 | 表级概念（`maps_to_kind=asset`，如 `商品`→`product`）解析不出列级绑定 → 归 `unresolved` | 意图分类应拦在前面？ |
| 6 | `declared_ambiguous` 是否允许被 L4 判唯一（读法 3：SCHEMA §5.2 的 `ambiguous:true` = "没有规范字段"） | L3/L4 的语义边界 |
| 7 | `BindingResult` 三字段装不下 `disclosure`/`clarify_prompt`/`reason` → 需 `resolve_detailed` 旁路 | 接口完备性 |
| 8 | 校准选点 tie-break：原文只说"取最小澄清率点" | 校准口径 |
| 9 | `query_plan` 表缺 `binding_state`/`binding_layer` 列（DoD① 硬前置）——更偏"给 W1B 的需求" | 阶段 3C 的 DoD① |

**另请确认两条读法**（已写进代码 docstring，待裁）：

- **读法 3**：`declared_ambiguous` 允许被 L4 判 `resolved_unique`（`four_layer` 顶部）。
- **读法 1（`filters`）**：步⑤ "取 Top-1" 与四层判定**并存**而非二选一 —— 若步⑤ 直接定稿，
  L2/L4 永不触达，与 §6.8.2 硬约束 5（`binding_layer` 四层都要有触发场景）自相矛盾。

---

## §给 W3-INT（收口需知）

1. **本包全离线**（N-01）：`pytest tests/unit/test_binding_*.py` → **265 passed / 0 skipped**，秒级。
2. **门禁工作目录必须是 `backend/`**（CI 用 `working-directory: BACKEND_DIR`）；`lint-imports` 用**控制台脚本**。
   另跑一点：`python -m app.core.enums` 与 `python scripts/assert_importlinter.py`（都是 CI 门禁）。
3. **全量 pytest 有 7 项红，全在 `tests/integration/test_retrieval_fts_pg.py`（W2B），根因 = Docker daemon 未运行**
   （PG 5432 拒绝连接）。55 个 skip 同理。**与本窗口 0 交集** —— 详见 `DELIVERY.md §3.1`。
   若收口要求"全绿"，需先起 Docker 栈（`docker compose up -d`）再复跑。
4. **接线前 DoD① 不成立**：`query_plan` 表与其两列不存在（§给 W1B）。收口报告里请勿写成"已落库"。
5. **L4 从未接真实 LLM**（`httpx.MockTransport` 固定响应）→ **τ 尚未校准**，真跑前 `is_finalizable` 必为 `False`。
   这是设计使然，不是缺陷；但也意味着**阶段 3 收口时 E-5 稳定性仍未在真实打分器上验证过**。
6. 本窗口**零新增依赖**（Kendall 自实现，未引 scipy）。
7. ⚠️ **入库惯例被本阶段两个窗口打破，待你裁决**。核实结果（2026-09-17 实测）：

   | 目录 | `PROMPT.md` | 入库？ |
   |---|---|---|
   | `w2-int/` | 有 | ✅（收口窗口，惯例如此） |
   | `w3a/` | 有 | ❌ **未入库**（在盘上、git 里没有） |
   | `w3b/` | 有 | ✅ 入库（`94f25e0`，132 行） |
   | `w3c/` | 有 | ✅ 入库（`affbf32`，本窗口） |

   W3A 的日志记载的惯例是"报告入库只提 `DELIVERY.md` + `RELAY.md`；`PROMPT.md` 仅收口窗口入库"
   （`w2-int` 有，`w2a`/`w2c`/`w3a` 都没有）。
   **`w3c/PROMPT.md` 是窗口自行重建件**（原始开工上下文未落盘），文件头已三条声明
   "不是上游文档的复述 / 以 `docs/**` 为准"。**若你判定不该入库，请 `git rm` 它**
   ——并请一并规整 `w3b/PROMPT.md`，避免同一阶段两种惯例并存（这类"同一事实两处做法"正是本项目的典型漂移源）。

