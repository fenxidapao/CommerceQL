"""Alembic 环境（`app/repo/migrations/`）。

归属窗口：W1B。

⚠️ 三条刻意的选择，与 07 §12.6 对齐：

1. **用同步 engine**：迁移是"一次性的 DDL 批处理"，没有并发需求；异步 engine 只会让
   `upgrade()` 里的每个 `op.execute` 都多一层 event loop 管理，且 alembic 的
   `transaction_per_migration` 在异步下语义更绕。运行时用异步，迁移用同步 —— 这不矛盾。
2. **DSN「只」从 `MIGRATION_DATABASE_URL` 取，没有默认值（取不到即失败）**：迁移要建角色 /
   GRANT，需要属主或超级用户；而运行时的 `DATABASE_URL` 角色是 `app_rw`（最小权限，
   **故意**建不了角色）。两者混用会让「权限最小化」这件事在第一步就被破坏。
   ⚠️ 这里**刻意不留默认 DSN**（2026-09-16 按 W0 转达的密钥扫描要求撤除）—— 理由详见
   `_MIGRATION_URL_ENV` 上方的注释：任何字面量都是把一个**可用口令**写进受版本控制的文件，
   而把它加进 `.gitleaks.toml` 的 allowlist 只是「把可用口令合法化」。
3. **不做 `target_metadata` autogenerate 绑定**：本项目的表定义**只有一处** ——
   迁移文件里的 SQL。若再挂一个 SQLAlchemy `MetaData` 作为"模型真相"，
   就会出现"模型说该有这张表、迁移说没有"的两份真相（正是 U-18 的形态）。
   → 表结构以迁移为准；`app/repo/**` 里的代码只用 SQL 文本 + 参数绑定，不定义 declarative model。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#: 迁移专用连接的**唯一**来源。刻意不留默认 DSN（2026-09-16 按 W0 转达的门禁要求撤除）：
#:
#: 1. 任何字面量都是把一个**可用口令**写进受版本控制的文件 —— CI 密钥扫描（DoD④，
#:    gitleaks 规则 `commerceql-dsn-with-password`，见 `.gitleaks.toml`）会命中；
#:    而把它加进该文件的 `allowlist` 只是"把可用口令合法化"，等于把这道门禁关掉。
#: 2. 留默认值的第二重害处更隐蔽：操作者忘了设变量时，迁移会**安静地**连上"某个"库
#:    （很可能不是他以为的那个），而本迁移要 `CREATE ROLE` / `GRANT` —— 不可逆。
#:    → 宁可起不来。这正是 07 §18.4 "fail fast" 的同一形态。
#:
#: 不需要 DSN 的命令（`alembic history` / `alembic heads`）不触发本函数，仍可直接运行。
_MIGRATION_URL_ENV = "MIGRATION_DATABASE_URL"


def _migration_url() -> str:
    """取迁移连接串；取不到就**失败**，不回落任何默认值。"""
    url = os.environ.get(_MIGRATION_URL_ENV) or ""
    if not url:
        raise RuntimeError(
            f"{_MIGRATION_URL_ENV} 未设置 —— 迁移无法确定连接目标，拒绝继续。\n"
            "\n"
            "  为什么不给兜底值：迁移 0001 要建角色 / 授权，必须由**属主或超级用户**连接；\n"
            "  而运行时的 DATABASE_URL 角色是 app_rw（最小权限，**故意**没有 CREATEROLE），\n"
            "  拿它兜底会在第一步就把「权限最小化」破坏掉。\n"
            "  取值形态与 DATABASE_URL 相同，只把用户名与口令换成属主（超级用户）那一组；\n"
            "  写进 `deploy/.env`（已 gitignore），并在执行 alembic 前载入当前 shell。\n"
            "  ⚠️ 不要为提高便利把它写回本文件 / alembic.ini / 任何受版本控制的示例：\n"
            "     CI 的密钥扫描（DoD④）会拒绝，而放进 allowlist 等于把门禁关掉。\n"
        )
    return url


def run_migrations_offline() -> None:
    """`alembic upgrade --sql`（产出 SQL 而不执行）。"""
    context.configure(
        url=_migration_url(),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """真正执行迁移。"""
    connectable = create_engine(_migration_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
