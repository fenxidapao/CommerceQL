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
- 🔴 **门数是 3 处、不是 2 处**（W7 回执 + 我方复核）：除上述两个**取用点**外，`policy_gate.py` 内部还有**两个读取面**要一起切 —— `:141` 的 ④（`extract_columns_with_assets` 走 `_resolve_column` ⇒ 依赖可见面）与 `:148` 的 ⑤（`has_tenant_col` 读 `columns`）都必须改读 `all_columns`。**换方法（`:105`）与换读取面是两件不同改动**：只换 `:105` 不换读取面 ⇒ **干净 SQL 当场抛未捕获 `ContractViolationError`（⑤ 先炸，会以 `INTERNAL` 形态出现在预检）**，不是"与今天一样"（档3c 实测，见 §6.4）。

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

- 🔴 **`assets` 这一行还欠一个子槽位**：`assets[物理名]` 里除 `columns` 外还需 **`all_columns`**（结构面，见 §6.4 B1 档）；且 **`columns` 的元素类型必须是 `{列名: 类型}` 而非 `tuple`**（A4 档：元组 ⇒ `ast_gate:751` 抛 `AttributeError`）。⇒ **`assets` 不是"一个键"，是"一个键 + 两个面 + 一层形状"**。

- 三条 fail-open（`default_predicates` / `bundle_version` / 以及 `max_rows` 的"请求级参数失效"）是本清单最该被 W0 看见的部分：**它们今天被 `assets` 缺失所产生的"全拒"掩盖着**。

### 6.4 `columns` 必须**双面**（W2A `RELAY §10` 提出；**W2C 已于 2026-09-21 独立复现**，读数见下）

同一个槽位被两类读者以**相反**要求共用：

| 面 | 读者 | 要求 |
|---|---|---|
| **可见面** | gate1 列解析（`ast_gate:748/:751`）+ planner/binding | 裁掉 deny 列（"不许被提出来"） |
| **结构面** | gate2 ④ 敏感列复核（`policy_gate:140-143`）、⑤ 双向断言（`policy_gate:148`）、`_column_type`（`ast_gate:879`，R17 隐式转换） | **全列 + 类型** `{列名: 类型}`（"得先认得出来，才拒得掉"） |

**W2C 独立复现读数**（探针 `backend/reports/w2c/_probe_u121_faces.py`，**v2**：真 `SemanticBundleRuntime` 输入 + 语义包 `bundle_2026.09.14.1.yaml`，离线不连库；五档互不混写）：

| 档 | 构造 | 干净-不限定 | `deny`-不限定 | `deny`-限定 | `deny`-别名 | 未知列 |
|---|---|---|---|---|---|---|
| **1** 真扁平面（顶层**无 `assets` 键**） | `asset_allowlist` 原样 | gate1 `R05` / gate2 `G2-ASSET` | 同左 | 同左 | 同左 | 同左 |
| **2** 形状顶层 + `columns`=**元组** | `guard_allowlist` 后把 `columns` 顶回 tuple | 🛑 `AttributeError`（gate1@751） | 🛑 同左 | 🛑 同左 | 🛑 同左 | 🛑 同左 |
| **3c** 只换 `:105`、④⑤ 仍读可见面 | 档2 撤 tuple（= W7 档A） | 🛑 **`ContractViolationError`（⑤ 先炸）** | 🛑 同左 | 拒 `G2-DENY` | 拒 `G2-DENY` | 🛑 同左 |
| **3a** 双面齐 + **④ auditor 视图切结构面** + ⑤ 读 `all_columns`（**建议方案 D3**，`columns` 保持可见） | 反事实变体（非生产） | ✅ 过 | 拒 `G2-DENY` | 拒 `G2-DENY` | 拒 `G2-DENY` | gate1 `R06` / gate2 过 |
| **3b** 把 `columns` **顶成全列**（W7 `TierB` 做法，**破坏可见面**） | `columns <- all_columns` | gate1 过 / gate2 过 | gate1 **`R07`** / gate2 `G2-DENY` | gate1 `R07` / gate2 `G2-DENY` | 同左 | gate1 `R06` / gate2 过 |

**三条机制（v2 修正版）**：

- **档1 = "生产今天全拒"的真实机制**：扁平面顶层没有 `assets` 键 ⇒ gate1 `self.assets={}` 全 `R05`、gate2 `:106` 全 `G2-ASSET` —— **资产级拦截，走不到任何列面代码**。⚠️ 我方 v1 曾把"形状顶层 + 元组 columns"（档2）误标为"真 runtime 扁平面"并据此解释 W7 读数 —— **标签错误，已撤**：W7 09-22 复核正确，真扁平面**先被资产级拦截，`ast_gate:751` 的 `AttributeError` 走不到**；那是我手拼"顶层有 assets + 元组 columns"的**假中间态**档。
- **档3c = "(a) 只换 :105 不换读取面"的真实后果**：**不是"与今天一样"（我方 v1 表述错误，已撤），是干净 SQL 当场抛未捕获 `ContractViolationError`**（⑤ `policy_gate:148` 读可见面找不到 `tenant_id`）⇒ 会以 `INTERNAL` 形态出现在预检里 —— **形态比"全拒"更坏**（拒绝是安全出口，未捕获异常是 500）。W7 09-22 指出，我方复跑证实。
- **档3a = 双面的实证价值（v2 关键修正）**：我方 v1 声称"④ 切面后 `deny`-不限定 仍漏检"——**假结论，已撤**。根因是我方 v1 探针里 `extract_columns_with_assets(sql, allowlist)` 仍走可见面（`_Auditor` 只认 `columns` 键），**注释写了"切面"但代码没切**。v2 给 ④ 一份 `columns <- all_columns` 的 auditor 视图后，**不限定形态同样命中 `G2-DENY`**（W7 `TierB` 读数复现，且不动形状）。
- **档3b 的代价 = 列白名单失效（判据⑥下的正确解释，2026-09-23 更新）**：`columns` 顶成全列后，gate1 的**列白名单**（R06）形同虚设（任意真实列都在"可见列集"里 ⇒ 不再有"未列出的列"这一拒绝面）；`deny` 列仍因 `:658` 的 deny 直查落 `R07`。⚠️ v1.6.8 判据⑤曾把 3b 的 `R06→R07` 归因漂移定性为 **error oracle**（列存在性侧信道）并据此禁 3b；**该论证已随判据⑤撤销作废** —— 07 v1.7.1 判据⑥明确要求 `R07`，残余的 `R07`/`R06` 可区分性按 `U-64-④` 方式登记为残余风险（架构原文："不要再为它改冻结集"）。⇒ 3b 仍**不作为落地形态**，理由只剩"保可见面 = 保列白名单 + 保 gate2 ④ 归属面独立"。
- 档3a 的 `未知列` 在 gate2 `pass=True` **不是漏检**：④ 的归属失败即放行，但该 SQL 已被 gate1 `R06` 拒在前面 —— gate2 ④ 的防线职责**只有 deny 复核**（07 §7.4"与 R07 冗余"），未知列归属 gate1。

⚠️ **deny 列的 gate1 归因（判据⑥，07 v1.7.1；2026-09-23 落地）**：
- 判据⑥原文：「deny 列**无论带不带表限定符都必须 R07**」，且**仍禁 gate1 读 `all_columns`**（结构面只对 gate2 ④ 开）。
- 实现 = `ast_gate` 新增 `_is_unqualified_deny()`：`_resolve_column` 返回 `None` 时，先用 `deny_columns` 顶层集合（`<逻辑名>.<列名>`）+ 本 scope 表的**逻辑名**反查，命中即 `R07`；**不读 `all_columns`**。
- ⚠️ 撤销历史：v1.6.8 判据⑤曾要求"deny 列与不存在列**同码 R06**"（anti-oracle）。撤销后 **探针读数不变、解释翻转**：裸写 deny 列的 `R06` 从"正确"变"待修"。W6 红队 `RT-R07-001…004` 曾因该漂移落 `R06` 而失败（`redteam_results.json`），现已具备转绿条件。

`columns` 是 `tuple` 而非 `{列名:类型}` 时的后果：`ast_gate:751` 的 `(...).keys()` 抛 `AttributeError`（**档2** 逐格复现），且 `_column_type`（`:879`）恒 `None` ⇒ **R17 恒不触发**。

### 6.5 三条禁止修法（`07` v1.6.4 原文，W2C 逐条认可）

1. **只补 `assets` 键** —— `R05` 一解除，其余六条从"被掩盖"变"被暴露"，含两条 fail-open ⇒ **比现状全拒更坏**。（W2A 实测的中间态更早：只补 `assets` ⇒ 三条 SQL 全 `AttributeError`，不是 fail-open 而是崩溃。）
2. **guard 内部自适配** —— `joins` 与 `bundle_version` **在现有端口里根本不存在**（`policy()` 不给）⇒ 派生不出来，多写一层也修不好。
3. **给夹具补 wrapper 键** —— `U-119` 明文禁止；那正是今天 CI 恒绿的做法本身。

### 6.6 W2C 动作清单（总控 2026-09-21 21:58 下达）与当前状态

| # | 动作 | 状态 |
|---|---|---|
| 1 | gate1/gate2 **两处一起**改为消费新方法 | ⏳ **待 W0/W2A 落地**（形状未定就动 = 第三次自造形状）。⚠️ 落点是 **3 处**：`gate1_ast:52`（W4）+ `policy_gate:105`（W2C，换方法）+ `policy_gate:141/:148`（W2C，**换读取面**，与换方法是两件改动，见 §6.2/§6.4） |
| 2 | 删除 guard 内部任何自造形状 / 自适配 | ⏳ 同上。**现状核查**：`ast_gate`/`policy_gate` 只做 `.get(key)` 读取，**没有形状转换层**；要删的是 `ast_gate.py:16-24` 那段"入参形状"docstring 的口径（随动作 1 一起改） |
| 3 | 保留 R06/R07 归因漂移的既有断言口径（集合 `{R06,R07}`） | 🔄 **2026-09-23 反转**：判据⑤撤销、判据⑥落地 ⇒ **收回单值 `R07`**（unit 与 eval 两条断言均已改）。原判定"无需改测试"依当时的判据⑤成立，判据换后失效 |
| — | 本节落盘（消费方需求，非形状定义） | ✅ 2026-09-21 |
| — | §6.4 独立复现 + §6.8 默认方案 | ✅ 2026-09-21（探针 v1，A1–A4/B1–B2 六档）——**v1 三处表述已于 09-22 勘误**（见 §6.8 v2 勘误条） |
| — | 探针 v2 重写（真 runtime 输入、五档、撤 v1 假结论）+ W7 三条质疑全部复核 | ✅ 2026-09-22（读数与 W7 `scratch_gate2_face_probe.py` 一致） |

### 6.7 顺序提醒（`07` 原文，不是 W2C 的动作项）

修完 `U-121` 只到 **GATE2 之后**：`gate3_cost`（EXPLAIN 计划 JSON 的来源，`U-63` 已裁"必须经 W2D `exec` 受控入口、节点不得自建连接"）与 `execute`（真 DB + 身份 GUC）**至今 `gate_passed` / `executing` 都为 0，一条都没验过** ⇒ 建议按 `07` 的要求**一次扫完 GATE2/GATE3/EXECUTE 的"判据源"接缝**，别让第六格第三次重演"修一格才发现下一格"。

### 6.8 默认方案（未获决策时按本方案推进；**不阻塞**）

> W7 2026-09-21 回执："遇到我没有决策的，列出默认方案，而非阻塞"。以下每项都标了"若被否，退到哪"。

| # | 事项 | 默认方案 | 若被否（fallback） |
|---|---|---|---|
| D1 | gate1 侧换方法 | ~~W4 在 `gate1_ast.py:52` 改调…~~ ✅ **W4 已落地（`357618f`）**：`gate1_ast.py` 改调 `guard_allowlist`（判据④ 走请求级 `max_rows`）；我方探针 gate1 入口已同步对齐该名 | — |
| D2 | gate2 侧换方法 | ✅ **已落地（本 commit）**：`policy_gate.py:110` 改调 `bundle.guard_allowlist(ctx)`（七键形状，唯一真相 `contracts.GuardAllowlist`） | — |
| D3 | **④ 读取面** | ✅ **已落地（本 commit）**：`policy_gate.py` 新增 `_struct_view()`（`columns <- all_columns` 一次性视图）喂 `extract_columns_with_assets`；**不动形状、gate1 列解析仍在可见面**（判据⑤落点约束） | — |
| D4 | **⑤ 读取面** | ✅ **已落地（本 commit）**：`policy_gate.py` ⑤ `has_tenant_col` 改读 `all_columns`（结构面） | — |
| D2/3/4 配套 | 删自造形状口径 + 夹具随契约更新 | ✅ `ast_gate.py` docstring 的 7 键自造形状段已删（改指 `contracts.GuardAllowlist` 唯一真相）；`guard_fixtures.build_allowlist` 补双面（`columns` 裁 deny 可见面 + `all_columns` 全列）并按真实语义包派生；`FakeSemanticBundle` 加 `guard_allowlist`；`_fullchain_deps.base_allowlist` 补 `all_columns` 键；`test_guard_gate1.test_r07_deny_columns` 单值 R07 → 集合 `{R06,R07}`（可见面下不限定形态归 R06 = 判据⑤明文的正确行为，非放宽：仍禁第三种码） | — |
| D5 | 归因口径 | 🔄 **2026-09-23 反转**：判据⑤（`{R06,R07}` 集合 / 同码 R06）**已撤销**，换 **判据⑥ = deny 列无论带不带限定符都必须 `R07`**。⇒ 断言从"集合"收回**单值 `R07`**（架构 `RELAY.md:1012` 原文："从 `{R06,R07}` 收回单值 `R07`"，并注明放宽责任在架构）。已改：`tests/unit/test_guard_gate1.py::test_r07_deny_columns`、`tests/eval/test_harness_allowlist.py::test_gate1_blocks_tenant_id_either_qualified_or_not`（后者架构只点了前者，属同类放宽、我方一并收回） | — |
| D5+ | **判据⑥ 机械断言**（替代原 anti-oracle） | 探针 `oracle_check` 已改口径：**A = 分类正确**（deny 三形态全 `R07`、不存在列仍 `R06`）；**B = gate2 ④⑤ 对 deny 列仍报 `G2-DENY`**。实测档3a/档3b 双 `A_judge6=PASS` + `B=PASS` | A 不过 = 归因面改错（如 deny 直查被绕过），**停手回查** |
| D5- | **机械守卫不叠层**（W7 2026-09-22 提示） | "生产从哪个方法取"的守卫**已存在且归 W6**：`tests/eval/test_harness_allowlist.py:170-186` 按文件 AST 扫描。⇒ W2C **不另写第二层守卫测试** | — |
| D6 | `all_columns` 的派生源 | 由 W2A 在 `guard_allowlist` 内从**同一份 `Asset.columns`** 派生（`runtime.py:202-203` 已这么做）⇒ 两面结构上不可能漂移 | 若 W0 要求两面**各自独立声明** ⇒ **拒绝**：那正是 `U-121` 的成因复发 |
| D7 | `U-119` 接缝测试 | 输入 = **真** `guard_allowlist()` 输出（不补 wrapper 键），断言普通 SQL `passed=True`；**今天必须红** | 无。补夹具 = 假绿，07 明令禁止 |
| D8 | 我方的落地顺序 | 等 W0 定形状 → W2A 实现 → **W4 与 W2C 同一 PR 窗口内**改三处（`gate1_ast:52`、`policy_gate:105`、`policy_gate:141+148`） | 若 W4 排不开同窗 ⇒ **宁可等**，不单侧先改（单侧 = 两真相，§6.2） |

- 🔴 **D3/D4 是本节最容易被漏的一半**：W7 的"`policy_gate.py:105` 可以动了"**只覆盖方法替换**；只做 D1+D2 而不做 D3/D4 ⇒ 逐格后果 = **档3c**（干净 SQL 抛未捕获 `ContractViolationError`，`INTERNAL` 形态）。**"可以动"≠"动一处就够"。**
- 📌 **v2 勘误（2026-09-22，应 W7 复跑要求）**：我方 v1 三处表述已撤并更正——①"④ 切面后不限定仍漏检"为假结论（v1 探针 ④ 根本没切面）；②"只换 :105 = 与今天一样"应为"当场抛未捕获异常"；③"真扁平面 ⇒ AttributeError@751"标签错误（真扁平面先被资产级拦截，@751 属于"形状顶层+元组 columns"那一档）。探针已重写为五档版（真 runtime 输入），读数与 W7 `scratch_gate2_face_probe.py` 一致。
- 📌 **v4 判据⑥落地（2026-09-23，架构 v1.7.1 换判据）**：
  - `ast_gate` 新增 `_is_unqualified_deny()`：归属失败前用 `deny_columns` 顶层集合直查 ⇒ **裸写 deny 列归 `R07`**（不读 `all_columns`；可见面仍裁 deny 列）。
  - 断言收回单值 `R07`：`tests/unit/test_guard_gate1.py::test_r07_deny_columns` + `tests/eval/test_harness_allowlist.py::test_gate1_blocks_tenant_id_either_qualified_or_not`（架构只点 unit 那条；eval 侧同款放宽一并收回，否则该测试红）。
  - 门禁：pytest unit+contract+eval = **2148 passed / 0 failed**；`pytest tests/redteam` = **11 passed**（架构判据②）；探针判据⑥断言 A/B 双 PASS。
  - ⚠️ **UNVERIFIED**：W7 的评测侧全链复跑（`leaked=0` / `PASS187/FAIL26/NOT_CHECKED25` 与 `RT-R07-001…004` 是否转绿）需重建镜像后由 W7 出读数 —— 我方只到「guard 层红队 11 passed + 归因码实测 R07」。
  - **覆盖面补测（判据⑥ 形态矩阵，探针 `_probe_u121_judge6_shapes.py`，11/11 符合期望）**：6 个语法位置（投影 / 表别名+裸列 / WHERE / ORDER BY / 子查询 / CTE 内）全 `R07`；**JOIN 多义**（`_resolve_column` 返 `None` 但列确实存在）也 `R07`；**反面仍 `R06`**（多义非 deny 列 / CTE 输出列名回避 / 不存在列）⇒ 新分支没有把"多义"顺手并入 deny 面。旧五档探针只覆盖投影列三形态，未覆盖 JOIN 多义。
  - ⚠️ **R13 边界未覆盖**：UNION 分支内的裸写 deny 列仍统一归 `R13`（`_branch_violation`，07 §7.2 原文）；判据⑥未提该形态，**保持原设计不改**，登记为待澄清。
- 📌 **v3 落地读数（2026-09-22 16:4x，D2+D3+D4 同批）** —— 以下为判据⑤当轮的存档读数；判据⑥换后仅"归因码"一列按 §6.4 新段复读：
  - 生产 `run_gate2`（真 runtime、真形状、无修饰）：干净 SQL `pass=True`、deny 三形态（限定/别名/不限定）全 `G2-DENY` —— 此前此档恒 `G2-ASSET`（资产级拦截）。
  - oracle 机械断言（**旧判据⑤口径，已废**）：A（anti-oracle，gate1 R06/R06 同码）PASS + B（④⑤ 冗余复核活）PASS。
  - 门禁：pytest unit+contract+eval = **2141 passed / 3 failed**；mypy app 147 files 0 issues；ruff 全绿；lint-imports 4 kept / 0 broken；DSN 卫生 8 passed。
  - 🔴 **当时剩余 3 红 = W6 到期哨兵（`tests/eval/test_harness_allowlist.py`）**：① `test_gate2_bidirectional_tenant_assertion_raises_on_production_visible_shape`（钉旧生产失效形态，落地后须反转）；② `test_the_dual_shape_view_dies_with_the_consumer_fix`（须删 `eval/harness.py` 的 `AssetAllowlistView`/`GuardAllowlistBundle` 与 `eval/redteam_eval.py` 的 `StructuralAllowlistBundle`/`structural_wrapper`）；③ `test_the_adapters_stated_reason_list_matches_the_code`。**09-23 现状：①②③ 均已不红**（W6/他窗已处理），仅剩 1 条归因断言（本文件 v4 段已收回）。
