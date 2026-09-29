"""W6 · 「审计行差」不变量取证件的判据测试（`backend/reports/w6/probe_audit_invariant.py`）。

全部离线：不连库、不联网、不花 token。这里守的是**判据形状**，不是今天的读数：
* 分母是 **`terminal`**（U-130），不是 `admitted` —— 有断流时后者会**假报"少落"**；
* 词表必须与 W7 的驱动**同源**（照抄 `driver.py` 的 `_TERMINAL_OUTCOMES`，防止第三份真相）；
* `admission.terminal` 与推导值不等 ⇒ 点名两个数，不静默挑一个；`admitted` 只作显式标注的代理；
* 缺分母 / 分母为 0（等式恒真）/ 窗口早于表里现存最老一行 ⇒ `not_applicable` 且**必须说出原因**；
* 差值是**双向**的（少落 = 终态丢失，多落 = 一个请求落多行，U-129 那一侧）；
* 取证件**不许带字面共享库 DSN**（与 `test_the_boundary_probe_takes_no_literal_shared_dsn` 同形）；
* 真产物里每个"违反"格都必须两个数齐全，且不可比格不许混进 `invariant_ok_cells`。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
from datetime import UTC, datetime, timedelta

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROBE = REPO / "backend" / "reports" / "w6" / "probe_audit_invariant.py"
PRODUCT = REPO / "backend" / "reports" / "w6" / "probe_audit_invariant.json"
DRIVER = REPO / "deploy" / "loadtest" / "driver.py"


def _load_probe(monkeypatch):
    monkeypatch.setenv("COMMERCEQL_PROBE_DSN", "postgresql://u@invalid.invalid/db")
    sys.path.insert(0, str(REPO / "eval"))
    spec = importlib.util.spec_from_file_location("probe_audit_invariant", PROBE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _receipt(tmp_path: pathlib.Path, scenario: dict,
             target: str = "http://127.0.0.1:18000/api/v1") -> pathlib.Path:
    path = tmp_path / "r_test.json"
    path.write_text(json.dumps({
        "schema": "w7.loadtest.receipt/1",
        "target": target,
        "started_at": "2026-09-29T02:00:00+00:00",
        "finished_at": "2026-09-29T02:01:00+00:00",
        "scenarios": [scenario],
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_denominator_is_terminal_not_admitted(monkeypatch, tmp_path):
    """W7 第十九轮的订正：有断流时 `admitted` 会把量具形状报成"服务端少落了终态"。

    形状照抄驱动自己的 `--self-check` 活样本（`driver.py:770-774`）：`admitted=8 / terminal=7`，
    差的那 1 条是 `truncated`（HTTP 200 但没读到 `terminal: true`）。审计真有 7 行 ⇒ 严格式成立；
    若按老分母就是"差 +1 ⇒ 少落"的**假红**。
    """
    m = _load_probe(monkeypatch)
    sc = {"admission": {"admitted": 8, "rejected_429": 2, "other_http_4xx": 0,
                        "http_5xx": 0, "unresolved": 0},
          "outcomes": {"ok": 5, "clarify": 1, "refuse": 1, "truncated": 1}}
    assert m.admitted_of(sc) == 8                      # 老分母：只是 2xx
    assert m.derived_terminal(sc) == 7                 # 新分母：只数有终止帧的
    den, basis, mismatch = m.denominator_of(sc)
    assert (den, basis, mismatch) == (7, m.BASIS_DERIVED, None)
    assert m.classify(den, 7) == (m.INVARIANT_OK, 0)   # ← 严格式成立
    assert m.classify(m.admitted_of(sc), 7) == (m.INVARIANT_VIOLATED, 1)  # ← 老分母的假红
    path = _receipt(tmp_path, sc)
    cell = m.collect(path.parent, path.name)[0]
    assert (cell["denominator"], cell["denominator_basis"], cell["admitted"],
            cell["terminal"], cell["stream_break_gap"]) == (7, m.BASIS_DERIVED, 8, 7, 1)


def test_strict_denominator_does_not_require_the_admission_block(monkeypatch, tmp_path):
    """分母的权威来源是 `outcomes`（+`admission.terminal`），不是 `admission` 整块。

    这条把今天实际发生的**适用面变宽**钉住：老回执没有 `admission` ⇒ 上一版一律 `not_applicable`，
    而它们的 `outcomes` 是在的 ⇒ 严格式本来就能比。两个数都没有的格子仍要 `not_applicable` 并报原因。
    """
    m = _load_probe(monkeypatch)
    only_outcomes = _receipt(tmp_path, {"outcomes": {"ok": 12, "timeout": 1}})
    cell = m.collect(only_outcomes.parent, only_outcomes.name)[0]
    assert (cell["denominator"], cell["denominator_basis"], cell["admitted"]) == (12, m.BASIS_DERIVED, None)
    assert cell["state"] == m.NO_DB and cell["inapplicability_reason"] is None
    empty = _receipt(tmp_path, {"scenario": "no-counters"})
    cell2 = m.collect(empty.parent, empty.name)[0]
    assert (cell2["denominator"], cell2["state"], cell2["inapplicability_reason"]) == (
        None, m.NOT_APPLICABLE, "denominator_unavailable")


def test_terminal_vocabulary_is_the_drivers_own(monkeypatch):
    """词表不许长成分叉的两份真相：探针的 `TERMINAL_OUTCOMES` 必须等于驱动的 `_TERMINAL_OUTCOMES`。"""
    m = _load_probe(monkeypatch)
    src = DRIVER.read_text(encoding="utf-8")
    block = re.search(r"_TERMINAL_OUTCOMES[^\n]*=\s*frozenset\((.*?)\)", src, re.S)
    assert block, "W7 的驱动里找不到 _TERMINAL_OUTCOMES ⇒ 这条不变量的分母已换定义，探针必须跟着改"
    theirs = set(re.findall(r'"([a-z0-9_]+)"', block.group(1)))
    assert set(m.TERMINAL_OUTCOMES) == theirs, f"词表漂移：驱动 {sorted(theirs)} vs 探针 {sorted(m.TERMINAL_OUTCOMES)}"
    # 反向也钉：非终态桶一律不许被数进分母（它们没有终止帧）
    for excluded in ("truncated", "http_4xx", "http_5xx", "timeout", "conn_error"):
        assert excluded not in theirs


def test_w7_selfcheck_shape_still_disagrees(monkeypatch):
    """驱动自报的 `admission.terminal` 与我的推导不等 ⇒ 用写件人的值，但两个数都落进产物。"""
    m = _load_probe(monkeypatch)
    sc = {"admission": {"admitted": 8, "terminal": 7}, "outcomes": {"ok": 8}}
    den, basis, mismatch = m.denominator_of(sc)
    assert (den, basis) == (7, m.BASIS_PROVIDED)
    assert mismatch == {"provided": 7, "derived": 8}
    s = m.summarize([{"receipt": "x.json", "state": m.INVARIANT_VIOLATED, "denominator": 7,
                      "denominator_basis": m.BASIS_PROVIDED, "admitted": 8, "terminal": 7,
                      "audit_rows": 9, "diff": -2, "inapplicability_reason": None,
                      "mismatch": {"provided": 7, "derived": 8}}], skew_s=0.0)
    assert s["provided_vs_derived_mismatch"] == [{"receipt": "x.json", "provided": 7, "derived": 8}]


def test_admitted_is_only_an_explicitly_labelled_proxy(monkeypatch):
    """两条严格取法都落空时才可以退回 `admitted`，且必须打上代理标签（代理格的 ok ≠ 严格式成立）。"""
    m = _load_probe(monkeypatch)
    assert m.denominator_of({"admission": {"admitted": 5}}) == (5, m.BASIS_PROXY, None)
    assert m.denominator_of({}) == (None, None, None)
    s = m.summarize([
        {"receipt": "proxy.json", "state": m.INVARIANT_OK, "denominator": 5,
         "denominator_basis": m.BASIS_PROXY, "admitted": 5, "terminal": None,
         "audit_rows": 5, "diff": 0, "inapplicability_reason": None},
    ], skew_s=0.0)
    assert s["proxy_denominator_cells"] == 1 and s["strict_denominator_cells"] == 0


def test_missing_denominator_is_never_a_zero_diff(monkeypatch):
    """没测到 = 没测到，写成"差 0"就是假绿灯（不可引用清单同族）。"""
    m = _load_probe(monkeypatch)
    assert m.classify(None, 0) == (m.NOT_APPLICABLE, None)
    assert m.classify(86, None) == (m.NOT_APPLICABLE, None)
    s = m.summarize([
        {"receipt": "a.json", "state": m.NOT_APPLICABLE, "denominator": None, "denominator_basis": None,
         "admitted": None, "terminal": None, "audit_rows": None, "diff": None,
         "inapplicability_reason": "denominator_unavailable"},
        {"receipt": "b.json", "state": m.INVARIANT_OK, "denominator": 86, "denominator_basis": m.BASIS_DERIVED,
         "admitted": 86, "terminal": 86, "audit_rows": 86, "diff": 0, "inapplicability_reason": None},
    ], skew_s=0.0)
    assert s["invariant_ok_cells"] == 1
    assert s["state_counts"][m.NOT_APPLICABLE] == 1
    assert s["violated_cells"] == []
    assert s["inapplicability_reason_counts"] == {"denominator_unavailable": 1}


def test_zero_denominator_is_vacuously_true_so_it_is_not_an_ok_cell(monkeypatch, tmp_path):
    """`terminal = 0` 的格子等式**恒真** ⇒ 不作数（数进去就是给不检验任何东西的格子发绿灯）。"""
    m = _load_probe(monkeypatch)
    assert m.classify(0, 0) == (m.NOT_APPLICABLE, None)
    assert m.classify(0, 5) == (m.NOT_APPLICABLE, None)   # 空格子也不许反过来算成"多落"
    sc = {"admission": {"admitted": 0}, "outcomes": {"http_4xx": 1}}   # 打错靶子的 404 回执形状
    path = _receipt(tmp_path, sc, target="http://127.0.0.1:8000/api/v1")  # 驱动 `--target` 的默认值
    cell = m.collect(path.parent, path.name)[0]
    assert (cell["denominator"], cell["state"], cell["inapplicability_reason"]) == (
        0, m.NOT_APPLICABLE, "zero_denominator_vacuous")
    # 「0 条终态」必须连着**打在哪儿**一起出：靶子错整批读数才会是 0（`d4b4fef` 留的那份件就是这个形状）
    assert cell["target"] == "http://127.0.0.1:8000/api/v1"
    s = m.summarize([cell], skew_s=0.0)
    assert s["zero_denominator_cells"] == [{"receipt": "r_test.json",
                                           "target": "http://127.0.0.1:8000/api/v1"}]
    assert s["target_counts"] == {"http://127.0.0.1:8000/api/v1": 1}


def test_window_older_than_the_table_is_not_an_undercount(monkeypatch):
    """表在共享实例上会被清理/重载 ⇒ 窗口早于现存最老一行时数到 0 行不是"少落"。"""
    m = _load_probe(monkeypatch)
    t = datetime(2026, 9, 29, 2, 0, 0, tzinfo=UTC)
    pad = timedelta(seconds=1)
    assert m.span_void(t, pad, t + timedelta(days=1)) is True      # 窗口比表老一整天的行
    assert m.span_void(t, pad, t) is False                          # 右端含该秒 ⇒ 同龄窗口照常比
    assert m.span_void(t, pad, None) is False                       # 表没读数 ⇒ 不凭空作废


def test_diff_is_two_sided_and_neither_side_is_silently_ok(monkeypatch):
    """少落（终态丢失）与多落（双终态）都必须点名，且两侧分得开。"""
    m = _load_probe(monkeypatch)
    assert m.classify(16, 8) == (m.INVARIANT_VIOLATED, 8)      # W7 修复前那一格：8 条没落终态
    assert m.classify(8, 16) == (m.INVARIANT_VIOLATED, -8)     # 反向：一个请求落了多行
    assert m.classify(86, 86) == (m.INVARIANT_OK, 0)
    s = m.summarize([
        {"receipt": "under.json", "state": m.INVARIANT_VIOLATED, "denominator": 16,
         "denominator_basis": m.BASIS_DERIVED, "admitted": 16, "terminal": 16,
         "audit_rows": 8, "diff": 8, "inapplicability_reason": None},
        {"receipt": "over.json", "state": m.INVARIANT_VIOLATED, "denominator": 8,
         "denominator_basis": m.BASIS_DERIVED, "admitted": 8, "terminal": 8,
         "audit_rows": 16, "diff": -8, "inapplicability_reason": None},
    ], skew_s=0.0)
    assert (s["undercount_side"], s["overcount_side"]) == (1, 1)
    assert s["strict_denominator_cells"] == 2 and s["proxy_denominator_cells"] == 0


def test_multi_scenario_receipt_level_window_is_not_compared(monkeypatch):
    """共享 receipt 级窗口的多场景回执 ⇒ ambiguous_window（比了恒假），不进"违反"也不进"成立"。"""
    m = _load_probe(monkeypatch)
    receipt = {
        "schema": "w7.loadtest.receipt/1",
        "started_at": "2026-09-28T13:46:44+00:00",
        "finished_at": "2026-09-28T13:47:41+00:00",
        "scenarios": [{"outcomes": {"ok": 10}}, {"outcomes": {"ok": 20}}],
    }
    for sc in receipt["scenarios"]:
        begin, end, kind = m.window_of(receipt, sc)
        assert (begin, end, kind) == (None, None, "ambiguous")
    # 单场景回执才允许用 receipt 级窗口（今天的 rB 十二份就是这个形状）
    one = {"started_at": "2026-09-28T13:46:44+00:00", "finished_at": "2026-09-28T13:47:41+00:00",
           "scenarios": [{"outcomes": {"ok": 86}}]}
    begin, end, kind = m.window_of(one, one["scenarios"][0])
    assert kind == "single" and begin == datetime(2026, 9, 28, 13, 46, 44, tzinfo=UTC)
    assert end == datetime(2026, 9, 28, 13, 47, 41, tzinfo=UTC)
    assert m.collect(REPO / "deploy" / "loadtest", "nonexistent_*.json") == []


def test_overlapping_windows_are_named_not_silently_summed(monkeypatch):
    m = _load_probe(monkeypatch)
    t = datetime(2026, 9, 28, 13, 46, 44, tzinfo=UTC)
    rows = [
        {"receipt": "a.json", "begin": t, "end": t + m.WINDOW_PAD},
        {"receipt": "b.json", "begin": t + m.WINDOW_PAD, "end": t + m.WINDOW_PAD * 2},
        {"receipt": "c.json", "begin": t + m.WINDOW_PAD * 10, "end": t + m.WINDOW_PAD * 11},
    ]
    assert m.overlap_pairs(rows) == [("a.json", "b.json")]


def test_the_invariant_probe_takes_no_literal_shared_dsn():
    """缺 env 必须终止、不出产物 ⇒ 源码里不许出现字面共享库连接串。"""
    src = PROBE.read_text(encoding="utf-8")
    for needle in ("@localhost:5432", "@pg:5432", "postgres:postgres", "app_rw_pwd", "app_ro_pwd"):
        assert needle not in src, f"取证件不该带字面共享 DSN（命中 {needle!r}）"
    assert "COMMERCEQL_PROBE_DSN" in src and "return 2" in src


@pytest.mark.skipif(not PRODUCT.exists(), reason="产物未生成（本轮没跑过该探针）")
def test_product_keeps_inapplicable_cells_out_of_the_ok_count():
    """吃真产物：每个"违反"格两个数必须齐全，且不可比格不许混进 ok 计数。"""
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    s = d["summary"]
    assert "terminal" in d["strict_denominator"], "产物头部的严格式必须是 terminal 分母"
    assert set(d["denominator_definition"]["terminal_outcomes"]) == set(m_terms())
    assert s["invariant_ok_cells"] == s["state_counts"].get("invariant_ok", 0)
    for v in s["violated_cells"]:
        assert isinstance(v["denominator"], int) and v["denominator"] > 0
        assert isinstance(v["audit_rows"], int)
        assert v["diff"] == v["denominator"] - v["audit_rows"]
    for c in d["cells"]:
        if c["state"] == "not_applicable":
            # 不作数必须**点名为什么**：静默的 not_applicable 与"没测"只隔一句话
            assert c["inapplicability_reason"], c["receipt"]
        if c["state"] == "invariant_ok":
            assert c["denominator"] == c["audit_rows"] and c["denominator"] > 0
            assert c["denominator_basis"] in ("admission.terminal", "derived:outcomes", "admitted_proxy:2xx")
    # 可见性条件、表的历史长度与**每格的对照**都必须落盘（交付 §5.24 / §5.29）：
    # 没有 rows_that_window_day 的"少落"读数会被读成缺陷，而它可能只是表没留那么久
    assert d["pg_guard"]["count_visible_without_tenant_guc"] is True
    assert d["pg_guard"]["time_column"] == "timestamp"
    for key in ("table_span", "table_day_counts", "table_outcome_counts"):
        assert key in d["pg_guard"], key
    assert all("target" in c for c in d["cells"]) and d["summary"]["target_counts"]
    assert "violated_by_window_day" in s and "attribution_note" in s
    for v in s["violated_cells"]:
        assert "rows_that_window_day" in v, v["receipt"]
    assert s["window_rule"] and "terminal" in s["note"]


def m_terms() -> set[str]:
    """从驱动源码取分母词表（产物回归用同一把尺，不在测试里再抄一遍常量）。"""
    block = re.search(r"_TERMINAL_OUTCOMES[^\n]*=\s*frozenset\((.*?)\)", DRIVER.read_text(encoding="utf-8"), re.S)
    assert block
    return set(re.findall(r'"([a-z0-9_]+)"', block.group(1)))
