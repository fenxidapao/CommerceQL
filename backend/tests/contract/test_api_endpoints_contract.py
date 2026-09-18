"""W4 端点的**契约测试** —— 四个 router 的 HTTP 面（附录 A §A.1–§A.5 / §A.11–§A.13）。

层号：L5｜归属窗口：W4（`tests/contract/**`）。

## 本文件与 `test_api_runner_contract.py` 的分工

| 文件 | 覆盖 |
|---|---|
| `test_api_runner_contract.py` | **生成器内部**：出帧顺序、N-08 唯一性、心跳、取消轮询、任务状态投影（不起 HTTP） |
| **本文件** | **HTTP 面**：路径/状态码/响应头/封套形状/身份与所有权/限流分桶/幂等/会话与澄清 |

⚠️ 为什么必须分开：生成器全绿**不代表**端点对 —— 端点的缺陷集中在
"HTTP 状态与响应头"这一层（`409` 不带 `X-RateLimit-*`、`404` 不泄露所有权、
`422` 与 `400` 不混用），而它们在生成器层根本不可见。

## 刻意**不**测的东西（避免假绿灯）

- **真 Redis 的限流/锁语义**：`tests/integration/test_real_redis_*`（那里的脚本位序只有真 Redis 能证）；
- **真图的业务结论**：本文件用 `mode` 脚本化的 planner（同 `test_graph_wiring.py` 的取舍），
  验的是"图跑完后端点怎么表达"，不是"问句解析对不对"（后者归 W3 的评测）；
- **真 LLM / 真数据库**：全离线。

## 装配方式（⚠️ 不跑 lifespan）

`TestClient(app)` 不用 `with`：`lifespan` 里有真 I/O（连库、开池、跑启动断言），
跑它就不再是离线契约测试了。改为手工把 `AppRuntime` / `GraphRuntime` 放进 `app.state` ——
它们都是**纯构造**（`build_runtime` 不做 I/O，`GraphRuntime` 只是装箱）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, GraphRuntime, build_runtime
from app.api.routers import clarify, query, session
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.config import get_settings
from app.core.contracts import IdentityContext
from app.core.enums import RateLimitBucket, Role
from app.graph.build import build_graph
from tests.contract.test_api_runner_contract import _DepsHolder
from tests.unit._redis_fake import FakeRedis

#: 路径前缀。⚠️ **写死而不用 `app.main.API_PREFIX`**：契约测试要钉住的正是
#: "前缀就是 `/api/v1`"这件事；import 过来等于把被测对象当期望值（改坏了也不红）。
API_PREFIX = "/api/v1"

_OPERATOR = VerifiedToken(
    subject="u_001",
    tenant_id="t_001",
    role=Role.OPERATOR,
    scope_claims=(),
    shop_ids=(),
    jti="jti-1",
    issued_at=datetime.now(UTC) - timedelta(minutes=1),
    expires_at=datetime.now(UTC) + timedelta(hours=1),
    kid="kid-1",
)


class _StubVerifier:
    """验签替身：**只**返回注入的令牌，不解析 `Authorization`。

    ⚠️ 这样做的代价与收益要写清：收益是本文件不依赖 JWT 构造链（`app/auth/**` 有它自己的
    契约测试）；代价是"端点忘了检查 `Authorization` 头"这类缺陷**本文件测不出来** ——
    故另有一条 `test_missing_authorization_is_rejected` 直接调真验签链路（用不存在的公钥路径
    ⇒ 必失败），把"端点确实把身份来源交给验签器"这条钉住。
    """

    def __init__(self, token: VerifiedToken = _OPERATOR) -> None:
        self.token = token
        self.calls = 0

    async def verify(self, authorization: str | None) -> VerifiedToken:
        self.calls += 1
        return self.token


def _client(
    mode: str = "refuse_intent", *, verifier: _StubVerifier | Any = None
) -> tuple[TestClient, GraphRuntime, FakeRedis]:
    """造一个**离线可用**的应用：真实 router + 替身依赖。"""
    fake = FakeRedis()
    settings = get_settings()
    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(query.router, prefix=API_PREFIX)
    app.include_router(session.router, prefix=API_PREFIX)
    app.include_router(clarify.router, prefix=API_PREFIX)

    setattr(
        app.state,
        RUNTIME_STATE_KEY,
        build_runtime(
            settings=settings,
            pools=_pools(),
            redis=fake,  # type: ignore[arg-type]
        ),
    )
    store = RedisStateStore(fake)  # type: ignore[arg-type]
    holder = _DepsHolder(mode)
    graph_runtime = GraphRuntime(
        graph=build_graph(),
        store=store,
        verifier=verifier if verifier is not None else _StubVerifier(),  # type: ignore[arg-type]
        new_deps=holder,
    )
    setattr(app.state, GRAPH_RUNTIME_STATE_KEY, graph_runtime)
    return TestClient(app, raise_server_exceptions=False), graph_runtime, fake


def _pools() -> Any:
    from app.repo.pools import build_three_pools

    return build_three_pools(get_settings())


def _auth(token: VerifiedToken | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer stub.token.value"}
    if token is not None:
        headers["X-Test-Tenant"] = token.tenant_id
    return headers


def _frames(raw: bytes) -> list[tuple[str, dict[str, Any]]]:
    """SSE 字节流 → `[(event, data), …]`（只服务断言，不复用 `sse.encode`）。"""
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in raw.decode().split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        parsed.append((event, data))
    return parsed


def _post_query(client: TestClient, **body: Any) -> Any:
    payload: dict[str, Any] = {"question": "上个月华东区GMV是多少"}
    payload.update(body)
    return client.post(f"{API_PREFIX}/query", json=payload, headers=_auth())


# ===========================================================================
# 一、会话（附录 A §A.5）
# ===========================================================================


class TestSessionEndpoints:
    def test_create_session_returns_ok_envelope_and_write_bucket(self) -> None:
        """`POST /session` → `code=OK` + `session_id`，且**写入类桶**的限流四头齐全。"""
        client, _, _ = _client()
        resp = client.post(f"{API_PREFIX}/session", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "OK", "2xx 但 code!=OK 前端会按错误处理（§A.0.4）"
        assert body["data"]["session_id"].startswith("ss_")
        assert body["data"]["created_at"]
        assert body["trace_id"], "错误与成功响应都应带 trace_id"
        # 逐桶下发（W5 RELAY §1.4）
        assert resp.headers["X-RateLimit-Bucket"] == RateLimitBucket.WRITE.value

    def test_create_session_does_not_accept_title(self) -> None:
        """§A.5.1 的 B-19 修订：客户端传 `title` → **422 显式拒绝**，不静默忽略。"""
        client, _, _ = _client()
        resp = client.post(
            f"{API_PREFIX}/session", json={"title": "偷偷写标题"}, headers=_auth()
        )
        assert resp.status_code == 400, "FastAPI 会把 extra=forbid 归为 RequestValidationError→400"
        assert resp.json()["code"] == "INVALID_REQUEST"

    def test_get_unknown_session_is_404(self) -> None:
        """404 与会话存在但无轮次（200 + 空列表）**必须**可区分（§A.5.2）。"""
        client, _, _ = _client()
        resp = client.get(f"{API_PREFIX}/session/ss_nope", headers=_auth())
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "SESSION_NOT_FOUND"
        assert body["suggestions"] is None, "❌ 档不得给 suggestions（§14.4 三级不对称）"

    def test_get_existing_session_without_turns(self) -> None:
        client, _, _ = _client()
        created = client.post(f"{API_PREFIX}/session", headers=_auth()).json()
        sid = created["data"]["session_id"]
        resp = client.get(f"{API_PREFIX}/session/{sid}", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["session_id"] == sid
        assert data["turns"] == []
        assert data["context_cursor"] is None, "P0 无历史消息载体 ⇒ 如实 None，不编游标"
        assert resp.headers["X-RateLimit-Bucket"] == RateLimitBucket.READ.value

    def test_get_session_never_returns_sql(self) -> None:
        """PRD FR-10.1：会话详情**不得**回原始 SQL（跨轮次持久化的可执行语句 = 越权模板）。"""
        client, _, _ = _client()
        created = client.post(f"{API_PREFIX}/session", headers=_auth()).json()
        sid = created["data"]["session_id"]
        resp = client.get(f"{API_PREFIX}/session/{sid}", headers=_auth())
        assert "sql" not in json.dumps(resp.json()["data"])


# ===========================================================================
# 二、查询 SSE（附录 A §A.1）
# ===========================================================================


class TestQueryStream:
    def test_missing_session_id_is_404_not_silent_new(self) -> None:
        """显式给了一个不存在的 `session_id` ⇒ 404；**不得**静默新开一个会话。"""
        client, _, _ = _client()
        resp = _post_query(client, session_id="ss_ghost")
        assert resp.status_code == 404
        assert resp.json()["code"] == "SESSION_NOT_FOUND"

    def test_stream_ack_first_and_exactly_one_terminal(self) -> None:
        """N-08 + W5 硬要求：**首个事件是 `ack`**（带 `task_id`），且恰有一个 `terminal:true`。"""
        client, _, _ = _client("refuse_intent")
        with client.stream("POST", f"{API_PREFIX}/query", json={"question": "x"}, headers=_auth()) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["X-Accel-Buffering"] == "no", "Nginx 不关缓冲则 SSE 被攒批"
            assert r.headers["X-RateLimit-Bucket"] == RateLimitBucket.QUERY.value
            frames = _frames(b"".join(r.iter_bytes()))

        assert frames and frames[0][0] == "ack"
        assert frames[0][1]["task_id"].startswith("tk_")
        assert frames[0][1]["terminal"] is False
        terminals = [d for _, d in frames if d.get("terminal") is True]
        assert len(terminals) == 1, "N-08：恰有一个 terminal:true"
        assert frames[-1][0] in {"refuse", "clarify", "error", "complete"}

    def test_refuse_path_writes_task_state_and_history(self) -> None:
        """拒答路径：任务状态落库（8 值之一）+ 首轮问题写进会话标题（§A.5.4）。"""
        client, _runtime, _ = _client("refuse_intent")
        created = client.post(f"{API_PREFIX}/session", headers=_auth()).json()
        sid = created["data"]["session_id"]
        with client.stream(
            "POST",
            f"{API_PREFIX}/query",
            json={"question": "上个月华东区GMV是多少", "session_id": sid},
            headers=_auth(),
        ) as r:
            frames = _frames(b"".join(r.iter_bytes()))
        task_id = frames[0][1]["task_id"]

        polled = client.get(f"{API_PREFIX}/query/{task_id}", headers=_auth())
        assert polled.status_code == 200
        assert polled.json()["data"]["status"] == "refused"

        detail = client.get(f"{API_PREFIX}/session/{sid}", headers=_auth()).json()["data"]
        assert len(detail["turns"]) == 1
        assert detail["turns"][0]["outcome"] in {
            "success",
            "clarify",
            "refuse",
            "degraded",
            "failed",
        }, "`TurnData.outcome` 是 Outcome（5 值），不是 TaskStatus（8 值）"

    def test_clarify_context_is_persisted_then_one_shot(self) -> None:
        """🔴 回归：澄清上下文必须由**接入层**存（图谱只产 `clarify_id`）。

        不存它 ⇒ `POST /clarify` 恒 `410`，而"前端拿到澄清卡、用户选了却没反应"
        会被误判成前端 bug。本用例走完整两跳：`/query`（澄清终态）→ `/clarify`（消费）。
        """
        client, _, _ = _client("time_unparsable")
        with client.stream("POST", f"{API_PREFIX}/query", json={"question": "x"}, headers=_auth()) as r:
            frames = _frames(b"".join(r.iter_bytes()))
        clarify_event = [d for e, d in frames if e == "clarify"]
        assert clarify_event, "该 mode 应产出澄清终态"
        clarify_id = clarify_event[0]["clarify_id"]

        first = client.post(
            f"{API_PREFIX}/clarify",
            json={"clarify_id": clarify_id, "free_text": "2026 年 8 月"},
            headers=_auth(),
        )
        assert first.status_code == 200, first.text
        clarify_frames = _frames(first.content)
        assert clarify_frames[0][0] == "ack", "澄清应答也是 SSE 流，且首帧仍是 ack"
        assert len([d for _, d in clarify_frames if d.get("terminal") is True]) == 1

        second = client.post(
            f"{API_PREFIX}/clarify",
            json={"clarify_id": clarify_id, "free_text": "2026 年 8 月"},
            headers=_auth(),
        )
        assert second.status_code == 410, "澄清上下文是**一次性**的（第二个请求必须 410）"
        assert second.json()["code"] == "CLARIFY_EXPIRED"

    def test_clarify_invalid_option_is_422_and_expired_is_410(self) -> None:
        """两个码**不得**混用：形状错 = DTO；值不在上下文里 = 422；上下文没了 = 410。"""
        client, _, _ = _client()
        unknown = client.post(
            f"{API_PREFIX}/clarify",
            json={"clarify_id": "cl_never_existed", "selected_value": "x"},
            headers=_auth(),
        )
        assert unknown.status_code == 410
        assert unknown.json()["code"] == "CLARIFY_EXPIRED"

        both = client.post(
            f"{API_PREFIX}/clarify",
            json={"clarify_id": "cl_x", "selected_value": "a", "free_text": "b"},
            headers=_auth(),
        )
        assert both.status_code == 400, "两个都给 = 请求形状错（INVALID_REQUEST）"
        assert both.json()["code"] == "INVALID_REQUEST"

    def test_session_conflict_409_has_no_ratelimit_headers(self) -> None:
        """§A.0.6 末行 + W5 §1.4：`409 SESSION_CONFLICT` **不带** `X-RateLimit-*`，但带 `Retry-After`。

        做法：先手工占住同一会话的锁（模拟"同一会话已有进行中的查询"），再发请求。
        ⚠️ 这条**只有 HTTP 层能测** —— 生成器层看不到状态码与响应头。
        """
        client, runtime, _ = _client()
        created = client.post(f"{API_PREFIX}/session", headers=_auth()).json()
        sid = created["data"]["session_id"]

        app_runtime = getattr(client.app.state, RUNTIME_STATE_KEY)  # type: ignore[attr-defined]
        held = IdentityContext(
            trace_id="tr_hold",
            task_id="tk_hold",
            session_id=sid,
            tenant_id=_OPERATOR.tenant_id,
            user_id=_OPERATOR.subject,
            role=Role.OPERATOR,
        )
        key = asyncio.run(
            app_runtime.session_lock.acquire(
                held, ttl_s=60, wait_ms=0
            )
        )
        assert key, "占锁失败 ⇒ 本用例的前提不成立"

        resp = _post_query(client, session_id=sid)
        assert resp.status_code == 409
        body = resp.json()
        assert body["code"] == "SESSION_CONFLICT"
        assert resp.headers.get("Retry-After"), "✅ 档必须带 Retry-After（§14.4）"
        for name in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
            assert name not in resp.headers, f"{name} 不得出现在 409 上（它不是配额事件）"
        del runtime


# ===========================================================================
# 三、任务状态与取消（附录 A §A.2 / §A.3）
# ===========================================================================


class TestTaskEndpoints:
    def test_poll_unknown_task_is_404(self) -> None:
        client, _, _ = _client()
        resp = client.get(f"{API_PREFIX}/query/tk_nope", headers=_auth())
        assert resp.status_code == 404
        assert resp.json()["code"] == "TASK_NOT_FOUND"

    def test_foreign_task_is_404_not_403(self) -> None:
        """所有权不符 ⇒ **同样** 404（区分会变成"哪些 task_id 真实存在"的枚举面）。"""
        foreign = VerifiedToken(
            subject="u_002",
            tenant_id="t_002",
            role=Role.OPERATOR,
            scope_claims=(),
            shop_ids=(),
            jti="jti-2",
            issued_at=_OPERATOR.issued_at,
            expires_at=_OPERATOR.expires_at,
            kid="kid-2",
        )
        client, _, _ = _client(verifier=_StubVerifier(foreign))
        resp = client.get(f"{API_PREFIX}/query/tk_any", headers=_auth())
        assert resp.status_code == 404
        assert resp.json()["code"] == "TASK_NOT_FOUND"

    def test_cancel_is_idempotent(self) -> None:
        """重复 cancel **不得** 5xx：第一次 200、第二次 200（§A.12 的幂等）。"""
        client, _, _ = _client()
        created = client.post(f"{API_PREFIX}/session", headers=_auth()).json()
        sid = created["data"]["session_id"]
        with client.stream(
            "POST",
            f"{API_PREFIX}/query",
            json={"question": "x", "session_id": sid},
            headers=_auth(),
        ) as r:
            task_id = _frames(b"".join(r.iter_bytes()))[0][1]["task_id"]

        # 该任务此时已是终态（refuse）⇒ 取消得到 409 TASK_NOT_CANCELLABLE（中性错误，不是 5xx）
        first = client.post(f"{API_PREFIX}/query/{task_id}/cancel", headers=_auth())
        assert first.status_code == 409
        assert first.json()["code"] == "TASK_NOT_CANCELLABLE"
        second = client.post(f"{API_PREFIX}/query/{task_id}/cancel", headers=_auth())
        assert second.status_code == 409, "重复取消必须稳定返回同一个码（幂等：不因次数而变）"

    def test_cancel_unknown_task_is_404(self) -> None:
        client, _, _ = _client()
        resp = client.post(f"{API_PREFIX}/query/tk_nope/cancel", headers=_auth())
        assert resp.status_code == 404
        assert resp.json()["code"] == "TASK_NOT_FOUND"


# ===========================================================================
# 四、幂等（附录 A §A.12）
# ===========================================================================


class TestIdempotency:
    def test_same_key_same_body_reuses_task_id(self) -> None:
        """同键同体 ⇒ **同一 `task_id`**（前端拿到的 task 不会因为重试而变）。"""
        client, _, _ = _client()
        headers = {**_auth(), "Idempotency-Key": "k-1"}
        body = {"question": "同一条问题"}
        with client.stream("POST", f"{API_PREFIX}/query", json=body, headers=headers) as r:
            first = _frames(b"".join(r.iter_bytes()))[0][1]["task_id"]
        with client.stream("POST", f"{API_PREFIX}/query", json=body, headers=headers) as r:
            replay = _frames(b"".join(r.iter_bytes()))[0][1]["task_id"]
        assert first == replay

    def test_same_key_different_body_is_conflict_with_original_task_id(self) -> None:
        """同键不同体 ⇒ `409 IDEMPOTENCY_CONFLICT`，`detail.original_task_id` = 原任务（§A.12）。

        ⚠️ 用 **analyst** 身份：`detail` 只对 `{analyst, platform_admin}` 下发
        （07 §14.2 收口）。用 operator 会看到 `detail: null` —— 那是**正确行为**，
        但会让本用例测不到 `original_task_id` 这条接线，故这里必须换身份。
        另一条用例（`test_detail_is_hidden_from_operator`）钉住 operator 侧。
        """
        analyst = VerifiedToken(
            subject=_OPERATOR.subject,
            tenant_id=_OPERATOR.tenant_id,
            role=Role.ANALYST,
            scope_claims=(),
            shop_ids=(),
            jti="jti-a",
            issued_at=_OPERATOR.issued_at,
            expires_at=_OPERATOR.expires_at,
            kid="kid-a",
        )
        client, _, _ = _client(verifier=_StubVerifier(analyst))
        headers = {**_auth(), "Idempotency-Key": "k-2"}
        with client.stream(
            "POST", f"{API_PREFIX}/query", json={"question": "第一条"}, headers=headers
        ) as r:
            original = _frames(b"".join(r.iter_bytes()))[0][1]["task_id"]

        resp = client.post(
            f"{API_PREFIX}/query", json={"question": "换了一条"}, headers=headers
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "IDEMPOTENCY_CONFLICT"
        assert resp.json()["detail"]["original_task_id"] == original


# ===========================================================================
# 五、错误路径与身份（附录 A §A.0.4 / §A.11 / §A.12）
# ===========================================================================


class TestErrorEnvelopeAndIdentity:
    def test_error_envelope_shape(self) -> None:
        """错误响应形状的唯一来源是 `errors.error_body`（六个键，缺一不可）。"""
        client, _, _ = _client()
        body = client.get(f"{API_PREFIX}/query/tk_x", headers=_auth()).json()
        assert set(body) == {"code", "message", "trace_id", "detail", "suggestions", "server_time"}
        assert body["trace_id"], "错误响应必须带 trace_id，否则线上无从查（§14.2 H15）"

    def test_detail_is_hidden_from_operator(self) -> None:
        """`detail` 只对 analyst/platform_admin 下发（07 §14.2 收口 + W5 §1.1）。

        ⚠️ 这是**服务端**义务：前端 P0 无角色来源、只能一律不展示 ——
        若后端照发，`detail` 里的闸门规则号就落到了无权角色的响应里。
        """
        client, _, _ = _client()
        assert _OPERATOR.role is Role.OPERATOR, "本用例的前提是 operator 不在 DETAIL_ROLES 内"
        body = client.get(f"{API_PREFIX}/query/tk_x", headers=_auth()).json()
        assert body["detail"] is None

    def test_query_body_validation_is_400(self) -> None:
        """请求体违约（空问题 / 未知字段）→ `INVALID_REQUEST`，**不是** 500。"""
        client, _, _ = _client()
        assert _post_query(client, question="   ").status_code == 400
        resp = client.post(
            f"{API_PREFIX}/query", json={"question": "x", "extra_field": 1}, headers=_auth()
        )
        assert resp.status_code == 400

    def test_missing_authorization_is_rejected_before_anything_else(self) -> None:
        """端点确实把身份来源交给**真**验签链路：无 `Authorization` 头 → `AUTH_FAILED`(401)。

        ⚠️ 本用例刻意用 `build_token_verifier`（**真**链路）而不是 `_StubVerifier`：
        替身会无视 `Authorization` 头，用它就测不出"端点有没有读头"。
        真链路在这里**不需要**可用的公钥 —— 缺头会在 `extract_bearer_token` 就短路
        （`PemFileJwksSource` 是惰性读，构造期零 I/O）。
        """
        from app.api.deps import build_token_verifier

        client, _, _ = _client(verifier=build_token_verifier(get_settings()))
        resp = client.get(f"{API_PREFIX}/query/tk_x")
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_FAILED"


# ===========================================================================
# 六、纯函数（不依赖 HTTP）
# ===========================================================================


@pytest.mark.parametrize(
    ("raw", "answer", "expected"),
    [
        ("上个月GMV是多少", "8月", "上个月GMV是多少（澄清补充：8月）"),
    ],
)
def test_compose_question_keeps_raw_question_at_front(
    raw: str, answer: str, expected: str
) -> None:
    """问题重组：原问题**原样在最前**（登记为 UNVERIFIED 的实现选择，见 `clarify.py` §二）。"""
    assert clarify.compose_question(raw, answer) == expected


def test_request_hash_is_order_and_default_insensitive() -> None:
    """幂等指纹只依赖**语义**：`options` 缺省与显式给默认值必须同哈希。

    ⚠️ 这就是不用 `str(body)` 的理由 —— 它会让"原样重试"被判成"同键不同体"而 409。
    """
    from app.api.dto.query import AskOptions, QueryRequest

    bare = QueryRequest(question="q")
    explicit = QueryRequest(question="q", options=AskOptions())
    assert query._request_hash(bare) == query._request_hash(explicit)


def test_sse_response_headers_include_quota_and_proxy_headers() -> None:
    """SSE 头 = 反代必备头 + 限流四头（两个 SSE 端点共用同一实现，只有一处）。"""
    from app.api.ratelimit import RateLimitQuota
    from app.core.contracts import RateLimitDecision

    quota = RateLimitQuota(
        decision=RateLimitDecision(allowed=True, bucket=RateLimitBucket.QUERY),
        limit=10,
        remaining=9,
        reset_epoch_s=1789374400,
    )
    headers = errors.sse_response_headers(quota)
    assert headers["X-Accel-Buffering"] == "no"
    assert headers["X-RateLimit-Bucket"] == "query"
    assert headers["X-RateLimit-Remaining"] == "9"
