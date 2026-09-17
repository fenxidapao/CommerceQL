"""L4 打分生产者单测（W3C，N-01：**全离线**，用假 `LLMPort`）。

七块：

| 块 | 验什么 |
|---|---|
| **契约字面量** | `L4_TASK` / `MODEL_AUTO` 与 W3A 的 `LlmTask.L4_SCORE` / `router.MODEL_AUTO` **逐字相等**（两边各写一份的代价由此兜住） |
| **出站载荷** | 过**真网关**的 `EgressPayload.from_mapping` 与 `assert_no_forbidden_keys`；键集恰为 6 个；**无身份字段** |
| **prompt 渲染** | 用真资产 `l4_score_v1` 渲染不报错，且问句/候选**真的出现在**消息里（不是"设了值但模板没引用"） |
| **输出 schema** | 与解析器的键集**同源**（`L4_SCORE_ITEM_KEYS` 里每个键都在 schema 文本里）；文本含 `json`（`response_format` 的实测硬要求） |
| **正常路径** | 合法 JSON → `ok`；`model_id`/`prompt_version` **取自响应**而非配置（N-27 约束②：比的是实际打分器） |
| **失败路径** | 非法 JSON / 越界 / 缺候选 → `failed=True`（**产品结论**）；空输入 → 失败**且不发请求** |
| **异常透传** | `LlmRefused` / `LlmUpstreamError` **原样上抛**，不得被转成 `ambiguous`（D6） |
| **与判定层串联** | `score_l4` → `decide`：大分差 → `resolved_unique`；τ 绑定响应里的模型 + prompt 版本 |

⚠️ 本文件 import `app.llm` 是**允许且必要**的：`.importlinter` 明确把 `tests/` 排除在契约外，
而"两边各写一份字面量"必须靠测试交叉校验，否则 W3A 改 `LlmTask.L4_SCORE` 时没人会发现。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.binding.filters import FilterOutcome, resolve_concept
from app.binding.four_layer import TauConfig, decide
from app.binding.grain import GrainIndex
from app.binding.l4 import (
    L4_CONSTRAINTS,
    L4_OUTPUT_SCHEMA,
    L4_TASK,
    MODEL_AUTO,
    build_l4_payload,
    score_l4,
)
from app.binding.scores import L4_SCORE_ITEM_KEYS, ScoreOutcome
from app.core.contracts import LLMResponse, TokenUsage
from app.core.enums import BindingLayer, BindingState
from app.llm import router as llm_router
from app.llm.egress_guard import EgressPayload, assert_no_forbidden_keys
from app.llm.errors import LlmRefused, LlmUpstreamError
from app.llm.prompts import load_prompt, render_messages
from app.semantics import SemanticBundleRuntime, load_bundle

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"

QUESTION = "按城市看 GMV"
CANDIDATES = ("order_paid.receiver_city", "shop.city")

MODEL_ID = "deepseek-flash"
PROMPT_VERSION = "l4_score_v1"

#: 一份**合法**的打分器输出（0.8 vs 0.4 → 分差 0.4 ≥ τ+ε）。
GOOD_TEXT = (
    '{"scores": ['
    '{"candidate_id": "order_paid.receiver_city", "score": 0.8},'
    ' {"candidate_id": "shop.city", "score": 0.4}'
    "]}"
)


def _response(text: str, *, model: str = MODEL_ID, prompt_version: str = PROMPT_VERSION) -> LLMResponse:
    return LLMResponse(
        text=text,
        model=model,
        prompt_version=prompt_version,
        tokens=TokenUsage(input=10, output=10, cache_hit=0, total=20),
        cost_cny=Decimal("0.0001"),
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "question": QUESTION,
        "candidates": CANDIDATES,
        "semantic_summary": "资产 order_paid / shop 的列注释摘要",
        "bundle_version": "2026.09.14.1",
    }
    base.update(overrides)
    return build_l4_payload(**base)


@dataclass
class _FakePort:
    """假 `LLMPort`：记录调用并回放一个结果或抛一个异常。"""

    text: str = GOOD_TEXT
    model: str = MODEL_ID
    prompt_version: str = PROMPT_VERSION
    raises: Exception | None = None
    calls: list[tuple[str, dict[str, Any], str]] = field(default_factory=list)

    async def call(self, task: str, payload: Any, model: str = MODEL_AUTO) -> LLMResponse:
        self.calls.append((task, dict(payload), model))
        if self.raises is not None:
            raise self.raises
        return _response(self.text, model=self.model, prompt_version=self.prompt_version)

    def estimate_cost(self, payload: Any) -> Decimal:  # pragma: no cover - 本窗口不用
        return Decimal("0")


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


@pytest.fixture(scope="module")
def index(runtime: SemanticBundleRuntime) -> GrainIndex:
    return GrainIndex.build(runtime)


# ============================================================================
# 一、契约字面量：两边各写一份，靠这里兜住
# ============================================================================


class TestContractLiterals:
    def test_task_name_matches_w3a_enum(self) -> None:
        """`binding` 不能 import `app.llm`（R-DEP-2），故 task 名是本地字面量 —— 必须**逐字**相等。

        W3A 改 `LlmTask.L4_SCORE` 的值而没同步本模块时，本断言会红。
        """
        assert llm_router.LlmTask.L4_SCORE.value == L4_TASK

    def test_model_auto_matches_router_constant(self) -> None:
        assert llm_router.MODEL_AUTO == MODEL_AUTO

    def test_l4_task_is_known_to_router(self) -> None:
        """反向：把字面量喂回路由表，必须能解析出路由（否则网关直接 `LlmUnknownTask`）。"""
        route = llm_router.resolve_route(L4_TASK)
        assert route.task.value == L4_TASK

    def test_l4_route_is_deterministic_scorer(self) -> None:
        """PRD §12.9 约束①：温度 = 0。这是**打分器属性**，不能靠"记得设"。"""
        route = llm_router.resolve_route(L4_TASK)
        assert route.temperature == 0.0


# ============================================================================
# 二、出站载荷：过真网关的白名单
# ============================================================================


class TestPayload:
    def test_payload_passes_real_gateway_whitelist(self) -> None:
        """最强的一条：拿真网关的构造入口试 —— 未登记键会**抛**（严格模式，不静默丢弃）。"""
        payload = _payload()
        egress = EgressPayload.from_mapping(payload)  # 不抛即通过
        assert egress.raw_question == QUESTION
        assert tuple(egress.candidates) == CANDIDATES

    def test_payload_has_no_forbidden_keys(self) -> None:
        assert_no_forbidden_keys(_payload())  # 不抛即通过

    def test_payload_key_set_is_exactly_seven(self) -> None:
        """键集**恰为 7 个** —— 多一个是"以防万一"式的出站面扩大，少一个则是功能缺失。

        ⚠️ 这里刻意用**硬编码清单**而不是 `set(_payload())` 的自我比对：
        后者恒为真，什么也没验。清单是**断言**，不是实现。
        """
        assert set(_payload()) == {
            "raw_question",
            "candidates",
            "semantic_summary",
            "dialect_note",
            "output_schema",
            "constraints",
            "bundle_version",
        }

    def test_payload_never_carries_identity(self) -> None:
        """`user_id` / `tenant_id` / `task_id` **不得进 payload**（W3A RELAY §3 边界 1）。"""
        payload = _payload()
        for key in ("user_id", "tenant_id", "task_id", "trace_id", "session_id"):
            assert key not in payload

    def test_candidates_sent_as_sequence_not_string(self) -> None:
        """若传成字符串，网关会按字符逐个展开成 200 条垃圾候选 —— 静默且昂贵。"""
        payload = _payload(candidates=("a.b", "c.d"))
        assert payload["candidates"] == ["a.b", "c.d"]
        egress = EgressPayload.from_mapping(payload)
        assert tuple(egress.candidates) == ("a.b", "c.d")

    def test_stable_texts_are_constants(self) -> None:
        """`output_schema` / `constraints` 必须是**模块级常量**（前缀缓存的稳定性前提）。"""
        assert _payload()["output_schema"] is L4_OUTPUT_SCHEMA
        assert _payload()["constraints"] is L4_CONSTRAINTS


# ============================================================================
# 三、prompt 渲染：值真的被模板引用了
# ============================================================================


class TestPromptRendering:
    def test_real_asset_renders_with_our_payload(self) -> None:
        """用**真资产**渲染：模板里引用的每个变量都必须能被我们的 payload 填上。

        若模板引用了我们没发的字段，`_render_template` 会因未替换的 `$var` 失败 ——
        这条断言就是"两边字段集对得上"的机器检查。
        """
        egress = EgressPayload.from_mapping(_payload())
        messages, prompt_version = render_messages(load_prompt(L4_TASK), egress)
        assert prompt_version == "l4_score_v1"
        assert len(messages) == 2
        # 渲染后**不得**残留任何 `$var` 占位符
        assert "$" not in messages[0]["content"]
        assert "$" not in messages[1]["content"]

    def test_question_and_candidates_actually_reach_the_prompt(self) -> None:
        """🔴 防"设了值但模板没引用"：逐项验证内容**出现在**出站文本里。"""
        egress = EgressPayload.from_mapping(_payload())
        messages, _ = render_messages(load_prompt(L4_TASK), egress)
        user_text = messages[1]["content"]
        assert QUESTION in user_text
        for cid in CANDIDATES:
            assert cid in user_text

    def test_output_schema_mentions_json_for_response_format(self) -> None:
        """`response_format={"type":"json_object"}` 需要整体消息内含 "json"（W3A 实测：否则 400）。"""
        assert "json" in L4_OUTPUT_SCHEMA.lower()


# ============================================================================
# 四、输出 schema 与解析器同源
# ============================================================================


class TestOutputSchema:
    @pytest.mark.parametrize("key", sorted(L4_SCORE_ITEM_KEYS))
    def test_every_parser_key_is_named_in_the_prompt_schema(self, key: str) -> None:
        """解析器允许的键，必须在出站 schema 里**被点名** —— 否则模型会用别的键名。"""
        assert f'"{key}"' in L4_OUTPUT_SCHEMA

    def test_parser_rejects_unknown_keys_so_schema_must_be_exact(self) -> None:
        """反向确认这条同源关系的必要性：多一个键，解析器就整体判失败。"""
        from app.binding.scores import parse_scores_json

        outcome = parse_scores_json(
            '{"scores": [{"candidate_id": "a.b", "score": 0.5, "confidence": 0.9}]}',
            expected_ids=["a.b"],
            model_id=MODEL_ID,
            prompt_version=PROMPT_VERSION,
        )
        assert outcome.failed is True
        assert outcome.reason is not None and outcome.reason.startswith("item_keys_invalid")


# ============================================================================
# 五、正常路径
# ============================================================================


class TestScoreHappyPath:
    async def test_returns_ok_outcome_with_scores_in_expected_order(self) -> None:
        port = _FakePort()
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        assert outcome.ok is True
        assert [s.candidate_id for s in outcome.scores] == list(CANDIDATES)
        assert [s.value for s in outcome.scores] == [0.8, 0.4]

    async def test_calls_the_gateway_with_contract_task_and_auto_model(self) -> None:
        port = _FakePort()
        await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        task, payload, model = port.calls[0]
        assert (task, model) == (L4_TASK, MODEL_AUTO)
        assert payload["raw_question"] == QUESTION
        assert tuple(payload["candidates"]) == CANDIDATES

    async def test_scorer_identity_comes_from_the_response_not_the_config(self) -> None:
        """🔴 N-27 约束② 的关键：降级后实际用的模型必须进 `RerankScore`。

        若这里取配置里的值，τ 会以为自己在跟 flash 比，而实际分是 v4-pro 给的 ——
        τ 绑定校验就永远通过，形同虚设。
        """
        port = _FakePort(model="deepseek-v4-pro", prompt_version="l4_score_v2")
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        assert outcome.ok is True
        assert all(s.model_id == "deepseek-v4-pro" for s in outcome.scores)
        assert all(s.prompt_version == "l4_score_v2" for s in outcome.scores)

    async def test_semantic_summary_is_forwarded(self) -> None:
        port = _FakePort()
        await score_l4(
            port=port,
            question=QUESTION,
            candidates=CANDIDATES,
            semantic_summary="SUMMARY-MARKER",
            bundle_version="2026.09.14.1",
        )
        payload = port.calls[0][1]
        assert payload["semantic_summary"] == "SUMMARY-MARKER"
        assert payload["bundle_version"] == "2026.09.14.1"


# ============================================================================
# 六、失败路径：产品结论，不是异常
# ============================================================================


class TestScoreFailurePaths:
    async def test_invalid_json_is_a_failed_outcome(self) -> None:
        port = _FakePort(text="这不是 JSON")
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        assert outcome.ok is False
        assert outcome.reason is not None and outcome.reason.startswith("invalid_json")

    async def test_out_of_range_score_is_a_failed_outcome(self) -> None:
        """PRD §12.9 约束①：越界 = 解析失败（**不是截断**）。"""
        port = _FakePort(
            text='{"scores": [{"candidate_id": "a.b", "score": 1.5},'
            ' {"candidate_id": "c.d", "score": 0.2}]}'
        )
        outcome = await score_l4(port=port, question=QUESTION, candidates=("a.b", "c.d"))
        assert outcome.ok is False
        assert outcome.reason is not None and "score_invalid" in outcome.reason

    async def test_missing_candidate_is_a_failed_outcome(self) -> None:
        """只给了一半候选的分 → 分差不可算 → 整体无效（不做部分采纳）。"""
        port = _FakePort(text='{"scores": [{"candidate_id": "order_paid.receiver_city", "score": 0.9}]}')
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        assert outcome.ok is False
        assert outcome.reason is not None and outcome.reason.startswith("missing_candidates")

    async def test_blank_question_fails_without_calling_the_gateway(self) -> None:
        """空输入本地拦掉：**不浪费一次出站**（也是不把空串送进 prompt 的兜底）。"""
        port = _FakePort()
        outcome = await score_l4(port=port, question="   ", candidates=CANDIDATES)
        assert outcome == ScoreOutcome(failed=True, reason="empty_question")
        assert port.calls == []

    async def test_no_usable_candidates_fails_without_calling_the_gateway(self) -> None:
        port = _FakePort()
        outcome = await score_l4(port=port, question=QUESTION, candidates=("", ""))
        assert outcome.failed is True
        assert outcome.reason == "no_candidates"
        assert port.calls == []

    async def test_failed_outcome_carries_no_scores(self) -> None:
        port = _FakePort(text="{}")
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        assert outcome.scores == ()


# ============================================================================
# 七、异常透传：D6 —— 系统故障不得被包装成"澄清"
# ============================================================================


class TestExceptionPropagation:
    async def test_llm_refused_propagates_untouched(self) -> None:
        """`LlmRefused` 是**产品终态 `refuse`**（07 §10.2 最后一行），必须原样交给 W4。

        本模块**没有** `except LlmError`，所以"原样上抛"不依赖任何 `raise` 语句 ——
        不存在"忘了重新抛"这种失效方式。
        """
        refused = LlmRefused("降级链走完仍无产出")
        port = _FakePort(raises=refused)
        with pytest.raises(LlmRefused) as exc:
            await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        assert exc.value is refused

    async def test_upstream_error_is_not_converted_to_ambiguous(self) -> None:
        """🔴 **D6 的核心断言**：5xx 是系统故障，不是"这个歧义我判不了"。

        若源码里出现 `except LlmError` 把它转成 `ScoreOutcome(failed=True)`，
        一次上游抖动就会变成一句"请澄清"——用产品结论掩盖故障（本项目红线）。
        """
        port = _FakePort(raises=LlmUpstreamError("上游 5xx", detail={"status": 503}))
        with pytest.raises(LlmUpstreamError):
            await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)

    async     def test_module_has_no_llm_error_catch(self) -> None:
        """把 D6 钉在**源码结构**上：一旦有人加 `except LlmError`，本断言立刻红。

        （行为断言只能覆盖"我测到的那几种异常"，这条覆盖"任何未来的捕获"。）

        ⚠️ 用 **AST** 而不是扫文本：本模块 docstring 里**就写着** "不写 `except LlmError`"，
        文本匹配会把那句散文当成违规；AST 只看真正的 `ast.Try` 处理器，散文免疫。
        同时它能抓到 `except (LlmRefused, LlmError)` / `except llm.LlmError` 这类变体。
        """
        source = (Path(__file__).resolve().parents[2] / "app" / "binding" / "l4.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        def handler_names(node: ast.expr | None) -> list[str]:
            if node is None:  # `except:` —— 裸捕获，连它一起禁（会连 KeyboardInterrupt 一起吞）
                return ["<bare>"]
            if isinstance(node, ast.Tuple):
                return [name for elt in node.elts for name in handler_names(elt)]
            if isinstance(node, ast.Name):
                return [node.id]
            if isinstance(node, ast.Attribute):
                return [node.attr]
            return [ast.dump(node)]

        catches = [
            name
            for try_node in ast.walk(tree)
            if isinstance(try_node, ast.Try)
            for handler in try_node.handlers
            for name in handler_names(handler.type)
        ]
        assert not [name for name in catches if "Llm" in name or name == "<bare>"]


# ============================================================================
# 八、与判定层串联：产物同一个类型，判定层不区分来源
# ============================================================================


class TestIntegrationWithFourLayer:
    async def test_big_gap_end_to_end_resolves_unique(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        resolution = resolve_concept("城市", runtime)
        assert resolution is not None and resolution.declared_ambiguous is True
        port = _FakePort()
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        decision = decide(
            resolution,
            FilterOutcome(ordered=CANDIDATES),
            grain_index=index,
            question_grain=index.question_level(QUESTION),
            tau=TauConfig(
                value=0.20,
                epsilon=0.05,
                model_id=MODEL_ID,
                prompt_version=PROMPT_VERSION,
                calibrated_at="2026-09-17T00:00:00Z",
            ),
            l4=outcome,
        )
        assert (decision.state, decision.layer) == (
            BindingState.RESOLVED_UNIQUE,
            BindingLayer.L4,
        )
        assert decision.bindings[0].asset_id == CANDIDATES[0]

    async def test_tau_bound_to_a_different_prompt_raises(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """端到端的 N-27 约束②：τ 绑 `v1`、实际打分器回 `v2` → **抛**，不是静默放行。"""
        from app.binding.errors import BindingTauScorerMismatch

        resolution = resolve_concept("城市", runtime)
        port = _FakePort(prompt_version="l4_score_v2")
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        with pytest.raises(BindingTauScorerMismatch):
            decide(
                resolution,
                FilterOutcome(ordered=CANDIDATES),
                grain_index=index,
                question_grain=None,
                tau=TauConfig(
                    value=0.20,
                    epsilon=0.05,
                    model_id=MODEL_ID,
                    prompt_version=PROMPT_VERSION,
                    calibrated_at="2026-09-17T00:00:00Z",
                ),
                l4=outcome,
            )

    async def test_failed_outcome_end_to_end_clarifies(
        self, runtime: SemanticBundleRuntime, index: GrainIndex
    ) -> None:
        """解析失败 → 端到端必须是 `ambiguous` + 澄清候选（N-27 约束④）。"""
        resolution = resolve_concept("城市", runtime)
        port = _FakePort(text="oops")
        outcome = await score_l4(port=port, question=QUESTION, candidates=CANDIDATES)
        decision = decide(
            resolution,
            FilterOutcome(ordered=CANDIDATES),
            grain_index=index,
            question_grain=None,
            tau=TauConfig(value=0.20, epsilon=0.05),
            l4=outcome,
        )
        assert decision.state is BindingState.AMBIGUOUS
        assert [b.asset_id for b in decision.bindings] == list(CANDIDATES)
        assert decision.clarify_prompt is not None
