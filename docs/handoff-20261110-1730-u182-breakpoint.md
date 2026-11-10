# 断点交接 — 2026-11-10 17:35（U-182 Spider 轨）

> 开机后先读 [`docs/09_当前状态与交接.md`](09_当前状态与交接.md)，再看本页第 5 节复算命令。零花费可复算。

## 1. 锚点（现读）

- HEAD `20af854` / 提交数 **1007**（含本页；本页提交前现读 1006）/ 工作树仅 `?? .codebuddy/`
- `python tools/open_issues.py --check` → `rows=25 OPEN=7 CLOSED=15 WAIVED=3 wip=7/12` exit 0
- `docs/07` 3,763 行未变（v1.7.69）

## 2. U-182 读数（可引用）

- 数据集 523 题（`eval/spider/dataset_ecom7_v1.json`，gold 自执行 523/523、零行 10、含 `ORDER BY` 121、7 库 379 列）
- 严格分母：聚合型 **277** 题 / 纯检索 246 题（不进分母，理由见第 4 节）
- 五批按 `case_id` 去重后：**可判面 277 题 EX 171/277 = 61.73%**
  （源件 `eval/spider/results_batch_r5_denominator_reconcile.json`）
- 逐批：r1 18/24、r2 12/18、r3 46/70（另 165 题 `llm_calls=0`）、r4 **不成立**（`calls=0`，旧 key 打旧端点 400 `Arrearage`，`not_a_reading=true`）、r5 109/185（判 195 题，其中 10 题被字符串判定误收）
- 花费（各批 `budget.spent_cny`）：0.414061 + 0.358245 + 1.073285 + 0 + 3.248973 = **¥5.094564**
- 口径红线：不与 Olist 70.88% 交叉比较；**非 Spider dev 全量**；语义包由 schema 机械派生、指标非业务口径
- **已作废值**：`59.58%`（287 宽松分母）、`0/4`（读 `state['result_rows']`）、`spent 0.0`（`isinstance` 判字符串）

## 3. 凭据与端点（已实测，勿再走错）

- 你指定的 key：`compatible-mode/v1/chat/completions` 200、`apps/anthropic/v1/messages` 200、`apps/anthropic/chat/completions` 404
- 客户端 `backend/app/llm/client.py:364` 只发 `/chat/completions` + `Authorization: Bearer` '⇒ 走 compatible-mode，**未改生产码**
- key 只在仓库外 `CommerceQL-archive/local/u182_llm.env`，未入库、未打印值；要删一句口令即可
- 仓库内 `deploy/.env` 仍是旧 key（旧账户余额 0）—— r1–r4 全部因此 400 `Arrearage`

## 4. 为什么 246 题纯检索不进分母

模型对纯检索题回的 Plan 是 `metrics=[]` + `blocking_issues=[]`，被 `_either_plan_or_blocked` 判非法（`backend/app/planner/schemas.py:325-332`）⇒ `PlanUnavailable(attempts=2)` ⇒ `refuse(no_data_asset)`。这是架构口径冲突，不是模型写错 SQL。

## 5. 复算命令（零花费）

```bash
python eval/spider/build_dataset.py --spider-root <spider_data> --check
python tools/open_issues.py --check
```

派生语义包：`python eval/spider/build_bundle.py --db <db> --spider-root <spider_data>`；包必须过真加载器 `load_bundle`（`semantic/validate_bundle.py` 对派生包是假绿）。

## 6. 未闭环（开机后按此顺序）

1. 无遗留未提交件；`land_u182_reconcile.py` 两笔 + 本页一笔即全部
2. 严格可判面已跑满 277/277 ⇒ 再提覆盖只能扩库（29 库 1,576 题），不是继续抽题
3. 台账 7 条 `OPEN` 未动：`T-04`/`T-06`/`T-07`/`T-15`/`T-16`/`T-18`/`T-20`
4. `U-182` 是否 `CLOSED` 由你定；判据齐但我不自行改状态

## 7. 我犯过并已修正的五处测量缺陷（防复发）

1. 读 `state['result_rows']`（体积字段，恒 0 行，`eval/runner.py:675-681`）
2. `state['cost_cny']` 是字符串，`isinstance` 判数字静默回落 0
3. 按库切分母（零调用题跨库混入，20 条落在前 3 库内）
4. r3 正则判定 vs r4/r5 `'GROUP' in upper`（库名 `cre_Drama_Workshop_Groups` 含 `Groups` 误收 10 题）
5. 用旧 key 打旧端点，把 400 `Arrearage` 误读成「等你账户充值」
