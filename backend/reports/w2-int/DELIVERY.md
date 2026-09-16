# W2-INT DELIVERY —— 阶段 2 收口窗口交付

> 日期：2026-09-16 ｜ 窗口：**W2-INT**（收口，不做功能开发）｜ 红线自查：本文所有"已落地"给出可核对位置（文件+行/键）。
> 逐窗口回执与下一阶段提示词见同目录 `RELAY.md`；端到端实测脚本 = `reports/w2-int/e2e_stage2_check.py`（可复跑）。

---

## 0. 结论先行

| 项 | 状态 | 一句话 |
|---|---|---|
| 接线三件套（W2A RELAY §1） | ✅ 全部落地 | startup_assertions 注入 / readiness 探针注册 / 迁移链核验 |
| 全量门禁 | ✅ pytest / lint-imports / assert_importlinter 全绿；⚠️ ruff 34 条 + mypy 22 条 = W2B/W2C 债（逐条归属，未吞） | 见 §4 |
| 端到端 /healthz | ✅ **ready=200**，`semantic_bundle_loaded=True`，`bundle_version=2026.09.14.1` | 接线前 503 → 接线后转真 |
| 六步发布演练 | ✅ 步骤①③④⑤⑥ 实测通过；步骤②（with_policy=True）**BLOCKED**（U-55/56） | BLOCKED 证据已留实测输出 |
| 裁决上呈 | ✅ 9 条合并去重成单一清单（U-54~56、U-58~61 候选、U-62~64） | 见 `RELAY.md` §2，未替架构选方案 |

---

## 1. 接线内容（唯一落笔区，均可核对）

### 1.1 `backend/app/repo/startup_assertions.py`（W2A RELAY §1①）
- 新增编排函数 `_evaluate_semantic_with_validator(validator)`（行 469 起）：实际 `await validator()`；`SemanticBundleError`（包缺失/非法）→ **PENDING**（软依赖，不拒启动；prod 经 `strict_in_prod` 收紧）；非预期异常 → FAIL（校验器缺陷 fail-fast）；成功 → PASS。
- `run_startup_assertions` / `enforce_startup_assertions` 增加可选参 `semantic_validator`（默认 None = 原插槽语义不变，向后兼容 W1B 既有测试）。
- `evaluate_semantic_bundle` 的 PASS 分支语义收窄为"编排层已实际调用"（docstring 已更新）。
- 分层合规：repo(L0) **不 import** `app.semantics`(L1)（R-DEP-1），只 import `app.core.errors.SemanticBundleError`（L0 层内）；校验器由组装根注入 —— 与 W2A materialize 注入 Redis 键同款修法。

### 1.2 `backend/app/api/routers/health.py`（W2A RELAY §1②）
- 新增 `SEMANTIC_RUNTIME_STATE_KEY = "commerceql.semantic_runtime"`（行 48 起）。
- `readiness()` / `aggregate()` 的 `bundle_version` 从 `app.state` 读运行时真实值（`_bundle_version()`，行 128 起）；未装配 = None（不填占位串）。

### 1.3 `backend/app/main.py`（组装根，W2A RELAY §1②）
- lifespan 新增步骤 2.5：软加载语义包（`load_bundle` → `SemanticBundleRuntime`），失败（`SemanticBundleError`）= WARN + runtime 保持 None，**不拒启动**；非预期异常不吞（bug fail-fast）。
- `enforce_startup_assertions(..., semantic_validator=_semantic_validator)` —— 注入 `validate_bundle_path(path, embedding_model, embedding_dim)`（tokenizer_probe 留空，等 U-54）。
- 注册探针：`health.register_probe(SEMANTIC_BUNDLE_LOADED, build_semantic_bundle_probe(lambda: semantic_runtime))`；runtime 存入 `app.state`。探针与断言**共用同一运行时实例**（防多实例漂移）。

### 1.4 迁移链纳入 0002（W2A RELAY §1③）—— 核验 + 缺口披露
- 0002 存在：`backend/app/repo/migrations/versions/0002_semantic_materialization.py`；本地库 0001→0002 已实测执行（W2A 交付时完成，本次 E2E 复核物化写入 197 embed_doc 复现成功）。
- **缺口（转 W0）**：`deploy/docker-compose.yml` 与 `.github/workflows/ci.yml` **均无 alembic 执行步骤**——迁移链当前是"手动 `alembic upgrade head`"。0002 在 versions/ 目录内会被 `upgrade head` 自动纳入，但"迁移先于 api"（07 §18.2）没有机器保证。deploy/.env 另有行内注释（compose env_file 会把注释并进值，本机实测 Settings 校验 15 项报错）→ W0 需修 .env 格式并在 compose/CI 落迁移步骤。
- **缺口（转 W0）**：api 服务**未挂载 `../semantic`** → 容器内 `/semantic/bundle_2026.09.14.1.yaml` 不存在，容器内 bundle 永远加载失败（readiness 持续 503）。本机验证用环境变量覆盖为宿主路径。

---

## 2. 核验结果（07 §4.7.4 抽查：声称 → 可核对位置 → 判定）

| 窗口 | 声称 | 核对位置 | 判定 |
|---|---|---|---|
| W2A | `validate_bundle_path` 交付 | `app/semantics/loader.py`（async，签名含 embedding_model/dim/tokenizer_probe） | 属实 |
| W2A | 探针"未接线=healthy=False 诚实表达" | `app/semantics/probe.py` runtime None 分支 | 属实 |
| W2A | materialize 全集 + 0002 迁移 | `materialize.py` 行 100/421/475/486/495/530；versions/0002 | 属实 |
| W2B | tokenizer 唯一入口 / 四路检索 | `app/retrieval/tokenizer.py` 等全模块在位；N-24 契约测试运行通过 | 属实 |
| W2B | dense.py 有 F821 债（W2D 转达） | `app/retrieval/dense.py:273` `Mapping` 未导入（`__future__ annotations` 下不炸运行时，ruff/mypy 红） | 属实 |
| W2C | 20 条规则注册表 / 红队 66 条 | `app/guard/rules.py` RuleDef（行 33）；`tests/redteam/test_redteam_guard.py:81` `assert len(cases)==66` | 属实 |
| W2D | executor / `$n`→`%s` 适配 / 揭盖链 | `app/exec/executor.py` 行 88（_bind_dollar_params）/123（PgSqlExecutor）/360（get_raw_connection） | 属实 |
| W2D | "ruff/mypy 红均在 W2B/W2C 在制品" | 本轮全仓 ruff/mypy 逐条归属核对（§4） | 属实 |
| W2C | "全量 3 failed 均他窗在制品"（20:5x 观察） | 本轮全量 pytest **0 failed**——三窗口已自行收口 | 已过期（向好） |

---

## 3. 收口总表

### 3.1 接线类
| # | 请求方 | 内容 | 状态 |
|---|---|---|---|
| 1 | W2A→W1B | startup_assertions 注入 validate_bundle_path | ✅ 本窗口落地 |
| 2 | W2A→W1B | readiness 注册 build_semantic_bundle_probe | ✅ 本窗口落地（ready 200 实证） |
| 3 | W2A→W1B | 迁移链纳入 0002 | ⚠️ 文件在位+本机已执行；compose/CI 无迁移步骤（W0 缺口） |
| 4 | W2D→W4 | exec/mask 装配点（PgSqlExecutor 构造 + effective_limit 必传 + 列身份掩码映射） | 待阶段 4（W4） |
| 5 | W2A→W2B | 物化侧 tokenizer 注入点 `materialize(..., tokenizer=tokenize)` | 等架构 U-54 |
| 6 | W2B→W0 | importlinter 新契约（retrieval 禁 LLM、httpx 例外） | 待 W0 落笔 .importlinter |

### 3.2 裁决类（已上呈，详见 RELAY §2；此处只列索引）
| 建议号 | 主题 | 提出方 |
|---|---|---|
| U-54 | TokenizerPort 落点（与 W2B 候选 U-58 同一件事，建议合并裁） | W2A+W2B |
| U-55 | RLS 不适用于 v_* 视图（三选一：基表 RLS / security_invoker / 放弃 DB 侧 RLS） | W2A |
| U-56 | v_* 业务视图 PG 侧 DDL 归属 | W2A |
| U-59 | CandidateRef 端口面 vs RetrievalResult 富结果旁路 | W2B |
| U-60 | embed_doc.tenant_id='*' 公共哨兵契约化 | W2B |
| U-61 | to_tsquery 需显式 `&` 的语法事实回填 07 §6.4 | W2B |
| U-62 | GuardPort 缺改写类出参通道 | W2C |
| U-63 | gate3 EXPLAIN 执行归编排层（W4 节点） | W2C |
| U-64 | 红队冻结集 vs 07 §7.2/§7.3 六处口径冲突 | W2C |

### 3.3 债务类（各窗口自留，未收口）
| 归属 | 债 |
|---|---|
| W2A | tokenizer/embedder 未注入 → tsv/embedding 全 NULL（E2E 复现：pending_tokenizer/pending_embedder）；L1 变体 patch 脚本 / L5 零分母 SKU / 4 个 `--check` 未挂 CI |
| W2B | refine.py P0 占位未实现；PgVectorStore SQL 模板 UNVERIFIED；recall=0.12/0.05 是 value+graph 两路成绩，四路齐后必重跑；dense.py F821 等 lint 债 |
| W2C | 敏感字段二次审批 P1 未实现（接口预留）；RT-LIM-003 deny/execute 互斥（并入 U-64#6）；gate3 性能未压测 |
| W2D | 列身份掩码 sensitivity 路径未接线（等 W3C/W4 装配点）；ColumnMeta.unit 恒 None；租户配额是进程内信号量 |
| W0 | compose/CI 迁移步骤；api 挂载 /semantic；deploy/.env 行内注释；4 个 `--check` 挂 CI |
| **W2-INT 本窗口** | 全仓 ruff 34 / mypy 22 红（W2B/W2C 债，逐条见 §4）——按"不直接改四窗口代码"纪律未修，回执转达 |

---

## 4. 全量门禁实测输出（2026-09-16 22:0x，commit `7a4bbce` + W2D 在制品工作区）

```
pytest -q（全量含 integration）
  → 764 passed, 8 skipped, 0 failed（60s）
  8 skips 全带理由：6 = test_retrieval_fts_pg（夹具 DSN 无 DDL 权限，需 RETRIEVAL_TEST_PG_DSN）
                   2 = test_semantic_materialization（业务视图未建，待裁决③/U-56）—— 无假绿

lint-imports（控制台脚本，非 python -m 假绿形态）
  → R-DEP-1 KEPT / R-DEP-2 KEPT / R-DEP-3 KEPT
  → Contracts: 3 kept, 0 broken.

python scripts/assert_importlinter.py
  → [probe] 三条契约注入→必红→还原→必绿全过；DoD② 通过；All checks passed!

ruff check .
  → Found 34 errors。归属：app/guard/**（W2C，8）+ app/retrieval/**（W2B，6，含 dense.py:273 F821）
    + reports/w2b/recall_report.py（W2B，4）+ tests/**（W2B/W2C 各自测试文件，15）
    + app/repo/startup_assertions.py RUF100（本窗口引入，已当场修复并复核通过）
  本窗口三文件 ruff：All checks passed!

mypy app
  → Found 22 errors in 3 files：app/guard/**（19，W2C）+ app/retrieval/dense.py:273（W2B）
  本窗口三文件：mypy app/main.py app/repo/startup_assertions.py app/api/routers/health.py
  → Success: no issues found in 3 source files
```

---

## 5. 端到端实测（`reports/w2-int/e2e_stage2_check.py`，真 lifespan + 真 PG/Redis + 真语义包）

```
Part A /healthz 三端点：
  live   : 200
  ready  : 200  checks={metadata_db:True, checkpointer:True, redis:True, semantic_bundle_loaded:True}
                bundle_version='2026.09.14.1'
  aggregate: 200 status=degraded（degraded_dependencies=['llm','embedding'] —— 软依赖如实降级）
  启动断言 4/4 PASS（analytics 只读 / 向量维度 1024==vector(1024) / audit append-only / 语义包五步校验）
  ① startup_assertions 注入生效："注入的校验器已通过（编排层已实际 await 调用）"
  ② 探针注册生效：semantic_bundle_loaded 由 503→True，bundle_version 回读真实值

Part B 六步发布演练（version=2026.09.14.1）：
  步骤①②③ materialize(with_policy=False) → doc_count=197
            rows={asset:8, metric_def:9, dimension:6, field_binding:7, join_path:10,
                  synonym:105, policy:2, default_predicate:2, embed_doc:197}
            tsv=pending_tokenizer / embedding=pending_embedder（如实降级，非通过）
  步骤②完整形态 with_policy=True → BLOCKED（预期）
            psycopg.errors.UndefinedTable: relation "v_order_paid" does not exist
            → 引用 U-55（RLS 不适用于视图）/ U-56（v_* DDL 归属未裁）；单事务整体回滚，无半态
  步骤④⑤   switch_version + get_active_version（键=cache_keys.active_version() 注入）→ 指针回读一致 [PASS]
  步骤⑥     rollback_to（目标版本存在性校验通过）[PASS]
  DoD③      assert_grant_policy_consistency → checked=8, consistent=False, 14 mismatches
            全部 = v_* 列授权缺失 + RLS 策略不存在（U-56 视图未建 + U-55 GRANT/RLS 未执行）
            —— 检查器如实报不一致（不静默），BLOCKED 状态的诚实表达
```

---

## 6. 诚实边界

1. **W2D 代码当前未提交**（untracked 在制品）——本收口基于工作区实测；W2D 提交后建议重跑全量门禁复核。
2. 全仓 ruff/mypy 红未清零（W2B/W2C 债）——收口窗口不越权修，已在 RELAY §1 逐窗口回执。
3. 六步演练的"完整形态"被 U-55/56 卡死是**结构性**的：视图不存在 + RLS 不可用于视图，写代码解决不了，必须架构裁决。
4. 本窗口唯一例外修改权（U-55 裁决后改 derive_policy_statements RLS 段）**未动用**——架构尚未裁决。
5. 阶段 3 收口窗口复用本模板时替换：包归属（W3A/W3B/W3C）、reports 目录、裁决号、迁移名（模板见 `w2-int/PROMPT.md`）。
