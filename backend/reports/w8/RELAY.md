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

## §二 第 2 轮（2026-10-02 19:4x–20:0x +0800 ｜ 起始 HEAD `c7cf34a` ｜ 零额度 · 零跑批 · 未动共享栈 · 未起停容器）

### 1. QA 第 2 轮三条账面订正 —— 逐条接受，并各带一条现读凭据

| # | QA 指出 | 本窗处置 | 现读凭据 |
|---|---|---|---|
| (a) | r23 第二处排除式在 **539** 不是 538 | **接受**，`grep -n` 复现 | `deploy/loadtest/r23_thread_from_checkpoints.sql` 的三处 = **491／539／577**（538 是 join 的起始行，排除式在 539）；另 `w4:157/189/220/253`、`w6:516` ⇒ **8 处行号全部现读复述** |
| (b) | 「142 行输出逐字节同」**缺 psql 输出格式这一面** | **接受**，本轮起**两面并报** | 面 1 = psql **默认对齐格式**：HEAD 版 155 行 ／ 本轮版 175 行（含表头与分隔行）；面 2 = `-t -A` **非空行**：**HEAD 51 行 ／ 本轮 63 行**（51 ＋ `⑰c` 的 11 行 ＋ `⑱` 的 1 行 = 63 ⇒ 闭合）⇒ **QA 那把 51 与本窗的 HEAD-51 同尺对上**；「逐字节同」那句只在**面 1 ＋ 三版互 diff**这个限定下成立，已在 §一 就地作废（🔻 失效时刻 = 本轮） |
| (c) | 停用「docs=c7cf34a」这种记法 | **接受** | `docs/**` 在本项目 = **保留且不在 git 的契约路径**；凡指提交一律写「提交 `c7cf34a`」。**本窗至今未写 `docs/**` 一行**（`git -C docs rev-parse` 仍 fatal） |

### 2. 格2 的三态 —— **接受 QA 的方向，并按本窗自己的尺复算**

- 尺 A（**按修法时刻**，边界 = `33675b9` 落地 `2026-09-30T14:25:35+00`，run 首见 ts 与它比）：`pre_fix` = t2_runs **61**／`t2_routed_supp` **5**／**格2 = 5**／格3 = 0；`post_fix` = **3**／**1**／**格2 = 0**／格3 = **3**。
- 尺 B（**按日**，即 QA 第 2 轮那把尺的近似）：`2026-09-29` = 38／5／**5**／0；`2026-10-01` = 3／1／**0**／3；其余各日 t2_runs 合计 23 条而 `t2_routed_supp` 全 0（09-19 15、09-28 8、09-22/23/20/21/16 各 0）。
- **对表结论**：尺 A 与尺 B **同域同值**（09-30 全天零 run ⇒ 日期代理这一次没与构建身份打架），且与 QA 的方向一致 ⇒ 本窗 §一.4 那句「格2 = 5 ⇒ 未达成」**就地作废**，正解 = **`n/a`（该作用域不含可判样本，5 条全是修法前存量）**；`post_fix` 域 **格2 = 0 可当验收位，但 n = 1**（只 1 条被路由进 `audit_supp`）⇒ **不得升格成率**。
- ⚠️ 两把尺都是**日期代理 ≠ 构建身份**（QA 已点名）。严格分域的前置 = **T-11②**（闸门输入产物自报 `self_reported_rev`）⇒ **本窗接受 QA 的意见，把 T-11② 从尾账升为第 3 轮正式项**；在此之前所有分域读数的标签只许写 `date_proxy__…`。

### 3. T-21（新单，零额度）= 已落地：全仓**唯一一处**形状守卫 `r23` 的 **⑱**

- 守的东西：`split_part(task_path, ', ', 2) <> '__start__'` 的正当性依赖两条约定，**若变两个方向都是假绿** —— 守卫 1：不含 `', '` 的 terminal 行必须 0（否则 `split_part` 返空串 ⇒ `'' <> '__start__'` 恒真 ⇒ 入口复位写行被算成"本轮自写终态"）；守卫 2：含字面 `__start__` 但不在第 2 段的必须 0（否则漏排）。
- 现测（`cd CommerceQL` ＋ `docker exec -i commerceql-pg-1 psql -U postgres -d ecom -t -A -F '|' -f - < deploy/loadtest/r23_thread_from_checkpoints.sql`，rc=0、0 条 ERROR，19:5x）：`terminal_rows` **825**／`g1_no_delim__want_0` **0**／`g2_start_outside_seg2__want_0` **0**／`start_rows_excluded` **6**／`seg2_node_kinds` **8**／`shape_ok` **t**。
- 🔴 **QA 那条提醒已被本窗现测坐实并写进件里**：`__start__` 那 6 行的 `type` 存的是**字符串 `'null'`** —— `type = 'null'::text` 命中 **6**、`type is null` 命中 **0**；自证法 = `select null::text, 'null'`（`-t -A` 下真 NULL 显示为**空**，所以印出来的 `null` 是值）。⇒ **不得拿 `type is not null` 当挡**。
- 只放一处的理由：8 处共享同一条约定 ⇒ 三件里各抄一份 = 造第三份真相。`w4:⑫` 与 `w6:GRID23` 的注记里只写**指针**指向 ⑱。
- 三态联动已写进件里：`shape_ok = f` ⇒ 本件 ⑮/⑯/⑯b/⑰/⑰c 的 `wrote_terminal` 系读数**一律不引用**（作废，不是重新解释）。

### 4. T-22（零额度部分）= 已落地：三处**分域并报**，标签带分域依据

| 件 | 加的东西 | 出口形状 | 现测（粒度 = run，分母 = 全库带 `tk_` 的检查点组） |
|---|---|---|---|
| `deploy/loadtest/r23_thread_from_checkpoints.sql` | 新语句 **⑰c**（两把尺同框：A 按修法时刻 ＋ B 按日）＋ `⑰` 上方一行 🔻 注 | 11 行（A 两行 ＋ B 九行） | A：`pre_fix 61/5/5/0`、`post_fix 3/1/0/3`；B：09-29 `38/5/5/0`、10-01 `3/1/0/3`，其余 `t2_routed_supp = 0` |
| `backend/reports/w4/probe_prod_checkpoint_terminal.sql` | 新语句 **⑫**（列尾带 `domain_ruler = date_proxy__33675b9@2026-09-30T14:25:35Z`）＋ 注记指向 `r23 ⑱` | 2 行 | `post_fix 3/1/0/3`、`pre_fix 61/5/5/0` ⇒ **与 ⑰c 逐字同** |
| `backend/reports/w6/probe_audit_invariant.py` | 新常量 `GRID23_BY_DOMAIN_SQL` ＋ 出口字段 `writes.grid23_by_domain`（含 `domain_ruler`、`domain_ruler_is_not`、`read_as` 三件）；**不改上面任何一格的形状** | 运行时落 JSON | SQL 单跑 rc=0 ⇒ `post_fix 3/1/0/3`、`pre_fix 61/5/5/0` ⇒ **三件同值** |
| ⑰ 本体 | **只改 verdict 文案**（`ge2 = 5 ⇒ 未达成` → `ge2 = 5 ⇒ 本行不作判（混合域）…三态只许读 ⑰c`），数值一格未动（`1384/64/5/3/6`） | — | diff 证据：与 HEAD 版输出对表，差异只有 ⑰ 文案 ＋ 新增 ⑰c/⑱ ＋ ⑭c 随秒年龄 ⇒ **属标签变更，不属判据变更**（判据措辞在 `07 §4.8`，本窗无权改） |

### 5. 本轮的门禁回归（每条带命令形状与真 rc）

| 门 | 命令形状 | 真 rc | 读数 |
|---|---|---|---|
| ruff（`backend` 整目录） | `cd CommerceQL/backend` ＋ `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m ruff check --config pyproject.toml .` | **0** | **All checks passed（0 条）** @ `c7cf34a` 之后的工作副本 |
| py_compile | 同解释器 `-m py_compile backend/reports/w6/probe_audit_invariant.py` | **0** | 通过 |
| r23 全件 | 见 §3 命令 | **0** | 0 条 ERROR；`-t -A` 面 63 非空行 |
| w4 探针全件 | `cd CommerceQL` ＋ `docker exec -i commerceql-pg-1 psql -U postgres -d ecom -f - < backend/reports/w4/probe_prod_checkpoint_terminal.sql` | **0** | 0 条 ERROR，含 ⑫ 两行 |
| 共享 `ecom` 未被写 | `select count(*) from app.embed_doc` | **0** | **197**（本轮跑前／跑后同数，U-114 残余面无新增） |
| 花费 | `select count(*), round(sum(cost_cny),6), max(created_at) from app.cost_ledger` | **0** | **1,601 ／ ¥2.635700 ／ 2026-10-01T12:56:32.538701+00** ⇒ 与 QA 两轮逐字同 ⇒ **10-02 全天仍零新增**；本窗零花费 |

### 6. 本窗自曝（第 2 轮一条，如实记）

- 🔴 **本轮我自己把 ruff 弄红过一次**：新加的 `dict(zip(grid_cols, r))` 漏 `strict=` ⇒ `B905` 一条、`rc=1`。修成 `strict=True` 后回到 0 条。这正是 `GATE_LOG.md` 里「改完必须跑门」那条的形状：**代码写完就报绿是错的**，必须跑完门再报。失效面 = 我若在红的那一版直接入库，`deploy/**` 之外的 lint 门会被本窗弄红。
- 顺带一次环境坑：在 Git Bash 里给 Windows Python 传 `/e/tmp_qoder/…` 路径 ⇒ `FileNotFoundError: \\e\\tmp_qoder\\…`（MSYS 路径不改写给 Python）。正解 = 一律写 **`E:/tmp_qoder/…`**。

### 7. 第 3 轮的路（顺序含 QA 建议，零额度优先）

**T-19（先数不改）→ T-20（gold_query `'*'` 行为断言）→ T-16（一次性容器跑 `U-123` 判据② 夹具）→ T-11②（闸门输入自报 rev，= 严格分域的前置，本轮升为正式项）→ T-09 剩余面（`load_synth_to_pg.py` 的 `U-133`①② ＋ T-18 同形清理）→ T-17／T-18 → A5（等总控给时点）**。
T-22 里"把 post-fix 的 n 从 1 抬上去"要真实流量 ⇒ **不跑**，届时按四件套（最小充分几何／进图条数／`is_peak` 档／题目深度）报总控。

### 8. 本轮落盘指纹（现算，非凭手感）

| 件 | CRLF | bare CR | LF | md5_raw | md5(LF 归一) |
|---|---|---|---|---|---|
| `deploy/loadtest/r23_thread_from_checkpoints.sql` | 0 | 0 | 695 | `ad37d1156372` | `ad37d1156372` |
| `backend/reports/w4/probe_prod_checkpoint_terminal.sql` | **359** | 0 | 359 | `49a12fc97c9c` | `4668b828d7ae` |
| `backend/reports/w6/probe_audit_invariant.py` | 0 | 0 | 1733 | `61b595ceefd3` | `61b595ceefd3` |

⚠️ `w4` 那份是**工作副本 CRLF、入库 LF**（`.gitattributes = * text=auto eol=lf`）⇒ 两个 md5 都写、引哪个必须点名面；`git status` 干净不等于字节等于 blob。

### 9. 🔻 同轮补记（推送后收尾前重读权威件 ⇒ 跟着改；时刻 = 本窗 push 之后）

- **重读结果 1**：`git log --oneline` 出现他窗新笔 **`9be42af` docs(qa): 第 8 轮**（= 本轮指令的来源件）；`docs/07` 盘上**未变**（3,642 行／783,220 字节／md5(LF) `436b06f02773`／版本字段仍 **v1.7.18**／取号行仍 L1078 = `U-135`）⇒ 本轮 §二 的句子**没有被新裁定作废**。
- **重读结果 2（QA 第 8 轮点名的一条，本窗自己复算了）**：`reports/w4/RELAY.md:1206` 那句「写行 **825** = 写过终态的 run **819** ＋ 来自 `__start__` 的 **6** 行」——**等式成立但缺面**。本窗两条独立算法现测（`cd CommerceQL` ＋ `docker exec -i commerceql-pg-1 psql -U postgres -d ecom -t -A -F '|' -c "…"`，19:5x，只读）：

| 面 | 谓词 | 读数 |
|---|---|---|
| **行** | `channel='terminal'` 全 | **825** |
| **行** | 同上 ＋ 排 `__start__` | **819** |
| **run**（`distinct tk`） | 含 `__start__` 也算 | **819** |
| **run** | 排 `__start__` | **819**（与上一行**同值 ⇒ 排除式在 run 面今日零增量**） |
| **thread**（`distinct thread_id`） | 排 `__start__` | **816** |

- ⇒ 三点结论：**①** `819` 同时是"非 `__start__` 写行数"和"写过终态的 run 数"，**同值不同义**（本项目第四种混淆形状「粒度」的加强版：光比对数值永远抓不到）；`816` 是 **thread** 面，拿 `819` 当 thread 数才是错。**②** 那 6 条 `__start__` 输入写**全部落在已有真写的 run 上** ⇒ 今日不存在"只有入口写、没有自写终态"的 run（此类 = **0**，由上面两行同值得出）⇒ ⑱ 守的是**将来**的形状，不是今日的读数。**③** 处置 = 在 `w4` 原句处加**带日期的 🔻 注记（原文不删）**，并把「一个名词三个面」的抄本一并标面；**未动 `w4` 其余任何文本**，也不改 `07`（措辞归架构，见本窗 §一.5 的 P-1）。
- **顺带复算 QA 第 8 轮的另一条**：`w4:1200` 那句「run 组 1,378 → **1,384**／turn≥2 61 → **64**」与本窗 ⑰c/⑱ 同尺同值（1,384／64）⇒ 无冲突。

## §三 第 3 轮（2026-10-02 20:1x–22:2x +0800 ｜ 起始 HEAD `4e11f64` ｜ 零额度 · 零跑批 · 未动共享栈 · 起停过一只一次性容器）

### 1. T-23（QA 第 3 轮 ②）= 把 ⑱ 的守卫从散文接成**否决位**

接线形状：在判定语句**内部**加一个与 ⑱ 逐字同源的 `shape` CTE（`g1`／`g2` 两条约定 ＋ `shape_ok = (g1 = 0 and g2 = 0)`），
并把 verdict 的**第一支**改成 `case when not shape.shape_ok then '不可判__shape_guard_failed（…）'` ⇒ 守卫翻 ⇒ 判定词自动降，
不需要下一位"记得先去跑 ⑱"（那正是 QA 点名的「加了列 ≠ 列进了判定量」）。

消费位前后对撞（现读 `grep -c shape_ok 件` ＋ `grep -n shape_guard_failed 件`，别抄本表）：

| 件 | `2ae0b43`（接线前） | 工作副本（接线后） | 真消费位行号 |
|---|---|---|---|
| `deploy/loadtest/r23_thread_from_checkpoints.sql` | `shape_ok` **2**／否决文案 **0** | **13**／**4** | `:608` ＋ `:613`（⑰ 两支 verdict）、`:697`（⑰c verdict）；`:717` 是 ⑱ 注记、不算消费 |
| `backend/reports/w4/probe_prod_checkpoint_terminal.sql` | **1**／**0** | **4**／**1** | `:364`（⑫ 的 verdict） |
| `backend/reports/w6/probe_audit_invariant.py` | **0**／**0** | **6**／**2** | `:549`（`GRID23_BY_DOMAIN_SQL` 的 verdict）、`:1496`（产物里的 `guard` 字段） |
| 合计 | **定义 2 处、消费 0 处**（＝ QA 的读数，本窗复现） | 定义 3 件、**消费 6 处** | — |

### 2. 反证 = 真注入了（不是 `UNVERIFIED`）

夹具件 = `backend/reports/w8/t23_negative_fixture.sql`（本窗新建、入库留证；第 1 行就写死「**绝不得对共享 `ecom` 执行**」，DDL／种子／抽取命令／期望值全在件内）。

- 一次性容器 `w8-t23-neg`：镜像 `pgvector/pgvector:pg16` = **`sha256:ccc6e83d6e35`**（容器已删，但镜像还在 ⇒ 这一行可现读，用来佐证那次跑过），
  端口 `127.0.0.1:55441`，库 `ecom_neg`，`POSTGRES_HOST_AUTH_METHOD=trust`（本机一次性、无口令 ⇒ 不进任何文件／日志／报告）。
- 注入内容：一条 `channel='terminal'` 且 `task_path` **不含 `', '`** 的写行 ⇒ `split_part(…, ', ', 2)` = 空串 ≠ `__start__`
  ⇒ **这一行本身就是"格3 假绿"的形状**，同时让 g1 变非 0（一石二鸟：既造出假绿、又造出守卫条件）。
- **同库、同参、只换件版本**（语句从文件里逐字抽，不手抄；抽取一行脚本在夹具件注释里）：

| 器件 | 读数（rc 均 0） |
|---|---|
| ⑰ 旧版（`2ae0b43`） | `ge2 = 0 且 t2_routed_supp = 1 ⇒ **非空真达成**` ← **假绿被复现**（这就是"没接守卫时会发生什么"） |
| ⑰ 新版（工作副本） | `不可判__shape_guard_failed（⑱ 两条形状约定有一条变了 ⇒ wrote_terminal 系读数一律作废，含本行与 ⑰c）` |
| ⑰c 新版 | 四行（A 尺两域 ＋ B 尺两天）**全部** `不可判__shape_guard_failed`，`shape_ok = f`、`g1 = 1`、`g2 = 0` |
| ⑱ 新版 | `terminal_rows 2`／`g1 1`／`g2 0`／`被排 0`／`段2 节点种数 2`／`literal-'null' 型 0`／`shape_ok f` |
| 夹具自检 | `fixture_g1_rows__want_1 = 1` ⇒ 证明靶子被打中了，不是"零命中判据的空转" |

- 拆容器前留证：`docker inspect` 行 = `/w8-t23-neg pgvector/pgvector:pg16 2026-10-02T14:03:24.841925091Z 5432/tcp=host 127.0.0.1:55441`，随后 `docker stop` ＋ `docker rm`。
  现读 `docker ps -a --format '{{.Names}}'` 里 `w8-t23-neg` 计数 = **0**（22:2x）。⚠️ 删的是**容器**；夹具件本身入库。

### 3. QA ③ 的措辞降格：⑰c 的 B 尺改成「分布可见性」，并把理由量出来

现测（共享 `ecom`，22:2x，`-t -A -F '|'` 面）：⑰c 的 B 尺只产出 **09-16(0)／09-19(15)／09-20…09-23(各 0)／09-28(8)／09-29(38)／10-01(3)**，
**09-30 与 10-02 根本没有行** ⇒ 边界常量 `2026-09-30T14:25:35Z` 落在**无样本间隙**里 ⇒ 两把尺**当期必然同值**
（对撞：15 ＋ 8 ＋ 38 ＋ 3 = **64** = ⑰ 的 `turn>=2` 总数 ⇒ 分日没有漏也没有多）。
⇒ 标签已改为 `A 按修法时刻（日期代理，非构建身份）`／`B 按日（分布可见性，当期与 A 必然同值）`，并在件内写明：**它要真的独立，得等 T-11② 的 `self_reported_rev` 落地**。
⚠️ 这条不是判据变更（`verdict` 的文案在接线前零消费者，QA 第 9 轮已认同一形状）⇒ 不需要逐臂复查原判据防的是什么。

### 4. T-25（QA ⑤）：收件人补记 ＋ 无收件人归属句通扫（**只列，本窗一条没改**）

**(a) 已加的一处** = `backend/reports/w4/RELAY.md` 第 3 项「必须改谓词（给 W7 / 架构）」处新增 **7 行 🔻 收件人补记**
（原 1204／1205 两行一字未动；插在「现测（16:12:12Z…）」之前，现该原句在 `:1213`）。写进去的事实：
排除式现读 = **11 处 run 级判定面**（r23 `491/539/577/666` ＋ w4 `157/189/220/253/348` ＋ w6 `516/535`；前 8 处入 `27c3e08`、后 3 处随 `2ae0b43` 的分域并报新增），
以及「这条形状约定要不要升成全仓规则」= 判据措辞题 ⇒ 只列进本节 §三.6 的 `P-` 队列，**不替它写结论**。
⚠️ 同轮顺带在 `r23` 的 ⑱ 注记里**订正我自己第 2 轮那句"共 8 处"**（原文不删）——它因为我后来新加 3 个消费面而变旧。

**(b) 通扫尺**：三条正则族 `A = (归|给|由|交给|移交|待|等|请|让) W(0|1B|2A|2B|2D|3A|3C|4|5|6|7)`、`B = W… (收口|结案|执行|接手|落地|入库|验收|复算|改|实现|补|裁定)`、`C = (上呈架构|请裁|待架构|等架构)`；
扫描面 = `backend/reports/**` ＋ `deploy/loadtest/*.sql` ＋ `eval/*.py`（扩展名只收 `.md/.py/.sql/.txt`），**134 个文件、938 条命中**，脚本 = 本机 scratch `E:/tmp_qoder/w8_t25_sweep2.py`（不入库）。
分三档，**全部只列**：

| 档 | 命中 | 判读 |
|---|---|---|
| **T1 在途面**（`reports/qa/**` ＋ `reports/w8/**`） | **64**（仍前瞻 52 ／ 非前瞻 12） | 真正会让下一轮读成"有人欠"的活口。⚠️ **写权不在本窗**（`qa/**` 归 QA，`w8/PROMPT.md` 由 QA 起草）⇒ 只交清单 |
| **T2 尺件注释**（`deploy/loadtest/*.sql`、`eval/*.py`、`reports/w*/probe_*.py`） | **38**（前瞻 12 ／ 非前瞻 26） | 本窗**有写权** ⇒ 建议列进第 4 轮尾巴；本轮按题面"先不改" |
| **T3 史料**（停用窗的 `RELAY/DELIVERY/HANDOFF/PROMPT` ＋ `arch/**`） | **836** | **不改**：带时刻的历史记录，改了毁审计链。规矩 = 只在被引用处加 🔻 注记（＝ (a) 的做法）。最大四本 = `arch/RELAY.md` 88／`w7/RELAY.md` 84／`w6/RELAY.md` 51／`w4/RELAY.md` 44 |

**点名清单**（T1＋T2 里最该先处理的，按"下一轮会把它当活任务读"的概率排；文件:行号均为现读）：
1. `qa/TASK_BOARD.md:29 / :39 / :50 / :60 / :71` —— 五个小节标题「### 给 W1B（T-01）」「给 W2B ＋ W0（T-02）」「给 W7（T-03）」「给 W6（T-04a ＋ T-06）」「给 W4（T-06）」⇒ **整块板面没有收件人**（QA 写权）。
2. `qa/TASK_BOARD.md:215 / :216 / :217 / :243 / :257 / :259` —— 「请 W2A 交…」「请 W1B 给一条可复算断言」「请 W6 把 G-3／G-4 推到可判」⇒ 三张属主已停用；其中 policy 集合差那半**现在就是本窗的 `O-12`／T-14 面**。
3. `qa/COMPLETENESS.md:42`（「当期读数等 W7/W6」）、`:189`（「请 W2A ＋ 架构判…」）、`:241`（「引用规则文本半边归 W4／架构」）、`QA_LEDGER.md:72`（「待架构确认转结」）⇒ 新体制下架构降为按需，这类句子应改写成 `P-` 队列引用（QA 写权）。
4. `qa/RELAY.md:309` 与 `qa/TASK_BOARD.md:454` 是本窗 §一／§二 的**镜像句**（QA 记录"该改"这件事本身），不算活口 ⇒ 列出仅为对账。
5. **生产／评测件里的注释也在指向停用窗**（T2，本窗有写权）：`eval/gates.py:12 / :345 / :358`（「输入归 W7」「压测归 W7，本轮未收到回执」）、`eval/gap_table.py:73 / :78 / :79 / :99 / :127 / :173`、`eval/harness.py:21 / :715`、`eval/reporter.py:89 / :601`、`eval/pg_guard.py:19`、`eval/attribution.py:38`、`eval/sqlite_exec.py:40`、`deploy/loadtest/r22_lag_runseq.sql:57 / :113`（「交给 W4 对第五档」）。
6. 探针件内注释（T2）：`reports/w6/probe_audit_invariant.py:452 / :1464`（「这张表归 W7/W4 的迁移面」）、`reports/w6/probe_gate_allowlist_shape.py:246`、`reports/w6/probe_gate_rejections.py:3`、`reports/w6/probe_rule_identity.py:121`、`reports/w3c/probe_l4_accuracy_carriers.py:4 / :20`、`reports/w2c/_probe_w2c_gate2_reject_faces.py:17`、`deploy/loadtest/r23_thread_from_checkpoints.sql:559`。
7. ⚠️ **一条工具坑（不计入 938）**：`reports/w6/__pycache__/probe_audit_invariant.cpython-313.pyc` 也命中 ⇒ 计数尺必须先按扩展名过滤，否则"文件数／命中数"里混进构建产物。

### 5. 本轮门禁与回归（每条带命令形状 ＋ 真 rc）

| 项 | 读数 |
|---|---|
| 尺件全跑（共享 `ecom`，注记订正**之后**）＝ `psql -U postgres -d ecom -t -A -F`（分隔符用**竖线**）`-f -` ＋ 三个 `-v`（值不套引号） | **rc=0**、`grep -ci ERROR` = **0**、非空行 **63**（与第 2 轮同尺同值；⚠️ 这个 63 依赖 `-F 竖线` 这一面，不带它本窗实测是 **60** ⇒ 报数必带输出格式面） |
| ⑱ 正常态 | `825 / g1 0 / g2 0 / 被排 6 / 段2 节点种数 8 / literal-'null' 型 6 / shape_ok t` |
| ⑰／⑰c 正常态 | ⑰ = 混合域不作判（runs 1,384／t2 64／ge2 5／ge3 3）；⑰c `post_fix` **3/1/0/3 ＋ t ⇒ 非空真达成（n=1）**、`pre_fix` **61/5/5/0 ＋ t ⇒ 未达成**；B 尺逐日与 A 尺同值 |
| `py_compile`（`backend/` 下，venv python） | rc=0 |
| ruff（`cd backend` ＋ `--config pyproject.toml .`，**rc 不接管道**） | `All checks passed!`、**0 条**、rc=0 |
| `reports/w4/probe_prod_checkpoint_terminal.sql` 端到端（同参、同 `-F 竖线` 面） | **rc=0**、ERROR **0**、非空行 **47**；⑫ 两行见 §三.5.2 |
| `reports/w6/probe_audit_invariant.py` 端到端（产物写到 scratch，**不动 W6 在库的 json**） | 修 `group by` 前 **rc=0 但整片写面降级**；修后 **rc=0 ＋ 「不可用」计数 0**（详见 §三.5.1） |
| 共享栈未动 | `docker ps -q` 计数 = **4**（api／pg／redis／pgbouncer 全 Up） |
| 他窗遗留容器未动 | `cql-it-pg-w2b-t02`／`cql-it-pg-t02`／`w7load-api_pre0930r11_bak` 仍在（默认保留，本窗不删） |
| 额度 | `app.cost_ledger` 今日新增 **0** ⇒ 全天零花费、零 LLM 调用 |

#### 5.1 🔴 本窗第 2 轮的 w6 leg 一直是**静默降级** —— 本轮端到端跑才抓到

现象（端到端跑 `probe_audit_invariant.py`，**rc = 0**，但 stdout 自己喊）：
`🔴 台账第 8 面不可用 ⇒ 本轮没有写面归属读数（不是「归属为 0」）：GroupingError: aggregate functions are not allowed in GROUP BY  LINE 26: when count(*) filter (where s.turn >= 2 and coal…`

根因（我自己写的，不是他窗遗留）：第 3 轮给 `GRID23_BY_DOMAIN_SQL` 追加 `shape_ok`／`verdict` 两列时，把结尾改成了 `group by 1, 7`
⇒ 第 7 列正是**含 `count(*) filter` 的 verdict**，PostgreSQL 不许它当分组表达式。`2ae0b43` 版是 5 列 ＋ `group by 1` ⇒
**我是"照着加列"改的，改完只跑了 `py_compile` ＋ 抽 SQL 单跑，没端到端跑那件 py。**

处置：改成 `group by 1 order by 1`，并在该 SQL 内留 🔴 注记写清"为什么不能 group by verdict"（防下一轮顺手补回来）。
验证：`py_compile` rc=0、ruff rc=0（0 条）、整件端到端 rc=0 且 `grep -c 不可用` = **0**（原为 1）。

⇒ 三条要往上收的规矩（本窗自曝，不藏在修法后面）：
1. **改了嵌在 py 里的 SQL，必须端到端跑那件 py**；"抽 SQL 单跑"只覆盖语法面，覆盖不到调用点的列数配对。
2. **rc=0 只证明进程没崩**。降级是器件自己喊出来的那句"不可用"，所以收尾要多印一个 `grep -c 不可用` ＋ `grep -ci error` 的计数；
   「降级必须喊出来」这条**第一次由我方器件真的喊了出来 —— 但没人读就等于没喊**。
3. **顺带量到一条次序事实**（对 T-24 有用）：用 `app_ro` 面 DSN 跑 ⇒ 报的是 `LookupError: app.audit_log 里没有我认识的时间列`，
   用 `app_rw` 面（= W6 产物 `dsn_redacted` 自报的 `app_rw@127.0.0.1:5432/ecom`）＋ 错的 scheme ⇒ 才撞到 `PgReadOnlyGuardError`
   ⇒ **时间列探测发生在 `force_readonly()` 之前**（同码、只换凭据面 ⇒ 差异归因于面而非代码；至于"为什么 ro 面看不到列"= **未定因，记 `UNVERIFIED`**）。
   另：`postgresql+psycopg` 这个 scheme 会被守卫直接拒 ⇒ 守卫确实"比只印类型名更宽"地起作用，且它拒绝时**没有泄漏 conninfo**。

#### 5.2 三件**各自真跑**之后的分域读数对撞（这次不是抽件单跑）

| 器件 | `post_fix` | `pre_fix` |
|---|---|---|
| `r23 ⑰c`（A 尺两行） | t2_runs 3／n 1／ge2 **0**／ge3 3／`shape_ok t` ⇒ **非空真达成（n = 1）** | 61／5／**5**／0／`t` ⇒ **未达成（ge2 = 5）** |
| `w4 ⑫`（端到端 psql） | `3｜1｜0｜3｜date_proxy…｜true｜非空真达成（ge2 = 0 且 n = 1）` | `61｜5｜5｜0｜date_proxy…｜true｜未达成（ge2 = 5）` |
| `w6 grid23_by_domain`（端到端 py 产物） | `3／1／0／3／shape_ok true／非空真达成（n=1）` | `61／5／5／0／true／未达成（ge2 = 5）` |

⇒ 三件逐字段同值，且**都是各件真跑出来的**（第 2 轮那次"三处同值"是抽件单跑，w6 leg 当时其实是坏的 ⇒ 那一条**本轮才算达成**）。
`read_as`／`domain_ruler_is_not` 两栏也随产物落盘（标签不许被念成构建身份）。


### 6. `P-` 队列（新体制形状：只列问题 ＋ 现测支撑，不写"上呈请裁"，不替架构写结论）

- **P-4｜形状约定要不要升成全仓规则**（旧 P-1 的同一件事，本轮补现测）：排除式 **11 处** vs 守卫 **1 处**（`r23 ⑱`）vs 否决消费位 **6 处**；
  `docs/07 §4.8 U-129`（现读 L1155）的引用规则文本目前只点到 `deploy/loadtest/r23_*.sql` 一件 ⇒ 问题：要不要一句全仓规则、挂在哪个号下。
- **P-5｜DoD④ 的承诺面**（旧 P-2，未动）：`.gitleaks.toml:82` 承诺「任何受版本控制文件里出现属主口令 DSN 都必须红」，门规则只吃 `+psycopg` 形状 ⇒ 改门 or 改那句话（后者 = 判据变更）。
- **P-6｜`U-129` 格2 要不要继续挂在 n = 1 上**：现读 post_fix 域 `n = 1` ⇒ 抬 n 只能靠真实流量（要额度），或改第四件前置的形状。

### 7. 本窗自曝（两条）

- **把 `docker compose ps` 的空表读成了"共享栈没了"**：不带 `-p` 时本目录返回**表头 1 行且 rc=1**；带 `-p commerceql` 才是 5 行 rc=0；`docker ps -q` = **4** 只都在。
  两条教训合一：**判"栈在不在"用 `docker ps -q` 计数**，且 **rc 不许接管道**（我第一次就是 `tr` 之后才看 rc）。
- **我自己第 2 轮写进 ⑱ 注记的"共 8 处"变成了旧数**（后续我又加了 3 个消费面）⇒ 凡是"处数／行号"这类随追加漂移的量，落笔要指"现读 grep"而不是把数钉死；已在件内加 🔻 订正、原文未删。
- 🔴 **最贵的一条：本窗第 2 轮的 w6 leg 从头到尾是坏的**（`group by 1, 7` ⇒ 整片写面静默降级，而 rc 一直是 0）。
  我第 2 轮在 §二.4 写的"三处同值互校"里，**w6 那一处其实是抽 SQL 单跑对上的、不是那件 py 跑出来的** ⇒ 本轮端到端重跑后才把它算成真达成（全貌与修法见 §三.5.1）。

### 8. 落盘指纹（现算，非凭手感；工作副本面 ＋ 入库前 blob 面都报）

| 件 | 工作副本 bytes／行／CR | 工作副本 md5(12) | blob 面 md5(12) @ `4e11f64` |
|---|---|---|---|
| `deploy/loadtest/r23_thread_from_checkpoints.sql` | 57,545／729／CR 0（纯 LF） | `cdd711ed33a6` | `ad37d1156372` |
| `backend/reports/w4/probe_prod_checkpoint_terminal.sql` | 26,532／369／**CR 369 = CRLF 369、bare 0** | `8226d67ff6c3` | `4668b828d7ae` |
| `backend/reports/w6/probe_audit_invariant.py`（含本轮的 `group by` 修法） | 125,009／1,749／CR 0 | `6ab0dfd421ad` | `61b595ceefd3` |
| `backend/reports/w4/RELAY.md`（本轮加了 7 行注记） | 158,485／1,232／CR 0 | `4dae4b2756ba` | `0feac626802a` |
| `backend/reports/w8/t23_negative_fixture.sql`（新建） | 4,547／58／CR 0 | `fe727c098a00` | —（未入库，本轮第一笔带上） |

⇒ 两个面同时存在且**必须同时报**：`.gitattributes = * text=auto eol=lf` ⇒ `w4` 探针的工作副本是 CRLF、blob 是 LF（`git status` 干净 ≠ 字节等于 blob）。

### 9. 下一步顺序 ＋ 可并发／必须串行（本轮刷新）

顺序（QA 第 3 轮 ⑥ ＋ 本窗判读）：**T-23（已完）→ T-11②（头项：`gate_provenance` 的 `self_reported_rev`，它决定 ⑰c 标签能不能从日期代理升成构建身份）→ T-24（`force_readonly()` ＋ 异常出口过 `scrub_secrets()`，4 件）→ T-19（先数不改）→ T-20 → T-16**；T-09 剩余面／T-17／T-18／A5 在后（A5 等总控给时点）。

| 档 | 件 | 为什么 |
|---|---|---|
| **可并发**（只读、零花费、不碰共享写面） | T-19 预扫、T-25 清单核对、T-24 的 4 件读码 | 全为只读或本窗独占文件 |
| **必须串行** | T-11②（改 `eval/gates.py`，闸门件）→ 之后才能重跑闸门；T-16（要一次性容器，且端口／容器名得避开他窗遗留） | 改闸门会让"当期性"判定重算；容器起停要与共享栈错开 |
| **要总控批时点** | A5（重建 4 个共享容器）、任何抬 n 的真实流量、评测重跑额度 | 花钱或动共享面 |

