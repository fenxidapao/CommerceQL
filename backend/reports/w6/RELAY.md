# W6 → 其他窗口的转述单（RELAY）

窗口：W6 · 首轮：2026-09-18 / 第二轮：2026-09-20（G-6 接 W7 的 U-106 口径 + PG 事实复测）
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
| A10 ★ | **G-6 的 P95 分母到底含不含"被限流/被拒的请求"**（W7 的 U-106 把口径改成准入样本，规格没写） | §17.3 只写"P95 延迟 ≤ 8s"。W7 现在给的 `latency_ms.p95` 只在 HTTP 2xx 上算，429 单列 `admission` ⇒ 同一批数据会有两个 P95，达标结论可能相反（本窗口的测试用例就是照这个形状造的：准入 5.2s 达标 / 全请求 12s 超标）。请裁决三选一：① G-6 按**全请求**判（被拒也是用户经历到的延迟）；② 按**准入**判，另立容量门禁管 429 比例；③ 两个都要，取较严者。在裁决前本窗口的做法：有全请求数就按全请求判，只有准入口径时**不判 PASS**（读数里显名分母）。**2026-09-20 补：W7 已明确"全请求不一定更严"且不投票** —— 实测被拒请求回来极快（3 个 401 的 `duration_seconds_sum = 0.0083` ⇒ 平均 2.8ms），把它们算进分位数会**拉低** p95；真正恶化全请求分位数的是另一类非 2xx（长尾失败/超时，如那 145 条 INTERNAL）。⇒ 本窗口选"全请求优先"的理由只是**population 与规格原文一致**，不是"更保守"；净符号取决于当天哪一类占多数，而十份历史回执没存逐样本延迟 ⇒ 只能等一次真跑批定。请裁决时把这一条算进去（别默认「含 429 = 更严」）|
| A11 ★ | **PG 并行下的 RLS 读数要裁一句"算不算接 PG 的硬门"**（本轮实测，见 W7 单 P7 / 本窗口 DELIVERY §4.8） | 实测：`app.shop_ids` 只是 `RESET` 留下的占位符时，`count(*) from app.v_order_paid` 串行恒 200,000、并行 100,385 / 97,282 / 103,929（`Worker 0: rows=0`，整片被策略的 `Filter` 掉，**不报错**）；同一状态下**显式** `set_config` 与真值清单两格两路都精确 ⇒ 生产执行链不受影响，暴露面是"任何把 GUC 留成占位符的连接"（装载脚本、评测适配器、池化连接提交后复用）。**成因已定位（2026-09-21，见 P7 ④）= 占位符 GUC 不随并行 worker 传值**：带列引用的投影实测 `''` 194,377 + `<NULL>` 405,801 = 600,178 且 `Workers Launched = 2` ⇒ leader 读 `''`、worker 读 NULL、策略两条款在 worker 侧同时为 false。我方上一版"worker 没拿到 GUC 已被排除"是**提升性伪影**（投影不带列引用 ⇒ leader 在 Gather 之上算完），已作废；plan 缓存与 index-only 两条排除仍成立。⇒ 待裁的不再是"机制"而是**修法**，请三选一裁死：① 评测的 PG 轮强制串行（`max_parallel_workers_per_gather=0`）并把这条写进 §17.4 的能力差；② 把"四形态并行/串行等值"定为接 PG 的**门禁前置**（不等值就不许进分母）；③ 宣布占位符形态不在受支持范围，并要求装载/评测侧禁走 `RESET`。本窗口**暂按 ② 执行**（判据已常驻、`parallel_equality_ok = false` 已落进产物），但不替任何人改策略文本或 PG 配置 |
| A12 ★ | **上游改出站 prompt 会静默作废评测的匣带证据链 —— 要不要立一条"可复算性"规矩**（第四轮实测，见 W6 交付 §4.3 / §4.9 / §8-10） | 实测：W2A 为解 G-6 卡点把 `metrics()/aliases()` 枚举器接进语义摘要（`fbae176`，**正当改动**）⇒ 首条 system 6,401→11,343 字符 ⇒ `w6_batch.jsonl` 的 48 个报文指纹对今天**20/20 全 miss** ⇒ G-2/G-5/G-7/G-8 的回放读数今天**不可零成本复算**。我方已把这件事变成有产物的读数（`probe_cassette_replay.py` + 报告 §8 三态措辞），但**结构上仍然没人负责**。**给四个选项（含我方立场）**：**①（推荐）规定"改 `app/planner`/`app/llm/prompts` 出站内容的提交必须在 commit 或 RELAY 点名一句'评测匣带受影响'"** —— 不推荐 ②"CI 里跑匣带命中率"（要真打或存指纹基线，成本落在评测窗口且会常误报）；不推荐 ③"每次改动后强制重录"（= 每轮花钱，且违反 §17.2 的"评测不出网"纪律）；不推荐 ④"什么都不立"（下一轮还会以"报告读数悄悄不可复算"的形式回来）。**我方能否自己推进**：能推进的已做完（探针 + 三态措辞 + §6 纪律二改口）；**重录需要额度授权**（20 题 ≈ ¥0.033 / 166 题 ≈ ¥0.27），本窗口不擅自真打。**不推进的后果**：报告里那批回放读数会变成"只有 09-20 那一天成立、且没人知道"的历史快照 |

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
| G1 ✅ **已关闭（U-107 / `d387347`，2026-09-20 在 `76e4e5d` 复测）** | 07 §5.3 的节点超时契约（`bind` 0.2s / `normalize` 2.0s）**容不下一次真实 LLM 出站** | 复测方式同前：只读跑 `_effective_limit_for(name, None)` ⇒ `normalize`/`intent`/`plan`/`gen_sql`/`present`/`repair` **六项全部解析成 15.0s**（§10.2 flash 客户端超时），"预算当硬超时"那一格已被你们按"单一超时点"的正解治掉，我方原文里 `normalize` 2.0s 的例子已随契约失效（本窗口 `eval/harness.py` 的同名注释已跟着订正，没留在报告里当既成事实）。**剩余的一半见 G3：`bind` 仍然实测 0.2s。** 代价声明不变：真打轮我方兜到 162s，与生产 15s/45s **不是同一个数** ⇒ §17.4 缺口表照登 |
| G2 | `clarify → 用户补答 → 再走一次` 的第二轮回路在图/接口面上**没有入口** | G-8 后半句因此结构性不可测（本窗口判 UNVERIFIED 而不是 FAIL）。要 G-8 变可测，需要 G2 + W6 的 runner 回路两边各补一段 |
| G3 ★ **U-107 之后仍未解（2026-09-20 在 `76e4e5d` 复测）** | **`bind` 落在那两份清单的缝里：它打 LLM，却没有 LLM 档超时** | `app/graph/build.py:377` 的 `NODE_TIMEOUT_S` 已不含 LLM 节点（改由 `_LLM_NODE_TASKS` → 路由在执行期解析，`build.py:396-403`），但 **`bind` 不在 `_LLM_NODE_TASKS` 里**，而 `app/graph/nodes/bind.py:180` 明确经 `context.deps.llm` 走 L4 精排。本窗口只读跑函数实测：`_effective_limit_for("bind") = 0.2s`，同一次探测里 `normalize`/`intent`/`plan`/`gen_sql`/`present`/`repair` 全是 15.0s ⇒ 生产路径上 L4 那一跳只有 0.2s，一次真出站必被掐。**评测侧看不出来**（我方给 LLM 节点兜了下界），也就是"评测比生产宽松"的存量一处。请二选一：① `bind` 补进 `_LLM_NODE_TASKS`；② 若 L4 刻意不受节点超时约束，请写进 07 §5.3 并给一处可断言的出口，别让"表里没有"成为隐式答案。<br>⚠️ 顺带把方向说全（同一份探测）：**两份清单双向都不一致** —— `present` 在你们的 `_LLM_NODE_TASKS` 里，而 `nodes/present.py` 全文件对 `llm` **零命中** ⇒ 清单比代码宽（对我方无害，只是别把它当基线）；`bind` 是代码有、清单没有 ⇒ 才是真缺口。⇒ 我方判据固定为"代码是否触达 `deps.llm`"，不照抄任何一侧清单；已加两条守卫：`test_timeouts_survive_contract_slimming`（契约再瘦身也不许让下界消失）+ `test_outbound_budget_nodes_are_not_double_amplified`（`link`/`execute` 不许被放大越过 LLM 档），并把 `not_in_contract` 写进 `describe_node_timeouts` 产物。<br>⚠️ **W7 的 ③ 带来一条读法变更（我方记档）**：按 W7 读码，`bind` 已进 W4 的新出路表 ⇒ `bind` 超时的终止码会是 `refuse(no_data_asset)`，与 `intent`/`link` **共用同一个 reason 枚举**。⇒ 0.2s 被掐的 `bind` 在回执里会长得像"没有数据资产"。本窗口实测 `eval/` 里 `no_data_asset` **零命中**（归因不吃这个字符串），所以现在还没被坑；但下一轮接 PG / 接新出路表时必须显式加一条"reason ≠ 真实成因"的判别，否则这一格会被记成语义包缺口（W1A 的账），把 W4 的超时问题藏起来 |

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
| P1 ✅ **已满足（2026-09-20 复测）**：往 PG 灌入与 `data/ecom_sandbox.db` 同规模的业务数据 | 首轮我报的是「业务事实表 0 行」——那句**结论对了但成因写错了**（见 P6）。本轮带租户上下文复测：`app` 六张租户域基表 **2,024,017 行**，§C.4.3 那五个事实关系求和 = **2,023,933 = 沙箱同数**（逐关系等量），`app_ro` 逐租户可见数求和恰等于属主总数（`order_paid` 200,000+175,000+119,249）⇒ **不重不漏**，两条负对照（零上下文 / 未知租户）都返 0 行。⇒ 缺口表现在可闭：请保持这份数据**不要 truncate**（复灌要多久只有你知道，而 W6 下一轮要接 PG 执行链）。证据：`backend/reports/w6/_probe_pg_real.json` 的 `rls_per_tenant_view_counts` / `rls_partition_check` / `rls_negative_*` |
| P2 ★ | **G-6 接口对表回执**：本窗口已按你方 schema 接好读端 | `eval/reporter.loadtest_pressure()` 解析 `w7.loadtest.receipt/1`（顶层 `schema`/`started_at`/`scenarios[]`，取各场景 `latency_ms.p95` 的**最大值**，任一场景带 `g6_caveat` ⇒ G-6 判 UNVERIFIED 不判 PASS）。**读的路径**：`deploy/loadtest/receipt.json`（你方 `--out` 默认文件名，目录本窗口自选）⇒ 若 W7 要放别处，只需告诉我，或跑 `--loadtest-receipt <路径>`。回执一落地 G-6 自动从 `NOT_AVAILABLE` 变实测值，**不用改任何措辞** |
| P3 | 关于你方 §七"请 W6 照抄 UNVERIFIED" | 本窗口保留 `NOT_AVAILABLE` 并在同一格引你方报告为"谁欠、去哪查"的证据；语义映射上呈 A5。另外你方 §五 提到"重启会打断 W6 在用的栈"⇒ 本窗口**已停批**，今晚不再有跑批占栈，可随时重启 |
| P4 | 你方 DELIVERY §六 提到"5 条 I001 在 `tests/eval/`（W6 未提交文件）" | 已修：`cd backend && ruff check .` 现在本窗口文件 0 违规（顺手把 `reports/w6/` 的探针脚本一并清了）。谢谢报出来，没你们这条我会继续把未 lint 的代码交上去 |
| P5 | 你的 U-106 口径变更**已接**，且那两行**没动** | `eval/reporter.py` 仍逐字比 `schema` 串、**不加未知键校验**：`receipt.json` 新增的 `p95_scope`/`admission`/`rejection_headers`/`latency_ms_all_ms`/`terminal_provenance` 都不在读的路径上，多余键无害 —— 并用 `test_loadtest_pressure_ignores_unknown_keys_and_still_matches_schema_verbatim`（含「版本串改成 `/2` 必须读不出来」的反面对照）把这条兼容性钉死，将来谁想"顺手严格一点"会先撞红。**判定值改为优先取 `latency_ms_all_ms.p95`**（全请求口径）；只有准入口径时**不得判 PASS**（降 UNVERIFIED + 上呈 A10）。复算你的第 3 条：`deploy/loadtest/receipt*.json` **10 份**过真读端 + 真 gates ⇒ `{'UNVERIFIED': 10}`、无一例 PASS（改读端前/后两次都是这个结果），产物 `backend/reports/w6/probe_loadtest_receipts.json` |
| P6 ✅ **已收到你的复现并订正本条目**（原条目的表清单与出路都写错了） | 你 ③ 的矩阵我这侧独立复算：含 `shop_ids` 条款的只有 `order_paid`/`product`/`shop` 三张基表，`order_refund`/`campaign`/`traffic_daily` 是纯租户条件 ⇒ 我原条目里列的 `v_campaign` **不在其中**，已删。另记两条我原先没意识到的：`RESET` 之后取到的是 `''`（= 不限店铺）而不是 NULL ⇒ 只有"从没设过"才落进恒 false 那一格；①的生产路径**已由 executor 保证**（我读了代码核过：`app/exec/executor.py:286-289` 在 `async with conn.begin()` 里发 `app/repo/dsn.py:141-145` 的三条 `set_config(..., true)`，且 `",".join(ctx.shop_ids)` 对"不限店铺"天然给 `''`）⇒ 暴露面收窄到装载脚本 / 评测适配器 / 任何自定义连接（`load_synth_to_pg.py:168` 就是补了那一行才读出数）。②**我撤回 coalesce 的提议**：你的 fail-open 论证成立（把"未设"当"不限"= 整租户跨店铺可读，比 0 行严重），语义已转架构裁；我方诉求收窄成"**漏设就吵**"（装载/评测侧的连接若只设 `app.tenant_id` 就应显式报错或断言，不要静默拿空结果集去给模型打分）。评测侧我自己兜：探针现在两条负对照 + 每次跑都显式设两个 GUC |
| P7 ★ ✅ **已复现 + 成因已定位**（你那句准备动作、和"600,178 行全部报 `''` 是提升性伪影"那条订正，两条都是关键）| 我方上一版写成"未复现"、又写成"机制未定"，**两条都已作废** | ① 我先错在两处，都是自己的问题：把 `debug_parallel_query` 的 off/on 当串行/并行轴（本机 PG 16.15 这个参数只接受 `off/on/regress`，而 **off 下计划里照样出 Gather** ⇒ 我根本没有串行对照组），以及只测"两把 GUC 都显式设值"这一种形态 ⇒ **恒绿正是这一格能藏错的原因**（你的建议①说的就是这件事，已照做）。<br>② 换成"四形态 × 真串行/真并行（串行 = `max_parallel_workers_per_gather=0`）+ 要求 `Workers Launched ≥ 1`"后：`app_ro` / T_A / `select count(*) from app.v_order_paid` 在 `app.shop_ids` **只是 `RESET` 占位符**那一格，**串行恒 200,000、并行 100,385 / 97,282 / 103,929**，计划里 `Worker 0: actual ... rows=0` 且 `Rows Removed by Filter` 覆盖 worker 的整片份额 ⇒ 与你"Worker 0: actual rows=0"完全对上。你的 119,181 / 104,708 / 93,019 / 115,622 我复现到了**同一族**（入库两份产物里 `reset_placeholder` 那一格的并行读数两端：**50,284 – 114,867**，随计划形状变），也复现到你订正前的 98,052。<br>③ 回你的四问：**裸 SQL**（不经执行器）；**两条角色路径我都测了** —— `app_ro` 直接登录 与 "postgres 登录 + 每条连接内 `SET ROLE app_rw`" 读数**一致**（你的 ② 那个"未测"现在可勾掉；顺带一条坑：**`SET ROLE` 不跨连接继承**，我第一版设在外层连接上等于没设，而且 superuser 绕过 RLS 会读出假的"正确"）；串行/并行轴 = `max_parallel_workers_per_gather` 0 vs 2（+`regress`）；`debug_parallel_query` 只当"强制考虑并行路径"用。<br>④ **成因已定位（并且是被你 U-110 那条订正定位的）**：先记我方另一条作废结论 —— 上一版 (c) 说"worker 没拿到这个 GUC"**被证伪**，那个证伪本身是**提升性伪影**：我投影的是不带列引用的 `current_setting('app.shop_ids',true)`，表达式由 **leader 在 Gather 之上**算完 ⇒ worker 进程根本没求值过它，"600,178 行全部报 `''`"只证明了 leader 看到什么。按你给的形状重跑（基表 `app.traffic_daily`、`case when t.tenant_id is not null then coalesce(current_setting(...),'<NULL-in-this-process>') else '<unreachable>' end v, count(*) ... group by 1`、`RESET app.shop_ids` + `set_config('app.tenant_id','T_A',false)`、`max_parallel_workers_per_gather=2` + `regress`、以 `app_rw` 跑）：同一计划 **`Workers Launched = 2`**，读数分两格 **`''` 194,377 + `<NULL-in-this-process>` 405,801 = 600,178**（入库产物里就是这一组；你的 6 个样本两格相加也恒 = 600,178）⇒ **占位符 GUC 不随并行 worker 传值**：leader 读 `''`、worker 读 NULL ⇒ 策略两条款在 worker 侧同为 false ⇒ worker 整片份额被 `Filter` 去掉，且**不报错**。<br>另外两条直观解释仍被排除（这两条我原来的对照形状是带聚合的 `count(*)`，不受提升伪影影响）：(a) plan 缓存 / 预处理语句 —— `prepare_threshold=default|1` × `plan_cache_mode=auto|force_custom_plan|force_generic_plan` 六种组合**全部照样少算**（91,804 – 114,867）；(b) 不是 index-only 节点特有 —— `enable_indexonlyscan=off` / `enable_indexscan=off` / `enable_parallel_append=off` 三组仍少算（50,284 – 106,764）。边界也复核过：显式 `set_config('')`、真值清单两格两路都精确；纯租户条件的视图四形态全等 ⇒ 掉数只发生在"**策略的 Filter 在 worker 进程里读那个占位符键**"。修法归 PG 配置 / 策略文本（**A11 请裁**），本窗口只报读数、不代修，也**不写成 PG bug**。<br>⑤ 给你 P1 的实测输入：当前策略文本是 `= '' OR shop_id = ANY(string_to_array(v, ','))` ⇒ `set_config('app.shop_ids','*')` 实测**读 0 行**（串行并行都是）⇒ **换 `'*'` 哨兵必须连策略一起改**，否则"不限店铺"会静默变成"什么都查不到"（安全上 fail-closed，语义上是另一种错）。另一条新发现的失败形态：在事务里 `set_config(..., true)`（= 生产执行链形状）**提交后再复用同一把连接** ⇒ 恒 **0 行**（两把键的事务级值一起消失、余值 `''` ⇒ `tenant_id = ''` 谁也匹配不上）⇒ 已并入 §十-6b①。<br>⑥ 判据已常驻并如实落盘：`_probe_pg_real.py` 的 `parallel_equality_ok = **false**`（`parallel_undercount_states = ["v_order_paid/reset_placeholder"]`），报告与缺口表按形态点名（`gap_table.parallel_clause`），并接了一条**吃真实产物**的测试防替身形状领先于现实。谢谢这一轮 —— 是你们那条 canary 把我们从"8 组全绿"里拽出来的。
| P8 ★ → W2C | **U-121 的 gate2 那一跳不止一行**（本窗口探针实测，不改你们文件） | 我方把 `asset_allowlist` 原样换成端口 `guard_allowlist` 之后，`run_gate2` 不再返回而是抛 `ContractViolationError：语义包 tenant_scoped 与 tenant_id 列不一致` —— 因为 ⑤ 在 `app/guard/policy_gate.py:148` 用**可见面** `columns` 判「`tenant_id` in columns」，而 `tenant_id` 恰是 deny 列。⇒ 落地要两件事：**(a)** `policy_gate.py:105` 改调 `guard_allowlist(ctx, max_rows=…)`；**(b)** ④⑤ 与 `_column_type`(R17) 改读 **`all_columns`**。⚠️ **不要整包换成结构面**：实测 `SELECT receiver_phone FROM v_order_paid` 在可见面下 = R06 拒、整包结构面（deny 仍在）= R07 拒，但**结构面 + 漏送 `deny_columns` = passed，且改写后的 SQL 里带着 `receiver_phone`** ⇒ 两面必须**按判据分别选**（读数：`backend/reports/w6/probe_gate_allowlist_shape.json` 的 `gate2` / `gate1_face_control`）。另：gate1 那半边评测已能直连端口（两条 SQL 全 passed），不必等我方适配层 |
| P9 ★ → W4 ✅ **已满足（2026-09-22 复测：你们选了方案①）** | 你们的接缝契约 `8a4121a` 输入形状确实选错了；`357618f` 已改对 | **复测读数**：`cd backend && PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest tests/contract/test_gate_seam_contract.py -q` → **2 passed**。Test A 现喂 `rt.guard_allowlist(_ctx(), max_rows=…)` 原样七键（不包装、不加键）、Test B 保留"扁平面必须被拒"的反向对照 ⇒ 我方原判断（"按 U-121 正解改完之后这条照样红"）**作废一半**：你们改的是测试输入本身，不是给扁平面补键。**连带动作**：上一轮我方按"1 failed / 2222 passed / 3 errors"写的 G-1 读数已按新基线复述（见交付 §3、本文件 O6），那条刻意红不再出现在门禁表里。留痕：我方仍不改 `tests/contract/**`（归 W4）；`gate1_ast.py:56` 接线后评测侧 gate1 那一半适配层同时到期，已记 §十-10 |
| P10 → W2A | 你们解 G-6 卡点那一笔，顺带让评测**整批匣带失效** —— 不是责怪，是请今后**点名一句** | `fbae176`（新增 `## 指标口径` 段）使首条 system 从 6,401 涨到 11,343 字符 ⇒ `w6_batch.jsonl` 的 48 个报文指纹对今天 **20/20 全 miss** ⇒ 评测 G-2/G-5/G-7/G-8 的回放读数今天不可零成本复算（我方已落成产物 + 报告 §8 三态措辞，见交付 §4.3/§4.9）。两件事：① 我方**不会**为了让报告好看去改判据、也不会偷偷回退真网络（§17.2）；② 若近期还要改出站报文，请在 RELAY/commit 说一声 —— 重录 20 题 ≈ ¥0.033、全量 166 题 ≈ ¥0.27，需总控授权。另外你们补的 `guard_allowlist`（`b7e6c8d`）**实测可用**：评测侧的私有派生已整体删除、改为直取端口 ⇒ U-119 的副产品一次做完，谢谢 |
| P11 ★ → W7 | 回你 09-21 的 U-120 三态知会：**"你不会红"复算成立**，但我方读端抓到一个三态救不了的假绿灯（已修，附前后对照） | ① **独立复算你的第 1 条**（不照抄）：`git grep g6_p95_le_8s` 全仓唯一写点 = `deploy/loadtest/driver.py:411`，**零读点**；我方 G-6 只取 `latency_ms.p95` / `p95_scope` / `admission` / `latency_ms_all_ms` / `g6_caveat`（`eval/reporter.py` 的 `loadtest_pressure()`）。三态改动确实打不到我方 ⇒ 但你那句"只是礼仪性知会"低估了一处长期风险，所以我把它变成了判据：新增 `test_the_reader_never_depends_on_w7s_g6_boolean`（该字段取 `true`/`false`/`null` 三值时读端产物必须逐字相同），将来谁想让 G-6 去读那个布尔就先撞红。<br>② **订正你那 14 个格的分解**：我方把探针扫描面从 `receipt*.json` 扩到 `deploy/loadtest/*.json`（旧 glob **恰好漏掉** `baseline_c5.json` 与两份 preflight —— 也就是漏掉了唯一会判绿的那一份）。产物 `probe_loadtest_receipts.json` 现在自带 `stale_true_cells_total = 14`（总数与你一致），但分布是 **11 个文件**：`baseline_c5.json` 1 + `receipt.json` 4 + 其余 **9** 份各 1（你写"其余 8 份"分解漏了一项）。<br>③ **一条你那边看不见的约束**：这 14 格所在的 11 份文件**全部没有 `admission` 字段**（`has_admission = false`）⇒ U-120 的三态是**写端未来的行为**，回改不动历史格。所以"别引用这 14 格"这件事在评测侧只能靠**读端兜**，不能等你的新判据生效。<br>④ 🔴 **实测到的假绿灯（本条是给你最有用的信息）**：`baseline_c5.json` 是 13 份里**唯一** `g6_caveat == null` 的那一份（`null_caveat_scenarios_total = 1`），p95 = 3675.8ms、无 `admission`、无 `latency_ms_all_ms` ⇒ 修之前喂我方**真 gates** 得到 **G-6 = PASS**。这正是你们 `driver.py:423-437` 文档里那句"旧文件的 null 会让 G-6 假绿"的形状，2026-09-19 修过一次、09-21 又从这个文件上活着回来；而三态改动救不了它（读端不读那个布尔）。<br>⑤ **我方已按自己边界修读端**（不碰你任何文件、不回写历史回执）：`eval/gates.py` 新增降档 —— caveat 为 null 但**既无 `admission` 又无全请求分位数** ⇒ 至多 UNVERIFIED（超预算照判 FAIL，降档不许洗白）。对照读数（同一条命令、改前 vs 改后）：`13 份：baseline_c5 由 PASS 变 UNVERIFIED`，改后 tally = `{'UNVERIFIED': 11, 'FAIL': 2}`、`any_pass = false`。<br>⑥ **门禁零漂移**：我方 G-6 格的输入路径没动（默认 `deploy/loadtest/receipt.json`，4/4 场景带 caveat ⇒ 一直 UNVERIFIED），改前改后 `gate_summary.counts` 一字未变。**代价照实说**：今后若你出一份"没有 `admission` 也没有 `latency_ms_all_ms`"的回执，我方只能给 UNVERIFIED —— 那是我方故意选保守，需要达标读数就带上那两个字段。<br>⑦ 你"匣带 20/20 我方未复测，花费一律按真调用报"这条**我方接受且认为读法正确**：匣带 miss 只影响我方**复算成本**，不影响你的成本口径。补一句免得被误引：我方报告里"零成本复算"那句已降级成带产物的条件句（见 A12 / P10 / 交付 §5.10）。复算：`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_loadtest_receipts.py`（零 LLM、零网络、只读你方产物）<br>⑧ **两端各自数过、对上了**：你 09:26 的 `stale_true_cells = 14 / files = 11`、"`baseline_c5` 是唯一 caveat=null 且同时缺 `admission` 与 `latency_ms_all_ms` 的那份"与我方产物逐字一致 ⇒ 这条从"一方声明"变成"两方独立实测同数"（我方读数：`stale_true_cells_total = 14`、`null_caveat_scenarios_total = 1`）。也记你一句订正：你上一轮的"12 份"错在把两份 `preflight_*` 混进来 —— 那两份的布尔是 **false**，不在不可引用清单里，而且它们过我方 gates 判 **FAIL**（p95 42,529ms / 187,728.9ms，本就超预算，不是"分母不明"）。<br>⑨ ★ **你把它接受成产出契约（每份回执都带 `admission` + `latency_ms_all_ms`），我方已把这条变成会响的正向对照**：`tests/eval/test_consistency_reporter.py::test_todays_w7_driver_shape_can_still_reach_a_pass` —— 夹具**不手写**，而是按文件路径加载你的 `deploy/loadtest/driver.py` 并调 `_summarize(...)` 现场生成"今天形状"（25 条全准入、零降级），再喂**真读端 + 真 gates** ⇒ 实测判 **G-6 = PASS**、判定值取全请求分位数。今后你删掉那两个键之一，这条当场红，而不是让 G-6 悄悄退化成"永远 UNVERIFIED"；它也防我方自伤（第五轮那条降档若写宽了，真·干净回执会被它压住）。⚠️ 一条踩坑留给你也给我自己：按文件路径 import `driver.py` 时**必须先把模块登记进 `sys.modules` 再 exec** —— 你那边是 `@dataclass(slots=True)`，`dataclasses` 在**建类时**查 `sys.modules[cls.__module__]`，不登记就抛 `'NoneType' object has no attribute '__dict__'`，**症状看起来像你的件坏了、其实是我方的加载方式**（第一版就是这么红的）。<br>⑩ 不可引用清单你会点名 `baseline_c5` ⇒ 收到；我方侧同一份的同一事实已进产物（`null_caveat_scenarios_total = 1`），不需要谁背书。 |

---

## 九、给 W0（`app/core`、CI、`.importlinter`）

| # | 要什么 | 现状 |
|---|---|---|
| O1 ✅ **已关闭（2026-09-20 复测）** | 全量套件的 2 条红属于 W0：`tests/unit/test_migration_dsn_hygiene.py::test_alembic_history_needs_no_dsn`、`::test_upgrade_fails_loudly_when_dsn_missing` | 首轮是 `'gbk' codec can't decode byte 0xae'`（子进程输出按 locale 解码）⇒ G-1 恒 FAIL。本轮重跑：**0 failed / 2160 passed / 6 skipped（102s）**⇒ W0 已修，G-1 自动转 PASS（`eval_metrics.json` 的 `gates[G-1].measured`）。谢谢收口；本窗口没动你们任何文件 |
| O2 | allowlist 端口形状（同 C4） | 评测侧双形状视图是**适配器**，不是修复；正解是端口给第二个方法或闸门自己从扁平派生 |
| O3 | `.importlinter` 增加 eval 契约（见 A7） | 本窗口的"评测不得被生产 import""评测不得重抄闸门"目前只有自家测试守着，CI 看不见 |
| O4 | `lint-imports` 在 GBK 控制台下崩溃，**已单变量定位**：罪魁是 Python 标准流编码，不是缓存 | 复现矩阵（`backend/` 目录，`.venv/Scripts/lint-imports.exe`）：① 无 `PYTHONUTF8` + 默认 cache → 抛 `'gbk' codec can't decode byte 0xae in position 129`，真实退出码 **1**；② 无 `PYTHONUTF8` + `--no-cache` → 同样崩 ⇒ `--no-cache` 与此无关；③ `PYTHONUTF8=1` + 默认 cache → `Contracts: 4 kept, 0 broken.`，退出码 0。⇒ 两条请求：把 `PYTHONUTF8=1` 写进环境坑清单（并顺手查 `ci.yml` job 的默认 locale）；另记一条骗人之处 —— 本窗口第一次把它读成"exit 0"，是因为命令接了 `\| tail`，管道吞掉了退出码。**任何"崩溃却看着像通过"的排查都请先去掉管道再取 `$?`** |
| O5 | **6 条 skip 集中在一个文件**：`tests/integration/test_retrieval_fts_pg.py`（171/185/198/219/236/250 行） | 全部理由 = `夹具 DSN 无 DDL 权限 … permission denied for database ecom`（明细在本机日志，`.log` 不入库见 A9；复算：`cd backend && PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m pytest tests/integration/test_retrieval_fts_pg.py -q -rs`）。⇒ PG FTS 那六条集成断言**在本部署形态下从未执行过**，不是"跑过且绿"。请裁决：给一个可建表的测试库（`RETRIEVAL_TEST_PG_DSN`，涉及 `deploy/.env` 即 W7 只读面），或在文档里写明"本形态下永久 skip"。在两者之一落地前，任何汇总请把这类 skip 一律折算成 UNVERIFIED |
| O6 ★ | **同一条夹具根因长出的 3 条 `ERROR`，如今是 G-1 唯一的红因**（第五轮复测订正，请并进 O5 一起处理） | 读数换过一次：第四轮我报的是 `1 failed / 2222 passed / 3 errors（112.70s）`，那条 failed = W4 为 U-119 立的刻意红；W4 落 `357618f`（接缝测试输入改对，见 P9）之后 ⇒ **2026-09-22 实测（收口那次）`0 failed / 2232 passed / 6 skipped / 3 errors / 127.76s`，commit `6da16db`** —— 让 G-1 仍红的**只剩这 3 条 error，且全部在窗外、坏的是测试环境不是被测系统**。（同一轮内先后出现过 `2228 → 2230 → 2231 → 2232` 四个数：前三次的差 = 我方自己补的取证测试，最后一次的差 = W4/W2C 又落了两笔 ⇒ **报数必须连着 commit 一起记**，别把两个数当成矛盾。）三条用例名（`-rfEs` 才点得出，小写 `e` 不收 error）：`test_dense_null_rows_never_crowd_out_valid_vectors`、`test_dense_all_null_column_raises_unavailable_not_type_error`、`test_dense_scope_with_zero_rows_is_not_degradation`，全在 `tests/integration/test_retrieval_fts_pg.py`（夹具 `dense_table` 里 `CREATE SCHEMA` 抛 `InsufficientPrivilege: permission denied for database ecom`）⇒ 与 O5 那 6 条 skip **同一根因**，只是那条路径有 `try/except → pytest.skip`、这条没有 ⇒ 表现成"错误"而不是"跳过"。我方侧已做两件事：`gates._p0_notes()` **逐条点名到测试**，且 `measured` 里把「断言失败」与「夹具 error」拆成两个数（旧写法 `failed=4` 把两类混成一个数，正是要防的误读）。归属：夹具 = W0/W2B（`c6373a2`/`1255065` 那条 dense 路径）。复算：`cd backend && PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest -q -rfEs` |

---

## 十、给 W6 自己（下一轮的起点，别当成"已交付"）

1. ★ **G-8 第二轮回路**：`runner.py` 要把 `clarify` 的补答喂回去再走一次（依赖 W4 的 G2）。
2. ★ **146/166 条未真打**（D1 裁定只跑 20 条冒烟）。全量外推 ≈ **769k tokens / ¥0.27**；先 `eval/runner.py`（不带 `--yes`）看计划再跑。
3. 匣带覆盖：`eval/cassettes/w6_batch.jsonl` 只有本轮 20 题（48 次调用）。prompt 或时间语义一变就是 miss ⇒ 重新录制，**不要在评测里回退到真网络**。
4. `sandbox_dialect_gap` 目前只有归类没有正样本（本轮 0 条）⇒ 需要在沙箱上跑 `date_trunc` / `::numeric` / `FILTER (WHERE)` 的对照用例来证明这条归因真的会亮。
5. `_has_result_set` 的历史低估已修（`reporter.py:270`）；`terminal_event` 与 `outcome` 两个轴仍靠 `_terminal()` 合并，下一轮考虑拆成两列展示。
6. **把 PG 执行链接进来**（现在是本窗口最大的剩余缺口）：`PgSqlExecutor` + 两个 GUC 进 `runner.py`，并把探针的 `rls_partition_ok` 接成 `cross_tenant.pg_rls_verified`。G-4 现在**故意**仍写"未在真实 DB 层验证"——判据只到"策略对原始 SQL 阅读器有效"，不等于"我们的链路在 PG 上隔离正确"，不许提前吃这条绿灯。
6b. **PG 适配器的三条硬要求**（从 P6/P7 长出来的，不是可选项）：① 连接装配必须**在事务内**同时设 `app.tenant_id` **和** `app.shop_ids`，并且**当批断言两把键都已生效**——实测：只设前者 ⇒ 三张表恒 0 行且不报错；而在事务里用 `set_config(..., true)` 设过、**提交后复用同一把连接** ⇒ 两把键的事务级值一起消失、`current_setting` 只剩 `''`（实测 `tenant_id = ''` 谁也匹配不上）⇒ 同样恒 **0 行**（fail-closed，但 0 行极易被误读成"模型没查到东西"）；② "并行开/关结果相等"已升级为常驻判据，但**形状换了**：旧版 `debug_parallel_query` off/on 不构成串行对照（off 下计划里仍有 Gather），现在跑"四形态 × 真串行(`max_parallel_workers_per_gather=0`)/真并行 + `Workers Launched ≥ 1`"。本轮实测 `parallel_equality_ok = **false**`（`v_order_paid/reset_placeholder` 少算约一半）⇒ **接 G-4 之前要么这一格转 true，要么由 A11 裁决强制串行**，不许带着 false 进分母；③ 09-18 那批的 `node_timeouts` 快照与当前树已不一致（报告 §0 会点名），下一轮若重录批次，顺手把 §8-9 的绝对路径一起换掉。
7. **G-6 的收紧点**：A10 一旦裁决，`gates.py` 里"只有准入口径 ⇒ 不判 PASS"这条要么删掉（口径定为准入）、要么保留并注明依据。别让这段逻辑变成没人知道的私人偏好。
8. **产物去绝对路径**：`reporter._rel()` 已用于回执来源；剩 `meta.run_config`（`runner.py` 落盘）与 `consistency_17_6.…artifacts.paths` 两处仍是本机绝对路径。
9. ★ **超时契约一个月内换了两次形状**（U-104 移节点、U-107 改执行期解析）⇒ 下一轮开工第一件事：只读跑一遍 `app.graph.build._effective_limit_for(name, None)`，把生效值和本单 G1/G3 引用的数字重新核一遍，再动 `eval_node_timeouts()`（判据与踩坑记录写在 `eval/harness.py` §五 的注释里）。这些数字**不会**有人通知评测窗口，漂移只会以"批次莫名变红/评测比生产宽松"的形式回来。
10. ★ **第四轮新增的两条到期项**（都带机制，不靠记性）：① **匣带重录** —— 今天 20/20 miss（成因在上游 `fbae176`），要重出 G-2/G-5/G-7/G-8 的回放读数必须真打（20 题 ≈ ¥0.033，需授权），复算命令与命中率见 `probe_cassette_replay.py` / `cassette_replay_probe.json`；开工前先跑一次这个探针，别默认 `--mode replay` 可用。② **删适配层** —— `AssetAllowlistView` / `GuardAllowlistBundle` / `StructuralAllowlistBundle` / `structural_wrapper` 四处。**2026-09-22 状态订正：这一项已经到期了一半**（W4 `357618f` 让 `gate1_ast.py:56` 改调 `guard_allowlist`，只剩 `policy_gate.py:105` 还读扁平面），而我方**并集式哨兵对这件事完全没响** ⇒ 机制换成两层：`test_the_dual_shape_view_dies_with_the_consumer_fix` 改**按文件**判（两道都接线才 fail，但逐文件读数写进消息），另加 `test_the_adapters_stated_reason_list_matches_the_code` 双向核对 `eval/harness.py` §三 那行 `存在理由（仍在读扁平面…）: <文件>:<行>` —— 清单点名了已接线的文件 ⇒ 红，接了线却没进清单 ⇒ 也红。**别把任何一条改成 skip 让它绿**（U-119 明令禁止的动作）。**默认方案（不阻塞）**：gate1 那半边的视图今天就能删，但它与 gate2 半边同在一个代理类里、改动面 = 10 处调用点（`harness.py:308/972`、`runner.py:446`、`redteam_eval.py:362/395/662`、conftest 与 4 处测试），**代价 = 同一个类改两遍 + 红队产物做两次漂移对照** ⇒ 默认等 P8 落地一次删净；要提前做只需总控说一声。③ ★ **第五轮新增：G-6 读端的降档 + "14 个 stale 格不引用"** —— `deploy/loadtest/` 的 14 个 `g6_p95_le_8s = true` 历史格（分布在 11 个文件）一律不得进任何读数；W7 的 U-120 三态只约束**今后**的写端，回改不动它们，而我方读端从不读那个布尔 ⇒ 兜底只能在我方做：`gates.py` 已加"caveat 为 null 但既无 `admission` 又无全请求分位数 ⇒ 不判 PASS"的降档（实测被救回来的正是 `baseline_c5.json`：修前 G-6 = PASS，修后 = UNVERIFIED）。下一轮开工**照旧**先跑 `probe_loadtest_receipts.py`，看 `any_pass` 是不是 false。

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
| 首轮入库的 `_probe_pg_real.json` 写着"PG 业务事实表 0 行 ⇒ 不可测" | **数字是真的，成因是假的**：探针没设 `app.shop_ids` ⇒ 策略恒 false ⇒ 视图恒 0 行；同一时刻属主侧基表已有 200 万行 | 带上下文复测 + 两条负对照（见 P1/P6），并重录产物；教训：**"数到 0"要先问"是不是我没给它看见的条件"** |
| 照抄 W7 的"十份回执全 UNVERIFIED" | 跨窗口声明不能当自己的读数用（读端刚被我改过） | 自建 `probe_loadtest_receipts.py` 真跑一遍（10 份，改前/改后各一次，`{'UNVERIFIED': 10}`）才写进 §4.6 |
| RELAY P6 初稿把受害视图写成 4 个（含 `v_campaign`），并建议用 coalesce 把"未设"当"不限" | 只有三张基表带 `shop_ids` 条款；且 `''` **已经**是"不限店铺"⇒ 那个提议会把 fail-closed 换成 fail-open（整租户跨店铺可读） | W7 用 `SET ROLE` + 五种写法复现后证伪 ⇒ P6 已订正/撤回，诉求改成"漏设就吵"（语义交架构裁） |
| 自家注释与本单 G1 里"`normalize` 契约 **2.0s** 被真出站打断"这个例子 | U-107（`d387347`）之后该例**作废**：LLM 节点的硬超时不再写死在 `NODE_TIMEOUT_S`，执行期解析为客户端超时（本轮只读实测 `normalize`/`intent`/`plan`/`gen_sql`/`present`/`repair` 全部 15.0s）。`bind` 的 0.2s **仍然成立**（G3 未解） | G1 关闭、G3 保留并订正引用行号；教训：**引用别人的契约值要带 commit，否则自己的注释会变成下一个假事实** |
| 我给"非 LLM 节点"统一乘 `EVAL_CPU_FACTOR = 8` 的放大规则 | 这条规则是冲"0.1s 闸门在慢机上假阳性"写的；U-107 把 `link` 的契约值抬到 30s（= `EMBEDDING_TIMEOUT_SECONDS`，出站客户端超时同档）后，无脑乘系数 = **240s**，而评测走本地夹具检索（不出网）⇒ 放大的是墙钟、不是被测事实 | `link` 移进 `EVAL_TIMEOUT_AS_CONTRACT`（逐节点写理由）+ `test_outbound_budget_nodes_are_not_double_amplified`；教训：**系数的适用前提要写下来，不然上游改了值它就悄悄失效** |
| 我第一版并行对照给出 `count(*) = 0`、`sum = None`（像复现了 W7 的 ④），订正后又上报"**未能复现**" | 两次都错：① 复用同一条连接/同一个事务 ⇒ 读的不是并行路径；② **第二次的结论更贵** —— `debug_parallel_query` 在本机 PG16 只有 `off/on/regress`，**off 下计划里仍有 Gather** ⇒ 我以为的"串行对照组"根本不存在，且只测了"两把 GUC 都显式设值"一种形态。换成真轴后**少算当场复现**（`v_order_paid/reset_placeholder`：串行 200,000 / 并行约 103k，`Worker 0: rows=0`） | 见 P7 / A11 与交付 §4.8；产物 `parallel_equality_ok` 从 `true` 改落 **`false`**。教训：**"我的对照组全绿"要先证明那组对照真的有对照组；没有对照组的绿 = 恒绿，而恒绿正是这一格能藏错的原因** |
| 我用来"排除 worker 没拿到 GUC"的那条对照：从不含 shop 条款的视图里并行投影 `current_setting('app.shop_ids',true)`，600,178 行**全部**报 `''` | **提升性伪影**（W7 的 U-110 指出）：投影表达式不带列引用 ⇒ 由 **leader 在 Gather 之上**算完，worker 进程从未求值它，这条读数只能证明 leader 看到什么。换成带列引用的形状重跑（`case when t.tenant_id is not null then coalesce(current_setting(...),'<NULL>') else '<unreachable>' end, count(*) group by 1`，同一计划 `Workers Launched = 2`）：**`''` 194,377 + `<NULL>` 405,801 = 600,178** ⇒ 结论反号，worker 侧**就是**读不到那个占位符，成因由此定位 | 它一度让 P7 挂着"机制未定"、并把归因往"策略去读占位符键"以外的方向带偏；现在 P7 ④ / A11 / 交付 §4.8 已改成"成因已定位 + 修法待裁"。教训：**测"另一个进程看到什么"时，表达式必须带列引用被下推；先证伪"这格是不是在 leader 算的"，再谈结论** |
| 我在回应 W7"成本基线重开"时写下"`eval/` 与 `reports/w6/` 对 `cost_ledger` **零引用**" | 复算把自己证伪了：`grep -rin cost_ledger eval/ backend/tests/eval/` = 0 命中（代码侧成立），但**本窗口已入库的** `_probe_pg_real.json` 里就有三处（`pg.pg_row_counts.cost_ledger = 3`、`parity.relations[4].pg = 3`、`pg.rls_flags[4]`）⇒ 那句否定过宽；而 3 与 W7 现报的 6 行不一致，恰是"表被清空过"的痕迹 | 交付 §4.8 已改口成两层（**代码侧零依赖 ⇒ 门禁读数无需重取**；**产物侧有清单级快照 ⇒ 重跑会变、不进任何判定**）。教训：**全称否定句要写清扫描范围**，尤其是被扫对象里包含自家产物时 —— W7 这条"清空"提醒真正有价值的部分，是逼我方去查自己产物里的隐性依赖 |
| §6 纪律二与 §4.3 里那句「匣带足以承担零成本复算 ⇒ 自我修正不必再花一次钱」 | 说得不算错，但**没时间戳、也没人有责任在它失效时改口**。第四轮想复算时 20/20 全 miss（上游把指标口径接进 prompt），而这件事**一直没人报**，直到我要重算才发现 | 能力句改成**带产物的读数句**：新增 `probe_cassette_replay.py`（命中率）+ `reporter.replay_reproducibility()`（三态措辞）⇒ 再失效它会自己出现在报告 §8。教训：**凡是"随时可以重算"这类能力断言，都要配一个会过期的探针**，否则它只在真要花钱的那天才被证伪 |
| 我复算 W7"十份回执全 UNVERIFIED"时把**他们的扫描面**一起继承了（探针 glob 写死 `receipt*.json`） | 复算本身没错（`{'UNVERIFIED': 10}`，改前改后两次一致），但"扫哪些文件"是**声明的一部分**：同一目录里的 `baseline_c5.json` 与两份 `preflight_*.json` 从没进过任何一侧的扫描面，而 `baseline_c5.json` 恰好是**唯一喂我方真 gates 会判 G-6 = PASS 的那一份**（p95=3675.8ms、`g6_caveat` 为 null、无 `admission`、无全请求分位数） | 扫描面改成 `deploy/loadtest/*.json`（13 份），并把"为什么不用 `receipt*`"写进注释；改后 `{'UNVERIFIED': 11, 'FAIL': 2}`、`any_pass = false`。教训：**复算别人的声明时，判定要自己跑，覆盖面也要自己定 —— 照抄 glob 等于把对方的盲区装进自己的证据链** |
| G-1 的 `measured` 写成 `failed = 1 failed + 3 errors`，且点名正则把 `FAILED` 与 `ERROR` 收进同一个列表 | 两个数说的是**不同的坏法**：断言失败 = 被测系统，夹具 error = 测试环境，归属窗口也不同（后者是 O6 的 W0/W2B）。混成一个数，下一轮就会有人问"评测系统坏了 4 处？" | `reporter.parse_pytest_summary()` 拆成 `failed_tests` / `error_tests`（两条正则），`gates._p0_notes()` 分组点名，`measured` 改成「断言失败 0 + 夹具 error 3 = 红 3 条」；顺带记一条取证坑：`-r` 里点 error 名的字符是**大写 `E`**，我方 §8 原来写的 `-rfes` 根本点不出名字 ⇒ 已改，并加 `test_pytest_summary_keeps_assertion_failures_and_fixture_errors_in_separate_lists` |
| 我上一轮上线的"适配层到期哨兵"用的是**两文件并集**判据，写的时候自评是"不靠记性" | W4 `357618f` 只接了 gate1 半边（`gate1_ast.py:56` → `guard_allowlist`），并集判据要等两边都接完才响 ⇒ 今天它**既不红也不报**，而 `harness.py` 里"消费方还在读 `asset_allowlist`（点名两个文件）"那句注释当场失真一半。机制没失效，是**机制的判据选错了粒度** | 改**按文件**判 + 逐文件读数写进消息；新增 `test_the_adapters_stated_reason_list_matches_the_code`，把"还剩谁没接线"从散文升级成 `harness.py` §三 那行机器可读清单并**双向**核对（点名了已接线的 ⇒ 红；接线了没进清单的 ⇒ 也红）。教训：**"到期就红"这类机制必须按最小可到期单元设计，否则它只在最后一件事发生时才工作，而错的是前一半** |
