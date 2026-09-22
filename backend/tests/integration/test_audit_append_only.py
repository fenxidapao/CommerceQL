"""审计 append-only 的**库侧**自证（DoD⑤）+ 三池不串用的库侧证据（DoD④）。

归属窗口：W1B。

⚠️ **为什么这一条必须是集成测试，离线断言替代不了**
`app/obs/audit.py` 的"只暴露 insert()"（第 ③ 层）与 `.importlinter` 的静态检查都**只说明代码想干什么**。
07 §12.4 把第 ④ 层单独列出来，正是因为它问的是**数据库愿不愿意**：
`app_rw` 真的没有 UPDATE 权限吗？触发器真的在吗？—— 这两个问题只有连库能答。

⚠️ **负向对照是刻意的**（`test_app_rw_can_insert`）：
只断言"UPDATE 失败"是不够的 —— 如果表根本不存在，UPDATE 会**以另一个理由**失败
（`UndefinedTable`），而测试照样"绿"。那正是最典型的假绿灯。
所以必须先证明 INSERT 成功，再证明 UPDATE/DELETE 被拒。

⚠️ **测试数据不清理**（有意）：审计表是 append-only，连测试都删不掉它 —— 这不是缺陷，
是 N-09 在工作。清理属运维动作（07 §12.7：归档后 `DROP PARTITION`）。
故本模块用带随机后缀的 `task_id`，避免与后续用例撞 `uq_audit_log_task_id`。

运行方式：有库即跑，无库自动 skip（`pytest -q` 与 CI 均可直接跑）。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from tests.integration._env_dsn import env_dsn

pytestmark = pytest.mark.integration

#: 集成测试的连接串 **只认环境变量**（U-114 防线①，共享守卫 `tests/integration/_env_dsn.py`）：
#: 旧实现给共享库 `ecom` 的字面默认值 —— 漏带 env 就静默打到共享库。缺 env = 当场 fail（禁止 skip）。
_RW = env_dsn("COMMERCEQL_TEST_RW_DSN")
_RO = env_dsn("COMMERCEQL_TEST_RO_DSN")
_SUPER = env_dsn("COMMERCEQL_TEST_SUPER_DSN")


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, connect_timeout=3)


@pytest.fixture(scope="module")
def super_conn() -> Iterator[psycopg.Connection]:
    """超级用户连接。**没有它就 skip 整个模块** —— 不静默假绿。"""
    try:
        conn = _connect(_SUPER)
    except Exception as exc:
        pytest.skip(f"集成环境不可用（{type(exc).__name__}）→ 跳过库侧断言，不计为通过")
    yield conn
    conn.close()


@pytest.fixture
def task_id() -> str:
    return f"t_it_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup_task(super_conn: psycopg.Connection, task_id: str) -> Iterator[None]:
    """清理本用例写入的行。

    ⚠️ 必须临时 `DISABLE TRIGGER` 才能删 —— 这正是 R-DEP-3/§12.4 想要的证据：
    **连属主都删不掉**，所以"应用代码永远删不掉"是结构性的，不是纪律性的。
    """
    yield
    with super_conn.cursor() as cur:
        cur.execute("ALTER TABLE app.audit_log DISABLE TRIGGER trg_audit_log_immutable")
        try:
            cur.execute("DELETE FROM app.audit_log_supplement WHERE task_id LIKE %s", (task_id,))
            cur.execute("DELETE FROM app.audit_log WHERE task_id LIKE %s", (task_id,))
        finally:
            cur.execute("ALTER TABLE app.audit_log ENABLE TRIGGER trg_audit_log_immutable")
    super_conn.commit()


def _insert_audit(conn: psycopg.Connection, task_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.audit_log
                (task_id, tenant_id, user_id, role, raw_question, final_executed_sql,
                 row_count_returned, outcome)
            VALUES (%s, 't_001', 'u_001', 'operator', '上个月各店铺 GMV', 'SELECT 1', 1, 'success')
            """,
            (task_id,),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# DoD⑤ 正身：append-only
# ---------------------------------------------------------------------------

def test_app_rw_can_insert(task_id: str) -> None:
    """★ 负向对照的前提：`app_rw` **必须能** INSERT，否则"UPDATE 失败"毫无意义。

    没有这一条，一个把表名写错、或者迁移没跑的仓库，也会让下面的用例"通过"。
    """
    with _connect(_RW) as conn:
        _insert_audit(conn, task_id)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM app.audit_log WHERE task_id = %s", (task_id,))
            assert cur.fetchone() == (1,)


def test_app_rw_cannot_update_audit_log(task_id: str) -> None:
    """DoD⑤：以 `app_rw` 身份 UPDATE 审计表**必须失败**。"""
    with _connect(_RW) as conn:
        _insert_audit(conn, task_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.cursor() as cur:
            cur.execute(
                "UPDATE app.audit_log SET outcome = 'failed' WHERE task_id = %s", (task_id,)
            )
        conn.rollback()


def test_app_rw_cannot_delete_audit_log(task_id: str) -> None:
    """DoD⑤：以 `app_rw` 身份 DELETE 审计表**必须失败**。"""
    with _connect(_RW) as conn:
        _insert_audit(conn, task_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.cursor() as cur:
            cur.execute("DELETE FROM app.audit_log WHERE task_id = %s", (task_id,))
        conn.rollback()


def test_trigger_blocks_mutation_even_for_owner(
    super_conn: psycopg.Connection, task_id: str
) -> None:
    """★ 第 ② 层（触发器）单独自证 —— 否则它可能只是一个"存在但从不触发"的装饰。

    权限层（第 ① 层）会**先**拦住 `app_rw`，所以用 `app_rw` 测不出触发器在不在。
    这里以**属主**身份改，绕开权限层，直接问触发器。
    """
    with super_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.audit_log (task_id, tenant_id, user_id, role, raw_question, outcome)
            VALUES (%s, 't_001', 'u_001', 'operator', 'probe', 'success')
            """,
            (task_id,),
        )
    super_conn.commit()

    for stmt in (
        "UPDATE app.audit_log SET outcome = 'failed' WHERE task_id = %s",
        "DELETE FROM app.audit_log WHERE task_id = %s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"), super_conn.cursor() as cur:
            cur.execute(stmt, (task_id,))
        super_conn.rollback()


def test_supplement_has_no_update_privilege(task_id: str) -> None:
    """段 2 的表同样只给 INSERT —— 两段都是审计，权限面必须一致。"""
    with _connect(_RW) as conn:
        _insert_audit(conn, task_id)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO app.audit_log_supplement (task_id, cost_cny) VALUES (%s, 0.5)",
                (task_id,),
            )
            cur.execute(
                "SELECT has_table_privilege('app_rw', 'app.audit_log_supplement', 'UPDATE'),"
                "       has_table_privilege('app_rw', 'app.audit_log_supplement', 'DELETE')"
            )
            assert cur.fetchone() == (False, False)
        conn.commit()


def test_privileges_are_exactly_insert_select(super_conn: psycopg.Connection) -> None:
    """权限面**逐项**断言，而不是只查 UPDATE/DELETE。

    只查两个动词会漏掉 `TRUNCATE`（它删全表且**不触发**行级触发器）——
    而 `TRUNCATE` 漏网时，append-only 的三层保证会一起失效却毫无提示。
    """
    with super_conn.cursor() as cur:
        cur.execute(
            """
            SELECT has_table_privilege('app_rw', 'app.audit_log', 'INSERT'),
                   has_table_privilege('app_rw', 'app.audit_log', 'SELECT'),
                   has_table_privilege('app_rw', 'app.audit_log', 'UPDATE'),
                   has_table_privilege('app_rw', 'app.audit_log', 'DELETE'),
                   has_table_privilege('app_rw', 'app.audit_log', 'TRUNCATE')
            """
        )
        assert cur.fetchone() == (True, True, False, False, False)


# ---------------------------------------------------------------------------
# DoD④ 的库侧证据：analytics 只读 + 三池 application_name 各自可辨
# ---------------------------------------------------------------------------

def test_analytics_role_is_read_only_at_transaction_level() -> None:
    """N-02 的物理形态：`app_ro` 连上即为只读事务（ADR-08）。

    ⚠️ 断言的是**运行时实际值**（`SHOW`），不是 `pg_roles.rolconfig` ——
    后者只说明"配置写着什么"，而 `SET`/`ALTER DATABASE` 可以覆盖它。
    """
    with _connect(_RO) as conn, conn.cursor() as cur:
        cur.execute("SHOW default_transaction_read_only")
        assert cur.fetchone() == ("on",)


def test_analytics_role_cannot_write() -> None:
    """★ `app_ro` 的写操作被**两道**独立机制拦下 —— 两道都要验，缺一就是假证据。

    | 道 | 机制 | 观察到 |
    |---|---|---|
    | 1 | 角色级 `default_transaction_read_only=on`（ADR-08） | `ReadOnlySqlTransaction` |
    | 2 | **无任何表级写权限** | `InsufficientPrivilege`（需先显式 `READ WRITE` 才看得到） |

    只验第 1 道是不够的：有人一句 `SET ... READ WRITE` 就能绕过它，
    而第 2 道才是"绕不过去"的那层。反过来只验第 2 道也不行 ——
    那会掩盖"角色级开关根本没生效"这个事实（它同时是启动期断言 `analytics_dsn_is_read_only` 的对象）。
    """
    _insert_as_ro = """
        INSERT INTO app.audit_log (task_id, tenant_id, user_id, role, raw_question, outcome)
        VALUES ('t_ro_probe', 't_001', 'u_001', 'operator', 'x', 'success')
    """

    # 第 1 道：默认只读事务（刻意不 rollback —— 退出 `with` 即关闭连接，事务自动作废；
    #         在 `with` 外调 rollback 会拿到"连接已关闭"，那是个假故障）
    with _connect(_RO) as conn, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute(_insert_as_ro)

    # 第 2 道：显式关掉只读事务开关后，仍然没有权限。
    # ⚠️ 必须切到 autocommit 再 `SET`：psycopg 默认非 autocommit，`SET` 会在**当前（只读）事务**
    #    里执行并被随后的 rollback 撤销 —— 那样第 2 道永远测不到，看起来像"权限层没生效"，
    #    实际是用例自己写错了（这是本文件第二次踩这个坑，故写进注释）。
    with _connect(_RO) as conn:
        conn.autocommit = True
        conn.execute("SET default_transaction_read_only = off")
        conn.autocommit = False
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(_insert_as_ro)
        conn.rollback()


def test_each_pool_reports_its_own_application_name() -> None:
    """DoD④ 的库侧证据：三条池的连接在 `pg_stat_activity` 里**可区分**。

    ⚠️ 这是 T-A1 观测的前提 —— 若三池 `application_name` 相同，
    "这条连接是谁持有的"就无法回答，压测结论也就无从谈起。
    离线断言（`tests/unit/test_pools.py`）只能证明规格表自洽，证明不了它真的传到了服务端。

    ⚠️ 这里**刻意不走 `Settings`**：`application_name` 是**装配**事实（由
    `app/repo/pools.py` 的 `_connect_args` 决定），不是配置项。走 `Settings`
    会把"装配有没有用上规格表"这个问题偷换成"配置读对没读对"。
    """
    from app.repo.pools import (
        ANALYTICS_APPLICATION_NAME,
        METADATA_APPLICATION_NAME,
        POOL_SPECS,
        PoolKind,
    )

    # 规格表与常量先对齐（否则下面的"实测 == 期望"就成了自证）
    assert POOL_SPECS[PoolKind.METADATA].application_name == METADATA_APPLICATION_NAME
    assert POOL_SPECS[PoolKind.ANALYTICS].application_name == ANALYTICS_APPLICATION_NAME

    cases = [
        (METADATA_APPLICATION_NAME, _RW),
        (ANALYTICS_APPLICATION_NAME, _RO),
    ]
    observed: list[str] = []
    for application_name, dsn in cases:
        with psycopg.connect(dsn, connect_timeout=3, application_name=application_name) as conn:
            row = conn.execute("SELECT current_setting('application_name')").fetchone()
            # ⚠️ `fetchone()` 的返回类型含 `None`：`SELECT ...` 在理论上可能不返回行。
            # 不判就索引会让 mypy 报 `not indexable`，**而这不是噪音** ——
            # 它恰好在提醒"若真没返回行，下面那句会抛一个与失败原因无关的 TypeError"。
            assert row is not None, "服务端未回显 application_name —— 观测手段本身失效"
            observed.append(str(row[0]))
    assert observed == [METADATA_APPLICATION_NAME, ANALYTICS_APPLICATION_NAME]
    assert len(set(observed)) == len(observed), "两条池的 application_name 撞名 = 观测手段失效"
