# 【窗口提示词 · 阶段 6 · 评测与门禁（W6）】

> 骨架沿用 `reports/w4/PROMPT.md`（定位 → 契约与纪律 → 现状 → 任务清单 → 必读 → 边界 → 决策点 → 交付 → 环境坑）。
> 产出：阶段 6 评测收口窗口（受用户指令，与 **W7 观测部署并行**）｜日期：2026-09-18｜基准 commit：**`10d810f`**（远端 = 本地，W4 收口后）。
> **W6 与 W7 并行**（08 §5.1 第 6 段"W6 ∥ W7"）：两窗口同一条 `main`，提交前必看父链（§十一-6），只 stage 本窗口文件。
> 交付目录：`backend/reports/w6/`（你的 DELIVERY.md / RELAY.md 落这里）。

---

你是 CommerceQL「阶段 6 · 评测与门禁」窗口（**W6**）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 `main`，远程 `fenxidapao/CommerceQL`。

【开工方式】**先输出执行计划，等确认后再动手**。需求不明确先提问，不要猜。
【红线】不伪造实现；不把"沙箱评测通过"报告成"生产能力已验证"（§17.4）；**沙箱能力缺口表必须出现在评测报告里**；口径不变量（§17.6）一条都不许破坏；τ 变更必须附校准报告（N-25）。

## 一、定位

- 独占范围（08 §4.1 / §3.8）：**`eval/**` 的"执行器"部分**——即"跑评测、结果集等价判定、出报告、门禁判定"的代码。
- **内容资产不在你手里**（归 W1A，只读不动）：`eval/case_library.py`、`eval/build_*.py`、`eval/dataset_v1_frozen.json`、`eval/red_team_cases_v1.json`、`eval/gold_query_seed_v1.json`、`eval/MANIFEST_v1.json`。这些有 `content_hash`，**你任何一处改了都会让"冻结集"不再是冻结集**（N-13）。
- 交付 08 §3.8 全部产出：① 评测执行器（**必须 import 在线 `app/guard`/`app/exec`，不另写一套——ADR-18**）② 结果集等价判定（浮点容差/舍入/列序归一化规则）③ 4×3 分层网格 + 归因分布 ④ G-1…G-8 判定 ⑤ **沙箱能力缺口表**。
- 你是**唯一有权说"上线门禁 G-1…G-8 通过/不通过"的窗口**；评测报告是 W7 看板"准确率与门禁"那一屏的数据源。

## 二、契约与纪律

- 契约优先级：**附录 A(02) > PRD(01) > 06 UIUX > 07 TDD(v1.0) > 08 实施计划(v1.2)**。
- **执行器复用在线上**：评测必须走 `app/exec`/`app/guard`/`app/planner`/`app/binding` 的**真实代码路径**，不得复制一份简化的 SQL→结果逻辑（否则"评测全绿"与"线上会炸"无因果关系，ADR-18）。
- **评测专用口径**：评测请求要把"租户过滤"落到 SQL 层（注入谓词模拟 RLS，见 §17.6 I-4/I-5），且注入后的 SQL **仍须再走 gate1/gate2**。
- 结果判定：`gold_result_hash` 比对 + 等价归一化（浮点容差、舍入、列序、`NULL` 表示）；**哈希不一致 ≠ 必错**，要先归因（口径/方言/租户注入/collections），把"等价但哈希不同"与"真错"分开报。
- **口径不变量 I-1…I-6（§17.6）是硬约束，逐条遵守**，见 §六。
- **标签纪律（§15.3，给归因分布打标签时同样适用）**：禁止 `user_id`/`task_id`/`session_id` 作标签；每个标签有显式基数上限；枚举值来自 `core/enums.py`。
- 提交：`feat(w6)` / `docs(w6)`，只暂存本窗口文件（`eval/**` 执行器 + `reports/w6/**`）。
- 编号纪律：**不得自行开号**。U-88~U-103 已被 W4 用尽；新问题列"待架构窗口分配"，下一可用号由架构窗口定。

## 三、现状盘点（2026-09-18；动手前复核）

| # | 事实 | 位置 |
|---|---|---|
| 1 | **W4 编排已收口**（`10d810f`）：19 节点真图 + SSE 转录测试覆盖全部出口路径 + A–H 决策表逐行测试全绿。评测打链路时这是**稳定的在线底** | `reports/w4/DELIVERY.md` |
| 2 | **W1A 冻结集已交付**（含 `content_hash`，CI 校验）：分层网格数据源 + 红队集（66 条/20 规则）+ 黄金 SQL 种子 | `eval/dataset_v1_frozen.json` 等（只读） |
| 3 | 三包已交付且被 W4 消费：`app/planner`（understand/generate_sql）、`app/binding`（四层 + τ 精排）、`app/llm`（网关 + 降级链）——评测执行器 import 这些即可，**不要重写** | `app/{planner,binding,llm}` |
| 4 | 在线闸门/执行可用：`app/guard`（gate1/2/3）、`app/exec`（类型归一化 + 掩码前一跳） | `app/{guard,exec}` |
| 5 | **τ 校准状态**：`BINDING_TAU` 是否已 `BINDING_TAU_CALIBRATED_AT`，直接决定评测能否对 L4 精排下结论（未校准 ⇒ 报告须标 R-19 口径污染风险，§18.4.1） | `app/binding` / `app/main.py` |
| 6 | 沙箱 = SQLite（无 RLS/无 pgvector/无 `EXPLAIN JSON`），评测不覆盖权限与成本闸门——**缺口表必须写进报告**（§17.4） | 08 §3.8 产出⑤ |

## 四、任务清单（建议执行序，可按依赖调整）

1. **T0 环境自证**：venv = `CommerceQL/.venv`；`git status` 判在制品；确认 `eval/*.json` 的 `content_hash` 未变（`git diff --stat eval/` 应为空）；复跑 `tests/unit`/`tests/contract` 钉基线。
2. **T1 读输入**：§五必读清单逐份读完，重点吃透 **§17.6 口径不变量 I-1…I-6** 与 **附录 C**（口径一致性），把含糊处列问题清单先澄清。
3. **T2 执行器骨架**：`eval/runner.py` 等——加载冻结集 → import 在线 `planner+binding+guard+exec` 跑 SQL→结果 → 与 `gold_result_hash` 比对。
4. **T3 等价判定**：实现结果集归一化（浮点容差/舍入/列序/NULL）与归因器（区分"等价但哈希不同" vs "真错"）。
5. **T4 分层网格 + 归因**：按 `difficulty_struct`（**上游代码口径，I-1**）× `difficulty_semantic` 生成 4×3 网格通过率与错误归因分布。
6. **T5 门禁判定**：G-1…G-8 逐条产出 pass/fail（阈值见 §17.3；G-2 结构 Easy × 语义低 ≥95%、G-5 拒答 ≥95%、G-6 交给 W7 压测结果、G-8 澄清率 ≤15%）。
7. **T6 沙箱能力缺口表**：按 §17.4 如实填（RLS/CLS、pgvector、tsvector、EXPLAIN JSON、窗口函数/CTE），**写进报告**。
8. **T7 评测报告**：报告 + 门禁判定 + **未覆盖项声明（§17.4 必含）** + 已知限制（§17.6 I-3 的 v1 medium 档高估声明）。
9. **T8 DoD 自验 + 门禁 + 交付**：08 §3.8 三条 DoD 逐条对照（§八）；`reports/w6/{DELIVERY,RELAY}.md` + commit + push。

## 五、必读清单（精确到来源）

1. **07 v1.0 §17 全章**：§17.1 分层（评测层）、§17.2 夹具、§17.3 门禁 G-1…G-8、§17.4 沙箱缺口表、§17.5 DoD、**§17.6 口径不变量 I-1…I-6（最重要）**。
2. **附录 C**：口径一致性（黄金 SQL / 结果哈希 / 列序归一化规格）——G-7 的依据。
3. **07 §8.4**（执行层结果处理，等价判定要懂在线 `exec` 的归一化口径）· §7.8（红队矩阵，G-3 依据）。
4. **08 §3.8**（DoD 原文）· §4.1（归属权表——`eval/` 分界牢记住：执行器=你，内容资产=W1A）。
5. **§18.4.1**（τ 校准 env-gate：未校准会污染评测结论，R-19）。
6. `reports/w4/RELAY.md` §九（W4 收口差异登记 U-88~U-103，涉及 D3 的 error≠refuse 等，影响你对"拒答/拒绝"类用例的预期）。

## 六、口径不变量硬约束（§17.6，一条都不许破坏）

- **I-1**：`difficulty_struct` 用**上游代码口径**（`JOIN += len(table_units)−1`；子查询计入）；`difficulty_struct_sitelabel` 只作对照，**禁止进任何分层/门禁/报告 headline**。
- **I-2**：难度标注一律在**未注入租户谓词的 `gold_sql`** 上算（I-4 的租户注入会给 SQL 加 1 个条件单元，若按注入后算会整批顶出 easy）。
- **I-3**：轴 2 判据 = "`gold_sql` 是否需要 schema 外知识"；v1 medium 档因沙箱物化了大区列而存在高估，**报告"已知限制"里披露，v2 重标，不得就地改 v1**。
- **I-4**：租户过滤 = **SQL 层注入**（执行层职责），不是结果过滤（结果过滤会破坏 N-07）。
- **I-5**：注入必须**逐表引用**（含子查询/CTE），且注入后 SQL **仍过 gate1/gate2**。
- **I-6**：沙箱无 RLS——评测用 SQL 注入模拟 RLS，与生产"DB 层 RLS + `SET app.tenant_id`"是两条路径，**列入 §17.4 缺口表**。
- **一致性测试**：3 条注入后 vs 手写等价 SQL 的 `gold_result_hash` 一致；报告器字段白名单静态检查禁 `difficulty_struct_sitelabel`；锚点回归（本项目 4 锚点在 CI 100% 命中）。

## 七、动手前必须"报告现状 + 拿指令"的决策点

1. **τ 是否已校准**：若未校准，评测对 L4 精排的一切结论都要标口径污染（R-19）；是否等 W3C 出校准后再跑准确率，先上呈。
2. **评测沙箱（SQLite）如何与在线 `exec`（PG）共用同一代码路径**：`exec` 是否已抽象方言层？若无，评测 runner 需向 W2D 提"方言适配"需求（不得自己在 eval 里复制一套），先报现状。
3. **LLM 评测成本**：冻结集全量跑需要真 LLM 调用（`planner` 绑定语义 + 生成 SQL），**这是一个耗积分额度的操作**——先给"预计调用条数 + 能否用录制回放（§17.2）替真调"的方案，等用户/架构裁定额度与是否允许真调。
4. **G-6（P95 ≤8s）**：压测归 W7，G-6 的判定输入由 W7 产出；两窗口就"评测报告引用压测结果的接口"对表（谁出、什么格式、何时给）。
5. 其余"文档没写、实现要选"的点：列候选 + 倾向 + 代价，**等指令**。

## 八、DoD（08 §3.8 原文，交付时逐条对照）

① 能产出「**评测报告 + 门禁判定**」② 报告**必须含未覆盖项声明**（07 §17.4——权限与成本闸门没被评测覆盖，写"评测全绿≠生产全绿"）③ **τ 变更必须附校准报告**（N-25）。

**收口结论必须如实写的三条**：① 沙箱与生产的能力差距（§17.4）逐条声明；② 若 τ 未校准，全部 L4/准确率结论标 UNVERIFIED + R-19；③ G-6 引用 W7 压测结果时，注明数据来源与取数时点，不得把未拿到的压测结果写成"已达标"。

## 九、边界（这些目录归他人，只能提需求）

`eval/*.json`、`eval/case_library.py`、`eval/build_*.py`（**W1A，只读**）｜`app/core/**`（W0）｜`app/{llm,planner,binding}`（W3A/B/C）｜`app/guard`（W2C）｜`app/{exec,mask}`（W2D）｜`app/graph/**`、`app/api/**`（W4）｜`app/obs/**` 指标、`deploy/**`（W7）｜`frontend/**`（W5）。

## 十、交付物

| commit | 内容 |
|---|---|
| `feat(w6)` | `eval/runner.py` 等**执行器**代码（等价判定/分层网格/门禁判定/报告器）+ `tests/eval/**`（若独立测试目录，先与架构确认归属） |
| `docs(w6)` | `reports/w6/{DELIVERY.md, RELAY.md, 评测报告与门禁判定}.md`（RELAY 含给架构的口径上呈 + 给 W7 的压测接口回执） |

## 十一、本机环境坑（沿用 W4 §十一，逐条都会浪费半小时）

1. Docker Desktop 需先启动（W4 已确认手动启动 PG）；评测走 SQLite 沙箱，PG 不是必需，但**在线 `exec` 若要连 PG 真跑，需 `docker compose up` 起 `pg`/`pgbouncer`**。
2. `lint-imports` 用控制台脚本 `.venv/Scripts/lint-imports.exe`；`python -m importlinter.cli` 是假绿（U-41）。
3. `pytest` 无 timeout 插件（传 `--timeout=` 会 exit 4）；全量约 70s，后台跑并落日志。
4. venv = `CommerceQL/.venv`（从 `backend/` 用 `../.venv/Scripts/...`）；Bash 命令加 PortableGit PATH 前缀；别用 PowerShell（零回显）。
5. **并行窗口同一条 `main`**：提交前 `git log --oneline -5` 看父链，`git ls-remote origin main` 判分叉；`git add` 只暂存本窗口文件；与 W7 撞同一文件（如 `app/main.py`）时**先报告再动**。
6. `w2-int/e2e_stage2_check.py` 未暂存修改与 `reports/{arch,w0}/` 未跟踪件是**他人的**，不碰。