"""B2：`POST /export` 路由级判据（假仓储 / 假缓存 / 假审计，零 PG / 零 Redis）。

覆盖的是**顺序**而不是 CSV 渲染（渲染在 `test_export_csv.py`）：
归属校验 → 读缓存 → 先审计 → 才可能下发。审计失败时响应里不得出现任何 CSV 字节。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, authenticate
from app.api.ratelimit import RateLimitQuota
from app.api.routers import export as export_router
from app.auth.tokens import VerifiedToken
from app.core.contracts import RateLimitDecision
from app.core.enums import RateLimitBucket, Role
from app.core.errors import AuditWriteFailed


class _Limiter:
    async def check_with_quota(self, bucket: RateLimitBucket, _ctx: Any) -> RateLimitQuota:
        return RateLimitQuota(
            RateLimitDecision(allowed=True, bucket=bucket), limit=30, remaining=29
        )


class _Store:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def get_task(self, ctx: Any, task_id: str) -> dict[str, Any] | None:
        self.calls.append((ctx.user_id, task_id))
        return self.payload


class _Cache:
    def __init__(self, raw: str | None) -> None:
        self.raw = raw
        self.keys: list[str] = []

    async def get(self, key: str) -> str | None:
        self.keys.append(key)
        return self.raw


class _AuditExport:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def write_export(self, ctx: Any, payload: dict[str, Any]) -> None:
        self.calls.append((ctx, payload))
        if self.fail:
            raise AuditWriteFailed(
                "导出审计写入失败，已中止本次导出（N-09 fail-closed）",
                detail={"phase": "export", "error_type": "RuntimeError"},
            )


@dataclass
class _Runtime:
    rate_limiter: Any
    audit_export: Any


@dataclass
class _GraphRuntime:
    store: Any
    result_cache: Any


@dataclass
class _Harness:
    client: TestClient
    store: _Store
    cache: _Cache
    audit: _AuditExport


def _token() -> VerifiedToken:
    now = datetime.now(UTC)
    return VerifiedToken(
        subject="user_1",
        tenant_id="T_A",
        role=Role.ANALYST,
        scope_claims=(),
        shop_ids=(),
        jti="jti_1",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        kid="kid_1",
    )


def _cached_payload(*, rows: list[list[Any]] | None = None) -> str:
    payload = {
        "columns": [{"name": "amount", "type_name": "numeric"}],
        "rows": [[1], [2]] if rows is None else rows,
        "row_count": 2 if rows is None else len(rows),
        "truncated": False,
        # 内部字段：`read_cached_result` 必须按 DATA_PAYLOAD_KEYS 裁掉
        "fingerprint": "internal-only",
    }
    return json.dumps(payload)


def _client(
    *,
    task: dict[str, Any] | None = None,
    cached: str | None = None,
    audit_fail: bool = False,
) -> _Harness:
    app = FastAPI()
    app.include_router(export_router.router, prefix="/api/v1")
    errors.install_exception_handlers(app)
    store = _Store(task if task is not None else {"status": "succeeded"})
    cache = _Cache(_cached_payload() if cached is None else cached)
    audit = _AuditExport(fail=audit_fail)
    runtime = _Runtime(rate_limiter=_Limiter(), audit_export=audit)
    graph_runtime = _GraphRuntime(store=store, result_cache=cache)
    setattr(app.state, RUNTIME_STATE_KEY, runtime)
    setattr(app.state, GRAPH_RUNTIME_STATE_KEY, graph_runtime)
    app.dependency_overrides[authenticate] = _token
    return _Harness(client=TestClient(app), store=store, cache=cache, audit=audit)


def test_export_writes_audit_before_downloading() -> None:
    h = _client()
    with h.client:
        resp = h.client.post("/api/v1/export", json={"task_id": "tk_1"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"] == 'attachment; filename="tk_1.csv"'
    assert resp.text == "amount\r\n1\r\n2\r\n"
    assert "fingerprint" not in resp.text

    assert len(h.audit.calls) == 1
    ctx, payload = h.audit.calls[0]
    assert ctx.tenant_id == "T_A"
    assert ctx.user_id == "user_1"
    assert ctx.task_id == "tk_1"
    assert payload == {"export_format": "csv", "row_count": 2, "truncated": False}

    # 归属校验先走 store.get_task；缓存键带租户
    assert h.store.calls == [("user_1", "tk_1")]
    assert h.cache.keys == ["result:T_A:tk_1"]


def test_audit_failure_returns_500_and_no_csv_bytes() -> None:
    h = _client(audit_fail=True)
    with h.client:
        resp = h.client.post("/api/v1/export", json={"task_id": "tk_1"})

    assert resp.status_code == 500
    assert resp.json()["code"] == "INTERNAL"
    assert "amount" not in resp.text
    assert resp.headers.get("content-type", "").startswith("application/json")
    assert len(h.audit.calls) == 1


def test_unknown_task_is_404_and_skips_cache_and_audit() -> None:
    h = _client(task=None)
    h.store.payload = None
    with h.client:
        resp = h.client.post("/api/v1/export", json={"task_id": "tk_missing"})

    assert resp.status_code == 404
    assert resp.json()["code"] == "TASK_NOT_FOUND"
    assert h.cache.keys == []
    assert h.audit.calls == []


def test_expired_result_cache_is_the_same_404() -> None:
    h = _client(cached="")
    h.cache.raw = None
    with h.client:
        resp = h.client.post("/api/v1/export", json={"task_id": "tk_1"})

    assert resp.status_code == 404
    assert resp.json()["code"] == "TASK_NOT_FOUND"
    assert h.cache.keys == ["result:T_A:tk_1"]
    assert h.audit.calls == []


def test_invalid_format_is_400_before_any_io() -> None:
    h = _client()
    with h.client:
        resp = h.client.post("/api/v1/export", json={"task_id": "tk_1", "format": "png"})

    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_REQUEST"
    assert h.store.calls == []
    assert h.cache.keys == []
    assert h.audit.calls == []


def test_empty_result_still_audits_and_returns_header_only() -> None:
    h = _client(cached=_cached_payload(rows=[]))
    with h.client:
        resp = h.client.post("/api/v1/export", json={"task_id": "tk_1"})

    assert resp.status_code == 200
    assert resp.text == "amount\r\n"
    assert h.audit.calls[0][1]["row_count"] == 0
