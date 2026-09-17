"""严格 JSON 提取、schema 校验与"修复 1 次"降级 —— 07 §10.3 的「JSON 输出与修复」。

归属窗口：W3B（docs/08 §4.1）｜层号：L3

## 一、为什么这件事**必须**在调用方（而不是网关）

`app/llm` 的 `LlmGateway.call` 返回的 `text` 是**未经解析的 JSON 字符串**
（W3A 的门面 docstring 与 `RELAY.md §给 W3B/W3C-5` 明确划界：网关是 L1，不认识业务 schema）。
⇒ 解析、schema 校验、修复重试、以及"修不好之后怎么办"全在本模块。

## 二、修复策略（**Q2 已裁**，逐条说明代价）

07 §10.3：`校验失败 → 修复重试 1 次（把校验错误摘要回灌）；再失败 → 降级（不是直接 500）`。

但"把校验错误摘要回灌"**结构上做不到对每个 task 都成立** —— 实测：

| 资产 | USER 段是否渲染 `$error_digest` |
|---|---|
| `repair_v1.txt` | ✅ 有 |
| `gen_sql_v1.txt` / `gen_sql_complex_v1.txt` | ❌ **无**（只有 question / constraints / few_shots） |
| `plan_v1.txt` / `intent_v1.txt` / `normalize_v1.txt` / `normalize_intent_v1.txt` | ❌ **无** |

⇒ 裁定（用户 2026-09-17 采纳建议）：

| 失败的任务 | 修复轮次怎么走 | 代价 |
|---|---|---|
| `gen_sql` / `gen_sql_complex` | 改走 **`repair` 任务**（它的资产有 `$error_digest`），把 `error_digest` 当**槽位**用 | ⚠️ `repair` 的 SYSTEM 文案假设"上一次生成的是 SQL"，用在**首轮就没产出 SQL** 的场景上是**槽位复用**而非语义吻合。已在 `DELIVERY.md` 具名登记 |
| `plan` / `normalize` / `intent` / `normalize_intent` | **同 task 重发**，**不带**错误摘要（无处可放） | ⚠️ 第二次成功率仅靠"再摇一次"，比带摘要的方案弱。已在 `RELAY.md §给 W3A` 提需求：给这三个资产补 `$error_digest` |

**不自己往 `constraints` 里塞校验错误**：`constraints` 是"附加约束/计划块"的槽位，
把校验错误混进去会让"这块文本是什么"变得不可推断 —— 而 `constraints` 在 `gen_sql` 里
承载的正是**计划**。槽位语义一旦糊掉，后续窗口无法安全地改它。

## 三、错误摘要**禁含值**（与 N-11/N-12 同源）

Pydantic 的 `ValidationError.errors()` 每条都带 `input` —— **那里就是模型回显的原值**，
对 `gen_sql` 而言它可能是一段 SQL，对其它任务可能是用户问题片段。
⇒ 本模块的摘要**只取 `loc` / `type` / `msg` 三个字段**，绝不含 `input`。
（`msg` 是 Pydantic 的固定模板文案，不含具体值 —— 这一点由测试用"含 SQL 的非法输入"钉住。）
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from pydantic import BaseModel, ValidationError

__all__ = [
    "JsonAttempt",
    "extract_json_object",
    "first_json_object",
    "validation_digest",
]

_ModelT = TypeVar("_ModelT", bound=BaseModel)

#: 代码围栏（```json ... ``` / ``` ... ```）—— 资产明令禁止，但模型仍会犯。
#: 这属于**格式噪声**，不是内容错误：剥掉即可，不必浪费一次修复重试。
_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*```[a-zA-Z]*\s*(.*?)\s*```\s*$", re.DOTALL)

#: 摘要的单条错误长度上限（防止某条错误自带上千字）。
_MAX_ONE_ERROR_CHARS: Final[int] = 200


@dataclass(frozen=True, slots=True)
class JsonAttempt:
    """一次"取 JSON + 校验"的结果。

    `error_digest` 为 `None` 表示**成功**；否则是可直接进 `error_digest` 槽位的脱敏摘要
    （禁含 SQL、≤ 调用方给的上限）。
    """

    parsed: BaseModel | None
    error_digest: str | None

    @property
    def ok(self) -> bool:
        return self.parsed is not None


def first_json_object(text: str) -> tuple[str | None, str | None]:
    """从模型输出里取出**第一个平衡的 JSON 对象**的字面量。

    返回 `(json_text, failure_reason)`，二者恰有一个非 None。

    为什么要自己扫括号而不是 `re.search(r"\\{.*\\}")`：贪婪正则会在
    `{"a": {"b": 1}} 后面还有一段解释` 这种文本上吃到最后一个 `}`，
    于是**把尾随解释也吞进 JSON**，`json.loads` 报的错就与真实问题无关了 ——
    而那个错误的摘要会被回灌给模型，形成一次注定失败的修复。
    平衡扫描同时正确处理**字符串内的括号与转义**（否则 `{"s": "}"}` 会提前收尾）。
    """
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1)

    start = text.find("{")
    if start < 0:
        return None, "输出里没有任何 JSON 对象（找不到 `{`）"

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1], None

    return None, "JSON 对象未闭合（`{` 之后没有找到配对的 `}`）"


def extract_json_object(text: str) -> tuple[Mapping[str, Any] | None, str | None]:
    """`first_json_object` + `json.loads`。顶层必须是**对象**（不是数组/标量）。"""
    literal, reason = first_json_object(text or "")
    if literal is None:
        return None, reason
    try:
        obj = json.loads(literal)
    except json.JSONDecodeError as exc:
        # ⚠️ 只报位置与原因，**不回显原文**（原文可能含 SQL / 用户输入片段）。
        return None, f"JSON 解析失败（line {exc.lineno} col {exc.colno}：{exc.msg}）"
    if not isinstance(obj, Mapping):
        return None, f"顶层必须是 JSON 对象，实际是 {type(obj).__name__}"
    return obj, None


def validation_digest(
    failure: BaseModel | ValidationError | str,
    *,
    limit: int,
) -> str:
    """把一次失败渲染成**可回灌的脱敏摘要**。

    `limit` = `MAX_ERROR_DIGEST_CHARS`（1000）。超限时按"先给错误清单、再给提示"的顺序
    截断 —— 因为错误清单比提示更有信息量；截断本身会写明有多少条未列出（不静默丢）。
    """
    if isinstance(failure, str):
        body = failure
    elif isinstance(failure, ValidationError):
        body = _render_validation_error(failure)
    else:
        # 模型构造期由 `model_validator` 抛的 `ValueError`（本模块的"要么给主体要么给原因"断言）
        body = f"- 结构校验未通过：{failure}"

    prefix = "上一次输出未通过校验，原因如下（**请只修正这些问题，不要改动其余内容**）：\n"
    text = prefix + body
    if len(text) <= limit:
        return text

    room = max(limit - len(prefix) - 40, 0)
    return (
        prefix
        + body[:room]
        + f"\n…（摘要已截断：原始错误摘要超出 {limit} 字符上限）"
    )[:limit]


def _render_validation_error(exc: ValidationError) -> str:
    """逐条渲染 `loc / type / msg`。

    🔴 **故意不取 `err["input"]`**：那是模型回显的原值（对 gen_sql 而言可能就是一段 SQL）。
    本函数的输出会被回灌进 prompt，因此它自己必须先是一个"合法出站内容"。
    """
    lines: list[str] = []
    dropped = 0
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "(根)"
        kind = str(err.get("type", "unknown"))
        msg = str(err.get("msg", "")).replace("\n", " ")[:_MAX_ONE_ERROR_CHARS]
        lines.append(f"- 字段 `{loc}`：{msg}（类型：{kind}）")
        if len(lines) >= 40:  # 上限 40 条 —— 再多也不是"摘要"了
            dropped = len(exc.errors()) - len(lines)
            break
    if dropped:
        lines.append(f"- …另有 {dropped} 条同类错误未列出")
    return "\n".join(lines) if lines else "- 结构校验未通过（无具体错误项）"
