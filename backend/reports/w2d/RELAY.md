# W2D RELAY —— 逐窗口转述件

> 2026-09-17 更新：**已提交**（响应收口窗口提交提醒）—— `4a63373` feat(w2d) 代码+测试 + docs 提交（交付/转述件）。请收口窗口基于提交后状态重跑门禁复核。
> 本文件是"谁下一步该做什么"的单页转述；细节与证据见同目录 `DELIVERY.md`。
> W2D 范围：`app/exec/**` + `app/mask/**`。96 tests passed（31+25+21+19），W2D 范围门禁全绿。

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
