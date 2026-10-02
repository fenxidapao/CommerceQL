# 集成收尾窗（W8）· RELAY

> 本窗唯一写者 = W8。只追加、不改历史文本；订正写在最新段并 🔻 具名失效。
> 报数固定五件：**数 ＋ 面 ＋ 谓词 ＋ 分母 ＋ 粒度**；三态 ＋ `UNVERIFIED`；未跑的一律写 `UNVERIFIED`。
> 纪律：不落题面、不落 SQL 结果行、不落任何凭据值（只报文件数／行号／布尔／长度）。

## §一 第 1 轮（2026-10-02 19:1x–19:3x +0800 ｜ 起始 HEAD `f485ffe` ｜ 零额度 · 零跑批 · 未动共享栈 · 未起停容器）

### 1. 开工必读（本窗 `PROMPT.md` §1 的六步）已读完，现读坐标如下

| 件 | 现读（尺 ＋ 结果） | 时刻 |
|---|---|---|
| `OVERVIEW.md`（项目根、不在 git） | 读全 281 行 ｜ 取证行自称 HEAD `d440ed6`、`07 = v1.7.18`、下一可用号 `U-135` ⇒ **HEAD 一项已被推翻**（见 §2） | 19:1x |
| `reports/arch/HANDOVER.md` | 读全：`§7.1` 硬纪律 **29 条**（血案全表）、`§9` 状态表、`§11` 五类错、`§13` checklist | 19:1x |
| `reports/qa/TASK_BOARD.md` | 读全（399 行）：T-01…T-20 ＋ 档位 A 队列 ＋ §九 体制变更 | 19:2x |
| `reports/qa/COMPLETENESS.md` ＋ `GATE_LOG.md` ＋ `QA_LEDGER.md` ＋ `RELAY.md` | 读全：完成度三表、门禁命令形状、判据级台账、QA 四轮复算与自曝 | 19:2x |
| `docs/07_技术设计文档_TDD.md` | `wc -l` **3,642** ／ 783,220 字节 ／ 第 11 行「文档版本 = **v1.7.18**」；尺 = `awk NR 与 length 逐行量` | 19:2x |
| ├ §4.8 缺陷登记 | 起 **L1073**；登记表 4 格；**取号行 = L1078「下一个可用号 = `U-135`」**（裸串「下一个可用号」在多行出现 ⇒ 必须带行首形状 `^> \*\*下一个可用号 = `） | 同上 |
| ├ 本轮要用的六行 | `U-114` **L1134** ／ `U-121` **L1141** ／ `U-123` **L1143** ／ `U-129` **L1155**（单行 18,904 字节）／ `U-130` **L1157** ／ `U-131` **L1159** ／ `U-133` **L1163** ／ `U-134` **L1165** | 同上 |
| ├ §12.2 `embed_doc` 与 `'*'` 哨兵 | 节起 **L2472**，契约行 **L2492**（505 字节）：`'*'` = 公共语义包派生行哨兵、检索过滤 `tenant_id IN ('*', :ctx_tenant)`、**Gold Query 行的 `tenant_id` 永远非 `'*'`** | 同上 |
| ├ §13.3 RLS／身份 GUC | 节起 **L2659**；三个硬前提表 **L2711–2713**；三个行为细节 **L2719–2722** ⇒ 细节 1 =「缺省 GUC = 失败关闭」；细节 2 =「空串 = 不限店铺，但只约束注入侧」；**细节 4 =「禁止在策略里把未设 coalesce 成空串」**（会把 fail-closed 翻成 fail-open），并记 RESET 后占位符 = `''` 的二义与 P1 换 `'*'` 哨兵的裁定 | 同上 |
| ├ §16.5 压测与验收口径 | 节起 **L3157**；场景行 **L3161**（5 个）；必测断言行 **L3164**（6 条，分母词汇 `admitted`／`terminal`／`limiter_passed` 三母不得并读）；配额档 **L3168**；可触发性前置 **L3169**（含单价按 `is_peak` 分档、乘数 = 进图条数、跑批前必须核 openapi 含 `/api/v1/query`） | 同上 |
| ├ §17.3 闸门 ＋ §17.4 诚实声明表 | §17.3 起 **L3268**，G-1…G-8 行 = **L3272–3279**，裁定句 **L3281**「落地判定以本表 8 条为准」；§17.4 起 **L3283**、正文警示 **L3293**「这张表必须出现在评测报告里」 | 同上 |
| `docs/08_编程实施计划…md` | 第 11 行「文档版本 = **v1.4.1**」；§4.1 归属表 = **L280–309**（`deploy/**` = W7、`eval/**` 执行器 = W6、`tests/integration/**` = 随被测模块、`backend/reports/**` = 各窗自本子目录）；§6.4／6.5／6.6 在 **L401／L414／L428** | 19:2x |

🔻 **同轮具名失效（对本窗 `PROMPT.md` §5 的两处）**：它写「`07` §17.3 闸门 = :3267–3274」「@ `304d37a`」⇒ 本窗现读 = **G 行 :3272–3279**、起始 HEAD = **`f485ffe`**（W8 提示词本身已入库）。⇒ 本窗今后引行号一律现读，不抄提示词与旧窗快照。

### 2. 开工五查（现测）

| 查项 | 读数（含面与谓词） | 判定 |
|---|---|---|
| 本地／远端 | `git rev-parse --short HEAD` = `f485ffe`；`git ls-remote origin main` = `f485ffe6ce02…` ⇒ **同点** | 通过 |
| 工作副本 | `git status --porcelain` = **1 行 M ＋ 3 行 ??**：`M deploy/loadtest/r23_thread_from_checkpoints.sql`（= W7 在途）、`?? backend/reports/w6/_full_pytest_0929.rev`、`?? eval/results_replay_probe.json`、`?? backend/生成：2026-09-16`（0 字节，全角冒号） | 登记，未跟踪件一律未动 |
| 容器面（两面并报） | **running 面 = 4**（`commerceql-{pg,api,redis,pgbouncer}-1`，Up 6 h，pg／api／redis healthy）；**`docker ps -a` 全列面 = 9**（另含 3 个本项目残留 ＋ **2 个非本项目容器 `coursrag-api`／`feynmantutor`**）；残留逐对象标面：`w7load-api_pre0930r11_bak` = 镜像 **`w7load-api:0928r10`**（pre-fix，Exited 255）、`cql-it-pg-t02` = **Created**、`cql-it-pg-w2b-t02` = Exited(0) | 保留，未起停未改名未删 |
| 花费口径 | 面 = `app.cost_ledger` 全库、粒度 = 行：`count(*)` = **1,601**、`round(sum(cost_cny),6)` = **¥2.635700**、`max(created_at)` = **2026-10-01T12:56:32.538701+00** ⇒ 与 QA 第 1／2 轮逐字同 ⇒ **10-02 全项目仍零新增**；本窗零花费 | 通过 |
| 被测构建 ≠ 运行容器 | 未在本轮引用任何活体读数（`commerceql-api-1` 装的是 `commerceql-api` 镜像，非被测构建） | 回避 |

### 3. 🔴 §5「接手第一件事」的处置 = **续写并入库**（不是还原、不是交回）

**盘面**：`deploy/loadtest/r23_thread_from_checkpoints.sql` 工作副本比入库版多 8 行（`git diff --stat` 原为 ＋10／－2），该件上一笔 = W7 `0a236ec` ⇒ W7 正在做 **T-12 的 W7 半边**（给以 `channel='terminal'` 写行当「本轮自写终态」证据的谓词加 `__start__` 排除）。

**处置三问，逐问实测**：

1. **它做对了吗** —— 方向对且必须做：`split_part(task_path, ', ', 2) = '__start__'` 的 terminal 写行 = **6 行／3 个 thread**（面 = `lg.checkpoint_writes`，谓词 = `channel='terminal'`，分母 = 全库 825 行，粒度 = 行；现测 19:3x），且 ts 全部落在 **2026-10-01T12:55:28Z–12:56:27Z** ⇒ 它们是 W4 入口复位修法（`RUN_SCOPED_STATE_FIELDS` 含 `terminal`）留下的**入口写行**，不排就是「本轮自己写了终态」的冒充路径。
2. **它的形状稳吗** —— 不稳。W7 写的是 `task_path not like '%__start__%'`，而 **LIKE 里 `_` 是单字符通配** ⇒ 该式实际是「任意两字符 + `start` + 任意两字符」，**过宽**：将来任何名字含 `start` 的节点（如 `*_start_idx`）会把**真**终态写一起排掉 ⇒ 伤 `格3`（`t2_with_terminal_write`），方向是假红。现测两式**同集合**（`like` 命中 6／`split_part` 命中 6／两个方向的集合差均 **0**／`task_path is null` 的 terminal 行 **0**）⇒ 换成与 T-12 文本同形的精确式**不改动任何读数**。
3. **覆盖面只有这三处吗** —— **不是**。全仓现读（尺 = `git grep -nE "channel *= *'terminal'" HEAD -- '*.sql' '*.py'`，落笔秒复算）：**run 级「自写终态」证据谓词共 8 处**，W7 只改了 3 处。

| 件 | run 级 `terminal` 谓词处数 | W7 在途是否改到 | 本窗处置 |
|---|---|---|---|
| `deploy/loadtest/r23_thread_from_checkpoints.sql` | **3**（⑯ 的 `wrote_terminal`、⑯b 的 `term_runs` 连接条件、⑰ 的 `wrote_terminal`） | 是 | 续写 ＋ 换精确式 |
| `backend/reports/w4/probe_prod_checkpoint_terminal.sql` | **4**（⑥ L152→157、⑦ L184→189、⑧ L215→220、⑨ L248→253，均 `bool_or(w.channel = 'terminal')`） | **否 ⇒ 漏** | 同规则补齐 ＋ 就地注记 |
| `backend/reports/w6/probe_audit_invariant.py` | **1**（`TERMINAL_RUN_TKS_SQL`，L506→516；它在 `:1433` 喂 `terminal_writes_on_runs`／`terminal_writes_at_turn2plus` ⇒ 正是 run 级「自写终态」证据） | **否 ⇒ 漏** | 同规则补齐 ＋ 就地注记 |
| 同类但**不在射程**（理由写进件里，防下一轮误读成"漏改"） | `r23:248` 与 `w4:29/136/139` ＝ **blobs 面／行级普查**；`w6:465–474`、`w6:485–503` ＝ **行级与 thread 级普查**（切不出 run 边界）；`tests/contract/test_audit_terminal_pairing_contract.py:147` ＝ docstring | — | **未动** |

**A/B 对照（同参、只换谓词；这是"加排除不推翻历史读数"那句话的全部凭据）**：

| 对照 | 命令形状（cwd 与解释器写全） | 真 rc | 结果 |
|---|---|---|---|
| r23 三版：HEAD 无排除 ／ W7 的 like 式 ／ 本窗的 split 式 | `cd CommerceQL` ⇒ `docker exec -i commerceql-pg-1 psql -U postgres -d ecom -v "win_a=2020-01-01 00:00:00+00" -v "win_b=2120-01-01 00:00:00+00" -v "upref=%" -f - < 该件`（**值里绝不再套单引号**，套两层会静默 0 行 —— 本窗第一轮就踩过一次，见 §6） | 均 **0** | 142 行输出**逐字节同**；唯一差异 = `⑭c 读数年龄` 的随秒列（81,283.5 → 81,290.2 → 81,460.2 s）⇒ **不是判据差，是秒差** |
| W4 探针两版：HEAD ／ 本窗 | 同形状，件 = `backend/reports/w4/probe_prod_checkpoint_terminal.sql`（无 psql 变量） | 均 **0** | 101 行输出仅 `UNION ALL` 的**行序**差（`branch_to_node_kinds` 位置变、值 22 不变） |
| 门禁回归 | `cd CommerceQL/backend` ⇒ `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m ruff check --config pyproject.toml .` ＋ 同解释器 `-m py_compile reports/w6/probe_audit_invariant.py` | 均 **0** | ruff **All checks passed（0 条）**；py_compile 通过 ⇒ 未给 `tests`／lint 面新增红 |

**入库**：`27c3e08`（`fix(w8/t12)`，3 个文件 ＋29/−7，`git show --stat` 复核归属 = 只含本窗动的三件）。落盘指纹（现算，非凭手感）：`r23` CR=0／631 行／md5 `4de72298577e`；`w4 探针` **CR=331（工作副本全 CRLF）**／331 行／md5_raw `84544403c07b`、md5(LF 归一) `1029dc20271c` ⇒ 入库时由 `.gitattributes` 归一为 LF，**两把尺都写、别只引一个**；`w6 探针` CR=0／1,694 行／md5 `2ea1492bde14`。

### 4. 本轮把 `U-129` 三格的当期读数一并量了（零额度、只读；粒度 = run）

作用域 = **全库宽窗**（`win_a=2020-01-01`／`win_b=2120-01-01`／`upref=%`），面 = `lg.checkpoints` × `lg.checkpoint_writes` × `app.audit_log`：

| 格 | 读数 | 判定（三态） |
|---|---|---|
| `⑮` 两臂（臂1 = `turn≥2` 且审计行 0；臂2 = 行 >1） | runs_in_scope **1,384**／`t2_runs` **64**／臂1 **13**／臂2 **0**／`max_rows_per_t2_run` 1／`scope_empty` f | **未达成**（臂1 = 13 ⇒ 与 `U-130` 登记的 13 条逐字同，属 **pre-fix 历史**） |
| `⑯` 写面可行性 | `t2_with_terminal_write` **3**／`t2_routed_audit_supp` **6**／`t2_routed_terminal_exit` **51**／`crash_t2_routed_audit_supp` **5**／`t2_runs_no_write_face` **0**／`max_routes_per_run` **15** | — |
| `⑯b` terminal 写的 run 归属 | `turn_of_terminal_write` = 1 ⇒ **816** run／= 2 ⇒ **3** run | 「逐 thread 恒 1 次」形状**已被现测替掉**：写面出现 `turn≥2` 的自写终态行 **3** 条 |
| `⑰` 格2／格3 | `ge2_routed_supp_no_terminal_write` **5**／`ge3_t2_with_terminal_write` **3**／第四件前置 `t2_routed_supp` **6**（>0 ⇒ 非空真）／`scope_empty` f | 格3 **达成**；**格2 未达成，但必须点名这是作用域问题**：全库宽窗把 `u_b*`／`u_f*` 的 pre-fix 崩臂算进来了 ⇒ **不得读成"修法回归"**，修法后的验收窗要按新前缀 ＋ 新时间窗限定（`U-129` 行末「验收读数按新前缀 + 新时间窗限定」同源） |

`⑰b` 路由行归属形状：route_rows **8,554**／tk_checkpoint_rows **10,760**／tk_runs **1,384**／route_unmatched_rows **1,321**／route_unmatched_threads **1,321**／unmatched_before_first_tk **1,320**／at_or_after **0**／threads_with_late_unmatched **0**。

### 5. 上呈（不自行裁，交总控转架构）

- **P-1｜T-12 的覆盖面事实**：判据的引用规则文本目前只覆盖 `deploy/loadtest/r23_*.sql` 一件，而同类形状在 `reports/w4`／`reports/w6` 两件的探针里另有 5 处。**本窗已按既有裁定文（"凡以 `terminal` 写行当本轮自写终态证据的谓词"）执行完毕，不改任何判据措辞**；请裁的是：**`U-129` 行的引用规则是否升成一句全仓规则**（否则下一件新探针照样漏）。归架构。
- **P-2｜DoD④ 的承诺面归属**（T-19 的前置，尚未开做）：`.gitleaks.toml:82` 那句承诺是「任何受版本控制的文件里出现属主口令 DSN 都必须红」，而门规则只吃 `+psycopg` 形状 ⇒ **是"改门"还是"改那句话"**，后者 = 判据变更。归架构 ＋ 总控。
- **P-3｜`U-133` 判据② 的两支拆分已被本窗现读确认**（存量治理归 `U-134`；`U-133` 只对 `load_synth_to_pg.py` 的字面默认串与运行期 DSN 来源负责）⇒ T-09 剩余面（①②，原 W7 面）**本窗接着做**，不需重裁。

### 6. 本窗自曝（第一轮就踩的，写在这里不在别处悄悄改）

- 第一次跑 r23 时按 shell 习惯写成 `-v win_a="'2020-01-01 00:00:00+00'"`（**值里套了两层单引号**）⇒ `⑮/⑯/⑰` 的 `runs_in_scope` 静默报 **0**、`scope_empty = t`，而 **rc=0、无任何报错**。这个件的第一行注释本来就警告过（"套两层会静默 0 行"）。⇒ 固化：**读数为 0 先问"有没有给被看见的条件"**，并当场用同一查询里的分子分母反推（本例 `⑰b` 的 1,384 run 与 `⑮` 的 0 相矛盾 ⇒ 立刻暴露）。第二遍改对参数后才有 §4 那组数。
- 本轮**未**跑任何 pytest 全树计数 ⇒ 目录级 passed 数本窗无当期读数（引则须带 HEAD ＋ 尺，见 `GATE_LOG.md`）。

### 7. 下一步（本窗任务池顺序，供总控转发／排期）

1. **T-19**（先数不改）：把 DoD④ 规则扩到吃纯 `postgresql://` 时，`gitleaks` 与本门会一次性点红几条、落在哪几个文件 —— 本窗自己现读，不复用 QA 的 61／24／37／35。
2. **T-20**：`embed_doc` 的 gold_query 哨兵不变式补一条断言（写入侧或只读行为侧，二选一）。
3. **T-09 剩余面**（原 W7）：`load_synth_to_pg.py` 的默认 DSN 改 `None` ＋ 缺 env 具名 fail ＋ "不传 `--dsn` 时 TRUNCATE 路径不可达"的负向用例。
4. **T-16** → **T-11①②** → **T-17** → **T-18** → **A5**。

### 8. 可并发／必须串行（本轮刷新）

| 动作 | 结论 | 理由 |
|---|---|---|
| 只读 psql 探针（`lg.*`／`app.cost_ledger`／`pg_*` 目录） | **可并发**（与架构窗、QA 窗同时跑） | 零写、零额度、不动共享栈 |
| 改 `deploy/**`、`backend/reports/**`（本轮三件） | **可并发**（同一时间只有 W8 一个写者 ⇒ 无单写者争用） | 体制变更 |
| 全树 pytest ＋ 一次性容器（T-16、T-20、T-11②） | **本窗内串行、与 QA 并发需报备** | 新容器名与端口要现读 `docker ps -a` 防撞；禁共享 `ecom` |
| 任何要额度的批（评测重跑／五场景／T-15） | **必须串行 ＋ 需总控批** | `LLM_SEMAPHORE_FLASH` 贴顶；共享栈单写者 |
| A5（compose 加 `host_ip`） | **必须挑无他窗在跑的时点 ＋ 需批** | 要重建 4 个共享容器 = 挤停全栈 |
