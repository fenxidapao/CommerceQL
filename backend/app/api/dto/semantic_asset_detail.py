"""资产详情 DTO 骨架（Phase B B1；端点与投影由 B5 接）。

层号：L5｜归属窗口：Phase B B1。

⚠️ 本 DTO **没有** `sensitive` / `denied_columns` 字段，且**不得添加**：
B5 的投影先用 `runtime.policy()["deny_columns"]` 去掉整列，再由本 DTO 序列化。
把被拒列名放进响应等于把"哪里敏感"告诉调用方（存在性泄露面）。

⚠️ `joins` 只输出语义包允许的已认证路径（包外未列出 = 禁止）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AssetDetailData", "ColumnDetail", "JoinDetail", "MetricRef"]


class ColumnDetail(BaseModel):
    """可展示的列（敏感列由投影层剔除后才进入本模型）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    comment: str | None = None
    unit: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    enum: dict[str, str] = Field(default_factory=dict)
    time_semantics: str | None = None


class JoinDetail(BaseModel):
    """语义包内的已认证 join 路径。"""

    model_config = ConfigDict(extra="forbid")

    left: str
    right: str
    type: str
    on_columns: list[str]
    certified_by: str
    note: str | None = None


class MetricRef(BaseModel):
    """与资产绑定的指标引用（只给标识与展示名，不展开表达式）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str


class AssetDetailData(BaseModel):
    """`GET /semantic/assets/{logical_name}` 的 `data`（B5）。"""

    model_config = ConfigDict(extra="forbid")

    logical_name: str
    physical_asset: str
    grain: str
    domain: str
    owner: str
    certified: bool
    freshness_sla: str
    level: str
    row_estimate: int
    description: str
    columns: list[ColumnDetail]
    joins: list[JoinDetail]
    metrics: list[MetricRef]
