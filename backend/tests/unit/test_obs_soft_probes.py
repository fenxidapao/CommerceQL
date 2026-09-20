"""`app/obs/probes.py` 的软依赖探针语义测试（U-108 / 07 §18.2）。

为什么这个模块以前**一个测试都没有**：它的判据全在 `healthy` 一个布尔上，而 `/healthz` 的
载荷契约由 `tests/contract/test_health_endpoints_contract.py` 钉着 —— 于是"探针自己说什么"
成了没人看的缝，U-108 那个假负就是从这条缝里漏出来的。这里补的是那条缝。

桩法是 `httpx.MockTransport`（不碰网络、不烧额度），加一个 `_log` 替身来拿 WARN 事件 ——
不用 `caplog`：structlog 的渲染层在本项目里是自定义的，靠日志文本反查事件名会随渲染器改动而失效。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest

from app.core.enums import Dependency
from app.obs import probes


class _LogSpy:
    """替身：只记录 `(event, kwargs)`，不渲染。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.records.append((event, kwargs))

    def info(self, event: str, **kwargs: Any) -> None:
        self.records.append((event, kwargs))

    @property
    def slow_events(self) -> list[dict[str, Any]]:
        return [kw for event, kw in self.records if event == "probe_slow"]


@pytest.fixture
def log_spy(monkeypatch: pytest.MonkeyPatch) -> _LogSpy:
    spy = _LogSpy()
    monkeypatch.setattr(probes, "_log", spy)
    return spy


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _counting(handler: Any) -> tuple[httpx.MockTransport, list[int]]:
    calls: list[int] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return handler(request)

    return httpx.MockTransport(wrapped), calls


# ---------------------------------------------------------------------------
# U-108 ①：复用连接（旧实现每次探测新建客户端 ⇒ 探针实测的是握手耗时）
# ---------------------------------------------------------------------------


def test_probe_does_not_construct_a_client_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归钉：一个探测周期内**只允许构造一个** `AsyncClient`。

    这是 U-108 的根因本身。旧代码 `async with _client()` 每次新建 ⇒ 三次探测三次握手，
    于是"上游慢不慢"量的其实是"这次 TCP+TLS 握手抖没抖"（实测建连 p95 4.09s）。
    """
    built: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def spy_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        client = real(*args, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(probes.httpx, "AsyncClient", spy_client)
    transport, calls = _counting(lambda request: httpx.Response(401))

    async def run() -> None:
        probe = probes.make_llm_probe("https://deepseek.test", transport=transport)
        for _ in range(3):
            assert (await probe()).healthy is True

    asyncio.run(run())
    assert len(calls) == 3, "探测本身要跑三次"
    assert len(built) == 1, f"每次探测新建客户端的形态回来了（构造了 {len(built)} 个）"


def test_keepalive_expiry_outlives_the_ui_poll_interval() -> None:
    """复用要跨得过 UI 的 30s 轮询才成立。

    httpx 默认 `keepalive_expiry=5s` ⇒ 若照默认值配，第二次探测必然重新握手，
    "修了复用"和"没修"在探针耗时上**没有区别**（这是最容易假装修好的一条）。
    """
    assert probes._KEEPALIVE_EXPIRY_S > 30.0


def test_client_is_rebuilt_when_the_event_loop_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """跨循环不复用：`AsyncClient` 的连接池绑死在首次使用它的循环上。

    生产只有一个循环（复用真的成立）；测试里一个用例一个循环，所以这条路径必然被走到。
    若反过来允许跨循环复用，拿到的是"看着活着、一 send 就炸"的池 —— 那是另一种假负。
    """
    built: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def spy_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        client = real(*args, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(probes.httpx, "AsyncClient", spy_client)
    transport, calls = _counting(lambda request: httpx.Response(200))
    probe = probes.make_llm_probe("https://deepseek.test", transport=transport)

    asyncio.run(probe())
    asyncio.run(probe())

    assert len(calls) == 2, "两次探测都要真跑到 transport"
    assert len(built) == 2, f"换循环必须重建客户端，实际构造 {len(built)} 个"
    assert built[0].is_closed is True, "旧循环那一份要被尽力关掉，不能留在池里"


# ---------------------------------------------------------------------------
# U-108 ②：两个探针不共用常量
# ---------------------------------------------------------------------------


def test_the_two_probes_do_not_share_one_timeout() -> None:
    """公网 DeepSeek 与本机 Ollama 的时延形态差三个数量级（实测 p95 4,087ms vs 6ms）。"""
    assert probes.LLM_PROBE_TIMEOUT_S != probes.EMBEDDING_PROBE_TIMEOUT_S
    assert probes.LLM_PROBE_SLOW_S != probes.EMBEDDING_PROBE_SLOW_S
    assert probes.LLM_PROBE_TIMEOUT_S > probes.EMBEDDING_PROBE_TIMEOUT_S

    # ⚠️ 光比常量本身挡不住"接错线"：把 embedding 工厂改成取 LLM 的常量，上面三条照样绿
    # （本轮一条变异实测到的空档）。所以要验到**每个工厂实际用了哪个**。
    before = set(map(id, probes._CACHES))
    probes.make_llm_probe("https://deepseek.test", transport=_transport(lambda r: httpx.Response(200)))
    probes.make_embedding_probe(
        "http://ollama.test", "bge-m3", transport=_transport(lambda r: httpx.Response(200))
    )
    fresh = [c for c in probes._CACHES if id(c) not in before]
    assert [c["timeout_s"] for c in fresh] == [
        probes.LLM_PROBE_TIMEOUT_S,
        probes.EMBEDDING_PROBE_TIMEOUT_S,
    ], "两个探针各自绑自己的门限"


def test_constants_carry_their_measured_source_in_the_module_text() -> None:
    """U-22 纪律的可执行版本：门限旁边必须有出处，否则下一个人只会看到一个魔法数。"""
    import inspect

    source = inspect.getsource(probes)
    assert "p95" in source, "两个超时常量的注释里要留实测出处（p95），不许裸给数字"
    assert "healthcheck.timeout" in source or "5s" in source, (
        "要留「探针不占附录 D 的 5s 预算」这条，否则下一个人又会为了塞进 5s 把阈值压回去"
    )


# ---------------------------------------------------------------------------
# U-108 ③：判据与门限分离 —— healthy=false 只表示"真不可达"
# ---------------------------------------------------------------------------


async def test_slow_but_answered_is_healthy_plus_warn(
    monkeypatch: pytest.MonkeyPatch, log_spy: _LogSpy
) -> None:
    """**慢不得翻转成不可达** —— 这条就是 U-108 立项时那个假负的正面写法。"""
    monkeypatch.setattr(probes, "LLM_PROBE_SLOW_S", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.02)  # 阻塞式 sleep：让 elapsed 必然越过被压低到 0 的"慢"线
        return httpx.Response(401)

    probe = probes.make_llm_probe("https://deepseek.test", transport=_transport(handler))
    result = await probe()

    assert result.dependency is Dependency.LLM
    assert result.healthy is True, "拿到了 HTTP 响应就是可达；慢只能在 detail/日志里表达"
    assert len(log_spy.slow_events) == 1
    event = log_spy.slow_events[0]
    assert event["dependency"] == "llm" and event["elapsed_ms"] >= 20


async def test_fast_path_stays_quiet(monkeypatch: pytest.MonkeyPatch, log_spy: _LogSpy) -> None:
    probe = probes.make_llm_probe(
        "https://deepseek.test", transport=_transport(lambda request: httpx.Response(401))
    )
    assert (await probe()).healthy is True
    assert log_spy.slow_events == [], "没慢却发 WARN = 告警疲劳，跟假负一样有害"


async def test_connect_layer_failure_is_unreachable() -> None:
    probe = probes.make_llm_probe(
        "https://deepseek.test",
        transport=_transport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("no route"))),
    )
    result = await probe()
    assert result.healthy is False
    assert "连接层失败" in result.detail


async def test_connect_timeout_is_a_connection_failure_not_a_read_timeout() -> None:
    """httpx 里 `ConnectTimeout` 只是 `TimeoutException` 的子类，与 `ConnectError` **是兄弟**。

    ⇒ 不显式先判它，握手超时就会掉进通用超时分支、被写成"连接已建立但没响应"。
    两句的排查方向相反（一个查网络/DNS/出口，一个查上游进程），所以这条钉的是**措辞的正确性**。
    """
    request = httpx.Request("GET", "https://deepseek.test")
    probe = probes.make_llm_probe(
        "https://deepseek.test",
        transport=_transport(
            lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("handshake", request=request))
        ),
    )
    result = await probe()
    assert result.healthy is False
    assert "连接层失败" in result.detail, result.detail


async def test_pool_timeout_is_not_reported_as_an_established_connection() -> None:
    """`PoolTimeout` = 本地池没给出连接、请求**没发出去** ⇒ 也不能说成"连接已建立"。"""
    request = httpx.Request("GET", "https://deepseek.test")
    probe = probes.make_llm_probe(
        "https://deepseek.test",
        transport=_transport(
            lambda r: (_ for _ in ()).throw(httpx.PoolTimeout("busy", request=request))
        ),
    )
    result = await probe()
    assert result.healthy is False
    assert "没给出连接" in result.detail and "连接已建立" not in result.detail, result.detail


async def test_read_timeout_is_unreachable_but_named_as_no_response() -> None:
    request = httpx.Request("GET", "https://deepseek.test")
    probe = probes.make_llm_probe(
        "https://deepseek.test",
        transport=_transport(
            lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("stalled", request=request))
        ),
    )
    result = await probe()
    assert result.healthy is False  # 超过松弛上界（§18.2 ③ 明写这一档仍算不可达）
    assert "连接已建立" in result.detail and "没走完一次请求" in result.detail


# ---------------------------------------------------------------------------
# embedding 探针：U-108 只裁"慢 vs 没接"这一根轴，另两条判据不许顺手改
# ---------------------------------------------------------------------------


async def test_embedding_reports_healthy_with_model_listed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "bge-m3:latest"}]})

    probe = probes.make_embedding_probe("http://ollama.test/", "bge-m3", transport=_transport(handler))
    result = await probe()
    assert result.dependency is Dependency.EMBEDDING
    assert result.healthy is True
    assert "在列" in result.detail


async def test_embedding_http_error_stays_unhealthy() -> None:
    """5xx/4xx 不是"慢"。把它一并改成 healthy=true 会是另一处越权。"""
    probe = probes.make_embedding_probe(
        "http://ollama.test", "bge-m3", transport=_transport(lambda request: httpx.Response(500))
    )
    assert (await probe()).healthy is False


async def test_embedding_missing_model_stays_unhealthy() -> None:
    """本项目实测过的真实故障形态：服务活着、模型没拉 ⇒ 检索静默退化成 sparse_only。"""
    probe = probes.make_embedding_probe(
        "http://ollama.test",
        "bge-m3",
        transport=_transport(
            lambda request: httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
        ),
    )
    result = await probe()
    assert result.healthy is False
    assert "未加载模型 bge-m3" in result.detail


# ---------------------------------------------------------------------------
# 停机：复用引入的出站连接必须还得回去（07 §18.3 第 4 步）
# ---------------------------------------------------------------------------


async def test_warm_skips_probes_bound_to_a_mock_transport() -> None:
    """暖身会真发一次请求 ⇒ 绑了替身 transport 的探针必须被跳过。

    否则 lifespan 里那句 `warm_probe_connections()` 会去遍历别的用例留在 `_CACHES` 里的
    `*.test` 域名，把真 DNS 查询带进启动路径 —— 那是"测试污染生产计时"的经典形态。
    """
    transport, calls = _counting(lambda request: httpx.Response(200))
    probes.make_llm_probe("https://deepseek.test", transport=transport)
    warmed = await probes.warm_probe_connections()
    assert calls == [], "暖身不得替探针发出请求"
    assert "https://deepseek.test" not in warmed, (
        "绑了替身的目标不该进暖身结果 —— 刻意**不**断言整个 dict 为空：全量跑时"
        "别的用例会经 lifespan 建出真 URL 的缓存，那会让本条变成顺序依赖的假红"
    )


async def test_aclose_probe_clients_closes_reused_clients() -> None:
    transport, _ = _counting(lambda request: httpx.Response(200))
    probe = probes.make_llm_probe("https://deepseek.test", transport=transport)
    await probe()
    cache = next(c for c in probes._CACHES if c["transport"] is transport)
    client = cache["client"]
    assert client.is_closed is False

    assert await probes.aclose_probe_clients() >= 1
    assert client.is_closed is True, "复用之后不关 = 停机路径漏了出站这一半"
    assert "client" not in cache, "关闭后不得再持有一个死客户端（下一次探测会新建）"


async def test_probe_still_works_after_a_close() -> None:
    """`aclose` 之后再来一次探测要能自愈（lifespan 测试里两种顺序都出现过）。"""
    transport, calls = _counting(lambda request: httpx.Response(200))
    probe = probes.make_embedding_probe("http://ollama.test", "bge-m3", transport=transport)
    await probe()
    await probes.aclose_probe_clients()
    assert (await probe()).healthy is True
    assert len(calls) == 2
