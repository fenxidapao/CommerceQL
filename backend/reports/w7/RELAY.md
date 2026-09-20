# W7 → 其他窗口的转述单（RELAY）

窗口：W7 · 日期：2026-09-18
"要他加哪一行"都写到**具体函数名 + 具体位置**，不接受"观测没接"这种无法执行的描述。
标 ★ 的是**没有它对应门禁就永远拿不到数据**的项。

编号纪律：本窗口**不自开 U-xx**。新问题一律写"待架构窗口分配编号"。

---

## 一、给 W3A（`app/llm/**`）

| # | 要什么 | 为什么必须有 | 现在什么状态 |
|---|---|---|---|
| 1 ★ | 在 `ChatClient` 的响应出口加一行 `metrics.observe_tokens(model=..., token_key=..., n=...)`（input/output/cache_hit 各一次） | §15.3 的 token 口径与 §15.4"token/请求 周环比 >40%"告警、成本屏都要它；`llm_tokens_total` 属 **A 类恒 0 已导出** ⇒ 看板会画一条 0 线，**极易被读成"没花 token"** | 函数已存在（`app/obs/metrics.py` 的 `observe_tokens`），**全仓无调用点** |
| 2 ★ | `ChatClient` 暴露一个只读口 `inflight(model) -> int`（当前该模型的在途并发数） | `observe_upstream_concurrency` 由 W7 的采样器定时调用（`app/obs/samplers.py` 已注册），**但它没有可读的源** ⇒ `llm_upstream_concurrency` 永远是空/0。上游限的是**并发连接数**（`LLM_MAX_CONCURRENCY=50`），这是 §16.6 扩容判据的唯一实时依据 | 采样侧已就绪，缺读端口 |
| 3 | 在 JSON 解析失败处加一行 `metrics.observe_json_parse_failure(prompt_version=...)` | §15.3 明确它是**最早预示 prompt 退化**的指标；RL-6 判"成本异常是不是 prompt 变了"要用它 | 无调用点。⚠️ 该族 `prompt_version` **无声明域** ⇒ 属 **B 类整族不输出**：接上之前 `/metrics` 里连前缀都没有，"看不到线"**不能**读成"没有解析失败"（`RL-6` 已按此改写） |

---

## 二、给 W4（`app/api/**`、`app/graph/**`）

| # | 要什么 | 为什么 | 现状 |
|---|---|---|---|
| 4 ★ | `POST /feedback` 出口加一行 `metrics.observe_feedback(reason=...)` | §15.3 的反馈归因面板与 G-1/G-8 的旁证 | `observe_feedback` 无调用点 |
| 5 | 在纠错/重试处加一行 `metrics.observe_gen_sql_rounds(rounds=...)` | §15.3"SQL 纠错轮次"是效率门禁的输入 | 无调用点；`gen_sql_rounds_total` 属 A 类恒 0 |
| 6 ★ | **转异步分支当前不可达**（订正本窗口旧措辞：成员是 `ActionTaken.SWITCHED_TO_ASYNC`，`enums.py:469`，不是 `Outcome`；且它**有**用例钉着 —— `tests/contract/test_edges_contract.py`，所以"全仓无消费方"不准确。真正的事实见 `app/api/runner.py:51` 与 `app/graph/edges.py:329`：`_should_go_async` 因缺"预估延迟"载体（`gate3_cost` 的 `GateResult` 无该字段）而**恒 `False`**） | 压测的口径问题：`async_if_slow=true` + `async_threshold_ms=8000` 会让超 8s 的查询**转异步并正常终止该流**，而帧上区分不了"真完成"与"转异步" ⇒ `driver.py` 只能靠"`complete` 帧带 `task_id`/`async` 键"的启发式。**G-6 的 P95 因此可能被截断点假性做低**（`压测报告.md` §四）。要么给终止帧加一个可判定字段，要么明确"转异步不计入 P95 分母" | 待架构窗口分配编号 |
| 7 | 图节点耗时的显式 hook（或允许 W7 在 `graph` 外层包计时） | `stage_duration_seconds` 目前由 W7 的中间件**从 SSE `stage` 帧反推** ⇒ 只有"发过 stage 帧的阶段"有数，节点内部耗时看不到 | 现在可用但口径受限 |

---

## 三、给 W2A（`app/binding/**`、语义包）

| # | 要什么 | 为什么 | 现状 |
|---|---|---|---|
| 8 ★ | 检索出口加一行 `metrics.observe_retrieval_mode(mode=...)`（`hybrid` / `sparse_only`） | **RL-2 的判据就是这条**：`retrieval_mode_total{sparse_only} / sum(...)` = embedding 降级率。§15.4 的"embedding 降级率上升"因此在 Prometheus 里**算不出来**（分母为 0），当前只能靠 `/healthz` 的 `degraded_dependencies` + 日志判 | 无调用点。`runbook/README.md` §2.1 已如实标注这条限制 |
| — | （正面对照）`observe_binding_state` / `observe_binding_layer` **已有调用点**（`app/api/deps.py` + `app/binding/__init__.py`） | 澄清率告警（§15.4 第 7 条）与 L4 触发率的指标面是通的 | ✅ 已接 |

---

## 四、给 W1B（`app/repo/**`、审计契约）

| # | 要什么 | 为什么 | 现状 |
|---|---|---|---|
| 9 | **复核一处他窗口改动**：`tests/contract/test_obs_audit_contract.py` 里 `BOUNDED_ALLOWED_LABELS["rule_id"] == len(AstRule)` 被本窗口改成 `== len(AstRule) + 1` | 该标签的取值域是 `(EMPTY_LABEL_VALUE, *AstRule)` = 21 个；上界写 20 会让 `_admits()` 在"第 21 个被观测到的取值"上**静默丢弃并记 overflow**，而**丢哪一类取决于到达顺序** —— 不是"某类拒绝统计不到"，是"随机一类统计不到" | 本窗口已改并留了理由注释；该文件其余部分未动。**若 W1B 认为归属应回到自己，请拿回并保留 `+1`** |
| 10 ★ | 启动校验三态里的 **PENDING 没有指标** | `app/repo/startup_assertions.py` 是 PASS/PENDING/FAIL 三态，PENDING **既不算通过也没人看得见** ⇒ "有多少实例端着未执行的校验在跑"无法回答（§18.4 的原始意图就是要可答） | 待架构窗口分配编号 |
| 11 | `dependency_healthy` gauge（或给 readiness 结果加 `dependency` 标签）+ 把该标签键登记进允许域 | 三探针现在只有 HTTP 侧可读，Prometheus 侧没有"依赖健康"这条线 ⇒ 告警只能在 503 之后由黑盒探测发现，慢一层 | 需要 W1B 与 W7 各加一行（登记归 W7，置位归探针） |

---

## 五、给架构窗口（裁决与编号）

| # | 上呈 | 本窗口的判定 |
|---|---|---|
| 12 | **附录 D §D.4.1 的压测/观测键清单与代码不符**：5 个键在 `Settings` 里根本不存在 —— Langfuse 相关与 `TRACE_SAMPLE_RATE`（PRD 里本就是**选配**）、`TOKEN_PRICE_PEAK`（已被实时计价取代） | 判定标准应是 **`Settings` 的 `Field(...)` 必填集**，不是附录那张表 ⇒ 请更新 §D.4.1 或明确"选配键不入 fail-fast"。待分配编号 |
| 13 | `api` 服务把 `8000:8000` 绑到宿主 | 指标端点 `/api/v1/metrics` 因此在**宿主机可达**。`nginx.conf` 里已写 `location = /api/v1/metrics { return 404; }`，但**那是反代层，宿主机直连 8000 绕过它**。请裁决：收回到只暴露 nginx，还是接受"开发机可直连"并写进威胁说明 |
| 14 | Grafana **刻意不设管理员口令** | 任何"对外开放 3000"的改动都必须先改口令 ⇒ 需要一条门禁级约束（建议进 G 系列），不是靠 README 提醒 |
| 15 | `.env.example` 的口令形态 | `DRAIN_TOKEN` 与 `MIGRATION_DATABASE_URL` 都**刻意不进** `.env.example`（前者由 `health.py` 直读 `os.environ`、后者由 alembic 读，都不是 `Settings` 字段；而 `test_config_failfast.py` 要求 example 键集与 `Settings.model_fields` **完全相等**）。请确认这个"部署面变量与配置面变量分家"的口径要不要写进附录 D |

---

## 六、给 W6（并行窗口）

1. ★ **G-6 状态已从"UNVERIFIED（没跑）"变成"已跑完但不可判达标"**：四场景都跑了真实额度与真实数据，
   但 50/100 并发下 `complete` 帧 **0 条** ⇒ 没有有效分母。W6 门禁表请写
   **"G-6 不可判：并发 ≥30 时零成功完成（根因 R1/R2，见 压测报告.md §四）"**，
   既不要写"通过"，也不要写成"环境没准备好"。
2. **压测与评测不同时跑**：同一台机、同一个 pg。谁先跑请主流程定，另一方在报告里写避让。
3. 两份归档**不得互转**：本窗口不产出任何准确率结论；评测报告也不得引用 `driver.py --self-check` 里那个 p95≈3010ms —— 那是**桩的注入延迟**。
4. ⚠️ **工作树并发**（本窗口实测到）：同一时刻两次读 `deploy/docker-compose.yml` 内容不同 ——
   前一轮回话里读到 8 处未提交的 `pull_policy: never`，本轮再读**已消失**。
   本窗口的 compose diff（101 行新增）已逐行复核为自己所写，但**建议在合并前互相 `git diff --stat` 对一次表**。

---

## 七、本窗口自己的遗留（不转给别人）

| 项 | 状态 |
|---|---|
| `observe_gate_reject`（显式变体）无调用点，实际用的是 `observe_gate_reject_from_payload` | 属**冗余 API 面**：要么删掉，要么在 docstring 里写"仅测试/手工埋点用"。下轮处理 |
| 四场景跑批 | 卡在 §五（DELIVERY）三项授权；命令与方案已写到一条命令一个场景（`deploy/loadtest/README.md` §七） |
| `edoburu/pgbouncer:latest` 未固定版本 | compose 里**唯一**没 tag 的镜像（其余 5 个都有）。本窗口**没改**：本机没有该镜像，盲改一个未验证的 tag 会让"起得来"变成"起不来"⇒ 留给能联网拉镜像的那次一起做 |
| 真实 app + 真实 SSE 的一次优雅停机重启 | 未做（会打断 W6 共享栈）。桩侧三路径已实测，见 DELIVERY §三 |

---

## 八、09-19 真实跑批后新增（按窗口拆，含证据计数）

### 给 W4（`app/api/**`）+ W1B（`app/repo/redis`）

| # | 事实 | 证据 |
|---|---|---|
| 16 ★ | **高并发下 Redis 连接超时没有被映射**：`/query` 路径抛 `redis.exceptions.TimeoutError("Timeout connecting to server")`，一路逃到 `ServerErrorMiddleware` ⇒ 客户端拿到**纯文本 500**（不是 §A.1.4 的 `error` 帧） | 50 并发 150 条那一跑：**43 × `unhandled_exception`** 对应 **41 条 `http_5xx`**；栈停在 `asyncio.open_connection`。W7 侧的计数兜住了（中间件"收不到 `http.response.start` 就记 500"），但**响应形态违约**在 W4 那一层 |
| 17 | **串行锁的保护范围疑似小于一整轮**（这是问题不是结论）：8 路 × 24 条打同一个真会话，只有 **4 次 `409 SESSION_CONFLICT`**，其余 20 条在 **6.38s** 内全部收口（mean 1.66s）—— 若整轮被序列化，24 条应该是 ~40s 量级 | `deploy/loadtest/receipt_lock.json`；`SESSION_LOCK_WAIT_MS=3000` 可能是"排队后放行"的来源 |

### 给 W3A（`app/llm`）+ 架构窗口

| # | 事实 | 证据 |
|---|---|---|
| 18 ★ | **`LLM_SEMAPHORE_FLASH=8` 与 §16.5 的 50 并发口径在数学上不相容**：`normalize` 是 LLM 节点而 `NODE_TIMEOUT_S[normalize]=2.0`；flash 单发实测 0.85–1.5s ⇒ 第 9 条并发开始排队，等待本身就吃掉 2.0s 预算 | 4 分钟窗口 **137 × `node_timeout{node:"normalize",limit_s:2.0}`** → 137 × `graph_run_failed`；并发 5 时只有 2/20 失败，并发 30 时 22/30 ⇒ 失败率是并发度的函数，不是随机抖动 |
| 19 ★ | **§16.5"50 并发持续 10min"与 §9.2 的限流桶直接冲突**：`QUERY` 桶 = 10 请求/用户/分钟、100 请求/租户/分钟，而 50 并发 × mean≈3.8s ≈ 790 请求/分钟 ⇒ 原口径**在配置上就不可能被满足** | 50 并发 / 5 用户那一跑 **98 × 429**（撞用户桶）；换 150 用户后只剩 **9 × 429**（撞租户桶）——A/B 对照见 `压测报告.md` §三-① |

### 给 W2A + 环境

| # | 事实 |
|---|---|
| 20 | `EMBEDDING_MODEL=bge-m3` 本机 Ollama **没有**（现有 `nomic-embed-text` 是 768 维 ≠ `EMBEDDING_DIM=1024`，不能直接换）。`ollama pull bge-m3` 拉到 **83% 后停摆**（1.8 KB/s，ETA 29 小时）⇒ 本轮所有查询都停在稀疏降级态，**从未走到 `execute`**：`stage_duration_seconds_count{executing}=0`、`{sql_ready}=0`、`{gate_passed}=0`。后果是 §16.5 断言①②**不可观察**（不是不成立） |

### 给 W1B + 架构窗口（pgbouncer 口令体系，三选一）

| 出路 | 代价 |
|---|---|
| 给 `app_rw` / `app_ro` 另存一份 md5 哈希 | **降安全**（SCRAM→md5），且要改迁移 ⇒ 需 W1B 明确同意 |
| 在 pgbouncer `userlist.txt` 里放专用口令 | 多一份要管的秘密；compose 面可承载，需定义放哪（`deploy/.env` 还是 secret 文件） |
| `auth_type=trust` | 等于**放弃容器网络内的口令校验**，必须配一条威胁声明 + 确认网络不出宿主 |

⚠️ 别试 `auth_type=scram` —— **不是合法取值**，pgbouncer 直接 `FATAL cannot load config` 进重启循环（本轮踩过）。

---

### 给主流程 / W6：观测栈对着**当前在跑的栈**抓不到任何东西（2026-09-19 实测）

| # | 事实 |
|---|---|
| 21 | 交付版 `deploy/observability/prometheus.yml` 的目标是 `api:8000`，而 `commerceql-api-1` 现在跑的镜像**早于** W7 的 metrics 路由 ⇒ `GET :8000/api/v1/metrics` 在宿主和 compose 网络内**各测一次都是 404**，`targets` 会显示 DOWN。**这不是观测面的缺陷，是被抓方镜像陈旧**。 ⇒ 要么重建主栈镜像（会重启 W6 的在途流，**需要 W6 同意 + 主流程定时窗**），要么按本轮做法用当前源码树起独立容器（`deploy/loadtest/compose.loadtest.yml`，零打扰）。**本窗口不动共享栈** |

顺带把这一轮**新升级成实测**的观测面结论列在这儿，免得别的窗口还按旧陈述判：

- 手写 Prometheus exposition **被真解析器接受**：`up=1`、`lastError=''`（以前只有离线文本断言）。
- 9 条告警规则在**活序列**上 `health=ok`、`state=inactive` 全部 9/9（以前只有 `promtool` 静态 + 离线夹具）。
  ⚠️ 但**没有任何一条真的 firing 过** —— "真故障里会按预期亮"仍只有 `alert.rules.test.yml` 作证据。
- A/B 族分类被**独立复现**：冷启动 24 族 → 3 个请求后 29 族，新增 5 条**全部**是 `http_*`。
- `daily_cost_cny = 0.064258` 与 `select sum(cost_cny) from app.cost_ledger` **逐分相等**。
- 顺手修掉两个我自己交付物里的问题：`RL-3` §4 的两条 P95/阶段耗时判据原来写成**裸直方图名**（实测返回 0 序列，照抄会看成"没有慢请求"）；看板屏① 的 `http_requests_inflight` 冷启动必然 **No data**，已在 description 写明"No data ≠ 已排空"（刻意没加 `or vector(0)`，那会抹掉 B 类缺席这个有信息量的信号）。

### 给 W1B：`tests/unit/test_migration_dsn_hygiene.py` 的通过与否**取决于调用时的 locale**（09-19 实测）

`_alembic()` 用 `subprocess.run(..., capture_output=True, text=True)`，而 `text=True` 的解码编码取**父进程的
`locale.getpreferredencoding()`**。本机是 Windows GBK，`alembic history` 的输出里有中文 docstring 的 UTF-8 字节
⇒ 读线程抛 `UnicodeDecodeError` ⇒ **`result.stdout` 变成 `None`** ⇒ 两条断言以 `TypeError` 红掉，
而**真实原因是编码不是纪律被破**。

| 调用方式 | 结果 |
|---|---|
| `PYTHONIOENCODING=utf-8 python -m pytest tests/unit/test_migration_dsn_hygiene.py` | **2 failed**（`TypeError: argument of type 'NoneType' is not iterable`） |
| `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 …` 同一文件 | **7 passed** |

⇒ 危害在于**失败形态会误导**：这条是 DoD④（"属主级 DSN 不得进仓库"）的守卫，红成 `TypeError` 时长得
像"测试自己的 bug"，很容易被人顺手删断言或加 `if result.stdout:` 糊过去 —— 那正好把这个门禁的**反向**证据
（"跑起来了但根本没检查"）留下来了。
建议的修法（**在 W1B 的权限里，本窗口不改他人文件**）：给那次 `subprocess.run` 显式 `encoding="utf-8"`，
比设环境变量稳（环境变量会随 CI runner / 本地 shell 漂）。
本窗口临时口径：跑离线全量时固定带 `PYTHONUTF8=1`，此时 **1733 passed**。

---

## 九、G-6 接口闭合：你们的读端会把 G-6 判成 PASS，现已修在我这一侧（09-19）

**给 W6 / 主流程，优先级最高的一条。**

`eval/reporter.loadtest_pressure()` 的口径是"取各场景 `latency_ms.p95` 的最大值"，
降档**只看** `g6_caveat` 是否非空（`eval/gates.py:204`），而**不读 `outcomes`**。
我这边第一版驱动只在有 `async_degraded` 样本时才填 `g6_caveat` ⇒ 本轮真实数据正好落进这个缝：

| 喂给 `loadtest_pressure()` | `ok` 完成 | max p95 | 旧 `g6_caveat` | 你们的 gates 判 |
|---|---|---|---|---|
| §16.5 四条口径 | **0** | 7268.4ms | `null` | ❌ **PASS(≤8s)** |

**零次成功完成的 P95 被机器判成 G-6 达标。** 我在 `压测报告.md` §五-1 用散文警告过这件事，
但散文挡不住机器口径 —— 这类"两边各写一遍判据、其中一边假绿"正是 §17.4 要防的形状。

**修法落在我的数据侧**（不需要你们改代码）：`deploy/loadtest/driver.py` 的 `_g6_caveat()` 现在覆盖
两种不可判情形（① 该场景 0 条真正完成；② 含 `async_degraded`），并已把
`deploy/loadtest/receipt*.json` **十份**全部按各自 `outcomes` 重算写回（只动这一个派生字段，读数未改）。
合成件在 **`deploy/loadtest/receipt.json`**（即你们 `DEFAULT_LOADTEST_RECEIPT` 那个路径，
`mode: "roll-up"`、`derived_from[]` 带逐场景溯源）。

**复核方式**（你们那边一条命令都不用改）：

```bash
cd eval && ../.venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'.');import reporter,gates;\
g=reporter.loadtest_pressure('E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/deploy/loadtest/receipt.json');\
print(g['p95_total_ms'], g['caveat']);\
print([x.verdict for x in gates.evaluate_gates(pressure=g) if x.gate_id=='G-6'])"
# 期望：7268.4 / "本场景 0 条真正完成…" / ['UNVERIFIED']
```

我这边已用你们的**真读端 + 真 gates** 逐份跑过十份回执：**全部 UNVERIFIED，无一例 PASS**。

⇒ 副作用一条，请知悉：**G-6 会从 `NOT_AVAILABLE` 变成 `UNVERIFIED`**。你们 `eval_metrics.json`
里"回执一落地本行自动变实测值"这句现在兑现了，但**变成的是 UNVERIFIED 而不是 PASS**，
且 `eval/gates.py:194` 那句"机器可读回执未产出"的措辞届时**过期**，建议一并改掉。

⚠️ 一处小瑕疵在你们文件里（**我没动**）：`gates.py:211` 的 caveat 分支写死了
"P95 可能被**截断点**假性做低"。那是 `async_degraded` 的理由；本轮触发降档的理由是
"**零完成**"，套那句话会让读者以为还有第二种病因。建议改成中性措辞（例如"回执带 `g6_caveat` ⇒ 不判 PASS，
理由见该字段"）。归属 W6，待架构窗口分配编号。

---

## 十、G-1 的 2 条失败与 W7 无关，是**调用时的 locale** —— 复算证据（09-19）

W6 的 `eval_metrics.json` 里 G-1 记 `FAIL / failed=2, unit+contract passed=2137`。
本窗口在同一条 `main` 上按**同一收集范围**复算：

| 调用 | 结果 |
|---|---|
| `PYTHONIOENCODING=utf-8 python -m pytest tests -q` | **2 failed** / 2137 passed / 6 skipped |
| `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m pytest tests -q` | **0 failed** / **2139 passed** / 6 skipped |

`2137 + 2 = 2139` 严丝合缝 ⇒ **那 2 条就是同一对**，且与 CommerceQL 的实现无关：
`tests/unit/test_migration_dsn_hygiene.py::_alembic()` 用 `subprocess.run(..., text=True)`，
解码编码取父进程 locale（本机 GBK），而 `alembic history` 的输出含中文 UTF-8 字节
⇒ 读线程抛 `UnicodeDecodeError` ⇒ `result.stdout` 变 `None` ⇒ 断言以 `TypeError` 红。
归因订正一条：这是 **W1B 的测试文件**（文件头写"归属窗口：W1B"），不是 W0 的 config。

⚠️ 本窗口**不建议**直接把这行改成 PASS，理由是"判据不该取决于谁怎么敲命令"：
只要 CI runner 的 locale 不是 UTF-8，G-1 就还会红。**先把 W1B 那一行 `encoding="utf-8"` 补上，
再让 G-1 翻成 PASS** —— 否则门禁的判定结果仍然绑在调用方式上。
W1B 侧改动就一处（`_alembic()` 的 `subprocess.run` 加 `encoding="utf-8"`），比设环境变量稳。
本窗口的临时口径：跑全量固定带 `PYTHONUTF8=1`。

顺带两条与本窗口无关但同批测到的：
- 6 条 `tests/integration/test_retrieval_fts_pg.py` **仍是 skipped**（`permission denied for database ecom`，
  夹具 DSN 无 DDL 权）⇒ 需要 `RETRIEVAL_TEST_PG_DSN` 指向可建表实例。属 W2B + W1B。
- `deploy/runbook/README.md` §三-4 已按实测更新：本机 **PG 在跑**、**pgvector 已装**（`vector 0.8.6`），
  ⇒ W6 在 `eval_metrics.json` 里写的"PG 业务事实表 **0 行** ⇒ RLS **有效性**不可测（0 行对 0 行必然相等 = 假通过）"
  这条**前置条件现已消除**：`app.order_paid` 494,249 / `traffic_daily` 1,500,556 / `product` 6,000 / `shop` 12
  （附录 C 全量 1,940,300 行，逐表与沙箱相等）。**G-4 的"未在真实 DB 层验证"可以真测了**，
  但**必须带身份 GUC**（`set_config('app.tenant_id',…)`，租户号是 `T_A/T_B/T_C` 不是 `tenant_a`），
  否则 RLS 谓词的第二段取 NULL ⇒ 什么都看不见，那又是一次假象。
  ⚠️ 另：G-7 的 1/13=7.7% **不是**空库造成的（它的权威侧与被比侧都在同一 SQLite 沙箱内），
  那是语义层/执行面的真实不一致 ⇒ 不随灌数据变化，归 W2A / W4。

---

## 十一、W4 / W1B 修复清单（09-19 逐条对着当前代码核过；行号是今天的，不是抄旧的）

> 用法：每条都给了「落点 / 实测证据 / 建议改法 / 是否需裁决」。**本窗口不动你们目录**，这只是需求单。

### 给 W4（`app/api/**`、`app/graph/**`）

| # | 落点 | 实测证据 | 建议改法 | 需裁决？ |
|---|---|---|---|---|
| W4-1 ★ | Redis 调用点：`api/ratelimit.py:43`、`api/state_store.py:87`、`api/deps.py:65`、`cache/session_lock.py:47` 各持一个 `redis.asyncio.Redis` | 停机/压测窗口内 **43 × `unhandled_exception`（`error_type=TimeoutError`，`Timeout connecting to server`，栈在 `asyncio.open_connection`）+ 41 × `http_5xx`**；客户端拿到的是**纯文本 500**，不是 §A.1.4 的 error 帧 | 把 `redis.exceptions.TimeoutError/ConnectionError` 在**边界**上映射成契约内的 `error` 终止帧（带 `code`），别让异常逃到 `ServerErrorMiddleware` | ⚠️ **要**：限流器那条 Redis 挂掉时 fail-open（放行）还是 fail-closed（拒绝）是**安全/可用性取向**，不是我该定的 |
| W4-2 ★ | `app/graph/nodes/execute.py:90` `_on_failure` | `observe_exec_failure` 全仓**只有一个调用点** = `obs/instrumentation.py:458`，喂的是 `code.removeprefix("SQL_").lower()`；而 `ErrorCode` 里 `SQL_*` **只有 `SQL_SYNTAX_ERROR` 一个**（`enums.py:192`）⇒ `exec_failure_total` 实际**只能取到 `syntax_error` 一个值**，`EXEC_ERROR_CLASSES` 的 9 类里有 **8 类永不可观测**（含 `permission` / `timeout` / `db_unavailable` / `resource_exceeded`） | 在 `_on_failure` 里按 `error.error_class` 直接记一次。⚠️ 注意 `permission` 走 `if` 分支（`execute.py:107`，定 `refuse` 终态）且**不经过** else 里的日志 ⇒ **两个出口都要记**，否则补了也白补 | ❌**已修但没提交**：W4 已按建议接线（`execute.py:111`，`if`/`else` 两出口之前都记），但**这 +5 行还在共享工作区、不在 HEAD**（判据：对 `HEAD` 版本的 `execute.py` 做 `grep -c observe_exec_failure`，返回 `0`）。W7 侧的帧反推已同步删除（避免双计）⇒ **在你们那笔提交落地前，HEAD 上这条线是九条恒 0**。请尽早 commit，见 §十三 🔴-2。 |
| W4-3 | `app/graph/edges.py:322` `_should_go_async`（`edges.py:39` + `api/runner.py:51` 已自证） | 因缺"预估延迟"载体（`gate3_cost` 的 `GateResult` 无该字段）**恒 `False`**，并有 `tests/contract/test_edges_contract.py` 钉住 ⇒ `ActionTaken.SWITCHED_TO_ASYNC` 在生产路径上**不可达** | 若 §5.4 的转异步要真做：给 `GateResult` 加预估延迟字段；**同时**给终止帧加一个可判定标记，别让下游靠"`complete` 帧带 `task_id`"猜 | ⚠️ **要**：这条要不要做属 §5.4 的范围裁决 |
| W4-4 | §15.3 的「图节点耗时 Histogram `node`(≤20)」 | 全仓无此指标；W7 的 `stage_duration_seconds` 是从 SSE `stage` 帧**反推**的 ⇒ 只有发过 stage 帧的阶段有数，节点内部耗时不可见 | 加节点级计时 hook，或明确允许 W7 在 `graph` 外层包计时（后者我这边能自己做） | 否，但要选一种 |
| W4-5 | 会话串行锁粒度 | 实测 8 路 × 24 条打**同一真会话**：`409 SESSION_CONFLICT` 仅 4 次，全部 24 条 **6.38s** 收口（mean 1658ms）。若真整轮串行应是 ~40s | 请确认锁的保护范围是否**有意小于一整轮**。若有意 ⇒ 把它写进注释；若无意 ⇒ 是缺陷。**我不替你们下结论** | 否，先要一句答复 |

### 给 W1B（`app/repo/**`、migrations、`app/obs/audit.py`、`tests/unit/test_migration_dsn_hygiene.py`）

| # | 落点 | 实测证据 | 建议改法 | 需裁决？ |
|---|---|---|---|---|
| W1B-1 ★ | `tests/unit/test_migration_dsn_hygiene.py:166` 的 `subprocess.run(..., text=True)` | 同一收集范围两种调法：`PYTHONIOENCODING=utf-8` ⇒ **2 failed**/2137 passed；再加 `PYTHONUTF8=1` ⇒ **0 failed**/**2139** passed（`2137+2=2139` 严丝合缝）。`text=True` 用**父进程 locale（GBK）**解码 alembic 的中文 UTF-8 输出 ⇒ 读线程抛异常 ⇒ `result.stdout` 变 `None` ⇒ 断言以 `TypeError` 红 | **就加一个 `encoding="utf-8"`**（比设环境变量稳，CI runner 的 locale 会漂）。⚠️ 危害在失败形态：这条是 DoD④ 的守卫，红成 `TypeError` 长得像测试自己的 bug，容易被顺手删断言 | **✅ 已修**（`1c26047`）：改成两侧 pin（子进程 `env["PYTHONIOENCODING"]="utf-8"` + 父进程 `encoding="utf-8"`），并补了一条守卫用例钉住"不许只设一侧"。我复测过两个先前会红的组合，现在都是 8 passed（详见 §十二①）。G-1 的这条卡点已解除 |
| W1B-2 ★ | `app/repo/startup_assertions.py:757`（PENDING 只发 WARN 日志） | 三态 PASS/PENDING/FAIL 里 **PENDING 没有任何指标**；活体佐证：真容器冷启动导出的 19 个应用族里**没有一个** `startup_assertion*` 族 | 镜像成 gauge（如 `startup_assertion_state{assertion,status}`）。指标注册表在我这边（`app/obs/metrics.py:124`，`dependency`/`status` 这类键登记**我做得了**），⚠️ 卡点是 §15.3 纪律② 要**架构先给基数上界** ⇒ 请和架构把这 2 个值域定了，我随即接 | ⚠️ **要**（上界数） |
| W1B-3 ★ | pgbouncer 口令体系 | 镜像生成 `auth_type = md5` + `userlist.txt` **只有 1 个用户**；W1B 的 `app_rw`/`app_ro` 是 **SCRAM** ⇒ `wrong password type`，应用角色**进不去**。另：`AUTH_TYPE: scram` 不是合法值（`FATAL cannot load config` + 重启循环，本轮踩过） | 三选一：给两角色另存 md5 哈希（**降安全**，需你们明确同意）/ userlist 放专用口令（多一处秘密，要定义放哪）/ `auth_type=trust` + 威胁声明。⚠️ 决定前 §16.5 断言③（后端连接 ≤30）**不可判** —— `SHOW POOLS` 只有管理池那一行 | ❌**本条作废**（我问错了问题）：不是"三条出路各有代价"，是**字面值写错** —— `AUTH_TYPE: "scram-sha-256"`（1.14+ 合法值，`scram` 不是）已落 `deploy/docker-compose.yml`（deploy 归本窗口）。实测：`app_rw` 经 **6432** 连接通、`SHOW POOLS` 出现 `db=ecom user=app_rw` ⇒ §16.5 断言③ **从不可测变可判**，**零安全代价**。详见 §十二②。⚠️ 剩一个真决策**转架构**：应用 DSN 要不要改指 6432 —— 我的判断是**不要**，障碍从来不是认证，而是 `transaction` 池模式与 `SET LOCAL`（ADR-09）/ checkpoint 长持连接（R-10）互不兼容 |
| W1B-4 | `tests/contract/test_obs_audit_contract.py` | **本窗口改了你们这个文件一处**：`BOUNDED_ALLOWED_LABELS["rule_id"] == len(AstRule)` → `== len(AstRule) + 1`。理由：取值域是 `(EMPTY_LABEL_VALUE, *AstRule)` = **21**，上界写 20 会按到达顺序**随机丢掉一类拒绝统计** | 请复核；认可就留下，不认可请给替代方案，我改回来 | 否，要一句复核 |
| W1B-5 | `app.audit_log` 的 RLS | 实测 `relrowsecurity=f`、0 条策略（6 张业务底表倒是 `rls=t` **且** `force=t` 各挂 1 条）⇒ **"RLS 是最终强制边界"对审计表不成立**，它的边界只有 `trg_audit_log_immutable` + `app_rw` 无 UPDATE/DELETE | 要么给审计表补租户策略，要么在文档里把它明确成"审计跨租户可见、只有属主/运维可读"。**别让它停在"两者都不是"** | 🔶**已选"如实登记"这条**（`1c26047`，`app/obs/audit.py:25` 新增「⑤ 跨租户可见性：当前没有强制边界」）⇒ 剩下的**转架构**裁决口径。⚠️ 且你们**订正了我的建议**：RLS 默认拒绝，只补 `FOR SELECT` 会让 `INSERT` 被拒，而审计写是 fail-closed ⇒ **每个请求都失败**。要补必须成对（`FOR SELECT` 租户谓词 + `FOR INSERT WITH CHECK (true)`）。我原先那句"补策略"是危险的，撤回 |
| W1B-6 | 迁移 0001–0005 | `alembic_version=0005`（= head），但 **`query_task` 与 `session` 两张表在任何 schema 下都不存在**（按 `table_name` 全库搜 0 行）。W4 已改用 Redis 承载（`app/cache/keys.py:228`、`reports/w4/RELAY.md:27`） | 二选一：补迁移建表，**或**明确"这两张不落 PG"并同步 07 §12.3 的口径。⚠️ 现状是"文档说建、库里没有"，运维按 §12.3 排查会一路误判 | 🔶**半修**（`1c26047`：`dsn.py`/`pools.py` 已把两张表标注为"文档口径而非库内事实"）⇒ 代码侧不再骗人，但 **07 §12.3 的文档口径还没改**（docs 只读，改它要架构/主流程） ⇒ **转架构**：要么补迁移，要么把 §12.3 改成"不落 PG" |
| W1B-7 | `CHECKPOINT_TTL_DAYS` | 全仓**只有 `app/core/config.py:147` 一处命中**（字段声明本身），**没有任何消费者** ⇒ 7 天 TTL 是装饰 | 要么加清理任务，要么删字段。现状最坏：运维以为 checkpoint 会自动回收（实测已 5,086 行/9.2MB 且在涨） | 否 |
| W1B-8 | `tests/integration/test_retrieval_fts_pg.py`（6 条） | ~~至今 **6 skipped** ⇒ 这批用例**从未执行过**~~ ❌ **我的结论错了，只对本地成立**：`ci.yml:119,124` 早就设了 `RETRIEVAL_TEST_PG_DSN: postgresql://postgres@127.0.0.1:5432/ecom`（超管，夹具要建临时 schema）。本轮按 CI 等价条件实测复现：**8 passed / 0 skipped**（6.25s）⇒ 这 6 条在 CI 上**一直在跑**，"从未执行"不成立 | （CI 侧不需要改）本地要跑满，缺的只是那条 DSN 的取法说明 | 🔻**降级**：不是测试覆盖缺陷，是**本地跑法没写清楚**。建议给一句 runbook 级的 `RETRIEVAL_TEST_PG_DSN` 取法（别把超管口令写进仓库文件），⚠️ 且**任何声称"FTS 集成测试从未跑过"的下游结论都要撤回** |
| W1B-9 | `app/repo/pools.py:173,191` 注释 | 写"3 个硬依赖 ⇒ 2.0s = 5s÷3"，实际 `READINESS_DEPENDENCIES` 是 **4 个** HARD。并行化落地后预算不再依赖这个差值，**只剩注释错** | 改文案即可 | **✅ 已修**（`1c26047`）：现在是"4 个硬依赖""5s ÷ 4 ≈ 1.25s，取整向上到 2.0s"（`pools.py:179,193`），并顺手标了 `_collect` 已并行 |

### 一句提醒（两窗口共用）

`MIGRATION_DATABASE_URL` **刻意不进 `deploy/.env`**（`tests/unit/test_migration_dsn_hygiene.py` 扫的是**整个工作区**，连 gitignore 的文件也扫）⇒ 别为了"方便跑迁移"把它写回任何仓库文件，那会直接踩 DoD④ 的 gitleaks 门禁。

---

## 十二、回执 W4 / W1B（09-19 复测）：三家结论有出入的三条，我核完了

### ① 对 W1B-1：**你们的订正成立，我的建议不完整**

我建议的"就加一个 `encoding="utf-8"`"——**只对了一半**。我核了你们的两个组合：

| 调用 | 你们改前 | 你们改后 |
|---|---|---|
| 只有 `PYTHONIOENCODING=utf-8`（我先前记的"红"那格） | 2 failed | **8 passed** |
| 两个环境变量都不设（裸 locale=GBK） | 2 failed | **8 passed** |

⇒ 两侧 pin 是对的，单侧不够。**G-1 现在与调用方式无关了** —— 这条我先前"判据不该取决于谁怎么敲命令"的顾虑已被你们消掉，不用再等架构。
（顺带：用例数 7→8，多的那条是新守卫。）

### ② 对 W1B-3：**你们对，我错**——已落 `deploy/docker-compose.yml`

`AUTH_TYPE: "scram-sha-256"` 已写进 compose（deploy 归本窗口）。我用自己的手复测了一遍，没只信结论：

- `app_rw` 经 **6432** 连接 → **`conn ok, current_user=app_rw`**（服务端 PostgreSQL 16.15）；
- `SHOW POOLS`（`autocommit=True` 连 `pgbouncer` 库）→ **出现 `db=ecom user=app_rw`，`sv_idle=1`**；
- ⇒ **§16.5 断言③ 从"不可测"变"可判"**。我先前那版"三条出路各有代价、零成本不可得"**作废**：真实原因是我把字面值写错（`scram` 不是合法值，`scram-sha-256` 才是，1.14+ 原生支持），**一个安全代价都不用付**。
- ⚠️ 仍**不要**把应用 DSN 指到 6432：真正的障碍从来不是认证，而是 `transaction` 池模式与 `SET LOCAL`（ADR-09）/ checkpoint 长持连接（R-10）互不兼容。这条已写回 `RL-3` §2.5 并把过期依据删掉。
- ⚠️ 另外"可判"≠"已有生产读数"：本轮池表里那条 `app_rw` 是**探针**连出来的，四场景期间 `sv_active=0`（没接，不是接了没超）。

### ③ 对 W4-⑤：我确实发的是**同一个显式 session_id + 同一身份**，你们的第二种解释不成立

`driver.py` 的 session-lock 路径：`single_session=True` ⇒ `session_pool=[create_session(..., tokens[0])]` 只建**一个**真会话，24 条全打 `session_pool[0]`；该场景我没传 `--tokens` ⇒ `_tokens_for()` 回落成**单枚** `COMMERCEQL_DEV_TOKEN` ⇒ 8 个 worker 用**同一枚令牌、同一个 session_id**。

数据在 `receipt_lock.json`：`requests=24, wall=6.383s, throughput=3.76rps`，`outcomes={clarify:13, refuse:7, http_4xx:4}`，`codes={SESSION_CONFLICT:4}`，`p50=1416ms`、`max=3026ms`。

⇒ 关键算式：**20 条成功 ÷ 6.383s ⇒ 每条平均只占住 319ms**，而一整轮 mean 是 1416ms。
`max 3026ms ≈ SESSION_LOCK_WAIT_MS=3000` 也对得上：**那 4 条正是等锁等到 3s 预算耗尽的**。
所以"锁在生效"我们俩一致（我从没说过它坏），但**被锁住的临界区 ≈ 320ms，只有一整轮的 1/4**。
请把 release 时机对一下：若 `release` 早于 `present`/`execute` 收尾，就是这个形状。要我复跑取证我就用 `--max-requests 8` 加 `task_id` 采证（⚠️ 但本机 `bge-m3` 缺失，复跑仍走的是失败路径，**成功路径下的临界区可能不一样** —— 这点先说清，别拿它当定论）。

### ④ 我这侧已跟着你们的回执改掉的（都是我的文件）

| 项 | 动作 |
|---|---|
| W4-② 双计 | **已删** `instrumentation.py` 的 `SQL_` 帧反推。补一条测试钉住，并做了变异检验（把反推加回去 ⇒ 测试 exit=1 红；还原 ⇒ 逐字节相同 + 绿）。⚠️ 顺带一条你们可能没注意：`app/exec/errors.py:136-140` 把 `unknown_column`/`unknown_table`/`type_mismatch`/`unknown_function`/`syntax_error` **五类压成同一个** `SQL_SYNTAX_ERROR` ⇒ 帧反推不只是双计，还会把四类结构错误**伪装成语法错误**。现在 9 类的唯一来源是 `_on_failure`，是对的。 |
| W1B 转出①（ruff 挡 CI） | **已复测确认**：`backend$ ruff check .` → `reports\w4\probe_feedback_endpoint_pg.py:100:5: SIM117`，由 `6863fdc`（W4）带入；`ci.yml:321` 就是 `ruff check .` 且不排除 `reports/**` ⇒ **当前远端 main 会让 CI 红，挡所有窗口推送**。不在我域，**这是现在最阻塞的一条**。 |
| W1B 转出②（`--basetemp` 陷阱） | 认可，且**我这边也犯过同款**：本窗口先前用的 scratch 目录建在仓库外的父目录，正是为了避免这个形状。建议照你们方案落 `[tool.ruff] exclude` + `.gitignore`（W0 文件）。 |
| W1B-2 你们的纠偏 | 接受，且比我说得更准：**PASS/FAIL 也没指标**，不止 PENDING。我这侧的活体证据支持你们——冷启动真容器导出的 19 个应用族里**没有一个** `startup_assertion*`。你们给的数（断言名 4 / `AssertionStatus` 3 / 每断言一行 ≤12）我这边注册够用，**等架构点这个数**，点到我就接（`BOUNDED_ALLOWED_LABELS` 在 `app/obs/metrics.py:124`，登记动作归我，不用等你们）。 |
| W1B-5 你们的 RLS 发现 | 接受，且这是本轮我收到的一条**真加固**：RLS 默认拒绝 ⇒ 只补 `FOR SELECT` 会让 `INSERT` 被拒，而审计写是 fail-closed ⇒ **每个请求都失败**。我原先"补策略"的建议是危险的。要补必须成对（`FOR SELECT` 租户谓词 + `FOR INSERT WITH CHECK (true)`）。 |

---

## 十三、待决策项的取向 + 阻塞/非阻塞拆分（09-20，给总控转述用）

### ⓪ 先报一条我自己的复核结果，它改变了整张清单的排序

**十份回执里 `outcome=ok` 全是 0。** 逐份从 `codes` 重算（不是引用旧结论）：

| 回执 | 终态分布 | 主因码 |
|---|---|---|
| `receipt_steady_pool` | error_frame 87 / http_5xx 41 / http_4xx 9 / refuse 6 / clarify 7 | `INTERNAL` 87、`RATE_LIMITED` 9 |
| `receipt_burst_pool` | error_frame **100** / 100 | `INTERNAL` 100（墙钟 7.438s 打完） |
| `receipt_quota` | error_frame 22 / clarify 5 / refuse 3 | `INTERNAL` 22 |
| `receipt_lock` | clarify 13 / refuse 7 / http_4xx 4 | `SESSION_CONFLICT` 4 |
| `receipt_steady` | http_4xx 98 / error_frame 50 / http_5xx 2（共 150 条） | `RATE_LIMITED` 98、`INTERNAL` 50、纯文本 5xx 2 |

⇒ **G-6（P95 ≤ 8s）现在没有一条"真正完成"的样本可判**。这不是 P95 算得高或低的问题，是**分母为空**。
`g6_caveat` 已经把它变成机器可读的降级（W6 的门禁会读 `g6_caveat` ⇒ 判 UNVERIFIED 而不是 PASS），
所以**门禁不会被骗过去** —— 但 DoD① 也**没有被满足**。这一条排 🔴-1，且**主要卡在我这侧**：
压测数据只有我能产，但我需要 W4 的两笔提交先进 HEAD，否则复跑还是同样的形状。

⚠️ 未定性部分如实标注：`burst` 那 100 条 `INTERNAL` 的**根因我还没钉死**。已钉死的是停机窗口那批
（34 × `TimeoutError` + `Timeout connecting to server`，栈在 `asyncio.open_connection` ⇒ W4-1 的 Redis 边界）；
但 burst 期间 Redis 是 up 的 ⇒ **不能**把 burst 也归给同一条。这一格是 **UNVERIFIED**，
钉它的方式见 🔴-1 的动作（1 条请求 + 容器日志即可判，不用跑批）。

### ① 🔴 阻塞项 —— 需要转给有权限的人，且顺序不能倒

| # | 事项 | 归属（谁能做） | 卡住了什么 | 判据（可自行复核） |
|---|---|---|---|---|
| 🔴-1 | **W4 把已在手的那两笔改动 commit 进 HEAD**（`app/api/errors.py` +22 的 Redis 边界映射、`app/graph/nodes/execute.py` +5 的 `_on_failure` 观测） | W4 | ① W7 已删帧反推 ⇒ HEAD 上 `exec_failure_total` 是**九条恒 0**，"执行失败分类分布"当前**无告警覆盖**；② 我复跑压测拿 `ok>0` 依赖那个边界映射，否则 Redis 一抖还是纯文本 500 | 对 `HEAD` 版本的 `execute.py` 做 `grep -c observe_exec_failure` → `0`；`git diff --stat` 仍显示这两文件为 modified |
| 🔴-2 | **`ruff check .` 的 SIM117 挡 CI** | W4（文件在 `backend/reports/w4/`） | **所有**窗口往 main 推的 CI 都会红（`ci.yml:321` 就是 `ruff check .`，且不排除 `reports/**`）⇒ 现在是全局第一阻塞 | `cd backend && ruff check .` → `Found 1 error`（`probe_feedback_endpoint_pg.py:100:5`，由 `6863fdc` 带入） |
| 🔴-3 | **W7 复跑四场景取 `ok>0` 的 G-6 数据** | 我（W7），但**必须等 🔴-1** | G-6 是 W6 全部下游门禁的输入；DoD① 未满足 | 复跑后看 `roll-up` 的 `outcomes.ok`，非 0 才有资格谈 P95 |
| 🔴-4 | **裁决：启动校验指标的基数上界**（W1B 已给数：断言名 4 / `AssertionStatus` 3 / 每断言一行 ≤12） | 架构点这个数；W1B+我随即接 | W1B-2（PENDING 三态无指标）+ 我这侧注册（`app/obs/metrics.py:124` 归我，登记动作我做得了）⇒ §15.3 纪律② 不许我自上而下猜上界 | 冷启动真容器导出的 19 个应用族里**没有一个** `startup_assertion*` |
| 🔴-5 | **裁决：§16.5 压测并发 vs 限流桶**（`ratelimit.py:203`：QUERY 10/user/min、100/tenant/min） | 架构 | `steady`/`burst` 两个场景的 429 到底**是预期还是缺陷**。不裁 ⇒ 我只能一直用 caveat 降级，W6 也判不了 G-6 的"限流不误伤"那一半 | `receipt_steady` 里 `http_4xx 98` 以 `RATE_LIMITED` 为主 |
| 🔴-6 | **`GateResult` 加预估延迟载体**（U-96，W4 已登记并明确不做真转异步；字段归 **W2D**） | W2D（编号归架构，**我不自开**） | 真转异步、`ActionTaken.SWITCHED_TO_ASYNC`、以及 §5.4 一切"降级到后台"的口径。当前 `_should_go_async` **恒 False** 且有契约用例钉住 | `edges.py:322`；`receipt_*.json` 里 `async_degraded=0` 是**预期**，不是"恰好没触发" |
| 🔴-7 | **裁决：embedding 模型名与维度**（`EMBEDDING_MODEL` 现值 vs 本机 ollama 是否有该模型；`EMBEDDING_DIM=1024` 被启动断言钉住） | 架构 + W3A | 成功路径压测。本机缺模型 ⇒ 复跑仍主要走**失败路径**，那批 P95 不能代表真实检索链路 | `docker logs w7load-api` 里 `still_unwired: [llm, embedding]` |
| 🔴-8 | **决策：共享 PG 里那 1,940,300 行合成数据留不留、何时清** | 总控（主流程） | 不是技术卡点，是**归属**：这批数据是 §16.5 复现的前置，也是 W6 现在可能同时在读的同一个库；`truncate` 在这儿不可逆 ⇒ 本窗口不动别人在用的库 | `backend/reports/w7/DELIVERY.md` §五 那条登记 |

### ② 🟠 不阻塞、但建议优先（能排进下一个窗口就别拖）

| # | 事项 | 归属 | 我的取向（仅供参考，不替你们定） |
|---|---|---|---|
| 🟠-1 | W1B-5 审计表跨租户口径（已在 `app/obs/audit.py:25` 如实登记"没有强制边界，待裁决"） | 架构 | 建议**先定读侧**：审计跨租户可见 ⇒ 明确"仅属主/运维角色可读"并把它写进 §13.7 清单；若要走 RLS，**必须成对**补 `FOR SELECT` 谓词 + `FOR INSERT WITH CHECK (true)`，否则 fail-closed 审计写会让每个请求失败 |
| 🟠-2 | W1B-6 剩余部分：07 §12.3 仍写着两张 PG 表，库里没有（代码侧已标注为"文档口径"） | 架构（docs 只读） | 建议**改文档**而不是补迁移 —— Redis 已是 `query_task`/`session` 的权威承载，补一张没人读的表只会多一处漂移源 |
| 🟠-3 | 应用 DSN 是否改指 pgbouncer 6432 | 架构 | 建议**不改**。认证障碍已消除（`scram-sha-256`），真正的障碍是 `transaction` 池模式与 `SET LOCAL`（ADR-09）、checkpoint 长持连接（R-10）互不兼容。6432 留给只读报表角色用 |
| 🟠-4 | W1B-7 `CHECKPOINT_TTL_DAYS` 全仓无消费者 | W1B 或我提清理任务？ | 建议**二选一，别停在中间**：加周期清理（我这边有 `event_loop_lag`/`daily_cost` 同款 sampler 位，接得上），或删字段。现状最坏 —— 运维以为会自动回收（实测已 5,086 行 / 9.2MB 且在涨） |
| 🟠-5 | W4-5 会话锁临界区 ≈ 320ms（只有一整轮的 1/4） | W4 | 只要**一句答复**：有意（写进注释）还是无意（是缺陷）。我发的确实是同一显式 `session_id` + 同一身份，你们回的第二种解释不成立（见 §十二③） |
| 🟠-6 | W4-4 节点级计时 | 架构已授权 W7 外包计时 | 我这侧做，**不需要你们动**。但要说清代价：外层包计时拿到的是"节点墙钟"，看不见节点内部拆分 |
| 🟠-7 | `[tool.ruff] exclude` + `.gitignore` 里 basetemp 那条 | W0 | 建议采纳 W1B 方案。⚠️ 与本窗口无关但同形状：我早先把 scratch 目录建在仓库外，就是为了躲这个坑 |
| 🟠-8 | Grafana 面板渲染 / nginx 404 活体验证 | 我（需镜像） | 本机已有镜像 ⇒ 我可以自己做，**排在 🔴-3 之后**。当前状态：告警规则加载已实采验证，面板与 Alertmanager 送达仍 UNVERIFIED（仓库里根本没有 AM） |
| 🟠-9 | RL-3 / RL-1 runbook 补 `DB_UNAVAILABLE` 新行为 | 我 | 等 🔴-1 落地后一次改完，否则写的是"还没进 HEAD 的行为" |
| 🟠-10 | liveness 探针**没有自动重启消费者** | 架构/运维 | DoD 收口必须如实带这句：探针语义正确 ≠ 有编排层在据此重启。compose 环境下 `restart` 策略不消费 liveness |

### ③ 已经不再是问题、但下游结论必须跟着撤回的三条

1. **"6 条 FTS 集成测试从未执行过"** —— ❌ 错。CI 有 `RETRIEVAL_TEST_PG_DSN`（超管），本轮按 CI 等价条件实测 **8 passed / 0 skipped**。谁引用过这句话，请撤回。
2. **"pgbouncer 口令体系要三选一、各有安全代价"** —— ❌ 错。是我把字面值写成 `scram`（合法值是 `scram-sha-256`）。**零安全代价**，且 §16.5 断言③ 从"不可判"变"可判"。
3. **"§15.4 第 2 条之所以没 expr，是因为 `exec_failure_total` 永远不会增"** —— 这半句已过期（W4 接线后它会增）。**但结论不变**：`error_class="permission"` 语义相反（是"拦住了"，不是"泄露了"），**不能**当跨租户泄露代理。否决理由从两条收敛到一条。

⚠️ 一句总纲：上面所有"会动了""可判了"都以**那两笔提交进 HEAD** 为前提。在那之前，HEAD 上这条线是全 0，
而 A 类的全 0 **看得见但不产生告警覆盖** —— 别把"注册了指标"读成"监控已生效"。
