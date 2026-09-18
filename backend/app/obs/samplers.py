"""周期采样器 —— 07 §15.3 里"没有请求也得有值"的那一类指标。

归属窗口：W7（docs/08 §4.1：`app/obs/**` 的采样器部分）

## 为什么是"采样器"而不是"在业务代码里埋点"
有些量的本体是**状态**而不是**事件**：事件循环卡了多久、上游信号量占了几格、
今天累计花了多少钱。它们没有"发生的那一刻"可埋点 —— 只有周期读一次才看得见。
反过来，事件类指标（终态、闸门拒绝、降级）**一律**由 `ObservingMiddleware` 或业务侧的
显式 `observe_*` 采集，绝不用采样去猜（采样会把"发生过 3 次"读成"1 次"）。

## 三条纪律
1. **单次采集失败不得打断循环**：记一条 WARN 后继续下一个周期。
   采样器挂掉的后果是"看板少一条线"，进程挂掉的后果是没有服务 —— 前者绝不能升级成后者。
2. **N-18：本模块不碰 `datetime.now()`**。"今天"由注入的 `ClockPort.today()` 给
   —— 成本按天聚合的口径必须与预算账本同一时钟，否则日成本与日预算会错一天。
3. **拿不到就什么都不写**：绝不用 0 冒充"测到了 0"。`/healthz/live` 在拿到第一个样本前
   返回 `event_loop_lag_ms: null`（§A.8.2 的"阻塞 > 5s → 503"依赖它，填 0 等于宣称健康）。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Protocol

from app.core.contracts import ClockPort
from app.obs import metrics
from app.obs.logging import get_logger

__all__ = [
    "CostLedgerView",
    "SamplerRunner",
    "SamplerSpec",
    "make_cost_sampler",
    "make_upstream_concurrency_sampler",
    "run_periodic",
]

_log = get_logger(__name__)

#: 循环延迟的采样间隔。取 1s 是因为 liveness 的判据是"阻塞 > 5s"（§A.8.2）——
#: 间隔大于阈值就等于"永远来不及在重启判据生效前测到"。
LOOP_LAG_INTERVAL_S: Final[float] = 1.0

#: 慢状态量（成本 / 上游并发）的采样间隔：与抓取间隔（15s）对齐，看板粒度够，
#: 且每轮只有一次内存读 —— 不该比它更贵。
STATE_SAMPLER_INTERVAL_S: Final[float] = 15.0


class CostLedgerView(Protocol):
    """`app/llm/budget` 账本里采样器需要的那一个方法（不 import W3A 的具体类）。

    用 `Protocol` 而不是直接标 `CostLedger` 的理由：`budget.py` 的账本类型在
    **默认预算路径**下可以整体不存在（`gateway=None` 的降级装配，见 `deps.py`），
    而这里要的只是"能问到某天花了多少钱"这一件事。
    """

    def global_spent_cny(self, day: date) -> Decimal: ...


def make_cost_sampler(ledger: CostLedgerView, clock: ClockPort) -> Callable[[], Awaitable[None]]:
    """日成本 gauge（§15.3 成本行；"80% / 100% 预算"两条告警的唯一数据源）。"""

    async def sample() -> None:
        metrics.observe_daily_cost_cny(float(ledger.global_spent_cny(clock.today())))

    return sample


def make_upstream_concurrency_sampler(
    accessor: Callable[[str], int], models: Sequence[str]
) -> Callable[[], Awaitable[None]]:
    """上游并发占用 gauge（§15.3 系统行；也是"429 比率 >5%"告警的定位手段）。

    ⚠️ `accessor` 由组装根注入。W3A 的 `ChatClient` 目前只在内部持有每模型的
    `asyncio.Semaphore`，**没有公开"已占用几格"的读口** —— 在拿到那一行代码之前
    本采样器**不接线**（接缝需求见 `reports/w7/RELAY.md`），而不是去翻
    `client._semaphores[...]` 私有字段：那等于把"改个属性名就让告警失效"写进主干。
    """

    async def sample() -> None:
        for model in models:
            metrics.observe_upstream_concurrency(model, int(accessor(model)))

    return sample


@dataclass(frozen=True, slots=True)
class SamplerSpec:
    """一个采样器：名字（进日志用）+ 间隔 + 无参异步钩子。"""

    name: str
    interval_s: float
    hook: Callable[[], Awaitable[None]]


async def run_periodic(spec: SamplerSpec) -> None:
    """跑一个采样循环，直到被取消。

    ⚠️ `except CancelledError: raise` 必须排在 `except Exception` **之前** ——
    反过来的顺序会把停机时的取消当成"采集失败"吞掉，采样器于是永远关不掉。
    """
    while True:
        await asyncio.sleep(spec.interval_s)
        try:
            await spec.hook()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 单次采集失败不许打断循环（模块 docstring 纪律 1）
            _log.warning("sampler_tick_failed", sampler=spec.name, error_type=type(exc).__name__)


async def run_loop_lag(interval_s: float = LOOP_LAG_INTERVAL_S) -> None:
    """事件循环延迟采样：睡到"应该在的时刻"，把实际醒来时刻的偏差写进 gauge。

    为什么不用 `loop.slow_callback_duration`：那是 debug 模式下**回调执行超时**的计数，
    与"一次响应被拖了多少毫秒"不是一回事，而 §A.8.2 的判据是毫秒级延迟。
    """
    loop = asyncio.get_running_loop()
    next_due = loop.time() + interval_s
    while True:
        delay = next_due - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        metrics.set_event_loop_lag_ms(max(0.0, (loop.time() - next_due) * 1000.0))
        next_due += interval_s


class SamplerRunner:
    """启动/停机时成对管理的采样器集合（由 `main.py` 的 lifespan 持有）。

    刻意**不**在构造时启动：第 3~5 步 fail-fast 装配失败时若已经起了后台任务，
    它们会在一个没有依赖的进程里空转并刷 WARN 日志。
    """

    __slots__ = ("_loop_lag_interval_s", "_specs", "_tasks")

    def __init__(
        self,
        specs: Sequence[SamplerSpec] = (),
        *,
        loop_lag_interval_s: float = LOOP_LAG_INTERVAL_S,
    ) -> None:
        self._specs = list(specs)
        self._loop_lag_interval_s = loop_lag_interval_s
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> int:
        """启动全部采样器（含循环延迟）。返回后台任务数 —— 启动日志用它自证"真的起了"。"""
        if self._tasks:
            return len(self._tasks)
        self._tasks.append(
            asyncio.create_task(run_loop_lag(self._loop_lag_interval_s), name="obs-loop-lag")
        )
        for spec in self._specs:
            self._tasks.append(asyncio.create_task(run_periodic(spec), name=f"obs-{spec.name}"))
        return len(self._tasks)

    async def stop(self) -> None:
        """取消并**等待**收尾：只 cancel 不 await 会让任务在事件循环关闭时仍在跑
        （uvicorn 侧的表现是 shutdown 阶段一条 "Task was destroyed but it is pending"）。"""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()

    @property
    def started(self) -> bool:
        return bool(self._tasks)
