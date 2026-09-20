# 压测面（07 §16.5）—— 方案、量具、以及本轮**没有**测到的东西

归属：W7。目录内只有 `driver.py`（量具）+ 本 README（方案与回执口径）。
本文是 §16.5 要求的"**先报告再跑批**"里的那份报告；跑批状态见 §六。

---

## 一、工具选型（PROMPT §十一-1 要求先报候选）

| 候选 | 本机现状 | 判定 |
|---|---|---|
| `k6` | `command -v k6` 空 ⇒ 未装 | 不选：装它要动 dev 依赖，且它按 **HTTP 状态码**计时 |
| `locust` | 未装（`.venv/Scripts` 无入口） | 不选：同上 |
| `deploy/loadtest/driver.py`（自研，`httpx` + asyncio） | `httpx 0.28.1` 已是应用依赖 | **选它** |

⚠️ 选型的真正理由不是"省事"，是**计时对象**：`POST /query` 在**刚开始**就返回 `200 + text/event-stream`，
按状态码计时的工具测出来的是 TTFB。而 §16.5/G-6 要的是端到端。附录 A §A.1.4 规定
**唯一完成判据是 `data.terminal === true`** ⇒ 驱动必须解析到终止帧才收表。通用压测工具做不到，
用它们跑出来的"P95 达标"是**测错了对象的达标**。

驱动同时记两个数（`ttfb_ms` / `total_ms`），回执里分开列，缺一个都会让 G-6 变成假的。

---

## 二、四场景参数（`driver.py` 的 `scenario_specs()` 就是这张表）

| 场景 | 并发 | 时长/条数 | 断言对象 | 备注 |
|---|---|---|---|---|
| `steady` | 50 | 600s | ④ P95、① checkpoint 写等待 | §16.5 原文"稳态 50 并发持续 10min" |
| `burst` | 100 | 30s | ④ 突发下的 P95、`LLM_MAX_CONCURRENCY=50` 的排队形态 | ⚠️ 实现是"**100 路同时开闸并持续 30s**"，比"一次性 100 条"更严；报告里必须按实现口径写 |
| `session-lock` | 8 | 24 条同 `session_id` | 串行锁：同会话并发必须 `409 SESSION_CONFLICT`，不得两个流同时跑 | 锁在 `app/api/state_store.py`（W4） |
| `tenant-quota` | 30 | 60 条同租户 | 配额：超限必须 `429` 且**只表示配额**（`409` 不是限流） | 桶在 `app/api/ratelimit.py`（W4） |

`--no-async` 是把 `options.async_if_slow` 置 `false`，见 §四-④ 的陷阱说明。

---

## 三、前置条件核对（2026-09-19 复测：**四条阻塞已解三条**，换来三条新事实）

| # | 前置 | 2026-09-18 的状态 | 2026-09-19 复测 |
|---|---|---|---|
| 1 | 被测栈有 `query` 路由 | 在跑的 `commerceql-api-1` 是陈旧镜像（只有 `health` 路由） | ✅ **已解**：`compose.loadtest.yml` 起独立容器 `w7load-api`（宿主 18000，外部网络 `commerceql_default`，复用同 pg/redis），镜像由当前源码树构建 ⇒ 不打断 W6 的 8000 容器 |
| 2 | 库里有**合成数据集全量** | 未核对 | ❌ **实测为 0 行**：`app.order_paid` / `traffic_daily` 等 8 张底表**结构与 `v_*` 视图都在**（W1B 的 `0003_business_views`，alembic head `0005`），但一行数据都没有；容器内 `/data/sandbox/` 也是空的。这正是 07 U-56 里"数据装载**另行裁定**"那半句没人接的后果 ⇒ 本目录补了 `load_synth_to_pg.py`（见 §三.1） |
| 3 | LLM 可用且不失控 | 无授权 | ✅ 已给密钥 + 有界额度授权；`deploy/.env` 里 `DEEPSEEK_API_KEY` **原本为空**（第 35 行），已写入本机（该文件被 gitignore，不进任何提交） |
| 4 | 软依赖 embedding | `bge-m3` 不在 Ollama 模型列表 | ⏳ 中途还发现 Ollama **整个没在跑**（宿主 `:11434` 无监听）；起来后 `host.docker.internal:11434` 从容器 23ms 可达，但 `bge-m3` 仍需拉取（1.2 GB）⇒ **未拉完之前所有查询走稀疏降级**，实测表现为大量 `clarify`/`refuse` |
| 5 | pgbouncer | 未运行 | ⚠️ **两处独立缺陷**：① compose 发布 `6432:6432` 但镜像默认 `LISTEN_PORT=5432` ⇒ 该服务自加入起从未可用（已在 compose 补 `LISTEN_PORT: "6432"`）；② 修好之后应用角色仍连不上：`FATAL: server login failed: wrong password type` —— 镜像默认 `auth_query` 只能配 md5 哈希，而 W1B 的角色口令是 SCRAM。且 `auth_type=scram` **不是合法取值**（写了直接 `FATAL cannot load config` + 重启循环）。⇒ 断言③仍不可测，三条出路已上呈 RELAY |

### 三.1 装载（本轮实测读数）

`load_synth_to_pg.py` 用 W1A 的 `data/generator/seed_generator.py`（确定性、附录 C §C.12 规模）
产出的 SQLite 沙箱作数据源，机械映射 `v_X → app.X` 灌进 PG：

```
| 表 | 沙箱 | PG | 一致 |
| app.order_paid | 494249 | 494249 | ✅ |   | app.traffic_daily | 1500556 | 1500556 | ✅ |
| app.order_refund | 23116 | 23116 | ✅ |   | app.product | 6000 | 6000 | ✅ |
| app.shop | 12 | 12 | ✅ |  app.campaign 84 ✅ |  app.dim_date 730 ✅ |  app.region 31 ✅ |
[视图] app.v_order_paid 以 tenant=T_A 可读 200000 行 …（8 个视图全部可读）
```

⚠️ 装载脚本的**行数比对**不是形式主义：第一版按 psycopg2 写法调 `cur.copy(sql, iterable)`，
psycopg 3.3.5 把第二个位置参数当 `params`、返回一个**没进入的 context manager**
⇒ 八张表全部**静默灌进 0 行且不报错**。是"沙箱 vs PG 行数相等"这条比对把它抓出来的。

⚠️ 另一条只在这里看得见的事实：`app.order_paid` 上是 **FORCE ROW LEVEL SECURITY**，
策略含 `current_setting('app.shop_ids', true) = ''` —— 两个身份 GUC **都不设**时该谓词整体求值为
**NULL（不是 true）**，于是**连超级用户走视图都是 0 行**。所以"视图 0 行"不能读成"没数据"，
也不能读成"装载失败"，只说明**没给身份**。

### 三.2 已经量到的两条（不依赖 embedding，与模型下载无关）

| 场景 | 读数 | 判读 |
|---|---|---|
| ③ 单会话并发（8 路 × 24 条同一 `session_id`） | `4 × SESSION_CONFLICT`；其余 20 条完成；`wall=6.38s`、`p50=1416ms`、`max=3026ms` | 锁**确实会拒**（4 次），但 24 条同会话请求在 6.4s 内跑完（mean 1.66s）⇒ 序列化范围**小于一整轮**（`SESSION_LOCK_WAIT_MS=3000` 也可能是那批"没冲突却排队"的来源）。**作为问题转 W4，不写成"通过"** |
| ④ 同租户并发（30 路 × 30 条，5 个用户同租户） | **0 × `429`**；`22 × error_frame` 全是 `INTERNAL`；`p50=2354ms`、`p95=2468ms` | 两个结论：**(a) 当时误读为"配额桶没触发"——错**：30 并发摊到 5 个用户 = 6 请求/人，`QUERY` 桶是 **10 请求/用户/分钟**（`ratelimit.py:203`），不限流才是正确行为；真正的配额证据见 §三.3；**(b) 22 条失败已被日志证实为容量问题**：`22 × node_timeout {"node":"normalize","limit_s":2.0}` → `22 × graph_run_failed`。即 `normalize` 这个 LLM 节点的 2.0s 预算在并发 30 时被击穿（flash 单发 0.85s，`LLM_SEMAPHORE_FLASH=8` 下排队即超） |

⚠️ 读 ④ 的 latency 时注意：本驱动的 `total_ms` 统计的是**到终止帧为止**，
`error_frame` 也是终止帧 ⇒ **失败样本在延迟里**。所以"p95 2468ms ≤8s"这种读法是错的：
同期成功率只有 **8/30**。任何引用都必须把 `outcomes` 与延迟一起给。


---

## 四、必测断言 ↔ 本沙箱可判定性（§16.5"必测断言"逐条）

| 断言 | 谁产生证据 | 2026-09-19 可判定性 |
|---|---|---|
| ① 无 checkpoint 写入等待（R-10） | 独立容器跑真查询 + `lg` 表写入耗时 | ✅ **可判**（`w7load-api` 已是当前代码 + 真数据）；结论随跑批回执给出 |
| ② `SET LOCAL` 身份在连接复用时正确复位（ADR-09 验证③） | 负载下跨租户抽查：同连接先后服务不同 token，看结果是否串号 | ✅ **可判**（装载后的视图带 `tenant_id`，可用 `app.shop_ids`/`app.tenant_id` 的可见行数差做对照） |
| ③ pgbouncer 后端连接数 ≤30 | `SHOW POOLS` | ❌ **仍不可判**：进程已能起（补 `LISTEN_PORT` 后），但应用角色进不去（SCRAM vs `auth_query`，见 §三-5）。三条出路待 W1B/架构裁决 |
| ④ P95 ≤ 8s（G-6） | 本驱动的 `total_ms.p95` | ⚠️ **可判但必须与成功率同读**：并发 30 实测 22/30 失败于 `normalize` 的 2.0s 节点预算 ⇒ 只报 P95 会读成"达标" |

⚠️ **④ 的口径陷阱（必须先讲清，否则这条会"自然达标"）**：
`AskOptions.async_if_slow` 默认 `true` 且 `async_threshold_ms=8000` —— 超过 8s 的查询**转异步**，
当前这条流于是**在 8s 附近正常终止**。只看 `total_ms` 的 P95，会得出"P95 ≤8s 达标"，
而它测的是**转异步的截断点**，不是查询完成时间。
驱动因此把这类样本单列成 `async_degraded`，并在回执里带 `g6_caveat` 字段。
判 G-6 必须用 `--no-async` 跑一遍（或按 `task_id` 轮询补完真实完成时间）。
⚠️ 与 W4 的对表项：`Outcome.SWITCHED_TO_ASYNC` 在全仓**只有枚举定义、无消费方**
⇒ 目前无法从 SSE 帧上区分"真完成"与"转异步"，驱动用的是"`complete` 帧带 `task_id`/`async` 键"的启发式。
已记入 RELAY。

### 四.1 `g6_caveat` 是**机器可读的降档开关**，不是注释（09-19 补，起因是一台真假绿灯）

下游 W6 的 `eval/reporter.loadtest_pressure()` 取"各场景 `latency_ms.p95` 的最大值"，
并**只靠 `g6_caveat` 是否非空**决定 G-6 降不降档（`eval/gates.py:204`）—— 它**不读 `outcomes`**。
本目录第一版只在有 `async_degraded` 时才填这个字段，于是本轮的真实数据落进去是这个形状：

| 输入 | `ok` 完成数 | p95 | 旧 `g6_caveat` | W6 读端算得 |
|---|---|---|---|---|
| §16.5 四条口径的合成回执 | **0** | 7268.4ms | `null` | ❌ **PASS(≤8s)** |

⇒ 散文里写"P95 全是失败样本"挡不住机器口径。已改成 `_g6_caveat(outcomes)` 统一覆盖**两种**不可判情形：
① **该场景 0 条真正完成**（本轮新增，最强的那种不可判）；② 含 `async_degraded`（原有）。
`--self-check` 里加了三种情形的判向断言，并用 4 条变异验证过它真的会红（含"退回旧行为"那条）。
复算后**十份回执逐份过 W6 真读端 + 真 gates，全部 UNVERIFIED，无一例 PASS**。

---

## 五、授权状态（2026-09-19：三项全部到位，按"独立容器 + 硬上限"执行）

| 授权 | 内容 | 实际采用的形态 |
|---|---|---|
| A 被测栈 | 已批 | **不重启 W6 的 `commerceql-api-1`**：另起 `w7load-api`（独立 project、外部网络、宿主 18000）。主栈三个容器的 Up 时长未断过 |
| B 额度 | 已批（密钥只写本机 `deploy/.env`，该文件 gitignore） | **每条场景都给 `--max-requests` 硬上限**，跑完以 `app.cost_ledger` 的实测 `cost_cny` 合计结账，不靠估算 |
| C pgbouncer | 已批 | 起来了（补 `LISTEN_PORT` 之后），但应用角色口令体系不兼容 ⇒ 断言③仍不可判，见 §三-5 |

⚠️ §16.5 的 `steady` 原口径是 **50 并发 × 10min**。按并发 30 实测（单条 mean≈2.3s、且 73% 失败）外推，
跑满 10min 会产生**数千条注定失败的请求**，既无信息量又烧额度 ⇒
本轮**主动不跑满**，以"有界样本 + 失败成因"换可解释性，并把这一偏离写进报告而不是隐去。

---

## 六、执行记录

| 动作 | 命令 | 结果 |
|---|---|---|
| 量具自检 | `python driver.py --self-check` | `10/10 分类正确`，exit=0（延迟读数落在 2000–3300ms 区间） |
| 量具变异检验（5 处注入缺陷） | 仓库外一次性脚本逐条改驱动再跑自检 | **5/5 被抓**：计时停在第一帧 / 无终止帧算成功 / 4xx 算成功 / 百分位取最小 / 百分位恒 0 |
| 数据集装载 | `python load_synth_to_pg.py --sqlite … --force` | 8 张底表 **1,940,300 行**全部沙箱↔PG 行数相等；8 个 `v_*` 视图带身份可读 |
| 场景③ 单会话并发 | `driver.py --scenario session-lock` | 24 条 / `4 × SESSION_CONFLICT`，见 §三.2 |
| 场景④ 同租户并发 | `driver.py --scenario tenant-quota --max-requests 30` | 30 条 / **0 × 429** / `22 × INTERNAL`（全部 `normalize` 2.0s 节点超时），见 §三.2 |
| 场景① 稳态（5 用户） | `--scenario steady --concurrency 50 --max-requests 150` | `429 × 98` / error 50 / 5xx 2 / **完成 0**；p50 **7.3ms**、p95 2394ms（撞的是**用户桶**） |
| 场景① 稳态（150 用户，对照） | 同上 + `--tokens tokens_pool.txt` | `429 × 9`（只剩租户桶）/ error **87** / 5xx **41** / 完成 13 / **complete 0**；p50 3881 · p95 **6190** · max 7110ms |
| 场景② 突发（两组） | `--scenario burst --concurrency 100 --max-requests 100` | 5 用户：**100/100 全 429**，0.40s 泄洪完毕；150 用户：**100/100 全 error**，p50 2487 · p95 **7268** · max 7351ms |
| 停机演练（真实 app + 真实 SSE） | 40 并发跑批中途 `docker stop -t 45 w7load-api` | **66 条在途流收到注入的终止帧**（`"服务重启中，请重试"`），`truncated=0`、`conn_error=0`；`排空=yes`、退出码 **143**、stop 耗时 10.5s。首跑还抓出 43 段 `Exception in ASGI application`（本窗口自己的 drain 缺陷，已修 + 复测归零） |

⚠️ **§16.5 的稳态 10min 原口径本轮主动未跑满**：在 R1（LLM 信号量 8 vs `normalize` 2.0s 预算）与
R3（租户桶 100 请求/分钟）之下，跑满只会产生数千条注定失败的请求。这一偏离是主动选择，已写进 `压测报告.md`。

自检的桩**必须走真 TCP 环回**：`httpx.ASGITransport` 会把响应体先攒成 `body_parts` 再整体交回
（`httpx/_transports/asgi.py:158-185`），于是 TTFB ≡ total，"计时停在第一帧"这类量具缺陷**测不出来**
—— 这一条不是推演，是变异 1 在改造前**实测漏判**后发现的。

**G-6 目前仍未判定**（①②两条主场景待跑）。已经判定的两件事反而是负面的：
并发 30 时**成功率 8/30**、**配额桶未触发** —— 这两条不会因为等模型而变好。

---

## 七、复现命令（本轮实际用的那组）

```bash
cd CommerceQL/backend
# 建被测容器（不打断主栈）
docker build -f deploy/Dockerfile -t w7load-api .
cd deploy/loadtest && docker compose -p w7load -f compose.loadtest.yml up -d
# 先确认被测栈真的有 query 路由（这一条能挡掉"对着陈旧镜像压测"整场）
docker exec w7load-api grep -c "include_router" /srv/app/main.py    # 期望 5
```

```bash
cd backend
# ⚠️ 租户必须与**数据里的 tenant_id** 一致（沙箱用 T_A/T_B/T_C），
#    写成 tenant_a 会让 RLS 把所有行滤掉 ⇒ 每条都"成功返回空结果"，P95 假性很好
../.venv/Scripts/python.exe scripts/mint_dev_token.py --tenant-id T_A --user-id u_load --role analyst
export COMMERCEQL_DEV_TOKEN=<上一步 stdout 的令牌>      # 公钥已由 compose 挂载，不需要 --docker-container
```

```bash
cd ../deploy/loadtest
python driver.py --scenario steady       --no-async --max-requests 150 --questions-file questions_T_A.txt --out steady.json
python driver.py --scenario burst        --no-async --max-requests 100 --questions-file questions_T_A.txt --out burst.json
python driver.py --scenario session-lock --no-async --tokens "$TOK" --questions-file questions_T_A.txt --out lock.json
python driver.py --scenario tenant-quota --no-async --max-requests 30 --tokens "$TOK" --questions-file questions_T_A.txt --out quota.json
```

题库 `questions_T_A.txt` 由 `eval/dataset_v1_frozen.json`（附录 C 冻结集，166 例）
按 `eval_tenant=T_A` 抽出 **155 条**问句生成，**不含 gold SQL**。
⚠️ §16.5 明文"不得用缩小数据集压测"——用 `driver.py` 内置的 5 条轮转题库跑出来的数**只能**用于量具演示。
回执文件含耗时分布与状态分类，**不含查询文本与结果行**（N-11 同源关注）⇒ 可以进仓库。

**最后一步：合成 W6 读端唯一认的那一份**（`deploy/loadtest/receipt.json`）。
`--roll-up` **不发包、不花额度**，只做两件事：把分场景回执按 §16.5 口径并成单文件、并按各自
`outcomes` **就地补算** `g6_caveat`（见 §四.1，防 G-6 假绿灯）。

```bash
cd ../deploy/loadtest
python driver.py --roll-up receipt_steady_pool.json receipt_burst_pool.json \
                       receipt_lock.json receipt_quota.json --out receipt.json
# 期望输出：[合成] 4 份 → receipt.json：4 条场景 …（首次跑会顺带把输入里的 null caveat 补算写回）
```
