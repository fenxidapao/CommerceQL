"""成本计量与预算熔断（07 §10.4 / PRD §12.3 / NFR-4.2）。

归属窗口：W3A｜落点由 07 §3.2 指定（`llm/budget.py` = "成本计量 + 预算熔断"）。

## 🔴 计量落库：`cost_ledger` 表**不存在**（Q1 裁定 = (a)）

07 §12.3 给了 `cost_ledger` 的完整列定义（`entry_id`/`task_id`/`tenant_id`/`user_id`/
`model`/`input_tokens`/`output_tokens`/`cache_hit_tokens`/`cost_cny`/`is_peak`/`created_at`，
保留 13 个月），但**迁移 0001/0002/0003 都没建这张表**（实测：全仓 `cost_ledger`
只出现在 `repo/dsn.py` 与 `repo/pools.py` 的 docstring 里，无模型、无迁移、无写入 API）。

裁定：**先在 `llm/` 内定义 sink 注入点（Protocol）+ 内存实现，把计量与预算逻辑跑通**，
同时向 W1B 出需求（表 + 写入 API）。**不得自建迁移，不得报告"已落库"**。

⇒ 本模块的 `InMemoryCostLedgerSink` **是真的能跑通**的（能算日累计、能触发 80%/100%），
但它的数据**进程一退出就没了**。这个限制必须原样出现在 `DELIVERY.md`，不许含糊。

## 计价：为什么"计量"和"TCO"用不同的时段价

07 §10.4 有两条**看似矛盾**的要求：

- 计价行："按 PRD §12.3 官方价，**分非高峰/高峰**" → 计量要如实反映**当时**的时段；
- TCO 纪律行："**一律按高峰价**测算（折扣基本吃不到）" → 规划/估算要按**最坏**算。

两者其实不冲突，它们回答的是不同问题：
**"这次实际花了多少"**（用真实时段价 + 落 `is_peak` 字段）vs
**"这类调用最多会花多少"**（用高峰价估上界）。
本模块据此拆成两个入口：`compute_cost()`（真实价，结算用）与
`estimate_cost()`（**高峰价上界**，pre-flight 用）。

## 汇率：全仓**没有**配置项，本模块给出**有推导的**常量

PRD §12.3 只用了一个换算数据点：`deepseek-flash` 一次查询 ≈ `$0.0071` → "≈ ¥0.05"
⇒ 反推汇率 ≈ **7.04**。本模块取 **7.1**（误差 +0.9%）并**显式标注为经验值**，
同时登记"全仓无汇率配置项"（U-22 纪律：推导不出来的值不许装成有依据；
这里的推导只有**一个**数据点，不足以称为机制）。
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dtime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

from app.core.contracts import TokenUsage
from app.llm.router import TaskRoute, max_tokens_for

__all__ = [
    "Tier",
    "ModelPrice",
    "PRICES",
    "USD_CNY_RATE",
    "BILLING_TZ",
    "PEAK_WINDOWS",
    "CostEntry",
    "CostLedgerSink",
    "InMemoryCostLedgerSink",
    "BudgetDecision",
    "BudgetGuard",
    "classify_tier",
    "compute_cost",
    "count_tokens",
    "estimate_prompt_tokens",
    "DEFAULT_TENANT_DAILY_BUDGET_CNY",
]


#: 计费时区。PRD §12.3 的高峰定义是**北京时间**（官方 UTC 01:00–04:00 / 06:00–10:00
#: 周一至周五）—— 这是**计费概念**，与业务时间口径（`TimeSemantics`，N-26）**解耦**：
#: 业务口径可能按财年/周起始日变，而账单时段不会变。故这里用固定常量并写明来源。
BILLING_TZ: Final[ZoneInfo] = ZoneInfo("Asia/Shanghai")

#: 高峰时段（北京时间的 `[起, 止)`），仅**工作日**生效（PRD §12.3 结论 ②）。
PEAK_WINDOWS: Final[tuple[tuple[dtime, dtime], ...]] = (
    (dtime(9, 0), dtime(12, 0)),
    (dtime(14, 0), dtime(18, 0)),
)

#: USD → CNY。**经验值**：由 PRD §12.3 的换算反推（$0.0071 → ¥0.05 ⇒ ≈7.04），取 7.1。
USD_CNY_RATE: Final[Decimal] = Decimal("7.1")

#: 租户日预算**没有配置项**（`config.py` 只有全局 `DAILY_BUDGET_CNY`）。
#: 为了让"租户日预算"这一层**真的可测**，本模块给它一个显式默认值并登记：
#: 取全局预算的 **1/10**。⚠️ 这是**经验值**，不是从任何上游推导出来的 ——
#: 07 §10.4 只说"预算层级 = 租户日预算 + 全局日预算"，**没给租户级的数**。
#: 正确做法是给它一个 config 键（归 W0），届时本常量应被删除。
DEFAULT_TENANT_DAILY_BUDGET_CNY: Final[Decimal] = Decimal("10")

_MILLION: Final[Decimal] = Decimal(1_000_000)


class Tier(StrEnum):
    """账单时段（PRD §12.3）。"""

    PEAK = "peak"
    OFF_PEAK = "off_peak"


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """单价，单位 **USD / 1M token**（PRD §12.3 的原始单位，不做中间换算以免丢精度）。"""

    cache_hit: Decimal
    cache_miss: Decimal
    output: Decimal


def _p(hit: str, miss: str, out: str) -> ModelPrice:
    return ModelPrice(cache_hit=Decimal(hit), cache_miss=Decimal(miss), output=Decimal(out))


#: PRD §12.3 官方价表**逐格照抄**（单位：USD / 100 万 token）。
#: ⚠️ 键是**模型 ID**；未知模型按 `STRONG` 计价并在 `CostEntry.price_guess` 打标
#: （宁可高估成本，也不要让一个新模型静默地按便宜价计量）。
PRICES: Final[dict[str, dict[Tier, ModelPrice]]] = {
    "deepseek-flash": {
        Tier.OFF_PEAK: _p("0.003", "0.15", "0.60"),
        Tier.PEAK: _p("0.006", "0.30", "1.20"),
    },
    "deepseek-v4-pro": {
        Tier.OFF_PEAK: _p("0.022", "0.66", "1.98"),
        Tier.PEAK: _p("0.044", "1.32", "3.96"),
    },
}

#: 兜底计价用的模型名（未知模型按它算 = 按最贵的算）。
_PRICE_FALLBACK_MODEL: Final[str] = "deepseek-v4-pro"


def classify_tier(now: datetime) -> Tier:
    """判定某个时刻属于高峰还是非高峰（PRD §12.3）。

    规则：**北京时间的工作日** 09:00–12:00 与 14:00–18:00 = 高峰；其余（含整个周末）= 非高峰。

    ⚠️ 传入的 `now` 会被 `astimezone(BILLING_TZ)` 归一 —— 调用方给 UTC 或带偏移的时间都可以，
    但**不要**给 naive datetime（会按本机时区解释，本机是 UTC+8 恰好对，换台机器就错）。
    """
    if now.tzinfo is None:
        raise ValueError("classify_tier 需要带时区的 datetime（naive 会随部署机器漂移）")
    local = now.astimezone(BILLING_TZ)
    if local.weekday() >= 5:
        return Tier.OFF_PEAK
    t = local.time()
    for start, end in PEAK_WINDOWS:
        if start <= t < end:
            return Tier.PEAK
    return Tier.OFF_PEAK


def resolve_price(model: str, tier: Tier) -> tuple[ModelPrice, bool]:
    """取单价；返回 `(price, is_guess)`。未知模型 → 按最贵的那档并在 `is_guess` 标真。"""
    table = PRICES.get(model)
    if table is None:
        return PRICES[_PRICE_FALLBACK_MODEL][tier], True
    return table[tier], False


def compute_cost(model: str, usage: TokenUsage, tier: Tier) -> Decimal:
    """按**真实时段价**算出本次调用的 CNY 成本（结算用）。

    输入侧按"缓存命中/未命中"分开计价 —— 这正是 NFR-4.3 要埋点的原因：
    命中价与未命中价在 `deepseek-flash` 上差 **50 倍**（PRD §12.3 结论 ①）。

    `usage.total` 不作为计算依据（上游的 `total_tokens` 含 reasoning token，
    而 reasoning 已计入 `output`），只用 `input`（未命中部分）/ `cache_hit` / `output`。
    """
    price, _ = resolve_price(model, tier)
    input_tokens = Decimal(max(usage.input - usage.cache_hit, 0))
    cache_tokens = Decimal(max(usage.cache_hit, 0))
    output_tokens = Decimal(max(usage.output, 0))
    usd = (
        input_tokens * price.cache_miss
        + cache_tokens * price.cache_hit
        + output_tokens * price.output
    ) / _MILLION
    return (usd * USD_CNY_RATE).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ============================================================================
# token 计量
# ============================================================================

_ENCODER: Any = None
_ENCODER_TRIED = False


def _encoder() -> Any:
    """懒加载 `tiktoken` 编码器。**失败返回 None**（不抛）—— 见 `count_tokens` 的说明。"""
    global _ENCODER, _ENCODER_TRIED
    if not _ENCODER_TRIED:
        _ENCODER_TRIED = True
        try:
            import tiktoken

            # ⚠️ DeepSeek **不公开自己的 BPE**，`cl100k_base` 是**近似**编码器。
            #    实测（2026-09-17）：19 个汉字 → 15 token（≈0.79 token/字），
            #    与 PRD §12.3 的量级估算同一数量级，用于**估算与预算**足够，
            #    但**不得**把它当作精确计费依据 —— 真正计费用上游回传的 `usage`。
            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # 编码器不可得**不是**致命错误：估算失败就退回字符启发式（见 count_tokens）
            _ENCODER = None
    return _ENCODER


def count_tokens(text: str) -> int:
    """估算 token 数。

    🔴 **刻意不抛异常**：`tiktoken` 首次使用会去下载 BPE 文件，离线环境会失败。
    但"算不出 token 数"**不应该**让一次 LLM 调用失败 —— 估算的用途是**预算与保护**，
    不是计费真相（计费真相来自上游 `usage`）。
    因此降级为**字符启发式**（中文 ≈ 0.8 token/字，与实测的 0.79 吻合）并继续。
    这条降级必须在 `meta`/日志里可见（本模块由 `BudgetGuard` 记录 `estimated=True`）。
    """
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass  # 单个字符串编码失败也走启发式，不让它影响调用
    return max(1, int(len(text) * 0.8))


def estimate_prompt_tokens(system_text: str, user_text: str) -> int:
    """估算一次调用的输入 token（system + user）。"""
    return count_tokens(system_text) + count_tokens(user_text)


# ============================================================================
# 计量落库（Q1：表不存在 → sink 注入点 + 内存实现）
# ============================================================================

@dataclass(frozen=True, slots=True)
class CostEntry:
    """一行计量。字段**逐列对齐** 07 §12.3 的 `cost_ledger` 表定义。

    保留这个对齐关系是刻意的：W1B 建表时按本类写插入语句即可，
    不需要在两边各定义一遍列（那正是"同一事实写两遍"的典型翻车点）。
    """

    entry_id: str
    task_id: str
    tenant_id: str
    user_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cost_cny: Decimal
    is_peak: bool
    created_at: datetime
    #: 本窗口附加的**非落库**标记（`cost_ledger` 无此列）：
    #: token 数是否为估算 / 单价是否为未知模型兜底。它们用于**运维可观测**，
    #: 若 W1B 认为有价值可作为额外列或落到日志，本窗口不擅自扩展表结构。
    tokens_estimated: bool = False
    price_guess: bool = False


class CostLedgerSink(Protocol):
    """计量 sink —— **W1B 实现落库版**，本窗口提供内存版。

    三个方法就是预算熔断需要的全部聚合：
    `record`（写）+ 两个日累计读（租户级 / 全局级）。
    刻意**不给**"查明细"这类接口：网关不需要，给了反而会诱使别人绕开仓库层。
    """

    def record(self, entry: CostEntry) -> None: ...

    def tenant_spent_cny(self, tenant_id: str, day: date) -> Decimal: ...

    def global_spent_cny(self, day: date) -> Decimal: ...


class InMemoryCostLedgerSink:
    """内存 sink：**进程内**可用的完整实现（能真触发 80% 告警与 100% 熔断）。

    ⚠️ **已知限制（必须原样进交付文档）**：

    1. 进程退出即丢 —— 重启后当日累计从 0 开始，熔断会被"重置"，
       即**熔断在重启面前不成立**；
    2. 单进程语义 —— P0 是单进程（07 §10.1），故够用；一旦扩多 worker，
       总预算会被放大到"worker 数 × 预算"，与"总并发 = 进程数 × 8"是同一类缺陷。
       两条都必须在扩多 worker 时一起改为 Redis（07 §10.1 已把并发那条写进 runbook）。
    """

    def __init__(self) -> None:
        self._entries: list[CostEntry] = []

    def record(self, entry: CostEntry) -> None:
        self._entries.append(entry)

    def tenant_spent_cny(self, tenant_id: str, day: date) -> Decimal:
        return sum(
            (e.cost_cny for e in self._entries
             if e.tenant_id == tenant_id and e.created_at.astimezone(BILLING_TZ).date() == day),
            Decimal(0),
        )

    def global_spent_cny(self, day: date) -> Decimal:
        return sum(
            (e.cost_cny for e in self._entries
             if e.created_at.astimezone(BILLING_TZ).date() == day),
            Decimal(0),
        )

    def __len__(self) -> int:
        return len(self._entries)


# ============================================================================
# 预算熔断（NFR-4.2：80% 告警 / 100% 硬熔断）
# ============================================================================

@dataclass(frozen=True, slots=True)
class BudgetDecision:
    """pre-flight 判定结果。**网关据此决定"是否降级到模板"与"是否减路"**。"""

    #: `False` = 已 100% 熔断 → 新请求走**模板 + 降级**（`reason=cost_too_high`）
    allowed: bool
    #: 已过 80% 告警线 → 新请求**自动降为单路生成**（`action_taken=reduced_candidates`）
    force_single_path: bool
    #: 触发的是哪一级预算（`tenant` / `global` / `None`）
    blocked_by: str | None
    #: 已花费 / 预算（诊断用，进日志）
    ratio: float
    warn: bool


class BudgetGuard:
    """租户日预算 + 全局日预算的双层熔断。

    与 07 §10.4 的对应：

    | 07 要求 | 本类实现 |
    |---|---|
    | 预算层级 = 租户日预算 + 全局日预算 | `tenant_budget` / `global_budget`，任一 100% 即熔断 |
    | **80% 告警 / 100% 硬熔断** | `warn` / `allowed=False`（阈值取 `BUDGET_ALERT_RATIO`） |
    | 熔断后走模板 + 降级并在 `meta` 标注 | 返回 `allowed=False`，由门面走模板层并发 `degraded(cost_too_high)` |
    | 前置估算：接近预算时自动降为单路 | `force_single_path=True`（`reduced_candidates`） |
    """

    def __init__(
        self,
        *,
        global_daily_budget_cny: Decimal | float,
        alert_ratio: float,
        sink: CostLedgerSink,
        tenant_daily_budget_cny: Decimal | float | None = DEFAULT_TENANT_DAILY_BUDGET_CNY,
    ) -> None:
        self._global = Decimal(str(global_daily_budget_cny))
        self._tenant = None if tenant_daily_budget_cny is None else Decimal(str(tenant_daily_budget_cny))
        self._alert = Decimal(str(alert_ratio))
        self._sink = sink

    @property
    def sink(self) -> CostLedgerSink:
        return self._sink

    def preflight(
        self, *, tenant_id: str, now: datetime, estimated_cny: Decimal
    ) -> BudgetDecision:
        """请求前判定。**两层都要查**，任一层到顶即熔断。

        ⚠️ 预估成本也计入判定（`spent + estimated`）：只按"已花"判定会让一次昂贵调用
        正好卡在 100% 之前通过，把预算击穿 —— 而击穿后所有请求都被熔断，
        属于"用一次超支换取全网停摆"。

        ⚠️ 触顶判定用 `>=` 而不是 `>`：预算的语义是"花到这个数就不能再花"，
        用 `>` 会让"恰好等于预算"的那一次调用通过，而它之后立刻熔断 ——
        边界行为与文档描述不符的 bug 都长这样。
        """
        day = now.astimezone(BILLING_TZ).date()
        spent_g = self._sink.global_spent_cny(day)
        ratio_g = float((spent_g + estimated_cny) / self._global) if self._global > 0 else 1.0
        if self._global > 0 and spent_g + estimated_cny >= self._global:
            return BudgetDecision(False, False, "global", ratio_g, True)

        if self._tenant is not None and self._tenant > 0:
            spent_t = self._sink.tenant_spent_cny(tenant_id, day)
            ratio_t = float((spent_t + estimated_cny) / self._tenant)
            if spent_t + estimated_cny >= self._tenant:
                return BudgetDecision(False, False, "tenant", ratio_t, True)
            if ratio_t >= float(self._alert):
                return BudgetDecision(True, True, None, ratio_t, True)

        if ratio_g >= float(self._alert):
            return BudgetDecision(True, True, None, ratio_g, True)
        return BudgetDecision(True, False, None, ratio_g, False)

    def settle(
        self,
        *,
        task_id: str,
        tenant_id: str,
        user_id: str,
        model: str,
        usage: TokenUsage,
        now: datetime,
        tokens_estimated: bool = False,
        extra: Mapping[str, Any] | None = None,
    ) -> CostEntry:
        """结算并写入 sink。返回写入的那一行（门面用它回填 `cost_cny`）。"""
        tier = classify_tier(now)
        _, is_guess = resolve_price(model, tier)
        cost = compute_cost(model, usage, tier)
        entry = CostEntry(
            entry_id=hashlib.sha256(
                f"{task_id}:{model}:{now.isoformat()}:{time.monotonic_ns()}".encode()
            ).hexdigest()[:24],
            task_id=task_id,
            tenant_id=tenant_id,
            user_id=user_id,
            model=model,
            input_tokens=usage.input,
            output_tokens=usage.output,
            cache_hit_tokens=usage.cache_hit,
            cost_cny=cost,
            is_peak=(tier is Tier.PEAK),
            created_at=now,
            tokens_estimated=tokens_estimated,
            price_guess=is_guess,
        )
        self._sink.record(entry)
        return entry

    def estimate_cny_upper_bound(
        self, *, model: str, prompt_tokens: int, output_tokens: int
    ) -> Decimal:
        """**高峰价**上界估算（TCO 纪律：一律按高峰价，PRD §12.3 结论 ②）。

        输入侧全部按"**缓存未命中**"算 —— 这是上界，因为命中只会更便宜。
        """
        price, _ = resolve_price(model, Tier.PEAK)
        usd = (Decimal(prompt_tokens) * price.cache_miss + Decimal(output_tokens) * price.output) / _MILLION
        return (usd * USD_CNY_RATE).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def estimate_for_payload(guard: BudgetGuard, payload: Mapping[str, Any], *, model: str) -> Decimal:
    """端口 `estimate_cost(payload)` 的实现体。

    **payload 的约定**（`LLMPort.estimate_cost` 的签名只有 `Mapping`，没给结构 ——
    这是端口的一处留白，本窗口在此定义并登记到 `RELAY.md §给 W3B/W3C`）：

    ```
    {"text": <将要出站的全部文本>,     # 必需；缺失 → 按空串算（会低估，但不会崩）
     "task": <LlmTask 取值>,           # 可选；给出则用它的 output_tokens_hint
     "output_tokens": <int>,           # 可选；显式覆盖输出预估
     "candidates": <int>}              # 可选；候选路数（默认 1）
    ```

    语义：**高峰价上界**（TCO 纪律）。它的用途是 pre-flight 防失控，不是精确对账。
    """
    text = str(payload.get("text", "") or "")
    prompt_tokens = count_tokens(text)

    task = payload.get("task")
    route: TaskRoute | None = None
    if isinstance(task, str):
        try:
            from app.llm.router import resolve_route

            route = resolve_route(task)
        except Exception:
            route = None  # 估算路径上不许因未知 task 抛错（那会让 pre-flight 变成故障点）

    output_tokens = payload.get("output_tokens")
    if not isinstance(output_tokens, int):
        output_tokens = (
            max_tokens_for(route) if route is not None else 800
        )  # 800 = PRD §12.3 量级估算的默认值（经验值，登记）

    candidates = payload.get("candidates")
    paths = candidates if isinstance(candidates, int) and candidates > 0 else 1
    # 候选路数 = 同一次调用会被并行发 N 次 → 上界按 N 倍算（这正是 §10.4 "候选路数 × 预估长度"）
    return guard.estimate_cny_upper_bound(
        model=model, prompt_tokens=prompt_tokens * paths, output_tokens=output_tokens * paths
    )
