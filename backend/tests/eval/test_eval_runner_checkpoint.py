"""W8 第 56 轮：评测跑批的断点续跑与传输故障退避（零出站）。"""

from __future__ import annotations

import json
from typing import Any

import pytest

import runner


def _record(case_id: str, *, event: str, scored: bool = True, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "scored": scored,
        "terminal_event": event,
        "terminal_error_detail": detail or {},
        "tokens": {"total": 0},
        "verdict": None,
    }


def test_transport_retry_excludes_hard_timeout() -> None:
    transport = _record("X-1", event="error", detail={"kind": "ConnectError"})
    timeout = _record("X-2", event="error", detail={"last_degrade_error": "LlmTimeout"})
    circuit = _record("X-3", event="error", detail={"last_degrade_error": "LlmCircuitOpen"})

    assert runner._is_transient_transport_record(transport) is True
    assert runner._is_transient_transport_record(circuit) is True
    assert runner._is_transient_transport_record(timeout) is False


def test_resume_skips_complete_and_hard_timeout_but_not_transport_failure() -> None:
    complete = _record("X-1", event="complete")
    timeout = _record("X-2", event="error", detail={"kind": "LlmTimeout"})
    transport = _record("X-3", event="error", detail={"kind": "ConnectError"})

    assert runner._resume_should_skip(complete) is True
    assert runner._resume_should_skip(timeout) is True
    assert runner._resume_should_skip(transport) is False


def test_checkpoint_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    path.write_text(
        json.dumps(
            {
                "dataset_content_hash": "sha256:old",
                "record": _record("X-1", event="complete"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dataset_content_hash"):
        runner._load_checkpoint(str(path), expected_content_hash="sha256:new")


class _Semantics:
    def guard_allowlist(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}


class _Transport:
    def __init__(self) -> None:
        self.calls: list[str] = []


class _Harness:
    def __init__(self, **_kwargs: Any) -> None:
        self.semantics = _Semantics()
        self.transport = _Transport()
        self.max_concurrency = _kwargs.get("max_concurrency")
        self.node_timeout_overrides: dict[str, float] = {}

    def save_cassette(self) -> int:
        return 0

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runner_retries_transient_but_not_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    async def fake_score_case(_harness: Any, case: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        calls.append(str(case["case_id"]))
        if case["case_id"] == "X-transport" and calls.count("X-transport") == 1:
            return _record("X-transport", event="error", detail={"kind": "ConnectError"})
        if case["case_id"] == "X-timeout":
            return _record("X-timeout", event="error", detail={"kind": "LlmTimeout"})
        return _record(str(case["case_id"]), event="complete")

    monkeypatch.setattr(runner, "Harness", _Harness)
    monkeypatch.setattr(runner, "score_case", fake_score_case)
    cases = [{"case_id": "X-transport"}, {"case_id": "X-timeout"}]
    batch = await runner.run_batch(
        cases,
        live=False,
        cassette="unused.jsonl",
        mode="replay",
        db_path="unused.db",
        column_top=None,
        node_timeout_overrides=None,
        max_concurrency=2,
        checkpoint_path=str(tmp_path / "checkpoint.jsonl"),
        checkpoint_meta={"dataset_content_hash": "sha256:test"},
        transport_retries=2,
        transport_backoff_s=0,
    )
    assert calls == ["X-transport", "X-transport", "X-timeout"]
    assert batch["records"][0]["runner_transport_retries"] == 1
    assert batch["records"][1]["runner_transport_retries"] == 0
    loaded = runner._load_checkpoint(
        str(tmp_path / "checkpoint.jsonl"), expected_content_hash="sha256:test"
    )
    assert set(loaded) == {"X-transport", "X-timeout"}

def test_gate_self_defect_is_only_recorded_when_gate1_actually_rejected() -> None:
    """gate1 已 pass 时，F1 静态形态不得覆盖 gate_decisions 的一手事实。"""
    sql = (
        "SELECT channel, SUM(pay_amount) AS gmv FROM v_order_paid "
        "GROUP BY channel ORDER BY gmv DESC LIMIT 100"
    )
    allowlist = {"assets": {}, "default_predicates": {}}
    assert runner._gate_defect_if_rejected(
        sql, allowlist, {"1": "pass/True"}
    ) is None
    assert runner._gate_defect_if_rejected(
        sql, allowlist, {"1": "reject/False"}
    ) is not None
