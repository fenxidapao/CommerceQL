"""唯一时间来源（N-18）—— 全系统**禁止**直接调用系统时间。

归属窗口：W0（docs/08 §4.1）。

规则（两条，都会由静态检查/单测兜住）：
1. **禁止**在业务代码里出现 `datetime.now()` / `datetime.utcnow()` / `date.today()` / `time.time()`；
   一律走本模块的 `ClockPort` 实现。
2. 时间口径（财年起点 / 周起点 / 时区 / 大促窗口）**只能来自语义包**（N-26），
   由 `TimeSemantics` 携带，**不得**在本模块里写死任何月份或星期常量。

本模块**只提供时间"读取"能力**，不含任何口径计算 ——
"把'上个月'解析成绝对区间"属 `normalize` 节点的职责（07 §5.2 组 2）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core.contracts import TimeSemantics

__all__ = ["Clock", "FrozenClock"]


class Clock:
    """生产用时钟：时间来自操作系统，**口径来自语义包**。

    ⚠️ 构造时必须传入 `TimeSemantics`。若拿不到语义包口径 → 说明启动校验漏了，
    此时**应当拒绝启动**（`app.core.errors.SemanticBundleError`），而不是回落到默认值：
    回落到默认值会让"财年算错"这类错误静默发生（FR-1.2 / N-26）。
    """

    __slots__ = ("_semantics", "_tz")

    def __init__(self, semantics: TimeSemantics) -> None:
        self._semantics = semantics
        self._tz = ZoneInfo(semantics.timezone)

    def now(self) -> datetime:
        """当前**带时区**时间（永远不是 naive datetime）。

        naive datetime 是本类项目最常见的静默 bug 来源：跨时区比较会抛
        `TypeError` 或给出错误差值，且往往到生产环境才暴露。
        """
        return datetime.now(tz=self._tz)

    def now_utc(self) -> datetime:
        """UTC 时间（仅用于落库时间戳的单调性，不参与口径计算）。"""
        return datetime.now(tz=UTC)

    def today(self) -> date:
        return self.now().date()

    def tz(self) -> ZoneInfo:
        return self._tz

    def semantics(self) -> TimeSemantics:
        return self._semantics


@dataclass(frozen=True, slots=True)
class FrozenClock:
    """测试用冻结时钟（07 §17.2 测试夹具）。

    没有它，时间相关断言只能靠 `freezegun` 之类的全局打桩 —— 那会污染进程内其它测试。
    这里用一个显式对象把时间变成**入参**，时间旅行测试即可写成纯粹的函数式断言。

    用法：边界用例必须覆盖 **周一 / 月末 / 年末 / 大促窗口**（N-26 检查方式）。
    """

    _now: datetime
    _semantics: TimeSemantics

    def now(self) -> datetime:
        return self._now

    def now_utc(self) -> datetime:
        return self._now.astimezone(UTC)

    def today(self) -> date:
        return self._now.date()

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self._semantics.timezone)

    def semantics(self) -> TimeSemantics:
        return self._semantics
