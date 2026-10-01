"""W6 · 「审计行差」不变量取证件的判据测试（`backend/reports/w6/probe_audit_invariant.py`）。

全部离线：不连库、不联网、不花 token。这里守的是**判据形状**，不是今天的读数：
* 分母是 **`terminal`**（U-130），不是 `admitted` —— 有断流时后者会**假报"少落"**；
* 词表必须与 W7 的驱动**同源**（照抄 `driver.py` 的 `_TERMINAL_OUTCOMES`，防止第三份真相）；
* `admission.terminal` 与推导值不等 ⇒ 点名两个数，不静默挑一个；`admitted` 只作显式标注的代理；
* 缺分母 / 分母为 0（等式恒真）/ 窗口早于表里现存最老一行 ⇒ `not_applicable` 且**必须说出原因**；
* 差值是**双向**的（少落 = 终态丢失，多落 = 一个请求落多行，U-129 那一侧）；
* 取证件**不许带字面共享库 DSN**（与 `test_the_boundary_probe_takes_no_literal_shared_dsn` 同形）；
* 🔴 **两数分写**（第二十轮，W7）：`admitted − terminal` 与 `terminal − 审计行` 各带归属、各自落键，
  合并值 `admitted − 审计行` **只许以布尔旗标的形式被点名"没输出"**，任何带数的同名键都算违规；
* 只有 `admitted` 可用（代理）⇒ **不参与严格式**，不比、不判、进 `proxy_only_cells`；
* `codes_task_ids` 只认完整形状，且**覆盖面本身是读数**（三态：absent / empty / present）；
* 🔴 **thread 尺那一维（架构 `U-130 v1.7.12` 的 `turn≥2` 限定）**：turn 必须**先在全历史上赋号、再按窗口筛**
  （反过来会把窗口里的第 2 轮读成 turn1 ⇒ `crash_turn2plus` 静默归零 = **假绿**）；字面式
  `terminal − 审计行(turn≥2)` 只许以 **`gap_literal_DO_NOT_USE`** 出现；尺的语义**按语句标签**向 W7 的 SQL 锚定
  （他改尺 ⇒ 我方红），且**不许复制他的 SQL**；
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


def test_the_two_gaps_are_written_separately_and_never_merged(monkeypatch, tmp_path):
    """W7 第二十轮："两数请分写别并"。`admitted − terminal` 与 `terminal − 审计行` 各归各家。

    形状故意选成**两半相等**（2 与 2）：合并值会是 4，而 4 既不是断流也不是缺行的真实条数 ——
    报出 4 就把"有 2 条断流"这件事抹掉了。所以这里既断两个具名键，也断**合并值不在块里**。
    """
    m = _load_probe(monkeypatch)
    sc = {"admission": {"admitted": 10, "terminal": 8, "rejected_429": 2},
          "outcomes": {"ok": 4, "clarify": 2, "refuse": 1, "error_frame": 1, "truncated": 2}}
    block = m.two_numbers_of(m.admitted_of(sc), m.terminal_of(sc), 6)
    assert block["gap_admitted_minus_terminal"] == 2          # 断流侧（U-129 家族）
    assert block["gap_terminal_minus_audit_rows"] == 2        # 缺行侧（U-130）
    assert block["admitted"] == 10 and block["terminal"] == 8 and block["audit_rows"] == 6
    assert 4 not in [v for v in block.values() if isinstance(v, int)], "合并值不该出现在两数块里"
    assert set(block["attribution"]) == {"gap_admitted_minus_terminal", "gap_terminal_minus_audit_rows"}
    cell = m.collect((p := _receipt(tmp_path, sc)).parent, p.name)[0]
    #: 还没数库 ⇒ 严格式那一半**没有数**（不许拿代理或时间窗凑出一个数来）
    assert cell["two_numbers"]["gap_admitted_minus_terminal"] == 2
    assert cell["two_numbers"]["gap_terminal_minus_audit_rows"] is None
    assert cell["strict_equation_evaluated"] is True          # NO_DB：等着被数，不是等着被猜


def test_proxy_only_denominator_is_never_compared_against_audit_rows(monkeypatch, tmp_path):
    """只有 `admitted` 可用时**不比**：拿它去比审计行数就是那个被禁的合并值。

    第十九轮的"代理要显式标注"在这一轮升级成"代理不参与严格式"——
    盘上 37 份回执都带 `outcomes`（本轮实测），所以这条今天不影响任何读数，
    它挡的是"以后某份回执只有 HTTP 计数时，器件静默把 2xx 当终态数"。
    """
    m = _load_probe(monkeypatch)
    p = _receipt(tmp_path, {"admission": {"admitted": 5}})
    cell = m.collect(p.parent, p.name)[0]
    assert cell["denominator_basis"] == m.BASIS_PROXY
    assert (cell["state"], cell["inapplicability_reason"]) == (m.NOT_APPLICABLE, "denominator_proxy_only")
    assert cell["diff"] is None and cell["terminal"] is None
    assert cell["two_numbers"]["gap_terminal_minus_audit_rows"] is None
    s = m.summarize([cell], 0.0)
    assert s["proxy_only_cells"] == [{"receipt": "r_test.json", "admitted": 5}]
    assert s["state_counts"].get(m.INVARIANT_OK, 0) == 0, "代理格绝不能混进 ok 计数"


def test_codes_task_ids_is_all_or_nothing(monkeypatch):
    """`codes_task_ids` 只认完整形状：半解析出来的 id 集会让人误以为"逐 id 点名过了"。"""
    m = _load_probe(monkeypatch)
    good = {"INTERNAL": ["t1", "t2"], "GATE_AST_REJECTED": ["t3"]}
    assert m.codes_task_ids_of({"codes_task_ids": good}) == good
    for junk in (None, {}, [], {"INTERNAL": []}, {"INTERNAL": "t1"}, {"INTERNAL": [1, 2]}, "x"):
        assert m.codes_task_ids_of({"codes_task_ids": junk}) is None, junk
    assert m.codes_task_ids_of({}) is None
    #: 部分坏 ⇒ 坏的那个键不算数，好的那个仍可用（宁可少点名，也不拿残缺 id 集宣布"点名过了"）
    got = m.codes_task_ids_of({"codes_task_ids": {"INTERNAL": ["t1"], "X": [None]}})
    assert got == {"INTERNAL": ["t1"]} and "X" not in got


def test_summary_reports_task_id_coverage_so_absent_cannot_be_claimed(monkeypatch, tmp_path):
    """覆盖面是**读数的一部分**：没带该字段的批次，产物要自己说"这批不能写成 task_id 级复算"。

    ⚠️ 两份件放**不同子目录**：`_receipt()` 固定写 `r_test.json`，同目录第二次会覆盖第一次 ⇒
    `collect()` 读到的是后一份，测试就会"绿得没有内容"（本项目踩过的那类假绿形状）。
    """
    m = _load_probe(monkeypatch)
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    without = _receipt(dir_a, {"outcomes": {"ok": 3}})
    ch = m.summarize(m.collect(without.parent, without.name), 0.0)["task_id_channel"]
    assert ch["cells_with_codes_task_ids"] == 0 and ch["cells_with_id_evidence"] == 0
    assert "不许" in ch["status"] and "task_id" in ch["status"]
    #: 带了字段的格要**算得出来**（覆盖面是数出来的，不是常量）
    with_ids = _receipt(dir_b, {"outcomes": {"ok": 3}, "codes_task_ids": {"INTERNAL": ["t1", "t2"]}})
    ch2 = m.summarize(m.collect(with_ids.parent, with_ids.name), 0.0)["task_id_channel"]
    assert ch2["cells_with_codes_task_ids"] == 1
    assert ch2["cells_with_id_evidence"] == 0, "没跑库就不许说有 id 级证据"


def test_product_carries_both_gaps_and_no_merged_number():
    """吃真产物：结构上确认"合并值不输出"这条不是嘴上说的。"""
    if not PRODUCT.exists():
        pytest.skip("产物未生成（本轮没跑过该探针）")
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    s = d["summary"]

    def walk(node):
        """ yields (key, value) for every dict entry in the payload. """
        if isinstance(node, dict):
            for k, v in node.items():
                yield k, v
                yield from walk(v)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    #: 名字里同时出现 `admitted` 与审计行的键**只许是旗标（布尔）**，不许带数 ——
    #: 带了数就说明器件把两半并成了一个值（W7 第二十轮禁的事）。
    named = [(k, v) for k, v in walk(d) if "admitted" in k.lower() and "audit" in k.lower()]
    assert named, "至少要有那条 `merged_…_emitted = False` 的旗标"
    for k, v in named:
        assert isinstance(v, bool) and v is False, f"被禁的合并值出现在键 {k!r} = {v!r}"
    assert s["two_number_block"]["merged_admitted_minus_audit_rows_emitted"] is False
    for c in d["cells"]:
        tn = c["two_numbers"]
        assert {"gap_admitted_minus_terminal", "gap_terminal_minus_audit_rows", "attribution"} <= set(tn)
        if c["state"] == "invariant_ok":
            assert tn["gap_terminal_minus_audit_rows"] == 0
            assert tn["terminal"] == tn["audit_rows"]
    #: 覆盖面自己也要在产物里（有 id 级证据的格数 == 带 codes_task_ids 的格数）
    assert s["task_id_channel"]["cells_with_id_evidence"] <= s["task_id_channel"]["cells_with_codes_task_ids"]


def m_terms() -> set[str]:
    """从驱动源码取分母词表（产物回归用同一把尺，不在测试里再抄一遍常量）。"""
    block = re.search(r"_TERMINAL_OUTCOMES[^\n]*=\s*frozenset\((.*?)\)", DRIVER.read_text(encoding="utf-8"), re.S)
    assert block
    return set(re.findall(r'"([a-z0-9_]+)"', block.group(1)))


def test_client_side_stage_counts_are_reported_but_never_judge(monkeypatch, tmp_path):
    """W7 第二十一轮把「要不要并进 U-130 判据面」交给我裁 ⇒ 裁定：**并进产物、不并进判据**。

    三条都要能被机器回答，所以这里同时钉：
    ① 解析形状（只数 `stage=none`，词表按 outcome 分组，缺 provenance ⇒ None 而不是 0）；
    ② `classify()` 的**入参个数**就决定了客户端面进不来（两个参数：分母与审计行数）——
       这比"我在注释里说了不判"硬：以后有人想并，必须先改签名，改签名会撞这条测试；
    ③ 同一格带不带 provenance ⇒ **除诊断列以外逐字段相同**（读数不许被对照面反向塑造）。
    """
    import inspect

    mod = _load_probe(monkeypatch)
    prov = {"error_frame": {"stage=none|reason=none": 3, "stage=sql_ready|reason=none": 2},
            "http_4xx": {"stage=none|reason=none": 9}}
    base = {"admission": {"admitted": 10, "terminal": 8},
            "outcomes": {"ok": 3, "refuse": 5, "error_frame": 3},
            "started_at": "2026-09-29T02:00:00+00:00", "finished_at": "2026-09-29T02:01:00+00:00"}

    #: `_receipt()` 写的是**固定文件名** ⇒ 两份件必须放两个目录（上一轮踩过同目录互相覆盖）。
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    with_prov = _receipt(dir_a, dict(base, terminal_provenance=prov))
    without = _receipt(dir_b, dict(base))
    row_a = mod.collect(with_prov.parent, with_prov.name)[0]
    row_b = mod.collect(without.parent, without.name)[0]

    assert row_a["client_side_evidence"] == {"by_outcome": {"error_frame": 3, "http_4xx": 9}, "total": 12}
    assert row_b["client_side_evidence"] is None
    assert list(inspect.signature(mod.classify).parameters) == ["denominator", "audit_rows"], \
        "判据若有第三个入参，'客户端面不参与判据'这句话就作废了"
    row_a.pop("client_side_evidence")
    row_b.pop("client_side_evidence")
    assert row_a == row_b, "带对照面读数不该改变任何判定字段"


@pytest.mark.skipif(not PRODUCT.exists(), reason="产物未生成（本轮没跑过该探针）")
def test_product_publishes_the_crosscheck_without_a_verdict_slot():
    """吃真产物：对照块必须**有数**但**没有结论位**（`same_scale` 那种字段一个都不许出现）。

    存在的理由：这条对照一旦有一个"同不同阶"的布尔格，下一轮就会有人只读那个格、
    不读两边并排的数 —— 而不同阶这件事（本轮实测：`stage=none` 与 gap 不是同一个数量级）
    只能靠把两个数一起摆出来才说服人。
    """
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    blk = d["summary"]["client_side_crosscheck"]
    assert blk["role"].startswith("只作对照列") and "not_computable_offline" in blk
    assert not any("same_scale" in k for k in blk), blk
    assert blk["n_cells"] == len(d["cells"])
    assert all("client_side_evidence" in c for c in d["cells"])
    expected = [c for c in d["cells"]
                if c["state"] == "invariant_violated" and c.get("client_side_evidence")]
    assert blk["cells_with_provenance"] == sum(1 for c in d["cells"] if c.get("client_side_evidence"))
    assert len(blk["violated_cells_compared"]) == len(expected)
    for row in blk["violated_cells_compared"]:
        assert isinstance(row["gap_terminal_minus_audit_rows"], int)
        assert isinstance(row["stage_none_total"], int)
        assert set(row["stage_none_by_outcome"]) <= {"ok", "clarify", "refuse", "error_frame",
                                                    "async_degraded", "http_4xx", "http_5xx"}


def test_codes_task_ids_coverage_is_reported_in_three_states(monkeypatch, tmp_path):
    """W7 第二十二轮 ④ 把我方"0 / 37"这句话打回重做：**两态覆盖面会冤枉字段**。

    `absent` = 回执根本没有这个键（老件）；`empty` = 键在但值是空字典（那批错误码**没有 ack 帧可取 id**，
    盘上活例 = `r22_lock_c8n8.json`：`codes = {SESSION_CONFLICT: 7}` 而 `codes_task_ids = {}`）；
    `present` = 有 id ⇒ 器件自动走逐行 join。三态混成一个 0，下一轮就会有人宣布"这字段没落地"。
    """
    mod = _load_probe(monkeypatch)
    assert mod.codes_task_ids_presence({}) == "absent"
    assert mod.codes_task_ids_presence({"codes_task_ids": {}}) == "empty"
    assert mod.codes_task_ids_presence({"codes_task_ids": {"INTERNAL": []}}) == "empty"
    assert mod.codes_task_ids_presence({"codes_task_ids": {"INTERNAL": ["tk_x"]}}) == "present"

    base = {"admission": {"admitted": 4, "terminal": 4}, "outcomes": {"error_frame": 4},
            "started_at": "2026-09-29T12:00:00+00:00", "finished_at": "2026-09-29T12:01:00+00:00"}
    dirs = {}
    for state, extra in (("absent", {}),
                         ("empty", {"codes": {"SESSION_CONFLICT": 7}, "codes_task_ids": {}}),
                         ("present", {"codes": {"INTERNAL": 1}, "codes_task_ids": {"INTERNAL": ["tk_x"]}})):
        dirs[state] = tmp_path / state
        dirs[state].mkdir()
        _receipt(dirs[state], dict(base, **extra))
    rows = []
    for state in ("absent", "empty", "present"):
        rows += mod.collect(dirs[state], "r_test.json")
    assert [r["codes_task_ids_presence"] for r in rows] == ["absent", "empty", "present"]
    summary = mod.summarize(rows, None)
    ch = summary["task_id_channel"]
    assert ch["presence_counts"] == {"absent": 1, "empty": 1, "present": 1}
    assert sum(ch["presence_counts"].values()) == ch["n_cells"] == len(rows)
    assert ch["cells_with_codes_task_ids"] == 1 and ch["present_cells"] == ["r_test.json"]
    assert "不是字段坏了" in ch["status"]


def test_the_id_join_counts_rows_in_python_not_via_a_lateral_expand() -> None:
    """⚠️ 本轮真实踩过的形状：`count(*) … join lateral jsonb_object_keys(latency_ms)` 把**一行按键数乘开**。

    症状长得很可信：W7 交来的四个 id 全部 `rows = 6`，而 6 恰好是它们各自的键数 —— 若照这个读数报出去，
    就等于宣布"一个请求落了六行审计"，而那正是 U-129 **双终态**那一侧的缺陷形状（方向完全相反）。
    改成"把 (task_id, outcome, latency_ms) 逐行取回来、在 Python 里数" ⇒ 同一个查询四个 id 都是 1 行。
    这条测试是**形状锁**：器件里再出现那个 lateral 展开就红，免得下一次又乘回去。
    """
    src = PROBE.read_text(encoding="utf-8")
    #: 那个词只许出现在**注释里**（解释为什么不用它），不许再进任何一条 SQL。
    for line in src.splitlines():
        if "jsonb_object_keys" in line:
            assert line.lstrip().startswith("#"), f"lateral 展开回到 SQL 里了：{line.strip()[:90]}"
    assert "select task_id, outcome, latency_ms from app." in src


@pytest.mark.skipif(not PRODUCT.exists(), reason="产物未生成（本轮没跑过该探针）")
def test_product_keeps_id_level_claims_inside_the_present_cells_only():
    """吃真产物：**只有带 id 的那一格**能拿逐 id 点名当证据，且它内部必须自洽。

    钉四条，都是"下一轮会有人引用错"的位置：
    · 三态覆盖面之和 = 格子总数（缺一个态就等于把老件算成空件）；
    · `cells_with_codes_task_ids` 必须等于 present 那一格的数（不许把 empty 算进来）；
    · 有 `task_id_evidence` 的格 ⇒ `n_with_row` 只能由 `by_id` 里的 `seg1_rows` 加出来（不许两个数各说各话）；
    · `by_code[code].missing_task_ids` 与 `with_row` 之和 = 该码给的 id 数（点名要闭合）。
    """
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    ch = d["summary"]["task_id_channel"]
    cells = d["cells"]
    assert ch["n_cells"] == len(cells)
    assert sum(ch["presence_counts"].values()) == len(cells)
    assert ch["cells_with_codes_task_ids"] == ch["presence_counts"]["present"] == len(ch["present_cells"])
    for cell in cells:
        evidence = cell.get("task_id_evidence")
        if not evidence:
            assert not cell.get("codes_task_ids"), "有 id 却没跑 join ⇒ 通道漏了"
            continue
        assert evidence["n_with_row"] == sum(1 for e in evidence["by_id"].values() if e["seg1_rows"] > 0)
        for entry in evidence["by_id"].values():
            assert isinstance(entry["seg1_rows"], int) and entry["seg1_rows"] >= 1
            assert entry["outcomes"]
            keys = entry.get("latency_keys")
            assert keys is None or 1 <= keys["min"] <= keys["max"]
        for code, block in evidence["by_code"].items():
            assert block["given"] == len(cell["codes_task_ids"][code])
            assert block["given"] == block["with_row"] + len(block["missing_task_ids"])
            for missing in block["missing_task_ids"]:
                assert missing not in evidence["by_id"] or evidence["by_id"][missing]["seg1_rows"] == 0


W7_THREAD_SQL = REPO / "deploy" / "loadtest" / "r23_thread_from_checkpoints.sql"


def test_turns_are_numbered_over_full_history_before_the_window_filters(monkeypatch):
    """🔴 假绿守卫（W7 第二十五轮 ⑭b 点名的那一族）：**先按窗口过滤再算 turn** 会把窗口里的第 2 轮读成 turn1
    ⇒ `crash_turn2plus` 静默归零。本器件的形状是"全历史赋号 → 调用方按窗口筛"，这里双向对照。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = mod.stamp_has_row(
        mod.thread_turns([("th1", "tk_pre", t0), ("th1", "tk_inwin", t0 + timedelta(hours=2))]),
        {"tk_pre": t0 + timedelta(seconds=3)}, {"tk_pre": 1})
    block = mod.cell_thread_position(ruler, [], t0 + timedelta(hours=1), t0 + timedelta(hours=3),
                                     terminal=1, gap=1)
    assert block["window_matched_runs"] == 1
    assert block["runs_by_turn_bucket"] == {"turn1": 0, "turn2plus": 1}
    assert block["crash_turn2plus"] == 1 and block["crash_turn1"] == 0
    assert block["turn2plus_no_row_ge_gap"] is True and block["scope_empty"] is False
    #: 反证（同一条 run 单独喂进去 = "先过滤"的形状）：号会变成 turn1 ⇒ 判据分子归零、假绿
    filtered_first = mod.thread_turns([("th1", "tk_inwin", t0 + timedelta(hours=2))])
    assert filtered_first["by_tk"]["tk_inwin"]["turn"] == 1
    #: 尺自检：一个 tk 落多个 thread ⇒ 不静默取第一个，整段作废（W7 的 ① 段同判据）
    ambiguous = mod.thread_turns([("th1", "tk_x", t0), ("th2", "tk_x", t0 + timedelta(minutes=1))])
    assert ambiguous["ambiguous_tk_to_threads"] == ["tk_x"]


def test_the_literal_equation_is_published_only_as_a_do_not_use_column(monkeypatch):
    """架构 `v1.7.12` 的字面式 `terminal − 审计行(turn≥2)` 被减数没有限定 ⇒ 会被 turn1 的行放大。

    本器件的形状：原式照旧（`gap_for_this_cell`），字面式**也算出来但命名成禁用列**
    （`gap_literal_DO_NOT_USE`，做法照 W7 第二十五轮 ⑭）⇒ "两种式子差多少"可复算，且不会被当判据引用。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = mod.stamp_has_row(
        mod.thread_turns([("th1", "tk_a", t0), ("th1", "tk_b", t0 + timedelta(minutes=1))]),
        {"tk_a": t0, "tk_b": t0 + timedelta(minutes=1)}, {"tk_a": 1, "tk_b": 1})
    block = mod.cell_thread_position(ruler, ["tk_a", "tk_b"], t0 - timedelta(seconds=1),
                                     t0 + timedelta(minutes=5), terminal=2, gap=0)
    assert block["receipt_tk_turn2plus"] == 1
    assert block["gap_for_this_cell"] == 0            # 原式：不差
    assert block["gap_literal_DO_NOT_USE"] == 1       # 字面式：凭空"差 1"
    assert block["crash_turn2plus"] == 0
    probe_src = PROBE.read_text(encoding="utf-8")
    for name in re.findall(r'"([A-Za-z0-9_]*literal[A-Za-z0-9_]*)"', probe_src):
        assert "DO_NOT_USE" in name, f"字面式列没打禁用标：{name}"
    note = mod.summarize([], 0.0, ruler)["thread_channel"]["naming_note"]
    assert "crash_turn2plus" in note and "DO_NOT_USE" in note
    #: 不复制他的 SQL（复制 = 第二份真相）：号是 Python 赋的，尺的 SQL 里不该出现窗口函数
    assert "row_number" not in mod.CHECKPOINT_RUNS_SQL


@pytest.mark.skipif(not W7_THREAD_SQL.exists(), reason="W7 的 thread 尺文件不在位")
def test_the_thread_ruler_is_borrowed_by_section_label_not_by_line_number(monkeypatch):
    """同源守卫：借 W7 的 thread 尺语义 ⇒ 他改尺而我没跟，我方测试当场红。

    ⚠️ 锚点用**语句标签**而不是行号（他第二十五轮 ③：「我下一轮可能要动 ⑥⑦，行号会漂」）。
    钉四处：文件在位、每个段标签仍以 `-- <标签>` 出现、三处被借表达式仍在位、他那个禁用列名仍在位。
    """
    mod = _load_probe(monkeypatch)
    sql_src = W7_THREAD_SQL.read_text(encoding="utf-8")
    assert mod.THREAD_RULER_SOURCE.split()[0] == "deploy/loadtest/r23_thread_from_checkpoints.sql"
    for tag in mod.THREAD_RULER_SECTIONS:
        assert re.search(rf"^-- {re.escape(tag)}", sql_src, re.M), f"W7 的段 {tag} 不见了 ⇒ 尺的语义要重读"
    for needle in ("checkpoint->'channel_values'->>'task_id'",
                   "min((checkpoint->>'ts')::timestamptz)",
                   "row_number() over (partition by",
                   "gap_literal_DO_NOT_USE"):
        assert needle in sql_src, f"W7 尺里少了：{needle}"


@pytest.mark.skipif(not PRODUCT.exists(), reason="产物未生成（本轮没跑过该探针）")
def test_gap_citations_carry_the_window_kind():
    """架构 `U-130 v1.7.13` 的"gap 双口径"：子窗与整窗**都对、不得互换** ⇒ 引用必须带着口径。

    钉两条：① 汇总里每个"违反"格与每条 turn 拆分都带 `window_kind`（少了它，读者无从知道自己引的是哪个口径）；
    ② 产物里有一条写死的引用规则，点名"子窗 / 整窗 / 不得互换"，并且**把边缘偏差的归属写成当前实测结论**
    （第十五轮：残差落在 `terminal − matched`，不是审计侧 pad；抬 pad = 改分母 ⇒ 见 `gap_attribution` /
    `edge_control` 与 `test_product_carries_the_attribution_the_horizon_and_the_kind_distribution`）。
    """
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    s = d["summary"]
    assert s["violated_cells"], "本轮无违反格时此测试应随产物一起重估"
    for v in s["violated_cells"]:
        assert v.get("window_kind"), "违反格没带窗口口径 ⇒ 引用者分不清子窗/整窗"
    rule = s["window_citation_rule"]
    #: `single` 必须被归到**子窗**（回执只含一个场景时，回执窗 = 该场景窗）—— 上一版我把它写成"整窗"，
    #: 那是错的分派：架构点名的"整窗 104/99"是跨回执的整批聚合，本器件从没算过那个口径。
    for needle in ("子窗", "整窗", "不得互换", "单场景", "first_seen"):
        assert needle in rule, f"引用规则少了关键一句：{needle}"
    kinds = {v.get("window_kind") for v in s["violated_cells"]}
    assert kinds <= {"scenario", "single"}, f"违反格里出现了未分派口径的 kind：{kinds}"
    for v in s["thread_channel"]["violated_cells_turn_split"]:
        assert v.get("window_kind")


@pytest.mark.skipif(not PRODUCT.exists(), reason="产物未生成（本轮没跑过该探针）")
def test_product_publishes_the_turn_dimension_only_on_live_windows():
    """吃真产物：turn 这一维必须**自洽且不承担结论**。

    尺不可用 ⇒ `available = false` 且各格不带这一维（"崩臂面未测"绝不许读成"没有崩臂"）；
    尺可用 ⇒ 全库块两桶闭合、窗口块"命中数 = 两桶之和"、作废窗口的格**不许**带尺读数；
    id 级 ⇒ 每个 given id 都要有 `turn`（映射不到就是显式 `null`，不是缺键）。
    """
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    ch = d["summary"]["thread_channel"]
    ruler = d["pg_guard"]["thread_ruler"]
    assert ch["available"] == ruler["available"]
    if ch["available"]:
        assert ruler["usable"] is True and ruler["ambiguous_tk_to_threads"] == 0
        db = ch["db_wide"]
        assert sum(db["runs_by_turn_bucket"].values()) == db["tk_runs"]
        for b in ("turn1", "turn2plus"):
            assert db["runs_by_turn_bucket"][b] == (db["runs_with_audit_row"][b]
                                                    + db["runs_without_audit_row"][b])
    cells = d["cells"]
    with_block = [c for c in cells if c.get("thread_position")]
    assert ch["cells_with_this_dimension"] == len(with_block)
    for cell in with_block:
        b = cell["thread_position"]
        assert b["runs_by_turn_bucket"]["turn1"] + b["runs_by_turn_bucket"]["turn2plus"] \
            == b["window_matched_runs"]
        assert b["scope_empty"] == (b["window_matched_runs"] == 0)
        assert b["crash_turn1"] + b["crash_turn2plus"] <= b["window_matched_runs"]
        assert "gap_literal_DO_NOT_USE" in b
        assert cell.get("inapplicability_reason") != "window_before_table_span"
    assert ch["scope_empty_cells"] == sum(1 for c in with_block if c["thread_position"]["scope_empty"])
    for cell in cells:
        evidence = cell.get("task_id_evidence")
        if not evidence:
            continue
        given = {t for group in cell["codes_task_ids"].values() for t in group}
        assert set(evidence["turn_of_given_id"]) == given
        for t in evidence["by_id"]:
            assert "turn" in evidence["by_id"][t]


def _ruler_with_two_turns(mod, t0: datetime):
    """一条 thread 两轮：turn1 落了审计行、turn2 没落 ⇒ 窗口内 matched=2 / crash_turn2plus=1。"""
    return mod.stamp_has_row(
        mod.thread_turns([("th1", "tk_a", t0), ("th1", "tk_b", t0 + timedelta(minutes=1))]),
        {"tk_a": t0 + timedelta(seconds=5)}, {"tk_a": 1})


def test_the_gap_crash_residue_is_attributed_to_the_ruler_not_the_audit_pad(monkeypatch):
    """🔴 第十五轮的核心对照：W7 第二十六轮 ① 猜"gap 与 crash 对不上是我方审计侧 pad 的漏计"⇒ 双向验。

    正头（一格一行成立）：窗口内 2 条 run、其中 1 条有行、回执自报 terminal=3 ⇒
    `gap = 3 − 1 = 2`、`crash_total = 1`、残差 **1** 恰好等于 `terminal − matched = 3 − 2 = 1`
    ⇒ 残差来自"回执终态 ≠ 尺配上的 run"，**不是**审计行被 pad 挡在窗外。
    反头（一格一行不成立）：窗口内多一条**尺配不到**的行（别人的批次落在同一时钟窗）⇒
    `row_run_agreement` 与 `identity_holds` 必须**同时**变 False ⇒ 这一族才是"时间窗归属"真正的失败模式。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = _ruler_with_two_turns(mod, t0)
    kw = dict(begin=t0 - timedelta(seconds=1), end=t0 + timedelta(minutes=5), terminal=3)

    good = mod.cell_thread_position(ruler, ["tk_a"], gap=2, audit_rows=1, **kw)
    assert good["window_matched_runs"] == 2 and good["crash_turn2plus"] == 1 and good["crash_turn1"] == 0
    assert good["runs_with_row_in_window"] == 1 and good["audit_rows_in_window"] == 1
    assert good["row_run_agreement"] is True
    assert good["terminal_minus_matched_runs"] == 1 and good["gap_minus_crash_total"] == 1
    assert good["identity_holds"] is True

    #: 反头：多一条不属于本尺的行 ⇒ 两套归属分叉，恒等式当场不成立（这正是"时间窗会低估 gap"的形状）
    bad = mod.cell_thread_position(ruler, ["tk_a", "tk_other_batch"], gap=1, audit_rows=2, **kw)
    assert bad["row_run_agreement"] is False
    assert bad["audit_rows_unmapped_to_thread"] == 1
    assert bad["identity_holds"] is False


def test_a_cell_read_inside_the_write_delay_horizon_is_not_citable(monkeypatch):
    """🔴 "还没写" ≠ "不会有"（W7 ⑭c 交给我方做的对照）：读数年龄 < 观测 max lag ⇒ 崩臂数**不可引**（假红方向）。

    三态都要钉：`True` = 在途、`False` = 过了静默期（唯一可引的一态）、`None` = 没有延迟样本或窗口里
    没配上 run ⇒ **未知不等于可以引**。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = _ruler_with_two_turns(mod, t0)
    kw = dict(begin=t0 - timedelta(seconds=1), end=t0 + timedelta(minutes=5), terminal=3,
              gap=2, audit_rows=1)

    early = mod.cell_thread_position(ruler, ["tk_a"], max_lag_s=188.0,
                                     now=t0 + timedelta(minutes=1, seconds=10), **kw)
    assert early["too_soon_to_read"] is True and early["crash_turn2plus_citable"] is False
    assert early["read_age_s"] == 10.0

    late = mod.cell_thread_position(ruler, ["tk_a"], max_lag_s=188.0,
                                    now=t0 + timedelta(minutes=1, seconds=400), **kw)
    assert late["too_soon_to_read"] is False and late["crash_turn2plus_citable"] is True

    unknown = mod.cell_thread_position(ruler, ["tk_a"], max_lag_s=None,
                                       now=t0 + timedelta(hours=9), **kw)
    assert unknown["too_soon_to_read"] is None and unknown["crash_turn2plus_citable"] is False
    #: 窗口里一条 run 都没配上 ⇒ 年龄无从算 ⇒ 同样是 None（不许默认成"可以引"）
    empty = mod.cell_thread_position(ruler, [], max_lag_s=188.0, now=t0 + timedelta(hours=9),
                                     begin=t0 + timedelta(hours=1), end=t0 + timedelta(hours=2),
                                     terminal=3, gap=2, audit_rows=1)
    assert empty["scope_empty"] is True and empty["too_soon_to_read"] is None


def test_widening_the_pad_is_published_as_a_cost_not_as_a_fix(monkeypatch):
    """W7 第 3 条给的两个方向之一（把 pad 抬到 ≥ max lag）不是免费的：它**吸进邻近 run** = 改分母。

    ⇒ 器件把代价做成读数（`edge_control`），并且只并列、不进判据；根治要么走 A17/架构，
    要么换配窗键（我方下一轮的默认）。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = mod.stamp_has_row(
        mod.thread_turns([("th1", "tk_a", t0), ("th1", "tk_b", t0 + timedelta(minutes=1)),
                          ("th9", "tk_right", t0 + timedelta(minutes=5, seconds=20)),
                          ("th8", "tk_left", t0 - timedelta(seconds=20))]),
        {"tk_a": t0}, {"tk_a": 1})
    block = mod.cell_thread_position(
        ruler, ["tk_a"], begin=t0 - timedelta(seconds=1), end=t0 + timedelta(minutes=5),
        terminal=2, gap=1)
    edge = block["edge_control"]
    assert block["window_matched_runs"] == 2, "当前 pad 下不该吸进邻近 run"
    assert edge["extra_runs_if_right_pad_widened"] == 1
    assert edge["extra_runs_if_left_pad_widened"] == 1
    assert edge["matched_at_current_pad"] == block["window_matched_runs"]


def test_summary_publishes_the_window_kind_distribution(monkeypatch):
    """🔴 上一轮我把「45 格全为 `single`」写进了文档与回执，而产物里**没有任何一处给出分布** ⇒ 那句话没人反对。

    ⇒ 口径的**分布**本身必须是字段：`summary.window_kind_counts`，且总数与逐格 `window_kind` 闭合。
    （现查真值 = `single` 41 + `ambiguous` 4 —— 不是"全为 single"；见交付 §5.45。）
    """
    mod = _load_probe(monkeypatch)
    rows = [{"receipt": "a.json", "state": mod.INVARIANT_VIOLATED, "denominator": 3,
             "denominator_basis": mod.BASIS_DERIVED, "admitted": 3, "terminal": 3,
             "audit_rows": 1, "diff": 2, "inapplicability_reason": None, "window_kind": "single"},
            {"receipt": "b.json", "state": mod.AMBIGUOUS_WINDOW, "denominator": None,
             "denominator_basis": None, "admitted": None, "terminal": None,
             "audit_rows": None, "diff": None, "inapplicability_reason": "window_ambiguous",
             "window_kind": "ambiguous"}]
    s = mod.summarize(rows, 0.0)
    assert s["window_kind_counts"] == {"single": 1, "ambiguous": 1}
    assert sum(s["window_kind_counts"].values()) == len(rows)


def test_the_thread_scope_sql_avoids_both_null_traps(monkeypatch):
    """🔴 「没有 tk」这条谓词的**两种错法**都要挡：`is null`（几乎恒真）与裸 `bool_or(… like …)`（恒 0）。

    第二个不是假想敌：我方第一版就写了裸 `bool_or`，`NULL like …` ⇒ NULL 被 `bool_or` 忽略 ⇒
    全是"无 tk"的 thread 聚合成 NULL 而不是 false ⇒ `filter (where not has_tk)` **恒 0**，
    被自己的产物测试逮到（`1322 == 1317 + 0`，交付 §5.46）。⇒ 这条是**源码形状**守卫，
    产物没重跑也会红。
    """
    mod = _load_probe(monkeypatch)
    sql_src = mod.THREAD_SCOPE_SQL
    assert "is null" not in sql_src, "用 is null 量「无 tk」会几乎恒真（W7 第一稿的错法）"
    assert "coalesce(checkpoint->'channel_values'->>'task_id' like 'tk_%', false)" in sql_src, \
        "bool_or 吞 NULL ⇒ 必须 coalesce 成 false，否则 threads_without_tk 恒 0"
    assert "filter (where not has_tk)" in sql_src and "filter (where has_tk)" in sql_src
    #: 三条读数必须能闭合（产物侧的闭合断言另有一条吃真产物的测试）
    for col in ("threads_all", "threads_with_tk", "threads_without_tk", "threads_multi_tk"):
        assert col in sql_src, f"口径读数缺列：{col}"


def test_the_thread_scope_block_is_closed_and_self_checking(monkeypatch):
    """🔴 「1,322 还是 1,317」这类数**必须连谓词一起落产物**（W7 第二十六轮 ⑤ = 我方 P23 ⑥ 的诉求）。

    三条同时钉：① 三个 thread 谓词读数**闭合**（`all == with_tk + without_tk`）；
    ② `tk_runs − threads_with_tk == 全库 turn2plus 桶` 这条**算术自证**（每条 thread 从 1 连续编号才成立，
       错成"每窗重新起号"就不可能相等）；③ 口径读数取不到时落 `available = false`，**不许静默缺项**。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = mod.stamp_has_row(
        mod.thread_turns([("th1", "tk_a", t0), ("th1", "tk_b", t0 + timedelta(minutes=1)),
                          ("th2", "tk_c", t0 + timedelta(minutes=2))]),
        {"tk_a": t0}, {"tk_a": 1})
    ruler["scope"] = {"available": True, "threads_all": 3, "threads_with_tk": 2,
                      "threads_without_tk": 1, "threads_multi_tk": 1}
    db = mod.thread_position(ruler)
    assert db["tk_runs"] == 3 and db["runs_by_turn_bucket"]["turn2plus"] == 1
    assert db["thread_scope"]["closure_threads_add_up"] is True
    assert db["thread_scope"]["turn_numbering_closes"] is True
    assert db["thread_scope"]["tk_runs_minus_threads_with_tk"] == 1

    #: 反头：口径 SQL 失败 ⇒ 显式 available=false，而不是"这一项没了"
    ruler["scope"] = {"available": False, "error": "PermissionDenied: lg.checkpoints"}
    assert mod.thread_position(ruler)["thread_scope"] == {"available": False,
                                                          "error": "PermissionDenied: lg.checkpoints"}


@pytest.mark.skipif(not PRODUCT.exists(), reason="产物未生成（本轮没跑过该探针）")
def test_product_carries_the_attribution_the_horizon_and_the_kind_distribution(monkeypatch):
    """吃真产物：本轮新增的引用面必须都在位，且**不许**自相矛盾。

    ① `gap_attribution` 的恒等式必须在每个带尺的格上成立（不成立 ⇒ 有人把"一格一行"当成了前提）；
    ② `read_horizon` 与 `edge_control` 的格数必须与带尺格数一致，`max_lag_s` 与 `db_wide` 同源；
    ③ `window_kind_counts` 必须与逐格读数闭合（上一轮那句过宽的话就是缺这一件东西才会写出来）；
    ④ 引用规则文本已改口：残差不再归给审计侧 pad，而是点名 `terminal − matched` 与"抬 pad = 改分母"。
    """
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    s = d["summary"]
    ch = s["thread_channel"]
    att = ch["gap_attribution"]
    cells = [c for c in d["cells"] if c.get("thread_position")]
    assert att["identity_holds_all"] is True, "有格不满足「一格一行」⇒ 残差归属要重写，不能沿用本轮结论"
    assert att["checked_cells"] == len(cells)
    assert att["cells_where_rows_differ_from_runs_with_row"] == []
    assert ch["read_horizon"]["max_lag_s"] == ch["db_wide"]["max_lag_s"]
    assert ch["edge_control"]["cells_measured"] == len(cells)
    assert sum(s["window_kind_counts"].values()) == s["n_scenario_cells"]
    rule = s["window_citation_rule"]
    for needle in ("子窗", "整窗", "不得互换", "单场景", "first_seen", "gap_attribution", "改分母"):
        assert needle in rule, f"引用规则少了关键一句：{needle}"
    assert "左边缘会多吸进上一条 run" not in rule, "旧归因还没改口（本轮已实测残差不在审计侧 pad）"
    for v in ch["violated_cells_turn_split"]:
        assert "identity_holds" in v and "too_soon_to_read" in v and "crash_turn2plus_citable" in v
    #: 🔴 thread 数的**谓词口径**与两条自证必须闭合（上一轮这三个数只活在我方文档里，不在产物里）。
    scope = ch["db_wide"]["thread_scope"]
    assert scope["available"] is True
    assert scope["threads_all"] == scope["threads_with_tk"] + scope["threads_without_tk"]
    assert scope["threads_with_tk"] == ch["db_wide"]["threads"]
    assert scope["closure_threads_add_up"] is True and scope["turn_numbering_closes"] is True
    #: 延迟分布的分桶必须是读数（"pad 1 秒放过几成"不许靠别人转述）；负延迟 > 0 ⇒ 配窗方向就该重估。
    spread = ch["db_wide"]["audit_row_minus_first_seen_s"]
    assert spread["negative"] == 0
    assert set(spread["gt_s"]) == {str(x) for x in _load_probe(monkeypatch).LAG_BUCKETS_S}
    assert spread["gt_s"]["1"] <= spread["n"] and spread["gt_s"]["188"] == 0


def test_the_pairing_arm_anchors_w7_section_15(monkeypatch):
    """🔴 判据② 的**配对臂**有了外部同形状语句（W7 按 `v1.7.14` 新起的 ⑮）⇒ 借语义就要锚，不能只写在注释里。

    两件分开钉：① `⑮` 在 `THREAD_RULER_SECTIONS` 里 ⇒ 同源守卫会逐标签检查它，他删/改名我方红；
    ② 产物 `overcount_pairing.external_counterpart` **点名 ⑮** 并写清"同向不互认"（他 ③ 的口径），
      否则下一轮的引用者只会看到我方一家的数、以为那就是全部接触面。
    """
    mod = _load_probe(monkeypatch)
    assert "⑮" in mod.THREAD_RULER_SECTIONS, "⑮ 没进锚点 ⇒ 他删掉那条两臂语句时我方不会红"
    assert "⑮" in mod.THREAD_RULER_SOURCE
    ch = mod.summarize([], 0.0, {"by_tk": {}})["thread_channel"]
    pair = ch["overcount_pairing"]
    counterpart = pair["external_counterpart"]
    assert "⑮" in counterpart and "run" in counterpart, counterpart
    assert "不互认" in counterpart or "不构成" in counterpart, "外部对应件必须自带不可互认的口径"
    #: **五面并存**必须落成**清单**（少一面就会被读成一面）：W4 夹具 / `07` 文本 / 我方落库面 / W7 ⑮ /
    #:   checkpoint 写面（台账第 8 面，第十七轮按架构 §38 ④ 接进来）。
    faces = " ".join(pair["pairing_faces"])
    assert len(pair["pairing_faces"]) == 5, pair["pairing_faces"]
    for face in ("d73a201", "v1.7.14", "⑮", "overcount_pairing", "checkpoint_writes"):
        assert face in faces, f"pairing_faces 少了 {face} 这一面"
    assert "thread 级上界" in faces, "写面必须自带量纲限制，否则会被读成 run 级证据"
    assert mod.THREAD_RULER_SECTIONS[-1] == "⑰b" and len(mod.THREAD_RULER_SECTIONS) == 12
    assert "⑯" in mod.THREAD_RULER_SECTIONS, "⑯/⑯b 没进锚点 ⇒ 他撤掉写面归属那条语句时我方不会红"
    assert "⑰" in mod.THREAD_RULER_SECTIONS and "⑰b" in mod.THREAD_RULER_SECTIONS, \
        "⑰/⑰b（格2/格3 + 覆盖面形状）没进锚点 ⇒ 他撤掉时我方不会红"


def test_the_checkpoint_writes_face_is_a_crosscheck_not_a_ruler(monkeypatch):
    """🔴 架构 §38 ④ 给 W6 的零成本动作 = 拿台账**第 8 面** `lg.checkpoint_writes` 给我方判据② 做**对照**。

    钉四件事（每件都对应一种会把这把尺读歪的方式）：
    ① 对撞是**集合**对撞（`a_minus_b` / `b_minus_a` 分写）⇒ 只比数会把"两侧都 813"读成同一条断言；
    ② 写面**归不出轮次**（`attributable_to_a_specific_turn` 恒 False）⇒ 不许写"这轮的终态写在第 2 轮"；
    ③ `max_terminal_writes_per_thread` 是 **thread 级上界** ⇒ 双写形状（= 2）必须自己变红，不靠读者想到；
    ④ 取不到 ⇒ `thread_position` 出口是 `None`（**没测**），不能静默变成 `{}` 或 0。
    """
    mod = _load_probe(monkeypatch)
    shape = {"rows_all": 46460, "threads_all": 1318, "ck_threads_all": 1322,
             "ck_only_threads": 4, "writes_only_threads": 0,
             "terminal_rows": 813, "terminal_threads": 813, "max_terminal_writes_per_thread": 1}
    ruler = {"by_tk": {
        "tk_1": {"thread_id": "th:1", "turn": 1, "audit_rows": 1, "has_row": True,
                 "first_seen": None, "audit_ts": None},
        "tk_2": {"thread_id": "th:2", "turn": 1, "audit_rows": 0, "has_row": False,
                 "first_seen": None, "audit_ts": None},
        "tk_3": {"thread_id": "th:3", "turn": 2, "audit_rows": 1, "has_row": True,
                 "first_seen": None, "audit_ts": None},
    }, "ambiguous_tk_to_threads": [], "usable": True}
    block = mod.writes_crosscheck(ruler, shape, {"th:1", "th:9"})
    eq = block["set_equality_with_my_turn1_face"]
    assert (eq["a_turn1_threads_with_audit_row"], eq["b_terminal_write_threads"]) == (1, 2)
    assert (eq["a_minus_b"], eq["b_minus_a"], eq["equal"]) == (0, 1, False)
    assert eq["b_threads_without_any_tk"] == 1, "写面里有我方尺上没有的 thread ⇒ 不许静默并入"
    assert block["turn2plus_overlap"]["a_turn2plus_intersect_b"] == 0
    #: 🔻 第十八轮改口：第十七轮这里**写死 False**（"归不出轮次"是转述、不是我方读数）⇒ 现在没传归属数据
    #:    必须落 `None`（= **没测**），既不真也不假。
    assert block["turn2plus_overlap"]["attributable_to_a_specific_turn"] is None
    assert block["run_attribution"] is None
    assert block["terminal_writes"]["any_double_terminal_write"] is False
    assert block["shape"]["thread_sets_equal_across_faces"] is False, "1,318 ≠ 1,322 必须报出来"
    double = mod.writes_crosscheck(ruler, {**shape, "max_terminal_writes_per_thread": 2}, {"th:1"})
    assert double["terminal_writes"]["any_double_terminal_write"] is True
    assert len(block["limits"]) == 3 and "checkpoint_id" in block["limits"][0]
    assert "按通道集" in block["limits"][0], "限制句必须按通道集分列，不许整张表一刀切"
    assert "不是判据" in block["verdict_role"] and "classify()" in block["verdict_role"]
    assert mod.thread_position(ruler).get("checkpoint_writes") is None
    assert mod.thread_position({**ruler, "writes": block})["checkpoint_writes"] == block
    text = mod.CHECKPOINT_WRITES_SHAPE_SQL
    assert "except" in text.lower() and "thread_id is null" not in text, "对撞用集合差，不用 is null"


def test_run_attribution_is_measured_per_channel_set(monkeypatch):
    """🔴 第十八轮把「切不出 run 边界」这句转述改成实测后作废；第十九轮又补量了它留下的两格 ⇒ 钉六件事：
    ① 覆盖面按通道集分列（`terminal_unmatched_rows` vs `route_unmatched_rows`），不许整张表一刀切；
    ② 归属后的 turn 用**我方尺**数（先编号、后归属），尺里没有的 tk 落 `unknown_runs` 而不是被丢掉；
    ③ 「该面切不切得出第 2 轮」用**路由行**回答（`route_rows_at_turn2plus`），terminal 只回答"有没有写终态"；
    ④ 不可归的行要**拆开并闭合**（建线期 / 真损失 / thread 无 tk）——不闭合就不许说"机制已查"；
    ⑤ 粒度（rows / runs / threads）三个数常常不等 ⇒ 成对报 + `runs_vs_threads_differ` 点名（W7 ⑯ 那句
       「70 条全在 turn1」的根因就是把 thread 数当 run 数）；
    ⑥ `attribution_closes` 只在 terminal 全命中、无 unknown、且全落第一轮时才真。
    """
    mod = _load_probe(monkeypatch)
    ruler = {"by_tk": {
        "tk_a": {"thread_id": "th:1", "turn": 1, "first_seen": None},
        "tk_b": {"thread_id": "th:1", "turn": 2, "first_seen": None},
        "tk_c": {"thread_id": "th:2", "turn": 2, "first_seen": None},
    }, "ambiguous_tk_to_threads": [], "usable": True}
    rows_by_tk = {"tk_a": 1, "tk_b": 0, "tk_c": 1}
    join = {"terminal_rows_via_join": 2, "terminal_matched_rows": 2, "terminal_unmatched_rows": 0,
            "route_rows": 8482, "route_channels": 22, "route_unmatched_rows": 1318,
            "route_unmatched_threads": 1318, "tk_runs_touched": 3}
    un_shape = {"route_rows": 8482, "route_unmatched_rows": 1318, "route_unmatched_threads": 1318,
                "unmatched_before_first_tk": 1317, "unmatched_at_or_after_first_tk": 0,
                "unmatched_on_threads_without_tk": 1, "threads_with_real_loss_rows": 0}
    block = mod.writes_attribution(join, {"tk_a"}, {"tk_c", "tk_ghost"}, {"tk_b", "tk_c"},
                                   un_shape, ruler, rows_by_tk)
    assert block["coverage"]["join_covers_terminal_rows"] is True
    assert block["terminal_writes_on_runs"] == {"runs": 1, "turn1": 1, "turn2plus": 0, "unknown_runs": 0,
                                                "zero_audit_row_runs": 0, "crash_turn2plus_runs": 0}
    supp = block["audit_supp_routes_on_runs"]
    assert (supp["runs"], supp["turn2plus"], supp["unknown_runs"]) == (2, 1, 1), supp
    assert supp["crash_turn2plus_runs"] == 0, "tk_c 有审计行 ⇒ 不能算成崩 run 上的路由"
    #: ③ 路由行落 turn≥2 ⇒ 该面切得出第 2 轮（这正是"现测排除黏性"那一维）
    rt = block["route_rows_on_runs"]
    assert (rt["runs"], rt["turn1"], rt["turn2plus"]) == (2, 0, 2), rt
    disc = block["discriminator"]
    assert disc["route_rows_at_turn2plus"] == 2 and disc["terminal_writes_at_turn2plus"] == 0
    assert disc["face_can_split_turn2plus"] is True, "路由有行 + terminal 无行 ⇒ 必须报「切得出第 2 轮」"
    assert (disc["audit_supp_at_turn2plus"], disc["audit_supp_on_crash_turn2plus_runs"]) == (1, 0)
    assert "0 不许读成" in disc["reads"], "pre-fix 就为 0 的列不得被读成验收通过（§8-33 那条恒真陷阱）"
    #: ④ 拆开且闭合才叫"机制已查"
    shape_blk = block["unmatched_route_rows_shape"]
    assert shape_blk["closure_adds_up"] is True and shape_blk["real_coverage_loss_rows"] == 0
    #: 两条 join 形状（只按 `checkpoint_id` / 再绑 `thread_id`）必须给同一个不可归行数
    assert shape_blk["agrees_with_attribution_join"] is True, shape_blk
    assert mod.writes_attribution(join, {"tk_a"}, set(), set(),
                                  {**un_shape, "route_unmatched_rows": 1300},
                                  ruler, rows_by_tk)["unmatched_route_rows_shape"][
                                      "agrees_with_attribution_join"] is False
    unclosed = {**un_shape, "unmatched_before_first_tk": 900}
    assert mod.writes_attribution(join, {"tk_a"}, set(), set(), unclosed,
                                  ruler, rows_by_tk)["unmatched_route_rows_shape"]["closure_adds_up"] is False
    #: ⑤ 粒度：audit_supp 两条 run 落在两个 thread ⇒ runs == threads；路由两 run 同在两 thread 也一样，
    #:    构造一条"两 run 同 thread"看它会不会点名
    same_thread = mod.writes_attribution(join, {"tk_a"}, {"tk_a", "tk_b"}, set(), un_shape, ruler, rows_by_tk)
    assert same_thread["granularity"]["audit_supp"] == {"runs": 2, "threads": 1}
    assert "audit_supp" in same_thread["granularity"]["runs_vs_threads_differ"], same_thread["granularity"]
    assert block["attribution_closes"] is True
    #: ⑥ 三种不闭合形状都不许报 closes
    open_join = {**join, "terminal_unmatched_rows": 5}
    assert mod.writes_attribution(open_join, {"tk_a"}, set(), set(), un_shape,
                                  ruler, rows_by_tk)["attribution_closes"] is False
    unknown = mod.writes_attribution(join, {"tk_ghost"}, set(), set(), un_shape, ruler, rows_by_tk)
    assert unknown["attribution_closes"] is False and unknown["terminal_writes_on_runs"]["unknown_runs"] == 1
    assert mod.writes_attribution(join, {"tk_a", "tk_b"}, set(), set(), un_shape,
                                  ruler, rows_by_tk)["attribution_closes"] is False
    #: `attributable_to_a_specific_turn` 跟着归属走（不是恒 False、也不是恒 True；没传 = None）
    shape2 = {"rows_all": 1, "threads_all": 1, "ck_threads_all": 1, "ck_only_threads": 0,
              "writes_only_threads": 0, "terminal_rows": 1, "terminal_threads": 1,
              "max_terminal_writes_per_thread": 1}
    blk = mod.writes_crosscheck(ruler, shape2, {"th:1"}, attrib=block)
    assert blk["turn2plus_overlap"]["attributable_to_a_specific_turn"] is True
    assert blk["run_attribution"] is block
    assert "通道集" in blk["limits"][0] and "unmatched_route_rows_shape" in blk["limits"][0]
    #: 器件形状：归属类语句里不许出现 `row_number()`（turn 只能由我方尺数），也不许拿 `is null` 当集合差
    for const in (mod.WRITES_ATTRIBUTION_SQL, mod.TERMINAL_RUN_TKS_SQL, mod.AUDIT_SUPP_RUN_TKS_SQL,
                  mod.ROUTE_RUN_TKS_SQL):
        assert "row_number()" not in const, "turn 只能由我方尺数（第三份真相禁令）"
    assert "branch:to:audit_supp" in mod.AUDIT_SUPP_RUN_TKS_SQL
    assert "branch:to:%" in mod.ROUTE_RUN_TKS_SQL
    #: ⑰b 那一族的三分类必须由 `first_tk` 比较得出，不能拿"没有 X"用 `is null` 糊（交付 §5.43 同族）
    un_sql = mod.ROUTE_UNMATCHED_SHAPE_SQL
    assert "first_tk" in un_sql and "<" in un_sql and ">=" in un_sql
    assert "count(distinct thread_id)" in un_sql, "不可归属要同时报 thread 数（粒度那一格）"
    #: 🔴 本轮实跑第一次红在这里：下游 CTE 从 `all_ck` 取数却写 `checkpoint->…`（`all_ck` 没投影那列）
    #:    ⇒ `UndefinedColumn` 把**整块** `checkpoint_writes` 打成 `available: false`（连上一轮的归属一起没了）。
    #:    守卫 = `checkpoint` 只许在 `all_ck` 里出现一次（select + ts），其余 CTE 只能引用出口列名。
    assert un_sql.count("checkpoint->") == 2, "只有 all_ck 能读 checkpoint 原文 ⇒ 下游 CTE 用 tk / ts 列名"


def test_the_direct_form_is_blind_to_a_double_written_run(monkeypatch):
    """🔴 判据② 现在是**两条**断言（架构 `v1.7.14` 裁直读式时补的那一臂）⇒ 这一条测的就是"为什么要补"。

    形状：两条 thread、每条两轮，窗口覆盖全部 4 条 run；`tk_b`（turn2）**落了两行**。
    ⇒ 直读式（零行的 run 数）= **0**（它看不见多落），配对式 = **1**，第二形 = 2 − 3 = **−1**（负 = 多落）。
    反头：所有 run 各 1 行 ⇒ 三者同时归零 ⇒ 这一臂今天不报东西，防的是**将来双写时恒绿**（U-129 那一族）。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    run_rows = [("th1", "tk_a", t0), ("th1", "tk_b", t0 + timedelta(minutes=1)),
                ("th2", "tk_c", t0), ("th2", "tk_d", t0 + timedelta(minutes=1))]
    ts = {"tk_a": t0 + timedelta(seconds=5), "tk_b": t0 + timedelta(seconds=65),
          "tk_c": t0 + timedelta(seconds=5), "tk_d": t0 + timedelta(seconds=65)}
    kw = dict(window_task_ids=["tk_a", "tk_b", "tk_c", "tk_d"],
              begin=t0 - timedelta(seconds=1), end=t0 + timedelta(minutes=5),
              terminal=4, gap=0)

    double = mod.cell_thread_position(mod.stamp_has_row(mod.thread_turns(run_rows), ts,
                                                        {"tk_a": 1, "tk_b": 2, "tk_c": 1, "tk_d": 1}),
                                      **kw, audit_rows=5)
    assert double["crash_turn2plus"] == 0, "直读式：零行的 run 数 = 0（这一臂看不见双写，正是它盲的地方）"
    assert double["multi_row_turn2plus_runs"] == 1
    assert double["rows_by_turn2plus_runs"] == 3 and double["runs_by_turn_bucket"]["turn2plus"] == 2
    assert double["second_form_turn2plus"] == -1, "第二形为负 = 多落 ⇒ 它是直读式看不见的另一支"
    assert double["gap_for_this_cell"] == 0, "格级 gap 也被抵消掉了（少一行 + 多一行）⇒ 只有 run 级看得见"

    single = mod.cell_thread_position(mod.stamp_has_row(mod.thread_turns(run_rows), ts,
                                                        {"tk_a": 1, "tk_b": 1, "tk_c": 1, "tk_d": 1}),
                                      **kw, audit_rows=4)
    assert single["multi_row_turn2plus_runs"] == 0 and single["second_form_turn2plus"] == 0
    #: 全库面同一件事：`direct_vs_second_form_agree` 只在"每 run 至多一行"时才 True。
    dbl_ruler = mod.stamp_has_row(mod.thread_turns(run_rows), ts, {"tk_a": 1, "tk_b": 2, "tk_c": 1, "tk_d": 1})
    one_ruler = mod.stamp_has_row(mod.thread_turns(run_rows), ts, {"tk_a": 1, "tk_b": 1, "tk_c": 1, "tk_d": 1})
    assert mod.thread_position(dbl_ruler)["direct_vs_second_form_agree"] is False
    assert mod.thread_position(one_ruler)["direct_vs_second_form_agree"] is True
    assert mod.thread_position(dbl_ruler)["multi_row_turn2plus_runs"] == 1


def test_the_reading_precondition_needs_both_the_scope_and_the_silence(monkeypatch):
    """架构 `v1.7.14` 同轮补记连带④：**作用域非空 ∧ 年龄 > 已观测 max lag** 两条都过才叫"前置通过"。

    四态各自钉住（关键是 **缺任一条 ⇒ 不可引**，以及"未知"不许当成"通过"）：
    ① 两条都过；② 窗口里没配上任何 run（空作用域，哪怕年龄再大也不可引）；③ 读得太早（假红方向）；
    ④ 没有延迟样本 ⇒ `aged_beyond_max_lag` 为 `null` ⇒ 同样不可引。
    """
    mod = _load_probe(monkeypatch)
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = _ruler_with_two_turns(mod, t0)
    inside = dict(window_task_ids=["tk_b"], begin=t0 - timedelta(seconds=1), end=t0 + timedelta(minutes=5),
                  terminal=2, gap=1, audit_rows=1)

    aged = mod.cell_thread_position(ruler, max_lag_s=188.0, now=t0 + timedelta(hours=10), **inside)
    assert aged["reading_precondition"] == {
        "scope_non_empty": True, "aged_beyond_max_lag": False, "both_pass": True,
        "read_age_over_max_lag": round(aged["read_age_s"] / 188.0, 3)}
    assert aged["crash_turn2plus_citable"] is aged["reading_precondition"]["both_pass"], \
        "citable 与前置必须是**同一个算式**（否则引用者拼出来的和产物里的不是一回事）"
    assert aged["reading_precondition"]["read_age_over_max_lag"] > 1, "年龄要引**比值**，秒数随读数时刻漂移"

    empty = mod.cell_thread_position(ruler, max_lag_s=188.0, now=t0 + timedelta(hours=10),
                                     **{**inside, "window_task_ids": [],
                                        "begin": t0 + timedelta(hours=8), "end": t0 + timedelta(hours=9)})
    assert empty["scope_empty"] is True and empty["reading_precondition"]["scope_non_empty"] is False
    assert empty["crash_turn2plus_citable"] is False, "空作用域**不得**记成「零行 = 没有崩臂」（假绿形状）"

    early = mod.cell_thread_position(ruler, max_lag_s=188.0, now=t0 + timedelta(minutes=1), **inside)
    assert early["reading_precondition"]["scope_non_empty"] is True
    assert early["reading_precondition"]["aged_beyond_max_lag"] is True
    assert early["crash_turn2plus_citable"] is False, "两条里缺一根也不行"

    unknown = mod.cell_thread_position(ruler, max_lag_s=None, now=t0 + timedelta(hours=10), **inside)
    assert unknown["reading_precondition"]["aged_beyond_max_lag"] is None
    assert unknown["reading_precondition"]["read_age_over_max_lag"] is None
    assert unknown["crash_turn2plus_citable"] is False, "「阈值未知」不等于「通过」"


def test_the_row_count_column_is_never_the_receipt_task_count(monkeypatch):
    """🔻 本轮**改了一列名**：旧 `rows_turn2plus` 读起来像"行数"，数的其实是**回执侧 task_id 个数**。

    ⇒ 与交付 §5.40（键数冒充行数）同族。现在两列**同时在场且各管各的**：
    `receipt_tk_turn2plus`（回执侧计数，`gap_literal_DO_NOT_USE` 的减数用它）与
    `rows_by_turn2plus_runs`（窗口内 run 的**真行数**，逐行取回后在 Python 里数）。
    """
    mod = _load_probe(monkeypatch)
    src = PROBE.read_text(encoding="utf-8")
    assert '"rows_turn2plus"' not in src, "旧列名回来了 ⇒ 两列又会被读成同一件事"
    assert '"receipt_tk_turn2plus"' in src and '"rows_by_turn2plus_runs"' in src
    #: 行数不许由库里聚合出来再当"行数"引（§5.40 的规矩）⇒ 取证侧必须是逐行取回 + Python 计数
    fetch = src[src.index("audit_row_pairs"):src.index("ruler = stamp_has_row")]
    assert "group by task_id" not in fetch, "行数一旦经过聚合就不是行数了"
    t0 = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    ruler = mod.stamp_has_row(
        mod.thread_turns([("th1", "tk_a", t0), ("th1", "tk_b", t0 + timedelta(minutes=1))]),
        {"tk_a": t0 + timedelta(seconds=5), "tk_b": t0 + timedelta(seconds=65)},
        {"tk_a": 1, "tk_b": 3})
    block = mod.cell_thread_position(ruler, ["tk_a", "tk_b"], t0 - timedelta(seconds=1),
                                     t0 + timedelta(minutes=5), terminal=2, gap=0, audit_rows=4)
    assert block["receipt_tk_turn2plus"] == 1 and block["rows_by_turn2plus_runs"] == 3


@pytest.mark.skipif(not PRODUCT.exists(), reason="产物未生成（本轮没跑过该探针）")
def test_product_carries_the_pairing_form_and_the_two_preconditions():
    """吃真产物：判据② 两条断言 + 读数前置两条 + v1.7.14 措辞，都必须**已经在盘上**。"""
    d = json.loads(PRODUCT.read_text(encoding="utf-8"))
    s = d["summary"]
    ch = s["thread_channel"]
    pair = ch["overcount_pairing"]
    for key in ("primary_form", "pair_form", "second_form", "cells_measured", "multi_row_turn2plus_total",
                "cells_with_negative_second_form", "db_wide_agreement"):
        assert key in pair, f"配对块少了 {key}"
    cells = [c for c in d["cells"] if c.get("thread_position")]
    assert pair["cells_measured"] == len(cells)
    assert pair["multi_row_turn2plus_total"] == sum(c["thread_position"]["multi_row_turn2plus_runs"] for c in cells)
    #: 🔴 架构 `§20.4` ㉗ 那条"限定写在差的一侧 = 另一侧没写"的形状守卫：**第二形**两侧都带 `turn≥2`。
    assert pair["second_form"].count("turn≥2") == 2, "第二形的限定没写全 ⇒ 又变回字面式"
    horizon = ch["read_horizon"]
    assert "作用域非空" in horizon["preconditions"] and "比值" in horizon["preconditions"]
    assert horizon["cells_citable"] + horizon["cells_precondition_fail"] == len(cells)
    for c in cells:
        pre = c["thread_position"]["reading_precondition"]
        assert pre["both_pass"] == c["thread_position"]["crash_turn2plus_citable"]
    #: 措辞必须是 v1.7.14 的形状：三个式子各自有名、且"分母不同源"与"缺前置记 UNVERIFIED"都在引用规则里。
    note = ch["naming_note"]
    for needle in ("crash_turn2plus", "multi_row_turn2plus_runs", "second_form_turn2plus", "两侧同限定",
                   "DO_NOT_USE", "receipt_tk_turn2plus"):
        assert needle in note, f"naming_note 少了 {needle}"
    rule = s["window_citation_rule"]
    for needle in ("哪一个式子", "不可互认", "UNVERIFIED", "window_kind"):
        assert needle in rule, f"引用规则少了 v1.7.14 的一件：{needle}"
    assert "差值式一律禁用" not in rule, "第二形是**允许的**（两侧同限定），别把它和字面式混成一个东西"
