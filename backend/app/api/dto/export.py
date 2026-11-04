"""`POST /api/v1/export` 的请求 DTO（附录 A §A.15，Phase B B2）。

层号：L5｜归属窗口：Phase B B2。

--------------------------------------------------------------------------
一、`format` 为什么只放 `csv`，且校验在 DTO 而不是端点
--------------------------------------------------------------------------
P0 唯一的导出格式是 `csv`（`docs/06 §6.8`：图片导出**未做**，登记为偏离）。
把这个约束放在 DTO：非法取值会在**进入端点之前**被 FastAPI 拦成
`400 INVALID_REQUEST`（`api/errors.py` 已统一映射 `RequestValidationError`），
于是端点内部不必再写一遍 `if format != "csv": raise ...` —— 两处判同一个约束，
早晚会有一处被改而另一处忘了。

⚠️ 取值集不写死字面量分支，走 `EXPORT_FORMATS` 一处声明：将来加 `xlsx` 只改这里，
与 `core/enums` 那套「取值集单一真相」的纪律同向（本文件是 L5 形状声明，
不进 `enums.py` —— 它没有跨层语义，不是错误码那类共享取值集）。

--------------------------------------------------------------------------
二、`task_id` 的上下界
--------------------------------------------------------------------------
`min_length=1` 挡空串；`max_length=128` 是**防御性上界**：`task_id` 由服务端
`new_id("task")` 生成（远短于 128），客户端拿它当键查询时给超长串只会在
Redis/日志里造噪声。真实来源仍是服务端，故不在这里做格式正则
—— 那会把「谁生成」这件事在 DTO 里再写一遍。
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["EXPORT_FORMATS", "ExportRequest"]

#: P0 支持的导出格式（`docs/02 §A.15.1` / `docs/06 §6.8`）。
#: ⚠️ 图片**不在**其中：那个产品决策位至今没开，`docs/06 §6.8` 已登记为偏离。
EXPORT_FORMATS: Final[frozenset[str]] = frozenset({"csv"})


class ExportRequest(BaseModel):
    """`POST /export` 请求体（附录 A §A.15.1）。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=128)
    format: str = "csv"

    @field_validator("task_id")
    @classmethod
    def _task_id_not_blank(cls, value: str) -> str:
        # `min_length=1` 挡不住全空白串，而它作为 Redis 键的一部分毫无意义。
        if not value.strip():
            raise ValueError("task_id 不得为空白")
        return value

    @field_validator("format")
    @classmethod
    def _supported_format(cls, value: str) -> str:
        if value not in EXPORT_FORMATS:
            raise ValueError(
                f"format 取值非法：{value!r} —— P0 只支持 {sorted(EXPORT_FORMATS)}"
                "（图片导出未做，见 docs/06 §6.8 的偏离登记）"
            )
        return value
