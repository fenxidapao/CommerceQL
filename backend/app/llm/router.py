"""模型路由决策 —— `task` → (模型, 思考位, 超时, 输出规格)，**集中一处**。

归属窗口：W3A｜落点由 07 §3.2 指定，**表内容来源 = PRD §12.1/§12.2 + 07 §16.1/§16.2/§6.8.2**。

## 为什么这张表必须在代码里、且必须只有一份（Q4 裁定）

端口签名是 `call(task, payload, model)` —— 模型**同时**由"路由表"和"调用方参数"给出。
如果路由逻辑散在调用方（W3B/W3C 各自 if-else），那么 PRD §12.2 那张表就会有 3 份实现，
而"某次调用实际用了哪个模型"将无法从代码回答 —— N-19 要求 `prompt_version` 必录，
但显然 `model` 也必须可归因（否则 §15.3 的成本指标无法按模型分解）。

**代价（写明，不隐瞒）**：改路由需重发版。P0 可接受 —— 它换来的是"路由可审计"。
若将来要热改，正确做法是把它挪进 `config`（归 W0）而不是散进调用方。

## 🔴 `model` 参数的语义（端口签名与路由表张力的收口）

`LLMPort.call(task, payload, model)` 的 `model` 是**必填**位置参数，但 PRD §12.2 又规定
"任务决定模型"。本实现把它定义为：

    model="auto"                → 按本文件的路由表决定（**默认、推荐**）
    model=<config 里的模型名>    → 显式**覆盖**路由表（逃生门），会被记录为 override

其他取值 → `LlmUnknownModel`（fail-fast）。**不做"猜最近的模型名"这种事情** ——
那正是 N-21 禁止的静默降级。

## 超时：**有 07 预算的用预算，没有的**绝不发明数字

07 §16.1 给了 7 个阶段预算（`normalize`/`intent`/精筛/`plan`/`gen_sql`/`present`），
§16.2 给了 `normalize+intent` **合并档** 1.2s，§6.8.2 给了 L4 打分器"单次约 0.3–0.8s"。
其余三项（`gen_sql_complex` / `repair` / 下游的 `l4_score` 之外）——

> `gen_sql_complex`（L3+ 走 `deepseek-v4-pro` **思考**）与 `repair`（有界纠错）
> **在 07 里没有任务级延迟预算**。

按 U-22 的根因纪律（"**推导不出来的值必须显式标为经验值并登记补齐请求，不得装成有依据**"），
本文件对这两个 task 的做法是：**`timeout_s=None` → 退化为 07 §10.2 的模型级上限**
（flash 15s / pro 45s），并在 `DELIVERY.md` 具名登记"07 缺这两个任务级预算"。

⚠️ 顺带暴露一个**真实矛盾**（已登记，非本窗口可裁）：07 §16.1 给 `gen_sql` 的预算是
**1.3s**，而 PRD §12.2 要求 L3+ 用 `deepseek-v4-pro` **思考** —— 实测（2026-09-17）
pro 一次最简调用耗时 **1.42s**，即"按 1.3s 预算跑 pro 思考"在物理上不可能。
两者不能同时成立，必须由架构窗口裁决（要么给 pro 档独立预算，要么承认 L3+ 必然超 P95）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.llm.errors import LlmUnknownModel, LlmUnknownTask

__all__ = [
    "LlmTask",
    "ModelKey",
    "TaskRoute",
    "TASK_ROUTES",
    "MODEL_AUTO",
    "THINKING_HEADROOM_TOKENS",
    "MODEL_HARD_TIMEOUT_S",
    "resolve_route",
    "resolve_model_name",
    "degrade_target",
    "effective_timeout_s",
    "max_tokens_for",
]


class ModelKey(StrEnum):
    """路由表里的**档位**，不是模型 ID —— ID 由 config 提供（`LLM_MODEL_FAST/STRONG`）。"""

    FAST = "fast"
    STRONG = "strong"


class LlmTask(StrEnum):
    """LLM 调用点的取值集（**10 个**）。

    来源 = **PRD §12.2 表**（7 行）+ **PRD §6.3.1 / §12.9 L4 打分器** +
    **07 §16.1 压缩手段 1 的合并档** + **07 §16.1 第 4 行"精筛"单列**。

    ⚠️ 字面量取值与 07 的**节点名**对齐（`normalize` / `intent` / `plan` / `gen_sql` /
    `present`），合并档与精排用 `_` 连接。**这是 W3B/W3C 的调用契约**，
    改动即破坏契约 —— 新增/改名必须同步 `reports/w3a/RELAY.md §给 W3B/W3C`。
    """

    #: 问题归一化改写（07 §16.1 行 2；PRD §12.2 第 2 行）
    NORMALIZE = "normalize"
    #: 意图分类（07 §16.1 行 3；PRD §12.2 第 1 行）
    INTENT = "intent"
    #: ★ **合并档**：07 §16.1 压缩手段 1「合并 normalize + intent 为一次 LLM 调用」。
    #: 预算取 §16.2 的 1.2s（首字节预算里给的就是这两个合并后的值）。
    NORMALIZE_INTENT = "normalize_intent"
    #: 候选筛选·精筛（07 §16.1 行 4 里的"精筛 0.8s"；PRD §12.2 第 3 行）
    RERANK = "rerank"
    #: 查询计划（07 §16.1 行 5）
    PLAN = "plan"
    #: SQL 生成 L0–L2（07 §16.1 行 7；PRD §12.2 第 4 行）
    GEN_SQL = "gen_sql"
    #: SQL 生成 L3+ 复杂（PRD §12.2 第 5 行；**唯一走"思考"的档**）
    GEN_SQL_COMPLEX = "gen_sql_complex"
    #: 有界纠错（PRD §12.2 第 6 行）
    REPAIR = "repair"
    #: 图表 spec + 结论（07 §16.1 行 13）
    PRESENT = "present"
    #: 字段绑定 L4 打分器（PRD §6.3.1 / §12.9 方案 C）
    L4_SCORE = "l4_score"


#: `model="auto"` —— 交给路由表决定（默认值）。
MODEL_AUTO: Final[str] = "auto"

#: 🔴 **经验值**（登记于 `DELIVERY.md`）：思考任务要给 `reasoning_tokens` 留的余量。
#:
#: 实测依据（2026-09-17，真机）：一个最简问句在思考模式下耗掉 32 个 completion token，
#: 而 `max_tokens=32` 的情形下 **32 个全进 reasoning、`content` 为空字符串、
#: HTTP 状态仍是 200**。若不预留，思考档会稳定返回空内容。
#: 真实 SQL 生成所需余量**必须由阶段 3 的实测标定**，当前值只是防"空 content"的下限。
THINKING_HEADROOM_TOKENS: Final[int] = 2048

#: 07 §10.2 的**模型级**硬上限（传输层超时）。任务级预算比它短时以任务级为准。
MODEL_HARD_TIMEOUT_S: Final[dict[ModelKey, float]] = {
    ModelKey.FAST: 15.0,
    ModelKey.STRONG: 45.0,
}


@dataclass(frozen=True, slots=True)
class TaskRoute:
    """单个 task 的完整路由决策。**不可变** —— 路由表是要被审计的，不是运行时状态。"""

    task: LlmTask
    model_key: ModelKey
    #: 是否开思考（PRD §12.2 的"模式"列）
    thinking: bool
    #: 任务级软超时（秒）。`None` = **07 未给该任务级预算** → 退化到模型级上限。
    timeout_s: float | None
    #: 采样温度。L4 打分器由 PRD §12.9 约束 1 明确要求 0；其余取 0.0 保评测可复现。
    temperature: float
    #: 输出 token 提示（**经验值**）：驱动 `max_tokens` 与 pre-flight 成本估算。
    output_tokens_hint: int
    #: 是否要求 JSON Output（07 §10.3：本项目"一律 JSON Output"，无例外）。
    json_output: bool
    #: 07 里给该任务的延迟预算出处（人读的追溯标签，不参与逻辑）。
    budget_source: str


#: 🔴 **路由表唯一真相**。改表前先读 PRD §12.2 与 07 §16.1/§16.2/§6.8.2。
#:
#: `output_tokens_hint` 与 `temperature` 是**经验值**（07/PRD 未逐项给值）：
#: 量级取自 PRD §12.3 的"一次查询输出 ≈ 2.4K token"按调用点拆分；温度统一 0.0。
#: 两者都登记在 `DELIVERY.md` 的"经验值清单"里，必须由阶段 3 实测替换。
TASK_ROUTES: Final[dict[LlmTask, TaskRoute]] = {
    LlmTask.NORMALIZE: TaskRoute(
        task=LlmTask.NORMALIZE, model_key=ModelKey.FAST, thinking=False,
        timeout_s=0.6, temperature=0.0, output_tokens_hint=256, json_output=True,
        budget_source="07 §16.1 行2（normalize 0.6s）",
    ),
    LlmTask.INTENT: TaskRoute(
        task=LlmTask.INTENT, model_key=ModelKey.FAST, thinking=False,
        timeout_s=0.6, temperature=0.0, output_tokens_hint=128, json_output=True,
        budget_source="07 §16.1 行3（intent 0.6s）",
    ),
    LlmTask.NORMALIZE_INTENT: TaskRoute(
        task=LlmTask.NORMALIZE_INTENT, model_key=ModelKey.FAST, thinking=False,
        timeout_s=1.2, temperature=0.0, output_tokens_hint=384, json_output=True,
        budget_source="07 §16.2（normalize+intent 合并 1.2s ＝ §16.1 压缩手段 1）",
    ),
    LlmTask.RERANK: TaskRoute(
        task=LlmTask.RERANK, model_key=ModelKey.FAST, thinking=False,
        timeout_s=0.8, temperature=0.0, output_tokens_hint=512, json_output=True,
        budget_source="07 §16.1 行4（精筛 0.8s）；PRD §12.2 第3行",
    ),
    LlmTask.PLAN: TaskRoute(
        task=LlmTask.PLAN, model_key=ModelKey.FAST, thinking=False,
        timeout_s=1.0, temperature=0.0, output_tokens_hint=600, json_output=True,
        budget_source="07 §16.1 行5（plan 1.0s）",
    ),
    LlmTask.GEN_SQL: TaskRoute(
        task=LlmTask.GEN_SQL, model_key=ModelKey.FAST, thinking=False,
        timeout_s=1.3, temperature=0.0, output_tokens_hint=800, json_output=True,
        budget_source="07 §16.1 行7（gen_sql 1.3s）；PRD §12.2 第4行（L0–L2 flash 非思考）",
    ),
    LlmTask.GEN_SQL_COMPLEX: TaskRoute(
        task=LlmTask.GEN_SQL_COMPLEX, model_key=ModelKey.STRONG, thinking=True,
        timeout_s=None, temperature=0.0, output_tokens_hint=1200, json_output=True,
        budget_source="PRD §12.2 第5行（L3+ v4-pro 思考）★ 07 **无**任务级预算 → 退化模型级 45s",
    ),
    LlmTask.REPAIR: TaskRoute(
        task=LlmTask.REPAIR, model_key=ModelKey.FAST, thinking=False,
        timeout_s=None, temperature=0.0, output_tokens_hint=800, json_output=True,
        budget_source="PRD §12.2 第6行 ★ 07 **无**任务级预算 → 退化模型级 15s",
    ),
    LlmTask.PRESENT: TaskRoute(
        task=LlmTask.PRESENT, model_key=ModelKey.FAST, thinking=False,
        timeout_s=1.5, temperature=0.0, output_tokens_hint=800, json_output=True,
        budget_source="07 §16.1 行13（present 1.5s）",
    ),
    LlmTask.L4_SCORE: TaskRoute(
        task=LlmTask.L4_SCORE, model_key=ModelKey.FAST, thinking=False,
        timeout_s=0.8, temperature=0.0, output_tokens_hint=512, json_output=True,
        budget_source="07 §6.8.2 方案C（'单次调用约增加 0.3–0.8s' 的上界）；PRD §12.9 约束1（温度=0）",
    ),
}


def resolve_route(task: str) -> TaskRoute:
    """`task` → `TaskRoute`。**未知 task 一律 fail-fast**（N-21：不猜、不静默降级）。"""
    try:
        key = LlmTask(task)
    except ValueError:
        raise LlmUnknownTask(
            "未知的 LLM task —— 路由表里没有它，**不会**回退到默认模型（那样等于静默降级）",
            detail={"task": task, "known_tasks": sorted(t.value for t in LlmTask)},
        ) from None
    return TASK_ROUTES[key]


def resolve_model_name(route: TaskRoute, model: str, model_names: dict[ModelKey, str]) -> str:
    """把 `call(..., model=...)` 的取值解析成真实模型 ID。

    `"auto"` → 按 `route.model_key` 取；显式模型名 → 覆盖（记录 override）；
    其他 → `LlmUnknownModel`。
    """
    if model == MODEL_AUTO:
        return model_names[route.model_key]
    if model in set(model_names.values()):
        # 覆盖是显式逃生门：允许（W3B 可能需要强制走快档），但必须能被审计到。
        return model
    raise LlmUnknownModel(
        "model 取值非法 —— 只接受 'auto' 或 config 里登记的模型名",
        detail={"model": model, "allowed": [MODEL_AUTO, *sorted(model_names.values())]},
    )


def degrade_target(route: TaskRoute, current_model_key: ModelKey) -> ModelKey | None:
    """降级链的下一档：`strong → fast → None`（`None` 表示"该进模板层了"）。

    07 §10.2 的链：`v4-pro（思考） → flash（非思考） → 模板匹配 → 拒答`。
    模板与拒答不是模型档，故本函数只表达模型段。
    """
    if current_model_key is ModelKey.STRONG:
        return ModelKey.FAST
    return None


def effective_timeout_s(route: TaskRoute, model_key: ModelKey) -> float:
    """任务级软超时；`None` 时退化到模型级硬上限（见模块 docstring 的 U-22 说明）。"""
    if route.timeout_s is not None:
        return route.timeout_s
    return MODEL_HARD_TIMEOUT_S[model_key]


def max_tokens_for(route: TaskRoute) -> int:
    """`max_tokens` = 输出提示 + （思考档的）reasoning 余量。

    🔴 不加余量会稳定触发"`content` 为空"（实测，见 `THINKING_HEADROOM_TOKENS`）。
    """
    return route.output_tokens_hint + (THINKING_HEADROOM_TOKENS if route.thinking else 0)
