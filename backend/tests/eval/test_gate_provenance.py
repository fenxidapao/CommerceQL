"""`eval/reporter.py` 的**门禁取证面**（QA 验收窗第一轮 ④ · T-06）的单元测试。

归属窗口：W6。T-06 要的是"每格四件：产物 + 生成时刻 + 生成用 HEAD + 零额度复算命令"，
而它唯一能被证伪的形式是：**别人照命令跑一遍，能拿到与报告相同的判定**。
所以这里既有纯函数级断言，也有一条真的把 `-c` 载荷跑一遍的子进程测试。

三处必须守住的坑（都是本轮实测撞出来的，不是风格）
--------------------------------------------------------------------------
1. 取证路径的**原点**：`git ls-files` 在仓库根跑，路径就必须仓库相对 ——
   用 `backend/` 相对会得到"入 git=否"的**假阴性**（文件其实入库）；
2. 判定输入只能有**一个装配口**（`gate_inputs()`）⇒ 复算命令与报告共用它；
3. 表格单元里的裸竖线会把 GFM 表劈列 ⇒ `_md_table` 必须转义。
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys

import gates as gt
import pytest
import reporter as rp

_FAKE_LOG = (
    "tests/integration/test_x.py .\n"
    "ERROR tests/integration/test_y.py - RuntimeError: 环境变量 X 未设置\n"
    "5 passed, 1 error in 1.00s\n"
)


# ==== 1. 路径原点：仓库相对，且"入 git"不假阴性 =========================
def test_evidence_rel_is_repo_relative_not_backend_relative():
    abs_real = os.path.join(rp._bootstrap.ROOT, "backend", "reports", "w6", "redteam_results.json")
    rel = rp._evidence_rel(abs_real)
    assert rel == "backend/reports/w6/redteam_results.json", rel


def test_tracked_in_git_does_not_report_false_negative_on_committed_artifact():
    """🔴 本轮真实撞到的：尺子用 `backend/` 相对喂给 `git -C <仓库根> ls-files`
    ⇒ 匹配不到 ⇒ "入 git=否"成了**假阴性**，而文件其实是入库的。

    一个假阴性的"没入库"会让人把已入库的产物写成"只能本机取证"，下一轮就有人重做已经存在的东西。
    """
    abs_real = os.path.join(rp._bootstrap.ROOT, "backend", "reports", "w6", "redteam_results.json")
    assert rp._tracked_in_git([abs_real]) == {"backend/reports/w6/redteam_results.json"}


def test_evidence_rel_resolves_against_cwd_then_canonicalises_to_repo_root():
    """同一条路径写法，在 `backend/` 里跑与在仓库根跑**不是同一个文件**。

    所以取证面不许保留"操作者当时怎么敲的"，必须归一成仓库相对 ——
    本轮实测：`--pytest-log reports/w6/x.log` 在 cwd=`backend/` 下跑，
    判定读到了文件、取证面按仓库根去拼 ⇒ 报告里同时出现"FAIL(红 8 条)"和"日志不在位"。
    """
    here = os.getcwd()
    try:
        os.chdir(os.path.join(rp._bootstrap.ROOT, "backend"))
        assert rp._evidence_rel("reports/w6/redteam_results.json") == \
            "backend/reports/w6/redteam_results.json"
        # 同一个字符串、换到仓库根去解释 ⇒ 指向另一个（不存在的）文件。
        # 这正是取证面必须在**报告生成时**按当时的 cwd 归一、而不是事后猜的原因。
        os.chdir(rp._bootstrap.ROOT)
        assert rp._evidence_rel("reports/w6/redteam_results.json") == "reports/w6/redteam_results.json"
        assert rp.artifact_evidence("reports/w6/redteam_results.json", set())["present"] is False
    finally:
        os.chdir(here)


def test_evidence_rel_returns_none_for_missing_path():
    assert rp._evidence_rel(None) is None


# ==== 2. 单个产物的取证四件：四态齐全，认不到键就退回 mtime =============
def test_artifact_evidence_reads_self_declared_timestamp_and_rev(tmp_path):
    f = tmp_path / "probe.json"
    f.write_text(json.dumps({"generated_at": "2026-10-02T00:00:00Z", "git_rev": "abcdef1"}),
                 encoding="utf-8")
    ev = rp.artifact_evidence(str(f), tracked=set())
    assert ev["basis"] == "self_reported"
    assert ev["self_reported_at"] == "2026-10-02T00:00:00Z" and ev["self_reported_at_key"] == "generated_at"
    assert ev["self_reported_rev"] == "abcdef1"
    #: 🔴 `tmp_path` 在仓库外 ⇒ 取证面**不许**写它的绝对路径（报告是共享产物，
    #: 绝对路径里含用户名/盘符），`path` 归一不到就写 `None`、`tracked_in_git` 只能是"未知"，
    #: 而不是"否"（"否"会被读成"这产物没入库"）。
    assert ev["path"] is None and ev["tracked_in_git"] is None
    assert "仓库外" in ev["display"] and "AppData" not in ev["display"]


def test_artifact_evidence_falls_back_to_mtime_only(tmp_path):
    f = tmp_path / "probe.json"
    f.write_text(json.dumps({"ok": True}), encoding="utf-8")
    ev = rp.artifact_evidence(str(f), tracked=None)
    assert ev["basis"] == "mtime_only" and ev["self_reported_at"] is None
    assert ev["mtime_utc"] and ev["tracked_in_git"] is None, "取不到 git 状态要写未知，不是「没入库」"


def test_artifact_evidence_on_text_log_does_not_crash(tmp_path):
    """🔴 G-1 的产物是 pytest **文本**日志 ⇒ 解析 JSON 声明键必然失败。

    只记异常**类型名**、不记 message：JSON 报错会把文件内容原样带出来，
    而产物目录里躺着 DSN 与回执（W7 规程：异常出口不许带回原文）。
    """
    f = tmp_path / "suite.log"
    f.write_text(_FAKE_LOG, encoding="utf-8")
    ev = rp.artifact_evidence(str(f), tracked=set())
    assert ev["basis"] == "mtime_only"
    assert ev["parseable_as_json"] is False
    assert ev["parse_error"] in (None, "JSONDecodeError")
    assert "RuntimeError" not in json.dumps(ev, ensure_ascii=False), "产物内容不许进取证行"


def test_artifact_evidence_absent_and_no_path_are_different_words(tmp_path):
    missing = rp.artifact_evidence(str(tmp_path / "nope.json"), tracked=set())
    assert missing["basis"] == "absent" and missing["present"] is False
    nopath = rp.artifact_evidence(None, tracked=set())
    assert nopath["basis"] == "no_path" and nopath["path"] is None


# ==== 3. 复算口与报告同源：装配只许一份 ==================================
def test_gate_inputs_keys_match_evaluate_gates_parameters():
    """🔴 `gate_inputs()` 的键必须正好是判定器的形参（除 `pressure_report` 那个在位证据）。

    漂移的表现很难看：报告里 G-7 是 FAIL，别人照命令复算出来是 NOT_AVAILABLE，
    两边都"没错"，因为装配的输入不一样。这条断言把"同一个口"钉死。
    """
    params = set(inspect.signature(gt.evaluate_gates).parameters)
    produced = set(rp.gate_inputs())
    assert produced == params - {"pressure_report"}, (produced ^ params)


def test_recompute_gate_returns_the_same_verdict_as_evaluate_gates(tmp_path):
    log = tmp_path / "_fake_suite.log"
    log.write_text(_FAKE_LOG, encoding="utf-8")
    kwargs = {"pytest_log": str(log), "integration_log": None}
    one = rp.recompute_gate("G-1", **kwargs)
    allg = {g.gate_id: g for g in gt.evaluate_gates(**rp.gate_inputs(**kwargs))}
    assert one["verdict"] == allg["G-1"].verdict == "FAIL"
    assert json.loads(json.dumps(one))["red_split"]["environment_errors"] == 1
    assert "环境未备 1" in one["measured"]


def test_recompute_gate_rejects_an_unknown_gate_id(tmp_path):
    with pytest.raises(KeyError):
        rp.recompute_gate("G-9")


def test_provenance_command_body_actually_runs():
    """别人照抄取证表里的命令 ⇒ 必须真能跑出同一格。这条是本节的**唯一验收**。

    🔴 故意不在 `tmp_path` 里造日志：那条路径在仓库外 ⇒ 归一化会给出 `path=None`，
    命令里就变成 `pytest_log=None`，跑出来的其实是**默认路径**那一格 —— 测试会绿，
    但它绿的是"另一件事"。这里把假日志放进仓库内（`*.log` 已被 `.gitignore` 全局忽略，
    不污染工作区），走 `artifact_evidence → recompute_command → 子进程`这一整条真实链路。
    """
    fake = os.path.join(rp._bootstrap.ROOT, "backend", "reports", "w6", "_test_recompute_fake.log")
    with open(fake, "w", encoding="utf-8", newline="") as fh:
        fh.write(_FAKE_LOG)
    try:
        arts = []
        for arg, p in (("pytest_log", fake), ("integration_log", None)):
            ev = rp.artifact_evidence(p, rp._tracked_in_git([fake]))
            ev["arg"] = arg
            arts.append(ev)
        cmd = rp.recompute_command("G-1", arts)
        assert "pytest_log='backend/reports/w6/_test_recompute_fake.log'" in cmd, cmd
        body = re.search(r'-c "(.+)"$', cmd).group(1)
        assert "|" not in body, "复算命令进 GFM 表格 ⇒ 单元里不许有裸竖线"
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = subprocess.run([sys.executable, "-c", body], cwd=rp._bootstrap.ROOT,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=300, env=env)
        assert out.returncode == 0, out.stderr[-400:]
        assert "'FAIL'" in out.stdout and "环境未备 1" in out.stdout, out.stdout[-400:]
    finally:
        os.remove(fake)


# ==== 4. 取证表本体：八格都在场、原因引用而非重写、欠件计数自洽 ==========
def test_provenance_has_one_row_per_gate_with_paths_and_commands():
    gate_list = gt.evaluate_gates()                       # 全 NOT_AVAILABLE 的一轮
    prov = rp._gate_provenance(gate_list, {"results_path": rp.DEFAULT_RESULTS,
                                           "pytest_log": rp.DEFAULT_PYTEST_LOG,
                                           "integration_log": rp.DEFAULT_INTEGRATION_LOG,
                                           "redteam_path": rp.DEFAULT_REDPATH,
                                           "pg_probe_path": rp.DEFAULT_PG_PROBE,
                                           "metric_values_path": rp.DEFAULT_METRIC_VALUES,
                                           "loadtest_receipt": rp.DEFAULT_LOADTEST_RECEIPT},
                               report_git={"rev": "testrev", "dirty": False})
    assert [r["gate_id"] for r in prov["rows"]] == [f"G-{i}" for i in range(1, 9)]
    for r in prov["rows"]:
        assert r["recompute"] and f"recompute_gate('{r['gate_id']}', " in r["recompute"]
        assert r["missing_input_reason"], f"{r['gate_id']} 判 NOT_AVAILABLE 却没写缺输入原因"
    # 「原因」引用 gates 的 caveat，不在取证表里重写一遍（两处措辞迟早分叉）
    by_id = {g.gate_id: g for g in gate_list}
    for r in prov["rows"]:
        assert r["missing_input_reason"] in (by_id[r["gate_id"]].caveats or ())


def test_provenance_gap_counts_are_recomputed_not_written(tmp_path):
    gate_list = gt.evaluate_gates(p0_tests={"failed": 0, "errors": 3, "passed": 10,
                                            "integration_ran": True,
                                            "error_tests": ["tests/integration/test_a.py"]})
    missing = str(tmp_path / "gone.json")
    prov = rp._gate_provenance(gate_list, {"pytest_log": missing, "integration_log": None},
                               report_git={"rev": None, "dirty": None})
    g1 = next(r for r in prov["rows"] if r["gate_id"] == "G-1")
    assert [a["basis"] for a in g1["artifacts"]] == ["absent", "no_path"]
    assert "G-1" in prov["gaps"]["gates_with_weak_or_missing_artifact"]
    #: 不在位的文件**不进**"在位但没入库"清单 —— 那格只放"本机有、别人的树里没有"这一类可执行欠件。
    assert prov["gaps"]["artifacts_not_tracked_in_git"] == []


# ==== 5. GFM 表格：裸竖线必须转义 ========================================
def test_md_table_escapes_bare_pipes():
    table = rp._md_table(["列"], [["a|b", "c\n|d"]])
    body = table.splitlines()[-1]
    assert "\\|" in body
    #: 只数**未被转义**的竖线：一张 2 列的表只该有 3 个列分隔符（首、中、尾）。
    assert len(re.findall(r"(?<!\\)\|", body)) == 3, body


def test_artifact_cell_distinguishes_present_from_tracked():
    """「在位」与「入 git」是两个词：`*.log` 被 .gitignore 全局忽略 ⇒ 本机有 ≠ 别人能复算。"""
    cell = rp._artifact_cell({"path": "backend/reports/w6/_full_pytest_x.log",
                              "display": "backend/reports/w6/_full_pytest_x.log",
                              "present": True, "tracked_in_git": False, "basis": "mtime_only"})
    assert "在位" in cell and "入 git=否" in cell and "|" not in cell


def test_provenance_section_does_not_eat_the_rest_of_the_report():
    """🔴 本轮真实事故（我自己造的）：取证表那段循环里用了变量名 `g`，
    而 `render_markdown` 的正文累加器正是 `g` ⇒ 循环结束后 `g` 变成一个 dict，
    末尾 `"\n".join(g)` 把**整份报告**渲染成 56 个字符的键名串，
    而 `main()` 照样打印 `generated=`、退出码 0。

    所以这条守卫只认一件事：**最后一节必须还在**。它不需要知道 §1.1 长什么样，
    任何"中途把累加器换掉"的改动都会让它红。
    """
    p = rp.build_payload(
        results_path="__nope__.json", redteam_path="__nope__.json",
        consistency_path="__nope__.json", pytest_log="__nope__.log",
        integration_log="__nope__.log", metric_probe_path="__nope__.json",
        metric_values_path="__nope__.json", pg_probe_path="__nope__.json",
        loadtest_receipt="__nope__.json", pressure_report="__nope__.md")
    md = rp.render_markdown(p)
    assert "### 1.1" in md, "取证表整节缺席 = T-06 没落进产物"
    assert len(md) > 2000, f"渲染文本只有 {len(md)} 字符 ⇒ 正文被中途换掉了"
    for header in ("## 1. 门禁判定", "## 8.", "## 10. 复算指令"):
        assert header in md, f"{header} 不见了"
