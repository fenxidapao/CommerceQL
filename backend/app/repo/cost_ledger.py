"""`cost_ledger` 的落库 sink —— `CostLedgerSink` Protocol（W3A `llm/budget.py`）的 DB 实现。

归属窗口：W1B（docs/08 §4.1：`app/repo/**`）。表结构 = 迁移 `0004`（列与 `CostEntry`
逐字段对齐，契约单测锁定双向）。

## ⚠️ 为什么本文件**不 import** `app.llm`（R-DEP-2 是硬契约，不是纪律）

`.importlinter` R-DEP-2 明文：`app.repo` ∈ 禁止 import `app.llm` 的模块清单。
而 `CostLedgerSink` / `CostEntry` 定义在 `app/llm/budget.py`（W3A，L1）——repo 是 L0。
处理方式：**本地声明结构化 Protocol**（`LedgerEntryProto` + `CostLedgerSinkProto`），
Python Protocol 是结构化子类型 —— W4 装配时把 `CostEntry` 传进来**天然兼容**，
mypy 在调用点（可 import 两边的层）做结构校验；"CostEntry ↔ 本地字段契约"的一致性
由离线契约测试钉死（tests/ 可以 import 任意层，那正是它的职责）。
W3A 在 `budget.py` 里写"按本类写插入语句即可"的期望，以这个形态兑现。

## 为什么是"单条同步连接 + 失败重连"（方案已由用户采纳，2026-09-17）

W3A 的 Protocol 是**同步**三方法（`record` / `tenant_spent_cny` / `global_spent_cny`），
且网关在**异步上下文里直接同步调用**（`llm/__init__.py` 的 `preflight`/`settle`）。
三个候选里选了最不对抗既有约束的一个：

| 方案 | 结论 |
|---|---|
| 复用 metadata 异步 engine | ❌ Protocol 是同步的，sync 方法里跑不了 async engine |
| 新建第 4 个连接池 | ❌ 正面违反"三池唯一装配点"（`pools.py` / 07 §8.1 / N-14）的字面与算术 |
| **每调用短连接** | ⚠️ 每次 LLM 调用 3 次 TCP+auth 握手（预检 2 查 + 结算 1 写），纯浪费 |
| **本实现：单条专用同步连接** | ✅ P0 单进程单事件循环 → sink 调用天然串行，一条连接够用；失败重连一次，`connect_timeout=2` 封顶挂死风险（U-53 的直接教训） |

**已登记的取舍（如实，不隐瞒）**：

1. **这是第 4 个长连 DB 资源**（虽然不是"池"）。07 §8.1 的三池算术（80 连接）不含它，
   已在 `reports/w1b/RELAY.md` 向架构登记；若架构裁定改回"每次短连接"或扩 Protocol 为
   async（动 W3A 文件），本类只改 `_connection()` 一个方法。
2. **同步 DB 调用会阻塞事件循环**：实测单条 SQL 在本机 PG ≈1ms，每次 LLM 调用 3 条
   ≈3ms —— 相对 LLM 1.5–45s 的延迟是噪声。若未来出现高频小调用场景，应重开方案。
3. **失败语义 = fail loud**：sink 抛错不做内部静默重试超过一次 —— 账本写失败意味着
   预算熔断失真，宁可让调用方（网关）看见并决定，也不悄悄丢一笔账。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

import psycopg

from app.repo.dsn import to_libpq_conninfo

__all__ = ["CostLedgerSinkProto", "DbCostLedgerSink", "LedgerEntryProto"]


# ============================================================================
# 本地结构化契约（与 `app/llm/budget.py` 的 `CostEntry` / `CostLedgerSink` 逐成员
# 同构 —— 不 import 是 R-DEP-2 的硬约束；一致性由离线契约测试钉死）
# ============================================================================

@runtime_checkable
class LedgerEntryProto(Protocol):
    """一行计量的**结构**（= `CostEntry` 的落库字段；`tokens_estimated`/`price_guess`
    是 W3A 的非落库标记，本 Protocol 刻意不含 —— 多余属性不影响结构兼容）。"""

    @property
    def entry_id(self) -> str: ...

    @property
    def task_id(self) -> str: ...

    @property
    def tenant_id(self) -> str: ...

    @property
    def user_id(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...

    @property
    def cache_hit_tokens(self) -> int: ...

    @property
    def cost_cny(self) -> Decimal: ...

    @property
    def is_peak(self) -> bool: ...

    @property
    def created_at(self) -> datetime: ...


@runtime_checkable
class CostLedgerSinkProto(Protocol):
    """与 W3A `CostLedgerSink` 同构的 sink 面（三方法，签名逐字一致）。"""

    def record(self, entry: LedgerEntryProto) -> None: ...

    def tenant_spent_cny(self, tenant_id: str, day: date) -> Decimal: ...

    def global_spent_cny(self, day: date) -> Decimal: ...


#: 计费时区名。与 `llm/budget.py::BILLING_TZ`（Asia/Shanghai，PRD §12.3）必须同值 ——
#: ⚠️ 不 import 它（R-DEP-2），改为**构造参数**：默认值即 PRD 的值，W4 装配时可显式传入；
#: 两处漂移由集成测试的日界用例钉住。
_DEFAULT_BILLING_TZ: Final[str] = "Asia/Shanghai"

#: 单次连接建立的上限（秒）。U-53：不带它的连接尝试会无限挂起，连累 `close()` 等满 clamp。
_CONNECT_TIMEOUT_S: Final[int] = 2

_INSERT_SQL: Final[str] = (
    "INSERT INTO app.cost_ledger "
    "(entry_id, task_id, tenant_id, user_id, model, "
    "input_tokens, output_tokens, cache_hit_tokens, cost_cny, is_peak, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

#: 日界 = 计费时区（PRD §12.3 高峰定义是北京时间）下的自然日。
#: `timestamptz AT TIME ZONE %s` → 该时区的 naive local time → 取 date。
_TENANT_SPENT_SQL: Final[str] = (
    "SELECT COALESCE(SUM(cost_cny), 0)::numeric FROM app.cost_ledger "
    "WHERE tenant_id = %s AND (created_at AT TIME ZONE %s)::date = %s"
)
_GLOBAL_SPENT_SQL: Final[str] = (
    "SELECT COALESCE(SUM(cost_cny), 0)::numeric FROM app.cost_ledger "
    "WHERE (created_at AT TIME ZONE %s)::date = %s"
)


def _conninfo_for(settings_dsn: str, *, connect_timeout: int = _CONNECT_TIMEOUT_S) -> str:
    """`DATABASE_URL`（SQLAlchemy 形态，项目约定）→ 带 `connect_timeout` 的 libpq 形态。

    转换走 `repo/dsn.py` 唯一入口（DSN 只有一个出处）；查询串已有参数则追加。
    """
    libpq = to_libpq_conninfo(settings_dsn)
    sep = "&" if "?" in libpq else "?"
    return f"{libpq}{sep}connect_timeout={connect_timeout}"


class DbCostLedgerSink:
    """`CostLedgerSink` 的落库实现（同步）。

    ⚠️ 不是线程安全的（P0 单进程单事件循环，sink 调用天然串行 —— 见模块 docstring）。
    扩多 worker 时这整层要按 W3A 在 `InMemoryCostLedgerSink` 里登记的同一结论重做。
    """

    def __init__(
        self,
        settings_dsn: str,
        *,
        billing_tz: str = _DEFAULT_BILLING_TZ,
    ) -> None:
        """`settings_dsn` = `DATABASE_URL` 的原值（SQLAlchemy 形态；转换在本类内部做）。"""
        self._conninfo = _conninfo_for(settings_dsn)
        self._billing_tz = billing_tz
        self._conn: psycopg.Connection | None = None

    # ------------------------------------------------------------------
    # 连接管理（单连接 + 一次重连）
    # ------------------------------------------------------------------

    def _connection(self) -> psycopg.Connection:
        """取可用连接；断了就重连（含首次）。连接失败**如实抛出**，不吞。"""
        if self._conn is not None and not self._conn.closed:
            return self._conn
        self._conn = psycopg.connect(self._conninfo)  # connect_timeout 已在 conninfo 里
        self._conn.autocommit = True  # 每条计量/聚合即时可见 —— 预算判定读的就是最新累计
        return self._conn

    def _run(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        """执行一条语句；遇连接级故障**重连一次**再试一次，第二次失败如实抛出。

        ⚠️ 只对 `OperationalError`（连接断/超时）重试 —— `UndefinedTable`、CHECK 违反等
        语义错误重试是掩盖 bug（迁移没跑就该炸得响）。
        """
        try:
            conn = self._connection()
        except psycopg.OperationalError:
            self._conn = None
            conn = self._connection()  # 第二次失败让它抛
        try:
            cur = conn.execute(sql, params)
            rows = cur.fetchall() if cur.description is not None else []
            cur.close()
            return rows
        except psycopg.OperationalError:
            # 连接可能在两次调用之间被服务端掐断：丢弃连接、重连、**重试一次**。
            # INSERT 重试的前提是第一次没提交成功 —— autocommit 下连接断即回滚，
            # 同一 entry_id 主键不会撞（幂等性由 PK 兜底）。
            self._conn = None
            conn = self._connection()
            cur = conn.execute(sql, params)
            rows = cur.fetchall() if cur.description is not None else []
            cur.close()
            return rows

    # ------------------------------------------------------------------
    # CostLedgerSinkProto 的三个方法（签名逐字对齐 W3A 的 Protocol）
    # ------------------------------------------------------------------

    def record(self, entry: LedgerEntryProto) -> None:
        """写一行计量。列集 = CostEntry 落库字段（契约单测锁定），多/少字段即 DB 报错。"""
        self._run(
            _INSERT_SQL,
            (
                entry.entry_id,
                entry.task_id,
                entry.tenant_id,
                entry.user_id,
                entry.model,
                entry.input_tokens,
                entry.output_tokens,
                entry.cache_hit_tokens,
                entry.cost_cny,
                entry.is_peak,
                entry.created_at,
            ),
        )

    def tenant_spent_cny(self, tenant_id: str, day: date) -> Decimal:
        rows = self._run(_TENANT_SPENT_SQL, (tenant_id, self._billing_tz, day))
        value = rows[0][0]
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def global_spent_cny(self, day: date) -> Decimal:
        rows = self._run(_GLOBAL_SPENT_SQL, (self._billing_tz, day))
        value = rows[0][0]
        return value if isinstance(value, Decimal) else Decimal(str(value))

    # ------------------------------------------------------------------
    # 生命周期（Protocol 之外的附加方法 —— W4 装配时在 shutdown 里调用）
    # ------------------------------------------------------------------

    def close(self) -> None:
        """释放连接。⚠️ W4 接线时必须挂进 lifespan 关闭段（`main.py` 的资源释放区）。"""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None
