"""迁移 0005 的离线契约测试 —— 两份真相的比对点（U-18 纪律）。

归属窗口：W1B。

0005 建 `feedback` + `gold_query` 两张表，本文件钉死四类"同一事实写两遍"的风险：

| 两份真相 | 漂移的后果 |
|---|---|
| `FeedbackReasonCode`（W0 `enums.py`，10 值）↔ `feedback.reason_code` 的 CHECK 字面 | 枚举加/改值 → DB CHECK 静默拒绝 → W4 端点写反馈全部失败（运行期才炸） |
| `FEEDBACK_COLUMNS`（写入通道白名单）↔ `0005` 的列集 | 迁移加列而通道不写 → **静默丢字段**（不报错，只是那一列永远 NULL） |
| 表列集 ↔ `docs/07 §12.3` 的表行 | 有人"顺手"补列 → 文档与库不再对得上，且补列没有依据可查 |
| `NULL` 比较的两处（`UNIQUE NULLS NOT DISTINCT` ↔ `IS NOT DISTINCT FROM`） | 只做一边 ⇒ 幂等看起来存在、实际失效（见下 §3） |

⚠️ 只测**离线可证**的形状；表真的建出来、CHECK 真的拒数据、权限真的拦 UPDATE，
在 `tests/integration/test_feedback_store_pg.py`（真库）。
"""

from __future__ import annotations

import importlib.util
import inspect
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.enums import FeedbackReasonCode
from app.repo.feedback import FEEDBACK_COLUMNS, FEEDBACK_REQUIRED_COLUMNS, FEEDBACK_TABLE

pytestmark = pytest.mark.contract

_BACKEND = Path(__file__).resolve().parents[2]
_MIGRATION_0005 = (
    _BACKEND / "app" / "repo" / "migrations" / "versions" / "0005_feedback_and_gold_query.py"
)

# ============================================================================
# docs/07 §12.3:2354-2355 的表行**逐字**抄下来的列集（不含 §12.3 没写的列）。
# 它们的作用不是"期望值"，而是**补列的登记点**：任何超出这两个集合的列都必须
# 出现在 `_REGISTERED_EXTRA_COLUMNS` 里，否则测试红 —— 补列不许悄悄扩散。
# ============================================================================

_SECTION_12_3_FEEDBACK = frozenset(
    {
        "feedback_id",
        "task_id",
        "user_id",
        "is_correct",
        "reason_code",
        "corrected_sql",
        "comment",
    }
)
_SECTION_12_3_GOLD_QUERY = frozenset(
    {
        "gold_id",
        "tenant_id",
        "question",
        "sql",
        "domain",
        "verified_by",
        "verified_at",
        "source",
        "ast_fingerprint",
    }
)

#: 0005 **刻意**超出 §12.3 表行的列（各有另一处规范性依据，见迁移文件头）：
#:   · `feedback.correct_result_hint` ← `docs/02 §A.6` 的请求字段（表行漏了）
#:   · `gold_query.bundle_version`   ← `docs/07 §11.7` 检索 SQL 的 `= :active_version`
#: 这是**唯一**允许超出 §12.3 的清单（同 0004 的 `query_plan.binding_layer` 先例）。
_REGISTERED_EXTRA_COLUMNS = {
    "feedback": {"correct_result_hint"},
    "gold_query": {"bundle_version"},
}


@pytest.fixture(scope="module")
def mig() -> Any:
    """按路径加载 0005 模块（`versions/` 不是常规包，文件名以数字开头无法 import）。"""
    spec = importlib.util.spec_from_file_location("mig_0005", _MIGRATION_0005)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_columns(ddl: str) -> list[tuple[str, str]]:
    """从 CREATE TABLE 块解析 `(列名, 类型)`（够用即可，不做完整 SQL 解析）。

    ⚠️ 三个细节都是 0004 那轮注入演练抓出来的（`scripts/drill_0004_contract_injection.py`）：
    1. 类型分支收尾用 `(?=\\s|$)` 而不是 `\\b`：`)` 与空格都是非词字符，`\\b` 不成立；
    2. `$` 不能省（去掉行尾逗号后，"行尾正好是类型"的行会被 lookahead 静默跳过
       ⇒ 解析器漏列 = 契约测试对"多列漂移"假绿）；
    3. **表级约束行必须跳过**（`CONSTRAINT … UNIQUE …` 会被第 1 组误当列名）。
    """
    columns: list[tuple[str, str]] = []
    for line in ddl.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith(("CREATE", ")", "CONSTRAINT")):
            continue
        m = re.match(r"^(\w+)\s+(text|boolean|timestamptz|jsonb|numeric)(?=\s|$)", line)
        if m:
            columns.append((m.group(1), m.group(2)))
    return columns


# ============================================================================
# 1. FeedbackReasonCode（W0 所有）↔ feedback.reason_code 的 CHECK 字面
# ============================================================================

def test_reason_code_tuple_matches_enums(mig: Any) -> None:
    """`_FEEDBACK_REASON_CODES` ↔ `FeedbackReasonCode`：双向、逐字。"""
    literal = set(mig._FEEDBACK_REASON_CODES)
    enum_values = {code.value for code in FeedbackReasonCode}
    assert literal == enum_values, (
        f"CHECK 字面与 FeedbackReasonCode 漂移：\n"
        f"  仅迁移有: {sorted(literal - enum_values)}\n"
        f"  仅枚举有: {sorted(enum_values - literal)}"
    )


def test_reason_code_check_literals_are_embedded_in_ddl(mig: Any) -> None:
    """CHECK 字面**真的嵌进 DDL 文本** —— 从 DDL 独立解析，防"元组对了但 DDL 里换了手写清单"。

    ⚠️ 不能拿 `_FEEDBACK_REASON_CODES` 渲染后比对：两边同源 = 恒真断言
    （0004 的注入演练②实测抓到过这种假绿）。
    """
    m = re.search(r"reason_code IN \(([^)]*)\)", mig._DDL_FEEDBACK)
    assert m, "0005 的 feedback DDL 里没有 reason_code 的 CHECK IN 子句 —— CHECK 被删了也是漂移"
    from_ddl = {item.strip().strip("'\"") for item in m.group(1).split(",") if item.strip()}
    assert from_ddl == {code.value for code in FeedbackReasonCode}


# ============================================================================
# 2. 列集：写入通道 ↔ 迁移 ↔ §12.3（含序 + 补列登记）
# ============================================================================

def test_feedback_columns_match_channel_and_migration(mig: Any) -> None:
    """`FEEDBACK_COLUMNS` ↔ 0005 的 `feedback` 列：双向且**含序**（INSERT 按序生成，序错位只写错不报错）。"""
    ddl_columns = [name for name, _ in _parse_columns(mig._DDL_FEEDBACK)]
    assert ddl_columns == list(FEEDBACK_COLUMNS), (
        f"feedback 列与 FEEDBACK_COLUMNS 不一致（含序）：\n"
        f"  仅迁移有: {sorted(set(ddl_columns) - set(FEEDBACK_COLUMNS))}\n"
        f"  仅通道有: {sorted(set(FEEDBACK_COLUMNS) - set(ddl_columns))}\n"
        f"  迁移列序: {ddl_columns}\n  通道列序: {list(FEEDBACK_COLUMNS)}"
    )


def test_feedback_extra_columns_are_registered(mig: Any) -> None:
    """`feedback` 超出 §12.3 表行的列**恰好**等于登记清单（多一个就红）。

    ⚠️ 必须从**迁移 DDL** 取列，不能从 `FEEDBACK_COLUMNS` 取 —— 首版用的是后者，
    注入演练①（给 DDL 加一个 `extra_col`）只红了"列集一致"那条，这条**静默绿**：
    它当时测的其实是"通道自己的白名单",与"迁移里多了什么列"无关（典型的假绿）。
    """
    ddl_columns = {name for name, _ in _parse_columns(mig._DDL_FEEDBACK)}
    extra = ddl_columns - _SECTION_12_3_FEEDBACK
    assert extra == _REGISTERED_EXTRA_COLUMNS["feedback"], (
        f"feedback 出现了未登记的补列：{sorted(extra - _REGISTERED_EXTRA_COLUMNS['feedback'])}\n"
        f"（补列必须有另一处规范性依据，并同时更新迁移文件头与本清单）"
    )


def test_gold_query_columns_match_section_12_3_plus_registered(mig: Any) -> None:
    """`gold_query` 列集 = §12.3 表行 + 已登记补列（双向，含序冻结）。"""
    ddl_columns = [name for name, _ in _parse_columns(mig._DDL_GOLD_QUERY)]
    expected = (
        "gold_id",
        "tenant_id",
        "question",
        "sql",
        "domain",
        "verified_by",
        "verified_at",
        "source",
        "ast_fingerprint",
        "bundle_version",
    )
    assert ddl_columns == list(expected), (
        f"gold_query 列与冻结清单不一致（含序）：\n"
        f"  实为: {ddl_columns}\n  期望: {list(expected)}\n"
        f"  （§12.3 表行 ∪ 已登记补列 {sorted(_REGISTERED_EXTRA_COLUMNS['gold_query'])}）"
    )
    extra = set(ddl_columns) - _SECTION_12_3_GOLD_QUERY
    assert extra == _REGISTERED_EXTRA_COLUMNS["gold_query"]


def test_gold_query_has_no_tier_column(mig: Any) -> None:
    """**禁止** `tier` 列：物理判据是 `tenant_id IS NULL`（`GoldQueryTier` docstring 明文）。"""
    names = {name for name, _ in _parse_columns(mig._DDL_GOLD_QUERY)}
    assert "tier" not in names, (
        "gold_query 出现了 tier 列 —— 那是同一事实的第二份真相（归属层已由 tenant_id 是否 NULL 表达）"
    )


def test_source_column_has_no_check_constraint(mig: Any) -> None:
    """`source` 刻意**没有** CHECK：07/PRD 只给了列名、没给取值集，W1B 不发明值集。

    这条断言的作用是**反向护栏**：若有人后来凭想象加了 `CHECK (source IN (...))`，
    必须先把值集的权威来源写进文档（届时改这里并注明依据）。
    """
    assert not re.search(r"source\s+IN \(", mig._DDL_GOLD_QUERY), (
        "gold_query.source 出现了 CHECK 取值集 —— 文档未定义该值集，添加等于发明契约"
    )


# ============================================================================
# 3. NULL 比较的两处必须成对（这是 0005 最关键的一条）
# ============================================================================

def test_feedback_unique_constraint_is_nulls_not_distinct(mig: Any) -> None:
    """唯一键必须带 `NULLS NOT DISTINCT`。

    `reason_code` 可空（§A.6 标 ⭕），而 PG 里 `NULL != NULL` ⇒ 不加这三个词，
    "同 task+同 reason 视为同一条"（§A.6 幂等 / §12.3 唯一键）**当场失效**，
    且失效方式是"约束看起来在、实际拦不住" —— 本仓库最忌讳的假护栏形态。
    """
    assert "UNIQUE NULLS NOT DISTINCT (task_id, user_id, reason_code)" in mig._DDL_FEEDBACK, (
        "feedback 的唯一键缺少 NULLS NOT DISTINCT —— 空 reason_code 会绕过幂等约束"
    )


def test_channel_read_back_uses_is_not_distinct_from() -> None:
    """回读必须用 `IS NOT DISTINCT FROM`（`=` 遇到 NULL 恒为 NULL ⇒ 永远查不到）。"""
    from app.repo import feedback as channel

    assert "IS NOT DISTINCT FROM" in channel._FIND_SQL, (
        "回读用了 `=` —— 空 reason_code 的重复提交将永远匹配不到已存在的行，"
        "与唯一约束的行为不一致（约束拦住了、回读却找不到）"
    )


# ============================================================================
# 4. 访问面（离线可证的 SQL 形状；库侧行为在集成测试）
# ============================================================================

def test_channel_exposes_only_insert_and_find() -> None:
    """写入通道只暴露 `insert_feedback` / `find_feedback_id`，没有 upsert / update / delete。"""
    from app.repo import feedback as channel

    public = {
        name
        for name, member in inspect.getmembers(channel.FeedbackStore, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {"insert_feedback", "find_feedback_id"}, f"访问面被扩大：{sorted(public)}"


def test_channel_source_has_no_mutation_or_on_conflict() -> None:
    """源码里没有针对本表的 `UPDATE` / `DELETE` / `TRUNCATE`，也没有 `ON CONFLICT`。

    ⚠️ 只扫**去掉 docstring 后的代码**：通道的 docstring 刻意在讨论这些禁用形态
    （解释"为什么不用 upsert"），直接对源码做正则会把说明文字当违规（0004 那轮踩过）。
    """
    from app.repo import feedback as channel

    source = inspect.getsource(channel.FeedbackStore.insert_feedback)
    source += inspect.getsource(channel.FeedbackStore.find_feedback_id)
    for forbidden in ("UPDATE ", "DELETE ", "TRUNCATE", "ON CONFLICT"):
        assert forbidden not in source.upper(), f"写入通道出现了禁用形态：{forbidden}"


def test_app_rw_gets_insert_select_only(mig: Any) -> None:
    """两张表都是**永久沉淀资产**：app_rw 只允许 INSERT/SELECT，UPDATE/DELETE 必须缺席。"""
    source = inspect.getsource(mig)
    assert "GRANT SELECT, INSERT ON app.feedback TO app_rw" in source
    assert "GRANT SELECT, INSERT ON app.gold_query TO app_rw" in source
    # 负向：实际执行的 GRANT **语句**（行首）不得对这两张表授 UPDATE/DELETE ——
    # ⚠️ 必须锚定行首，否则会把 docstring 里讨论 "GRANT/UPDATE" 的正文扫进来（0004 真踩过）。
    for forbidden in (
        r"^\s*GRANT[^;\n]*UPDATE[^;\n]*ON app\.(feedback|gold_query)",
        r"^\s*GRANT[^;\n]*DELETE[^;\n]*ON app\.(feedback|gold_query)",
    ):
        assert not re.search(forbidden, source, re.M), f"迁移出现了禁止的授权形态：{forbidden}"


def test_required_columns_are_not_nullable_in_ddl(mig: Any) -> None:
    """`FEEDBACK_REQUIRED_COLUMNS` 与 DDL 的 NOT NULL 一致（否则"必填在 Python 层挡、DB 层放行"）。

    ⚠️ `PRIMARY KEY` **隐含 NOT NULL**（PG 语义，真库 `\\d app.feedback` 实测为 not null）——
    只认字面 `NOT NULL` 会把 `feedback_id` 判成可空（首版就是这么红的）。
    """
    not_null: set[str] = set()
    for line in mig._DDL_FEEDBACK.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or stripped.startswith(("CREATE", ")", "CONSTRAINT")):
            continue
        m = re.match(r"^(\w+)\s+\S+", stripped)
        if m and ("NOT NULL" in stripped or "PRIMARY KEY" in stripped):
            not_null.add(m.group(1))
    assert not_null >= FEEDBACK_REQUIRED_COLUMNS, (
        f"以下列被声明为必填但 DDL 允许 NULL：{sorted(FEEDBACK_REQUIRED_COLUMNS - not_null)}"
    )
    assert FEEDBACK_TABLE == "app.feedback"
