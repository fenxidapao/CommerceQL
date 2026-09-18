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
| 6 ★ | **`Outcome.SWITCHED_TO_ASYNC` 无消费方**（全仓只有枚举定义） | 压测的口径问题：`async_if_slow=true` + `async_threshold_ms=8000` 会让超 8s 的查询**转异步并正常终止该流**，而帧上区分不了"真完成"与"转异步" ⇒ `driver.py` 只能靠"`complete` 帧带 `task_id`/`async` 键"的启发式。**G-6 的 P95 因此可能被截断点假性做低**（`压测报告.md` §四）。要么给终止帧加一个可判定字段，要么明确"转异步不计入 P95 分母" | 待架构窗口分配编号 |
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

1. ★ **G-6 现在是 UNVERIFIED**，不是"还没写"。原因与取证在 `压测报告.md` §二；门禁表请照抄 UNVERIFIED（外部阻塞），不要填空、不要填通过。
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
