"""绑定所需的**请求级输入** —— 端口签名装不下的那一部分。

归属窗口：W3C｜依据：07 §6.8.1（L2 的粒度词抽取）、§6.8.2（L4 的联合打分）。

🔴 **本模块存在的原因是一处真实的契约缺口（已登记，见 RELAY §给 W0 / §给架构）**：
   冻结端口是 `BindingPort.resolve(concept, ctx, candidates)` —— **没有问句**。
   而规范对 `binding` 的两条要求都**必须要问句**：

   | 位置 | 原文要求 | 为什么离不开问句 |
   |---|---|---|
   | 07 §6.8.1 | "从归一化问句抽粒度词…抽取失败 → **不进入 L2**" | 判"是否同粒度"要先知道**用户问的是哪一级**，"城市 vs 区县"正是靠问句里的粒度词区分的 |
   | 07 §6.8.2 | L4 是**联合打分**（问句与候选**同一次调用内**共同参与） | 不给问句，打分器只能按"名字像不像"打分 —— 那正是 PRD §12.9 要禁的双塔余弦语义 |

   **本轮取 D2(a) 方案**（用户已裁）：请求级 `contextvars`（形状照抄 W3A 的 `set_call_context`），
   **同时**向 W0/架构提"端口补问句入参"的正式需求。选它的理由不是优雅，而是**不阻塞**：

   - 扩端口要动 `app/core/contracts.py`（W0）并走编号，会把 W3B/W4 一起挂住；
   - `contextvars` 是**请求级**的（并发不串号），且**未设置时是可见的** —— 见下。

⚠️ **未接线时的行为是刻意"可见且偏安全"，不是静默兜底**：

   - `current_binding_scope().is_set is False` → L1/L3 照常（它们不需要问句），
     **L2 直接不参与**（规范原话就是"抽取失败 → 不进入 L2"），L4 走 fail-safe 判 `ambiguous`；
   - 同时打 `binding_scope_missing` WARN 并计入观测 sink ——
     这样"忘了接线"表现为**一堆澄清**（可见、可查），而不是"猜得挺准"（不可见）。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final

__all__ = [
    "UNSET_SCOPE",
    "BindingRequestScope",
    "clear_binding_scope",
    "current_binding_scope",
    "set_binding_scope",
]


@dataclass(frozen=True, slots=True)
class BindingRequestScope:
    """一次绑定请求的上下文。全部字段都是**请求级**的，且**不出站**（除 `normalized_question`）。

    ⚠️ `normalized_question` 本身就是"允许出站的用户问题"（07 §10.5 ③）——
    L4 打分必须把它原样交给网关，这不是泄漏；**其它字段不得进 payload**。
    """

    #: 归一化后的问题（07 §10.5 ③ 唯一允许出站的用户输入）。
    normalized_question: str = ""
    #: 调用方**自行抽取**的粒度词（可选逃生门：W4 若已抽取，不必让本包再抽一遍）。
    #: 空 = 由本包按语义包的词汇表从 `normalized_question` 抽（07 §6.8.1）。
    grain_words: tuple[str, ...] = ()
    #: 请求声明的**时间语义**（`current` / `transaction_time` / `statistics_period_end`…）。
    #: 用于五步过滤第 ④ 步（`field_binding.time_semantics` 校验）；`None` = 不校。
    time_semantics: str | None = None
    #: 会话固定的 `bundle_version`（N-23：同一会话内不得漂移）。
    #: 本包只用它做**一致性告警**，不做拒绝 —— 会话版本固定是 W4 的活。
    bundle_version: str | None = None

    @property
    def is_set(self) -> bool:
        """是否**真的**被接线设置过（`normalized_question` 非空是判据）。

        ⚠️ 用它而不是判 `None`：`set_binding_scope(BindingRequestScope())` 也是"没给问句"，
        对 L2/L4 而言与"没设置"**等价**，必须走同一条可见的降级路径。
        """
        return bool(self.normalized_question.strip())


#: 未接线时的哨兵。用一个**具名常量**而不是临时构造，是为了让日志与断言里
#: "看起来是空对象"与"确知未设置"可区分（同 W3A `_UNSET_CONTEXT` 的取向）。
UNSET_SCOPE: Final[BindingRequestScope] = BindingRequestScope()

#: ⚠️ 用 `contextvars` 而不是模块级变量：并发请求必须互不串号 ——
#: "把问句挂在全局"在异步服务里是经典事故（B 请求的粒度词决定 A 请求绑哪个字段）。
_SCOPE: ContextVar[BindingRequestScope | None] = ContextVar("binding_request_scope", default=None)


def set_binding_scope(scope: BindingRequestScope) -> None:
    """由**接线层**在进 bind 节点前调用（接线动作归 W4，本包不自行调用）。"""
    _SCOPE.set(scope)


def current_binding_scope() -> BindingRequestScope:
    """取当前请求的绑定上下文；未接线时返回哨兵（**可见**，不静默）。"""
    return _SCOPE.get() or UNSET_SCOPE


def clear_binding_scope() -> None:
    """显式清空（测试与长生命周期 worker 用；请求级任务通常随上下文自然回收）。"""
    _SCOPE.set(None)
