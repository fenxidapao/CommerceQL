"""条件边判定函数 —— **纯函数，全部可单测**（07 §5.4；`docs/08 §3.6` 产出②）。

层号：L4｜归属窗口：W4（`docs/08 §4.1`：`app/graph/**`）。

--------------------------------------------------------------------------
一、为什么条件边必须是纯函数（而不是"在节点里 if/else 掉"）
--------------------------------------------------------------------------
分支写在节点内部时，"两条分支都必须可达"这件事**无法被测试** —— 测试只能跑节点，
跑到哪条分支取决于节点里的判断，而那个判断正是被测对象（自证循环）。
抽成 `state -> 节点名` 的纯函数后，§14.2 A–H 的每一行都能变成"构造一个 state → 断言去向"
的用例，且**不需要真的跑图**（`tests/contract/test_edges_contract.py`）。

--------------------------------------------------------------------------
二、四处与文档不一致 / 文档缺口（**如实登记，不擅自发明语义**）
--------------------------------------------------------------------------
1. **`binding_status` 的取值集**：`graph/state.py` 的注释写 `unique | ambiguous | none`（3 值），
   而唯一取值集来源 `core.enums.BindingState` 是 **4 值**（`resolved_unique` / `resolved_default` /
   `ambiguous` / `unresolved`）。本窗口按 **4 值**实现（07 §4.1 禁令三：取值集只能有一处定义），
   并在交付里登记该注释需订正。4 值形态才能表达两件文档明文要求的事实：
   §14.2 B4（`unresolved` → `refuse`）与 B6（`resolved_default` **无异常事件**、仍成功但必须
   把 `disclosure` 写进 `insight.caveats[]`）—— 3 值形态下 `resolved_default` 与
   `resolved_unique` 无法区分。

2. **`route_after_plan` 的"模板命中则 `gen_sql`"分支在当前实现里不存在**：
   §5.4 伪代码写 `plan is None → degraded → 模板匹配 → 命中则 gen_sql`。但模板层产出的是
   **一段文本**，而 `gen_sql` 需要结构化 `Plan` —— 把文本当 `Plan` 就是发明语义。
   P0 的 `NullTemplateProvider` 恒无命中（`app/llm/__init__.py` 已如实声明），
   故本函数把"`plan` 缺失"一律判为 `refuse_out`。若模板层将来落地，
   它应当产出**真 `Plan`**（或直接产出 SQL 走另一条边），而不该由本函数猜。

3. **`route_after_repair` / `route_after_audit_pre` 在 §5.4 表中缺席**：
   它们的依据分别是 §5.3 第 16 行的"失败转移：→ 重回 `gate1`"与 §5.4 `route_after_mask` 行内的
   "→ `audit_pre` → `present`"。两条都是**已有明文的上游依据**（不是发明），但确实没被 §5.4 单列。
   缺口已登记。

4. **转异步判定当前**不可达**（缺载体，非缺陷）**：§5.4 写 `预估延迟 > async_threshold_ms`，
   但 `GateResult`（`core/contracts.py`，端口已冻结）只有 `estimated_rows` / `estimated_cost`，
   **没有**预估延迟字段 —— 拿 `estimated_rows` 当延迟就是造一个假数字（U-22 红线）。
   ⇒ `_should_go_async()` 在缺载体时**恒返回 `False`**，并在此登记"需 gate3 侧提供预估延迟载体"。
   这是"如实暴露未接线"，不是"静默不实现"（`tests/contract/` 有一条用例专门钉住这个默认行为）。

--------------------------------------------------------------------------
三、`route_terminal` 的"audit"目标（§5.4 表格最后一行）
--------------------------------------------------------------------------
§5.4 写"若 `state.terminal` 已设置 → 直接 `audit` → `END`"，但 §5.3 的 16 节点表里
**没有**一个叫 `audit` 的节点（终态审计由 `audit_pre`（阻断段）与 `audit_supp`（补充段）承担，
二者已在表内）。新增第 17 个主节点会破坏"16 节点"这条对账基线。
⇒ 本实现：`route_terminal` 作为**终态收口**返回 `END`；其"幂等"语义由两条既有机制双保险承担
（§14.3 约束 1 的原话就是"由 `route_terminal` + `events.py` 双保险"）：
`graph/state.py::assert_terminal_is_settable`（写入口拒绝重复设终态）＋
`graph/events.py::EventRecorder.push`（重复终止事件 → 丢弃 + `ui_contract_violation` 告警）。
缺口已登记（是否需要显式 `audit` 节点待架构裁决）。
"""

from __future__ import annotations

from typing import Final

from langgraph.graph import END

from app.core.enums import BindingState, GateDecision, GateNo
from app.exec import REPAIRABLE_CLASSES
from app.graph.nodes import (
    AUDIT_PRE,
    AUDIT_SUPP,
    BIND,
    CLARIFY_OUT,
    ERROR_OUT,
    EXECUTE,
    GATE1_AST,
    GATE2_POLICY,
    GATE3_COST,
    GEN_SQL,
    INTENT,
    LINK,
    MASK,
    PLAN,
    PRESENT,
    REFUSE_OUT,
    REPAIR,
)
from app.graph.state import GraphState
from app.planner.schemas import IntentKind

__all__ = [
    "MAX_REPAIR_ROUNDS",
    "route_after_audit_pre",
    "route_after_bind",
    "route_after_execute",
    "route_after_gate1",
    "route_after_gate2",
    "route_after_gate3",
    "route_after_gen_sql",
    "route_after_intent",
    "route_after_link",
    "route_after_mask",
    "route_after_normalize",
    "route_after_plan",
    "route_after_present",
    "route_after_repair",
    "route_terminal",
    "terminal_target",
]

#: 有界纠错轮次上限（07 §5.3 第 16 行"≤2 轮" / NFR-2.4）。
MAX_REPAIR_ROUNDS: Final[int] = 2

#: 转异步的两个判据键（07 §5.4 `route_after_gate3` 原文用词）。
#:
#: ⚠️ 键名取自 §5.4，**待与附录 A §A.1.1 的 `RunOptions` 对账**（T5 落 `api/dto/` 时钉死）。
#: 这里既不发明第二套名字，也不做"兼容多种拼写"的兜底 —— 兜底会让键名漂移变成静默容忍。
_ASYNC_THRESHOLD_KEY: Final[str] = "async_threshold_ms"
_ASYNC_IF_SLOW_KEY: Final[str] = "async_if_slow"

#: 出口节点名 ← `state.terminal.event`（组 11：`{event, code?, reason?}`）。
#:
#: ⚠️ 为什么按"节点写下的终态"选出口，而不是按"哪一步失败"猜：
#: 同一节点可能有两类去向 —— §14.2 里 gate2 就有 D2（`error(GATE_POLICY_REJECTED)`）
#: 与 D3（`refuse(pii_blocked)`）两条，条件边无法从 `GateResult` 反推是哪一条。
#: 节点把结论写进 `state.terminal`，边按结论选出口 —— 判断只有一处。
_EXIT_BY_EVENT: Final[dict[str, str]] = {
    "clarify": CLARIFY_OUT,
    "refuse": REFUSE_OUT,
    "error": ERROR_OUT,
    "complete": AUDIT_SUPP,
}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def terminal_target(state: GraphState) -> str:
    """按 `state.terminal.event` 给出出口节点名（**未设终态**时回落到 `error_out`）。

    ⚠️ 回落是刻意的：走到"该选出口"却**没有终态**说明图有缺陷（漏设或漏分支），
    此时给 `error_out(INTERNAL)` 比"继续往下跑"安全 —— 后者会让这一轮没有终态事件，
    前端永久停在加载态（§14.3 约束 1 的反面）。
    """
    terminal = state.get("terminal") or {}
    event = str(terminal.get("event", ""))
    return _EXIT_BY_EVENT.get(event, ERROR_OUT)


def _gate(state: GraphState, gate_no: GateNo) -> object | None:
    results = state.get("gate_results") or {}
    return results.get(gate_no)


def _gate_passed(state: GraphState, gate_no: GateNo) -> bool:
    """读某个闸门的 `passed`。**只看 `is True`** —— 缺席 / `None` 一律不算通过。"""
    result = _gate(state, gate_no)
    return getattr(result, "passed", None) is True


def _gate3_rejected(state: GraphState) -> bool:
    """`decision=reject`（§14.2 D4）。`warn` / `skipped` **不是** reject（D5/D6 仍执行）。"""
    return getattr(_gate(state, GateNo.COST), "decision", None) is GateDecision.REJECT


def _exec_error_class(state: GraphState) -> str | None:
    """取 `exec_error.error_class`（W2D 的脱敏摘要，N-11）。

    `exec_error` 的类型在 `state.py` 里是 `OpaquePayload`（U-24 占位），
    实现里 W2D 传的是 `ExecError`（frozen dataclass）→ 故同时接受两种形态。
    """
    error = state.get("exec_error")
    if error is None:
        return None
    if isinstance(error, dict):
        value = error.get("error_class")
    else:
        value = getattr(error, "error_class", None)
    return str(value) if value is not None else None


# ---------------------------------------------------------------------------
# 逐条条件边（07 §5.4 表格逐行）
# ---------------------------------------------------------------------------


def route_after_normalize(state: GraphState) -> str:
    """§5.4：`not time_parse_ok and 含时间表达` → `clarify`；否则 → `intent`。

    ⚠️ "含时间表达"这一半由 planner 层承担："识别到时间表达但解析不出唯一窗口"才会
    返回 `time_parse_ok=False`（未识别到时 `resolve_time` 给 `ok=True`）。
    这里**不重做一遍文本判断** —— 那会是同一事实的第二份实现，且两份必然漂移
    （N-26：时间基准只来自语义包）。
    """
    if state.get("time_parse_ok") is False:
        return CLARIFY_OUT
    return INTENT


def route_after_intent(state: GraphState) -> str:
    """§5.4：`refuse` → `refuse_out`；`clarify` → `clarify_out`；
    `open_analysis` → `refuse_out`（NG4，给替代问法）；`executable` → `link`。"""
    intent = str(state.get("intent", IntentKind.EXECUTABLE.value))
    if intent == IntentKind.REFUSE.value:
        return REFUSE_OUT
    if intent == IntentKind.CLARIFY.value:
        return CLARIFY_OUT
    if intent == IntentKind.OPEN_ANALYSIS.value:
        # NG4：开放分析不是"看不懂"，是"这类问题不由本产品回答" → 拒答 + 替代问法。
        return REFUSE_OUT
    if state.get("terminal") is not None:
        # 意图为 `executable` 但节点已设终态（例如理解阶段撞上 kill switch，§14.2 G3）
        # → 按已定的终态出口，不硬走 `link`。
        return terminal_target(state)
    return LINK


def route_after_link(state: GraphState) -> str:
    """§5.4：`candidates.empty` → `refuse_out`；`ambiguities` 不可自动消解 → `clarify_out`；
    否则 → `plan`。

    ⚠️ "不可自动消解"的判定**不在本函数**：`link` 节点只把**消解不掉**的歧义留在
    `state.ambiguities` 里（能靠会话上下文消解的已在节点内消解并落日志）。
    本函数只看"还剩没有"—— 加一层启发式判断会让同一条歧义在两个地方被判定两次。
    ⚠️ 与 `binding_ambiguity`（L4 打分型歧义，发生在更晚的 `bind`）是**两个来源**，
    文案也完全不同（A1/A2 时间与意图 vs B2/B3 字段粒度），不得混判。
    """
    if state.get("terminal") is not None:
        return terminal_target(state)
    if not state.get("candidates"):
        return REFUSE_OUT
    if state.get("ambiguities"):
        return CLARIFY_OUT
    return PLAN


def route_after_plan(state: GraphState) -> str:
    """§5.4 第 4 行：`plan is None` → degraded → 模板 → 未命中 `refuse_out`。

    ⚠️ 成功去向 = **`bind`**（不是 §5.4 表字面的"命中则 `gen_sql`"）：
    该表没有给 `bind`（§5.3 主节点 5）任何入边 —— 按字面装配会让 `bind` 悬空，
    `route_after_bind`（表的下一行）与 §14.2 B2–B6（绑定歧义/未解析/口径披露）
    全部不可达。⇒ 本函数把成功跳接到 `bind`，由 `route_after_bind` 决定
    `gen_sql` / `clarify_out` / `refuse_out`（与表 L1330 的三去向逐字一致）。
    07 L1329 的字面缺口与本次修正已登记 RELAY §九。

    ⚠️ 模板分支在当前实现里不可达（模块 docstring §二-2）：模板层产出文本、
    `gen_sql` 需要结构化 `Plan`，故 `plan` 缺失一律 → `refuse_out`。
    """
    if state.get("terminal") is not None:
        return terminal_target(state)
    if state.get("plan") is None:
        return REFUSE_OUT
    return BIND


def route_after_bind(state: GraphState) -> str:
    """§5.4：`unique` → `gen_sql`；`ambiguous` → `clarify_out`；`none` → `refuse_out`。

    ⚠️ 按 `BindingState` 的 **4 值**实现（两种 `resolved_*` 都 → `gen_sql`），
    与 `state.py` 注释的 3 值不一致处见模块 docstring §二-1。
    """
    if state.get("terminal") is not None:
        return terminal_target(state)
    status = str(state.get("binding_status", ""))
    if status == BindingState.AMBIGUOUS.value:
        return CLARIFY_OUT
    if status == BindingState.UNRESOLVED.value:
        return REFUSE_OUT
    if status in (BindingState.RESOLVED_UNIQUE.value, BindingState.RESOLVED_DEFAULT.value):
        return GEN_SQL
    # 未登记的取值：宁可拒答（fail-safe，N-27）也不猜"大概绑上了"。
    return REFUSE_OUT


def route_after_gen_sql(state: GraphState) -> str:
    """§5.4：**恒 → `gate1_ast`**（"无分支：闸门是不可跳过的链"，N-03）。

    ⚠️ 本函数刻意**不判** `state.terminal`：在这里加 `terminal` 分支就等于允许
    "生成失败直接出去、跳过闸门"。SQL 生成失败由 `gen_sql` 节点自己决定出口（写终态），
    而"生成成功"必须过闸门。
    """
    return GATE1_AST


def route_after_gate1(state: GraphState) -> str:
    """§5.4：`not passed` → `error_out(GATE_AST_REJECTED)`，**不进 repair**
    （结构性拒绝，重试无意义 —— 07 §5.4 明文）。"""
    if _gate_passed(state, GateNo.AST):
        return GATE2_POLICY
    return ERROR_OUT


def route_after_gate2(state: GraphState) -> str:
    """§5.4：`not passed` → `error_out`（"按具体码"）。

    ⚠️ "按具体码"在实现上 = **节点已把码写进 `state.terminal`**：§14.2 里 gate2 有两条不同去向
    （D2 策略版本不一致 → `error(GATE_POLICY_REJECTED)`；D3 命中敏感列 → `refuse(pii_blocked)`），
    条件边无法从 `GateResult` 反推是哪一条。
    """
    if _gate_passed(state, GateNo.POLICY):
        return GATE3_COST
    return terminal_target(state)


def route_after_gate3(state: GraphState) -> str:
    """§5.4：`decision=pass` → 若超阈值且 `async_if_slow` → 转异步 `complete`；否则 → `execute`。
    `decision=reject` → `error_out(COST_TOO_HIGH)`。

    ⚠️ **`warn` / `skipped` 一律继续执行**（§14.2 D5/D6）：它们不是 `reject`，
    同时**不得**被报告为"通过"—— 那条判据在 `events.py`（按 `passed is True` 决定发不发
    `stage=gate_passed`），两处各管一件事，不重复也不互替。
    ⚠️ 转异步的去向是 `audit_supp`（跳过 `execute`/`mask`/`audit_pre`/`present`）：
    结果尚未产生，没有 `data` 可发；`complete` 由 `audit_supp` 之后统一发出。
    ⚠️ 但该分支当前**不可达** —— 缺"预估延迟"载体（模块 docstring §二-4）。
    """
    if _gate3_rejected(state):
        return ERROR_OUT
    if state.get("terminal") is not None:
        return terminal_target(state)
    if _should_go_async(state):
        return AUDIT_SUPP
    return EXECUTE


def _should_go_async(state: GraphState) -> bool:
    """转异步判定（§5.4 + §14.2 F5）。

    **四个条件缺一不可**：① 用户显式允许（`async_if_slow`）；② 给了阈值；
    ③ 有"预估延迟"这个载体；④ 它真的超了阈值。缺任一项就转异步是不允许的 ——
    用户拿到一个被异步化的答案、却从未同意过，与静默降级同类（N-21）。

    ⚠️ 当前 ③ 不成立（`GateResult` 无延迟字段，见模块 docstring §二-4）⇒ 恒 `False`。
    这是**如实暴露的未接线**，不是"静默不实现"：`tests/contract/test_edges_contract.py`
    有一条用例专门断言这个默认行为，接线后它会红 —— 那时才是改动点。
    """
    options = state.get("options")
    if not isinstance(options, dict):
        return False
    if options.get(_ASYNC_IF_SLOW_KEY) is not True:
        return False
    threshold = options.get(_ASYNC_THRESHOLD_KEY)
    if not isinstance(threshold, int | float):
        return False
    estimated = _estimated_latency_ms(state)
    if estimated is None:
        return False
    return estimated > threshold


def _estimated_latency_ms(state: GraphState) -> int | float | None:
    """gate3 预估的执行延迟（毫秒）。

    ⚠️ **当前恒返回 `None`**：`GateResult` 只有 `estimated_rows` / `estimated_cost` /
    `decision`（`core/contracts.py`，端口已冻结），没有延迟字段。拿 `estimated_rows` 当延迟
    是"造一个看起来合理的假数字"（U-22 红线），故此处返回 `None`（→ 不转异步）。
    载体落地后，本函数是唯一改动点。
    """
    return None


def route_after_execute(state: GraphState) -> str:
    """§5.4：成功 → `mask`；失败 且 `repair_round < 2` 且 `exec_error.class ∈ 可修集`
    → `repair`；否则 → `error_out(EXEC_TIMEOUT / SQL_SYNTAX_ERROR / DB_UNAVAILABLE)`。

    可修集来自 `app.exec.REPAIRABLE_CLASSES`（**不在这里再抄一份**）。
    """
    error_class = _exec_error_class(state)
    if error_class is None:
        return MASK
    if int(state.get("repair_round", 0)) < MAX_REPAIR_ROUNDS and error_class in REPAIRABLE_CLASSES:
        return REPAIR
    return ERROR_OUT


def route_after_repair(state: GraphState) -> str:
    """§5.3 第 16 行"失败转移：→ 重回 `gate1`"（§5.4 表缺席，见模块 docstring §二-3）。

    ⚠️ 纠错后的 SQL **必须重过全部闸门**：`repair` 产出的新 SQL 与首次生成在安全面上等价 ——
    "它只是小改"是模型的声明，不是事实（N-17 原话：乱改会产出"看起来能跑但算错"的 SQL）。
    """
    return GATE1_AST


def route_after_mask(state: GraphState) -> str:
    """§5.4：成功 → `audit_pre` → `present`；失败 → `error_out(INTERNAL)`。

    ⚠️ 脱敏失败是 **fail-closed**（07 §5.3 第 12 行）：宁可不给，也不给明文。
    故这里不存在"部分脱敏 + 继续"的路径。
    """
    if state.get("terminal") is not None:
        return terminal_target(state)
    return AUDIT_PRE


def route_after_audit_pre(state: GraphState) -> str:
    """§5.4 `route_after_mask` 行内含（"→ `audit_pre` → `present`"）（缺口见 docstring §二-3）。

    段 1 审计失败 → **fail-closed**：不下发 `data`（N-09 / §14.2 G1）。
    """
    if state.get("terminal") is not None:
        return terminal_target(state)
    return PRESENT


def route_after_present(state: GraphState) -> str:
    """§5.4：→ `audit_supp` → 发 `complete`。"""
    return AUDIT_SUPP


def route_terminal(state: GraphState) -> str:
    """§5.4 最后一行的**幂等收口**：终态已设 → `END`。

    ⚠️ 本函数只回答"能不能结束"，不回答"发不发终态事件" —— 后者是 `events.py` 的守卫
    （重复终止事件 → 丢弃 + `ui_contract_violation`）。双保险是 §14.3 约束 1 的原文要求。
    """
    if state.get("terminal") is None:
        raise ValueError(
            "`route_terminal` 在未设终态时被调用 —— 说明图里有出口路径没有写 `state.terminal`。"
            "这会让这一轮没有任何 `terminal:true` 事件（前端永久停在加载态），"
            "必须作为图缺陷处理，而不是在这里补一个默认终态。"
        )
    return END
