# 集成收尾窗（W8）· DELIVERY

> 一行一件事；状态三态（达成／未达成／`n/a`）＋ `UNVERIFIED`；每条证据的形状见 `RELAY.md` 对应节，本表不重复散文。
> 判据权威 = `docs/07 §4.8`（架构窗），本窗**不自取 `U-xx`、不改判据措辞**。

## 第 1 轮交付（2026-10-02 19:1x–19:3x +0800 ｜ 起始 HEAD `f485ffe` ｜ 零额度、零跑批、未动共享栈）

| 单号 | 交付物 | 判据出处（本窗现读） | 状态 | 证据在 | 要额度过不过 |
|---|---|---|---|---|---|
| **T-12**（W7 半边 ＋ 覆盖面延伸） | `deploy/loadtest/r23_thread_from_checkpoints.sql` 3 处 ＋ `backend/reports/w4/probe_prod_checkpoint_terminal.sql` 4 处 ＋ `backend/reports/w6/probe_audit_invariant.py` 1 处 ⇒ **run 级 `terminal` 证据谓词 8 处全部带 `__start__` 排除**；排除式换成与 T-12 文本同形的精确式 | `07 §4.8 U-129` = **L1155**；`07 §4.8 U-130` 判据②（直读式）= **L1157**；任务文本 = `reports/qa/TASK_BOARD.md` 第二轮 §二 与「→ W7（T-09 ＋ T-12 合并）」粘贴块 ③ | **达成（8／8 覆盖面）**，且现测证明**不推翻任何历史读数** | `RELAY.md` §一.3（含三向 A/B 对照命令与两把 EOL 尺）＋ commit `27c3e08` | 否（零额度） |
| **T-12 的 W4 半边**（把「谁引格3 谁排 `__start__`」写进 `U-129` 引用规则文本） | 未做（归 `docs/07` 正文 = 架构笔）⇒ 改为**上呈 P-1** | 同上 | `n/a`（不在本窗写权面） | `RELAY.md` §一.5 P-1 | 否 |
| **§5 盘面处置**（他窗在途改动） | 判为**续写并入库**，未还原、未 `stash`、未 `checkout`、未 `clean` | `PROMPT.md` §5、`08 §6.4` | **达成** | `RELAY.md` §一.3 | 否 |
| **`U-129` 三格当期读数**（零额度副产物，非结案证据） | 全库宽窗 `⑮/⑯/⑯b/⑰/⑰b` 五组数（粒度 = run） | `07 §4.8 U-129` L1155 末段「三格并报 ＋ 第四件前置非空真」 | 格3 **达成**／格2 ~~未达成（作用域含 pre-fix，不得读成回归）~~ 🔻 **10-02 第 2 轮就地改判 = `n/a`（该作用域不含可判样本）**；分域后 `post_fix` 域格2 = 0 且 **n = 1** ⇒ 可当验收位、不得升格成率／臂2 **达成（0）** | `RELAY.md` §一.4 ＋ **§二.2** | 否 |
| T-19／T-20／T-16／T-09 剩余面／T-11①②／T-17／T-18／A5 | **未启动**（顺序见 `RELAY.md` §一.7） | `TASK_BOARD.md` §8.2／§8.3／档位 A §四／`07:1163` | `UNVERIFIED` | — | 仅 A5 要总控批时点 |

## 第 2 轮交付（2026-10-02 19:4x–20:0x +0800 ｜ 起始 HEAD `c7cf34a` ｜ 零额度、零跑批、未动共享栈、未起停容器）

| 单号 | 交付物 | 判据／任务出处 | 状态 | 证据在 | 要额度过不过 |
|---|---|---|---|---|---|
| QA 三条账面订正 (a)(b)(c) | 行号复述 8 处（491／539／577／w4 4 处／w6 1 处）＋ 报数补「psql 输出格式」这一面（默认面 155 vs 175 行；`-t -A` 非空行面 **51 vs 63**，与 QA 的 51 同尺对上）＋ 停用 `docs=` 记法 | `reports/qa/RELAY.md` 第 2 轮 ① | **接受并入库** | `RELAY.md` §二.1 | 否 |
| **格2 三态改判** | 两把尺独立复算（A 按修法时刻／B 按日）⇒ 全库窗 `n/a`、`post_fix` 域 0 且 n=1；三件同值互校 | `07 §4.8 U-129` L1155（第四件前置非空真） | **改判成立**（本窗 §一.4 的"未达成"就地作废） | `RELAY.md` §二.2 ＋ §二.4 | 否 |
| **T-21**（新） | 全仓唯一一处形状守卫 = `r23` 的 **⑱**（两条形成立刻各配"若变则怎么坏"的方向 ＋ `shape_ok` 三态联动 ＋ `type` 存字符串 `'null'` 的现测） | `reports/qa/RELAY.md` 第 2 轮 ③ | **达成**：g1 = **0**／g2 = **0**／terminal 行 **825**／被排 **6**／段 2 节点种数 **8**／`shape_ok = t` | `RELAY.md` §二.3 | 否 |
| **T-22**（零额度部分） | 三处分域并报：`r23 ⑰c`（两把尺同框）＋ `w4 ⑫` ＋ `w6 writes.grid23_by_domain`；标签一律写 `domain_ruler = date_proxy__…`，并写明它**不是**构建身份 | `reports/qa/RELAY.md` 第 2 轮 ④ | **达成（零额度部分）**；抬 n 那半 = 要真实流量 ⇒ **未做、未跑** | `RELAY.md` §二.4 ＋ 提交（本轮第二笔） | 花钱那半待批 |
| **T-11②**（升为正式项） | 未做 ⇒ 登记为第 3 轮头项，并写清它是"严格分域"的前置（本轮三处的标签只能到日期代理） | `TASK_BOARD.md` §二 T-11②、QA 第 2 轮 ② 末句 | **UNVERIFIED**（未开工） | `RELAY.md` §二.7 | 否 |
| T-19／T-20／T-16／T-09 剩余面／T-17／T-18／A5 | 未启动（顺序见 `RELAY.md` §二.7）；A5 等总控给时点 | `TASK_BOARD.md` §8.2／§8.3／档位 A §四／`07:1163` | `UNVERIFIED` | — | 仅 A5 要时点 |

## 第 3 轮交付（2026-10-02 20:1x–22:3x +0800 ｜ 起始 HEAD `4e11f64` ｜ 零额度、零跑批、未动共享栈、起停过一只一次性容器）

| 单号 | 交付物 | 判据／任务出处 | 状态 | 证据在 | 要额度过不过 |
|---|---|---|---|---|---|
| **T-23**（QA 第 3 轮 ②，头项） | `shape_ok` 接成**否决位**：三件各加同源 `shape` CTE，⑰／⑰c／⑫／`GRID23_BY_DOMAIN_SQL` 的 verdict **第一支**即消费它；新增输出列 `shape_ok__T23／g1__want_0／g2__want_0` | `reports/qa/RELAY.md` 第 3 轮 ② ＋ `reports/qa/TASK_BOARD.md` T-23 | **达成**：消费位从 **0 处 → 6 处**（行号现读见 §三.1） | `RELAY.md` §三.1 | 否 |
| **T-23 的反证**（不注入就要记 `UNVERIFIED`） | 一次性容器 `w8-t23-neg`（`sha256:ccc6e83d6e35`，已 `stop`＋`rm`，现读计数 0）＋ 夹具件 `reports/w8/t23_negative_fixture.sql`；同库同参只换件版本 ⇒ **旧版假绿被复现**、新版自动降「不可判」 | 同上 ＋ QA `RELAY §4.1` 的 out-of-tree 方法 | **达成（真注入，非 `UNVERIFIED`）**；夹具自检 `fixture_g1_rows = 1` ⇒ 靶子确实被打中 | `RELAY.md` §三.2 ＋ 夹具件内注释（含全部复算命令） | 否 |
| QA ③ 措辞降格 | ⑰c 的 B 尺标签改为「分布可见性，当期与 A 必然同值」；现测：B 尺只产出 09-19(15)／09-28(8)／09-29(38)／10-01(3)，**09-30 与 10-02 无行** ⇒ 边界常量落在无样本间隙里；15＋8＋38＋3 = 64 = ⑰ 的 `turn>=2` | `reports/qa/RELAY.md` 第 3 轮 ③ | **达成**；"真的独立"这一半 = **待 T-11②**，件内已写明 | `RELAY.md` §三.3 | 否 |
| **T-25**(a)（QA ⑤） | `reports/w4/RELAY.md` 第 3 项处新增 **7 行 🔻 收件人补记**（原 1204／1205 一字未动）；同轮订正 `r23 ⑱` 注记里我自己那句"共 8 处"→ 现读 **11 处** | `reports/qa/RELAY.md` 第 3 轮 ⑤ | **达成** | `RELAY.md` §三.4(a) | 否 |
| **T-25**(b) 通扫（题面＝只列不改） | 134 文件／**938 条**命中，分三档：在途面 64（前瞻 52）／尺件注释 38／史料 836；**未改任何一条**，点名清单 8 组带 file:line | 同上 | **达成（清单交付）**；改不改由总控与 QA 定 ⇒ 本窗不自作改他窗写权面 | `RELAY.md` §三.4(b) | 否 |
| 🔴 端到端重跑的副产物（本窗自找） | 发现第 2 轮的 w6 leg 一直是**静默降级**（`group by 1, 7` ⇒ `GroupingError`，而 **rc 仍 = 0**）⇒ 修为 `group by 1`，件内留注记防补回；端到端复跑后「不可用」计数 1 → **0** | 本窗纪律「降级必须喊出来」＋「新 SQL 先单独跑」的**加强版** | **修成并复核**；副作用 = 三件分域读数这次是**各件真跑**同值（§三.5.2） | `RELAY.md` §三.5.1／§三.5.2／§三.7 | 否 |
| **T-11②**（本轮顺序头项） | **未启动** ⇒ 已登记为第 4 轮头项；它是 ⑰c／⑫／`grid23` 标签从"日期代理"升成"构建身份"的唯一前置 | `TASK_BOARD.md` T-11②；`07 §4.8 U-129` L1155 | `UNVERIFIED` | `RELAY.md` §三.9 | 否 |
| T-24／T-19／T-20／T-16／T-09 剩余面／T-17／T-18／A5 | 未启动（顺序 `T-11② → T-24 → T-19 → T-20 → T-16`）；T-24 的本轮现读：连库 py 件 7／带守卫 5／无守卫 4 ＋ 一条次序事实（时间列探测在 `force_readonly()` **之前**） | `TASK_BOARD.md` §8.2／§8.3／档位 A §四；QA 第 3 轮 ④ | `UNVERIFIED` | `RELAY.md` §三.5.1③／§三.9 | 仅 A5 要总控给时点 |

## 第 4 轮交付（2026-10-03 11:4x–14:2x +0800 ｜ 起始 HEAD `d38cf55` ｜ 零额度 · 零跑批 · **动了一次共享栈**（A5 recreate）· 起停一只一次性容器（用完即删））

> 体制：本轮起本窗同时持有开发＋架构决策面（总控指令见 `RELAY.md` §四.0），QA 复算移到收尾一次 ⇒
> 每条结论自带现算命令。`docs/**` 本轮一字未改、未取 `U-xx`。

| 单号 | 交付物 | 判据／任务出处 | 状态 | 证据在 | 要额度过不过 |
|---|---|---|---|---|---|
| **T-19 ＋ DoD④ 门面** | 规则正则扩到 `postgres(ql)?(\+[a-z]+)?://…@<主机>`、`keywords` 同改（**第二个独立失明面**）、allowlist 属主口令只在"引导值 × 回环主机"笛卡尔积上豁免；43 处点红治理到 **0** | `docs/07:2492` 一侧的 DoD④ 承诺句 ＋ `reports/qa/COMPLETENESS.md` 第 9 轮两条 blindness | **达成**（`test_migration_dsn_hygiene.py` 8 passed，含全仓重放零未放行命中） | `RELAY.md` §四.1 ＋ commit `720d434` | 否 |
| **T-19 装载侧 ＋ T-24 探针侧** | 装载器 `DEFAULT_DSN` 删除 ＋ 两条同形状守卫（先解 DSN 再碰文件、空清单即退）；6 处探针兜底全删；w4 的 RO 串不再由 RW 串做字符串手术；w2d 变量名统一 `COMMERCEQL_PROBE_DSN` | `07 §4.8 U-133` 判据①／`U-114`；`reports/qa/TASK_BOARD.md` T-24 | **达成**（五条失败路径真跑：rc 1/1/2/2/2，全部点名缺的变量） | `RELAY.md` §四.2 ＋ commit `335b3d9` | 否 |
| **T-24 尺子侧** | `_module_str_constants` 补 `AnnAssign`（旧尺对带注解模块常量**整仓静默漏网**）＋ 扫面加 `backend/reports`／`deploy`／`eval` ＋ 正对照第三形 | 同上 ＋ 本窗现测（旧尺给 w2d 判过"零命中"） | **达成**：三面现算 0/0/0，例外 2 处（`versions/0001:77-78`）如实登记为"刻意不扫" | `RELAY.md` §四.2 | 否 |
| **T-11②** | `build_stamp()` 唯一口接进四个生产者（含 loadtest 回执——原先只写 `finished_at`，而该键不在 reporter 识别列表里）；红队件在干净树上重生成、五字段与 dirty 版逐字段相同 | `reports/qa/TASK_BOARD.md` T-11②；`07 §4.8 U-129` 对"日期代理 vs 构建身份"的前置 | **部分达成**：`results_v1.json` 在 ¥0 下**重建不出来**（回放 rc=0 但 `n_scored=0`、166 条 `cassette_miss`）⇒ G-2/G-5/G-8 输入件仍停在 `mtime_only` | `RELAY.md` §四.3 ＋ commits `97bce0e`／`00d2321` | 🔴 **要**（`--live` 才能升，四件套届时另报） |
| **T-20** | gold_query 的 `tenant_id` 哨兵不变式接**装配期 raise**（选项 a）＋ 三条测试 ＋ 一次真 A/B 对照（摘掉调用链上那句守卫 ⇒ 用例不红 = 证明它没在自证） | `docs/07:2492`「Gold Query 类行的 `tenant_id` 永远非 `'*'`」＋ QA 第 7 轮 §8.3 现测三条前提 | **达成**（17 passed）；库层 `CHECK` 未做（要在共享栈落迁移） | `RELAY.md` §四.4 ＋ commit `7d1a9c7` | 否 |
| **T-26** | 三面尺定名 F-pred／F-guard／F-consume ＋ 计数件 ＋ 契约测试（只断言三面齐全，不断言数值）；"8 vs 11"归因 = **注释行算不算** 一根轴 | `reports/qa/RELAY.md` 第 10 轮 ③(b)／新开单 | **达成**：现算 F-pred=8（去守卫自身 3）／F-guard=6／F-consume=5 | `RELAY.md` §四.5 ＋ commit `02bd10e` | 否 |
| **T-27** | 反证夹具接成可重复门禁：两侧断言（pre-fix 必出假绿 ＋ 新版必出不可判且**⑰c 必须有行**）＋ ci.yml 新 job（一次性库 `ecom_neg`）＋ 对照件入库带 sha256 ＋ 库名 `ecom` 拒跑（实测拒后库内 lg/app 表数 = 0） | 同上 §四.5 新开单；`07 §4.8 U-114` | **达成**：本机一次性容器 8 项全过 rc 0；回执已入库 `fbbb493` | `RELAY.md` §四.5 ＋ `reports/w8/t23_negative_gate_receipt.json` | 否 |
| **A5** | compose 五个发布端口收到宿主回环，**声明面（`compose config`）与运行面（`docker ps` ＋ `netstat`）两面都量过**；新契约测试钉"回环"＋"宿主端口不重号" | `reports/qa/TASK_BOARD.md` 档位 A A5 ＋ O-11（U-134 前提耦合）；`07 §4.8 U-134` | **达成**： recreate 后 live/ready/web = 200/200/200、`app.embed_doc` 仍 **197 行** | `RELAY.md` §四.6 ＋ commit `8b1aa76` | 否（但要一次共享栈停机，本窗自选时点做完） |
| **P-4／P-5／P-6** | 新体制下由本窗直接裁（P-4 不升全仓规则／P-5 归已修规则／P-6 出率前置 `n ≥ 20`） | `reports/qa/TASK_BOARD.md` §8.4 批次 C | **已裁**（可逆，代价逐条写明） | `RELAY.md` §四.7 | 否 |
| 🔻 同轮补记：**换构建**（原捆给 T-15 的第一半） | `commerceql-api` 由 09-18 的 79-`.py` 骨架重建为 HEAD 级（147 `.py`／openapi 12 path 含 `/api/v1/query`／import 实证 `RUN_SCOPED_STATE_FIELDS` n=47 ＋ `_guard_tenant_private_kinds` 在位），回滚点 = `commerceql-api:rollback-0918stage0` | `reports/qa/TASK_BOARD.md` T-15（①compose `host_ip` ②换构建 ③观测栈 ④压测）；§9 (vi) 三层证据尺 | **达成（①②两半）**：启动断言 4 passed／0 pending、live/ready/web = 200/200/200；🔴 **未发过 `POST /query`** ⇒ 不得写"端到端可用" | `RELAY.md` §四.11 | ④压测半边要 |
| T-16／T-09 剩余面／T-17／T-18／T-15 | **未启动**；T-15 现在只剩"起观测栈＋抓 `/api/v1/metrics`＋（若批）压测"三件（换构建已由本窗在本轮做掉，**不必重做** ⇒ 那一轮的报价按三件算） | `TASK_BOARD.md` §四／§8.2／T-15 | `UNVERIFIED` | `RELAY.md` §四.10 ＋ §四.11(6) | T-15 的压测半边要 |

## 第 5 轮交付（2026-10-03 14:5x–15:5x +0800 ｜ 起始 HEAD `9f30f73` ｜ **本轮花了钱**：5 run / 28 调用 / ¥0.058674 ｜ **动了共享栈**：`api` 重建 3 次 ＋ compose 给 `api` 加公网 DNS）

> 体制未变（开发＋架构同窗，QA 复算在收尾）。本轮的**验收面**变了：第一次把页面在浏览器里打开
> （`http://localhost/`，走 nginx 同源面），一次走查打出 8 处 v1 阻断面。`docs/**` 一字未改、未取 `U-xx`。

| 单号 | 交付物 | 判据／任务出处 | 状态 | 证据在 | 要额度过不过 |
|---|---|---|---|---|---|
| **V1-UI 走查**（新开，本窗自开自裁） | 第一次真机开页并逐面走：空态、健康点、登录、一次完整问答、错误态、重复提问 | §12「出第一版」的 DoD 里**没有**"面向人的判据要开浏览器"这一条 ⇒ 本轮补进纪律 | **达成**：8 处阻断面全部定位并修，最终一次 run 出 5 行真实结果（`direct 162890 … feed 161618`） | `RELAY.md` §五.0／§五.8(1) | 是（¥0.059，已花） |
| **前端四处** | API 前缀唯一出处（`base.ts:18` ＋ 4 条断言）、dev 代理不再剥 `/api`、三列 grid 占位改真实零宽（`ChatPage.tsx:484`）、幂等键一次提交一枚（`queryStream.ts:50`） | 本窗现测：产物内 `undefined/api` 3 处、`main` 宽 32px、同问题重问必 `INTERNAL` | **达成**：vitest 19 passed／tsc rc=0／eslint rc=0／build rc=0，产物内该串 **0** 命中 | `RELAY.md` §五.1 ＋ commit `849b564` | 否 |
| **后端 meta 两处** | `meta_payload` 出站改标量（`events.py:330`／:362）＋ `present` 自己收口组 11（`present.py:83`）＋ 契约夹具改回**契约形状**并加类型断言 | `docs/02_附录A:338` 示例两个都是标量；实测前端印 `NaNs`、`成本 ¥0` 而 `cost_ledger` 记 ¥0.007 | **达成**：修后实测"耗时 14.2s ｜ 成本 ¥0.003171" | `RELAY.md` §五.2／§五.3 ＋ commit `e7d9442` | 否 |
| **gen_sql 表名规则** | 物理名规则写进**只有 SQL 阶段读**的三个提示词（`gen_sql_v1.txt:19` ＋ complex ＋ repair） | 实测：空态示例问题被 R05 连拒两次，结构性拒绝按 §5.4 不触发 repair | **达成**（同问题同租户重跑：过闸、出结果） | `RELAY.md` §五.2 ＋ commit `e7d9442` | 是（2 run） |
| 🔻 同轮自曝：**一次失败的修法** | 第一版改的是共用资产清单的主语 ⇒ PLAN 退到 `no_data_asset` 自拒；**已回退**，教训与对照（改前 2 次出计划／改后 2 次自拒）写进 `payloads.py:309-323` | 共用面（一份摘要喂多阶段）上的"更清楚"＝另一阶段的判据变更 | **已回退**（离线 1888 全绿也拦不住 ⇒ 反证用例已补） | `RELAY.md` §五.4 ＋ §五.8(2) | 是（2 run，≈¥0.011） |
| **api 容器 DNS** | compose 给 `api` 加公网解析（`docker-compose.yml:162`），并写明内网部署该删这三行 | 同镜像同网络 A/B：内嵌 DNS 8 次里 1 次 gaierror(8.02s)＋1 次 3.07s，公网 8/8 ≤0.11s | **达成**：重建后 8/8、`host.docker.internal` 与 `pg`/`redis` 实测仍可解析、ready=200 | `RELAY.md` §五.2／§五.7 | 否 |
| **演示登录面** | runbook 新增 §5.1 三步（`:173`）＋ `mint_dev_token.py` 的"compose 没挂公钥"陈旧话改掉、演示租户钉 `T_A` | D-H 未裁 ⇒ 生产构建不渲染粘贴框 ⇒ **没有任何登录入口**；签错租户的表现是"五步走完、没有数据"而非报错 | **达成**（本轮全部 UI 证据都走这条登录路） | `RELAY.md` §五.2 ＋ commit `e7d9442` | 否 |
| **门禁全跑**（任务 #12 的"跑"半边） | 后端全量／contract＋unit／ruff／mypy／lint-imports／前端四件套／DoD④ 等价扫描／一次反证 | §12 收尾四件套 | **达成但有缺口**：`tests/integration` 9 条本地**未跑**（缺 `COMMERCEQL_TEST_*_DSN`，U-114 设计如此，CI 跑）；本机**没有 gitleaks**，只做了 diff 扫描（0 命中） | `RELAY.md` §五.6 | 否 |
| 🔻 同轮第二次落笔：**集成面闭合 ＋ 一次假红归因** | 一次性库 `ecom_v1int`（建→`alembic` 到 0005→跑→**删**，现查 `ecom_v1%` = 0 行）：`tests/integration` **107 passed**、全量含集成 **2,424 passed / 0 failed** rc=0；`_settings()` 显式钉 `CORS_ALLOWED_ORIGINS=""` | §五.6 那格"集成面本地未跑"被本格取代；`07 §4.8 U-114`（禁指共享库／禁 skip） | **达成**（含三臂对照：净壳 29／只导出该 CORS 变量 4 failed／修复后两态 29） | `RELAY.md` §五.10 ＋ 工作区一笔测试件修复 | 否 |
| **§12「出第一版」** | 版本报告与 OVERVIEW 刷新随本轮收尾件一起出 | 任务 #12 | **进行中**（本报告件即其交付物） | 本节 ＋ `OVERVIEW.md` | 否 |

## 第 6 轮交付（2026-10-03 21:5x–23:2x +0800 ｜ 起始 HEAD `c3b4114` ｜ **本轮花了钱**：`--live` 全量 166 题 ¥0.337171 ＋ 演示 1 问 ¥0.003221 ｜ **动了共享栈**：`api` 重建 1 次 ＋ 一次性库 `ecom_w8int` 建→迁移→删）

| 面 | 落点 | 判据／实测来源 | 状态 | 证据 |
|---|---|---|---|---|
| **第一次真打评测** | 166 题全量、匣带与两份产物入库 | §C.6.1 先报告再跑批（计划打印 ¥0.332 → 实花 **¥0.337171**，+1.6%）；`n_scored=166`、`n_unscored=0`、`n_node_timeout=0` | **达成**（估子准；我中途的"偏低 2–5 倍"警告是错的，已在 §六.1 订正） | `RELAY.md` §六.1 ＋ commit `1af8f65` |
| **gate1 四处闸门自伤** | `_inject_predicates`／`_resolve_column`＋`_clause_key_of`／`_literal_in_value_position`／`_normalize_limit` ＋ 反证 12 条 | 32 条拒绝逐条复算：R06 21／R14 8／R04 2／R10 1，**模型编造列 0 条**；金标自身含 10 条 `NULLIF(x,0)` | **达成**：同一份产物复算 32 ⇒ 通过 30／仍拒 2（那 2 条是模型的账） | commit `0041d94` ＋ `reports/w8/probe_live_ast_rejections.json` |
| **同匣带零成本复算** | 回放①（唯一变量=闸门修复） | 逐条对照真打：30 次翻转**全部** `failed→success`、0 反向；error 32→2、complete 12→42 | **达成**（延迟/花费两栏按 §六.3 的分工读，不许串） | commit `66d5fba` |
| **EX 恒 0 的量具缺陷** | `run_in_sandbox` 补 `%(name)s→:name` 方言桥；预测侧改与金标同器同界复算（不再读体积字段 `result_rows`）；守卫 3 条（含 AST 形状尺） | 出站契约本就要求绑定参数；07 §5.2.1 把 `result_rows` 定为体积字段 ⇒ 只进 `context.hold_rows` | **达成**：`n_equivalent` 0 → **3**（E-MET-10／M-MET-06／M-MET-07）🔻 连带订正第 5 轮引用的 `EX 0/11` | commit `ea0454a` ＋ `tests/eval/test_scorer_sandbox_path.py` |
| **金标默认谓词缺口** | 探针量化，**不动冻结集** | 41 条有 SQL：预测=金标 3 条／预测=金标＋默认谓词 **22 条** ⇒ 19 条属判据侧、19 条属能力侧 | **上呈待裁**（改 `gold_sql` 会破 `content_hash`，N-13 当场验真失败） | `reports/w8/probe_gold_predicate_gap.json` ＋ `RELAY.md` §六.5 |
| **八格重算** | `eval/reporter.py`（零 LLM）＋ G-1 规模两栏显示修正 | G-1 PASS（离线 2,332 ＋ 集成 107）／G-2 FAIL easy×low 0/10／G-3·G-4 PARTIAL／G-5 FAIL／G-6·G-8 UNVERIFIED／G-7 FAIL ⇒ **`PASS 1/8`** | **达成**（`PASS 0/8` 作废；历史文本不删，用 🔻 就地订正） | `reports/w6/评测报告与门禁判定.md` ＋ `RELAY.md` §六.6 |
| **T-11② 闭合** | `build_stamp()` 只统计跟踪件＋stamp 在写盘前取；`git_dirty` 不再被自己的产物淹没 | 真打件自报 `dirty=True` 而开跑时树干净 `c3b4114` | **达成**：G-2／G-5／G-8 输入件取证等级 `mtime_only` → **`self_reported`**（rev 现可读、`dirty=False`） | commit `2ac3d1e` ＋ `RELAY.md` §六.7 |
| **easy×low 为什么 0/10** | `TENANT_SELF_REFERENCE_NOTE` 只进三个理解任务，`plan`/`gen_sql`/`repair` 一个字不给（两面守卫） | 匣带原文：63 条 `clarify_needed` 里最主要一类 `reason_code=unmapped_entity`，提示语就是"「T_A」无法映射到任何已登记实体" | 🔴 **UNVERIFIED**：23:03 起上游 401（密钥尾号 `d46d` 失效）⇒ 两次子集试跑全降级、实花 ¥0；匣带里 4 条认证错误响应已 `git restore` | `RELAY.md` §六.8 ＋ `tests/unit/test_planner_payloads.py::TestTenantSelfReferenceNote` |
| **演示面复走查**（第五件） | `api` 重建后真开浏览器走 runbook §5.1 | 第 1 问：`normalize` 撞 15s 生产契约超时 → `template_only` → `refuse(no_data_asset)`，UI 文案"系统里没有这类数据"（**真实原因是上游**）；第 2 问同题：表渲染 `gmv=30768819.37`，与评测沙箱复算**逐位相同**，15.6s／¥0.003221；两帧降级都喊了出来；同题连问不再 `INTERNAL` | **达成并开单建议**（错误分类把凭据失效/超时统一收口成 `llm_unavailable → no_data_asset`，W3A 面） | `RELAY.md` §六.9 |
| **§五.10 欠的复算命令** | 一次性库整段命令补进 `RELAY.md` §六.10（建库→授权→`alembic` 0005→107 passed→DROP＋残渣尺） | 第 5 轮只写了读数没写命令 ⇒ 本轮要重跑才发现"怎么跑的"已不在我手里 | **达成**（自曝第 3 条） | `RELAY.md` §六.10／§六.11 |

## 按轮留痕（只追加，不回填到上表的结论行）

| 轮 | 本地提交 | 远端复核 |
|---|---|---|
| 1 | `27c3e08`（`fix(w8/t12)`，3 文件 ＋29/−7，`git show --stat` 复核 = 只含本窗三件）＋ 第二笔报告件提交 `c7cf34a` | 推送后 `git ls-remote origin main` = **`c7cf34ae9993…` ＝ 本地 HEAD ⇒ 同点**（本窗第 2 轮开轮时复核，仍同点） |
| 2 | 本轮两笔：尺件笔（3 文件 ＋132/−1）＋ 报告件笔（`reports/w8/{RELAY,DELIVERY}.md`） | 推送后的 `ls-remote` 值记在**下一轮**这一列（不为它另起一笔） |
| 3 | 尺件笔 **`9cf77ac`**（`test+fix(w8/t23)`，4 文件 ＋147/−29；`git show --stat` 复核 = 只含本窗四件：`r23`／`w4` 探针／`w6` 探针／新建夹具件；三件他窗遗留未跟踪物**未 add**）＋ 报告件笔（`reports/w8/{RELAY,DELIVERY}.md` ＋ `reports/w4/RELAY.md` 的 7 行 🔻 收件人补记，原文 1204／1205 一字未动） | 推送后的 `ls-remote` 值记在**下一轮**这一列 |
| 4 | 五笔尺件 ＋ 一笔回执：`720d434`（DoD④ 门面 11 文件）／`335b3d9`（装载器＋四条探针＋尺子 6 文件）／`7d1a9c7`（T-20 两文件）／`02bd10e`（T-26＋T-27 八文件，含新建 CI job）／`fbbb493`（T-27 回执）／`8b1aa76`（A5 compose ＋ 新契约测试）。每笔都按名 `git add`，**未用 `add -A`**；`git show --stat` 逐笔复核只含该单文件 | 开轮时 `git ls-remote origin main` = `d38cf55`（＝上一轮推送点）⇒ 本轮起点与远端同点；本轮推送后的值记在**下一轮**这一列 |
| 5 | 两笔尺件：`849b564`（`fix(w8/ui)`，11 文件 ＋130/−39，含新建 `api/base.ts`／`api/base.test.ts`）＋ `e7d9442`（`fix(w8/v1)`，11 文件 ＋143/−22）。两笔都按名 `git add`，**未用 `add -A`**；`git show --stat` 逐笔复核只含本窗文件。另：本轮删掉一个空残渣目录 `deploy/secrets/jwt_public.pem;C/`（09-20 的重定向产物，不在库内、`secrets/` 本就 gitignore） | 推送后的 `ls-remote` 值记在**下一轮**这一列 |
| 6 | 六笔尺件／证据 ＋ 收尾笔：`0041d94`（gate1 四处修复 ＋ 反证 12 条 ＋ 探针两件）／`2ac3d1e`（`build_stamp` 语义 ＋ stamp 取在写盘前）／`1af8f65`（匣带 409 条 ＋ 真打原始件 ＋ `results_v1.json`）／`ea0454a`（评分器两处缺陷 ＋ 守卫 3 条 ＋ 金标默认谓词探针）／`33736b7`（**修复前**八格读数单独留档，作下一轮的对照基线）／`66d5fba`（回放①读数，含"延迟/花费两栏分工"的警告）。收尾笔：报告件 ＋ 租户自指说明（含两面守卫）＋ G-1 规模两栏。每笔都按名 `git add`，**未用 `add -A`**；`git show --stat` 逐笔复核只含本窗文件。清理：一次性库 `ecom_w8int` 已 DROP（`ecom_%` 计数回 1）、 reporter/runner 留下的 6 个 `.bak-*` 草稿件已删、试跑写进匣带的 4 条认证错误响应已 `git restore` | 推送后的 `ls-remote` 值记在**下一轮**这一列 |
| 🔻 同轮第三次落笔：**第二次全量真打有了读数**（`--live` ¥0.391504，HEAD `b97920d`，凭据按 §六.8🔻🔻 显式覆盖） | complete 12→**48**、error 32→**1**、clarify 54→**30**、EX 3→**6**；但 refuse 68→**87** ⇒ **误拒 63/124=50.8%（G-5 更红）**、澄清率 18.1%（仍未达 ≤15%）⇒ **八格仍 PASS 1/8** | 主阻塞换形：63 条 `execute→refuse` 全部死在 `plan`、理由 100% `no_data_asset`；按金标形状拆 = **34 条计数形态 ＋ 29 条未声明列级聚合**，而语义包 `metrics:` 只有 **9 个** ⇒ 第二处判据侧缺口（冻结集期望 vs 指标面不同源）。不回退租户自指说明（把题留在走不下去的那一步不是修复），下一步杠杆只有"扩指标面（要钱＋W1A 内容）"或"裁考卷口径（判据）" | `RELAY.md` §六.15 ＋ `eval/results_v2_live_20261003T1632Z.json` | 是（¥0.391504） |
