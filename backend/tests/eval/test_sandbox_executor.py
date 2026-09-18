"""`eval/sqlite_exec.py` 的单元测试 —— D2 裁定（"SQLite 只换 I/O，复用在线纯逻辑"）的落点。

归属窗口：W6。

三条必须被测住的边界
--------------------------------------------------------------------------
* **驱动契约适配**：在线 `PgSqlExecutor._execute_and_collect` 按 `d.name` 取列名，
  而 `sqlite3` 给裸元组。这条不补齐的实测后果是"红队 15 条执行用例**全部**没跑到一行"
  （`_AsyncCursor.description` 的 docstring 记了原委），而且炸法是被
  `except BaseException` 重抛成"执行层内部错误" —— 看起来像被测系统的错。
* **只读 + 租户边界**：评测对 `data/ecom_sandbox.db` 零改动，且 SQL 里不出现
  `tenant_id` 也看不到别家行（I-4/I-5 冲突的解法，见模块 docstring 第二节）。
* **错误分类与生产同形**：sqlite 消息签名 → `ExecError.error_class` 必须落在
  07 §8.9 的既有类别里，且 `pgcode` 恒 `None`（伪造 SQLSTATE 会被下游当 PG 码统计）。
"""

from __future__ import annotations

import sqlite3

import pytest
import sqlite_exec as sx

from app.exec.errors import EXEC_ERROR_CLASSES, MESSAGES, NON_REPAIRABLE, ExecFailure


@pytest.fixture
def mini_db(tmp_path):
    """一个人造小库：租户边界与只读语义要**可判别**，440,000 行的真沙箱做不到这点。

    ⚠️ 为什么不能拿 `data/ecom_sandbox.db` 做这件事（实测教训）：全表 200,000 行
    100% 带 `tenant_id='T_A'`，于是"`WHERE tenant_id='T_B'` 返回 0 行"这种
    **什么都没验证到**的断言也能通过。小库让"过滤真的生效"成为可判别的。
    """
    path = tmp_path / "mini.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE v_order_paid (order_id TEXT, tenant_id TEXT, pay_amount REAL);
        INSERT INTO v_order_paid VALUES ('A1','T_A',10.0),('A2','T_A',20.0),
                                        ('B1','T_B',30.0),('C1','T_C',40.0);
        CREATE TABLE v_region (region_code TEXT, region_name TEXT);
        INSERT INTO v_region VALUES ('r1','华东'),('r2','华南');
        """
    )
    con.commit()
    con.close()
    return str(path)


_TENANT_PHYSICALS = {"v_order_paid": "tenant_id"}


# ==== 错误分类：签名 → 类别（07 §8.9 的既有词表，不新增）==============
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("no such table: v_shop", "unknown_table"),
        ("no such column: pay_amunt", "unknown_column"),
        ("table v_shop has no column named foo", "unknown_column"),
        ("no such function: date_trunc", "unknown_function"),
        ("no such collation sequence: C", "unknown_function"),
        ("datatype mismatch", "type_mismatch"),
        ("interrupted", "timeout"),
        ('near "FROM": syntax error', "syntax_error"),
        # 写操作被沙箱拒：必须归 `permission`（PG 同形：42501）。
        # 落到 `syntax_error` 的代价是进 repair 循环让模型改写重试（`REPAIRABLE`）。
        ("attempt to write a readonly database", "permission"),
        ("cannot modify v_order_paid because it is a view", "permission"),
        ("database is locked", "db_unavailable"),
    ],
)
def test_classify_maps_signature_to_error_class(message, expected):
    err = sx.classify_sqlite_error(sqlite3.OperationalError(message))
    assert err.error_class == expected
    assert err.error_class in EXEC_ERROR_CLASSES, "分类不许造词表外的类别"
    assert err.message == MESSAGES[expected], "类别级文案必须取自 W2D，不写第二份"


def test_no_such_table_wins_over_bare_no_such():
    """顺序敏感的正对照：兜底签名若排在前面会把表错误读成列错误。"""
    err = sx.classify_sqlite_error(sqlite3.OperationalError("no such table: v_shop"))
    assert err.error_class == "unknown_table"


def test_unregistered_message_falls_back_to_syntax_family():
    assert sx.classify_sqlite_error(sqlite3.OperationalError(" totally odd ")).error_class == "syntax_error"


def test_pgcode_is_always_none_so_no_fake_sqlstate_leaks():
    """沙箱没有 SQLSTATE；伪造一个会被下游按 PG 错误码统计（§17.4 的假绿形态）。"""
    for msg in ("no such table: x", "no such function: f", "weird"):
        assert sx.classify_sqlite_error(sqlite3.OperationalError(msg)).pgcode is None


def test_timeout_and_permission_are_non_repairable_classes():
    """分类错不只是文案问题：它决定这条 SQL 会不会被回灌重跑。"""
    assert {"timeout", "permission", "db_unavailable"} <= NON_REPAIRABLE


# ==== 占位符适配：只动形状，值仍走绑定（N-04）=========================
def test_to_sqlite_sql_rewrites_named_placeholders_only():
    out = sx.to_sqlite_sql("SELECT * FROM t WHERE a = %(x)s AND b = %(y_2)s")
    assert out == "SELECT * FROM t WHERE a = :x AND b = :y_2"


def test_to_sqlite_sql_leaves_unparameterised_sql_untouched():
    sql = "SELECT pay_amount FROM v_order_paid WHERE pay_status = 'paid'"
    assert sx.to_sqlite_sql(sql) == sql


# ==== 租户边界：TEMP VIEW（谓词在被测 SQL 之外）=======================
def test_tenant_view_filters_without_touching_the_sql(mini_db):
    con = sx.open_sandbox_connection(mini_db, tenant_id="T_A", tenant_scoped_physicals=_TENANT_PHYSICALS)
    rows = con.execute("SELECT order_id FROM v_order_paid").fetchall()   # SQL 里没有 tenant_id
    assert sorted(r[0] for r in rows) == ["A1", "A2"]
    con.close()


def test_boundary_is_entirely_driven_by_the_registry(mini_db):
    """换一份 `{物理表: 列名}` 清单，边界就跟着变 —— 所以它**必须**来自语义包。

    ⚠️ 这条同时记下该机制的软肋：清单漏一项不会报错，只会**静默失去边界**
    （下面第二条断言就是漏项后的全量读取）。因此 `consistency.py` 的 ①前置
    逐资产验证"视图确实过滤 + 各租户并集覆盖全量"，而不是只测一条用例。
    """
    con = sx.open_sandbox_connection(mini_db, tenant_id="T_A",
                                     tenant_scoped_physicals={"v_region": "region_code"})
    assert len(con.execute("SELECT order_id FROM v_order_paid").fetchall()) == 4   # 漏项 ⇒ 无边界
    assert [r[0] for r in con.execute("SELECT region_code FROM v_region").fetchall()] == []
    con.close()


def test_non_tenant_asset_falls_back_to_shared_dimension(mini_db):
    con = sx.open_sandbox_connection(mini_db, tenant_id="T_A", tenant_scoped_physicals=_TENANT_PHYSICALS)
    assert len(con.execute("SELECT region_code FROM v_region").fetchall()) == 2  # 公共维表不被过滤
    con.close()


def test_none_tenant_means_unscoped_connection(mini_db):
    """§17.6① 的另一侧：与 W1A `tenant_wrap` 同形比对时需要**未隔离**的连接。"""
    con = sx.open_sandbox_connection(mini_db, tenant_id=None, tenant_scoped_physicals=_TENANT_PHYSICALS)
    assert len(con.execute("SELECT order_id FROM v_order_paid").fetchall()) == 4
    con.close()


def test_readonly_connection_rejects_writes(mini_db):
    con = sx.open_sandbox_connection(mini_db, tenant_id=None, tenant_scoped_physicals={})
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        con.execute("UPDATE v_order_paid SET pay_amount = 0")
    con.close()


@pytest.mark.parametrize("bad", ["T_A' OR 1=1 --", "T A", "", "T;A", "租户"])
def test_tenant_code_charset_gate(mini_db, bad):
    """拼进视图 DDL 的**唯一**变量必须过白名单（`CREATE VIEW` 不吃参数绑定，实测）。"""
    with pytest.raises(ValueError, match="租户码"):
        sx.open_sandbox_connection(mini_db, tenant_id=bad, tenant_scoped_physicals=_TENANT_PHYSICALS)


@pytest.mark.parametrize("phys,col", [("v_order_paid", "bad-col"), ("1table", "tenant_id")])
def test_identifier_whitelist_on_bundle_supplied_names(mini_db, phys, col):
    """表/列名虽然来自语义包（受控来源），**仍然**要校验 —— 受控不等于合法。"""
    with pytest.raises(ValueError, match="标识符"):
        sx.open_sandbox_connection(mini_db, tenant_id="T_A", tenant_scoped_physicals={phys: col})


# ==== 异步游标：驱动契约的两条腿 =====================================
async def test_async_cursor_description_exposes_name_and_index(mini_db):
    """`d.name`（在线代码）与 `d[0]`（评测等价判定）必须同时可用。"""
    con = sx.open_sandbox_connection(mini_db, tenant_id="T_A", tenant_scoped_physicals=_TENANT_PHYSICALS)
    async with sx._AsyncCursor(con, 5000) as cur:
        assert cur.description is None                      # 未执行前没有元数据
        await cur.execute("SELECT order_id, pay_amount FROM v_order_paid", {})
        names = [d.name for d in cur.description]
        assert names == ["order_id", "pay_amount"]
        assert cur.description[0][0] == "order_id"
        assert await cur.fetchmany(10) == [("A1", 10.0), ("A2", 20.0)]
    con.close()


async def test_async_cursor_raises_classified_exec_failure(mini_db):
    con = sx.open_sandbox_connection(mini_db, tenant_id="T_A", tenant_scoped_physicals=_TENANT_PHYSICALS)
    async with sx._AsyncCursor(con, 5000) as cur:
        with pytest.raises(ExecFailure) as ei:
            await cur.execute("SELECT no_such_col FROM v_order_paid", {})
        assert ei.value.error.error_class == "unknown_column"
    con.close()


async def test_deadline_interrupt_is_classified_as_timeout(tmp_path):
    """`set_progress_handler` 是沙箱里唯一的取消手段（PG 那边是 `pg_cancel_backend`）。

    断言的是**类别**而不是"有没有报错"：`interrupted` 若落到 `syntax_error` 兜底，
    评测会把一次超时记成一次"模型写错 SQL"。
    """
    path = str(tmp_path / "big.db")
    rw = sqlite3.connect(path)
    rw.execute("CREATE TABLE t(x)")
    rw.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100_000)])
    rw.commit()
    rw.close()

    con = sx.open_sandbox_connection(path, tenant_id=None, tenant_scoped_physicals={})
    async with sx._AsyncCursor(con, 1) as cur:
        with pytest.raises(ExecFailure) as ei:
            await cur.execute("SELECT count(*) FROM t a, t b WHERE a.x < b.x", {})
        assert ei.value.error.error_class == "timeout"
    con.close()


# ==== 端到端：真沙箱上把在线收集/掩码链路跑通 ========================
async def test_fetch_end_to_end_on_real_sandbox(harness, analyst_ctx):
    """报告 §8 说"执行层端到端未覆盖"—— 那是**被测系统**没出 SQL，不是执行器坏。

    这条测试把这一格钉死：手写一条合法 SQL 走 `fetch` ⇒ 收集、判型、掩码、指纹全通。
    金额列在沙箱是 REAL→float（缺口表"驱动层"行），所以只断言形状不断言类型。
    """
    rs = await harness.executor.fetch(
        "SELECT pay_amount, receiver_phone FROM v_order_paid LIMIT 5", {}, analyst_ctx,
        max_rows=50, statement_timeout_ms=8000,
    )
    assert [c.name for c in rs.columns] == ["pay_amount", "receiver_phone"]
    assert rs.row_count == 5 and len(rs.rows) == 5
    assert rs.truncated is False
    assert all("***" in row[1] for row in rs.rows), "PII 列必须经在线掩码引擎"
    assert len(rs.fingerprint) == 64


async def test_fetch_truncates_at_max_rows(harness, analyst_ctx):
    rs = await harness.executor.fetch(
        "SELECT order_id FROM v_order_paid", {}, analyst_ctx,
        max_rows=3, statement_timeout_ms=8000,
    )
    assert len(rs.rows) == 3 and rs.truncated is True, "N-06：截断必须显形，不能静默丢行"


async def test_tenant_isolation_holds_through_executor(harness):
    """同一句 SQL、两个租户 ⇒ 行数等于一致性测试① 的每租户基数（两处必须同数）。"""
    async def count(tenant: str) -> int:
        ctx = __import__("harness").identity_for_case("T-ISO", tenant)
        rs = await harness.executor.fetch(
            "SELECT COUNT(*) AS n FROM v_order_paid", {}, ctx,
            max_rows=10, statement_timeout_ms=8000,
        )
        return int(rs.rows[0][0])

    a, b = await count("T_A"), await count("T_B")
    assert (a, b) == (200000, 175000), "与 consistency_results.json 的 ①前置 基数不一致"
    assert a != b


async def test_named_parameters_survive_the_placeholder_rewrite(harness, analyst_ctx):
    rs = await harness.executor.fetch(
        "SELECT pay_amount FROM v_order_paid WHERE pay_status = %(st)s LIMIT 2",
        {"st": "paid"}, analyst_ctx, max_rows=10, statement_timeout_ms=8000,
    )
    assert rs.row_count == 2, "绑定值必须仍走参数绑定（N-04），而不是被拼进 SQL"


async def test_explain_returns_none_so_gate3_self_reports_skipped(harness, analyst_ctx):
    """§17.4：SQLite 无 `EXPLAIN (FORMAT JSON)`。返回 None 而不是抛异常，
    让 `run_gate3` 自己判 `SKIPPED`（"不可用"≠"通过"，也≠成本闸门 FAIL）。"""
    assert await harness.executor.explain(
        "SELECT 1", {}, analyst_ctx, statement_timeout_ms=100
    ) is None


async def test_cancel_is_always_false_in_sandbox(harness):
    """没有 PG 后端 PID 可取消 —— 谎报 True 会让超时治理看起来比实际强。"""
    assert await harness.executor.cancel("no-such-task") is False
