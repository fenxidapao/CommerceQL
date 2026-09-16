"""健康检查 —— **三个探针，职责分离**（附录 A §A.8；07 §18.2）。

归属窗口：W0 交付**空实现骨架** → W7 接管实现（docs/08 §4.1 标注 `app/api/routers/health.py` 归 W7）。
本文件当前的状态是**刻意的 503**：硬依赖尚未接线，这正是阶段 0 DoD① 要求的"正确行为"。

三个端点各自的消费方**完全不同**，这也是它们必须分开的原因（附录 A §A.8）：

| 端点 | 消费方 | 失败动作 | 含软依赖？ |
|---|---|---|---|
| `/healthz/live` | 进程重启决策 | 重启进程 | ❌ 不检查任何外部依赖 |
| `/healthz/ready` | Compose `healthcheck` / LB | **摘流量，不重启** | ❌ **只含硬依赖** |
| `/healthz` | 运维人工排查 / UI 健康点 | 无自动动作（走告警） | ✅ 软依赖分列上报 |

⚠️ **最容易做错的一条**：把软依赖（LLM / embedding）塞进 readiness。
二者都已有明确的降级路径，塞进去等于**把"降级"变成"不可用"** —— 一个本可以继续服务的实例会被摘流量（N-21）。

⚠️ **诚实边界（阶段 0）**：
- `event_loop_lag_ms` 返回 `null` 而非 `0` —— 采样器属 W7，**不填 0 冒充已实现**；
- `bundle_version` 在语义包接入前为 `null`；
- `/healthz/live` 当前**在单机 Compose 下没有自动消费者**（Compose 不会因 `unhealthy` 自动重启容器），
  附录 A §A.8.2 已诚实标注。**不得声称"已实现健康自愈"。**
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.contracts import HealthProbeResult
from app.core.enums import (
    DEPENDENCY_KIND,
    READINESS_DEPENDENCIES,
    Dependency,
    DependencyKind,
    HealthStatus,
)

__all__ = ["SEMANTIC_RUNTIME_STATE_KEY", "register_probe", "router"]

router = APIRouter(tags=["health"])

#: `app.state` 上语义包运行时的键名（W2-INT 接线，主键形态对齐 `deps.RUNTIME_STATE_KEY`）。
#: 定义在本文件（L5）而不是 `app/semantics`（L1）：放运行时对象进 `app.state`
#: 是**接入层装配动作**，语义包模块自己不知道也不该知道 `app.state` 的存在。
SEMANTIC_RUNTIME_STATE_KEY: Final[str] = "commerceql.semantic_runtime"

#: 进程启动时刻（单调时钟）。`time.monotonic` 不受系统时间调整影响 ——
#: 用墙钟算 uptime 会在 NTP 校时后出现负数。
_STARTED_MONOTONIC: Final[float] = time.monotonic()

ProbeFn = Callable[[], Awaitable[HealthProbeResult]]


async def _unwired_probe(dependency: Dependency) -> HealthProbeResult:
    """阶段 0 占位探针：**明确报告"未接线"，不谎报健康**。

    为什么不用 `healthy=True` 让 DoD 好过：健康的绿色状态会让接线遗漏被一直掩盖到上线。
    """
    return HealthProbeResult(
        dependency=dependency,
        kind=DEPENDENCY_KIND[dependency],
        healthy=False,
        detail="阶段 0 骨架：探针未接线（实现归 W1B/W7）",
    )


def _make_unwired_probe(dependency: Dependency) -> ProbeFn:
    """把 `_unwired_probe` 绑到具体依赖上。

    刻意用工厂函数而不是 `lambda d=dep: _unwired_probe(d)`：
    `lambda` 的默认参数绑定让 mypy 无法推断类型（`Cannot infer type of lambda`），
    而 `ProbeFn` 是给 W1B / W7 看的**签名契约** —— 类型信息在这里丢了，
    后续窗口接线时就失去了"参数与返回值长什么样"的机器提示。
    """

    async def _probe() -> HealthProbeResult:
        return await _unwired_probe(dependency)

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
    targets = Dependency if dependencies is None else dependencies
    results: dict[Dependency, HealthProbeResult] = {}
    for dep in targets:
        try:
            results[dep] = await _PROBES[dep]()
        except Exception as exc:
            results[dep] = HealthProbeResult(
                dependency=dep,
                kind=DEPENDENCY_KIND[dep],
                healthy=False,
                detail=f"探针异常：{type(exc).__name__}",
            )
    return results


def _checks_payload(results: dict[Dependency, HealthProbeResult]) -> dict[str, bool]:
    return {dep.value: res.healthy for dep, res in results.items()}


def _bundle_version(request: Request) -> str | None:
    """从 `app.state` 取语义包运行时的激活版本（W2-INT 接线）。

    ⚠️ 运行时未装配 → `None`（如实），**不填 `"unknown"` 之类的占位串** ——
    消费方（前端/监控）区分"没有"与"有一个叫 unknown 的版本"靠的就是 None。
    """
    runtime = getattr(request.app.state, SEMANTIC_RUNTIME_STATE_KEY, None)
    if runtime is None:
        return None
    return str(runtime.active_version())


@router.get("/healthz/live")
async def liveness() -> JSONResponse:
    """liveness（附录 A §A.8.2）。**约束：不检查任何外部依赖。**

    数据库抖动不应触发进程重启 —— 重启会杀掉在途的 SSE 流，把一次抖动放大成一次事故。
    """
    body: dict[str, Any] = {
        "status": HealthStatus.OK.value,
        "uptime_s": int(time.monotonic() - _STARTED_MONOTONIC),
        # ⚠️ W7 实现事件循环延迟采样器之前，这里必须是 null。
        #    A.8.2 规定"事件循环阻塞 > 5s → 503"，没有采样器就无法判定该条件，
        #    因此**不能**返回 0（那等于宣称"已实现且健康"）。
        "event_loop_lag_ms": None,
    }
    return JSONResponse(body, status_code=200)


@router.get("/healthz/ready")
async def readiness(request: Request) -> JSONResponse:
    """readiness（附录 A §A.8.3）。**只含硬依赖**（N-21）。

    阶段 0 返回 503 —— 元数据库 / checkpointer / Redis / 语义包**均未接线**。
    这是 DoD① 明确要求的行为：**503 是正确的，不是缺陷**。
    W2-INT 接线后：语义包运行时装配成功 → `semantic_bundle_loaded` 转真；
    未装配（包缺失/非法/未接线）→ 如实 503（`SEMANTIC_BUNDLE_LOADED` 属 HARD，enums 单一定义）。
    """
    results = await _collect(READINESS_DEPENDENCIES)
    ok = all(res.healthy for res in results.values())
    body: dict[str, Any] = {
        "status": HealthStatus.OK.value if ok else HealthStatus.UNHEALTHY.value,
        "checks": _checks_payload(results),
        "bundle_version": _bundle_version(request),
    }
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/healthz")
async def aggregate(request: Request) -> JSONResponse:
    """聚合详情（附录 A §A.8.4）。**不要用它做编排探针。**

    ⚠️ 关键规则：仅软依赖失败 → **200 + degraded**（不是 503）。
    原设计在这里返回 503 是错的 —— `503` 会让任何按 HTTP 码判断的编排层/监控误判为服务不可用。
    """
    results = await _collect()
    checks = _checks_payload(results)

    hard_failed = [
        dep for dep, res in results.items()
        if not res.healthy and DEPENDENCY_KIND[dep] is DependencyKind.HARD
    ]
    degraded = [
        dep.value for dep, res in results.items()
        if not res.healthy and DEPENDENCY_KIND[dep] is DependencyKind.SOFT
    ]

    if hard_failed:
        status, http_status = HealthStatus.UNHEALTHY, 503
    elif degraded:
        status, http_status = HealthStatus.DEGRADED, 200
    else:
        status, http_status = HealthStatus.OK, 200

    body: dict[str, Any] = {
        # `status` 与 HTTP 码**必须成对**：附录 A §A.8.4 允许"仅软依赖失败 → 200 + degraded"，
        # 此时 HTTP 码是 200，唯一能看出降级的信号就是这个字段。
        # 只算不填 = 编排层只能看到 200，也就永远发现不了降级（ruff F841 曾抓到此处遗漏）。
        "status": status.value,
        # `graph_compiled` 的权威来源是 app.main 的装配结果；阶段 0 尚无图，如实报 false
        "graph_compiled": False,
        **checks,
        "degraded_dependencies": degraded,
        "bundle_version": _bundle_version(request),
        "version": "0.1.0",
        # 二者**必须分列**（附录 A §A.8.4）：Ollama 在宿主、DeepSeek 在公网，
        # 合成一个字段会让"到底是 embedding 挂了还是对话模型挂了"无法定位
        "embedding_model": None,
        "embedding_dim": None,
        "probe_detail": {dep.value: res.detail for dep, res in results.items() if res.detail},
    }
    return JSONResponse(body, status_code=http_status)
