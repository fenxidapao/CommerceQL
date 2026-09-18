"""软依赖探针（LLM / embedding）—— 附录 A §A.8.1 的"可降级依赖"这一半。

归属窗口：W7（docs/08 §4.1：`app/obs/**` 指标与采样器部分）

## 为什么只有这两个探针放在这里，硬依赖仍在 `app/repo/health.py`
硬依赖（元数据库 / checkpointer / Redis）探的是**自己的连接池与 Redis 客户端**，
它们的构造事实归 W1B（`app/repo`）。软依赖探的是**两个互相独立的外部 HTTP 服务**
（DeepSeek 在公网、Ollama 在宿主），与仓储层无关，且都必须遵守同一条纪律：
**探测失败只能表达"降级"，绝不能表达"不可用"**（N-21）。

## 探针只做"可达性"，不做"可用性证明"
⚠️ 这是刻意的收窄，也是本文件的诚实边界：
· 一次 TCP+TLS+HTTP 握手成功 **不等于** 模型会返回可解析的 JSON、不等于配额还在；
· 因此 `healthy=True` 的语义是"**上游可达**"，写进 `detail` 里，不写成"LLM 正常"。
真正的"这次调用成功了没"由 `degraded_total` / `llm_json_parse_failure_total` 承载（§15.3）。

## 为什么零配额
`/healthz`（聚合详情）会被 UI 健康点周期性拉（06 §11.4）。若探针走一次真补全，
就是"每 30 秒烧一次额度"，且把观测链路变成了额度依赖。两个探针都只做 **GET 根路径 /
`/api/tags`**：Ollama 完全本地，DeepSeek 只到 HTTP 层（不带 key、不产生 token）。
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Final

import httpx

from app.core.contracts import HealthProbeResult
from app.core.enums import DEPENDENCY_KIND, Dependency

__all__ = ["PROBE_TIMEOUT_S", "ProbeFn", "make_embedding_probe", "make_llm_probe"]

#: 探针签名。**就地定义而不是 `from app.repo.health import ProbeFn`** ——
#: U-18 的代价约束是「`obs/` 内除 `audit.py` 外不得引入 `repo` 依赖」
#: （`tests/contract/test_obs_audit_contract.py` 静态扫描 + `.importlinter` r-dep-3 双道闸门），
#: 借一个类型别名也会被判违规。三处同名 `ProbeFn`（此处 / `repo.health` / `api.routers.health`）
#: 是**同一形状的鸭子类型**，`register_probe` 接受的是可调用对象本身，不需要导入关系成立。
ProbeFn = Callable[[], Awaitable[HealthProbeResult]]

#: 探针超时。**必须远小于**探针消费方的间隔（LB / UI 轮询），否则一次上游抖动会让
#: `/healthz` 自己变成慢点 —— 那是"观测拖垮服务"的形态。
PROBE_TIMEOUT_S: Final[float] = 2.0


def _result(dependency: Dependency, *, healthy: bool, detail: str) -> HealthProbeResult:
    """构造探针结果。`kind` 只从 `DEPENDENCY_KIND` 单一定义取（软/硬不是这里能改的）。"""
    return HealthProbeResult(
        dependency=dependency, kind=DEPENDENCY_KIND[dependency], healthy=healthy, detail=detail
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=PROBE_TIMEOUT_S, follow_redirects=False)


def make_llm_probe(base_url: str) -> ProbeFn:
    """对话模型可达性探针（GET 根路径）。

    ⚠️ 只判"拿到了任意 HTTP 响应"：`401/404` 同样算可达 —— 那说明 DNS、TCP、TLS、
    HTTP 服务本身都是活的，剩下的鉴权/配额问题会在真实调用里以 `degraded(llm_unavailable)`
    暴露（那才是该告警的信号）。**刻意不打补全请求**：零配额、零延迟污染。
    """

    async def probe() -> HealthProbeResult:
        try:
            async with _client() as client:
                response = await client.get(base_url)
        except Exception as exc:
            return _result(
                Dependency.LLM,
                healthy=False,
                detail=f"上游不可达：{type(exc).__name__}（走降级：模板查询 / 提示重试）",
            )
        return _result(
            Dependency.LLM,
            healthy=True,
            detail=f"上游可达（HTTP {response.status_code}；未校验鉴权与配额）",
        )

    return probe


def make_embedding_probe(base_url: str, model: str) -> ProbeFn:
    """embedding 可达性探针（Ollama `GET /api/tags`，纯本地、零额度）。

    比 LLM 多做一步"**模型在不在**"判定：Ollama 活着但模型没拉取，是本项目实测过的
    真实故障形态，而它的表现是"检索退化成 sparse_only 却没人知道"——
    所以 `detail` 里要能区分"连不上"与"连上了但没有这个模型"。
    """

    async def probe() -> HealthProbeResult:
        url = f"{base_url.rstrip('/')}/api/tags"
        try:
            async with _client() as client:
                response = await client.get(url)
        except Exception as exc:
            return _result(
                Dependency.EMBEDDING,
                healthy=False,
                detail=f"Ollama 不可达：{type(exc).__name__}（走降级：稀疏 + Join 图扩展）",
            )
        if response.status_code >= 400:
            return _result(
                Dependency.EMBEDDING,
                healthy=False,
                detail=f"Ollama 返回 HTTP {response.status_code}（走降级：稀疏 + Join 图扩展）",
            )
        listed: list[str] = []
        with contextlib.suppress(Exception):
            payload = response.json()
            models = payload.get("models") if isinstance(payload, dict) else None
            listed = [str(m.get("name", "")) for m in models if isinstance(m, dict)] if models else []
        if listed and not any(name == model or name.startswith(f"{model}:") for name in listed):
            return _result(
                Dependency.EMBEDDING,
                healthy=False,
                detail=f"Ollama 可达但未加载模型 {model}（已加载：{','.join(sorted(set(listed))[:5])}）",
            )
        return _result(Dependency.EMBEDDING, healthy=True, detail=f"Ollama 可达，模型 {model} 在列")

    return probe
