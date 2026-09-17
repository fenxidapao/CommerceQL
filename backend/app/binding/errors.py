"""绑定层领域异常 —— **不含 HTTP 语义**（与 `app/core/errors.py` 的分工一致）。

归属窗口：W3C（docs/08 §4.1）｜依据：07 §6.8、N-27。

为什么本包只需要**一个很小的异常族**：绑定层的"失败"绝大多数**不是异常**，而是
`BindingResult` 四态里的一态（`ambiguous` / `unresolved`）。真正的异常只剩三类，
它们有一个共同点 —— **都不是"这次查询没绑上"，而是"系统本身不可信了"**：

| 异常 | 什么时候响 | 为什么不降级 |
|---|---|---|
| `BindingBundleInconsistency` | 语义包的**层级刻度自相矛盾**（同名层级在两个维度里给了两个值） | 继续跑 = 按一个错刻度做粒度判定，会**静默绑错字段**（不报错，最难查） |
| `BindingTauScorerMismatch` | 实际打分器标识 ≠ τ 所绑定的 `(model_id, prompt_version)` | N-27 约束②：分数量纲随 prompt 漂移 → 不匹配时 τ **不再是同一个阈值** |
| `BindingScoreMisuse` | 把裸 `float` 当 `RerankScore` 用（N-27 检查方式①） | 类型误用正是"双塔余弦分混进来"的唯一入口，必须硬拦 |

反过来，L4 的**解析失败**刻意**不在此列**：它的正确响应是 fail-safe 判 `ambiguous`（产品结论），
所以那是 `ScoreOutcome(failed=True)` 这个**返回值**，不是异常（见 `scores.py`）。
"""

from __future__ import annotations

from app.core.errors import CommerceQLError

__all__ = [
    "BindingBundleInconsistency",
    "BindingError",
    "BindingScoreMisuse",
    "BindingTauScorerMismatch",
]


class BindingError(CommerceQLError):
    """绑定层全部异常的基类。默认码由 `app/api/errors.py` 兜底为 `INTERNAL`。"""

    default_code = "INTERNAL"


class BindingBundleInconsistency(BindingError):
    """语义包的层级刻度自相矛盾 → **fail-closed**（07 §6.8.1）。

    `grain_level` 是**族内刻度**（地理族 `country=1 … city=4`），判"是否同粒度"靠**数值相等**。
    若同一族里两个维度给同一个层级名配了不同的值，那么"相等"这个判据本身就失去了意义 ——
    此时继续绑定只会产出一个**看起来正常的错绑定**。宁可拒绝。
    """


class BindingTauScorerMismatch(BindingError):
    """τ 所绑定的打分器标识 ≠ 本次实际使用的打分器（N-27 约束② / PRD §6.3.1）。

    ⚠️ **仅改 prompt 也会触发**：LLM 精排的分数量纲随 prompt 漂移，所以打分器标识是
    `(model_id, prompt_version)` 二元组，不是单独的模型名。命中本异常 = τ 需要**重新校准**
    （不是把 τ 改大或改小 —— 那正是 N-25 明令禁止的动作）。
    """


class BindingScoreMisuse(TypeError):
    """把非 `RerankScore` 的值传进了四层判定（N-27 检查方式①）。

    继承 `TypeError` 而不是 `CommerceQLError`：它**不是**业务失败，是**编程错误**，
    应当像写错参数一样在测试期就炸掉（且不得被 `except CommerceQLError` 悄悄吞掉）。
    """
