"""审计两段式的**代码层**自证（07 §12.4 第 ③ 层 / N-09 / ADR-14）。

归属窗口：W1B。

⚠️ **本文件是两个文档字符串点名承诺过的文件，此前并不存在。**
`app/obs/audit.py` 与 `app/repo/audit_store.py` 都写着"由 `tests/unit/test_audit_writer.py`
静态断言"——**盘上没有这个文件**。这正是本项目反复吃亏的那类"影子承诺"
（`tests/conftest.py` 的文档字符串里已经记录过一次同型事故）：
文档说"有护栏"，于是没人去查护栏在不在；真出事时才发现那句话是空的。
本文件把承诺兑现，覆盖**两个文件**（段 1 的语义层 + 段 2 的 SQL 层）。

## 本文件验什么 / 不验什么

**验**（离线，不连库）：
1. 第 ③ 层"代码层不可变"：两个文件里都没有针对审计表的 `UPDATE` / `DELETE` / `TRUNCATE`；
   `AuditStore` 也没有任何改名换姓的写改删方法；
2. 身份列**结构上**不可能被 payload 覆盖（不是靠调用方自觉）；
3. 两段式的**失败语义确实不同**：段 1 fail-closed（抛且保留异常链）、段 2 不阻断（永不抛）；
4. 白名单与绑定表达式**同源**（`jsonb` / `text[]` 列不会被按 `str` 绑）。

**不验**（属别的层，别混）：
- "`app_rw` 真的没有 UPDATE 权限吗" → **库侧**，`tests/integration/test_audit_append_only.py`；
- "SQL 真的能执行成功吗" → 需真库，本文件用记录型假 engine 只验**形状**；
- "审计字段集与迁移列集是否逐列一致" → 需读 `information_schema`，属集成。

⚠️ 本文件**只用假 engine**，不建真连接：单元测试若依赖库，在 CI 上会变成
"库没起就跳过" —— 而"跳过"在 pytest 里**显示为绿色**，护栏就成了摆设。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.contracts import AuditSinkPort, IdentityContext
from app.core.enums import Role
from app.core.errors import AuditWriteFailed
from app.obs.audit import AuditWriter
from app.repo.audit_store import (
    AUDIT_IDENTITY_COLUMNS,
    AUDIT_PAYLOAD_BINDINGS,
    AUDIT_PAYLOAD_COLUMNS,
    AUDIT_REQUIRED_COLUMNS,
    AUDIT_TABLE,
    SUPPLEMENT_TABLE,
    AuditSchemaMismatch,
    AuditStore,
    _binding,
    _normalize_value,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_OBS_AUDIT = _BACKEND_ROOT / "app" / "obs" / "audit.py"
_REPO_AUDIT_STORE = _BACKEND_ROOT / "app" / "repo" / "audit_store.py"

#: 对审计表的写改删语句（第 ③ 层的对象）。
_MUTATION = r"\b(UPDATE\s+\w|DELETE\s+FROM\b|TRUNCATE\s+\w)"


def _ctx(**over: Any) -> IdentityContext:
    base: dict[str, Any] = {
        "trace_id": "tr_1",
        "task_id": "task_1",
        "session_id": "sess_1",
        "tenant_id": "t_001",
        "user_id": "u_001",
        "role": Role.OPERATOR,
    }
    base.update(over)
    return IdentityContext(**base)


# ===========================================================================
# 假实现：记录型假 engine（**只验 SQL 形状，不假装能执行**）
# ===========================================================================

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
    """记下 `(sql, params)`。`error` 非空时 `execute` 直接抛 —— 用于验"不 catch"。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []
        self._error = error

    def begin(self) -> _Begin:
        return _Begin(_RecordingConnection(self.log, self._error))


def _store(*, error: Exception | None = None) -> tuple[AuditStore, _FakeEngine]:
    engine = _FakeEngine(error=error)
    # 假 engine 只实现了 `begin()` —— 类型上声明成 AsyncEngine 是测试替身的常规做法，
    # 这里用 cast 而不是 Any，是为了保留"若 AuditStore 改了用法，本文件会报错"的检查面。
    return AuditStore(cast(AsyncEngine, engine)), engine


class _StoreDouble:
    """`AuditStore` 的行为替身（按需抛，并记录调用）。

    ⚠️ 它**不是** `AuditStore` 的子类：子类会继承真实实现，于是"改了真实实现、
    替身跟着一起改"这类漂移不会被发现。这里只实现被 `AuditWriter` 用到的两个方法。
    """

    def __init__(self, *, pre_error: Exception | None = None, supp_error: Exception | None = None) -> None:
        self.pre_error = pre_error
        self.supp_error = supp_error
        self.pre_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.supp_calls: list[tuple[str, dict[str, Any]]] = []

    async def insert_audit_log(self, identity: Any, payload: Any) -> None:
        if self.pre_error is not None:
            raise self.pre_error
        self.pre_calls.append((dict(identity), dict(payload)))

    async def insert_supplement(self, task_id: str, payload: Any) -> None:
        if self.supp_error is not None:
            raise self.supp_error
        self.supp_calls.append((task_id, dict(payload)))


def _writer(**kw: Any) -> tuple[AuditWriter, _StoreDouble]:
    store = _StoreDouble(**kw)
    return AuditWriter(cast(AuditStore, store)), store


# ===========================================================================
# 1. 第 ③ 层：代码层不可变（静态）
# ===========================================================================

def test_neither_audit_file_has_a_mutation_statement() -> None:
    """★ 07 §12.4 第 ③ 层：**段 1 与段 2 的两个文件**都不得出现写改删语句。

    ⚠️ **复用** W0 契约测试里的 AST 扫描器，而不是再抄一份，理由是两个：
    ① 那个实现踩过一次假阳性坑（全文正则会命中**文档字符串里在讨论** UPDATE 这件事），
       抄一份就会把那个坑一起抄过来，而且以后修一处不代表修两处；
    ② 单一实现 → "什么算写改删语句"只有一个定义，不会出现两个测试各判各的。
    ⚠️ 代价：本文件因此依赖 W0 的测试模块（`tests/contract/`）。若 W0 改了那个私有函数名，
    本文件会以 **ImportError** 红掉 —— 那是**显式的**，比"两份实现悄悄分叉"好。
    （已登记为交接项：建议 W0 把扫描器提到 `tests/_sql_scan.py`，两边都从那里取。）
    ⚠️ 为什么连 `repo/audit_store.py` 一起扫：第 ③ 层真正能被绕过的地方在**数据访问层** ——
    `obs/audit.py` 只是策略，SQL 文本全在本文件之外的那个模块里。
    只扫 `obs/` 会得到一个"看起来绿、实则没覆盖 SQL 面"的结论。
    """
    from tests.contract.test_obs_audit_contract import _sql_strings_with

    for path in (_OBS_AUDIT, _REPO_AUDIT_STORE):
        hits = _sql_strings_with(path.read_text(encoding="utf-8"), _MUTATION)
        assert not hits, (
            f"{path.name} 在代码里（非文档）出现写改删语句 {hits} —— "
            f"append-only 被破坏（N-09/ADR-14）"
        )


def test_audit_store_exposes_no_mutating_method() -> None:
    """★ 静态扫描的**补集**：既没有写改删 **SQL**，也没有写改删 **方法**。

    只扫 SQL 文本会漏掉"方法名换了个说法"的情况（`upsert_audit_log` / `set_outcome`）。
    这里按**动词词根**判，而不是枚举已知名字 —— 枚举永远追不上创造力。

    ⚠️ 判的是 `AuditStore` 的**公开面**（`__all__` 之外的方法也算）：审计表的写权限
    在代码层只允许 `insert_*`，多一个公开方法就多一个入口。
    """
    forbidden_roots = ("update", "delete", "truncate", "remove", "set_", "upsert", "drop", "purge")
    offenders = sorted(
        name
        for name in dir(AuditStore)
        if not name.startswith("_")
        and any(root in name.lower() for root in forbidden_roots)
    )
    assert not offenders, (
        f"AuditStore 出现疑似写改删方法：{offenders} —— "
        f"审计表只允许 INSERT（N-09）；确属误判请改方法名而不是放宽本断言"
    )


def test_audit_store_public_surface_is_insert_only() -> None:
    """正向对照：**只断言"没有坏的"是不够的**，还要断言"好的那些确实在"。

    否则一个把方法全删光的空类也能让上面那条绿。
    """
    public = {n for n in dir(AuditStore) if not n.startswith("_")}
    assert public == {"insert_audit_log", "insert_supplement"}, (
        f"AuditStore 的公开面变了：{sorted(public)} —— "
        f"新增方法必须同步本断言（并说明为什么它不是第二个写入入口）"
    )


# ===========================================================================
# 2. 白名单与绑定：单一来源 + 类型正确
# ===========================================================================

def test_binding_table_and_whitelist_are_the_same_source() -> None:
    """★ 白名单与"怎么绑"必须**同源**。

    分成两份表时，新增列漏改一处就会得到一条**用错转换**的 SQL（`jsonb` 列按 `text` 绑），
    而它只在运行时、只在有值时报错 —— 单元测试里看不到。
    """
    assert set(AUDIT_PAYLOAD_BINDINGS) == set(AUDIT_PAYLOAD_COLUMNS)
    assert set(AUDIT_PAYLOAD_COLUMNS) & set(AUDIT_IDENTITY_COLUMNS) == set(), (
        "同一列不能既算身份列又算 payload 列 —— 那会让「身份不可覆盖」出现缺口"
    )


def test_jsonb_and_array_columns_are_cast_not_plain_bound() -> None:
    """`jsonb` / `text[]` 列**必须**显式 CAST。

    psycopg3 把 Python `str` 按 `text` 绑定，而 `text → jsonb` 在 PG 里
    **没有隐式转换**（直接报 `column is of type jsonb but expression is of type text`）。
    这条断言把"哪几列需要 CAST"钉在测试里：删掉某个 CAST 就会红，
    而不是等到有值的那次查询才炸。
    """
    assert _binding("latency_ms") == "CAST(:latency_ms AS jsonb)"
    for col in ("tables_accessed", "columns_accessed", "pii_columns_hit"):
        assert _binding(col) == f"CAST(:{col} AS text[])", col
    # 普通文本列**不得**被 CAST（多一次转换就多一处与列定义分叉的机会）
    assert _binding("outcome") == ":outcome"
    assert _binding("raw_question") == ":raw_question"


def test_array_columns_are_never_json_encoded() -> None:
    """`text[]` 列**不得**被 `json.dumps`。

    对 `list[str]` 做 `json.dumps` 会让它变成**一个元素的数组**（整段 JSON 当元素），
    而这种错误在库里"看起来有数据"，只在消费端按元素遍历时才暴露 —— 最晚被发现的一类。
    """
    assert _normalize_value("tables_accessed", ["orders", "shops"]) == ["orders", "shops"]
    assert _normalize_value("pii_columns_hit", []) == []
    # jsonb 列则相反：非 str 必须序列化（否则 psycopg 不知道该 SERIALIZE 成什么）
    assert _normalize_value("latency_ms", {"total": 12}) == '{"total": 12}'
    # 已经是 str 的不再包一层引号
    assert _normalize_value("latency_ms", '{"total": 12}') == '{"total": 12}'


# ===========================================================================
# 3. 身份列**结构上**不可被 payload 覆盖
# ===========================================================================

@pytest.mark.parametrize("column", ["task_id", "tenant_id", "user_id", "role"])
def test_payload_cannot_override_identity(column: str) -> None:
    """★ 审计的全部价值 = "不可被请求方影响"。

    若身份与业务事实合并成一个 dict（`{**identity, **payload}`），payload 里的 `role`
    会**静默覆盖**身份里的 `role` —— "谁干的"变成请求方可控。
    这里逐列验证：**四列中的任何一列**都不接受 payload 提供。
    """
    store, engine = _store()
    with pytest.raises(AuditSchemaMismatch, match="身份列"):
        _run(
            store.insert_audit_log(
                {c: "x" for c in AUDIT_IDENTITY_COLUMNS},
                {"raw_question": "q", "outcome": "success", column: "attacker"},
            )
        )
    assert engine.log == [], "身份覆盖必须在**触库之前**就被拒绝（不能靠数据库约束兜底）"


def test_missing_identity_column_is_rejected() -> None:
    """身份列**缺一项**也要拒绝，而不是"让它为 NULL 先记下来"。

    NULL 身份行在事后排查里是**不可用**的：无法回答"这条是谁的"。
    今天放宽，明天就会有人用它绕过身份传递。
    """
    store, engine = _store()
    with pytest.raises(AuditSchemaMismatch, match="缺少身份列"):
        _run(
            store.insert_audit_log(
                {"task_id": "t", "tenant_id": "t_001", "user_id": "u_001"},  # 缺 role
                {"raw_question": "q", "outcome": "success"},
            )
        )
    assert engine.log == []


def test_unknown_payload_column_is_rejected_not_dropped() -> None:
    """字段名漂移（`sql_text` 改名 `final_sql`）必须**当次就红**。

    静默丢弃的表现是"审计少记了一个字段"，几个月后才被发现 —— 而那时已经无法补记。
    """
    store, engine = _store()
    with pytest.raises(AuditSchemaMismatch, match="未登记的列名"):
        _run(
            store.insert_audit_log(
                {c: "x" for c in AUDIT_IDENTITY_COLUMNS},
                {"raw_question": "q", "outcome": "success", "final_sql": "SELECT 1"},
            )
        )
    assert engine.log == []


@pytest.mark.parametrize("column", sorted(AUDIT_REQUIRED_COLUMNS))
def test_missing_required_column_names_the_field(column: str) -> None:
    """缺必填列时**指出是哪个字段**。

    放给数据库报错的话，会被 `obs/audit.py` 包成 `AuditWriteFailed`（"写失败了"）——
    排查方向从"字段名写错"偏到"数据库有问题"。N-11 不禁止我们指出自己的字段名。
    """
    store, _ = _store()
    payload = {"raw_question": "q", "outcome": "success"}
    payload.pop(column)
    with pytest.raises(AuditSchemaMismatch, match=re.escape(column)):
        _run(store.insert_audit_log({c: "x" for c in AUDIT_IDENTITY_COLUMNS}, payload))


# ===========================================================================
# 4. SQL 形状：只有 INSERT
# ===========================================================================

def test_audit_insert_sql_shape_is_insert_only() -> None:
    """正身：整条 SQL 是**单条 `INSERT INTO app.audit_log`**，无 `ON CONFLICT`。

    ⚠️ `ON CONFLICT` 也在禁止之列：`DO UPDATE` 会让"同 `task_id` 覆盖写"成为可能，
    等于给 append-only 开了一个后门（`uq_audit_log_task_id` 正是为了拦住重复，
    冲突时应当**报错**而不是覆盖）。
    """
    store, engine = _store()
    _run(
        store.insert_audit_log(
            _identity_dict(),
            {
                "raw_question": "上个月各店铺 GMV",
                "outcome": "success",
                "tables_accessed": ["orders"],
                "latency_ms": {"total": 1200},
            },
        )
    )
    assert len(engine.log) == 1
    sql, params = engine.log[0]
    assert sql.startswith(f"INSERT INTO {AUDIT_TABLE} (")
    assert "ON CONFLICT" not in sql.upper()
    assert re.search(_MUTATION, sql, re.IGNORECASE) is None
    # 参数里**不得**出现身份列的重复来源：身份只能来自 identity 参数
    assert params["role"] == Role.OPERATOR.value
    assert params["latency_ms"] == '{"total": 1200}'
    assert params["tables_accessed"] == ["orders"]


def test_supplement_needs_only_task_id() -> None:
    """段 2 **没有必填列** —— 这不是宽松：它是补充信息，强加必填项会制造
    "因为少了一个可选指标所以审计不完整"的假故障（其结果还是不阻断）。
    """
    store, engine = _store()
    _run(store.insert_supplement("task_1", {}))
    sql, params = engine.log[0]
    assert sql.startswith(f"INSERT INTO {SUPPLEMENT_TABLE} (task_id)")
    assert params == {"task_id": "task_1"}


# ===========================================================================
# 5. 数据访问层**不吞异常**（"非阻断"是策略，不是事实）
# ===========================================================================

def test_store_does_not_swallow_engine_error() -> None:
    """★ 若 `AuditStore` 自己 catch，`obs/audit.py` 的 fail-closed **永远收不到信号** ——
    于是"审计一直静默失败、`audit_log` 永远是空的"将无人发现。

    这一条把"谁来 catch"钉死在**策略层**（`obs/audit.py`）这一个位置。
    """
    store, _ = _store(error=RuntimeError("connection reset"))
    with pytest.raises(RuntimeError, match="connection reset"):
        _run(store.insert_audit_log(_identity_dict(), {"raw_question": "q", "outcome": "success"}))

    store2, _ = _store(error=RuntimeError("connection reset"))
    with pytest.raises(RuntimeError, match="connection reset"):
        _run(store2.insert_supplement("task_1", {}))


# ===========================================================================
# 6. 策略层：两段式的失败语义**确实不同**
# ===========================================================================

def test_audit_writer_implements_the_port() -> None:
    """`AuditSinkPort` 是 `runtime_checkable` 的 Protocol —— 这里做一次运行时确认。

    它能过**不代表**语义对（Protocol 只查方法名），故本文件其余部分才是重点；
    但它能拦住"改了方法名/签名导致调用方 `TypeError`"这类低级断裂。
    """
    writer, _ = _writer()
    assert isinstance(writer, AuditSinkPort)


def test_write_pre_is_fail_closed_and_preserves_cause() -> None:
    """★ 段 1：抛 `AuditWriteFailed`，且**保留原异常链**。

    不保留链的后果："审计写不进去"会变成一类查不出原因的高频故障 ——
    调用方只看到"审计失败"，看不到底下的 `OperationalError: password authentication failed`。
    """
    writer, store = _writer(pre_error=RuntimeError("boom"))
    with pytest.raises(AuditWriteFailed) as ei:
        _run(writer.write_pre(_ctx(), {"raw_question": "q", "outcome": "success"}))
    assert isinstance(ei.value.__cause__, RuntimeError), "异常链必须保留（便于定位根因）"
    assert ei.value.default_code == "INTERNAL", (
        "段 1 失败映射 error(INTERNAL)（07 §12.4）—— 换码会让前端把它当成业务错误"
    )
    assert store.pre_calls == []


def test_write_pre_does_not_wrap_schema_mismatch() -> None:
    """★ 两类错误**刻意分开**：`AuditSchemaMismatch` 是编程错误（代码与表不一致），
    原样抛出。包成审计失败会把排查方向从"字段名写错了"偏到"数据库有问题"。
    """
    writer, _ = _writer(pre_error=AuditSchemaMismatch("bad column"))
    with pytest.raises(AuditSchemaMismatch, match="bad column"):
        _run(writer.write_pre(_ctx(), {"outcome": "success"}))


def test_write_supp_never_raises_on_generic_error() -> None:
    """★ 段 2：结果**已经下发了**，此时抛异常只会把一次成功的查询变成一次 500，
    而用户手里是一份完整的结果（07 §14.2 G2：只告警）。
    """
    writer, _ = _writer(supp_error=RuntimeError("boom"))
    _run(writer.write_supp(_ctx(), {"input_tokens": 1}))  # 不抛即通过


def test_write_supp_also_swallows_schema_mismatch_unlike_pre() -> None:
    """★ 与段 1 **不一样**，这里连 `AuditSchemaMismatch` 也不抛。

    段 1 抛它是为了不让脏字段流进审计表；段 2 若抛，就会把
    "补充信息字段名写错"升级成"用户的查询失败"——收益为零、代价明确。
    本用例把这个"刻意的两侧不同"钉住：谁把两段写成一样，这里就红。
    """
    writer, _ = _writer(supp_error=AuditSchemaMismatch("bad column"))
    _run(writer.write_supp(_ctx(), {"nope": 1}))  # 不抛即通过


def test_write_pre_passes_identity_and_payload_as_two_arguments() -> None:
    """身份与业务事实**分两个参数**传递（结构上防覆盖，而不是靠约定）。

    `role` 取 `.value`：`Role` 虽是 `StrEnum`，但传枚举对象依赖"驱动恰好按 str 适配"，
    而 `audit_log.role` 是 `text` 列 —— 让"库里存的是字符串"成为代码里看得见的事实。
    """
    writer, store = _writer()
    _run(writer.write_pre(_ctx(), {"raw_question": "q", "outcome": "success"}))
    identity, payload = store.pre_calls[0]
    assert identity == {
        "task_id": "task_1",
        "tenant_id": "t_001",
        "user_id": "u_001",
        "role": "operator",
    }
    assert isinstance(identity["role"], str)
    assert "role" not in payload, "payload 不得夹带身份列（否则 store 会拒绝，且暴露设计意图错位）"
    assert payload == {"raw_question": "q", "outcome": "success"}


def test_write_supp_uses_the_identity_task_id() -> None:
    """段 2 只传 `task_id`（它是外键，指向段 1 的行）—— **同样来自身份**，不是 payload。"""
    writer, store = _writer()
    _run(writer.write_supp(_ctx(task_id="task_9"), {"cost_cny": 0.01}))
    assert store.supp_calls == [("task_9", {"cost_cny": 0.01})]


def test_audit_writer_exposes_no_way_to_disable_fail_closed() -> None:
    """★ NFR-3.4：审计失败**不得**降级成"先放过去"。

    一个 `strict=False` 之类的开关，在第一次线上抖动时就会被打开，然后再也没关回去 ——
    而它打开的正是"结果下发了、审计没记"这个窗口。
    **本用例是那个开关的闸门**：加它必须显式改红本文件（而不是顺手加个默认参数）。
    """
    import inspect

    params = set(inspect.signature(AuditWriter.__init__).parameters)
    assert params == {"self", "store"}, f"AuditWriter 构造参数变了：{sorted(params)}"
    public = {n for n in dir(AuditWriter) if not n.startswith("_")}
    assert public == {"write_pre", "write_supp"}, f"AuditWriter 公开面变了：{sorted(public)}"


def test_fail_closed_failure_is_logged_with_its_outcome(capsys: pytest.CaptureFixture[str]) -> None:
    """"不隐瞒"：段 1 失败必须留下**可检索**的日志字段（`outcome=fail_closed`）。

    ⚠️ 本层**不定义指标**（`obs/metrics.py` 明文"阶段 0 刻意不定义任何指标名"，
    "审计写失败率"的标签口径属 §15.3 清单，归 W7）—— 故可见性由日志承载，
    日志字段名是契约（`obs/schema.py`）。
    """
    writer, _ = _writer(pre_error=RuntimeError("boom"))
    with pytest.raises(AuditWriteFailed):
        _run(writer.write_pre(_ctx(), {"outcome": "success"}))
    out = capsys.readouterr().out
    assert "audit_pre_failed" in out
    assert "fail_closed" in out

    writer2, _ = _writer(supp_error=RuntimeError("boom"))
    _run(writer2.write_supp(_ctx(), {"cost_cny": 0.0}))
    out2 = capsys.readouterr().out
    assert "audit_supp_failed" in out2
    assert "non_blocking" in out2


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _identity_dict() -> dict[str, str]:
    return {"task_id": "task_1", "tenant_id": "t_001", "user_id": "u_001", "role": "operator"}


def _run(coro: Any) -> Any:
    """跑一个协程。

    ⚠️ **刻意不用 `asyncio.run`**：`pytest-asyncio` 的 auto 模式下，同步测试里调
    `asyncio.run` 会新建事件循环，而 redis/asyncpg 之类的对象可能已绑定到别的循环。
    这里改用 `asyncio.Runner`（3.11+）显式托管一个短命循环，语义与用普通同步测试一致，
    且不会与 pytest 的 fixture 循环打架。
    """
    import asyncio

    with asyncio.Runner() as runner:
        return runner.run(coro)
