# 官方快照决策备忘（W80 · 2026-10-24）

> 决定：**官方快照仍不刷新**。当前官方门禁读数仍是 **`88f3500`／PASS 1/8**，未刷新、非当期读数。
> 本件只回答两件事：为什么现在不刷、什么条件下才允许刷。

## 1. 现读（2026-10-24 14:2x +0800）

| 项 | 值 |
|---|---|
| 文件 | `backend/reports/w6/eval_metrics.json` |
| 自报构建身份（件内 `meta.git`） | **`88f3500`／dirty=false** |
| 自报生成时刻 | `2026-10-07T05:27:34+00:00` |
| 判定计数 | PASS **1**／FAIL 3／PARTIAL 2／UNVERIFIED 2；`summary.all_pass=false` |
| 最后改动该文件的提交 | `24d4477`（ⓘ 与件内自报 rev 不是同一个身份格，引用时两格并报） |
| 当期复算（**非官方**） | `eval/results_w80_gate_recompute.json`：**6 PASS／0 PARTIAL／2 UNVERIFIED／0 FAIL**，rev `26421ae`／dirty=false |
| 当期审计链 | `eval/results_w80_final_audit.json`，rev `26421ae`／dirty=false，`all_checks_pass=true` |

> 两个数必须同框：官方件是 **`88f3500`／PASS 1/8**；当期复算是 **6 PASS＋2 UNVERIFIED**。
> 后者不是官方快照，前者也不是当期读数。

## 2. 为什么仍不刷新

1. **语义**：官方快照的语义是「在 `88f3500` 那棵干净树上、由 `eval/reporter.py` 生成的那一份」，
   不是「最新最好的一份」。刷新一个 6/8 的件会被误读成定稿。
2. **两格是外部阻塞**：G-6 缺 live 预算＋容量决策＋满档 50 并发×10min 的全请求分母；
   G-8 缺 17/18 条补答来源＋绑定型澄清路径＋二轮真跑。没有这些输入，刷新只会把 UNVERIFIED
   固定进官方件。
3. **证据不同源**：当期 G-1/G-4 的集成层复用 W78 `e7fc769`，G-2/G-5/G-7/G-8 用 W77 replay
   `2cd6c92`；它们都绑定了各自 rev/dirty，但**不是同一次全新全量跑**。官方刷新要求八格证据与
   产品代码同 rev，这一条现在不成立。
4. **成本与证据姿势**：成本未在本轮重测。`results_v1`/`results_v2_live` 的 `cost_cny_total=0.391504` 是修复前**下限口径**（W8 RELAY §六.15 明写少算最贵一档；同批评测复算为 ¥1.131531）；W59 全量 166 的 price_guess 为 ¥8.813584；W76 G-8 全批重录估 ¥1.1025。刷新前按当期 budget.PRICES 重算，不得把 ¥0.39 当报价。
   若要与官方快照同 rev 的证据，先在同一 HEAD 重跑 166 replay（零 LLM）对齐 rev；只有需要 fresh live 证据时才出站。G-6 另需 ¥40+ 的压测预算；本轮零 LLM、零出站。

## 3. 刷新条件（必须全部满足）

1. **G-6 与 G-8 都有带证据的 PASS**（不是 PARTIAL／UNVERIFIED／历史读数）；
2. 八格证据与产品代码**同 rev**、`dirty=false`；任一格用旧 rev 的证据都不得冒充；
3. 只许 `eval/reporter.py` 重生成，**禁止手改** `backend/reports/w6/eval_metrics.json`；
4. 同步更新 `backend/reports/w6/评测报告与门禁判定.md`；
5. 刷新后在 `backend/reports/w8/RELAY.md` 与本件记录新 rev／时刻／命令，并保留旧快照指针
   `88f3500` 作历史。

## 4. 刷新方式（条件满足时）

唯一入口 = `eval/reporter.py`（**cwd = 仓库根**；下面的相对路径均按仓库根写；`--help` 为参数权威）。
示意：

```bash
# 条件：G-6/G-8 已 PASS，且两把当期日志/全量结果/红队/探针都与被测代码同 rev、dirty=false
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/reporter.py \
  --results <当期全量 166> \
  --redteam <当期红队产物> \
  --pytest-log <当期离线日志> \
  --integration-log <当期集成日志> \
  --p0-summary <当期取证件> \
  --json-out backend/reports/w6/eval_metrics.json \
  --md-out backend/reports/w6/评测报告与门禁判定.md
```

默认输入路径与备份行为以 `eval/reporter.py` 的 `argparse` 为准；本件不替代其装配口。
刷新后必须重跑本件 §1 的现读，并把「旧快照 `88f3500`」保留为历史指针。

## 5. 本件的失效条件

出现下列任一情况，本件需重写而不是沿用：

- G-6 或 G-8 拿到新的外部输入（预算/补答源）并开始真打；
- `backend/app/**` 出现改动（τ 豁免与 replay 证据的前提被打破）；
- 官方快照被合法刷新（新 rev 替换 `88f3500`）；
- 门禁判据/阈值被总控正式变更（本件不参与判据定义）。

## 6. 证据指针

- 当期审计：`eval/results_w80_final_audit.json`（八格 evidence/rev/dirty/fresh/命令/什么会改变判定）
- 当期复算：`eval/results_w80_gate_recompute.json`（**不是**官方快照）
- 红队：`eval/results_w80_redteam.json`＋尾部归类 `eval/results_w80_redteam_tail.json`
- 最终交付：`backend/reports/w8/DELIVERY.md` 的「终版（路径 A 收口）」节
