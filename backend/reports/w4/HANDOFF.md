# W4 HANDOFF —— 开窗继承交接（把新窗口变成 W4）

> 生成：2026-09-21｜归属：**W4（阶段 4 · 编排收口）**｜基准：远端 `main`（最近提交 `8a4121a`）
> 用途：**新窗口读到本文即继承本 W4**。每节自包含；关键编号/裁定/卡点都给了出处，别信结论、照位置复核。
> 关联交付：`backend/reports/w4/RELAY.md`（跨窗口持续转述）、`backend/reports/w4/DELIVERY.md`（DoD 自验）。

---

## 一、你是 W4：身份 / 目录 / 提交纪律

- 窗口：**W4**，阶段 4 · 编排收口。负责人是你（读到本文的新窗口）。
- **可写目录**：`app/graph/**`、`app/api/runner.py`（出口帧组装）、`tests/contract/**`、`backend/reports/w4/**`（及本次交接的 `backend/reports/w4/HANDOFF.md`）。
  ⚠️ 严格以 `08 §4.1` 文件归属为准；**不碰** `app/{llm,planner,binding,guard,exec,mask,semantics,retrieval,core}`（W0/W1B/W2A/B/C/D/W3A/B/C）、`frontend/**`（W5）、`reports/{w1a,w1b,w2a,w2b,w2c,w6,w7,arch}/`。
- 提交前缀：**`feat(w4)`** 改代码、**`docs(w4)`** 改文档；**只暂存本窗口文件**，别 `git add -A`。
- 沟通用**中文**；给跨窗口的产出做成**可直接复制粘贴的短回执**（每节自包含）。
- **不猜纪律**：只给可归因的事实/证据；归不了因就明说"待栈/待读数"，绝不把"未接线"说成"已实现"。

---

## 二、硬约束（全项目 + 本窗口，照背）

- **前端零判断权**：任何业务结论不得在前端推断/聚合，只渲染后端给的数据。
- **枚举与 `app/core/enums.py` 逐字对齐**；**不写死一个数值**，能具名引用就具名引用（U-22：不得就地发明数值）。
- **不伪造实现**；`mock` 只在测试层，**禁止用 mock 冒充 BLOCKED/未接线项通过 QA**。
- **门禁 scope 不得缩**（架构裁定：缩 scope = 假绿）。正确修法 = 拆词形 / 补真件，不是绕过。
- **U-16 纪律**：红队 `rewrite`/`warn` 级必须带 `not_blocked` 断言。
- **W7 纪律**："物化 → 判据④采样"之间**不要跑 `tests/integration`**（会静默把 embed_doc 的 embedding/tsv 归零）；要跑请把 `COMMERCEQL_TEST_RW_DSN` 指到一次性库。

---

## 三、门禁（每次结尾必跑，从 `backend/` 目录，venv 在 `..\.venv`）

```
..\.venv\Scripts\python.exe -m ruff check app tests   # 全仓
..\.venv\Scripts\python.exe -m mypy app               # 仅 app，含 tests
..\.venv\Scripts\python.exe -m pytest tests/contract -q --tb=short
```
- ⚠️ **当前契约 suite 有 1 条故意红**：`tests/contract/test_gate_seam_contract.py::test_plain_sql_passes_through_gate_seam`（U-119，见 §六）。这是**有意的**，红 = 缝没修；**不得 skip/xfail/绕绿**。除此之外 contract 应全绿。
- Windows PowerShell 下命令输出可能丢，用 `... 2>&1 | Out-String`（或 `*> 临时文件`）再读。

---

## 四、已收口（本会话已完成，勿重做）

### 4.1 U-107（节点超时 = 客户端超时 + 出路表）—— `app/graph/build.py`
- **6→7 个 LLM 节点**的硬超时 = 该 task 路由模型的**客户端超时**（§10.2 flash 15s / pro 45s），**执行期解析**，不写死一个数。
  实现：`_LLM_NODE_TASKS` → `_client_timeout_for(task)=hard_timeout_s(resolve_route(task).model_key)` → `_effective_limit_for(name, override)`。
  `resolve_route` 对未知 task **fail-fast**（N-21）。
- `NODE_TIMEOUT_S` 现只有**固定非 LLM 节点**：`link 30.0 / gate1 0.1 / gate2 0.1 / gate3 1.0 / execute 30.0 / mask 0.1 / audit_pre 1.0 / audit_supp 0.5`（`bind` 已移出，见 4.2）。
- `link 30.0` 具名引用 `Settings.EMBEDDING_TIMEOUT_SECONDS`（§6.5，默认 30）。
- `_MERGED_NORMALIZE_EXTRA_S=3.5` 是**分配**（预算/占位/over_budget），**不再叠加进 `asyncio.timeout`**。
- `_timeout_fallback`：逐节点复用 §5.3 失败转移列（LLM→降级 refuse、link→`degraded(embedding_unavailable, sparse_only)`、gate1/2/3→GATE_* 码或 `run_gate3(sql,{"explain_error":True})`、execute→`exec_error(timeout)`→EXEC_TIMEOUT、present→`degraded(present_failed,table_only)`）；`_RERAISE_TIMEOUT_NODES={"mask","audit_pre","audit_supp"}`（fail-closed；audit_supp 兼发 complete 终态故不吞，理由已具名注释）。
- 契约：`tests/contract/test_graph_timeout_contract.py`（表值逐字 + 出路表 + fail-closed + overrides）。

### 4.2 U-118①（架构 (B)：bind 并入 LLM 超时）—— 同一文件 + 同一契约
- 删 `NODE_TIMEOUT_S["bind"]=0.2`，`_LLM_NODE_TASKS` 加 `"bind":"l4_score"`（`LlmTask.L4_SCORE` 已注册，FAST，`budget_s=0.8` 是分配非超时）。
- 理由：bind 内部 `score_l4 → port.call("l4_score")` 是真发 LLM（客户端超时 15s），旧 0.2s = U-107 同款病害"预算当硬超时"。
- 契约：`EXPECTED_TIMED_NODES` 删 bind、`EXPECTED_LLM_NODES` 加 bind + 断言 `_effective_limit_for("bind")==_client_timeout_for("l4_score")>0.2`。

### 4.3 U-115（plan_blocked 外部可读）—— `app/api/runner.py::_extras`（REFUSE_OUT 分支）
- 累积 state 的 `intent_detail` 若 `reason_code=="plan_blocked"`，把 `blocking_issues` 拼进 refuse 帧（现成出口，不新开）。
- **⚠️ 仍 OPEN（不要关）**：只有 PLAN 自拒触发；bind-超时/UNRESOLVED 的 refuse 帧**无**该字段 ⇒ 外部仍只能靠 `node_timeout_degraded{node}` 日志计数区分。这正是"U-115 缺口仍在"的证据。测试 `test_decision_table_b_c.py::test_c_plan_blocked_refuses_with_blocking_issues_in_frame` 已锁。

### 4.4 U-119（闸门接缝契约测试）—— `tests/contract/test_gate_seam_contract.py`
- Test A：真 `SemanticBundleRuntime(load_bundle(…bundle_2026.09.14.1.yaml)).asset_allowlist(ctx)` **原样**喂 `run_gate1`/`run_gate2`，断言普通 SQL `SELECT pay_amount FROM v_order_paid` 过闸 `passed=True`。**今天红**（`assets` 取不到→R05）。
- Test B：删 mandatory 资产→断言被拒（对照组，绿）。
- **U-121 由 W0/W2A/W2C 修形状后，Test A 必须反绿**。新窗口收到"U-121 形状已合"通知时，先跑这条确认。

---

## 五、当前卡点（G-6，归属要分清——多数**不是** W4 的活）

- **λ 演进**：bind 0.2s 掐死（已修，4.2）→ 现在唯一卡点 = **τ 未校准**：`binding_tau_is_calibrated=false`（L4 分数不可用）。W7 判据：先看 `sql_ready` 0→≥1；不达标再看 `binding_layer` 是否落"澄清分支"（那是卡点后移 τ 校准，**非 (B) 没生效**）。
- **GATE3 / EXECUTE 判据源整条未验**（`gate_passed`/`executing` 恒 0）：
  - GATE3 判据源 = EXPLAIN 计划 JSON，**U-63 须经 W2D exec 受控入口**（节点不得自建连接）。⚠️ U-107 超时 fallback 的 `run_gate3(sql,{"explain_error":True})` 是短路 WARN，**非**真 EXPLAIN 路径。
  - EXECUTE 判据源 = 真 DB + 身份 GUC。
  - 这两格缺 U-119 类接缝锁，**待架构/W2D 立号**，W4 不擅自发明出口；只要 W2D 给真 EXPLAIN/SQL 结果，W4 可承接消费侧断言。
- **GATE1 缝**：`gate1_ast.py:52` 的 `deps.semantics.asset_allowlist(identity)`（扁平）→ `run_gate1`（期待 wrapper）。**形状 U-121 定案前别动手、别加适配层**（否则造第三份真相）。**换形状时保留模块 docstring §二的"与 gate2 各取一次是刻意的"设计，别合并成一次取用**。gate2 侧 W4 不改（`policy_gate.py:105` 是 W2C）。

---

## 六、U-121 定案后 W4 的动作项（现在按住，收到"已合"再动）
1. `app/graph/nodes/gate1_ast.py:52` 换调 W0 新方法；`run_gate1(sql, allowlist)` 入参形状随 U-121 变。
2. 跑 U-119 Test A 确认反绿；若没反绿，查形状≠W0 显式形状（不是改测试适配）。

---

## 七、W4 名下待办（open，勿擅自关）
| 编号 | 事项 | 合作方 | 状态 |
|---|---|---|---|
| U-115 | blocking_issues 出口仍只覆盖 plan_blocked，bind-超时不可外部归因 | W2B/W2C | **OPEN**（见 4.3）|
| U-117 | bind 无条件发 L4 出站 = 浪费；先读数再定（`binding_layer` 里 L4 占比 ≈0⇒升 P1 改条件触发 / >0⇒已知代价）| W4+W3C | P2 待读数，**不阻塞** |
| RELAY 登记 | 新窗口把 §四/§五/本节的落地与卡点逐条落进 `backend/reports/w4/RELAY.md`，并在 `DELIVERY.md` 订正受影响的完成声称 | — | 待续 |
| GATE3/EXECUTE 接缝锁 | 待架构/W2D 立号（见 §五）| W4+W2D | 未立号 |

---

## 八、跨窗口协作现状一句话
- W7 压测/预检已给足读数；跑批仍**等 W7 报"已拿 go"**，不主动压额度。
- 架构 07 到 **v1.6.4**；给受范围内 U-号前**先报架构要号**（避免撞号，架构明令"窗口不得自占号"）。当前已知号：U-107/108/112/113/114/115/117/118/119/121。
- 资源红线：**严禁擅自用 AI 生图/生视频**（耗额度）；涉及花费金额操作先征得用户同意。

---

## 九、开窗后头三件事
1. `git pull origin main`，确认基准在 `8a4121a` 附近。
2. 跑 §三门禁（接受 U-119 那条故意红）。
3. 读 `arch/RELAY.md §10/最新节` + `backend/reports/w4/RELAY.md`（W4 侧全部转述），把 §四~§七登记进 RELAY，再按 §五确认卡点归属未变。