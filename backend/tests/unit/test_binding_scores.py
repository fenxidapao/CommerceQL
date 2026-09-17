"""`app/binding` 类型层单测（W3C，N-01：离线、不连网、不起服务）。

覆盖三件事，每件都对应一条上游硬约束：
- `RerankScore` 的**越界即失败**（PRD §12.9 约束①）与**必带打分器标识**（N-27 约束②）；
- **裸 float 进不了 L4 判定**（N-27 检查方式①）—— 含 `require_rerank_scores` 与
  `adopt_l4_candidates` 两道闸门；
- 解析失败**返回失败态**而不是抛异常（N-27 约束④：解析失败 → fail-safe 判 `ambiguous`）。
"""

from __future__ import annotations

import json

import pytest

from app.binding.context import (
    UNSET_SCOPE,
    BindingRequestScope,
    clear_binding_scope,
    current_binding_scope,
    set_binding_scope,
)
from app.binding.errors import BindingScoreMisuse
from app.binding.scores import (
    RerankScore,
    ScoreParseError,
    adopt_l4_candidates,
    parse_scores_json,
    require_rerank_scores,
)
from app.core.contracts import CandidateRef
from app.core.enums import BindingLayer

MODEL = "deepseek-flash"
PROMPT = "l4_score_v1"


def _score(candidate_id: str = "order_paid.receiver_city", value: float = 0.9) -> RerankScore:
    return RerankScore(
        candidate_id=candidate_id, value=value, model_id=MODEL, prompt_version=PROMPT
    )


class TestRerankScore:
    def test_valid_score_round_trips(self) -> None:
        s = _score()
        assert (s.candidate_id, s.value, s.model_id, s.prompt_version) == (
            "order_paid.receiver_city",
            0.9,
            MODEL,
            PROMPT,
        )

    @pytest.mark.parametrize("value", [1.0000001, -0.0001, 2.0, float("nan"), float("inf")])
    def test_out_of_range_is_a_parse_failure_not_a_clamp(self, value: float) -> None:
        """越界必须**报错**。截断会让"打分器已经不可信"这件事看起来正常（约束①）。"""
        with pytest.raises(ScoreParseError):
            _score(value=value)

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_is_rejected(self, value: bool) -> None:
        """`bool` 是 `int` 的子类 —— `True` 混进来当 1.0 是典型的"看起来对"。"""
        with pytest.raises(ScoreParseError):
            _score(value=value)

    @pytest.mark.parametrize("kwargs", [{"model_id": ""}, {"prompt_version": ""}])
    def test_scorer_identity_is_mandatory(self, kwargs: dict[str, str]) -> None:
        """缺打分器标识 → 分数不可比、τ 无绑定对象（N-27 约束②）。"""
        base = {"candidate_id": "a", "value": 0.5, "model_id": MODEL, "prompt_version": PROMPT}
        with pytest.raises(ScoreParseError):
            RerankScore(**{**base, **kwargs})  # type: ignore[arg-type]

    def test_boundaries_are_inclusive(self) -> None:
        assert _score(value=0.0).value == 0.0
        assert _score(value=1.0).value == 1.0


class TestTypeBarrier:
    @pytest.mark.parametrize("raw", [0.9, "0.9", None, {"value": 0.9}])
    def test_raw_values_are_rejected(self, raw: object) -> None:
        """N-27 检查方式①：`four_layer` 的 L4 入口只接受 `RerankScore`。"""
        with pytest.raises(BindingScoreMisuse):
            require_rerank_scores([raw])

    def test_typed_scores_pass(self) -> None:
        assert require_rerank_scores([_score()]) == (_score(),)


class TestAdoptL4Candidates:
    def test_adopts_only_candidates_declared_as_l4(self) -> None:
        """检索侧的分（`layer is None` / `dense`）**不得**被当成精排分 —— 这正是禁余弦要防的。"""
        refs = (
            CandidateRef(asset_id="order_paid.receiver_city", score=0.9, layer=BindingLayer.L4),
            CandidateRef(asset_id="shop.city", score=0.88, layer=BindingLayer.L4),
        )
        outcome = adopt_l4_candidates(refs, model_id=MODEL, prompt_version=PROMPT)
        assert outcome.ok
        assert [s.candidate_id for s in outcome.scores] == [
            "order_paid.receiver_city",
            "shop.city",
        ]

    @pytest.mark.parametrize("layer", [None, BindingLayer.L1, BindingLayer.L3])
    def test_unmarked_candidate_fails_safe(self, layer: BindingLayer | None) -> None:
        refs = (CandidateRef(asset_id="a", score=0.9, layer=layer),)
        outcome = adopt_l4_candidates(refs, model_id=MODEL, prompt_version=PROMPT)
        assert not outcome.ok
        assert outcome.reason is not None and outcome.reason.startswith("candidate_not_l4")

    def test_out_of_range_candidate_fails_safe(self) -> None:
        refs = (CandidateRef(asset_id="a", score=1.4, layer=BindingLayer.L4),)
        outcome = adopt_l4_candidates(refs, model_id=MODEL, prompt_version=PROMPT)
        assert not outcome.ok
        assert outcome.reason is not None and outcome.reason.startswith("score_invalid")

    def test_empty_candidates_fails_safe(self) -> None:
        assert not adopt_l4_candidates((), model_id=MODEL, prompt_version=PROMPT).ok


class TestParseScoresJson:
    EXPECTED = ("order_paid.receiver_city", "shop.city")

    def _payload(self, **overrides: object) -> str:
        items: list[dict[str, object]] = [
            {"candidate_id": "order_paid.receiver_city", "score": 0.91, "reason": "收货侧"},
            {"candidate_id": "shop.city", "score": 0.32},
        ]
        body: dict[str, object] = {"scores": items}
        body.update(overrides)
        return json.dumps(body, ensure_ascii=False)

    def test_happy_path_preserves_expected_order(self) -> None:
        outcome = parse_scores_json(
            self._payload(), expected_ids=self.EXPECTED, model_id=MODEL, prompt_version=PROMPT
        )
        assert outcome.ok
        assert [s.candidate_id for s in outcome.scores] == list(self.EXPECTED)
        assert outcome.scores[0].model_id == MODEL

    @pytest.mark.parametrize(
        ("raw", "reason_prefix"),
        [
            ("", "empty_text"),
            ("   ", "empty_text"),
            ("not json", "invalid_json"),
            ("[1,2,3]", "top_level_not_object"),
            ('{"items": []}', "missing_scores_key"),
            ('{"scores": {"a": 1}}', "scores_not_list"),
            ('{"scores": ["x"]}', "item_not_object"),
            ('{"scores": [{"candidate_id": "order_paid.receiver_city"}]}', "item_keys_invalid"),
            ('{"scores": [{"id": "a", "score": 1}]}', "item_keys_invalid"),
            ('{"scores": []}', "missing_candidates"),
        ],
    )
    def test_malformed_payloads_fail_but_do_not_raise(self, raw: str, reason_prefix: str) -> None:
        """解析失败是**返回值**，不是异常 —— 它的下游是 fail-safe 判 `ambiguous`（约束④）。"""
        outcome = parse_scores_json(
            raw, expected_ids=self.EXPECTED, model_id=MODEL, prompt_version=PROMPT
        )
        assert not outcome.ok
        assert outcome.reason is not None and outcome.reason.startswith(reason_prefix)

    def test_partial_coverage_is_rejected_not_partially_adopted(self) -> None:
        """缺一个候选的分 → 整体失败。部分采纳会把"近乎并列"误读成"明显占优"。"""
        raw = json.dumps({"scores": [{"candidate_id": "shop.city", "score": 0.5}]})
        outcome = parse_scores_json(
            raw, expected_ids=self.EXPECTED, model_id=MODEL, prompt_version=PROMPT
        )
        assert not outcome.ok
        assert outcome.reason is not None and "missing_candidates" in outcome.reason

    def test_duplicate_and_unknown_candidates_are_rejected(self) -> None:
        dup = json.dumps(
            {
                "scores": [
                    {"candidate_id": "shop.city", "score": 0.5},
                    {"candidate_id": "shop.city", "score": 0.6},
                ]
            }
        )
        assert not parse_scores_json(
            dup, expected_ids=self.EXPECTED, model_id=MODEL, prompt_version=PROMPT
        ).ok

        unknown = json.dumps(
            {
                "scores": [
                    {"candidate_id": "order_paid.receiver_city", "score": 0.5},
                    {"candidate_id": "shop.city", "score": 0.5},
                    {"candidate_id": "order_paid.buyer_id", "score": 0.5},
                ]
            }
        )
        outcome = parse_scores_json(
            unknown, expected_ids=self.EXPECTED, model_id=MODEL, prompt_version=PROMPT
        )
        assert not outcome.ok
        assert outcome.reason is not None and outcome.reason.startswith("unknown_candidate")

    def test_out_of_range_score_is_parse_failure(self) -> None:
        raw = json.dumps(
            {
                "scores": [
                    {"candidate_id": "order_paid.receiver_city", "score": 1.2},
                    {"candidate_id": "shop.city", "score": 0.3},
                ]
            }
        )
        outcome = parse_scores_json(
            raw, expected_ids=self.EXPECTED, model_id=MODEL, prompt_version=PROMPT
        )
        assert not outcome.ok
        assert outcome.reason is not None and "score_invalid" in outcome.reason


class TestBindingRequestScope:
    def test_unset_scope_is_visible_not_silent(self) -> None:
        clear_binding_scope()
        assert current_binding_scope() is UNSET_SCOPE
        assert not current_binding_scope().is_set

    def test_empty_question_counts_as_unset(self) -> None:
        """`BindingRequestScope()` 与"没设置"对 L2/L4 等价 —— 必须走同一条可见降级路径。"""
        clear_binding_scope()
        set_binding_scope(BindingRequestScope())
        assert not current_binding_scope().is_set

    def test_set_scope_carries_question(self) -> None:
        clear_binding_scope()
        set_binding_scope(BindingRequestScope(normalized_question="哪个城市卖得好"))
        assert current_binding_scope().is_set
        assert current_binding_scope().normalized_question == "哪个城市卖得好"
        clear_binding_scope()
