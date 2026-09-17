"""T5/T6 门面（`LLMPort` 实现）单测 —— **本窗口的 DoD③ 就落在这个文件里**。

## 这个文件是"全项目唯一 LLM 出站通道"的验收现场

07 §10.5 与 N-12 的全部承诺，最终只能靠一件事证明：
**把实际发出去的字节流抓下来，逐键看它是不是只有我们登记过的东西**。
所以本文件的核心断言是 `FakeUpstream.calls`（原始 `httpx.Request.content`）上的**白名单等式** ——
不是"代码看起来没传敏感字段"，是"线缆上确实没有"。

## 降级链的每一条分支都要有断言（N-21：不得静默降级）

| 触发 | 断言 |
|---|---|
| pro 空 content | 换 flash **且关思考**；发 `degraded(llm_unavailable, switched_to_weak_model)` |
| 信号量饱和（强档） | 发 `degraded(llm_concurrency_exceeded, reduced_candidates)`，且 detail 里**明写 advisory** |
| 预算 80% | 发 `degraded(cost_too_high, reduced_candidates)`，**模型照调**（"减路"是建议不是动作） |
| 预算 100% | **一个模型请求都不发**，直接模板；无模板 → `LlmRefused`（**不是 error**） |
| F2 429 / F3 5xx | **不降级**、只发一个请求就上抛 —— 把上游抖动变成模板答案是更坏的结果 |

## ⚠️ 本文件不掩盖的两件事

1. **模板层是空的**（`NullTemplateProvider`）。默认路径实际是 `pro → flash → 拒答`。
   本文件用 `test_default_template_provider_is_a_declared_gap_not_an_implementation`
   把这一点**钉成断言**，以免后来人以为"模板降级已实现"。
2. **降级事件目前只到日志**（`DegradationSink` 默认实现）。到 SSE 的那一跳在 L4，归 W4。
   本文件证明的是"事件确实产生了、字段确实齐全"，不是"前端能看到"。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.contracts import LLMPort
from app.core.enums import ActionTaken, DegradedReason
from app.llm import (
    TEMPLATE_MODEL_ID,
    TEMPLATE_PROMPT_VERSION,
    CallRecord,
    DegradationEvent,
    LlmCallContext,
    LlmGateway,
    NullTemplateProvider,
    build_gateway,
    set_call_context,
)
from app.llm.budget import (
    BILLING_TZ,
    BudgetGuard,
    CostEntry,
    InMemoryCostLedgerSink,
)
from app.llm.client import ChatClient, Completion
from app.llm.egress_guard import ALLOWED_WIRE_KEYS
from app.llm.errors import (
    LlmConcurrencyExceeded,
    LlmEgressViolation,
    LlmRefused,
    LlmUnknownModel,
    LlmUnknownTask,
    LlmUpstreamError,
)
from app.llm.router import (
    MODEL_AUTO,
    MODEL_HARD_TIMEOUT_S,
    TASK_ROUTES,
    LlmTask,
    ModelKey,
)
from tests.unit._llm_fake_upstream import FakeUpstream, json_error, json_ok

#: 用**真实模型 ID**（而不是 "m-flash" 这类假名）：
#: 否则成本断言会全部落到"未知模型按最贵档兜底"那条路径上，
#: `test_cost_settled_...` 就失去了"按真实价目表结算"的证据力。
_MODEL_NAMES: dict[ModelKey, str] = {
    ModelKey.FAST: "deepseek-flash",
    ModelKey.STRONG: "deepseek-v4-pro",
}

#: 固定"当前时刻"= 工作日高峰，让 `is_peak` 与计价都确定。
_NOW = datetime(2026, 9, 17, 10, 30, tzinfo=BILLING_TZ)

#: 固定的 `user_scope`（16 hex，符合 `cache/keys.user_scope_hash` 的形状）。
_SCOPE = "0123456789abcdef"


def _payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "raw_question": "统计华东区上月销售额前十的 SKU",
        "semantic_summary": "表 fact_sales(sku_id, order_id, amount, dt)；指标：销售额=sum(amount)",
        "dialect_note": "PostgreSQL 16 + pgvector。金额单位：元。",
        "output_schema": '{"type":"object","properties":{"sql":{"type":"string"}}}',
        "bundle_version": "2026.09.14.1",
    }
    base.update(over)
    return base


class _HitTemplate:
    """有命中的模板提供者（模拟 Gold Query 库已接线时的行为）。"""

    def __init__(self, text: str = "SELECT count(*) FROM fact_sales") -> None:
        self.text = text
        self.seen: list[tuple[str, Mapping[str, Any]]] = []

    def lookup(self, task: str, payload: Mapping[str, Any]) -> str | None:
        self.seen.append((task, payload))
        return self.text


class _Clock:
    """可手动推进的假时钟 —— 走 `ChatClient(monotonic=...)` 注入口。

    用它把"这次调用花了多久"精确设成想要的值，而不必真的等。注意它**替代不了**
    `asyncio.timeout` 的真实计时（后者量的是墙钟），所以"deadline 到底取了哪个值"
    那组断言必须直接看传输层收到的参数，不能靠假时钟造超时。
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


class _RecordingLedger(InMemoryCostLedgerSink):
    """内存 sink + 一个可读的明细视图。

    加这个子类是为了避免在测试里直接摸父类的 `_entries`：
    子类读父类的受保护成员是正常写法，而"测试去戳被测对象的私有字段"不是。
    """

    @property
    def entries(self) -> list[CostEntry]:
        return list(self._entries)


def _gw(
    upstream: FakeUpstream,
    *,
    ledger: _RecordingLedger | None = None,
    templates: Any = None,
    budget_global: Decimal = Decimal("1000"),
    tenant_budget: Decimal | None = Decimal("1000"),
    semaphore_flash: int = 8,
    semaphore_pro: int = 2,
    max_concurrency: int = 50,
    max_retries: int = 0,
    monotonic: Callable[[], float] | None = None,
    client_cls: Any = ChatClient,
) -> tuple[LlmGateway, _RecordingLedger, list[DegradationEvent], list[CallRecord]]:
    """装配一个"上游全假、观测全记"的网关。

    `monotonic` / `client_cls` 是给"deadline 取值"那组守卫测试用的注入口
    （默认值 = 真实时钟 + `ChatClient`，对其余测试无影响）。
    """
    events: list[DegradationEvent] = []
    records: list[CallRecord] = []

    class _Sink:
        def on_degraded(self, event: DegradationEvent) -> None:
            events.append(event)

    class _Metrics:
        def on_call(self, record: CallRecord) -> None:
            records.append(record)

    the_ledger = ledger if ledger is not None else _RecordingLedger()
    client = client_cls(
        base_url="https://upstream.test",
        api_key="sk-test-not-a-real-key",
        model_names={
            "fast": _MODEL_NAMES[ModelKey.FAST],
            "strong": _MODEL_NAMES[ModelKey.STRONG],
        },
        max_concurrency=max_concurrency,
        semaphore_flash=semaphore_flash,
        semaphore_pro=semaphore_pro,
        max_retries=max_retries,
        circuit_fails=999,  # 熔断那条归 test_llm_client.py；这里不让它干扰降级链观察
        circuit_open_s=30.0,
        transport=upstream.transport,
        monotonic=monotonic,
    )
    gateway = LlmGateway(
        client=client,
        model_names=_MODEL_NAMES,
        budget=BudgetGuard(
            global_daily_budget_cny=budget_global,
            alert_ratio=0.8,
            sink=the_ledger,
            tenant_daily_budget_cny=tenant_budget,
        ),
        now_fn=lambda: _NOW,
        degradation=_Sink(),
        templates=templates,
        metrics=_Metrics(),
    )
    return gateway, the_ledger, events, records


def _seed_spend(
    ledger: InMemoryCostLedgerSink, amount: Decimal, *, tenant: str = "(unset)"
) -> None:
    """预置一笔已花金额。

    刻意不经 `settle()`：这组测试要的是"已花到某个比例"这个**状态**，
    用真实计价去凑金额会让夹具数字与价目表耦合，价目表一改测试就莫名其妙地红。
    """
    ledger.record(
        CostEntry(
            entry_id="seed", task_id="seed", tenant_id=tenant, user_id="seed",
            model="deepseek-flash", input_tokens=0, output_tokens=0, cache_hit_tokens=0,
            cost_cny=amount, is_peak=True, created_at=_NOW,
        )
    )


@pytest.fixture(autouse=True)
def _clean_call_context() -> None:
    """每个用例前把请求级上下文复位，避免用例间串号（`contextvars` 在同一任务里会残留）。"""
    set_call_context(LlmCallContext())


# ============================================================================
# 一、端口契约
# ============================================================================

class TestPortContract:
    async def test_gateway_satisfies_llm_port(self) -> None:
        """`LLMPort` 是 `runtime_checkable` —— 结构性兼容要靠断言钉住，不能靠"我觉得像"。"""
        gw, *_ = _gw(FakeUpstream())
        try:
            assert isinstance(gw, LLMPort)
        finally:
            await gw.aclose()

    async def test_call_signature_matches_the_frozen_port(self) -> None:
        """参数名与顺序也是契约的一部分：`(task, payload, model)`。"""
        params = list(inspect.signature(LlmGateway.call).parameters)
        assert params[:3] == ["self", "task", "payload"]
        assert params[3] == "model"
        assert inspect.signature(LlmGateway.call).parameters["model"].default == MODEL_AUTO
        assert not inspect.iscoroutinefunction(LlmGateway.estimate_cost)

    async def test_estimate_cost_returns_decimal(self) -> None:
        gw, *_ = _gw(FakeUpstream())
        try:
            assert isinstance(gw.estimate_cost({"text": "统计销售额"}), Decimal)
        finally:
            await gw.aclose()

    async def test_estimate_cost_follows_the_route_model(self) -> None:
        """估算要按**该 task 实际会用的模型**算，否则 pre-flight 的金额与真实账单不同量级。"""
        gw, *_ = _gw(FakeUpstream())
        try:
            cheap = gw.estimate_cost({"text": "x" * 500, "task": "gen_sql"})
            pricey = gw.estimate_cost({"text": "x" * 500, "task": "gen_sql_complex"})
        finally:
            await gw.aclose()
        assert pricey > cheap

    async def test_estimate_cost_does_not_raise_on_unknown_task(self) -> None:
        gw, *_ = _gw(FakeUpstream())
        try:
            assert gw.estimate_cost({"text": "x", "task": "no_such_task"}) >= Decimal(0)
        finally:
            await gw.aclose()


# ============================================================================
# 二、DoD③：录制出站 payload 并逐键核对白名单
# ============================================================================

class TestOutboundAttachment:
    """**这一段就是 DoD③ 的证据**。断言对象是抓包到的原始请求体。"""

    async def test_wire_body_keys_are_exactly_the_registered_set(self) -> None:
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        body = up.calls[0]
        assert set(body) <= ALLOWED_WIRE_KEYS
        assert set(body) == {
            "model", "messages", "max_tokens", "temperature", "response_format", "thinking",
        }
        assert set(body["response_format"]) == {"type"}
        assert set(body["thinking"]) == {"type"}
        assert [m["role"] for m in body["messages"]] == ["system", "user"]

    async def test_user_scope_goes_only_to_the_user_parameter_never_into_messages(self) -> None:
        """N-12 把 `user_id` 列为 PII，而 07 §10.3 规则 2 又要"开 user_id 隔离"。

        收口方式：出站的是**哈希**，且只走 API 的 `user` 参数、**不进 messages**
        （进了文本就会被模型复述，等于把 PII 送进上下文）。
        """
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql", _payload(user_scope=_SCOPE))
        finally:
            await gw.aclose()
        body = up.calls[0]
        assert body["user"] == _SCOPE
        for m in body["messages"]:
            assert _SCOPE not in m["content"]

    async def test_identity_context_never_reaches_the_wire(self) -> None:
        """`task_id` / `tenant_id` / `user_id` 只服务计量与日志，**永不出站**。"""
        set_call_context(
            LlmCallContext(task_id="task-secret", tenant_id="tenant-secret", user_id="user-secret")
        )
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        hay = up.all_sent_text()
        for secret in ("task-secret", "tenant-secret", "user-secret"):
            assert secret not in hay

    async def test_api_key_never_appears_in_the_body(self) -> None:
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert "sk-test-not-a-real-key" not in up.all_sent_text()

    async def test_thinking_off_uses_the_only_spelling_the_upstream_honours(self) -> None:
        """🔴 实测：关闭思考的**唯一**有效写法是 `{"type":"disabled"}`。

        `thinking: false` → **400**；`enable_thinking: false` / `chat_template_kwargs` →
        **被静默忽略**（仍产 reasoning token，即"以为关了其实没关"）。
        静默忽略是最坏的一种：代码看着对，成本与延迟却按思考档付。
        """
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        body = up.calls[0]
        assert body["thinking"] == {"type": "disabled"}
        assert body["thinking"] is not False
        assert "enable_thinking" not in body
        assert "chat_template_kwargs" not in body

    async def test_thinking_on_only_when_the_route_asks_for_it(self) -> None:
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql_complex", _payload())
        finally:
            await gw.aclose()
        assert up.calls[0]["thinking"] == {"type": "enabled"}

    async def test_max_tokens_leaves_reasoning_headroom_on_thinking_routes(self) -> None:
        from app.llm.router import TASK_ROUTES, THINKING_HEADROOM_TOKENS, LlmTask

        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql_complex", _payload())
        finally:
            await gw.aclose()
        hint = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX].output_tokens_hint
        assert up.calls[0]["max_tokens"] == hint + THINKING_HEADROOM_TOKENS

    async def test_temperature_and_json_output_travel_as_configured(self) -> None:
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        body = up.calls[0]
        assert body["temperature"] == 0.0
        assert body["response_format"] == {"type": "json_object"}

    async def test_prompt_version_is_recorded_on_the_response(self) -> None:
        """N-19：`prompt_version` 必录 —— 没有它就无法回答"这份答案是哪版 prompt 产出的"。"""
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            resp = await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert resp.prompt_version == "gen_sql_v1"

    async def test_model_override_is_an_auditable_escape_hatch(self) -> None:
        """显式 `model` 覆盖路由表：允许，且必须**真的按覆盖值出站**。

        🔴 这条断言抓到过一个真实缺陷：`resolve_model_name` 校验并返回了覆盖值，
        但出站 `model` 取自 `route.model_key` —— 覆盖只影响了**预算估算**。
        后果是"调用方以为换了模型，账单和延迟却按另一个模型走"，
        且没有任何日志能看出来（典型的 N-21 静默行为）。
        """
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql_complex", _payload(), "deepseek-flash")
        finally:
            await gw.aclose()
        assert up.calls[0]["model"] == "deepseek-flash"

    async def test_override_to_the_strong_model_also_takes_effect(self) -> None:
        """反向对照：只往"降档"一个方向断言的话，"永远按 route 走"的实现也能过 ——
        那个实现恰好会在覆盖到**快档**时看起来正确（因为多数 task 本来就是快档）。
        """
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            await gw.call("gen_sql", _payload(), "deepseek-v4-pro")
        finally:
            await gw.aclose()
        assert up.calls[0]["model"] == "deepseek-v4-pro"
        # 覆盖只改**模型档**，不改任务的思考位（`gen_sql` 的 route.thinking=False）
        assert up.calls[0]["thinking"] == {"type": "disabled"}

    async def test_override_does_not_silently_disable_the_degrade_chain(self) -> None:
        """覆盖到强档后，降级链仍要从**该档**继续（强 → 弱），不是从路由表那档开始。"""
        up = FakeUpstream(lambda i, r: json_ok(content="") if i == 0 else json_ok(content="{}"))
        gw, _, events, _ = _gw(up)
        try:
            await gw.call("gen_sql", _payload(), "deepseek-v4-pro")
        finally:
            await gw.aclose()
        assert [c["model"] for c in up.calls] == ["deepseek-v4-pro", "deepseek-flash"]
        assert events[0].detail["model_override"] is True


class TestNothingIsSentOnContractViolations:
    """契约错误与安全事件**必须在发请求之前**就炸掉 —— 否则我们花了钱还什么都没学到。"""

    async def test_unregistered_payload_key_is_rejected_before_any_request(self) -> None:
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            with pytest.raises(LlmEgressViolation):
                await gw.call("gen_sql", _payload(rows=[["a", 1]]))
        finally:
            await gw.aclose()
        assert up.sent == 0

    async def test_result_set_shaped_question_is_rejected_before_any_request(self) -> None:
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            with pytest.raises(LlmEgressViolation):
                await gw.call(
                    "gen_sql",
                    _payload(
                        raw_question=(
                            "看下这几行\nsku_001,129.00,2026-09-01\n"
                            "sku_002,88.50,2026-09-02\nsku_003,19.90,2026-09-03"
                        )
                    ),
                )
        finally:
            await gw.aclose()
        assert up.sent == 0

    async def test_sql_in_session_history_is_rejected_before_any_request(self) -> None:
        """N-17：`sql_text` 永不回灌 prompt。历史里只有"问题"是合法的。"""
        up = FakeUpstream()
        gw, *_ = _gw(up)
        try:
            with pytest.raises(LlmEgressViolation):
                await gw.call(
                    "normalize",
                    _payload(history_questions=["SELECT sum(amount) FROM fact_sales 的结果是多少"]),
                )
        finally:
            await gw.aclose()
        assert up.sent == 0

    async def test_unknown_task_fails_fast_without_degrading(self) -> None:
        up = FakeUpstream()
        gw, _, events, _ = _gw(up)
        try:
            with pytest.raises(LlmUnknownTask):
                await gw.call("no_such_task", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 0
        assert events == [], "契约错误不是'上游不行'，降级会掩盖它"

    async def test_unknown_model_fails_fast_without_degrading(self) -> None:
        up = FakeUpstream()
        gw, _, events, _ = _gw(up)
        try:
            with pytest.raises(LlmUnknownModel):
                await gw.call("gen_sql", _payload(), "gpt-4o")
        finally:
            await gw.aclose()
        assert up.sent == 0
        assert events == []


# ============================================================================
# 三、降级链（07 §10.2 逐行）
# ============================================================================

class TestDegradeToWeakModel:
    async def test_strong_failure_switches_to_flash_and_forces_thinking_off(self) -> None:
        """链上第二档写的是 **flash（非思考）** —— 换成 flash 却留着思考，
        既拿不到质量也拿不到速度（思考的钱照付）。"""
        up = FakeUpstream(
            lambda i, r: json_ok(content="")
            if i == 0
            else json_ok(content='{"sql":"SELECT 1"}', model="deepseek-flash")
        )
        gw, _, events, records = _gw(up)
        try:
            resp = await gw.call("gen_sql_complex", _payload())
        finally:
            await gw.aclose()

        assert up.sent == 2
        assert up.calls[0]["model"] == "deepseek-v4-pro"
        assert up.calls[0]["thinking"] == {"type": "enabled"}
        assert up.calls[1]["model"] == "deepseek-flash"
        assert up.calls[1]["thinking"] == {"type": "disabled"}
        assert resp.model == "deepseek-flash"

        assert [e.reason for e in events] == [DegradedReason.LLM_UNAVAILABLE]
        assert [e.action_taken for e in events] == [ActionTaken.SWITCHED_TO_WEAK_MODEL]
        assert events[0].detail["from_model"] == "deepseek-v4-pro"
        assert events[0].task == "gen_sql_complex"
        assert records[0].degraded is True, "降级后成功也必须被标记（N-21 不得静默降级）"

    async def test_degraded_event_fields_use_the_sse_vocabulary(self) -> None:
        """`reason` / `action_taken` 必须是**契约枚举**（StrEnum）——
        W4 要原样把它们塞进 SSE，自造字符串会在前端静默失配。"""
        up = FakeUpstream(lambda i, r: json_ok(content="") if i == 0 else json_ok(content="{}"))
        gw, _, events, _ = _gw(up)
        try:
            await gw.call("gen_sql_complex", _payload())
        finally:
            await gw.aclose()
        assert isinstance(events[0].reason, DegradedReason)
        assert isinstance(events[0].action_taken, ActionTaken)
        assert str(events[0].reason) in {str(v) for v in DegradedReason}
        assert str(events[0].action_taken) in {str(v) for v in ActionTaken}

    async def test_saturation_on_the_strong_model_emits_an_advisory_not_a_fake_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """🔴 "减路"网关**做不到** —— payload 归调用方所有。

        能做的实物动作是"换到并发位更多的 flash"（8 位 vs 2 位，pro 饱和时几乎必然可用）。
        所以取 `action_taken=reduced_candidates` 的同时，detail 必须**明写 `advisory=True`**，
        否则这个字段就是在冒充一个已完成的动作。
        """
        monkeypatch.setattr("app.llm.client.SEMAPHORE_WAIT_TIMEOUT_S", 0.01)

        async def responder(i: int, r: Any) -> Any:
            if i == 0:  # 第一个请求（强档）挂住，占满 pro 的唯一并发位
                await asyncio.sleep(0.3)
            return json_ok(content='{"sql":"SELECT 1"}', model="deepseek-flash")

        up = FakeUpstream(responder)
        gw, _, events, _ = _gw(up, semaphore_pro=1)
        try:
            holder = asyncio.create_task(gw.call("gen_sql_complex", _payload()))
            await asyncio.sleep(0.05)  # 让 holder 占住 pro 的位
            resp = await gw.call("gen_sql_complex", _payload())
            await holder
        finally:
            await gw.aclose()

        sat = [e for e in events if e.reason is DegradedReason.LLM_CONCURRENCY_EXCEEDED]
        assert sat, "pro 饱和必须发 llm_concurrency_exceeded"
        assert sat[0].action_taken is ActionTaken.REDUCED_CANDIDATES
        assert sat[0].detail["advisory"] is True
        assert resp.model == "deepseek-flash"  # 实物动作：换到弱档（这个能真的做成）
        assert "candidates" not in up.calls[-1], "网关不会、也不能替调用方减路"


class TestDegradeToTemplateAndRefuse:
    async def test_template_hit_returns_a_template_answer_and_still_emits_degraded(self) -> None:
        up = FakeUpstream(lambda i, r: json_ok(content=""))
        templates = _HitTemplate("SELECT count(*) FROM fact_sales")
        gw, ledger, events, records = _gw(up, templates=templates)
        try:
            resp = await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()

        assert resp.model == TEMPLATE_MODEL_ID
        assert resp.prompt_version == TEMPLATE_PROMPT_VERSION
        assert resp.text == "SELECT count(*) FROM fact_sales"
        # 模板层没烧 token / 没花钱 —— 必须**如实为 0**，不许填个"估算值"
        assert resp.tokens.input == 0 and resp.tokens.output == 0
        assert resp.cost_cny == Decimal(0)
        assert ledger.entries == []
        assert records == []  # 没有模型调用 → 没有调用记录（不制造假的延迟/命中率样本）
        assert any(e.action_taken is ActionTaken.TEMPLATE_ONLY for e in events)
        assert templates.seen[0][0] == "gen_sql"

    async def test_template_path_is_observable_as_a_distinct_model_id(self) -> None:
        """`model="template"` 让"这份答案是降级产物"在**审计里看得出来**（N-21 的精神）。"""
        up = FakeUpstream(lambda i, r: json_ok(content=""))
        gw, *_ = _gw(up, templates=_HitTemplate())
        try:
            resp = await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert resp.model == TEMPLATE_MODEL_ID
        assert resp.model not in set(_MODEL_NAMES.values())

    async def test_no_template_hit_is_a_refusal_not_an_error(self) -> None:
        """07 §10.2 最后一行：`refuse` 是**产品结论**，不是 `error`。

        `LlmRefused.default_code is None` 这条断言的含义：它**不是错误码**。
        若 W4 忘了先捕获它，它会被兜底成 `500 INTERNAL` —— 那是错的终态。
        """
        up = FakeUpstream(lambda i, r: json_ok(content=""))
        gw, ledger, events, _ = _gw(up)
        try:
            with pytest.raises(LlmRefused) as ei:
                await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 1
        assert ei.value.default_code is None
        assert ei.value.detail["task"] == "gen_sql"
        assert ledger.entries == []
        assert events[-1].action_taken is ActionTaken.TEMPLATE_ONLY

    async def test_default_template_provider_is_a_declared_gap_not_an_implementation(self) -> None:
        """🔴 诚实声明钉成断言：P0 的模板层**是空的**（`gold_query` 未接线）。

        默认路径实际是 `pro → flash → 拒答`。这条断言的作用是：哪天有人接上了模板库，
        它会红 —— 提醒同步 `DELIVERY.md`，而不是让文档继续声称"模板降级已实现"。
        """
        provider = NullTemplateProvider()
        assert provider.lookup("gen_sql", {"anything": 1}) is None
        up = FakeUpstream(lambda i, r: json_ok(content=""))
        gw, *_ = _gw(up)  # 不传 templates → 走默认
        try:
            with pytest.raises(LlmRefused):
                await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()


class TestErrorsThatMustNotDegrade:
    """F2 / F3：把一次上游抖动变成一份看起来正常的模板答案，比报错危险得多。"""

    async def test_429_is_an_error_and_never_tries_the_weaker_model(self) -> None:
        up = FakeUpstream(lambda i, r: json_error(429))
        gw, _, events, _ = _gw(up)
        try:
            with pytest.raises(LlmConcurrencyExceeded):
                await gw.call("gen_sql_complex", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 1, "F2 不该触发降级链的第二档"
        assert events == []

    async def test_5xx_is_an_error_and_never_falls_back_to_the_template(self) -> None:
        up = FakeUpstream(lambda i, r: json_error(503))
        gw, _, events, _ = _gw(up, templates=_HitTemplate())
        try:
            with pytest.raises(LlmUpstreamError):
                await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 1
        assert events == []


# ============================================================================
# 四、预算熔断（NFR-4.2）
# ============================================================================

class TestBudgetFuse:
    async def test_fuse_skips_every_model_call_and_goes_straight_to_template(self) -> None:
        ledger = _RecordingLedger()
        _seed_spend(ledger, Decimal("1000"))
        up = FakeUpstream()
        gw, _, events, _ = _gw(up, ledger=ledger, templates=_HitTemplate("SELECT 1"))
        try:
            resp = await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 0, "100% 熔断后**一个模型请求都不许发**"
        assert resp.model == TEMPLATE_MODEL_ID
        assert events[0].reason is DegradedReason.COST_TOO_HIGH
        assert events[0].action_taken is ActionTaken.TEMPLATE_ONLY
        assert events[0].detail["blocked_by"] == "global"

    async def test_fuse_without_a_template_is_a_refusal_not_a_500(self) -> None:
        ledger = _RecordingLedger()
        _seed_spend(ledger, Decimal("1000"))
        up = FakeUpstream()
        gw, *_ = _gw(up, ledger=ledger)
        try:
            with pytest.raises(LlmRefused):
                await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 0

    async def test_eighty_percent_warns_and_still_calls_the_model(self) -> None:
        """80% 是**告警**不是熔断：模型照调，只是把"减路"作为建议发出去。"""
        ledger = _RecordingLedger()
        _seed_spend(ledger, Decimal("800"))
        up = FakeUpstream()
        gw, _, events, _ = _gw(up, ledger=ledger)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 1
        warn = [e for e in events if e.reason is DegradedReason.COST_TOO_HIGH]
        assert warn and warn[0].action_taken is ActionTaken.REDUCED_CANDIDATES
        assert warn[0].detail["advisory"] is True
        assert "candidates" not in up.calls[0], "网关不替调用方减路（也不假装减了）"

    async def test_no_degradation_event_on_a_healthy_call(self) -> None:
        """反向对照：一切正常时**不许**发 degraded（否则前端会一直显示"降级中"）。"""
        up = FakeUpstream()
        gw, _, events, _ = _gw(up)
        try:
            resp = await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert events == []
        assert resp.model == "deepseek-flash"


# ============================================================================
# 五、计量与观测
# ============================================================================

class TestAccountingAndObservability:
    async def test_successful_call_settles_one_row_with_the_context_identity(self) -> None:
        set_call_context(LlmCallContext(task_id="task-1", tenant_id="t1", user_id="u1"))
        up = FakeUpstream()
        gw, ledger, _, _ = _gw(up)
        try:
            resp = await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert len(ledger.entries) == 1
        assert ledger.entries[0].task_id == "task-1"
        assert ledger.entries[0].tenant_id == "t1"
        assert ledger.entries[0].user_id == "u1"
        assert ledger.tenant_spent_cny("t1", _NOW.date()) == resp.cost_cny
        assert ledger.global_spent_cny(_NOW.date()) == resp.cost_cny

    async def test_unset_context_is_visible_instead_of_silently_wrong(self) -> None:
        """未接线时归集到 `"(unset)"` —— **可见的错误**好过静默的错误。"""
        up = FakeUpstream()
        gw, ledger, _, _ = _gw(up)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert ledger.global_spent_cny(_NOW.date()) > 0
        assert ledger.tenant_spent_cny("(unset)", _NOW.date()) > 0

    async def test_call_record_carries_the_cache_hit_data_source(self) -> None:
        """NFR-4.3 的命中率 = `cache_hit_tokens / input_tokens`，数据由上游 `usage` 直供。"""
        up = FakeUpstream(lambda i, r: json_ok(prompt_tokens=1000, cache_hit_tokens=800))
        gw, _, _, records = _gw(up)
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert records[0].input_tokens == 1000
        assert records[0].cache_hit_tokens == 800
        assert records[0].prompt_version == "gen_sql_v1"
        assert records[0].degraded is False
        assert records[0].is_peak is True  # `now_fn` 固定在工作日高峰

    async def test_cost_settled_after_degradation_uses_the_model_that_actually_ran(self) -> None:
        """降级后结算的必须是**真正跑了的那个模型**的价，不是原路由档的价 ——
        否则成本账会按 pro 计价，而实际只调了 flash（高估 3 倍以上）。
        """
        up = FakeUpstream(lambda i, r: json_ok(content="") if i == 0 else json_ok(content="{}"))
        gw, ledger, _, records = _gw(up)
        try:
            await gw.call("gen_sql_complex", _payload())
        finally:
            await gw.aclose()
        assert len(ledger.entries) == 1
        assert ledger.entries[0].model == "deepseek-flash"
        assert records[0].model == "deepseek-flash"
        assert ledger.entries[0].price_guess is False  # flash 在价目表里，不是兜底价

    async def test_template_answer_settles_no_row(self) -> None:
        """模板层不烧 token → 不该在 `cost_ledger` 里留一行 0 元账
        （那会污染"调用次数"统计，让"降级了多少次"看起来像"调用了多少次模型"）。"""
        ledger = _RecordingLedger()
        _seed_spend(ledger, Decimal("1000"))
        up = FakeUpstream()
        gw, *_ = _gw(up, ledger=ledger, templates=_HitTemplate())
        try:
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert len(ledger.entries) == 1  # 只有我们预置的那一笔


# ============================================================================
# 六、装配入口
# ============================================================================

class _FakeSettings:
    """`build_gateway` 需要的最小 Settings 替身（字段名必须与 `core/config.py` 一致）。"""

    DEEPSEEK_BASE_URL = "https://upstream.test"
    DEEPSEEK_API_KEY = SecretStr("sk-test-not-a-real-key")
    LLM_MODEL_FAST = "deepseek-flash"
    LLM_MODEL_STRONG = "deepseek-v4-pro"
    LLM_MAX_CONCURRENCY = 50
    LLM_SEMAPHORE_FLASH = 8
    LLM_SEMAPHORE_PRO = 2
    LLM_MAX_RETRIES = 0
    LLM_CIRCUIT_FAILS = 5
    LLM_CIRCUIT_OPEN_S = 30
    DAILY_BUDGET_CNY = 100.0
    BUDGET_ALERT_RATIO = 0.8


def _injected_client(up: FakeUpstream) -> ChatClient:
    return ChatClient(
        base_url=_FakeSettings.DEEPSEEK_BASE_URL,
        api_key=_FakeSettings.DEEPSEEK_API_KEY.get_secret_value(),
        model_names={"fast": "deepseek-flash", "strong": "deepseek-v4-pro"},
        max_concurrency=50, semaphore_flash=8, semaphore_pro=2,
        max_retries=0, circuit_fails=5, circuit_open_s=30.0,
        transport=up.transport,
    )


class TestBuildGateway:
    async def test_build_gateway_uses_the_injected_client_end_to_end(self) -> None:
        """行为证明优于读私有字段：用注入的 client 真的能发出去、真的能拿回答案。"""
        up = FakeUpstream()
        ledger = _RecordingLedger()
        gw = build_gateway(_FakeSettings(), client=_injected_client(up), ledger=ledger)
        try:
            assert isinstance(gw, LlmGateway)
            await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert up.sent == 1
        assert len(ledger.entries) == 1

    async def test_build_gateway_defaults_to_an_in_memory_ledger(self) -> None:
        """不传 `ledger` 时也**能跑**（内存 sink），但那条限制必须写在文档里 ——
        进程一退出数据就没了，**熔断在重启面前不成立**。"""
        up = FakeUpstream()
        gw = build_gateway(_FakeSettings(), client=_injected_client(up))
        try:
            resp = await gw.call("gen_sql", _payload())
        finally:
            await gw.aclose()
        assert resp.model == "deepseek-flash"


# ============================================================================
# 七、路由表与门面的接线一致性
# ============================================================================

class TestRouteRouterIntegration:
    async def test_every_task_actually_calls_the_model_its_route_names(self) -> None:
        """逐 task 跑一遍：出站 `model` 必须等于路由表说的那个档（10 个 task 全覆盖）。

        这条防的是"门面用了另一张表"—— 路由表单测全绿，但门面把档位写反了。
        """
        from app.llm.router import TASK_ROUTES, LlmTask

        for task in LlmTask:
            up = FakeUpstream()
            gw, *_ = _gw(up)
            try:
                await gw.call(task.value, _payload())
            finally:
                await gw.aclose()
            assert up.calls[0]["model"] == _MODEL_NAMES[TASK_ROUTES[task].model_key], task.value

    async def test_thinking_flag_follows_the_route_for_non_thinking_tasks(self) -> None:
        from app.llm.router import TASK_ROUTES, LlmTask

        for task in (LlmTask.GEN_SQL, LlmTask.PLAN, LlmTask.PRESENT, LlmTask.REPAIR):
            up = FakeUpstream()
            gw, *_ = _gw(up)
            try:
                await gw.call(task.value, _payload())
            finally:
                await gw.aclose()
            assert up.calls[0]["thinking"] == {"type": "disabled"}, task.value
            assert TASK_ROUTES[task].thinking is False, task.value


# ============================================================================
# 十一、🔴 阶段延迟预算**不是**超时（2026-09-17 真机故障的守卫）
# ============================================================================

class TestStageBudgetIsNeverTheDeadline:
    """`TASK_ROUTES[task].budget_s`（07 §16.1 的 P95 分配）曾被当作硬 deadline。

    真机双向对照（真 key，同进程/同 payload/同模型，唯一变量 = deadline，n=3×5 任务）：

    | task | §16.1 预算 | 当 deadline 用 | 改用 §10.2 上限 | 后者实测延迟中位 |
    |---|---|---|---|---|
    | `normalize` | 0.6s | **0/3** | 3/3 | 1.45s |
    | `intent` | 0.6s | **0/3** | 3/3 | 1.39s |
    | `normalize_intent` | 1.2s | **0/3** | 3/3 | 1.56s |
    | `plan` | 1.0s | **0/3** | 3/3 | 1.49s |
    | `gen_sql` | 1.3s | **0/3** | 3/3 | 1.60s |

    失败耗时**恰好等于各自预算**（卡在 deadline 上死，不是上游不可用）；而真机延迟
    **全部高于**分配值。根因：P95 是**分位数**不是上界 —— 拿它当硬上限，健康系统也
    必然砍掉尾部；分配值低于中位时就是 100% 失败。07 §16.2 也写明超预算应"先推占位符"
    （降级 UX），不是失败；PRD §12.2 的路由表根本没有超时列。
    """

    def _spy(self) -> tuple[Any, list[float]]:
        """造一个把 `deadline_s` 记下来的 `ChatClient` 子类。

        为什么必须在这个位置判定：`asyncio.timeout` 量的是**真实时间**，所以
        "用假时钟把耗时拉到 1.8s"**无法**让旧接线失败（协程立刻返回、计时器不触发）——
        纯行为测试对这条缺陷没有鉴别力。能直接回答"deadline 取了哪个值"的，
        只有传输层入口的那个参数。
        """
        seen: list[float] = []

        class _DeadlineSpy(ChatClient):
            async def invoke(
                self, *, model: str, wire_body: Mapping[str, Any], deadline_s: float
            ) -> Completion:
                seen.append(deadline_s)
                return await super().invoke(
                    model=model, wire_body=wire_body, deadline_s=deadline_s
                )

        return _DeadlineSpy, seen

    async def test_deadline_handed_to_transport_is_the_model_tier(self) -> None:
        spy_cls, seen = self._spy()
        up = FakeUpstream()
        gw, *_ = _gw(up, client_cls=spy_cls)
        try:
            await gw.call(LlmTask.PLAN.value, _payload())
        finally:
            await gw.aclose()

        plan_budget = TASK_ROUTES[LlmTask.PLAN].budget_s
        assert plan_budget == 1.0, "夹具前提：plan 的阶段预算确实是 1.0s"
        assert seen == [MODEL_HARD_TIMEOUT_S[ModelKey.FAST]]
        assert seen[0] != plan_budget, "deadline 取了阶段预算 —— 正是那个故障"

    async def test_deadline_follows_the_tier_for_a_task_without_a_budget(self) -> None:
        """`budget_s is None` 的 task 同样必须拿到模型级上限（不能是 None/0/被跳过）。"""
        spy_cls, seen = self._spy()
        up = FakeUpstream()
        gw, *_ = _gw(up, client_cls=spy_cls)
        try:
            await gw.call(LlmTask.REPAIR.value, _payload())
        finally:
            await gw.aclose()
        assert seen == [MODEL_HARD_TIMEOUT_S[ModelKey.FAST]]

    async def test_negative_control_the_spy_actually_tracks_the_wiring(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """负向对照：注入旧接线（deadline 取任务级预算）→ 记录值必须随之变成 1.0。

        没有这一条，上面两条"== 模型级上限"可能是**恒真**的（例如 spy 记的其实是个常量，
        或 `invoke` 的 deadline 压根不来自 `hard_timeout_s`）。这条证明那些断言有鉴别力。
        """
        import app.llm as llm_pkg

        monkeypatch.setattr(
            llm_pkg, "hard_timeout_s", lambda model_key: TASK_ROUTES[LlmTask.PLAN].budget_s
        )
        spy_cls, seen = self._spy()
        up = FakeUpstream()
        gw, *_ = _gw(up, client_cls=spy_cls)
        try:
            await gw.call(LlmTask.GEN_SQL.value, _payload())
        finally:
            await gw.aclose()

        assert seen == [TASK_ROUTES[LlmTask.PLAN].budget_s]
        assert seen[0] != MODEL_HARD_TIMEOUT_S[ModelKey.FAST], (
            "注入旧接线后仍等于模型级上限 —— 说明那两条正向断言没有鉴别力"
        )

    async def test_a_call_slower_than_its_stage_budget_survives_and_is_marked(self) -> None:
        """行为面：慢于阶段预算的调用必须**成功**，并被标成 `over_budget`。

        假时钟把"耗时"记成 1750ms（> `plan` 的 1000ms 阶段预算，< flash 的 15s 上限）。
        `over_budget=True` 是新机制的载体 —— §16.1 的一致性从"强制"改为"可观测"，
        这个标志若不亮，删掉硬上限就等于把 §16.1 整个丢了。

        ⚠️ 步长刻意取 1.75s（= 1 + 1/2 + 1/4，二进制可精确表示）：`1.8` 不可精确表示，
        `(1001.8 - 1000.0) * 1000` 会截断成 1799，让断言莫名其妙地红。
        """
        clock = _Clock()

        def slow_ok(index: int, request: Any) -> Any:
            _ = (index, request)
            clock.t += 1.75
            return json_ok()

        up = FakeUpstream(slow_ok)
        gw, _, events, records = _gw(up, monotonic=clock)
        try:
            resp = await gw.call(LlmTask.PLAN.value, _payload())
        finally:
            await gw.aclose()

        assert up.sent == 1, "超预算不该触发重试"
        assert resp.text, "拿不到内容说明调用被 deadline 掐死了（正是那个故障）"
        assert records[-1].latency_ms == 1750
        assert records[-1].budget_s == TASK_ROUTES[LlmTask.PLAN].budget_s
        assert records[-1].over_budget is True
        assert events == [], "延迟超标**不是降级** —— 发 degraded 会谎称答案来自降级路径"

    async def test_a_call_within_budget_is_not_marked_over_budget(self) -> None:
        """反向对照：没超预算就不许标 `over_budget`（否则这个标志没有信息量）。"""
        clock = _Clock()

        def fast_ok(index: int, request: Any) -> Any:
            _ = (index, request)
            clock.t += 0.25
            return json_ok()

        up = FakeUpstream(fast_ok)
        gw, _, _, records = _gw(up, monotonic=clock)
        try:
            await gw.call(LlmTask.PLAN.value, _payload())
        finally:
            await gw.aclose()
        assert records[-1].latency_ms == 250
        assert records[-1].over_budget is False

    async def test_over_budget_is_false_when_07_gave_no_budget(self) -> None:
        """`budget_s is None`（07 未给该阶段分配）→ 没有可比对象，不得标超预算。"""
        clock = _Clock()

        def slow_ok(index: int, request: Any) -> Any:
            _ = (index, request)
            clock.t += 5.0
            return json_ok()

        up = FakeUpstream(slow_ok)
        gw, _, _, records = _gw(up, monotonic=clock)
        try:
            await gw.call(LlmTask.REPAIR.value, _payload())
        finally:
            await gw.aclose()
        assert records[-1].budget_s is None
        assert records[-1].over_budget is False
