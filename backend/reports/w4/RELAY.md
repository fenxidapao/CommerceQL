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