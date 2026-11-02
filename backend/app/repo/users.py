"""`app.auth_user` 访问层（Phase B B3）—— 注册写、登录读。

层号：L0｜归属窗口：Phase B B3。

| 层 | 文件 | 职责 |
|---|---|---|
| 语义 | `app/api/routers/auth.py` | 注册开关、统一错误文案、限流、令牌签发 |
| 事实 | **本文件** | 列名、SQL 文本、用户名大小写归一 |

⚠️ 列名只在这里出现一次（`USER_COLUMNS`）；端点不拼 SQL。
⚠️ 不 catch 异常：唯一约束冲突向上抛，由端点决定映射成什么码。
⚠️ 没有 `update` / `delete`：账号禁用属运维动作（见迁移 0008 的权限说明）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = ["USER_COLUMNS", "USER_TABLE", "UserRow", "UserStore"]

USER_TABLE: Final[str] = "app.auth_user"
USER_COLUMNS: Final[tuple[str, ...]] = (
    "user_id",
    "tenant_id",
    "username",
    "password_hash",
    "role",
    "shop_ids",
    "disabled",
)


@dataclass(frozen=True, slots=True)
class UserRow:
    user_id: str
    tenant_id: str
    username: str
    password_hash: str
    role: str
    shop_ids: tuple[str, ...]
    disabled: bool


class UserStore:
    """每语句借还一次连接（与 `FeedbackStore` / `AuditStore` 同一纪律）。"""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def find_by_username(self, username: str) -> UserRow | None:
        """按 `lower(username)` 唯一命中（迁移 0008 的唯一索引）。"""
        sql = text(
            f"SELECT {', '.join(USER_COLUMNS)} FROM {USER_TABLE} "
            "WHERE lower(username) = lower(:username)"
        )
        async with self._engine.connect() as conn:
            row = (await conn.execute(sql, {"username": username})).mappings().first()
        if row is None:
            return None
        return UserRow(
            user_id=str(row["user_id"]),
            tenant_id=str(row["tenant_id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            role=str(row["role"]),
            shop_ids=tuple(str(item) for item in (row["shop_ids"] or ())),
            disabled=bool(row["disabled"]),
        )

    async def insert_user(
        self,
        *,
        user_id: str,
        tenant_id: str,
        username: str,
        password_hash: str,
        role: str,
        shop_ids: tuple[str, ...] = (),
    ) -> None:
        sql = text(
            f"INSERT INTO {USER_TABLE} "
            "(user_id, tenant_id, username, password_hash, role, shop_ids) "
            "VALUES (:user_id, :tenant_id, :username, :password_hash, :role, "
            "CAST(:shop_ids AS text[]))"
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                sql,
                {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "username": username,
                    "password_hash": password_hash,
                    "role": role,
                    "shop_ids": list(shop_ids),
                },
            )
