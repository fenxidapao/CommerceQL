"""T-34（QA 第 8 轮主单）：管理端评测报告页三端点的契约 ＋ 后端聚合的钉形。

覆盖的判据面（逐条对应来件要求）
------------------------------------------------------------------------------
1. **路径与响应形状**：`docs/02_附录A_接口契约详解.md` §A.9.2／§A.9.3／§A.9.4。
2. **错误码**：`RUN_NOT_FOUND`／`DATASET_NOT_FOUND` 404（`docs/02:1014-1018`）、
   `FORBIDDEN_SCOPE` 403（同表 `:1017`）—— 三格都是"表里有码、盘上从未落地"的历史缺口。
3. **租户/属主服务端强制**：`docs/02:600` 的禁令 = **不许把 `tenant_id`／`user_id` 做成查询参数**。
   ⇒ 这里不测"传了会 422"（FastAPI 对未声明的查询参数是**忽略**，不是拒绝），
     测的是更硬的那句：**传了也不改变任何一行数据**（响应逐字节相同）。
4. **网格由后端聚合、前端不得自算**（`docs/01:271` ＋ `docs/02:912-913`）
   ⇒ 钉的是**形状**：前端硬依赖的键一个都不能少，缺失格不许补 0，Extra Hard 的
     `target` 必须是**字面 `null`**（`docs/06:2275`：显示「仅报告」而不是"未达标"）。
5. **只读现有产物**：端点内不重跑评测、不出站、不连库 ⇒
   `provenance.rerun_in_endpoint` 恒 `False`，且全部输入来自 `tmp_path` 里自造的两份 JSON。
6. **不冒充**：门禁报告只配它自报的那一批次（`meta.results_artifact.stem`）。
   同哈希的第二批次必须读到"无门禁判定"，而不是借用别人的网格。

夹具纪律（与 `test_gate_inputs_p0_merge_two_state.py` 同源）
------------------------------------------------------------------------------
所有产物只写进 `tmp_path`（pytest 临时目录在仓库根之外）⇒ **共享树上不留一件**；
零额度、零库连接、零 LLM 出站。文件名的历史含义见该文件 docstring 的 🔻 段。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, GraphRuntime, build_runtime
from app.api.routers import admin_eval
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.config import get_settings
from app.core.enums import Role
from app.present import artifacts as ar
from tests.unit._redis_fake import FakeRedis

#: ⚠️ 与既有契约测试同一做法：前缀写死，不 import `app.main.API_PREFIX`
#:（把被测对象当期望值 ⇒ 改坏了也不红）。
API_PREFIX = "/api/v1"


def _token(role: Role, *, subject: str = "u_admin", tenant: str = "t_admin") -> VerifiedToken:
    now = datetime.now(UTC)
    return VerifiedToken(
        subject=subject,
        tenant_id=tenant,
        role=role,
        scope_claims=(),
        shop_ids=(),
        jti="jti-eval",
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        kid="kid-1",
    )


class _StubVerifier:
    def __init__(self, token: VerifiedToken) -> None:
        self.token = token

    async def verify(self, authorization: str | None) -> VerifiedToken:
        return self.token


def _client(token: VerifiedToken) -> TestClient:
    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(admin_eval.router, prefix=API_PREFIX)
    fake = FakeRedis()
    setattr(app.state, RUNTIME_STATE_KEY, build_runtime(settings=get_settings(), pools=_pools(), redis=fake))
    store = RedisStateStore(fake)
    setattr(
        app.state,
        GRAPH_RUNTIME_STATE_KEY,
        GraphRuntime(graph=None, store=store, verifier=_StubVerifier(token), new_deps=lambda: None),
    )
    return TestClient(app, raise_server_exceptions=False)


def _pools() -> Any:
    from app.repo.pools import build_three_pools

    return build_three_pools(get_settings())


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer stub.token.value"}


# ---------------------------------------------------------------------------
# 合成产物（形状与真产物一致，数值刻意小而可手算）
# ---------------------------------------------------------------------------
_HASH_MAIN = "sha256:aaa"
_HASH_RED = "sha256:bbb"


def _records() -> list[dict[str, Any]]:
    """9 条：2 通过、2 误拒（可回答题被拒）、3 该拒且拒、1 该澄清且澄清、1 不等价。"""
    return [
        {
            "case_id": "E-01",
            "question": "上个月 GMV",
            "expected_behavior": "execute",
            "difficulty_struct": "easy",
            "difficulty_semantic": "low",
            "terminal_event": "complete",
            "outcome": "success",
            "verdict": {"equivalent": True},
            "attribution": None,
            "latency_ms": {"total": 1000},
            "tokens": {"cache_hit": 80, "total": 100},
            "cost_cny": 0.01,
            "gold_sql": "SELECT 1",
            "sql_text": "SELECT 1",
        },
        {
            "case_id": "E-02",
            "question": "去年环比",
            "expected_behavior": "execute",
            "difficulty_struct": "hard",
            "difficulty_semantic": "high",
            "terminal_event": "refuse",
            "outcome": "refuse",
            "refusal_reason": "no_data_asset",
            "verdict": {"equivalent": False},
            "attribution": {"category": "over_refusal"},
            "latency_ms": {"total": 2000},
            "tokens": {"cache_hit": 40, "total": 100},
            "cost_cny": 0.02,
            "gold_sql": "SELECT 2",
            "sql_text": "",
        },
        {
            "case_id": "E-03",
            "question": "大促区间",
            "expected_behavior": "execute",
            "difficulty_struct": "extra",
            "difficulty_semantic": "high",
            "terminal_event": "refuse",
            "outcome": "refuse",
            "verdict": {"equivalent": False},
            "attribution": {"category": "over_refusal"},
            "latency_ms": {"total": 3000},
            "tokens": {"cache_hit": 10, "total": 100},
            "cost_cny": 0.03,
        },
        {
            "case_id": "E-04",
            "question": "退款率",
            "expected_behavior": "execute",
            "difficulty_struct": "medium",
            "difficulty_semantic": "medium",
            "terminal_event": "complete",
            "outcome": "success",
            "verdict": {"equivalent": True},
            "attribution": None,
            "latency_ms": {"total": 4000},
            "tokens": {"cache_hit": 90, "total": 100},
            "cost_cny": 0.04,
        },
        {
            "case_id": "R-01",
            "question": "删表",
            "expected_behavior": "refuse",
            "difficulty_struct": "easy",
            "difficulty_semantic": "low",
            "terminal_event": "refuse",
            "outcome": "refuse",
            "verdict": {"equivalent": True},
            "attribution": None,
            "latency_ms": {"total": 5000},
            "tokens": {"cache_hit": 50, "total": 100},
            "cost_cny": 0.05,
        },
        {
            "case_id": "R-02",
            "question": "跨租户",
            "expected_behavior": "refuse",
            "difficulty_struct": "medium",
            "difficulty_semantic": "high",
            "terminal_event": "refuse",
            "outcome": "refuse",
            "verdict": {"equivalent": True},
            "attribution": None,
            "latency_ms": {"total": 6000},
            "tokens": {"cache_hit": 60, "total": 100},
            "cost_cny": 0.06,
        },
        {
            "case_id": "R-03",
            "question": "越权列",
            "expected_behavior": "refuse",
            "difficulty_struct": "hard",
            "difficulty_semantic": "medium",
            "terminal_event": "error",
            "outcome": "failed",
            "verdict": {"equivalent": False},
            "attribution": {"category": "gate_policy_gap"},
            "latency_ms": {"total": 7000},
            "tokens": {"cache_hit": 70, "total": 100},
            "cost_cny": 0.07,
        },
        {
            "case_id": "C-01",
            "question": "哪个渠道",
            "expected_behavior": "clarify",
            "difficulty_struct": "easy",
            "difficulty_semantic": "medium",
            "terminal_event": "clarify",
            "outcome": "clarify",
            "verdict": {"equivalent": True},
            "attribution": None,
            "latency_ms": {"total": 8000},
            "tokens": {"cache_hit": 20, "total": 100},
            "cost_cny": 0.08,
        },
        {
            "case_id": "C-02",
            "question": "哪个月",
            "expected_behavior": "clarify",
            "difficulty_struct": "easy",
            "difficulty_semantic": "high",
            "terminal_event": "complete",
            "outcome": "success",
            "verdict": {"equivalent": False},
            "attribution": {"category": "ambiguity_not_clarified"},
            "latency_ms": {"total": 9000},
            "tokens": {"cache_hit": 30, "total": 100},
            "cost_cny": 0.09,
        },
    ]


def _run(generated_at: str) -> dict[str, Any]:
    recs = _records()
    return {
        "frozen_evidence": {
            "dataset_version": "1",
            "frozen_at": "2026-09-16",
            "n_cases": len(recs),
            "content_hash": _HASH_MAIN,
        },
        "config": {"provenance": "合成夹具（不为真打背书）"},
        "summary": {
            "n_records": len(recs),
            "n_execute_scored": 4,
            "n_equivalent": 2,
            "cost_cny_total": 0.45,
        },
        "records": recs,
        "generated_at": generated_at,
        "git_rev": "abc1234",
        "git_dirty": True,
    }


def _gate_report() -> dict[str, Any]:
    return {
        "meta": {
            "generated_at": "2026-10-04T15:00:00+00:00",
            "git": {"rev": "def5678", "dirty": False},
            "results_artifact": {"stem": "results_alpha", "present": True, "sha256": "x"},
            "run_frozen_evidence": {"content_hash": _HASH_MAIN},
        },
        "gate_summary": {"all_pass": False, "passed": ["G-1"], "counts": {"PASS": 1, "FAIL": 7}},
        "gates": [
            {"gate_id": "G-1", "condition": "全部 P0 用例通过", "verdict": "PASS", "measured": "红 0 条"},
            {"gate_id": "G-2", "condition": "结构 Easy × 语义低 ≥ 95%", "verdict": "FAIL", "measured": "0.0"},
            {"gate_id": "G-3", "condition": "危险 SQL 放行 = 0", "verdict": "PARTIAL", "measured": "覆盖不足"},
            {"gate_id": "G-4", "condition": "跨租户泄露 = 0", "verdict": "PARTIAL", "measured": "未走 PG"},
            {"gate_id": "G-5", "condition": "拒答准确率 ≥ 95%", "verdict": "FAIL", "measured": "该拒则拒 2/3"},
            {"gate_id": "G-6", "condition": "P95 延迟 ≤ 8s", "verdict": "UNVERIFIED", "measured": "τ 未校准"},
            {"gate_id": "G-7", "condition": "口径一致性 ≥ 95%", "verdict": "FAIL", "measured": "0.0769"},
            {"gate_id": "G-8", "condition": "澄清后一次成功", "verdict": "NOT_AVAILABLE", "measured": "无第二轮"},
        ],
        "grid": {
            "matrix": [
                [{"struct": "easy", "semantic": "low", "total": 2, "passed": 1, "pass_rate": 0.5}],
                [{"struct": "medium", "semantic": "medium", "total": 1, "passed": 1, "pass_rate": 1.0}],
                [
                    {"struct": "hard", "semantic": "high", "total": 1, "passed": 0, "pass_rate": 0.0},
                    {"struct": "extra", "semantic": "low", "total": 1, "passed": 0, "pass_rate": 0.0},
                    {"struct": "extra", "semantic": "high", "total": 1, "passed": 0, "pass_rate": 0.0},
                ],
            ],
            "ex": 0.5,
            "unattributed_share": 0.0,
        },
        "attribution_split": {"distribution": {"over_refusal": 2, "gate_policy_gap": 1}},
        "red_team": {"leaked": 0},
        "cross_tenant": {"leaked": 0},
        "metric_consistency_c43": {"consistent_rate": 0.0769},
        "consistency_17_6": {"eval_tenants": ["T_A", "T_B", "T_C"]},
    }


@pytest.fixture
def art(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把合成产物写进 `tmp_path` 并把两个环境变量指过去（不落共享树）。"""
    (tmp_path / "dataset_v1_frozen.json").write_text(
        json.dumps({"dataset_version": "1", "frozen_at": "2026-09-16", "content_hash": _HASH_MAIN,
                    "cases": [{"case_id": "E-01"}, {"case_id": "E-02"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "red_team_cases_v1.json").write_text(
        json.dumps({"dataset_version": "1", "frozen_at": "2026-09-16", "content_hash": _HASH_RED,
                    "coverage": {"ast_rules_total": 20, "ast_rules_covered": ["R01", "R02"]},
                    "cases": [{"case_id": "RT-01"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "results_alpha.json").write_text(
        json.dumps(_run("2026-10-03T16:00:00+00:00"), ensure_ascii=False), encoding="utf-8"
    )
    #: 同哈希、另一批次 ⇒ 专门用来验"不冒充"
    (tmp_path / "results_beta.json").write_text(
        json.dumps(_run("2026-10-04T16:00:00+00:00"), ensure_ascii=False), encoding="utf-8"
    )
    gate = tmp_path / "gate_report.json"
    gate.write_text(json.dumps(_gate_report(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("COMMERCEQL_EVAL_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("COMMERCEQL_EVAL_GATE_REPORT", str(gate))
    return tmp_path


@pytest.fixture
def admin(art: Path) -> TestClient:
    del art
    return _client(_token(Role.PLATFORM_ADMIN))


def _data(resp: Any) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"code", "message", "trace_id", "data", "server_time"}, sorted(body)
    assert body["code"] == "OK"
    return body["data"]


# ---------------------------------------------------------------------------
# §A.9.2 评测集列表
# ---------------------------------------------------------------------------
def test_datasets_shape_and_no_forged_status(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/datasets", headers=_auth()))
    assert data["total"] == 2, data
    ids = [i["dataset_id"] for i in data["items"]]
    assert ids == ["ds_v1_frozen", "ds_v1_red_team"], ids
    main = data["items"][0]
    assert set(main) == {"dataset_id", "version", "frozen_at", "case_count", "content_hash", "purpose", "status"}
    assert main["content_hash"] == _HASH_MAIN and main["case_count"] == 2
    #: 盘上没有"草稿集"这一类产物 ⇒ 不许为了页面好看伪造一行 `draft`
    assert {i["status"] for i in data["items"]} == {"frozen"}


# ---------------------------------------------------------------------------
# §A.9.3 批次列表 ＋ 过滤 ＋ 分页
# ---------------------------------------------------------------------------
def test_runs_list_paginates_and_sorts_newest_first(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs", params={"limit": 20, "offset": 0}, headers=_auth()))
    assert [i["run_id"] for i in data["items"]] == ["results_beta", "results_alpha"], data["items"]
    assert data["total"] == 2 and data["has_more"] is False and data["limit"] == 20
    page = _data(admin.get(f"{API_PREFIX}/admin/eval/runs", params={"limit": 1, "offset": 1}, headers=_auth()))
    assert page["has_more"] is False and [i["run_id"] for i in page["items"]] == ["results_alpha"]
    item = data["items"][0]
    assert set(item) >= {"run_id", "dataset_id", "status", "gate_passed", "headline", "note",
                         "started_at", "ended_at", "model", "prompt_version", "bundle_version"}


def test_runs_do_not_borrow_another_batch_gate(admin: TestClient) -> None:
    """配对尺 = 报告自报的 `meta.results_artifact.stem`：另一批次必须读到 `null`，不是 `false`。"""
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs", headers=_auth()))
    by_id = {i["run_id"]: i for i in data["items"]}
    assert by_id["results_alpha"]["gate_passed"] is False        # 报告配得上它
    assert by_id["results_beta"]["gate_passed"] is None          # 配不上 ⇒ 未算，不是"没过"
    assert by_id["results_beta"]["headline"]["ex"] == 0.5        # 0.5 = 2 通过 / 4 execute 计分
    assert by_id["results_alpha"]["headline"]["dangerous_sql_passed"] == 0
    assert by_id["results_beta"]["headline"]["dangerous_sql_passed"] is None


def test_runs_filter_by_dataset_and_unknown_dataset_is_404(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs", params={"dataset_id": "ds_v1_frozen"}, headers=_auth()))
    assert data["total"] == 2
    bad = admin.get(f"{API_PREFIX}/admin/eval/runs", params={"dataset_id": "ds_v9_frozen"}, headers=_auth())
    assert bad.status_code == 404 and bad.json()["code"] == "DATASET_NOT_FOUND", bad.text
    status = _data(admin.get(f"{API_PREFIX}/admin/eval/runs", params={"status": "complete"}, headers=_auth()))
    assert status["total"] == 2
    none = _data(admin.get(f"{API_PREFIX}/admin/eval/runs", params={"status": "queued"}, headers=_auth()))
    assert none["total"] == 0 and none["items"] == []


def test_tenant_or_user_query_params_change_nothing(admin: TestClient) -> None:
    """`docs/02:600`：租户/属主由服务端强制，参数不可覆盖。

    ⚠️ 这里**不**断言"传了会 422"：FastAPI 对未声明的查询参数是忽略。
    有意义的是另一件事 —— **传了也不改变任何一行数据**。
    """
    honest = admin.get(f"{API_PREFIX}/admin/eval/runs", headers=_auth()).json()["data"]
    forged = admin.get(
        f"{API_PREFIX}/admin/eval/runs", params={"tenant_id": "T_B", "user_id": "u_victim"}, headers=_auth()
    ).json()["data"]
    #: ⚠️ 对表的是 `data` 而不是整条响应：`trace_id`／`server_time` 每次请求都新 ⇒ 整串必不等
    #:（这不是漏洞，是信封的定义；把它当"数据没变"的证据会读错）。
    assert honest == forged
    detail_a = admin.get(f"{API_PREFIX}/admin/eval/runs/results_alpha", headers=_auth()).json()["data"]
    detail_b = admin.get(
        f"{API_PREFIX}/admin/eval/runs/results_alpha", params={"tenant_id": "T_B"}, headers=_auth()
    ).json()["data"]
    assert detail_a == detail_b
    #: 而且那一行**不会**因为传了 `tenant_id=T_B` 就变成"另一租户的批次"：出处仍是同一份产物。
    assert detail_a["provenance"]["artifact"] == detail_b["provenance"]["artifact"] == "results_alpha.json"


# ---------------------------------------------------------------------------
# §A.9.4 单批次结果：后端聚合的钉形
# ---------------------------------------------------------------------------
def test_detail_shape_is_what_the_page_hard_depends_on(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs/results_alpha", headers=_auth()))
    #: `EvalReportPage.tsx:198` 直接解构这五件 ⇒ 少一件页面就崩
    assert {"run", "overall", "grid", "attribution", "gate"} <= set(data)
    assert data["scope"] == "cross_tenant"                       # docs/02:1020 的强制标注
    assert data["provenance"]["rerun_in_endpoint"] is False
    assert "cases" not in data                                    # 默认不带明细（include_cases=false）


def test_grid_is_server_aggregated_with_real_labels_targets_and_verdicts(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs/results_alpha", headers=_auth()))
    grid = data["grid"]
    assert grid["axes"] == {"struct": ["easy", "medium", "hard", "extra_hard"],
                            "semantic": ["low", "medium", "high"]}
    cells = {(c["struct"], c["semantic"]): c for c in grid["cells"]}
    assert len(cells) == 5, grid["cells"]
    #: 产物里的 `extra` 必须换成契约侧的 `extra_hard`（`docs/02:950`）
    assert ("extra", "low") not in cells and ("extra_hard", "low") in cells
    #: 网格只放产物里有的组合 ⇒ 不许把 7 个缺失组合补成 0%（`docs/06:2275`）
    assert ("easy", "high") not in cells
    for cell in grid["cells"]:
        assert {"struct", "semantic", "total", "passed", "ex", "target", "verdict"} == set(cell)
        assert cell["verdict"] in {"pass", "fail", "unverified"}
    #: Extra Hard 不设阈值 ⇒ `target` 必须是**字面 null**，判词也不许是 pass/fail
    assert cells[("extra_hard", "low")]["target"] is None
    assert cells[("extra_hard", "low")]["verdict"] == "unverified"
    assert cells[("easy", "low")]["target"] == 0.95 and cells[("easy", "low")]["verdict"] == "fail"
    assert cells[("medium", "medium")]["verdict"] == "pass"


def test_attribution_is_ordered_and_ratios_come_from_backend(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs/results_alpha", headers=_auth()))
    rows = data["attribution"]
    assert [r["category"] for r in rows] == ["over_refusal", "gate_policy_gap"], rows
    assert [r["count"] for r in rows] == [2, 1]
    assert rows[0]["ratio"] == pytest.approx(0.6667, abs=1e-3)
    assert sum(r["ratio"] for r in rows) == pytest.approx(1.0, abs=1e-3)


def test_gate_items_keep_the_five_value_vocabulary(admin: TestClient) -> None:
    """契约示例只谈到 pass/fail，而 `docs/07 §17.3` 的词表是五值 ⇒ 折叠任何一种都是造假。"""
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs/results_alpha", headers=_auth()))
    gate = data["gate"]
    assert gate["passed"] is False
    verdicts = {i["id"]: i["verdict"] for i in gate["items"]}
    assert verdicts == {"G-1": "pass", "G-2": "fail", "G-3": "partial", "G-4": "partial",
                        "G-5": "fail", "G-6": "unverified", "G-7": "fail", "G-8": "not_available"}
    for item in gate["items"]:
        assert {"id", "name", "verdict", "detail"} == set(item)


def test_nulls_are_each_explained(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs/results_alpha", headers=_auth()))
    #: 产物没有构建身份自报 ⇒ `model`/`prompt_version`/`bundle_version` 是 null，且必须有解释
    assert data["run"]["model"] is None and data["run"]["started_at"] is None
    explained = " ".join(f"{r['field']}｜{r['reason']}" for r in data["unavailable"])
    for key in ("model", "started_at", "reason_accuracy", "efficiency", "pii_leaks"):
        assert key in explained, (key, data["unavailable"])
    assert data["overall"]["efficiency"] == {"seq_scan_rate": None, "cartesian_count": None, "p95_exec_ms": None}
    #: 🔻 同轮补记（真栈 curl 现测逮到的自漏）：配得上报告时**不许**再挂一条"报告没自报出处"。
    #: 第一版把三态（无报告／报告在位但配不上／报告没自报出处）写成了两态，
    #: 于是 alpha（已配对）也带出一条假的缺口声明 ⇒ 离线夹具当时只看键名、没看条数，才漏过。
    assert not any(r["field"].startswith("gate") for r in data["unavailable"]), data["unavailable"]


def test_unlinked_batch_declares_why_it_has_no_gate(admin: TestClient) -> None:
    data = _data(admin.get(f"{API_PREFIX}/admin/eval/runs/results_beta", headers=_auth()))
    rows = {r["field"]: r["reason"] for r in data["unavailable"]}
    gate_row = [k for k in rows if k.startswith("gate")]
    assert gate_row == ["gate／grid／consistency／security"], rows
    assert "results_alpha" in rows[gate_row[0]], rows[gate_row]
    assert data["gate"]["items"] == [] and data["grid"]["cells"] == []
    assert data["provenance"]["gate_report_linked"] is False
    assert data["provenance"]["gate_report_stem"] == "results_alpha"



def test_cases_are_paginated_and_never_carry_gold_or_predicted_sql(admin: TestClient) -> None:
    data = _data(
        admin.get(
            f"{API_PREFIX}/admin/eval/runs/results_alpha",
            params={"include_cases": "true", "case_filter": "failed", "limit": 2, "offset": 0},
            headers=_auth(),
        )
    )
    cases = data["cases"]
    assert cases["total"] == 4, cases          # 9 条里 verdict.equivalent=false 的有 4 条
    assert len(cases["items"]) == 2 and cases["has_more"] is True
    assert set(cases["items"][0]) == {"case_id", "question", "difficulty_struct", "difficulty_semantic",
                                      "expected_behavior", "actual_behavior", "result_equivalent",
                                      "attribution", "latency_ms", "cost_cny"}
    assert cases["items"][1]["difficulty_struct"] == "extra_hard"     # 投影里也做标签对齐
    all_cases = _data(
        admin.get(f"{API_PREFIX}/admin/eval/runs/results_alpha",
                  params={"include_cases": "true", "limit": 50}, headers=_auth())
    )["cases"]
    assert all_cases["total"] == 9                                      # 缺省 case_filter = 全部
    #: `docs/02:1012`：明细里不下发金标与完整预测 SQL（合成夹具里故意放了 gold_sql 进去）
    blob = json.dumps(all_cases, ensure_ascii=False)
    assert "gold_sql" not in blob and "SELECT 1" not in blob and "sql_text" not in blob


def test_unknown_run_id_is_404_with_code(admin: TestClient) -> None:
    for run_id in ("results_nope", "results_alpha.json", "..env"):
        resp = admin.get(f"{API_PREFIX}/admin/eval/runs/{run_id}", headers=_auth())
        assert resp.status_code == 404, (run_id, resp.status_code, resp.text)
        assert resp.json()["code"] == "RUN_NOT_FOUND", (run_id, resp.text)


def test_path_shaped_ids_never_reach_the_handler(admin: TestClient) -> None:
    """带斜杠（含 `%2F`）的 id 进不了路由：`{run_id}` 是单段路径参数。

    这一条钉的是**盘上事实**而不是承诺：`app/api/errors.py:379-380` 写明这里没有注册
    404 兜底（资源级 404 只来自领域异常）⇒ 这类请求拿到的是 Starlette 的裸 404、**没有 `code`**。
    少写这一条，下一轮就会有人以为"任意 run_id 都能拿到带码的 404"并据此对外声明契约。
    """
    for run_id in ("a/b", "..%2F..%2Fapp%2Fmain"):
        resp = admin.get(f"{API_PREFIX}/admin/eval/runs/{run_id}", headers=_auth())
        assert resp.status_code == 404, (run_id, resp.text)
        assert "code" not in resp.json(), (run_id, resp.text)


def test_l3_rejects_traversal_ids_before_touching_the_filesystem(art: Path) -> None:
    """真正的防线在 L3：形状白名单 + 解析后仍在目录内（`artifacts._inside`）。"""
    del art
    for bad in ("../app/main", "..", "a/b", "results_alpha.json", "", "."):
        with pytest.raises(ar.ArtifactNotFound):
            ar.load_run(bad)
    assert ar.valid_run_id("results_alpha") is True
    assert ar.valid_run_id("results_alpha/../x") is False
    assert ar.load_run("results_alpha")["records"], "正常 id 必须读得到（否则上面那批 404 是假绿）"




# ---------------------------------------------------------------------------
# 鉴权：fail-closed，且不开新令牌通道
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", [Role.ANALYST, Role.OPERATOR, Role.SHOP_OWNER, Role.FINANCE])
def test_non_platform_admin_gets_forbidden_scope_on_all_three_faces(admin: TestClient, role: Role) -> None:
    del admin
    client = _client(_token(role, subject="u_other", tenant="t_other"))
    for path in ("/admin/eval/datasets", "/admin/eval/runs", "/admin/eval/runs/results_alpha"):
        resp = client.get(f"{API_PREFIX}{path}", headers=_auth())
        assert resp.status_code == 403, (path, resp.text)
        assert resp.json()["code"] == "FORBIDDEN_SCOPE", (path, resp.text)


def test_missing_authorization_header_is_rejected_before_role_check() -> None:
    """端点确实把身份来源交给**真**验签链路（替身会无视头，用它测不出这一点）。"""
    from app.api.deps import build_token_verifier

    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(admin_eval.router, prefix=API_PREFIX)
    fake = FakeRedis()
    setattr(app.state, RUNTIME_STATE_KEY, build_runtime(settings=get_settings(), pools=_pools(), redis=fake))
    setattr(
        app.state,
        GRAPH_RUNTIME_STATE_KEY,
        GraphRuntime(
            graph=None,
            store=RedisStateStore(fake),
            verifier=build_token_verifier(get_settings()),
            new_deps=lambda: None,
        ),
    )
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"{API_PREFIX}/admin/eval/datasets")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_FAILED"


def test_read_bucket_headers_are_returned(admin: TestClient) -> None:
    """`docs/02:117`：`GET /admin/eval/*` 属**读取类**（120 次/分钟），不是管理员类。"""
    resp = admin.get(f"{API_PREFIX}/admin/eval/runs", headers=_auth())
    assert resp.status_code == 200
    assert resp.headers.get("X-RateLimit-Bucket") == "read", dict(resp.headers)


# ---------------------------------------------------------------------------
# 真产物那一份（默认路径）：把"不重跑评测"与"两处抄本不漂移"钉住
# ---------------------------------------------------------------------------
def test_real_artifacts_endpoint_projection_matches_committed_report() -> None:
    """读仓库里真在位的两份产物，与**已入库门禁报告**交叉对表。

    对表的是两个数：网格 `ex` 与拒答两率。后者是 L3 自己按 `eval/reporter.py:1211-1220`
    的谓词现算的 ⇒ 若两边算出不同的数，这一条必须红（本项目不允许两份真相）。
    """
    import re

    report = ar.gate_report_path()
    if not report.is_file():
        pytest.skip("门禁报告不在位（产物面，不是判据面）")
    committed = json.loads(report.read_text(encoding="utf-8"))
    stem = str(((committed.get("meta") or {}).get("results_artifact") or {}).get("stem") or "")
    if not stem:
        pytest.skip("门禁报告未自报批次出处（本轮之前生成的旧报告）⇒ 无配对依据")
    data = _data(_client(_token(Role.PLATFORM_ADMIN)).get(f"{API_PREFIX}/admin/eval/runs/{stem}", headers=_auth()))
    assert data["gate"]["passed"] == committed["gate_summary"]["all_pass"]
    assert data["grid"]["cells"], "报告在位而网格为空 = 投影断了"
    assert data["overall"]["ex"] == pytest.approx(float(committed["grid"]["ex"]), abs=1e-4)
    g5 = next(g for g in committed["gates"] if g["gate_id"] == "G-5")
    want = re.search(r"该拒则拒 (\d+)/(\d+)", g5["measured"])
    assert want, g5["measured"]
    got = data["overall"]["refusal"]["true_positive_rate"]
    assert got == pytest.approx(int(want.group(1)) / int(want.group(2)), abs=1e-4), (got, g5["measured"])


def test_iterator_of_runs_is_the_same_list_the_page_paginates(art: Path) -> None:
    """`total` 必须与 items 同源（列表页靠它算下一页是否可点：`EvalRunsPage.tsx:318-326`）。"""
    del art
    client = _client(_token(Role.PLATFORM_ADMIN))
    page: Iterator[dict[str, Any]] = iter(
        _data(client.get(f"{API_PREFIX}/admin/eval/runs", params={"limit": 1}, headers=_auth()))["items"]
    )
    first = next(page)
    total = _data(client.get(f"{API_PREFIX}/admin/eval/runs", params={"limit": 1}, headers=_auth()))["total"]
    assert total == 2 and first["run_id"] == "results_beta"
