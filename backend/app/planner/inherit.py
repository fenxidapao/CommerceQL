"""多轮**条件继承**（B6 / U-154）—— 纯函数，不调 LLM、不碰 I/O。

## 边界

- 输入只有：本轮 LLM 产出的 `Plan`、上一轮**脱敏计划摘要**（C-01 键集）、归一化后的问题。
- 只补**空位**：本轮计划已经给出的字段**一律不覆盖**（模型的当前判断优先于历史）。
- 只继承**非结构字段**：`time_range` / `dimensions` / `filters` / `grain` / `order_by` / `limit`。
  `assets` / `output_columns` **不继承** —— 摘要里没有关联键与物理列，拼半份计划比缺字段更危险。
- `metrics` **在「本轮为空」时按名继承**，但有一个硬前提：调用方必须给出 `is_metric_active`，
  未定义或 `draft` 的指标**一律不进计划**；没给检查器就**不继承**（证明不了 active 就不补）。
  书面裁定见 `docs/07 §4.8` 的 `U-169`（含「`caliber` 不由继承合成」一条）。
- 只在问题形似**追问**时启用（见 `FOLLOW_UP_CUES`）。判据是本窗自设的启发式，
  07/PRD 没有规则；宁可少继承，不把独立新问题硬接在上一轮上。

## 为什么不做成 prompt 里的历史计划块

多轮会改 prompt ⇒ 既有 cassette 全量 miss。B6 的目标是"条件继承可测、可回退"，
不是"再录一遍全量匣带"。继承结果通过**本轮计划本身**进入 `gen_sql` 的 `$constraints`，
出站面不新增字段（`history_plan` 在 `PROMPT_ALLOWED_FIELDS` 之外）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.planner.schemas import Plan

__all__ = [
    "FOLLOW_UP_CUES",
    "InheritanceResult",
    "inherit_plan",
    "looks_like_follow_up",
]

#: 追问线索（自设启发式）：省略/指代/换条件/继续比较。
FOLLOW_UP_CUES: Final[tuple[str, ...]] = (
    "那",
    "呢",
    "再",
    "换成",
    "改为",
    "改成",
    "同样",
    "继续",
    "它",
    "这个",
    "那个",
    "上述",
    "前面",
    "刚才",
    "同比",
    "环比",
    "按",
    "只看",
    "哪个",
    "一起",
    "也",
)

#: 超过这个长度基本是一句完整的新问题，不做继承（避免"看起来像追问"的长句误接）。
_MAX_FOLLOW_UP_CHARS: Final[int] = 24

#: 继承列表字段时的条数上限（历史摘要本身也已限长，这里再兜一层）。
_MAX_LIST_ITEMS: Final[int] = 20


@dataclass(frozen=True, slots=True)
class InheritanceResult:
    plan: Plan
    fields: tuple[str, ...] = ()


def looks_like_follow_up(question: str) -> bool:
    text = question.strip()
    if not text or len(text) > _MAX_FOLLOW_UP_CHARS:
        return False
    return any(cue in text for cue in FOLLOW_UP_CUES)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value[:_MAX_LIST_ITEMS]:
        text = item.strip() if isinstance(item, str) else ""
        if text:
            out.append(text)
    return out


def inherit_plan(
    plan: Plan,
    history_plan: Mapping[str, Any] | None,
    question: str,
    *,
    is_metric_active: Callable[[str], bool] | None = None,
) -> InheritanceResult:
    """按"只补空位"的规则合并上一轮计划摘要；没有可继承项时原样返回。"""
    if not history_plan or not looks_like_follow_up(question):
        return InheritanceResult(plan)

    data = plan.model_dump()
    fields: list[str] = []

    if plan.time_range.start is None and plan.time_range.end is None:
        raw_window = history_plan.get("time_range")
        if isinstance(raw_window, Mapping):
            window = {
                side: str(raw_window[side]).strip()
                for side in ("start", "end")
                if isinstance(raw_window.get(side), str) and str(raw_window[side]).strip()
            }
            if window:
                data["time_range"] = window
                fields.append("time_range")

    #: U-169：`metrics` 只在本轮为空、且**能证明指标 active** 时按名继承。
    #: `history_plan` 的 `metrics` 是**名字串**（`PlanSummary.metrics`），不是 `PlanMetric`；
    #: 这里转成 `{"name": ...}`，`caliber` 留空 —— 从语义包合成口径属另一件事（见 §4.8 的书面裁定）。
    #: 没给检查器就**不继承**：证明不了 active 的指标不许进计划（`FR-12.3`）。
    if not data.get("metrics") and is_metric_active is not None:
        names = [n for n in _strings(history_plan.get("metrics")) if is_metric_active(n)]
        if names:
            data["metrics"] = [{"name": n} for n in names]
            fields.append("metrics")

    for key in ("dimensions", "filters", "order_by"):
        if not data.get(key):
            values = _strings(history_plan.get(key))
            if values:
                data[key] = values
                fields.append(key)

    if not data.get("grain"):
        grain = history_plan.get("grain")
        if isinstance(grain, str) and grain.strip():
            data["grain"] = grain.strip()
            fields.append("grain")

    if data.get("limit") is None:
        limit = history_plan.get("limit")
        if isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= 10_000:
            data["limit"] = limit
            fields.append("limit")

    if not fields:
        return InheritanceResult(plan)
    return InheritanceResult(Plan.model_validate(data), tuple(fields))
