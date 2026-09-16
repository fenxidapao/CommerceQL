"""认证链路 7 步的行为级契约（07 §13.1）。归属窗口：W1B。

**这个文件为什么存在**：认证是本系统**唯一的身份来源**（禁令 1/2：
`tenant_id` / `role` / `shop_ids` 禁止从请求体或 query 取）。
因此它的失败模式不是"某个功能不好用"，而是**跨租户泄露**。
下面的断言按"每一处能让身份可被客户端影响的入口"组织，而不是按代码结构组织。

⚠️ **测试用真实 RSA 签名，不用 mock**。
理由：`jwt.decode(..., algorithms=["RS256"])` 的关键防线是**算法白名单**
（拒 `none` / `HS256`）。若测试把 `jwt.decode` mock 掉，"算法被配错"就测不出来 ——
而那正是最经典的一类认证漏洞。真实签名 + 真实验签才能覆盖它。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.context import (
    bind_identity,
    build_identity,
    current_identity,
    identity_obs_fields,
    identity_or_none,
    reset_identity,
)
from app.auth.errors import AuthError, TokenRevokedError
from app.auth.jwks import DEFAULT_KID, JwksCache
from app.auth.revocation import InMemoryRevocationList
from app.auth.tokens import REQUIRED_CLAIMS, TokenVerifier, extract_bearer_token
from app.core.enums import Role
from app.obs.schema import LogField

ISSUER = "https://idp.test/commerceql"
AUDIENCE = "commerceql-api"
KID = "test-kid"

# ⚠️ 刻意**不加** `pytestmark`：本仓库 `pyproject.toml` 的 `markers` 只有
# `contract` / `redteam` / `integration`（W0 持有，本窗口不改），
# 而 `--strict-markers` 会让未注册的 `unit` 直接**收集失败**（不是跳过）。
# `tests/unit/test_pools.py` 同样不带 mark。若将来 W0 注册 `unit`，两者应一起补。


# ---------------------------------------------------------------------------
# 夹具：真实密钥对 + 可控时钟
# ---------------------------------------------------------------------------


class _StaticJwksSource:
    """固定返回一份 JWKS 的 `JwksSource`；可被改成抛错以测量"刷新失败"。"""

    def __init__(self, keys: Mapping[str, Any]) -> None:
        self._keys = dict(keys)
        self.fetch_count = 0
        self.fail_next = False

    async def fetch(self) -> Mapping[str, Any]:
        self.fetch_count += 1
        if self.fail_next:
            raise RuntimeError("IdP 不可达（测试桩）")
        return dict(self._keys)


@pytest.fixture(scope="module")
def rsa_keys() -> tuple[Any, Any]:
    """2048 位密钥对。**module 级**：生成一次即可（约 100ms，避免每条用例都付）。"""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


@pytest.fixture
def jwks_source(rsa_keys: tuple[Any, Any]) -> _StaticJwksSource:
    # 同一把公钥挂两个 `kid`：`test-kid`（显式 kid 的用例）与 `default`
    # （无 kid / 缺 kid 时 `TokenVerifier` 回退到的那个 —— ADR-17 单 key stub 的键）。
    return _StaticJwksSource({KID: rsa_keys[1], DEFAULT_KID: rsa_keys[1]})


class _Clock:
    """可推进的 monotonic —— 让 TTL 可测（`JwksCache` 支持注入）。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def verifier(jwks_source: _StaticJwksSource) -> TokenVerifier:
    return TokenVerifier(
        jwks=JwksCache(jwks_source, monotonic=_Clock()),
        issuer=ISSUER,
        audience=AUDIENCE,
        revocation=InMemoryRevocationList(),
    )


def _claims(**overrides: Any) -> dict[str, Any]:
    """一份**合法**的 claims 基线；各用例只覆盖自己关心的那一项。"""
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "sub": "u_001",
        "tenant_id": "t_001",
        "role": Role.OPERATOR.value,
        "scope": "orders:read shops:read",
        "shop_ids": ["s_001", "s_002"],
        "jti": "jti_001",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "iss": ISSUER,
        "aud": AUDIENCE,
    }
    base.update(overrides)
    return base


def _sign(private: Any, claims: Mapping[str, Any], *, kid: str | None = KID, alg: str = "RS256") -> str:
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(dict(claims), private, algorithm=alg, headers=headers)


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _craft_hs256(claims: Mapping[str, Any], secret: bytes, *, kid: str) -> str:
    """**手工**拼一个 HS256 令牌 —— 因为 PyJWT 会拒绝签这种令牌。

    ⚠️ 这不是"绕过测试的便利函数"，而恰恰是**攻击者真实做的事**：
    PyJWT 在 `encode` 阶段就拦住"拿 RSA 公钥当 HMAC 密钥"（`InvalidKeyError`），
    但攻击者不会用 PyJWT 的 `encode` —— 他直接拼三段 base64。
    所以**只能在 `decode` 侧测出这条防线**，`encode` 侧的拦截不能算数。
    """
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}, separators=(",", ":")).encode())
    payload = _b64(json.dumps(dict(claims), separators=(",", ":")).encode())
    signing_input = header + b"." + payload
    signature = _b64(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + signature).decode()


# ---------------------------------------------------------------------------
# 步 1：Authorization 头提取
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        (None, "missing_header"),
        ("", "missing_header"),
        ("Bearer", "malformed_header"),
        ("Basic dXNlcjpwYXNz", "malformed_header"),
        ("Bearer   ", "malformed_header"),
    ],
)
def test_step1_rejects_malformed_authorization_header(header: str | None, reason: str) -> None:
    """**必须只认 `Bearer`**：`Basic` 能被当成令牌传下去，等于给了一条绕过签名的口子。"""
    with pytest.raises(AuthError) as excinfo:
        extract_bearer_token(header)
    assert excinfo.value.step == 1
    assert excinfo.value.reason == reason


def test_step1_accepts_lowercase_bearer_and_strips_whitespace() -> None:
    """RFC 6750 规定 scheme 大小写不敏感 —— 只认小写会让"换个客户端就全 401"。"""
    assert extract_bearer_token("bearer  abc.def.ghi  ") == "abc.def.ghi"
    assert extract_bearer_token("BEARER abc.def.ghi") == "abc.def.ghi"


# ---------------------------------------------------------------------------
# ★ 禁令 3：任何失败都不得把令牌原文带进异常
# ---------------------------------------------------------------------------


def test_failures_never_leak_the_token(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """**PRD §11.5 有真实事故**：令牌进日志 = 一次日志读取就能冒充任意用户。

    这里用 `repr(exc)` 而不是 `str(exc)`：`repr` 会把 `detail` 也带出来，
    而 `detail` 是正式进响应体的那一份。
    """
    secret = "eyJhbGciOiJIUzI1NiJ9.SECRET-PAYLOAD-DO-NOT-LEAK.signature"
    samples: list[str] = []

    # ① 格式非法（连 header 都解不开）
    for bad in (secret, f"Bearer {secret}", "Bearer not-a-jwt"):
        with pytest.raises(AuthError) as excinfo:
            asyncio.run(verifier.verify(f"Bearer {bad}"))
        samples.append(repr(excinfo.value))

    # ② 签名错（结构合法，但用另一把私钥签）
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = _sign(other, _claims())
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {forged}"))
    samples.append(repr(excinfo.value))

    # ③ 过期
    expired = _sign(rsa_keys[0], _claims(exp=int((datetime.now(UTC) - timedelta(hours=1)).timestamp())))
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {expired}"))
    samples.append(repr(excinfo.value))

    for sample in samples:
        assert secret not in sample
        assert "SECRET-PAYLOAD-DO-NOT-LEAK" not in sample
        # 令牌的任何一段都不得出现
        for part in secret.split("."):
            assert part not in sample
    assert forged not in samples[-1]


def test_failure_detail_carries_only_server_side_observability_fields(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any]
) -> None:
    """失败归因走 `detail`（**服务端字段**），且只含步骤号与原因 —— 不含任何 claim 值。"""
    expired = _sign(rsa_keys[0], _claims(exp=int((datetime.now(UTC) - timedelta(hours=1)).timestamp())))
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {expired}"))
    detail = excinfo.value.detail
    assert detail == {"auth_failure_step": 3, "auth_failure_reason": "expired"}
    assert "t_001" not in repr(detail)  # 连租户 id 都不进去


# ---------------------------------------------------------------------------
# 步 2：JWKS —— 缓存击穿与"刷新失败不清空"
# ---------------------------------------------------------------------------


def test_step2_unknown_kid_falls_back_to_default_and_reports_step_2(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any]
) -> None:
    """`kid` 未知 → **步 2** 失败（而不是"签名错"）。

    归因很重要：把"密钥对不上"报成"签名错"会让运维去查用户，而真正的故障在 IdP 轮转。
    """
    token = _sign(rsa_keys[0], _claims(), kid="rotated-away")
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {token}"))
    # stub 只有 default 一个 key，故 'rotated-away' 查不到
    assert excinfo.value.step == 2
    assert excinfo.value.reason == "unknown_kid"


def test_step2_kid_absent_uses_default(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """无 `kid` 的令牌按 `default` 查 —— 这是 ADR-17 单 key stub 的可用前提。"""
    token = _sign(rsa_keys[0], _claims(), kid=None)
    verified = asyncio.run(verifier.verify(f"Bearer {token}"))
    assert verified.kid == "default"


def test_jwks_refresh_failure_does_not_empty_the_cache(
    jwks_source: _StaticJwksSource, rsa_keys: tuple[Any, Any]
) -> None:
    """★ **"miss 时刷新一次，不清空缓存"的机器化**（07 §13.1 第 2 步）。

    若实现写成"先 clear() 再 fetch()"，刷新失败那一刻缓存是空的 →
    **认证全挂**，而真相只是 IdP 抖了一下。本用例把这条钉死。
    """
    clock = _Clock()
    cache = JwksCache(jwks_source, ttl_s=600, monotonic=clock)

    # 先正常预热
    assert asyncio.run(cache.get(KID)) is not None
    assert cache.cached_kids == (DEFAULT_KID, KID)

    # 让缓存过期 + 让刷新失败
    clock.now += 601
    jwks_source.fail_next = True

    # 刷新失败：旧 key 仍然可用（不清空）
    assert asyncio.run(cache.get(KID)) is not None
    assert cache.cached_kids == (DEFAULT_KID, KID), "刷新失败时不得清空缓存（会让认证全挂）"


def test_jwks_refresh_is_serialized_under_concurrency(jwks_source: _StaticJwksSource) -> None:
    """N 个并发请求同时 miss → 只产生 **1 次**读盘/对外请求（防缓存击穿）。"""
    cache = JwksCache(jwks_source)

    async def _many() -> None:
        await asyncio.gather(*(cache.get(KID) for _ in range(20)))

    asyncio.run(_many())
    assert jwks_source.fetch_count == 1, f"并发 miss 触发了 {jwks_source.fetch_count} 次刷新（应为 1）"


def test_jwks_cold_start_failure_is_auth_failed_not_silent(
    jwks_source: _StaticJwksSource, rsa_keys: tuple[Any, Any]
) -> None:
    """**冷启动**就有缓存与"缓存为空时刷新失败"是两件事：

    前者可降级（用旧 key），后者**必须报错** —— 静默放行等于不验签。
    """
    jwks_source.fail_next = True
    cache = JwksCache(jwks_source)
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(cache.get(KID))
    assert excinfo.value.step == 2
    assert excinfo.value.reason.startswith("jwks_unavailable")


def test_jwks_cache_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError, match="必须为正数"):
        JwksCache(_StaticJwksSource({}), ttl_s=0)


# ---------------------------------------------------------------------------
# 步 3：签名 / iss / aud / exp(±60s)
# ---------------------------------------------------------------------------


def test_step3_rejects_token_signed_by_another_key(verifier: TokenVerifier) -> None:
    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _sign(forged_key, _claims())
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {token}"))
    assert (excinfo.value.step, excinfo.value.reason) == (3, "bad_signature")


def test_step3_rejects_none_algorithm(verifier: TokenVerifier) -> None:
    """**经典攻击**：`alg=none`（去掉签名）。

    若 `algorithms` 没写死（或写成 `None` 让它从 header 取），这条就会**通过** ——
    任何人不带密钥即可伪造任意身份。**这是本文件最重要的一条断言。**

    ⚠️ 必须带 `kid`：否则会在**步 2**（查不到密钥）就失败，
    于是"步 3 的算法白名单是否生效"根本没被验证 —— 一个假绿灯。
    """
    unsigned = jwt.encode(_claims(), key="", algorithm="none", headers={"kid": KID})
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {unsigned}"))
    assert (excinfo.value.step, excinfo.value.reason) == (3, "invalid_token")


def test_step3_rejects_hs256_signed_with_public_key(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """**另一种经典攻击**：用 RS256 的**公钥**当 HMAC 密钥签 HS256。

    公钥是公开的（本仓库的 stub 就是一个 PEM 文件），所以这个攻击极其廉价。
    防御完全依赖 `algorithms=["RS256"]` 白名单 —— 这正是"写死而不是可配置"的理由。
    """
    pem = rsa_keys[1].public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    hs = _craft_hs256(_claims(), pem, kid=KID)
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {hs}"))
    assert excinfo.value.step == 3


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("iss", "https://evil.example", "bad_issuer"),
        ("aud", "another-api", "bad_audience"),
    ],
)
def test_step3_rejects_wrong_issuer_and_audience(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any], field: str, value: str, reason: str
) -> None:
    """`iss` / `aud` 缺一不可：只验签名不验来源，等于接受"任何用同一密钥签的令牌"。"""
    token = _sign(rsa_keys[0], _claims(**{field: value}))
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {token}"))
    assert (excinfo.value.step, excinfo.value.reason) == (3, reason)


def test_step3_expired_token_is_rejected(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    token = _sign(rsa_keys[0], _claims(exp=int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())))
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {token}"))
    assert (excinfo.value.step, excinfo.value.reason) == (3, "expired")


@pytest.mark.parametrize("offset_s", [59, -59])
def test_step3_tolerates_clock_skew_within_60s(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any], offset_s: int
) -> None:
    """**±60s 是必需而不是宽松**：多实例时钟不可能严格同步。

    ⚠️ 两个方向都要测：只测"刚过期 30s 仍放行"会漏掉"时钟快的那台机器
    把还没生效的令牌拒掉"（`iat` 在未来），而后者的表现是随机 401，极难定位。
    """
    now = datetime.now(UTC)
    claims = _claims(
        iat=int((now + timedelta(seconds=offset_s)).timestamp()),
        exp=int((now + timedelta(seconds=offset_s + 600)).timestamp()),
    )
    verified = asyncio.run(verifier.verify(f"Bearer {_sign(rsa_keys[0], claims)}"))
    assert verified.subject == "u_001"


def test_step3_rejects_beyond_60s_skew(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """容差**有上界**：否则 leeway 配错（比如配成 1 天）不会被发现。"""
    past = datetime.now(UTC) - timedelta(seconds=300)
    token = _sign(rsa_keys[0], _claims(exp=int(past.timestamp())))
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {token}"))
    assert excinfo.value.reason == "expired"


# ---------------------------------------------------------------------------
# 步 4：jti 撤销
# ---------------------------------------------------------------------------


def test_step4_revoked_token_uses_a_different_error_code(rsa_keys: tuple[Any, Any]) -> None:
    """★ `TOKEN_REVOKED` ≠ `AUTH_FAILED`：前端处理完全不同（前者还要提示"已被登出"）。"""
    revocation = InMemoryRevocationList()
    revocation.revoke("jti_revoked", expires_at=datetime.now(UTC) + timedelta(hours=1))
    verifier = TokenVerifier(
        jwks=JwksCache(_StaticJwksSource({KID: rsa_keys[1]})),
        issuer=ISSUER,
        audience=AUDIENCE,
        revocation=revocation,
    )
    token = _sign(rsa_keys[0], _claims(jti="jti_revoked"))
    with pytest.raises(TokenRevokedError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {token}"))
    assert excinfo.value.default_code == "TOKEN_REVOKED"


def test_step4_revocation_happens_after_signature_check(rsa_keys: tuple[Any, Any]) -> None:
    """**顺序不可颠倒**：撤销名单是一次查询，先查它等于把未验签的 `jti`
    （攻击者完全可控）送进存储层 —— 一个廉价的 DoS 面。
    """
    revocation = InMemoryRevocationList()
    revocation.revoke("jti_revoked", expires_at=datetime.now(UTC) + timedelta(hours=1))
    verifier = TokenVerifier(
        jwks=JwksCache(_StaticJwksSource({KID: rsa_keys[1]})),
        issuer=ISSUER,
        audience=AUDIENCE,
        revocation=revocation,
    )
    # jti 命中撤销名单，但签名是伪造的 → 必须报**签名错**（步 3），而不是 TOKEN_REVOKED
    forged = _sign(
        rsa.generate_private_key(public_exponent=65537, key_size=2048), _claims(jti="jti_revoked")
    )
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {forged}"))
    assert excinfo.value.step == 3


def test_revocation_list_purges_expired_entries() -> None:
    """过期条目必须清理：否则撤销名单只增不减 → 内存泄漏 + 查询变慢。"""
    revocation = InMemoryRevocationList()
    revocation.revoke("jti_old", expires_at=datetime.now(UTC) - timedelta(seconds=1))
    revocation.revoke("jti_new", expires_at=datetime.now(UTC) + timedelta(hours=1))
    assert asyncio.run(revocation.is_revoked("jti_old")) is False
    assert asyncio.run(revocation.is_revoked("jti_new")) is True
    assert len(revocation) == 1


# ---------------------------------------------------------------------------
# 步 5：必需 claims
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", REQUIRED_CLAIMS)
def test_step5_every_required_claim_is_enforced(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any], missing: str
) -> None:
    """**逐个 claim 都要测**（07 §13.1 第 5 步的 7 项）。

    参数化而不是抽查：漏掉 `tenant_id` 会让越权在一次"顺手删个字段"之后悄悄出现。
    """
    claims = _claims()
    del claims[missing]
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {_sign(rsa_keys[0], claims)}"))
    assert (excinfo.value.step, excinfo.value.reason) == (5, "missing_claim")


def test_step5_unknown_role_is_rejected_not_downgraded(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """非法 `role` **必须报错**。

    两种"宽容"做法都是错的：
    ① 跳过 → 放行一个身份不明的调用者；
    ② 当成最低权限 → **静默降权**，用户看到的是"没权限"而日志里什么都没有。
    """
    token = _sign(rsa_keys[0], _claims(role="superuser"))
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {token}"))
    assert (excinfo.value.step, excinfo.value.reason) == (5, "unknown_role")


def test_verified_token_normalizes_scope_string_and_list(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """`scope` 两种形态都要接受：RFC 8693 是**空格分隔字符串**，不少 IdP 给 **JSON 数组**。

    只支持一种会让"换个 IdP 就全 401"，而原因藏在 claim 的序列化方式里。
    """
    as_str = asyncio.run(verifier.verify(f"Bearer {_sign(rsa_keys[0], _claims(scope='orders:read shops:read'))}"))
    as_list = asyncio.run(verifier.verify(f"Bearer {_sign(rsa_keys[0], _claims(scope=['orders:read', 'shops:read']))}"))
    assert as_str.scope_claims == as_list.scope_claims == ("orders:read", "shops:read")


def test_null_valued_required_claim_counts_as_missing(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any]
) -> None:
    """`scope: null` → **步 5** 失败，而不是"归一为空元组"。

    ⚠️ 这条纠正了一个容易写错的直觉（我第一版就写错了）：
    PyJWT 的 `require` 判定不是 `claim in payload`，而是 **`payload.get(claim) is None`** ——
    即**值为 `null` 与键不存在等价**。
    这是本项目想要的语义：`scope=null` 若被当成"无 scope"放行，
    就制造了一个"合法令牌但权限字段被清空"的形态，而它与"忘了签 scope"无法区分。
    """
    with pytest.raises(AuthError) as excinfo:
        asyncio.run(verifier.verify(f"Bearer {_sign(rsa_keys[0], _claims(scope=None))}"))
    assert (excinfo.value.step, excinfo.value.reason) == (5, "missing_claim")


def test_absent_shop_ids_and_noisy_scope_elements_are_tolerated(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any]
) -> None:
    """`shop_ids` 缺失合法；`scope` 里的**非字符串元素**是"格式噪声"而非越权。

    两者的分工不同：
    · `shop_ids` **不在** `REQUIRED_CLAIMS` 里 —— 缺它合法（07 §13.2：空 = 不限制）。
      空 `shop_ids` 是**危险语义**，但边界在 `guard`（W2C），不在认证层；
      认证层替它"默认收紧"会制造一份看不见的第二权限规则。
    · `scope` 元素类型不对 → 丢弃而不是抛错（抛错会让"IdP 顺序变了"表现成"用户被拒"）。
    """
    claims = _claims()
    claims.pop("shop_ids")
    no_shops = asyncio.run(verifier.verify(f"Bearer {_sign(rsa_keys[0], claims)}"))
    assert no_shops.shop_ids == ()

    noisy = asyncio.run(
        verifier.verify(f"Bearer {_sign(rsa_keys[0], _claims(scope=['a', 1, {'x': 'y'}, 'b']))}")
    )
    assert noisy.scope_claims == ("a", "b")


# ---------------------------------------------------------------------------
# 步 6：不可变 IdentityContext
# ---------------------------------------------------------------------------


def _verified(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> Any:
    return asyncio.run(verifier.verify(f"Bearer {_sign(rsa_keys[0], _claims())}"))


def test_step6_identity_is_frozen(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """★ **"进图之后只读"是类型事实，不是纪律**（07 §5.2 组 1）。

    若它只是 `dataclass`，任何节点都能 `ctx.role = Role.PLATFORM_ADMIN` ——
    而那种越权不会报错、不会留痕。
    """
    ctx = build_identity(_verified(verifier, rsa_keys), trace_id="tr_1", task_id="tk_1", session_id="se_1")
    with pytest.raises(Exception) as excinfo:
        ctx.role = Role.PLATFORM_ADMIN  # type: ignore[misc]
    assert "frozen" in type(excinfo.value).__name__.lower() or "FrozenInstance" in str(excinfo.value)


def test_step6_identity_fields_come_only_from_the_token(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """身份四要素（`tenant_id` / `user_id` / `role` / `scope_claims`）**只来自令牌**。"""
    token = _verified(verifier, rsa_keys)
    ctx = build_identity(token, trace_id="tr_1", task_id="tk_1", session_id="se_1")
    assert (ctx.tenant_id, ctx.user_id, ctx.role, ctx.scope_claims) == (
        "t_001",
        "u_001",
        Role.OPERATOR,
        ("orders:read", "shops:read"),
    )
    assert ctx.shop_ids == ("s_001", "s_002")


@pytest.mark.parametrize("blank", ["trace_id", "task_id", "session_id"])
def test_step6_blank_runtime_identifiers_are_rejected(
    verifier: TokenVerifier, rsa_keys: tuple[Any, Any], blank: str
) -> None:
    """运行标识（trace/task/session）**由服务端生成**，缺了它审计与 trace 无法关联。

    ⚠️ 这里刻意**不**给默认值：一个 `session_id=""` 的默认值会让
    `thread_id = t:u:`（空段）成为可能，而那是**跨用户串会话**的入口。
    """
    kwargs: dict[str, str] = {"trace_id": "tr_1", "task_id": "tk_1", "session_id": "se_1"}
    kwargs[blank] = ""
    with pytest.raises(ValueError, match=blank):
        build_identity(_verified(verifier, rsa_keys), **kwargs)


def test_step6_build_identity_has_no_second_identity_input(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """★ **禁令 1/2 的结构性落实**：签名里没有可以传 `tenant_id` / `role` / `shop_ids` 的地方。

    这不是形式检查 —— "多加一个可选参数覆盖令牌值"就是越权入口，
    而且它看起来完全合理（"调试用"）。
    """
    import inspect

    params = inspect.signature(build_identity).parameters
    banned = {"tenant_id", "role", "shop_ids", "user_id", "scope_claims", "subject"}
    assert not (set(params) & banned), f"`build_identity` 出现了可覆盖身份的参数：{sorted(set(params) & banned)}"


# ---------------------------------------------------------------------------
# 步 7：contextvar
# ---------------------------------------------------------------------------


def test_step7_contextvar_roundtrip_and_reset(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """`bind` / `reset` 必须成对 —— 不复位会造成**跨租户身份串台**（最难查的一类泄露）。"""
    ctx = build_identity(_verified(verifier, rsa_keys), trace_id="tr_1", task_id="tk_1", session_id="se_1")
    assert identity_or_none() is None

    token = bind_identity(ctx)
    assert current_identity() is ctx
    reset_identity(token)
    assert identity_or_none() is None


def test_step7_unbound_identity_raises_instead_of_defaulting(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """★ **不得用"匿名上下文"兜底**：默认身份必然比真实身份更宽（否则它没法通用），
    于是"忘了绑定身份"会静默变成"以更宽的身份跑完全程"。
    """
    with pytest.raises(RuntimeError, match="未绑定身份"):
        current_identity()


def test_step7_identity_does_not_leak_across_tasks(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """★ contextvar 的隔离性 —— 也是它**不能当授权依据**的原因（见 `context.py` 顶部说明）。

    本用例同时钉两件事：
    ① 新 task 不会继承**已重置**的身份；
    ② `asyncio.create_task` **会复制**当前 context（因此后台任务可能带着一个**过期的**身份）。
    第 ② 条是"授权一律用显式传入的 `IdentityContext`"这条纪律的实证依据。
    """
    ctx = build_identity(_verified(verifier, rsa_keys), trace_id="tr_1", task_id="tk_1", session_id="se_1")
    token = bind_identity(ctx)
    reset_identity(token)

    seen: list[Any] = []

    async def _child() -> None:
        seen.append(identity_or_none())

    asyncio.run(_child())
    assert seen == [None], "重置之后新 task 不得看到身份"


def test_step7_create_task_inherits_context(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """显式记录"复制"行为：它是**特性**（日志能带上身份），也是**陷阱**（授权不能用它）。"""
    ctx = build_identity(_verified(verifier, rsa_keys), trace_id="tr_1", task_id="tk_1", session_id="se_1")

    async def _main() -> list[Any]:
        token = bind_identity(ctx)
        try:
            return await asyncio.gather(*[_child_once() for _ in range(3)])
        finally:
            reset_identity(token)

    async def _child_once() -> Any:
        return identity_or_none()

    got = asyncio.run(_main())
    assert all(item is ctx for item in got), "`create_task` 会复制 context —— 后台任务会继承调用时的身份"


def test_step7_obs_fields_use_schema_names(verifier: TokenVerifier, rsa_keys: tuple[Any, Any]) -> None:
    """第 7 步"写入 contextvar 供 obs 记录"具体是哪 4 个字段（07 §13.1 逐字）。

    ⚠️ 字段名必须取自 `obs/schema.py`（唯一定义处）：
    一个 `tenantId` / `tenant_id` 的差异既不报错也不影响功能，只是**永远排不了障**。
    """
    ctx = build_identity(_verified(verifier, rsa_keys), trace_id="tr_1", task_id="tk_1", session_id="se_1")
    fields = identity_obs_fields(ctx)
    assert set(fields) == {LogField.TRACE_ID, LogField.TENANT_ID, LogField.USER_ID, LogField.ROLE}
    assert fields[LogField.TENANT_ID] == "t_001"
    assert fields[LogField.ROLE] == Role.OPERATOR.value
    # 令牌原文绝不进 obs
    assert not any("eyJ" in value for value in fields.values())
