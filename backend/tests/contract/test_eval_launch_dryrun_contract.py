"""T-37 A3（QA 第 14 轮主单）：`POST /api/v1/admin/eval/run` 的 **dry-run 预检**契约面。

判据来源（逐字，不转述）
------------------------------------------------------------------------------
- `docs/02_附录A_接口契约详解.md:829-843`（§A.9.1 的请求 5 键 ＋ `{"run_id","status":"queued"}`）
  ⇒ 本轮**只交预检**：`run_id` 恒 `null`、`status="dry_run"`（`docs/02 §A.9.1 补记` 已登记该子状态）。
- 同件 `:119`（`POST /admin/eval/run` = **管理员类** 5 次/分钟）
- 同件 `:65`（`tenant_id` 必须从 JWT 取，禁止做成查询参数）
- 同件 `:1119`（"本表是错误码**唯一来源**"）⇒ 本文件**只断言既有的 28 码**，
  出现第 29 个码就是改判据（`dry_run=false` 走 `INVALID_REQUEST`，见臂 6）。
- 来件红线：这一支一按就发 LLM 出站 ⇒ **默认 dry-run、真发起不可表达、本轮零额度**。

本文件钉什么（缺任何一条，对应那个失败就会静默活下来）
------------------------------------------------------------------------------
1. **角色 fail-closed**：6 个非 `platform_admin` 角色逐个 ⇒ 403 `FORBIDDEN_SCOPE`，
   且**明确不是** 401（令牌没问题）也不是 500（没有未捕获异常）。
2. **报价的每一格可手算**：夹具两批（A：0.001／0.003、LLM 节点 3＋6；B：0.002／0.018、4＋8）⇒
   条数 9／12、均价 0.004／0.020、保守 0.036（= max-per-case 0.018×2）、峰上界 0.040。改算法就红。
3. **只认真打过批次**：`config.live = false` 的 replay 产物（夹具里总额 99.0）必须**不进基准**；
   非 LLM 节点（`trusted_context`／`link`／`refuse_out`）必须**不计数**；
   同一批次的**文件副本**只算一次观测（`artifacts_available` 与 `distinct_batches` 是两个数）。
4. **外推方向如实**：被请求集没有真打批次 ⇒ `mode` 逐格点名，且**没有观测批**时
   `estimate` 逐格 `null`（不许拿价表乘一个猜的条数当报价）。
5. **模型归属不可证**：观测批次 `config` 不自报 `model` ⇒ `evidenced_by_basis` 恒 `False`。
6. **真发起在 schema 面不可表达**：`dry_run=false` ⇒ 400 `INVALID_REQUEST`（用的仍是 28 码之一），
   字段名点在 **DTO 面**（`detail` 此时不下发 —— 身份还没装配，N-11 的缺省；有对照臂）。
7. **零出站的两种证法**：① 结构性 —— `eval_launch.py` 的 import 集合被钉成逐字一份抄本，
   多一个 `httpx`／`app.graph` 就红；② 运行时 —— 把 `httpx` 两条请求路径换成会抛的实现再打端点，
   仍然 200。
8. **抄本钉等值**：`LLM_NODE_NAMES == frozenset(_LLM_NODE_TASKS)`（L3 不能向上 import L4，
   所以只有测试可以跨层核对）；`CONTRACT_REQUEST_KEYS == EvalRunRequest` 的字段集。
9. **限流桶 = `admin`**（不是 `read`），第 6 次 ⇒ 429 `RATE_LIMITED` ＋ `Retry-After: 60`。

夹具纪律：批次产物与冻结集只写进 `tmp_path`（仓库根之外）⇒ **共享树上不留一件**；
零额度、零库连接、零 LLM 出站。
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import GRAPH_RUNTIME_STATE_KEY, RUNTIME_STATE_KEY, GraphRuntime, build_runtime
from app.api.dto.eval_run import CONTRACT_REQUEST_KEYS, EvalRunRequest
from app.api.routers import admin_eval
from app.api.state_store import RedisStateStore
from app.auth.tokens import VerifiedToken
from app.core.config import get_settings
from app.core.enums import Role
from app.present import eval_launch
from tests.unit._redis_fake import FakeRedis

#: ⚠️ 前缀写死，不 import `app.main.API_PREFIX`（把被测对象当期望值 ⇒ 改坏了也不红）。
API_PREFIX = "/api/v1"
RUN_URL = f"{API_PREFIX}/admin/eval/run"

#: 夹具里合成冻结集的内容哈希（与真冻结集无关，只在 tmp_path 内自洽）。
HASH_FROZEN = "sha256:" + "f" * 64
HASH_OTHER = "sha256:" + "e" * 64

#: §A.9.1 请求体的键（`docs/02:829-837` 的 5 键 ＋ 本窗自订的 `dry_run`）。
ENDPOINT = "/admin/eval/run"

#: `eval_launch.py` 允许触碰的模块 —— **逐字一份抄本**（臂 7①）。
#: 改这个集合的人必须同时说明：为什么预检需要一个会出站的依赖。
EVAL_LAUNCH_IMPORTS: frozenset[str] = frozenset(
    {
        "__future__.annotations",
        "datetime.UTC",
        "datetime.datetime",
        "decimal.Decimal",
        "statistics.median",
        "typing.Any",
        "typing.Final",
        "app.llm.budget",
        "app.present.artifacts",
        "app.present.eval_report",
    }
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _token(role: Role, *, subject: str = "u_admin", tenant: str = "t_admin") -> VerifiedToken:
    now = datetime.now(UTC)
    return VerifiedToken(
        subject=subject,
        tenant_id=tenant,
        role=role,
        scope_claims=(),
        shop_ids=(),
        jti="jti-evalrun",
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        kid="kid-1",
    )


class _StubVerifier:
    def __init__(self, token: VerifiedToken) -> None:
        self.token = token

    async def verify(self, authorization: str | None) -> VerifiedToken:
        return self.token


def _pools() -> Any:
    from app.repo.pools import build_three_pools

    return build_three_pools(get_settings())


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


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer stub.token.value"}


def _data(resp: Any) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _dataset_file(hash_value: str, cases: int) -> dict[str, Any]:
    return {
        "dataset_version": 1,
        "frozen_at": "2026-09-14",
        "content_hash": hash_value,
        "cases": [{"case_id": f"E-{i}"} for i in range(cases)],
    }


#: 节点序列：`trusted_context`／`link`／`refuse_out` **不是** LLM 节点（臂 3 靠这个差额）。
_CASE_GATEWAY = ["trusted_context", "normalize", "intent", "link", "plan", "refuse_out"]  # 3 个 LLM 节点
_CASE_FULL = ["normalize", "intent", "plan", "gen_sql", "present", "repair"]  # 6 个
_CASE_SHORT = ["normalize", "intent", "plan", "gen_sql"]  # 4 个
_CASE_REPAIRED = ["normalize", "intent", "plan", "gen_sql", "present", "repair", "bind", "gen_sql"]  # 8 个


def _batch(
    *,
    rev: str,
    generated_at: str,
    cost_total: float,
    cases: list[tuple[float, list[str]]],
    live: bool = True,
    hash_value: str = HASH_FROZEN,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "git_rev": rev,
        "config": {"live": live, "mode": "record" if live else "replay"},
        "summary": {"cost_cny_total": cost_total},
        "frozen_evidence": {"checks": {"dataset_content_hash": {"actual": hash_value}}},
        "records": [{"case_id": f"E-{i}", "cost_cny": cost, "nodes": nodes} for i, (cost, nodes) in enumerate(cases)],
    }


#: 批次 A：2 案、成本 0.001／0.003、LLM 节点 3＋6 = 9 次、总额 0.004（每案均 0.002）。
_A = _batch(
    rev="deadbee",
    generated_at="2026-10-03T14:10:32+00:00",
    cost_total=0.004,
    cases=[(0.001, _CASE_GATEWAY), (0.003, _CASE_FULL)],
)
#: 批次 B：2 案、成本 0.002／0.018、LLM 节点 4＋8 = 12 次、总额 0.020（每案均 0.010）。
#: ⚠️ 刻意与 A 的"每案最贵"不同 ⇒ 保守档取错（min 而不是 max）当场可辨。
_B = _batch(
    rev="cafebee",
    generated_at="2026-10-04T03:00:00+00:00",
    cost_total=0.020,
    cases=[(0.002, _CASE_SHORT), (0.018, _CASE_REPAIRED)],
)
#: replay 产物：`live = false`，成本 99.0 ⇒ 一旦被当基准就必然红。
_REPLAY = _batch(
    rev="bee0001",
    generated_at="2026-10-05T02:00:00+00:00",
    cost_total=99.0,
    cases=[(50.0, _CASE_FULL), (49.0, _CASE_FULL)],
    live=False,
)


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """产物目录指到 `tmp_path`：冻结集 2 案 ＋ 批次 A ＋ **A 的副本** ＋ 批次 B ＋ 一份 replay。

    ⚠️ 副本不是凑数：盘上真实存在这种情况（`results_v1.json` 与
    `results_v2_live_20261003T1632Z.json` 同 `git_rev`＋同 `generated_at`＋同总成本）。
    ⇒ 文件数与批次数必须是两个数，否则读的人以为是两次**独立**观测。
    """
    (tmp_path / "dataset_v1_frozen.json").write_text(json.dumps(_dataset_file(HASH_FROZEN, 2)), encoding="utf-8")
    for name, doc in (
        ("results_synth_live.json", _A),
        ("results_synth_live_copy.json", _A),
        ("results_synth_live_b.json", _B),
        ("results_synth_replay.json", _REPLAY),
    ):
        (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("COMMERCEQL_EVAL_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("COMMERCEQL_EVAL_GATE_REPORT", str(tmp_path / "no_gate.json"))
    return tmp_path


def _post(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post(RUN_URL, json=body, headers=_auth())


# ---------------------------------------------------------------------------
# 1 角色 fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role",
    [Role.SHOP_OWNER, Role.OPERATOR, Role.MARKETER, Role.FINANCE, Role.SUPPORT, Role.ANALYST],
)
def test_non_platform_admin_gets_named_403_not_401_or_500(role: Role, runs: Path) -> None:
    resp = _post(_client(_token(role)), {"dataset_id": "ds_v1_frozen"})
    assert resp.status_code == 403, f"{role} ⇒ {resp.status_code}（判据：fail-closed 且不是 401/500）"
    assert resp.json()["code"] == "FORBIDDEN_SCOPE"


def test_missing_authorization_header_is_rejected_by_the_real_verifier(runs: Path) -> None:
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
    resp = TestClient(app, raise_server_exceptions=False).post(RUN_URL, json={"dataset_id": "ds_v1_frozen"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_FAILED"


# ---------------------------------------------------------------------------
# 2 预检形状：不产生 run_id、不声称已发起
# ---------------------------------------------------------------------------
def test_dry_run_never_invents_a_run_id(runs: Path) -> None:
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"}))
    assert data["run_id"] is None, "§A.9.1 的 run_id 需要运行登记表 ⇒ 今天不许编一个"
    assert data["status"] == "dry_run"
    assert data["launched"] is False
    assert {b["missing"] for b in data["launch_blockers"]} == {
        "eval_run_registry",
        "in_process_runner",
        "approved_spend",
    }


def test_echo_is_the_request_body_verbatim(runs: Path) -> None:
    body = {"dataset_id": "ds_v1_frozen", "model": "deepseek-flash", "note": "回归：新增同义词表后"}
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), body))
    assert data["echo"]["dataset_id"] == "ds_v1_frozen"
    assert data["echo"]["model"] == "deepseek-flash"
    assert data["echo"]["note"] == "回归：新增同义词表后"
    assert set(data["echo"]) == set(CONTRACT_REQUEST_KEYS)


# ---------------------------------------------------------------------------
# 3 报价可手算（夹具数值刻意为小而可除尽）
# ---------------------------------------------------------------------------
def test_quote_reconciles_by_hand(runs: Path) -> None:
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"}))
    q = data["quote"]
    assert q["dataset_id"] == "ds_v1_frozen"
    assert q["cases_total"] == 2
    assert q["basis"]["mode"] == "same_dataset"
    est = q["estimate"]
    #: 每案 LLM 节点：A = 9÷2 = 4.5，B = 12÷2 = 6 ⇒ ×2 案 = 9 ／ 12
    assert est["llm_calls_low"] == 9 and est["llm_calls_high"] == 12
    #: 每案均价：A = 0.004÷2 = 0.002，B = 0.020÷2 = 0.010 ⇒ ×2 案 = 0.004 ／ 0.020
    assert est["cost_cny_off_peak_low"] == pytest.approx(0.004)
    assert est["cost_cny_off_peak_high"] == pytest.approx(0.020)
    #: 保守 = **各批最贵一案里的最大值** 0.018 × 2 = 0.036（取 min 会算成 0.006）
    assert est["cost_cny_off_peak_conservative"] == pytest.approx(0.036)
    #: 峰上界 = 0.020 × 乘数 2.00
    assert q["tier"]["peak_multiplier"]["multiplier"] == "2.00"
    assert est["cost_cny_peak_upper_bound"] == pytest.approx(0.040)


def test_replay_batch_and_non_llm_nodes_do_not_enter_the_basis(runs: Path) -> None:
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"}))
    basis = data["quote"]["basis"]
    names = {a["artifact"] for a in basis["artifacts"]}
    assert names == {"results_synth_live", "results_synth_live_copy", "results_synth_live_b"}, (
        f"基准里混进了非 live 批次：{names}"
    )
    assert basis["artifacts_available"] == 3, "replay 产物（¥99）不得进分母"
    row = basis["artifacts"][0]
    #: 9 而不是 11 —— `trusted_context`／`link`／`refuse_out` 不是 LLM 节点
    assert row["llm_calls"] == 9
    assert row["cases"] == 2
    assert row["cost_cny_per_case"] == {"min": 0.001, "median": 0.002, "max": 0.003}
    assert row["tier_observed"] == "off_peak"


def test_duplicate_copy_of_one_batch_is_not_reported_as_two_observations(runs: Path) -> None:
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"}))
    basis = data["quote"]["basis"]
    assert basis["artifacts_available"] == 3
    assert basis["distinct_batches"] == 2, "同 rev＋同 generated_at＋同总成本的副本 = 一次观测，不是两次"


def test_every_basis_row_carries_its_own_provenance(runs: Path) -> None:
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"}))
    for row in data["quote"]["basis"]["artifacts"]:
        for key in ("artifact", "generated_at", "git_rev", "dataset_content_hash"):
            assert row[key], f"报价的出处缺一格：{key}"


# ---------------------------------------------------------------------------
# 4 外推方向 ＋ 无观测批时不许造数
# ---------------------------------------------------------------------------
def test_extrapolated_mode_is_named_when_the_requested_set_was_never_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "dataset_v1_frozen.json").write_text(json.dumps(_dataset_file(HASH_FROZEN, 2)), encoding="utf-8")
    (tmp_path / "red_team_cases_v1.json").write_text(
        json.dumps({**_dataset_file(HASH_OTHER, 3), "coverage": {}}), encoding="utf-8"
    )
    (tmp_path / "results_synth_live.json").write_text(json.dumps(_A), encoding="utf-8")
    monkeypatch.setenv("COMMERCEQL_EVAL_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("COMMERCEQL_EVAL_GATE_REPORT", str(tmp_path / "no_gate.json"))
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_red_team"}))
    assert data["quote"]["basis"]["mode"] == "extrapolated_from_other_dataset"
    assert data["quote"]["cases_total"] == 3
    #: 外推方向 = 上界（红队题多在上游早退）⇒ 报价必须仍非空，但口径要写明
    assert data["quote"]["estimate"]["llm_calls_high"] == round(4.5 * 3)


def test_no_live_batch_gives_nulls_instead_of_a_made_up_quote(runs: Path) -> None:
    for path in runs.glob("results_synth_live*.json"):
        path.unlink()
    data = _data(_post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"}))
    q = data["quote"]
    assert q["basis"]["mode"] == "no_live_batch"
    assert all(v is None for v in q["estimate"].values() if not isinstance(v, str))
    assert q["basis"]["artifacts"] == []


def test_missing_dataset_artifact_is_named_404_not_500(runs: Path) -> None:
    (runs / "dataset_v1_frozen.json").unlink()
    resp = _post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"})
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "DATASET_NOT_FOUND"


# ---------------------------------------------------------------------------
# 5 模型归属不可证
# ---------------------------------------------------------------------------
def test_model_attribution_does_not_claim_evidence_it_does_not_have(runs: Path) -> None:
    data = _data(
        _post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen", "model": "deepseek-flash"})
    )
    ma = data["quote"]["model_attribution"]
    assert ma["requested_model"] == "deepseek-flash"
    assert ma["evidenced_by_basis"] is False, "观测批次 config 不自报 model ⇒ 不许写成已证"


# ---------------------------------------------------------------------------
# 6 真发起在 schema 面不可表达 ＋ 非法参数具名失败
# ---------------------------------------------------------------------------
def test_dry_run_false_is_invalid_request_not_a_new_error_code(runs: Path) -> None:
    resp = _post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen", "dry_run": False})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_REQUEST", "第 29 个码就是改判据（docs/02:1119）"


def test_the_false_branch_names_the_field_at_the_schema_level() -> None:
    """字段名点在哪一层：**DTO 面**（`detail` 在这里按 N-11 不下发，见下条对照）。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        EvalRunRequest.model_validate({"dataset_id": "ds_v1_frozen", "dry_run": False})
    assert [tuple(e["loc"]) for e in excinfo.value.errors()] == [("dry_run",)]


def test_validation_error_loses_detail_while_domain_error_keeps_it(runs: Path) -> None:
    """单变量对照：同一个 `platform_admin` 令牌，两种失败的 `detail` 面**不同且各有理由**。

    · `404 DATASET_NOT_FOUND` 在身份装配之后抛出 ⇒ `detail` 下发（角色在 `DETAIL_ROLES`）；
    · `400 INVALID_REQUEST` 在依赖解析阶段抛出 ⇒ 那时 `request.state` 还没有身份 ⇒ 按 N-11 缺省**不下发**。
      这不是缺陷，是"诊断面只给能处置它的人"；所以字段名点在第 2 条那个 schema 面。
    """
    client = _client(_token(Role.PLATFORM_ADMIN))
    ok_detail = _post(client, {"dataset_id": "ds_v9_nonexistent"}).json()
    assert ok_detail["detail"] == {"dataset_id": "ds_v9_nonexistent"}
    no_detail = _post(client, {"dataset_id": "ds_v1_frozen", "dry_run": False}).json()
    assert no_detail["detail"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"dataset_id": ""},
        {"dataset_id": "ds_v1_frozen", "max_cases": 20},
        {"dataset_id": "ds_v1_frozen", "confirm": True},
    ],
)
def test_illegal_bodies_fail_with_named_invalid_request(body: dict[str, Any], runs: Path) -> None:
    resp = _post(_client(_token(Role.PLATFORM_ADMIN)), body)
    assert resp.status_code == 400, f"{body} ⇒ {resp.status_code} {resp.text}"
    assert resp.json()["code"] == "INVALID_REQUEST"


def test_unknown_dataset_is_404(runs: Path) -> None:
    resp = _post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v9_nonexistent"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "DATASET_NOT_FOUND"


def test_tenant_or_user_query_params_change_nothing(runs: Path) -> None:
    client = _client(_token(Role.PLATFORM_ADMIN))
    base = _post(client, {"dataset_id": "ds_v1_frozen"}).json()
    forged = client.post(
        RUN_URL,
        params={"tenant_id": "T_B", "user_id": "u_other"},
        json={"dataset_id": "ds_v1_frozen"},
        headers=_auth(),
    ).json()
    forged.pop("trace_id", None)
    base.pop("trace_id", None)
    forged.pop("server_time", None)
    base.pop("server_time", None)
    assert forged == base, "身份只能来自 JWT：伪造查询参数不得改变任何一格"


# ---------------------------------------------------------------------------
# 7 零出站的两种证法
# ---------------------------------------------------------------------------
def test_eval_launch_imports_are_a_pinned_copy(runs: Path) -> None:
    source = Path(eval_launch.__file__).read_text(encoding="utf-8")
    touched: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            touched.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "eval_launch 不得用相对 import 绕过本臂"
            base = node.module or ""
            for alias in node.names:
                touched.add(f"{base}.{alias.name}" if base else alias.name)
    assert touched == EVAL_LAUNCH_IMPORTS, (
        f"预检模块的依赖面变了 ⇒ 多出 {sorted(touched - EVAL_LAUNCH_IMPORTS)}、"
        f"少了 {sorted(EVAL_LAUNCH_IMPORTS - touched)}；若确实需要新增依赖，先在本文件写明它不会出站"
    )


def test_endpoint_survives_a_blocked_network(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("预检端点不得发起任何 HTTP 请求")

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "request", _boom)
    monkeypatch.setattr(httpx.Client, "request", _boom)
    resp = _post(_client(_token(Role.PLATFORM_ADMIN)), {"dataset_id": "ds_v1_frozen"})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 8 两份抄本钉等值
# ---------------------------------------------------------------------------
def test_llm_node_copy_matches_the_graph_authority(runs: Path) -> None:
    from app.graph.build import _LLM_NODE_TASKS

    assert frozenset(_LLM_NODE_TASKS) == eval_launch.LLM_NODE_NAMES, (
        "`app.present` 是 L3、不能 import L4 的权威表 ⇒ 只能靠这条等值钉住；"
        "图里增减 LLM 节点而这里没跟，报价的条数就是错的"
    )


def test_dto_field_copy_matches_the_model(runs: Path) -> None:
    assert set(EvalRunRequest.model_fields) == CONTRACT_REQUEST_KEYS


# ---------------------------------------------------------------------------
# 9 限流桶 = admin（5/min），不是 read
# ---------------------------------------------------------------------------
def test_bucket_is_admin_and_sixth_call_is_rate_limited(runs: Path) -> None:
    client = _client(_token(Role.PLATFORM_ADMIN))
    for i in range(5):
        resp = _post(client, {"dataset_id": "ds_v1_frozen"})
        assert resp.status_code == 200, f"第 {i + 1} 次 ⇒ {resp.status_code} {resp.text}"
        assert resp.headers["X-RateLimit-Bucket"] == "admin"
        assert resp.headers["X-RateLimit-Limit"] == "5"
    sixth = _post(client, {"dataset_id": "ds_v1_frozen"})
    assert sixth.status_code == 429, sixth.text
    assert sixth.json()["code"] == "RATE_LIMITED"
    assert sixth.headers.get("Retry-After") == "60"


def test_endpoint_is_mounted_under_the_contract_path(runs: Path) -> None:
    app = FastAPI()
    app.include_router(admin_eval.router, prefix=API_PREFIX)
    assert f"{API_PREFIX}{ENDPOINT}" in app.openapi()["paths"], "§A.9.1 的路径形状是判据"
