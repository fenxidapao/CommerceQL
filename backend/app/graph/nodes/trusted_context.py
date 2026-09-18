"""节点 1 `trusted_context` —— 身份就位检查 + 语义包版本固定（07 §5.3 行 1）。

层号：L4｜归属窗口：W4。

--------------------------------------------------------------------------
一、本节点为什么"几乎什么都不做"（而这正是它存在的意义）
--------------------------------------------------------------------------
07 §5.3 行 1 写"由 JWT 构造**不可变**身份上下文" —— 但本项目把这一步**前移到了 API 层**：
`graph/state.py::initial_state(identity, ...)` 只接受由 `app/auth` 验签得到的
`IdentityContext`，且 07 §13.1 的禁令 1/2 明令"身份不得由客户端影响"。
若把 JWT 解析放进图里，它会发生在**已经产生 checkpoint 之后**（非法请求会留下中间态），
且给了"某一轮从 state 里改 tenant_id"的可能（state 是 dict，不是 frozen 值对象）。

⇒ 本节点做三件在图内才有意义的事：

1. **就位自检**：组 1 的 8 个身份字段必须全部在位。缺一个（例如 API 层忘了走
   `identity_fields()`）时，后续任一服务调用都会拿不到租户 —— 而那个错误会**远在
   出事点之后**才体现（例如 gate2 判 scope 时）。在这里 fail-fast，错误信息才指得准。
2. **固定语义包版本**（07 §5.7 的"固定时机 = 会话首次成功调用"）：`meta.bundle_version`
   是必填（§5.6），而 `GraphState` 的 §5.2 字段表里**没有**这个键 ⇒ 它只能落在
   `RunContext.bundle_version`（见 `events.meta_payload` 的表）。
   ⚠️ 本节点只取**当前激活版本**；"同一 `session_id` 内全程沿用旧版本"需要
   `session.pinned_versions`（表在 W1B），而 `GraphDeps` 里**没有** `RepositoryPort`
   ⇒ 会话级版本固定的**读写两侧都没有接线**。已登记缺口（见模块 docstring §三）。
3. **写 `scope` 的缺省依据**：不写。gate2 才是 scope 的确定性来源（§7.4），
   `events.meta_payload` 在它缺席时用 C-07 的缺省语义 —— 两处都不猜。

--------------------------------------------------------------------------
二、为什么返回空增量而不是"把身份再写一遍"
--------------------------------------------------------------------------
`GraphState` 组 1 的写入出口是 `identity_fields()`（唯一转换点）。本节点若"顺手回写"
一遍，就制造了第二个写入点，而两个写入点的差异在 `resume` 语义下无法区分
（`state.py` 明令组 1 "之后只读"）。⇒ 返回 `{}`。

--------------------------------------------------------------------------
三、缺口登记（不在 P0 解决，但必须写清）
--------------------------------------------------------------------------
| 缺口 | 影响 | 归属 |
|---|---|---|
| 会话级版本固定（§5.7）需要 `RepositoryPort.get_session/save_task` | 同会话跨轮次的 `bundle_version` 可能漂移 —— 而 §5.7 说这正是"用户无法解释差异"的信任崩塌点 | 需装配层补 `RepositoryPort`（W1B 有实现，`GraphDeps` 未收） |
| `GRAPH_VERSION`（§5.7 的 `graph_version`）也无 state 载体 | 同上 | 与 `bundle_version` 同款处理（进 `RunContext`） |
"""

from __future__ import annotations

from typing import Any, Final

from app.core.errors import ContractViolationError
from app.graph.nodes._shared import deps_of, identity_of, rc
from app.graph.state import REQUIRED_STATE_FIELDS, GraphState

__all__ = ["trusted_context"]

#: 组 1 里**允许缺席**的两个字段 —— 它们是可选请求体，`initial_state()` 在 `None` 时
#: **刻意不写键**（该函数 docstring 的原话："字段存在但为 `None`"与"字段不存在"
#: 在 `resume` 语义下不同）。
#:
#: 🔴 为什么必须显式列出而不是靠 `state.get(f) is None` 判定：
#: `REQUIRED_STATE_FIELDS` 是组 1 **全集**（11 个，`STATE_GROUPS` 的原文如此），
#: 其中 `options` / `idempotency_key` 在 `initial_state()` 里是**条件写入**。
#: 早期版本用 `state.get(f) is None` 判缺 ⇒ **本产品自己的官方构造器造出的状态
#: 过不了本节点的自检**（实测 `missing=['idempotency_key','options']`）——
#: 即整张图从入口就起不来。这是"合取判定盖过了定义域"的典型错法：
#: "必须就位"对 8 个身份字段成立，对那两个可选请求体**不成立**。
#:
#: ⚠️ 与之配套的"名义与实现不一致"已登记（**改 `state.py` 需要 W1B/架构点头**，
#: 本窗口只提需求）：`state.py` 第 234 行把 `REQUIRED_STATE_FIELDS` 注释为
#: "必须在 `initial_state()` 中就位" —— 对这两个键而言该描述为假。
_OPTIONAL_AT_ENTRY: Final[frozenset[str]] = frozenset({"options", "idempotency_key"})

#: 自检只认"组 1 里**必须**在位的那些"；判定用**键是否在场**（`in`）而非值是否非空 ——
#: `role` 之外的值型字段合法地可能是空串/空元组（`scope_claims=()` / `shop_ids=()`），
#: 用 `is None` 会把"合法的空"和"没写"混成一类。
_EXPECTED_AT_ENTRY: Final[frozenset[str]] = REQUIRED_STATE_FIELDS - _OPTIONAL_AT_ENTRY


async def trusted_context(state: GraphState) -> dict[str, Any]:
    """就位自检 + 固定 `bundle_version`（07 §5.3 行 1）。"""
    missing = sorted(f for f in _EXPECTED_AT_ENTRY if f not in state)
    if missing:
        raise ContractViolationError(
            "图入口缺少身份字段 —— API 层没有走 `state.initial_state(identity, ...)` "
            "（或用了裸 dict 构造初始状态）。身份字段缺一个就会让某个下游节点拿不到租户，"
            "而跨租户场景下那是**安全**问题，故在此 fail-fast。",
            detail={"missing_identity_fields": missing},
        )

    # 反序列化一次身份（不为取值，只为"转换器本身可用"这件事在最早处被验证）。
    identity_of(state)

    context = rc()
    semantics = deps_of().semantics
    active_version = semantics.active_version()
    if not active_version:
        raise ContractViolationError(
            "语义包 `active_version()` 为空 —— 版本固定是审计前提（07 §5.7 / `query_plan.bundle_version` 为 NOT NULL）",
            detail={"active_version": active_version},
        )
    context.bundle_version = str(active_version)
    return {}
