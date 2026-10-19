"""W58 P0：跨租户代号被 normalize 改写后的确定性拒答回归。"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.contracts import IdentityContext
from app.core.enums import Outcome, RefuseReason, Role
from app.graph.nodes import _shared
from app.graph.nodes import normalize as normalize_node
from app.planner.schemas import IntentKind
from app.semantics import SemanticBundleRuntime, load_bundle


def _identity(tenant: str = "T_A") -> IdentityContext:
    return IdentityContext(
        trace_id="tr",
        task_id="tk",
        session_id="ss",
        tenant_id=tenant,
        user_id="u1",
        role=Role.ANALYST,
    )


class _FakeContext:
    def elapsed_ms(self) -> int:
        return 0

    def record_latency(self, *_: Any, **__: Any) -> None:
        pass

    def record_usage(self, *_: Any, **__: Any) -> None:
        pass

    def latency_ms(self) -> dict[str, int]:
        return {}

    def tokens_payload(self) -> dict[str, int]:
        return {"input": 0, "output": 0, "cache_hit": 0, "total": 0}

    def cost_cny(self) -> Decimal:
        return Decimal("0")

    def degradations(self) -> list[dict[str, Any]]:
        return []


class _FakePlanner:
    def __init__(
        self,
        normalized_question: str,
        *,
        reason_code: str | None = None,
        unresolved_terms: tuple[str, ...] = (),
    ) -> None:
        self.calls = 0
        self._normalized_question = normalized_question
        self._reason_code = reason_code
        self._unresolved_terms = unresolved_terms

    async def understand(self, *_: Any, **__: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(
            state_payload=lambda: {
                "normalized_question": self._normalized_question,
                "time_range": None,
                "resolved_terms": [],
                "unresolved_terms": list(self._unresolved_terms),
                "time_parse_ok": True,
                "intent": IntentKind.EXECUTABLE.value,
                "intent_detail": {"reason_code": self._reason_code},
            },
            meta=SimpleNamespace(tokens=0, cost_cny=Decimal("0")),
        )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    normalized_question: str,
    *,
    reason_code: str | None = None,
    unresolved_terms: tuple[str, ...] = (),
    semantics: Any | None = None,
) -> None:
    ctx = _FakeContext()
    monkeypatch.setattr(normalize_node, "rc", lambda: ctx)
    monkeypatch.setattr(_shared, "rc", lambda: ctx)
    monkeypatch.setattr(
        normalize_node,
        "deps_of",
        lambda: SimpleNamespace(
            merged_understand=True,
            planner=_FakePlanner(
                normalized_question,
                reason_code=reason_code,
                unresolved_terms=unresolved_terms,
            ),
            semantics=semantics,
        ),
    )
    monkeypatch.setattr(normalize_node, "identity_of", lambda _state: _identity("T_A"))


@pytest.mark.parametrize("normalized", ["本租户这个月卖了多少？", "这个月卖了多少？"])
async def test_foreign_tenant_code_rewrite_is_refused(
    monkeypatch: pytest.MonkeyPatch, normalized: str
) -> None:
    _patch(monkeypatch, normalized)
    update = await normalize_node.normalize({"raw_question": "T_B 租户这个月卖了多少？"})

    assert update["terminal"]["event"] == "refuse"
    assert update["terminal"]["reason"] == RefuseReason.OUT_OF_SCOPE.value
    assert update["outcome"] == Outcome.REFUSE
    assert update["intent_detail"]["reason_code"] == "unauthorized_scope"


@pytest.mark.parametrize(
    ("raw", "normalized", "expected"),
    [
        ("T_A 的SPU 数是多少？", "SPU 数是多少？", "SPU 数是多少？"),
        ("T_A 2026-08 的日期维表有多少天？", "2026-08 的日期维表有多少天？", "2026-08 的日期维表有多少天？"),
        ("各店铺的商品数分别是多少？", "各店铺的商品数分别是多少？", "各店铺的商品数分别是多少？"),
    ],
)
async def test_own_or_absent_code_does_not_refuse(
    monkeypatch: pytest.MonkeyPatch, raw: str, normalized: str, expected: str
) -> None:
    _patch(monkeypatch, normalized)
    update = await normalize_node.normalize({"raw_question": raw})

    assert "terminal" not in update
    assert update["normalized_question"] == expected


async def test_foreign_tenant_code_preserved_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, "T_B 租户这个月卖了多少？")
    update = await normalize_node.normalize({"raw_question": "T_B 租户这个月卖了多少？"})

    assert update["terminal"]["event"] == "refuse"
    assert update["terminal"]["reason"] == RefuseReason.OUT_OF_SCOPE.value
    assert update["intent_detail"]["reason_code"] == "unauthorized_scope"

_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"


class _AlwaysTimeoutPlanner:
    def __init__(self) -> None:
        self.calls = 0

    async def understand(self, *_: Any, **__: Any) -> Any:
        self.calls += 1
        raise TimeoutError("forced timeout")


@pytest.mark.parametrize(
    ("tenant", "raw", "must_refuse"),
    [
        ("T_A", "T_B 租户这个月卖了多少？", True),
        ("T_A", "T_A 的在架商品数是多少？", False),
        ("T_B", "T_B 租户这个月卖了多少？", False),
        ("T_C", "在架商品数是多少？", False),
    ],
)
async def test_foreign_tenant_scope_is_decided_before_llm(
    monkeypatch: pytest.MonkeyPatch, tenant: str, raw: str, must_refuse: bool
) -> None:
    planner = _AlwaysTimeoutPlanner()
    ctx = _FakeContext()
    monkeypatch.setattr(normalize_node, "rc", lambda: ctx)
    monkeypatch.setattr(_shared, "rc", lambda: ctx)
    monkeypatch.setattr(
        normalize_node,
        "deps_of",
        lambda: SimpleNamespace(merged_understand=True, planner=planner, semantics=None),
    )
    monkeypatch.setattr(normalize_node, "identity_of", lambda _state: _identity(tenant))

    if must_refuse:
        update = await normalize_node.normalize({"raw_question": raw})
    else:
        with pytest.raises(TimeoutError):
            await normalize_node.normalize({"raw_question": raw})
        assert planner.calls == 1
        return

    if must_refuse:
        assert planner.calls == 0
        assert update["terminal"]["event"] == "refuse"
        assert update["terminal"]["reason"] == RefuseReason.OUT_OF_SCOPE.value
        assert "code" not in update["terminal"]


@pytest.mark.parametrize(
    ("question", "expected_reason"),
    [
        ("买家手机号前几位分布是怎样的？", RefuseReason.PII_BLOCKED),
        ("看看隔壁店铺的销量", RefuseReason.OUT_OF_SCOPE),
    ],
)
async def test_raw_safe_refusal_precedes_llm(
    monkeypatch: pytest.MonkeyPatch, question: str, expected_reason: RefuseReason
) -> None:
    planner = _FakePlanner(question)
    ctx = _FakeContext()
    monkeypatch.setattr(normalize_node, "rc", lambda: ctx)
    monkeypatch.setattr(_shared, "rc", lambda: ctx)
    monkeypatch.setattr(
        normalize_node,
        "deps_of",
        lambda: SimpleNamespace(
            merged_understand=True,
            planner=planner,
            semantics=SemanticBundleRuntime(load_bundle(_BUNDLE)),
        ),
    )
    monkeypatch.setattr(normalize_node, "identity_of", lambda _state: _identity("T_A"))

    update = await normalize_node.normalize({"raw_question": question})

    assert planner.calls == 0
    assert update["terminal"]["event"] == "refuse"
    assert update["terminal"]["reason"] == expected_reason.value


@pytest.mark.parametrize(
    ("question", "reason_code", "unresolved", "expected_reason"),
    [
        ("给我收货地址明细", "ambiguous_metric_and_grain", ("收货地址明细",), RefuseReason.PII_BLOCKED),
        ("导出一份订单明细 CSV", "ambiguous_metric_and_grain", (), RefuseReason.PII_BLOCKED),
        ("淡季的销量是多少？", "ambiguous_time_and_metric", ("淡季", "销量"), RefuseReason.NO_DATA_ASSET),
        ("看看隔壁店铺的销量", "AMBIGUOUS_SHOP_REFERENCE", ("隔壁店铺", "销量"), RefuseReason.OUT_OF_SCOPE),
        ("竞品的销量是多少？", "unmapped_metric_and_scope", ("竞品", "销量"), RefuseReason.NO_DATA_ASSET),
    ],
)
async def test_clarify_shaped_refusals_are_terminal_refuse(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    reason_code: str,
    unresolved: tuple[str, ...],
    expected_reason: RefuseReason,
) -> None:
    _patch(
        monkeypatch,
        question,
        reason_code=reason_code,
        unresolved_terms=unresolved,
        semantics=SemanticBundleRuntime(load_bundle(_BUNDLE)),
    )
    update = await normalize_node.normalize({"raw_question": question})

    assert update["terminal"]["event"] == "refuse"
    assert update["terminal"]["reason"] == expected_reason.value
    assert update["outcome"] == Outcome.REFUSE

