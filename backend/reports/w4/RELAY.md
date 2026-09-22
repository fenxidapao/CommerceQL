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
