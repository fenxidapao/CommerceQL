# W2A → 各窗口 转述件（逐条可直接复制）

> 生成：2026-09-16 ｜ 归属窗口：W2A ｜ 配套交付说明：`backend/reports/w2a/DELIVERY.md`
>
> **用法**：每一节就是一个"整块可粘贴"的消息，收件人在标题里写明。直接复制该节引用块即可。
>
> ⚠️ 本文件**不含任何 DSN 字面量**（连示例都不写）—— 沿用 W1B 的密钥扫描纪律；描述形态时写「`postgresql+psycopg://` + 用户名 + `:` + 口令 + `@` + 主机」。
>
> **编号说明**：W2A 无 U 号区间。本文件提出 **U-54 / U-55 / U-56（均为"待架构分配"建议号）**，未获架构登记前不得引用为已编号问题。

---

## 1 → W1B：三项接线请求（按约定我不碰 main.py / startup_assertions.py）

> **W2A → W1B：语义层运行时已交付，请收 3 项接线**
>
> W2A 产物已落 `app/semantics/**`（DELIVERY 见 `reports/w2a/DELIVERY.md`，59 passed / 门禁全绿）。按约定接线动作归你收集执行，三条如下：
>
> **① 启动断言注入**（`app/repo/startup_assertions.py` 的 semantic 槽位）：
> 用 `app.semantics.validate_bundle_path`。签名：`validate_bundle_path(path, *, embedding_model, embedding_dim, tokenizer_probe)`，async；语义包缺失/非法时抛 `SemanticBundleError`。期望形态与现有 PENDING 槽位一致：加载失败 = PENDING（软依赖，N-21），**不得**因它 503。
>
> **② readiness 探针注册**：`app.semantics.build_semantic_bundle_probe(runtime_provider)` 产出 `ProbeFn`。注意：**runtime 未装配（provider 返回 None）时它返回 healthy=False** —— 这是"未接线"的诚实表达，不是缺陷；接上即转真。
>
> **③ 迁移链**：`0002_semantic_materialization`（语义物化 9 表 + pgvector + embed_doc 双索引）已在**本地库实测执行成功**（0001→0002，pgvector 0.8.6 可用）。请把它纳入 compose/CI 的迁移执行路径。属主 DSN 用法不变：`MIGRATION_DATABASE_URL` 环境变量，**必须带 `+psycopg` 驱动段**（`postgresql://` 裸形态会被 SQLAlchemy 路由到 psycopg2 → 本地已实测报 `No module named 'psycopg2'`）。
>
> 另披露：我在本地开发库执行了 `alembic upgrade head`（0001→0002），只增不改，audit 集成测试实测不受影响。

---

## 2 → W2B：tokenizer 交接（N-24 同源问题，有 U-54 依赖）

> **W2A → W2B：你的 tokenizer 是物化 tsv 的唯一注入点，但落点冲突待裁（U-54）**
>
> 1. 物化侧已留注入点：`app.semantics.materialize.materialize(..., tokenizer=tokenize)`。你不注入时，`synonym.tsv` 全 NULL + `pending_tokenizer`（**如实 PENDING，不是通过**）—— 本地实测当前就是此状态。
> 2. N-24 要求写入侧与查询侧**同一分词器**：查询侧 = 你的检索 tsv 查询，写入侧 = 上面这个参数。**两边必须拿到同一个 `tokenize`**。
> 3. 阻塞：`core/contracts.py`（tokenizer 契约在 L0/L1）与 08（实现在你的 L3 `retrieval/tokenizer.py`）冲突，W2A（L1）不能 import 你的 L3（`lint-imports` R-DEP-1 实测会拦）。建议形态：**契约留 contracts，实例由装配根（W1B/W4）同时注入物化与检索两侧**。已提 U-54 待架构裁，裁定前请不要自行从 semantics 里 import 任何东西来"打通"。
> 4. 你的 `test_retrieval_tokenizer.py` 目前有 2 条 ruff 红（I001/RUF021，W2B 自留地，我没动）；全量 `pytest tests/unit` 还被 W2D 的 `app/exec/errors.py` 语法错误挡住收集 —— 两处都不是 W2A 产物，转达给你们自行收口。

---

## 3 → W2C（guard）：可用的语义层查询面

> **W2A → W2C：guard 可用的语义层接口**
>
> `app.semantics.SemanticBundleRuntime`（W1B/W4 装配后经 `SemanticBundlePort`/直接实例可达）提供你需要的黑名单与敏感列：
> · `lookup_blacklist(term)` / `resolve_terms(text)` → `[{surface, canonical, kind}]`（歧义词会带出，**不会被静默解析掉**——与 W1A 的"大促只进 blacklist"设计一致）；
> · `is_denied_column(asset, col)` / `deny_columns` → 敏感列拦截；
> · `asset(logical)` → 含 `tenant_scoped` 声明。
> 注意：runtime **尚未被装配**（没人 new 它）—— 在 W1B 接线前你若要联调，可先 `load_bundle(semantic/bundle_2026.09.14.1.yaml)` 自建实例，这是公开 API 不是 hack。

---

## 4 → W2D（exec/mask）：CLS 白名单与派生 SQL 的关系

> **W2A → W2D：你若需要列白名单，用 runtime，不要自己解析语义包**
>
> 应用侧列白名单（ADR-10 的"应用侧保险"）= `runtime.asset_allowlist(role)`（已按 deny_columns 裁剪、tenant_id 已剔除）；DB 侧 GRANT 由 `materialize.derive_policy_statements()` 派生（ADR-10 的"DB 侧保险"）。两者**同源**（同一语义包、同一份代码派生），DoD③ 用 `assert_grant_policy_consistency()` 双向核对。**任何一边手写/复制白名单都会让双保险变成两份会漂移的真相。**
> 另：`app/exec/errors.py` 当前有 IndentationError（第 131 行起，函数体缺失），挡住全量单测收集 —— 判定为你窗口在制品，我未触碰，仅转达。

---

## 5 → 架构窗口：三条待裁决（建议号 U-54/U-55/U-56，均未擅自落码）

> **W2A → 架构：W2A 完成度 90%，剩余 10% 全部卡在三条裁决上**
>
> 交付详情见 `reports/w2a/DELIVERY.md` §5。逐条给可选解与后果：
>
> **① U-54（待分配）TokenizerPort 落点**：contracts（L0/L1）说契约归它，08 说实现归 retrieval（L3），§6.2 说 tsv 写入侧（W2A，L1）与查询侧必须同源。L1 import L3 被 R-DEP-1 实测拦截。
> 可选解：(a) 契约在 contracts、实例由装配根注入两侧（**W2A 推荐**，零分层破坏）；(b) 把 retrieval/tokenizer 移到 L1（改 W2B 归属）。
>
> **② U-55（待分配）RLS 落点缺口**：§13.3 模板对 `v_*` **视图** `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`，但 PG 的 RLS **只适用于表**（实测 `WrongObjectType`）。`materialize(with_policy=True)` 会在第一条 RLS 语句整体回滚 —— §6.2 步骤②③无法完成。
> 可选解：(a) RLS 落基表/物化表，视图透传；(b) `security_invoker` 视图 + 基表 RLS；(c) 放弃 DB 侧 RLS，租户谓词全走执行层注入（评测口径现状）。三者的越权防线与审计面**不同**，需要你拍板；我未选任一落码。
>
> **③ U-56（待分配）业务视图 `v_*` 的 DDL 归属**：8 个 `v_*` 资产在库里不存在（数据在 SQLite 沙箱）。谁来建、建在哪层（compose init? 迁移? 数据窗口?）没有归属。视图不存在 → GRANT/一致性检查连对象都没有 → **DoD③ 端到端持续无法运行**（集成测试已写好，2 条 skip 理由即此）。
>
> 三条都已在集成测试与 DELIVERY 里如实标注 skip/pending，未伪装完成。请登记编号并给方向。

---

## 6 → 下一窗口开工提示词（按约定写入本文件，可整块复制开新窗口）

> **【窗口提示词 · 语义层收口（W2A 后续，建议 W7 或 W4 联调窗口执行）】**
>
> 你是 CommerceQL「语义层收口」窗口的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 main。上游契约优先级：附录 A > PRD > 06 > 07 > 08。
>
> 背景：W2A 已交付语义层运行时（`app/semantics/**`，见 `backend/reports/w2a/DELIVERY.md`）。你的任务不是重写它，而是把它**接到运行中的应用**并跑通完整发布流程：
>
> 1. （前提）确认架构窗口已裁决 `reports/w2a/RELAY.md` §5 的 U-54/U-55/U-56；未裁决先停，不要替架构做选择。
> 2. 按 `reports/w2a/RELAY.md` §1 的三项接线请求实施（startup_assertions 注入 `validate_bundle_path`；probe 表注册 `build_semantic_bundle_probe` 产出；迁移链纳入 0002）。
> 3. 用 `app.semantics.materialize` 走一次**完整六步发布**（真实包 `semantic/bundle_2026.09.14.1.yaml`）：物化 → with_policy=True → Redis 单键切换（键 = `cache.keys.active_version()`，注入传参）→ `assert_grant_policy_consistency` 全绿。tokenizer/embedder 就绪则注入，未就绪则保持 PENDING 并在报告里如实记录。
> 4. 红线：不伪造实现；未接线不得报已实现；测试集冻结禁调参；接线外的文件（main.py 除外，本窗口获授权）改动前先 `git status` 确认不是别的窗口在制品；同文件多处编辑串行改 + grep 复核。
> 5. 交付：`backend/reports/<你的窗口>/DELIVERY.md` + `RELAY.md`（含给下一窗口的提示词），提交前跑 pytest（你的范围）/ruff/mypy/lint-imports 四件套并记录**实测**结果。
>
> ⚠️ 若 U-55 裁决为 (c)（放弃 DB 侧 RLS），`derive_policy_statements` 的 RLS 段要按裁决重写并重跑注入对照 —— 这是唯一允许触碰 W2A 产物的授权范围（只此一处、需在 DELIVERY 里留改动记录）。

---

> **给 W3A/W3B/W3C 的一句话**（不单独成节）：语义层查询面见 RELAY §3（runtime 的 alias/dimension/field_binding/metric 系列方法），你们绑定与规划需要的 L1–L3 查询都有；装配方式由 W1B/W4 统一接线后经 `SemanticBundlePort` 注入，**不要各自 load_bundle 造成多实例漂移**。
