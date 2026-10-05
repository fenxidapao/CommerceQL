"""`POST /api/v1/admin/eval/run` 的请求 DTO（附录 A §A.9.1）。

层号：L5｜归属窗口：W8（T-37，2026-10-05）。

--------------------------------------------------------------------------
为什么 `dry_run` 是 `Literal[True]`，而不是"默认 True、false 时运行时拒绝"
--------------------------------------------------------------------------
§A.9.1 原文的响应是 `{"run_id": "run_01J8XA", "status": "queued"}` —— 那要求服务端
真能**发起**一次评测。现读盘上缺运行登记表与进程内执行通道（逐条见
`app/present/eval_launch.py::launch_blockers`），所以"真发起"这一支**今天没有实现**。

两种写法只有一种是诚实的：

| 写法 | 后果 |
|---|---|
| 实现了、收到 `dry_run=false` 时抛错 | 需要一个"能力未就绪"的错误码 ⇒ **发明第 29 个码**（`docs/02:1119` 明写"本表是错误码唯一来源"，加一行就是改判据） |
| **schema 面不可表达**（本文件） | `dry_run` 只接受字面 `true` ⇒ 传 `false` 落在 `RequestValidationError` → `400 INVALID_REQUEST`，用的是既有的 28 码之一 |

⚠️ 差别不是洁癖：前者让"发起"在代码面上**存在**，下一个加运行表的人会以为端点已通，
只是被开关挡着；后者让它在代码面上**不存在**，要加就必须先改这个 DTO —— 改动会出现在 diff 里，
而 diff 是本轮唯一能拦住"看起来能用"的地方。

--------------------------------------------------------------------------
`extra="forbid"` 的理由（与 `dto/session.py::CreateSessionRequest` 同源）
--------------------------------------------------------------------------
§A.9.1 的请求体只给了 5 个键。放开 extra 会让客户端多传的键（例如 `max_cases`、
`priority`）**静默失效** —— 联调期表现为"我限了 20 条却按全量报价"，而这类偏差恰好落在
**花钱**那条线上，必须 400 具名拒绝。
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CONTRACT_REQUEST_KEYS", "EvalRunRequest"]

#: §A.9.1 请求体的六个键（`docs/02:829-837` 的 5 个 ＋ 本窗自订的 `dry_run`）。
#: 抄本，由 `tests/contract/test_eval_launch_dryrun_contract.py` 钉住与 DTO 字段集相等。
CONTRACT_REQUEST_KEYS: Final[frozenset[str]] = frozenset(
    {"dataset_id", "model", "prompt_version", "bundle_version", "note", "dry_run"}
)


class EvalRunRequest(BaseModel):
    """`POST /admin/eval/run` 请求体（§A.9.1 ＋ dry-run 开关）。"""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, description="§A.9.2 列出的冻结集 ID")
    model: str | None = Field(default=None, description="报价对应的模型（批次产物不自报，见 model_attribution）")
    prompt_version: str | None = Field(default=None, description="提示词版本")
    bundle_version: str | None = Field(default=None, description="语义包版本")
    note: str | None = Field(default=None, description="备注：只回显、不入库、不参与报价")

    #: 🔴 只接受字面 `true`：理由见模块 docstring 第一节。默认值让"不传"= 预检。
    dry_run: Literal[True] = Field(
        default=True,
        description="本轮唯一可取的取值：只回预检与报价，不发起、不出站",
    )

    def as_echo(self) -> dict[str, Any]:
        """回显给调用方的"你刚才请求了什么"（键序稳定，逐键来自 DTO 本身）。"""
        return self.model_dump()
