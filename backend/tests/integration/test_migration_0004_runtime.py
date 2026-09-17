"""迁移 0004 的**真库**集成测试 —— cost_ledger / query_plan 运行时行为证明。

只测**必须真库才能证明**的部分（单测见 `test_migration_0004_runtime_contract.py`
与 `test_cost_ledger_sink.py`）：
1. `alembic upgrade head` 真实执行（0001→…→0004 全链），两表存在；
2. 权限面：app_ro 零 GRANT（表不在业务查询路径上，N-02）；app_rw **恰好**
   INSERT/SELECT —— UPDATE 被权限层拒绝是"账本行不可改"的行为级证据；
3. CHECK 约束真实拒收非法 `binding_state` / `binding_layer`（取值集 =
   `app/core/enums.py` 冻结快照，单测锁定，这里验证 DB 侧真的 enforce）；
4. `DbCostLedgerSink` 往返：record → 租户/全局日累计聚合，**Asia/Shanghai 日界**、
   Decimal 精度无损、`entry_id` 主键撞重时**如实抛出**（fail-loud 语义）。

跳过策略（同 test_migration_0003_views）：PG 不可达 → skip（写明缺失前置）；
迁移执行失败 → 让它红（那是缺陷不是前置缺失）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.repo.cost_ledger import DbCostLedgerSink

pytestmark = pytest.mark.integration

_BACKEND = Path(__file__).resolve().parents[2]

#: 项目约定 DSN 形态 = `postgresql+psycopg://`；属主 DSN **运行时拼接**（DoD④）。
_SCHEME = "postgresql+psycopg" + "://"
_SUPER = os.environ.get(
    "COMMERCEQL_TEST_SUPER_DSN",
    _SCHEME + "postgres" + ":" + "postgres" + "@localhost:5432/ecom",
)
_RW = os.environ.get(
    "COMMERCEQL_TEST_RW_DSN",
    "postgresql+psycopg://app_rw:app_rw_pwd@localhost:5432/ecom",
)
_RO = os.environ.get(
    "COMMERCEQL_TEST_RO_DSN",
    "postgresql+psycopg://app_ro:app_ro_pwd@localhost:5432/ecom",
)


def _sqla(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def _libpq(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


_SUPER_LIBPQ = _libpq(_SUPER)
_RW_LIBPQ = _libpq(_RW)
_RO_LIBPQ = _libpq(_RO)


def _pg_available() -> bool:
    try:
        psycopg.connect(_RW_LIBPQ, connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def upgraded() -> Any:
    """真实执行 `alembic upgrade head`（幂等：head 已应用则 no-op）。"""
    if not _pg_available():
        pytest.skip("PG 不可达（compose 栈未起）→ 不计为通过")
    env = {
        **os.environ,
        "MIGRATION_DATABASE_URL": _sqla(_SUPER),
        "DATABASE_URL": _sqla(_RW),
        "ANALYTICS_DB_URL": _sqla(_RW),
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head 失败:\n{result.stdout}\n{result.stderr}"
    )
    return _SUPER


@pytest.fixture(scope="module")
def rw(upgraded: Any) -> Any:
    conn = psycopg.connect(_RW_LIBPQ, connect_timeout=3)
    conn.autocommit = True
    # ⚠️ autocommit 是刻意的：CHECK/权限拒绝用例会把事务打 Abort，
    # 模块级连接若留在事务里，aborted 状态会污染后续所有用例（InFailedSqlTransaction）。
    yield conn
    conn.close()


@pytest.fixture()
def clean(upgraded: Any) -> Any:
    """每条 sink/CHECK 用例前后清空两表（用**属主**连接 —— app_rw 无 DELETE，
    清理本来就该走属主身份，见 0004 文件头「刻意不做 #1」）。"""
    owner = psycopg.connect(_SUPER_LIBPQ, connect_timeout=3)
    owner.autocommit = True
    owner.execute("TRUNCATE app.cost_ledger, app.query_plan")
    yield owner
    owner.execute("TRUNCATE app.cost_ledger, app.query_plan")
    owner.close()


# ============================================================================
# 1. 对象存在性 + 形状
# ============================================================================

def test_both_tables_exist_after_full_chain(rw: Any) -> None:
    rows = rw.execute(
        """
        SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = ANY(%s)
        """,
        (["cost_ledger", "query_plan"],),
    ).fetchall()
    found = {name: (kind, owner) for name, kind, owner in rows}
    for table in ("cost_ledger", "query_plan"):
        assert found.get(table, (None, None))[0] == "r", f"app.{table} 不存在"
        owner = found[table][1]
        assert owner not in ("app_rw", "app_ro"), (
            f"app.{table} 属主是 {owner} —— 属主必须是迁移身份（保留期清理走属主，"
            f"app_rw 只拿 INSERT/SELECT，见 0004 权限节）"
        )


def test_cost_ledger_indexes_exist(rw: Any) -> None:
    """§12.3 的两条聚合查询路径各配一个索引（缺了 = 聚合全表扫，熔断判定被拖慢）。"""
    names = {
        r[0]
        for r in rw.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='app' AND tablename='cost_ledger'"
        ).fetchall()
    }
    assert "ix_cost_ledger_tenant_time" in names
    assert "ix_cost_ledger_time" in names


# ============================================================================
# 2. 权限面（行为级 —— has_table_privilege 只查目录，行为才算数）
# ============================================================================

def test_app_ro_has_zero_privileges_on_both_tables(rw: Any) -> None:
    for table in ("cost_ledger", "query_plan"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not rw.execute(
                "SELECT has_table_privilege('app_ro', %s, %s)", (f"app.{table}", priv)
            ).fetchone()[0], f"app_ro 意外持有 app.{table} 的 {priv}"


def test_app_rw_can_insert_but_not_update(rw: Any, clean: Any) -> None:
    """app_rw：INSERT/SELECT 通；UPDATE 被权限层拒 —— 「账本行不可改」的行为级证据。"""
    rw.execute(
        "INSERT INTO app.cost_ledger VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        ("e-priv", "t-1", "t_1001", "u_1", "qwen2.5:7b", 10, 5, 0,
         Decimal("0.000001"), False, datetime.now(UTC)),
    )
    assert rw.execute(
        "SELECT cost_cny FROM app.cost_ledger WHERE entry_id = 'e-priv'"
    ).fetchone()[0] == Decimal("0.000001")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rw.execute("UPDATE app.cost_ledger SET cost_cny = 0 WHERE entry_id = 'e-priv'")


# ============================================================================
# 3. CHECK 约束真实 enforce（取值集 = enums 冻结快照）
# ============================================================================

def test_check_rejects_invalid_binding_state(rw: Any, clean: Any) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        rw.execute(
            "INSERT INTO app.query_plan (task_id, plan_json, bundle_version, binding_state)"
            " VALUES (%s, %s, %s, %s)",
            ("t-bad", "{}", "test", "not_a_state"),
        )


def test_check_rejects_invalid_binding_layer(rw: Any, clean: Any) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        rw.execute(
            "INSERT INTO app.query_plan (task_id, plan_json, bundle_version, binding_state,"
            " binding_layer) VALUES (%s, %s, %s, %s, %s)",
            ("t-bad", "{}", "test", "resolved_unique", "L9"),
        )


def test_query_plan_accepts_null_layer_and_summary(rw: Any, clean: Any) -> None:
    """可空性裁定：binding_layer / plan_summary / confidence 允许 NULL（0004 docstring）。"""
    rw.execute(
        "INSERT INTO app.query_plan (task_id, plan_json, bundle_version, binding_state)"
        " VALUES (%s, %s, %s, %s)",
        ("t-null", '{"schema_version": 1}', "test", "unresolved"),
    )
    row = rw.execute(
        "SELECT plan_summary, binding_layer, confidence FROM app.query_plan WHERE task_id='t-null'"
    ).fetchone()
    assert row == (None, None, None)


# ============================================================================
# 4. DbCostLedgerSink 往返（预算熔断的数据面）
# ============================================================================

def _entry(entry_id: str, tenant: str, cost: Decimal, created_at: datetime) -> Any:
    from app.llm.budget import CostEntry

    return CostEntry(
        entry_id=entry_id,
        task_id="task-1",
        tenant_id=tenant,
        user_id="u_1",
        model="qwen2.5:7b",
        input_tokens=100,
        output_tokens=50,
        cache_hit_tokens=0,
        cost_cny=cost,
        is_peak=False,
        created_at=created_at,
    )


def test_sink_roundtrip_aggregates_tenant_and_global(clean: Any) -> None:
    sink = DbCostLedgerSink(_RW)
    try:
        day = date(2026, 9, 17)
        base = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
        sink.record(_entry("e-1", "t_1001", Decimal("0.001000"), base))
        sink.record(_entry("e-2", "t_1001", Decimal("0.002000"), base + timedelta(minutes=1)))
        sink.record(_entry("e-3", "t_2002", Decimal("0.004000"), base + timedelta(minutes=2)))
        # 租户级：只聚合本租户
        assert sink.tenant_spent_cny("t_1001", day) == Decimal("0.003000")
        assert sink.tenant_spent_cny("t_2002", day) == Decimal("0.004000")
        # 全局：跨租户求和
        assert sink.global_spent_cny(day) == Decimal("0.007000")
        # 无数据日 = 0（COALESCE），且是 Decimal（类型漂移会在熔断比较处炸）
        assert sink.global_spent_cny(date(2026, 1, 1)) == Decimal("0")
    finally:
        sink.close()


def test_sink_day_boundary_follows_billing_tz(clean: Any) -> None:
    """日界 = Asia/Shanghai 自然日（PRD §12.3）：UTC 16:00 后已计入**次日**。

    这个用例同时钉住 repo 侧默认时区与 `llm/budget.py::BILLING_TZ` 的同值性 ——
    若有人只改一边，这里的累计数立刻对不上。
    """
    sink = DbCostLedgerSink(_RW)
    try:
        # 2026-09-17 15:30 UTC = 2026-09-17 23:30 +08 ；16:30 UTC = 2026-09-18 00:30 +08
        sink.record(_entry("d-1", "t_1001", Decimal("0.100000"),
                           datetime(2026, 9, 17, 15, 30, tzinfo=UTC)))
        sink.record(_entry("d-2", "t_1001", Decimal("0.200000"),
                           datetime(2026, 9, 17, 16, 30, tzinfo=UTC)))
        assert sink.tenant_spent_cny("t_1001", date(2026, 9, 17)) == Decimal("0.100000")
        assert sink.tenant_spent_cny("t_1001", date(2026, 9, 18)) == Decimal("0.200000")
    finally:
        sink.close()


def test_sink_duplicate_entry_id_fails_loud(clean: Any) -> None:
    """entry_id 撞主键 → 如实抛 UniqueViolation（fail-loud：静默丢账 = 熔断失真）。"""
    sink = DbCostLedgerSink(_RW)
    try:
        entry = _entry("dup-1", "t_1001", Decimal("0.001000"),
                       datetime(2026, 9, 17, 8, 0, tzinfo=UTC))
        sink.record(entry)
        with pytest.raises(psycopg.errors.UniqueViolation):
            sink.record(entry)
    finally:
        sink.close()


def test_sink_unreachable_dsn_raises_operational_error_quickly() -> None:
    """依赖不可达时**如实抛**且不挂死（connect_timeout=2 兜底，U-53 教训的直接复验）。

    用一个路由黑洞地址（RFC 5737 文档段 + 非监听端口）：TCP SYN 无响应，
    若 connect_timeout 失效，本测试会挂到 OS 级超时（~20s+）而非 2s 封顶。
    """
    import time

    sink = DbCostLedgerSink(
        "postgresql+psycopg://app_rw:app_rw_pwd@192.0.2.1:5432/ecom"
    )
    t0 = time.monotonic()
    with pytest.raises(psycopg.OperationalError):
        sink.global_spent_cny(date(2026, 9, 17))
    elapsed = time.monotonic() - t0
    sink.close()
    assert elapsed < 15, f"连接挂了 {elapsed:.1f}s —— connect_timeout 没生效？"
