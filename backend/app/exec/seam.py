"""exec 入口形态 —— **图真正调用的那两面**的显式声明（供契约/单元测试消费）。

层号：L2｜归属窗口：W2D（`docs/08 §4.1`：`app/exec/**`）。

--------------------------------------------------------------------------
一、为什么需要这个文件（根因，不是洁癖）
--------------------------------------------------------------------------
`core/contracts.py::SqlExecutorPort`（W0，阶段 0 冻结）**只声明 `fetch`**，且只有
`max_rows` / `statement_timeout_ms` 两个关键字 —— **没有 `explain`**。

而图实际调用的是：

| 调用方 | 调用 | 端口有没有授权 |
|---|---|---|
| `app/graph/nodes/execute.py` | `deps.executor.fetch(..., effective_limit=...)` | ❌ 端口没这个关键字 |
| `app/graph/nodes/gate3_cost.py` | `rich_method(deps.executor, "explain", ...)`（U-63） | ❌ 端口没这个方法 |

且这条缝**在类型层完全不检查**：`app/graph/nodes/_shared.deps_of() -> Any` ⇒
`deps` 是 `Any`，mypy 看不见上面两个调用；`rich_method` 在运行期**只查"这个名字是否
callable"**，不查签名、不查返回。

⇒ **没有任何一层声明"gate3 / execute 需要 exec 提供什么"**。两个可测后果：

1. 契约测试里要造替身，只能去**读调用点抄签名**；抄错了**不会红**
   （`rich_method` 放行、Python 参数不匹配只在真的调到那一行时才炸）。
2. `isinstance(fake, SqlExecutorPort)` 对"缺 `explain` 的替身"**照样为真**
   （端口本来就没有这个方法）⇒ 这个检查**不足以**证明图能跑到底。

本文件把这条缝**显式声明**出来，让实现与替身都必须对齐同一份形状。
⚠️ **它不改端口**（端口是 W0 的冻结面）：只把"图实际要求的面"写在实现侧。

--------------------------------------------------------------------------
二、仓库里已有的三个 `explain` 实现（同一方法、无人被迫对齐）
--------------------------------------------------------------------------
| 实现 | 位置 | "方言不支持" 怎么表达 |
|---|---|---|
| `PgSqlExecutor` | `app/exec/executor.py` | **不存在这一态**（PG 永远支持 FORMAT JSON）；失败即抛 |
| `SqliteEvalExecutor` | `eval/sqlite_exec.py`（**继承**上者并覆盖） | 返回 `None` |
| `ScriptExecutor` | `tests/contract/_fullchain_deps.py` | 脚本注入的异常 |

三者形状**互不校验**。这正是 `U-119` 那个病的同型（"喂进闸门的形状没人被迫对齐"），
只是发生在 exec 这条缝上。
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any, Final, Protocol, runtime_checkable

from app.core.contracts import IdentityContext, ResultSet

__all__ = [
    "ExplainPlan",
    "ExecutorSeam",
    "EXPLAIN_CALL_FACE",
    "FETCH_CALL_FACE",
    "declared_call_face_mismatches",
]

#: `EXPLAIN (FORMAT JSON)` 的解析结果（psycopg 解析后的 json 载荷）。
#:
#: - `list[dict[str, Any]]` = 正常计划：单元素列表，`[0]` 是计划文档（`{"Plan": {...}}`）；
#: - `None` = **该方言不支持** `EXPLAIN (FORMAT JSON)`（SQLite 评测沙箱，07 §17.4）。
#:
#: 🔴 两种"拿不到计划"是**两条不同语义**，不得混：
#:
#: | 表达 | 含义 | gate3 结论 |
#: |---|---|---|
#: | 返回 `None` | 这个方言**没有**这个能力 | `SKIPPED`（"不可用 ≠ 通过"，§14.2 D6） |
#: | 抛异常 | 有这个能力、但**本次** EXPLAIN 失败 | `WARN`（`explain_error`，§14.2 D5，**不阻断**） |
#:
#: 把前者写成异常 ⇒ 沙箱里的 gate3 从 `SKIPPED` 变成 `WARN`（多出一条"闸门故障"告警，
#: 而实际是"这个方言没这个能力"）；把后者写成 `None` ⇒ 真数据库的 EXPLAIN 故障被记成
#: "方言不支持" ⇒ **闸门故障被静默成能力缺失**（比前者更坏）。
ExplainPlan = list[dict[str, Any]] | None

#: `fetch` 的**必需**调用面 —— 图形参（`app/graph/nodes/execute.py`）。
#: ⚠️ `effective_limit` 是**端口没有**、而图真的在传的关键字：替身漏了它 = `TypeError`。
FETCH_CALL_FACE: Final[tuple[str, ...]] = (
    "sql",
    "params",
    "ctx",
    "max_rows",
    "statement_timeout_ms",
    "effective_limit",
)

#: `explain` 的**必需**调用面 —— 图形参（`app/graph/nodes/gate3_cost.py`，U-63）。
EXPLAIN_CALL_FACE: Final[tuple[str, ...]] = ("sql", "params", "ctx", "statement_timeout_ms")


@runtime_checkable
class ExecutorSeam(Protocol):
    """`GraphDeps.executor` 的**实际调用面**（= 端口 ∪ 图多用的两处）。

    ⚠️ 为什么不是直接检查 `SqlExecutorPort`：端口少两样图真的在用的东西 ——
    `fetch` 的 `effective_limit`（07 §7.3 的生效 LIMIT）与 `explain`（U-63）。
    `isinstance(x, SqlExecutorPort)` 对"两样都缺"的替身**仍为真**。

    ⚠️ `runtime_checkable` 的 `isinstance` **只查属性存在**，不查签名 ⇒ 签名漂移要
    用 `declared_call_face_mismatches()` 补一刀。两者都不查返回类型。
    """

    async def fetch(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        statement_timeout_ms: int,
        effective_limit: int | None = None,
    ) -> ResultSet: ...

    async def explain(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        statement_timeout_ms: int,
    ) -> ExplainPlan: ...


def declared_call_face_mismatches(candidate: Any) -> tuple[str, ...]:
    """候选实现与声明的调用面的差异（空元组 = 对齐）。

    查三件**机械可查**的事，不查语义：

    1. 方法存在且**是** `async def`（同步实现会在 `await` 处炸，且信息量很低）；
    2. 声明面里的**每个**参数名都能被 `inspect.signature` 看到；
    3. `effective_limit` 之外的参数**没有默认值**（有默认值 = 调用方以为在传、实现其实在忽略）。

    ⚠️ **不查**：返回类型、参数类型、`*args/**kwargs` 的展开（`__call__` 转发实现会被
    判为"缺参数"—— 那类实现请自行 `cast`，本函数刻意不做启发式猜测）。

    用途：契约/单元测试对**替身**跑一遍 —— 这样"抄错签名"从"跑到那一行才炸"变成
    "立判据时当场红"。
    """
    problems: list[str] = []
    for method_name, face in (("fetch", FETCH_CALL_FACE), ("explain", EXPLAIN_CALL_FACE)):
        method = getattr(candidate, method_name, None)
        if method is None:
            problems.append(f"缺方法 {method_name}")
            continue
        if not inspect.iscoroutinefunction(method):
            problems.append(f"{method_name} 不是 async def")
            continue
        try:
            params = inspect.signature(method).parameters
        except (TypeError, ValueError):  # pragma: no cover - C 实现/内建才有
            problems.append(f"{method_name} 签名不可读（inspect 拿不到）")
            continue
        # `self` 在绑定方法上已去掉；这里按名字判断即可。
        for name in face:
            if name not in params:
                problems.append(f"{method_name} 缺参数 {name}")
        for name, param in params.items():
            if name in ("self",) or name in face:
                continue
            if param.default is inspect.Parameter.empty and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                problems.append(f"{method_name} 多出无默认值的参数 {name}")
    return tuple(problems)
