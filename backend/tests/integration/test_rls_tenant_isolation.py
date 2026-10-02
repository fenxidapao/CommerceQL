"""跨租户 RLS 的**行为级**断言（一次性容器；**禁共享 `ecom`**）—— QA A4 的两条。

`docs/01` 把「跨租户数据泄露」列为**硬红线**（`:609`，不达标 = 立即阻断上线）并把
**数据库层 RLS** 定为**最终边界**（`:1265`、`§11.2:1271`）⇒ 这条边界必须有**可复算的行为断言**，
而不是只数 `pg_policies` 有几行（数对象 = 证明"策略存在"，不证明"策略会拦"）。

本文件补的两条（QA 10-02 指派的 ③）：

- **(a) 未设身份 ⇒ 零行**：`app_ro` 拿不到任何身份 GUC 时，6 张租户表的视图**一律 0 行**
  （fail-closed：漏注入的失效方向必须是"什么都看不到"，不是"全看得见"）。
- **(b) `app.shop_ids` 两态**：**未设**（NULL）vs **显式置空串 `''`** 必须**可区分** ——
  `''` 在本策略里是**正面语义**（= 该租户全部店铺，`07 §7.4`），未设是 fail-closed。
  ⚠️ **只测未设会恒绿**：两态都断言"看见全部行"的写法会把 `07` 细节 4（U-109）否掉的那条
  coalesce 当成通过 ⇒ 必须同时断言 **未设 = 0 行** 与 **`''` = 该租户全量**，且两者**不等**。

## ⚠️ 本文件的关键前提：6 张表不是同一种形状（3 / 3 分裂）

策略模板是**按列存在性**二选一的（`app/semantics/materialize.py:167-174`）：

- **有 `shop_id` 列** ⇒ 两分支：
  `tenant_id = current_setting('app.tenant_id', true) AND (current_setting('app.shop_ids', true) = ''
   OR shop_id = ANY (string_to_array(current_setting('app.shop_ids', true), ',')))`
- **无 `shop_id` 列** ⇒ 单分支：`tenant_id = current_setting('app.tenant_id', true)`

实测（一次性容器 `information_schema.columns`）：**只有 3 张基表带 `shop_id`**
（`order_paid` / `product` / `shop`），另 3 张**没有**（`order_refund` / `campaign` / `traffic_daily`，
其 PK 分别是 `(tenant_id, refund_id)` / `(tenant_id, campaign_id)` / `(tenant_id, stat_date, sku_id, channel)`）。

⇒ **`shop_ids` 只对有店铺轴的 3 张表有意义**；对另外 3 张它是**惰性**的（改它读数不变）。
把 6 张表当同一种形状写断言，是"只测了半边还看不出来"的典型 —— 因此本文件：

1. 用 `test_shop_axis_presence_matches_derivation_rule` 把这条 3/3 分裂**钉成结构断言**
   （DB 列存在性 ↔ `pg_policies.qual` 是否含 `shop_ids` ↔ 静态声明，三面互证）；
2. (b) 的**主体**只对有店铺轴的 3 张表断言"未设 ≠ `''`"；
3. (b) 的**对照半边**对无店铺轴的 3 张表断言"`shop_ids` 三态恒等" —— 这才让"分裂是设计使然"
   从叙述变成可复算读数。

读路径口径：`app_ro` 对 6 张**基表零 GRANT**（U-55(a)/0003），唯一入口是 `v_*` 视图；
视图以属主 `app_rw` 权限执行，而基表 `FORCE ROW LEVEL SECURITY` ⇒ 策略按 GUC 过滤。
因此本文件读**视图**（这才是生产路径），而不是基表。

跑法（一次性容器，例：cwd = `backend/`；venv 在**仓库根**，故是 `../.venv`）：

    docker run -d --name pg-rls-w2a -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=ecom_rls \\
      -p 55432:5432 pgvector/pgvector:pg16
    COMMERCEQL_TEST_SUPER_DSN=postgresql://postgres:postgres@127.0.0.1:55432/ecom_rls \\
    COMMERCEQL_TEST_RW_DSN=postgresql://app_rw:app_rw_pwd@127.0.0.1:55432/ecom_rls \\
    COMMERCEQL_TEST_RO_DSN=postgresql://app_ro:app_ro_pwd@127.0.0.1:55432/ecom_rls \\
      ../.venv/Scripts/python.exe -m pytest tests/integration/test_rls_tenant_isolation.py -v

缺 env = 当场 fail（U-114 防线①，禁止 skip、禁止字面默认 DSN）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest

from tests.integration._env_dsn import env_dsn

pytestmark = pytest.mark.integration

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent
_REAL_BUNDLE = _REPO / "semantic" / "bundle_2026.09.14.1.yaml"

_SUPER = env_dsn("COMMERCEQL_TEST_SUPER_DSN")
_RW = env_dsn("COMMERCEQL_TEST_RW_DSN")
_RO = env_dsn("COMMERCEQL_TEST_RO_DSN")

#: 6 张 tenant_scoped=true 的租户基表（bundle 声明 ⇒ materialize 派生策略）。
_TENANT_BASES = (
    "order_paid",
    "order_refund",
    "product",
    "shop",
    "campaign",
    "traffic_daily",
)

#: ★ 3/3 分裂（见模块 docstring）：只有这 3 张基表**有** `shop_id` 列 ⇒ 策略含店铺分支。
_SHOP_SCOPED = ("order_paid", "product", "shop")

#: 另 3 张**无** `shop_id` ⇒ 策略只有租户分支，`app.shop_ids` 对它们**惰性**。
_TENANT_ONLY = ("order_refund", "campaign", "traffic_daily")

assert set(_SHOP_SCOPED) | set(_TENANT_ONLY) == set(_TENANT_BASES), (
    "静态分裂声明必须恰好覆盖 6 张租户基表（导入期自检）"
)

#: 种子计划 = **每个 (租户, 店铺) 对、每表 1 行**。
#:
#: ⚠️ 为什么不是"每对多行"：`shop` 的主键 = `(tenant_id, shop_id)`（实测），
#: 同一对插两行会撞 PK；把每对压到 1 行，是 6 张表**共用同一套种子计划**的唯一写法。
#: 而"`''` 是严格超集"这条仍然成立：T_A 的 `''` = 2 行（S1 + S2），`'S1'` = 1 行 ⇒ 2 > 1。
_PAIRS = (("T_A", "S1"), ("T_A", "S2"), ("T_B", "S1"))

_T_A_TOTAL = sum(1 for t, _s in _PAIRS if t == "T_A")  # = 2
_T_A_S1 = sum(1 for t, s in _PAIRS if (t, s) == ("T_A", "S1"))  # = 1
_T_B_TOTAL = sum(1 for t, _s in _PAIRS if t == "T_B")  # = 1


def _sqla(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def _libpq(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


_SUPER_LIBPQ = _libpq(_SUPER)
_RW_LIBPQ = _libpq(_RW)
_RO_LIBPQ = _libpq(_RO)

_TEXTUAL = ("text", "character varying", "character", "uuid")


def _placeholder(col: str, data_type: str, tag: str, seq: int) -> Any:
    """按列类型造**唯一**占位值（PK 列也走这里 ⇒ 不能重复）。"""
    if data_type in _TEXTUAL:
        return f"{col}-{tag}"
    if data_type in ("integer", "bigint", "smallint", "numeric", "double precision", "real"):
        return seq + 1
    if data_type == "boolean":
        return False
    if data_type == "date":
        return "2026-01-01"
    if data_type.startswith("timestamp"):
        return "2026-01-01 00:00:00"
    return f"{col}-{tag}"


def _insert_row(conn: Any, table: str, tenant: str, shop: str, tag: str) -> None:
    """往基表塞 1 行（自动补齐 NOT NULL 无默认列）。

    身份列的处理**按列存在**：`tenant_id` 必写；`shop_id` **有才写** ——
    `order_refund` / `campaign` / `traffic_daily` 根本没有这一列（3/3 分裂）。
    """
    all_cols = conn.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default, is_identity
          FROM information_schema.columns
         WHERE table_schema = 'app' AND table_name = %s
         ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    names = {name for name, *_ in all_cols}
    assert "tenant_id" in names, f"app.{table} 无 tenant_id 列 —— 租户策略无从谈起"
    has_shop = "shop_id" in names
    identity_cols = {"tenant_id"} | ({"shop_id"} if has_shop else set())
    # 必填 = NOT NULL 且无默认且非 identity；**再加上**身份列
    # （身份列可能可空，那时不在必填集里，但本测试必须自己写值，否则策略两支都拿不到可比对的值）。
    required = [
        (name, dtype)
        for name, dtype, nullable, default, identity in all_cols
        if (nullable == "NO" and default is None and identity == "NO") or name in identity_cols
    ]
    cols = [name for name, _t in required]
    values: dict[str, Any] = {}
    for name, dtype in required:
        if name == "tenant_id":
            values[name] = tenant
        elif name == "shop_id":
            values[name] = shop
        else:
            values[name] = _placeholder(name, dtype, tag, 0)
    placeholders = ", ".join(["%s"] * len(cols))
    conn.execute(
        f"INSERT INTO app.{table} ({', '.join(cols)}) VALUES ({placeholders})",
        tuple(values[c] for c in cols),
    )


def _pg_available() -> bool:
    """探活必须用 **SUPER** DSN —— `app_rw`/`app_ro` 是 0001 建的，首次跑时还不存在；
    用它们探活会把"库刚建好、还没迁"误判成"PG 不可达"（自锁：skip 掉真正该跑的迁移）。"""
    try:
        psycopg.connect(_libpq(_SUPER), connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def upgraded() -> Any:
    """真跑 `alembic upgrade head`（0001→…→head；幂等）。"""
    if not _pg_available():
        pytest.skip("PG 不可达（一次性容器未起）→ 不计为通过")
    env = {
        **os.environ,
        "MIGRATION_DATABASE_URL": _sqla(_SUPER),
        "DATABASE_URL": _sqla(_RW),
        # ⚠️ 必须是 **RO**（0001 从这里取 `app_ro` 的密码）—— 传成 RW 会撞
        # `dsn.py:94` 的 N-02 断言"DATABASE_URL 与 ANALYTICS_DB_URL 不得相同"。
        "ANALYTICS_DB_URL": _sqla(_RO),
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"alembic upgrade head 失败:\n{result.stdout}\n{result.stderr}"
    return _SUPER


_SEED_TENANTS = tuple(sorted({t for t, _s in _PAIRS}))  # = ('T_A', 'T_B')


def _purge_seed_tenants(conn: Any) -> None:
    """只删**本文件种的租户**（`tenant_id = ANY(_SEED_TENANTS)`），**绝不整表 DELETE**。

    ⚠️ 为什么这条纪律是硬的：`_env_dsn` 只挡"**静默**落到共享库"，挡不住有人**显式**
    export 共享 `ecom` 的 DSN（CI 就是这么做的，指它自己的 service container）。
    共享 `ecom` 里 `app.order_paid` 有 ~49 万行（W7 的 load 数据）—— 一个不带谓词的
    `DELETE FROM app.order_paid` 会把它们全抹掉。用租户谓词后最坏情况是删掉同名的
    `T_A`/`T_B` 行，而两个租户号是本文件发明的测试字面量（真实租户形如 `t_1001`，
    见 `test_migration_0003_views.py:224`）。
    """
    for table in _TENANT_BASES:
        # ⚠️ 传 `list` 不是 `tuple`：psycopg 把 Python tuple 适配成**复合类型行**
        # （渲染成 `(T_A,T_B)` ⇒ PG 报 malformed array literal），只有 list 才适配成 PG 数组。
        conn.execute(f"DELETE FROM app.{table} WHERE tenant_id = ANY (%s)", (list(_SEED_TENANTS),))


@pytest.fixture(scope="module")
def seeded(upgraded: Any) -> Any:
    """灌两租户种子 + `materialize(with_policy=True)`（策略由语义包派生，ADR-10）；**收尾归还**。

    ⚠️ **种子走 SUPER**（不是 app_rw）：`materialize` 给基表开了 `FORCE ROW LEVEL SECURITY`，
    而 `FORCE` 只对**表属主**生效 —— 超级用户**永远**绕过 RLS（`rolbypassrls` 无关）。
    用 app_rw 灌种子，在同一容器上**重跑**本文件时会撞 WITH CHECK（未设 GUC ⇒ 新增行不满足
    `tenant_id = current_setting(...)`）而报 "new row violates row-level security policy"。
    种子是**测试前置**、不是被测路径（被测路径是下面 `app_ro` 读视图），走 SUPER 才幂等。
    """
    from app.semantics import load_bundle
    from app.semantics.materialize import materialize

    rw = psycopg.connect(_SUPER_LIBPQ, connect_timeout=5, autocommit=True)
    try:
        _purge_seed_tenants(rw)
        for table in _TENANT_BASES:
            for tenant, shop in _PAIRS:
                _insert_row(rw, table, tenant, shop, f"{table}-{tenant}-{shop}")
    finally:
        rw.close()

    # materialize 的派生语句走 app_rw；search_path 显式给 app（与 0003 测试同口径）。
    sep = "&" if "?" in _RW_LIBPQ else "?"
    dsn_sp = _RW_LIBPQ + sep + "options=-c%20search_path%3Dapp%2Cpublic"
    report = materialize(load_bundle(_REAL_BUNDLE), dsn=dsn_sp, with_policy=True)
    assert report.grant_policy_executed, "GRANT/POLICY 段未执行 ⇒ RLS 未落，后续断言无意义"

    yield report

    # 收尾：把库还原成"没来过"（CI 单进程跑全套时，不给后面的用例留脏数据）。
    done = psycopg.connect(_SUPER_LIBPQ, connect_timeout=5, autocommit=True)
    try:
        _purge_seed_tenants(done)
    finally:
        done.close()


def _count(view: str, set_config: dict[str, str] | None) -> int:
    """**每条语句一条新连接**：GUC 是会话级的，复用连接会让"未设"态被上一次的 SET 污染。"""
    conn = psycopg.connect(_RO_LIBPQ, connect_timeout=5, autocommit=True)
    try:
        for key, val in (set_config or {}).items():
            conn.execute("SELECT set_config(%s, %s, false)", (key, val))
        row = conn.execute(f"SELECT count(*) FROM app.{view}").fetchone()
        assert row is not None, "count(*) 必须返回恰好一行"
        return int(row[0])
    finally:
        conn.close()


def _policy_quals() -> dict[str, str]:
    """读 6 张表的策略表达式（`pg_policies.qual`），供结构断言比对。"""
    conn = psycopg.connect(_RW_LIBPQ, connect_timeout=5, autocommit=True)
    try:
        rows = conn.execute(
            """
            SELECT tablename, qual
              FROM pg_policies
             WHERE schemaname = 'app' AND tablename = ANY (%s)
            """,
            (list(_TENANT_BASES),),
        ).fetchall()
    finally:
        conn.close()
    return {name: (qual or "") for name, qual in rows}


# ============================================================================
# 结构钉子：3/3 分裂是真的（DB 列 ↔ 策略文本 ↔ 静态声明）
# ============================================================================


def test_shop_axis_presence_matches_derivation_rule(seeded: Any) -> None:
    """★ 把"哪几张表有店铺轴"钉成三面互证 —— 它是 (b) 分组断言的前提。

    `materialize.py:167` 按 `asset.has_column("shop_id")` 二选一生成策略 ⇒
    **DB 列存在性、`pg_policies.qual` 是否含 `shop_ids`、本文件的静态分组** 三者必须一致。
    任一面漂了（例如有人给 `order_refund` 加了 `shop_id`、或改了派生模板），这条先红，
    从而避免 (b) 在"表形状已变"的静默前提下给出假绿。

    反面（本用例的存在理由）：若 (b) 把 6 张表一律当"有店铺轴"，
    `order_refund` 那格会在未设态返回 0（恰好等于期望的 fail-closed 值）而"通过"，
    但它的 0 是因为策略里**没有店铺分支**、且 tenant_id 也没设 —— 两回事，读数却一样。
    """
    conn = psycopg.connect(_RW_LIBPQ, connect_timeout=5, autocommit=True)
    try:
        rows = conn.execute(
            """
            SELECT table_name
              FROM information_schema.columns
             WHERE table_schema = 'app' AND column_name = 'shop_id'
               AND table_name = ANY (%s)
            """,
            (list(_TENANT_BASES),),
        ).fetchall()
    finally:
        conn.close()
    db_has_shop = {r[0] for r in rows}

    assert db_has_shop == set(_SHOP_SCOPED), (
        f"DB 里带 shop_id 的表 = {sorted(db_has_shop)}，静态声明 = {sorted(_SHOP_SCOPED)}"
        " —— 3/3 分裂已变，本文件的分组断言前提失效"
    )

    quals = _policy_quals()
    assert set(quals) == set(_TENANT_BASES), (
        f"pg_policies 只覆盖 {sorted(quals)}，期望 6 张 —— 有表没派生策略"
    )
    for base in _SHOP_SCOPED:
        assert "shop_ids" in quals[base], (
            f"app.{base} 有 shop_id 列，但策略文本里没有 shop_ids 分支：{quals[base]!r}"
        )
    for base in _TENANT_ONLY:
        assert "shop_ids" not in quals[base], (
            f"app.{base} 无 shop_id 列，策略文本却出现 shop_ids：{quals[base]!r}"
        )


# ============================================================================
# (a) 未设身份 ⇒ 6 张租户表零行可见（fail-closed）
# ============================================================================


def test_no_identity_yields_zero_rows_on_all_six_tenant_views(seeded: Any) -> None:
    """★ 未注入任何身份 GUC ⇒ 6 张表的视图一律 0 行。

    失效方向：这里若 > 0，等于"漏注入 = 全租户可见"（`07 §13.3` 细节 1/4 要防的那一侧）。
    本条对 6 张表**统一成立**（无店铺轴的 3 张也一样：`tenant_id = NULL` ⇒ 行全滤）。
    """
    conn = psycopg.connect(_RO_LIBPQ, connect_timeout=5, autocommit=True)
    try:
        row = conn.execute("SELECT current_setting('app.tenant_id', true)").fetchone()
        assert row is not None, "current_setting(...) 必须返回恰好一行"
        assert row[0] is None, "本连接上 app.tenant_id 竟然有值 ⇒ 不是'未设'态，本断言的前提不成立"
    finally:
        conn.close()

    for base in _TENANT_BASES:
        assert _count(f"v_{base}", None) == 0, (
            f"未设身份时 app.v_{base} 仍可见行 —— RLS 没有失败关闭"
        )


# ============================================================================
# (b) shop_ids 两态：未设 ≠ 显式 '' —— 主体（有店铺轴的 3 张表）
# ============================================================================


def test_shop_ids_unset_vs_explicit_empty_is_distinguishable(seeded: Any) -> None:
    """★ `app.shop_ids` 未设（NULL）⇒ 0 行；显式 `''` ⇒ **该租户全部行**；两者必须不等。

    只测"未设"会**恒绿**（NULL 走任何比较都是 NULL ⇒ 恒 0 行），因此这条同时断言
    `''` 的正语义与 `'S1'` 的子集语义 —— 三个读数缺一个都证明不了 `''` 的含义。
    ⚠️ `07 §13.3` 细节 4（U-109）：**禁止**把未设 coalesce 成 `''`。若有人加了那个
    coalesce，本用例的**态①**（未设 = 0 行）会变红 —— 那正是它存在的理由。
    """
    for base in _SHOP_SCOPED:
        unset = _count(f"v_{base}", {"app.tenant_id": "T_A"})
        empty = _count(f"v_{base}", {"app.tenant_id": "T_A", "app.shop_ids": ""})
        only_s1 = _count(f"v_{base}", {"app.tenant_id": "T_A", "app.shop_ids": "S1"})

        assert unset == 0, (
            f"app.v_{base}：shop_ids **未设**时应 0 行（fail-closed），实际 {unset} 行"
        )
        assert empty == _T_A_TOTAL, (
            f"app.v_{base}：shop_ids='' 应 = 该租户全部 {_T_A_TOTAL} 行，实际 {empty} 行"
        )
        assert only_s1 == _T_A_S1, (
            f"app.v_{base}：shop_ids='S1' 应 = 该店铺 {_T_A_S1} 行，实际 {only_s1} 行"
        )
        assert unset != empty, "未设与空串不可区分 ⇒ 细节 4 的边界已被抹掉"


# ============================================================================
# (b) 对照半边：无店铺轴的 3 张表，shop_ids **惰性**（三态恒等）
# ============================================================================


def test_shop_ids_is_inert_on_tables_without_shop_column(seeded: Any) -> None:
    """★ 无 `shop_id` 的 3 张表：策略里**没有**店铺分支 ⇒ `shop_ids` 三态读数**恒等**。

    `materialize.py:174` 对这些表生成的 USING 只有 `tenant_id = current_setting(...)`
    ⇒ 无论 `app.shop_ids` 未设 / `''` / `'S1'`，都只按租户过滤 ⇒ 三态都 = 该租户全量。

    ⚠️ 这条不是"凑数"：它把"`shop_ids` 只对有店铺轴的表有意义"从**叙述**变成**读数**。
    若有人把店铺分支错加到这几张表上（例如误用 `*` 代替列清单），
    这里未设态会从 `_T_A_TOTAL` 掉到 0 ⇒ 立刻红。
    """
    for base in _TENANT_ONLY:
        states = {
            "未设": _count(f"v_{base}", {"app.tenant_id": "T_A"}),
            "空串": _count(f"v_{base}", {"app.tenant_id": "T_A", "app.shop_ids": ""}),
            "S1": _count(f"v_{base}", {"app.tenant_id": "T_A", "app.shop_ids": "S1"}),
        }
        for label, n in states.items():
            assert n == _T_A_TOTAL, (
                f"app.v_{base}：无 shop_id 列 ⇒ shop_ids({label}) 应惰性、读数 = 租户全量 "
                f"{_T_A_TOTAL}，实际 {n} 行（三态读数：{states}）"
            )


# ============================================================================
# (b) 跨租户半边：'' 只放开本租户，不顺带看到别家
# ============================================================================


def test_empty_shop_ids_never_leaks_another_tenant(seeded: Any) -> None:
    """`''`（不限店铺）**只**放开本租户的店铺 —— 6 张表都不许顺带看到 T_B。

    这条是 (b) 的跨租户半边：`shop_ids=''` 若被实现成"无条件放行"，上一条仍会绿
    （T_A 行数照样对），而这条会红。
    """
    for base in _TENANT_BASES:
        a_rows = _count(f"v_{base}", {"app.tenant_id": "T_A", "app.shop_ids": ""})
        b_rows = _count(f"v_{base}", {"app.tenant_id": "T_B", "app.shop_ids": ""})
        assert a_rows == _T_A_TOTAL, f"app.v_{base}：T_A 应见 {_T_A_TOTAL} 行，实际 {a_rows} 行"
        assert b_rows == _T_B_TOTAL, f"app.v_{base}：T_B 应见 {_T_B_TOTAL} 行，实际 {b_rows} 行"
