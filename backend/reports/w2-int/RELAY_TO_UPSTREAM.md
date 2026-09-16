# W2-INT → 上游转述件（统一版，供用户代为转述）

> 生成：2026-09-16 22:2x ｜ 更新：23:1x（架构 9 条已裁定 → §2 状态更新；新增 W0 回复与 W2A/W2B 分派）
> 来源：W2-INT 收口窗口（commit `f351ada` + `167295b` + `3fc1790`）
> 用法：每个【】块就是一条完整消息，直接复制给对应窗口即可，互相无依赖。
> 证据细节都在 `backend/reports/w2-int/DELIVERY.md`（§4 门禁 / §5 端到端 / §6 U-55 授权改动 / §7 CI 分派），收件窗口可自行查。

---

## 【给架构窗口】阶段 2 收口 · 裁决请求汇总（9 条）

> ✅ **状态更新（2026-09-16 23:1x）**：架构窗口已将 9 条全部裁定并落 **07 v0.9**（§4.8 登记表 + §13.3 RLS 模板重写 + §7.2/§7.3 口径更正）。W2-INT 已按 U-55 (a) 完成授权范围内的 `derive_policy_statements` 修改（含注入对照与全量门禁复核，见 DELIVERY §6）。**本节保留作归档**，以下为原始请求内容。

> 阶段 2 四窗口（W2A 语义层 / W2B 检索 / W2C 闸门 / W2D 执行脱敏）已全部交付并经收口窗口核验接线。以下 9 条裁决请求已去重合并（编号占用现状：U-01~53 已用；下一可用号 = **U-65**；终局以 07 §4.8 登记为准）。
>
> | 建议号 | 主题 | 选项摘要 | 影响面 |
> |---|---|---|---|
> | U-54 | TokenizerPort 落点冲突（= W2B 候选 U-58，同一件事，建议合并裁） | (a) 契约留 contracts、实例由装配根注入物化+检索两侧（W2A/W2B 均倾向）；(b) tokenizer 移到 L1 | W2A / W2B / W0 |
> | U-55 | **RLS 不适用于 PG 视图**（实测 `WrongObjectType`） | (a) RLS 落基表、视图透传；(b) `security_invoker` 视图 + 基表 RLS；(c) 放弃 DB 侧 RLS，租户谓词全走执行层注入 | W2A / W4 / W6（三者的越权防线与审计面不同） |
> | U-56 | v_* 业务视图的 PG 侧 DDL 归属（compose init / 迁移 / 数据窗口，谁建？） | 8 个 v_* 资产库里不存在 → GRANT 与一致性检查无对象可比 | W2A / W0 |
> | U-59 | `CandidateRef` 端口装不下列级富结果 | 端口面升级 vs 维持 `search_full()` 富结果旁路 | W0 / W3B / W3C |
> | U-60 | `embed_doc.tenant_id='*'` 公共哨兵未契约化 | 07 §12.2 回填 | W2A / W2B |
> | U-61 | `to_tsquery` 需显式 `&` 连接（空格形态 = syntax error，实测） | 07 §6.4 举例若有空格形态请更正 | 架构 |
> | U-62 | `GuardPort` 缺"改写类"出参通道（rewritten_sql / limit_injected / applied_predicates） | (a) W4 直接调 `run_gate1` 模块函数；(b) 扩 GuardPort（W0 落笔） | W0 / W4 |
> | U-63 | gate3 的 EXPLAIN 执行归属 | 确认"W4 的 gate3_cost 节点跑 EXPLAIN 并传计划 JSON"为正式契约 | W4 |
> | U-64 | 红队冻结集与 07 §7.2/§7.3 六处口径冲突（LIMIT ALL / SET 消歧×2 / CROSS JOIN 归因 / R14 vs R17 / RT-LIM-003 deny-execute 互斥） | 红队集是 DoD① 判定基准且已冻结，W2C 按冻结集执行；裁定反向则改动集中在 ast_gate.py | W1A / W4 / W6 |
>
> **阻塞提醒**：U-55 + U-56 不裁决，`materialize(with_policy=True)` 永远 BLOCKED（收口窗口已实测：`UndefinedTable: relation "v_order_paid" does not exist`，单事务回滚无半态），DoD③ 端到端无法收口，语义包无法从 candidate 转正式发布。**这不是写代码能解决的，必须先拍板。**

---

## 【给 W0 · 回复】CI 分派：选 (a)，(b) 列为后续增强

> 收口窗口决定：**选 (a)**——W2A/W2B 各自为其集成测试补"连不上 → skip（写明理由）"分支（范本 = `tests/integration/test_real_redis_lock_and_ratelimit.py:454`），分派消息已发（见下两节）。
> **(b) 不否决**：(a) 与 (b) 完全兼容——CI 加了 PG service 后连接可达，skip 分支自然不触发、integration 真跑；连接不可达时诚实 skip。若你愿意加（pgvector 镜像 + 跑迁移 0001/0002 + 注入 `RETRIEVAL_TEST_PG_DSN` 等环境变量），**窗口侧零额外改动**即可受益，建议作为后续增强排期。
> 另收到：R-DEP-4（retrieval 禁 LLM）已在本机 lint-imports 实测生效（Contracts: 4 kept），多谢落笔。§前一条消息里的 3 条部署缺口（迁移步骤 / semantic 挂载 / .env 行内注释）仍待你处理。

---

## 【给 W2A · 分派】test_semantic_materialization.py ×2：补"连不上 → skip"分支

> W0 在 CI（afaia31c，早于 c02f97a 同红）定位：你的 `tests/integration/test_semantic_materialization.py` 2 条用例在**无 PG 的 CI 环境**连接拒绝时直接 fail 而不是如实 skip（本地 8 skipped 走的是"权限不足/视图未建"分支，所以看不到这条红）。
> **请补"连接不可达 → skip（写明理由）"分支**，范本 = `tests/integration/test_real_redis_lock_and_ratelimit.py:454`（W0 指定）。注意 skip 理由要区分：连不上（部署前置缺失）≠ 视图未建（U-56 实施中）≠ 无 DDL 权限。
> 配套告知：架构已裁 U-55 = (a)（RLS 落基表）、U-56 = W1B alembic 迁移建视图+基表；收口窗口已按授权把 `derive_policy_statements` 的 RLS/POLICY 段改为基表目标（策略名 `p_{基表}_tenant`），你的 `test_materialize_derivation.py` 有 4 条断言随之更新并过注入对照（改动记录 = `reports/w2-int/DELIVERY.md §6`）——请知悉并复核。

---

## 【给 W2B · 分派】test_retrieval_fts_pg.py ×6：补"连不上 → skip"分支

> W0 在 CI（afaa31c，早于 c02f97a 同红）定位：你的 `tests/integration/test_retrieval_fts_pg.py` 6 条用例在**无 PG 的 CI 环境**连接拒绝时直接 fail 而不是如实 skip（本地走的是"夹具 DSN 无 DDL 权限"分支）。
> **请补"连接不可达 → skip（写明理由）"分支**，范本 = `tests/integration/test_real_redis_lock_and_ratelimit.py:454`（W0 指定）。skip 理由区分：连不上（部署前置缺失）≠ 无 DDL 权限。
> 配套告知：架构已裁 U-54 = (a)（契约在 contracts、装配根注入两侧同实例）、U-59 = (a) **升级 RetrievalPort 端口面**（富结果进契约，**search_full() 旁路被否决**，W0 落笔 contracts.py）、U-60/U-61 已契约化进 07——你的 `search_full` 旁路后续要按新端口面收敛，请在阶段 3 排期时留意。

---

## 【给 W0】部署面缺口 3 条 + 2 条待办

> 阶段 2 收口发现以下缺口，均在你归属内（deploy/** / .github/** / .importlinter），收口窗口未越权修改：
>
> 1. **迁移链无机器保证**：`deploy/docker-compose.yml` 与 `.github/workflows/ci.yml` 均无 alembic 执行步骤，迁移目前靠手动 `alembic upgrade head`。0002 已在 `backend/app/repo/migrations/versions/` 会被自动纳入，但 07 §18.2"迁移先于 api"没有机器保证 → 建议在 compose 加 migrate 步骤或 CI 加迁移 job。
> 2. **api 容器缺语义包挂载**：api 服务未挂载 `../semantic` → 容器内 `/semantic/bundle_2026.09.14.1.yaml` 永远不存在，语义包加载必失败、readiness 持续 503（本机验证是用环境变量覆盖宿主路径跑通的）。
> 3. **deploy/.env 有行内注释**：`KEY=value  # 注释` 形态在 pydantic-settings 下会把注释并进值（实测 Settings 校验 15 项报错）；compose env_file 语义也存疑 → 建议 .env 去注释、说明挪 `#` 注释行。
> 4. （W2B 提案）`.importlinter` 增补契约：retrieval 禁 LLM（refine 除外，P0 未实现），httpx 例外属 embedding 网关——原文见 `backend/reports/w2b/RELAY.md §2 Q4`。
> 5. （W1A/W2B 遗留）4 个 `--check`（含 importlinter）尚未挂 CI。

---

## 【给 W2B】lint 债回执（不阻断，但 CI 先行会挂）

> 收口窗口全仓门禁结果：`ruff check .` 34 条中 **15 条在你窗口**（app/retrieval 6 条含 `dense.py:273 F821 Mapping 未导入`——W2D 转达属实，`__future__ annotations` 下不炸运行时但 ruff/mypy 必红；reports/w2b/recall_report.py 4 条；你的测试文件若干）；`mypy app` 22 条中 1 条在 dense.py。逐条清单见 `backend/reports/w2-int/DELIVERY.md §4`，请自行收口。另：全量 pytest 你的范围 0 failed（dense 断言债已解）；你的 U-59/60/61 已合并上呈架构。

---

## 【给 W2C】lint/类型债回执

> 收口窗口全仓门禁结果：`ruff` 34 条中 **8 条在 app/guard/**（UP035×4 / RUF034×2 / UP037 / RUF100）；`mypy` 22 条中 **19 条在 guard**（ast_gate 15 / cost_gate 4）。全部为 lint/类型级、行为未动，清单见 `backend/reports/w2-int/DELIVERY.md §4`。你的 U-62/63/64 已合并上呈架构（与 W2A 的 U-54~56 无撞号）。

---

## 【给 W2A】接线确认（告知性质，无需动作）

> 你的 RELAY §1 三项接线已由收口窗口落地并实测：启动断言注入（实测 PASS）、readiness 探针（**/healthz/ready 实测 200**，`bundle_version=2026.09.14.1`）、迁移链核验（compose/CI 缺口归 W0）。六步演练：materialize 197 docs 复现、指针切换/回滚 PASS；`with_policy=True` 如预期 BLOCKED（U-55/56）。tokenizer 注入点（`materialize(..., tokenizer=...)`）等 U-54 裁决后接。

---

## 【给 W2D】交付确认 + 提交提醒

> ① 你的 91 条测试全量复跑通过；全仓 ruff/mypy 归属核对与你 DELIVERY §5 的判断一致（0 条归你）。② **你的代码当前 untracked 未提交**——收口基于工作区实测（结论有效），提交后请通知收口窗口重跑门禁复核一次。③ 你给 W4 的装配说明已列入阶段 4 移交清单。
