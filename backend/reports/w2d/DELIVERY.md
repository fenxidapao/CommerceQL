# 阶段 2D · 受控执行与脱敏 —— W2D 交付与交接说明

> 生成时间：2026-09-16（本机实测）
> 归属窗口：**W2D**（`app/exec/**`、`app/mask/**` + 随附测试，docs/08 §4.1）
> 上游：**W1B**（三池 / DSN / 审计 / GraphState），**不是 W2C** —— exec 收到的是闸门已放行的 SQL，P2C 与 P2D 是汇聚于 W4 的兄弟节点，阶段 0 冻结的 `core/contracts.py` 端口就是两窗口的接口。
> ⚠️ 本文件是**交付说明**，不是设计文档。设计归 `docs/07` §8；本文只写"盘上实际是什么状态"和"下一步谁做什么"。

---

## 0. 结论先行

| 项 | 状态 | 一句话 |
|---|---|---|
| DoD① 类型归一化逐条测试 | ✅ | 07 §8.4 全分支：numeric 保精度成串 / >2^53→串 / NaN±Inf→null / timestamptz→ISO+08:00 / bytea 占位 / json 深度>5 截断 / 数组递归；**31 条**（含 2^53 正负边界与负向对照注入） |
| DoD② deny 与 mask 语义分离 | ✅ | `tenant_key`/`internal_cost` 类 deny 标签**不掩码**（那是闸门的活）；引擎 21 条含钉死用例 `test_deny_semantics_tags_are_not_masked` |
| DoD③ `app_ro` 写必败（N-02） | ✅ 双证 | **库级**：裸 psycopg UPDATE → 锁① 只读事务 25006 + 锁② 关掉会话只读后权限 42501（两道独立锁分开验证，见 §4.1）；**executor 级**：写语句经服务端游标必失败且零落库 |
| DoD④ `truncated` 只由 LIMIT 触发 | ✅ | 行数 == 生效 LIMIT → True；RLS 减行 / 行数<LIMIT → False；executor 另加"收集硬上限 = min(max_rows, effective_limit)"纵深防御（§3.4） |
| U-63 对照（gate3 EXPLAIN 归属） | ✅ 已核并落地 | W4 `gate3_cost` **必须走 `executor.explain()`**，不能喂 `fetch` —— EXPLAIN 不能经 DECLARE 游标执行（PG 实测 42601，见 §3.6） |
| 测试（本窗口 4 文件） | ✅ **96 passed / 0 failed** | 31 + 25 + 21 + 19，含真 PG 集成 19 条（无库自动 skip，不假绿） |
| `lint-imports` | ✅ rc=0 | 3 kept, 0 broken（含 R-DEP-1/2：exec/mask 不 import llm） |
| `ruff check .`（本窗口文件） | ✅ 0 违规 | ⚠️ 全仓剩 29 条**全在 W2B/W2C/W4 的未跟踪在制品里**（§5），非本窗口引入 |
| `mypy app/exec app/mask` | ✅ no issues | 全仓 `mypy app` 剩 24 条中 22 条在 guard（W2C）/retrieval（W2B）在制品 |

**一句话**：W2D 范围内代码、测试、门禁**全绿**；U-63 对照发现并补齐了一个契约缺口（`explain()` 受控入口，§3.6）；交付物含两个如实登记的 P0 诚实边界（列身份掩码装配点、unit 标注），详见 §4。

> **提交说明（2026-09-17）**：W2D 产物以两个提交落库（响应 W2-INT 收口窗口的提交提醒）——
> **`4a63373` feat(w2d)** 代码+测试（12 文件，+2595 行）、**docs 提交** = 交付/转述件（hash 见 git log）。
> 只暂存 W2D 独占文件；工作区中 W2B 的 `retrieval/dense.py` 在制品一条未碰。**未 push**（no-push 纪律）。

---

## 1. 交付物（`git status` 显示为 untracked，未提交）

| 路径 | 内容 |
|---|---|
| `app/exec/executor.py` | `PgSqlExecutor(SqlExecutorPort)`：analytics 池唯一出口 / `prepare_threshold=None` / ADR-09 身份注入 / `set_config` 资源控制 / 服务端游标分批取 / 内存估算→`EXEC_RESOURCE_EXCEEDED` / 取消登记 + `pg_cancel_backend` / 归一化→掩码→指纹；**`explain()` = gate3_cost 的 EXPLAIN 受控入口（U-63）** |
| `app/exec/normalize.py` | `normalize_cell` / `normalize_row`（07 §8.4 逐条）+ `raw_type_name`（⚠️ 判型必须用原始值，归一化后 Decimal 已是串） |
| `app/exec/errors.py` | `ExecError` / `ExecFailure` / `classify_pg_error`（N-11：只读 sqlstate，原文零回灌）/ 8+1 类 / repairable vs non-repairable |
| `app/exec/fingerprint.py` | `result_fingerprint`（sha256：列序+行序+生效参数；不含 tenant_id 的责任在调用方） |
| `app/mask/engine.py` | `SemanticMaskEngine(MaskPort)`：**先全列解析规则（fail-closed）再动行**；`hit_columns` 记录；None 直通 |
| `app/mask/rules.py` | 5 类 PII 规则 + 语义包规则形态表（`***-***-1234` 等已知形态）+ `resolve_rule_for_column`（身份优先、正则兜底，07 §8.7） |
| `app/exec/__init__.py` `app/mask/__init__.py` | 再导出（阶段 0 对 mask 的空壳约束已解除） |
| `tests/unit/test_type_normalization.py` | 31 条 |
| `tests/unit/test_mask_engine.py` | 21 条（含负向对照注入） |
| `tests/unit/test_exec_offline.py` | 25 条（错误分类 N-11 / 指纹 / executor 纯逻辑 / `_bind_dollar_params` 契约） |
| `tests/integration/test_exec_real_pg.py` | 19 条真 PG（沿用 W1B 模式：无库 skip 不假绿；schema 随机后缀） |
| `reports/w2d/DELIVERY.md` `reports/w2d/RELAY.md` | 本文件 + 逐窗口转述件 |
| `reports/w2d/probe_explain_timing_pg.py` | **2026-09-18 追加**：U-96 判据实验探针（可复跑、只读、不写库）—— 钉死"07 §7.5 规定的 `EXPLAIN (FORMAT JSON)` 不产出任何耗时字段" + "cost→ms 系数跨 327× 不成立"。见 RELAY 第一节 / DELIVERY §8 |

---

## 2. 实测证据（可复现）

### 2.1 真 PG 集成（19 条，`pytest tests/integration/test_exec_real_pg.py` → 19 passed, ~3s）

最有分量的几条（替身做不到）：

1. **N-02 双锁库级证明**：app_ro 默认连接 UPDATE → `25006`（角色级 `default_transaction_read_only=on`，迁移 0001）；同一角色 `SET default_transaction_read_only=off` 后再 UPDATE → **`42501`**（表级权限兜底）；两锁各自验证后核对 `amount=0` 零落库 —— "失败不只是报了个错"。
2. **全类型归一化一镜到底**：numeric→`"1.00"` 保精度、NaN→null、bytea→`"[binary omitted]"`、timestamptz→`"2026-09-16T00:00:00+08:00"`（UTC 16:00 跨日边界）、6 层 jsonb 第 6 层被截断标记、列元数据按**原始值**判型（`amount=decimal` 而非 string）。
3. **身份注入真达 GUC**：`set_config(..., true)` 注入后同一事务内 `current_setting('app.tenant_id')` = 注入值（ADR-09 的库侧证据）。
4. **取消链路**：`pg_sleep(10)` 执行中 `cancel()` → `pg_cancel_backend` → 57014 → `timeout` 类，登记表被 `finally` 清干净。
5. **内存上限**：1MB 预算 + 每行 1.5MB → 第一批即 `EXEC_RESOURCE_EXCEEDED`（不是 `COST_TOO_HIGH`，附录 A §A.11）。
6. **U-63 的 EXPLAIN 链路**（2026-09-17 补）：`explain()` 返回解析后的计划 JSON；`EXPLAIN (ANALYZE)` 真执行时超时 → `EXEC_TIMEOUT`；`fetch` 喂 EXPLAIN 被**钉死为必败**（42601，防 W4 误接）；非 EXPLAIN SQL / 非 FORMAT JSON 均 fail-closed 拒绝。

### 2.2 测试计数

| 文件 | 条数 | 说明 |
|---|---|---|
| `test_type_normalization.py` | 31 | 含 2^53 正负 4 边界 + 负向对照注入（patch 模块属性路径，第一版踩过 from-import 失效坑） |
| `test_mask_engine.py` | 21 | 身份优先 / 正则兜底 / deny 不掩码 / fail-closed 三态（行宽、缺键、坏正则）/ 负向对照 |
| `test_exec_offline.py` | 25 | 分类表逐行 / 指纹序敏感 / 配额隔离 / `_bind_dollar_params`（乱序重排 + 4 种契约破损 fail-closed） |
| `test_exec_real_pg.py` | 19 | 真 PG，见 §2.1 |
| **合计** | **96 passed / 0 failed** | 2026-09-17 终测（feat 提交 `4a63373` 前） |

---

## 3. 实测暴露并已修复的问题（防"照文档写就踩坑"复发）

### 3.1 async SQLAlchemy 揭盖必须走 `get_raw_connection()`

`AsyncConnection.connection` 属性**未实现**（首次集成跑 13 条全挂在它上面）。正确链：
`await conn.get_raw_connection()` → `.dbapi_connection` → `.driver_connection`（psycopg 本体）。
`_raw_connection` 已改为 async，揭盖点全仓**仅此一处**，拿不到即 fail-fast，绝不静默退化成"没有身份注入"。

### 3.2 `IDENTITY_INJECTION_TEMPLATE` 是 pg 原生 `$n` 形态，psycopg 客户端绑定不认

实测报错：`the query has 0 placeholders but 3 parameters were passed`。
W1B 的契约模板用 `$1..$3`（pg 服务端绑定形态），而 psycopg 客户端绑定只认 `%s`。
**归属处理**：`dsn.py` 归 W1B，未越权修改；executor 侧加确定性转换 `_bind_dollar_params`：
`$n` → `%s` 并**按 $n 序重排参数**；占位符缺号 / 重复 / 参数数不匹配 → `契约破损` fail-fast（4 种形态各有测试）。
**给 W1B 的回执**：模板本身没改、语义没变；若 W1B 想在 `dsn.py` 注释里补一句"消费者需做 `$n`→`%s` 适配"，请自便（见 RELAY.md）。

### 3.3 N-02 库级测试第一版断言 `42501` 是错的

app_ro 角色级 `default_transaction_read_only=on` 让默认连接跑在只读事务里，UPDATE 在权限检查**之前**就被 `25006` 拒绝 —— 第一版测试**根本没测到权限锁**。
修正为双锁分开验证（§2.1 第 1 条）。这条的价值：如果未来有人把角色级只读关掉，权限锁仍被独立钉死。

### 3.4 非 PG 异常不得伪装成 SQL 错误喂 repair

修复过程中亲历：`_resource_error` 漏 import `ExecError` → `NameError` 被 `classify_pg_error` 兜底成 `syntax_error` → 用户会看到"SQL 语法有误"且 LLM 进 repair 循环修一条根本没坏的 SQL。
已修两层：① 补齐 import；② `fetch` 的兜底 except 现在**区分** `psycopg.Error`（→ 脱敏分类）与非 PG 异常（→ `CommerceQLError("执行层内部错误")`，不进 repair 误导）。

### 3.5 `_resource_error` 返回的就是成品 `ExecFailure`

再包一层 `ExecFailure(_resource_error(...))` 会把 ExecFailure 当 ExecError 解构，当场 `AttributeError`。已改为直接 raise。

### 3.6 U-63 对照：EXPLAIN **不能**经 DECLARE 游标执行 —— `fetch` 不能当 gate3 入口

收口窗口转达 U-63（07 v0.9 §4.8）：gate3 的 EXPLAIN 由 W4 `gate3_cost` 节点执行，**必须经 W2D exec 受控入口**（analytics 池 + 同事务 + 同身份 GUC + 只读），节点不得自建连接。对照 exec 现状后发现**契约缺口**：

| 路径 | 实测（app_ro @ 本机 PG） |
|---|---|
| 普通 `execute` 跑 `EXPLAIN (FORMAT JSON) ...` | ✅ 返回解析后的 `[{Plan: {...}}]` |
| 命名游标（`DECLARE ... CURSOR`）跑同一语句 | ❌ **42601** `syntax error at or near "EXPLAIN"`（与 DML 同因：DECLARE 不接受） |

即：W4 若把 EXPLAIN 直接喂 `fetch`（它走的就是命名游标），必撞 42601，且会被 `classify_pg_error` 归成 **syntax_error 回灌 repair** —— LLM 会被派去"修"一条根本没坏的 SQL。

**补齐**：`PgSqlExecutor.explain(sql, params, ctx, *, statement_timeout_ms)` ——
- 与 `fetch` 共享**同一套**受控序列（重构出 `_controlled_session` 上下文，两入口唯一实现：配额 / 揭盖 / `prepare_threshold=None` / 取消登记 / 事务内身份注入 / statement_timeout / N-11 脱敏分类）；
- 收集方式不同：普通客户端游标 `fetchone`（单行单列），**不走**掩码/归一化/指纹（计划 JSON 不是用户数据，那些管线不适用）；
- fail-closed 两道：SQL 必须以 EXPLAIN 开头；输出必须是 FORMAT JSON（文本形态 str 被拒）；
- 集成测试 5 条：正向计划 JSON / 拒非 EXPLAIN / 拒非 FORMAT JSON / `EXPLAIN ANALYZE` 超时→`EXEC_TIMEOUT` / **`fetch` 喂 EXPLAIN 必败**（钉死陷阱防误接）。

---

## 4. 诚实边界与设计取舍（**未掩盖**，均为 P0 范围界定而非缺陷）

### 4.1 列身份掩码（sensitivity 路径）在 executor 侧**未接线**

输出列名（SQL 别名）→ 语义包资产的映射属**绑定层**（W3C 的 `bindings`），端口签名里没有它的位置。
P0 接线的是**语义包 mask_rules 覆盖路径**（`bundle.policy()["mask_rules"]` 对输出列名正则匹配 —— 判据仍是语义包声明，不是本模块发明的正则）。
引擎本身的 sensitivity 路径**已实现且有 21 条测试**，等 W4 在装配点提供列身份映射即可启用（`_mask_policy` 目前把 sensitivity 恒置 None，如实标注）。

### 4.2 `ColumnMeta.unit` 恒为 None

单位标注需要"输出列 → 指标"映射，同上归绑定层 / W4 装配点。

### 4.3 每租户连接配额是**进程内**信号量

40% × analytics 池上限（40 → 16），07 §8.2 的"池内按租户"语义在**单进程**下成立；多进程形态由 W7 部署模型决定，不在此假装全局。

### 4.4 `effective_limit` 双重钳制（纵深防御）

除 SQL 内闸门注入的 LIMIT 外，executor 收集上限再压一道 `min(max_rows, effective_limit)` —— 即便改写失守，执行器也绝不返回超过生效 LIMIT 的行数。§8.6 的 `truncated` 判定语义不变。

### 4.5 掩码在**归一化后的字符串形态**上工作

行先归一化再过 MaskPort —— 掩码规则的输入恒为 str/int，不用处理 Decimal/bytes 等 DB 类型。`ColumnMeta` 判型则用**归一化前**的原始值（否则 decimal 列被标成 string）。

### 4.6 `explain()` **刻意不走**掩码/归一化/指纹管线

计划 JSON 是基础设施数据不是用户数据：无 PII 可掩（N-05 不适用）、无业务类型可标、指纹语义（§8.8 对结果集去重）对计划无意义。硬套管线只会给 gate3 增加无意义的失败面。身份注入 / statement_timeout / 取消登记等**受控前提一条不少**（与 fetch 共用 `_controlled_session`）。

---

## 5. 并行窗口在制品的**非本窗口**红（如实登记，未越界修）

`git status` 实测以下均为未跟踪的在制品（并行窗口正在写，归属权纪律：不落笔）：

| 位置 | 问题 | 归属 |
|---|---|---|
| `app/retrieval/dense.py:273` | **`F821 Mapping 未定义`**（ruff F821 + mypy name-defined，import 块整理会顺带修掉） | **W2B** |
| `app/guard/**`（cost_gate / ast_gate / policy_gate / rules / __init__） | ruff 7 条 + mypy 19 条 | **W2C** |
| `app/retrieval/**` 其余 + `tests/unit/test_retrieval_*` + `tests/integration/test_retrieval_fts_pg.py` | ruff 多条；全量 pytest 有 1 红（`test_retrieval_dense.py::test_pg_store_passes_params_and_parses_rows`） | **W2B** |
| `tests/redteam/test_redteam_guard.py` | F401 unused import | W4/W2C |

**含义**：若以当前工作区跑全仓 `ruff check .` / `mypy app` / `pytest`，会因上述在制品出现红 —— **与 W2D 交付无关**。本窗口验证口径：W2D 自有 4 个测试文件全绿 + `mypy app/exec app/mask` clean + `lint-imports` 全仓 rc=0。

---

## 6. 编号（新登记）

**无新增编号请求。** 本窗口范围内的所有问题均在交付前修复，无遗留未决项需要开号。
（记忆约定：W1A/W1B 区间已用尽，下一可用号 = U-54；本窗口未占用。）

> **2026-09-18 补充**：回应 🔴-6 时**亦未开新号** —— `U-96` 已由 W4 登记，其编号与裁定归架构。详见 §8。

---

## 7. 门禁复跑命令（`cd backend`，真 PG/Redis 在位）

```
pytest tests/unit/test_type_normalization.py tests/unit/test_exec_offline.py tests/unit/test_mask_engine.py tests/integration/test_exec_real_pg.py
lint-imports                       # ⚠️ 不要写 python -m importlinter.cli（U-41）
ruff check app/exec app/mask tests/unit/test_exec_offline.py tests/unit/test_mask_engine.py tests/unit/test_type_normalization.py tests/integration/test_exec_real_pg.py
mypy app/exec app/mask
```

---

## 8. U-96 回执（2026-09-18 追加，回应 W7 🔴-6）

**W7 的交办口径**：`GateResult` 加预估延迟载体（U-96），"字段归 W2D"。

**W2D 的结论：口径需要更正 —— 这不是"加个字段"，是"值来源从未定义"。**

| 结论 | 依据（实测，非推断） |
|---|---|
| 07 §7.5 规定的 `EXPLAIN (FORMAT JSON)` **不产出任何耗时字段** | 五种查询形状顶层键恒为 `['Plan']`，"含 time 的键"命中 **0**；只有 `Total Cost` / `Plan Rows`（PG 16.15 实测） |
| 耗时只在 `EXPLAIN (ANALYZE, ...)` 里有，而它**会真执行查询** | 与 §7.5 "只估算不执行"直接冲突；且"执行完再转异步"失去意义 |
| 代用路线（`Total Cost` × 系数 = 毫秒）**不成立** | `cost/ms` 跨 **1.667 ~ 545.5（327×）**；同 SQL 同进程漂移 1.10~1.32×，跨进程冷调用 2.2× |
| "字段归 W2D" **不成立** | `GateResult`∈W0（`app/core/contracts.py`，冻结端口面）、`edges.py`∈W4（`app/graph/**`）、`run_gate3`∈W2C（`app/guard/**`）；docs/08 §4.1:297 只给 W2D `app/exec/** + app/mask/**` |
| 连"标定"路线的数据源也没有 | `cost_ledger` 只记 LLM token 成本；`query_plan` 只记计划/绑定诊断 —— 全仓无 `(estimated_cost → 实测耗时)` 留存 |

**W2D 交出的**：`probe_explain_timing_pg.py`（证据）+ 三方案对比与推荐（甲：`warn` 即"超阈值"，约 1 行改 W4 的 `edges.py`）。
**W2D 未动的**：一切他人代码（`contracts.py` / `edges.py` / `cost_gate.py` / `tests/contract/**` 零改动）。

> 决策与完整方案表见 `RELAY.md` 第一节。**待架构一句裁定**（甲/乙/丙）后即可落地。
