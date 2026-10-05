"""§A.9.5 审计读路径的**库侧**证据（一次性库；🚫 禁共享 `ecom`）。

判据落点（`docs/02` §A.9.5 判据块④ 原文）：**"跨租户不可读 = `tests/integration/**`（一次性库，禁指共享 `ecom`）"**。
形状与错误码在 `tests/contract/test_admin_audit_contract.py`；本文件只回答**数据库愿不愿意**这三件事：

1. **迁移 0006 真的落了**：`app_ro` 现在能 `SELECT` 审计两张表 —— 而且**仍然不能写**
   （负向对照：先证明 SELECT 成功，再证明 INSERT 被拒；只测"被拒"会在表不存在时也以另一个理由被拒 = 假绿）。
2. **`WHERE tenant_id = …` 这一道在真库上确实切得开**：两个租户各有一行，
   本租户视角只回自己那一行（🔴 只看"返回 0 行"或"返回一堆"都判不出这件事）。
3. **身份 GUC 注入不是装饰**：在测试里现造一对策略（`ENABLE` ＋ `FOR SELECT` 租户谓词
   ＋ `FOR INSERT WITH CHECK (true)`，缺第三条会掐死 fail-closed 的审计写，见 `app/obs/audit.py` ⑤ 段），
   然后**故意丢掉 `WHERE`** 裸读 ——
   只剩注入的那条谓词也必须切不开别人的租户，且**不注入 = 0 行**（fail-closed）。
   ⚠️ 这一段测的是"**策略在位时会怎样**"，**不是**"策略现在在位" ——
   盘上现况由 `test_rls_state_reports_the_actual_catalog` 报（`relrowsecurity` 与 `pg_policies` 计数）。

⚠️ **`is_local = true` 的语义在这里是承重墙**：autocommit 下每条语句自己就是一个事务 ⇒
`set_config(…, true)` 在下一条语句就已经失效。所有"注入后读"的用例因此必须**显式开事务**
（`_connect_tx`），而生产路径靠 `engine.begin()` 提供同一个事务。用 autocommit 连接测注入
会读到 0 行，症状与"注入没生效"完全一样 —— 那是本文件最容易误判成缺陷的一处。

夹具纪律：只连 `COMMERCEQL_TEST_*_DSN` 指的**一次性库**（缺 env = 当场 fail，禁 skip、禁字面默认 DSN，
见 `_env_dsn.py` 的 U-114 防线①）；跑完删掉自己种下的行与策略，**不动**别人的对象。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.contracts import IdentityContext
from app.core.enums import Outcome, Role
from app.repo.audit_read import AuditFilters, AuditPage, AuditReadDAO
from app.repo.pools import analytics_connect_args
from tests.integration._env_dsn import env_dsn

pytestmark = pytest.mark.integration

_BACKEND = Path(__file__).resolve().parents[2]

_SUPER = env_dsn("COMMERCEQL_TEST_SUPER_DSN")
_RW = env_dsn("COMMERCEQL_TEST_RW_DSN")
_RO = env_dsn("COMMERCEQL_TEST_RO_DSN")

#: 本轮种下的行全部带这个前缀 ⇒ 清理只删自己的东西，且"残渣 = 0"可复核。
_MARK = f"t37a2_{uuid.uuid4().hex[:8]}"
_TENANT_A = "T_A_T37"
_TENANT_B = "T_B_T37"
#: 第三家租户**只给负向对照用** ⇒ 不让"某处多插了一行"去改 T_A/T_B 的期望集合（用例之间零副作用）。
_TENANT_C = "T_C_T37"

_POLICY_SELECT = "t37_a2_audit_ro_tenant"
_POLICY_INSERT = "t37_a2_audit_rw_insert"

#: 本文件写进审计表的总行数：3 条种子 ＋ `_MARK_w` ＋ `_MARK_p` ＋ `_MARK_n`（负向对照那两条）。
_OWN_ROWS = 6


def _sqlalchemy(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, connect_timeout=5, autocommit=True)


def _connect_tx(dsn: str) -> psycopg.Connection:
    """**非 autocommit** 连接：`set_config(..., true)` 只在当前事务里有效，必须显式开事务。"""
    return psycopg.connect(dsn, connect_timeout=5, autocommit=False)


def _identity(tenant: str, role: Role = Role.PLATFORM_ADMIN) -> IdentityContext:
    return IdentityContext(
        trace_id=f"tr_{_MARK}",
        task_id=f"tk_{_MARK}",
        session_id="admin_audit",
        tenant_id=tenant,
        user_id="u_t37",
        role=role,
    )


@pytest.fixture(scope="module")
def db() -> Iterator[psycopg.Connection]:
    """连上一次性库；连不上 = **fail**（不是 skip —— skip 会让这整面变成"没测"却被读成"测过了"）。"""
    try:
        conn = _connect(_SUPER)
    except Exception as exc:  # 连接失败的原因很多，一律转成一条具名 failure
        pytest.fail(f"集成环境不可用（{type(exc).__name__}）：一次性库连不上，本文件一条都没测")
    else:
        yield conn
        conn.close()


@pytest.fixture(scope="module")
def upgraded(db: psycopg.Connection) -> str:
    """真跑 `alembic upgrade head`（含本轮新增的 0006）。"""
    env = dict(os.environ)
    env["MIGRATION_DATABASE_URL"] = _sqlalchemy(_SUPER)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"alembic upgrade head 失败：\n{result.stdout}\n{result.stderr}"
    heads = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert "0006" in heads.stdout, f"迁移头不是 0006（读路径的授权没落）：{heads.stdout}"
    return heads.stdout.strip()


def _insert_audit(conn: psycopg.Connection, task_id: str, tenant: str, user: str, outcome: str, pii: list[str]) -> int:
    """写一条审计（返回 rowcount）。

    ⚠️ 调用方**不要**用"回读条数"来证明写成功：策略在位时，非属主角色的 SELECT
    会被默认拒绝挡成 0 行 —— 那看着像"没写进去"，其实写了。回读要用**属主/超管**连接。
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.audit_log
                (task_id, tenant_id, user_id, role, raw_question, final_executed_sql,
                 row_count_returned, pii_columns_hit, outcome, latency_ms, refusal_reason)
            VALUES (%s, %s, %s, 'analyst', '上个月各渠道 GMV 是多少', 'SELECT 1', 3, %s, %s,
                    '{"total": 1200}'::jsonb, NULL)
            """,
            (task_id, tenant, user, pii, outcome),
        )
        return cur.rowcount


@pytest.fixture(scope="module")
def seeded(upgraded: str) -> Iterator[int]:
    """两个租户各若干行审计（含一行 PII 命中、一行 refuse）⇒ 每个过滤条件都能被单独证伪。"""
    rw = _connect(_RW)
    _insert_audit(rw, f"{_MARK}_a", _TENANT_A, "u_alpha", "success", [])
    _insert_audit(rw, f"{_MARK}_c", _TENANT_A, "u_gamma", "clarify", [])
    _insert_audit(rw, f"{_MARK}_w", _TENANT_A, "u_w", "degraded", [])
    _insert_audit(rw, f"{_MARK}_b", _TENANT_B, "u_beta", "refuse", ["phone"])
    with rw.cursor() as cur:
        cur.execute(
            "INSERT INTO app.audit_log_supplement (task_id, cost_cny) VALUES (%s, 0.0123)",
            (f"{_MARK}_a",),
        )
        rows = cur.execute("SELECT count(*) FROM app.audit_log WHERE task_id LIKE %s", (f"{_MARK}%",)).fetchone()[0]
    assert rows == 4, f"种子没建成（读到 {rows} 行）—— 后面每条断言都会变成假绿"
    yield rows
    rw.close()
    # ⚠️ `ALTER TABLE … DISABLE TRIGGER` 需要**属主**：一次性库里表由迁移连接（超管）创建 ⇒ 用超管删。
    su = _connect(_SUPER)
    with su.cursor() as cur:
        cur.execute("ALTER TABLE app.audit_log DISABLE TRIGGER trg_audit_log_immutable")
        try:
            cur.execute("DELETE FROM app.audit_log_supplement WHERE task_id LIKE %s", (f"{_MARK}%",))
            cur.execute("DELETE FROM app.audit_log WHERE task_id LIKE %s", (f"{_MARK}%",))
        finally:
            cur.execute("ALTER TABLE app.audit_log ENABLE TRIGGER trg_audit_log_immutable")
    su.close()


def _read(
    identity: IdentityContext,
    filters: AuditFilters,
    tenant_scope: str | None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> AuditPage:
    """建引擎 → 跑协程 →  dispose，**三件同一个循环**（仓库既有 async 用例的同一形状）。

    ⚠️ 不用 `async def test_`：`conftest` 的会话级 fixture 换的是 **事件循环策略**，
    而 pytest-asyncio 自建循环不吃这个策略 ⇒ Windows 上必 `ProactorEventLoop` InterfaceError
    （`test_query_plan_store_pg.py` 首版就栽在这里，理由见其文件头）。
    """

    async def _go() -> AuditPage:
        engine = create_async_engine(_sqlalchemy(_RO), connect_args=analytics_connect_args())
        try:
            return await AuditReadDAO(engine).fetch_page(
                identity, filters=filters, tenant_scope=tenant_scope, limit=limit, offset=offset
            )
        finally:
            await engine.dispose()

    return asyncio.run(_go())


def _drop_policy(db: psycopg.Connection) -> None:
    with db.cursor() as cur:
        cur.execute(f"DROP POLICY IF EXISTS {_POLICY_SELECT} ON app.audit_log")
        cur.execute(f"DROP POLICY IF EXISTS {_POLICY_INSERT} ON app.audit_log")
        cur.execute("ALTER TABLE app.audit_log NO FORCE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE app.audit_log DISABLE ROW LEVEL SECURITY")


def _make_policy(db: psycopg.Connection, *, with_insert_policy: bool = True) -> None:
    _drop_policy(db)
    with db.cursor() as cur:
        cur.execute("ALTER TABLE app.audit_log ENABLE ROW LEVEL SECURITY")
        # ① 只放读、按 GUC 的租户谓词（PG 默认拒绝 ⇒ 没注入就什么都看不到）
        cur.execute(
            f"""
            CREATE POLICY {_POLICY_SELECT} ON app.audit_log
                FOR SELECT TO app_ro
                USING (tenant_id = current_setting('app.tenant_id', true))
            """
        )
        if with_insert_policy:
            # ② 写侧放行策略：缺了它，非属主的 INSERT 会被默认拒绝掐死
            #    （`app/obs/audit.py` ⑤ 段登记的陷阱；审计写是 fail-closed ⇒ 全站一起红）
            cur.execute(
                f"""
                CREATE POLICY {_POLICY_INSERT} ON app.audit_log
                    FOR INSERT TO app_rw, postgres
                    WITH CHECK (true)
                """
            )


@pytest.fixture
def clean_policy(db: psycopg.Connection) -> Iterator[None]:
    """每条用例前后都清掉本文件可能造出的策略 ⇒ 策略面**不残留**在一次性库里。"""
    _drop_policy(db)
    yield
    _drop_policy(db)


# ---------------------------------------------------------------------------
# 1 迁移 0006 的落库事实
# ---------------------------------------------------------------------------
def test_app_ro_can_select_audit_but_cannot_write(db: psycopg.Connection, seeded: int) -> None:
    ro = _connect(_RO)
    n = ro.execute("SELECT count(*) FROM app.audit_log").fetchone()[0]
    assert n >= seeded, f"app_ro SELECT 到 {n} 行 < 种子 {seeded} 行 ⇒ 0006 的 GRANT 没生效"
    # 🔴 本机实测（本轮）：`app_ro` 的写**先**撞角色级 `default_transaction_read_only`
    # （`ReadOnlySqlTransaction`），表级权限那一层（`InsufficientPrivilege`）根本没轮到。
    # 只断言后者会红，而那条红会被读成"0006 多授了写权限"—— 所以两种具名拒绝都算拒绝，
    # 但**必须是这两种之一**（"任何错误都算拒"就等于没测）。
    refused = (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)
    with pytest.raises(refused):
        _insert_audit(ro, f"{_MARK}_x", _TENANT_A, "u", "success", [])
    with pytest.raises(refused):
        ro.execute("UPDATE app.audit_log SET outcome = 'failed'")
    with pytest.raises(refused):
        ro.execute("DELETE FROM app.audit_log")
    # 负向对照的另一半：同一张表对 rw 是可写的（否则"被拒"只是表根本不让动）
    rw = _connect(_RW)
    assert _insert_audit(rw, f"{_MARK}_r", _TENANT_C, "u_r", "success", []) == 1
    n_after = db.execute("SELECT count(*) FROM app.audit_log WHERE task_id = %s", (f"{_MARK}_r",)).fetchone()[0]
    assert n_after == 1, "rw 写进去的行在超管面读不到 ⇒ 后面的拒绝可能是别的原因"


def test_supplement_is_readable_by_app_ro_for_the_cost_column(db: psycopg.Connection, seeded: int) -> None:
    ro = _connect(_RO)
    row = ro.execute(
        "SELECT cost_cny FROM app.audit_log_supplement WHERE task_id = %s", (f"{_MARK}_a",)
    ).fetchone()
    assert row is not None and float(row[0]) == pytest.approx(0.0123)


# ---------------------------------------------------------------------------
# 2 服务端租户谓词（判据③ 第一道）
# ---------------------------------------------------------------------------
def test_tenant_scope_returns_only_its_own_rows(seeded: int) -> None:
    page = _read(
        _identity(_TENANT_A), filters=AuditFilters(), tenant_scope=_TENANT_A, limit=50, offset=0
    )
    ids = {r["task_id"] for r in page.rows}
    assert ids == {f"{_MARK}_a", f"{_MARK}_c", f"{_MARK}_w"}, f"本租户视角读到别人的行了或漏了自己的：{ids}"
    assert page.total == 3
    # 同一 DAO、换租户 ⇒ 集合必须换掉（只对撞一次无法区分"过滤生效"和"永远返回同一批"）
    other = _read(
        _identity(_TENANT_B), filters=AuditFilters(), tenant_scope=_TENANT_B, limit=50, offset=0
    )
    assert {r["task_id"] for r in other.rows} == {f"{_MARK}_b"}


def test_cross_tenant_view_sees_both_tenants(seeded: int) -> None:
    page = _read(
        _identity("t_admin"), filters=AuditFilters(), tenant_scope=None, limit=50, offset=0
    )
    tenants = {r["tenant_id"] for r in page.rows}
    assert {_TENANT_A, _TENANT_B} <= tenants, f"跨租户视角没看到两家：{tenants}"


def test_outcome_filter_narrows_within_the_same_tenant(seeded: int) -> None:
    all_a = _read(
        _identity(_TENANT_A), filters=AuditFilters(), tenant_scope=_TENANT_A, limit=50, offset=0
    )
    only_clarify = _read(
        _identity(_TENANT_A),
        filters=AuditFilters(outcome=Outcome.CLARIFY),
        tenant_scope=_TENANT_A,
        limit=50,
        offset=0,
    )
    assert {r["task_id"] for r in only_clarify.rows} == {f"{_MARK}_c"}
    assert len(all_a.rows) == 3 and only_clarify.total == 1, "过滤应当改变 total，而 limit 不该（见下条）"


def test_limit_pages_but_total_stays_the_count(seeded: int) -> None:
    page = _read(
        _identity(_TENANT_A), filters=AuditFilters(), tenant_scope=_TENANT_A, limit=1, offset=0
    )
    assert len(page.rows) == 1 and page.total == 3


def test_pii_hit_predicate_is_both_sides(seeded: int) -> None:
    pii = _read(
        _identity(_TENANT_B), filters=AuditFilters(pii_hit=True), tenant_scope=_TENANT_B, limit=50, offset=0
    )
    assert {r["task_id"] for r in pii.rows} == {f"{_MARK}_b"}
    assert pii.rows[0]["pii_columns_hit"] == ["phone"]
    not_pii = _read(
        _identity(_TENANT_B), filters=AuditFilters(pii_hit=False), tenant_scope=_TENANT_B, limit=50, offset=0
    )
    assert not_pii.rows == [], "pii_hit=false 那一支应当读到空（T_B 只有那一条 PII 命中）"


def test_time_window_and_order_are_stable(seeded: int) -> None:
    page = _read(
        _identity(_TENANT_A),
        filters=AuditFilters(since=datetime(2000, 1, 1, tzinfo=UTC), until=datetime(2100, 1, 1, tzinfo=UTC)),
        tenant_scope=_TENANT_A,
        limit=50,
        offset=0,
    )
    stamps = [r["timestamp"] for r in page.rows]
    assert len(stamps) == 3
    assert stamps == sorted(stamps, reverse=True), f"排序不是 timestamp DESC：{stamps}"
    empty = _read(
        _identity(_TENANT_A),
        filters=AuditFilters(since=datetime(2100, 1, 1, tzinfo=UTC)),
        tenant_scope=_TENANT_A,
        limit=50,
        offset=0,
    )
    assert empty.rows == [] and empty.total == 0


def test_cost_is_null_when_supplement_row_is_absent(seeded: int) -> None:
    page = _read(
        _identity(_TENANT_A), filters=AuditFilters(), tenant_scope=_TENANT_A, limit=50, offset=0
    )
    by_id = {r["task_id"]: r for r in page.rows}
    assert float(by_id[f"{_MARK}_a"]["cost_cny"]) == pytest.approx(0.0123)
    assert by_id[f"{_MARK}_c"]["cost_cny"] is None, "段 2 缺失必须读到 NULL，不许被补成 0"


# ---------------------------------------------------------------------------
# 3 身份注入 ＋ RLS（判据②③ 第二道，策略由本文件现造现清）
# ---------------------------------------------------------------------------
def test_rls_state_reports_the_actual_catalog(seeded: int) -> None:
    page = _read(
        _identity(_TENANT_A), filters=AuditFilters(), tenant_scope=None, limit=1, offset=0
    )
    assert page.rls["rls_enabled"] is False, "本文件跑完会清策略 ⇒ 现查应当报 False（这条也证明读数不是硬编码）"
    assert page.rls["policies"] == 0


def test_injected_guc_enforces_isolation_without_the_where(
    db: psycopg.Connection, seeded: int, clean_policy: None
) -> None:
    """丢掉 `WHERE` 裸读，只靠"三键同一条语句注入"＋策略，也必须切不开别家租户。

    ⚠️ 这一条是判据② 的全部意义：注入若是装饰（键名写错、`is_local` 给成 `false`、只注入一键），
    这里就会读到两家租户 —— 而第 2 节那几条照样全绿。
    """
    _make_policy(db)
    conn = _connect_tx(_RO)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.role', %s, true), "
            "set_config('app.shop_ids', %s, true)",
            (_TENANT_A, "platform_admin", ""),
        )
        tenants = {r[0] for r in cur.execute("SELECT DISTINCT tenant_id FROM app.audit_log").fetchall()}
    conn.rollback()
    conn.close()
    assert tenants == {_TENANT_A}, f"注入生效则只该看到本租户，实得 {tenants}"


def test_policy_binds_to_whichever_tenant_is_injected(
    db: psycopg.Connection, seeded: int, clean_policy: None
) -> None:
    """单变量对照：换一个注入值 ⇒ 读到的集合跟着换。

    不写这一条，上一条的"只读到 T_A"可能有第二种成因 —— **策略根本没生效而表里只有 T_A**
    （种子建歪了也会长这样）。两个注入值各给各自那一族，才叫策略在过滤。
    """
    _make_policy(db)
    conn = _connect_tx(_RO)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.role', %s, true), "
            "set_config('app.shop_ids', %s, true)",
            (_TENANT_B, "platform_admin", ""),
        )
        tenants = {r[0] for r in cur.execute("SELECT DISTINCT tenant_id FROM app.audit_log").fetchall()}
    conn.rollback()
    conn.close()
    assert tenants == {_TENANT_B}, f"换注入没换读数 ⇒ 策略/夹具有一边是假的：{tenants}"


def test_no_injection_reads_zero_rows_under_the_policy(
    db: psycopg.Connection, seeded: int, clean_policy: None
) -> None:
    """fail-closed 方向：策略在位而**没注入身份** ⇒ 0 行（不是"全看得见"）。"""
    _make_policy(db)
    conn = _connect_tx(_RO)
    n = conn.execute("SELECT count(*) FROM app.audit_log").fetchone()[0]
    conn.rollback()
    conn.close()
    assert n == 0, f"未注入身份读到 {n} 行 ⇒ 策略不是 fail-closed"


def test_dao_still_returns_rows_with_the_policy_in_place(
    db: psycopg.Connection, seeded: int, clean_policy: None
) -> None:
    """**双向对照的最后一半**：策略在位时 DAO 走自己的注入通道仍读到本租户的行。

    少了这一半，上一条的"0 行"也可能只是因为策略把一切都挡掉了。
    """
    _make_policy(db)
    page = _read(
        _identity(_TENANT_A), filters=AuditFilters(), tenant_scope=_TENANT_A, limit=50, offset=0
    )
    assert {r["task_id"] for r in page.rows} == {f"{_MARK}_a", f"{_MARK}_c", f"{_MARK}_w"}
    assert page.rls["rls_enabled"] is True and page.rls["policies"] == 2


def test_audit_write_survives_the_policy_pair(
    db: psycopg.Connection, clean_policy: None
) -> None:
    """带写侧放行策略时：INSERT 必须成功（NFR-3.4 的 fail-closed 不能被 RLS 掐死）。

    ⚠️ 回读走超管连接 `db`：策略在位时 `app_rw`（非属主）的 SELECT 会被默认拒绝挡成 0 行，
    拿它当"写成功了没有"的证据会得到一条**假红**。
    """
    _make_policy(db, with_insert_policy=True)
    rw = _connect(_RW)
    wrote = _insert_audit(rw, f"{_MARK}_p", _TENANT_C, "u_p", "success", [])
    rw.close()
    assert wrote == 1, f"带 INSERT 放行策略仍写不进（rowcount={wrote}）"
    n = db.execute("SELECT count(*) FROM app.audit_log WHERE task_id = %s", (f"{_MARK}_p",)).fetchone()[0]
    assert n == 1


def test_missing_insert_policy_is_the_trap_obs_audit_records(
    db: psycopg.Connection, seeded: int, clean_policy: None
) -> None:
    """只有 `FOR SELECT` 的形态（`app/obs/audit.py` ⑤ 段的陷阱①）：非属主的 INSERT 被默认拒绝。

    这条不证明"我们的产品坏了"（盘上没有这条 DDL），它证明
    **为什么本窗不擅自落 RLS 迁移**：形状落错一条 = 每个请求都失败（审计写是 fail-closed）。
    ⚠️ 单向断言：如果哪天执行迁移的角色变成表属主（属主对 RLS 免疫），这一条会**红**，
    红了要回去读 `pg_class.relowner` 而不是放宽断言。
    """
    _make_policy(db, with_insert_policy=False)
    rw = _connect(_RW)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _insert_audit(rw, f"{_MARK}_n", _TENANT_C, "u_n", "success", [])
    rw.close()
    n = db.execute("SELECT count(*) FROM app.audit_log WHERE task_id = %s", (f"{_MARK}_n",)).fetchone()[0]
    assert n == 0, "缺 INSERT 策略却写进去了 ⇒ 执行角色的属主关系变了，请重读 obs/audit.py ⑤ 段"


# ---------------------------------------------------------------------------
# 4 残渣
# ---------------------------------------------------------------------------
def test_nothing_from_this_file_is_left_behind(db: psycopg.Connection) -> None:
    """本文件的行与策略都必须清干净（审计表连属主都删不掉，所以要临时 DISABLE TRIGGER ——
    这件事本身就是 §12.4 的库侧证据）。"""
    with db.cursor() as cur:
        cur.execute("ALTER TABLE app.audit_log DISABLE TRIGGER trg_audit_log_immutable")
        try:
            cur.execute("DELETE FROM app.audit_log_supplement WHERE task_id LIKE %s", (f"{_MARK}%",))
            deleted = cur.execute("DELETE FROM app.audit_log WHERE task_id LIKE %s", (f"{_MARK}%",)).rowcount
        finally:
            cur.execute("ALTER TABLE app.audit_log ENABLE TRIGGER trg_audit_log_immutable")
    assert deleted >= 4, f"至少该删掉 4 条种子，实删 {deleted} ⇒ 种子或某条负向对照没建成"
    left = db.execute("SELECT count(*) FROM app.audit_log WHERE task_id LIKE %s", (f"{_MARK}%",)).fetchone()[0]
    assert left == 0, f"残渣 {left} 行"
    policies = db.execute(
        "SELECT count(*) FROM pg_policies WHERE schemaname = 'app' AND tablename = 'audit_log'"
    ).fetchone()[0]
    assert policies == 0, f"策略残留 {policies} 条 ⇒ 一次性库被本文件改成了另一个形状"
    rls = db.execute(
        "SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'app' AND c.relname = 'audit_log'"
    ).fetchone()[0]
    assert rls is False, "RLS 开关没关回去 ⇒ 下一条集成用例会在没策略的地方读到 0 行"
