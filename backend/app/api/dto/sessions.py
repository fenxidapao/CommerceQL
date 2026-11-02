"""会话列表/关闭 DTO 骨架（Phase B B1；端点由 B4 接）。

层号：L5｜归属窗口：Phase B B1。

契约逐字对齐附录 A：
- 列表 = §A.5.4（`items` / `total` / `limit` / `offset` / `has_more`）；
- 关闭 = §A.5.3（`{session_id, closed}`）。

⚠️ 列表只返回**元数据**，不返回轮次明细；`title` 由服务端生成，客户端不可写
（§A.5.4 的 B-19 修订，与 `dto/session.py` 同一立场）。
⚠️ `tenant_id`/`user_id` 不是查询参数：服务端从 JWT 取并强制过滤。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["CloseSessionData", "SessionListData", "SessionSummary"]


class SessionSummary(BaseModel):
    """§A.5.4 的单条会话元数据。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str
    turn_count: int
    last_turn_at: str
    created_at: str
    last_bundle_version: str


class SessionListData(BaseModel):
    """§A.5.4 的分页壳（`total` 是过滤后的总数，与 `items` 长度分开）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[SessionSummary]
    total: int
    limit: int
    offset: int
    has_more: bool


class CloseSessionData(BaseModel):
    """§A.5.3 的 `data`。软关闭，幂等。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    closed: bool
