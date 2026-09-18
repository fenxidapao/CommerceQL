"""节点 12 `mask` —— 结果脱敏（07 §5.3 行 12，**唯一出口**）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、为什么"executor 已经脱过敏了"本节点还要再过一遍（三条理由，缺一条就不该有它）
--------------------------------------------------------------------------
`PgSqlExecutor.fetch` 在 `_execute_and_collect` 里已经 `self._mask.apply(...)`
（`ResultSet` 的 docstring：`rows` **已完成脱敏**）。那本节点是不是冗余？不是，有三件事
**只有在本节点做**才对：

| 要什么 | 为什么不能省 |
|---|---|
| **`pii_columns_hit`**（§5.3.1 段 1 审计的必填列） | `MaskOutcome.hit_columns` 在 executor 内部被丢掉了（`ResultSet` 五字段里没有它）⇒ 只有重算一次才拿得到 |
| **fail-closed 的落点**（§5.3 行 12） | 脱敏失败必须 `error(INTERNAL)` 且**不给出任何行**。这在图里需要一个**节点**来承载（节点才能设终态） |
| **脱敏与缓存的顺序**（N-05） | 未脱敏行不得进 Redis。缓存写在**脱敏之后**这件事必须在图里可见 |

▶ 重算一次是**安全**的：`apply_rule` 对五个 pii 标签都幂等（已实测：`once == twice`，
手机号/邮箱/身份证/地址/姓名五个标签全过），不会二次打码。

--------------------------------------------------------------------------
二、policy 的组装在这里**第二次**出现（登记）
--------------------------------------------------------------------------
policy 形状 = `{"columns": [{"name": n, "sensitivity": None}], "mask_rules": [...]}`
—— executor 的 `_mask_policy` 组装过一份（私有方法，无公开出口）。
⇒ 本节点是**第二个组装点**。两处必须同形，而"必须同形"是纪律不是机制。
登记为耦合项：请 W2D 把 policy 组装提成公开函数（或本节点改为消费 `MaskPort` 的公开入口）。
⚠️ 同时如实说明 P0 的边界（W2D RELAY §3）：`sensitivity` 恒 `None` ⇒ **只有
语义包 `mask_rules` 正则路径生效**，语义包里 `sensitivity` 标注的列不会被掩码。

--------------------------------------------------------------------------
三、结果缓存写在**这里**（脱敏之后），且是 best-effort
--------------------------------------------------------------------------
`result:{tenant}:{task_id}`（TTL 1h）是异步/重放路径的载体；P0 的异步路径**不可达**
（缺预估延迟载体，见 `edges.py` §二-4）⇒ 写失败只告警、不阻断，`result_ref` 缺失
不会影响本次下发。**不假装写成功**（日志 `result_cache_write_failed`）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.contracts import ColumnMeta
from app.core.enums import ErrorCode, Outcome
from app.graph.context import RunContext
from app.graph.nodes._shared import deps_of, rc, terminal_update
from app.graph.state import GraphState
from app.mask import MaskFailed
from app.obs.logging import get_logger

__all__ = ["mask"]

_log = get_logger(__name__)

#: 结果集缓存 TTL（07 §5.2 组 8：`result_rows` 脱敏后存 Redis，TTL 3600s）。
_RESULT_TTL_S: int = 3600


async def mask(state: GraphState) -> dict[str, Any]:
    """脱敏（fail-closed）→ 移交 `audit_pre` + 写结果缓存。"""
    context = rc()
    deps = deps_of()
    rows = context.take_rows()

    columns: tuple[ColumnMeta, ...] = tuple(state.get("result_columns") or ())
    try:
        outcome = deps.mask.apply(rows, _policy_for(context, columns))
    except MaskFailed as exc:
        # fail-closed（§5.3 行 12 原文："宁可不给，不给明文"）——**不**把行交给下游。
        _log.error(
            "mask_failed",
            outcome="fail_closed",
            task_id=str(state.get("task_id")),
            error_type=type(exc).__name__,
            extra_fact="脱敏失败 → 不下发任何行（N-05）",
        )
        return terminal_update(
            state,
            event="error",
            outcome=Outcome.FAILED,
            code=ErrorCode.INTERNAL.value,
        )

    # 脱敏后的行回到内存通道，交给 `audit_pre`/runner 发 `data`（未脱敏行从未离开本进程）。
    context.hold_rows(outcome.rows)
    context.hold_mask_hits(outcome.hit_columns)

    result_ref = await _write_result_cache(context, state, outcome.rows, columns)
    return {"result_ref": result_ref} if result_ref else {}


def _policy_for(context: RunContext, columns: tuple[ColumnMeta, ...]) -> dict[str, Any]:
    """组装 `MaskPort` 的 policy（见模块 docstring §二：这是第二个组装点）。"""
    bundle_policy: Mapping[str, Any] = context.deps.semantics.policy() or {}
    return {
        # `sensitivity` 恒 None（P0 边界，同 executor._mask_policy 的注释）。
        "columns": [{"name": col.name, "sensitivity": None} for col in columns],
        "mask_rules": list(bundle_policy.get("mask_rules", ()) or ()),
    }


async def _write_result_cache(
    context: RunContext,
    state: GraphState,
    rows: tuple[tuple[Any, ...], ...],
    columns: tuple[ColumnMeta, ...],
) -> str | None:
    """脱敏后写 `result:{tenant}:{task_id}`（§11）。失败只告警，见 docstring §三。"""
    cache = context.deps.result_cache
    if cache is None:
        return None
    import orjson

    from app.cache.keys import result_set  # 局部：键构造函数只能有一处（§11.2 硬规则 3）

    key = result_set(str(state["tenant_id"]), str(state["task_id"]))
    payload = {
        "columns": [col.name for col in columns],
        "rows": rows,
        "row_count": int(state.get("row_count", len(rows))),
        "truncated": bool(state.get("truncated", False)),
        "fingerprint": state.get("result_fingerprint"),
    }
    try:
        # `default=str`：Decimal/date 之类非 JSON 原生标量退回字符串。
        # 缓存是**旁路**（异步/重放用），本次下发的帧才是这一轮数据的唯一真相。
        await cache.set(key, orjson.dumps(payload, default=str).decode(), ttl_s=_RESULT_TTL_S)
    except Exception as exc:
        _log.warning(
            "result_cache_write_failed",
            outcome="non_blocking",
            task_id=str(state.get("task_id")),
            error_type=type(exc).__name__,
        )
        return None
    return key
