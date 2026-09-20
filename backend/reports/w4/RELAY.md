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
