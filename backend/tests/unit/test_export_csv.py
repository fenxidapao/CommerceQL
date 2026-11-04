"""B2：导出请求 DTO 与 CSV 渲染的离线断言（零 DB、零 Redis、零网络）。

## ⚠️ 这个文件证明什么、不证明什么

| 断言 | 这里 | 需起栈 |
|---|---|---|
| `format` 只接受 `csv`（其余 400） | ✅ | — |
| 表头/单元格渲染、公式注入防护、`None` → 空串 | ✅ | — |
| 「先审计再下发」「归属校验只在一处」「缓存过期 ⇒ 404」 | — | ⛔ `routers/export.py` 的编排；需 TestClient + 真/替身 Redis（登记为已知边界） |

⚠️ 公式注入防护**会改变字面值**（`=1+1` → `'=1+1`）。下面有用例是**钉子**：
下一个人若把它当 bug「修掉」，导出就重新变成一条能往运维 Excel 里塞公式的通道。

⚠️ 两条用例写法的由来（都是踩出来的，不是洁癖）：
① 以回车符开头的单元格会被 `csv` 用引号包裹，而 `str.splitlines()` 会把引号内的回车也当换行
   ⇒ 「渲染后逐行比对」对这类值不成立。故 prefix 覆盖改在 `_cell_text` 层钉，
   渲染层只钉不会触发引号包裹的安全 payload；
② 单列空串行会被渲染成一个空行，而 `splitlines()` 会把它丢掉 ⇒「普通值不改动」组里不含空串。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.dto.export import EXPORT_FORMATS, ExportRequest
from app.api.routers.export import (
    CSV_INJECTION_PREFIXES,
    _cell_text,
    _filename,
    render_csv,
)

# ===========================================================================
# 1. 请求 DTO
# ===========================================================================


def test_defaults_to_csv() -> None:
    assert ExportRequest(task_id="tk_1").format == "csv"


def test_the_only_supported_format_is_accepted() -> None:
    assert ExportRequest(task_id="tk_1", format="csv").format in EXPORT_FORMATS


@pytest.mark.parametrize("bad", ["png", "xlsx", "CSV", "pdf"])
def test_rejects_unsupported_formats(bad: str) -> None:
    with pytest.raises(ValidationError, match="format"):
        ExportRequest(task_id="tk_1", format=bad)


def test_rejects_extra_fields() -> None:
    """`extra=forbid`：请求体里塞 `tenant_id` 必须被拒 —— 租户只能来自令牌。"""
    with pytest.raises(ValidationError):
        ExportRequest(task_id="tk_1", tenant_id="t_other")


def test_rejects_blank_task_id() -> None:
    with pytest.raises(ValidationError, match="task_id"):
        ExportRequest(task_id="   ")


# ===========================================================================
# 2. CSV 渲染
# ===========================================================================


def test_header_comes_from_column_metadata() -> None:
    text = render_csv(
        [{"name": "gmv", "type_name": "numeric", "unit": "元"}, {"name": "city"}],
        [[1.5, "广州"]],
    )
    assert text.splitlines()[0] == "gmv,city"


def test_rows_are_rendered_in_order() -> None:
    assert render_csv(["a", "b"], [[1, 2], [3, 4]]).splitlines() == ["a,b", "1,2", "3,4"]


def test_none_becomes_empty_cell_not_the_string_none() -> None:
    """`None` 若被 `str()` 成字符串，导出文件里会出现一批假的 "None" 值。"""
    assert render_csv(["a", "b"], [[None, 1]]).splitlines()[1] == ",1"


def test_empty_result_still_emits_the_header_row() -> None:
    assert render_csv(["a", "b"], []).splitlines() == ["a,b"]


def test_line_terminator_is_crlf() -> None:
    assert "\r\n" in render_csv(["a"], [[1]])


@pytest.mark.parametrize("payload", ["=1+1", "+SUM(A1)", "-2", "@cmd"])
def test_formula_injection_is_neutralised_in_the_rendered_file(payload: str) -> None:
    """★ 钉子：命中起始字符即以 `'` 前缀，否则 CSV 能在 Excel 里执行公式。"""
    assert render_csv(["v"], [[payload]]).splitlines()[1] == "'" + payload


@pytest.mark.parametrize("prefix", list(CSV_INJECTION_PREFIXES))
def test_every_declared_prefix_is_guarded_at_cell_level(prefix: str) -> None:
    """六个起始字符逐个钉在单元格层（渲染层只覆盖不会触发引号包裹的那几个）。"""
    assert _cell_text(prefix + "x") == "'" + prefix + "x"


@pytest.mark.parametrize("safe", ["广州", "1.5", "a=b", "100%"])
def test_ordinary_values_are_untouched(safe: str) -> None:
    """反向对照：**不在**起始位置的 `=` 等字符不得被改（过度消毒 = 改数据）。"""
    assert render_csv(["v"], [[safe]]).splitlines()[1] == safe


def test_injection_prefixes_cover_the_owasp_set() -> None:
    assert set(CSV_INJECTION_PREFIXES) == {"=", "+", "-", "@", "\t", "\r"}


# ===========================================================================
# 3. 文件名净化（响应头也是注入面）
# ===========================================================================


def test_filename_is_sanitised() -> None:
    assert _filename("tk_01J8X1") == "tk_01J8X1.csv"


def test_filename_cannot_inject_a_response_header() -> None:
    """换行会切开 `Content-Disposition` —— 白名单净化必须吃掉它。"""
    name = _filename('tk_1"; filename="evil\r\nX-Injected: 1')
    assert "\r" not in name
    assert "\n" not in name
    assert '"' not in name


def test_empty_task_id_falls_back_to_result() -> None:
    """空文件名会让浏览器按 URL 猜，而 URL 里带着 `task_id` ⇒ 必须退成固定名。"""
    assert _filename("") == "result.csv"


def test_non_ascii_task_id_yields_an_ascii_filename() -> None:
    name = _filename("中文")
    assert name.isascii()
    assert name.endswith(".csv")
