"""节点 8 `gate1_ast` —— AST 静态审计 + LIMIT 注入 + 默认谓词注入（07 §5.3 行 8）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、被拒时**不覆盖 `sql_text`**（审计证据优先）
--------------------------------------------------------------------------
`run_gate1` 在拒绝时的 `rewritten_sql` 是空串（`_build_reject`）。若照抄回 `sql_text`，
被拒的那条 SQL 就**从 state 里消失了** —— 而它是审计里唯一能回答"模型当时生成了什么"
的一手证据（07 §5.2 组 6 的注释：`sql_text` 持久化供审计）。⇒ 只在**通过**时回写改写后的 SQL。

--------------------------------------------------------------------------
二、`allowlist` 的来源只有一处：`guard_allowlist`（闸门唯一形状）
--------------------------------------------------------------------------
`run_gate1(sql, allowlist)` 的 `allowlist` 是 gate1 的**全部判据**（白名单表、默认谓词、
`deny_columns`、常量表、生效 LIMIT）。它**只能**由 `SemanticBundlePort.guard_allowlist(ctx, max_rows=…)`
产出（`contracts.GuardAllowlist`，8 键 wrapper —— W72-3 起增 `metric_predicates`；
U-121 裁定"两个投影、两种形状"）。
⚠️ 扁平的 `asset_allowlist(ctx)` 是 planner / binding 的**可见面**，按设计**不得**喂闸门 ——
把它喂进来 `assets` 键取不到 ⇒ 普通 SQL 必被 R05 拒（那正是 `U-121` 的病害，不是预期行为）。
⚠️ 与 gate2 各自取一次：两次调用是**刻意**的 —— 判据按身份现算，共用一份变量会让
"gate2 复核"变成"复核自己刚给的那份"（失去二次校验的意义）。gate2 侧的取用点归 W2C。

--------------------------------------------------------------------------
三、不触发 repair（§5.4 明文）
--------------------------------------------------------------------------
结构性拒绝（多语句 / 非 SELECT / 注释注入…）**重试无意义** ⇒ 直接 `error(GATE_AST_REJECTED)`。
`route_after_gate1` 会读 `gate_results[AST].passed` 决定去向；本节点的终态写在
"拒绝"分支上，两条路互斥且都由**本节点**给出结论（判定只有一处）。

--------------------------------------------------------------------------
四、指标窗口强制（W75-1）在**本节点**做，理由有二
--------------------------------------------------------------------------
① `repair` 重新出 SQL 后**也回到本节点**（`build.py:828`）⇒ 这里是所有待执行 SQL 的
   唯一收口点；放在 `gen_sql` 会漏掉 repair 生成的 SQL。
② 必须在 `run_gate1` **之前**改写：R14 字面量与列白名单审计的对象应是**最终** SQL。
   补/修的上界一律走绑定参数（`app/guard/metric_window.py`），不产生新字面量。
无法强制的窗口 ⇒ `refuse(no_data_asset)` + `reason_code=metric_window_unenforceable`
（fail-closed；派单 §96.8 明令「不得静默忽略」）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.core.contracts import GuardAllowlist
from app.core.enums import ErrorCode, GateNo, LatencyKey, Outcome, RefuseReason
from app.graph.nodes._shared import (
    deps_of,
    gate_update,
    identity_of,
    node_latency,
    terminal_update,
)
from app.graph.state import GraphState
from app.guard import run_gate1
from app.guard.metric_window import (
    MetricWindowError,
    MetricWindowRule,
    WindowEnforcement,
    enforce_metric_windows,
)

__all__ = ["gate1_ast"]

_LOG = logging.getLogger(__name__)


async def gate1_ast(state: GraphState) -> dict[str, Any]:
    """gate1：静态审计（纯函数，W2C）+ 指标窗口强制（W75-1）。"""
    deps = deps_of()
    identity = identity_of(state)
    sql = str(state.get("sql_text") or "")
    params: Mapping[str, Any] = _sql_params(state) or {}
    allowlist: GuardAllowlist = deps.semantics.guard_allowlist(
        identity, max_rows=_request_max_rows(state)
    )

    windowed: WindowEnforcement | None = None
    rules = _metric_window_rules(state, deps.semantics)
    if rules:
        try:
            windowed = enforce_metric_windows(sql, params, rules)
        except MetricWindowError as exc:
            _LOG.warning(
                "metric window unenforceable (fail-closed): code=%s detail=%s",
                exc.code, exc.detail,
            )
            update = terminal_update(
                state,
                event="refuse",
                outcome=Outcome.REFUSE,
                reason=RefuseReason.NO_DATA_ASSET.value,
            )
            update["intent_detail"] = {
                "reason_code": "metric_window_unenforceable",
                "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
                "metric_window_error": exc.code,
                "metric_window_detail": exc.detail,
            }
            return update
        if windowed.changed:
            _LOG.info("metric window enforced: %s", "; ".join(windowed.applied))
            sql = windowed.sql
            params = windowed.params

    with node_latency(LatencyKey.GATE):
        report = run_gate1(
            sql, allowlist, metrics=_metric_names(state), params=params
        )

    update: dict[str, Any] = dict(gate_update(state, GateNo.AST, report.gate_result))
    if report.gate_result.passed:
        update["sql_text"] = report.rewritten_sql
        if windowed is not None and windowed.changed:
            #: 补/修出来的上界走绑定参数（N-04）⇒ 参数表必须与 SQL 同批落盘。
            update["sql_params"] = dict(params)
        update["limit_injected"] = (
            dict(report.limit_injected) if report.limit_injected is not None else None
        )
        update["applied_predicates"] = tuple(report.applied_predicates)
        return update

    # 被拒：保留原始 SQL（见模块 docstring §一），只写终态。
    update.update(
        terminal_update(
            state,
            event="error",
            outcome=Outcome.FAILED,
            code=ErrorCode.GATE_AST_REJECTED.value,
        )
    )
    return update


def _request_max_rows(state: GraphState) -> int | None:
    """`GuardAllowlist["max_rows"]` 的送货面（U-121 判据④）：**只认请求级值**。

    来源 = `state["options"]["max_rows"]`（`api/dto/query.AskOptions`，`state.py:465` 写入）。
    ⚠️ **不得**拿 `deps.max_rows`（= `EXEC_MAX_ROWS`）冒充 —— 两者可能不同，填进去就是造数字（U-22）。
    options 缺失或值非 `int` ⇒ 照实 `None`（本键"必在"≠"必非空"；clamp 由 `ast_gate._effective_limit` 做）。
    """
    options = state.get("options")
    if not isinstance(options, Mapping):
        return None
    value = options.get("max_rows")
    return value if isinstance(value, int) else None


def _metric_names(state: GraphState) -> tuple[str, ...]:
    """本次计划声明的指标名（去重保序）—— 谓词按指标收窄的入口（W72-3 / R31bq）。

    来源 = `state["plan"].metrics[].name`（`planner/schemas.Plan`；`bind` 读的是
    `plan.metrics[0].name`，这里取**全部**）。计划缺失 / 非结构化 ⇒ 返回空元组 ⇒
    `ast_gate._inject_predicates` 回落域级谓词（保持旧行为，不放松）。
    """
    plan = state.get("plan")
    metrics: Any = getattr(plan, "metrics", None)
    if metrics is None and isinstance(plan, Mapping):
        metrics = plan.get("metrics")
    names: list[str] = []
    for item in metrics or ():
        name = getattr(item, "name", None)
        if name is None and isinstance(item, Mapping):
            name = item.get("name")
        if name and str(name) not in names:
            names.append(str(name))
    return tuple(names)


def _sql_params(state: GraphState) -> Mapping[str, Any] | None:
    """该 SQL 的绑定参数（`state["sql_params"]`，`planner/engine.py:538` 写入）。

    只给闸门的矛盾守卫解析 `%(name)s` 用（W73-1）；非 `Mapping` ⇒ `None`
    ⇒ 占位符一律按「解析不出」处理（保守跳过同列 `=`/`<>` 候选，不放松其它谓词）。
    """
    params = state.get("sql_params")
    return params if isinstance(params, Mapping) else None


def _metric_window_rules(state: GraphState, semantics: Any) -> tuple[MetricWindowRule, ...]:
    """本次计划里**声明了 window** 的指标（W75-1）。

    来源 = 语义包 `Metric.window` / `Metric.time_basis`。`metric()` 不在
    `SemanticBundlePort` 的五方法里 ⇒ 按 `payloads.py` 的既有约定做**可选能力探测**：
    取不到就返回空元组（评测夹具之外的生产/评测路径都持有真运行时）。
    """
    lookup = getattr(semantics, "metric", None)
    if not callable(lookup):
        return ()
    rules: list[MetricWindowRule] = []
    for name in _metric_names(state):
        metric = lookup(name)
        if metric is None:
            continue
        window = getattr(metric, "window", None)
        if not window:
            continue
        rules.append(
            MetricWindowRule(
                metric=name,
                time_basis=str(getattr(metric, "time_basis", "") or ""),
                window=str(window),
            )
        )
    return tuple(rules)
