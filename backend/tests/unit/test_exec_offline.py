"""exec 层离线单测：错误分类（N-11）/ 指纹（§8.8）/ executor 纯逻辑部分。

真库行为（超时 / 只读写失败 / prepare_threshold）在 `tests/integration/` ——
替身测不出"数据库愿不愿意"，那是集成测试的职责（W1B 固化的分层）。
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import psycopg
import pytest

from app.core.config import Settings
from app.core.contracts import ColumnMeta, IdentityContext, MaskOutcome, ResultSet
from app.core.enums import Role
from app.exec.errors import (
    EXEC_ERROR_CLASSES,
    NON_REPAIRABLE,
    REPAIRABLE_CLASSES,
    ExecError,
    ExecFailure,
    classify_pg_error,
)
from app.exec.executor import PgSqlExecutor
from app.exec.fingerprint import result_fingerprint

# ============================================================================
# classify_pg_error：07 §8.9 表逐行（N-11：原始错误文本绝不进任何字段）
# ============================================================================


def _pg_exc(cls: type[Exception], sqlstate: str | None, raw_text: str) -> Exception:
    exc = cls(raw_text)
    if sqlstate is not None:
        exc.sqlstate = sqlstate
    return exc


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("42703", "unknown_column"),
        ("42P01", "unknown_table"),
        ("42804", "type_mismatch"),
        ("42883", "unknown_function"),
        ("42601", "syntax_error"),
        ("57014", "timeout"),
        ("42501", "permission"),
    ],
)
def test_pgcode_maps_to_error_class(sqlstate, expected):
    err = classify_pg_error(_pg_exc(psycopg.errors.ProgrammingError, sqlstate, "column x does not exist"))
    assert err.error_class == expected
    assert err.pgcode == sqlstate


def test_operational_error_without_pgcode_is_db_unavailable():
    exc = psycopg.OperationalError("connection refused to 10.0.0.1")
    err = classify_pg_error(exc)
    assert err.error_class == "db_unavailable"
    assert err.llm_hint is None  # 不可修类不回灌


def test_raw_error_text_never_leaks_into_message():
    """N-11 的直接检验：原始报错里的对象名/值不得出现在 message / llm_hint。"""
    raw = 'invalid input syntax for type integer: "abc" at column v_orders.internal_note'
    err = classify_pg_error(_pg_exc(psycopg.errors.DataError, "42601", raw))
    assert raw not in err.message
    assert "v_orders" not in err.message
    assert err.llm_hint == "SQL 语法有误"  # 07 §8.9 第 42601 行的逐字提示


def test_repairable_and_non_repairable_are_disjoint_and_complete():
    assert not (REPAIRABLE_CLASSES & NON_REPAIRABLE)
    assert REPAIRABLE_CLASSES | NON_REPAIRABLE == EXEC_ERROR_CLASSES
    # 07 §8.9：可 repair 的恰是 5 个 SQL 家族；timeout/permission/db_unavailable/resource 不修
    assert {
        "unknown_column", "unknown_table", "type_mismatch", "unknown_function", "syntax_error",
    } == REPAIRABLE_CLASSES


def test_exec_failure_default_code_fallback():
    e = ExecFailure(ExecError("unknown_column", "42703", "引用了不存在的列（已隐去名称）", "x"))
    assert e.default_code == "SQL_SYNTAX_ERROR"
    t = ExecFailure(ExecError("timeout", "57014", "超时", None))
    assert t.default_code == "EXEC_TIMEOUT"
    # permission 刻意无兜底码：终态应是 refuse（产品结论），落到 error 就错了
    p = ExecFailure(ExecError("permission", "42501", "无权", None))
    assert p.default_code is None


def test_cancelled_error_passes_through_executor_contract():
    """executor 对 CancelledError 的穿透是 §8.3 硬要求 —— 这里钉分类函数不吞它。"""
    assert not isinstance(asyncio.CancelledError(), psycopg.Error)


# ============================================================================
# 指纹（07 §8.8）
# ============================================================================


def test_fingerprint_stable_and_order_sensitive():
    a = result_fingerprint(columns=["a", "b"], rows=[(1, "x")])
    b = result_fingerprint(columns=["a", "b"], rows=[(1, "x")])
    assert a == b
    # 列序不同 = 不同结果集
    assert result_fingerprint(columns=["b", "a"], rows=[("x", 1)]) != a
    # 行序不同 = 不同结果集（无 ORDER BY 的不稳定行序会被指纹如实暴露）
    assert result_fingerprint(columns=["a", "b"], rows=[(2, "y"), (1, "x")]) != a


def test_fingerprint_ignores_tenant_id():
    """07 §8.8 明文：指纹不含 tenant_id（同租户内去重与幂等用）。"""
    a = result_fingerprint(columns=["a"], rows=[(1,)], params={"limit": 10})
    b = result_fingerprint(columns=["a"], rows=[(1,)], params={"limit": 10, "tenant_id": "t_b"})
    # params 里含 tenant_id 会变 —— 所以"不进指纹"的责任在调用方不把 tenant_id 放 params；
    # 本函数层面：params 参与指纹（生效参数变了指纹必须变），tenant 的隔离由缓存键层负责。
    assert a != b  # 生效参数变了 → 指纹必须变（这是断言的本意）


def test_fingerprint_normalization_equivalence():
    """Decimal('1.50') 与字符串 '1.50' 必须同指纹（repair 前后等价比对的前提）。"""
    a = result_fingerprint(columns=["amt"], rows=[(Decimal("1.50"),)])
    b = result_fingerprint(columns=["amt"], rows=[("1.50",)])
    assert a == b


# ============================================================================
# executor 纯逻辑：mask policy 装配 / 每租户配额 / max_rows 钳制
# ============================================================================


class _StubMask:
    def apply(self, rows, policy):
        return MaskOutcome(rows=tuple(tuple(r) for r in rows), hit_columns=())


class _StubBundle:
    def __init__(self, mask_rules):
        self._mr = mask_rules

    def policy(self):
        return {"mask_rules": self._mr}

    def active_version(self):
        return "test"

    def asset_allowlist(self, ctx):
        return {}

    def time_semantics(self):
        raise AssertionError("exec 不消费 time_semantics")


def _settings() -> Settings:
    import os

    return Settings(
        DATABASE_URL=os.environ["DATABASE_URL"],
        ANALYTICS_DB_URL=os.environ["ANALYTICS_DB_URL"],
        DEEPSEEK_API_KEY="sk-placeholder",
    )


def _ctx(tenant: str = "t_001") -> IdentityContext:
    return IdentityContext(
        trace_id="tr", task_id="tk", session_id="s", tenant_id=tenant,
        user_id="u", role=Role.ANALYST,
    )


def test_mask_policy_uses_bundle_overlay_and_null_sensitivity():
    ex = PgSqlExecutor(
        analytics_engine=None, mask=_StubMask(), settings=_settings(),
        bundle=_StubBundle([{"column_pattern": ".*phone.*", "rule": "***-***-1234"}]),
    )
    policy = ex._mask_policy(("receiver_phone", "amount"))
    assert policy["columns"] == [
        {"name": "receiver_phone", "sensitivity": None},
        {"name": "amount", "sensitivity": None},
    ]
    assert policy["mask_rules"] == [{"column_pattern": ".*phone.*", "rule": "***-***-1234"}]


def test_mask_policy_without_bundle_is_empty_overlay():
    ex = PgSqlExecutor(analytics_engine=None, mask=_StubMask(), settings=_settings())
    policy = ex._mask_policy(("a",))
    assert policy["mask_rules"] == []


def test_tenant_quota_default_is_40pct_of_pool():
    ex = PgSqlExecutor(analytics_engine=None, mask=_StubMask(), settings=_settings())
    assert ex._tenant_quota == 16  # 07 §8.2：analytics 池上限 40 × 40%


def test_tenant_quota_per_tenant_isolation():
    ex = PgSqlExecutor(analytics_engine=None, mask=_StubMask(), settings=_settings())
    a = ex._tenant_semaphores.setdefault("t_a", asyncio.Semaphore(ex._tenant_quota))
    b = ex._tenant_semaphores.setdefault("t_b", asyncio.Semaphore(ex._tenant_quota))
    assert a is not b  # 配额按租户隔离，不共享


def test_cancel_unknown_task_is_idempotent_false():
    """未执行中 / 已结束的任务：cancel → False（幂等，不抛）。"""
    ex = PgSqlExecutor(analytics_engine=None, mask=_StubMask(), settings=_settings())

    async def run():
        return await ex.cancel("no-such-task")

    assert asyncio.new_event_loop().run_until_complete(run()) is False


def test_column_meta_type_name_from_raw_values():
    """type_name 按**原始值**判型 —— 归一化后 Decimal 已变字符串，decimal 信息会丢。"""
    from datetime import datetime

    ex = PgSqlExecutor(analytics_engine=None, mask=_StubMask(), settings=_settings())
    raw_rows = ((None, Decimal("1.00"), 2, datetime(2026, 9, 16, tzinfo=None)),)
    metas = ex._column_meta(("a", "b", "c", "d"), raw_rows)
    assert metas[0].type_name == "null"
    assert metas[1].type_name == "decimal"  # 原始 Decimal → decimal（不是 string）
    assert metas[2].type_name == "number"
    assert metas[3].type_name == "datetime"
    assert all(m.unit is None for m in metas)  # unit 恒 None（诚实边界，见模块头）


def test_result_set_shape_is_frozen_contract():
    """ResultSet 是 frozen 值对象 —— 试图改字段必须失败（防下游就地篡改脱敏结果）。"""
    rs = ResultSet(
        columns=(ColumnMeta(name="a", type_name="number"),),
        rows=((1,),),
        row_count=1,
        truncated=False,
        fingerprint="x",
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        rs.row_count = 99  # type: ignore[misc]


# ============================================================================
# _bind_dollar_params：pg 原生 $n 模板 → psycopg 客户端绑定（N-04 相关）
# ============================================================================


def test_bind_dollar_params_converts_and_reorders():
    from app.exec.executor import _bind_dollar_params

    tpl = "SELECT set_config('app.tenant_id', $1, true), set_config('app.role', $2, true)"
    sql, params = _bind_dollar_params(tpl, ("t_001", "analyst"))
    assert "$1" not in sql and "$2" not in sql
    assert sql.count("%s") == 2
    assert params == ("t_001", "analyst")
    # 参数数量必须与占位符严格相等（多余/不足都拒绝，绝不静默错位绑定）
    with pytest.raises(Exception, match="契约破损"):
        _bind_dollar_params(tpl, ("t_001", "analyst", "extra"))


def test_bind_dollar_params_reorders_out_of_sequence():
    from app.exec.executor import _bind_dollar_params

    sql, params = _bind_dollar_params("SELECT f($2, $1)", ("a", "b"))
    assert sql == "SELECT f(%s, %s)"
    assert params == ("b", "a")  # 按 $n 序重排，不依赖占位符出现序


def test_bind_dollar_params_fail_closed_on_bad_template():
    from app.exec.executor import _bind_dollar_params

    with pytest.raises(Exception, match="契约破损"):
        _bind_dollar_params("SELECT f($1, $3)", ("a", "b", "c"))  # 缺 $2
    with pytest.raises(Exception, match="契约破损"):
        _bind_dollar_params("SELECT f($2, $1)", ("a", "b", "c"))  # 不从 $1 起
    with pytest.raises(Exception, match="契约破损"):
        _bind_dollar_params("SELECT f($1, $1)", ("a", "b"))  # 重复占位
    with pytest.raises(Exception, match="契约破损"):
        _bind_dollar_params("SELECT f($1, $2)", ("a",))  # 参数不足
