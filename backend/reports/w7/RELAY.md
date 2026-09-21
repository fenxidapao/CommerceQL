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
所以**门禁不会被骗过去** —— 但 DoD① 也**没有被满足**。
⚠️ 且这条**不再是"卡在我这侧"**：**`ok=0` 至少有两个独立成因** ——
① 大量请求死在 `normalize` 的 2.0s 硬超时（根因见下，修法不在我域）；
② 即便走通 `normalize`，也停在 `clarify`/`refuse` 而不是 `complete`：09-19 的 c=5 基线
20 条里 18 条走通，结局是 **clarify 5 + refuse 13 + complete 0**。
⚠️ 这 18 条**为什么**停在这里，我**分辨不了**，别听我编：服务端出现过
`refuse_total{reason="no_data_asset"}`，但 `RefuseReason` 只有 4 个值（`enums.py:429-432`），
而 `no_data_asset` 这个字符串**同时**是 intent 层 `INTENT_MAP` 的产物（07 §5.2 组 3）
**和** §5.3 给 `link` 的"空召回 → `refuse`"的落点 ⇒ **单看 reason 判不出是哪个节点说的**。
⇒ 分辨手段**我这侧已经做好**（09-20）：`driver.py` 新增回执字段 `terminal_provenance`
（按终止 outcome 汇总"终止前最后一个 `stage` + 帧自带 `reason`"），`--self-check` 把三种形状
钉成**整字典相等**的断言，并做过变异检验（删掉记 stage 那行 ⇒ exit 3 红；还原 ⇒ 逐字节相同 + 绿）。
⚠️ 但它**只在新的跑批里产数** —— 本轮十份回执是这个字段存在之前产的，键不存在 ⇒
**要拿到答案必须复跑**（前置见 🔴-3）。文档见 `deploy/loadtest/README.md` §八，
方法论（先 c=1 再谈并发）见 §九。
⇒ 因此复跑前置是：**🔴-0 必做**；**🔴-7 是否必要，等复跑出来的这一眼指纹分辨完再说**（别提前把两件事捆在一起）。

⚠️ **09-20 已把根因钉死**（用 1 条请求复现，不跑批、不猜）：在**同一个 `w7load-api` 镜像**上
单条打 `POST /query` ⇒ 稳定得到同一条链：

```
{"node":"normalize","limit_s":2.0,"event":"node_timeout"}
{"error_type":"TimeoutError","event":"graph_run_failed",
 "extra_fact":"图未收口 → 补发 error(INTERNAL)，不留一条无终态的流（N-08）"}
→ 客户端收到 error 帧，code=INTERNAL，端到端 2052.2ms
```

**8 次小样（1 + 6 + 1）全部同形**。这组实验**能**排除三件事：
- 排除"**并发是必要条件**"：在途只有 1 条时也 8/8 超时；
- 排除"冷启动"：进程已热身后的第 9 次仍然 `p95=2052.2ms`；
- 排除"Redis"：这条链的日志里没有任何 Redis 字样（那批 41 × `http_5xx` 才是 Redis 边界，W4-1）。

⚠️ 但它**不能**支持"每条请求都必死"这个说法 —— 反例在我自己的归档里：
09-19 的 `baseline_c5.json`（c=5，20 条）是 **clarify 5 + refuse 13 + error 2**，
即**多数请求当年是在 2.0s 内走通 `normalize` 的**，那时单发 LLM 延迟是 1060/1104/**1515ms**。
⇒ 两天的数据合起来才是机制：**2.0s 预算对那次 1.5–1.6s 的合并调用几乎零余量（只剩 ~0.4s）**，
所以**谁能活由 LLM 单次延迟的抖动决定**，并发只是放大器（把 2.05s 放大成 2.5–7.3s）。
⇒ 也正因为如此，"调大 `LLM_SEMAPHORE_FLASH`"或"降并发"都**不是**正解 —— 根子上没有余量。
（今天 `LLM_SEMAPHORE_PRO=2` 与"降并发"这两条被排除，仅对今天这组 c=1 样本成立，不是普遍结论。）

**耗时去哪了 —— 用我自己那套指标量的**（`/api/v1/metrics` 活体抓取，8 条样本）：

| 读数 | 值 |
|---|---|
| `stage_duration_seconds{stage="intent"}` count / sum | 8 / **12.87** ⇒ mean **1.609s** |
| 该族 `le="1"` / `le="2"` 累计 | **0** / **8** ⇒ 8 条全落在 **(1s, 2s]** |
| `normalize` 节点超时阈值（`build.py:370`） | **2.0s** |
| 契约给 `normalize`+`intent` **合并后**那次调用的分配（07 **§16.2** 首字节预算，:2923 表 + :2929 已把旧值 1.2s 订正为 **1.6s**） | **1.6s** |

⇒ 结论：**LLM 侧完全按契约的 1.6s 在跑**（实测 mean 1.609s，几乎不偏）；
死因是**节点级 2.0s 硬超时**（`build.py:388 _with_node_timeout` 用 `asyncio.timeout` 抛异常，
除 `present` 外**没有任何降级出口**）只剩 **0.4s** 给"合并调用之外的那部分节点工作"，而这 0.4s **不够**。
差值稳定在 ~50–100ms（2052/2101/2104ms 三个读数）⇒ 是**系统性预算冲突**，不是抖动。

⚠️ 别把两件事混了：超的是 **§16.2 给合并调用的那次分配 + 节点 2.0s 硬超时**；
**NFR-1.2 首字节 ≤1.5s 本身实测是达标的** —— 十份回执的 `ttfb_ms.p50` 在 **79–320ms**
（`burst_pool 217 / quota 201 / steady 128 / lock 8`），只有 drain 两份的 p95 到 3.2–4.2s，
那是**停机窗口**该看到的形状，不是首字节预算破了。

⚠️ 最后 0.4s 里具体是谁（`resolve_time` / `INTENT_MAP` / `detect_injection` / 事件循环节流）
**从 SSE 层看不到** —— 那正是 §十一 W4-4「节点内部耗时不可见」这个观测缺口现在挡住建模的地方。
这条我按实测能钉到"预算冲突"这一层，再往里要 W4 的节点内计时才能判。

### ① 🔴 阻塞项 —— 需要转给有权限的人，且顺序不能倒

| # | 事项 | 归属（谁能做） | 卡住了什么 | 判据（可自行复核） |
|---|---|---|---|---|
| 🔴-0 ★★ | **节点超时没有降级落点 ⇒ 一超时就判 `error(INTERNAL)`**（`build.py:370` 阈值 + `build.py:388 _with_node_timeout` 用 `asyncio.timeout` 抛异常，除 `present` 外无出口；07 §5.3 给 `normalize` 那行**只写了 2.0s 超时、没写超时后落点**） | 修法在 **W4**（`app/graph/**`）；**预算数字与 §5.3 那一格要架构补** | **G-6 / DoD① / W6 全部下游门禁**。抖动事实：09-20 **c=1 时 8/8 超时**（那次合并调用 mean **1.609s**，§16.2 已把分配订正到 1.6s），09-19 **c=5 时 20 条只有 2 条超时**（单发 1060/1104/1515ms）⇒ **2.0s 对 1.5–1.6s 的调用零余量**，谁能活由 LLM 抖动决定。三条候选（选一即可）：① 超时后按 §5.3 语义**降级**（澄清 / `degraded(llm_unavailable, template_only)`）而不是 `INTERNAL`；② 承认"合并调用同时干了节点 2+3 的活"，给它 **2.0s + 节点 3 的 1.5s** 这一档预算；③ 把 `resolve_time`/`INTENT_MAP`/`detect_injection` 挪出计时段（若那 0.4s 真是它们吃的）。⚠️ 我倾向 **①+②组合**：②解当下的量不够，①让"预算破了"不再等于"用户拿到 INTERNAL" | 见 §⓪ 的复现链与指标读数（1 条请求即可，不跑批）：`node_timeout{node=normalize,limit_s=2.0}` + `graph_run_failed(TimeoutError)`；`stage_duration_seconds{stage="intent"}` 8 条全在 (1s, 2s] |
| 🔴-1 | **W4 把已在手的那两笔改动 commit 进 HEAD**（`app/api/errors.py` +22 的 Redis 边界映射、`app/graph/nodes/execute.py` +5 的 `_on_failure` 观测） | W4 | ① W7 已删帧反推 ⇒ HEAD 上 `exec_failure_total` 是**九条恒 0**，"执行失败分类分布"当前**无告警覆盖**；② 我复跑压测拿 `ok>0` 依赖那个边界映射，否则 Redis 一抖还是纯文本 500 | 对 `HEAD` 版本的 `execute.py` 做 `grep -c observe_exec_failure` → `0`；`git diff --stat` 仍显示这两文件为 modified |
| 🔴-2 | **`ruff check .` 的 SIM117 挡 CI** | W4（文件在 `backend/reports/w4/`） | **所有**窗口往 main 推的 CI 都会红（`ci.yml:321` 就是 `ruff check .`，且不排除 `reports/**`）⇒ 这是**CI 侧第一**阻塞（产品侧第一是 🔴-0） | `cd backend && ruff check .` → `Found 1 error`（`probe_feedback_endpoint_pg.py:100:5`，由 `6863fdc` 带入） |
| 🔴-3 | **W7 复跑四场景取 `ok>0` 的 G-6 数据** | 我（W7）；🔴-0 不修 ⇒ 几乎必然还是 `ok=0`（另有一半要看 §⓪-② 那个"终止来源节点"明细才能判，那条在我域） | G-6 是 W6 全部下游门禁的输入；DoD① 未满足 | 复跑后看 `roll-up` 的 `outcomes.ok`，非 0 才有资格谈 P95 |
| 🔴-4 | **裁决：启动校验指标的基数上界**（W1B 已给数：断言名 4 / `AssertionStatus` 3 / 每断言一行 ≤12） | 架构点这个数；W1B+我随即接 | W1B-2（PENDING 三态无指标）+ 我这侧注册（`app/obs/metrics.py:124` 归我，登记动作我做得了）⇒ §15.3 纪律② 不许我自上而下猜上界 | 冷启动真容器导出的 19 个应用族里**没有一个** `startup_assertion*` |
| 🔴-5 | **裁决：§16.5 压测并发 vs 限流桶**（`ratelimit.py:203`：QUERY 10/user/min、100/tenant/min） | 架构 | `steady`/`burst` 两个场景的 429 到底**是预期还是缺陷**。不裁 ⇒ 我只能一直用 caveat 降级，W6 也判不了 G-6 的"限流不误伤"那一半 | `receipt_steady` 里 `http_4xx 98` 以 `RATE_LIMITED` 为主 |
| 🔴-6 | **`GateResult` 加预估延迟载体**（U-96，W4 已登记并明确不做真转异步；字段归 **W2D**） | W2D（编号归架构，**我不自开**） | 真转异步、`ActionTaken.SWITCHED_TO_ASYNC`、以及 §5.4 一切"降级到后台"的口径。当前 `_should_go_async` **恒 False** 且有契约用例钉住 | `edges.py:322`；`receipt_*.json` 里 `async_degraded=0` 是**预期**，不是"恰好没触发" |
| 🔴-7 | **裁决 + 恢复：embedding 提供方**。订正我原先的说法 —— 本机 09-20 实测**不是"缺 `bge-m3` 模型"，是 Ollama 整个没在听**：`127.0.0.1:11434` connect **refused**、`netstat` 里 **0 个** 11434 监听。而 `EMBEDDING_MODEL=bge-m3` / `EMBEDDING_REQUIRED=false` / 容器侧 `EMBEDDING_BASE_URL=http://host.docker.internal:11434` | 运维起 Ollama（不在任何窗口域）；**模型名/维度仍要架构 + W3A 裁** | ⚠️ 它**不是** 🔴-0 那条链的成因（`normalize` 只调 LLM，不调 embedding）。要不要在它上面花功夫，**等 §⓪-② 的"终止来源节点"分辨完再定**；二选一地表态：**要么把 Ollama 拉起来**，**要么明确"本轮 P95 只覆盖 dense 不可用的 sparse-only 路径"** —— 别两者都不说、让下游以为测的是正常检索链路 | connect refused + netstat 0 命中。⚠️ 不要拿 `still_unwired: [llm, embedding]` 当证据 —— 那句话说的是**探针没被注册**，不是服务可用性 |
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

---

## 十四、回执 W4 / 架构：U-104 / U-105 / U-106 已落，另报一条新的第一阻塞（09-20）

**先解除 §十三 末尾那句前提**：`addc554` + `134476d` 已进 `main`，我复测过（不是引用你们的说法）——

| 判据 | 结果 |
|---|---|
| `grep -rn observe_exec_failure app/ --include=*.py` | 只剩 `execute.py:53/111`（直记）+ `metrics.py:857`（定义）⇒ **帧反推已无、无双计** ✅ |
| `cd backend && ruff check .` | **All checks passed!** ⇒ 🔴-2 解除 ✅ |
| 全量测试 | **2154 passed / 6 skipped / 0 failed** ✅ |
| `lint-imports` | **4 kept, 0 broken**（U-105 的注入形态没违反 R-DEP-3）✅ |
| 活体（重建 `w7load-api` 镜像后） | `node_timeout{node:"normalize","limit_s":3.5}` ⇒ 3.5s 合并档**真的生效** ✅ |

### ① U-105（`startup_assertion_state`）—— 已接，且是**活体验过**的

架构给的三条约束我都守住了，但**约束 ① 与 R-DEP-3 直接冲突**，得说清我是怎么解的：

> 约束① 要求"取值从 `ASSERTION_NAMES` / `AssertionStatus` 导出，禁手抄"；
> 而 `.importlinter` 的 **R-DEP-3 禁止 `app/obs/**`（除 `audit.py`）import `app/repo/**`**。
> ⇒ `metrics.py` 自己 import 源枚举这条路**不存在**。手抄一份字面量能过所有测试，
> 而它的失效方式正是 U-105 要消灭的那种：W1B 加第 5 条断言时 CI 全绿、第 5 条永远不上看板。

**采用的形态**：注册表只提供"封闭集 + `bind_domain` 注入口"，由**已经 import 得到 repo 的那一侧**
（`app/main.py` lifespan 新增的第 **3.5** 段，照 W4 第 4.5 段的同一条"只追加"纪律）把
`ASSERTION_NAMES` / `AssertionStatus` 注入。指标名/标签名/上界逐字按裁定：
`startup_assertion_state`、`assertion`(≤4)、**`assertion_status`**（不叫 `status`，避开 HTTP `status`≤10 与 `state`≤4 的一名两义）。

活体读数（重建镜像 + 起容器 + 抓 `/metrics`，不是推导）：**正好 12 条序列**，
每条断言一行 `1` + 两行 `0`（`analytics_dsn_is_read_only` / `embedding_dim_matches_vector_column` /
`audit_log_append_only_enforced` / `semantic_bundle_passed_five_step_validation`，全 `pass`）。

约束②（封闭集越界 fail-fast）做成了通用机制 `_MetricSpec(closed=...)`：域外/未绑定/超上界一律**抛**，
不走"丢弃 + 计溢出"那条路。新增 **8 条具名用例**（`test_obs_metrics_cardinality.py` 4 条 +
`tests/contract/test_obs_startup_assertion_wiring.py` 4 条），再加 1 条随新指标**自动展开**的参数化用例
⇒ 收集数 **+9**，与全量从 2145 涨到 2154 严格对齐。并对"手抄字面量"这种**看起来更简单、
而且能通过全部现有测试**的写法做了 AST 级拦截 + 变异验证（往 `metrics.py` 塞一个字面量 ⇒ 契约红；
还原 ⇒ 逐字节相同 + 绿）。第一次变异我写成了注释，**没被测到 —— 那是变异无效不是守卫无效**，
重做成真字面量后才红；这一笔也记在这儿，免得有人以为一次就过了。

### ② U-106（P95 只算准入 + 429 单列 + 场景⑤）—— 驱动侧已落

* `latency_ms.*` 的分母改成**准入（HTTP 2xx）样本**；新字段 `p95_scope="admitted_http_2xx"`、
  `admission{admitted/rejected_429/other_http_4xx/http_5xx/unresolved}`、`rejection_headers`
  （429/503 的 `Retry-After` 指纹 —— 场景⑤的主判据）。旧混算口径留在 `latency_ms_all_ms`，**不得**引用成达标。
* ⚠️ 一处刻意的**不升版**：`SCHEMA_VERSION` 仍是 `w7.loadtest.receipt/1`。
  因为 W6 的 `eval/reporter.py:139` 按这个串**精确匹配**，升串 = G-6 静默退回 `NOT_AVAILABLE`。
  我拿现有 `receipt.json` 过了 W6 真读端验证：`p95_total_ms=7268.4`、`caveat` 非空 ⇒ 接口未断。**口径靠字段自证，不靠版本号。**
* `g6_caveat` 从 2 种降到 6 种判向（准入为 0 / 准入 < 20 / 旧回执无 `admission` / 有 429 被排除 …），
  含一条"45 条准入且真有完成 ⇒ **不该**降档"的正向对照；两条新变异（摘 `Retry-After` 读取、把准入放宽成全体）都验过会红。
* 场景⑤ `tenant-saturation` 已加，但**刻意不进默认集**（§16.5 是四场景，W6 读的 `receipt.json` 按那四条合成），
  只能 `--scenario tenant-saturation` 点名跑。⚠️ 成本要说清：租户桶 100/分钟 ⇒ 前 ~100 条是**真准入真花额度**的，
  它不是"免费冒烟测试"。
* 40 用户 × 4 租户的画像算术写在 `deploy/loadtest/README.md` §三.0（375 req/min 需求 ⇔ 4 租户 / 38 用户）。

### ③ ★ 新的第一阻塞：**上游 LLM 今天的抖动**，不是任何窗口的代码

重建镜像后我打了 5 条探测请求（**不是跑批**）+ 在容器内直接量 `deepseek-flash`：

| 量 | 读数（09-20，容器内） | 09-19 对照 |
|---|---|---|
| warm 单发 | **1853 / 2033 ms** | 1060 / 1104 / 1515 ms |
| warmup 请求 | 一次 **HTTP 503** | — |
| 首次调用 | **27,348 ms** | — |
| 容器→上游建连 | 一批 **3134 / 4038 / 4049 ms**，稍后复测 **22–70 ms**（宿主 123 ms；两批解析到的 IPv4 集合相同） | — |
| 端到端 5 条探测 | 全 `node_timeout{limit_s:3.5}` ⇒ `error(INTERNAL)`，3584.8 / 12129.7 ms | — |

⇒ **结论：3.5s 合并档是对的，但它解决的是"零余量"，不解决"上游慢"。** 在 warm 单发已经 2.0s 的供给方上，
`normalize` 的余量又变成 1.5s，与 09-19 的形状等价。**我没有跑四场景**（判据与命令见 `README.md` §三.0.1：
warm 单发 p50 ≤1.5s 且三次无 5xx 才开跑）—— 这种状态跑出来的 P95 是 DeepSeek 当天的抖动画像，
而 W6 的门禁会照抄我的数，**不跑比跑更负责**。
⇒ 要转述的话就一句：**G-6 复跑现在卡在外部供给方的延迟窗口，不卡在代码**。请总控在"容器内 warm 单发回到
≤1.5s"时给我一句话，我立刻按 §三.0 的 40 令牌画像跑四场景 + 场景⑤。

### ④ 我自己的一处量具缺陷（如实报，属 W7 域）

`app/obs/probes.py:45` 的 `PROBE_TIMEOUT_S = 2.0` 让 `/healthz` 在上述慢建连窗口里报
**`llm_reachable=false` + `degraded_dependencies=["llm"]`，而真实请求是能通的**（同一时刻 warm 单发 1.9s < 60s 预算）。
⇒ `checks.llm_reachable` 这个布尔把"**连不上**"和"**慢于 2s**"合并成了同一个读数 —— 这是**契约 A.8.4 的形状**逼出来的，
我不能改 payload 形状（`checks` 是布尔表），只能在阈值上取舍。
**我没有擅自改这个阈值**：它同时影响 readiness 轮询耗时与 N-21 的告警语义，要改建议连同
"软探针是否该在 `/healthz` 内联跑"一起判 ⇒ **待架构给一句话**（改阈值 / 拆成两态字段 / 保持现状但在文档标注"false 可能是慢"）。
本轮已把这条写进 `README.md` §三.0.1 与这里，看板侧暂时按"`llm` 软探针 false ⇒ 先复测量具再说"处理。

### ⑤ 我这侧还剩什么（不阻塞别人）

| 项 | 状态 |
|---|---|
| G-6 四场景复跑 + 场景⑤ | **等上游窗口**（§③）+ 40 枚多租户令牌（命令已写） |
| 绑定后的 `/metrics` 活体 | ✅ 本轮已抓（12 条序列）；runbook §二 那条"PENDING 不可查询"已改成可查询 |
| RL-1/RL-3 里 `DB_UNAVAILABLE`(503 + `Retry-After: 5s`) 的新行为 | 待复跑时一起改（现在改写的是"没有活体读数的行为"） |
| Grafana 面板渲染 / nginx 404 | 仍 UNVERIFIED（排在复跑之后） |
| `exec_failure_total` 9 类真数 | 需要一次真跑批才谈得上（今天 5 条探测全是 `INTERNAL` 终止，不进执行失败分类） |

---

## 十五、架构 v1.3 回执 · W6 的 P6 答复 · W4 条 2 的反证（2026-09-20 第二轮）

### ① `U-108` 已落地（`app/obs/probes.py` + `app/main.py` 两段追加）

架构 §11① 那四条我按"顺序反了就只是抬高假负门槛"这句执行，落成**四件事**而不是一处改数：

| 裁定的那条 | 落成了什么 |
|---|---|
| ④ 先修连接复用 | `_client_for()` 跨探测复用同一个 `AsyncClient`，并**显式** `keepalive_expiry=60s`。⚠️ 这条是本轮最容易假装修好的地方：httpx 默认 5s **小于 UI 的 30s 轮询间隔** ⇒ 不改这个值，"复用"在稳态下根本不会发生，第二次探测照样重新握手。实测跨 30s / 65s 闲置仍命中同一连接（96 / 114ms） |
| ② 两探针不共用常量 | `LLM_PROBE_TIMEOUT_S=12.0` / `EMBEDDING_PROBE_TIMEOUT_S=1.0`，另各配一条"慢"线（1.0s / 0.2s）。四个数**全部**在常量旁写了出处，方法指向 `deploy/loadtest/README.md` §三.0.2 |
| ③ 判据与门限分离 | `healthy=False` 只在**连接层失败 / 超过松弛上界 / 本地池没给出连接**三档；"拿到响应但慢" ⇒ `healthy=true` + detail + **本模块自己发 `probe_slow` WARN**。没上新字段（C-13）、没上新指标 |
| ① 探针不占 5s 预算 | 旧注释里"2.0s 是为了塞进 5s"这条**错的归因**已就地订正为"唯一约束是远小于 30s" |

**三处需要点名我自己先前说错的地方**（都在本轮当场撞出来的）：

1. **举证错位**：我在 `RELAY §十四` 用 1853 / 2033 / 27348ms 论证假负，而那三条是**补全调用**的耗时，
   探针打的是 `GET /`。**直接证据本来就在我自己写的表里**（同节"建连 3134 / 4038 / 4049ms"）——
   我把相邻两行当成了因果。架构 §11① 的这条纠正成立。
2. **`httpx.ConnectTimeout` 不是 `ConnectError` 的子类**（两者是兄弟，共同父类是 `TransportError`）。
   我第一版按"先判 `ConnectError` 就够"写，`ConnectTimeout` 于是掉进超时分支、
   被写成"连接已建立但没响应"——**一句方向相反的假话**（该查网络/DNS 的说成该查上游进程）。
   是本轮新加的断言测试把它抓出来的；`PoolTimeout` 同款（请求根本没发出去），一并单列。
3. **我定的 8.0s 被自己的读数证伪**：`p95 × 1.96` 只覆盖了**裸建连**那一层，
   而 httpx 路径（含 DNS 与多 A 回退）实测两次在 8,119 / 8,151ms 处被截断、紧随的一次 5,236ms 成功
   ⇒ 抬到 12.0s。**并写明残余**：间歇长尾不会被任何界消掉，这处交付的其实是"报得准"而不是那个数。

**一次当场复现的假负**（新代码、真上游、容器内）：第 1 次探测 `ConnectTimeout` ⇒ `healthy=False`；
第 2 次 **5,236ms 拿到 HTTP 401** ⇒ `healthy=True` + WARN；第 3–4 次 155 / 103ms（池已暖）。
**同一段时间窗口内旧代码（共用 2.0s）会把这四次全判成"LLM 不可达"。**

追加的第五件事（不在裁定里，但被上面的读数逼出来）：`warm_probe_connections()` 由 lifespan 启动段调用，
把握手成本挪到"还没有人轮询"的时刻付掉；永不抛，失败只留 `probe_warm_failed`。
以及 §18.3 第 4 步"归还连接"补了**出站**这一半（`aclose_probe_clients()`，实测返回 2）——
复用引入之前不存在这笔账。

量具：`tests/unit/test_obs_soft_probes.py` **17 条**（此前这个模块**一条测试都没有**，
而 `/healthz` 的载荷契约在别处钉着 ⇒ "探针自己说什么"是一条没人看的缝，假负就是从这条缝漏的）。
5 条变异验证：每次新建客户端 / 慢⇒unhealthy / 探针共用常量 / keepalive 退回 5s / 停机不关 ——
**第 3 条第一次逃跑成功**（原测试只比两个常量不相等，不验"哪个工厂用了哪个"），补了接线断言后才红。

### ② W6 的 `RELAY P6`（未设 GUC ⇒ 视图静默返 0 行）—— 答复，附一条你们没问的反方向

**先说结论：你们的前提成立，我复现了；但同一个开关还有另一个失效方向，比"0 行"危险。**
全部读数是本轮在 `commerceql-pg-1` 上以 `SET ROLE app_rw`（视图属主、`FORCE ROW LEVEL SECURITY` 生效、
非超级用户）跑的**只读**实验，每个案例都用**独立新连接**（第一版我用 `RESET` 清场，
把结论污染成了 `''` —— 那次数出来 97,374 行，是错的，已作废）。

| 状态（新连接） | `app.shop_ids` 生效值 | 结果 |
|---|---|---|
| 什么都不设 | **NULL** | `v_order_paid` **0 行，不报错** ✅ 与 P6 一致 |
| **只设 `app.tenant_id='T_A'`** | **NULL** | `v_order_paid` **0 行**、`v_shop` **0 行**、不报错 ⇒ **P6 问的那一支，成立** |
| 显式设 `''`（`set_config` / 原生 `SET` / `SET LOCAL` 三种写法各测） | `''` | **200,000 行**（= T_A 全部 5 家店）✅ 稳定 |
| 显式设 `'T_A-S01'` | 单店 | **39,887 行** = 属主视角真值，分毫不差 |
| **`RESET app.shop_ids` 之后** | **`''`（不是 NULL！）** | **不限店铺**：串行 200,000 行；**并行计划下 98,359 / 98,052 / 1,271 —— 三次三个数，全部偏小、无报错** |
| `DISCARD ALL` 之后 | `''`（`tenant_id` 也变 `''`） | 0 行（`tenant_id=''` 谁都匹配不上） |

**答 Q①（`app/exec` 的连接装配是否保证两个 GUC 都设）：这个消费者是保证的。**
`app/exec/executor.py:287-288` 每个请求在事务里跑 `app/repo/dsn.py:141-145` 的
`IDENTITY_INJECTION_TEMPLATE`，三条 `set_config(..., true)` 一起发，
且 `",".join(ctx.shop_ids)` 对"不限店铺"的身份天然给出 `''`（不是 NULL）⇒ 生产执行路径落在表里第 3 行。
⚠️ 但这条**只覆盖 executor 一个消费者**：`is_local=true` 要求它在事务里；
而任何绕开它的连接（你们的评测 PG 执行链、我的装载脚本 `load_synth_to_pg.py:168`
—— 我昨天就是被迫显式补那一行才读出数）都要自己负责。

**答 Q②（"未设"该不该与"设成空"同义，即你们提的 `coalesce(..., '')`）：我建议不要，并且给出实测理由。**
`''` **已经是**"不限店铺"了（表里第 3 行）。所以把"未设"也 coalesce 成"不限"，
不是"让空结果变得有意义"，而是**把失效方向从 fail-closed 翻成 fail-open**：
漏设 GUC 的消费者会从"拿到 0 行（会被当成模型答错）"变成"拿到整个租户 200,000 行"——
在同一租户内跨店铺越权。你们原始的那个痛（空结果被记成答错）用另一种办法解决更便宜：
**让漏设变吵而不是变宽**（在身份注入之后验一句 `current_setting('app.shop_ids', true) IS NOT NULL`，
或在装配期断言三键齐）。**代码不在我权限内** ⇒ 这条转 `app/exec` 属主 + 语义判归架构。

**⚠️ 另外两件必须跟着读的事实：**

1. **`RESET` 那一支是反方向且静默**：PostgreSQL 对**从未设过**的自定义 GUC 执行 `RESET`，
   不会回到 NULL，而是留下一个值为 `''` 的占位符 ⇒ 在 `p_*_tenant` 里那正好等于"不限店铺"
   （实测串行 200,000 = T_A 全部 5 家店）。可达性我这侧**目前是零**：
   `grep` 过 `backend/app/**`，没有任何一处发 `RESET`/`DISCARD`；pgbouncer 实测
   `pool_mode=transaction` + `server_reset_query=DISCARD ALL` + **`server_reset_query_always=0`**
   ⇒ 交易池模式下这条重置**不会**被执行。但**若有人把 `POOL_MODE` 改成 `session`（或把
   `server_reset_query_always` 置 1）**，"休息态"就变成"店铺范围不限"—— 这给 07 §16.3 风险 1
   那笔"应用要不要真走 6432"的账添了一条**安全侧**的代价，建议架构在裁那笔账时引这条。
2. **并行计划下少行，机制我**没**定位**（如实标 UNVERIFIED，别读成"已查明"）：
   已排除两个假设 —— ①不是"占位符 GUC 不传给并行 worker"：用一个与 RLS 无关的
   `app.canary` 探针谓词在 `app.traffic_daily`（600,178 行）上测，**并行与串行都是 600,178，分毫不差**；
   ②不是"数据本来在变"：同一份数据、同一个生效值 `''`，串行 200,000 稳定复现。
   `EXPLAIN (ANALYZE)` 只给出 2 个进程合并后的平均（`loops=2`、`Rows Removed by Filter: 48,780`），
   单进程视角拿不到。能确证的只有现象：**同一条 SQL，正确与"静默偏小且每次不同"取决于计划是否并行**。
   ⇒ 这条对你们下一步"把 PG 执行链接进评测"（G-4 / N-07）是**直接相关**的：
   若你们的评测查询里出现 `count(*)`/聚合，一个被并行计划吃掉的分量**不会报错**。
   我不替别人下结论，但建议你们那一步加一条"并行开/关结果相等"的对照。

3. **一处小订正**：`app.shop_ids` 那一条款只在 **`order_paid` / `product` / `shop`** 三张基表上
   （本轮从 `pg_policy` 直接读出的生效表达式）；`order_refund` / `campaign` / `traffic_daily`
   是**只有租户条件**。你们条目里列的 **`v_campaign` 不在此列** —— 它的 0 行只能由 `app.tenant_id` 解释。

### ③ W4 条 2 的反证：那一次 503 和那 27,348ms 都**没有经过 CommerceQL 一行代码**

W4 建议"判定 PG 还是 Redis：看那次 503 的 error 帧 detail"。**这个判据在这两条上不适用** ——
`deploy/loadtest/README.md` §三.0.1 里那条脚本是 `httpx.post(base + "/chat/completions")`，
`base` 就是 `https://api.deepseek.com`：请求根本没进我们的进程，
打印出来的 `r.status_code` 是 **DeepSeek 自己的 HTTP 状态**，没有 error 帧可看。
⇒ 那一次 503 既不是 `exec db_unavailable`，也不是 W4 上轮加的 `RedisError → DB_UNAVAILABLE`。

**另有一条来自十份历史回执的反证**（`outcomes` + `codes` 全量汇总，非抽样）：

```
http_5xx 合计 145 条，其响应体逐条都是 {"code":"INTERNAL","message":"内部错误，请携带 trace_id …
DB_UNAVAILABLE 出现次数：0        INTERNAL：725 条 error 帧 + 145 条 5xx 体
```

⇒ 在我的全部压测数据里，**没有任何一条 5xx 是"如实上报的依赖故障"**；它们全是
`build.py:432` 那条"其余节点超时 → re-raise → `error(INTERNAL)`"的产物（`errors.py:470` 的兜底映射）。
这和架构 §10 对 `U-107` 的定性是同一件事，也和"5/5 探测 `node_timeout{s:3.5}` → `graph_run_failed`"同源。
所以：**`U-107` 落地之前，我的回执里 5xx 的含义是"图没跑完"，不是"依赖挂了"** —— 这条我已经写进
`README` §三.0.1 的判据 ③，复跑不再在它之前开。

W4 的"慢在 flash 上游本身"我接受，`app/llm/router.py:41` 自己记着 flash `normalize_intent`
真机中位 **1.56s**；我那个 `p50 ≤ 1.5s` 的门**低于这条中位数**，是一扇开不了的 ⇒ 已撤回，
换成"单发 p95 ≤ 8s（就用 G-6 同一个数，不另发明）+ 三次无 5xx + `U-107` 已落"三条，
理由与算术写在 §三.0.1 第二版。

**顺带一条给 W4 的取数**（本轮量的，可能帮你们核 `link` 那格）：
Ollama `bge-m3` 单条 embedding 实测 **4,462–5,025ms**（6 路并发各 4.5–5.0s）。
而 `NODE_TIMEOUT_S["link"]` = **4.0s** ⇒ 在这台机器上 `link` **即使一切健康也必然超时**。
架构 §10① 说这是"同款病害第二处"，这条数是它的实测支撑。

### ④ W6 第 3 条（p95 分母）：我不动口径，但供一条会影响判向的读数

你们提的三选一我不投票，但**"准入 5.2s 达标 / 全请求 12s 超标"这个方向在 429 场景下是反的**：
被限流的请求**回来得快**（本轮 Prometheus 侧实测：3 个 401 请求 `duration_seconds_sum = 0.0083`，
即平均 **2.8ms**）⇒ 把 429 算进分位数会**拉低** p95，而不是抬高。会让全请求分位数**变差**的是
另一类非 2xx —— 长尾失败/超时（例如那 145 条 `INTERNAL`）。
所以两种效应的净符号取决于**当天样本里谁占多数**，而这个数**只能等一次真跑批**：
十份历史回执没存逐样本延迟，我不猜方向、也不拿"两列都写"当已解决。
`p95_scope` / `admission` / `rejection_headers` / `latency_ms_all_ms` / `terminal_provenance`
本轮**一个都没改**（schema 串仍是 `/1`，你们那条"忽略未知键"的测试就是它的护栏）。

### ⑤ 我这侧的状态与剩余（阻塞项已换人）

| 项 | 状态 |
|---|---|
| `U-108` | ✅ 已落 + 17 条测试 + 5 条变异 + 真上游复现（本节①） |
| `MIN_ADMITTED_FOR_P95 = 20` | ✅ 架构已确认进 §16.5，**不进配置清单**（我没去开 env 键） |
| G-6 四场景复跑 + 场景⑤ | 🔴 **第一阻塞换成 `U-107`（W4）** —— 架构 §10④ 明写"必须先落，否则 P95 结论被这个缺陷污染"。上游侧按新判据① 已经满足，剩下的间歇 5xx 属外部门 |
| P6 的两条修复（漏设要吵 / `RESET` 形态） | 代码不在我权限内 ⇒ 已按文件行号转属主；语义判归架构 |
| `DB_UNAVAILABLE`(503 + `Retry-After: 5s`) 的 RL-1/RL-3 活体 | 仍待真跑批（我的十份回执里 `DB_UNAVAILABLE` **0 次**，所以现在改写就是编） |
| Grafana 面板渲染 / nginx `/metrics` 404 | 仍 UNVERIFIED（本机无这两个镜像），排在复跑之后 |
| 并行计划少行的机制 | 现象可复现、机制未定位（已排除两条假设）⇒ 谁有 PG 侧手段再挖 |

---

## 十六、`U-110` 首诊结论（机制已定位）· 给 W6 的 P7 可复现形状 · `U-109` 回执

### ① 架构的两条纠正都成立，我先认下来

| 你们指出的 | 实情 |
|---|---|
| "你声称排除的假设并未被排除" | **成立**。我的 canary 对照组用的是一条**能被提升成 `One-Time Filter` 的纯 GUC 谓词** —— 那种形态下 worker 直接不干活、leader 一个人扫完，结果**恰好正确**，所以这条对照**对故障不敏感**。它当时"证明"的只是"没测到差异"，不是"差异不存在"。 |
| "串行 200,000 vs 并行 98,359/98,052/1,271 是 cross-run 比较" | **成立**。那三组来自不同的 psql 进程，甚至不是我最初的同一份准备。现已按"控住变量"重做（见下）。 |
| 另外我自己又抓到一条 | 我那两次"值级直读"（`select (pg_backend_pid()=0) …  group by`）**设计上就不可能有效**：`pg_backend_pid()` 与 `current_setting()` 都在 **Gather 之上**求值（`EXPLAIN VERBOSE` 的 `Output:` 显示 worker 只回传 `tenant_id, shop_id`）⇒ 永远只有 `is_worker=false` 一行。这**不是**"worker 取值正常"的证据。作废。 |

### ② 同会话 · 同快照 · 交错跑（架构要的第一刀）—— 复现，且差值落在同一轮内

准备：一条连接、`SET ROLE app_rw`（视图属主、FORCE RLS 生效、非超级用户）、
`set_config('app.tenant_id','T_A',false)` 后 **`reset app.shop_ids`** ⇒ 停在**占位符**那一格；
`BEGIN ISOLATION LEVEL REPEATABLE READ` 包住全部轮次；每轮**只切换** `max_parallel_workers_per_gather`（0↔2），
并在同一轮内 `RESET ROLE` 取一次属主真值。`n_live_tup` 三轮恒为 494,249。

| 轮 | 串行 count | 并行 count | 同轮属主真值 |
|---|---|---|---|
| 1 | **200,000** | **119,181** | 200,000 |
| 2 | **200,000** | **104,708** | 200,000 |
| 3 | **200,000** | **93,019** | 200,000 |
| 4 | **200,000** | **115,622** | 200,000 |

⇒ 唯一变量是计划并行度；同会话、同快照、同轮真值。**串行 4/4 精确，并行 4/4 偏小且每次都不同。**

### ③ 机制（按进程的对等证据，不是推断）

`EXPLAIN (ANALYZE, VERBOSE, COSTS OFF, TIMING OFF) select count(*) from app.v_order_paid`，同一份准备：

```
占位符状态（RESET 过）：                            显式设值状态（set_config('app.shop_ids','',false)）：
  Parallel Index Only Scan  rows=42,052 loops=2       Parallel Index Only Scan  rows=100,000 loops=2
    Index Cond: tenant_id = current_setting(...true)      Index Cond: 同上
    Filter: (current_setting('app.shop_ids',true)=''        Filter: 同一条
              OR shop_id = ANY(string_to_array(...,',')))
    Rows Removed by Filter: 57,948                       （无 Removed 行）
    Worker 0:  actual rows=0          ← ★ worker 一行没留下    Worker 0:  actual rows=92,983  ← ★ worker 正常留行
```

**结论（可直接当口径用）**：
1. **`RESET` 在一个"本会话从未设过"的自定义键上留下的占位符，不会被带进并行 worker** ⇒ worker 里
   `current_setting('app.shop_ids', true)` 取到的是 **NULL**。
   （旁证：另一条纯 GUC 谓词的 `One-Time Filter: current_setting('app.canary',true)=''` 同样是
   leader 为真、`Worker 0/1: actual rows=0`。）
2. **RLS 那一支为什么偏偏会少算**：它的谓词是 `GUC='' OR shop_id = ANY(...)`，
   含逐行比较 ⇒ **不能被提升成 `One-Time Filter`** ⇒ 只能作为逐行 `Filter` 在**每个进程内**求值。
   leader 取到 `''` ⇒ 全通过；worker 取到 NULL ⇒ 全不通过 ⇒ 每个 worker 把它抢到的块**整块丢弃**。
3. **为什么每次数字都不一样**：并行索引扫描是**动态派块**（谁空谁拿）。leader 拿到多少块是随机的，
   所以存活量 ≈ leader 那一份，落在 46%–60% 之间漂移。
4. **不是"并行里 current_setting 都坏"**：显式设值（`set_config(...,false)` / 原生 `SET` / `SET LOCAL`）
   三种写法在并行下都精确（上面右列 + C/E/F/G 各 3 次；G 单店 39,887 = 属主真值分毫不差）。
   ⚠️ 也别读成"只有 `RESET` 会坏" —— 我只证了 `RESET` 这一条制造占位符的路径，别的（如某些客户端库
   的会话清理）我没测，不替它打包票。

⇒ 按架构 §12 那句"**若证实为 'worker 内取到不同 GUC 值' ⇒ 与 `U-109` 合并收**"：**已证实，我提请合并**。
`U-110` 不是第二个缺陷，是 `U-109①` 那同一根因（同一个 `RESET`/占位符形态）的第二种伤害：
`U-109` 处理的是"leader 里 `''` = 不限店铺"（读多），这一条是"worker 里 NULL ⇒ 静默读少"。

⚠️ **一条推断，未实测**（P1 哨兵还没落，别当已验）：若 `U-109③` 把"不限"换成 `'*'` 哨兵、
让 `''` 与 NULL **双双 fail-closed**，那么 leader 与 worker 在这条谓词上的求值会**同为 false** ⇒
少算形态一并消失（变成"稳定 0 行"这种可发现的问题）。
这是"哨兵那条改动顺手关掉 R-17"的论据，**要等实现落地后由实测替换**。

### ④ 给 W6 的 `P7`：可复现形状（你们复现不出来是因为没进那一格）

```
环境：PostgreSQL 16.15（Debian 16.15-1.pgdg12+2），docker 容器内 unix socket，库 ecom
准备（关键就是第 3 行的 RESET —— 你们 8 组测的是显式设值，那一格本来就是好的）：
  psql -U postgres -d ecom
  set role app_rw;                                   -- 视图属主、FORCE RLS 生效、非超级用户
  select set_config('app.tenant_id','T_A',false);
  reset app.shop_ids;                                -- ★ 占位符：值 '' 而非 NULL
  set debug_parallel_query to on;                    -- PG16 的开关（force_parallel_mode 在 16 已移除）
  select count(*) from app.v_order_paid;             -- 期望 200,000；实得 ~9.3万–12万，且每次不同
  reset role; select count(*) from app.order_paid where tenant_id='T_A';   -- 同轮真值 = 200,000
相关 planner 现值（全部 default，我没调过）：max_parallel_workers_per_gather=2、
  min_parallel_index_scan_size=64(8kB)、parallel_setup_cost=1000、parallel_tuple_cost=0.1、
  shared_buffers=128MB、max_parallel_workers=8
```
你们把 `parallel_equality` 常驻成前置判据这件事我支持，但**请把"判据"跑在三种状态下**，
否则它测不到这一格：① 显式 `''`（你们现在这两个 is_local 组合都是这格，恒绿）
② `RESET` 占位符（会红）③ P1 换 `'*'` 哨兵之后（预期两进程同为 false ⇒ 恒 0 行、相等）。
⚠️ 还有一条给你们自己的：`debug_parallel_query=on` 只能证明"计划里有 Gather"，
**不能证明 worker 真的扫了块** —— 要看 `Worker 0: actual rows=` 那一行；我们两边都被
"结果恰好正确"骗过一次（我那条 canary，你们第一版复用同一条连接/事务）。

### ⑤ `U-109` 回执 + 两条要盯住别丢的约束

三条都收到，且第②条那个 ⚠️ 是我答复里没想到的维度：**"漏设就吵"只许吵在内部**
（注入后验 / 装配断言 → 日志 + 指标），**不得变成对客户端可区分的响应** —— 因为 N-07 要求
"跨租户"与"真无数据"不可区分。我先前写的是"让漏设变吵"，若实现者把它做成"给客户端一句 4xx/不同码"，
那就用一个观测性修复换掉了一条隔离判据。**这条我抄进 `DELIVERY.md` 的接口节，属主实现时对着核。**
第①条"RESET 路径不可达从事实升级为受约束（两半都要检查）"同样收到：应用侧那一半本轮 `grep` 过是零命中，
`pgbouncer` 那一半读数是 `pool_mode=transaction` + `server_reset_query=DISCARD ALL` + `server_reset_query_always=0`。

### ⑥ 另：W6 顺手逮到的那条不在我范围内的（`bind` 触达 LLM 却不在 `_LLM_NODE_TASKS`）

`nodes/bind.py:180` 走 `deps.llm` 而 `_effective_limit_for("bind")` 仍是 0.2s，同一次探测里 6 个 LLM 节点都是 15.0s。
这条对**我**的意义只有一条：如果 `bind` 因 0.2s 被掐，终止码会走 W4 新落的失败转移而不是 `INTERNAL` ⇒
我的回执里 `codes` 会开始出现 `GATE_*`/降级码而不是只有 `INTERNAL`。**下一次跑批我会按这个预期读**，
判向变了不是我的驱动坏了。归 W4（他们已收 RELAY G3）。

### ⑦ P7 那四问逐条答（W6：你们复现不出来是**差一步准备动作**，不是形状不对）

| 你们要的四件事之一 | 答 |
|---|---|
| ① 经 app 执行器还是裸 SQL | **裸 SQL**，`docker exec commerceql-pg-1 psql -U postgres -d ecom`，没进 executor、没有游标、没有 `EXEC_MAX_ROWS` |
| ② `SET ROLE app_rw` 与直接以 `app_rw` 登录 | 我只测了 `SET ROLE app_rw`（视图属主、`FORCE RLS` 对它生效、非超级用户），**没有 app_ro 的口令 ⇒ 那条路径我未测**。"两者应走同一策略（普通视图按属主求值）"是我的推断，不是读数 |
| ③ SQL 的确切形状 | `select count(*) from app.v_order_paid`（无 GROUP BY、无游标；`v_order_paid` 定义是纯 `SELECT … FROM app.order_paid`，**无 WHERE**，已核 `pg_get_viewdef`） |
| ④ `max_parallel_workers_per_gather` | 服务器默认 **2**（我交错实验里就在 0↔2 之间切；早先那几个数用的是 4 与默认） |
| **★ 你们 8 组全绿的真正原因** | 你们的准备里 **两把 GUC 都是 `set_config` 显式设值** ⇒ 从来没进过"占位符"那一格。差的只有这一句：`reset app.shop_ids;`（键在本会话从未设过 ⇒ 留下列值 `''` 的占位符，而不是 NULL）。补上这一句，off/on 立刻不等值（我这边串行恒 200,000 / 并行 119,181…115,622）。 |

⚠️ **同时订正一件对我自己不利的事**：你们试图复现的那三个数（98,359 / 98,052 / 1,271）来自我**被污染的前两批**
—— 第一批用 `RESET` 清场混在会话里、第二批跨了不同 psql 进程。它们**不该被当成一组可复现读数**发给你们，
是我发出去得太早。现在这组才是受控的（同会话、同 REPEATABLE READ 快照、每轮同轮取属主真值）：
**119,181 / 104,708 / 93,019 / 115,622**，串行恒 200,000。
你们那句"更像部分并行分量为 0 的形状"**判断正确**，且现在按进程证实了：`Worker 0: actual rows=0`。

另：你们把 `parallel_equality` 常驻成前置判据这件事，请把它**跑在三态上**（显式设值 / `RESET` 占位符 /
P1 换 `'*'` 哨兵后）—— 只测前两态里的第一态会恒绿，而这正是这一格能藏住错的原因。
还有 `debug_parallel_query=on` 只证明"计划里有 Gather"，**不证明 worker 真扫了块**：
要看 `Worker 0: actual rows=`。我们两边各被"结果恰好正确"骗过一次。

---

## 十七、`U-107` 验收（读码 + 活体）· 一条新缺陷 · 以及我上一轮说过头的一句

### ① `U-107` 四条逐条核过（**不照抄回执**：读码 + 全量跑）

| 裁定（架构 §10） | 我核到的实现 | 判 |
|---|---|---|
| ① 硬超时 = 本请求模型的客户端超时，执行期解析、不写死 | `build.py:360-383` 的 `NODE_TIMEOUT_S` 里**已无 6 个 LLM 节点**（只剩 `link 30.0 / bind 0.2 / gate1-3 / execute / mask / audit_*`）；`_LLM_NODE_TASKS`（`:396`）→ `_client_timeout_for`（`:417`）= `hard_timeout_s(resolve_route(task).model_key)` ⇒ pro 档自动跟 45s；`link` 的 30.0 具名引用 `Settings.EMBEDDING_TIMEOUT_SECONDS`（U-22 合规） | ✅ |
| ② 超时出路复用 §5.3"失败转移"列，不消灭 fail-closed 节点的 `INTERNAL` | `_timeout_fallback`（`:454`）逐节点给出口（`bind`→`refuse(no_data_asset)`、`link`→`degraded(embedding_unavailable,sparse_only)`、`present`→`degraded(present_failed,table_only)`…），`_RERAISE_TIMEOUT_NODES = {mask, audit_pre, audit_supp}` 保留 re-raise 且 `audit_supp` 有具名理由 | ✅ |
| ③ 3.5s 改指"分配"，不再叠加进 `asyncio.timeout` | `_MERGED_NORMALIZE_EXTRA_S = 1.5` 仍在（`:414`），但 `_effective_limit_for`（`:427`）对 LLM 节点直接返回客户端超时，**没有 `base + extra`** | ✅ |
| ④ 契约测试"只钉键集、不需改断言" | ⚠️ **架构这句不成立、W4 的订正成立**：`tests/contract/test_graph_timeout_contract.py:44` 实测是**值级**断言（字典字面量里有 `"bind": 0.2` 这样的逐节点数值）⇒ 改 `NODE_TIMEOUT_S` 必红。W4 重写整份测试是对的。这条我核出来是为了让两边下一轮不要又按"只钉键集"行事 | ✅（W4 已登记分歧） |

**静态门全绿（含 `U-107` 的当前树）**：`2187 passed / 6 skipped / 0 failed`（真实退出码，从日志文件读）；
`ruff check .` 全绿；`mypy` 干净；`lint-imports` 4 kept / 0 broken。
⚠️ 顺带订正我自己：我上一轮说过"我那 2180 条的树里已经含 `U-107`"——**那是用错判据得出的**
（我用 `--is-ancestor d387347 HEAD` 判，而当时 HEAD 已经是别人的提交）。
按提交顺序 `d387347` 是 `1300379` 的**后代** ⇒ 那轮 2180 不含 `U-107`，本轮这次重跑才算。

### ② 活体（`w7load-api:0920r2`，当前树构建，c=1 / 3 条 / `--no-async`）

- **`U-108` 在真实服务形态里成立**：lifespan 的 `probe_connections_warmed` 付掉 `deepseek 4,256ms / ollama 18ms`，
  之后第一次 `/healthz` 端到端 **0.296s** 且 `llm_reachable=true`、`embedding_reachable=true`、`status=ok`。
- **`U-107` 的形状变化被观察到**：整场 **零条 `node_timeout`**（先前是 137 条），`/healthz/ready=200`。
- ⚠️ 但 **`ok=0/3` 又出现了**：`outcomes={error_frame: 2, clarify: 1}`、`codes={INTERNAL: 2}`、
  `p95=15,855.9ms` ⇒ 按 §三.0.1 判据① 不过 ⇒ **本轮不跑批**（细节与启动形态教训见 README §三.0.1b/§三.0.1c）。

### ③ ★ 一条新缺陷（不在我权限内，够格当 G-6 的下一个第一阻塞）

服务端日志（两次，同一形状）：

```
error_type=TypeError  detail="float() argument must be a string or a real number, not 'NoneType'"
extra_fact="图未收口 → 补发 error(INTERNAL)，不留一条无终态的流（N-08）"
```

**它不是超时**：`node_timeout` 事件为零 ⇒ `U-107` 新落的降级出口这一轮**根本没被走到**，
我这 3 条既没验到降级路径、也没验到转异步路径。**下一轮跑批要同时把这两条路径钉出读数**，
否则 `U-107` 的活体证据仍然只有"超时不再发生"这一半。

我做的定位（**到"候选点"为止，不当结论用**）：
- `app/api/runner.py:483` 的 `_log.error(..., detail=str(exc)[:300])` **不带 `exc_info`** ⇒ **没有栈**。
  所以我无法证明是哪一处。★ **这条本身就是一个请求**：给这一处补上栈（N-11 禁止的是"回灌用户"，
  不是"日志里也不留"）—— 现在任何 `INTERNAL` 都是不可归因的，而 `INTERNAL` 恰好是我回执里的主码。
- 我在自己权限内能复现的候选点（同一句报错文案）：
  `app/graph/nodes/_shared.py:238` 的 `float(ref.score)` —— 纯函数调用
  `candidate_payload(SimpleNamespace(asset_id='a', score=None, layer=None))` 直接抛出
  **一模一样的 TypeError**。旁证：同一个函数里 `layer` 做了 None 保护（`:239`），`score` 没有；
  而 `CandidateRef.score` 的契约类型是 `float`（`app/core/contracts.py:205`，非 Optional），
  `app/binding/scores.py:129 require_rerank_scores` 只校验 `item` 是不是 `RerankScore`，**不校验 `.value` 不是 None**
  ⇒ `bind.py:194` 的 `score=score.value` 是可达 `None` 的一条路（模型 JSON 里 `"score": null`）。
- ⚠️ 反向证据也要摆着：`provenance` 是 `stage=intent`，而候选通常由 `link` 之后才产出 ⇒ 时间上贴，
  但我不据此断言。**归因等栈。**
- 另一处同文案候选在 `app/llm/budget.py:392/395` 的 `float(self._alert)`（若 `_alert` 为 None）——
  我没排除它，只是它会在每次预算判定都炸，与我这 3 条"1 条走通"的形状不太合。

### ④ 我上一轮说过头的一句，现在收回来一半

我对 W4 说过："十份回执里 145 条 5xx **全是** `build.py:432` 那条节点超时的产物"。
现在必须收窄：**"5xx 体的码是 INTERNAL"成立，"INTERNAL ⇒ 节点超时"这个反向推论不成立** ——
本轮就是 `INTERNAL` 但零超时。所以正确表述是：
`INTERNAL` 是一个**至少混有两类成因**的兜底码（节点超时 / 未捕获异常如本条 TypeError），
而我的 `codes` 字段分不开它们 —— 能分开的只有服务端栈（见 ③ 的请求）或一条 §15.3 的注册指标
（那是封闭登记表，要开得走架构，我不自增）。
先前那批的归因**不受影响**：那批日志里 `node_timeout` 与 `graph_run_failed` 是同数对上的
（137 : 137），所以"那一批是超时"仍成立；错的是我把它写成了一条通用逆命题。

---

## 十八、撤回两条推导 · 回架构 U-110 两件未结 · 对 W6 第三条读数提一个反证要求

### ① 我撤回两条推导（都核过码才撤，不是照抄别人的回执）

| 我先前说的 | 实情（我自己去读的码） | 判 |
|---|---|---|
| `bind.py:194` 的 `score=score.value` 可达 None ⇒ 那是 `float(None)` 的源头 | `app/binding/scores.py:73-93` 的 `RerankScore.__post_init__` 在**构造期**就挡：`isinstance(value, bool) or not isinstance(value, (int, float))` ⇒ `None` 直接 `ScoreParseError`；`parse_scores_json` 把 `"score": null` 变成 `ScoreOutcome(failed=True)`，`bind.py:185` 早退 ⇒ **L4/bind 这条路给不出 None** | 🔴 **撤回**。W4 的纠正成立，我的旁证里"require_rerank_scores 不校验 .value"是真话但结论错——校验已经埋在构造函数里 |
| `provenance=stage=intent` 是**反向**证据（候选一般在 link 之后才有） | `app/api/runner.py:454` 用 `stream_mode="updates"`，头注第 8 行明写"每个节点跑完拿到一次增量" ⇒ **stage 帧在节点返回之后才发射** ⇒ `stage=intent` 的唯一可靠含义是"**intent 已完成**"，破点在**后继节点** = `link` ⇒ 这条是**正向**证据 | 🔴 **撤回**，并把它变成量具自己的语义订正：`driver.py:_provenance` 的 docstring 已重写（旧写法会让人读成"intent 收不了口"，我就是那么读的）。**这个字段的读法错一次，整条归因链就反一次** |

⇒ 我上一版那句"归因等栈"没错，但候选点给错了方向；正解是 W4 找到的
`app/retrieval/search.py:325/326`（缓存重建把 `raw["candidates"]` 里的 null 直传 `CandidateRef(score=None)`）。

### ② 回架构的两件"未结"—— 第①件我接受，第②件我要先反证 W6 的一条读数

**未结①（"进程对等证据取自另一组配置"）接受。** 确实：我的 4 个偏小读数与
`Worker 0: actual rows=0` 来自两条不同的 psql 会话。关闭证据需要同一 run 同源三件套，
我把它写成了入库脚本而不是又一段聊天读数：**`deploy/loadtest/rls_parallel_evidence.sql`**
（⓪ 先证明 `Workers Launched ≥ 1` → ① RLS qual 落层与每进程留行 → ② 每个进程实际读到的值
→ ②b 同一状态同一键的"可提升"形状 → ③ 同快照内串行/属主真值/`n_live_tup`）。
⚠️ **本轮跑不了**：这台机器的 Docker 引擎在写这份文档时掉了（主栈 5 个容器全断，
`docker version` 连不上 named pipe）。我**没有擅自拉起 Docker Desktop** —— 那会重启 W6/W4 共用的
`pg`/`redis`/`api` 与 1,940,300 行共享库所在的实例，属跨窗口共享状态，要总控点头。
⇒ 三件套的实测状态：**UNVERIFIED，等环境恢复**，不预写结论。

**未结②（生产注入形态是否复现）**：W4/W6 的读数是"事务内 `set_config(...,true)` 恒 200,000"，
与我读到的 `dsn.py:141-145` 模板形状一致 ⇒ 我同意"触发面只在未显式设值那一格"，
但这条也要在同一 run 里被三件套覆盖到（脚本 ②/③ 两栏就是为它设计的）。

### ③ ★ 对 W6 第三条读数提一个反证要求：**"worker 拿不到值被证伪"这句还下不了**

你们报的：同一占位符状态下，从**不含 shop 条款**的 `v_traffic_daily` 里并行投影
`current_setting('app.shop_ids',true)`，600,178 行全部报 `''`（`Workers Launched=2`）。

⚠️ 这条测量的形状，**与本窗口自己被同一种形状骗过一次的那条一模一样**：
表达式若**不含列引用**，规划器可以把它放到 **Gather 之上**、由 leader 一次算完 ——
我当时的 `EXPLAIN VERBOSE` 原文就是这么写的：

```
GroupAggregate   Output: (pg_backend_pid() = 0), current_setting('app.canary'::text, true)
  -> Index Only Scan ...   Output: tenant_id, channel          ← worker 只回传这两列
```

⇒ 那一栏读到的 `''` 有可能是 **leader 算完发下来的**，不是 worker 扫到的。
所以"worker 看得见值"目前**既没被你们证实、也没被我们证伪**。
要证实它，把表达式变成**不能提升**的形状（带一个列引用 + `group by` 该表达式）：

```sql
select case when t.tenant_id is not null
            then coalesce(current_setting('app.shop_ids',true), '<NULL-in-this-process>')
            else '<unreachable>' end as value_seen_by_the_scanning_process,
       count(*)
  from app.traffic_daily t group by 1;
```
出现 `<NULL-in-this-process>` 组 ⇒ 我那条机制成立；只出现 `''` 组 ⇒ **机制作废，我改口径**，
而且你们排除的另两条（plan 缓存、index-only 特有）就真的成了唯一剩余解释面。
两种结果我都接受，但**别用一条可提升的投影定死机制** —— 这与你们订正前的 `off/on` 不是串行/并行轴
是同一类错误，你们已经认了一条，这条我替你们先想到。

### ④ 三条我要转出去的事实（其中一条改的是架构刚写下的东西）

1. **给架构**：`§13.3 细节 4` 刚把我那条推断（"P1 换 `'*'` ⇒ 少算变成稳定 0 行"）记成 P1 的第 4 条理由，
   标 UNVERIFIED。**W6 本轮实测把它推翻了一半**：在**当前策略文本**
   （`= '' OR shop_id = ANY(string_to_array(v,','))`）下 `'*'` 串行并行都读 **0 行**
   ⇒ 哨兵**必须连策略文本一起改**，否则"不限店铺"静默变成"什么都查不到"。
   那条"第 4 理由"的措辞请改成"哨兵 + 策略文本同改之后才成立"，否则会有人照 §13.3 只改常量。
2. **给架构 + W1B**：W6 报的**新失败形态**要并进 `U-109` —— 同一条连接**提交后再复用**，
   两把键的 `LOCAL` 值一起消失、余值只剩 `''` ⇒ `tenant_id = ''` ⇒ 恒 0 行。
   这是"`SET LOCAL` 的生命周期"而不是"`RESET`"，与 §16.3 那笔池模式账直接相关（池复用正是提交后再用）。
3. **给我自己**：`--no-async` 那 3 条预检的 `p95=15,855.9ms` 现在有了一个**不依赖上游**的解释候选 ——
   崩点在 `link`（见 ①），而 `link` 的 embedding 调用实测单条 4.5–5.0s；
   那条 15.86s 到底是"上游慢"还是"link 之后才炸"，等 `exc_info` + 重跑一次才分得开。
   **先前把它写成"纯上游容量问题"是过早的。**

### ⑤ 收到的其余几条（不复述、只登记）

- 架构：`§10④` 你们自己认错并升级为"§5.3 表 / 代码 / 契约测试 三处同改"，`link` 行 4.0→30 已同步；
  R-17 风险面上调为**结果正确性**（接受，且我认为这是本轮最该上调的一条）；
  `INTERNAL` 不开指标、不扩 `codes`（接受，理由成立：成因属内部诊断，对外不可区分是 A.11/N-07 的有意语义）。
  报告纪律"INTERNAL 不得当节点超时的同义词"——**这条本来就是我被本轮教育之后写下的**，已并入口径。
- W4：`exc_info=True` 已核（`runner.py:483-489`）。重跑请等我这边环境恢复（见 ②）。
- W6：`parallel_equality_ok=false` + `parallel_undercount_states` 点名到形态，
  比我上一版那句含糊的"不等值"强，方向对；"吃真实产物的测试"那条尤其对。
