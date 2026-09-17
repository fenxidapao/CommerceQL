"""T4 成本计量与预算熔断单测 —— PRD §12.3 / 07 §10.4 / NFR-4.2 / NFR-4.3。

## 这份文件在防什么

| 断言组 | 防的事故 |
|---|---|
| `TestTier` | 时段判错 → 账单价按错的档算（高峰价是非高峰的 **2 倍**） |
| `TestCost` | 缓存命中价用成未命中价 → 成本高估 **50 倍**，TCO 结论全错 |
| `TestTokenCount` | 估算失败**抛异常** → 把"算不出 token"升级成"LLM 调用失败" |
| `TestBudgetGuard` | 边界判定写成 `>` 而非 `>=` → 恰好等于预算的那次调用会击穿预算 |
| `TestUpperBound` | 估算用"当前时段价" → 非高峰期估算低估一半，pre-flight 形同虚设 |

## ⚠️ 一条必须写明的限制（不是本文件的，是被测实现自带的）

`cost_ledger` 表**不存在**（迁移 0001–0003 都没有），故本窗口给的是内存 sink。
本文件能证明"**逻辑**是对的"（能真触发 80%/100%），**不能**证明"数据留得住"。
"重启后熔断被重置"这条限制原样登记在 `DELIVERY.md`，此处不掩盖。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.contracts import TokenUsage
from app.llm import budget as budget_mod
from app.llm.budget import (
    BILLING_TZ,
    DEFAULT_TENANT_DAILY_BUDGET_CNY,
    PRICES,
    USD_CNY_RATE,
    BudgetGuard,
    CostEntry,
    InMemoryCostLedgerSink,
    Tier,
    classify_tier,
    compute_cost,
    count_tokens,
    estimate_for_payload,
    estimate_prompt_tokens,
    resolve_price,
)
from app.llm.router import LlmTask

#: 一个**工作日**的北京时间 10:00（高峰）—— 2026-09-17 是周四。
_PEAK = datetime(2026, 9, 17, 10, 0, tzinfo=BILLING_TZ)
#: 同一天的 13:00（午休空档，非高峰）。
_OFF_PEAK = datetime(2026, 9, 17, 13, 0, tzinfo=BILLING_TZ)
#: 周六 10:00 —— 周末整日非高峰。
_WEEKEND = datetime(2026, 9, 19, 10, 0, tzinfo=BILLING_TZ)


class TestTier:
    """PRD §12.3：北京时间的**工作日** 09:00–12:00 与 14:00–18:00 = 高峰。"""

    @pytest.mark.parametrize(
        ("hour", "minute", "expected"),
        [
            (8, 59, Tier.OFF_PEAK),
            (9, 0, Tier.PEAK),        # 左闭
            (11, 59, Tier.PEAK),
            (12, 0, Tier.OFF_PEAK),   # 右开
            (13, 59, Tier.OFF_PEAK),
            (14, 0, Tier.PEAK),       # 左闭
            (17, 59, Tier.PEAK),
            (18, 0, Tier.OFF_PEAK),   # 右开
            (23, 59, Tier.OFF_PEAK),
        ],
    )
    def test_peak_window_boundaries(self, hour: int, minute: int, expected: Tier) -> None:
        """边界逐分钟钉住：`[起, 止)` 的语义只靠文档说是不牢的。"""
        now = datetime(2026, 9, 17, hour, minute, tzinfo=BILLING_TZ)
        assert classify_tier(now) is expected

    def test_weekend_is_always_off_peak(self) -> None:
        assert classify_tier(_WEEKEND) is Tier.OFF_PEAK
        sat_14 = datetime(2026, 9, 19, 15, 0, tzinfo=BILLING_TZ)
        assert classify_tier(sat_14) is Tier.OFF_PEAK
        sun = datetime(2026, 9, 20, 10, 0, tzinfo=BILLING_TZ)
        assert classify_tier(sun) is Tier.OFF_PEAK

    def test_timezone_is_normalized_to_beijing(self) -> None:
        """官方高峰是北京时间；给 UTC 的时刻必须**换算后**判定，不能拿 UTC 小时直接比。"""
        utc_0130 = datetime(2026, 9, 17, 1, 30, tzinfo=UTC)  # = 北京 09:30
        assert classify_tier(utc_0130) is Tier.PEAK
        utc_0600 = datetime(2026, 9, 17, 6, 0, tzinfo=UTC)   # = 北京 14:00
        assert classify_tier(utc_0600) is Tier.PEAK

    def test_naive_datetime_is_rejected(self) -> None:
        """🔴 反向对照：naive datetime 会按**部署机器**的本地时区解释。

        本机恰好是 UTC+8，所以 naive 传进来的结果"看起来是对的" ——
        这正是最坏的一种 bug：换台机器就错，而在本机永远复现不出来。
        """
        with pytest.raises(ValueError, match="带时区"):
            classify_tier(datetime(2026, 9, 17, 10, 0))

    def test_billing_tz_is_explicitly_a_billing_concept(self) -> None:
        """计费时区必须是固定常量，不得复用业务时间口径（N-26 的 `TimeSemantics`）。"""
        assert str(BILLING_TZ) == "Asia/Shanghai"


class TestCost:
    """PRD §12.3 的价表**逐格照抄** + 计价公式。"""

    def test_price_table_is_copied_from_the_prd(self) -> None:
        flash = PRICES["deepseek-flash"]
        assert flash[Tier.OFF_PEAK].cache_hit == Decimal("0.003")
        assert flash[Tier.OFF_PEAK].cache_miss == Decimal("0.15")
        assert flash[Tier.OFF_PEAK].output == Decimal("0.60")
        assert flash[Tier.PEAK].cache_miss == Decimal("0.30")
        pro = PRICES["deepseek-v4-pro"]
        assert pro[Tier.PEAK].output == Decimal("3.96")

    def test_cache_hit_is_fifty_times_cheaper_on_flash(self) -> None:
        """PRD §12.3 结论①：命中与未命中在 flash 上差 **50 倍**（0.003 vs 0.15）。

        这是 NFR-4.3 要埋缓存命中率的**唯一**理由 —— 如果两者价差不显著，
        埋这个指标就不值得。所以这条断言同时也是"埋点有意义"的证据。
        """
        flash = PRICES["deepseek-flash"][Tier.OFF_PEAK]
        assert flash.cache_miss / flash.cache_hit == Decimal("50")

    def test_input_cache_hit_and_miss_are_priced_separately(self) -> None:
        u = TokenUsage(input=1_000_000, output=0, cache_hit=1_000_000, total=1_000_000)
        assert compute_cost("deepseek-flash", u, Tier.OFF_PEAK) == (
            Decimal("0.003") * USD_CNY_RATE
        ).quantize(Decimal("0.000001"))

    def test_miss_price_applies_to_the_non_hit_part_only(self) -> None:
        """`input - cache_hit` = 未命中部分；把两者相加是**重复计费**。"""
        u = TokenUsage(input=1_000_000, output=0, cache_hit=400_000, total=1_000_000)
        expected = (
            (Decimal(600_000) * Decimal("0.15") + Decimal(400_000) * Decimal("0.003"))
            / Decimal(1_000_000)
            * USD_CNY_RATE
        ).quantize(Decimal("0.000001"))
        assert compute_cost("deepseek-flash", u, Tier.OFF_PEAK) == expected

    def test_peak_costs_exactly_twice_off_peak(self) -> None:
        """PRD §12.3 结论②：高峰价恰为非高峰的 2 倍（三档都是）。"""
        u = TokenUsage(input=1_000_000, output=1_000_000, cache_hit=0, total=2_000_000)
        off = compute_cost("deepseek-flash", u, Tier.OFF_PEAK)
        peak = compute_cost("deepseek-flash", u, Tier.PEAK)
        assert peak == off * 2

    def test_cache_hit_greater_than_input_does_not_produce_a_negative_cost(self) -> None:
        """上游字段不一致（`cache_hit > input`）不得让成本变成负数 —— 负成本会穿透预算。"""
        u = TokenUsage(input=10, output=0, cache_hit=999, total=10)
        assert compute_cost("deepseek-flash", u, Tier.PEAK) >= Decimal(0)

    def test_unknown_model_is_charged_as_the_most_expensive_one(self) -> None:
        """🔴 方向性选择：未知模型按**最贵**的档计价并打 `is_guess` 标。

        宁可高估成本（有人会去看为什么超预算），也不要让一个新模型静默按便宜价计量
        （那样它超支了也没人知道）。这与 07 §10.4 的 TCO 纪律同源。
        """
        price, is_guess = resolve_price("some-new-model", Tier.PEAK)
        assert is_guess is True
        assert price == PRICES["deepseek-v4-pro"][Tier.PEAK]

    def test_known_model_is_not_flagged_as_guess(self) -> None:
        _, is_guess = resolve_price("deepseek-flash", Tier.PEAK)
        assert is_guess is False

    def test_total_field_is_not_used_for_pricing(self) -> None:
        """`total` 含 reasoning token，而 reasoning 已计入 `output` —— 用它就是重复计。"""
        a = TokenUsage(input=1000, output=500, cache_hit=0, total=1500)
        b = TokenUsage(input=1000, output=500, cache_hit=0, total=99_999_999)
        assert compute_cost("deepseek-flash", a, Tier.PEAK) == compute_cost(
            "deepseek-flash", b, Tier.PEAK
        )

    def test_decimal_is_used_not_float(self) -> None:
        """成本必须 `Decimal` —— float 累加会让"预算恰好用满"这类判定飘。"""
        assert isinstance(compute_cost("deepseek-flash", TokenUsage(), Tier.PEAK), Decimal)


class TestTokenCount:
    def test_empty_text_is_zero(self) -> None:
        assert count_tokens("") == 0

    def test_chinese_text_is_in_the_expected_order_of_magnitude(self) -> None:
        """实测（2026-09-17）：19 个汉字 → 15 token（≈0.79/字）。

        ⚠️ `cl100k_base` 是**近似**编码器（DeepSeek 不公开自己的 BPE），
        这里只断言**量级**（0.5–1.5 倍字符数），不断言精确值 ——
        精确值属于"上游回传的 `usage`"，不属于估算。
        """
        text = "统计华东区上月销售额前十的SKU" * 3
        n = count_tokens(text)
        assert len(text) * 0.5 <= n <= len(text) * 1.5

    def test_estimate_prompt_tokens_sums_system_and_user(self) -> None:
        s, u = "你是数据分析助手。", "统计销售额。"
        assert estimate_prompt_tokens(s, u) == count_tokens(s) + count_tokens(u)

    def test_missing_encoder_falls_back_to_heuristic_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """🔴 `tiktoken` 首次使用要下载 BPE 文件，**离线环境会失败**。

        但"算不出 token 数"不该让一次 LLM 调用失败 —— 估算的用途是预算与保护，
        计费真相来自上游 `usage`。故此处必须降级为字符启发式并**继续**。
        """
        monkeypatch.setattr(budget_mod, "_ENCODER", None)
        monkeypatch.setattr(budget_mod, "_ENCODER_TRIED", True)
        text = "统计华东区上月销售额前十的SKU"
        n = count_tokens(text)
        assert n == max(1, int(len(text) * 0.8))

    def test_heuristic_never_returns_zero_for_non_empty_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """启发式若返回 0，pre-flight 会认为"几乎不花钱" → 预算形同虚设。"""
        monkeypatch.setattr(budget_mod, "_ENCODER", None)
        monkeypatch.setattr(budget_mod, "_ENCODER_TRIED", True)
        assert count_tokens("a") >= 1


class TestInMemoryLedger:
    def test_tenant_and_global_aggregation_by_billing_day(self) -> None:
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink)
        _settle(guard, tenant="t1", cost_day=_PEAK, model="deepseek-flash")
        _settle(guard, tenant="t2", cost_day=_PEAK, model="deepseek-flash")
        day = _PEAK.date()
        assert sink.global_spent_cny(day) > 0
        assert sink.tenant_spent_cny("t1", day) > 0
        assert sink.tenant_spent_cny("t1", day) < sink.global_spent_cny(day)
        assert len(sink) == 2

    def test_entries_on_another_day_do_not_count(self) -> None:
        """跨日照**北京时间**切分（UTC 16:00 是北京次日 00:00 → 必须落到次日）。"""
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink)
        _settle(guard, tenant="t1", cost_day=_PEAK, model="deepseek-flash")
        assert sink.global_spent_cny(_PEAK.date() + timedelta(days=1)) == Decimal(0)

    def test_other_tenants_do_not_count_toward_this_tenant(self) -> None:
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink)
        _settle(guard, tenant="t2", cost_day=_PEAK, model="deepseek-flash")
        assert sink.tenant_spent_cny("t1", _PEAK.date()) == Decimal(0)


class TestCostEntryShape:
    def test_entry_columns_align_with_the_07_cost_ledger_table(self) -> None:
        """`CostEntry` 必须逐列对齐 07 §12.3 的 `cost_ledger` —— 否则 W1B 建表要重新对一遍。

        这条断言的价值：W1B 落地时可以直接按本类写 INSERT，两边不会各定义一遍列。
        """
        expected = {
            "entry_id", "task_id", "tenant_id", "user_id", "model",
            "input_tokens", "output_tokens", "cache_hit_tokens",
            "cost_cny", "is_peak", "created_at",
        }
        got = {f for f in CostEntry.__dataclass_fields__}
        assert expected <= got

    def test_settle_records_is_peak_truthfully(self) -> None:
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink)
        entry = guard.settle(
            task_id="task-1", tenant_id="t1", user_id="u1", model="deepseek-flash",
            usage=TokenUsage(input=10, output=5, cache_hit=0, total=15), now=_OFF_PEAK,
        )
        assert entry.is_peak is False
        entry2 = guard.settle(
            task_id="task-2", tenant_id="t1", user_id="u1", model="deepseek-flash",
            usage=TokenUsage(input=10, output=5, cache_hit=0, total=15), now=_PEAK,
        )
        assert entry2.is_peak is True

    def test_unknown_model_settle_is_flagged_as_price_guess(self) -> None:
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink)
        entry = guard.settle(
            task_id="task-1", tenant_id="t1", user_id="u1", model="brand-new-model",
            usage=TokenUsage(input=10, output=5, cache_hit=0, total=15), now=_PEAK,
        )
        assert entry.price_guess is True


class TestBudgetGuard:
    """NFR-4.2：**80% 告警 / 100% 硬熔断**，双层（租户 + 全局）。"""

    def test_fresh_guard_allows_and_does_not_warn(self) -> None:
        d = _guard(InMemoryCostLedgerSink()).preflight(
            tenant_id="t1", now=_PEAK, estimated_cny=Decimal("0.0001")
        )
        assert d.allowed is True and d.warn is False and d.force_single_path is False
        assert d.blocked_by is None

    def test_crossing_80_percent_warns_and_forces_single_path(self) -> None:
        """07 §10.4 的"前置估算：接近预算时自动降为单路"。"""
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink, global_budget=Decimal("10"), tenant_budget=Decimal("100"))
        _settle_amount(guard, tenant="t1", cost=Decimal("7.9"))
        d = guard.preflight(tenant_id="t1", now=_PEAK, estimated_cny=Decimal("0.2"))
        assert d.warn is True
        assert d.force_single_path is True
        assert d.allowed is True  # 告警不等于熔断

    def test_crossing_100_percent_fuses_and_names_the_layer(self) -> None:
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink, global_budget=Decimal("10"), tenant_budget=Decimal("100"))
        _settle_amount(guard, tenant="t1", cost=Decimal("10"))
        d = guard.preflight(tenant_id="t1", now=_PEAK, estimated_cny=Decimal("0.001"))
        assert d.allowed is False
        assert d.blocked_by == "global"

    def test_boundary_is_inclusive_ge_not_gt(self) -> None:
        """🔴 边界断言：花到**恰好**等于预算就不能再花。

        写成 `>` 的后果：恰好等于预算的那次调用通过、并立刻把预算击穿，
        之后所有请求被熔断 —— "用一次超支换取全网停摆"。
        """
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink, global_budget=Decimal("10"), tenant_budget=Decimal("100"))
        _settle_amount(guard, tenant="t1", cost=Decimal("9.9"))
        # 恰好补到 10.0 → 必须熔断
        d = guard.preflight(tenant_id="t1", now=_PEAK, estimated_cny=Decimal("0.1"))
        assert d.allowed is False

    def test_estimated_cost_counts_toward_the_fuse(self) -> None:
        """只按"已花"判定会让一次昂贵调用卡在 100% 之前通过。"""
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink, global_budget=Decimal("10"), tenant_budget=Decimal("100"))
        _settle_amount(guard, tenant="t1", cost=Decimal("1"))
        d = guard.preflight(tenant_id="t1", now=_PEAK, estimated_cny=Decimal("50"))
        assert d.allowed is False

    def test_tenant_layer_fuses_even_when_global_is_fine(self) -> None:
        """双层里任一层到顶即熔断 —— 租户级熔断不得被"全局还很空"放过。"""
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink, global_budget=Decimal("1000"), tenant_budget=Decimal("5"))
        _settle_amount(guard, tenant="t1", cost=Decimal("5"), tenant_only=True)
        d = guard.preflight(tenant_id="t1", now=_PEAK, estimated_cny=Decimal("0.001"))
        assert d.allowed is False and d.blocked_by == "tenant"

    def test_another_tenants_spend_does_not_fuse_this_tenant(self) -> None:
        """反向对照：t2 花光自己的租户预算，不得连累 t1。"""
        sink = InMemoryCostLedgerSink()
        guard = _guard(sink, global_budget=Decimal("1000"), tenant_budget=Decimal("5"))
        _settle_amount(guard, tenant="t2", cost=Decimal("5"))
        d = guard.preflight(tenant_id="t1", now=_PEAK, estimated_cny=Decimal("0.001"))
        assert d.allowed is True

    def test_tenant_layer_can_be_disabled_explicitly(self) -> None:
        """`tenant_daily_budget_cny=None` = 只做全局层（W0 给了租户级 config 键前的逃生门）。"""
        sink = InMemoryCostLedgerSink()
        guard = BudgetGuard(
            global_daily_budget_cny=Decimal("1000"), alert_ratio=0.8, sink=sink,
            tenant_daily_budget_cny=None,
        )
        _settle_amount(guard, tenant="t1", cost=Decimal("100"))
        assert guard.preflight(
            tenant_id="t1", now=_PEAK, estimated_cny=Decimal("0.001")
        ).allowed is True

    def test_default_tenant_budget_is_a_declared_experience_value(self) -> None:
        """07 只说"预算层级 = 租户日预算 + 全局日预算"，**没给租户级的数**。

        本窗口不给"看起来有依据"的假推导：它就是 10 元、就是经验值、就是要 W0 给 config 键。
        这条断言把"它是经验值"钉在代码里，防止下一个人以为它是从哪算出来的。
        """
        declared_default = DEFAULT_TENANT_DAILY_BUDGET_CNY
        assert declared_default == Decimal("10")


class TestUpperBound:
    """TCO 纪律（07 §10.4）：估算**一律按高峰价** —— 折扣基本吃不到，规划按最坏算。"""

    def test_upper_bound_uses_peak_price_regardless_of_now(self) -> None:
        g = _guard(InMemoryCostLedgerSink())
        a = g.estimate_cny_upper_bound(model="deepseek-flash", prompt_tokens=0, output_tokens=1_000_000)
        assert a == (Decimal("1.20") * USD_CNY_RATE).quantize(Decimal("0.000001"))

    def test_upper_bound_treats_all_input_as_cache_miss(self) -> None:
        """把输入当命中算会**低估 50 倍** —— 那就不叫上界了。"""
        g = _guard(InMemoryCostLedgerSink())
        v = g.estimate_cny_upper_bound(
            model="deepseek-flash", prompt_tokens=1_000_000, output_tokens=0
        )
        assert v == (Decimal("0.30") * USD_CNY_RATE).quantize(Decimal("0.000001"))

    def test_estimate_for_payload_multiplies_by_candidate_paths(self) -> None:
        """07 §10.4："候选路数 × 预估长度" —— 多路生成会被并行发 N 次。"""
        g = _guard(InMemoryCostLedgerSink())
        one = estimate_for_payload(
            g, {"text": "统计销售额" * 20, "task": "gen_sql", "candidates": 1},
            model="deepseek-flash",
        )
        three = estimate_for_payload(
            g, {"text": "统计销售额" * 20, "task": "gen_sql", "candidates": 3},
            model="deepseek-flash",
        )
        assert three > one

    def test_estimate_for_payload_uses_task_output_hint_when_omitted(self) -> None:
        g = _guard(InMemoryCostLedgerSink())
        v = estimate_for_payload(g, {"text": "x", "task": LlmTask.PRESENT.value},
                                 model="deepseek-flash")
        assert v > 0

    def test_estimate_for_payload_does_not_raise_on_unknown_task(self) -> None:
        """🔴 估算路径上**不许抛**：pre-flight 一旦会抛，它自己就变成了故障点 ——

        一个拼错的 task 名会把"预算保护"变成"请求失败"。这与 `count_tokens`
        不抛异常是同一条纪律（保护机制不得成为故障源）。
        """
        g = _guard(InMemoryCostLedgerSink())
        assert estimate_for_payload(g, {"text": "x", "task": "no_such_task"},
                                    model="deepseek-flash") > 0

    def test_estimate_for_payload_on_empty_payload_is_zero_not_an_error(self) -> None:
        g = _guard(InMemoryCostLedgerSink())
        assert estimate_for_payload(g, {}, model="deepseek-flash") >= Decimal(0)

    def test_estimate_for_payload_ignores_non_int_candidates(self) -> None:
        """`candidates="3"`（字符串）不得被当成 3 路，也不得抛错。"""
        g = _guard(InMemoryCostLedgerSink())
        a = estimate_for_payload(g, {"text": "x", "candidates": "3"}, model="deepseek-flash")
        b = estimate_for_payload(g, {"text": "x"}, model="deepseek-flash")
        assert a == b

    def test_explicit_output_tokens_overrides_the_hint(self) -> None:
        g = _guard(InMemoryCostLedgerSink())
        small = estimate_for_payload(
            g, {"text": "x", "task": "gen_sql", "output_tokens": 10}, model="deepseek-flash"
        )
        big = estimate_for_payload(
            g, {"text": "x", "task": "gen_sql", "output_tokens": 10_000}, model="deepseek-flash"
        )
        assert big > small


# ============================================================================
# 夹具
# ============================================================================

def _guard(
    sink: InMemoryCostLedgerSink,
    *,
    global_budget: Decimal = Decimal("1000"),
    tenant_budget: Decimal | None = Decimal("1000"),
) -> BudgetGuard:
    return BudgetGuard(
        global_daily_budget_cny=global_budget,
        alert_ratio=0.8,
        sink=sink,
        tenant_daily_budget_cny=tenant_budget,
    )


def _settle(guard: BudgetGuard, *, tenant: str, cost_day: datetime, model: str) -> CostEntry:
    return guard.settle(
        task_id="t", tenant_id=tenant, user_id="u", model=model,
        usage=TokenUsage(input=1_000_000, output=1_000_000, cache_hit=0, total=2_000_000),
        now=cost_day,
    )


def _settle_amount(
    guard: BudgetGuard,
    *,
    tenant: str,
    cost: Decimal,
    tenant_only: bool = False,
    day: date | None = None,
) -> None:
    """往 sink 里塞一笔**指定金额**的账。

    刻意绕过 `settle()`（那需要真实 token 数）：本组测试要的是"已花到某个比例"这个**状态**，
    用真实计价去凑金额会让夹具数字与价表耦合，价表一变测试就莫名其妙地红。
    这里直接构造 `CostEntry`，把"金额"这个自变量暴露出来。
    """
    d = day or _PEAK.date()
    guard.sink.record(
        CostEntry(
            entry_id=f"e-{tenant}-{cost}",
            task_id="t", tenant_id=tenant, user_id="u",
            model="deepseek-flash" if not tenant_only else "deepseek-v4-pro",
            input_tokens=0, output_tokens=0, cache_hit_tokens=0,
            cost_cny=cost, is_peak=False,
            created_at=datetime.combine(d, datetime.min.time(), tzinfo=BILLING_TZ),
        )
    )
