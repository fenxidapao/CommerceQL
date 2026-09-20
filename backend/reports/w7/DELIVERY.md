# W7 交付报告（阶段 7 · 观测与部署）

窗口：W7 · 日期：2026-09-18 · 提交标签：`feat(w7)` + `docs(w7)`
契约权威顺序：附录 A(02) > PRD(01) > 06 UIUX > 07 TDD > 08 实施计划。
压测相关的**数字与缺口**在 [`压测报告.md`](压测报告.md)，runbook 的**可执行性证据**在 [`runbook.md`](runbook.md)，
本文不重复它们，只做 DoD 判定与总账。

---

## 一、DoD 三条判定（08 §3.9）

| DoD | 判定 | 证据在哪 |
|---|---|---|
| ① 四场景压测通过 + P95 ≤8s | ⚠️ **四场景已跑完（真实额度、真实数据、真实并发），但 G-6 不可判"达标"**：50/100 并发下 `complete` 帧 **0 条**，P95 全部来自失败样本。四条根因已量化（LLM 信号量 8 vs 节点预算 2.0s / Redis 超时未映射成 500 / §16.5 与 §9.2 配额数学冲突 / embedding 不可用致零执行） | [`压测报告.md`](压测报告.md) §三 逐条读数、§四 根因；回执 `deploy/loadtest/receipt_*.json` |
| ② runbook 六条可执行 | ⚠️ **判定入口这一半已逐条真跑过（09-19）**：RL-1 §2.4/2.5、RL-2 §2.2/2.4、RL-3 §2.4/2.5、RL-5 §2.5、RL-6 §2.3 的 SQL/命令**全部可执行**，读数与判读已写回各条正文（不再是 `UNVERIFIED` 占位）；过程中还抓到并修掉 `RL-3` §4 两条**裸直方图名**判据（照抄会返回 0 序列）。**处置闭环那一半仍 UNVERIFIED**（除 RL-2 读侧外） | `runbook.md` §二 逐条 + §三 活栈读数；`deploy/runbook/RL-*` 各 §2 的"2026-09-19 实测"表 |
| ③ `/healthz` 三探针语义正确（软依赖失败必须 `200 + degraded`，N-21） | ✅ **本轮在 W7 自己的实现上活体验证过**：当前源码树构建的 `w7load-api`，`llm_reachable=true` / `embedding_reachable=false` → **HTTP 200 + `degraded_dependencies:["embedding"]`**，payload 为收敛后的 §A.8.4 `checks{}` 形状。（09-18 那版"读数来自旧镜像占位探针"的限定**已解除**） | `压测报告.md` §二 探针行；`tests/contract/test_health_endpoints_contract.py` 16 条 |

⚠️ ③ 的验证范围要说清：证到的是"**软依赖坏掉时不 503、给 200+degraded，且 payload 是 A.8.4 形状**"，
用的确实是我这一版 `probes.py`（`llm_reachable` 走 TLS 连通探测、`embedding_reachable` 走 Ollama 探维）。
**没有证到**的是"embedding 可用时的正向路径"——本机 `bge-m3` 拉取停摆，探针在这一侧只有失败分支的实测。

---

## 二、08 §3.9 七项产出 → 落点

| §3.9 产出 | 落点 | 状态 |
|---|---|---|
| ① 指标接入（§15.3 清单 + 标签基数上限） | `app/obs/metrics.py`（手写 exposition，不引 `prometheus_client`） | 23 族注册；**冷启动导出 17 族 / 262 条序列**，另 6 族属"B 类整族不输出"（无声明域且未被观测）⇒ 看板与告警**不得**把"没有这条线"读成"值为 0" |
| ② 看板 | `deploy/observability/grafana/`（datasource + provider + `dashboards/commerceql.json`，§15.5 五块面板） | JSON/`yaml` 全部离线可解析；**从未在浏览器渲染过**（本机无 `grafana/grafana` 镜像） |
| ③ 告警规则 | `deploy/observability/alert.rules.yml`（§15.4 十条 → 9 条规则 / 5 group） | 过 `promtool check rules` + `promtool test rules`；⚠️ 无 Alertmanager ⇒ "有人去 `/alerts` 看"，不是"已送达值班" |
| ④ 压测（§16.5 四场景） | `deploy/loadtest/{driver.py,load_synth_to_pg.py,compose.loadtest.yml,questions_T_A.txt,README.md}` + 8 份回执 JSON | **四场景已跑完**（真实额度 ¥0.0643 / 82 次调用、真实附录 C 全量 194 万行）。结论：`complete` 帧 0 条 ⇒ **G-6 不可判达标**，量到的是容量事实（50 并发成功率 8.7%）+ 四条根因。见 `压测报告.md` |
| ⑤ 优雅停机（§18.3 六步） | `deploy/{entrypoint.sh,drain_client.py}` + `app/obs/instrumentation.py` + `app/main.py` 追加段 + `health.py` 的 `/healthz/drain` | ✅ **真实 app + 真实 SSE 客户端复测过**（09-19，40 并发中途 `docker stop`）：66 条在途流全拿到终止帧、0 条硬断、`排空=yes`、退出码 143；顺带抓出并修掉本窗口一处 drain 日志污染缺陷。时序与证据见 §三 |
| ⑥ runbook 六条 | `deploy/runbook/README.md` + `RL-1`…`RL-6` | 见 `runbook.md` |
| ⑦ 启动校验全量（§18.4 八行） | 分散在 W0/W1B/W2A 实现，本窗口出**逐条核对表** | `deploy/runbook/README.md` §2.4（八行 × 落点/失败动作/钉死测试/本沙箱能否判） |

指标接入的**调用点缺口**不在本窗口能闭环的范围（`app/llm`、`app/graph`、`app/exec` 归 W3A/W4）：
`llm_tokens_total`、`gen_sql_rounds_total`、`retrieval_mode_total`、`llm_json_parse_failure_total`、
`ui_contract_violation_total` 等**已注册但无调用点** ⇒ 恒 0 或整族缺席。逐条要谁加哪一行，见 `RELAY.md`。

---

## 三、§18.3 时序回执（`entrypoint.sh` 尾注 forward-reference 的就是这一节）

链路与预算（compose `api` 服务 + `Dockerfile` CMD 三者自洽，由 `test_shutdown_budget_contract.py` 6 条钉死）：

```
docker stop (SIGTERM → PID 1)
  └─ entrypoint.sh trap
       1. python /srv/drain_client.py begin-wait 32      # DRAIN_BUDGET_S:-32
            POST /healthz/drain（Bearer DRAIN_TOKEN）→ 轮询 GET 直到 inflight=0 或预算耗尽
       2. kill -TERM $UVICORN_PID
       3. uvicorn --timeout-graceful-shutdown 5           # GRACEFUL_SHUTDOWN_TIMEOUT_S:-5
       4. lifespan 第二道锁：REGISTRY.drain() ≤ 30s        # app/obs/instrumentation.py DRAIN_TIMEOUT_S
       5. ObservingMiddleware 给在途 SSE 注入终止 error 帧（"服务重启中，请重试", terminal=true）
       6. 第 4–6 步的实际执行体在 app/api/runner.py 的 finally（W4 归属）
预算：32 + 5 = 37 < stop_grace_period: 40s < SIGKILL
```

实测（一次性容器 + 假 drain 端点，**不碰 W6 在用的栈**）：

| 场景 | 观察到的顺序 |
|---|---|
| 有 `DRAIN_TOKEN` | 置位**之后**在途流才逐条收尾；inflight 归零后才转发 TERM（有 TERM 前的对照组：不置位则 inflight 不降） |
| 无 `DRAIN_TOKEN` | `POST /healthz/drain` → `403`（fail-closed），**仍转发 TERM**、不卡死；启动时打 `drain_trigger_unavailable` WARN |
| 排空预算耗尽 | 打 `排空=no` 后照常退出，实测 6s ≪ 40s |

### 退出码这件事的诚实结论

优雅停机后 `docker ps -a` 显示 **`Exited (143)`**。根因是 **dash 的 `wait` 伪影**：trap 处理器跑过
（尤其它派生子进程）之后，`wait` 会**反复**返回 `128+signo`，即使子进程实际 `exit 0` ⇒
PID 1 在不用 `exec`、不加监督进程的前提下**拿不到**服务进程的真实退出码。

处置（`entrypoint.sh` 尾段，写清而不掩盖）：
· **时机**是真保证的 —— 用 `kill -0` 存活判据做有界重等（80 次 × 0.5s 上限），服务还活着时 PID 1 绝不先退；
· **码**如实报 143 并在 stderr 说明它是伪影，不伪造 0；
· **运维判据**因此改为：`143` = 正常优雅停机产物；**`137` = 被 SIGKILL = §18.3 要避免的"流被硬断"**。
这条已写进 `docker-compose.yml` 头部 ① 与 `runbook/README.md` §四-2、`RL-4/RL-5`。

### 仍未覆盖 → **已覆盖（2026-09-19 补）**

上面三路径是"一次性容器 + 假 drain 端点"。本轮用 `w7load-api`（当前源码树构建的真实 app + 真实 SSE 客户端）
在 40 并发跑批中途 `docker stop -t 45`，两侧同时取证：

| 侧 | 读数 |
|---|---|
| 客户端（驱动回执 `receipt_drain3.json`） | 120 条中 **66 条收到注入的终止帧**（`error_messages = {"服务重启中，请重试": 66}`），`truncated=0`、`conn_error=0` ⇒ **没有一条流被硬断**（§18.3 要防的正是这个形态） |
| 服务端 | `[drain] 排空=yes 预算=32.0s` → `INFO: Shutting down` → `graceful_shutdown_drained` → `[entrypoint] … status=143 …`；退出码 **143**（与本文的判据一致），`docker stop` 实际耗时 **10.5s ≪ 40s** |

⚠️ 这一跑同时**抓出本窗口自己的一个缺陷**：`_drain_stream` 发完终止帧后把 `_DrainAbort` 一路抛回 uvicorn，
于是每条被 drain 的流都留下一段 `ERROR: Exception in ASGI application` + 全栈
（首跑实测 **43 段**）。客户端没受伤，坏的是可观测性 —— runbook 与 §15.4 里"按 error 级日志计数"的
判据会被自家停机噪声整体污染。
已修（`app/obs/instrumentation.py` 的 `__call__` 就地吞掉并补一个关流帧），
复测 **traceback 归零**；契约同步改在 `test_obs_frame_format.py` 与
`test_obs_instrumentation.py`（后者带变异检验：注掉 `except _DrainAbort` ⇒ 测试变红）。

仍**未**覆盖的只剩一条：readiness 被编排层消费后真正摘走流量的端到端（本机没有消费编排器的自动重启/摘流机制）。

---

## 四、校验读数（全部本轮实测）

| 项 | 命令 | 读数 |
|---|---|---|
| 离线全量 | `pytest tests/unit tests/contract -q` | **1733 passed** |
| 本窗口新增测试 | 5 个文件 | 86 条（health 契约 16 · 停机预算 6 · obs 帧格式 10 · instrumentation 24 · 指标基数 30） |
| 分层契约 | `.venv/Scripts/lint-imports.exe`（⚠️ 必须用 exe，`python -m importlinter.cli` 会假绿，U-41） | `Analyzed 190 files, 1048 dependencies` / `Contracts: 4 kept, 0 broken` |
| 类型 | `mypy app/obs/{metrics,instrumentation,probes,samplers}.py app/api/routers/health.py` | `no issues found in 5 source files` |
| Lint | `ruff check app/obs/ app/api/routers/health.py tests/` | 本窗口文件全绿；**5 条 I001 在 `tests/eval/`（W6 未提交文件）** ⇒ 不改他人文件 |
| 停机预算的"守卫真的会拦" | 9 处变异注入（改 `stop_grace_period`、改 shell 默认值、删 trap、换 CMD 等） | **9/9 被抓，0 漏** |
| 探针并发的"守卫真的会拦" | 把 `health.py` 的 `gather` 改回串行 `await` | 红：`readiness 的探针峰值只有 1（硬依赖共 4 个）`，还原后绿 |
| 压测量具 | `driver.py --self-check` + 6 处变异（`.tmp-w7-loadtest/mutation_check.py`，临时脚手架不入库） | 自检 `exit=0`（10/10 分类）；变异 **6/6 被抓，0 漏**：计时停在第一帧 / 流结束无终止帧算作成功 / HTTP 4xx 算作成功 / **转异步出口算作完成** / 百分位取最小值 / 百分位恒为 0。脚本先跑**未注入基线**，基线不绿则整轮判"无法判定"（否则"全都红"可能只是脚本坏了）|
| 观测配置可解析 | compose + prometheus/告警/datasource/provider 共 6 yaml + dashboard JSON | 全部通过；规则另过 `promtool check rules` |
| 活栈探针读数（09-18，旧镜像） | `curl :8000/api/v1/healthz{,/live,/ready}` | `live=200 ok` · `ready=200 四项硬依赖全 true` · `healthz=200 status=degraded`（**该版实现是占位探针，不能算 W7 证据**） |
| 活栈探针读数（09-19，**W7 自己的代码**） | `curl :18000/api/v1/healthz`（当前源码树构建的独立容器） | `200` + `checks{llm_reachable:true, embedding_reachable:false}` + `degraded_dependencies:["embedding"]` ⇒ N-21 活体成立 |
| 指标面与独立量具对表 | 冒烟 + 3 次跑批之后 `curl :18000/api/v1/metrics` | `query_outcome_total{clarify,refuse,failed}` = **23 / 26 / 25**，与四次客户端回执的分类计数逐项相加**完全一致**（clarify=13+5+5、refuse=7+13+3+3、failed=22+2+1）；`stage_duration_seconds_count{executing}=0` 直接证明"零执行"不是猜的 |
| **真实抓取活体**（T2/T7 的关键补验，09-19） | 本机 `prom/prometheus:v2.54.1` 起一次性容器，抓 `w7load-api:8000`，`alert.rules.yml` 按交付的绝对路径原样挂载 | ✅ **手写 exposition 被真解析器接受**：`up=1`、`lastError=''`；✅ **5 组 / 9 条规则在活序列上 `health=ok`**（且 `state` 全 `inactive` —— ⚠️ 所以"会按预期 firing"仍未验，证据仍只有离线夹具）；✅ A/B 族分类**独立复现**：冷启 24 族 → 3 个请求后 29 族，新增 5 条全是 `http_*`；✅ `daily_cost_cny=0.064258` 与 `sum(cost_ledger.cost_cny)` **逐分相等**；✅ 计数语义对（3 个无令牌请求记成 `status="4xx"`，直方图 `_count=3`、在途归 0）。⚠️ Grafana 渲染与告警送达**仍未验**（无 `grafana` / Alertmanager）|
| 看板引用 ⟷ 实际导出 交叉核对 | 从 `commerceql.json` 抽 15 条 `expr`、11 个被引用族，与真序列清单比对 | ⚠️ 抓到**我自己 T7 的两处**：① 屏① 的 `http_requests_inflight` 冷启动必然 **No data**（B 类整族不输出）⇒ 已在 `description`/`legendFormat` 写明"No data ≠ 在途为 0"，**刻意不加 `or vector(0)`**（会抹掉这个有信息量的缺席信号）；② `RL-3` §4 两条判据原本写成**裸直方图名**（`stage_duration_seconds` / `http_request_duration_seconds`），实测裸选择器返回 **0 条序列** ⇒ 已换成 `histogram_quantile(..._bucket...)` 并加了记法约定 |
| 数据装载 | `load_synth_to_pg.py --force` | 8 表 **1,940,300 行**沙箱↔PG 逐表相等；8 个 `v_*` 视图带身份 GUC 可读（`v_order_paid` 以 T_A 可见 200,000 行） |
| **G-6 接口假绿灯（本轮最重要的一个发现）** | 拿 W6 的**真读端 + 真 gates** 复算我自己的回执 | ❌→✅ `eval/reporter.loadtest_pressure()` 只看 `g6_caveat` 降档、**不读 `outcomes`**，而驱动旧版只在有 `async_degraded` 时填它 ⇒ **0 条完成 + max p95 7268.4ms 被机器判成 G-6 `PASS`**。修法在我数据侧：`_g6_caveat()` 现覆盖"零完成/转异步"两种情形，十份回执按各自 `outcomes` 重算写回（只动派生字段），新增 `--roll-up` 合成 W6 认的 `deploy/loadtest/receipt.json`。复算后**十份全部 UNVERIFIED、无一例 PASS**。守卫本身过 **4/4 变异**（含"退回旧行为"那条）。⇒ 已发 `RELAY.md` §九，**W6 的 G-6 将由 `NOT_AVAILABLE` 变 `UNVERIFIED`**（不是变 PASS） |
| 实际额度花费 | `select count(*), sum(input_tokens+output_tokens), sum(cost_cny) from app.cost_ledger where created_at < '2026-09-19 06:21Z'` | 四场景切片：**71 次调用 / 217,675 tokens / ¥0.05613**。⚠️ token **不加** `cache_hit_tokens`（它是 `input_tokens` 的子集，`budget.py:175` 用 `max(input-cache_hit,0)` 计未命中价 ⇒ 相加会把命中前缀算两遍）。其后的停机演练追加 11 次 / ¥0.00812，**全表此刻** 82 行 / ¥0.06426 |

---

## 五、例外与越界声明（先说，别让别人发现）

1. **`app/main.py` 名义"只能追加"，本轮改了 3 行 import**：`from app.api import errors` → `errors, sse`、
   `Dependency` → `Dependency, ErrorCode, SseEvent`、`metrics` → `instrumentation, metrics, samplers`，
   并新增 `from app.obs import probes as obs_probes`（别名是必须的：lifespan 第 5 步有同名局部变量 `probes`）。
   追加段引不到符号时没有更小的改法。除这 4 行外 `main.py` 的改动全是新增块。
2. **`tests/contract/test_obs_audit_contract.py` 是本窗口改的他窗口文件**（一处断言）：
   `BOUNDED_ALLOWED_LABELS["rule_id"] == len(AstRule)` → `== len(AstRule) + 1`。
   理由：`GATE_REJECT_TOTAL` 的取值域是 `(EMPTY_LABEL_VALUE, *AstRule)` = 21 个，上界写 20 会
   **按到达顺序随机丢一类拒绝统计**。该文件其余部分未动。⚠️ 归属是 W1B 的审计契约面 ⇒ 已进 RELAY 请 W1B 复核。
3. **`.importlinter` 只补了本窗口自己的三个新模块**（`app.obs.{instrumentation,probes,samplers}` 进 R-DEP-3 左集），
   未触碰任何契约语义。
4. **工作区里有不属于本窗口的改动，本窗口一律没有 stage**（按"撞文件先报告"）：
   `backend/reports/w2-int/e2e_stage2_check.py` 处于 modified（1 行删除，**不是本窗口改的**），
   另有 `backend/reports/w6/eval_metrics.json.bak-*`（7 个）与未跟踪的 `backend/reports/arch/`。
   ⇒ 提交前 `git status` 逐条核过，本窗口那批只含 `backend/reports/w7/**`、`deploy/runbook/**`、
   `deploy/observability/**`、`deploy/loadtest/**`、`app/obs/**`、`app/api/routers/health.py`。
5. **本轮为验证临时起的资源与它们的当前状态**：一次性 Prometheus 容器 `w7prom` **已删**；
   `w7load-api` 停在 `Exited (143)`（drain 演练的正常出口）；`commerceql-pgbouncer-1` 在跑但应用角色进不去；
   ⚠️ **灌进共享 PG 的 1,940,300 行合成数据没有回滚** —— 它是 §16.5 复现的前置，也是 W6 现在可能在读的同一个库。
   **要不要清、什么时候清，属主流程决定**，本窗口不擅自动别人在用的库（`truncate` 在这儿不可逆）。
6. **本轮对着当前代码复核自己发布过的结论，订正三处**（都写在原处，不留旧版误导）：
   ① `deploy/loadtest/README.md` §四 的"async 截断点会压低 P95"这条陷阱，**在当前构建里不可达** ——
   `_should_go_async()` 因缺预估延迟载体恒 `False`（`edges.py:329`、`runner.py:51` 自证，且有契约用例钉住）。
   ⇒ 含义变了：本轮十份回执 `async_degraded=0` 是**预期结果**而非"恰好没触发"；`--no-async` 仍保留（载体一接上就复现）。
   ② RELAY 条目 6 原写"`Outcome.SWITCHED_TO_ASYNC` 全仓无消费方"——两处都不准：成员在 `ActionTaken`
   （`enums.py:469`），且有 `test_edges_contract.py` 引用。真实事实是"生产路径不可达"。
   ③ `observability` 看板屏① 的 `dependency_healthy` 原写"两步都在本窗口权限外"——**登记动作其实在我权限内**
   （`app/obs/metrics.py:124` 归 W7），只有基数上界要架构给数。原措辞把一个"等一个数"的事写成了"等两个窗口"。
   ④ 另订正一处**归因**（非本窗口文件）：G-1 那 2 条失败我先前记在"W0 的 GBK"，实际在 **W1B 的
   `test_migration_dsn_hygiene.py:166`**（`subprocess.run(text=True)` 未指定 encoding）。

---

## 六、UNVERIFIED 清单（收口必须随附）

| 项 | 为什么 |
|---|---|
| **G-6"P95 ≤8s"是否达标** | 四场景已跑完（真实额度、真实数据）但**零成功完成** ⇒ 无有效分母。已量到的是容量事实：50 并发成功率 8.7%、100 并发 0%，根因见 `压测报告.md` §四 R1/R2 |
| pgbouncer 后端连接 ≤30 | 服务已能起（补 `LISTEN_PORT: "6432"` 之前**从未可用**），但应用角色进不去：镜像 `auth_query` 只认 md5、W1B 角色口令是 SCRAM，且 `auth_type=scram` 是非法取值（直接 FATAL + 重启循环）。三条出路已上呈 |
| 断言① checkpoint 无写入等待 / 断言② `SET LOCAL` 复位**在负载下** | **不可观察**而非"不成立"：embedding 不可用 ⇒ 查询从未走到 `execute`（`stage_duration_seconds_count{executing}=0`）。侧证有（`lg.checkpoints` 4,200 行在写、审计 62 行），但那不等于"负载下无等待" |
| embedding 探针的**成功分支** | `bge-m3` 拉取停在 83%（1.8 KB/s）⇒ 只实测过失败分支的 `200 + degraded` |
| 真实 app + 真实 SSE 的一次优雅停机重启 | ✅ **已覆盖（09-19）**：40 并发中途 `docker stop`，66 条在途流全部拿到终止帧、0 条硬断、traceback 归零。见 §三 末节 |
| liveness 失败后的自动重启 | **附录 A 口径**：readiness/liveness 的**消费者**里没有编排器自动重启 ⇒ "探针就位"不等于"自愈已闭环" |
| **9 条告警规则会不会按预期亮** | 真 Prometheus 已实测到"9 条在活序列上 `health=ok`、`state` 全 `inactive`"，但**没有任何一条真正跨越过阈值**（不该为了看它亮去制造超支/超时）⇒ 判据方向**仍只有** `alert.rules.test.yml` 那 13 条离线断言作证据。另：compose 里**没有 Alertmanager** ⇒ "告警送达"这一环根本没有实现面可验 |
| Grafana 面板渲染、nginx `/metrics` 404 的活体行为 | 本机无 `grafana` / `nginx` 镜像（`prometheus` **有**，已用来做真实抓取），反代容器未起 ⇒ 渲染与 404 的活体行为未验。**但** 09-19 做完了"看板 11 个被引用族 ⟷ 真序列清单"的交叉核对，抓到屏① 冷启动必然 No data（已修文案，见 §五 校验读数末两行）|
| `retrieval_mode_total` 的降级率告警口径 | 指标**无调用点** ⇒ 比值分母为 0，当前只能靠 `/healthz` 的 `degraded_dependencies` + 日志判 RL-2 |
| 附录 D §D.4.1 的键清单 vs `Settings` 必填集 | 5 个键在代码里根本不存在（Langfuse/`TRACE_SAMPLE_RATE` 属 PRD 选配、`TOKEN_PRICE_PEAK` 已被实时计价取代）⇒ 判定标准应是 `Settings` 的 `Field(...)` 集，**待架构窗口分配编号** |
| 启动校验 PENDING 的可观测性 | `startup_assertions` 是三态（PASS/PENDING/FAIL），**PENDING 既不算通过也没有指标** ⇒ 需要 gauge，属 W1B 面，已进 RELAY |

---

## 七、与 W6 的接口（避免两边各写一份口径）

· G-6 输入 = 本窗口产出，当前值 **UNVERIFIED**；W6 门禁表请照抄这个状态而不是留空。
· 压测结果与评测结果**分开归档**（PRD §13.5）：本文与 `压测报告.md` 里没有任何准确率结论。
· 取数时点：真实压测与评测**不得同时跑**（同机 CPU、同 pg 连接池），谁先跑由主流程定。
· 本窗口**没有**改动共享栈：全程只做只读 `curl` / `docker exec` 与一次性容器，`docker ps` 三容器 Up 时长未断。
