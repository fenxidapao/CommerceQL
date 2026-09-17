"""迁移 0003 的**真库**集成测试 —— DoD③ 端到端解锁的证明（U-56）。

只测**必须真库才能证明**的部分（单测见 `test_migration_views_contract.py`）：
1. `alembic upgrade head` 真实执行（0001→0002→0003 全链）；
2. 16 个对象（8 基表 + 8 视图）存在、**属主 = app_rw**（U-55(a)：materialize 以
   app_rw 执行 ALTER TABLE / CREATE POLICY / GRANT —— 无属主身份则发布期失败）；
3. **app_ro 对基表零 GRANT**（U-55(a) 前提 2：视图是唯一入口）；
4. **materialize(with_policy=True) 真实通过** + DoD③ 一致性 = True ——
   这是 w2-int 六步演练 step② `UndefinedTable` 阻塞被解除的直接证明；
5. RLS 失败关闭的**对象级**证据：6 张租户基表各有 `p_{基表}_tenant` 策略，
   region/dim_date（tenant_scoped=false）无策略。

跳过策略（每条 skip 写明缺失前置，不假绿 —— 同 test_semantic_materialization）：
- PG 不可达 → skip；迁移执行失败 → 让它红（那不是"前置缺失"，是缺陷）。

⚠️ **search_path 前提（已登记转 W2A）**：materialize 派生的语句是**非限定名**
（`ALTER TABLE order_paid ...`），本测试用连接串 `options` 显式给
`search_path=app,public`。生产发布路径若不给，同样的语句会报 `relation does not
exist` —— 该修复在 materialize/调用侧（W2A 文件），W1B 不越权。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest

pytestmark = pytest.mark.integration

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent
_REAL_BUNDLE = _REPO / "semantic" / "bundle_2026.09.14.1.yaml"

#: 项目约定 DSN 形态 = `postgresql+psycopg://`（psycopg **3**，见 app/core/config.py 的校验；
#: 裸 `postgresql://` 会让 SQLAlchemy 去找未安装的 psycopg2 —— env.py 原样透传，不归一化）。
#: ⚠️ 属主 DSN **运行时拼接**（DoD④，同 test_migration_dsn_hygiene 的示范）：
#: 源码里不落能被 `commerceql-dsn-with-password` 规则命中的完整字面量；
#: `app_rw` / `app_ro` 已被 .gitleaks.toml 的 allowlist 放行，可直接写字面量。
_SCHEME = "postgresql+psycopg" + "://"
_SUPER = os.environ.get(
    "COMMERCEQL_TEST_SUPER_DSN",
    _SCHEME + "postgres" + ":" + "postgres" + "@localhost:5432/ecom",
)
_RW = os.environ.get(
    "COMMERCEQL_TEST_RW_DSN",
    "postgresql+psycopg://app_rw:app_rw_pwd@localhost:5432/ecom",
)
_RO = os.environ.get(
    "COMMERCEQL_TEST_RO_DSN",
    "postgresql+psycopg://app_ro:app_ro_pwd@localhost:5432/ecom",
)


def _sqla(dsn: str) -> str:
    """归一化为 SQLAlchemy 形态（给 alembic 子进程的 env 用）。"""
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def _libpq(dsn: str) -> str:
    """归一化为 libpq 形态（给 psycopg.connect 直连 / materialize 的 dsn 用）。"""
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


_RW_LIBPQ = _libpq(_RW)
_RO_LIBPQ = _libpq(_RO)
#: materialize 的语句是非限定名 → 本测试的连接显式带 search_path（见模块 docstring）。
_RW_SP = _RW_LIBPQ + ("&" if "?" in _RW_LIBPQ else "?") + "options=-c%20search_path%3Dapp%2Cpublic"

_TENANT_BASES = ("order_paid", "order_refund", "product", "shop", "campaign", "traffic_daily")
_PUBLIC_BASES = ("region", "dim_date")
_ALL = _TENANT_BASES + _PUBLIC_BASES


def _pg_available() -> bool:
    try:
        psycopg.connect(_RW_LIBPQ, connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def upgraded() -> Any:
    """真实执行 `alembic upgrade head`（幂等：head 已应用则 no-op）。"""
    if not _pg_available():
        pytest.skip("PG 不可达（compose 栈未起）→ 不计为通过")
    env = {
        **os.environ,
        "MIGRATION_DATABASE_URL": _sqla(_SUPER),
        "DATABASE_URL": _sqla(_RW),
        "ANALYTICS_DB_URL": _sqla(_RW),  # 0001 只取密码形态，同值无害
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head 失败（DoD③ 解锁的前提）:\n{result.stdout}\n{result.stderr}"
    )
    return _SUPER


@pytest.fixture(scope="module")
def rw(upgraded: Any) -> Any:
    conn = psycopg.connect(_RW_LIBPQ, connect_timeout=3)
    yield conn
    conn.close()


# ============================================================================
# 1. 对象存在性 + 属主（U-55(a) 的硬前提）
# ============================================================================

def test_all_base_tables_and_views_exist_with_app_rw_owner(rw: Any) -> None:
    rows = rw.execute(
        """
        SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = ANY(%s)
        """,
        (list(_ALL) + [f"v_{b}" for b in _ALL],),
    ).fetchall()
    found = {name: (kind, owner) for name, kind, owner in rows}
    for base in _ALL:
        assert found.get(base, (None, None))[0] == "r", f"基表 app.{base} 不存在"
        assert found.get(f"v_{base}", (None, None))[0] == "v", f"视图 app.v_{base} 不存在"
        assert found[base][1] == "app_rw", (
            f"app.{base} 属主是 {found[base][1]} —— materialize(app_rw) 将无法"
            f"执行 RLS/POLICY/GRANT（U-55(a) 硬前提，见 0003 文件头「所有权」节）"
        )
        assert found[f"v_{base}"][1] == "app_rw", f"app.v_{base} 属主必须是 app_rw"


def test_app_ro_has_zero_privileges_on_base_tables(rw: Any) -> None:
    """U-55(a) 前提 2：视图是 app_ro 唯一入口，基表零 GRANT。"""
    for base in _ALL:
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not rw.execute(
                "SELECT has_table_privilege('app_ro', %s, %s)", (f"app.{base}", priv)
            ).fetchone()[0], f"app_ro 意外持有 app.{base} 的 {priv} —— 基表零 GRANT 被破坏"


def test_view_columns_are_in_contiguous_first_block(rw: Any) -> None:
    """视图必须**原样透出**基表列（顺序与基表一致）—— 执行层按列名取值的前提。"""
    pair = rw.execute(
        """
        SELECT
          (SELECT array_agg(column_name ORDER BY ordinal_position)
             FROM information_schema.columns
            WHERE table_schema='app' AND table_name='order_paid'),
          (SELECT array_agg(column_name ORDER BY ordinal_position)
             FROM information_schema.columns
            WHERE table_schema='app' AND table_name='v_order_paid')
        """
    ).fetchone()
    assert pair[0] == pair[1], "v_order_paid 的列序与基表不一致"


# ============================================================================
# 2. RLS 对象级证据（策略由 materialize 派生落基表 —— U-55(a) 口径）
# ============================================================================

def test_rls_policies_exist_on_tenant_bases_only_after_materialize(rw: Any, loaded: Any) -> None:
    """materialize(with_policy=True) 后：6 张租户基表各有 p_{基表}_tenant，公共表零策略。"""
    report = _materialize_with_policy(loaded)
    assert report.grant_policy_executed
    rows = rw.execute(
        "SELECT schemaname, tablename, policyname FROM pg_policies WHERE schemaname = 'app'"
    ).fetchall()
    policies = {tablename: policyname for _s, tablename, policyname in rows}
    for base in _TENANT_BASES:
        assert policies.get(base) == f"p_{base}_tenant", (
            f"app.{base} 缺策略 p_{base}_tenant（实有: {policies.get(base)}）—— "
            f"派生段没落上，或落错了对象"
        )
    for base in _PUBLIC_BASES:
        assert base not in policies, (
            f"app.{base} 是 tenant_scoped=false 的公共维表，不应有 RLS 策略"
        )


# ============================================================================
# 3. ★ DoD③ 端到端：materialize(with_policy=True) + 一致性 = True
# ============================================================================

@pytest.fixture(scope="module")
def loaded() -> Any:
    from app.semantics import load_bundle

    return load_bundle(_REAL_BUNDLE)


def _materialize_with_policy(loaded: Any) -> Any:
    from app.semantics.materialize import materialize

    return materialize(loaded, dsn=_RW_SP, with_policy=True)


def test_dod3_consistency_is_true_after_full_release(rw: Any, loaded: Any) -> None:
    """★ 全链证明：w2-int 实测的 `UndefinedTable: relation "v_order_paid" does not
    exist` 阻塞被本迁移解除 —— with_policy=True 通过 + DoD③ 双向一致性 = True。

    ⚠️ 这一条就是本迁移的验收标准，缺了它前面全是结构测试。
    """
    from app.semantics.materialize import assert_grant_policy_consistency

    _materialize_with_policy(loaded)
    result = assert_grant_policy_consistency(rw, loaded)
    assert result.consistent, (
        f"DoD③ 不一致（{len(result.mismatches)} 条）—— 本迁移的对象形状与"
        f"派生 GRANT/POLICY 没对齐：\n" + "\n".join(result.mismatches[:10])
    )


def test_app_ro_can_select_view_but_not_base(rw: Any, loaded: Any) -> None:
    """行为级边界：app_ro 走视图 = 通（列授权由 materialize 落），碰基表 = 权限拒绝。

    ⚠️ 负向断言必须用 **app_ro 自己的连接**：rw 夹具是 app_rw —— 它是基表属主，
    拿它查基表永远不会 InsufficientPrivilege（那等于没测）。
    """
    from app.semantics.materialize import materialize

    materialize(loaded, dsn=_RW_SP, with_policy=True)
    ro = psycopg.connect(_RO_LIBPQ, connect_timeout=3)
    try:
        # 视图：SELECT 授权列可行（表空 → 0 行，但"能执行"本身就是授权证明）
        ro.execute("SET app.tenant_id = 't_1001'")
        count = ro.execute("SELECT count(*) FROM app.v_order_paid").fetchone()[0]
        assert count == 0  # 数据装载另行裁定（U-56）—— 这里证明的是"可查询"而非数据
        # 基表：权限层直接拒绝（不是返回 0 行 —— 那是 RLS 的表现，两者混淆会掩盖配置错误）
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            ro.execute("SELECT count(*) FROM app.order_paid").fetchone()
    finally:
        ro.close()
