# RL-2 · Ollama 不可用（embedding 软依赖降级）

> 归属窗口：**W7** ｜ 日期：**2026-09-18**
> 依据：07 §18.7 第 2 行 · §18.2 · §16.5（检索降级率）· §15.3 · ADR-05/ADR-06 · 附录 A §A.8.1/§A.8.4 · N-21 / NFR-2.7 · 附录 D §D.1.4/§D.5（E-11）
> 共用命令与端口约定见同目录 `README.md` §五。**开工前先读 `README.md` §四-3「软依赖探针已接线」与 §四-6「没数据有两种长相」。**

---

## 0. 一句话定性

**这是降级，不是不可用。** §18.7 处置栏原文："**期间系统按降级路径继续服务（不得摘流量）**"。稠密不可用时走 **稀疏 + Join 图扩展 + 值检索**（`app/retrieval/dense.py:9`、`app/retrieval/fuse.py:68` 的确定性权重重分配），并在 `meta.retrieval_mode=sparse_only` 显式标注（C-11）+ 发 `degraded(embedding_unavailable, sparse_only)`。

---

## 1. 触发信号（真实名字）

| 类型 | 信号 |
|---|---|
| 探针 | `GET /api/v1/healthz` → **`200`**（**必须**是 200）+ `"status": "degraded"` + `"degraded_dependencies": ["embedding"]`（附录 A §A.8.4；`Dependency.EMBEDDING = "embedding"`，`DEPENDENCY_KIND[EMBEDDING] = SOFT`） |
| 探针（反向判据） | `GET /api/v1/healthz/ready` **必须仍是 `200`**。若它也 503 → **不是本故障，转 RL-1** |
| 帧 | SSE `degraded` 事件：`reason=embedding_unavailable` / `action_taken=sparse_only`；随后 `meta.retrieval_mode = "sparse_only"` |
| 指标 | **降级率口径 = `degraded_total{reason="embedding_unavailable",action_taken="sparse_only"}` / `sum(degraded_total)`**（分子分母同族，且本族**已接线** —— `app/obs/instrumentation.py` 的 SSE 帧观测器）。⚠️ 两个**假分母不要用**：① `retrieval_mode_total` 至今无调用点 ⇒ 导出的是恒 0 序列，`0/0` 在 PromQL 里是"无数据"，既不是红线也不是绿线，只在 W2B 接上 `observe_retrieval_mode()` 之后当趋势复核；② `query_outcome_total{outcome="degraded"}` 恒 0 —— 2026-09-21 活体对照：同一次预检里 `degraded_total{reason="embedding_unavailable",action_taken="sparse_only"}=1` 而 `outcome="degraded"=0`，因为被降级请求的**终止态**只记 `refuse`/`clarify` ⇒ 拿它当分母会系统性低估 |
| 告警（§15.4） | §15.4 表内**没有**"embedding 不可用"这一行；它只以"检索降级率上升"出现在 §18.7 的判据里 → 待架构窗口分配编号 |

> ✅ **"未接线"这个第一解释已经作废**（2026-09-18）：`app/main.py:282-285` 注册了 `obs_probes.make_llm_probe` / `make_embedding_probe`，`checks.embedding_reachable` 现在是**真实可达性**，不再是 `health._unwired_probe` 那句 `"阶段 0 骨架：探针未接线"`。所以 `/healthz` 里看到 `embedding_reachable: false` + `status:"degraded"`，**可以直接按本故障走**。
> ⚠️ 仍然要留两句：① 本窗口未起栈复验探针返回值 ⇒ 第一次遇到 `embedding:false` 时先用 §2.2 的宿主侧 `curl :11434/api/tags` 对一下，排除"探针自己判错"（例如 `EMBEDDING_BASE_URL` 在容器里指向 `host.docker.internal` 而宿主没放宽绑定 —— 那是配置故障不是 Ollama 故障）；② **`probe_detail` 已不在 payload 里**（附录 A §A.8.4 没有这个字段），"到底为什么挂"改成一条 WARN 日志：`docker compose logs api | grep healthz_failed_probes`，其 `failed` 字段是 `{依赖: 原因}`。

> ⚠️ **键名以 `checks` 里的那份表为准**（附录 A §A.8.4）：`graph_compiled` / `metadata_db` / `checkpointer_reachable` /
> `redis_reachable` / `semantic_bundle_loaded` / `llm_reachable` / `embedding_reachable` / `embedding_model` / `embedding_dim`，
> 全部**平铺在 `checks` 内**，代码由 `health.py:_AGGREGATE_CHECK_KEYS` 一对一给出（本轮 T3 收敛，不再有"用 `Dependency` 枚举值当键 + 顶层 `probe_detail`"那套私增字段）。
> 判 RL-2 要读的字段是 `degraded_dependencies`（含 `embedding`）而不是 `checks` 的键名 —— §18.7 的原文口径是前者。
> 与 §A.8.4 示例**唯一**剩余的字段差异是 `version` 的字面值（代码 `"0.1.0"` vs 示例 `"1.0.0"`），登记在 §5 末行。

---

## 2. 判定

```bash
# 工作目录：仓库根 CommerceQL/（下列 docker compose 命令再 cd deploy）
BASE=http://127.0.0.1:8000/api/v1
# 2.1 先确认「200 + degraded + embedding」而不是 503；失败原因看 WARN 日志 healthz_failed_probes
curl -sS -o /dev/null -w 'aggregate=%{http_code}\n' "$BASE/healthz"
curl -sS "$BASE/healthz"; echo                          # 原样读即可，不必在宿主装 JSON 工具
curl -sS -o /dev/null -w 'ready=%{http_code}\n'   "$BASE/healthz/ready"   # 期望 200，全程不得变
```

```bash
# 2.2 宿主侧：Ollama 在不在（ADR-05：它【不在 Compose 内】，跑在宿主）
curl -sS http://127.0.0.1:11434/api/tags          # 期望返回模型列表；连接被拒 = Ollama 没起或没放宽绑定

cd deploy
# 2.3 模型是否已拉 + 维度对不对（bge-m3 = 1024 维，ADR-06）
curl -sS http://127.0.0.1:11434/api/tags | grep -o 'bge-m3[^"]*' | head -1
docker compose exec -T api \
  python -c "import os;print(os.getenv('EMBEDDING_MODEL'),os.getenv('EMBEDDING_DIM'),os.getenv('EMBEDDING_BASE_URL'))"

# 2.4 容器内可达性（附录 D §D.5 第 14 步的**可执行版**）
#     ⚠️ 镜像是 python:3.13-slim，**没有 curl**；附录 D 写的 `docker compose exec api curl ...` 跑不通，
#        这里一律用 python urllib（compose 的 healthcheck 也是这么写的）
docker compose exec -T api python -c "import os,urllib.request as u;\
print(u.urlopen(os.environ['EMBEDDING_BASE_URL'].rstrip('/')+'/api/tags',timeout=10).status)"
```

**判定表（三个根因，处置不同）**

| 现象 | 根因 | 走 |
|---|---|---|
| 2.2 连不上（宿主也拒） | Ollama 进程没起 | §3-1 |
| 2.2 通、2.4 不通 | **E-11**：宿主仍绑 `127.0.0.1`，或容器 `EMBEDDING_BASE_URL` 写了 `127.0.0.1`（compose 已覆盖成 `host.docker.internal:11434`，`deploy/docker-compose.yml:86`） | §3-2、3 |
| 2.2/2.4 都通、但报维度/模型错 | `EMBEDDING_MODEL` / `EMBEDDING_DIM` 与索引不一致（§18.4 第 3 行断言 `embedding_dim_matches_vector_column`） | §3-4，**这是配置级故障，可能拒绝启动** |
| 只是**慢**（首次调用几十秒） | 模型未预热（`start_period: 60s` 与 `EMBEDDING_TIMEOUT_SECONDS=30` 就是为它准备的） | §3-5 |

`UNVERIFIED` 的当前状态（2026-09-19 按本轮实测逐项收口，**不要整段照抄旧口径**）：

| 步骤 | 状态 | 实测 |
|---|---|---|
| 2.2 宿主 Ollama 在跑 | ✅ 已验 | 起进程后 `11434/api/tags` 可答 |
| 2.4 容器内可达 | ✅ 已验（**E-11 在本机不成立**） | 容器内经 `http://host.docker.internal:11434` 实测 **23ms** 拿到响应（`extra_hosts: host-gateway` 生效）⇒ 判据表的"2.2 通、2.4 不通"这一格本轮**未被走到** |
| 2.3 模型已拉 + 维度对 | ❌ **仍不可观测** | `bge-m3` 不在 `/api/tags`；`ollama pull bge-m3` 到 **83%** 后停摆（末次读数 1.8 KB/s、ETA≈29h）⇒ 属网络面阻塞，非本 runbook 可解 |
| 降级分支（本条的正题） | ✅ 已验 | embedding 不可用时 `GET /healthz` → **200** + `status=degraded` + `degraded_dependencies:["embedding"]`，且 `checks.llm_reachable=true` ⇒ **N-21（软依赖失败不得 503）活体成立** |

⚠️ 两个不得外推：① 上表验的是"**失败时**降级正确"，**不是**"模型可用"。
`embedding_dim_matches_vector_column` 本轮**合法 PASS**（容器日志原文 `detail="EMBEDDING_DIM=1024 == 向量列 vector(1024)"`
⇒ `app.embed_doc.embedding` 确实已物化成 `vector(1024)`），但**它的判定范围只有"配置维度 vs 库内列维度"**，
与 embedding **服务**是否真在吐 1024 维无关 ⇒ `bge-m3` 缺席时它**照样 PASS**。
不要拿这条 PASS 去否定 R4：**没有任何一次查询走到执行**（`stage_duration_seconds_count{executing}=0`，见 `压测报告.md` §四 R4）。
② 维度一致性断言要连**真 PG + pgvector**，SQLite 沙箱形态下该断言是 `PENDING`（不是通过）—— 本轮它之所以可判定，
正是因为跑在真 PG 上（`load_synth_to_pg.py` 那套装载已把元库建到位）。

---

## 3. 处置动作

1. **起宿主 Ollama**（Windows 侧，不进 WSL —— 07 §18.8/`docker-compose.yml` 头注：`wsl.exe` 被安全策略拦截）：确认 Ollama 服务已运行并监听 11434。
2. **放宽宿主绑定**（仅本机/内网，**绝不公网**；这是**安全面变化，必须写进部署记录**，附录 D §D.1.4 的安全说明）：

   ```
   OLLAMA_HOST=0.0.0.0        # 宿主环境变量，改完重启 Ollama 服务
   ```

   ⚠️ 这一步是宿主动作，**不需要、也不应该重启 api 容器**。
3. **确认容器用对了地址**（`deploy/.env` 与 compose 的 `environment:` 双写，compose 优先）：

   ```bash
   cd deploy && grep -n "EMBEDDING_BASE_URL" .env docker-compose.yml
   # 后端【容器化】= http://host.docker.internal:11434（compose 已硬覆盖，改 .env 无效）
   # 后端【本地 uvicorn】= http://127.0.0.1:11434（§18.8 E-1 的开发形态，此时不要用 compose 的 api 容器）
   ```
4. **模型缺失**：`ollama pull bge-m3`。若换模型 → 属**版本递增 + 重建索引**的动作（`EMBEDDING_DIM` 参与向量索引 DDL，附录 D），**不得**只改 `EMBEDDING_MODEL` 就重启 —— 那会撞上启动断言并按 §18.4 **拒绝启动**。
5. **冷启动慢**：预热一次即可，不要调低 `EMBEDDING_TIMEOUT_SECONDS`：

   ```bash
   curl -sS http://127.0.0.1:11434/api/embeddings -d '{"model":"bge-m3","prompt":"warmup"}' -o /dev/null -w '%{http_code} %{time_total}s\n'
   ```
6. **⛔ 禁止清单**：
   * **不得为"恢复 embedding"摘流量或重启 api**。§18.7 明写"继续服务、不得摘流量"；`docker kill`/`kill -9` 更禁止（会打断在途 SSE + 丢审计，§18.3）。
   * **不得把 `EMBEDDING` 加进 `READINESS_DEPENDENCIES`**。那是 `app/core/enums.py:890` 从 `DEPENDENCY_KIND` 推导出来的**结构约束**（不是"实现者记得就行"），且该文件归 **W0**；把软依赖塞进 readiness = 把降级变成不可用（N-21），"摘了一台其实还能服务的机器"。
   * **不得把 `EMBEDDING_REQUIRED` 改成 `true`** 来"强制暴露问题"。它是**降级策略开关**（`deploy/.env:79` 注释：`false = 不可用时走降级并在 meta 显式标注`），改成 `true` 会把一条已设计好的降级路径变成 500/拒绝服务。
   * 不得为了消灭 `sparse_only` 占比而去调 `DENSE_WEIGHT/SPARSE_WEIGHT/...`（四项权重和必须 = 1.0，`config.py` 有校验；调它属于语义变更，不是故障处置）。

**回滚**：本条的正常处置是**宿主侧 + 只读 `.env`**，不产生需要回滚的变更。若改过 `deploy/.env`：改前 `cp .env .env.bak-$(date +%Y%m%d%H%M)`，回滚 = 覆盖回去 + 按 README §四-2 的约束（无在途流时、`docker compose stop --timeout 45 api`）重启才生效。若改过宿主 `OLLAMA_HOST`：还原为原绑定（**默认收紧是安全方向**）。

---

## 4. 验证恢复

| 判据 | 怎么看 | 位置 |
|---|---|---|
| 探针不再降级 | `curl -sS $BASE/healthz` → 200 且 `degraded_dependencies` **不含** `embedding`；且日志里**不再出现** `healthz_failed_probes` 的 `failed.embedding` | 聚合详情（**不要拿它做编排探针**，A.8.4）+ `docker compose logs api` |
| 硬依赖全程没动 | 整个处置期间 `curl -o /dev/null -w '%{http_code}' $BASE/healthz/ready` **始终 200** | readiness |
| 检索回到混合 | 新查询的 `meta.retrieval_mode` = `"hybrid"`，且本轮**没有** `degraded(embedding_unavailable)` 帧 | SSE 帧 / `audit_log` 的 `meta` |
| 降级率回落 | **主判据 = `rate(degraded_total{reason="embedding_unavailable",action_taken="sparse_only"}[15m])` 增速归零**（本族已接线，`/metrics` 上直接可读）。⚠️ **别用 `retrieval_mode_total` 做这条**：`observe_retrieval_mode()` 全仓**无调用点**，而标签有完整枚举域 ⇒ 注册表**导出恒 0 序列**（不是"序列缺席"）⇒ `0/0` 在 PromQL 里是**无数据**，看板上既不是红线也不是绿线 —— 只在 W2B 接线后当趋势复核。同样**别用** `query_outcome_total{outcome="degraded"}` 当分母（被降级请求的终止态只记 `refuse`/`clarify`，该位恒 0 ⇒ 系统性低估）。⇒ 帧侧/表侧的回落证据看上一行 `meta.retrieval_mode` 与 `audit_log`。缺口登记见 `deploy/observability/README.md` §三.4 |
| 首包没退化 | 一次真实 `/query` 的 `meta.latency_ms.linking` 与 `http_request_duration_seconds` P95 回到基线（G-6 ≤8s 口径） | §16.1/§16.5 |

**如实声明（不得报告成"已恢复原状"）**：降级期间跑的查询**检索质量确实下降了**（少了一路稠密）。这些轮次在 `meta` 与审计里都有 `sparse_only` 标记，若在降级窗口内产出评测/澄清率结论，必须标注（§18.4.1 对 R-19 口径污染的同一套纪律）。

---

## 5. 升级 / 联系（归属见 08 §4.1）

| 议题 | 找谁 |
|---|---|
| embedding 探针接线（`/healthz` 里 `embedding` 真值）、`deploy/**`、检索降级率的看板/告警 | **W7（本窗口）** |
| 稠密检索实现与降级（`app/retrieval/dense.py`、`fuse.py` 的权重再分配） | **W2B** |
| `retrieval_mode` / `DegradedReason` / `ActionTaken` 取值集 | **W0**（`app/core/enums.py`，改它走 08 §4.3 四步流程） |
| `meta.retrieval_mode` 进帧、`degraded` 事件发射 | **W4**（`app/graph/events.py`、`app/api/runner.py`） |
| 向量维度与索引 DDL、pgvector 物化 | **W1B**（migrations）+ **W2A**（语义包物化） |
| **不一致上呈**：① ~~`/healthz` payload 与 §A.8.4 不一致（`checks` 键用 `Dependency` 枚举值 + 顶层私增 `probe_detail`）~~ → **本轮已修**：键名按 `_AGGREGATE_CHECK_KEYS` 对齐 §A.8.4，`probe_detail` 移出响应体改落 WARN 日志。② `version` 代码 `"0.1.0"` vs 附录示例 `"1.0.0"`（示例值是否算契约，由架构定）。③ 附录 D §D.5 第 14 步给的 `docker compose exec api curl` 在 `python:3.13-slim` 镜像里**不可执行**（无 curl）→ 本文一律用 `python -c urllib`。④ §18.7 把"检索降级率 >5%"写成判据，但 §15.4 没有对应规则、且 `retrieval_mode_total` 无采集点 ⇒ RL-2 的指标侧出口**两头都缺** | **架构窗口**（②③属文档/环境侧，④属观测面）→ **待架构窗口分配编号** |
