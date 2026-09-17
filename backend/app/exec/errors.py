"""执行层错误对象 —— `ExecError` 的定义点（graph/state.py 组 8 注明归 W2D，U-24）。

归属窗口：W2D（docs/08 §4.1：`app/exec/**`）。

--------------------------------------------------------------------------------
与 07 §8.9 的对应关系（N-11：原始库错误绝不回灌）
--------------------------------------------------------------------------------

PG 原始错误常含表名、列名、甚至值。本模块是「脱敏摘要」的**唯一生产点**：

| PG 错误类 | `error_class` | 回灌给 LLM（`llm_hint`） | 终态建议（W4 消费） |
|---|---|---|---|
| 42703 | `unknown_column` | "引用了不存在的列（已隐去名称）" | repair |
| 42P01 | `unknown_table` | "引用了不存在的资产" | repair |
| 42804 | `type_mismatch` | "比较或运算的双方类型不一致" | repair |
| 42883 | `unknown_function` | "使用了不存在的函数" | repair |
| 42601 | `syntax_error` | "SQL 语法有误" | repair |
| 57014 | `timeout` | **不回灌**（不可修） | `error(EXEC_TIMEOUT)` |
| 42501 | `permission` | **不回灌**（不可修） | `refuse(out_of_scope)` |
| 连接类 | `db_unavailable` | 不回灌 | `error(DB_UNAVAILABLE)` |

⚠️ **`llm_hint` 只有上表这几句** —— 任何想"把 PG 报错文本修一修再给 LLM"的改动
都是在回灌 schema（N-11）。`pgcode`（如 42703）可以下传：它暴露的是**类别**，
不是对象名（07 §8.9 硬规则：detail 只允许对象名与错误类别）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.core.errors import CommerceQLError

__all__ = [
    "EXEC_ERROR_CLASSES",
    "PGCODE_TO_ERROR_CLASS",
    "LLM_HINT_BY_CLASS",
    "REPAIRABLE_CLASSES",
    "ExecError",
    "ExecFailure",
]


@dataclass(frozen=True, slots=True)
class ExecError:
    """执行失败的脱敏摘要（进 `GraphState.exec_error`；**严禁原始库错误**，N-11）。

    `message` 永远是类别级描述（本模块的常量表），不是 PG 的报错文本。
    """

    error_class: str          # `EXEC_ERROR_CLASSES` 之一
    pgcode: str | None        # PG SQLSTATE（类别可下传；原始消息不进任何字段）
    message: str              # 对用户的类别级文案（已脱敏）
    llm_hint: str | None      # 回灌给 repair 的提示；`None` = 不可修，不回灌


#: error_class 全集 = 07 §8.9 的 8 类 + `resource_exceeded`。
#: ⚠️ `resource_exceeded` 不是 PG 错误（无 SQLSTATE）：它是应用侧资源契约
#: （07 §8.2 内存上限），终态码 `EXEC_RESOURCE_EXCEEDED`（附录 A §A.11 明文：
#: 与 gate3 的 `COST_TOO_HIGH` 层级不同，不得合并）。
EXEC_ERROR_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "unknown_column",
        "unknown_table",
        "type_mismatch",
        "unknown_function",
        "syntax_error",
        "timeout",
        "permission",
        "db_unavailable",
        "resource_exceeded",
    }
)

#: SQLSTATE 前缀/精确码 → error_class（07 §8.9 表逐行）。连接类错误**无 SQLSTATE**，
#: 由 executor 按 `psycopg.OperationalError` / `InterfaceError` 归类。
PGCODE_TO_ERROR_CLASS: Final[dict[str, str]] = {
    "42703": "unknown_column",
    "42P01": "unknown_table",
    "42804": "type_mismatch",
    "42883": "unknown_function",
    "42601": "syntax_error",
    "57014": "timeout",
    "42501": "permission",
}

#: 不可修类（不回灌给 LLM；07 §8.9 表第 3 列"不回灌" + 资源超限）。
#: ⚠️ `resource_exceeded` 不进 repair：它的出路是用户收窄查询（`suggestions[]`），
#: 让 LLM 重写同一类 SQL 必然再超限 —— 与 timeout 同理。
NON_REPAIRABLE: Final[frozenset[str]] = frozenset(
    {"timeout", "permission", "db_unavailable", "resource_exceeded"}
)

#: 可 repair 的类（W4 据此进 repair 循环，上限 `GATE_MAX_REPAIR_ROUNDS`）。
REPAIRABLE_CLASSES: Final[frozenset[str]] = EXEC_ERROR_CLASSES - NON_REPAIRABLE

#: 类别级文案（对用户）；repair 类同时是 `llm_hint`（07 §8.9 第 3 列逐句落位）。
MESSAGES: Final[dict[str, str]] = {
    "unknown_column": "引用了不存在的列（已隐去名称）",
    "unknown_table": "引用了不存在的资产",
    "type_mismatch": "比较或运算的双方类型不一致",
    "unknown_function": "使用了不存在的函数",
    "syntax_error": "SQL 语法有误",
    "timeout": "查询超时，建议收窄时间范围或增加过滤条件",
    "permission": "当前身份无权访问该数据范围",
    "db_unavailable": "数据库暂不可用，请稍后重试",
}

#: 回灌给 LLM 的提示（仅 repair 类有值；不可修类 = None，07 §8.9 第 3 列）。
LLM_HINT_BY_CLASS: Final[dict[str, str | None]] = {
    "unknown_column": MESSAGES["unknown_column"],
    "unknown_table": MESSAGES["unknown_table"],
    "type_mismatch": MESSAGES["type_mismatch"],
    "unknown_function": MESSAGES["unknown_function"],
    "syntax_error": MESSAGES["syntax_error"],
    "timeout": None,
    "permission": None,
    "db_unavailable": None,
}


class ExecFailure(CommerceQLError):
    """执行失败的**唯一**异常形态（executor 只抛这一种业务异常）。

    携带脱敏后的 `ExecError` 摘要；W4 据此分流：
    - `error.error_class ∈ REPAIRABLE_CLASSES` → 进 repair（写 `state["exec_error"]`）；
    - `timeout` → `error(EXEC_TIMEOUT)`；`permission` → `refuse(out_of_scope)`；
    - `db_unavailable` → `error(DB_UNAVAILABLE)`。

    ⚠️ `default_code` 只是**兜底建议**（若 W4 忘记分流，映射层给一个不至于泄露的码）；
    语义上正确的终态以 `error_class` 为准。
    """

    def __init__(self, error: ExecError, *, detail: dict[str, Any] | None = None) -> None:
        fallback = {
        "unknown_column": "SQL_SYNTAX_ERROR",
        "unknown_table": "SQL_SYNTAX_ERROR",
        "type_mismatch": "SQL_SYNTAX_ERROR",
        "unknown_function": "SQL_SYNTAX_ERROR",
        "syntax_error": "SQL_SYNTAX_ERROR",
        "timeout": "EXEC_TIMEOUT",
        "resource_exceeded": "EXEC_RESOURCE_EXCEEDED",
        "db_unavailable": "DB_UNAVAILABLE",
        # permission 刻意不给兜底码：按 07 §8.9 它的终态是 refuse（产品结论），
        # 落到 error 就错了 —— 留 None 让映射层与 W4 都能看见"没分流"。
        "permission": None,
    }[error.error_class]
        super().__init__(error.message, detail={"error_class": error.error_class, **(detail or {})})
        self.error = error
        if fallback is not None:
            self.default_code = fallback


def classify_pg_error(exc: BaseException) -> ExecError:
    """psycopg 异常 → 脱敏 `ExecError`（**唯一**的分类点，N-11）。

    ⚠️ 本函数**从不**读取 `exc.args` / `str(exc)` 进任何产出字段 ——
    那里可能含表名、列名、值。只取 `sqlstate`（类别）。
    """
    pgcode = getattr(exc, "sqlstate", None)
    error_class = PGCODE_TO_ERROR_CLASS.get(pgcode) if pgcode else None
    if error_class is None:
        # 无 SQLSTATE 或未登记的码：连接类 → db_unavailable；其余按 syntax 家族兜底。
        # （未登记码不猜 —— 兜底为 syntax_error 与"5 个 repair 类对用户呈现一致"。）
        import psycopg

        if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
            error_class = "db_unavailable"
        else:
            error_class = "syntax_error"
        pgcode = pgcode if isinstance(pgcode, str) else None
    return ExecError(
        error_class=error_class,
        pgcode=pgcode,
        message=MESSAGES[error_class],
        llm_hint=LLM_HINT_BY_CLASS[error_class],
    )
