# W2D RELAY —— 逐窗口转述件

> 2026-09-17 更新：**已提交**（响应收口窗口提交提醒）—— `4a63373` feat(w2d) 代码+测试 + docs 提交（交付/转述件）。请收口窗口基于提交后状态重跑门禁复核。
> **2026-09-18 更新：回应 W7 阻塞项 🔴-6（U-96"预估延迟载体"）—— 见本页第二节。结论：这不是"给
> `GateResult` 加个字段"，是"值来源从未定义"；已出可复跑探针 + 三条实测事实 + 三方案裁定请求。**
> **2026-09-21 更新：回应总控"GATE3 / EXECUTE 两格至今一帧未见"—— 见本页第一节（更靠前）。结论：
> 入口不缺 —— 离线全链夹具今天就能产出 `gate_passed` + `executing`（探针读数）；两格为 0 的成因是
> `U-121`。真正缺的是"`explain` 不在端口上、缝没人声明"，已补 `app/exec/seam.py`。**
> 本文件是"谁下一步该做什么"的单页转述；细节与证据见同目录 `DELIVERY.md`。
> W2D 范围：`app/exec/**` + `app/mask/**`。96 tests passed（31+25+21+19），W2D 范围门禁全绿。

---

## 🔴 给总控 / W4 / 架构 —— GATE3 & EXECUTE 的入口形态回执（前提需更正）

> 2026-09-21。回应总控"两格至今一帧未见，需要 W2D 按 U-63 开口子"。
> 复跑：`cd backend && ../.venv/Scripts/python.exe reports/w2d/probe_fullchain_two_cells.py`（**不连库**）

### 0. 🔴 先更正前提：入口不缺，两格在**离线侧今天就能兑现**

离线全链夹具（`tests/contract/_fullchain_deps.make_chain()` 默认绿档）一轮的 stage 序列：

| 读数 | 值 |
|---|---|
| stage 序列 | `intent → schema_linking → plan_ready → sql_ready → gate_passed → executing` |
| `gate_passed` 出现 | **True** |
| `executing` 出现 | **True** |
| `ScriptExecutor.fetch_calls` | **1**（真走到了 execute） |
| `ScriptExecutor.explain_calls` | **1**（gate3 真走了 U-63 的 EXPLAIN 入口） |

**⇒ 两格的判据不需要 W2D 再开任何口子。** 生产为 0 的成因**不在 exec 侧** ——
它是 `U-121`（闸门判据不可达：端口给扁平 `allowlist`，闸门要 7 个键 ⇒ `assets={}` ⇒
**任何真 SQL 必 `R05`**）⇒ 图根本到不了 `gate3_cost`。

补充（同样是既有事实，不是新发现）：`executor.explain()` 已实现且已生产装配
（`app/api/deps.py:750` 构造真 `PgSqlExecutor`）、已有 **5 条真 PG 集成测试**
（`tests/integration/test_exec_real_pg.py` 的 `test_explain_*`，含超时与 42601 对照）。

### 1. 真正缺的那一层（**今天已补**）：`explain` 不在端口上，缝没人声明

| 事实 | 位置 |
|---|---|
| `SqlExecutorPort` **只声明 `fetch`**，且只有 `max_rows` / `statement_timeout_ms` 两个关键字 | `app/core/contracts.py:494-510`（W0，冻结面） |
| 而图真的在传 `effective_limit` | `app/graph/nodes/execute.py`（07 §7.3 生效 LIMIT） |
| 而图真的在取 `explain`（`rich_method`） | `app/graph/nodes/gate3_cost.py`（U-63） |
| 这条缝**在类型层完全不检查** | `app/graph/nodes/_shared.deps_of() -> Any` ⇒ mypy 看不见上面两个调用；`rich_method` 运行期**只查 callable** |

两个可测后果（都指向"判据立不起来"）：

1. 契约测试要造替身，只能去**读调用点抄签名**；抄错了**不会红**（Python 参数不匹配只在真调到那一行才炸）。
2. `isinstance(fake, SqlExecutorPort)` 对**缺 `explain`** 的替身**照样为真** ⇒ 这个检查不足以证明图能跑到底。

⇒ **交付 `app/exec/seam.py`**（不改端口 —— 端口是 W0 的冻结面，同 W1B 为 `cost_ledger` 用本地结构化 Protocol 的先例）：

| 导出 | 内容 |
|---|---|
| `ExplainPlan` | `list[dict[str, Any]] | None`，并**明文区分两种"拿不到计划"**：返回 `None` = 方言不支持 → gate3 `SKIPPED`；抛异常 = 本次 EXPLAIN 失败 → gate3 `WARN`。仓库里三个实现（`PgSqlExecutor` / `SqliteEvalExecutor` / `ScriptExecutor`）此前**各表各的** |
| `ExecutorSeam` | `@runtime_checkable` Protocol = 端口 ∪ 图真正多用的两处（`effective_limit` + `explain`） |
| `declared_call_face_mismatches(obj)` | 用 `inspect.signature` 抓"抄错签名"，让它在**立判据时当场红**，而不是跑到那一行才炸 |

**分离力已做正向对照**（本仓护栏口径：注入 → 必须红 → 还原 → 必须绿）：
把 `ExecutorSeam` 里的 `explain` 删掉 ⇒ `tests/unit/test_exec_seam.py::test_port_face_double_is_rejected`
**正好 1 条红**（`assert not isinstance(_PortFaceDouble(), ExecutorSeam)` 失败）；还原 ⇒ 5 passed。

### 2. 顺带量出的**判据不完整**（是"没写"，不是"不可立"）

| 断言 | 条数 | 位置 |
|---|---|---|
| `"executing" in stages`（肯定） | **2** | `test_decision_table_d_e.py:147/162` |
| `"gate_passed" not in stages`（否定） | 2 | 同上 `:146/161`（warn/skipped 路径） |
| **`"gate_passed" in stages`（肯定）** | **0** | —— |

⇒ **`gate_passed` 只有否定面、没有肯定面**：D5/D6 钉住了"warn/skipped 时不许发"，
但"三闸门全 PASS ⇒ 要发"这条正路径**契约层无人钉**。而本探针证明它**离线可达**（今天就能写）。

### 3. 给架构的意见：**不建议为 GATE3 / EXECUTE 各立一条接缝号**

| 问题 | 我的判断 | 理由 |
|---|---|---|
| 两格各立一条 U-119 式接缝号？ | ❌ 不必 | 两格的**入口是同一条**（同一个 `deps.executor`、同一个端口）；拆两条会把"端口不声明形状"这个**唯一根因**切成两半 —— 而这正是 `U-121` 家族"修一格才发现下一格"的成因 |
| 那该立什么？ | ✅ 一条就够，且**不是** exec 侧的 | 缺的是"`gate_passed` **肯定路径**判据"（1 条，`tests/contract/**` = W4）。而"生产端口直连"这件事**已有的 `U-119` 已经覆盖实质** ⇒ 建议**并入 `U-119` 的判据**，不另开号 |
| 我这条（`explain`/`effective_limit` 未声明）要号吗？ | ⚠️ 倾向并入 `U-119` | 同一句病的两个实例：**"生产端口的实际调用面 > 声明面"**（闸门 allowlist 形状 / exec 入口形状）。⚠️ **编号归架构，我不自开** |

### 4. 给 W4 的可直接落地口径（两条）

- **①`gate_passed` 肯定用例**：用 `_fullchain_deps.make_chain()`（默认绿档）跑一轮，断言
  `"gate_passed" in stages` 且 `"executing" in stages` 且 `fetch_calls == 1`。
  ⚠️ **必须配正向对照**（本仓护栏口径）：把 `ScriptExecutor` 的 `explain_payload` 换成 `_WARN_BAND`
  ⇒ 该断言**必须红**（证明它在测"clean pass"这条缝，不是在测夹具恒真）。
- **②替身忠实性**：`assert declared_call_face_mismatches(deps.executor) == ()`
  （`from app.exec import declared_call_face_mismatches`）⇒ 签名漂移在立判据时红，而不是跑到那一行才炸。

### 5. 如实登记（本窗口自己的）

`app/exec/*.py` 与 `app/mask/*.py` 中有 **4 个已提交文件不满足 `ruff format --check`**
（`errors.py` / `executor.py` / `normalize.py` / `mask/engine.py`）。**文档门禁只有 `ruff check`（全绿）**，
故这不是现状红；但若 CI 将来加 `ruff format --check`，这 4 个会红。⚠️ **本轮不动它们**（改已提交文件会给
并行窗口制造 diff 噪声），登记待裁。

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
