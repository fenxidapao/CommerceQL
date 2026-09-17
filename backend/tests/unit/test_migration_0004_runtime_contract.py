"""迁移 0004 的离线契约测试 —— 两份真相的比对点（U-18 纪律）。

归属窗口：W1B。

0004 的两处"同一事实写两遍"风险，都在本文件钉死：

| 两份真相 | 漂移的后果 |
|---|---|
| `CostEntry`（W3A `budget.py`，落库写入方的行结构）↔ `cost_ledger` 列（本迁移） | sink 的 INSERT 起初能跑，W3A 加/改字段后**静默丢列**——账本缺列不报错，聚合悄悄算少 |
| `BindingState`/`BindingLayer`（W0 `enums.py`）↔ `query_plan` CHECK 字面 | 枚举加一个态 → DB CHECK 静默拒绝 → W4 写计划全部失败（且是运行期才炸） |

⚠️ 只测**离线可证**的形状；表真的建出来、CHECK 真的拒数据，在
`tests/integration/test_migration_0004_runtime.py`（真库）。
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.enums import BindingLayer, BindingState
from app.llm.budget import CostEntry

pytestmark = pytest.mark.contract

_BACKEND = Path(__file__).resolve().parents[2]
_MIGRATION_0004 = (
    _BACKEND / "app" / "repo" / "migrations" / "versions" / "0004_cost_ledger_and_query_plan.py"
)

#: CostEntry 里**刻意不落库**的两个标记（W3A docstring 明写"cost_ledger 无此列"）。
_NON_PERSIST_FIELDS = frozenset({"tokens_estimated", "price_guess"})


@pytest.fixture(scope="module")
def mig() -> Any:
    """按路径加载 0004 模块（`versions/` 不是常规包，文件名以数字开头无法 import）。"""
    spec = importlib.util.spec_from_file_location("mig_0004", _MIGRATION_0004)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_columns(ddl: str) -> list[tuple[str, str]]:
    """从 CREATE TABLE 块解析 `(列名, 类型)`（够用即可，不做完整 SQL 解析）。

    ⚠️ 两个正则细节都是注入演练抓出来的（scripts/drill_0004_contract_injection.py）：
    1. 类型分支把 `NUMERIC(14, 6)` 放在最前、收尾用 `(?=\\s|$)` 而不是 `\\b`：
       `\\b` 在右括号后不成立（`)` 与空格都是非词字符），会把 cost_cny 整行漏掉；
    2. `(?=\\s|$)` 里的 `$` 不能省：去掉行尾逗号后，"行尾正好是类型"的行
       （如 `extra_col text,`）会因 lookahead 失败被静默跳过 —— 解析器漏列 =
       契约测试对"多列漂移"假绿。
    """
    columns: list[tuple[str, str]] = []
    for line in ddl.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith(("CREATE", ")")):
            continue
        m = re.match(
            r"^(\w+)\s+(NUMERIC\(14, 6\)|text|bigint|boolean|timestamptz|jsonb|numeric)(?=\s|$)",
            line,
        )
        if m:
            columns.append((m.group(1), m.group(2)))
    return columns


# ============================================================================
# 1. CostEntry ↔ cost_ledger 列（双向 + 含序）
# ============================================================================

def test_cost_entry_fields_and_migration_columns_match(mig: Any) -> None:
    """字段↔列**双向**比对（防单侧增删）且**含序**（INSERT 列名按字段序生成，序错位不报错只写错）。"""
    entry_fields = [f.name for f in fields(CostEntry) if f.name not in _NON_PERSIST_FIELDS]
    ddl_columns = [name for name, _ in _parse_columns(mig._DDL_COST_LEDGER)]
    assert ddl_columns == entry_fields, (
        f"cost_ledger 列与 CostEntry 字段不一致（含序）：\n"
        f"  仅迁移有: {sorted(set(ddl_columns) - set(entry_fields))}\n"
        f"  仅 CostEntry 有: {sorted(set(entry_fields) - set(ddl_columns))}\n"
        f"  迁移列序: {ddl_columns}\n  字段序: {entry_fields}"
    )


def test_cost_cny_column_precision_matches_quantize_step(mig: Any) -> None:
    """`cost_cny` 的 NUMERIC 精度必须无损容纳 W3A 的量化步长（0.000001，ROUND_HALF_UP）。"""
    columns = dict(_parse_columns(mig._DDL_COST_LEDGER))
    precision = columns["cost_cny"]
    m = re.fullmatch(r"NUMERIC\((\d+), (\d+)\)", precision)
    assert m, f"cost_cny 应为 NUMERIC(p, s) 形态，实为 {precision!r}"
    scale = int(m.group(2))
    step = Decimal("0.000001").as_tuple().exponent  # = -6
    assert scale == -step, (
        f"cost_cny 精度 ({precision}) 与 compute_cost 的量化步长 {step} 不符 —— "
        f"丢精度的账本在对账时才暴露，那是财务口径的静默错误"
    )


def test_cost_ledger_has_both_aggregate_indexes(mig: Any) -> None:
    """预算聚合的两条路径必须有索引支撑（§12.3 原文）：(tenant_id, created_at) + (created_at)。"""
    joined = " ".join(mig._IX_COST_LEDGER)
    assert "ix_cost_ledger_tenant_time" in joined and "(tenant_id, created_at)" in joined
    assert "ix_cost_ledger_time" in joined and "ON app.cost_ledger (created_at)" in joined


# ============================================================================
# 2. enums（W0 所有）↔ query_plan CHECK 字面
# ============================================================================

def test_binding_state_check_matches_enums(mig: Any) -> None:
    """`binding_state` CHECK 字面 ↔ `BindingState` 取值集：双向、逐字。"""
    assert set(mig._BINDING_STATES) == {s.value for s in BindingState}, (
        f"CHECK 字面与 BindingState 漂移：\n"
        f"  仅迁移有: {sorted(set(mig._BINDING_STATES) - {s.value for s in BindingState})}\n"
        f"  仅枚举有: {sorted({s.value for s in BindingState} - set(mig._BINDING_STATES))}"
    )


def test_binding_layer_check_matches_enums(mig: Any) -> None:
    """`binding_layer` CHECK 字面 ↔ `BindingLayer` 取值集：双向、逐字（含大小写 —— 'L1' 不是 'l1'）。"""
    layer_values = {ly.value for ly in BindingLayer}
    assert set(mig._BINDING_LAYERS) == layer_values, (
        f"CHECK 字面与 BindingLayer 漂移：\n"
        f"  仅迁移有: {sorted(set(mig._BINDING_LAYERS) - layer_values)}\n"
        f"  仅枚举有: {sorted(layer_values - set(mig._BINDING_LAYERS))}"
    )


def _check_literals_from_ddl(ddl: str, column: str) -> set[str]:
    """从 DDL 文本里**独立解析** `CHECK (col IN (...))` 的字面值。

    ⚠️ 为什么不拿 `_BINDING_STATES` 渲染后比对：两边同源 = 恒真断言（注入演练
    ② 实测抓到）。只有"从 DDL 文本反向解析"才能抓住"有人把占位符换成手写字面"。
    """
    m = re.search(rf"{column} IN \(([^)]*)\)", ddl)
    assert m, f"DDL 里没有 {column} 的 CHECK IN 子句 —— CHECK 被删了也是漂移"
    return {item.strip().strip("'\"") for item in m.group(1).split(",") if item.strip()}


def test_ddl_embedding_of_check_literals(mig: Any) -> None:
    """CHECK 字面真的嵌进了 DDL 文本，且与元组一致（从 DDL 独立解析，防占位符被换成手写清单）。"""
    assert _check_literals_from_ddl(mig._DDL_QUERY_PLAN, "binding_state") == set(mig._BINDING_STATES)
    assert _check_literals_from_ddl(mig._DDL_QUERY_PLAN, "binding_layer") == set(mig._BINDING_LAYERS)


# ============================================================================
# 3. 权限面（离线可证的 SQL 形状；库侧行为在集成测试）
# ============================================================================

def test_app_rw_gets_insert_select_only(mig: Any) -> None:
    """账本与计划行**不可改**：app_rw 只允许 INSERT/SELECT，UPDATE/DELETE/TRUNCATE 必须缺席。"""
    import inspect

    source = inspect.getsource(mig)
    assert "GRANT SELECT, INSERT ON app.cost_ledger TO app_rw" in source
    assert "GRANT SELECT, INSERT ON app.query_plan TO app_rw" in source
    # 负向：实际执行的 GRANT **语句**（行首）不得对这两张表授 UPDATE/DELETE ——
    # ⚠️ 必须锚定行首的 GRANT：不锚定会把 docstring 里讨论 "GRANT/UPDATE" 的正文扫进来（真踩过）。
    for forbidden in (
        r"^\s*GRANT[^;\n]*UPDATE[^;\n]*ON app\.(cost_ledger|query_plan)",
        r"^\s*GRANT[^;\n]*DELETE[^;\n]*ON app\.(cost_ledger|query_plan)",
    ):
        assert not re.search(forbidden, source, re.M), f"迁移出现了禁止的授权形态：{forbidden}"
