"""节点 2/3/5/7/16 行为单测（W3B，N-01：离线、假端口）。

## 这个文件的两条主线

### 一、"出站的是什么"（契约面）

`FakeLlmPort` 记录每次调用的 `(task, payload, model)`。断言对象是**这三元组**：

- `task` —— 必须是 `LlmTask` 的字面量（W3A 的路由表按它选模型）；
  **修复轮次的 task 可以不同**（`gen_sql` 修不好时改走 `repair`，Q2 裁定）。
- `payload` —— 必须过 `EgressPayload.from_mapping`（N-12），且**永不含 `sql_text`**（N-17）。
- 次数 —— 修复轮次确实只多一次（`MAX_REPAIR_ATTEMPTS = 1`），不是"无限重试"。

### 二、"失败时发生什么"（降级面）

`*Unavailable` 是本窗口的**业务降级**（不是 error、不是 refuse）——
它必须带一条 `notes`，且 reason 用的是**登记过的**取值 + `missing_reason_value` 说明缺口。
`LlmRefused` 则**必须原样穿过**：把它包成 `PlannerError` 会让"产品结论"退化成"一次降级"。

## 为什么用假端口而不是真网关

真网关的降级链（pro→flash→模板→拒答）归 W3A 的 DoD③；
本窗口要证明的是"**本引擎交给网关的输入**与"**它如何消化网关的输出**"，
用假端口能把这两件事钉死，不受网关内部策略干扰。
真网关的联调在 `test_planner_egress_contract.py`（一个用例，证明载荷能穿过真白名单）。
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.clock import FrozenClock
from app.core.contracts import IdentityContext, LLMResponse, TokenUsage
from app.core.enums import ActionTaken, DegradedReason, RefuseReason, Role
from app.llm.egress_guard import EgressPayload
from app.llm.errors import LlmRefused, LlmUpstreamError
from app.llm.router import MODEL_AUTO
from app.planner.engine import (
    MAX_REPAIR_ATTEMPTS,
    LlmCallMeta,
    PlannerEngine,
    PlanOutcome,
    SqlOutcome,
    UnderstandOutcome,
)
from app.planner.errors import (
    PlannerError,
    PlanUnavailable,
    SqlGenerationUnavailable,
    UnderstandUnavailable,
)
from app.planner.schemas import (
    INTENT_MAP,
    IntentKind,
    LlmIntent,
    PlanSummary,
)
from app.semantics import SemanticBundleRuntime, load_bundle

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"

_QUESTION = "上月华东区销售额"


# ============================================================================
# 夹具：假端口 / 记录型 sink / 冻结时钟
# ============================================================================

class FakeLlmPort:
    """按 `task` 脚本化应答的假网关；记录**每一次**调用的三元组。

    `script[task]` 是一个字符串列表（依次消费）；`script["*"]` 是兜底队列。
    列表耗尽后抛 `AssertionError` —— **不允许"悄悄返回上一次的答案"**，
    否则"修复轮次"、"重试次数"这类断言会失去意义。
    """

    def __init__(self, script: Mapping[str, Sequence[str]]) -> None:
        self._script: dict[str, list[str]] = {k: list(v) for k, v in script.items()}
        #: 每次调用的 `(task, payload, model)` —— 本文件的主要断言对象
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self._responses = 0

    def _next_text(self, task: str) -> str:
        queue = self._script.get(task) or self._script.get("*")
        assert queue, f"FakeLlmPort 没有为 task={task!r} 准备应答（脚本耗尽）"
        return queue.pop(0)

    async def call(self, task: str, payload: Mapping[str, Any], model: str) -> LLMResponse:
        assert model == MODEL_AUTO, "引擎必须以 MODEL_AUTO 出站（按路由表选模型）"
        self.calls.append((task, dict(payload), model))
        self._responses += 1
        return LLMResponse(
            text=self._next_text(task),
            # 用**真实模型 ID**：与 W3A 的 `_MODEL_NAMES` 保持一致，
            # 免得"模型名"这类断言落在假名上失去证据力
            model="deepseek-flash",
            prompt_version=f"{task}_v1",
            tokens=TokenUsage(input=100, output=20, cache_hit=0, total=120),
            cost_cny=Decimal("0.001"),
        )

    def estimate_cost(self, payload: Mapping[str, Any]) -> Decimal:  # pragma: no cover
        return Decimal(0)

    # -- 断言辅助 ---------------------------------------------------------

    @property
    def tasks(self) -> list[str]:
        return [task for task, _, _ in self.calls]

    def payload(self, index: int = 0) -> dict[str, Any]:
        return self.calls[index][1]


@dataclass
class RecordingSink:
    """把降级事件攒起来（W4 的 SSE 队列在真实装配里的位置）。"""

    notes: list[Any] = field(default_factory=list)

    def on_degraded(self, note: Any) -> None:
        self.notes.append(note)


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


@pytest.fixture(scope="module")
def clock(runtime: SemanticBundleRuntime) -> FrozenClock:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return FrozenClock(
        _now=datetime(2026, 9, 17, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        _semantics=runtime.time_semantics(),
    )


def _ctx(role: Role = Role.ANALYST) -> IdentityContext:
    return IdentityContext(
        trace_id="tr", task_id="tk", session_id="ss", tenant_id="t1", user_id="u1", role=role
    )


def _engine(
    script: Mapping[str, Sequence[str]],
    runtime: SemanticBundleRuntime,
    clock: FrozenClock,
    *,
    sink: RecordingSink | None = None,
    few_shots: Any = None,
) -> tuple[PlannerEngine, FakeLlmPort, RecordingSink]:
    llm = FakeLlmPort(script)
    the_sink = sink if sink is not None else RecordingSink()
    # `monotonic` 用**递增计数**而不是有限迭代器：一次公开调用会取两次（起/止），
    # 而组合入口（`build_plan` → `generate_sql`）会取更多次。
    # 每两次相邻取值的差恒为 0.25s ⇒ `latency_ms` 恒为 250，与机器速度无关。
    ticks = itertools.count(0)
    engine = PlannerEngine(
        llm=llm,
        semantics=runtime,
        clock=clock,
        degradation=the_sink,
        few_shots=few_shots,
        monotonic=lambda: 1.0 + 0.25 * next(ticks),
    )
    return engine, llm, the_sink


# ============================================================================
# 应答体构造（形状对着 `schemas` 写，不凭记忆）
# ============================================================================

def _normalize_intent_body(**over: Any) -> str:
    body: dict[str, Any] = {
        "normalized_question": _QUESTION,
        "time_expression": "上月",
        "unmapped_terms": [],
        "intent": "query",
        "reason_code": None,
        "confidence": 0.92,
        "clarify_hint": None,
    }
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


def _intent_body(**over: Any) -> str:
    body: dict[str, Any] = {
        "intent": "query",
        "reason_code": None,
        "confidence": 0.9,
        "clarify_hint": None,
    }
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


def _plan_body(**over: Any) -> str:
    body: dict[str, Any] = {
        "metrics": [{"name": "gmv", "caliber": "sum(amount)，含税，不去重"}],
        "dimensions": ["region"],
        "filters": ["pay_status = 'paid'"],
        "grain": "day",
        "time_range": {"start": None, "end": None},
        "order_by": ["gmv desc"],
        "limit": 10,
        "assets": [{"asset": "v_order_paid", "join_key": None}],
        "output_columns": ["region", "gmv"],
        "blocking_issues": [],
    }
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


def _sql_body(*, count: int = 1, **over: Any) -> str:
    candidates = [
        {
            "sql_text": f"SELECT region, sum(amount) AS gmv FROM order_paid GROUP BY region LIMIT 10 -- {i}",
            "params": {"start": "2026-08-01"},
            "rationale": "按大区聚合销售额",
            "confidence": 0.8,
        }
        for i in range(count)
    ]
    body: dict[str, Any] = {"candidates": candidates, "blocking_issues": []}
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


def _repair_body(**over: Any) -> str:
    body = json.loads(_sql_body())
    body["repairable"] = True
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


def _plan(**over: Any) -> Any:
    from app.planner.schemas import Plan

    return Plan.model_validate(json.loads(_plan_body(**over)))


# ============================================================================
# 一、合并档 `understand`（节点 2 + 3）
# ============================================================================

class TestUnderstand:
    @pytest.mark.asyncio
    async def test_happy_path(self, runtime: SemanticBundleRuntime, clock: FrozenClock) -> None:
        engine, llm, sink = _engine(
            {"normalize_intent": [_normalize_intent_body()]}, runtime, clock
        )
        outcome = await engine.understand(_ctx(), _QUESTION, history=["上一轮问题"])

        assert isinstance(outcome, UnderstandOutcome)
        assert outcome.merged is True
        assert outcome.normalized_question == _QUESTION
        assert outcome.intent is IntentKind.EXECUTABLE
        assert outcome.refuse_kind is None
        assert outcome.attempts == 1
        assert outcome.latency_ms == 250  # 由注入的 monotonic 决定，与机器速度无关
        assert outcome.meta.prompt_version == "normalize_intent_v1"
        assert outcome.meta.calls == 1
        assert outcome.degradations == ()  # 没有降级就不许编一条

        # 时间窗由**确定性解析器**算出（不是模型给的日期）
        assert outcome.time_range is not None
        assert outcome.time_range.start == "2026-08-01T00:00:00+08:00"
        assert outcome.time_range.end == "2026-08-31T23:59:59+08:00"
        assert outcome.time_parse_ok is True

        # 出站的就一个 task，且载荷合法
        assert llm.tasks == ["normalize_intent"]
        EgressPayload.from_mapping(llm.payload())
        assert sink.notes == []

    @pytest.mark.asyncio
    async def test_state_payload_keys_match_the_registered_groups(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`state_payload()` 的键 = 07 §5.2 组 2/组 3 的字段名（W4 直接 `state.update`）。"""
        engine, _, _ = _engine({"normalize_intent": [_normalize_intent_body()]}, runtime, clock)
        state = (await engine.understand(_ctx(), _QUESTION)).state_payload()
        assert set(state) == {
            "normalized_question",
            "time_range",
            "resolved_terms",
            "unresolved_terms",
            "time_parse_ok",
            "intent",
            "intent_detail",
        }
        assert state["intent"] == "executable"
        assert state["intent_detail"] == {"reason_code": None}  # 非拒答 → **无** refuse_kind

    @pytest.mark.asyncio
    async def test_payload_never_carries_sql(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """N-17：载荷里既没有 `sql_text` 这类**键**，也没有承载 SQL 的**值**。

        ⚠️ 这里**不能**断言"整份载荷不含 `SELECT` 字样" —— `dialect_note` 是自产稳定文本，
        它**合法地**写着"不得使用 `SELECT *`"（方言说明当然要提 SELECT）。
        `egress_guard` 因此只对**外部来源字段**做 SQL 特征扫描（见其模块 docstring §🔴）。
        所以本用例断言的是：① 键名无 `sql`；② **用户来源**字段里没有 SQL。
        """
        engine, llm, _ = _engine({"normalize_intent": [_normalize_intent_body()]}, runtime, clock)
        await engine.understand(_ctx(), _QUESTION)
        payload = llm.payload()
        assert not any("sql" in key.lower() for key in payload)
        assert "SELECT" not in payload["raw_question"]
        assert "SELECT" not in json.dumps(payload["history_questions"], ensure_ascii=False)
        # 对照：稳定文本里**有** SELECT —— 这正是"值级扫描不覆盖自产文本"的理由
        assert "SELECT" in payload["dialect_note"]
        EgressPayload.from_mapping(payload)  # 但网关照样接受它

    @pytest.mark.asyncio
    async def test_history_is_sanitized_before_egress(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """历史里的 SQL 不得出站（§10.5 ⑥）。"""
        engine, llm, _ = _engine({"normalize_intent": [_normalize_intent_body()]}, runtime, clock)
        await engine.understand(
            _ctx(), _QUESTION, history=["之前问过", "SELECT * FROM order_refund", "再问一次"]
        )
        payload = llm.payload()
        assert payload["history_questions"] == ["之前问过", "再问一次"]
        EgressPayload.from_mapping(payload)

    @pytest.mark.parametrize(
        ("llm_intent", "expected_kind", "expected_refuse"),
        [
            ("query", IntentKind.EXECUTABLE, None),
            ("clarify_needed", IntentKind.CLARIFY, None),
            ("out_of_scope", IntentKind.REFUSE, RefuseReason.OUT_OF_SCOPE),
            ("unsafe", IntentKind.REFUSE, RefuseReason.PII_BLOCKED),
        ],
    )
    @pytest.mark.asyncio
    async def test_intent_mapping_table_is_exhaustive(
        self,
        runtime: SemanticBundleRuntime,
        clock: FrozenClock,
        llm_intent: str,
        expected_kind: IntentKind,
        expected_refuse: RefuseReason | None,
    ) -> None:
        """Q3 的四条映射逐条落测；表本身是 `MappingProxyType`（不可被就地篡改）。"""
        engine, _, _ = _engine(
            {"normalize_intent": [_normalize_intent_body(intent=llm_intent)]}, runtime, clock
        )
        outcome = await engine.understand(_ctx(), _QUESTION)
        assert outcome.intent is expected_kind
        assert outcome.refuse_kind is expected_refuse

    @pytest.mark.asyncio
    async def test_open_analysis_is_unreachable_by_construction(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """🔴 `open_analysis` **不可达**（登记的缺口，不是遗漏）。

        `LlmIntent` 只有 4 个取值、`INTENT_MAP` 只有 4 条 ⇒ 状态机的第 4 个意图
        永远不会被本窗口产出。把它写成断言，是为了让"某天有人以为它可达"当场可见。
        """
        assert set(INTENT_MAP) == set(LlmIntent)
        assert IntentKind.OPEN_ANALYSIS not in {kind for kind, _ in INTENT_MAP.values()}

    @pytest.mark.asyncio
    async def test_refuse_detail_carries_the_refuse_kind(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, _, _ = _engine(
            {
                "normalize_intent": [
                    _normalize_intent_body(
                        intent="out_of_scope", reason_code="not_analytics", confidence=0.7
                    )
                ]
            },
            runtime,
            clock,
        )
        state = (await engine.understand(_ctx(), _QUESTION)).state_payload()
        assert state["intent"] == "refuse"
        assert state["intent_detail"] == {
            "reason_code": "not_analytics",
            "refuse_kind": "out_of_scope",
        }

    @pytest.mark.asyncio
    async def test_fenced_json_is_accepted_without_a_repair_call(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """围栏是格式噪声 ⇒ 剥掉即可，**不该**白花一次修复往返。"""
        engine, llm, _ = _engine(
            {"normalize_intent": [f"```json\n{_normalize_intent_body()}\n```"]}, runtime, clock
        )
        outcome = await engine.understand(_ctx(), _QUESTION)
        assert outcome.attempts == 1
        assert llm.tasks == ["normalize_intent"]

    @pytest.mark.asyncio
    async def test_stringer_question_is_taken_from_the_model(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """归一是**模型**的活：出站的是原始问题，回来的是改写后的（黑话展开）。"""
        engine, llm, _ = _engine(
            {
                "normalize_intent": [
                    _normalize_intent_body(
                        normalized_question="上月（2026-08）华东大区的成交额（GMV）",
                        unmapped_terms=["华东大区"],
                    )
                ]
            },
            runtime,
            clock,
        )
        outcome = await engine.understand(_ctx(), "上个月华东大区赚了多少")
        assert llm.payload()["raw_question"] == "上个月华东大区赚了多少"
        assert outcome.normalized_question == "上月（2026-08）华东大区的成交额（GMV）"
        assert outcome.unresolved_terms == ("华东大区",)


class TestUnderstandRepair:
    """修复轮次：**恰好**多一次，且第二次带得上错误摘要（若能带）。"""

    @pytest.mark.asyncio
    async def test_invalid_then_valid_uses_exactly_two_calls(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine(
            {"normalize_intent": ["这不是 JSON", _normalize_intent_body()]}, runtime, clock
        )
        outcome = await engine.understand(_ctx(), _QUESTION)
        assert outcome.attempts == 2
        assert len(llm.calls) == 2
        # `normalize_intent_v1` **没有** `$error_digest` 槽（Q2 裁定的代价）
        assert llm.tasks == ["normalize_intent", "normalize_intent"]
        assert "error_digest" not in llm.payload(1)

    @pytest.mark.asyncio
    async def test_extra_key_is_rejected_then_repaired(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """多一个键 = 整份拒收（`extra="forbid"`），并触发一次修复。"""
        bad = json.loads(_normalize_intent_body())
        bad["oops"] = 1
        engine, llm, _ = _engine(
            {"normalize_intent": [json.dumps(bad, ensure_ascii=False), _normalize_intent_body()]},
            runtime,
            clock,
        )
        outcome = await engine.understand(_ctx(), _QUESTION)
        assert outcome.attempts == 2 and len(llm.calls) == 2

    @pytest.mark.asyncio
    async def test_repair_is_bounded_at_one_extra_call(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """两次都不行 ⇒ 上抛 `UnderstandUnavailable`，**不再第三次**。"""
        assert MAX_REPAIR_ATTEMPTS == 1
        engine, llm, _ = _engine(
            {"normalize_intent": ["坏", "还是坏"]}, runtime, clock
        )
        with pytest.raises(UnderstandUnavailable) as excinfo:
            await engine.understand(_ctx(), _QUESTION)
        assert len(llm.calls) == 2
        assert excinfo.value.attempts == 2

    @pytest.mark.asyncio
    async def test_unavailable_outcome_carries_a_registered_degradation(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """降级必须是**登记过的** reason + 显式的缺口标注（不发明枚举值）。"""
        sink = RecordingSink()
        engine, _, _ = _engine(
            {"normalize_intent": ["坏", "还是坏"]}, runtime, clock, sink=sink
        )
        with pytest.raises(UnderstandUnavailable) as excinfo:
            await engine.understand(_ctx(), _QUESTION)

        notes = excinfo.value.notes
        assert len(notes) == 1
        note = notes[0]
        assert note.reason is DegradedReason.LLM_UNAVAILABLE
        assert note.action_taken is ActionTaken.TEMPLATE_ONLY
        assert note.detail["missing_reason_value"] == "understanding_failed"
        assert note.detail["attempts"] == 2

    @pytest.mark.asyncio
    async def test_llm_errors_pass_through_untouched(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """🔴 `LlmRefused` 是**产品结论**，绝不能被包装成本窗口的业务降级。

        这条是负向对照：若实现把它包成 `PlannerError`，
        `pytest.raises(LlmRefused)` 会因为异常类型不匹配而红。
        """

        class _Refusing:
            async def call(self, task: str, payload: Mapping[str, Any], model: str) -> Any:
                raise LlmRefused("模板未命中", detail={"task": task})

        engine = PlannerEngine(
            llm=_Refusing(), semantics=runtime, clock=clock, degradation=RecordingSink()
        )
        with pytest.raises(LlmRefused) as excinfo:
            await engine.understand(_ctx(), _QUESTION)
        assert not isinstance(excinfo.value, PlannerError)

    @pytest.mark.asyncio
    async def test_engineering_errors_also_pass_through(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """F3 上游 5xx 是**工程故障**（error 终态），也不许被降级掩盖（N-21）。"""

        class _Broken:
            async def call(self, task: str, payload: Mapping[str, Any], model: str) -> Any:
                raise LlmUpstreamError("上游 5xx", detail={"status": 503})

        engine = PlannerEngine(
            llm=_Broken(), semantics=runtime, clock=clock, degradation=RecordingSink()
        )
        with pytest.raises(LlmUpstreamError):
            await engine.understand(_ctx(), _QUESTION)


class TestSingleTaskEntryPoints:
    """`normalize` / `classify_intent` 单跑（合并档是优化，不是必需 —— DoD① 要能对拍）。"""

    @pytest.mark.asyncio
    async def test_normalize_alone_does_not_produce_an_intent(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        single = json.dumps(
            {"normalized_question": _QUESTION, "time_expression": "上月", "unmapped_terms": []},
            ensure_ascii=False,
        )
        engine, llm, _ = _engine({"normalize": [single]}, runtime, clock)
        outcome = await engine.normalize(_ctx(), _QUESTION)
        assert llm.tasks == ["normalize"]
        assert outcome.merged is False
        # 占位值 —— `merged=False` 就是给调用方的标记（别把它当成真实意图）
        assert outcome.intent is IntentKind.EXECUTABLE
        assert outcome.confidence == 0.0
        assert outcome.intent_detail == {"reason_code": None}

    @pytest.mark.asyncio
    async def test_intent_alone_skips_time_resolution(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine({"intent": [_intent_body()]}, runtime, clock)
        outcome = await engine.classify_intent(_ctx(), "上月销售额")
        assert llm.tasks == ["intent"]
        assert outcome.normalized_question == "上月销售额"  # 不归一化 → 原样带出
        assert outcome.time_range is None  # 该入口不做时间解析
        assert outcome.time_parse_ok is True

    @pytest.mark.asyncio
    async def test_intent_payload_has_no_history_slot(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`intent_v1` 没有 `$history_block` ⇒ 载荷里不塞历史（塞了也不会被渲染）。"""
        engine, llm, _ = _engine({"intent": [_intent_body()]}, runtime, clock)
        await engine.classify_intent(_ctx(), "上月销售额")
        assert "history_questions" not in llm.payload()


# ============================================================================
# 二、节点 5：查询计划
# ============================================================================

class TestPlanFor:
    @pytest.mark.asyncio
    async def test_happy_path(self, runtime: SemanticBundleRuntime, clock: FrozenClock) -> None:
        engine, llm, _ = _engine({"plan": [_plan_body()]}, runtime, clock)
        outcome = await engine.plan_for(_ctx(), normalized_question=_QUESTION)

        assert isinstance(outcome, PlanOutcome)
        assert outcome.attempts == 1
        assert outcome.latency_ms == 250
        assert outcome.plan.metrics[0].name == "gmv"
        EgressPayload.from_mapping(llm.payload())
        # 出站的是**归一化后**的问题（§10.5 ③）
        assert llm.payload()["raw_question"] == _QUESTION

    @pytest.mark.asyncio
    async def test_plan_summary_shape_is_c01_plus_the_registered_extra(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """C-01 的键集 + **一个**登记过的额外键 `blocked`。"""
        engine, _, _ = _engine({"plan": [_plan_body()]}, runtime, clock)
        summary = (await engine.plan_for(_ctx(), normalized_question=_QUESTION)).plan_summary
        assert isinstance(summary, PlanSummary)
        assert set(summary.model_dump()) == {
            "metrics",
            "dimensions",
            "filters",
            "grain",
            "time_range",
            "order_by",
            "limit",
            "blocked",
        }
        assert summary.metrics == ["gmv"]
        assert summary.blocked is False

    @pytest.mark.asyncio
    async def test_plan_summary_never_contains_sql(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`plan_summary` 会进 SSE 事件（C-01）—— 它不含 SQL，结构上就不含。"""
        engine, _, _ = _engine({"plan": [_plan_body()]}, runtime, clock)
        summary = (await engine.plan_for(_ctx(), normalized_question=_QUESTION)).plan_summary
        blob = json.dumps(summary.model_dump(), ensure_ascii=False)
        assert "SELECT" not in blob.upper()

    @pytest.mark.asyncio
    async def test_blocking_issues_alone_is_a_legal_plan(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """资产规则：找不到关联路径时**不要猜** —— 只给 `blocking_issues` 也合法。"""
        body = _plan_body(metrics=[], assets=[], blocking_issues=["订单表与流量表无关联路径"])
        engine, _, _ = _engine({"plan": [body]}, runtime, clock)
        outcome = await engine.plan_for(_ctx(), normalized_question=_QUESTION)
        assert outcome.plan.blocking_issues == ["订单表与流量表无关联路径"]
        assert outcome.plan_summary.blocked is True

    @pytest.mark.asyncio
    async def test_plan_with_neither_metrics_nor_blocking_is_rejected(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """"什么都没说"不是合法计划 → 校验失败 → 修复 → 仍失败 → `PlanUnavailable`。"""
        empty = _plan_body(metrics=[], blocking_issues=[])
        engine, llm, _ = _engine({"plan": [empty, empty]}, runtime, clock)
        with pytest.raises(PlanUnavailable) as excinfo:
            await engine.plan_for(_ctx(), normalized_question=_QUESTION)
        assert len(llm.calls) == 2
        note = excinfo.value.notes[0]
        assert note.reason is DegradedReason.PLAN_GENERATION_FAILED
        assert note.detail["stage"] == "plan"

    @pytest.mark.asyncio
    async def test_extra_constraints_are_carried_into_the_payload(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine({"plan": [_plan_body()]}, runtime, clock)
        await engine.plan_for(
            _ctx(), normalized_question=_QUESTION, extra_constraints="只允许单表查询"
        )
        assert "只允许单表查询" in llm.payload()["constraints"]


# ============================================================================
# 三、节点 7 / 16：SQL 生成与有界纠错
# ============================================================================

class TestSqlFor:
    @pytest.mark.asyncio
    async def test_happy_path(self, runtime: SemanticBundleRuntime, clock: FrozenClock) -> None:
        engine, llm, _ = _engine({"gen_sql": [_sql_body()]}, runtime, clock)
        outcome = await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=_plan(), candidates=1
        )
        assert isinstance(outcome, SqlOutcome)
        assert outcome.task == "gen_sql"
        assert outcome.repair_used is False
        assert outcome.primary is not None
        assert outcome.primary.sql_text.startswith("SELECT")
        EgressPayload.from_mapping(llm.payload())
        assert "sql_text" not in llm.payload()

    @pytest.mark.asyncio
    async def test_complex_route_is_selected_explicitly(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`complex_query=True` → `gen_sql_complex`（PRD §12.2：唯一走思考的档）。"""
        engine, llm, _ = _engine({"gen_sql_complex": [_sql_body()]}, runtime, clock)
        await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=_plan(), complex_query=True
        )
        assert llm.tasks == ["gen_sql_complex"]

    @pytest.mark.asyncio
    async def test_state_payload_shape(self, runtime: SemanticBundleRuntime, clock: FrozenClock) -> None:
        engine, _, _ = _engine({"gen_sql": [_sql_body()]}, runtime, clock)
        outcome = await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=_plan(), candidates=1
        )
        state = outcome.state_payload()
        assert set(state) == {
            "sql_text",
            "sql_params",
            "sql_dialect",
            "sql_candidates",
            "prompt_version",
            "model_version",
            "confidence",
        }
        assert state["sql_dialect"] == "postgres"
        assert state["sql_text"] == outcome.primary.sql_text if outcome.primary else False

    @pytest.mark.asyncio
    async def test_requested_vs_returned_is_reported_honestly(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """要 3 路、模型只给 1 路 ⇒ **如实记录两个数**，不伪装成一次降级事件。

        `DegradedReason` 里没有"路数不足"的取值，硬套一个就是撒谎（见 `SqlOutcome` docstring）。
        """
        engine, llm, _ = _engine({"gen_sql": [_sql_body(count=1)]}, runtime, clock)
        outcome = await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=_plan(), candidates=3
        )
        assert outcome.requested == 3
        assert len(outcome.candidates) == 1
        assert outcome.degradations == ()
        assert "期望候选 SQL 条数：3" in llm.payload()["constraints"]

    @pytest.mark.asyncio
    async def test_zero_or_negative_candidates_is_normalized_to_one(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine({"gen_sql": [_sql_body()]}, runtime, clock)
        outcome = await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=_plan(), candidates=0
        )
        assert outcome.requested == 1
        assert "期望候选 SQL 条数：1" in llm.payload()["constraints"]

    @pytest.mark.asyncio
    async def test_few_shots_are_passed_through_when_available(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        seen: list[str] = []

        def _few_shots(question: str) -> list[tuple[str, str]]:
            seen.append(question)
            return [("上月华东销售额", "SELECT region, sum(amount) FROM order_paid GROUP BY region")]

        engine, llm, _ = _engine({"gen_sql": [_sql_body()]}, runtime, clock, few_shots=_few_shots)
        await engine.sql_for(_ctx(), normalized_question=_QUESTION, plan=_plan())
        assert seen == [_QUESTION]
        # 载荷里的形态是**二元组**（`EgressPayload.from_mapping` 只做规范化，不改成 list）
        assert llm.payload()["few_shots"] == [
            ("上月华东销售额", "SELECT region, sum(amount) FROM order_paid GROUP BY region")
        ]

    @pytest.mark.asyncio
    async def test_no_few_shot_provider_means_no_few_shots(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """没有 Gold Query 库就**不假装有**（默认不传）。"""
        engine, llm, _ = _engine({"gen_sql": [_sql_body()]}, runtime, clock)
        await engine.sql_for(_ctx(), normalized_question=_QUESTION, plan=_plan())
        assert llm.payload()["few_shots"] == []


class TestSqlRepairRound:
    """Q2 裁定：`gen_sql*` 的修复轮次**改走 `repair` 任务**（它有 `$error_digest` 槽）。"""

    @pytest.mark.asyncio
    async def test_repair_round_switches_task_and_carries_a_digest(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine(
            {"gen_sql": ["坏输出"], "repair": [_repair_body()]}, runtime, clock
        )
        outcome = await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=_plan(), candidates=1
        )
        assert outcome.attempts == 2
        assert outcome.repair_used is True
        assert llm.tasks == ["gen_sql", "repair"]
        retry_payload = llm.payload(1)
        assert retry_payload["error_digest"]  # 有摘要可回灌
        assert "sql_text" not in retry_payload  # 但**没有**失败的那条 SQL（N-17）

    @pytest.mark.asyncio
    async def test_repair_prompt_version_comes_from_the_second_call(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """产出者才是版本的所有者：`prompt_version` 取**第二次**，token/成本两次都算。"""
        engine, _, _ = _engine(
            {"gen_sql": ["坏输出"], "repair": [_repair_body()]}, runtime, clock
        )
        outcome = await engine.sql_for(_ctx(), normalized_question=_QUESTION, plan=_plan())
        assert outcome.meta.prompt_version == "repair_v1"
        assert outcome.meta.calls == 2
        assert outcome.meta.tokens.total == 240  # 120 × 2
        assert outcome.meta.cost_cny == Decimal("0.002")

    @pytest.mark.asyncio
    async def test_both_rounds_bad_raises_sql_generation_unavailable(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine({"gen_sql": ["坏"], "repair": ["还坏"]}, runtime, clock)
        with pytest.raises(SqlGenerationUnavailable) as excinfo:
            await engine.sql_for(_ctx(), normalized_question=_QUESTION, plan=_plan())
        assert len(llm.calls) == 2
        note = excinfo.value.notes[0]
        # 复用 `plan_generation_failed` + 显式标注缺口（`DegradedReason` 缺专值）
        assert note.reason is DegradedReason.PLAN_GENERATION_FAILED
        assert note.detail["missing_reason_value"] == "sql_generation_failed"
        assert note.detail["stage"] == "gen_sql"

    @pytest.mark.asyncio
    async def test_repair_sql_takes_only_a_digest_and_does_not_nest_repairs(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """节点 16：输入只有计划 + 摘要；且**纠错本身不再套一层修复**（2 轮不是 4 轮）。"""
        engine, llm, _ = _engine({"repair": [_repair_body()]}, runtime, clock)
        outcome = await engine.repair_sql(
            _ctx(),
            normalized_question=_QUESTION,
            plan=_plan(),
            error_digest="- 字段 `region`：Unknown column",
        )
        assert llm.tasks == ["repair"]
        assert llm.payload()["error_digest"].startswith("- 字段 `region`")
        assert outcome.task == "repair"
        assert outcome.requested == 1
        assert outcome.repair_used is False

    @pytest.mark.asyncio
    async def test_repair_sql_failure_is_bounded_to_one_call(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine({"repair": ["坏"]}, runtime, clock)
        with pytest.raises(SqlGenerationUnavailable):
            await engine.repair_sql(
                _ctx(), normalized_question=_QUESTION, plan=_plan(), error_digest="d"
            )
        assert len(llm.calls) == 1  # `repair_payload_factory=None`

    @pytest.mark.asyncio
    async def test_give_up_path_is_legal_and_explained(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`repairable=false` + `blocking_issues` = 资产鼓励的**放弃**路径。"""
        body = {
            "candidates": [],
            "blocking_issues": ["错误摘要不足以定位原因"],
            "repairable": False,
        }
        engine, _, _ = _engine({"repair": [json.dumps(body, ensure_ascii=False)]}, runtime, clock)
        outcome = await engine.repair_sql(
            _ctx(), normalized_question=_QUESTION, plan=_plan(), error_digest="只有一句话"
        )
        assert outcome.candidates == ()
        assert outcome.blocking_issues == ("错误摘要不足以定位原因",)
        assert outcome.primary is None

    @pytest.mark.asyncio
    async def test_give_up_without_explanation_is_rejected(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """放弃却不说明缺什么 = 空手而归 → 契约不允许。"""
        body = {"candidates": [], "blocking_issues": [], "repairable": False}
        engine, _, _ = _engine({"repair": [json.dumps(body, ensure_ascii=False)]}, runtime, clock)
        with pytest.raises(SqlGenerationUnavailable):
            await engine.repair_sql(
                _ctx(), normalized_question=_QUESTION, plan=_plan(), error_digest="d"
            )


# ============================================================================
# 四、`PlannerPort` 的薄包装
# ============================================================================

class TestPlannerPortSurface:
    @pytest.mark.asyncio
    async def test_structural_conformance_to_the_port(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        from app.core.contracts import PlannerPort

        engine, _, _ = _engine({"plan": [_plan_body()]}, runtime, clock)
        assert isinstance(engine, PlannerPort)

    @pytest.mark.asyncio
    async def test_build_plan_returns_a_state_shaped_mapping(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine({"plan": [_plan_body()]}, runtime, clock)
        result = await engine.build_plan(_QUESTION, [{"asset_id": "a1", "score": 0.9}], _ctx())
        assert set(result) == {"plan", "plan_summary", "prompt_version", "model_version"}
        assert result["prompt_version"] == "plan_v1"
        assert result["model_version"] == "deepseek-flash"
        # 候选**当前不进 prompt**（`plan_v1` 的 USER 段没有 `$candidates_block`）
        assert "candidates" not in llm.payload()

    @pytest.mark.asyncio
    async def test_generate_sql_requires_a_normalized_question(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """端口签名里没有这一位 ⇒ 缺失时**抛契约错误，不编一个**（编一个 = 基于错问题生成）。"""
        engine, llm, _ = _engine({"gen_sql": [_sql_body()]}, runtime, clock)
        with pytest.raises(PlannerError) as excinfo:
            await engine.generate_sql(json.loads(_plan_body()), _ctx(), candidates=1)
        assert "normalized_question" in str(excinfo.value)
        assert llm.calls == []  # 一个请求都没发

    @pytest.mark.asyncio
    async def test_generate_sql_accepts_the_engine_s_own_plan_payload(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """端口契约：`plan` 可以是 `plan_for().state_payload()` 的整份形状。"""
        engine, llm, _ = _engine({"plan": [_plan_body()], "gen_sql": [_sql_body()]}, runtime, clock)
        plan_state = await engine.build_plan(_QUESTION, [], _ctx())
        plan_state["normalized_question"] = _QUESTION
        result = await engine.generate_sql(plan_state, _ctx(), candidates=1)
        assert llm.tasks == ["plan", "gen_sql"]
        assert result["sql_text"].startswith("SELECT")

    @pytest.mark.asyncio
    async def test_generate_sql_refuses_when_the_plan_declares_blockers(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """计划自述有阻塞项 ⇒ 按资产规则 7 不出 SQL（宁可不输出，也不猜）。"""
        engine, llm, sink = _engine({"gen_sql": [_sql_body()]}, runtime, clock, sink=RecordingSink())
        blocked_plan = json.loads(_plan_body(metrics=[], blocking_issues=["缺关联路径"]))
        # 形状 = 图状态（嵌套 `plan` + 顶层 `normalized_question`）—— 见下一条用例的说明
        state_like = {"plan": blocked_plan, "normalized_question": _QUESTION}
        with pytest.raises(SqlGenerationUnavailable) as excinfo:
            await engine.generate_sql(state_like, _ctx(), candidates=1)
        assert excinfo.value.attempts == 0  # 没发请求，"从未尝试"≠"试了两次失败"
        assert excinfo.value.notes[0].detail["blocking_issues"] == ["缺关联路径"]
        assert llm.calls == []
        # 这条降级必须**真的送到 sink**（W4 的 SSE 通道）—— 它不是一个只挂在异常上的说明
        assert [n.detail.get("blocking_issues") for n in sink.notes] == [["缺关联路径"]]

    @pytest.mark.asyncio
    async def test_bare_plan_mapping_plus_a_question_is_NOT_accepted(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """🔴 `generate_sql` 的入参形状**只有一种**：嵌套 `plan` + 顶层 `normalized_question`。

        这条用例钉住一个很容易踩的坑：把"裸 `Plan` 形状"再塞一个 `normalized_question`
        键进去 —— 看起来最自然 —— **一定会失败**，因为 `Plan` 是 `extra="forbid"` 的，
        多出来的那个键就是"未登记字段"，整份拒收。

        ⇒ 给 W4 的口径写成一句话：**把图状态原样传进来**（`state` 里本就有
        `plan` 与 `normalized_question` 两个键），不要手工拼一个 plan dict。
        """
        from pydantic import ValidationError

        engine, llm, _ = _engine({"gen_sql": [_sql_body()]}, runtime, clock)
        bare_plan_plus_question = json.loads(_plan_body())
        bare_plan_plus_question["normalized_question"] = _QUESTION
        with pytest.raises(ValidationError):
            await engine.generate_sql(bare_plan_plus_question, _ctx(), candidates=1)
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_complexity_heuristic_picks_the_thinking_route(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`_looks_complex` 的自设启发式：计划里出现"排名/同比/占比…"信号 → 复杂档。"""
        complex_plan = _plan_body(filters=["使用窗口函数计算同比"])
        engine, llm, _ = _engine(
            {"plan": [complex_plan], "gen_sql_complex": [_sql_body()]}, runtime, clock
        )
        plan_state = await engine.build_plan(_QUESTION, [], _ctx())
        plan_state["normalized_question"] = _QUESTION
        await engine.generate_sql(plan_state, _ctx(), candidates=1)
        assert llm.tasks == ["plan", "gen_sql_complex"]

    @pytest.mark.asyncio
    async def test_simple_plan_stays_on_the_non_thinking_route(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        engine, llm, _ = _engine({"plan": [_plan_body()], "gen_sql": [_sql_body()]}, runtime, clock)
        plan_state = await engine.build_plan(_QUESTION, [], _ctx())
        plan_state["normalized_question"] = _QUESTION
        await engine.generate_sql(plan_state, _ctx(), candidates=1)
        assert llm.tasks == ["plan", "gen_sql"]


# ============================================================================
# 五、降级通道与调用隔离
# ============================================================================

class TestDegradationPlumbing:
    @pytest.mark.asyncio
    async def test_a_successful_repair_is_not_a_degradation(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """修复成功 ≠ 降级：`DegradedReason` 里没有"修复过一次"这种取值，

        把内部重试上报成降级会让前端弹出一个用户无从理解的提示（N-21 的另一面：
        该报的必须报，**不该报的也不许乱报**）。
        两次通道都必须是空的。
        """
        sink = RecordingSink()
        engine = PlannerEngine(
            llm=FakeLlmPort({"gen_sql": ["坏"], "repair": [_repair_body()]}),
            semantics=runtime,
            clock=clock,
            degradation=sink,
            monotonic=lambda: 1.0,
        )
        outcome = await engine.sql_for(_ctx(), normalized_question=_QUESTION, plan=_plan())
        assert outcome.attempts == 2 and outcome.repair_used is True
        assert outcome.degradations == ()
        assert sink.notes == []

    @pytest.mark.asyncio
    async def test_engine_resets_state_between_calls(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """一次失败调用不得把降级泄漏到下一次成功调用上（`_reset` 的作用）。"""
        sink = RecordingSink()
        llm = FakeLlmPort(
            {
                "normalize_intent": [
                    "坏",
                    "还是坏",  # 第一次调用：失败
                    _normalize_intent_body(intent="query"),  # 第二次调用：成功
                ]
            }
        )
        engine = PlannerEngine(
            llm=llm,
            semantics=runtime,
            clock=clock,
            degradation=sink,
            monotonic=lambda: 1.0,
        )
        with pytest.raises(UnderstandUnavailable):
            await engine.understand(_ctx(), _QUESTION)
        assert sink.notes  # 第一次的降级已经被 sink 收集

        ok = await engine.understand(_ctx(), _QUESTION)
        assert ok.attempts == 1
        assert ok.degradations == ()  # 关键：**不带**上一次的降级

    @pytest.mark.asyncio
    async def test_engine_emits_a_degrade_when_generation_gives_up(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        sink = RecordingSink()
        engine = PlannerEngine(
            llm=FakeLlmPort({"gen_sql": ["坏"], "repair": ["还坏"]}),
            semantics=runtime,
            clock=clock,
            degradation=sink,
            monotonic=lambda: 1.0,
        )
        with pytest.raises(SqlGenerationUnavailable) as excinfo:
            await engine.sql_for(_ctx(), normalized_question=_QUESTION, plan=_plan())
        assert len(sink.notes) == 1
        assert excinfo.value.notes == tuple(sink.notes)  # 同一条事件走了两条通道


class TestCallMeta:
    def test_merged_with_takes_the_producing_call_s_version(self) -> None:
        first = LlmCallMeta(
            model="deepseek-flash",
            prompt_version="gen_sql_v1",
            tokens=TokenUsage(input=10, output=5, total=15),
            cost_cny=Decimal("0.001"),
        )
        second = LlmCallMeta(
            model="deepseek-v4-pro",
            prompt_version="repair_v1",
            tokens=TokenUsage(input=20, output=8, total=28),
            cost_cny=Decimal("0.002"),
        )
        merged = first.merged_with(second)
        assert merged.prompt_version == "repair_v1"  # 产出者才是版本的所有者
        assert merged.model == "deepseek-v4-pro"
        assert merged.tokens.total == 43
        assert merged.cost_cny == Decimal("0.003")
        assert merged.calls == 2
