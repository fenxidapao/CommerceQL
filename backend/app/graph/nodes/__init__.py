"""16 个主节点 + 3 个终态出口 —— **节点名的唯一来源**（07 §5.3 节点契约表）。

层号：L4｜归属窗口：W4（`docs/08 §4.1`：`app/graph/**` 全部独占）。

--------------------------------------------------------------------------
一、为什么节点名要先在这里集中定义，而不是散在各节点文件里
--------------------------------------------------------------------------
节点名同时被**四处**引用：图的 `add_node` / 条件边的返回值 / `events.py` 的「哪个节点发哪个事件」
映射 / 契约测试的覆盖断言。若各写一遍字面量，改名时必然漏一处 ——
而漏掉的那处**不会报错**：LangGraph 只在 `add_edge` 时校验目标存在，
条件边返回一个未注册的名字会在**运行时**才炸（且只在走到那条分支时）。

所以：本文件是节点名的唯一真相，其余三处一律 `import` 常量。

--------------------------------------------------------------------------
二、与 07 §5.3 的行号对应（对账用，勿改语义）
--------------------------------------------------------------------------
| 07 §5.3 行 | 节点 | 本文件常量 |
|---|---|---|
| 1 | `trusted_context` | `TRUSTED_CONTEXT` |
| 2 | `normalize` | `NORMALIZE` |
| 3 | `intent` | `INTENT` |
| 4 | `link` | `LINK` |
| 5 | `plan` | `PLAN` |
| 6 | `bind` | `BIND` |
| 7 | `gen_sql` | `GEN_SQL` |
| 8 | `gate1_ast` | `GATE1_AST` |
| 9 | `gate2_policy` | `GATE2_POLICY` |
| 10 | `gate3_cost` | `GATE3_COST` |
| 11 | `execute` | `EXECUTE` |
| 12 | `mask` | `MASK` |
| 13 | `audit_pre` | `AUDIT_PRE` |
| 14 | `present` | `PRESENT` |
| 15 | `audit_supp` | `AUDIT_SUPP` |
| 16 | `repair` | `REPAIR` |
| 17（**一行三节点**） | `clarify_out` / `refuse_out` / `error_out` | `CLARIFY_OUT` / `REFUSE_OUT` / `ERROR_OUT` |

⚠️ 07 §5.3 的第 17 行写了**三个**具名出口 —— 它们是三个独立节点（不是"一个出口节点三种行为"）：
条件边按失败类型分别指向其中一个，而"恰有 1 个终止事件"由它们各自单向收口（N-08）。
把它合成一个节点会让"哪条路径设了终态"在图上不可见，而 `route_terminal` 的幂等判据正是靠这个。
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ALL_NODE_NAMES",
    "AUDIT_PRE",
    "AUDIT_SUPP",
    "BIND",
    "CLARIFY_OUT",
    "EXECUTE",
    "GATE1_AST",
    "GATE2_POLICY",
    "GATE3_COST",
    "GEN_SQL",
    "INTENT",
    "LINK",
    "MAIN_NODE_COUNT",
    "MAIN_NODE_NAMES",
    "MASK",
    "NORMALIZE",
    "PLAN",
    "PRESENT",
    "REFUSE_OUT",
    "REPAIR",
    "TERMINAL_EVENT_BY_NODE",
    "TERMINAL_NODE_NAMES",
    "TRUSTED_CONTEXT",
    "ERROR_OUT",
]

# ---------------------------------------------------------------------------
# 16 个主节点（顺序 = 07 §5.3 表序，**不代表运行顺序**）
# ---------------------------------------------------------------------------

TRUSTED_CONTEXT: Final[str] = "trusted_context"
NORMALIZE: Final[str] = "normalize"
INTENT: Final[str] = "intent"
LINK: Final[str] = "link"
PLAN: Final[str] = "plan"
BIND: Final[str] = "bind"
GEN_SQL: Final[str] = "gen_sql"
GATE1_AST: Final[str] = "gate1_ast"
GATE2_POLICY: Final[str] = "gate2_policy"
GATE3_COST: Final[str] = "gate3_cost"
EXECUTE: Final[str] = "execute"
MASK: Final[str] = "mask"
AUDIT_PRE: Final[str] = "audit_pre"
PRESENT: Final[str] = "present"
AUDIT_SUPP: Final[str] = "audit_supp"
REPAIR: Final[str] = "repair"

MAIN_NODE_NAMES: Final[tuple[str, ...]] = (
    TRUSTED_CONTEXT,
    NORMALIZE,
    INTENT,
    LINK,
    PLAN,
    BIND,
    GEN_SQL,
    GATE1_AST,
    GATE2_POLICY,
    GATE3_COST,
    EXECUTE,
    MASK,
    AUDIT_PRE,
    PRESENT,
    AUDIT_SUPP,
    REPAIR,
)

#: 16 —— `tests/graph_snapshot/` 与 §5.3 的对账断言读它。
MAIN_NODE_COUNT: Final[int] = len(MAIN_NODE_NAMES)

# ---------------------------------------------------------------------------
# 3 个终态出口（07 §5.3 第 17 行）
# ---------------------------------------------------------------------------

CLARIFY_OUT: Final[str] = "clarify_out"
REFUSE_OUT: Final[str] = "refuse_out"
ERROR_OUT: Final[str] = "error_out"

TERMINAL_NODE_NAMES: Final[tuple[str, str, str]] = (CLARIFY_OUT, REFUSE_OUT, ERROR_OUT)

ALL_NODE_NAMES: Final[tuple[str, ...]] = MAIN_NODE_NAMES + TERMINAL_NODE_NAMES

#: 终态出口节点 → 它发出的终止事件（07 §5.6 表后三行）。
#:
#: ⚠️ `complete` **不在**这里：它不是出口节点发的，而是 `audit_supp` 走完后由
#: `events.py` 发出（07 §5.6："`complete` | `audit_supp` 之后"）。
#: 把"出口节点"与"终止事件"的对应关系写成一张表，是为了让
#: `events.py` 不再第二遍判断"该发哪个终态"——那是同一个事实的第二次编码。
TERMINAL_EVENT_BY_NODE: Final[dict[str, str]] = {
    CLARIFY_OUT: "clarify",
    REFUSE_OUT: "refuse",
    ERROR_OUT: "error",
}
