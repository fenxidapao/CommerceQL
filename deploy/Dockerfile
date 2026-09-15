# ============================================================================
# api / worker 共用镜像（07 §18.1：worker 与 api 同镜像）
# 归属窗口：W0 建骨架 → W7 接管（docs/08 §4.1）
#
# ⚠️ **清单外必需文件（Q-16）**：docs/08 §3.1 的 `deploy/` 只列了
#    `docker-compose.yml` / `nginx.conf` / `.env.example`，
#    但 compose 里的 `build:` 需要一个 Dockerfile —— 没有它 `docker compose up` 直接失败，
#    阶段 0 的 DoD①「up 后 `/healthz/live` 返回 200」在字面上无法达成。
#    因此这是"缺它就交付不了 DoD"的必要补充，内容保持最小。
#
# ⚠️ 依赖只装 `backend/pyproject.toml`（ADR-20 白名单）那一份，
#    绝不在这里另加 `pip install` —— 那会绕过"未登记不得进依赖"的规则。
#
# ⚠️ 开发期推荐形态是**后端本地跑、PG/Redis 在容器**（07 §3.4 E-1），
#    本镜像服务的是"类生产形态"，W7 还会按需调整（用户隔离/只读根文件系统等）。
# ============================================================================

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY backend/pyproject.toml ./

# 先装依赖、后拷代码 —— 改代码不会让依赖层缓存失效（构建时间差一个数量级）
RUN pip install --upgrade pip && pip install .

COPY backend/app ./app

# 沙箱库目录（评测用 SQLite，附录 D §D.4）
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/sandbox \
    && chown -R appuser:appuser /srv /data
USER appuser

EXPOSE 8000

# ⚠️ 单进程 uvicorn（P0）。
#    多 worker 需先把 LLM 信号量改成 Redis 令牌桶（07 §18.1），
#    否则"每模型并发上限"会被**按进程数悄悄放大**。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
