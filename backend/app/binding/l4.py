"""L4 打分生产者：把「问句 + 候选」经**注入的 `LLMPort`** 交给 LLM 打分器，拿回可校准的分数。

归属窗口：W3C｜依据：PRD §12.9（方案 C + 5 条硬约束）、07 §6.8.2、N-27、W3A RELAY §给 W3B/W3C。

## 本模块只说一件事：**怎么问**

四层判定的「怎么判」在 `four_layer.py`；本模块负责**产出**那一层吃的 `ScoreOutcome`。
两者之间**只通过 `ScoreOutcome` 通信** —— 判定层不知道有 LLM，生产层不知道有 τ。

## 为什么是"经端口"而不是"直接调网关"

N-01 / `.importlinter` R-DEP-2 把"`binding` 禁 import `app.llm`"做成了**结构约束**：
本模块**不 import** 任何 `app.llm` 符号，`port` 由装配根（W4 的 lifespan）从外部传进来。
连带的三条后果（都写进单测）：

1. **task 名与 model 名是字面量**（`"l4_score"` / `"auto"`）。字面量即契约（W3A RELAY §2），
   但"两边各写一份字面量"是靠**测试交叉校验**兜住的：`test_binding_l4.py` 断言
   `L4_TASK == LlmTask.L4_SCORE.value`（`tests/` 不受 R-DEP-2 约束）。
2. **payload 的键集是白名单**（§10.5）。本模块只发**七个键**，且每个都能在 W3A 的
   `ALLOWED_WIRE_KEYS` / `EgressPayload` 里找到 —— 多一个键网关会**抛**（严格模式，不静默丢弃）。
3. **出站 `output_schema` 从 `L4_SCORE_ITEM_KEYS` 派生**，不手写第二份键名清单（见该常量的注释）。

## 🔴 上游故障**不在这里**被转成 `ambiguous`（本窗口的裁定，登记 RELAY §D6）

PRD §12.9 约束④ 把 fail-safe 的触发**逐一列举**了两种：**解析失败** / **分差落在 τ 邻域**。
"打分器不可用"（超时、5xx、限流、拒答）**不在其列** —— 而这两类事的性质不同：

| | 是什么 | 正确响应 |
|---|---|---|
| 模型回了、但内容不可用（非法 JSON / 越界 / 缺候选） | **本次查询的结论**："这个歧义我判不了" | `ScoreOutcome(failed=True)` → 澄清 |
| 调用本身没成功（`LlmRefused` / `LlmUpstreamError` / `LlmConcurrencyExceeded` / 出站违规） | **系统故障或安全事件** | **原样上抛**，由 W4 决定终态 |

把第二类包装成"澄清"= 用产品结论掩盖系统故障 —— 那正是 W3A RELAY §4 与本项目红线
（反对 `200 OK` 隐瞒降级）禁止的动作。故本模块**不写任何 `except LlmError`**：
`LlmRefused` 不需要特殊处理就能原样上抛（这是"不捕获"相对"捕获后重新抛出"的额外好处 ——
不存在漏写 `raise` 的可能）。

⚠️ 代价（如实登记）：L4 全不可用时，本该澄清的问句会变成 error。**缓解在 W4**：
L4 是兜底层，且 `binding_layer` 分布可观测（N-27 约束⑤）—— 若 L4 大面积不可用，
它在指标上是可见的，不会静默。若架构裁定改为"降级成澄清"，改动点是本模块的
`await port.call(...)` 一处（加 `except LlmError` → `_fail(...)`），**裁定后改 3 行**。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from app.binding.scores import L4_SCORE_ITEM_KEYS, ScoreOutcome, parse_scores_json
from app.core.contracts import LLMPort

__all__ = [
    "L4_CONSTRAINTS",
    "L4_OUTPUT_SCHEMA",
    "L4_TASK",
    "MODEL_AUTO",
    "build_l4_payload",
    "score_l4",
]

#: LLM 调用点的名字（`LlmTask.L4_SCORE` 的值）。
#: ⚠️ **字面量即契约** —— 不能 `from app.llm.router import LlmTask`（R-DEP-2 会红）。
#: 两边一致性由 `tests/unit/test_binding_l4.py` 交叉断言兜住。
L4_TASK: Final[str] = "l4_score"

#: `model="auto"` = 交给网关的路由表决定（PRD §12.2）。
#: L4 必须走路由表而不是写死模型名：**降级链也在这条路上**（v4-pro → flash），
#: 而实际用了哪个模型由 `LLMResponse.model` 回传 → 进 `RerankScore.model_id` → 供 τ 绑定校验。
MODEL_AUTO: Final[str] = "auto"

#: 出站输出契约（`$output_schema`）。**从 `L4_SCORE_ITEM_KEYS` 派生**，不手写键名清单。
#:
#: ⚠️ 文本里必须出现"JSON"字样：网关用了 `response_format={"type":"json_object"}`，
#: 而实测上游要求整体消息内含 "json" 否则直接 400（W3A `client.build_wire_request` 有断言）。
L4_OUTPUT_SCHEMA: Final[str] = (
    "只输出一个 JSON 对象，形状严格如下（不要额外包裹、不要解释文字）：\n"
    '{"scores": [{"'
    + '": <值>, "'.join(sorted(L4_SCORE_ITEM_KEYS))
    + '": <值>}]}\n'
    "其中：\n"
    '- "candidate_id"：**必须逐字复制**输入里给出的候选资产名（不要改写、不要加编号前缀）；\n'
    '- "score"：0 到 1 之间的**数值**（不是字符串）。越界即整体无效；\n'
    '- "reason"：可选，一句话说明为什么给这个分。\n'
    "必须为**全部**候选各给一条，缺任何一个都会导致本次输出整体无效。"
)

#: 出站附加约束（`$constraints`）。**自产稳定文本** —— 不含时间戳/随机数/租户信息，
#: 否则上游前缀缓存命中率归零（07 §10.3 硬规则 1/3）。
L4_CONSTRAINTS: Final[str] = (
    "1. 你判的是「这个字段**是不是用户要的那个**」，不是「这个名字像不像」。"
    "名字表面相似但语义不同的候选必须给低分。\n"
    "2. 全部候选在**同一次回答内**一起打分 —— 分数之间必须可比较（这是联合打分的要求）。\n"
    "3. **拿不准就给相近的分**：两个候选难分伯仲时给接近的分数，不要强行拉开。"
    "下游会检查分差；分差太小会被判为「无法判定」并触发澄清 —— 这是设计如此，不是失败。\n"
    "4. 不要输出 markdown 代码围栏，不要输出任何 JSON 之外的内容。"
)


# ============================================================================
# 出站载荷：只发六个键，每个都在 W3A 的登记白名单内
# ============================================================================


def build_l4_payload(
    *,
    question: str,
    candidates: Sequence[str],
    semantic_summary: str = "",
    dialect_note: str = "",
    output_schema: str = L4_OUTPUT_SCHEMA,
    constraints: str = L4_CONSTRAINTS,
    bundle_version: str = "",
) -> dict[str, Any]:
    """构造 `l4_score` 的**出站载荷**。

    七个键，逐一说明**为什么是它**（剩下的白名单键刻意不发，见下）：

    | 键 | 内容 | 为什么 |
    |---|---|---|
    | `raw_question` | 归一化后的问题 | 唯一允许出站的用户输入；是打分器的「问句」侧 |
    | `candidates` | 候选资产名列表 | 是打分器的「候选」侧。**联合打分**要求两侧同时到场 |
    | `semantic_summary` | 语义包摘要 | 同名异义/粒度差异/默认口径的**唯一**来源（本地取不到，须由调用方经端口取好再传） |
    | `dialect_note` | 方言说明 | `l4_score_v1` 资产**引用了它**（`$dialect_note`）→ 不发会留下未替换的占位符。填的是自产稳定文本 |
    | `output_schema` | 输出契约 | 结构化输出（约束①） |
    | `constraints` | 附加约束 | 把"拿不准给相近分"这条**明确说出来**，否则模型会倾向于强行排序 |
    | `bundle_version` | 语义包版本 | 前缀按它冻结；也是分数可追溯的上下文 |

    **刻意不发**：`few_shots`（L4 是打分不是生成，示例会污染分数尺度）、
    `history_questions`（多轮上下文对"这个字段是不是我要的"无信息量，且扩大出站面）、
    `error_digest`（L4 不参与纠错）、`user_scope`（只服务 HTTP `user` 参数，与打分无关）。

    ⚠️ `dialect_note` 的**默认值是空串**，此时渲染会填进 `（语义包摘要未提供）` 那类占位文案；
    W4 装配时若能从语义包拿到真实方言说明就应传入（`semantic/dialect.md`）。
    这里不发第二个方言默认值：默认文本的唯一真相在 `prompts/loader.py`，在此再写一份必漂。

    ⚠️ **不做长度/条数上限的本地校验**：那些上限（200 条 / 120 字）**唯一真相在网关**
    （`egress_guard`）。在这里再写一遍数字 = 两处真相，改一处必漂。本函数只拦
    "明显不成立"的空输入，其余交给网关的 fail-closed 校验。

    ⚠️ **不发身份**：`user_id` / `tenant_id` / `task_id` 不在白名单内，也不应在此出现。
    计量与日志走 `app.llm.set_call_context`（contextvars，永不出站）—— 那是 W4 的接线动作。
    """
    return {
        "raw_question": question,
        "candidates": list(candidates),
        "semantic_summary": semantic_summary,
        "dialect_note": dialect_note,
        "output_schema": output_schema,
        "constraints": constraints,
        "bundle_version": bundle_version,
    }


# ============================================================================
# 打分：唯一的异步入口
# ============================================================================


async def score_l4(
    *,
    port: LLMPort,
    question: str,
    candidates: Sequence[str],
    semantic_summary: str = "",
    dialect_note: str = "",
    bundle_version: str = "",
    output_schema: str = L4_OUTPUT_SCHEMA,
    constraints: str = L4_CONSTRAINTS,
    model: str = MODEL_AUTO,
) -> ScoreOutcome:
    """调 L4 打分器并解析结果。**四层判定的 L4 唯一异步入口**（另一个入口见下）。

    返回 `ScoreOutcome`：

    - `failed=True` → "本次打分不可用"（空输入 / 非法 JSON / 越界 / 缺候选）→
      判定层按 N-27 约束④ fail-safe 判 `ambiguous`（**产品结论**，不是异常）；
    - `failed=False` → 分数覆盖**全部**候选，可进分差判定。

    🔴 **`LlmRefused` 与其余 `LlmError` 原样上抛**（理由见模块 docstring 的对照表）：
    本函数**没有** `except LlmError` —— 不是漏写，是刻意不留那条路。

    ⚠️ **与 `adopt_l4_candidates` 的分工（D1(a) 双入口）**：本条路是"W4 在 `bind` 节点里
    真的去问模型"；若 L4 分数是**上游注入**的（评测夹具、离线回溯、或 W2B 已算好），
    走 `scores.adopt_l4_candidates` 的**同步**入口进判定 —— 那条路只收显式声明
    `layer is BindingLayer.L4` 的 `CandidateRef`，是"裸 float 混进 L4"的唯一可能入口，
    故它必须窄。两条路的产物**同一个类型**（`ScoreOutcome`），判定层不区分来源。

    🔴 **两条路的校验强度不同，不得混为一谈**：
    本条路拿到的 `model_id` / `prompt_version` 来自 `LLMResponse`（**实际**用的那个），
    所以 τ 绑定校验（N-27 约束②）在这里是**真校验**；而注入路径没有身份字段可读，
    只能取 τ 自身的标识 → 那里的校验**恒通过**（详见 `service._split_candidates` 的对照表）。
    """
    if not question or not question.strip():
        return ScoreOutcome(failed=True, reason="empty_question")
    expected = [cid for cid in candidates if cid]
    if not expected:
        return ScoreOutcome(failed=True, reason="no_candidates")

    payload = build_l4_payload(
        question=question,
        candidates=expected,
        semantic_summary=semantic_summary,
        dialect_note=dialect_note,
        output_schema=output_schema,
        constraints=constraints,
        bundle_version=bundle_version,
    )
    # ⚠️ 这一行是**唯一**的失败策略切换点：若架构裁定"上游故障降级为澄清"，
    #    在这里包 try/except LlmError（先 except LlmRefused: raise）即可，其余代码不动。
    response = await port.call(L4_TASK, payload, model)

    return parse_scores_json(
        response.text,
        expected_ids=expected,
        model_id=response.model,
        prompt_version=response.prompt_version,
    )
