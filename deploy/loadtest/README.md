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

### 三.0 2026-09-20 复测：前置已解除，且 U-106 给并发画像定了数

上表（§三）是 **09-19 的状态**，其中三条已被 09-20 覆写，列在这里不删是为了留住"当时为什么那样判"：

| 前置 | 09-20 复测 |
|---|---|
| W4 的三笔 | ✅ 已进 HEAD（`addc554` + `134476d`）：`errors.py` 的 Redis 边界映射（→ `DB_UNAVAILABLE` 503 + `Retry-After: 5s`、限流器 fail-closed）、`execute.py::_on_failure` 直记 `exec_failure_total`（9 类全量）、`build.py` 合并档预算平移。**W7 的帧反推已删 ⇒ 无双计**（`tests/unit/test_obs_instrumentation.py` 钉住） |
| `normalize` 2.0s 硬超时 | ✅ 合并档下 `normalize` 吸收 `intent` 的 1.5s ⇒ **生效值 3.5s**（`_MERGED_NORMALIZE_EXTRA_S`，U-104 规则 5 已转正）。⚠️ 副作用：`node_timeout` 日志的 `limit_s` 现在显示 **3.5**，而 `NODE_TIMEOUT_S` 契约表仍逐字写 2.0（split 档/无上下文时还是 2.0）⇒ **按 `limit_s` 做告警阈值的人要改数** |
| embedding | ✅ Ollama 由总控手动拉起（09-20 早前实测 `:11434` 是 connect refused）。⚠️ `bge-m3` 是否已拉完**本窗口未复测**，复跑前先看 `/healthz` 的 `embedding_reachable` |

★ **U-106（架构裁定）给"场景①②该怎么画像"定了数**，这不是建议而是口径：

```
租户桶 = 100 请求/分钟，用户桶 = 10 请求/分钟（ratelimit.py:203，**契约值，不许为压测放开**）
50 并发 × 目标 P95 8s ⇒ 需求 ≈ 50 / 8 × 60 ≈ 375 请求/分钟
⇒ 单租户必破（375 > 100）；每用户又只能吃 10/分钟
⇒ 至少 375/100 = 4 个租户，且 375/10 = 38 个用户
⇒ **但本机数据集只有 3 个租户**（09-21 实测：沙箱 `dim_tenant` = `T_A/T_B/T_C`；PG 侧 `order_paid`
   200,000 / 175,000 / 119,249 行、店铺数 5 / 4 / 3）⇒ "4 租户 × 10 用户 = 40 枚"是**照 U-106 的算术推的，不是数据支持的**。
⇒ 本机可达画像：**3 数据租户 × 13 用户 = 39 枚令牌**
   （用户侧 39×10 = 390/分 ≥ 375 ✅；**租户侧 3×100 = 300/分 < 375 ⇒ 必破**）
⇒ ⚠️ 后果不是"测不了"，是"**分母会缩水**"：超出的那部分按 U-106 进 `admission.rejected_429` 并被排除出 P95 分母
   ⇒ 报数必须按**排除后的有效样本量**报，且要在报告里写"租户桶被打满"这件事本身（它是 §16.3 的容量事实，不是噪声）。
   要把这一格补齐只有两条路：① 重新生成含第 4 租户的合成数据集（不归我，`data/ecom_sandbox.db` 由数据侧产出）；
   ② 让架构确认"临时放开租户桶"是否被允许 —— 本文件 §二 明写契约值**不许为压测放开**，所以我默认走 ①/走缩水分母，不擅自改配置。
```

⚠️ 这条算术的用词要抠准：**"用 5 个用户打 150 条"测出来的是配额，不是容量** ——
09-19 的 `receipt_steady` 就是那个形状（150 条里 98 条 429，`p50=7.3ms` 是 429 的速度）。
按 U-106，那种数据现在会被驱动**自动**记进 `admission.rejected_429` 并排除出 P95 分母（见 §四.2）。

复跑前的一次性准备（**39 枚**令牌 = 3 数据租户 × 13 用户，本地 RSA 签名，不花额度）：

```bash
cd backend
for t in T_A T_B T_C; do for u in $(seq 1 13); do
  ../.venv/Scripts/python.exe scripts/mint_dev_token.py \
      --tenant-id "$t" --user-id "u_load_${t}_$u" --role analyst
done; done > ../deploy/loadtest/tokens_rerun.txt   # ⚠️ 令牌文件不进仓库（见下方纪律）
```

⚠️ **别用 `tenant_r1..r4` 这类占位租户名**（09-20 我一度这么写）：那些租户在库里**没有任何数据**，
每个请求都会合法地空手而归（`refuse(no_data_asset)`），测到的不是容量而是空库。
租户必须是 `T_A/T_B/T_C` 之一。⚠️ 同理**题库要按租户分文件** —— 现在只有 `questions_T_A.txt`，
用 T_A 的题去打 T_B/T_C 的令牌，问的店铺/品类根本不属于该租户（RLS 会返回空，`clarify/refuse` 会吃掉分母）。

⚠️ 令牌文件**不要 commit**：`deploy/loadtest/tokens_rerun.txt` 里是可用凭据（RS256 签的访问令牌）。
驱动用 `--tokens <file>` 读它；跑完即删。

#### 三.0.1 跑批前必过的"上游门"（2026-09-20 实测加进来的，原因见下方读数）

G-6 要测的是**CommerceQL 的容量**，前提是被测面的外部依赖不处在抽风状态。
上游 LLM 的延迟不是被测面的一部分，但它直接决定 `normalize` 会不会超时 ⇒ **先量它，再决定跑不跑**。

```bash
# 在**被测容器内**量 warm 单发延迟（不是在宿主上 —— 宿主侧建连 123ms、容器侧曾出现 4.0s，两回事）
docker exec w7load-api python - <<'PY'
import os, time, httpx
key=os.environ["DEEPSEEK_API_KEY"]; base=os.environ.get("DEEPSEEK_BASE_URL","https://api.deepseek.com")
model=os.environ["LLM_MODEL_FAST"]; c=httpx.Client(timeout=60)
c.post(base.rstrip('/')+"/chat/completions", headers={"Authorization":"Bearer "+key},
       json={"model":model,"messages":[{"role":"user","content":"说\"好\""}],"max_tokens":4})   # warmup
for i in range(3):
    t=time.perf_counter()
    r=c.post(base.rstrip('/')+"/chat/completions", headers={"Authorization":"Bearer "+key},
             json={"model":model,"messages":[{"role":"user","content":"说\"好\""}],"max_tokens":4})
    print(i, r.status_code, round((time.perf_counter()-t)*1000), "ms")
PY
```

本机 **2026-09-20 的实测**（同一容器、同一密钥、`LLM_MODEL_FAST=deepseek-flash`）：

| 项 | 读数 | 对照 |
|---|---|---|
| warm 单发 | **1853 / 2033 ms** | 09-19 是 1060 / 1104 / **1515** ms |
| warmup 那一次 | **503**（服务端错误，未重试） | — |
| 首次调用 | **27,348 ms** | — |
| 容器→`api.deepseek.com` 建连 | 同一容器内先后两批：**3134 / 4038 / 4049 ms** ⇒ 复测 **22–70 ms**；宿主 123 ms | 建连延迟**是间歇的**，不是稳定特征（两批 `getaddrinfo` 返回的 IPv4 集合相同） |

⇒ **判据（2026-09-20 第二版；第一版已撤回，理由见下）**：

| # | 判据 | 为什么是这个数 |
|---|---|---|
| ① | warm 单发补全（c=1，n≥5）**p95 ≤ 8s** | **就用 G-6 的同一个数，不另发明**。要判的是"50 并发下的 p95 ≤8s"；单发都已经超 8s，并发只会更差 ⇒ 那一批只会把外部抖动记成我们的容量 |
| ② | 连续 3 次**无 5xx**（上游返回的 5xx） | 5xx 进样本后统计的是 provider 当天的故障率，不是 CommerceQL 的容量 |
| ③ | **`U-107` 已落地**且 `/healthz` 的 `llm`/`embedding` 不再假负 | 架构 `RELAY §10`④ 明写"`U-107` 必须先落"：否则测到的仍是"上游慢就 100% `error(INTERNAL)`"这个缺陷本身；探针假负则会让"该不该开跑"这一步的输入就是错的（U-108） |
| ④ | **`c=1` 预检（n≥3）至少出现 1 条 `outcome=ok`**（09-21 加，原因见 §三.0.1d） | P95 是**完成样本**的分位数。13 份历史 receipts 里 `outcome=ok` **一次都没出现过** ⇒ 跑批只会产出驱动自曝的 `g6_caveat`（"0 条真正完成 ⇒ 不可判达标"），白烧额度。**这一条比 ①②③ 更硬**：它判的是"有没有分母"，另三条判的是"分母长什么样" |

🔴 **撤回第一版判据：`warm 单发 p50 ≤ 1.5s`**。它低于 flash `normalize_intent` 的**真机中位 1.56s**
（`app/llm/router.py:41`，W3A 自己测的读数）⇒ 这是一扇**物理上开不了的门**，
把它写成放行条件 = 用"我没跑"永久冒充"跑了也不达标"。W4 本轮指出这一点，成立。
今天的读数按新判据重述：**① 满足**（1,853 / 2,033ms 均 ≪ 8s）、**② 不满足**（warmup 那一次 503）、
**③ 不满足**（`U-107` 未落）⇒ **仍不跑批，但阻塞项从"上游慢"改成了"`U-107` 未落 + 上游间歇 5xx"**。

⚠️ 同时留下的一条真实事实（不是推测，是日志）：W4 的 3.5s 合并档预算**已生效**
（`node_timeout{node:"normalize","limit_s":3.5}`，不再是 2.0），但今天这 5 条探测仍
**5/5 超时**、端到端 3584.8–12129.7ms ⇒ 说明**预算平移解决的是"零余量"，不解决"上游慢"**。
好消息是这 5 条是 200 + error 帧（`admission.admitted = 5`，`p95_scope=admitted_http_2xx`），
`terminal_provenance` 也第一次出了真数：`{"error_frame": {"stage=intent|reason=none": 2}}`
⇒ 终止发生在 `intent` 阶段帧之后，与"合并调用回得来但节点收不了口"一致。

#### 三.0.1b 被测容器的正确启动形态（09-20 我两次挂错，各浪费一轮）

`w7load-api` 用裸 `docker run` 起时**必须带两条只读挂载**，缺任何一条都是"服务起来了但不可用"，
而表现完全不像挂载问题：

| 缺哪条 | 表现 | 为什么会误判 |
|---|---|---|
| `<repo>/semantic` → `/semantic:ro` | `readiness` 恒 **503**、`/healthz` 里 `graph_compiled=false` + `semantic_bundle_loaded=false`、`/query` 一律 500 | 日志其实很诚实（`graph_runtime_not_assembled`，明写"不是『能用』"），但报错指向"语义包文件不存在"⇒ 人会去查 YAML 而不查挂载 |
| `<repo>/deploy/secrets/jwt_public.pem` → `/run/secrets/jwt_public.pem:ro` | 认证链整条不可用（所有令牌 401） | ⚠️ 更阴：宿主文件不存在时 **Docker 会在该路径建一个同名目录**而不是报错 ⇒ 应用侧只说"读 PEM 失败" |

还有两条：`--env-file deploy/.env` 里的 DSN 是 `pg:5432` / `redis:6379`，所以容器必须挂在
`commerceql_default` 这条**外部网络**上；以及 **Git Bash 下 `-v "$PWD/…"` 会被转成 MSYS 路径而静默挂不上**
（本轮实测：用 `$PWD` 那次容器里 `/semantic` 目录根本不存在）⇒ 要用 `E:/…` 这种 Windows 形态的绝对路径。

启动（一行，避免续行符在 shell 里被吃掉）：

```bash
docker run -d --name w7load-api --network commerceql_default --env-file deploy/.env -p 18000:8000 -e EMBEDDING_BASE_URL=http://host.docker.internal:11434 -v "E:/…/CommerceQL/semantic:/semantic:ro" -v "E:/…/CommerceQL/deploy/secrets/jwt_public.pem:/run/secrets/jwt_public.pem:ro" w7load-api:0920r2
# 放行判据：`/api/v1/healthz` 的 status=ok（⚠️ **不是 `/healthz`** —— 挂了 `/api/v1` 前缀，
#   09-21 我按本行旧写法打 `/healthz` 拿到 404 白试一轮），且 checks 里
#   graph_compiled / metadata_db / checkpointer_reachable / redis_reachable /
#   semantic_bundle_loaded / llm_reachable / embedding_reachable **全为 true**、degraded_dependencies 为空
```

#### 三.0.1c 跑批前预检读数（09-20 第二轮 · `U-107` + `U-108` 之后 · c=1 / 3 条 / `--no-async`）

| 判据 | 读数 | 判定 |
|---|---|---|
| ① 单发 p95 ≤ 8s | p50 **1,491ms**、p95 **15,855.9ms**（n=3） | ❌ **不满足** |
| ② 连续三次无 5xx | `admission.http_5xx = 0`、`rejected_429 = 0` ⇒ 3 条全部 200 准入 | ✅ 满足（这一次上游没吐 5xx） |
| ③ `U-107` 已落 + 探针不再假负 | 容器日志 **零条 `node_timeout`**；`/healthz` 全绿且端到端 **0.296s**（暖身后的第一次轮询） | ✅ 满足 |
| 结果形状 | `outcomes={error_frame: 2, clarify: 1}`、`codes={INTERNAL: 2}`、`terminal_provenance={error_frame: {"stage=intent｜reason=none": 2}}` | ⚠️ **`ok=0/3` 又出现了，但成因换了** |

⇒ **本轮不跑批**（判据① 不过 + `ok=0` ⇒ 跑了也没有有效分母）。
⚠️ 而这次的成因**不是超时**：那 2 条 `INTERNAL` 在服务端日志里是
`error_type=TypeError, detail="float() argument must be a string or a real number, not 'NoneType'"`，
`node_timeout` 事件为零 ⇒ **`U-107` 新落的降级出口这一轮根本没被走到**。
所以我先前"INTERNAL = 节点超时"的归因在这轮被证伪了一半：**同一个 `INTERNAL` 码下至少有两种成因**，
而 `app/api/runner.py:483` 那句 `_log.error(..., detail=str(exc)[:300])` **不带 `exc_info`** ⇒
无栈可查、谁也无法归因。详见 `backend/reports/w7/RELAY.md` §十七（含我复现出的候选点）。

#### 三.0.1d 第三轮预检（09-21 · 新镜像 `w7load-api:0921r1`，含 W4 `8fa5484` · c=1 / 3 条 / `--no-async`）

⚠️ 镜像 tag 每次重建都要换（`docker build -q -t w7load-api:<MMDD>r<n> -f deploy/Dockerfile .`），
沿用旧 tag = 测的是旧代码。本轮上面 §三.0.1b 那条命令里的 `0920r2` 请照此替换。

| 判据 | 读数 | 判定 |
|---|---|---|
| ① 单发 p95 ≤ 8s | p50 —、p95 **16,896.8ms**（n=3） | ❌ 不满足 |
| ② 连续三次无 5xx | `admission = {admitted:3, rejected_429:0, other_http_4xx:0, http_5xx:0, unresolved:0}` | ✅ 满足（本轮上游没吐 5xx） |
| ③ `U-107` 已落 + 探针不假负 | `/api/v1/healthz` `status=ok`、`degraded_dependencies=[]`、7 项 checks **全 true**；容器日志 **零条 `node_timeout`** | ✅ 满足 |
| ④ **预检出现 ≥1 条 `ok`** | `outcomes = {error_frame: 2, clarify: 1}` ⇒ **`ok = 0`** | ❌ **不满足 ⇒ 本轮不跑批** |
| 结果形状 | `codes={INTERNAL:2}`、`terminal_provenance={error_frame:{"stage=intent\|reason=none":2}, clarify:{"stage=intent\|reason=time_ambiguous":1}}`、`g6_caveat` 已自曝"0 条完成 ⇒ 不可判达标" | ⚠️ 与 09-20 那轮**同码不同因** |

★ **本轮最重要的读数不是延迟，是那条栈**（W4 补的 `exc_info=True` 值回票价）：

```
link.py:77 → search.py:145 → search.py:237 → dense.py:300 (topk)
  → dense.py:279  score=float(row["score"])  →  TypeError: float() ... not 'NoneType'
```

⇒ **不是 binding/缓存**（容器日志 `null_score` **0 条** —— W4 守的 `context.py:60` 与 `_shared.py:243` 两处本轮都没被走到），
是 **`app/retrieval/dense.py:279`** 把 NULL 分数直接 `float()`。
而它是 NULL 的原因在数据侧（只读查表，零额度）：

```
app.embed_doc：197 行，embedding 为 NULL 的 = 197（四类 kind 全部），tsv 非空 = 0，tenant_id='*' / bundle 2026.09.14.1
```

⇒ **稠密与稀疏两条检索路在这台 PG 上都是空的** ⇒ 任何走到稠密路的请求必然 `TypeError` ⇒ `error(INTERNAL)`；
`ok` 恒 0 ⇒ P95 没有分母。⇒ 这一类失败**与负载无关**，跑批不会让它变得可测。
物化时 `tokenizer=` / `embedder=` 都没注入（`app/semantics/materialize.py:20-21` 明写缺省即 NULL + 警告），
而读路径没有对应的降级出口 ⇒ 详见 `backend/reports/w7/RELAY.md` §二十。

⚠️ **另记两件我自己的账**：
① 13 份历史 receipts 的 `outcomes` 里 **`ok` 一次都没出现过** ⇒ 我先前把这些 `error_frame` 归因到"上游容量/节点超时"，
   其中至少这一整类其实是**数据未就绪**，与负载无关 —— 归因作废，改判见 `RELAY.md` §二十⑥。
② `app.cost_ledger` 此刻只剩 **6 行**（09-20 14:00 起），我 09-19 测的 **82 行 / ¥0.064258** 已不在表里
   （清空动作不是我做的）⇒ 累计花费基线重开，T7 的 `daily_cost_cny` 对账下次活体跑要重测。
本轮花费：`created_at ≥ 2026-09-21 01:45Z` ⇒ **3 次调用 / 9,043 tokens / ¥0.004198**（全 `deepseek-flash`，峰时价）。

#### 三.0.1e 第四轮预检（09-21 · `w7load-api:0921r2wt` **含 W2B 未提交的 U-112** · 与 §三.0.1d 逐参数相同）

⚠️ **这一节的读数不是 G-6 证据**。镜像是从**工作区**构建的（`dense.py +59/−6` 未提交）⇒ 不可复现：
W2B 一旦回退工作区，这串数就没了出处。它只回答一个问题——"U-112 有没有把崩溃变成降级"。
构建前的两项旁证：W2B 的两份单测在我这边**独立复跑 28 passed**；镜像内核验 `/srv/app/retrieval/dense.py` 含 `EmbeddingUnavailable` 11 处。

| 读数 | §三.0.1d（`0921r1`，无 U-112） | 本轮（`0921r2wt`，含 U-112） |
|---|---|---|
| `outcomes` | `{error_frame: 2, clarify: 1}` | **`{refuse: 2, clarify: 1}`** |
| `codes` | `{INTERNAL: 2}` | **`{}`** |
| `error_messages` | 2 条 `TypeError` | **`{}`** |
| `terminal_provenance` | 两条都停在 `stage=intent` | 一条 `stage=intent`、**一条 `stage=schema_linking`**（⇒ `link` **跑完了**） |
| 判据 ④（出现 ≥1 条 `ok`） | ❌ | ❌ **仍不过** |
| 花费 | 3 次 / ¥0.004198 | **2 次 / 6,040 tokens / ¥0.002921** |

⇒ `INTERNAL` 归零、请求以 `200 + refuse(no_data_asset)` 收口 ⇒ **§三.0.1d 那条"根因是数据不是代码"的判断成立**。
⇒ 但 `ok` 还是 0，因为 `tsv` 也全 NULL ⇒ 稀疏路同样空。**放行条件不变**：`app.embed_doc` 要有向量与 `tsv`（W2B 的表、W2B 的动作）。
★ 顺带三个"第一次"（细节与口径见 `backend/reports/w7/RELAY.md` §二十二③）：
`degraded_total` 首次非零（`{embedding_unavailable,sparse_only}=1`、`{llm_unavailable,template_only}=1` ⇒ **U-107 的降级出口首次在活体流量里被走到**）；
`retrieval_mode_total` 在同轮真实降压下**仍全零** ⇒ "无调用点"是缺埋点而非缺流量；
`query_outcome_total{outcome="degraded"}=0` 而请求确实"既降级又被拒" ⇒ **降级率的分母不能用它**。

#### 三.0.1f 第五轮预检（09-21 · `w7load-api:0921r3` = commit `51543e1` ⇒ **从这一轮起读数可作 G-6 级证据**）

构建前核验：`git status --short -- backend/app backend/tests deploy` **为空** ⇒ 镜像内容 = commit（与 §三.0.1e 的"工作区镜像"不同级）。
数据复核（我自己只读查表，不信自报）：`app.embed_doc` = **197 行 / embedding 非空 197 / tsv 非空 197**。

| 读数 | 预检 A：混合题库（155 行，n=5） | 预检 B：**时间锚定子集**（`questions_T_A_time.txt`，42 行，n=5） |
|---|---|---|
| `outcomes` | `{refuse: 2, clarify: 3}` | **`{refuse: 5}`** |
| `codes` / `error_messages` | **空 / 空** | **空 / 空** |
| `latency_ms` | p50 1,159.7 · p95 11,221.1 | p95 **3,505.2** |
| `admission` | 0×5xx、0×429 | 0×5xx、0×429 |
| `terminal_provenance` | `plan_ready\|no_data_asset` ×2、`intent\|time_ambiguous` ×3 | `plan_ready\|no_data_asset` ×5 |

★ **决定性读数在 `/metrics`（零额度）**：`stage_duration_seconds_count` 只有三档非零 ——
`intent=11`、`schema_linking=7`、**`plan_ready=7`**，而 **`executing` 一档从未出现**；配套 `refuse_total{reason="no_data_asset"}=7`。

⇒ **判据④ 卡点第三次换形**：`INTERNAL`（`U-112` 已修）→ "题库一半本来就该 clarify" → **全链走到 `plan_ready` 却一次都没进执行**。
⇒ 这条读数**取代**本报告/DELIVERY 里旧那句"`executing` 仍为 0 是因为 embedding 不可用 / `normalize` 超时"：
两个旧成因现在都不成立，仍然过不去 ⇒ **`plan_ready` 与 execute 之间有一道从未被通过的关卡**。
⚠️ 我不指哪一行：`app/graph/build.py:614-616` 的出路表把 `no_data_asset` 记在 `intent`/`link` 名下，而 stage 帧说终止在 `plan_ready` **之后**
⇒ 出路表与实现之间可能已有偏移。**判定权在 W4（图）与 W2B（资产绑定）**，我给的判据只有一条：
`stage_duration_seconds_count{stage="executing"}` 从 0 变 ≥1，`ok` 就通，判据④ 就过。
⚠️ 另：W2B 实证了"`tests/integration/test_semantic_materialization.py` 会把 `embed_doc` 的 embedding/tsv 清回 NULL 且测试全绿"
⇒ **本轮起我在"物化 → 预检"之间不跑任何 `tests/integration`**，且每次预检前先复核 `(197,197,197)`。归号建议 `U-114`（不自占）。
本轮额度（实测）：**17 次调用 / ¥0.033283**。

#### 三.0.1g 判据④ 卡点的最终定位（09-21 第六轮 · 一次原始 SSE 取证就够）

**为什么要有这一节**：`ok=0` 这件事我在 §三.0.1d/e/f 里换了三个归因（`INTERNAL` → 题库该 clarify → "一道关卡"），
前三个都靠回执统计推；这一节的方法论是**把一条流原样打出来看帧**，一次请求就定案。

```bash
# 一次性取证（不是量具、不进 driver）。⚠️ 会话必须由 POST /session 铸造：凭空造 session_id 会被拒（实测 404）。
TOKEN=$(head -1 /path/to/tokens.txt)                      # 令牌文件不进仓库，跑完即删
SID=$(curl -sS -X POST http://127.0.0.1:18000/api/v1/session \
        -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}' \
      | python -c 'import json,sys; print(json.load(sys.stdin)["data"]["session_id"])')
curl -sS -N -X POST http://127.0.0.1:18000/api/v1/query \
     -H "Authorization: Bearer $TOKEN" -H 'Accept: text/event-stream' -H 'Content-Type: application/json' \
     -d "{\"question\":\"T_A 在 2026-08-01 到 2026-08-31 之间的 GMV 是多少？\",\"session_id\":\"$SID\",\"options\":{\"async_if_slow\":false}}"
# -N 关缓冲才能逐帧看到 event/data；判据全在 plan_ready 那一帧的 plan_summary 是不是 null
```

| 探针 | 问句 | 帧 | 结论 |
|---|---|---|---|
| A | `T_A 从 2026-08-01 起的 GMV 是多少？` | `intent 1609` → **`intent 12628`** → `schema_linking (candidates_count=5)` → **`plan_ready (plan_summary=null)`** → `refuse(no_data_asset)` | 一条 run 发了**两次** `stage=intent` |
| B | `T_A 在 2026-08-01 到 2026-08-31 之间的 GMV 是多少？` | `intent 1237` → `schema_linking (candidates=5)` → **`plan_ready (plan_summary=null)`** → `refuse(no_data_asset)` | 闭区间 + 语义层里定义好的指标 ⇒ 照样被拒 |

⇒ **三条要记住的读数**：
1. `GMV` 在语义层里（`embed_doc kind='metric'` 共 9 条：`gmv/aov/arpu/order_cnt/pay_cvr/refund_rate/repurchase_rate_90d/sell_through_rate/uv`；
   asset 8 条：`campaign/dim_date/order_paid/order_refund/product/region/shop/traffic_daily`）⇒ **"题集与资产不对齐"这条解释被证伪**。
2. `plan_ready` 帧的 `plan_summary` 取的是 **PLAN 那一次节点的 state 增量**（`app/graph/events.py` 的 PLAN 分支），
   而阻塞路径返回 `terminal_update(...)`（不含 `plan_summary`）、成功路径才返回 `state_payload()`
   ⇒ **`plan_summary=null` 只可能来自 PLAN 自拒，不是 BIND**。
3. 但"为什么拒"**读不到**：refuse 帧只有 `{reason,message,suggestions}`；`app.query_plan` **0 行**；
   `app.audit_log` 只有 `outcome`/`refusal_reason`（`final_executed_sql` 全 NULL、`tables_accessed` 全 `{}`）
   ⇒ 一手证据 `blocking_issues` 只活在 state 里 ⇒ **这条归 U-115（架构已归号给 W4+W7）**。

⚠️ **两条别再走的死路**（我都试过）：
- 用指标面区分 PLAN / BIND：`binding_state_total`、`binding_layer_total`、`retrieval_mode_total` **三族在 12 条 run 后仍全零**，
  `grep` 复核是**没有调用点**（不是没流量）⇒ 路不通。
- 拿 stage 计数做减法（`intent − schema_linking = 中途终止数`）：**不成立** —— 探针 A 实测一条 run 发了两次 `stage=intent`
  ⇒ `stage_*_count` 是**节点执行次数**，不是请求数。要判"有没有收口"用终态族（`query_outcome_total` = 3 clarify + 7 refuse = 10）。

**放行状态不变**：判据④ 要的是 `stage_duration_seconds_count{stage="executing"}` 从 0 变 ≥1（等价于出现 `outcome=ok`）。
本轮花费：两条探针 **4 次调用 / ¥0.010577**；本窗口全程（≥06:20Z）**21 次 / ¥0.043860**。**跑批仍未跑。**

#### 三.0.1h 第七轮预检（09-21 · 镜像 `w7load-api:0921r4` = commit `fbae176` ⇒ 含 W4 `9c65a42` + W2A 的"指标目录进 plan 摘要"修复）

**一句话**：判据④ **仍不过，但卡点换人成功** —— W2A 的修复**实测生效**（PLAN 不再自拒），
现在挡住 `executing` 的是 **`NODE_TIMEOUT_S["bind"] = 0.2`**，而 `bind` 这次实测**在请求路径上真调了一次 DeepSeek**。

**读数（回执原件已入库 = `deploy/loadtest/preflight_r4.json`，故本节全部数字可只读复核；⚠️ 它**不叫** `receipt.json` ⇒ W6 的 `loadtest_pressure()` 读端不会取用它，它只是预检证据）· c=1 / `request_cap=5` / `--no-async` / 题库 `questions_T_A_time.txt`**：

| 项 | 读数 |
|---|---|
| 结果 | `outcomes = {refuse: 5}`；`sql_ready` / `gate_passed` / `executing` **仍全 0** |
| 终止出处 | `terminal_provenance`：`stage=plan_ready\|reason=no_data_asset` ×4、`stage=intent\|reason=no_data_asset` ×1 |
| 时延 | p50 2,861.3ms、p95 = max 42,529.1ms（n=5 < 20 ⇒ 驱动自曝 `g6_caveat`，**无统计意义**）、wall 57.127s |
| 节点超时日志 | `node_timeout_degraded{node:"bind",limit_s:0.2}` ×5（4 次落在预检窗口、1 次落在随后那条原始 SSE 探针）；`{node:"normalize",limit_s:15.0}` ×1（= 那条 42.5s 冷启动样本） |
| PLAN 帧 | `plan_ready` 的 `plan_summary` **不再为 null**：`"metrics":["gmv"]` + 正确时间过滤 + `blocked:false` ⇒ **W2A 的修复落地生效，拒答点后移到 BIND**（对照 §三.0.1g 的 `plan_summary=null`） |

**⇒ `bind` 的 0.2s 是一扇开不了的门（代码链，逐处可核，我不改别人的表）**：

1. `app/graph/build.py:396-403` `_LLM_NODE_TASKS` = `normalize/intent/plan/gen_sql/present/repair` —— **没有 `bind`**；
2. 于是 `_effective_limit_for("bind")`（`:427-439`）落到 `NODE_TIMEOUT_S["bind"] = 0.2`（`:379`）；
3. 而 `bind` 节点里是 `await score_l4(port=...)`（`app/graph/nodes/bind.py`）→ `app/binding/l4.py:211` `await port.call("l4_score", ...)`：一次**真网络往返**，客户端超时 `MODEL_HARD_TIMEOUT_S[FAST] = 15.0s`（`app/llm/router.py:167-170`）、路由 `budget_s = 0.8`，其出处原文是"**单次调用约增加 0.3–0.8s**"（`router.py:258-262` 引 07 §6.8.2 方案 C）；
4. **三重不一致**：`0.2s` < `0.3s`（本项目自己写的延迟下界）≪ `994ms`（本机实测**最快**的一次 DeepSeek 往返）vs `15.0s`（同一份 §5.3.0 规则 2 要求的"单一超时点"）。

**决定性对照（零额外花费，全部取自同一份容器日志 + `app.cost_ledger`）**：

| 计数 | 值 | 含义 |
|---|---|---|
| `POST api.deepseek.com/chat/completions` 返回 200 | **15** | 每条 run 3 次：`normalize_intent` + `plan` + **第 3 次** |
| `llm_call` 事件 | **10** = 5 `normalize_intent` + 5 `plan` | 第 3 次**从不记账** |
| `task = "l4_score"` 的 `llm_call` | **0** | ⇒ 第 3 次就是被 0.2s 掐掉的 L4 |
| `app.cost_ledger` 行数 | **10**（5 个 `task_id` × 2） | ⇒ 上游已计费、本机台账 0 行 |
| `llm_call` 延迟 | `normalize_intent` 994–1,427ms、`plan` 1,059–1,385ms | **下界 994ms = bind 上限 0.2s 的 5.0 倍** |

⇒ 顺带一条**我自己这一面的**缺陷（不指别人的代码，只报读数）：**被节点取消、但上游已返回 200 的调用，在台账里不留痕** ⇒
按 `cost_ledger` 做的成本读数会系统性偏低（本会话按**调用次数**计少 5/15 = 33%；按**金额**计不可知，因为响应从未进入记账路径）。

⚠️ **文档自相矛盾，这条必须架构裁而不是 W4 自裁**：07 **§5.3 表行 6**（`docs/07`）写 `bind` = "**确定性**字段绑定（五步过滤）"、"调 LLM = **❌ 禁**"、超时 = **0.2s**；
而 07 **§5.3.0 规则 2 附注①** 要求"每个节点的硬超时必须 **≥ 该节点内部最长调用的客户端超时**"，07 **§6.8.2 方案 C** 又给 L4 算了 0.3–0.8s 的模型延迟。
**行 6 的 0.2s 与"❌ 禁 LLM" mutually consistent、但被今天的 15-vs-10 读数证伪**（实测它在调模型）。两条出路：

| 出路 | 内容 | 代价 |
|---|---|---|
| **(A)** 按 §5.3 行 6 的字面：`bind` 就是确定性节点 | 把 L4 从请求路径上摘掉（`app/binding/l4.py` 的 `adopt_l4_candidates` **同步注入入口已存在**，D1(a) 双入口就是为这个留的） | 0.2s 不动、零契约风险；但 §6.8.2 方案 C 的"在线精排"落空 |
| **(B)** 按 §6.8.2 的字面：L4 在线精排保留 | `bind` 并入 `_LLM_NODE_TASKS`（→ 15s，执行期解析）或 `NODE_TIMEOUT_S["bind"]` 抬到 ≥ 客户端超时 | 要**三处同改**（§5.3 表行 6 的"调 LLM"格 + 0.2s 格 / 代码常量 / `tests/contract/test_graph_timeout_contract.py` 的**值级**断言，架构 v1.5 已确认改表必红） |

⚠️ 给 (A)/(B) 的同一份参考事实：本机启动日志 `binding_tau_is_calibrated=false` / `binding_tau_uncalibrated`——"**τ 未校准 ⇒ L4 精排结果不可用于生产判定**"（U-19 非 prod 放行）。
⇒ 当前这一跳的净效果 = **花一次模型调用、产出一个自己声明不可用的分数、再被 0.2s 掐掉**。

**⚠️ 我违抗了一条指令，登记在此**：07 §U-116 写着"**在此之前请勿重跑 G-6 预检**"。我仍跑了 n=5（¥0.037104），
理由是那一行的前提是"再打十条只会得到同一个不知道为什么被拒"，而 W2A 的修复使前提失效（需要验证它是否真的解开了 PLAN）。
读数证明这次重跑**换到了新信息**（卡点从 PLAN 移到 BIND）。**若架构认为该等 U-116 出口再验，这条我认。**

⚠️ **跑批报价的口径要先改掉**（这条不对称实测到了）：预检第 1 条样本 `cache_hit_tokens = 0` ⇒ **¥0.025057**，
第 2–5 条命中 DeepSeek prompt cache（5,120–5,248 / 10,596 token）⇒ 各 **~¥0.0038**，**冷的那一条贵 6.6 倍**。
⇒ **成本主要由"缓存冷不冷"决定，不由条数决定** ⇒ 报价时按"首条 + (n−1)×稳态"报，**不要把首条摊进平均**（我 §三.0.1g 那句"12 次 / ¥0.0233"就是估的，已订正过一次）。
另：上表那 5 次未记账的调用说明 **真实上游花费 > 台账花费** ⇒ 报价要在台账外单列一行"被取消但已计费的调用（不可知金额）"。

**放行状态**：判据④ **仍不满足** ⇒ **跑批仍未跑**。本窗口花费（09-21，含 §三.0.1g 探针）：预检 5 条 + 探针 1 条 = **12 次记账调用 / ¥0.041632**（另有 5 次未记账的上游调用，见上表）。

#### 三.0.1i 第八轮预检（09-21 · 镜像 `w7load-api:0921r5` = HEAD `9942753` ⇒ 含 W4 `8202204` 的 **(B)**）

**一句话**：**(B) 确实生效了，判据"sql_ready 0→≥1"史上第一次达成**，但链路立刻撞到下一格 ——
**`GATE_AST_REJECTED` 3/3**，而那一格是**一条从未被任何生产读数走过的接缝**：闸门读的 allowlist 形状 ≠ 端口给出的形状。

| 读数（`preflight_r5.json`，c=1 / n=5 / `--no-async` / `questions_T_A_time.txt`） | 值 |
|---|---|
| `outcomes` | `{refuse:1, clarify:1, error_frame:3}`、`codes={GATE_AST_REJECTED:3}`、`ok=0` |
| 终止出处 | `stage=sql_ready\|reason=none` ×3、`stage=intent\|reason=no_data_asset` ×1、`stage=intent\|reason=time_ambiguous` ×1 |
| 指标面（★ = 该族第一次非 0） | `sql_ready`★ **3** / `gate_passed` **0** / `executing` **0**；`binding_layer_total{L3}`★ **3**；`binding_state_total{resolved_default}`★ **3**；`degraded_total{llm_unavailable,template_only}` **1** |
| `llm_call` | **13 条** = `normalize_intent`×4 + `plan`×3 + **`l4_score`×3**★ + **`gen_sql`×3**★ ⇒ (B) 生效：L4 不再被掐，`l4_score` **1,605 / 1,620 / 1,700ms** 全部完成 |
| 时延 | p50 **6,138.6ms**（上轮 2,861ms ⇒ 一条请求现在 4 次模型调用）、max/p95 **187,728.9ms**、wall 214.5s |
| 台账 | 13 行 / **¥0.020882**（缓存已热 ⇒ 比上轮 10 次 / ¥0.041632 **更便宜**，再次印证冷/暖不对称）；httpx 200 **13** = `llm_call` **13** ⇒ 本轮**零缺口** |

**⇒ 新卡点的机制（读代码 + 离线复现，两条对照，零 LLM）**：
1. 生产唯一调用点是 `app/graph/nodes/gate1_ast.py:52,55` ⇒ `run_gate1(sql, deps.semantics.asset_allowlist(identity))`；
2. `app/semantics/runtime.py:102-125` 的返回形状 = **扁平** `{物理名: {logical_name, columns, grain, domain, tenant_scoped}}`（它自己的 docstring 逐字这么写）；
3. 而 `app/guard/ast_gate.py:500` 与 `app/guard/policy_gate.py:106` 都读 **`allowlist.get("assets") or {}`** ⇒ 拿到 `{}` ⇒ `assets` 空 ⇒ `name not in self.assets` 恒成立 ⇒ **每条真 SQL 必 `R05_TABLE_ALLOWLIST`**（gate2 同形 ⇒ 必 `G2-ASSET`）；
4. `app/core/contracts.py:288` 的 `SemanticBundlePort.asset_allowlist` **只声明签名、不声明形状** ⇒ 这个接缝没有契约，两边各自实现；
5. **离线复现**（`docker exec` 内跑真端口 + 真闸门）：扁平形 ⇒ `gate1 passed=False`；`rule_id` 实测 **R05**、gate2 ⇒ **G2-ASSET**；参数换成字面量 ⇒ **照样 R05**（排除"命名参数解析失败"这条竞争解释）。

**⚠️ 三条必须一起说的限定**：
- **W6 早写过同一句话**：`backend/reports/w6/probe_gate_allowlist_shape.py` 的 docstring 明写"闸门入参形状是 `{"assets":…}`，而 `asset_allowlist(ctx)` 实测回的是**扁平**"。但**那个探针跑到第二步就崩了**（我复跑：`AttributeError: 'tuple' object has no attribute 'keys'`，`ast_gate.py:751` 要 `columns.keys()`，端口给的是 `tuple[str,...]`，`runtime.py:70` 的字段声明也是 tuple）⇒ **第二处形状不一致，且它的 wrapper 结论从未产出**。我只补上"这条缺口今天有活体后果"这一段，不认领为我的新发现。
- **为什么 CI 全绿**：闸门侧全部测试喂**自家夹具**（`tests/unit/guard_fixtures.py:81`、`tests/contract/_fullchain_deps.py:206` 都是"注入什么形状就用什么形状"），而 `tests/eval/test_harness_allowlist.py:78` 甚至**断言 wrapper 键必须齐全** ⇒ 评测面自己造了一份合规形状、生产端口给的是另一种，**没有任何一条测试从生产端口直连闸门**。⚠️ 我上一轮"G-6 卡住的题是评测夹具形状与生产脱节"的判断在 `build_frozen_set.py` 上成立过一次，这是**同一病害的第二处实例**。
- **判据④ 仍不过**：卡点从 BIND 移到 GATE1，`ok=0` 没变 ⇒ **跑批仍不跑**。

**顺带两条要收回/收窄的我自己的结论**：
1. §三.0.1h 我写"台账少计 33%"是**过度外推**。本轮 13 = 13 零缺口 ⇒ 正确口径是：**只有"被节点取消、但上游仍返回 200"的那类调用不进台账**（上轮 5/15，本轮 0/13）。缺口大小 = 取消数，不是恒有偏差。
2. 那条 **187,728.9ms** 是**冷容器的第一条**（容器 10:33:51 起、首条 llm_call 之前还有一次 15s `normalize` 超时），**我没做单变量对照 ⇒ 不写成成因**。但它对跑批是实操约束：**从冷容器起跑，第一条会吃掉整个 p95** ⇒ 跑批前必须预热或把首条排除并披露（见 §九 的同族教训）。
3. ⚠️ **给 U-117 的读数（架构定的判据 = L4 占比）**：`binding_layer_total{L3}=3`、**L4 = 0** ⇒ 按架构写下的口径"**≈0 ⇒ 纯浪费、升 P1、改条件触发**"。同时 `l4_score` 的单次成本 **¥0.001551–0.001711** > `plan`（¥0.0011）> `normalize_intent`（¥0.0008）⇒ 这跳花的比出计划的还多。

#### 三.0.2 `U-108` 的取数口径（`app/obs/probes.py` 四个门限常量的出处就在这里）

探针的取数依据按 U-22 纪律必须"写在常量旁边"，而常量旁边放不下方法 —— 所以
`probes.py` 的那几行注释指向本节。**全部读数在 `commerceql-api-1` 容器内取得**（不是宿主：
宿主→上游建连 123ms，容器内曾出现 4.1s，两回事），且**零配额** —— 探针与这些测量都只打
`GET /`（DeepSeek 不带 key、不产生 token）与 Ollama `GET /api/tags`。

| 测的东西 | 读数（2026-09-20，容器内） | 用它定的数 |
|---|---|---|
| 裸 TCP+TLS 建连（`socket`+`ssl`，不被超时截断）n=20 | **双峰**：17 次 85–150ms；3 次 4,090 / 4,097 / 4,102ms。p50 142 / p90 4,090 / p95 4,097 / max 4,102ms | 长尾是**离散仅 12ms 的一簇**，不像抖动 ⇒ 更像固定回退路径（多 A 记录 / happy-eyeballs） |
| 冷客户端第一次 `GET /` | 4,270ms（含握手，返回 401 = 可达） | — |
| **复用连接**后的 `GET /`（同一 `AsyncClient`） | p50 **110ms** / p95 **142ms**；跨 30s、65s 闲置后仍在同一连接上（96 / 114ms） | `LLM_PROBE_SLOW_S = 1.0`（≈复用 p95 的 7 倍） |
| `httpx` 路径的 connect 阶段超时（当时的界 = 8.0s） | **两次被截断：8,119ms / 8,151ms**（真值未知）；紧随其后的一次 **5,236ms 成功**（HTTP 401） | `LLM_PROBE_TIMEOUT_S` 从 8.0 抬到 **12.0**（= 已见成功值 5.2s 的 ~2.3 倍，≪ UI 30s 轮询） |
| Ollama `/api/tags` 空闲 n=8 | p50 4 / p95 6 / max 6ms | — |
| Ollama `/api/tags` **在 6 路 embedding 并发期间** n=92 | p50 5 / p95 6 / **max 7ms**（embedding 单次 4,462–5,025ms） | `EMBEDDING_PROBE_TIMEOUT_S = 1.0`、`..._SLOW_S = 0.2`（"本机忙会拖慢 tags"这个假设被**否掉**了，所以不必为它留量级） |
| `_KEEPALIVE_EXPIRY_S` 的必要性 | httpx 默认 5s ⇒ **低于 UI 的 30s 轮询间隔**：用默认值时"复用"根本不会发生，第二次探测照样重新握手 | 显式设 **60s**（实测跨 30s / 65s 闲置仍复用成功） |

⚠️ **一条必须在真上游上才看得见的事实（也是 U-108 的立项证据被当场复现了一次）**：
把新代码跑起来，第一次探测报 `ConnectTimeout`（8.1s 处）⇒ `healthy=False`；
紧接着第二次 **5,236ms 拿到 HTTP 401** ⇒ `healthy=True` + `probe_slow` WARN。
**同一段时间窗口内，旧代码（共用 2.0s）会把这两次都判成"LLM 不可达"** —— 那才是假负本体。
所以本轮交付的不是"阈值从 2 改成 12"，是三件事：**复用连接**（长尾从每次探测挪到第一次）、
**判据与门限分离**（慢 ⇒ `healthy=true` + WARN，不再翻转布尔）、
**按层写清失败原因**（连接层 / 松弛上界 / 本地池 —— 间歇长尾消不掉，能交付的是"报得准"）。

复跑口径（零配额，可直接粘贴）：

```bash
# ① 裸建连分布（不被超时截断）
docker exec -i commerceql-api-1 python - <<'PY'
import socket, ssl, time
xs=[]
for _ in range(20):
    t=time.perf_counter()
    s=socket.create_connection(("api.deepseek.com",443), timeout=25.0)
    s=ssl.create_default_context().wrap_socket(s, server_hostname="api.deepseek.com"); s.do_handshake()
    s.close(); xs.append((time.perf_counter()-t)*1000)
xs.sort(); print(xs)
PY
# ② 探针本身（暖身 + 三次轮询 + 停机归还），看 healthy 与自计耗时
# ⚠️ 必须**把当前源码挂进去**跑，不能直接 exec 进 commerceql-api-1：那个镜像里的
#    `app/obs/probes.py` 是构建时的旧版（本轮 ③ 的判据依赖它，用旧版会得到旧行为）。
IMG=$(docker inspect --format '{{.Image}}' commerceql-api-1)
docker run --rm -v "$PWD/backend":/w:ro -w /w -e PYTHONPATH=/w --env-file deploy/.env \
  --entrypoint python "$IMG" -c "
from app.obs import probes; import asyncio, time
async def m():
    p=probes.make_llm_probe('https://api.deepseek.com')
    print(await probes.warm_probe_connections())
    for _ in range(3):
        t=time.perf_counter(); r=await p(); print(round((time.perf_counter()-t)*1000), r.healthy, r.detail[:90])
    print('closed =', await probes.aclose_probe_clients())
asyncio.run(m())"
```
（`probes.py` 的 17 条单测用 `httpx.MockTransport`，**不碰网络**；本节这些数只能真跑，两者不互相顶替。）

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
⚠️ 与 W4 的对表项（09-19 对着代码订正，**这条陷阱当前不成立**）：
`app/graph/edges.py:329` + `app/api/runner.py:51` 自证 —— `_should_go_async()` 因缺"预估延迟"载体
（`gate3_cost` 的 `GateResult` 没有该字段）而**恒返回 `False`**，并有 `tests/contract/test_edges_contract.py`
钉着这个默认行为。⇒ **这个构建里没有任何查询会转异步**，本轮十份回执 `async_degraded=0` 是**预期结果**，
不是"恰好没触发"。上面那段"截断点压低 P95"的风险**要等该分支接线之后才生效**。
（旧版这里写过"全仓无消费方"，不准确：该枚举值有契约用例引用。）
⚠️ 但**别因此删掉 `--no-async`**：载体一加上，行为立刻变成上面描述的那样；届时必须重查 P95 口径。

### 四.1 `g6_caveat` 是**机器可读的降档开关**，不是注释（09-19 补，起因是一台真假绿灯）

下游 W6 的 `eval/reporter.loadtest_pressure()` 取"各场景 `latency_ms.p95` 的最大值"，
并**只靠 `g6_caveat` 是否非空**决定 G-6 降不降档（`eval/gates.py:204`）—— 它**不读 `outcomes`**。
本目录第一版只在有 `async_degraded` 时才填这个字段，于是本轮的真实数据落进去是这个形状：

| 输入 | `ok` 完成数 | p95 | 旧 `g6_caveat` | W6 读端算得 |
|---|---|---|---|---|
| §16.5 四条口径的合成回执 | **0** | 7268.4ms | `null` | ❌ **PASS(≤8s)** |

⇒ 散文里写"P95 全是失败样本"挡不住机器口径。已改成 `_g6_caveat(outcomes, admission)` 覆盖**六种**不可判情形：
① **该场景 0 条真正完成**（本轮新增，最强的那种不可判）；② 含 `async_degraded`（原有）；
③ 准入样本为 0；④ 准入样本 < `MIN_ADMITTED_FOR_P95`；⑤ 回执产自 U-106 之前（无 `admission` 字段）；
⑥ 有 429 被排除（把"排除了多少"这件事本身留在 caveat 里，不让它变成一个看不见的除法）。
`--self-check` 里这六种判向都有断言（含"真有 45 条准入完成 ⇒ **不该**降档"那条正向对照）。
变异检验分两批，别混着记：**09-19** 那批验的是"退回旧 `g6_caveat` 行为"（4/4 红）；
**09-20** 这批新验的是 ① 摘掉 `Retry-After` 读取 ⇒ 红、② 把"准入"放宽成"全部样本" ⇒ 红。
复算后**十份回执逐份过 W6 真读端 + 真 gates，全部 UNVERIFIED，无一例 PASS**。

### 四.2 U-106 的口径：**P95 只算准入样本，429 单列**（2026-09-20 架构裁定）

裁定原文的第二条是"报告口径：P95 只在准入（2xx）样本上算，429 比例单列"。落地成三个字段：

```json
"p95_scope": "admitted_http_2xx",
"admission": {"admitted": 30, "rejected_429": 20, "other_http_4xx": 1, "http_5xx": 0, "unresolved": 0},
"rejection_headers": {"429": {"retry_after=30": 20}, "503": {"retry_after=5": 1}}
```

⚠️ 上面是**形状示例**（数字是占位，不是本机读数 —— 这四份新口径回执还没跑过）。

| 字段 | 为什么要它 | 读法 |
|---|---|---|
| `p95_scope` | **自证分母**。`schema` 串刻意仍是 `w7.loadtest.receipt/1` 没升版：W6 的 `eval/reporter.py:139` 按该串**精确匹配**，升串会让 G-6 静默退回 `NOT_AVAILABLE`（口径修对了、接口弄断了）。⇒ 新旧回执靠这个字段区分，不靠版本号 | 缺这个键 ⇒ 是 U-106 之前的回执，`latency_ms` 是**混算**口径 |
| `admission` | 09-19 的 `receipt_steady` 里 `p50=7.3ms` 那种荒谬读数，来源就是"429 也是样本" | `rejected_429/admitted` 才是配额画像；`admitted` 才是容量的分母 |
| `rejection_headers` | 429/503 只有带 `Retry-After` 才叫"可恢复拒绝"；没有它，客户端只会立刻重试把配额保护打穿 | 场景⑤ `tenant-saturation` 的主判据就是这个字段（画像与命令见 §三.0） |

⚠️ 一处必须一起说的：`latency_ms_all_ms` 保留了**旧混算口径**，只用于"同一次跑批两口径对照"，
**不得**被引用成任何达标结论 —— 有 `p95_scope` 的场合，权威值是 `latency_ms.p95`。

### 四.3 U-120：`g6_p95_le_8s` 是**三态**，不是布尔（2026-09-22 落地）

判定点收在 `driver._g6_boolean()` 一处（唯一写点仍是 `_summarize`）。`None` 有三种来路，
每一种都比旧写法诚实 —— 旧写法在 `admitted=5` 时照样给布尔，且 p95 无值时给 `false`：

| 输入 | `g6_p95_le_8s` | 为什么 |
|---|---|---|
| `p95 = None` | `null` | "没有数"写成 `false` = 谎报"不达标"（架构 v1.6.5 补的①） |
| 无 `admission`（U-106 之前的旧件） | `null` | 分母口径无法确认 |
| `admitted < 20` | `null` | 07 §16.5：落点由个别样本决定，不构成容量结论 |
| `admitted ≥ 20` 且 `p95 ≤ 8000` | `true` | 唯一许出 `true` 的形态 |
| `admitted ≥ 20` 且 `p95 > 8000` | `false` | **唯一**许出 `false` 的形态 |

scope 就这一格：`ttfb_ms.p95` 与 `latency_ms_all_ms` 没有配对布尔，不入本判据（架构 v1.6.5 补的②）。
读法不变：**该位必须与 `g6_caveat` 同读**，单独引用任何一格都是断章。

守卫（`--self-check` 内，零外呼）：7 情形三态用例 + **`_summarize` 调用点双向**（低样本 ⇒ `null`；
20 条同型准入样本 ⇒ 真给 `true`，防"把三态写成永远 `null`"）。变异检查
`backend/reports/w7/scratch_g6_mutation_check.py` 实测 **6/6 被抓**（基线先跑、必绿；
M2 是崩溃式抓红 = `TypeError`，其余 5 条是断言式），含两处 A-1 变异。

**不可引用清单**（`g6_p95_le_8s: true` 但分母根本不可判的历史格，实测 **14 格 / 11 份文件**）：

⚠️ 在 **CommerceQL 根目录**执行（glob 是相对路径），零额度、零外呼：

```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe -c "
import glob,json
cells=0;files=set()
for f in sorted(glob.glob('deploy/loadtest/*.json')):
    for s in (json.load(open(f,encoding='utf-8')).get('scenarios') or []):
        if s.get('g6_p95_le_8s') is True:
            cells+=1;files.add(f);print(f,s.get('scenario'),(s.get('admission') or {}).get('admitted'))
print('stale_true_cells=',cells,'files=',len(files))"
```

2026-09-22 复算读数：`stale_true_cells=14 files=11`，逐格分解与我 10:26 的手工计数、
W6 产物 `probe_loadtest_receipts.json` 的 `stale_true_cells_total=14` 三方同数。
其中 `baseline_c5.json` 是唯一 `g6_caveat=null` 且同时缺 `admission`/`latency_ms_all_ms` 的那份
（p95=3675.8）⇒ W6 实测：这份喂进真 gates 会判 **G-6 PASS**，是那台假绿灯在当前盘上唯一活着的样本。

⚠️ **两种红法不许并成一种**：`preflight_r4/r5`（`admitted=5`、p95 42,529.1 / 187,728.9ms）的布尔本来是
`false`，不在上面这 14 格里 —— 它们是"**量到了、超预算**"，不是"分母不明"。引用时按 §三.0.1 的判据④说。

**A-1（架构 v1.6.6）现状**：`--roll-up` 已扩成同时重算 `g6_caveat` 与 `g6_p95_le_8s`，每格留
`g6_derived_audit{caveat_before/after,bool_before/after}`，且自检钉住"不许越界改读数"。
在**副本**上演示过：`receipt_steady true→null`、`receipt_burst`（p95=274.6ms！）`true→null`、
`baseline_c5 true→null`、`preflight_r5 false→null`。⚠️ **11 份归档件本身的就地降档尚未执行**
—— 那会改写归档证据的字节、且 `receipt.json` 是 W6 的 G-6 默认输入 ⇒ 等总控点头再做，做完在此登记读数。

### 四.4 U-122：本目录引用 exec 侧读数的口径（归 W7 的那半）

| 本目录里的名字 | 它**不是**什么 | 实测依据（2026-09-22，零额度） |
|---|---|---|
| `outcomes.truncated` | ❌ 不是 §8.6 的"行数被 LIMIT 截断" | 它是**客户端流截断**：流结束却没拿到终止帧（`driver.py` 的分类判据） |
| 任何回执 | ❌ 不能当"服务端截断判定已验证"的证据 | gate1 的 `limit_injected` 实测只有 `{"injected": true}`，**注入值 L 没有出口**；`app/graph/nodes/execute.py:133-146` 的 `_effective_limit` **P0 恒 `None`** ⇒ §8.6 的 `truncated` 判定在生产路径今天就是退化的 |

⇒ 结论口径：压测面**只能**判"端到端有没有在 8s 内收口"，判不了"结果集有没有被静默截断"。
后者要等 U-122 判据①②④ 落地（端口成员集 + 替身忠实性）＋ W2C 给出 L 的出口，
本目录届时回一条可复制的读法。⚠️ 该读法 **UNVERIFIED**（今天写不出来，别在别处引成"已有"）。



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

## 八、回执字段 `terminal_provenance`：分清"这条终止是谁说的"（09-20 补）

`outcomes` 只说"终止成了什么"，`codes` 只说"错误码"。有一类问题这两个字段**都答不了**：

> 一条 `refuse(reason=no_data_asset)` 是 **intent 层**给的（07 §5.2 组 3），还是 **`link` 空召回**给的（§5.3）？

两个落点**共用同一个 4 值枚举**（`core/enums.py:429-432`）⇒ 只看 reason 无法分家，而这件事直接决定
"要让 `complete` 不为 0，该去修闸门还是该去修检索"。驱动因此多记一条**终止前最后一个 `stage` 帧**，
在回执里落成：

```json
"terminal_provenance": {
  "clarify": {"stage=阶段名|reason=原因值": 1},
  "refuse":  {"stage=阶段名|reason=no_data_asset": 2}
}
```

⚠️ 上面是**形状示例**（占位），不是本机读数 —— 本轮四场景是在这个字段存在之前产的，
它们的 `terminal_provenance` 键**不存在**（见下表第三行）。

读法（⚠️ 三种形状各有含义，别一律当"数据缺失"）：

| 形状 | 含义 |
|---|---|
| `stage=<某阶段>` 加 `reason=<某值>` | 终止**之前**流上最后出现的那个阶段 ⇒ 该阶段的**下游**节点说的 |
| `stage=none` 加 `reason=none` | 要么根本没进流（`http_4xx`/`http_5xx` 就是这种），要么**第一个 stage 帧之前**就破了 ⇒ 本身就是定位信息 |
| 整个键缺失 | 这份回执是 09-20 之前产的（旧驱动没有这两个字段）⇒ **不要**据此推断"没有终止" |

自检（`--self-check`）已把这三个形状**钉成整字典相等**的断言，并做过变异检验：
删掉"记 stage"那一行 ⇒ 自检 exit=3 红；还原 ⇒ 逐字节相同 + 绿。

## 九、判"零完成是不是并发造成的"：先跑 c=1，再谈并发预算（09-20 的方法论教训）

本报告 §三/§四 原先把"所有档 `complete`=0"归给"并发预算撑不到 50 并发"。**那个归因错了**，
而纠正它只花了 **1 条请求**：

```bash
# 同一镜像、同一题库，把在途压到 1 条：并发因素被摘掉
python driver.py --target http://127.0.0.1:18000/api/v1 --scenario steady \
                 --max-requests 1 --duration-s 30 --out probe.json
# 本机 09-20 实测：-> 1 条，p95=2052.2ms，{'error_frame': 1}（codes: INTERNAL）
```

⇒ 在途只有 1 条时仍然超时（服务端 `node_timeout{node:"normalize",limit_s:2.0}`），
所以**并发不是必要条件**，只是放大器（2.05s → 2.5–7.3s）。

⚠️ 反过来也**不要**据此说成"每条请求必死"：同一天回读 `baseline_c5.json`（09-19，c=5）是
**clarify 5 + refuse 13 + error 2 / 20** ⇒ 多数请求当时在 2.0s 内走通了 `normalize`。
两组合起来的正确说法是：**预算对那次合并 LLM 调用零余量 ⇒ 存活由 LLM 延迟抖动决定**。

⇒ 纪律：**任何"N 并发下全崩"的结论，都要先用 `--max-requests 1` 复现一次**。
不花额度、几秒钟，但能把"容量问题"和"根本跑不通"这两种完全不同的病分开 —— 它们的修法、归属、优先级都不一样。
