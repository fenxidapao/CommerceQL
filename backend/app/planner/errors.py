"""W3B 的领域异常 —— 只表达"理解/生成这一环失败了"，**不含 HTTP 语义**。

归属窗口：W3B（docs/08 §4.1）｜层号：L3

## 为什么需要自己的异常（而不是复用 `app.llm.errors`）

`app.llm` 的异常（`LlmConcurrencyExceeded` / `LlmUpstreamError` / `LlmRefused` …）
描述的是**出站那一跳**的结果。而本模块还有**出站成功但产出不可用**的失败形态：

- 模型回了 200，但 `content` 不是 JSON、或 JSON 不满足 schema（修复 1 次后仍不满足）。

这类**不能**与 `app.llm` 的异常混为一谈：

| 形态 | 语义 | 处置 |
|---|---|---|
| `LlmConcurrencyExceeded`（F2）/ `LlmUpstreamError`（F3） | 上游抖动 | **error**，上抛（07 §14.2） |
| `LlmRefused` | 产品结论（模板无命中） | **原样上抛**，由 W4 转 `refuse` 终态 |
| 本文件的 `*Unavailable` | 本环节**产出不可用** | **degraded**（07 §5.3 节点 2/3/5/7 的失败转移）→ 模板 → 拒答 |

🔴 **`LlmRefused` 绝不被本模块吞掉**：它 `default_code is None`，一旦被包装成本文件的异常
就会从"产品结论"退化成"一次业务降级"—— 语义就错了。实现里对所有 LLM 异常一律 `raise`。

## 🔴 两个 reason 取值缺口（**如实标注，不自己发明枚举值**）

`DegradedReason`（C-08，落 `core/enums.py`）只有 8 个值，本环节的失败形态**没有专值**：

| 形态 | 应有的 reason | 现状 |
|---|---|---|
| 计划生成失败 | `plan_generation_failed` ✅ 有 | 直接用 |
| **SQL 生成 / 纠错失败** | 应有一个 `sql_generation_failed` | 🔴 **缺** → 复用 `plan_generation_failed`，并在 `detail` 里带 `missing_reason_value` |
| **归一化 / 意图失败** | 应有一个 `understanding_failed`（或承认它等于 `llm_unavailable`） | 🔴 **缺** → 复用 `llm_unavailable`，同样在 `detail` 里标注 |

补值要改 `app/core/enums.py` —— 那是 **W0** 的文件，本窗口只提需求（见 `RELAY.md §给 W0`）。
**不得**在本模块私建一个平行的 reason 枚举（那会制造第二份真相）。
"""

from __future__ import annotations

from app.core.enums import ActionTaken, DegradedReason
from app.planner.schemas import DegradedNote

__all__ = [
    "PlanUnavailable",
    "PlannerError",
    "SqlGenerationUnavailable",
    "UnderstandUnavailable",
]


class PlannerError(Exception):
    """本环节异常基类。

    ⚠️ 刻意**不继承** `app.core.errors.CommerceQLError`：后者是"可跨层抛出、由
    `api/errors.py` 映射成 HTTP 码"的家族，而本文件的异常**不应到达 HTTP 层** ——
    它们必须在 W4 的节点里被捕获并转成 `plan is None` / `refuse`（07 §5.4 的条件边）。
    继承它反而会诱使某个窗口让 `PlanUnavailable` 一路冒到 500，那是错的终态。

    `notes` = 本环节要上报的降级事件（W4 依此发 `degraded`，见 `RELAY.md §给 W4`）。
    """

    def __init__(self, message: str, *, notes: tuple[DegradedNote, ...] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.notes = notes


class UnderstandUnavailable(PlannerError):
    """节点 2/3 失败：归一化 / 意图的产出不可用（出站成功，但 JSON 取不到或 schema 不过）。

    W4 的处置（07 §5.3 节点 3 的失败转移）：`degraded` → 模板 → 未命中 → `refuse`。
    **不是** `error`：没有任何工程故障，只是这一轮的理解环节拿不到可用产出。

    🔴 reason 复用 `llm_unavailable` 并标注缺口（见模块 docstring）。
    """

    def __init__(self, message: str, *, attempts: int, detail: dict[str, object] | None = None) -> None:
        merged: dict[str, object] = {
            "attempts": attempts,
            "stage": "understand",
            "missing_reason_value": "understanding_failed",
        }
        if detail:
            merged.update(detail)
        super().__init__(
            message,
            notes=(
                DegradedNote(
                    reason=DegradedReason.LLM_UNAVAILABLE,
                    action_taken=ActionTaken.TEMPLATE_ONLY,
                    detail=merged,
                ),
            ),
        )
        self.attempts = attempts


class PlanUnavailable(PlannerError):
    """节点 5 失败：计划的产出不可用（出站成功，但 JSON 取不到或 schema 不过）。

    W4 的处置（07 §5.4 `route_after_plan`）：`plan = None` → 发 `degraded` →
    模板匹配 → 命中则继续 `gen_sql`，未命中 → `refuse_out`。

    **不是** `error`：这不是工程故障，是"这一轮拿不到计划"。
    """

    def __init__(self, message: str, *, attempts: int, detail: dict[str, object] | None = None) -> None:
        merged: dict[str, object] = {"attempts": attempts, "stage": "plan"}
        if detail:
            merged.update(detail)
        super().__init__(
            message,
            notes=(
                DegradedNote(
                    reason=DegradedReason.PLAN_GENERATION_FAILED,
                    action_taken=ActionTaken.TEMPLATE_ONLY,
                    detail=merged,
                ),
            ),
        )
        self.attempts = attempts


class SqlGenerationUnavailable(PlannerError):
    """节点 7/16 失败：SQL 生成或纠错的产出不可用。

    🔴 `DegradedReason` 里**没有** `sql_generation_failed`（见模块 docstring 的缺口表），
    故这里复用 `plan_generation_failed` 并在 `detail` 里显式带
    `missing_reason_value="sql_generation_failed"` —— 让"这个值是凑出来的"这件事
    **可被查询**，而不是伪装成语义吻合。
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        detail: dict[str, object] | None = None,
    ) -> None:
        merged: dict[str, object] = {
            "attempts": attempts,
            "stage": "gen_sql",
            "missing_reason_value": "sql_generation_failed",
        }
        if detail:
            merged.update(detail)
        super().__init__(
            message,
            notes=(
                DegradedNote(
                    reason=DegradedReason.PLAN_GENERATION_FAILED,
                    action_taken=ActionTaken.TEMPLATE_ONLY,
                    detail=merged,
                ),
            ),
        )
        self.attempts = attempts
