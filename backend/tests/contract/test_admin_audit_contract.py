"""T-37 A2（QA 第 14 轮主单）：§A.9.5 `GET /admin/audit` 的契约面 ＋ "读路径只 SELECT"的源码级断言。

判据来源（逐字，不转述）
------------------------------------------------------------------------------
- `docs/02_附录A_接口契约详解.md` §A.9.5 判据块（2026-10-05 第 12 轮，本窗落笔）①–⑤：
  ①连接角色 `app_ro` ＋ 读口不进 `audit_store`；②身份 GUC **三键同一条语句**、
  🚫 单键注入、🚫 `RESET`；③服务端 `WHERE tenant_id = JWT.tenant_id` ＋ RLS 双保证，
  `tenant_id`／`user_id` **不得**做成查询参数，`platform_admin` 跨租户须带 `scope: cross_tenant`；
  ④断言落点 = `tests/integration/**`（跨租户不可读）＋ `tests/contract/**`（形状与错误码），
  限流 = **管理员类 5 次/分钟**；⑤未裁项 = 无。
- 同件 `:119`（管理员类桶）＋ `:65`（身份只从 JWT）＋ `:1119`（错误码唯一来源 ⇒ 本文件只用既有 28 码）。
- `docs/06_UIUX设计文档.md:2310-2322` §11.4：列表列**不含**问题全文（"截断，全文在详情"）、
  分页默认 50／上限 500、成本列存在（⇒ 段 2 缺失时**如实 null**）。

本文件钉什么（缺任何一条，对应那个失败就会静默活下来）
------------------------------------------------------------------------------
1. **视角与谓词同源**：默认 ⇒ 传给 DAO 的 `tenant_scope` **等于 JWT 的 tenant**；
   `?scope=cross_tenant` ⇒ 传 `None` 且响应 `scope.level` 与 `tenant_id` 两格同时改。
2. **伪造参数无效**：带 `tenant_id`／`user_id` 查询参数得到的 `data` 与不带时**逐字节相同**。
3. **fail-closed 角色面**：6 个非 `platform_admin` 角色 ⇒ 403（不是 401／500）。
4. **只 SELECT 是源码事实**：AST 取 `audit_read.py` 的可执行字符串常量（排除 docstring），
   出现 `INSERT`／`UPDATE`／`DELETE`／`TRUNCATE`／`RESET`／`POLICY` 即红。
   ⚠️ 不用 `grep`：本模块的**注释**里就在讨论这些词，纯文本扫描会假阳（同 `test_rls_policy_provenance.py` 的教训）。
5. **注入形状**：三键在**一条**语句里、`is_local = true`、无 `RESET`；键集合与
   `dsn.IDENTITY_GUC_KEYS` **同源**（不是本文件的抄本）。
6. **不补零、不给全文**：`cost_cny` 缺失 ⇒ `null`；`raw_question` 全文**不得**出现在响应里。
7. **RLS 现查**：`policies = 0` 时 `enforced_by` 只有两条、`second_guarantee_in_place = false`
   —— 今天盘上就是这个状态，响应不许把它写成"双保证已生效"。

零额度、零库连接（DAO 被替身接管）；真 SQL 与跨租户不可读在
`tests/integration/test_audit_read_rls.py`。
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, GraphRuntime, build_runtime
from app.api.routers import admin_audit
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.config import get_settings
from app.core.enums import Outcome, Role
from app.repo.audit_read import AUDIT_LIST_COLUMNS, AuditFilters, AuditPage
from app.repo.dsn import IDENTITY_GUC_KEYS
from tests.unit._redis_fake import FakeRedis

#: ⚠️ 前缀写死，不 import `app.main.API_PREFIX`（把被测对象当期望值 ⇒ 改坏了也不红）。
API_PREFIX = "/api/v1"
AUDIT_URL = f"{API_PREFIX}/admin/audit"

_READ_SOURCE = Path(__file__).resolve().parents[2] / "app" / "repo" / "audit_read.py"
_DEPS_SOURCE = Path(__file__).resolve().parents[2] / "app" / "api" / "deps.py"

#: §A.9.5 的 `data` 顶层键（形状由本窗 2026-10-05 落进 `docs/02 §A.9.5 补记`）。
DATA_KEYS = {
    "scope",
    "identity_guc",
    "rls",
    "items",
    "total",
    "limit",
    "offset",
    "has_more",
    "filters",
    "notes",
}

#: 列表页每行应有的格（UIUX §11.4 的列 ＋ 可复核的原始数组）。
ITEM_KEYS = {
    "log_id",
    "task_id",
    "tenant_id",
    "user_id",
    "role",
    "timestamp",
    "question_preview",
    "row_count_returned",
    "pii_hit",
    "pii_columns_hit",
    "outcome",
    "latency_ms",
    "latency_total_ms",
    "cost_cny",
    "bundle_version",
    "prompt_version",
    "model_version",
    "tables_accessed",
    "columns_accessed",
}


def _token(role: Role, *, subject: str = "u_admin", tenant: str = "t_admin") -> VerifiedToken:
    now = datetime.now(UTC)
    return VerifiedToken(
        subject=subject,
        tenant_id=tenant,
        role=role,
        scope_claims=(),
        shop_ids=(),
        jti="jti-audit",
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


def _row(**over: Any) -> dict[str, Any]:
    """按 `AUDIT_LIST_COLUMNS` 的别名生成一行；默认 = T_A 的一条成功查询。"""
    base: dict[str, Any] = {
        "log_id": 7,
        "task_id": "01JTASK",
        "tenant_id": "T_A",
        "user_id": "u_1",
        "role": "analyst",
        "timestamp": datetime(2026, 10, 5, 3, 4, 5, tzinfo=UTC),
        "raw_question": "上个月各渠道 GMV",
        "row_count_returned": 12,
        "pii_columns_hit": [],
        "truncated": False,
        "scope_level": "unrestricted",
        "outcome": "success",
        "refusal_reason": None,
        "latency_ms": {"total": 2400, "plan": 300},
        "bundle_version": "2026.09.14.1",
        "prompt_version": "gen_sql_v7",
        "model_version": "deepseek-flash",
        "tables_accessed": ["v_order_daily"],
        "columns_accessed": ["gmv"],
        "cost_cny": Decimal("0.0512"),
    }
    return {**base, **over}


class _Recorder:
    """替身 DAO：记录 router 传下来的**每一个**参数，返回可控的两行页。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = [_row(), _row(log_id=6, task_id="01JTASK2", tenant_id="T_A")]
        self.total = 2
        self.rls: dict[str, Any] = {"rls_enabled": False, "rls_forced": False, "policies": 0}

    async def fetch_page(self, ctx: Any, **kwargs: Any) -> AuditPage:
        self.calls.append({"ctx": ctx, **kwargs})
        return AuditPage(rows=list(self.rows), total=self.total, rls=dict(self.rls))


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Recorder]:
    fake = _Recorder()

    async def _fetch(self: Any, ctx: Any, **kwargs: Any) -> AuditPage:
        return await fake.fetch_page(ctx, **kwargs)

    monkeypatch.setattr("app.repo.audit_read.AuditReadDAO.fetch_page", _fetch)
    yield fake


def _client(token: VerifiedToken) -> TestClient:
    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(admin_audit.router, prefix=API_PREFIX)
    fake = FakeRedis()
    setattr(app.state, RUNTIME_STATE_KEY, build_runtime(settings=get_settings(), pools=_pools(), redis=fake))
    store = RedisStateStore(fake)
    setattr(
        app.state,
        GRAPH_RUNTIME_STATE_KEY,
        GraphRuntime(graph=None, store=store, verifier=_StubVerifier(token), new_deps=lambda: None),
    )
    return TestClient(app, raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer stub.token.value"}


def _get(client: TestClient, params: dict[str, Any] | None = None) -> Any:
    return client.get(AUDIT_URL, params=params or {}, headers=_auth())


def _data(resp: Any) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# 1 形状
# ---------------------------------------------------------------------------
def test_response_shape_covers_every_judgment_face(recorder: _Recorder) -> None:
    data = _data(_get(_client(_token(Role.PLATFORM_ADMIN))))
    assert set(data) >= DATA_KEYS, f"缺键：{DATA_KEYS - set(data)}"
    assert data["items"], "夹具给了两行 ⇒ 空 items 说明投影断了"
    aliases = {c.strip('"') for c in AUDIT_LIST_COLUMNS}
    for item in data["items"]:
        assert set(item) >= ITEM_KEYS, f"缺列：{ITEM_KEYS - set(item)}"
        missing = {a for a in aliases if a not in item and a != "raw_question"}
        assert missing == set(), f"DAO 取了列但响应没投影：{missing}"
    assert data["total"] == 2 and data["limit"] == 50 and data["offset"] == 0
    assert data["has_more"] is False


def test_pagination_is_reconcilable(recorder: _Recorder) -> None:
    recorder.total = 120
    client = _client(_token(Role.PLATFORM_ADMIN))
    data = _data(_get(client, {"limit": 2, "offset": 0}))
    assert data["has_more"] is True
    assert data["limit"] == 2 and data["offset"] == 0
    assert recorder.calls[-1]["limit"] == 2 and recorder.calls[-1]["offset"] == 0


# ---------------------------------------------------------------------------
# 2 视角 = 谓词（判据③）
# ---------------------------------------------------------------------------
def test_default_scope_uses_the_jwt_tenant_as_the_predicate(recorder: _Recorder) -> None:
    client = _client(_token(Role.PLATFORM_ADMIN, tenant="T_A"))
    data = _data(_get(client))
    call = recorder.calls[-1]
    assert call["tenant_scope"] == "T_A", "默认必须按 JWT 的 tenant 过滤（参数不可覆盖）"
    assert data["scope"] == {
        "level": "tenant",
        "tenant_id": "T_A",
        "source": "jwt",
        "enforced_by": ["server_where_on_jwt_tenant", "identity_guc_injection"],
    }


def test_cross_tenant_view_is_labelled_and_drops_the_predicate(recorder: _Recorder) -> None:
    client = _client(_token(Role.PLATFORM_ADMIN, tenant="t_admin"))
    data = _data(_get(client, {"scope": "cross_tenant"}))
    assert recorder.calls[-1]["tenant_scope"] is None
    assert data["scope"]["level"] == "cross_tenant"
    assert data["scope"]["tenant_id"] is None, "跨租户视角不得再声称自己属于某个租户"


def test_tenant_or_user_query_params_change_nothing(recorder: _Recorder) -> None:
    client = _client(_token(Role.PLATFORM_ADMIN, tenant="T_A"))
    base = _get(client).json()
    forged = _get(client, {"tenant_id": "T_B", "user_id": "u_someone_else"}).json()
    for body in (base, forged):
        body.pop("trace_id", None)
        body.pop("server_time", None)
    assert forged == base, "身份只能来自 JWT：伪造查询参数不得改变任何一格"
    assert recorder.calls[-1]["tenant_scope"] == "T_A"


# ---------------------------------------------------------------------------
# 3 fail-closed 角色面
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role",
    [Role.SHOP_OWNER, Role.OPERATOR, Role.MARKETER, Role.FINANCE, Role.SUPPORT, Role.ANALYST],
)
def test_non_platform_admin_gets_named_403(role: Role, recorder: _Recorder) -> None:
    resp = _get(_client(_token(role)))
    assert resp.status_code == 403, f"{role} ⇒ {resp.status_code}（不是 401/500）"
    assert resp.json()["code"] == "FORBIDDEN_SCOPE"
    assert recorder.calls == [], "门禁必须在取数之前：越权请求不得真的读库"


def test_missing_authorization_is_rejected_by_the_real_verifier(recorder: _Recorder) -> None:
    from app.api.deps import build_token_verifier

    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(admin_audit.router, prefix=API_PREFIX)
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
    got = TestClient(app, raise_server_exceptions=False).get(AUDIT_URL)
    assert got.status_code == 401
    assert got.json()["code"] == "AUTH_FAILED"


# ---------------------------------------------------------------------------
# 4 非法参数具名失败（全是既有码：INVALID_REQUEST）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "params",
    [
        {"outcome": "not_a_real_outcome"},
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
        {"from": "2026-13-45"},
        {"scope": "global"},
        {"pii_hit": "maybe"},
    ],
)
def test_illegal_params_are_named_invalid_request(params: dict[str, Any], recorder: _Recorder) -> None:
    resp = _get(_client(_token(Role.PLATFORM_ADMIN)), params)
    assert resp.status_code == 400, f"{params} ⇒ {resp.status_code} {resp.text}"
    assert resp.json()["code"] == "INVALID_REQUEST"
    assert recorder.calls == [], "校验失败不得先读库"


def test_valid_filters_reach_the_dao_as_typed_values(recorder: _Recorder) -> None:
    client = _client(_token(Role.PLATFORM_ADMIN))
    resp = _get(
        client,
        {
            "from": "2026-10-01T00:00:00+00:00",
            "to": "2026-10-05T00:00:00+00:00",
            "outcome": "refuse",
            "pii_hit": "true",
        },
    )
    assert resp.status_code == 200, resp.text
    filters = recorder.calls[-1]["filters"]
    assert isinstance(filters, AuditFilters)
    assert filters.outcome.value == "refuse"
    assert filters.pii_hit is True
    assert filters.since.year == 2026 and filters.since.month == 10 and filters.since.day == 1
    assert recorder.calls[-1]["ctx"].role is Role.PLATFORM_ADMIN


# ---------------------------------------------------------------------------
# 5 身份注入形状（判据②）
# ---------------------------------------------------------------------------
def test_identity_guc_block_is_one_statement_and_same_source(recorder: _Recorder) -> None:
    from app.repo.dsn import IDENTITY_GUC_KEYS

    data = _data(_get(_client(_token(Role.PLATFORM_ADMIN))))
    guc = data["identity_guc"]
    assert guc["keys"] == list(IDENTITY_GUC_KEYS), "键名唯一来源 = dsn.IDENTITY_GUC_KEYS，不许是抄本"
    assert guc["statement_count"] == 1 and guc["is_local"] is True and guc["reset_issued"] is False


def test_injection_statement_binds_all_three_keys_once() -> None:
    """SQL 文本面：三键各出现**一次**、同一条语句、`is_local=true`、没有 RESET。"""
    from app.repo.audit_read import _INJECT_SQL

    sql = str(_INJECT_SQL)
    assert sql.count("set_config(") == 3
    assert sql.upper().count("RESET") == 0
    assert sql.count(";") == 0, "一条语句：分号 = 多语句面"
    for key in IDENTITY_GUC_KEYS:
        assert sql.count(f"'{key}'") == 1, f"{key} 出现次数不是 1：单键重复或缺失都测不出来"
    assert ", true)" in sql, "is_local 必须是 true（否则身份顺着池化连接漂到下一个请求）"


# ---------------------------------------------------------------------------
# 5b 谓词与分页的 SQL 形状（判据③ 第一道，离线可判的那半）
# ---------------------------------------------------------------------------
def test_tenant_predicate_is_the_jwt_value_and_only_that() -> None:
    from app.repo.audit_read import build_queries

    _, _, where_params, page_params = build_queries(AuditFilters(), "T_A", limit=10, offset=20)
    assert where_params == {"scope_tenant": "T_A"}
    assert page_params == {"scope_tenant": "T_A", "limit": 10, "offset": 20}
    select_sql, count_sql, _, _ = build_queries(AuditFilters(), "T_A", limit=10, offset=20)
    assert "a.tenant_id = :scope_tenant" in select_sql
    assert "a.tenant_id = :scope_tenant" in count_sql, "count 走同一谓词，否则 total 与 items 不是同一个集合"
    # 跨租户视角：谓词整条消失（而不是退化成 `tenant_id = NULL` 那种"恒假"写法）
    cross_select, _, cross_params, _ = build_queries(AuditFilters(), None, limit=10, offset=0)
    assert "tenant_id" not in cross_select.split("FROM")[1]
    assert cross_params == {}


def test_count_query_is_not_paginated() -> None:
    from app.repo.audit_read import build_queries

    select_sql, count_sql, _, _ = build_queries(AuditFilters(), "T_A", limit=5, offset=10)
    assert "LIMIT :limit OFFSET :offset" in select_sql
    assert "LIMIT" not in count_sql, "total 被分页切过 ⇒ 前端的分页条与 has_more 全是错的"
    assert 'ORDER BY a."timestamp" DESC, a.log_id DESC' in select_sql, (
        "tiebreaker：同毫秒的多条审计只按时间排会在页边界重复/漏行"
    )


def test_cost_join_is_left_so_missing_supplement_survives() -> None:
    from app.repo.audit_read import build_queries

    select_sql, count_sql, _, _ = build_queries(AuditFilters(), "T_A", limit=1, offset=0)
    assert "LEFT JOIN" in select_sql
    assert "LEFT JOIN" in count_sql, "两侧 join 形态必须一致，否则 total 与 items 数的是两个集合"
    assert "INNER JOIN" not in select_sql and "INNER JOIN" not in count_sql


def test_pii_predicate_is_two_sided_and_outcome_binds_the_enum_value() -> None:
    from app.repo.audit_read import build_queries

    truthy, _, _, _ = build_queries(AuditFilters(pii_hit=True), None, limit=1, offset=0)
    falsy, _, _, _ = build_queries(AuditFilters(pii_hit=False), None, limit=1, offset=0)
    assert "pii_columns_hit <> '{}'" in truthy.replace("::text[]", "")
    assert "pii_columns_hit = '{}'" in falsy.replace("::text[]", "")
    assert truthy != falsy, "两支同文 = 过滤器失效，而两条断言都会绿"
    _, _, params, _ = build_queries(AuditFilters(outcome=Outcome.REFUSE), "T_A", limit=1, offset=0)
    assert params["outcome"] == "refuse", "绑给 DB 的必须是**字面值**（枚举成员名不是列里的值）"


# ---------------------------------------------------------------------------
# 6 源码级"只 SELECT"（判据①）
# ---------------------------------------------------------------------------
#: 词边界匹配：`truncated` 是审计表的**列名**（0001:140），裸子串匹配会把它读成 `TRUNCATE` ——
#: 那是假阳，而假阳的修法（放宽整条断言）会把真阳一起放掉。
_FORBIDDEN_SQL_WORDS = (
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bTRUNCATE\b",
    r"\bRESET\b",
    r"\bPOLICY\b",
    r"\bROW LEVEL SECURITY\b",
)


def _executable_string_literals(path: Path) -> list[str]:
    """非 docstring 的字符串常量（含 f-string 的字面片段）—— 注释与文档不参与判断。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    doc_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = getattr(node, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc_ids.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids
    ]


def test_audit_read_source_contains_only_reads() -> None:
    literals = _executable_string_literals(_READ_SOURCE)
    assert literals, "扫描器没抓到任何字符串常量 ⇒ 本臂的绿色没有意义"
    offenders = [
        (text, pattern)
        for text in literals
        for pattern in _FORBIDDEN_SQL_WORDS
        if re.search(pattern, text.upper())
    ]
    assert offenders == [], f"审计读路径出现了写/改 DDL 的字面量：{offenders}"


def test_docstring_exclusion_is_effective() -> None:
    """反向对照：证明"排除 docstring"这步真的在起作用（否则上一条的绿色可能是"全被当 docstring"）。"""
    source = _READ_SOURCE.read_text(encoding="utf-8")
    assert "RESET" in source, "阳性标本失效：audit_read.py 里不再讨论 RESET，请另选标本"
    assert not any("RESET" in text for text in _executable_string_literals(_READ_SOURCE))


def test_audit_read_is_not_the_write_store() -> None:
    """判据①：读口**不进** `audit_store` —— 它只许 import 表名常量，不碰那个类。"""
    source = _READ_SOURCE.read_text(encoding="utf-8")
    assert "AuditStore" not in source
    assert "audit_store" in source, "表名常量的唯一来源是 audit_store，导入它是对的"


def test_read_path_uses_the_analytics_pool_not_metadata() -> None:
    """判据① 的装配面：写反了不会报错，只会让"只读"这道权限形同不存在。"""
    from app.api.deps import build_runtime

    text = _DEPS_SOURCE.read_text(encoding="utf-8")
    assert "AuditReadDAO(pools.analytics)" in text
    assert "AuditReadDAO(pools.metadata)" not in text
    runtime = build_runtime(settings=get_settings(), pools=_pools(), redis=FakeRedis())
    assert runtime.audit_read._engine is runtime.pools.analytics
    assert runtime.audit_read._engine is not runtime.pools.metadata


# ---------------------------------------------------------------------------
# 7 不补零、不给全文
# ---------------------------------------------------------------------------
def test_missing_supplement_cost_stays_null(recorder: _Recorder) -> None:
    recorder.rows = [_row(cost_cny=None)]
    data = _data(_get(_client(_token(Role.PLATFORM_ADMIN))))
    assert data["items"][0]["cost_cny"] is None, "段 2 缺失必须报 null，不许补 0"


def test_decimal_and_datetime_survive_json_encoding(recorder: _Recorder) -> None:
    recorder.rows = [_row(cost_cny=Decimal("0.0512"))]
    resp = _get(_client(_token(Role.PLATFORM_ADMIN)))
    assert resp.status_code == 200, resp.text
    item = resp.json()["data"]["items"][0]
    assert item["cost_cny"] == pytest.approx(0.0512)
    assert item["timestamp"] == "2026-10-05T03:04:05+00:00"


def test_list_page_never_leaks_the_full_question(recorder: _Recorder) -> None:
    long_question = "查客户张三的订单明细" * 40  # 360 字，含 PII 形状
    recorder.rows = [_row(raw_question=long_question)]
    body = _get(_client(_token(Role.PLATFORM_ADMIN))).text
    data = json.loads(body)["data"]
    preview = data["items"][0]["question_preview"]
    assert len(preview) <= 121, f"预览必须截断（120 + 省略号），实得 {len(preview)}"
    assert preview.endswith("…")
    assert long_question not in body, "列表页出现全文 = 把 PII 原文批量下发"


def test_pii_hit_is_derived_and_the_array_still_travels(recorder: _Recorder) -> None:
    recorder.rows = [_row(pii_columns_hit=["phone"]), _row(pii_columns_hit=[])]
    data = _data(_get(_client(_token(Role.PLATFORM_ADMIN))))
    hit, miss = data["items"]
    assert hit["pii_hit"] is True and hit["pii_columns_hit"] == ["phone"]
    assert miss["pii_hit"] is False and miss["pii_columns_hit"] == []


# ---------------------------------------------------------------------------
# 8 RLS 现查（判据③ 第二道的当期状态）
# ---------------------------------------------------------------------------
def test_rls_absent_is_reported_as_absent(recorder: _Recorder) -> None:
    data = _data(_get(_client(_token(Role.PLATFORM_ADMIN))))
    rls = data["rls"]
    assert rls["table"] == "app.audit_log"
    assert rls["policies"] == 0 and rls["enabled"] is False
    assert rls["second_guarantee_in_place"] is False
    assert "rls_policy" not in data["scope"]["enforced_by"]


def test_rls_present_flips_the_second_guarantee(recorder: _Recorder) -> None:
    recorder.rls = {"rls_enabled": True, "rls_forced": True, "policies": 2}
    data = _data(_get(_client(_token(Role.PLATFORM_ADMIN))))
    assert data["rls"]["second_guarantee_in_place"] is True
    assert data["scope"]["enforced_by"][-1] == "rls_policy"


def test_enabled_without_policy_is_not_counted_as_a_guarantee(recorder: _Recorder) -> None:
    """`ENABLE ROW LEVEL SECURITY` 但 0 条策略 = **假边界**（PG 默认拒绝的是写侧，读侧无策略可依）。

    `app/obs/audit.py` 与 `test_rls_policy_provenance.py` ② 都记过这一族：
    开关为真不等于边界存在。⇒ 判据必须是 `enabled AND policies > 0`，`OR` 会在这里红。
    """
    recorder.rls = {"rls_enabled": True, "rls_forced": False, "policies": 0}
    data = _data(_get(_client(_token(Role.PLATFORM_ADMIN))))
    assert data["rls"]["enabled"] is True
    assert data["rls"]["second_guarantee_in_place"] is False
    assert "rls_policy" not in data["scope"]["enforced_by"]


# ---------------------------------------------------------------------------
# 9 限流桶 = 管理员类（判据④）
# ---------------------------------------------------------------------------
def test_bucket_is_admin_and_sixth_call_is_rate_limited(recorder: _Recorder) -> None:
    client = _client(_token(Role.PLATFORM_ADMIN))
    for i in range(5):
        resp = _get(client)
        assert resp.status_code == 200, f"第 {i + 1} 次 ⇒ {resp.status_code} {resp.text}"
        assert resp.headers["X-RateLimit-Bucket"] == "admin"
        assert resp.headers["X-RateLimit-Limit"] == "5"
    sixth = _get(client)
    assert sixth.status_code == 429, sixth.text
    assert sixth.json()["code"] == "RATE_LIMITED"
    assert sixth.headers.get("Retry-After") == "60"


def test_endpoint_is_mounted_under_the_contract_path() -> None:
    app = FastAPI()
    app.include_router(admin_audit.router, prefix=API_PREFIX)
    paths = app.openapi()["paths"]
    assert AUDIT_URL in paths, "§A.9.5 的路径形状是判据"
    assert "get" in paths[AUDIT_URL]
