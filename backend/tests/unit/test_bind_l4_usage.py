"""`bind` 节点把 **L4 的用量**记进 run 累加器（2026-10-04 实测缺口的守卫）。

缺口是怎么被逮到的：一条真跑的 run，浏览器口径条写 `成本 ¥0.003288`，而同一条 run 在
落库面 `app.cost_ledger` 的 sum = `¥0.004670` —— 差值 `¥0.001382` **恰等于**四档调用里
`l4_score` 那一档。根因不在闸门也不在网关：`record_usage` 只有
`normalize` / `intent` / `plan` / `gen_sql` / `repair` 五个调用点，`bind` 是唯一"自己出过站、
却没往累加器里记"的节点 ⇒ 口径条与审计的成本**长期少算一整档**，而离线门禁全绿。

这里守三件事：① 用量真的进了累加器；② **解析失败也要记**（模型回了、内容不可用 ⇒ 钱已经花了）；
③ 没出站就不许记（`candidate_ids` 为空时省掉那次调用，虚增用量会把成本口径反过来污染）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.contracts import LLMResponse, TokenUsage
from app.graph.nodes.bind import _online_l4

_GOOD = '{"scores": [{"candidate_id": "a", "score": 0.9}, {"candidate_id": "b", "score": 0.2}]}'
_USAGE = TokenUsage(input=100, output=20, cache_hit=0, total=120)
_COST = Decimal("0.0007")


class _FakePort:
    """最小 `LLMPort`：只回放一份文本，用量固定（本文件只关心用量去哪了）。"""

    def __init__(self, text: str = _GOOD) -> None:
        self.text = text
        self.calls: list[str] = []

    async def call(self, task: str, payload: Any, model: str = "auto") -> LLMResponse:
        self.calls.append(task)
        return LLMResponse(
            text=self.text,
            model="deepseek-flash",
            prompt_version="l4_score_v1",
            tokens=_USAGE,
            cost_cny=_COST,
        )

    def estimate_cost(self, payload: Any) -> Decimal:  # pragma: no cover - 未用到
        return Decimal("0")


@dataclass
class _StubContext:
    """`RunContext` 的用量面替身（其余方法本节点在 `_online_l4` 里用不到）。"""

    deps: Any
    bundle_version: str = "2026.09.14.1"
    usages: list[tuple[TokenUsage, Decimal]] = field(default_factory=list)
    degradations: list[Any] = field(default_factory=list)

    def record_usage(self, usage: TokenUsage, cost: Decimal) -> None:
        self.usages.append((usage, cost))

    def report_degraded(self, reason: Any, action: Any, fact: Any = None) -> None:
        self.degradations.append((reason, action, fact))


def _ctx(port: _FakePort) -> _StubContext:
    return _StubContext(deps=_FakeDeps(llm=port))


@dataclass
class _FakeDeps:
    llm: Any


async def test_l4_usage_is_recorded_into_the_run_accumulator() -> None:
    port = _FakePort()
    ctx = _ctx(port)

    refs = await _online_l4(ctx, ["a", "b"], "GMV")

    assert [r.asset_id for r in refs] == ["a", "b"]
    assert ctx.usages == [(_USAGE, _COST)], "L4 的 token 与成本必须进 run 累加器"


async def test_failed_parse_still_bills() -> None:
    """模型回了但内容不可用 ⇒ 这次调用**已经付费** ⇒ 用量照样入账（失败态不是免费）。"""
    port = _FakePort(text="not json at all")
    ctx = _ctx(port)

    refs = await _online_l4(ctx, ["a", "b"], "GMV")

    assert refs == ()
    assert len(ctx.degradations) == 1
    assert ctx.usages == [(_USAGE, _COST)]


async def test_no_candidates_means_no_call_and_no_usage() -> None:
    """没有字段级候选 → 不出站 ⇒ 也不许凭空记一笔用量（否则成本口径反向失真）。"""
    port = _FakePort()
    ctx = _ctx(port)

    refs = await _online_l4(ctx, [], "GMV")

    assert refs == ()
    assert port.calls == []
    assert ctx.usages == []
