"""T-37 A1（QA 第 10 轮 T-37 主单）：`GET /semantic/metrics`／`/semantic/assets` 的契约面。

判据来源（逐字，不转述）
------------------------------------------------------------------------------
- `docs/02_附录A_接口契约详解.md:663-698`（§A.7.1 的 12 个键 ＋ `domain`／`q`／`limit`／`offset`）
- 同件 `:708-730`（§A.7.2 的 9 个键）
- 同件 `:700-706`（10-05 裁定的多租户口径）：**不得**声称"本租户口径"、响应**不带** `scope: cross_tenant`
- 同件 `:117`（`GET /semantic/*` 属**读取类** 120 次/分钟，不是查询类）
- 同件 `:65`（`tenant_id` 必须从 JWT 取，禁止从查询参数取）

本文件钉什么（缺任何一条，对应那个失败就会静默活下来）
------------------------------------------------------------------------------
1. **形状**：契约键一个都不能少（前端 `types.ts:473-499` 按契约名取值）。
2. **不冒充**：包里没有 `updated_at` ⇒ 恒 `null`；`column_count`／`denied_columns` 是**派生量**，
   必须与 `runtime.policy()["deny_columns"]` 同源（对撞臂）。
3. **draft 不被抹平**：`status="draft"` 那条的 `expression`/`unit` 必须**如实 null 且带状态**
   （防"把没定显示成空公式"，同 `runtime.py:349-359` 的立场）。
4. **没有角色门禁**（共享面的裁定）⇒ `ANALYST` 必须 200，且与 `platform_admin` 拿到**同一份 items**。
   ⚠️ 这条是**反门禁**的臂：将来谁给这两个端点加了角色判定，这里就红。
5. **红线**：整条响应里不出现 `cross_tenant`／"本租户口径"，且 `data` 里**没有** `scope` 键。
6. **限流档** = `read`（`X-RateLimit-Bucket`），不是 `query` —— 渲染字典页不许吃问答额度。
7. **缺 env／缺装载** 的具名失败：运行时不在位 ⇒ 422 `NO_DATA_ASSET` ＋ `detail.reason`，**不是 500**。
8. **传了 `tenant_id` 也不改变任何东西**（与 `test_admin_eval_report_contract.py::test_tenant_or_user_query_params_change_nothing` 同口径；
   ⚠️ 这里**不**断言"传了会 422"—— FastAPI 对未声明的查询参数是忽略，那才是可测的面）。

零额度、零库连接、零 LLM 出站。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, GraphRuntime, build_runtime
from app.api.routers import semantic
from app.api.routers.health import SEMANTIC_RUNTIME_STATE_KEY
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.config import get_settings
from app.core.enums import Role
from app.semantics import load_bundle
from app.semantics.runtime import SemanticBundleRuntime
from tests.unit._redis_fake import FakeRedis

#: ⚠️ 前缀写死，不 import `app.main.API_PREFIX`（把被测对象当期望值 ⇒ 改坏了也不红）。
API_PREFIX = "/api/v1"

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"

#: §A.7.1 的 12 个契约键（逐字抄 `docs/02:675-693`，不是从代码里读回来的）。
METRIC_CONTRACT_KEYS = {
    "name",
    "display_name",
    "expression",
    "default_aggregation",
    "unit",
    "owner",
    "domain",
    "definition_note",
    "default_predicates",
    "synonyms",
    "bundle_version",
    "updated_at",
}
#: §A.7.2 的 9 个契约键（逐字抄 `docs/02:714-725`）。
ASSET_CONTRACT_KEYS = {
    "logical_name",
    "physical_asset",
    "grain",
    "freshness_sla",
    "owner",
    "certified",
    "domain",
    "column_count",
    "denied_columns",
}
#: 契约外附加键（在 §A.7.1 补记里登记，来源全是包内实有字段）。
METRIC_EXTRA_KEYS = {"status", "created_at", "version", "time_basis"}


def _token(role: Role, *, subject: str = "u_sem", tenant: str = "T_A") -> VerifiedToken:
    now = datetime.now(UTC)
    return VerifiedToken(
        subject=subject,
        tenant_id=tenant,
        role=role,
        scope_claims=(),
        shop_ids=(),
        jti="jti-semantic",
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        kid="kid-1",
    )


class _StubVerifier:
    def __init__(self, token: VerifiedToken) -> None:
        self.token = token

    async def verify(self, authorization: str | None) -> VerifiedToken:
        return self.token


def _pools() -> Any:
    from app.repo.pools import build_three_pools

    return build_three_pools(get_settings())


def _runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


def _client(role: Role = Role.ANALYST, *, with_bundle: bool = True) -> TestClient:
    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(semantic.router, prefix=API_PREFIX)
    fake = FakeRedis()
    setattr(app.state, RUNTIME_STATE_KEY, build_runtime(settings=get_settings(), pools=_pools(), redis=fake))
    store = RedisStateStore(fake)
    setattr(
        app.state,
        GRAPH_RUNTIME_STATE_KEY,
        GraphRuntime(graph=None, store=store, verifier=_StubVerifier(_token(role)), new_deps=lambda: None),
    )
    if with_bundle:
        setattr(app.state, SEMANTIC_RUNTIME_STATE_KEY, _runtime())
    return TestClient(app, raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer stub.token.value"}


def _data(resp: Any) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# 1／2／3 形状、不冒充、draft
# ---------------------------------------------------------------------------
def test_metrics_shape_covers_contract_and_does_not_invent_updated_at() -> None:
    data = _data(_client().get(f"{API_PREFIX}/semantic/metrics", headers=_auth()))
    assert data["items"], "真包必须有指标（空 = 投影断了，不是包空了）"
    for row in data["items"]:
        assert set(row) >= METRIC_CONTRACT_KEYS, f"契约键缺失：{METRIC_CONTRACT_KEYS - set(row)}"
        assert row["updated_at"] is None, "包内 0/9 有 `updated_at` ⇒ 不许拿 created_at 冒充"
        assert row["bundle_version"] == "2026.09.14.1"
    drafts = [r for r in data["items"] if r["status"] == "draft"]
    assert drafts, "真包里有 draft 指标（sell_through_rate）⇒ 被过滤掉就是抹平"
    for d in drafts:
        assert d["expression"] is None and d["unit"] is None


def test_assets_column_count_and_denied_columns_have_one_source() -> None:
    rt = _runtime()
    data = _data(_client().get(f"{API_PREFIX}/semantic/assets", headers=_auth()))
    deny_refs = set(rt.policy()["deny_columns"])
    by_name = {a.logical_name: a for a in rt.assets()}
    assert data["total"] == len(rt.assets())
    for row in data["items"]:
        assert set(row) >= ASSET_CONTRACT_KEYS, f"契约键缺失：{ASSET_CONTRACT_KEYS - set(row)}"
        a = by_name[row["logical_name"]]
        assert row["column_count"] == len(a.columns), "column_count 是派生量 ⇒ 必须与列集对撞"
        for col in row["denied_columns"]:
            assert f"{a.logical_name}.{col}" in deny_refs, f"deny 列出现第二份真相：{a.logical_name}.{col}"
        assert row["physical_asset"] == a.physical_asset and row["certified"] == a.certified


# ---------------------------------------------------------------------------
# 4／5 共享面：无角色门禁 ＋ 红线
# ---------------------------------------------------------------------------
def test_analyst_and_admin_get_the_same_dictionary() -> None:
    """§A.7.1／§A.7.2 是**平台级共享面** ⇒ 谁都不该被 403，也不该看到"另一份"字典。"""
    admin = _data(_client(Role.PLATFORM_ADMIN).get(f"{API_PREFIX}/semantic/metrics", headers=_auth()))
    analyst = _data(_client(Role.ANALYST).get(f"{API_PREFIX}/semantic/metrics", headers=_auth()))
    assert admin == analyst, "共享面按身份分叉 = 契约变更（先给 app.semantic_bundle 加租户维度）"
    assert _data(_client(Role.ANALYST).get(f"{API_PREFIX}/semantic/assets", headers=_auth()))


@pytest.mark.parametrize("path", ["/semantic/metrics", "/semantic/assets"])
def test_response_never_claims_tenant_scope(path: str) -> None:
    resp = _client(Role.ANALYST).get(f"{API_PREFIX}{path}", headers=_auth())
    body = resp.text
    assert "cross_tenant" not in body, "共享字典不许挂跨租户标量（§A.7.1 补记的红线）"
    assert "本租户口径" not in body
    assert "scope" not in _data(resp), "响应里不该出现 `scope` 键（那属于读私有数据的面）"


# ---------------------------------------------------------------------------
# 6 限流档
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/semantic/metrics", "/semantic/assets"])
def test_bucket_is_read_not_query(path: str) -> None:
    """`docs/02:117`：`GET /semantic/*` 属**读取类** ⇒ 头里的桶名必须是 `read`。"""
    resp = _client().get(f"{API_PREFIX}{path}", headers=_auth())
    assert resp.headers["X-RateLimit-Bucket"] == "read", resp.headers.get("X-RateLimit-Bucket")


# ---------------------------------------------------------------------------
# 7 具名失败（缺装载 / 非法参数 / 缺凭据）
# ---------------------------------------------------------------------------
def test_missing_bundle_is_named_422_not_500() -> None:
    resp = _client(with_bundle=False).get(f"{API_PREFIX}/semantic/metrics", headers=_auth())
    assert resp.status_code == 422, resp.text
    env = resp.json()
    assert env["code"] == "NO_DATA_ASSET"
    assert env["detail"]["reason"] == "semantic_bundle_not_loaded"
    assert "口径字典" in env["message"], "文案要与查询链路的『拒答』分开（两个触发面不共用一句）"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_illegal_pagination_is_invalid_request(params: dict[str, int]) -> None:
    resp = _client().get(f"{API_PREFIX}/semantic/metrics", params=params, headers=_auth())
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_REQUEST"


def test_missing_authorization_header_is_rejected_by_the_real_verifier() -> None:
    from app.api.deps import build_token_verifier

    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(semantic.router, prefix=API_PREFIX)
    fake = FakeRedis()
    setattr(app.state, RUNTIME_STATE_KEY, build_runtime(settings=get_settings(), pools=_pools(), redis=fake))
    setattr(
        app.state,
        GRAPH_RUNTIME_STATE_KEY,
        GraphRuntime(
            graph=None,
            store=RedisStateStore(fake),
            verifier=build_token_verifier(get_settings()),
            new_deps=lambda: None,
        ),
    )
    setattr(app.state, SEMANTIC_RUNTIME_STATE_KEY, _runtime())
    resp = TestClient(app, raise_server_exceptions=False).get(f"{API_PREFIX}/semantic/metrics")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_FAILED"


# ---------------------------------------------------------------------------
# 8 过滤、分页对撞、伪造参数无效
# ---------------------------------------------------------------------------
def test_filter_and_pagination_are_reconcilable() -> None:
    c = _client()
    base = _data(c.get(f"{API_PREFIX}/semantic/assets", headers=_auth()))
    total = base["total"]
    pages, offset, seen = 3, 0, []
    while True:
        d = _data(c.get(f"{API_PREFIX}/semantic/assets", params={"limit": pages, "offset": offset}, headers=_auth()))
        seen += [r["logical_name"] for r in d["items"]]
        assert d["total"] == total, "每一页的 `total` 都必须是过滤后的总数（不随页变小 = §A.0.5 的定义）"
        if not d["has_more"]:
            break
        offset += pages
    assert sorted(seen) == sorted(r["logical_name"] for r in base["items"]), "分页必须不重不漏"
    assert base["total"] == len(seen), (
        "`total` 必须是**过滤后的总数**，不是当前页条数（§A.0.5 的两栏分不开 = 引用方会读成「只有这些」）"
    )
    assert _data(c.get(f"{API_PREFIX}/semantic/assets", params={"domain": "orders"}, headers=_auth()))["total"] < total
    empty = _data(c.get(f"{API_PREFIX}/semantic/assets", params={"domain": "no_such_domain"}, headers=_auth()))
    assert empty == {"items": [], "total": 0, "limit": 50, "offset": 0, "has_more": False}, (
        "未知 domain 如实给空集，**不** 404（§A.7.2 没给它 404 语义）"
    )
    hit = _data(c.get(f"{API_PREFIX}/semantic/metrics", params={"q": "复购"}, headers=_auth()))
    assert hit["total"] >= 1, "q 要真能命中同义词（口径：name/display_name/synonyms 子串，大小写不敏感）"


def test_forged_tenant_or_user_params_change_nothing() -> None:
    """`docs/02:65`：租户由服务端强制 ⇒ 这两个参数**传了也不该改变任何东西**。

    ⚠️ 不断言"传了就 422"：FastAPI 对未声明的查询参数是忽略（这是框架事实，不是漏洞）；
    有意义的是数据面等值。对表 `data` 而非整条响应（`trace_id`／`server_time` 每次都新）。
    """
    c = _client()
    honest = _data(c.get(f"{API_PREFIX}/semantic/metrics", headers=_auth()))
    forged = _data(
        c.get(f"{API_PREFIX}/semantic/metrics", params={"tenant_id": "T_B", "user_id": "u_victim"}, headers=_auth())
    )
    assert honest == forged
