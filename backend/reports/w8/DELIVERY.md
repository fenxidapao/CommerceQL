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

- 🔻 **同轮第四次落笔（收尾之后又逮到一件自家器件缺陷）**（2026-10-04 01:0x–01:5x +0800，起点 HEAD `079916d`）
  ① **`l4_score` 的用量从未进 run 累加器** ⇒ 口径条 `¥0.003288` vs 同一条 run 落库面 `¥0.004670`，差值恰为 `llm_call` 里 `task=l4_score` 那一档；根因 = `record_usage` 全仓只有 5 个调用点、`bind` 是唯一"出过站不记账"的节点。已修（`ScoreOutcome` 带出 `tokens`/`cost_cny`、`score_l4` 用 `replace` 把用量挂上、解析失败也挂；`bind` 入累加器）＋ 守卫 6 条两文件三面（`tests/unit/test_bind_l4_usage.py`、`tests/unit/test_binding_l4.py::TestUsageCarriesOut`）。
  ② **闭合证明分两栏**：零额度回放（唯一变量 = 这条修复）`cost_cny_total` `0.391504`→**`1.131531`**、tokens `1,836,623`→**`2,090,419`**，`l4_score` 一档 **¥0.741315 = 65.5%**、**恰好 73 条用例成本变大 / 93 条逐位不变**；质量三格（`n_equivalent=6`、终态 48/30/87/1）**不变**。活体面：修复后同题口径条 **`¥0.004312` = 落库面 sum `¥0.004312`**（`tk_b6ad2288…`，4 档全数入账）。固定件：`eval/results_replay_after_l4fix_20261003T1722Z.json`。
  ③ ⇒ **此前上报的两批花费都是下限**（少算的正是最贵的一档）⇒ 真实累计花费记 **`UNVERIFIED`**，等 DeepSeek 控制台对账或下一次 `--live`（按新口径 ≈¥1.15，**未批 ⇒ 没跑**）。
  ④ **上一轮那次浏览器走查的镜像现读缺载荷改动**（容器内 `hasattr(app.planner.payloads,'TENANT_SELF_REFERENCE_NOTE')=False`，而闸门两处修复在位）⇒ 两次 `build api` ＋ recreate（`a3b14d1d597c`→`c97ef6d353f8`），三层构建指纹重取 ＋ `/api/v1/healthz/{live,ready}`=200/200（⚠️ 裸 `/healthz/ready` 因第 5 轮加了 API 前缀而 **404**，别当成服务没起）。
  ⑤ **G-1 两栏在当前树重跑**：离线 **2,340 passed / 0 failed**（＝上一读数 2,334 ＋ 本轮 6 条守卫，rc 0）＋ 集成 **107 passed / 0 skipped**（一次性库 `ecom_w8int2`／`ecom_w8int3`，跑完当场 DROP）；`eval/reporter.py` rc **1** 重算 ⇒ **`PASS 1/8` 未变**。🔴 途中两条自曝：第一次集成的 38 条红**全在我的 DSN 形态**（测试四个 DSN 必须 libpq `postgresql://`，`MIGRATION_DATABASE_URL` 反过来必须带 `+psycopg`）；用 `-q` 跑的集成日志会让 `integration_ran=False` ⇒ **G-1 当场从 PASS 掉到 PARTIAL**（真跑过 107 条也不算）⇒ 集成层必须 `-v`。
  ⑥ 🔴 **残渣尺纠错**：§六.10 那句"现查 `ecom_%` = 1，只剩共享库"是错的（SQL `LIKE` 里 `_` 是**单字符通配**，`ecom` 本身不匹配该模式）⇒ 那个"1"其实是别窗留下的 `ecom_u123_probe`；正确现算 `datname like 'ecom%'` = **2 个**（`ecom` 505 MB ＋ `ecom_u123_probe` 10 MB，**非本窗造的，未经同意不删**）。
  ⑦ **顺带量到 `U-128` 现状与本项目最贵的措辞**：`app/llm/router.py:261/288` 已 `512→2304`；匣带 115 条 L4 响应按档分 `finish_reason` = **`512 档 8/8=length`、`2304 档 7/107=length（6.5%）`** ⇒ **大幅缓解、未清零**（⚠️ 这是**匣带面**，与 W7 第十七轮活体的"约 64% 未生效"是两个数、不得互认）；L4 `completion_tokens` 中位 **2,193** 贴着上限 ⇒ 钱花在 `{candidate_id, score, reason}` 的 `reason` 自由文本上，压它属 **G-2 判据变更**，登记待裁、不自动手。
  ⑧ 对外件 `OVERVIEW.md`：证据行（380 / `079916d`，`docs/07 v1.7.18`／`08 v1.4.1`／U-135 指针三处今日重读）＋ §1 ＋ §6 五格 ＋ §7（G-1／G-2／G-5／G-6／G-8 ＋ EX `6/124` ＋ 两条新状态声明）＋ §9 六条（金标默认谓词／指标面覆盖／上游不可用归类／夹具痕迹／L4 计量／`U-128` 现状）全部就地刷新，历史读数一律 🔻 追加不删。细节：`RELAY.md` §六.16／§六.17／§六.18。

- 🔻 **同轮第五次落笔（打包）**（2026-10-04 02:0x–02:2x +0800，起点 HEAD `a29fedc`）
  ① `docs/01–08` ＋ `OVERVIEW.md` ＋ `_refs/` 进 git（新增 **12** 个跟踪文件；`git ls-files docs` 0→**8**；`wc -l` 复算 07=3,642／08=487 与搬前逐位一致 ⇒ 内容未改，只有 `.gitattributes` 的 LF 归一副作用）。
  ② `docs/*.bak-*` 七份移到工作区外归档（移动非删除，`MANIFEST.md` 已记账）⇒ docs 的回滚点此后 = git 历史。
  ③ 🔴 **入库前凭据检查逮到自己一处**：`OVERVIEW.md` 含 `.env` 里两条真口令的字面量（为描述"固定串尺"而落）⇒ 提交前脱敏成形状、复扫命中 **0** 才 add。全仓复扫另有 **8 个早已跟踪并推送**的文件仍含同样字面量（`qa/{QA_LEDGER,RELAY,TASK_BOARD}`／`w2b/RELAY`／`w6/DELIVERY`／`w7/HANDOFF_W7`／`w8/PROMPT`／`deploy/loadtest/README`）⇒ 属 `U-134` 未裁项，本窗只登记、不擅动。
  ④ 门复跑：DoD④ 替身 8 passed ＋ 离线全量 **2,340 passed / 0 failed**（含 docs 的树，rc 0）。
  ⑤ 交付包：`git archive --format=zip -o "E:\01_实训\项目\CommerceQL_v1_20261004.zip" HEAD`（筛选口径 = 跟踪集 ⇒ 天然排除 `.venv`／`node_modules`／**421 MB 沙箱库**／`deploy/.env`／`*.bak-*`／`*.log`）；包外需收件人自补三件：`deploy/.env`、`data/ecom_sandbox.db`（`seed_generator.py` 重建，**本窗未重跑 ⇒ UNVERIFIED**）、宿主 Ollama `:11434`。
  ⑥ 结论：可交 = 一版可跑、可复算、状态诚实的工程作品；**不可**交成"可上线系统"（`PASS 1/8`、EX 6/124、`U-131` 未修）。细节：`RELAY.md` §六.20。

- 🔻 **同轮第六次落笔（验收通知落地）**（2026-10-04 13:5x–14:2x +0800，起点 HEAD `60624ff`）
  ① 新增 `deliverables/ACCEPTANCE.md`（包入口页：导览／跑法／**演示脚本 5 条问句 ↔ 5 张截图**／PPT 素材 a–e 映射／答辩红线表）＋ `deliverables/screenshots/` **7 张真机截图**（结果表含口径条、五渠道订单量多行表、两张澄清卡、一张 PII 拒答卡、两张缺陷取证）⇒ 提交 `8e5b029`。
  ② 🔴 截图顺手打出一个 **P1 新缺口**：顶栏「口径字典」「评测」两页必出 HTTP 404（前端路由在、后端端点未接线，`openapi` 12 条里没有）⇒ 已入 `OVERVIEW §9`；连带订正一句旧表述——第 5 轮"浏览器走查通过"的覆盖面**只有问答链路**，面向人的判据要逐入口点。
  ③ 交付包两版（含 `.git` 历史 ＋ `frontend/dist` ＋ 两份 pytest 日志；禁物断言：无 `.env`／无 `*.pem`／无 venv／无 `node_modules`，且 `deploy/.env.example` **必须在**）：轻包 **26.50 MB／1,421 件**，重包 **120.68 MB／1,422 件**（多一件 420 MB 沙箱库）；两包 `testzip` 完整。夜里那份 7.2 MB 旧包移到 `旧包_已作废\`（未删）。
  ④ 本轮演示花费按落库面现算 = **6 run／15 次调用／¥0.016933**（三条早退的只有 1 次调用 ¥0.0006–0.0010，全链路三条 ¥0.0042–0.0058；这批**含 `l4_score`**，与夜里旧口径不可混比）。
  ⑤ 三条自曝：内嵌浏览器不可见时 `take_snapshot` 能读但 `take_screenshot` 必失败（改本机 Edge headless ＋ CDP，独立 user-data-dir）；注入串用 `replace('%TOKEN%')` 反被占位符吞掉（回显 `len=7` 是唯一线索 ⇒ 一律 `JSON.stringify` 整段注入）；禁物规则子串匹配误伤 `.env.example` ⇒ 打完必须**正面断言该在的在**。

## 第 7 轮交付（**提示词与长期指令整理轮** ｜ 2026-10-04 15:5x–16:2x +0800 ｜ 起始 HEAD `5307a94` ｜ 零额度 · 零跑批 · 未动共享栈 · 未连库 · **门禁没重算**）

- 改的面：**只有规程，没有一行代码／产物／契约正文**。① `reports/w8/PROMPT.md` v2 → **v2.1**（新增 §0′ 八条边界订正 ＋ §1 修 `eval` 路径 ＋ §2⑤ 写面 ＋ §3 拆"每轮必读四件／按需" ＋ §4 两条 🔻 补记 ＋ §5 三处）；② `reports/arch/PROMPT.md` 顶部加 **停用横幅**（判据＋取号已并入 W8，正文旧体制不得再执行；`HANDOVER.md` 血案表仍为必读）；③ 仓库外 `Prompt_W8接力_开发窗.md` 三处定点（写面那句 ＋ 两处 v2.1 指针）；④ 项目记忆 `project-w8-single-dev-window.md` 追加 v2.1 定版段 ＋ 两处就地作废旧句。
- **本轮"执行与证据不一致"点（本窗自报，先于 QA 逮到）**：① 我一度在 `project-delivery-round-protocol.md` 造出**第三份同义抄本**（别手已写「三处降档」），16:19 已撤回我那 2 行；② 我往记忆里写过一条**自己没跑过的复算命令**（漏 `import time`），已换成 16:16 真跑过的两条；③ 16:06 那格"工作区 clean"5 分钟后变 3 行 M ⇒ 状态级断言改成两个时点都写。
- 🔴 **待总控定名的一件事**：16:11–16:18 实测**两只窗同时在写同一批共享件**（`reports/qa/QA_PROMPT.md` ＋ 两份接力件 ＋ 两层记忆）。建议把**长期指令面**（两层记忆 ＋ 两份接力件 ＋ `reports/arch/**`）的整理权收给一只窗（默认建议 = W8），QA 只留 `reports/qa/**`；这条**不由本窗裁**（动的是别手的写面）。细节与复算：`RELAY.md` **§七.4／§七.5／§七.10**。
- 进度对表：**P0／P1 零进展**（`U-131` 未动、顶栏那 **四条**未接端点 A.7.1／A.7.2／A.9.3／A.9.4 未落地（🔻 前手只数了三条，现测见 §七.12）、`OVERVIEW §6/§7/§9` 未刷新、门禁产物仍 `rev 079916d` ＋ `dirty`）⇒ **本行不得被读成"交付面有推进"**。
- 🔻 **同轮补记（16:2x，提交 `f7076d9` 之后）**：上面"改的面"少列了一批 ⇒ 本窗随后又定点改了**项目记忆四件**（`memory-layers` 规则 1＋2 实测证伪后改写、`sole-writer` 加两处降档、`reference` 加定名尺、`MEMORY.md` 索引补 4 条钩子），并把 §七.6 的写面清单补成 `RELAY.md` **§七.11**；第二笔提交 `dcf1c1d` 只动本窗自己的 `RELAY.md` ＋ 本件（门禁**依旧没重算**）。
- 🔻 **同轮补记（16:3x）**：QA 于 16:22 更新 `TASK_BOARD`、16:25 随 `6d7c208` 入库，开出 **`T-28`（P0 · `U-131`，判据 `docs/07:1159` 本窗已复核 = 唯一命中）** ＋ **`T-29`（P2 · 就是要裁 §1↔§2⑤ 写面冲突）**。⇒ **`T-29` 本轮已处置**（§0′ ① 定"全归 W8"＋补 `_refs/` 属主＋§4 三条读数重跑），处置细节与两处纠前手数（路由 `:27-29` 非 `:33-35`；未接线端点**四条**非三条，漏的是 A.9.4 `EvalReportPage.tsx:149`）见 `RELAY.md` **§七.12**。**`T-28` 未开工**（下轮主单，本轮零进展）。

## 第 8 轮交付（**T-28 · `U-131` 修复** ｜ 2026-10-04 17:0x–17:2x +0800 ｜ 起始 HEAD `55751e0`、代码 `4a070ae` ｜ **本轮花了钱**：18 条调用／**¥0.028686**（全非峰）｜ **动了共享栈**：`api` 重建 ＋ recreate ｜ 一次性库零、未跑迁移）

- ① **改了什么**：`app/api/state_store.py`（`SessionMeta.user_id` `:157`、`create_session` 写入 `:354`、**`get_session` 单一强制点** `:379`、内部拒绝计数 `:115`、载荷重建补属主 `:450`）＋ `tests/contract/test_api_endpoints_contract.py` 新增 `TestSessionOwnership` **7 条**。**键与键族一字未动**（判据⑦），`app/cache/keys.py` 不在改动集 ⇒ `git show --stat 4a070ae` 只有两文件。
- ② **三面结案（活体，被测构建 = `4a070ae`，两层身份见 `RELAY.md` §八.6）**：读 = 非属主 `GET` **404**；写 = 非属主 `POST /query` **404**（`task_id=None`、0 帧）；**推理 = 机械可证"不适用"**（那一臂连 `GraphDeps` 都没构造）。每个 404 之前属主已真实产生一轮 ⇒ **不是空靶**。复算：`cd deploy/loadtest ＋ …python.exe probe_session_owner_context.py --target http://127.0.0.1:8000/api/v1 --tokens <两支令牌文件> --out E:/tmp_w7/x.json`（**不带 `--control`** 才是非属主臂；`:18000` 在本机连不通）。
- ③ **离线面**：新契约 7 passed ＋ 整文件 **31 passed**；全树 **2,362 passed / 0 failed / 9 errors**（9 条全是 `tests/integration` 缺 DSN ⇒ 环境未备，**0 条断言失败**）；`mypy` 过、`ruff` 全树过；**`lint-imports` 未跑成**（gbk 崩）⇒ 该格 `UNVERIFIED`。
- ④ 🔴 **顺手修掉一处会产假话的取证件**：`probe_session_owner_context.py` 的 `--control` 是**换臂不是加臂**（`asker = owner if args.control`），而旧 `5_owner_get` 无条件写 `nonowner_followup_written_into_owner_session=True` ⇒ 正对照臂下产物自称"非属主把追问写进了属主会话"。改后同臂复跑 = **False**（新增 `control_followup_present_in_owner_session=True`）。旧产物那份自相矛盾的读数已在 `RELAY.md` §八.5 点名，**不得引用**。
- ⑤ **对外文档面**：`OVERVIEW.md §9` 的 `U-131` 那格从"未修"改为 **修复已落地、待验收**（原历史读数保留）；`§6/§7` **没刷**（门禁没重算）。🔴 对外仍不得写"门禁通过"，也**不得写"跨用户隔离已达成"**；`U-129` 状态不变（旁证只到客户端面，审计三格未查 ⇒ 见 §八.5 末段）。
- ⑥ **两条自曝**：借别窗永久件时先没读它的分支就跑了第一轮（差点把正确的正对照报成"写侧未闭合"）；照抄 QA 块坐标 `:191/:226` 做基准（本手现读 `:189/:405`，一半位移是自己插的行造成的）⇒ 跨窗坐标一律各自按尺引。

## 第 9 轮交付（**T-30 当期门禁重算 ＋ T-31 `U-129` 审计三格** ｜ 2026-10-04 18:3x–19:2x +0800 ｜ 起始 HEAD `a84fc6f`（399 笔、工作树 0 行、与 `origin/main` 同点）｜ **零额度 · 零跑批 · 未重建镜像 · 共享 `ecom` 只读（探针包在 `begin;…rollback;` 里）· 一次性库 `ecom_t30_it` 建→迁移→跑→当场 DROP**）

- ① **T-30 主单达成（"当期"这件事第一次是有尺的）**：八格经**唯一装配口** `reporter.gate_inputs()` 在 `a84fc6f` 上重算并落 `backend/reports/w6/eval_metrics.json` ＋ `评测报告与门禁判定.md`，`meta.git = {rev: a84fc6f, dirty: true}`（脏面 11 行**逐件点名**、唯一代码件 `app/cache/keys.py` 的改动整段在 docstring 里）。🔴 **总判定 `PASS 1/8` 未变**（G-1 PASS／G-2／G-5／G-7 FAIL／G-6／G-8 UNVERIFIED／G-3／G-4 PARTIAL）⇒ 对外**不写"门禁通过"**。🔻 **同轮补记（19:23）**：收尾后在干净树 `cbff229` 上**又重算一次**，两份产物递归 diff **只有 5 条 meta／report_git 字段**（rev 抬到 `cbff229`、dirty true→false）⇒ 判定词逐字节可复现 ＋ 来件起点读数②的 dirty 那一半闭掉。
- ② **G-1 缺的"集成已跑"补上了**：离线 **2,347 passed／0 红**（一个集成 DSN 都没给）＋ 集成 **107 passed**（一次性库，`-v` ⇒ `integration_ran` 才取到）；🔴 **合树单日志对照臂 2,454 passed／0 failed／0 errors** 且 `2,347＋107 = 2,454` 逐位对撞 ⇒ 这条对照同时排掉了 §九.6 那处"合并只取集成层的 `failed`／`errors`"对本轮的污染。
- ③ 🔴 **七格的"数"仍不属当期构建**，本轮按派单零额度 ⇒ 不能换：G-2／G-5／G-8 的输入自报 `b97920d`（10-03 16:29:35Z），G-3／G-4 自报 `22e69d3`，G-6 只有时刻（09-19）无 rev，G-7 只有 mtime（09-18，八格最老）。**5 格 `self_reported_rev = null` 这一维本轮一格未动** ⇒ 登记成 `T-11②` 的第二实例，不自裁（修法要动唯一装配口）。
- ④ **对外八件已落**：`OVERVIEW.md:212` 表 A（数／面／谓词／分母／粒度）＋ `:223` 表 B（时刻／HEAD／取证等级／复算命令，八条逐格一行、全零额度）；`:184` 顺手点名了**两份门禁定义**（`07 §17.3` = 八格 vs `04 §C.8` = 七格）；G-6 那格**多加一条覆盖面**（回执 4 场景 vs `§16.5:3161` 定义的 5 场景）。
- ⑤ **T-31 达成**：`U-129` 审计三格已交，件 = `backend/reports/w8/t31_three_cells.json`（29,450 B，三条作用域原始行 ＋ `generated_at`／`git`／`scope_invariance`）。post-fix 域（日期代理）＝ **格1 臂1 0 ∧ 臂2 0（`t2_runs=10`）**、**格2 `ge2=0` 且第四件前置 `t2_routed_supp=5`**、**格3 `ge3=10≥1`**，⑱ `shape_ok=t`；A 档子窗同尺重跑与 v1.7.17 基线**逐位相同**。**判据措辞一字未动**、`docs/07:1155` 未进 diff ⇒ **本号转绿由 QA 复算裁**，本窗只交数与谓词（`10-04` 那一域 `t2_routed_supp=0` 记的是 `n/a__该域空真`，不是 0）。
- ⑥ **§4.8 那行状态落笔**：`docs/07:1159` 行末追加 **🟢 结案**（三面已交 ＋ QA 五臂逐臂达成）；**行内追加、不新增行** ⇒ 行数 3,642 不变、`:1078`／`:1155` 两把行位尺落笔前后逐字未漂。措辞边界：**只写"已结案"，不写"跨用户隔离已达成"**。
- ⑦ **不占号两件已做**：`keys.py:179` 的 `session_meta` 值清单补 `user_id` ＋ "缺失即按会话不存在处理"；九份旧窗 `PROMPT.md`（`w2-int w3-int w3a w3b w3c w4 w5 w6 w7`）各加"本席位已停用"横幅 ⇒ 尺 `awk 'NR==3 && /停用/' <件> \| wc -l` 十份现读各 1（含上轮 `arch`）。
- ⑧ 静态门重跑：mypy **147 件 no issues**、`lint-imports` **4 kept／0 broken**（不带 `check`）、ruff **两把形状**：`check app` = 全绿 rc 0，`check .`（整目录）= **1 error** 且**不在本窗写面** —— 落在 QA 的 `reports/qa/prompts/probe_u131_readonly.py:18`（`RUF005`，`a84fc6f` 入库）。⚠️ 由此带出一条**标着 UNVERIFIED 的 CI 线索**：`ci.yml:319-321` 的 ruff 步与整目录那把**同形**、`pyproject.toml` 无 `exclude` ⇒ **按命令形状推断 CI 会红**，但 CI 实跑状态我没测到（本机没有 `gh`）⇒ 不写成"就是红的"；**报给 QA 一行改，本窗不动别人的面**。
- ⑨ 本轮**自曝三条**（先于 QA 逮到，全文 `RELAY §九.11`）：① 重算第一次用**系统 `python`**（Anaconda `pydantic` v1 ⇒ `ImportError`）而 **rc 被 `| tail` 吃成 0** ⇒ 我把"没写成功的旧产物"当结果读了半分钟（本项目第三次撞管道吞退出码）；② r23 抽件只截到第 15 行 ⇒ `\if` 守卫块被劈断，报错形状长得像"变量写法错"；同轮把 S1 宽窗的 `t2_routed_supp` 按肉眼位数读成 4（真值 10），靠**分子分母反推**抓住 ⇒ 落笔的数改为按表头 zip 解析、取自入库件；③ 横幅第一版把**复算尺写成了自己的命中行**（`grep -c "本席位已停用"` = 2）⇒ 换 `awk 'NR==3'` 那把。
- ⑩ 🔻 **进度对表（这一行不得被读成"交付面有推进"的抵消项）**：`PASS 1/8` 未动、七格的数未换；仍欠 `OVERVIEW §6` 的四条未接线端点（A.7.1／A.7.2／A.9.3／A.9.4）、`app/present/` 空壳、`U-133`／`U-134`、§九.6／§九.7 两处器件（建议并成 `T-32`），以及**长期指令面的唯一写者定名**（本轮 `reports/qa/TASK_BOARD.md` 又被别手推进过一次，我没进那个面）。
## 第 10 轮交付（QA 第 7 轮派单 ｜ T-33 主单 ＋ T-32／③ 顺带 ｜ 2026-10-04 20:1x–20:5x +0800 ｜ **零额度、零跑批、未重建镜像、共享库只读**）

- ① **T-33 达成（数交了、判词没写）**：`U-129` 结案所必需的第二条耦合量已算成入库件
  `backend/reports/w8/t33_u130_coupling.json`（取数件 = 同名 `.py`，每条语句外层 `begin; … rollback;`）。
  **面 R（回执／request）** = 7 份带 `admission.terminal` 的入库回执逐格对表，差合计 **＋4**，全部在 A 档那一格
  （`terminal 99 − 段1 行 95`），4 条**逐条具名**并与 `deploy/loadtest/r20_internal_attribution.txt:23-26` 那 4 条
  `graph_run_failed` **集合全等** ⇒ 归 X1 崩臂（`U-129` 的缺陷面），**不算豁免**。
  **面 W（落库面／run）** = 全库 `gap_down = 0`、修法后域 `runs 30／t2 10／gap_down 0`（**非空真**）；
  反向 `gap_up = 48` 全部 `turn≥2 ∧ pre-fix`。🔴 并附**面 W 的结构性失明**那一句（崩臂两侧都不在场 ⇒ 那个 0 不等于账平）。
- ② **豁免集合按类别逐条具名**（X1 崩臂／X2 决策表 G1 fail-closed／X3 未进图＝分母纪律／X4 断流取消＝反方向／
  X5 停服排水＝豁免候选／X6 `recursion_limit` ＝ 与 `07:2879` 的 G4 行口径冲突）；每条给 `文件:行号` ＋ 当期成员数，
  其中 X2／X5／X6 **面上无样本**（要夹具才出现，本窗零额度未造）。**`U-129` 是否转绿由 QA 裁**，本窗未写"已修／已结案"。
- ③ **T-32 达成**：`gate_inputs()` 的合并支由 `{**离线, **集成}` 改成 `merge_p0_logs()`
  （四件计数两侧相加、点名列取并集、`integration_ran` 取 OR、每列留 `_offline`／`_integration` 两档）；
  **不取 max** 的依据 = 两面各一条红那种形状 max 会低估（有一条臂专门否证）。
  两态反证 ＋ **修复前对照臂**（同一对旧式必读 0）＋ 整树 `-v` 不重复相加 ＋ **八格逐格与已入库报告对表**
  ⇒ `backend/tests/eval/test_gate_inputs_p0_merge_two_state.py`（12 collected 全绿；夹具只在 `tmp_path`，共享树上不留一件）。
- ④ **③ 入库件达成**：`backend/reports/w8/gate_inputs_p0_summary.json`（两份日志的计数＋集成文件名清单＋各自 sha256/mtime
  ＋ `generated_at`／`git_rev`／`git_dirty`／`commit_count` ＋ 合并视图），生成器 = `reporter.py --emit-p0-summary`
  （尺与判定同一把）。G-1 的取证面由两件变**三件**，第三件等级 = **`self_reported`**；两份 `.log` 仍 `mtime_only`
  （`.gitignore:47` ⇒ 结构上升不了），所以对外上限是「当期重算 ＋ 自报 rev 的入库取证件在位」。
  另有一条会响的守卫：取证件与当场解析不一致 ⇒ `p0_summary_artifact.mismatch` 非空（夹具造漂移验过它会响）。
- ⑤ **判据口径变更留笔（唯一动 `docs/**` 的一处）**：`docs/07` v1.7.19 在 `§17.3` 的 G-1 行与 `§17.1` 的集成行**行内追加**；
  行数 **3,642 CRLF／裸 CR 0** 不变、改动行仅 `13`／`3253`／`3272`、§4.8 的 `:1155`／`:1157` 两行**逐字节未动**（脚本断言）。
  `U-129`／`U-130` 的判据措辞一字未改，**零取号**。
- ⑥ **上一条对撞结论退回改写**：第 9 轮那句「2,454 = 2,347＋107 ⇒ 证合并没吞红」错在**把加法当成了两列的证明**
  （`failed`／`errors` 当时是整键覆盖，加法只核验 `passed` 那一支）⇒ `OVERVIEW §6`／`§7` 与本窗 `RELAY §十.1①` 三处就地 🔻，原文不删。
- ⑦ **当期输入**：离线 **2,359 passed／0 红／rc 0／95.36s**（未给集成 DSN）＋ 集成 **107 passed／27.87s／rc 0**
  （一次性库 `ecom_t32_it`：建→授权→owner→alembic 到 `0005`（32 张表）→`-v` 跑→**当场 DROP**；残渣尺 `datname like 'ecom%'` 前后都是 **2**）。
  `总判定 PASS 1/8` 未动 ⇒ 对外仍不写"门禁通过"。
- ⑧ 静态门：mypy **147 件 no issues**、`lint-imports` **4 kept／0 broken**、ruff **`check app` 与 `check .` 双形状全绿**
  （第 9 轮那 1 条 `RUF005` 已由 QA 自修）、`eval/` 侧尺 **21 条与上一轮逐位相同**、DSN 卫生门 **8 passed**。
- ⑨ 本轮**自曝两条**（先于 QA 逮到，全文 `RELAY §十.1`）：① 那条对撞结论的解释错了（见 ⑥）；
  ② T-33 探针第一版**把 `task_path` 的第 2 段当"被路由到的节点"**（真尺是 `channel = 'branch:to:<节点>'`，与 ⑯ 同）
  ⇒ 已按正确的尺重算并登记。另有一条靠现读逮到的自漏：`build_payload()` 的取证 `paths` 映射第一次没补 `p0_summary_path`
  ⇒ 第三件在取证行显示 `no_path`，是 `eval_metrics.json` 的 `artifacts` 那行现读把我拦下来的。
- ⑩ **本轮没做／仍欠**：没重跑评测（G-2／G-5／G-8 要换数必须再打全量 ≈¥0.39，未申请）；没造 X2／X5／X6 的夹具臂；
  没补修法后的压测回执 ⇒ **面 R 的修法后域 = `UNVERIFIED`**；09-19~09-21 那 454 条零行 run 的构建身份仍 `UNVERIFIED`（= T-11②）；
  旧账四条未接线端点／`app/present/` 空壳／`U-133`／`U-134` 未动。逐条见 `RELAY §十.8`。
- ⑪ 🔻 **同轮补记：可复现自证从叙述变成实测**（详 `RELAY §十.10`）——同一套命令共跑三遍（第 1 遍在带改动的工作树，第 2／3 遍在**已提交的干净树**上，产物自报 rev `4566e84`／`ce1dec4`／报告 `d93db8f`，`dirty=False`）；递归叶子 diff = T-33 件 **16 条 ＋ 12 条**、G-1 取证件 **4 条**、`eval_metrics.json` **10 条**，**判定量 0 处差异**（八格 verdict 与 `PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2`、`gap_down 0`／`gap_up 48`／零行 cohort、shape guard、台账、残渣尺全同）。唯一与时间无关的那 2 处 = 取证件 `tracked_in_git` 否→**是**（连带未入库清单从 3 项缩到 2 项）⇒ 就是 ④ 那句「本轮提交后为是」的实测。pytest 未在这几遍重跑（两份 `.log` 的 sha256 未变）；三遍全程零额度（台账 `1,674／¥2.753794` 未动）。
