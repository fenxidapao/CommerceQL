"""B6 多轮 runner 的离线契约（零 LLM、零出站、零数据库）。

只钉四件事：
1. 数据集自检（15 条 × 2 轮、content_hash、追问启发式）现算成立；
2. `compare_expectation` 的判定口径（集合归一、时间窗、缺失计划、未映射键）；
3. turn1 / turn2 分开计数 —— 不把两轮混成一个准确率；
4. `--replay` 能在没有 Harness 的情况下重打分（live 读数落盘后可零成本复核）。
"""

from __future__ import annotations

from typing import Any

import multiturn
import pytest
import run_multiturn


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return multiturn.load_dataset()


def _summary(expect: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": list(expect.get("metrics") or []),
        "dimensions": list(expect.get("dimensions") or []),
        "filters": list(expect.get("filters") or []),
        "grain": expect.get("grain"),
        "time_range": {"start": expect.get("time_start"), "end": expect.get("time_end")},
        "order_by": list(expect.get("order_by") or []),
        "limit": expect.get("limit"),
        "blocked": False,
    }


def _perfect_payload(spec: dict[str, Any]) -> dict[str, Any]:
    records = []
    for case in spec["cases"]:
        turns = [
            {
                "question": turn["question"],
                "expect": turn["expect"],
                "plan_summary": _summary(turn["expect"]),
                "terminal_event": "complete",
                "cost_cny": 0.001,
            }
            for turn in case["turns"]
        ]
        records.append(
            {
                "case_id": case["case_id"],
                "follow_up_type": case["follow_up_type"],
                "turns": turns,
            }
        )
    return {
        "dataset_content_hash": spec["content_hash"],
        "dataset_cases": spec["cases"],
        "records": records,
    }


def test_dataset_hash_shape_and_heuristic(spec: dict[str, Any]) -> None:
    check = multiturn.verify_dataset(spec)
    assert check["ok"], check
    assert check["n_cases"] == multiturn.EXPECTED_CASES == 15
    assert check["content_hash"]["actual"] == spec["content_hash"]
    assert all(len(case["turns"]) == multiturn.EXPECTED_TURNS for case in spec["cases"])


def test_compare_exact_expectation_passes(spec: dict[str, Any]) -> None:
    expect = spec["cases"][0]["turns"][0]["expect"]
    result = multiturn.compare_expectation(expect, _summary(expect))
    assert result["passed"] is True
    assert result["plan_present"] is True
    assert set(result["fields"]) == {
        "metrics", "dimensions", "time_start", "time_end",
    }
    assert result["unmapped"] == {}


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("metrics", {"metrics": ["order_cnt"]}),
        ("dimensions", {"dimensions": ["customer_state"]}),
        ("time_end", {"time_range": {"start": "2018-01-01", "end": "2018-12-31"}}),
    ],
)
def test_compare_detects_mismatch(
    spec: dict[str, Any], field: str, mutate: dict[str, Any]
) -> None:
    expect = spec["cases"][0]["turns"][0]["expect"]
    summary = {**_summary(expect), **mutate}
    result = multiturn.compare_expectation(expect, summary)
    assert result["passed"] is False
    assert result["fields"][field]["ok"] is False


def test_unmapped_expect_key_is_reported_not_scored(spec: dict[str, Any]) -> None:
    # mt05 的 comparison 在 PlanSummary 里没有承载位：必须上报，不能静默丢弃。
    case = next(case for case in spec["cases"] if case["case_id"] == "mt05")
    expect = case["turns"][1]["expect"]
    result = multiturn.compare_expectation(expect, _summary(expect))
    assert result["unmapped"] == {"comparison": "2017"}
    assert result["passed"] is True


def test_missing_plan_is_never_a_pass(spec: dict[str, Any]) -> None:
    expect = spec["cases"][0]["turns"][0]["expect"]
    result = multiturn.compare_expectation(expect, None)
    assert result["passed"] is False
    assert result["plan_present"] is False
    assert result["fields"]["metrics"]["ok"] is False
    assert result["fields"]["time_start"]["actual"] is None


def test_time_caliber_day_granularity_and_exclusive_upper() -> None:
    """U-157：时间面按日粒度比，`… 23:59:59` 抬次日与金标右开同口径。

    这四条是**新口径的正/反控制**：① 时分秒差不再判不等；② 闭区间上界归一后与右开
    金标相等；③ `T` 分隔同样归一；④ 纯日期上界**不抬**（U-165 撤回，仍按字面比、不猜）（`2018-12-31` ≠ `2019-01-01`，
    仍判不等）—— 少了第 ④ 条，改动就会退化成「时间面永远通过」。
    """
    assert multiturn.time_field_ok("time_start", "2018-01-01", "2018-01-01 00:00:00") is True
    assert multiturn.time_field_ok("time_end", "2019-01-01", "2018-12-31 23:59:59") is True
    assert multiturn.time_field_ok("time_end", "2019-01-01", "2018-12-31T23:59:59") is True
    # U-165 撤回（2026-11-09）：纯日期「抬次日」这条放弃 —— 它与本文件 `time_end-mutate2`
    # （同一 mutate 必须判 False）直接互斥，且 `timeexpr.py:227-234` 只描述 resolve_time
    # 的产出格式、不构成「计划裸日期 = 闭区间」的契约。评测口径变更属红线，须书面裁定；
    # 在此之前按字面比、不猜。
    assert multiturn.time_field_ok("time_end", "2019-01-01", "2018-12-31") is False
    assert multiturn.time_field_ok("time_start", "2018-01-01", None) is False


def test_history_sanitizer_matches_production() -> None:
    """镜像必须与 `app/api/runner._sanitize_history_plan` 等价（eval 不许 import app.api）。"""
    from app.api.runner import _sanitize_history_plan

    samples = [
        None,
        {},
        {"metrics": ["gmv"], "dimensions": [], "grain": " ", "limit": 0},
        {
            "metrics": ["gmv", "  order_cnt  ", 3],
            "dimensions": ["customer_state"] * 25,
            "filters": ["customer_state = 'SP'"],
            "grain": "month",
            "time_range": {"start": "2018-01-01", "end": "2019-01-01", "expr": "2018"},
            "order_by": ["gmv desc"],
            "limit": 5,
            "blocked": True,
        },
        {"limit": True, "time_range": {"start": 2018}},  # 布尔/非字符串一律丢弃
    ]
    for sample in samples:
        assert multiturn.sanitize_history_plan(sample) == _sanitize_history_plan(sample)


def test_history_seed_drops_empty_fields_like_production(spec: dict[str, Any]) -> None:
    summary = {
        "metrics": ["gmv"],
        "dimensions": [],
        "filters": [],
        "grain": "month",
        "time_range": {"start": "2018-01-01", "end": "2019-01-01"},
        "order_by": [],
        "limit": None,
        "blocked": False,
    }
    history = multiturn.history_plan_from_summary(summary)
    assert history == {
        "metrics": ["gmv"],
        "grain": "month",
        "time_range": {"start": "2018-01-01", "end": "2019-01-01"},
    }


def test_turn_counts_are_separate(spec: dict[str, Any]) -> None:
    payload = _perfect_payload(spec)
    payload["records"][0]["turns"][1]["plan_summary"]["metrics"] = ["aov"]
    result = run_multiturn.replay_records(payload)
    summary = result["summary"]
    assert summary["n_cases"] == 15
    assert summary["turn1_passed"] == 15
    assert summary["turn2_passed"] == 14
    assert summary["cases_both_passed"] == 14
    assert summary["unmapped_expect_keys"] == ["comparison"]
    assert summary["cost_cny_total"] == pytest.approx(0.03)


def test_replay_rejects_dataset_hash_mismatch(spec: dict[str, Any]) -> None:
    payload = _perfect_payload(spec)
    payload["dataset_content_hash"] = "sha256:not-the-dataset"
    with pytest.raises(ValueError, match="数据集哈希不符"):
        run_multiturn.replay_records(payload)


def test_cli_check_mode_needs_no_harness(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_multiturn.main(["--check"]) == 0
    assert "数据集自检：通过" in capsys.readouterr().out


def test_cli_live_without_yes_does_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_multiturn.main(["--live"]) == 0
    assert "未带 --yes" in capsys.readouterr().err
