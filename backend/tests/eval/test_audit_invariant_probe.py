"""W6 · 「审计行差」不变量取证件的判据测试（`backend/reports/w6/probe_audit_invariant.py`）。

全部离线：不连库、不联网、不花 token。这里守的是**判据形状**，不是今天的读数：
* 缺 `admission` 的格子绝不许被算成"差 0"（不可引用清单同族 —— 没测到 ≠ 通过）；
* 差值是**双向**的（少落 = 终态丢失，多落 = 一个请求落多行，U-129 那一侧）；
* 多场景回执只有 receipt 级窗口时不许逐格比（否则整批行数会被压到单场景的 `admitted` 上）；
* 取证件**不许带字面共享库 DSN**（与 `test_the_boundary_probe_takes_no_literal_shared_dsn` 同形）；
* 真产物里每个"违反"格都必须两个数齐全，且 `not_applicable` 不许混进 `invariant_ok_cells`。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from datetime import UTC, datetime

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROBE = REPO / "backend" / "reports" / "w6" / "probe_audit_invariant.py"
PRODUCT = REPO / "backend" / "reports" / "w6" / "probe_audit_invariant.json"


def _load_probe(monkeypatch):
    monkeypatch.setenv("COMMERCEQL_PROBE_DSN", "postgresql://u@invalid.invalid/db")
    sys.path.insert(0, str(REPO / "eval"))
    spec = importlib.util.spec_from_file_location("probe_audit_invariant", PROBE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_missing_admission_is_never_counted_as_a_zero_diff(monkeypatch):
    """没有 `admission` 字段 = 没测；写成"差 0"就是假绿灯。"""
    m = _load_probe(monkeypatch)
    state, diff = m.classify(None, 0)
    assert state == m.NOT_APPLICABLE and diff is None
    state, diff = m.classify(86, None)
    assert state == m.NOT_APPLICABLE and diff is None
    s = m.summarize([
        {"receipt": "a.json", "state": m.NOT_APPLICABLE, "admitted": None, "audit_rows": None, "diff": None},
        {"receipt": "b.json", "state": m.INVARIANT_OK, "admitted": 86, "audit_rows": 86, "diff": 0},
    ], skew_s=0.0)
    assert s["invariant_ok_cells"] == 1
    assert s["state_counts"][m.NOT_APPLICABLE] == 1
    assert s["violated_cells"] == []


def test_diff_is_two_sided_and_neither_side_is_silently_ok(monkeypatch):
    """少落（终态丢失）与多落（双终态）都必须点名，且两侧分得开。"""
    m = _load_probe(monkeypatch)
    assert m.classify(16, 8) == (m.INVARIANT_VIOLATED, 8)      # W7 修复前那一格：8 条没落终态
    assert m.classify(8, 16) == (m.INVARIANT_VIOLATED, -8)     # 反向：一个请求落了多行
    assert m.classify(86, 86) == (m.INVARIANT_OK, 0)
    s = m.summarize([
        {"receipt": "under.json", "state": m.INVARIANT_VIOLATED, "admitted": 16, "audit_rows": 8, "diff": 8},
        {"receipt": "over.json", "state": m.INVARIANT_VIOLATED, "admitted": 8, "audit_rows": 16, "diff": -8},
    ], skew_s=0.0)
    assert (s["undercount_side"], s["overcount_side"]) == (1, 1)


def test_multi_scenario_receipt_level_window_is_not_compared(monkeypatch):
    """共享 receipt 级窗口的多场景回执 ⇒ ambiguous_window（比了恒假），不进"违反"也不进"成立"。"""
    m = _load_probe(monkeypatch)
    receipt = {
        "schema": "w7.loadtest.receipt/1",
        "started_at": "2026-09-28T13:46:44+00:00",
        "finished_at": "2026-09-28T13:47:41+00:00",
        "scenarios": [{"admission": {"admitted": 10}}, {"admission": {"admitted": 20}}],
    }
    for sc in receipt["scenarios"]:
        begin, end, kind = m.window_of(receipt, sc)
        assert (begin, end, kind) == (None, None, "ambiguous")
    # 单场景回执才允许用 receipt 级窗口（今天的 rB 五份就是这个形状）
    one = {"started_at": "2026-09-28T13:46:44+00:00", "finished_at": "2026-09-28T13:47:41+00:00",
           "scenarios": [{"admission": {"admitted": 86}}]}
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
    assert s["invariant_ok_cells"] == s["state_counts"].get("invariant_ok", 0)
    for v in s["violated_cells"]:
        assert isinstance(v["admitted"], int) and isinstance(v["audit_rows"], int)
        assert v["diff"] == v["admitted"] - v["audit_rows"]
    for c in d["cells"]:
        if c["state"] == "not_applicable":
            assert c["admitted"] is None or c["audit_rows"] is None
        if c["state"] == "invariant_ok":
            assert c["admitted"] == c["audit_rows"]
    # 可见性条件必须落盘：这张表一旦被纳入 RLS，本探针不设租户 GUC 就会静默数到 0（交付 §5.24）
    assert d["pg_guard"]["count_visible_without_tenant_guc"] is True
    assert d["pg_guard"]["time_column"] == "timestamp"
    assert s["window_rule"] and "note" in s
    assert d["cells"]  # 空扫描面绝不能写成"没违反"
