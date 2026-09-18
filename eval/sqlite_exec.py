"""沙箱执行适配器（D2 裁定："SQLite I/O 适配 + 复用纯逻辑"）。

归属窗口：W6（docs/08 §4.1：`eval/**` 的**执行器**部分）。

--------------------------------------------------------------------------
一、ADR-18：评测必须走在线 exec 代码路径，本文件只换 I/O
--------------------------------------------------------------------------
`SqliteEvalExecutor` **继承** `app.exec.executor.PgSqlExecutor`，并且只替换两处：

1. `_controlled_session`（PG 连接治理：analytics 池 / `set_config` GUC / 服务端命名
   游标 / `statement_timeout` / `pg_cancel_backend`）→ 换成 SQLite 只读连接 +
   `set_progress_handler` 的超时打断；
2. 驱动层的**错误分类**（`classify_pg_error` 读 SQLSTATE）→ 换成 `sqlite3` 消息签名。

**收集上限、内存预算、`truncated` 判定、`normalize_row` 类型归一化、掩码交接、
`_column_meta` 判型、`result_fingerprint` 指纹** —— 全部由
`PgSqlExecutor._execute_and_collect` **逐字执行**（子类直接调它，不复制一行）。
本文件里没有任何一条自己的归一化/哈希规则：那正是 ADR-18 要防的"第二份真相"。

--------------------------------------------------------------------------
二、租户边界：DB 对象级（视图），**不是** SQL 改写（I-4 / I-5 的结构性冲突）
--------------------------------------------------------------------------
§17.6 的 I-4 要求"租户过滤由执行层在资产边界注入（SQL 层改写），不是结果过滤"，
I-5 补一句"注入后的 SQL **仍须过 gate1/gate2**"。这两条在**本项目语义包下不能同时成立**：

· `semantic/bundle_2026.09.14.1.yaml` 的 `policies.deny_columns` 逐条列了 6 个租户域的
  `<logical>.tenant_id`（原文注释："租户键由执行层注入，模型不得引用"）；
· `LoadedBundle.allowlist` 的列集**已剔除 deny 列**（loader 的 ADR-10 派生）；
· `ast_gate._check_columns` 对 `deny_columns` 命中的列直接 `R07_DENY_COLUMNS`。

⇒ 任何把 `tenant_id = '…'` 写进被审计 SQL 的做法（含 W1A 的
`build_frozen_set.tenant_wrap` 派生表形态）都会被 gate1 拒 —— 于是 I-5 的
"过闸门"与 I-4 的"SQL 层改写"互斥。生产不撞这个矛盾，是因为它走 **PG RLS**：
谓词活在**策略层**，压根不出现在 SQL 里（`SET app.tenant_id` 只是给策略喂值）。

**本文件据此选择与生产同构的那一半**：租户边界做成 **DB 对象**
（`CREATE TEMP VIEW`，与 RLS 策略同为"谓词在被测 SQL 之外"），
被测 SQL 里**不出现** `tenant_id` —— 既满足 I-4 的实质（"数据库层面看不到"，
不是结果过滤），又满足 I-5 的"注入后仍须过闸门"（它从未经过 tenant 谓词，
与在线 SQL 同形）。冲突本身进 §17.4 缺口表 + `reports/w6/RELAY.md` 上呈架构，
**不由评测器私自改口径**。

gold 侧（W1A 的 `tenant_wrap` + `result_hash`）保持原样复算，两条路径的一致性由
`eval/consistency.py` 的 §17.6① 判定；口径不同导致的差异**如实报告**，不合并。

--------------------------------------------------------------------------
三、`explain()` 返回 None（§17.4 的"无 EXPLAIN JSON"）
--------------------------------------------------------------------------
SQLite 没有 `EXPLAIN (FORMAT JSON)`。返回 `None` 而不是抛异常：
`app/guard/cost_gate.run_gate3` 对空 `explain_plan` 判 `SKIPPED`
（`reason="dialect_no_explain_json"`），这正是 §17.4 规定的缺口呈现形态
（"不可用 ≠ 通过"，也 ≠ 把成本闸门判成 FAIL）。

--------------------------------------------------------------------------
四、诚实边界（本文件**不**声称覆盖的东西）
--------------------------------------------------------------------------
· **numeric → Decimal 不成立**：沙箱金额列是 SQLite REAL → Python `float`，
  在线 PG 是 `numeric` → `Decimal` → 归一化成**字符串**。因此评测里的金额列
  天然带浮点尾差，等价判定必须走 `eval/equivalence.py` 的 `REL_TOL`；
  指纹与 `gold_result_hash`（同为 float 口径）之间不因此失配，
  但**与生产结果失配的可能存在**（缺口表"驱动层"行）。
· **无 `statement_timeout` 的库侧取消**：`set_progress_handler` 只能中断**本进程**
  的执行，不存在 PG 的后端 PID 取消语义 —— `cancel()` 恒 `False`。
· **性能不可外推**：SQLite 单机、无并发、无优化器成本模型；本文件测得的时延
  不得用作 G-6（P95 ≤ 8s）的依据（G-6 数据源 = W7 压测）。
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections import namedtuple
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from app.core.config import Settings
from app.core.contracts import IdentityContext, MaskPort, ResultSet, SemanticBundlePort
from app.exec.errors import LLM_HINT_BY_CLASS, MESSAGES, ExecError, ExecFailure
from app.exec.executor import PgSqlExecutor

__all__ = [
    "SqliteEvalExecutor",
    "classify_sqlite_error",
    "open_sandbox_connection",
    "to_sqlite_sql",
]

#: DBAPI / psycopg3 `cursor.description` 的七元组形状（在线代码按 `d.name` 取列名，
#: sqlite3 只给裸元组 ⇒ 见 `_AsyncCursor.description` 的适配）。
ColumnDesc = namedtuple(
    "ColumnDesc",
    "name type_code display_size internal_size precision scale null_ok",
)

#: psycopg 命名占位符 `%(name)s` → SQLite 命名占位符 `:name`（键名不变，值仍走绑定，N-04）。
_PSYCOPG_PARAM_RE: Final[re.Pattern[str]] = re.compile(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)s")

#: `set_progress_handler` 的调用间隔（每 N 条虚拟机指令回调一次；太小会拖慢执行）。
_PROGRESS_OPS: Final[int] = 20_000

#: sqlite 消息签名 → `error_class`（07 §8.9 的同一套类别，**不新增类别**）。
#: ⚠️ 顺序敏感：`no such table` 必须先于 `no such`（后者会吞掉所有形态）。
_SQLITE_SIGNATURES: Final[tuple[tuple[str, str], ...]] = (
    ("no such table", "unknown_table"),
    ("no such column", "unknown_column"),
    ("has no column named", "unknown_column"),
    ("no such function", "unknown_function"),
    ("no such collation sequence", "unknown_function"),
    ("datatype mismatch", "type_mismatch"),
    ("interrupted", "timeout"),
    # 只读沙箱里的一切写操作。⚠️ 缺这两条时它们会落到 `syntax_error` 兜底
    # （"SQL 语法有误"），而同一句 SQL 在 PG 上回的是 42501 → `permission` ——
    # 分类必须与生产同形。更要紧的是 `syntax_error` 属 `REPAIRABLE_CLASSES`：
    # 把"写操作被拒"说成"语法错了"会把 DML 尝试喂进 repair 循环让模型改写重试。
    # 两种形态都要盖住：无视图时是 `attempt to write a readonly database`，
    # 建了租户视图时是 `cannot modify <view> because it is a view`。
    ("attempt to write a readonly database", "permission"),
    ("cannot modify", "permission"),
    # 锁冲突 = 可用性问题（PG 侧同类由 `classify_pg_error` 归 `db_unavailable`），
    # 落到兜底会把它说成"语法有误"并进 repair 循环 —— 而重试同一条 SQL 只会再撞一次锁。
    ("database is locked", "db_unavailable"),
    ("syntax error", "syntax_error"),
)


def classify_sqlite_error(exc: BaseException) -> ExecError:
    """`sqlite3.Error` → 脱敏 `ExecError`（与 `classify_pg_error` 同一产出契约）。

    ⚠️ 与 PG 版的**唯一**差异是判据来源：SQLSTATE 读不到，只能按消息子串分类。
    产出字段仍然只含**类别级**文案（`MESSAGES` / `LLM_HINT_BY_CLASS` 取自 W2D，
    本文件不写第二份）—— sqlite 的原文含表名/列名（N-11 禁的是回灌它）。
    """
    text = str(exc).lower()
    error_class = next((cls for sig, cls in _SQLITE_SIGNATURES if sig in text), None)
    if error_class is None:
        # 与 PG 版同款兜底：未登记签名不猜，按 syntax 家族（"5 个 repair 类呈现一致"）。
        error_class = "syntax_error"
    return ExecError(
        error_class=error_class,
        pgcode=None,  # ⚠️ 不伪造 SQLSTATE：那会被下游当成 PG 错误码做统计
        message=MESSAGES[error_class],
        llm_hint=LLM_HINT_BY_CLASS[error_class],
    )


def to_sqlite_sql(sql: str) -> str:
    """把在线契约的 `%(name)s` 占位符改写成 sqlite 的 `:name`（只动占位符，不碰值）。

    ⚠️ 不处理**字符串字面量内部**出现的 `%(x)s`（那是 gate1 R15 之外的极端形态）。
    在线路径由 psycopg 消费 `%(name)s`，本函数只在评测侧存在，故不改动任何在线代码。
    """
    return _PSYCOPG_PARAM_RE.sub(r":\1", sql)


def open_sandbox_connection(
    db_path: str,
    *,
    tenant_id: str | None,
    tenant_scoped_physicals: Mapping[str, str],
) -> sqlite3.Connection:
    """打开**只读**沙箱连接，并按租户建边界视图。

    `tenant_scoped_physicals` = `{物理表名: tenant 列名}`（由 `harness` 从语义包
    `tenant_scoped=true` 的资产导出 —— 不在本文件硬编码第二份清单）。

    实现要点：
    ① `mode=ro` URI：源库**不可能**被写（评测对 `data/ecom_sandbox.db` 零改动，
       也零物化副本 —— 440 MB 的库不做无谓复制）；
    ② 视图建在 **TEMP** schema：SQLite 解析非限定名时 TEMP 优先于 main，
       于是 `FROM v_order_paid` 自动命中租户过滤视图，而 `v_region` / `v_dim_date`
       （`tenant_scoped=false`）不建视图 → 落回 main 的公共维表；
    ③ `tenant_id=None` → 不建视图（一致性测试① 的"手写含租户谓词"那一侧需要**未隔离**
       的连接，才能与 W1A 的 `tenant_wrap` 路径同形比对）。
    """
    con = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = None  # 必须是 tuple：`_execute_and_collect` 按 `tuple(row)` 消费
    if tenant_id is not None:
        # ⚠️ `CREATE VIEW` 的 DDL **不接受参数绑定**（实测 `parameters are not allowed in
        # views`：视图存的是 SQL 文本，绑定值无处安放）⇒ 只能拼字面量。
        # 拼接的安全前提 = 下面的严格白名单（`T_A` 形态的租户码，来自冻结集与 dim_tenant）。
        if not re.fullmatch(r"[A-Za-z0-9_-]+", tenant_id):
            raise ValueError(f"eval_tenant 不符合租户码字符集，拒绝拼进视图 DDL：{tenant_id!r}")
        for physical, column in tenant_scoped_physicals.items():
            # 表/列名同样来自语义包（受控来源），仍做标识符白名单校验。
            for ident in (physical, column):
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident):
                    raise ValueError(f"语义包资产标识符非法，拒绝建视图：{ident!r}")
            con.execute(
                f"CREATE TEMP VIEW {physical} AS SELECT * FROM main.{physical} "
                f"WHERE {column} = '{tenant_id}'"
            )
    return con


class _AsyncCursor:
    """`sqlite3.Cursor` 的**异步外壳**（`_execute_and_collect` 认的是 psycopg 协议）。

    只实现在线路径用到的四个面：`execute` / `description` / `fetchmany` / `close`。
    执行放在事件循环里**同步**跑（评测是 §C.6.1 的串行批跑，不与其他请求抢循环）——
    代价写进模块 docstring 的"性能不可外推"。
    """

    def __init__(self, con: sqlite3.Connection, timeout_ms: int) -> None:
        self._con = con
        self._timeout_ms = timeout_ms
        self._cur: sqlite3.Cursor | None = None
        self._deadline = 0.0

    async def __aenter__(self) -> _AsyncCursor:
        self._cur = self._con.cursor()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    # -- psycopg ServerCursor 面 -------------------------------------------

    @property
    def description(self) -> Any:
        """适配成 **psycopg3 `Column` 的形状**（`.name` 有主，不是裸下标）。

        🔴 为什么不是洁癖（实测）：`PgSqlExecutor._execute_and_collect` 写的是
        `tuple(d.name for d in scur.description)`，而 `sqlite3` 给裸 7 元组 ⇒
        `AttributeError: 'tuple' object has no attribute 'name'`，且它被
        `except BaseException` 分支重抛成"执行层内部错误"（不是 SQL 错误）——
        红队批次 15 条执行用例**全部**因此没跑到一行。适配器必须补齐驱动契约，
        而不是去改在线代码（那是 W2D 的件）。
        """
        if self._cur is None or self._cur.description is None:
            return None
        return tuple(ColumnDesc(*row) for row in self._cur.description)

    async def execute(self, sql: str, params: Any) -> None:
        assert self._cur is not None, "游标未打开"
        self._deadline = time.monotonic() + self._timeout_ms / 1000
        # 每次执行装一次进度回调（超时打断的唯一手段：sqlite 没有服务端 statement_timeout）
        self._con.set_progress_handler(self._abort_after_deadline, _PROGRESS_OPS)
        try:
            self._cur.execute(sql, params if params else [])
        except sqlite3.Error as exc:
            raise ExecFailure(
                classify_sqlite_error(exc),
                detail={"driver": "sqlite3", "sandbox": True},
            ) from exc
        finally:
            self._con.set_progress_handler(None, 0)

    async def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        assert self._cur is not None, "游标未打开"
        return list(self._cur.fetchmany(size))

    async def close(self) -> None:
        self._con.set_progress_handler(None, 0)
        if self._cur is not None:
            self._cur.close()
            self._cur = None

    def _abort_after_deadline(self) -> int:
        """返回非 0 → SQLite 立即中断本次执行（抛 `OperationalError: interrupted`）。"""
        return 1 if time.monotonic() > self._deadline else 0


class _RawShim:
    """psycopg **原始连接**的最小替身（`_execute_and_collect` 只经 `cursor()` 用它）。"""

    def __init__(self, con: sqlite3.Connection, timeout_ms: int) -> None:
        self._con = con
        self._timeout_ms = timeout_ms

    def cursor(self, name: str | None = None, **kwargs: Any) -> _AsyncCursor:
        # `name=` 是服务端命名游标的形态（PG 专属）；SQLite 无此概念，忽略 ——
        # 这正是缺口表"驱动层"那一行的内容，不假装实现了它。
        return _AsyncCursor(self._con, self._timeout_ms)


class SqliteEvalExecutor(PgSqlExecutor):
    """`SqlExecutorPort` 的沙箱实现：**在线采集/归一化/脱敏/指纹管线 + SQLite I/O**。

    ⚠️ 连接按 `(tenant_id)` 缓存复用：一条连接一份 TEMP 视图，逐用例重开会把
    440 MB 库的页缓存反复打冷（实测单次全批 124 条 execute 用例）。
    租户隔离因此是**连接级**的，与生产的"会话级 GUC + RLS"同构（见模块 docstring §二）。
    """

    def __init__(
        self,
        *,
        db_path: str,
        mask: MaskPort,
        settings: Settings,
        tenant_scoped_physicals: Mapping[str, str],
        bundle: SemanticBundlePort | None = None,
    ) -> None:
        # `analytics_engine=None`：本类的 I/O 不经 SQLAlchemy/psycopg（PG 侧专用）。
        # 传 None 是**刻意的** —— 一旦哪条路径回到 `self._engine`，它会以
        # `AttributeError` 当场暴露，而不是静默连到生产库。
        super().__init__(None, mask, settings, bundle=bundle)  # type: ignore[arg-type]
        self._db_path = db_path
        self._tenant_scoped = dict(tenant_scoped_physicals)
        self._conns: dict[str, sqlite3.Connection] = {}

    # ------------------------------------------------------------------
    # SqlExecutorPort.fetch
    # ------------------------------------------------------------------

    async def fetch(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        statement_timeout_ms: int,
        effective_limit: int | None = None,
    ) -> ResultSet:
        """与在线 `fetch` 同序：行数硬上限夹紧 → 超时校验 → 采集管线（逐字复用）。

        ⚠️ 唯一被替换的是 `_controlled_session`；`_execute_and_collect` 是
        `PgSqlExecutor` 的本尊方法（ADR-18 的复用点）。
        """
        if statement_timeout_ms <= 0:
            raise ValueError(f"statement_timeout_ms 必须为正（毫秒）：{statement_timeout_ms}")
        if max_rows > self._settings.EXEC_MAX_ROWS:
            max_rows = self._settings.EXEC_MAX_ROWS

        con = self._connection_for(ctx.tenant_id)
        raw = _RawShim(con, statement_timeout_ms)
        memory_budget = self._settings.EXEC_MAX_MEMORY_MB * 1024 * 1024
        return await self._execute_and_collect(
            raw,
            to_sqlite_sql(sql),
            dict(params or {}),
            ctx,
            max_rows=max_rows,
            effective_limit=effective_limit,
            memory_budget=memory_budget,
        )

    # ------------------------------------------------------------------
    # EXPLAIN：沙箱无计划 JSON（§17.4）
    # ------------------------------------------------------------------

    async def explain(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        statement_timeout_ms: int,
    ) -> None:
        """恒 `None` → `run_gate3` 判 `SKIPPED(dialect_no_explain_json)`。

        抛异常会得到 `WARN`（成本闸门"报错不阻断"），那会让报告读成
        "EXPLAIN 失败过一次"而不是"该能力在沙箱不存在"—— 语义与 §17.4 不一致，故返回 None。
        """
        return None

    async def cancel(self, task_id: str) -> bool:
        """沙箱无后端 PID 可取消（在线走 `pg_cancel_backend`）→ 恒 `False`（幂等语义保持）。

        超时由 `set_progress_handler` 在 `execute` 内部打断，不依赖本方法。
        """
        return False

    # ------------------------------------------------------------------
    # 连接治理
    # ------------------------------------------------------------------

    def _connection_for(self, tenant_id: str) -> sqlite3.Connection:
        con = self._conns.get(tenant_id)
        if con is None:
            con = open_sandbox_connection(
                self._db_path,
                tenant_id=tenant_id,
                tenant_scoped_physicals=self._tenant_scoped,
            )
            self._conns[tenant_id] = con
        return con

    def close(self) -> None:
        for con in self._conns.values():
            con.close()
        self._conns.clear()
