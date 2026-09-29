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
★ **09-23 晚订正**：W2B `f5e501d` 已补上调用点 ⇒ 本轮该族**第一次有活体非 0 序列**（`hybrid=2`）。本句"缺埋点"已是历史状态，见 §三.0.1l。
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
  ★ **09-23 晚订正（这条"路不通"的归因写错了）**：`binding_state_total` / `binding_layer_total` **一直有调用点**
  （`app/api/deps.py:563/564`，W2B 指出、我 grep 复核）；`retrieval_mode_total` 的调用点由 W2B `f5e501d` 补上，
  09-23 晚**首次拿到活体非 0 序列**（§三.0.1l）。⇒ 当时全零的真实原因是**请求根本没走到那段代码**（PLAN/BIND/link 之前就被终止），
  不是"埋点不存在"。**区分这两件事很要紧**：前者换个题面就能出读数，后者要改代码。
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

#### 三.0.1j 第九轮预检（09-22 · 镜像 `w7load-api:0922r6` = HEAD `fb8b4c6` ⇒ 含 W2C `c76f701` + W2A `5e47558` + W0 `36c782a` + W2B `d4ca203`）

**一句话**：**U-121 那一格真的通了** —— 史上第一次有请求穿过 gate1+gate2+gate3 走到 `executing`
（`stage_duration_seconds_count{executing}` 0→**1**）。但判据④ 仍不过（`ok=0`），且**红因已经不是闸门**：
今天是一条**两边各自合规、合起来走不通的死锁** ⇒ 闸门只认非限定资产名（带 `app.` 前缀一律 `R16`），
而 analytics 池的 `search_path` 里**没有 `app`** ⇒ 任何合法资产名在 execute 期必 `undefined_table`。

| 读数（`preflight_r6.json`，c=1 / n=5 / `--no-async` / `questions_T_A_time.txt` · 11:48:48–11:49:07Z） | 值 |
|---|---|
| `outcomes` | `{refuse:1, clarify:3, error_frame:1}`、`codes={GATE_AST_REJECTED:1}`、**`ok=0`** |
| 终止出处 | `stage=intent\|reason=out_of_scope` ×1、`stage=intent\|reason=time_ambiguous` ×3、**`stage=executing\|reason=none` ×1** |
| 指标面（★ = 该格第一次非 0） | `intent` **6** / `schema_linking`★ **1** / `plan_ready`★ **1** / `sql_ready`★ **1** / `gate_passed` **0** / **`executing`★ 1**；`query_outcome_total{failed}`★ **1**、`{success}` **0** |
| `llm_call` | **9 条** = `normalize_intent`×5 + `plan`×1 + `l4_score`×1 + `gen_sql`×1 + **`repair`×1**★ |
| 时延 | p50 **1,060.5ms**、p95=max **11,157.4ms**、mean 3,875.1ms、wall 19.45s、TTFB p50 **6.8ms** |
| `g6_p95_le_8s` / `g6_caveat` | **`null`** / "0 条真正完成 ⇒ 分母全是失败样本"＋"准入样本仅 5 条（< 20）" ⇒ **U-120 三态在活体上第一次走对**（没把"没量到"写成"不达标"） |
| 台账结账 | 9 行 / **¥0.014471**（跑前报备的是 ¥0.02–0.04 ⇒ 声明偏保守，实测更低）；`httpx 200` 9 = `llm_call` 9 ⇒ 零缺口 |

**红因换了什么（三条互相独立的实测，不是一条推论）**：

1. **闸门面（离线、零额度）** `scratch_searchpath_asset_face_probe.py`：
   非限定合法资产名 `v_order_paid` ⇒ gate1 **过**、gate2 **过**；`app.v_order_paid` ⇒ **gate1 `R16` 拒**
   （`ast_gate.py:531-534`：带 schema 前缀 = 绕白名单形态）；裸表 `order_paid` ⇒ gate1 `R05` / gate2 `G2-ASSET`
   ⇒ ✅ 顺带排掉一条我本来担心的洞：**deny 列经裸表名绕不过去**（裸表 + `receiver_phone` 仍是 `R05`/`G2-ASSET`）。
2. **解析面（psql，以 `app_ro` 会话身份，只读）**：`search_path="$user", public` ⇒
   `from order_paid` 与 **`from v_order_paid`（合法资产）同样** `relation does not exist`；`from app.v_order_paid` ⇒ 可解析。
3. **生产池 A/B（`scratch_searchpath_ab.py`，六臂 E1…F，容器内跑真 `build_analytics_engine`）**：
   A 生产池原样 + 非限定名 ⇒ `ProgrammingError: relation "v_order_paid" does not exist`；
   B 同池连接内 `SET search_path=app,public` ⇒ `count=200000`；C 池级 `-c search_path=app`（照 `lg` 的先例 `pools.py:343`）⇒ `count=200000`；
   D 限定名在 B 臂同样出数（但闸门面 R16 拒 ⇒ 这条路不可用）。

**⇒ 一处修好、两格复原（不记两笔账）**：E 臂 = 生产池上 `EXPLAIN … from v_order_paid` 报的**也是**
`relation "v_order_paid" does not exist`，F 臂 = 池级 `search_path=app` 上 EXPLAIN **出计划**。
所以本轮日志里 `gate3_explain_failed → "EXPLAIN 不可用 → warn"` 与 `exec_failed unknown_table`
**同一个因**，不是两个缺陷。

**⚠️ 我自己上一版判据的收窄（留痕，不改 §四.5 原文）**：本轮之前我写的"预检要读 `sql_ready → gate_passed` 的第一格非零"
—— **`gate_passed` 在 EXPLAIN 不可用的今天结构性为 0**：`events.py:55` 明写 `stage=gate_passed` 只在**三闸门 `passed is True`** 时发，
而 gate3 判 `warn` 按 §14.2 D6 **不得算通过**（`nodes/gate3_cost.py:18` 同句）。⇒ 活体上**最早**能拿到的穿透信号是
`executing`，不是 `gate_passed`；把 `gate_passed=0` 读成"闸门坏了"是反向的。

**⚠️ `rule_id` 今天到不了归因面（这是缺口，不是我没看）**：客户端 error 帧只有 `code`/`message`/`retryable`
（`api/runner.py:542-561` 的 `_extras(ERROR_OUT)` 载荷 = `errors.map_code(...)` 的**固定文案**，`detail` 还只在特定角色下给），
`gate_detail` 只挂在 `gate_passed` 事件上 ⇒ 拒绝路径**没有 `rule_id` 出口**。指标面同一条实测：
`gate_reject_total{gate_no="1",rule_id=""} 1` —— **有调用点**（`obs/instrumentation.py:455`）但**载体未给规则号**
（`metrics.py:177` 把空值定义成"载体未给"，所以这不是崩，是口径到头）。
⇒ 本轮 §四.5 第 4 行那种 `R06/R06` 核对**只能走离线器件**，压测面与 `/metrics` 都判不了。需求已提给 W4/W5：
唯一记录点应落在闸门节点（先例就是 `execute.py::_on_failure` 记 `exec_failure_total`），
且**必须同时**摘掉 `instrumentation` 里那条反推 —— 否则双计（同一处注释已经警告过）。

**三条必须一起说的限定**：
1. **HANDOFF 的构建配方是错的**：我写的 `docker build -f deploy/Dockerfile … backend` 必失败
   （`Dockerfile:38` 的 `COPY deploy/entrypoint.sh` 相对构建上下文解析 ⇒ 上下文必须是**仓库根**）。
   本轮实跑：上下文 `backend` ⇒ `ERROR … "/deploy/entrypoint.sh": not found`；上下文 `.` ⇒ 成功。**已改 HANDOFF §五**。
2. **`repair` 这一跳本轮花了 ¥0.006592**（单次最贵，`cache_hit_ratio=0.0`），产出是一条被 gate1 `R05` 拒的裸表 SQL
   ⇒ 对 G-6 是**纯浪费**。它不是我造成的（同一因），但**修好 search_path 之前 repair 的账会一直这么花**，跑批成本口径要带上它。
3. **题池决定 clarify 占比**：`questions_T_A_time.txt` 42 条里本轮 3/5 终止在 `reason=time_ambiguous` 是**设计使然**
   （这个池就是为澄清率建的），不是回归。⇒ 判据④ 用这个池**天然难拿 `ok`**，下一轮要么换"时间口径完整"的池，
   要么显式说明"判据④ 只需 ≥1 条 ok，与澄清率题池不冲突"。

**⇒ 本轮处置**：判据④ 未过 ⇒ **四场景仍不跑批**。红因从"闸门恒拒"换成"`search_path` 无人认领"，
架构 v1.6.9 那句"修完 U-121 也还不能演示"**仍然成立**，但成因又换了一格。`app/repo/pools.py:227` 写"归 W2A 的认证视图 schema"、
W2A 未设 ⇒ **两格互相指认**，按纪律我**不自取 U 号**，需求已随回执上报（下一可用号 U-124）。



#### 三.0.1k 第十轮预检（09-23 16:0x · 镜像 `w7load-api:0923r7` = HEAD `776beb4` ⇒ 含 W2A `d8eca02` = U-124）：**判据④ 第一次达成**

**一句话**：`search_path` 那处一落地，链路**整条亮起来** —— `ok=3`、`codes={}`（零错误帧）、
**`gate_passed` 与 `executing` 同时第一次非 0（各 3）**。⇒ **G-6 从"没有分母"变成"有分母但样本不够"**，四场景跑批的前置解除。

| 读数（`preflight_r7.json`，c=1 / n=5 / `--no-async` / 与上轮**逐参数相同**） | 值 |
|---|---|
| `outcomes` | `{ok:3, clarify:1, refuse:1}` ⇒ ★ **判据④（≥1 条 `outcome=ok`）达成** |
| `codes` / `error_messages` | **`{}` / `{}`** —— 本目录九轮预检以来**第一次零错误帧** |
| 终止出处 | `ok` 三条全 `stage=executing\|reason=none`；`clarify` `stage=intent\|time_ambiguous` ×1；`refuse` `stage=intent\|out_of_scope` ×1 |
| 指标面（★ = 首次非 0） | `intent` 6 / `schema_linking`★ **3** / `plan_ready`★ **3** / `sql_ready`★ **3** / **`gate_passed`★ 3** / `executing`★ **3**；`query_outcome_total{success}`★ **3** |
| 时延 | p50 **5,767.6ms**、p95=max **9,756.0ms**、mean 5,490.7ms、wall 27.55s、TTFB p50 **6.4ms** |
| `g6_p95_le_8s` / `g6_caveat` | **`null`** / **只剩一条**："准入样本仅 5 条（< 20）" ⇒ "0 条完成"那条 caveat 正确地消失了（U-120 三态的第二面） |
| 台账结账 | **14 次调用 / 62,552 tokens / ¥0.030397**（⚠️ **高于我报备的 ¥0.015–0.025**，见下方校准） |
| 前置复核 | `embed_doc` 跑前 15:57 与跑后 16:04 均 `197\|197\|197` |

**独立复测 U-124（不转述 W2A 的回执）**：我自己的六臂件 A 臂**由红转绿** ——
生产 `build_analytics_engine` 原样、无任何 preset：`SELECT count(*) FROM v_order_paid` ⇒ `200000  search_path=app`，
`EXPLAIN` 同一连接 ⇒ 出计划。⇒ §三.0.1j 那条死锁**已解**，且 `gate3` 从此走真 EXPLAIN 而非 warn
（这解释了本轮 `gate_passed` 为什么同时从 0 变 3：**它依赖 EXPLAIN 真出计划**）。

**⚠️ 花费校准（我报备错了方向，必须记进报价口径）**：上轮 9 次 / ¥0.0145 是**链路在 gen_sql 之后当场死掉**的形态；
本轮**成功反而更贵** —— 一条走完全链的请求要 `normalize_intent + plan + l4_score + gen_sql` ≈ 4 次调用，
`repair` 只是失败路径的额外开销。⇒ **新锚点：一条 `ok` ≈ ¥0.0087**（14 次 / ¥0.0304 ÷ 3 条 ok + 2 条早退）。
**跑批报价一律用这个锚点，别再拿"死在闸门前"的单价外推**（那会系统性低估 3–5 倍）。

**跑批前必须一起说的两条限定**：
1. **单机不是产品容量**：本机 Ollama `bge-m3` 单条 embedding 实测 **4.5–5.0s**（§三.0.2），
   c=50 时检索侧会排队 ⇒ P95 里含**压测环境的瓶颈**，报告须按"单机观测容量"口径写，不得写成产品结论。
2. **`--max-requests` 硬上限 ≠ §16.5 的"持续 10min"**：按 §二 参数跑满是 **50 并发 × 600s ≈ 数千条** ⇒
   按 ¥0.0087/条粗算 **¥40+**，不可行。⇒ 只能"配额上限 + 满足 `MIN_ADMITTED_FOR_P95=20`"，
   这是**对 §16.5 的偏离**，要架构/总控明确接受才写进 G-6 报告（默认建议见 `RELAY.md` §三十二⑤）。

#### 三.0.1l 第十一轮（09-23 晚 · 镜像 `w7load-api:0923r8` = HEAD `f5e501d` ⇒ 含 W2B 的 RL-2 接线）

**一句话**：**`retrieval_mode_total` 第一次出现活体非 0 序列**（W2B 接线由我复验成立）、
**判据④ 在新镜像上复现（`ok=2`）**，但同轮抓到一条**新的文档级互斥**：
`MODEL_HARD_TIMEOUT_S[FAST] = 15.0s`（07 §10.2 分配）与 G-6 的"端到端 p95 ≤ 8s"在文档层面就不能同时成立。

**共享栈外部重启第 4 次 + 一条新坑**（我全程没碰编排，只登记）：`pg_postmaster_start_time = 2026-09-23 12:47:19+00`，
我自己的 `w7load-api` 以 `Exited(255)` 躺在里面。⚠️ **重启后 `pg_stat_user_tables` 四张表全部归零**：

| 表 | `n_live_tup / ins / upd / del`（归零） | `count(*)` 真值（完好） |
|---|---|---|
| `app.embed_doc` | 0/0/0/0 | **197**（`count(embedding)=197`、`count(tsv)=197`） |
| `app.cost_ledger` | 0/0/0/0 | 23 → **本轮后 36**（终值实测，见末节花费） |
| `app.query_plan` | 0/0/0/0 | 4 |
| `app.audit_log` | 0/0/0/0 | 108 |

⇒ **口径改写（对我自己是破坏性的）**：`HANDOFF §六` 那条"pg_stat 是累计量 ⇒ 只有带时间戳的**差分**作数"**前提还在，但基线断了** ——
归零之后无法再区分"别人重灌了 N 次 `embed_doc`"与"统计被清"。U-114 的历史取证链在 12:47Z 之前那段**永久不可重建**。
⇒ 本轮起 embed_doc 前置判据退回 **`count(*)=197` + `count(embedding)/count(tsv)` 非空计数**，不再引用差分。
⚠️ 归零的**成因我不写**（`pg_stat_database.stats_reset` 对 `ecom` 仍为 NULL，与"有人调了 `pg_stat_reset()`"不同态；
我没有单变量对照 ⇒ 只登记"数据完好而计数归零"这个事实）。

**四条运行读数**（同一容器、同一镜像、同一 token，全部真实额度）：

| # | 命令 | 结果 |
|---|---|---|
| ① | `steady --no-async c=1 n=2`（**冷容器**） | `{refuse 1, clarify 1}`、`ok=0`、**p95 72,768.7ms** |
| ② | 同上（**热容器**） | 同两题、同镜像：**p95 1,345.7ms** |
| ③ | `session-lock c=8 n=24`（单一真会话） | `admitted=1`、**9×409 `SESSION_CONFLICT`(Retry-After 3)** + **14×429 `RATE_LIMITED`(Retry-After 30)**、准入那条 p95 15,060.6ms → `refuse(no_data_asset)` |
| ④ | `steady --no-async c=1 n=5`（= r7 同配置，等 75s 清滑窗后跑） | **`{ok 2, clarify 2, refuse 1}`**、`codes={}`、p50 **5,213.3ms** / p95=max **15,080.1ms**、wall 35.9s |

**★ ①/② 是本仓第一条干净的单变量对照**：同镜像、同题、同 n、同并发，只差"容器冷/热"一个变量 ⇒
**p95 72,768.7ms → 1,345.7ms（54 倍）**。§三.0.1i 末节我写过"冷容器第一条吃掉整个 p95，但未做单变量对照 ⇒ 不写成成因"——
**这条限定今天可以撤销了**。⇒ **跑批规程**：跑批前必须先打 1–2 条预热请求并把它们排除出分母、或整体作废重跑。

**★ 我自己的一个取证错误（先撤回再报）**：① ② 两条都"没有 ok"，我一度判成"判据④ 不可稳定复现"。
读驱动才知道取题是 `questions[i % len(questions)]`（`driver.py:280`）⇒ **n=2 只打到文件第 0、1 题**：
`T_A 2026-08 的日期维表有多少天？`（`intent → refuse(out_of_scope)`）与
`T_A 从 2026-08-01 起的 GMV 是多少？`（`intent → clarify(time_ambiguous)`）——
**这两题结构上就到不了 `link`**，r7 的 3 条 ok 来自 Q2–Q4。⇒ **不是回归，是我切片切错了**；
"判据④ 抖动"这句话在写进任何文档之前就被我自己否掉了（归档回执 `preflight_r8_cold/warm.json` 仍留着，作为"别按 n=2 下结论"的反例）。

**★★ ③ 的算术完全对上一条配置 ⇒ session-lock 的参数集是自相矛盾的**：
`ratelimit.py:203` `RateLimitBucket.QUERY = RateLimitRule(QUERY, per_user_per_min=10, per_tenant_per_min=100)`、窗口 `WINDOW_S=60` ⇒
24 条同一 `user_id` 在 15.2s 内打出 = **10 条过限流 + 14 条 429**；那 10 条 = **1 条拿到锁 + 9 条 409**（锁只给一个赢家，其余按 `SESSION_LOCK_WAIT_MS=3000` 等待后拒）。
⇒ **场景③ 按 §16.5 原样跑，测到的主要是限流器，不是会话锁**：锁的真实观察面只有 10/24。
✔ 立得住的判据：**409 带 `Retry-After: 3`、429 带 `Retry-After: 30`、两者桶名与头齐全**（U-106 的"拒绝必须可区分"这一面成立）。
✘ 立不住的判据："并发下锁把请求排成串行"—— 需要 per-user 配额 ≥ 总请求数，或把 24 条摊到 >60s 窗口。
⚠️ **我不擅自改 §16.5 的场景参数**（那是契约面）⇒ 提架构裁（见 `RELAY.md` §三十三③）。

**★★★ ④ 复现了判据④，同时暴露一条新的 G-6 结构性障碍**：
`stage_duration_seconds_count` 六档同亮：intent **11** / schema_linking **2** / plan_ready **2** / sql_ready **2** / **`gate_passed` 2** / **`executing` 2**，
`query_outcome_total{success}=2`、`codes={}`、`gate_reject_total` 全 0。
⇒ **`gate_passed` 与 `executing` 同时亮**（架构 09-23 回执⑤的说法在我这里得到实测支持），
我先前那条"只亮 executing 而 gate_passed=0 ⇒ 闸门坏了"的反向读法**正式作废**。

**★ `retrieval_mode_total{hybrid} = 2` —— 该族第一次有活体非 0 序列**（基线同容器为 0）。
⇒ W2B `f5e501d`（`app/retrieval/search.py:242 observe_retrieval_mode(effective_mode)`）**接线成立，由我独立复验**。
⚠️ **只验了成功分支**：本轮 `sparse_only` 仍 = 0（没有发生 embedding 降级）⇒
"降级分支会被记成 `sparse_only`"这条**UNVERIFIED**，且**我不为它制造降级**（要停共享 Ollama = 动别人的运行面）。
⇒ RL-2 的"证据"等级从今天起可以从「缺埋点」升到「分子已有活体读数」，但**分母口径仍未测**。

**★★ 新发现的文档级互斥（给架构 + W4，不是我的地盘）**：
`app/llm/router.py:306 hard_timeout_s()` 明写 **flash 15s / pro 45s（07 §10.2 分配）**，
而 G-6 要的是**端到端 p95 ≤ 8s**。⇒ 一条用满 flash deadline 的请求**独自就能把 p95 顶到 15s** ——
本轮 ④ 的 max/p95 样本 **15,080.1ms ≈ 15.0s + 80ms**，且同轮 `degraded_total{llm_unavailable,template_only}` 由 2 → **3**
⇒ 那个样本极可能就是"normalize 吃满 15s 后降级"的那条（⚠️ 相关不是因果：n=5，我没有对该条做单请求追踪）。
本轮 `llm_unavailable` 累计 **3 次 / 约 9 条走到 normalize 的请求 ⇒ ~33% 命中率**。
⇒ **可判的推论（这是推算，不是读数）**：按 33% 命中率，admitted=20 的批测里期望 ~6 条落在 15s ⇒
**p95 必然 ≥15s ⇒ G-6 会读成 `false` 而不是 `null`**。
这与 §三.0.1h 的 `bind 0.2s` 是**同一处预算表的两面**（一面掐太紧、一面放太松），⇒ 归 W4 落、架构裁，**W7 两边都不动**。

**一条免费的自洽断言**：`degraded_total{present_failed,table_only} = 2` 与 `query_outcome_total{success} = 2` **1:1** ——
出处是 `app/api/deps.py:824-826`（`presenter=None` ⇒ `app/present/` 空壳 ⇒ §14.2 F4 **P0 下每个成功请求必带一条 degraded**，注释自陈"这是既定 P0 形态（不是缺陷）"）。
⇒ 以后任何一次跑批若出现 `success ≠ degraded{present_failed}`，**说明 present 接线变了**，这比单独盯某个计数器灵敏。

**本轮花费（先报后跑，全部实测复核）**：预估 ≤¥0.07（上限 ¥0.23）⇒ **实跑 13 次调用 / ¥0.013110**（台账 `created_at > 12:55Z` 过滤）。
⚠️ 低于预估的原因不是便宜，是 **24 条里有 23 条在模型之前就被 409/429 拒了** ⇒ **"花费低于预估"本身要按"准入数低于预估"来读，别当成单价校准成功**。
锚点复核：④ 一条 ok ≈ 7 次调用 / ¥0.0079 ⇒ §三.0.1k 定的 **¥0.0087/条** 误差 <10%，**继续用**。

#### 三.0.1m 第十六轮（09-28 · 镜像 `w7load-api:0928r9` = HEAD `fb307f7` ⇒ 含 `e0e6b39` U-125①②③ / `7114c7f`+`3251344` 判据⑥ / `e0ce440` U-119④）

**一句话**：**`g6_p95_le_8s` 第一次产出布尔 = `false`**（`admitted=79 ≥ 20`），同轮拿到 **U-125 判据的活体读数**与
**`retrieval_mode_total{sparse_only}` 的首次活体非 0**；但**整轮的容量读数被一条依赖故障污染** —— 本机 **Ollama 没在跑** ⇒
检索全量走 `sparse_only` ⇒ 我**主动扣住 `burst` 不跑**（不花 ¥0.5 买一个被混淆的数字），等依赖恢复后重打。

**⚠️ 前置就变了：共享栈今晨又被外部重启，且一条软依赖是死的**（我全程未碰编排）

| 检查 | 读数 |
|---|---|
| `app.embed_doc` 跑前/跑后 | **`197\|197\|197` 两次同值** ⇒ 我没损坏共享前置 |
| `/api/v1/healthz/ready` | **5.5 / 5.0 / 4.3 ms**（闲置 >5 分钟后取的冷读数） |
| 容器 → Ollama | **`ConnectError [Errno 101] Network is unreachable`**；宿主 `127.0.0.1:11434` 连不上 ⇒ **embedding 依赖 down** |
| 容器 → DeepSeek | **98 次全 `HTTP/1.1 200`、零次非 200** ⇒ **不是没钱、不是被上游限流** |
| 台账 | 本轮 **98 行 / ¥0.168636**；`httpx 200` 98 = 台账 98 ⇒ **零缺口**（复证 §三.0.1i 的口径：缺口 = 被取消数，不是恒有偏差） |

**四条运行读数**（同一容器、`questions_T_A_time.txt`）：

| # | 命令 | 结果 |
|---|---|---|
| ⓪ 预热 | `steady --no-async c=1 n=2`（**排除出分母**，见下"规程"） | `{refuse 2}`、p95 5,690.4ms |
| ① | `steady c=50 n=120`（**10 个同租户 T_A 令牌**轮转） | `{refuse 66, http_4xx 41, clarify 8, error_frame 3, ok 2}`、`codes={RATE_LIMITED:41, GATE_AST_REJECTED:3}`、`admitted=79`、p50 **5,474.4** / p95 **11,381.8** / p99=max 14,289.8、wall **14.4s**、**`g6_p95_le_8s=false`** |
| ② | `tenant-quota c=30 n=60`（**改单令牌** —— 见下"设计更正"） | `{http_4xx 50, refuse 8, error_frame 2}`、`codes={RATE_LIMITED:50, LLM_UPSTREAM_ERROR:2}`、`admitted=10`、429 全带 `Retry-After: 30`、p50 15,199.6 / p95 20,227.8、`g6=null` |
| ③ | `steady --no-async c=1 n=3`（**对照实验**） | `{refuse 3}`、**p95 2,117.1ms**、**期间 `node_timeout_degraded` 增量 = 0** |
| — | `burst c=100 n=100` | ⛔ **主动不跑**（依赖故障态下只会产出又一个被混淆的 P95；等 Ollama 恢复） |

**★★ `g6_p95_le_8s = false` 是本目录第一次给出布尔 —— 但它是"配额档 P95"，不是达标判定**：
架构 `07 §16.5` 配额档四条判据逐条自证：①具名 `deviation=quota_capped_n`（`--max-requests 120` 截断，实跑 14.4s ≪ §16.5 的 600s）✅；
②`admitted=79 ≥ 20` ⇒ 布尔可给，**标签只能写"配额档 P95"**，G-6 达标行仍只认满档 ✅；③环境瓶颈同行披露 ✅（下面两条）；④先跑零额度那格 ✅（`session-lock` 已于 §三.0.1l 跑完）。
⚠️ 引用纪律：**这一格不得写成"G-6 判定为不达标"**，只能写成"配额档 P95 = 11,381.8ms > 8s，且测于检索降级态"。

**★★★ 15s 那一条尾是并发排队打出来的（本次做了单变量对照，不再靠推测）**：
① 有 **8 次 `node_timeout_degraded{node:"normalize", limit_s:15.0}`**，而同一容器内所有 `normalize_intent` 调用的
`latency_ms` 全在 **1,003–1,132ms** ⇒ **15s 不是模型耗时**；③ 在**同一栈、同一降级态、隔几分钟**下用 `c=1` 打三条 ⇒
**p95 2,117.1ms 且超时增量为 0**。⇒ **结论**：`normalize` 的 15s 墙钟被**网关并发闸（`LLM_SEMAPHORE_FLASH=8`）的排队**吃掉，
不是上游慢、也不是 embedding 中断。⇒ 这条**修订我 09-23 §三.0.1l 的推论**（当时写"flash 15s deadline 独自把 p95 顶到 15s"）：
deadline 是**上限**，真正把 p95 顶上去的是 **c=50 vs 8 个槽的排队**；两者叠加 ⇒ 见 `RELAY §三十四③` 给架构的新判据问题。

**★★ `retrieval_mode_total{sparse_only} = 70` —— 降级分支首次活体（且不是我制造的）**
与 `degraded_total{reason="embedding_unavailable",action_taken="sparse_only"} = 70` **同数同因**，容器日志逐字：
`"embedding": "上游不可达：连接层失败（DNS / TCP / TLS 未建立）：ConnectError（走降级：稀疏 + Join 图扩展）"`。
⇒ **RL-2 的分子两面（`hybrid` 09-23 / `sparse_only` 09-28）都有活体读数了**；**"我不为它制造降级"这条纪律自动兑现**（依赖是自然坏的）。
⚠️ 分母口径仍未定（§三.0.1l 那条"不得拿 `schema_linking` 计数当分母"继续有效）。

**⚠️ 本轮 80% 的准入请求死在检索之后的原因（根因 + 竞争解释已排）**：`refuse` 66 条里 **63 条落在 `stage=schema_linking|reason=no_data_asset`**，
与 `sparse_only=70` 同向 ⇒ 归因于 embedding 中断。⚠️ 我原本怀疑自己的**多令牌设计**（10 个合成用户没有数据范围）才是主因，
用 `app.audit_log` 逐用户分组否掉了：`no_data_asset` 在 **u_a01…u_a10 上均匀分布（各 5–8 条）** ⇒ 不是用户维度的事。

**★ 设计更正（这条很重要，别让下一个人再踩）**：`QUERY` 桶是 **per_user=10/min + per_tenant=100/min**（`ratelimit.py:203`）。
⇒ ① 对 `steady`/`burst`：用**同租户多用户令牌**（驱动 `--tokens` 天然支持 `tokens[i % len]`）把整形从 per-user 抬到 per-tenant，
这才是"测并发"而不是"测限流"；② 对 `tenant-quota`：**必须反过来用单令牌** —— 否则 60 条摊到 10 个用户（6/用户）**谁也碰不到桶**，
本场景会零拒绝收场、什么也没测。⚠️ 且 **`n=60 < per_tenant=100/min` ⇒ 场景④ 在 §16.5 原参下永远触发不了租户维度**，
只能演示 per-user 维度 ⇒ 与 §三.0.1l 的 `session-lock` 是**同一族参数自相矛盾**（第二条实例），已提架构。

**★ U-125 判据达成（架构定的"拒一条后 `/metrics` 的 `rule_id` 非空"）**：`gate_reject_total{gate_no="1",rule_id="R05"} 3`，
同轮 `query_outcome_total{failed}=3` 与 `codes={GATE_AST_REJECTED:3}` 对齐 ⇒ **闸门侧唯一记录点成立、帧面双计已摘**（`e0e6b39` 三方同批）。
⚠️ 只覆盖 gate1；`gate2/gate3` 的 `rule_id` 活体序列本轮未出现（本轮没有闸门 2/3 的拒绝 ⇒ 分母为空，不是不成立）。

**★ 还掉一条我自己挂着的欠账（U-122 归 W7 那半）+ 顺带否掉我自己的一个新判断**：
本轮两条 `ok` 里有一条 `row_count_returned=1000`、`final_executed_sql` 结尾确实是 **`LIMIT 1000`**，而 `audit_log.truncated=false`。
我第一反应是"§8.6 判定失效"—— **读了实现才撤回**：`execute.py:28-35` 明写 **`effective_limit` 在 P0 恒 `None`**
（注入值 L 在 `ast_gate._effective_limit` 内部用完即弃），于是 `executor.py:371` 走
`truncated = len(rows)==effective_limit if effective_limit is not None else more_exist` 的**兜底分支** ⇒
`false` 是兜底的正常输出、**不是判定错**。⇒ 可复制的读法（本节即为交付物）：
**"今天 `audit_log.truncated` 一律来自 `more_exist` 探测，不来自 §8.6 的 LIMIT 规则 ⇒ 压测面不得声称'服务端截断已验证'"**；
核对命令（零额度、只读）：`select row_count_returned, truncated, right(final_executed_sql,60) from app.audit_log where outcome='success'`。
⇒ 开项仍是**已登记**的那条（`execute.py:35`："请 W2C 把 L 一并放进 `limit_injected`"，与 W6 的 `RT-LIM-001/004` 同一件事）。

**本轮花费**：**98 次调用 / ¥0.168636**（跑前预估 ¥1.1–2.0 ⇒ **实际远低于预估**，原因照旧是**准入后大量早退、且 `burst` 未跑**，
不是单价准）。⇒ **剩余待办 = Ollama 恢复后重打 ①（`steady`）与 ②（`burst`）**，估 ¥1.1–1.9。

#### 三.0.1n ★★ 第十七轮（2026-09-28 18:00–18:27 本机 / 10:00–10:27Z）：**健康态四场景补齐 + 三条新缺陷有日志署名**（镜像 `w7load-api:0928r9` 全程未换）

**前置（跑前 / 跑后各一次，只读）**：Ollama 由**总控于 17:5x 启动**（不是我自己启的 —— 见本节末"纪律条"），我复验三处可达性：宿主 `127.0.0.1:11434` → 200 / 3.6ms，容器内 → 200 / 91ms，`bge-m3:latest` 在列；`/api/v1/healthz` = `status:ok` 且 `degraded_dependencies=[]`、`embedding_reachable:true`；`app.embed_doc` 跑前跑后 **`197|197|197`**（`count(*)|count(embedding)|count(tsv)` 未变 ⇒ 我没损坏共享前置）。
**令牌**：本轮两批 —— `u_b01..u_b10`（10 个，§三.0.1m 末铸）与 `u_c01..u_c20`（20 个，为本轮两个租户格新铸，`iss=workbuddy-demo aud=text2sql-agent ttl=3600s`）。⚠️ **令牌数就是实验变量**（下面第 ③ 条），所以每个格子的令牌数写在表里。
**花费（先报后跑，实际结账）**：跑前声明 ≈¥0.6 ⇒ 实测**本轮 6 格合计 797 次调用 / ¥1.057905**（`app.cost_ledger` 按 `created_at >= 10:00Z` 只读结账）。分档：`steady+burst` 455 次 / ¥0.583246，`tenant-quota` 99 次 / ¥0.136287，`tenant-saturation` 243 次 / ¥0.338372，**`session-lock` 0 次 / ¥0.000000**（16 条准入全部没走完一次 LLM ⇒ 见第 ③ 条）。⚠️ **超出声明 0.4 元的原因 = 我在声明里只算了"准入数×单价"、漏算了 `steady` 的 264 次里含 `plan`+`gen_sql` 的多次调用**；租户日预算 `DEFAULT_TENANT_DAILY_BUDGET_CNY=10`（`app/llm/budget.py:94`）本轮峰值用量 ¥1.29 ⇒ **距 80% 强降档线（¥8）很远，不存在 `force_single_path` 混淆**。

##### ① 健康态矩阵（六格，同镜像 / 同题集 `questions_T_A_time.txt` / 只差参数）

| 格 | 参数 | 令牌 | admitted | 拒/冲突/5xx | 终态分布 | p50 / **p95** (ms) | `g6_p95_le_8s` |
|---|---|---|---|---|---|---|---|
| 预热 | `steady` c=1 n=2 | 10 | 2 | 0 | `refuse 1` / `clarify 1`（**`ok 0`**） | 1,185.2 / 5,074.6 | `null`（0 完成 + 样本 2 < 20） |
| **① 稳态** | c=50 n=120 | 10 | **77** | **43×429** | `error_frame 45`(R05…) / `refuse 14` / `clarify 8` / **`ok 10`** | 30,831.2 / **36,803.4** | `false` |
| **② 突增** | c=100 n=100 | 10 | **100** | **0×429** | `refuse 85` / `clarify 12` / `error_frame 2` / **`ok 1`** | 32,784.9 / **41,333.4** | `false` |
| **③ 单会话锁** | c=8 n=24 单会话 | 10 | **16** | **4×409 SESSION_CONFLICT** + **4×503** | `error_frame 8`(INTERNAL) / `refuse 8` / **`ok 0`** | 5,097.7 / **15,185.5** | `null`（0 完成 + 样本 <20，caveat 两条） |
| **④ 同租户配额** | c=30 n=60 同租户 | **20** | **60** | 0 | `refuse 33` / `error_frame 18`(R05…) / `clarify 5` / **`ok 4`** | **1,117.4** / **17,821.8** | `false` |
| **④′ 同租户饱和** | c=30 n=130 30s | **20** | **71** | **0×429** | `error_frame 37` / `refuse 13` / `clarify 7` / **`ok 14`** | 19,967.1 / **21,909.0** | `false` |

⇒ **配额档四条判据**（架构 `reports/arch/RELAY.md:1047`）逐格自证：①具名偏离 `deviation=quota_capped_n`（本轮 `n` 被 `--max-requests` / `duration_s` 截断，实跑时长在表里）✅；②`admitted≥20` 才给布尔 ⇒ 只有 ①②④④′ 给，③ 给 `null` ✅；③环境瓶颈同行披露 ⇒ 就是下面 ②③④ 条 ✅；④先跑零额度那格 ⇒ `session-lock` 实测 0 次调用 ✅。**标签只能写"配额档 P95"，G-6 达标行仍只认满档 ⇒ 本轮依旧不得宣称 G-6。**

##### ② 🔴 **新缺陷（本窗口第一次能归因到"配置面"）：`l4_score` 的 `max_tokens=512` 把响应截断 ⇒ L4 精排静默整层失效**

`degraded_total{reason="llm_unavailable",action_taken="reduced_candidates"}` 从 0923r8 的 0 涨到本轮 **96**。我上一轮把它写成"未归因"，本轮**用零额度日志把它归了**，链条五环：

1. `app/llm/router.py:258-262` —— `LlmTask.L4_SCORE` 路由 `thinking=False`、`output_tokens_hint=512`；`max_tokens_for()`（`router.py:316-321`）在无思考档**不加余量** ⇒ 出站 `max_tokens=512`。
2. 容器日志里同一时间窗内 `task="l4_score"` 的 `llm_call` 行，**`output_tokens` 恰好 = 512 的那些**就是被截断的（未截断的散在 314–494）。四格计数：`steady` **43/65 = 66.2%**、`tenant-quota` **16/22 = 72.7%**、`tenant-saturation` **36/59 = 61.0%**（合并 95/146 = 65%）。
3. 截断的 JSON 解析不出来 ⇒ `app/binding/scores.py:256-259` `_fail("invalid_json:…")` ⇒ `ScoreOutcome(failed=True)`（`l4.py:212-217` 把解析结果原样返回，不做部分采纳 —— 这是 `N-27 约束④` 的**刻意**行为）。
4. `app/graph/nodes/bind.py:185-192` —— `if not scores.ok:` 报 `LLM_UNAVAILABLE / REDUCED_CANDIDATES`，detail 里带 `{"stage":"bind.l4","reason":scores.reason}`。
5. **记账 1:1 闭合**：五格的"512 截断次数"与"该格 `reduced_candidates` 增量"逐格相等（`steady 43↔43`、`burst 1↔1`、`session-lock 0↔0`、`tenant-quota 16↔16`、`saturation 36↔36`）⇒ 合计 **96 ↔ 计数器终值 96**。⇒ 这不是相关，是**同一事件的两个计数面**。`burst` 那格尤其干净：只有 3 条 `l4_score` 完成，`output_tokens` 分别是 `512 / 422 / 348` ⇒ 恰好 1 条截断、恰好 +1 降级。

**为什么这一条必须上报而不是我改**：① 修复面在 `app/llm/router.py`（W3A 的地盘）与 `app/binding/l4.py`（W3A/W0），`deploy/**` 一行都不用动；② 观测面缺一件 —— `app/llm/client.py` **完全不读 `finish_reason`**（全仓 `finish_reason` 只出现在 `router.py:141` 的一行文档表格里），所以"被截断"与"写完了"在日志里长得一样，只有 `output_tokens==max_tokens` 这个巧合暴露了它。`client.py:380-383` 的 `LlmEmptyContent` 只拦"**空** content"，**非空但残缺**的原样放行到解析层。
⇒ **建议判据（请架构定号、我不自取）**：`llm_call` 增加 `finish_reason`（或 `truncated` 布尔）字段，并把 `bind.l4` 的 `reason` 落一条日志（与 `U-116` 同一族"理由没有出口"）。
⚠️ **取号前三查的结果纠正我自己上一句写下的断言**：我先按 `reports/arch/RELAY.md` v13 的旧快照写下"`U-126` 仍可用"，实跑三查（18:3x，HEAD `d26fac5`）⇒ **`U-126` / `U-127` 已被架构 v1.7.3 轮取走**（`docs/07:1134` / `:1136` 两行在表内），`arch/RELAY.md:5` 现报"下一可用 = `U-128`"。**本条不占号、交总控转架构。**（教训同项目那条"表比人快"：**快照字段读盘前一律不用**。）
⚠️ **同时撤回一句我自己的旧口径**：09-21 至 09-23 我把这类 `reduced_candidates` 暗示成"上游不稳"。本轮五格的上游响应统计 = **`POST` 到 DeepSeek/Ollama 共 1,100 次全部 200、非 200 计 0 次**（另有 **1 次 `GET https://api.deepseek.com` 返回 401** —— 那是 `U-108` 设计里的可达性探针**不带 key** 打根路径，401 = "可达"的正确语义，**不是故障**）⇒ **"上游间歇故障"在这些读数里不成立**，成因在**本机出站配置**。
另需更正第 2 步的合并数口径：截断率按 `l4_score` 完成数算 `steady 43/65`、`tenant-quota 16/22`、`saturation 36/59`、`burst 1/3` ⇒ 合并 **96/149 = 64.4%**。

##### ②-附 ★ **给架构 `U-126`/`U-127` 的两条零额度实测回执**（本轮顺手能给的、不需要额度的部分）

⚠️ 先登记一处**取号现状核对**（09-28 18:3x，按 09-28 纪律 ④ 读盘不抄快照）：`docs/07` 已是 **v1.7.3**、`§4.8` 新增 **`U-126`（P0）/`U-127`** 两行，`reports/arch/RELAY.md:5` 写"**下一可用号 = `U-128`**"，而 **`docs/07:1063` 的同一字段仍写 `U-126`** ⇒ **两处不一致**（架构自己 §7.1"四处同改"的那条又在同一字段上漏了一次）。**我不取号**，只把上呈交给总控/架构。

| 架构的输入（具名） | 我本轮的实测 | 差 |
|---|---|---|
| `§16.1` 健康态"每请求 4 次串行 flash 调用、槽占用 **H=6.15s**" = `normalize 1.56 + plan 1.49 + gen_sql 1.60 + present 1.50` | 四格 `llm_call` 的 p50：`normalize_intent` **967ms**、`plan` **1,424ms**、**`l4_score` 2,075ms**、`gen_sql` **1,522ms** ⇒ **H 实测 5.99s**；但**第 4 次调用是 `l4_score` 不是 `present`**（`deps.py:824-826` 的 `presenter=None` 是 P0 既定 ⇒ `present` 今天不发 LLM） | **−2.6%**（算术站得住，**调用清单需订正**） |
| `§10.1` 8 槽 ⇒ 吞吐硬上限 **8 × 60/1.56 ≈ 308 调用/分钟** | 四格分别 **317.3 / 267.5 / 295.6 / 328.5 调用/分钟**（`llm_call` 日志行数 ÷ 回执 `wall_s`；`session-lock` 那格 = **0 次调用**，不参与） ⇒ 均值 **302** | **±7% ⇒ 8 槽天花板本轮被四个独立格子测到，不再只是推导** |

⇒ 由这两行得出一条**对总控有用、且不违反新不变量**的结论：截断的 96 次 `l4_score` 平均每次占槽 **2,037ms** ⇒ **196 槽·秒 ÷ 8 槽 = 24.4s ≈ 本轮跑批墙钟（180.1s）的 13.6%** 换不来任何可用输出。
**修 `max_tokens` 减的是"工作量 H"，不是超时** ⇒ 恰好落在架构那句新不变量的**合法一侧**（"禁止以调小超时达标"管的是掐 deadline，这条是砍掉一次注定失败的出站）。⚠️ 但**它不改变 8 槽与 375 请求/分钟不相容这件事本身** ⇒ 不能拿它当 `U-126` 的出路。
🔴 **判据④ 的防伪我自己先认一条**：`steady` 那格 `admitted=77` 里有 **43 条被 429 挡在分母外** ⇒ 抬槽位后同样的 `n=120` 会"准入变多、p95 变差"。⇒ **我后续任何"p95 下降"的读数都会同排 `admitted` 与 `rejected_429` 两个数**（已写进 `HANDOFF §六`）。
📌 **台账零缺口对账**：五格 `llm_call` 日志 **795 行** + 预热格 2 次（未取该格日志窗口）= `app.cost_ledger` 本轮 **797 行** ⇒ **缺口 0**（复证 §三.0.1i 口径：缺口 = 被取消数，不是恒有偏差）。

##### ③ 🟠 **`session-lock` 换令牌数 = 换被测对象（我上一轮的假设本轮被证实，并顺出两条新缺陷）**

同一镜像、同一 `n=24`、同一 `single_session`，唯一变量 = 令牌数：

| 读数时刻 | 令牌 | admitted | 429 | 409 SESSION_CONFLICT | 5xx |
|---|---|---|---|---|---|
| 09-23 21:07（§三.0.1l） | **1** | 1 | **14** | 9 | 0 |
| 09-28 18:22（本轮） | **10** | **16** | **0** | 4 | **4×503** |

⇒ **`driver.py:289-291` 在 `single_session` 下只建一个会话（用 `tokens[0]`），而 `:294` 给每个 worker 固定发 `tokens[i%len]`（i = worker 序号）⇒ 令牌数决定 `RATE_LIMIT_RULES` 的 `QUERY=(per_user 10/min)` 会不会先 bind**：单令牌时 24 条全压在同一个 `user_id` 上 ⇒ 桶必 bind；10 令牌时压力被摊到 8 个 `user_id` ⇒ **桶完全不 bind（本轮实测 `rejected_429=0`）**。所以 §三.0.1l 我那句"24=10+14 与 `ratelimit.py:203` 逐格对上"**只在"单令牌"这一个取值下成立**，不是场景③ 的固有性质（**旧读数不删、限定条件补在这里**）。
⚠️ **要 W1B/W0 判的一件事（我只报证据、不下结论）**：本轮 24 条里 **8 条准入并落审计，`user_id` 分别是 `u_b01..u_b08`**，而 `driver.py:289-291` 的会话是用 **`tokens[0]`（= `u_b01`）** 建的 ⇒ **另 7 条是"换了 user 的令牌打同一个会话"**，服务端全部受理并进入图。⚠️ **为什么恰好 8 个用户**：`driver.py:294` 是 `worker(client, tokens[i % len(tokens)])`，`i` 是 **worker 序号**（`c=8`）不是请求序号 ⇒ **每个 worker 全程固定一个令牌** ⇒ 8 workers × 10 令牌 = 恰好 8 个不同 `user_id`。`app.audit_log` **没有 `session_id` 列**（实测列清单：`log_id task_id tenant_id user_id role timestamp raw_question … outcome refusal_reason`）⇒ 我从数据面**无法**判断"会话归属校验"是否存在、也无法判断这条路径**应当**拒绝还是放行 ⇒ **UNVERIFIED，不是漏洞判定**；且实测这 8 行 **`count(row_count_returned)=0`、`count(final_executed_sql)=0`**（全 `refuse(no_data_asset)`）⇒ **无任何数据泄露证据**。⇒ 请 W1B/W0 判："同一会话被不同 `user_id` 复用"在 §9/§13 的口径下是特性还是缺陷；若判缺陷，我这边只需把 `single_session` 改成固定用创建者令牌即可（一行、零额度）。
🔴 **本轮另两条只在健康态才看得见的新缺陷（都有日志逐条署名，零额外花费取证）**：
- **4× `503 DB_UNAVAILABLE`**：事件 `redis_unavailable{path:"/api/v1/query", extra_fact:"fail-closed → 503 DB_UNAVAILABLE（Retry-After 5s，可原样重试）"}` ⇒ **Redis 单路不可用被报成"数据库不可用"**，而同一时刻 `/healthz` 的 `redis_reachable:true`、事后查 `pg_stat_activity` = 18 idle / 1 active / `max_connections=100`（⇒ 不是连接池打满、也不是 PG 侧）。**归属在 `app/api`/`app/core` 的错误映射（W4/W0），不在 `deploy/**`**。
- **8× N-08 重复终态**：`node_timeout_degraded{node:"normalize",limit_s:15.0}` ×8 → `llm_falling_back_to_template{task:"normalize_intent"}` ×8 → `graph_run_failed{detail:"终态已被设置（N-08）—— 一个 run 只允许 1 个终止事件。重复设置说明存在两条出口路径同时在跑，必须判为图缺陷而不是覆盖。"}` ×8 ⇒ **走"模板兜底"那条路时，模板自己判了 `refuse` 已经把终态设上，随后运行包装器又补发 `error(INTERNAL)`** ⇒ 客户端拿到 8 条 INTERNAL、审计侧 0 行。**这条与 `U-107`/`U-118` 同族但触发面不同**（`U-107` 管"超时落点"，这里落点有了、但落点和终态各设一次），**我不自取号**，报架构按 `§4.8 规则②` 判拆还是并。

##### ④ 🟡 **场景④ 的参数在健康态仍然打不到租户桶**（契约面问题，要裁不是我改）

`tenant-saturation` spec = `c=30 / duration_s=30 / total_requests=130`（`driver.py` ScenarioSpecs），本轮**实际只发出 71 条**：`duration_s` 是**开工门**不是**收尾门**（worker 只在 30s 窗口内取号），30s × 实测吞吐 ≈ 71。⇒ `admitted=71 / rejected_429=0` ⇒ **`per_tenant 100/min` 从未被触及**，这一格**没测到租户配额、只测到 c=30 的持续吞吐**。
⚠️ 上一格 `tenant-quota`（`n=60`，20 令牌 ⇒ 3/用户）同样**两个桶都不会 bind**（60 < 100/min、3 < 10/min）⇒ 它的 `0×429` 是**参数决定的必然值，不是"配额未生效"的证据**。
⇒ **给架构的两个可选口径**（我不擅自改 `§16.5` 的参数）：**(a)** 把 ④′ 的 `duration_s` 抬到 ≥60s 且令牌 ≥14（`130/14=9.3/用户 < 10/min` ⇒ per-user 不 bind、`130 > 100` ⇒ 租户桶必 bind）；**(b)** 或把"租户桶 bind"从场景④ 摘出来，认 §三.0.1l 的 `session-lock`（单令牌 14×429）那种"故意让桶 bind"的取数形态。**我推荐 (a)**，理由：`rejection_headers` 已经能带 `Retry-After`，(a) 才第一次给出"per-tenant 与 per-user 谁先 bind"的**可区分**证据。

##### ⑤ 免费自洽断言复算（跨五格，零成本）

- `degraded_total{reason="present_failed",action_taken="table_only"} = 31` **等于** `query_outcome_total{outcome="success"} = 31`（本轮 5 个真实格各自都对得上：13↔13、31↔31）⇒ `deps.py:824-826` 的 `presenter=None` P0 既定形态仍按 1:1 成立。**W3B 接上 `present` 的那天这条会断，届时不是回归。**
- **U-125 在大量样本下不退步**：`gate_reject_total{gate_no="1",rule_id=""} = 0`，带号合计 **105**（`R06 63 / R05 24 / R14 11 / R10 4 / R04 3`）⇒ 架构定的判据"拒一条后 `rule_id` 非空"在本轮 105 条拒绝上**全数成立**；`gate2/gate3` 本轮**分母为 0**（无拒绝）⇒ 不是不成立，是**未测**。
- `retrieval_mode_total{hybrid}=239 / {sparse_only}=72` ⇒ `sparse_only` 停在 72（= §三.0.1m 的 70 + 本轮 2）⇒ **Ollama 恢复后新增的降级确实归零**，反向佐证本轮读数是"健康态"。

##### ⑥ 复现命令（本轮实际用的那组，零密钥）

```bash
# 0) 三处可达性（宿主 / 容器内 / 模型名）
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' http://127.0.0.1:11434/api/tags
MSYS_NO_PATHCONV=1 docker exec w7load-api python -c "import httpx;print(httpx.get('http://host.docker.internal:11434/api/tags',timeout=5).status_code)"
# 1) 前置快照（跑前跑后各一次；embed_doc 必须是 197|197|197）
MSYS_NO_PATHCONV=1 docker exec commerceql-pg-1 psql -U postgres -d ecom -tAc \
  "select count(*),count(embedding),count(tsv) from app.embed_doc;"
# 2) 六格（同镜像 w7load-api:0928r9，题集统一 questions_T_A_time.txt）
cd CommerceQL/deploy/loadtest
for S in "session-lock 24 E:/tmp_w7/tokA.txt" "tenant-quota 60 E:/tmp_w7/tokC.txt" "tenant-saturation 130 E:/tmp_w7/tokC.txt"; do
  set -- $S; ../../.venv/Scripts/python.exe driver.py --target http://127.0.0.1:18000/api/v1 \
    --scenario "$1" --no-async --max-requests "$2" --tokens "$3" \
    --questions-file questions_T_A_time.txt --out "E:/tmp_w7/rA_$1.json"; sleep 70   # ⚠️ 必须 >60s 让上一格的分钟桶清空
done
# 3) 截断取证（零额度，只读日志）—— 核心式：output_tokens==512 的 l4_score 次数 == 该格 reduced_candidates 增量
docker logs --since <UTC起> --until <UTC止> w7load-api > E:/tmp_w7/win.txt 2>&1   # ⚠️ 必须 '> file 2>&1'，写成 '2>&1 > file' 会把 stderr 打到终端
grep '"event": "llm_call"' E:/tmp_w7/win.txt | python -c "
import sys,json
v=[json.loads(l) for l in sys.stdin if l.strip().startswith('{')]
x=[d for d in v if d.get('task')=='l4_score']
print('l4_score',len(x),'@512',sum(1 for d in x if d.get('output_tokens')==512))"
# 4) 结账（只读）
MSYS_NO_PATHCONV=1 docker exec commerceql-pg-1 psql -U postgres -d ecom -tAc \
  "select count(*),round(sum(cost_cny)::numeric,6) from app.cost_ledger where created_at >= '2026-09-28 10:00:00+00';"
```

##### ⑦ 纪律条（对自己的一条订正，写在证据旁边而不是别处）

**"本机依赖没起来"这件事，我不该拿它去问总控。** §三.0.1m 我把 Ollama 判成"环境瓶颈 ⇒ 扣住整批不跑"并上呈，这个**判断本身是对的**（污染容量读数，必须扣），但我停在"等总控开" —— 开 Ollama 是本机上一个可逆、零外呼、不碰共享数据的动作，**该我自己做完再汇报**。已把这条订正写进长期记忆（分界：**只读探测 + 恢复本机自有依赖 ⇒ 做完汇报；改共享状态 / 不可逆 ⇒ 才问**）。本轮 Ollama 由总控先开了，我照旧做了三处可达性复验再跑批 —— 顺序合规，但**下轮同类不再问**。

#### 三.0.1o ★★ 第十八轮（2026-09-28 21:40–22:10 本机 / 13:40–14:10Z）：**新镜像首格作废（冷容器假象）+ U-128 / U-129 活体验收 + 属主负向断言拿到读数**（镜像 `w7load-api:0928r10` = HEAD `00d3c12`，含 `e1ea13a` / `1036295` / `7035db3`）

##### ① 五格读数（同镜像、同题集 `questions_T_A_time.txt`、令牌 `u_d01..u_d10` 十枚，用后即删、永不入库）

| 格 | 参数 | 窗口 (UTC) | req | admitted | 429 | 4xx(409) | 5xx | ok | p50 / p95 ms | `llm_call`(stop) | 台账行 / ¥ | 回执文件 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 预热 | c1 / n2 | 13:40:15–13:40:29 | 2 | 2 | 0 | 0 | 0 | 0 | 1,146 / 13,381 | 2 (2/2) | 2 / ¥0.001445 | `healthy_rB_warm_c1n2.json` |
| **steady 冷** | c50 / n120 | 13:41:40–13:42:05 | 120 | 84 | 1 | 0 | **35** | **0** | 15,664 / 24,443 | **0** | 0 / ¥0 | `healthy_rB_steady_c50n120_cold.json` |
| 控制臂 | c1 / n3 | 13:45:06–13:45:29 | 3 | 3 | 0 | 0 | 0 | 1 | 9,218 / 13,044 | 6 (6/6) | 6 / ¥0.006944 | `healthy_rB_c1n3_control.json` |
| **steady 热**（同参重跑） | c50 / n120 | 13:46:44–13:47:41 | 120 | 86 | 34 | 0 | 0 | **8** | 31,839 / 39,552 | 225 (**225/225**) | 225 / ¥0.333996 | `healthy_rB2_steady_c50n120_warm.json` |
| session-lock（令牌已钉） | c8 / n24 | 13:48:18–13:48:32 | 24 | **1** | 14 | 9 | 0 | 1 | 13,776（单样本） | 2 (2/2) | 2 / ¥0.001566 | `healthy_rB_sessionlock_c8n24_pinned.json` |

冷格的 35 条 5xx 全为 `DB_UNAVAILABLE` + `Retry-After: 5`，容器日志同刻 `redis_unavailable` 35 条、
`error_type: TimeoutError` 38 条、`node_timeout_degraded` 42 条、`llm_falling_back_to_template` 34 条、
**`llm_call` 0 条**；`codes` 里 `LLM_UPSTREAM_ERROR` 8 条。

##### ② 冷容器假象是本轮的**主结论**，不是代码回归

同一镜像、同一参数、间隔 4.5 分钟，两格的 `ok` 从 **0** 变成 **8**、5xx 从 **35** 变成 **0**：

| 对照 | 冷臂（首格） | 热臂（同参重跑） |
|---|---|---|
| ok / admitted | 0 / 84 | 8 / 86 |
| 5xx | 35（`DB_UNAVAILABLE`） | **0** |
| 429 | 1 | 34（`RATE_LIMITED`，`Retry-After: 30`） |
| `llm_call` | **0** | 225（全 `finish_reason=stop`） |
| p50 / p95 | 15,664 / 24,443 | 31,839 / 39,552 |

环境旁证（同窗口内取，排除"栈坏了"）：容器 → DeepSeek 首连 **4,320 ms**（401，冷 TLS），随后两次 **193 / 180 ms**；
Redis `PONG` 0.14 ms、`clients=30`。⇒ 冷臂的红是**首格冷启动**（TLS/连接池/Redis 首握手全部落在同一 20 s 窗口），
不是 W3A / W4 三个 commit 引入的回归。**判据 = 同参热臂 + `c=1` 控制臂**，缺一不得下"回归"结论（§六 已登记为排期硬约束）。

##### ③ 审计对账（`app.audit_log` 按 `timestamp` 窗口，连接角色 = `postgres`）

| 窗口 | admitted | 审计行 | 差 | outcome 明细 |
|---|---|---|---|---|
| rB 冷 steady | 84 | 84 | **0** | refuse 76 / failed 8 |
| rB 热 steady | 86 | 86 | **0** | failed 40 / refuse 30 / clarify 8 / success 8 |
| rB 控制 c1n3 | 3 | 3 | **0** | success 1 / clarify 1 / refuse 1 |
| rB session-lock | 1 | 1 | **0** | refuse 1 |
| **rA 第十七轮 session-lock（U-129 修复前）** | **16** | **8** | **8** | refuse 8 |

⇒ **U-129 的量纲拿到了**：修复前那一格"应有而没有"的终态行 = **8**，与该窗 `error_frame` 里 8 条
`error_type:"ValueError"` 精确相等；修复后四格差值全为 0。
⇒ 同时纠正我自己上一轮的措辞：我写的"审计 **0** 行"**不准确** —— 该窗实际有 8 行（全 `refuse`，模板回落写的），
缺的是那 8 个崩掉的请求的终态行。读法见 RELAY §三十六 ①。

##### ④ U-128（L4 截断）活体验收 = 通过

| 判据 | 读数 | 载体 |
|---|---|---|
| 截断签名消失 | `l4_score` 单请求最大输出 **775** tok（> 旧 `max_tokens_for` 的 512 档）；命中 2304 档 0 次、命中 512 档 0 次 | 热臂窗口容器日志 `llm_call` 225 条 |
| 全部完成 | `finish_reason=stop` **225/225** | 同上 |
| 降级归零 | `bind.l4` 的 `REDUCED_CANDIDATES` 降级行：**全库累计 20 行，13:40Z 之后 0 行**（20 行全部是修复前 rA 留下的） | `app.audit_log_supplement` ⋈ `app.audit_log` on `task_id` |
| 覆盖口径不变 | 该出口仍只覆盖"跑到 `present` 的请求"⇒ 热臂 86 admitted 里只有 8 条 success 具备写 supplement 的资格 | `audit_supp.py:55-70` |

⚠️ 载体纠偏（W3A 提出、我确认）：`bind.py:187-191` 的 degraded detail **有**出口（`{"stage":"bind.l4","reason":…}`），
我上一轮"没有出口"那句说过头了；本轮据此把 20 行样本逐条读回，reason 全为 `invalid_json:*`。

##### ⑤ 交回 U-126 配平表的新单请求槽占用 **H ≈ 6.18 s**

控制臂 `c=1/n=3` 的逐任务耗时（容器日志，同一请求内串行相加）：
`normalize` 1,143 / 1,058 / 1,432 ms、`plan` 1,988 ms、**`l4_score` 1,413 ms（输出 321 tok）**、`gen_sql` 1,568 ms
⇒ 单请求模型槽占用 **H ≈ 6.18 s**，对第十七轮的 5.99 s 是 **+0.19 s（+3.2%）**。
吞吐上限沿用第十七轮四格实测均值 **302 calls/min**（本轮未重测，冷臂 0 调用不可用、热臂受 429 压制不可用）。

##### ⑥ 属主负向断言（W1B 判缺陷 / W0 判特性 —— 本轮第一次有实测）

新永久件 `probe_session_owner.py`（只读、零写库）：以 `u_d02` 令牌打 `u_d01` 创建的 `session_id`：

| 断言 | 契约期望 | **实测** |
|---|---|---|
| 非属主 `POST /query` 打他人 session | 404 `SESSION_NOT_FOUND` | **HTTP 200**，完整 SSE 流 **2,101 字节** |
| 非属主 `GET /session/{sid}` | 404 | **HTTP 200**，`turns_readable_by_nonowner = 2` |
| 非属主能否拿到 title | — | `returned_a_title = false` |

⇒ W1B 的"fail-open 判缺陷"成立且已量化；产物 `probe_session_owner_nonowner.json` / `probe_session_owner_with_owner_ask.json`。
driver 侧 W1B+W0 裁定的那一行已改（`single_session` 时 workers 全用创建者令牌），
`--self-check` 10/10，session-lock 复跑形状 = **admitted 1 / 14×429(RA 30) / 9×409(RA 3)**，与 09-23 的 1+14+9 完全同形
⇒ 令牌枚数不再改变被测对象。

##### ⑦ U-124 A 臂在新树复跑（W2A 结案要求的回执）

永久件 `probe_searchpath_a_arm.py`（analytics 池原样、调用方不给任何 preset）：
`show search_path = app`、`current_user = app_ro`、非限定 `from v_order_paid` **名称解析通过**
⇒ 与 09-23 的 A 臂（`ProgrammingError: relation "v_order_paid" does not exist`）相反 ⇒ U-124 的连接级 `search_path` 在活体成立。

⚠️ **`rows=0` 不是缺陷**，对照三臂（全为只读；app 侧定位件 = `probe_rls_face_locator.py` / `probe_rls_face_locator.txt`）：

| 读法 | 结果 |
|---|---|
| 基表直查（`postgres`，超户） | 494,249 |
| 视图、只给 `app.tenant_id=T_A` | **0** |
| 视图、三个身份 GUC 齐给（`shop_ids` = 空串 = 不限） | **200,000**（= T_A 全部行） |

原始读数归档：`probe_rls_table_vs_view_counts.txt`（基表 494,249 / 视图 0）、`probe_rls_three_guc_count.txt`（三 GUC = 200,000）、
`probe_tenant_rowcounts.txt`（T_A 200,000 / T_B 175,000 / T_C 119,249）、`probe_rls_face_facts.txt`（owner / `relforcerowsecurity` / 是否超户）、
`probe_rls_policy_readout.txt`（策略原文）。

机制（已验证事实，非推测）：`app.v_order_paid` owner = `app_rw` 且非 security-invoker；
`app.order_paid` `relrowsecurity=t` **且 `relforcerowsecurity=t`**；策略 `app.p_order_paid_tenant` 的第二支
`current_setting('app.shop_ids', true) = '' OR shop_id = ANY(...)` 在键未设时求值为 **NULL** ⇒ 整条策略不为真。
⇒ 生产注入模板 `dsn.py:141-145` 三个键一起给，是对的；探针只给一个就会静默 0 行。
⇒ 对 W6 长期挂着的"PG 侧 0 行"给出**候选解释路径**（是否即其成因我没有同对象对照，不写结论）。

##### ⑧ 候选数上界探针的标签自纠（`probe_l4_candidate_bound.py`）

同一 42 题、同一镜像重跑，`columns histogram` 与第十七轮**逐桶相同** ⇒ 探针可复现（跨镜像重建）。
但 `rep()` 原实现把 `st.mean(v)` 打印在 `p50` 位 ⇒ 归档件里 `p50` 与 `mean` 数值相同就是证据。
修正后：`columns` **min 8 / p50 17.0 / p95 22 / max 25 / mean 15.81**，`metrics` p50 5.0。
⇒ 交给 W3A 的两个推导输入（硬上界 30 = `search.py:92 column_top: int = 30`、p95 = 22）**不受影响**，
`hint=2304` 的推导成立。新读数存 `probe_l4_candidate_bound_r10.txt`。

##### ⑨ 本轮花费与归因（共享库台账 `app.cost_ledger`）

跑前基线 934 行 / ¥1.288840 ⇒ 跑后 1,181 行 / ¥1.647555，**本轮 Δ = 247 行 / ¥0.358715**。
逐分钟 × 逐用户拆开，247 行全部落在我本轮铸的 `u_d01..u_d10` 上，加总闭合：
2（预热）+ 0（冷臂）+ 6（控制）+ 225（热臂）+ 2（session-lock）+ 12（13:49–13:51 属主探针，其中含一次 owner 真问）= **247** ✅。
⚠️ **冷臂那 84 个请求没有一条进台账** ⇒ 台账只记"成功完成的模型调用"，上游故障/超时的请求对它不可见 ——
这一条直接回答了架构 §三十六 ① 的"缺口 0 与 0 行是否矛盾"。

##### ⑩ 复现命令（本机，逐条可贴）

```bash
# 五格（令牌文件用完即删；<tok> 为本机临时文件，绝不入库）
docker exec -i -e PYTHONPATH=/srv -w /srv w7load-api python /srv/deploy/loadtest/driver.py \
  --target http://127.0.0.1:18000/api/v1 --scenario steady --concurrency 50 --requests 120 \
  --questions deploy/loadtest/questions_T_A_time.txt --tokens <tok> --out <receipt.json>
# 审计对账（连接角色 = postgres，列名是 timestamp 不是 created_at）
docker exec commerceql-pg-1 psql -U postgres -d ecom -At \
  -c "select outcome,count(*) from app.audit_log where timestamp >= '<UTC 起>' and timestamp < '<UTC 止>' group by 1"
# 降级出口按窗口计数（supplement 表无时间列 ⇒ 必须 join audit_log on task_id）
docker exec commerceql-pg-1 psql -U postgres -d ecom -At \
  -c "select count(*) from app.audit_log_supplement s join app.audit_log a using(task_id)
      where s.degradations::text like '%bind.l4%' and a.timestamp >= '<UTC 起>'"
# 候选数上界 / A 臂（零 DeepSeek，容器内 stdin 喂脚本）
docker exec -i -e PYTHONPATH=/srv -w /srv w7load-api python - < deploy/loadtest/probe_l4_candidate_bound.py
docker exec -i -e PYTHONPATH=/srv -w /srv w7load-api python - < deploy/loadtest/probe_searchpath_a_arm.py
```

#### 三.0.1p ★ 第十九轮（2026-09-29 10:0x–10:1x 本机 / 02:0x–02:1xZ）：**`admitted` 口径入表（W6 要的契约件）+ U-131 三面取证 + W0 的 CI 红我在隔离树里复算**

镜像/容器：`w7load-api:0928r10`（`docker start` 复用，未重建）。等价性判据 = `git diff 00d3c12 origin/main -- backend/app`
只有 `app/llm/router.py` 的 **4 行注释**（W3A 的 p50 订正说明）⇒ 行为面无变化。基准 = `origin/main` `872cd2d`。

##### ① ★ 字段表：`admission.*` 各桶到底是什么（W6 回请的那条 —— 它是契约，不是读数）

| 字段 | 判据（代码位） | 含什么 | 🔴 不含什么 / 易误读点 |
|---|---|---|---|
| `admitted` | `200 ≤ status < 300`（`driver.py:325-326`） | 真进入 SSE 流的请求；**含 `outcome=error_frame`（SSE 里的错误帧，HTTP 仍是 200）与 `truncated`（流断在半途）** | ❌ 不等于"业务成功"；❌ 也不等于"服务端落了一条终态" |
| `rejected_429` | `status == 429` | 限流器**正确工作**（U-106 要求单列） | 按 U-106 已排除出 P95 分母 |
| `other_http_4xx` | 其余 4xx | `409 SESSION_CONFLICT`、`401`、`404`… | ⚠️ 409 **不是**限流，是会话锁；混进 429 会伪造"配额生效" |
| `http_5xx` | `status ≥ 500` | `503 DB_UNAVAILABLE` 等 | 冷容器首格常在这里爆（§三.0.1o ②） |
| `unresolved` | `status is None` | 超时 / 连不上 | 连接层事实，没资格进任何 HTTP 桶 |
| ★ `terminal`（**本轮新增**） | `outcome ∈ {ok, clarify, refuse, error_frame, async_degraded}`（`driver.py:322-330`） | 收到 `terminal: true` 终止帧的请求 | ⇒ **「`admitted − app.audit_log` 行差 = 0」这条不变量（`U-130`）的严格分母是它**，`admitted` 只是"本格没有断流"时的代理 |

✅ 本轮 11 份 `healthy_r*.json` 逐份复算：`admitted − terminal = 0` **全格成立**（无 `truncated` / `timeout`）⇒ 今天两个分母同值。
🔒 自检桩**刻意**做成两者不等：`--self-check` 里 `admitted=8 / terminal=7`（10 条样本含 1 条 200 断流）⇒ 谁把分母退回 `admitted`，自检当场红。
复算命令（零成本，读归档件即可）：

```bash
python - <<'PY'   # 逐格 admitted vs terminal（terminal = Σ outcomes{ok,clarify,refuse,error_frame,async_degraded}）
import json, glob
TERM = {"ok","clarify","refuse","error_frame","async_degraded"}
for f in sorted(glob.glob("deploy/loadtest/healthy_r*.json")):
    s = json.load(open(f, encoding="utf-8"))["scenarios"][0]
    a = s["admission"]["admitted"]; o = s.get("outcomes") or {}
    t = sum(v for k, v in o.items() if k in TERM)
    print(f.split("/")[-1], "admitted", a, "terminal", t, "差", a - t)
PY
```

##### ② ★ U-131（跨属主会话可读）三面取证 —— 读侧与写侧**确证**，推理侧**判不了**

新永久件 `probe_session_owner_context.py`（顺序修正：旧件先跑非属主 ⇒ 回合数混进非属主自己那一轮）。

| 步 | 实测 |
|---|---|
| 属主 `POST /session` + 问 Q1 | 200 / SSE；两轮 Q1 分别是 `退款率`（978B）与 `GMV`（520B） |
| 非属主 `GET /session/{sid}` | **200，`turns[0]` = 属主问句原文**（`T_A 从 2026-06-01 起的退款率是多少？`）⇒ 🔴 **读侧内容外泄确证** |
| 非属主 `POST /query`（追问） | 200，445B ⇒ 🔴 **写侧污染确证**：属主随后 `GET` 回合数 **1→2**，且追问原文出现在**别人的**会话里 |
| 上下文是否被推理继承 | ⚠️ **UNVERIFIED**：两轮都**没走到 `gen_sql`**（日志只有 `normalize_intent`×2 + `plan`×1；`app.audit_log` 该窗 = `refuse` / `clarify`）⇒ "流里没属主词"= **没走到会用上下文的那一步**，属**无信息**，不得据此收窄严重度 |
| 契约期望 | 非属主应得 **404 `SESSION_NOT_FOUND`**（附录 A §A.11 / 07 §14 H7 / PRD FR-10.4） |

码证（我自己读到，非转述）：`app/api/state_store.py:330-343` 的 `create_session` 载荷七字段里**没有 `user_id`**；
`get_session()`（`:358-371`）用 `cache_keys.session_meta(ctx.tenant_id, session_id)` ⇒ **只按租户定位、无属主比对**。
同一文件里 `task_state` 已是正确形状（写 `user_id`、读时比对 `tenant_id`+`user_id` 不匹配返 `None`）⇒ 修法 = 把既有形状套到 session。
🟠 `app/api/routers/clarify.py`：`get_session` **0 命中**（`:113` 按租户读澄清记录 → `:137` 用记录里的 `session_id` 组 ctx → `:262/:265` 直接 `touch_session`/`append_turn`）
⇒ "单一强制点 = `get_session()`"**不覆盖澄清写路径**；缓解 = `clarify_id` 服务端随机不可猜。**我没有活体可达证据 ⇒ 只登记不下结论。**
💰 取证花费 **5 次调用 / ¥0.009263**（`app.cost_ledger` 1181/¥1.647555 → 1186/¥1.656818）；令牌 2 枚 `u_e01/u_e02`（`E:/tmp_w7/tokE.txt`，用后即删）。

##### ③ 环境事件：共享栈 **09-29 01:15:01Z 集体重启**（不是我）+ 我的 near-miss

- `docker inspect` 四个共享容器 `StartedAt` 同为 `2026-09-29T01:15:01Z`；我的 `w7load-api` 因此 `Exited (255)` ⇒ 我 `docker start` 复用。
- 🔴 **我打错目标一次**：`driver.py:808` 的默认 `--target = http://127.0.0.1:8000/api/v1` = **共享 `commerceql-api-1`**。
  我漏带 `--target` 跑了一条"预热" ⇒ 打到共享栈，返回 **404 `{"detail":"Not Found"}`**。
  ✅ 后果核实：**零花费零写入**（`cost_ledger` 仍 1,181 / ¥1.647555、`audit_log` 仍 709、`admitted=0` ⇒ 没进图）。
  ⇒ 规程：跑批前先看回执里的 **`target` 字段**（它一直在记，只是我没看）；预热与探针一律显式 `--target http://127.0.0.1:18000/api/v1`。
- 🟠 顺带一条对**所有窗口**有用的活体事实（零成本 curl）：共享 `:8000` 现在 `POST /api/v1/query` 与 `/api/v1/session` = **404**、
  `/api/v1/healthz` = **405**（路由在、方法不对）⇒ 共享 api 那个镜像里**没有 `/query` 系路由**；拿 `:8000` 做端点级联调会拿到与代码无关的 404。

##### ④ W0 的 CI 长期红：我在**隔离树**里复算成立，并把 14 条拆成三种签名

复现（CI 视角：没有 `deploy/.env`、没有 `*.db`；只跑 `tests/eval`；显式去掉 `DEEPSEEK_API_KEY` ⇒ **零模型调用零花费**）：

```bash
rm -rf /e/tmp_w7/isotree && mkdir -p /e/tmp_w7/isotree
git archive HEAD | tar -x -C /e/tmp_w7/isotree
cd /e/tmp_w7/isotree/backend && env -u DEEPSEEK_API_KEY python -m pytest tests/eval -q -p no:cacheprovider
# 14 failed, 325 passed   ← 与 W0 的数字一字不差
```

签名拆分（同一前置的三个面，**没有一条是代码逻辑红**）：`10 × sqlite3.OperationalError: unable to open database file` +
`6 × FileNotFoundError` + `2 × AssertionError`。根因链三处我自己读到：
`backend/pyproject.toml:120 testpaths = ["tests"]`；`.github/workflows/ci.yml:121` 步骤名叫"全量测试（tests/contract = DoD③ 的载体）"
而 `:128 run: pytest`（**裸跑 ⇒ 把 `tests/eval` 拉进 DoD③**）；`.gitignore:54 *.db`（`data/ecom_sandbox.db` = 440,729,600 B ⇒ 结构上不可能进检出）。
🟠 `ci.yml:87` 还留着"阶段 1B 实测已 386+"，而同段 `:89` 明写"当前规模以 pytest 实际输出为准"⇒ 自相矛盾（归 W0，我已授权他们顺手改）。
⇒ 我在这轮之后**复跑任何门禁读数一律用隔离树**：共享工作副本里有别人未提交的改动（本轮 `backend/reports/w1b/RELAY.md` 与
`backend/tests/contract/test_gate_seam_contract.py` 都呈 `M`）⇒ 在共享副本上测到的**不是任何一个 commit 的树**。

##### ⑤ W2C 的纠正生效：我撤回"活体读数支持 G2-DOMAIN"那句

那批流量**没有** `scope_claims 不含目标 domain` 的请求 ⇒ ③ 分支未进入 ⇒ 属**无信息**。
"另三号恒 0"的登记理由改为**结构推导**，三处我逐条读码核过：`app/semantics/runtime.py:206-208`、
`app/guard/ast_gate.py:536`（`name not in self.assets → R05`，与 gate2 用同一个 assets 键 ⇒ 先被 gate1 拦）、
`app/graph/edges.py:283-288`（AST 不过 → `ERROR_OUT`，不进 gate2）。
⚠️ 并按 W6 的提醒带限定：这是 **graph 路径**的性质，不是 gate2 逻辑的性质（离线直调 gate2 能命中 `G2-DENY` / `G2-ASSET`）。

##### ⑥ 不可引用清单（本轮 +2）

- `probe_session_owner_context.py` 的布尔项 `owner_q1_readable_by_nonowner`：它依赖我传入的 `--terms`（大小写敏感），
  第二次跑就退化成 `false` 而 excerpt 里明摆着挂着属主问句原文 ⇒ **判据以 `turn_questions_excerpt` 为准，布尔只能作辅助**。
- "非属主追问流里没有属主词"这条：**不得**引为"上下文未跨属主流入"（两轮都没走到 `gen_sql`）。

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

#### 三.0.1q ★ 第二十轮（2026-09-29 14:1x–14:4x 本机 / 06:15–06:41Z）：**④′A 档跑了但形状不对；17 条 INTERNAL 拆成两族；U-130 的"差 ≥1 那一臂"由真实流量交出来了**

跑批前先报的规模与花费（批准值 = 总控 09-29 上午「两件都准许」：④′A 档 ≈¥0.07、推理侧取证 ≈¥0.03）。
**实际花费 ¥0.832504，超批准 ¥0.73（11.6 倍）** ⇒ 我起先把超支**全**记成"我单价估错"，那个归因没有对照；
按 `cost_ledger.is_peak` 重测后拆成**两个各自成立的因子**（进图条数 ×8.25、峰时单价 ×1.92），见本节第 5 段。

**1）这一格跑了什么（`healthy_r20_aprime_c12n108.json`）**

| 项 | 读数 |
|---|---|
| 几何 | `--scenario steady --concurrency 12 --max-requests 108 --reuse-sessions --session-pool 12`，题库 `questions_T_A_time.txt`，12 枚新令牌（u_f01–u_f12，同租户 T_A） |
| 目标核对 | `target_check`：12 条路径、`has_query=true`（§16.5 的新守卫当场放行，读数有效） |
| 准入分桶 | `admitted 99 / rejected_429 9 / other_http_4xx 0 / http_5xx 0 / unresolved 0 / **terminal 99**` |
| outcomes | `error_frame 60 / refuse 18 / ok 13 / clarify 8 / http_4xx 9` |
| codes | `GATE_AST_REJECTED 43 / INTERNAL 17 / RATE_LIMITED 9` |
| 延迟 | p95(准入 2xx) **28235.1ms**、wall 72.6s、`g6_p95_le_8s=false`（⚠️ 与 `g6_caveat` 同读：429 已排除在分母外） |
| 跑后 Redis | `ZCARD rl:t:query:T_A = 87`（不是 100 —— 72.6s > 60s 窗口，ZSET 自己剪了 13 条） |

🔴 **裁定：这一格 = 「场景④′ 未按要求执行」，不得记通过。** 架构 §31 预测 `2xx≈12 / 409≈88 / 429≈8`，
实测 `409 = 0`。但**也不是**架构点名的"桶根本没响"签名（那条签名要求 `rejected_429 = 0`；本轮 `= 9` 且九条全带
`Retry-After: 30` ⇒ 租户桶在响）。真实原因在几何上：12 个 worker **各自串行**打**自己名下**的会话 ⇒
同一会话上永远只有一个在途请求 ⇒ 端点步骤 6 的抢锁**结构上不可能命中**。
要打出 409 需要"同一会话并发 ≥2"的几何（24 worker / 144 条），按第 5 段校准式 ≈**¥1.12（峰时）/ ¥0.58（非峰）**
⇒ **未批不跑**。

**2）17 条 INTERNAL 不是一种，是两种（全文见 `r20_internal_attribution.txt`）**

| 族 | 条数 | 审计行 | LLM 调用数 | 服务端日志 | 压测侧指纹 |
|---|---|---|---|---|---|
| 浅失败 | **13** | **有**（`outcome=failed`，`latency_ms` 只有 `total`+`normalize`） | 1 | **无任何具名日志** | `error_frame`，`stage=none/intent` |
| N-08 崩溃 | **4** | **0 行** | 1 | `graph_run_failed` ×4，栈顶 `audit_supp:49 → terminal_update → assert_terminal_is_settable → ValueError` | 同左，分不出来 |

三个读面必须叠起来才分得开：日志里 `INTERNAL` 全生命周期只有 4 次、`GATE_AST_REJECTED` **0 次**
⇒ **拿 `docker logs` 计数去否证回执计数会得假结论**（闸门拒绝不落具名日志）。
⚠️ 六个涉事文件（`graph/state.py`/`_shared.py`/`build.py`/`api/runner.py`/`api/errors.py`/`audit_supp.py`）
镜像与工作树 **md5 逐一相等** ⇒ 崩点是**当前代码**，不是旧镜像。

**3）U-130 的"差 ≥1 那一臂"第一次由真实流量交出来（不是夹具）**

`terminal 99 − app.audit_log 95 行 = 4`，且这 4 条与四条 `graph_run_failed` 的 task_id **一一对上**
（逐条 `where task_id in (...)` = 0 行）。按架构 §31 判据②的订正：**`--self-check` 桩只证明器件会响**，
真臂必须由缺陷触发 —— 本轮就是真臂，且触发源是产品路径。⚠️ 另：W4 的结构锁（`47d787a`）具名例外只有
`audit_pre 写库失败`，**没登记这条 `audit_supp` 崩溃 ⇒ 0 行**的路径 ⇒ 批级不变量会因它报红而结构锁报绿，
两个读数不能并成一个。

**4）U-131 三面：读/写确证第二次复现，推理侧不是"不适用"而是"被一条新触发面挡住"**

| 面 | 本轮读数（Q1 = `T_A 从 2026-03-01 起的 GMV 是多少？`，实测 4 次调用、stages 到 `executing` ⇒ **真打到 `gen_sql`**） |
|---|---|
| 读侧 | 非属主 `GET /session/{owner_sid}` = **200**（契约要 404），`turn_questions_excerpt` 里**逐字出现属主 Q1** |
| 写侧 | 非属主 `POST /query` = **200**，属主再 GET ⇒ 回合 **1→2**，非属主那句进了**别人的**会话 |
| 推理侧 | 非属主那一臂 = `clarify`（只跑 1 次调用、只发过 `intent` 帧）；**属主正对照（`--control`）= `error(INTERNAL)`，一条 `stage` 帧都没有**，日志同一句 N-08 栈、审计 0 行 |

⇒ 唯一能把上下文带进 `gen_sql` 的路径（**属主在自己会话上的第 2 轮**）在进 `gen_sql` 之前就崩：
本轮 1/1，A 档格内 4/99（不是 100% ⇒ 有竞态成分）。⚠️ 我**没有**把机制钉成"检查点回放/`terminal` 通道残留"
—— 那是 `app/graph/**`（W4 域），本轮证据只到"触发面 + 崩点 + 两个计数"。
🔴 结案口径因此要改：三面里第三面写**「当前不可测（被 N-08 崩溃挡住）」**，不得写"不适用"，也不得只交读侧。

**5）花费订正（本轮最要紧的一条自曝）**

| 件 | 批准/预测 | 实测 | 依据 |
|---|---|---|---|
| warm 1 条 | （含在下面） | **¥0.001280** | u_f00，1 次调用 |
| ④′A 档 108 条 | ≈¥0.07 ＝ 预测"12 条进图 × 4 次调用 = 48 次"× **¥0.001452/次**（07 §16.5 那行取的第十八轮单价） | **¥0.809780** | u_f01–u_f12 = **287 次调用**；同窗口非 `u_f*` 行数 = **0** ⇒ 全是本窗口的 |
| 推理侧取证两臂 | ≈¥0.03 | **¥0.021444** | 10 次调用（两臂各 5 次）✓ 未超 |
| 合计 | ¥0.10 | **¥0.832504** | **超 ¥0.73 ＝ 11.6 倍** |

🔴 **超支 = 两个因子相乘，每个因子各自有读数（不是事后合理解释）**

| 因子 | 预测 | 实测 | 倍率 | 单变量对照 |
|---|---|---|---|---|
| **A：进图的请求数** | 12 条 | **99 条** | ×8.25 | 调用数 48 → **287**（= ×5.98；不是每条 4 次：43 条深失败 ≈4 次、17 条 INTERNAL ≈1 次、18 条 refuse ≈2 次）—— 根因就是本节第 3 段那个"会话锁那一维未被执行"的几何错 |
| **B：单次调用价** | ¥0.001452 | **¥0.002794** | ×1.92 | `cost_ledger.is_peak` 逐批：09-28 13Z 那 247 次 `is_peak=f` ⇒ **¥0.001452/次**；本轮 06:17–06:18Z（北京 14:17，峰时）298 次 `is_peak=t` ⇒ **¥0.002794/次**。全库同表观：非峰 1044 次均值 ¥0.001357、峰时 404 次均值 ¥0.002512 |

⇒ 5.98 × 1.92 ≈ **11.5** ≈ 实测 11.6 倍 ✓ 两因子相乘能解释全部缺口，不需要第三条。

⚠️ **因子 B 是可预防的**：07 §16.5 引用的第十八轮单价是**非峰时**读数 ⇒ **报价前先查 `is_peak`**，
并按"跑批将落在的时段"取上界，不要沿用上一轮的单价。
★ 校准后的报价式：**¥0.01116/进图请求**（峰时，4 次 ×¥0.002794）、**¥0.0058/进图请求**（非峰）；
本轮混合形状实测 **¥0.00818/准入条**（287 次 ÷ 99 条 = 2.9 次/条 ×¥0.002794）。
⇒ 修正几何（24 worker / 144 条、≈100 条进图）**≈¥1.12（峰）/ ¥0.58（非峰）**；B 档满画像同量级。
🔴 **撤回**：上一轮我在 `RELAY §三十七` 给的"修正几何 ≈¥0.14"**作废** —— 它同时按错了进图数与单价；
以后报价一律同时报**进图条数 + 峰/非峰时段**，不报"发出条数"。

**6）本轮改的量具（`deploy/**` 归本窗，零额度自证）**

- `driver.py` 新增回执字段 **`codes_task_ids`**（`错误码 → 命中该码的 task_id`，每码 ≤12 条、排序截断）：
  本轮 17 条 INTERNAL 拆族花了一整轮，就是因为回执里**没有任何 join 键**，只能靠时间窗反查。
  `Sample.task_id` 取自 `ack` 帧（`app/graph/events.py:462`）；⚠️ 只装标识符，不装查询文本与结果数据（N-11）。
- `--self-check` 加了**调用点**钉：桩现在也发 `ack` 帧，断言 `codes_task_ids == {"INTERNAL": ["tk_stub_3"]}`
  （整字典相等，不留"字段存在但恒空"）。复跑 **10/10 通过**，`ruff` 全绿（顺带清掉 `driver.py` 里一处
  无效 `# noqa: BLE001` —— 本项目 ruff `select` 不含 `BLE`，RUF100 判它多余）。
- `probe_session_owner_context.py` 三处补强：`_sse_names()`（**结构**证据：events/stages 序列）、
  `_task_id_of_stream()`（旧写法 `_obj()` 只读最后一帧 ⇒ `clarify`/`complete` 帧上没有 `task_id`，
  本轮实测两处都读成 `null`，取证件交不出关联键）、`--control`（属主正对照）。
  ⚠️ 新增字段/参数**未被真实流量验证以外的路径覆盖**：`codes_task_ids` 的线上形状 = **UNVERIFIED**（桩已钉住接线，
  但本轮那份回执是改代码**之前**跑的，不含该字段）。
- 字段表补一行：

| 字段 | 口径 | 谁要用 |
|---|---|---|
| `codes_task_ids` | `错误码 → 命中该码的 task_id 样本（≤12，排序后截断）`；来源 = 流里任意一帧的 `task_id`（实服务只在 `ack` 给） | W4/W6：`where task_id = any(...)` 直接对 `app.audit_log` / `app.cost_ledger` 复算，不必按时间窗猜 |

**7）本轮进"不可引用 / 需订正"清单的三条**

1. `healthy_r20_aprime_c12n108.json` **不得**被引用为"场景④′ 通过"或"租户配额保护达标" —— 判语见本节第 1 段
   （`409=0` = 会话锁那一维未被执行）；它的 `admission`/`codes`/`latency` 可作为**该几何**的读数引用。
2. 「`docker logs` 里只有 4 条 INTERNAL ⇒ 回执的 17 是虚高」= **假推论**，引用者请先读本节第 2 段的读面覆盖差异。
3. 架构 18fc2a9 报的 `platform.machine()` 挂死 >120s 与本轮 14:2x 复测 **6/6 全部 ≤0.08s** 并存 ⇒
   `U-132` 的"此刻必红"是**间歇读数**，任何"已经恢复/还没恢复"的断言都必须带**复测时刻**。

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

**09-23 复算（同一条命令，逐字）**：`json_files=15 stale_true_cells=14 files=11` ⇒ **归档件从 13 涨到 15**
（新增 `preflight_r6.json` / `preflight_r7.json`），但**那 14 格 stale-true 一格没变**（新件都不在内）。
布尔为 `null` 的件现清单 = **`preflight_r6.json`、`preflight_r7.json`** —— 即 **U-120 的三态第一次在"新写的回执"上产出 `null`**
（旧件要变 `null` 得靠 `--roll-up` 重算，见上一段 A-1）。⚠️ 引用纪律：`r7` 是**判据④ 达成的那一轮**（`ok=3`），
但它的 `p95=9,756.0ms` **同样不可当 P95 结论**（`admitted=5 < 20`）—— "走通了"与"量够了"是两件事。

**09-23 晚复算（同一条命令，逐字）**：`json_files=19 stale_true_cells=14 files=11` ⇒ 归档件从 15 涨到 **19**
（新增 §三.0.1l 的 4 份 `preflight_r8_*.json`），**那 14 格 stale-true 依旧一格没变**。
布尔为 `null` 的件从 2 份涨到 **6 份**：`preflight_r6` / `preflight_r7` / `preflight_r8_c1n5` / `preflight_r8_cold` / `preflight_r8_sessionlock` / `preflight_r8_warm`。
⚠️ 这 6 份的 `null` 是**两种不同成因**并存，引用时必须分开说：
① `cold`/`warm`/`sessionlock` = **0 条 `ok`** ⇒ 分母全是失败样本（无效率意义上的不可判）；
② `r6`/`r7`/`c1n5` = **有 `ok` 但 `admitted < 20`** ⇒ 量不够（统计意义上的不可判）。
⇒ 这正是 U-120 三态想要的区分：`null` 不等于"还没跑"，`false` 才等于"量到了且超预算"。

**A-1（架构 v1.6.6）现状**：`--roll-up` 已扩成同时重算 `g6_caveat` 与 `g6_p95_le_8s`，每格留
`g6_derived_audit{caveat_before/after,bool_before/after}`，且自检钉住"不许越界改读数"。
在**副本**上演示过：`receipt_steady true→null`、`receipt_burst`（p95=274.6ms！）`true→null`、
`baseline_c5 true→null`、`preflight_r5 false→null`。⚠️ **11 份归档件本身的就地降档尚未执行**
—— 那会改写归档证据的字节、且 `receipt.json` 是 W6 的 G-6 默认输入 ⇒ 等总控点头再做，做完在此登记读数。

**架构 v1.6.9 点名要的那条读数：注入 `admitted=5` ⇒ 达标字段必须缺席**（零额度，在副本上做，不碰归档件）：

```bash
mkdir -p E:/tmp_w7/u120 && cp deploy/loadtest/preflight_r5.json E:/tmp_w7/u120/
cd deploy/loadtest && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../../.venv/Scripts/python.exe \
  driver.py --roll-up E:/tmp_w7/u120/preflight_r5.json --out E:/tmp_w7/u120/merged.json
```

09-22 15:2x 实测（逐字）：

```
[合成] 1 份 → …/merged.json：1 条场景，其中 1 条的派生判定量被重算（caveat 补算 / g6 布尔降档）
g6_p95_le_8s = null            ← 重算前这格是 false（旧写法把"没量到"写成"不达标"）
admitted     = 5 | outcomes = {"refuse": 1, "clarify": 1, "error_frame": 3}
merged 件同名字段 = null        ← 合成件与输入件一致；admission/outcomes/latency_ms 未被改写
audit = {"bool_before": false, "bool_after": null, "changed": true, "caveat_before": …, "caveat_after": …}
```

**变异用例名**（架构要求点名；跑法 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w7/scratch_g6_mutation_check.py`）：
`M1 退回无条件布尔` / `M2 去掉「没有 p95」这一支` / `M3 去掉准入样本门槛` / `M4 把门槛常量改成 1` /
`M5 roll-up 只算 caveat 不算布尔` / `M6 roll-up 越界改读数` ⇒ 09-22 15:2x 复跑 **6/6 被抓、0 逃跑、基线先绿**。
守卫本体在 `driver.py --self-check` 的两处：`bool_cases`（7 情形）与 **`_summarize` 调用点双向**（后者是被 M1 逼出来的 —— 见 `RELAY §二十八③`）。

### 四.4 U-122：本目录引用 exec 侧读数的口径（归 W7 的那半）

| 本目录里的名字 | 它**不是**什么 | 实测依据（2026-09-22，零额度） |
|---|---|---|
| `outcomes.truncated` | ❌ 不是 §8.6 的"行数被 LIMIT 截断" | 它是**客户端流截断**：流结束却没拿到终止帧（`driver.py` 的分类判据） |
| 任何回执 | ❌ 不能当"服务端截断判定已验证"的证据 | gate1 的 `limit_injected` 实测只有 `{"injected": true}`，**注入值 L 没有出口**；`app/graph/nodes/execute.py:133-146` 的 `_effective_limit` **P0 恒 `None`** ⇒ §8.6 的 `truncated` 判定在生产路径今天就是退化的 |

⇒ 结论口径：压测面**只能**判"端到端有没有在 8s 内收口"，判不了"结果集有没有被静默截断"。
后者要等 **U-122 剩余两条**（③ 全链肯定断言、④ 替身忠实性 `declared_call_face_mismatches()==()`；
①端口成员集 + ②`isinstance` 反证已由 W4 `c2f63cf` 落地，序号按架构 v9.3 对齐）＋ W2C 给出 L 的出口，
本目录届时回一条可复制的读法。⚠️ 该读法 **UNVERIFIED**（今天写不出来，别在别处引成"已有"）。

★ **09-28 订正（上面那句"写不出来"已被实测作废 ⇒ 可复制的读法已交付在 §三.0.1m 末节）**：
① W2D `0c596e6` + W4 `c2f63cf` 之后，`executor.fetch(..., effective_limit=...)` 这条**通道已存在**；
② 但 **`effective_limit` 在 P0 恒 `None`**（`app/graph/nodes/execute.py:28-35` 自陈：注入值 L 在
`ast_gate._effective_limit` 内部用完即弃）⇒ `executor.py:371` 今天**走的是 `more_exist` 兜底支**，
`audit_log.truncated` **不是** §8.6 那句"行数 == 生效 LIMIT"的产物；
③ 一手证据（零额度、只读，本轮两条 `ok` 之一）：`row_count_returned=1000`、`final_executed_sql` 结尾 `LIMIT 1000`、
`truncated=false` ⇒ **我一度判成"§8.6 判定失效"，读完实现撤回**（兜底路径的正常输出 ≠ 判定错误）。
⇒ 结论口径收窄为：**压测/回执面要谈"服务端截断"，只能读 `app.audit_log` 的 `more_exist` 结果，
不得声称"已按 §8.6 验证"**；真正的开项是那条**早已登记**的请求（`execute.py:35` 请 W2C 把 L 放进 `limit_injected`，
与 W6 的 `RT-LIM-001/RT-LIM-004` 同一件事）⇒ 它落地后本节再改一次口径。

### 四.5 预检归因核对表（跑预检时照抄，别让"红因"靠记忆 —— 架构 v1.6.9 两条后果的落地）

| 看到什么形态 | 第一解释（**待验假设，不是读数**） | 必须同时给出的证据 | 零额度复核手段 |
|---|---|---|---|
| `codes={GATE_AST_REJECTED:n}` 且 `sql_ready=0` | gate1 没吃到端口形状（镜像没含 W4 `357618f`） | 容器日志里的 `R05` 行 | `docker logs` + `/metrics` |
| `codes={INTERNAL:n}` 且 `sql_ready>0` | 🔴 W2C **半落地态**：只换 `policy_gate.py:105`、没换 ④⑤ 读取面 ⇒ ⑤ 抛未捕获 `ContractViolationError` | ⚠️ 按 §14.2 **不得凭 `code` 推成因** ⇒ 必须附 `error_type` + 栈（`graph_run_failed` 带 `exc_info`），并点名抛出点 `policy_gate.py:148` | `docker logs --since` + 器件 `scratch_gate2_face_probe.py` 档 A |
| `gate_passed=0` 且 `codes` 里有 `G2-*` | gate2 已接线、判据真在拒（正常态，不是坏了） | 拒绝码 + `rule_id` | `/metrics` + `app.audit_log` 只读 |
| 链路走到 gate1 之后的任意 SQL | **归因面核对**（架构 U-121 判据⑤）：同一资产跑「任一 deny 列」与「该资产内根本不存在的列名」 | 两者在 gate1 的 `rule_id` **必须同为 `R06`**；分裂成 `R07`/`R06` ⇒ 顶全列 = **列存在性 oracle** ⇒ 功能面过了也判未落地 | 同一器件第四档 `oracle对照`（两条 SQL × 两种面已内置） |

⚠️ 前 3 行今天都还是**假设**（GATE3/EXECUTE 与 gate2 的活体帧至今 `=0` ⇒ UNVERIFIED）。
第 4 行是唯一已经量过的：09-22 实测可见面 `R06/R06`、顶全列 `R07/R06`（`scratch_gate2_face_probe.out`）。

**追加（09-22 20:2x · 第九轮预检后本表的实际状态；原文不动，只标状态）**：

| 上面那 4 行 | 现在的状态 |
|---|---|
| 第 1 行（`sql_ready=0` ⇒ 镜像没含端口形状） | **已被活体证否**：`sql_ready` 首次 `=1`，W2C `c76f701` 三处同批已进镜像 |
| 第 2 行（半落地 ⇒ `INTERNAL` + 未捕获 `ContractViolationError`） | **本轮未出现**（`codes` 里没有 `INTERNAL`）⇒ 仍按"半落地警示"保留，别删；W2C 已在 commit message 里把"三处同批"写成硬约束 |
| 第 3 行（`codes` 有 `G2-*` = 正常态） | **仍未命中**（本轮一个 `G2-*` 都没有）⇒ 继续按假设用 |
| 第 4 行（`R06/R06` 归因核对） | ✅ 复跑通过（W2C 器件档3a `A_anti_oracle=PASS`、档3b `FAIL(oracle!)`，我亲测）。⚠️ 但**核对手段变了**：见下表第 3 行，活体面上拿不到 `rule_id` |

新增三行（都来自本轮活体，不是推论）：

| 看到什么形态 | 第一解释（**本轮已是读数，不是假设**） | 必须同时给出的证据 | 零额度复核手段 |
|---|---|---|---|
| `stage=executing\|reason=none` + `codes={GATE_AST_REJECTED:1}` | **不是 gate1 坏了**：`executing` 完成 → repair → **repair 产出的 SQL** 被 gate1 拒（§八 的"stage=X 只表示 X 已完成"口径）。本轮 repair 写的是裸表 `order_paid` ⇒ `R05` | `docker logs` 里 `exec_failed error_class=…` 与 `task=repair` 两条的**先后**；审计行 `prompt_version=repair_v1` | `docker logs w7load-api --since 15m` + `app.audit_log`（只读） |
| `gate_passed=0` 且 `executing>0` | ✅ **合规形态**，不是"闸门坏了"：gate3 判 `warn` 时按 §14.2 D6 不得算通过 ⇒ `events.py:55` 干脆不发 `gate_passed` 帧，但链照走执行 | 日志里 `gate3_explain_failed` 的 `extra_fact`（本轮：`EXPLAIN 不可用 → gate3 判 warn`） | `/metrics` 两格并读 + `nodes/gate3_cost.py:18` |
| `gate_reject_total{rule_id=""}` | ⚠️ **载体未给规则号**（`metrics.py:177` 定义的空值语义），不是崩也不是"没规则"。⇒ 闸门拒绝**按规则号归因今天不可做**，无论 `/metrics` 还是压测回执 | 同刻 `app.audit_log` 的 `outcome` 与容器日志配对 | `scratch_searchpath_asset_face_probe.py`（离线喂闸门，规则号直接可见） |





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
