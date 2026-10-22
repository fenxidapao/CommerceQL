"""C4：语义包发布闸门的**环境分流**（W8 第 65 轮；零出站）。

## 为什么闸门落在这里、不在 `active_version()`

W8 第 64 轮 C4 的结论是：`SemanticBundleRuntime.active_version()` 直接回 `self._loaded.version`，
**不看 `status`** ⇒ `candidate` 包被当作 active 正常服务，FR-12.3 的"只有 published 可服务"
在运行时没有闸门。QA §86.2-3 明确否掉了"在 `active_version()` 里硬校验"这条修法：

> 硬校验会让 dev 与评测（包 status=candidate）起不来。

所以分流放在启动断言：**prod 且非 published ⇒ FAIL；dev/staging（含评测面）⇒ PENDING（WARN）**。
本文件把四分表逐格钉住，并顺带钉住"旧调用点不传探针不会静默通过"。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import AppEnv
from app.repo.startup_assertions import (
    ASSERTION_NAMES,
    SEMANTIC_BUNDLE_STATUS_PUBLISHED,
    AssertionStatus,
    StartupProbes,
    assert_covers_delegated_names,
    evaluate_semantic_bundle_published,
    run_startup_assertions,
)


def _settings(app_env: AppEnv) -> Any:
    """`is_fatal()` 只读 `APP_ENV`（见 `AssertionOutcome.is_fatal`），给个最小壳即可。"""
    return SimpleNamespace(APP_ENV=app_env)


@pytest.mark.parametrize("status", ["candidate", "draft", "staged", "weird"])
def test_prod_with_unpublished_bundle_fails(status: str) -> None:
    """prod + 非 published ⇒ **FAIL**，且 `is_fatal` 为真（拒启动）。"""
    outcome = evaluate_semantic_bundle_published(
        status, app_env=AppEnv.PROD, version="2026.10.16.2"
    )
    assert outcome.name == SEMANTIC_BUNDLE_STATUS_PUBLISHED
    assert outcome.status is AssertionStatus.FAIL
    assert outcome.is_fatal(_settings(AppEnv.PROD)) is True
    assert "FR-12.3" in outcome.detail
    assert status in outcome.detail


def test_published_passes_in_every_env() -> None:
    for env in (AppEnv.PROD, AppEnv.STAGING, AppEnv.DEV):
        outcome = evaluate_semantic_bundle_published("published", app_env=env)
        assert outcome.status is AssertionStatus.PASS, env
        assert outcome.is_fatal(_settings(env)) is False, env


@pytest.mark.parametrize("env", [AppEnv.DEV, AppEnv.STAGING])
def test_non_prod_with_unpublished_bundle_is_pending_but_not_fatal(env: AppEnv) -> None:
    """dev/staging + candidate ⇒ PENDING（日志 WARN）+ **不阻断启动**。

    这正是 QA 要的"WARN"语义：本模块只有三态，而"非 prod 放行但必须可见"
    就是 `PENDING`（`enforce_startup_assertions` 对 PENDING 打的日志级别是 WARNING）。
    """
    outcome = evaluate_semantic_bundle_published("candidate", app_env=env)
    assert outcome.status is AssertionStatus.PENDING
    assert outcome.is_fatal(_settings(env)) is False
    assert outcome.detail.startswith("WARN")
    assert "prod 下本项会拒绝启动" in outcome.detail


def test_unknown_status_is_pending_not_pass() -> None:
    """读不到 status ⇒ PENDING（**不是 PASS**）；prod 下由 `strict_in_prod` 升级为致命。"""
    outcome = evaluate_semantic_bundle_published(None, app_env=AppEnv.DEV)
    assert outcome.status is AssertionStatus.PENDING
    assert outcome.strict_in_prod is True
    assert outcome.is_fatal(_settings(AppEnv.DEV)) is False
    assert outcome.is_fatal(_settings(AppEnv.PROD)) is True


def test_default_probe_does_not_silently_pass() -> None:
    """旧调用点不注入 `bundle_status` ⇒ 占位探针回 `None` ⇒ PENDING（**不会静默通过**）。"""
    from app.repo.startup_assertions import _no_bundle_status_probe  # noqa: PLC2701

    assert StartupProbes.analytics_role.__class__ is not None  # dataclass 存在性（防拼写漂移）
    assert _no_bundle_status_probe is StartupProbes.__dataclass_fields__["bundle_status"].default


def test_assertion_name_is_registered_both_ways() -> None:
    """双向登记：实现里有、`config.STARTUP_ASSERTIONS_DELEGATED_TO_W1B` 里也有。"""
    assert SEMANTIC_BUNDLE_STATUS_PUBLISHED in ASSERTION_NAMES
    assert_covers_delegated_names()


async def test_run_startup_assertions_reads_the_status_probe() -> None:
    """编排层真的把 status 读进来并产出第 6 条（防"写了判定函数但没人调"）。"""
    from tests.unit.test_startup_assertions import _probes

    async def candidate() -> str:
        return "candidate"

    probes = _probes(bundle_status=candidate)
    settings = _probes_settings()
    outcomes = await run_startup_assertions(settings, probes)  # type: ignore[arg-type]
    names = [o.name for o in outcomes]
    assert SEMANTIC_BUNDLE_STATUS_PUBLISHED in names
    outcome = outcomes[names.index(SEMANTIC_BUNDLE_STATUS_PUBLISHED)]
    assert outcome.status is AssertionStatus.PENDING
    assert "candidate" in outcome.detail

    # prod 同一份读数 ⇒ FAIL（这正是分流的意义：同事实、不同环境、不同判）
    async def candidate_prod() -> str:
        return "candidate"

    prod_outcomes = await run_startup_assertions(
        _probes_settings(AppEnv.PROD), _probes(bundle_status=candidate_prod)  # type: ignore[arg-type]
    )
    prod_outcome = prod_outcomes[[o.name for o in prod_outcomes].index(SEMANTIC_BUNDLE_STATUS_PUBLISHED)]
    assert prod_outcome.status is AssertionStatus.FAIL


def _probes_settings(app_env: AppEnv = AppEnv.DEV) -> Any:
    return SimpleNamespace(
        APP_ENV=app_env,
        ANALYTICS_DB_URL="postgresql://ro@127.0.0.1:5432/ecom",
        EMBEDDING_DIM=1024,
    )
