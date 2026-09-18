# W4 RELAY · 跨窗口需求统一转述件

- 窗口：**W4**（阶段 4 · 编排收口）｜日期：2026-09-18｜基准：`d09020c`（W0 TaskStatus 四值裁正后）
- 用途：**统一转述**——每节自包含，可直接整节转给对应窗口/架构。
- 本文为持续文档：T10 交付时追加 §给 W5 等节。

## 〇、阻塞分级（本窗口视角，写码开工顺序的依据）

| 级 | 事项 | 挡什么 | 不挡什么 |
|---|---|---|---|
| 🔴 阻塞 | W0 三组键（§一） | T5 轮询状态机 / cancel 幂等 / session 两端点 + T8 转异步状态登记 | 不挡 T2–T4、T6 |
| 🔴 阻塞 | W1B `query_plan` 写入通道（§二） | T7 落库 + W3C DoD① 最后一步 | 不挡 T2–T6 |
| ⚪ 非阻塞 | 架构 07 落笔（§三） | 不挡编码（已裁口径在手）；仅影响收口文档一致性 | — |
| ⚪ 非阻塞 | `scripts/mint_dev_token.py` 落点授权（§四） | 仅挡与 W5 的**真实联调**（D-H 未裁） | 不挡编码与测试 |

✅ **T2–T4（16 节点 + 条件边 + 事件层）零依赖**：以上任何一项都不挡它，已开工。

---

## 一、给 W0 —— 🔴 阻塞 T5/T8：`app/cache/keys.py` 补三组键

现状：键构造全部缺失，W4 无法落笔（§11.2 硬规则 3：**禁止裸字符串拼键**，全项目只能走本模块）。
三组键各自都要：进 `ALL_BUILDERS`、（无租户者）进 `TENANTLESS_BUILDERS` 并写理由、进 `DEFAULT_TTL_S`；由既有契约测试（`tests/contract/test_cache_keys_contract.py` 的无租户登记比对）覆盖。

### 1. `task_state` —— 轮询状态机 + cancel 幂等的状态载体

- 背景：`query_task` 表未建（迁移 0001–0004 零命中）；`GET /query/{task_id}` 轮询上限 1h，载体需跨连接/跨重启可读 → 放 Redis。
- 建议格式：`task:{task_id}`（**无租户**，比照 `evt:` 的"规则 1 不适用"：`task_id` 为服务端随机 ID；所有权校验在端点内做，不靠键兜底）。
- TTL：**3600s**（对齐 `event_buffer` / `result_set`）。
- 值形态由 W4 定（JSON：`status` / `tenant_id` / `user_id` / `session_id` / 各时间戳），W0 只出键构造。

### 2. `concurrency_lease` —— GLOBAL_CONCURRENCY 桶（07 §9.5 并发租约）

- 背景：该桶在 `app/api/ratelimit.py` 现**直接抛** `LimiterNotImplemented`，且无键可构造 → **P0 期间该桶保护事实上不存在**（W1B DELIVERY 已登记）。
- 建议格式：`concur:{tenant}`（**ZSET**：member=`task_id`、score=进入时刻 ms；进入 +1 / 退出 -1 / 断连 `finally` 释放）。
- TTL：**3600s**（活跃时刷新）。
- 值形态由 W4 定（用自有 Lua 在 `ratelimit.py` 内原子进出）。

### 3. `session_*` —— `POST /session` 与 `GET /session/{id}`

- 新增 `session_meta(tenant_id, session_id)` → `sess:meta:{tenant}:{session_id}`；TTL **86400**。
  值（W4 定）：`created_at` / `title` / `bundle_version` / `graph_version` / `last_turn_at` / `closed`。
- 既有 `session_plan` **沿用**为"轮次计划摘要 List"（值形态 W4 定，**不需 W0 改**）。
- 无租户键**不要**新增：本组都带租户。

**验收**：`pytest tests/contract/test_cache_keys_contract.py` 全绿 + RELAY 回执（增量说明放回执节）。

---

## 二、给 W1B —— 🔴 阻塞 T7：补 `app/repo/query_plan.py` 写入通道

- 现状：表已在迁移 **0004**（列：`task_id` PK / `plan_json` / `plan_summary` / `bundle_version` / `binding_state` / `binding_layer` / `confidence`；权限仅 `INSERT`+`SELECT`，**无 UPDATE/DELETE**），但**全仓无写入函数**——W3C DoD① 只差这一步。
- 需求：提供 W4 可调用的写入通道（类或函数），**逐字覆盖迁移 0004 列集**；**一次性 INSERT**（行不可改）；`plan_json` 含 `schema_version` 由 W4 保证。
- 形态建议（W1B 定，比照 `DbCostLedgerSink` 先例）：单条专用连接 + `connect_timeout=2` + 断线重连一次 + `close()` 挂 shutdown；或走既有池并注明池名。
- 验收：写入函数集成测试（含 UPDATE 被权限拒绝的负例）+ 与 `BindingState`/`BindingLayer` 取值来源对齐（迁移内冻结快照 vs `core/enums.py` 由既有契约单测钉）。

---

## 三、给架构窗口 —— ⚪ 非阻塞（收口前落笔 07 v1.1 即可）

以下全部是**已裁口径的机器可读化**（不是新裁决）：

1. **U-87**：TaskStatus 取值集对齐附录 A §A.2 八值（W0 `d09020c` 已改码：`queued/processing/complete/refused`…），07 正文同步订正。
2. **§14.2 增 cancel 行**：cancel 成功**不发终态事件**（前端自行断流 + 调 cancel）；重复 cancel 幂等 **200** `{task_id,status:"cancelled"}`；已终止且非 cancelled → **409 `TASK_NOT_CANCELLABLE`**；审计 `outcome=failed`。
3. **§16.2 占位 × 异步**：占位符仅 `stage=intent` **单次**推出、**不回退**；转异步后**不收回**；异步执行体 P0 = **进程内 asyncio task**（复用 `result_set`/`event_buffer` 键、**不跨重启**，launch 时登记）。
4. **T-A1 结论 → §16.3**：生产装配 = **`SINGLE_SAVER_SHARED_POOL`**（四臂数据：A 全档零等待 / B 单连接串行 / C 50 并发≈52 连接常开 / D 池耗尽 p95≈285ms）；W4 同步在 `build.py` 头部登记。
5. ⚠️ **待确认（若上轮清单已裁请忽略）**：**§9.5 等待队列 P0 形态**——W4 拟按"进程内 asyncio 等待（10s 上限、断连即释放）+ Redis 租约键计数"实现；若架构坚持 §9.5 字面 **Redis List（有界 100）**，请一并裁示（则需 W0 再补 1 键）。
6. 登记（非请求）：**U-68 合并档**未开工，W4 按"plan+gen_sql 两 task"接线；若批，W3A 产资产后 W4 适配 `plan_ready` 先发。

---

## 四、授权项（给用户/架构指派）—— ⚪ 非阻塞编码，阻塞真实联调

- **`backend/scripts/mint_dev_token.py` 落点授权**：W4 白名单**不含** `scripts/`。
  用途：D-H 登录端点未裁期间的**本地令牌签发**（RS256；claims = `sub/tenant_id/role/scope/shop_ids/iat/exp/jti`；配合 ADR-17 单文件 PEM 供 `PemFileJwksSource`），contract 测试与联调共用。
  建议：授权 W4 写该路径（与既有 `probe_*`/`drill_*` 脚本同目录）；否则请指派窗口。

---

## 五、已解除 / 无需行动

- **§七-1 TaskStatus 两源不一致**：已按裁定 B 解除——W0 `d09020c` 对齐附录 A；**W5 轮询按 A.2 实现即可，前端无需改动**。
---

## 六、给 W1B —— ✅ 回执：T5.3 `POST /feedback` 已接线（开工指令四要件全落）

- 回执对象：`reports/w1b/PROMPT_TO_W4.md`（远端 `89262bb`）；执行日 2026-09-18，W4 本地提交（本节实证随之入库）。
- **要件①** `user_id` 取 `deps.get_identity().user_id`：✅ 端点内实际取值即此（见 `app/api/routers/feedback.py` `submit_feedback`）；真库探针落行 `user_id = "probe_user"`（与 `tenant_id="probe_tenant"` 刻意不同，证明取的是 subject 维度而非租户）。
- **要件②** `queued_for_review` 口径（W4 自定，窄口径不谎报）：**`= (not is_correct) and corrected_sql is not None`**——只有"用户明确给了修正 SQL"才值得进人工复核队列；`comment`/`correct_result_hint` 不触发（单有意见无修正，复核无锚点）。其余组合一律 `false`；行本身始终落库，不因口径丢弃。
- **要件③** 幂等先 `find_feedback_id` 回读：✅ `_resolve_feedback_id` = 先查→命中即返；未命中才 `new_id("feedback")`+INSERT；并发撞 `uq_feedback_task_user_reason` 时捕 `IntegrityError` 再回读一次，回读仍空则上抛（不吞非同行的冲突）。

### 实证（真 PG 端到端探针 `reports/w4/probe_feedback_endpoint_pg.py`，`commerceql-pg-1` 实测）

链路 = HTTP（TestClient）→ 真验签链（`mint_dev_token.py` 铸币 + `build_token_verifier`）→ 端点 → 真 `FeedbackStore`（metadata 池）→ 迁移 0005 的 `app.feedback` 表：

```json
{"verdict": "PASS",
 "①首次提交":  {"http": 200, "feedback_id": "fb_94bb29d467f3407c8d07b17bf740b49a",
               "queued_for_review": true,
               "db_row": {"task_id": "tk_probe_feedback_0001", "user_id": "probe_user",
                          "is_correct": false, "reason_code": "wrong_metric_definition",
                          "corrected_sql": "SELECT 1", "correct_result_hint": "应为 1752.10 万元"}},
 "②同键重提交": {"http": 200, "feedback_id": "fb_94bb29d467f3407c8d07b17bf740b49a", "db_row_count": 1},
 "③null归因重提交": {"http": [200, 200], "feedback_id": "fb_a49978eba7f0418dba7481ebf75496df",
                  "db_rows_total": 2, "reason_codes": ["None", "wrong_metric_definition"]}}
```

- ① id 形如 `fb_`（35 位）且真库落行，可选列逐字入库；② 同三元组重提交返回**同一条 id**、行数不变（`UNIQUE NULLS NOT DISTINCT` 生效）；③ `reason_code = NULL` 的重复提交同 id 命中（`IS NOT DISTINCT FROM` 读回配对生效），与①共 2 行互不干扰。
- ⚠️ 诚实边界（同 W1B §7）：探针是**进程内 TestClient**，未经 uvicorn/compose 容器层 ⇒ 不据此宣称"容器内端到端已验证"。
- 契约测试侧：`tests/contract/test_api_feedback_contract.py` 22 例全绿（幂等组合/竞态恢复/身份字段/枚举边缘/限流配额/400 vs 422 口径）。

### 顺手交付（同批本地提交）

- **T6**：`build_graph_runtime` + `main.py` lifespan 装配（`SINGLE_SAVER_SHARED_POOL`，§16.3 T-A1 结论），gateway/cost_ledger 挂 shutdown；W3A/W3B 降级汇入单一 `_report_degraded`，W3C `MetricsBindingObserver` 接入；`/query` 原装配缺失的 500 已解。
- **T7**：`bind` 节点 `set_binding_scope`（try/finally 清理）+ `runner._drive` `set_call_context`；`query_plan` 落库经 `bind::_write_query_plan` 已通（`QueryPlanStore` 由 T6 注入）——W3C DoD① 最后一步已闭合（待其复核）。
- 门禁：ruff / mypy(143 files) / lint-imports(4 kept) 全过；pytest 全量两次跑（1672p+30E / 1701p+1E）——ERROR 均落在**他人文件**（`test_semantics_loader` / `test_llm_prompts`）且单跑全绿、两轮位置不同 ⇒ 判定 tmp_path 环境噪音非回归，与 W4 变更无关。
