"""会话端点 DTO（附录 A §A.5.1 / §A.5.2）。

层号：L5｜归属窗口：W4。

⚠️ **`POST /session` 的请求体是空对象，且 `extra="forbid"`** ——
这不是形式主义：附录 A §A.5.1 的 B-19 修订**专门删掉了 `title`**，
理由有三条（服务端才知道首轮的题、客户端可写标题 = XSS/超长攻击面、
前端此刻提供不出有意义的标题）。`extra="forbid"` 让"客户端还在传 `title`"
变成 **422 显式拒绝**，而不是**静默忽略** —— 静默忽略会让联调期变成
"我传了 title 但列表里没有"这种要翻代码才能定位的问题。

⚠️ `GET /session/{id}` **只回计划摘要，不回原始 SQL**（PRD FR-10.1 / 附录 A §A.5.2 原话）。
故 `TurnData` 里**没有 `sql` 字段，且不得加**：加了它，权限变更后这些 SQL
仍是有效的越权模板（跨轮次持久化的可执行语句）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = ["CreateSessionRequest", "SessionCreatedData", "SessionDetailData", "TurnData"]


class CreateSessionRequest(BaseModel):
    """`POST /session` 的请求体 = **空对象**（附录 A §A.5.1）。

    ⚠️ 必须**显式声明**这个类型，哪怕它一个字段都没有 —— 端点若不给请求体参数，
    FastAPI 会**完全不解析 body**：客户端传 `{"title": "..."}` 会得到 `200 OK`
    而不是拒绝。那样 §A.5.1 的 B-19 修订（"不接受 `title`"，理由见模块 docstring）
    就只剩文档里的一句话，实现上完全敞开 —— 而"文档说不行、代码不拦"是最坏的一种不一致：
    联调期前端传了 `title`，看起来也生效了（没人报错），上线后才被当成 XSS 面。
    """

    model_config = ConfigDict(extra="forbid")


class SessionCreatedData(BaseModel):
    """`POST /session` 的 `data`（附录 A §A.5.1）。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    created_at: str


class TurnData(BaseModel):
    """`GET /session/{session_id}` 的单轮（附录 A §A.5.2）。

    ⚠️ `outcome` 是**审计结论**（`core.enums.Outcome` 的 5 值：`success`/`refuse`/
    `clarify`/`degraded`/`failed`），**不是** `TaskStatus` 的 8 值。
    附录 A §A.5.2 的示例给的是 `"outcome": "success"` —— 与 `Outcome` 对齐。
    这两个取值集**不得混用**（`core/enums.py::TaskStatus` 的 docstring 已就此立过规矩）。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    question: str
    outcome: str
    plan_summary: dict[str, Any] | None = None
    at: str


class SessionDetailData(BaseModel):
    """`GET /session/{session_id}` 的 `data`（附录 A §A.5.2）。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    turns: list[TurnData]
    #: 附录 A §A.5.2 的 `context_cursor`。⚠️ **P0 恒 `None`**：
    #: 多轮指代消解需要"历史消息"载体，而 `GraphState` §5.2 的 11 组字段里没有它
    #: （`normalize` 节点已按 `history=()` 调用并登记该缺口）⇒ 没有游标可给。
    #: 如实返回 `None` 而不是编一个 `"tu_1"`（U-22）。
    context_cursor: str | None = None
