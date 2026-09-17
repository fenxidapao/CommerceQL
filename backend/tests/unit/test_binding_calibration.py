"""τ / ε 校准脚手架单测（W3C，N-01：**全离线、纯函数**）。

五块：

| 块 | 验什么 |
|---|---|
| **输入校验** | 候选 < 2 / 重复 < 3 / 长度不齐 / 分数越界 / 金标准不在候选 → 构造期 `ValueError`（夹具错要当场炸） |
| **Kendall τ-b** | 与**手算的已知值**对照（含并列修正），不是"跑通就算过" |
| **稳定性门槛** | 分差 std ≥ 分辨率 → `UNSTABLE`；判据用 **max** 而非均值；Kendall **只报告不判定** |
| **扫描** | 曲线单调形状、τ=0 起点存在、三列指标的分母语义、`None` 与 `0.0` 可区分 |
| **端到端 `calibrate`** | 稳定性未过 → **不给 τ 候选** + 升级动作；达标 → 选点保守；NFR-7.1 不达标 → 动作指向**语义层**而非换 τ |
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from app.binding.calibration import (
    CLARIFY_RATE_LIMIT,
    MIN_REPEATS,
    TAU_SWEEP_STEP,
    ScoreSample,
    StabilityVerdict,
    assess_stability,
    calibrate,
    kendall_tau_b,
    sweep,
)


def _sample(
    sample_id: str,
    scores: tuple[float, ...],
    *,
    gold: str | None,
    candidates: tuple[str, ...] | None = None,
    noise: tuple[float, ...] | None = None,
    repeats: int = MIN_REPEATS,
) -> ScoreSample:
    """构造一条样本：`scores` 是第 1 次重复，后续重复**按 ± 交替**施加 `noise`（`[0, +n, −n, +n, …]`）。

    ⚠️ 交替，而不是"后续重复同向偏移"。原来的同向写法有两个坑，本文件**两个都踩到过**：

    1. **分差恒非负**（`Δ = 最高 − 次高 ≥ 0`）。对两个候选**同向**施加同一偏移不改变分差，
       于是 `noise` 对"分差方差"这个被测量的影响恒为 0 —— 参数形同虚设，
       而写测试的人会以为自己已经造出了"分数在抖"的样本。
    2. `repeats=3` 时同向偏移只得到 **2 个不同取值**（第 2、3 次逐字相同）：
       声明 3 次重复、实际 2 点样本，方差被系统性低估 —— 而这里判的正是方差够不够小。

    交替后有一个**可直接手算**的结论：两候选样本的分差序列恰为 `[g, g+d, g−d]`，
    其中 `d = noise[0] − noise[1]`，其**样本**标准差恰为 `|d|`（`g` 被消掉）。
    """
    ids = candidates or tuple(f"c{i}" for i in range(len(scores)))
    offsets = noise or tuple(0.0 for _ in scores)
    rows = [tuple(scores)]
    for index in range(1, repeats):
        sign = 1.0 if index % 2 else -1.0
        rows.append(tuple(s + sign * d for s, d in zip(scores, offsets, strict=True)))
    return ScoreSample(
        sample_id=sample_id,
        candidate_ids=ids,
        repeats=tuple(rows),
        gold_candidate_id=gold,
    )


# ============================================================================
# 一、输入校验
# ============================================================================


class TestScoreSampleValidation:
    def test_single_candidate_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="候选少于 2 个"):
            ScoreSample(sample_id="s", candidate_ids=("a",), repeats=((0.9,),) * 3)

    def test_duplicate_candidate_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="重复 id"):
            ScoreSample(sample_id="s", candidate_ids=("a", "a"), repeats=((0.9, 0.1),) * 3)

    def test_too_few_repeats_rejected(self) -> None:
        with pytest.raises(ValueError, match="n ≥ 3"):
            ScoreSample(sample_id="s", candidate_ids=("a", "b"), repeats=((0.9, 0.1),) * 2)

    def test_ragged_repeat_rejected(self) -> None:
        with pytest.raises(ValueError, match="不一致"):
            ScoreSample(
                sample_id="s",
                candidate_ids=("a", "b"),
                repeats=((0.9, 0.1), (0.9,), (0.9, 0.1)),
            )

    @pytest.mark.parametrize("bad", [1.4, -0.01, float("nan"), float("inf")])
    def test_out_of_range_score_rejected(self, bad: float) -> None:
        """越界不是"截断"，是**夹具错** —— 按 PRD §12.9 约束① 它是解析失败。"""
        with pytest.raises(ValueError, match="非法分数"):
            ScoreSample(sample_id="s", candidate_ids=("a", "b"), repeats=((bad, 0.1),) * 3)

    def test_gold_outside_candidates_rejected(self) -> None:
        with pytest.raises(ValueError, match="金标准"):
            ScoreSample(
                sample_id="s",
                candidate_ids=("a", "b"),
                repeats=((0.9, 0.1),) * 3,
                gold_candidate_id="c",
            )

    def test_gold_none_means_should_clarify(self) -> None:
        assert _sample("s", (0.9, 0.1), gold=None).gold_should_clarify is True
        assert _sample("s", (0.9, 0.1), gold="c0").gold_should_clarify is False

    def test_gap_and_ranking(self) -> None:
        sample = _sample("s", (0.30, 0.90, 0.60), gold="c1")
        assert sample.gap(0) == pytest.approx(0.30)
        assert sample.ranking(0) == ("c1", "c2", "c0")

    def test_tied_scores_have_zero_gap(self) -> None:
        assert _sample("s", (0.5, 0.5), gold=None).gap(0) == 0.0


# ============================================================================
# 二、Kendall τ-b：与手算值对照
# ============================================================================


class TestKendallTauB:
    def test_identical_rankings(self) -> None:
        assert kendall_tau_b([0.9, 0.5, 0.1], [0.8, 0.4, 0.2]) == pytest.approx(1.0)

    def test_reversed_rankings(self) -> None:
        """完全反转 → −1.0（分子 = −3，分母 = 3）。"""
        assert kendall_tau_b([0.9, 0.5, 0.1], [0.1, 0.5, 0.9]) == pytest.approx(-1.0)

    def test_single_discordant_pair_of_three(self) -> None:
        """3 个元素、3 对、1 对不一致 → `(2 − 1) / 3`。"""
        assert kendall_tau_b([0.9, 0.5, 0.1], [0.9, 0.1, 0.5]) == pytest.approx(1 / 3)

    def test_tie_in_one_side_uses_b_variant(self) -> None:
        """`x` 有一对并列、`y` 无并列 → 分母带 `n₁` 修正（**b 变体**的定义）。

        `x = [9,5,5]`：并列修正 `n₁ = 1`；`n₀ = 3` → 分母 `sqrt((3−1)(3−0)) = sqrt(6)`。
        一致的只有 `(x₁,x₂)` 与 `(x₁,x₃)` 两对 → 分子 `2`。
        """
        assert kendall_tau_b([0.9, 0.5, 0.5], [0.9, 0.5, 0.1]) == pytest.approx(2 / math.sqrt(6))

    def test_all_tied_returns_one(self) -> None:
        """全体并列 → 两边都没给出排序信息，返回 1.0（不是 undefined/nan）。"""
        assert kendall_tau_b([0.5, 0.5], [0.5, 0.5]) == 1.0

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="长度必须一致"):
            kendall_tau_b([0.9, 0.1], [0.9, 0.5, 0.1])

    def test_four_element_known_value(self) -> None:
        """4 元素、6 对、**1 对不一致** → `(5 − 1) / 6 = 2/3`。

        ⚠️ 手算时容易只盯首尾两个元素（首端一致、末端不一致）就数成"2 对不一致"——
        中间 `(1,2)` / `(1,3)` 两对也都一致，必须**逐对**数清。
        （初版本用例就写错成 `2/6`，被实现反证：实得 `0.6667`。）
        """
        assert kendall_tau_b([0.9, 0.8, 0.2, 0.1], [0.9, 0.7, 0.1, 0.2]) == pytest.approx(4 / 6)


# ============================================================================
# 三、约束 5：稳定性门槛
# ============================================================================


class TestStabilityGate:
    def test_zero_variance_is_stable(self) -> None:
        samples = [
            _sample("a", (0.9, 0.4), gold="c0"),
            _sample("b", (0.8, 0.7), gold="c0"),
        ]
        report = assess_stability(samples)
        assert report.verdict is StabilityVerdict.STABLE
        assert report.is_calibratable is True
        assert report.max_gap_std == 0.0
        assert report.repeats == MIN_REPEATS

    def test_variance_at_resolution_scale_is_unstable(self) -> None:
        """分差 std ≥ 步长 0.05 → **不可信**（§C.4.6 约束 5 原文的"同量级"）。"""
        noisy = _sample("a", (0.90, 0.40), gold="c0", noise=(0.10, -0.10), repeats=3)
        report = assess_stability([noisy])
        assert report.verdict is StabilityVerdict.UNSTABLE
        assert report.max_gap_std >= TAU_SWEEP_STEP
        assert report.is_calibratable is False

    def test_gate_uses_max_not_mean(self) -> None:
        """一条极噪声样本 + 多条干净样本 → **仍判 UNSTABLE**。

        用均值会把单条噪声平均掉，而判据问的是"这份校准能不能信" ——
        一条不可复现的样本足以让某个结论不可复现。
        """
        clean = [_sample(f"clean{i}", (0.9, 0.1), gold="c0") for i in range(9)]
        # 分差 [0.35, 0.55, 0.15] → 样本 std = |0.10 − (−0.10)| = 0.20；最高分 0.90+0.10 = 1.00 仍在 [0,1]
        noisy = _sample("noisy", (0.90, 0.55), gold="c0", noise=(0.10, -0.10), repeats=3)
        report = assess_stability([*clean, noisy])
        assert report.verdict is StabilityVerdict.UNSTABLE
        assert report.max_gap_std == pytest.approx(0.20)
        mean_std = sum(item.gap_std for item in report.samples) / len(report.samples)
        assert mean_std == pytest.approx(0.02)  # 10 条里 9 条 std=0，单条噪声被摊薄十倍
        assert mean_std < TAU_SWEEP_STEP < report.max_gap_std  # 均值会放行，max 不会

    def test_kendall_is_reported_but_does_not_gate(self) -> None:
        """排名反转但**分差恒定** → std=0 → STABLE，而 Kendall 如实报 −1。

        这不是漏洞：约束 5 把方差列在判据侧、把 Kendall 列在报告侧。把 Kendall 也做成门槛
        = **加了一条文档没有的规则**。本断言把这条边界钉住，免得后来者"顺手补上"。
        """
        sample = ScoreSample(
            sample_id="flip",
            candidate_ids=("a", "b"),
            repeats=((0.9, 0.1), (0.1, 0.9), (0.9, 0.1)),
        )
        report = assess_stability([sample])
        assert report.verdict is StabilityVerdict.STABLE
        assert report.min_kendall == pytest.approx(-1.0)

    def test_sample_detail_is_per_sample(self) -> None:
        report = assess_stability([_sample("a", (0.9, 0.1), gold="c0")])
        detail = report.samples[0]
        assert detail.sample_id == "a"
        assert detail.gaps == (pytest.approx(0.8),) * 3
        assert detail.kendalls[0] == 1.0
        assert detail.is_stable is True

    def test_empty_input_rejected(self) -> None:
        with pytest.raises(ValueError, match="至少一条样本"):
            assess_stability([])

    def test_stdev_uses_sample_denominator(self) -> None:
        """`n−1` 口径：分差 `[0.00, 0.10, 0.20]` → 样本 std `0.10`；**总体口径只会给 `0.0816`**。

        ⚠️ 初版这条断言写的是"'[d, −d, 0] 的 std 应等于 d'"，从而期望 0.1 —— 那个推理错在
        **把分差当成有正负的偏差**：`Δ = 最高 − 次高` 恒 `≥ 0`，`(0.6,0.5)/(0.4,0.5)/(0.5,0.5)`
        的真实分差是 `[0.1, 0.1, 0.0]`，样本 std 只有 `0.0577`（实测值）。
        故本用例改成让**均值不等于中间那个值**（`[0, 0.1, 0.2]`）——
        这时两个分母才真的分得开：`0.10` vs `0.0816`。
        """
        sample = ScoreSample(
            sample_id="s",
            candidate_ids=("a", "b"),
            repeats=((0.50, 0.50), (0.60, 0.50), (0.70, 0.50)),
        )
        detail = assess_stability([sample]).samples[0]
        assert detail.gaps == pytest.approx((0.00, 0.10, 0.20))
        # 偏差 [−0.1, 0, +0.1] → 平方和 0.02 → 样本(÷2) 0.10；总体(÷3) 0.0816（**低估**方差）
        assert detail.gap_std == pytest.approx(0.10)
        assert detail.gap_std > math.sqrt(0.02 / 3)


# ============================================================================
# 四、扫描
# ============================================================================


class TestSweep:
    def test_curve_spans_zero_to_one_inclusive(self) -> None:
        points = sweep([_sample("a", (0.9, 0.1), gold="c0")], epsilon=0.05)
        assert len(points) == 21
        assert points[0].tau == 0.0
        assert points[-1].tau == pytest.approx(1.0)

    def test_higher_tau_never_reduces_clarify_rate(self) -> None:
        """澄清率随 τ **单调不减**：τ 越高，越难满足 `Δ ≥ τ+ε`。"""
        samples = [
            _sample("a", (0.90, 0.40), gold="c0"),  # 分差 0.50
            _sample("b", (0.60, 0.50), gold="c1"),  # 分差 0.10 → 最先落进澄清侧
            _sample("c", (0.55, 0.10), gold="c0"),  # 分差 0.45
        ]
        rates = [point.clarify_rate for point in sweep(samples, epsilon=0.05)]
        # ⚠️ 用 `pairwise`，**不要**写 `zip(rates, rates[1:], strict=True)`：后者两个序列长度不等，
        # `strict=True` 会直接抛 ValueError —— 初版就是在这儿炸的，红的其实是测试自己。
        assert all(later >= earlier - 1e-12 for earlier, later in pairwise(rates))
        # 两端确有差别，避免"全程恒等值"把单调性蒙过去（τ=0 全判唯一 → 0.0；τ=1 全落邻域 → 1.0）
        # ⚠️ 这里刻意用**分差明显不等于 ε** 的样本：若取 `(0.60, 0.55)`，`0.60 − 0.55` 在 IEEE-754 下是
        # `0.049999999999999933 < 0.05`，τ=0 就已经判澄清 —— 那属于边界现象，已由 four_layer 的专门
        # 边界用例（二进制可精确表示的 τ/ε）钉住，不该混进本用例干扰单调性判读。
        assert rates[0] == 0.0
        assert rates[-1] == pytest.approx(1.0)

    def test_accuracy_denominator_is_decided_count(self) -> None:
        """`binding_accuracy` 的分母是**判为唯一的条数**，不是样本总数。

        两个样本：一个大分差（判唯一且判对）、一个小分差（落邻域 → 澄清）。
        小 τ 下应得 `decided=1, accuracy=1.0, clarify_rate=0.5`。
        """
        samples = [
            _sample("a", (0.90, 0.10), gold="c0"),
            _sample("b", (0.50, 0.48), gold="c1"),
        ]
        point = sweep(samples, epsilon=0.05)[0]
        assert point.tau == 0.0
        assert point.decided == 1
        assert point.binding_accuracy == pytest.approx(1.0)
        assert point.clarify_rate == pytest.approx(0.5)

    def test_wrong_decision_lowers_accuracy(self) -> None:
        samples = [_sample("a", (0.90, 0.10), gold="c1")]
        point = sweep(samples, epsilon=0.05)[0]
        assert point.binding_accuracy == pytest.approx(0.0)

    def test_none_versus_zero_are_distinguishable(self) -> None:
        """**空分母给 `None`，不给 `0.0`** —— `0.0` 会被读成"完全达标"。"""
        sample = _sample("a", (0.50, 0.48), gold="c0")  # 落邻域 → 永不判唯一
        points = sweep([sample], epsilon=0.05)
        assert points[0].decided == 0
        assert points[0].binding_accuracy is None
        # 分差 0.02 恒落邻域 → 全程澄清
        assert all(point.clarify_rate == 1.0 for point in points)

    def test_safety_side_error_is_counted(self) -> None:
        """金标准为"该澄清"却被判唯一 → 计入 `should_clarify_but_did_not`。"""
        sample = _sample("a", (0.95, 0.05), gold=None)
        point = sweep([sample], epsilon=0.05)[0]
        assert point.should_clarify_total == 1
        assert point.should_clarify_but_did_not == pytest.approx(1.0)

    def test_safety_side_metric_is_none_without_such_samples(self) -> None:
        sample = _sample("a", (0.95, 0.05), gold="c0")
        point = sweep([sample], epsilon=0.05)[0]
        assert point.should_clarify_total == 0
        assert point.should_clarify_but_did_not is None

    def test_zero_epsilon_rejected(self) -> None:
        with pytest.raises(ValueError, match="epsilon 必须 > 0"):
            sweep([_sample("a", (0.9, 0.1), gold="c0")], epsilon=0.0)


# ============================================================================
# 五、端到端 calibrate
# ============================================================================


def _clean_samples() -> list[ScoreSample]:
    """7 条：5 条大分差且判对、1 条小分差（恒澄清）、1 条本该澄清的大分差（安全侧错误）。

    ⚠️ **为什么是 7 条而不是 5 条**：NFR-7.1 上限 15% 的分母是**样本总数**，而这里恒有 1 条
    落邻域、永远澄清。7 条 → `1/7 ≈ 0.1429 ≤ 0.15` 达标；5 条同构样本只会给 `1/5 = 0.20`，
    **被上限判罚是正确的**（故改的是夹具，不是实现 —— 见 `_over_limit_samples`）。
    """
    return [
        _sample("a", (0.95, 0.20), gold="c0"),
        _sample("b", (0.90, 0.15), gold="c0"),
        _sample("c", (0.80, 0.10), gold="c0"),
        _sample("d", (0.60, 0.58), gold="c0"),  # 分差 0.02 → 恒落邻域（ε=0.05）
        _sample("e", (0.88, 0.12), gold=None),  # 本该澄清（计入安全侧错误，不改变澄清率）
        _sample("f", (0.85, 0.05), gold="c0"),
        _sample("g", (0.70, 0.20), gold="c0"),
    ]


def _over_limit_samples() -> list[ScoreSample]:
    """5 条里 1 条恒澄清 → 最小可表示澄清率 `1/5 = 0.20 > 0.15`，**NFR-7.1 不达标**。

    形态：4 条大分差（3 条判对 + 1 条本该澄清）+ 1 条分差 0.02 恒落邻域。
    它同时是"**样本太少，以致最小可表示澄清率本身就超过上限**"的样本 ——
    用来钉住"不达标 ⇒ 不可定稿"，也正是 `_clean_samples` 必须扩到 7 条的原因。
    """
    return [
        _sample("a", (0.95, 0.20), gold="c0"),
        _sample("b", (0.90, 0.15), gold="c0"),
        _sample("c", (0.80, 0.10), gold="c0"),
        _sample("d", (0.60, 0.58), gold="c0"),
        _sample("e", (0.88, 0.12), gold=None),
    ]


def _tiny_samples() -> list[ScoreSample]:
    """5 条分差 0.01（< ε=0.02）→ **全程澄清**，澄清率恒 100%。"""
    return [_sample(f"s{i}", (0.50, 0.49), gold="c0") for i in range(5)]


class TestCalibrate:
    def test_stable_run_selects_a_tau(self) -> None:
        report = calibrate(
            _clean_samples(),
            epsilon=0.05,
            accuracy_target=0.5,
            model_id="deepseek-flash",
            prompt_version="l4_score_v1",
            calibrated_at="2026-09-17T00:00:00Z",
            holdout_separated=True,
            layer_distribution={"L1": 40, "L2": 5, "L3": 20, "L4": 35},
        )
        assert report.stability.verdict is StabilityVerdict.STABLE
        assert report.selected_tau is not None
        assert report.escalation_required is False
        assert report.selected_point is not None

    def test_unstable_run_gives_no_tau_and_requires_escalation(self) -> None:
        """约束 5：稳定性未过 → **禁止定稿**（不给 τ 候选）+ 必须升级方案 A。"""
        # 分差 [0.40, 0.60, 0.20] → 样本 std 0.20 ≥ 0.05 → UNSTABLE（最高分 0.90+0.10 = 1.00 仍在 [0,1]）
        noisy = _sample("a", (0.90, 0.50), gold="c0", noise=(0.10, -0.10), repeats=3)
        report = calibrate([noisy, *_clean_samples()], epsilon=0.05, accuracy_target=0.5)
        assert report.stability.verdict is StabilityVerdict.UNSTABLE
        assert report.selected_tau is None
        assert report.selected_point is None
        assert report.escalation_required is True
        assert any("禁止定稿" in action for action in report.blocking_actions)
        assert any("方案 A" in action for action in report.blocking_actions)
        assert report.is_finalizable is False
        # 曲线仍然给出来 —— 它是"该升级打分器"的证据
        assert len(report.points) == 21

    def test_selection_prefers_the_smallest_clarify_rate(self) -> None:
        report = calibrate(_clean_samples(), epsilon=0.05, accuracy_target=0.5)
        assert report.selected_point is not None
        eligible = [
            p
            for p in report.points
            if p.binding_accuracy is not None and p.binding_accuracy >= 0.5
        ]
        best = min(p.clarify_rate for p in eligible)
        assert report.selected_point.clarify_rate == pytest.approx(best)

    def test_tie_break_is_conservative(self) -> None:
        """并列最小澄清率时取 **τ 更大**（要求更强证据），不是更小。

        `clarify_rate` 关于 τ 单调不减，故并列点必是"同一分类结果的连续区间"；
        取右端 = 对未来样本要求更强证据 = 保守侧。
        """
        report = calibrate(_clean_samples(), epsilon=0.05, accuracy_target=0.5)
        assert report.selected_point is not None
        same_rate = [
            p
            for p in report.points
            if p.clarify_rate == pytest.approx(report.selected_point.clarify_rate)
            and p.binding_accuracy is not None
            and p.binding_accuracy >= 0.5
        ]
        assert report.selected_tau == max(p.tau for p in same_rate)

    def test_high_clarify_rate_points_the_action_at_the_semantic_layer(self) -> None:
        """NFR-7.1 超标 → 动作必须指向**语义层**，不是"换个 τ"（N-25 / R-19）。"""
        report = calibrate(_tiny_samples(), epsilon=0.02, accuracy_target=0.5)
        assert report.nfr71_satisfied is False
        assert report.selected_tau is None  # 没有任何点判过唯一 → 无 eligible
        assert any("回看语义包" in action for action in report.blocking_actions)
        assert any("不是**放宽 τ**" in action or "不是" in action for action in report.blocking_actions)

    def test_no_action_when_everything_is_in_place(self) -> None:
        report = calibrate(
            _clean_samples(),
            epsilon=0.05,
            accuracy_target=0.5,
            model_id="deepseek-flash",
            prompt_version="l4_score_v1",
            calibrated_at="2026-09-17T00:00:00Z",
            holdout_separated=True,
            layer_distribution={"L1": 1, "L2": 2, "L3": 0, "L4": 4},
        )
        assert report.blocking_actions == ()
        assert report.is_finalizable is True

    def test_over_limit_clarify_rate_blocks_finalization(self) -> None:
        """NFR-7.1 没达标 → **不可定稿**：步骤 4 的定稿分支以"满足上限"为前提。

        ⚠️ 这条钉的是一致性：`blocking_actions` 已经写了"澄清率超限 → 回看语义层"，
        `is_finalizable` 就不能同时说可以定稿 —— 使用者只会看后者。
        （注意此处**稳定性是通过的**，所以卡住的确实是 NFR，不是约束 5。）
        """
        report = calibrate(
            _over_limit_samples(),
            epsilon=0.05,
            accuracy_target=0.5,
            model_id="deepseek-flash",
            prompt_version="l4_score_v1",
            calibrated_at="2026-09-17T00:00:00Z",
            holdout_separated=True,
            layer_distribution={"L1": 1, "L4": 4},
        )
        assert report.stability.is_calibratable is True  # 稳定性这关过了
        assert report.escalation_required is False
        assert report.selected_tau is not None  # 确实选出了一个点
        assert report.nfr71_satisfied is False  # 但澄清率 1/5 = 0.20 > 0.15
        assert report.is_finalizable is False
        assert any("澄清率" in action for action in report.blocking_actions)

    def test_missing_layer_distribution_blocks_finalization(self) -> None:
        """步骤 6 的 `binding_layer` 分布是**报告产出** —— 没记录就不算跑完校准。"""
        report = calibrate(
            _clean_samples(),
            epsilon=0.05,
            accuracy_target=0.5,
            model_id="deepseek-flash",
            prompt_version="l4_score_v1",
            calibrated_at="2026-09-17T00:00:00Z",
            holdout_separated=True,
        )
        assert report.layer_distribution is None
        assert report.blocking_actions != ()
        assert report.is_finalizable is False  # 与上面的动作项**不得自相矛盾**

    def test_empty_layer_distribution_counts_as_missing(self) -> None:
        """空映射 = 没记录（不是"记录了 0 层"）—— 与动作项同判据，否则两个信号会打架。"""
        report = calibrate(
            _clean_samples(),
            epsilon=0.05,
            accuracy_target=0.5,
            model_id="deepseek-flash",
            prompt_version="l4_score_v1",
            calibrated_at="2026-09-17T00:00:00Z",
            holdout_separated=True,
            layer_distribution={},
        )
        assert any("binding_layer" in action for action in report.blocking_actions)
        assert report.is_finalizable is False

    def test_finalizable_implies_no_blocking_actions(self) -> None:
        """**不变量**：`is_finalizable` 为真 ⟺ `blocking_actions` 为空。

        两者若不一致，报告就会"一边说可以定稿、一边列出必须先做的事"。
        这里把四种典型形态都过一遍（全齐 / 全缺 / NFR 超限 / 稳定性未过）。
        """
        complete: dict[str, object] = {
            "model_id": "deepseek-flash",
            "prompt_version": "l4_score_v1",
            "calibrated_at": "2026-09-17T00:00:00Z",
            "holdout_separated": True,
            "layer_distribution": {"L1": 1, "L2": 2, "L4": 4},
        }
        noisy = _sample("n", (0.90, 0.50), gold="c0", noise=(0.10, -0.10))
        cases = [
            calibrate(_clean_samples(), epsilon=0.05, accuracy_target=0.5, **complete),  # type: ignore[arg-type]
            calibrate(_clean_samples(), epsilon=0.05, accuracy_target=0.5),
            calibrate(_over_limit_samples(), epsilon=0.05, accuracy_target=0.5, **complete),  # type: ignore[arg-type]
            calibrate(_tiny_samples(), epsilon=0.02, accuracy_target=0.5, **complete),  # type: ignore[arg-type]
            calibrate([noisy, *_clean_samples()], epsilon=0.05, accuracy_target=0.5, **complete),  # type: ignore[arg-type]
        ]
        for report in cases:
            assert report.is_finalizable is (report.blocking_actions == ()), report.blocking_actions

    def test_config_lines_refuse_to_emit_without_a_selected_tau(self) -> None:
        """没有定稿点 → **抛错**，不产出配置行。

        旧实现给的是 `BINDING_TAU=`（空值）。它贴进 `.env` 就是一个解析错误，
        但看上去像"待填" —— 等于把一个**不存在的** τ 伪装成可部署配置。
        """
        report = calibrate(_tiny_samples(), epsilon=0.02, accuracy_target=0.5)
        assert report.selected_tau is None
        with pytest.raises(ValueError, match="没有定稿"):
            report.config_lines()

    def test_layer_distribution_is_echoed_not_invented(self) -> None:
        """`binding_layer` 分布只能由调用方带入；没带就**如实为 `None`** + 一条动作项。"""
        report = calibrate(_clean_samples(), epsilon=0.05, accuracy_target=0.5)
        assert report.layer_distribution is None
        assert any("binding_layer" in action for action in report.blocking_actions)

    def test_missing_scorer_identity_blocks_finalization(self) -> None:
        report = calibrate(_clean_samples(), epsilon=0.05, accuracy_target=0.5)
        assert report.is_finalizable is False
        assert any("打分器标识" in action for action in report.blocking_actions)
        assert any("校准日期" in action for action in report.blocking_actions)
        assert any("分离" in action for action in report.blocking_actions)

    def test_invalid_accuracy_target_rejected(self) -> None:
        for bad in (0.0, -0.1, 1.5):
            with pytest.raises(ValueError, match="accuracy_target"):
                calibrate(_clean_samples(), epsilon=0.05, accuracy_target=bad)

    def test_config_lines_are_paste_ready(self) -> None:
        report = calibrate(
            _clean_samples(),
            epsilon=0.05,
            accuracy_target=0.5,
            model_id="deepseek-flash",
            prompt_version="l4_score_v1",
            calibrated_at="2026-09-17T00:00:00Z",
            holdout_separated=True,
        )
        lines = report.config_lines()
        assert len(lines) == 6
        assert any(line.startswith("BINDING_TAU=") and not line.endswith("=") for line in lines)
        assert "BINDING_TAU_MODEL_ID=deepseek-flash" in lines
        assert "BINDING_TAU_PROMPT_VERSION=l4_score_v1" in lines

    def test_nfr71_limit_matches_the_documented_requirement(self) -> None:
        """把需求常量钉住：NFR-7.1 是 15%。改它等于改需求，必须同时改文档。"""
        assert CLARIFY_RATE_LIMIT == 0.15

    def test_sweep_step_matches_the_documented_resolution(self) -> None:
        """步长 0.05 同时是约束 5 的"τ 分辨率"—— 一个常量两处用。"""
        assert TAU_SWEEP_STEP == 0.05
        assert MIN_REPEATS == 3
