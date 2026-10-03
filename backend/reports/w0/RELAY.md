# W0 → 各窗口 转述件（逐条可直接复制）

> 生成：2026-09-16 ｜ 归属窗口：**W0（阶段 0 脚手架与契约固化）**
> 对应提交：`c63f67a`（U-39/U-38/U-41 清账 + gitleaks 定口径）＋ `0836aae`（CI 修正）—— **CI success，5 job 全绿**
>
> **用法**：每一节就是一个"整块可粘贴"的消息，收件人写在节标题里。
>
> ⚠️ 本件**不写任何可用口令字面量**（`test_migration_dsn_hygiene.py` 会全仓重放 DoD④ 规则，
> W1B 已踩过一次）。需要描述形态时一律写「`postgresql+psycopg://` + 用户名 + `:` + 口令 + `@` + 主机」。
>
> **编号**：本件开 **U-47 / U-48 / U-49**（W0 区间 = U-47~U-50，依据 W1B RELAY §7 的区间声明），
> **U-50 留存未用**。引用既有编号：U-14~U-22（W0）、U-37（W0，2026-09-16）、U-38/39/41/44（W1B）。

---

## 1 → W1B：U-38 / U-39 / U-41 / U-44 清账 ＋ 两条定口径裁定（**回你的 §1 / §2**）

> **W0 回执 —— 你 RELAY 里归我的四项全部处理完，两条"请我定口径"裁定如下。**
> 对应提交 `c63f67a` + `0836aae`，CI success。验收请按你自己的纪律复核，别信结论。
>
> **① U-39 已修（你的最高优先）**：`tests/conftest.py` 新增会话级 autouse fixture
> `_win32_selector_event_loop_policy`——仅 win32 下 `asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())`，
> 非 win32 为 no-op。**没有**用 `asyncio.to_thread` 同步连接（按你的要求，不藏事实）。
> 复核：`test_obs_audit_contract.py` 12 passed（修复前 2 failed）；全量 **377 passed / 0 failed**；
> 你的两条防伪装断言（`test_interface_error_is_deliberately_not_treated_as_unreachable` 等）仍绿。
>
> **② U-38 W0 侧已补齐，接线（一行级）归你**：
> `app/cache/keys.py` 新增 `rate_limit_tenant(bucket, tenant_id)` → **`rl:t:{bucket}:{tenant}`**。
> 防撞设计：用户键 `rl:{bucket}:{tenant}:{user}`，租户键第 2 段是字面量 `t`——两键**在任何输入下不可能相等**，
> 滑窗脚本两维度必落不同 ZSET（"启用租户维度却复用用户键"在键空间层面不可能发生）。
> 契约测试 +12（格式钉死 + 4 桶 × 3 用户防撞参数化 + PII 纪律延伸），全过。
> **你的接线（`ratelimit.py` 归 U-42 待裁定，我一行未碰）**：
> 　a. `check()` 里 `tenant_limit = rule.per_tenant_per_min or 0`（替换硬编码的 `0`）；
> 　b. `_window_keys` 的 `tenant_enabled` 分支改用 `cache_keys.rate_limit_tenant(bucket.value, ctx.tenant_id)`；
> 　c. `ENFORCED_DIMENSIONS` / `UNENFORCED_DIMENSIONS` 翻转——你文件里的
> 　`test_per_tenant_dimension_is_not_enforced_and_why` 会红，按你自己写的注释改它即可；
> 　d. `ADMIN` 桶 `per_tenant=None` 不受影响；`GLOBAL_CONCURRENCY` 仍未实现（不动）。
>
> **③ U-41 已封死**：`ci.yml` 的 lint-imports 步骤加存在性断言（输出必须含 `Contracts: `，否则报
> "疑似假绿——禁止 `python -m importlinter.cli`"）；README 工程约束② 同步注明禁令。U-44 按你确认关闭。
>
> **④ 定口径 1（allowlist 整文件放行 `.env.example`）—— 已收口，选了你的方向 (a) 的收紧版**：
> `deploy/.env.example` **从 `allowlist.paths` 移除**，改由 `allowlist.regexes` **按形态**放行：
> 仅放行 `app_rw`/`app_ro` + 弱占位口令的引导凭据形态（与 docker-compose 同源的本地开发值）。
> **边界已写进 `.gitleaks.toml` 注释**：属主口令、真实主机名、任何其他 DSN 形态出现必红。
> 双向对照实测（非推理）：属主形态 DSN 写入仓库根临时文件 → 命中 `commerceql-dsn-with-password`；
> 弱占位形态 → 放行；全量 `no leaks found`。探针已删。
> → 连带结论：**`.env.example` 里现有两条占位 DSN 保留现状，不再要求 W7 改"键留空"**——
> 例外边界已在文件注释里写明。你 §3 给 W7 那条里的"定口径"部分就此关闭（MIGRATION_DATABASE_URL 键登记仍归 W7）。
>
> **⑤ 定口径 2（`0001` 迁移的默认口令 DSN）—— 维持你的取舍：不编辑已应用的迁移。**
> 你的理由成立：改冻结制品会让"从零重建的库"与"已建成的库"得到不同角色口令，比现状更坏。
> 其形态恰在上述 regexes 放行边界内（本地开发引导凭据），不会红；属主形态始终会红。
> 若后续根治：走**新增迁移**或强制环境变量，**不走 allowlist**（与你的原则一致）。

---

## 2 → W1A：CI 挂载请求 —— 已接（4/5），冻结集一项有结构性例外

> **W0 回执 —— 你 RELAY §2 的请求已落实（对应提交 `c63f67a`+`0836aae`，CI success）。**
>
> **新 CI job `w1a-artifact-checks`**（独立 job = 红时归因清晰，不会与 W0 契约断言混淆）：
> 　· `semantic/validate_bundle.py`（34 项结构校验）
> 　· `eval/build_red_team.py --check`
> 　· `semantic/render_metric_dictionary.py --check`
> 　· `eval/build_gold_seed.py --check`
> 断言**全部来自你自己的校验器**，ci.yml 不硬编码任何字段形状——你升 SCHEMA 版本时由你同步校验器，
> CI 红 = 该同步了，不是误报。
>
> **⚠️ 冻结集 `build_frozen_set.py --check` 刻意不挂（首次挂载实测 CI 红，非漂移）**：
> 它开头就检查 `data/ecom_sandbox.db`（420MB，按"数据物不入库"决定不进 git）→
> CI 环境结构上没有该文件，`[FATAL] 沙箱库不存在` exit 2。它与上面 4 个"纯结构 + hash"检查**不同类**，
> 属"需要本地数据物"的检查，与 seed_generator 复现流程绑定（你的 MANIFEST 已给种子与 sha256）。
> 在 CI 重建 150 万行沙箱库成本远超收益 → 仍归本地人工跑，原因已写进 ci.yml 注释。
> → 你的"遗留项"记录建议写：**冻结集未漂移检查留在本地，其余 4 项已上 CI**。

---

## 3 → 架构窗口：2 组补录 ＋ 3 个开号（U-47~U-49）

> **W0 → 架构窗口（对应提交 `c63f67a`/`0836aae`，CI success）**
>
> **① U-37 补录（2026-09-16 登记）**：ADR-20 表与附录 D §D.2.1 均无 YAML 解析库，
> 但 07 §6.1① / §3.2 的 `loader.py` 明文要求读 YAML；W1A 实测不含传递依赖的解释器跑
> `semantic/validate_bundle.py` → 硬失败。代码侧 W0 已落笔，请补录：
> 　· 5 个包转正（"直接 import 却只靠传递依赖活着"，全仓 AST 扫描抓出）：
> 　**pyyaml / psycopg-pool / cryptography / starlette / python-dotenv**；
> 　· 2 个版本按用户"都钉"裁定精确钉死：**langgraph==1.2.11 / langgraph-checkpoint-postgres==3.1.2**。
>
> **② U-21 / U-22 补录**（W0 早已落码，但 07 v0.7 的统计行写"W0 6 条 U-14~U-19"，把这两条漏了）：
> 　· U-21：`INTERNAL` 档位附录 A=⭕ / 07 §14.4=✅ → 按契约优先级**取附录 A（⭕）**，已落码。
> 　· U-22：✅ 档缺省 Retry-After，**数量修正为 3 个码**（因 U-21 把 `INTERNAL` 移出 ✅ 档）：
> 　`LLM_CONCURRENCY_EXCEEDED` 2s / `LLM_UPSTREAM_ERROR` 5s / `DB_UNAVAILABLE` 5s
> 　（`RATE_LIMITED` 30s 与 `SESSION_CONFLICT` 3s 文档本有值，不属 U-22）。W0 落的是保守缺省值，待核定。
> 　⚠️ 与 W1B RELAY §5④ **联动**：`DB_UNAVAILABLE` 的 5s vs 池默认等待 30s 的自洽缺口，请两条一起裁
> 　（W1B 已给实测数字与 (a)/(b) 两案）。
>
> **③ 开号（W0 区间 U-47~U-50，承接 W1B RELAY §7 的"待分配"表——W1B 区间 U-38~U-46 已用尽）**：
> 　· **U-47** ＝ `/healthz/ready` 的 `_collect` 串行探针须并行化（`asyncio.gather` + 语义原样保留）
> 　　→ 归 **W7**。实测：依赖不可达时 7.82s > 平台预算 `healthcheck.timeout: 5s`（串行=求和，并行=最大值）。
> 　· **U-48** ＝ 07 §8 缺"池超时与重连规则"→ `DB_UNAVAILABLE` Retry-After=5s 与池默认等待 30s 不自洽
> 　　→ 归 **架构**（W1B 已交实测值与两案，见其 RELAY §5④）。
> 　· **U-49** ＝ 依赖不可达时 `pool.close()` 有 2s 关停延迟未追 → 归 **W1B（后续）**。
> 　· U-50 留存未用。
>
> **④ 顺带提醒**：W1B 的 U-40（DoD② 判定时序落 docs/08）、U-42/U-43（清单外文件登记 / `obs/audit.py`
> 重写追认）、U-45③（07 §12.6 补"迁移连接唯一来源"一行）仍在你处待办，本件不重复其内容。

---

## 4 → PRD 窗口（docs/05 附录 D）：依赖白名单补录（U-37 文档侧）

> **W0 → 附录 D 窗口（docs/05）**：§D.2.1 依赖白名单待补录 7 项（U-37）。
>
> 背景：`semantic/validate_bundle.py` 直接 `import yaml`，而 PyYAML 此前不在白名单、
> 只作为 langchain-core 的传递依赖存在——用不含传递依赖的解释器跑会**硬失败**（W1A 实测）。
> 顺此形态全仓 AST 扫描，共 5 个"直接 import 但未声明"的包：
> **pyyaml / psycopg-pool / cryptography / starlette / python-dotenv**。
>
> 代码侧 W0 已在 `backend/pyproject.toml` 声明并配机器护栏（`test_no_undeclared_third_party_imports`：
> 直接 import 必须已声明，含函数内延迟 import；另有正向对照测试防检测器空转）。
> 请 §D.2.1 补录这 5 项，以及 2 个精确钉死版本（用户 2026-09-15"都钉"裁定）：
> **langgraph==1.2.11、langgraph-checkpoint-postgres==3.1.2**。
>
> 新增下载体积 = 0（5 个本就在依赖闭包内），只是把既存事实写明。
> 另：W1B 的 U-46（附录 D 步骤 11 缺 `MIGRATION_DATABASE_URL` 前置）是他直接转给你的，本件不重复。

---

## 5 编号与状态汇总（本件涉及的）

| 编号 | 事项 | 归属 | 状态 |
|---|---|---|---|
| U-21 / U-22 | INTERNAL 档位裁定 / ✅ 档缺省 Retry-After（**3 码修正**） | 架构补录 | 已落码，文档待补 |
| U-37 | 5 包转正 + 2 版本钉死 | 代码=W0 ✅ / 文档=架构+附录 D | 文档待补录 |
| U-38 | 限流租户维度未启用 | W0 键函数 ✅ / W1B 接线 | 本轮键函数已交付 |
| U-39 | win32 需 Selector 循环 fixture | W0 | **已修**（377 passed / 0 failed） |
| U-41 | `-m importlinter.cli` 假绿形态 | W0 | **已封**（CI 断言 + README 禁令） |
| U-44 | 在制品 5 条 ruff 违规 | W0 | 已关闭（W1B 确认） |
| U-47 | `_collect` 串行 → 7.82s 超平台预算 5s | W7 | 新开，待 W7 |
| U-48 | 池等待 30s vs Retry-After 5s 不自洽 | 架构 | 新开，待裁定 |
| U-49 | `pool.close()` 2s 关停延迟 | W1B（后续） | 新开，登记 |
| U-50 | —（W0 区间留存） | — | 未用 |

> **W0 当前无未决代码项**。工作区里 W1A/W1B 未提交的在制品（3 个 M + 若干未跟踪）本窗口全程未触碰。

---

## 6 【给 W2-INT】CI ruff 红 33 条 —— 随你们阶段 2 提交带入（2026-09-16 晚）

> 【给 W2-INT】CI ruff 红 33 条，是 `c6373a2` / `c02f97a` / `b697667`（阶段 2 收口与 U-55(a)）带进来的，基线在 W0 隔离树复现一致（afaa31c 之前 CI 全绿）。**W0 不动你们归属的文件**，清单如下，请自行修复或分派（23 条可 `ruff check . --fix` 自动修）：
>
> ⚠️ **先修非自动项**：`app/retrieval/dense.py:273 F821 Undefined name Mapping` —— 这是运行时 NameError（走到该路径就炸），`--fix` 修不了，需手动把 `Mapping` 移到 `collections.abc` import。
>
> - W1B 域（guard，10 条）：`app/guard/__init__.py:20 UP035`；`ast_gate.py:196,764 RUF034`；`cost_gate.py:22 UP035 / :56 UP037`；`policy_gate.py:23 UP035 / :218 RUF100`；`rules.py:19 UP035`；`tests/unit/guard_fixtures.py:27 UP020`；`test_guard_gate3.py:10 F401`；`test_guard_rules.py:3 I001 / :7 F401 / :17 B007`
> - W2B 域（retrieval，13 条）：`app/retrieval/dense.py:27 I001 / :32 UP035 / :273 F821⚠️`；`tokenizer.py:31 UP035`；`view.py:175 UP037`；`reports/w2b/recall_report.py:51 B007 / :55 SIM117 / :61 B905 / :83 RUF100`；`tests/contract/test_retrieval_contract.py:53 SIM102`；`tests/integration/test_retrieval_fts_pg.py:34 F401 / :47 I001 / :150 B007 / :157 B905`；`tests/unit/test_retrieval_search.py:11 F401 / :92 RUF059`；`test_retrieval_tokenizer.py:3 I001 / :54 RUF021`
> - W2-INT 域（1 条）：`reports/w2-int/e2e_stage2_check.py:1 UP009`
> - W1A 域（1 条）：`tests/redteam/test_redteam_guard.py:23 F401`
>
> 顺带回报：(b) 已落码（`c7bb534`）——契约断言 job 挂 pgvector service + 迁移前置 + 4 个无口令 DSN，CI 集成测试真跑全绿；你们 (a) 的 skip 分支与之兼容，无需改动。


---

## 7 【给 W3-INT 回执】12 条逐条处置（2026-09-17，commit `1c24f14`）

> 【给 W3-INT · 来自 W0】§给 W0 的 12 条已逐条处置（`1c24f14`，CI 待本次推送确认）：
> **已落码（7 条）**：
> ① `Retry-After` 已按 07 v0.8 §14.4.1 裁正 5s/30s（`enums.py`，`DB_UNAVAILABLE`=5 保持，U-52 推导归 07 §8）。
> ② `DEEPSEEK_API_KEY` 加 `min_length=1`，空串不再过必填校验。
> ③ `assert_importlinter.py` 并发安全根修：探针文件名带 PID + O_EXCL 文件锁（陈旧 10min 接管）+ 持锁后清扫死进程残留 + 信号转 SystemExit/finally + atexit 兜底。你们撞到的"粘性残留"形态已不可能复现（同前缀残留会被下次启动自动清扫）。
> ④⑤ `binding_state_total` / `binding_layer_total` counter 本体已落 `obs/metrics.py`（07 §15.3 明文规格：标签 `state`(4)/`layer`(4)，枚举来自 `BindingState`/`BindingLayer`，未观测值补 0，渲染进 Prometheus 文本）。W4 接线用 `observe_binding_state()/observe_binding_layer()`。**但 7 个 `llm_*` 指标名 §15.3 没有**（是你们/A 组的建议名）—— 本文件"不凭空起名"纪律不破例，已呈架构补名后再落本体（含 #6 的 `budget_s`/`over_budget` 纳入点）。
> ⑪ `tenacity`/`respx` 已双录账移除（全仓零 import 实证）。
> ⑫ `LLM_TIMEOUT_SECONDS` 已标注"被 07 §10.2 取代、无消费方"，删除待裁决（删键要动 `.env.example` 双向同步，与裁决一起做干净）。
> **待架构裁决（5 条）**：#7=A11、#8=A10、#9=A13、#10=A16（端口/取值集变更，不先斩后奏）+ #4 的 llm_* 指标命名。
> 隔离树验证（CI 等效 DSN）：pytest 1477 passed / 1 skipped；DoD② 4/4；ruff（W0 文件）0；mypy clean；Contracts: 4 kept。


---

## 8 【给 W4 回执】三组键已交付（`b19698f`，2026-09-18）—— 解 T5/T8 阻塞

> 【给 W4 · 来自 W0】`app/cache/keys.py` 三组键已落码（`b19698f`），你 §一 的验收条件全过：
> `pytest tests/contract/test_cache_keys_contract.py` **52 passed**；进 `ALL_BUILDERS` ✓；进 `DEFAULT_TTL_S` ✓；无租户者进 `TENANTLESS_BUILDERS` 并写理由 ✓。
>
> **可直接接线**：
> - `keys.task_state(task_id)` → `task:{task_id}`（**无租户**），TTL **3600**
> - `keys.concurrency_lease(tenant_id)` → `concur:{tenant}`，TTL **3600**
> - `keys.session_meta(tenant_id, session_id)` → `sess:meta:{tenant}:{session_id}`，TTL **86400**
> - `session_plan` 未改（沿用为轮次计划摘要 List）；`session_lock` / `event_buffer` / `result_set` 均未改
>
> ⚠️ **两个必须在端点侧兑现的义务**（我写进了键的 docstring，别让它们停留在注释里）：
> 1. `task_state` 无租户的分类前提是**读端做所有权校验**（`GET /query/{task_id}` 按附录 A §A.2 校验归属）——与 `evt:` 同一条义务。若有第二个消费方绕过端点直读本键，这个分类需要重新评估（回来找我改，别在别处拼键）。
> 2. `concurrency_lease` **必须按租户隔离**（别把多个租户塞进一个 ZSET）；它是本模块唯一的 `concur:` 前缀，与 `rl` / `rl:t` 结构性不同。
>
> 隔离树验证：全量 1512 passed / 1 skipped；ruff/mypy clean；`Contracts: 4 kept`。


---

## 9 阶段 4 阻塞项处置：W0 部分已落码 + 一条 🔴 CI 阻断（2026-09-18）

### 9.1 【给 W4】决策点 ① 与 ② 的 W0 侧事实（回执）

> 【给 W4 · 来自 W0】你 A/B/C 三条路里的 **A 方案有一处违规**：在 `app/api/dto/` 写 `Literal[...]` 10 值 = **第二份取值集**（单一真相在 `app/core/enums.py`，docs/08 §4.1）。W0 已把枚举侧落地（`c31f9b9`，**尚未推送**，见 §9.2）：
> - `from app.core.enums import FeedbackReasonCode`（10 值 = §A.6 逐字）
> - `new_id("feedback")` → `fb_...`（§A.6 明文 `"fb_01J8X7"`；**不需要**架构认账"新前缀"——它是文档给定，不是自创。若不登记，回退 `kind[:2]` 会得到 `fe_`，与契约文档不符）
>
> ⇒ 你可以按 **B 的"契约壳"** 走而不写第二份取值集：DTO 用枚举校验、`feedback_id` 真实生成；**只有 `queued_for_review` 与 `corrected_sql` 的落库部分**仍缺表（U-20 / 迁移 0005，归 W1B）——该字段必须**如实** `false` + DELIVERY 显著登记，不得谎报 `true`。
>
> 决策点 ②（`mint_dev_token` 落点）：按 docs/08 §4.1，**`backend/scripts/**` 归 W1B**（不是 W0 —— 你 PROMPT 里的"转 W0"与归属表冲突），且 W1B 的 `tests/unit/test_auth_chain.py` 里已有 `_sign()/_claims()/rsa_keys` 可复用 → 建议**转 W1B**。另注意：`scripts/` 下目前确实有 W0 的 `assert_importlinter.py`（阶段 0 遗产）与 W1B 的 4 个探针并存，归属表与实现历史**不一致**，需要架构澄清一条规则（"阶段 0 遗留怎么办"）。

### 9.2 🔴 【给 W1B】CI 阻断：`COMMERCEQL_TEST_SUPER_DSN` 形态不兼容（挡一切推送）

> 【给 W1B · 来自 W0】你新增的 `tests/integration/test_query_plan_store_pg.py` 与 CI 的 DSN 注入**不兼容**，下一次任何窗口推送都会让 **DoD③ job 变红**（本地隔离树已复现：6 errors）。
>
> 根因：CI（`ci.yml`，2026-09-16 的 (b) 改动）注入的 `COMMERCEQL_TEST_*_DSN` 是 **libpq（plain）形态** `postgresql://role@127.0.0.1:5432/ecom` —— 这是被迫的：`test_semantic_materialization.py` / `test_exec_real_pg.py` 直接把它交给 `psycopg.connect()`，而 psycopg 3 **不接受** `+psycopg` 方言后缀。你的 `upgraded` 夹具却把它原样交给 `MIGRATION_DATABASE_URL` → SQLAlchemy 解析出 **psycopg2** 方言 → `ModuleNotFoundError: No module named 'psycopg2'`。
>
> 修法（2 行，你自己已经写了反向助手 `_libpq()`，只缺正向）：
> ```python
> def _sqla(dsn: str) -> str:
>     """libpq → SQLAlchemy 形态（alembic 需要；本环境只有 psycopg(3)，无 psycopg2）。"""
>     return dsn if "+psycopg://" in dsn else dsn.replace("postgresql://", "postgresql+psycopg://", 1)
> # upgraded 夹具里： "MIGRATION_DATABASE_URL": _sqla(_SUPER)
> ```
> 修完请复跑 `pytest tests/integration/test_query_plan_store_pg.py`，**并带上 CI 等效 DSN 环境变量**（裸跑会跳过该失败路径，看不出问题）。

---

## 10 阶段 4 · 挂载落地 + 全窗口推送状态（2026-09-18 晚，W0）

### 10.1 【给 W1B · 回执】`jwt_public.pem` 只读挂载已落

> 【给 W1B · 来自 W0】你 DELIVERY §13.4 第 1 条（公钥无持久路径 → 容器重启即失效）**已解决**：
> `deploy/docker-compose.yml` 的 `api.volumes` 增加
> `./secrets/jwt_public.pem:/run/secrets/jwt_public.pem:ro`（路径 = `settings.JWT_PUBLIC_KEY_PATH` 默认值）。
>
> 给你改脚本/文档时用的三点：
> 1. **`--docker-container` 可以不用了**（原先是"没挂载"才需要 `docker cp`，容器非 root 还得 `-u root`）。
>    兼容路径留着不冲突，但文档里"重启要重拷公钥"那句应删掉。
> 2. **首次使用的确切命令**（幂等；私钥缺失时自动生成 RSA-2048，已存在则复用）：
>    ```bash
>    cd backend && ../.venv/Scripts/python.exe scripts/mint_dev_token.py --tenant-id t_dev
>    ```
>    写出 `deploy/secrets/jwt_private.pem`（PKCS8，POSIX 下 chmod 600）+ `deploy/secrets/jwt_public.pem`。
> 3. **踩坑已写进注释**：宿主文件不存在时 Docker 会在该路径**建一个同名目录**（不报错）→
>    应用侧表现为"读 PEM 失败"。所以顺序必须是**先生成密钥对，再 up**。
>
> 实测边界（**不说满**）：`docker compose config -q` 通过；重建 api 后容器内 `/run/secrets/jwt_public.pem`
> 可见、`/api/v1/healthz/ready` = 200。**只证到 readiness**，HTTP 层令牌端到端**仍未证**
> —— 那正是你 §13.4 第 2 条的未决事实，本次挂载不改变它。

### 10.2 【给 W1B · 回执】§9.2 的 🔴 CI 阻断 **已解除**

> `tests/integration/test_query_plan_store_pg.py` 里已见 `_sqla(_SUPER)`（你 `7f205e2` / `f05c7da` / `9fed317` 一带落码，
> 行 72 `def _sqla`、行 119 `"MIGRATION_DATABASE_URL": _sqla(_SUPER)`）→ 我此前的"推送即让 DoD③ 变红"顾虑消失。
> **§9.2 视为关闭**，无需你另行处理。

### 10.3 【给 W2-INT】ruff 只剩 **1 条**：已在你工作区修好，但**没进提交**

> 用**真实路径**复判 `ruff check reports/w2-int/e2e_stage2_check.py` → `All checks passed!`；
> 而 **HEAD（= 远端 `89262bb`）版本** 仍报 1 条：
> ```
> reports/w2-int/e2e_stage2_check.py:1:1  UP009  UTF-8 encoding declaration is unnecessary
> ```
> 即"删掉首行 `# -*- coding: utf-8 -*-`"这个改动**只在工作区、未提交** → 远端 ruff job 仍红一条。
> **归属是你们**（`backend/reports/w2-int/**` 按 docs/08 §4.1），**W0 未代提交**，请补一次提交带上它。
> （`ruff check --fix` 即可，`UP009` 属不安全修复之外的自动可修项，实测 1 fixable。）
>
> ⚠️ 附一条**方法论坑**（本次实测）：`ruff check --stdin-filename ... --config ...` 组合下 isort 的
> first-party 判定会失准，对该文件**虚报 2 条 I001**（真实路径判定为 0）。**lint 结论必须用真实路径下判**，
> 否则会去追一个不存在的问题。

### 10.4 全窗口推送状态（`git ls-remote` 实证，非推断）

> 远端 `refs/heads/main` = `89262bb` = **本地 HEAD** ⇒ W0 阶段 3/4 的全部提交**已在远端**：
> `c7bb534`（CI 真 PG service）· `d09020c`（TaskStatus 4 值）· `1c24f14`（W3-INT 七项）·
> `b19698f`（三组键）· `c31f9b9`（FeedbackReasonCode）。**没有任何窗口需要等 W0 的推送。**
> §9.1 里"`c31f9b9` 尚未推送"的括注**作废**。
>
> ⚠️ **环境提示（非契约，仅本机）**：本机 `git fetch` 会打印 `[new branch] main -> origin/main`，
> 但引用**不落盘**（`.git/refs/remotes/` 始终为空，`refs/heads/main` 正常；无 hook、无 `core.hooksPath`），
> 导致 `git status` / `git branch -vv` 误显 `[origin/main: gone]`。
> 判断"我领先/落后远端"请用 `git ls-remote origin main`，**不要相信 `[gone]`**。

---

## 11 【U-121 第一步回执】闸门判据形状已定稿（`ae59c5c`，2026-09-21）

### 11.0 一句话

`app/core/contracts.py` 现在**显式声明**了闸门那 7 个键的形状（`GuardAllowlist`，**7 键全 Required**）
+ 新方法 `guard_allowlist(ctx, *, max_rows=None)`。**唯一改动文件 = `app/core/contracts.py`**，
**未动任何实现** —— 下一步按 07 v1.6.4 的三方归属（W2A 实现 / W2C 消费 / W4 换 gate1 调用点）走。

### 11.1 定了什么形状（W2A 照着实现、W2C 照着消费）

| 名字 | 形状 | 谁用 |
|---|---|---|
| `AssetAllowlistEntry` | `{logical_name, domain, grain, tenant_scoped, columns}` | **扁平面**（`asset_allowlist` 的返回值；planner/binding） |
| `GuardAllowlistAsset` | 上式 **+ `all_columns`** | 闸门面条目 |
| `GuardAllowlistJoin` | `{left, right, on_columns}`（**逻辑名**，已截 `.列` 后缀） | R10/R11 |
| `GuardAllowlist` | `bundle_version` / `assets` / `joins` / `deny_columns` / `default_predicates` / `allowed_constants` / `max_rows` | gate1 + gate2 |
| 端口 | `asset_allowlist(ctx) -> Mapping[str, AssetAllowlistEntry]`（⚠️ 注解**未**收紧，见 §11.3③）+ **新增** `guard_allowlist(ctx, *, max_rows=None) -> GuardAllowlist` | — |

**两面的判据（坑 ② 的落点）**：

| 面 | 键 | 内容 | 消费者 |
|---|---|---|---|
| **可见面** | `columns` | `{列名: PG 类型}`，**已裁 `deny_columns`** | gate1 列解析（R06）、planner、binding |
| **结构面** | `all_columns` | `{列名: PG 类型}`，**全列含 deny** | gate2 ④（敏感列复核）⑤（`tenant_id` 双向断言）、`_column_type`（R17） |

> 为什么 `columns` **必须**取可见面（这条决定了 W2C 现有测试要不要改）：07 v1.6.4 子事实 4 写
> "`deny_columns` 缺 ⇒ 仍 fail-closed，丢的只是归因（R07→R06）" —— **这句话只在可见面下成立**。
> 若 `columns` 给全列而 `deny_columns` 又缺 ⇒ `colname in columns` 成立 ⇒ **敏感列直接放行**（fail-open）。
> 且 W2A §10 的漂移表已实测：可见列(21) 下 `tenant_id`/`receiver_phone` 未限定 → R06、
> 全列(24) → R07 ⇒ **取可见面则 W2C 那条 `{R06, R07}` 集合断言继续成立，测试不用改**。

**七个键的缺省方向**（逐键裁入 docstring，抄 07 v1.6.4 + W2C 表）：
`assets` / `joins` / `deny_columns` / `allowed_constants` 缺 = **fail-closed**
（全拒 R05 ／ join 全落 R10 ／ 丢归因 R07→R06 ／ R14 少一类来源）；
`default_predicates` / `bundle_version` / `max_rows` 缺 = 🔴 **fail-open**
（口径静默失真 ／ 版本守卫静默失效 ／ 请求级上限被静默忽略）。
⇒ 故"只补 `assets` 键"被明令禁止：那会把一条 fail-closed 换成三条 fail-open。

### 11.2 你要点名的两个坑 —— 答复

**（1）入参形态不对称 ⇒ 我选"端口加第二个方法"，不给闸门派生。** 落点按 W2C 20:43 的精确化：

| 取用点 | 现状 | 改谁 |
|---|---|---|
| `app/graph/nodes/gate1_ast.py:52` | `... = deps.semantics.asset_allowlist(identity)` → `:55 run_gate1(sql, allowlist)` | **W4**（换成 `guard_allowlist(identity, max_rows=<请求级>)`） |
| `app/guard/policy_gate.py:105` | `allowlist = bundle.asset_allowlist(ctx)` | **W2C**（换成 `bundle.guard_allowlist(ctx)`）；`gate2_policy.py:57` 的传入形态**不变** |

> ⚠️ 两处**保持各自取一次**（`gate1_ast.py:13-18` 明写"与 gate2 各自取一次是刻意的"），
> 换方法时**别顺手合并**成一次取用。

**（2）`columns` 两面 ⇒ 已按 §11.1 定。** 给 W2C 追加一条**必须做**的：
`_Auditor._resolve_column` 的**归属面要可切换** —— 同一个 helper 今天既服务 gate1 的 R06（要可见面），
又服务 gate2 ④ 的列归属（**要结构面**）。实测后果（W2A §10 复现）：给 gate2 喂可见面 ⇒
④ 对 `SELECT receiver_phone FROM v_order_paid` **完全不响**（落到 ⑤ 抛 `ContractViolationError`）——
**fail-open 的一半，比崩溃更值得记**。

**（3）`allowed_constants` 从哪来 ⇒ 只有一个来源：`allowlist["allowed_constants"]`。**
`run_gate1(sql, allowlist)` 现在**已无**独立形参（`ast_gate.py:314` 直接读该键）；
07 §7.2 三类白名单里 **① LIMIT 注入值 ② 注入谓词的常量由 `run_gate1` 自算**，
**不得**经此键提供。当前语义包**没有**该区块（grep 实证）⇒ W2A **给空元组**：既不编造，也不省略键。

### 11.3 我另外核出的三条（不在你给的清单里）

① **判据④ 的通路已核实可行，且不能用别的数冒充**：请求级选项在 **`GraphState.options`**
（`app/graph/state.py:272`，`OpaquePayload` = `RunOptions`，由 `:447-465` 写入）
⇒ `gate1_ast` 能读到 `state["options"]["max_rows"]`。
⚠️ **禁止**用 `GraphDeps.max_rows` 代替它 —— 那是 `EXEC_MAX_ROWS`（`graph/context.py:126`，默认 1000），
而 `nodes/execute.py:34` 已具名自警"两者可能不同，拿它冒充是造数字"。
归一（`min(值, 10000)`）由 `ast_gate._effective_limit` **自己做**（它已 `min(int(...), 10000)`，
且对 `None` 走 `TypeError` 分支退化到硬上限 `MAX_ROWS_HARD_LIMIT`）⇒
**调用方不必先 clamp**，而 `max_rows` 的语义定为"**键必在**，值为 `int` = 请求级上限 /
`None` = 调用方未声明（照实填 `None`，不许编数）"。

② **两个键的来源现成**：`joins` ← `runtime.joins()`（`app/semantics/runtime.py:290`，**已存在**、
只是**不在端口上**）；`bundle_version` ← 与 `active_version()` 同一读数。W2A 不必新写派生器。

③ 🆕 **扁平面收紧的连带风险（我刻意没做的那部分）**：`binding/filters.py:345` 用
`isinstance(columns, (list, tuple))` 判"无权限" ⇒ 扁平面 `columns` 从 **tuple 改成 Mapping** 会让它
**静默 fail-open**（返回 True = 不拦）。所以我**没有**把 `asset_allowlist` 的注解收紧到 `AssetAllowlistEntry`：
实测收紧会让 `planner/payloads.py:311` 的 `entry = allowlist[physical] or {}` 变成**死兜底**
（mypy `warn_unreachable` 报错；对照实验：松注解 **147 files clean** / 收紧 **1 error**）。
⇒ 归属 = **W3B（`app/planner/payloads.py`）+ W2B 侧 `binding`**；建议**单开一条编号**
（**我没自行占号**，按纪律请架构/总控归号）：同步改 `isinstance` 判据 + 补"Mapping 形态下 deny 列仍被拦"
的测试，**然后**才能收紧注解。

### 11.4 我没做什么（诚实边界）

- **未动任何实现**：`app/semantics/**`（W2A）、`app/guard/**`（W2C）、`app/graph/**`（W4）一行未改。
- **未改 W4 的接缝测试**：`tests/contract/test_gate_seam_contract.py:54` 现在调的仍是
  `rt.asset_allowlist(_ctx())` ⇒ 新方法落地后，**Test A 的调用点要换成 `rt.guard_allowlist(_ctx())`**
  （否则它测的是被废弃的那个投影）。该文件归 W4；它的**红我复跑对照过**（见 §11.5 末行）。
- **未推**（按今日纪律"上传听指令"）：本地 `ae59c5c`，**远端未含本提交**。

### 11.5 验证读数（可复现）

| 项 | 读数 |
|---|---|
| `ruff check .` | **All checks passed** |
| `mypy app` | **Success / 147 source files** |
| 契约自检（`python -c`） | `GuardAllowlist.__required_keys__` = **7** 个（`allowed_constants, assets, bundle_version, default_predicates, deny_columns, joins, max_rows`）· `__optional_keys__` = **空** · 端口方法 **4 → 5** |
| `pytest -q`（全量） | **1 failed, 2207 passed, 6 skipped, 3 errors**（138.2s） |
| 唯一 failed | `tests/contract/test_gate_seam_contract.py::test_plain_sql_passes_through_gate_seam` = **U-119 的刻意红**（`8a4121a` 立的判据①） |
| 3 errors | `tests/integration/test_retrieval_fts_pg.py`：本机 DSN 无 DDL 权限（**环境**，非代码；CI 注入了可建表的 DSN） |
| **对照归因** | `git stash push -- backend/app/core/contracts.py` 后**同一条照样红** ⇒ **本次改动零新增红** |
| 远端 CI 现状 | 最近 3 次 run 全 `failure`（`ff3e122`/`8a4121a`/`5327b1e`）—— **接缝红是既定的**，不是本轮引入 |

### 11.6 07 v1.6.4 四条判据的落点

| 判据 | 落点 |
|---|---|
| ① 普通 SQL 必须 `passed=True` | W2A 实现新方法 + W4 换 `gate1_ast:52` 调用点（W4 的接缝测试随之转绿） |
| ② 默认谓词真注入（含 `pay_status = 'paid'`） | W2A（`default_predicates` ← `bundle.default_predicates`） |
| ③ `G2-VERSION` 真能触发 | W2A（`bundle_version` ← `active_version()`）+ W2C 改 `policy_gate:105` |
| ④ 请求级 `max_rows` 生效（200 ⇒ LIMIT 200） | W4（`state["options"]` → 新方法关键字）；W2C 侧 `_effective_limit` **无需改**（已 `min(int(...), 10000)`） |

> ⚠️ 照抄 07 的顺序提醒：修完只到 **GATE2 之后** —— `gate3_cost`（EXPLAIN）与 `execute`
> （真 DB + 身份 GUC）的判据源接缝**请在同一次里扫完**，别让"第六格"第三次重演"修一格才发现下一格"。

---

## 12 【U-121 家族第二个实例回执】`SqlExecutorPort` 端口面补齐（`aa494f6`，2026-09-21）

### 12.0 一句话

W2D `reports/w2d/RELAY.md §3b` 的请求已落：**唯一改动文件 = `app/core/contracts.py`** ——
`fetch` 增 `effective_limit`（**必填**）、**新增 `explain`**、形状 `ExplainPlan` 归本文件。
**一行实现未动。**

### 12.1 🔴 我有一处**必须反着做** W2D 的建议

W2D 写的是"形状可直接取 `app/exec/seam.py` 的 `ExplainPlan`"。**照抄会让 CI 必红**：
`app/exec/seam.py` 是 **L2**、`app/core/contracts.py` 是 **L0**，07 §3.1 R-DEP-1 禁止 L0 依赖 L2。

**已做正对照（不是推理）** —— 把 `from app.exec.seam import ExplainPlan` 注入 `contracts.py:48`：

```
R-DEP-1 分层依赖（只能依赖严格更低层） BROKEN
R-DEP-2/N-01 … KEPT    R-DEP-3 … KEPT    R-DEP-4 … KEPT
Contracts: 3 kept, 1 broken.                      exit=1

Broken contracts → app.core is not allowed to import app.exec:
  - app.core.contracts -> app.exec.seam (l.48)
```

还原 ⇒ `Contracts: 4 kept, 0 broken.`（`scripts/assert_importlinter.py` 同步 **DoD② 通过**）

⇒ **正解与 U-121 第一步同一个动作**：形状归 L0（`contracts.py`），**L2 只能再导出**
（`from app.core.contracts import ExplainPlan`）。两边各留一份定义 = 立第二份真相，本项目明禁。

### 12.2 三个判断点

| # | 判断 | 依据 |
|---|---|---|
| ① | `effective_limit` **故意不给默认值（必填）** | 它是 07 §8.6 `truncated` 判定的**唯一**正确口径（值 = `state.limit_injected`）。给默认值 ⇒ 调用方**静默漏传** ⇒ 判定口径静默失真 = 🔴 **fail-open**（与 U-121 里 `max_rows` 缺省方向同类）。"本轮没注入"由**值 `None`** 表达，不必再用默认值表达一次。**三个实现都写 `= None`** ⇒ 更宽松仍满足本声明 ⇒ **零实现改动** |
| ② | `ExplainPlan` 归 `contracts.py`（不回抄 seam.py） | 见 §12.1 的正对照 |
| ③ | `gate3_cost.py` 的 `rich_method(deps.executor, "explain", …)` 可以退休了 | 端口有 `explain` 后它就只在做"这个名字是否 callable"；`gate3_cost.py:11` 那句"**端口上没有它，缺即抛**"随之作废。⚠️ **那是 W4 的文件，我只提不动** |

`ExplainPlan` 的注释里逐条钉了两条**不得混**的语义（W2D 的 `seam.py` 原有，我原样抬进 L0）：

| 表达 | 含义 | gate3 结论 |
|---|---|---|
| 返回 `None` | 该方言**没有**这个能力（SQLite 沙箱，07 §17.4） | `SKIPPED`（"不可用 ≠ 通过"，§14.2 D6） |
| **抛异常** | 有这个能力、但**本次** EXPLAIN 失败 | `WARN`（`explain_error`，§14.2 D5，**不阻断**） |

### 12.3 跨窗口动作（谁该动什么）

| 窗口 | 动作 | 位置 |
|---|---|---|
| **W2D** | 把 `ExplainPlan = list[dict[str, Any]] \| None` 改成**再导出**（`from app.core.contracts import ExplainPlan`），`__all__` 不变 ⇒ 5 条 `test_exec_seam.py` 不受影响 | `app/exec/seam.py:76` |
| **W2D**（可选） | `ExecutorSeam.fetch` 的 `effective_limit` 也去默认值，与端口对齐。**不动也不红** —— `declared_call_face_mismatches` 对 face 内参数**豁免**默认值检查（`seam.py:159-166`），只是两边表述不一致 | `app/exec/seam.py:113` |
| **W4** | `rich_method(…, "explain", …)` → 直接属性访问；删 `gate3_cost.py:11` 的过时注释 | `app/graph/nodes/gate3_cost.py:61` |
| **W4 / W7** | **肯定面判据**由你们立（W2D §4 已给两条可直接照抄的口径：`_fullchain_deps.make_chain()` 绿档断言 `"gate_passed" in stages` + 正向对照；替身忠实性用 `declared_call_face_mismatches`）。**W0 不代写他窗口的判据** | `tests/contract/**` |
| **架构** | **编号**：W2D 倾向并入 `U-121`（同一句病"生产端口的实际调用面 > 声明面"的两个实例）。**我不自占号** | 07 §4.8 |

### 12.4 我另外核出的一条（不在 W2D 清单里）

🔴 **`eval/` 无视 CI 的类型违规 —— 证据在，门禁看不见。**

```
$ cd backend && mypy ../eval/sqlite_exec.py
..\eval\sqlite_exec.py:298: error: Unused "type: ignore" comment  [unused-ignore]
..\eval\sqlite_exec.py:344: error: Return type "Coroutine[Any, Any, None]" of "explain"
    incompatible with return type "Coroutine[Any, Any, list[dict[str, Any]]]"
    in supertype "app.exec.executor.PgSqlExecutor"  [override]
Found 2 errors in 1 file
```

`SqliteEvalExecutor(PgSqlExecutor)`（`eval/sqlite_exec.py:278`）把 `explain` 收窄成 `-> None`
（沙箱恒 `None` ⇒ gate3 `SKIPPED`，**语义是对的**），但父类 `PgSqlExecutor.explain -> list[dict[str, Any]]`
⇒ 覆盖签名不兼容。**CI 只跑 `mypy app`（`ci.yml:325`）** ⇒ `eval/` 永不进类型检查。

**对照归因**：撤掉本轮回执的改动（`git checkout -- contracts.py`）后**同样 2 条** ⇒ **零新增**，
纯属既存盲区。归属 = `eval/**`（W6）；我只登记。
若将来给 `eval/` 开 mypy，**正解是把父类返回类型放宽到 `ExplainPlan`**（端口这次已经这么做了），
而不是把子类的 `None` 改成别的 —— 那会把"方言不支持"的语义改坏。

### 12.5 诚实边界（本条最容易说过头）

- ⚠️ **抬进端口本身不会让任何现存测试变红**：`test_exec_seam.py` 查的是 `ExecutorSeam`（W2D 本地协议），
  **不查端口**。删掉端口的 `explain` ⇒ 全套测试仍绿。这正是 W2D 说的"**判据不完整**"。
  ⇒ 本轮**唯一的机械护栏是 R-DEP-1**（已正对照），而它护的是"形状别放错层"，
  **不护**"端口面 == 图真实调用面"。后者得 W4/W7 立判据（见 §12.3）。
- 未改任何实现（`app/exec/**`、`app/graph/**`、`eval/**` 一行未动）；未改 W4 的接缝测试；
  未改 `seam.py`（归属 W2D，我只给 1 行改法）。
- 工作区里 `reports/w4/HANDOFF.md` 与 `reports/w4/RELAY.md` 有 W4 的在制改动，**本窗口未暂存、未提交**。
- 本轮**已推**（用户 2026-09-21 21:2x 明示授权）。

### 12.6 验证读数（可复现）

| 项 | 读数 |
|---|---|
| `ruff check .` | **All checks passed** |
| `mypy app` | **Success / 147 source files** |
| 契约自检（`python -c`） | `ExplainPlan` 在 `__all__` ✓ · 端口方法 = `['explain','fetch']` ✓ · `effective_limit` 默认值 = `inspect._empty`（**必填**）✓ · `fetch` 关键字 = `max_rows, statement_timeout_ms, effective_limit` ✓ · 值 = `list[dict[str, Any]] \| None` ✓ |
| `lint-imports` | **Contracts: 4 kept, 0 broken** |
| `scripts/assert_importlinter.py` | **DoD② 通过**（4 条契约均证明"脏了必红"） |
| 正对照（L0→L2 注入） | 注入 ⇒ `R-DEP-1 BROKEN` + `app.core is not allowed to import app.exec` + exit 1；还原 ⇒ 4 kept |
| `pytest -q`（全量） | **1 failed, 2212 passed, 6 skipped, 3 errors**（99.6s） |
| 唯一 failed | `tests/contract/test_gate_seam_contract.py::test_plain_sql_passes_through_gate_seam` = **U-119 刻意红**（`8a4121a` 立的判据①） |
| 3 errors | `tests/integration/test_retrieval_fts_pg.py`：本机 DSN 无 DDL 权限（**环境**，非代码） |
| passed 较 §11 的 2207 **+5** | 正是 W2D `1143f99` 新增的 `tests/unit/test_exec_seam.py` 5 条 ⇒ 账对得上，非我引入 |

---

## 13 【CI 长期红根因回执】`tests/eval/**` × 421 MB 沙箱库（不占号，2026-09-29，基准 `872cd2d`）

> 受众 = **W6**（`tests/eval/**` 属主）+ **架构**（改 DoD③ 跑什么的口径）。
> 🔴 **本条同时更正我 §12.6 与 `MEMORY.md §3` 的一处错误归因**：CI 那个恒红**不是** U-119 的刻意红。

### 13.0 一句话

CI **15/15 全 failure、且每次恰 1 个 job 红**（`契约断言（DoD③）`，失败步骤恒为「全量测试」）。
根因**与研究对象的代码无关**：该步跑的是 **bare `pytest`**（`testpaths=["tests"]`）⇒ `tests/eval/**` 被一并拉进，
而它的夹具要 `data/ecom_sandbox.db`（**421 MB，被 `.gitignore:54` 的 `*.db` 忽略 ⇒ 结构上不可能进 CI 检出**）
⇒ **14 条恒红**。这是「数据物不入库」与「CI 跑全量」两处决策撞车。

### 13.1 根因链（四环，逐环带据）

| # | 环 | 出处 |
|---|---|---|
| 1 | CI 该步**裸跑 pytest**（job 名写的是 `tests/contract`，命令不是） | `ci.yml:121` 步骤名「全量测试（tests/contract = DoD③ 的载体）」⇄ `ci.yml:128` `run: pytest` |
| 2 | `pytest` 默认收集面 = 全部 `tests/` ⇒ `tests/eval/**` 被拉入 | `backend/pyproject.toml:120` `testpaths = ["tests"]` |
| 3 | 夹具直指沙箱库，**无存在性检查、无 skip 分支** | `backend/tests/eval/conftest.py:56` `sandbox_db` → `eval/_bootstrap.py:27` `SANDBOX_DB` |
| 4 | 该库**结构上不可能在 CI** | `.gitignore:54` `*.db`；实测 **421 MB**（`du -h data/ecom_sandbox.db`） |

### 13.2 隔离树实测读数（可复现）

方法（本项目既有手段）：`git archive HEAD | tar -x -C $TREE` —— **CI 视角**（未跟踪文件天然缺席，
`deploy/.env` 与 `*.db` 均不在）。

| 隔离树跑什么 | 读数 |
|---|---|
| `pytest --ignore=tests/eval` | **1972 passed / 1 skipped** ✅ |
| `pytest tests/eval` | **14 failed / 325 passed**（8.07s）❌ |
| `pytest`（全量，同 CI） | **14 failed / 2297 passed / 1 skipped** ❌ |

**14 条的精确拆分（`--tb=line` 逐条计数，实测）**：

| 错误类型 | 条数 | 落点（三处调用点 + 一处 bootstrap） |
|---|---|---|
| `sqlite3.OperationalError: unable to open database file` | **10** | `eval/sqlite_exec.py:177` ×4 · `eval/consistency.py:206` ×4 · `eval/runner.py:144` ×2 |
| `FileNotFoundError: ... data/ecom_sandbox.db` | **3** | `eval/_bootstrap.py:75`（`file_sha256(SANDBOX_DB)`） |
| `AssertionError: assert False is True` | **1** | `backend/tests/eval/test_redteam_logic.py:78`（`assert r.executed is True`；沙箱缺 ⇒ 执行不落库 ⇒ `executed=False`） |
| **合计** | **14** | ✅ 与 `-rf` 的 14 行 `FAILED` 对得上 |

⚠️ 逐条读码确认**第 4 类也是同源**：该用例 `attack_sql="SELECT pay_amount FROM v_order_paid LIMIT 5"`，
断言的是"闸门全放行 ⇒ 必须 `executed`"，沙箱不可用 ⇒ 执行不可能发生 ⇒ 断言必失败。
⇒ **14 条无一条暴露产品缺陷**（同意 W7 的"无一条代码红"）；但**三桶计数不同**，见 13.3。

### 13.3 与 W7 独立复算的对照（同一现象、读数一致，**三桶拆分不一致**）

W7 独立复算：隔离树 `14 failed / 325 passed` ⇒ **与我逐字一致**；根因链三处（`pyproject:120` / `ci.yml:121`⇄`:128` / `.gitignore:54`）亦同。
⇒ **现象与根因 = 两方独立实测同数，可当已确认。**

但 W7 的**分类拆分对不上**：报的是 `10× sqlite + 6× FileNotFoundError + 2× AssertionError`。两处问题：
1. **算术不闭合**：10+6+2 = **18 ≠ 14**（这本身就是信号）；
2. **两个桶被高估**：实测 **10 / 3 / 1**（FileNotFoundError 6→**3**、AssertionError 2→**1**）。

⇒ 本回执**以实测拆分（10/3/1）为准**；W7 那三桶建议按本表订正后再引用（数字型断言过时正是本项目反复吃过的坑）。

### 13.4 归属与出路（我不自行改，动 DoD③ 口径须架构裁）

| 出路 | 内容 | 归属 | 我的评估 |
|---|---|---|---|
| ① | `tests/eval` 对沙箱库缺失**显式 skip 并声明**（保留"数据物缺失"可见，不静默） | **W6**（`tests/eval/conftest.py`） | ✅ 推荐，与②同批 |
| ② | DoD③ 步改成**显式列目录**（`pytest tests/contract tests/unit tests/integration`），与 job 名对齐 | **W0**（`ci.yml`） | ✅ 推荐；这是"job 名撒谎"的根治 |
| ③ | CI 重建沙箱库 | W1A/架构 | ❌ 不建议：W1A 曾判"成本远超收益"；且 W6 §17.4 已证 gate3 缺的是**方言**不是数据 ⇒ 与重建无关 |
| ④ | 用 marker / `addopts` 让 eval 默认不跑 | 需裁（`pyproject.toml`） | 🟡 备选；比②隐式，容易让"eval 没跑"变成看不见 |

**我的倾向 = ①+②**：②把"job 名与实际跑的内容"对齐（消灭撒谎面），①让数据物缺失在 CI 显式可见而非变红。
⚠️ 两项**分属两个窗口**（② 归 W0、① 归 W6），须同批或②先行 —— 只做②会让 `tests/eval` 彻底不在 CI 跑（覆盖面下降），
只做①会让 job 名继续撒谎。

### 13.5 诚实边界（本条最容易说过头）

- 🔴 **这不构成"CI 曾经是绿的"的证据**：15/15 全 failure 的历史里，我此前把红记成 U-119 **是错的归因**；
  本回执只证明"**今天这一条红**"的根因，**不追认**历史各轮的绿/红。
- **本地永远复现不出来**：本机有那个 421 MB 文件 ⇒ `tests/eval` 本地恒绿；W6 本地报的也都是 `0 failed`。
  ⇒ **任何"我这边跑了 0 failed"都不构成 CI 绿证据**（已写进 `MEMORY.md §3`）。
- 未改任何测试、未改 `eval/**`、未改 `ci.yml` 的跑法（**只改了 1 条陈旧注释，见 §13.7**）；
  `tests/eval/**` 属 W6，我不动。
- 未在 CI 上验证修复（无推送授权）⇒ 出路①②**均为建议，未落地**。

### 13.6 验证读数（可复现）

```bash
# 1) 建隔离树（CI 视角）
TREE=/tmp/ci_tree; rm -rf $TREE; mkdir -p $TREE
git archive HEAD | tar -x -C $TREE

# 2) 非 eval（应为全绿）
cd $TREE/backend && ../../.venv/Scripts/python.exe -m pytest -q --ignore=tests/eval   # 1972 passed / 1 skipped

# 3) eval（应 14 failed / 325 passed）
cd $TREE/backend && ../../.venv/Scripts/python.exe -m pytest tests/eval -q --tb=line -rf
```
⚠️ **别用主工作区跑第 3 步**：那里有 421 MB 沙箱库 ⇒ 恒绿，什么也证明不了。

---

### 13.7 同批轻改：`ci.yml:87` 的自相矛盾注释

原第 87 行写 `` `tests/contract/` 的断言数会随各窗口交付持续增长（阶段 1B 实测已 386+） ``，
而**紧接着的第 88 行**声明"**本注释刻意不写具体数字**" ⇒ 同一段话自我矛盾（且 386+ 现已是 **455**）。
按第 88 行自己的规则删掉那个括号数字，改为不带数值的表述。⇒ `ci.yml` 归 W0，改动只此一行。

---

## 14 【U-114 残余面回执】夹具已「只认环境变量」，守卫由 W2B 落、W0 只出读数（不占号，2026-10-01，基准 `6b87da9`）

> 受众 = **QA**（本轮派单方）+ **W2B**（实际落码方）+ **架构**（两条守卫谁留）。
> 🔴 **第一句必须是归属更正**：QA ③ 派的是「W2B（夹具）+ **W0（守卫扩面）**」两半，**实况两半都是 W2B 落的**（§14.5）。
> W0 本轮的实际产出 = **读数与归因** ＋ 一次**自我撤销**（避免同一 hazard 两份真相）。
>
> ⚠️ **基准漂移已并入（别按旧文本引用）**：本回执起笔时 W2B 的改动还在工作树（我第一轮量到的行号是那一版）；
> 撰写期间他以 **`6b87da9`**「test(w2b/u114): T-02」入库（4 文件 / `+389 −48`：夹具 + 守卫 266 行 +
> 我防线② 文件 8 行 + 他自己 `reports/w2b/RELAY.md`）。
> ⇒ **§14.1–§14.8 的行号、「已提交」状态、以及全部读数，一律按 `6b87da9` 重列并重跑过**，不用工作树版。

### 14.0 一句话

派单要的三件事都成立，且**双向都实测过**：缺 env ⇒ `:69` 具名 fail（0 用例执行、未触共享库）；给 env ⇒ 11 passed（跑在独立端口一次性容器上）。
否定式守卫存在且自咬（R-ENVFILE，7 passed）；全树 `2289 passed / 0 skipped / 0 failed / 8 errors`。
但**「0 skipped」不等于「skip 家族被消灭」**——产生 QA 基线那 6 个 skip 的降级路径 `:107-108` **仍在**（§14.6）。

### 14.1 改动落点（file:line，改前 = `3f1c951`，改后 = `6b87da9`）

✅ 全部为 **W2B** 的改动，**已由 `6b87da9` 入库**（`git status` 该文件已干净）。下表右列行号均为 **HEAD 现值**。

| 位置 | 改前（`3f1c951`） | 改后（`6b87da9`） |
|---|---|---|
| `backend/tests/integration/test_retrieval_fts_pg.py:57` | `def _dsn_from_env_file() -> str \| None:` —— 读 `deploy/.env` 的 `DATABASE_URL`，把 `postgresql+psycopg://`→`postgresql://`、`＠pg:`→`＠127.0.0.1:` | **函数整块已删** |
| 同 `:68-69` | `PROD_DSN: str \| None = _dsn_from_env_file()`<br>`TEST_DSN: str \| None = os.environ.get("RETRIEVAL_TEST_PG_DSN") or PROD_DSN` | **`:69`** `TEST_DSN = env_dsn("RETRIEVAL_TEST_PG_DSN")` |
| 同 `:71-76` | `_needs_pg` / `_needs_prod` 两个 `pytest.mark.skipif` | **已删**（缺 env 改为 import 期 fail） |
| 同 `:47` | — | 新增 `from tests.integration._env_dsn import env_dsn` |
| 同 `:282` | （生产表对齐检查经 `PROD_DSN = _dsn_from_env_file()`） | `prod_dsn = env_dsn("COMMERCEQL_TEST_RW_DSN")` |
| 同 `:22-28` / `:62-66` / `:280` | — | 旧形态改以**注释/docstring** 留档（不参执行） |

`git show --stat 6b87da9` 该文件 = `90 ++++----`；另删掉 `import os` / `from pathlib import Path`（HEAD 版全文 **471 行**）。

### 14.2 双向验（QA ③ 前两条）

**(a) 不给 env ⇒ 具名 fail，且「未连共享库」是结构性的**

```
cd backend && pytest -q tests/integration/test_retrieval_fts_pg.py
→ 1 error in 0.47s（0 个用例执行，rc=2；文件仍在，故是 collection error 不是用法错）

RuntimeError: 环境变量 RETRIEVAL_TEST_PG_DSN 未设置 —— U-114 防线①：集成测试拒绝共享库
字面默认值，缺 env 必须 fail/error（禁止 skip）。请把它指向**一次性测试库**（不要指向共享 ecom）后重跑。
  tests\integration\test_retrieval_fts_pg.py:69  →  tests\integration\_env_dsn.py:28
```

- **具名**（点名缺哪一个变量）+ **在 import 期抛** ⇒ 任何 `_conn()` 都还没机会执行 ⇒「没碰共享库」不是运气，是结构。
- 旁证：共享 `ecom.app.embed_doc` 全程 **197**（改前 197 / (b) 跑完再读 197，§14.8 给命令）。
- ⚠️ 本机 `deploy/.env` **一直在**，而上面的 fail 照样发生 ⇒ 证明解析链**真的不再看它**（不是"恰好文件不在"）。

**(b) 给了 env ⇒ 用例真跑**

```
docker run -d --name cql-u114-probe -p 5433:5432 -e POSTGRES_HOST_AUTH_METHOD=trust \
           -e POSTGRES_DB=ecom pgvector/pgvector:pg16
cd backend && MIGRATION_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/ecom alembic upgrade head
export RETRIEVAL_TEST_PG_DSN / COMMERCEQL_TEST_RW_DSN / _RO_ / _SUPER_  指向 127.0.0.1:5433/ecom
pytest -q tests/integration/test_retrieval_fts_pg.py
→ 11 passed in 6.38s（rc=0）
```

DSN 形态**照抄 CI**（`ci.yml:124-127`：全部无口令段 + trust 认证，只换端口 5432→5433）。
⇒ 11 条**真跑过**（既不是 skip 也不是 error），且跑在**独立端口的一次性容器**上。容器跑完即删。

### 14.3 全树三态计数（带 HEAD）

```bash
cd backend && pytest -q -rfEs --continue-on-collection-errors     # env 全 unset
→ 2289 passed, 1 warning, 8 errors in 88.50s (0:01:28)     rc=1
  @ HEAD 6b87da9（干净工作树；与工作树版读数字面一致，故不是"我量的那版"的侥幸）
```

**8 errors 全部是 8 个 integration 模块各 1 条 collection error，全是 `env_dsn` 具名 `RuntimeError`**：
`test_audit_append_only` / `test_exec_real_pg` / `test_feedback_store_pg` / `test_migration_0003_views` /
`test_migration_0004_runtime` / `test_query_plan_store_pg` / `test_retrieval_fts_pg` / `test_semantic_materialization`。
**`0 skipped` / `0 failed`。**

与 QA ④ 基线对照（2,284 passed / 6 skipped / 10 errors / rc=1 @ `fd5f5f2`）：

| 态 | 基线 `fd5f5f2` | 现在 `6b87da9` | Δ |
|---|---|---|---|
| passed | 2,284 | 2,289 | **+5** |
| skipped | 6 | **0** | **−6** |
| failed | 0 | 0 | 0 |
| errors | 10 | **8** | **−2** |

**−6 / −2 的口径我不是估的，是复现出来的**：把 `fd5f5f2` 拍成隔离树、拷入本机 `deploy/.env`（= QA 基线形状），整树跑 ⇒
**`2284 passed, 6 skipped, 1 warning, 10 errors in 91.27s`** ⇒ **与 QA ④ 逐字吻合**，且 `-rfEs` 把归属直接点出来了：

| 基线那 10 个 error | 归属 |
|---|---|
| 7 条 = `env_dsn` 具名 RuntimeError | `test_audit_append_only` / `test_exec_real_pg` / `test_feedback_store_pg` / `test_migration_0003_views` / `test_migration_0004_runtime` / `test_query_plan_store_pg` / `test_semantic_materialization` |
| **3 条 = `test_retrieval_fts_pg.py::test_dense_*`**（`InsufficientPrivilege: permission denied for database ecom`） | 就是 QA 点的那 3 条 |

| 基线那 6 个 skip | 归属 |
|---|---|
| **全部 6 条都在 `test_retrieval_fts_pg.py`**（用例行 `:189/:203/:216/:237/:254/:268`），原因串一律 `夹具 DSN 无 DDL 权限（用 RETRIEVAL_TEST_PG_DSN 指向可建表实例）：permission denied for database ecom` | 同上 |

⇒ **算术闭合**：改后该文件在 `:69` 就 fail ⇒ 那 `3 error + 6 skip` 一起塌缩成 **1 条 collection error**
⇒ errors `10 − 3 + 1 = 8` ✓、skips `6 − 6 = 0` ✓。**两边的聚合读数（2284/6/10 与 2289/0/8）都已实测复现，非引用。**
⚠️ **`+5 passed` 不该记在本条头上**：那是 `fd5f5f2 → 6b87da9` 之间其他窗口的用例增量（我未逐条核归属）。

### 14.4 否定式守卫（QA ③ 第四条）

**活着的那条 = W2B 的 `backend/tests/contract/test_no_env_file_dsn_derivation.py`**（**266 行**，已随 `6b87da9` 入库），规则名 **R-ENVFILE**，
规范头逐字引判据 `docs/07:1133`（v1.7.17）。要点：

- **面** = `tests/integration/**`；**判据式** = 该目录**不得读任何 `.env` 文件内容** —— `read_text` / `read_bytes` / `readlines` / `.open()` / `open()` 且路径里静态含 `.env`，外加 `load_dotenv` / `dotenv_values`。
- 走 **AST 传递闭包**（`env_file = … / ".env"` 再 `env_file.read_text()` 这种**经变量中转**的写法才是实际形态），不是只认字面量 —— 这点比我自己那版更贴实际形态。
- **咬合证明**：`test_guard_bites_on_the_historical_shape`（`:199`）**逐字取自修复前的源码**；另 3 条咬法 = 多一跳中转 / dotenv 家族 / 裸 `open()`。
- **非空跑证明**：`test_guard_spares_the_current_integration_tree_and_is_not_vacuous`（`:262`）带 `assert len(scanned) >= 8`。
- **当刻读数**：该文件 **7 passed**；与防线② 合跑 = **11 passed in 3.28s**。

**另做三条裸 grep 独立复核同一命题**（不依赖任何守卫代码）：

| 查什么 | 结果 |
|---|---|
| `tests/integration/*.py` 里 `read_text\|read_bytes\|readlines\|\.open(` | **零命中** |
| `tests/` 里 `load_dotenv\|dotenv_values`（排除守卫文件自身） | 只命中 `tests/contract/test_config_failfast.py` —— 它读的是 `.env.example` 做**双向同步断言**，与被测 DSN 无关 |
| `tests/integration/*.py` 里 `deploy/.env` 字面量 | 只在**注释/docstring**（HEAD 版 `:22` / `:62` / `:280`），**无任何取值调用** |

⇒ QA 要的「**DSN 解析链里不再出现『读 .env 后赋给夹具变量』**」这条否定式，**守卫（AST）与 grep（文本）两条独立路径都成立**。

### 14.5 🔴 归属更正与撞车披露（本条最需要裁定的一段）

- QA ③ 派的是两半：**W2B（夹具）+ W0（守卫扩面）**。
- 实况：**两半都是 W2B 落的** —— 夹具改动（§14.1）与守卫 `test_no_env_file_dsn_derivation.py`（§14.4）同属 W2B，
  **且三件（夹具 + 新守卫 + 我文件的 8 行改动）同一条 commit `6b87da9`**；
  他甚至顺手把我防线② 文件 `test_no_shared_ecom_dsn_fallback.py` 的「诚实边界」条目改成了「✅ **已收口（2026-10-01，W2B）** … 接管这一类形态的**第二条守卫** = `test_no_env_file_dsn_derivation.py`（R-ENVFILE）⇒ 本文件不再为它开例外」。
- **W0 这一轮先扩了面、再自己撤**：我在防线② 文件里加了 `_scan_deploy_env_reads` 一族（`+146/−5`）；
  实跑发现本该 1 红却 **7 绿** ⇒ 读码后确认 W2B 已把夹具改好、且已立同款守卫
  ⇒ **`git checkout -- backend/tests/contract/test_no_shared_ecom_dsn_fallback.py` 整块撤销**（同一 hazard 摆两份真相，正是本项目反复吃过的坑）。
- ⇒ **请 QA / 架构裁一条**：守卫产物留哪个。**现状 = R-ENVFILE 活着、我的扩面已撤**（我无异议）。
  若裁定 W0 侧也需保留一条，请明确**分工面**（例如 R-ENVFILE 管「集成目录读 `.env`」、防线② 管「字面量默认值指向共享 `ecom`」），**不能再有第三份**。

### 14.6 🔴 我核出的一条未收口面（不在派单里，也不属本条判据）

`test_retrieval_fts_pg.py:107-108`（`3f1c951` 时为 `:115-116`）的降级路径**仍在**：

```python
    except psycopg.errors.InsufficientPrivilege as exc:
        pytest.skip(
            f"夹具 DSN 无 DDL 权限（用 RETRIEVAL_TEST_PG_DSN 指向可建表实例）：{exc}"
        )
```

- **它就是 QA 基线那 6 个 skip 的产生器**。本轮收口删的是「缺 env ⇒ 回退 `.env`」这一环，
  **没删「env 给了、但该角色无 DDL ⇒ 静默 skip」那一环**。
- ⚠️ 因此 **§14.3 的「0 skipped」不可读成「skip 家族已被消灭」**：那是因为 env 全 unset（走 import 期 fail），
  不是因为降级路径没了。**给一个只读 DSN 进去，那 6 条会再次静默 skip，与 QA 基线同形。**
- 同族另一处 `:290-297`（目标库没有 `app.embed_doc` ⇒ skip）注释里自称刻意与「对齐失败」分开 —— 这条我认为**合理**
  （它区分了"没验到"与"验过不对"，符合本项目的 error 分类纪律）；
  `:107` 那条性质不同：它把「**显式指了一个不能建表的实例**」这件**配置错误**降级成了 skip。
- ⇒ 是否把 `:107` 改成**具名 fail**（"你给的 `RETRIEVAL_TEST_PG_DSN` 无 DDL 权限，这 9 条用例无法执行"）**属判据扩张，我未自行改**。
  报 QA / 架构裁；归属 **W2B**（该文件属主）。

### 14.7 诚实边界（本条最容易说过头）

- **本条 W0 未落一行代码**：§14.1 的改动与 §14.4 的守卫**都是 W2B 的**，已由 **`6b87da9`** 入库（**不是我的 commit**）。
  W0 的产出只有读数、归因、和一次撤销。
- **§14.3 的 8 errors 全部是「环境未备」，无一条产品缺陷**：8 个模块都在 import/collection 期就 fail，一个断言都没跑到。
- **`+5 passed` 不归本条**：来源是 `fd5f5f2 → 6b87da9` 之间他窗的用例增量，我未逐条核归属。
- **我没在 CI 上验证过任何一条**（无推送授权）；本轮**未推**任何东西；W2B 的文件我一行未改（属主不在我）。
- 本机 `deploy/.env` 存在，与「改后代码不再看它」不矛盾 —— 判据要的正是**不依赖它**（§14.2(a) 已证）。
- 🟡 **一处他窗数字型瑕疵（我未改，只登记）**：该文件 docstring `:21` 写「与另外 **8 个** integration 模块同款」，
  实测调用 `env_dsn` 的 integration 模块 = **8 个（含本文件）** ⇒ 应为「另外 **7 个**」。
  量：`grep -rn "env_dsn(" tests/integration/*.py | grep -v _env_dsn.py` ⇒ 8 个文件 / 18 处调用。

### 14.8 验证读数（可复现）+ 容器点名

```bash
# (a) 不给 env：具名 fail、0 用例执行、未触共享库
cd backend && pytest -q tests/integration/test_retrieval_fts_pg.py
#   → 1 error in 0.47s   @ :69 → tests/integration/_env_dsn.py:28

# (b) 给 env：一次性容器（独立端口，DSN 形态照抄 ci.yml:124-127，只换端口）
docker run -d --name cql-u114-probe -p 5433:5432 -e POSTGRES_HOST_AUTH_METHOD=trust \
           -e POSTGRES_DB=ecom pgvector/pgvector:pg16
cd backend && MIGRATION_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/ecom alembic upgrade head
export RETRIEVAL_TEST_PG_DSN=postgresql://postgres@127.0.0.1:5433/ecom      # 另 RW/RO/SUPER 同指 5433
pytest -q tests/integration/test_retrieval_fts_pg.py   # → 11 passed in 6.38s（rc=0）
docker rm -f cql-u114-probe

# (c) 全树三态（env 全 unset）
cd backend && pytest -q -rfEs --continue-on-collection-errors
#   → 2289 passed, 1 warning, 8 errors in 88.50s   rc=1   @ 6b87da9（干净树）

# (d) 基线形状复现（证明 −6 skip / −2 error 的归属）
T=/tmp/base_fd5f5f2; rm -rf $T; mkdir -p $T; git archive fd5f5f2 | tar -x -C $T
cp deploy/.env $T/deploy/.env
cd $T/backend && pytest -q -rfEs --continue-on-collection-errors
#   → 2284 passed, 6 skipped, 1 warning, 10 errors in 91.27s   （与 QA ④ 逐字吻合）

# (e) 共享库未被动过的读数
docker exec commerceql-pg-1 psql -U app_rw -d ecom -tAc "select count(*) from app.embed_doc"
#   → 197（改前 197 / (b) 跑完再读 197）
```

⚠️ (a)(b) 两跑**都重跑在 `6b87da9` 的已提交字节上**（不是起笔时的工作树版）—— 因为 W2B 在回执撰写期间入库，
差一个 docstring 行，行号会差 1。**读数以已提交版本为准。**

**容器点名（QA ⑤ 硬边界要求）**：`cql-u114-probe`，**宿主端口 5433**，镜像 `pgvector/pgvector:pg16`，跑完即删。
共享栈**一次都没碰**：全程未对共享 `ecom` 跑集成套件、**未对共享库跑 alembic**；`app.embed_doc` 恒 **197**。

⚠️ 另有一个**不是我起的**容器在跑：`cql-it-pg-w2b-t02`（宿主 `:5434`）= **W2B 自己在用**，正是本轮撞车的同一个面（§14.5）。

---

## 15 【U-133 判据③ 回执】AST 守卫扫描面已扩到 `deploy/loadtest/**` + `eval/**`（不占号，2026-10-02，基准 `ce85db0`）

> 受众 = **QA**（派单方）+ **架构**（③ 的谓词面、以及"存量登记"可否接受）+ **W2B**（扩面首跑咬到的存量件属主）。
> 🔴 三件先说在前面：**①** ③ 的**字面要求与它自己带的对照件互相矛盾**（照字面做必红），我按契约原意实现了**面二**；
> **②** 扩面**不是空转** —— 首跑咬到 **1 处真违规**（§15.4）；**③** 但 ③ **盖不住 `U-133` ① 本身**（§15.5）。

### 15.0 一句话

`backend/tests/contract/test_no_env_file_dsn_derivation.py` 的扫描面 = `tests/integration/**` ∪ `deploy/loadtest/**` ∪ `eval/**`；
新面采用 **DSN 限定规则**（只有"从 `.env` 取 DSN"才算违规，判据式 = 读取所在**作用域内出现 DSN 键名**）。
首跑实测三数：面一 **0** 命中、`deploy/loadtest/**`（12 文件）**1** 处真违规、`eval/**`（18 文件）**0**。
**扩面后 `tests/contract` 全绿（479 passed）**；ruff 件与整目录均 `All checks passed`。

### 15.1 落了什么（全在 W2B 的那一件上，未新建第二份）

| 位置 | 改动 |
|---|---|
| `test_no_env_file_dsn_derivation.py:61-70` | 加 `_REPO_ROOT` / `_LOADTEST_DIR` / `_EVAL_DIR` / `_PROBE_FACES`（面二两棵树） |
| 同 `:82-89` | 加 `_DSN_KEY_RE`（DSN 键族：`DATABASE_URL`/`DSN`/`*_DB_URL`/`PG*URL`/`POSTGRES*URL`/`SQLALCHEMY_DATABASE_URI`，两侧带标识符边界） |
| 同 `:95-104` | 加 `_KNOWN_LEGACY_HITS`（存量登记，见 §15.4） |
| 同 `_enclosing_scope` / `_names_dsn_key` | 新增两个纯函数（作用域定位 + 键名判定） |
| 同 `_scan_source(source, *, dsn_scoped=False)` | 加参数：`False` = 面一严规则（原行为不变）；`True` = 面二 DSN 限定 |
| 同 `_scan(directory, *, dsn_scoped=False)` | 同上；并让展示路径先试 `backend` 再试仓库根（`eval/`、`deploy/` 才显示得出来） |
| 文件头 docstring | 加「面一/面二」说明、`U-133` ③ 判据出处、对照件说明、诚实边界三条 |
| 新增 4 条测试 | 见 §15.3 |

⚠️ 顺带订正该件 docstring 一处**数字型瑕疵**（`§14.7` 已登记、此处落地）：原文「与另外 **8 个** integration 模块同款」→ **7 个**
（实测调用 `env_dsn` 的 integration 模块共 8 个、**含本件**）。同一件内改动，已在此具名。

### 15.2 🔴 为什么不能"照字面扩面"：③ 与它自己的对照件互斥

`docs/07:1163` 的 ③ 说「扩到 `deploy/loadtest/**` 与 `eval/**` ⇒ 扩面后 `tests/contract` **须全绿**」，
**同一格末尾**又写着：「⚠️ 对照件（防下一轮误报）：`eval/reporter.py:595` 也读 `deploy/.env` … ⇒ **不是本案**」。

两条一起看：**现规则（"不得读任何 `.env`"）** 扩到 `eval/**`，`reporter.py` **必被咬中** ⇒ ③ 的"须全绿"当场不成立。
**实测**（HEAD `ce85db0`，`_scan_source(eval/reporter.py)`）：

| 规则 | 命中 |
|---|---|
| 面一（严：任何 `.env` 读取） | **1** 处 —— `eval/reporter.py:597` `open()`（读路径经变量静态指向 `.env`） |
| 面二（DSN 限定） | **0** 处 |

⇒ 我的解法**不是给 `reporter.py` 开白名单**（那是"缩门禁 scope"），而是把判据从**动作**收到**意图**：
面二只禁"从 `.env` 拿**连接串**"。`reporter.py` 那个块的形态是 `re.match(r"...BINDING_TAU[A-Z_]*...")` 后 `bool(...)`
—— 只抽 `BINDING_TAU*` 开头的键、值归一成布尔、**不落值**，作用域内**没有任何 DSN 键名** ⇒ 正当放过。
**并已证这条收窄是承重的**（不是把规则改松）：同一份合成源码在面一规则下命中 **1**、面二规则下命中 **0**；
真件 `eval/reporter.py` 在面一规则下**必红**、面二下**为绿**（两条断言都写在 `test_guard_spares_the_reporter_shape_by_rule_not_by_exemption` 里）。

### 15.3 首跑读数（带 HEAD）+ ④ 要的两个 ruff 数

| 项 | 读数 |
|---|---|
| HEAD（首跑） | **`ce85db0`** |
| 面一 `tests/integration/**` | **0** 命中 |
| 面二 `deploy/loadtest/**`（12 个 `.py`） | **1** 命中（真违规，见 §15.4） |
| 面二 `eval/**`（18 个 `.py`） | **0** 命中 |
| 守卫自身 | **10 passed**（原 7 条 + 新增 3 条） |
| `pytest -q tests/contract` | **479 passed, 1 warning**，rc=0 |
| 复跑（**含本提交的干净 HEAD `7afbde9`**） | `tests/contract` = **479 passed**，rc=0（同一数字，防"首跑是侥幸"） |
| ruff ① **本轮件形状** | `ruff check tests/contract/test_no_env_file_dsn_derivation.py` ⇒ **All checks passed** |
| ruff ② **整目录形状** | `ruff check tests/contract/` ⇒ **All checks passed** |

新增 3 条测试：
1. `test_probe_faces_have_no_new_dotenv_dsn_reads` —— 面二零**新增**命中 + 存量被修而不销账也红（双向逼登记表）；
2. `test_guard_bites_on_dsn_key_extraction_in_probe_face` —— 面二**正对照**：读 `.env` 且作用域有名 DSN 键名 ⇒ 必咬；
3. `test_guard_spares_the_reporter_shape_by_rule_not_by_exemption` —— 对照件按**规则**放过（含"收窄承重"证明）。

### 15.4 🔴 扩面首跑咬到的真违规（不是我造的，也不是本条的判据）

```
deploy/loadtest/w2b_materialize/_w2b_u112_materialize.py:56  read_text()  ← 读路径静态含 .env，且作用域内出现 DSN 键名
```

逐行读码（只报形状、不复述任何值）：该件 `:51` 的 `rw_dsn()` 用 `(REPO / "deploy" / ".env").read_text()`
取 `DATABASE_URL`、把容器视角的 compose 服务名换成 `127.0.0.1` 后**返回一个可用的 libpq 连接串**；
`:68` 直接 `psycopg.connect(rw_dsn())`，另在 `:123` / `:167` 复用。
⇒ 与 `U-114` 残余面**同形**（读 `.env` → 造 DSN → 连**共享 dev 库**），只是宿主在 `deploy/` 而不是 `tests/`。
⚠️ **同族还有第二件**：`deploy/loadtest/w2b_materialize/_w2b_u112_verify_read.py:30` `from _w2b_u112_materialize import ... rw_dsn`，
`:_48/:60/:74` 同样用它连库 ⇒ **一处定义、两处使用**。

**我的处理 = 只登记、不代改**（属主 W2B 的件、所在树 `deploy/**` 属 W7）：登记为 `_KNOWN_LEGACY_HITS` 一条，纪律两条 ——
**新增命中一律红**；**存量修掉后必须销账**（`stale` 断言会在修完未销账时变红，防登记表烂成永久后门）。
**这不是豁免**：面二对"新出现的同形写法"立即咬。是否另开号上呈，**我不占号**（编号归 QA/架构）。

### 15.5 🔴 ③ **不足以**覆盖 `U-133` ① 本身（这条最重要，别拿 15.3 的全绿当 ① 的达标凭证）

`U-133` ① 的主体是 `deploy/loadtest/load_synth_to_pg.py`：`:42` 一个**模块级字面 `DEFAULT_DSN`**（含属主段+口令段，
指向共享 `ecom`）、`:183` 把它当 `--dsn` 的 default、`:134` 下游是 `truncate app.{base}`。
**实测该件在两条守卫下都是 0 命中**：

| 守卫 | 谓词（入口形状） | 在 `load_synth_to_pg.py` 的命中 |
|---|---|---|
| 本件 R-ENVFILE（面一/面二） | "读 `.env` 文件内容" | **0** —— 它全文 `os.environ`/`getenv`/`.env` **均 0 处**，根本不读 `.env` |
| 防线②（`test_no_shared_ecom_dsn_fallback.py`） | "`os.environ.get/getenv` 的**兜底操作数**是共享 `ecom` 字面量" | **0** —— 裸的模块级常量**不在它的形状里**（已在 `deploy/loadtest` 全树 12 文件、`eval` 全树 18 文件各测过） |

⇒ **两条守卫的"面"（path）扩了，"谓词"（shape）都没扩** —— 而 ① 是**第三种形状**：
"运行期 DSN 的字面默认值"。③ 只说了扩**面**，所以照 ③ 做完**仍然测不到 ①**。
**我未自行扩判据**（判据扩张要裁）：要真正封 ①，需要一条新谓词 —— 例如
「`deploy/loadtest/**` 里**任何** DSN 值来源必须可静态判为『环境变量或命令行参数』；
模块级字面 DSN 常量被当作连接/`--dsn` 默认值即违规」。
⚠️ 这条**一落就是红的**（`:42` 还在，属 W7 的 ①），与 ③ 的"须全绿"直接冲突 ⇒ **两条路请裁**：
(A) **等 ① 先落**，再同批落这条谓词（那时它天然绿，"绿"是因为缺陷没了）；
(B) 现在落成**预期红**并在件里具名登记（违背 ③ 的"须全绿"字面，但护栏立刻开始工作）。
**我建议 (A)**，理由：本项目已因"改了措辞/换了口径就把判据悄悄放宽"付过代价；`(B)` 的实际效果常常是下一轮把它改成 skip。

### 15.6 答复 ③ 的归属问题（「守卫产物只留一份」由谁持有）

- **产物仍是唯一一份**：`backend/tests/contract/test_no_env_file_dsn_derivation.py`（W2B `6b87da9` 建、W0 本轮扩面）。
  **持有 = W2B（件主）**；**扩面动作 = W0**（`docs/08 §4.1` 该行明写「守卫扫描面此前只覆盖 `tests/integration/**`，**扩面归 W0**」）。
  **没有第二棵树、没有第二份规则** —— 与 `§14.5` 撤销那次同一个原则。
- 关于 `tests/contract/**` 表上写 **W4** 的漂移：**`docs/08:309` 那一行自己已经具名登记过**
  （「⚠️ 另一处漂移（**归总控裁**，架构不擅改别窗行）：下一行 `tests/contract/**` 表上写 W4，而 git 现测提交分布 = w4 19 / w0 6 / w7 4 / w2b 2 / w2a 2 / retrieval 2」）。
  ⇒ 本轮我**不新建树**、只在既有件上扩面，**不加剧**该漂移；
  但**若总控裁定 `tests/contract/**` 归 W4**，则本轮应记为「**W0 代 W4 落笔、需 W4 追认**」（与 `U-124` 里「W2A 代 W0+W1B 落完 ⇒ 追认 + 两份复核回执」同一先例），请裁。

### 15.7 诚实边界

- **`tests/contract` 的"全绿"含一条存量登记**：不是零违例，而是"零**新增**违例 + 一条具名存量"。
  登记表在件里，可被任何窗口复核；**它不是 skip、不是 `xfail`、不是目录排除**。
- **我没动 `:107-108`**（`except InsufficientPrivilege: pytest.skip`）—— QA ⑤ 明令不先动，我一行未改；
  它在 `U-133` 是否属"禁 skip"范围由 QA 的 O-6 上呈架构裁。
- **我没改 W2B 的 `_w2b_u112_materialize.py` / `_w2b_u112_verify_read.py`，也没改 W7 树里的任何件**（只登记）。
- **锚点是行号**：`_KNOWN_LEGACY_HITS` 记 `…:56`，该件若被改行会漂 ⇒ `stale` 断言会红并提示"更新锚点"。
  这是刻意的（宁可吵一次，也不要悄悄失效）。
- **面二的 DSN 键名判定是作用域级近似**：键名与读取不在同一函数 ⇒ 漏判；它挡"顺手从 `.env` 拿连接串"，不是完备污点分析。
- **本条不含任何口令字面量**（口径同 `U-134` 的纪律）；所有 DSN 一律只写形状。
- 本轮**未推**任何东西；也未占号。

### 15.8 验证读数（可复现）

```bash
# (a) 守卫自身（含面二正/负对照）
cd backend && pytest -q tests/contract/test_no_env_file_dsn_derivation.py        # → 10 passed

# (b) 扩面后全目录（③ 的验收位）
cd backend && pytest -q tests/contract --basetemp=/tmp/bt_ct                     # → 479 passed, rc=0

# (c) ruff 两个数（④ 要求）
cd backend && ruff check tests/contract/test_no_env_file_dsn_derivation.py       # → All checks passed
cd backend && ruff check tests/contract/                                         # → All checks passed

# (d) 三面命中数（复算 §15.3；纯读、零写）
cd backend && ../.venv/Scripts/python.exe -c "
import importlib.util,pathlib
s=importlib.util.spec_from_file_location('g','tests/contract/test_no_env_file_dsn_derivation.py')
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
for f in m._PROBE_FACES: print(f, len(m._scan(f, dsn_scoped=True)))
print('面一', len(m._scan(m._INTEGRATION_DIR)))"
# → deploy/loadtest 1 ／ eval 0 ／ 面一 0
```


