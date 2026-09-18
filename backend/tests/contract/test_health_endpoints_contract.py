"""三探针 + 停机闸门的 **HTTP 契约形状**断言（附录 A §A.8.2/§A.8.3/§A.8.4；N-21；C-13；07 §18.3 第 1~2 步）。

归属窗口：W7。

## 与 `tests/unit/test_health_probes.py` 的分工
那个文件测**探针函数**（池超时、表族判定）；本文件测**端点对外长什么样**：
状态码、`checks` 的键名、字段集合。这层之所以值得单独钉，是因为契约的失效方式很隐蔽 ——
`detail` 移出响应体、`checks` 换成枚举原名、多塞一个"有用"的字段，**都不会让任何功能变坏**，
但前端 `types.ts` 与编排层的按码判定会静默错位（C-13 说的正是这件事）。

## 本文件不碰的东西（别把它读成"停机已验证"）
在途 SSE 流的**终止帧注入**由 `test_obs_frame_format.py` / `test_obs_instrumentation.py` 覆盖；
`deploy/entrypoint.sh` 那条 shell 链（TERM → 调本端点 → 轮询 → 转 TERM 给 uvicorn）的
**预算与装配不变量**在 `test_shutdown_budget_contract.py`，但 pytest **不覆盖运行时顺序** ——
那三条（置位后才收尾 / 预算耗尽仍转发 TERM / 无 token 不卡死）的证据是一次性容器 + 假
drain 端点的实测，见 `deploy/runbook/README.md` §四-2。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routers import health
from app.core.contracts import HealthProbeResult
from app.core.enums import (
    DEPENDENCY_KIND,
    READINESS_DEPENDENCIES,
    Dependency,
    DependencyKind,
    HealthStatus,
)
from app.obs import metrics
from app.obs.instrumentation import InFlightRegistry

pytestmark = pytest.mark.contract

_ALL_DEPENDENCIES: tuple[Dependency, ...] = tuple(Dependency)
_SOFT_DEPENDENCIES: tuple[Dependency, ...] = tuple(
    dependency
    for dependency in _ALL_DEPENDENCIES
    if DEPENDENCY_KIND[dependency] is DependencyKind.SOFT
)
_HARD_DEPENDENCIES: tuple[Dependency, ...] = tuple(
    dependency
    for dependency in _ALL_DEPENDENCIES
    if DEPENDENCY_KIND[dependency] is DependencyKind.HARD
)

#: §A.8.3 readiness 示例的字段集（多一个少一个都是契约变更）。
_READY_KEYS = {"status", "checks", "bundle_version"}
#: §A.8.4 聚合详情示例的字段集。`draining` 只在 drain 期间出现，故单列。
_AGGREGATE_KEYS = {"status", "checks", "degraded_dependencies", "bundle_version", "version"}
_LIVE_KEYS = {"status", "uptime_s", "event_loop_lag_ms"}


@pytest.fixture(autouse=True)
def _clean_metrics() -> Iterator[None]:
    metrics.reset_for_tests()
    yield
    metrics.reset_for_tests()


@pytest.fixture
def healthy(monkeypatch: pytest.MonkeyPatch) -> dict[Dependency, bool]:
    """把六个依赖的探针全部换成可控替身，返回**可变**的健康字典。

    ⚠️ 整表替换（而不是逐个 `register_probe`）：替身必须覆盖**全部**依赖，否则漏掉的那个
    会走真探针 —— 在 CI 上它必然连不上池，于是"payload 形状"测试会掺进环境噪声。
    """
    states = {dependency: True for dependency in _ALL_DEPENDENCIES}

    def _make(dependency: Dependency) -> health.ProbeFn:
        async def _probe() -> HealthProbeResult:
            return HealthProbeResult(
                dependency=dependency,
                kind=DEPENDENCY_KIND[dependency],
                healthy=states[dependency],
                detail=f"替身：{dependency.value} healthy={states[dependency]}",
            )

        return _probe

    monkeypatch.setattr(health, "_PROBES", {dependency: _make(dependency) for dependency in _ALL_DEPENDENCIES})
    monkeypatch.setattr(health, "REGISTRY", InFlightRegistry())
    return states


@pytest.fixture
def client() -> TestClient:
    """**不进上下文管理器** ⇒ 不跑 lifespan。

    lifespan 会去连池、装配图，那不是本文件的判据；探针已在 `healthy` 里换成替身。
    """
    from app.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def _json(client: TestClient, path: str) -> tuple[int, dict[str, Any]]:
    response = client.get(path)
    assert response.headers["content-type"].startswith("application/json"), (
        f"{path} 返回了非 JSON：探针消费者（compose healthcheck / LB / 前端）都按 JSON 解"
    )
    return response.status_code, response.json()


# ===========================================================================
# 一、liveness（§A.8.2）
# ===========================================================================


def test_liveness_never_calls_a_dependency_probe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**约束**：liveness 不碰外部依赖。

    这条断言的价值全在"替身被调用了几次"上：若哪天有人往 `liveness()` 里加一句
    `await _collect()`，DB 抖动就会开始**重启进程**（把一次抖动放大成一次在途流事故）。
    """
    calls: list[Dependency] = []

    def _spy(dependency: Dependency) -> health.ProbeFn:
        async def _probe() -> HealthProbeResult:
            calls.append(dependency)
            return HealthProbeResult(
                dependency=dependency,
                kind=DEPENDENCY_KIND[dependency],
                healthy=True,
                detail="spy",
            )

        return _probe

    monkeypatch.setattr(health, "_PROBES", {dependency: _spy(dependency) for dependency in _ALL_DEPENDENCIES})

    status_code, body = _json(client, "/api/v1/healthz/live")
    assert calls == [], f"liveness 打了 {len(calls)} 次依赖探针（{[c.value for c in calls]}）⇒ 依赖抖动会触发进程重启"
    assert status_code == 200
    assert body["status"] == HealthStatus.OK.value


def test_liveness_payload_shape_and_null_before_first_sample(client: TestClient) -> None:
    """`event_loop_lag_ms` 在**首个样本之前必须是 `null`**，不是 0。

    A.8.2 的判据是"阻塞 > 5s → 503"。填 0 会让采样器还没跑起来的实例**看起来**已被证明不阻塞。
    """
    status_code, body = _json(client, "/api/v1/healthz/live")
    assert status_code == 200
    assert set(body) == _LIVE_KEYS, f"liveness 字段集漂移：{sorted(body)}"
    assert body["event_loop_lag_ms"] is None
    assert isinstance(body["uptime_s"], int)


def test_liveness_turns_503_only_past_the_threshold(client: TestClient) -> None:
    """边界取"超过"不取"等于"：5000ms 仍 200，5001ms 才 503（§A.8.2 写的是 `> 5s`）。"""
    metrics.set_event_loop_lag_ms(health.LIVENESS_LAG_THRESHOLD_MS)
    assert _json(client, "/api/v1/healthz/live")[0] == 200

    metrics.set_event_loop_lag_ms(health.LIVENESS_LAG_THRESHOLD_MS + 1.0)
    status_code, body = _json(client, "/api/v1/healthz/live")
    assert status_code == 503
    assert body["status"] == HealthStatus.UNHEALTHY.value


# ===========================================================================
# 二、readiness（§A.8.3 + N-21）
# ===========================================================================


def test_readiness_checks_are_exactly_the_hard_dependencies(client: TestClient, healthy: dict[Dependency, bool]) -> None:
    _ , body = _json(client, "/api/v1/healthz/ready")
    assert set(body["checks"]) == {dependency.value for dependency in READINESS_DEPENDENCIES}
    assert set(READINESS_DEPENDENCIES) == set(_HARD_DEPENDENCIES), (
        "readiness 集合与 HARD 分类不一致 —— 二者是同一事实的两处表述，漂了就等于契约两样"
    )
    for soft in _SOFT_DEPENDENCIES:
        assert soft.value not in body["checks"], f"软依赖 {soft.value} 进了 readiness ⇒ 降级会被读成不可用（N-21）"


def test_readiness_ignores_soft_dependency_failures(client: TestClient, healthy: dict[Dependency, bool]) -> None:
    """**N-21 的正面表述**：LLM / embedding 全挂，readiness 仍 200。

    这是最容易"改坏而不报错"的一条：把软依赖塞进 readiness 之后所有功能照样跑，
    差别只在真实故障时**摘掉了一台还能服务（转模板）的机器**。
    """
    for soft in _SOFT_DEPENDENCIES:
        healthy[soft] = False

    status_code, body = _json(client, "/api/v1/healthz/ready")
    assert status_code == 200, "软依赖失败 ⇒ 503（N-21 违例）"
    assert body["status"] == HealthStatus.OK.value
    assert set(body) == _READY_KEYS, f"正常路径多塞了字段：{sorted(body)}"


@pytest.mark.parametrize("broken", _HARD_DEPENDENCIES, ids=lambda d: d.value)
def test_readiness_fails_closed_on_any_hard_dependency(
    client: TestClient, healthy: dict[Dependency, bool], broken: Dependency
) -> None:
    """逐个硬依赖各打挂一次：任意一项不健康都必须 503，且 `checks` 里只有那一项是 false。"""
    healthy[broken] = False
    status_code, body = _json(client, "/api/v1/healthz/ready")
    assert status_code == 503
    assert body["status"] == HealthStatus.UNHEALTHY.value
    assert body["checks"][broken.value] is False
    assert all(value for key, value in body["checks"].items() if key != broken.value)


def test_readiness_probes_run_concurrently_not_serially(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**约束**：readiness 并行探全部硬依赖（附录 A §A.8.3 的 5s 预算只有"取最大值"才成立）。

    这条为什么值得单独钉：串行实现**功能完全正确**（同样的 `checks{}`、同样的状态码），
    只是把端点耗时从"最慢的一个"变成"全部之和" —— 而 `deploy/docker-compose.yml` 的
    `healthcheck.timeout: 5s` 会让它超时，超时后消费者读到的是"没有响应"，
    于是"依赖没接（诚实 503）"与"探针实现坏了"在外部不可区分（W1B 实测串行 7.82s）。

    ⚠️ 判据用**同时在跑的探针数峰值**，不用墙钟：sleep 的精度在 CI 上不足以让
    "串行 = n × 耗时"稳定成立，而计数与调度抖动无关（替身在**进入时**计数，
    串行实现下峰值恒为 1）。
    """
    inflight = 0
    peak = 0

    def _make(dependency: Dependency) -> health.ProbeFn:
        async def _probe() -> HealthProbeResult:
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.05)
            inflight -= 1
            return HealthProbeResult(
                dependency=dependency,
                kind=DEPENDENCY_KIND[dependency],
                healthy=True,
                detail="并发替身：只计数，不判定",
            )

        return _probe

    monkeypatch.setattr(health, "_PROBES", {dependency: _make(dependency) for dependency in _ALL_DEPENDENCIES})

    status_code, _body = _json(client, "/api/v1/healthz/ready")
    assert status_code == 200
    assert peak == len(READINESS_DEPENDENCIES), (
        f"readiness 的探针峰值只有 {peak}（硬依赖共 {len(READINESS_DEPENDENCIES)} 个）"
        "⇒ 探测被改回串行，端点耗时变成各依赖之和，会撞穿 compose 的 5s 健康检查预算"
    )


# ===========================================================================
# 三、聚合详情（§A.8.4 + C-13）
# ===========================================================================


def test_aggregate_payload_keys_and_check_names(client: TestClient, healthy: dict[Dependency, bool]) -> None:
    """字段集与 `checks` 键名逐字对齐 §A.8.4：**软依赖用 `*_reachable`，硬依赖用原名**。

    两处不同名是刻意的（readiness 面向编排、聚合面向 UI），所以这里既断言"没有私增字段"
    也断言"没有把两套键名统一掉"——后者看起来像清理，实际会同时打断两拨消费方。
    """
    status_code, body = _json(client, "/api/v1/healthz")
    assert status_code == 200
    assert set(body) == _AGGREGATE_KEYS, f"payload 字段集漂移（C-13）：{sorted(body)}"
    expected_checks = {"graph_compiled", "embedding_model", "embedding_dim"} | set(
        health._AGGREGATE_CHECK_KEYS.values()
    )
    assert set(body["checks"]) == expected_checks, f"checks 键集漂移：{sorted(body['checks'])}"
    assert "probe_detail" not in body and "probe_detail" not in body["checks"], (
        "`probe_detail` 又回到了响应体 —— 它是 §A.8.4 里没有的私增字段，原因只该进 WARN 日志"
    )
    assert body["checks"]["graph_compiled"] is False, "无 lifespan ⇒ 图上不应该是 True（True 就是假仪表）"


def test_aggregate_soft_failure_is_200_degraded(client: TestClient, healthy: dict[Dependency, bool]) -> None:
    """§A.8.4 的"关键修正"：仅软依赖失败 ⇒ **200 + `status: degraded`**（原设计写 503 是错的）。"""
    healthy[Dependency.EMBEDDING] = False
    status_code, body = _json(client, "/api/v1/healthz")
    assert status_code == 200
    assert body["status"] == HealthStatus.DEGRADED.value
    assert body["degraded_dependencies"] == [Dependency.EMBEDDING.value]
    assert body["checks"]["embedding_reachable"] is False
    assert body["checks"]["llm_reachable"] is True, "两个软依赖被合成一个信号 ⇒ 分不清是 Ollama 还是对话模型挂了"


def test_aggregate_hard_failure_is_503_unhealthy(client: TestClient, healthy: dict[Dependency, bool]) -> None:
    """硬依赖挂时 `status` 必须是 `unhealthy` 且 HTTP 503 —— 与"降级"是两种颜色，不得混。"""
    healthy[Dependency.METADATA_DB] = False
    healthy[Dependency.LLM] = False
    status_code, body = _json(client, "/api/v1/healthz")
    assert status_code == 503
    assert body["status"] == HealthStatus.UNHEALTHY.value
    assert body["degraded_dependencies"] == [Dependency.LLM.value], (
        "unhealthy 时仍要如实列出降级的软依赖：两者并存是常见形态（DB 挂了同时 LLM 也挂了）"
    )


def test_failed_probe_reasons_land_in_logs_not_payload(
    client: TestClient, healthy: dict[Dependency, bool], capsys: pytest.CaptureFixture[str]
) -> None:
    """`detail` 换了承载位（响应体 → WARN），所以必须有一处钉住"原因仍然拿得到"。

    否则这次的收敛就成了"把可观测性删掉"而不是"搬到正确的层"。
    （`structlog` 的 logger_factory 是 PrintLogger，写 stdout ⇒ 用 capsys 而不是 caplog。）
    """
    healthy[Dependency.REDIS] = False
    capsys.readouterr()  # 丢掉建 app 时的启动输出
    _, body = _json(client, "/api/v1/healthz/ready")
    out = capsys.readouterr().out

    assert "healthz_failed_probes" in out, "探针失败原因既不在响应体也不在日志 ⇒ 值班只能盲猜"
    assert Dependency.REDIS.value in out
    assert "probe_detail" not in str(body), "`detail` 又漏回响应体了（§A.8.4 没有这个字段）"


# ===========================================================================
# 四、drain 闸门（§18.3 第 1~2 步的触发面）
# ===========================================================================


def test_drain_endpoint_is_disabled_without_a_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """**fail-closed**：`DRAIN_TOKEN` 未设 ⇒ 一律 403。

    这条路由的语义是"让本机开始停机"。无鉴权暴露 = 任何能打到端口的人都能反复触发重启。
    """
    monkeypatch.delenv(health.DRAIN_TOKEN_ENV, raising=False)
    assert client.post("/api/v1/healthz/drain").status_code == 403
    monkeypatch.setenv(health.DRAIN_TOKEN_ENV, "right")
    assert client.post("/api/v1/healthz/drain", headers={"X-Drain-Token": "wrong"}).status_code == 403


def test_drain_begun_flips_readiness_to_503_without_touching_probes(
    client: TestClient, healthy: dict[Dependency, bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§18.3 第 1 步的可验证部分：**摘流量不是"依赖坏了"**。

    ⇒ 探针全绿 + `draining: true` + 503。若实现成"把 readiness 探针改脏"，
    运维会去查一个根本不存在的依赖故障。
    """
    monkeypatch.setenv(health.DRAIN_TOKEN_ENV, "tok")
    assert client.get("/api/v1/healthz/ready").status_code == 200

    response = client.post("/api/v1/healthz/drain", headers={"X-Drain-Token": "tok"})
    assert response.status_code == 202
    assert response.json() == {"draining": True, "inflight": 0}

    status_code, body = _json(client, "/api/v1/healthz/ready")
    assert status_code == 503
    assert body["draining"] is True
    assert all(body["checks"].values()), "drain 期间不该顺手把依赖判成不健康"

    assert client.get("/api/v1/healthz/drain").json() == {"draining": True, "inflight": 0}
    assert _json(client, "/api/v1/healthz")[0] == 200, "drain 不是依赖故障 ⇒ 聚合详情不得转红"
