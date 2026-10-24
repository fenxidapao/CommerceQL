# deploy —— 部署面（compose / 镜像 / 压测 / runbook / 观测）

> 这一层是**部署与运行时**，不含业务逻辑。应用怎么跑起来看这里；代码结构去 `backend/README.md`。

## 1. 目录

| 路径 | 作用 | 注意 |
|---|---|---|
| `docker-compose.yml` | 8 个服务：`pg` `pgbouncer` `redis` `api` `web` `worker` `prometheus` `grafana` | 发布端口按设计**只绑 127.0.0.1**；`worker` 服务目前**无实现**（`python -m app.worker` 模块不存在） |
| `Dockerfile` / `entrypoint.sh` | api 镜像与启动脚本 | 构建身份（镜像 ⟷ 工作树 ⟷ HEAD）是门禁取证面，改构建别忘同步 |
| `nginx.conf` | `web` 反代的 SSE 配置（`X-Accel-Buffering: no`、不缓冲） | — |
| `.env.example` | **唯一**配置模板；新增配置项必须同步（双向同步断言钉住） | 🚫 仓库不放真实密钥；`.env` 被 gitignore |
| `secrets/` | 本地 JWT 密钥对（`jwt_private.pem` / `jwt_public.pem`） | 🚫 **禁止读取/提交**；已 gitignore |
| `runbook/` | 6 份故障处置 RL-1…RL-6（审计库失败 / Ollama 不可用 / checkpoint 写慢 / 上游 LLM 故障 / 危险查询告警 / 成本异常）＋ `README.md` | 线上处置的唯一剧本 |
| `observability/` | `prometheus.yml`、`alert.rules.yml`（＋ 测试副本）、`grafana/` 面板 | 阈值改动先看 `docs/05 附录 D` |
| `loadtest/` | 压测驱动 `driver.py`、装载器 `load_synth_to_pg.py`、构建身份取证 `attest_build_identity.py`、回执 `*.json`/`*.txt`、`README.md`（**253KB 逐轮流水**） | ⚠️ 见下 §3 |
| `COMPOSE_SURFACE_DIFF_20261001.md` | 一次 compose 面差异取证 | 史料 |
| `drain_client.py` | 调 `/healthz/drain` 的下线客户端 | — |

## 2. 起停

```bash
cp deploy/.env.example deploy/.env      # 填 DEEPSEEK_API_KEY 等；DSN/端口已按 compose 服务名预置
docker compose -f deploy/docker-compose.yml up -d --build pg redis api
curl -i http://127.0.0.1:8000/api/v1/healthz/live    # 200
curl -i http://127.0.0.1:8000/api/v1/healthz         # 503 + degraded_dependencies 是设计
```

⚠️ 探针**必须带 `/api/v1` 前缀**；裸 `/healthz/*` 是 404。

## 3. ⚠️ `loadtest/` 为什么不能随便整理

1. **`README.md` 是 253KB / 2,029 行的逐轮压测流水**，而且被当作"对外抄本"与**按行号**引用（`backend/app/obs/probes.py` 指向 §三.0.2，`backend/reports/qa/evidence_*` 里有 `README.md:434` 这类行锚）⇒ **任何在文件顶部插行都会让行号锚失效**。要看结论只看需要的那一节，别整读。
2. **回执 `*.json` 不是纯产物**：`attest_build_identity.py --receipt <file>` 会**回写** build_identity；`baseline_c5.json` 被测试当基线喂真门禁；`healthy_rA_sessionlock_c8n24.json` 等被契约测试按名读取。
3. 契约测试还会对 `deploy/loadtest/**` 做整目录 `rglob` 扫描并断言文件数 —— **删/移会让测试红**。

**结论**：这个目录**只增不改**；要查某轮读数用 `grep` 定位，不要重排、不要拆分、不要在顶部加说明。

## 4. 与 CI 的关系

`.github/workflows/ci.yml` 的 7 个 job 里，`migration-gate`（alembic 迁移闸门）、`dependency-direction`（`lint-imports`）、`secret-scan`（gitleaks 全史）会直接检查本目录与仓库的交互面。改动 `docker-compose.yml` 或 `.env.example` 前先读 `docs/05 附录 D`。
