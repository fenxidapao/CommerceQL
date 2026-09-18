"""W7 观测层与 L5 帧契约之间的**接缝**断言（07 §14.3 / §15.3 / §18.3；附录 A §A.1.4）。

归属窗口：W7。

## 为什么这些断言非有不可
`app/obs/instrumentation.py` 在 **L1**，按 R-DEP-1 **不许** import `app.api.sse`（L5）。
于是它必须自带两份"抄来的事实"：SSE 的 `content-type` 子串、帧分隔符 `\n\n`。
抄来的东西一旦漂移，后果**不是报错而是静默失效**：
· `content-type` 漂了 ⇒ 中间件认不出 SSE 流 ⇒ 在途流登记为空 ⇒ **优雅停机不 drain**，
  而且没有任何一处会红；
· 分隔符漂了 ⇒ 帧解析切不开 ⇒ §14.3 的独立复算全部落空 ⇒ `ui_contract_violation_total`
  恒为 0，看起来"契约零违规"。
所以这两份常量必须由测试**钉在真实现上**。

## 另一件本文件钉住的事
停机时注入给客户端的那一帧，是 L5 的编码器产出、L1 的观测器复核的。
两端的理解必须一致：客户端拿到 `terminal: true` ⇒ 观测器判"已终态" ⇒ 不记 `stream_without_terminal`。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import sse
from app.core.enums import ErrorCode, SseEvent
from app.obs import instrumentation, metrics
from app.obs.instrumentation import (
    DRAIN_MESSAGE,
    InFlightRegistry,
    ObservingMiddleware,
    _StreamObserver,
)

pytestmark = pytest.mark.contract

_START: dict[str, Any] = {
    "type": "http.response.start",
    "status": 200,
    "headers": [(b"content-type", sse.SSE_MEDIA_TYPE.encode())],
}


def _body(frame: bytes, *, closing: bool = False) -> dict[str, Any]:
    return {"type": "http.response.body", "body": frame, "more_body": not closing}


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.fixture(autouse=True)
def _clean_metrics() -> Iterator[None]:
    """指标注册表是**进程级全局**：不复位，后面的 `== 0` / `== 1` 断言就只是"顺序运气"。"""
    metrics.reset_for_tests()
    yield
    metrics.reset_for_tests()


# ---------------------------------------------------------------------------
# 1. L1 里两份"抄来的事实"必须与 L5 真实现一致
# ---------------------------------------------------------------------------

def test_sse_content_type_copy_matches_the_encoder() -> None:
    """漂移后果：中间件认不出 SSE ⇒ 在途流登记为空 ⇒ **停机不 drain**（且无一处报错）。"""
    assert instrumentation._SSE_MEDIA == sse.SSE_MEDIA_TYPE, (
        "`app.api.sse.SSE_MEDIA_TYPE` 已改动而 L1 的副本没跟上 —— "
        "R-DEP-1 不许 obs import api，所以这里只能是**测试**来对齐两者，而不是 import"
    )


def test_frame_separator_copy_matches_the_encoder() -> None:
    """漂移后果：帧切不开 ⇒ §14.3 独立复算落空 ⇒ `ui_contract_violation_total` 恒 0。"""
    encoded = sse.encode(SseEvent.HEARTBEAT, {})
    assert encoded.endswith(instrumentation._FRAME_SEP), "encode 的帧尾与观测器的分隔符不一致"
    assert instrumentation._FRAME_SEP == b"\n\n"
    # 单帧内部不得提前出现分隔符，否则一条消息会被切成两半（`feed` 按它切帧）
    assert encoded[: -len(instrumentation._FRAME_SEP)].count(instrumentation._FRAME_SEP) == 0


def test_endpoint_label_cap_matches_the_metric_domain() -> None:
    """两处上界必须同值：中间件的 `unmatched` 预留位是按它算的。

    不同值的失效方向很隐蔽：中间件放行了 20 个 endpoint，而指标层把第 20 个当越界丢弃
    （并计入 `metric_label_overflow_total`）⇒ 看板少一条曲线，且看起来像"应用乱打标签"。
    """
    assert metrics.BOUNDED_ALLOWED_LABELS["endpoint"] == instrumentation.ENDPOINT_LABEL_CAP


def test_ui_violation_kinds_stay_inside_the_declared_cardinality() -> None:
    """§15.3 的基数闸门：取值域长度不得超过标签键上界（超了下一次 inc 直接被丢弃）。"""
    assert len(metrics.UI_CONTRACT_VIOLATION_KINDS) <= metrics.BOUNDED_ALLOWED_LABELS["kind"]
    # 约束 1（终态漏标志）与约束 2（非终止事件谎称终止）**必须**是两个不同的 kind：
    # 它们的修法在完全不同的代码路径上，合并计数会把值班人引向反方向。
    assert "non_terminal_claims_terminal" in metrics.UI_CONTRACT_VIOLATION_KINDS


# ---------------------------------------------------------------------------
# 2. 停机注入帧：L5 产出 ⇔ L1 复核
# ---------------------------------------------------------------------------

def test_drain_frame_is_a_wellformed_terminal_error() -> None:
    """`main._drain_terminal_frame()` 的形状逐字段核对（附录 A §A.1.2 的 error 事件）。"""
    from app.api import errors
    from app.main import _drain_terminal_frame

    raw = _drain_terminal_frame()
    assert raw.startswith(b"event: error\n") and raw.endswith(b"\n\n")
    payload = json.loads(raw.split(b"data: ", 1)[1])
    assert payload["terminal"] is True, "缺 terminal=true = 前端停在加载态（N-08）"
    assert payload["code"] == ErrorCode.INTERNAL.value
    assert payload["message"] == DRAIN_MESSAGE, "文案是 §18.3 给定的那句，不得自行改写"
    assert payload["retryable"] is errors.map_code(ErrorCode.INTERNAL).retryable
    assert "node" not in payload, "06 D2 红线：内部节点名只进日志，不进 data"


def test_injected_frame_is_judged_terminal_by_the_observer() -> None:
    """L5 编码器产出的那一帧，L1 观测器必须读成"已终态"。

    否则会出现最坏的组合：客户端正常关流了，而 `stream_without_terminal` 还在涨 ——
    "非零即 P0"的指标被自己的观测器污染，值班人顺着它去查一条没问题的链路。
    """
    from app.main import _drain_terminal_frame

    registry = InFlightRegistry()
    stream = registry.register("/api/v1/query")
    observer = _StreamObserver(stream)
    observer.observe(observer.feed(_drain_terminal_frame()))
    assert stream.seen_terminal and stream.terminal_event == "error"
    observer.finalize()
    assert metrics.UI_CONTRACT_VIOLATION_TOTAL.total() == 0


async def test_drain_bytes_reach_the_client_and_count_as_failed() -> None:
    """端到端（仍是离线 ASGI）：drain 期间的一帧 SSE 真的拿到终止帧并计入 `outcome=failed`。

    这条是本文件的落点：前两条各自成立（帧合法 / 观测器认得），但只有走一遍中间件
    才能证明"客户端实际收到的字节"里带 `terminal: true`。
    """
    from app.main import _drain_terminal_frame

    registry = InFlightRegistry()
    registry.begin_drain()
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send(_START)
        await send(_body(sse.encode(SseEvent.STAGE, {"stage": "intent", "elapsed_ms": 12})))
        await send(_body(b""))  # 不该走到这里：上一条已被 drain 中止

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    mw = ObservingMiddleware(app, registry=registry, terminal_error_frame=_drain_terminal_frame)
    with pytest.raises(BaseException) as raised:  # _DrainAbort 故意穿透 except Exception
        await mw({"type": "http", "path": "/api/v1/query", "method": "POST"}, _noop_receive, send)
    assert type(raised.value).__name__ == "_DrainAbort"

    assert _drain_terminal_frame() in [m.get("body") for m in sent], "终止帧没真的发出去"
    assert metrics.QUERY_OUTCOME_TOTAL.value(outcome="failed") == 1
    assert metrics.UI_CONTRACT_VIOLATION_TOTAL.total() == 0
    assert registry.count() == 0, "中止后必须从在途表里摘掉，否则 drain 永远等不完"


def test_gate_code_copy_matches_the_graph_verdict_table() -> None:
    """L1 那份"闸门拒绝码 → 闸门编号"必须与 L4 的判定表**逐项相等**（R-DEP-1 不许 import）。

    漂移的后果不是报错，而是**归错闸门**：例如 `COST_TOO_HIGH` 从表里漏掉，
    闸门三的全部拒绝会静默落到 `gate_no=""`（= 不计数），看板上的成本闸门曲线归零，
    而"闸门工作正常"这个结论仍然看起来成立。
    """
    from app.graph.nodes import error_out

    mirrored = {code: gate for gate, code in error_out._GATE_CODE.items()}
    assert dict(instrumentation._GATE_NO_BY_ERROR_CODE) == mirrored, (
        "`app/graph/nodes/error_out.py::_GATE_CODE` 与本文件的镜像不一致 ⇒ 闸门拒绝会计错编号"
    )


# ---------------------------------------------------------------------------
# 3. 导出面与"自抓取不计数"
# ---------------------------------------------------------------------------

def _http_request_sample_lines(text: str) -> set[str]:
    """取 exposition 里 `http_requests_total` 的**样本行**（不含 `#` 注释行）。"""
    return {
        line
        for line in text.splitlines()
        if line.startswith("http_requests_total{")
    }


#: 正向对照用的路径：**未注册**（必然 404）、不在自跳过前缀下、且不会被
#: `normalize_endpoint` 归一化成 ID 段（名字里没有数字/UUID 形状）。
_CONTROL_PATH = "/api/v1/unregistered-control-endpoint"


def test_middleware_is_installed_by_create_app_and_skips_self_scrape_paths() -> None:
    """自跳过前缀的两面：**确实是真路由** + **确实不计数**。

    ⚠️ 为什么不是"扫路由表"（本测试的第一版写法）：这个 FastAPI 版本的 `include_router`
    产生惰性的 `_IncludedRouter`，路由项上根本没有 `.path`（前缀在匹配时才拼），
    于是 `create_app().routes` 自省只会看到 docs/openapi 四条 —— 那会把"中间件没装"
    和"路由不存在"混成同一个假红。**行为**不受这个实现细节影响，所以只断言行为。

    正向对照（`_CONTROL_PATH` 必须被计数）是关键：没有它，"healthz 没有样本行"
    可以是"前缀跳过生效"，也可以是"整个中间件压根没装配"，两者在看板上长得一样。
    """
    from app.main import create_app

    # `raise_server_exceptions=False`：探针在**无 lifespan**（无池、探针未注册）下可能抛，
    # 那不是本测试的判据；这里只关心"有没有被计数"。404 才是"路由不存在"的唯一信号。
    client = TestClient(create_app(), raise_server_exceptions=False)

    assert client.get(_CONTROL_PATH).status_code == 404
    control = _http_request_sample_lines(client.get("/api/v1/metrics").text)
    assert control, "正向对照失败：ObservingMiddleware 没被 create_app() 装进去 ⇒ 整个 §15.3 采集面都是空的"
    assert len(control) == 1, f"对照请求应当只留下一条样本行，实际 {control}"
    assert f'endpoint="{_CONTROL_PATH}"' in next(iter(control)), (
        f"对照请求被记成了别的 endpoint：{control}"
    )

    routed = {
        "/api/v1/healthz",
        "/api/v1/healthz/live",
        "/api/v1/healthz/ready",
        "/api/v1/metrics",
    }
    for path in sorted(routed):
        response = client.get(path)
        assert response.status_code != 404, (
            f"{path} 无路由：`_SELF_SCRAPE_PREFIXES` 里的这条前缀已经守不住任何东西"
            f"（拼错的路径永远匹配不上，日后改名同样静默失效）"
        )
    assert _http_request_sample_lines(client.get("/api/v1/metrics").text) == control, (
        "抓取自计数 ⇒ 错误率会被 Prometheus/LB 的探测节奏主导（07 §15.3）"
    )


def test_metrics_endpoint_serves_exposition_and_hides_itself() -> None:
    """`/api/v1/metrics` 的媒体类型：Prometheus 只认 `text/plain; version=0.0.4`。

    非自计数那一半放在上一个测试里（那里有正向对照，能区分"跳过了"与"没装"）；
    本测试只管导出面的形状。⚠️ 只断言**已产生样本**的 family：注册表刻意不输出空
    family（§15.3 纪律②：宁缺不假），所以先打一次真实请求再取文本。
    """
    from app.main import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    client.get(_CONTROL_PATH)  # 制造一个真实样本（同时证明中间件在链路里）

    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"] == metrics.PROMETHEUS_CONTENT_TYPE
    text = response.text
    assert "# TYPE http_requests_total counter" in text
    # 对照请求要以**自己的路径**出现在标签里。注意 `unmatched` 是"endpoint 数超过 20 上限"
    # 之后的溢出桶，**不是**"未注册路径"的桶 —— 未注册路径照样按归一化结果单独计数。
    assert f'endpoint="{_CONTROL_PATH}"' in text, "正向对照没有被计数 ⇒ 中间件不在链路上"
    for self_scrape in instrumentation._SELF_SCRAPE_PREFIXES:
        assert f'endpoint="{self_scrape}"' not in text, (
            f"{self_scrape} 出现在自己的 `endpoint` 标签里 ⇒ 抓取流量污染了 QPS/错误率"
        )
