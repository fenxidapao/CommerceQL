# G-2 正式豁免／契约处理申请（W8 第 54 轮）

- 申请方：W8 开发窗；申请时点：2026-10-17 19:18 +0800。
- 现读工作树 HEAD：`d61e254`（QA-only；被测代码提交 `b70822e`）。
- 证据：`eval/results_r54_g2_conflicts.json`、`eval/results_g2_r53_clean.json`、`eval/dataset_v1_frozen.json`、`semantic/bundle_2026.09.14.1.yaml`。
- 边界：本申请**不自行豁免**、不改冻结集、不改判据/阈值；在总控裁决前，G-2 继续记 **FAIL／未达门**。

## 1. 结构上限

当前 G-2 分母 = G-2 的 10 条 `execute` 用例；阈值 = `>= 0.95`。10 条整数分子下，PASS 至少需要 **10/10**（9/10 = 90% 不足）。

现读三条均已登记为冻结口径冲突，且在当前 judge 下都为非等价：

| case | QA 现读终态 | 当前结果 | 冲突性质 |
|---|---|---|---|
| `E-VER-01` | `complete` | 预测为 2026-08 的月份天数，gold 为整表 730 天 | 题面有月份、gold 无时间谓词 |
| `E-VER-06` | `complete` | 预测全量活动数，gold 带 `campaign_type='normal_sale'` | 包内 `campaign_cnt` 刻意全量；同包 `M-DIM-04` 又要求无谓词，两个 gold 互斥 |
| `E-VER-08` | `refuse / no_data_asset`（G-2） | 未产出 SQL；57 批同题走 `clarify` | `province_covered_cnt.time_basis=pay_time` 要求时间范围，gold 无时间谓词 |

⇒ 若三条冲突继续非等价，**理论最大等价数 = 7/10 = 70%**，低于 95%；继续改代码不能使 G-2 在当前判据下 PASS。

## 2. 逐条证据

### E-VER-01

- 题面：`T_A 2026-08 的日期维表有多少天？`
- gold：`SELECT COUNT(*) FROM v_dim_date`（全表 730）。
- 包内 `day_cnt`：`semantic/bundle_2026.09.14.1.yaml:908-922`，明确“问某月有多少天须显式加月份筛选谓词”，且 `time_basis=current`。
- 实测：`complete`、非等价；预测 SQL 带 `WHERE year=… AND month=…`。

### E-VER-06

- 题面：`T_A 的活动数是多少？`
- gold：`SELECT COUNT(*) FROM v_campaign WHERE campaign_type = 'normal_sale'`。
- 包内 `campaign_cnt`：同件 `:847-863`，明确“刻意不挂 `campaign_type='normal_sale'`，默认取全量”。
- 冲突旁证：`M-DIM-04` 同指标的 gold 又无该谓词，冻结集内部两条 gold 口径互斥。
- 实测：`complete`、非等价；预测 SQL 为全量 `COUNT(*)`。

### E-VER-08

- 题面：`T_A 的收货省份覆盖数是多少？`
- gold：`SELECT COUNT(DISTINCT region_code) FROM v_order_paid WHERE region_code IS NOT NULL`（无时间谓词）。
- 包内 `province_covered_cnt`：同件 `:887-904`，`time_basis=pay_time`，定义自述“须给时间范围”。
- G-2：normalize 判 `query`，plan 给出缺时间范围 `blocking_issues`，收口 `refuse/no_data_asset`。
- 57：normalize 判 `clarify_needed`，`reason_code=missing_time_range`，在意图层收口 `clarify`。
- 因此跨批差异是**同根因的两条拒绝出口**（plan vs intent），不是新增普通回归；证据见 `eval/results_r54_ever08_cross_batch.json`。

## 3. 可选处置与代价

| 选项 | 做法 | 代价／风险 | W8 建议 |
|---|---|---|---|
| A. 正式豁免 | 总控批准把 E-VER-01/06/08 从 G-2 判分分母排除，另保留 `10 条全量诊断` | 改的是门禁 scope；必须书面版本化；若不保留全量副指标，未来回归可能被豁免掩盖 | 需要总控裁决 |
| B. 契约澄清／改 gold | 统一题面、gold 与包内口径（三选中至少两条冲突必须重新定稿） | 改冻结集或指标口径，等同改验收基准；影响历史可比性，工作量大 | 需要产品/架构共同裁定 |
| C. 重定义分母 | 保留完整 10 条作为诊断，另定义冲突以外子集为门禁分母 | 双重口径易被误读；必须同时在 G-2 行写清分子/分母/冲突外规则 | 若 A 不批，这是唯一透明的禁改路径 |
| D. 维持现状 | 不改任何输入，G-2 继续 FAIL | 项目无法按现判据收口，但没有隐藏风险 | 默认状态 |

## 4. 申请事项

请总控在 A/B/C/D 中明确裁决，并指定若选 B 时谁负责改冻结集或包内口径。W8 在收到裁决前不会自行豁免、删例或改判据。


---

## 5. 第 55 轮状态：总控已选 B，待逐条确认后才落地（2026-10-17 20:05–20:20 +0800｜HEAD `1305ef6`）

- 总控选择：**B 契约澄清/改 gold**；要求 W8 在改冻结基准前先回传逐条 diff。
- W8 已出零出站提案：`backend/reports/w8/G2_CONTRACT_CLARIFICATION_PROPOSAL.md`；机器可读证据：`eval/results_r55_g2_contract_proposal.json`。
- 本件状态：**提案 only**。未改 `eval/dataset_v1_frozen.json`、未改 gold seed、未改语义包、未改阈值/判据/15s、未动 `reports/qa/**`。
- 候选统一哈希（仅内存）：dataset `sha256:31f3385f3a5da8e126cac209d1d812d09dd7c62998f60b0fdde61ac19235d7c5`；seed `sha256:812728f1be0dc1d7e58474f5bfe76c301e60a51f30deb280f232bee72af47466`。文件 SHA 待正式写盘后生成。
- 关键待总控逐条确认：① E-VER-01 新 gold 月份过滤；② E-VER-06 新 gold 全量；③ E-VER-08 新问句/新 gold 补 `2026-08` 支付时间范围；④ 是否接受 `easy×low` 10→8、`medium×low` 10→12 的网格迁移；⑤ 推荐路线不改语义包内容，是否仍要求无内容空跳版。
