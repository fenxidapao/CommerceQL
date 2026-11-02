"""B5：资产详情投影与端点（假运行时，零语义包 I/O）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import RUNTIME_STATE_KEY, authenticate
from app.api.ratelimit import RateLimitQuota
from app.api.routers import semantic as semantic_router
from app.api.routers.health import SEMANTIC_RUNTIME_STATE_KEY
from app.auth.tokens import VerifiedToken
from app.core.contracts import RateLimitDecision
from app.core.enums import RateLimitBucket, Role
from app.obs.trace import new_id
from app.present import semantic_dict


def _column(name: str, *, sensitive: str | None = None, enum: dict[str, str] | None = None) -> Any:
    return SimpleNamespace(
        name=name,
        type="text",
        comment=f"{name} comment",
        unit=None,
        sensitive=sensitive,
        synonyms=(),
        enum=enum or {},
        time_semantics=None,
    )


def _asset(name: str, columns: list[Any]) -> Any:
    return SimpleNamespace(
        logical_name=name,
        physical_asset=f"v_{name}",
        grain="order",
        domain="orders",
        owner="data-team",
        certified=True,
        freshness_sla="P1D",
        level="warm",
        row_estimate=100,
        description=f"{name} desc",
        columns=tuple(columns),
    )


def _runtime() -> Any:
    joins = [
        SimpleNamespace(
            left="order.order_id",
            right="item.order_id",
            type="inner",
            on_columns=("order_id",),
            certified_by="data-team",
            note=None,
        ),
        SimpleNamespace(
            left="product.product_id",
            right="item.product_id",
            type="inner",
            on_columns=("product_id",),
            certified_by="data-team",
            note=None,
        ),
    ]
    metrics = [
        SimpleNamespace(name="gmv", display_name="GMV", default_binding=SimpleNamespace(asset="order")),
        SimpleNamespace(
            name="items", display_name="件数", default_binding=SimpleNamespace(asset="item")
        ),
    ]
    return SimpleNamespace(
        assets=lambda: (
            _asset(
                "order",
                [
                    _column("tenant_id", sensitive="tenant_key"),
                    _column("order_id"),
                    _column("status", enum={"delivered": "已送达"}),
                ],
            ),
            _asset("item", [_column("order_id")]),
        ),
        policy=lambda: {"deny_columns": ["order.tenant_id"]},
        joins=lambda: tuple(joins),
        metrics=lambda: tuple(metrics),
    )


def test_projection_drops_denied_and_sensitive_columns() -> None:
    data = semantic_dict.asset_detail(_runtime(), "order")
    assert data is not None
    names = [c["name"] for c in data["columns"]]
    assert names == ["order_id", "status"]
    assert data["columns"][1]["enum"] == {"delivered": "已送达"}
    for column in data["columns"]:
        assert "sensitive" not in column
    assert "denied_columns" not in data
    assert [j["left"] for j in data["joins"]] == ["order.order_id"]
    assert [m["name"] for m in data["metrics"]] == ["gmv"]


def test_unknown_asset_returns_none() -> None:
    assert semantic_dict.asset_detail(_runtime(), "nope") is None


class _Limiter:
    async def check_with_quota(self, bucket: RateLimitBucket, _ctx: Any) -> RateLimitQuota:
        return RateLimitQuota(RateLimitDecision(True, bucket), limit=120, remaining=119)


def _token() -> VerifiedToken:
    now = datetime.now(UTC)
    return VerifiedToken(
        subject="u_a",
        tenant_id="T_A",
        role=Role.ANALYST,
        scope_claims=(),
        shop_ids=(),
        jti=new_id("jti"),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        kid="default",
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(semantic_router.router, prefix="/api/v1")
    errors.install_exception_handlers(app)
    setattr(app.state, RUNTIME_STATE_KEY, SimpleNamespace(rate_limiter=_Limiter()))
    setattr(app.state, SEMANTIC_RUNTIME_STATE_KEY, _runtime())
    app.dependency_overrides[authenticate] = _token
    return TestClient(app)


def test_endpoint_shapes_and_unknown_asset_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `_runtime()` 里有 isinstance 守卫（真实运行时才放行）；替身直接替换取用函数。
    import app.api.routers.semantic as semantic_module

    runtime = _runtime()
    monkeypatch.setattr(semantic_module, "_runtime", lambda _request: runtime)
    with _client() as client:
        ok = client.get("/api/v1/semantic/assets/order")
        assert ok.status_code == 200
        data = ok.json()["data"]
        assert data["logical_name"] == "order"
        assert [c["name"] for c in data["columns"]] == ["order_id", "status"]

        missing = client.get("/api/v1/semantic/assets/nope")
        assert missing.status_code == 422
        assert missing.json()["code"] == "NO_DATA_ASSET"
