"""PG 接触面取证（`reporter.pg_surface` / `gates._pg_surface_notes`）与只读闸门（`eval/pg_guard.py`）。

归属窗口：W6。

这一份文件的存在理由（2026-09-22，W7 提的两条要求）
--------------------------------------------------------------------------
* 「报全量读数时点名是否含集成层 / 夹具 DSN 指向哪」⇒ 这句话一旦只写在散文里就会腐：
  下一轮没人记得点名。所以把它做成**读数的固定字段**，并测三件事 ——
  ① 没取证时必须说「未取证」（不许沉默、也不许反过来替环境宣布「没连库」）；
  ② 红不红都要出这句话（窗外红时最容易只盯红因、把接触面漏掉）；
  ③ DDL 落在共享业务 schema（`app` / `public`）时必须额外 ⚠️ 点名。
* 「加一条会响的守卫」⇒ 我方做不到「拒连共享 `ecom`」（做到就等于把 G-4 退回 UNVERIFIED），
  做到的是「每条会话都没有写能力、且被服务端拒过一次」。所以本文件测的是**它会响**：
  闸门没生效时 `open_readonly()` 必须抛，而不是返回一把看起来只读的连接。

⚠️ 全部离线：不连任何数据库。真库那一半由 `_probe_pg_real.py` / `_probe_parallel_states.py`
   产物里的 `pg_guard` 字段自证。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import gates as gt
import pg_guard
import pytest
import reporter as rp
from psycopg.conninfo import conninfo_to_dict

_LOG_WITH_PG_SIGNAL = """\
E           psycopg.errors.InsufficientPrivilege: permission denied for database ecom
DDL: CREATE SCHEMA IF NOT EXISTS retrieval_dense_it
DDL: DROP TABLE IF EXISTS retrieval_dense_it.embed_doc
host=localhost port=5432 user=app_ro password=s3cr3t-not-a-real-one dbname=ecom
ERROR tests/integration/test_retrieval_fts_pg.py::test_retrieval_pg - psycopg...
1 failed, 2232 passed
"""


def _log(tmp_path: Path, text: str) -> str:
    path = tmp_path / "pytest.log"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ============================================================================
# 取证：pg_surface 从日志里能说什么、不能说什么
# ============================================================================
def test_pg_surface_returns_none_when_the_log_carries_no_pg_signal(tmp_path):
    """日志里既没有集成层文件名、也没有库名/DDL ⇒ 如实返回 None（不是空 dict，那会被读成「查过了、干净」）。"""
    assert rp.pg_surface(_log(tmp_path, "2232 passed in 127.76s\n")) is None
    assert rp.pg_surface(None) is None


def test_pg_surface_names_layers_and_ddl_without_leaving_credentials(tmp_path):
    """接触面要能点名「含不含集成层 / 动过哪些对象」，但口令一个字都不许进产物。"""
    surface = rp.pg_surface(_log(tmp_path, _LOG_WITH_PG_SIGNAL))
    assert surface is not None
    assert surface["integration_named"] == ["tests/integration/test_retrieval_fts_pg.py"]
    assert surface["databases_denied"] == ["ecom"]
    assert "CREATE SCHEMA retrieval_dense_it" in surface["ddl_targets"]
    assert "DROP TABLE retrieval_dense_it.embed_doc" in surface["ddl_targets"]
    assert "s3cr3t-not-a-real-one" not in repr(surface)


def test_pg_surface_dedupes_repeated_ddl_lines(tmp_path):
    """同一条 DDL 在 traceback 里出现三次 ⇒ 只点名一次（否则会被读成「动了三次」）。"""
    text = "CREATE TABLE app.orders_bak\n" * 3
    assert rp.pg_surface(_log(tmp_path, text))["ddl_targets"] == ["CREATE TABLE app.orders_bak"]


#: 🔴 正对照，形状**照抄真日志**（`_full_pytest_w6.log:53`）：pytest 把夹具的 SQL 以 **repr**
#: 打出来，所以 `\n` 是两个字符 —— 取证正则若带 `\b` 就永远取不到东西（看着绿、其实空）。
_REAL_LOG_DDL_SHAPE = (
    "query = '\\nCREATE SCHEMA IF NOT EXISTS retrieval_dense_it;"
    "\\nDROP TABLE IF EXISTS retrieval_dense_it.embed_doc;\\nCREATE TABLE r...   "
    "text NOT NULL,\\n    embedding      vector(4)\\n);\\n'\n"
)


def test_pg_surface_reads_ddl_from_the_real_repr_shaped_pytest_output(tmp_path):
    """接触面必须能在**真日志形状**上取到 DDL，不只是在我顺手写的干净文本上取到。"""
    targets = rp.pg_surface(_log(tmp_path, _REAL_LOG_DDL_SHAPE))["ddl_targets"]
    assert "CREATE SCHEMA retrieval_dense_it" in targets
    assert "DROP TABLE retrieval_dense_it.embed_doc" in targets
    assert "CREATE TABLE r (截断)" in targets  # 日志被 pytest 截断 ⇒ 如实点名，不假装是对象名
    assert not any(t.startswith("CREATE TABLE r...") for t in targets)


def test_empty_ddl_targets_is_worded_as_a_lower_bound(tmp_path):
    """「DDL 形状 = 无」不许被读成「这轮对共享库什么都没做」⇒ 空值时措辞自带下界。"""
    notes = gt._pg_surface_notes({"pg_surface": {
        "integration_named": ["tests/integration/test_x.py"], "databases_denied": ["ecom"],
        "ddl_targets": [], "conn_params": []}})
    assert "取不到 ≠" in notes[0] and "没做任何写操作" in notes[0]


def test_the_g1_input_carries_the_surface_as_a_fixed_key(tmp_path):
    """接触面必须是 `parse_pytest_summary` 的固定键 ⇒ 复算时不可能被手抄漏掉。"""
    summary = rp.parse_pytest_summary(_log(tmp_path, _LOG_WITH_PG_SIGNAL))
    assert summary is not None and summary["failed"] == 1
    assert summary["pg_surface"]["databases_denied"] == ["ecom"]


# ============================================================================
# 声明：这条话什么时候必须出现
# ============================================================================
def test_the_surface_declaration_is_emitted_even_when_nothing_is_red():
    """不红也要出这句话 —— 只在红的时候才说，等于下一轮没人记得说。"""
    notes = gt._pg_surface_notes({"pg_surface": {
        "integration_named": ["tests/integration/test_retrieval_fts_pg.py"],
        "databases_denied": [],
        "ddl_targets": ["CREATE SCHEMA retrieval_dense_it"],
        "conn_params": ["localhost"],
    }})
    assert len(notes) == 1  # 目标全在测试专用 schema ⇒ 不额外 ⚠️
    assert "test_retrieval_fts_pg.py" in notes[0]
    assert "凭据一律不落盘" in notes[0]


def test_missing_surface_is_reported_as_unaudited_not_as_no_database():
    """没取证只能写成「未取证 + 怎么补」，不许写成「这轮没连库」（那是替环境宣布结论）。"""
    notes = gt._pg_surface_notes({})
    assert len(notes) == 1
    assert "未取证" in notes[0] and "-rfEs" in notes[0]
    assert "没连库" not in notes[0] and "未连" not in notes[0]


def test_ddl_on_the_shared_business_schema_gets_a_named_warning():
    """DDL 目标限定在 `app` / `public` ⇒ 必须额外 ⚠️ 点名（「会响」那半条的读端）。

    两词动词（`DROP TABLE`）与带子句/尾缀的目标（`DROP SCHEMA IF EXISTS … CASCADE`）都要判对：
    按固定词数切对象名时，前者永不命中、后者会被误判 ⇒ 这一格是那条 bug 的正反对照。
    """
    notes = gt._pg_surface_notes({"pg_surface": {
        "integration_named": [],
        "databases_denied": ["ecom"],
        "ddl_targets": ["CREATE SCHEMA retrieval_dense_it", "TRUNCATE app.embed_doc",
                        "DROP TABLE public.foo", "DROP SCHEMA IF EXISTS retrieval_dense_it CASCADE"],
    }})
    assert len(notes) == 2
    assert notes[1].startswith("⚠️")
    assert "app.embed_doc" in notes[1] and "public.foo" in notes[1]
    assert "retrieval_dense_it" not in notes[1]
    assert "不推断因果" in notes[1]


# ============================================================================
# 闸门：pg_guard 必须「会响」
# ============================================================================
class _Rejected(Exception):
    """替身：对应 `psycopg.errors.ReadOnlySqlTransaction`。"""


class _Cursor:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class _FakeConn:
    """假连接：按 SQL 文本决定返回值，并把「写请求有没有被拒」摆出来。"""

    def __init__(self, *, show_value: str, write_rejected: bool):
        self.stmt: list[str] = []
        self.closed = False
        self._show = show_value
        self._reject_write = write_rejected

    async def execute(self, sql, *args, **kwargs):
        self.stmt.append(sql)
        low = sql.lower()
        if low.startswith("show"):
            return _Cursor((self._show,))
        if "current_database()" in low:
            return _Cursor(("ecom", "postgres", self._show, "PostgreSQL 16.15, on x86_64"))
        if "create table" in low and self._reject_write:
            raise _Rejected("cannot execute CREATE TABLE in a read-only transaction")
        return _Cursor(None)

    async def close(self):
        self.closed = True


class _FakePsycopg:
    """只替 `pg_guard` 眼里的两处：`AsyncConnection.connect` 与 `errors.ReadOnlySqlTransaction`。"""

    def __init__(self, conn):
        self.conn = conn
        errors = type("errors", (), {"ReadOnlySqlTransaction": _Rejected})
        connector = type("AsyncConnection", (), {
            "connect": staticmethod(lambda dsn, **kw: self._connect())})
        self.AsyncConnection = connector
        self.errors = errors

    async def _connect(self):
        return self.conn


@pytest.fixture
def fake_pg(monkeypatch):
    def _install(conn):
        monkeypatch.setattr(pg_guard, "psycopg", _FakePsycopg(conn), raising=True)
        return conn

    return _install


def test_open_readonly_raises_when_the_write_attempt_is_not_rejected(fake_pg):
    """故意下发 CREATE TABLE 却**没被拒** ⇒ 这道闸是假的，必须抛，且当场关掉连接。"""
    conn = fake_pg(_FakeConn(show_value="on", write_rejected=False))
    with pytest.raises(pg_guard.PgReadOnlyGuardError) as exc:
        asyncio.run(pg_guard.open_readonly(
            "postgresql://app_ro:app_ro_pwd@localhost:5432/ecom", purpose="test"))
    assert "没有被拒" in str(exc.value)
    assert conn.closed is True
    # 🔴 异常文案也会被打印进日志 ⇒ 里面同样不许出现口令，但要点名目标库。
    assert "app_ro_pwd" not in str(exc.value)
    assert "app_ro@localhost:5432/ecom" in str(exc.value)


def test_open_readonly_raises_when_show_says_it_is_not_read_only(fake_pg):
    """SET 之后 SHOW 回来不是 on ⇒ 同样必须抛（服务端没认这把闸）。"""
    conn = fake_pg(_FakeConn(show_value="off", write_rejected=True))
    with pytest.raises(pg_guard.PgReadOnlyGuardError, match="SHOW 回来"):
        asyncio.run(pg_guard.open_readonly("postgresql://x@localhost:5432/ecom", purpose="test"))
    assert conn.closed is True


def test_open_readonly_passes_and_stamps_when_the_gate_holds(fake_pg):
    """两关都过（SHOW=on + 写被拒）⇒ 放行，且 `target_stamp()` 把两件事都落成读数。"""
    conn = fake_pg(_FakeConn(show_value="on", write_rejected=True))
    opened = asyncio.run(pg_guard.open_readonly(
        "postgresql://x@localhost:5432/ecom", purpose="test"))
    assert opened is conn
    assert asyncio.run(pg_guard.target_stamp(opened)) == {
        "database": "ecom", "role": "postgres", "read_only_enforced": True,
        "write_attempt_rejected": True, "server": "PostgreSQL 16.15"}
    assert any("create table" in s.lower() for s in conn.stmt), "闸门必须真的写过一次"


# ============================================================================
# DSN：编码要能被 libpq 解析，且幂等
# ============================================================================
def test_force_readonly_encodes_the_guc_so_libpq_can_parse_it():
    """实测坑：`options` 值里的 `=` 不编码 ⇒ psycopg 直接抛
    `extra key/value separator "=" in URI query parameter: "options"`。
    所以这里不只看字符串，而是**让 libpq 自己解析一遍**再读回参数值。
    """
    out = pg_guard.force_readonly(
        "postgresql://app_ro:app_ro_pwd@localhost:5432/ecom?connect_timeout=3")
    info = conninfo_to_dict(out)
    assert info["options"] == "-c default_transaction_read_only=on"
    assert info["connect_timeout"] == "3" and info["dbname"] == "ecom"


def test_force_readonly_is_idempotent():
    """两个探针各自再包一次同一个常量；包两次拼出两个 `options` 就破坏连接串。"""
    once = pg_guard.force_readonly("postgresql://postgres:postgres@localhost:5432/ecom")
    assert pg_guard.force_readonly(once) == once


def test_redact_dsn_keeps_the_target_and_drops_the_password():
    """跨窗口要点名「连的是哪个库」，但凭据不能跟着走。"""
    assert pg_guard.redact_dsn(
        "postgresql://app_ro:app_ro_pwd@localhost:5432/ecom") == "app_ro@localhost:5432/ecom"


def test_redact_dsn_on_an_unparseable_shape_does_not_echo_the_input():
    """解析不了就返回固定文案 —— 宁可少说，也不把原文（可能含口令）抄进产物。"""
    out = pg_guard.redact_dsn("host=localhost user=app_ro password=app_ro_pwd")
    assert "app_ro_pwd" not in out and "无法解析" in out
