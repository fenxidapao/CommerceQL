"""认证链路 7 步中的第 1–5 步（07 §13.1）。

归属窗口：W1B。

| 步 | 动作 | 失败码 | 本模块 |
|---|---|---|---|
| 1 | 从 `Authorization: Bearer` 提取令牌 | `AUTH_FAILED` | ✅ `_extract_bearer` |
| 2 | 解 header 取 `kid` → 查 JWKS（本地缓存 10 分钟；miss 刷新一次，不清空缓存） | `AUTH_FAILED` | ✅ `app/auth/jwks.py` |
| 3 | 校验签名（**RS256**）、`iss`、`aud`、`exp`（容许 **±60s** 时钟偏移） | `AUTH_FAILED` | ✅ `TokenVerifier.verify` |
| 4 | 校验 `jti` 不在撤销名单 | **`TOKEN_REVOKED`** | ✅ `app/auth/revocation.py` |
| 5 | 校验必需 claims 齐全（`sub`/`tenant_id`/`role`/`scope`/`exp`/`iat`/`jti`） | `AUTH_FAILED` | ✅ `TokenVerifier.verify` |
| 6 | 构造**不可变** `TrustedContext` | — | `app/auth/context.py` |
| 7 | 写入 contextvar 供 `obs` 记录 | — | `app/auth/context.py` |

**四条禁令（07 §13.1 末表的机器化）**

| # | 禁令 | 本文件的落实 |
|---|---|---|
| 1 | `tenant_id` **禁止**从请求体或 query 取（只从 JWT） | `verify()` 的**唯一入参**是 `Authorization` 头 —— 没有第二个入口可传身份 |
| 2 | 禁止信任客户端传入的 `role` / `shop_ids` | 同上；`role` 由 `Role(...)` 白名单转换，非法值即 401 |
| 3 | 禁止把令牌原文写日志 | 所有异常消息只含**步骤号与原因**，见 `errors.py`；`repr` 亦不可含 |
| 4 | 禁止把令牌放 URL query | `_extract_bearer` 只认 header；传 URL 无从进入本模块 |

⚠️ **`TrustedContext` 的命名歧义（已登记，不擅自裁定）**
07 §13.1 第 6 步写的是 `TrustedContext`，而 §5.2 组 1 与 `core/contracts.py` 用的是
`IdentityContext`（**已冻结的 L0 值对象**）。两者描述的是同一件事。
→ 按"同一事实只能写一遍"（U-18 的教训），本窗口**不新建第二个值对象**，
   统一用 `IdentityContext`，并把该命名歧义登记为 **U-23**（请求架构窗口在 §13.1 加一句对应关系）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import jwt

from app.auth.errors import AuthError, TokenRevokedError
from app.auth.jwks import JwksCache
from app.auth.revocation import RevocationChecker
from app.core.enums import Role

__all__ = [
    "JWKS_LEEWAY_S",
    "REQUIRED_CLAIMS",
    "VerifiedToken",
    "TokenVerifier",
    "extract_bearer_token",
]

#: 07 §13.1 第 3 步：容许 **±60s** 时钟偏移。
#: ⚠️ 这不是"宽松"，是**必需**：多实例/容器与 IdP 的时钟不可能严格同步，
#: 设 0 会让"刚签发的令牌"在时钟慢的那台机器上被拒 —— 表现为随机 401，极难定位。
JWKS_LEEWAY_S: Final[int] = 60

#: 07 §13.1 第 5 步的必需 claims（**逐字对齐**，不得增减）。
REQUIRED_CLAIMS: Final[tuple[str, ...]] = ("sub", "tenant_id", "role", "scope", "exp", "iat", "jti")

#: 唯一允许的算法。**写死而不是可配置**：把 `none` / `HS256` 混进来的经典攻击
#: （用对称算法伪造、或直接去掉签名）都靠这一步拦住。可配置 = 可被配错。
_ALGORITHMS: Final[tuple[str, ...]] = ("RS256",)


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    """**已通过 5 步校验**的令牌事实（不可变）。

    ⚠️ 它是"服务端已确认的事实"，因此可以放心用于授权的**输入**；
    但它**不是** `IdentityContext` —— 后者还含 `trace_id` / `task_id` / `session_id`
    这些**由服务端生成**的运行标识（见 `context.py`）。
    把两者分开，是为了让"哪些字段来自令牌、哪些来自服务端"在类型上就看得见。

    ⚠️ `tenant_id` / `subject` 是 **PII**（N-12）：禁止出站到 LLM，进日志受审计约束。
    """

    subject: str
    tenant_id: str
    role: Role
    scope_claims: tuple[str, ...]
    shop_ids: tuple[str, ...]
    jti: str
    issued_at: datetime
    expires_at: datetime
    kid: str


def extract_bearer_token(authorization: str | None) -> str:
    """第 1 步：从 `Authorization: Bearer <token>` 提取令牌。

    ⚠️ 失败信息**不含传入值**（禁令 3）：只报"头缺失 / 格式非法"。
    一个把 `Authorization: Bearer eyJ...` 原样拼进异常的写法，会让令牌进日志。
    """
    if not authorization:
        raise AuthError("缺少 Authorization 头", step=1, reason="missing_header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError(
            "Authorization 头格式非法（应为 `Bearer <token>`）", step=1, reason="malformed_header"
        )
    return parts[1].strip()


class TokenVerifier:
    """第 1–5 步的实现。**无状态**（除注入的 JWKS 缓存与撤销名单），可安全共享。"""

    def __init__(
        self,
        *,
        jwks: JwksCache,
        issuer: str,
        audience: str,
        revocation: RevocationChecker,
        leeway_s: int = JWKS_LEEWAY_S,
    ) -> None:
        self._jwks = jwks
        self._issuer = issuer
        self._audience = audience
        self._revocation = revocation
        self._leeway_s = leeway_s

    async def verify(self, authorization: str | None) -> VerifiedToken:
        token = extract_bearer_token(authorization)  # 步 1

        claims = await self._decode(token)           # 步 2 + 3 + 5

        jti = str(claims["jti"])
        if await self._revocation.is_revoked(jti):   # 步 4
            raise TokenRevokedError()

        return self._to_verified(claims)

    # ------------------------------------------------------------------
    # 步 2 / 3 / 5
    # ------------------------------------------------------------------
    async def _decode(self, token: str) -> Mapping[str, Any]:
        # --- 步 2：先取未校验的 header 拿 `kid` ---
        # ⚠️ 这里**只**读 header，绝不读未校验的 payload ——
        #    `get_unverified_claims` 会让攻击者用伪造的 payload 影响后续判断。
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise AuthError("令牌格式非法", step=2, reason="malformed_token") from exc

        kid = str(header.get("kid") or "default")
        key = await self._jwks.get(kid)

        # --- 步 3 + 5：签名 / iss / aud / exp(+leeway) / 必需 claims ---
        try:
            return jwt.decode(
                token,
                key=key,
                algorithms=list(_ALGORITHMS),
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway_s,
                options={
                    "require": list(REQUIRED_CLAIMS),
                    # 显式写出，避免依赖 PyJWT 的默认值随版本变化
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_signature": True,
                },
            )
        except jwt.MissingRequiredClaimError as exc:
            # 归**第 5 步**：签名是对的，只是 claims 不齐 —— 两者归因完全不同
            raise AuthError("令牌缺少必需 claim", step=5, reason="missing_claim") from exc
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("令牌已过期", step=3, reason="expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthError("令牌签发者不匹配", step=3, reason="bad_issuer") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthError("令牌受众不匹配", step=3, reason="bad_audience") from exc
        except jwt.InvalidSignatureError as exc:
            raise AuthError("令牌签名校验失败", step=3, reason="bad_signature") from exc
        except jwt.InvalidTokenError as exc:
            # ⚠️ 兜底分支：**不回显 `exc` 的消息**（PyJWT 的某些消息会带上 payload 片段）
            raise AuthError("令牌校验失败", step=3, reason="invalid_token") from exc

    # ------------------------------------------------------------------
    def _to_verified(self, claims: Mapping[str, Any]) -> VerifiedToken:
        """把 claims 转成**强类型**的 `VerifiedToken`（第 5 步的后半）。"""
        raw_role = claims["role"]
        try:
            role = Role(raw_role)
        except ValueError as exc:
            # 非法 role 不能"跳过"也不能"当最低权限"：
            # 前者是放行未知身份，后者是**静默降权** —— 两者都会让权限判定失去意义。
            raise AuthError("令牌中的 role 不在系统角色集内", step=5, reason="unknown_role") from exc

        return VerifiedToken(
            subject=str(claims["sub"]),
            tenant_id=str(claims["tenant_id"]),
            role=role,
            scope_claims=_as_str_tuple(claims.get("scope")),
            shop_ids=_as_str_tuple(claims.get("shop_ids")),
            jti=str(claims["jti"]),
            issued_at=datetime.fromtimestamp(int(claims["iat"]), tz=UTC),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
            kid=str(claims.get("kid") or "default"),
        )


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """`scope` / `shop_ids` 的归一化。

    ⚠️ 必须同时接受**字符串**与**列表**两种形态：RFC 8693 / OAuth2 的 `scope`
    是**空格分隔的字符串**，而不少 IdP（含部分 OIDC 实现）直接给 JSON 数组。
    只支持一种会让"换个 IdP 就全 401"，而原因藏在 claim 的序列化方式里，极难定位。
    ⚠️ 非法类型（数字 / 嵌套结构）→ **返回空元组**而不是抛错：
    它们不是"越权"而是"格式噪声"，且 `shop_ids` 为空语义是"不限制"（07 §13.2）。
    ⚠️ 但**空 `shop_ids` 是危险语义**，故此处不做任何"默认收紧"——
    真正的边界在 `guard` 的 scope 计算（W2C），不在认证层。
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part for part in value.split() if part)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if isinstance(item, str) and item)
    return ()
