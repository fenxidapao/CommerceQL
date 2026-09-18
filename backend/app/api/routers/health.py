"""健康检查 —— **三个探针，职责分离**（附录 A §A.8；07 §18.2）+ 指标导出 + 停机闸门。

归属窗口：W0 交付空实现骨架 → **W7 接管实现**（docs/08 §4.1 标注本文件归 W7）。

## 三个端点各自的消费方完全不同，这也是它们必须分开的原因（附录 A §A.8）

| 端点 | 消费方 | 失败动作 | 含软依赖？ |
|---|---|---|---|
| `/healthz/live` | 进程重启决策 | 重启进程 | ❌ 不检查任何外部依赖 |
| `/healthz/ready` | Compose `healthcheck` / LB | **摘流量，不重启** | ❌ **只含硬依赖** |
| `/healthz` | 运维人工排查 / UI 健康点 | 无自动动作（走告警） | ✅ 软依赖分列上报 |

⚠️ **最容易做错的一条**：把软依赖（LLM / embedding）塞进 readiness。
二者都已有明确的降级路径，塞进去等于**把"降级"变成"不可用"** —— 实例会被摘流量（N-21）。
判定用的是 `READINESS_DEPENDENCIES`（`app.core.enums` 单一定义），**不是**"注册了什么就查什么"。

## 本文件另外两个"停机/观测"面（W7）
- `GET /metrics`：07 §15.3 指标的**导出面**（手写 exposition，见 `app/obs/metrics.py`）。
  ⚠️ 它挂在本 router 上，因此实际路径是 `/api/v1/metrics`，且 **Nginx 不得对外代理**
  （`deploy/nginx.conf` 已按此配置）—— 指标里虽无行级数据，但有租户维度的成本与错误分布。
- `POST /healthz/drain` + `GET /healthz/drain`：07 §18.3 第 1~2 步的**触发面**。
  🔴 **为什么不能只在 lifespan 的关闭段里 drain**（实测 uvicorn 0.53 `Server.shutdown`）：
  uvicorn 的顺序是「停监听 → 等在途连接结束（`timeout_graceful_shutdown`，默认**无限**）」
  → **之后**才发 lifespan shutdown 事件。也就是说，把六步写在 `yield` 之后，
  uvicorn 会先一直等 SSE 流自己结束（长轮询下就是等不到），等到 `stop_grace_period` 到了
  再 SIGKILL —— 那正是 §18.3 要避免的"静默断连"。所以必须有一个**先于 SIGTERM 传导**的触发面：
  `deploy/entrypoint.sh` 收到 TERM 后先调用本端点，等在途流收尾，再把 TERM 转给 uvicorn。
"""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.deps import GRAPH_RUNTIME_STATE_KEY
from app.core.config import get_settings
from app.core.contracts import HealthProbeResult
from app.core.enums import (
    DEPENDENCY_KIND,
    READINESS_DEPENDENCIES,
    Dependency,
    DependencyKind,
    HealthStatus,
)
from app.obs import metrics
from app.obs.instrumentation import REGISTRY
from app.obs.logging import get_logger

__all__ = ["SEMANTIC_RUNTIME_STATE_KEY", "register_probe", "router"]

_log = get_logger(__name__)

router = APIRouter(tags=["health"])

#: `app.state` 上语义包运行时的键名（W2-INT 接线，主键形态对齐 `deps.RUNTIME_STATE_KEY`）。
#: 定义在本文件（L5）而不是 `app/semantics`（L1）：放运行时对象进 `app.state`
#: 是**接入层装配动作**，语义包模块自己不知道也不该知道 `app.state` 的存在。
SEMANTIC_RUNTIME_STATE_KEY: Final[str] = "commerceql.semantic_runtime"

#: drain 令牌的**环境变量名**。刻意不进 `Settings`：`app/core/config.py` 归 W0，
#: 而本项是 W7 的运行动作开关，不是业务配置（写死在这里，比拉一次跨窗口改动便宜）。
#: 未设置 ⇒ drain 端点**禁用**（fail-closed：宁可停机走 SIGKILL 老路，也不开一个无鉴权的远程停机口）。
DRAIN_TOKEN_ENV: Final[str] = "DRAIN_TOKEN"

#: 事件循环阻塞阈值（附录 A §A.8.2："阻塞 > 5s → 503"）。
LIVENESS_LAG_THRESHOLD_MS: Final[float] = 5000.0

#: 进程启动时刻（单调时钟）。`time.monotonic` 不受系统时间调整影响 ——
#: 用墙钟算 uptime 会在 NTP 校时后出现负数。
_STARTED_MONOTONIC: Final[float] = time.monotonic()

ProbeFn = Callable[[], Awaitable[HealthProbeResult]]

#: 聚合详情里 `checks` 的键名（附录 A §A.8.4 逐字给定，**与 §A.8.3 的 readiness 不同名**：
#: readiness 用依赖原名 `checkpointer`/`redis`，聚合详情用 `checkpointer_reachable`/`redis_reachable`。
#: 两处刻意不同形状，因为消费方不同：编排层只要"哪一项挂了"，UI 要"这一项通不通"）。
_AGGREGATE_CHECK_KEYS: Final[dict[Dependency, str]] = {
    Dependency.METADATA_DB: "metadata_db",
    Dependency.CHECKPOINTER: "checkpointer_reachable",
    Dependency.REDIS: "redis_reachable",
    Dependency.SEMANTIC_BUNDLE_LOADED: "semantic_bundle_loaded",
    Dependency.LLM: "llm_reachable",
    Dependency.EMBEDDING: "embedding_reachable",
}


def _unwired_probe(dependency: Dependency) -> HealthProbeResult:
    """未接线占位探针：**明确报告"未接线"，不谎报健康**。

    为什么不用 `healthy=True` 让 DoD 好过：健康的绿色状态会把接线遗漏一直掩盖到上线。
    """
    return HealthProbeResult(
        dependency=dependency,
        kind=DEPENDENCY_KIND[dependency],
        healthy=False,
        detail="探针未接线（W7 只接软依赖；硬依赖由 W1B 的 build_probe_table 接）",
    )


def _make_unwired_probe(dependency: Dependency) -> ProbeFn:
    """把 `_unwired_probe` 绑到具体依赖上。

    刻意用工厂函数而不是 `lambda d=dep: _unwired_probe(d)`：
    `lambda` 的默认参数绑定让 mypy 无法推断类型（`Cannot infer type of lambda`），
    而 `ProbeFn` 是给 W1B / W7 看的**签名契约** —— 类型信息在这里丢了，
    后续窗口接线时就失去了"参数与返回值长什么样"的机器提示。
    """

    async def _probe() -> HealthProbeResult:
        return _unwired_probe(dependency)

    return _probe


#: 探针注册表。W1B 接元数据库/checkpointer/Redis，W7 接 LLM/embedding/语义包。
_PROBES: dict[Dependency, ProbeFn] = {
    dependency: _make_unwired_probe(dependency) for dependency in Dependency
}


def register_probe(dependency: Dependency, probe: ProbeFn) -> None:
    """接线入口（W1B / W7 调用）。

    ⚠️ 软依赖探针**不得**被 `/healthz/ready` 使用 —— 判定用的是 `READINESS_DEPENDENCIES`
    （由 `app.core.enums` 单一定义），而不是"注册了什么就查什么"。这一点是刻意的：
    让"软依赖不许进 readiness"成为**结构约束**，而不是靠实现者记得。
    """
    _PROBES[dependency] = probe


async def _collect(dependencies: frozenset[Dependency] | None = None) -> dict[Dependency, HealthProbeResult]:
    """并发跑探针，返回 `{依赖: 结果}`（键序 == `targets` 的迭代序）。

    ⭐ **必须并发，不是优化而是达成预算**（W1B 转交项）：附录 D 给 `/healthz/ready` 的
    平台预算是 `healthcheck.timeout: 5s`。串行 `await` 让端点耗时 = **各硬依赖之和**
    （W1B 实测 7.82s，其中 5.84s 是 Windows `getaddrinfo` 失败本身的环境代价 ——
    调 `connect_timeout` 消不掉）。超出预算的后果不是"慢"，而是**诚实的 503 体读不到**：
    消费者只看到 curl 超时，于是"依赖没接"与"探针实现坏了"在外部不可区分。
    改成 gather 后上界从"和"变成"最大值"。

    ⚠️ 不用 `asyncio.as_completed` / 不吞异常：探针**永不**因为异常而变成"没有这一项" ——
    缺席会让 `all(...)` 在少一项的情况下更容易通过。
    """
    targets = tuple(Dependency if dependencies is None else dependencies)

    async def _one(dep: Dependency) -> HealthProbeResult:
        try:
            return await _PROBES[dep]()
        except Exception as exc:
            name = type(exc).__name__
            return HealthProbeResult(
                dependency=dep,
                kind=DEPENDENCY_KIND[dep],
                healthy=False,
                detail=(
                    "池在预算内未取到连接（预期的未就绪，非探针实现异常）"
                    if name == "PoolTimeout"
                    else f"探针异常：{name}"
                ),
            )

    results = await asyncio.gather(*(_one(dep) for dep in targets))
    return dict(zip(targets, results, strict=True))


def _bundle_version(request: Request) -> str | None:
    """从 `app.state` 取语义包运行时的激活版本（W2-INT 接线）。

    ⚠️ 运行时未装配 → `None`（如实），**不填 `"unknown"` 之类的占位串** ——
    消费方（前端/监控）区分"没有"与"有一个叫 unknown 的版本"靠的就是 None。
    """
    runtime = getattr(request.app.state, SEMANTIC_RUNTIME_STATE_KEY, None)
    if runtime is None:
        return None
    return str(runtime.active_version())


def _graph_compiled(request: Request) -> bool:
    """图是否已编译装配（§A.8.4 的 `graph_compiled`）。

    权威来源是 **`app.state` 上有没有 `GraphRuntime`**（`main.py` 第 4.5 步的装配结果），
    而不是在本文件里再 `compile()` 一次判断 —— 那会出现"探针说有图、端点用的是另一份图"。
    """
    runtime = getattr(request.app.state, GRAPH_RUNTIME_STATE_KEY, None)
    return bool(runtime is not None and getattr(runtime, "graph", None) is not None)


def _log_probe_details(results: dict[Dependency, HealthProbeResult]) -> None:
    """探针明细**只进日志，不进响应体**。

    原实现把 `probe_detail` 塞进 `/healthz` —— 那是 §A.8.4 里没有的字段（前端 `types.ts`
    也没有它，等于一个"只有后端知道"的私增字段，违反 07 §4.1"唯一规范源"）。
    但"哪个依赖到底为什么挂"必须看得到，所以换个承载位：一次 WARN 日志。
    """
    failed = {dep.value: res.detail for dep, res in results.items() if not res.healthy and res.detail}
    if failed:
        _log.warning("healthz_failed_probes", failed=failed)


# ============================================================================
# 一、三个探针
# ============================================================================


@router.get("/healthz/live")
async def liveness() -> JSONResponse:
    """liveness（附录 A §A.8.2）。**约束：不检查任何外部依赖。**

    数据库抖动不应触发进程重启 —— 重启会杀掉在途的 SSE 流，把一次抖动放大成一次事故。

    `event_loop_lag_ms` 来自 W7 的循环延迟采样器（`app/obs/samplers.py`）。
    ⚠️ 采样器还没跑出第一个样本时返回 `null` 而**不是 0**：A.8.2 的"阻塞 > 5s → 503"
    需要真实测量才能判定，填 0 等于宣称"已实现且健康"。
    """
    lag_ms = metrics.get_event_loop_lag_ms()
    blocked = lag_ms is not None and lag_ms > LIVENESS_LAG_THRESHOLD_MS
    body: dict[str, Any] = {
        "status": HealthStatus.UNHEALTHY.value if blocked else HealthStatus.OK.value,
        "uptime_s": int(time.monotonic() - _STARTED_MONOTONIC),
        "event_loop_lag_ms": lag_ms,
    }
    return JSONResponse(body, status_code=503 if blocked else 200)


@router.get("/healthz/ready")
async def readiness(request: Request) -> JSONResponse:
    """readiness（附录 A §A.8.3）。**只含硬依赖**（N-21）。

    🔴 额外的一条：`draining` 期间**立刻**返回 503 —— 这是 §18.3 第 1 步"摘 readiness"。
    它不属于任何依赖的健康度（依赖可能全绿），而是"本实例不再接受新工作"的显式声明；
    放在这里而不是新开字段，因为消费方（Compose `healthcheck` / LB）只看 HTTP 码。
    """
    registry = REGISTRY
    results = await _collect(READINESS_DEPENDENCIES)
    ok = all(res.healthy for res in results.values()) and not registry.draining
    checks = {dep.value: res.healthy for dep, res in results.items()}
    body: dict[str, Any] = {
        "status": HealthStatus.OK.value if ok else HealthStatus.UNHEALTHY.value,
        "checks": checks,
        "bundle_version": _bundle_version(request),
    }
    if registry.draining:
        # 只在 drain 时出现：正常路径的 payload 与 §A.8.3 的示例逐字段一致。
        body["draining"] = True
    _log_probe_details(results)
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/healthz")
async def aggregate(request: Request) -> JSONResponse:
    """聚合详情（附录 A §A.8.4）。**不要用它做编排探针。**

    ⚠️ 关键规则：仅软依赖失败 → **200 + `degraded`**（不是 503）。
    原设计在这里返回 503 是错的 —— `503` 会让任何按 HTTP 码判断的编排层/监控误判为服务不可用。
    """
    results = await _collect()
    settings = get_settings()

    hard_failed = [
        dep
        for dep, res in results.items()
        if not res.healthy and DEPENDENCY_KIND[dep] is DependencyKind.HARD
    ]
    degraded = [
        dep.value
        for dep, res in results.items()
        if not res.healthy and DEPENDENCY_KIND[dep] is DependencyKind.SOFT
    ]

    if hard_failed:
        status, http_status = HealthStatus.UNHEALTHY, 503
    elif degraded:
        status, http_status = HealthStatus.DEGRADED, 200
    else:
        status, http_status = HealthStatus.OK, 200

    body: dict[str, Any] = {
        # `status` 与 HTTP 码**必须成对**：§A.8.4 允许"仅软依赖失败 → 200 + degraded"，
        # 此时 HTTP 码是 200，唯一能看出降级的信号就是这个字段。只算不填 = 编排层只能看到 200。
        "status": status.value,
        "checks": {
            # 🔴 `graph_compiled` 在 `checks` **里面**（§A.8.4 示例的位置），不是顶层字段。
            "graph_compiled": _graph_compiled(request),
            **{_AGGREGATE_CHECK_KEYS[dep]: res.healthy for dep, res in results.items()},
            # 二者**必须分列**（§A.8.4）：Ollama 在宿主、DeepSeek 在公网，合成一个字段
            # 会让"到底是 embedding 挂了还是对话模型挂了"无法定位。
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dim": settings.EMBEDDING_DIM,
        },
        "degraded_dependencies": degraded,
        "bundle_version": _bundle_version(request),
        "version": request.app.version,
    }
    _log_probe_details(results)
    return JSONResponse(body, status_code=http_status)


# ============================================================================
# 二、指标导出（07 §15.3）
# ============================================================================


@router.get("/metrics")
async def prometheus_metrics() -> PlainTextResponse:
    """Prometheus text exposition 0.0.4（`app/obs/metrics.py` 手写渲染，无第三方客户端库）。

    ⚠️ 本端点**不在** §A 的对外契约面里（附录 A 没有它），因此：
    ① `deploy/nginx.conf` 不代理它（只允许内网抓取）；
    ② 它不进 `http_requests_total`（`ObservingMiddleware` 按 `/api/v1/healthz`、
       `/api/v1/metrics` 前缀自跳过）—— 否则每 15s 一次的抓取会淹没真实 QPS。
    """
    return PlainTextResponse(metrics.render_prometheus_text(), media_type=metrics.PROMETHEUS_CONTENT_TYPE)


# ============================================================================
# 三、优雅停机闸门（07 §18.3 第 1~2 步的触发面）
# ============================================================================


def _drain_authorized(request: Request) -> bool:
    """drain 鉴权：`DRAIN_TOKEN` 环境变量 + `X-Drain-Token` 头的**常量时间**比对。

    未设置该变量 ⇒ **一律 403**（fail-closed）。理由是这条路由的语义是"让本机开始停机"，
    无鉴权地暴露它 = 任何能打到这个端口的人都能周期性让服务重启。
    """
    expected = os.environ.get(DRAIN_TOKEN_ENV, "")
    given = request.headers.get("x-drain-token", "")
    return bool(expected) and hmac.compare_digest(expected, given)


@router.post("/healthz/drain", status_code=202)
async def begin_drain(request: Request) -> JSONResponse:
    """置位 drain（幂等）：readiness 立刻转 503，在途 SSE 流在下一次出帧时收到终止 `error`。

    ⚠️ 本端点**只置位不等待**：等待由调用方（`deploy/entrypoint.sh`）轮询
    `GET /healthz/drain` 完成，从而把"等多久"这个策略留在部署侧，而不是焊死在应用里。
    """
    registry = REGISTRY
    if not _drain_authorized(request):
        return JSONResponse({"detail": "drain 未启用或令牌不符"}, status_code=403)
    inflight = registry.begin_drain()
    _log.warning("drain_begun", inflight_streams=inflight, via=request.client.host if request.client else "unknown")
    return JSONResponse({"draining": True, "inflight": inflight}, status_code=202)


@router.get("/healthz/drain")
async def drain_status() -> JSONResponse:
    """drain 进度（pre-stop 脚本轮询它，直到 `inflight == 0` 或到达 `stop_grace_period` 预算）。"""
    registry = REGISTRY
    return JSONResponse({"draining": registry.draining, "inflight": registry.count()})
