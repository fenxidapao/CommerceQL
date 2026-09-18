"""`POST /api/v1/feedback` 的**端点契约测试**（附录 A §A.6 + §A.12 幂等分表）。

层号：L5｜归属窗口：W4（`tests/contract/**`）。

## 为什么单独一个文件

`app/repo/feedback.py` 的落库面已由 W1B 覆盖（`tests/integration/test_feedback_store_pg.py`
的 16 条 + `tests/unit/test_migration_0005_runtime_contract.py` 的 14 条）。
那些**测不到**本窗口的三件事（它们全在端点层）：

| # | 端点层独有的语义 | 为什么表/store 层测不到 |
|---|---|---|
| 1 | 幂等的**组合方式**（先回读 ⇒ 不写；未命中 ⇒ 写一次） | store 刻意**不做**这个决定（模块 docstring 的"两个方法"裁定） |
| 2 | 竞态恢复（撞唯一约束后**再回读**） | 这是调用方的异常策略，store 明文"不 catch 异常" |
| 3 | `user_id` 取哪一份身份字段 | 传错成 `tenant_id` 时**表照样接受**（列名相同、NOT NULL 满足） |

## 装配方式（同 `test_api_endpoints_contract.py`，⚠️ 不跑 lifespan）

`TestClient(app)` **不用 `with`**：`lifespan` 有真 I/O（连库、开池、跑启动断言）。
改为手工把 `AppRuntime` / `GraphRuntime` 放进 `app.state` —— 二者都是纯构造。
`AppRuntime.feedback` 用**替身**替换（`dataclasses.replace`），
所以本文件**全离线**、不需要 PG。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, GraphRuntime, build_runtime
from app.api.ratelimit import RateLimitQuota
from app.api.routers import feedback
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.config import get_settings
from app.core.contracts import IdentityContext, RateLimitDecision
from app.core.enums import FeedbackReasonCode, RateLimitBucket, Role
from app.graph.build import build_graph
from tests.contract.test_api_runner_contract import _DepsHolder
from tests.unit._redis_fake import FakeRedis

#: ⚠️ 写死而**不**用 `app.main.API_PREFIX`：本文件要钉住的正是"前缀就是 `/api/v1`"，
#: import 过来等于把被测对象当期望值（改坏了也不红）。
API_PREFIX = "/api/v1"

#: 🔴 `subject` 与 `tenant_id` **刻意不同** —— 有一条用例专门钉住
#: "端点取的是 `subject`（`IdentityContext.user_id`）而不是 `tenant_id`"。
#: 二者相同的话，传错也测不出来（这正是本条断言存在的理由）。
_SUBJECT = "u_001"
_TENANT = "t_999"

_TOKEN = VerifiedToken(
    subject=_SUBJECT,
    tenant_id=_TENANT,
    role=Role.ANALYST,  # `detail` 可见角色（见 errors.DETAIL_ROLES）
    scope_claims=(),
    shop_ids=(),
    jti="jti-feedback-1",
    issued_at=datetime.now(UTC) - timedelta(minutes=1),
    expires_at=datetime.now(UTC) + timedelta(hours=1),
    kid="kid-1",
)


class _StubVerifier:
    """验签替身：只返回注入的令牌。⚠️ 另有一条用例走**真**验签链路钉"确实交给验签器"。"""

    def __init__(self, token: VerifiedToken = _TOKEN) -> None:
        self.token = token

    async def verify(self, authorization: str | None) -> VerifiedToken:
        return self.token


class _FakeFeedbackStore:
    """`FeedbackStore` 的替身 —— 记录**调用序列**（这是本文件的主要证据来源）。

    ⚠️ 替身必须能表达"竞态"：`race_winner_id` 非空时，`insert_feedback` 抛
    `IntegrityError`，同时把那一行"变成别人先插进去的"（回读第二次才命中的形态）。
    没有这个开关，"并发下仍可能撞 ⇒ 再回读一次"这条分支只能靠真并发触发，
    而真并发在单测里是**不可复现**的（要跑出来才有意义 = 随机红）。
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str | None], str] = {}
        self.insert_calls: list[dict[str, Any]] = []
        self.find_calls: list[dict[str, Any]] = []
        self.race_winner_id: str | None = None

    async def find_feedback_id(
        self, *, task_id: str, user_id: str, reason_code: FeedbackReasonCode | None = None
    ) -> str | None:
        self.find_calls.append(
            {"task_id": task_id, "user_id": user_id, "reason_code": reason_code}
        )
        return self.rows.get(self._key(task_id, user_id, reason_code))

    async def insert_feedback(self, **kw: Any) -> None:
        self.insert_calls.append(kw)
        key = self._key(kw["task_id"], kw["user_id"], kw["reason_code"])
        if self.race_winner_id is not None:
            # 模拟"我们在回读之后、写入之前被别人抢先"：
            # 先让那一行存在（回读第二次才找得到），再抛和真实一样被包装过的异常。
            self.rows[key] = self.race_winner_id
            self.race_winner_id = None
            raise IntegrityError("INSERT", {}, Exception("uq_feedback_task_user_reason"))
        self.rows[key] = kw["feedback_id"]

    @staticmethod
    def _key(task_id: str, user_id: str, reason_code: FeedbackReasonCode | None) -> tuple[str, str, str | None]:
        # ⚠️ `None` 必须保留为 `None` 而不是转成字符串 —— `is not None` 的三元组键
        #    天然表达"NULLS NOT DISTINCT"（None == None 命中），与
        #    真实回读的 `IS NOT DISTINCT FROM` 同语义。
        return (task_id, user_id, None if reason_code is None else reason_code.value)


class _StubLimiter:
    """限流替身：记录桶名，可强制拒绝。

    ⚠️ 实现 `check_with_quota` 而**不是**只实现端口方法 `check` —— 这不是图省事：
    `deps.check_rate_limit` 优先取 `check_with_quota`，而配额三数（`Limit`/`Remaining`/
    `Reset`）**只**从它返回的 `RateLimitQuota` 来。只实现 `check` 时三头一律不下发
    （`RateLimitQuota` 的三个可选字段留空是"如实少三个头"，不是 bug），
    于是"四头是否真的端到端透出"就测不到了。生产实现
    （`RedisBucketRateLimiter.check_with_quota`）也是这条路径。
    """

    def __init__(self, *, allowed: bool = True) -> None:
        self.buckets: list[RateLimitBucket] = []
        self.allowed = allowed

    def _quota(self, bucket: RateLimitBucket) -> RateLimitQuota:
        #: 窗口重置时刻取自"服务端时间"（真实实现里是 Redis 的 TIME）；这里给个固定值，
        #: 本文件只验"透出与否"，不验具体时刻。
        return RateLimitQuota(
            decision=RateLimitDecision(
                allowed=self.allowed, bucket=bucket, retry_after_s=None if self.allowed else 10
            ),
            limit=30,
            #: `被拒时恒为 0`（`RateLimitQuota.remaining` 的契约注释）。
            remaining=29 if self.allowed else 0,
            reset_epoch_s=1_800_000_000,
        )

    async def check(self, bucket: RateLimitBucket, ctx: IdentityContext) -> RateLimitDecision:
        return self._quota(bucket).decision

    async def check_with_quota(
        self, bucket: RateLimitBucket, ctx: IdentityContext
    ) -> RateLimitQuota:
        self.buckets.append(bucket)
        return self._quota(bucket)


def _client(
    store: _FakeFeedbackStore | None = None,
    *,
    limiter: _StubLimiter | None = None,
    verifier: Any = None,
) -> tuple[TestClient, _FakeFeedbackStore, _StubLimiter]:
    fake_redis = FakeRedis()
    settings = get_settings()
    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(feedback.router, prefix=API_PREFIX)

    runtime = build_runtime(
        settings=settings,
        pools=_pools(),
        redis=fake_redis,  # type: ignore[arg-type]
    )
    the_store = store if store is not None else _FakeFeedbackStore()
    the_limiter = limiter if limiter is not None else _StubLimiter()
    setattr(
        app.state,
        RUNTIME_STATE_KEY,
        replace(runtime, feedback=the_store, rate_limiter=the_limiter),  # type: ignore[arg-type]
    )
    setattr(
        app.state,
        GRAPH_RUNTIME_STATE_KEY,
        GraphRuntime(
            graph=build_graph(),
            store=RedisStateStore(fake_redis),  # type: ignore[arg-type]
            verifier=verifier if verifier is not None else _StubVerifier(),
            new_deps=_DepsHolder("refuse_intent"),
        ),
    )
    return TestClient(app, raise_server_exceptions=False), the_store, the_limiter


def _pools() -> Any:
    from app.repo.pools import build_three_pools

    return build_three_pools(get_settings())


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer stub.token.value"}


def _body(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"task_id": "tk_aaaa", "is_correct": False}
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 要件 ①②③：幂等（**先回读**，命中返回同一条）
# ---------------------------------------------------------------------------


def test_first_submit_lands_one_row_and_returns_fb_prefixed_id() -> None:
    """要件①：首次提交 → 落一行，`feedback_id` 形如 `fb_…`（§A.6 明文形态）。"""
    client, store, _ = _client()

    resp = client.post(f"{API_PREFIX}/feedback", json=_body(reason_code="wrong_join"), headers=_auth())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == "OK"
    feedback_id = body["data"]["feedback_id"]
    # `fb_` 由附录 A §A.6 明文给定（`"fb_01J8X7"`），`obs.trace._PREFIX` 已登记。
    assert feedback_id.startswith("fb_"), feedback_id
    assert len(feedback_id) == len("fb_") + 32  # `{prefix}_{uuid4().hex}`
    assert len(store.insert_calls) == 1
    assert set(store.rows.values()) == {feedback_id}


def test_repeat_returns_same_id_and_does_not_insert_again() -> None:
    """要件②：同 `(task_id, user_id, reason_code)` 再提交 → **同一条 id，且不再写**。

    ⚠️ "不再写"是本条的核心：只断言 id 相同的话，一个"每次都 INSERT 然后靠
    `ON CONFLICT` 吞掉"的实现也能通过 —— 而那种实现恰恰违反 §A.6 的"同一条"
    （它返回的是**新生成**的 id）。`insert_calls` 长度必须停在 1。
    """
    client, store, _ = _client()
    payload = _body(reason_code="wrong_metric_definition")

    first = client.post(f"{API_PREFIX}/feedback", json=payload, headers=_auth()).json()
    second = client.post(f"{API_PREFIX}/feedback", json=payload, headers=_auth()).json()

    assert first["data"]["feedback_id"] == second["data"]["feedback_id"]
    assert len(store.insert_calls) == 1, "幂等命中**不得**再次写入"
    assert len(store.rows) == 1


def test_repeat_with_null_reason_code_also_hits() -> None:
    """要件③：`reason_code = null` 的重复提交**也命中**。

    这条单列的理由：`reason_code` 可空 ⇒ 唯一键用 `UNIQUE NULLS NOT DISTINCT`、
    回读用 `IS NOT DISTINCT FROM`。**两处成对**才有效；少任一处时这个用例会红
    （天真写法下 `NULL = NULL` 恒 UNKNOWN ⇒ 第二次查不到 ⇒ 插出第二行）。
    """
    client, store, _ = _client()

    first = client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth()).json()
    second = client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth()).json()

    assert first["data"]["feedback_id"] == second["data"]["feedback_id"]
    assert len(store.insert_calls) == 1
    assert len(store.rows) == 1
    # 键里的第三位真的是 None（而不是被转成字符串 "None"）
    assert next(iter(store.rows))[2] is None


# ---------------------------------------------------------------------------
# 竞态：撞唯一约束后**再回读**（不是在数据层 upsert）
# ---------------------------------------------------------------------------


def test_insert_race_is_recovered_by_second_read() -> None:
    """并发竞态：写入撞唯一约束 ⇒ 回读拿回"别人那条" ⇒ **不是 500**。"""
    store = _FakeFeedbackStore()
    store.race_winner_id = "fb_racewinner00000000000000000000"
    client, _, _ = _client(store)

    resp = client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth())

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["feedback_id"] == "fb_racewinner00000000000000000000"
    # 回读两次：一次在写之前（未命中），一次在竞态恢复（命中）
    assert len(store.find_calls) == 2


def test_integrity_error_without_existing_row_propagates() -> None:
    """🔴 竞态恢复**不得吞掉**"找不到那条"的冲突（那会是静默的数据丢失）。

    本用例让 `insert_feedback` 抛 `IntegrityError`，而回读**仍然**找不到 ——
    这对应"冲突不是同一条造成的"（例如主键重复、约束被改成别的列）。
    此时必须向上抛，由全局处理器落 `500 INTERNAL`，
    **不是** 200 配一个编出来的 id，也不是把异常咽掉当成功。
    """
    store = _FakeFeedbackStore()

    async def _boom(**kw: Any) -> None:
        store.insert_calls.append(kw)
        raise IntegrityError("INSERT", {}, Exception("pk_feedback"))

    store.insert_feedback = _boom  # type: ignore[method-assign]
    client, _, _ = _client(store)

    resp = client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth())

    assert resp.status_code == 500, resp.text
    assert resp.json()["code"] == "INTERNAL"
    assert store.rows == {}, "失败路径不得留下任何行"


# ---------------------------------------------------------------------------
# 身份：`user_id` 必须是 `sub`，不是 `tenant_id`
# ---------------------------------------------------------------------------


def test_user_id_comes_from_subject_not_tenant() -> None:
    """🔴 `user_id` = JWT `sub`（`IdentityContext.user_id`），**不是** `tenant_id`。

    传错的后果是静默的：`tenant_id` 也 NOT NULL、也非空 ⇒ 表照样接受，
    但幂等三元组从此变成"按租户去重" —— 同一租户下 A 用户的反馈会把 B 用户的顶掉。
    本用例把 `subject` 与 `tenant_id` 设成**不同值**，所以传错必红。
    """
    client, store, _ = _client()

    client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth())

    assert len(store.insert_calls) == 1
    assert store.insert_calls[0]["user_id"] == _SUBJECT
    assert store.insert_calls[0]["user_id"] != _TENANT
    # 回读用的是同一个值（否则"写入键"与"回读键"不是同一把）
    assert store.find_calls[0]["user_id"] == _SUBJECT


def test_missing_authorization_is_rejected_by_real_verifier_chain() -> None:
    """端点**确实**把身份来源交给验签器（用真链路 + 缺头 ⇒ 必失败）。

    ⚠️ 其余用例用替身验签器（不依赖 JWT 构造链）；若没有这一条，
    "端点忘了检查 `Authorization`"这类缺陷在本文件里就是**测不出来**的。

    ⚠️ 真链路在这里**不需要**可用的公钥：缺头在 `extract_bearer_token` 就短路
    （`PemFileJwksSource` 是惰性读，构造期零 I/O）—— 与
    `test_api_endpoints_contract.py::test_missing_authorization_is_rejected_before_anything_else` 同款。
    """
    from app.api.deps import build_token_verifier

    client, _, _ = _client(verifier=build_token_verifier(get_settings()))

    resp = client.post(f"{API_PREFIX}/feedback", json=_body())

    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == "AUTH_FAILED"


# ---------------------------------------------------------------------------
# `queued_for_review` 口径（窄口径：有可审之物才算入池）
# ---------------------------------------------------------------------------


def test_queued_for_review_is_false_when_result_is_correct() -> None:
    client, _, _ = _client()
    resp = client.post(
        f"{API_PREFIX}/feedback",
        json=_body(is_correct=True, corrected_sql="SELECT 1"),
        headers=_auth(),
    )
    assert resp.json()["data"]["queued_for_review"] is False


def test_queued_for_review_is_false_without_corrected_sql() -> None:
    """标了"有误"但**没给修正 SQL** ⇒ 池里没有可审之物 ⇒ `false`（不是谎报）。"""
    client, _, _ = _client()
    resp = client.post(
        f"{API_PREFIX}/feedback",
        json=_body(is_correct=False, reason_code="wrong_join"),
        headers=_auth(),
    )
    assert resp.json()["data"]["queued_for_review"] is False


def test_queued_for_review_is_true_only_with_correction() -> None:
    client, _, _ = _client()
    resp = client.post(
        f"{API_PREFIX}/feedback",
        json=_body(is_correct=False, corrected_sql="SELECT 1"),
        headers=_auth(),
    )
    assert resp.json()["data"]["queued_for_review"] is True


def test_queued_for_review_reflects_row_that_really_landed() -> None:
    """真值只在**行真的落了**的前提下出现（写失败时端点根本到不了响应）。"""
    client, store, _ = _client()
    resp = client.post(
        f"{API_PREFIX}/feedback",
        json=_body(is_correct=False, corrected_sql="SELECT 1"),
        headers=_auth(),
    )
    assert resp.json()["data"]["queued_for_review"] is True
    assert len(store.rows) == 1, "回 true 的前提是那一行确实存在"


# ---------------------------------------------------------------------------
# 请求体契约（§A.6）
# ---------------------------------------------------------------------------


def test_unknown_field_is_rejected() -> None:
    """`extra="forbid"`：多传的键（例如驼峰 `taskId`）**显式拒绝**，不静默丢弃。

    ⚠️ 状态码是 **400**（`INVALID_REQUEST`）而不是 FastAPI 默认的 422 ——
    本项目的 `RequestValidationError` 处理器统一把它映射成 400
    （`api/errors.py` 的表：`RequestValidationError` → `INVALID_REQUEST`）。
    写 422 会让"客户端按契约文档实现"与"实际收到 400"对不上。
    """
    client, store, _ = _client()
    resp = client.post(f"{API_PREFIX}/feedback", json={"taskId": "tk_x", "is_correct": True}, headers=_auth())
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_REQUEST"
    assert store.insert_calls == []


def test_non_enum_reason_code_is_rejected_at_the_edge() -> None:
    """非 §A.6 取值集的 `reason_code` 在**端点边界**就红（DB CHECK 只是兜底）。"""
    client, store, _ = _client()
    resp = client.post(f"{API_PREFIX}/feedback", json=_body(reason_code="not_a_reason"), headers=_auth())
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_REQUEST"
    assert store.insert_calls == []


def test_empty_task_id_is_rejected() -> None:
    client, store, _ = _client()
    resp = client.post(f"{API_PREFIX}/feedback", json=_body(task_id=""), headers=_auth())
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_REQUEST"
    assert store.insert_calls == []


def test_all_ten_reason_codes_are_accepted() -> None:
    """§A.6 的 10 个取值**逐个**可用（枚举是唯一取值集，DTO 不另写 `Literal`）。"""
    assert len(FeedbackReasonCode) == 10
    client, store, _ = _client()
    for i, code in enumerate(FeedbackReasonCode):
        resp = client.post(
            f"{API_PREFIX}/feedback",
            json=_body(task_id=f"tk_{i}", reason_code=code.value),
            headers=_auth(),
        )
        assert resp.status_code == 200, (code, resp.text)
    assert len(store.insert_calls) == 10


def test_optional_text_fields_are_forwarded_verbatim() -> None:
    """`comment` / `corrected_sql` / `correct_result_hint` **不丢**（§12.3 曾漏列 `correct_result_hint`）。"""
    client, store, _ = _client()
    client.post(
        f"{API_PREFIX}/feedback",
        json=_body(
            is_correct=False,
            reason_code="wrong_metric_definition",
            comment="GMV 应该剔除运费",
            corrected_sql="SELECT 1",
            correct_result_hint="应为 1752.10 万元",
        ),
        headers=_auth(),
    )
    call = store.insert_calls[0]
    assert call["comment"] == "GMV 应该剔除运费"
    assert call["corrected_sql"] == "SELECT 1"
    assert call["correct_result_hint"] == "应为 1752.10 万元"
    assert call["reason_code"] is FeedbackReasonCode.WRONG_METRIC_DEFINITION


# ---------------------------------------------------------------------------
# 封套 / 分桶 / 响应头
# ---------------------------------------------------------------------------


def test_envelope_shape_and_rate_limit_headers() -> None:
    """成功封套 + 逐桶限流四头（§A.0.4 / §A.0.6）。"""
    client, _, limiter = _client()
    resp = client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth())

    body = resp.json()
    assert set(body) == {"code", "message", "trace_id", "data", "server_time"}
    assert body["code"] == "OK"
    assert body["trace_id"], "trace_id 必须下发（否则前端无法反馈问题）"
    assert set(body["data"]) == {"feedback_id", "queued_for_review"}
    assert limiter.buckets == [RateLimitBucket.WRITE], "§A.0.6：/feedback ∈ 写入类桶"
    # 四头（`Bucket` 恒发；三数来自同一次判定）
    assert resp.headers["X-RateLimit-Bucket"] == RateLimitBucket.WRITE.value
    assert resp.headers["X-RateLimit-Limit"] == "30"
    assert resp.headers["X-RateLimit-Remaining"] == "29"
    assert resp.headers["X-RateLimit-Reset"] == "1800000000"


def test_rate_limited_maps_to_429_with_retry_after() -> None:
    client, store, _ = _client(limiter=_StubLimiter(allowed=False))
    resp = client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth())

    assert resp.status_code == 429, resp.text
    assert resp.json()["code"] == "RATE_LIMITED"
    assert resp.headers.get("Retry-After") == "10"
    assert store.insert_calls == [], "被限流的请求**不得**已经写库"


def test_rate_limit_denial_carries_quota_from_the_same_decision() -> None:
    """`429` 的配额头必须与本次判定**同源**（防"响应说还剩 3 次、状态码却是 429"）。"""
    client, _, _ = _client(limiter=_StubLimiter(allowed=False))
    resp = client.post(f"{API_PREFIX}/feedback", json=_body(), headers=_auth())

    assert resp.headers["X-RateLimit-Bucket"] == RateLimitBucket.WRITE.value
    # 被拒时剩余额度**恒为 0**（`RateLimitQuota.remaining` 的契约注释）
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    assert resp.headers["Retry-After"] == "10"


def test_success_does_not_use_idempotency_key_header() -> None:
    """§A.12：`/feedback` 的幂等键是**业务三元组**，客户端换 `Idempotency-Key` **不产生第二条**。"""
    client, store, _ = _client()
    payload = _body()

    a = client.post(f"{API_PREFIX}/feedback", json=payload, headers={**_auth(), "Idempotency-Key": "k1"})
    b = client.post(f"{API_PREFIX}/feedback", json=payload, headers={**_auth(), "Idempotency-Key": "k2"})

    assert a.json()["data"]["feedback_id"] == b.json()["data"]["feedback_id"]
    assert len(store.insert_calls) == 1


# ---------------------------------------------------------------------------
# 纯函数：口径本身
# ---------------------------------------------------------------------------


def test_queued_for_review_predicate_is_narrow() -> None:
    """直接钉住判定表（4 种组合）—— 免得只靠 3 条用例覆盖不全。"""
    from app.api.dto.feedback import FeedbackRequest
    from app.api.routers.feedback import _queued_for_review

    cases = [
        (True, None, False),
        (True, "SELECT 1", False),
        (False, None, False),
        (False, "SELECT 1", True),
    ]
    for is_correct, sql, expected in cases:
        req = FeedbackRequest(task_id="tk_x", is_correct=is_correct, corrected_sql=sql)
        assert _queued_for_review(req) is expected, (is_correct, sql)


def test_rate_limit_quota_helper_shape() -> None:
    """`RateLimitQuota` 四头在本端点与其余端点同形（唯一判据 = `HttpErrorMapping.headers`）。"""
    quota = RateLimitQuota(
        RateLimitDecision(allowed=True, bucket=RateLimitBucket.WRITE, retry_after_s=None)
    )
    headers = quota.headers()
    assert headers["X-RateLimit-Bucket"] == RateLimitBucket.WRITE.value
    assert "Retry-After" not in headers  # 允许时不给倒计时
