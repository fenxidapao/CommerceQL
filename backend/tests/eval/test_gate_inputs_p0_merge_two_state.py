"""T-32（QA 第 7 轮顺带件）：G-1 合并支失明的修法 ＋ **两态反证**。

缺陷形状（QA 注入夹具实测坐实；本文件用等价件重建那一对日志，零额度、零写库）
--------------------------------------------------------------------------
`gate_inputs()` 旧写法 `{**离线, **集成}` 把 `failed` / `errors` **一并覆盖**成集成层那两个数，
只给 `passed` 留了两档 ⇒ 「离线面有红、集成面干净」时 `red_split()` 读到 0、**G-1 判 PASS**。
它防的正是「P0 面有红却写 PASS」⇒ 修完之后原判据防的东西一条都不能少（下面逐臂钉住）。

三条纪律写在这里
--------------------------------------------------------------------------
1. **夹具自含、绝不在共享树上留**：所有日志只写进 `tmp_path`（pytest 临时目录在仓库根之外，
   由 `test_tmp_fixtures_never_land_on_the_shared_tree` 当场断言），本件不往仓库里落任何文件。
2. **单变量对照**：净态那一臂除两份日志换成"本轮真实形状"外，其余输入全走默认产物，
   再与**已入库报告**逐格对表 ⇒ 「修合并支没动其它七格」是被测出来的，不是叙述出来的。
3. **相加的前提要能被证伪**：整树 `-v` 那种日志（离线面自己点了集成文件名）不得再相加，
   否则同一条红数两遍 ⇒ 有一臂专门测这个守卫。
"""

from __future__ import annotations

import json
import os

import gates as gt
import pytest
import reporter as rp

# ── 日志形状（summary 行必须落在**末 4000 字符**内；点名列取全文 —— 尺 = parse_pytest_summary）
_OFFLINE_DIRTY = (
    "tests/unit/test_startup_assertions.py .F\n"
    "FAILED tests/unit/test_startup_assertions.py::test_x - AssertionError: boom\n"
    "========================= 1 failed, 2347 passed in 90.10s =========================\n"
)
_OFFLINE_CLEAN = (
    "tests/unit/test_startup_assertions.py " + ("." * 60) + "\n"
    "============================== 2347 passed in 90.10s ==============================\n"
)
_INTEGRATION_CLEAN = (
    "tests/integration/test_rls_tenant_isolation.py ............\n"
    "tests/integration/test_audit_append_only.py ............\n"
    "============================== 107 passed in 27.44s ===============================\n"
)
_INTEGRATION_DIRTY = (
    "tests/integration/test_rls_tenant_isolation.py .E\n"
    "ERROR tests/integration/test_audit_append_only.py - RuntimeError: 夹具起不来\n"
    "======================== 106 passed, 1 error in 27.44s ============================\n"
)
#: 整树 `-v`：离线面日志**自己**就点了集成层文件名 ⇒ `integration_ran=True` ⇒ 不进合并支。
_WHOLE_TREE_VERBOSE = (
    "tests/integration/test_rls_tenant_isolation.py ....\n"
    "tests/unit/test_startup_assertions.py .F\n"
    "FAILED tests/unit/test_startup_assertions.py::test_x - AssertionError: boom\n"
    "========================= 1 failed, 2453 passed in 120.00s =========================\n"
)


@pytest.fixture
def log(tmp_path):
    """把一段日志落成临时文件并返回路径（自含；不落仓库、不落库）。"""

    def _write(name: str, body: str) -> str:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return str(path)

    return _write


def test_tmp_fixtures_never_land_on_the_shared_tree(tmp_path):
    """守「绝不在共享树上留」：临时目录必须在仓库根之外（否则夹具会污染别人的取证面）。"""
    root = os.path.abspath(rp._bootstrap.ROOT)
    assert not os.path.abspath(str(tmp_path)).startswith(root + os.sep), tmp_path


# ── 1. 修复前对照（单变量：同一对日志，只换合并式）───────────────────────────
def test_old_cover_policy_would_have_reported_zero_red(log):
    offline = rp.parse_pytest_summary(log("off.log", _OFFLINE_DIRTY))
    integ = rp.parse_pytest_summary(log("int.log", _INTEGRATION_CLEAN))
    assert offline and offline["failed"] == 1 and offline["errors"] == 0
    assert integ and integ["failed"] == 0 and integ["errors"] == 0

    old_style = {**offline, **{k: v for k, v in integ.items() if k != "source_log"}}
    assert gt.red_split(old_style)["red_total"] == 0                       # ← 失明：离线那条红被覆盖掉
    assert gt.red_split(rp.merge_p0_logs(offline, integ))["red_total"] == 1  # ← 修法后


# ── 2. 两两形状：相加，不是取 max（max 会把"两面各一条红"读成一条）────────────
@pytest.mark.parametrize(
    ("offline_body", "integration_body", "want_failed", "want_errors"),
    [
        (_OFFLINE_DIRTY, _INTEGRATION_CLEAN, 1, 0),
        (_OFFLINE_CLEAN, _INTEGRATION_DIRTY, 0, 1),
        (_OFFLINE_DIRTY, _INTEGRATION_DIRTY, 1, 1),
    ],
)
def test_merge_sums_both_faces_instead_of_overwriting(
        log, offline_body, integration_body, want_failed, want_errors):
    offline = rp.parse_pytest_summary(log("off.log", offline_body))
    integ = rp.parse_pytest_summary(log("int.log", integration_body))
    merged = rp.merge_p0_logs(offline, integ)
    assert merged["failed"] == offline["failed"] + integ["failed"] == want_failed
    assert merged["errors"] == offline["errors"] + integ["errors"] == want_errors
    #: 每一列两档都要留着 —— 引用时能点名「红在哪一面」（旧写法只给 `passed` 留档）。
    assert merged["failed_offline"] == offline["failed"]
    assert merged["failed_integration"] == integ["failed"]
    assert merged["errors_offline"] == offline["errors"]
    assert merged["errors_integration"] == integ["errors"]
    assert merged["passed"] == merged["passed_offline"] + merged["passed_integration"]
    assert merged["integration_ran"] is True
    assert merged["merge_policy"]


def test_merge_unions_the_named_lists_so_notes_still_name_every_red(log):
    offline = rp.parse_pytest_summary(log("off.log", _OFFLINE_DIRTY))
    integ = rp.parse_pytest_summary(log("int.log", _INTEGRATION_DIRTY))
    merged = rp.merge_p0_logs(offline, integ)
    assert "tests/unit/test_startup_assertions.py::test_x" in merged["failed_tests"]
    assert "tests/integration/test_audit_append_only.py" in merged["error_tests"]
    assert len(merged["integration_files_seen"]) >= len(integ["integration_files_seen"])


# ── 3. 两态：脏态必须翻 FAIL（且红要能被点名），净态必须 PASS ─────────────────
def test_dirty_pair_flips_g1_to_fail_and_names_the_red(log):
    gate = rp.recompute_gate("G-1",
                             pytest_log=log("off.log", _OFFLINE_DIRTY),
                             integration_log=log("int.log", _INTEGRATION_CLEAN))
    assert gate["verdict"] == "FAIL", gate["verdict"]
    assert gate["red_split"]["red_total"] == 1
    assert any("test_startup_assertions.py::test_x" in c for c in gate["caveats"]), gate["caveats"]


def test_clean_pair_still_passes(log):
    gate = rp.recompute_gate("G-1",
                             pytest_log=log("off.log", _OFFLINE_CLEAN),
                             integration_log=log("int.log", _INTEGRATION_CLEAN))
    assert gate["verdict"] == "PASS", gate["measured"]
    assert gate["red_split"]["red_total"] == 0


# ── 4. 净态那一臂：八格逐格与**已入库报告**对表（改合并支不许动别的格）──────────
def test_all_eight_verdicts_equal_the_committed_report_on_clean_pair(log):
    report_path = os.path.join(rp.W6_DIR, "eval_metrics.json")
    if not os.path.isfile(report_path):
        pytest.skip("报告产物不在位 ⇒ 无历史读数可对表（是产物缺失，不是判据缺失）")
    with open(report_path, encoding="utf-8") as fh:
        committed = json.load(fh)
    want = {g["gate_id"]: g["verdict"] for g in committed["gates"]}
    assert len(want) == 8, sorted(want)

    gi = rp.gate_inputs(pytest_log=log("off.log", _OFFLINE_CLEAN),
                        integration_log=log("int.log", _INTEGRATION_CLEAN))
    pr = rp.DEFAULT_PRESSURE_REPORT
    gate_list = gt.evaluate_gates(
        **gi,
        pressure_report=(os.path.relpath(pr, rp._bootstrap.ROOT) if pr and os.path.isfile(pr) else None),
    )
    got = {g.gate_id: g.verdict for g in gate_list}
    assert got == want, {k: (want[k], got[k]) for k in want if want[k] != got[k]}


# ── 5. 守卫：离线日志自己点过集成层 ⇒ 不相加（否则同一条红数两遍）───────────────
def test_no_double_count_when_offline_log_already_covers_integration(log):
    whole = log("whole.log", _WHOLE_TREE_VERBOSE)
    integ = log("int.log", _INTEGRATION_CLEAN)
    gate = rp.recompute_gate("G-1", pytest_log=whole, integration_log=integ)
    p0 = rp.gate_inputs(pytest_log=whole, integration_log=integ)["p0_tests"]
    assert p0["integration_ran"] is True
    assert p0["passed"] == 2453                       # 整树那一份的数，没再加集成的 107
    assert "passed_integration" not in p0             # ⇒ 也没走合并支（两档键是合并支的产物）
    assert p0["failed"] == 1 and p0["errors"] == 0
    assert gate["verdict"] == "FAIL"


# ── 6. ③ 取证件：对得上就静默、对不上必须报出来（不许静默成第二份过期真相）─────
def test_p0_summary_crosscheck_is_loud_when_it_disagrees(log, tmp_path):
    off = log("off.log", _OFFLINE_CLEAN)
    integ = log("int.log", _INTEGRATION_CLEAN)

    summary = rp.build_p0_summary(off, integ)
    good = tmp_path / "summary_good.json"
    with open(good, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False)
    ev = rp.p0_summary_evidence(rp.parse_pytest_summary(off), rp.parse_pytest_summary(integ), str(good))
    assert ev["present"] and ev["loaded"] and ev["mismatch"] == [], ev

    drift = json.loads(json.dumps(summary))
    drift["offline"]["passed"] = int(summary["offline"]["passed"]) + 6      # 日志重跑过、取证件旧了
    bad = tmp_path / "summary_bad.json"
    with open(bad, "w", encoding="utf-8") as fh:
        json.dump(drift, fh, ensure_ascii=False)
    ev_bad = rp.p0_summary_evidence(rp.parse_pytest_summary(off), rp.parse_pytest_summary(integ), str(bad))
    assert any("offline.passed" in m for m in ev_bad["mismatch"]), ev_bad


def test_p0_summary_declares_the_keys_that_raise_the_evidence_level(log, tmp_path):
    """`artifact_evidence()` 只认 `_AT_KEYS` / `_REV_KEYS` 里那两个名字 ⇒ 键名写错 = 等级不升。"""
    off = log("off.log", _OFFLINE_CLEAN)
    integ = log("int.log", _INTEGRATION_CLEAN)
    path = tmp_path / "summary.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rp.build_p0_summary(off, integ), fh, ensure_ascii=False)
    row = rp.artifact_evidence(str(path), rp._tracked_in_git([str(path)]))
    assert row["self_reported_at"] is not None, row
    assert row["self_reported_rev"] is not None, row
    assert row["basis"] == "self_reported", row
