"""三池装配的离线断言（DoD④ 的**装配期**一半）。

归属窗口：W1B。

⚠️ 分工必须说清，否则会误以为"测试全绿 = 三池没问题"：

| 断言 | 在哪里 | 能证明什么 | **不能**证明什么 |
|---|---|---|---|
| 对象不复用 / DSN 归属正确 / 名字不撞 | **本文件**（离线） | 装配代码没写错 | 权限是否真的只读 |
| `application_name` 真的带上了、`app_ro` 真的只读、`app_rw` 真的不能改审计表 | `tests/integration/`（连库） | 数据库侧的事实 | —（它们才是 DoD④⑤ 的正身） |

把两者混为一谈是这类项目最典型的假绿灯：离线断言全绿，而数据库里
`app_ro` 其实有写权限 —— 那种情况下**没有任何报错**，只会某天发现数据被改了。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.repo import pools as pools_mod
from app.repo.dsn import DsnPair
from app.repo.pools import (
    ANALYTICS_APPLICATION_NAME,
    CHECKPOINT_APPLICATION_NAME,
    METADATA_APPLICATION_NAME,
    PoolSeparationError,
    assert_application_names_are_unique,
    build_analytics_engine,
    build_checkpoint_pool,
    build_metadata_engine,
    build_three_pools,
)

_RW = "postgresql+psycopg://app_rw:pw@localhost:5432/ecom"
_RO = "postgresql+psycopg://app_ro:pw@localhost:5432/ecom"


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]  # 其余字段来自 conftest 的占位环境
        DATABASE_URL=_RW,
        ANALYTICS_DB_URL=_RO,
    )


def test_application_names_are_unique_and_match_constants() -> None:
    """规格表的三个 `application_name` 互不相同 —— T-A1 靠它们区分 pg 后端。"""
    assert_application_names_are_unique()
    names = {spec.application_name for spec in pools_mod.POOL_SPECS.values()}
    assert names == {
        METADATA_APPLICATION_NAME,
        ANALYTICS_APPLICATION_NAME,
        CHECKPOINT_APPLICATION_NAME,
    }


def test_engines_use_their_own_dsn(settings: Settings) -> None:
    """metadata 必须接 `DATABASE_URL`，analytics 必须接 `ANALYTICS_DB_URL`。

    ⚠️ 写反**不会报任何错** —— 只会让业务 SQL 跑在可写连接上，而那正是 N-02 的边界。
    """
    meta = build_metadata_engine(settings)
    ana = build_analytics_engine(settings)
    assert meta.url.render_as_string(hide_password=False) == _RW
    assert ana.url.render_as_string(hide_password=False) == _RO


def test_checkpoint_pool_is_not_open_at_construction(settings: Settings) -> None:
    """checkpoint 池必须 `open=False` 构造。

    理由是可复现的故障：`AsyncConnectionPool` 在 `open=True` 时会绑定**创建它的** event loop，
    在 import 期或非 async 上下文里构造会抛 "attached to a different loop" ——
    而 `app/main.py` 的装配原则是"import 期零 I/O"。
    """
    pool = build_checkpoint_pool(settings)
    assert pool.closed is True
    assert pool.max_size == (
        pools_mod.POOL_SPECS[pools_mod.PoolKind.CHECKPOINT].pool_size
        + pools_mod.POOL_SPECS[pools_mod.PoolKind.CHECKPOINT].max_overflow
    )


def test_three_pools_are_separated(settings: Settings) -> None:
    """正例：三池互不串用。"""
    three = build_three_pools(settings)
    # ⚠️ 用 `id()` 而不是 `is not`：三池的静态类型互不相同（`AsyncEngine` vs `AsyncConnectionPool`），
    # mypy 因此判定 `is not` **恒真**并报 `comparison-overlap` —— 它说得对，
    # 但那是以"类型已证明"为前提的；本用例要证的是**装配事实**（没人把同一个对象塞进两个字段），
    # 只能运行时判。改成 `id()` 保留运行时语义，同时不再与静态结论打架。
    assert id(three.metadata) != id(three.analytics)
    assert id(three.metadata) != id(three.checkpoint)
    assert id(three.analytics) != id(three.checkpoint)


def test_swapped_dsn_is_rejected(settings: Settings) -> None:
    """★ 负向：把 analytics 池接到 `DATABASE_URL` 上必须被装配期拦下。

    这是本文件存在的**主要理由** —— 正向用例只能证明"现在是对的"，
    负向用例才能证明"这道断言真的会拦住"（否则它就是一条永远为真的装饰）。
    """
    pools = pools_mod.ThreePools(
        metadata=build_metadata_engine(settings),
        analytics=build_metadata_engine(settings),  # ← 故意的错误：analytics 用了 RW DSN
        checkpoint=build_checkpoint_pool(settings),
    )
    with pytest.raises(PoolSeparationError, match="ANALYTICS_DB_URL"):
        pools_mod.assert_pools_are_separated(pools, DsnPair.from_raw(_RW, _RO))


def test_reused_pool_object_is_rejected(settings: Settings) -> None:
    """★ 负向：把同一个 engine 同时当 metadata 和 analytics 用，必须被拦下。"""
    shared = build_metadata_engine(settings)
    pools = pools_mod.ThreePools(
        metadata=shared,
        analytics=shared,
        checkpoint=build_checkpoint_pool(settings),
    )
    with pytest.raises(PoolSeparationError, match="N-14"):
        pools_mod.assert_pools_are_separated(pools, DsnPair.from_raw(_RW, _RO))
