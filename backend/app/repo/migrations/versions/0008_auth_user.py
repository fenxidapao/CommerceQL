"""0008 —— 本地账号表 `app.auth_user`（Phase B B3）

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02

归属窗口：Phase B B3（`计划_合并版 §4 B3`；`docs/08 §4.1` 归属登记随本迁移补记）。

============================================================================
为什么用户名唯一是**全局**而不是按租户
============================================================================

`POST /auth/login` 的请求体只有 `username` + `password`（`dto/auth.py`）——
**没有** `tenant_id`（客户端传租户 = 自助跨租户建号）。因此登录必须先靠
`lower(username)` 定位唯一一行，再取该行的 `tenant_id`。
若唯一约束是 `(tenant_id, lower(username))`，同名用户会在多个租户各存一行，
登录端无法知道该验哪一个 —— 那不是"更安全"，是**无法实现**。

⚠️ 代价必须写明：租户 B 无法注册与租户 A 相同的用户名。
课程演示可接受；生产接真实 IdP 后本表只保留角色映射，用户名唯一性交给 IdP。

============================================================================
列与约束
============================================================================

- `user_id`：服务端生成（`obs.trace.new_id("user")` 的前缀风格），主键；
- `tenant_id`：登录成功后写进令牌的租户事实，**不从请求体取**；
- `password_hash`：`app.auth.passwords.hash_password` 的自描述串（scrypt + 盐 + 参数）；
- `role`：`core.enums.Role` 的 7 值之一（端点侧用枚举白名单转换，不在这里 CHECK，
  避免迁移与枚举两份真相 —— 枚举变更时迁移不该被迫重写）；
- `shop_ids text[]`：与令牌 claim 同形；空数组表示不限制（07 §13.2）；
- `disabled`：禁用账号仍能查到行，但登录返回统一 403（`FORBIDDEN_SCOPE`）。

============================================================================
权限（最小面）
============================================================================

`app_rw` 只有 `SELECT, INSERT`：注册写、登录读。**没有 UPDATE/DELETE** ——
禁用账号由运维/管理角色在演示环境直接改库（`app_rw` 不应能改密码散列）。
`app_ro` 无任何权限（业务只读角色不需要账号表）。
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.auth_user (
            user_id        text        PRIMARY KEY,
            tenant_id      text        NOT NULL,
            username       text        NOT NULL,
            password_hash  text        NOT NULL,
            role           text        NOT NULL DEFAULT 'analyst',
            shop_ids       text[]      NOT NULL DEFAULT '{}',
            disabled       boolean     NOT NULL DEFAULT false,
            created_at     timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_auth_user_username_lower "
        "ON app.auth_user (lower(username))"
    )
    op.execute("REVOKE ALL ON app.auth_user FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON app.auth_user TO app_rw")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON app.auth_user FROM app_rw")
