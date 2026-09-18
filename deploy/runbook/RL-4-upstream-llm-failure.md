# RL-4 · 上游 LLM 故障（熔断开路 / 降级链）

> 归属窗口：**W7** ｜ 日期：**2026-09-18**
> 依据：07 §18.7 第 4 行 · §10.1（并发模型）· §10.2（超时/熔断/降级链）· §14.2 F1/F3/G4 · §15.3/§15.4 · 附录 A §A.8.1/§A.8.4/§A.11 · N-21 / NFR-2.2 / NFR-2.7
> 共用命令与端口约定见同目录 `README.md` §五。**先读 `README.md` §三-1 与 §四-3。**

---

## 0. 一句话定性

§18.7 处置栏原文：「系统自动走降级链（**flash → 模板**）；确认模板命中率；**必要时全局降级开关**」。
本条的核心判断是：**熔断开路 = 保护机制在工作，不是可用性事故。** 唯一要"确认"的是降级链有没有真的接住。

**降级链实装（`app/llm/__init__.py:47-50` 的表，逐行有代码）**

| 触发 | 动作 | `degraded.reason` | `action_taken` |
|---|---|---|---|
| pro 超时 / **熔断开路** / 空 content | 换 flash（并关思考） | `llm_unavailable` | `switched_to_weak_model` |
| flash 也不可用 | 模板匹配 | `llm_unavailable` | `template_only` |
| 预算 100% | 跳过全部模型调用，直接模板 | `cost_too_high` | `template_only` |
| 单次调用超时（F1） | 可降级 | — | `switched_to_weak_model` |

⚠️ 模板层在 P0 **恒无命中**（`app/graph/nodes/normalize.py:24`）：`UnderstandUnavailable`（JSON 修复用尽）→ `degraded(llm_unavailable, template_only)` + `intent=refuse` → 走 `refuse`。所以 **LLM 长时间不可用时，用户看到的是拒答而不是结果** —— 这是设计的，但它会让拒答率/澄清率上涨，必须提前对表（见 §4）。

---

## 1. 触发信号（真实名字）

| 类型 | 信号 |
|---|---|
| 代码内部 | `LlmCircuitOpen`（`app/llm/errors.py:144`），由 `app/llm/client.py:194` 的 `_Breaker.is_open()` 抛出；参数 `LLM_CIRCUIT_FAILS=5`、`LLM_CIRCUIT_OPEN_S=30`（`deploy/.env:50-52`） |
| 帧 | SSE `degraded` 帧：`reason` 取 `llm_unavailable` 或 `llm_concurrency_exceeded`，`action_taken` 取 `switched_to_weak_model` 或 `template_only`；或 `error{code="LLM_UPSTREAM_ERROR"}` / `error{code="LLM_CONCURRENCY_EXCEEDED"}` |
| HTTP | `LLM_UPSTREAM_ERROR` → **502**、`LLM_CONCURRENCY_EXCEEDED` → **502**（`ERROR_HTTP_STATUS`）。二者都是 `✅` 档 → **必须带** `Retry-After`：分别为 **30s** 与 **5s**（`RETRY_AFTER_DEFAULT_S`，U-22 裁正） |
| 探针 | `GET /api/v1/healthz` → **`200`** + `status="degraded"` + `degraded_dependencies=["llm"]`。**不得**是 503（附录 A §A.8.4 的"关键修正"）；`GET /api/v1/healthz/ready` **必须仍是 200** |
| 指标 | `degraded_total{reason="llm_unavailable"}`、`http_requests_total{status="5xx"}`、`llm_json_parse_failure_total{prompt_version}`（prompt 退化的最早预警，**调用点在 `app/llm`，本期未接线 → 不输出序列**）、`llm_upstream_concurrency{model}` |
| 告警（§15.4） | P95 > 15s（P1）可能一并触发（LLM 重试会顶高 P95）→ 与 **RL-3** 共用入口，按 §2 分流 |

> ⚠️ **不要照抄 §18.7 去"看熔断状态"**：熔断开路**没有任何可观测出口**。`_Breakers` 是 `ChatClient` 的**进程内 dict**（`app/llm/client.py:154`），既无指标也无 `/healthz` 字段（`/healthz` 是附录 A §A.8.4 契约，私增字段违反 C-13）。唯一判据是**日志与对外错误码**。
> ✅ **探针已接线，`llm:false` 现在就是真信号**（2026-09-18，`app/main.py:282`）：`checks.llm_reachable=false` 不再来自 `health._unwired_probe` 那句占位文案。⚠️ 但它**只**证明"拿到了任意 HTTP 响应"：`make_llm_probe` 打的是 `DEEPSEEK_BASE_URL` 根路径，**`401`/`404` 也算可达**（刻意不打补全请求 = 零配额、零延迟污染）。⇒ **密钥过期 / 额度耗尽时 `llm_reachable` 仍是 `true`**，这类故障只能看日志错误码（`LLM_UPSTREAM_ERROR`、`RATE_LIMITED`）与 `degraded_total{reason="llm_unavailable"}`。为什么挂：查 WARN 日志 `healthz_failed_probes`（`probe_detail` 已从响应体移除）。

---

## 2. 判定

```bash
BASE=http://127.0.0.1:8000/api/v1
# 2.1 三个探针各看一次：期望 live=200 / ready=200 / aggregate=200+degraded
curl -sS -o /dev/null -w 'live=%{http_code} ' "$BASE/healthz/live"
curl -sS -o /dev/null -w 'ready=%{http_code} ' "$BASE/healthz/ready"
curl -sS "$BASE/healthz"; echo
```

```bash
cd deploy
# 2.2 对外症状计数（真实错误码字面量来自 app/core/enums.py:ErrorCode）
docker compose logs --since 10m api \
  | grep -oE '"LLM_UPSTREAM_ERROR"|"LLM_CONCURRENCY_EXCEEDED"|"llm_unavailable"|"template_only"|"switched_to_weak_model"' \
  | sort | uniq -c | sort -rn
# 2.3 熔断/重试的原语日志（client.py 与 errors.py 的文案里带 model 与 circuit_open_s）
docker compose logs --since 10m api | grep -iE "circuit|timeout|retry" | tail -20
```

```bash
# 2.4 网络可达性 vs 额度/鉴权 vs 真故障 —— **三者处置完全不同**
#     ① 只做 TLS 连通探测，不发消息、不耗额度（401/404 即"网络通"）
curl -sS -o /dev/null -w 'base=%{http_code} dns=%{time_namelookup}s conn=%{time_connect}s tls=%{time_appconnect}s\n' \
     https://api.deepseek.com
#     ② 真发一次 chat 会消耗额度：PRD §13.5 / §16.5「先报告再跑批」的精神同样适用这里 —— 先报再打
#        （密钥只从环境取，禁止把 DEEPSEEK_API_KEY 写进命令行历史或日志）
```

**分流表（本条最值钱的一段）**

| 观察 | 真因 | 走 |
|---|---|---|
| 2.4-① 通，`LLM_UPSTREAM_ERROR` 502 + `Retry-After: 30` | 上游 5xx / 熔断开路 | 本条 §3 |
| `LLM_CONCURRENCY_EXCEEDED` 502（`Retry-After: 5`） | **并发超限**，不是上游挂了。上游限的是**并发连接数不是 QPS**（§10.1）；`LLM_MAX_CONCURRENCY=50` vs `LLM_SEMAPHORE_FLASH=8`/`LLM_SEMAPHORE_PRO=2` | 本条 §3-3（调信号量） |
| `degraded_total{reason="embedding_unavailable"}` | **不是 LLM**，Ollama 在宿主、DeepSeek 在公网，二者是独立依赖（A.8.4 为此要求分列） | **转 RL-2** |
| `llm_json_parse_failure_total` 上升、502 不涨 | **prompt 退化**（格式不合），不是上游故障 | 转 **W3A** |
| 只有 P95 高、无 LLM 错误码 | 检查点/DB 侧 | **转 RL-3** |
| 客户端看到 **429 RATE_LIMITED**（带按桶的 `Retry-After`） | **配额**，不是 LLM、不是会话冲突 | 转 **W4**（`app/api/ratelimit.py`） |
| 客户端看到 **409 SESSION_CONFLICT** | **同一会话串行**，锁等待 `SESSION_LOCK_WAIT_MS=3000` 内没拿到锁。**不是限流**：不带 `X-RateLimit-*`（`enums.py` §A.11 补充约定），"等 3s 再发"**只在同会话排队真的会推进时才有意义** —— 要查的是**上一条查询是否卡住不释放锁**，不是扩配额 | 转 **W4**（`app/cache/session_lock.py` 归 W1B） |

---

## 3. 处置动作

1. **先确认降级链在跑，再考虑做任何别的**。判据：`degraded{...template_only|switched_to_weak_model}` 有增量 **且** 用户侧拿到的是 `refuse`/降级结果，**不是** 500 或静默断流。
   ```bash
   docker compose logs --since 5m api | grep -c '"event":"degraded"'   # 字段名以 §15.1 契约为准
   curl -sS http://127.0.0.1/api/v1/healthz/live; echo                 # 经 nginx（80）也验一次反代没坏
   ```
2. **什么都不重启**。`LLM_CIRCUIT_OPEN_S=30` 意味着**最多 30 秒后自动半开试探**（`client.py:213-219` 的半开逻辑，探测成功后 `breaker.fails=0 / opened_at=None`）。重启会：把半开状态清零 + 打断在途 SSE + 上游没好就立刻重开。**这是本条最主要的"不要做"。**
3. **并发超限（`LLM_CONCURRENCY_EXCEEDED`）时降并发**，改**配置**不改代码（`deploy/.env`，改前备份 `cp .env .env.bak-$(date +%Y%m%d%H%M)`）：
   ```
   LLM_MAX_CONCURRENCY=20        # 原 50
   LLM_SEMAPHORE_PRO=1           # 原 2（pro 是最贵也最容易撞上游限的一路）
   ```
   生效需要重启 api（配置在启动期读入），**按 §3-6 的姿势做**。
   ⚠️ 前提：P0 是**单进程** uvicorn（§18.1 + `Dockerfile:42-45`）。信号量是**按进程**的，**多 worker 会把并发上限按进程数悄悄放大** —— 想加 worker 必须先把信号量换成 Redis 令牌桶（§16.6），不是"顺手改个参数"。
4. **要换端点/模型**（区域故障、额度耗尽换备用通道）：同样走 `.env`（`DEEPSEEK_BASE_URL` / `LLM_MODEL_FAST` / `LLM_MODEL_STRONG`）。⚠️ `llm_upstream_concurrency` 的 `model` 标签上界是 **2**（flash/pro，`BOUNDED_ALLOWED_LABELS`），加第三个模型会先撞上基数闸门（`metric_label_overflow_total`）。
5. **"必要时全局降级开关"（§18.7 原文）——当前做不到**。`app/core/config.py` 全字段里没有任何 kill switch / force-template 开关，§14.2 G3 的 `refuse(no_data_asset)` 路径未接线。现实替代只有：
   ```bash
   docker compose stop web     # 挡住新会话（api 与在途流不动，探针仍可查）
   ```
   ⚠️ 若真启用 G3 全局禁用：§14.2 要求 `refuse` **文案必须中性**，不得暴露"系统被关"这种内部状态。缺实现 → **待架构窗口分配编号**。
6. **确需重启时的唯一姿势**（§18.3；drain 第 1~3 步已实装且**已用桩实测过顺序**，但真实 `app.main:app` + 真实 SSE 链路未测；`DRAIN_TOKEN` 缺失时 drain 端点 403 fail-closed —— 桩实测该路径仍会转发 TERM、不卡死；停机后 `Exited (143)` 是正常产物，只有 `137` 才是被硬杀。见 README §四-2 ⇒ 务必挑空载时点）：
   ```bash
   cd deploy
   docker compose stop --timeout 45 api && docker compose up -d api
   curl -sS http://127.0.0.1:8000/api/v1/healthz/ready; echo   # 期望 200
   ```
   重启后 `/healthz` 仍 `degraded` 现在**只有一种解释**：上游确实还没恢复（探针已接线，不再是"未接线"的固定噪声）⇒ **停止重启**，回到 §2 的配额/鉴权分支（`llm_reachable` 对 401 宽容，见 §1）。`degraded` 配 HTTP 200 本身就是正确状态。
7. **⛔ 禁止清单**：
   * 不得"重启实例来恢复 LLM"（§18.7 与 A.8.1 都把 LLM 归为软依赖 + 降级路径）。
   * 不得把 `LLM` 加进 readiness（`READINESS_DEPENDENCIES` 由 `DEPENDENCY_KIND` 从 `app/core/enums.py` 推导，是**结构约束**；且该文件归 W0）。
   * 不得把 `LLM_TIMEOUT_SECONDS` 调大来"少报 502"（那是把 §16.1 的延迟预算改掉，代价全转给用户）。
   * 不得为了压错误率而绕过审计或放宽闸门（N-09 / N-03）。

**回滚**：`.env` 还原 `cp .env.bak-<时间戳> .env` + 按 §3-6 重启。若换过 `DEEPSEEK_BASE_URL`，回滚后必须重跑一次 §2.4-① 与一次真实 `/query`，确认不是"配置回来了但熔断还开着"。

---

## 4. 验证恢复

| 判据 | 怎么看 | 位置 |
|---|---|---|
| 熔闭合了 | 恢复后**连续 ≥2 个 `LLM_CIRCUIT_OPEN_S` 窗口（≥60s）**无新的 `LLM_UPSTREAM_ERROR` / 无半开失败记录 | `docker compose logs api` |
| 降级回落 | `degraded_total{reason="llm_unavailable"}` 增速归零；`action_taken="template_only"` 不再增长 | 指标。✅ `degraded_total` **已接线**（`instrumentation.py` 的 SSE 帧观测器），`/metrics` 也已注册。读取：经 80 端口会被 nginx 故意 404，**走 8000 或容器内**（命令见 `README.md` §四-4；8000 对宿主可直读正是那条未收口的暴露）。拿到全文再筛 `^degraded_total{` |
| 模板命中率回落 = **恢复的反证** | §18.7 要求"确认模板命中率"：命中率**从高位回落**才算真恢复（一直 100% 走模板 = 链还在降级） | 日志/审计里 `action_taken` 分布 |
| 探针回到 ok | `curl $BASE/healthz` → 200 且 `checks.llm_reachable=true`、`degraded_dependencies` 不含 `llm`，且日志不再出现 `healthz_failed_probes` 的 `failed.llm`；期间 `ready` 始终 200 | 三探针（`llm` 探针已接线；⚠️ 它对 401/404 宽容，见 §1） |
| 语义指标回到基线 | `refuse_total` / `clarify_total` / `query_outcome_total{outcome="clarify"}` 回到故障前水平 —— **降级期间拒答必然偏多**，恢复后要把它和 §15.4「澄清率 >15% P1」分开解释 | §15.3/§15.4 |
| 延迟与成本 | `http_request_duration_seconds` P95 回落到 ≤8s；`daily_cost_cny` 未因重试异常抬升（否则并走 **RL-6**）。⚠️ 该指标**已接线但有条件**：采样器在 `app/obs/samplers.py`（**不在** `instrumentation.py`），且只在 `graph_runtime.cost_ledger` 存在时注册；它**无标签 ⇒ 永远导出一条序列** ⇒ 熔断装配下你会看到一条 **0 线**，那**不等于"今天没花钱"**。分辨方法：启动日志 `obs_wiring_done` 的 `samplers=[...]` 是否含 `daily_cost` | §16.5 / §10.4 |
| 5xx 回落 | `http_requests_total{status="5xx"}` 速率回基线 | 指标 |

**如实上报（不得藏）**：故障窗口内的查询**结果质量确实下降**（走 flash 或模板），这段时间产生的任何准确率/澄清率结论都必须标注，不得混进评测（§18.4.1 的同一纪律，R-19 口径污染风险）。

---

## 5. 升级 / 联系（归属见 08 §4.1）

| 议题 | 找谁 |
|---|---|
| 网关：并发模型、重试、**熔断器本体与半开**、降级链（`app/llm/client.py`、`app/llm/__init__.py`、`app/llm/errors.py`、`app/llm/router.py`）、prompts | **W3A** |
| 预算熔断与 `cost_too_high` 分支（`app/llm/budget.py`） | **W3A**（表落 `cost_ledger` → 建表归 **W1B**） |
| `degraded`/`error` 帧与 HTTP 映射、`Retry-After` 下发 | **W4**（`app/graph/events.py`、`app/api/errors.py`、`app/api/runner.py`） |
| `llm_upstream_concurrency` 采样（对信号量的只读内省，`app/obs/samplers.py`）、探针接线、`.env` 与 compose | **W7（本窗口）**；其中"公共访问器需求"已作为上呈给 **W3A** |
| 图节点侧降级点（`bind.py` / `gen_sql.py` / `repair.py` / `normalize.py` / `plan.py`） | **W4**（`app/graph/**`） |
| **不一致上呈**：① §18.7 的判据"熔断开路"无可观测出口（无指标/无探针字段），runbook 只能靠日志；② §18.7 的"必要时全局降级开关"无实现（G3 未接线）；③ `llm_json_parse_failure_total` 的采集点未接线（§15.3 明写它是"最早预示 prompt 退化"的指标） | **架构窗口** → **待架构窗口分配编号** |
