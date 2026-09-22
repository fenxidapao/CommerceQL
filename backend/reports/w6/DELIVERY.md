# W6 交付 —— 阶段 6 · 评测与门禁

> 窗口：W6｜日期：2026-09-18｜分支 `main`｜提交：`feat(w6)` + `docs(w6)`（见 §7）
> 依据：`reports/w6/PROMPT.md`（T1–T8）｜规格：07 §17 全章 + 附录 C §C.4/§C.6/§C.7 + 08 §3.8
> 权威优先级：附录 A(02) > PRD(01) > 06 UIUX > 07 TDD > 08 实施计划
> **本报告里所有数字都来自产物 JSON**（`backend/reports/w6/eval_metrics.json`），
> 要改结论得改 `eval/reporter.py` —— 文字也生成在代码里，不给"顺手抄一句"留空间。

---

## 1. 交付范围

| 产出 | 行数 | 对应任务 / 门禁 |
|---|---|---|
| `eval/runner.py` | 630 | T2 批次执行器：验真 → 计划 → 跑批 → 备份 → 落盘（§C.6.1 三条纪律全部落在这里） |
| `eval/harness.py` | 898 | T2 **在线 `app/guard`/`app/exec` 的复用面**（ADR-18）+ 租户边界装配 + 节点超时派生 |
| `eval/sqlite_exec.py` | 384 | T2/D2 沙箱执行适配器：实现 `SqlExecutorPort` 同一签名，复用 `app/exec` 的纯逻辑 |
| `eval/cassette.py` | 202 | T1/§17.2 LLM 出站录制/回放匣带（httpx transport，JSONL，miss 即抛不回落网络） |
| `eval/equivalence.py` | 478 | T3 §C.4.1 九条结果集等价规则 + 指纹 |
| `eval/attribution.py` | 221 | T3 §C.7 归因器（短路顺序：安全 > 交互 > 闸门 > 执行 > 模型） |
| `eval/grid.py` | 124 | T4 4×3 分层网格（I-1 主口径：结构档用**重算标签**，不信用题面字段） |
| `eval/gates.py` | 430 | T5 G-1…G-8 判定 + 五词判定词表（第五轮 +G-6 分母降档分支、G-1 把断言失败与夹具 error 分组点名；第六轮 +`_pg_surface_notes()`：报"全量"时**红不红都声明**分层与 PG 接触面） |
| `eval/gap_table.py` | 237 | T5 §17.4 沙箱能力缺口表（8 行，每行 `covered_by_eval=False`；RLS / 并行等值两行的措辞均由探测派生）|
| `eval/consistency.py` | 533 | T6 §17.6 一致性三测（I-1 白名单扫描 / I-6 三条哈希链路 / §4.7.2 锚点回归） |
| `eval/redteam_eval.py` | 738 | G-3/G-4 §7.8 红队矩阵 66 条断言级判定 |
| `eval/reporter.py` | 1354 | T7 报告器（Markdown + `eval_metrics.json`；§17.4 表与 §8 已知限制由它生成；本轮加"跑批快照 vs 当前树"的超时表漂移点名；第五轮把日志里的 `FAILED` 与 `ERROR` 拆成 `failed_tests` / `error_tests` 两个取证列表；第六轮 +`pg_surface()`：从日志取证"含不含集成层 / 被拒的库 / 夹具下发过的 DDL 形状"，四个出口一律过 `_redact`） |
| `eval/pg_guard.py` | 98 | 第六轮新建：**会响的只读闸门** —— `force_readonly()` 把 `default_transaction_read_only` 编进 DSN，`open_readonly()` `SET`+`SHOW` 复核后**故意写一次并期望被拒**，没过闸门探针不出产物；`target_stamp()` 落"连到哪个库、以谁的身份"，`redact_dsn()` 保证凭据不落盘 |
| `eval/_bootstrap.py` | 121 | 冻结件验真的唯一入口（N-13） |
| `backend/tests/eval/**`（12 文件） | 3,930 | D4 裁定：评测器自己的测试，**334 条**（第六轮 +16：`test_pg_contact_surface.py` —— 接触面取证 4 条（含**照抄真日志 repr 形状**的正对照与截断点名）、声明出不出/措辞下界 4 条、闸门"会响"3 条、DSN 编码与脱敏 4 条、G-1 固定键 1 条；第五轮 +9：G-6"分母无从核对不得判 PASS"2 条、现行 driver 形状仍可达 PASS 的正向对照 1 条 + 装配路径上的同判据反面对照、"读端永不依赖 W7 那个布尔"三值参数化 1 条、G-1 把断言失败与夹具 error 分开取证 2 条（判定格 + 日志解析）、适配层"存在理由清单"双向核对 1 条、`_all_pass_inputs` 的压测夹具改成现行干净形状 1 条；第四轮 +3：端口形状逐键转发的正对照 / 评测不得自造 wrapper 形状 / 适配层到期哨兵；第二轮 +9：G-6 口径 5 条、读端兼容 2 条、RLS 措辞派生 2 条；第三轮 +4：超时并集/放大档漂移守卫 2 条、并行等值按形态点名的措辞 1 条 + 探针读端 1 条、快照漂移点名 1 条、**吃真实产物**的并行措辞回归 1 条 —— 并把原 300 条里的超时契约测试按新形状重写） |
| `backend/reports/w6/**` | 2,691 | 取证产物：取证脚本 **12** 个 `.py`（第四轮新增 `probe_cassette_replay.py`，并把 `probe_gate_allowlist_shape.py` 从「第二步就崩」改成跑到底出结论；第五轮把 `probe_loadtest_receipts.py` 的扫描面从 `receipt*.json` 10 份扩到 `*.json` **13 份**；第六轮给 `_probe_pg_real.py` 与 `_probe_parallel_states.py` **接上只读闸门**，两份产物各多一个 `pg_guard` 自证键；**续轮新增 `probe_pg_boundary.py`（168 行）** —— 因为 `count(*)` 对"整表重载"不敏感，改取 `relfilenode` + `n_tup_ins/del` 这类**对变化敏感**的签名，跑前/跑后各一次并写差值）+ 日志 + `results_w6_live20.json` + 匣带 + 本报告 |

合计 `eval/` 新模块 **14 个 / 6,464 行**，测试 **3,930 行 / 331 条**（口径：`eval/` 下除 W1A 的 `case_library.py`/`build_*.py` 之外的 `.py`；`wc -l` 现场核过，同一口径在 HEAD `82f5bdb` 复算 = 13 个 / 6,393 行；第七轮删适配层后按同口径复算 = 6,464 行（`harness.py` −112、`redteam_eval.py` −49，reporter/gates/runner 三处共 +12 ⇒ 差值全部可指到具体文件） ⇒ 上一轮那句"6,393"没写定义，本轮起把定义写进表里）。**未落笔他人范围**：
`eval/*.json`、`eval/case_library.py`、`eval/build_*.py`（W1A）｜`app/**`（W0–W4）｜`frontend/**`（W5）｜`deploy/**`、`app/obs/**`（W7）。

---

## 2. DoD 逐条自验（08 §3.8）

| # | 要求原文 | 落点 | 可核对的证据 |
|---|---|---|---|
| ① | 能产出「**评测报告 + 门禁判定**」 | `eval/reporter.py` → `reports/w6/评测报告与门禁判定.md` + `eval_metrics.json` | 复算指令在报告 §10；`test_missing_artifacts_degrade_to_not_available_not_crash`（零输入也要出报告，且不许出现 PASS） |
| ② | 报告**必须含未覆盖项声明**（§17.4） | 报告 §7 缺口表（8 行）+ §8 已知限制（10 条） | `eval/gap_table.py` 每次重新生成；`test_zero_input_report_still_carries_the_gap_table_and_limitations` 同时钉住两件事：零输入时缺口表**不许缺席**，且 8 行**全部** `covered_by_eval is False` |
| ③ | **τ 变更必须附校准报告**（N-25） | 本窗口**未修改 τ**（`BINDING_TAU` 仍是 0.2），也未新增 τ 取值路径 | 报告 §9：`changed_this_window: False`；`test_tau_facts_report_presence_not_values`（只报"有没有值"，不打印密钥/值） |

### 2.1 收口结论"必须如实写的三条"

| 条 | 本窗口的写法 | 位置 |
|---|---|---|
| ① 沙箱与生产的能力差距逐条声明 | §17.4 表 8 行 + 每行"本次实测证据"列由产物回填（不是套话） | 报告 §7 |
| ② τ 未校准 ⇒ L4/准确率结论标 UNVERIFIED + R-19 | `_TAU_DEPENDENT = {G-2, G-5, G-7, G-8}`，`_tau_verdict` **只降级 PASS**（未校准下的 FAIL 仍是 FAIL，方向偏向拦住上线） | 报告 §1 caveats 列 + `test_uncalibrated_tau_does_not_soften_a_fail` |
| ③ G-6 引用 W7 压测结果时注明数据来源与取数时点 | **第二轮已满足**：G-6 的输入 = `deploy/loadtest/receipt.json`（schema `w7.loadtest.receipt/1`）**已存在并被读到**，读数里带来源与 `started_at` 时点（`P95 = 7268ms，分母 = 口径未标注 = U-106 之前的回执`）；判定因回执自带"0 条真正完成"的 `g6_caveat` 而落 UNVERIFIED ⇒ 没有把没完成的跑批写成达标 | 报告 §1 G-6 行 + `test_loadtest_pressure_refuses_to_invent_a_p95` |

---

## 3. 门禁判定（本轮实测）

`PASS 0 / FAIL 4 / UNVERIFIED 2 / PARTIAL 2 / NOT_AVAILABLE 0`　（2026-09-22 第六轮实测；**连续三轮一字不差** —— **第四轮起 PASS = 0**，第二轮那句 `PASS 1 / FAIL 3` 是历史读数，保留在此只为让"为什么掉到 0"可追溯）
⚠️ **判定集合不变 ≠ 红因不变**：同日续轮（16:3x，HEAD `d367287`）G-1 的构成换成 **21 条断言失败 + 10 条夹具/收集 error = 红 31 条**，其中 **3 条在本窗内**（适配层到期哨兵按设计响了，见 §4.12⑥），其余在窗外（W4 决策表 11+4+2、W2D 红队 1、7 个集成包 import 期 fail = U-114 防线①）。下表那一格的 `2254 / 3 errors @ 3ff31c4` 是**上一轮次**的读数，保留作对照，不当本轮用。
🔴 **第七轮（同日 17:0x，HEAD `c76f701`）G-1 的红因又换了一次，而且这次多了一条真失败**：**1 条断言失败 + 10 条夹具/收集 error = 红 11 条**，`passed = 2187`（实测 `1 failed / 2187 passed / 6 skipped / 10 errors / 95.43s`，命令 = `cd backend && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest -q -rfEs --continue-on-collection-errors`）。唯一的断言级失败**不在本窗口**、也**不是环境问题**：`tests/redteam/test_redteam_guard.py::TestRedTeamFrozenSet` 四条 `RT-R07-00x` 期望 R07 实得 R06 = 我方 C3 那条归因失真在 W2C 自己冻结集里现形（RELAY §三 C5 已点名）。⇒ G-1 仍 FAIL，但**分类必须分开报**：1 条被测系统缺陷 vs 7 条本机缺 env vs 3 条 O6 权限。本窗口自己那格同时刷新为 **331 passed / 0 failed**（上一轮那 3 条按设计红的到期哨兵已反转成回归哨兵，见 §4.13）。

| 门禁 | 判定 | 读数 | 一句话原因 |
|---|---|---|---|
| G-1 全部 P0 通过 | **FAIL**（第四轮由 PASS 改口；第五轮红因**只剩窗外一条**；第六轮红因**一字未动**） | **断言失败 0 + 夹具 error 3 = 红 3 条**；unit+contract passed=**2254**，integration_ran=True（第六轮实测 `0 failed / 2254 passed / 6 skipped / 3 errors / 119.76s` @ `3ff31c4`（本轮 feat 提交；起点 = `82f5bdb`）） | ⚠️ **红因全在本窗口外，本窗口零回归**：第四轮那两条里的第 ① 条已消失 —— W4 落 `357618f` 把 U-119 接缝测试的**输入形状**改对（喂端口 `guard_allowlist`，反向对照保留），实测该文件 **2 passed**（RELAY P9 已闭）。剩下的 3 条 = `tests/integration/test_retrieval_fts_pg.py` 的 `test_dense_null_rows_never_crowd_out_valid_vectors` / `test_dense_all_null_column_raises_unavailable_not_type_error` / `test_dense_scope_with_zero_rows_is_not_degradation`，在**夹具阶段**抛 `InsufficientPrivilege: permission denied for database ecom` ⇒ 与 RELAY O5 那 6 条 skip 同源，只是这条路径没兜成 skip。**判据不变**：G-1 只看"套件绿"，不绿就是 FAIL，本窗口不替别人把红说成绿、也不把它算成自己的回归。**第五轮订正了自己两处取证缺陷**：① `measured` 原来写 `failed=4`（把 1 条断言失败与 3 条夹具 error 加成一个数），现按"断言失败 / 夹具 error"分开落（两者坏的东西不同、归属窗口也不同）；② 点名正则原来 ``FAILED\|ERROR`` 混收一个列表 ⇒ 现拆成 `failed_tests` / `error_tests`；另记一条坑：摘要里要点出 error 用例名，`-r` 必须带**大写 `E`**（我方 §8 原来写的 `-rfes` 根本点不出，报告只能给一个数）⇒ 已改。**第六轮起这一格自带"接触面"字段（见 §4.11）**：本轮 = 含集成层 `test_retrieval_fts_pg.py`；被拒的库 `ecom`；夹具 DDL 目标 `CREATE SCHEMA retrieval_dense_it` / `DROP TABLE retrieval_dense_it.embed_doc`（**全部限定在测试专用 schema**）；夹具 DSN = `RETRIEVAL_TEST_PG_DSN` 未设 ⇒ 回退 `deploy/.env` 的共享生产 DSN（角色 `app_rw`）⇒ 已作为 O7 提给 W0/W2B。**🔴 同日续轮（@ `d367287`）本行两句话被推翻**：「红因全在窗外」不再成立 —— 红 31 条 = 21 断言失败（W4 决策表 17、W2D 红队 1、**本窗 3**）+ 10 error（7 个集成包 import 期 fail = U-114 防线①缺 env、3 条仍是 O6），且「DDL 目标全部限定在测试专用 schema」是**过宽**（该字段只看得见日志打印的失败夹具 ⇒ 下界）⇒ 详见 §4.12 / §5.17–5.18 |
| G-2 结构 Easy × 语义低 ≥95% | FAIL | easy×low = 0/2 | 样本量 2 条，且**分母只有 2 是因为覆盖率**，不是能力 |
| G-3 危险 SQL 放行 = 0 | PARTIAL | 放行 **0** / 覆盖 48（应拦 50） | 未覆盖的 2 条是成本闸门用例（沙箱无 `EXPLAIN` ⇒ gate3 恒 SKIPPED） |
| G-4 跨租户泄露 = 0 | PARTIAL | 跨租户行 **0**；PG RLS 未在 DB 层验证 | 拦下发生在 SQL 层，与 PG 策略生效是两条路径（I-6）。⚠️ 本轮新事实：**策略本身已在 PG 实测有效**（见 §4.4），没接的是"应用链走不走 PG"这一半 |
| G-5 拒答 ≥95% / 误拒 ≤5% | FAIL | 该拒则拒 3/5 = 60.0%；误拒 4/12 = 33.3% | 5 条应拒答题里 2 条收口成 clarify；12 条可答题里 4 条被误澄清 |
| G-6 P95 ≤ 8s | UNVERIFIED | P95 = 7268ms，分母 = 口径未标注 = U-106 之前的回执 | 首轮是"没拿到回执"（NOT_AVAILABLE），本轮**读到 W7 真回执**了 ⇒ 降为 UNVERIFIED：回执自带 `g6_caveat`「本场景 0 条真正完成」⇒ 分母里一次成功都没有，不许判达标。口径变更的影响见 §4.6。**第五轮：判定格与输入路径一字未动**（W7 的 U-120 三态改的是 `g6_p95_le_8s` 那个布尔，而我方读端从不读它 ⇒ 已用参数化测试把这条依赖面钉死），但本轮逮到并修掉了读端自己的一个**假绿灯**，见 §4.10 |
| G-7 口径一致性 ≥95% 且差异 100% 可归因 | **FAIL** | 一致 **1/13 = 7.7%**；不可归因 **0** | **本窗口最重要的实测发现**，见 §4.1 |
| G-8 澄清率 ≤15% 且澄清后一次成功 ≥80% | UNVERIFIED | 澄清率 9/20 = 45.0%；后半句无分子 | `runner.py` 没有第二轮回路 ⇒ 拿评测器自己的缺口给被测系统定 FAIL 是错的，见 §5.2 |

> **第四轮（2026-09-21）起 PASS = 0**：G-1 从 PASS 落成 FAIL（W4 的 U-119 刻意红 + W2B 集成夹具 3 条 error，两条都在本窗口外，判据见 §3）。上一版这句是 **1 个 PASS 不等于"过了 1/8"**：G-1 只护"P0 测试全过"；其余 7 条里 3 条是实测未达标，2 条是"测了但成立条件不满足"，2 条是"只覆盖了一半"。本轮真打仍只有 20/166 条（成本裁定 D1），G-7 的 FAIL 指向**冻结集自身**的口径问题（W1A），不是模型能力。

---

## 4. 关键实测发现

### 4.1 G-7：§C.4.3 核心指标口径一致率 7.7%（1/13），12 条差异**全部可归因**

- 比对方法：权威侧 = 语义包 `metrics[].expression + default_predicates + time_basis` 在同一沙箱、同一租户边界（TEMP VIEW）上直接实现；被比侧 = 冻结集 `gold_sql`（`content_hash` 冻结）。
- 结果：`gmv` 最大相对误差 **5.58%**、`order_cnt` 5.37%、`aov` 0.46%、`refund_rate` 0.29%、`uv` 0%（唯一一致的那条属于 `uv`：它的默认谓词只有 `uv >= 0` —— 一个恒真的取值域约束而非口径筛选项 ⇒ 落在 `v_traffic_daily` 上的 gold 本来就没有"少写的谓词"可犯）。
- 归因：12 条差异逐条追到 `default_predicates`（`is_test_order = false` / `pay_status = 'paid'` / `refund_status <> 'refunded'`）—— **gold SQL 系统性少写默认谓词 ⇒ 数字偏大**。不可归因 0 条（§C.4.3 的另一半达标）。
  ⚠️ 但三条里**真正携带差值的只有 `is_test_order` 与 `refund_status`**（补齐步 12/12 与 10/10 非零）；`pay_status = 'paid'` 在 12/12 步差值为 **0** —— 根因实测在数据层：沙箱 `v_order_paid` 里 `pay_status <> 'paid'` 的 74,173 行 `pay_time` **全为 NULL**，任何 `pay_time >= '…'` 已隐含它。**但并非恒零**：无时间边界的题（"全时段 GMV"）该谓词筛掉 **74,173 行 / 1.05 亿**金额（全表跨租户：6.85 亿 → 5.80 亿，15.4%）。⇒ 已作为 RELAY B1 请口径侧写明适用条件，否则下一轮有人据此删掉这条谓词。
- 诚实边界：本项目**没有外部 BI 权威值可引**，所以 §C.4.3 的"已确认权威值"只能降级到"内部口径"这一层。报告里连着判定写这句，免得被读成"对过报表了"。
- 这条**不由 W6 修**：改 gold 会动 `content_hash`（W1A 冻结件），需要 W1A + 架构裁决（补谓词重冻结，还是宣布语义包口径权威）。已上呈 RELAY A1/A2 与 W1A-1。

### 4.2 执行层端到端 0 条拿到结果集

12 条 execute 用例里：产出非空 SQL 4 条，**真拿到结果集 0 条**（终态 clarify 9 / refuse 7 / error 3 / 无 1）。
⇒ 本轮 EX 度量的是"闸门之前 + 闸门本身"，**绝不等于**"执行 + 掩码 + 渲染链路正确"。报告 §8 有专门一条限制说这件事；EX=0/11 只能当覆盖率读数。

### 4.3 §17.2 回放决定论：同一批 20 条，live 与 replay 逐字段一致

- 真打：20 条 / 48 次 LLM 调用 / 92,642 tokens / **¥0.032804**（入库读数：`results_w6_live20.json` 快照 + `eval_metrics.json` 的 `meta.run_config.provenance`；逐次调用日志 `live_smoke20.log` 留本机，`*.log` 不入库）。
- 回放：同批、同沙箱、同闸门，**¥0**，中位墙钟 1.465s → 0.021s（≈70×）。
- 逐条 diff `(case_id, terminal_event, sql_text, equivalent)`：**20/20 完全一致**；唯一差异是 2 条**归因**（`security_leak` → `terminal_shape_gap`，即 §5.1 那次修正）。
- 结论（第四轮订正）：匣带**当时**足以承担"零成本复算归因/门禁"的职责 —— 但**今天已经不成立**：`probe_cassette_replay.py` 实测同一批 20 题重放 `w6_batch.jsonl` ⇒ **20/20 全 miss**（`tokens_total=0`）。成因实测在上游：W2A `fbae176` 把 `metrics()/aliases()` 枚举器接进语义摘要，首条 system 从 **6,401 → 11,343 字符**（新增整块 `## 指标口径`）⇒ 报文指纹全变。⇒ "自我修正不必再花一次钱"现在带日期：**要重出这批读数必须重录**（20 题 ≈ ¥0.033 / 全量 166 题 ≈ ¥0.27）。报告 §8 由该产物派生同一条 🔴 限制，§10 附复算命令。
- 成本外推（给决策用）：全量 166 条真打 ≈ **769k tokens / ¥0.27**。这条写在 runner 的计划输出里，跑批前先看计划是纪律一。

### 4.4 PG 侧事实订正（上一版的结论是错的）

上一轮我写"hostname `pg` 解析失败 ⇒ PG 侧全部 UNVERIFIED"——那是**只查了一条 DSN** 的结论。本轮实测：
`PostgreSQL 16.15`、alembic `0005`、24 表 + 8 视图、6 条 `p_<table>_tenant` RLS 策略且 6 张表 `FORCE ROW LEVEL SECURITY`、`app_ro` 可读视图；
**首轮那一刻业务事实表 0 行**，而 SQLite 沙箱有 **2,023,933** 行。
⇒ 结构/权限面已实测，RLS **有效性**与 PG 侧结果集等价**当时**不可测：0 行对 0 行必然相等，那种"通过"比不测更糟。
这条措辞现在只有一个真相来源：`reporter.pg_statement()`，三分支（未探测 / 不可达 / 可达但空表）都有测试钉住"不许多说"。

**2026-09-20 更新（同一函数自动改口的实证）**：W7 已把与沙箱同规模的数据灌进 PG，探针重跑读数：

| 事实 | 实测值 |
|---|---|
| `app` 六张租户域基表 | **2,024,017 行**（`order_paid` 494,249 / `traffic_daily` 1,500,556 / `order_refund` 23,116 / `product` 6,000 / `shop` 12 / `campaign` 84）|
| 与 SQLite 沙箱的对照 | §C.4.3 那五个事实关系求和 = **2,023,933 = 沙箱同数**（逐关系等量，见 `_probe_pg_real.json` 的 `parity.rows`）⇒ 两边算的是同一份数据 |
| RLS **策略本身**是否有效 | **有效**（`app_ro` + `set_config('app.tenant_id', …)` 逐租户可见数：`order_paid` 200,000 / 175,000 / 119,249，三租户**求和恰等于**属主看到的总数 ⇒ 不重不漏；`rls_partition_ok = true`）|
| 负对照 | ①零上下文（不设 GUC）⇒ `v_order_paid` **0 行**；②设一个不存在的租户 ⇒ **0 行**；③经视图引用 `tenant_id` ⇒ `permission denied`（deny 列生效）|
| 仍然没接的那一半 | G-4 保持 PARTIAL：以上证的是**DB 层策略**，而评测主链路走的是 SQLite TEMP VIEW；"应用运行时是否经 PG 执行"仍未测 ⇒ 见 §8 与 RELAY §十 |
| 并行 vs 串行（回应 W7 的 ④） | **已复现 + 成因已定位**（本轮订正：上一版这一格写的"没能复现"作废，成因见 §4.8 与 §5.7 / §5.8）。常驻判据从"`debug_parallel_query` off/on"换成"**四形态 × 真串行/真并行**"后实测：`v_order_paid` 在 `app.shop_ids` 只是 `RESET` 占位符那一格，串行恒 200,000、并行 100,385 / 97,282 / 103,929（`Workers Launched = 1`、`Worker 0: rows=0`）⇒ **静默少算约一半**；而显式 `set_config`（生产执行链的形状）与真值清单两格两路都精确 ⇒ 见 §4.8、RELAY P7 |
| ⚠️ 顺带发现的一个坑（已由 W7 复现并收窄） | `p_*_tenant` 里 `current_setting('app.shop_ids', true) = ''` 这一支在 **GUC 从未设过**时取 NULL ⇒ 整条策略恒 false ⇒ 静默 0 行。范围只有 `order_paid`/`product`/`shop` 三张基表（另三张是纯租户条件）；`RESET` 之后取到的是 `''`（= 不限店铺）而非 NULL；**生产路径不落在这一格**（`app/exec/executor.py:286-289` 在事务里连发三条 `set_config(..., true)`，`",".join(ctx.shop_ids)` 对"不限"天然给 `''`）⇒ 暴露面是装载脚本 / 评测适配器 / 自定义连接。首轮"业务事实表为空"的误判就是它造成的（§5.5），见 RELAY P6。**本轮再加一条边界**：`RESET` 留下的 `''` 占位符在 SQL 里读出来与显式 `''` **同值**，但在并行计划下**不是同一格**（少算约一半）⇒ "值相同"≠"行为相同"，见 §4.8 |

### 4.5 I-2 结构标签：全量 166 条**零漂移**（本轮唯一一条"不变量已被机器验证"的正面读数）

- `eval/grid.py:75 recompute_struct_labels()` 用 `data/generator/layering.py`（I-1/I-2 的唯一分层实现，本窗口只读复用）对**整份冻结集**重算 `difficulty_struct` 并与冻结标签逐条比对：**漂移 0 条 / 166**。
- 不是"跑了一次没报错"：`test_recompute_agrees_with_frozen_labels_on_real_dataset` 钉住零漂移，`test_recompute_detects_a_planted_drift` 是**正对照**（故意改掉一条标签，复算必须抓出来）⇒ 前者不会因扫描器自身失效而假绿。
- 为什么值得单列：报告 §2 的 4×3 网格**行轴**就是结构档。这条成立 ⇒ "网格行轴 = 上游代码口径"不再是一句声明；哪天 `layering.py` 改了而冻结集没重做，这条测试先红，G-2/G-5 的读数就不会静默换口径（N-13 前兆）。
- 反面仍然成立：**语义档**轴（`difficulty_semantic`）本轮**没有**独立复算路径 ⇒ I-3 只能靠 W1A 重标（RELAY W1A-5），本窗口只在报告 §8 披露，不就地改冻结集。

### 4.6 G-6 接 W7 的 U-106 口径变更（P95 的分母换人了）

- W7 把 `latency_ms.p95` 改成**只在准入（HTTP 2xx）样本上算**，429 剔出分母、单列 `admission`，并**刻意不升 schema 版本号**（升了就打断本窗口的逐字比对）。
- 本窗口的处置（三条都有测试钉）：① **不动那两行** —— schema 串仍逐字比对、**不加未知键校验**（`test_loadtest_pressure_ignores_unknown_keys_and_still_matches_schema_verbatim`，含"版本号变成 /2 必须读不出来"的反面对照）；② 新字段如实搬出来（`p95_scope` / `admission` / `latency_ms_all_ms`，`test_loadtest_pressure_transports_the_u106_scope_fields`）；③ **判定值改为优先取全请求分位数**，只有准入口径时**不得判 PASS**（`test_g6_admitted_only_scope_cannot_borrow_a_pass`、`test_g6_judges_on_the_all_request_percentile_not_the_admitted_one`：准入 5.2s 达标 + 全请求 12s ⇒ FAIL，这是防假绿的关键一条）。
- 跨窗口声明**不照抄**：W7 说"十份历史回执全 UNVERIFIED"，本窗口自己跑了 —— `backend/reports/w6/probe_loadtest_receipts.py` 把 `deploy/loadtest/receipt*.json` **10 份**逐个过真读端 + 真 gates ⇒ `{'UNVERIFIED': 10}`、`any_pass = false`，与 W7 的声明一致（读端改动后复算仍是同一结果）。
- 上呈 A10：§17.3 的 G-6 **没写分母含不含被限流的请求**，这不是实现细节能推出来的 ⇒ 本窗口不替架构把这个字填上，只把口径写在读数里。
- ⚠️ 一个被我写进判定顺序、但**方向其实未证**的假设：W7 复算指出被拒请求回来极快（3 个 401 合计 8.3ms）⇒ 计入分位数会**拉低** p95，"取全请求"只是 population 与规格原文一致，**不等于更保守**；净符号要看当天哪一类非 2xx 占多数，而这要一次真跑批才有数（十份历史回执没存逐样本延迟）。⇒ 该假设已连证据一起写进 RELAY A10 交给架构，本窗口不拿"更严"当理由自证。

### 4.7 一处"契约换形状"把我的测试打红，复测后又逮到生产侧的 0.2s（`bind` / L4）

把 `main` 拉到本地（现 `76e4e5d`）后 `backend/tests/eval` 有 1 条红：`test_eval_timeouts_keep_contract_values_but_floor_llm_nodes` 抛 `KeyError: 'gen_sql'`。查下来不是 W4 改坏，而是**契约换了两次形状**：

- **U-104** 把 5 个 LLM 节点从 `NODE_TIMEOUT_S` 移了出去；**U-107**（`d387347`）进一步把"预算当硬超时"这个病害整体改掉 —— LLM 节点的硬超时**不再写死**，执行期经 `_LLM_NODE_TASKS` → `resolve_route` → `hard_timeout_s` 解析为客户端超时。
- 只读跑 `_effective_limit_for(name, None)` 实测（当前 HEAD）：`normalize` `intent` `plan` `gen_sql` `present` `repair` **六项全部 15.0s**（flash 档），`link`/`execute` 各 30.0s，闸门三兄弟 0.1s ⇒ 我方 RELAY **G1 关闭**（那条"契约 2.0s 容不下一次真出站"已被 W4 按正解修掉），报告与本窗口注释里 `normalize` 2.0s 的旧例子同步作废。
- 我的 `eval_node_timeouts()` 只遍历契约表 ⇒ `gen_sql`/`intent`/`plan`/`normalize`/`repair` **拿不到评测下界** —— 也就是"一次真 LLM 出站把整批判成链路故障"这个老问题会换个方式复发，而且不报错。
- 修法：遍历 `契约表 ∪ LLM 清单`；`describe_node_timeouts()` 新增 `not_in_contract` 显式列出"哪些节点名已不在契约表里"（隐身名单不许隐身）；两条守卫测试 —— `test_timeouts_survive_contract_slimming`（契约再瘦身也不许让下界消失）、`test_outbound_budget_nodes_are_not_double_amplified`（不放大清单 = `{execute, link}`，且非 LLM 节点不许被放大越过 LLM 档）。
- ⚠️ 同一次探测顺手发现的**第二个 U-107 副作用**：`link` 的契约值被抬到 30s（= `EMBEDDING_TIMEOUT_SECONDS`，为了不被节点超时先掐掉 embedding 自己的报错）。我原来的"非 LLM 节点 ×8"系数是冲"0.1s 闸门在慢机上假阳性"设计的 ⇒ 套到 30s 上就是 **240s**，而评测用的是本地夹具检索（`BundleCatalogRetrieval`，§17.4 明文不测向量检索），永远逼近不了 30s ⇒ **放大的是墙钟不是被测事实**。已把 `link` 移进"不放大"清单，并逐节点写下理由。
- ★ **仍然没解的生产侧缺口**（RELAY G3）：`bind` 触达 `deps.llm`（`nodes/bind.py:180` 走 L4 精排）却不在 `_LLM_NODE_TASKS` 里 ⇒ `_effective_limit_for("bind") = **0.2s**`。评测侧因为我给 LLM 节点兜了下界，**这条在批次里完全看不出来** —— 是"评测比生产宽松"的存量一处，不是可以拿来给自己加分的通过。
- ⚠️ 方向要说全：**两份清单双向都不一致** —— `present` 在对方清单里，但 `nodes/present.py` 对 `llm` 零命中（清单比代码宽，对我方无害）。⇒ 本窗口的判据固定为"代码是否触达 `deps.llm`"，**不照抄任何一侧清单**（含自家注释）。
- ⚠️ 顺带发现产物里的**陈旧快照**：`meta.run_config.node_timeouts.contract` 是 runner **跑批当时**落盘的（09-18 那批 = 15 个节点、`normalize` 2.0s、`link` 4.0s），而报告 §0 同一页写着本次生成时的 commit ⇒ 读者会拿一张已经不存在的表去引用 §5.3 契约。修法不是重跑批次（要花钱），而是让报告器**读当时、比当前**：新增 `reporter.timeout_snapshot_drift()`，不一致就在 §0 点名（实测输出"已移出契约表：`gen_sql`、`intent`、`normalize`、`plan`、`present`、`repair`；值变了：`link` 4.0s→30.0s"），并加 `test_timeout_snapshot_drift_names_the_shape_change`。
- 实测：`pytest backend/tests/eval -q` → **306 passed**（本轮新增守卫见 §1）。

### 4.8 ★ PG 并行下的**静默少算**已复现（W7 的 ④）：成因已定位 = 占位符 GUC 不随 worker 传值

上一版我写"8 组全绿 ⇒ 未能复现"。那条结论**错了两次**：轴选错（`debug_parallel_query` 在本机 PG 16.15 只接受 `off/on/regress`，而 **off 下计划里照样有 Gather** ⇒ 我根本没有串行对照组），形态也只剩一种（两把 GUC 都显式设值）。换成"四形态 × 真串行/真并行"后（`_probe_pg_real.py` + `_probe_parallel_states.py`，全程只读）：

| 项 | 实测（T_A / `app.v_order_paid`；串行 = `max_parallel_workers_per_gather=0`，并行 = 2 + `regress`） |
|---|---|
| 复现形状 | `app.shop_ids` 只被 `RESET` 过（键本会话从未设过 ⇒ 留下值为 `''` 的占位符）⇒ 并行 **100,385 / 97,282 / 103,929**，串行恒 **200,000**；`Workers Launched = 1`，扫描节点 `Worker 0: actual ... rows=0` + `Rows Removed by Filter` 覆盖 worker 整片份额 |
| 等值的形状 | 显式 `set_config('app.shop_ids','')`（生产执行链形状）两路恒 200,000；显式真值清单（`T_A-S04`）两路恒 40,162；`v_traffic_daily`（策略**不含** shop 条款）四形态两路全等 ⇒ **只有"策略的 Filter 去读那个占位符键"这一格会掉数** |
| 排除掉的 / 定位到的 | ① 不是 plan 缓存：入库产物跑的是 `prepare_threshold=default(5)/1` × `plan_cache_mode=auto/force_custom_plan/force_generic_plan` 六种组合，**全部照样少算**（并行读数 91,804 – 114,867）；② 不是 index-only 节点特有：`enable_indexonlyscan=off` / `enable_indexscan=off` / `enable_parallel_append=off` 三组下仍少算（50,284 – 106,764）；③ ★ **成因已定位**（前一条草稿在这里写错了，见 §5.8）：我方上一版用 `select coalesce(current_setting(...)) as v from 视图 group by v` 投影 GUC —— 表达式**没有列引用** ⇒ planner 把它提到 `Gather` 之上、只由 leader 算一次 ⇒ 产出"worker 也看到 `''`"的**提升性伪影**。换成带列引用的形状（`case when t.tenant_id is not null then coalesce(current_setting('app.shop_ids',true),'<NULL-in-this-process>') …`，基表 `traffic_daily`，`app_rw`）后：同一条查询 `Workers Launched = 2`，**leader 格 `''` = 194,377 行、worker 格 `<NULL-in-this-process>` = 405,801 行，两格相加恒 = 600,178** ⇒ 少算的成因就是**`RESET` 留下的占位符 GUC 不随并行 worker 传值**（worker 读到 NULL ⇒ 策略两支都不成立 ⇒ worker 整片被 `Filter` 掉）|
| 两条角色路径 | `app_ro` 直接登录 与 "postgres 登录 + 每条连接内 `SET ROLE app_rw`" 读数一致 ⇒ 回掉 W7 的 ②（他们只测了后者）。⚠️ 顺带一条实验纪律：**`SET ROLE` 不跨连接继承**，我第一版把它设在外层连接上、而每条状态又新建连接 ⇒ 等于什么都没设（且 superuser 绕过 RLS，那样读出来的"正确"是假的）|
| 生产暴露面 | **不受影响**：`app/exec/executor.py` 在事务内用 `set_config(..., true)`（`IDENTITY_INJECTION_TEMPLATE`）⇒ 实测事务内并行 4/4 精确。但**同一把连接提交后再复用** ⇒ 实测恒 **0 行**：两把键的事务级值随提交消失、`current_setting` 只剩 `''`（入库产物 `production_shapes["③…"]` 的 `guc_left = {'app.tenant_id': '', 'app.shop_ids': ''}`）⇒ `tenant_id = ''` 谁也匹配不上（fail-closed，不是半值）⇒ 直接进 RELAY §十-6b①：接 PG 的评测适配器必须**每批都在事务内设两把 GUC**，且不许把 0 行读成"模型没查到" |
| 对 W7 的 P1（`'*'` 哨兵）的实测含义 | 当前策略文本是 `= '' OR shop_id = ANY(string_to_array(v, ','))` ⇒ 设成 `'*'` 时**读 0 行**（串行并行都是）⇒ 换哨兵必须**连策略一起改**，否则"不限店铺"会静默变成"什么都查不到"（安全上 fail-closed，语义上是另一种错）|

**这条为什么值得单列**：它不是评测器的 bug，也不是模型能力问题，而是"同一条 SQL 在并行开/关下给出不同的数、且不报错"。N-07 抓不到（策略照样生效，只是分量没了），门禁也不会顺路逮到 ⇒ 任何把评测执行链切到 PG 的方案（§8-5）都会把它引进分母。本窗口的处置：判据常驻（`parallel_equality_ok = false` 已如实落进产物）、措辞按形态点名（缺口表与报告 §0/§7 同一状态）、复现形状与成因都已入库；**修法不归本窗口**（PG 配置 / 策略文本，等 A11 裁决）。

⚠️ **两件事不要并案**（W7 提供的新事实，我方核对后各自独立）：
1. 他们 13 份 G-6 回执里 `outcomes=ok` 从未出现，根因是 `app.embed_doc` 无 embedding / 无 `tsv` ⇒ 那是**被测系统侧**的另一条失效，与本条"PG 并行下读数变小"没有因果关 —— 我方 G-6 停在 UNVERIFIED 是前者 + `g6_caveat`，不是后者。
2. 他们说 `app.cost_ledger` 被清空（现 6 行，09-20 14:00 起），09-19 报的 82 行 / ¥0.064258 不可复核 ⇒ 累计成本基线重开。我方核对结论分两层，别混着引用：**代码侧零依赖**（`grep -rin cost_ledger eval/ backend/tests/eval/` → **0 命中**，成本读数走 `eval/harness.py:646 cost_cny()` → `runner.py:503 cost_cny_total` → `reporter.py:597`，实测 `eval/results_v1.json` 的 `summary = 92,642 tokens / ¥0.032804`，逐条派生自批次自身与匣带）⇒ **门禁读数不受影响，无需重取**；⚠️ 但**产物侧并非零出现**：本窗口的 `_probe_pg_real.json` 顺带拍到这张表三处（`pg.pg_row_counts.cost_ledger = 3`、`parity.relations[4].pg = 3`、`pg.rls_flags[4]` 的 `row_security/force = false`）⇒ 重跑探针这几个数会变成他们报的那一档，那几个数**不进任何判定**，只作"PG 里存在哪些对象"的清单证据。上一版这句写成"`eval/` 与 `reports/w6/` 对它零引用"，**过宽了**（产物里就有），本轮按实测改口。

---

### 4.9 ★ U-119 判据③ + U-121 收尾：探针跑到底、适配层从"造面"降成"选面"、匣带失效第一次有了读数

总控这一轮给的三件事，逐条落成品（全部实测，命令在报告 §10）：

| 项 | 读数 |
|---|---|
| 探针崩因（U-119 判据③） | 旧版第二步 `AttributeError: 'tuple' object has no attribute 'keys'` @ `ast_gate.py:751` —— 我方自拼 wrapper 时把**扁平面**的 `columns`（列名元组）当类型字典用。⚠️ 架构的原话成立：**有诊断没结论 = 没有诊断**（docstring 09-20 就写下了这件事，结论从未产出） |
| 三种形状 × gate1（同一个真运行时） | 扁平面（生产今天的接线）→ **两条 SQL 都 R05 拒**；旧自拼件 → **崩**；端口 `guard_allowlist`（U-121，W2A `b7e6c8d`）→ **两条都 passed**，并注入三条 `default_predicates` |
| 两种形状 × gate2 | 真运行时 → **G2-ASSET 拒**；把 `asset_allowlist` 换成端口输出的代理 → **`ContractViolationError`：语义包 tenant_scoped 与 tenant_id 列不一致** ⇒ 🔴 **gate2 缺的不止一行**：`policy_gate.py:105` 要改调 `guard_allowlist`，且 ⑤ 在 `:148` 用**可见面**判「`tenant_id` in columns」而 `tenant_id` 恰是 deny 列 ⇒ ④⑤ 必须改读 `all_columns`（归 W2C） |
| 「两面不能整包换」的反证 | `SELECT receiver_phone FROM v_order_paid`：可见面 → **R06 拒**；整包换结构面（deny 清单还在）→ **R07 拒**；结构面 + 漏送 `deny_columns` → **passed=True，改写后的 SQL 里真的带着 `receiver_phone`** ⇒ 敏感列出库的形态第一次被我方量出来（不是引文档） |
| 适配层收尾 | `eval/harness.py` 的 `build_guard_allowlist()`（手拼七键 + 补列类型 + 截 joins）**整体删除** ⇒ 现在两面都取自端口；`redteam_eval.structural_wrapper()` 从"造面"降成"**选面**"（只把 `columns` 换成端口的 `all_columns`，顶层键集合与端口逐键相等）。⚠️ **不能全删**：生产消费侧还没接线（`contracts.py:423` 点名的正是我这三个符号），今天删了评测就直连一条断缝 ⇒ 改成**到期哨兵** `test_the_dual_shape_view_dies_with_the_consumer_fix`：AST 扫 `policy_gate.py` / `gate1_ast.py` 实际调的方法名，哪天两边都改调 `guard_allowlist`，这条测试立刻红并点名要删的四处 |
| 切换的安全性（两条对照） | ① 红队产物 `redteam_results.json` 切换前后**逐字节相同**；② 出站报文的**认证资产段逐字相同**（2,277 字符 / 76 行，旧录制 vs 今天出站）⇒ "端口形状 ≡ 我方旧派生"在评测路径上成立，G-3/G-4 读数没有因为这次切换漂移 |
| 顺带抓到的新事实 | 匣带 `w6_batch.jsonl`（48 个报文指纹）对今天的出站报文 **20/20 全 miss** —— 上游 `fbae176` 把指标口径枚举器接进语义摘要（system 6,401→11,343 字符）⇒ §C.6.1 纪律二"零成本复算"今天失真，已改口并落成 `probe_cassette_replay.py` + `cassette_replay_probe.json`（详见 §4.3、§6） |
| 给 W4 的一条复核 | 他们的接缝契约把**扁平面**原样喂 `run_gate1` 并要求 pass ⇒ 按 U-121 的正解（消费方改调 `guard_allowlist`）修完之后**这条仍会红**，绿条件只剩"给扁平面补 wrapper 键"这一条**被 07 明令禁止**的路。判据①的输入应是端口形状，或由 W4 显式声明"红的是消费侧未接线、不是形状本身"（实测读数在 `probe_gate_allowlist_shape.json`，本窗口不改别人文件） |

---

### 4.10 ★ 第五轮（2026-09-22 跨零点）：一次"礼仪性知会"复算出三件事，其中一件是我方自己的假绿灯

W7 发来 U-120 的三态改动知会（`admitted<20` 或 p95 无值 ⇒ `g6_p95_le_8s = null`），并声明"我方读端不会红"。**跨窗口声明不照抄** ⇒ 三条都自己复算，结果第 1、2 条成立、第 3 条不成立（W7 没提到，是我方扩大扫描面后自己逮的）：

| 项 | 实测读数 |
|---|---|
| ① 复算"你不会红" | ✅ 成立：`git grep g6_p95_le_8s` 全仓**唯一写点** = `deploy/loadtest/driver.py:411`，**零读点**；我方 G-6 只取 `latency_ms.p95` / `p95_scope` / `admission` / `latency_ms_all_ms` / `g6_caveat`。已把它升级为判据：`test_the_reader_never_depends_on_w7s_g6_boolean`（该字段取 `true`/`false`/`null` 三值时读端产物必须逐字相同）⇒ 将来谁想让 G-6 去读那个布尔，先撞红 |
| ② 复算"14 个 stale `true` 格" | 总数对（`stale_true_cells_total = 14`），分解订正：分布在 **11 个文件**（`baseline_c5.json` 1 + `receipt.json` 4 + 其余 **9** 份各 1；W7 写"其余 8 份"漏了一项）。⚠️ 更关键的一条是 W7 侧看不到的：**这 11 份全部没有 `admission` 字段** ⇒ 三态是写端**未来**的行为，回改不动历史格 ⇒ "别引用"在评测侧只能靠读端兜 |
| ③ 🔴 我方读端的假绿灯（本轮最有价值的产出） | `baseline_c5.json` 是 13 份里**唯一** `g6_caveat == null` 的那一份（p95 = 3675.8ms、无 `admission`、无 `latency_ms_all_ms`）⇒ 喂**真读端 + 真 gates** 得到 **G-6 = PASS**。也就是 W7 自家 `driver.py` 文档里那句"旧文件的 null 会让 G-6 假绿"的形状，09-19 修过一次、09-21 又从这个文件上活着回来，而 U-120 的三态**救不了它**（读端不读那个布尔）。**修法**：`gates.py` 新增降档 —— caveat 为 null 但既无 `admission` 又无全请求分位数 ⇒ 至多 UNVERIFIED（超预算照判 FAIL，降档不许洗白） |
| 对照（改前 / 改后，同一条命令） | 改前：`13 份 → {'PASS': 1, 'UNVERIFIED': 10, 'FAIL': 2}`，PASS 那格 = `baseline_c5.json`；改后：**`{'UNVERIFIED': 11, 'FAIL': 2}`、`any_pass = false`**。门禁表**零漂移**（`counts` 一字未动，G-6 输入路径仍是 `receipt.json` ⇒ 一直 UNVERIFIED） |
| 为什么上一轮没发现（记进 §5.11） | 我方复算 W7"十份全 UNVERIFIED"时**把他们的 glob 一起继承了**（`receipt*.json`）⇒ 判定自己跑，覆盖面却抄了别人的边界，而盲区里正好躺着唯一会判绿的那份 |
| ④ 适配层"到期一半"（W4 `357618f` 的连带后果） | `gate1_ast.py:56` 已改调 `guard_allowlist`，只剩 `policy_gate.py:105` 读扁平面 ⇒ 我方**并集式哨兵既不红也不报**，`harness.py` 那句"消费方还在读 `asset_allowlist`（点名两个文件）"当场失真一半。机制已换成两层：哨兵**按文件**判（逐文件读数写进消息）+ `test_the_adapters_stated_reason_list_matches_the_code` 双向核对 `harness.py` §三 那行机器可读清单（点名了已接线的 ⇒ 红；接线了没进清单 ⇒ 也红）。**默认方案**：gate1 那半边视图今天就能删，但与 gate2 半边同类、改动面 10 处 ⇒ 默认等 P8 一次删净，代价与提前做的选项写进 RELAY §十-10② |
| ⑤ ★ **契约闭环**：W7 接受"每份回执都带 `admission` + `latency_ms_all_ms`"（`driver.py:393/399` 今天确实无条件写）⇒ 我方把这条做成**会响的正向对照** | 新测试 `test_todays_w7_driver_shape_can_still_reach_a_pass` **不手写夹具**：按文件路径加载 `deploy/loadtest/driver.py`、调 `_summarize(...)` 现场生成今天的形状（25 条全准入、零降级、p95 远低于 8s），再喂真读端 + 真 gates ⇒ 实测 **G-6 = PASS**、判定值取全请求分位数。他们删掉那两个键之一，这条当场红，而不是让 G-6 悄悄退化成"永远 UNVERIFIED"；它同时防我方自伤（上一条降档若写宽了，真·干净回执也会被压住 —— 只有正向对照逮得到）。⚠️ 一条加载踩坑（症状长得像**对方的件坏了**）：按路径 import 一个含 `@dataclass(slots=True)` 的模块**必须先登记 `sys.modules` 再 exec** —— `dataclasses` 在建类时查 `sys.modules[cls.__module__]`，不登记就抛 `AttributeError: 'NoneType' object has no attribute '__dict__'`；我方第一版就是这么红的，与 `driver.py` 无关 |

> **订正 §4.9 表里的一个时点**：那行"扁平面（生产今天的接线）"成立于 09-21 那次探针运行；`357618f` 之后 gate1 侧的生产接线已是**端口形状**，扁平面只剩 `policy_gate`（gate2）一处在用。探针本身不受影响（它直接喂形状给 `run_gate1`，实测产物逐字节未变）。

### 4.11 ★ 第六轮（2026-09-22 日间）：W7 的两件事落成**机器口径**，接线过程当场逮到自己两个取证 bug

W7 提了两件：① 报"全量"读数时点名是否含 integration、夹具 DSN 指向哪，并问能否在评测侧加一条"会响的守卫（拒连共享 `ecom`）"；② 别摘掉那条按文件扫生产调用口的 AST 守卫。两条都落成了代码，不是落成纪律（纪律会腐，判据不会）：

| 项 | 实测读数 / 落点 |
|---|---|
| ① 接触面 = 读数的固定字段 | `eval/reporter.py::pg_surface()` 从 pytest 日志取证（集成层文件名 / 被拒的库 / 夹具下发过的 DDL 形状 / 连接参数），挂进 `parse_pytest_summary()["pg_surface"]` ⇒ `gates._pg_surface_notes()` 把它写进 **G-1 格的 caveats**，**红不红都声明**（`eval_metrics.json` 与报告表格同源）。本轮读数（HEAD `3ff31c4`，`cd backend && PYTHONUTF8=1 pytest -q -rfEs`，119.76s）：**含 integration**（`tests/integration/test_retrieval_fts_pg.py`）、**被拒的库** `ecom`、**DDL 形状** `CREATE SCHEMA retrieval_dense_it` / `DROP TABLE retrieval_dense_it.embed_doc` / `CREATE TABLE r (截断)`（pytest 把过长 query 截断，"截断"这件事本身被点名而不是被当成噪声）。**夹具 DSN 指向哪**：`test_retrieval_fts_pg.py:69` = `RETRIEVAL_TEST_PG_DSN or PROD_DSN`，环境变量未设 ⇒ 回退 `deploy/.env` 生产 DSN（`_dsn_from_env_file()` 把 `@pg:` 改写成 `@127.0.0.1:`，角色按该文件 54 行注释 = `app_rw`）⇒ **默认就往共享 `ecom` 上试 DDL**，已作为 O7 提给 W0/W2B。<br>🔴 **本行两处已被同日 §4.12 订正**：「DDL 目标全部限定在 `retrieval_dense_it`」是**过宽**结论（`pg_surface` 只看得见日志打印出来的失败夹具 ⇒ 下界，见 §5.18）；「前/后各测一次 `app.embed_doc` = 197|197 ⇒ 我方这轮没改那张表」**判据不成立**（计数对重载不敏感，见 §5.17） |
| ② 会响的守卫（做不到的那半句先说清） | **"拒连共享 `ecom`"我方做不到**：PG 侧证据（G-4 的 RLS 有效性、并行少算）只存在共享实例上，拒连 = 把 G-4 退回 UNVERIFIED。做到的是**每条会话都不许有写能力、且被服务端拒过一次**：新建 `eval/pg_guard.py` —— `force_readonly()` 把 `default_transaction_read_only` 编进 DSN（⚠️ 值里的 `=` 必须编码成 `%3D`，否则 libpq 抛 `extra key/value separator`），`open_readonly()` 连上后 `SET` → `SHOW` 复核 → **故意下发一次 `CREATE TABLE` 并期望被拒**，没过闸门**探针不出产物**。已接 `_probe_pg_real.py`、`_probe_parallel_states.py`（两者本轮实测退出码 0，产物各多一个 `pg_guard` 键：`{"database":"ecom","role":"postgres\|app_ro","read_only_enforced":true,"write_attempt_rejected":true,"dsn_redacted":"…@localhost:5432/ecom"}`） |
| ②b 接线时先做前后对照（因为那是 U-110 的证据件） | `_probe_parallel_states.py` 改前 / 改后各跑一次：**判据字段**（`measurable` / `parallel_ran` / `equal`）10 格逐格相同、**串行 counts** 相同（`200000` / `40162` / `0`）、`workers_launched` 相同、三条生产形状 counts 相同、worker 侧两格合计 **600,178 → 600,178**；只有并行 counts 本身逐轮变（那正是被测量本身的性质）⇒ **闸门对读数中性**，改动没污染证据 |
| ③ 🔴 自己写的取证代码里两个 bug（新增测试直接抓到） | ⓐ `_PG_DDL_RE` 以 `\b` 起头 ⇒ 在**我顺手写的干净文本**上绿、在**真日志**上恒返空（pytest 把 SQL 以 **repr** 打印，`\n` 是两个字符 ⇒ `n` 与 `C` 之间没有词边界）。"DDL 形状 = 无"差一点被我当事实报出去 —— 发现方式是跑完真日志发现该格为空，再拿同一份日志做单变量对照（带 `\b` = `[]`，去掉 = 3 条）。ⓑ 共享 schema 判据用 `split(" ", 1)` 切对象名 ⇒ 两词动词（`DROP TABLE public.foo`）永不命中、带 `CASCADE` 的会误命中 ⇒ 换成"跳过动词/`IF EXISTS` 词表、取第一个剩下的词"。ⓒ 顺带订正一条**假引用**：`pg_surface` 的 docstring 写着"由 `_redact` 兜底脱敏"，而 `_redact` **根本不存在** ⇒ 已补实现并让四个出口都过它（"凭据不落盘"从此由代码成立，而不是由"我的正则取不到"成立） |
| ④ 那条 AST 守卫：不摘，且现状已是 W7 要求的形状 | `tests/eval/test_harness_allowlist.py` 的 `_port_methods_called_by_gates()` 返回**按文件**的调用集合，`test_the_dual_shape_view_dies_with_the_consumer_fix` 只在"**仍读扁平面的文件非空**"时红 ⇒ W2C 把 `policy_gate.py:105` 也接到 `guard_allowlist` 的当天它**转绿**（不是失效、也不会被摘），届时连同 `AssetAllowlistView` / `GuardAllowlistBundle` / `StructuralAllowlistBundle` / `structural_wrapper` 整体删除（§8-11） |
| 本轮读数一览 | `pytest tests/eval -q` → **334 passed / 15.56s**（+16）；全量 → **0 failed / 2254 passed / 6 skipped / 3 errors / 119.76s @ `3ff31c4`（本轮 feat 提交；起点 = `82f5bdb`）**（红因仍 = O6 那 3 条窗外夹具 error）；`ruff check .` 通过、`lint-imports` **4 kept / 0 broken**；`eval/reporter.py --no-backup` 退出码 1 ⇒ **PASS 0 / FAIL 4 / PARTIAL 2 / UNVERIFIED 2 = 连续两轮零判定漂移**；匣带复算探针仍 **20/20 miss**（`n_scored = 0`）⇒ §8-2"今天不可复算"继续成立 |

### 4.12 🔴 第六轮·续（同日 16:00–16:40）：W7 的新证据证伪了我方两句结论，并把"跑全量"这件事本身打停

W7 追加证据：14:26 之后仍有一次运行同时留下 `embed_doc` 全表重载与 `cost_ledger` 的 TRUNCATE 签名（`ins=24 / del=0 / count=0`），而"那台夹具的 DSN 默认回退"正是我方 O7 报出去的那条。核对下来三件事都成立，其中两件是**我方自己的问题**：

| 项 | 实测 / 订正 |
|---|---|
| ① 我方上一轮那句"我这轮没改 embed_doc"**判据不成立** | 我用的是 `count(*)` 与 `count(embed_doc)` 前后相等（197\|197 → 197\|197）⇒ 但一次破坏性重载（TRUNCATE + 重灌，或无派生器的 materialize）**之后可以是同一个数**。计数对"重载"不敏感 ⇒ 这句结论作废（§5.17）。对重载敏感的签名 = `pg_class.relfilenode`（TRUNCATE 换存储文件）+ `n_tup_ins` 涨而 `n_tup_del` 不涨（本机 **PG 16.15 没有 `truncates` 也没有 `stats_reset` 列**，第一版照抄新版本列名直接抛 `UndefinedColumn`，已按 `pg_attribute` 实测改） |
| ② 我方 §4.11① 那句"夹具 DDL 目标**全部**限定在 `retrieval_dense_it`"**过宽** | `pg_surface` 是**从日志文本取证**，而 `pytest -q` 只打印失败/报错的夹具 SQL ⇒ **通过的夹具一行都不留**。证据：16:25 那次（防线①之后，零测试执行）与 14:53 那次（防线①之前，很可能 truncate 过 `app.cost_ledger`）在 `ddl_targets` 上**输出同一串三行** ⇒ 该字段区分不了这两个世界 ⇒ 它是接触面的**下界**，不是全集（§5.18）。已在措辞里补下界句，并把"跑前/跑后签名"作为上界补件 |
| ③ 新器件：`backend/reports/w6/probe_pg_boundary.py`（168 行，只读，走同一把 `pg_guard` 闸门） | 用法 = 跑前 `--label A`、跑后 `--label B --diff-with A`；产物 `pg_boundary.json` 逐表逐字段存快照与差值。**本轮两组实测**：ⓐ `16:25:19Z+8 → 16:25:24Z+8`（`pytest -q -rfEs`，被 7 条**收集 error** 打断、**零条测试执行**）⇒ 差值 `[]`；ⓑ `16:3x → 16:3x`（同一条命令加 `--continue-on-collection-errors`，**128.37s 全量真跑**）⇒ 差值仍是 `[]`（`relfilenode` 与四张表所有计数逐字段等）。⚠️ 边界：差值 = 0 只证明"**现在**这条命令不写共享库"（因为 U-114 防线①让集成包 import 期就抛、根本拨不出去），**不能**反推 14:53 那次；那只能靠时间线（见 ④） |
| ④ 我方是 W7 那个窗口的**候选来源**，我不否认 | 本机时间线（+0800）：W6 第一次全量 **14:22:45 → 14:24:46**（`2252`），第二次 **14:53:47 → 14:55:46**（`2254`，基线 = `82f5bdb`，**早于** W0 `36c782a` 防线②与 W2A `5e47558` 防线①）⇒ 第二次**整段落在 W7 取证的 14:26–15:06 里**；且当时本机四个 env（`COMMERCEQL_TEST_{RW,RO,SUPER}_DSN` / `RETRIEVAL_TEST_PG_DSN`）**全部未设**（本轮实测均为空）⇒ 走的正是 O7 那条字面/回退 DSN。⚠️ 我方**不据此下因果结论**：`relfilenode` 在两次快照之间没有历史值，14:53 那次的日志文件也已被本轮覆盖（§5.19）⇒ 只能说"W6 的跑具备产生该签名的全部条件"，归因请 W7 用 PG 侧事件时间戳对齐 |
| ⑤ "跑全量"这件事本身在新 HEAD 上被打停 | `cd backend && pytest -q -rfEs` @ `d367287` → **`Interrupted: 7 errors during collection`、退出码 2、一条都没跑**（`tests/integration/*` 在 import 期 `env_dsn()` 抛 `RuntimeError: 环境变量 … 未设置`）⇒ G-1 **取不到数**。我方**没有**用"窄化收集范围"绕过去（缩门禁 = 假绿同族），改用 `--continue-on-collection-errors` 保住同一范围 ⇒ 本轮新读数 **21 failed / 2164 passed / 6 skipped / 10 errors / 128.37s @ `d367287`**，判定 `PASS 0 / FAIL 4 / PARTIAL 2 / UNVERIFIED 2`（连续三轮零判定漂移）。这条命令形状已写进报告 §10 |
| ⑥ 🔴 本轮 G-1 新增**窗内**红因 3 条 = 我方到期哨兵按设计响了 | `tests/eval/test_harness_allowlist.py` 的 `test_the_dual_shape_view_dies_with_the_consumer_fix` / `test_the_adapters_stated_reason_list_matches_the_code` / `test_gate2_bidirectional_tenant_assertion_raises_on_production_visible_shape` 三条红，逐文件读数 = `{'app/guard/policy_gate.py': ['guard_allowlist'], 'app/graph/nodes/gate1_ast.py': ['guard_allowlist']}` ⇒ **W2C 已把 gate2 也接到端口**（RELAY P8 两件事都做完了）⇒ §十-10② 那"到期一半"如今**整体到期**。处理：不删断言、不改 skip，按 §8-11 原计划**整体删除适配层**（四处符号 + 10 处消费点 + 红队/一致性产物重录），列为下一轮第一件事（§8-14） |

> 顺带一条对我方有用的确认：W0 的 `tests/contract/test_no_shared_ecom_dsn_fallback.py`（`36c782a`）把 **`eval/pg_guard.py` 当作 DSN 形状/脱敏的唯一真相**来 import，且不复制第二份 regex ⇒ `redact_dsn` 从此有**窗外消费者**（我方已把它自己的四条断言当作对该消费者的契约面；下一轮删适配层时不得顺手改这个函数）。该守卫自己的 docstring 也写明：`_dsn_from_env_file()` 那条**运行时**回退静态看不见 ⇒ O7 的剩余面正好是这一条，已按实测收窄（见 RELAY O7 更新）。

---

### 4.13 🔴 第七轮（同日 16:45–17:10，HEAD `c76f701`）：适配层**当天到期、当天删净**，并第一次拿到「闸门在生产链上生效」的产物级证据

| 项 | 内容 |
|---|---|
| 触发 | W2C `c76f701`（U-121 第三步：`policy_gate.py:110` 改调 `guard_allowlist`、④⑤ 改读 `all_columns`）落地 ⇒ 上一轮自己立的三条到期哨兵**当场变红**（就是 §8-14 预约的那件事）。判据一字未改，红得正是设计意图 |
| 动作（不再等下一轮） | 删 `AssetAllowlistView` / `GuardAllowlistBundle` / `StructuralAllowlistBundle` / `structural_wrapper` **四处符号** + `harness.py` §三 那行「存在理由」清单；5 处消费点改调端口的 `guard_allowlist`（`harness.selfcheck`、`runner.py:446`、`redteam_eval` 的 gate1 取面 / gate2 探针 / `run_redteam`）+ `conftest.py` 夹具 + 6 处测试。净变化 = **`eval/` 三个文件 64 增 / 216 删** |
| 三条红哨兵的去向 | **没有一条改成 skip、没有删任何断言**。AST 扫描器 `_port_methods_called_by_gates()` 一字未动（W7 点名要留的那条），判据从「到期即红」反转成「回退即红」= `test_the_adapter_symbols_stay_dead`，四件事一起钉：① 两侧都调 `guard_allowlist`；② 两侧都不再调 `asset_allowlist`；③ 适配符号不在（含 `redteam_eval` 那两个）；④ 「存在理由」清单行不在。前身那条 raise 测试转成 `test_gate2_on_the_production_port_no_longer_raises`（**点名绿态**：不抛且 pass 才算绿） |
| ★ 本轮最值钱的读数是漂移对照 | 红队 66 条逐用例比对「删之前 / 删之后」：**安全判定零漂移**（`n_cases_clean` 52 → 52；`blocked` / `leaked` / `covered` / 终态形状 / 拒绝处 66 条全等），唯一变化是那一格口径——裸端口喂 `run_gate2` 的 `ContractViolationError` 从 **45/66 → 0**。⇒ ① 删适配层没有偷偷改变任何一条安全结论（这就是「漂移不是回归」的证据）；② **「策略闸门在生产链上生效」这句话第一次有产物级证据**，已作为 RELAY §三 C6 知会 W2C。对照件两份都在库里：`_redteam_before_c76f701.json`（HEAD 版 = 之前）与 `redteam_results.json`（之后） |
| 顺手修好两条**假安全** | `probe_gate_rejections.py` 与 `probe_rule_identity.py` 仍 `from harness import build_guard_allowlist`（上一轮删函数时漏改）⇒ 报告 §10 的复算命令**跑不动**，而 `test_reproduce_commands_are_runnable_paths` 只查「路径存在」不查「能不能跑」⇒ 它一直绿。两条已改调端口并实测跑通（详见 §5.22） |
| 复算 | `cd backend && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest tests/eval -q` → **331 passed / 0 failed**（15.17s）；全量见 §6；`ruff check .` 与 `ruff check --config pyproject.toml ../backend/reports/w6` 均 All checks passed；`PYTHONUTF8=1 lint-imports` → 4 kept / 0 broken；`eval/reporter.py --no-backup --pytest-log backend/reports/w6/_full_pytest_committed.log` → 判定集合 **PASS 0 / FAIL 4 / PARTIAL 2 / UNVERIFIED 2**（连续**四轮**零判定漂移） |


## 5. 本窗口的自我修正（二十三处，都是"差点把假的报出去"）

| # | 差点报出去的东西 | 真相 | 修法 |
|---|---|---|---|
| 5.1 | **2 条 P0 `security_leak`**（`R-PII-07`、`R-NA-02`）| 题面应拒答，系统收口成 `clarify` 且**没有出 SQL** ⇒ 是终态形状/出口策略之争，不是泄露。这个类别会直接触发"回滚上线"决策 | `attribution.py` 安全侧改成"应拒答**且真的出数了**"才算泄露；新增 `terminal_shape_gap` 类别（§C.7 词表外，报告单列）；`test_correct_refusal_is_not_a_security_leak` + 新类别合法性断言 |
| 5.2 | **G-8 = FAIL**（"澄清后一次成功率 0%"）| `runner.py` 是单轮的，没有"clarify → 用户补答 → 再走一次"的回路 ⇒ 那个 0% 是**结构性不可测**，不是被测系统失败。判 FAIL 会让下一轮有人来放宽阈值 | G-8 在缺第二轮回路时判 **UNVERIFIED**，并把可测的那一半（澄清率 45%）作为证据保留；`test_g8_single_turn_batch_is_unverified_not_fail` |
| 5.3 | §4 归因表里的 **`? \| 7`** | 旧实现按"verdict 不等价"聚类别，而 runner 对**交互层判对**的用例根本不写 verdict ⇒ 3 条正确拒答 + 3 条正确澄清 + 1 条 infra_error 全落进"无法归因"。§C.7 的"不可归因 ≤10%"就是靠这张表被读错的 | 新增 `split_attributions()`：失败分布 + 三个补集（`interaction_correct` / `unscored` / `equivalent_so_not_failure`）分开列；真失败却无类别才并入 `unattributed` |
| 5.4 | RELAY 初稿写"`pay_status='paid'` 零差值是因为 `v_order_paid` **已预筛**" | 那是**没做过的实验**：沙箱里 `v_order_paid` 根本不是视图（SQLite 侧是实体表），非 paid 行 74,173 条确实存在。真跑数据才看到根因是这些行 `pay_time` **全为 NULL**，而且**无时间边界时该谓词差 15.4%** ⇒ 原句的因果和"恒零"都错 | 用 §4.1 的实测数（`attribution.steps[].delta_vs_prev` 12/12 为 0 + 全表分布）重写 RELAY B1；结论从"补了也没用"改成"仅在有 `pay_time` 边界时冗余"，并据此补正 A1 的归因措辞 |
| 5.5 | 首轮报告写着"**PG 业务事实表 0 行** ⇒ RLS 有效性与结果集等价不可测" | 数据其实到位得比我想的早，而且**那句 0 行的成因写错了**：探针只数了视图，而 `p_*_tenant` 里 `current_setting('app.shop_ids', true) = ''` 在 GUC 未设时取 NULL ⇒ 整条策略恒 false ⇒ 视图恒 0 行（视图按**属主**求策略，连绕开 RLS 的属主连接也一样）。我把"自己没设上下文"报告成了"环境没数据" | `_probe_pg_real.py` 加"逐租户 `set_config` + 两条负对照 + 不重不漏判据"，重跑后基表 **2,024,017 行**、五关系求和与沙箱**逐数相等**、`rls_partition_ok = true`（§4.4）；教训并入 §5.4 同一条：**没设上下文 ≠ 没有数据** |
| 5.6 | 我在 RELAY P6 里把受害视图列成 `v_order_paid`/`v_product`/`v_shop`/`v_campaign`，并建议把"未设"改成"= 不限"（coalesce） | 两处都不成立：含 `shop_ids` 条款的只有三张基表，`campaign`/`order_refund`/`traffic_daily` 是纯租户条件；而 `''` 已经是"不限店铺"，把"未设"也当"不限"= **fail-open**（整租户跨店铺可读），比现在 fail-closed 的 0 行更糟 | 由 W7 的复现矩阵证伪 ⇒ P6 已订正范围、删掉 `v_campaign`、**撤回 coalesce 提议**，诉求收窄为"漏设就吵"；同时把"未设过 ⇒ NULL"和"RESET ⇒ `''`"两种状态区分开（我只踩了前者） |
| 5.7 | 两连错：① 第一版并行对照给出 `count(*) = 0`、`sum = None`，看起来正好"复现"W7 的 ④；② 订正 ① 之后我上报了**"未能复现"** | ① 是我自己的实验缺陷：同一条连接、同一个事务里连改 `debug_parallel_query` ⇒ 读的根本不是并行路径。② **更贵**：每例独立连接重写后 8 组全精确，我就把它当成了事实 —— 但那把"轴"本身是坏的（本机 PG16 的 `debug_parallel_query` 只接受 `off/on/regress`，而 **off 下计划里照样有 Gather** ⇒ 我没有串行对照组），且只测了"两把 GUC 都显式设值"一种形态 ⇒ **"恒绿"正是这一格能藏错的原因** | 判据换成"四形态 × 真串行/真并行 + `Workers Launched ≥ 1`"后**少算已复现**（§4.8）；`parallel_equality_ok = false` 如实落盘，措辞按形态点名（`gap_table.parallel_clause`），并加 `test_real_probe_artifact_wording_names_the_reproduced_undercount`（吃**真实产物**，防替身形状领先于现实）。教训：**"我的对照组全绿"要先证明那组对照真的有对照组** |
| 5.8 | 我用来**排除**"worker 没拿到 GUC"这条解释的证据：同一状态下并行投影 `current_setting('app.shop_ids',true)`，600,178 行全部报 `''` | 那是**提升性伪影**：投影表达式里**没有列引用** ⇒ planner 把它提到 `Gather` 之上、只由 leader 算一次 ⇒ 我测到的自始至终是 leader。W7 给出带列引用的形状后我方复算：`Workers Launched = 2`，leader 格 `''` **194,377** 行、worker 格 `<NULL-in-this-process>` **405,801** 行，两格相加恒 = 600,178 ⇒ 被排除的那条解释**恰恰是成因** | §4.8 ③ 改写为"成因已定位"；`_probe_parallel_states.py` 的这组对照换成带列引用形状并加 `void`（同一条计划里 `Workers Launched < 1` 就整组作废，不许留假读数）；`gap_table.parallel_clause` 的措辞同步从"机制未定"改口。教训：**测"另一个进程看到什么"的对照，表达式必须带列引用，且要在同一条计划里核对 worker 真的起了** —— 否则你测的是自己 |
| 5.9 | 我在 §4.8 写"**`eval/` 与 `reports/w6/` 对 `cost_ledger` 零引用**"（用来回应 W7 说的"累计成本基线重开"） | **这句话过宽、且被我自己复算证伪**：`grep -rin cost_ledger eval/ backend/tests/eval/` 确实 0 命中（代码侧成立），但本窗口**已入库的产物** `_probe_pg_real.json` 里就拍到这张表三处（`pg.pg_row_counts.cost_ledger = 3`、`parity.relations[4].pg = 3`、`pg.rls_flags[4]`）⇒ "reports/w6/ 零引用"不成立；而 3 这个数与 W7 现报的 6 行已经不一致，正是"表被清空过"的痕迹 | §4.8 那条按实测改口成**两层**说法（代码侧零依赖 ⇒ 门禁读数无需重取；产物侧有清单级快照 ⇒ 重跑会变、且不进任何判定）。教训：**"零引用"这种全称结论必须写清扫描范围**，尤其当我方产物本身就是被扫对象的一部分时 —— 范围没写清的否定句，比肯定句更容易骗到下一轮的自己 |
| 5.10 | §4.3 与 §6 纪律二里那句「匣带足以承担零成本复算 ⇒ 自我修正不必再花一次钱」 | 第四轮想复算时**20/20 全 miss**（`tokens_total=0`）：上游 `fbae176` 把 `metrics()/aliases()` 枚举器接进语义摘要，首条 system 从 6,401 涨到 11,343 字符 ⇒ 报文指纹全变。**那句话本身没错，错在它没时间戳、也没人负责在失效时改口** | 新增 `probe_cassette_replay.py` + `cassette_replay_probe.json`，措辞改由 `reporter.replay_reproducibility()` 按命中率三态派生；§4.3/§6 两处按实测订正并把"重录 = 花钱（20 题 ≈ ¥0.033）"写回 §8。教训：**能力句必须带复算方式**，否则上游一次正常迭代就能让它变成假话，而且只有下一轮花钱时才发现 |
| 5.11 | 复算 W7"十份历史回执全部 UNVERIFIED"时，把**他们的扫描面**一起继承成了我的扫描面（探针 glob 写死 `receipt*.json`） | 判定我是自己跑的（`{'UNVERIFIED': 10}`，改前改后两次一致），但"扫哪些文件"是声明不可拆的一部分：同目录的 `baseline_c5.json` 与两份 `preflight_*.json` 从没进过**任何一侧**的扫描面，而 `baseline_c5.json` 恰是唯一喂我方真 gates 会判 **G-6 = PASS** 的那一份（p95=3675.8ms、`g6_caveat` 为 null、无 `admission`、无全请求分位数） | 扫描面改 `deploy/loadtest/*.json`（13 份）并把"为什么不用 `receipt*`"写进注释；产物新增 `stale_true_cells_total` / `null_caveat_scenarios_total` 两个可核对读数；降档见 §4.10③。教训：**复算别人的声明时，判定要自己跑，覆盖面也要自己定 —— 照抄 glob 等于把对方的盲区装进自己的证据链** |
| 5.12 | G-1 的 `measured` 写成 `failed = 1 failed + 3 errors = 4`，且点名正则 `FAILED\|ERROR` 把两类收进同一个列表 | 两个数说的是**不同的坏法**：断言失败 = 被测系统，夹具 error = 测试环境，归属窗口也不同（后者归 O6 的 W0/W2B）。混成一个数，下一轮就会有人问"评测系统坏了 4 处？"；而第五轮的真实构成已经是 **0 断言失败 + 3 夹具 error**，旧写法会把"红因只剩窗外"这件事糊掉 | `reporter.parse_pytest_summary()` 拆 `failed_tests` / `error_tests`，`gates._p0_notes()` 分组点名，`measured` 改「断言失败 0 + 夹具 error 3 = 红 3 条」；再记一条取证坑：摘要要点出 error 名，`-r` 须带**大写 `E`** ⇒ §8 的复算命令由 `-rfes` 改 `-rfEs`；测试 `test_pytest_summary_keeps_assertion_failures_and_fixture_errors_in_separate_lists` + `test_g1_measured_keeps_assertion_failures_and_fixture_errors_apart` |
| 5.13 | 上一轮我自己上线的"适配层到期哨兵"，判据是**两文件并集**（"两个都不读扁平面才红"），当时还自评"不靠记性" | W4 `357618f` 只接了 gate1 半边 ⇒ 并集判据**既不红也不报**，而 `harness.py` 里"消费方还在读 `asset_allowlist`（点名两个文件）"那句注释当场失真一半。机制没坏，是**判据粒度选错了**：一个会分两次到期的东西，不能用一个整体条件守 | 哨兵改**按文件**判（逐文件读数进消息）+ 新增 `test_the_adapters_stated_reason_list_matches_the_code`，把"还剩谁"从散文升级成 `harness.py` §三 那行机器可读清单并**双向**核对。教训：**"到期就红"这类机制必须按最小可到期单元设计，否则它只在最后一件事发生时才工作，而错的是前一半** |
| 5.14 | 我给**自己新写的取证正则**带了 `\b` ⇒ 在干净文本上绿、在真日志上恒返空，「夹具下发过的 DDL 形状 = 无」差一点被我当事实报出去 | pytest 把夹具 SQL 以 **repr** 打印（形如 `query = '\nCREATE SCHEMA …'`），那个 `\n` 是**两个字符** ⇒ `n` 与 `C` 之间没有词边界。发现方式不是读懂了代码，而是**跑完真日志后去产物里看那一格**（空的），再拿同一份日志做单变量对照：带 `\b` = `[]`、去掉 `\b` = 3 条 | 去掉 `\b`，并补一条**照抄真产物形状**的正对照 `test_pg_surface_reads_ddl_from_the_real_repr_shaped_pytest_output`。教训：**取证正则用顺手写的干净文本只能证伪、不能证实**，必须有一条夹具是从真日志上抄的 |
| 5.15 | 共享 schema 判据用 `split(" ", 1)` 切对象名 ⇒ 我以为它在判「有没有动 `app` / `public`」 | DDL 动词**一词两词都有**（`TRUNCATE x` / `DROP TABLE public.x`）⇒ 两词动词那类**永不命中**（对象名剩成 `table public.foo`），带 `CASCADE` 的又会**误命中**：两个方向都错，所以不是"少报"而是"乱报" | 换成「跳过动词/`IF EXISTS` 词表、取第一个剩下的词」（`gates._DDL_PREAMBLE`），正反两向都进测试（`test_ddl_on_the_shared_business_schema_gets_a_named_warning` 先红后绿 —— 是测试抓到的，不是我看出来的） |
| 5.16 | `pg_surface()` 的 docstring 写着「凭据由 `_redact` 兜底脱敏」，而 `_redact` **根本不存在** | 写实现时把"打算写的东西"当成"已经写的东西"。当时的真实状态：口令不落盘只由"我那三条正则取不到"这一句成立 | 补实现 + 四个出口一律过它；并把一条纪律写死：**文档/注释里任何函数名引用都必须能 grep 到**（§1 的行数口径本轮也补进了表格，理由同类 —— 上一版只写数字不写定义，本轮同口径复算才敢确认 6,393 与 6,597 之间没有矛盾） |
| 5.17 | 我在 §4.11① 与 RELAY P12 写下"本轮全量套件前/后各测一次 `app.embed_doc` = 197\|197 ⇒ **我方这轮没有改变那张表**" | **判据不敏感于被测量**：一次破坏性重载（TRUNCATE + 重灌 / 无派生器的 materialize）之后，`count(*)` 与非空计数**可以是同一个数**。W7 的"14:26 之后仍有一次运行留下重载签名"正好落在我方第二次全量（14:53:47–14:55:46，基线 `82f5bdb` 早于 U-114 防线①）里 ⇒ 我那句话**作废**，改口成"W6 的跑具备产生该签名的全部条件，但不据此下因果结论" | 换成对重载敏感的签名：`pg_class.relfilenode` + `n_tup_ins`/`n_tup_del` 形状，并落成可复跑器件 `probe_pg_boundary.py`（产物 `pg_boundary.json`）。教训：**"没有变化"这类否定结论，要用对变化敏感的度量**；计数相等只能证明"我没看见差别" |
| 5.18 | 我在 §4.11① 写"夹具 DDL 目标**全部**限定在 `retrieval_dense_it`" | `pg_surface` 从**日志文本**取证，而 `pytest -q` 只打印失败/报错夹具的 SQL ⇒ **通过的夹具一行都不留**。同一串三行输出既出现在"零测试执行"的那次、也出现在"可能 truncate 过 `app.cost_ledger`"的那次 ⇒ 该字段区分不了这两个世界 | 措辞降级成**下界**（代码与文档各一处：`gates._pg_surface_notes()` 空值时明说"取不到 ≠ 没做写操作"；§4.11 补"下界不是全集"），并让"跑前/跑后签名"作为上界补件。教训：**全称句的范围要写清"取自哪里"** —— 从日志取证的字段永远不可能覆盖日志没打印的部分 |
| 5.19 | 我为了做本轮实验，把 `backend/reports/w6/_full_pytest_w6.log` 覆盖了 | 上一轮那份 **2254 passed / 3 errors @ `3ff31c4`** 的原始日志**不再存在** ⇒ 那个读数如今只在 `eval_metrics.json`、报告表格与本文件文字里，无法从日志重取。这是我自己的取证倒退，不是别人的 | 已改做法：新日志按轮次改名保留（`--continue-on-collection-errors` 这次的读数落在同名文件里，本轮之后再落 `_full_pytest_<UTC>.log`），并在 §6 写明"哪些数还能从产物重取、哪些只能引本文件" |
| 5.20 | 我在 RELAY P14 的**草稿**里写下了 `embed_doc` 的 `relfilenode`「25076 → 32396」这个**根本没测过**的数字（用来支持「15:10 之后还在重载」） | 起草时把「如果 W7 说得对，我应该看到什么」当成了读数。真实快照：`08:25:19Z → 09:05:43Z` 八个快照 `relfilenode=25076`、`n_tup_ins=n_tup_del=10244`、`n_live_tup=197` **逐字段一字未动** ⇒ 不但数字错，**方向也反了**（该区间没有任何重载） | 落笔前先读 `pg_boundary.json` 再写句子（这次靠这一步拦住，未进版本库）。P14 已改写成「我方最早一把敏感签名在 16:25（本机）⇒ 对 W7 的 14:26–15:06 既不能证实也不能证伪」。这是 §5.17『计数不敏感』同族的另一种错法：**把推断出来的读数当实测读数** |
| 5.21 | 重录红队产物**之前**的 `cp` 失败了，我仍然接着跑了覆盖命令 | `cp eval/redteam_results.json …` 静默失败（真产物在 `backend/reports/w6/`，不在 `eval/`），而我把 `&& echo backup_ok` 挂在后面 ⇒ 没打印就是失败了，我盯着 tail 看却没看这一行。上一轮刚为同类事写过 §5.19 | 本次**侥幸可恢复**：该文件在版本库里，用 `git show HEAD:…` 取回并入库为 `_redteam_before_c76f701.json`。规则收紧：覆盖任何入库产物前先 `git status --short <file>` 确认它 tracked；未入库的产物一律先复制再跑 |
| 5.22 | 我方 `test_reproduce_commands_are_runnable_paths` 给出的是**假安全**：报告 §10 两条复算命令其实跑不动 | 那两条脚本 import 了一个上一轮就删掉的函数 ⇒ `ImportError`；而测试只断言「路径存在」，所以整轮全绿。另外我用「管道 + tail」读退出码，把这次的 traceback 读成 `rc=0`（同一族的坑第二次踩） | 已改两条脚本并各实测跑通一次（`probe_rule_identity` 复算到 R06/R07 归因漂移；`probe_gate_rejections` 出 F1/F2/F3 三桶）。**待办**：把 §10 里不联网、不连 PG 的那几条探针改成「真跑一遍」的断言，而不是靠我记着跑 ⇒ §8-16 |
| 5.23 | 我写的 star-splat 把一句 caveat **拆成了 150 多个单字条目**：`*（f"长句" if cond else ()）` 星号展开的是**字符串本身**（字符串可迭代），不是「一行文字」 | 新加的 G-6 归因句在产物里变成一格一个字。抓到它的是**我自己刚写的那条测试**（`test_g6_over_budget_on_a_writer_unjudged_receipt_stays_fail_but_names_the_kind` 断言整句在其中 —— 先红，我照它的失败输出回去看源码）⇒ 顺序是对的：**先写判据再写实现**，所以缺陷没进到产物与报告里 | 改成显式 `cav = [*notes, …]` + `if …: cav.append(…)`；并把这条教训记成规则：**凡「按条件往 tuple 里追加一段文字」一律用 list.append，不许在 `*` 位置上写三元** |
另外两处过程性错误也如实记：**两次**把只打印了计划的命令当成跑完的批次（runner 未带 `--yes` 时只输出计划、exit 0），都是从日志里发现"未带 --yes：只打印计划，不执行。"后重跑。还有一处是**读数骗人**：`lint-imports` 在 GBK 控制台崩溃时真实退出码是 **1**，但命令尾接了 `| tail` 把退出码吞掉，我因此记成"exit 0 却打印了 gbk"——去掉管道重取 `$?` 才对得上（RELAY O4）。纪律：**只报实测，且实测要连着退出码一起看**。

---

## 6. 边界与纪律自证

| 要求 | 自证 |
|---|---|
| ADR-18：评测**必须** import 在线 `app/guard`/`app/exec`，不另写一套 | `test_eval_reuses_the_online_gate_and_executor_entries`（正面：`eval/` 里必须出现 `from app.guard import…`，且出现重抄的闸门实现即失败）+ `test_production_code_never_imports_the_evaluator`、`test_the_sandbox_adapter_is_not_visible_to_production`（反面：评测件不得反向进入生产 import 图） |
| 不写冻结件 | `test_w6_owned_eval_modules_never_open_a_frozen_asset_for_writing`（AST 扫 `open(..., mode)`，4 个冻结件词根一律不许写模式）+ `test_only_the_w1a_build_scripts_can_write_frozen_assets`（命中集**恰好等于** W1A 那三个 `build_*.py` ⇒ 顺带证明扫描器没瞎） |
| 验真不是装饰 | `test_frozen_input_verification_actually_catches_a_tamper`（改一个字节就必须红）+ `test_sandbox_db_hash_is_part_of_the_frozen_evidence` |
| §C.6.1 纪律一（先报计划） | `runner.py` 不带 `--yes` 只打印计划；计划含条数、模式、超时、**外推成本** |
| 纪律二（产物可复算） | 报告 §10 全部命令零 LLM 优先；但"缺匣带就 `--mode replay`"这句**今天被实测证伪**（20/20 miss，见 §4.3）⇒ 本窗口把它从**能力句**改成**带产物的读数句**：新增 `probe_cassette_replay.py` + `cassette_replay_probe.json`，措辞由 `reporter.replay_reproducibility()` 按命中率三态派生（全 miss / 部分 miss / 0 miss），下次再失效它会自己改口 |
| 纪律三（覆盖前备份） | `_backup()` 覆盖前先 `mv` 成 `*.bak-<UTC>`；本机累计 **28 份**（均不入库）。**第三轮**刷新报告与 `eval_metrics.json` 时改带 `--no-backup` —— 这两个文件已在版本库里，git 就是备份，不该再长出一堆本机副本；`runner.py` 落盘批次产物的备份行为**未改** |
| §C.4.3 与 §17.6 不混用 | `consistency.py`（三测）与 `probe_metric_values.py`（G-7）**是两个不同产物**，报告 §6 与 §6.5 分别引用。`test_known_limitations_discloses_c43_rate_and_never_the_coverage_probe` 钉住"G-7 只吃权威值比对产物，喂覆盖度探针会读出假一致率"；`test_zero_input_report_has_no_pg_or_c43_readings` 钉住"没跑就不许有读数" |
| 分层契约 | `lint-imports` 控制台脚本：`Contracts: 4 kept, 0 broken.`（U-41：`python -m importlinter.cli` 假绿，不用；中文 Windows 须加 `PYTHONUTF8=1`，否则 gbk 崩溃，见 RELAY O4） |
| Lint | **CI 口径**：`cd backend && ruff check .` → 本轮实测 `All checks passed!`（上一版残留的 `reports/w4/` 那 1 条已不在）。**`eval/` 不在 CI 范围内**（RELAY A7），自查口径 = `cd eval && ruff check --config ../backend/pyproject.toml .` → 23 条：18 条在 W1A 的 `build_*.py`/`case_library.py`（他人范围，未碰），**5 条是本窗口刻意保留的 `I001`**（`consistency`/`harness`×2/`redteam_eval`/`runner`）—— 这些文件的 `import _bootstrap` **必须**排在任何 `app` 导入之前（它负责改 `sys.path`），而 `ruff --fix` 会把它排到 `from app…` 之后 ⇒ 一修就 `ImportError`。本轮改动前后的 HEAD 版本在这 5 条上计数相同（实测对比，非本轮引入）；本窗口改过的 `gap_table.py`/`reporter.py` 与全部新增测试均为 0 违规 |
| 密钥 | 全程未打印任何 key 的值（只报"有无值"与长度）；`deploy/.env` 只读。入库侧自查（按两个 commit 的文件清单逐个扫，共 **50 个文件**）：长 `sk-[A-Za-z0-9]{16,}` **0 命中**、`Bearer` **0 命中**；匣带 `eval/cassettes/w6_batch.jsonl` 每条只含 `key/path/status` + `request`（`model/messages/temperature/max_tokens/…`）+ `response`（`choices/usage/…`），**不含任何 HTTP 头字段** ⇒ 结构上就存不下凭据。`_probe_pg_real.py:39` 的两处本地引导 DSN 与**已在版本库里**的 `backend/tests/integration/test_exec_real_pg.py:34` **同字面**（同一 dev compose 引导值 ⇒ 未新增凭据，`.gitleaks.toml` 的 `app_ro_pwd` 形态本就放行）|
| 中文控制台 | 所有命令带 `PYTHONIOENCODING=utf-8`，产物 UTF-8 |

**测试**：`backend/tests/eval` **334 passed**（15.56s）。全量套件**本轮重跑**（`cd backend && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m pytest -q -rfEs`）⇒ **0 failed / 2254 passed / 6 skipped / 3 errors（119.76s）@ `3ff31c4`（本轮 feat 提交；起点 = `82f5bdb`）**，G-1 按这份新日志取数；被点名的测试、错误数与**接触面**（`pg_surface`）都已搬进 `eval_metrics.json` 的 `gates[G-1]`（日志本身不入库 `.gitignore:47`，见 A9）。基线在**同一天里第三次换**：第五轮收口是 `2232`，本轮 `2254` —— 差值**逐条点名可核对**：我方 +16（`tests/eval` 收集数 318 → 334），W4 落 `c2f63cf`（U-122 端口成员集断言）新建 `tests/contract/test_exec_port_face_contract.py` = 5 条 + 给 `test_decision_table_d_e.py` 从 13 条加到 14 条 = +1 ⇒ **2232 + 16 + 6 = 2254** 对得上（当日其余 `docs(w2b)/docs(w2c)/docs(w4)` 提交不新增用例）。⚠️ 本轮内我自己就差点错一次：第一次全量跑（2252）时新测试只落了 14 条，补满 16 条后**重跑**才得 2254 ⇒ 报数只认**最后一次整轮跑**，中途那个数不进任何文档。⚠️ 一条取证细节：**`-r` 必须带大写 `E` 才点得出 error 用例名**（第四轮用的 `-rfes` 只能给个数），报告 §10 的复算命令已改。教训同类：**同一天的基线也会漂三次 ⇒ 取数要连着 commit 一起记**（`eval_metrics.json` 的 `meta.git.rev` 由代码写入，不用手抄）。
**同日续轮（16:3x，HEAD `d367287`）两条新实测**：① 上面那条"全量"命令**跑不动了** —— 裸跑 `pytest -q -rfEs` 得 `Interrupted: 7 errors during collection`、**退出码 2、零条测试执行**（`tests/integration/*` 在 import 期被 U-114 防线①的 `env_dsn()` 拦住，本机三个 env 全未设）；② 我方**不窄化范围**（缩门禁与假绿同族），改用同一收集面的 `--continue-on-collection-errors` ⇒ **21 failed / 2164 passed / 6 skipped / 10 errors / 128.37s**，`eval/reporter.py --no-backup` 已按这份日志重生成（`meta.git.rev = d367287`），判定集合不变。新命令形状已进报告 §10。
首轮那 2 条 W0 的 GBK 红**已被 W0 修掉**（RELAY O1 关闭 ⇒ G-1 才转 PASS，见 §3）；剩下 6 条 skip 全在 `tests/integration/test_retrieval_fts_pg.py`（夹具 DSN 对 `ecom` 库无 DDL 权限），仍按 RELAY O5 折算成 UNVERIFIED。

---

**第七轮（同日 17:0x，HEAD `c76f701`，适配层删净之后）三条实测**：① W6 自己那格 `cd backend && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest tests/eval -q` → **331 passed / 0 failed / 15.17s**（上一轮那 3 条按设计红的到期哨兵已反转成回归哨兵，不再是红灯）；② 全量 `cd backend && … pytest -q -rfEs --continue-on-collection-errors` → **1 failed / 2187 passed / 6 skipped / 10 errors / 95.43s**，唯一的断言级红灯在 **W2C 自己的套件**（`tests/redteam/test_redteam_guard.py::TestRedTeamFrozenSet`：四条 `RT-R07-00x` 期望 R07 实得 R06 = RELAY C3 的现形），10 条 error 仍是夹具起不来（7 条 = 本机缺 env 的 U-114 防线①，3 条 = O6 的 `permission denied for database ecom`）⇒ G-1 的红因**第一次全部指在窗外**，但**性质变了**：不再只是环境，多了一条被测系统侧的真失败；③ 两次把全量套件夹在中间的运行边界签名差值仍为 `[]`（本轮四组 A/B 全 `[]`，见 `pg_boundary.json`）。⚠️ 分解口径（别把两数并成一个）：`tests/eval` 329 = 上一轮 331 − 4 条视图/代理测试 + 2 条替代断言；全量 passed **2187** = 删适配层前同树基线 `2181`（−4 条视图/代理测试 +2 条替代断言后的自然结果）+ 我方本轮新增 **2** 条（边界探针「不许带字面共享 DSN」的守卫 + G-6「写端未判定」的归因判据）+ 他家窗口在同一条 main 上落地的 **6** 条（本轮树里含 W2A `d8eca02`（U-124）等批）⇒ **没有任何一条是被我删掉来换绿的**，但也不许把 +6 说成我方的产出（红队 66 条安全判定逐用例全等，见 §4.13）。
⚠️ **全量这一格在本轮被重跑三次，报告只引用最后一次**（`_full_pytest_a14.log`，与被推送的树同源）：前两跑的 2179 / 2180 全部作废 —— 一次是我方改完 `eval/reporter.py` 之后才发现它已跑过，一次是补测试之后。🔴 **共享工作树还有一条必须写出来的读数纪律**：最后一跑的 `passed` 从 2180 跳到 **2187**，其中只有 **+1 是我方新增的守卫**，其余 **+6 来自别家窗口落在同一条 main 上的测试**（本轮树里新增了 W2A `d8eca02`（U-124）等批）⇒ 报 `passed` 总数时必须说清它是**整棵共享树**的数，不能当成「我方这轮多测了 7 条」；我方自己那一格的权威读数始终是 `pytest tests/eval` = **331 条**（构成可指）。
🔴 **同轮再补一条自证的守卫**（第七轮，最后一步）：`probe_pg_boundary.py` 原本也带**字面默认 DSN** 指向共享 `ecom`（`COMMERCEQL_PROBE_DSN` 未设就回退）—— 而我方上一轮刚把「夹具默认回退到共享库」作为 O7 上报给 W0/W2B。已改成**缺 env 即 exit 2、不出产物**（与 U-114 防线①同形：**不 skip**、不猜默认库），并加一条源码级守卫 `test_the_boundary_probe_takes_no_literal_shared_dsn`（`tests/eval/test_pg_contact_surface.py`）钉住「探针源码里不许出现字面共享库 DSN」。实测：不设 env → 退出码 2 并打印要设什么；设 env → 正常出快照与差值（`post-final-check → env-shape-check` 差值仍 `[]`）。⇒ `tests/eval` 329 → **331 条**（A14 那条又 +1 ⇒ 见 §6）。
## 7. 提交

| commit | 内容 |
|---|---|
| `feat(w6)`（首轮） | `eval/{_bootstrap,runner,harness,sqlite_exec,cassette,equivalence,attribution,grid,gates,gap_table,consistency,redteam_eval,reporter}.py`（13 个模块）+ `backend/tests/eval/**` |
| `docs(w6)`（首轮） | `backend/reports/w6/` 全部本窗口产物：3 份 md（`DELIVERY`/`RELAY`/`评测报告与门禁判定`）+ 读数件（`eval_metrics.json`、`consistency_results.json`、`redteam_results.json`、`results_w6_live20.json`、`smoke_one_case.json`、`_probe_pg_real.json`、三个 `probe_*.json`、`probe_gate_rejections.json`）+ 取证脚本（`probe_*.py`、`_probe_pg_real.py`、`select_smoke_batch.py`、`smoke_one_case.py`）+ `smoke_batch_ids.json`；外加数据侧 `eval/cassettes/`（`w6_batch.jsonl` 48 次调用 + `w6_smoke.jsonl` 单条冒烟）与 `eval/results_v1.json`（本轮批次读数）。**不含 `*.log`** —— `.gitignore:47` 全局忽略，本窗口不例外（该约定的后果见 RELAY A9）|
| 第二轮（2026-09-20） | 代码：`gates.py` G-6 判定按 U-106 口径重写（全请求优先、准入口径不得判 PASS）、`reporter.py` 读 `p95_scope`/`admission`/`latency_ms_all_ms` 且路径改仓库相对、`_probe_pg_real.py` 加租户上下文与负对照、新增 `probe_loadtest_receipts.py`、测试 +6。产物：重新生成的报告 + `eval_metrics.json` + `_probe_pg_real.json` + 本轮 RELAY/DELIVERY |
| 第三轮（2026-09-20，回应 W7 对 P6 的答复 + 拉入 U-107/U-108 后复测） | 代码：`harness.py` 超时遍历改"契约 ∪ LLM 清单"并显式输出 `not_in_contract`、`link` 移进"不放大"清单、四处注释按当前契约形状订正；`gap_table.py` 新增 `parallel_clause()`（三态、由探测派生）；`reporter.py` 读探针的 `parallel_equality_ok` 并新增 `timeout_snapshot_drift()`（跑批快照 vs 当前树的超时表点名）；`_probe_pg_real.py` 新增 `_parallel_equality()`（并行开/关 × `is_local` × 各 5 次，每例独立连接）。测试 +3（→ **305 条**，含把超时契约测试按新形状重写）。产物：`eval/reporter.py --no-backup` 重生成报告 + `eval_metrics.json`、`_probe_pg_real.json`（`parallel_equality_ok = true`）。文档：RELAY **G1 关闭 / G3 订正 / P6 全面订正 / P7 新增 / A10 补 W7 反证**、DELIVERY §1 §4.4 §4.6 §4.7 §5 §6 §7 §8。<br>⚠️ 该行里的 `parallel_equality_ok = true` 已被下一行**订正**（判据本身有缺陷） |
| 第三轮 · 续（同日，答 W7 对 P7 的答复） | 判据换形：`_probe_pg_real.py` 的 `parallel_equality` 从"`debug_parallel_query` off/on"改成"**四形态 × 真串行/真并行**（串行 = `max_parallel_workers_per_gather=0`）+ `Workers Launched ≥ 1` 才算测到"，实测把 `parallel_equality_ok` 落成 **false**（`v_order_paid/reset_placeholder` 并行少算约一半）；新增 `_probe_parallel_states.py`（两条角色路径 × 五种形态 + 被排除的三个假设）；`gap_table.parallel_clause()` 改成**按形态点名**并写明"机制未定"；`reporter.pg_facts()` 多搬 `parallel_undercount_states` / `parallel_state_ok`；测试 +1（→ **306**，含一条**吃真实产物**的措辞回归）。产物：`_probe_pg_real.json`、`_probe_parallel_states.json`、重生成报告 + `eval_metrics.json`。文档：RELAY **P7 由"未复现"改写为"已复现 + 机制未定"**、§十-6b 补"提交后复用连接 ⇒ 恒 0 行"、G3 补 W7 ③（`bind` 超时在回执里会长成 `refuse(no_data_asset)`）；DELIVERY §4.4 订正 + 新增 §4.8 + §5.7 改成"两连错" + §8-4 换待办。<br>⚠️ 该行里的**"机制未定"**与"`parallel_clause()` 写明机制未定"已被下一行（续二）**订正** |
| 第三轮 · 续二（2026-09-21，接 W7 的 U-110：把"机制未定"改成"成因已定位"） | 代码：`gap_table.parallel_clause()` 措辞改口（成因 = 占位符 GUC 不随并行 worker 传值 + 明写"本窗口只报读数不代修"）、`_probe_parallel_states.py` 的 `worker_side_guc_value` 对照换成**带列引用**形状（基表 `app.traffic_daily` × `app_rw`）并加 `void` 守卫（同一条计划 `Workers Launched < 1` ⇒ 整组作废）。**验证（全部本轮实测）**：`pytest backend/tests/eval -q` → **306 passed / 16.90s**；`cd backend && ruff check .` → `All checks passed!`（退出码 0）；`cd backend && PYTHONUTF8=1 ../.venv/Scripts/lint-imports.exe` → `Contracts: 4 kept, 0 broken.`（⚠️ 同一条命令在仓库根跑会 `Could not read any configuration.` + 退出码 **1** ⇒ 它必须在 `backend/` 下跑）；`eval/reporter.py --no-backup` → 退出码 **1 = 门禁未全绿**（不是脚本报错），读数 `PASS 1 / FAIL 3 / PARTIAL 2 / UNVERIFIED 2`（与上一轮同）。产物：重录 `_probe_parallel_states.json`（`workers_launched = 2`、`void = false`、`''` **194,377** + `<NULL-in-this-process>` **405,801** = 600,178）+ 重生成报告与 `eval_metrics.json`（缺口表/§7/§0 三处措辞已按产物派生成"成因已定位"）。文档：RELAY **P7 ④ 改写 + 表头改口 / A11 收窄成"裁修法不裁机制" / §十二 新增提升性伪影一行**；DELIVERY §1（6,300 / 3,375 / 237）§4.4 §4.8 标题与"两件事不并案"块 §5 标题（七→九）+ 新增 §5.9（把"对 `cost_ledger` 零引用"这句过宽的结论按实测改口）§6 §7。<br>⚠️ 一条命令形状账：`cd eval && ruff check --config ../backend/pyproject.toml .` = **23 条**（18 条 W1A + 5 条本窗口刻意保留的 `I001`，与 §6 一致），而 `cd backend && ruff check --config pyproject.toml ../eval` = **21 条**（少的是 `consistency.py:53`、`harness.py:75` 两条 `I001`）⇒ 本窗口**没做单变量对照**，所以只登记"复现请照抄 §6 的命令形状"，不解释成因 |

| 第四轮（2026-09-21，总控派单：U-119 判据③ + U-121 收尾 + 基线复述） | 代码：`probe_gate_allowlist_shape.py` **重写**（三种形状 × 两道闸门 + 两面反证 + 结论派生，退出码 0）；`eval/harness.py` **删除** `build_guard_allowlist()`（-45 行手拼派生）、`GuardAllowlistBundle` 改取端口 `guard_allowlist(ctx, max_rows=None)`；`eval/redteam_eval.py` 的 `structural_wrapper()` 从"造面"降为"**选面**"（只把 `columns` 换成端口的 `all_columns`）；`eval/gates.py` 新增 `_p0_notes()`（G-1 逐条点名到测试 + error 分开数）；`eval/reporter.py` 新增 `replay_reproducibility()` + `--cassette-probe`（§8 那条限制由产物派生，三态措辞）；新增 `probe_cassette_replay.py`。测试 +3 → **309**（端口形状逐键转发正对照 / 评测不得自造 wrapper / 适配层到期哨兵）。<br>**验证（全实测）**：`pytest tests/eval -q` → 309 passed / 12.09s；`cd backend && PYTHONUTF8=1 pytest -q` → **1 failed / 2222 passed / 6 skipped / 3 errors / 112.70s**（两因见 §3，均在本窗口外）；`cd backend && ruff check .` → 通过；`cd backend && PYTHONUTF8=1 lint-imports.exe` → 4 kept, 0 broken；两个探针退出码 0；`eval/reporter.py --no-backup` → **PASS 0 / FAIL 4 / PARTIAL 2 / UNVERIFIED 2**（G-1 由 PASS 改口 FAIL）。<br>产物：新增 `probe_gate_allowlist_shape.json`、`cassette_replay_probe.json`；`consistency_results.json` 扫描面 20→26 个源文件、7→16 个工件（判定不变）；`redteam_results.json` **逐字节未变**；报告 + `eval_metrics.json` 重生成。<br>⚠️ **push 状态**：本轮三笔提交留在本地 —— HEAD 里另含 W2A `b7e6c8d` 与 W2C `e125348` 两笔**未推**提交，本窗口不代推别人的活（唯一写者纪律），已上报总控待裁。 |

| 第五轮（2026-09-22 跨零点，起因 = W7 的 U-120 三态知会） | 代码：`eval/gates.py` 新增 G-6 降档分支（`g6_caveat` 为 null 但既无 `admission` 又无全请求分位数 ⇒ 不判 PASS）+ `measured` 把断言失败与夹具 error 分开 + `_p0_notes()` 分组点名；`eval/reporter.py` 把 `FAILED` / `ERROR` 拆成 `failed_tests` / `error_tests`，§10 复算命令改 `-rfEs`；`eval/harness.py` §三 把"适配层还剩谁没接线"改成**机器可读清单行**（类 docstring 里的重复点名删除）；到期哨兵改**按文件**判；`probe_loadtest_receipts.py` 扫描面 `receipt*.json`（10 份）→ `*.json`（**13 份**）并新增 `stale_true_cells_total` / `null_caveat_scenarios_total`。测试 +9 → **318**。<br>**验证（全实测）**：`pytest tests/eval -q` → **318 passed / 16.71s**；`pytest -q -rfEs` → **0 failed / 2232 passed / 6 skipped / 3 errors / 127.76s**；`cd backend && ruff check .` 与 `ruff check --config pyproject.toml ../backend/reports/w6` → 均 `All checks passed!`；`PYTHONUTF8=1 lint-imports` → **4 kept, 0 broken**；`probe_loadtest_receipts.py` / `probe_gate_allowlist_shape.py` 退出码 0；`eval/reporter.py --no-backup` → 退出码 1（门禁未全绿），读数 **PASS 0 / FAIL 4 / PARTIAL 2 / UNVERIFIED 2** = **与第四轮一字不差（零判定漂移）**。<br>产物：`probe_loadtest_receipts.json` 重录（改前 `{'PASS':1,'UNVERIFIED':10,'FAIL':2}` → 改后 `{'UNVERIFIED':11,'FAIL':2}`，`any_pass=false`）；`redteam_results.json` 在 W4 接 gate1 之后仍**逐字节相同**；`probe_gate_allowlist_shape.json` 逐字节相同；报告 + `eval_metrics.json` 重生成（`meta.git.rev` 落笔时 = `2544399`，收尾时 HEAD 已漂到 `6da16db` ⇒ 同一天的基线随别人落笔漂了三次，报数必须连着 commit 记）。<br>⚠️ **push 状态未变、且更复杂**：本地 HEAD 仍含 W2A `b7e6c8d`、W2C `e125348` 两笔**未推**提交，且本轮期间 HEAD 又向前漂了两笔（W4 `357618f`、`2544399`）⇒ 本窗口不代推别人的活，仍待总控裁定（RELAY 无新增 A 项，此项已在第四轮上报）。 |

| 第六轮（2026-09-22 日间，起因 = W7 提的两件事） | 代码：新建 `eval/pg_guard.py`（98 行，服务端只读闸门 + 故意写一次的自证 + DSN 脱敏）；`eval/reporter.py` +`pg_surface()`（从日志取证接触面）与 `_redact()`（四个出口一律过；⚠️ 修掉 `\b` 导致真日志上恒返空）；`eval/gates.py` +`_pg_surface_notes()`（红不红都声明；共享 schema 命中额外 ⚠️；⚠️ 修掉按固定词数切对象名）；`_probe_pg_real.py` / `_probe_parallel_states.py` 两条 DSN 一律过 `force_readonly()` 并把闸门自证写进产物。<br>测试 +16 → **334**（`backend/tests/eval/test_pg_contact_surface.py`，全离线）；其中两条**先红后绿**，各自抓出上面那个 bug。<br>**验证（全实测）**：`pytest tests/eval -q` → **334 passed / 15.56s**；`cd backend && PYTHONUTF8=1 pytest -q -rfEs` → **0 failed / 2254 passed / 6 skipped / 3 errors / 119.76s @ `3ff31c4`（本轮 feat 提交；起点 = `82f5bdb`）**；`ruff check .` 与 `ruff check --config pyproject.toml ../backend/reports/w6` 均通过；`lint-imports` **4 kept, 0 broken**；两探针 + `probe_loadtest_receipts.py` + `probe_gate_allowlist_shape.py` + `probe_cassette_replay.py` 退出码 0；`eval/reporter.py --no-backup` 退出码 1 ⇒ **PASS 0 / FAIL 4 / PARTIAL 2 / UNVERIFIED 2 = 连续两轮零判定漂移**。<br>**接闸门时的前后对照**（防"我的准备动作改了被测状态"）：并行探针改前/改后判据字段 10 格逐格相同、串行 counts 与三条生产形状 counts 相同、worker 侧两格合计 **600,178 → 600,178** ⇒ 闸门对读数中性。<br>产物：`_probe_pg_real.json` / `_probe_parallel_states.json` 各新增 `pg_guard` 自证键；`_full_pytest_w6.log`、`eval_metrics.json`、报告与 `cassette_replay_probe.json`（仍 20/20 miss）重生成。<br>⚠️ **push 状态按 09-22 新纪律变更（`dc62468`：各窗自推）**：本轮起点 `origin/main` = 本地 HEAD = `82f5bdb` ⇒ 我推的两笔只带我自己的活，第五轮那条"不代推别人的活"的悬置问题**自动消失** |

| 第六轮 · 续（同日 16:00–16:40，起因 = W7 的追加证据） | 代码：`eval/gates.py` 的接触面声明改成**无条件带下界句**（取到清单 ≠ 只做了这些）+ 对应断言；`eval/reporter.py` §10 补 `--continue-on-collection-errors` 那条命令形状（并写明**不许**用 `--ignore/--deselect` 窄化范围）。新器件：`backend/reports/w6/probe_pg_boundary.py`（168 行，只读、走同一把 `pg_guard` 闸门；产物 `pg_boundary.json` 存快照与逐字段差值）。<br>**订正（全部指向本窗口自己）**：§4.11① 的"DDL 全部限定在测试专用 schema"与"前/后 197\|197 ⇒ 没改那张表"两句作废（§5.17–5.18），§3 G-1 行"红因全在窗外"改口（红 31 条、3 条在窗内），并登记我方覆盖了上一轮日志这件事（§5.19）。<br>**验证（全实测）**：`cd backend && PYTHONUTF8=1 pytest -q -rfEs` → **退出码 2、`Interrupted: 7 errors during collection`、零条执行**；加 `--continue-on-collection-errors` → **21 failed / 2164 passed / 6 skipped / 10 errors / 128.37s @ `d367287`**；`pytest tests/eval -q` → **4 failed / 330 passed / 18.94s**：其中 **1 条是我方自己的守卫抓到我写错命令**（`test_reproduce_commands_are_runnable_paths` 要求每条复算命令带 `PYTHONIOENCODING=utf-8`，我新加的那行只写了 `PYTHONUTF8=1` ⇒ 已补，**没有去改那条测试**）；另 **3 条 = 适配层到期哨兵按设计响**（§4.12⑥，不弱化、不 skip）；边界签名两次差值均 `[]`；`eval/reporter.py --no-backup` 判定集合不变。 |
| 第七轮（同日 17:0x，删适配层） | `feat(w6)`：`eval/harness.py` / `eval/redteam_eval.py` 四处适配符号整体删除 + `eval/runner.py`、`conftest.py` 消费点改调端口 `guard_allowlist`；`eval/reporter.py` 的 `gate2_visible_raise` → `gate2_on_port_raise`；`backend/reports/w6/probe_gate_rejections.py` / `probe_rule_identity.py` 修 ImportError。<br>`test(w6)`：`tests/eval/test_harness_allowlist.py` 到期哨兵反转成回归哨兵 `test_the_adapter_symbols_stay_dead`（AST 扫描器未动）+ `test_redteam_logic.py` §六 两条结构面测试改判为生产端口正照。<br>`docs(w6)`：DELIVERY §4.13 / §5.20–5.22 / §6 / §7 / §8-14·16·17；RELAY §三 C5·C6、§八 P14、§十-12；产物 `redteam_results.json`（重录）、`_redteam_before_c76f701.json`（对照件）、`pg_boundary.json`（四组快照 + 差值）、`eval_metrics.json`、`评测报告与门禁判定.md`。**不含 `*.log`**（`.gitignore:47`） |

**不入版本库**：
`eval/results_replay_probe.json`（中途探针临时产物，已被 `results_v1.json` 取代）、`eval/*.bak-*`、`backend/reports/w6/*.bak-*`、
`backend/reports/w6/*.log`（`.gitignore:47`，见 A9）、本轮的前后对照临时件 `_parallel_runA.tmp.json` 与 `_pg_before.tmp.json`（**用完即删，不入库**）、
`__pycache__/`（含 `backend/reports/w6/__pycache__/`）、以及**他人归属**的三处工作区改动：`backend/reports/w2-int/e2e_stage2_check.py`（已被别方修改，本窗口未碰）、`backend/reports/arch/`、`backend/reports/w7/PROMPT.md`。

---

## 8. 还没做 / 做不到（下一轮的真实起点）

1. **146/166 条未真打**（D1 裁定：先冒烟）。全量 ≈¥0.27 / 769k tokens，需要额度授权。
2. **G-8 需要第二轮回路**（W6 自己的缺口）：`runner.py` 要能把 `clarify` 的补答喂回去再走一次。
3. **§C.4.3 的裁决**：gold 补 `default_predicates` 重冻结，还是宣布语义包口径权威 —— 待 W1A + 架构。
4. **PG 并行少算：已复现 + 成因已定位 = `RESET` 留下的占位符 GUC 不随并行 worker 传值**（§4.8；上一版这条写"机制未定"，并把我"排除 worker 没拿到 GUC"的那条对照当成了证据 —— 那条对照本身是**提升性伪影**，见 §5.8）。判据已常驻在"四形态 × 真串行/真并行 + `Workers Launched ≥ 1`"上，本轮 `parallel_equality_ok` 仍为 **false**（`v_order_paid/reset_placeholder`）。剩下三件：① **修法**待架构裁（RELAY A11 三选一：PG 轮强制串行 / 把并行等值定为接 PG 的硬门 / 宣布占位符形态不受支持并禁 `RESET`）—— 策略文本与 PG 配置都不归本窗口，我方不代修；② §8-5 那条"接 PG 执行链"必须把这条判据当**前置门**：不等值就不许进分母；③ 适配器要断言"事务内设两把 GUC 且当批生效"—— 我实测到**提交后复用同一把连接**会让事务级值消失、只剩占位符 ⇒ 恒 0 行（fail-closed，但 0 行极易被误读成"模型没查到东西"）。
5. **G-4 的"应用链走 PG"那一半**：数据已到位、**策略本身已实测有效**（§4.4），但评测主链路仍走 SQLite TEMP VIEW。下一步是把 `PgSqlExecutor` + 两个 GUC 接进跑批，并把探针的 `rls_partition_ok` 接成 `cross_tenant.pg_rls_verified` 的证据 —— 现在那一格仍写"未在真实 DB 层验证"，**故意不提前吃这条绿灯**（判据只到"策略对原始 SQL 阅读器有效"，不等于"我们的执行链在 PG 上隔离正确"）。
6. **红队四桶分歧**：终态形状 / rule_id 归因 / truncated 可观测性 / 用例前提与语义包不相容 —— 分属 W1A·W2C·W2D·W4（RELAY §二/§三/§五/§六）。
7. `eval/` 不在 CI 的 lint / import-linter 范围内（都在 `backend/` 下跑）⇒ 本窗口的边界契约靠自己的测试兜底，建议架构给 `eval/` 一个正式契约（RELAY A7 / O3）。
8. **G-6 的分母定义**（A10）：§17.3 没写"被限流的请求算不进 P95"还是"算"。本窗口采取"有全请求数就用全请求、只有准入口径就不判 PASS"，等架构定死后再收紧（注意 W7 已证"含 429 不一定更严"，见 §4.6）。
9. **产物里的绝对路径**：`eval_metrics.json` 的 `meta.run_config`（来自 `runner.py` 落盘）与 `consistency_17_6.…artifacts.paths` 仍是本机绝对路径。报告正文已改仓库相对（`reporter._rel()`），下一轮把这两处也换成 `_rel()`，并**重录**这两个产物。同一个 `meta.run_config` 还带着**跑批当时**的超时表快照（形状已被 U-104/U-107 换掉，见 §4.7）⇒ 本轮先在报告 §0 点名差异（`timeout_snapshot_drift`），要根治仍得重录产物。
10. ★ **匣带重录（§C.6.1 纪律二今天的唯一恢复动作）**：`w6_batch.jsonl` 的 48 个指纹对当前出站报文 **20/20 miss**（上游 `fbae176` 把指标口径枚举器接进语义摘要）。⇒ 报告里所有回放读数（G-2/G-5/G-7/G-8 的分母）**今天不可零成本复算**。要恢复只有两条：**(a)** 重录 20 题（≈ ¥0.033，需授权）；**(b)** 接受这批读数只到 09-20 为止。本窗口**没有自行真打**（§17.2 禁止评测静默回退网络），并已把该事实落进报告 §8 与 §4.3。
11. **删评测侧适配层：今天已到期一半**（第五轮订正）。四处：`AssetAllowlistView` / `GuardAllowlistBundle` / `StructuralAllowlistBundle` / `structural_wrapper`。**实测状态**：W4 `357618f` 让 `app/graph/nodes/gate1_ast.py:56` 改调 `guard_allowlist` ⇒ **gate1 那半边视图的存在理由已消失**；只剩 `app/guard/policy_gate.py:105` 仍读扁平面（RELAY P8 那两件事）。⚠️ 上一版那句"等两边都改完会变红"的**并集哨兵对这一半没有任何反应** ⇒ 机制已换两层：`test_the_dual_shape_view_dies_with_the_consumer_fix` **按文件**判（逐文件读数进消息）+ `test_the_adapters_stated_reason_list_matches_the_code` 双向核对 `harness.py` §三 那行机器可读清单。**默认方案**：等 P8 落地**一次删净**（理由：同一代理类改两遍要做两次漂移对照，而红队产物每改一次都得重取逐字节比对）；**代价**：双形状视图多活一轮，且评测侧 gate1 路径仍经过一层本可不要的转发（该转发已被 `test_view_forwards_the_port_output_verbatim` 钉成"逐键等于端口"，不是第三份真相）。要提前删只需总控说一声。**不靠注释传承。**
12. ★ **"不可引用清单"（第五轮，交给 W7 汇总 / 架构知悉）**：`deploy/loadtest/` 里 **14 个 `g6_p95_le_8s = true`** 的历史格（分布在 **11 个文件**：`baseline_c5.json` 1、`receipt.json` 4、其余 9 份各 1）**一律不得进任何延迟读数**。它们不可引用的理由不是"值算错了"，而是**分母无从核对**——这 11 份**全部没有 `admission` 字段**（U-106 之前的形状），而 W7 的 U-120 三态只约束**今后**的写端，回改不动历史格（架构已裁"不回写"，本窗口尊重该裁定、也不代改）。我方侧的兜底已落三件：① 读端从不依赖那个布尔（`test_the_reader_never_depends_on_w7s_g6_boolean` 三值参数化钉死）；② G-6 降档规则堵住"分母不明却判 PASS"（实测被拦下的正是 `baseline_c5.json`，见 §4.10③）；③ 探针产物 `probe_loadtest_receipts.json` 自带 `stale_true_cells_total` / `null_caveat_scenarios_total` 两个计数，谁都能自己数，不用信转述。**仍残留的风险**（说清楚，别让这条清单看起来像已被解决）：任何人直接 `cat` 那份 JSON 仍会读到一个绿色的 `true`，评测侧的降档管不到目录外的读者 ⇒ 若要有约束力，需由架构决定是否在 `07`/`08` 里挂一条"历史压测回执的布尔位不得作为门禁证据引用"。
13. ★ **只读闸门今天只覆盖"我方自己的 PG 会话"，不覆盖全仓**（第六轮）：`eval/pg_guard.py` 已接 `_probe_pg_real.py` 与 `_probe_parallel_states.py`（两份产物各带 `pg_guard` 自证键），但**集成夹具的连接装配在 W0/W2B 侧**（`tests/integration/test_retrieval_fts_pg.py:69` 的 `TEST_DSN = RETRIEVAL_TEST_PG_DSN or PROD_DSN`）⇒ "没有任何进程能对共享 `ecom` 写"这句话**今天仍不成立**，已作为 **O7** 提给 W0/W2B（含两条出路，默认：未设专用测试 DSN 时整文件 skip）。我方能做且已做的两件事如实报边界：① 每次"全量"读数自带接触面（`pg_surface`）；② 我方探针的每条会话都被服务端拒过一次写请求。下一步：§8-5 把 PG 执行链接进 `runner.py` 时，`force_readonly()` 是**前置条件而不是可选项**（同 RELAY §十-6b 三条硬要求）。
    ⚠️ **本条已被同日续轮两次改写**：① 默认方案从"skip"改成 **fail**（W0 的 U-114 判据明写"缺 env 必须 fail/error，禁止 skip"，我方原提案与之冲突 ⇒ 已撤回）；② W0 防线② `36c782a` 与 W2A 防线① `5e47558` 已落 ⇒ 剩余面收窄成**只剩** `test_retrieval_fts_pg.py::_dsn_from_env_file()` 那条运行时回退（W0 的静态守卫自己声明覆盖不到它）。详见 RELAY O7 更新。
14. ✅ **适配层已整体删除**（同日第七轮做完，原「下一轮第一件事」提前收口）：四处符号 + §三 那行「存在理由」清单一起消失，消费点全部改调端口 `guard_allowlist`；三条到期哨兵**未 skip、未删断言**，反转成回归哨兵（判据与实测见 §4.13）。**残留的一条口径**：`app/core/contracts.py:423/425` 的 docstring 仍写着「`run_gate2` 今天调的是 `asset_allowlist`」并点名 `AssetAllowlistView` / `build_guard_allowlist` 为「存在理由」⇒ 那句话现在**是错的**，属 W0 只读面，已作为 RELAY §十一 订正请求上呈（我方不动笔）
15. **G-1 的取数形状从此带一条环境依赖**（第六轮·续）：U-114 防线①之后，本机 `cd backend && pytest -q -rfEs` **整轮中断**（7 条 import 期 `env_dsn()` 抛错、退出码 2、零条执行）⇒ 我方改用 `--continue-on-collection-errors` 保住同一收集面，代价是 G-1 的 error 数里**长期混着 7 条"本机缺 env"**（与 O6 那 3 条夹具 error 不同源）。要根治只有 RELAY O7 出路②：**给一次性测试库并把三个 env 写进本地/CI 约定**。已作为 A13 请架构裁"本地无 env 时全量这一格该报什么"（我方默认：照报，且把"来自环境"的 error 单独点名，不折算成被测系统失败）。
16. **报告 §10 的复算命令「存在」不等于「能跑」**（本轮实测到的假安全）：`test_reproduce_commands_are_runnable_paths` 只查路径，两条探针因此带着 ImportError 绿了一整轮。下一轮要加一条**真跑**的测试（子集 = 离线、不连 PG 的那几条：`probe_rule_identity`、`probe_gate_rejections`、`probe_gate_allowlist_shape`、`probe_cassette_replay`、`probe_loadtest_receipts`），并把「跑不通就红」写进判据。**代价**：这几条各约 1–3s，且 `probe_cassette_replay` 会读匣带（不联网，安全）。
17. **匣带仍然 20/20 miss**（本轮未重录 = 未拿到授权）：G-2/G-5/G-7/G-8 的回放读数只能沿用上一轮产物 + 本报告的 UNVERIFIED/FAIL 口径。重录需真打（20 题 ≈ ¥0.033、166 题 ≈ ¥0.27），**评测侧绝不偷偷回退网络**；开工第一件事照旧是跑 `probe_cassette_replay.py` 看命中率。
