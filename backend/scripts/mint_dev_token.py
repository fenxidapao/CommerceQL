"""签发一枚**本地开发用**的访问令牌（RS256），并自证它能被真实的认证链验过。

归属窗口：W1B（`docs/08 §4.1` v1.2 / U-42：`backend/scripts/**` → W1B）。

## 这个脚本补的是哪个洞

D-H（登录端点）未裁 ⇒ **没有任何地方签发令牌**。`/login` 不在 W4 的端点清单里，
而认证链（`app/auth/tokens.py`，W1B 已交付）是完整可跑的：它要的只是一枚
用 RS256 签、`kid=default`、claims 齐全的令牌，以及一把摆在 `JWT_PUBLIC_KEY_PATH` 的公钥。
没有这个脚本，前端那个"粘贴 token"的框永远粘贴不出一枚可用令牌 —— **不是链路断，是没人签发**。

## 为什么必须自证（而不是只打印令牌）

脚本会用**应用自己的 `TokenVerifier`**（不是另写一套校验）验一遍刚签的令牌：
`JwksCache(PemFileJwksSource(公钥文件))` → `verify("Bearer <token>")`。
⇒ 令牌能用是**被证明的**，不是"应该能用"。
⚠️ 少了这一步，`iss`/`aud`/`kid`/claim 名任何一处写错都会变成
"前端说 401、后端说令牌没问题"的扯皮（而且错处在脚本里，不在应用里）。

## 密钥从哪来

仓库里**没有任何密钥对**（`.pem` 只在 `.venv/` 里，是依赖自带的）。
所以首次运行会生成一把 RSA-2048 并落盘（默认 `deploy/secrets/`，被 `.gitignore`
的 `secrets/` + `*.pem` 双重忽略）。**私钥不进仓库、也不进日志。**

## 用法

```bash
# 首次：生成密钥对 + 签发 + 自验（令牌打到 stdout）
python scripts/mint_dev_token.py --tenant-id tenant_a --user-id u_1 --role analyst

# 之后：复用私钥（公钥文件已存在时不会覆盖，除非给 --force-public-key）
python scripts/mint_dev_token.py --tenant-id tenant_a --role analyst

# 让容器里的 api 也能验这枚令牌（compose 没有挂载公钥 ⇒ 必须自己拷；需 -u root）
python scripts/mint_dev_token.py --tenant-id tenant_a --role analyst \
    --docker-container commerceql-api-1
```

⚠️ **持久化公钥的归属不在本脚本**：`deploy/docker-compose.yml` 属 **W0**，
给 api 加一条 `../deploy/secrets/jwt_public.pem:/run/secrets/jwt_public.pem:ro`
才能让容器重启后仍然验得过（`--docker-container` 是临时手段）。这条已登记在
`reports/w1b/RELAY.md`（→ W0）。

⚠️ **这是开发工具，不是生产签发器**：私钥以明文落盘、`jti` 用 `uuid4`、
不做撤销登记。生产由真实 IdP 签发（ADR-17：只把 JWKS 来源做成配置）。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:  # 让 `python scripts/mint_dev_token.py` 也能 import app.*
    sys.path.insert(0, str(_BACKEND))

from app.auth.jwks import DEFAULT_KID, JwksCache, PemFileJwksSource  # noqa: E402
from app.auth.revocation import InMemoryRevocationList  # noqa: E402
from app.auth.tokens import REQUIRED_CLAIMS, TokenVerifier  # noqa: E402
from app.core.enums import Role  # noqa: E402

_DEFAULT_SECRETS_DIR = _BACKEND.parent / "deploy" / "secrets"
_DEFAULT_PRIVATE_KEY = _DEFAULT_SECRETS_DIR / "jwt_private.pem"
_DEFAULT_PUBLIC_KEY = _DEFAULT_SECRETS_DIR / "jwt_public.pem"


def _settings_default(field: str) -> str:
    """从 `app.core.config.Settings` 取**字段默认值**（不实例化，故不依赖 3 个 DSN 环境变量）。

    ⚠️ 刻意不在这里写 `"workbuddy-demo"` 字面量：`iss`/`aud` 的权威源是 Settings，
    在脚本里再抄一份 = 两份真相。Settings 被改成别的值时，这里会跟着变。
    """
    from app.core.config import Settings

    default = Settings.model_fields[field].default
    if not isinstance(default, str) or not default:
        raise SystemExit(
            f"无法从 Settings 读到 {field} 的默认值（实为 {default!r}）—— "
            f"请显式传 --issuer/--audience"
        )
    return default


def _resolve_iss_aud(args: argparse.Namespace) -> tuple[str, str]:
    """解析 `iss`/`aud`：命令行 > 环境变量 > Settings 默认值（与应用的读取顺序一致）。"""
    issuer = args.issuer or os.environ.get("JWT_ISSUER") or _settings_default("JWT_ISSUER")
    audience = (
        args.audience or os.environ.get("JWT_AUDIENCE") or _settings_default("JWT_AUDIENCE")
    )
    return issuer, audience


def _load_or_create_private_key(path: Path) -> tuple[rsa.RSAPrivateKey, bool]:
    """返回 `(私钥, 是否新生成)`。"""
    if path.exists():
        return (
            cast(rsa.RSAPrivateKey, serialization.load_pem_private_key(path.read_bytes(), password=None)),
            False,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    # POSIX 上收权限；Windows 上是 no-op（ACL 由目录继承），失败不该让签发失败。
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return key, True


def _public_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    pem: bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem


def _verify_with_real_chain(token: str, *, public_key_path: Path, issuer: str, audience: str) -> str:
    """用**应用自己的**认证链验一遍。返回被验出的身份摘要（给操作者看）。"""
    import asyncio

    verifier = TokenVerifier(
        jwks=JwksCache(PemFileJwksSource(public_key_path)),
        issuer=issuer,
        audience=audience,
        revocation=InMemoryRevocationList(),
    )
    verified = asyncio.run(verifier.verify(f"Bearer {token}"))
    return (
        f"sub={verified.subject} tenant_id={verified.tenant_id} "
        f"role={verified.role.value} scope={list(verified.scope_claims)} kid={verified.kid}"
    )


def _parse_scope(raw: str | None) -> str | None:
    """空格分隔的 scope 串（RFC 8693 / OAuth2 形态；`_as_str_tuple` 也吃空格分隔串）。"""
    if not raw:
        return None
    return " ".join(part for part in raw.replace(",", " ").split() if part)


def _build_claims(
    *,
    subject: str,
    tenant_id: str,
    role: Role,
    scope: str | None,
    shop_ids: list[str] | None,
    issuer: str,
    audience: str,
    ttl_s: int,
    now: datetime,
    jti: str,
) -> dict[str, Any]:
    """构造 claims —— **纯函数**（唯一需要自证正确的一段，故可被单测直接覆盖）。

    ⚠️ 三条都被首版的真实校验抓出来过，别删：

    1. **`iss` / `aud` 必须自己写进 claims**：它们不在 `REQUIRED_CLAIMS` 里
       （那是 07 §13.1 第 5 步的"必备项"），但 `TokenVerifier` 会把
       `issuer=`/`audience=` 传给 `jwt.decode` ⇒ **PyJWT 在令牌缺 `iss`/`aud` 时报
       `InvalidIssuerError`/`InvalidAudienceError`**（不是"跳过校验"）。
       首版没写这两个 claim，脚本自证当场红。
    2. **`scope` 是必需 claim**（在 `REQUIRED_CLAIMS` 内）⇒ 即使操作者没给 `--scope` 也
       必须**发出这个键**（缺键 = PyJWT `missing_claim` → 401）。故这里的取值是
       "空串而不是 None"：`None` 会让 `jwt.encode` 落成 `null`，`_as_str_tuple(None)` → `()`。
    3. `role` 取 `.value`（StrEnum）：写进令牌的是字面值，不是 `Role.ANALYST` 的 repr。
    """
    claims: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role.value,
        "scope": scope or "",
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_s)).timestamp()),
        #: `jti` 只是唯一标识（撤销名单的键）；这里要唯一，不需要可读前缀 ⇒ uuid4。
        "jti": jti,
    }
    if shop_ids:
        #: ⚠️ 空列表**不发这个键**：`_as_str_tuple` 对 `None` 与 `[]` 都返回 `()`，
        #: 但"键不存在"与"键为空"在排查时不是一回事（前者说明没设置，后者说明设置成空）。
        claims["shop_ids"] = list(shop_ids)
    return claims


def _sign(private_key: rsa.RSAPrivateKey, claims: dict[str, Any]) -> str:
    """RS256 + `kid=default`（`DEFAULT_KID`：ADR-17 单文件 PEM stub 的唯一键）。"""
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": DEFAULT_KID})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="签发本地开发用 RS256 令牌，并用真实认证链自证可用。",
        epilog=(
            f"可用角色（Role）：{', '.join(r.value for r in Role)}\n"
            f"必需 claims（07 §13.1 第 5 步，逐字）：{', '.join(REQUIRED_CLAIMS)}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tenant-id", required=True, help="租户 ID（写进 tenant_id claim）")
    parser.add_argument("--user-id", default="u_dev", help="用户 ID（写进 sub claim）")
    parser.add_argument(
        "--role", default=Role.ANALYST.value,
        help="角色，必须在 Role 枚举内（默认 analyst；可用值见 --help 末尾）",
    )
    parser.add_argument("--scope", default=None, help="空格或逗号分隔的 scope（可选）")
    parser.add_argument("--shop-ids", default=None, help="逗号分隔的 shop_id（可选）")
    parser.add_argument("--ttl", type=int, default=3600, help="有效期秒数（默认 3600）")
    parser.add_argument("--issuer", default=None, help="覆盖 iss（默认读 JWT_ISSUER / Settings）")
    parser.add_argument("--audience", default=None, help="覆盖 aud（默认读 JWT_AUDIENCE / Settings）")
    parser.add_argument("--private-key", type=Path, default=_DEFAULT_PRIVATE_KEY)
    parser.add_argument("--public-key-out", type=Path, default=_DEFAULT_PUBLIC_KEY)
    parser.add_argument(
        "--force-public-key", action="store_true",
        help="公钥文件已存在时仍覆盖（默认不覆盖，避免把别人的联调令牌打断）",
    )
    parser.add_argument(
        "--docker-container", default=None,
        help="把公钥 `docker cp` 进该容器的 JWT_PUBLIC_KEY_PATH（compose 未挂载公钥）",
    )
    args = parser.parse_args(argv)

    if args.role is None:
        parser.error("--role 必填（可用值见 --help 末尾）")
    try:
        role = Role(args.role)
    except ValueError:
        parser.error(
            f"--role {args.role!r} 不在 Role 枚举内；可用：{', '.join(r.value for r in Role)}"
        )
    issuer, audience = _resolve_iss_aud(args)
    private_key, generated = _load_or_create_private_key(args.private_key)
    public_pem = _public_pem(private_key)

    wrote_public = True
    if args.public_key_out.exists() and not args.force_public_key:
        existing = args.public_key_out.read_bytes()
        if existing != public_pem:
            print(
                f"⚠️  {args.public_key_out} 已存在且与本次私钥不匹配 —— 未覆盖。\n"
                f"    若就是要换钥匙（会让已签发的令牌全部失效），加 --force-public-key。",
                file=sys.stderr,
            )
        wrote_public = False
    else:
        args.public_key_out.parent.mkdir(parents=True, exist_ok=True)
        args.public_key_out.write_bytes(public_pem)

    now = datetime.now(UTC)
    claims = _build_claims(
        subject=args.user_id,
        tenant_id=args.tenant_id,
        role=role,
        scope=_parse_scope(args.scope),
        shop_ids=[s.strip() for s in args.shop_ids.split(",") if s.strip()]
        if args.shop_ids
        else None,
        issuer=issuer,
        audience=audience,
        ttl_s=args.ttl,
        now=now,
        jti=uuid.uuid4().hex,
    )

    missing = [c for c in REQUIRED_CLAIMS if c not in claims]
    if missing:
        raise SystemExit(f"内部错误：以下必需 claim 未构造 —— {missing}（单测应拦住这种改动）")

    token = _sign(private_key, claims)

    identity = _verify_with_real_chain(
        token, public_key_path=args.public_key_out, issuer=issuer, audience=audience
    )

    print(f"[mint] 私钥 {'新生成' if generated else '复用'}：{args.private_key}", file=sys.stderr)
    print(
        f"[mint] 公钥 {'已写出' if wrote_public else '未改动'}：{args.public_key_out}",
        file=sys.stderr,
    )
    print(f"[mint] iss={issuer} aud={audience} kid={DEFAULT_KID} ttl={args.ttl}s", file=sys.stderr)
    print(f"[verify] ✅ 真实认证链验过：{identity}", file=sys.stderr)

    copied = False
    if args.docker_container:
        target = f"{args.docker_container}:/run/secrets/jwt_public.pem"
        # ⚠️ `-u root`：api 容器**以非 root 用户运行**（实测 `/run` 不可写：
        # `mkdir: cannot create directory '/run/secrets': Permission denied`），
        # 不加 `-u root` 会在 `docker cp` 处报 "Could not find the file /run/secrets"。
        # ⚠️ 注意这只是**临时**让容器能验签：容器重启（若为无卷挂载）后这条就没了。
        # 持久做法是给 compose 的 api 加一条只读挂载 —— `deploy/**` 属 W0，本脚本不改它。
        subprocess.run(
            ["docker", "exec", "-u", "root", args.docker_container, "mkdir", "-p", "/run/secrets"],
            capture_output=True, text=True,
        )
        result = subprocess.run(
            ["docker", "cp", str(args.public_key_out), target],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            copied = True
            print(f"[docker] 公钥已拷进 {target}（容器重启后失效，见 --help 的持久做法）",
                  file=sys.stderr)
        else:
            print(f"⚠️  docker cp 失败（{result.stderr.strip()}）—— 手动拷：", file=sys.stderr)
            print(f"    docker exec -u root {args.docker_container} mkdir -p /run/secrets",
                  file=sys.stderr)
            print(f"    docker cp {args.public_key_out} {target}", file=sys.stderr)

    if not copied:
        print(
            "[next] compose **没有**挂载公钥，容器内的 JWT_PUBLIC_KEY_PATH 默认不存在。二选一：",
            file=sys.stderr,
        )
        print(
            f"       docker cp {args.public_key_out} <容器>:/run/secrets/jwt_public.pem",
            file=sys.stderr,
        )
        print(
            "       （或给 deploy/docker-compose.yml 的 api 加一条只读挂载后重启）",
            file=sys.stderr,
        )

    print(
        "[curl] curl -H \"Authorization: Bearer $(cat -)\" http://127.0.0.1:8000/api/v1/healthz/ready",
        file=sys.stderr,
    )

    # 令牌单独走 stdout（诊断走 stderr）⇒ `TOKEN=$(python scripts/mint_dev_token.py …)` 可用
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
