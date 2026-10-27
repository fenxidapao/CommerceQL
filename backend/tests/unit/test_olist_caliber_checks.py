"""caliber 7 条判据的**正控**：每条都得能被一次注入打红。

为什么需要它（本窗自订，不在合并版 §6.2 的文件清单里）：
`gold_executable=10/10` 与 `caliber_match=10/10` 都只是**绿**；
一条永远返回 True 的判据也会给出同样的读数。本文件把"绿"变成"能被证明会红"。
判据本身在 `eval/olist/run_olist.py::check_case`，这里只注入、不改它。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO_ROOT / "eval"
OLIST_DIR = EVAL_DIR / "olist"
for _p in (str(REPO_ROOT), str(EVAL_DIR), str(OLIST_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval.olist import run_olist as R  # noqa: E402


@pytest.fixture(scope="module")
def bundle():
    from app.semantics.loader import load_bundle

    return load_bundle(str(REPO_ROOT / "semantic" / "bundle_olist_2018.yaml")).bundle


@pytest.fixture(scope="module")
def cases() -> dict[str, dict]:
    spec = R.load_cases(OLIST_DIR / "dataset_w1_gold10.yaml")
    return {case["case_id"]: case for case in spec["cases"]}


def _evaluate(case: dict, bundle) -> dict[str, bool]:
    return R.check_case(case, R.parse_sql(case["gold_sql"]), bundle)


def _mutate(case: dict, field: str, value) -> dict:
    mutated = dict(case)
    mutated[field] = value
    return mutated


def test_baseline_all_seven_green(cases, bundle) -> None:
    for case in cases.values():
        assert all(_evaluate(case, bundle).values()), case["case_id"]


@pytest.mark.parametrize(
    "judge,case_id,field,transform",
    [
        (
            "C1_assets",
            "g01",
            "gold_sql",
            lambda s: s.replace("v_o_payments", "v_o_unknown"),
        ),
        (
            "C2_columns",
            "g01",
            "gold_sql",
            lambda s: s.replace("p.payment_value", "p.nonexistent_col"),
        ),
        (
            "C3_time_basis",
            "g01",
            "gold_sql",
            lambda s: s.replace("order_purchase_timestamp", "order_approved_at"),
        ),
        (
            "C4_amount",
            "g01",
            "gold_sql",
            lambda s: s.replace("SUM(p.payment_value)", "SUM(p.payment_installments)"),
        ),
        (
            "C5_status",
            "g07",
            "gold_sql",
            lambda s: s.replace(
                "FROM v_o_orders AS o",
                "FROM v_o_orders AS o\nWHERE o.order_status NOT IN ('canceled','unavailable')",
            ),
        ),
        (
            "C6_tenant",
            "g01",
            "gold_sql",
            lambda s: s.replace(
                "WHERE o.order_status", "WHERE o.tenant_id = 'T_A' AND o.order_status"
            ),
        ),
        ("C7_metric", "g01", "metrics", lambda _: ["no_such_metric"]),
    ],
    ids=lambda v: str(v) if isinstance(v, str) else "",
)
def test_injection_turns_that_judge_red(
    judge: str, case_id: str, field: str, transform, cases, bundle
) -> None:
    original = cases[case_id][field]
    mutated = _mutate(cases[case_id], field, transform(original))
    assert _evaluate(mutated, bundle)[judge] is False
