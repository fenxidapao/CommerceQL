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

