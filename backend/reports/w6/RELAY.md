# W6 → 其他窗口的转述单（RELAY）

窗口：W6 · 日期：2026-09-18
"要谁改哪一行"尽量写到**具体函数 + 具体证据文件**，不接受"评测没跑通"这种无法执行的描述。
标 ★ = **没有它对应门禁就永远拿不到可信读数**。

编号纪律：本窗口**不自开 U-xx**（U-88~U-103 已被 W4 用尽）。新问题一律写"待架构窗口分配编号"。
归属纪律：`eval/*.json`、`case_library.py`、`build_*.py` 是 W1A 的；`app/**` 各段分别归 W0–W4/W7；
本窗口**只取证、不改他人文件**。所以本单里凡"请改 X"的，都是本窗口无权落笔的东西。

---

## 一、给架构窗口：需要裁决（不是 bug，是"两份规格互相矛盾"）

| # | 上呈 | 本窗口的判定与证据 |
|---|---|---|
| A1 ★ | **冻结集 gold 与语义包默认口径不一致，G-7 因此永久 FAIL** | §C.4.3 核心指标一致率 **1/13 = 7.7%**（门槛 95%），12 条差异**全部**可归因到 `default_predicates` 的三个谓词（`is_test_order = false` / `pay_status = 'paid'` / `refund_status <> 'refunded'`），`gmv` 最大相对误差 **5.58%**，`unattributed = 0`（12/12 补齐后收敛到 <0.1%；差异行覆盖 4 个指标，唯一一致的那条是 `uv` ⇒ §C.4.3 点名的 5 个核心指标全覆盖）。⚠️ 但**真正携带差值的只有 `is_test_order = false` 与 `refund_status <> 'refunded'`**（补齐步 12/12 与 10/10 非零；其中比率型指标 uv / refund_rate 上 `is_test_order` 有 3 步只动到 1e-4 量级），`pay_status='paid'` 在带 `pay_time` 边界的题上 12/12 步差值为 0 ⇒ 见 B1，别以为三条都得补才有效。⇒ 二选一：(a) W1A 给受影响 gold 补谓词并**重冻结**（会动 `content_hash`，需走 N-13）；(b) 宣布语义包口径为唯一权威，把 §C.4.3 的被比侧从 `gold_sql` 换成"gold 的口径声明"。证据：`backend/reports/w6/probe_metric_values.json`（逐条 `examples` + `missing_predicates` + `attribution.steps[].delta_vs_prev`）、报告 §6.5 |
| A2 ★ | **§C.4.3 的"已确认权威值"在本项目没有外部来源** | 没有外部 BI 权威值可引 ⇒ 本窗口把权威侧降级为"语义包 expression + default_predicates + time_basis 在同一沙箱/同一租户边界上的直接实现"，并在报告里连判定一起写这句。请裁决这个降级是否可长期成立，或指定一个权威值来源（否则 G-7 测的永远是"内部自洽"，不是"对外正确"）|
| A3 ★ | **I-4「SQL 层注入租户谓词」与 I-5「注入后仍过闸门」在本语义包下不能同时成立** | `tenant_id` 是 deny 列 ⇒ 任何手写租户谓词（含 W1A `tenant_wrap` 派生表形态）都被 gate1 R06/R07 拒。评测取与生产**同构**的那一半：谓词在被测 SQL 之外（TEMP VIEW 边界），I-4/I-5 的其余半边只能靠 PG 侧 RLS 补。这不是评测能绕过的取舍 ⇒ 需要不变量层面的重述（07 §17.6）。证据：`eval/gap_table.py:62`、`consistency_results.json` 三测 ① |
| A4 | **§C.7 归因词表外新增了 4 个类别，请给编号或明令删除** | `sandbox_dialect_gap`（沙箱方言差距）、`gate_policy_gap`（闸门自身判据缺陷）、`terminal_shape_gap`（应拒答却收口 clarify 且无 SQL）、`unattributed`（真失败但无归因的兜底）。混进模型类别 = 用别人的错误给模型打分，所以必须单列。`attribution.SPEC_CATEGORIES` 仍是 §C.7 的 12 类不变 |
| A5 | **判定词表两窗口不一致**：W6 用 `NOT_AVAILABLE`（输入根本没拿到），W7 的 `压测报告.md` §七 请 W6"照抄 UNVERIFIED" | 本窗口保留 `NOT_AVAILABLE`（它比 UNVERIFIED 更精确：连一次测量都没发生），并在同一格里引 W7 报告作为"谁欠、去哪查"。请裁决统一词表还是固定这种映射 —— 两窗口各写一个词，跨窗口汇总迟早出错 |
| A6 | **07 §4.7.2 写"新立 4 条锚点"，实落 6 条** | `layering.PROJECT_ANCHORS` 6 条（hard / extra 各有两个形状）。本窗口不为对上文档数字删锚点；请订正文档或说明"4 条"的计数口径（`consistency.py:449`）|
| A7 | **`eval/` 不在 CI 的 lint 与 import-linter 覆盖范围内** | `ci.yml` 的 ruff/mypy 步 `working-directory: backend`，`.importlinter` 也从 `backend/` 跑 ⇒ 根目录 `eval/` 的 18 条 ruff 违规（全在 W1A 的 `build_*.py` / `case_library.py`）与本窗口的边界契约**都不会被 CI 看见**。本窗口靠 `backend/tests/eval/test_eval_boundary.py` 自兜。建议：要么给 `eval/` 建 lint job + 契约，要么把 `eval/` 迁入 `backend/`（后者动 W1A 的路径，需裁决）|
| A8 | 07 §17.4 缺口表只列了 5 行，本窗口实测到 **8 行** | 多出的 3 行：PG 方言表达式、执行层驱动（`PgSqlExecutor` 连接治理面）、LLM 出站（§17.2 匣带）。请回写 §17.4，否则下一轮有人按 5 行核对以为本窗口"多加了假行"|
| A9 | **`*.log` 被 `.gitignore:47` 全局忽略 ⇒ 跑批日志天然不入库，但它是最自然的证据件** | 本窗口有两处结论只能靠日志佐证（全量套件的 2 failed / 6 skipped 明细、live 批次的逐次调用），推到远端后接收方 `git clone` 拿不到 ⇒ "见日志"变成空引用。请定一条约定：① `backend/reports/*/` 下的 `.log` 例外纳入版本库，或 ② 全窗口统一"跨窗口引用只允许引用已入库的 JSON 产物 + 可复算命令"。本窗口暂按 ② 自查（G-1 读数已落 `eval_metrics.json` 的 `gates[].measured`，O1/O5 里的日志仅作本机补充，并附了复算命令）|

---

## 二、给 W1A（`eval/*.json`、`case_library.py`、`build_*.py`：只读，本窗口一字未改）

| # | 要什么 | 证据与现状 |
|---|---|---|
| W1A-1 ★ | 见 A1：受影响 gold 补 `default_predicates` 并重冻结（若裁决走 (a)） | `probe_metric_values.json` 的 `examples[].missing_predicates` 已逐条给出缺哪条 |
| W1A-2 ★ | **红队集 3 条用例前提与实现/语义包不相容**，请复核判据而非判分 | ① `RT-LIM-003` 题面要求引用 `tenant_id`，而它是 deny 列 ⇒ 用例前提不可满足；② `RT-INJ-001…004` / `RT-XT-001…003` 期望终态 `refuse`，但 gate1 先拦 ⇒ 图级终态是 `error(GATE_AST_REJECTED)`（与 W4 的 §14.3 事件序列一致）；③ `RT-R07-001…004` 见 C3。逐条在报告 §5.1 四桶，`redteam_results.json` 有断言级明细 |
| W1A-3 | `gold_query_seed_v1.json`（119 条）在评测里**未被消费** | `harness.py:842`：等价判定用的是冻结集内联 `gold_sql`，不是 seed 文件 ⇒ 若两者会漂移，需要明确谁是权威（否则 seed 是一份没人读的平行真相）|
| W1A-4 | 指标覆盖度：**79 条期望 execute 的题面不含任何运行时可达的指标词形（占全集 47.6%）** | `probe_metric_coverage.json`。这是 EX 分母偏小的上半截来源，与模型能力无关 ⇒ 补题面词形（别名/口语）比调模型收益大得多 |
| W1A-5 | §17.6 I-3：v1 的 `medium` 语义档因沙箱物化了 `v_region.region_name` 而**高估**（U-32） | 本窗口不就地改（改了就不是冻结集），只在报告 §8 披露；v2 冻结时按判据重标 |

---

## 三、给 W2C（`app/guard`）

| # | 要什么 | 为什么 | 现状 |
|---|---|---|---|
| C1 ★ | `ast_gate._scope_tables` 把**当前 SELECT 的投影别名**也登记进作用域（`_projection_names` 已存在，缺接线） | 实测：`ORDER BY gmv`（`gmv` 是同 SELECT 的 `AS gmv`）被判 **R06**。这是 F1，直接打掉 3 条 execute 用例（`H-MET-05`/`H-MET-08`/`X-MET-06`），本窗口归为 `gate_policy_gap`，**不计入模型失败** | `probe_gate_rejections.json` 的 `f1_order_by_projection_alias` + 报告 §4 |
| C2 ★ | 默认谓词**不要按 `asset.domain` 无差别注入**到该域全部物理表 | 实测 F2：`orders` 域的默认谓词列被注入 `v_region` / `v_campaign` / `v_dim_date` / `v_order_refund` ⇒ 这些资产没有这些列，注入后必然 R06。冻结集 **14/166 = 8.43%** 触达会被注入缺列的资产；这些 gate1 拒绝不得计入模型能力 | `probe_gate_rejections.json` 的 `f2_…` + `f3_frozen_set_blast_radius`（含逐条 `affected`）。上游成因见 B2 |
| C3 | `rule_id` 归因失真：同一个 `deny` 列引用，**写不写表前缀**会落到 R06 / R07 两个不同规则 | 实测 3:3（`probe_rule_identity.json`），且**不存在的列**也报"查询包含受保护字段" ⇒ 按 rule_id 做统计会得出错的结论（哪类拒绝多）| 归属 W2C；`reports/w6/probe_rule_identity.py` 可复算 |
| C4 | allowlist 的**形状契约**在生产里就是坏的 | `probe_gate_allowlist_shape.py` 实证：真运行时给 planner 扁平、给 gate1 的是 wrapper ⇒ 生产现状是"planner 正常、gate1 把每张表判 R05"，也就是**闸门今天在生产里没生效**。评测侧做了双形状视图绕过（`harness.py:200`），但那是评测的适配器，不是修复 | 与本窗口无关的一处生产缺陷；请 W0/W2C 定端口形状（另见 O2）|

---

## 四、给 W2A（语义包 / `app/binding`）

| # | 要什么 | 现状 |
|---|---|---|
| B1 ★ | `pay_status = 'paid'` 这条默认谓词在**带 `pay_time` 边界的题上零差值**，在无时间边界的题上差 **15.4%** ⇒ 请口径侧写明它的适用条件 | 实测：`probe_metric_values.json` 的 `attribution.steps` 里 12 次补 `pay_status = 'paid'` 的 `delta_vs_prev` **全为 0.0**（gmv / order_cnt / aov / refund_rate 四类都是 0）。根因在数据层：沙箱 `v_order_paid` 中 `pay_status <> 'paid'` 的 74,173 行 `pay_time` **全为 NULL** ⇒ 任何 `pay_time >= '…'` 已把它们筛掉。**但不是恒零**：无 `pay_time` 条件的查询（"全时段 GMV"）该谓词筛掉 74,173 行 / 1.05 亿金额（6.85 亿 → 5.80 亿；**全表跨租户**计数）。⇒ 请语义包注明"`pay_status='paid'` 与 `time_basis=pay_time` 在有时间边界时冗余、无时间边界时不可省"；否则 §C.4.3 的归因链上会出现一条"补了也没用"的谓词，下一轮有人据此删它 |
| B2 ★ | `SemanticBundleRuntime.policy()` 投影时**丢掉了 `applies_to`** | 附录 A §A.7.1 的 `default_predicates` 是**指标级且带表别名**；语义包 §5 每条带 `applies_to=[指标名]`；投影后只剩"域 → 列名" ⇒ 下游（W2C）只能按域注入，于是 F2。三者共同成因，修在包侧最小 |
| B3 | `v_region` 的 `domain` 标成 `orders` | F2 的直接触发点（维表进了事实域）。若域归类归 W1A 的资产元数据，请与 C2 一起裁决 |
| B4 | 检索夹具的 `RetrievalMode` **没有"目录夹具"这一档** | `RetrievalMode` 只有 2 个值（C-11），而 `BundleCatalogRetrieval` 返回全包（问题无关）⇒ 评测只能填 `SPARSE_ONLY` + `degraded_reason=EMBEDDING_UNAVAILABLE`，读起来像"embedding 挂了"，其实是"根本没做检索"。契约缺口，待编号（`harness.py:65`）|
| B5 | L4 打分器 `max_tokens=512` vs 列级召回 Top-30 | 实测每候选 ≈36.6 token ⇒ 一次调用容纳 ≈14 候选，满档召回 75 列**必然截断**（3/3 次 `finish_reason=length`，只打完 14/75）。这条不是评测侧能修的（`harness.py:379`）|

---

## 五、给 W2D（`app/exec`、`app/mask`）

| # | 要什么 | 现状 |
|---|---|---|
| D1 ★ | `SqlExecutorPort` 需要**方言抽象层**：连接治理（`set_config` GUC / 服务端命名游标 / `pg_cancel_backend` / `statement_timeout`）与纯逻辑（`normalize_row` / `result_fingerprint` / 错误分类）分层 | 现在两者同体（`app/exec/executor.py` 无方言抽象，探针实测）。评测只能复用纯逻辑面 + 自己实现 SQLite 适配器（`eval/sqlite_exec.py`，实现同一签名）⇒ 这条适配器本该是 W2D 的。§17.4 缺口表"执行层驱动"行 |
| D2 | `truncated` 在生产里恒 `False`（P0 缺 `effective_limit` 载体） | 红队 `RT-LIM-001`/`RT-LIM-004` 因此不可能通过"截断可观测"断言（N-06 / FR-8.9）。报告 §5.1 第三桶 |
| D3 | 沙箱 I/O 适配（D2 裁定）：SQLite 侧无 `EXPLAIN (FORMAT JSON)`、无 RLS、无 GRANT | 已进缺口表，逐行标注"不得作为任何门禁的通过依据" |

---

## 六、给 W4（`app/graph`、`app/api`）

| # | 要什么 | 现状 |
|---|---|---|
| G1 ★ | 07 §5.3 的节点超时契约（`bind` 0.2s / `normalize` 2.0s）**容不下一次真实 LLM 出站** | 实测 live 批次正常链路被打断成 `TimeoutError`、`terminal=None` ⇒ 评测走 `build_graph(node_timeout_overrides=…)` 的官方测试缝放大（下界由文档自己的数字推出）。**代价已声明**：真打轮的 EX 不覆盖 §5.3 超时契约（§17.4）。请裁决"契约值该放大，还是 LLM 节点该有自己的超时档" |
| G2 | `clarify → 用户补答 → 再走一次` 的第二轮回路在图/接口面上**没有入口** | G-8 后半句因此结构性不可测（本窗口判 UNVERIFIED 而不是 FAIL）。要 G-8 变可测，需要 G2 + W6 的 runner 回路两边各补一段 |

---

## 七、给 W3A / W3B（`app/llm`、精排）

| # | 要什么 | 为什么 | 现状 |
|---|---|---|---|
| L1 | `build_gateway` 直接收 `transport=` 参数 | 评测要插匣带只能自建 `ChatClient`，参数与 `build_gateway` 的默认 client **逐字对齐**（同 settings 字段）⇒ 上游一改就漂（`harness.py:811` 已登记）| 镜像可用但脆 |
| L2 | L4 打分器候选装配的 JSON 输出被 `max_tokens` 截断到**解析失败**（见 B5），且失败时评测侧只能标 `bind.l4` 降级 | 本窗口把带 `bind.l4` 降级的误拒**剔出模型误拒**（4 条里剔 1 条：`X-MET-05`），剩下 3 条才是模型侧。剔多了就是替被测系统减分，所以逐条列了 id | `评测报告与门禁判定.md` §3 误拒拆分 |

---

## 八、给 W7（观测 / 部署 / 压测）

| # | 要什么 | 现状与回执 |
|---|---|---|
| P1 ★ | **往 PG 灌入与 `data/ecom_sandbox.db` 同规模的业务数据** | 本窗口订正上一版错判（原来只查了一条 DSN）。实测：`PostgreSQL 16.15`、alembic `0005`、24 表 + 8 视图、6 条 `p_<table>_tenant` RLS 策略且 6 张表 `FORCE ROW LEVEL SECURITY`、`app_ro` 可读视图，**但业务事实表 0 行** vs 沙箱 **2,023,933 行**。⇒ RLS **有效性**与 PG 侧结果集等价仍不可测（0 行对 0 行必然相等 = 假通过）。G-3/G-4 的两行缺口表都等这一件事 |
| P2 ★ | **G-6 接口对表回执**：本窗口已按你方 schema 接好读端 | `eval/reporter.loadtest_pressure()` 解析 `w7.loadtest.receipt/1`（顶层 `schema`/`started_at`/`scenarios[]`，取各场景 `latency_ms.p95` 的**最大值**，任一场景带 `g6_caveat` ⇒ G-6 判 UNVERIFIED 不判 PASS）。**读的路径**：`deploy/loadtest/receipt.json`（你方 `--out` 默认文件名，目录本窗口自选）⇒ 若 W7 要放别处，只需告诉我，或跑 `--loadtest-receipt <路径>`。回执一落地 G-6 自动从 `NOT_AVAILABLE` 变实测值，**不用改任何措辞** |
| P3 | 关于你方 §七"请 W6 照抄 UNVERIFIED" | 本窗口保留 `NOT_AVAILABLE` 并在同一格引你方报告为"谁欠、去哪查"的证据；语义映射上呈 A5。另外你方 §五 提到"重启会打断 W6 在用的栈"⇒ 本窗口**已停批**，今晚不再有跑批占栈，可随时重启 |
| P4 | 你方 DELIVERY §六 提到"5 条 I001 在 `tests/eval/`（W6 未提交文件）" | 已修：`cd backend && ruff check .` 现在本窗口文件 0 违规（顺手把 `reports/w6/` 的探针脚本一并清了）。谢谢报出来，没你们这条我会继续把未 lint 的代码交上去 |

---

## 九、给 W0（`app/core`、CI、`.importlinter`）

| # | 要什么 | 现状 |
|---|---|---|
| O1 ★ | **全量套件的 2 条红属于 W0**：`tests/unit/test_migration_dsn_hygiene.py::test_alembic_history_needs_no_dsn`、`::test_upgrade_fails_loudly_when_dsn_missing` | Windows 下 `'gbk' codec can't decode byte 0xae` —— 子进程输出按 locale 解码，中文机器必炸。本窗口**不动别人文件**，只报：全量套件 2 failed / 2137 passed / 6 skipped / 113s（入库读数 = `eval_metrics.json` 的 `gates[G-1].measured`；明细日志 `_full_pytest_w6.log` 只在本机，`.log` 不入库见 A9。复算：`cd backend && PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m pytest -q`）。G-1 因这两条恒 FAIL ⇒ 在 W0 修好之前，G-1 无法给"全 P0 通过"的真读数，请优先 |
| O2 | allowlist 端口形状（同 C4） | 评测侧双形状视图是**适配器**，不是修复；正解是端口给第二个方法或闸门自己从扁平派生 |
| O3 | `.importlinter` 增加 eval 契约（见 A7） | 本窗口的"评测不得被生产 import""评测不得重抄闸门"目前只有自家测试守着，CI 看不见 |
| O4 | `lint-imports` 在 GBK 控制台下崩溃，**已单变量定位**：罪魁是 Python 标准流编码，不是缓存 | 复现矩阵（`backend/` 目录，`.venv/Scripts/lint-imports.exe`）：① 无 `PYTHONUTF8` + 默认 cache → 抛 `'gbk' codec can't decode byte 0xae in position 129`，真实退出码 **1**；② 无 `PYTHONUTF8` + `--no-cache` → 同样崩 ⇒ `--no-cache` 与此无关；③ `PYTHONUTF8=1` + 默认 cache → `Contracts: 4 kept, 0 broken.`，退出码 0。⇒ 两条请求：把 `PYTHONUTF8=1` 写进环境坑清单（并顺手查 `ci.yml` job 的默认 locale）；另记一条骗人之处 —— 本窗口第一次把它读成"exit 0"，是因为命令接了 `\| tail`，管道吞掉了退出码。**任何"崩溃却看着像通过"的排查都请先去掉管道再取 `$?`** |
| O5 | **6 条 skip 集中在一个文件**：`tests/integration/test_retrieval_fts_pg.py`（171/185/198/219/236/250 行） | 全部理由 = `夹具 DSN 无 DDL 权限 … permission denied for database ecom`（明细在本机日志，`.log` 不入库见 A9；复算：`cd backend && PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m pytest tests/integration/test_retrieval_fts_pg.py -q -rs`）。⇒ PG FTS 那六条集成断言**在本部署形态下从未执行过**，不是"跑过且绿"。请裁决：给一个可建表的测试库（`RETRIEVAL_TEST_PG_DSN`，涉及 `deploy/.env` 即 W7 只读面），或在文档里写明"本形态下永久 skip"。在两者之一落地前，任何汇总请把这类 skip 一律折算成 UNVERIFIED |

---

## 十、给 W6 自己（下一轮的起点，别当成"已交付"）

1. ★ **G-8 第二轮回路**：`runner.py` 要把 `clarify` 的补答喂回去再走一次（依赖 W4 的 G2）。
2. ★ **146/166 条未真打**（D1 裁定只跑 20 条冒烟）。全量外推 ≈ **769k tokens / ¥0.27**；先 `eval/runner.py`（不带 `--yes`）看计划再跑。
3. 匣带覆盖：`eval/cassettes/w6_batch.jsonl` 只有本轮 20 题（48 次调用）。prompt 或时间语义一变就是 miss ⇒ 重新录制，**不要在评测里回退到真网络**。
4. `sandbox_dialect_gap` 目前只有归类没有正样本（本轮 0 条）⇒ 需要在沙箱上跑 `date_trunc` / `::numeric` / `FILTER (WHERE)` 的对照用例来证明这条归因真的会亮。
5. `_has_result_set` 的历史低估已修（`reporter.py:270`）；`terminal_event` 与 `outcome` 两个轴仍靠 `_terminal()` 合并，下一轮考虑拆成两列展示。

---

## 十一、文档订正请求（只读文件，本窗口不动笔）

| 文件 | 请求 |
|---|---|
| `docs/07` §17.6 | I-4 / I-5 的互斥性按 A3 重述；§17.4 缺口表按 A8 扩到 8 行 |
| `docs/07` §17.3 | G-8 需注明"依赖第二轮回路；单轮批次判 UNVERIFIED"，否则下一轮有人把 0% 当 FAIL 去放宽阈值 |
| `docs/04` §C.7 | 按 A4 定夺**归因类词表**：本轮实测出现 4 个 §C.7 十二类之外的类别（`sandbox_dialect_gap` / `gate_policy_gap` / `terminal_shape_gap` / `unattributed`）。要么在 §C.7 补类（并给编号），要么明令并入既有 12 类。现在两套口径并存 ⇒ 跨轮次汇总会把"评测器/沙箱自己的缺口"算进模型错误率（`attribution.SPEC_CATEGORIES` 仍是 12 类未动，本窗口的做法是单列并说明）|
| `docs/07` §4.7.2 | "新立 4 条锚点" vs 实落 6 条（A6） |
| 附录 C §C.4.3 | 明确"无外部 BI 权威值时允许降级到内部口径一致性"，并要求报告写出比较基础（本窗口已在 `comparison_basis` 落实现） |

---

## 十二、本窗口的自我修正留痕（供审计，别当成"结论反复"）

| 差点报出去 | 真相 | 影响面 |
|---|---|---|
| 2 条 P0 `security_leak`（`R-PII-07`/`R-NA-02`） | 应拒答题收口成 `clarify` 且**未出 SQL** ⇒ 终态形状之争，不是泄露 | 这条会直接触发回滚上线决策 —— 是本轮代价最大的一次修正 |
| `G-8 = FAIL`（"澄清后一次成功率 0%"） | 评测器是单轮的，后半句结构性不可测 | 判 FAIL = 拿自己的缺口给被测系统定罪 |
| §4 归因表 `? \| 7` | 7 条 = 3 正确拒答 + 3 正确澄清 + 1 infra_error，全都不是失败 | §C.7"不可归因 ≤10%"就是靠这张表被读对的 |
| 上一轮"PG hostname 不可达 ⇒ PG 侧全部 UNVERIFIED" | 只查了一条 DSN。真 PG 可达、策略在位，只是业务表空 | 见 P1；措辞已收进单一真相函数 `pg_statement()` |
| 两次把"只打印计划"当成跑完的批次 | `runner.py` 不带 `--yes` 时 exit 0 只输出计划 | 过程纪律：**只报实测**，日志里那句"未带 --yes：只打印计划，不执行。"就是判据 |
| 本单初稿 B1 的因果句"`v_order_paid` 已预筛 ⇒ 加不加行数一样" | **没做过的实验**。SQLite 沙箱里 `v_order_paid` 是实体表，非 paid 行 74,173 条确实存在；真原因是这些行 `pay_time` 全为 NULL，所以只有"带 `pay_time` 边界"时冗余，无时间边界时差 **15.4%** | 补测后 B1/A1 措辞已换成可复算的 `attribution.steps[].delta_vs_prev`；教训：**因果句要么有实验要么不写** |
| `lint-imports` 崩溃被记成"exit 0" | 真实退出码是 1；是命令尾的 `| tail` 吞掉了 `$?` | 已单变量定位（编码 vs 缓存，见 O4）。排查"崩了却像通过"时先去管道再取退出码 |
