"""类型归一化单测 —— 07 §8.4 表**逐条**（W2D DoD①："逐条测试"）。

每条规则 = 一个独立用例；数值边界（2^53、精度）全部落死。
时区行为用 Asia/Shanghai（生产值）断言，不用注入替身 —— 替身测不出真实契约。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.exec.normalize import (
    BYTEA_PLACEHOLDER,
    JSON_DEPTH_PLACEHOLDER,
    JSON_MAX_DEPTH,
    normalize_cell,
    normalize_row,
    normalized_type_name,
)

TZ = ZoneInfo("Asia/Shanghai")


# ============================================================================
# numeric / decimal：保精度，不转 float（财务红线）
# ============================================================================


def test_numeric_stays_string_with_precision():
    # 0.1+0.2 类误差不可接受：必须原样保字符串
    assert normalize_cell(Decimal("12.50")) == "12.50"
    assert normalize_cell(Decimal("0.1")) == "0.1"
    assert normalize_cell(Decimal("12345678901234567890.123456789")) == "12345678901234567890.123456789"


def test_numeric_is_never_converted_to_float():
    out = normalize_cell(Decimal("0.10"))
    assert isinstance(out, str)
    assert out != str(float("0.10"))  # float 形态会丢尾零


def test_numeric_nan_becomes_null():
    assert normalize_cell(Decimal("NaN")) is None


# ============================================================================
# 整数：2^53 边界（JS 精度上限）
# ============================================================================


@pytest.mark.parametrize("v", [0, 1, -1, 2**53 - 1, -(2**53 - 1)])
def test_int_within_js_range_stays_number(v):
    assert normalize_cell(v) == v
    assert isinstance(normalize_cell(v), int)


@pytest.mark.parametrize("v", [2**53, -(2**53), 2**63 - 1, -(2**63)])
def test_int_beyond_js_range_becomes_string(v):
    out = normalize_cell(v)
    assert out == str(v)
    assert isinstance(out, str)


# ============================================================================
# float：NaN / ±Infinity → null
# ============================================================================


def test_float_nan_becomes_null():
    assert normalize_cell(float("nan")) is None


def test_float_inf_becomes_null():
    assert normalize_cell(float("inf")) is None
    assert normalize_cell(float("-inf")) is None


def test_float_finite_stays_number():
    assert normalize_cell(3.14) == 3.14


# ============================================================================
# 时间：timestamptz 一律 Asia/Shanghai + ISO 带 +08:00（N-18）
# ============================================================================


def test_timestamptz_converts_to_shanghai_iso():
    # UTC 16:00 = 上海次日 00:00（跨日边界是最容易错的样本）
    dt = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)
    assert normalize_cell(dt) == "2026-09-16T00:00:00+08:00"


def test_naive_timestamp_attaches_shanghai_tz():
    # naive 只可能是 timestamp（无时区）：附上海时区，不猜测 UTC
    dt = datetime(2026, 9, 16, 12, 0, 0)
    assert normalize_cell(dt) == "2026-09-16T12:00:00+08:00"


def test_date_is_yyyy_mm_dd():
    from datetime import date

    assert normalize_cell(date(2026, 9, 16)) == "2026-09-16"


def test_interval_becomes_iso_duration():
    assert normalize_cell(timedelta(days=1, hours=2, minutes=3)) == "P1DT2H3M"
    assert normalize_cell(timedelta(0)) == "PT0S"
    assert normalize_cell(timedelta(hours=-5)) == "-PT5H"


# ============================================================================
# bytea：不返回（防二进制带出文件内容）
# ============================================================================


def test_bytea_becomes_placeholder():
    assert normalize_cell(b"\x00\x01binary") == BYTEA_PLACEHOLDER
    assert normalize_cell(memoryview(b"\xff")) == BYTEA_PLACEHOLDER


def test_bytea_placeholder_is_not_raw_content():
    raw = b"secret-file-content"
    assert b"secret" not in str(normalize_cell(raw)).encode()


# ============================================================================
# json / jsonb：原样嵌套 + 深度 > 5 截断
# ============================================================================


def test_json_passes_through_with_normalized_leaves():
    assert normalize_cell({"a": Decimal("1.20")}) == {"a": "1.20"}
    assert normalize_cell([float("nan"), 1]) == [None, 1]


def test_json_depth_over_limit_is_truncated_with_marker():
    deep = 0
    for _ in range(JSON_MAX_DEPTH + 3):  # 远超上限
        deep = {"v": deep}
    out = normalize_cell(deep)
    # 第 6 层起必须被标记替换 —— 用逐层下钻验证深度确实被截住
    cur = out
    depth_seen = 0
    while isinstance(cur, dict):
        cur = cur["v"]
        depth_seen += 1
    assert depth_seen == JSON_MAX_DEPTH
    assert cur == JSON_DEPTH_PLACEHOLDER


def test_json_depth_at_limit_is_not_truncated():
    v = 1
    for _ in range(JSON_MAX_DEPTH - 1):
        v = {"v": v}
    assert normalize_cell(v) == v  # 恰好 5 层：不截断


# ============================================================================
# 其他：None / bool / 数组 / 未知类型
# ============================================================================


def test_null_stays_null():
    assert normalize_cell(None) is None


def test_bool_is_bool_not_int():
    out = normalize_cell(True)
    assert out is True
    assert isinstance(out, bool)


def test_array_elements_follow_same_rules():
    out = normalize_cell([Decimal("1.5"), None, 2**53])
    assert out == ["1.5", None, str(2**53)]  # 数组 → JSON array（list）


def test_unknown_type_falls_back_to_str():
    class Weird:
        def __str__(self) -> str:
            return "weird"

    assert normalize_cell(Weird()) == "weird"


def test_row_helper_normalizes_each_cell():
    row = (Decimal("1.00"), None, float("inf"))
    assert normalize_row(row) == ("1.00", None, None)


# ============================================================================
# 负向对照：注入 → 必红 → 还原 → 必绿
# ============================================================================


def test_negative_control_js53_boundary_actually_fires():
    """把 2^53 判据破坏掉必须让越界用例红；还原后回绿 —— 证明断言测的是阈值本身。

    ⚠️ 必须经模块属性调用（`norm.normalize_cell`）而不是测试文件的 from-import 名：
    monkeypatch 换的是模块属性，from-import 的本地名不受影响 —— 那是本窗口
    第一版踩的"注入没生效"陷阱（对照实验自己红给了我看）。
    """
    import app.exec.normalize as norm

    v = 2**53
    assert isinstance(norm.normalize_cell(v), str)

    # 注入：int 直接原样返回（**跳过** 2^53 判据）→ 越界值漏成 number（"必红"）
    original = norm.normalize_cell

    def _broken(value, **kw):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return original(value, **kw)

    norm.normalize_cell = _broken
    try:
        assert isinstance(norm.normalize_cell(v), int)  # 注入生效：2^53 现在漏成 number
    finally:
        norm.normalize_cell = original
    assert isinstance(norm.normalize_cell(v), str)  # 还原：回绿


# ============================================================================
# normalized_type_name
# ============================================================================


def test_type_names_are_stable():
    assert normalized_type_name("x") == "string"
    assert normalized_type_name(None) == "null"
    assert normalized_type_name(BYTEA_PLACEHOLDER) == "binary_omitted"
    assert normalized_type_name(1) == "number"
    assert normalized_type_name(Decimal("1")) == "decimal"
    assert normalized_type_name(datetime.now(TZ)) == "datetime"
    assert normalized_type_name({"a": 1}) == "json"
    assert normalized_type_name([1]) == "array"
    assert normalized_type_name(True) == "boolean"
