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

## 🔴 延迟预算 ≠ 超时（本模块的语义边界，**2026-09-17 修正**）

这里有两个**必须分开**的概念，它们曾经被本模块混为一谈并造成生产级故障：

| 概念 | 出处 | 性质 | 用途 |
|---|---|---|---|
| **单次调用超时** | 07 §10.2：flash **15s** / v4-pro **45s** | **硬上限**（保护） | 真正的传输 deadline |
| **阶段延迟预算** | 07 §16.1 的 `normalize` 0.6s / `intent` 0.6s / 精筛 0.8s / `plan` 1.0s / `gen_sql` 1.3s / `present` 1.5s；§16.2 合并档 1.2s；§6.8.2 L4 打分 0.3–0.8s | **P95 分配**（目标） | 元数据：衡量 §16.1 一致性、供上层决定是否推占位符 |

**故障复现（真机，双向对照，n=3×5 任务）** —— 把上表第二行当第一行用：

| task | §16.1 预算 | 停用预算后实测延迟中位 | 把预算当硬 deadline |
|---|---|---|---|
| `normalize` | 0.6s | 1.45s | **0/3**（失败耗时 608/606/605ms） |
| `intent` | 0.6s | 1.39s | **0/3**（604/611/602ms） |
| `normalize_intent` | 1.2s | 1.56s | **0/3**（1311/1202/1213ms） |
| `plan` | 1.0s | 1.49s | **0/3**（1004/1003/1003ms） |
| `gen_sql` | 1.3s | 1.60s | **0/3**（1304/1311/1315ms） |

同一进程、同一 payload、同一模型，**唯一变量 = deadline**：0/15 → 15/15。
失败耗时**恰好等于预算值**，即"卡在 deadline 上死"，而非上游不可用。

**为什么这是逻辑错误而非"调大一点"**：P95 是**分位数**，不是上界。拿分位数当硬上限，
即使系统完全健康也必然砍掉约 5% 的调用；而当分配值低于真机中位时，就退化成 100% 失败。
07 §16.2 也写明超预算的处置是"**先推 `stage=intent` 占位**"（降级 UX），**不是失败**。
PRD §12.2 那张路由表**没有超时列** —— 全项目唯一的"每次调用"超时就是 §10.2 的 15s/45s。

**所以本文件的做法**：`TaskRoute.budget_s` 只承载 §16.1 的阶段分配（**可观测元数据**），
真实 deadline 一律由 `hard_timeout_s(model_key)` 给（§10.2）。§16.1 的分配值**只影响埋点**，
不再影响任何一次调用的成败 —— 一致性由 `CallRecord.over_budget` 度量。

⚠️ **仍需架构裁决**（本窗口不越界）：§16.1 的分配值已被真机证伪（实测 1.39–1.60s
vs 分配 0.6–1.3s，全部超），且"超预算→推占位符"的执行责任现落在上层（W4 的 SSE），
不在网关。两条都已写进 `RELAY.md §给架构`。
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
    "hard_timeout_s",
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

#: 思考任务要给 `reasoning_tokens` 留的余量。
#:
#: **已由阶段 3 真机实测标定（2026-09-17）**，不再是估计值：
#:
#: | `max_tokens` | `finish_reason` | content | `reasoning_tokens` | 耗时 |
#: |---|---|---|---|---|
#: | **3248**（旧值 = 1200 + 2048） | `length` ×3 | **空** ×3 | 3248 ×3（全被思考吃光） | 68–80s |
#: | 16384（放宽观察） | `stop` ×3 | ✅ 合法 JSON ×3 | 4900 / 5619 / **6719** | 97–138s |
#:
#: ⇒ 旧余量 2048 **差 3.3 倍**，导致 `gen_sql_complex` 稳定返回空 content。
#: 现值 8192 = 实测上界 6719 向上取到 2 的幂（×1.22 余量）。
#:
#: ⚠️ **证据强度有限**：n=3、单一问句。若后续实测出现更长的思考，本值需再调；
#: 保险机制是 `client` 侧**仍然**检测空 content（`LlmEmptyContent` → 降级），
#: 所以偏小不会产出垃圾答案，只会降级 —— 但降级也是失败，别把余量当可以省的东西。
#:
#: ⚠️ **改了它并不能让 `gen_sql_complex` 变可用**：真实 L3+ 调用耗时 **97–138s**，
#: 远超 07 §10.2 的 pro 上限 **45s** ⇒ 仍会在传输层被掐。见 `DELIVERY.md §13`。
THINKING_HEADROOM_TOKENS: Final[int] = 8192

#: 07 §10.2 的**单次调用超时**（传输层 deadline）—— **全项目唯一的硬上限**。
#:
#: ⚠️ 这是 07 里唯一以"**单次调用**"为口径给出的超时。§16.1 的 0.6/1.0/1.3s 是**端到端
#: P95 的阶段分配**，不是调用超时（见模块 docstring 的故障实录）—— 二者不得互相顶替。
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
    #: 07 §16.1 给该阶段的**延迟预算**（端到端 P95 的分配份额）。`None` = 07 未给该阶段分配。
    #:
    #: 🔴 **它不参与任何超时判定** —— 只是可观测元数据（驱动 `CallRecord.over_budget`）。
    #: 真正的 deadline 一律取 `hard_timeout_s()`（§10.2）。把本字段当 deadline 用会让
    #: 所有分配值低于真机延迟的任务 100% 失败（实测记录见模块 docstring）。
    budget_s: float | None
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
        budget_s=0.6, temperature=0.0, output_tokens_hint=256, json_output=True,
        budget_source="07 §16.1 行2（normalize 0.6s）",
    ),
    LlmTask.INTENT: TaskRoute(
        task=LlmTask.INTENT, model_key=ModelKey.FAST, thinking=False,
        budget_s=0.6, temperature=0.0, output_tokens_hint=128, json_output=True,
        budget_source="07 §16.1 行3（intent 0.6s）",
    ),
    LlmTask.NORMALIZE_INTENT: TaskRoute(
        task=LlmTask.NORMALIZE_INTENT, model_key=ModelKey.FAST, thinking=False,
        budget_s=1.2, temperature=0.0, output_tokens_hint=384, json_output=True,
        budget_source="07 §16.2（normalize+intent 合并 1.2s ＝ §16.1 压缩手段 1）",
    ),
    LlmTask.RERANK: TaskRoute(
        task=LlmTask.RERANK, model_key=ModelKey.FAST, thinking=False,
        budget_s=0.8, temperature=0.0, output_tokens_hint=512, json_output=True,
        budget_source="07 §16.1 行4（精筛 0.8s）；PRD §12.2 第3行",
    ),
    LlmTask.PLAN: TaskRoute(
        task=LlmTask.PLAN, model_key=ModelKey.FAST, thinking=False,
        budget_s=1.0, temperature=0.0, output_tokens_hint=600, json_output=True,
        budget_source="07 §16.1 行5（plan 1.0s）",
    ),
    LlmTask.GEN_SQL: TaskRoute(
        task=LlmTask.GEN_SQL, model_key=ModelKey.FAST, thinking=False,
        budget_s=1.3, temperature=0.0, output_tokens_hint=800, json_output=True,
        budget_source="07 §16.1 行7（gen_sql 1.3s）；PRD §12.2 第4行（L0–L2 flash 非思考）",
    ),
    LlmTask.GEN_SQL_COMPLEX: TaskRoute(
        task=LlmTask.GEN_SQL_COMPLEX, model_key=ModelKey.STRONG, thinking=True,
        #: 1200 → 1536（2026-09-17 实测标定）：真机 content 实测 545–1223 token，
        #: 即**原值 1200 低于实测需求**（那一次 1223 > 1200），已验证合法 JSON 输出。
        budget_s=None, temperature=0.0, output_tokens_hint=1536, json_output=True,
        budget_source="PRD §12.2 第5行（L3+ v4-pro 思考）★ 07 §16.1 **无**该阶段分配（已在 DELIVERY 登记）",
    ),
    LlmTask.REPAIR: TaskRoute(
        task=LlmTask.REPAIR, model_key=ModelKey.FAST, thinking=False,
        budget_s=None, temperature=0.0, output_tokens_hint=800, json_output=True,
        budget_source="PRD §12.2 第6行 ★ 07 §16.1 **无**该阶段分配（已在 DELIVERY 登记）",
    ),
    LlmTask.PRESENT: TaskRoute(
        task=LlmTask.PRESENT, model_key=ModelKey.FAST, thinking=False,
        budget_s=1.5, temperature=0.0, output_tokens_hint=800, json_output=True,
        budget_source="07 §16.1 行13（present 1.5s）",
    ),
    LlmTask.L4_SCORE: TaskRoute(
        task=LlmTask.L4_SCORE, model_key=ModelKey.FAST, thinking=False,
        budget_s=0.8, temperature=0.0, output_tokens_hint=512, json_output=True,
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


def hard_timeout_s(model_key: ModelKey) -> float:
    """单次调用的传输 deadline —— **只按模型档取**（07 §10.2：flash 15s / pro 45s）。

    🔴 **刻意不看 task**：stage 延迟预算（`TaskRoute.budget_s`）是 P95 目标而非超时上限。
    曾把它接进来当 deadline，导致"真机延迟 > 分配值"的任务 100% 失败
    （实测 0/15 → 15/15，见模块 docstring 的故障实录）。改回按 task 取 = 重新引入该缺陷。
    """
    return MODEL_HARD_TIMEOUT_S[model_key]


def max_tokens_for(route: TaskRoute) -> int:
    """`max_tokens` = 输出提示 + （思考档的）reasoning 余量。

    🔴 不加余量会稳定触发"`content` 为空"（实测，见 `THINKING_HEADROOM_TOKENS`）。
    """
    return route.output_tokens_hint + (THINKING_HEADROOM_TOKENS if route.thinking else 0)
