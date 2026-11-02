"""B4：会话索引（ZSET）+ 列表/关闭端点（假 Redis，零外部服务）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, authenticate
from app.api.ratelimit import RateLimitQuota
from app.api.routers import session as session_router
from app.api.routers import sessions as sessions_router
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.contracts import IdentityContext, RateLimitDecision
from app.core.enums import RateLimitBucket, Role
from app.obs.trace import new_id
from tests.unit._redis_fake import FakeRedis


class _Limiter:
    async def check_with_quota(self, bucket: RateLimitBucket, _ctx: Any) -> RateLimitQuota:
        return RateLimitQuota(RateLimitDecision(True, bucket), limit=120, remaining=119)


def _token(user: str, tenant: str = "T_A") -> VerifiedToken:
    now = datetime.now(UTC)
    return VerifiedToken(
        subject=user,
        tenant_id=tenant,
        role=Role.ANALYST,
        scope_claims=(),
        shop_ids=(),
        jti=new_id("jti"),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        kid="default",
    )


def _ctx(user: str, session_id: str, tenant: str = "T_A") -> IdentityContext:
    return IdentityContext(
        trace_id=new_id("trace"),
        task_id=new_id("task"),
        session_id=session_id,
        tenant_id=tenant,
        user_id=user,
        role=Role.ANALYST,
    )


async def test_index_is_per_user_and_close_hides_without_deleting_history() -> None:
    fake = FakeRedis()
    store = RedisStateStore(fake)  # type: ignore[arg-type]
    a = _ctx("u_a", "ss_a")
    b = _ctx("u_b", "ss_b")
    await store.create_session(a)
    await store.create_session(b)

    assert [m.session_id for m in await store.list_sessions(a)] == ["ss_a"]
    assert [m.session_id for m in await store.list_sessions(b)] == ["ss_b"]

    assert await store.close_session(a, "ss_a") is True
    assert await store.list_sessions(a) == ()
    # 历史仍可读，且标记为已关闭（软关闭，不是删除）
    still = await store.get_session(a, "ss_a")
    assert still is not None and still.closed is True
    # 属主不符 ⇒ 关闭失败（与 404 同形）
    assert await store.close_session(b, "ss_a") is False


async def test_cross_tenant_index_is_not_shared() -> None:
    fake = FakeRedis()
    store = RedisStateStore(fake)  # type: ignore[arg-type]
    await store.create_session(_ctx("u_a", "ss_1", tenant="T_A"))
    other = _ctx("u_a", "ss_x", tenant="T_B")
    assert await store.list_sessions(other) == ()


def _client(store: RedisStateStore) -> TestClient:
    app = FastAPI()
    app.include_router(session_router.router, prefix="/api/v1")
    app.include_router(sessions_router.router, prefix="/api/v1")
    errors.install_exception_handlers(app)
    setattr(app.state, RUNTIME_STATE_KEY, SimpleNamespace(rate_limiter=_Limiter()))
    setattr(app.state, GRAPH_RUNTIME_STATE_KEY, SimpleNamespace(store=store))
    app.dependency_overrides[authenticate] = lambda: _token("u_a")
    return TestClient(app)


def test_list_endpoint_shape_and_close_route() -> None:
    fake = FakeRedis()
    store = RedisStateStore(fake)  # type: ignore[arg-type]
    # 预置一条会话（直接用 store，避免依赖 /session 端点）
    import asyncio

    asyncio.run(store.create_session(_ctx("u_a", "ss_1")))
    asyncio.run(
        store.append_turn(
            _ctx("u_a", "ss_1"),
            question="2018 年各州 GMV 前十",
            outcome="success",
            plan_summary={"metric": "gmv"},
            bundle_version="2026.10.27.1",
        )
    )
    asyncio.run(
        store.touch_session(
            _ctx("u_a", "ss_1"), title="2018 年各州 GMV 前十", bundle_version="2026.10.27.1"
        )
    )

    with _client(store) as client:
        listed = client.get("/api/v1/sessions")
        assert listed.status_code == 200
        body = listed.json()["data"]
        assert body["total"] == 1
        assert body["items"][0]["session_id"] == "ss_1"
        assert body["items"][0]["turn_count"] == 1
        assert body["items"][0]["title"] == "2018 年各州 GMV 前十"

        closed = client.delete("/api/v1/session/ss_1")
        assert closed.status_code == 200
        assert closed.json()["data"] == {"session_id": "ss_1", "closed": True}

        assert client.get("/api/v1/sessions").json()["data"]["total"] == 0
        # 再关一次：meta 仍在（closed=True），幂等返回 200
        again = client.delete("/api/v1/session/ss_1")
        assert again.status_code == 200


def test_close_unknown_session_is_404() -> None:
    fake = FakeRedis()
    with _client(RedisStateStore(fake)) as client:  # type: ignore[arg-type]
        resp = client.delete("/api/v1/session/ss_missing")
    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"
