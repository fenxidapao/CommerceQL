"""反馈端点 DTO（附录 A §A.6）。

层号：L5｜归属窗口：W4。

⚠️ **`reason_code` 用 `core.enums.FeedbackReasonCode`，本文件不另写 `Literal[...]`。**
枚举自己的 docstring 已经把理由立成规矩：`app/core/enums.py` 是**取值集唯一真相**
（08 §4.1 / 07 §4.2 断言⑤）。API 层再写一份 = 第二份取值集，两处漂移时
（枚举侧加值、DTO 侧漏加）表现为"契约文档说支持、端点返回 **400 `INVALID_REQUEST`**"，
而**没有任何测试会红** —— 这类不一致只在联调期以"文档说行、代码不行"的形式暴露。

⚠️ `queue_for_review` 的口径**不在本文件**（而是 `routers/feedback.py`）：
它是端点的判定，DTO 只负责"响应长什么样"。

⚠️ 与 `dto/session.py` 的差别（**不是遗漏**）：本端点**没有** `extra="forbid"` 的
"空请求体"问题 —— §A.6 的请求体是有字段的，`extra="forbid"` 拦的是"多传了未知字段"
（客户端把 `taskId` 写成驼峰就会得到 **400** 而不是静默丢弃那个字段）。

⚠️ 状态码是 **400**（`INVALID_REQUEST`）而不是 FastAPI 默认的 422：
`api/errors.py` 统一把 `RequestValidationError` 映射成 400。
（`CLARIFY_INVALID_OPTION` 的 422 是**另一回事** —— 那是领域错误码 `§A.4` 明文的 422，
不是请求体校验失败。）
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import FeedbackReasonCode

__all__ = ["FeedbackData", "FeedbackRequest"]


class FeedbackRequest(BaseModel):
    """`POST /feedback` 的请求体（附录 A §A.6）。

    | 字段 | 必填 | 约束来源 |
    |---|---|---|
    | `task_id` | ✅ | `min_length=1`：空字符串不是"某个任务"，它就是"没给任务" |
    | `is_correct` | ✅ | `bool`；**落库前**拦 `1` 的是 `FeedbackStore.insert_feedback` 的 `isinstance` |
    | `reason_code` | ⭕ | 枚举（见模块 docstring） |
    | `comment` / `corrected_sql` / `correct_result_hint` | ⭕ | 自由文本，§A.6 未给长度上限 ⇒ **不发明**上限 |

    ⚠️ `is_correct` 刻意用 pydantic 的**默认**（非 strict）bool 而不是 `StrictBool`：
    全仓 DTO 没有第二处用 `Strict*`（加一处就是给契约面引入孤立约定），
    而"传 `1` 必须被拒"的权威闸门在 `FeedbackStore`（W1B 要件⑤ 的落点，
    `tests/integration/test_feedback_store_pg.py::test_is_correct_must_be_bool`）。
    两处职责不同：DTO 管 JSON 形态，store 管**落库前的 Python 形态**。

    ⚠️ `task_id` 只做**语法**校验（非空），**不做存在性校验** —— §A.6 没有给
    "反馈一个不存在的 task_id"任何错误码，而擅自加 404 会让"任务状态已过期被清理、
    用户仍想反馈"这条**合法**路径变成错误。存在性不属于本端点的契约。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    is_correct: bool
    reason_code: FeedbackReasonCode | None = None
    comment: str | None = None
    corrected_sql: str | None = None
    correct_result_hint: str | None = None


class FeedbackData(BaseModel):
    """`POST /feedback` 的 `data`（附录 A §A.6 明文两字段）。

    ⚠️ 只有这两个键 —— §A.6 的响应示例是
    `{ "code": "OK", "data": { "feedback_id": "fb_01J8X7", "queued_for_review": true } }`。
    **不得**顺手回传 `reason_code` / `task_id`：那会让"响应 = 请求的回声"，
    而 §A.6 的响应面是**结果**（新 id + 是否入池），不是回执单。
    """

    model_config = ConfigDict(extra="forbid")

    feedback_id: str
    queued_for_review: bool
