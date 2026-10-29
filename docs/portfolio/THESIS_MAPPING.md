# THESIS_MAPPING —— 毕设/论文映射

> 目标：把工程资产映射到毕设章节，并把**实验协议**与**口径**钉死，避免"论文里换一种说法"。
> 原则：只报实测；B0 未做就写 `UNVERIFIED`；`6/8 ≠ 门禁通过`。

---

## 1. 章节映射

| 毕设/论文章节 | 本项目对应资产 | 源件 |
|---|---|---|
| **引言 / 相关工作** | Text2SQL 的不可信输入问题；受控管道 vs 开放式 Agent；本项目定位 = "受控 Agent 管道"（固定 19 节点图，不堆多 Agent） | `README.md`、`AGENTS.md`、`docs/07 §3–§5` |
| **威胁模型与受控管道** | 三道闸门（AST / 政策 / 成本）+ 三终态出口 + repair 只回 gate1 + 依赖方向 R-DEP-1..4 | `app/graph/nodes/__init__.py`、`app/guard/*`、`backend/.importlinter` |
| **Olist 语义层与结果级校验** | 薄语义包（`bundle_olist_2018.yaml`，`meta.version=2026.10.27.1`）+ 物化/RLS + 结果级校验四条判据（U-149） | `semantic/bundle_olist_2018.yaml`、`deploy/demo/materialize_olist.py`、`app/present/checks.py` |
| **实验（B0–B3）** | 60 题冻结集 + 3 个独立 live 批次 + 交互题 + 仪器正/负控；B0 未做 | `eval/olist/report.md`、`eval/olist/report.json`、`eval/olist/results_v1_r1..r3.json` |
| **讨论与局限** | 方言缺口 12/55、`AS order` 7/55、`delivery_late_rate` 口径、`ROUND` 容差、R14 月度题、B0 未做、dirty build | `eval/olist/report.md:66-76`、`deploy/demo/README.md §2.6`、本目录 `README.md §7` |
| **可复现章节** | 每个数字一条命令；冻结件哈希；账本；公开仓库检查 | 本目录 `README.md §8`、`docs/portfolio/LICENSES.md` |

---

## 2. 实验协议（写进论文的同一份口径）

| 项 | 值 | 源件 |
|---|---|---|
| 题集 | **60 题冻结集** = 55 execute + 5 interaction（3 clarify + 2 refuse） | `eval/olist/dataset_v1_frozen.json`、`eval/olist/README.md:16` |
| 批次 | **3 个独立批次**（各自进程 + 各自 `--batch-id`：`w2_r1` / `w2_r2` / `w2_r3`），不是"一条命令循环 3 次" | `eval/olist/report.md:3`、`eval/olist/report.json` 的 `batch_ids` |
| 日期 | 2026-10-28 | `eval/olist/results_v1_r1..r3.json` 的 `build.generated_at` |
| 温度 | 所有 LLM 路由 `temperature=0.0` | `backend/app/llm/router.py:202-260` |
| DSN | `postgresql+psycopg://postgres:postgres@127.0.0.1:5432/ecom` | `deploy/demo/README.md:60` |
| 读数身份 | 三批运行时刻 `build.git_rev=aeb53eb`、`build.git_dirty=true`（三批同，W2 窗未提交的中间态）；最终入库代码 `b780125` | `eval/olist/results_v1_r1..r3.json` 的 `build` |
| 冻结件 | `content_hash=sha256:f5e78268…`、`full_hash=sha256:b4491abb…`、`sandbox_db_sha256=17c14cee…` | `eval/olist/report.md:51-53` |
| 预算 | 冒烟 ≤¥5；3 批 ≤¥50；B0 消融 30×4 ≤¥20（**未执行**） | `计划_合并版 §5.4` |
| 改题/改 bundle | **必须升 v2**；不回头改 v1 冻结集 | `计划_合并版 §3.4`、`eval/olist/README.md §6.7` |

**关键口径**：

- `EX_official = grid.scored_passed / grid.scored_total`，`scored_total` **现算**，不抄常量；
  本次三批 `23/54`、`23/55`、`22/55`；r1 的 o19 `GraphRecursionError` 记 `unscored` ⇒ 分母 54。
- 交互题不计入 EX；判据 = `terminal_event == expected_behavior and infra_error is None`；
  本次 refuse `2/2`、clarify `2/3`、`1/3`、`1/3`。
- `sandbox_dialect_gap=12/55`（三批同）**单列、不归因模型**；`EX_exec=23/55` 只作 coverage。
- 仪器正/负控（+55/55、−0/55）**不是模型 EX**。
- 三批的 `git_dirty=true` 必须随论文一起写；**可复算的是命令、冻结件与三批结果件，
  不是一棵干净的 git 树**——不得写"同一 rev 的干净复现"。

---

## 3. 消融 B0–B3 现状（照实）

> ⚠️ 计划只对 **B0** 给出了明确消融定义（`计划_合并版 §3.2` 第 5 条、§5.4）；
> B1/B2 的独立定义与读数在 Phase A **不存在**。本窗不虚构 B1/B2 数字。

| 臂 | 定义 | 现状 | 源件 |
|---|---|---|---|
| **B0** | 30 题子集；schema 从 bundle 的 columns 导出，信息量与 B3 对等；同模型、同温度、同 substrate；**一次调用，不经过语义层/闸门/结果校验** | **`UNVERIFIED`（未做）**；按计划 §3.1 "时间紧可砍"；本窗未跑、不补跑 | `计划_合并版 §3.2` 第 5 条、§5.4；无结果件 |
| **B1** | 中间消融臂（计划未给出独立定义） | **`UNVERIFIED`**；Phase A 未单独跑，不得用 B3 的读数替代 | — |
| **B2** | 中间消融臂（计划未给出独立定义） | **`UNVERIFIED`**；同上 | — |
| **B3** | **当前全系统**：语义层 + 三闸门 + 结果级校验（计划用"信息量与 B3 对等"指代全系统） | 有读数：`EX_official=41.47%±1.33%`（n=3）、交互 refuse 2/2、clarify 2/3·1/3·1/3、方言缺口 12/55、RLS `448,152` 行、demo 5/5 | `eval/olist/report.md`、`eval/olist/report.json`、`backend/reports/w3_demo/materialize_olist_2026-10-28.json`、`backend/reports/w3_demo/demo_5.json` |

> 如果论文必须写 B1/B2/B3 三档消融，正确做法是**先给 B1/B2 下定义、再按 §5.4 预算批准后真跑**；
> 本窗不把"没跑过"写成"没差异"。

---

## 4. 三处口径的原文（不得改写）

以下三段按 `计划_合并版 §5.3` 的措辞写；**不得**写成"门禁通过"：

1. **85%**：任务书原文"SQL 执行准确率目标 85% 以上"。本计划只报实测，不承诺、不改判据；
   报告写"当前 41.47%，未达 85%"。源：`计划_合并版 §5.3`。
2. **8 秒**：任务书原文"平均响应时间目标不超过 8 秒"。G-6 判词仍是**未达成、不可引用**；
   最近压测 p95 8,887.4ms（n=18，含 8 条 `SESSION_NOT_FOUND` 快速失败）**不能当产品延迟**；
   Phase A 用 eval 链路的端到端分位数，报 n、样本构成与批次；未跑写 `UNVERIFIED`。
   源：`计划_合并版 §5.3`、`backend/reports/w8/DELIVERY.md:360`。
3. **6/8 ≠ 门禁通过**：官方快照 `PASS 1/8`（`backend/reports/w6/eval_metrics.json`）与当期复算
   `6 PASS / 2 UNVERIFIED`（`eval/results_w80_gate_recompute.json`）必须同框；G-6、G-8 仍
   `UNVERIFIED`。

---

## 5. 论文里可直接引用的"可复现"材料

| 材料 | 路径 |
|---|---|
| 题集与冻结件 | `eval/olist/dataset_v1_frozen.json`、`eval/olist/dataset_v1.yaml` |
| 三批逐题读数 | `eval/olist/results_v1_r1.json`、`r2`、`r3` |
| 报告（固定五行） | `eval/olist/report.md`、`eval/olist/report.json` |
| 仪器正/负控 | `eval/olist/instrument_control.json` |
| 验真 profile | `eval/olist/olist_profile_frozen.json` |
| 预算账本 | `eval/olist/budget_smoke.json`、`budget_full.json` |
| 沙箱清单 | `eval/olist/sandbox_manifest.json` |
| RLS 物化读数 | `backend/reports/w3_demo/materialize_olist_2026-10-28.json` |
| 5 条 demo | `backend/reports/w3_demo/demo_5.json`、`browser_acceptance.json`、5 张 PNG |
| 许可证 | `docs/portfolio/LICENSES.md`、`backend/reports/w4_acceptance/kaggle_olist_metadata.json` |

> 复算命令逐条见本目录 `README.md §8`；未跑/未做的项一律 `UNVERIFIED`。
