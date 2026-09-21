# Runbook 索引 —— 07 TDD §18.7「关键 6 条」

> 归属窗口：**W7（阶段 7 · 观测与部署）** ｜ 日期：**2026-09-18**
> 依据：`docs/07_技术设计文档_TDD.md` **§18.7**（六条主题与顺序）· §18.2（三探针）· §18.3（优雅停机六步）· §18.4（启动校验八行）· §15.1/§15.3/§15.4/§15.5 · §16.5 · §14.2/§14.5
> 契约优先级：**附录 A(02) > PRD(01) > 06 > 07 TDD > 08**（07 §0.2）。本目录内任何与附录 A §A.8 冲突的表述，以附录 A 为准。

---

## 一、六条清单（主题与顺序逐字取自 §18.7 表格）

| # | §18.7 原文故障名 | 文件 | 一句话主题 |
|---|---|---|---|
| RL-1 | **审计库故障**（fail-closed 生效） | `RL-1-audit-db-failure-fail-closed.md` | 元数据库不可用导致段 1 审计写不进 → 系统**按设计**拒绝下发结果；恢复 DB，不是恢复"绕过审计" |
| RL-2 | **Ollama 不可用** | `RL-2-ollama-unavailable.md` | embedding 是**软依赖**：`200 + degraded` + 检索降 `sparse_only`，**继续服务、不摘流量** |
| RL-3 | **checkpoint 写入变慢** | `RL-3-checkpoint-write-slowdown.md` | 检查点池/`lg` 表族拖慢阶段间耗时；先定位是不是连带把审计池打满 |
| RL-4 | **上游 LLM 故障** | `RL-4-upstream-llm-failure.md` | 熔断开路 → 降级链（flash → 模板）本就是正确行为；**不要重启实例来"恢复 LLM"** |
| RL-5 | **危险查询告警** | `RL-5-dangerous-query-alert.md` | `ui_contract_violation`（帧序列违规）与「闸门放行」（安全边界）**是两个不同的 P0**，处置相反 |
| RL-6 | **成本异常** | `RL-6-cost-anomaly.md` | 日预算 80%/100% 两级；100% 熔断后服务**没停**（转模板），抬预算必须是显式决策 |

---

## 二、谁在什么信号下打开哪一条

### 2.1 按 §15.4 告警规则对应

| §15.4 规则（阈值 / 级别） | 打开 | 备注 |
|---|---|---|
| 危险 SQL 放行（>0 / **P0**） | **RL-5** | §15.4 明写生产侧**无直接指标**，靠"闸门拒绝率突降"间接探测 |
| 跨租户泄露（>0 / **P0**） | **RL-5** | 与契约违规同一入口；专项渗透 + 门禁 G-4 归 W6/W4 |
| `ui_contract_violation`（>0 / **P0**） | **RL-5** | 指标 `ui_contract_violation_total{kind}` |
| P95 延迟（>15s / P1） | **RL-3** → 未命中再转 **RL-4** | checkpoint 变慢与 LLM 重试都会推高 P95；判据见两条的 §判定 |
| 日成本（80% / 100% → P1 / **P0**） | **RL-6** | |
| 准确率周环比（降 >10% / P1） | 转 **W6**（评测域，不属本六条） | |
| token/请求 周环比（升 >40% / P2） | **RL-6** | §15.4：提示 prompt 或输入分布变了 |
| 429 比率（>5% / P2） | 转 **W4**（限流分桶属 `app/api/ratelimit.py`） | `429` **只表示配额**；`409 SESSION_CONFLICT` 不是限流，见 §三-3 |
| 澄清率（>15% / P1） | 转 **W3C/W2A**（绑定与语义包域） | 诊断入口 = `binding_state_total{state}` + `binding_layer_total{layer}` |
| L4 触发率（>10% / P2） | 转 **W2A**（回看语义包，**不是放宽 τ**，N-25） | |
| （§15.4 未列，但 §18.7 列了）审计库 / readiness 503 | **RL-1** | |
| （§15.4 未列）embedding 降级率上升 | **RL-2** | 口径 = `retrieval_mode_total{retrieval_mode="sparse_only"} / sum(retrieval_mode_total)`；⚠️ **该指标无调用点**（恒 0 序列）⇒ 分母为 0、比值无数据，**现在只能靠 `/healthz` 的 `degraded_dependencies` + 日志判 RL-2** |

> ✅ **告警规则文件已在仓库里**：`deploy/observability/alert.rules.yml`（§15.4 十条落成 **9 条规则 / 5 个 group**，
> 已过 `promtool check rules` + `test rules`）。上表的"§15.4 规则"到真实规则名的映射见
> `deploy/observability/README.md` §二（如第 1 条 = `CommerceQLGateRejectSilence`、第 3 条 = `CommerceQLUiContractViolation`）。
> 打开本目录任何一条之前，先读那份 README 的两条限制：
> ① **§15.4 第 2/6/8 条（跨租户 / 准确率环比 / 429）在 Prometheus 里没有对应规则**，
>    表里那些行仍要按"无告警，靠 X 门禁"执行，**不要因为规则文件存在就以为它们有人盯**；
> ② 规则只在 `docker compose --profile observability up -d prometheus` 之后才会被求值 ——
>    默认主干栈不含 Prometheus，且**没有 Alertmanager**，所以现状是"有人去 `/alerts` 页面看才知道"，
>    不是"告警已送达值班人"。

### 2.2 按探针状态对应

| 观察到的状态 | HTTP | 打开 |
|---|---|---|
| `/api/v1/healthz/ready` 的 `checks.metadata_db=false` 或 `checkpointer=false` | 503 | **RL-1**（RL-3 只在"慢但不是假"时） |
| `/api/v1/healthz/ready` 的 `checks.redis=false` | 503 | **RL-1** 的判定分支（同为硬依赖；锁/限流属安全边界，A.8.1） |
| `/api/v1/healthz/ready` 的 `checks.semantic_bundle_loaded=false` | 503 | **RL-5** 的 §处置-3（语义包版本/挂载），并复核 §18.4 五步校验 |
| `/api/v1/healthz` 的 `status="degraded"` 且 `degraded_dependencies=["embedding"]` | **200** | **RL-2** |
| `/api/v1/healthz` 的 `status="degraded"` 且 `degraded_dependencies=["llm"]` | **200** | **RL-4** |
| `/api/v1/healthz` 的 `status="unhealthy"` | 503 | **RL-1**（硬依赖里挑一个） |
| `/api/v1/healthz/live` 非 200 而 `ready` 正常 | 503 | 事件循环阻塞 >5s（A.8.2）→ 见 §四「liveness 无自动消费者」 |

### 2.3 按日志事件对应（JSON Lines，§15.1；字段名即契约）

| 真实事件名（代码里存在） | 落点 | 打开 |
|---|---|---|
| `audit_pre_failed` / `audit_pre_blocked_data` | `app/obs/audit.py:92` / `app/graph/nodes/audit_pre.py:44` | **RL-1** |
| `audit_supp_failed` | `app/obs/audit.py:125` | **RL-1**（段 2 **不阻断**，只告警，§14.2 G2） |
| `semantic_bundle_load_failed` | `app/main.py:151` | **RL-5** §处置-3 |
| `startup_assertions_failed` / `startup_assertion_pending` | `app/repo/startup_assertions.py:768/757` | 按断言名分流（见 §2.4 八行） |
| `checkpoint_schema_created` / `checkpoint_schema_check_skipped` | `app/main.py:187/193` | **RL-3** |
| `graph_runtime_assembly_failed` | `app/main.py:237` | 装配错误（fail-fast），非运维故障 → 回 W4/W7 |
| `binding_tau_is_calibrated=false` | `app/main.py:118`（另有 `app/api/deps.py:770` 同文案） | 不属六条；**非 prod 的既定行为**（U-19 硬要求①） |
| `obs_wiring_done` | `app/main.py:308` | **不属故障**。W7 观测接线的自证：`samplers=[...]` 列出本次真正起了哪几个采样器（`daily_cost_cny` 只在熔断装配下才有 ⇒ 缺 `cost_ledger` 时它是一条静默的 0 线，判 RL-6 前先确认这一行） |
| `drain_trigger_unavailable` | `app/main.py:323` | **不属故障，但影响停机**：`DRAIN_TOKEN` 未设 ⇒ `POST /healthz/drain` 一律 403（fail-closed），重启时只剩 uvicorn 的 5s 收尾。**要停机前先读 §四-2** |

> ⚠️ 上面的行号是 2026-09-19 重新对齐的（`app/main.py` 由多个窗口**追加**，行号会漂）。
> 因此**行号只当"大概在哪"用，检索请用事件名**：`grep -rn "事件名" backend/app/`。

### 2.4 §18.4 八行启动校验的逐条核对（08 §3.9⑦「启动校验全量」）

> 用法：容器反复重启 / `docker compose logs api` 里有 `startup_assertions_failed`
> 或 `refused_to_start` 时，按**断言名**在下表找到那一行，再看"失败动作"决定是配置错还是依赖没起。
> 八行**全部有实现处、全部有钉死测试**（本轮逐条对过，测试名都是真的能 `pytest -k` 到的）。

| # | 校验（§18.4 原文顺序） | 实现落点（归属） | 失败动作 | 钉死测试 | 可判性（本机实测） |
|---|---|---|---|---|---|
| 1 | 必填环境变量齐全 | `app/core/config.py` 的 `Settings`（`Field(...)` 必填 + DSN 形态 + 值域，W0） | 拒绝启动（pydantic `ValidationError`） | `tests/contract/test_config_failfast.py`：`test_minimal_env_is_valid`、`test_dsn_must_be_psycopg3`、`test_analytics_dsn_must_be_psycopg3`、`test_dsns_must_differ`、`test_invalid_timezone_refuses`、`test_invalid_log_level_refuses` | ✅ 离线可判 |
| 2 | `ANALYTICS_DB_URL` 角色具备 `default_transaction_read_only`（N-02） | `app/repo/startup_assertions.py:230` `evaluate_analytics_is_read_only`，SQL 在 `app/repo/dsn.py:126`，角色由迁移 0001 `ALTER ROLE app_ro SET …` 建立（W1B） | prod 拒绝启动；非 prod 且连不上 ⇒ **PENDING**（`startup_assertion_pending` WARN） | `tests/unit/test_startup_assertions.py`：`test_analytics_read_only_pass`、`test_analytics_read_only_fails`、`test_read_only_flag_is_case_insensitive` | ✅ **活体已判**（2026-09-19，`w7load-api` 启动日志）：detail="角色 'app_ro'：非超级用户且 default_transaction_read_only=on" ⇒ 真角色真的只读。⚠️ 区分不变：离线单测判的是**判定函数**，这一格判的是**真库**（`tests/integration/` 仍默认不跑） |
| 3 | `EMBEDDING_DIM` 与向量列维度一致 | 同上文件 `:288` `evaluate_embedding_dim`（W1B） | 维度不符 ⇒ 拒绝启动；**列还没物化 ⇒ PENDING**（不是 FAIL） | `test_vector_column_absent_is_pending_not_fail`、`test_embedding_dim_fails`、`test_embedding_dim_pass` | ✅ **活体已判**（同上）：detail="EMBEDDING_DIM=1024 == 向量列 vector(1024)" ⇒ 列**已由 W2A 物化**，本行不再是 PENDING。⚠️ 判定范围只有"配置维度 vs 库内列维度"，**与 embedding 服务是否真在提供 1024 维无关** ⇒ 模型缺席时它照样 PASS（见 `RL-2` §2 的表） |
| 4 | 语义包通过 §6.1 五步校验 | 判定壳 `…startup_assertions.py:419` `evaluate_semantic_bundle`；**校验器由组装根注入**：`app/main.py:157-163` → `app.semantics.validate_bundle_path`（W2A 实现、W2-INT 接线） | 校验不过 ⇒ 拒绝启动；**没注入 callable ⇒ PENDING 并点名 W2A** | `test_semantic_bundle_slot_is_pending_and_names_w2a` + `tests/unit/test_semantics_loader.py`（五步本体） | ✅ 注入已落地（第 4 行不再是"等上游"），真实包判过与否取决于挂载的 bundle |
| 5 | `audit_log` 存在且 `app_rw` **无** UPDATE/DELETE（N-09 前提） | 同上文件 `:356` `evaluate_audit_append_only`（W1B）+ 迁移 0001 的 `REVOKE` | 表缺失或权限没收紧 ⇒ 拒绝启动；连不上 ⇒ PENDING | `test_audit_append_only_pass`、`test_audit_table_missing_fails`、`test_audit_append_only_fails`、`test_superuser_connection_is_reported_first`、`tests/integration/test_audit_append_only.py`、`tests/contract/test_obs_audit_contract.py`（应用侧无 UPDATE/DELETE 的静态断言） | ✅ **活体已判**（同上）：detail="角色 'app_rw'：INSERT ✅ / UPDATE ❌ / DELETE ❌ / TRUNCATE ❌ 且触发器在位"，与 `RL-1` §2.5 用 `has_table_privilege` 的独立读法同值。⚠️ 告诫不变：**别用超级用户连着跑这条断言**（会被单列报出"权限判定失真"）。注意区分两件事：以 `postgres` 走 `psql` **查目录表**（`pg_roles` / `has_table_privilege`）是只读旁路，可用；要失效的是**让被测连接本身以超级用户身份去满足断言** |
| 6 | 结果缓存开关为 `on` 时必须有显式确认标志（ADR-12） | `app/core/config.py:201`（W0） | 拒绝启动 | `test_result_cache_requires_explicit_confirmation`、`test_result_cache_ok_with_confirmation` | ✅ 离线可判 |
| 7 | `CORS_ALLOWED_ORIGINS` 在 `APP_ENV=prod` 时必须为空（§8.6.5） | `app/core/config.py:197`（W0） | 拒绝启动 | `test_prod_forbids_cors` | ✅ 离线可判 |
| 8 | τ 三元组齐备（`BINDING_TAU_MODEL_ID` + `PROMPT_VERSION` + `CALIBRATED_AT`） | `app/core/config.py:245`（prod 校验）+ `:289` `binding_tau_is_calibrated` 属性（W0，U-19 的 env-gate） | **仅 prod** 拒绝启动；非 prod **放行但不得隐瞒** | 双向往返：`test_tau_gate_is_prod_only_by_design`（+ `test_tau_uncalibrated_boots_in_dev`、`test_tau_uncalibrated_refuses_in_prod`、`test_tau_gate_does_not_apply_to_staging`）；"不隐瞒"三条：`tests/contract/test_obs_audit_contract.py` 的 `test_startup_warn_is_emitted_when_tau_uncalibrated`、`test_gauge_reflects_calibration_state`、`test_gauge_is_exposed_in_prometheus_text` | ✅ 离线可判（这是八行里唯一"放行"的一行） |

**两条必须一起读的口径**：

1. **第 1 行不能按附录 D §D.4 逐字核**。本轮实测 `docs/05 §D.4.1` 与 `deploy/.env.example` 已不等：
   §D.4.1 有 **5 个键在代码里根本不存在**（`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` /
   `LANGFUSE_HOST` / `TRACE_SAMPLE_RATE` —— PRD 里写的是"**选配** Langfuse"，07/08 从未要求；
   `TOKEN_PRICE_PEAK` 则被"按真实时段计价 + 估算走高峰上界"取代，见 `app/llm/budget.py:22-29`，
   实现**比那个开关更严**）；`.env.example` 另有 **30 个键不在 §D.4.1** 里（τ 三元组、GATE3、
   HNSW、融合权重等，后续窗口新增）。⇒ 权威判据是 **`Settings` 的 `Field(...)` 集合**
   （且 `test_env_example_covers_every_setting` 双向钉住），文档漂移 → **待架构窗口分配编号**。
2. **`PENDING` 不是"通过"**。第 2/3/5 行要连真实依赖才判得动，`app/main.py` 的
   `startup_assertions_done` 会把它们列进 `pending=[...]`。判据写在
   `tests/unit/test_startup_assertions.py::test_pending_is_fatal_only_in_prod_by_design`：
   **prod 下 PENDING 升级为拒绝启动**，非 prod 放行 —— 所以"本地起得来"不代表这三条过了。
   ✅ 这一条**已从"只有日志"变成可查询**（★ U-105，2026-09-20 裁定 + W7 接线）：
   `startup_assertion_state{assertion,assertion_status}`（gauge，1=当前态；5×3=15 条序列 —— 上界已按 U-111 预留第 5 条断言）。
   运维查法：`count(startup_assertion_state{assertion_status="pending"} == 1) by (instance)`
   ⇒ "有多少实例端着未判定断言在跑"第一次有了数。
   ⚠️ 读法两条：① 该族**整族不输出**不代表"没有 pending"，而是**进程没跑到 lifespan 第 3.5 段**
   （取值域在那里绑定；没绑定时任何写入会当场抛，不会静默）；
   ② 本窗口**尚未对绑定后的导出面做活体抓取**（容器要重建才能带上新代码）⇒ 这一格目前是
   "代码+契约测试已判、活体读数待复跑"，不要当已验证。

---

## 三、五条硬纪律（六条共同遵守，违反即返工）

1. **软依赖不得变成不可用**。LLM / embedding 失败 → `/healthz` **必须 `200` + `status:"degraded"`**，只有硬依赖（元数据库 / checkpointer / Redis / 语义包）失败才是 `503`（附录 A §A.8.1、§A.8.4；07 §18.2；N-21）。**任何"重启 api 来恢复 LLM/embedding"的建议都是错的** —— 那会把一次降级放大成一次事故。
2. **停机不用 `docker kill` / `kill -9`**。§18.3 期望顺序：`SIGTERM` → 摘 readiness → drain 在途 SSE ≤30s → 超时流发 `error(INTERNAL, message="服务重启中，请重试")` + `terminal:true` → 释放会话锁/归还连接 → 写审计 `outcome=failed` → 退出。静默断连会让前端永远停在"加载中"。**先读 §四-2 的现状声明再决定要不要重启。**
3. **`429` 与 `409` 是两件事**。`429 RATE_LIMITED` = 配额超限，按桶给 `Retry-After`（30/5/10/60，`GLOBAL_CONCURRENCY` 无该头语义）。`409 SESSION_CONFLICT` = 会话串行冲突（`SESSION_LOCK_WAIT_MS=3000` 内没等到锁），**不是限流**，处置是"串行化本身生效了"，**不得写成"等 Retry-After 就行"**（它带的 `Retry-After: 3` 是附录 A §A.11 的补充约定，不是配额窗口）。二者也不共用指标（§14.5）。
4. **不伪造能力**。凡是当前环境做不到的步骤，本目录一律标 `UNVERIFIED` 或「需在真 PG 环境验证」。**标了 UNVERIFIED 的条目不得在交付报告里写成"已验证"。**
   ⚠️ 但**别照抄旧版那句"PG 可能未起 / 没有 pgvector"** —— 2026-09-19 实测两点都已变：本机 **PG 在跑**（`alembic_version=0005`，`app` schema 有 1,940,300 行业务数据），**pgvector 已装**（`pg_extension` 里 `vector 0.8.6`，`app.embed_doc.embedding` 是 `vector(1024)`）⇒ 凡"需要真 PG 才能判"的步骤，**在本机已经可以判**，不要再拿沙箱形态当挡箭牌。
   仍然**不成立**的环境事实（这几条没变）：没有 K8s、没有第二台机器可横向扩展、宿主 Ollama **缺 `bge-m3`**（RL-2）。
   镜像面按 `docker images` 实测分两半（**别整句照抄旧版**）：`prom/prometheus:v2.54.1` 与 `edoburu/pgbouncer:latest` **在本机就有** ⇒ Prometheus 侧的抓取/规则**可以在本机真跑**，不要再说"拉不到镜像"；`grafana` 与 `nginx` **确实没有** ⇒ 看板**渲染**与反代 `/metrics` 404 的活体行为仍未验（dashboard JSON 只过了解析，告警规则只过了 `promtool`）。
5. **编号纪律**：本目录**不开任何 `U-xx` 编号**。发现的文档/实现不一致，一律写成「**待架构窗口分配编号**」，由架构窗口登记到 07 §4.8。

---

## 四、诚实边界（打开任何一条之前先读这七行）

| # | 现状 | 影响 |
|---|---|---|
| 1 | **liveness 当前没有自动消费者**。单机 Compose 不会因 `unhealthy` 重启容器（附录 A §A.8.2 已诚实标注） | 探针就位 ≠ 自愈闭环；本目录不得把任何一条写成"自动恢复" |
| 2 | **§18.3 停机链已闭合并且 shell 侧已实测（桩）**。第 1~3 步（W7）：PID 1 = `deploy/entrypoint.sh` → trap TERM → `drain_client.py begin-wait 32`（`POST /healthz/drain` 摘 readiness + 轮询 inflight 归零）→ TERM uvicorn（`--timeout-graceful-shutdown 5`）→ lifespan 第二道保险（drain 30s，正常路径下 no-op）→ 未终态的流由 `ObservingMiddleware` 在下次 `send` 注入终止 `error` 帧。预算自洽：32+5=37 < `stop_grace_period: 40s` · **已实测**（2026-09-18，一次性 `python:3.13-slim` 容器 + 假 drain 端点，**没碰 W6 在用的共享栈**）：A「有 `DRAIN_TOKEN`」= 置位**之后**在途流才逐条收尾、归零后才转发 TERM（TERM 前连续 3 次 `GET` 恒为 `inflight=3`，排除"归零是巧合"）；B「无 token」= 403 fail-closed 但仍转发 TERM、2s 退出不卡死；C「预算 4s + 40 条慢流」= `排空=no` 后仍转发 TERM、6s 退出 < 40s。· **退出码不是 0**：三个场景都以 **143** 结束 —— dash 在 trap 跑过之后会反复把 `wait` 报成 128+signo（即使服务进程自己 `exit 0`），PID 1 取不到真实退出码，脚本按"不伪造"原样报并写日志。· **未验证的部分**：真实 `app.main:app` + 真实 SSE 客户端的整机重启（要起栈）；**第 4~6 步**（释放会话锁 / 写审计 `outcome=failed`）属 `app/api/runner.py` 的 `finally`（**W4 域，本窗口未复核其实现**） | 可以按 §18.3 的语义执行停机了，**别再 `docker kill`**。判"有没有被硬杀"看 **137**（= SIGKILL = drain 超时，这才是失败形态），**不要把 143 当成事故** —— 它是本脚本的正常产物。首停还要盯 `graceful_shutdown_drained` / `graceful_shutdown_drain_incomplete` 两条日志，出现后者说明还有流没收到终止帧 |
| 3 | **软依赖探针已接线**（`app/main.py:282-285` 注册 `obs_probes.make_llm_probe` / `make_embedding_probe`）。⚠️ 本窗口未起栈复验其返回值 ⇒ "接线"与"探针判得准"仍是两件事 | `/healthz` 的 `degraded_dependencies` 现在反映**依赖真实可达性**，不再是"阶段 0 骨架未接线"的固定噪声。判 RL-2/RL-4 时可以直接读它；但逐依赖的失败原因**只在 WARN 日志**里（`_log_probe_details`），不在 JSON payload —— 附录 A §A.8.4 的 `checks` 只有聚合布尔 |
| 4 | **`/metrics` 已注册**：`app/api/routers/health.py:310` → `render_prometheus_text()`（完整路径 `$BASE/metrics` = `/api/v1/metrics`）。⚠️ 对外暴露**半关闭**：经 80 端口由 nginx `location = /api/v1/metrics` 故意 404，但 compose 的 api 仍 `ports: "8000:8000"`（绑 0.0.0.0）⇒ 宿主进程/同网段机器可绕过 nginx 直读 | 首选 `curl -sS $BASE/metrics`（8000 有宿主映射，最省事；**这条便利本身就是上面那半敞的门**）。无宿主映射时走容器内：`docker compose exec -T api python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/api/v1/metrics').read().decode())"`（slim 镜像无 curl）。收紧需与并行窗口协调，见 `deploy/observability/README.md` §五 ⓪ |
| 5 | **无运维侧 kill switch / 全局降级开关**。§18.7 的"必要时降并发（kill switch）"与"必要时全局降级开关"在 `app/core/config.py` **没有对应字段**（§14.2 G3 未接线） | RL-3/RL-4 的"降并发"只能靠停 `web` 或调 `LLM_SEMAPHORE_*`，已如实写在正文 |
| 6 | **指标"已声明" ≠ "采集端已接线"，而且"没数据"有两种长相**（快照 2026-09-18，按 `render_prometheus_text()` 冷启动实测）。· **已接线**：HTTP 三面（`http_requests_total` / `http_request_duration_seconds` / `http_requests_inflight`）+ `query_outcome_total` / `clarify_total` / `refuse_total` / `degraded_total` / `gate_reject_total` / `exec_failure_total` / `ui_contract_violation_total` / `stage_duration_seconds`（`instrumentation.py`）、`binding_state_total` / `binding_layer_total`（`app/api/deps.py`）、`binding_tau_calibrated`（lifespan）、`event_loop_lag_ms`（`samplers.py` @1s）。· **有条件接线**：`daily_cost_cny` —— 只在 `cost_ledger` 存在时注册采样器，而它**无标签 ⇒ 永远导出一条序列**，所以熔断装配下它是一条**静默的 0 线**（自证 = 启动日志 `obs_wiring_done` 的 `samplers=[...]`）。· **无调用点但仍导出恒 0**：`retrieval_mode_total` / `llm_tokens_total` / `gen_sql_rounds_total` / `feedback_reason_total`（标签都有枚举域）。· **整族不输出**：`llm_json_parse_failure_total`（`prompt_version` 无域）、`llm_upstream_concurrency`（等 W3A 的 `inflight(model)` 读口）、`metric_label_overflow_total`（自身即计数器，出现即真出过事） | **恒 0 的线能被读成"该类事件为零"，而真实原因是采集点不存在** —— 引用未接线指标的判据（RL-2 §4、RL-4 §1/§4、RL-6 §1/§2/§4）当前拿不到真数据，不得据此判"正常"。完整清单见 `deploy/observability/README.md` §三.4 |
| 7 | **`/metrics` 的对外暴露只关掉了 nginx 那一半**（本目录与 `deploy/observability/` 同为 W7 产物，安全边界要一起读） | 任何"把 9090 / 3000 / 8000 开放到内网或公网"的改动之前，先补 api 侧鉴权或收紧端口映射 |

---

## 五、命令约定（六份文件共用）

```bash
# 仓库根（E:\01_实训\...\CommerceQL）
cd deploy                      # docker-compose.yml / Dockerfile / nginx.conf / .env 都在这一层
docker compose ps              # project name = commerceql（compose 里 `name: commerceql`）

# API（宿主映射 8000:8000；经 web 容器则 http://127.0.0.1/api/v1/...）
BASE=http://127.0.0.1:8000/api/v1
curl -sS "$BASE/healthz/live";  echo
curl -sS "$BASE/healthz/ready"; echo
curl -sS "$BASE/healthz";       echo

# 元数据库（compose 里 pg 服务：postgres/postgres，库名 ecom，映射 5432:5432）
docker compose exec -T pg psql -U postgres -d ecom -c '<SQL>'

# 迁移（DSN 只从 MIGRATION_DATABASE_URL 取，无默认值 —— app/repo/migrations/env.py:45-63）
# ⚠️ 它**不在** `deploy/.env` 里：`tests/unit/test_migration_dsn_hygiene.py` 扫的是整个**工作区**
#    （连 gitignore 掉的文件也扫），属主级字面 DSN 落在仓库树里 = DoD④ 当场红。
#    ⇒ 在宿主 shell 里临时导出，值形如 postgresql+psycopg://<属主>@127.0.0.1:5432/<库>
#      （迁移在宿主跑，所以走宿主映射而不是服务名 pg）：
export MIGRATION_DATABASE_URL='<按上面形态填，勿写进任何仓库文件>'
cd ../backend && ../.venv/Scripts/python.exe -m alembic upgrade head
```

**端口与池速记**：`api` 8000 · `pg` 5432 · `pgbouncer` 6432（⚠️ **容器在跑 ≠ 可用**：该镜像默认监听 **5432**，要靠 compose 里显式的 `LISTEN_PORT: "6432"` 才对得上；且 `auth_type=md5` 与 W1B 角色的 SCRAM 口令不兼容 ⇒ 应用侧**一条连接都进不去**，详见 `RL-3` §2.5）· `redis` 6379 · `web` 80 · Ollama **在宿主** 11434（不在 Compose 内，§18.1）· `worker` 属 `profiles: [async]` **P0 不启用**（ADR-15）。
**停机宽限**：`api` 的 `stop_grace_period: 40s` 对应 §18.3 的 drain 30s；`healthcheck` 用 **readiness**（不是 liveness），`start_period: 60s`（Ollama 预热慢）。
**venv**：`CommerceQL/.venv`，从 `backend/` 用 `../.venv/Scripts/python.exe`；本机用 **Git Bash**（不要 PowerShell，零回显）。

> ⚠️ **三条命令级坑（六份 RL-\* 正文共用）**：
> ① 本目录已在 `deploy/runbook/`，与 `docker-compose.yml` **同一层** ⇒ `docker compose …` 的工作目录是
>    **`CommerceQL/deploy`**（不是本目录、也不用 `cd ..`）。
> ② **api 镜像是 slim 构建，容器内没有 `curl`** ⇒ `docker compose exec api curl …` 必然失败。
>    容器内取探针/指标一律用 `docker compose exec api python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/api/v1/…').read().decode())"`；
>    上面那段 `curl` 只在**宿主** Git Bash 里可用（宿主有 curl，且 8000/80 有宿主映射）。
> ③ **只有 `docker compose exec -T` 可用**；绕过 compose 直接 `docker exec -T <容器> …` 在本机 docker CLI 上
>    报 `unknown shorthand flag: 'T' in -T`（2026-09-19 实测）。⇒ 本目录一律写 compose 形式；
>    确实要按容器名直连时**去掉 `-T`** 即可（非交互下 `-T` 本来也没有作用）。

---

## 六、维护

* 六条的**主题与顺序**由 07 §18.7 固定；增删主题需架构窗口改 §18.7，不在本目录自行加条。
* 指标名 / 标签以 `backend/app/obs/metrics.py` 为准；探针语义以 `backend/app/api/routers/health.py` + 附录 A §A.8 为准。三者任一处改名，本目录**同一批**跟着改（名字漂了就等于 runbook 不可执行）。
* 归属（08 §4.1）：`deploy/**`、`app/obs/**` 指标部分、`app/api/routers/health.py` → **W7**；`app/obs/audit.py`、`app/repo/**`、migrations → **W1B**；`app/graph/**`、`app/api/**`（health 除外）→ **W4**；`app/llm/**` → **W3A**；`app/guard/**` → **W2C**；`app/semantics/**` → **W2A**；`app/retrieval/**` → **W2B**；`app/core/**` → **W0**；`eval/**` 执行器 → **W6**；`frontend/**` → **W5**；`app/main.py` → **W1B**（只能追加）。
