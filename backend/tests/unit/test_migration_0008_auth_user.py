"""B3：迁移 0008 与 `UserStore` 的列集对账（静态、零 DB）。"""

from __future__ import annotations

from pathlib import Path

from app.repo.users import USER_COLUMNS, USER_TABLE

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "repo"
    / "migrations"
    / "versions"
    / "0008_auth_user.py"
)


def test_migration_chain_and_table_name() -> None:
    text = _MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0008"' in text
    assert 'down_revision = "0007"' in text
    assert f"CREATE TABLE IF NOT EXISTS {USER_TABLE}" in text


def test_repo_columns_match_migration_columns() -> None:
    text = _MIGRATION.read_text(encoding="utf-8")
    for column in USER_COLUMNS:
        assert f'            "{column}"' in text or f"            {column} " in text, column


def test_username_unique_is_global() -> None:
    """登录请求没有 tenant_id ⇒ 唯一约束必须只按 `lower(username)`（全库唯一）。"""
    text = _MIGRATION.read_text(encoding="utf-8")
    assert "ux_auth_user_username_lower" in text
    assert "ON app.auth_user (lower(username))" in text


def test_grants_are_minimal() -> None:
    text = _MIGRATION.read_text(encoding="utf-8")
    assert "GRANT SELECT, INSERT ON app.auth_user TO app_rw" in text
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON app.auth_user FROM app_rw" in text
    assert "TO app_ro" not in text
