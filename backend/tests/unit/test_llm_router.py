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
    TaskRoute,
    degrade_target,
    hard_timeout_s,
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


def _strong_thinking_route() -> TaskRoute:
    """U-67 后路由表里**不再有** STRONG/思考条目 —— 需要"高档"语义的测试用这个合成档。

    它**不是**对路由表现状的断言对象，而是降级链 / 模型覆盖 / 思考余量这几个**机制**的
    载具（07 §10.2 的降级链 `pro → flash → 模板` 仍是契约；P1 方向 C 重启 pro 时，
    真实条目就会长这样 —— U-67 ②：45s 与 max_tokens 标定保留）。
    """
    return TaskRoute(
        task=LlmTask.GEN_SQL_COMPLEX, model_key=ModelKey.STRONG, thinking=True,
        budget_s=None, temperature=0.0, output_tokens_hint=1536, json_output=True,
        budget_source="测试合成档（U-67 P1 前置形态，**非**路由表现状）",
    )


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
            route.budget_s = 999  # type: ignore[misc]


class TestUpstreamValuesAreCopiedVerbatim:
    """表内容 = PRD §12.2 + 07 §16.1/§16.2/§6.8.2 的**逐格照抄**。"""

    #: 07 §16.1/§16.2/§6.8.2 给的**阶段延迟预算**（秒，端到端 P95 的分配份额）。
    #: 🔴 它是**目标**不是上限 —— 每一格都低于真机实测延迟（1.39–1.60s），
    #: 所以它绝不能当超时用（见 `TestTimeoutIsTheModelTierNotTheBudget`）。
    _DOCUMENTED_BUDGETS: ClassVar[dict[LlmTask, float]] = {
        LlmTask.NORMALIZE: 0.6,          # §16.1 行2
        LlmTask.INTENT: 0.6,             # §16.1 行3
        LlmTask.NORMALIZE_INTENT: 1.2,   # §16.2 合并档
        LlmTask.RERANK: 0.8,             # §16.1 行4「精筛」
        LlmTask.PLAN: 1.0,               # §16.1 行5
        LlmTask.GEN_SQL: 1.3,            # §16.1 行7
        LlmTask.GEN_SQL_COMPLEX: 3.0,    # §16.1 表6' 行（v1.0 U-65 补：**经验值**，首轮评测校准）
        LlmTask.PRESENT: 1.5,            # §16.1 行13
        LlmTask.L4_SCORE: 0.8,           # §6.8.2「0.3–0.8s」的上界
    }

    @pytest.mark.parametrize(("task", "expected"), sorted(_DOCUMENTED_BUDGETS.items()))
    def test_documented_budgets_are_copied(self, task: LlmTask, expected: float) -> None:
        assert TASK_ROUTES[task].budget_s == pytest.approx(expected), task.value

    @pytest.mark.parametrize("task", [LlmTask.REPAIR])
    def test_tasks_without_a_documented_budget_declare_None(self, task: LlmTask) -> None:
        """🔴 **07 在这个 task 上没给阶段预算** —— 唯一合法的表达是 `None`。

        防的是"必须给值但文档没给 ⇒ 实现者发明一个数字"。07 里找不到该任务的
        延迟预算，所以填任何秒数都是**编造**；`None` 让"我们不知道"这件事留在代码里。
        （`gen_sql_complex` 的 3.0s 已由 v1.0 U-65 补进 §16.1 表 6' —— 显式标了"经验值"，
        那是架构的编号裁决，不是实现者发明的。）
        """
        assert TASK_ROUTES[task].budget_s is None, task.value

    def test_no_task_uses_the_strong_model_u67(self) -> None:
        """U-67（07 v1.0 §10.2，方向 B）：L3+ 生效档 = **flash 非思考** ⇒ 表里**没有任何** STRONG。

        实测 pro 在真实 L3+ 上 97–138s > 45s 上限，pro 端到端从未生效（白等 45s → 降级
        flash）—— 裁定把既成事实变成诚实契约。对 PRD §12.2 构成 deviation，**待上游认账**。
        若 P1（方向 C）立项重启 pro，本条与下一条会一起红 —— 那是有意设计：改契约必须
        连测试一起改，不许"顺手把思考位打开"。
        """
        strong = {t for t, r in TASK_ROUTES.items() if r.model_key is ModelKey.STRONG}
        assert strong == set()

    def test_no_task_thinks_u67(self) -> None:
        """U-67 的另一半：生效档 = flash **非思考** ⇒ 表里**没有任何**思考位。

        ⚠️ 实测（2026-09-17）思考会吃掉 `max_tokens` 并让 `content` 变空（HTTP 200）——
        思考位一旦被顺手打开，症状是"稳定空答案"，不是"慢一点"。标定余量仍保留
        （`THINKING_HEADROOM_TOKENS`，P1 重启 pro 的前置），但路由表不再使用它。
        """
        thinking = {t for t, r in TASK_ROUTES.items() if r.thinking}
        assert thinking == set()

    def test_l3_effective_tier_is_flash_non_thinking(self) -> None:
        """U-67 的**正向**断言（防"两条集合断言被同时删掉"的空转）：L3+ 明确 = FAST + 非思考。"""
        route = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX]
        assert route.model_key is ModelKey.FAST
        assert route.thinking is False
        assert route.budget_s == pytest.approx(3.0)  # U-65 经验值

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
        strong_route = _strong_thinking_route()
        assert resolve_model_name(strong_route, MODEL_AUTO, _MODEL_NAMES) == "test-pro"

    def test_explicit_model_overrides_the_route(self) -> None:
        """逃生门：调用方可能需要强制换档（例如已知语义包很小）—— 跨档覆盖必须生效。"""
        route = _strong_thinking_route()
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
        assert degrade_target(_strong_thinking_route(), ModelKey.STRONG) is ModelKey.FAST

    def test_fast_has_no_model_target_so_it_goes_to_template(self) -> None:
        """`None` 的语义是"该进模板层了"，不是"降级失败"。"""
        route = TASK_ROUTES[LlmTask.PLAN]
        assert degrade_target(route, ModelKey.FAST) is None


class TestTimeoutIsTheModelTierNotTheBudget:
    """🔴 **本缺陷的守卫**：超时只能取模型档（07 §10.2），绝不能取阶段预算（07 §16.1）。

    故障实录（2026-09-17，真机双向对照，同进程/同 payload/同模型，唯一变量 = deadline）：
    把 §16.1 的 0.6/0.6/1.2/1.0/1.3s 当硬 deadline → **0/15 全部 LlmRefused**，
    失败耗时恰好等于各预算值；换成模型档上限 → **15/15 成功**（真机延迟 1.39–1.60s）。
    根因：P95 是**分位数**不是上界，拿它当硬上限必然砍掉尾部；当分配值低于真机中位时就是 100%。
    """

    def test_hard_timeout_follows_the_model_tier(self) -> None:
        assert hard_timeout_s(ModelKey.FAST) == MODEL_HARD_TIMEOUT_S[ModelKey.FAST]
        assert hard_timeout_s(ModelKey.STRONG) == MODEL_HARD_TIMEOUT_S[ModelKey.STRONG]

    def test_every_task_gets_a_model_tier_timeout(self) -> None:
        """**逐任务**过一遍：不允许任何 task 拿到"自己的预算值"当超时。

        只断言一两个 task 会漏掉整张表 —— 这条必须遍历 `TASK_ROUTES`。
        """
        for task, route in TASK_ROUTES.items():
            assert hard_timeout_s(route.model_key) == MODEL_HARD_TIMEOUT_S[route.model_key], (
                task.value
            )

    def test_stage_budget_is_never_equal_to_the_timeout(self) -> None:
        """反向对照：每个**有**阶段预算的 task，它的预算值都不得等于其超时值。

        若有人把 `hard_timeout_s` 改回按 task 取，这条会立刻变红 —— 而上面那条
        "按模型档取"的断言在"预算恰好等于模型上限"时可能巧合通过。
        """
        checked = 0
        for task, route in TASK_ROUTES.items():
            if route.budget_s is None:
                continue
            checked += 1
            assert route.budget_s != hard_timeout_s(route.model_key), task.value
        assert checked == 9, f"应检查 9 个有阶段预算的 task（8 个原 §16.1 + U-65 的 3.0s），实际 {checked} 个"

    #: 2026-09-17 真机实测的延迟中位（秒）—— **只含量过的 task**。
    #: 未实测（`present` / `rerank` / `l4_score`）刻意不在此表里：对没量过的值作延迟断言
    #: 就是编造。它们的预算值仍然登记在 `_DOCUMENTED_BUDGETS`（源自 07），但延迟未知。
    _MEASURED_LATENCY_S: ClassVar[dict[LlmTask, float]] = {
        LlmTask.NORMALIZE: 1.45,
        LlmTask.INTENT: 1.39,
        LlmTask.NORMALIZE_INTENT: 1.56,
        LlmTask.PLAN: 1.49,
        LlmTask.GEN_SQL: 1.60,
    }

    @pytest.mark.parametrize(("task", "measured"), sorted(_MEASURED_LATENCY_S.items()))
    def test_measured_budgets_are_below_the_real_latency(
        self, task: LlmTask, measured: float
    ) -> None:
        """把"预算低于实测"这条**事实**钉住：当超时用必然 100% 失败（本缺陷的成因）。

        ⚠️ 范围诚实：只覆盖 `_MEASURED_LATENCY_S` 里量过的 5 个 task。
        （若将来实测延迟降到预算以下，这条会红 —— 那是好消息，可重新讨论，
        但不能靠改这个数字把事实抹掉。）
        """
        budget = TASK_ROUTES[task].budget_s
        assert budget is not None, task.value
        assert budget < measured, f"{task.value}: 预算 {budget}s 未低于实测 {measured}s"

    def test_thinking_route_gets_reasoning_headroom(self) -> None:
        """🔴 实测：思考档不预留余量 → `max_tokens` 被 reasoning 吃光 → `content=''`（HTTP 200）。

        U-67 后真实路由表无思考档 —— 用合成档钉住**机制**（P1 重启 pro 时真实条目即此形态）。
        """
        route = _strong_thinking_route()
        assert max_tokens_for(route) == route.output_tokens_hint + THINKING_HEADROOM_TOKENS

    def test_non_thinking_routes_get_no_headroom(self) -> None:
        """反向对照：非思考档不该白白多花几千 token 的上限（那是成本口径污染）。"""
        for task, route in TASK_ROUTES.items():
            if route.thinking:
                continue
            assert max_tokens_for(route) == route.output_tokens_hint, task.value

    def test_headroom_is_strictly_positive(self) -> None:
        """余量必须 > 0，否则上面那条"留余量"的断言可以被 `+0` 满足。"""
        assert THINKING_HEADROOM_TOKENS > 0

    def test_strong_model_has_the_longer_hard_limit(self) -> None:
        assert MODEL_HARD_TIMEOUT_S[ModelKey.STRONG] > MODEL_HARD_TIMEOUT_S[ModelKey.FAST]


class TestThinkingBudgetIsCalibratedFromMeasurement:
    """思考档的 `max_tokens` 标定 —— U-67 后路由表**不再使用**思考位，但标定**刻意保留**。

    实测（2026-09-17，真 key，`gen_sql_complex` 真实资产，n=3）：

    | `max_tokens` | `finish_reason` | content | `reasoning_tokens` |
    |---|---|---|---|
    | 3248（旧值） | `length` ×3 | **空** ×3 | 3248 ×3（全被思考吃光） |
    | 16384 | `stop` ×3 | ✅ 合法 JSON ×3 | 4900 / 5619 / **6719** |

    旧余量 2048 差 3.3 倍 ⇒ pro 思考档稳定返回空 content（空 content 又会触发
    降级到 flash，即"用户拿不到 pro 档质量"）。

    U-67（07 v1.0 §10.2）裁定：L3+ 生效档 = flash 非思考（方向 B），但 **"45s 与
    max_tokens 标定保留"（② 明文）** —— 它们是 P1（方向 C：pro 异步生成）重启 pro 的
    前置条件。本组的存在意义就是：**将来有人把思考位打开时，旧标定必须还在、且仍盖住实测**，
    而不是被当成"没人用的死配置"清掉后重新踩一遍空 content。
    """

    #: 实测上界（token）。改这些数字前请先重跑真机标定，别对着文档改代码。
    _MEASURED_MAX_REASONING = 6719
    _MEASURED_MAX_CONTENT = 1223

    def test_headroom_covers_measured_reasoning(self) -> None:
        assert THINKING_HEADROOM_TOKENS >= self._MEASURED_MAX_REASONING, (
            "思考余量低于实测 reasoning 上界 —— 会稳定产出空 content"
        )

    def test_output_hint_covers_measured_content(self) -> None:
        route = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX]
        assert route.output_tokens_hint >= self._MEASURED_MAX_CONTENT, (
            "输出提示低于实测 content 上界 —— 合法 JSON 会被截断"
        )

    def test_if_pro_thinking_is_reenabled_the_budget_still_covers_the_measured_worst_case(
        self,
    ) -> None:
        """P1 前置守卫：**重启 pro 思考时**（条目改回 STRONG+thinking），合成 `max_tokens`
        （hint + 余量）必须盖住"思考 + 内容"的实测最坏总计（9728 > 7672）。

        刻意**不**读 `max_tokens_for(TASK_ROUTES[...])`（那是 flash 非思考，无余量），
        而用"当前 hint + 当前余量"的合成式 —— 表达的就是 U-67 ②"标定保留"这件事。
        """
        route = TASK_ROUTES[LlmTask.GEN_SQL_COMPLEX]
        future_pro_max_tokens = route.output_tokens_hint + THINKING_HEADROOM_TOKENS
        assert future_pro_max_tokens > self._MEASURED_MAX_REASONING + self._MEASURED_MAX_CONTENT

    def test_headroom_is_not_absurdly_large(self) -> None:
        """反向对照：余量也不能无限大 —— 它是**上限**，过大意味着失控的思考不会被截断。

        上界取"实测上界的 4 倍"这种粗口径：本条不是为了精算，而是防"有人把余量
        调成 10 万来让测试变绿"。
        """
        assert THINKING_HEADROOM_TOKENS <= self._MEASURED_MAX_REASONING * 4
