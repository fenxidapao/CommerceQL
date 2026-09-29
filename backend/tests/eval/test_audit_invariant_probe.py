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
* `codes_task_ids` 只认完整形状，且**覆盖面本身是读数**：没带该字段的批次不许写成"task_id 级复算过"；
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
