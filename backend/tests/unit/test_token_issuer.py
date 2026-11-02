"""B3：`TokenIssuer` 与真实验证链闭环（签发 → `TokenVerifier.verify`）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.jwks import JwksCache, PemFileJwksSource
from app.auth.revocation import InMemoryRevocationList
from app.auth.tokens import TokenIssuer, TokenVerifier
from app.core.enums import Role

_ISSUER = "workbuddy-demo"
_AUDIENCE = "text2sql-agent"


@pytest.fixture()
def keys(tmp_path: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "jwt_private.pem"
    public_path = tmp_path / "jwt_public.pem"
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


async def test_issued_token_verifies_with_the_real_chain(keys: tuple[Path, Path]) -> None:
    private_path, public_path = keys
    issuer = TokenIssuer(
        str(private_path), issuer=_ISSUER, audience=_AUDIENCE, ttl_s=600
    )
    issued = issuer.issue(
        subject="user_abc", tenant_id="T_A", role=Role.ANALYST, shop_ids=("s1",)
    )
    verifier = TokenVerifier(
        jwks=JwksCache(PemFileJwksSource(str(public_path))),
        issuer=_ISSUER,
        audience=_AUDIENCE,
        revocation=InMemoryRevocationList(),
    )
    verified = await verifier.verify(f"Bearer {issued.access_token}")
    assert verified.subject == "user_abc"
    assert verified.tenant_id == "T_A"
    assert verified.role is Role.ANALYST
    assert verified.shop_ids == ("s1",)
    assert verified.jti == issued.jti
    assert issued.expires_in == 600


def test_missing_private_key_is_a_server_error(tmp_path: Path) -> None:
    issuer = TokenIssuer(
        str(tmp_path / "missing.pem"), issuer=_ISSUER, audience=_AUDIENCE, ttl_s=60
    )
    with pytest.raises(RuntimeError, match="JWT 私钥不可用"):
        issuer.issue(subject="u", tenant_id="T_A", role=Role.ANALYST)


def test_non_positive_ttl_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        TokenIssuer(str(tmp_path / "x.pem"), issuer=_ISSUER, audience=_AUDIENCE, ttl_s=0)
