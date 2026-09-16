"""`semantic_bundle_loaded` 探针实现 —— 附录 A §A.8.1 / 07 §18.2。

归属窗口：W2A（探针**实现**）。**注册动作在 `app/main.py`（W1B 组装根）** ——
`repo/health.py`（L0）不得 import L5 端点层，本模块同样不碰 `main.py`；
接线请求走 `backend/reports/w2a/RELAY.md`（用户 2026-09-16 约定）。

失败语义（附录 A §A.8.1）：`semantic_bundle_loaded` 是**硬依赖**
（`DEPENDENCY_KIND` 单一定义）—— 未加载 / 未通过五步校验 → readiness 503。
这不是"降级"，是**不可用**：无口径 = 不可用，不是降级（07 §5.1）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.contracts import HealthProbeResult
from app.core.enums import DEPENDENCY_KIND, Dependency, DependencyKind
from app.semantics.runtime import SemanticBundleRuntime

__all__ = ["build_semantic_bundle_probe"]

#: 与 `repo/health.py::ProbeFn` / `app/api/routers/health.py::ProbeFn` 结构一致
#: （二者"同名不同对象"是有意的 —— L0 不 import L5，能互相赋值靠的是结构相同）。
ProbeFn = Callable[[], Awaitable[HealthProbeResult]]


def build_semantic_bundle_probe(
    runtime_provider: Callable[[], SemanticBundleRuntime | None],
) -> ProbeFn:
    """构造探针函数（签名 = `ProbeFn`）。

    `runtime_provider`：装配根提供的取运行时函数（lifespan 里加载成功后返回实例，
    未加载/失败返回 None）。**探针每次现取，不缓存** —— readiness 的价值全在"此刻"
    （对齐 `repo/health.py::probe_metadata_db` 的同一纪律）。

    ⚠️ 探针**不做日志**（L1 不得 import `app.obs`；失败正文进 `detail`，
    服务端日志归 W7 的探针边界补齐项 —— `repo/health.py` 已登记同一缺口）。
    """

    async def _probe() -> HealthProbeResult:
        runtime = runtime_provider()
        if runtime is None:
            return HealthProbeResult(
                dependency=Dependency.SEMANTIC_BUNDLE_LOADED,
                kind=DependencyKind.HARD,
                healthy=False,
                detail="语义包未加载（五步校验未通过或装配根未接线）",
            )
        return HealthProbeResult(
            dependency=Dependency.SEMANTIC_BUNDLE_LOADED,
            kind=DEPENDENCY_KIND[Dependency.SEMANTIC_BUNDLE_LOADED],
            healthy=True,
            detail=f"bundle={runtime.active_version()} status={runtime.bundle_status()}",
        )

    _probe.__name__ = "probe_semantic_bundle"  # 健康面板上的可读名
    return _probe
