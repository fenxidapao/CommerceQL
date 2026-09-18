"""`feedback` + `gold_query`（迁移 0005）的**库侧**自证。

归属窗口：W1B。

只测**必须真库才能证明**的部分（离线契约见 `tests/unit/test_migration_0005_runtime_contract.py`）：

1. **往返**：真 `AsyncEngine`（元数据池形态，`app_rw`）→ 写入 → 读回，字段逐项一致
   （枚举落成字面值、五处可空列可写 NULL）；
2. **★ NULL 语义的两处成对**（本文件最重要的两条）：
   · 空 `reason_code` 的重复提交**必须被唯一约束拦住**（`NULLS NOT DISTINCT`，否则 §A.6 幂等失效）；
   · 空 `reason_code` 的**回读必须命中**（`IS NOT DISTINCT FROM`，用 `=` 会永远查不到）——
     两条必须同时为真，只做一边就是"约束拦住了、回读找不到"的自相矛盾形态；
3. **权限负例**：`app_rw` 对 `app.feedback` 只有 INSERT/SELECT ⇒ `UPDATE` 报 42501（沉淀资产不可改）；
4. **两层防线各自的证据**：Python 层（非枚举 → 不发语句）+ 数据库层（CHECK 拒非法字面值）；
5. **`gold_query` 的 §11.7 检索规则在这个 schema 上真的成立**：
   `(tenant_id IS NULL OR tenant_id = :t) AND domain = :d AND bundle_version = :v`
   只能看到"全局库 ∪ 本租户"，看不到别的租户（双层库的物理判据是 `tenant_id` 是否 NULL）。

⚠️ **本文件不用 `async def test_`**：仓库既有 async 用例一律 `asyncio.run(...)`
（`test_auth_chain.py` 30+ 处）。根因是 Windows 上 psycopg async 只支持 `SelectorEventLoop`，
而 `conftest` 的会话级 fixture 用 `set_event_loop_policy` 换策略 ——
`asyncio.run` 认这个策略，**pytest-asyncio 1.4 自建循环不认**。

⚠️ **本地复核必须至少跑一遍 CI 形态的 DSN**（否则"本地全绿"是假绿，见 `_sqla()`）。

跳过策略：PG 不可达 → skip（写明缺失前置）；迁移失败 → 让它红。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.enums import FeedbackReasonCode
from app.repo.feedback import FeedbackSchemaMismatch, FeedbackStore

pytestmark = pytest.mark.integration

_BACKEND = Path(__file__).resolve().parents[2]

#: 属主 DSN **运行时拼接**（DoD④：源码不落完整字面量；app_rw 在 allowlist 内可直写）。
_SCHEME = "postgresql+psycopg" + "://"
_SUPER = os.environ.get(
    "COMMERCEQL_TEST_SUPER_DSN",
    _SCHEME + "postgres" + ":" + "postgres" + "@localhost:5432/ecom",
)
_RW = os.environ.get(
    "COMMERCEQL_TEST_RW_DSN",
    "postgresql+psycopg://app_rw:app_rw_pwd@localhost:5432/ecom",
)


def _libpq(dsn: str) -> str:
    """SQLAlchemy 形态 → libpq 形态（`psycopg.connect()` **不接受** `+psycopg` 后缀）。"""
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _sqla(dsn: str) -> str:
    """libpq 形态 → SQLAlchemy 形态（`alembic` / SQLAlchemy 需要）。

    ⚠️ **两个方向都要有**，缺正向那个会让 CI 整个 DoD③ job 变红（W0 RELAY §9.2）：
    本地缺省值是 SQLAlchemy 形态所以本地全绿，CI 注入的是 libpq 形态
    （`ci.yml:125-127`，被迫的：另两个测试直接把它交给 `psycopg.connect()`）。
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
_PREFIX = f"it_fb_{uuid.uuid4().hex[:8]}_"


def _fb_id(name: str) -> str:
    return f"{_PREFIX}{name}"


def _gold_id(name: str) -> str:
    return f"{_PREFIX}{name}"


def _pg_available() -> bool:
    try:
        psycopg.connect(_RW_LIBPQ, connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def upgraded() -> str:
    """真实执行 `alembic upgrade head`（幂等）—— 0005 的两张表必须存在。"""
    if not _pg_available():
        pytest.skip("PG 不可达（compose 栈未起）→ 不计为通过")
    env = {
        **os.environ,
        # ⚠️ 全部过 `_sqla()`：alembic/SQLAlchemy 侧只认 `+psycopg` 后缀。
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
    """清掉本模块写入的行（属主身份 —— app_rw 无 DELETE，这正是 0005 的权限裁定）。"""
    owner = psycopg.connect(_SUPER_LIBPQ, connect_timeout=3)
    owner.autocommit = True
    yield
    owner.execute("DELETE FROM app.feedback WHERE feedback_id LIKE %s", (f"{_PREFIX}%",))
    owner.execute("DELETE FROM app.gold_query WHERE gold_id LIKE %s", (f"{_PREFIX}%",))
    owner.close()


def _run(action: Callable[[FeedbackStore], Awaitable[Any]]) -> Any:
    """在**当前策略**的事件循环里跑（conftest 已把 win32 策略设为 Selector）。

    engine 与协程必须同循环：跨循环复用 psycopg async 池会拿到 "loop is closed"。
    """

    async def main() -> Any:
        # ⚠️ `_sqla()`：CI 注入的是 libpq 形态，而 `create_async_engine` 认方言后缀。
        engine = create_async_engine(_sqla(_RW), pool_size=2, max_overflow=0)
        try:
            return await action(FeedbackStore(engine))
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _insert(
    store: FeedbackStore,
    feedback_id: str,
    *,
    task_id: str | None = None,
    user_id: str = "u_1",
    is_correct: bool = False,
    reason_code: FeedbackReasonCode | None = FeedbackReasonCode.WRONG_METRIC_DEFINITION,
    corrected_sql: str | None = None,
    comment: str | None = None,
    correct_result_hint: str | None = None,
) -> None:
    await store.insert_feedback(
        feedback_id=feedback_id,
        task_id=task_id or f"{_PREFIX}task",
        user_id=user_id,
        is_correct=is_correct,
        reason_code=reason_code,
        corrected_sql=corrected_sql,
        comment=comment,
        correct_result_hint=correct_result_hint,
    )


# ============================================================================
# 1. 往返
# ============================================================================

def test_roundtrip_preserves_all_fields(rw_row: psycopg.Connection) -> None:
    fid = _fb_id("round")
    task_id = f"{_PREFIX}round"

    async def action(store: FeedbackStore) -> None:
        await _insert(
            store, fid, task_id=task_id,
            corrected_sql="SELECT 1", comment="GMV 应剔除运费", correct_result_hint="1752.10",
        )

    _run(action)
    row = rw_row.execute(
        "SELECT task_id, user_id, is_correct, reason_code, corrected_sql, comment,"
        " correct_result_hint FROM app.feedback WHERE feedback_id = %s",
        (fid,),
    ).fetchone()
    assert row is not None, "写入后读不到 —— 写入通道没真正落库"
    assert row[0] == task_id
    assert row[1] == "u_1", "user_id 来自调用方（应为 JWT 的 sub）"
    assert row[2] is False
    assert row[3] == "wrong_metric_definition", "枚举必须落成 .value"
    assert row[4] == "SELECT 1"
    assert row[5] == "GMV 应剔除运费"
    assert row[6] == "1752.10", "correct_result_hint 必须落库（§12.3 表行漏列，0005 补齐）"


def test_nullable_columns_accept_null(rw_row: psycopg.Connection) -> None:
    """§A.6 的四个 ⭕ 字段全空（用户只点了"结果有误"、没填任何细节）。"""
    fid = _fb_id("null")

    async def action(store: FeedbackStore) -> None:
        await _insert(store, fid, reason_code=None)

    _run(action)
    row = rw_row.execute(
        "SELECT reason_code, corrected_sql, comment, correct_result_hint"
        " FROM app.feedback WHERE feedback_id = %s",
        (fid,),
    ).fetchone()
    assert row == (None, None, None, None)


# ============================================================================
# 2. ★ NULL 语义的两处必须成对
# ============================================================================

def test_find_returns_existing_id(rw_row: psycopg.Connection) -> None:
    fid = _fb_id("find")

    async def action(store: FeedbackStore) -> Any:
        await _insert(store, fid)
        return await store.find_feedback_id(
            task_id=f"{_PREFIX}task", user_id="u_1",
            reason_code=FeedbackReasonCode.WRONG_METRIC_DEFINITION,
        )

    assert _run(action) == fid


def test_find_returns_none_when_absent(rw_row: psycopg.Connection) -> None:
    async def action(store: FeedbackStore) -> Any:
        return await store.find_feedback_id(
            task_id=f"{_PREFIX}no_such_task", user_id="u_1",
            reason_code=FeedbackReasonCode.OTHER,
        )

    assert _run(action) is None


def test_find_matches_null_reason_code(rw_row: psycopg.Connection) -> None:
    """★ 空 `reason_code` 的**回读**必须命中（`IS NOT DISTINCT FROM` 而非 `=`）。

    用 `=` 时 `NULL = NULL` 为 NULL（不是 true）⇒ 永远查不到，
    表现为"用户连点两次、约束拦住了第二次，但端点回读不到已有 id" ⇒ 又插一次 → 又撞约束 → 500。
    """
    fid = _fb_id("find_null")

    async def action(store: FeedbackStore) -> Any:
        await _insert(store, fid, reason_code=None)
        return await store.find_feedback_id(
            task_id=f"{_PREFIX}task", user_id="u_1", reason_code=None
        )

    assert _run(action) == fid


def test_duplicate_triple_raises_unique_violation(rw_row: psycopg.Connection) -> None:
    """§A.6 幂等三元组撞重**如实抛**（不做 upsert），且原行未被覆盖。"""
    first, second = _fb_id("dup1"), _fb_id("dup2")

    async def action(store: FeedbackStore) -> None:
        await _insert(store, first, comment="first")
        await _insert(store, second, comment="second")

    with pytest.raises(IntegrityError) as caught:
        _run(action)
    assert isinstance(caught.value.orig, psycopg.errors.UniqueViolation), (
        f"应是唯一约束冲突，实为 {caught.value.orig!r}"
    )
    row = rw_row.execute(
        "SELECT feedback_id, comment FROM app.feedback WHERE feedback_id IN (%s, %s)",
        (first, second),
    ).fetchall()
    assert row == [(first, "first")], "原行必须原样保留（有 ON CONFLICT DO UPDATE 的话这里会看到 second）"


def test_duplicate_null_reason_code_raises(rw_row: psycopg.Connection) -> None:
    """★ `NULLS NOT DISTINCT` 的行为证明：空归因的重复提交**同样被拦住**。

    去掉迁移里的 `NULLS NOT DISTINCT` 后，本用例会**写入两行**并失败 ——
    这正是 §A.6 幂等"看起来有、实际没有"的那个形态。
    """
    first, second = _fb_id("dupn1"), _fb_id("dupn2")

    async def action(store: FeedbackStore) -> None:
        await _insert(store, first, reason_code=None)
        await _insert(store, second, reason_code=None)

    with pytest.raises(IntegrityError):
        _run(action)
    rows = rw_row.execute(
        "SELECT count(*) FROM app.feedback WHERE feedback_id IN (%s, %s)", (first, second)
    ).fetchone()
    assert rows == (1,), f"空归因未被唯一约束拦住 —— 落了 {rows[0]} 行（§A.6 幂等失效）"


def test_different_users_do_not_collide(rw_row: psycopg.Connection) -> None:
    """同一 task 的两个用户报同一个归因 = 两条（§12.3 的唯一键含 `user_id`，与 §A.6 等价）。"""
    first, second = _fb_id("u1"), _fb_id("u2")

    async def action(store: FeedbackStore) -> None:
        await _insert(store, first, user_id="u_1")
        await _insert(store, second, user_id="u_2")

    _run(action)
    count = rw_row.execute(
        "SELECT count(*) FROM app.feedback WHERE feedback_id IN (%s, %s)", (first, second)
    ).fetchone()
    assert count == (2,)


# ============================================================================
# 3. 两层防线：Python 层（不发语句）+ 数据库层（CHECK）
# ============================================================================

def test_non_enum_reason_code_fails_before_touching_db() -> None:
    """裸字符串必须在**调用点**就红（engine 传 None 也能证 —— 报错在碰 engine 之前）。"""
    store = FeedbackStore(cast(Any, None))
    with pytest.raises(FeedbackSchemaMismatch) as caught:
        asyncio.run(_insert(store, _fb_id("bad"), reason_code=cast(Any, "wrong_join")))
    assert "FeedbackReasonCode" in str(caught.value)


def test_is_correct_must_be_bool() -> None:
    """`1` 不是 `True`：布尔列收到整数是编程错误，不该静默入库。"""
    store = FeedbackStore(cast(Any, None))
    with pytest.raises(FeedbackSchemaMismatch):
        asyncio.run(_insert(store, _fb_id("bad2"), is_correct=cast(Any, 1)))


def test_missing_required_column_reported_by_name() -> None:
    store = FeedbackStore(cast(Any, None))
    with pytest.raises(FeedbackSchemaMismatch) as caught:
        asyncio.run(
            store.insert_feedback(
                feedback_id=cast(Any, None), task_id="t", user_id="u", is_correct=False
            )
        )
    assert "feedback_id" in str(caught.value)


def test_check_rejects_invalid_literal(rw_row: psycopg.Connection) -> None:
    """绕过通道、直接写非法归因 → 数据库层 CHECK 拒（`app_rw` 有 INSERT，所以这条测的是 CHECK 不是权限）。"""
    with pytest.raises(psycopg.errors.CheckViolation):
        rw_row.execute(
            "INSERT INTO app.feedback (feedback_id, task_id, user_id, is_correct, reason_code)"
            " VALUES (%s, %s, %s, %s, %s)",
            (_fb_id("check"), f"{_PREFIX}t", "u", False, "not_a_reason"),
        )


# ============================================================================
# 4. ★ 权限负例 —— 反馈记录不可改
# ============================================================================

def test_app_rw_update_is_rejected_by_privilege(rw_row: psycopg.Connection) -> None:
    """`app_rw` 对 `app.feedback` 只有 INSERT/SELECT ⇒ UPDATE 报 42501（不是靠代码自觉）。"""
    fid = _fb_id("perm")

    async def action(store: FeedbackStore) -> None:
        await _insert(store, fid)

    _run(action)
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as caught:
        rw_row.execute(
            "UPDATE app.feedback SET comment = 'tampered' WHERE feedback_id = %s", (fid,)
        )
    assert caught.value.sqlstate == "42501"
    comment = rw_row.execute(
        "SELECT comment FROM app.feedback WHERE feedback_id = %s", (fid,)
    ).fetchone()
    assert comment == (None,), "UPDATE 被拒后原值必须未变"


# ============================================================================
# 5. ★ gold_query：§11.7 的检索规则在这个 schema 上真的成立
# ============================================================================

def _insert_gold(
    conn: psycopg.Connection,
    *,
    name: str,
    tenant_id: str | None,
    domain: str,
    fingerprint: str,
    bundle: str = "bundle_2026.09.14.1",
) -> str:
    gid = _gold_id(name)
    conn.execute(
        "INSERT INTO app.gold_query (gold_id, tenant_id, question, sql, domain, verified_by,"
        " verified_at, source, ast_fingerprint, bundle_version)"
        " VALUES (%s, %s, %s, %s, %s, %s, now(), %s, %s, %s)",
        (gid, tenant_id, f"Q {name}", "SELECT 1", domain, None, "seed", fingerprint, bundle),
    )
    return gid


def test_gold_query_tenant_visibility_follows_section_11_7(rw_row: psycopg.Connection) -> None:
    """`tenant_id IS NULL`（全局库）∪ 本租户，**看不到**别的租户；且被 bundle_version 过滤。"""
    domain = f"{_PREFIX}domain"
    bundle = "bundle_2026.09.14.1"
    global_g = _insert_gold(rw_row, name="g", tenant_id=None, domain=domain, fingerprint="fp_g")
    a_g = _insert_gold(rw_row, name="a", tenant_id="tenant_a", domain=domain, fingerprint="fp_a")
    b_g = _insert_gold(rw_row, name="b", tenant_id="tenant_b", domain=domain, fingerprint="fp_b")
    other_bundle = _insert_gold(
        rw_row, name="ob", tenant_id="tenant_a", domain=domain,
        fingerprint="fp_ob", bundle="bundle_2026.09.01.1",
    )

    def visible(tenant: str) -> set[str]:
        # §11.7 的检索规则原文（必须写进 SQL，不是应用层过滤）
        rows = rw_row.execute(
            "SELECT gold_id FROM app.gold_query"
            " WHERE (tenant_id IS NULL OR tenant_id = %s)"
            " AND domain = %s AND bundle_version = %s",
            (tenant, domain, bundle),
        ).fetchall()
        return {r[0] for r in rows}

    assert visible("tenant_a") == {global_g, a_g}, "应看到 全局库 ∪ 本租户"
    assert visible("tenant_b") == {global_g, b_g}, "不应看到 tenant_a 的私有条目"
    assert other_bundle not in visible("tenant_a"), "别的 bundle_version 必须被过滤（§11.7 明文）"


def test_gold_query_fingerprint_domain_is_unique(rw_row: psycopg.Connection) -> None:
    """唯一 `(ast_fingerprint, domain)` = 防重复沉淀（§12.3）。"""
    domain = f"{_PREFIX}uniq"
    _insert_gold(rw_row, name="f1", tenant_id=None, domain=domain, fingerprint="fp_dup")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_gold(rw_row, name="f2", tenant_id="tenant_a", domain=domain, fingerprint="fp_dup")


def test_gold_query_allows_null_verifier(rw_row: psycopg.Connection) -> None:
    """`verified_by` / `verified_at` 可空**是刻意的**：种子与批量导入没有人工审核人。

    钉成 NOT NULL 会逼写入方编一个审核人 —— 那正是"编造数据"。
    """
    gid = _insert_gold(
        rw_row, name="seed", tenant_id=None, domain=f"{_PREFIX}seed", fingerprint="fp_seed"
    )
    row = rw_row.execute(
        "SELECT verified_by FROM app.gold_query WHERE gold_id = %s", (gid,)
    ).fetchone()
    assert row == (None,)
