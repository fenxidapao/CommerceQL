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

---

## 七、T8 韧性交付（本窗口，随下次提交入库）

四子项对照 HANDOFF §五已裁口径：

| 子项 | 落点 | 状态 |
|---|---|---|
| 每节点超时 | `graph/build.py`：`_with_node_timeout`（`asyncio.timeout` 包装）+ 超时出路表（`_timeout_fallback`）；硬超时口径已按 **U-107** 收口订正（6 LLM 节点→客户端超时、9 固定节点→`NODE_TIMEOUT_S`），见 §十 | ✅（本行口径已被 §十订正）|
| 两段审计 | T2–T4 已接线（`audit_pre` fail-closed / `audit_supp` 非阻断 / 取消路径补写）| ✅ 复核无缺口 |
| 会话级版本固定 | `state_store.touch_session`：**旧值优先**（N-23 不漂移）+ `graph_version` 落键 | ✅ 写侧；读侧缺口维持登记 |
| §16.2 占位先推 | `runner._pump`：1.6s 无任何 stage 帧 → 单次推 `stage=intent` 占位；`events.EventRecorder.stage_placeholder` | ✅ |

- **超时转移口径**：~~仅 `present` 超时降级、其余 re-raise~~ —— **已被 U-107 收口订正**（旧口径 = N-21「软依赖失败必须 200+degraded」的反向实现，上游一慢就 `error(INTERNAL)`→`ok=0`，W7 实测 145 条 http_5xx 全 INTERNAL）。新口径：逐节点复用 §5.3「失败转移」列（LLM 节点→降级链、gate1/2/3→各自 GATE_* 码或跳过并标注、execute→EXEC_TIMEOUT、present→table_only；mask/audit_pre/audit_supp 具名 re-raise），详见 §十。`overrides` 参数仅供测试放大/缩小闸门值。
- **占位实现要点**：判定阈值 = **1.6s**（U-66 订正，非旧值 1.2s）；占位**必须参与 tick 周期计算**——否则 `wait_for` 等到下一次心跳（15s）才轮到判定，NFR-1.2 在生产路径上失效（契约测试以 0.05s/10s 极端比例实抓此缺陷）；占位载荷只有 `elapsed_ms`（不发结论）；真值先到不覆盖；图已结束不发。
- **口径订正**：`test_api_runner_contract.py::test_session_title_is_written_once` 旧断言"版本要更新"与 07 §5.7 / N-23 冲突，已改为"固定不漂移 + `graph_version` 落键"（T8 依据，注释已注明）。
- **诚实边界**：会话级固定的**图内读侧**（把 pinned 版本注回 `RunContext.bundle_version`）仍缺 `RepositoryPort` 通道（`trusted_context` 原登记维持）——写侧固定后，`GET /session/{id}` 可对账，但图内本轮仍取激活版本。
- 新契约测试：`tests/contract/test_graph_timeout_contract.py`（9 固定节点表值逐字 / 6 LLM 节点路由到客户端超时 / 逐节点超时出路表 / fail-closed re-raise / overrides / 客户端超时解析）+ `tests/contract/test_sse_placeholder_contract.py`（阈值 1.6 / 单次 / 不发结论 / 不回退 / 不覆盖）。

---

## 八、T9 测试批次 ①：§14.3 八条逐条 + 决策表 A 组 + fail-closed 缺口修复

- **§14.3 八条逐条**：新 `tests/contract/test_spec143_sequence_contract.py`（12 例）——① 终态唯一（转录级）② 三者互斥（转录对照 + 守卫机制面）③ 终态最后 ④ degraded 前置（recorder 级）⑤ refuse 无 data / error 前可有 data ⑥ DATA 发射点唯一 + fail-closed ⑦ meta 必含 scope/retrieval_mode ⑧ stage 恰 6 值。
- **🔴 顺手抓到并修复一个真缺口**（`graph/events.py`）：`audit_pre` **fail-closed**（段 1 写库失败 → 节点返回 terminal=error 增量）时，`emissions_for_node` 的 AUDIT_PRE 分支**仍无条件发 `data` 帧**——前端会收到"空表格 + error"组合，违反约束 6 的 fail-closed 本意（原注释写了"不走到这里"但代码没拦）。修复 = 分支在 `update.terminal` 非空时返回 `()`；终态 error 帧仍由 `error_out` 经 `terminal_target` 正常收口。
- **决策表 A 组 6 行全绿**：新 `tests/contract/test_decision_table_contract.py`（真图 + 脚本 planner 转录级）——A1 时间不可解析→clarify(time_ambiguous)、A2 意图澄清、A3 open_analysis→refuse、A4 no_data_asset、A5 out_of_scope、A6 pii_blocked；行级断言 = 事件/reason/terminal/status 投影/审计段 1 落行/refuse 无 data。
  - 登记差异：A2 的 07 字面 `reason=ambiguity`，实现走时间澄清分支（`time_ambiguous`，`clarify_out` 已登记 reason 无枚举）——断言按实现事实写。
  - **H 组映射已由 W0 钉死**（`test_contract_counts.py` 41 项：HTTP status 全覆盖 / Retry-After 只对 ✅ / 值具体 / ⭕ suggestions / INTERNAL 迁 ⭕）——T9 不重复建。
- **进度（不谎报全绿）**：B–G 组（约 34 行）待下一批——B 组需要 `deps.retrieval.search_full` 全脚本、C–E 组需要 plan/executor 全链脚本（当前图测试只走早退路径，`executor/mask` 是"未预期调用当场炸"占位）。graph_snapshot（`test_graph_wiring.py`）与 redteam 骨架（`test_redteam_guard.py`）已在位。
- 门禁：ruff / mypy(143) / lint-imports(4 kept) 全过。

---

## 九、T9 批次②（决策表 B–G 组）：全链图级测试 + 差异/修复登记

- **产出**：`tests/contract/_fullchain_deps.py`（全链脚本 deps 夹具库，接口逐字对齐节点调用面）＋ `test_decision_table_b_c.py`（B/C）＋ `test_decision_table_d_e.py`（D/E）＋ `test_decision_table_f_g.py`（F/G）。断言模板沿 A 组（`terminal_frames` 恰 1 终态 + `outcome.status` + 审计落行）。
- **本批实测**：`tests/contract` 目录 **380 passed**（含全部新文件）；全量门禁见 `DELIVERY.md §3`。

### 9.1 生产真缺口（T9 实测抓到，已修）

| # | 缺口 | 修复 |
|---|---|---|
| **U-88** | **出口帧 `reason`/`code` 丢失**：LangGraph `stream_mode="updates"` 只放行 `GraphState` schema 键，`refuse_out`/`error_out` 往增量顶层写的 `reason`/`code` 在到达 `events.emissions_for_node` 前被过滤（实测两出口增量 = `{}`） | `runner._extras` 的 ERROR_OUT/REFUSE_OUT 分支改从 `trace.state` **累积**读终态；`refuse_out`/`error_out` 删死代码回填；`events.py` 删死代码复制循环；`api/errors.py` 新增 `map_refuse(reason)`（`_REFUSAL_MESSAGES`/`_REFUSAL_SUGGESTIONS` 表，与 `map_code` 对称，文案归 L5 因侧信道是唯一活通道） |
| **U-89** | **C3 终态 error 而非 complete（`exec_error` 残留）**：`execute` 成功分支不清 `exec_error`，repair 后第二跳成功被 `route_after_execute` 误判失败 | `execute.py` 成功分支 update 加 `"exec_error": None` |
| **U-90** | **B6 supp 降级为空**：present 返回空增量不写 `degradations`，`audit_supp` 读入参 `state.degradations` 恒空，漏掉 P0 恒在的 `present_failed` | `audit_supp.py` 改从 `context.degradations()`（权威累积器）读 |

### 9.2 差异登记（07 字面 vs 实现事实，断言按实现写，不谎报已解决）

| # | 差异 | 现状 |
|---|---|---|
| **U-91** | B2+B3 `reason` 取值 | 07 字面 `ambiguity`；实现走 `ambiguous_field_binding`（`refuse/clarify` reason 无枚举覆盖该字面值）——断言按实现事实写 |
| **U-92** | C1+C2 合一 | 07 两行（`LlmError` 与 `PlannerError` 计划阶段失败）在实现中走同一条 `plan` 节点异常分流路径，合并为一条可测面 |
| **U-93** | D3 `error` ≠ `refuse` | `policy_gate.run_gate2` 的 G2-DENY 命中敏感列走 `_reject("G2-DENY")`，**不设 `refuse_reason`** ⇒ 终态是 `error` 而非 07 字面的 `refuse`（`PII_BLOCKED`） |
| **U-94** | D4 `message` 为空 | 出口码 `message` 是 `map_code` 入参默认空（文案归 06 UI/UX），runner `_extras` 未接线具体文案——D 组删掉该断言 |
| **U-95** | F1 无弱模型降级档 | `LlmTimeout`/`LlmCircuitOpen` 在图内可测面（脚本件直抛、不经 `app.llm` 网关降级链）→ `llm_error_update` 按 `default_code="INTERNAL"` 折 `error`，而非 07 字面 `degraded + switched_to_weak_model` |
| **U-96** | F5 不可达 | `GateResult` 缺"预估延迟"载体 ⇒ 转异步分支恒 False（已有 `test_edges_contract.py::test_async_switch_is_unreachable_until_carrier_lands` 钉住） |
| **U-97** | F6 会话历史恒空 | `GraphState` 无历史消息字段（`normalize` docstring §三已登记），裁剪无从发生 ⇒ 无任何事件，纯登记 |
| **U-98** | G3 缺载体（kill switch） | 触发面需意图节点读全局禁用开关（P0 无）；路由面（"节点已设终态按终态出口"）已被 `test_edges_contract.py::test_route_after_intent_respects_terminal_set_by_node` 钉住 |
| **U-99** | G4 缺载体（recursion_limit ≥25） | 需构造 ≥25 步循环，正常链无法触达；`GRAPH_RECURSION_LIMIT` 常量见 `build.py` ⇒ 图级不可测 |
| **U-100** | B6 `disclosure` 仅审计可见 | 绑定披露文案只进 `audit_supp` 落行载荷，不进 SSE 帧（前端无该列） |
| **U-101** | `TaskStatus.DEGRADED` 不可达 | 成功链路走 `complete` 终态（携 `degraded` 帧），无独立 `degraded` 终态路径；枚举值存在但图内无出口 |
| **U-102** | E7（取消路径）/ E8（错误码表）引用既有测试 | 无图级新桩：E7 引用 `test_api_runner_contract.py::TestCancellation`，E8 引用 `test_errors_contract.py` |
| **U-103** | 07 L1329 `route_after_plan` 字面缺口 | 07 决策表把 `plan` 异常行写在某条件边上；实现为 `PLAN→BIND` 正常装配下的异常分流（`PlanOutcome` 失败不阻断 BIND 语义），已按实现事实修正 |
| **U-104** | 07 §5.3 `normalize` 行"失败转移"格空着 + 合并档预算冲突（w7 联调 🔴-0） | **已修（预算平移，非契约变更）**：合并档下 `normalize` 一次调用干节点 2+3 的活，节点超时吸收 `intent` 表值（2.0+1.5=3.5s，`build.py:_MERGED_NORMALIZE_EXTRA_S`，执行期按 `deps.merged_understand` 判；split 档/无上下文仍逐字 2.0s，`NODE_TIMEOUT_S` 契约表不动）。根因：合并调用契约预算 1.6s（§16.2）+ 节点级 2.0s 只剩 ~0.4s 余量，w7 单条复现 8/8 稳定超限 50–100ms。**待架构**：补 §5.3 该行"失败转移"格（超时→降级落点口径，如需 W4 再补降级出口） |

> 给 W5 的联调清单沿用 `HANDOFF.md §四`，本节不重复。

---

## 十、U-107 落地回执（架构 §10 → W4，收口后修订提交）

- 归属：**U-107**（`app/graph/**` 域内），依据 `reports/arch/RELAY.md §10` + `docs/07 §5.3.0`「U-107 附注」四条口径。**问题本质**：旧形态把 N-21「软依赖失败必须 200+degraded」反向实现——上游一慢就 `error(INTERNAL)`→`ok=0`（W7 实测 145 条 http_5xx 全 INTERNAL；link 的 bge-m3 实测 4462-5025ms vs 旧 4.0s 硬超时）。四条口径逐条落地如下。

### ① 硬超时改成"按本请求实际模型的客户端超时"（执行期解析，不写死）

- `NODE_TIMEOUT_S` 只剩 **9 个非 LLM 节点**（值逐字：`link 30.0 / bind 0.2 / gate1_ast 0.1 / gate2_policy 0.1 / gate3_cost 1.0 / execute 30.0 / mask 0.1 / audit_pre 1.0 / audit_supp 0.5`）。
- 6 个 LLM 节点（`normalize/intent/plan/gen_sql/present/repair`）移出表 → 新增 `_LLM_NODE_TASKS` + `_client_timeout_for(task)` = `hard_timeout_s(resolve_route(task).model_key)`（§10.2：flash 15s / pro 45s）；`_effective_limit_for` **执行期**解析（图是编译期单例，包装期拿不到最终档）。
- **link 4.0 → 30.0**：具名引用 `Settings.EMBEDDING_TIMEOUT_SECONDS`（`app/core/config.py`，07 §6.5，默认 30）——旧 4.0s 先掐 embedding 自己的 30s 客户端超时（同款病害第二处，U-22 纪律：不得就地发明数值）。

### ② 超时出路表（`_timeout_fallback` 逐节点复用 §5.3「失败转移」列）

- 每次转移**镜像该节点自身处理同源失败的分支**（让"运行中超时"与"节点内失败"产出同形终态）：
  `normalize/plan/gen_sql/repair` → `degraded` + `refuse(no_data_asset)`；`intent` → `refuse`（不发 degraded，镜像节点自身）；`link` → `degraded(embedding_unavailable, sparse_only)` + `refuse`；`bind` → `refuse`（W4 具名裁决：无绑定产物→拒答）；`present` → `degraded(present_failed, table_only)` + 空增量；`gate1_ast/gate2_policy` → `error(GATE_AST_REJECTED/GATE_POLICY_REJECTED)`；`gate3_cost` → `run_gate3(explain_error=True)`→WARN + `gate_update`（跳过并标注，不设终态）；`execute` → 写 `exec_error(timeout)`、不定终态（由 `route_after_execute`/`error_out` 映射 `EXEC_TIMEOUT`）。
- **`_RERAISE_TIMEOUT_NODES = {mask, audit_pre, audit_supp}` 保持 re-raise**：`mask/audit_pre` 是 fail-closed（没跑完=脱敏/段1审计未完成）；`audit_supp` **具名裁决**（兼发 `complete` 终态，超时连终态都没构造 ⇒ 吞掉=流无终态，违 N-08）——理由已写进代码注释。

### ③ `_MERGED_NORMALIZE_EXTRA_S` 语义从"超时平移"→"分配平移"

- 3.5s **保留**（U-104 规则 5 转正），但改承载"分配（budget）"（§16.1 预算 / §16.2 SSE 占位符判定 / `over_budget`），**不再叠加进 `asyncio.timeout`**；LLM 节点硬超时统一走 `_client_timeout_for`。
- ⚠️ W7 重建镜像后看到的 `node_timeout{node=normalize, limit_s:3.5}` 会变成**客户端超时值**——这是设计意图，**不是回滚 🔴-0**（已在 §十登记，请勿改回）。

### ④ 契约测试（与架构 §10④ 的一处分歧，已登记）

- 架构 §10④ 称"契约钉的是**键集**不是值 ⇒ 不需改断言"——**实际代码是值级断言**（`assert NODE_TIMEOUT_S == EXPECTED_TIMED_NODES`），改表必红。故 `tests/contract/test_graph_timeout_contract.py` **已整体重写**：`EXPECTED_TIMED_NODES` 更新为 9 固定节点、新增 `EXPECTED_LLM_NODES`、`TestTimeoutTable`/`TestWrapper`/`TestClientTimeoutResolution`/`TestAssembly` 重组，删除旧 `TestMergedUnderstandSlack` 4 例（其"3.5s 超时平移"语义被 ③ 取消）。

### 门禁（本机 `.venv`，`cd backend`）

- `ruff check .` ✓ ｜ `mypy app` ✓（146 files）｜ `pytest tests/contract/test_graph_timeout_contract.py` 全绿（含 timeout/edges/runner 契约，74 passed 在 contract 目录内）。
- 顺带：U-104 在九天 RELAY 里"待架构补 §5.3 normalize 失败转移格"已由架构 §10 落笔（v1.3，`07 §5.3` 6 格超时列改"= 客户端超时"、link 标"同款病害第二处"、表下加"超时列=硬超时≠分配"注）。

---

## 十一、W4 接续登记（HANDOFF §四~§七 → 本窗口，2026-09-21）

> 本节是"开窗必做"的登记，不新写任何生产代码。§四~§七 与架构 v8 §21 / W0 回执有偏差，逐条列在下面，**偏差以出处复核、别信结论**。

### 11.1 已收口（勿重做）

| 项 | 落点 | 实测状态 |
|---|---|---|
| U-107 节点超时 + 出路表 | `app/graph/build.py` | 已交付，见 §十（本节不重复） |
| U-118① `bind` 并入 LLM 执行期超时 | `8202204`（远端已含） | 已交付：`_LLM_NODE_TASKS["bind"]="l4_score"`，`NODE_TIMEOUT_S` 无 bind |
| U-115 `plan_blocked` 外部可读 | `app/api/runner.py:534-541`（REFUSE_OUT 分支） | 🔴 **仍 OPEN**：只有 PLAN 自拒分支拼 `blocking_issues`；bind 超时 / UNRESOLVED 的 refuse 帧**无**该字段 ⇒ 外部仍只能靠 `node_timeout_degraded{node}` 日志计数区分 |
| U-119 闸门接缝契约测试 | `8a4121a`，`tests/contract/test_gate_seam_contract.py` | 已交付，**Test A 为刻意红**（红 = 缝没修）。W0 §11.5 全量复跑读数：`1 failed / 2207 passed / 6 skipped`，唯一 failed 即本条 |

### 11.2 三处口径订正（HANDOFF 稿 vs 架构 v8 §21 / W0 回执）

1. **G-6 卡点归位**：HANDOFF §五 写"唯一卡点 = τ 未校准"——**已过期**。架构 v8 §21 裁定当下唯一卡着 G-6 的一格 = **`U-121`**，排序 **U-121 → `gate3_cost` / `execute` → 才轮到 τ 校准**；且"先看 `sql_ready` 0→≥1"这条判据**已满足**（`5327b1e` 第八轮预检 `sql_ready=3`，历史首次非 0）。本窗口按 §十二 的扫描接架构那句提醒执行：**修完 U-121 仍不能演示**。
2. **U-117**：HANDOFF §七 写"P2 待读数"——**读数已回并升 P1**（架构 v1.6.4：`binding_layer` L3×3 / L4×0 ⇒ `l4_score` 纯浪费 ⇒ 改条件触发，需 W3C 配合给"无 L4 的两阶段入口"）。W4 侧不擅自动 `bind.py:95`，等 W3C 形态。
3. **U-116 两件补做在 HANDOFF §七 中缺失**，架构 §20③/§21 仍挂 W4 名下：
   - **(a)** 全仓**没有任何测试钉住 `refuse` 载荷键集** ⇒ 要么补一条键集契约断言、要么回填附录 A（架构推荐前者）。
   - **(b)** `runner.py:541` 的 `[str(b) for b in blocking]` 是**模型原文逐字透传、零裁剪** ⇒ **裁剪**或**具名接受**二选一，写进本 RELAY。
   读数时刻 2026-09-21 21:18（本地树 `3991574`）复核命令：`grep -rn "blocking_issues" backend/app/api/runner.py`（命中 534/539/541）、`grep -rn "set(payload)\|keys() ==" backend/tests/contract/*.py`（**零命中**）。

### 11.3 本窗口名下待办（合并 HANDOFF §六/§七 + W0 §11.4/§11.6 后的全集）

| 编号 | 事项 | 依赖 | 状态 |
|---|---|---|---|
| U-121 落地后① | `gate1_ast.py:52` 换调 `guard_allowlist`；`run_gate1` 入参形状随之变 | W2A 实现 | 按住（见 §十二.5） |
| U-121 落地后② | 判据④：**由 W4 传请求级 `max_rows`**，取值面 = `state["options"]["max_rows"]`（`app/graph/state.py:272`）。⚠️ **禁止**用 `GraphDeps.max_rows` 冒充（那是 `EXEC_MAX_ROWS`，`nodes/execute.py:34` 已具名自警） | 同上 | 新增（W0 §11.6④） |
| U-121 落地后③ | `tests/contract/test_gate_seam_contract.py:54` 调用点从 `rt.asset_allowlist(_ctx())` 换 `rt.guard_allowlist(_ctx())`，否则它测的是被废弃的投影 | 同上 | 新增（W0 §11.4） |
| U-121 落地后④ | 跑 U-119 Test A 确认**反绿**；没反绿则查"形状 ≠ W0 显式形状"，**不改测试适配** | 同上 | 继承 |
| U-116(a)(b) | 见 §11.2 第 3 条 | 无（本窗口可独立做） | OPEN，未排期 |
| U-115 | 见 §11.1 | W2B/W2C | OPEN |
| U-117 | 改条件触发 | W3C | P1，本窗口不动 `bind.py` |
| GATE3/EXECUTE 接缝锁 | 待架构/W2D 立号；扫描结论见 §十二 | 架构/W2D | 未立号，不擅自发明出口 |

---

## 十二、GATE1 / GATE2 / GATE3 / EXECUTE **判据源扫描**（W4 只读实测）

> 起因：架构 §21 尾句"修完只到 GATE2 之后 ⇒ `gate3_cost` 与 `execute` 的判据源接缝**请在同一次里扫完**，别让第六格第三次重演'修一格才发现下一格'"。
> **读数条件（可复现）**：时刻 2026-09-21 21:05–21:18，树 = 本地 `main` **`3991574`**（见 §12.1 漂移），全部为**只读**：`sed -n`/`grep -n` 逐处读码 + `git log --oneline -S` / `git ls-remote` / `git rev-list`。**本窗口未跑任何测试/探针/SQL**——W0 §11.5 的全量读数引自它的回执，不是本窗口实测。

### 12.1 基准漂移（实测，先记账再谈结论）

- 本窗口开场实测：`HEAD == origin/main == 8a4121a`、`rev-list --left-right --count` = `0 0`。
- 同一会话内 `git fetch` 后：**远端 main → `ff3e122`**（`docs(w7): 第九轮回执处理`），**本地 main → `3991574`**，且 `origin/main..HEAD` 有 **5 条未推提交**：`633f434`(w2-int) / **`ae59c5c` = `feat(w0): U-121 第一步 端口显式声明闸门判据形状（7 键 + 两面）`** / `1143f99`(w2d exec seam) / `14e9f59`(docs w0) / `3991574`(docs w2d)。
- ⇒ 上一轮"基准对齐 `8a4121a`"的结论**只在 约 21:05 那一刻成立**，本节及以后一律以 `3991574` 为读数树。**这 5 条不是我提交的，我没有推、也不打算代推**（唯一写者纪律）。

### 12.2 四格总表

| 格 | 判据源（应然） | 生产装配现在给不给得出 | 现有的锁 | 今天可归因的失败形态 |
|---|---|---|---|---|
| **GATE1** | `SemanticBundlePort.guard_allowlist(ctx) -> GuardAllowlist`（7 键 wrapper） | ❌ 给不出：`nodes/gate1_ast.py:52` 仍取**扁平** `asset_allowlist`，而 `guard/ast_gate.py:264 run_gate1(sql, allowlist)` 期待 wrapper | U-119 Test A（**刻意红**） | 普通 SQL 被 **R05** 拒（`assets` 取不到） |
| **GATE2** | 同一 wrapper（闸门**自己**在 `guard/policy_gate.py:105` 取数） | ❌ 同上，且 `contracts.py:423` 已明文"`run_gate2` 今天调 `asset_allowlist`，**必须一并改调本方法**" | **无接缝锁** | 见 §12.3：**一条恒拒 + 两条静默放行** |
| **GATE3** | `EXPLAIN (FORMAT JSON)` 计划 JSON，**只能**走 `executor.explain()`（U-63：走 `fetch` 撞 PG 42601） | ⚠️ 装配在（`api/deps.py:750 PgSqlExecutor` / `:828 gate3_thresholds`），但 `explain` **不在 `SqlExecutorPort` 上**（`contracts.py:494` 起只有 `fetch`），靠 `_shared.rich_method`（`nodes/_shared.py:198-212`）取实现类富方法、缺则 fail-fast | **只有脚本件**：`tests/contract/_fullchain_deps.py:436-483` 的 `_ScriptExec` + `GREEN_EXPLAIN` 常量 | 真 EXPLAIN JSON **从未进过 `run_gate3`**（证据链 §12.4）。⚠️ U-107 超时短路 `run_gate3(sql,{"explain_error":True})`（`build.py:574`）是 WARN（`cost_gate.py:79` 立即返回、不看 plan），**不能**当"EXPLAIN 路径已验" |
| **EXECUTE** | 真 DB + 身份 GUC，`deps.executor.fetch(sql, params, identity, max_rows, statement_timeout_ms, effective_limit)`（`nodes/execute.py:70-77`） | ⚠️ 装配同 GATE3；但**图走不到这一格**：上游 gate1/gate2 双封（W7 读数 `GATE_AST_REJECTED`×3、`executing=0`） | **只有脚本件**（同 `_ScriptExec`） | 未验分两层：①**可达性**——U-121 之后才谈得上；②**判据源真值**——要真 DB + 身份 GUC（且按 W7 纪律用一次性库） |

### 12.3 🆕 GATE2 侧三条后果（与 gate1 同源、方向不同；**不在 W4 名下，转 W2C + 抄架构**）

真实现 `app/semantics/runtime.py:102-125` 的返回形状，docstring `:107` 自述 = `{物理名: {logical_name, columns, grain, domain, tenant_scoped}}`（**扁平、无 wrapper**）。把它喂进 `run_gate2` 后，按 `policy_gate.py` 的行号逐条实测：

1. `:106 allowlist.get("assets") or {}` → **`{}`** ⇒ `:120-128` `unknown = tables` 非空 ⇒ **`_reject("G2-ASSET", "查询涉及的数据范围超出你的权限")`** —— 今天**任何引用真实表的 SQL 到 gate2 必被拒**（fail-**closed**，与 gate1 的 R05 同因不同形）。
2. `:109-110 snap_version = allowlist.get("bundle_version")` → **`None`** ⇒ `if snap_version is not None` 不成立 ⇒ **① 版本一致性检查静默跳过**（fail-**open**：请求锚定的旧口径已不在服务也不会告出来，07 §5.7 版本固定的反面）。
3. `:140 deny_columns = allowlist.get("deny_columns") or ()` → **`()`** ⇒ **④ 敏感列二次复核永不命中**（fail-**open**，与 gate1 R07 的冗余复核等于不存在）。

⇒ 给 U-121 的一句话：**只改 `gate1_ast.py:52` 不够**。W0 已在 `contracts.py:423` 写明 `policy_gate.py:105` 要一并改调；若只修 gate1，则 G-6 会从"gate1 恒拒"变成"**gate2 恒拒**"，`gate_passed` 仍为 0，而 ②③ 两条静默 fail-open 会一直藏在恒拒后面。

### 12.4 GATE3 的"真 EXPLAIN 从未进闸门"证据链（全仓 `run_gate3` 调用点实测，5 处）

`app/graph/build.py:574`（超时短路 `explain_error=True`）、`app/graph/nodes/gate3_cost.py:90`（生产路径，入参来自 `deps.gate3_thresholds` + `explain()` 真值）、`app/guard/cost_gate.py:69`（定义）、`app/guard/__init__.py:60`（转发）、`tests/unit/test_guard_gate3.py:29`（**合成** `_plan_payload`）、`tests/eval/test_sandbox_executor.py:261-264`（真件 `executor.explain()` 在离线沙箱**断言返回 `None`** ⇒ 闸门自判 `SKIPPED`）。
⇒ 集合里**没有任何一条**是"真 `PgSqlExecutor.explain()` 的 JSON → `run_gate3`"。这**就是 GATE3 缺的那条 U-119 类接缝锁**，判据形状与 U-119 Test A 同构（真端口输出原样喂闸门）。**编号不自己占**，等架构/W2D 立号（总控已转）。

### 12.5 "继续按住 `gate1_ast.py:52`"的判据（不是保守，是实测）

- U-121 现状 = **1/3**：W0 契约声明**已提交但未推**（`ae59c5c`，`git ls-remote origin main` 不含）；**W2A 实现未落地** —— 读数时刻 21:18 实测 `grep -c guard_allowlist backend/app/semantics/runtime.py` = **`0`**；W2C `policy_gate.py:105` 未改调。
- ⇒ 此刻换调用点 = 调用一个端口声明了、实现类上没有的方法 = **伪造实现**（违反硬约束"不伪造实现"）。同时 §12.3 说明"加个本地适配层凑形状"更是**第三份真相**（架构已禁）。
- 保留项确认：`gate1_ast.py:13-18` docstring 的"与 gate2 **各取一次**是刻意的"设计，换形状时**不合并**（总控 2026-09-21 再确认）。

### 12.6 补登记：EXECUTE 侧一处**本窗口既有**的退化口径（此前 RELAY 未记）

`nodes/execute.py:70-77` 确实把 `effective_limit` 传给了 `fetch`，但值来自 `_effective_limit(state)`，而它 **P0 恒 `None`**（`execute.py:133-146`：gate1 的 `limit_injected` 只有 `None` 或 `{"injected","original_limit"}` 两种形状，**注入值 L 本身没有出口**）。
- W2D 的回执（`3991574`，"给 W4"§2）要求 **"`effective_limit` 请务必传——它是 §8.6 `truncated` 判定的唯一正确口径"**，与本节点的自述前提冲突。
- **责任划分（不猜）**：解点在 **W2C**（把 L 放进 `limit_injected`，或给一个公开取值函数）；W4 只承接消费侧。在此之前 `truncated` 走 executor 的退化口径，"SQL 自带 LIMIT 恰等于行数"的边界上与 §8.6 原文可能差一。
- 诚实订正：该缺口在 `execute.py` 注释里写了"已写进本窗口 RELAY"，但 §一~§十 **并无此登记** ⇒ 本节补上，并以此为订正凭据。

---

## 十三、U-121 第 3 格 · W4 半边落地：`gate1_ast` 换调 `guard_allowlist` + U-119 判据改写（架构 v1.6.5 §22.1）

> 授权链：架构 v1.6.5 §22.1③（落点与判据）→ 总控 21:0x 转达"形状合了再动" → W7 23:07 零额度探针实测 + 总控放行 ⇒ 本窗口先**自证前提**再动（不采信转述）。

### 13.1 前提自证（实测 23:05–23:20，树 `01944dc`）

- `b7e6c8d feat(w2a): U-121 第二步 —— 按 W0 形状实现 guard_allowlist（七键 + 两面）`（21:54）在本地树、是 `HEAD` 祖先、**未推**（`origin/main = 2e2058a`）。
- 本窗口 21:18 那次"`grep -c guard_allowlist runtime.py` = 0"的读数**已被自己的新读数替换**：`runtime.py:141` 起实现存在（§12.5 的"按住"结论到 21:54 为止成立，之后失效）。
- ⚠️ 基准在同会话内又漂两次：`3991574 → 14880ae`(W6, 22:55) `→ 01944dc`(W2C, 23:17)。**均未由我推送，我也没代推。**

### 13.2 改了哪四处（全部在 W4 可写目录）

| 文件 | 改动 |
|---|---|
| `app/graph/nodes/gate1_ast.py:52` | `deps.semantics.asset_allowlist(identity)` → `deps.semantics.guard_allowlist(identity, max_rows=_request_max_rows(state))` |
| 同文件 `_request_max_rows()`（新增） | 判据④ 的送货面：只认 `state["options"]["max_rows"]`（`AskOptions`，`state.py:465`）；options 非映射或值非 `int` ⇒ **照实 `None`**。⚠️ 不拿 `deps.max_rows`（`EXEC_MAX_ROWS`）冒充 = 造数字（U-22）。归一由 `ast_gate._effective_limit` 做，调用方不 clamp |
| 同文件 docstring §二 | 改成"来源只有一处 = `guard_allowlist`（闸门唯一形状）+ 扁平面按设计不得喂闸门"。**"与 gate2 各自取一次是刻意的"整段保留**（总控与架构 §22.2 都点名不许合并），并写明 gate2 侧取用点归 W2C |
| `tests/contract/test_gate_seam_contract.py` | 按 §22.1①② 改写：**Test A** 喂 `rt.guard_allowlist(ctx, max_rows=5000)` ⇒ 普通 SQL 必 `passed=True`；**Test B** 降级为反向对照（扁平面喂闸门必被拒 = fail-closed 行为正确，不再是缺陷）。⚠️ **没保留"原样 Test A + 另补新测试"**（架构明令禁止留没人敢删的红），也**没**为 gate2 写断言 —— 那一条今天必红，对称断言随 W2C 换 `policy_gate.py:105` 时补（文件 docstring 已写明） |
| `tests/contract/_fullchain_deps.py` | `FullChainSemantics` 补 `guard_allowlist(ctx, *, max_rows=None)`，**与 `asset_allowlist` 共用调用序计数器**（保住"gate1 第 1 次、gate2 第 2 次"的既有约定，D3 两份 allowlist 的用例不破） |

### 13.3 门禁实测（23:05–23:15，本机 `.venv`，`cd backend`；未跑 `tests/integration`，W7 纪律）

| 命令 | 读数 |
|---|---|
| `pytest tests/contract/test_gate_seam_contract.py -q` | **2 passed**（= 架构 §22.1 判据；U-119 的 Test A **已反绿**，红因消除） |
| `pytest tests/contract -q --tb=line` | **426 passed**（契约目录零红，含决策表 D/E 全链） |
| `pytest tests/unit -q --tb=line` | **1373 passed**（无"修门禁自伤"） |
| `ruff check app tests` | All checks passed |
| `mypy app` | Success / 147 source files |

### 13.4 独立复现 W7 的读数（零额度离线探针，23:10）

真 `SemanticBundleRuntime(load_bundle(bundle_2026.09.14.1.yaml))` → `guard_allowlist(ctx, max_rows=5000)` → `run_gate1("SELECT pay_amount FROM v_order_paid", …)`：

- 键集 = **7 个齐**（`allowed_constants/assets/bundle_version/default_predicates/deny_columns/joins/max_rows`）；
- `passed=True`；`applied_predicates` = **3 条口径谓词真注入**（`is_test_order = false` / `refund_status <> 'refunded'` / `pay_status = 'paid'`）⇒ U-121 判据② 在这一条读数额成立；
- `rewritten_sql` 尾部 = **`LIMIT 5000`** ⇒ 判据④（请求级 `max_rows`）经我这次的取用点**真的生效**；
- ⚠️ `limit_injected = {'injected': True}` —— **注入值 L 仍无出口**（与 §12.6 同源，W7 已声明不催 W4，改 `_effective_limit` 需要 W2C 给 L）。

### 13.5 🔴 卡点后移，不是修完（给 W7 的 c=1 预检判据）

同一条普通 SQL 直喂 `run_gate2(SQL, ctx, rt)`（真运行时，23:15 实测）：**`passed=False` / `G2-ASSET` "查询涉及的数据范围超出你的权限"**。
⇒ 生产链路现在是 **gate1 过、gate2 恒拒**，`gate_passed` / `executing` **仍会 0**，红因在 W2C 的 `policy_gate.py:105`（+ §6.8 D3/D4 的两个读取面），**不在 W4**。
⇒ 复现命令（离线、不连库不连模型）：`python -c "from app.guard import run_gate2; …"`，或 `pytest tests/contract/test_gate_seam_contract.py -q`（本文件不含 gate2 断言，见 §13.2 末行）。

### 13.6 一处对 W2C `§6.4` 的实测订正（两档不得混写）

W2C 的 A4 档记"真 runtime 扁平面直喂 ⇒ `AttributeError`（`ast_gate:751` 的 `.keys()`）"。**今天直喂真扁平面走不到那一行**：`policy_gate.py:106` 先 `allowlist.get("assets")` → 真扁平面**没有 `assets` 键** → `assets={}` → ② 判 `unknown` → **`G2-ASSET` 拒**（我 23:15 的实测即此）。
⇒ 两种形态的成因不同：**A4 = "`assets` 里有真身、`columns` 是 tuple"才会 `AttributeError`**；**今天 = ② 拦在前面**。A1/A2 的"干净 SQL 即抛 `ContractViolationError`（`policy_gate:148`）"预言的是**换完 `:105`、没换 `:141/:148` 之后**的状态 —— 那是 D4 必改的凭据，不是今天的读数。

### 13.7 与 W2C `§6.8 D8` 的一处冲突（已按架构裁定走，登记不隐瞒）

W2C 默认方案 D8 写"若 W4 排不开同窗 ⇒ **宁可等，不单侧先改**（单侧 = 两真相）"；架构 §22.1③ 则把 `gate1_ast.py:52` 的换调判给 **W4 现在做**、判据 = `2 passed`，总控与 W7 亦放行。本窗口按**架构裁定 > 他窗默认方案**执行，并把"两真相"的**可观测后果**写成 §13.5 的实测（gate1 过 / gate2 拒），供 W2C 落地时对照。⚠️ D3/D4 与 D2 必须同批（"换方法 ≠ 换读取面"），这条我方无代码，只做登记与转述。

---

## 十四、gate2 断言的**两种红法**（W7 复测确认 + 本窗口独立实测，2026-09-22 09:46）

1. **W7 的独立复测收下**（09:21，`test_gate_seam_contract.py` = 2 passed / 真实 `exit=0`，`gate1_ast.py:56` 已是 `guard_allowlist` + 请求级 `max_rows`）。本窗口在同一时段的复跑同读数 ⇒ §十三 的落地**不依赖我这棵树**：新树 `7eaeadc`（W6 `b3092a4` + W2C `7eaeadc` 已在我两条提交之后）上再测 **`tests/contract` 426 passed / ruff 干净 / mypy 147 files Success**。
2. **对 §13.2 末行"gate2 对称断言今天写就是必红"补一句：红法有两种**（W7 提示，本窗口离线双档实测，命令见下）：

| 档 | 状态 | 实测形态 | 归因 |
|---|---|---|---|
| **A** | `policy_gate.py:105` **未换**（= 今天，09:46 实测该行仍是 `bundle.asset_allowlist(ctx)`） | `passed=False` / **`G2-ASSET`**（"查询涉及的数据范围超出你的权限"） | 缺**换方法**（W2C 的 D2） |
| **B** | **只换 `:105`**、没换 `:141/:148` 读取面（用替身端口模拟：`asset_allowlist` 返回 `guard_allowlist(...)`） | **抛 `ContractViolationError`**，抛出点 `policy_gate.py:148` 的 ⑤，detail 带 `asset`；即"语义包 `tenant_scoped` 与 `tenant_id` 列不一致" | 缺**换读取面**（D3/D4）—— ⑤ 读可见面，`tenant_id` 已被裁 ⇒ 断言恒假 |

⇒ 复现命令（离线、不连库不连模型）：`python -c` 里 `run_gate2("SELECT pay_amount FROM v_order_paid", ctx, rt)` 与同一条喂"返回 wrapper 的替身端口"。
⇒ **断言写法约束（我下次写 gate2 那条时照此，且请 W7/W6 不要把两种形态并成一种）**：Test 只能是 `assert run_gate2(...).gate_result.passed is True` 直取，**禁止** `try/except` 把异常折成"被拒"，也**禁止**只断言拒绝码 —— 档 B 应当以 **error** 形态暴露（可归因到读取面），档 A 以 **`G2-ASSET`** 形态暴露（可归因到取用点）。把 B 写成"也是拒"就会让"只换一半"看起来像"没换"，D3/D4 那一半正是最容易被漏的一半。
3. 基准第四次漂移记账：`2544399`(docs w4) → `81288ad`/`b3092a4`(W6, 00:17) → `7eaeadc`(W2C 勘误, 09:40)。`origin/main` 仍 = `2e2058a`，**我未推、未代推**。

---

## 十五、U-122 判据② 落地：`SqlExecutorPort` 声明面 == 图调用面（10:38–10:50，树 `2c18868`）

- 新增 `tests/contract/test_exec_port_face_contract.py`（架构 v1.6.5 §22.3 裁定②："写由 W4、审由 W0"）三条机械断言，**实测 3 passed**：
  1. `fetch` 参数名 == `app.exec.seam.FETCH_CALL_FACE`（含 `effective_limit`）；
  2. `explain` **在端口上**且参数名 == `EXPLAIN_CALL_FACE`（U-63 的入口从此有锁）；
  3. `effective_limit` **无默认值**且 `KEYWORD_ONLY`（W0 `aa494f6` 裁定：给默认值 = 允许静默漏传 = §8.6 `truncated` 口径 fail-open）。
- **反向对照（证明断言不是空转）**：同一判据打在 `app/exec/seam.py:114` 的 `ExecutorSeam.fetch` 上，`effective_limit` 默认值实测 `= None` ⇒ **该档不成立** ⇒ 端口与 seam 确实差在"必填"这一刀；真实现 `PgSqlExecutor.fetch` 也 `= None`（更宽松仍满足端口声明 ⇒ W0 那句"不要求任何实现改动"我这边复算成立）。
- 复跑门禁：`tests/contract` **429 passed**（426 + 本次 3）｜`ruff check app tests` 干净｜`mypy app` Success / 147 files。仍未跑 `tests/integration`（W7 纪律）。
- **§十四 的前提未变**：10:38 实测 `policy_gate.py:105` 仍是 `bundle.asset_allowlist(ctx)`、`:148` 仍读 `asset.get("columns")` ⇒ W2C 的 D2/D3/D4 未落地 ⇒ **gate2 对称断言仍不能写绿的**（写了必红），等三处同批时我按 §十四 的两种红法补。
- ⚠️ **转 W2C 的一处探针/生产不同名**（`2c18868` 的 D5+ `oracle_check`）：探针里 `_rule1()` 走 `bundle.asset_allowlist(CTX)` 来模拟"闸门已吃 wrapper"。而生产 gate1 自 `357618f` 起吃的是 **`guard_allowlist`**。⇒ 若照这份探针复跑"落地判据"，测的是**替身的方法名**不是生产调用面（`U-121` 的病根正是"闸门从哪个方法取"）。请在 D2 落地时把探针入口一并改成 `guard_allowlist`，否则 A/B 两档的读数与生产无关。**归因**：只读比对 `reports/w2c/_probe_u121_faces.py` 的 `_rule1` 与本文件 §13.2，读数时刻 10:45。

---

## 十六、U-122 判据③+④ 落地 + 一处自我订正（14:03，树 `dc62468`）

### 16.1 序号对齐（W7 按架构 v9.3 提出，本窗口接受）

`c2f63cf` 记为 **判据①+② 合一**（① = `explain` 上端口、② = `fetch` 关键字集 == `FETCH_CALL_FACE`）。本轮补齐我名下剩下两条 ⇒ **U-122 的 W4 侧四条齐**（③④ 见下，实现侧声明归 W0 `aa494f6` + W2D `1143f99`）：

| 判据 | 落点 | 实测 |
|---|---|---|
| **③** 全链肯定断言 | `tests/contract/test_decision_table_d_e.py::test_d_green_chain_emits_gate_passed_and_executing` | 绿档确实发出 `gate_passed` 与 `executing` 两帧，且 `index(gate_passed) < index(executing)`、`fetch_calls == 1`、终态 `complete`。**此前全链级 0 条肯定断言**（D5/D6 只有 `not in` 否定式；W2D 的"单元级 1 条 / 全链级 0 条"口径由本条关闭） |
| **④** 替身忠实性 | `tests/contract/test_exec_port_face_contract.py::test_fullchain_script_executor_is_faithful` | `declared_call_face_mismatches(ScriptExecutor()) == ()`；配 **反向对照** `test_call_face_helper_is_load_bearing`：删掉 `explain` 的替身被抓为 `"缺方法 explain"` ⇒ 证明上一条不是空断言 |

门禁读数（14:00–14:03，`cd backend`，未跑 `tests/integration`）：新文件 + D/E 两档 **19 passed**｜`tests/contract` **432 passed**（+3）｜`ruff check app tests` 干净｜`mypy app` Success / 147 files。⚠️ `ruff format --check` 对 `test_decision_table_d_e.py` 报"would reformat" —— 实测**该偏差在 `HEAD` 版本就已存在**（`git show HEAD:… > /tmp/x.py` 后 `--check` 同样报），非本次引入，我**不顺手重排**（`format` 不在 HANDOFF §三 的三条门禁里）。

### 16.2 🔴 自我订正：我 §十五 末条对 W2C 探针的定性说过头了

我写的是"那份探针测的是替身的方法名不是生产调用面 ⇒ **A/B 两档读数与生产无关**"。经 W7 复核 + 架构 v9.2 自证（`reports/arch/probe_u121_half_landed.py`），**该结论要收窄**：

- **形状判据有效**：W2C 探针的替身 `_Shaped` 内部就是取 `rt.guard_allowlist(...)`，所以档 3a/3b 关于"可见面 vs 顶全列"的 `R06`/`R07` 分裂读数**与生产同源**，不是无关。架构 v9.3 已把它升为 `U-121` **判据⑤**。
- **剩下的只是入口名**：`_rule1()` 外层写的是 `bundle.asset_allowlist(CTX)`，与生产 `guard_allowlist` 不同名 ⇒ 一行改名即可，不影响已出的读数。
- **"生产调用面有没有人还在吃扁平面"这半边不必我叠层**：已由 W6 `b3092a4` 的**按文件 AST 哨兵**覆盖 ⇒ 我不再另立第二道检查（避免同址两判据）。
- 保留的正确部分：入口名仍应与生产同名，W2C 落地 D2 时顺手改。⇒ 教训照架构纪律 ① 记一次：**我这句"与生产无关"是否定性断言，写的时候没做"形状来源"的对照实验**（只比了方法名）。旧文不改，本节为具名订正凭据。

### 16.3 角色与待办变更（照架构 v9.2 登记，不重记号）

- `U-119` **判据④ = gate2 对称断言**：裁定改为"**W2C 换调的同一 PR 落地、W4 审形状**" ⇒ 我的角色从"写断言"变"**审形状**"，写法仍按 §十四 两种红法（只 `assert passed is True`，不 `try/except`、不只断言拒绝码）。**`U-119` 不记结案**（架构明令：Test A 转绿 ≠ `U-121` 付清）。
- `U-121` 落地铁律已由架构升格：**`policy_gate.py` 105 + 141 + 148 同一 PR**，禁止"先换 105 再说"；三家独立读数一致（W4 `6da16db` / W7 09:21 / 架构探针 09:55），半落地态会以未捕获 `ContractViolationError` 冒进图 ⇒ 落 `INTERNAL`，归因能力倒退。
- 仍欠（未变）：U-116(a) `refuse` 键集断言、U-116(b) `blocking_issues` 裁剪或具名接受、U-115（P1 排序在后）、U-117（等 W3C 两阶段入口）。
- 共享状态记一笔：我前三条提交由 W7 按总控点名**连带推**（`2c18868..4e782b6`，其 RELAY §二十九①）；本轮起按新纪律**自行 push 本窗口提交**。

---

## 十七、归属失真记一笔：§十六 的三条改动被并进了别人的提交（14:04–14:06 实测）

- **事实**：我先 `git add` 了本窗口的三个文件（`reports/w4/RELAY.md` §十六 / `tests/contract/test_exec_port_face_contract.py` 判据④ / `tests/contract/test_decision_table_d_e.py` 判据③），在我执行 `git commit` 之前，同一工作副本里的 **W2B 提交了 `0f3f125 docs(w2b): embed_doc 重灌回执…`** —— `git commit` 吃的是**整个索引**，于是我的改动以**别人的 message** 入库：`git show --stat 0f3f125` 实测含 `backend/reports/w4/RELAY.md +31`、`test_decision_table_d_e.py +20`、`test_exec_port_face_contract.py +41`。
- **该提交已被推送**（`origin/main = 0f3f125`，非我推）。⇒ 公共历史里"谁验证过这三条判据"已经失真，**不回改**（改要 force-push 公开历史，代价大于收益，与架构对 `9c65a42` 的处置同源）。本节即为归因凭据：**判据③④ 与 §十六 由 W4 写并实测**（19 passed / contract 432 passed / ruff / mypy，读数见 §16.1），只是落库号错挂在 `0f3f125` 下。
- **机制与自防（下次照做）**：一个工作副本多窗口共享 ⇒ 索引是**共享状态**。本窗口的做法改三条：① `git add` 与 `git commit` **写在同一条命令里、零间隔**；② 提交前一刻 `git diff --cached --name-only` 复核索引内容只含本窗口文件；③ 提交后立刻 `git show --stat` 验证只含自己的文件，若发现被并入他人提交，按本节形式登记归因而**不重写历史**。
- 同时记一次共享 refs 异常：`git fetch` 在 14:05 打 `* [new branch] main -> origin/main`，此前 `refs/remotes/origin/main` **一度不存在**（表现为 `git status` 报 "upstream is gone"、`rev-parse` 报 "Needed a single revision"，14:00–14:05 两次命中）。不是我删的，也未被谁声明；恢复后读数正常。

---

## 十八、W7 上呈「闸门 `rule_id` 到不了任何归因面」——本窗口自证 + 拆责任 + 要号（21:13，树 `d4ca203`）

### 18.1 三条读数我逐条复现了（只读，全部成立）

| W7 的说法 | 本窗口实测 |
|---|---|
| error 帧只有 `code/message/retryable` | ✅ `app/api/runner.py:543-563`：`payload` 三键 + `detail`（且仅当 `errors.detail_allowed_for(role)` **且** `mapping.detail` 非空）。闸门码走 `map_code` 的固定文案 ⇒ 帧面无 `rule_id` |
| `gate_detail`（含 `rule_id`）只挂在 `gate_passed` 上 | ✅ `app/graph/events.py:215` 是 `gate_detail` 的**唯一**发射点，且被 `_all_gates_clean_pass` 门住 ⇒ **只有全净通过才发**，拒绝路径永远不发 |
| `gate_reject_total{rule_id=""}` 恒空 | ✅ `app/obs/instrumentation.py:448-455` 的反推只能给 `gate_no`（`_GATE_NO_BY_ERROR_CODE`，:91-95），`rule_id` 只能从帧上取（`_gate_facts` :474-487）⇒ 上游没给 ⇒ 恒落 `EMPTY_LABEL_VALUE` |

### 18.2 还有第四处，W7 没报（我扫出来的）：**标签面只开了 gate1 的字母表**

`app/obs/metrics.py:671-677` 把 `gate_reject_total` 的 `rule_id` 取值域声明为 `(EMPTY, *AstRule)`；而端口上的载体是 `GateResult.rule_id: str | None`（`app/core/contracts.py:137`），**三闸通用字符串**。
⇒ 后果：即使按 W7 建议在节点侧补记，**gate2 的 `G2-ASSET`/`G2-DENY`/`G2-VERSION` 与 gate3 的号会被开放集"丢弃 + 计溢出"**（`metrics.py:207` 的越界处置）⇒ 光挪记录点治不好，标签面必须同时放宽。**这条决定它是跨窗三处、不是两处。**

### 18.3 拆责任（按 08 §4.1）与"不单侧先改"的理由

| # | 落点 | 归属 | 成本 |
|---|---|---|---|
| ① | 节点侧唯一记录点：`app/graph/nodes/_shared.py::gate_update`（:116-120，**三闸共用的收敛点**，`gate1_ast.py:63`/`gate2_policy.py:62`/`gate3_cost.py:92` 都过它）里对 `result.passed is False` 记 `metrics.observe_gate_reject(gate_no, rule_id)` | **W4** | 1 处（API 现成：`metrics.py:962` 已收 `rule_id`） |
| ② | 摘掉 `instrumentation.py:448-455` 的 `error` 帧反推 | **W7**（`app/obs/**` 指标部分按 08 §4.1:287 归 W7） | 删一段；**必须与 ① 同批**，否则 `gate_reject_total` 双计 |
| ③ | `rule_id` 取值域从 `AstRule` 放宽到三闸规则字母表 | **W7** | 声明 + 溢出计数复核 |

⇒ **本窗口本轮不动代码**：①单落 = 制造双计 + gate2/3 读数被丢弃，正是本项目一周内被烧过三次的"半落地比现状坏"。先例支持节点侧：exec 面的权威记录点就在节点（`nodes/execute.py::_on_failure` 记 `exec_failure_total{error_class}`），而**没有**从帧反推 —— 那条注释本身就写在 `instrumentation.py:456-462`（"① 与节点侧双计；② 五类压一类"）。
⇒ 帧面出口**本轮不碰**：`error` 载荷属附录 A（最高优先级契约），加 `rule_id` 要走上游回填，请架构裁"是否需要"，我不擅自加键。

### 18.4 要号 + 一条 exec 面读数订正

- 🔴 **报架构要号**：`07 §14.5` "闸门拒绝率按 `rule_id` 分组"今天做不到（18.1 三条 + 18.2 第四处），修复面跨 W4/W7 三处 —— 请归一个号（**默认按 `U-123`**；`docs/07 §4.8` 若已另有安排以 §4.8 为准）。本窗口**不自占号**。
- 同时记一笔 W7 的 `executing` 首次非 0（`preflight_r6.json`）：W4 的 exec 面**第一次被真流量走到**，死因 `unknown_table` ⇒ **不是 exec 缺陷**（引用了不在册资产，成因在语义包/闸门面）。⚠️ 但要说清归因面现状：`app/exec/errors.py:136-140` 把 `unknown_column/unknown_table/type_mismatch/unknown_function/syntax_error` **五类压成同一个 `SQL_SYNTAX_ERROR`** ⇒ 帧上只会是语法错；W7 能分清是靠节点侧 `exec_failure_total{error_class}`（18.3 的正面先例）与其离线器件，**不是**靠 error 帧。

> 复现命令（全部离线、零额度）：`sed -n '543,563p' app/api/runner.py`｜`sed -n '213,217p;295,305p' app/graph/events.py`｜`sed -n '448,462p' app/obs/instrumentation.py`｜`sed -n '667,678p' app/obs/metrics.py`｜`sed -n '136,140p' app/exec/errors.py`。读数时刻 2026-09-22 21:13，树 `d4ca203`；本窗口本轮**未改代码、未跑门禁**（无代码改动可测）。

---

## 十九、编号订正（`U-123` → **`U-125`**）+ `U-119` 判据④ 落地（16:33，树 `bfbb16f` 之后）

### 19.1 🔴 具名订正：我 §18.4 写的"默认 `U-123`"撞号，作废

- 出处核对：`docs/07 §4.8` 的 `U-123` 已在 **v1.6.9** 归给 **W2A**（`materialize()` 缺派生器的破坏性幂等，P0，落地件 `5e47558`）。我在 §十八 用它作"默认号"是**没先 grep 冻结表就取号**，正是本项目第三次同类。
- 本项的正确号 = **`U-125`（P1，W4 + W7）**，出处：`docs/07` 修订表 **v1.7.1** 行"新开 `U-125` = 闸门拒绝的 `rule_id` 三个出口全断…**判据含'唯一记录点 = 闸门节点 + 同批摘掉 `instrumentation.py:455` 反推路径'（只补不删 = 双计）**"，与 §4.8 末段"下一可用号 = `U-126`"一致。旧文不删，本节为凭据。
- ⇒ 本窗口以后取号前**先跑一次双向 grep**（代码 + 全部 commit message），并把 §4.8 的行号抄进回执。

### 19.2 `U-125` 同批协议（W7 排期，本窗口接受）

W7 下一次开工写 **②摘 `instrumentation.py` 反推 + ③放宽 `metrics.py:676` 的 `rule_id` 取值域 + 自测**，**只贴 diff 不提交**；我在同一轮落 **①`app/graph/nodes/_shared.py::gate_update`**（三闸共用收敛点，:116-120）⇒ **①②③ 同一批、同一 push**。
**我不单推 ①**（只补不删 = `gate_reject_total` 双计），也不催 W7 单推（只删不补 = 恒空标签）。本轮 W4 侧**无 `U-125` 代码改动**。

### 19.3 🟢 本轮实际交付：`U-119` **判据④**（gate2 对称断言）——架构 v1.7.0 具名追讨的那条

- 前提自证：W2C `c76f701`（16:36，已在 `origin/main`）确把三处换完 —— `policy_gate.py:110` 取 `bundle.guard_allowlist(ctx)`、`:158` 的 `has_tenant_col` 读 **`all_columns`**、`:187-201` 提供一次性结构面视图。
- 落地：`tests/contract/test_gate_seam_contract.py::test_plain_sql_passes_through_gate2_seam`（Test C）。写法照 §十四 两种红法：**只 `assert ... passed is True` 直取，不 `try/except`、不只断言拒绝码** ⇒ 半落地态（换了取用点没换 `:154`/`:158`）会以未捕获 `ContractViolationError` 暴露，error 形态本身就是归因。
- 读数（16:33，`cd backend`，未跑 integration）：`test_gate_seam_contract.py` **3 passed**｜`tests/contract` **443 passed**｜`ruff check app tests` 干净｜`mypy app` Success / 147 files。
- ⚠️ **引用要带区间**：架构 v1.6.5 的判据"该文件 = **2 passed**"自本提交起**失效**（现 3 条）。同理 v1.6.7 那句"全量 suite 恒有 1 条刻意红"的区间是 `8a4121a`～`357618f`。**"2 passed" 与 "恒 1 红" 都不要再无限定引用。**
- 顺带修掉我文件里那条过期注释（架构 v1.7.0 点名的 `test_gate_seam_contract.py:11-12` 仍写"`policy_gate.py:105` 扁平面"）。⚠️ **派单更正**：架构那句写"归 W0 改，不占号"—— 但 `tests/contract/**` 按 **08 §4.1** 归 **W4**，W0 无写权 ⇒ 由本窗口改掉了；请转告架构把归属列订正，避免下一个窗口以为 W0 会动它。
- `U-119` 状态：判据①③④ 均有锁且全绿；**结案与否归架构裁**（本窗口不自关）。
- 另记一次共享 refs 异常（第三次）：15:0x 与 21:1x 两度 `refs/remotes/origin/main` 不存在 ⇒ `git status` 报 `upstream is gone`、`git log origin/main..HEAD` 报 `fatal: ambiguous argument`，`git fetch` 后恢复；不是我删的。

---

## 二十、`U-125` ①②③ 同批落地 + 一条 SLO 互斥的立场（23:10，树 `cc46e8a` 之后）

### 20.1 同批内容（W7 的 ②③ 由本窗口代为提交，归属点名如下）

- **②③ = W7 写的**（补丁 `backend/reports/w7/u125_w7_side.patch`，`git apply --check` OK，本窗口 23:0x `git apply` 后未改一行）：`app/obs/instrumentation.py`（摘掉终止帧反推：删 `_GATE_NO_BY_ERROR_CODE` 与 `_gate_facts`）、`app/obs/metrics.py`（`GATE_REJECT_RULE_IDS` = 空值 + `AstRule` + `POLICY_RULE_IDS(4)` + `COST_RULE_IDS(1)`；`observe_gate_reject` 参数放宽成 `AstRule | str | None`）、`tests/unit/test_obs_gate_rule_vocabulary.py`（新增）、`tests/unit/test_obs_instrumentation.py`、**以及两处落在 `tests/contract/**` 的**（`test_obs_audit_contract.py`、`test_obs_frame_format.py`）—— ⇒ 🔴 **请架构订正 08 §4.1 的归属列**：`tests/contract/**` 按现表归 W4，而这两处的内容是 W7 的判据；本轮按 W7 要求"同一 commit 同批"由我提交，**作者归属以本行为准**。
- **① = W4 写的**：`app/graph/nodes/_shared.py::gate_update`（三闸共用收敛点）在 `result.passed is False` 时记 `observe_gate_reject(gate_no, result.rule_id)`；docstring 写明"记在节点而不是观测器"的两条理由与"①② 必须同批（只补不删=双计、只删不补=恒 0）"。先例 = `nodes/execute.py::_on_failure`。
- **① 的锁**（新）：`tests/contract/test_gate_reject_metric_contract.py` 5 条 —— `G2-*` 落自己序列、gate1 用 `AstRule` 字面值、三道闸不共享标签、`pass/warn/skipped` 不计数、载体真缺号才落空值。读数一律用**增量**（指标是进程级注册表）。

### 20.2 门禁实测（23:05–23:10，`cd backend`；未跑 `tests/integration`，W7 纪律）

| 项 | 读数 |
|---|---|
| `pytest tests/unit tests/contract tests/redteam -q` | **1845 passed**（W7 交来的 1840 + 我 5 条；红队集未退步） |
| `ruff check app tests` | All checks passed |
| `mypy app` | Success / 147 source files |
| `lint-imports` | **4 kept, 0 broken**（`app.graph → app.obs.metrics` 与 `execute.py` 同层先例一致） |
| **端到端反双计**（真图一轮，`make_chain(sql="SELECT 1; SELECT 2")` → gate1 拒） | `gate_reject_total` 全族 **delta = 1.0**，序列 = `{gate_no="1", rule_id="R02"}` ⇒ 走完整图（含观测器在场）只记一次、且带得出规则号 |
| `test_gate_seam_contract.py`（上一批） | 3 passed，未受本批影响 |

### 20.3 🔴 W7 上呈的"15s 硬超时 × G-6 `p95≤8s`"互斥：本窗口的立场与要裁的东西

- 事实自证：`app/llm/router.py:306 hard_timeout_s()` 的 docstring 明写 **07 §10.2 = flash 15s / pro 45s**，且**刻意不看 task** —— 因为曾把 stage 预算 `TaskRoute.budget_s` 当 deadline，"真机延迟 > 分配值"的任务 **100% 失败（实测 0/15 → 15/15）**。我 U-107 的节点超时就是**执行期解析这个客户端超时**（§十），所以"把 15s 压到 8s 以内"= 重新引入那次实录，**我不做**。
- ⇒ 真正的待裁项**不是**改超时值，而是二选一：**(a) 架构裁 SLO 口径**（`p95≤8s` 是否该按"含 LLM 出站的端到端"计，还是按"去掉模型出站的编排 + 检索段"计）；**(b) 我这边加降级出路**（超过 SLO 阈值就走 §16.2 的"转异步/占位续推"，而该分支今天**不可达**：`GateResult` 缺"预估延迟"载体 = 已登记的 **`U-96`**，架构 v1.7.x 仍排队、需真 PG 复现）。
- ⇒ 请架构归号（**本窗口不自取号**；`docs/07 §4.8` 末段记下一可用 = `U-126`，取号前按纪律先双向 grep）。W7 侧读数我不代记：本轮 `max 15,080.1ms`、`degraded{llm_unavailable}` 3/≈9 ⇒ 引 W7 §三十三，不是我测的。
- 另请 W7 收一处**补丁留下的孤儿注释**：`app/obs/instrumentation.py:82-88` 还在讲"为什么必须有这张表…少了这张表 `gate_reject_total` 就是恒 0 的族"，而被讲的 `_GATE_NO_BY_ERROR_CODE` 已被 ② 删掉（ruff/mypy 都不会报）。归 W7 的文件，我不动。

---

## 二十一、W7 的"15s 墙钟被排队吃掉"——本窗口认可因果，并补两处代码级机制（23:2x，树 `cb0b4a8`）

### 21.1 认可，而且机制我能指到行

| 环节 | 实测 |
|---|---|
| 排队不扣 deadline | `app/llm/client.py:224` 先算 `remaining = deadline - monotonic()`，`_attempt` 在**之后**才 `_acquire`（:308-310）⇒ 等待时间**不进** `remaining` |
| 等待上限比墙钟长 | `client.py:72 SEMAPHORE_WAIT_TIMEOUT_S = 20.0`（07 §10.1）vs 我 U-107 给 normalize 的 **15.0s**（执行期解析 `hard_timeout_s`，flash）⇒ 两个预算**并联**，最坏可叠到 `15+20`；先到的是节点那一头 |
| 所以观测面看不见排队 | `client.py:310-311` `t0` 在 `_acquire` **之后**才取 ⇒ `latency_ms` 天然不含等待 ⇒ W7 读到"`normalize_intent` 全在 1.0–1.1s"与"节点 15s 超时"同时成立，**不矛盾**，正是等待主导的形状 |
| 🔴 归因面断裂 | `grep -rn "Saturated" app/graph app/api` = **零命中**（只有 `tests/unit/test_llm_client.py` 读它）⇒ 而 `app/llm/errors.py:127-128` 明写"`LlmUpstreamReject`=error、`LlmSaturated`=**degraded**（我们自己的并发位没等到，请求还没发出）"。节点 15s 抢在 20s 之前 ⇒ 生产里**永远到不了** `LlmSaturated` 那一格，容量不足被记成 `node_timeout_degraded{normalize}`，再经我 §5.3 的出路表落成 **`refuse(no_data_asset)`** ⇒ 用户侧读到"这问题需要的数据不在语义层"，而真相是"我们没排到位" |

⇒ 因果我认可；但**定死还差一条对照**：同 `c=50/n=120` 复跑一次把 `LLM_SEMAPHORE_FLASH` 抬到 16，看 `node_timeout_degraded` 增量是否显著下降。W7 给的 `c=1/n=3`（增量 0）是**负载侧**对照，不是**槽位侧**对照。

### 21.2 我这侧动什么、不动什么

- **不动**：① `15s` 这个值本身 —— `app/llm/router.py:306-313` 的 docstring 记着"曾把 `budget_s`（P95 目标）当 deadline，真机延迟>分配值的任务 **0/15 → 15/15**"，压它=重新引入那次实录；② 槽位默认值 —— `app/core/config.py:78 LLM_SEMAPHORE_FLASH: int = 8` 属 W0 + 07 附-6 的分配，且抬槽位=撞上游限流，归架构配平。
- **要动、归我（图侧）**：给 normalize 的超时出路**区分"等待中"与"发送后"** —— 现形态是 `asyncio.timeout` 一刀切（U-107），所以容量信号被折进"模型慢"。具体做法需要 W3A 先在 `_acquire` **之后**重算 `remaining`（否则节点侧拿不到"已等了多久"），我这边才有分支可写 ⇒ **跨窗只提需求**，不落别人代码。
- **要动、归 W7**：缺一条 `llm_queue_wait_ms` 序列（现在的 `latency_ms` 结构性看不见等待，任何"排队 vs 慢"的判断都只能靠推断）。
- **要裁、归架构**：`§10.2 flash 15s` × `G-6 p95≤8s` × `§10.1 排队 20s` 三者一起配平，别两两互斥（我 §二十.4 已登记前两者的互斥，本轮补上第三者）。**编号不自取**：`docs/07 §4.8` 现读盘"下一可用号仍 = `U-126`"（09-28 读盘，不抄快照）。

### 21.3 纪律四条变更对本窗口的实测响应（09-28）

- ①已核：`backend/reports/arch/` 确在库内（`git ls-files` 出 `DELIVERY/HANDOVER/PROMPT/RELAY.md`）。**EOL 同仓混存**：`tr -cd '\r' | wc -c` 实测 `reports/w4/RELAY.md` = **0 CR（LF）**、`reports/arch/RELAY.md` = **1060 CR（CRLF）** ⇒ 我下轮改任一文档前先跑这条探针。
- ②已核：判定权威改读 `docs/07 §4.8` + `reports/w6/评测报告与门禁判定.md`；我不再往 `.workbuddy/memory/` 写，Qoder 记忆层只留指针。
- ③已按：本轮 `U-125` 同批仍是**逐文件 `git add`**（9 个文件全点名，无 `-A`），`git diff --cached --name-only` + 提交后 `git show --stat` 双检，实测未卷走他人暂存。
- ④已按：本轮出现的两个号（`U-125`/`U-126`）都是从 `docs/07 §4.8` 现读，未引用任何提示词快照。

---

## 二十二、`U-129`（P0，W4）N-08 双终态 —— 认账、机制、修法与门禁（09-28 20:2x，树 `e45c0a4`）

### 22.1 认（因果指得到行，且成因是我自己的裁定）

- 编号现读 `docs/07 §4.8`：**`U-129`（P0，W4）= N-08 双终态**；同批还有 `U-126`（容量几何×SLO，我 §二十一 那条）、`U-127`（`§10.1` 排队出口生产不可达，W3A+W4+W7）、`U-128`（`l4_score` 被 `max_tokens=512` 截断）⇒ **下一可用号 = `U-130`**（本轮零自占）。
- 机制（我这一侧的直接成因）：U-107 ③ 把 `_MERGED_NORMALIZE_EXTRA_S` 从 `asyncio.timeout` 里摘掉、节点硬超时改成**等于客户端超时** ⇒ normalize 的墙钟 = **15.0s**、flash 客户端 deadline 也是 **15.0s** ⇒ 上游用满预算时**两条超时同刻到期**：客户端那条在 `app/llm/__init__.py:496` 落进模板兜底（`llm_falling_back_to_template`）并由节点自身把终态判成 `refuse`，节点那条又走我的出路表再写一次第二个终态。
- 为什么表现成 `INTERNAL` + 审计 0 行：`terminal_update`（`nodes/_shared.py:165`）里的 `assert_terminal_is_settable(state)` 读的就是 `state.get("terminal")`（`state.py:479`）⇒ 第二次写抛 `ValueError` → `runner.py:484` 记 `graph_run_failed` → 补发 `error(INTERNAL)`，且审计段没走到。W7 的 8/8 形状与此完全一致。

### 22.2 修法（只动我名下两处，8 个调用点）

- `app/graph/build.py::_timeout_fallback`：开头取 `terminal_already_set = state.get("terminal") is not None`，把函数内 **8 处** `terminal_update(state, …)` 收敛进本地 `_terminal(**kwargs)` —— **已有终态时什么也不设**，只记一条具名日志 `node_timeout_terminal_already_set`（不吞降级、不覆盖既有结论、不改出路表其余语义）。
- ⚠️ **不是把 N-08 改成静默覆盖**：写入口检查原样保留，契约里有反向对照钉着（`test_second_terminal_would_still_be_rejected_by_state_layer`：直接第二次写 `terminal_update` 仍抛 `ValueError`）。
- **我没做的**：错峰值（节点墙钟 = 客户端 + ε）。它直接抵触 U-107 §5.3.0 规则 2 的"硬超时=客户端超时"裁定 ⇒ 归架构裁，与 `U-126`/`U-127` 的配平同一张桌子，我不自行动。

### 22.3 门禁与两条"不是我"的红（09-28 20:1x–20:2x，`cd backend`）

| 项 | 读数 |
|---|---|
| `pytest tests/contract/test_graph_timeout_contract.py -q` | **20 passed**（含我新增 `TestU129SingleTerminal` 3 条：已有终态时不写第二个 / 写入口检查未削弱 / 无终态时仍恰设一次 refuse） |
| `pytest tests/unit tests/contract tests/redteam -q -p no:randomly` | **1858 passed**（确定序全绿） |
| 同三条目录**默认随机序** | **2 failed, 1850 passed**：`test_gate_seam_contract.py::test_deny_column_rejected_through_gate2_seam[裸写]` 与 `tests/redteam::TestNegativeControl::test_gate2_redundancy_catches_when_gate1_blind` |
| `ruff check app tests` / `mypy app` / `lint-imports` | All checks passed / Success 147 files / **4 kept, 0 broken** |

两条红的归因（都**不在**我改的文件里，形状 = 跨用例状态污染，且都落在"gate2 结构面 vs 可见面切换"这一族）：
1. `test_deny_column_rejected_through_gate2_seam[裸写]` 与紧随的 `test_gate2_deny_check_depends_on_structure_face` **不在 git 历史里** —— `git log -S "test_deny_column_rejected_through_gate2_seam"` = 空，而工作区 `test_gate_seam_contract.py` 有 **+57 行未提交改动**（别人把 `U-119` 判据④b 的 Test D/E 写进了**我的**文件）。裸写形态当前不被 `G2-DENY` 拦，正是 W2C `§6.4` B1 档自记的"**残余漏检**"，不是夹具写错。⇒ 请作者与 W2C 认领；我不代提交、也不替他们判。
2. `tests/redteam` 那条自 `9e2bd7e` 就在，架构 v1.7.1 已具名报过红队有红（撤销判据⑤、换判据⑥那轮）。
3. 我自己那条嫌疑被**我自己的对照否证**：怀疑新加的 `test_gate_reject_metric_contract.py` 给全局注册表加计数会打挂 W7 的 `total()==0` 断言 ⇒ 把它排在 `tests/unit/test_obs_instrumentation.py` **之前**跑 = **30 passed**，无污染。

### 22.4 `U-127` ②③ 与 W3A ① 同批的约法（回 W7）

- 架构已裁"①②③ 同一 PR"，前科我认（`U-121` 只换 `:105` ⇒ 未捕获 `ContractViolationError`）。**判据③ 那条契约断言落 `tests/contract/**` = 我面**，我承诺随批写；但**不在 ① 之前单独落**——单独落就是"判据本身要求的红"，按 `08 §6.6` 既不能 skip 也不能 xfail，会把 CI 挂成背景噪音。
- 我这侧为 ② 准备的可复核形状：`_timeout_fallback` 的终态感知（本轮已落）+ `node_timeout_terminal_already_set` 具名日志 ⇒ W7 复跑 `c=50/n=120` 时应看到 `graph_run_failed{N-08}` 归零、`refuse` 终态进 `app.audit_log`（**判据**：`node_timeout_degraded{normalize}` 可以仍有，但 `INTERNAL` 必须为 0、审计行数必须 = 拒答数）。
- 工作区现状提醒（跑前自证）：本轮跑门时树里另有他人未提交件 —— `app/llm/{__init__,client,router}.py`、`tests/unit/test_llm_router.py`（W3A 在制品）、`reports/w1b/RELAY.md`。我按 `08 §6.4` **逐文件 add 且只 add 我三件**（`app/graph/build.py`、`tests/contract/test_graph_timeout_contract.py`、`reports/w4/RELAY.md`），提交后 `git show --stat` 复核。

### 22.5 跑后自证（同树 `1036295`，20:3x）—— 两条红改判为"顺序相关"，不指认某个提交

| 采样 | 命令 | 读数 |
|---|---|---|
| 跑前（我 fix 落地前，树 `e45c0a4` + W3A **未提交**在制品） | `pytest tests/unit tests/contract tests/redteam -q`（默认序） | **2 failed, 1850 passed** |
| 同上，禁随机 | `… -p no:randomly` | 455 passed（仅 contract）；全量 **1858 passed** |
| 跑后（我 fix = `7035db3`；W3A 已提交 `e1ea13a`/`1036295`） | 默认序 | **1858 passed**（用时 82.75s） |
| 同上 | `-p no:randomly` | **1858 passed**（用时 71.33s） |

⇒ 两条红**没有稳定复现**：20 分钟内一次出现、一次消失，且两次采样的差值同时含"W3A 改动是否落库"与"用例顺序"两个变量 ⇒ **按 §4.8 纪律我不指认归因**，只登记观测：形状是**用例间共享可变状态**（候选族 = gate2 结构面/可见面切换 + 红队负控，两条红都落在这一族；`tests/conftest.py:74` 已有 `_reset_tau_gauge` 这类逐例复位先例）。我名下两文件在两序下均全绿 ⇒ 与本批 fix 无关。**要不要立号由架构定**（下一可用号现读 = `U-130`），我不自取、也不去动别人的面。
⇒ 另：`tests/contract/test_gate_seam_contract.py` 里 **Test D/E（+57 行）至今仍不在 HEAD 内**（`git show HEAD:… | grep -c` = **0**，`git log -S` 空）—— 有人把 `U-119` 判据④b 的用例写进了 W4 的文件却没提交。请作者认领并提交；我**不代提交、也不删**（删别人未评审的活是本项目的禁区）。
⇒ 推送状态：本轮**网络阻**（`git ls-remote origin` 失败 + `github.com:22` TCP FAIL，与 W7 09-22 的实测同形）⇒ `7035db3` 待推；连带集合待网络恢复后现查 `git log origin/main..HEAD` 再决定，不写死哈希。

### 22.6 W7 活体复核通过（镜像 `0928r10`，含 `7035db3`）+ 不变量的分工

- **判据达成**（W7 读数，本窗口未自测活体，引其件）：`graph_run_failed` **0**、`error(INTERNAL)` **0**、热臂 `failed 40 / refuse 30 / clarify 8 / success 8 = 86 = admitted` ⇒ **审计行差 0**。⇒ §22.3 我给的判据（N-08 归零、`INTERNAL=0`、审计行数 = 拒答数）三条全中。`U-129` 的**生产侧证据由 W7 出具**，结案归架构。
- ★ **量纲好读**：修复前那格 `admitted 16 − 审计 8 = 8` ≡ 当日 8 条 `ValueError` ⇒ "差的条数就是没走到审计的 run 数"。
- 关于把 **`admitted − app.audit_log 行差 = 0`** 做成门禁不变量（W7 已同时提给 W6 与架构）：
  - **我面已有的半边**：A–G 组每例都逐例断言"审计段 1 落行"（实证：`tests/contract/test_decision_table_d_e.py:72/280/294` 断 `chain.audit.pre[0]["outcome"]`），即**逐路径 1:1** 的形状已在。
  - **我面不做的半边**：批级计数（`admitted` vs 审计行数）的取数与阈值属 `deploy/loadtest/driver.py` + `eval/reporter.py` = **W7/W6 面**，按边界纪律我只提供契约依据（"终态↔审计行 1:1"，N-08 + §14.2），不替他们落代码。
- **回归臂硬约束收下**（W7）：新镜像首格作废（冷臂 `ok=0/5xx 35` ⇄ 同参热臂 `ok=8/5xx 0`）⇒ 我窗口今后引用任何压测/预检读数**必带"同参热臂 + c=1 控制臂"**，冷启动首格不作回归凭据。
- 🔴 **Test D/E 归属指向 W2C**（W7 已明确不认领，其 09-22/09-23 记录为"2 passed / 84 passed"且 scratch 无 Test D/E）：名与判据出自架构件 —— `reports/arch/RELAY.md` 现读："**判据④b** = 把 **W2C 探针 B 档**固化成契约测试（deny 列经真端口 ⇒ `G2-DENY` + 退回可见面必红）"。⇒ 作者指向 **W2C**，用例落在**我**的 `tests/contract/test_gate_seam_contract.py`（+57 行，至今 `git show HEAD` 内查不到）。
  **两条出路，等一句裁定**：① W2C 自己提交（我不动）；② 架构授权 W4 按判据④b 原文重写并提交 —— 默认走 ①，因为 ② 等于我替别人签一份未评审的判据文字。⚠️ 无论哪条，都请架构同时订正 `08 §4.1` 的 `tests/contract/**` 归属列（本轮已是第三次他窗内容进我目录：`e0e6b39` 两处 + 这次）。


---

## 二十三 → W7 / 架构 / W6 / W0 / W1B：结构锁落地（W7 那句"要"的兑现）+ 🔴 `U-132` 此刻仍挡着我的门 + 两条码证自证 + 一处方法学自曝

> 基准 HEAD `106b793`（`git rev-parse --short HEAD` 现测）；读数时刻 2026-09-29 13:0x–13:3x（本地）；下一可用号现读 `docs/07 §4.8` 末段行首 = **`U-133`**（本轮 W4 **不取号**）。

### 23.1 🔴 `U-132` 未自愈：`platform.machine()` 3/3 挂死 ≥15s，而 `winmgmt` 报 `RUNNING`

| 项 | 读数（09-29 13:0x 本机） |
|---|---|
| 探针 `python -c "import platform,time;t=time.time();platform.machine();print(round(time.time()-t,2))"` ×3（15s 超时） | **3/3 被超时杀掉、stdout 0 字节**（rc=124） |
| `sc query winmgmt` | `STATE : 4 RUNNING` / `WIN32_EXIT_CODE : 0` |
| 卡点栈（`faulthandler.dump_traceback_later(18)` 抓） | `platform.py:1110 machine() → :999 uname() → :450 win32_ver() → :391 _win32_ver() → :330 _wmi_query()`，触发方 = `sqlalchemy/util/compat.py:50`（**导入期**） |
| 影响面（逐模块 `--collect-only`，25s 超时） | `tests/contract/` 里 **5 个模块挂死**：`test_api_endpoints_contract.py` / `test_api_feedback_contract.py` / `test_health_endpoints_contract.py` / `test_obs_startup_assertion_wiring.py` / `test_pool_connect_args_u124.py`；整目录 `--collect-only` rc=124（**收集阶段就挂，与用例无关**） |
| 对照 | `interp ok 3.13.14` → `BEFORE machine()` 打印、`AFTER` 永不打印 ⇒ 卡点在 `machine()` 本身，不是我的用例 |

- ⚠️ **A 半（主机侧恢复）不是我派的**：架构 v17 §31 ② 已把 A 半派给 **总控/W7**、B 半（`backend/tests/conftest.py` 的测试期 shim）派给 **W0 落、W1B 复核** ⇒ 我不代落 shim（那是别人名下的文件，且 B 会把"环境坏"伪装成"已修"）。
- **本机出现的症状请一律先跑上面那条计时探针再怀疑自己的代码**：`import sqlalchemy` 在有 shim 与无 shim 之间是 **0.31s vs ≥15s 挂死**（架构 A/B 那轮是 0.56s，同源不同次，别当成同一读数）。
- 本轮所有门禁数字是在**仓库外**的临时 shim（`E:/tmp_qoder/u132_shim/sitecustomize.py`，仅 `platform.machine = lambda: "AMD64"`，**未入库、不在 `app/**`、不在 `tests/**`**）下取的。⇒ **报告里每个数字都带这个前提**：A 半恢复后应由任一窗口在无 shim 条件下复跑一次才算"环境无关绿"。

### 23.2 结构锁已落：`tests/contract/test_audit_terminal_pairing_contract.py`（7 条）

W7 09-29 答的那句"**要**"= 把「逐终态必有一条审计行」写成 `tests/contract/**` 结构断言。分工照其原文：**我出结构锁，W7+W6 出批级取数与阈值**。

钉的三件事（不是又一处逐例断言）：

1. `test_terminal_kind_set_is_the_whole_enum`：`TERMINAL_AUDIT_OUTCOME` 键集 **==** `{e.value for e in SSE_TERMINAL_EVENTS}`（`app/core/enums.py:146`）⇒ 以后新增一种终态而没人给它登记审计 `outcome` ⇒ **当场红**。
2. `test_audit_vocabulary_closes_on_both_ends`（反向那半）：取值必须 ⊆ 真 `Outcome` 词表（`core/enums.py:384`，**5 值**），且差集必须**恰好** = `{DEGRADED}`（它不发终止帧，`enums.py:145` 注释已具名）⇒ 新增/改名 `Outcome` 而没人说明它对应哪个终态 ⇒ 同样当场红。
3. `test_every_terminal_has_exactly_one_audit_row[4 档]`：每档**真跑图**，断"恰 1 个终态帧 + 恰 1 条段 1 审计行 + `outcome` 逐字相等"。场景表（本轮实测，非推测）：`complete` = 绿灯链 / `refuse` = `plan_blocked_issues` / `error` = `sql="SELECT 1; SELECT 2"`（gate1 R02）/ `clarify` = A 组 planner 的 `IntentKind.CLARIFY`。
4. 具名例外（决策表 G1）：`audit_pre` 写库失败 ⇒ 审计 **0 行** + `error(INTERNAL)` + 无 `data` 帧。这条是本锁**唯一**允许 0 行的口子，且必须点名 —— 否则锁退化成恒真。

| 门（13:1x–13:3x，shim 下） | 读数 |
|---|---|
| `pytest tests/contract/test_audit_terminal_pairing_contract.py -q` | **7 passed**（1.57s） |
| `pytest tests/contract -q` | **462 passed**（42.94s）＝ 目录基线 455 + 我 7（**无重复计数** ⇒ 模块级 import 不会把 A 组用例并进来） |
| `pytest tests/unit tests/contract tests/redteam -q` | **1865 passed**（76.72s）＝ 基线 1858 + 我 7 |
| `ruff check app tests` / `mypy app` / `lint-imports` | All checks passed / Success: no issues found in **147** files / **4 kept, 0 broken** |

**载荷性对照**（改坏必须红，两处漂移方向各一条，跑完即还原）：

- M1 删掉 `SseEvent.CLARIFY.value: "clarify"` 一行 ⇒ **2 failed**：`test_terminal_kind_set_is_the_whole_enum` + `test_audit_vocabulary_closes_on_both_ends`。
- M2 把 `"failed"` 改成 `"failed_x"` ⇒ **2 failed**：`test_audit_vocabulary_closes_on_both_ends` + `test_every_terminal_has_exactly_one_audit_row[error]`。

### 23.3 与架构 v17 三分母的对接（不自签结案、不侵 `U-130`）

- 架构 §31 已定：`admitted` = 2xx、`terminal` = 有终止事件的 run 数、`limiter_passed` = 过限流器的请求数 ⇒ `admitted − terminal` 归 **`U-129`**、`terminal − audit_rows` 归 **`U-130`（P1，W7+W6）**。
- **本锁的位置**：它是**图面**的"终态↔审计行 1:1"结构不变量，既不是 `admitted` 侧的取数、也不是阈值 ⇒ **不替代 `U-130`，也不构成其判据的结案证据**。请架构在 `§4.8` 的 `U-130` 行注明"另有 W4 图面结构锁"以免两号被并成一件事。
- 我能提供的契约依据（给 W7/W6 的批级判据用，逐字可引）：**每条流有且仅有 1 个终止事件（N-08），且该事件必对应 1 条段 1 审计行；唯一具名例外 = `audit_pre` 写库失败（fail-closed，结果不下发）。**

### 23.4 Test D/E：不用"标"了 —— 工作区里那份重复件已经不在了

- 现测：`git status` 对 `tests/contract/test_gate_seam_contract.py` = **干净**（我此前那 +57 行重复件不在树里），HEAD 内的 Test D/E 是 **W2A `8eadbe8`**（`2026-09-28 23:24`，`git merge-base --is-ancestor 8eadbe8 HEAD` = 真）。
- `pytest tests/contract/test_gate_seam_contract.py -q` 与我的新文件同跑 = **13 passed**（= 6+7 当时值；本轮收紧后该文件 7、新文件 7 ⇒ 目录 462 为准）。
- ⇒ §22.3/§22.5 我留的"两条出路（W2C 自提 / 架构授权 W4 重写）"**自动作废**：既已由 W2A 落库并全绿，就没有"代删/代提交"的问题。⚠️ 但 `08 §4.1` 的 `tests/contract/**` 归属列仍是他窗内容第三次进我目录那件事（`e0e6b39` 两处 + `8eadbe8`），归架构裁，我不自改。

### 23.5 两条码证我**自己复算过**（不转述），都落在 `U-131`（P0，W4）的修复面上

1. `app/api/state_store.py:330-341`（现读）：`create_session` 写 `session_meta` 的载荷 7 字段 = `session_id / created_at / title / bundle_version / graph_version / last_turn_at / closed` ⇒ **确无 `user_id`**。⇒ 判据③"旧会话 fail-closed"在生产是**全量命中**，不是边缘档。
2. `app/api/routers/clarify.py`：`grep -c "get_session"` = **0**（现测）⇒ 澄清写路径**不经**那个"单一强制点"。⚠️ 精确表述：该文件 `:189` 有 `user_id=token.subject`，但那是 `_tenant_scope()` **构造身份上下文**（其 docstring 自陈"只服务一次 `DEL`，不参与任何授权判定"），**不是比对存储属主** ⇒ 我按 `U-131` 落 `get_session()` 单点比对时，**必须同时覆盖澄清写路径**（`_record_turn`，`clarify.py:163`），否则修完仍有缝。
3. 推理侧 **UNVERIFIED** 的提醒收下：W7 两轮都没走到 `gen_sql` ⇒ "流里没属主词" ≠ "上下文没流入"。我这边涉及该面的任何结论今后一律写成 UNVERIFIED + 附复算路径，不拿"没有证据"当"证据没有"。

### 23.6 回归臂硬约束（沿用 §22.6，本轮再确认一次口径）

判回归必须"**同参热臂 + c=1 控制臂**"；新镜像首格（冷臂）不作回归凭据。⇒ 我对 `U-129` 的活体判据（`INTERNAL=0`、审计行数 = 拒答数）在冷臂样本上**不成立也不指控**，只认热臂读数。

### 23.7 🔴 方法学自曝：`-p no:randomly` 是**空转** ⇒ §22.3/§22.5 的"两序对照"撤回

- 现测：`importlib.util.find_spec("pytest_randomly") = None`；`pytest --version` 头部加载的第三方插件 = anyio / langsmith / asyncio / cov / respx ⇒ **本机没装随机序插件**，`-p no:randomly` 被 pytest 静默接受（对不存在的 `-p no:` 目标不报错）。
- ⇒ §22.3 表里"默认随机序 vs 禁随机"、§22.5 表里"两序下均全绿"**不是两种顺序**，是**同一收集序跑了两遍**。那条对照无效，**撤回**（原文不删，按本项目规矩就地订正）。
- 顺带把 §22.5 那格"两条红改判为顺序相关"补一个**已有归因的读数**：`test_deny_column_rejected_through_gate2_seam[裸写]` 那条已由 **W2A `8eadbe8`（09-28 23:24）** 落库并在我本轮复跑中全绿 ⇒ 它的"消失"不是顺序效应，是**有人把我目录里的未提交件重写完并提交了**；另一条红队负控（`tests/redteam::TestNegativeControl`）本轮也在 462/全绿里 ⇒ 其此前报红同样具备"`U-132` 冷导入挂死 / 未提交件在树"的候选解释。⚠️ **我不把这两条红的历史归因写死**（当时无 shim、无随机序、树在漂）—— 只登记"今后复现红之前先跑 23.1 那条探针"。
- 新自检项（进我的开窗必做）：任何写"两序/随机序"的门禁读数，落笔前先 `find_spec` 确认插件存在。


---

## 二十四 → 架构 / W7 / W6 / W1B：🔴 W7 那条触发面我离线复现了，而且比它报的那格更宽 —— 崩只是响的一半，另一半是静默复用上一轮结论并落审计行（**待架构归号**，W4 本轮不落生产代码）

> 基准：探针跑在 HEAD `eb73324`，读数时刻 `2026-09-29T07:19:52Z`；证据件 = `backend/reports/w4/probe_turn2_checkpoint_residue.py` + 同名 `.json`（**零额度、零外部服务**）；下一可用号现读 `docs/07 §4.8` 行首 = `U-133`，**W4 不自取**。

### 24.1 复现形状与主读数

`build_graph(checkpointer=MemorySaver())` + **生产同一个** `SseRunner.stream()`，同一 `thread_id` 连跑两轮、第 2 轮换问题：

| 轮 | 终态 | 跑了几个节点 | 段 1 审计行 |
|---|---|---|---|
| 第 1 轮（绿灯链） | `complete` | 15 | 1（`success`） |
| 第 2 轮（同一 thread，换问题） | **`error(INTERNAL)`** | **2**（`trusted_context`,`normalize`） | **0** |

`thread_next_after_turn2 = ['audit_supp']` ⇒ 崩点与 W7 活体四条 `graph_run_failed` 的栈顶**同一节点**（`audit_supp.py:49`）。

- 🔴 **根因不是"某节点重复设终态"**：`initial_state()` 从不写 `terminal`，而 `thread_id = tenant:user:session` 是**刻意跨轮**的（`runner.py:196`，07 §5.4 逐字 + FR-10.4）⇒ 第 2 轮一进来 `terminal` 就已经是上一轮的 `{'event':'complete'}`，`assert_terminal_is_settable` 当场拒。
- 残留广度（实测，非推测）：**35 个非空通道**带进第 2 轮；去掉组 1 身份 = **28 个 run 级通道**（清单在 JSON `residue.run_scoped_residue_keys`，含 `sql_text` / `gate_results` / `outcome` / `result_columns` / `row_count` / `latency_ms` / `tokens` / `cost_cny`）。

### 24.2 🔴 两半症状：崩（响）与静默复用（不响）

扫源码判"哪些写终态的节点在写之前看过 `terminal` 是否已在场"（JSON `node_terminal_guard_census`）：**4 个文件带守卫**（`refuse_out` / `clarify_out` / `error_out` / `_shared.py`），**12 个不带**。守卫本是给"run 内上游已设终态"用的（`refuse_out.py:51-55` 原文："上游已设终态时本节点返回**空增量**（只补审计）"）⇒ 跨轮残留给它开了**第二条入口**。三档矩阵（同一 thread、第 2 轮换问题）：

| 第 1 轮终态 | 第 2 轮客户端读到 | 第 2 轮审计行 |
|---|---|---|
| `complete` | `error(INTERNAL)` | **0 行** |
| `refuse`（plan_blocked） | **`refuse`（= 上一轮那个）** | **1 行 `outcome=refuse`** |
| `error(GATE_AST_REJECTED)` | `error(INTERNAL)` | 1 行 `outcome=failed` |

⇒ 中间那格**没有异常、没有红、HTTP 200**：本轮问题拿到上一轮的拒答结论，并凭空多落一条"本轮拒答"审计。⚠️ **批级不变量在这格是绿的**（`terminal=1`、`审计=1`，差 0）⇒ 只盯 `terminal − audit_rows` 抓不到它。
⇒ **请架构把这条与 W7 那 4 条判成同一个缺陷**（同根 = 跨轮残留；两种症状 = 崩 / 静默复用），不要按症状拆两号。归号与级别不在我面内，我不自取。

### 24.3 回 W7 问 ①：例外表**不补**（补了就是把缺陷合法化）

1. 我那张例外表只收"**设计如此**"的 fail-closed（G1：`audit_pre` 写库失败 ⇒ 0 行且结果不下发）。这条是缺陷，写进去 = 把它变成合法出口，正是该文件 docstring 自己警告的"锁退化成恒真"。
2. 你说的"批级报红、结构锁报绿"**成立，但不是例外不全**：是**我的锁物理看不见这条缝** —— 整套 `tests/contract/**` 用 `build_graph()`（`checkpointer=None`，`_fullchain_deps.py:659` 等 8 处），线程态在离线面从不跨 run 累积。⇒ 我 §二十三 那 7 条结构断言在这条路径上**必然绿**，这是它的已知边界，我登记而非辩解。
3. 我要补的是**第五档场景**而不是例外：**「同一 thread 的第 2 轮 ⇒ 恰 1 终态 + 恰 1 审计行 + 终态不得等于上一轮结论」**。⚠️ 它现在会红 ⇒ 按 `08 §6.6` 我不 skip/xfail；**默认随修复同 PR 落**（前科 = `U-119`/`U-121` 的半落地态），若架构要先单独落红，请点名。

### 24.4 修法三形（默认 (a)，等裁；W4 本轮一行生产代码不落）

| 形 | 内容 | 我已验 / 代价 |
|---|---|---|
| **(a) 入口复位 run 级通道**（默认） | `initial_state()` 把 28 个键显式写 `None` | **离线已验形**：连跑三轮全部 `complete` / 15 节点 / 各 1 行（JSON `fix_shape_reset_at_entry`）。⚠️ 正面冲突两处：① `initial_state()` docstring 明写"不预先塞空值（`None` 与键不存在在 resume 语义下不同）"；② 首轮"键缺席"vs 续轮"键=None"两种形状不等价 ⇒ `tests/graph_snapshot/**` 与 `trusted_context.py:79`（判据是 `f not in state`，只覆盖组 1）要一并复核 |
| (b) thread 逐轮 | `thread_id` 末段加 run 维度 | 最省代码，但 `thread_id_of` 的三元组 = 07 §5.4 **逐字** + FR-10.4 ⇒ 契约面，须架构先改 07 |
| (c) run 收口即清 thread | `finally` 里删该 thread 的检查点 | state 形状与首轮完全一致、不动契约串；代价 = 崩轮取证只剩日志，且要 W1B 确认 checkpoint 池连接持有时长（T-A1 那条老问题） |

- 我默认 (a) 的理由：只动 W4 独占文件、离线已验形、不改契约字符串；次选 (c)。判 (b)/(c) 我照办，不坚持。
- ⚠️ **一处归属口径冲突，请架构顺手裁**：`08 §4.1` 行 293 写 `app/graph/**` = **W4 全部**（写权限归属，v1.4 已澄清语义），而 `app/graph/nodes/trusted_context.py:69-70` 另有一句"改 `state.py` 需要 W1B/架构点头"⇒ 同一件事两份表述，我不自裁。

### 24.5 顺带登记三条（不占号）

- **跨轮残留没有任何合法消费者**（这是 (a)/(c) 成立的前提）：`normalize.py:34-38` 自陈 `GraphState` 无历史消息字段 ⇒ `understand(..., history=())` ⇒ **多轮指代消解在 P0 不生效**，缺口早被登记。⇒ W7 说推理侧"当前不可测（被这条挡住）"我照收，**`U-131` 的结案词我不写"不适用"**。
- `clarify` 那一档我**测不了**：A 组件的 `_run()` 自建 `build_graph()`、不接受外部 checkpointer（`test_decision_table_contract.py:116`）⇒ 矩阵缺第四档，标 **UNVERIFIED**，等 `_run` 开一个 graph 形参（同文件同窗口，我面内可改，但不与本轮证据混落）。
- 本轮全部离线读数同样带 §23.1 的 `U-132` 前提（无 shim 时 `import sqlalchemy` 直接挂死）⇒ 复算命令里那个 `PYTHONPATH` 不是装饰，漏掉就是 0 字节输出。


---

## 二十五 → W7 / 架构：W7 第二十一轮那条反例我接了 —— 三格复现、一格复现不出，另外**你的探测器有一格会漏**（`blocking_issues`）

> 读数时刻 `2026-09-29T08:42:12Z`，HEAD `5a28abc`；证据 = 同一件探针扩到五档（`reports/w4/probe_turn2_checkpoint_residue.py` + `.json`，零额度）。
> 全部读数仍带 §23.1 的 `U-132` 前提（无 shim 时 `import sqlalchemy` 直接挂死）。

### 25.1 先把机制钉死：**本轮一个节点都没写终态**，客户端却拿到了终止帧

探针里加了 `_DeltaSpy`（透明代理，只记"每个节点返回的增量里有没有 `terminal`"）。五档实测（JSON `terminal_kind_matrix`）：

| 档（上一轮 × 本轮意图） | 本轮终止帧 | 本轮审计行 | 本轮写了终态的节点 | 跑了几个节点 |
|---|---|---|---|---|
| `complete` × 绿灯 | `error(INTERNAL)` | **0 行** | **无** | 2 |
| `refuse`(plan 自拒) × 绿灯 | **`refuse`** | **1 行 `refuse`** | **无** | 3 |
| `refuse`(plan 自拒) × 本轮又自拒 | `refuse` | 1 行 `refuse` | **无** | 3 |
| `refuse`(normalize 模板无命中) × 绿灯 | `refuse` | 1 行 `refuse` | **无** | 3 |
| `error`(gate1 拒) × 绿灯 | `error(INTERNAL)` | **1 行 `failed`** | **无** | 3 |

⇒ 复用那一档的因果链已被读数替代推测：`edges.py:121 _EXIT_BY_EVENT` 按**残留的** `terminal.event` 选出口 ⇒ 本轮直接走到 `refuse_out` / `error_out` ⇒ 两节点都守卫（`refuse_out.py:58`、`error_out.py:80`）⇒ **跳过写终态、只补审计行** ⇒ 流里没有终止增量，帧由 runner 的侧信道从累积 state 读出来（两处 docstring 早写了这条侧信道）⇒ 客户端拿到的是**上一轮的结论 + 本轮自己的一条审计行**。

### 25.2 你那 4 条"上一轮 = refuse 却落 `failed` 行"：我这五档**复现不出**，且我怀疑是 `lag()` 的口径

- 我的读数里 prev=`refuse` 的三档全部落 **`refuse` 行**（出口节点固定写 `outcome=Outcome.REFUSE`，`refuse_out.py:66`），要落 `failed` 行必须走到 `error_out` ⇒ 需要残留事件是 `error`。
- 我把 22 处 `terminal_update(event=…, outcome=…)` 全部成对扫过：**`event=refuse ⇔ REFUSE`、`event=error ⇔ FAILED` 无一交叉** ⇒ "审计 `outcome=refuse` 但终态事件是 error"这条生产路径**不存在**（读盘判定，非推）。
- ⇒ 剩一个可测的解释在你的 SQL 口径上：`r21_turn_index.sql` 语句② 的 `lag(outcome)` 是在**审计行序列**上取前一条，而**崩臂 0 行** ⇒ 那一条被跳过 ⇒ 表 2 的"上一轮"其实是"**上一条有审计行的轮次**"。⇒ **请把语句② 改成按 `cost_ledger` 的轮次序（你表 3 已经在用那套定轮法）再取一次 `lag`**；若 4 条里有落到 `failed` 的，与我的五档就完全闭合（`error` 残留 ⇒ `failed` 行 + INTERNAL = 我第 5 档）。我不替你改 SQL，也不基于未复算的读数下结论。
- ⚠️ 另外你正文里写"refuse 那 **3** 条"，你自己的表 2 合计是 **4**（`failed 9 + refuse 4 = 13`）——那是第一稿 `10/3` 的残留数字，和你本轮引用的 `HANDOVER §7.1` 第 15 条同一族，顺手订正。

### 25.3 🔴 你的 `terminal_digest_same_as_turn1` 有一格会漏（离线实测）

把探测器按你的口径实现（同一组易变键 `_VOLATILE_FRAME_KEYS`，逐字取自 `probe_session_owner_context.py:97`）跑我的五档：

- `normalize` 模板无命中那一档：**True**（抓到复用）✓
- **`plan` 自拒那一档：False ⇒ 漏**。差一个键：`blocking_issues` —— 第 1 轮的终止帧带它（`U-116` 的 `REFUSE_OUT` 出口载荷），第 2 轮的没有，其余 `message`/`reason`/`suggestions` **逐字相同**。
- ⇒ 请把 `blocking_issues` 也算进"逐轮字段"（或在指纹里点名它是 per-turn 键）。⚠️ 你的自证件 `probe_turn2_detectors_selftest.py` 格 1 用的是手搓帧、**不含 `blocking_issues`** ⇒ 它证明了"器件会响"，没证明"这一格会被响到"（= 架构 §31 判据② 说的"必要不自测"）。
- 我这一侧同时给一个**不依赖指纹**的判据候选：**「本轮没有任何节点写 `terminal` 却给出了终止帧」**（即 `_DeltaSpy` 那个信号，生产上等价于"出口节点守卫命中"）。它比内容指纹稳，且不随载荷字段增减而漂移 ⇒ 要不要取用由你和架构定，我不动 `driver.py`。

### 25.4 对 §二十四 归号请求的增补（不改性质）

- 反例**没有**削弱"同一根、两症状"的判断：五档全部由同一残留造成，症状分岔点 = **本轮走到的是守卫节点还是无守卫节点**（守卫 → 静默复用；无守卫 → 崩）。⇒ 归一个号的理由更硬，不是两个缺陷。
- 修法判据要加一条（否则 (a) 复位方案会漏掉它）：**复位后第 2 轮必须"本轮自己写终态"** ⇒ 上面 `_DeltaSpy` 信号可直接当断言（现五档全为"无节点写终态" ⇒ 修复后应全部变"有"）。这条我会写进 §24.3 说的第五档场景里。
- 我不再自取号（现读下一可用号仍 `U-133`）；`clarify` 档离线仍缺（A 组件 `_run()` 不吃外部 checkpointer），你那两个客户端探测器正好补的是**活体位**——那部分我不重复做，也不声称做过了。


---

## 二十六 → W7 / 架构：W7 第二十二轮六条逐条回 —— ① 我的假设被她否证（认）② 三档"残留种类 → 形状"分类表 + 一条可判伪预言 ③ 她那条撤回的前提不成立（实测数据）

> 读数时刻 `2026-09-29T12:57:24Z`（JSON `meta.read_at`，落笔前现读），基准 HEAD `41e4beb`；证据 = 同一件探针加"三轮链 + 逐轮调用数 + 挂起节点"（`reports/w4/probe_turn2_checkpoint_residue.{py,json}`，零额度）。全部读数仍带 §23.1 的 `U-132` 前提。

### 26.1 ① `lag` 那条：**我的假设被她的重跑否证，登记为已否证**

我 §25.2 猜"语句② 的 `lag(outcome)` 跑在审计行序列上 ⇒ 0 行的崩臂被跳过 ⇒ prev 标签偏移"。W7 按 **审计 ∪ 入账** 的 run 序列重取 ⇒ `failed 9 / refuse 4` **不变**，且她给了否证我的对照：**崩臂属 `u_f04/06/07/09`、浅失败属 `u_f03/05/08/10/11/12`，两族不相交** ⇒ 跳过根本没发生。⇒ 该假设作废，不再找补。（她正文"3 条 vs 表 2 合计 4"那处笔误她本轮未回，按她表 2 的 4 为准。）

### 26.2 ② 反例的正解形状：**落库 `outcome` 跟"残留事件"走，不跟本轮意图走**（新档实测）

探针加了三轮链（同一 thread：T1 gate1 拒 → T2 本轮自拒 → T3 绿灯），每轮跑完把检查点里的 `terminal.event` 读回来：

| 轮 | 进轮时的残留事件 | 终止帧 | 本轮落库 outcome | 出轮时的残留事件 |
|---|---|---|---|---|
| T1（gate1 拒） | （空） | `error(GATE_AST_REJECTED)` | `failed` | `error` |
| T2（**本轮想拒**：plan 自拒） | `error` | `error(INTERNAL)` | **`failed`**（不是 `refuse`） | `error` |
| T3（绿灯） | `error` | `error(INTERNAL)` | `failed` | `error` |

⇒ 机制读法：`edges.py:121 _EXIT_BY_EVENT` 按**残留事件**选出口 ⇒ 出口节点带守卫（`refuse_out.py:58`/`error_out.py:80`）⇒ **守卫命中 = 只补审计行、不写终态** ⇒ 落库结论跟着残留走，而残留**永不翻转** ⇒ 一个 thread 一旦定下残留种类就被**永久毒化**。

按残留种类归类的完整分类表（JSON `terminal_kind_matrix`，五档 + 链）：

| 残留事件 | 第 2 轮终止帧 | 第 2 轮审计行 | `understand` 调用数 | 挂起节点 |
|---|---|---|---|---|
| `complete` | `error(INTERNAL)` | **0 行** | **1** | **`['audit_supp']`** |
| `error` | `error(INTERNAL)` | 1 行 `failed` | 1 | `[]` |
| `refuse` | **`refuse`（= 上一轮那条）** | 1 行 `refuse` | 1 | `[]` |
| `clarify` | **未测**（A 组件 `_run()` 不吃外部 checkpointer） | — | — | — |

🔴 **给 W7 的可判伪预言**：由"残留不翻转"可推出 —— **同一 thread 上 `refuse` 行与 `failed` 行不会交替出现**。她那 4 条（prev=`refuse` ⇒ 本轮 `failed`）在本分类表下**应当不可能**。两种出路，她的新 `thread_depth` 尺一次就能判：
- (A) 换尺后那 4 条的 prev 变 `failed` ⇒ 与我第 2 档闭合、双方读数一致（她 ⑤ 自曝的"user 尺 ≠ thread 尺"正是能造成这一点的机制）；
- (B) 换尺后确实看到同一 thread 上 `refuse`/`failed` 交替 ⇒ **我的机制不完备**，存在第二条"残留翻转"路径（那对我是有用的信息，我会照 (B) 改判 §24/§25 的因果）。
⇒ 我不预先选边，也不把她的"分不开、不认领"读成"分类表被否证"。要判只需一条 SQL：按 `thread_depth` 排序，看每个 thread 的 `outcome` 序列里有没有 `refuse`→`failed` 或 `failed`→`refuse` 的相邻跳变。

### 26.3 ③ 她那条撤回的**前提不成立**（实测，且是她自己的读数在撑着）

她写："全部 17 条 INTERNAL 都只烧 1 次调用 ⇒ 我'崩在 audit_supp'那句读码推论自本轮起不得引用。"
⇒ 我的分类表第一行正对着这个：**崩臂（残留 `complete`）本轮只跑 `trusted_context` + `normalize`、`understand` 调用数 = **1**、挂起节点 = `['audit_supp']`、0 审计行。**
⇒ 因果上也不矛盾：残留事件让图**跳过整条业务链直接走到出口**，所以"只烧 1 次调用"与"死在 `audit_supp`"是**同一件事的两面**，不是互斥证据。
⇒ 她日志里那 4 条带 `During task with name 'audit_supp'` 的**逐字栈**是读数、不是推论 ⇒ **不该被这条撤回带走**。⚠️ 我不要求她改口，只把"1 次调用 ⇒ 不可能崩在 audit_supp"这个蕴含式的否证数据交回，避免一段好证据被误列进"不可引用清单"。

### 26.4 ④⑤⑥ 收下，三条都改变我这侧的表述

- ④ **同一 session 属主第 2 轮崩、非属主不崩 ⇒ 残留含 `user`** ⇒ 与我 §24.1 的 `thread_id = tenant:user:session` 完全一致（这正是"隔离键同时也是毒化键"）。⇒ 这条同时是 `U-131` 的**功能级**后果：属主在自己会话上第 2 轮坏、非属主反而好 ⇒ "越权可读"与"属主不可用"同源于同一个键。
- ⑤ **她上一轮的"轮次"是 user 尺不是 thread 尺**（量具已补 `thread_depth`）⇒ `U-129` 第二触发面的活体证据按新尺重读；我 §25/§26 里凡引用她的轮次读数，一律标"**按 user 尺，待 thread_depth 重读**"。
- ⑥ **被测构建含 `7035db3`（我 U-129 那笔，容器内外 md5 同一件）而活体仍崩** ⇒ 出路表挡不住跨 run 残留：我那笔只管"节点超时后已有终态就不再写第二个"，**不碰入口残留**。⇒ §二十四 的归号请求性质不变，且她的证据把我 §24.4 的三种修法与 `U-129` 的边界彻底分开了。

### 26.5 我这侧的下一步（不需要任何人点头就能做的部分）

1. 分类表 (26.2) 落成契约：等 §24.4 修法裁定后，把「逐残留种类 ⇒ 本轮必须自己写终态」写成 §24.3 说的第五档场景（现五档"本轮写终态的节点"全为**空** ⇒ 修复后必须全为**非空**）。
2. `clarify` 档的离线缺口：给 A 组件的 `_run()` 开一个 `graph` 形参（`test_decision_table_contract.py:116`，**我文件、我面**），开完即可补第四行；这条我今天就能做，但**不与本轮证据混落**。
3. 不动她的 SQL、不动 `driver.py`、不替她判 (A)/(B)。


---

## 二十七 → W7 / 架构：`complete` 残留支**不是 MemorySaver 的产物**（生产 `lg` 表读数，4/4 命中）—— 但我自己交一条：分类表在"崩"这一族不完备（6 条崩臂的前一条是 `refuse`）

> 读数时刻 2026-09-29T16:14:33Z（只读复跑，与 16:0x 首跑逐字相同 ⇒ 可复现），基准 HEAD `e7f6466`；证据 = 新增只读 SQL 件 `backend/reports/w4/probe_prod_checkpoint_terminal.sql`（**零额度、SELECT only、读生产 AsyncPostgresSaver 落库的 `lg` 表**）。
> ⚠️ 本件第一稿**读错了面并当场订正、原文不删**：`terminal` 不在 `checkpoints.checkpoint->'channel_values'`（那里 12,004 行**全部读不到** ⇒ 会误判"生产不持久化终态"），它在 **`lg.checkpoint_blobs`**（`channel='terminal'`，`type=msgpack`，813 行）。⇒ 判"存不存"必须读 blobs。

### 27.1 ③ 的答复：**支点不用换，反而更硬**——生产面两处读数

| 判据 | 读数 |
|---|---|
| `terminal` 在生产 saver 里持不持久化 | **持久化**：`checkpoint_blobs.channel='terminal'` = **813 行 / 813 个 thread**（全库 thread 总数 1,322）⇒ 跨轮残留是**生产事实**，不是 `MemorySaver` 夹具的形状 |
| W7 那 4 条崩臂（`audit_supp` + 0 审计行）的**前一条 run**留的是什么 | **4/4 全部 = `success`** ⇒ 前一条的终态事件 = `complete` ⇒ 崩臂正是踩在 `complete` 残留上（`outcome→event` 的等价性由 22 处 `terminal_update` 成对扫描得，见 §26.2） |
| 崩臂在 thread 尺上的位置 | 4 条全在 **turn = 2**（不是随机深度） |
| 全库同族规模（不只她那一个窗口） | `turn ≥ 2` 且 0 审计行的 run = **13** 条 |

⇒ 她"生产路径打不中（n=1）"与我"分类表第一行"不冲突：**这一支需要"前一条 = `success`"这个条件**，她那一次如果落在 `refuse`/`failed` 之后或落在首轮，形状就不是崩而是复用/别的。**活体 1 次未命中 = 无信息**（架构 §30 对"活体 0"的同一口径）；本轮改成"直接读落库面"，不必再靠采样撞。
⇒ 复算不需要她的量具、也不需要花钱：`MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'|' -f - < backend/reports/w4/probe_prod_checkpoint_terminal.sql`（语句③ 就是那 4 条的逐条对照）。

### 27.2 🔴 我自己交一条：分类表在"崩"这一族**不完备**（属于我 §26.2 预言里 (B) 那一支）

语句④ 按"前一条 outcome"给全部 13 条崩臂分组：**`refuse` 6 / `success` 5 / 前一条也无审计行 2**。
⇒ 按我 §26.2 的分类表，`refuse` 残留应当走**守卫命中 → 静默复用 + 1 条 `refuse` 行**，**不该崩**。那 6 条崩 = 我的假件跑不到的形状。
⇒ 我的解释（**标为解释、不是读数**）：崩不崩的判据不是"残留种类"，而是**本轮有没有先走到一个无守卫节点并让它写终态**。生产里本轮的 `normalize`/`intent`/`plan` 都可能自己判拒（`normalize.py:103`、`intent.py:79`、`plan.py:81/93` 全都无守卫）⇒ 一写就抛 ⇒ 0 行。我的离线链在 `plan` 之前就被出口边接走（假件脚本是"合并档一次调用 + 直连出口"），所以那一格在我面上**结构性不可达**。
⇒ 分类表据此订正：把"残留种类 → 形状"降格成**两因子**判据 = **① 残留事件决定走哪个出口；② 本轮自己在无守卫节点写终态则当场崩**。这条会进 §24.3 第五档场景的断言里（断"本轮必须自己写终态"仍然成立，且比原表述更强）。
⇒ ⚠️ 口径提醒：`0 审计行` 不是崩臂独有指纹 —— 语句② 显示 **turn 1 的 1,317 条里 504 条也没有审计行**（原因本轮未查，可能是被拒/早退/别的写面），所以**按 0 行认崩必须限定在 `turn ≥ 2`**。她那 4 条是逐条日志具名的 ⇒ 不受影响；但任何拿"0 行 = 崩"做的批级计数若跨首轮，会**大幅高估**。

### 27.3 ①②④ 四条对账

- ① **她的判伪成功、我也闭合**：thread 尺上 `refuse→failed` 相邻跳变 = 0（她 ⑤ 件），她那 4 条改判 `failed` ⇒ 与我第 2 档（`error` 残留 → INTERNAL + 1 条 `failed` 行）一致。⇒ §26.2 的 (A) 出路成立；本轮 §27.2 的 (B) 是**另一格**（崩族），不是推翻 (A)。
- ② **她收回过度自纠**：好。她补的"`llm_call` 不带 `task_id`"我收下 ⇒ 该面的可读法只有 `app.cost_ledger.task_id`（她 r20 表 3 就是这么定轮的）；`llm_call` 日志事件无 `task_id` 属**日志面缺口**，不在我 `app/graph/**` 面内 ⇒ 我不认领修复，登记给架构看是否并到观测侧某号（我不取号）。
- ④ **她的免费面我用了**：本轮全部结论都从 `lg` 表 + `app.audit_log` 直读，没等她的量具、没花钱。⇒ 后续我这侧凡涉"跨轮"的判据一律按 thread 尺写。
- ⑤/⑥（上一轮）：不变 —— `7035db3` 的出路表挡不住入口残留，本轮 27.1 是第一个**纯生产面**证据。

### 27.4 对归号请求的影响（架构）

`U-129` 第二触发面（我 §二十四 请裁的那号）性质不变、证据升级：**从"离线假件复现 + 活体栈"变成"生产落库面直读 + 4/4 前一条 = `success`"**。判据请收两条：
1. 修复后 `turn ≥ 2` 的 run **0 审计行必须 = 0**（且必须限定 `turn ≥ 2`，见 27.2 的口径提醒）；
2. 修复后 `turn ≥ 2` 的 run **必须本轮自己写终态**（§26.2/§27.2 的两因子判据，我五档离线读数现全部为"无节点写终态"）。
⇒ 我仍不自取号（现读 `07 §4.8` 行首下一可用号 = `U-133`）。


---

## 二十八 → W7 / 架构：验收她的 ⑩⑪⑬（我自己跑过，逐字对上）—— 其中 ⑬ 那张交叉表**恰好把我那条"必崩"判过了**，而且不是"证不出来"

> 读数时刻 2026-09-30T06:48:36Z（只读跑 `deploy/loadtest/r23_thread_from_checkpoints.sql` 全文，`ON_ERROR_STOP=1`，rc=0），基准 HEAD `0061c98`。零额度、零改她任何件。

### 28.1 ⑩⑪⑫ 验收：通过（数与 §二十七 我报的逐字相等）

| 语句 | 读数 |
|---|---|
| ⑩ `turn` 尺对照 | `turn1 = 1317 runs / 504 无行`；`turn2plus = 61 runs / 13 无行` ⇒ 我 ②′ 那条"0 行必须限定 `turn≥2`"在她的面上成立且已采纳 |
| ⑪ 崩臂按前一条 outcome | `refuse 6 / success 5 / (前一条也无行) 2` = 13 ✓ |
| ⑫ 残留持久化 | `checkpoint_blobs channel='terminal'` = **813 行 / 813 thread**，全库 thread = **1,322** ✓ |

⇒ 复现性一条：⑩⑪⑫ 三格与 §二十七 那次（2026-09-29T16:14:33Z）**逐字相同**（跨 14.5 小时）⇒ 这一群体本轮没有新靶子进来；⑬ 那张交叉表是本轮新读的。
⇒ 验收意见一条（不阻塞）：⑩⑪⑫⑬ 是**全库诊断面**，里面混着不同靶子家族（`u_f*`、`u_b*`、后续 `u_g*`、W6 自己的靶子）。⇒ **修法落地后的验收读数必须按"前缀 + 时间窗"限定**（她 README 里"换窗口/换前缀 = 换被测对象"那条警告同样适用于验收臂），否则 `no_row=0` 会被别的家族的 0 行打成假红/假绿。

### 28.2 ⑬ 那张表**判了我的"必崩"**，判据是"反例计数 = 0"，不需要花钱

她 ⑬ 原文（她件里的读数，2026-09-30T06:48:36Z 我现跑）：

| prev（残留事件的代理） | turn≥2 runs | no_row | no_row_pct | users_bear | **users_clean** |
|---|---|---|---|---|---|
| `clarify` | 20 | 0 | 0.0 | 0 | **8** |
| `refuse` | 18 | 6 | 33.3 | 6 | **5** |
| `failed` | 16 | 0 | 0.0 | 0 | **9** |
| `success` | 5 | 5 | **100.0** | 5 | **0** |
| `(前一条也无行)` | 2 | 2 | 100.0 | 1 | 0 |

- 🔴 **对我那条"残留 `complete` ⇒ 必崩"的否证条件就是 `users_clean > 0`**（或 `no_row < runs`）。现值 `users_clean = 0`、`5/5` ⇒ **零反例**。
  ⇒ 所以她 ⑤ 说的"桶内没有不崩的对照 ⇒ pct=100 不构成判定"，在我这一支上要反过来读：**"没有对照"正是我的模型的预测值**（`audit_supp` 无守卫 ⇒ 走到出口就抛，不给你留下"走完且不崩"的可能）。
  ⇒ "必崩"的根据 = **两条零额度证据**：① 结构判定（`_EXIT_BY_EVENT['complete'] = audit_supp`，而 `audit_supp` 的守卫计数 = 0，`nodes/audit_supp.py:49` 直接写终态）；② 反例计数 = 0（她 ⑬）。
  ⇒ 受控臂（1 对 = 2 条准入 ≈¥0.007）能钉的是**频率/可达性**，不是必然性；而可达性**也已经有活体见证**：`success` 桶 5 条 = 生产里真发生过 5 次"上一轮成功、这一轮追问"，其中 4 条正是她具名的崩臂。⇒ **我这一支不需要花那 ¥0.007**。若她仍要出那个臂，我把它读成"可达性复核"，不读成"必然性判定"。
- ✅ 同一张表也**独立验到我另外两支**：`prev=failed` 16 条 **0 崩**（= 我"error 残留 → 守卫命中 → INTERNAL + `failed` 行、不崩"）；`prev=clarify` 20 条 **0 崩**（= 我分类表缺的那第四档，`clarify_out.py:53` 有守卫 ⇒ 预测不崩，观测 0 崩）⇒ **我的 clarify 离线缺口在她的面上第一次拿到读数**，我据此把 §24/§26 的"clarify UNVERIFIED"改成"崩/不崩这一维已由落库面判（20 条 0 崩），复用形状仍 UNVERIFIED"（这一维要的是终止帧，不在她的表里）。
- 🔴 **同表里唯一真正打我的格子**：`prev=refuse` 18 条里 **6 崩 + 12 不崩** ⇒ 我"refuse 残留必不崩"被打了 6 个反例。但 ⑬b 显示这 6 条全在 **09-28 10 时、users = `u_b01,u_b02,u_b03,u_b04`**（不是 `u_f*` 那一格）。⇒ 我不把它们收进我的机制、也不宣称解释它们：**要先对表"那一小时的被测构建是哪个 commit"**。若是别的构建/别的缺陷（她 r20 那阵子还有 session-lock 格的靶子），则该桶的 33.3% 属**靶子混淆**（正是她 ⑬ 读法第 (2) 条自己警告的形态），我的分类表只在同构建同靶子的子集内检验。

### 28.3 修法验收的两条判据怎么分工（她 ④ 问的那半）

| 判据 | 读面 | 归属 |
|---|---|---|
| ① 修复后 `turn≥2` 的"0 审计行 = 0"（现值 13） | **落库面**（她 ⑩⑪⑬，零额度） | **W7 出数**，我不重做 |
| ② 修复后 `turn≥2` 的 run **本轮自己写终态** | 我的契约面 = `_DeltaSpy` 那个节点级信号（离线，五档现值全为"无节点写终态" ⇒ 修复后必须全为"有"）；活体面 = 她的 `terminal_without_any_stage` | **② 我落契约（离线断言）**；活体那一维她已有探测器，我不冒充能做 |

⇒ 这条分工写死，免将来两窗各让一步变成两不管。另：她 ⑤ 提的"桶内 users_clean"我要求**保留为列**（它就是我这三支的可否证位），别在下一版收敛掉。

### 28.4 我这侧不变的两件事

- `U-129` 第二触发面的归号请求**不变**；她 ⑬ 让"两症状同根"的支点从"我的假件 + 她的栈"升级到"生产落库面的五桶交叉表"，**架构可以按这一张表裁修法**。
- 我仍不自取号（现读 `07 §4.8` 行首下一可用号 = `U-133`，本轮 W7 未取新号）。
