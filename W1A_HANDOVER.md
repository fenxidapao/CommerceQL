# W1A（阶段 1A · 地基）交付与交接

> **作者窗口**：W1A　**日期**：2026-09-16
> **任务书**：`docs/08 §3.2`
> **自检入口**：`./.venv/Scripts/python.exe data/generator/selfcheck.py`　→ **32 项：PASS=30 / FAIL=0 / SKIP=2**
> **纪律**：本文只记录「已实测」「已自证」「未决」三类，**不含推测**。凡未跑过的都标 UNVERIFIED。
> **⚠️ 本轮（v2）性质**：`07` 已升到 **v0.8 并新增 §4.7 裁定 `U-23`～`U-33`**。本文档本轮的**全部改动 = 把那份裁定落进产物**，
> 不是新增功能。**凡"已落地"的条目都给出产物位置（文件 + 键名），不给结论性措辞** —— 这是 §4.7.4 的教训（见 §2.4）。

> **修订记录**
> - `2026-09-16` 初版交付（DoD 六条自证通过，24 项自检）。
> - `2026-09-16` W0 回执落地（`main @ aef8750`）：转达项 ①② 关闭；新增护栏 `test_no_undeclared_third_party_imports` → 新增 **§2.3**；L8 由"已知限制"改"已消解"；§7.1 前提修正（**W1B 与 W1A 同期并行**）。
> - `2026-09-16` **v2｜落 `07 §4.7` 的 11 条裁定**（本次）：语义包删 2 字段 / 收窄 1 / 加 `default_reason` / 登记 U-28 两跳；校验器 **27 → 34 项**（含 3 条**负向断言**）；`SCHEMA_v1.md → v1.1`；`MANIFEST` 新增 `measured` 段；`layering.py` 官方锚点降级 + **新立本项目 4 级 6 条锚点**；`selfcheck` **24 → 32 项**。新增 **§2.4**（§4.7.4 的 3 处更正登记）、**§5 的 L9 / L10**。


---

## 1. 交付物清单（全部在本仓库内，可直接 review）

| 路径 | 内容 | DoD |
|---|---|---|
| `semantic/bundle_2026.09.14.1.yaml` | 3 域语义包（orders/products/traffic），8 资产 / 9 指标 / 6 维度 / 105 别名 / 15 黑话 / **10 条 join** | ①⑤⑥ |
| `semantic/SCHEMA_v1.md` | 语义包字段契约，**v1.1（已按 §4.7.1 同步）** —— **W2A 的动手依据** | ①⑤⑥ |
| `semantic/validate_bundle.py` | 07 §6.1 五步校验器，**34 项断言**（含 3 条负向 + 3 条双向） | ① |
| `semantic/metric_dictionary.md` | 指标口径字典 —— **由 YAML 渲染**（`render_metric_dictionary.py`），杜绝两份真相 | — |
| `data/schema.sql` | SQLite 沙箱 DDL（**契约声明件**，非生产 DDL 真相）+ V0–V7 变体落地方式说明 | ② |
| `data/generator/seed_generator.py` | 确定性生成器（纯标准库，命名子种子，14 类脏度全注入） | ② |
| `data/generator/layering.py` | 4×3 分层判定器（**按上游 evaluation.py 原样实现**）+ 锚点回归 | ③ |
| `data/generator/selfcheck.py` | DoD 逐条自证脚本（32 项） | 全部 |
| `data/ecom_sandbox.db` | 沙箱数据物 **420.3 MB**（**未入库**，见 §5-L4） | ② |
| `eval/case_library.py` | 用例库（声明式，166 条） | ②③ |
| `eval/build_frozen_set.py` | 冻结集构建器（真实执行 → hash → 机器分层 → 网格断言） | ②③ |
| `eval/dataset_v1_frozen.json` | 冻结集 v1，124 execute + 18 clarify + 24 refuse | ②③ |
| `eval/build_red_team.py` / `eval/red_team_cases_v1.json` | 红队集 v1，66 条，**20/20 AST 规则全覆盖** | ④ |
| `eval/build_gold_seed.py` / `eval/gold_query_seed_v1.json` | few-shot Gold Query 种子 119 条（**由冻结集派生**） | — |
| `eval/MANIFEST_v1.json` | 可复现证据链（**含 `measured` 实测段** + 名义参数 + 库/生成器 sha256 + 网格计数 + 3 条实测发现） | ② |
| **`backend/reports/w1a/RELAY.md`** | **逐窗口可直接粘贴的转述件**（每节一个收件人） | — |

---

## 2. DoD 六条自证（逐条给证据，不是声称）

| DoD | 结果 | 证据（产物位置） |
|---|---|---|
| ① 3 域语义包通过 §6.1 五步校验 | **PASS** | `validate_bundle.py`：**34 项，PASS=31 / FAIL=0 / SKIP=1 / WARN=2** |
| ② 冻结集含 `content_hash`（N-13） | **PASS** | `dataset_v1_frozen.json` → `content_hash = sha256:43e153de…`；`--check` 重算一致（**盘上 hash 与重算 hash 逐字节相同**） |
| ③ 4×3 网格每格 ≥ 8 | **PASS** | `dataset_v1_frozen.json` → `grid.*`：12 格最小值 **8**，合计 **124** 条 |
| ④ 红队覆盖 20 条 AST 规则 + 跨租户 + ~~RLS/~~truncated | **⚠️ 部分** | `red_team_cases_v1.json` → `coverage.ast_rules_covered` = **20/20**；`RT-XT-*` 3 条 + `RT-INJ-002`；`RT-LIM-*` 4 条。**RLS 专项未达成 —— 见 §2.2** |
| ⑤ `default_binding` 与别名表就位 | **PASS** | YAML → `field_bindings[]` 6/7 有 `canonical_asset` + `default_reason`（1 条刻意 `ambiguous`）；`metrics[]` **8/8** 活跃指标有 `default_binding{asset,reason}`；`aliases[]` 105 个 term 一对一 |
| ⑥ 维度含 `grain_level` | **PASS** | YAML → `dimensions[]` 6 个全有 `grain_level` **与** `grain_levels`；且 `grain_level == grain_levels[hierarchy 末项]` 6/6 |

### 2.1 我额外加的五条"防两份真相"断言（不在 DoD 里，但必须做）

| 断言 | 结果 | 为什么 |
|---|---|---|
| DDL 列名 ↔ 语义包 `assets[].columns` 逐列一致 | PASS（8 张表全一致） | 否则 DDL 与语义包会各说各话 |
| 沙箱库 sha256 ↔ MANIFEST 一致 | PASS（`eb35a97f…`） | "数字类结论可复现"的物证 |
| **MANIFEST.measured ↔ 沙箱库现场复算** | PASS（**8 张表逐表一致，2,024,778 行**） | ★ 本轮新增。**"名义/实测分开"只是第一步**：没人复算的话，MANIFEST 里的数字仍只是一句自称 → 库一改而不更新 MANIFEST，自检就变红 |
| `metric_dictionary.md` / `gold_query_seed_v1.json` ↔ 上游源一致 | PASS | 两者都是**派生视图**，不许手改 |
| **结构分层锚点回归（本项目 4 级 6 条）** | PASS（**6/6 命中**） | ★ 本轮新增。锚点是**唯一会随口径漂移的断言**：若有人动了 `spider_level`，4×3 网格会**整批一起变而看起来正常**，只有锚点会立刻红 |

### 2.2 明确 **不归 W1A / 未达成** 的项（标 SKIP，不冒充通过）

| 项 | 状态 | 说明 |
|---|---|---|
| 07 §6.1⑤ 的「jieba 词典可加载 / 分词函数可用」 | **不归 W1A** | 归 **W2B**（`retrieval/tokenizer.py` 是唯一入口，N-24）。W1A 的校验脚本**刻意不 import `app.*`**，以保证独立运行 |
| 08 §3.2 DoD④ 的「**RLS 专项**」 | 🔴 **未达成** | 66 条红队产物逐项核对：跨租户 ✅（`RT-XT-001~003` + `RT-INJ-002`）、truncated ✅（`RT-LIM-001~004`），但 **RLS 没有独立用例** —— 只有 2 条的 `why` 提到 RLS。**根因**：沙箱是 SQLite，**物理上没有 RLS**（`data/schema.sql` 自陈），生产侧的 RLS 是"DB 层 RLS + `SET app.tenant_id`"，评测侧只能用 SQL 注入**模拟**（07 §17.6 不变量 I-4/I-5/I-6），而"注入后执行 + 存在性不泄露"的断言**属执行层 → W6**。<br>→ **已提请架构窗口把 DoD④ 拆成「SQL 层（W1A，已完成）」+「RLS 层（W6/PG）」两段**；该问题需**新编号**，请架构窗口按 §4.8 区间表分配（W1A 的 `U-23~U-33` 已用尽，**不自行开号**） |

### 2.3 W0 新增护栏的通过证据（`test_no_undeclared_third_party_imports`）

W0 于 2026-09-16（`main @ aef8750`）在 `tests/contract/test_dependency_whitelist.py` 新增 AST 扫描护栏，**扫描范围含 `semantic` / `data` / `eval`（即 W1A 的三个目录）**。这直接影响 W1A 的交付物，故已实测复核。

| 检查 | 结果 | 证据 |
|---|---|---|
| `pytest tests/contract/test_dependency_whitelist.py` | **14 passed in 1.21s** | 含新增的幽灵依赖检测 |
| W1A 目录被真实纳入扫描 | ✅ | 扫描 88 个 `.py`，其中 `semantic/` 2 + `data/` 3 + `eval/` 4 = **9 个** |
| W1A 文件的第三方 import 全已声明 | ✅ | 仅 2 个：`sqlglot`（`data/generator/layering.py`）与 `yaml`（`semantic/validate_bundle.py`、`semantic/render_metric_dictionary.py`、`data/generator/selfcheck.py`）→ 均已声明 |
| `eval/*.py`（4 个）+ `seed_generator.py` | ✅ 零第三方 import | 印证"纯标准库、无新依赖"的交付声明 |
| **违规项** | **无** | 另写独立 AST 探针从零复算，结论与护栏一致（非空跑）；探针跑完已删 |

> **纪律（W0 明确要求，W1A 照办）**：`semantic/` 与 `data/` 若还需要别的包，**不得靠传递依赖**，须走 `docs/08 §4.3` 提给 W0。

### 2.4 ⚠️ `07 §4.7.4` 点名的 3 处「交接文档与产物不符」（**登记 + 处置**）

架构窗口在 `§4.7.4` 核出 3 处我的自述与实际产物不符，**2 处成立**。逐条登记并已修：

| # | 我原来的措辞 | 实测 | 处置 |
|---|---|---|---|
| 1 | 「（U-31）订单总数 494,249 **并如实写进 MANIFEST**」 | ❌ **不成立**。当时 `MANIFEST` 里**只有名义值** `sandbox.params.order_rows_total: 500000`，**全文无 `measured` 键** | ✅ **已修**：`MANIFEST_v1.json` 新增 `measured` 段（8 张表逐表实测 + 逐租户 + 3 条 findings），并新增 `nominal_vs_measured_discipline` 说明；另加 **selfcheck 额外②b** 做现场复算断言。**且同步改了 `assets[].row_estimate` → 实测值**（8 处） |
| 2 | 「（L5）零分母 SKU 指定集**未导出（没写进 MANIFEST）**」 | ⚠️ **表述过头**：MANIFEST **有** `zero_denominator_sku_count: 40`（只有数量、无清单）→ "指定集未导出"成立，"没写进 MANIFEST"不成立 | ✅ **已改**：表述订正为"**清单**未导出"；真缺口 = 40 个 SKU 的**具体名单**（做 V6 变体前需要） |
| 3 | 「（L7）`dimensions.time` 多绑定形态，附录 B **只给了单绑定示例**」 | ❌ **不成立**：附录 B §B.1.2 的 time 维度示例**本身就是多绑定**（`bindings: {day/week/month: pay_time}`）→ 多绑定**有上游依据** | ✅ **L7 关闭**（无需 W2A 反馈） |
| 4 | 「（U-24）`08 §4.1` **只写** `semantic/**`」 | ⚠️ **表述过头**：`08 §4.1` **已有** `semantic/**` 与 `eval/dataset_*` 行，真正缺的是 `data/**` | ✅ 已由架构窗口补 `08 §4.1`，U-24 销账 |

> **这一节的教训（已内化为纪律）**：交接文档的价值在于"**让审计者可以不信任何一句话就完成核对**"。
> 当"已落地"这类**结论性措辞**与产物不符时，危害不是"少做了一件事"，而是**审计者会依据它跳过核对**。
> → 本文 v2 起，凡"已落地"条目**必须给出产物位置（文件 + 键名）**，给不出的标 UNVERIFIED。

---

## 3. 关键设计决定（附理由与代价）

| # | 决定 | 理由 | 代价 |
|---|---|---|---|
| D1 | **`gold_sql` 不含 `tenant_id`**，租户由评测器在**资产边界**注入（`tenant_wrap`） | ① 语义包明写该列「不暴露给模型生成」；② 实测：`tenant_id` 会额外算 **1 个 WHERE 条件单元** → `others +1` → 把整批用例顶出 `easy`，使 **`easy × 高` 这一格不可达**（而 DoD③ 要求 12 格全达标） | W6 执行器必须真正做租户注入。**07 §4.7.1 已裁定采纳**，并补 5 条硬约束（§17.6 不变量 **I-1…I-6**） |
| D2 | ~~`assets[].grain_level` 用独立的"资产细度档"刻度（1–6）~~ → ❌ **已按 §4.7.1 删除** | 裁定理由：① 07 全文仅出现一次、无消费者；② 与 `dimensions[].grain_level` **同名不同义**（"两套刻度永不比较"是我自己立的纪律，**同名是最容易被违反的形态**）；③ §6.8 步③ 用 `asset.grain`（枚举 token）已足够 | 已删全部 8 处 + 头部刻度表；**加了负向断言防它复活**（`validate_bundle.py` 的 `REMOVED_FIELDS`） |
| D3 | 冻结集的 `difficulty_struct` 由 `layering.py` **机器判定**，用例库**只写 tags** | 防"看起来对"：人写级别必然向期望靠拢 | 用例作者必须先算清 `c1/o/c2` 才能命中目标格（本库每块注释都标了它靠什么落格） |
| D4 | 数据物 **420.3 MB 不入 Git**，改为"脚本 + 固定种子 + sha256" | 已裁定：>50 MB 只入库脚本与 hash | clone 后需跑一次生成器（实测 **4 分 12 秒**，单核纯 Python）。`MANIFEST.sandbox.git_tracked = false` |
| D5 | `metric_dictionary.md` 与 `gold_query_seed_v1.json` 均为**派生视图** | 同一事实只写一遍（U-18 教训） | 需在 CI 里跑两个 `--check`（**尚未挂 CI**，见 L8） |
| D6 | 红队集的 `rewrite`/`warn` 级**一律带 `not_blocked` 断言** | U-16：把这级写成"拒绝"就是实现缺陷 | 构建器会在缺断言时**直接 FAIL**，防悄悄退化 |
| **D7** | `difficulty_struct` **= 上游代码口径（唯一主口径）**；`difficulty_struct_sitelabel` **降级为对照字段** | §4.7.2：可复现；**换站点口径会让 `extra` 从 28 条塌成 3 条 → DoD③ 直接不达标** | 对照字段**禁止进任何统计/门禁/报告 headline**（`MANIFEST.layering.comparison_only_dialect` + §17.6 I-1 一致性测试②做静态白名单检查）；官方 4 锚点降级为差异记录，**另立本项目锚点**（见 L10） |
| **D8** | **区间关联不新增 join 类型**，只能经 `v_dim_date` **两跳**，且**必须在 `joins` 里显式登记** | §4.7.1（U-28）：保住 `joins ⊆ 等值列对` 这个**可机器校验的不变量** | ⚠️ 实测两个陷阱必须带 `note`：① `pay_time`(timestamptz) → `date_key`(date) **非裸等值**；② `dim_date`（公共）→ `campaign`（租户）是**跨租户边界的边**，不写租户谓词会 **3 倍扇出**。校验器已加"危险边必须带 note"断言 |

---

## 4. 未决项登记（已完成 / 阻塞 / 假设）

> **没有任何一项阻塞 W1A 的交付**（包括裁定项 —— 11 条已全部落地产物）。

### 4.1 `U-23`～`U-33`：**已由 07 §4.7 裁定，本轮已全部落地**

| 编号 | 裁定结论 | 我的落地状态 | 产物位置 |
|---|---|---|---|
| **U-23** | 采纳 3 / 收窄 1 / **删除 2** | ✅ **已落** | 删 `assets[].grain_level`（8 处）+ `field_bindings[].default_binding`（6 处）；`metrics[].default_binding` 收窄为 `{asset, reason}`（删 `time_field` 8 处）；新增 `field_bindings[].default_reason`；`ambiguous ⇒ canonical_asset 为空`（本就为空，现加**双向断言**） |
| **U-24** | 采纳（`08 §4.1` 补 `data/**`） | ✅ 上游已补，销账 | — |
| **U-25** | ✅ 采纳 `meta.embedding.{model,dim}` | ✅ 已在位，校验器步骤⑤断言一致 | YAML `meta.embedding` |
| **U-26** | ❌ **不采纳** `meta.disclosure_text`；载体 = `insight.caveats[]` | ✅ **已落** | 删 YAML 的 `meta.disclosure_text`；在 YAML 文件头写明披露链路（指标层 `reason` / 概念层 `default_reason` / 去重→字典序→≤40 字 / **禁塞 `scope.notice`**）；`SCHEMA_v1.md §1.2`；校验器加**负向断言** |
| **U-27** | ✅ 采纳（`receiver_city` 已实测落库） | ✅ 一致，待上游回填附录 C | `data/schema.sql` + YAML `assets[order_paid].columns` |
| **U-28** | ✅ 采纳"不新增 join 类型"，**只能经 `v_dim_date` 两跳**，且语义包**必须显式登记** | ✅ **已落**（**本轮新增 3 条 join**：7 → 10） | YAML `joins[]` 最后三条；每条带 `note`；`SCHEMA_v1.md §6.2`。⚠️ 见下方"新发现" |
| **U-29** | ✅ 采纳我的诊断（`len(get_nestedSQL())`，子查询计入） | ✅ 一致，待上游改写 §C.3.1 | `layering.py` 头部 + `comp2_setops` 对照列 |
| **U-30** | 维持上游代码口径为唯一主口径；`_sitelabel` 降级对照；官方锚点降级差异记录 + **新立本项目锚点** | ✅ **已落** | `layering.py`：`OFFICIAL_ANCHORS` / `PROJECT_ANCHORS`（4 级 6 条）/ `DIVERGENCE_SQL`；`--anchors` 退出码即门禁结论；`selfcheck 额外⑤` |
| **U-31** | ✅ 保空区间；⚠️ **但"已写进 MANIFEST"不成立 → 补 `measured` 段** | ✅ **已落**（见 §2.4 第 1 条） | `MANIFEST_v1.json` 的 `measured` + `nominal_vs_measured_discipline`；YAML 的 `row_estimate` 改实测 |
| **U-32** | ✅ 保留 `region_name`，标注为 `value_map` 派生列；轴 2 的 `medium` 档高估**必须在报告披露** | ✅ **已落**（披露义务写进契约） | `SCHEMA_v1.md §7` 的 **D-5**；`data/schema.sql` 的 `v_region` 注释；评审报告属 W6 |
| **U-33** | ✅ 采纳"执行层注入" + 5 条硬约束（§17.6 I-1…I-6） | ✅ 一致（D1） | `eval/build_frozen_set.py` 的 `tenant_wrap()`；`SCHEMA_v1.md §7` **D-4** |

### 4.1b ⚠️ 裁定落地过程中**新发现的两个问题**（都已给物证，均未擅自改上游/未擅自开号）

| # | 发现 | 物证 | 处置 |
|---|---|---|---|
| **N-1** | **§4.7.2 锚点③ 的括号注与它自己指定的唯一主口径冲突**。裁定写「3 表 JOIN + WHERE + GROUP BY（`comp1=4`）→ `hard`」；按上游代码实算 `comp1 = (3-1)+1+1 = 4` → 三条 hard 子句**全不满足** → **`extra`**。**`comp1=4` 落 `extra` 正是 U-30 的结论本身** | `layering.py --anchors` 的"分歧点"段：`comp1=4`，采纳口径 = `extra`，裁定描述 = `hard` | **不按那句话写锚点**，改按**真实边界**写；并把该 SQL 作为"分歧点锚点"**故意保留**（若哪天它变成 `hard`，说明 `spider_level` 被人改了 → 那必须先改 `07 §4.7.2` 与 `§17.6 I-1`）。**与 U-35 同族，需回填 07 / 附录 C** |
| **N-2** | **U-28 的两跳路径不是"理想的等值两跳"**，有两个会**静默算错**的陷阱：① `order_paid.pay_time` 是 `timestamptz`、`dim_date.date_key` 是 `date` → 写 `ON pay_time = date_key` **恒假 → 静默 0 行**；② `v_dim_date` 是公共日历（`tenant_scoped: false`）而它的 `campaign_id` **只有 4 个 PROM 值、且这 4 个 id 在 3 个租户里都存在** → 不把租户谓词落在 `campaign` 侧会**一条 dim_date 行匹配 3 条 campaign 行 = 3 倍扇出，聚合值静默变大** | `MANIFEST.measured.findings` 的 **M-1 / M-2 / M-3**（含实测数字：102/730 天有值、4 个 id 各自命中 >1 租户） | 已在 `joins[].note` 写明处置；`SCHEMA_v1.md §6.2` 逐条列出；校验器新增**"危险边必须带 note"**断言（跨租户 / 跨类型两类，缺 note 即 FAIL）。**第三个推论必须进评测报告**：该路径**只覆盖大促**，日常促销在 `dim_date` 里**无映射** → "活动订单"口径不完整（`SCHEMA_v1.md` 的 **D-6**） |
| **N-3** | **`grain_level` 的"默认层级"读法未定死** → §4.7.1 要求的断言**无法唯一实现**。裁定说它"必须等于 `grain_levels` 中该维度的默认层级值"，但"默认层级"没有任何承载位 | 我采用"默认层级 ≡ `hierarchy` 末项"（可机检、6/6 通过）；但若裁定本意是"**`binding` 的粒度**"，则 `region`(4→3) 与 `category`(3→1) 要改 | **不擅自改、不擅自新增字段**（改它需新增 `default_level`，**附录 B 无承载位 → 属 U-34 范围**）。→ 做成**每次跑都会出现的 WARN**（`validate_bundle.py` 第 20 项），确保不被忘掉。**属已裁定的 U-23 残留，不新开号** |

### 4.2 要**转达**给其它窗口的（W1A 不动别人的文件）

> **逐窗口可直接粘贴的版本在 `backend/reports/w1a/RELAY.md`**（每节一个收件人）。下表只是索引。

| 转达对象 | 内容 | 性质 |
|---|---|---|
| **W0**（`pyproject.toml` / `.importlinter` / `.gitignore`） | ① PyYAML 白名单；② `!ecom_sandbox.db` 反向放行 —— **两条均已于 2026-09-16 由 W0 关闭**（`main @ aef8750`，CI success；另同类补登 4 个包，文档侧 U-37）。**仅剩一个请求**：W1A 的 **5 个 `--check`（frozen / red_team / metric_dict / gold_seed / **anchors**）尚未挂 CI**，"未漂移"只能靠人手动跑 → 接不接？**不接也请回一句**（我记成 L8 遗留项） | ✅ 已关闭；余 1 项**不阻塞** |
| **W1B**（alembic / 数据层，**与 W1A 同期并行**） | ① `data/schema.sql` 是**契约声明件**，不是生产 DDL 真相；RLS/GRANT/触发器**只由你的 alembic 产出**；② 角色名统一 `app_ro` / `app_rw`（早期写 `app_readonly`，勿沿用）；③ U-28 的迁移约束**先等架构窗口裁定**（裁定已下：**不新增 join 类型**，经 `v_dim_date` 两跳） | 接口对齐 |
| **W2A**（语义层） | 🔴 **`SCHEMA_v1.md` 已升 v1.1，字段契约变了**（删 2 / 收窄 1 / 加 `default_reason`）→ **按 v1.1 动手**。三条硬约束：① L2 判"同粒度"用 **`grain_level` 数值相等**，**禁用 `hierarchy` 下标**；② `metrics[].default_binding` **形状恰好 `{asset, reason}`**，时间基准读 **`time_basis`**；③ `ambiguous ⇒ 无 `canonical_asset`/无 `default_reason`（**双向**）。另：W0 新护栏扫 `semantic`/`data`/`eval`，**新包别靠传递依赖** | 🔴 **关键路径** |
| **W2B**（检索/分词） | 07 §6.1⑤ 的「jieba 词典可加载 / 分词函数可用」**归你自证**；W1A 校验器刻意不 import `app.*`（那一项是 SKIP，**不是通过**）。可直接读 `aliases`（105）/ `blacklist_terms`（15）/ `meta.embedding` | 分工 |
| **W2C**（闸门 `app/guard/**`） | 红队集 66 条已就位；`rule_id` 直接取自 `enums.AstRule`、严重度取自 `enums.AST_RULE_SEVERITY`（**都不另立编号/映射**）。**`rewrite`/`warn` 级绝不能被实现成"拒绝"**（U-16），每条都带 `not_blocked` 断言，构建器缺断言会直接 FAIL | 纪律 |
| **W2D**（执行 `app/exec/**` + 脱敏 `app/mask/**`） | 与你的 DoD 强相关的我的产物：① `truncated` **只由 LIMIT 触发**（`RT-LIM-001~004`，含 1 条**反向断言**：聚合结果不得置 truncated）；② 类型归一化：沙箱 8 张表的列类型见 `data/schema.sql`（与 YAML 逐列一致，有断言）；③ `app_ro` 写操作必须失败 —— **沙箱无 RLS/角色**（D-4），这条只能在 PG 侧验 | 接手项 |
| **W4**（阶段 4 编排收口） | 红队集消费方；`gold_sql` 不含 tenant（U-33）；LLM 提示层注入集**不在 W1A 范围** | 分工 |
| **W6**（评测执行） | 冻结集 / MANIFEST / 红队集 / Gold 种子的消费方。四条最容易踩：① `gold_sql` **不含 tenant**，按 `eval_tenant` 在**资产边界**注入（`tenant_wrap()` 可复用）；② `gold_result_hash` **由真实执行产生，禁止手填**，且**行序不参与 hash**；③ **6 个格子刚好 8 条（贴线）** → 冻结后勿再动用例库；④ 沙箱是 SQLite，**不覆盖 RLS / CLS / pgvector / EXPLAIN JSON** → "评测全绿"≠"生产全绿"。**另：U-28 的两跳路径只覆盖大促 + 有 3 倍扇出风险（N-2），必须进报告"已知限制"** | 接手项 |
| **W6**（承接 DoD④ 的 RLS 层） | 见 §2.2：RLS 专项**未达成**，执行层断言归你；已提请架构窗口拆 DoD④ 并分配新编号 | 🔴 **待裁定** |
| **上游文档窗口**（PRD / 附录 B / 附录 C） | ① **U-29**：附录 C §C.3.1 的 Component2 定义引用了死常量 `HARDNESS`（真正生效的是 `len(get_nestedSQL())`，子查询计入）；② **U-27**：附录 C §C.11.2 缺 `receiver_city` 列；③ **U-28**：§C.11.3 的区间关联在 `joins` 契约里**只能经 `v_dim_date` 两跳**，请明确该路径；④ **U-34**：§4.7.1 的扩展字段在附录 B 均无承载位；⑤ **U-35**：官方四级锚点与代码口径在 Hard 档不一致；⑥ **U-36**：§C.11 的 `v_region` 只列了 `code`（实测 3 列） | 6 条 |
| **架构窗口** | ① **DoD④ 需拆分**（RLS 层归 W6）→ **请分配新编号**；② **N-1**：§4.7.2 锚点③ 的括号注与采纳口径冲突（需回填）；③ **N-3**：`grain_level` 的"默认层级"读法需一句话定死（若取"binding 的粒度"读法则我必须改 `region`/`category`） | 3 条 |

---

## 5. ⚠️ 交付里**未完成 / 有已知限制**的部分（不隐瞒）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| L1 | **V1–V7 数据变体的 patch 脚本** | **未实现** | `data/schema.sql` 末尾已写明做法（V0 全量 + 确定性 patch），但 `variants.py` 尚未写。附录 C §C.5.3 的"每条用例至少跑 V0 + 1 个随机变体"因此**当前跑不了** |
| L2 | **红队集只覆盖 SQL 层攻击面** | 已知限制 | `RT-INJ-003`（提示词套取）等 4 条只是"期望行为"声明；**LLM 提示层的注入测试集不在 W1A 范围**（属 W4/W6） |
| L3 | **4×3 网格贴线** | 已知限制 | 6 个格子刚好 **8 条**（DoD 下限）。任何一条用例被判 invalid 都会立即破格 → 建议 W6 冻结前不要再动用例库 |
| L4 | **沙箱库未入库** | 已知限制 | 420.3 MB；clone 后必须跑一次生成器（4 分 12 秒）。`MANIFEST` 里有 sha256 可校验 |
| L5 | **"零分母 SKU"的**清单**未导出** | 小缺口 | 生成器内部有 40 个确定性 SKU，`MANIFEST.measured` 记了数量、**没有名单**。要做 V6 变体需先暴露（见 §2.4 第 2 条：v1 时我把这条写成"没写进 MANIFEST"，**表述过头**，已订正） |
| ~~L6~~ | ~~`assets[].grain_level` 无上游消费者~~ | ✅ **已关闭** | 07 §4.7.1 裁定**删除**该字段（理由与我 L6 的观察一致）。已删 8 处 + 加**负向断言**防复活 |
| ~~L7~~ | ~~`dimensions.time` 多绑定形态待 W2A 反馈~~ | ✅ **已关闭** | 附录 B §B.1.2 的 time 示例**本身就是多绑定** → 有上游依据，无需反馈（§4.7.4 第 3 条） |
| L8 | **W1A 工具链需用 `CommerceQL/.venv`**（根因已关闭，**遗留 1 项**） | **部分消解** | 根因（PyYAML 只以传递依赖存在）已由 W0 `aef8750` 转正 → 干净环境 `pip install -e backend` 后不再断。**仍保留的纪律**：复现一律用 `./.venv/Scripts/python.exe`。**未做完的**：5 个 `--check`（frozen / red_team / metric_dict / gold_seed / **anchors**）**尚未挂进 CI** → 归 **W0 或 W6** 决定是否接线（已问，不阻塞） |
| **L9** | **DoD④ 的「RLS 专项」未达成** | 🔴 **未达成** | 见 §2.2。沙箱物理无 RLS；语义层跨租户用例已做（`RT-XT-001~003` + `RT-INJ-002`），**执行层断言归 W6**。已提请架构窗口拆 DoD④ 并**分配新编号** |
| **L10** | **官方锚点与裁定描述的冲突已保留为物证** | 已登记 | 官方 4 锚点在采纳口径下 **Hard 一条必然不符**（= U-30）；且 **§4.7.2 锚点③ 的括号注与采纳口径冲突**（= N-1）。两者都**不作为门禁**，门禁 = 本项目锚点 6/6（`layering.py --anchors` 退出码） |

---

## 6. 复现步骤（任何人可独立重跑）

```bash
cd CommerceQL

# ⚠️ 必须用本仓库的 venv 解释器，**不要用裸 `python`**
PY=./.venv/Scripts/python.exe        # Windows
# PY=./.venv/bin/python              # Linux/macOS

# 1) 生成沙箱数据（4 分 12 秒，纯标准库）
$PY data/generator/seed_generator.py --out data/ecom_sandbox.db

# 2) 校验语义包（**34 项**）
$PY semantic/validate_bundle.py

# 3) 重算冻结集并校验未漂移
$PY eval/build_frozen_set.py --check

# 4) 红队集覆盖度自证
$PY eval/build_red_team.py --check

# 5) 派生视图同步性
$PY semantic/render_metric_dictionary.py --check
$PY eval/build_gold_seed.py --check

# 6) 锚点回归（**退出码 = 本项目锚点是否 100% 命中**；官方锚点只作差异记录）
$PY data/generator/layering.py --anchors

# 7) 一键全跑（**32 项**）
$PY data/generator/selfcheck.py
```

### 6.1 2026-09-16 复核记录（全部用 venv 解释器重跑，落裁定之后）

| 脚本 | 结果 |
|---|---|
| `validate_bundle.py` | **34 项：PASS=31 / FAIL=0 / SKIP=1 / WARN=2**（WARN = jieba 归 W2B 之外的两条：`grain_level` 读法待确认、2 个概念无别名） |
| `build_frozen_set.py --check` | 12 格全 ≥ 8（最小值 8，合计 124）｜`content_hash = sha256:43e153de…`｜**未漂移**（改 `layering.py` 前后哈希相同） |
| `build_red_team.py --check` | 66 条｜20/20 规则｜`sha256:886cb570…`｜**未漂移** |
| `render_metric_dictionary.py --check` | OK，与语义包同步（`rate_hash=ecbcb01b08d9563e`） |
| `build_gold_seed.py --check` | 119 条种子 / 124 条冻结集｜**已同步** |
| `layering.py --anchors` | **本项目锚点 6/6 命中**（exit 0）｜官方锚点：主口径 3/4（Hard 不符 = U-30）、对照口径 4/4 |
| `selfcheck.py` | **32 项：PASS=30 / FAIL=0 / SKIP=2**（2 个 SKIP = jieba 归 W2B、RLS 专项未达成） |

venv 实测版本：`PyYAML 6.0.3`（2026-09-16 起为**显式依赖**）、`sqlglot 30.18.0`（白名单内）、`jieba 0.42.1`、`pydantic 2.13.5`。`langgraph==1.2.11` / `langgraph-checkpoint-postgres==3.1.2` 已由 W0 钉死。


---

## 7. 给下一个窗口的交接话术

### 7.1 若下一个窗口是 **W1B（数据层 / alembic 迁移）**

> ⚠️ **前提（2026-09-16 用户确认）**：**W1B 与 W1A 是同期并行的**（`08 §2` 阶段 1 下两个工作包），不是"W1A 完了才轮到 W1B"。下面不是"交接话术"，而是**两个平行窗口之间的接口对齐**——**文件归属边界照旧，不得互相落笔**。

> 你是本项目「阶段 1B · 数据层」窗口（W1B）的负责人。W1A 已交付，你可以直接依赖：
> - `data/schema.sql` —— **只是契约声明件**，列名已与 `semantic/bundle_2026.09.14.1.yaml` 逐列对齐并被 `selfcheck.py` 断言。**不要把它当生产 DDL 的真相来源，也不要往里加 RLS/GRANT/触发器**：按 `docs/08 §4.3`，这些只由你的 alembic 产出。
> - 沙箱库 `data/ecom_sandbox.db`（420.3 MB，未入库）+ `eval/MANIFEST_v1.json`（含**名义参数**、**实测行数**、生成器与库的 sha256）。
>
> **需要你注意的**：
> ① 语义包的租户隔离由 `app/auth/context.py` + `SET app.tenant_id` 落地；沙箱里**没有 RLS**，评测靠执行层注入 —— **W6 与你的实现必须一致**（U-33 已裁定）。
> ② 角色名已统一为 `app_ro` / `app_rw`（早期版本写 `app_readonly`，勿再沿用）。
> ③ **U-28 已裁定**：区间关联**不新增 join 类型**，只能经 `v_dim_date` 两跳，且语义包**必须显式登记**（我已登记 3 条边）。⚠️ 但实测两个陷阱：`pay_time`(timestamptz) → `date_key`(date) **不是裸等值**；`dim_date`（公共）→ `campaign`（租户）是**跨租户边界的边**，不写租户谓词会 **3 倍扇出**。若你的迁移里要给这条路径加约束/索引，**先读 `SCHEMA_v1.md §6.2`**。

### 7.2 若下一个窗口是 **W2A / W2B（语义层 / 检索）**

> 你是本项目「阶段 2 · 语义层与检索」窗口（W2A/W2B）的负责人。W1A 已交付语义包 v1，可直接依赖：
> - `semantic/bundle_2026.09.14.1.yaml`（3 域 / 8 资产 / 9 指标 / 6 维度 / 105 别名 / 15 黑话 / **10 条 join**）
> - **`semantic/SCHEMA_v1.md` v1.1 —— 字段契约，动手前必读**
> - 校验器 `semantic/validate_bundle.py`（**34 项**）
>
> **🔴 先说清最重要的一条**：`SCHEMA_v1.md` v1 曾是 candidate，`07 §4.7` 明确要求"**裁定前 W2A 不得按它动手**"。**现在裁定已下、v1.1 已同步**，你可以动手了。相对 v1，**字段契约有三处变化**：
> - ❌ `assets[].grain_level` **删除**（无消费者 + 与 `dimensions[].grain_level` 同名不同义）
> - ❌ `field_bindings[].default_binding` **删除** → 改读 **`canonical_asset`**（字段层依据）+ **`default_reason`**（披露文案）
> - ⚠️ `metrics[].default_binding` **收窄为 `{asset, reason}`**，**时间基准读 `time_basis`**（`time_field` 已删）
>
> **三个硬约束（写错任何一条都会静默出错）**：
> ① **L2 判"是否同粒度"必须用 `grain_level` 数值相等，不能用 `hierarchy` 数组下标。** 地理族刻度是 `country=1/region=2/province=3/city=4`，而 `dimensions.city` 故意从 2 起（不是笔误）——用下标会把 `city`(4) 与 `shop`(1) 误判成不同粒度，真歧义被漏判。
> ② **`metrics[].default_binding` 的形状必须恰好是 `{asset, reason}`**；时间基准一律读 `time_basis`。校验器**不只查少了什么，也查多了什么**（被删字段最可能的回归形态是"顺手又加回来"）。
> ③ **`ambiguous` ⇔ 无 `canonical_asset` / 无 `default_reason`（双向）**：`城市` 概念刻意留歧义（`order_paid.receiver_city` vs `shop.city`，同 `grain_level=4`）→ L3 **不得**抢在澄清前把它"解决"掉；反过来，**非** ambiguous 概念缺 `default_reason` 会让 L3 退回澄清 → 澄清率虚高。
>
> **披露（U-26 改判）**：`resolved_default` 的文案来源 = **指标层 `default_binding.reason` / 概念层 `default_reason`**，最终载体 = **`insight.caveats[]`**（附录 A §A.1.2 第 8 条）。渲染规则：去重 → 按 `display_name`/`concept` **字典序** → 每条 **≤ 40 字**。**禁止塞 `scope.notice`**（那是权限范围披露的专用字段）。`meta.disclosure_text` 已被裁定**不采纳**（校验器有负向断言）。
>
> **~~阻塞项~~ → ✅ 已解除（W0 @ aef8750）**：PyYAML 已转正为显式依赖。
> **⚠️ 但 W0 同批新增了一条会红你代码的护栏**：`test_no_undeclared_third_party_imports` 会 AST 扫描 `backend/app`、`backend/tests`、`backend/scripts`、`semantic`、`data`、`eval` —— **任何直接 import（含函数内延迟 import）都必须已在 `pyproject.toml` 声明**。需要新包时走 `docs/08 §4.3` 提给 W0，**不得靠传递依赖**。
>
> **归你自证、我不冒充的**：07 §6.1⑤ 的「jieba 词典可加载 / 分词函数可用」（`retrieval/tokenizer.py` 是唯一入口）。W1A 校验器里那一项**是 SKIP，不是通过**。
>
> **一个待确认项（不阻塞你动手）**：`dimensions[].grain_level` 的"默认层级"读法 —— 我按 `hierarchy` 末项实现（6/6 一致），若架构窗口明确定义为"`binding` 的粒度"，则 `region`(4→3) 与 `category`(3→1) 会改。**你若发现 L2 需要"binding 的粒度"这个量，请立刻反馈** —— 那说明契约缺一个字段。

### 7.3 若下一个窗口是 **W2C（闸门）/ W2D（执行与脱敏）/ W4 / W6**

> **先纠正我上一轮的两个窗口名错误**（已改）：
> - `app/guard/**`（含 `rules.py` 唯一入口）**是 W2C**，我上一轮误写成 W4。**W4 = 阶段 4 编排收口**（`app/graph/**` + `api/routers/**` + `errors.py` + `sse.py`）。
> - `app/exec/**` + `app/mask/**` **是 W2D**，我上一轮**整包漏发**。

> **W2C（闸门）**：红队集 66 条已就位 —— `rule_id` 直接取自 `enums.AstRule`、严重度取自 `enums.AST_RULE_SEVERITY`（**都不另立编号/映射**）。**最易踩的一条：`rewrite` / `warn` 级绝不能被实现成"拒绝"**（U-16）。每条都带 `not_blocked` + `rewritten` / `warning_emitted` 断言，构建器缺断言会**直接 FAIL** —— 这是防复发的机制，别绕过。`block` 级必须断言错误文案**不回显表名/列名**。已知边界：**红队只覆盖 SQL 层**，LLM 提示层注入集不在 W1A 范围。
>
> **W2D（执行 / 脱敏）**：与你的 DoD 强相关的我的产物 —— ① **`truncated` 只由 LIMIT 触发**：`eval/red_team_cases_v1.json` 的 `RT-LIM-001~004`（含 1 条**反向断言**：聚合结果不可能被截断 → 不得置 `truncated`）；② **类型归一化**：沙箱 8 张表的列类型见 `data/schema.sql`，与语义包 `assets[].columns` **逐列一致**（有断言）；③ **`app_ro` 写操作必须失败** —— 沙箱**无 RLS / 无角色**（`SCHEMA_v1.md` 的 D-4），**这条只能在 PG 侧验**；④ 沙箱是 SQLite，**不覆盖 pgvector / EXPLAIN JSON** → `RT-COST-003` 的期望是**报"未评估"而不是报"通过"**。
>
> **W4（编排收口）**：`eval/red_team_cases_v1.json`（66 条）+ `eval/dataset_v1_frozen.json` 的消费方；`gold_sql` **不含 tenant**（U-33）。
>
> **W6（评测执行）**：可直接依赖 `eval/dataset_v1_frozen.json`（`content_hash = sha256:43e153de…`）、`eval/MANIFEST_v1.json`（**含 `measured` 段**）、`eval/gold_query_seed_v1.json`（**派生视图，别手改**）。**四条最容易踩的**：
> ① **`gold_sql` 不含 `tenant_id`**（U-33）：执行器要按 `eval_tenant` 在**资产边界**注入。`eval/build_frozen_set.py` 里有可复用的 `tenant_wrap()` 参考实现。
> ② **`gold_result_hash` 由真实执行产生，禁止手填**；且**行序不参与 hash**（无 ORDER BY 的 SQL 不保证顺序，把顺序算进去会造成假失败）。
> ③ **4×3 网格有 6 个格子刚好 8 条（贴线）**：任何一条被判 invalid 就立即破格 → 冻结后请勿再动用例库。
> ④ **沙箱是 SQLite**，不覆盖 RLS / CLS / pgvector / EXPLAIN JSON → **"评测全绿"≠"生产全绿"**，这条必须写进评测报告（§17.6 不变量 I-6）。
>
> **且你要接手的四项未完成（我如实留给你）**：
> - **U-28 的两跳路径只覆盖大促 + 有 3 倍扇出风险**：`v_dim_date.campaign_id` 只有 4 个 PROM 值、102/730 天有值，日常促销**无映射** → "活动订单"口径不完整，**必须进报告"已知限制"**；且 `dim_date` 是公共表，跨租户跳转必须带租户谓词（见 `MANIFEST.measured.findings` M-1/M-2/M-3）。
> - **DoD④ 的 RLS 层断言**（语义层部分已做，执行层归你；架构窗口正在拆 DoD④）。
> - **V1–V7 数据变体的 patch 脚本未实现**（`data/schema.sql` 末尾写了做法）→ 附录 C §C.5.3 的"每条用例跑 V0 + 1 变体"**当前跑不了**。
> - **"零分母 SKU" 清单未导出**（生成器内部有 40 个确定性 SKU，MANIFEST 只记了数量）→ 做 V6 前需先暴露。
