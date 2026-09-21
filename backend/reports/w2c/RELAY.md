# W2C RELAY —— 跨窗口转达件（唯一转达入口）

> 归属：W2C（`app/guard/**`）｜初版日期：2026-09-16｜状态：**阶段 2C 已交付并 push（`9e2bd7e`/`c02f97a`/`a9ccec9`）；`U-62/63/64` 已裁定；`U-121`（P0）的形状由 W0 定，本窗待其落地后消费（见 §6）**

---

## 1. 需架构窗口登记/裁定的编号（**W2C 未开号，只提案**）

> 编号更正（2026-09-16，两次让号）：W2C 初稿曾用 U-54/U-55/U-56，发现 W2A 已在 `c864ea2` 先行提案同号（TokenizerPort/RLS 视图/v_* DDL）→ 一让；改用 U-59/60/61 后，又发现 W2B 在 `cc2c619` 的候选号为 U-58~61（前提 = W2A 三号被采纳）→ 二让。按 docs/08 §6.3「引用面小者让号」，W2C 三条提案最终改号为 **U-62/U-63/U-64**（引用本文者一律以新号为准；终局以架构登记表 07 §4.8 为准）。W2C 不落笔 07，只在此提案，请架构窗口裁定并开号。

### 提案 U-62 —— GuardPort 缺"改写类"出参通道

- **现状**：`contracts.GuardPort` 只有 `gate1/gate2/gate3` 三个查询型签名；但 07 §5.3 节点 8 `gate1_ast` 的职责是"AST 审计 + LIMIT 注入 + **默认谓词注入**"，节点（W4）还需要 **`rewritten_sql` / `limit_injected` / `applied_predicates` / warnings** 这些改写产物写回 GraphState（07 §5.2 组 7）。
- **W2C 已做**：`guard/ast_gate.py` 的模块函数 `run_gate1(sql, allowlist) -> Gate1Report`（含全部出参）；`SqlGuard`（`app/guard/__init__.py`）实现 GuardPort 端口形状。
- **请裁定**：① W4 节点直接调 `run_gate1` 模块函数（端口不改，最快）；或 ② 扩 GuardPort（W0 落笔 contracts.py）。
- **影响面**：W4（gate1_ast / gate2_policy / gate3_cost 三节点的调用方式）、W0（contracts.py）。

### 提案 U-63 —— gate3 的 EXPLAIN 执行归编排层

- **现状**：`GuardPort.gate3(sql, thresholds)` 是纯函数，但 07 §7.5 要求 EXPLAIN 在"只读连接、同事务、同身份 GUC"下执行 —— guard 作为 L2 纯函数（N-01/N-03）不能持连接。
- **W2C 已做**：`run_gate3` 只做**计划解析 + 阈值判定**；计划 JSON 经 `thresholds["explain_plan"]` 传入；`thresholds["explain_error"]=True` → warn；`thresholds` 缺省 → `SKIPPED`（D6：不报告为通过）。降级常量 `EXPLAIN_ERROR_DEGRADE_THRESHOLD=3`（连续计数归节点层）。
- **请裁定**：确认"W4 的 gate3_cost 节点负责跑 EXPLAIN 并传计划 JSON"为正式契约。
- **影响面**：W4。

### 提案 U-64 —— 红队冻结集与 07 §7.2/§7.3 的 5 处口径冲突（**需裁决，W2C 已按冻结集执行**）

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

## 6. `U-121` allowlist 形状接缝 —— **本节是"消费方需求"，不是"形状定义"**（2026-09-21）

> **定位声明**：下表是 W2C **作为消费方**对入参形状的**需求输入**，**不是契约**。形状所有权在 **W0**（`app/core/**`），依据 = `07` v1.6.4 §4.8 的 `U-121` 裁定（W0 定形状 / W2A 实现 / W2C 消费并删自造口径）。**任何窗口不得把本节当契约引用**；W0 定的形状若与本节不一致，**以 W0 为准**，本节随新形状重写。

### 6.1 W2C 立场：不主张形状所有权

- 闸门要的 7 键出自 `app/guard/ast_gate.py:16-24` 的**我方 docstring**（原文写作"入参形状"）—— **无任何上游依据**，是"把自己写的入参说明当成了端口契约"。
- **扁平才是端口的既成契约**：`app/planner/payloads.py:293`、`app/binding/filters.py:337` 两个生产消费者按扁平用；`tests/unit/test_semantics_loader.py:394-401` 在真实现上把扁平钉住。
- 根因不在任一侧的实现：`app/core/contracts.py:288` 的 `asset_allowlist(ctx) -> Mapping[str, Any]` **只声明签名、不声明形状** ⇒ 无人违约、也无人对齐。
- ⇒ **W2C 的动作 = 消费新方法 + 删掉自造形状的口径**；不是定义形状，也不是在 guard 内部自适配。

### 6.2 两个取用点的入参形态**不对称**，落点分属两窗

| 取用点 | 现状 | 换新方法由谁改 |
|---|---|---|
| `app/graph/nodes/gate1_ast.py:52` | `deps.semantics.asset_allowlist(identity)` → `:55` `run_gate1(sql, allowlist)`（**映射**入参） | **W4**（节点侧换方法） |
| `app/graph/nodes/gate2_policy.py:57` | `run_gate2(sql, identity, deps.semantics)`（**端口**入参；内部 `policy_gate.py:105` 自行取 allowlist） | **W2C**（改 `policy_gate.py:105`）；W4 的传入形态**不变** |

- ⚠️ **两处必须一起换**：只换 gate1 调用点、gate2 仍走扁平 ⇒ 同一 run 内 gate1 用新形状、gate2 用旧扁平 = **两个真相**，且**不会有任何测试发现**（那正是 `U-119` 的病灶）。
- ⚠️ **两处各自取一次是刻意设计**（`gate1_ast.py:13-18`：共用一份会让 gate2 的复核变成"复核自己刚给的那份"）⇒ 换形状时**不要顺手合并成一次取用**。

### 6.3 消费方需求清单（键 → 消费行 → 需要类型 → 缺了的方向）

| 键 | W2C 消费点 | 需要类型（我方实测的用法） | 缺了的方向 |
|---|---|---|---|
| `assets` | `ast_gate:500/:544/:638/:748/:751/:879`、`policy_gate:106` | `{物理名: {logical_name, columns: {列名: 类型}}}` | fail-closed（全拒 `R05`） |
| `joins` | `ast_gate:501/:640` | `[{left, right, on_columns[]}]`（**逻辑名**对） | fail-closed（所有 join 落 `R10`） |
| `deny_columns` | `ast_gate:502/:666/:693`、`policy_gate:140` | `frozenset["逻辑名.列名"]` | fail-closed，但**归因退化**（`R07`→`R06`）、gate2 `G2-DENY` 失效 |
| `default_predicates` | `ast_gate:444`（`:445` 空即 `return []`） | `{域: [SQL 片段]}` | 🔴 **fail-open**：口径谓词一条不注入 ⇒ GMV 等**静默算进测试单/退款单/未支付单** |
| `bundle_version` | `policy_gate:109` | `str` | 🔴 **fail-open**：`G2-VERSION` 永不触发 ⇒ 违反 §5.7"旧版本必须显式失效" |
| `max_rows` | `ast_gate:370` | 可选 `int` | 请求级 `max_rows` **静默失效**（恒 `L = 10000`），`api/deps.py` 的 `EXEC_MAX_ROWS` 送不进来 |
| `allowed_constants` | `ast_gate:314` | — | ⚠️ **不走 allowlist 入参**：它是 `run_gate1` 的独立形参 `literal_allowlist` ⇒ 形状设计须交代它从哪来，但**不必进 wrapper** |

- 三条 fail-open（`default_predicates` / `bundle_version` / 以及 `max_rows` 的"请求级参数失效"）是本清单最该被 W0 看见的部分：**它们今天被 `assets` 缺失所产生的"全拒"掩盖着**。

### 6.4 `columns` 必须**双面**（采纳 W2A `RELAY §10` 的实测，我方未独立复现）

同一个槽位被两类读者以**相反**要求共用：

| 面 | 读者 | 要求 |
|---|---|---|
| **可见面** | gate1 列解析（`ast_gate:748/:751`）+ planner/binding | 裁掉 deny 列（"不许被提出来"） |
| **结构面** | gate2 ④ 敏感列复核（`policy_gate:140-143`）、`_column_type`（`ast_gate:879`，R17 隐式转换） | **全列 + 类型** `{列名: 类型}`（"得先认得出来，才拒得掉"） |

- 喂**裁剪列**给 gate2 的实测后果（W2A）：⑤ 双向断言当场抛 `ContractViolationError`；④ 对 `SELECT receiver_phone FROM v_order_paid` **完全没响**（= fail-open 的一半，比崩溃更值得记）。
- `columns` 是 `tuple` 而非 `{列名:类型}` 时的后果：`ast_gate:751` 的 `(...).keys()` **抛 `AttributeError`**（W6 探针正崩在此），且 `_column_type`（`:879`）恒 `None` ⇒ **R17 恒不触发**。

### 6.5 三条禁止修法（`07` v1.6.4 原文，W2C 逐条认可）

1. **只补 `assets` 键** —— `R05` 一解除，其余六条从"被掩盖"变"被暴露"，含两条 fail-open ⇒ **比现状全拒更坏**。（W2A 实测的中间态更早：只补 `assets` ⇒ 三条 SQL 全 `AttributeError`，不是 fail-open 而是崩溃。）
2. **guard 内部自适配** —— `joins` 与 `bundle_version` **在现有端口里根本不存在**（`policy()` 不给）⇒ 派生不出来，多写一层也修不好。
3. **给夹具补 wrapper 键** —— `U-119` 明文禁止；那正是今天 CI 恒绿的做法本身。

### 6.6 W2C 动作清单（总控 2026-09-21 21:58 下达）与当前状态

| # | 动作 | 状态 |
|---|---|---|
| 1 | gate1/gate2 **两处一起**改为消费新方法 | ⏳ **待 W0/W2A 落地**（形状未定就动 = 第三次自造形状） |
| 2 | 删除 guard 内部任何自造形状 / 自适配 | ⏳ 同上。**现状核查**：`ast_gate`/`policy_gate` 只做 `.get(key)` 读取，**没有形状转换层**；要删的是 `ast_gate.py:16-24` 那段"入参形状"docstring 的口径（随动作 1 一起改） |
| 3 | 保留 R06/R07 归因漂移的既有断言口径（集合 `{R06,R07}`） | ✅ **已确认无需改测试** —— `test_gate1_blocks_tenant_id_either_qualified_or_not` 断言的正是集合；依据 = W2A §10 的两档归因实测表 |
| — | 本节落盘（消费方需求，非形状定义） | ✅ 2026-09-21 |

### 6.7 顺序提醒（`07` 原文，不是 W2C 的动作项）

修完 `U-121` 只到 **GATE2 之后**：`gate3_cost`（EXPLAIN 计划 JSON 的来源，`U-63` 已裁"必须经 W2D `exec` 受控入口、节点不得自建连接"）与 `execute`（真 DB + 身份 GUC）**至今 `gate_passed` / `executing` 都为 0，一条都没验过** ⇒ 建议按 `07` 的要求**一次扫完 GATE2/GATE3/EXECUTE 的"判据源"接缝**，别让第六格第三次重演"修一格才发现下一格"。
