"""exec 执行器**库侧**自证（W2D DoD①②③④ / N-02 / 07 §8.2 / §8.3 / §8.4 / §8.6）。

归属窗口：W2D。集成环境模式沿用 W1B 的 `test_audit_append_only.py`：
有库即跑，无库自动 skip（**不静默假绿**）；schema 带随机后缀，模块级建/删。

⚠️ 负向对照是刻意的（与 W1B 同一纪律）：
只断言"UPDATE 失败"不够 —— 表不存在也会以另一个理由失败。
本模块先证明 SELECT 成功（正向），再证明 UPDATE 被拒（负向），且核对**拒绝理由**
是 42501（权限），不是别的。

⚠️ 两条口径先说清（防止误读）：
- executor 对写语句的失败**形态**可能是 `syntax_error`（服务端游标 DECLARE 不接受
  DML，在到权限检查之前就报语法错）—— 这不是缺陷：闸门 R01 本就只放行 SELECT，
  写语句到不了 exec。**N-02 的库侧证据**由 DB 级用例（裸连接执行 UPDATE：锁①
  只读事务 25006 + 锁② 关掉会话只读后权限拒绝 42501）提供，那才是"app_ro 物理
  不可写"的证明。
- monkeypatch 必须 patch **executor 的命名空间**（executor 是 from-import 引用
  classify_pg_error 的），patch errors 模块属性不生效 —— 本文件第一版踩过。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest

pytestmark = pytest.mark.integration

_SUPER = os.environ.get(
    "COMMERCEQL_TEST_SUPER_DSN", "postgresql://postgres:postgres@localhost:5432/ecom"
)
_RO = os.environ.get("COMMERCEQL_TEST_RO_DSN", "postgresql://app_ro:app_ro_pwd@localhost:5432/ecom")

#: 模块随机后缀（并发跑两次 pytest 也不撞表名）
_SCHEMA = f"it_w2d_{uuid.uuid4().hex[:8]}"

_RO_SQLA_DSN = "postgresql+psycopg://" + _RO[len("postgresql://"):]
_RO_RAW_DSN = _RO


def _connect_super() -> psycopg.Connection:
    return psycopg.connect(_SUPER, connect_timeout=3)


@pytest.fixture(scope="module")
def super_conn() -> Iterator[psycopg.Connection]:
    try:
        conn = _connect_super()
    except Exception as exc:
        pytest.skip(f"集成环境不可用（{type(exc).__name__}）→ 跳过库侧断言，不计为通过")
    yield conn
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    conn.commit()
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def sandbox(super_conn: psycopg.Connection) -> Iterator[None]:
    """建测试 schema + 表 + 数据，并给 app_ro 授予 SELECT（仅 SELECT）。

    行内容覆盖 07 §8.4 的类型分支：numeric / float NaN(id=4,8) / bytea /
    timestamptz / 深嵌套 jsonb（6 层 dict，第 6 层必须被截断标记）。
    """
    with super_conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {_SCHEMA}")
        cur.execute(
            f"CREATE TABLE {_SCHEMA}.t ("
            " id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            " amount numeric(12,2),"
            " ratio float8,"
            " phone text,"
            " note bytea,"
            " created timestamptz,"
            " meta jsonb,"
            " grp text)"
        )
        cur.execute(
            "INSERT INTO "
            f"{_SCHEMA}.t (amount, ratio, phone, note, created, meta, grp) "
            "SELECT g,"
            " CASE WHEN g % 4 = 0 THEN 'NaN'::float8 ELSE g / 3.0 END,"
            " '1380000' || lpad(g::text, 4, '0'),"
            " decode('deadbeef', 'hex'),"
            " '2026-09-15T16:00:00Z'::timestamptz,"
            # 6 层嵌套 dict：a(1)→b(2)→c(3)→d(4)→e(5)→f(6)，第 6 层 > 上限 5
            " jsonb_build_object('a', jsonb_build_object('a', jsonb_build_object('a',"
            " jsonb_build_object('a', jsonb_build_object('a', jsonb_build_object('a', 1)))))),"
            " 'grp' FROM generate_series(1, 10) g"
        )
        cur.execute(f"GRANT USAGE ON SCHEMA {_SCHEMA} TO app_ro")
        cur.execute(f"GRANT SELECT ON {_SCHEMA}.t TO app_ro")
    super_conn.commit()
    yield


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(_RO_SQLA_DSN, pool_size=2, max_overflow=2)


def _settings(**overrides):
    from app.core.config import Settings

    return Settings(
        DATABASE_URL="postgresql+psycopg://app_rw:placeholder@pg:5432/ecom",
        ANALYTICS_DB_URL=_RO_SQLA_DSN,
        DEEPSEEK_API_KEY="sk-placeholder",
        **overrides,
    )


def _ctx(task_id: str = "tk_it"):
    from app.core.contracts import IdentityContext
    from app.core.enums import Role

    return IdentityContext(
        trace_id="tr_it", task_id=task_id, session_id="s_it",
        tenant_id="t_it", user_id="u_it", role=Role.ANALYST,
    )


class _Mask:
    """替身：记录 policy（供断言装配形态），透传 rows（掩码语义已离线覆盖）。"""

    def __init__(self) -> None:
        self.last_policy: dict | None = None

    def apply(self, rows, policy):
        self.last_policy = policy
        from app.core.contracts import MaskOutcome

        return MaskOutcome(rows=tuple(tuple(r) for r in rows), hit_columns=())


def _make_executor(mask: _Mask | None = None, **kw):
    from app.exec.executor import PgSqlExecutor

    return PgSqlExecutor(_engine(), mask or _Mask(), _settings(), **kw)


TENANT_COLS = "id, amount, ratio, phone, note, created, meta"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# DoD③ / N-02：app_ro 物理不可写（DB 级）+ executor 写语句必失败且不落库
# ============================================================================


def test_n02_db_level_app_ro_write_must_fail():
    """N-02 的**库侧**证明：app_ro 两道独立的写锁各自验证（迁移 0001 / startup_assertions 口径）。

    ⚠️ 第一版只断言 42501 是错的：app_ro 角色级 `default_transaction_read_only=on`
    （迁移 0001）让默认连接跑在只读事务里，UPDATE 在权限检查**之前**就被
    25006（只读事务）拒绝 —— 42501 根本没被触达。
    正确口径是两道锁分开证明：
    锁① 连上即只读（25006）；锁② 显式关掉会话只读后，仍必须被表级权限拒绝（42501）。
    """
    # 锁①：默认连接（角色级 read_only=on）→ 25006
    with psycopg.connect(_RO_RAW_DSN, connect_timeout=3) as conn:
        with pytest.raises(psycopg.Error) as ei:
            conn.execute(f"UPDATE {_SCHEMA}.t SET amount = 0")
        assert ei.value.sqlstate == "25006"
    # 锁②：app_ro 自己把会话只读关掉（PGC_USERSET，做得到）→ 权限锁必须兜底 → 42501
    with psycopg.connect(_RO_RAW_DSN, connect_timeout=3, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as ei2:
            conn.execute(f"UPDATE {_SCHEMA}.t SET amount = 0")
        assert ei2.value.sqlstate == "42501"
    # 数据未被改动（写确实没发生，不只是"报了个错"）
    with psycopg.connect(_SUPER, connect_timeout=3) as conn:
        assert conn.execute(f"SELECT count(*) FROM {_SCHEMA}.t WHERE amount = 0").fetchone()[0] == 0


def test_n02_write_via_executor_fails_and_writes_nothing():
    from app.exec.errors import ExecFailure

    ex = _make_executor()

    async def run():
        return await ex.fetch(
            f"UPDATE {_SCHEMA}.t SET amount = 0", {}, _ctx(), max_rows=10, statement_timeout_ms=8000,
        )

    with pytest.raises(ExecFailure) as ei:
        _run(run())
    # 失败形态：DECLARE 不接受 DML → syntax 家族；无论哪类，不得是"成功"
    assert ei.value.error.error_class in {"syntax_error", "permission"}
    assert _SCHEMA not in str(ei.value)  # N-11：不泄露对象名
    # 正向对照 + 未落库验证
    rs = _run(
        ex.fetch(f"SELECT count(*) AS n FROM {_SCHEMA}.t WHERE amount = 0", {}, _ctx(),
                 max_rows=10, statement_timeout_ms=8000)
    )
    assert rs.rows == ((0,),)


def test_n02_negative_control_classification_actually_fires():
    """注入对照：patch executor 命名空间的 classify_pg_error 必须让断言变红、还原回绿。"""
    import app.exec.executor as exec_mod
    from app.exec.errors import ExecError, ExecFailure

    ex = _make_executor()

    async def run():
        return await ex.fetch(
            f"UPDATE {_SCHEMA}.t SET amount = 0", {}, _ctx(), max_rows=10, statement_timeout_ms=8000,
        )

    try:
        with pytest.raises(ExecFailure) as ei:
            _run(run())
        normal_class = ei.value.error.error_class

        exec_mod.classify_pg_error = lambda exc: ExecError(
            error_class="db_unavailable", pgcode=None, message="x", llm_hint=None
        )
        with pytest.raises(ExecFailure) as ei2:
            _run(run())
        assert ei2.value.error.error_class == "db_unavailable"  # 注入生效 ≠ normal_class
        assert normal_class != "db_unavailable"
    finally:
        import app.exec.errors as errors_mod

        exec_mod.classify_pg_error = errors_mod.classify_pg_error
    with pytest.raises(ExecFailure) as ei3:
        _run(run())
    assert ei3.value.error.error_class == normal_class  # 还原：回绿


# ============================================================================
# 超时（§8.2 / §8.9：57014 → EXEC_TIMEOUT）
# ============================================================================


def test_statement_timeout_maps_to_exec_timeout():
    ex = _make_executor()
    from app.exec.errors import ExecFailure

    async def run():
        return await ex.fetch(
            "SELECT pg_sleep(2)", {}, _ctx(), max_rows=10, statement_timeout_ms=300,
        )

    with pytest.raises(ExecFailure) as ei:
        _run(run())
    assert ei.value.error.error_class == "timeout"
    assert ei.value.default_code == "EXEC_TIMEOUT"
    assert ei.value.error.llm_hint is None  # 超时不可修，不回灌


# ============================================================================
# 正常路径：归一化 / 掩码交接 / 指纹 / truncated（DoD①④ 的库侧证据）
# ============================================================================


def test_fetch_full_row_normalization_and_mask_handoff():
    mask = _Mask()
    ex = _make_executor(mask=mask)
    rs = _run(
        ex.fetch(
            f"SELECT {TENANT_COLS} FROM {_SCHEMA}.t ORDER BY id LIMIT 4",
            {}, _ctx(), max_rows=100, statement_timeout_ms=8000,
        )
    )
    assert rs.row_count == 4
    assert rs.truncated is False  # 行数 < LIMIT → §8.6：过滤减行不置 true
    # numeric → 字符串保精度（07 §8.4 第 1 行）
    assert rs.rows[0][1] == "1.00"
    # float NaN → null（id=4 的 ratio 是 NaN）
    assert rs.rows[3][2] is None
    # float 有限值保持 number
    assert isinstance(rs.rows[0][2], float)
    # bytea → 占位符
    assert rs.rows[0][4] == "[binary omitted]"
    # timestamptz → ISO 带 +08:00（UTC 16:00 = 上海次日 00:00，N-18）
    assert rs.rows[0][5] == "2026-09-16T00:00:00+08:00"
    # jsonb：第 6 层 dict 必须被截断标记（§8.4）
    cur_node = rs.rows[0][6]
    depth_seen = 0
    while isinstance(cur_node, dict):
        cur_node = next(iter(cur_node.values()))
        depth_seen += 1
    assert depth_seen == 5
    assert cur_node == "[json depth truncated]"
    # 列元数据按原始值判型
    type_by_name = {c.name: c.type_name for c in rs.columns}
    assert type_by_name["id"] == "number"
    assert type_by_name["amount"] == "decimal"
    assert type_by_name["note"] == "binary_omitted"
    assert type_by_name["created"] == "datetime"
    assert type_by_name["meta"] == "json"
    # 掩码 policy 形状（列序与结果集对齐 + sensitivity 诚实置 None）
    assert mask.last_policy is not None
    assert [c["name"] for c in mask.last_policy["columns"]] == [
        "id", "amount", "ratio", "phone", "note", "created", "meta",
    ]
    assert all(c["sensitivity"] is None for c in mask.last_policy["columns"])
    # 指纹稳定
    rs2 = _run(
        ex.fetch(
            f"SELECT {TENANT_COLS} FROM {_SCHEMA}.t ORDER BY id LIMIT 4",
            {}, _ctx(), max_rows=100, statement_timeout_ms=8000,
        )
    )
    assert rs2.fingerprint == rs.fingerprint


def test_named_cursor_supports_bound_params():
    """N-04 参数化绑定的库侧证据：%(name)s 占位经服务端游标执行。"""
    ex = _make_executor()
    rs = _run(
        ex.fetch(
            f"SELECT id FROM {_SCHEMA}.t WHERE id = %(g)s", {"g": 3}, _ctx(),
            max_rows=10, statement_timeout_ms=8000,
        )
    )
    assert rs.rows == ((3,),)


def test_truncated_true_only_when_rows_reach_effective_limit():
    ex = _make_executor()
    # 生效 LIMIT=3，正好取满 3 行 → truncated=True（§8.6：行数 == 生效 LIMIT）
    rs = _run(
        ex.fetch(
            f"SELECT id FROM {_SCHEMA}.t ORDER BY id", {}, _ctx(),
            max_rows=100, statement_timeout_ms=8000, effective_limit=3,
        )
    )
    assert rs.row_count == 3 and rs.truncated is True
    # 生效 LIMIT=50，只有 10 行 → truncated=False（RLS 减行语义同此路径）
    rs2 = _run(
        ex.fetch(
            f"SELECT id FROM {_SCHEMA}.t ORDER BY id", {}, _ctx(),
            max_rows=100, statement_timeout_ms=8000, effective_limit=50,
        )
    )
    assert rs2.row_count == 10 and rs2.truncated is False


def test_max_rows_hard_cap_and_has_more_fallback():
    ex = _make_executor()
    rs = _run(
        ex.fetch(
            f"SELECT id FROM {_SCHEMA}.t ORDER BY id", {}, _ctx(),
            max_rows=4, statement_timeout_ms=8000,  # 不给 effective_limit → 走 has-more 判定
        )
    )
    assert rs.row_count == 4 and rs.truncated is True


def test_identity_injection_reaches_session_guc():
    """ADR-09 的库侧证据：`set_config(..., true)` 注入的 GUC 在**同一事务**内可读。"""
    ex = _make_executor()

    rs = _run(
        ex.fetch(
            "SELECT current_setting('app.tenant_id', true) AS tid, "
            "current_setting('app.role', true) AS rid, "
            "current_setting('app.shop_ids', true) AS sid",
            {}, _ctx(), max_rows=10, statement_timeout_ms=8000,
        )
    )
    assert rs.rows == (("t_it", "analyst", ""),)


def test_unknown_column_error_is_sanitized_for_repair():
    ex = _make_executor()
    from app.exec.errors import ExecFailure

    async def run():
        return await ex.fetch(
            f"SELECT nonexistent_col FROM {_SCHEMA}.t", {}, _ctx(),
            max_rows=10, statement_timeout_ms=8000,
        )

    with pytest.raises(ExecFailure) as ei:
        _run(run())
    assert ei.value.error.error_class == "unknown_column"
    assert ei.value.error.llm_hint == "引用了不存在的列（已隐去名称）"
    assert _SCHEMA not in ei.value.error.message
    assert "nonexistent_col" not in ei.value.error.message
    assert ei.value.default_code == "SQL_SYNTAX_ERROR"


def test_prepare_threshold_disabled_via_wrapper_chain():
    """§8.1 纪律 3：`prepare_threshold=None`。验证"揭盖"链在真实栈上成立。"""
    from app.exec.executor import PgSqlExecutor

    async def run():
        engine = _engine()
        async with engine.connect() as conn:
            raw = await PgSqlExecutor._raw_connection(conn)
            assert raw is not None
            assert hasattr(raw, "pgconn")  # 是 psycopg 本体（不是 SQLAlchemy 适配壳）
            raw.prepare_threshold = None
            assert raw.prepare_threshold is None
            pid = raw.pgconn.backend_pid
            await engine.dispose()
            return pid

    assert _run(run()) > 0


def test_cancel_running_query():
    """§8.3：cancel 能力 —— 执行中的 pg_sleep 被 pg_cancel_backend 打断 → 57014。"""
    from app.exec.errors import ExecFailure

    ex = _make_executor()

    async def run():
        task = asyncio.ensure_future(
            ex.fetch("SELECT pg_sleep(10)", {}, _ctx("tk_cancel"), max_rows=10, statement_timeout_ms=30000)
        )
        await asyncio.sleep(0.5)  # 让查询先跑起来并完成登记
        ok = await ex.cancel("tk_cancel")
        assert ok is True
        return await task

    with pytest.raises(ExecFailure) as ei:
        _run(run())
    assert ei.value.error.error_class == "timeout"
    assert "tk_cancel" not in ex._running  # finally 清理登记


def test_cancel_unknown_task_returns_false():
    ex = _make_executor()
    assert _run(ex.cancel("no-such")) is False


# ============================================================================
# U-63：gate3_cost 的 EXPLAIN 必须走 explain() 受控入口（07 v0.9 §4.8）
# ============================================================================


def test_explain_returns_structured_plan():
    """U-63 正向：explain() 走受控入口返回解析后的计划 JSON。"""
    ex = _make_executor()
    plan = _run(
        ex.explain(
            f"EXPLAIN (FORMAT JSON) SELECT id FROM {_SCHEMA}.t WHERE grp = 'grp'",
            {}, _ctx("tk_explain"), statement_timeout_ms=8000,
        )
    )
    assert isinstance(plan, list) and plan
    assert "Plan" in plan[0]  # EXPLAIN (FORMAT JSON) 的单行单列 → [{Plan: {...}}]


def test_explain_rejects_non_explain_sql():
    """fail-closed：explain() 只接 EXPLAIN —— 塞普通 SELECT 是契约破损。"""
    ex = _make_executor()
    with pytest.raises(Exception, match="契约破损"):
        _run(
            ex.explain(
                f"SELECT id FROM {_SCHEMA}.t", {}, _ctx("tk_explain_bad"),
                statement_timeout_ms=8000,
            )
        )


def test_explain_requires_format_json():
    """fail-closed：普通 EXPLAIN 输出是文本（str），不是契约要的计划 JSON。"""
    ex = _make_executor()
    with pytest.raises(Exception, match="FORMAT JSON"):
        _run(
            ex.explain(
                f"EXPLAIN SELECT id FROM {_SCHEMA}.t", {}, _ctx("tk_explain_text"),
                statement_timeout_ms=8000,
            )
        )


def test_explain_analyze_timeout_maps_to_exec_timeout():
    """EXPLAIN ANALYZE 会**真执行**查询 —— 超时链路在 explain() 上同样成立。"""
    ex = _make_executor()
    from app.exec.errors import ExecFailure

    async def run():
        return await ex.explain(
            "EXPLAIN (ANALYZE, FORMAT JSON) SELECT pg_sleep(2)",
            {}, _ctx("tk_explain_timeout"), statement_timeout_ms=300,
        )

    with pytest.raises(ExecFailure) as ei:
        _run(run())
    assert ei.value.error.error_class == "timeout"
    assert ei.value.default_code == "EXEC_TIMEOUT"


def test_explain_via_named_cursor_would_fail_42601():
    """⚠️ 钉住陷阱：EXPLAIN **不能**经 DECLARE 游标执行（PG 42601）——

    这正是 fetch() 不能当 gate3 入口用的原因；误走 fetch 会得到
    syntax_error 分类并被回灌 repair（错误信号完全误导）。W4 必须走 explain()。
    """
    ex = _make_executor()
    from app.exec.errors import ExecFailure

    async def run():
        return await ex.fetch(
            "EXPLAIN (FORMAT JSON) SELECT 1", {}, _ctx("tk_explain_fetch"),
            max_rows=10, statement_timeout_ms=8000,
        )

    with pytest.raises(ExecFailure) as ei:
        _run(run())
    assert ei.value.error.error_class == "syntax_error"


# ============================================================================
# 内存上限（§8.2：EXEC_RESOURCE_EXCEEDED，不是 COST_TOO_HIGH）
# ============================================================================


def test_memory_limit_raises_resource_exceeded():
    from app.core.enums import LimitType
    from app.exec.errors import ExecFailure
    from app.exec.executor import PgSqlExecutor

    # 1MB 预算 + 每行 ~1.5MB 文本 → 第一批就超
    ex = PgSqlExecutor(_engine(), _Mask(), _settings(EXEC_MAX_MEMORY_MB=1))

    async def run():
        return await ex.fetch(
            f"SELECT repeat('x', 1500000) AS big FROM {_SCHEMA}.t",
            {}, _ctx(), max_rows=100, statement_timeout_ms=8000,
        )

    with pytest.raises(ExecFailure) as ei:
        _run(run())
    assert ei.value.default_code == "EXEC_RESOURCE_EXCEEDED"
    assert ei.value.detail["limit_type"] == LimitType.MEMORY.value
