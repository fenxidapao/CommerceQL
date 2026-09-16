"""健康探针的离线断言（附录 A §A.8.1 / N-21 / 07 §18.2）。

归属窗口：W1B。

## ⚠️ 这个文件证明什么、不证明什么

| 断言 | 在这里（离线） | 在 `tests/integration/`（连库/连 Redis） |
|---|---|---|
| 探针判定逻辑（表族齐否 / `PING` 通否） | ✅ | — |
| `build_probe_table` **只接硬依赖**、且接完之后 readiness 全集恰好齐 | ✅（结构断言） | — |
| 探针在**真实** PG / Redis 上返回 healthy | ❌ | ✅ |

结构断言是这里最有价值的一条：它把"软依赖不许进 readiness"（N-21）从一句纪律
变成**可执行的算式** —— 三个硬依赖减去 W2A 的那一个，多一个少一个都红。
"""

from __future__ import annotations

import inspect
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import psycopg_pool
import pytest
from psycopg_pool import AsyncConnectionPool

from app.core.contracts import HealthProbeResult
from app.core.enums import (
    DEGRADABLE_DEPENDENCIES,
    DEPENDENCY_KIND,
    READINESS_DEPENDENCIES,
    Dependency,
    DependencyKind,
)
from app.graph.build import CheckpointSetupOutcome, ensure_checkpoint_schema
from app.repo.health import (
    CHECKPOINT_TABLE_FAMILY,
    build_probe_table,
    probe_checkpointer,
    probe_metadata_db,
    probe_redis,
)
from app.repo.pools import POOL_ACQUIRE_TIMEOUT_S

from ._redis_fake import FakeRedis

#: 打不通的池会由 `psycopg_pool` 在**自己的** logger 上反复打英文错误
#: （`error connecting in 'pool-1': ...`）。本文件的第 6 节刻意使用打不通的真池，
#: 因此必须把它按下去 —— 否则一条用例能刷出上百行噪音，把真正的失败信息埋掉。
logging.getLogger("psycopg.pool").setLevel(logging.CRITICAL)


class _Rows:
    """`execute(...)` 的返回值：够 `fetchone()` / `first()` 用即可。"""

    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _FakeConn:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row
        self.executed: list[Any] = []

    async def execute(self, sql: Any, params: Any = None) -> _Rows:
        self.executed.append(sql)
        return _Rows(self._row)

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    # SQLAlchemy 的 `async with engine.connect()` 里还会调 `conn.scalar(...)`
    async def scalar(self, sql: Any, params: Any = None) -> Any:
        self.executed.append(sql)
        return None if self._row is None else self._row[0]


class _FakeEngine:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row
        self.conn = _FakeConn(row)

    def connect(self) -> _FakeConn:
        return self.conn


class _FakePool:
    """够 `probe_checkpointer` 用的最小池替身。

    ⚠️ `connection()` 是**方法**（不是属性）—— `psycopg_pool` 3.x 的用法。
    替身若把它写成属性，用例会通过，而生产代码会在第一次探针时 `TypeError`。

    ⚠️ 必须接受并**记录** `timeout` 关键字：探针的可用性全靠它
    （不给 timeout 时 `psycopg_pool` 的默认值是 30s，实测让 `/healthz/ready` 35.8s 才作答）。
    替身若不接受该参数，用例会在第一次调用时 `TypeError` 而**恰好**暴露漏传 ——
    但那只在"有人刚好改了实现"时才会红；下面另有专门断言在**任何**情况下都盯着它。
    """

    def __init__(self, row: tuple[Any, ...] | None, *, exc: Exception | None = None) -> None:
        self._row = row
        self._exc = exc
        self.conn = _FakeConn(row)
        self.acquire_timeouts: list[float | None] = []

    @asynccontextmanager
    async def connection(self, timeout: float | None = None) -> Any:
        self.acquire_timeouts.append(timeout)
        if self._exc is not None:
            raise self._exc
        yield self.conn


# ---------------------------------------------------------------------------
# 1. ★ 结构断言：接哪三个、以及接完之后 readiness 恰好齐
# ---------------------------------------------------------------------------

def test_probe_table_covers_exactly_the_three_hard_dependencies_owned_by_w1b() -> None:
    """本窗口接的三个 + W2A 的语义包 == readiness 全集。

    这条断言同时挡住三种漂移：
    ① 少接一个（例如漏了 Redis）→ 左集变小 → 红；
    ② 多接一个软依赖（`LLM` / `EMBEDDING`）→ 左集变大 → 红（**这是 N-21 的机器化**）；
    ③ 上游改了 `READINESS_DEPENDENCIES`（例如把某个软依赖误标成硬）→ 也红。
    """
    table = build_probe_table(
        metadata_engine=_FakeEngine((1, "commerceql-metadata", "ecom")),  # type: ignore[arg-type]
        checkpoint_pool=_FakePool((1, len(CHECKPOINT_TABLE_FAMILY))),  # type: ignore[arg-type]
        redis_client=FakeRedis(),  # type: ignore[arg-type]
    )
    assert set(table) | {Dependency.SEMANTIC_BUNDLE_LOADED} == set(READINESS_DEPENDENCIES)


def test_probe_table_never_contains_soft_dependencies() -> None:
    """★ 软依赖**永不**出现在探针表里（N-21：把"降级"变成"不可用"是这里唯一的错法）。"""
    table = build_probe_table(
        metadata_engine=_FakeEngine((1, "a", "ecom")),  # type: ignore[arg-type]
        checkpoint_pool=_FakePool((1, 4)),  # type: ignore[arg-type]
        redis_client=FakeRedis(),  # type: ignore[arg-type]
    )
    assert not (set(table) & set(DEGRADABLE_DEPENDENCIES))
    assert {Dependency.LLM, Dependency.EMBEDDING}.isdisjoint(table)


# ---------------------------------------------------------------------------
# 2. 元数据库探针
# ---------------------------------------------------------------------------

async def test_metadata_probe_healthy_and_reports_application_name() -> None:
    """healthy 时 detail 里必须带 `application_name` —— 它是 T-A1 观测手段本身，
    让它出现在健康检查里，等于把"这条连接属于哪个池"变成运维面上随时可读的事实。"""
    probe = probe_metadata_db(_FakeEngine((1, "commerceql-metadata", "ecom")))  # type: ignore[arg-type]
    result = await probe()
    assert isinstance(result, HealthProbeResult)
    assert result.healthy is True
    assert result.dependency is Dependency.METADATA_DB
    assert result.kind is DependencyKind.HARD
    assert "commerceql-metadata" in (result.detail or "")


async def test_metadata_probe_returns_unhealthy_on_missing_row() -> None:
    probe = probe_metadata_db(_FakeEngine(None))  # type: ignore[arg-type]
    result = await probe()
    assert result.healthy is False


# ---------------------------------------------------------------------------
# 3. checkpointer 探针
# ---------------------------------------------------------------------------

async def test_checkpointer_probe_healthy_when_table_family_is_complete() -> None:
    probe = probe_checkpointer(_FakePool((1, len(CHECKPOINT_TABLE_FAMILY))))  # type: ignore[arg-type]
    result = await probe()
    assert result.healthy is True
    assert result.dependency is Dependency.CHECKPOINTER


async def test_checkpointer_probe_unhealthy_when_setup_never_ran() -> None:
    """★ 表族不齐 → **不健康**，而不是"池能连上就算健康"。

    只探连通性的后果很具体：忘了跑 `setup()` 时探针全绿，而图一执行就抛 `UndefinedTable` ——
    "探针说没事、用户说全挂"是最难排查的一类组合。
    """
    probe = probe_checkpointer(_FakePool((1, 0)))  # type: ignore[arg-type]
    result = await probe()
    assert result.healthy is False
    assert "setup()" in (result.detail or "")


async def test_checkpointer_probe_does_not_swallow_pool_errors() -> None:
    """池没开（`PoolClosed`）必须**向上抛**，不得吞成 `healthy=False`。

    ⚠️ 这是刻意的设计决定，值得写进用例：吞掉异常会让"池根本没开"与
    "池开着但表族不齐"得到同一个 `healthy=False`，而两者的修法完全不同
    （前者是装配顺序问题、后者是迁移问题）。异常由端点层的统一处理
    写成 `detail="探针异常：PoolClosed"` —— 归因信息反而更准。
    """
    probe = probe_checkpointer(_FakePool(None, exc=RuntimeError("PoolClosed")))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="PoolClosed"):
        await probe()


# ---------------------------------------------------------------------------
# 4. Redis 探针
# ---------------------------------------------------------------------------

async def test_redis_probe_healthy() -> None:
    probe = probe_redis(FakeRedis())  # type: ignore[arg-type]
    result = await probe()
    assert result.healthy is True
    assert result.dependency is Dependency.REDIS
    assert result.kind is DependencyKind.HARD, "Redis 是**硬依赖**：锁与限流挂掉不是降级（附录 A §A.8.1）"


async def test_redis_probe_returns_unhealthy_when_ping_is_false() -> None:
    class _LyingRedis(FakeRedis):
        async def ping(self) -> bool:
            return False

    probe = probe_redis(_LyingRedis())  # type: ignore[arg-type]
    result = await probe()
    assert result.healthy is False


# ---------------------------------------------------------------------------
# 5. 表族清单本身
# ---------------------------------------------------------------------------

def test_checkpoint_table_family_matches_langgraph_schema() -> None:
    """表族清单是**实测得来**的（本机跑完 `setup()` 后读 `pg_class`）。

    ⚠️ 这条断言的作用不是"证明清单对"，而是**把清单钉在一个地方**：
    `langgraph` 升级若改了表名，这里会红 —— 而如果没有这条，
    探针会一直报"表族不齐"（healthy=false），看起来像"迁移没跑"，
    实际是依赖升级改了 schema。两者的排查方向完全不同。
    """
    assert set(CHECKPOINT_TABLE_FAMILY) == {
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    }
    assert DEPENDENCY_KIND[Dependency.CHECKPOINTER] is DependencyKind.HARD


# ---------------------------------------------------------------------------
# 6. ★ 可用性：探针与启动检查**不得无限等待**
#
# 这一节是 2026-09-16 实测换来的，不是预防性洁癖。实测（依赖不可达）：
#   · `ensure_checkpoint_schema()` 卡 30.65s → 启动被拖住；
#   · `probe_checkpointer()` 卡 30s     → `/healthz/ready` 端到端 35.8s。
# 而附录 D 给 `/healthz/ready` 的平台预算只有 5s（`healthcheck.timeout`），
# 于是**"诚实的 503"根本传不到消费者手里**，只留下一次超时；
# 且每次探针白占一个 worker 达 30s —— 健康端点自己变成可用性风险。
# ---------------------------------------------------------------------------

def test_pool_acquire_timeout_fits_inside_the_platform_probe_budget() -> None:
    """★ 取值必须落在附录 D 给的平台预算之内，且**远小于**池的默认等待。

    ⚠️ 这里断言的是**不变量**（区间），不是"等于 2.0"：
    锁死字面值会让"调参"变成改测试，反而看不出它是否还在预算内。
    真正要防的两件事各有一条：
    · 有人把它调回默认（≥30s）→ 第二个断言红；
    · 有人把它调成"和平台预算一样大"→ 第一个断言红（那样 `_collect` 串行的三个依赖必然超时）。

    ⚠️ 默认值**从签名里读**，不写死 30：写死的话，依赖某天改了默认值，
    这条断言会变成"检查一个早已不存在的对手"，静默失效。
    """
    default_acquire_timeout = inspect.signature(psycopg_pool.ConnectionPool.__init__).parameters[
        "timeout"
    ].default

    assert 0 < POOL_ACQUIRE_TIMEOUT_S < 5.0, (
        "取连接的上限必须严格小于附录 D 的 5s 平台探针预算，"
        "否则 `/healthz/ready` 会在平台侧表现为超时而不是一次诚实的 503"
    )
    assert default_acquire_timeout > POOL_ACQUIRE_TIMEOUT_S, (
        f"取连接上限（{POOL_ACQUIRE_TIMEOUT_S}s）没有比池的默认等待"
        f"（{default_acquire_timeout}s）小 —— 等于没设"
    )


async def test_checkpointer_probe_actually_passes_the_bounded_timeout() -> None:
    """★ 光是**定义了**常量没用 —— 得确认它真的被传下去了。

    `psycopg_pool` 的 `timeout` 是**调用点**参数：`pool.connection()` 不给就用默认 30s。
    所以"常量存在"与"等待被限住"是两件事，中间隔着一行容易漏掉的显式传参。
    """
    pool = _FakePool((None, 0))
    await probe_checkpointer(pool)()  # type: ignore[arg-type]
    assert pool.acquire_timeouts == [POOL_ACQUIRE_TIMEOUT_S], (
        f"探针没有把有界超时传给池（收到的是 {pool.acquire_timeouts}）—— 默认值 30s 会生效"
    )


async def test_ensure_checkpoint_schema_actually_passes_the_bounded_timeout() -> None:
    """★ 启动路径同理 —— 光有常量不算数，要看**调用点**有没有传。

    ⚠️ 这条用例是被**负向对照**逼出来的：第一版把池构造器写成
    `AsyncConnectionPool(..., timeout=POOL_ACQUIRE_TIMEOUT_S)`，于是
    "把 `_count_present_checkpoint_tables` 里的 `timeout=` 删掉"**测不出来** ——
    池的默认值恰好也是 2s，用例照样绿。**通过了一个与被测对象无关的原因。**
    → 凡"调用点参数"类断言，替身/夹具都**不得**提供同一个参数的值，
    否则测的是夹具的配置，不是代码的行为。
    """
    pool = _FakePool((len(CHECKPOINT_TABLE_FAMILY),))
    outcome = await ensure_checkpoint_schema(pool)  # type: ignore[arg-type]
    assert outcome is CheckpointSetupOutcome.ALREADY_PRESENT
    assert pool.acquire_timeouts == [POOL_ACQUIRE_TIMEOUT_S], (
        f"启动期表族检查没有把有界超时传给池（收到的是 {pool.acquire_timeouts}）—— 默认 30s 会生效"
    )


async def test_checkpointer_probe_cannot_stall_on_an_unreachable_pool() -> None:
    """★ 真池 + 打不通的地址：探针**必须快速失败**。

    用**真 `AsyncConnectionPool`**（不是替身）：本用例要验的恰恰是替身验不了的那部分 ——
    "psycopg_pool 在拿不到连接时到底等多久"。替身只会立刻返回，永远不会暴露这个。

    ⚠️ **刻意不给池构造器传 `timeout`** —— 必须让它带着库的默认值（30s）跑。
    传了的话，本用例就变成在验证"池被配成了 2s"，而**看不见调用点漏传**这件事
    （负向对照已实证：那样注入 `pool.connection()` 仍然全绿）。

    地址取 `127.0.0.1:1`：TCP 立即被拒（`ECONNREFUSED`），所以耗时**全部**来自池的等待逻辑，
    不会被 DNS / 防火墙的偶发延迟污染 —— 用例要测的是"我们的上限生效了"，
    不是"这台机器的网络快不快"。
    """
    pool = AsyncConnectionPool(
        conninfo="postgresql://app_rw:placeholder@127.0.0.1:1/ecom",
        min_size=0,
        max_size=1,
        open=False,
    )
    await pool.open(wait=False)
    try:
        started = time.monotonic()
        with pytest.raises(Exception) as ei:
            await probe_checkpointer(pool)()
        elapsed = time.monotonic() - started
    finally:
        await pool.close()

    assert isinstance(ei.value, psycopg_pool.PoolTimeout), (
        f"打不通时抛出的应是 PoolTimeout（= 我们的上限生效了），实际 {type(ei.value).__name__}: {ei.value}"
    )
    assert elapsed < 5.0, (
        f"探针在打不通的池上等了 {elapsed:.2f}s —— 已超出附录 D 的 5s 平台预算，"
        f"`/healthz/ready` 会表现为超时而非诚实的 503"
    )


async def test_ensure_checkpoint_schema_returns_unreachable_fast_instead_of_blocking() -> None:
    """★ 启动路径同理：连不上时**快速**返回 `UNREACHABLE`，而不是把启动卡住 30s。

    ⚠️ 这条同时钉住两件事，缺一不可：
    · 结果是 `UNREACHABLE`（**不是抛异常**）—— 库没起来不该让进程起不来（07 §18.2）；
    · 耗时 < 5s —— 否则 `start_period: 60s` 的启动预算被一次池等待吃掉一半。

    ⚠️ 同样**刻意不给池构造器传 `timeout`**，理由见上一条。
    """
    pool = AsyncConnectionPool(
        conninfo="postgresql://app_rw:placeholder@127.0.0.1:1/ecom",
        min_size=0,
        max_size=1,
        open=False,
    )
    await pool.open(wait=False)
    try:
        started = time.monotonic()
        outcome = await ensure_checkpoint_schema(pool)
        elapsed = time.monotonic() - started
    finally:
        await pool.close()

    assert outcome is CheckpointSetupOutcome.UNREACHABLE
    assert elapsed < 5.0, f"启动期表族检查等了 {elapsed:.2f}s（上限 {POOL_ACQUIRE_TIMEOUT_S}s 未生效）"
