"""CommerceQL 后端包：受控执行 + 结果类型归一化（N-05 脱敏边界）。

层号：L2｜归属窗口：W2D（docs/08 §4.1 文件归属权表）。
（阶段 0 的「只允许 docstring」约束已随 W2D 开工解除；实现落在子模块，本文件只做再导出。）

⚠️ 本包是**业务查询的唯一执行出口**（N-02，analytics 池 / `app_ro`）；
结果离开本包前必须已完成类型归一化（07 §8.4）与脱敏（N-05 / §8.7）。
"""

from app.exec.errors import (
    EXEC_ERROR_CLASSES,
    LLM_HINT_BY_CLASS,
    REPAIRABLE_CLASSES,
    ExecError,
    ExecFailure,
    classify_pg_error,
)
from app.exec.executor import FETCH_SIZE, WORK_MEM, PgSqlExecutor
from app.exec.fingerprint import result_fingerprint
from app.exec.normalize import normalize_cell, normalize_row

__all__ = [
    "EXEC_ERROR_CLASSES",
    "FETCH_SIZE",
    "LLM_HINT_BY_CLASS",
    "REPAIRABLE_CLASSES",
    "WORK_MEM",
    "ExecError",
    "ExecFailure",
    "PgSqlExecutor",
    "classify_pg_error",
    "normalize_cell",
    "normalize_row",
    "result_fingerprint",
]
