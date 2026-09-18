"""`scripts/mint_dev_token.py` 的离线契约测试 —— 令牌**真的能被认证链验过**。

归属窗口：W1B。

这个脚本的存在理由 = "没人签发令牌"（D-H 未裁）：它是 W4↔W5 真实联调的唯一入口，
所以它的正确性不能靠"跑一次看着像对的"。本文件把三件事钉死：

| # | 断言 | 为什么必须机器化 |
|---|---|---|
| 1 | claims 齐全（含 `REQUIRED_CLAIMS` **与** `iss`/`aud`） | 首版漏了 `iss`/`aud`（它们不在 `REQUIRED_CLAIMS` 里，但 `jwt.decode(issuer=…, audience=…)` 会校验）→ 令牌被自己的认证链拒 |
| 2 | 签出来的令牌能被**应用自己的 `TokenVerifier`** 验过（真 RSA + 真 PEM 文件） | 少了这条，"脚本说签好了、应用说 401"就成了扯皮 |
| 3 | **删掉 `iss` 必须让验证失败**（负向对照） | 否则第 1 条只是"字符串在场"的断言，证明不了它真的参与校验 |

⚠️ 本文件不碰网络、不碰 PG：公钥写进 `tmp_path`，用 `PemFileJwksSource` 直接读。
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.jwks import DEFAULT_KID, JwksCache, PemFileJwksSource
from app.auth.revocation import InMemoryRevocationList
from app.auth.tokens import REQUIRED_CLAIMS, TokenVerifier
from app.core.enums import Role

pytestmark = pytest.mark.contract

_BACKEND = Path(__file__).resolve().parents[2]
_SCRIPT = _BACKEND / "scripts" / "mint_dev_token.py"

_ISSUER = "issuer-for-test"
_AUDIENCE = "audience-for-test"


@pytest.fixture(scope="module")
def mint() -> Any:
    """按路径加载脚本（`scripts/` 不是包，无法 import）。"""
    spec = importlib.util.spec_from_file_location("mint_dev_token", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rsa_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def public_key_path(rsa_key: Any, tmp_path: Path) -> Path:
    path = tmp_path / "jwt_public.pem"
    path.write_bytes(
        rsa_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return path


def _verify(token: str, public_key_path: Path) -> Any:
    verifier = TokenVerifier(
        jwks=JwksCache(PemFileJwksSource(public_key_path)),
        issuer=_ISSUER,
        audience=_AUDIENCE,
        revocation=InMemoryRevocationList(),
    )
    return asyncio.run(verifier.verify(f"Bearer {token}"))


def _claims(mint: Any, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "subject": "u_dev",
        "tenant_id": "tenant_a",
        "role": Role.ANALYST,
        "scope": "query:read",
        "shop_ids": None,
        "issuer": _ISSUER,
        "audience": _AUDIENCE,
        "ttl_s": 600,
        #: ⚠️ 必须是**真实的现在**，不能写一个固定时刻：PyJWT 2.14 的 `_validate_iat`
        #: 会拒"`iat` 在未来"的令牌（`ImmatureSignatureError`），而 `TokenVerifier` 把它
        #: 归到 step 3 的兜底 `invalid_token` —— 首版写死 `2026-09-18T12:00Z` 时，
        #: 三条端到端用例全红，报的却是"令牌校验失败"，方向完全看不出是 iat 问题。
        "now": datetime.now(UTC),
        "jti": "jti_for_test",
    }
    kwargs.update(overrides)
    return mint._build_claims(**kwargs)


# ============================================================================
# 1. claims 齐全（含 REQUIRED_CLAIMS 之外的 iss/aud）
# ============================================================================

def test_claims_cover_required_set_and_iss_aud(mint: Any) -> None:
    """`REQUIRED_CLAIMS` 是 07 §13.1 第 5 步的**必备项**；`iss`/`aud` 另有校验（见下一条）。"""
    claims = _claims(mint)
    missing = [c for c in REQUIRED_CLAIMS if c not in claims]
    assert not missing, f"缺必需 claim：{missing}"
    assert claims["iss"] == _ISSUER and claims["aud"] == _AUDIENCE
    assert claims["role"] == "analyst", "role 必须是枚举字面值，不是 Role.ANALYST 的 repr"


def test_scope_claim_is_always_emitted(mint: Any) -> None:
    """`scope` 在 `REQUIRED_CLAIMS` 内 ⇒ 没给 `--scope` 也要**发出这个键**（空串），不能省略。

    省略会让 PyJWT 报 `missing_claim` → 401，而操作者看到的现象是"我明明没设 scope 却 401"。
    """
    claims = _claims(mint, scope=None)
    assert "scope" in claims and claims["scope"] == ""


def test_shop_ids_only_when_provided(mint: Any) -> None:
    assert "shop_ids" not in _claims(mint)
    assert _claims(mint, shop_ids=["s1", "s2"])["shop_ids"] == ["s1", "s2"]


def test_parse_scope_normalizes(mint: Any) -> None:
    assert mint._parse_scope("query:read, clarify:write") == "query:read clarify:write"
    assert mint._parse_scope("  query:read   clarify:write ") == "query:read clarify:write"
    assert mint._parse_scope(None) is None
    assert mint._parse_scope("") is None


# ============================================================================
# 2. ★ 端到端：签出来的令牌必须被**应用自己的**认证链验过
# ============================================================================

def test_minted_token_verifies_with_real_chain(mint: Any, rsa_key: Any, public_key_path: Path) -> None:
    token = mint._sign(rsa_key, _claims(mint))
    verified = _verify(token, public_key_path)
    assert verified.subject == "u_dev"
    assert verified.tenant_id == "tenant_a"
    assert verified.role is Role.ANALYST
    assert verified.scope_claims == ("query:read",)
    assert verified.kid == DEFAULT_KID, "header 里的 kid 必须是 ADR-17 单文件 PEM 的那个键"


def test_token_header_is_rs256_with_default_kid(mint: Any, rsa_key: Any) -> None:
    token = mint._sign(rsa_key, _claims(mint))
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == DEFAULT_KID


# ============================================================================
# 3. 负向对照：删掉 iss / aud 必须让验证失败（否则前两条证明不了什么）
# ============================================================================

def test_missing_iss_is_rejected(mint: Any, rsa_key: Any, public_key_path: Path) -> None:
    """★ 这条是首版真实踩到的 bug 的机器化：`iss`/`aud` 不在 `REQUIRED_CLAIMS` 里，
    但 `jwt.decode(issuer=…)` 会把它补进 required 集合 ⇒ 缺了就被拒。

    ⚠️ 实测归因是 **step 5 `missing_claim`**（不是 step 3 `bad_issuer`）：
    PyJWT 在传了 `issuer=` 时会把 `iss` 加进必需 claim 集，
    所以"缺 iss"先被 `MissingRequiredClaimError` 拦下。断言写成"两者之一"而不是
    钉死某一个 —— 钉死会让 PyJWT 换个抛法就误红（而拒绝行为其实没变）。
    """
    claims = _claims(mint)
    claims.pop("iss")
    token = mint._sign(rsa_key, claims)
    with pytest.raises(Exception) as caught:
        _verify(token, public_key_path)
    rendered = str(caught.value)
    assert "missing_claim" in rendered or "bad_issuer" in rendered, rendered


def test_wrong_audience_is_rejected(mint: Any, rsa_key: Any, public_key_path: Path) -> None:
    claims = _claims(mint, audience="someone-else")
    token = mint._sign(rsa_key, claims)
    with pytest.raises(Exception) as caught:
        _verify(token, public_key_path)
    assert "bad_audience" in str(caught.value), str(caught.value)


# ============================================================================
# 4. CLI 面：非法角色必须在**签发前**被拒（不是签出一枚用不了的令牌）
# ============================================================================

def test_invalid_role_is_rejected_by_parser(mint: Any, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        mint.main([
            "--tenant-id", "tenant_a", "--role", "not_a_role",
            "--private-key", str(tmp_path / "k.pem"),
            "--public-key-out", str(tmp_path / "pub.pem"),
        ])


def test_main_end_to_end_writes_public_key(mint: Any, tmp_path: Path, capsys: Any) -> None:
    """整条 CLI 走一遍：生成私钥 → 写公钥 → 打印令牌（令牌只在 stdout）。"""
    private_key = tmp_path / "jwt_private.pem"
    public_key = tmp_path / "jwt_public.pem"
    code = mint.main([
        "--tenant-id", "tenant_a", "--user-id", "u_dev", "--role", "analyst",
        "--issuer", _ISSUER, "--audience", _AUDIENCE,
        "--private-key", str(private_key), "--public-key-out", str(public_key),
    ])
    assert code == 0
    assert private_key.exists() and public_key.exists()

    captured = capsys.readouterr()
    token = captured.out.strip().splitlines()[-1]
    assert token.count(".") == 2, f"stdout 最后一行应是令牌，实为 {token!r}"
    # 诊断信息必须走 stderr（否则 `TOKEN=$(…)` 会拿到一坨日志）
    assert "BEGIN" not in captured.out
    assert "[verify]" in captured.err

    verified = _verify(token, public_key)
    assert verified.tenant_id == "tenant_a"
