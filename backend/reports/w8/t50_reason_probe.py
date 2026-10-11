"""T-50 判据③ 夹具读数：截断/内容不可用 ⇒ `report_degraded` 的 reason 取值。零出站、零额度。

与 `tests/unit/test_bind_l4_usage.py::test_failed_parse_still_bills` 同形（同一替身形状）：
`_FakePort` 回放**不可解析**文本（= 截断的等价观测形态：非完整 JSON ⇒ `invalid_json`）
⇒ `score_l4` 落 `ScoreOutcome(failed=True)` ⇒ `bind._online_l4` 报一条 degraded。
本脚本把该次的 `(reason, action, detail.reason)` 打出来，供 QA 尺① 对撞。

用法（cwd = `backend`，需 `PYTHONUTF8=1`）：
    python reports/w8/t50_reason_probe.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.contracts import LLMResponse, TokenUsage
from app.graph.nodes.bind import _online_l4

_BAD = "not json at all"  # 截断的等价形态：非完整 JSON ⇒ 解析层报 invalid_json
_USAGE = TokenUsage(input=100, output=20, cache_hit=0, total=120)
_COST = Decimal("0.0007")


class _FakePort:
    async def call(self, task: str, payload: Any, model: str = "auto") -> LLMResponse:
        return LLMResponse(
            text=_BAD,
            model="deepseek-flash",
            prompt_version="l4_score_v1",
            tokens=_USAGE,
            cost_cny=_COST,
        )

    def estimate_cost(self, payload: Any) -> Decimal:  # pragma: no cover - 未用到
        return Decimal("0")


@dataclass
class _FakeDeps:
    llm: Any


@dataclass
class _StubContext:
    deps: Any
    bundle_version: str = "2026.09.14.1"
    usages: list[Any] = field(default_factory=list)
    degradations: list[Any] = field(default_factory=list)

    def record_usage(self, usage: TokenUsage, cost: Decimal) -> None:
        self.usages.append((usage, cost))

    def report_degraded(self, reason: Any, action: Any, fact: Any = None) -> None:
        self.degradations.append((reason, action, fact))


async def _main() -> None:
    ctx = _StubContext(deps=_FakeDeps(llm=_FakePort()))
    refs = await _online_l4(ctx, ["a", "b"], "GMV")
    print("refs =", refs)
    print("n_degradations =", len(ctx.degradations))
    for reason, action, fact in ctx.degradations:
        print("reason.value  =", getattr(reason, "value", None))
        print("reason.str    =", repr(str(reason)))
        print("action_taken  =", str(action))
        print("detail        =", json.dumps(fact, ensure_ascii=False))
        print("detail.reason =", (fact or {}).get("reason"))
        print("in llm_unavailable family? =", str(reason) == "llm_unavailable")
    print("usage_recorded =", ctx.usages)


asyncio.run(_main())