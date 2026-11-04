"""B2：迁移 `0009` 与 `AuditExportStore` 的对账（静态、零 DB）。

--------------------------------------------------------------------------
⚠️ 这个文件证明什么、不证明什么
--------------------------------------------------------------------------

| 断言 | 这里（静态） | 需真 PG |
|---|---|---|
| 迁移链 / 表名 / 列集与 DAO 白名单一致 | ✅ | — |
| append-only 三重保险的 ① 权限 / ② 触发器**写在迁移里** | ✅ | — |
| 导出审计 DAO 里没有改删语句（③ 代码层） | ✅ | — |
| 触发器真的拦住改删、`app_rw` 真的没有权限 | — | ⛔ 本表尚无 `tests/integration/` 用例（登记为已知边界） |

--------------------------------------------------------------------------
为什么必须静态扫（而不是"靠 code review"）
--------------------------------------------------------------------------
第三重保险（代码层只暴露 insert）失效时**不会报错**：有人给 DAO 加一个
`delete_export_log()`，导出行照样能删，而**没有任何测试会红**。
`test_audit_writer.py` 已经用同一手法锁住了 `audit_log` 那一侧；
新表若不进同一口径，第三重对它就是空的。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.repo.audit_export_store import (
    EXPORT_FORMAT_CSV,
    EXPORT_IDENTITY_COLUMNS,
    EXPORT_PAYLOAD_COLUMNS,
    EXPORT_REQUIRED_COLUMNS,
    EXPORT_TABLE,
    AuditExportStore,
    ExportSchemaMismatch,
    _build_insert,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _BACKEND_ROOT / "app" / "repo" / "migrations" / "versions" / "0009_audit_export_log.py"
)
_EXPORT_STORE = _BACKEND_ROOT / "app" / "repo" / "audit_export_store.py"

#: 对审计表的改、删语句（第 ③ 层的对象）。
#: ⚠️ 与 `test_audit_writer.py:61` **同一个正则** —— 两处口径必须一致，否则
#: "新表被扫、旧表没被扫"这类差异会变成永久盲区，而盲区不会自我暴露。
_MUTATION = r"\b(UPDATE\s+\w|DELETE\s+FROM\b|TRUNCATE\s+\w)"


# ===========================================================================
# 1. 迁移形态
# ===========================================================================


def test_migration_chain_and_table_name() -> None:
    text = _MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0009"' in text
    assert 'down_revision = "0008"' in text
    assert f"CREATE TABLE IF NOT EXISTS {EXPORT_TABLE}" in text


def test_store_columns_match_migration_columns() -> None:
    """DAO 白名单里每一列都必须在迁移里存在 —— 否则运行时才有 `UndefinedColumn`。"""
    text = _MIGRATION.read_text(encoding="utf-8")
    for column in (*EXPORT_IDENTITY_COLUMNS, *sorted(EXPORT_PAYLOAD_COLUMNS)):
        assert column in text, column


def test_export_rows_cannot_bypass_the_query_audit() -> None:
    """`task_id` 必须是**外键**引用 `app.audit_log(task_id)`，且 `ON DELETE RESTRICT`。

    这不是形式：没有段 1 审计的查询不可能有结果下发（`audit_pre` fail-closed，N-09）
    ⇒ 外键把"没有审计的 task 不可能被导出"变成**机器判据**。
    把外键降成普通列，这条判据就退回"纪律"，而纪律在跨窗口协作里等于不存在。
    """
    text = _MIGRATION.read_text(encoding="utf-8")
    assert "REFERENCES app.audit_log (task_id)" in text
    assert "ON DELETE RESTRICT" in text


def test_append_only_layers_one_and_two_are_present() -> None:
    """① 权限层 + ② 触发器层必须都在迁移里（③ 由下面那条静态扫描守）。"""
    text = _MIGRATION.read_text(encoding="utf-8")
    assert f"GRANT INSERT, SELECT ON {EXPORT_TABLE} TO app_rw" in text
    #: ⚠️ 必须**显式** REVOKE 而不是"不给就够了"：`REVOKE ... FROM PUBLIC` 只收回默认权限，
    #: 某次排障临时授过又忘收回时，只有这一行能把它掰回来 —— 而"忘收回"不会报错。
    assert f"REVOKE UPDATE, DELETE, TRUNCATE ON {EXPORT_TABLE} FROM app_rw" in text
    assert "trg_audit_export_log_immutable" in text
    #: 触发器函数必须**独立**，不能复用 `deny_mutation()`：后者的异常文案写死 `audit_log`，
    #: 复用会让导出表的拒绝信息指向**错的表**（文案是运维唯一的定位线索）。
    assert "app.deny_export_log_mutation()" in text
    assert "EXECUTE FUNCTION app.deny_export_log_mutation()" in text


def test_migration_does_not_touch_the_existing_audit_tables() -> None:
    """新表不牵动既有审计表：迁移里不得出现对 `app.audit_log` 的 ALTER / 改删。"""
    text = _MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE app.audit_log" not in text
    assert "DROP TABLE IF EXISTS app.audit_log" not in text


# ===========================================================================
# 2. 第三重保险：代码层（静态扫描）
# ===========================================================================


def test_dao_file_has_no_mutation_statement() -> None:
    text = _EXPORT_STORE.read_text(encoding="utf-8")
    hits = [m.group(0) for m in re.finditer(_MUTATION, text)]
    assert hits == [], f"导出审计 DAO 出现改删语句：{hits}（第三重保险失效）"


def test_dao_exposes_only_the_insert_surface() -> None:
    """DAO 的公开面只有 `insert_export_log`：多一个 `delete_*` / `update_*` 就是第二个写通道。"""
    public = [name for name in dir(AuditExportStore) if not name.startswith("_")]
    assert public == ["insert_export_log"], public


# ===========================================================================
# 3. payload 契约（不触库）
# ===========================================================================


def test_unknown_column_is_rejected_not_silently_dropped() -> None:
    with pytest.raises(ExportSchemaMismatch, match="未登记的列名"):
        _build_insert({"row_count": 1, "csv_body": "..."})


def test_missing_required_column_is_named() -> None:
    with pytest.raises(ExportSchemaMismatch, match="row_count"):
        _build_insert({"export_format": EXPORT_FORMAT_CSV, "truncated": False})


def test_required_columns_are_a_subset_of_the_payload_whitelist() -> None:
    assert EXPORT_REQUIRED_COLUMNS <= EXPORT_PAYLOAD_COLUMNS


def test_identity_columns_never_reach_the_payload_whitelist() -> None:
    assert not set(EXPORT_IDENTITY_COLUMNS) & EXPORT_PAYLOAD_COLUMNS


# ===========================================================================
# 4. 写入形状（记录型假 engine：只验 SQL，不假装能执行）
# ===========================================================================


class _RecordingConnection:
    def __init__(self, log: list[tuple[str, dict[str, Any]]]) -> None:
        self._log = log

    async def execute(self, stmt: Any, params: Any) -> None:
        self._log.append((str(stmt), dict(params)))


class _Begin:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _RecordingConnection:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _RecordingEngine:
    def __init__(self) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []

    def begin(self) -> _Begin:
        return _Begin(_RecordingConnection(self.log))


class _NeverTouchedEngine:
    """校验必须在触库之前完成；被碰到就直接炸出用例。"""

    def begin(self) -> Iterator[Any]:  # pragma: no cover - 不该被调用
        raise AssertionError("身份列校验必须在触库之前完成")


_IDENTITY = {"task_id": "tk_1", "tenant_id": "t_1", "user_id": "u_1", "role": "operator"}


async def test_insert_sql_shape_and_no_db_generated_columns() -> None:
    """`export_id` / `timestamp` 由数据库生成 ⇒ 应用侧**不得**出现这两个列名。

    多一个可写字段 = 多一个让"导出发生在何时"失真的入口（与 `audit_log` 同款裁定）。
    """
    engine = _RecordingEngine()
    store = AuditExportStore(engine)  # type: ignore[arg-type]
    await store.insert_export_log(
        _IDENTITY,
        {"export_format": EXPORT_FORMAT_CSV, "row_count": 12, "truncated": True},
    )
    assert len(engine.log) == 1
    sql, params = engine.log[0]
    assert sql.startswith(f"INSERT INTO {EXPORT_TABLE} (")
    assert "export_id" not in sql
    assert "timestamp" not in sql
    assert params["row_count"] == 12
    assert params["truncated"] is True
    assert params["tenant_id"] == "t_1"


async def test_payload_cannot_supply_identity_columns() -> None:
    store = AuditExportStore(_NeverTouchedEngine())  # type: ignore[arg-type]
    with pytest.raises(ExportSchemaMismatch, match="身份列"):
        await store.insert_export_log(_IDENTITY, {"task_id": "tk_1", "row_count": 1})


async def test_missing_identity_column_is_named() -> None:
    store = AuditExportStore(_NeverTouchedEngine())  # type: ignore[arg-type]
    with pytest.raises(ExportSchemaMismatch, match="缺少身份列"):
        await store.insert_export_log(
            {"task_id": "tk_1", "tenant_id": "t_1", "user_id": "u_1"},
            {"row_count": 1},
        )
