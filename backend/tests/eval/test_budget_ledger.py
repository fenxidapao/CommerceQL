"""W77-4：全局预算账本（calls / tokens / ¥ 并列，先到即停）—— 假 transport，零真打。

W76 的教训不是"多花了多少钱"，而是**没有账本**：冒烟 4 calls + 三批 348 calls
本来就已经越过 350 的授权上限，但每一批单看都合规，于是继续跑了 b3。
本文件钉住三件事：
1. `max_calls` 按 `transport.calls` **增量**判（重试产生的调用也计入）；
2. `prior_usage`（上轮账本）先计入，开跑前就越限 ⇒ 一条都不跑；
3. tokens 把二轮 tokens 也算进去，且 `budget_stop` 带 `calls`/`tokens`/`breached`。
"""

from __future__ import annotations

import asyncio
from typing import Any

import runner


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []


class _FakeSemantics:
    def guard_allowlist(self, identity: Any, max_rows: Any = None) -> dict[str, Any]:
        return {}


class _FakeHarness:
    instances: list["_FakeHarness"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.transport = _FakeTransport()
        self.semantics = _FakeSemantics()
        self.node_timeout_overrides: dict[str, float] = {}
        self.max_concurrency = None
        self.closed = False
        type(self).instances.append(self)

    def save_cassette(self) -> int:
        return 0

    async def aclose(self) -> None:
        self.closed = True


_CASES = [{"case_id": f"C{i}", "question": f"q{i}"} for i in range(1, 4)]


def _record(case_id: str, *, tokens: int = 10, cost: float = 0.01,
            second_tokens: int = 0) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "expected_behavior": "execute",
        "terminal_event": "complete",
        "terminal_error_detail": None,
        "verdict": {"equivalent": True},
        "tokens": {"total": tokens},
        "cost_cny": cost,
        "second_round": (
            {"attempted": True, "success": True, "tokens": {"total": second_tokens},
             "cost_cny": 0.0}
            if second_tokens else None
        ),
        "scored": True,
        "attribution": None,
    }


def _install(monkeypatch: Any, scorer: Any) -> None:
    _FakeHarness.instances.clear()
    monkeypatch.setattr(runner, "Harness", _FakeHarness)
    monkeypatch.setattr(runner, "score_case", scorer)


def _run(monkeypatch: Any, *, max_calls: int | None = None,
         max_tokens: int | None = None, prior: dict[str, Any] | None = None,
         cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return asyncio.run(runner.run_batch(
        cases or _CASES,
        live=False,
        cassette="unused.jsonl",
        mode="replay",
        db_path="unused.db",
        column_top=None,
        node_timeout_overrides=None,
        transport_retries=2,
        transport_backoff_s=0.0,
        max_calls=max_calls,
        max_tokens=max_tokens,
        prior_usage=prior,
    ))


def test_calls_cap_stops_before_next_case(monkeypatch: Any) -> None:
    async def score(harness: _FakeHarness, case: dict[str, Any], **kw: Any) -> dict[str, Any]:
        harness.transport.calls.extend([f"{case['case_id']}-{i}" for i in range(2)])
        return _record(case["case_id"])

    _install(monkeypatch, score)
    batch = _run(monkeypatch, max_calls=3)

    assert [r["case_id"] for r in batch["records"]] == ["C1", "C2"], "第 3 条不该开始"
    stop = batch["budget_stop"]
    assert stop is not None
    assert stop["reason"] == "max_calls_exceeded"
    assert stop["breached"] == ["max_calls"]
    assert stop["calls"] == 4
    assert stop["completed_cases"] == 2
    assert batch["usage"]["calls"] == 4
    assert batch["calls_unique"] == 4


def test_prior_ledger_can_stop_before_any_case(monkeypatch: Any) -> None:
    called = {"n": 0}

    async def score(harness: _FakeHarness, case: dict[str, Any], **kw: Any) -> dict[str, Any]:
        called["n"] += 1
        return _record(case["case_id"])

    _install(monkeypatch, score)
    batch = _run(monkeypatch, max_calls=10, prior={"calls": 10, "tokens": 0, "cost_cny": 0.0})

    assert batch["records"] == []
    assert called["n"] == 0, "账本已越限却仍调用了模型"
    stop = batch["budget_stop"]
    assert stop is not None
    assert stop["reason"] == "budget_already_exhausted"
    assert stop["calls"] == 10


def test_retries_are_counted_in_calls(monkeypatch: Any) -> None:
    attempts = {"n": 0}

    async def score(harness: _FakeHarness, case: dict[str, Any], **kw: Any) -> dict[str, Any]:
        attempts["n"] += 1
        harness.transport.calls.append(f"{case['case_id']}-{attempts['n']}")
        if attempts["n"] == 1:
            return {
                "case_id": case["case_id"],
                "scored": True,
                "expected_behavior": "execute",
                "terminal_event": "error",
                "terminal_error_detail": {"kind": "ConnectError"},
                "verdict": None,
                "tokens": {"total": 3},
                "cost_cny": 0.0,
                "second_round": None,
                "attribution": None,
            }
        return _record(case["case_id"])

    _install(monkeypatch, score)
    batch = _run(monkeypatch, cases=[_CASES[0]])

    assert batch["budget_stop"] is None
    assert batch["records"][0]["runner_transport_retries"] == 1
    assert batch["usage"]["calls"] == 2, "重试的调用也必须进账"
    assert batch["usage"]["tokens"] == 13, "两次尝试的 tokens 都要计"


def test_tokens_cap_includes_second_round(monkeypatch: Any) -> None:
    async def score(harness: _FakeHarness, case: dict[str, Any], **kw: Any) -> dict[str, Any]:
        harness.transport.calls.append(case["case_id"])
        return _record(case["case_id"], tokens=10, second_tokens=5)

    _install(monkeypatch, score)
    batch = _run(monkeypatch, cases=[_CASES[0]], max_tokens=14)

    assert batch["usage"]["tokens"] == 15
    stop = batch["budget_stop"]
    assert stop is not None
    assert stop["reason"] == "max_tokens_exceeded"
    assert stop["tokens"] == 15
