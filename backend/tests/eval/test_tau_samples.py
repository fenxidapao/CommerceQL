"""C2：τ 采样 schema —— gold 反解 + `ScoreSample` 派生的**离线**契约（W8 第 65 轮；零出站）。

## 本文件钉的三件事（对应 QA §86.2-2 的三条点句）

| 点句 | 钉法 |
|---|---|
| 候选 ID 用**稳定键**（禁下标），顺序另存 `rank` | 派生器按 id 对齐；**换一次候选顺序**后仍得到同一份样本 |
| gold 由 `gold_sql` **反解**，匹配不上写 `null`+`reason`，**不许猜** | 无反解 / 多命中 / 空 gold / 无候选，四类各一条，全部 `unmatched` |
| raw 与 `ScoreSample` **双落** | record 侧 raw 保留全部原始字段；样本由 `build_score_samples` 派生，不反向回写 |

🔴 **最容易犯的错**：把 `unmatched` 当成 `gold_candidate_id=None` 的"该澄清"样本。
本文件用 `test_unmatched_gold_is_skipped_not_treated_as_should_clarify` 专门钉住它。
"""

from __future__ import annotations

from typing import Any

import pytest

from eval.runner import _gold_for_tau
from eval.tau_samples import (
    build_score_samples,
    candidate_ids_of,
    coverage_summary,
    summarize,
)


def _tau_record(
    case_id: str,
    *,
    candidate_ids: list[str],
    scores: list[float],
    gold_status: str = "matched",
    gold_candidate_id: str | None = None,
    gold_unmatched_reason: str | None = None,
    ok: bool = True,
) -> dict[str, Any]:
    rank = [
        cid for cid, _ in sorted(zip(candidate_ids, scores), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "case_id": case_id,
        "tau_raw": {
            "schema": "W8_TAU_RAW/v1",
            "source": "bind.l4",
            "ok": ok,
            "reason": None,
            "candidate_ids": candidate_ids,
            "scores": scores,
            "rank": rank,
            "scorer": {"model_id": "deepseek-flash", "prompt_version": "l4_score_v1"},
            "gold_status": gold_status,
            "gold_candidate_id": gold_candidate_id,
            "gold_unmatched_reason": gold_unmatched_reason,
            "gold_sql_present": True,
            "gold_sql_sha256": "0" * 64,
        },
    }


# ---------------------------------------------------------------------------
# 1. gold 反解（runner._gold_for_tau）
# ---------------------------------------------------------------------------


def test_gold_single_column_hit_is_matched() -> None:
    case = {"gold_sql": "SELECT sum(pay_amount) FROM v_order_paid WHERE pay_status = 'paid'"}
    gold = _gold_for_tau(case, "execute", ["v_order_paid.pay_amount", "v_order_paid.order_cnt"])
    assert gold["gold_status"] == "matched"
    assert gold["gold_candidate_id"] == "v_order_paid.pay_amount"
    assert gold["gold_unmatched_reason"] is None
    assert gold["gold_sql_present"] is True
    assert len(gold["gold_sql_sha256"]) == 64


def test_gold_prefers_the_aggregate_argument_over_filter_columns() -> None:
    """过滤列与**被测字段**同时出现在 SQL 里时，只认聚合参数里的那一列。

    这是初版规则的实测病根：`pay_status`/`pay_time` 这类过滤列会把"唯一命中"挤成多命中，
    119 条已打分记录里 75 条因此被判 `multiple_candidates_match`。
    """
    case = {
        "gold_sql": (
            "SELECT sum(pay_amount) FROM v_order_paid "
            "WHERE pay_status = 'paid' AND pay_time >= '2026-08-01'"
        )
    }
    gold = _gold_for_tau(
        case,
        "execute",
        ["v_order_paid.pay_amount", "v_order_paid.pay_status", "v_order_paid.pay_time"],
    )
    assert gold["gold_status"] == "matched"
    assert gold["gold_candidate_id"] == "v_order_paid.pay_amount"
    assert gold["gold_match_rule"] == "aggregate_arg"


def test_gold_uses_the_from_join_table_to_disambiguate_same_column_name() -> None:
    """同名同列在两套资产里都出现 ⇒ 用 gold_sql 的 `FROM` 表收敛（**不是**挑一个更像的）。"""
    case = {"gold_sql": "SELECT COUNT(spu_id) FROM v_product WHERE on_sale = 1"}
    gold = _gold_for_tau(
        case, "execute", ["v_product.spu_id", "v_dim_product.spu_id"]
    )
    assert gold["gold_status"] == "matched"
    assert gold["gold_candidate_id"] == "v_product.spu_id"

    # 🔴 W8 第 66 轮 C2-1 订正：表名不在候选的资产前缀里 ⇒ **作用域为空** ⇒
    # 按新规则①**不再回退全候选**，而是判 `gold_table_not_in_candidates`。
    # （旧规则回退全候选后才落到"多命中"，那正是 QA §87.2 指出的假匹配来源。）
    ambiguous = _gold_for_tau(
        {"gold_sql": "SELECT COUNT(spu_id) FROM v_unknown WHERE on_sale = 1"},
        "execute",
        ["v_product.spu_id", "v_dim_product.spu_id"],
    )
    assert ambiguous["gold_status"] == "unmatched"
    assert ambiguous["gold_unmatched_reason"] == "gold_table_not_in_candidates"


def test_gold_count_star_has_no_measurable_field() -> None:
    """QA §87.3-①-② 第一例：`COUNT(*)` **无参数列** ⇒ 无可反解的被测字段 ⇒ unmatched。

    🔴 这条是本轮返工的**核心病根**：旧正则把 `*` 排除在参数之外，于是 `COUNT(*)`
    与"聚合参数找不到"混成同一条路；而旧规则的兜底又会把过滤列顶上来当金标。
    """
    gold = _gold_for_tau(
        {"gold_sql": "SELECT COUNT(*) FROM v_product WHERE on_sale = 1"},
        "execute",
        ["v_product.spu_id", "v_product.on_sale", "v_order_paid.pay_amount"],
    )
    assert gold["gold_status"] == "unmatched"
    assert gold["gold_candidate_id"] is None
    assert gold["gold_unmatched_reason"] == "no_target_column"
    # `COUNT(*)` 的存在被显式记下来（不是"没找到"，是"结构上没有"）
    assert gold["gold_has_star_agg"] is True


def test_gold_count_distinct_takes_the_distinct_column() -> None:
    """QA §87.3-①-② 第二例：`COUNT(DISTINCT x)` ⇒ 目标列是 `x`（不是 `*`、不是 `COUNT`）。"""
    gold = _gold_for_tau(
        {"gold_sql": "SELECT COUNT(DISTINCT sub_order_id) FROM v_order_paid WHERE pay_time >= '2026-08-01'"},
        "execute",
        ["v_order_paid.sub_order_id", "v_order_paid.order_id", "v_order_paid.pay_time"],
    )
    assert gold["gold_status"] == "matched"
    assert gold["gold_candidate_id"] == "v_order_paid.sub_order_id"
    assert gold["gold_match_rule"] == "aggregate_arg"
    assert gold["gold_has_star_agg"] is False


def test_gold_never_picks_a_filter_column_just_because_it_appears() -> None:
    """QA §87.3-①-③ 第三例：过滤列与被测列**同名**时，不许靠"在 gold_sql 里出现过"命中。

    这条是 §87.2 的核心指控：`category_l1`（过滤/分组列）与金标同名前缀时，
    旧规则的全文兜底会把它当被测字段 ⇒ 金标分数低于次优 ⇒ τ 校到错位置。
    """
    gold = _gold_for_tau(
        {
            "gold_sql": (
                "SELECT category_l1, SUM(pay_amount) FROM v_order_paid "
                "WHERE category_l1 = '家电' GROUP BY category_l1"
            )
        },
        "execute",
        [
            "v_order_paid.pay_amount",
            "v_order_paid.category_l1",
            "v_order_paid.pay_time",
        ],
    )
    # 唯一命中必须是聚合参数列 `pay_amount`，**不是**同名的 `category_l1`
    assert gold["gold_status"] == "matched"
    assert gold["gold_candidate_id"] == "v_order_paid.pay_amount"

    # 若聚合参数列压根不在候选里 ⇒ 判 unmatched，**不**回退去挑那个出现过的过滤列
    fallback = _gold_for_tau(
        {
            "gold_sql": (
                "SELECT category_l1, SUM(pay_amount) FROM v_order_paid GROUP BY category_l1"
            )
        },
        "execute",
        ["v_order_paid.category_l1", "v_order_paid.pay_time"],
    )
    assert fallback["gold_status"] == "unmatched"
    assert fallback["gold_unmatched_reason"] == "no_column_overlap"


def test_gold_table_not_in_candidates_does_not_fall_back_to_all() -> None:
    """QA §87.3-①-① 第四例：gold 表不在候选资产内 ⇒ **不回退全候选**。

    实例（QA §87.2 点名的 `M-HIER-03`）：gold_sql 是 `SELECT city, COUNT(*) FROM v_shop`，
    而 `v_shop.city` 根本不在候选集（候选只有 `v_order_paid`/`v_order_refund`/`v_product`）
    ⇒ 旧规则回退全候选后把金标判成 `v_order_paid.category_l1`（0.02 分、排名 12）。
    """
    gold = _gold_for_tau(
        {"gold_sql": "SELECT city, COUNT(*) FROM v_shop"},
        "execute",
        [
            "v_order_paid.category_l1",
            "v_order_paid.pay_amount",
            "v_product.spu_id",
        ],
    )
    assert gold["gold_status"] == "unmatched"
    assert gold["gold_candidate_id"] is None
    assert gold["gold_unmatched_reason"] == "gold_table_not_in_candidates"


def test_gold_does_not_fall_back_to_group_by_column_across_assets() -> None:
    """`GROUP BY` 的维度列**不**作兜底：同列名跨资产会假匹配。

    `SELECT v_shop.shop_id, COUNT(*) FROM v_order_paid JOIN v_shop ...` 的
    `v_shop.shop_id` 若拿列名去命中，会撞上 `v_order_paid.shop_id`（同列名、错资产）。
    """
    gold = _gold_for_tau(
        {
            "gold_sql": (
                "SELECT v_shop.shop_id, COUNT(*) FROM v_order_paid "
                "JOIN v_shop ON v_order_paid.shop_id = v_shop.shop_id "
                "GROUP BY v_shop.shop_id"
            )
        },
        "execute",
        ["v_order_paid.shop_id", "v_order_paid.pay_amount"],
    )
    # `COUNT(*)` ⇒ 无被测字段 ⇒ unmatched（**不是** `v_order_paid.shop_id`）
    assert gold["gold_status"] == "unmatched"
    assert gold["gold_candidate_id"] is None
    assert gold["gold_unmatched_reason"] == "no_target_column"


def test_gold_expected_clarify_is_its_own_status_not_unmatched() -> None:
    """该澄清题：`gold_candidate_id=None` 但状态是 `expected_clarify`（安全侧样本）。"""
    gold = _gold_for_tau({"gold_sql": ""}, "clarify", ["a.x", "b.y"])
    assert gold["gold_status"] == "expected_clarify"
    assert gold["gold_candidate_id"] is None
    assert gold["gold_unmatched_reason"] is None


@pytest.mark.parametrize(
    ("case", "candidates", "expected", "reason"),
    [
        ({"gold_sql": ""}, ["a.x", "b.y"], "execute", "empty_gold_sql"),
        # 🔴 W8 第 66 轮 C2-1 订正：`COUNT(*)` **无参数列** ⇒ 没有可反解的被测字段
        # ⇒ `no_target_column`（旧规则会落到 `no_column_overlap`，两者是不同的病）。
        # ⚠️ 作用域要先判：`v_dim_date` 不在候选资产 `a` 里 ⇒ 命中的是①的
        # `gold_table_not_in_candidates`；要让②生效，gold 表必须在候选资产内。
        (
            {"gold_sql": "SELECT count(*) FROM v_dim_date WHERE year = 2026"},
            ["v_dim_date.year", "v_dim_date.month"],
            "execute",
            "no_target_column",
        ),
        # 作用域为空（gold 表不在候选资产内）⇒ 新 reason
        (
            {"gold_sql": "SELECT count(spu_id) FROM v_unknown"},
            ["v_product.spu_id"],
            "execute",
            "gold_table_not_in_candidates",
        ),
        (
            # 没有聚合函数 ⇒ 没有可反解的被测字段 ⇒ `no_target_column`
            # （旧规则会靠"列名在 gold_sql 出现过"兜底，撞上 `t.a`／`t.b` 两条）
            {"gold_sql": "SELECT a, b FROM t"},
            ["t.a", "t.b"],
            "execute",
            "no_target_column",
        ),
        (
            # 作用域内**两个**候选列名都等于聚合参数列 ⇒ 不挑一个更像的，判 unmatched
            {"gold_sql": "SELECT sum(a) FROM t JOIN u ON t.id = u.id"},
            ["t.a", "u.a"],
            "execute",
            "multiple_candidates_match",
        ),
        ({"gold_sql": "SELECT amount FROM t"}, [], "execute", "no_l4_candidates"),
    ],
)
def test_gold_never_guesses(
    case: dict[str, Any], candidates: list[str], expected: str, reason: str
) -> None:
    """四类反解失败一律 `unmatched` + 具名 reason，**不挑一个更像的**。"""
    gold = _gold_for_tau(case, expected, candidates)
    assert gold["gold_status"] == "unmatched"
    assert gold["gold_candidate_id"] is None
    assert gold["gold_unmatched_reason"] == reason


def test_second_round_gold_is_not_defined_rather_than_should_clarify() -> None:
    """二轮问句带补答 ⇒ gold 未定义（**不是** `expected_clarify`），派生器必须跳过。

    这是最隐蔽的一类假样本：clarify 用例的二轮明明答出了 complete，
    若沿用首轮 gold（`expected_clarify`），校准会把它读成"本该澄清"。
    """
    class _Run:
        l4_raw = {
            "schema": "W8_TAU_RAW/v1",
            "ok": True,
            "candidate_ids": ["v_order_paid.pay_amount", "v_order_paid.receiver_city"],
            "scores": [0.7, 0.6],
            "rank": ["v_order_paid.pay_amount", "v_order_paid.receiver_city"],
            "scorer": {"model_id": "deepseek-flash", "prompt_version": "l4_score_v1"},
        }

    from eval.runner import GOLD_NOT_DEFINED_SECOND_ROUND, _tau_raw

    raw = _tau_raw(_Run(), {"gold_sql": ""}, "clarify", second_round=True)
    assert raw["gold_status"] == GOLD_NOT_DEFINED_SECOND_ROUND
    assert raw["gold_candidate_id"] is None
    assert raw["gold_unmatched_reason"] == "second_round_question_changed"

    records = [{"case_id": "C-9", "tau_raw": raw} for _ in range(3)]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert samples == []
    assert skips[0]["reason"] == "gold_missing"


# ---------------------------------------------------------------------------
# 2. 派生器（eval/tau_samples.build_score_samples）
# ---------------------------------------------------------------------------


def test_three_repeats_become_one_sample() -> None:
    records = [
        _tau_record("C-1", candidate_ids=["t.a", "t.b"], scores=[0.9, 0.2], gold_candidate_id="t.a"),
        _tau_record("C-1", candidate_ids=["t.a", "t.b"], scores=[0.8, 0.3], gold_candidate_id="t.a"),
        _tau_record("C-1", candidate_ids=["t.a", "t.b"], scores=[0.85, 0.25], gold_candidate_id="t.a"),
    ]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert skips == []
    assert len(samples) == 1
    sample = samples[0]
    assert sample.sample_id == "C-1"
    assert sample.candidate_ids == ("t.a", "t.b")
    assert sample.repeats == ((0.9, 0.2), (0.8, 0.3), (0.85, 0.25))
    assert sample.gold_candidate_id == "t.a"


def test_candidate_order_does_not_change_the_sample() -> None:
    """**禁下标**的实证：第二轮把候选顺序反过来，样本的分数向量必须仍按 id 对齐。"""
    records = [
        _tau_record("C-2", candidate_ids=["t.a", "t.b"], scores=[0.9, 0.2], gold_candidate_id="t.a"),
        _tau_record("C-2", candidate_ids=["t.b", "t.a"], scores=[0.2, 0.9], gold_candidate_id="t.a"),
        _tau_record("C-2", candidate_ids=["t.a", "t.b"], scores=[0.7, 0.4], gold_candidate_id="t.a"),
    ]
    samples, _ = build_score_samples(records, min_repeats=3)
    assert len(samples) == 1
    assert samples[0].candidate_ids == ("t.a", "t.b")
    assert samples[0].repeats == ((0.9, 0.2), (0.9, 0.2), (0.7, 0.4))


def test_unmatched_gold_is_skipped_not_treated_as_should_clarify() -> None:
    """🔴 关键一条：反解不上 = **跳过**，绝不能落成 `gold_candidate_id=None`（那会被读成"该澄清"）。"""
    records = [
        _tau_record(
            "C-3",
            candidate_ids=["t.a", "t.b"],
            scores=[0.9, 0.2],
            gold_status="unmatched",
            gold_unmatched_reason="no_column_overlap",
        )
        for _ in range(3)
    ]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert samples == []
    assert skips == [
        {"sample_id": "C-3", "reason": "gold_unmatched", "gold_unmatched_reason": "no_column_overlap"}
    ]


def test_expected_clarify_gold_is_none_but_kept() -> None:
    records = [
        _tau_record(
            "C-4", candidate_ids=["t.a", "t.b"], scores=[0.5, 0.5], gold_status="expected_clarify"
        )
        for _ in range(3)
    ]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert skips == []
    assert len(samples) == 1
    assert samples[0].gold_candidate_id is None


def test_candidate_set_drift_is_skipped_with_a_reason() -> None:
    records = [
        _tau_record("C-5", candidate_ids=["t.a", "t.b"], scores=[0.9, 0.2], gold_candidate_id="t.a"),
        _tau_record("C-5", candidate_ids=["t.a", "t.c"], scores=[0.9, 0.2], gold_candidate_id="t.a"),
        _tau_record("C-5", candidate_ids=["t.a", "t.b"], scores=[0.9, 0.2], gold_candidate_id="t.a"),
    ]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert samples == []
    assert skips[0]["reason"] == "candidate_set_unstable"


def test_single_candidate_is_not_a_calibration_sample() -> None:
    """单候选不构成分差问题（`ScoreSample.__post_init__` 的既有约束）⇒ 跳过并说明。"""
    records = [
        _tau_record("C-6", candidate_ids=["t.a"], scores=[0.9], gold_candidate_id="t.a")
        for _ in range(3)
    ]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert samples == []
    assert skips[0]["reason"] == "single_candidate"


def test_insufficient_repeats_is_counted_not_hidden() -> None:
    """单次跑批 = 1 次重复 ⇒ 0 样本，且必须能回答"为什么是 0"。"""
    records = [
        _tau_record("C-7", candidate_ids=["t.a", "t.b"], scores=[0.9, 0.2], gold_candidate_id="t.a")
    ]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert samples == []
    assert skips == [
        {"sample_id": "C-7", "reason": "insufficient_repeats", "usable": 1, "required": 3, "total_records": 1}
    ]


def test_raw_is_kept_verbatim_and_rank_is_order_by_score() -> None:
    """raw 与样本双落：原始记录不被改写，且 `rank` 是分数降序（稳定序断平）。"""
    record = _tau_record(
        "C-8", candidate_ids=["t.a", "t.b", "t.c"], scores=[0.3, 0.9, 0.3], gold_candidate_id="t.b"
    )
    before = {k: list(v) if isinstance(v, list) else v for k, v in record["tau_raw"].items()}
    samples, _ = build_score_samples([record] * 3, min_repeats=3)
    assert samples and samples[0].gold_candidate_id == "t.b"
    assert record["tau_raw"]["rank"] == ["t.b", "t.a", "t.c"], "同分按 id 字典序断平"
    assert {k: v for k, v in record["tau_raw"].items()} == before, "raw 不得被派生器改写"
    assert candidate_ids_of(record) == ["t.a", "t.b", "t.c"]


def test_coverage_and_summary_expose_the_denominator() -> None:
    records = [
        *[
            _tau_record("A", candidate_ids=["t.a", "t.b"], scores=[0.9, 0.1], gold_candidate_id="t.a")
            for _ in range(3)
        ],
        *[
            _tau_record(
                "B",
                candidate_ids=["t.a", "t.b"],
                scores=[0.5, 0.5],
                gold_status="unmatched",
                gold_unmatched_reason="no_column_overlap",
            )
            for _ in range(3)
        ],
        _tau_record("C", candidate_ids=[], scores=[], ok=False, gold_status="unmatched", gold_unmatched_reason="no_l4_candidates"),
    ]
    coverage = coverage_summary(records)
    assert coverage["n_records"] == 7
    assert coverage["n_l4_scored"] == 6
    assert coverage["gold_status"] == {"matched": 3, "unmatched": 4}
    assert coverage["gold_unmatched_reason"] == {"no_column_overlap": 3, "no_l4_candidates": 1}

    samples, skips = build_score_samples(records, min_repeats=1)  # 会被夹紧到 MIN_REPEATS=3
    report = summarize(samples, skips)
    assert report["n_samples"] == 1
    assert report["skip_reasons"] == {"gold_unmatched": 1, "insufficient_repeats": 1}
