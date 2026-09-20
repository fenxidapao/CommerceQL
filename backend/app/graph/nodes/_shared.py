"""节点共用件：依赖取用、终态写入、闸门合并、分项计时。

层号：L4｜归属窗口：W4（`docs/08 §4.1`：`app/graph/**`）。

⚠️ 本模块**不是**节点 —— 它不出现在 `graph/nodes/__init__.py` 的节点名常量表里，
也不被 `add_node` 注册。它存在的理由是三条**跨全部节点**的纪律只能各写一遍：

| 纪律 | 若各写一遍会怎样 |
|---|---|
| 终态只能写一次（N-08） | 漏调 `assert_terminal_is_settable` 的那个节点可以覆盖终态，而它的表现是"事件重复"而不是报错 |
| `gate_results` 是**合并**写（组 7 是 Mapping） | 后写的闸门把前两个盖掉 → `gate_passed` 永远不满足"三闸门全过" |
| 出口节点必须带计量（组 11） | 漏一个键 → `latency_ms`/`tokens`/`cost_cny` 只在成功路径上有值，**失败路径上审计缺计量** |

--------------------------------------------------------------------------
一、`terminal_update()` 为什么连计量一起写
--------------------------------------------------------------------------
`GraphState` 组 11 是 `terminal / clarify / outcome / latency_ms / tokens / cost_cny`
**同一组**：07 §5.2 把它们归在一起正是因为"谁写终态，谁就把这一轮的计量收口"
（出口是所有路径的汇聚点，也是唯一能确定"这一轮到此为止"的地方）。
若让三个出口节点各自拼这六个键，漏一个键的表现是**静默的**：`meta` 事件少一个字段
（只有 `missing_meta_keys` 会记账，且它不阻断）。

--------------------------------------------------------------------------
二、`gate_update()` 为什么必须合并而不是覆盖
--------------------------------------------------------------------------
`GraphState.gate_results` 没有 reducer（`state.py` 是纯 `TypedDict`，无 `Annotated[...]`），
⇒ 节点返回的增量对该键是**整体覆盖**。三道闸门分三个节点写 ⇒ 各自返回
`{"gate_results": {自身那一个}}` 会把前一道抹掉，而 `events._all_gates_clean_pass`
读的是"三闸门全过"——它就会永远为假（表现为 `gate_passed` 事件从不出现）。
本函数把"读旧 + 加新"收在一处，调用方拿到的永远是全量 Mapping。

--------------------------------------------------------------------------
三、分项计时的键集缺口（**如实登记，不发明键**）
--------------------------------------------------------------------------
`LatencyKey` 是**恰好 8 个**（C-04 要求与 `audit_log.latency_ms` 键集完全一致），
其中没有 `bind` / `mask` / `audit` 三项 —— 而 07 §16.1 的预算表里它们是独立阶段
（0.1s / 0.1s / 0.1s）。⇒ 本模块**不**给它们硬塞一个语义不符的键（那会让
`latency_ms.exec` 变成"execute+mask"，两处数不再可比）。它们的耗时只体现在
`latency_ms.total` 里。缺口已登记。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, cast

import orjson

from app.core.contracts import CandidateRef, GateResult, IdentityContext
from app.core.enums import (
    BindingLayer,
    ErrorCode,
    GateNo,
    LatencyKey,
    Outcome,
    RefuseReason,
)
from app.core.errors import ContractViolationError
from app.graph.context import RunContext, current_run_context
from app.graph.state import GraphState, assert_terminal_is_settable
from app.llm.errors import LlmRefused
from app.obs.logging import get_logger

_log = get_logger(__name__)

__all__ = [
    "audit_pre_payload",
    "candidate_payload",
    "candidate_ref",
    "deps_of",
    "gate_update",
    "identity_of",
    "llm_error_update",
    "metering_update",
    "node_latency",
    "rc",
    "rich_method",
    "terminal_update",
    "write_audit_pre",
]


def rc() -> RunContext:
    """当前请求的上下文（未设置即抛 —— fail-fast 归 `context.current_run_context`）。"""
    return current_run_context()


def deps_of() -> Any:
    """当前请求的服务依赖（`GraphDeps`）。"""
    return current_run_context().deps


def identity_of(state: Mapping[str, Any]) -> IdentityContext:
    """state 组 1 → `IdentityContext`（**唯一**逆向转换点，见 `context.identity_from_state`）。"""
    from app.graph.context import identity_from_state

    return identity_from_state(state)


@contextmanager
def node_latency(key: LatencyKey) -> Iterator[None]:
    """给一段节点内的工作计时并累加到 `RunContext`（同键累加，见 `record_latency`）。

    用上下文管理器而不是"起止各调一次"：后者在异常路径上会**丢掉**计时
    （`except` 里忘写第二行），而失败路径的耗时恰恰是排查慢请求时最需要的。
    """
    context = rc()
    started = context.elapsed_ms()
    try:
        yield
    finally:
        context.record_latency(key, context.elapsed_ms() - started)


def gate_update(state: Mapping[str, Any], gate_no: GateNo, result: GateResult) -> dict[str, Any]:
    """把一道闸门的判定并进 `gate_results`（**合并**，见模块 docstring §二）。"""
    merged: dict[GateNo, GateResult] = dict(state.get("gate_results") or {})
    merged[gate_no] = result
    return {"gate_results": merged}


def metering_update(context: RunContext | None = None) -> dict[str, Any]:
    """组 11 的计量三件套 + 组 10 的降级累积（出口/`present` 的收口写）。"""
    the_context = context or rc()
    return {
        "latency_ms": the_context.latency_ms(),
        "tokens": the_context.tokens_payload(),
        "cost_cny": the_context.cost_cny(),
        "degradations": list(the_context.degradations()),
    }


def terminal_update(
    state: GraphState,
    *,
    event: str,
    outcome: Outcome,
    code: str | None = None,
    reason: str | None = None,
    clarify: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """写终态（**唯一**入口：含 N-08 的一次性检查 + 计量收口）。

    `event` 的取值集 = `state.terminal.event` 的四种：`clarify` / `refuse` / `error` / `complete`。
    前三种由**出口节点**（`clarify_out` / `refuse_out` / `error_out`）写；`complete` **不由**
    出口节点写 —— 它是成功路径的收口，由 `audit_supp` 在段 2 审计之后写
    （07 §5.6："`complete` | `audit_supp` 之后"）。
    写它的理由不是"发事件"（`complete` 事件由 `events.emissions_for_node` 产出），
    而是让成功路径也**经过同一个 `route_terminal` 收口**（两处收口 = 两套幂等语义）。

    ⚠️ 本函数**不做**"该给哪个码"的判断：那是各节点自己的结论（同一个 gate2 有
    D2 `error(GATE_POLICY_REJECTED)` 与 D3 `refuse(pii_blocked)` 两条去向）。
    """
    assert_terminal_is_settable(state)
    terminal: dict[str, Any] = {"event": event}
    if code is not None:
        terminal["code"] = code
    if reason is not None:
        terminal["reason"] = reason
    update: dict[str, Any] = {"terminal": terminal, "outcome": outcome}
    update.update(metering_update())
    if clarify is not None:
        update["clarify"] = dict(clarify)
    return update


def llm_error_update(state: GraphState, exc: Exception, *, stage: str) -> dict[str, Any]:
    """`LlmError` 家族 → 终态增量（**`LlmRefused` 必须最先分流**，07 §10.2 末行）。

    | 异常 | 终态 | 依据 |
    |---|---|---|
    | `LlmRefused` | **`refuse`**（产品结论） | 07 §10.2 末行"模板无命中 = 拒答（不是 error）" |
    | 其余 `LlmError` | `error`（取 `default_code`，缺则 `INTERNAL`） | §14.2 F2/F3：429/5xx **不降级**，直接成为 error |

    🔴 **为什么本函数必须先 `isinstance(exc, LlmRefused)` 再取 `default_code`**：
    `LlmRefused.default_code is None`（W3A 刻意留 `None`），一旦走"取 default_code → 缺则 INTERNAL"
    的兜底，产品结论就会被折成 `500 INTERNAL` —— 那正是 W3A/W3B 两份 RELAY 反复警告的错终态。

    ⚠️ **本条路径不再补发 `degraded`**：网关在降级链的每一跳都已通过它的 sink 发过
    （`app/llm/__init__.py` 的 `_emit`），这里再发一条会把同一跳记成两次。
    只有"模板无命中"这一跳是网关**没有**发的（它直接抛异常）—— 但那一跳没有对应的
    `DegradedReason` 取值（C-08 的 8 值里没有"拒答"），故也不在此处编一个。
    """
    if isinstance(exc, LlmRefused):
        return terminal_update(
            state,
            event="refuse",
            outcome=Outcome.REFUSE,
            # ⚠️ C-12 的 4 个取值里没有"模型全档不可用"的槽位 → 取最接近的 `no_data_asset`。
            #    这是一条**已知近似**，已登记待架构裁决（见本窗口 RELAY）。
            reason=RefuseReason.NO_DATA_ASSET.value,
        )
    code = getattr(exc, "default_code", None) or ErrorCode.INTERNAL.value
    return terminal_update(state, event="error", outcome=Outcome.FAILED, code=str(code))


def rich_method(port: Any, name: str, *, why: str) -> Callable[..., Any]:
    """取某个 **Port 上没有、但实现类上有**的"富方法"（缺则 fail-fast）。

    存在的理由：端口是 W0 冻结的最小面（`core/contracts.py`），而节点需要实现类上的富出参
    —— `retrieval.search_full`（要 `mode`/`degraded_reason`，C-11 要求如实回填）与
    `executor.explain`（U-63：gate3 的 EXPLAIN **只能**走它，走 `fetch` 会撞 PG 42601）。
    这类调用**不能**写成 `getattr(..., None)` 后静默跳过：跳过 = gate3 永远 SKIPPED、
    link 永远拿不到降级信息，而且没有任何报错。故取不到即抛（契约破损，fail-fast）。

    ⚠️ 返回类型是 `Callable[..., Any]`（不是具体签名）：本函数**刻意**不锁签名 ——
    真正的契约在调用点的逐字段使用上（`why` 把那条契约写在错误信息里，便于归因）。
    `cast` 只把 `getattr` 的 `Any` 收敛到已声明的返回类型上，**不缩小** callable 本身的
    参数/返回面（mypy 要求 `no-any-return` 显式，故这里必须写）。
    """
    method = getattr(port, name, None)
    if not callable(method):
        raise ContractViolationError(
            f"注入的实现缺少 `{name}` —— {why}",
            detail={"missing_method": name, "port_type": type(port).__name__},
        )
    return cast("Callable[..., Any]", method)


# ============================================================================
# 候选引用的两个方向（**成对**，键名只在这里出现一次）
# ============================================================================
#
# 为什么需要这一对：
# `GraphState.candidates` 的标注是 `tuple[OpaquePayload, ...]`（`state.py` 的 U-24 占位：
# "图不解释载荷"），而 `app.binding` 的入参是 `Sequence[CandidateRef]`（L0 值对象）。
# 两个方向若各写一遍 `{"asset_id": ...}` 的字面量，改键名时必然漏一处 ——
# 而漏掉的表现是**静默少一个候选**（`resolve_detailed` 不会报错，只会当它不存在）。
# 故两个方向写在一起，由 `tests/contract/` 的往返用例钉住（`ref → payload → ref` 等值）。


def candidate_payload(ref: Any) -> dict[str, Any]:
    """`CandidateRef` → state 可存的 `Mapping`（`layer` 缺省写 `None`，不省略键）。"""
    layer = getattr(ref, "layer", None)
    score = ref.score
    if score is None:
        # 上游（检索/缓存）违反了 `CandidateRef.score: float` 契约，给了 None ——
        # 不该为一个元数据字段把整条请求 500 掉（U-107 同款：上游坏数据 → 降级可见，
        # 不是 error(INTERNAL)）。与 `candidate_ref` 的 `or 0.0` 对称：按 0 分落地并告警，
        # 溯源修复归上游数据源。
        _log.warning(
            "candidate_payload_null_score",
            asset_id=str(ref.asset_id),
            extra_fact="上游给了 score=None 的候选（契约违约）→ 按 0.0 落地，需上游溯源",
        )
        score = 0.0
    return {
        "asset_id": str(ref.asset_id),
        "score": float(score),
        "layer": None if layer is None else str(getattr(layer, "value", layer)),
    }


def candidate_ref(payload: Any) -> CandidateRef:
    """`Mapping` → `CandidateRef`（**逆向**；形状不合即抛，不猜）。

    ⚠️ `layer` 是 `BindingLayer | None`：写成裸字符串会让 binding 的
    `ref.layer is BindingLayer.L4` 恒为假 —— 表现为"L4 分数一个都不被消费、
    `ignored_candidates` 等于全量"，而没有任何报错。故此处必须还原成枚举。
    """
    if not isinstance(payload, Mapping) or "asset_id" not in payload:
        raise ContractViolationError(
            "候选引用形状不合（缺 `asset_id`）—— `GraphState.candidates` 只接受 "
            "`candidate_payload()` 写出的形状；手拼的 dict 必须走该函数",
            detail={"got_type": type(payload).__name__},
        )
    raw_layer = payload.get("layer")
    layer = None if raw_layer is None else BindingLayer(str(raw_layer))
    return CandidateRef(
        asset_id=str(payload["asset_id"]),
        score=float(payload.get("score") or 0.0),
        layer=layer,
    )


# ============================================================================
# 段 1 审计（**一处实现，五个调用方**）
# ============================================================================
#
# 为什么它不是 `audit_pre` 节点的私有件：
# §5.4 的 `route_terminal` 写"若 `state.terminal` 已设置 → 直接 `audit` → `END`"，
# 而 07 §5.3 的 16 节点表里**没有** `audit` 节点（新增会破坏 16 节点对账基线）。
# ⇒ 失败/澄清/拒答三条路径的段 1 审计只能由**出口节点自己**做 —— 于是它是 4 个调用方
# （`audit_pre` + 三个出口 + 将来可能的 `switch_to_async`）。
# 若各写一份，漂移的表现是**审计缺列**（`AuditSchemaMismatch` 只在字段名不在白名单时红，
# 少一列不会报错）。
#
# 🔴 `latency_ms` 必须传 **JSON 字符串**：列是 `jsonb`，而 `insert_audit_log` 用的是
# `CAST(:latency_ms AS jsonb)` —— psycopg 把 `str` 按 `text` 绑，靠 CAST 转；
# 传 dict 会走另一条适配路径（两条路径对"空 dict"的行为未必一致）。


def audit_pre_payload(
    state: Mapping[str, Any],
    *,
    columns_accessed: Sequence[str] = (),
    tables_accessed: Sequence[str] = (),
    outcome: Outcome | None = None,
    refusal_reason: str | None = None,
) -> dict[str, Any]:
    """段 1 审计的 payload（列名与 `app/repo/audit_store.py` 的白名单**逐字对齐**）。

    | 列 | 来源 | 缺时 |
    |---|---|---|
    | `raw_question` / `outcome` | 组 1 / 组 11（**必填**） | `outcome` 缺失时按"这一轮尚未失败"落 `success`（段 1 只在下发前写） |
    | `final_executed_sql` | 组 6（`sql_text`，**改写后**的那条） | 早退路径没有 SQL → 省略 |
    | `pii_columns_hit` | `mask` 命中的列名（`RunContext` 中转） | 空 |
    | `truncated` / `row_count_returned` | 组 8 | 省略 |
    | `scope_level` | 组 7；缺失按 C-07 缺省 `unrestricted` | — |
    | `bundle_version` | `RunContext.bundle_version`（§5.7） | — |
    | `prompt_version` / `model_version` | 组 6（N-19） | 未调模型时省略 |
    | `latency_ms` | `RunContext.latency_ms()`（**下发前快照**，与 `meta.latency_ms.total` 必然不同 —— C-04 已注明） | — |
    | `refusal_reason` | `terminal.reason` | 非拒答时省略 |
    | `tables_accessed` / `columns_accessed` | **无来源**（见模块 docstring 缺口） | 省略 |

    ⚠️ 缺口如实说明：`tables_accessed` / `columns_accessed` 在 P0 **拿不到** ——
    被引用的表/列由 `guard` 内部的 `_extract_tables` / `extract_columns_with_assets` 提取，
    两者都**未公开**，而 `run_gate1/gate2` 的出参里没有它们。审计这两列因此暂缺，
    而不是填一个语义不符的值（审计表是合规产物，宁可缺列不可错列）。

    ⚠️ `outcome` / `refusal_reason` 必须可由**调用方显式传入**：出口节点调用本函数时，
    它自己的终态增量**还没有并进 state**（`write_audit_pre` 拿到的是入参 state），
    靠读 `state["outcome"]` 会把一次澄清/拒答记成 `success`（审计表里最危险的一类错）。
    """
    context = rc()
    payload: dict[str, Any] = {
        "raw_question": state.get("raw_question"),
        "outcome": _outcome_text(state, outcome),
        # §5.7：语义包版本挂在 `RunContext`（`GraphState` 没有该键，见 `events.meta_payload` 的表）。
        "bundle_version": context.bundle_version,
        "scope_level": _scope_level(state),
        # 段 1 的 `latency_ms` 是**下发前快照**（与 `meta.latency_ms.total` 必然不同 —— C-04 已注明）。
        # 🔴 取自 `RunContext` 累加器而**不是** `state["latency_ms"]`：
        # `metering_update()` 只在**出口节点**（`terminal_update` 内）调用一次 ⇒ 在成功路径上
        # `audit_pre` 运行时 `state["latency_ms"]` **还没被写过**，读它会得到空 `{}`
        # （实测：`{"latency_ms": "{}"}`）；而在失败路径上读到的又是"某个失败节点当时写的"
        # 半成品 —— 同一个审计列在两条路径上语义不同，且成功路径恒为空。累加器是唯一真相。
        "latency_ms": _json_text(context.latency_ms()),
        # `mask` 命中的列（`RunContext` 中转；`take` 取走即清 —— 段 1 每轮只写一次）。
        "pii_columns_hit": list(context.take_mask_hits()),
    }
    sql_text = state.get("sql_text")
    if sql_text:
        payload["final_executed_sql"] = str(sql_text)
    for key, column in (
        ("row_count", "row_count_returned"),
        ("truncated", "truncated"),
    ):
        if state.get(key) is not None:
            payload[column] = state[key]
    for key, column in (("prompt_version", "prompt_version"), ("model_version", "model_version")):
        if state.get(key) is not None:
            payload[column] = str(state[key])
    terminal = state.get("terminal") or {}
    reason = refusal_reason if refusal_reason is not None else terminal.get("reason")
    if reason is not None:
        payload["refusal_reason"] = str(reason)
    if tables_accessed:
        payload["tables_accessed"] = list(tables_accessed)
    if columns_accessed:
        payload["columns_accessed"] = list(columns_accessed)
    return payload


async def write_audit_pre(
    state: GraphState,
    *,
    columns_accessed: Sequence[str] = (),
    outcome: Outcome | None = None,
    refusal_reason: str | None = None,
) -> bool:
    """写段 1（`audit_log`）。返回 `True` = 已落库；`False` = 失败（**调用方决定后果**）。

    ⚠️ 后果**不是本函数决定**的：`audit_pre` 节点失败时走 fail-closed（不下发 `data`），
    而出口节点失败时终态**已经定了**（N-08 不允许改），只能告警 + 如实登记。
    把"怎么写"与"失败怎么办"分开，是因为这两个答案在四个调用点上不同。
    """
    context = rc()
    identity = identity_of(state)
    payload = audit_pre_payload(
        state,
        columns_accessed=columns_accessed,
        outcome=outcome,
        refusal_reason=refusal_reason,
    )
    try:
        await context.deps.audit.write_pre(identity, payload)
    except Exception as exc:
        _log.error(
            "audit_pre_failed",
            outcome="see_caller",
            task_id=identity.task_id,
            error_type=type(exc).__name__,
            extra_fact="audit_pre 节点在此之后 fail-closed；出口节点已定终态（N-08）只能告警",
        )
        return False
    return True


def _outcome_text(state: Mapping[str, Any], explicit: Outcome | None = None) -> str:
    if explicit is not None:
        return explicit.value
    outcome = state.get("outcome")
    if outcome is None:
        # 段 1 只在下发前写 ⇒ 走到这里说明这一轮没有失败（其余出口各自落自己的终态）。
        return Outcome.SUCCESS.value
    return str(getattr(outcome, "value", outcome))


def _scope_level(state: Mapping[str, Any]) -> str:
    scope = state.get("scope")
    level = getattr(scope, "level", None)
    if level is None:
        # C-07 缺省语义：字段缺失视为 `unrestricted`（不改变披露策略）。
        return _DEFAULT_SCOPE_LEVEL
    return str(getattr(level, "value", level))


def _json_text(value: Any) -> str:
    return orjson.dumps(value, default=str).decode()


#: C-07 的缺省 `scope.level`（= `ScopeLevel.UNRESTRICTED` 的取值）。
_DEFAULT_SCOPE_LEVEL = "unrestricted"
