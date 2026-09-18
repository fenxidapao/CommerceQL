"""接入层领域异常 —— 端点**只抛这些**，HTTP 码由 `app/api/errors.py` 查表决定。

层号：L5｜归属窗口：W4。

--------------------------------------------------------------------------
一、为什么需要这个文件（"清单外必需文件"登记，同 `state_store.py` 的理由）
--------------------------------------------------------------------------
`docs/08 §3.1` 的落地清单里没有它。没有它会怎样：六个码
（`TASK_NOT_FOUND` / `SESSION_NOT_FOUND` / `TASK_NOT_CANCELLABLE` /
`IDEMPOTENCY_CONFLICT` / `CLARIFY_EXPIRED` / `CLARIFY_INVALID_OPTION`）
会在四个 router 里各写一遍 —— 于是**同一个码会有四份 `message` 与四份 `detail` 形状**，
而前端按码做文案映射时看到的是"同一种错误，四种提示"。

`app/core/errors.py` **不放它们**（那是 W0 域、且放的是"可跨层抛出的领域异常"）：
这六个码全部**只在 HTTP 边界上有意义** —— 图内部（L1–L4）不知道 `task_id` 的 HTTP 语义，
也不该知道。判据与 `deps.py::RateLimited` 完全相同（那里已就"入口限流是接入层概念"立过规矩）。

⚠️ 若架构窗口裁定它们该收进 `core/errors.py`，本文件应**整体迁走**，不得两边各留一份（U-18）。

--------------------------------------------------------------------------
二、这里**不做**的事
--------------------------------------------------------------------------
- **不决定 HTTP 状态**：`ERROR_HTTP_STATUS` 是唯一判据，本文件连 `status` 字段都没有。
- **不带 Retry-After / suggestions**：那也是 `errors.py` 查表的事。这六个码全在 `❌` 档
  （`RetryableTier.NONE`）⇒ 既无倒计时也无改法建议；`validate()` 会因为"多给了"而抛错。
- **`message` 不得含内部细节**（N-11）：库里原文、规则号、路径一律不进这里
  （`detail` 只放**用户可理解**的结构化补充，且要过 `errors.detail_allowed_for(role)` 才下发）。
"""

from __future__ import annotations

from app.core.errors import CommerceQLError

__all__ = [
    "ClarifyExpired",
    "ClarifyInvalidOption",
    "IdempotencyConflict",
    "InvalidRequest",
    "SessionNotFound",
    "TaskNotFound",
    "TaskNotCancellable",
]


class InvalidRequest(CommerceQLError):
    """请求**形状**合法但取值越界（附录 A §A.11 的 400）。

    ⚠️ 与 DTO 的 `RequestValidationError` 分工不同：那个由 FastAPI 在**进入端点之前**
    抛出（字段缺失、类型错、`extra="forbid"` 命中），码同样是 `INVALID_REQUEST`；
    本异常用于**端点内部**才能判定的越界（例如"澄清补充并入原问题后超过 500 字"）——
    那是**跨字段/跨对象**的约束，DTO 层看不见。
    两者最终映射到同一个码，故前端无需区分。
    """

    default_code = "INVALID_REQUEST"


class TaskNotFound(CommerceQLError):
    """`GET /query/{task_id}` 与 `cancel` 的 404（附录 A §A.2 / §A.3）。

    ⚠️ **"不存在"与"不属于你"共用这一个异常**（`state_store` 的所有权校验返回 `None`）：
    区分它们会让攻击者用 404/403 的差异枚举出"哪些 `task_id` 真实存在"。
    附录 A §A.11 的 404 语义本来就是"不存在或已过期"，两者同形是**契约要求的**。
    """

    default_code = "TASK_NOT_FOUND"


class TaskNotCancellable(CommerceQLError):
    """任务已进入终态，不可取消（附录 A §A.3 的 409）。

    ⚠️ 这不是错误路径上的"意外"：用户点「停止」时这一轮常常刚好跑完。
    故文案必须是**中性**的（W5 RELAY §1.2 明确"前端有专门中性文案"）——
    不得写成"取消失败"，那会让用户以为系统出问题。
    """

    default_code = "TASK_NOT_CANCELLABLE"


class SessionNotFound(CommerceQLError):
    """会话不存在 / 不属于本租户（附录 A §A.5.2 的 404）。"""

    default_code = "SESSION_NOT_FOUND"


class IdempotencyConflict(CommerceQLError):
    """同一 `Idempotency-Key` 对应不同请求体（附录 A §A.12 的 409）。

    ⚠️ `detail` 只放 `original_task_id`（§A.12 的响应示例逐字）——
    不放请求体、不放哈希：那些对用户没有可用价值，却会把"用户问过什么"回灌进响应。
    """

    default_code = "IDEMPOTENCY_CONFLICT"


class ClarifyExpired(CommerceQLError):
    """澄清上下文不存在或已过期（附录 A §A.4 的 410）。

    ⚠️ 两种情形**同码同形**（附录 A §A.13：有效期 5 分钟）：
    "从来没存在过"与"存在过但过期了"对用户是同一件事 —— 都是"得重新问一遍"。
    区分它们需要区分"键不存在"与"键被 TTL 删除"，而 Redis 不提供这个信息（也不该提供）。
    """

    default_code = "CLARIFY_EXPIRED"


class ClarifyInvalidOption(CommerceQLError):
    """`selected_value` 不在澄清上下文给出的选项里（附录 A §A.4 的 422）。

    ⚠️ 与 `INVALID_REQUEST`（请求**形状**错，400）是两件事：
    本异常的前提是"形状合法、值不在上下文里"，归因方向是**上下文过期或被篡改**，
    而形状错归因于前端 bug。附录 A 给了两个码就是要求区分（见 `dto/clarify.py`）。
    """

    default_code = "CLARIFY_INVALID_OPTION"


def task_not_found(task_id: str) -> TaskNotFound:
    """`TaskNotFound` 的统一构造（`detail` 形状只此一处）。

    ⚠️ `detail` 里**回显 `task_id` 是刻意的**：它是用户自己持有的标识，
    回显让"我查的是哪个任务"在联调期可自证；而**所有权失败时也一样回显**——
    回显与否不泄露任何东西（用户本来就知道自己传了什么）。
    """
    return TaskNotFound("任务不存在或已过期", detail={"task_id": task_id})
