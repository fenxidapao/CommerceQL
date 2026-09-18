"""`graph/events.py` —— SSE 事件的**唯一产出点**（07 §5.6；`docs/08 §3.6` 产出③）。

层号：L4｜归属窗口：W4（`docs/08 §4.1`：`app/graph/**`）。

--------------------------------------------------------------------------
一、本层存在的理由（不是"把发事件封装一下"）
--------------------------------------------------------------------------
07 §5.3 表头那句是硬约束：**"SSE 事件不由节点直接发 —— 节点只写 state，事件由
`graph/events.py` 按 state 变化统一产出（§5.6）。这消灭了『多处拼事件帧』的漂移源。"**

已登记的历史病害给出了漂移的具体形态：`stage` 出现过非法值（`data_ready` / `complete`），
`terminal: true` 有的出口路径记得带、有的忘带 —— 于是**前端在澄清路径上永远转圈**。
所以本层落的是两个**机制**（不是纪律）：

| 机制 | 实现点 | 违反时 |
|---|---|---|
| `terminal` 由本模块**统一注入** | `EventRecorder.push()`（单点） | 任何 Emission **不得**自带 `terminal` → 抛错 |
| 终态唯一 + 终态后禁发 | `EventRecorder.push()` 的 `_terminal_emitted` 守卫 | **丢弃**已产出的帧 + `ui_contract_violation` 告警（07 §14.3 约束 3） |

⚠️ 与 `app.api.sse.encode()` 的分工**刻意切开**（见下节）：
`encode()` 仍会对 `terminal` 做第二次校验 —— 两道防线不是冗余：本层防"该不该发"，
`encode()` 防"发出去的帧自相矛盾"，而 `encode()` 是**唯一**能保证字节级格式的地方。

--------------------------------------------------------------------------
二、分层：本模块**不 import `app.api`**（`.importlinter` 的 W4 TODO 第 2 条）
--------------------------------------------------------------------------
`app.api` 是 L5、`app.graph` 是 L4 → **L4 不得 import L5**。而帧编码的唯一入口是
`app.api.sse`。两者的分工：

| 层 | 唯一职责 |
|---|---|
| `app.api.sse` | **编码**：`SseEvent + data` → SSE 字节帧（`terminal` 缺省、`stage` 合法性、JSON 序列化） |
| 本模块 | **发射决策**：何时发哪个事件、是否已发过终态、事件顺序是否合法 |

因此 `encoder` 是**注入**的、**无默认值**：一个有默认值的编码器会诱使本层去
`import app.api.sse`，而那正是 importlinter 要拦的（"看起来能用"是这类越界最危险的地方）。
装配点（`app/main.py` 的 lifespan、`app/api/routers/query.py`）注入 `app.api.sse.encode`。

--------------------------------------------------------------------------
三、"17 发射点"是怎么分配到这个模块的
--------------------------------------------------------------------------
`core.enums.SSE_STAGE_EMISSION_POINTS` 的 17 项 = 12 种事件类型 + 6 个 `stage` 值（`stage` 要发 6 次）。
其中 2 项**不由节点触发**，但**仍由本模块产出**（保持"唯一产出点"不破）：

- `ack` —— 流建立后立即，由 API 层调 `recorder.ack(...)`；
- `heartbeat` —— API 层定时器每 15s 调 `recorder.heartbeat()`。

另 15 项由节点结束时的 state 变化触发（`emissions_for_node`）。节点名 → 发射点的映射
**逐个对照 07 §5.6 的"发出时机"列**，其中两处需要显式说明（都是有意的，不是抄漏）：

1. **`stage=executing`（"执行**开始前**"）挂在 `gate3_cost` 之后**：
   updates 流只给"节点跑完"的增量，拿不到"节点将要开始"。而 gate3 通过后**下一個节点必然是
   `execute`**（07 §5.4 `route_after_gate3`），故此处发出的 `executing` 在时序上仍严格
   早于执行本身 —— 语义没有被拉扯，只是挂载点必须选一个可观测的时刻。
2. **`stage=gate_passed` 只在三闸门 `passed is True` 时发**：
   §14.2 D5（`warn` 仍执行）/ D6（`skipped` 仍执行）都**不得报告为通过**，但**仍要发 `executing`**
   —— 两者是独立判据，故 `gate3_cost` 可能只发 `executing`。这是 D5/D6 的机器化。
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Final

from app.core.enums import (
    GateDecision,
    GateNo,
    SseEvent,
    Stage,
)
from app.core.errors import ContractViolationError
from app.graph.nodes import (
    AUDIT_PRE,
    AUDIT_SUPP,
    CLARIFY_OUT,
    ERROR_OUT,
    GATE3_COST,
    GEN_SQL,
    INTENT,
    LINK,
    PLAN,
    PRESENT,
    REFUSE_OUT,
    TERMINAL_EVENT_BY_NODE,
)
from app.obs.logging import get_logger

__all__ = [
    "Encoder",
    "Emission",
    "EventRecorder",
    "emissions_for_node",
    "gate_detail",
    "meta_payload",
    "missing_meta_keys",
]

_log = get_logger(__name__)

#: 帧编码器。装配点注入 `app.api.sse.encode`（本模块不得 import 它，见模块 docstring §二）。
Encoder = Callable[[SseEvent, Mapping[str, Any]], bytes]

#: `meta` 事件**必须**携带的键。07 §14.3 约束 7 明文："`meta` 必须携带 `scope` 与 `retrieval_mode`
#: —— 缺任一项即为契约违规（C-07 / C-11）"。
#: 后 5 个来自 07 §5.6 的 `meta` 行（`bundle_version` / `cost_cny` / `tokens` / `latency_ms` / `trace_id`）。
_META_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "bundle_version",
    "cost_cny",
    "tokens",
    "latency_ms",
    "trace_id",
    "scope",
    "retrieval_mode",
)

#: 有界队列容量。**必须有界**：无界队列在"客户端断连但图仍在跑"时会把内存吃光。
_QUEUE_MAXSIZE: Final[int] = 1024

#: 流结束哨兵（消费者收到它即停止迭代）。用 `None` 而不是空字节串 ——
#: 空字节串是一个合法的（虽然没有意义的）帧，混用它会让消费者无法区分"结束"与"收到空帧"。
_EOF: Final[None] = None


# ============================================================================
# 值对象
# ============================================================================


@dataclass(frozen=True, slots=True)
class Emission:
    """一次**发射决策**（尚未编码）。

    ⚠️ **没有 `terminal` 字段，且不得有**：它由 `EventRecorder.push()` 单点注入
    （见模块 docstring §一）。把它放进值对象，就等于允许调用方各自决定 —— 那正是病害的形态。
    """

    event: SseEvent
    data: Mapping[str, Any]
    stage: Stage | None = None


# ============================================================================
# 纯函数：state 增量 → 事件序列（可单测；不碰队列、不碰时钟）
# ============================================================================


def emissions_for_node(
    node: str,
    update: Mapping[str, Any],
    *,
    elapsed_ms: int,
    explain: bool = True,
    extras: Mapping[str, Any] | None = None,
) -> tuple[Emission, ...]:
    """按节点名 + 该节点的 state 增量产出事件序列（07 §5.6 的"发出时机"列逐行）。

    ⚠️ **本函数不发 `degraded`**：降级来自两条**侧信道**（`app.llm` 的 `DegradationSink`
    与 `app.planner` 的 `PlannerDegradationSink`，都是**同步回调**），它们的触发时刻与
    "节点跑完"无关（可能发生在节点中途）。故 `degraded` 由 `EventRecorder.degraded()`
    独立产出 —— 但**仍经由本模块**，唯一产出点不破。

    `extras` 承接**不属于 `GraphState` 的载荷**（07 §5.2 的字段是穷举的，不得为发事件新增字段）：
    · `audit_pre` → `rows`（结果行在 Redis，不在 state；runner 取回后经此传入）
    · `error_out` → `message` / `detail` / `retryable`（文案与可重试性由 `api/errors` 映射，
      见 `ErrorMapperPort`）
    缺 `extras` 时如实发"少字段"的事件并告警，**不编造**（U-22）。
    """
    payload_extra: Mapping[str, Any] = extras if extras is not None else {}
    if node == INTENT:
        # 07 §5.6：`stage=intent` 的耗时**含 `normalize`** —— 故 elapsed 从 run 起算，
        # 而不是本节点的局部耗时（局部耗时会让前端进度条在合并档下突然回退）。
        return (_stage_emission(Stage.INTENT, elapsed_ms, {}),)

    if node == LINK:
        return (
            _stage_emission(
                Stage.SCHEMA_LINKING,
                elapsed_ms,
                {"candidates_count": len(_seq(update.get("candidates")))},
            ),
        )

    if node == PLAN:
        return (
            _stage_emission(
                Stage.PLAN_READY,
                elapsed_ms,
                {"plan_summary": _jsonable(update.get("plan_summary"))},
            ),
        )

    if node == GEN_SQL:
        data: dict[str, Any] = {
            "dialect": update.get("sql_dialect", "postgres"),
            "confidence": update.get("confidence"),
        }
        # 07 §5.6：`explain=false` 时**省略 `sql` 字段但事件照发** ——
        # "省略字段"与"不发事件"是两件事，混起来会让前端少一个进度节点。
        if explain:
            data["sql"] = update.get("sql_text")
        return (_stage_emission(Stage.SQL_READY, elapsed_ms, data),)

    if node == GATE3_COST:
        # 三闸门全过 → `gate_passed`；随后无论 warn/skipped/pass 都要进执行 → `executing`。
        emissions: list[Emission] = []
        gates = _mapping(update.get("gate_results"))
        if _all_gates_clean_pass(gates):
            emissions.append(
                _stage_emission(
                    Stage.GATE_PASSED, elapsed_ms, {"gate_detail": gate_detail(gates)}
                )
            )
        emissions.append(_stage_emission(Stage.EXECUTING, elapsed_ms, {}))
        return tuple(emissions)

    if node == AUDIT_PRE:
        # 07 §5.6：`data` 在"`mask` 完成**且 `audit_pre` 提交后**"发出 —— 挂在本节点之后，
        # 正是 N-09「审计写入不得晚于结果下发」的落地（审计失败 = fail-closed，不走到这里）。
        # 🔴 fail-closed 必须在**发射层**兑现（§14.3 约束 6）：写库失败时节点返回的是
        # `terminal=error` 增量（没有 result_columns）—— 此时若仍无条件发 DATA，前端会
        # 收到"空表格 + error"的组合，data 帧的"审计已提交"承诺就成了谎话。
        # （终态 error 帧由后续 `error_out` 节点经 terminal_target 收口发出，不受影响。）
        if update.get("terminal") is not None:
            return ()
        columns = _seq(update.get("result_columns"))
        return (
            Emission(
                SseEvent.DATA,
                {
                    "columns": [_jsonable(c) for c in columns],
                    "rows": _jsonable(payload_extra.get("rows", update.get("result_rows", ()))),
                    "row_count": update.get("row_count", 0),
                    "truncated": bool(update.get("truncated", False)),
                    "amount_unit": _amount_unit(columns),
                },
            ),
        )

    if node == PRESENT:
        present: list[Emission] = []
        chart = update.get("chart_spec")
        if chart:
            chart_map = _mapping(chart)
            present.append(
                Emission(
                    SseEvent.CHART,
                    {
                        "chart_type": chart_map.get("chart_type"),
                        "option": _jsonable(chart_map.get("option")),
                    },
                )
            )
        insight = update.get("insight")
        if insight:
            insight_map = _mapping(insight)
            present.append(
                Emission(
                    SseEvent.INSIGHT,
                    {
                        "text": insight_map.get("text"),
                        "caveats": _jsonable(insight_map.get("caveats", ())),
                        "citations": _jsonable(insight_map.get("citations", ())),
                    },
                )
            )
        # `meta` 恒发（07 §5.6 没有"insight 非空才发 meta"的条件）—— 它是
        # "这一轮用了什么口径"的唯一载体，缺它前端无法解释数字差异。
        present.append(Emission(SseEvent.META, dict(payload_extra.get("meta", {}))))
        return tuple(present)

    if node == AUDIT_SUPP:
        # 07 §5.6：`complete` 在 `audit_supp` 之后。它**不是**出口节点发的 ——
        # 出口三节点走的是 clarify/refuse/error。
        return (Emission(SseEvent.COMPLETE, {}),)

    if node in TERMINAL_EVENT_BY_NODE:
        event = SseEvent(TERMINAL_EVENT_BY_NODE[node])
        return (Emission(event, _terminal_payload(node, update, payload_extra)),)

    # 其余节点（`trusted_context` / `normalize` / `bind` / `gate1_ast` / `gate2_policy` /
    # `execute` / `mask` / `repair`）**按契约不发事件**：
    # · `normalize` 的耗时被算进 `intent`（§5.6 明文的"含 normalize"）；
    # · `bind` / `gate1_ast` / `gate2_policy` / `mask` 在 §5.6 表里没有对应行
    #   （前两者是内部判定，`mask` 的结果经 `data` 一次性下发）；
    # · `execute` 的进度由 `executing` 表达，完成态由 `data` 表达；
    # · `repair` 是**内部重试**（§14.2 C3/E1："无事件"）。
    return ()


def gate_detail(gates: Mapping[Any, Any]) -> dict[str, Any]:
    """按补充契约 **C-02** 构造 `gate_passed.gate_detail`。

    C-02 原文结构：
    `{ast:{passed, rule_id?, reason?}, policy:{passed, rule_id?, reason?},
      cost:{passed, estimated_rows, estimated_cost, decision}}`

    ⚠️ `rule_id` 必须进 `gate_detail`（07 §14.5"闸门拒绝率按 `rule_id` 分组"依赖它）。
    ⚠️ `cost.decision` 保留 `warn`/`skipped` 原值 —— 07 §14.2 D6 明文"**不得报告为通过**"，
    把 `skipped` 折成 `pass` 就是那条禁令要防的事。
    """
    detail: dict[str, Any] = {}
    for gate_no, key in ((GateNo.AST, "ast"), (GateNo.POLICY, "policy"), (GateNo.COST, "cost")):
        result = _mapping(gates.get(gate_no) or gates.get(str(gate_no.value)))
        entry: dict[str, Any] = {
            "passed": bool(result.get("passed", False)),
            "rule_id": result.get("rule_id"),
            "reason": result.get("reason"),
        }
        if gate_no is GateNo.COST:
            decision = result.get("decision")
            entry["decision"] = (
                decision.value if isinstance(decision, GateDecision) else decision
            )
            entry["estimated_rows"] = result.get("estimated_rows")
            entry["estimated_cost"] = _jsonable(result.get("estimated_cost"))
        detail[key] = entry
    return detail


def missing_meta_keys(data: Mapping[str, Any]) -> tuple[str, ...]:
    """`meta` 事件缺哪些必填键（07 §14.3 约束 7）。空元组 = 合规。"""
    return tuple(key for key in _META_REQUIRED_KEYS if data.get(key) is None)


def meta_payload(state: Mapping[str, Any], *, bundle_version: str) -> dict[str, Any]:
    """按 07 §5.6 的 `meta` 行组装载荷（**唯一组装点**）。

    七个键的来源逐条写清 —— 其中**一个是缺口，必须知道**：

    | 键 | 来源 |
    |---|---|
    | `bundle_version` | **入参**：`GraphState` 的 07 §5.2 字段表里**没有**它（组 4 只有 `retrieval_mode`），
      而 §5.6 又要求 `meta` 必带 → 它来自 `RunContext.bundle_version`（`trusted_context` 写入）。
      ⚠️ 这是**契约缺口**：`meta.bundle_version` 无 state 载体。不得为它新增 state 字段
      （§5.2 是穷举的，加字段=造第二份真相），故走上下文。 |
    | `cost_cny` / `tokens` / `latency_ms` | 组 11（`present` / 出口节点写入） |
    | `trace_id` | 组 1 |
    | `scope` | 组 7（gate2 算出）；缺失时按 C-07 缺省语义（`unrestricted` / 不改变披露策略） |
    | `retrieval_mode` | 组 4（C-11：必须如实回填**实际**执行档） |

    ⚠️ C-07 的缺省语义**在这里也要成立**：`scope` 缺失时不填 `None`（那会让
    `missing_meta_keys` 判它缺失、把一轮正常查询记成契约违规），而是填缺省三元组 ——
    这正是 C-07 原文"字段缺失视为 `unrestricted` / `applied=False` / `disclosable=True`，
    **不改变披露策略**"的意思。
    """
    scope = state.get("scope")
    return {
        "bundle_version": bundle_version,
        "cost_cny": _jsonable(state.get("cost_cny", 0)),
        "tokens": _jsonable(state.get("tokens") or {}),
        "latency_ms": _jsonable(state.get("latency_ms") or {}),
        "trace_id": state.get("trace_id"),
        "scope": _jsonable(scope) if scope is not None else _DEFAULT_SCOPE,
        "retrieval_mode": state.get("retrieval_mode"),
    }


#: C-07 的缺省 `scope`（字段缺失时的语义，**不改变披露策略**）。
_DEFAULT_SCOPE: Final[dict[str, Any]] = {
    "level": "unrestricted",
    "applied": False,
    "notice": None,
    "disclosable": True,
}


# ============================================================================
# 发射器
# ============================================================================


class EventRecorder:
    """一次 run 的**发射器 + 契约守卫**（每请求一份，**不得跨请求复用**）。

    ⚠️ 每请求一份不是"优化"，是正确性前提：`_terminal_emitted` 是**流级**状态，
    跨请求复用它会让"上一个请求已发过终态"导致本请求**一个事件都发不出去**。

    ⚠️ `push()` 是**同步**的：`app.llm` / `app.planner` 的降级 sink 是同步回调
    （`on_degraded`），而那里**禁止 `asyncio.run`**（07 §10.2 的接线硬约束）。
    帧入队用 `put_nowait`，故整条链路无需 await。
    """

    __slots__ = (
        "_dropped",
        "_emissions",
        "_encoder",
        "_explain",
        "_log",
        "_monotonic",
        "_queue",
        "_started",
        "_terminal_count",
        "_terminal_emitted",
        "_violations",
    )

    def __init__(
        self,
        *,
        encoder: Encoder,
        explain: bool = True,
        monotonic: Callable[[], float] | None = None,
        maxsize: int = _QUEUE_MAXSIZE,
    ) -> None:
        self._encoder = encoder
        self._explain = explain
        self._monotonic = monotonic or time.perf_counter
        self._started = self._monotonic()
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=maxsize)
        self._emissions: list[Emission] = []
        self._dropped: list[str] = []
        self._violations: list[str] = []
        self._terminal_emitted = False
        self._terminal_count = 0

    # -- 只读视图（契约测试与 API 层读它们） --------------------------------

    @property
    def queue(self) -> asyncio.Queue[bytes | None]:
        """字节帧队列。消费者读到 `None` 即流结束。"""
        return self._queue

    @property
    def emissions(self) -> tuple[Emission, ...]:
        """**已接受**的发射序列（被丢弃的另见 `dropped`）。

        它存在的理由是"恰有 1 个 `terminal:true`"这条 DoD 需要**可断言的对象** ——
        靠遍历字节帧去数会同时考核 JSON 格式，把两件事绑死。
        """
        return tuple(self._emissions)

    @property
    def dropped(self) -> tuple[str, ...]:
        """被守卫丢弃的事件类型（终态之后到达的）。"""
        return tuple(self._dropped)

    @property
    def violations(self) -> tuple[str, ...]:
        """`ui_contract_violation` 的机器可读记录（同时已打 WARN 日志）。"""
        return tuple(self._violations)

    @property
    def terminal_count(self) -> int:
        return self._terminal_count

    @property
    def elapsed_ms(self) -> int:
        return int((self._monotonic() - self._started) * 1000)

    # -- 产出 ---------------------------------------------------------------

    def ack(self, *, task_id: str, session_id: str) -> None:
        """流建立后**立即**发（07 §5.6 第 1 行）。

        ⚠️ 首帧必须尽快带 `task_id`：停止、看门狗、轮询三件事都靠它（HANDOFF §七-7）。
        """
        self.push(Emission(SseEvent.ACK, {"task_id": task_id, "session_id": session_id}))

    def heartbeat(self) -> None:
        """心跳（15s 一次）。它是**唯一**允许在终态之后发出的事件（07 §14.3 约束 3）。"""
        self.push(Emission(SseEvent.HEARTBEAT, {}), after_terminal_ok=True)

    def has_stage_emission(self) -> bool:
        """是否已发出过任何 `stage` 帧（§16.2 占位判定的依据，由 runner 查询）。

        ⚠️ 查询**本记录器**而不是去数节点："`intent` 完成过没有"在合并档下有歧义
        （`intent` 节点可能返回空增量），而"前端见没见过 stage 帧"是**唯一**与
        NFR-1.2（首字节必须有可见变化）对齐的事实。
        """
        return any(emission.stage is not None for emission in self._emissions)

    def stage_placeholder(self) -> None:
        """§16.2 首字节兜底：`stage=intent` **占位帧**（U-66，NFR-1.2 的唯一执行点）。

        语义（HANDOFF §五-6 逐字）：
        - **单次**：调用方（runner）保证只调一次；这里不再防重 —— 防重放在
          "发射决策"层会把"谁负责只发一次"变成两个窗口的共同假设。
        - **不发结论**：载荷只有 `elapsed_ms`（真实经过时间，同 `on_node` 的时钟口径），
          不携带任何 intent 的结论字段 —— 它是进度条的第一段，不是分类结果。
        - **不回退**：真实 `intent` 完成后 `on_node` 照常发带真值的 `stage=intent`；
          前端按段幂等显示，不存在"收回占位"的动作。

        ⚠️ 终态守卫对它生效：占位若在终态后才被调用（竞态），会被 `push` 丢弃 ——
        那正是正确行为（已收口的流不再需要进度占位）。
        """
        self.push(
            Emission(
                SseEvent.STAGE,
                {"elapsed_ms": self.elapsed_ms},
                stage=Stage.INTENT,
            )
        )

    def on_node(self, node: str, update: Mapping[str, Any], *, extras: Mapping[str, Any] | None = None) -> None:
        """节点结束 → 产出其事件序列。

        `elapsed_ms` 一律**从 run 起算**（不是本节点的局部耗时）：`stage=intent` 明确要求
        "含 `normalize`"，而其余 stage 用同一时钟口径，前端进度条才是单调的。
        """
        for emission in emissions_for_node(
            node,
            update,
            elapsed_ms=self.elapsed_ms,
            explain=self._explain,
            extras=extras,
        ):
            self.push(emission)

    def degraded(self, *, reason: Any, action_taken: Any, detail: Mapping[str, Any] | None = None) -> None:
        """降级事件（`DegradedReason` + `ActionTaken`，补充契约 C-08）。

        ⚠️ 它**不是**终止事件（`terminal: false`），且必须在终态**之前**发出（§14.3 约束 4：
        转异步时 `degraded` 在前、`complete` 在后）。终态之后到达的降级会被守卫丢弃 ——
        那不是"漏了"，而是"这轮已经结束了，前端不该再收到状态变更"。
        """
        data: dict[str, Any] = {"reason": str(reason), "action_taken": str(action_taken)}
        if detail:
            data["detail"] = dict(detail)
        self.push(Emission(SseEvent.DEGRADED, data))

    def close(self) -> None:
        """放流结束哨兵（**不是**终止事件：终止事件是 `terminal:true` 的那 4 个）。"""
        try:
            self._queue.put_nowait(_EOF)
        except asyncio.QueueFull:
            # 队列满时哨兵优先级最高（否则消费者永远不返回）。
            self._evict_oldest()
            self._queue.put_nowait(_EOF)

    # -- 守卫（唯一性与顺序的落点） -----------------------------------------

    def push(self, emission: Emission, *, after_terminal_ok: bool = False) -> None:
        """把一个发射决策编码入队。**全部守卫集中在此**（单点 = 可审计）。"""
        if "terminal" in emission.data:
            # fail-closed：调用方不得自行决定 terminal（模块 docstring §一）。
            raise ContractViolationError(
                f"Emission 不得自带 `terminal`（{emission.event.value}）—— 它由 push() 单点注入；"
                f"多处各自设置正是历史病害（有的路径忘带 terminal:true → 前端永远转圈）"
            )

        is_terminal = emission.event in (SseEvent.COMPLETE, SseEvent.CLARIFY, SseEvent.REFUSE, SseEvent.ERROR)

        if self._terminal_emitted and not after_terminal_ok:
            self._drop(emission, "终态之后的事件（07 §14.3 约束 3）")
            return

        if is_terminal:
            if self._terminal_emitted:
                # 第二次终止事件：**丢弃 + 告警**（N-08）。不抛错是刻意的 ——
                # 抛错会把"图有两条出口路径同时跑"变成一个 500，而用户已经拿到过终态了；
                # 丢弃 + 告警保留了可观测性，且不破坏已发出的那条流。
                self._drop(emission, "重复的终止事件（N-08：每条流恰有 1 个 terminal:true）")
                return
            self._terminal_emitted = True
            self._terminal_count += 1

        data: dict[str, Any] = dict(emission.data)
        # `terminal` 由本层注入：终止事件 `True`，其余 `False`（`degraded` 恒 false，§14.3 约束 4）。
        data["terminal"] = is_terminal
        if emission.stage is not None:
            data.setdefault("stage", str(emission.stage))

        if emission.event is SseEvent.META:
            missing = missing_meta_keys(data)
            if missing:
                # 07 §14.3 约束 7 是"契约违规"，但**不阻断**：缺一个键就把整轮打成 error
                # 比让前端拿不到数据更贵。故记违规 + 照发，把判定权交给契约测试（可断言）。
                self._violate(f"meta 事件缺必填键 {list(missing)}（C-07 / C-11）")

        frame = self._encoder(emission.event, data)
        self._emissions.append(emission)
        self._enqueue(frame)

    # -- 内部 ---------------------------------------------------------------

    def _enqueue(self, frame: bytes) -> None:
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            # 队列满 = 消费者跟不上（例如客户端断连但图还在跑）。
            # **终止事件必须送达**：清空队列后放入它（前端至少要拿到"这轮结束了"）。
            # 其余帧丢弃并告警 —— 静默丢失终止事件会让前端永久转圈，比丢中间帧严重得多。
            self._evict_oldest()
            self._violate("SSE 队列已满：丢弃最旧帧以保证新帧入队")
            self._queue.put_nowait(frame)

    def _evict_oldest(self) -> None:
        # 消费者已经把队列取空了（竞态窗口极窄）—— 没有"最旧帧"可丢，不是错误。
        with contextlib.suppress(asyncio.QueueEmpty):
            self._queue.get_nowait()

    def _drop(self, emission: Emission, why: str) -> None:
        self._dropped.append(emission.event.value)
        self._violate(f"丢弃 {emission.event.value}：{why}")

    def _violate(self, detail: str) -> None:
        self._violations.append(detail)
        # `ui_contract_violation` 是 07 §14.3 约束 3 指定的告警名（W5 前端有同款探测器）。
        # ⚠️ 这里只打日志、**不自建指标**：指标本体归 W0/W7（`app/obs/metrics.py` 的准入规则）。
        _log.warning("ui_contract_violation", detail=detail)


# ============================================================================
# 内部工具
# ============================================================================


def _stage_emission(stage: Stage, elapsed_ms: int, extra: Mapping[str, Any]) -> Emission:
    data: dict[str, Any] = {"elapsed_ms": elapsed_ms}
    data.update(extra)
    return Emission(SseEvent.STAGE, data, stage=stage)


def _terminal_payload(node: str, update: Mapping[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    """出口三节点的载荷（07 §5.6 表后三行 + `GraphState` 组 11）。

    ⚠️ 产品文案（`message` / `suggestions[]` / `detail` / `retryable`）有**两个可能来源**：
    · `extras`（runner/端点层，经 `app/api/errors.map_code` 映射 —— `error` 帧的正常来源）；
    · 本节点的**增量**（`refuse_out` 直接把文案放进它的返回值 —— 拒答不走错误码映射）。
    两者都取不到时**如实缺字段**，不编造（U-22）。
    """
    payload: dict[str, Any] = dict(extra)
    for key in ("message", "suggestions", "detail", "retryable"):
        if payload.get(key) is None and update.get(key) is not None:
            payload[key] = _jsonable(update[key])
    if node == CLARIFY_OUT:
        clarify = _mapping(update.get("clarify"))
        payload.setdefault("clarify_id", clarify.get("clarify_id"))
        payload.setdefault("question", clarify.get("question"))
        payload.setdefault("options", _jsonable(clarify.get("options", ())))
        payload.setdefault("reason", clarify.get("reason"))
        return payload
    # `refuse_out` / `error_out`：`reason` 或 `code` 都在 `state.terminal` 里（组 11）。
    terminal = _mapping(update.get("terminal"))
    if node == REFUSE_OUT:
        payload.setdefault("reason", terminal.get("reason"))
        return payload
    if node != ERROR_OUT:  # pragma: no cover - 目前只有三个出口，多一个即为图缺陷
        raise ContractViolationError(
            f"{node} 不是终态出口节点 —— 事件类型无法确定（出口三节点之外的节点不得走本分支）"
        )
    payload.setdefault("code", terminal.get("code"))
    if payload.get("code") is None:
        # `error_out` **必带** `code`（07 §5.6 `error` 行的关键字段）；缺失是图缺陷，
        # 落 `INTERNAL` 兜底（不编一个更"精确"的码 —— 那会让归因指向错误的方向）。
        payload["code"] = "INTERNAL"
    return payload


def _all_gates_clean_pass(gates: Mapping[Any, Any]) -> bool:
    """三闸门**全部** `decision is PASS`（07 §5.6："三闸门**全通过**后"）。

    ⚠️ 判据用 **`decision`** 而不是 `passed`，这是 §14.2 D5/D6 的直接要求：
    · D5（gate3 `warn`，仍执行）—— `passed` 可能为 `True`（不阻断执行），但它**不是通过**；
    · D6（gate3 `skipped`，SQLite 沙箱）—— 原文"**不得报告为通过**"。
    若按 `passed` 判定，`warn`/`skipped` 会被报告为"闸门全过"，正是 D6 要禁的事。
    ⚠️ 缺席的闸门一律判 `False`（`gate_results` 缺一项说明链被跳过 —— N-03 不可跳过）。
    """
    for gate_no in GateNo:
        result = _mapping(gates.get(gate_no) or gates.get(str(gate_no.value)))
        if result.get("decision") is not GateDecision.PASS:
            return False
    return True


def _amount_unit(columns: Sequence[Any]) -> Any:
    """`data.amount_unit`：`result_columns` 中**唯一**的 `unit`。

    ⚠️ 多个不同单位 → `None`（**不猜**）：`amount_unit` 是"整张表的金额单位"，
    混合单位时给任意一个都会让前端把数字标错量级。
    """
    units = {_mapping(c).get("unit") for c in columns}
    units.discard(None)
    return units.pop() if len(units) == 1 else None


def _mapping(value: Any) -> Mapping[str, Any]:
    """尽力把值读成 Mapping（dataclass / pydantic / Mapping 三种形态）。

    ⚠️ 本层**不解释载荷**（G-1）：它只做"能不能读出键"的最小转换，不判断内容对不对。
    读不出就返回空 Mapping —— 让下游按"缺字段"处理，而不是在这里猜。
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    if is_dataclass(value) and not isinstance(value, type):
        dumped_dataclass = asdict(value)
        if isinstance(dumped_dataclass, Mapping):
            return dumped_dataclass
    # `frozen=True, slots=True` 的 dataclass 走上面那条；其余带 `__slots__` 的值对象走这条。
    slots = getattr(value, "__slots__", None)
    if slots:
        return {name: getattr(value, name, None) for name in slots}
    return {}


def _seq(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Sequence):
        return value
    return ()


def _jsonable(value: Any) -> Any:
    """把 dataclass / 枚举 / 嵌套结构转成可 JSON 序列化的形态。

    `api/sse.encode()` 用 `json.dumps` —— 未转换的 dataclass 会在**编码时**抛 TypeError，
    而那时错误发生在 SSE 生成器内部（表现为连接中断），归因极难。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_jsonable(v) for v in value]
    dumped = _mapping(value)
    if dumped:
        return {str(k): _jsonable(v) for k, v in dumped.items()}
    return str(value)
