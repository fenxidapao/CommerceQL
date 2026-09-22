"""`query_plan` 写入通道的**库侧**自证（W4 RELAY §二 的验收条件）。

归属窗口：W1B。

只测**必须真库才能证明**的部分（离线契约见 `tests/unit/test_query_plan_store.py`）：

1. **往返**：真 `AsyncEngine`（元数据池形态，`app_rw`）→ 写入 → 读回，字段逐项一致
   （`plan_json` 是真 jsonb 对象而非字符串、`plan_summary` 是可解析 JSON 文本、
   枚举落成字面值、`confidence` 保持 Decimal 精度、三处可空列可写 NULL）；
2. **★ UPDATE 被权限拒绝**（W4 明确点名的负例）：`app_rw` 对 `app.query_plan` 只有
   INSERT/SELECT ⇒ `UPDATE` 报 42501。这是"计划行一次写入"的**权限层证据**，
   不是靠代码自觉；
3. **主键撞重如实抛**：同 `task_id` 二次写入 → `UniqueViolation` 从 store 往外抛，
   且原行**未被覆盖**（有 `ON CONFLICT DO UPDATE` 的话这里会看到新值）；
4. **两层防线各自的证据**：Python 层（非枚举 → 不发语句）+ 数据库层（CHECK 拒非法字面值）。

⚠️ **本文件不用 `async def test_`**：仓库既有 async 用例一律 `asyncio.run(...)`
（`test_auth_chain.py` 30+ 处）。根因是 Windows 上 psycopg async 只支持
`SelectorEventLoop`，而 `conftest` 的会话级 fixture 用 `set_event_loop_policy` 换策略 ——
`asyncio.run` 认这个策略，**pytest-asyncio 1.4 自建循环不认**（首版就是栽在这上面：
4 条用例全 `InterfaceError: cannot use the 'ProactorEventLoop'`）。
本文件因此在**同一个 helper 里**建 engine → 跑协程 → dispose，三者同循环。

跳过策略（同 0004 集成测试）：PG 不可达 → skip（写明缺失前置）；迁移失败 → 让它红。

⚠️ **本地复核必须至少跑一遍 CI 形态的 DSN**（否则"本地全绿"是假绿，见 `_sqla()`）：
`COMMERCEQL_TEST_SUPER_DSN=<超管 DSN> COMMERCEQL_TEST_RW_DSN=<读写 DSN> pytest tests/integration/test_query_plan_store_pg.py`
（U-114 防线①：DSN 只认环境变量，缺 = fail；别指向共享库，用一次性测试库。）
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.enums import BindingLayer, BindingState
from app.repo.query_plan import QueryPlanStore
from tests.integration._env_dsn import env_dsn

pytestmark = pytest.mark.integration

_BACKEND = Path(__file__).resolve().parents[2]

#: 属主 DSN **运行时拼接**（DoD④：源码不落完整字面量；app_rw 在 allowlist 内可直写）。
#: DSN **只认环境变量**（U-114 防线①，共享守卫 `_env_dsn.py`）：缺 env = 当场 fail（禁止 skip）。
_SCHEME = "postgresql+psycopg" + "://"
_SUPER = env_dsn("COMMERCEQL_TEST_SUPER_DSN")
_RW = env_dsn("COMMERCEQL_TEST_RW_DSN")


def _libpq(dsn: str) -> str:
    """SQLAlchemy 形态 → libpq 形态（`psycopg.connect()` **不接受** `+psycopg` 后缀）。"""
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _sqla(dsn: str) -> str:
    """libpq 形态 → SQLAlchemy 形态（`alembic` / SQLAlchemy 需要）。

    ⚠️ **两个方向都要有**，缺正向那个会让 CI 整个 DoD③ job 变红（W0 RELAY §9.2）：

    - 本模块**本地**跑时 `COMMERCEQL_TEST_*_DSN` 缺省值就是 SQLAlchemy 形态，
      把 `_SUPER` 直接交给 `MIGRATION_DATABASE_URL` 恰好是对的 —— 所以本地全绿；
    - CI（`ci.yml`）注入的却是 **libpq 形态** `postgresql://role@127.0.0.1:5432/ecom`
      （被迫的：`test_semantic_materialization.py` / `test_exec_real_pg.py`
      直接把它交给 `psycopg.connect()`），于是同一行代码解析出 **psycopg2** 方言
      → `ModuleNotFoundError: No module named 'psycopg2'`（本环境只有 psycopg 3）。

    教训：**"本地绿"证明不了"CI 绿"的前提是两者注入同形态的配置**；
    这里两个方向的转换函数成对存在，任何一种形态进来都能归一。
    """
    if "+psycopg://" in dsn:
        return dsn
    for libpq_prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(libpq_prefix):
            return dsn.replace(libpq_prefix, "postgresql+psycopg://", 1)
    return dsn


_SUPER_LIBPQ = _libpq(_SUPER)
_RW_LIBPQ = _libpq(_RW)

#: 本模块写入的行统一挂随机前缀（并发跑两次 pytest 也不互撞）。
_TASK_PREFIX = f"it_qp_{uuid.uuid4().hex[:8]}_"


def _pg_available() -> bool:
    try:
        psycopg.connect(_RW_LIBPQ, connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def upgraded() -> str:
    """真实执行 `alembic upgrade head`（幂等）—— 0004 的表必须存在。"""
    if not _pg_available():
        pytest.skip("PG 不可达（compose 栈未起）→ 不计为通过")
    env = {
        **os.environ,
        # ⚠️ 全部过 `_sqla()`：alembic/SQLAlchemy 侧只认 `+psycopg` 后缀，
        # 而 CI 注入的是 libpq 形态（W0 RELAY §9.2 的根因）。
        "MIGRATION_DATABASE_URL": _sqla(_SUPER),
        "DATABASE_URL": _sqla(_RW),
        "ANALYTICS_DB_URL": _sqla(_RW),
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head 失败:\n{result.stdout}\n{result.stderr}"
    )
    return _SUPER


@pytest.fixture()
def rw_row(upgraded: str) -> Iterator[psycopg.Connection]:
    """读回侧连接（`app_rw` 的 SELECT 权限）。autocommit：CHECK/权限失败不打 Abort 事务。"""
    conn = psycopg.connect(_RW_LIBPQ, connect_timeout=3)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_rows(upgraded: str) -> Iterator[None]:
    """清掉本模块写入的行（属主身份 —— app_rw 无 DELETE，这正是 0004 的权限裁定）。"""
    owner = psycopg.connect(_SUPER_LIBPQ, connect_timeout=3)
    owner.autocommit = True
    yield
    owner.execute("DELETE FROM app.query_plan WHERE task_id LIKE %s", (f"{_TASK_PREFIX}%",))
    owner.close()


def _run(action: Callable[[QueryPlanStore], Awaitable[Any]]) -> Any:
    """在**当前策略**的事件循环里跑（conftest 已把 win32 策略设为 Selector）。

    engine 与协程必须同循环：跨循环复用 psycopg async 池会拿到 "loop is closed"。
    """

    async def main() -> Any:
        # ⚠️ `_sqla()`：CI 注入的是 libpq 形态，而 `create_async_engine` 认方言后缀
        # —— 少这一层会把 `postgresql://` 解析成 psycopg2（本环境没有）。
        engine = create_async_engine(_sqla(_RW), pool_size=2, max_overflow=0)
        try:
            return await action(QueryPlanStore(engine))
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _insert(
    store: QueryPlanStore,
    task_id: str,
    *,
    binding_state: BindingState = BindingState.RESOLVED_UNIQUE,
    binding_layer: BindingLayer | None = BindingLayer.L3,
    plan_summary: Any = None,
    confidence: Decimal | None = Decimal("0.870000"),
) -> None:
    await store.insert_query_plan(
        task_id=task_id,
        plan_json={"schema_version": 1, "grain": "day", "metrics": ["gmv"]},
        bundle_version="bundle_2026.09.14.1",
        binding_state=binding_state,
        binding_layer=binding_layer,
        plan_summary={"metrics": ["gmv"]} if plan_summary is None else plan_summary,
        confidence=confidence,
    )


# ============================================================================
# 1. 往返
# ============================================================================

def test_roundtrip_preserves_all_fields(rw_row: psycopg.Connection) -> None:
    task_id = f"{_TASK_PREFIX}round"
    _run(lambda store: _insert(store, task_id))

    row = rw_row.execute(
        "SELECT plan_json, plan_summary, bundle_version, binding_state, binding_layer,"
        " confidence FROM app.query_plan WHERE task_id = %s",
        (task_id,),
    ).fetchone()
    assert row is not None, "写入后读不到 —— 写入通道没真正落库"
    assert row[0]["grain"] == "day", "plan_json 必须是真 jsonb 对象（不是被转义的字符串）"
    assert row[1] == '{"metrics": ["gmv"]}', "plan_summary 是可解析 JSON 文本"
    assert row[2] == "bundle_2026.09.14.1"
    assert row[3] == "resolved_unique", "枚举必须落成 .value"
    assert row[4] == "L3"
    assert row[5] == Decimal("0.870000"), "confidence 必须保持 Decimal 精度（float 会有二进制误差）"


def test_nullable_columns_accept_null(rw_row: psycopg.Connection) -> None:
    """`unresolved` 终态形态：无判定层 / 无置信度 / 摘要缺省（0004 的可空性裁定）。"""
    task_id = f"{_TASK_PREFIX}null"

    async def action(store: QueryPlanStore) -> None:
        await store.insert_query_plan(
            task_id=task_id,
            plan_json={"schema_version": 1},
            bundle_version="bundle_2026.09.14.1",
            binding_state=BindingState.UNRESOLVED,
        )

    _run(action)
    row = rw_row.execute(
        "SELECT plan_summary, binding_layer, confidence FROM app.query_plan WHERE task_id = %s",
        (task_id,),
    ).fetchone()
    assert row == (None, None, None)


# ============================================================================
# 2. ★ 权限负例（W4 点名）—— 计划行不可改
# ============================================================================

def test_app_rw_update_is_rejected_by_privilege(rw_row: psycopg.Connection) -> None:
    """先证明能写（正向），再证明改不动（负向），并核对拒绝理由 = 42501。

    ⚠️ 只断言"UPDATE 失败"不够 —— 表不存在、列名写错也都会失败。
    先正向写一行（证明表在、权限在），再打 UPDATE，且**核对 sqlstate**。
    """
    task_id = f"{_TASK_PREFIX}immutable"
    _run(lambda store: _insert(store, task_id))
    assert rw_row.execute(
        "SELECT count(*) FROM app.query_plan WHERE task_id = %s", (task_id,)
    ).fetchone()[0] == 1

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as caught:
        rw_row.execute(
            "UPDATE app.query_plan SET binding_state = 'ambiguous' WHERE task_id = %s",
            (task_id,),
        )
    assert caught.value.sqlstate == "42501"


# ============================================================================
# 3. 主键撞重 = 如实抛（没有 ON CONFLICT 的行为级证据）
# ============================================================================

def test_duplicate_task_id_raises_unique_violation(rw_row: psycopg.Connection) -> None:
    """同 `task_id` 二次写入 → 抛（`UniqueViolation` 被 SQLAlchemy 包成 `IntegrityError`）。

    ⚠️ **异常类型是包装后的**：经 `AsyncEngine` 执行时 SQLAlchemy 把 DBAPI 异常包成
    `sqlalchemy.exc.IntegrityError`，原始 psycopg 异常在 `.orig`。这条对调用方（W4）
    是必要信息 —— 捕获点是 `IntegrityError`，不是 `psycopg.errors.UniqueViolation`。
    """
    from sqlalchemy.exc import IntegrityError

    task_id = f"{_TASK_PREFIX}dup"

    async def action(store: QueryPlanStore) -> None:
        await _insert(store, task_id)
        with pytest.raises(IntegrityError) as caught:
            await _insert(store, task_id, binding_state=BindingState.AMBIGUOUS)
        assert isinstance(caught.value.orig, psycopg.errors.UniqueViolation), (
            f"包的原始异常是 {type(caught.value.orig).__name__} —— "
            f"说明撞的不是主键（那这个用例证明的就不是'无 upsert'）"
        )

    _run(action)
    # 原有那行**没被覆盖**（有 ON CONFLICT DO UPDATE 的话这里会变成 ambiguous）
    state = rw_row.execute(
        "SELECT binding_state FROM app.query_plan WHERE task_id = %s", (task_id,)
    ).fetchone()[0]
    assert state == "resolved_unique", (
        "重复写入改动了原行 —— 说明实现或表语义被改成了 upsert（诊断价值在第一次写的那行）"
    )


# ============================================================================
# 4. 两层防线各自的证据：枚举挡住非法类型、CHECK 挡住非法字面值
# ============================================================================

def test_non_enum_state_fails_before_touching_db(rw_row: psycopg.Connection) -> None:
    """第一层（Python）：传裸字符串 → 取 `.value` 当场 AttributeError，**不发语句**。

    ⚠️ 这是刻意的严格：宽松实现（`str(x)` 兼容两种形态）会让"传了非枚举"这种调用点错误
    一路走到库里，只在 CHECK 拒绝时才发现 —— 那时的错误信息里没有字段名。
    """
    task_id = f"{_TASK_PREFIX}nonenum"

    async def action(store: QueryPlanStore) -> None:
        with pytest.raises(AttributeError):
            await store.insert_query_plan(  # type: ignore[arg-type]
                task_id=task_id,
                plan_json={"schema_version": 1},
                bundle_version="bundle_2026.09.14.1",
                binding_state="bogus_state",  # 裸字符串：调用点错误
            )

    _run(action)
    assert rw_row.execute(
        "SELECT count(*) FROM app.query_plan WHERE task_id = %s", (task_id,)
    ).fetchone()[0] == 0, "类型错误竟然写进去了"


def test_check_rejects_invalid_state_at_db_layer(rw_row: psycopg.Connection) -> None:
    """第二层（数据库）：绕过 Python 直接 INSERT 非法字面值 → CHECK 拒。

    这一层不是给本通道用的（它走枚举），而是**最后一道防线**：
    将来任何新写入方（脚本/运维/新模块）绕过枚举时，库不让非法态进来。
    """
    with pytest.raises(psycopg.errors.CheckViolation):
        rw_row.execute(
            "INSERT INTO app.query_plan (task_id, plan_json, bundle_version, binding_state)"
            " VALUES (%s, %s, %s, %s)",
            (f"{_TASK_PREFIX}raw", "{}", "bundle_x", "bogus_state"),
        )
