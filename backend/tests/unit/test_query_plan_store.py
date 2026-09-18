"""`app/repo/query_plan.py` 写入通道的**代码层**自证（07 §12.3:2349 / §6.8.3 硬约束 5）。

归属窗口：W1B。

## 验什么 / 不验什么

**验**（离线，不连库）：
1. **只写**：公开面只有 `insert_query_plan`；模块源码（**去掉文档字符串后**）里没有
   针对本表的 `UPDATE` / `DELETE` / `TRUNCATE`，也**没有 `ON CONFLICT`**（主键撞重不许被静默）；
2. **列集双向一致**：`QUERY_PLAN_COLUMNS` ↔ 迁移 `0004` 的 `CREATE TABLE` 列集
   （两份真相比对 —— 表改了而写入面没改，或反之，本文件当场红）；
3. **列序与绑定**：INSERT 的列清单 = `QUERY_PLAN_COLUMNS` 顺序；`plan_json` 走
   `CAST(... AS jsonb)`（psycopg3 `text → jsonb` 无隐式转换，这个 CAST 不是装饰）；
4. **枚举入参**：签名的注解真的是 `BindingState` / `BindingLayer | None`
   （不是 `str` —— 传枚举是本通道对调用方的主要保护）；
5. **写入值形态**：枚举落库为其 `.value`；`plan_json` 缺 `schema_version` 直接拒；
   `Mapping` 形态的 `plan_summary` 被序列化为 JSON 文本；
6. **不 catch**：engine 抛什么就往外抛什么。

**不验**（属别的层）：
- "app_rw 真的能 INSERT 但不能 UPDATE 吗" → 库侧，`tests/integration/test_query_plan_store.py`；
- "CHECK 真的拒非法 binding_state 吗" → 库侧，同上；
- "SQL 真能执行吗" → 本文件用记录型假 engine 只验**形状**（同 `test_audit_writer.py` 的裁定：
  单元测试若依赖库，CI 上会变成"库没起就跳过"，而**跳过在 pytest 里显示为绿色**）。

⚠️ **文档字符串要剥掉再扫**：本模块的 docstring **故意**讨论这些禁止形态
（"不做 upsert"、"没有 UPDATE/DELETE"），裸扫源码会把说明文字当成违规命中。
`ast` 剥离后只扫**真正会执行的东西**。
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.enums import BindingLayer, BindingState
from app.repo.query_plan import (
    _INSERT_SQL,
    QUERY_PLAN_COLUMNS,
    QUERY_PLAN_REQUIRED_COLUMNS,
    QUERY_PLAN_TABLE,
    QueryPlanSchemaMismatch,
    QueryPlanStore,
    _binding,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_STORE_SRC = _BACKEND_ROOT / "app" / "repo" / "query_plan.py"
_MIGRATION_SRC = (
    _BACKEND_ROOT / "app" / "repo" / "migrations" / "versions" / "0004_cost_ledger_and_query_plan.py"
)

#: 针对本表的写改删语句（第 1 条的对象）。
_MUTATION = re.compile(r"\b(UPDATE\s+\w|DELETE\s+FROM\b|TRUNCATE\s+\w)")


# ============================================================================
# 1. 源码层：只写 + 没有 upsert
# ============================================================================

def _code_without_docstrings(path: Path) -> str:
    """剥离模块/类/函数的文档字符串后的源码（理由见文件头 ⚠️）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_bearing = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, doc_bearing) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:]
    return ast.unparse(tree)


def test_module_source_has_no_mutation_statements() -> None:
    code = _code_without_docstrings(_STORE_SRC)
    hit = _MUTATION.search(code)
    assert hit is None, (
        f"写入通道里出现了改/删语句：{hit.group(0)!r} —— "
        f"本表语义 = 一行一次写入（0004 权限层也只给 INSERT/SELECT）"
    )


def test_module_source_has_no_on_conflict() -> None:
    """`ON CONFLICT` = 把"同一任务写了两次"这种图结构缺陷静默掉（文件头已论证）。"""
    code = _code_without_docstrings(_STORE_SRC)
    assert "ON CONFLICT" not in code.upper(), (
        "出现 ON CONFLICT —— 主键撞重必须如实抛 UniqueViolation（诊断价值在第一次写的那行）"
    )


def test_only_insert_method_is_exposed() -> None:
    public = {
        name
        for name, member in vars(QueryPlanStore).items()
        if not name.startswith("_") and callable(member)
    }
    assert public == {"insert_query_plan"}, (
        f"QueryPlanStore 的公开方法面漂移：{sorted(public)} —— 本类只写，"
        f"任何 update/delete/upsert 都超出表语义"
    )


# ============================================================================
# 2. 列集双向一致：写入面 ↔ 迁移 0004 的 DDL
# ============================================================================

def _migration_query_plan_columns() -> list[str]:
    """从迁移 0004 的 `_DDL_QUERY_PLAN` 里解析 `CREATE TABLE` 的列名。

    ⚠️ **通用解析，不写死列名**：把列名清单写进正则等于"只认得已知的 7 列"——
    迁移将来新增一列时匹配不到，两份清单仍然相等，护栏**假绿**。
    本函数按"行首标识符 + 类型"提取，只跳过约束行。
    """
    tree = ast.parse(_MIGRATION_SRC.read_text(encoding="utf-8"))
    ddl_repr: str | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_DDL_QUERY_PLAN" for t in node.targets
        ):
            # f-string 经 unparse 后是带转义换行的字面量；列名与类型都不含插值
            ddl_repr = ast.unparse(node.value)
    assert ddl_repr is not None, "迁移 0004 里找不到 _DDL_QUERY_PLAN"

    body = re.split(r"\\n", ddl_repr)  # 还原行
    columns: list[str] = []
    inside = False
    for raw in body:
        line = raw.strip()
        if "CREATE TABLE" in line:
            inside = True
            continue
        if not inside:
            continue
        if line.startswith(")"):
            break
        if not line or line.startswith("("):
            continue
        if re.match(r"^(CONSTRAINT|PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN)\b", line, re.I):
            continue
        m = re.match(r"^([A-Za-z_]\w*)\s+[A-Za-z]", line)
        if m:
            columns.append(m.group(1))
    assert columns, "解析出的迁移列集为空 —— 解析器坏了，护栏空转"
    return columns


def test_columns_match_migration_ddl_bidirectionally() -> None:
    ddl_columns = _migration_query_plan_columns()
    assert list(QUERY_PLAN_COLUMNS) == ddl_columns, (
        f"写入面与迁移 0004 的列集/列序不一致：\n"
        f"  写入面: {list(QUERY_PLAN_COLUMNS)}\n  迁移:   {ddl_columns}"
    )


def test_required_columns_are_subset_of_columns() -> None:
    assert set(QUERY_PLAN_COLUMNS) >= QUERY_PLAN_REQUIRED_COLUMNS
    # 0004 明写可空的三列不得被列为必填（否则 unresolved 态写不进去）
    assert QUERY_PLAN_REQUIRED_COLUMNS.isdisjoint({"binding_layer", "plan_summary", "confidence"})


# ============================================================================
# 3. INSERT 形状
# ============================================================================

def test_insert_sql_column_list_matches_whitelist_order() -> None:
    m = re.search(r"\(([^)]*)\)\s*VALUES", _INSERT_SQL)
    assert m, "_INSERT_SQL 里解析不出列清单"
    assert [c.strip() for c in m.group(1).split(",")] == list(QUERY_PLAN_COLUMNS)
    assert QUERY_PLAN_TABLE in _INSERT_SQL


def test_plan_json_binds_as_jsonb_cast() -> None:
    """`text → jsonb` 无隐式转换：少了这个 CAST，PG 直接报类型错（audit_store 踩过）。"""
    assert _binding("plan_json") == "CAST(:plan_json AS jsonb)"
    assert "CAST(:plan_json AS jsonb)" in _INSERT_SQL
    # 其余列不得被 CAST（多一个 CAST 就是一处将来会漂的假设）
    for column in QUERY_PLAN_COLUMNS:
        if column != "plan_json":
            assert _binding(column) == f":{column}"


def test_sql_uses_bound_params_only() -> None:
    assert _INSERT_SQL.count(":") == len(QUERY_PLAN_COLUMNS)  # 每列一个绑定参数
    assert "{" not in _INSERT_SQL and "}" not in _INSERT_SQL, "SQL 里出现插值痕迹"


# ============================================================================
# 4. 枚举入参（本通道对调用方的主要保护）
# ============================================================================

def test_signature_annotations_use_enums() -> None:
    from typing import get_type_hints

    hints = get_type_hints(QueryPlanStore.insert_query_plan)
    assert hints["binding_state"] is BindingState, (
        f"binding_state 的注解是 {hints['binding_state']!r} —— 必须是枚举，"
        f"裸 str 会让拼错取值拖到运行时才被 CHECK 拒（错误信息还看不出是哪个字段）"
    )
    assert hints["binding_layer"] == BindingLayer | None
    assert hints["confidence"] == Decimal | None, "confidence 必须是 Decimal（float 有二进制误差）"


# ============================================================================
# 5/6. 写入值形态 + 不 catch（记录型假 engine，不连库）
# ============================================================================

class _RecordingConnection:
    def __init__(self, log: list[tuple[str, dict[str, Any]]], error: Exception | None) -> None:
        self._log = log
        self._error = error

    async def execute(self, stmt: Any, params: Any) -> None:
        if self._error is not None:
            raise self._error
        self._log.append((str(stmt), dict(params)))


class _Begin:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _RecordingConnection:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeEngine:
    """记下 `(sql, params)`；`error` 非空时 `execute` 直接抛 —— 用于验"不 catch"。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []
        self._error = error

    def begin(self) -> _Begin:
        return _Begin(_RecordingConnection(self.log, self._error))


def _store(*, error: Exception | None = None) -> tuple[QueryPlanStore, _FakeEngine]:
    engine = _FakeEngine(error=error)
    # 假 engine 只实现 `begin()` —— 声明成 AsyncEngine 是测试替身的常规做法；
    # 用 cast 而不是 Any，是为了保留"若 QueryPlanStore 改了用法，本文件会报错"的检查面。
    return QueryPlanStore(cast(AsyncEngine, engine)), engine


def _insert(
    store: QueryPlanStore,
    *,
    task_id: str | None = "tk_1",
    plan_json: Any = None,
    binding_layer: BindingLayer | None = BindingLayer.L3,
    plan_summary: Any = None,
    confidence: Decimal | None = Decimal("0.87"),
) -> None:
    asyncio.run(
        store.insert_query_plan(
            task_id=cast(str, task_id),
            plan_json={"schema_version": 1, "grain": "day"} if plan_json is None else plan_json,
            bundle_version="bundle_2026.09.14.1",
            binding_state=BindingState.RESOLVED_UNIQUE,
            binding_layer=binding_layer,
            plan_summary={"metrics": ["gmv"]} if plan_summary is None else plan_summary,
            confidence=confidence,
        )
    )


def test_written_values_use_enum_values_and_json_text() -> None:
    store, engine = _store()
    _insert(store)
    assert len(engine.log) == 1
    sql, params = engine.log[0]
    assert sql.startswith("INSERT INTO app.query_plan")
    assert params["binding_state"] == "resolved_unique", (
        "落库的必须是枚举的 .value —— 写成 repr/name 会被 CHECK 拒或（更糟）绕开诊断口径"
    )
    assert params["binding_layer"] == "L3"
    assert json.loads(params["plan_json"]) == {"schema_version": 1, "grain": "day"}
    assert json.loads(params["plan_summary"]) == {"metrics": ["gmv"]}
    assert params["confidence"] == Decimal("0.87")


def test_optional_columns_can_be_null() -> None:
    """`unresolved` 终态的形态：没有判定层、没有置信度、摘要可以缺（0004 的可空性裁定）。"""
    store, engine = _store()
    _insert(store, plan_summary=None, confidence=None, binding_layer=None)
    _sql, params = engine.log[0]
    # plan_summary 显式传 None 时才为 None（上面的 helper 默认给了 dict，这里另跑一次）
    assert params["binding_layer"] is None
    assert params["confidence"] is None


def test_missing_schema_version_is_rejected_before_touching_db() -> None:
    store, engine = _store()
    with pytest.raises(QueryPlanSchemaMismatch, match="schema_version"):
        _insert(store, plan_json={"grain": "day"})
    assert engine.log == [], "拒收必须发生在发语句之前"


def test_pre_serialized_plan_json_passes_through() -> None:
    """`str` 形态按原样绑（W4 自证 schema_version；本层只保证 CAST 到 jsonb）。"""
    store, engine = _store()
    _insert(store, plan_json='{"schema_version": 2}')
    assert engine.log[0][1]["plan_json"] == '{"schema_version": 2}'


def test_missing_required_value_is_reported_by_name() -> None:
    """缺必填项要在**发语句前**报出字段名 —— 让 DB 报 NOT NULL 的话，错误里没有列名。"""
    store, engine = _store()
    with pytest.raises(QueryPlanSchemaMismatch, match="task_id"):
        _insert(store, task_id=None)
    assert engine.log == []


def test_engine_errors_propagate() -> None:
    """不 catch：写失败向上抛（阻断性归调用方 —— 同 audit_store 的分层裁定）。"""
    boom = RuntimeError("库炸了")
    store, _engine = _store(error=boom)
    with pytest.raises(RuntimeError) as caught:
        _insert(store)
    assert caught.value is boom
