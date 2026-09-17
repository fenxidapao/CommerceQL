# W3C 交付 —— 阶段 3 · 字段绑定（`app/binding/**`）

> 窗口：W3C（08 §4.1 归属权：`app/binding/**`）｜日期：2026-09-17｜分支 `main`
> 依据：`07 §6.8` 全节 / `07 §6.8.2`（5 条硬约束）/ `07 附-1`（端口签名）｜PRD `§6.3.1` / `§12.9`（N-27）
> ｜附录 C `§C.4.6`（六步 + 5 条硬约束，**校准的权威来源**）/ `§C.4.5`（NFR-7.1）｜`08 §3.5`（DoD）
> 上游：W3A（`app/llm/**`，已交付 `94ae6ea`）｜下游：W4 接线、W6 评测执行器

---

## 1. 交付范围

`app/binding/` 从零建包（10 个模块，3112 行），全部为本窗口新增 —— 仅 `__init__.py` 原有一句 docstring，
本次重写为包门面。

| 模块 | 行数 | 职责 |
|---|---:|---|
| `context.py` | 94 | 请求级上下文（`contextvars`）：归一化问句 / 时间语义 / 包版本 |
| `errors.py` | 60 | **只有三类**异常：包刻度矛盾 / τ 绑定不匹配 / 裸 float 误用 —— **都不是"这次没绑上"** |
| `grain.py` | 426 | 粒度族索引：并查集推族 + 词汇表 + 问句→粒度（**禁跨族比较**） |
| `scores.py` | 260 | `RerankScore` 值对象（**拒裸 `float`**）+ 严格 JSON 解析 + 注入适配缝 |
| `filters.py` | 438 | 五步过滤：概念解析① + 权限② + 粒度可服务③ + 时间语义④ + 排序⑤ |
| `four_layer.py` | 429 | **核心**：L1→L2→L3→L4 顺序判定 + 四态 + fail-safe + `classify_gap` 唯一区间实现 |
| `l4.py` | 217 | L4 打分生产者：经注入 `LLMPort` 出站 + 严格解析（**本包唯一异步入口**） |
| `service.py` | 424 | 门面：装配各层，实现 `BindingPort` + 观测出口 |
| `calibration.py` | 592 | τ/ε 校准脚手架（六步 + E-5 稳定性机器判定）；**不联网、不连库、不打分** |
| `__init__.py` | 172 | 包门面（54 个导出）+ **给 W4 的四条接线须知** |

测试：`tests/unit/test_binding_*.py`，**7 个文件 / 265 用例 / 全离线**（N-01）。

| 测试文件 | 用例 | 覆盖 |
|---|---:|---|
| `test_binding_grain.py` | 28 | 族推导 / 跨族拒绝 / 问句粒度 |
| `test_binding_scores.py` | 39 | 裸 float 拒绝 / 越界即失败 / 严格 JSON |
| `test_binding_filters.py` | 29 | 五步归因 / RBAC 面 / 排序确定性 |
| `test_binding_four_layer.py` | 47 | 四层各层 + 跨层不变量 + 区间边界（用**二进制可精确表示**的 τ/ε） |
| `test_binding_l4.py` | 33 | 契约字面量交叉校验 / payload 过真网关 / **AST 扫描禁 `except Llm*`** |
| `test_binding_service.py` | 38 | 端口契约 / 上下文 / 候选拆分 / **门面自证（4 条，新增）** |
| `test_binding_calibration.py` | 51 | Kendall τ-b 手算对照 / 稳定性门槛 / 扫描 / 端到端 |

---

## 2. DoD 逐条对照（08 第 232 行）

| # | DoD 原文 | 状态 | 证据 / 缺口 |
|---|---|---|---|
| ① | **四层判定四态可观测**（`binding_state` + `binding_layer` 双双落库） | 🟡 **部分达成（表结构阻塞已解除，差 W4 写入）** | **达成的一半**：每次判定恒产出 `(state, layer)` 二元组（`LayerDecision` 无默认值，两字段必填）；观测出口 `BindingEvent` 同携 `state/layer/reason/attribution/scope_was_set/tau_is_calibrated/ignored_candidates/bundle_version`；计量端已由 W0 落（`observe_binding_state/layer`，见 §10 回执②）。<br>**未达成的一半**：写入 `query_plan` 是 **W4 的接线动作**。✅ **表结构阻塞已解除**（本窗口交付后 W1B 落迁移 0004，见 §10 回执①）：<br>`app.query_plan` = `task_id`(PK) / `plan_json` / `plan_summary` / `bundle_version` / **`binding_state` text NOT NULL CHECK(四态)** / **`binding_layer` text CHECK(L1–L4)** / `confidence`，取值集与 `core.enums` **逐字一致**且有离线契约单测钉住（`test_migration_0004_runtime_contract.py`）。本窗口实测复跑：枚举 `.value` 与快照逐字比对通过 |
| ② | **L4 fail-safe**：解析失败 / 分差落在 τ 邻域 → 必判 `ambiguous`（N-27） | ✅ | `four_layer._level4` 四条路径全部偏 `ambiguous`：候选数<2 / `l4.ok=False`（解析失败）/ 覆盖不全 / 分差落邻域或低于下界。测试含**负向对照**（见 §5）。**例外已裁并具名**：上游故障（`LlmRefused`/`LlmUpstreamError`）**原样上抛**，不转 `ambiguous`（D6） |
| ③ | τ/ε 校准脚手架（含 **E-5**：n ≥ 3 排名一致性 + 分差 std） | ✅ | `calibration.assess_stability`：`n ≥ 3` 硬校验（构造期即拒）+ Kendall τ-b（自实现，含并列修正）+ 分差样本 std；判据严格按原文 = `max(gap_std) ≥ 0.05` 即 `UNSTABLE` → **禁止定稿** + 升级方案 A 动作项。`calibrate()` 串完六步 |
| ④ | `RerankScore` 类型**不接受裸 `float`** | ✅ | `scores.require_rerank_scores` 对非 `RerankScore` 入参抛 `BindingScoreMisuse`；单测逐条对照 |

---

## 3. 门禁实测输出（2026-09-17，本机，`.venv`，工作目录 `backend/`）

```
$ ../.venv/Scripts/python.exe -m pytest tests/unit/test_binding_*.py -q
265 passed in 1.25s

$ ../.venv/Scripts/python.exe -m ruff check .
All checks passed!

$ ../.venv/Scripts/python.exe -m mypy app
Success: no issues found in 102 source files

$ ../.venv/Scripts/lint-imports.exe
R-DEP-1 分层依赖（只能依赖严格更低层） KEPT
R-DEP-2/N-01 确定性模块与 binding 禁止 import app.llm KEPT
R-DEP-3 obs 内除 audit 外禁止依赖 repo（U-18 代价约束） KEPT
R-DEP-4 retrieval 禁 LLM（refine 唯一豁免，P0 未实现） KEPT
Contracts: 4 kept, 0 broken.

$ ../.venv/Scripts/python.exe -m app.core.enums
enums.py 契约自检通过；取值集基数 = {… 'binding_state': 4, 'binding_layer': 4, …}

$ ../.venv/Scripts/python.exe scripts/assert_importlinter.py
[baseline] 干净状态 lint 通过（Contracts: 4 kept, 0 broken.）
[probe] ✅ r-dep-2-no-llm-in-deterministic —— app.guard (L2) → app.llm (L1)：方向合法，但被 R-DEP-2 显式禁止
[probe] ✅ r-dep-1-layers / r-dep-3 / r-dep-4 …
[restored] 还原后 lint 重新通过（Contracts: 4 kept, 0 broken.）
DoD② 通过 —— 4 条契约均已证明「脏了必红」
```

> **R-DEP-2 的运行时镜像本窗口另加了一条**：`TestPackageFacade.test_importing_the_package_does_not_pull_in_the_llm_gateway`
> 用**干净解释器** `subprocess` 跑 `import app.binding` 后检查 `sys.modules` 无 `app.llm*`。
> 必须用子进程 —— 同进程的 `sys.modules` 会被其它测试文件（它们 import `app.llm`）污染，断言会恒假红。

### 3.1 全量 pytest（**1 红 6 错，全部在他人窗口且为环境性**）

```
$ ../.venv/Scripts/python.exe -m pytest -q
1 failed, 1395 passed, 55 skipped, 6 errors in 145.86s (0:02:25)
```

| 现象 | 归属 | 根因（实测） |
|---|---|---|
| `FAILED test_retrieval_fts_pg.py::test_production_embed_doc_schema_matches_query_template` | W2B | `psycopg.errors.ConnectionTimeout` → `127.0.0.1:5432` |
| `ERROR at setup` × 6（同文件，`pg_table` 夹具） | W2B | 同上 |
| 55 skipped = `test_exec_real_pg`(19) / `test_real_redis_lock_and_ratelimit`(14) / `test_audit_append_only`(9) / `test_semantic_materialization`(7) / `test_migration_0003_views`(6) | W2D/W1B/W2A | 全在 `tests/integration/`，连接不可用 |

**环境实测**：`docker ps` → `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`；
`/dev/tcp/127.0.0.1/5432` → `Connection refused`。⇒ **Docker daemon 未运行**，全部红项与 skip 均由连接不可用解释。
**本窗口绑定域：265 passed / 0 skipped**，与上表无交集。

🐞 **顺带发现一处测试健壮性缺陷（属 W2B，只报告不落笔）**：`test_retrieval_fts_pg.py` 的 `pg_table` 夹具
（第 110–117 行）**只捕获 `InsufficientPrivilege`**，于是"库不可达"时异常外逸 → **ERROR**（而非像同项目的
其它集成用例那样 skip）。且同文件的 `@_needs_prod` 用例只判 `PROD_DSN is not None`，库不可达时**失败**而非跳过。
W3A 交付时该文件是"6 skip"（当时 PG 在跑、只是无 DDL 权限），**现在变成"6 error + 1 failed"**——同一文件两种行为，
说明缺的是"不可达 → skip"。已写入 RELAY §给 W2B。

---

## 4. 决策点落定（D 系列）

| # | 决策点 | 落定 | 理由与代价 |
|---|---|---|---|
| **D1** | L4 分数怎么进判定：在线打分 vs 注入 | **(a) 双入口，唯一适配缝 = `scores.adopt_l4_candidates`** | 在线（`l4.score_l4`，W4 用）是真校验；注入（评测/回溯/W2B 预计算）走同一缝，避免两条路各写一份校验 |
| **D2** | 端口签名无问句，而 L2/步③ 需要 | **请求级 `contextvars`**（形状照抄 W3A `set_call_context`） | 取不到时**不判**并置 `question_grain=None`、`scope_was_set=False`，**绝不默认某个粒度**（fail-open 但可见） |
| **D4** | `disclosure`/`clarify_prompt`/`reason` 装不进三字段端口 | `disclosure`→`insight.caveats[]`（**U-26 裁定的唯一载体**）；`clarify_prompt`→澄清节点；`reason`→观测 sink；经 `resolve_detailed` 旁路 | 不塞进 `bindings`（否则"已绑定字段"和"说明文案"混在一个元组里，消费方分不开） |
| **D6** | L4 **上游故障**要不要转 `ambiguous` | **不转，原样上抛** | PRD §12.9 约束④只列"解析失败/τ邻域"两种 fail-safe，上游故障不在列。把它包装成"澄清"= **用产品结论掩盖系统故障**。代价：L4 全不可用时本该澄清的问句变 error（缓解在 W4 观测）。钉法 = **AST 扫描**断言 `l4.py` 无 `except Llm*`（比文本匹配可靠，见 §5） |
| **D7** | 端口 `candidates` 语义（07 附-1 未定义） | **只消费显式 `layer is L4` 的条目**，其余**计数上报**（`ignored_candidates`） | 绑定层的候选另有更权威来源（语义包声明，07 §6.8 步①）。"传进来了却被忽略"必须**可见**，否则 W4 会以为自己传的生效了。语义待架构确认 |
| **D8** | 校准选点并列怎么破（原文只说"最小澄清率"） | `(澄清率, −准确率, −τ)` 取最小 → **要求更强证据** | 两个 tie-break 方向都在保守侧，不存在"为降低澄清率向弱侧滑"的路径 |

**另有一处本窗口主动收紧（有文档依据，非发明）**：校准报告的 `is_finalizable` 原只看"稳定性 + 选点 +
打分器标识 + 日期 + 分离"，本次补上 **`nfr71_satisfied`** 与 **`layer_distribution` 已记录**两条
（依据：§C.4.6 步骤 4 的定稿分支以"满足 NFR-7.1"为前提；步骤 6 的层分布是报告产出）。
理由是**报告自证一致性**：`blocking_actions` 已经写着"澄清率超限 → 回看语义层"，
`is_finalizable` 就不能同时说可定稿 —— 而使用者只会看后者。现加了一条不变量测试钉住
`is_finalizable ⟺ blocking_actions == ()`（五种形态全过）。

---

## 5. 交付期发现并修掉的缺陷（**含测试自身的缺陷 —— 两类分开列**）

### 5.1 实现缺陷（3 处，都会静默出坏结果）

| # | 缺陷 | 后果（为什么危险） | 修法 |
|---|---|---|---|
| 1 | `_try_level3` 用扁平 `refs` 判"命中声明" | `refs` 把 `canonical_asset`/`candidates`/`alternatives` 混在一起 → **canonical 被 RBAC 淘汰时会静默绑到带 `use_when` 条件的 `alternatives`**，却披露 canonical 的文案 = "用一个没验证过的口径，披露另一条口径的文案" | 新增 `ConceptResolution.canonical_ref`，L3 **只认它**且须在过滤后存活 |
| 2 | `tau.check_binds_scorer()` 返回值被丢弃 | docstring 承诺"未校验必须可见"但实现静默 → **"校验通过"与"压根没校验"在观测里长得一模一样**（N-27 约束②的存在意义就是消除这个歧义） | 接住返回值，`False` 时 `reason` 追加 `\|tau_unverified` |
| 3 | `config_lines()` 在无定稿点时输出 `BINDING_TAU=`（空值） | 贴进 `.env` 是解析错误，但**看上去像"待填"** —— 把一个不存在的 τ 伪装成可部署配置 | 改为抛 `ValueError`，并把 `blocking_actions` 带进错误信息 |

### 5.2 测试自身缺陷（7 处 —— **夹具/期望值错了，实现是对的**）

> 这一节单列，是因为"测试红了就先怀疑实现"是本项目反复踩到的坑：以下 7 条**没有一条是实现的错**。

| # | 缺陷 | 真相 |
|---|---|---|
| 4 | `test_four_element_known_value` 期望 `2/6` | 手算漏了中间两对：`(0.9,0.8,0.2,0.1)` vs `(0.9,0.7,0.1,0.2)` 只有 **1 对**不一致 → 正确值 `4/6`。被实现反证（实得 `0.6667`） |
| 5 | `test_stdev_uses_sample_denominator` 期望 `0.1` | 把分差当成**有符号偏差**：`Δ = 最高 − 次高` 恒 `≥ 0`，真实分差是 `[0.1, 0.1, 0.0]`，样本 std = **`0.0577`**（实测）。改夹具为 `[0, 0.1, 0.2]`，两个分母才真分得开（`0.10` vs `0.0816`） |
| 6 | `_sample` 夹具的 `noise` 语义 | 原为"后续重复**同向**偏移"：① 分差恒非负 → 同向偏移**不改变分差**，`noise` 对"分差方差"影响**恒为 0**（参数形同虚设）；② `repeats=3` 只得 **2 个不同取值**（第 2、3 次逐字相同），方差被系统性低估。改为 **`±` 交替**，并给出可手算结论：两候选样本分差 std **恰为 `\|noise[0] − noise[1]\|`** |
| 7 | `test_higher_tau…` 用 `zip(rates, rates[1:], strict=True)` | 两序列长度不等 → **`strict=True` 直接 `ValueError`**。红的是测试自己。改用 `itertools.pairwise` |
| 8 | 两处夹具 `noise` 让分数越界 | `0.90 + 0.30 = 1.20`、`0.90 + 0.20 = 1.10` → 构造期 `ValueError`（实现按 PRD §12.9 约束①**拒绝**越界分，行为正确）。改噪声幅度使其留在 `[0,1]` |
| 9 | `_clean_samples` 5 条样本 | 恒有 1 条落邻域 → 澄清率 `1/5 = 0.20 > 15%`，**被 NFR-7.1 判罚是正确的**。夹具扩到 7 条（`1/7 ≈ 0.1429`），并把原 5 条保留为 `_over_limit_samples` 专门钉"不达标 ⇒ 不可定稿" |
| 10 | 浮点边界踩坑（**记录为知识，非缺陷**） | `0.60 − 0.55` 在 IEEE-754 下是 `0.049999999999999933 < 0.05` → τ=0 已判澄清。这正是 `four_layer._level4` docstring 记录的现象；本用例改用分差明显不等于 ε 的样本，边界由 `four_layer` 的专门用例（**二进制可精确表示**的 τ/ε）钉住，不混进单调性判读 |

### 5.3 门面从未被 import（覆盖缺口）

**发现**：`grep -rn "import app.binding" tests/` **零命中** —— 所有测试都直接 import 子模块。
于是 `__init__.py` 里一个拼错的名字、一条漏掉的 import、一个循环依赖，**都能一路静默到 W4 接线时才炸**（排查成本最高的时刻）。

**修法**：新增 `TestPackageFacade`（4 条）：① `__all__` 每个名字都能 `getattr` 到；② `__all__` 三组
（常量→类→函数）各自 ASCII 有序且组序固定；③ 校准 API 从门面可达（W6 的唯一入口）；④ 干净解释器 import 不拖入 `app.llm`。
同时把 `calibration` 的离线 API 导出到门面。

> ⚠️ 第 ② 条初版写成 `sorted(pkg.__all__)`，被自己的实现反证 —— ASCII 下 `'L'(76) < 'a'(97)`，
> 一把梭会把三组混成一组，**与本仓库既有风格不符**。已按真实约定（三组各自有序）重写。

---

## 6. 已知限制（具名登记，不假装已满足）

| # | 限制 | 影响 | 何时解除 |
|---|---|---|---|
| L1 | 🟡 **DoD① 的"双双落库"差最后一步（W4 写入）** | 表结构阻塞**已解除**（W1B 迁移 0004 建了 `app.query_plan`，含 `binding_state` NOT NULL CHECK / `binding_layer` CHECK，取值集与 enums 逐字一致 + 离线契约单测钉住）。澄清率异常时**仍无法定位哪层失效**，直到 W4 把 `(state, layer)` 写进该表 | W4 接线（写入动作）。一个观察留给 W1B/W4：`binding_layer` 可空而 `binding_state` NOT NULL —— 本层**恒产出** `(state, layer)`（`unresolved` 时 `layer=L1`），W4 写库时恒有值，可空性不影响正确性 |
| L2 | **注入路径的 τ 身份校验恒通过** | `CandidateRef` 只有 `{asset_id, score, layer}`，**没有打分器标识** → `model_id`/`prompt_version` 只能取 τ 自己那组。走注入路径的调用方（评测夹具/离线回溯）**必须自己保证**分数来源与 τ 所绑一致 | W0 给 `CandidateRef` 补标识（建议 `RerankScore` 直接进候选，或加 `scorer_id`）。在线路径（`score_l4`）**是真校验**（标识取自 `LLMResponse`） |
| L3 | **观测出口没有实现**（指标本体已由 W0 落，见 §10 回执②） | 默认 `NullBindingObserver` 什么都不做（`__slots__=()`）→ 不接线时 **N-27 约束⑤ 的指标面是缺的**；刻意不做"默认写日志"：那会让每条判定路径依赖日志配置可用性 | W4 实现 `BindingObserver` 适配器（`service.observer` 属性就是为"查到底接的是真适配器还是空实现"而暴露的），在 `on_binding` 里调 `obs.metrics.observe_binding_state(event.state)` / `observe_binding_layer(event.layer)` —— **别再自行登记同名 Counter**（会变第二真相） |
| L4 | 🔴 **L4 从未接过真实 LLM** | 全部 33 条 `l4` 单测用 `httpx.MockTransport` 固定响应（离线纪律）。⇒ **真实模型的分数量纲是否让 τ=0.20 成立、E-5 稳定性是否过关，均未实测** | **首次真跑打分器后**（W3-INT / W6）。在此之前 `is_finalizable` 必为 `False`，**τ 不得定稿** —— 这正是该校验存在的意义 |
| L5 | 校准的 `accuracy_target` 无上游数值 | §C.4.6 步骤 3 只说"满足绑定准确率目标"、**没给数值** → 本窗口做成**必填参数**（编一个默认值 = 逼人相信它） | 由业务/架构给口径 |
| L6 | `layer_distribution` 只能由调用方带入 | 本模块离线且只吃分数，**无法自行得出** → 留 `None` 而非编一份 | W4 的观测/审计提供 |
| L7 | 排序键实际只用 4 项（`certified / quality_score / freshness_sla / ref`） | 07 原表的"**血缘完整**"与"**成本**"在语义包中**没有对应字段** | W1A 补字段 |
| L8 | `quality_gates.max_staleness_hours` 未实施 | 需要**实际新鲜度**，包内只有 SLA **声明**（不是实测）；loader 与本步都没实施 | W1A/W0 |
| L9 | 🔴 **`platform_admin` 的白名单结论与黑名单相反**（只报告不裁决） | 同一 ref 上"能不能绑"与"能不能查"两个判据结论相反：`asset_allowlist` 放行 `order_paid.receiver_phone`，而 `is_denied_column` 恒 `True` → **gate1 R07 会拒绝**。本层取白名单（它才是角色感知的那一个） | 架构裁定（RELAY §给架构） |
| L10 | 表级概念（`aliases` 的 `maps_to_kind=asset`，如 `商品`→`product`）解析不出列级绑定 | 归 `unresolved`（表级不是字段绑定；意图分类应拦在前面） | 架构确认 |
| L11 | `declared_ambiguous` 的概念**允许**被 L4 判 `resolved_unique`（读法 3） | `ambiguous: true` 在 SCHEMA §5.2 的含义是"没有规范字段"⇒ 与"禁止 L4 判唯一"不同义。实测 `城市` 温度=0 下两分接近 → 落邻域 → `ambiguous`，与 PRD §6.3.1 期望一致 | 架构确认读法 |

---

## 7. 待架构窗口分配编号（**本窗口未自行开号**，下一可用 = `U-65`）

| 候选 | 问题 | 位置 |
|---|---|---|
| 1 | `CandidateRef` 缺"分数来源"字段：L1–L3 的 `score=0.0` 是**占位**（那三层本无分数）→ 消费方读 `score` 前必须先看 `layer` | `four_layer._candidate` |
| 2 | `CandidateRef` 缺打分器标识 → 注入路径 τ 身份校验恒通过（见 L2） | `service._split_candidates` |
| 3 | `BindingPort.resolve` 签名**无问句位**，且 07 附-1 **未定义 `candidates` 语义** → 本窗口以 `contextvars` + "只消费 L4 标记"绕过（D2/D7） | `service.py` 读法 2/3 |
| 4 | `platform_admin` 在两判据上结论相反（见 L9） | `filters._step_permitted` |
| 5 | 表级概念解析不出列级绑定（见 L10） | `filters.resolve_concept` |
| 6 | `declared_ambiguous` 是否允许被 L4 判唯一（见 L11） | `four_layer` 读法 3 |
| 7 | `BindingResult` 三字段装不下 `disclosure`/`clarify_prompt`/`reason` → 需 `resolve_detailed` 旁路（D4） | `service.BindingOutcome` |
| 8 | 校准选点 tie-break 原文只说"最小澄清率"（D8） | `calibration.calibrate` |
| 9 | `query_plan` 表缺 `binding_state`/`binding_layer` 列（DoD① 硬前置，见 L1）——更偏"给 W1B 的需求"，是否开号由架构定 | 迁移 0001–0003 |

---

## 8. 复现指引（给 W3-INT）

```bash
cd CommerceQL/backend        # ⚠️ ruff/mypy 必须在 backend/ 下跑，在仓库根会 E902

# 本包（全离线，秒级）
../.venv/Scripts/python.exe -m pytest tests/unit/test_binding_*.py -q

# CI 对齐的四道静态门禁
../.venv/Scripts/python.exe -m ruff check .
../.venv/Scripts/python.exe -m mypy app
../.venv/Scripts/lint-imports.exe                    # 必须用控制台脚本；-m importlinter.cli 是假绿
../.venv/Scripts/python.exe -m app.core.enums         # 枚举契约自检（含 binding_state/layer 基数）
../.venv/Scripts/python.exe scripts/assert_importlinter.py   # DoD② 注入 → 必红 → 还原

# 全量（约 2.5 分钟；前台会超时，建议后台跑并落日志）
../.venv/Scripts/python.exe -m pytest -q
```

**接线前的三件事**（详见 `app/binding/__init__.py` 的"给 W4"节，那里是**唯一权威**）：
装配（含 `assert_usable_tau()` + gauge）→ 每请求 `set_binding_scope`（否则 L2 与步③ **静默失效**）→ 观测出口必须有实现。

---

## 9. 提交

| commit | 内容 |
|---|---|
| `feat(w3c)` | `app/binding/**` 10 模块 + `tests/unit/test_binding_*.py` 7 文件 |
| `docs(w3c)` | `reports/w3c/{PROMPT,DELIVERY,RELAY}.md` |

---

## 10. 回执核验（2026-09-17 深夜，据 W1B/W0 回执实测）

用户转达两条外部回执：① W1B 两表结构阻塞已解除；② W0 `1c24f14` 落了 binding 计量端。**未盲信声称，逐一实测核验**：

| # | 声称 | 核验方式 | 结果 |
|---|---|---|---|
| 1 | W1B 迁移 0004 建了 `query_plan` 表 | 读 `app/repo/migrations/versions/0004_cost_ledger_and_query_plan.py` | ✅ `task_id`(PK)/`plan_json`(jsonb)/`plan_summary`/`bundle_version`/`binding_state`/`binding_layer`/`confidence`，**两列均 NOT NULL/CHECK 约束齐全** |
| 2 | 列值集与 enums 逐字一致 | 迁移内 `_BINDING_STATES`/`_BINDING_LAYERS` 快照 vs `python -m app.core.enums` 实跑 `.value` | ✅ `resolved_unique/resolved_default/ambiguous/unresolved` 与 `L1/L2/L3/L4` **逐字一致**；另有 `test_migration_0004_runtime_contract.py` 离线契约单测钉住 |
| 3 | W0 已落 binding counter 本体 | 读 `app/obs/metrics.py` | ✅ `BINDING_STATE_TOTAL`/`BINDING_LAYER_TOTAL` + `observe_binding_state(event.state)`/`observe_binding_layer(event.layer)`，**枚举即准入校验**、线程锁；无同名重复登记必要 |

**状态订正**（已同步改回本文档 §2/§6 与 `app/binding/__init__.py`）：

- DoD①：🔴 缺表阻塞 → 🟡 **表结构已解除，差 W4 写入动作**（装配点写入 `query_plan` 两列）。
- L1 同步落库：🔴 → 🟡，同上。
- L3 观测出口：观测出口本身仍缺（W4 `on_binding` 实现），但**指标本体已存在**——W4 直接调 `obs.metrics.observe_binding_state/layer`，**不要再自行登记同名 Counter**。

**门禁未回归**：回执核验后复跑绑定域全量 —— 265 passed / ruff All passed / mypy 104 files clean / lint-imports 4 kept。W0/W1B 的改动未破坏 `app/binding/**`。

**仍待分配**：§7 的 9 条候选编号——§7 原记"下一可用 = U-65"**已过时**（架构窗口已裁 A1–A22 = U-65~86，见 docs/07 v1.0 §4.9），现下一可用 = **U-87**；其中 #7/#8/#9/#10 与 7 个 `llm_*` 指标命名**用户明确待架构裁决，不先斩后奏**。
