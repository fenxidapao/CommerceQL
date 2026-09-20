# W2D RELAY —— 逐窗口转述件

> 2026-09-17 更新：**已提交**（响应收口窗口提交提醒）—— `4a63373` feat(w2d) 代码+测试 + docs 提交（交付/转述件）。请收口窗口基于提交后状态重跑门禁复核。
> **2026-09-18 更新：回应 W7 阻塞项 🔴-6（U-96"预估延迟载体"）—— 见本页第一节。结论：这不是"给
> `GateResult` 加个字段"，是"值来源从未定义"；已出可复跑探针 + 三条实测事实 + 三方案裁定请求。**
> 本文件是"谁下一步该做什么"的单页转述；细节与证据见同目录 `DELIVERY.md`。
> W2D 范围：`app/exec/**` + `app/mask/**`。96 tests passed（31+25+21+19），W2D 范围门禁全绿。

---

## 🔴 给 W7 / 架构 —— U-96 回执：不是"加个字段"，是"值来源从未定义"

> 2026-09-18。对应 W7 阻塞项 🔴-6（`backend/reports/w7/RELAY.md:407`）。
> 复跑：`cd backend && ../.venv/Scripts/python.exe reports/w2d/probe_explain_timing_pg.py`（真 PG 在位）

### 0. 三条**实测**事实（脚本输出为准，不是推断）

实测环境：PG **16.15**（compose 栈 `commerceql-pg-1`），表 `app.order_paid`，五种查询形状。

| # | 事实 | 证据 |
|---|---|---|
| 1 | `EXPLAIN (FORMAT JSON)`（**07 §7.5 明文规定的取数形态**）输出里**没有任何耗时字段** | 五种形状（全表聚合 / 点查 / 高基数分组 / 排序+LIMIT / 无索引全扫）顶层键**恒为 `['Plan']`**，"含 time 的键"命中数 **0**。JSON 里只有 `Startup Cost` / `Total Cost` / `Plan Rows` / `Plan Width` |
| 2 | 耗时只存在于 `EXPLAIN (ANALYZE, FORMAT JSON)`（`Planning Time` / `Execution Time` / 逐节点 `Actual Total Time`），而 **ANALYZE 会真执行查询** | plain 形态 0 命中；同一个 SQL 加 `ANALYZE` 立刻出现 `Execution Time` |
| 3 | 代用路线"`Total Cost` × 系数 = 毫秒"**不成立** | 五种形状 `cost/ms` = **1.667 ~ 545.5（327×）**；同一 SQL 同进程连跑 3 次漂移 **1.10~1.32×**，经独立进程冷调用实测 **2.2×**（21.4ms vs 47.8ms，同 SQL 同机） |

### 1. 为什么"给 `GateResult` 加预估延迟字段"不是正解

- **加了字段也没有诚实的取值来源**：事实 1 说 §7.5 的数据源里没有毫秒；事实 2 的取值要先执行（自毁分支目的，且与 §7.5 自己的"只估算不执行"冲突）；事实 3 的代用是造数字（**U-22 红线**）。
- **归属也不成立**：`GateResult` 在 `app/core/contracts.py`（W0，阶段 0 冻结的最小端口面）；`edges.py::_estimated_latency_ms` 在 `app/graph/**`（W4）；`run_gate3` 在 `app/guard/**`（W2C）。`docs/08 §4.1:297` 给 W2D 的只有 `app/exec/** + app/mask/**`。
  ⇒ W2D 能供的是**读计划的通道**（已有 `executor.explain()`，U-63），不是那个值本身。
- **配置键也从未存在**：`async_threshold_ms` 在任何配置契约里都没有定义（附录 A §A.1.3 只定义了 `async_if_slow`，默认 true）——`edges.py:108-113` 已如实标注这个待对账。
- **连标定路线的数据源也没有**：全仓没有 `(estimated_cost → 实测耗时)` 的证据留存 —— `cost_ledger` 只记 LLM token 成本（`entry_id/model/input_tokens/cost_cny/...`），`query_plan` 只记计划与绑定诊断（`plan_json/binding_state/...`）。

### 2. 三个方案（需架构一句裁定）

| 方案 | 内容 | 需要什么 | 归属 | 我的判断 |
|---|---|---|---|---|
| **甲** | 把"超阈值"落到 gate3 **已有的 `warn` 决策**上：`decision is WARN and async_if_slow` → 转异步；`async_threshold_ms` 由"必需"降为"可选覆盖" | 一句语义裁定（"预估耗时超阈值" ≡ "gate3 判 warn"）+ 架构给 `async_threshold_ms` 定义或删除 | **W4 改 `edges._should_go_async`，约 1 行** | ✅ **推荐**：零新数据、零编数；且 §7.5:1786 的 async 分支**本来就只在 `warn` 行** —— 语义天然对齐 |
| **乙** | 坚持毫秒语义 ⇒ 成本→耗时系数 + 标定 | 新配置键 + 新证据列/表 + 标定流程 | 架构 + W1B（迁移）+ W6（标定） | ❌ 事实 3 已否掉：系数跨 327×，不是常数 |
| **丙** | 不在 gate3 预判，改在 **execute 侧"超时即转后台"拦截**（不预测、只拦截） | §5.4 路由语义改写 | 架构 + W4；W2D 配合出"同步等待超时"的可区分结果 | ⚠️ 工程上最正确（预测不如拦截），但动 §5.4 结构 |

**推荐甲的额外理由**：`GateResult` 的 `decision` **已经**是 gate3 唯一的"轻/重"分类器，`warn` 的定义就是"重到要提示、但允许执行"。再引入一个与 `Total Cost` 强相关、却谁都没定义过的 ms 阈值，等于给同一个判断做两套口径 —— 而它们必然漂移。

### 3. 我落地了什么 / 没落地什么

- **落地**：`reports/w2d/probe_explain_timing_pg.py`（可复跑、只读、ruff clean、`ruff format` clean）+ 本节登记。
- **未落地**：**未改任何一行他人代码** —— `app/graph/**`、`app/core/contracts.py`、`app/guard/**`、`tests/contract/**` 全未动（甲方案那 1 行属 W4，且需先有架构裁定）。
- **未开号**：U-96 的编号归架构，我不自开新号。

### 4. 附带发现：🔴-2 的 `SIM117` 是**系统性陷阱**，不是 W4 的笔误

本探针**第一版**同样命中 `SIM117`（嵌套 `with psycopg.connect() / with conn.cursor()`），与 W4
`reports/w4/probe_feedback_endpoint_pg.py:100` 同因。
⇒ 只要 CI 跑的是 `backend/` 下 `ruff check .`（**不排除 `reports/**`**），**任何**写成"两个嵌套 `with`"的探针脚本都会挡 CI。
建议（归 W0/W4，我只出证据）：`ci.yml` 排除 `reports/**`，或 `backend/pyproject.toml [tool.ruff]` 加 `exclude = ["reports"]` —— 逐个手修是治症状。

---

## 给 W4（graph / api routers 装配）—— 接线说明

### 0. U-63 回执（gate3_cost 的 EXPLAIN 怎么接）—— 🔴 先读这条

07 v0.9 §4.8 U-63 已核：`gate3_cost` 节点跑 EXPLAIN **必须走 W2D 受控入口，且只能用 `explain()`，不能用 `fetch`**。

```python
plan = await executor.explain(
    "EXPLAIN (FORMAT JSON) SELECT ...",   # ⚠️ 必须 FORMAT JSON（否则 fail-closed 拒绝）
    params, ctx, statement_timeout_ms=...,
)   # → list[dict]，已解析的计划 JSON
```

实测依据（DELIVERY §3.6）：**EXPLAIN 不能经 `DECLARE ... CURSOR` 执行（PG 42601）**，而 `fetch` 走的就是命名游标 —— 误接会得到 `syntax_error` 分类并被回灌 repair（错误信号完全误导）。集成测试已把这条陷阱**钉死为必败**（`test_explain_via_named_cursor_would_fail_42601`）。`explain()` 与 `fetch` 共享同一套受控前提（同池/同事务/同身份 GUC/statement_timeout/取消登记，U-63 的"不得自建连接"由此保证）。

### 1. exec / mask 的装配点

- **构造**：`PgSqlExecutor(analytics_engine, mask, settings, bundle=None, tz=None, tenant_quota=None)`
  - `analytics_engine` = W1B `build_three_pools(settings).analytics`（SQLAlchemy AsyncEngine，`app_ro`）；
  - `mask` = `SemanticMaskEngine()`（无状态，可全局单例）；
  - `bundle` = 语义包运行时（实现 `SemanticBundlePort`），给 `policy()["mask_rules"]` 作掩码覆盖路径。**不给也能跑**（退化为空覆盖），但语义包里配了 mask_rules 就等于没生效 —— 建议必接。
- **调用**：`await executor.fetch(sql, params, ctx, *, max_rows, statement_timeout_ms, effective_limit=state.limit_injected)`。
  - ⚠️ `effective_limit` 请务必传（`state.limit_injected`）：它是 §8.6 `truncated` 判定的**唯一**正确口径，也是 executor 侧收集硬上限的依据。
- **成功产出**：`ResultSet(columns, rows, row_count, truncated, fingerprint)` —— rows 已过掩码，**这是下游（present/SSE/缓存）唯一能拿到的形态**。
- **失败形态**：只抛 `ExecFailure`（或内部错误形态的 `CommerceQLError`）。分流规则：
  - `error.error_class ∈ REPAIRABLE_CLASSES`（5 个 SQL 家族）→ 进 repair（`llm_hint` 已备好，**不要**自己再造提示语 —— 那是 N-11 的回灌面）；
  - `timeout` → `error(EXEC_TIMEOUT)`；`db_unavailable` → `error(DB_UNAVAILABLE)`；
  - `permission` → `refuse(out_of_scope)`（`default_code` 刻意为 None，落到 error 就错了）；
  - `resource_exceeded` → `error(EXEC_RESOURCE_EXCEEDED)`，终态建议走 `suggestions[]`（用户收窄查询）。

### 2. 取消（§8.3）与 SSE 的接缝

- `await executor.cancel(task_id)` → `pg_cancel_backend`（只对自己后端，**没有** terminate）。幂等：目标不在执行中 → False。
- SSE 断连检测归 W4：检测到客户端断开 → 调 `cancel(task_id)`。executor 执行期间以 `task_id → backend_pid` 登记，结束自动清除。

### 3. 列身份掩码的装配点（P0 诚实边界，见 DELIVERY §4.1）

executor 的 `_mask_policy` 目前把每列 `sensitivity` 恒置 None（输出列名→语义资产的映射属绑定层，端口签名里没有位置）。
**要启用 sensitivity 主判路径**：W4 装配时把"输出列名 → sensitivity 标签"的映射函数交给 executor（或改为由绑定层在调用前提供）。引擎侧逻辑已就绪（21 条测试），只是映射源未接。**在此之前，语义包里 `sensitivity` 标注的列不会被掩码，只有 mask_rules 正则路径生效 —— 请在对外口径里如实说明。**

### 4. 缓存键

`keys.result_set(tenant_id, task_id)` 已存在（W0），可直接用于结果缓存键；`ResultSet.fingerprint` 可作去重/幂等比对（不含 tenant_id，隔离由键层负责）。

---

## 给 W3C（binding）—— 一个待办

输出列名（SQL 别名）→ 语义包资产（含 `sensitivity` 标签）的映射归绑定层。当前 executor 拿不到它，列身份掩码未启用（DELIVERY §4.1）。请评估：这个映射在绑定层是否已有产出形态？若有，W4 装配时可直接接。

---

## 给 W2C（guard）—— deny 语义分离确认（DoD②）

掩码引擎**不做 deny**：`tenant_key` / `internal_cost` 这类 deny 标签的列**不会**被掩码也不会被放行 —— 拦截是闸门（gate）的职责。测试 `test_deny_semantics_tags_are_not_masked` 把这条边界钉死。两侧语义无重叠、无遗漏衔接问题。

---

## 给 W1B —— 契约消费回执（1 条，无需行动）

`IDENTITY_INJECTION_TEMPLATE`（`$1..$3` pg 原生形态）在 psycopg **客户端绑定**下不能直接传参（实测 `the query has 0 placeholders but 3 parameters were passed`）。W2D 在 executor 侧做了确定性转换 `_bind_dollar_params`（`$n`→`%s` + 按 $n 重排 + 契约破损 fail-fast，4 种破损形态有测试），**模板本身未动**。
可选动作：在 `dsn.py` 模板注释补一句"消费者需做 `$n`→`%s` 适配（见 exec/executor._bind_dollar_params）"，防止后续窗口直接 `raw.execute(template, params)` 踩同一个坑。是否补由 W1B 定。

---

## 给 W2B —— 在制品提醒（1 条，非阻断）

`app/retrieval/dense.py:273` 的 `_row_to_hit(row: Mapping[str, Any])`：`Mapping` **未导入**（ruff F821 + mypy name-defined，import 块整理会顺带修掉）。全仓 `ruff check .` / `mypy app` / 全量 pytest 因此有 W2B 侧红 —— 与 W2D 无关，但若 CI 先行会挂在这批在制品上。

---

## 给架构窗口 —— 无新编号请求

W2D 范围内问题均已交付前修复，无遗留未决项需要开号（下一可用号仍是 U-54，未占用）。
