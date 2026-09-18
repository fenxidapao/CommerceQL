"""`POST /api/v1/query` 的请求/响应 DTO（附录 A §A.1.1 / §A.2 / §A.3）。

层号：L5｜归属窗口：W4。

--------------------------------------------------------------------------
一、`options` 的键名是**与 `graph/edges.py` 的对账点**，不是自由选择
--------------------------------------------------------------------------
`edges.py::_ASYNC_THRESHOLD_KEY = "async_threshold_ms"` / `_ASYNC_IF_SLOW_KEY = "async_if_slow"`
的注释写着"键名取自 §5.4，**待与附录 A §A.1.1 的 `RunOptions` 对账**（T5 落 `api/dto/` 时钉死）"。
本文件即那次对账的落点，结论是：**两处逐字相同，无需改动任何一方**。
`tests/contract/test_api_dto_contract.py` 钉住这条相等关系 —— 若将来有人改了 DTO 字段名，
边层的转异步判定会**静默恒假**（用户勾了"慢就转异步"却永远不生效），而测试会红。

⚠️ 这也解释了为什么 `options` 用 `snake_case` 而不是驼峰：附录 A §A.1.1 就是 `snake_case`，
而 `edges.py` 读的正是那些字面量键。DTO 层做"驼峰→下划线"的转换等于**在中间插一层命名映射**，
以后每个新选项都要在三个地方同步。

--------------------------------------------------------------------------
二、`max_rows` 的两道限制：契约上限 10000 与调用方默认 5000
--------------------------------------------------------------------------
附录 A §A.1.1 写"默认 5000，上限受服务端硬上限约束（10000）"，
而服务端硬上限的唯一来源是 `Settings.EXEC_MAX_ROWS`（FR-6.7 的同一条约束）。
⇒ DTO 只声明**契约层**的 `le=10000` 作为静态上界，真实硬上限由端点用 `Settings` 二次收敛
（配置调低时 DTO 的静态上界不再生效 —— 那是**配置**说了算，不是常量）。

⚠️ 这里**不**把 `EXEC_MAX_ROWS` import 进 DTO：DTO 是纯形状声明，读配置会让
"import DTO" 变成"需要一个已校验的环境"（而 `get_settings()` 缺项即抛，见 `main.create_app`）。
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import TaskStatus

__all__ = [
    "CHART_PREFERENCES",
    "MAX_QUESTION_LEN",
    "QUERY_MAX_ROWS_CEILING",
    "AskOptions",
    "CancelData",
    "QueryRequest",
    "TaskStatusData",
]


#: 问题长度上限（附录 A §A.1.1："长度 1–500"）。
MAX_QUESTION_LEN: Final[int] = 500

#: `max_rows` 的契约层静态上界（附录 A §A.1.1 的"服务端硬上限 10000"）。
#: ⚠️ 真实上界由端点在运行时用 `Settings.EXEC_MAX_ROWS` 再收敛一次（见模块 docstring §二）。
QUERY_MAX_ROWS_CEILING: Final[int] = 10_000

#: `chart_preference` 的 8 个取值（附录 A §A.1.1，**逐字**）。
CHART_PREFERENCES: Final[frozenset[str]] = frozenset(
    {"auto", "line", "bar", "stacked_bar", "pie", "table", "kpi", "none"}
)


class AskOptions(BaseModel):
    """`options`（附录 A §A.1.1 的八项，默认值逐字对齐）。

    ⚠️ 全部字段都有默认值，且 `QueryRequest.options` 可整体缺省 ——
    附录 A §A.1.1 把它们全标成 ⭕（可选）。前端恒传其中五项（W5 RELAY §1.2），
    但"前端恒传"不是契约，**不得**据此把字段设成必填：那会让 curl/测试/第三方接入
    因为漏一个字段而收到 400（`INVALID_REQUEST`）。
    """

    model_config = ConfigDict(extra="forbid")

    max_candidates: int = Field(default=3, ge=1, le=5)
    allow_clarify: bool = True
    chart_preference: str = "auto"
    timezone: str = "Asia/Shanghai"
    explain: bool = True
    max_rows: int = Field(default=5000, ge=1, le=QUERY_MAX_ROWS_CEILING)
    #: ⚠️ 与 `graph/edges.py::_ASYNC_IF_SLOW_KEY` **逐字相同**（见模块 docstring §一）。
    async_if_slow: bool = True
    #: ⚠️ 与 `graph/edges.py::_ASYNC_THRESHOLD_KEY` **逐字相同**；单位毫秒。
    async_threshold_ms: int = Field(default=8000, ge=1)

    @field_validator("chart_preference")
    @classmethod
    def _known_chart_preference(cls, value: str) -> str:
        if value not in CHART_PREFERENCES:
            raise ValueError(
                f"chart_preference 取值非法：{value!r} —— 合法值只有 8 个：{sorted(CHART_PREFERENCES)}"
            )
        return value

    @field_validator("timezone")
    @classmethod
    def _non_empty_timezone(cls, value: str) -> str:
        # ⚠️ 只校验非空，**不**在这里查 IANA 库：时区解析的唯一入口是语义包的时间口径
        # （N-26：时间基准只来自语义包），在 DTO 里再查一次会让"时区是否可用"有两处判据。
        if not value.strip():
            raise ValueError("timezone 不得为空字符串")
        return value


class QueryRequest(BaseModel):
    """`POST /query` 请求体（附录 A §A.1.1）。"""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LEN)
    session_id: str | None = None
    options: AskOptions | None = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        # ⚠️ `min_length=1` 挡不住全空白串（`"   "`），而它对本产品毫无意义：
        # 归一化后是空问题，LLM 只会给出一段无根据的意图判定。在入口挡掉比让它进图便宜。
        if not value.strip():
            raise ValueError("question 不得为空白")
        return value


class CancelData(BaseModel):
    """`POST /query/{task_id}/cancel` 的 `data`（附录 A §A.3）。"""

    task_id: str
    status: str = TaskStatus.CANCELLED.value


class TaskStatusData(BaseModel):
    """`GET /query/{task_id}` 的 `data`（附录 A §A.2）。

    ⚠️ `status` 的取值集 = `TaskStatus`（**8 值**），且 `status=complete` 才可能带
    `data`/`chart`/`insight`/`meta`。字段集与 SSE 帧"同构"（§A.2 原话），
    故这里用 `dict[str, Any] | None` 而不是重现一套类型 ——
    重现会让"SSE 改了一个字段而轮询没改"变成两处各自漂移。
    """

    task_id: str
    status: str
    stage: str | None = None
    queued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    progress: float | None = None
    sql: str | None = None
    data: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    insight: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    audit_ref: str | None = None
    poll_url: str | None = None
