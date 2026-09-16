# W1A（阶段 1A · 地基）交付与交接

> **作者窗口**：W1A　**日期**：2026-09-16
> **任务书**：`docs/08 §3.2`
> **自检入口**：`./.venv/Scripts/python.exe data/generator/selfcheck.py`　→ 结果 **24 项：PASS=23 / FAIL=0 / SKIP=1**
> **纪律**：本文只记录「已实测」「已自证」「未决」三类，**不含推测**。凡未跑过的都标 UNVERIFIED。
>
> **修订记录**
> - `2026-09-16` 初版交付（DoD 六条自证通过）。
> - `2026-09-16` W0 回执落地（`main @ aef8750`，CI success）：转达项 ①② **均已关闭**；新增护栏 `test_no_undeclared_third_party_imports`，W1A 三目录已实测通过 → 新增 **§2.3**；L8 状态由"已知限制"改为"已消解"；§7.1 前提修正（**W1B 与 W1A 同期并行**，非先后交接）。


---

## 1. 交付物清单（全部在本仓库内，可直接 review）

| 路径 | 内容 | DoD |
|---|---|---|
| `semantic/bundle_2026.09.14.1.yaml` | 3 域语义包（orders/products/traffic），8 资产 / 9 指标 / 6 维度 / 105 别名 / 15 黑话 | ①⑤⑥ |
| `semantic/SCHEMA_v1.md` | 语义包字段契约（含 ★ 扩展字段形状 + 三套 grain 刻度说明） | ①⑤⑥ |
| `semantic/validate_bundle.py` | 07 §6.1 五步校验器，**27 项断言**（含本节新增的双向谓词断言） | ① |
| `semantic/metric_dictionary.md` | 指标口径字典 —— **由 YAML 渲染**（`render_metric_dictionary.py`），杜绝两份真相 | — |
| `data/schema.sql` | SQLite 沙箱 DDL（**契约声明件**，非生产 DDL 真相）+ V0–V7 变体落地方式说明 | ② |
| `data/generator/seed_generator.py` | 确定性生成器（纯标准库，命名子种子，14 类脏度全注入） | ② |
| `data/generator/layering.py` | 4×3 分层判定器（**按上游 evaluation.py 原样实现**） | ③ |
| `data/generator/selfcheck.py` | DoD 逐条自证脚本 | 全部 |
| `data/ecom_sandbox.db` | 沙箱数据物 **420.3 MB**（**未入库**，见 §4-R1） | ② |
| `eval/case_library.py` | 用例库（声明式，166 条） | ②③ |
| `eval/build_frozen_set.py` | 冻结集构建器（真实执行 → hash → 机器分层 → 网格断言） | ②③ |
| `eval/dataset_v1_frozen.json` | 冻结集 v1，124 execute + 18 clarify + 24 refuse | ②③ |
| `eval/build_red_team.py` / `eval/red_team_cases_v1.json` | 红队集 v1，66 条，**20/20 AST 规则全覆盖** | ④ |
| `eval/build_gold_seed.py` / `eval/gold_query_seed_v1.json` | few-shot Gold Query 种子 119 条（**由冻结集派生**） | — |
| `eval/MANIFEST_v1.json` | 可复现证据链（种子 / 参数 / 生成器 sha256 / 库 sha256 / 网格计数） | ② |

---

## 2. DoD 六条自证（逐条给证据，不是声称）

| DoD | 结果 | 证据 |
|---|---|---|
| ① 3 域语义包通过 §6.1 五步校验 | **PASS** | `validate_bundle.py`：27 项断言，**PASS=25 / FAIL=0 / SKIP=1 / WARN=1** |
| ② 冻结集含 `content_hash`（N-13） | **PASS** | `sha256:43e153de…`；且 `--check` 重算一致（未漂移） |
| ③ 4×3 网格每格 ≥ 8 | **PASS** | 12 格最小值 **8**，合计 **124** 条 |
| ④ 红队覆盖 20 条 AST 规则 + 跨租户 + RLS/truncated | **PASS** | `20/20` 规则；`RT-XT-*` 3 条；`RT-LIM-*` 4 条 |
| ⑤ `default_binding` 与别名表就位 | **PASS** | 6/7 概念有默认口径（1 条刻意 ambiguous）；8/8 活跃指标有默认绑定；105 个 term 一对一 |
| ⑥ 维度含 `grain_level` | **PASS** | 6 个维度全部有 `grain_level` 与 `grain_levels` |

### 2.1 我额外加的三条"防两份真相"断言（不在 DoD 里，但必须做）

| 断言 | 结果 | 为什么 |
|---|---|---|
| DDL 列名 ↔ 语义包 `assets[].columns` 逐列一致 | PASS（8 张表全一致） | 否则 DDL 与语义包会各说各话 |
| 沙箱库 sha256 ↔ MANIFEST 一致 | PASS（`eb35a97f…`） | "数字类结论可复现"的物证 |
| `metric_dictionary.md` / `gold_query_seed_v1.json` ↔ 上游源一致 | PASS | 两者都是**派生视图**，不许手改 |

### 2.2 明确 **不归 W1A 自证** 的项（标 SKIP，不冒充通过）

- **07 §6.1 步骤⑤ 的「jieba 词典可加载 / 分词函数可用」** → 归 **W2B**
  （`retrieval/tokenizer.py` 是唯一入口，N-24）。W1A 的校验脚本**刻意不 import `app.*`**，
  以保证它能独立运行、不受包路径影响。

### 2.3 W0 新增护栏的通过证据（`test_no_undeclared_third_party_imports`）

W0 于 2026-09-16（`main @ aef8750`）在 `tests/contract/test_dependency_whitelist.py` 新增 AST 扫描护栏，**扫描范围含 `semantic` / `data` / `eval`（即 W1A 的三个目录）**。这直接影响 W1A 的交付物，故已实测复核。

| 检查 | 结果 | 证据 |
|---|---|---|
| `pytest tests/contract/test_dependency_whitelist.py` | **14 passed in 1.21s** | 含新增的幽灵依赖检测 |
| W1A 目录被真实纳入扫描 | ✅ | 扫描 88 个 `.py`，其中 `semantic/` 2 + `data/` 3 + `eval/` 4 = **9 个** |
| W1A 文件的第三方 import 全已声明 | ✅ | 仅 2 个：`sqlglot`（`data/generator/layering.py`）与 `yaml`（`semantic/validate_bundle.py`、`semantic/render_metric_dictionary.py`、`data/generator/selfcheck.py`）→ 均已声明 |
| `eval/*.py`（4 个） | ✅ 零第三方 import | 只 import 一方模块（`app.*` / `case_library` / `layering`） |
| `data/generator/seed_generator.py` | ✅ 零第三方 import | 印证"纯标准库、无新依赖"的交付声明 |
| **违规项** | **无** | 独立探针（自写 AST 扫描）与护栏结论一致，非空跑 |

> **纪律（W0 明确要求，W1A 照办）**：`semantic/` 与 `data/` 若还需要别的包，**不得靠传递依赖**，须走 `docs/08 §4.3` 提给 W0。

---

## 3. 关键设计决定（附理由与代价）

| # | 决定 | 理由 | 代价 |
|---|---|---|---|
| D1 | **`gold_sql` 不含 `tenant_id`**，租户由评测器在**资产边界**注入（`tenant_wrap`） | ① 语义包明写该列「不暴露给模型生成」；② 实测：`tenant_id` 会额外算 **1 个 WHERE 条件单元** → `others +1` → 把整批用例顶出 `easy`，使 **`easy × 高` 这一格不可达**（而 DoD③ 要求 12 格全达标） | W6 执行器必须真正做租户注入；gold_sql 需用**表名限定**而非短别名（本库已遵守）。登记 **U-33** |
| D2 | `assets[].grain_level` 用**独立的"资产细度档"刻度**（1–6），与 `dimensions[].grain_level` 的**族内刻度**严格分开 | 两套刻度的**比较范围不同**：L2 只在同维度候选间比；资产档要比不同资产。混用会让 `shop(3)` 与 `city(4)` 产生虚假粒度关系 | 上游 07 §12.2 列了该字段却**从未定义语义、全文无消费者**（实测）。本刻度为 W1A 提议 → 登记 **U-23** |
| D3 | 冻结集的 `difficulty_struct` 由 `layering.py` **机器判定**，声明式用例库**只写 tags** | 防"看起来对"：人写级别必然向期望靠拢 | 用例作者必须先算清 `c1/o/c2` 才能命中目标格（本库每块注释都标了它靠什么落格） |
| D4 | 数据物 **420 MB 不入 Git**，改为"脚本 + 固定种子 + sha256" | 已裁定：>50 MB 只入库脚本与 hash | clone 后需跑一次生成器（实测 **4 分 12 秒**，单核纯 Python）。登记 **U-31** 相关 |
| D5 | `metric_dictionary.md` 与 `gold_query_seed_v1.json` 均为**派生视图** | 同一事实只写一遍（U-18 教训） | 需在 CI 里跑两个 `--check` |
| D6 | 红队集的 `rewrite`/`warn` 级**一律带 `not_blocked` 断言** | U-16：把这级写成"拒绝"就是实现缺陷 | 构建器会在缺断言时**直接 FAIL**，防止悄悄退化 |

---

## 4. 未决项登记（已完成 / 阻塞 / 假设）

> 说明：**没有任何一项阻塞了 W1A 的交付**。全部按"假设 + 默认方案"落地，等待裁定后改一行即可。
> 若裁定与本文不同，**改 YAML 是 W1A 的事，改代码不是**。

### 4.1 U-23 … U-33（交**架构窗口**裁定）

| 编号 | 内容 | 我的默认方案（已落地） | 若裁定不同，改动成本 |
|---|---|---|---|
| **U-23** | `grain_level` / `grain_levels` / `default_binding` / `tenant_scoped` / `quality_score` 在 YAML 里的**位置与形状** —— 07 §12.2 的物化表与 §6.8.1/§7.4 都依赖，**附录 B v1.1 结构示例里没有这 4 个字段的任何定义** | 见 `SCHEMA_v1.md` §3.3/§3.4；其中 `assets[].grain_level` 用 1–6 资产细度档 | 低（YAML 改字段 + 校验器 5 行） |
| **U-24** | `semantic/` 与 `data/` 的**目录归属** —— `08 §4.1` 只写 `semantic/**`，`07 §3.2` 的目录树里**两个目录都不存在** | 落 `CommerceQL/semantic/` + `CommerceQL/data/` | 低（整目录移动） |
| **U-25** | `EMBEDDING_DIM` 一致性（§6.1⑤）需要"YAML 里声明维度"，附录 B **无承载位** | 放 `meta.embedding.{model,dim}` | 低 |
| **U-26** | 07 §6.8 要求 `resolved_default` 态**强制披露**，但**文案的唯一来源未指定** | 放 `meta.disclosure_text` | 低 |
| **U-27** | `dimensions.city.binding` 需要城市列，但**附录 C §C.11.2 的 `v_order_paid` 字段表只列了 `region_code`**（省），`receiver_address` 是敏感列不可用 | 在 `v_order_paid` 补 `receiver_city`（非敏感），列进 DDL，selfcheck 断言两处一致 | 低 |
| **U-28** | **区间关联无法用 `joins[].on_columns` 表达** —— `v_campaign` 靠 `start_date/end_date` 与订单时间关联（附录 C §C.11.3 的 ER 图也画了这条），但 `on_columns` 只能是等值列对 | W1A **不发明 join type**；`v_campaign` 暂只能按 `campaign_id` 等值可达；`v_dim_date.campaign_id` 已写入大促标签 | 中（要新增 join 类型或改用 between 谓词） |
| **U-29** | **附录 C §C.3.1 的 Component2 定义抄了一个死常量**。附录 C 写「Component2：EXCEPT、UNION、INTERSECT」（来源标注"行号 53-56"）。实测 `evaluation.py` 第 53-56 行是 `HARDNESS = {...}`，而 **`HARDNESS` 在全文件只出现这一次 —— 定义后从未被使用**；真正生效的第 324 行 `count_component2` = `len(get_nestedSQL(sql))`，**子查询同样计入** | `layering.py` **以上游生效代码为准**（子查询计入）；输出另留 `comp2_setops` 供核对 | 低 |
| **U-30** | **按上游代码实算，官方站点标注的 "Hard" 示例会得到 "extra"**。官方示例是 3 表 JOIN + WHERE + GROUP BY + HAVING → 按 `count += len(table_units) - 1` 得 `c1=4` → 落入 `else: return "extra"`。若 JOIN 只记 1 个组件，则四个官方示例**全部吻合** | 两套都实现：`difficulty_struct`＝上游代码口径（默认）、`difficulty_struct_sitelabel`＝站点标签口径。**不擅自选一个当"官方真相"** | 低（一行切换） |
| **U-31** | **"订单总数 50 万行"与"某月某租户无订单"不可同时严格成立**。实测：注入空区间后订单总数为 **494,249**（差 5,751 = T_C 2025-02 应占的量） | 保空区间（它是 V1 变体的前提），总数记为 494,249 并如实写进 MANIFEST | 低（若要严格 50 万，把差额摊回其他月） |
| **U-32** | **`v_region.region_name` 让大区映射在 schema 内可直接使用** —— 与"大区归属是业务约定，必须走 `value_map`"存在张力 | 保留 `region_name`（语义包自身也声明了该列，注释为"由 value_map 派生"）；冻结集里需要大区集合的用例标 `value_map:region` | 低 |
| **U-33** | **`gold_sql` 是否应含 `tenant_id`**（即租户过滤是"模型职责"还是"执行层职责"） | 采纳"执行层职责"：gold_sql 不含，评测时在资产边界注入（见 D1） | 中（影响 W6 执行器契约） |

### 4.2 要**转达**给其它窗口的（W1A 不动别人的文件）

| 转达对象 | 内容 | 性质 |
|---|---|---|
| **W0**（`pyproject.toml` / `.importlinter` / `.gitignore` 归属） | ① **PyYAML 不在 ADR-20 白名单**，但 W2A 按 §6.1① 必须读 YAML。**实测证据（2026-09-16 复核）**：`backend/pyproject.toml` 的 `dependencies` 段与 `docs/07` 全文**均无 PyYAML**；它只以**传递依赖**身份存在于 `CommerceQL/.venv`（版本 6.0.3）。用**不含传递依赖的解释器**裸跑 `semantic/validate_bundle.py` → **直接 `FATAL: PyYAML 不可用`**（非警告，是硬失败）。→ 请走 `docs/08 §4.3` 四步正式加入白名单；② `.gitignore` 里有一条显式的 **`!ecom_sandbox.db`（反向放行）**，与"420 MB 数据物不入库"的决定**直接冲突** → 请改为默认忽略 | **✅ 已于 2026-09-16 由 W0 关闭**（`main @ aef8750`，CI success）：① PyYAML 转正，另**同类补登 4 个**（`psycopg-pool` / `cryptography` / `starlette` / `python-dotenv`），共 5 个，文档侧走 **U-37**；② `!ecom_sandbox.db` 已撤除（现命中 `*.db`），并补 `*.db-wal/-shm/-journal`。**详见 §2.3** |
| **W1B**（alembic 迁移 / 数据层） | `data/schema.sql` 是**契约声明件**，**不是生产 DDL 的真相来源**。`RLS`/`GRANT`/`REVOKE`/触发器**一律不进该文件**，只由 W1B 的 alembic 产出 |
| **W2A**（语义层 / 检索） | 加载器字段契约见 `semantic/SCHEMA_v1.md`；★ 扩展字段见 **U-23**；**L2 判"同粒度"务必用 `grain_level` 数值相等，不要用 `hierarchy` 下标**（否则 `city`(4) 与 `shop`(1) 会被误判为不同粒度） |
| **W2B**（检索 / 分词） | 07 §6.1⑤ 的「jieba 词典可加载 / 分词函数可用」由你自证；W1A 的校验器刻意不 import `app.*` |
| **W4**（守卫） | 红队集 66 条已就位，`rule_id` 直接取自 `enums.AstRule`（未另立编号）。**`rewrite`/`warn` 级一律带 `not_blocked` 断言 —— 把它们实现成"拒绝"即为缺陷（U-16）** |
| **W6**（评测执行） | 冻结集 / MANIFEST / 红队集 / Gold 种子的消费方；`gold_sql` **不含 tenant**（U-33），需按 `eval_tenant` 注入；V1–V7 变体的 **patch 脚本尚未实现**（见 §5） |
| **上游文档窗口**（`docs/01–06`） | ① 附录 C §C.3.1 的 Component2 定义引用了未使用的 `HARDNESS` 常量（**U-29**）；② 附录 C §C.11.2 缺 `receiver_city` 列（**U-27**）；③ 附录 C §C.11.3 的区间关联在 `joins` 契约里无法表达（**U-28**）；④ `08 §4.1` 未登记 `data/**`（**U-24**） |

---

## 5. ⚠️ 交付里**未完成 / 有已知限制**的部分（不隐瞒）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| L1 | **V1–V7 数据变体的 patch 脚本** | **未实现** | `data/schema.sql` 末尾已写明做法（V0 全量 + 确定性 patch），但 `variants.py` 尚未写。附录 C §C.5.3 的"每条用例至少跑 V0 + 1 个随机变体"因此**当前跑不了** |
| L2 | **红队集只覆盖 SQL 层攻击面** | 已知限制 | `RT-INJ-003`（提示词套取）等 4 条只是"期望行为"声明；**LLM 提示层的注入测试集不在 W1A 范围**（属 W4/W6） |
| L3 | **4×3 网格贴线** | 已知限制 | 6 个格子刚好 **8 条**（DoD 下限）。任何一条用例被判 invalid 都会立即破格 → 建议 W6 冻结前不要再动用例库 |
| L4 | **沙箱库未入库** | 已知限制 | 420 MB；clone 后必须跑一次生成器（4 分 12 秒）。`MANIFEST_v1.json` 里有 sha256 可校验 |
| L5 | **"零分母 SKU"的指定集未导出** | 小缺口 | 生成器内部有 `zero_skus`（40 个，确定性），但**没写进 MANIFEST**。要做 V6 变体需先把它暴露出来 |
| L6 | **`assets[].grain_level` 无上游消费者** | 已知（U-23） | 实测 07/附录 B 只在 §12.2 表结构清单出现该字段名，**无任何地方使用**。W1A 给了提议刻度，但这字段**可能本就不该存在** |
| L7 | `dimensions.time` 的 `binding` 键名 | 待 W2A 反馈 | 时间维度用 `bindings: {粒度: 列}` 多绑定形态（其他维度是单 `binding`）。附录 B 只给了单绑定示例 → 若 W2A 的 loader 不认，须登记 |
| L8 | **W1A 工具链需用 `CommerceQL/.venv`**（~~强绑定~~ → 根因已关闭） | **已消解**（2026-09-16） | 现象：裸 `python` 跑 `semantic/validate_bundle.py` → `FATAL: PyYAML 不可用`；跑 `eval/build_frozen_set.py` → `ModuleNotFoundError: sqlglot`。**根因 = PyYAML 只以传递依赖存在**，已由 W0 于 `aef8750` 转正（+5 个同类，U-37）→ 干净环境 `pip install -e backend` 后不再断。**仍保留的纪律**：复现一律用 `./.venv/Scripts/python.exe`（裸解释器什么都没装，与白名单无关）。**未做完的**：W1A 的 5 个 `--check`（frozen / red_team / metric_dict / gold_seed）**尚未挂进 CI** → 目前"未漂移"只能靠人手动复核，归 **W0 或 W6** 决定是否接线 |

---

## 6. 复现步骤（任何人可独立重跑）

```bash
cd CommerceQL

# ⚠️ 必须用本仓库的 venv 解释器，**不要用裸 `python`**
#    裸 python（未装依赖的解释器）会在第 2 步直接 FATAL（见 L8）
PY=./.venv/Scripts/python.exe        # Windows
# PY=./.venv/bin/python              # Linux/macOS

# 1) 生成沙箱数据（4 分 12 秒，纯标准库）
$PY data/generator/seed_generator.py --out data/ecom_sandbox.db

# 2) 校验语义包（27 项）
$PY semantic/validate_bundle.py

# 3) 重算冻结集并校验未漂移
$PY eval/build_frozen_set.py --check

# 4) 红队集覆盖度自证
$PY eval/build_red_team.py --check

# 5) 派生视图同步性
$PY semantic/render_metric_dictionary.py --check
$PY eval/build_gold_seed.py --check

# 6) 上限锚点复现（U-30 的暴露点）
$PY data/generator/layering.py --anchors

# 7) 一键全跑
$PY data/generator/selfcheck.py
```

### 6.1 2026-09-16 复核记录（全部用 venv 解释器重跑）

| 脚本 | 结果 |
|---|---|
| `validate_bundle.py` | 27 项：**PASS=25 / FAIL=0 / SKIP=1 / WARN=1** |
| `build_frozen_set.py --check` | 12 格全 ≥ 8（最小值 8，合计 124）｜`content_hash = sha256:43e153de…`｜**未漂移** |
| `build_red_team.py --check` | 66 条｜20/20 规则｜`sha256:886cb570…`｜**未漂移** |
| `render_metric_dictionary.py --check` | OK，与语义包同步 |
| `build_gold_seed.py --check` | 119 条种子 / 124 条冻结集｜**已同步** |

venv 实测版本：`PyYAML 6.0.3`（**2026-09-16 起为显式依赖**，此前是传递依赖）、`sqlglot 30.18.0`（白名单内，pyproject line 42）、`jieba 0.42.1`、`pydantic 2.13.5`。`langgraph==1.2.11` / `langgraph-checkpoint-postgres==3.1.2` 已由 W0 钉死。


---

## 7. 给下一个窗口的交接话术

### 7.1 若下一个窗口是 **W1B（数据层 / alembic 迁移）**

> ⚠️ **前提修正（2026-09-16 用户确认）**：**W1B 与 W1A 是同期并行的**（`08 §2` 阶段 1 下两个工作包），不是"W1A 完了才轮到 W1B"。因此下面这段不是"交接话术"，而是**两个平行窗口之间的接口对齐**——**文件归属边界照旧，不得互相落笔**。§7.1 保留是因为它写清了 W1A 交给 W1B 的**接口契约**（`schema.sql` 的性质、U-28 的等待项）。

> 你是本项目「阶段 1B · 数据层」窗口（W1B）的负责人。W1A 已交付，你可以直接依赖：
> - `data/schema.sql` —— **只是契约声明件**，列名已与 `semantic/bundle_2026.09.14.1.yaml` 逐列对齐并被 `data/generator/selfcheck.py` 断言。**不要把它当生产 DDL 的真相来源，也不要往里加 RLS/GRANT/触发器**：按 `docs/08 §4.3`，这些只由你的 alembic 产出。
> - 沙箱库 `data/ecom_sandbox.db`（420 MB，未入库）+ `eval/MANIFEST_v1.json`（含种子、参数、生成器与库的 sha256）。
>
> **需要你注意的**：
> ① 语义包的租户隔离由 `app/auth/context.py` + `SET app.tenant_id` 落地（附录 C §C.13 的 `tenant_role_isolation` 策略）；沙箱里**没有 RLS**，评测靠执行层注入——**W6 与你的实现必须一致**（U-33）。
> ② 附录 C §C.13 的角色名已统一为 `app_ro` / `app_rw`（早期版本写 `app_readonly`，勿再沿用）。
> ③ 我登记了 **U-28**：`v_campaign` 与订单是**区间关联**（`start_date/end_date`），`joins[].on_columns` 表达不了。若你的迁移里要给这条路径加约束/索引，请先等架构窗口对 U-28 的裁定。

### 7.2 若下一个窗口是 **W2A / W2B（语义层 / 检索）**

> 你是本项目「阶段 2 · 语义层与检索」窗口（W2A/W2B）的负责人。W1A 已交付语义包 v1，可直接依赖：
> - `semantic/bundle_2026.09.14.1.yaml`（3 域 / 8 资产 / 9 指标 / 6 维度 / 105 别名 / 15 黑话）+ `semantic/SCHEMA_v1.md`（**字段契约，动手前必读**）
> - 校验器 `semantic/validate_bundle.py`（27 项）
>
> **三个硬约束（写错任何一条都会静默出错）**：
> ① **L2 判"是否同粒度"必须用 `grain_level` 数值相等，不能用 `hierarchy` 数组下标。** 地理族刻度是 `country=1/region=2/province=3/city=4`，而 `dimensions.city` 故意从 2 起（不是笔误）——用下标会把 `city`(4) 与 `shop`(1) 误判成不同粒度，真歧义被漏判。
> ② **`assets[].grain_level` 与 `dimensions[].grain_level` 是两套刻度，永不互相比较**（见 `SCHEMA_v1.md` §3.4）。
> ③ **`field_bindings[].default_binding` 与 `ambiguous: true` 互斥**：`城市` 概念刻意留歧义（`order_paid.receiver_city` vs `shop.city`，同 `grain_level=4`）→ L3 **不得**抢在澄清前把它"解决"掉。
>
> **~~阻塞项（要你或 W0 处理）~~ → ✅ 已解除（2026-09-16，W0 @ aef8750）**：PyYAML 已转正为显式依赖（同批补登 `psycopg-pool` / `cryptography` / `starlette` / `python-dotenv`，共 5 个，文档侧 U-37），**你现在读 YAML 是合法的**。
>
> **⚠️ 但 W0 同批新增了一条会红你代码的护栏**：`tests/contract/test_dependency_whitelist.py::test_no_undeclared_third_party_imports` 会 AST 扫描 `backend/app`、`backend/tests`、`backend/scripts`、`semantic`、`data`、`eval` —— **任何直接 import（含函数内延迟 import）都必须已在 `pyproject.toml` 声明**。需要新包时走 `docs/08 §4.3` 提给 W0，**不得靠传递依赖**。（W1A 的三个目录已实测 14 passed / 0 违规，见 §2.3。）
>
> **归你自证、我不冒充的**：07 §6.1⑤ 的「jieba 词典可加载 / 分词函数可用」（`retrieval/tokenizer.py` 是唯一入口）。
>
> **待架构窗口裁定**：U-23（★ 扩展字段形状）、U-25、U-26。

### 7.3 若下一个窗口是 **W4（守卫）/ W6（评测执行）**

> W1A 已交付红队集与冻结集，可直接依赖：
> - `eval/red_team_cases_v1.json` —— 66 条，**20/20 AST 规则全覆盖**，`rule_id` 直接取自 `enums.AstRule`（未另立编号），严重度取自 `enums.AST_RULE_SEVERITY`（不另立映射）
> - `eval/dataset_v1_frozen.json` —— 124 execute + 18 clarify + 24 refuse，`content_hash = sha256:43e153de…`
> - `eval/MANIFEST_v1.json`、`eval/gold_query_seed_v1.json`
>
> **四条最容易踩的**：
> ① **`rewrite` / `warn` 级绝不能被实现成"拒绝"**。红队集每条都带 `not_blocked` + `rewritten`/`warning_emitted` 断言，构建器会在缺断言时直接 FAIL —— 这是防 U-16 复发的机制，别绕过它。
> ② **`block` 级必须断言错误文案不回显表名/列名**（基础断言里已含）。
> ③ **`gold_sql` 不含 `tenant_id`**（U-33）：执行器要按 `eval_tenant` 在**资产边界**注入租户过滤。冻结集构建器里有可复用的 `tenant_wrap()` 参考实现。
> ④ **`gold_result_hash` 由真实执行产生，禁止手填**；hash 计算时**行序不参与**（无 ORDER BY 的 SQL 不保证顺序，把顺序算进去会造成假失败）。
>
> **你要接手的未完成项（我如实留给你）**：
> - **V1–V7 数据变体的 patch 脚本未实现**（`data/schema.sql` 末尾写了做法）。附录 C §C.5.3 的"每条用例至少跑 V0 + 1 个随机变体；安全类必跑 V7"因此**当前跑不了**。
> - **"零分母 SKU"指定集未导出**（生成器内部有 40 个确定性 SKU，未写进 MANIFEST）→ 做 V6 前需要我或你把它暴露。
> - **4×3 网格有 6 个格子刚好 8 条（贴线）**：任何一条被判 invalid 就会破格 → 冻结后请勿再动用例库。
> - **红队集只覆盖 SQL 层**；LLM 提示层的注入测试集不在 W1A 范围。
