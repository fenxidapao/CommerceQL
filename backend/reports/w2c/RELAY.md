# W2C RELAY —— 跨窗口转达件（唯一转达入口）

> 归属：W2C（`app/guard/**`）｜日期：2026-09-16｜状态：**阶段 2C 代码完成，待架构裁定 3 项 + W2A 对齐 1 项**

---

## 1. 需架构窗口登记/裁定的编号（**W2C 未开号，只提案**）

按 docs/08 §6.3：先查 07 §4.8（下一可用号 = **U-54**），W2C 不落笔 07，只在此提案，请架构窗口裁定并开号。

### 提案 U-54 —— GuardPort 缺"改写类"出参通道

- **现状**：`contracts.GuardPort` 只有 `gate1/gate2/gate3` 三个查询型签名；但 07 §5.3 节点 8 `gate1_ast` 的职责是"AST 审计 + LIMIT 注入 + **默认谓词注入**"，节点（W4）还需要 **`rewritten_sql` / `limit_injected` / `applied_predicates` / warnings** 这些改写产物写回 GraphState（07 §5.2 组 7）。
- **W2C 已做**：`guard/ast_gate.py` 的模块函数 `run_gate1(sql, allowlist) -> Gate1Report`（含全部出参）；`SqlGuard`（`app/guard/__init__.py`）实现 GuardPort 端口形状。
- **请裁定**：① W4 节点直接调 `run_gate1` 模块函数（端口不改，最快）；或 ② 扩 GuardPort（W0 落笔 contracts.py）。
- **影响面**：W4（gate1_ast / gate2_policy / gate3_cost 三节点的调用方式）、W0（contracts.py）。

### 提案 U-55 —— gate3 的 EXPLAIN 执行归编排层

- **现状**：`GuardPort.gate3(sql, thresholds)` 是纯函数，但 07 §7.5 要求 EXPLAIN 在"只读连接、同事务、同身份 GUC"下执行 —— guard 作为 L2 纯函数（N-01/N-03）不能持连接。
- **W2C 已做**：`run_gate3` 只做**计划解析 + 阈值判定**；计划 JSON 经 `thresholds["explain_plan"]` 传入；`thresholds["explain_error"]=True` → warn；`thresholds` 缺省 → `SKIPPED`（D6：不报告为通过）。降级常量 `EXPLAIN_ERROR_DEGRADE_THRESHOLD=3`（连续计数归节点层）。
- **请裁定**：确认"W4 的 gate3_cost 节点负责跑 EXPLAIN 并传计划 JSON"为正式契约。
- **影响面**：W4。

### 提案 U-56 —— 红队冻结集与 07 §7.2/§7.3 的 5 处口径冲突（**需裁决，W2C 已按冻结集执行**）

红队集是 DoD① 的判定基准且 content_hash 冻结；冲突处 W2C **按红队集执行**并在测试内留断言。逐条：

| # | 冲突 | 07 原文 | 红队冻结口径 | W2C 执行 |
|---|---|---|---|---|
| 1 | `LIMIT ALL` | §7.3：**拒绝** | RT-R04-003：**rewrite**（"SQLite/PG 方言差异写法"） | rewrite（剥除后按无 LIMIT 注入） |
| 2 | `SET search_path`（会话级） | §7.2 R16 | RT-R01-002 tag=**R01** | 归因 R01 |
| 3 | `SET LOCAL search_path` | §7.2 R16 | RT-R16-002 tag=R16 | 归因 R16（与上一条并存，按 LOCAL 区分） |
| 4 | CROSS JOIN 归因 | §7.2 R11（"无 ON/USING 的 JOIN/CROSS JOIN"） | RT-R10-003 tag=**R10** | 无条件连接 → R10；认证边上条件列错配 → R11 |
| 5 | R14 字面量策略 vs R17 告警 | §7.2 R14：除三类外**任何**字面量拒绝；但 §7.8 R17 要求 `region_code = 440000` 放行+告警 | RT-R17-001/002 warn | R14 实际口径 = "字面量-字面量恒真比较 + 无列上下文自由字面量"拒绝；**列-常量比较放行**（类型失配交 R17）。两种读法不可同时满足，按红队集执行 |
| 6 | **RT-LIM-003 内部矛盾** | policies.deny_columns 明列 `order_paid.tenant_id`（"不得由模型生成"） | RT-LIM-003 期望 execute（RLS 返回 0 行） | **W2C 按契约拒绝（R07）**；测试内留豁免断言，deny 与 execute 期望二选一需裁定 |

- **影响面**：W1A（红队集生产方）、架构窗口（07 §7 章节回填）、W6（评测器复用同口径）。

## 2. 需 W2A 对齐的接口点（非阻塞，W2A 交付时对表）

- `asset_allowlist(ctx) -> Mapping` 的**预期形状**定义在 `app/guard/ast_gate.py` 模块 docstring（assets/joins/deny_columns/default_predicates/allowed_constants/bundle_version/max_rows）。测试夹具 `tests/unit/guard_fixtures.py::build_allowlist()` 已按该形状从**真语义包 YAML** 构建（单一事实来源，不手抄）。
- W2A 交付运行时后，红队/单测夹具应切换为直接调 W2A 运行时（防两套形状）。
- `default_predicates` 按**域**注入到该域每个资产实例：实测 bundle 中 `v_shop`/`v_region`/`v_dim_date` 的域归属与谓词列不交叉，注入安全；若 W2A 语义包后续把带谓词域的资产改为引用无谓词列的表，注入器会跳过（`_parse_predicate` 失败静默跳过由 W2A 校验器兜底）——请 W2A 在校验器加"谓词列必须存在于域内全部资产"断言。

## 3. 给 W4 的接线提示词（阶段 4 启动时复制使用）

见本目录 `W4_PROMPT.md`（本窗口产出）。

## 4. 给 W2D/W2B 的观察（不要求动作）

- 全量 pytest（2026-09-16 20:5x，本窗口收尾时）：758 passed / 3 failed / 8 skipped。3 个失败均在**他窗在制品**，W2C 不落笔：
  - `tests/integration/test_exec_real_pg.py::test_truncated_true_only_when_rows_reach_effective_limit`（`effective_limit` 参数疑似未生效，row_count=10）——W2D；
  - `tests/integration/test_exec_real_pg.py::test_memory_limit_raises_resource_exceeded`（报 `SQL_SYNTAX_ERROR` 而非 `EXEC_RESOURCE_EXCEEDED`）——W2D；
  - `tests/unit/test_retrieval_dense.py::test_pg_store_passes_params_and_parses_rows`（SQL 实际为 `tenant_id IN (:tenant_id, '*')`，断言期待 `=`）——W2B。
- 另：`tests/integration/test_retrieval_fts_pg.py` 6 skip（夹具 DSN 无 DDL 权限）、`test_semantic_materialization.py` 2 skip（业务视图未建，待裁决③）。

## 5. W2C 未做 / 移交（诚实清单）

- gate2 "敏感字段二次审批（P1）"：07 §7.4 表内 P1 项，接口预留位未实现（P0 无令牌通道），与 07 §13.6 一致。
- R14 第③类"语义包内声明的白名单常量"：当前 bundle 无声明区 → `allowed_constants=[]`；W1A 若增补声明区，guard 零改动（读 allowlist 键）。
- `SHOP_LIMITED_NOTICE` 固定文案内容：07 只规定"固定文案"未给文本，W2C 给了默认值（`policy_gate.py`），措辞请 06/W4 复核。
