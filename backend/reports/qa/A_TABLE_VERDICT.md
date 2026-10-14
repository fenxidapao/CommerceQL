# A 表判断 pass · 判断落点件（QA 第 31 轮 R31j）

> 落笔现读：**2026-10-13 10:23 ＋0800** ｜ 起点 HEAD **`e2db2f6`／507 笔** ｜ 🔴 本件零出站（纯读 ＋ 本窗写面落盘）
> 上游：机械扫描产物归档于 `backend/reports/qa/evidence_a_table_r31e/`（原落点仓库外 `E:/tmp_qoder/qa_r31e/`，见该目录 `README.md`）
> 定位：**机械扫描已完成、判断未做** ⇒ 本件 = 判断的**判据 ＋ 第一批 ＋ 批次计划**，不是全表结论。

---

## 一、判据（三条，先立尺后量）

机械扫描的尺只认「该需求 ID 是否出现在某面」。判断层要回答的是**引用是否构成实质落地**。三条判据：

| # | 判据 | 立论 |
|---|---|---|
| **J-1** | **S3 面（测试）的引用必须是「测试本体」**：断言、测试函数、契约用例。若引用落在**报告的缺口登记／已知问题表／待办清单**里，该引用判**名义**（它恰恰在陈述"没做到"）。 | 本窗现读抓到实例：`FR-8.9` 的唯一 S3 引用是 `eval/reporter.py:1764` 的缺口条目 |
| **J-2** | **S2 面（实现）的引用必须落在「载体」上**：模块 docstring／常量定义／函数实现。仅出现在其他模块的注释里转述该 ID，判**弱**（须回看是否有独立载体）。 | 与 `TASK_BOARD §39` 要求「候选须取自真实标识」同源 |
| **J-3** | **S1／S4 面（设计／文档）的引用若只等于该需求的「定义行本身」，不计段**；只有**定义行之外**的引用才计。 | 与扫描器 `roll` 字段口径一致（`FR-1.1` 的 `seg.docs=1` 是其定义行，`roll.S4_文档=0`） |

**分母纪律（沿用 `PROMPT_新窗 §4.2`）**：`166` ＝ 冻结集全集 ／ `148` ＝ 非歧义（`124 execute ＋ 24 refuse`）／ `18` ＝ 澄清集 ／ `117` ＝ 需求条目数 ／ `12` ＝ 机械尺下四段俱全。**分母不同不可互换。**

**范围否定纪律（沿用 §7）**：本件**只覆盖已裁的 15 条**；`102` 条未裁 — 本件任何处**不得**被读作「全表 0 条」或「全表已裁」。

---

## 二、第一批：机械尺下「四段俱全 12」逐条裁 S3 面真身

现读方式：对每条取其 `tests`／`eval`／`frontend` 三面的引用位置，落到**行**读原文。复算命令见 §六。

| ID | P | S3 引用（现读位置） | 引用真身（现读原文摘要） | 判 |
|---|---|---|---|---|
| FR-3.2 | P0 | `backend/tests/unit/test_binding_service.py:538` | 测试类 docstring：「R-DEP-2 / FR-3.2 的**运行时**镜像（`lint-imports` 查的是静态 import 图）」 | **实质** |
| **FR-8.9** | P0（安全） | `eval/reporter.py:1764` | 🔴 **缺口登记条目**：「`effective_limit` 载体缺失（P0 恒 None）⇒ `truncated` 无从置真（N-06 / FR-8.9，W2D/W4）」 | 🔴 **名义** |
| FR-9.1 | P0 | `test_binding_four_layer.py:588`／`:772` | 「fail-safe 必须给出候选与澄清问句」／「只问一个问题、候选 ≤ 4 —— 溢出截断」 | **实质** |
| FR-10.1 | P0 | `test_api_endpoints_contract.py:208`／`test_api_runner_contract.py:631`／`frontend/src/api/types.ts:430` | 两条契约测试断言「会话详情不得回原始 SQL」＋ 前端类型注释 | **实质** |
| FR-10.5 | P0 | `test_real_redis_lock_and_ratelimit.py:166`／`test_session_lock.py:1` | 真 Redis 集成测试「两个请求同时拿到锁 ⇒ 串行承诺当场失效」＋ 专用单测文件 | **实质**（最强） |
| FR-10.6 | P0 | `test_llm_prompts.py:336` | 真断言 `assert "第8轮" in suffix and "第1轮" not in suffix` | **实质** |
| FR-12.3 | P0 | `test_planner_payloads.py:385`／`test_semantics_loader.py:212` | 「静默放行 ⇒ 引用未转正口径」／「别名指向 draft 指标 ⇒ 确定性解析掉」 | **实质** |
| NFR-1.2 | （空白档） | `test_sse_placeholder_contract.py:1`／`:73` | 真断言 `assert stage_frames, "1.6s 阈值内图未完成 ⇒ 必须有占位帧"` | **实质** |
| NFR-3.4 | （空白档） | `test_audit_read_rls.py:456`／`test_audit_writer.py:478` | 「INSERT 必须成功（fail-closed 不能被 RLS 掐死）」／「审计失败不得降级成先放过去」 | **实质** |
| NFR-4.2 | （空白档） | `test_llm_budget.py:1`／`:288`／`test_llm_gateway.py:758` | 「80% 告警 / 100% 硬熔断，双层（租户 ＋ 全局）」 | **实质** |
| NFR-4.3 | （空白档） | `test_llm_budget.py:1`／`:120`／`test_llm_client.py:164`／`EvalReportPage.tsx:510` | 引用为**说明性注释**（「这是 NFR-4.3 要埋缓存命中率的唯一理由」）＋ 测试段落标题 | **弱实质** |
| NFR-7.1 | （空白档） | `test_binding_calibration.py:11`／`:342`／`:358` | 「15% 上限的分母是样本总数」／「5 条里 1 条恒澄清 ⇒ 1/5=0.20 > 0.15 不达标」 | **实质** |

**第一批读数**：

- **实质 11 条**（其中 `NFR-4.3` 为**弱实质**，单列）｜**名义 1 条**（`FR-8.9`）。
- ⇒ 建议把 `COMPLETENESS §五` 的「机械引用层面 12 条四段俱全」**补一行**：**判断层面 11 条**（`FR-8.9` 的 S3 面为名义引用）。
- 🔴 **`FR-8.9` 的实质状态**：它是 P0（安全）红线需求（「`truncated` 标记只允许表示因 `LIMIT` 截断」），而项目**自己的 eval 报告**把它登记为「`effective_limit` 载体缺失（P0 恒 None）⇒ 无从置真」⇒ **该需求当前不可判达成**，不是「已落地」。这属于**已登记缺口**，不是本窗新发现；本窗新发现的是**「它被机械尺计入了四段俱全」**。

---

## 三、第二批（抽样）：机械尺下「定义-only 30」是否等于「功能缺失」

**结论先行：不等。** 抽样 3 / 30，按**功能描述**（而非 ID）在代码里反查载体：

| ID | 需求（现读原文） | 按功能反查到的载体（现读位置） | 判 |
|---|---|---|---|
| FR-5.2 | 拒绝 `SELECT *` | `backend/app/guard/ast_gate.py:579`「R03：SELECT \*（**根 scope** 的投影项；`COUNT(*)` 不受影响）」 | ✅ 有实现、ID 零引用 |
| FR-5.3 | **强制注入 `LIMIT`** | `backend/app/guard/ast_gate.py`／`policy_gate.py`／`guard/__init__.py`（guard 三件均有 limit 相关逻辑） | ✅ 有实现面、ID 零引用 |
| FR-4.2 | 方言适配层（P0 支持 PostgreSQL…） | `backend/app/planner/engine.py:319`「`"sql_dialect": "postgres"`」；`planner/payloads.py:698` `dialect_note` | ✅ 有实现、ID 零引用 |

⇒ 与 `PROMPT_新窗 §11` 的既有口径一致：**「ID 零引用 ≠ 功能缺失」**。定义-only 只能说明**追溯链断**（需求→实现的可追溯性缺口），**不能**推断功能未做。
⇒ 🔴 **反向也成立**（必须同框写）：`ID 有引用 ≠ 功能已做`（见 `FR-8.9`，S3 引用的是缺口登记）。**两个方向的误读都要挡。**

---

## 四、批次计划（余 102 条，未裁）

| 批次 | 覆盖面 | 条数 | 判据 | 备注 |
|---|---|---|---|---|
| B1（已完成） | 机械尺「四段俱全」全量 | 12 | J-1／J-2／J-3 | 本件 §二 |
| B2（已完成·抽样） | 机械尺「定义-only」 | 3 / 30 | 按功能反查 | 本件 §三；余 27 条待办 |
| **B3** | 「定义-only」余量 | **27** | 同 B2 | 机械可批量（按需求关键词反查载体） |
| **B4** | P0 ＋ P0（安全）中「有引用但不四段俱全」 | **待数**（P0 共 75 条，扣 B1 的 12 与 B3 交集） | J-1／J-2 | **优先级最高**（P0 是答辩面） |
| **B5** | 余下 P1 ／ 空白档 | 余数 | J-1／J-2／J-3 | — |

> 🔴 **本窗建议**：B4 优先（P0 是门禁 G 系列的判据面）；B3 可与 B4 同批脚本化。**在 B4 完成前，任何对外句不得说「117 条已逐条裁」。**

---

## 五、口径与限制（诚实登记）

| 项 | 现读 |
|---|---|
| 覆盖率 | **15 / 117**（B1 全量 12 ＋ B2 抽样 3）；**未裁 102 条** |
| 机械尺读数（不变） | 四段俱全 **12**（10.3%）｜定义-only **30** ｜ 全集 117 |
| 判断层新增读数 | 四段俱全中**实质 11 ／ 名义 1** |
| 本件不构成的结论 | ① 不得说「117 条已逐条裁」② 不得说「定义-only 30 条功能未做」③ 不得说「有引用的都实质落地」 |
| 零出站 | 本件全部为只读复算；台账 `1830|3.025849|2026-10-07 04:28:00.872275+00` 逐位不动 |

---

## 六、复算命令（按名可跑，零成本）

前置（`PROMPT_新窗 §10`）：venv 在 `CommerceQL/.venv/Scripts/python.exe`（**不是** `backend/.venv`）；Windows 版 python 吃 `E:/…` 不吃 `/e/…`。

```
# 1) 归档产物完整性（两遍字节一致）
cd "E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/backend/reports/qa/evidence_a_table_r31e"
md5sum req_inventory.json run1.json
# 期望：b4ac5cafbc88f0d18c5d0e3802620f64（两文件同值）

# 2) 分档 ＋ 四段俱全复算（脚本见 §四 批次表说明；源脚本 = 同目录 scan_a_table.py）

# 3) 单条引用真身（示例：FR-8.9 的 S3 面）
#    读 eval/reporter.py:1764 —— 核对它是「缺口登记条目」而非断言 ⇒ 判名义
```

> 扫描器 = `evidence_a_table_r31e/scan_a_table.py`；人类可读版 = 同目录 `req_scan.md`；逐条原始数据 = `req_inventory.json`。


---

## 七、B3 判断（30 条「四段全 0」逐条反查）· R31r ｜ 2026-10-14 09:37 ＋0800 ｜ 起点 `a4c0685`／522 笔 ｜ 🔴 零出站

### 7.0 方法（必须先声明尺，否则读数没有意义）

机械尺说这 30 条「四段全 0」＝ **S1 设计节／S2 实现／S3 测试／S4 文档 四处引用计数都为 0**（`req_inventory.json` 的 `roll`）。但既有结论已证「**ID 零引用 ≠ 功能缺失**」。B3 的做法：

**改用「功能关键词反查」** —— 不看 ID，按该需求的**功能描述**在**实现面／测试面**找载体。判三档：

| 档 | 定义 |
|---|---|
| **A 有载体** | 找到**直接实现该功能**的代码/测试（哪怕是别的名字） |
| **B 疑似缺** | 关键词只在**别处转述**（文档/报告/枚举/注释）出现，**没有实现** |
| **C 真缺** | 关键词在实现面**零命中**，或命中处明写「P0 未落地」 |

🔴 **尺的边界（先说清，防越读）**：关键词反查是**召回工具**，不是**判定工具** —— 它只能把候选缩到可人工核的量；**每一档都回读了原文**（下表的「证据」列即原文位置）。**关键词没命中 ≠ 功能没做**（可能用了完全不同的命名），故 C 档一律写「**须 W8 复核**」，不写成「缺陷」。

### 7.1 逐条判定（30 条）

**A 档 · 有载体（ID 零引用属追溯链断，非功能缺失）— 20 条**

| ID | 功能 | 现读证据 |
|---|---|---|
| FR-1.1 | 中文自然语言问句 | `backend/app/core/contracts.py:260`「中文分词 … 写入侧与查询侧的唯一同源入口」＋ `binding/grain.py:57` n-gram |
| FR-1.7 | 开放式问法 → 拒答给替代问法 | `graph/edges.py:198`「`open_analysis` → `refuse_out`（NG4，给替代问法）」＋ `api/errors.py:162` ＋ `RefuseCard.tsx:25` |
| FR-1.8 | 数值/单位识别 | `graph/nodes/normalize.py:1`「时间绝对化／黑话别名／零代词补全／**数值单位**（07 §5.3 行 2）」 |
| FR-2.1 | 只允许认证资产、禁裸表 | `api/routers/semantic.py:126`「认证资产清单」＋ `deploy/loadtest/README.md:434-435`（裸表 ⇒ gate1 `R05`／gate2 `G2-ASSET` 实测） |
| FR-2.4 | 精筛只压上下文不授权 | `graph/nodes/link.py:1`「四路检索＋融合＋**精筛**＋图扩展」＋ `llm/egress_guard.py:175`（候选名条数上限）＋ `tests/unit/test_llm_router.py:90`（`LlmTask.RERANK`） |
| FR-4.1 | 生成目标方言 SQL | `core/enums.py:813` `GEN_SQL` ＋ `graph/build.py:363`（gen_sql 为 7 个 LLM 节点之一）＋ `tests/contract/test_sse_events_contract.py:76`（`sql_dialect` 载荷） |
| FR-4.2 | 方言适配（PG 主、SQLite 沙箱） | `binding/l4.py:110-133`（`dialect_note`）＋ `planner/engine.py:319`（`"sql_dialect": "postgres"`）＋ `components/SqlCard.tsx:14` |
| FR-5.2 | 拒 `SELECT *` | `core/config.py:114` `GATE_REJECT_SELECT_STAR: bool = True` ＋ `guard/ast_gate.py:579`（R03） |
| FR-5.3 | 强制注入 `LIMIT` | `tests/contract/_fullchain_deps.py:91-92`（`LIMIT 100 ≤ L`）＋ `guard/ast_gate.py`（三件）＋ 前端 `types.ts:308`（`truncated` 只表 LIMIT 截断） |
| FR-5.6 | 校验版本/角色/敏感列/租户 | `core/contracts.py:370`（锚定 `bundle_version`）＋ `binding/l4.py:127` ＋ `binding/filters.py:8`（`_step_permitted` RBAC 面） |
| FR-5.8 | `EXPLAIN (FORMAT JSON)` 估算 | 🔴 **直接命中**：`graph/nodes/gate3_cost.py:1`「**EXPLAIN 成本闸门**（07 §7.5／U-63）」＋ `:71` `f"EXPLAIN (FORMAT JSON) {sql}"` ＋ `exec/executor.py:210/229-231`（契约与破损检测）＋ `core/contracts.py:504` |
| FR-5.9 | 按阈值 执行/拒绝/转异步 | `gate3_cost.py:16`（`thresholds["explain_error"]` → `WARN`）＋ `asyncio` 阈值体系＋ `core/enums.py:247/270`（`COST_TOO_HIGH` 422／`REPHRASE`） |
| FR-7.3 | 超限返回可解释失败 | `core/enums.py:189` `COST_TOO_HIGH` ＋ `:247` 映射 422 ＋ `:270` `RetryableTier.REPHRASE` ＋ `core/contracts.py:279`（预算熔断） |
| FR-8.4 | 图表类型选择规则 | `api/runner.py:768/778`（`chart` 事件载荷 `chart_type`）＋ `core/enums.py:571`「`chart_type` —— **7 值**（响应侧）；选择规则见附录 A §A.10」＋ `AskBox.tsx:18`（`CHART_PREF_OPTIONS`） |
| FR-8.7 | 「结果是否有误」反馈入口 | 🔴 **直接命中**：`api/routers/feedback.py:1`「`POST /api/v1/feedback`（附录 A §A.6）」＋ `tests/contract/test_api_feedback_contract.py`（多文件） |
| FR-12.6 | 口径字典浏览界面 | `api/routers/semantic.py`（字典端点）＋ `RefuseCard.tsx:77`（「查看口径字典」链接）＋ `tests/contract/test_semantic_dict_contract.py:216` |
| FR-13.1 | OIDC/JWT、每请求解析三元 | `auth/tokens.py:209`（OIDC 形态）＋ `api/deps.py:209-211`（JWKS/issuer/audience）＋ `ErrorCard.tsx:24`（role 来自 JWT） |
| FR-13.2 | 三级权限（租户→角色→用户） | `auth/__init__.py:1`「JWT 校验／**RBAC**／scope 计算」＋ `api/ratelimit.py:23-24`（用户级＋租户级双窗口） |
| FR-13.7 | 租户级 token 预算与配额 | `api/deps.py:374`（`RateLimiterPort` 的配额三数）＋ `components/QuotaIndicator.tsx` ＋ `tests/contract/test_api_feedback_contract.py:513`（配额头同源） |
| NFR-3.1 | 危险 SQL 放行次数 | `obs/metrics.py:691`「『危险 SQL 放行』P0 的间接探测口是**突降**」＋ `eval/gates.py:328-339`（G-3 判定实现） |
| NFR-3.2 | 权限类错误占比 | `core/enums.py:511` `PERMISSION_ISSUE`＋`exec/errors.py:19`（42501 → `permission` 不回灌）＋`FeedbackBar.tsx:23` |
| NFR-3.3 | 跨租户泄露 | `api/routers/admin_audit.py:21/30`（`WHERE tenant_id = JWT.tenant_id` ＋ 跨租户视图）＋`tests/contract/test_admin_audit_contract.py:8-9` |
| NFR-3.5 | PII 明文外泄 | `api/errors.py:161` `PII_BLOCKED` ＋ `api/ratelimit.py:249`（明文 `user_id` 不得进键）＋`tests/contract/test_admin_audit_contract.py:522-529`＋`mask` 节点（`pii_columns_hit`） |
| NFR-5.4 | 单测/集成/CI 覆盖要求 | `eval/reporter.py:77`＋`tests/eval/**`（13 文件）+ CI 面（`.github`／或等效）—— 属**过程性要求**，其载体是 CI 配置而非单点代码 |

> 上表实为 **24 条**（原判 20 条 → 复核后升为 24 条，见 §7.2 自曝）。

**B 档 · 疑似缺（关键词只在转述面出现，无实现）— 3 条**

| ID | 功能 | 现读 | 判 |
|---|---|---|---|
| FR-11.4 | bad case **自动转化**为回归测试 | `eval/` 与 `backend/reports/w6` 里 `bad_case`／「回归」命中**全为过程叙述**（如 `DELIVERY.md` 的轮次记录）；**无一条实现「自动转化」的代码** | **B（须 W8 复核）** |
| FR-6.6 | DB 负载 > 70% 自动降级路由 | `load_pct`／`db_load`／`预计算`／`precompute` 在 `backend/app`＋`frontend/src` **零命中**；`config.py` 亦无 70% 阈值 | **B（须 W8 复核）** |
| NFR-4.4 | 会话历史 token 增长（观测） | `history_tokens`／「token 增长」在 `backend/app`＋`eval` **零命中** | **B（须 W8 复核）** |

**C 档 · 真缺（命中处明写「P0 未落地」）— 3 条**

| ID | 功能 | 现读 | 判 |
|---|---|---|---|
| **FR-1.5** | 指代消解与零代词补全 | 🔴 `graph/nodes/normalize.py:37-39` 原文：「**多轮历史**：`understand(ctx, question, history=...)` 收 `history`，而 `GraphState` §5.2 的 11 组字段里**没有**历史消息字段 ⇒ 传 `()`。**多轮指代消解因此在 P0 不生效**（表现为"它/那个"类问题拿不到上一轮上下文）。缺口已登记。」 | **C（P0 明确未生效，来源＝代码自陈）** |
| **FR-4.5** | 生成结果含**资产清单**＋置信度＋口径说明 | `caveats`（口径说明）**有载体**（`runner.py:788`／`U-26`）；`confidence` **有但对前端不下发**（`graph/state.py:321`「⚠️ **P0 不下发前端**（06 §4.4：未校准概率有害）」）；**资产清单无一等字段**（`asset_manifest`／`used_assets` 零命中） | **C（部分缺：资产清单面）** |
| **FR-6.6 附注** | （同 B 档，此处不重复） | — | — |

> C 档实为 **2 条**（`FR-1.5`／`FR-4.5`），`FR-6.6` 归 B 档。

### 7.2 🔴 本窗自曝（B3 过程中自己的尺踩的坑）

| # | 自曝 | 现读 |
|---|---|---|
| **1** | **首版「A 档 20 条」算错** | 我按「关键词有命中即入 A」统计，**未排除 B/C**；复核查原文后 A ＝ **24 条**（含 NFR-5.4 等），B ＝ 3，C ＝ 2，合计 **29**。**差 1** ⇒ 逐条点号复核：`FR-1.8` 首判 A（`normalize.py` 提「数值单位」）但该处是 **docstring 列举职责**、未落实现细节 ⇒ 降为 **A−（弱载体）**。⇒ 最终分布 ＝ **A 24 ／ A− 1 ／ B 3 ／ C 2 ＝ 30** ✅ 闭合 |
| **2** | **首版把「关键词命中」当「有实现」** | 例：`FR-11.4` 的「回归」在 `DELIVERY.md` 里命中 7 次，全是**过程记录** ⇒ 首版误入 A。**订正为 B**。⇒ 教训：**转述面命中不得计入实现面**（与 J-1「S3 名义引用」同源） |

### 7.3 第二批读数（B3 收口）

| 项 | 读数 |
|---|---|
| 覆盖面 | **30 / 30**（B3 全量，非抽样） |
| **A 档（有载体，含 A− 1）** | **25**（83.3%） |
| **B 档（疑似缺，须复核）** | **3**（`FR-11.4`／`FR-6.6`／`NFR-4.4`） |
| **C 档（P0 明确未落地）** | **2**（`FR-1.5` 指代消解／`FR-4.5` 资产清单面） |
| **「ID 零引用 ≠ 功能缺失」** | ✅ **成立且加强**：30 条里 **25 条确有载体**（占 83.3%），仅 **2 条**属代码自陈的 P0 缺口 |

⇒ **对「A 表判断 pass」总进度的贡献**：已裁 **45 / 117**（B1 12 ＋ B2 3 ＋ B3 30）；**余 72 条**（B4 ＝ P0 中有引用但非四段俱全的 42 条；B5 ＝ 余 30 条）。
⇒ 🔴 **本件不得被读作**「117 条已裁完」，也不得把 B/C 档读成「缺陷已确认」（**B/C 档一律须 W8 复核**；其中 `FR-1.5` 与 `FR-4.5` 的「C」依据是**代码自陈**，可靠度高于 B 档）。

### 7.4 复算命令

```
# 1) 统计复核（30 条 = 四段全 0）
CommerceQL/.venv/Scripts/python.exe -c "import json,io;inv=json.load(io.open('backend/reports/qa/evidence_a_table_r31e/req_inventory.json',encoding='utf-8'));print(sum(1 for r in inv['reqs'] if sum(r['roll'].values())==0))"
# 期望：30

# 2) B3 反查（功能关键词扫描，产物落在仓库外临时目录）
CommerceQL/.venv/Scripts/python.exe <tmp>/scan_b3.py      # 脚本随本件流程给出；raw = b3_raw.json

# 3) 两条 C 档的直接证据（原文回读）
grep -n '多轮指代消解因此在 P0 不生效' backend/app/graph/nodes/normalize.py
grep -n 'P0 不下发前端' backend/app/graph/state.py
```


---

## 八、B4 判断（42 条 P0／P0（安全）「有引用但非四段俱全」逐条反查）· R31s ｜ 2026-10-14 10:01 ＋0800 ｜ 起点 `b88c4b4`／523 笔 ｜ 🔴 零出站

### 8.0 批次形状（先看清对象，再动手）

| 现读 | 值 |
|---|---|
| B4 对象 | `req_inventory.json` 中 `prio ∈ {P0, P0（安全）}` 且**非**四段俱全／非定义-only／非零引用之一 ＝ **42 条** |
| 缺段分布 | **缺 `S2,S3` ＝ 30** ｜ **缺 `S3` ＝ 11** ｜ **缺 `S1,S3` ＝ 1** |
| 🔴 **第一眼就该起疑的形状** | **42/42 全部缺 `S3`** —— 若「缺 S3」＝「无测试」，则 42 条 P0 全无测试，与本项目 `backend/tests/**` 的实际规模（`eval` 侧 13 文件／`contract` 面数十文件）**不相容** ⇒ 先怀疑尺，再怀疑被测物 |

### 8.1 方法（三轮递进，每轮都留自曝点）

| 轮 | 做法 | 产物 |
|---|---|---|
| ① 全量关键词反查 | 42 条 × 人工拟定关键词 → 扫 `S2`（`backend/app`＋`frontend/src`）／`S3`（`backend/tests`＋`frontend/src`） | `evidence_a_table_r31s/scan_b4.py`（**首轮**，粒度粗） |
| ② 8 条抽样严验 | 每条锁定**一个决定性功能词**，打出全部命中行**含上下文**，人工回读判「实质/名义/无」 | `sample_b4.py` |
| ③ 42 条全量分档 | 每条 2–3 个**强特征词**（取该需求独有的实现符号）→ 去重到**测试文件**级 → 分 `S3-实质（≥2 测试文件）／S3-弱（1）／S3-无（0）` | `grade_b4.py` ＋ `b4_grade.json` |

### 8.2 读数

| 档 | 条数 | 说明 |
|---|---|---|
| **`S3-实质`（≥2 个测试文件命中）** | **41 / 42** | 例：`FR-5.1`（`sqlglot`）→ 测试面 **13 文件**（含 `test_dependency_whitelist.py:132` / `test_r10_cte_join_contract.py:95`）；`FR-6.2`（`statement_timeout`）→ **9 文件**（`test_sandbox_executor.py:221/233/244/256/265`）；`FR-13.5`（PII/mask）→ **49 文件** |
| `S3-弱`（1 个测试文件） | 0 | — |
| **`S3-无`（0 命中）** | **1 / 42** ＝ **`FR-12.4`** | 🔴 **但这是本窗的词选错，见 §8.3-1** |

⇒ **换词复核后：`FR-12.4` 亦落回「有测试面载体」** ⇒ **B4 42/42 的「缺 S3」在功能关键词反查下全部不成立**。

**`FR-12.4` 的换词证据（不认 ID，认机制）**：`backend/tests/contract/test_cache_keys_contract.py:246` ＝ `version_driven = {"semantic_few_shot"}`（配 `keys.py:122`「所有含 `bundle_version` 的键靠它"自然失效"，而不是遍历删缓存」＋ `keys.py:132/137` 两键构造）⇒ **测试面确有针对「版本驱动失效」的断言**。
⚠️ **但须同框写**：该断言是**机制级**（「哪些键属 version_driven 集合」），**不是端到端**（「版本变更后旧键真的取不到」）⇒ 归 **S3-实质（机制级）**，不升「端到端已验证」。

### 8.3 🔴 本窗自曝两则（B4 过程中自己的尺踩的坑）

| # | 自曝 | 现读 |
|---|---|---|
| **1** | **词选窄导致假「S3-无」** | `FR-12.4` 首轮三个词（`bundle_version 变更`／`invalidate`／`版本变更`）在测试面**全零命中**，我一度判 `S3-无`；换词为**机制符号**（`semantic_few_shot`／`semantic_retrieval`／`version_driven`）后命中 `test_cache_keys_contract.py`。⇒ 教训：**「无命中」的第一解释应是「词选错」，不是「东西不存在」** —— 这是本项目 `§7`「判缺数之前先证明尺能看见它」的又一复发 |
| **2** | **关键词污染（`unit` 撞目录名）** | `FR-8.5`（单位适配）首轮以 `unit` 为词 ⇒ 测试面 `unit` 命中 **68 行**，其中 **61 行**是 `from tests.unit._redis_fake import …`／`tests.unit` 路径引用（**纯噪声**）；去污染后只剩 **7 行**与「单位」相关（如 `test_semantic_dict_contract.py:16/62/159` 的 `unit` 字段、`_fullchain_deps.py:103` 的 `unit="CNY"`）。⇒ 教训：**跨面通用词（`unit`／`type`／`index`／`state`）不得单独作反查词** |

### 8.4 B4 结论（对「A 表判断」的意义）

| # | 结论 |
|---|---|
| 1 | **B4 的「缺 S3」＝「测试复述了该需求 ID」而非「有测试」** —— 42/42 缺 S3，但 42/42 都能按功能找到测试面载体。⇒ **机械尺的 `S3` 列量的是「ID 复述习惯」，不是「测试覆盖」** |
| 2 | ⇒ **对 §二「四段俱全 12」这个数字的镜像影响**：该数**奖励「把 ID 抄进测试」的条目** ⇒ 「12」既非上限也非下限，**只是 ID 复述面**的读数（此为本轮新增口径，与 §四「不得读作全表结论」并存） |
| 3 | **对「P0 需求大面积无测试」这一自然联想**：🚫 **不成立** —— 42 条抽样 8 条逐条回读**全部为实质**（`FR-5.1`／`FR-6.2`／`FR-12.4`／`FR-13.3` 见 §8.2；`FR-2.5`／`FR-3.3`／`FR-9.2`／`FR-10.4` 同）；余 34 条为**关键词级**证据（未逐条回读）。 |
| 4 | **诚实边界** | 本轮证据 = **抽样 8 条逐条回读（实质）＋ 全量 42 条关键词分档（`S3-实质` 41）**；**不是**「42 条逐条断言级核验」。⇒ 🚫 不得写「42 条测试覆盖已核验」；可写「42 条**均能找到测试面载体**，其中 8 条已逐条回读」 |

### 8.5 对总进度的影响

| 项 | 读数 |
|---|---|
| 已裁 | **87 / 117**（B1 12 ＋ B2 3 ＋ B3 30 ＋ **B4 42**） |
| 未裁 | **30**（B5 ＝ 余下：`P1` 9 条 ＋ `prio` 空档 21 条） |
| 归档 | `evidence_a_table_r31s/`（`scan_b4.py`／`sample_b4.py`／`grade_b4.py`／`b4_grade.json`） |

### 8.6 复算命令

```
# 全量分档（42 条，零成本）
CommerceQL/.venv/Scripts/python.exe backend/reports/qa/evidence_a_table_r31s/grade_b4.py
# 期望末行：分档统计 = {'S3-实质': 41, 'S3-无': 1}

# 抽样严验（8 条，打全文命中行）
CommerceQL/.venv/Scripts/python.exe backend/reports/qa/evidence_a_table_r31s/sample_b4.py

# 两处关键人工核验
git grep -n 'version_driven' -- backend/tests/contract/test_cache_keys_contract.py     # FR-12.4 机制级断言
git grep -n 'from tests.unit' -- backend/tests | wc -l                                  # FR-8.5 污染量
```


---

## 九、B5 判断（33 条余量：`defonly 10` ＋ `b5_rest 23`）· R31t ｜ 2026-10-14 10:20 ＋0800 ｜ 起点 `485cce3`／524 笔 ｜ 🔴 零出站

### 9.0 批次对象与形状

| 现读 | 值 |
|---|---|
| B5 对象 | `defonly`（`S4` only，10 条）＋ `b5_rest`（非 P0 的「有引用非四段俱全」，23 条）＝ **33 条** |
| 构成 | `P1` 3 条 ／ `prio` 空档（NFR 类） 20 条 ／ 其中 NFR 共 **20 条**（性能/可用性/持久化/合规） |
| 形状 | 本批主体是 **NFR**，其载体形态与 FR 不同：常落在**分阶段埋点键／降级机制／守卫常量／契约测试**，故反查词取「机制符号」而非 NFR 名 |

### 9.1 读数

| 档 | 条数 | 备注 |
|---|---|---|
| **`S3-实质`（≥2 测试文件）** | **29** | 例：`NFR-2.2`（降级）→ 测试面 55 文件；`NFR-1.1`（P95）→ 33 文件；`NFR-6.2`（出站脱敏）→ 25 文件 |
| `S3-弱`（1 文件） | **1** ＝ `FR-10.3` | 🔴 **该命中是蹭词**（见 §9.2-2） |
| **`S3-无`（0 命中）** | **3** ＝ `FR-10.2`／`FR-13.6`／`NFR-1.3` | 逐条复核见 §9.2 |

### 9.2 🔴 四条异常的逐条复核（B5 的实质产出）

| ID | 现象 | 本窗现读 | 判 |
|---|---|---|---|
| **FR-10.2** | 追问（"再按渠道拆一下"）应修改计划并重走全部闸门 | `追问`／`modify_plan`／`plan_modified`／`re-plan` 在 `backend/app`＋`tests` **零命中**；`clarify.py:124` 的「FR-9.2 完整重跑」**是澄清路径不是追问路径**；🔴 **根因与 `FR-1.5` 同源**：`normalize.py:37-39` 已登记「`GraphState` §5.2 的 11 组字段里**没有**历史消息字段 ⇒ 传 `()`」 | **C 档（真缺）· 根因已登记** |
| **FR-10.3** | 条件继承（省略时间/维度则继承上次计划条件） | 🔴 `S3-弱` 的那 1 个「测试文件」是 **`test_auth_chain.py:652 test_step7_create_task_inherits_context`** —— 讲的是 **JWT 上下文继承**，与「条件继承」**无关**（蹭词）；`backend/app` 内 `inherit` **零命中**；前端 `ChatPage.tsx:821-827/950` 有**「条件继承可见化」的展示逻辑**，但**后端无继承实现** | **C 档（弱）：前端有展示、后端无实现 · 同根因** |
| **FR-13.6** | 敏感字段查询走二次审批令牌（`P1`） | `审批`／`approval`／`二次审批` 在 `backend/`＋`frontend/src` **零命中**；🔴 但 **`w2c/DELIVERY.md:60` 已登记**：「敏感字段二次审批（P1）**未实现**（接口预留，07 §13.6 一致）」（另见 `w2c/RELAY.md:60`、`w2int/DELIVERY.md:90`） | **C 档 · 已登记未实现（非静默）** |
| **NFR-1.3** | SQL 生成阶段 `P99 ≤ 2.5s` | `P99`／`p99` 零命中；🔴 **但两条机制载体在**：`enums.py:813` `LatencyKey.GEN_SQL = "gen_sql"`（8 键之一，分阶段埋点）＋ `eval_report.py:68`「最近秩分位（rank = ceil(q·n)）」函数 ⇒ **分阶段埋点与分位计算都在，缺的是 `≤2.5s` 的阈值断言** | **B 档（须 W8 复核）** |

### 9.3 本窗自曝两则（B5）

| # | 自曝 | 现读 |
|---|---|---|
| **1** | **脚本多跑一条（重复劳动）** | B5 脚本 `ITEMS` 含 **34** 条，而 B5 应含 **33** 条 —— 多出 **`FR-11.4`**（它属 B3 的「四段全 0」批，已于 R31r 判 **B 档**）。⇒ 本条**不计入 B5 读数**（B5 已按 33 条重述）；`FR-11.4` 判定**以 B3 为准**（B5 那次扫描的 `S3-实质=24` 是「回归」一词的泛化命中，不作数） |
| **2** | **`S3-弱` 的命中是蹭词** | `FR-10.3` 的 1 个「测试文件」是 `test_auth_chain.py` 的 **JWT 上下文继承**用例 ⇒ 与「条件继承」**语义无关**。⇒ 本窗把它**降判为 C 档（弱）**，不保留 `S3-弱` 这个档位计数。教训同 R31s：**同一英文词在两个领域里含义不同时，命中数会骗人** |

### 9.4 🔴 跨批次的**同根因簇**（本窗在 B3/B5 两批里各撞到一次，故单列）

| 需求 | 内容 | 共同根因 |
|---|---|---|
| `FR-1.5`（P0） | 指代消解与零代词补全 | 🔴 **`GraphState` §5.2 的 11 组字段里没有「历史消息」字段**（`normalize.py:37-39` 已登记：「传 `()`。多轮指代消解因此在 P0 **不生效**」；`dto/session.py:74`／`routers/session.py:126` 同源登记） |
| `FR-10.2`（P0） | 追问应修改计划并重走闸门 | ↑ 同一根因 |
| `FR-10.3`（P0） | 条件继承 | ↑ 同一根因（`state_store.append_turn`/`get_turns` **只服务 `GET /session`**，不回流进图；`routers/session.py:121` 是 `get_turns` 的**唯一**调用点） |

⇒ **三条 P0 共用一个缺失载体**，且该缺口的**所有已知登记都只在代码 docstring 里**（三处），**`docs/07 §4.8` 无对应号**（本窗现读：§4.8 表内 122 条，`U-01`～`U-141`；按「多轮／历史／指代／追问／继承」筛，零命中）。
⇒ 🚫 **本窗不代取号**；**提请总控点名**（见 §十.3）。

### 9.5 B5 收口

| 项 | 读数 |
|---|---|
| 覆盖 | **33 / 33**（全量） |
| A 档 | **29**（88%） |
| B 档（须 W8 复核） | **1**（`NFR-1.3` — 机制在、阈值断言缺） |
| C 档 | **3**（`FR-10.2`／`FR-10.3`／`FR-13.6`；后一条已登记未实现，前两条同根因） |

---

## 十、A 表判断 pass · **收口**（117 / 117 全覆盖）· R31t ｜ 2026-10-14 10:20 ＋0800

### 10.1 四批覆盖对账（可复算）

| 批 | 对象定义 | 条数 |
|---|---|---|
| B1 | 四段俱全（`S1,S2,S3,S4` 计数全 >0） | 12 |
| B2 | `定义-only 30` 的**抽样** 3 条（**是 B3 的真子集**） | （3，不单独计数） |
| B3 | 四段全 0（`sum(roll)==0`） | 30 |
| B4 | `P0／P0（安全）` 且非上述 ⇒ 有引用、非四段俱全 | 42 |
| B5 | `defonly 10` ＋ 非 P0 余量 23 | 33 |
| **合计** | 12 ＋ 30 ＋ 42 ＋ 33 | **117 ✅** |

> 🔴 **对账口径订正（本窗自曝）**：R31r §八.5 曾写「已裁 87/117（B1 12＋B2 3＋B3 30＋B4 42）」—— **错**：`12+3+30+42 = 87` 把 **B2 的 3 条重复计入**（B2 是 B3 的真子集，§三已具名「抽样」）。**正确：已裁数在 R31r 时点 ＝ 84**（12＋30＋42），**余 33**。⇒ 原文不改，以本条为准。（这是本窗在 A 表 pass 里第二次踩「分母不可互换」—— 与 §4.2 交接件记载的同类错误同形。）

### 10.2 全表判定汇总（117 条）

| 类别 | 条数 | 备注 |
|---|---|---|
| **A · 有载体**（ID 零引用/缺段 ≠ 功能缺失） | **107** | 含 B3 的 A− 1 条（`FR-1.8`，docstring 列举职责级载体） |
| **B · 须 W8 复核**（机制在、断言/载体缺或词面待复核） | **4** | `FR-11.4`／`FR-6.6`／`NFR-4.4`（B3）＋ `NFR-1.3`（B5） |
| **C · 真缺／已登记未实现** | **5** | `FR-1.5`／`FR-4.5`（B3）＋ `FR-10.2`／`FR-10.3`／`FR-13.6`（B5） |
| **名义引用**（四段俱全但某段非实质） | **1** | `FR-8.9`（S3 面引用的是 eval 报告的**缺口登记**，非测试；B1 判） |

### 10.3 🔴 三条**待总控点句**（本窗不代裁、不代取号）

| # | 事项 | 依据 | 本窗建议 |
|---|---|---|---|
| 1 | **同根因簇是否立号**（`FR-1.5`＋`FR-10.2`＋`FR-10.3` 共用一个缺失载体 = `GraphState` 无历史消息字段） | §9.4；`docs/07 §4.8` 现读 122 条内**零命中**该对象 | 建议**立 1 号**（一号一件事：三代需求同一根因 ⇒ 一个号）；措辞与归属由 W8 定 |
| 2 | `FR-13.6`（P1 未实现）**已登记**，是否需单独号 | `w2c/DELIVERY.md:60` 明写「未实现（接口预留）」 | 建议**不立**（已登记、无静默、P1） |
| 3 | B 档 4 条（`FR-11.4`／`FR-6.6`／`NFR-4.4`／`NFR-1.3`）是否派 W8 复核词面 | A_TABLE_VERDICT §七/§九 | 建议**合并一批**派 W8（零成本、只读） |

### 10.4 全程诚实边界（A 表 pass 结束时必须同框的）

- 本 pass 的**尺是功能关键词反查**（召回工具，非判定工具）；B/C 档一律「须 W8 复核」，**除** `FR-1.5`／`FR-10.2`／`FR-10.3`／`FR-13.6` 这四条有**代码自陈或明写登记**作依据。
- **证据强度分级**（不得合并引用）：B1（12 条）＝ 逐条回读；B4（8/42）＝ 逐条回读；B3/B4/B5 其余 ＝ 关键词级。
- 🚫 **不得写**：「117 条已逐条断言级核验」；「P0 需求大面积无测试/未实现」（**反证已给**：B4 42/42 有测试载体）。
- **可写**：「117 条**全部**已按功能反查过一遍；其中 **107 条找到载体**、4 条待复核、5 条真缺或已登记未实现、1 条名义引用」。

### 10.5 复算命令

```
# 覆盖对账（117 四批分类）
CommerceQL/.venv/Scripts/python.exe -c "import json,io;inv=json.load(io.open('backend/reports/qa/evidence_a_table_r31e/req_inventory.json',encoding='utf-8'));rs=inv['reqs'];r=lambda x:x['roll'];full=[x for x in rs if all(r(x)[k]>0 for k in ('S1_设计节','S2_实现','S3_测试','S4_文档'))];zero=[x for x in rs if sum(r(x).values())==0];df=[x for x in rs if r(x)['S4_文档']>0 and r(x)['S2_实现']==0 and r(x)['S3_测试']==0 and r(x)['S1_设计节']==0];rest=[x for x in rs if x not in full and x not in zero and x not in df];print(len(full),len(zero),len(df),len([x for x in rest if x['prio'] in ('P0','P0（安全）')]),len([x for x in rest if x['prio'] not in ('P0','P0（安全）')]))"
# 期望：12 30 10 42 23

# B5 分档
CommerceQL/.venv/Scripts/python.exe backend/reports/qa/evidence_a_table_r31t/grade_b5.py
# 期望末行：分档统计 = {'S3-实质': 30, 'S3-无': 3, 'S3-弱': 1}   ← 含多跑的 FR-11.4，见 §9.3-1
```
