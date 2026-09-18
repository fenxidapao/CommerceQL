# W7 runbook 交付自证（07 §18.7 六条 · DoD②）

日期：2026-09-18 · 窗口：W7
**正文在 `deploy/runbook/`**（`README.md` + `RL-1`…`RL-6`），本文只回答一个问题：
**DoD② "runbook 六条可执行" 到底证到了哪一步。** 不重复正文内容。

---

## 一、结论

| 判据 | 判定 |
|---|---|
| 六条文件存在且各有 §触发 / §判定 / §处置 | ✅ 齐（`RL-1`…`RL-6`，共 6 份 + 索引 README） |
| 六条里的**读侧命令**（探针 / 日志 / 指标查询）能执行 | ✅ 部分：探针类已在活栈实测（§三）；指标类在当前活栈**取不到**（原因见 §四-2，属陈旧镜像不是命令写错） |
| 六条里的**处置命令**（重启 / 改配 / 起容器）能执行 | ⚠️ **只证到"命令形态正确"，没证到"处置后系统恢复"**：任何一次真重启都会打断 W6 在用的栈（未授权） |
| DoD② 整体 | **部分达成**：六条"可执行"= 值班照着能走完诊断段；处置段的闭环除 RL-2 的降级读侧外均 **UNVERIFIED** |

把这张表读成"runbook 已可交付值班"是可以的；读成"六条故障演练已通过"是不行的。

---

## 二、六条逐条状态

| 条目 | 诊断入口 | 本轮执行到哪 | 未验证 |
|---|---|---|---|
| **RL-1** 审计库故障（fail-closed） | `/healthz/ready` 的 `metadata_db` + 审计写失败日志 | 读侧：`ready` 在活栈返回 `200` 且 `checks.metadata_db=true`（§三） | 把审计库真打挂 ⇒ 需要停 `pg` 容器 = 打断 W6；fail-closed 的**实际拒绝行为**只有 W1B 的离线契约测试撑着 |
| **RL-2** Ollama 不可用（embedding 软依赖降级） | `/healthz` 的 `degraded_dependencies` | ✅ 读侧在活栈**真 observed**：`embedding=false` 且响应仍是 `200 + degraded`（N-21 的形态成立） | 但活栈那版探针是**阶段 0 骨架**（`probe_detail.embedding` 明写"探针未接线"），⇒ 证的是**端点形态**，不是 W7 `probes.py` 的真实探测逻辑；`retrieval_mode_total` 无调用点 ⇒ 降级率指标当前只能靠日志（README §2.1 已注明） |
| **RL-3** checkpoint 写入变慢 | `/healthz/ready` 的 `checkpointer` + checkpoint 表写入延迟 | 读侧：`checks.checkpointer=true`、`bundle_version` 可见 | 判定要看**真查询**下的延迟；造慢需要打挂/打满 pg ⇒ 未授权。且 §15.4 的 P95>15s 告警只在 observability profile 起来后才求值 |
| **RL-4** 上游 LLM 故障（熔断/降级链） | 三个探针 + 日志错误码计数（`docker compose logs` 取 `LLM_UPSTREAM_ERROR` 等字面量，见该条 §2.2 代码块） | 读侧：`llm=false` 且聚合探针 `200`；日志检索命令形态可跑 | 熔断开路、弱模型切换、重试链**都要真发 LLM 请求** ⇒ 花额度，未跑 |
| **RL-5** 危险查询告警 / 契约违规 / 跨租户 | 闸门拒绝指标 + `ui_contract_violation_total` + drain 重启 | 停机链 **shell 侧已用一次性容器 + 桩实测三条路径**（有 token ⇒ 先置位再转发 TERM；无 token ⇒ `403` 但仍转发不卡死；预算耗尽 ⇒ 照样退出） | 真实 app + 真实 SSE 客户端下的停机未测；闸门"放行=0"的证据属 W4/W6 红队域，不在本窗口 |
| **RL-6** 成本异常（日预算 80%/100%） | `/metrics` 的 `daily_cost_cny` + 成本屏 | 配置侧：告警规则过 `promtool check rules`（离线）；指标族在**源码树**里已注册（契约测试） | 活栈 `/api/v1/metrics` 当前 `404`（§四-2）；且 `llm_tokens_total`/`gen_sql_rounds_total` **无调用点** ⇒ 看板会显示恒 0 线，那**不是**"没花钱" |

---

## 三、本轮对活栈实际执行的读数（2026-09-18）

```bash
B=http://127.0.0.1:8000/api/v1/healthz
curl -sS "$B/live"   # -> 200 {status: ok, uptime_s, event_loop_lag_ms}
curl -sS "$B/ready"  # -> 200 {status: ok, checks:{redis,metadata_db,semantic_bundle_loaded,checkpointer}=全 true, bundle_version}
curl -sS "$B"        # -> 200 {status: degraded, llm: false, embedding: false, degraded_dependencies:[llm,embedding]}
curl -sS "$B/"       # -> 307（FastAPI redirect_slashes；规范路径是**不带尾斜杠**的 /healthz）
```

两点值得值班注意：

1. `ready` 与聚合 `healthz` **同时**给出 `ok` 和 `degraded` 不是矛盾：`ready` 只判硬依赖，
   聚合面把软依赖算进 `status` ⇒ 这正是 N-21 要的"软依赖坏了别让编排摘流量"。
2. ⚠️ 上面这些读数来自**容器里那版代码**，不是当前源码树。取证：
   `docker exec commerceql-api-1 ls /srv/app/api/routers/` → 只有 `__init__.py`、`health.py`；
   `grep -n include_router /srv/app/main.py` 在容器内只有 **1 行**。⇒ 镜像建在 W4 收口之前。
   所以 `bundle_version=2026.09.14.1`、`graph_compiled=false` 这些字段是**旧 payload**，
   不能拿来核对 W7 收敛后的 §A.8.4 字段集（那份由 16 条 `test_health_endpoints_contract.py` 离线钉死）。

---

## 四、为什么处置段整体停在 UNVERIFIED

1. **不能重启共享栈**：`commerceql-api-1` 正被 W6 使用（Up 4 hours），
   `docker compose restart` / `build` 都会打断它的评测会话 ⇒ 未获授权。
2. **`/metrics` 在活栈取不到**：`/api/v1/metrics`、`/metrics`、`/metrics/` 全 `404` ——
   同样是因为镜像陈旧（该路由在源码树里已注册并有契约测试）。
   RL-6 的读侧命令因此**只能**在重建栈之后执行。
3. **造故障=破坏性**：RL-1/RL-3/RL-4 的确诊动作分别是停 `pg`、拖慢 checkpoint、断上游，
   全都在共享栈上 ⇒ 一条都不该在本窗口做。
4. **反代侧没有活体验证**：`web`（nginx）服务在**默认栈里**（不是 profile 后面），
   但当前 `docker ps` 里**没有它**（只有 api/redis/pg），且本机**没有 `nginx` 镜像**
   （`docker images` 实测只有 `redis:7-alpine`、`pgvector/pgvector:pg16`、`prom/prometheus:v2.54.1`）⇒ `deploy/nginx.conf` 里那条
   `location = /api/v1/metrics { return 404; }`（为"不对公网开放指标"而写）只经过配置推理，
   没有一个真实请求证过"外部访问 /api/v1/metrics 得到 404 而容器网络内直连 `api:8000` 抓得到"。
   ⚠️ 同理 **Grafana 看板从未在浏览器里渲染过**（本机也没有 `grafana/grafana` 镜像）：
   §15.5 五块面板交出的是 JSON + 离线校验（provider/datasource 可解析），**不是"截图上墙"**。

---

## 五、值班使用注意（写在这里而不是散在六条里）

| 注意 | 为什么 |
|---|---|
| 用**事件名**检索日志，别用行号 | `app/main.py` 被多窗口追加，行号一直在漂（本轮就修正过 §2.3 表里 6 处）。检索键：`obs_wiring_done`、`drain_trigger_unavailable`、`τ 未校准` |
| 优雅停机后看到 `Exited (143)` 是**正常**的 | dash 在 trap 跑过后会把 `wait` 报成 `128+signo`；**只有 `137` = SIGKILL** 才是 §18.3 要避的"流被硬断"。见 `deploy/docker-compose.yml` 头部 ① 与 `entrypoint.sh` 尾注 |
| 规则文件存在 ≠ 有人被通知 | `deploy/observability/alert.rules.yml` 只在 `--profile observability` 起来后才求值，且**没有 Alertmanager** ⇒ 现状是"有人去 `/alerts` 页面看才知道" |
| §15.4 第 2/6/8 条（跨租户 / 准确率环比 / 429）在 Prometheus 里**没有对应规则** | 别因为规则文件存在就以为有人盯；这三条仍按"靠 G-3/G-4 门禁"执行 |
| `/healthz` 的规范路径不带尾斜杠 | 带斜杠是 `307`，用 `curl -f` 且不加 `-L` 的健康检查会把好端端的探针判成失败 |

---

## 六、DoD② 记法（收口时照抄这句，不要美化）

> DoD② **部分达成**：六条 runbook 的诊断入口均可执行或已执行（活栈探针读数见 §三），
> 处置闭环除 RL-2 的降级读侧外为 UNVERIFIED；根因是被测栈镜像陈旧 + 重启共享栈未授权，
> 不是命令写错。解开需要 `reports/w7/压测报告.md` §五 的授权 A（重建/独立栈）。
