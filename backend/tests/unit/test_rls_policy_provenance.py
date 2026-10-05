"""RLS 策略的**来源与形状**断言（W1B 域：迁移 + 语义派生器两侧）。

--------------------------------------------------------------------------
为什么需要这个文件（QA 验收窗口第一轮 ④）
--------------------------------------------------------------------------
外部问的是："现库 6 条 policy 是否**全部由迁移产出**"。

**答案是否 —— 迁移产出 0 条。** 6 条 policy 与 6 张表的 RLS 来自
`app/semantics/materialize.py::derive_policy_statements()`（ADR-10：由语义包派生、
**绝不手写**），由 `materialize(with_policy=True)` 在**发布事务内**执行；
`0003_business_views.py` 的 docstring 自己写着"**RLS / POLICY / GRANT 一条都不在这里**"。

⇒ 对拍形态必须是「**派生器 ⇒ 现库**」，写成「迁移 ⇒ 现库」**不是漂移、是测错了对象**
（一个"迁移 0 vs 现库 6"的表看起来像缺 6 条，实际是 0 条本就该是 0）。

--------------------------------------------------------------------------
本文件钉四件（零 DB、零 LLM、可进 unit 套件）
--------------------------------------------------------------------------
① **迁移侧零产**：扫 `versions/` 下**所有**四位前缀迁移（当前 `0001`–`0006`，glob 自动跟新文件）
   的**非 docstring** 字符串常量，不得出现可执行的
   `CREATE POLICY` / `ENABLE|FORCE ROW LEVEL SECURITY`。
   ⚠️ **必须走 AST 且排除 docstring**：`0003` 的 docstring 里**就有**这两个词
   ⇒ 纯文本 `grep` 会**假阳**（本项目已有"grep 到就算命中"的教训族）。
② **ENABLE / FORCE 必须成对**：实测现库 6 张表 `relrowsecurity=t` 且
   `relforcerowsecurity=t`、`owner=app_rw` ⇒ **真正让策略生效的是 `FORCE`**：
   PG 里**表属主对 RLS 免疫**（走的是所有权豁免，**不是** `rolbypassrls` 属性）
   ⇒ 只 `ENABLE` 不 `FORCE` = **假边界**（对外读数会像"启了 RLS"）。
③ **谓词两形态**：资产有 `shop_id` 列 ⇒ USING 必含店铺子句；无 ⇒ 必**不含**。
④ **具名登记"租户级但无店铺列"的表集合，只减不增**（见下）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.semantics import load_bundle
from app.semantics.materialize import derive_policy_statements

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
_MIGRATIONS = Path(__file__).resolve().parents[2] / "app" / "repo" / "migrations" / "versions"

#: 本断言集只对**可执行的 SQL 文本**下结论，故先列出要查的两个短语。
_FORBIDDEN_IN_MIGRATIONS = (
    "CREATE POLICY",
    "ENABLE ROW LEVEL SECURITY",
    "FORCE ROW LEVEL SECURITY",
)

#: ④ 具名登记：`tenant_scoped=true` 但语义资产**没有 `shop_id` 列** ⇒ 派生出的策略
#: **只能表达租户、表达不了店铺**（`app.shop_ids` 对它们零影响）。
#: ⚠️ 与 `07 §13.2` 的"**行级范围只有 `shop_ids` 一个维度**"直接冲突：对这 3 张表，
#: L3（RLS，§13.4 的"最后一道边界"）**无法**表达店铺维度 ⇒ 一个被限店的
#: `finance`/`operator` 用户，从这些资产上读到的是**整个租户**的行。
#: ⇒ 本集合**只减不增**（新增即红：新增的每张表都要先被判过一次）。
_TENANT_SCOPED_WITHOUT_SHOP_COLUMN = {"campaign", "order_refund", "traffic_daily"}


# ============================================================================
# 工具：取"非 docstring"的字符串常量
# ============================================================================


def _docstring_value_ids(tree: ast.AST) -> set[int]:
    """收集所有 docstring 节点的 `id()`（Module / Function / AsyncFunction / Class 的首个 Expr）。"""
    ids: set[int] = set()
    owners = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, owners):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _executable_sql_literals(path: Path) -> list[str]:
    """迁移文件里**可能被执行**的字符串常量（排除 docstring 与普通注释文本）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_value_ids(tree)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append(node.value)
    return out


def _migration_files() -> list[Path]:
    files = sorted(p for p in _MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))
    assert files, f"未找到迁移文件：{_MIGRATIONS}"
    return files


# ============================================================================
# ① 迁移侧零产
# ============================================================================


def test_migrations_emit_no_rls_or_policy() -> None:
    """迁移**不得**产出任何 RLS / POLICY 语句（ADR-10：由语义包派生）。"""
    offenders: list[str] = []
    for path in _migration_files():
        for text in _executable_sql_literals(path):
            for needle in _FORBIDDEN_IN_MIGRATIONS:
                if needle in text:
                    offenders.append(f"{path.name}: 可执行常量里出现 {needle!r}")
    assert offenders == [], (
        "迁移里出现了 RLS/POLICY 语句 —— 这会与语义派生器形成**两份真相**：\n  "
        + "\n  ".join(offenders)
    )


def test_docstring_exclusion_is_effective() -> None:
    """⚠️ 反向对照：证明"排除 docstring"这一步**真的在起作用**。

    不写这条的话，① 的绿色可以有两种成因：**迁移里确实没有**、或者
    **扫描器把所有内容都当成了 docstring**。`0003` 的模块 docstring 里**确含**
    `CREATE POLICY` —— 拿它当阳性标本：原文含该短语，可执行常量里不含。
    """
    path = _MIGRATIONS / "0003_business_views.py"
    raw = path.read_text(encoding="utf-8")
    assert "CREATE POLICY" in raw, "阳性标本失效：0003 的 docstring 不再含该短语，请另选标本"

    literals = _executable_sql_literals(path)
    assert any("CREATE TABLE" in text for text in literals), (
        "扫描器没抓到可执行常量：0003 里有 `CREATE TABLE ...` 的 SQL 字面量"
    )
    assert not any("CREATE POLICY" in text for text in literals), (
        "扫描器把 docstring 也算进来了 ⇒ ① 的绿色是**假绿**"
    )


# ============================================================================
# ② / ③ / ④ 派生侧形状
# ============================================================================


@pytest.fixture(scope="module")
def stmts() -> object:
    return derive_policy_statements(load_bundle(REAL_BUNDLE))  # type: ignore[arg-type]


_TARGET_RE = re.compile(r"\b(?:ON|ALTER\s+TABLE)\s+(\S+)", re.IGNORECASE)


def _target_table(stmt: str) -> str:
    """从 `... ON app."order_paid"...` / `ALTER TABLE app."order_paid" ...` 取出**基表名**。

    ⚠️ 两个坑（本文件第一版各踩一次，共 4 条红）：① 目标是 `app."order_paid"`，
    "取第一个标识符"的正则会把 **`app`（schema）** 当表名；② `ALTER TABLE` 语句里
    **没有 `ON`** ⇒ 只用 `ON` 抓会直接 `assert` 失败（同一条语句两种形态都要认）。
    """
    m = _TARGET_RE.search(stmt)
    assert m, f"语句里找不到目标表：{stmt[:80]!r}"
    raw = m.group(1).rstrip(";").rstrip(",")
    return raw.rsplit(".", 1)[-1].strip('"')


def _policy_names(stmts: object) -> dict[str, str]:
    """`{基表名: 策略名}`。"""
    out: dict[str, str] = {}
    for stmt in stmts.policy_sql:  # type: ignore[attr-defined]
        m = re.search(r'CREATE POLICY "?([A-Za-z0-9_]+)"?\s+ON\b', stmt)
        assert m, f"策略语句形状变了，断言需同步：{stmt[:80]!r}"
        out[_target_table(stmt)] = m.group(1)
    return out


def _rls_targets(stmts: object, keyword: str) -> set[str]:
    """`ALTER TABLE <目标> {keyword} ROW LEVEL SECURITY` 的目标基表集。"""
    got: set[str] = set()
    for stmt in stmts.rls_sql:  # type: ignore[attr-defined]
        if re.search(rf"\b{keyword}\s+ROW\s+LEVEL\s+SECURITY\b", stmt):
            got.add(_target_table(stmt))
    return got


def test_rls_enable_and_force_are_paired(stmts: object) -> None:
    """② ENABLE 与 FORCE 必须**逐表成对**（只 ENABLE = 属主豁免 ⇒ 假边界）。"""
    enabled = _rls_targets(stmts, "ENABLE")
    forced = _rls_targets(stmts, "FORCE")
    assert enabled, "派生器没产出任何 ENABLE ROW LEVEL SECURITY"
    assert enabled == forced, (
        "ENABLE / FORCE 目标不一致 —— 差异表上的策略对**属主（app_rw）无效**：\n"
        f"  只 ENABLE 未 FORCE = {sorted(enabled - forced)}\n"
        f"  只 FORCE 未 ENABLE = {sorted(forced - enabled)}"
    )


def test_policy_naming_contract(stmts: object) -> None:
    """③ 策略名契约 = `p_{基表}_tenant`，且与 RLS 目标表同集。"""
    names = _policy_names(stmts)
    assert names, "派生器没产出任何 CREATE POLICY"
    for table, name in names.items():
        assert name == f"p_{table}_tenant", f"{table} 的策略名 {name!r} 不符契约"
    assert set(names) == _rls_targets(stmts, "ENABLE"), "策略表集与 RLS 表集不一致"


def test_shop_predicate_follows_column(stmts: object) -> None:
    """③ 有 `shop_id` 列 ⇒ 含店铺子句；无 ⇒ 不含（谓词不得凭空出现）。"""
    bundle = load_bundle(REAL_BUNDLE)
    has_col = {
        asset.physical_asset.removeprefix("v_"): asset.has_column("shop_id")
        for asset in bundle.active_assets.values()
        if asset.tenant_scoped
    }
    for stmt in stmts.policy_sql:  # type: ignore[attr-defined]
        table = _target_table(stmt)
        with_shop = "shop_id" in stmt
        assert with_shop == has_col[table], (
            f"{table}: 谓词含 shop_id={with_shop}，而资产列 shop_id={has_col[table]}"
        )


def test_tenant_scoped_without_shop_column_set_only_shrinks(stmts: object) -> None:
    """④ 登记集**只减不增**：租户级但无店铺列的表，行级范围表达不了店铺。"""
    bundle = load_bundle(REAL_BUNDLE)
    current = {
        asset.physical_asset.removeprefix("v_")
        for asset in bundle.active_assets.values()
        if asset.tenant_scoped and not asset.has_column("shop_id")
    }
    added = current - _TENANT_SCOPED_WITHOUT_SHOP_COLUMN
    assert not added, (
        "新增了「租户级但无 shop_id 列」的资产 ⇒ 它的 RLS 策略只能表达租户、"
        "**表达不了店铺**（与 §13.2「行级范围只有 shop_ids」冲突）："
        f"{sorted(added)}\n"
        "请先判：补列 / 补 join 谓词 / 或显式接受并扩写本断言里的登记集。"
    )
    assert current, "登记集已空 ⇒ 请删掉本断言（前提消失）"
