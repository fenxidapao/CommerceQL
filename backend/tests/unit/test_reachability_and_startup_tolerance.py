"""「连不上」与「答了但不合格」的**区分**必须成立（`repo/reachability.py` + 启动断言的三态）。

归属窗口：W1B。

## ⚠️ 为什么单独立一个文件

`repo/reachability.py` 与本轮引入的 `Unreachable` 三态分支，在此文件建立前是
**零覆盖** —— 而它决定的正是"依赖没起来时服务能不能起来"。
这类"代码在、纪律写在 docstring 里、但没有任何东西盯着"的状态，
在本项目已经出现过两次（`tests/conftest.py` 的影子承诺、`test_audit_writer.py` 的缺失），
所以这里把证据立成文件而不是散在别处。

## 这个文件证明什么、不证明什么

| 断言 | 在这里（离线） | 在集成测试 |
|---|---|---|
| 「连不上」→ `PENDING`（**不是** `FAIL`） | ✅ 喂 `Unreachable` 即可覆盖 | — |
| 三个 `live_probes` 闭包**都**包了 `_guarded` | ✅ 真接线 + 替身 I/O | — |
| `psycopg.InterfaceError` **不**被当成「连不上」 | ✅ ★ 这条把 U-39 钉在"必须红"的一侧 | — |
| 真 DSN 打不通时端到端确实放行 | ❌ | ✅ |

★ 标的两条是本文件的主要价值：它们把两条**方向相反**的纪律都变成可执行断言 ——
"依赖不可达要放行"与"环境不兼容不许伪装成依赖不可达"。
只钉前者会让人把 `InterfaceError` 也吞掉（测试变绿、U-39 消失）；
只钉后者则会让 07 §18.4.1 要求的 `live=200` / `ready=503` 状态不可达。
"""

from __future__ import annotations

from typing import Any

import psycopg
import psycopg.errors
import psycopg_pool
import pytest
import redis.exceptions as redis_exc
import sqlalchemy.exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import AppEnv
from app.repo import startup_assertions as sa
from app.repo.reachability import (
    UNREACHABLE_ERROR_TYPES,
    Unreachable,
    is_unreachable,
    unreachable_from,
)
from app.repo.startup_assertions import (
    ANALYTICS_DSN_IS_READ_ONLY,
    AUDIT_LOG_APPEND_ONLY_ENFORCED,
    EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
    AssertionStatus,
    evaluate_analytics_is_read_only,
    evaluate_audit_append_only,
    evaluate_embedding_dim,
)

#: 复用启动断言用例里的 `Settings` 构造器（prod 下必须同时给齐 τ 三元组那条约束写在那里）。
#: ⚠️ 刻意 import 而不是复制：`APP_ENV=prod` 的构造规则是**同一个事实**，
#: 复制一份会让"prod 怎么构造"出现两处真相。
from .test_startup_assertions import _settings

# ---------------------------------------------------------------------------
# 1. 「连不上」的类型集合
# ---------------------------------------------------------------------------

def test_each_covered_driver_exception_is_recognised_as_unreachable() -> None:
    """四个类型各自都要被认出来 —— 漏一个是**静默**的（那条断言会以异常炸穿启动）。

    ⚠️ 用**真异常实例**，不用 `issubclass` 空跑：`is_unreachable` 的实现是 `isinstance`，
    而 `sqlalchemy.exc.OperationalError` 的构造签名与 psycopg 的完全不同
    （要 `(statement, params, orig)` 三个参数）—— 这里把三种构造形态都走一遍，
    顺带证明"能被真实抛出"。
    """
    cases = {
        "psycopg.OperationalError": psycopg.OperationalError("connection refused"),
        "sqlalchemy.exc.OperationalError": sa_exc.OperationalError(
            "SELECT 1", {}, psycopg.OperationalError("connection refused")
        ),
        "redis.exceptions.ConnectionError": redis_exc.ConnectionError("getaddrinfo failed"),
        # ⚠️ 实测它**不是** `ConnectionError` 的子类 —— 单列的理由就在这里。
        "redis.exceptions.TimeoutError": redis_exc.TimeoutError("timed out"),
    }
    for label, exc in cases.items():
        assert is_unreachable(exc), f"{label} 未被认成「连不上」—— 它会以异常炸穿启动路径而不是判 PENDING"


def test_subclasses_of_the_covered_types_are_also_covered() -> None:
    """子类必须被覆盖 —— 这是**实际会抛出**的那两个，不是边角。

    · `psycopg_pool.PoolTimeout`：拿不到池里的连接时抛的**就是**它
      （`probe_checkpointer` / 启动期表族检查都会撞上）。
    · `psycopg.errors.ConnectionTimeout`：`connect_timeout` 到点。
    两者实测都是 `psycopg.OperationalError` 的子类 —— 本用例把这个实测事实钉住。
    """
    assert is_unreachable(psycopg_pool.PoolTimeout("pool exhausted"))
    assert is_unreachable(psycopg.errors.ConnectionTimeout("connect timeout expired"))


def test_the_type_tuple_is_not_empty_and_is_exposed_as_a_single_source() -> None:
    """`UNREACHABLE_ERROR_TYPES()` 是唯一出处：`except` 子句与 `is_unreachable` 必须同源。

    若哪天有人只在 `except` 里加了一个类型、忘了加进 `is_unreachable`（或反之），
    两者会给出**不一致**的归类 —— 而症状是"同一件事时而放行时而炸"，最难排查。
    这里把"同源"实现成可执行断言：`is_unreachable(exc)` **必须恒等于**
    `isinstance(exc, UNREACHABLE_ERROR_TYPES())`，用一批覆盖/不覆盖两侧的实例逐一比对。

    ⚠️ 不逐个 `t("probe")` 构造实例：`sqlalchemy.exc.OperationalError` 要
    `(statement, params, orig)` 三个参数，按类型循环构造会在它身上 `TypeError`
    —— 那样这条用例测的是"驱动构造签名"，而不是"归类同源"。
    """
    types = UNREACHABLE_ERROR_TYPES()
    assert types, "类型集合为空会让「连不上」全部变成未捕获异常"
    for t in types:
        assert isinstance(t, type) and issubclass(t, BaseException), f"{t!r} 不是异常类型"

    probes = [
        psycopg.OperationalError("x"),
        sa_exc.OperationalError("x", {}, psycopg.OperationalError("x")),
        redis_exc.ConnectionError("x"),
        redis_exc.TimeoutError("x"),
        psycopg_pool.PoolTimeout("x"),
        psycopg.InterfaceError("x"),
        sa_exc.InterfaceError("x", {}, psycopg.InterfaceError("x")),
        ValueError("x"),
    ]
    for exc in probes:
        assert is_unreachable(exc) == isinstance(exc, types), (
            f"{type(exc).__name__} 在 `is_unreachable` 与类型集合两处得到了不同结论 —— 归类出现第二真相"
        )


# ---------------------------------------------------------------------------
# 2. ★ 「环境不兼容」**不得**伪装成「依赖不可达」
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        psycopg.InterfaceError("Psycopg cannot use the 'ProactorEventLoop' to run in async mode"),
        sa_exc.InterfaceError("SELECT 1", {}, psycopg.InterfaceError("bad event loop")),
    ],
    ids=["psycopg", "sqlalchemy"],
)
def test_interface_error_is_deliberately_not_treated_as_unreachable(exc: BaseException) -> None:
    """★★ 本文件最重要的一条：`InterfaceError` 必须**不被**认成「连不上」。

    实测含义：**Windows 默认 `ProactorEventLoop` 下 psycopg async 直接拒绝工作**，
    抛的就是 `psycopg.InterfaceError`（实测它**不是** `OperationalError` 的子类）。

    若把它归成「依赖不可达」，后果是一条完整的掩盖链：
    本机跑不起来 → 判 `PENDING` → dev 放行 → **测试变绿** →
    所有人以为"只是库没起" → 而真相是这台机器的事件循环根本不兼容（U-39）。
    → 所以这里断言的是**错归因被物理挡住**，而不是"少判了一种情况"。

    ⚠️ 反过来的代价（把它当致命）已由 07 §18.4.1 排除：那会让 `live=200` / `ready=503`
    这个状态不可达。两害相权，这里的取舍是：**宁可红着，也不许错归因。**
    """
    assert not is_unreachable(exc), (
        f"{type(exc).__name__} 被当成了「连不上」—— 它表达的是「你用错了」，"
        f"不是「依赖不在」。归错类会让 U-39 这类真问题伪装成「库没起」而消失"
    )


def test_unreachable_reason_carries_only_the_exception_class_name() -> None:
    """★ `reason` 会进启动日志与 `ConfigError` 文本 —— **不得**带出 DSN 片段。

    "连不上"时最容易顺手带出去的就是连接串（含口令）。
    这里构造一个**消息里带口令**的异常，断言 `reason` 里拿不到它 ——
    也就是说，即使驱动把 DSN 回显在异常正文里，本模块也不会把它传播出去。
    """
    leaky = psycopg.OperationalError(
        "connection to server at 'db.internal' failed: "
        "postgresql://app_rw:sup3r-s3cret@db.internal:5432/ecom"
    )
    reason = unreachable_from(leaky).reason

    assert "sup3r-s3cret" not in reason, f"reason 泄露了口令：{reason!r}"
    assert "app_rw" not in reason, f"reason 泄露了用户名：{reason!r}"
    assert "db.internal" not in reason, f"reason 泄露了主机名：{reason!r}"
    assert type(leaky).__name__ in reason, (
        f"reason 至少要留下异常类名（那是唯一的定位线索）：{reason!r}"
    )


def test_unreachable_is_not_confused_with_none() -> None:
    """`Unreachable` 与 `None` 必须是**不同类型** —— 二者含义相反。

    `None` 在现有判定里已有确定含义（"连上了、但那个角色/列不存在" → `FAIL`）。
    用同一个 `None` 承载两种相反事实，迟早有人把"连不上"读成"角色配错了"。
    """
    needle = Unreachable(reason="依赖不可达（OperationalError）")
    assert needle is not None
    assert str(needle) == needle.reason, "`str()` 必须给出理由，否则日志里只剩一个对象地址"


# ---------------------------------------------------------------------------
# 3. 三条 I/O 断言：「连不上」→ PENDING，而不是 FAIL
# ---------------------------------------------------------------------------

def test_analytics_unreachable_is_pending_not_fail() -> None:
    """★ `None`（角色不存在）与 `Unreachable`（连不上）**同一条断言、相反结论**。

    这是全项目最容易写错的一处：两者都是"我没拿到那个元组"，
    但一个是"配置错了 → 必须拒绝启动"，一个是"库没起 → 无法判定 → 放行并如实上报"。
    """
    unreachable = Unreachable(reason="依赖不可达（OperationalError）")

    got_unreachable = evaluate_analytics_is_read_only(connecting_role="app_ro", row=unreachable)
    assert got_unreachable.name == ANALYTICS_DSN_IS_READ_ONLY
    assert got_unreachable.status is AssertionStatus.PENDING, "连不上必须判 PENDING（放行 + 上报 503）"

    got_missing_role = evaluate_analytics_is_read_only(connecting_role="app_ro", row=None)
    assert got_missing_role.status is AssertionStatus.FAIL, "角色不存在是**配置错**，必须判 FAIL"

    assert "无法判定" in got_unreachable.detail
    assert "部署" in got_unreachable.detail, (
        "detail 必须把归因指向「部署/依赖未就绪」—— 否则排查的人会去找上游窗口要交付"
    )


def test_embedding_unreachable_and_absent_are_both_pending_but_say_different_things() -> None:
    """★ 两者都判 `PENDING`，但**理由不同、detail 必须不同**。

    合并措辞的代价：真实原因在"部署没起库"时，文档却把人指向 W2A 要语义包 ——
    排查方向被引到错误的窗口，而且没有任何信号说方向错了。
    """
    unreachable = evaluate_embedding_dim(
        declared_dim=1024, column=Unreachable(reason="依赖不可达（OperationalError）")
    )
    absent = evaluate_embedding_dim(declared_dim=1024, column=None)

    assert unreachable.name == absent.name == EMBEDDING_DIM_MATCHES_VECTOR_COLUMN
    assert unreachable.status is absent.status is AssertionStatus.PENDING
    assert unreachable.detail != absent.detail, "两种 PENDING 的 detail 不得相同"
    assert "无法判定" in unreachable.detail
    assert "W2A" in absent.detail, "列不存在这条必须点名 W2A（上游交付）"
    assert "W2A" not in unreachable.detail, (
        "连不上这条**不得**提 W2A —— 那不是上游缺交付，是本地依赖没起"
    )


def test_audit_unreachable_is_pending_while_missing_table_is_fail() -> None:
    """审计表：连不上 → `PENDING`；表不存在 → `FAIL`（迁移没跑，是硬前置没满足）。"""
    unreachable = evaluate_audit_append_only(Unreachable(reason="依赖不可达（PoolTimeout）"))
    assert unreachable.name == AUDIT_LOG_APPEND_ONLY_ENFORCED
    assert unreachable.status is AssertionStatus.PENDING

    missing = evaluate_audit_append_only(
        sa.AuditAccess(
            table_present=False,
            connecting_role="app_rw",
            connecting_role_is_superuser=False,
            can_insert=False,
            can_update=False,
            can_delete=False,
            can_truncate=False,
            trigger_present=False,
        )
    )
    assert missing.status is AssertionStatus.FAIL


def test_unreachable_pending_obeys_the_same_prod_env_gate() -> None:
    """「无法判定」在 prod 下必须升级为拒绝启动 —— 与 U-19 的 τ env-gate 同形。**双断言**。

    只断言 prod 致命 → 分不清"env-gate"与"一律致命"（后者会让阶段 1B 起不来）；
    只断言 dev 放行 → 证明不了生产真的收紧了，而那是安全侧的那一半。
    """
    outcome = evaluate_analytics_is_read_only(
        connecting_role="app_ro", row=Unreachable(reason="依赖不可达（OperationalError）")
    )
    assert outcome.is_fatal(_settings(AppEnv.DEV)) is False, (
        "dev 下「连不上」不得致命 —— 否则 `live=200` / `ready=503` 这个状态不可达（07 §18.4.1）"
    )
    assert outcome.is_fatal(_settings(AppEnv.PROD)) is True, (
        "prod 下「无法判定」必须拒绝启动 —— 生产不存在'依赖待补'这个状态"
    )


# ---------------------------------------------------------------------------
# 4. ★★ 三个 `live_probes` 闭包**都**必须包 `_guarded`
# ---------------------------------------------------------------------------

def _engine_stub() -> AsyncEngine:
    """一个**永不发起连接**的真引擎（构造是惰性的，真实 I/O 已被替身拦掉）。"""
    return create_async_engine("postgresql+psycopg://app_rw:placeholder@127.0.0.1:1/ecom")


def _raiser(exc: BaseException) -> Any:
    """造一个"调用即抛"的替身，签名宽容（三个 `_fetch_*` 的参数个数不同）。"""

    async def _fn(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return _fn


async def test_every_live_probe_converts_unreachable_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★ 三个闭包**一个都不能少**包 `_guarded`。

    只替换最底层的 `_fetch_*`（真 I/O 那一步），保留 `live_probes` 的**真实接线** ——
    要验的正是那层接线。少包一个的后果不是"少判一条"，
    而是那条断言会以**异常**形式炸穿启动路径：症状（启动崩溃 / 500）
    离病因（某个依赖没起）很远，而且只在那一个依赖出问题时才出现 —— 最难被发现的一类。

    ⚠️ 用替身而非"真连一个打不通的地址"：后者在 Windows + 默认事件循环下抛的是
    `InterfaceError`（见上一条），本用例会变成在测事件循环，而不是在测接线。
    """
    boom = psycopg.OperationalError("connection refused")
    for name in ("_fetch_analytics_role", "_fetch_vector_column", "_fetch_audit_access"):
        monkeypatch.setattr(sa, name, _raiser(boom))

    engine = _engine_stub()
    try:
        probes = sa.live_probes(_settings(AppEnv.DEV), metadata_engine=engine)
        for label, call in (
            ("analytics_role", probes.analytics_role),
            ("vector_column", probes.vector_column),
            ("audit_access", probes.audit_access),
        ):
            got = await call()
            assert isinstance(got, Unreachable), (
                f"`{label}` 没有把「连不上」转成 `Unreachable`（拿到 {type(got).__name__}）—— "
                f"该闭包漏包了 `_guarded`，依赖未起时它会炸穿启动路径"
            )
    finally:
        await engine.dispose()


async def test_live_probe_does_not_hide_a_non_connectivity_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★ 反过来的一半：**非**「连不上」的异常必须照常抛出，不得被吞成 `Unreachable`。

    这条与上一条方向相反、缺一不可。实测对应的正是 U-39：
    Windows `ProactorEventLoop` 下 psycopg 抛 `InterfaceError`。
    若被吞掉，本机就会表现成"库没起"→ 放行 → 测试变绿 → **U-39 从视野里消失**。

    换句话说：**本用例在断言"U-39 必须继续红着"** —— 直到 W0 真正修好事件循环。
    """
    monkeypatch.setattr(
        sa,
        "_fetch_vector_column",
        _raiser(psycopg.InterfaceError("Psycopg cannot use the 'ProactorEventLoop' in async mode")),
    )

    engine = _engine_stub()
    try:
        probes = sa.live_probes(_settings(AppEnv.DEV), metadata_engine=engine)
        with pytest.raises(psycopg.InterfaceError, match="ProactorEventLoop"):
            await probes.vector_column()
    finally:
        await engine.dispose()


async def test_live_probe_passes_the_real_result_through_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路径不得被 `_guarded` 改变 —— 它只该在 `except` 分支出现。"""
    expected = ("app_ro", "on")

    async def _fine(*args: Any, **kwargs: Any) -> Any:
        return expected

    monkeypatch.setattr(sa, "_fetch_analytics_role", _fine)

    engine = _engine_stub()
    try:
        probes = sa.live_probes(_settings(AppEnv.DEV), metadata_engine=engine)
        assert await probes.analytics_role() == expected
    finally:
        await engine.dispose()
