# 观测栈配置（阶段 7 · 交付物 ②看板 + ③告警规则）

> 归属窗口：**W7**（docs/08 §4.1：`deploy/**` 归 W7｜§3.9 产出 ②③）· 日期：**2026-09-18**
> 依据：07 **§15.3**（指标清单 + 标签基数上限）· **§15.4**（十条告警规则）· **§15.5**（五屏最小看板）
> · §14.5（错误码→指标映射）· §10.4（预算 80%/100%）· §16.5（压测口径）· §17.3/§17.4（门禁与沙箱缺口）
> · §18.1/§18.2（进程模型与探针）· §18.7（runbook 六条）· PRD A-7（**单机 Compose，无 K8s**）
>
> **一句话状态**：抓取端配置、告警规则、看板 JSON、dashboard provider **已写完，且规则语义已过
> `promtool` 机器校验**（`check rules` 9 条 SUCCESS、`check config` SUCCESS、
> `alert.rules.test.yml` test rules SUCCESS —— 见文末校验记录）。
> 但**仍未在真实运行时验证过**：本窗口没起观测栈、没做过一次抓取、没在 Grafana 里渲染过面板。
> 且**采集侧仍有未接线指标**（采集点在应用侧，见 §三.4 的 A/B 分类）。
> ⇒ 「配置写好了」≠「规则语义过了」≠「生产观测已验证」。这三件事在本文件里必须分开读。

## 目录

本目录**就在** `deploy/observability/`，与可执行的 `docker-compose.yml` **同一层**
⇒ 下面所有挂载/命令的工作目录都是 `CommerceQL/deploy`，相对路径一律以 `./` 开头。

```
deploy/
├── docker-compose.yml                        主干栈 + 两个 profile（async / observability）
├── nginx.conf                                `location = /api/v1/metrics` → 404（本窗口收口）
├── observability/                            ← 本目录
│   ├── prometheus.yml                        抓取端（1 个必用 job + 两处刻意注释掉的 job）
│   ├── alert.rules.yml                       §15.4 十条：6 条有 expr、3 条无指标来源（注释块）、+1 条观测层自检
│   ├── alert.rules.test.yml                  上述 9 条规则的**离线语义**用例（promtool test rules）
│   ├── grafana/
│   │   ├── datasource/prometheus.yml         provisioning 数据源（uid=commerceql-prom）
│   │   ├── provider.dashboards.yml           dashboard provider（缺它则 /var/lib/grafana/dashboards 无人扫）
│   │   └── dashboards/commerceql.json        §15.5 五屏（uid=commerceql-w7，schemaVersion 39）
│   └── README.md                             本文件
└── runbook/                                  README.md + RL-1…RL-6（同属 W7）
```

> 历史包袱澄清：本目录早期被放在 `backend/deploy/observability/`，那层**从未存在过也不需要**
> —— 与 compose 不同层的唯一后果是挂载要写 `../backend/...`，而写错一层的表现是"容器起来、
> 目录被 Docker 建成空文件夹、看板全黑"。现已收敛到单层（§五 ⑥ 记录结论）。

## 一、当前状态下怎么起

前置事实（**均已落地，不是"等主窗口"**）：

| 依赖 | 位置 | 状态 |
|---|---|---|
| `GET /api/v1/metrics` | `app/api/routers/health.py:310` → `metrics.render_prometheus_text()` | ✅ 本窗口实现，Content-Type `text/plain; version=0.0.4; charset=utf-8` |
| prometheus / grafana 服务 | `deploy/docker-compose.yml`，`profiles: ["observability"]` | ✅ 已在文件里（**默认不起**） |
| dashboard provider | `./observability/grafana/provider.dashboards.yml` | ✅ 已存在（早期 README 说"缺这一个文件"，已补） |
| 镜像 | `prom/prometheus:v2.54.1` · `grafana/grafana:11.2.0` | ✅ 版本已固定；`v2.54.1` 本机已实际拉取过（用于跑 promtool），`11.2.0` **未拉取过** |

### 1. 先确认端点有输出（不需要观测栈）

```bash
cd CommerceQL/deploy
docker compose up -d pg redis api          # 注意：本机 wsl.exe 被拦截，一律用 compose exec/run，别写"进 WSL"
docker compose exec api python -c "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8000/api/v1/metrics').read(300).decode())"
```

期望看到 `# HELP http_requests_total ...` / `# TYPE ...`。看不到就**先别往下起**——
观测栈起来只会得到一片空白，而"空白"在 Grafana 里和"没有事件"长得一模一样
（§三.4 解释为什么"恒 0 的线"比空白更危险）。

⚠️ api 镜像是 slim 构建，**容器内没有 `curl`** ⇒ 上面这条必须是 `python -c urllib`，
`docker compose exec api curl …` 不可用（runbook 里的同类命令同理）。

### 2. 起观测服务（**profile 已存在，不用改 compose**）

```bash
cd CommerceQL/deploy
docker compose --profile observability up -d prometheus grafana
```

三个必须知道的设计约束：

1. **两个服务名不能被改**：`prometheus.yml` 的 target 是 `api:8000`、数据源 URL 是
   `http://prometheus:9090`，都靠 compose 的默认网络按服务名解析 ⇒ 改名 = 静默断链。
2. **宿主端口只绑回环**：`127.0.0.1:9090` / `127.0.0.1:3000`。9090 与 3000 上都没有鉴权，
   绑 `0.0.0.0` 等于把指标面（含 `rule_id` 分布、真实成本）重新对外打开。
3. **没开 `--web.enable-lifecycle`**：改 `alert.rules.yml` 后要 `docker compose restart prometheus`
   才生效（少一个"能远程触发的写接口"是刻意的）。Grafana 未设管理员口令（口令进不了
   `.env.example`，写死在受版本管理的文件里更糟），默认 admin/admin + 只绑回环；
   **任何对外开放 3000 的改动都必须先改口令**。
   ⚠️ 本窗口没起过 Grafana ⇒ 首屏登录/改密行为**未验证**。

**不开 profile 时的现象是预期的，不是故障**：Prometheus/Grafana 不存在 →
看板全黑、`up` 无序列。W6 的门禁判定与日常联调只依赖 `api/web/pg/redis`，
所以观测栈被放在 profile 里而不是主干（理由写在 compose 的注释块）。

### 3. 需要哪些 env

**本目录的配置不读任何 env。** Prometheus 与 Grafana 的配置全部是字面量——
这正是 §15.4 第 5 条（日成本）当前的**弱点**：预算阈值写死为 `80` / `100` 元。

| 事实 | 出处 |
|---|---|
| 告警比例 80% / 100% | 07 §10.4「80% 告警 / 100% 硬熔断（NFR-4.2）」+ 附录 D §D.4.1 `BUDGET_ALERT_RATIO=0.8` |
| 预算 `DAILY_BUDGET_CNY` | 代码默认 100.0（`app/core/config.py:148`）；当前 `deploy/.env` = 100 |
| **但分环境不同** | 附录 D §D.4.2：dev=**20** / staging=**50** / prod=**100** |

⇒ **换环境必须同步改**`alert.rules.yml` 组 3 的 `80/100` 与看板屏④的两条 `vector()` 参考线
（dev 应为 16/20）。Prometheus 读不到应用的 env，是静默失效的那种。彻底修法见 §五 ①。

### 4. 校验：离线（不需要共享栈）与在线（需要）两条路

本窗口与 W6 **并行共用同一条 `main` 和同一套本机容器**。`--profile observability up` 会因
`api` 的配置哈希变化（本轮加了 `DRAIN_TOKEN`）而**重建 api 容器**，把 W6 正在用的实例打断
⇒ 本窗口的规则校验**全部走离线**，不碰共享栈。

**(a) 离线：promtool，三条命令都真跑过**（工作目录 `CommerceQL/deploy`）

```bash
# Git-Bash 会把 /bin/promtool 改写成 D:/Git/usr/bin/promtool ⇒ MSYS_NO_PATHCONV=1 是必须的
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/observability:/etc/prometheus:ro" \
  --entrypoint /bin/promtool prom/prometheus:v2.54.1 check rules /etc/prometheus/alert.rules.yml

# test rules 的 `rule_files` 用相对路径（相对测试文件自身），所以只挂一个目录就够
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/observability:/c:ro" --workdir /c \
  --entrypoint /bin/promtool prom/prometheus:v2.54.1 test rules /c/alert.rules.test.yml

# check config 必须按**容器内真实挂载路径**挂，否则 rule_files 的绝对路径匹配不到（= 另一种静默）
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$PWD/observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/observability/alert.rules.yml:/etc/prometheus/rules/alert.rules.yml:ro" \
  --entrypoint /bin/promtool prom/prometheus:v2.54.1 check config /etc/prometheus/prometheus.yml
```

**(b) 在线：起栈之后才跑得动**（本窗口**未执行**，命令留给主流程/验收）

```bash
curl -s http://127.0.0.1:9090/api/v1/targets | grep -o '"health":"[a-z]*"'   # commerceql-api 应 up
curl -s http://127.0.0.1:9090/api/v1/rules   | head -c 400                    # 9 条规则都被加载
```

浏览器：`http://localhost:9090/alerts`（十条的实际可见形态）· `http://localhost:3000` → 看板
`CommerceQL · 阶段 7 最小看板`。

## 二、`alert.rules.yml` 的 9 条规则（真实规则名，供 runbook 路由表引用）

| 组 | 规则名 | 级别 | 对应 §15.4 |
|---|---|---|---|
| `commerceql-security` | `CommerceQLGateRejectSilence` | P0 | 第 1 条（**间接探测**） |
| | `CommerceQLUiContractViolation` | P0 | 第 3 条 |
| `commerceql-latency-and-capacity` | `CommerceQLP95LatencyHigh` | P1 | 第 4 条 |
| `commerceql-cost` | `CommerceQLDailyCostWarning` | P1 | 第 5 条 80% 档 |
| | `CommerceQLDailyCostBreach` | P0 | 第 5 条 100% 档 |
| `commerceql-quality` | `CommerceQLTokensPerRequestWeekOverWeekRise` | P2 | 第 7 条 |
| | `CommerceQLClarifyRateHigh` | P1 | 第 9 条 |
| | `CommerceQLBindingL4RateHigh` | P2 | 第 10 条 |
| `commerceql-observability-self` | `CommerceQLMetricLabelOverflow` | P1 | 超出 §15.4（观测层自检） |

每条规则的 `annotations.coverage` 里都写了**这条在本轮的真实可响性**（已接线 / 已接线但有条件 /
序列恒 0 / 自身即计数器）。**读规则先看 coverage 注解，不要看 expr 存在就认为它会响。**

### §15.4 十条的逐条覆盖结论（**这就是"覆盖了什么/没覆盖什么"的答案**）

| # | §15.4 规则 | 级别 | 本文件的处置 | 判据所在 |
|---|---|---|---|---|
| 1 | 危险 SQL 放行 >0 | P0 | **只写了间接探测** `CommerceQLGateRejectSilence`（闸门 30min 零拒绝 + 有足量查询） | 直接判据 = CI 红队门禁 **G-3**，**无生产指标** |
| 2 | 跨租户泄露 >0 | P0 | ⚠️ **无 expr**（注释块逐个否决了 4 种"凑法"） | 渗透测试 + 门禁 **G-4**；`exec_failure_total{permission}` 语义相反且**永远不会增**（§三.2） |
| 3 | `ui_contract_violation` >0 | P0 | ✅ `increase(...[5m]) > 0`，kind **五**值 | §15.3 契约行「非零即 P0」 |
| 4 | P95 >15s | P1 | ✅ `histogram_quantile(...)`，桶边界含 8.0/15.0 不插值；自抓取路径在采集侧跳过（非规则里的 filter） | §15.3 系统行；G-6 的 8s 是压测口径，不是本告警 |
| 5 | 日成本 80%/100% | P1/**P0** | ✅ 两条；⚠️ **已接线但有条件**（`cost_ledger` 为 None 时采样器不注册 ⇒ 恒 0 序列 ⇒ 静默不响） | §10.4；自证 = 启动日志 `obs_wiring_done` 的 `samplers=[...]` |
| 6 | 准确率周环比 −10% | P1 | ⚠️ **无 expr** | W6 影子/离线评测报告 `backend/reports/w6/`；`outcome=success` 是"跑完了"不是"对" |
| 7 | token/请求 周环比 +40% | P2 | ✅ 表达式就绪；⚠️ `llm_tokens_total` **序列恒 0**（无调用点）⇒ 当前不会响 | §15.4 原文点名它是"prompt/输入分布变了"的信号 |
| 8 | 429 比率 >5% | P2 | ⚠️ **无 expr** | `status_class()` 只有 2xx/3xx/4xx/5xx；§14.5 要求的 `bucket` 标签**无指标使用它** |
| 9 | 澄清率 >15% | P1 | ✅ `outcome=clarify / 全体 outcome`（**照 §14.5 与 metrics.py help 原文**，不用 `clarify_total`） | NFR-7.1；⚠️ G-8 后半条"澄清后一次成功率"无指标来源 |
| 10 | L4 触发率 >10% | P2 | ✅ 只覆盖 PRD §12.9 升级评估三条件的**条件①**；②③ 无指标来源 | PRD §12.9 约束 5 + §6.8.2/§6.8.3 + N-27④ |
| +1 | `metric_label_overflow_total` >0 | P1 | ✅ 委托方要求的第 11 条（**超出 §15.4**，已在文件里标注） | §15.3 纪律②③；它响了，同窗口其它规则读数都要打问号 |

**Runbook 编号已核对**：`deploy/runbook/` 的文件名即
`RL-1-audit-db-failure-fail-closed` / `RL-2-ollama-unavailable` / `RL-3-checkpoint-write-slowdown`
/ `RL-4-upstream-llm-failure` / `RL-5-dangerous-query-alert` / `RL-6-cost-anomaly` —— 与
07 §18.7 表格行序一致，`alert.rules.yml` 的 `runbook` 注解按此写。
**并对齐了 runbook README §二.1 的路由表**（那一份是告警→处置的手术入口，本目录必须服从它，不能两处各定一套）：
第 7 条 token/请求 → **RL-6**；第 2 条跨租户 → 与契约违规同走 **RL-5** 入口（尽管它本身无 expr）；
第 6 条准确率 → 转 W6；第 8 条 429 → 转 W4；第 9 条 → 转 W3C/W2A、第 10 条 → 转 W2A（均无 RL 条目，属语义层而非故障）。
⚠️ 反向缺口（**runbook README §二.1 末两行亦独立列出，两份产物互相印证**）：
§15.4 十条里**没有任何一条对应 RL-1 与 RL-2**（审计库故障 fail-closed、Ollama 不可用）——
§18.7 给了判据（`/healthz/ready` 503、`degraded_dependencies` 含 embedding、检索降级率 >5%）
但 §15.4 没把它列成规则。本窗口不越权补第 12 条，登记见 §五 ③。

## 三、明确声明：**未被覆盖 / 未验证**的部分

1. **运行时验证到哪一层（2026-09-19 更新：抓取层已补上，触发层仍未）**。
   已过的机器证据：`promtool check rules`（9 条）、`check config`（含 rule_files 真的被加载）、
   `test rules`（`alert.rules.test.yml`，6 组用例 / 13 个断言），**以及 §六(6) 的真实抓取**
   （手写 exposition 被解析、9 条规则在活序列上 `health=ok`、A/B 族分类被独立复现）。
   **仍未过**：⚠️ **没有任何一条规则在真流量下实际跨越过阈值**（本轮读数全部远低于判据，
   `pending`/`firing` 状态一次都没出现，也不该为了看它亮而去制造超支或超时）。
   ⇒ 所以"表达式的**形状与方向**对不对"目前**只有离线夹具**作证据；
   "在真故障里会不会按预期亮"仍是**未验证**，别把 §六(6) 读成这条也过了。
   Grafana 面板渲染、Alertmanager 送达（根本没有 AM，见第 10 条）同样未验。
2. **§15.4 第 2/6/8 条无 expr**（跨租户 / 准确率环比 / 429）。见上表，注释块里写明了缺口与修法。
   第 2 条尤其要防"凑"：`exec_failure_total{error_class="permission"}` 是**双重不可用** ——
   语义相反（它记的是"被权限层拦住了"= 防住了，不是泄露了），而且**永远不会增**
   （`observe_exec_failure` 的唯一来源是 `SQL_*` 错误码，而 `ErrorCode` 里只有
   `SQL_SYNTAX_ERROR`；真正的权限分类在 `GraphState.exec_error.error_class`，无观察者 → §五 ⑧）。
3. **第 1 条只有间接探测**，且有双侧盲区（真零拒绝会误报、少量放行会漏报）。
   **不得**因该规则存在而声称"危险 SQL 放行已被监控"。
4. **采集端接线现状（必须按两种"没数据"分开读）**。`metrics.render_prometheus_text()` 的导出语义是：
   · **A 类｜恒 0 已导出** = 标签都有声明域（或**根本没有标签**，那是全集退化的特例）⇒ 冷启动就吐一条 0 序列；
   · **B 类｜整族不输出** = 有标签但无声明域且从未观测 ⇒ 文本里连 `# TYPE` 都没有。

   | 指标 | 类别 | 调用点 | 对规则/看板的影响 |
   |---|---|---|---|
   | `llm_tokens_total` | A（`token_key` 有四值域） | ❌ 无（计量在 `app/llm`，W3A 域） | 规则 7 恒假；屏④ token 曲线是一条 0 线 |
   | `retrieval_mode_total` | A | ❌ 无 | 屏③ 检索占比恒 0/0 = 无数据 |
   | `gen_sql_rounds_total` | A（无标签） | ❌ 无 | 屏③ 轮次柱恒 0 |
   | `feedback_reason_total` | A | ❌ 无（反馈端点未回调） | 屏③ "有误"率无分子 |
   | `llm_json_parse_failure_total` | **B**（`prompt_version` 无域） | ❌ 无 | 序列**不出现**，看板上是"缺席"而非 0 |
   | `daily_cost_cny` | A（无标签） | ✅ 有条件（`cost_ledger` 存在才注册采样器） | 熔断装配下**静默恒 0** ⇒ 规则 5 不响 |
   | `event_loop_lag_ms` | A（无标签） | ✅ `samplers.run_loop_lag` @1s | 已接线；但无标签 ⇒ **不能靠"有没有序列"判断采样器活着** |
   | `llm_upstream_concurrency` | **B**（`model` 上界 2、无域） | ⚠️ 采样器已备，等 W3A 的 `inflight(model)` 公开读口 | 序列不出现 |
   | `metric_label_overflow_total` | **B**（`metric` 无域） | ✅ 自身即计数器 | 丢弃动作发生才出现，属正确行为 |
   | HTTP 三面（`http_requests_total` / `http_request_duration_seconds` / `http_requests_inflight`） | **B**（`endpoint` 无域） | ✅ `instrumentation.py` 中间件 | 有流量后正常出现 |

   ⇒ **A 类的 0 线不等于"没数据"，也不等于"健康"**：它同时能被读成"该类事件为零"，
   而真实原因可能是"采集点根本不存在"。规则 5/7 与屏③/④ 的多条曲线现在就是这个形状。
   措辞纪律：只有 B 类可以叫"序列不会出现"。
5. **图节点耗时 Histogram（§15.3 `node`≤20）未采且本文件刻意不登记同名指标** —— 登记一条恒 0
   的 `node` 直方图 = 假仪表。帧里没有节点名，需要 `app/graph/build.py` 的节点包装器加观测钩子
   （W4 域，需求见 `reports/w7/RELAY.md`）；本期用 `stage_duration_seconds{stage}` 承接诊断粒度。
6. **委托清单里的两个"声明式直方图" `retrieval_latency_ms` / `cost_check_ms` 在 `app/obs/metrics.py`
   里根本未声明**（不是"声明了没接线"）。按委托要求未为其写任何规则或面板。
7. **评测沙箱 = SQLite**（07 §17.4）：`EXPLAIN(FORMAT JSON)` 缺失 → gate3 在评测里被跳过；
   **RLS/CLS 完全不被评测覆盖**；pgvector/tsvector 不覆盖。⇒ 屏⑤ 的绿色**不代表**行/列级权限被验证过。
8. **§15.5 屏① 只做了一半**：三探针的逐依赖布尔态与 `degraded_dependencies` 只存在于 JSON 响应体里，
   Prometheus 抓不了 JSON，compose 内也没有 `blackbox_exporter`（该 job 已在 `prometheus.yml` 里
   **整段注释并说明条件**）。屏① 用 `up` / `event_loop_lag_ms` / `http_requests_inflight`
   / `binding_tau_calibrated` 承接，其余在看板描述里如实标注。
   另：`/healthz` 的逐依赖明细现在只进 **WARN 日志**（`_log_probe_details`），不在 JSON payload 里 ——
   附录 A §A.8.4 的 `checks` 只有聚合布尔。
9. **§15.5 屏② 无数据源** → 做成 `text` 面板（G-1…G-8 表格**只有口径、数值留白**）。
   委托清单要求的"必须如实写明"已落在 panel 正文第一行。
10. **§15.5 屏④ 缺"峰值时段占比"**：`daily_cost_cny` 是无标签单值 gauge，明细在未导出为指标的
    `cost_ledger` 里 → 无来源，面板描述里已声明。
11. **无 Alertmanager** → 九条规则的当前唯一消费者是 Prometheus 的 `/alerts` 页面。
    **没有任何告警会送达人**（`alerting:` 段已注释并说明）。§15.4 的 P0 在当下等于"有人去看才会知道"。
12. **`/metrics` 的暴露：公网侧已关闭，宿主侧仍敞着**（见 §五 ⓪）：
    ✅ `deploy/nginx.conf`（归本窗口）已加 `location = /api/v1/metrics { access_log off; return 404; }`
    —— 精确匹配优先级高于 `location /api/` 前缀，不必依赖书写顺序；用 404 而非 403。
    ⚠️ 但 `docker-compose.yml` 的 api 服务仍是 `ports: "8000:8000"`（绑 0.0.0.0）⇒
    宿主本机进程与同网段机器可**绕过 nginx** 直接读 `宿主IP:8000/api/v1/metrics`。
    收紧方式（`expose` 或 `127.0.0.1:8000:8000`）**本窗口刻意未做**：那份 compose 是 W6 正在用的共享栈，
    且他们依赖宿主 `localhost:8000` 直连调试。⇒ 登记为待确认项，不写成"已解决"。

## 四、与委托方给的"指标全量清单"的取值差异（**以代码为准，逐条列出**）

委托清单的表把 `app/obs/metrics.py` 的标签取值写成了另一套字面量。PromQL 的字面量匹配是
**静默失效**的那种（不报错，只是查不到数据），故全部按 enums 实际取值写，差异登记如下：

| 标签 | 委托清单 | **实际取值**（`app/core/enums.py` / `metrics.py`） |
|---|---|---|
| `binding_state_total{state}` | grounded/ambiguous/unbound/off_scope | **resolved_unique / resolved_default / ambiguous / unresolved**（`BindingState`，§6.8.3 原文） |
| `binding_layer_total{layer}` | L1/L2/L3/L4/**miss** | **L1/L2/L3/L4，无 `miss`**（`BindingLayer`） |
| `gate_reject_total{gate_no}` | gate1/gate2/gate3 | **"1" / "2" / "3"**（`str(int(GateNo))`） |
| `gate_reject_total{rule_id}` | 30 个 AST 规则码 + 空串 | **20 个**（`AstRule` R01–R20：14 阻断级 + 2 改写级 `R04/R15` + 4 告警级 `R17–R20`）+ 空串（= 载体本轮未给规则号）；基数上界已同步为 **21**（§五 ②） |
| `http_requests_total{status}` | 2xx/3xx/4xx/5xx/client_error/error | **只有 2xx/3xx/4xx/5xx**（`metrics.status_class()` 做 `code//100`）→ 这正是 §15.4 第 8 条表达不了的根因 |
| `feedback_reason_total{reason_code}` | inaccurate/incomprehensible/slow/other | **10 值**（附录 A §A.6：`wrong_metric_definition` … `other`） |
| `llm_upstream_concurrency{model}` | deepseek-flash/deepseek-pro/local-ollama | 指标**无声明域**（只输出实采序列），且 `BOUNDED_ALLOWED_LABELS["model"]=2`（注释：flash/pro）；采样器未接线 |
| 澄清率口径 | `clarify_total / query_outcome_total` | **`query_outcome_total{outcome="clarify"} / query_outcome_total 全体`**（`QUERY_OUTCOME_TOTAL` help 原文；`clarify_total` 是"为什么澄清"的归因指标） |
| `query_outcome_total{outcome}` | 含 degraded | `degraded` 是**恒 0 的声明序列**（`_TERMINAL_OUTCOME` 不映射它；降级不是终态）⇒ 任何按 `outcome="degraded"` 的判据都是死读；`failed` 由 `error` 帧导出 ⇒ **闸门拒绝也落在 `failed`** |

## 五、待架构窗口分配的问题（**不开 U-xx 编号**，请转 RELAY）

- **⓪ api 的 `8000:8000` 绑在 0.0.0.0，`/api/v1/metrics` 可绕过 nginx 直读**（§三.12）：
  nginx 侧已关闭；剩下的这一步只需把端口映射改成 `expose: ["8000"]` 或 `127.0.0.1:8000:8000`。
  **本窗口单方面未改**（W6 在用的共享栈 + 宿主直连调试依赖它）⇒ 需与 W6 协同后一次改定。P0 级安全边界，**当前半关闭**。
- **① 告警阈值与 `DAILY_BUDGET_CNY` 不同源**：建议应用侧随指标导出 `budget_daily_cny` gauge，
  规则改成 `daily_cost_cny / budget_daily_cny > 0.8`，使阈值与环境同源（附录 D §D.4.2 的 dev/staging/prod 三档）。
- **② ~~`rule_id` 基数上界比取值域小 1~~ → 已修**：`BOUNDED_ALLOWED_LABELS["rule_id"]` 现为 **21**
  （= 空串 + R01…R20），与 `GATE_REJECT_TOTAL` 的域一致；W1B 审计契约里的 `len(AstRule)+1` 断言同步过。
  保留本条是为了记录"上界=取值域大小"这条不变量的来源（§15.3 纪律②）。
- **③ §15.4 与 §18.7 的双向缺口**：RL-1（审计库故障 fail-closed）与 RL-2（Ollama 不可用）在 §18.7 有判据但 §15.4 未列规则；§6.10 甚至把"检索降级率 >5%"直接写成告警口径。是否升格为第 11/12 条由架构定，本窗口不越权。
- **④ §15.5 屏① 的完整兑现需要 `dependency_healthy{dependency,kind}` gauge**（或引入 blackbox_exporter）。二选一，都要跨窗口协作。⚠️ 标签键 `dependency` **尚未**在 `BOUNDED_ALLOWED_LABELS` 注册 ⇒ 直接 `register_metric` 会在声明期抛 `ValueError`，必须先按 §15.3 纪律② 定上界（依赖数 = `DEPENDENCY_KIND` 的键数）。
- **⑤ §15.4 第 8 条（429）需要 §14.5 点名却无人实现的 `ratelimit_reject_total{bucket}`**；标签键 `bucket: 5` 已在 `BOUNDED_ALLOWED_LABELS` 预留但**没有任何指标使用它**。
- **⑥ ~~`deploy` 资产分两层~~ → 已收敛**：本目录与 runbook 均已落在仓库根 `deploy/` 下
  （`deploy/observability/`、`deploy/runbook/`），与 `docker-compose.yml` / `nginx.conf` / `Dockerfile` 同层。
  所有挂载与文档路径已按 `./observability/...` 重写；`backend/deploy/` 不存在也不该存在。
- **⑦ runbook README §二.1 / §四 的措辞要跟本目录对齐**：`deploy/runbook/README.md` 曾写
  「告警规则文件当前不在仓库里 …… 上表的"告警名"目前是**文档名**」—— 已不成立，本文件 §二
  给出了 9 个真实规则名。runbook 侧需 ① 改掉那句，② 把"告警名"列换成 §二 的真实规则名，
  ③ 其中**第 2/6/8 条（跨租户 / 准确率环比 / 429）在 Prometheus 里没有对应规则**，
  表里要继续标成"无告警，靠 X 门禁"，不要因为本目录存在就被补成一条绿线。
  ④ 另外三条命令级事实要一并校正：`/healthz` 逐依赖明细只在 WARN 日志里；
  slim 镜像无 `curl`（用 `python -c urllib`）；`docker compose stop --timeout` 必须 ≥ `stop_grace_period`（40s）。
- **⑧ `GraphState.exec_error.error_class` 无观察者**（§三.2）：权限/超时/行数超限这几类真实执行失败
  目前只存在于图状态里，`exec_failure_total` 只能计到 `syntax_error`。要么 W4/graph 侧补一行回调，
  要么承认 §15.3 的"执行失败分类"这一行只有 1/5 的覆盖面。
- **⑨ 建议加一条资产不变量测试**（本窗口未擅自新建 `tests/**`，因它跨窗口所有权）：
  用纯 Python 解析 `alert.rules.yml` + `commerceql.json` 里的 expr，逐个回查
  `metrics._REGISTRY` 的指标名与标签域 —— 本轮**手工做过一次**（结论见 §六），
  但没有防漂移网：改枚举/改上界不会有任何测试提醒"看板少了一条线"。

## 六、校验记录（本窗口实际跑过的）

**（1）语法层**，工作目录 = `CommerceQL/`（venv 在 `CommerceQL/.venv`）：

```
yaml.safe_load  deploy/docker-compose.yml                                  -> OK
yaml.safe_load  deploy/observability/prometheus.yml                        -> OK
yaml.safe_load  deploy/observability/alert.rules.yml                        -> OK（5 组 / 9 条规则全部可解析）
yaml.safe_load  deploy/observability/alert.rules.test.yml                   -> OK
yaml.safe_load  deploy/observability/grafana/datasource/prometheus.yml      -> OK
yaml.safe_load  deploy/observability/grafana/provider.dashboards.yml        -> OK
json.load       deploy/observability/grafana/dashboards/commerceql.json     -> OK（uid/schemaVersion=39 / 5 panels / templating 齐）
```

**（2）语义层（promtool，镜像 `prom/prometheus:v2.54.1`，命令见 §一.4(a)）**：

```
promtool check rules  alert.rules.yml            -> SUCCESS（9 rules, 5 groups，含 level/threshold/runbook/source/coverage 注解）
promtool check config /etc/prometheus/prometheus.yml
                                                 -> SUCCESS（1 rule file 被真正加载）
promtool test rules   alert.rules.test.yml       -> SUCCESS（6 组用例 / 13 个断言）
```

`alert.rules.test.yml` 是本目录新增的**第 6 个文件**，也是 §15.4 判据方向当前唯一的机器证据。
它覆盖全部 9 条规则的正/负例，其中包括三处刻意设计的坑：
① 手工构造 `gate_reject_total{gate_no="1",rule_id=""} 0x120` 来复现注册表的 A/B 导出语义
（否则"闸门沉默"用例会因为序列根本不存在而假过）；
② P95 用例断言 29.25（所有质量压在 (15,30] 桶时的插值结果），同时断言快桶版本**不触发**；
③ 周环比用例用 `values: '0+1x100 100+2x100'`（1h 间隔 / 200h）来逼出 `offset 7d` 的比值形状。
它的头部写明了**不证明**的三件事：不产生真实序列、不涉及抓取与 Grafana、不涉及告警送达。

**（3）看板 expr 的离线检查**：把 `commerceql.json` 里 15 个 `expr` 抽出来喂 `promtool check rules`
（`$__rate_interval` 会被 promtool 当成空 duration，需先替换成 `5m`）→ 全部 SUCCESS；
再做了一次**跨文件一致性回查**：这些 expr 与 `alert.rules.yml` 里出现的每个指标名 / 标签名 /
标签取值，逐个回查 `app/obs/metrics.py` 的 `register_metric(...)` 声明与 `BOUNDED_ALLOWED_LABELS`
—— 结论：**无越界指标、无越界标签**。

**（4）冷启动导出实测**（`render_prometheus_text()` 在无任何观测下的真实输出）：
A 类恒 0 已导出 **17 族**、B 类整族不输出 **6 族**（清单见 §三.4 的表）。
这条是 §三.4 分类的**唯一依据**，不是从代码注释推出来的。

**（5）文档自身可执行性**（runbook 的价值全在"照着抄能跑"，所以语法漂了等于没写）：

```
markdown 表格列数逐行比对（本 README + runbook 7 个文件）              -> 0 处不一致
表格单元格内的 shell 管道（`\|` 与裸 `|` 两类）                          -> 0 处（命令一律移出表格到代码块）
A/B 族数复测（render_prometheus_text() 冷启动）                        -> 17 导出 / 6 缺席（与 §三.4 一致）
指标调用点复测（grep `metrics.(observe_|inc_|record_|set_)` 全仓）      -> 与 §三.4 的"调用点"列逐项一致
配置可解析复测（compose + prometheus/告警/datasource/provider 共 6 yaml + dashboard JSON） -> 全部通过
```

同一轮里还按**一次性容器的桩实测**改写了 runbook 中"停机链端到端未验证"的旧陈述
（三场景 + `Exited (143)` 与 `137` 的判据）⇒ 证据与边界见 `deploy/runbook/README.md` §四-2。

**（6）真实抓取活体验证（2026-09-19 新增 —— 前五项都只是"文件没错"，这一项才碰到"指标真的进得去 Prometheus"）**

前提：`prom/prometheus:v2.54.1` 本机就有（§一 开头的镜像表记的是准的 —— 缺的只有 `grafana:11.2.0`）。
区别在于本轮**第一次拿它真跑一个实例**，而不只是借里面的 `promtool`。
为不动 W6 的共享栈，用**一次性容器**：挂 `deploy/observability/alert.rules.yml` 到交付文档里那个**绝对路径**（这本身就是要验的点 —— `rule_files` 用绝对路径，换一种挂载布局就会静默变成"规则没加载"），配置文件只改一行 `targets`（`api:8000` → `w7load-api:8000`，理由见下），端口只绑宿主回环。

| 验的东西 | 读数 | 判读 |
|---|---|---|
| **手写 exposition 能不能被真解析器接受**（T2 的核心风险，前五项**一项都没覆盖到它**） | `health=up`、`lastError=''`、`scrapeUrl=http://w7load-api:8000/api/v1/metrics` | ✅ `app/obs/metrics.py` 手写的 text format 0.0.4 被 Prometheus 真解析，不是"看起来像" |
| 规则是否**真的加载**（不是 promtool 静态过） | 启动日志 `Completed loading of configuration file ... rules=6.706817ms`；`/api/v1/rules?type=alert` → **5 组 / 9 条，全部 `health=ok`** | ✅ 9 条表达式在**活数据**上求值通过（含 `histogram_quantile` 与 `offset 7d` 那两条形状复杂的） |
| §三.4 的 A/B 族分类 | 冷启动 **24 族**（19 个应用族 + `up` 与 4 个 `scrape_*`）；发 3 个请求后 **29 族**，新增的 5 个**全部**是 `http_requests_total` / `http_request_duration_seconds_{bucket,count,sum}` / `http_requests_inflight` | ✅ 独立复现"B 类整族不输出、有流量才出现"。这条以前只是读代码推出来的 |
| 计数**语义**对不对（不是只数族） | 3 个无令牌请求 → `http_requests_total{endpoint="/api/v1/query",status="4xx"} 3`、`..._duration_seconds_count 3`、`_sum 0.0083`、`http_requests_inflight 0` | ✅ 401 记成 4xx 而不是成功；直方图与计数器同源；在途归零 |
| 采样器与真库对账 | `daily_cost_cny = 0.064258` ⟷ `select sum(cost_cny) from app.cost_ledger` = `0.064258` | ✅ 成本不是"接了个指标"，是**和账本逐分相等** |
| τ 门禁 gauges | `binding_tau_calibrated = 0` | ✅ 实时反映"未校准"，与 §18.4.1/U-19 的 dev 放行口径一致 |
| **看板引用 ⟷ 实际导出**交叉核对（本轮才做得动：需要一份真序列清单） | 屏①–⑤ 共 15 条 `expr`、引用 11 个族；其中**只有 `http_requests_inflight`** 在冷启动不存在 | ⚠️ 抓到我自己 T7 的一个真问题：刚重启时屏①那条会显示 **No data**，而这正是运维最想看的一刻。已在屏①的 `description`/`legendFormat` 写明"No data ≠ 在途为 0"（**刻意没改成 `or vector(0)`** —— 那会把 B 类缺席这个有信息量的信号抹掉，且 `RL-3` §4 的严格判据就是"出现过且为 0"）|

⚠️ **一条必须跟着读的运维事实**：交付版 `prometheus.yml` 的 `targets: ["api:8000"]` 在**本机现在这台机器上会 DOWN** —— 不是配置错，是 `commerceql-api-1` 的镜像早于 W7 的 metrics 路由，`GET :8000/api/v1/metrics` 返回 **404**（宿主与 compose 网络内各测一次，都是 404）。⇒ 观测栈要看到数据，前提是**被测镜像含 W7 的应用侧改动**（本轮用 `w7load-api`，它由当前源码树构建）。这一条已进 `RELAY.md`。

**仍未验**（别把上面读成这些也过了）：**Grafana 面板渲染**与**反代 `/metrics` 404 的活体行为**（本机确实没有 `grafana` / `nginx` 镜像，dashboard JSON 只过了解析 + 上面那次序列交叉核对）；**告警送达**（compose 里没有 Alertmanager，规则求值过 ≠ 有人被通知）；`/alerts` 页在**常驻**实例上的长观察窗（本次容器只跑了几分钟，`for:` 时长类的Pending→Firing 迁移未被跨越）。
（venv 里 `pyyaml` 已存在，**未新装任何 Python 依赖**；未跑 pytest 全量。）
