"""B3：注册/登录全分支（假仓储 + 假签发器，零 PG / 零 Redis）。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api import errors
from app.api.deps import RUNTIME_STATE_KEY
from app.api.ratelimit import RateLimitQuota
from app.api.routers import auth as auth_router
from app.auth.passwords import hash_password
from app.auth.tokens import IssuedToken
from app.core.contracts import RateLimitDecision
from app.core.enums import RateLimitBucket
from app.repo.users import UserRow

_GOOD_PASSWORD = "correct-horse-battery"


class _Limiter:
    async def check_with_quota(self, bucket: RateLimitBucket, _ctx: Any) -> RateLimitQuota:
        return RateLimitQuota(
            RateLimitDecision(allowed=True, bucket=bucket), limit=5, remaining=4
        )


class _Issuer:
    def issue(self, **_kwargs: Any) -> IssuedToken:
        return IssuedToken(access_token="tok", expires_in=3600, jti="jti")


class _Users:
    def __init__(self) -> None:
        self.rows: dict[str, UserRow] = {}
        self.inserts: list[dict[str, Any]] = []

    async def find_by_username(self, username: str) -> UserRow | None:
        return self.rows.get(username.lower())

    async def insert_user(self, **kwargs: Any) -> None:
        username = str(kwargs["username"]).lower()
        if username in self.rows:
            raise IntegrityError("INSERT", {}, Exception("duplicate"))
        self.inserts.append(kwargs)
        self.rows[username] = UserRow(
            user_id=kwargs["user_id"],
            tenant_id=kwargs["tenant_id"],
            username=kwargs["username"],
            password_hash=kwargs["password_hash"],
            role=kwargs["role"],
            shop_ids=tuple(kwargs.get("shop_ids") or ()),
            disabled=False,
        )


@dataclass
class _Runtime:
    settings: Any
    rate_limiter: Any
    users: Any
    issuer: Any


def _client(*, allow_registration: bool = True, users: _Users | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    errors.install_exception_handlers(app)
    runtime = _Runtime(
        settings=SimpleNamespace(
            AUTH_ALLOW_REGISTRATION=allow_registration,
            AUTH_REGISTRATION_TENANT_ID="T_A",
        ),
        rate_limiter=_Limiter(),
        users=users or _Users(),
        issuer=_Issuer(),
    )
    setattr(app.state, RUNTIME_STATE_KEY, runtime)
    return TestClient(app)


def _add_user(users: _Users, *, disabled: bool = False, role: str = "analyst") -> None:
    users.rows["alice"] = UserRow(
        user_id="user_1",
        tenant_id="T_A",
        username="alice",
        password_hash=hash_password(_GOOD_PASSWORD),
        role=role,
        shop_ids=(),
        disabled=disabled,
    )


def test_register_is_forbidden_when_switch_is_off() -> None:
    with _client(allow_registration=False) as client:
        resp = client.post("/api/v1/auth/register", json={"username": "alice", "password": _GOOD_PASSWORD})
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN_SCOPE"


def test_register_success_uses_server_tenant() -> None:
    users = _Users()
    with _client(users=users) as client:
        resp = client.post("/api/v1/auth/register", json={"username": "alice", "password": _GOOD_PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "alice"
    assert users.inserts[0]["tenant_id"] == "T_A"
    assert users.inserts[0]["role"] == "analyst"


def test_register_duplicate_is_409() -> None:
    users = _Users()
    _add_user(users)
    with _client(users=users) as client:
        resp = client.post("/api/v1/auth/register", json={"username": "alice", "password": _GOOD_PASSWORD})
    assert resp.status_code == 409
    assert resp.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_login_success_returns_token() -> None:
    users = _Users()
    _add_user(users)
    with _client(users=users) as client:
        resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": _GOOD_PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"] == "tok"
    assert resp.json()["data"]["expires_in"] == 3600


def test_login_unknown_and_wrong_password_share_one_message() -> None:
    users = _Users()
    _add_user(users)
    with _client(users=users) as client:
        unknown = client.post("/api/v1/auth/login", json={"username": "bobby", "password": _GOOD_PASSWORD})
        wrong = client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong-password"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "AUTH_FAILED"
    assert unknown.json()["message"] == wrong.json()["message"]


def test_disabled_account_is_forbidden() -> None:
    users = _Users()
    _add_user(users, disabled=True)
    with _client(users=users) as client:
        resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": _GOOD_PASSWORD})
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN_SCOPE"


def test_invalid_role_in_db_is_auth_failed() -> None:
    users = _Users()
    _add_user(users, role="not-a-role")
    with _client(users=users) as client:
        resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": _GOOD_PASSWORD})
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_FAILED"
