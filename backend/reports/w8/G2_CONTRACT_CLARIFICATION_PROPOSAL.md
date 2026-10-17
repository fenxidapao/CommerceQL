# G-2 契约澄清 B 案逐条 diff 提案（W8 第 55 轮）

- 状态：**零出站提案；未改冻结集、未改语义包、未改阈值/判据/15s、未动 `backend/reports/qa/**`**。
- 现读 HEAD：`1305ef6`；工作树仅 `?? .workbuddy/`（原样保留）。提出时段：2026-10-17 20:05–20:20 +0800。
- 本件目的：按总控已选 B（契约澄清/改 gold），先交三条冲突的 before/after，待总控逐条确认后才落地。
- 依据：`eval/dataset_v1_frozen.json`、`eval/gold_query_seed_v1.json`、`semantic/bundle_2026.09.14.1.yaml`、`eval/case_library.py`、`eval/build_frozen_set.py`、`eval/build_gold_seed.py`。
- 零出站复算：仓库 `.venv` 读 `data/ecom_sandbox.db`（SQLite 只读）与上述 JSON/YAML；未访问网络、未打共享 PostgreSQL。

## 0. 结论先行

| case | 现冲突 | 推荐 B 案 | 结果是否为真实语义修正 | 备注 |
|---|---|---|---|---|
| `E-VER-01` | 题面有 `2026-08`，gold 全表 730 | 改 gold，按 2026-08 过滤 | 是，和 `day_cnt` 口径一致 | 条件数 +2，结构级 `easy→medium` |
| `E-VER-06` | 包内 `campaign_cnt` 取全量，gold 取 `normal_sale` | 改 gold 为全量 | 是，且与 `M-DIM-04` 对齐 | 保持 `easy×low` |
| `E-VER-08` | 题面/gold 无时间范围，包内 `province_covered_cnt` 要求 `pay_time` | 改题面与 gold，补 `2026-08` 支付时间范围 | 是，仍使用事实表指标口径 | 结果值同为 31，但 SQL 语义已明确；结构级 `easy→medium` |

**边界结论**：推荐路线只改冻结评测集/其生成源与派生 seed；**不需要改语义包定义**，因此不应为了本轮做无内容变化的 `meta.version` 空跳版。若总控坚持“语义包版本必须递增”，应作为单独的治理决定处理；若改 `E-VER-08` 为允许无时间，则必须改 `province_covered_cnt` 的 `time_basis` 与定义并升版，不能用只改 gold 绕过。

## 1. 当前冻结物身份

| 文件 | 现读文件 SHA-256 | 现读语义内容哈希/元信息 |
|---|---|---|
| `eval/dataset_v1_frozen.json` | `d0929fb2f09007d6ce30d5660a13c30a2c94a7ba5573633c41f1f62fec11b680` | `dataset_version=1`；`content_hash=sha256:43e153de0203258c3497bd271d73c9a62f5307f907cbe5bff7cad6f5a9fe8609` |
| `eval/gold_query_seed_v1.json` | `67e553424458d12c1dd3b4005ec8117c6b60fa280ce810539134752e86a387b6` | `seed_version=1`；`content_hash=sha256:2b23d7ef4d5d5eb8690699af86237c8413e4e6bf04d9104ad61d17228aa5ea4a` |
| `semantic/bundle_2026.09.14.1.yaml` | `2c802e24f799d2904b369120317bbfd3e2fbb444c7c50462046184039753da82` | `meta.version=2026.10.16.2` |

**统一计划哈希（仅内存复算，尚未写盘）**：按下面三条推荐 diff 一次性修改后，`dataset.content_hash` 候选 = `sha256:31f3385f3a5da8e126cac209d1d812d09dd7c62998f60b0fdde61ac19235d7c5`；对应 seed `content_hash` 候选 = `sha256:812728f1be0dc1d7e58474f5bfe76c301e60a51f30deb280f232bee72af47466`。**新文件 SHA 必须等 `build_frozen_set.py` 写盘后生成，现阶段写 UNVERIFIED，不预填假值。**

### 1.1 当前旧基线复算

```powershell
.\.venv\Scripts\python.exe -X utf8 eval/build_frozen_set.py --no-write
```

实跑：12 格均 ≥8；行为分布 `execute=124 / clarify=18 / refuse=24`；`content_hash=sha256:43e153de...8609`。

### 1.2 推荐 B 案候选复算

已在内存中 monkeypatch `eval/case_library.py` 的三条声明后执行 `build_frozen_set.build(write=False)`；实跑得到 `easy×low=8`、`medium×low=12`，12 格仍全部 ≥8，候选 `content_hash=sha256:31f3385f...d7c5`。该命令不写盘；落地时必须由 `build_frozen_set.py` 正式重算，不得手填 hash。

## 2. E-VER-01：题面要求月份，gold 不能继续全表

### 2.1 现读冲突

- 题面：`T_A 2026-08 的日期维表有多少天？`
- 旧 gold：`SELECT COUNT(*) FROM v_dim_date`（`eval/dataset_v1_frozen.json:38`）。
- 旧结果：`730`；旧 gold result hash：`sha256:16b496dc3e59e31900eadc8ea34f7d81c17dbc66bc5039ceb1c69dad8d00fdba`。
- 包内 `day_cnt`：`semantic/bundle_2026.09.14.1.yaml:908-925` 明写“问某月有多少天须显式加月份筛选谓词”，`time_basis=current`。
- 生成源：`eval/case_library.py:81-83`，当前 `notes` 还写“为保持 easy，条件数必须为 0”，这是旧口径残留。

### 2.2 推荐 after

- 题面：不变。
- 新 gold：`SELECT COUNT(*) FROM v_dim_date WHERE year = 2026 AND month = 8`
- 新结果：`31`；新 gold result hash：`sha256:c1bffd7deb46a23060777bdadfad8d42da45d2ba5b1a50add3365db9836daeff77`。
- `day_cnt` 包定义：**不需要改**；当前定义已经支持“月份筛选”。E-VER-01 只是把 gold 改回定义所要求的行为。
- 结构影响：SQL 条件叶数 2；`easy×low → medium×low`。全网格由 `easy×low=10 / medium×low=10` 变为 `8 / 12`，仍满足每格 ≥8。`notes` 若保留“条件数必须为 0”会与冻结事实自相矛盾，建议同批改为说明月份筛选是本题显式条件。
- 受影响 M/D/E：`E-VER-01` 自身；`M-DIM-03` 只按日期维表分组，不依赖 `day_cnt` 数值，gold 不动；未发现其他 D/E 用例直接复用该 gold。

## 3. E-VER-06：包内全量口径 vs gold 的 `normal_sale`

### 3.1 现读冲突

- 题面：`T_A 的活动数是多少？`
- 旧 gold：`SELECT COUNT(*) FROM v_campaign WHERE campaign_type = 'normal_sale'`（`eval/dataset_v1_frozen.json:228`）。
- 旧结果（`eval_tenant=T_A` 注入后）：`24`；旧 hash：`sha256:82b91475bfef6bda1fa9d517cd3ee39804d3dc28da9965046ad3c14d5f58dd15`。
- 包内 `campaign_cnt`：`semantic/bundle_2026.09.14.1.yaml:847-865` 明写“刻意不挂 `campaign_type='normal_sale'`，默认全量”；数据实测三类为 `normal_sale=72 / prom_618=6 / prom_double11=6`（全库）；T_A 为 `24 / 2 / 2`。
- 同指标冲突旁证：`M-DIM-04` 的 gold = `SELECT campaign_type, COUNT(*) FROM v_campaign GROUP BY campaign_type`（`eval/dataset_v1_frozen.json:1368`），即全类型，不存在 normal_sale 谓词。

### 3.2 推荐 after

- 题面：不变（“活动数”即包内全量口径）。
- 新 gold：`SELECT COUNT(*) FROM v_campaign`
- 新结果（T_A 注入后）：`28`；新 hash：`sha256:b73dcfb64f4e95199c480115f45f7604040d5e9015dc672bd88c17224da6674f`。
- 对齐：E-VER-06 与 M-DIM-04 现在都遵循包内全量口径；不修改 M-DIM-04 gold。
- 结构影响：无（仍 `easy×low`）。
- 受影响 M/D/E：M-DIM-04 仅作为口径一致性对照；不改变其 SQL/hash。未发现其他活动数用例。

## 4. E-VER-08：事实表指标必须带 `pay_time` 时间范围

### 4.1 现读冲突

- 旧题面：`T_A 的收货省份覆盖数是多少？`
- 旧 gold：`SELECT COUNT(DISTINCT region_code) FROM v_order_paid WHERE region_code IS NOT NULL`（`eval/dataset_v1_frozen.json:300-305`）。
- 旧结果（T_A 注入后）：`31`；旧 hash：`sha256:a0b3c1b524fb20987722479c2fbef657cd73096342a271eec179c4507631c89f`。
- 包内 `province_covered_cnt`：`semantic/bundle_2026.09.14.1.yaml:887-905` 明写“订单实际覆盖到的收货省份数（跨列去重，落在事实表）；须给时间范围”，`time_basis=pay_time`。
- 历史终态：G-2 clean 为 `refuse/no_data_asset`；57 族 clean 为 `clarify/field_binding`，二者都非等价；根因是同一“缺时间范围”契约冲突。

### 4.2 推荐 after（主方案）

- 新题面：`T_A 2026-08 的收货省份覆盖数是多少？`
- 新 gold：`SELECT COUNT(DISTINCT region_code) FROM v_order_paid WHERE region_code IS NOT NULL AND pay_time >= '2026-08-01' AND pay_time < '2026-09-01'`
- 新结果（T_A 注入后）：`31`；新 hash：`sha256:a0b3c1b524fb20987722479c2fbef657cd73096342a271eec179c4507631c89f`（结果值恰好与旧口径相同，但时间语义已显式化；不得据此写“无变化”）。
- 包定义：**不需要改**；包内已经要求 `pay_time` 时间范围。
- 结构影响：新增两个支付时间条件叶；`easy×low → medium×low`。全网格同样从 10/10 迁移到 8/12，12 格仍 ≥8。
- 受影响 M/D/E：`E-VER-07`、`M-DIM-08` 是 `v_region` 的清单口径，不应被本改动牵引；`E-VER-08` 是唯一 `province_covered_cnt` 用例。落地时新增契约测试必须同时断言：E-VER-08 gold 含 `pay_time`，E-VER-07/M-DIM-08 gold 仍含 `v_region` 且不含时间范围。

### 4.3 备选 after（不推荐）

若产品决定允许“无时间范围的收货省份覆盖数”，必须修改 `province_covered_cnt.time_basis` 与定义，并把 gold 改为无时间；这会改变生效语义包，升 `meta.version`，并使历史 `time_basis=pay_time` 读数不可直接比较。**不得只改 gold 而保留包内“须给时间范围”**。该备选不是本提案默认路线。

## 5. 一次性落地清单（仅在总控逐条确认后执行）

| 顺序 | 文件/行 | 动作 |
|---|---|---|
| 1 | `eval/case_library.py:81-92` | 更新三条源用例的 question/gold；E-VER-01 的 `notes` 同步 |
| 2 | `eval/build_frozen_set.py:46` | `DATASET_VERSION` `1→2`；运行 builder 重算每例 `gold_result_hash`、结构字段、grid、content_hash |
| 3 | `eval/dataset_v1_frozen.json:30-311` | 生成新冻结集；保留旧版本归档/旧 hash，不手改生成字段 |
| 4 | `eval/build_gold_seed.py:34-35,103` | seed 版本 `1→2`；从新冻结集重新生成，不另写 SQL |
| 5 | `eval/gold_query_seed_v1.json:1004-1112` | 生成新 seed；更新 `derived_from_content_hash`/coverage |
| 6 | `eval/MANIFEST_v1.json:3-5` | 更新 dataset version/content_hash；补新文件 SHA、批准人、修改理由 |
| 7 | `backend/tests/contract/test_semantic_f_coverage_contract.py:205-215` | 增加防漂回：E-VER-01 月份过滤、E-VER-06 全量、E-VER-08 `pay_time` 且不与 E-VER-07/M-DIM-08 混淆 |
| 8 | `semantic/bundle_2026.09.14.1.yaml:847-925` | **推荐路线不改**；仅备选 4.3 改 `province_covered_cnt` 并升 `meta.version` |
| 9 | `semantic/metric_dictionary.md:241-279` | 仅当语义包实际变化时重渲染 |
| 10 | `backend/reports/w8/RELAY.md` / `DELIVERY.md` | 落地后写实际 diff、旧/新 hash、复跑读数 |

### 5.1 版本号判断（需总控裁决）

`semantic/SCHEMA_v1.md:430-433` 写“改本包 → 必须递增 `meta.version`”，并写“冻结评测集不随语义包一起改；语义包升版后，冻结集是否需重生成由 W6 判定”。推荐路线只改冻结集及 seed，不改语义包内容，因此**不应制造无内容变化的包版本跳变**；`dataset_version 1→2` 与 `seed_version 1→2` 足够。若总控仍要求包版本递增，应把代价记为：缓存/few-shot 索引失效、需说明包内容实际未变，不能让版本号成为空承诺。

## 6. 历史读数影响与未决点

- 旧产物（`results_r54_*`、G-2/57 clean 批）继续绑定旧 `dataset_v1_frozen.json` 的 `content_hash=43e153...`；新版落地后不能把新旧读数直接拼接成同一门禁分子/分母。
- 目标复跑只在落地后执行：G-2 10 条目标 10/10；G-5 最小 91 条（67 execute＋24 refuse）另算完整分母；18 条 clarify 只作 G-8 诊断。本轮尚未跑这些，故不写“G-2/G-5 已改善”。
- E-VER-01/E-VER-08 的 difficulty 迁移会使 `easy×low` 少 2 条、`medium×low` 多 2 条；当前 12 格都仍 ≥8，但 `grid` 字段必须由 builder 重算，不能手填。
- E-VER-08 的 `domain` 仍为 `products`（`eval/dataset_v1_frozen.json:301`），而包内指标在 orders 域；这是独立登记项，**本提案不擅自改**。若总控要一并修，需把它作为第 4 条明确 diff 重新批准，并重算 content_hash。
- E-VER-01/E-VER-06/E-VER-08 的 `business_knowledge_required` 目前为空；本提案保持最小改动。若要把它们显式标为 `metric:*`/`time:*`，结构语义轴上可能升到 high 并改变 grid；那属于另一项契约决定，不在本提案中暗改。

## 7. 证据入口

- 机器可读提案证据：`eval/results_r55_g2_contract_proposal.json`。
- 旧基线复算：`.\.venv\Scripts\python.exe -X utf8 eval/build_frozen_set.py --no-write` → 实跑 `content_hash=sha256:43e153...8609`。
- 本次未改任何冻结文件；`git status --porcelain` 应只有 `?? .workbuddy/`（本报告与提案证据为待提交件）。
