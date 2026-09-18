"""节点 11 `execute` —— 受控执行（07 §5.3 行 11 / §8）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、结果行**不进 state**：三层理由，缺一条都不足以否决
--------------------------------------------------------------------------
1. 07 §5.2.1 把 `result_rows` 列为体积字段（只留 `result_ref`）；
2. 结果行是**单次 I/O 的临时物**，进检查点等于每次节点切换写一遍（R-10 的第一大事故形态）；
3. 未脱敏的行**不能进 Redis**（N-05），而"确定已脱敏"的时刻在 `mask` 之后
   ⇒ 缓存写入（`result:{tenant}:{task_id}`）安排在 `mask` 节点，本节点只做**内存**交接
   （`RunContext.hold_rows`），并在 state 里留 `result_columns` / `row_count` /
   `truncated` / `result_fingerprint`（都是小标量）。

--------------------------------------------------------------------------
二、失败**不由本节点定终态**（除 `permission` 一条）
--------------------------------------------------------------------------
`route_after_execute` 已经承担了"可修 → repair / 不可修 → error_out"的判定
（读 `app.exec.REPAIRABLE_CLASSES`）。若本节点也判一遍，就有两个判据来源 ——
它们漂移的表现是"节点认为该修、边认为该报错"，而两边都不报错，只是行为不一致。

⇒ 本节点只写 `exec_error`（脱敏摘要，N-11），让边去路由；**唯一例外是 `permission`**：
W2D 明确"它的终态是 `refuse(out_of_scope)`（产品结论），落到 `error` 就错了"，
而条件边无法从 `exec_error` 反推出"该发 refuse 还是 error"（`route_after_execute`
只认'可修/不可修'）⇒ 这条结论只能在这里落进 `state.terminal`。

--------------------------------------------------------------------------
三、`effective_limit` 在 P0 **恒 None**（载体缺失，登记）
--------------------------------------------------------------------------
`fetch(..., effective_limit=...)` 给了它，`truncated` 才按 §8.6 原文判定
（行数 == 生效 LIMIT）；不给则退化为"取到 max_rows 仍有余量"。
而生效 LIMIT **拿不到**：`gate1` 的 `limit_injected` 只给 `injected`/`original_limit`，
注入值 L（= `min(allowlist.max_rows, 10000)`）在 `ast_gate._effective_limit` 内部用完即弃。
⇒ 传 `None`（退化口径），**不**拿 `deps.max_rows` 冒充它（两者可能不同 —— 那会是造数字，U-22）。
缺口已登记：请 W2C 把 L 一并放进 `limit_injected`。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import LatencyKey, Outcome, RefuseReason
from app.exec import ExecFailure
from app.graph.nodes._shared import (
    deps_of,
    identity_of,
    node_latency,
    rc,
    terminal_update,
)
from app.graph.state import GraphState
from app.obs.logging import get_logger

__all__ = ["execute"]

_log = get_logger(__name__)


async def execute(state: GraphState) -> dict[str, Any]:
    """受控执行 → 组 8（不含 `result_rows`，见 docstring §一）。"""
    context = rc()
    deps = deps_of()
    identity = identity_of(state)
    sql = str(state.get("sql_text") or "")
    params = dict(state.get("sql_params") or {})

    try:
        with node_latency(LatencyKey.EXEC):
            result = await deps.executor.fetch(
                sql,
                params,
                identity,
                max_rows=deps.max_rows,
                statement_timeout_ms=deps.statement_timeout_ms,
                effective_limit=_effective_limit(state),
            )
    except ExecFailure as exc:
        return _on_failure(state, exc)

    # 行经内存交给 `mask`（未脱敏行不进 Redis / 不进检查点，见 docstring §一）。
    context.hold_rows(result.rows)
    return {
        "result_columns": result.columns,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "result_fingerprint": result.fingerprint,
        # ⚠️ 成功必须清掉上一轮失败残留：repair 循环里本节点会被二次进入，
        # 若不清，`route_after_execute` 读到旧 `exec_error` 会把成功误判成
        # 失败并继续 repair 直到超限（实测 §14.2 C3：终态 error 而非 complete）。
        "exec_error": None,
    }


def _on_failure(state: GraphState, exc: ExecFailure) -> dict[str, Any]:
    """执行失败 → 脱敏摘要（N-11）+ 只在 `permission` 时定终态（见 docstring §二）。"""
    error = exc.error
    update: dict[str, Any] = {
        "exec_error": {
            "error_class": error.error_class,
            "pgcode": error.pgcode,
            # ⚠️ 只放类别级文案：`ExecError.message` 已由 W2D 保证不含原始库文本（N-11）。
            "message": error.message,
            # `repair` 的**唯一**输入提示（N-11 的回灌面）——W2D 明文"不要自己再造提示语"。必须带走。
            "llm_hint": error.llm_hint,
        }
    }
    if error.error_class == "permission":
        update.update(
            terminal_update(
                state,
                event="refuse",
                outcome=Outcome.REFUSE,
                reason=RefuseReason.OUT_OF_SCOPE.value,
            )
        )
    else:
        # 记录一次（可修类会在 `repair` 里被消费；不可修类由 `error_out` 映射成错误码）。
        _log.info(
            "exec_failed",
            outcome="routed",
            task_id=str(state.get("task_id")),
            error_class=error.error_class,
            extra_fact="可修类 → repair；不可修类 → error_out（码由 error_out 唯一映射，见其 docstring）",
        )
    return update


def _effective_limit(state: GraphState) -> int | None:
    """生效 LIMIT。**P0 恒 `None`** —— 载体缺失，如实登记（不猜）。

    `gate1` 的 `limit_injected` 只有两种形状：`None`（原 LIMIT ≤ L，保留）或
    `{"injected": bool, "original_limit": int|"NULL"}`。**注入值 L 本身不在里面**
    （它在 `ast_gate._effective_limit(allowlist)` 内部算完就用掉了，没有出口），
    而 `L` 依赖 **allowlist 的** `max_rows`（≠ `GraphDeps.max_rows`，两者可能不同）
    ⇒ 在本节点复算 L 需要再取一次 `asset_allowlist`，且要 import 私有函数；两者都不做。

    后果如实说明：`truncated` 走 executor 的**退化口径**（"取到上限仍有余量"），
    在"SQL 自带 LIMIT 恰好等于行数"的边界上与 §8.6 的原文口径可能差一。
    需 W2C 把 L 一并放进 `limit_injected`（或给出公开取值函数）—— 已写进本窗口 RELAY。
    """
    return None
