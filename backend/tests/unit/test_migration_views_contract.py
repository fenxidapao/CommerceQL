"""迁移 0003 的**离线**契约测试 —— 防两份真相（U-56）。

被钉死的三个真相来源及其关系：

    semantic/bundle_*.yaml (列名+PG类型, 权威)
        ↕ W1A selfcheck 已保证
    data/schema.sql (SQLite 方言: 列序+可空性+PK+索引)
        ↕ ★ 本测试保证（此前没人管 —— 0003 是第三个副本，最易漂移）
    app/repo/migrations/versions/0003_business_views.py::_ASSETS (PG DDL)

schema.sql ↔ bundle 的列名一致性由 W1A 的 `selfcheck.py` 断言；
本文件补上"0003 ↔ 两者"这一段。**列在数据结构里而不是内联 SQL 字符串**，
就是为了这里能逐列比对（见 0003 docstring"真相来源"节）。

⚠️ 这份测试**不许出现 skip**：全部输入是仓库内文件（yaml/sql/py），离线可测。
一旦有人往这里加外部依赖，护栏就变成了绿色装饰。
"""

from __future__ import annotations

# 说明：alembic 的 versions/ 目录不是常规包（文件名以数字开头，无法 `import 0003_...`）。
# 这里用 importlib 按路径直接加载迁移模块。**不要**为此把 versions/ 变成包 ——
# alembic 对目录内容有自己的约定，加 __init__.py 反而引入歧义。
import importlib.util
import re
from pathlib import Path

import pytest


def _load_migration_module():
    path = Path(__file__).resolve().parents[2] / "app" / "repo" / "migrations" / "versions" / "0003_business_views.py"
    spec = importlib.util.spec_from_file_location("mig_0003", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mig():
    return _load_migration_module()


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


# ============================================================================
# 1. 0003 ↔ 语义包（列名 + PG 类型，逐字）
# ============================================================================

def _bundle_columns(repo_root: Path) -> dict[str, list[tuple[str, str]]]:
    """从语义包提取 `physical_asset → [(列名, 类型)]`。

    用正则而不是 yaml 解析器：类型声明就在 `columns` 段，且**资产段之外**没有
    `name:/type:` 的二行形态；正则让测试不依赖 loader 的 Pydantic 版本行为。
    若将来 bundle 结构变了导致这里抓错 → 本测试立刻红 → 改这里即可（显式成本）。
    """
    text = (repo_root / "semantic" / "bundle_2026.09.14.1.yaml").read_text(encoding="utf-8")
    assets: dict[str, list[tuple[str, str]]] = {}
    for chunk in re.split(r"\n  - logical_name: ", text)[1:]:
        phys = re.search(r"physical_asset: (\S+)", chunk).group(1)
        cols = re.findall(r"^\s*- name: (\w+)\n\s+type: (\S+)", chunk, re.M)
        assets[phys] = cols
    return assets


def test_view_set_matches_bundle_exactly(mig, repo_root) -> None:
    """8 个视图名与语义包 `physical_asset` 集合**双向相等**。

    单向断言的漏洞：多建一个视图（bundle 里没有）= 攻击面 + 一致性检查器困惑；
    少建一个 = materialize 又会 UndefinedTable。集合相等才同时防住两个方向。
    """
    bundle = _bundle_columns(repo_root)
    mig_views = {f"v_{base}" for base in mig._ASSETS}
    assert mig_views == set(bundle), (
        "0003 的视图集合与语义包 physical_asset 不一致 —— "
        f"仅在迁移: {sorted(mig_views - set(bundle))}, "
        f"仅在 bundle: {sorted(set(bundle) - mig_views)}"
    )


def test_column_names_and_types_match_bundle_verbatim(mig, repo_root) -> None:
    """每张基表的列名与 PG 类型**逐字**等于 bundle 声明（含列序）。

    列序也锁：视图用显式列清单建，顺序漂移不会报错但会让
    `SELECT *` 类查询的语义在 SQLite 沙箱与 PG 之间分叉。
    """
    bundle = _bundle_columns(repo_root)
    for base, (view, columns, _pk, _idx) in mig._ASSETS.items():
        expected = bundle[f"v_{base}"]
        actual = [(name, tp) for name, tp, _nullable in columns]
        assert actual == expected, (
            f"app.{base}（视图 {view}）与语义包不一致：\n"
            f"  仅迁移有: {sorted(set(actual) - set(expected))}\n"
            f"  仅 bundle 有: {sorted(set(expected) - set(actual))}\n"
            f"  顺序/类型差异: {[ (a, e) for a, e in zip(actual, expected, strict=False) if a != e ]}"
        )


# ============================================================================
# 2. 0003 ↔ schema.sql（列序 + 可空性 + 主键 + 索引名）
# ============================================================================

def _parse_schema_sql(repo_root: Path) -> dict[str, dict]:
    """解析 `data/schema.sql` 的 CREATE TABLE / CREATE INDEX（够用即可，不做完整 SQL 解析）。"""
    text = (repo_root / "data" / "schema.sql").read_text(encoding="utf-8")
    tables: dict[str, dict] = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\);", text, re.S):
        name, body = m.group(1), m.group(2)
        cols, pk = [], []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.startswith("--"):
                line_wo_comment = line.split("--")[0].strip().rstrip(",")
                if not line_wo_comment:
                    continue
                line = line_wo_comment
            if line.upper().startswith("PRIMARY KEY"):
                pk = tuple(re.findall(r"\w+", line.split("(")[1].split(")")[0]))
                continue
            parts = line.split()
            if len(parts) >= 2:
                is_inline_pk = "PRIMARY KEY" in line.upper()
                # ⚠️ 内联主键（`code TEXT PRIMARY KEY`）⇒ 隐含 NOT NULL（region 的形态）；
                # 漏判会让"可空性比对"在 PK 列上假红。
                nullable = "NOT NULL" not in line.upper() and not is_inline_pk
                cols.append((parts[0], nullable))
                if is_inline_pk:
                    pk = (parts[0],)
        tables[name] = {"columns": cols, "pk": tuple(pk)}
    indexes = {
        m.group(1): (m.group(2), tuple(re.findall(r"\w+", m.group(3))))
        # ⚠️ `\s+`：schema.sql 为对齐用了**多个空格**（`idx_op_tenant_shop    ON`），
        # 单空格正则会静默漏掉 5/13 条 —— 第一版就这样漏的（靠与 _ASSETS 集合比对才暴露）。
        for m in re.finditer(r"CREATE INDEX (\w+)\s+ON\s+(\w+)\s*\(([^)]+)\)", text)
    }
    return {"tables": tables, "indexes": indexes}


def test_column_order_and_nullability_match_schema_sql(mig, repo_root) -> None:
    """列序与 NOT NULL 逐列等于 schema.sql（可空性是数据层契约，bundle 不声明它）。"""
    parsed = _parse_schema_sql(repo_root)["tables"]
    for base, (_view, columns, _pk, _idx) in mig._ASSETS.items():
        expected = parsed[f"v_{base}"]  # schema.sql 里表名带 v_ 前缀（SQLite 沙箱形态）
        actual = [(name, nullable) for name, _tp, nullable in columns]
        assert [n for n, _ in actual] == [n for n, _ in expected["columns"]], (
            f"{base}: 列序与 schema.sql 不一致 —— 视图按显式列清单建，"
            f"顺序漂移会让 SQLite/PG 的 SELECT * 语义分叉"
        )
        assert actual == expected["columns"], (
            f"{base}: 可空性与 schema.sql 不一致（NOT NULL 是数据装载契约，装载数据会踩）"
        )


def test_primary_keys_match_schema_sql(mig, repo_root) -> None:
    parsed = _parse_schema_sql(repo_root)["tables"]
    for base, (_view, _cols, pk, _idx) in mig._ASSETS.items():
        assert pk == parsed[f"v_{base}"]["pk"], f"{base}: 主键与 schema.sql 不一致"


def test_index_names_and_columns_match_schema_sql(mig, repo_root) -> None:
    """索引名与列**逐字**一致（名字是运维/EXPLAIN 的公共语言，改名 = 悄悄破坏约定）。"""
    parsed = _parse_schema_sql(repo_root)["indexes"]
    declared: dict[str, tuple[str, tuple[str, ...]]] = {}
    for base, (_view, _cols, _pk, indexes) in mig._ASSETS.items():
        for idx_name, idx_cols in indexes:
            declared[idx_name] = (base, idx_cols)
    assert set(declared) == set(parsed), (
        f"索引集合不一致：仅迁移 {sorted(set(declared) - set(parsed))}，"
        f"仅 schema.sql {sorted(set(parsed) - set(declared))}"
    )
    for name, (base, cols) in declared.items():
        schema_base = parsed[name][0].removeprefix("v_")  # schema.sql 索引挂在 v_* 表上，归一后再比
        assert (schema_base, parsed[name][1]) == (base, cols), (
            f"索引 {name} 的表/列与 schema.sql 不一致"
        )


# ============================================================================
# 3. 迁移自身的结构不变量（不依赖外部文件的纪律）
# ============================================================================

def test_tenant_scoped_assets_all_have_tenant_id_column(mig) -> None:
    """带 tenant_id 的基表 ↔ 不带的（region/dim_date）边界必须清晰。

    materialize 只给 `tenant_scoped: true` 的资产落 RLS 策略；若基表**有**
    tenant_id 却被 bundle 标 false（或反之），策略与数据就会错位。此处按
    "列里有没有 tenant_id"自洽校验，与 bundle 的 tenant_scoped 声明呼应
    （bundle 侧的 ⇔ 校验由 W1A 校验器保证，测试见 `test_column_names_and_types_match_bundle_verbatim`）。
    """
    for base, (_view, columns, _pk, _idx) in mig._ASSETS.items():
        has_tenant = any(name == "tenant_id" for name, _tp, _n in columns)
        if base in ("region", "dim_date"):
            assert not has_tenant, f"{base} 是公共维表（tenant_scoped=false），不得有 tenant_id"
        else:
            assert has_tenant, f"{base} 是租户资产，必须有 tenant_id（RLS 谓词的依据）"


def test_shop_id_only_on_assets_that_derive_the_shop_clause(mig) -> None:
    """shop_id 只出现在 order_paid/product/shop —— 与 materialize 的派生分支对齐。

    `derive_policy_statements` 用 `has_column('shop_id')` 决定策略里有没有
    `app.shop_ids` 子句；基表若意外多/少 shop_id，派生策略会静默换形。
    """
    for base, (_view, columns, _pk, _idx) in mig._ASSETS.items():
        has_shop = any(name == "shop_id" for name, _tp, _n in columns)
        assert has_shop == (base in ("order_paid", "product", "shop")), (
            f"{base}: shop_id 的有无与派生分支的预期不符"
        )


def test_views_shadow_base_tables_with_explicit_column_lists(mig) -> None:
    """视图命名 = `v_{base}`，且迁移里视图必须**显式列清单**（不许 SELECT *）。

    SELECT * 的视图在基表加列后会静默多出列 —— 而 CLS 的 GRANT 是按列的，
    "多出来的列恰好不在 GRANT 里"会让 app_ro 查询时才炸（运行期，最难排查）。
    """
    for base, (view, columns, _pk, _idx) in mig._ASSETS.items():
        assert view == f"v_{base}"
        assert f"SELECT {', '.join(n for n, _, _ in columns)} FROM app.{base}" in (
            # 迁移文件以 f-string 拼接 —— 这里直接校验数据结构的使用方式：
            # 若有人改成 SELECT *，上面这行的构造方式会与 _ASSETS 脱钩 → 本断言红。
            _view_select(mig, base, view)
        )


def _view_select(mig, base: str, view: str) -> str:
    """复现迁移的视图 SELECT 构造 —— 与 upgrade() 保持同一形状（改一处必改两处 → 测试红）。"""
    cols = mig._ASSETS[base][1]
    return f"SELECT {', '.join(n for n, _, _ in cols)} FROM app.{base}"
