# RESUME_BULLETS

> 全部为**实测数字**；没有数字的条目不写。`EX_exec` 只做 coverage 附注，不进主 bullet；
> 不出现"85%""8 秒"这类未达成目标。每条下一行给一条可直接粘贴的复算命令（仓库根）。

---

## 1. 真实数据评测轨

**把 LLM 生成的 SQL 当不可信输入**：为 Text2SQL Agent 建 Olist 真实数据评测轨（60 题冻结集：
55 execute + 5 交互），跑 3 个独立 live 批次，`EX_official = 72.73% ± 1.82%`（n=3；
41/55、39/55、40/55）；分母按 `scored_total` 现算，方言缺口 12/55 单列、不归因模型。
**在 v2 冻结集上做了一轮归因**（37 条 gold 去 `ROUND`、bundle 修 `delivery_late_rate`；v1 原件未改）：
三类桶内失败 58 条次，逐例转等价 **51 条次**（逐批 18/16/17，含 `delivery` 15/15），
另有 2 条非桶转等价、**1 条分母变化**、**2 条回归**，**7 条次旧桶案例仍不等价**
（源：`eval/olist/report_v2.md` §6.1）。31.26pp 是净观测差，**不全部记在修复账上**：
v2/v1 端点不同，交互 `c01`/`r02` 有退化，同端点对照未做。

`复算：` `"$V" -c "import json;r=json.load(open('eval/olist/report_v2.json'));print(r['ex_official'],[(b['scored_passed'],b['scored_total']) for b in r['batches']])"`

## 2. PostgreSQL 生产栈 + 租户 RLS

**在 PostgreSQL 生产栈落地租户 RLS**：迁移 0007 + Olist 五表 **448,152 行**；
`materialize ok=true / consistent=true / checked_assets=5`；`app_ro` 无 GUC 五表全 0，
`T_B` 金丝雀每表 1、删后 0。

`复算：` `"$V" -c "import json;d=json.load(open('backend/reports/w3_demo/materialize_olist_2026-10-28.json'));print(d['ok'],d['consistency'],d['expected_rows'],d['readings']['no_guc'],d['readings']['T_B'],d['cleanup']['T_B'])"`

## 3. 安全面端到端

**三道闸门 + 两段式审计 fail-closed**：AST / 政策 / 成本三闸门在 `execute` 前；
生产栈浏览器 demo **5/5**（4 图 + 1 危险请求拒答），单次跑完 **¥0.02384**；
危险请求"删掉订单表"被拒（原因码 `pii_blocked`，只证明拒答，不证明脱敏链路）。

`复算：` `"$V" -c "import json;d=json.load(open('backend/reports/w3_demo/demo_5.json'));print(d['total_cost_cny'],[(c['demo_id'],c['terminal']['event'],c['chart_type']) for c in d['cases']])"`

## 4. Presenter + 结果级校验

**Presenter 接线生产栈 + 结果级校验**：`ChartPresenter` 出图；结果级校验四条判据
（空结果 / 全 NULL / 单行 KPI 异常 / 守恒式），无基准时跳过而不猜；demo 4 条出图
（bar/bar/bar/kpi）+ 1 条拒答。

`复算：` `cd backend && PYTHONPATH=.. "$V" -m pytest -q tests/unit/test_present_checks.py tests/unit/test_present_chart_selection.py tests/unit/test_present_row_lifecycle.py tests/unit/test_present_insight.py tests/contract/test_present_contract.py`

---

**口径附注**

- `EX_exec = 41/55`（v2，仅 coverage，非官方，不进主数字）；v1 为 `23/55`。
- 三批 live 的 `build.git_rev=aeb53eb`、`build.git_dirty=true`（W2 窗未提交的中间态）；
  最终入库代码 `b780125`。可复算的是命令/冻结件/三批结果件，**不是干净同 rev 复现**。
- v2 三批的端点是百炼 `deepseek-v4.1-flash`（v1 为官方 `deepseek-flash`）；按总控裁定
  合并成一次读数，端点差异在报告里留一句。**交互正确有退化**（`c01`/`r02`），不进 EX 但同框报。
- 72.73% **仍未达** 85% 目标；G-6（P95 ≤ 8s）/ G-8（澄清率）仍 `UNVERIFIED`；
  `6/8 ≠ 门禁通过`。
