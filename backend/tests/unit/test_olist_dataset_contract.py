"""Olist 60 题的结构契约（W2，`U-144`）。

锁的是**数据集本身**，不是 runner：
· 60 / 55 / 3 / 2；ID 唯一；W1 的 g01..g10 逐字承接（防已验收的 10/10 被悄悄改写）；
· execute 题的 metrics/assets 都能在薄语义包里解析；gold 只查 `v_o_*`、无 tenant_id；
· 逐题 C1–C7 全绿、每例 ≥1 行（负控需要非空 gold）；
· 4×3 每格 ≥1；9 个指标每类 ≥5；
· 源 YAML 的两个 stamp 与复算一致；篡改 question/expect/metrics/assets 时
  `full_hash` 必变（`content_hash` 只盖 10 个共享字段，不盖 expect/metrics/assets）。
"""

from __future__ import annotations

import copy
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OLIST_DIR = REPO_ROOT / "eval" / "olist"
BUNDLE_PATH = REPO_ROOT / "semantic" / "bundle_olist_2018.yaml"
SANDBOX_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "data" / "generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402
from eval.olist.hashing import case_full_hash, read_stamps  # noqa: E402

RECONCILE_FIELDS = (
    "question", "gold_sql", "metrics", "assets", "expect", "business_knowledge_required",
)
SEMS = ("low", "medium", "high")
LEVELS = ("easy", "medium", "hard", "extra")


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load((OLIST_DIR / "dataset_v1.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def annotated(spec) -> list[dict]:
    return R.load_annotated_cases(OLIST_DIR / "dataset_v1.yaml")["cases"]


@pytest.fixture(scope="module")
def bundle():
    from app.semantics.loader import load_bundle

    return load_bundle(str(BUNDLE_PATH)).bundle


def test_counts_and_ids(spec) -> None:
    cases = spec["cases"]
    behaviors = Counter(str(c.get("expected_behavior")) for c in cases)
    assert behaviors == {"execute": 55, "clarify": 3, "refuse": 2}
    assert len(cases) == 60
    ids = [str(c["case_id"]) for c in cases]
    assert len(ids) == len(set(ids))
    assert ids[:10] == [f"g{i:02d}" for i in range(1, 11)]
    assert ids[10:55] == [f"o{i:02d}" for i in range(1, 46)]
    assert ids[55:] == ["c01", "c02", "c03", "r01", "r02"]


def test_w1_gold10_is_carried_over_verbatim(spec) -> None:
    w1 = yaml.safe_load((OLIST_DIR / "dataset_w1_gold10.yaml").read_text(encoding="utf-8"))
    new = {str(c["case_id"]): c for c in spec["cases"]}
    for old in w1["cases"]:
        carried = new[str(old["case_id"])]
        for field in RECONCILE_FIELDS:
            # W1 YAML 没有 `business_knowledge_required` ⇒ 两边都归一为 []。
            assert (old.get(field) or []) == (carried.get(field) or []), (
                old["case_id"], field
            )


def test_execute_declarations_resolve_in_bundle(annotated, bundle) -> None:
    assets = {a.logical_name for a in bundle.assets}
    metrics = {m.name for m in bundle.metrics}
    for case in annotated:
        if (case.get("expected_behavior") or "execute") != "execute":
            assert case.get("metrics") == [] and case.get("assets") == [], case["case_id"]
            continue
        assert set(case["metrics"]) <= metrics, case["case_id"]
        assert set(case["assets"]) <= assets, case["case_id"]


def test_gold_sql_uses_only_tenant_views(annotated) -> None:
    for case in annotated:
        sql = case.get("gold_sql")
        if not sql:
            continue
        lowered = sql.lower()
        assert "tenant_id" not in lowered, case["case_id"]
        assert "v_o_" in lowered, case["case_id"]
        for forbidden in (" from orders", " from payments", " from order_items"):
            assert forbidden not in lowered, case["case_id"]


def test_every_execute_case_passes_c1_c7(annotated, bundle) -> None:
    for case in annotated:
        if (case.get("expected_behavior") or "execute") != "execute":
            continue
        checks = R.check_case(case, R.parse_sql(case["gold_sql"]), bundle)
        assert all(checks.values()), (case["case_id"], checks)


def test_every_execute_gold_returns_rows(annotated) -> None:
    if not SANDBOX_DB.is_file():
        pytest.skip(f"sandbox_db_absent: {SANDBOX_DB}")
    report = R.run(OLIST_DIR / "dataset_v1.yaml", SANDBOX_DB)
    empty = [
        record["case_id"] for record in report["cases"]
        if (record.get("expected_behavior") or "execute") == "execute"
        and not record.get("rows")
    ]
    assert not empty, empty
    assert report["gold_executable"] == report["caliber_match"] == 55


def test_grid_has_every_cell_and_metric_coverage(annotated) -> None:
    execute = [c for c in annotated if (c.get("expected_behavior") or "execute") == "execute"]
    grid = Counter((c["difficulty_struct"], c["difficulty_semantic"]) for c in execute)
    missing = [
        (level, sem) for level in LEVELS for sem in SEMS if grid.get((level, sem), 0) < 1
    ]
    assert not missing, missing
    for case in execute:
        assert case["difficulty_struct"] in LEVELS, case["case_id"]
        assert case["difficulty_semantic"] in SEMS, case["case_id"]

    per_metric = Counter(m for c in execute for m in c["metrics"])
    thin = {
        name: per_metric.get(name, 0)
        for name in (
            "gmv", "order_cnt", "order_cnt_all", "aov", "item_gmv",
            "freight_total", "item_cnt", "avg_review_score", "delivery_late_rate",
        )
        if per_metric.get(name, 0) < 5
    }
    assert not thin, thin


def test_shape_and_dimension_coverage(annotated) -> None:
    execute = [c for c in annotated if (c.get("expected_behavior") or "execute") == "execute"]
    sqls = [str(c["gold_sql"]).upper() for c in execute]
    assert any("GROUP BY" not in sql for sql in sqls), "缺 scalar"
    assert any("GROUP BY" in sql for sql in sqls), "缺 group-by"
    assert any("LIMIT" in sql for sql in sqls), "缺 Top-N"
    assert any("HAVING" in sql for sql in sqls), "缺 HAVING"
    assert any(sql.count("SELECT") > 1 for sql in sqls), "缺子查询"
    assert any(len(c.get("metrics") or []) > 1 for c in execute), "缺多指标"

    joined = " ".join(sqls)
    for token in ("CUSTOMER_STATE", "PRODUCT_CATEGORY", "ORDER_STATUS", "STRFTIME"):
        assert token in joined, f"维度未覆盖：{token}"


def test_two_source_stamps_match_recomputation(spec) -> None:
    stamps = read_stamps(OLIST_DIR / "dataset_v1.yaml")
    assert stamps["content_hash"] == bfs.case_content_hash(spec["cases"])
    assert stamps["full_hash"] == case_full_hash(spec["cases"])


@pytest.mark.parametrize(
    "field,must_change_content",
    [
        ("question", True),
        ("expect", False),
        ("metrics", False),
        ("assets", False),
    ],
)
def test_tamper_is_caught_by_full_hash(spec, field: str, must_change_content: bool) -> None:
    original = copy.deepcopy(spec)
    tampered = copy.deepcopy(spec)
    target = tampered["cases"][20]
    if field == "metrics":
        target[field] = [target[field][0]]
        target[field][0] = "order_cnt" if target[field][0] != "order_cnt" else "gmv"
    elif field == "assets":
        target[field] = [target[field][0]]
        target[field][0] = "review" if target[field][0] != "review" else "order"
    elif field == "expect":
        target[field]["time_filtered"] = not target[field]["time_filtered"]
    else:
        target[field] = str(target[field]) + "（篡改）"

    content_changed = (
        bfs.case_content_hash(tampered["cases"]) != bfs.case_content_hash(original["cases"])
    )
    full_changed = case_full_hash(tampered["cases"]) != case_full_hash(original["cases"])
    assert full_changed, f"{field} 没有被 full_hash 覆盖"
    assert content_changed is must_change_content, field
