"""注册/登录 DTO 骨架（Phase B B1；端点由 B3 接）。

层号：L5｜归属窗口：Phase B B1。

⚠️ `tenant_id` **不是**注册/登录的请求字段：租户必须来自服务端可信上下文
（部署配置或已签发 token），接受客户端传入 = 自助跨租户建号（N-10 同类漏洞）。
B3 落端点时若确需演示多租户，只从服务端配置取，不扩本 DTO。

⚠️ 密码只做**长度**约束，不做复杂度规则：复杂度提示属前端文案；后端只保证
"非空且不会让 scrypt 成本失控"（上限 128）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["LoginRequest", "RegisterData", "RegisterRequest", "TokenData"]

_USERNAME_PATTERN = r"^[A-Za-z0-9_.@-]+$"


class RegisterRequest(BaseModel):
    """`POST /auth/register`（B3）。用户名按 `lower(username)` 唯一。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=_USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    """`POST /auth/login`（B3）。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=_USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class RegisterData(BaseModel):
    """`POST /auth/register` 的 `data`（不返回密码散列等任何凭据材料）。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    username: str
    created_at: str


class TokenData(BaseModel):
    """`POST /auth/login` 的 `data`。`expires_in` 与 `Settings.JWT_TTL_SECONDS` 同源。"""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)
