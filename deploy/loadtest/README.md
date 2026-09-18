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

## 三、前置条件核对（2026-09-18 实测，**四条阻塞**）

| # | 前置 | 实测事实 | 后果 |
|---|---|---|---|
| 1 | 被测栈有 `query` 路由 | `docker exec commerceql-api-1 grep -n include_router /srv/app/main.py` → **只有 `health.router` 一行**；`/srv/app/api/routers/` 里只有 `__init__.py` + `health.py`；带令牌 `POST /api/v1/query` 返回 `404` | 在跑的 `commerceql-api-1`（Up 4 hours）是 **W4 收口之前的陈旧镜像**。四场景 E2E **无法在当前栈上跑**；要跑得 `docker compose build api` ⇒ **重启 W6 正在用的共享栈**（未授权） |
| 2 | pgbouncer 在跑 | `docker ps` 只有 `api / redis / pg` 三个容器，**无 pgbouncer** | 断言③（后端连接 ≤30）**无对象可测**。启动它未获授权 |
| 3 | LLM 不烧额度 | `DEEPSEEK_BASE_URL` 默认 `https://api.deepseek.com`，`LLM_MODEL_FAST/STRONG` 都是真实模型 | 任何走通 `POST /query` 的请求都**花真钱**。已授权范围是"只跑不烧额度子集" ⇒ 四场景全量**不在授权内** |
| 4 | 本地模型可替代（若要零额度 E2E） | Ollama 在宿主可达，文本模型有 `qwen2.5:7b`/`llama3.1:8b`；但 `EMBEDDING_MODEL=bge-m3` **不在**模型列表里（只有 `nomic-embed-text`，768 维 ≠ `EMBEDDING_DIM=1024`） | 指向 Ollama 能零额度跑通，但：① 仍要重建镜像（回到阻塞 1）② `LLM_SEMAPHORE_FLASH=8 / PRO=2` 下 50 并发会排长队，宿主 CPU 上的 7B 延迟**既不代表生产也不代表降级**，且与 W6 抢 CPU ⇒ 拿它出的 P95 填 G-6 是**双向都可能错**的数字，**不做** |

阻塞 1 是最硬的一条：它同时挡住四场景与 pgbouncer 路线，且解开它必须动 W6 的栈。

---

## 四、必测断言 ↔ 本沙箱可判定性（§16.5"必测断言"逐条）

| 断言 | 谁产生证据 | 本轮可判定？ |
|---|---|---|
| ① 无 checkpoint 写入等待（R-10） | 需真实栈 + 真查询流；候选侧证是 `checkpoint` 表写入耗时日志 | ❌ 阻塞 1/3 |
| ② `SET LOCAL` 身份在连接复用时正确复位（ADR-09 验证③） | 连接池归 W1B，已有离线契约测试；**负载下的**复位需真实栈 | ❌ 阻塞 1（离线部分不由我重复声称） |
| ③ pgbouncer 后端连接数 ≤30 | `pgbouncer` 的 `SHOW POOLS` | ❌ 阻塞 2（无进程可问） |
| ④ P95 ≤ 8s（G-6） | 本驱动的 `total_ms.p95` | ❌ 阻塞 1/3；且见下方陷阱 |

⚠️ **④ 的口径陷阱（必须先讲清，否则这条会"自然达标"）**：
`AskOptions.async_if_slow` 默认 `true` 且 `async_threshold_ms=8000` —— 超过 8s 的查询**转异步**，
当前这条流于是**在 8s 附近正常终止**。只看 `total_ms` 的 P95，会得出"P95 ≤8s 达标"，
而它测的是**转异步的截断点**，不是查询完成时间。
驱动因此把这类样本单列成 `async_degraded`，并在回执里带 `g6_caveat` 字段。
判 G-6 必须用 `--no-async` 跑一遍（或按 `task_id` 轮询补完真实完成时间）。
⚠️ 与 W4 的对表项：`Outcome.SWITCHED_TO_ASYNC` 在全仓**只有枚举定义、无消费方**
⇒ 目前无法从 SSE 帧上区分"真完成"与"转异步"，驱动用的是"`complete` 帧带 `task_id`/`async` 键"的启发式。
已记入 RELAY。

---

## 五、跑批需要的三项授权

1. **可以重建并重启共享栈**（`docker compose build api && docker compose up -d api`），并知会 W6 取数时点；
   或授权 W7 用 `docker compose -p w7load` 起一套**独立 api 容器**（复用同一 pg/redis 网络、宿主端口 18000）。
2. **额度**：批准一次有界的真实 DeepSeek 调用量。量级估算：`steady` 50×600s 在 P95 8s 下约 3.7 万条
   ⇒ 不可接受；可行的是**缩短为 50 并发 × 60s（约 300~400 条）**并把 §16.5 的 10min 口径如实记为"未跑满"。
3. **pgbouncer**：授权启动（否则断言③永远 UNVERIFIED）。

未拿到 1 之前，本轮**不跑任何打向 `POST /query` 的批量请求**；未拿到 2 之前不跑任何**真实模型**的批量请求。
理由：这两件事分别会在 W6 正在用的栈上制造负载、和花掉无法回收的额度。

---

## 六、本轮实际执行了什么（回执）

| 动作 | 命令 | 结果 |
|---|---|---|
| 量具自检（零外呼、零额度、不起容器之外的服务） | `python driver.py --self-check` | `10/10 分类正确；样本 p95=3010.5ms（桩注入最大延迟 3000ms）`，exit=0 |
| 量具有效性变异检验（5 处注入缺陷） | `.tmp` 内脚本，逐条改驱动再跑自检 | **5/5 被抓**：计时停在第一帧 / 无终止帧算成功 / 4xx 算成功 / 百分位取最小 / 百分位恒 0 |
| 四场景跑批 | — | **未执行**（§三 的四条阻塞 + §五 的三项授权未到位） |

自检的桩**必须走真 TCP 环回**：`httpx.ASGITransport` 会把响应体先攒成 `body_parts` 再整体交回
（`httpx/_transports/asgi.py:158-185`），于是 TTFB ≡ total，"计时停在第一帧"这类量具缺陷**测不出来**
—— 这一条不是推演，是变异 1 在改造前**实测漏判**后发现的。

**G-6（P95 ≤8s）= UNVERIFIED**。本目录交出的是"仪器已校准 + 方案已定 + 阻塞已定位到具体命令"，
不是一组数字。任何把上面这行改写成"P95 达标"的报告都是伪造。

---

## 七、授权到位后的确切命令

```bash
cd CommerceQL/backend
../.venv/Scripts/python.exe scripts/mint_dev_token.py --tenant-id tenant_a --role analyst \
    --docker-container <api 容器名>       # 公钥要拷进容器：compose 没挂 JWT_PUBLIC_KEY_PATH
export COMMERCEQL_DEV_TOKEN=<上一步 stdout 的令牌>
```

```bash
cd ../deploy/loadtest
# 先确认被测栈真的有新路由（这条能挡掉"对着陈旧镜像压测"整场）
docker exec <api 容器名> grep -c "include_router" /srv/app/main.py    # 期望 ≥5
python driver.py --scenario steady --no-async --out steady.json
python driver.py --scenario burst --no-async --out burst.json
python driver.py --scenario session-lock --out lock.json
python driver.py --scenario tenant-quota --tokens tenant_a_users.txt --out quota.json
```

题库：`--questions-file` 指向**附录 C 合成数据集全量**口径的问句文件（一行一条）。
⚠️ §16.5 明文"不得用缩小数据集压测"——用 `driver.py` 内置的 5 条轮转题库跑出来的数**只能**用于量具演示。
回执文件含耗时分布与状态分类，**不含查询文本与结果行**（N-11 同源关注）⇒ 可以进仓库。
