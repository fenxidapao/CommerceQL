"""W76-1：τ 采样 schema 的三件补充（零出站）。

派单 §97.8 要求先补齐 schema 再真打：

| 补充 | 落点 | 本文件钉什么 |
|---|---|---|
| ① case 级 calibration/holdout split（种子/规则先写死） | `tau_samples.split_of` / `split_summary` | 同一 case **永远同一侧**；规则字符串带盐版本；样本上带 `split` |
| ② runner 逐 case `binding_layer` | `runner` 记录的 `binding_layer` + summary 分布 | 分布按层计数，缺失记 `none` |
| ③ `batch_id`（3 批可区分） | `run_batch(..., batch_id=…)` | 本文件只钉记录字段（跑批路径由真打批次实证） |
| ④ 候选覆盖面与 gold 命中率照录 | `tau_samples.coverage_summary` 的 `candidate_asset_records` | 候选资产前缀逐条计数 |

🔴 split 的规则**在采样前写死**：改盐 = 历史样本侧别全失效 ⇒ 只能升版本号，
不得原地改（`test_split_rule_is_versioned` 钉住字符串里带 `/v1`）。
"""

from __future__ import annotations

from eval.runner import summarize as runner_summarize
from eval.tau_samples import (
    SPLIT_CALIBRATION,
    SPLIT_HOLDOUT,
    SPLIT_SALT,
    build_score_samples,
    coverage_summary,
    split_of,
    split_summary,
    summarize,
)


def _record(case_id: str, *, candidates: list[str], gold: str = "matched") -> dict:
    return {
        "case_id": case_id,
        "batch_id": "b1",
        "binding_layer": "L4",
        "tau_raw": {
            "ok": True,
            "candidate_ids": candidates,
            "scores": [0.9 - 0.1 * i for i in range(len(candidates))],
            "rank": candidates,
            "gold_status": gold,
            "gold_candidate_id": candidates[0] if gold == "matched" else None,
        },
    }


def test_split_is_deterministic_and_both_sides_exist() -> None:
    ids = [f"X-{i:03d}" for i in range(60)]
    first = {cid: split_of(cid) for cid in ids}
    second = {cid: split_of(cid) for cid in ids}
    assert first == second, "同一 case 在不同进程/调用里必须落同一侧"
    assert set(first.values()) == {SPLIT_CALIBRATION, SPLIT_HOLDOUT}, (
        "60 个 id 只落一侧 ⇒ split 退化成全量校准（等于没分离）"
    )


def test_split_rule_is_versioned() -> None:
    assert "/v1" in SPLIT_SALT, "改 split 必须升盐版本号，禁止原地改"
    summary = split_summary([f"X-{i}" for i in range(10)])
    assert summary["salt"] == SPLIT_SALT
    assert SPLIT_SALT in summary["rule"]
    assert sum(summary["counts"].values()) == 10


def test_samples_carry_their_split() -> None:
    records = [
        _record("A", candidates=["v_order_paid.a", "v_order_paid.b"]) for _ in range(3)
    ]
    samples, skips = build_score_samples(records, min_repeats=3)
    assert not skips and len(samples) == 1
    report = summarize(samples, skips)
    assert report["samples"][0]["split"] == split_of("A")


def test_coverage_records_candidate_assets() -> None:
    coverage = coverage_summary([
        _record("A", candidates=["v_order_paid.a", "v_order_paid.b"]),
        _record("B", candidates=["v_product.c", "v_product.d"]),
        _record("C", candidates=["v_order_paid.e"], gold="unmatched"),
    ])
    assert coverage["candidate_asset_records"] == {"v_order_paid": 3, "v_product": 2}
    assert coverage["gold_status"] == {"matched": 2, "unmatched": 1}


def test_runner_summary_counts_binding_layers() -> None:
    records = [
        {"case_id": "A", "binding_layer": "L1", "scored": True, "expected_behavior": "execute"},
        {"case_id": "B", "binding_layer": "L4", "scored": True, "expected_behavior": "execute"},
        {"case_id": "C", "binding_layer": None, "scored": True, "expected_behavior": "execute"},
    ]
    summary = runner_summarize(records)
    assert summary["binding_layer_distribution"] == {"L1": 1, "L4": 1, "none": 1}
