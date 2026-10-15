# evidence_main_r31ad —— 主线重启诊断（QA 第 31 轮 R31ad）

> **性质**：总控点句「重启主线」后的**第一步**（QA 自发的**只读**诊断，非 W8 回执验收）。
> **只读 / 零出站 / 零花费 / 不跑 W8 脚本 / 不动容器**。
> **动机**：连 6 轮（`§33`–`§39`）都在修标注/口径，**主线（G-2/G-5/G-7）停两周**。重启第一步 = **先定位真正的卡点**，而不是继续修纪律。

## 一、结论（一句话）

🔴 **G-2（easy×low 0/10）与 G-5（误拒 63/124）是同一根因，且不是 τ、不是打分器、不是 embedding** ——
**是语义包的 `metric` 覆盖不足**：物理列/资产**都在**（`on_sale`／`spu_id`／`sku`／`shop`／`campaign`／`province`／`sku_day_channel` 全在），但**这些题要的指标在 `metrics` 里没有定义**（现只有 9 个 metric：`gmv`／`order_cnt`／`aov`／`arpu`／`refund_rate`／`repurchase_rate_90d`／`uv`／`pay_cvr`／`sell_through_rate`）。

## 二、证据链（五步，逐条可复算）

| # | 断言 | 实跑 | 脚本 |
|---|---|---|---|
| ① | G-2 面 10 条 **全部** `refuse`／`no_data_asset`，且 `expected=execute` | `easy×low = 10｜{'refuse': 10}｜{'no_data_asset': 10}｜expected={'execute': 10}` | `diag_g2.py` |
| ② | **G-2 ⊆ 误拒 63** | `set(G-2) ⊆ set(误拒) = True` | `diag_main.py` |
| ③ | 误拒 63 条 **100% 是 `no_data_asset`**（无第二种理由） | `no_data_asset = 63`（`pii_blocked`/`out_of_scope` 各 9 **不在误拒内**） | `diag_g2.py` |
| ④ | 🔴 **`embedding_unavailable` 不是根因**（**全场伴随**） | 期望 execute 的 124 条：**success 45／45 含（100%）** ⟷ **误拒 63／63 含（100%）** ⇒ 两组**同率** ⇒ 无区分力 | `diag_emb.py` |
| ⑤ | 误拒**停止点全在 `plan → refuse_out`**（非 link 空召回） | `nodes 末位 = refuse_out 63/63`；`retrieval_counts.assets = 8`（**非空召回**）；`gate_decisions` 空 | `diag_g2.py` |

**根因定位（读代码）**：`backend/app/graph/nodes/plan.py:24` ——
> 模型**给出了** `blocking_issues` ⇒ 直接 `refuse(no_data_asset)`，**不发 degraded**（它是产品结论："这问题需要的数据不在语义层"）

⇒ **模型正确地报告"语义层里没有这个指标"** ⇒ 系统正确地拒答 ⇒ **但题面期望它能答**。

## 三、为什么这**不是** τ / 打分器 / 方案 A 的问题

| PRD §12.9 方案 A 三条前置 | 现读 | 判 |
|---|---|---|
| ① L4 触发率 > 10% | **0.0%**（`query_plan` 355 行 L4 = 0） | ❌ 不满足 |
| ② L4 误判 `ambiguous` 是主因 | **bind 层 clarify = 0**；误拒主因 = **plan 层 `no_data_asset`** | ❌ 不满足 |
| ③ 语义层补全后仍不降 | 未取 | — |

⇒ **三条前置全不满足** ⇒ **方案 A 未触发**（PRD 原话「**仅当同时满足**…才评估方案 A」）。
🔴 **更要紧的**：`T-51`（τ 校准）这个方向**本身就不是当前卡点** —— G-2/G-5 的红点**根本不在绑定层**。

## 四、真正该做的（PRD §C.4.6 步骤 4「回看语义包」）

| 缺口 | 题数（估） | 补法 | 工作量 |
|---|---|---|---|
| `metric` 覆盖不足（在架商品数／浏览量／加购／商品数／SKU 数／活动数／店铺数／省份覆盖…） | ≥ 40 | 在 `semantic/*.yaml` 的 `metrics` 里**新增定义**（含 `default_binding` ＋ `default_predicates` ＋ `synonyms`） | 中等（纯 YAML，但**要不要动需总控裁**） |
| 维度 group by 面（`M-DIM-*`／`M-HIER-*`） | 10+ | 同上（部分已有列，缺 metric） | 中等 |
| `sell_through_rate` 是 `draft` 状态 | — | 待业务确认（**不算缺口**） | — |

🔴 **关键约束**：`semantic/**` **不在 W8 `PROMPT.md §1` 的权限清单里**（清单含 `backend/**`／`eval/**`／`frontend/**`／`deploy/**`／`docs/**`／`OVERVIEW.md`／`_refs/`，**无 `semantic/`**）⇒ **扩语义包属"动别的窗写面"** ⇒ **须总控点句**（`PROMPT.md §6` 四例外之一）。

## 五、与冻结集的关系（**必须先说清**）

🔴 **不得**为了迎合这 63 条去改冻结集或改判据 —— 冻结集是**验收标准**，不是待优化的训练集。
✅ **正当做法**：把「语义层缺哪些 metric」当成**产品缺口**来补（补完**重跑**冻结集看 G-2/G-5 是否真降）；**不许**按题面逐条特判。

## 六、文件

| 文件 | 说明 | md5(前 12) |
|---|---|---|
| `diag_g2.py` | ① ③ ⑤：G-2 面／误拒构成／停止点 | `05cca08bffb9` |
| `diag_main.py` | ② ④：同根因验证 ＋ 语义包覆盖对照 | `e2290cf51e89` |
| `diag_emb.py` | ④ 的决定性对照（embedding 是否根因） | `74eb9aca7f7c` |
| `out_g2.txt` / `out_main.txt` / `out_emb.txt` | 三者实跑输出 | — |

复跑（从仓库根）：
```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/qa/evidence_main_r31ad/diag_g2.py
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/qa/evidence_main_r31ad/diag_main.py
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/qa/evidence_main_r31ad/diag_emb.py
```

## 七、本诊断的限制（诚实登记）

| # | 限制 |
|---|---|
| ① | **只在 `eval/results_v1.json`（旧批）上跑**；`results_v2_live_*`（新批）是否同形**未核** |
| ② | 「题要的 metric 缺」是**本窗按题面关键词人工比对**语义包 `metrics` 列表得出的（**不是**跑的判定器）⇒ 数量「≥40」是**估**，非精确 |
| ③ | `plan.py` 的 `blocking_issues` 路径是**读代码**得知；**未**取到单条 record 的 `blocking_issues` 原文（该字段未落评测件） |
| ④ | 未核 `M-DIM-*` 是否真因 metric 缺（也可能是 group-by 面），**列为待核** |
