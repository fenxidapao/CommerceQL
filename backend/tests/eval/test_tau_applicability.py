"""W77-2 / D-W77-1：条件性 τ 非适用豁免（fixture，零出站）。

守的五件事（与派单 §98.8-W77-2 一一对应）：
1. 证据缺失 ⇒ G-2/G-5/G-7 维持 UNVERIFIED；
2. `l4_decisions > 0` ⇒ 维持 UNVERIFIED；
3. `ambiguous_bindings > 0` ⇒ 维持 UNVERIFIED；
4. 三条件满足 ⇒ PASS + `tau_applicability=not_exercised` 标注；**G-8 不豁免**；
5. FAIL 不被豁免（τ 口径只挡"宣布通过"，不许洗白"没达标"）。

⚠️ 本文件只用 fixture 构造输入，不读 W77-1 产物、不调 LLM。
"""

from __future__ import annotations

from typing import Any

import gates as gt
import grid as g

_EVIDENCE = {"n_records": 166, "l4_decisions": 0, "ambiguous_bindings": 0}


def _inputs(passed: int = 25) -> dict[str, Any]:
    cases = [
        {"case_id": f"C{i}", "difficulty_struct": "easy", "difficulty_semantic": "low",
         "difficulty_struct_sitelabel": "easy"}
        for i in range(25)
    ]
    results = {
        c["case_id"]: {"scored": True, "passed": i < passed}
        for i, c in enumerate(cases)
    }
    return {
        "grid": g.build_grid(cases, results),
        "refusal": {"correct_refused": 24, "total": 24, "over_refused": 0,
                    "answerable_total": 100},
        "consistency": {"system_consistent": 5, "system_total": 5},
        "clarification": {"requests": 100, "clarified": 10, "clarify_then_correct": 9,
                          "second_round_loop_available": True},
        "tau_calibrated": False,
    }


def _by_id(gate_list: list[gt.Gate]) -> dict[str, gt.Gate]:
    return {x.gate_id: x for x in gate_list}


def test_missing_evidence_keeps_unverified() -> None:
    """没有 W77-1 证据 ⇒ 三格维持旧降级（fail-closed）。"""
    got = _by_id(gt.evaluate_gates(**_inputs()))
    for gate_id in ("G-2", "G-5", "G-7"):
        assert got[gate_id].verdict == "UNVERIFIED", gate_id
        assert not any("tau_applicability=not_exercised" in c for c in got[gate_id].caveats)


def test_l4_decisions_nonzero_keeps_unverified() -> None:
    """L4 真的参与过终判 ⇒ 前提不成立，豁免自动失效。"""
    evidence = {**_EVIDENCE, "l4_decisions": 1}
    got = _by_id(gt.evaluate_gates(**_inputs(), tau_applicability=evidence))
    for gate_id in ("G-2", "G-5", "G-7"):
        assert got[gate_id].verdict == "UNVERIFIED", gate_id


def test_ambiguous_bindings_nonzero_keeps_unverified() -> None:
    """存在 ambiguous 绑定 ⇒ 豁免自动失效。"""
    evidence = {**_EVIDENCE, "ambiguous_bindings": 1}
    got = _by_id(gt.evaluate_gates(**_inputs(), tau_applicability=evidence))
    for gate_id in ("G-2", "G-5", "G-7"):
        assert got[gate_id].verdict == "UNVERIFIED", gate_id


def test_incomplete_sample_keeps_unverified() -> None:
    """`n_records != 166` ⇒ 没跑全量就不是"本数据集不触发"。"""
    evidence = {**_EVIDENCE, "n_records": 165}
    got = _by_id(gt.evaluate_gates(**_inputs(), tau_applicability=evidence))
    for gate_id in ("G-2", "G-5", "G-7"):
        assert got[gate_id].verdict == "UNVERIFIED", gate_id


def test_three_conditions_keep_pass_with_annotation() -> None:
    """三条件满足 ⇒ G-2/G-5/G-7 的 PASS 不被降级，并强制带标注；G-8 仍 UNVERIFIED。"""
    got = _by_id(gt.evaluate_gates(**_inputs(), tau_applicability=_EVIDENCE))
    for gate_id in ("G-2", "G-5", "G-7"):
        assert got[gate_id].verdict == "PASS", gate_id
        notes = "；".join(got[gate_id].caveats)
        assert "tau_applicability=not_exercised" in notes, gate_id
        assert "τ 未校准；本数据集不触发 L4 决策；此标注不是 τ 校准证据" in notes, gate_id
    # G-8 不在豁免集合里：即使数字全达标，τ 未校准仍降 UNVERIFIED。
    assert got["G-8"].verdict == "UNVERIFIED"
    assert not any("tau_applicability=not_exercised" in c for c in got["G-8"].caveats)


def test_fail_is_not_exempted() -> None:
    """G-2 92% < 95% ⇒ FAIL；豁免只挡"宣布通过"，不挡"没达标"。"""
    got = _by_id(gt.evaluate_gates(**_inputs(passed=23), tau_applicability=_EVIDENCE))
    assert got["G-2"].verdict == "FAIL"
    assert not any("tau_applicability=not_exercised" in c for c in got["G-2"].caveats)
