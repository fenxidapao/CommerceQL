"""`repo/cost_ledger.py` 的离线断言（真库行为在 `tests/integration/test_migration_0004_runtime.py`）。

归属窗口：W1B。

核心要钉住的一件事：**R-DEP-2 禁止 repo import llm** ⇒ sink 用本地结构化 Protocol
与 W3A 的 `CostEntry`/`CostLedgerSink` 隔开。结构一致这件事没有编译器兜底
（结构化子类型在调用点才校验，而调用点在 W4，还没人写）—— 所以必须在这里
逐字段/逐签名比对，否则两边漂移会静默到 W4 装配那天才炸。
"""

from __future__ import annotations

import inspect
from dataclasses import fields
from typing import Any, get_type_hints

import pytest

from app.llm.budget import CostEntry
from app.llm.budget import CostLedgerSink as W3ASinkProtocol
from app.repo.cost_ledger import (
    _GLOBAL_SPENT_SQL,
    _INSERT_SQL,
    _TENANT_SPENT_SQL,
    CostLedgerSinkProto,
    DbCostLedgerSink,
    LedgerEntryProto,
    _conninfo_for,
)

pytestmark = pytest.mark.contract

_NON_PERSIST_FIELDS = frozenset({"tokens_estimated", "price_guess"})


# ============================================================================
# 1. 结构兼容：CostEntry（W3A，落库写入方）↔ LedgerEntryProto（repo，落库执行方）
# ============================================================================

def _proto_member_hints() -> dict[str, Any]:
    """从 `LedgerEntryProto` 的 `@property` 提取 `(成员名 → 返回类型)`。

    ⚠️ 不能用 `get_type_hints(LedgerEntryProto)` —— 它只收集**类级注解**
    （`entry_id: str` 声明形式），拿不到 `@property def ... -> str` 的返回注解，
    会返回空 dict，让下方所有比对**空转变恒真**（本测试首轮就栽在这上面）。
    """
    hints: dict[str, Any] = {}
    for name, member in vars(LedgerEntryProto).items():
        if isinstance(member, property) and member.fget is not None:
            hints[name] = get_type_hints(member.fget)["return"]
    return hints


def test_cost_entry_is_structurally_compatible_with_local_proto() -> None:
    """逐字段比对：名字 + 类型注解，双向。

    ⚠️ 本地 Proto 刻意**不含** `tokens_estimated`/`price_guess`（W3A 的非落库标记），
    故只断"Proto 的每个成员都在 CostEntry 里且类型一致" + "CostEntry 的落库字段
    都被 Proto 覆盖"两个方向。
    """
    proto_hints = _proto_member_hints()
    assert proto_hints, "Proto 成员提取为空 —— 提取逻辑坏了，护栏空转"
    entry_hints = get_type_hints(CostEntry)  # dataclass 字段注解的统一解析口

    for name, ann in proto_hints.items():
        assert name in entry_hints, f"本地 Proto 多出 CostEntry 没有的成员：{name}"
        assert entry_hints[name] == ann, (
            f"成员 {name} 类型漂移：CostEntry={entry_hints[name]!r} vs Proto={ann!r}"
        )
    persist_fields = {n for n in entry_hints if n not in _NON_PERSIST_FIELDS}
    assert persist_fields == set(proto_hints), (
        f"覆盖缺口：CostEntry 落库字段里有 Proto 没覆盖的：{sorted(persist_fields - set(proto_hints))}"
    )


def test_insert_sql_column_list_matches_cost_entry_field_order() -> None:
    """INSERT 的列名清单（含序）= CostEntry 落库字段序 —— 列序错位不报错只写错，必须锁。"""
    import re

    m = re.search(r"\(([^)]*)\)\s*VALUES", _INSERT_SQL)
    assert m, "_INSERT_SQL 里解析不出列清单"
    sql_columns = [c.strip() for c in m.group(1).split(",")]
    field_order = [f.name for f in fields(CostEntry) if f.name not in _NON_PERSIST_FIELDS]
    assert sql_columns == field_order, (
        f"INSERT 列序与 CostEntry 字段序不一致：\n  SQL: {sql_columns}\n  字段: {field_order}"
    )


def test_sql_uses_bound_params_only() -> None:
    """N-04 纪律的形状面：三条 SQL 的占位符数量正确，且没有 f-string 拼值的痕迹。"""
    assert _INSERT_SQL.count("%s") == 11
    assert _TENANT_SPENT_SQL.count("%s") == 3  # tenant_id + 时区名 + day
    assert _GLOBAL_SPENT_SQL.count("%s") == 2  # 时区名 + day
    for sql in (_INSERT_SQL, _TENANT_SPENT_SQL, _GLOBAL_SPENT_SQL):
        assert "{" not in sql and "}" not in sql, "SQL 里出现插值痕迹（拼接风险）"


# ============================================================================
# 2. 与 W3A Protocol 的签名同构（不能 import 比对类型，就比对签名形状）
# ============================================================================

def test_local_sink_proto_matches_w3a_protocol_signature() -> None:
    """方法名 + 参数名逐一比对（类型注解必不同 —— 两边靠结构兼容，比签名形状就够了）。"""
    w3a_methods = {
        name: list(inspect.signature(m).parameters)
        for name, m in vars(W3ASinkProtocol).items()
        if callable(m) and not name.startswith("_")
    }
    local_methods = {
        name: list(inspect.signature(m).parameters)
        for name, m in vars(CostLedgerSinkProto).items()
        if callable(m) and not name.startswith("_")
    }
    assert w3a_methods == local_methods, (
        f"本地 Proto 与 W3A Protocol 的方法面漂移：\n"
        f"  W3A: {w3a_methods}\n  本地: {local_methods}"
    )


def test_db_sink_satisfies_local_proto() -> None:
    """`DbCostLedgerSink` 满足本地 Proto（runtime_checkable 的 isinstance 是形状检查）。"""
    sink = DbCostLedgerSink("postgresql+psycopg://app_rw:pw@localhost:5432/ecom")
    assert isinstance(sink, CostLedgerSinkProto)


# ============================================================================
# 3. conninfo 换算（U-53 教训：connect_timeout 必须带上）
# ============================================================================

def test_conninfo_converts_sqlalchemy_form_and_appends_timeout() -> None:
    assert (
        _conninfo_for("postgresql+psycopg://app_rw:pw@localhost:5432/ecom")
        == "postgresql://app_rw:pw@localhost:5432/ecom?connect_timeout=2"
    )


def test_conninfo_appends_to_existing_query_string() -> None:
    assert (
        _conninfo_for("postgresql+psycopg://app_rw:pw@localhost:5432/ecom?application_name=x")
        == "postgresql://app_rw:pw@localhost:5432/ecom?application_name=x&connect_timeout=2"
    )


def test_conninfo_rejects_unknown_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        _conninfo_for("mysql://app_rw:pw@localhost:5432/ecom")
