"""时间表达解析单测（W3B，N-01：离线）。

## 这个文件守的两条纪律

1. **N-26：时间口径只能来自语义包**。词表来自 `SemanticBundleRuntime.resolve_terms`
   （不硬编码），周起点来自 `TimeSemantics.week_starts_on`（不假设周日）。
2. **不猜**。解析不出来必须 `ok=False` + 一个**可区分的 reason**，
   因为下游（W4）据此走澄清；`ok=False` 时若还给一个"最像"的窗口，
   就是把用户的沉默当成同意。

## 边界用例的来源

07 §17.2 / N-26 明确要求边界覆盖 **周一 / 月末 / 年末 / 大促窗口**。
下面对每个固定日期都用**字面 ISO 串**断言（不调用被测函数生成期望值 ——
那等于让实现给自己判卷）。日期本身是客观事实：

| 固定"今天" | 星期 | 要考什么 |
|---|---|---|
| 2026-09-17 | 周四 | 常规路径（与其它窗口的夹具保持同一天） |
| 2026-01-05 | 周一 | `上月` 跨年 + `本周`/`上周` 落在跨年周 |
| 2026-03-05 | 周四 | `上月` = 2 月（2026 非闰年，28 日） |
| 2026-03-01 | 周日 | 周日视角下"本周"从**上一个周一**开始 |

## 实测校正（2026-09-17）

初版计划里有两条**想当然**的用例，探测真实语义包后被推翻，已按实测改写：

- `11月大促` **不是**别名（包里的写法是 `十一月大促` / `双十一` / `双11`）；
  它是"没有任何时间表述"，因此 `ok=True, window=None`。
- `week_starts_on` 支持**全部七天**（`monday`…`sunday`），不是只认周一/周日；
  真正会失败的只有**非法取值**（如拼错），那才走 `unknown_week_starts_on`。
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import FrozenClock
from app.core.contracts import TimeSemantics
from app.planner.timeexpr import (
    MAX_NGRAM,
    find_alias_terms,
    resolve_time,
    resolve_window,
)
from app.semantics import SemanticBundleRuntime, load_bundle

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
_TZ = ZoneInfo("Asia/Shanghai")

#: 期望区间端点的**字面**写法（00:00:00 / 23:59:59，闭区间，带 +08:00）。
_AM = "T00:00:00+08:00"
_PM = "T23:59:59+08:00"


def _span(start: str, end: str) -> tuple[str, str]:
    return f"{start}{_AM}", f"{end}{_PM}"


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


def _clock(runtime: SemanticBundleRuntime, *, y: int, m: int, d: int) -> FrozenClock:
    return FrozenClock(
        _now=datetime(y, m, d, 10, 30, tzinfo=_TZ),
        _semantics=runtime.time_semantics(),
    )


def _assert_window(resolution, expected: tuple[str, str], *, expr: str) -> None:
    window = resolution.window
    assert window is not None, f"expected a window for {expr!r}"
    assert (window.start, window.end) == expected
    assert window.tz == "Asia/Shanghai"
    # `expr` 记的是**用户说过的话**，不是我们的中间表示（`relative:last_month`）
    assert window.expr == expr


# ============================================================================
# 一、词表命中：最长匹配 + 不重叠 + 词表来自语义层
# ============================================================================

class TestFindAliasTerms:
    def test_longest_match_wins(self, runtime: SemanticBundleRuntime) -> None:
        """`十一月大促`（5 字）必须**整体**命中，而不是被切成 `十一月` + `大促`。

        ⚠️ 实测：`十一月` 与 `大促` **都不是**别名 —— 所以本用例真正的证明力在于
        "扫描器取到了 5-gram 且它整体可解析"，而不是"切分冲突被消解"。
        冲突消解另有一例（下一条）。
        """
        found = find_alias_terms("十一月大促当天销售额", runtime)
        surfaces = [t.surface for t in found]
        assert "十一月大促" in surfaces
        assert surfaces.count("十一月大促") == 1

    def test_overlapping_candidates_do_not_double_count(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`双十一和十一月大促`：两个别名区间不重叠，各命中一次。"""
        found = find_alias_terms("双十一和十一月大促", runtime)
        surfaces = [t.surface for t in found]
        assert surfaces == ["双十一", "十一月大促"]

    def test_non_time_aliases_are_also_returned(self, runtime: SemanticBundleRuntime) -> None:
        """扫描器是**通用**的（kind 含 metric），时间的过滤由 `resolve_time` 做。"""
        found = find_alias_terms("上月销售额", runtime)
        kinds = {t.kind for t in found}
        assert "metric" in kinds and "time" in kinds

    def test_blank_text_yields_nothing(self, runtime: SemanticBundleRuntime) -> None:
        assert find_alias_terms("", runtime) == ()

    def test_unmapped_wording_yields_nothing(self, runtime: SemanticBundleRuntime) -> None:
        """`11月大促` 不在词表里 —— 返回空，而不是"就近取一个"。"""
        assert find_alias_terms("11月大促", runtime) == ()

    def test_ngram_bound_is_respected(self, runtime: SemanticBundleRuntime) -> None:
        assert MAX_NGRAM >= 5  # `十一月大促` 有 5 字，扫描窗口不能比它短

    def test_deterministic(self, runtime: SemanticBundleRuntime) -> None:
        text = "统计上月销售额与近7天趋势"
        assert find_alias_terms(text, runtime) == find_alias_terms(text, runtime)


# ============================================================================
# 二、区间计算（纯函数，直接喂 ref）
# ============================================================================

class TestResolveWindow:
    def test_unknown_ref_returns_none(self) -> None:
        assert resolve_window(
            "nope:x", today=date(2026, 9, 17), tz=_TZ, week_starts_on="monday"
        ) is None

    def test_campaign_is_not_resolvable_here(self) -> None:
        """大促窗口在语义包里是**自由文本 notes**，没有结构化区间 ⇒ 这里必然 None。"""
        assert resolve_window(
            "campaign:prom_double11", today=date(2026, 9, 17), tz=_TZ, week_starts_on="monday"
        ) is None

    def test_rolling_zero_is_invalid(self) -> None:
        assert resolve_window(
            "rolling:0d_incl_today", today=date(2026, 9, 17), tz=_TZ, week_starts_on="monday"
        ) is None

    def test_invalid_week_starts_on_returns_none(self) -> None:
        """拼错的周起点**不落回周日** —— 那会让"本周"静默算错。"""
        assert resolve_window(
            "relative:this_week_monday",
            today=date(2026, 9, 17),
            tz=_TZ,
            week_starts_on="notaday",
        ) is None

    @pytest.mark.parametrize(
        ("label", "today", "week_starts_on", "expected"),
        [
            ("周一", date(2026, 9, 14), "monday", ("2026-09-14", "2026-09-20")),
            ("周四", date(2026, 9, 17), "monday", ("2026-09-14", "2026-09-20")),
            ("周日（按周一制仍在同一周）", date(2026, 9, 20), "monday", ("2026-09-14", "2026-09-20")),
            ("周一开始的下一周", date(2026, 9, 21), "monday", ("2026-09-21", "2026-09-27")),
            ("周五制：周四的天属于上周五开始的那周", date(2026, 9, 17), "friday", ("2026-09-11", "2026-09-17")),
            ("周日制：周四的天属于上周日开始的那周", date(2026, 9, 17), "sunday", ("2026-09-13", "2026-09-19")),
        ],
    )
    def test_this_week_follows_week_starts_on(
        self, label: str, today: date, week_starts_on: str, expected: tuple[str, str]
    ) -> None:
        """周起点**由语义包决定**（N-26）—— 换一个起点，"本周"就是另一段区间。"""
        window = resolve_window(
            "relative:this_week_monday", today=today, tz=_TZ, week_starts_on=week_starts_on
        )
        assert window is not None, label
        assert (window.start, window.end) == _span(*expected)

    def test_last_month_crosses_the_year_boundary(self) -> None:
        window = resolve_window(
            "relative:last_month", today=date(2026, 1, 5), tz=_TZ, week_starts_on="monday"
        )
        assert window is not None
        assert (window.start, window.end) == _span("2025-12-01", "2025-12-31")

    def test_last_month_in_a_non_leap_february(self) -> None:
        """2026 非闰年 → 2 月末是 28 日（`_month_bounds` 用下月首日减一天算出来）。"""
        window = resolve_window(
            "relative:last_month", today=date(2026, 3, 5), tz=_TZ, week_starts_on="monday"
        )
        assert window is not None
        assert (window.start, window.end) == _span("2026-02-01", "2026-02-28")

    def test_boundary_format_is_closed_interval(self) -> None:
        """闭区间 + 时区偏移；**不用** `23:59:59.999999`（多出的微秒没有语义）。"""
        window = resolve_window(
            "relative:yesterday", today=date(2026, 9, 17), tz=_TZ, week_starts_on="monday"
        )
        assert window is not None
        assert window.start == "2026-09-16T00:00:00+08:00"
        assert window.end == "2026-09-16T23:59:59+08:00"

    def test_expr_is_the_user_wording_not_the_internal_ref(self) -> None:
        window = resolve_window(
            "relative:last_month",
            today=date(2026, 9, 17),
            tz=_TZ,
            week_starts_on="monday",
            expr="上个月",
        )
        assert window is not None
        assert window.expr == "上个月"
        assert "relative" not in (window.expr or "")


# ============================================================================
# 三、对外单一入口
# ============================================================================

class TestResolveTime:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("昨天", ("2026-09-16", "2026-09-16")),
            ("前天", ("2026-09-15", "2026-09-15")),
            ("本月", ("2026-09-01", "2026-09-30")),
            ("上月", ("2026-08-01", "2026-08-31")),
            ("本周", ("2026-09-14", "2026-09-20")),
            ("上周", ("2026-09-07", "2026-09-13")),
            ("近7天", ("2026-09-11", "2026-09-17")),
            ("上个月", ("2026-08-01", "2026-08-31")),  # 同义的另一种写法
        ],
    )
    def test_relative_expressions(
        self, runtime: SemanticBundleRuntime, text: str, expected: tuple[str, str]
    ) -> None:
        resolution = resolve_time(text, runtime, _clock(runtime, y=2026, m=9, d=17))
        assert resolution.ok, resolution.reason
        _assert_window(resolution, _span(*expected), expr=text)

    def test_no_time_expression_is_not_a_failure(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """"问题里没提时间" ≠ "解析失败"：`ok=True` + 无窗口。"""
        resolution = resolve_time("统计各渠道订单量", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert resolution.ok
        assert resolution.window is None
        assert resolution.reason is None

    def test_campaign_expression_is_an_explicit_gap(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """大促窗口无结构化来源 ⇒ `ok=False` + 专属 reason（**不猜一个区间**）。"""
        resolution = resolve_time("双11的销售额", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert not resolution.ok
        assert resolution.reason == "campaign_window_not_structured"
        assert resolution.window is None
        assert resolution.unresolved  # 待补清单非空 → W4 可转澄清

    def test_two_campaign_surfaces_are_the_same_ref_not_a_conflict(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`双十一` 与 `十一月大促` 是**同一个** canonical ⇒ 不是"两个区间"的歧义。"""
        resolution = resolve_time("双十一和十一月大促", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert resolution.reason == "campaign_window_not_structured"

    def test_comparison_alone_cannot_form_a_window(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`同比` 本身不是一个区间 —— 没有基准期就算不出"去年同期"。"""
        resolution = resolve_time("销售额同比", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert not resolution.ok
        assert resolution.reason == "comparison_without_base_period"
        assert resolution.window is None
        assert resolution.comparisons == ("compare:yoy",)

    def test_comparison_with_a_base_period_is_carried_along(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """有基准期时，`同比` 被如实带出来（供下游算对照），不影响主窗口。"""
        resolution = resolve_time("上月销售额同比", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert resolution.ok
        _assert_window(resolution, _span("2026-08-01", "2026-08-31"), expr="上月")
        assert resolution.comparisons == ("compare:yoy",)

    def test_two_distinct_ranges_are_ambiguous(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`上月和本周`：挑一个就是用沉默替用户做决定 ⇒ 澄清。"""
        resolution = resolve_time("上月和本周的销售额", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert not resolution.ok
        assert resolution.reason == "multiple_time_ranges"
        assert set(resolution.unresolved) == {"上月", "本周"}

    def test_same_ref_twice_is_not_ambiguous(self, runtime: SemanticBundleRuntime) -> None:
        """`上月和上个月` 指同一个月 ⇒ 不构成歧义。"""
        resolution = resolve_time("上月和上个月销售额", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert resolution.ok
        _assert_window(resolution, _span("2026-08-01", "2026-08-31"), expr="上月")

    def test_invalid_week_starts_on_surfaces_as_its_own_reason(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """周起点非法 → 专属 reason（与"词表没命中"必须能区分开）。

        口径来自 `ClockPort.semantics()`（N-26），所以只换时钟即可覆盖该分支 ——
        不需要动语义包。
        """
        clock = FrozenClock(
            _now=datetime(2026, 9, 17, 10, 30, tzinfo=_TZ),
            _semantics=TimeSemantics(
                timezone="Asia/Shanghai", fiscal_year_start_month=1, week_starts_on="notaday"
            ),
        )
        resolution = resolve_time("本周销售额", runtime, clock)
        assert not resolution.ok
        assert resolution.reason == "unknown_week_starts_on"
        assert resolution.window is None

    def test_terms_carry_every_resolved_kind_not_only_time(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """`terms` = 组 2 `resolved_terms` **整份**（含 metric），不是仅时间项。

        ## 这条用例的由来（一次被自己测试抓出来的契约矛盾）

        本文件初版按 `TimeResolution.terms` 的 docstring 断言"只含 kind=time" —— **它红了**。
        追下去发现是 **docstring 写错了**，不是实现错了：数据来源侧
        （`SemanticBundleRuntime.resolve_terms`）的 docstring 明写其产出就是
        "`graph/state.py` 组 2 `resolved_terms` 的形状"，而组 2 的 `resolved_terms`
        是"本轮识别出的**全部**语义项"。

        故此处断言的是**正确行为**，并额外钉住那条与时间无关的性质（下一条用例）：
        `metric` 项可以进 `terms`，但**不得**影响时间窗的判定。
        """
        resolution = resolve_time("上月销售额", runtime, _clock(runtime, y=2026, m=9, d=17))
        kinds = {term.kind for term in resolution.terms}
        assert kinds == {"time", "metric"}
        assert {term.surface for term in resolution.terms} == {"上月", "销售额"}

    def test_non_time_terms_do_not_create_a_window(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """纯 metric 命中**不构成**时间表述 → `ok=True` 且无窗口（不是"时间解析失败"）。"""
        resolution = resolve_time("客单价", runtime, _clock(runtime, y=2026, m=9, d=17))
        assert resolution.ok
        assert resolution.window is None
        assert {term.kind for term in resolution.terms} == {"metric"}

    def test_month_end_boundary(self, runtime: SemanticBundleRuntime) -> None:
        """月末：`本月` 的末日必须由**下月首日减一天**得出（30 天的月份不会写成 31）。"""
        resolution = resolve_time("本月", runtime, _clock(runtime, y=2026, m=4, d=30))
        _assert_window(resolution, _span("2026-04-01", "2026-04-30"), expr="本月")

    def test_year_boundary(self, runtime: SemanticBundleRuntime) -> None:
        resolution = resolve_time("上月", runtime, _clock(runtime, y=2026, m=1, d=1))
        _assert_window(resolution, _span("2025-12-01", "2025-12-31"), expr="上月")

    def test_is_deterministic(self, runtime: SemanticBundleRuntime) -> None:
        clock = _clock(runtime, y=2026, m=9, d=17)
        first = resolve_time("上月华东销售额", runtime, clock)
        second = resolve_time("上月华东销售额", runtime, clock)
        assert first == second

    def test_clock_is_the_only_time_source(self, runtime: SemanticBundleRuntime) -> None:
        """换个"今天"，同一句话落到另一段区间 —— 唯一时间来源是 `ClockPort`（N-18）。"""
        a = resolve_time("昨天", runtime, _clock(runtime, y=2026, m=9, d=17))
        b = resolve_time("昨天", runtime, _clock(runtime, y=2026, m=1, d=1))
        assert a.window is not None and b.window is not None
        assert a.window.start != b.window.start
        assert b.window.start == "2025-12-31T00:00:00+08:00"
