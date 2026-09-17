"""T3 路由表单测 —— **PRD §12.2 / 07 §16.1/§16.2/§6.8.2 的逐格照抄**与 fail-fast 纪律。

本文件的三类断言，各自防一类事故：

| 类别 | 防的事故 |
|---|---|
| **表完整性**（每个 task 有路由、字段与键一致） | 新增 task 忘配路由 → 运行到那一步才炸 |
| **上游取值照抄**（模型档/思考位/超时值） | 有人"顺手调一下"把 PRD 的表改成了自己的直觉 |
| **fail-fast**（未知 task / 未知模型不猜） | N-21 静默降级：猜一个"最近的"模型跑下去，成本与质量都无声漂移 |

⚠️ 本文件**不测**"表里的值合不合理"这类判断题 —— 那是架构窗口的裁决权
（`gen_sql` 1.3s 与 pro 思考物理不兼容那件事已登记在 `DELIVERY.md`）。
这里只钉住"表里写的**就是**上游文档写的"。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import ClassVar

import pytest

from app.llm.errors import LlmUnknownModel, LlmUnknownTask
from app.llm.router import (
    MODEL_AUTO,
    MODEL_HARD_TIMEOUT_S,
    TASK_ROUTES,
    THINKING_HEADROOM_TOKENS,
    LlmTask,
    ModelKey,
    degrade_target,
    effective_timeout_s,
    max_tokens_for,
    resolve_model_name,
    resolve_route,
)

#: 测试用的模型名映射（真实值来自 config，这里刻意用**可辨认的假名**，
#: 以免测试在"config 恰好等于某个字面量"时产生假绿）。
_MODEL_NAMES: dict[ModelKey, str] = {
    ModelKey.FAST: "test-flash",
    ModelKey.STRONG: "test-pro",
}


class TestRouteTableCompleteness:
    def test_every_task_has_a_route(self) -> None:
        """路由表与 task 枚举必须**一一对应**（多一个少一个都是 bug）。"""
        assert set(TASK_ROUTES) == set(LlmTask)

    def test_route_task_field_matches_its_key(self) -> None:
        """`TaskRoute.task` 是冗余字段 —— 冗余字段漂了就是"审计时看到的路由不是真路由"。"""
        for key, route in TASK_ROUTES.items():
            assert route.task is key, key.value

    def test_route_is_frozen_dataclass(self) -> None:
        """路由表是要被审计的产物，不是运行时状态：改它必须改代码、走 review。"""
        route = TASK_ROUTES[LlmTask.PLAN]
        with pytest.raises(FrozenInstanceError):
            route.timeout_s = 999  # type: ignore[misc]


class TestUpstreamValuesAreCopiedVerbatim:
    """表内容 = PRD §12.2 + 07 §16.1/§16.2/§6.8.2 的**逐格照抄**。"""

    #: 07 §16.1/§16.2/§6.8.2 给的**任务级**延迟预算（秒）。
    _DOCUMENTED_BUDGETS: ClassVar[dict[LlmTask, float]] = {
        LlmTask.NORMALIZE: 0.6,          # §16.1 行2
        LlmTask.INTENT: 0.6,             # §16.1 行3
        LlmTask.NORMALIZE_INTENT: 1.2,   # §16.2 合并档
        LlmTask.RERANK: 0.8,             # §16.1 行4「精筛」
        LlmTask.PLAN: 1.0,               # §16.1 行5
        LlmTask.GEN_SQL: 1.3,            # §16.1 行7
        LlmTask.PRESENT: 1.5,            # §16.1 行13
        LlmTask.L4_SCORE: 0.8,           # §6.8.2「0.3–0.8s」的上界
    }

    @pytest.mark.parametrize(("task", "expected"), sorted(_DOCUMENTED_BUDGETS.items()))
    def test_documented_budgets_are_copied(self, task: LlmTask, expected: float) -> None:
        assert TASK_ROUTES[task].timeout_s == pytest.approx(expected), task.value

    @pytest.mark.parametrize("task", [LlmTask.GEN_SQL_COMPLEX, LlmTask.REPAIR])
    def test_tasks_without_a_documented_budget_declare_None(self, task: LlmTask) -> None:
        """🔴 **07 在这两个 task 上没给任务级预算** —— 唯一合法的表达是 `None`。

        防的是"必须给值但文档没给 ⇒ 实现者发明一个数字"。07 里找不到这三个任务的
        延迟预算，所以填任何秒数都是**编造**；`None` 让"我们不知道"这件事留在代码里，
        并退化为 07 §10.2 的模型级上限（见 `test_None_degrades_to_model_hard_limit`）。
        """
        assert TASK_ROUTES[task].timeout_s is None, task.value

    def test_only_the_complex_sql_task_uses_the_strong_model(self) -> None:
        """PRD §12.2：只有 L3+ 的 `gen_sql_complex` 走高档；其余一律 flash。"""
        strong = {t for t, r in TASK_ROUTES.items() if r.model_key is ModelKey.STRONG}
        assert strong == {LlmTask.GEN_SQL_COMPLEX}

    def test_only_the_complex_sql_task_thinks(self) -> None:
        """PRD §12.2 的"模式"列：**唯一**走"思考"的档是 L3+。

        ⚠️ 这条不只是性能约束 —— 实测（2026-09-17）思考会吃掉 `max_tokens` 并让
        `content` 变空。思考位一旦被顺手打开，症状是"稳定空答案"，不是"慢一点"。
        """
        thinking = {t for t, r in TASK_ROUTES.items() if r.thinking}
        assert thinking == {LlmTask.GEN_SQL_COMPLEX}

    def test_temperature_is_zero_everywhere(self) -> None:
        """PRD §12.9 约束 1 明确要求 L4 打分器温度 0；其余取 0 保评测可复现。

        非零温度会让"同一份冻结集跑两次结果不同"，而 eval 的口径是**不许调参**的。
        """
        for task, route in TASK_ROUTES.items():
            assert route.temperature == 0.0, task.value

    def test_every_task_uses_json_output(self) -> None:
        """07 §10.3：本项目"一律 JSON Output"，**无例外**。"""
        for task, route in TASK_ROUTES.items():
            assert route.json_output is True, task.value

    def test_every_route_carries_a_traceable_budget_source(self) -> None:
        """`budget_source` 是人读的追溯标签：没有它，"这个 0.8 从哪来"只能靠考古。"""
        for task, route in TASK_ROUTES.items():
            assert route.budget_source, task.value
            assert "§" in route.budget_source, task.value  # 必须指到具体章节

    def test_output_hints_are_positive(self) -> None:
        for task, route in TASK_ROUTES.items():
            assert route.output_tokens_hint > 0, task.value


class TestResolveRoute:
    def test_known_task_returns_its_route(self) -> None:
        assert resolve_route("plan") is TASK_ROUTES[LlmTask.PLAN]

    def test_unknown_task_fails_fast_and_never_falls_back(self) -> None:
        """N-21：未知 task **不许**回退到默认模型 —— 那正是静默降级。"""
        with pytest.raises(LlmUnknownTask) as ei:
            resolve_route("no_such_task")
        assert ei.value.detail["task"] == "no_such_task"
        assert "normalize" in ei.value.detail["known_tasks"]
        assert "不会" in ei.value.message  # 报错文本必须写明"不回退"

    def test_task_names_are_unique_and_snake_case(self) -> None:
        """task 字面量是 W3B/W3C 的**调用契约** —— 大小写混用会让调用方靠猜。"""
        values = [t.value for t in LlmTask]
        assert len(values) == len(set(values))
        for v in values:
            assert v == v.lower() and " " not in v, v


class TestResolveModelName:
    def test_auto_follows_the_route(self) -> None:
        fast_route = TASK_ROUTES[LlmTask.PLAN]
        assert resolve_model_name(fast_route, MODEL_AUTO, _MODEL_NAMES) == "test-flash"
        strong_route = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX]
        assert resolve_model_name(strong_route, MODEL_AUTO, _MODEL_NAMES) == "test-pro"

    def test_explicit_model_overrides_the_route(self) -> None:
        """逃生门：W3B 可能需要强制走快档（例如已知语义包很小）。"""
        route = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX]
        assert resolve_model_name(route, "test-flash", _MODEL_NAMES) == "test-flash"

    def test_unknown_model_fails_fast(self) -> None:
        """不做"猜最近的模型名" —— 猜错就是静默换模型，成本与质量都无声漂移。"""
        with pytest.raises(LlmUnknownModel) as ei:
            resolve_model_name(TASK_ROUTES[LlmTask.PLAN], "gpt-4o", _MODEL_NAMES)
        assert ei.value.detail["model"] == "gpt-4o"
        assert MODEL_AUTO in ei.value.detail["allowed"]

    def test_lookalike_model_name_is_rejected(self) -> None:
        """反向对照：**像**但不等于已登记模型名 → 也必须拒绝（防止子串/前缀匹配的宽松实现）。"""
        with pytest.raises(LlmUnknownModel):
            resolve_model_name(TASK_ROUTES[LlmTask.PLAN], "test-flash-2", _MODEL_NAMES)


class TestDegradeChain:
    """07 §10.2：`v4-pro(思考) → flash(非思考) → 模板 → 拒答`（本函数只表达模型段）。"""

    def test_strong_degrades_to_fast(self) -> None:
        route = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX]
        assert degrade_target(route, ModelKey.STRONG) is ModelKey.FAST

    def test_fast_has_no_model_target_so_it_goes_to_template(self) -> None:
        """`None` 的语义是"该进模板层了"，不是"降级失败"。"""
        route = TASK_ROUTES[LlmTask.PLAN]
        assert degrade_target(route, ModelKey.FAST) is None


class TestTimeoutAndMaxTokens:
    def test_effective_timeout_uses_the_task_budget_when_present(self) -> None:
        assert effective_timeout_s(TASK_ROUTES[LlmTask.GEN_SQL], ModelKey.FAST) == 1.3

    def test_None_degrades_to_the_model_hard_limit(self) -> None:
        """07 无任务级预算 → 退化为 §10.2 的模型级上限（并在 DELIVERY 具名登记）。"""
        assert effective_timeout_s(
            TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX], ModelKey.STRONG
        ) == MODEL_HARD_TIMEOUT_S[ModelKey.STRONG]
        assert effective_timeout_s(TASK_ROUTES[LlmTask.REPAIR], ModelKey.FAST) == (
            MODEL_HARD_TIMEOUT_S[ModelKey.FAST]
        )

    def test_thinking_route_gets_reasoning_headroom(self) -> None:
        """🔴 实测：思考档不预留余量 → `max_tokens` 被 reasoning 吃光 → `content=''`（HTTP 200）。"""
        route = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX]
        assert max_tokens_for(route) == route.output_tokens_hint + THINKING_HEADROOM_TOKENS

    def test_non_thinking_routes_get_no_headroom(self) -> None:
        """反向对照：非思考档不该白白多花 2048 token 的上限（那是成本口径污染）。"""
        for task, route in TASK_ROUTES.items():
            if route.thinking:
                continue
            assert max_tokens_for(route) == route.output_tokens_hint, task.value

    def test_headroom_is_strictly_positive(self) -> None:
        """余量必须 > 0，否则上面那条"留余量"的断言可以被 `+0` 满足。"""
        assert THINKING_HEADROOM_TOKENS > 0

    def test_strong_model_has_the_longer_hard_limit(self) -> None:
        assert MODEL_HARD_TIMEOUT_S[ModelKey.STRONG] > MODEL_HARD_TIMEOUT_S[ModelKey.FAST]
