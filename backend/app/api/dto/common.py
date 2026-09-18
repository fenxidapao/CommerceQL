"""DTO 公共件 —— 统一响应封套（附录 A §A.0.4）。

层号：L5｜归属窗口：W4（`app/api/dto/**` 的归属见模块 docstring 末节）。

⚠️ **本模块不做任何业务判定**：它只定义"响应长什么样"。
错误码到 HTTP 的映射唯一入口是 `app/api/errors.py`（07 §3.2），不在这里。

⚠️ **`code` 与 HTTP 状态是两条独立的通道**（附录 A §A.11 + W5 RELAY §1.6）：
W5 明文"`2xx` 但 `code !== 'OK'` 前端按**错误**处理" ⇒ 成功响应必须 `code="OK"`，
且**不得**用 `code` 承载业务子状态（例如"部分成功"）。业务子状态一律进 `data`。

--------------------------------------------------------------------------
归属登记（`app/api/dto/**` 是"§08 §4.1 归属权表未登记"的目录之一）
--------------------------------------------------------------------------
`docs/08 §4.1` 的归属表只写了 `app/api/errors.py` / `app/api/sse.py` / `app/api/routers/**`。
`dto/**` 未登记。W1B 在 `app/api/deps.py` 文件头把 `dto/**` 与 `deps.py`/`ratelimit.py`
一起登记为"清单外必需文件（Q-15 同类）"并"待架构窗口裁定"。

W4 接管它的**理由不是"顺手"**，而是 `app/graph/edges.py` 的文件内注释已经指明：
`_ASYNC_THRESHOLD_KEY` / `_ASYNC_IF_SLOW_KEY` 的键名"**待与附录 A §A.1.1 的 `RunOptions` 对账
（T5 落 `api/dto/` 时钉死）**" —— 即 W4 自己留的对账点。故本目录归 W4，
并有 `tests/contract/test_api_dto_contract.py` 钉住"两处键名逐字相同"。
若架构裁定它归他窗口，应整体移交并**删除本目录**，不得两边各留一份（U-18）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ErrorEnvelope", "OkEnvelope", "PageData", "PagedEnvelope"]


class OkEnvelope[T](BaseModel):
    """成功响应封套（附录 A §A.0.4）。"""

    model_config = ConfigDict(extra="forbid")

    code: str = "OK"
    message: str = "success"
    trace_id: str | None = None
    data: T
    server_time: str | None = None


class ErrorEnvelope(BaseModel):
    """错误响应封套 —— **唯一**的错误响应形状（附录 A §A.0.4 + §A.12 的 `detail`）。

    ⚠️ 它由**全局异常处理器**（`app/api/errors.py::install_exception_handlers`）统一产出，
    端点**不得**自己构造错误响应：两处构造会让"哪个码带 `Retry-After`"出现第二个判据
    （`HttpErrorMapping.headers()` 是唯一判据）。
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    trace_id: str | None = None
    detail: dict[str, Any] | None = None
    suggestions: list[str] | None = None
    server_time: str | None = None


class PageData[T](BaseModel):
    """分页数据（附录 A §A.0.5）。"""

    items: list[T]
    total: int
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    has_more: bool = False


class PagedEnvelope[T](BaseModel):
    """分页响应（与 `OkEnvelope` 同形，`data` 换成 `PageData`）。

    ⚠️ 保留独立类而**不**用 `OkEnvelope[PageData[T]]` —— 但理由已与初版不同：
    初版担心"泛型嵌套退化成 `Any`，从而丢掉 `items` 的类型检查"。该担心在
    **PEP 695 语法下不成立**（本窗口实测：`Alias = OkEnvelope[PageData[int]]` 后
    `env.data.total` 仍被 mypy 判为 `int`，`warn_return_any` 未报错）。
    保留它的真实理由是**语义**：分页响应的 `data` **恒为** `PageData`，独立类让
    端点签名（`-> PagedEnvelope[MetricItem]`）自解释，且将来要加分页专属字段
    （如 `next_cursor`）时只有一处要改。
    """
    model_config = ConfigDict(extra="forbid")

    code: str = "OK"
    message: str = "success"
    trace_id: str | None = None
    data: PageData[T]
    server_time: str | None = None
