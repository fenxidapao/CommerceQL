"""exec 入口形态 —— 再导出层 + 实现侧运行期检查器（U-122 收敛后的形态）。

层号：L2｜归属窗口：W2D（`docs/08 §4.1`：`app/exec/**`）。

--------------------------------------------------------------------------
一、本文件现在是什么（W0 `aa494f6` 端口面补齐之后）
--------------------------------------------------------------------------
端口面补齐前，本文件曾自带 `ExplainPlan` 定义与 `ExecutorSeam` 协议 —— 那是
"图真正调用的面 > 端口声明的面"（`effective_limit` + `explain` 两处越过端口、
`deps_of() -> Any` 与 `rich_method` 两层都不检查）那道缝的**临时声明层**，
全案 = `07 §4.8` 的 `U-122`（`reports/arch/RELAY.md` §5 → W2D）。

W0 `aa494f6` 把 `effective_limit`（**必填**）与 `explain` 抬进 `SqlExecutorPort`
后，按 `contracts.py:515-517` 的明文指令（"L2 只能再导出本名，不得另立第二份
定义 —— 第二份真相正是本项目明禁的那条"），本文件收敛为三件事：

1. **再导出 `ExplainPlan`**：唯一真相 = `app/core/contracts.py`（"返回 `None` =
   方言不支持 → `SKIPPED` / 抛异常 = 本次失败 → `WARN`"的两语义表也在那边）；
2. **两个调用面常量 + 运行期签名检查器** `declared_call_face_mismatches`
   （U-122 判据④：替身忠实性，见函数 docstring）；
3. **`ExecutorSeam` = `SqlExecutorPort` 的迁移别名** —— 名字留在本文件
   （架构裁定③：`ExecutorSeam`/`ExplainPlan` 不得搬进 `app/core/`），定义收敛到
   端口。W7 的 deploy/loadtest 引用口径可继续用 `app.exec.seam.ExecutorSeam`；
   **新代码请直接引 `SqlExecutorPort`**。

--------------------------------------------------------------------------
二、⚠️ 两个 face 常量刻意**手写**、不从端口签名推导
--------------------------------------------------------------------------
W4 的 `tests/contract/test_exec_port_face_contract.py`（U-122 判据②，W4 写 / W0 审）
把 `SqlExecutorPort` 的参数名与这两个常量做**等式断言** —— 它能**防回退**，靠的正是
两边**独立**：常量若改成 `inspect.signature` 现场推导，等式恒真，防回退失效。
所以这里保留字面量；端口改脸时必须**同步**改这里，改漏了判据②会红（这正是设计）。
"""

from __future__ import annotations

import inspect
from typing import Any, Final

from app.core.contracts import ExplainPlan, SqlExecutorPort

__all__ = [
    "ExplainPlan",
    "ExecutorSeam",
    "EXPLAIN_CALL_FACE",
    "FETCH_CALL_FACE",
    "declared_call_face_mismatches",
]

#: 迁移别名：唯一真相 = `SqlExecutorPort`（W0 `aa494f6`）。
#: 名字保留是给 W7 的 deploy/loadtest 引用口径与现存测试过渡；新代码直接用端口。
ExecutorSeam = SqlExecutorPort

#: `fetch` 的**必需**调用面 —— 与 `SqlExecutorPort.fetch` 参数名逐字相等
#:（见模块 docstring 第二节：刻意手写、不做推导）。
FETCH_CALL_FACE: Final[tuple[str, ...]] = (
    "sql",
    "params",
    "ctx",
    "max_rows",
    "statement_timeout_ms",
    "effective_limit",
)

#: `explain` 的**必需**调用面 —— 与 `SqlExecutorPort.explain` 参数名逐字相等。
EXPLAIN_CALL_FACE: Final[tuple[str, ...]] = ("sql", "params", "ctx", "statement_timeout_ms")


def declared_call_face_mismatches(candidate: Any) -> tuple[str, ...]:
    """候选实现与声明的调用面的差异（空元组 = 对齐）。

    查三件**机械可查**的事，不查语义：

    1. 方法存在且**是** `async def`（同步实现会在 `await` 处炸，且信息量很低）；
    2. 声明面里的**每个**参数名都能被 `inspect.signature` 看到；
    3. `effective_limit` 之外的参数**没有默认值**（有默认值 = 调用方以为在传、实现其实在忽略；
       `effective_limit` 豁免 —— 端口必填，实现给 `= None` 是"更宽松仍满足声明"的合法形态，
       W0 `aa494f6` docstring 明文）。

    ⚠️ **不查**：返回类型、参数类型、`*args/**kwargs` 的展开（`__call__` 转发实现会被
    判为"缺参数"—— 那类实现请自行 `cast`，本函数刻意不做启发式猜测）。

    用途：契约/单元测试对**替身**跑一遍 —— 这样"抄错签名"从"跑到那一行才炸"变成
    "立判据时当场红"（U-122 判据④：`ScriptExecutor` 必须对齐 + 反向对照证明非空转）。
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
