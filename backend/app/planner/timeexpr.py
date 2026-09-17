"""节点 2 的**时间绝对化** —— 确定性解析，基准 100% 来自语义包（N-26 / FR-1.2）。

归属窗口：W3B（docs/08 §4.1）｜层号：L3

## 一、为什么这块**不能**交给 LLM（两处上游原文同时指向这一结论）

1. `app/llm/prompts/normalize_v1.txt` 硬性规则 3：
   "保留原问题中的时间表达**原样**（如"上月""近 7 天""本季度"），**不要换算成具体日期**：
   时间口径由系统统一解释，换算会造成口径漂移。"
2. 07 §5.2 组 2 `time_range`：解析基准（财年 `fiscal_year_start_month`、周起点
   `week_starts_on`、时区、大促窗口）**只能来自语义包（附录 B）**，**禁止代码硬编码**。

⇒ 模型负责"把表述抄回来"，本模块负责"把它算成区间"。两者分工写在 `NormalizeResult` 的 docstring 里。

## 二、词汇表也从语义包来（**不是代码里的 if-else**）

语义包 `synonyms` 区块里 `maps_to_kind: time` 的别名就是全部合法表述：

    relative:today / relative:yesterday / relative:day_before_yesterday
    relative:this_week_monday / relative:last_week_monday
    relative:this_month / relative:last_month
    rolling:7d_incl_today
    campaign:prom_double11 / campaign:prom_618
    compare:yoy / compare:period_over_period

本模块**不硬编码词表**：它把问题切成 n-gram，逐个问语义层 `resolve_terms`，
拿回来的 `canonical` 里已经是 `<kind>:<ref>`。新增一个"昨天"的同义词只需改 YAML，本文件零改动。
**这是本模块最重要的设计约束** —— 任何形如 `if "上月" in q` 的写法都会在下一个同义词出现时失效，
且失效方式是**静默的**（问题照跑，只是时间范围为空）。

## 三、🔴 `canonical` 是权威、**不**信 `kind` 字段（实测证据）

实测（2026-09-17，`SemanticBundleRuntime.resolve_terms`）：

| 输入 | `resolve_alias().maps_to_kind` | `resolve_terms()` 的 `canonical` | `resolve_terms()` 的 `kind` |
|---|---|---|---|
| `上月` | `time` | `time:relative:last_month` | `time` |
| **`支付时间`** | **`column`** | `column:order_paid.pay_time` | **`time`** ⚠️ |

即 `kind` 填的是 `alias.category`（分组：时间/实体/维度），**不是** `maps_to_kind`。
若本模块按 `kind == "time"` 筛时间词，`支付时间` 会被误判成时间区间表述 → 时间范围解析错。
⇒ 本模块**一律从 `canonical` 的前缀取 kind**（`canonical.split(":", 1)[0]`）。
该不一致已提给 W2A 确认（`RELAY.md §给 W2A`）—— 在它被澄清前后，从 `canonical` 取都是对的。

## 四、🔴 大促区间当前**无法**解析（不解析自由文本，如实暴露）

语义包 §9 `time_semantics.notes` **有**权威口径：

    - '618' = 2026-05-24 至 2026-06-20（含预售期）
    - '双11' = 2026-10-20 至 2026-11-11（含预售期）

但它是**自由文本 notes**，而运行时对外**只暴露结构化的 `TimeSemantics`
（timezone / fiscal_year_start_month / week_starts_on）** —— 大促区间没有结构化承载位。

⇒ 本模块**不去正则解析那句 notes**：那等于"把文档当契约"，notes 改一个标点就会静默解析错。
`campaign:*` 一律进 `unresolved`，并把缺口写进返回值（`reason="campaign_window_not_structured"`）。
产品代价（"双11 GMV" 会走澄清）与补位需求见 `DELIVERY.md` / `RELAY.md §给 W2A`。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.core.contracts import ClockPort, SemanticBundlePort
from app.planner.schemas import ResolvedTerm, TimeRange

__all__ = [
    "MAX_NGRAM",
    "TimeResolution",
    "find_alias_terms",
    "resolve_time",
    "resolve_window",
]

#: n-gram 的最长长度。
#:
#: 语义包里最长的别名是 `十一月大促`（5 字），取 6 留一格余量。
#: **不设更大**：O(长度 × N) 的扫描在每请求路径上跑，而别名都是短语级；
#: 提高 N 只会放大开销，不会找回不存在的词条。
MAX_NGRAM: Final[int] = 6

#: `rolling:<n>d_incl_today` 的唯一合法形态。
_ROLLING_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,3})d_incl_today$")

#: `week_starts_on` 取值 → `date.weekday()` 的下标（周一=0）。**未知取值一律失败**（不猜周日）。
_WEEKDAY_INDEX: Final[Mapping[str, int]] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_UNRESOLVED_REASON_CAMPAIGN: Final[str] = "campaign_window_not_structured"
_UNRESOLVED_REASON_WEEKSTART: Final[str] = "unknown_week_starts_on"
_UNRESOLVED_REASON_REF: Final[str] = "unknown_time_ref"
_UNRESOLVED_REASON_COMPARE: Final[str] = "comparison_without_base_period"


@dataclass(frozen=True, slots=True)
class TimeResolution:
    """一次时间解析的完整结果。

    | 字段 | 去 `GraphState` 的哪个位置 |
    |---|---|
    | `window` | 组 2 `time_range` |
    | `terms` | 组 2 `resolved_terms`（**全部命中项**，含 metric / dimension / alias） |
    | `unresolved` | 组 2 `unresolved_terms`（FR-11.5 待补清单） |
    | `ok` | 组 2 `time_parse_ok`（`False` → W4 走澄清，**不猜**） |
    | `reason` | 审计/日志用；`ok=True` 时为 `None` |

    ## ⚠️ `terms` 为什么含非时间项（与时间语义无关的 kind 也在这里）

    本类的字段名是"时间解析"，但 `terms` 承载的是**组 2 的 `resolved_terms` 整份**，
    不是仅时间项。依据是**数据来源侧的口径**：`SemanticBundleRuntime.resolve_terms`
    的 docstring 明写它的产出就是"`graph/state.py` 组 2 `resolved_terms` 的形状"，
    而组 2 的 `resolved_terms` 是"本轮识别出的全部语义项"（`unresolved_terms` 才是待补清单）。

    实现上的后果有一条，必须写清楚，否则后来人会以为这是漏过滤：

    - **时间窗的判定只由 `kind == "time"` 的项参与**（内部 `_time_refs` 过滤），
      所以一条 `metric:gmv` 命中**不会**凭空造出一个时间区间；
    - 但那条 `metric:gmv` 会**跟着 `terms` 一起**进 `state.resolved_terms` —— 这是有意的：
      调用方只扫一次 n-gram 就能同时拿到"时间窗"与"整份已识别术语"，
      再扫一次（为了补 metric 项）是纯粹的重复开销。

    ⇒ 若将来有人要把 `terms` 收窄成"仅时间项"，**必须同时**给组 2 的 `resolved_terms`
    另找一个来源（`find_alias_terms` 再调一次），否则 `resolved_terms` 会静默丢项。
    """

    window: TimeRange | None
    terms: tuple[ResolvedTerm, ...]
    unresolved: tuple[str, ...]
    ok: bool
    reason: str | None = None
    comparisons: tuple[str, ...] = ()


# ============================================================================
# 一、词表命中（**问语义层，不硬编码词表**）
# ============================================================================

def _ngrams(text: str, *, max_n: int = MAX_NGRAM) -> list[str]:
    """切 n-gram（**按字符**，中文无空格切分）。

    顺序：长 → 短。这样"最长匹配优先"只需顺序扫描 + 标记已占用区间即可实现，
    不需要额外的排序与冲突消解。
    """
    out: list[str] = []
    for n in range(min(max_n, len(text)), 0, -1):
        for i in range(len(text) - n + 1):
            out.append(text[i : i + n])
    return out


def find_alias_terms(
    text: str, semantics: SemanticBundlePort, *, max_n: int = MAX_NGRAM
) -> tuple[ResolvedTerm, ...]:
    """问题文本 → 命中的别名项（**最长匹配、无重叠**）。

    取数走 `resolve_terms`（W2A 的批量面）。`kind` 从 `canonical` 前缀推导（见模块 docstring §三）。

    ⚠️ 未命中即未命中：本层**不做模糊匹配**（语义层明令 L1 只做 O(1) 精确命中，
    模糊是 L4 的事）—— 在这里补一层相似度匹配会把"确定性层"变成"半确定性层"。
    """
    if not text:
        return ()
    resolver = getattr(semantics, "resolve_terms", None)
    if not callable(resolver):
        # 语义层没暴露批量面 → 退化为**不做别名命中**（如实：宁可没有 resolved_terms，
        # 也不自己解析 YAML 造第二份真相）。
        return ()

    candidates = _ngrams(text, max_n=max_n)
    hits = resolver(candidates)

    by_surface: dict[str, ResolvedTerm] = {}
    for hit in hits:
        surface = str(hit.get("surface", ""))
        canonical = str(hit.get("canonical", ""))
        if not surface or ":" not in canonical:
            continue
        kind = canonical.split(":", 1)[0]
        by_surface.setdefault(surface, ResolvedTerm(surface=surface, canonical=canonical, kind=kind))

    # 最长匹配 + 区间占用：`十一月大促` 与（若存在的）`大促` 同时命中时只保留长的那个。
    occupied = [False] * len(text)
    picked: list[ResolvedTerm] = []
    for surface in sorted(by_surface, key=len, reverse=True):
        start = 0
        while True:
            idx = text.find(surface, start)
            if idx < 0:
                break
            end = idx + len(surface)
            if not any(occupied[idx:end]):
                for pos in range(idx, end):
                    occupied[pos] = True
                picked.append(by_surface[surface])
            start = idx + 1
    # 输出顺序按在文本中首次出现的先后 —— 与用户表述顺序一致（可读性，且确定性）。
    picked.sort(key=lambda t: text.find(t.surface))
    return tuple(picked)


def _time_refs(terms: Iterable[ResolvedTerm]) -> tuple[ResolvedTerm, ...]:
    """只留 `kind == "time"` 的项。"""
    return tuple(t for t in terms if t.kind == "time")


def _ref_of(term: ResolvedTerm) -> str:
    """`time:relative:last_month` → `relative:last_month`（去掉 kind 前缀）。"""
    return term.canonical.split(":", 1)[1] if ":" in term.canonical else ""


# ============================================================================
# 二、区间计算（基准全部来自 `TimeSemantics`）
# ============================================================================

def _boundary(day: date, *, end: bool, tz: ZoneInfo) -> str:
    """把一天渲染成区间端点。

    口径**逐字取自语义包 §9 notes**："'上个月' = 日历上月首日 **00:00:00** 至末日 **23:59:59**（Asia/Shanghai）"。
    ⇒ 闭区间、含时区偏移。**不用 23:59:59.999999**：多出来的微秒没有语义，
    却会让两个实现（本模块 vs 未来的 SQL 侧）在字符串比较上出现无意义差异。
    """
    moment = datetime.combine(day, time(23, 59, 59) if end else time(0, 0, 0), tzinfo=tz)
    return moment.isoformat()


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last = date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    return first, last


def _week_start(day: date, *, week_starts_on: str) -> date | None:
    """本周起点（按 `week_starts_on`）。未知取值返回 `None` —— **不假设周日**。"""
    idx = _WEEKDAY_INDEX.get(week_starts_on.strip().lower())
    if idx is None:
        return None
    return day - timedelta(days=(day.weekday() - idx) % 7)


def resolve_window(
    ref: str,
    *,
    today: date,
    tz: ZoneInfo,
    week_starts_on: str,
    expr: str | None = None,
) -> TimeRange | None:
    """单个 `maps_to_ref` → 绝对区间。无法解析一律返回 `None`（**不猜**）。

    `expr` = 用户侧的**原表达**（如"上月"），写进 `time_range.expr` 供追溯
    （07 §5.2 组 2："`expr` 保留原表达用于追溯"）。**不填 ref** ——
    `relative:last_month` 是我们的中间表示，不是用户说过的话。

    ⚠️ 这里是本模块唯一"有业务知识"的地方，且每条规则都能在上游找到出处：

    | ref | 依据 |
    |---|---|
    | `relative:today` / `yesterday` / `day_before_yesterday` | 字面 |
    | `relative:this_week_monday` / `last_week_monday` | 语义包 notes："'本周' 起点 = 周一（对齐 `meta.week_starts_on`）" |
    | `relative:this_month` / `last_month` | 语义包 notes 的 00:00:00–23:59:59 口径 |
    | `rolling:<n>d_incl_today` | 语义包 notes："'近7天' = 含今天往前 7 个自然日" |
    """
    if ref == "relative:today":
        return _single_day(today, tz=tz, expr=expr)
    if ref == "relative:yesterday":
        return _single_day(today - timedelta(days=1), tz=tz, expr=expr)
    if ref == "relative:day_before_yesterday":
        return _single_day(today - timedelta(days=2), tz=tz, expr=expr)
    if ref == "relative:this_month":
        start, end = _month_bounds(today.year, today.month)
        return _range(start, end, expr=expr, tz=tz)
    if ref == "relative:last_month":
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        start, end = _month_bounds(year, month)
        return _range(start, end, expr=expr, tz=tz)
    if ref in ("relative:this_week_monday", "relative:last_week_monday"):
        monday = _week_start(today, week_starts_on=week_starts_on)
        if monday is None:
            return None
        if ref == "relative:last_week_monday":
            monday -= timedelta(days=7)
        return _range(monday, monday + timedelta(days=6), expr=expr, tz=tz)

    rolling = _ROLLING_RE.match(ref[8:]) if ref.startswith("rolling:") else None
    if rolling is not None:
        days = int(rolling.group(1))
        if days <= 0:
            return None
        return _range(today - timedelta(days=days - 1), today, expr=expr, tz=tz)

    # `campaign:*` / 未知 ref → 未解析（见模块 docstring §四）
    return None


def _single_day(day: date, *, tz: ZoneInfo, expr: str | None = None) -> TimeRange:
    return TimeRange(
        start=_boundary(day, end=False, tz=tz),
        end=_boundary(day, end=True, tz=tz),
        expr=expr,
        tz=str(tz),
    )


def _range(start: date, end: date, *, tz: ZoneInfo, expr: str | None = None) -> TimeRange:
    return TimeRange(
        start=_boundary(start, end=False, tz=tz),
        end=_boundary(end, end=True, tz=tz),
        expr=expr,
        tz=str(tz),
    )


# ============================================================================
# 三、对外的单一入口
# ============================================================================

def resolve_time(
    text: str,
    semantics: SemanticBundlePort,
    clock: ClockPort,
    *,
    max_n: int = MAX_NGRAM,
) -> TimeResolution:
    """问题文本 → (`time_range`, `resolved_terms`, `unresolved_terms`, `time_parse_ok`)。

    `ok=False` 的三种情形（都要走澄清，**不猜**）：

    1. 出现了**大促**表述但区间无结构化来源（`campaign_window_not_structured`）；
    2. 出现了**同环比**表述但**没有**基准区间（`comparison_without_base_period`）——
       "同比"本身不构成一个时间窗，没有基准期就算不出"去年同期"；
    3. 出现了**两个及以上不同**的区间表述（如"上月和本周"）—— 该问的是"哪一个"，
       挑一个就是用沉默替用户做了决定。

    没有任何时间表述时 `ok=True, window=None`：这不是失败，是"问题里没提时间"。
    """
    found = find_alias_terms(text, semantics, max_n=max_n)
    time_terms = _time_refs(found)
    tz = clock.tz()
    semantics_info = clock.semantics()

    refs: list[tuple[str, str]] = []  # (ref, surface)
    for term in time_terms:
        ref = _ref_of(term)
        if ref.startswith("compare:"):
            continue
        if ref not in {r for r, _ in refs}:
            refs.append((ref, term.surface))

    comparisons = tuple(_ref_of(t) for t in time_terms if _ref_of(t).startswith("compare:"))
    unresolved: list[str] = []
    reason: str | None = None

    if len(refs) > 1:
        # 多个不同区间 → 歧义（见函数 docstring）
        unresolved.extend(t.surface for t in time_terms if not _ref_of(t).startswith("compare:"))
        return TimeResolution(
            window=None,
            terms=found,
            unresolved=tuple(unresolved),
            ok=False,
            reason="multiple_time_ranges",
            comparisons=comparisons,
        )

    if refs:
        ref, surface = refs[0]
        window = resolve_window(
            ref,
            today=clock.today(),
            tz=tz,
            week_starts_on=semantics_info.week_starts_on,
            expr=surface,
        )
        if window is None:
            if ref.startswith("campaign:"):
                reason = _UNRESOLVED_REASON_CAMPAIGN
            elif ref.startswith("relative:this_week") or ref.startswith("relative:last_week"):
                reason = _UNRESOLVED_REASON_WEEKSTART
            else:
                reason = _UNRESOLVED_REASON_REF
            unresolved.extend(t.surface for t in time_terms)
            return TimeResolution(
                window=None,
                terms=found,
                unresolved=tuple(unresolved),
                ok=False,
                reason=reason,
                comparisons=comparisons,
            )
        return TimeResolution(
            window=window, terms=found, unresolved=(), ok=True, comparisons=comparisons
        )

    if comparisons:
        # 只有同环比、没有基准期 → 算不出窗（见函数 docstring）
        return TimeResolution(
            window=None,
            terms=found,
            unresolved=tuple(t.surface for t in time_terms),
            ok=False,
            reason=_UNRESOLVED_REASON_COMPARE,
            comparisons=comparisons,
        )

    return TimeResolution(window=None, terms=found, unresolved=(), ok=True, comparisons=())
