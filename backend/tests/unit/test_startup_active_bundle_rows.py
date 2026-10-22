"""W8 第 64 轮 C3：启动断言「active 版本是否有物化行」（零出站）。

判定口径（总控 2026-10-22 裁：替代新增 G-9）：
* `app.asset` 或 `app.embed_doc` 在 **active 版本** 行数为 0 ⇒ **FAIL（拒启动）**；
* 两表都有行 ⇒ PASS；
* 库不可达 / 未注入版本 / 表不存在 ⇒ PENDING（**无法判定 ≠ 通过**）。

⚠️ 本文件**不改** `dense.py` 的「0 行 = 合法空」语义；那条语义管的是业务空库，
这条断言管的是"版本指针与库内物化错位"，两件事各有各的落点。
"""

from __future__ import annotations

from app.repo.reachability import Unreachable
from app.repo.startup_assertions import (
    ACTIVE_BUNDLE_VERSION_MATERIALIZED,
    ASSERTION_NAMES,
    AssertionStatus,
    assert_covers_delegated_names,
    evaluate_active_bundle_rows,
)

V = "2026.10.16.2"


def test_zero_rows_fails() -> None:
    out = evaluate_active_bundle_rows((0, 0), version=V)
    assert out.status is AssertionStatus.FAIL
    assert out.name == ACTIVE_BUNDLE_VERSION_MATERIALIZED
    assert "未物化" in out.detail and V in out.detail


def test_partial_zero_rows_fails() -> None:
    # 只有 asset 有行、embed_doc 为 0：检索面仍然空 → 必须 FAIL（不能只看一张表）
    assert evaluate_active_bundle_rows((8, 0), version=V).status is AssertionStatus.FAIL
    assert evaluate_active_bundle_rows((0, 284), version=V).status is AssertionStatus.FAIL


def test_rows_present_passes_with_counts() -> None:
    out = evaluate_active_bundle_rows((8, 284), version=V)
    assert out.status is AssertionStatus.PASS
    assert "8" in out.detail and "284" in out.detail


def test_unreachable_is_pending_not_pass() -> None:
    out = evaluate_active_bundle_rows(Unreachable("connect failed"), version=V)
    assert out.status is AssertionStatus.PENDING
    assert "不可达" in out.detail


def test_missing_query_result_is_pending() -> None:
    assert evaluate_active_bundle_rows(None, version=V).status is AssertionStatus.PENDING


def test_absent_version_is_pending_not_pass() -> None:
    """组装根没注入 active 版本 ⇒ PENDING（不得默认通过）。"""
    out = evaluate_active_bundle_rows((8, 284), version=None)
    assert out.status is AssertionStatus.PENDING


def test_assertion_name_registered_and_bijection_holds() -> None:
    assert ACTIVE_BUNDLE_VERSION_MATERIALIZED in ASSERTION_NAMES
    # 双向比对：实现集合 == config 登记集合（新断言必须两处都登记）
    assert_covers_delegated_names()
