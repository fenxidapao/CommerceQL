"""`eval/consistency.py`（§17.6 一致性三测）与 `eval/reporter.py`（报告装配 / 渲染）。

归属窗口：W6。

这两个文件共同决定**报告里那些句子有没有依据**：
--------------------------------------------------------------------------
* ② 的静态扫描最容易的失效方式不是误报，是"正则写坏了 → 永远绿"。所以它自带
  **正对照**，本文件再测一次"故意破坏必须被抓"。
* `_known_limitations` 与 `render_markdown` 的汇总句是 §17.4 红线的落点：
  `PASS` 之外的一律不许进"门禁通过"那句话，`UNVERIFIED` 也不算过。
* `parse_pytest_summary` 只许取数：集成层是否跑过要**日志里有证据**才算，
  而"没证据"只能写成"无法断定"，不许替环境宣布"PG 不可达"。
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import consistency as cs
import pytest
import reporter as rp

#: 已知限制里那句 PG 结论的替身（真句子的长度会干扰断言，这里只验「原样出现」）。
PG_TXT = "【PG 面结论占位】"


# ============================================================================
# ① 租户边界一致性
# ============================================================================
def test_boundary_case_selection_only_takes_cases_the_wrap_actually_touches(dataset_cases):
    """不合格用例（没被 `tenant_wrap` 改写过）会让 ① 变成"永远绿的假测试"。"""
    picked = cs.select_boundary_cases(dataset_cases, n=3)
    assert len(picked) == 3
    for c in picked:
        assert str(c["expected_behavior"]) == "execute"
        assert c["gold_result_hash"] and c["eval_tenant"]
        assert cs.bfs.tenant_wrap(str(c["gold_sql"]), str(c["eval_tenant"])) != str(c["gold_sql"])


@pytest.fixture(scope="module")
def cs_result() -> dict:
    """② 的真扫描结果（含正对照）。跑一次即可：它只读文件，不碰 DB。"""
    return cs.assert_field_whitelist()


def test_boundary_selection_is_cross_tenant_first(dataset_cases):
    """实测：纯按文件原序取前 3 条全落在 T_A ⇒ "三条链路相等"只在一个租户上验过。"""
    picked = cs.select_boundary_cases(dataset_cases, n=3)
    assert len({str(c["eval_tenant"]) for c in picked}) > 1
    ordered = [str(c.get("eval_tenant")) for c in dataset_cases if c.get("eval_tenant")]
    assert set(ordered) == {"T_A", "T_B", "T_C"}, "冻结集租户集合变了 → ①的覆盖面要重判"


def test_boundary_selection_is_deterministic(dataset_cases):
    a = [c["case_id"] for c in cs.select_boundary_cases(dataset_cases, n=3)]
    b = [c["case_id"] for c in cs.select_boundary_cases(dataset_cases, n=3)]
    assert a == b, "选取不确定 ⇒ 两次一致性测的不是同一批题，哈希比较失去意义"


def test_selection_skips_refuse_and_hashless_cases():
    """只有 execute + 有 gold_sql + 有 hash + 会被 wrap 改写的才有资格。"""
    good = {"case_id": "G", "gold_sql": "SELECT 1 FROM v_order_paid", "eval_tenant": "T_A",
            "gold_result_hash": "sha256:x", "expected_behavior": "execute"}
    ineligible = [
        {**good, "case_id": "R", "expected_behavior": "refuse"},
        {**good, "case_id": "N", "gold_result_hash": ""},
        {**good, "case_id": "S", "gold_sql": ""},
        {**good, "case_id": "T", "gold_sql": "SELECT 1 FROM v_region"},   # 非租户域 → wrap 无差异
        {**good, "case_id": "U", "eval_tenant": ""},
    ]
    for c in ineligible:
        assert cs.select_boundary_cases([c], n=1) == [], f"{c['case_id']} 不该入选"
    picked = cs.select_boundary_cases([*ineligible, good], n=1)
    assert [c["case_id"] for c in picked] == ["G"]


def test_tenant_boundary_three_hash_chains_agree(dataset_cases, sandbox_db, harness):
    r = cs.test_tenant_boundary(
        cases=dataset_cases, db_path=sandbox_db,
        tenant_scoped_physicals=dict(harness.tenant_scoped_physicals), n=cs.ANCHOR_CASE_N,
    )
    assert r["ok"] is True and r["selection_complete"] is True
    assert r["n_selected"] == r["n_required"] == 3
    for row in r["rows"]:
        assert row["frozen_eq_wrap"] and row["wrap_eq_view"], row
        assert row["error_wrap"] is None and row["error_view"] is None
        assert row["touched_tenant_scoped"] is True
    # 三个租户各一条（跨租户覆盖才是这条测试的判别力所在）
    assert r["tenants_covered"] == ["T_A", "T_B", "T_C"]


def test_tenant_boundary_reports_red_when_selection_is_short(dataset_cases, sandbox_db, harness):
    """要求数 > 可选数 ⇒ 必须 FAIL。空/不足的选择不能表现成"边界一致"。"""
    one = cs.select_boundary_cases(dataset_cases, n=1)
    assert len(one) == 1
    r = cs.test_tenant_boundary(
        cases=one, db_path=sandbox_db,
        tenant_scoped_physicals=dict(harness.tenant_scoped_physicals), n=2,
    )
    assert r["n_selected"] == 1 and r["selection_complete"] is False
    assert r["rows"][0]["ok"] is True, "红必须来自选择不足，而不是这一行本身失败"
    assert r["ok"] is False


def test_boundary_efficacy_proves_the_view_is_actually_filtering(sandbox_db, harness):
    """①的前置探针：视图边界必须**真的减行**，且评测租户集合覆盖全量行。"""
    ts = dict(harness.tenant_scoped_physicals)
    r = cs.test_boundary_efficacy(
        db_path=sandbox_db, tenant_scoped_physicals=ts, tenants=["T_A", "T_B", "T_C"]
    )
    assert r["ok"] is True and len(r["rows"]) == len(ts) == 6
    for row in r["rows"]:
        assert row["filters_something"] is True, f"{row['asset']} 的边界什么都没过滤"
        assert row["covers_all_rows"] is True, f"{row['asset']} 有行落在评测租户之外（视图会静默藏行）"


def test_boundary_efficacy_goes_red_on_a_missing_tenant(sandbox_db, harness):
    """🔴 反例：漏掉一个租户 ⇒ 该租户的行被视图静默藏起来 ⇒ "跨租户不可见"成了假的。"""
    ts = dict(harness.tenant_scoped_physicals)
    r = cs.test_boundary_efficacy(
        db_path=sandbox_db, tenant_scoped_physicals=ts, tenants=["T_A", "T_B"]
    )
    assert r["ok"] is False
    assert any(row["covers_all_rows"] is False for row in r["rows"])


def test_boundary_efficacy_rejects_a_non_identifier_asset_name(sandbox_db, harness):
    ts = {"v_order_paid": "tenant_id", "bad'; DROP": "tenant_id"}
    with pytest.raises(ValueError, match="非法"):
        cs.test_boundary_efficacy(db_path=sandbox_db, tenant_scoped_physicals=ts, tenants=["T_A"])


def test_empty_tenant_list_is_red_not_green(sandbox_db, harness):
    """`ok` 的初值是 `bool(tenants)` —— 传空清单必须红，否则探针变成了恒真。"""
    r = cs.test_boundary_efficacy(
        db_path=sandbox_db, tenant_scoped_physicals=dict(harness.tenant_scoped_physicals), tenants=[]
    )
    assert r["ok"] is False


# ============================================================================
# ② 字段白名单（I-1 的护栏）
# ============================================================================
@pytest.mark.parametrize(
    ("line", "want_hit"),
    [
        ('x = payload["difficulty_struct_sitelabel"]', True),
        ("x = payload.get('difficulty_struct_sitelabel')", True),
        ('x = {"difficulty_struct_sitelabel": 1}', True),
        ("render(case, difficulty_struct_sitelabel=1)", True),
        ('x = payload["difficulty_semantic"]', False),
        ("# payload[\"difficulty_struct_sitelabel\"] 禁止使用", False),
        ("BANNED_FIELD = 'difficulty_struct_sitelabel'  # 只定义名字，不读值", False),
    ],
)
def test_scan_hits_only_read_shapes(tmp_path, line, want_hit):
    p = tmp_path / "sample.py"
    p.write_text(line + "\n", encoding="utf-8")
    hits = cs._scan_file(str(p))
    assert bool(hits) is want_hit, f"{line!r} → {hits}"


def test_scan_skips_the_file_that_defines_the_ban(repo_root):
    """`consistency.py` 必须能写出被禁字段的名字才能禁它 —— 自我排除，不是漏扫。"""
    path = os.path.join(repo_root, "eval", "consistency.py")
    assert cs.BANNED_FIELD in Path(path).read_text(encoding="utf-8")
    assert cs.scan_field_whitelist([path]) == {"n_files_scanned": 0, "hits": [], "ok": True}


def test_whitelist_legs_all_hold_and_the_positive_control_catches(cs_result: dict):
    """:func:`consistency.assert_field_whitelist` 的三条腿 + 正对照。"""
    assert cs_result["ok"] is True
    assert cs_result["source"]["ok"] and cs_result["artifacts"]["ok"]
    assert cs_result["source"]["n_files_scanned"] >= 20
    assert cs_result["self_test"]["caught"] is True, "扫描器自身失效 ⇒ ② 不得判绿"
    assert cs_result["self_test"]["patterns_hit"] == 3
    assert cs_result["control_field_present"] is True, "对照字段被删出冻结集 ⇒ I-1 的物证没了"


def test_positive_control_is_not_hardcoded(tmp_path, monkeypatch):
    """正对照必须真的走一遍扫描器：把被禁字段从形状里换掉就不该命中。"""
    path = tmp_path / "ctrl.py"
    path.write_text("x = payload['some_other_field']\n", encoding="utf-8")
    assert cs.scan_field_whitelist([str(path)])["ok"] is True
    path.write_text("x = payload[cs.BANNED_FIELD]\n", encoding="utf-8")  # 裸名不是读取形态
    assert cs.scan_field_whitelist([str(path)])["ok"] is True


def test_artifact_collection_excludes_w1a_content_assets(repo_root):
    """🔴 冻结集里保留对照字段是**设计**（I-1"只作对照字段"）。把它扫进来 = 这条检查永远红。"""
    paths = [os.path.basename(p) for p in cs._collect_artifacts(repo_root)]
    assert not {"dataset_v1_frozen.json", "gold_query_seed_v1.json",
                "red_team_cases_v1.json", "MANIFEST_v1.json"} & set(paths)
    assert any(p.startswith("results") for p in paths), "门禁输入（results*.json）必须在扫描范围内"


# ============================================================================
# ③ 锚点回归
# ============================================================================
def test_project_anchors_must_all_match_and_official_are_record_only():
    r = cs.test_anchors()
    assert r["ok"] is True
    assert all(p["ok"] for p in r["project"]) and r["n_project_anchors"] == len(r["project"]) == 6
    assert r["official_participates_in_verdict"] is False, "官方锚点当门禁 ⇒ Hard 永远红 ⇒ 有人来放宽阈值"
    assert r["divergence"]["ok"] is True and r["divergence"]["actual_adopted"] == "extra"
    assert r["doc_says_n"] != r["n_project_anchors"], "07 §4.7.2 说 4 条、实落 6 条，差异必须留在产物里"
    assert r["official_mismatch_n"] >= 1, "官方锚点全对上 ⇒ 要么文档被改了，要么锚点被改小了"


# ============================================================================
# 报告器：覆盖率面
# ============================================================================
def _rec(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "case_id": "T-1", "expected_behavior": "execute", "sql_text": "SELECT 1",
        "scored": True, "verdict": {"equivalent": True, "diffs": [], "hash_matches": True},
        "terminal_event": "complete", "outcome": "succeeded", "degradations": [],
        "attribution": {"category": "correct"},
    }
    return {**base, **over}


def test_terminal_reads_terminal_event_not_the_audit_outcome():
    """实测坑：同一条记录 `outcome='failed'` 而 `terminal_event='error'` —— 两个轴。"""
    assert rp._terminal({"terminal_event": "error", "outcome": "failed"}) == "error"
    assert rp._terminal({"outcome": "refused"}) == "refused"
    assert rp._terminal({}) == "?"


@pytest.mark.parametrize(
    ("rec", "want"),
    [
        ({"predicted": {"columns": ["a"], "rows": 3}}, True),
        ({"predicted": {"columns": [], "rows": 0}}, False),
        ({"predicted": {"columns": ["a"], "rows": 0}}, True),          # 0 行也是真跑出来了
        ({"predicted": None}, False),
        ({"predicted": {"columns": ["a"], "rows": 1},
         "verdict": {"diffs": ["列数不同：金标 2 / 预测 0"]}}, True),   # 事实优先于文案
        ({"verdict": {"diffs": []}, "sql_text": "SELECT 1"}, False),   # 无 predicted 区块 ⇒ 不猜
    ],
)
def test_has_result_set_reads_the_table_the_comparator_actually_got(rec, want):
    assert rp._has_result_set(_rec(**rec)) is want


def test_coverage_separates_ran_from_reached_the_executor():
    """🔴 §C.4.1 的分母只含"真拿到结果集"的条目 —— 这条把三个计数钉死。"""
    records = [
        _rec(case_id="A", predicted={"columns": ["x"], "rows": 2}),
        _rec(case_id="B", predicted={"columns": [], "rows": 0},
             verdict={"equivalent": False, "diffs": ["列数不同：金标 1 / 预测 0"], "hash_matches": None}),
        _rec(case_id="C", sql_text=""),
        _rec(case_id="D", expected_behavior="refuse", sql_text="", terminal_event="refuse",
             scored=False, verdict={}, attribution={"category": "correct_refuse"}),
        _rec(case_id="E", terminal_event="clarify", sql_text="",
             attribution={"category": "over_clarification"}),
    ]
    cov = rp.collect_coverage(records)
    assert cov["n_records"] == 5 and cov["n_scored"] == 4
    assert cov["n_execute_cases"] == 4
    assert cov["n_execute_with_sql"] == 2, "只有 A/B 产出 SQL"
    assert cov["n_execute_with_result"] == 1, "只有 A 真拿到非空结果集"
    assert cov["n_false_clarify"] == 1
    assert cov["terminal_distribution"] == {"clarify": 1, "complete": 3, "refuse": 1}
    assert cov["hash_matches_none_n"] == 2


def test_over_refusal_split_keeps_env_caused_refusals_out_of_the_model_s_bill():
    l4 = {"code": "llm_unavailable", "detail": {"stage": "bind.l4"}}
    other = {"code": "embedding_unavailable", "detail": {"stage": "bind.l2"}}
    records = [
        _rec(case_id="M", attribution={"category": "over_refusal"}, degradations=[l4]),
        _rec(case_id="N", attribution={"category": "over_refusal"}, degradations=[other]),
        _rec(case_id="O", attribution={"category": "over_refusal"}, degradations=[{"detail": None}]),
        _rec(case_id="P", attribution={"category": "sql_generation"}, degradations=[l4]),
    ]
    s = rp.split_over_refusal(records)
    assert s["total"] == 3
    assert s["with_bind_l4_degradation"] == ["M"]
    assert s["without"] == ["N", "O"]
    assert "不得" in s["note"]


def test_refusal_and_clarification_inputs_are_absent_not_zero():
    """没有该类题 ⇒ `None` ⇒ `NOT_AVAILABLE`。返回 0 会把"没测"读成"零误拒"。"""
    records = [_rec()]
    assert rp._refusal_counts(records) is None
    assert rp._clarify_counts(records) is None
    r = rp._refusal_counts([_rec(expected_behavior="refuse", terminal_event="refuse", sql_text=""),
                            _rec(expected_behavior="execute", terminal_event="refuse")])
    assert r == {"total": 1, "correct_refused": 1, "answerable_total": 1, "over_refused": 1}


def test_clarify_counts_record_the_denominator_it_used():
    c = rp._clarify_counts([
        _rec(case_id="A", expected_behavior="clarify", terminal_event="clarify",
             verdict={"equivalent": True, "diffs": [], "hash_matches": True}),
        _rec(case_id="B", expected_behavior="clarify", terminal_event="complete"),
        _rec(case_id="C", terminal_event="clarify", sql_text="",
             verdict={"equivalent": False, "diffs": ["预测 0 列"], "hash_matches": None}),
    ])
    assert c == {"requests": 3, "clarify_expected_n": 2, "clarified": 2, "clarify_then_correct": 1,
                 "second_round_loop_available": False}


# ============================================================================
# 报告器：G-1 输入与 τ
# ============================================================================
def test_pytest_summary_without_integration_evidence_stays_partial(tmp_path):
    """日志只有一行计数 ⇒ `integration_ran=False`，且措辞是「无法断定」而非「PG 不通」。

    旧实现把 `integration_ran` 写死成 False 并归因于 `ANALYTICS_DB_URL` 的主机名 `pg`
    解析失败 —— 那是把"我没查这条路"写成"这条路不通"，§17.4 禁止的叙述。
    """
    log = tmp_path / "pytest.log"
    log.write_text("============ 132 passed, 3 warnings in 71.20s ============\n", encoding="utf-8")
    s = rp.parse_pytest_summary(str(log))
    assert s["passed"] == 132 and s["failed"] == 0 and s["errors"] == 0
    assert s["integration_ran"] is False
    assert "无法" in s["integration_note"] and "PARTIAL" in s["integration_note"]
    assert "解析失败" not in s["integration_note"], "不许再替环境宣布 PG 不可达"


def test_pytest_summary_reads_integration_layer_from_log(tmp_path):
    """日志点名 `tests/integration` ⇒ 集成层有读数；全绿的用例不留文件名，所以必须真点名。"""
    log = tmp_path / "full.log"
    log.write_text(
        "........................................................................ [ 78%]\n"
        "FAILED tests/integration/test_rls.py::test_cross_tenant_invisible - AssertionError\n"
        "============= 1 failed, 91 passed, 6 skipped in 88.31s =============\n",
        encoding="utf-8",
    )
    s = rp.parse_pytest_summary(str(log))
    assert s["integration_ran"] is True
    assert s["integration_files_seen"] == ["test_rls.py"]
    assert s["failed_tests"] == ["tests/integration/test_rls.py::test_cross_tenant_invisible"]
    assert (s["passed"], s["failed"], s["skipped"]) == (91, 1, 6)
    assert "集成层已跑" in s["integration_note"]


def test_pytest_summary_none_cases(tmp_path):
    assert rp.parse_pytest_summary(None) is None
    assert rp.parse_pytest_summary(str(tmp_path / "missing.log")) is None
    empty = tmp_path / "empty.log"
    empty.write_text("no counts here\n", encoding="utf-8")
    assert rp.parse_pytest_summary(str(empty)) is None, "没有计数 ⇒ None，而不是 0 passed ⇒ G-1 假绿"


def test_pytest_summary_counts_errors_separately(tmp_path):
    log = tmp_path / "e.log"
    log.write_text("==== 10 passed, 2 failed, 1 error in 3s ====\n", encoding="utf-8")
    s = rp.parse_pytest_summary(str(log))
    assert (s["passed"], s["failed"], s["errors"]) == (10, 2, 1)


def test_tau_facts_report_presence_not_values():
    """🔴 `deploy/.env` 归 W7 且含密钥：这里只允许落"有没有值"（bool），不许落值。"""
    t = rp.tau_facts()
    assert t["changed_this_window"] is False, "τ 若被本窗口改过而没附校准报告 = N-25 违规"
    assert "calibrated_under_eval_env" in t
    assert all(isinstance(v, bool) for v in t["deploy_env_declared"].values()), "τ 面泄露了 env 原文"
    assert all(str(k).startswith("BINDING_TAU") for k in t["deploy_env_declared"]), "只该抓校准字段"
    assert "N-25" in t["consequence"] and "UNVERIFIED" in t["consequence"]


# ============================================================================
# 报告器：零输入装配 + 渲染的"汇总句"红线
# ============================================================================
@pytest.fixture(scope="module")
def zero_input_payload() -> dict:
    """把**全部**输入路径指向不存在的文件 —— 报告必须照样写得出来，且不许宣布通过。"""
    return rp.build_payload(
        results_path="__nope__.json", redteam_path="__nope__.json",
        consistency_path="__nope__.json", pytest_log="__nope__.log",
        integration_log="__nope__.log", metric_probe_path="__nope__.json",
        metric_values_path="__nope__.json", pg_probe_path="__nope__.json",
        loadtest_receipt="__nope__.json", pressure_report="__nope__.md",
    )


def test_missing_artifacts_degrade_to_not_available_not_crash(zero_input_payload):
    p = zero_input_payload
    assert p["meta"]["artifacts_present"] == {
        "results": False, "redteam": False, "consistency": False, "pytest_log": False,
        "metric_probe": False, "metric_values": False, "pg_probe": False,
        "loadtest_receipt": False,
    }
    verdicts = [g["verdict"] for g in p["gates"]]
    assert len(verdicts) == 8 and set(verdicts) == {"NOT_AVAILABLE"}
    assert p["gate_summary"]["all_pass"] is False and p["gate_summary"]["passed"] == []
    assert p["red_team"] is None and p["cross_tenant"] is None and p["consistency_17_6"] is None
    assert p["grid"]["ex"] is None, "无样本 ⇒ EX 必须是 None，不是 0.0（0.0 是能力读数）"


def test_zero_input_report_still_carries_the_gap_table_and_limitations(zero_input_payload):
    """红线：沙箱能力缺口表必须出现在评测报告里，一条输入都没有时也不许缺席。"""
    p = zero_input_payload
    assert p["gap_table"], "缺口表缺席 = §17.4 红线"
    assert all("covered_by_eval" in r for r in p["gap_table"])
    assert all(r["covered_by_eval"] is False for r in p["gap_table"]), (
        "出现 covered_by_eval=True 的行 ⇒ 有人在把沙箱能力说成生产已验证"
    )
    text = "\n".join(p["known_limitations"])
    assert "生产能力已验证" in text and "τ 未校准" in text
    assert "G-8 结构性不可测" in text and "NOT_AVAILABLE" in text


def test_rendered_summary_sentence_only_counts_pass(zero_input_payload):
    md = rp.render_markdown(zero_input_payload)
    assert "总判定：未全部通过" in md and "全部 PASS" not in md
    assert "之外的一律不得进入" in md and "门禁通过" in md
    for gid in ("G-1", "G-8"):
        assert f"| {gid} |" in md


def test_a_single_non_pass_cannot_be_summarised_away(zero_input_payload):
    """把 7 条改成 PASS、留 1 条 UNVERIFIED ⇒ 汇总句必须仍是"未全部通过"并点名它。"""
    p = copy.deepcopy(zero_input_payload)
    for i, gate in enumerate(p["gates"]):
        gate["verdict"] = "PASS" if i else "UNVERIFIED"
    p["gate_summary"] = {
        "all_pass": False,
        "passed": [g["gate_id"] for g in p["gates"][1:]],
        "not_pass": {p["gates"][0]["gate_id"]: "UNVERIFIED"},
        "counts": {"PASS": 7, "FAIL": 0, "UNVERIFIED": 1, "NOT_AVAILABLE": 0, "PARTIAL": 0},
    }
    md = rp.render_markdown(p)
    assert "未全部通过" in md and "PASS 7/8" in md and "UNVERIFIED" in md
    assert not p["gate_summary"]["all_pass"]


def test_all_pass_payload_is_the_only_one_that_says_pass(zero_input_payload):
    p = copy.deepcopy(zero_input_payload)
    for gate in p["gates"]:
        gate["verdict"] = "PASS"
    p["gate_summary"] = {
        "all_pass": True, "passed": [g["gate_id"] for g in p["gates"]], "not_pass": {},
        "counts": {"PASS": 8, "FAIL": 0, "UNVERIFIED": 0, "NOT_AVAILABLE": 0, "PARTIAL": 0},
    }
    assert "总判定：全部 PASS" in rp.render_markdown(p)


def test_known_limitations_names_the_execution_layer_gap():
    """本轮报告里最容易被读成"EX 低=模型差"的一句，必须由覆盖率读数自动生成。"""
    cov = {"n_records": 5, "n_execute_cases": 5, "n_execute_with_sql": 5,
           "n_execute_with_result": 0, "n_false_clarify": 2,
           "terminal_distribution": {"clarify": 2, "error": 3}, "n_scored": 5,
           "hash_matches_none_n": 5}
    text = "\n".join(
        rp._known_limitations(cov, None, None, None, g8_second_round_available=False, pg_txt=PG_TXT)
    )
    assert "执行层端到端未覆盖" in text and "闸门之前" in text
    assert "不等于" in text and "渲染链路正确" in text
    assert "任何百分比都是覆盖率读数，不是能力读数" in text
    assert PG_TXT in text, "PG 面结论必须原样出现在已知限制里"
    assert "G-8 结构性不可测" in text and "没有应澄清题" in text


def test_known_limitations_switches_when_execution_was_covered():
    cov = {"n_records": 6, "n_execute_cases": 6, "n_execute_with_sql": 6,
           "n_execute_with_result": 4, "n_false_clarify": 0, "terminal_distribution": {},
           "n_scored": 6, "hash_matches_none_n": 0}
    text = "\n".join(
        rp._known_limitations(cov, {"total": 66, "not_covered_cases": []}, {}, {},
                              g8_second_round_available=True, pg_txt=PG_TXT)
    )
    assert "执行层端到端未覆盖" not in text
    assert "覆盖不完整" in text and "4 条真拿到结果集" in text
    assert "G-8 结构性不可测" not in text
    assert "G-7（核心指标口径一致性）**未跑**" in text


def test_known_limitations_discloses_c43_rate_and_never_the_coverage_probe():
    """G-7 只吃 `probe_metric_values.json`；把覆盖度探针喂进去会读出假的一致率。"""
    cov = {"n_records": 1, "n_execute_cases": 0, "n_execute_with_sql": 0,
           "n_execute_with_result": 0, "n_false_clarify": 0, "terminal_distribution": {},
           "n_scored": 1, "hash_matches_none_n": 0}
    low = rp._known_limitations(
        cov, None, None, None, g8_second_round_available=True, pg_txt=PG_TXT,
        metric_values={"total": 13, "consistent": 1, "consistent_rate": 0.0769, "unattributed": 0},
    )
    text = "\n".join(low)
    assert "§C.4.3 口径比对" in text and "7.7%" in text and "冻结集 gold 与语义包默认口径" in text
    assert "G-7（核心指标口径一致性）**未跑**" not in text

    ok = rp._known_limitations(
        cov, None, None, None, g8_second_round_available=True, pg_txt=PG_TXT,
        metric_values={"total": 13, "consistent": 13, "consistent_rate": 1.0, "unattributed": 0},
    )
    assert "冻结集 gold 与语义包默认口径" not in "\n".join(ok), "达标时不许留低一致率的归因句"


def test_zero_input_report_has_no_pg_or_c43_readings(zero_input_payload):
    """未探测 ⇒ 这两个区块必须是 `None`，不能是 0 或空表（那会被读成"比对过且全不一致"）。"""
    p = zero_input_payload
    assert p["pg_probe"] is None and p["metric_consistency_c43"] is None
    assert p["metric_coverage"] is None
    text = rp.render_markdown(p)
    assert "未探测" in text, "报告里必须明写 PG 未探测"


def test_replay_batch_still_names_its_recording_provenance(tmp_path):
    """回放轮不许把"已花钱录过匣带"说成"本轮没真打"—— 漏报同样是失真。"""
    f = tmp_path / "results.json"
    f.write_text(json.dumps({
        "config": {"live": False, "mode": "replay",
                   "provenance": "由 20 条真打批次录制（92,642 tokens / ¥0.032804）"},
        "summary": {}, "records": [],
    }), encoding="utf-8")
    p = rp.build_payload(
        results_path=str(f), redteam_path="__nope__.json", consistency_path="__nope__.json",
        pytest_log="__nope__.log", integration_log="__nope__.log",
        metric_probe_path="__nope__.json", metric_values_path="__nope__.json",
        pg_probe_path="__nope__.json",
    )
    row = next(r for r in p["gap_table"] if "LLM" in str(r["capability"]))
    assert "¥0.032804" in row["evidence"], row["evidence"]
    assert "无 live 记录" not in row["evidence"]


def test_pg_statement_three_branches_never_claim_more_than_measured():
    """四档措辞各自不许越界：未探测 ≠ 不可达；可达但空表 ≠ RLS 已验证；有数据 ≠ 有效性已实测。"""
    assert "未探测" in rp.pg_statement(None)
    assert "未探测 ≠ 不可达" in rp.pg_statement(None)

    unreachable = rp.pg_statement({"reachable": False, "pg_fact_rows": 0, "version": None,
                                   "alembic_version": None, "n_app_tables": 0, "n_app_views": 0,
                                   "rls_policies_n": 0, "rls_forced_relations": [],
                                   "app_ro_visible_objects": None, "app_ro_reads_view": None,
                                   "sqlite_fact_rows": 0})
    assert "PG 不可达" in unreachable and "UNVERIFIED" in unreachable

    empty = rp.pg_statement({"reachable": True, "version": "PostgreSQL 16.15 on x86_64",
                             "alembic_version": "0005", "n_app_tables": 24, "n_app_views": 8,
                             "rls_policies_n": 6, "rls_forced_relations": ["order_paid"],
                             "app_ro_visible_objects": 18, "app_ro_reads_view": True,
                             "pg_fact_rows": 0, "sqlite_fact_rows": 2023933})
    assert "结构/权限面已实测" in empty and "仍不可测" in empty
    assert "2,023,933" in empty and "0 行" in empty
    assert "0 行对 0 行" in empty, "必须点破「空对空必然相等」这种假通过"


def _pg_facts_with_data(**over):
    base = {"reachable": True, "version": "PostgreSQL 16.15 on x86_64", "alembic_version": "0005",
            "n_app_tables": 24, "n_app_views": 8, "rls_policies_n": 6,
            "rls_forced_relations": ["order_paid", "traffic_daily"],
            "app_ro_visible_objects": 18, "app_ro_reads_view": 494249,
            "pg_fact_rows": 2023933, "sqlite_fact_rows": 2023933, "rls_partition_ok": False}
    return {**base, **over}


def test_pg_statement_has_data_but_no_effectiveness_evidence():
    """有数据 ≠ 有效性已实测：探针没给 `rls_partition_ok` 时只能说"在位"。"""
    got = rp.pg_statement(_pg_facts_with_data())
    assert "可评估把评测主链路切到 PG" in got
    assert "有效性已实测" not in got.replace("不到「RLS 有效性已实测」", "")
    assert "rls_partition_ok" in got, "要告诉读者缺的是哪一个证据"


def test_pg_statement_effectiveness_measured_still_not_the_app_path():
    """四条负对照齐了才允许说"均已实测"，且必须紧跟着"不等于评测走了 PG"。"""
    got = rp.pg_statement(_pg_facts_with_data(rls_partition_ok=True))
    assert "存在性与有效性均已实测" in got
    assert "不等于" in got and "TEMP VIEW" in got
    assert "PASS" not in got, "措辞里不许混进判定词"


def test_gap_table_rls_follow_up_tracks_the_probe_not_the_prose():
    """§17.4 缺口表 RLS 行的"下一步"必须由探测派生。

    反例就是首轮那份：判定已经改了，缺口表里还写着"业务事实表全空 ⇒ 待 W7 灌数"，
    于是同一份报告里同时存在"200 万行"和"全空"。缺口表读起来像背景，比判定更容易说谎。
    """
    def rls_row(facts):
        rows = rp.gaps_mod.build_gap_table(extra_evidence={}, pg_facts=facts)
        return next(r for r in rows if str(r["capability"]).startswith("RLS"))["follow_up"]

    assert "未探测真 PG" in rls_row(None)
    empty = rls_row(_pg_facts_with_data(pg_fact_rows=0))
    assert "0 行对 0 行" in empty and "补齐条件" in empty
    has_data_no_proof = rls_row(_pg_facts_with_data())
    assert "有效性**仍未实测**" in has_data_no_proof
    proven = rls_row(_pg_facts_with_data(rls_partition_ok=True))
    assert "存在性与有效性均已实测" in proven
    assert "全空" not in proven and "2,023,933" in proven
    assert proven != empty, "事实变了措辞必须变（否则就是写死的散文）"


def test_rls_follow_up_parallel_equality_clause_is_three_state():
    """并行/串行等值对照三态：**没跑 ≠ 跑过且通过**，不等值则连本行读数一起废掉。

    为什么单独钉：W7 报过"并行把 `count(*)` 吃掉一截且不报错"，而 N-07 抓不到这类错
    （策略照样生效、只是数变小）⇒ 判据只能由引用读数的人自带，措辞不能含糊。
    """
    def rls_row(facts):
        rows = rp.gaps_mod.build_gap_table(extra_evidence={}, pg_facts=facts)
        return next(r for r in rows if str(r["capability"]).startswith("RLS"))["follow_up"]

    not_probed = rls_row(_pg_facts_with_data(rls_partition_ok=True))
    assert "未做**并行/串行等值对照" in not_probed and "通过" not in not_probed
    failed = rls_row(_pg_facts_with_data(rls_partition_ok=True, parallel_equality_ok=False))
    assert "不等值" in failed and "不得引用" in failed
    passed = rls_row(_pg_facts_with_data(rls_partition_ok=True, parallel_equality_ok=True))
    assert "等值对照**通过**" in passed
    assert failed != passed != not_probed
    # 同一状态必须也出现在报告正文那句 PG 措辞里（缺口表有、报告没有 = 两处口径不一致）
    assert "未做**并行/串行等值对照" in rp.pg_statement(_pg_facts_with_data(rls_partition_ok=True))
    assert "等值对照**通过**" in rp.pg_statement(
        _pg_facts_with_data(rls_partition_ok=True, parallel_equality_ok=True))
    # 子句不自带句首标点：本轮实测踩过"。。"（主句已以句号结尾时又接一个"。"）
    for text in (not_probed, failed, passed):
        assert "。。" not in text


def test_pg_facts_carries_the_parallel_control_from_the_probe(tmp_path):
    """读端必须把探针的 `parallel_equality_ok` 搬出来 —— 否则措辞派生的是空气。"""
    f = tmp_path / "probe.json"
    f.write_text(json.dumps({"pg": {"reachable": True, "parallel_equality_ok": True},
                             "parity": {}}), encoding="utf-8")
    assert rp.pg_facts(str(f))["parallel_equality_ok"] is True
    g = tmp_path / "probe2.json"
    g.write_text(json.dumps({"pg": {"reachable": True}, "parity": {}}), encoding="utf-8")
    assert rp.pg_facts(str(g))["parallel_equality_ok"] is None


def test_timeout_snapshot_drift_names_the_shape_change():
    """§0 同页写着"本次生成时的 commit"和**跑批当时**的超时快照 ⇒ 两者不一致必须点名。

    真实输入：`eval/results_v1.json` 是 09-18 那批，快照里 15 个节点（`normalize` 2.0s、
    `link` 4.0s）；U-104/U-107 之后当前树只剩 9 个非 LLM 节点。不点名的话读者会拿一张
    已经不存在的表去引用 §5.3 的超时契约。
    """
    import harness as h

    snapshot = rp._load(rp.DEFAULT_RESULTS)["config"]["node_timeouts"]["contract"]
    drift = rp.timeout_snapshot_drift(snapshot)
    assert drift, "跑批快照与当前树明显不同，却报「无漂移」= 这条守卫失效"
    assert "normalize" in drift and "已移出契约表" in drift
    assert "`link` 4.0s→30.0s" in drift, "值变化的节点要带上前后两个数"
    assert rp.timeout_snapshot_drift(dict(h.NODE_TIMEOUT_S)) == "", "一致时无许无病呻吟"
    assert rp.timeout_snapshot_drift(None) == ""


def _minimal_payload() -> dict:
    """`render_markdown` 的 §4 只需要这几个键；其余区块给它空值。"""
    return {
        "meta": {"generated_at": "x", "window": "W6", "git": {}, "run_config": {},
                 "run_frozen_evidence": {}, "frozen_recheck_now": {}, "dataset_version": 1,
                 "n_dataset_cases": 0, "artifacts_present": {}},
        "gates": [], "gate_summary": {"all_pass": False, "passed": [], "not_pass": {},
                                      "counts": {}},
        "grid": {"matrix": [[{"passed": 0, "total": 0, "pass_rate": None}
                             for _ in rp.grid_mod.SEMS] for _ in rp.grid_mod.LEVELS],
                 "scored_total": 0, "scored_passed": 0, "ex": None,
                 "unattributed_share": 0.0},
        "coverage": {"n_records": 0, "n_scored": 0, "n_execute_cases": 0,
                     "n_execute_with_sql": 0, "n_execute_with_result": 0, "n_false_clarify": 0,
                     "terminal_distribution": {}, "hash_matches_none_n": 0},
        "over_refusal_split": {"total": 0, "with_bind_l4_degradation": [], "without": [],
                               "note": ""},
        "red_team": None, "cross_tenant": None,
        "consistency_17_6": None, "metric_consistency_c43": None, "metric_coverage": None,
        "pg_probe": None, "gap_table": [], "reproduce": [],
        "tau": {"BINDING_TAU": 0.2, "calibrated_under_eval_env": False,
                "deploy_env_declared": {}, "changed_this_window": False, "consequence": "x"},
        "known_limitations": [],
    }


def test_split_attributions_keeps_non_failures_out_of_the_failure_table():
    """`?` 桶事故的回归测试：交互层判对与 unscored **不是**失败。

    旧实现把 `category or "?"` 塞进同一张表 ⇒ 报告里出现 `? | 7`，读起来像
    "7 条无法归因"，而实测那 7 条是 3 正确拒答 + 3 正确澄清 + 1 infra_error。
    """
    def _r(cid, expected, terminal, *, category=None, scored=True, equivalent=None):
        rec: dict[str, Any] = {
            "case_id": cid, "expected_behavior": expected, "terminal_event": terminal,
            "scored": scored,
        }
        if equivalent is not None:
            rec["verdict"] = {"equivalent": equivalent}
        if category:
            rec["attribution"] = {"category": category}
        return rec

    sp = rp.split_attributions([
        _r("A", "refuse", "refuse"),                              # 判对：不是失败
        _r("B", "clarify", "clarify"),                            # 判对：不是失败
        _r("C", "execute", "error", scored=False),                # 未进判定
        _r("D", "execute", "complete", category="time_semantics", equivalent=False),
        _r("E", "execute", "complete", equivalent=False),         # 失败但没归因
        _r("F", "execute", "complete", equivalent=True),          # 等价 ⇒ 不是失败
    ])
    assert sp["distribution"] == {"time_semantics": 1, "unattributed": 1}
    assert sp["interaction_correct"] == ["A", "B"]
    assert sp["unscored"] == ["C"]
    assert sp["failure_without_attribution"] == ["E"]
    assert sp["equivalent_so_not_failure"] == ["F"]
    assert "?" not in sp["distribution"], "`?` 是野词：它把非失败项混进了 §C.7 分母"
    md = rp.render_markdown({**_minimal_payload(), "attribution_distribution": sp["distribution"],
                             "attribution_split": sp, "attribution_extra_categories": []})
    assert "上表**只含失败**" in md and "2 条「交互层判对」" in md


def test_redteam_digest_caps_the_layer_ordering_sample_and_keeps_g3_keys():
    rt = {
        "total": 66, "leaked": 0, "expect_block": 50, "checked": 48, "n_cases_clean": 40,
        "assertion_counts": {"PASS": 100, "FAIL": 10, "NOT_CHECKED": 20},
        "layer_ordering": [{"case_id": f"RT-{i}"} for i in range(20)],
        "not_covered_cases": [{"case_id": "RT-COST-001"}],
    }
    d = rp._redteam_digest(rt)
    assert (d["total"], d["leaked"], d["expect_block"], d["checked"]) == (66, 0, 50, 48)
    assert len(d["layer_ordering_sample"]) == 3
    assert d["failures_by_class"] is None and d["gate2_visible_raise"] is None, "缺键不许编默认值"


def test_git_rev_never_fabricates_a_commit(zero_input_payload):
    """报告缺版本锚点，好过带着一个错误的 commit 让人去复现错误的树。"""
    g = zero_input_payload["meta"]["git"]
    assert set(g) <= {"rev", "dirty", "error"}
    if g.get("rev") is None:
        assert "error" in g


def test_reproduce_commands_are_runnable_paths(zero_input_payload):
    """复现清单里写错的脚本名 = 报告不可复现。"""
    cmds = zero_input_payload["reproduce"]
    assert cmds, "没有复现命令的报告无法复核"
    for cmd in cmds:
        assert "PYTHONIOENCODING=utf-8" in cmd, cmd
        assert ".venv/Scripts/python.exe" in cmd, cmd
        for token in cmd.split():
            if token.endswith(".py"):
                assert os.path.exists(os.path.join(rp._bootstrap.ROOT, token)), (
                    f"复现清单指向不存在的文件：{token}"
                )
    joined = "\n".join(cmds)
    assert "probe_metric_values.py" in joined, "G-7 的输入必须在复现清单里"
    assert "_probe_pg_real.py" in joined, "PG 结论的来源必须可复跑"


def test_metric_values_digest_is_none_safe_and_attributive():
    assert rp._metric_values_digest(None) is None
    d = rp._metric_values_digest({
        "total": 3, "consistent": 1, "consistent_rate": 1 / 3, "unattributed": 0,
        "threshold_rel_error": 1e-3, "metrics_covered": ["gmv"],
        "comparison_basis": "语义包 vs 冻结集 gold", "excluded": [{"case_id": "X"}],
        "rows": [
            {"case_id": "A", "metric": "gmv", "consistent": True, "rel_error": 0.0,
             "attribution": {"missing_predicates": ["应记在差异行"]}},
            {"case_id": "B", "metric": "gmv", "consistent": False, "rel_error": 0.055,
             "attribution": {"missing_predicates": ["pay_status = 'paid'"],
                             "explained_by_predicate": "is_test_order = false"}},
            {"case_id": "C", "metric": "gmv", "consistent": False, "rel_error": None},
        ],
    })
    assert d["n_excluded"] == 1 and d["total"] == 3
    gmv = d["per_metric"]["gmv"]
    assert gmv["n"] == 3 and gmv["consistent"] == 1
    assert gmv["max_rel_error"] == 0.055, "None 参与 max() 会在 Windows 上抛 TypeError"
    assert gmv["predicates_behind_differences"] == ["pay_status = 'paid'"], (
        "一致行的 attribution 不许混进差异归因（那是空集的另一半来源）"
    )
    assert [e["case_id"] for e in d["examples"]] == ["B", "C"], "只列不一致行"


def test_metric_coverage_digest_is_none_safe():
    assert rp._metric_coverage_digest(None) is None
    d = rp._metric_coverage_digest({"n_cases": 40, "n_question_hits_metric_term": 12,
                                    "n_execute_agg_without_metric_term": 9,
                                    "execute_miss_share": 0.225, "active_metrics": ["gmv"]})
    assert d["execute_miss_share"] == 0.225 and d["active_metrics"] == ["gmv"]


# ==== W7 压测回执 → G-6 输入（读不到就 None，绝不造数）==================

def _receipt(tmp_path, scenarios, schema=rp.LOADTEST_SCHEMA):
    p = tmp_path / "receipt.json"
    p.write_text(json.dumps({"schema": schema, "started_at": "2026-09-18T10:00:00+00:00",
                             "scenarios": scenarios}, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_loadtest_pressure_takes_the_worst_scenario_p95(tmp_path):
    got = rp.loadtest_pressure(_receipt(tmp_path, [
        {"scenario": "steady", "latency_ms": {"p95": 4200.0}},
        {"scenario": "burst", "latency_ms": {"p95": 9100.0}},
    ]))
    assert got["p95_total_ms"] == 9100.0, "取平均/只取 steady 会让 burst 的劣迹隐身"
    assert got["as_of"] == "2026-09-18T10:00:00+00:00" and got["caveat"] is None


def test_loadtest_pressure_propagates_the_async_degraded_caveat(tmp_path):
    got = rp.loadtest_pressure(_receipt(tmp_path, [
        {"scenario": "steady", "latency_ms": {"p95": 4200.0}, "g6_caveat": "含 async_degraded 样本"},
    ]))
    assert got["caveat"] == "含 async_degraded 样本", "caveat 丢了 ⇒ gates 会把截断读数判成达标"


def test_loadtest_pressure_transports_the_u106_scope_fields(tmp_path):
    """W7 的 U-106 把 P95 的分母换成准入样本并单列 429 ⇒ 读端必须把口径一起搬走。

    只搬数值不搬口径 = 读端自己把"端到端 P95"这个词说错了，下游无从纠错。
    """
    got = rp.loadtest_pressure(_receipt(tmp_path, [
        {"scenario": "steady", "latency_ms": {"p95": 4200.0}, "p95_scope": "admitted_http_2xx",
         "admission": {"admitted": 8, "rejected_429": 2}, "rejection_headers": {"429": {"retry-after": 30}},
         "latency_ms_all_ms": {"p95": 6900.0}, "terminal_provenance": {"intent": 8}},
    ]))
    assert got["p95_total_ms"] == 4200.0, "判定用的仍是 schema 里定义的那一个 p95"
    assert got["p95_scope"] == "admitted_http_2xx"
    assert got["p95_all_requests_ms"] == 6900.0
    assert got["admission"] == [{"admitted": 8, "rejected_429": 2}]


def test_loadtest_pressure_ignores_unknown_keys_and_still_matches_schema_verbatim(tmp_path):
    """W7 刻意不升 schema 版本号 ⇒ 我方**不得**加未知键校验，否则接口当场断。

    这条测试钉的是"读端的宽容度"本身：将来有人想'顺手严格一点'，这里先红。
    """
    path = _receipt(tmp_path, [
        {"scenario": "steady", "latency_ms": {"p95": 4200.0}, "brand_new_w7_field": {"x": 1},
         "another_unknown": [1, 2, 3]},
    ])
    got = rp.loadtest_pressure(path)
    assert got is not None and got["p95_total_ms"] == 4200.0
    assert got["p95_scope"] is None and got["p95_all_requests_ms"] is None
    assert got["admission"] == [], "缺字段要落成空/None，不能凭空造一个数"
    # 反面对照：版本号逐字比对这条**不能**被放宽成前缀匹配。
    assert rp.loadtest_pressure(_receipt(tmp_path, [{"latency_ms": {"p95": 1.0}}],
                                         schema="w7.loadtest.receipt/2")) is None


@pytest.mark.parametrize("scenarios", [
    [],                     # 四场景一个没跑（W7 本轮的真实状态）
    [{"scenario": "steady", "latency_ms": {"p95": None}}],   # 跑了但零样本
])
def test_loadtest_pressure_refuses_to_invent_a_p95(tmp_path, scenarios):
    assert rp.loadtest_pressure(_receipt(tmp_path, scenarios)) is None


def test_loadtest_pressure_ignores_foreign_schema_and_absent_files(tmp_path):
    """schema 不符 = 不是那份契约，宁可判「没输入」也不按猜测解析别人的字段。"""
    assert rp.loadtest_pressure(
        _receipt(tmp_path, [{"latency_ms": {"p95": 1.0}}], schema="someone.else/1")) is None
    assert rp.loadtest_pressure(str(tmp_path / "nope.json")) is None


def test_build_payload_routes_the_receipt_into_g6(tmp_path):
    """装配半边也要钉住：回执一落地，门禁表里就是实测 P95，不用再改任何措辞。"""
    p = rp.build_payload(
        results_path="__nope__.json", redteam_path="__nope__.json",
        consistency_path="__nope__.json", pytest_log="__nope__.log",
        integration_log="__nope__.log", metric_probe_path="__nope__.json",
        metric_values_path="__nope__.json", pg_probe_path="__nope__.json",
        loadtest_receipt=_receipt(tmp_path, [{"scenario": "steady", "latency_ms": {"p95": 4200.0}}]),
        pressure_report="__nope__.md",
    )
    g6 = next(x for x in p["gates"] if x["gate_id"] == "G-6")
    assert g6["verdict"] == "PASS"
    assert g6["measured"] == "P95 = 4200ms，分母 = 口径未标注 = U-106 之前的回执", \
        "U-106 之后读数必须显名分母：只写数值会让准入 P95 被读成端到端 P95"
    assert p["meta"]["artifacts_present"]["loadtest_receipt"] is True
    assert p["gate_summary"]["all_pass"] is False, "一条 PASS 掩不掉其余 NOT_AVAILABLE"
