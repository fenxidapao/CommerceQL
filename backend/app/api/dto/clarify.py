"""澄清端点 DTO（附录 A §A.4）。

层号：L5｜归属窗口：W4。

⚠️ **`selected_value` 与 `free_text` 二选一**（附录 A §A.4 的表格：两者都标 ⭕）。
"二选一"是**跨字段**约束，pydantic 的单字段校验表达不了 ⇒ 用 `model_validator(mode="after")`。
把它放在 DTO 而不是端点里，是因为两条错误路径对前端是**不同**的：

| 情形 | 码 | HTTP | 前端动作 |
|---|---|---|---|
| 两个都给 / 都不给 | `INVALID_REQUEST` | 400 | 保留澄清卡 + inline 报错（同 `CLARIFY_INVALID_OPTION` 的处置） |
| 给的选项不在澄清上下文里 | `CLARIFY_INVALID_OPTION` | 422 | 同上 |

⚠️ 混成一条会让"请求形状错"与"选项不合法"无法区分，而归因方向完全不同
（前者是前端 bug，后者是上下文过期或被篡改）—— 附录 A 给了两个码就是要求区分。

⚠️ `free_text` 长度**不在**这里限制：它是自由文本，长度上限归"并入问题后的问题长度"
（`MAX_QUESTION_LEN`）在端点侧统一收敛（见 `routers/clarify.py`）——
在这里再限一个数会让"澄清补充"与"直接提问"有两条不同的长度口径。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = ["ClarifyRequest"]


class ClarifyRequest(BaseModel):
    """`POST /clarify` 请求体（附录 A §A.4）。"""

    model_config = ConfigDict(extra="forbid")

    clarify_id: str
    selected_value: str | None = None
    free_text: str | None = None

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> ClarifyRequest:
        has_selected = self.selected_value is not None and self.selected_value.strip() != ""
        has_free = self.free_text is not None and self.free_text.strip() != ""
        if has_selected == has_free:
            raise ValueError(
                "`selected_value` 与 `free_text` 必须**恰好给一个**（附录 A §A.4）—— "
                "两个都给会让'用户到底选了什么'无法判定，都不给则这次澄清没有输入"
            )
        return self
