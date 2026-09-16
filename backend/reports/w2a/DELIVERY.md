# 阶段 2A · 语义层运行时 —— W2A 交付与交接说明

> 生成时间：2026-09-16（本机实测）｜ 归属窗口：**W2A**（`app/semantics/**` + 迁移 0002 + 随附测试）
> 交付范围：docs/08 §4.1 的 T1–T5 与 DoD ①②③
> ⚠️ 本文件是**交付说明**，不是设计文档。设计归 `docs/07`；本文只写"盘上实际是什么状态"和"下一步谁做什么"。
> 逐窗口可粘贴的转述件见 `backend/reports/w2a/RELAY.md`。

---

## 0. 结论先行

| 项 | 状态 | 一句话 |
|---|---|---|
| T1 §6.1 五步校验（loader/models） | ✅ | `load_bundle()` 五步 + Pydantic `extra="forbid"`/`frozen` 负向字段防线；真实包 43 用例全绿 |
| T2 运行时（`SemanticBundlePort` 实现 + L1/L2/L3 查询） | ✅ | `runtime.py` 全接口 + `probe.py` 探针产出；**未接线**（按约定不碰 main.py，见 RELAY §1） |
| T3 §12.2 物化表 + §6.2 发布/切换/回滚 | ✅ | 迁移 0002 **已在本地库实测执行**（0001→0002 成功，pgvector 0.8.6）；`materialize()` 实测写入 197 embed_doc |
| T4 探针 + 启动断言交付 | ✅（产出）／⏸（接线） | 接线动作按约定写进 RELAY §1，由 W1B 收集执行 |
| T5 测试（含负向） | ✅ 59 passed / 2 skipped | skip 均因**待裁决③**（业务视图未建）；DoD③ 注入对照（红→还原→绿）已落码，等视图即可跑 |
| DoD① §6.1 五步 | ✅ | 步骤③ fifteen-classes + ⑥ 类双向断言全部离线可验 |
| DoD② §6.2 单键指针原子切换 + 回滚 | ✅ | `switch_version`（一次 SET）/ `get_active_version` / `rollback_to`（目标版本存在性校验） |
| DoD③ 应用白名单 == DB 实际 GRANT/POLICY | ⚠️ **部分** | 派生函数（ADR-10 纯函数）+ 一致性检查器已落码并离线验证；**真库端到端被待裁决②③卡住**（RLS 不适用于视图 / 业务视图未建），非本窗口可解 |
| 门禁 `pytest`（W2A 范围） | ✅ **59 passed / 2 skipped / 0 failed** | |
| 门禁 `ruff` / `mypy app/semantics` | ✅ 全绿 | |
| 门禁 `lint-imports` | ✅ **3 kept / 0 broken**（用 `lint-imports` 控制台脚本跑，非 `-m` 假绿形态） | 期间抓到并修掉一处 R-DEP-1 违规（semantics→cache），见 §4.3 |

**一句话**：W2A 的代码与离线断言**全绿**；发布链路在本地库**实测走通到"步骤④"**；步骤②③（GRANT/POLICY 执行 + DoD③ 端到端）被两条**待架构裁决**卡住 —— 这两条不裁决，DoD③ 无法收口，**且这不是写代码能解决的**。

---

## 1. 交付物

### 1.1 本窗口新建

| 路径 | 内容 |
|---|---|
| `app/semantics/models.py` | SCHEMA v1.1 运行时模型：`extra="forbid"`（已删字段复活即拒绝）+ `frozen`；Dimension 粒度契约 / FieldBinding 歧义契约（`ambiguous⇔canonical_asset 为空` 双向）在**模型层**强制 |
| `app/semantics/loader.py` | `load_bundle()` §6.1 五步：重复键拒绝 / 15 类完整性 / 引用完整性（field_bindings·dimensions·joins·aliases·policies·tenant_scoped⇔tenant_id·draft 跳过·default_predicates 双向）/ 质量门（**exclude 不报错**）/ tokenizer PENDING 诚实警告；`validate_bundle_path()` 供启动断言注入 |
| `app/semantics/runtime.py` | `SemanticBundleRuntime`：实现 `SemanticBundlePort`（active_version/asset_allowlist/time_semantics/policy）+ L1 别名 / L2 数值粒度 / L3 字段绑定查询；`with_bundle()` 支持原子换包 |
| `app/semantics/probe.py` | `build_semantic_bundle_probe()`：未接线时返回 healthy=False（**诚实未接线**，不伪造 200） |
| `app/semantics/materialize.py` | §6.2 发布机器动作全集：`derive_policy_statements()`（**ADR-10 纯函数**，revoke→grant→RLS→policy 顺序固定）/ `materialize()`（单事务，步骤①②③）/ `switch_version()`/`get_active_version()`/`rollback_to()`（步骤⑤⑥）/ `assert_grant_policy_consistency()`（DoD③ 双向比对） |
| `app/repo/migrations/versions/0002_semantic_materialization.py` | pgvector 扩展 + 9 张物化表（§12.2）+ embed_doc `vector(1024)` HNSW/GIN 双索引 + **逐表 GRANT**（不用 `ON ALL TABLES`，避免重授 audit_log 写权限破坏 0001 append-only） |
| `tests/unit/test_semantics_loader.py` | 43 用例：真实包正向 ×12 / 坏包负向 ×20 / 运行时 ×13 |
| `tests/unit/test_materialize_derivation.py` | 12 用例：派生确定性 / CLS 仅白名单列 / revoke 先于 grant / tenant_id 永不授权 / RLS 仅 tenant_scoped（6 条策略）/ GUC 失败关闭 / shop_ids 空串语义 / embed_doc 组装对账 / `content_sha256` 稳定 / 标识符转义 |
| `tests/integration/test_semantic_materialization.py` | 6 用例：真库物化 + 幂等重跑 + DoD③ + **注入对照**（REVOKE→必红→重物化还原→必绿）+ 指针切换/回滚；无库/无迁移/无视图按**具体理由** skip |
| `reports/w2a/DELIVERY.md` `RELAY.md` | 本文件 + 逐窗口转述件 |

### 1.2 本地库状态变更（**披露**）

本窗口在**本地开发库**（compose 映射的 5432 实例）执行了 `alembic upgrade head`：**0001 → 0002 成功**。影响 = 新增 pgvector 扩展 + 9 张表 + 逐表 GRANT；**未触碰** 0001 的任何对象与 `alembic_version` 之外的数据。并行窗口（W1B 的 audit 集成测试）不受影响且实测仍可跑。

---

## 2. 验证记录（全部本机实测，时间 2026-09-16 晚）

```
pytest tests/unit/test_semantics_loader.py tests/unit/test_materialize_derivation.py
  → 55 passed
pytest tests/integration/test_semantic_materialization.py
  → 3 passed / 2 skipped（skip 理由 = 业务视图未建，待裁决③）/ 1 failed→已修（见 §4.2）
ruff check app/semantics tests/unit/test_semantics_loader.py tests/unit/test_materialize_derivation.py
  tests/integration/test_semantic_materialization.py  → All checks passed!
mypy app/semantics  → Success: no issues found in 6 source files
lint-imports        → Contracts: 3 kept, 0 broken
alembic upgrade head（MIGRATION_DATABASE_URL 指向本地属主）→ 0001 → 0002 成功
materialize(真实包, dsn=app_rw, with_policy=False) → asset=8 / metric_def=9 / dimension=6
  / synonym=105 / embed_doc=197（=资产 8 + 列 75 + 指标 9 + 别名 105）；tsv_status=pending_tokenizer
  embedding_status=pending_embedder（诚实降级，未注入即如实 PENDING）
rollback_to / switch_version / get_active_version → stub Redis 语义 + 真库存在性校验实测通过
```

⚠️ **注意范围**：本机全量 `pytest tests/unit` 当前会因**其他并行窗口的在制品**（`app/exec/errors.py` 的 IndentationError 归 W2D；`test_retrieval_tokenizer.py` 的 ruff 项归 W2B）收集失败 —— 非本窗口产物，W2A 未触碰。

---

## 3. 与 07 §12.2 的 2 处偏差（有意，均已注释在迁移文件内）

| # | 偏差 | 理由 |
|---|---|---|
| 1 | `field_binding` 主键 = `(bundle_version, concept)` 而非 §12.2 的单列 | SCHEMA v1.1 中 field_bindings 无独立 id 键；单列键无法表达"同 concept 多版本" |
| 2 | `default_predicate.predicates` 用 jsonb 数组而非逐谓词一行 | 谓词条目（id/predicate/reason/owner）是**一个不可分组的声明单元**，拆行反而引入行序语义；查询侧按 domain 整包读 |

---

## 4. 诚实边界（**不得当作已完成**）

### 4.1 PENDING 项（如实降级，非通过）
- `tokenizer=None` → `synonym.tsv` 全 NULL + `pending_tokenizer`（N-24：写入侧与查询侧必须同源，**等 W2B 交付后注入**，W2A 不私自 `import jieba` 制造第二入口）。
- `embedder=None` → `embed_doc.embedding` 全 NULL + `pending_embedder`；向量列与 HNSW 索引**已建**（空列可建索引，回填自动生效），等 W2B/W7 的 embedding 客户端。
- `semantic_bundle.status='candidate'`：本地包未走发布流程，`validate_bundle_path` 会按配置放行 candidate（非 prod）；**正式发布需跑 `materialize(with_policy=True)` 全六步** —— 目前只走到步骤④。

### 4.2 测试侧
- 集成 2 条 skip 原因是**待裁决③**（业务视图 PG 侧 DDL 没人建）。skip 里写明了缺失前置，**不是假绿**；但 DoD③ 的端到端（含注入对照）在裁决前**持续无法运行** —— 这是本窗口最想上报的风险。
- 修复过程披露：集成首跑红过 2 次（embed_doc 数我猜错 122 vs 实际 197；`emb_status` 字段名猜错，实为 `embedding_status`）——两次都是**测试断言前提没验证**，不是产品码缺陷；已按"先实测再断言"修正。

### 4.3 期间发现并修复的自身违规
`materialize.py` 初版直接 `from app.cache import keys` → `lint-imports` 抓到 R-DEP-1（semantics→cache 禁止）。已修：**Redis 键名改为调用方注入**（`switch_version(redis, version, *, key=cache_keys.active_version())`）——键定义仍是 W0 的单一真相，semantics 不持有第二份。这验证了依赖护栏真的在拦人。

---

## 5. 待架构裁决（**本窗口未开 U 号 —— 按编号纪律列"待分配"，建议从 U-54 起**）

| 建议号 | 问题 | 为什么卡住 W2A/W2B |
|---|---|---|
| **U-54（待分配）** | **TokenizerPort 落点冲突**：`core/contracts.py` 把 tokenizer 定义在 L0/L1（contracts），docs/08 把实现放在 `retrieval/tokenizer.py`（L3 归 W2B），而 §6.2 要求物化 tsv 的**写入侧**（W2A，L1）与查询侧**同源**。若只能 import L3，W2A 就违反分层（本次 R-DEP-1 修法同款：键/函数由调用方注入）。**需要一句裁定**：tokenizer 以"依赖注入 + 契约在 contracts"为准，还是允许 L1 import L3 唯一入口。 | 不裁定 → W2B 交付的 tokenizer 无法合入物化侧，稀疏检索永远 PENDING |
| **U-55（待分配）** | **RLS 落点缺口**：§13.3 模板对 `v_*` 视图执行 `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`，但 **PG 的 RLS 只适用于表，不适用于视图**（实测 `psycopg.errors.WrongObjectType`）。可选解：(a) RLS 落到物化基表/中台表，视图透传；(b) 视图改 `security_invoker` + 基表 RLS；(c) 放弃 DB 侧 RLS，租户谓词全部走执行层 SQL 注入（现评测口径即如此）。**三种的安全语义与审计面不同，必须架构拍板**。 | `materialize(with_policy=True)` 在第一条 RLS 语句必炸 → 步骤②③无法完成 → DoD③ 无法收口 |
| **U-56（待分配）** | **业务视图 `v_*` 的 PG 侧 DDL 归属**：语义包声明了 8 个 `v_*` 资产，但库里不存在（数据在 SQLite 沙箱 → 附录 D 部署形态里由谁建视图？）。归属不明 → 07 的"v_* 视图"模板整节无法落地。 | 同上；且 `assert_grant_policy_consistency` 无对象可比 |

> 提交说明：以上三条均已写进 RELAY §5（→ 架构窗口），W2A 不擅自选 (a)(b)(c) 任何一条落码。

---

## 6. 下一步（谁做什么）

1. **W1B**（收集 RELAY §1 后）：`startup_assertions` 注入 `validate_bundle_path`；probe 表注册 `semantic_bundle_loaded`；CI/部署侧把 0002 纳入迁移链。
2. **W2B**：交付 `retrieval/tokenizer.py` 后，物化侧注入点 = `materialize(..., tokenizer=tokenize)`（签名已留好）；等 U-54 裁决定接线形态。
3. **架构窗口**：裁 U-54/U-55/U-56（RELAY §5 有逐条选项与后果）。
4. **W7**：embedding 客户端就绪后回填 embedding（索引已建，直接可查）；§6.2 步骤⑥的"旧版本 7 天清理 job"。
5. **下一窗口的开工提示词**：见 `reports/w2a/RELAY.md` §6（按用户约定，提示词已写入该文件，可直接复制开新窗口）。
