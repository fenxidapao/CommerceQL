"""节点 2 `normalize` —— 时间绝对化 / 黑话别名 / 零代词补全 / 数值单位（07 §5.3 行 2）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、本节点走的是**合并档**（`understand()`），不是单跑 `normalize()`
--------------------------------------------------------------------------
07 §16.1 的手段 1 = "合并 `normalize` + `intent` 为一次调用"，状态栏已标 ✅ 已落地，
实测 2.84s → 1.56s（W3A §12.1）；而 §16.1 的诚实结论是"全串行 + 不合并时不满足 8s P95"。
⇒ P0 默认走 `PlannerEngine.understand()`（W3B 标注为"推荐入口"），本节点一次写满
**组 2 + 组 3**，随后的 `intent` 节点因此变成空操作（见该文件）。

⚠️ 合并**不改变任何判定标准**（§16.1 原文），只是省一次往返与一段重复上下文。
⇒ 单跑路径（`engine.normalize()` + `engine.classify_intent()`）必须仍然可跑 ——
否则 §16.1 DoD① 的"合并省了多少"无从测量。开关 = `GraphDeps.merged_understand`。

--------------------------------------------------------------------------
二、失败转移（§5.3 行 2 与行 3 的交集，逐条落到出口）
--------------------------------------------------------------------------
| 触发 | 本节点动作 | 去向 |
|---|---|---|
| `LlmRefused` | 直接转 `refuse` 终态（**必须先于 `PlannerError` 分流**） | `refuse` |
| 其余 `LlmError`（429/5xx/出站违规…） | `error(default_code)` | `error` |
| `UnderstandUnavailable`（JSON 修复用尽） | `degraded(llm_unavailable, template_only)` + `intent=refuse` | `refuse`（模板层 P0 恒无命中） |

⚠️ **时间不可解析 → 澄清**不在本节：`UnderstandOutcome.time_parse_ok=False` 只是写进 state，
由 `route_after_normalize` 判去向（§5.4 第 1 行）。本节点**不猜时间**（N-26）。

⚠️ **降级方向不对称，必须写清**：`UnderstandUnavailable` 是"模型给不出可用 JSON"，
在本项目里它的产品动作是**模板 → 无命中 → 拒答**（§10.2 最后两行），
故这里先把 `intent` 写成 `refuse` 再设终态 —— 让 state 与终态互相印证
（只设终态而不写 `intent` 的话，审计里"为什么拒答"就只剩一句 reason）。

--------------------------------------------------------------------------
三、两个"要了但给不了"的入参（如实登记，不编）
--------------------------------------------------------------------------
1. **多轮历史**：`understand(ctx, question, history=...)` 收 `history`。🔻 **P0-A-3 已接线**
   （2026-10-16）：`GraphState` 新增组 1 字段 `history_questions`（`state.py:283-289`），
   由 `runner` 从 `sess:plan:{tenant}:{sid}` 播种，本节点读出后传给 `understand/normalize`
   ⇒ 历史问题落进 `$history_block`（`normalize_v1.txt:32` / `normalize_intent_v1.txt:42`）。
   ⚠️ **`gen_sql` 仍拿不到历史文本**：它的资产（`gen_sql_v1.txt` / `gen_sql_complex_v1.txt`）
   **没有** `$history_block` 占位符，而占位符集合由 `tests/unit/test_llm_prompts.py:295-320`
   逐资产钉住 ⇒ 历史对 `gen_sql` 的影响是**间接**的（经"归一化后的问题"），不是直接注入。
2. **`resolved_terms` 的语义包批量命中**：`SemanticBundleRuntime.resolve_terms()` 提供
   O(1) 批量命中，但 `understand()` 内部已经做了时间词与别名解析（`resolve_time` 走
   `semantics`），故本节**不重复**调一次 —— 同一事实算两遍必然漂移。
"""

from __future__ import annotations

import re

from typing import Any

from app.core.enums import ActionTaken, DegradedReason, LatencyKey, Outcome, RefuseReason
from app.graph.nodes._shared import (
    deps_of,
    identity_of,
    llm_error_update,
    node_latency,
    rc,
    terminal_update,
)
from app.graph.state import GraphState
from app.llm.errors import LlmError
from app.planner.errors import PlannerError
from app.planner.payloads import detect_foreign_tenant_code, strip_tenant_self_reference
from app.planner.request_policy import preflight_refusal, raw_preflight_refusal
from app.planner.schemas import IntentKind

__all__ = ["normalize"]


#: 「位于/在 … 的店铺」**定语位**（QA R31bl / W68 派单①）：城市短语是店铺的定语，
#: 城市语义必然唯一落在 shop.city —— 不可能是商品/收货城市歧义。
#: 红线：不得扩成"句中出现城市名就撤销"——C-CITY-03「广州的销售额是多少？」
#: 没有店铺定语位，必须仍走澄清。
_SHOP_LOCATIVE_RE = re.compile(r"(?:位于|在)\s*[^，。？?！!、\s]{2,6}\s*的\s*店铺")

#: 定语位之后的**被测主体**：逐店聚合「商品数 / SKU」口径 ⇒ 被测主体是店铺或商品。
#: H-STR 族「各有多少个商品」与 W60 族「各 SKU …」都落在这一尾缀上。
_SHOP_SUBJECT_RE = re.compile(r"^\s*各\s*(?:有多少个?商品|SKU|商品数)", re.IGNORECASE)

#: 可被结构证据撤销的澄清理由族：
#: - ``*city*``：城市维度歧义（结构证明城市是店铺定语 ⇒ 唯一 shop.city）；
#: - ``product_cnt`` / ``product_count``：商品数口径歧义（下游 bind 有 L3 默认绑定
#:   on_sale_product_cnt 兜底，实测见 r63 M-HIER-03 / M-MET-04）。
#: 时间 / 范围 / 权限类澄清**永不**在此列：没有可证伪的结构证据，不能被措辞覆盖。
#: ⚠️ 实测（r63 匣带 + r68 首次 live）：H-STR 族的 reason_code 表面形式**逐次漂移**——
#: 同一题面出现过 ``ambiguous_metric_product_cnt``（r63/r68 杭蓉汉郑）与
#: ``ambiguous_metric_product_count``（r68 穗宁西沙）两种拼法，还有
#: ``ambiguous_city_dimension``（r68 郑）。守卫必须按族匹配而非单串子串，
#: 否则同一题面一次能降级、下一次不能（W68-1 live 实测 4/8 漏网）。
_DEMOTABLE_REASON_PARTS = ("city", "product_cnt", "product_count")


def _demote_unambiguous_shop_city_clarification(
    update: dict[str, Any], raw_question: str
) -> dict[str, Any]:
    """明确指向店铺城市（结构证据）时，撤销 normalize 的城市/商品数歧义澄清。

    三类题面结构证据（QA R31bl / W68 派单①）：
    - 各城市（按城市分组，W60 原判据）；
    - 在<城市>的店铺各 SKU（W60 原判据）；
    - 「位于/在 <城市> 的店铺」**定语位** + 被测主体是逐店聚合的商品数/SKU
      （W68 新增 —— 覆盖 H-STR-01…08「位于<城市>的店铺各有多少个商品」）。

    C-CITY-01/03/04（城市维度 / 城市名做主语 / 城市口径视角）无定语位，保持澄清；
    时间 / 范围 / 权限类澄清理由不在此函数的撤销范围内，保持原终态。
    """
    if str(update.get("intent") or "") != IntentKind.CLARIFY.value:
        return update
    detail = dict(update.get("intent_detail") or {})
    reason_code = str(detail.get("reason_code") or "")
    lowered = reason_code.casefold()
    if not any(part in lowered for part in _DEMOTABLE_REASON_PARTS):
        return update
    question = raw_question.strip()
    locative = _SHOP_LOCATIVE_RE.search(question)
    structured_evidence = "各城市" in question or (
        locative is not None
        and _SHOP_SUBJECT_RE.match(question[locative.end():]) is not None
    )
    if not structured_evidence:
        return update
    update["intent"] = IntentKind.EXECUTABLE.value
    update["intent_detail"] = {
        **detail,
        "reason_code": "shop_city_unambiguous",
        "normalize_original_reason_code": reason_code,
    }
    return update


async def normalize(state: GraphState) -> dict[str, Any]:
    """归一化（合并档下同时产出意图）→ 07 §5.2 组 2（+ 组 3）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    question = str(state.get("raw_question") or "")
    #: 🔴 **P0-A-3（U-142）｜真实历史载体**：从组 1 的 `history_questions` 取同会话历史问题
    #: （**只问题**，不含 SQL 与结果 —— N-17 / §10.5 ⑥）。此前这里恒传 `()`，
    #: 表现为多轮指代（"它/那个/再看一下"）拿不到上一轮上下文 —— 缺口已登记 U-142。
    history = tuple(state.get("history_questions") or ())

    # 🔴 W59 P0：跨租户范围只依赖可信 identity + 原始问题，必须在任何 LLM 调用之前判死。
    # 这能保证 normalize 超时不会把“应拒”折成 infra error，且不产生任何 token。
    foreign_code = detect_foreign_tenant_code(question, identity.tenant_id)
    if foreign_code is not None:
        update = {
            "intent": IntentKind.REFUSE.value,
            "intent_detail": {
                "reason_code": "unauthorized_scope",
                "refuse_kind": RefuseReason.OUT_OF_SCOPE.value,
                "foreign_tenant_code": foreign_code,
            },
        }
        update.update(
            terminal_update(
                state,
                event="refuse",
                outcome=Outcome.REFUSE,
                reason=RefuseReason.OUT_OF_SCOPE.value,
            )
        )
        return update

    # 🔴 W58：应拒问题（PII/竞品/其它店铺）必须在 LLM 之前判死。
    # 否则上游 normalize 超时会把“系统不回答”错误地变成 infra error。
    semantics = getattr(deps, "semantics", None)
    if semantics is not None:
        early = raw_preflight_refusal(question, semantics)
        if early is not None:
            update = {
                "intent": IntentKind.REFUSE.value,
                "intent_detail": {
                    "reason_code": early.reason_code,
                    "refuse_kind": early.reason.value,
                    "preflight_evidence": early.evidence,
                },
            }
            update.update(
                terminal_update(
                    state,
                    event="refuse",
                    outcome=Outcome.REFUSE,
                    reason=early.reason.value,
                )
            )
            return update

    try:
        with node_latency(LatencyKey.NORMALIZE):
            if deps.merged_understand:
                outcome = await deps.planner.understand(identity, question, history=history)
            else:
                outcome = await deps.planner.normalize(identity, question, history=history)
    except LlmError as exc:
        # 顺序刻意：`LlmRefused` 在 `llm_error_update` 内部最先分流（产品结论 ≠ 故障）。
        return llm_error_update(state, exc, stage="normalize")
    except TimeoutError:
        # W59: TimeoutError from a stub/provider must propagate to the graph-level timeout handling,
        # not be converted into a product refusal. Scope refusal is already handled before this call.
        raise
    except PlannerError as exc:
        # 引擎已把 notes 送进它自己的 sink（→ `RunContext.report_degraded`），此处**不重发**，
        # 只补一条"下一步走模板"的业务降级（网关那一条是"出站跳"，语义不同）。
        context.report_degraded(
            DegradedReason.LLM_UNAVAILABLE,
            ActionTaken.TEMPLATE_ONLY,
            {
                "stage": "normalize",
                "error": type(exc).__name__,
                "attempts": getattr(exc, "attempts", None),
            },
        )
        update: dict[str, Any] = {
            "intent": IntentKind.REFUSE.value,
            "intent_detail": {
                "reason_code": "understand_unavailable",
                # ⚠️ 与终态 reason 同一取值（C-12 的 4 值里没有"理解失败"的槽位，已登记近似）
                "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
            },
        }
        update.update(
            terminal_update(
                state,
                event="refuse",
                outcome=Outcome.REFUSE,
                reason=RefuseReason.NO_DATA_ASSET.value,
            )
        )
        return update

    context.record_usage(outcome.meta.tokens, outcome.meta.cost_cny)
    update: dict[str, Any] = _demote_unambiguous_shop_city_clarification(
        dict(outcome.state_payload()), question
    )
    # 🔴 W58 P0：raw 中出现非本租户代号，但 LLM 把它改写/删掉时，
    # 不得让下游以为这是本租户自指而继续出数。这里做成确定性 fail-closed。
    foreign_code = detect_foreign_tenant_code(
        str(state.get("raw_question") or ""),
        identity.tenant_id,
    )
    if foreign_code is not None:
        update["intent"] = IntentKind.REFUSE.value
        update["intent_detail"] = {
            "reason_code": "unauthorized_scope",
            "refuse_kind": RefuseReason.OUT_OF_SCOPE.value,
            "foreign_tenant_code": foreign_code,
        }
        update.update(
            terminal_update(
                state,
                event="refuse",
                outcome=Outcome.REFUSE,
                reason=RefuseReason.OUT_OF_SCOPE.value,
            )
        )
        return update
    # 🔴 W58：把语义包已能确定的“不回答”问题从 clarify 出口拉回 refuse。
    if semantics is not None:
        policy_refusal = preflight_refusal(
            str(update.get("normalized_question") or question),
            dict(update.get("intent_detail") or {}),
            [str(term) for term in (update.get("unresolved_terms") or ())],
            semantics,
        )
        if policy_refusal is not None:
            update["intent"] = IntentKind.REFUSE.value
            update["intent_detail"] = {
                "reason_code": policy_refusal.reason_code,
                "refuse_kind": policy_refusal.reason.value,
                "preflight_evidence": policy_refusal.evidence,
            }
            update.update(
                terminal_update(
                    state,
                    event="refuse",
                    outcome=Outcome.REFUSE,
                    reason=policy_refusal.reason.value,
                )
            )
            return update
    # 🔴 P0-A-1（2026-10-16）：**确定性**剥掉指向调用者自身租户的自指。
    #   为什么放在这里而不是提示词里：`normalized_question` 的残留**只有**本节点能收口，
    #   而下游 `plan` **刻意不带**那条「范围自指」说明（`payloads.py:136-137`）⇒
    #   残留一个 `T_A` 就足以让 plan 判 blocking、把本可 success 的题变成 `refuse_out`。
    #   实测：同批 5 条里 4 条模型自己剥了、1 条没剥 ⇒ 该路径**依赖 LLM 顺从性**，必须由代码兜住。
    cleaned = strip_tenant_self_reference(
        str(update.get("normalized_question") or ""), identity.tenant_id
    )
    if cleaned != update.get("normalized_question"):
        update["normalized_question"] = cleaned
    return update
